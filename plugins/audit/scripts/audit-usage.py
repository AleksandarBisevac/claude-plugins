#!/usr/bin/env python3
"""
`/audit:usage` — token spend, attributed.

THIS SCRIPT RENDERS ITS OWN FINAL OUTPUT. The command file prints stdout verbatim
and is forbidden from re-formatting it. That is deliberate: having the model read a
JSON rollup and lay out a table costs tokens on every invocation, and a usage tool
that is itself expensive is self-defeating. Everything below is plain ASCII — no box
drawing, no ANSI, no emoji — matching the convention the rest of the plugin already
follows so it reads in any terminal.

    audit-usage.py [<manifestPath>] [--by phase|task|model|author|agent|day|hour|
                                          session|branch|attr]
                   [--phase ID] [--task ID] [--model NAME] [--author WHO]
                   [--attr task|phase|window|unattributed]
                   [--since 7d|YYYY-MM-DD] [--until YYYY-MM-DD]
                   [--top N] [--no-cost] [--json]
                   [--backfill] [--project-dir DIR] [--ledger-dir DIR]

With `--by`, one focused table. Without it, the full dashboard.

`--backfill` re-reads every transcript for this project from offset 0 and rebuilds
the affected monthly files. It is the repair path for a lost cursor or a drifted
ledger, and it is idempotent — running it twice leaves identical totals. It is also
the ONLY path that rewrites (and therefore locks); the metering hook only appends.

Exit codes: 0 ok - 2 usage error / unreadable ledger.
"""
import argparse
import json
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, _HERE)
import _loader  # noqa: E402  (the one way scripts/ loads a sibling script as a library)


def _load(name, filename):
    return _loader.load_script(filename, modname=name)


ul = _load("usage_ledger", "usage_ledger.py")
mio = _load("_manifest_io", "_manifest_io.py")

DEFAULT_LEDGER = os.path.join(".claude", "usage")


# --- formatting -----------------------------------------------------------------
def fmt_tokens(n):
    """Compact, right-alignable token counts."""
    n = int(n or 0)
    for limit, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if abs(n) >= limit:
            return "%.1f%s" % (n / float(limit), suffix)
    return str(n)


def fmt_cost(x, show=True):
    if not show:
        return ""
    x = float(x or 0.0)
    if x and abs(x) < 0.01:
        return "<$0.01"          # never render real spend as $0.00
    return "$%.2f" % x


def fmt_int(n):
    return "{:,}".format(int(n or 0))


def bar(fraction, width=18):
    """`[##########........]` — a share bar that survives any terminal."""
    try:
        filled = int(round(max(0.0, min(1.0, float(fraction))) * width))
    except (TypeError, ValueError):
        filled = 0
    return "[" + "#" * filled + "." * (width - filled) + "]"


def table(rows, headers, aligns=None, indent="  "):
    """Fixed-width ASCII table. `rows` is a list of string tuples."""
    if not rows:
        return []
    cols = len(headers)
    aligns = aligns or (["<"] + [">"] * (cols - 1))
    widths = [len(h) for h in headers]
    for row in rows:
        for i in range(cols):
            widths[i] = max(widths[i], len(str(row[i])))
    out = [indent + "  ".join(
        ("%-*s" if aligns[i] == "<" else "%*s") % (widths[i], headers[i])
        for i in range(cols)).rstrip()]
    for row in rows:
        out.append(indent + "  ".join(
            ("%-*s" if aligns[i] == "<" else "%*s") % (widths[i], str(row[i]))
            for i in range(cols)).rstrip())
    return out


# --- dates ----------------------------------------------------------------------
_REL_RE = re.compile(r"^(\d+)\s*([dwm])$", re.I)


def resolve_since(value, now=None):
    """`7d` / `2w` / `3m` / `YYYY-MM-DD` -> `YYYY-MM-DD`. None passes through."""
    if not value:
        return None
    m = _REL_RE.match(str(value).strip())
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        days = n * {"d": 1, "w": 7, "m": 30}[unit]
        t = (now if now is not None else time.time()) - days * 86400
        g = time.gmtime(t)
        return "%04d-%02d-%02d" % (g.tm_year, g.tm_mon, g.tm_mday)
    return str(value).strip()[:10]


def today(now=None):
    g = time.gmtime(now if now is not None else time.time())
    return "%04d-%02d-%02d" % (g.tm_year, g.tm_mon, g.tm_mday)


# --- ledger location ------------------------------------------------------------
def resolve_project(args):
    return os.path.abspath(
        args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


DEFAULT_MANIFEST_REL = os.path.join("docs", "audit", "audit-plan.json")


def resolve_manifest_path(args, project):
    """`<manifestPath argument>` > config `manifestPath` > `docs/audit/audit-plan.json`.

    The middle term is the one that was missing, and its absence was not cosmetic.
    This resolved the default location and nothing else, so a project keeping its
    manifest anywhere else loaded NO manifest — and then read every project value
    off `{}`. The shipped example is exactly that project: its config sets
    `"manifestPath": "audit-plan.json"` and says in its own comment why. So
    `/audit:usage` there ignored `meta.usage` entirely, including
    **`showCost: false`** — a repo that had asked for dollars to stay off the
    screen got them printed anyway, which is the failure the setting exists to
    prevent. `panel-server.py` has always resolved it this way; this is that.

    The manifest stays the commands' source for project values and the config is
    read for one key only. That does not cross the standing manifest/hooks split
    — finding the manifest is not the same act as reading it.
    """
    if args.manifest:
        return args.manifest
    rel = None
    try:
        with open(os.path.join(project, ".claude", "audit.config.json"),
                  encoding="utf-8") as fh:
            cfg = json.load(fh)
        if isinstance(cfg, dict) and isinstance(cfg.get("manifestPath"), str):
            rel = cfg["manifestPath"]
    except Exception:
        rel = None                    # unreadable or malformed: fall through, never raise
    for cand in (rel, DEFAULT_MANIFEST_REL):
        if not cand:
            continue
        p = os.path.normpath(os.path.join(project, cand))
        if os.path.isfile(p):
            return p
    return None


def resolve_ledger(args, project, manifest):
    """`--ledger-dir` > manifest `meta.usage.ledgerDir` > `.claude/usage`.

    The manifest is the commands' source for project values (the hooks read their
    own copy from `.claude/audit.config.json`) — the plugin's standing split."""
    if args.ledger_dir:
        return os.path.abspath(args.ledger_dir)
    rel = DEFAULT_LEDGER
    try:
        meta_usage = ((manifest or {}).get("meta") or {}).get("usage") or {}
        if isinstance(meta_usage, dict) and meta_usage.get("ledgerDir"):
            rel = meta_usage["ledgerDir"]
    except Exception:
        pass
    # When a manifest was named, search upward from IT — pointing at another
    # project's manifest from this cwd must not silently read this project's spend.
    if args.manifest and not args.project_dir \
            and not os.environ.get("CLAUDE_PROJECT_DIR"):
        found = ul.find_ledger_dir(args.manifest, rel)
        if found:
            return found
    return os.path.join(project, rel)


def load_manifest(path):
    if not path:
        return {}
    try:
        return mio.load_manifest_safe(path)
    except Exception:
        return {}


def titles_of(manifest):
    """(phase id -> title, task id -> title) for labelling rows."""
    phases, tasks = {}, {}
    for ph in ((manifest or {}).get("phases") or []):
        if not isinstance(ph, dict):
            continue
        if ph.get("id"):
            phases[ph["id"]] = ph.get("title") or ""
        for t in (ph.get("tasks") or []):
            if isinstance(t, dict) and t.get("id"):
                tasks[t["id"]] = t.get("title") or ""
    return phases, tasks


# --- filtering ------------------------------------------------------------------
def apply_filters(rows, args):
    def keep(row):
        if args.phase and row.get("phaseId") != args.phase:
            return False
        if args.task and row.get("taskId") != args.task:
            return False
        if args.model and args.model not in (row.get("model") or ""):
            return False
        if args.author and args.author not in (row.get("author") or ""):
            return False
        if args.attr and row.get("attr") != args.attr:
            return False
        return True
    return [r for r in rows if keep(r)]


# --- rendering ------------------------------------------------------------------
def render(rows, args, manifest, window, show_cost):
    phase_titles, task_titles = titles_of(manifest)
    tot = ul.totals(rows)
    repo = next((r.get("repo") for r in rows if r.get("repo")), "-")
    out = []

    out.append("USAGE  repo %s   window %s" % (repo, window))
    out.append("")
    head = "  Total   %s tokens" % fmt_tokens(tot["tokens"])
    if show_cost:
        head += "   ~%s equiv" % fmt_cost(tot["costUSD"])
    head += "   %s msgs   %s sessions" % (fmt_int(tot["msgs"]), tot["sessions"])
    if tot["authors"] > 1:
        head += "   %d authors" % tot["authors"]
    out.append(head)
    out.append("          in %s - out %s - cache write %s - cache read %s   "
               "(cache hit %.0f%%)" % (
                   fmt_tokens(tot["in"]), fmt_tokens(tot["out"]),
                   fmt_tokens(tot["cacheW5m"] + tot["cacheW1h"]),
                   fmt_tokens(tot["cacheR"]), tot["cacheHitPct"]))
    # The rate table behind every dollar above. This is the third surface of the
    # same gap: the JSON payload has carried `pricingAsOf` all along and the
    # terminal printed a cost with no basis at all, exactly as the HTML report did
    # before 0.22.0. There is no fallback to the default table's date here either
    # — see render-report._usage_context for why manufacturing one is worse than
    # admitting the manifest never declared it.
    if show_cost and rows:
        as_of = ((((manifest or {}).get("meta") or {}).get("usage") or {})
                 .get("pricingAsOf"))
        out.append("          costs priced at %s" % (
            "rates as of %s" % as_of if as_of
            else "undated rates - set usage.pricingAsOf"))
    if not rows:
        out.append("")
        out.append("  No usage recorded for this window.")
        out.append("  Metering starts once the plugin's hooks have run at least "
                   "one turn; `/audit:usage --backfill` reads existing transcripts.")
        return "\n".join(out)

    def label_for(by, key):
        if by == "phase":
            return ("%-4s %s" % (key, phase_titles.get(key, ""))).rstrip() \
                if key != "--" else "--   unattributed"
        if by == "task":
            return ("%-7s %s" % (key, task_titles.get(key, ""))).rstrip() \
                if key != "--" else "--      (no task)"
        return key

    def group_table(by, title, limit=None, extra=None):
        agg = ul.aggregate(rows, by)
        if not agg:
            return []
        items = sorted(agg.items(), key=lambda kv: -kv[1]["tokens"])
        if limit:
            items = items[:limit]
        grand = tot["tokens"] or 1
        headers = [title, "tokens"]
        aligns = ["<", ">"]
        if show_cost:
            headers.append("cost")
            aligns.append(">")
        headers += ["msgs", "share"]
        aligns += [">", "<"]
        if extra:
            headers.append(extra[0])
            aligns.append("<")
        body = []
        for key, v in items:
            row = [label_for(by, key), fmt_tokens(v["tokens"])]
            if show_cost:
                row.append(fmt_cost(v["costUSD"]))
            share = 100.0 * v["tokens"] / grand
            # A visible slice must never print as 0% — that reads as "free".
            pct = "<1%" if 0 < share < 1 else "%.0f%%" % share
            row += [fmt_int(v["msgs"]),
                    "%s %4s" % (bar(v["tokens"] / float(grand)), pct)]
            if extra:
                row.append(extra[1](key, v))
            body.append(tuple(row))
        return [""] + table(body, headers, aligns)

    if args.by:
        out += group_table(args.by, args.by.upper(), limit=args.top)
        return "\n".join(out)

    out += group_table("phase", "BY PHASE")
    if ul.aggregate(rows, "author") and tot["authors"] > 0:
        out += group_table("author", "BY AUTHOR")
    out += group_table("model", "BY MODEL")
    out += group_table("agent", "BY AGENT")
    tasks_agg = ul.aggregate(rows, "task")
    if [k for k in tasks_agg if k != "--"]:
        # Same derivation the report uses: commands read project values from the
        # manifest, hooks read .claude/audit.config.json.
        meta_usage = ((manifest or {}).get("meta") or {}).get("usage") or {}
        bands = ul.cost_bands(manifest, rows,
                              meta_usage if isinstance(meta_usage, dict) else {})
        if bands.get("sufficient"):
            out += group_table("task", "TOP TASKS", limit=args.top,
                               extra=("band", lambda k, v:
                                      (bands["byTask"].get(k) or "-")))
        else:
            out += group_table("task", "TOP TASKS", limit=args.top)
        out.append("")
        out.append("  " + band_note(bands))
        out += routing_advice_lines(
            ul.routing(manifest, rows,
                       (meta_usage or {}).get("pricing")).get("advice") or [])
    out += render_trend(rows)
    return "\n".join(out)


def routing_advice_lines(advice):
    """The one recommendation the CLI makes. Silent unless the ledger's own
    evidence clears every gate — which on a well-routed project is normal."""
    if not advice:
        return []
    out = ["", "  WHAT THE EVIDENCE SUPPORTS"]
    for a in advice:
        out.append("  %s work is running on %s - %d task(s) at %.1f mean attempts"
                   % (a["risk"], a["from"], a["tasks"], a["fromMeanAttempts"] or 0))
        out.append("    those same tokens cost %s at %s rates vs %s  ->  %s less (%.0f%%)"
                   % (fmt_cost(a["atToRates"]), a["to"],
                      fmt_cost(a["atFromRates"]), fmt_cost(a["saving"]),
                      a["savingPct"]))
        out.append("    %s has already run %d task(s) in this band here, at %.1f "
                   "mean attempts" % (a["to"], a["evidenceTasks"],
                                      a["evidenceAttempts"] or 0))
    out.append("  upper bound, not a forecast: the same tokens re-priced at the "
               "other model's rates")
    return out


def band_note(bands):
    """One line saying where the band thresholds came from, or why there are none.

    "This task is an outlier" is a claim, and a claim whose basis is invisible
    cannot be checked. On a young project this line is the entire content: it says
    the band is waiting for a sample rather than leaving a blank column."""
    if not bands.get("sufficient"):
        return ("band: not calibrated yet - needs %d completed tasks, there are %d "
                "(or set usage.bands.highUSD / outlierUSD for a fixed budget)"
                % (bands.get("gate", 5), bands.get("sample", 0)))
    return ("band: %s - typical <= %s, high <= %s, outlier above"
            % ("configured thresholds" if bands.get("basis") == "absolute"
               else "this project's completed tasks (median / p90)",
               fmt_cost(bands.get("high")), fmt_cost(bands.get("outlier"))))


def render_trend(rows, width=28):
    """Daily column chart plus the peak/quiet read the trend is actually for."""
    daily = ul.aggregate(rows, "day")
    days = sorted(k for k in daily if k != "unknown")
    if not days:
        return []
    out = ["", "  TREND  daily tokens"]
    peak = max(daily[d]["tokens"] for d in days) or 1
    for d in days[-30:]:
        n = daily[d]["tokens"]
        marker = "   peak %s" % fmt_tokens(n) if n == peak else ""
        out.append("  %s  %s%s" % (
            d[5:], "#" * max(1 if n else 0, int(round(width * n / float(peak)))),
            marker))

    hourly = {}
    for row in rows:
        h = ul.bucket_hour(row.get("ts"))
        if h is None:
            continue
        hourly[h] = hourly.get(h, 0) + sum(
            int(row.get(k) or 0) for k in ul.TOKEN_KEYS)
    bits = []
    if hourly:
        busiest = max(hourly, key=lambda h: hourly[h])
        quietest = min(hourly, key=lambda h: hourly[h])
        bits.append("peak hour %02d:00-%02d:00" % (busiest, (busiest + 1) % 24))
        bits.append("quietest %02d:00" % quietest)
    delta = _trend_delta(daily, days)
    if delta is not None:
        bits.append("last 7 active days %+.0f%% vs prior 7" % delta)
    if bits:
        out.append("  " + " - ".join(bits))
    return out


def _trend_delta(daily, days):
    """Percent change over the last 7 days THAT HAVE DATA vs the 7 before them.
    Deliberately not calendar days: on a sparse ledger those differ, and calling
    it "last 7d" would overclaim. None when there is no prior period to compare
    against (a fabricated 'up 100%' helps nobody)."""
    last = days[-7:]
    prior = days[-14:-7]
    if not prior:
        return None
    a = sum(daily[d]["tokens"] for d in last)
    b = sum(daily[d]["tokens"] for d in prior)
    if not b:
        return None
    return 100.0 * (a - b) / b


# --- backfill -------------------------------------------------------------------
def project_slug_candidates(project):
    """Claude Code stores transcripts under a slugified absolute path. The observed
    scheme replaces path separators with '-'; the looser variant is a fallback for
    paths containing characters the strict form leaves alone."""
    p = os.path.abspath(project)
    strict = p.replace(os.sep, "-").replace("/", "-")
    loose = re.sub(r"[^A-Za-z0-9]", "-", p)
    return [s for s in dict.fromkeys([strict, loose]) if s]


def find_transcripts(project, explicit=None):
    """Main-session transcript paths for this project (subagents are discovered
    from each main transcript by usage_ledger.scan_transcripts)."""
    if explicit:
        base = os.path.abspath(explicit)
        return sorted(p for p in _jsonl_in(base))
    home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude")
    for slug in project_slug_candidates(project):
        base = os.path.join(home, "projects", slug)
        if os.path.isdir(base):
            return sorted(_jsonl_in(base))
    return []


def _jsonl_in(base):
    try:
        return [os.path.join(base, n) for n in os.listdir(base)
                if n.endswith(".jsonl") and os.path.isfile(os.path.join(base, n))]
    except OSError:
        return []


def _lockmod():
    """audit-lock.py, loaded by path (hyphenated filename)."""
    return _loader.load_script("audit-lock.py", modname="audit_lock", cache=False)


def acquire_lock(ledger_dir, project):
    """Backfill rewrites monthly files, so it locks; the hook only appends and never
    does. Shares audit-lock.py's verdict rather than re-deriving it — a backfill
    that crashed used to keep the next one out for the rest of the hour, and the
    lock file said nothing about who held it. Unlike the orchestrator's locks this
    one is held by THIS process, so os.getpid() is the pid that belongs in it."""
    import platform
    lock = _lockmod()
    lock_dir = lock.lock_dir(project) or ledger_dir
    path = os.path.join(lock_dir, "usage.lock")
    try:
        os.makedirs(lock_dir, exist_ok=True)
    except Exception:
        return None, "cannot create lock directory %s" % lock_dir
    if os.path.exists(path):
        live, basis = lock.judge(lock.read_lock(path), path)
        if live:
            return None, ("another usage backfill is running (%s) — %s"
                          % (path, basis))
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"hostname": platform.node(),
                       "pid": os.getpid(),
                       "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                  time.gmtime()),
                       "note": "usage backfill"}, fh)
    except Exception as exc:
        return None, "cannot write lock: %s" % exc
    return path, None


def backfill(args, project, ledger_dir, manifest, pricing):
    """Re-scan every transcript from offset 0 and rebuild the affected months.

    Rows carry `sessionId`, so a rebuild drops exactly the sessions it re-reads and
    keeps everything else — which is what makes running it twice a no-op."""
    transcripts = find_transcripts(project, args.transcript_dir)
    if not transcripts:
        return 2, ("no transcripts found for %s\n"
                   "  looked under %s/projects/<slug>; pass --transcript-dir to "
                   "point at them explicitly." % (
                       project, os.environ.get("CLAUDE_CONFIG_DIR")
                       or os.path.join(os.path.expanduser("~"), ".claude")))

    lock, err = acquire_lock(ledger_dir, project)
    if err:
        return 2, err
    try:
        fresh, sessions, cursors = [], set(), {}
        for path in transcripts:
            sid = os.path.splitext(os.path.basename(path))[0]
            rows, cursor = ul.scan_transcripts(
                path, sid, {"author": ul.resolve_author(project, args.author_mode)},
                manifest,
                {"repo": os.path.basename(project) or "repo", "pricing": pricing,
                 "backfillOnFirstRun": True, "maxScanBytes": float("inf")})
            fresh += rows
            cursors[sid] = cursor
            sessions.add(sid)

        existing = ul.read_ledger(ledger_dir)
        months = {ul.bucket_month(r.get("ts")) for r in fresh}
        months |= {ul.bucket_month(r.get("ts")) for r in existing
                   if r.get("sessionId") in sessions}
        for month in sorted(m for m in months if m and m != "unknown"):
            keep = [r for r in existing
                    if ul.bucket_month(r.get("ts")) == month
                    and r.get("sessionId") not in sessions]
            add = [r for r in fresh if ul.bucket_month(r.get("ts")) == month]
            ul.rewrite_month(ledger_dir, month, keep + add)
        for sid, cursor in cursors.items():
            ul.save_cursor(ledger_dir, sid, cursor)
    finally:
        if lock:
            try:
                os.remove(lock)
            except OSError:
                pass

    tot = ul.totals(fresh)
    return 0, ("[OK] backfill: %d transcript(s), %d session(s), %s rows, "
               "%s tokens\n     ledger %s" % (
                   len(transcripts), len(sessions), fmt_int(len(fresh)),
                   fmt_tokens(tot["tokens"]), ledger_dir))


# --- main -----------------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(
        prog="audit-usage.py", add_help=True,
        description="Token spend for this project, attributed by phase/task/"
                    "model/author.")
    p.add_argument("manifest", nargs="?", default=None,
                   help="manifest path (for phase/task titles and meta.usage)")
    p.add_argument("--by", choices=sorted(ul.GROUP_KEYS), default=None,
                   help="render a single grouped table instead of the dashboard")
    p.add_argument("--phase")
    p.add_argument("--task")
    p.add_argument("--model")
    p.add_argument("--author")
    p.add_argument("--attr", choices=["task", "phase", "window", "unattributed"])
    p.add_argument("--since", default=None, help="7d | 2w | 3m | YYYY-MM-DD")
    p.add_argument("--until", default=None, help="YYYY-MM-DD")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--no-cost", action="store_true",
                   help="tokens only; omit equivalent cost")
    p.add_argument("--json", action="store_true", dest="as_json")
    p.add_argument("--backfill", action="store_true",
                   help="re-scan all transcripts and rebuild the ledger")
    p.add_argument("--author-mode", default="email",
                   choices=["email", "name", "hash", "none"],
                   help="author attribution for --backfill")
    p.add_argument("--project-dir", default=None)
    p.add_argument("--ledger-dir", default=None)
    p.add_argument("--transcript-dir", default=None,
                   help="override transcript discovery for --backfill")
    return p


def main(argv):
    args = build_parser().parse_args(argv)
    project = resolve_project(args)
    manifest_path = resolve_manifest_path(args, project)
    manifest = load_manifest(manifest_path)
    ledger_dir = resolve_ledger(args, project, manifest)

    meta_usage = ((manifest or {}).get("meta") or {}).get("usage") or {}
    show_cost = not args.no_cost and bool(
        meta_usage.get("showCost", True) if isinstance(meta_usage, dict) else True)

    if args.backfill:
        code, message = backfill(args, project, ledger_dir, manifest,
                                 meta_usage.get("pricing"))
        (sys.stdout if code == 0 else sys.stderr).write(message + "\n")
        return code

    since = resolve_since(args.since)
    rows = apply_filters(ul.read_ledger(ledger_dir, since, args.until), args)
    window = "all time" if not (since or args.until) else "%s -> %s" % (
        since or "start", args.until or today())

    if args.as_json:
        payload = {
            "window": {"since": since, "until": args.until},
            "ledgerDir": ledger_dir,
            "pricingAsOf": meta_usage.get("pricingAsOf"),
            "totals": ul.totals(rows),
            "byPhase": ul.aggregate(rows, "phase"),
            "byTask": ul.aggregate(rows, "task"),
            "byModel": ul.aggregate(rows, "model"),
            "byAuthor": ul.aggregate(rows, "author"),
            "byAgent": ul.aggregate(rows, "agent"),
            "byDay": ul.aggregate(rows, "day"),
            "byAttribution": ul.aggregate(rows, "attr"),
            "heatmap": ul.heatmap(rows),
            "bands": ul.cost_bands(
                manifest, rows, meta_usage if isinstance(meta_usage, dict) else {}),
            "routing": ul.routing(manifest, rows, meta_usage.get("pricing")),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(render(rows, args, manifest, window, show_cost))
    return 0


# --- selftest -------------------------------------------------------------------
def _selftest():
    import shutil
    import tempfile

    cases = []

    def check(label, ok, detail=""):
        cases.append((label, bool(ok), detail))

    # "This task is an outlier" is a claim; a claim whose basis is invisible
    # cannot be checked. Both branches must name their basis or their shortfall.
    check("band note: an active band states basis AND thresholds",
          "median / p90" in band_note(
              {"sufficient": True, "basis": "relative", "high": 5.59,
               "outlier": 35.4})
          and "$5.59" in band_note(
              {"sufficient": True, "basis": "relative", "high": 5.59,
               "outlier": 35.4}))
    check("band note: an absolute basis does not claim a percentile",
          "configured thresholds" in band_note(
              {"sufficient": True, "basis": "absolute", "high": 15, "outlier": 50}))
    check("band note: below the gate it says what is missing and how to opt out",
          band_note({"sufficient": False, "gate": 5, "sample": 4})
          == "band: not calibrated yet - needs 5 completed tasks, there are 4 "
             "(or set usage.bands.highUSD / outlierUSD for a fixed budget)")

    check("advice: silence when the evidence does not support a move",
          routing_advice_lines([]) == [])
    _al = "\n".join(routing_advice_lines([{
        "risk": "low", "from": "claude-opus-5", "to": "claude-sonnet-5",
        "tasks": 7, "fromMeanAttempts": 1.0, "atFromRates": 157.75,
        "atToRates": 94.65, "saving": 63.10, "savingPct": 40.0,
        "evidenceTasks": 5, "evidenceAttempts": 1.0}]))
    check("advice: the CLI carries the same numbers and the same caveat",
          "$63.10 less (40%)" in _al and "already run 5 task(s)" in _al
          and "upper bound, not a forecast" in _al)

    check("fmt: tokens scale", (fmt_tokens(942) == "942"
                                and fmt_tokens(214_300) == "214.3K"
                                and fmt_tokens(14_700_000) == "14.7M"
                                and fmt_tokens(2_000_000_000) == "2.0B"))
    check("fmt: cost rounds to cents", fmt_cost(42.1789) == "$42.18")
    check("fmt: sub-cent cost does not render as $0.00",
          fmt_cost(0.004) == "<$0.01")
    check("fmt: cost suppressed when disabled", fmt_cost(9.0, show=False) == "")
    check("fmt: bar is fixed width and clamps",
          bar(0.5) == "[#########.........]" and bar(3.0) == "[" + "#" * 18 + "]"
          and bar(-1) == "[" + "." * 18 + "]")
    check("fmt: bar tolerates garbage", bar(None) == "[" + "." * 18 + "]")
    check("fmt: table pads to the widest cell",
          table([("a", "1"), ("bbbb", "22")], ["k", "v"])[1].startswith("  a   "))
    check("fmt: empty table renders nothing", table([], ["k"]) == [])

    now = 1_754_000_000.0        # fixed instant; no wall-clock dependence
    check("since: relative days", resolve_since("7d", now) == resolve_since("7d", now))
    check("since: 7d is 7 days before today",
          resolve_since("7d", now) < today(now))
    check("since: weeks and months resolve",
          resolve_since("2w", now) < resolve_since("7d", now)
          and resolve_since("3m", now) < resolve_since("2w", now))
    check("since: absolute date passes through",
          resolve_since("2026-07-01") == "2026-07-01")
    check("since: None passes through", resolve_since(None) is None)

    # Built for the running platform, and matched as a SUBSTRING. `abspath` on
    # Windows prepends the current drive, so the strict slug is `D:-Users-x-repo`
    # — and `x in [list]` is exact membership, not containment, so the original
    # assertion could only ever pass on POSIX. The function was right; the test
    # was the thing tied to one operating system.
    _slug_path = os.path.abspath(os.path.join(os.sep, "Users", "x", "repo"))
    _slugs = project_slug_candidates(_slug_path)
    check("slug: strict candidate replaces separators",
          "-Users-x-repo" in _slugs[0], repr(_slugs))
    check("slug: no path separator survives in any candidate",
          all(os.sep not in s and "/" not in s for s in _slugs), repr(_slugs))

    tmp = tempfile.mkdtemp(prefix="audit-usage-selftest-")
    try:
        ledger = os.path.join(tmp, "usage")
        rows = []
        for day, task, model, author, out_tok in (
                ("2026-08-01T09", "P1.1", "claude-opus-5", "a@x.io", 1000),
                ("2026-08-01T14", "P1.2", "claude-haiku-4-5", "b@x.io", 500),
                ("2026-08-02T14", "P2.1", "claude-opus-5", "a@x.io", 2000)):
            counts = {"in": 10, "out": out_tok, "cacheW5m": 0, "cacheW1h": 0,
                      "cacheR": 100}
            row = {"ts": day, "author": author, "sessionId": "s-" + task,
                   "agentId": None, "agentType": "audit-executor",
                   "phaseId": task.split(".")[0], "taskId": task, "attr": "task",
                   "model": model, "branch": "audit/x", "repo": "demo", "msgs": 1}
            row.update(counts)
            row["costUSD"] = round(ul.price(counts, model), 6)
            rows.append(row)
        ul.append_rows(ledger, rows)

        manifest = {"meta": {"version": 2, "usage": {"ledgerDir": "usage"}},
                    "phases": [
                        {"id": "P1", "title": "Alpha",
                         "tasks": [{"id": "P1.1", "title": "one"},
                                   {"id": "P1.2", "title": "two"}]},
                        {"id": "P2", "title": "Beta",
                         "tasks": [{"id": "P2.1", "title": "three"}]}]}

        args = build_parser().parse_args([])
        args.ledger_dir = ledger
        loaded = ul.read_ledger(ledger)
        check("render: ledger round-trips through the CLI reader",
              len(loaded) == 3)

        text = render(loaded, args, manifest, "all time", True)
        check("render: header names the repo", "repo demo" in text)
        check("render: phase titles come from the manifest", "Alpha" in text
              and "Beta" in text)
        check("render: task titles surface in TOP TASKS", "three" in text)
        check("render: author section appears when authors differ",
              "BY AUTHOR" in text and "a@x.io" in text)
        check("render: both models listed",
              "claude-opus-5" in text and "claude-haiku-4-5" in text)
        check("render: trend section present", "TREND" in text
              and "peak hour" in text)
        check("render: pure ASCII output", all(ord(c) < 128 for c in text))
        check("render: no ANSI escapes", "\033" not in text)
        check("render: no box-drawing or emoji",
              not any(0x2500 <= ord(c) <= 0x27BF or ord(c) > 0x1F000
                      for c in text))
        check("render: cost shown by default", "equiv" in text)

        # The rate basis, third surface of the gap the HTML report carried until
        # 0.22.0: a cost printed with nothing saying what priced it.
        _mp = json.loads(json.dumps(manifest))
        _mp.setdefault("meta", {}).setdefault("usage", {})["pricingAsOf"] = "2026-08-06"
        _dated = render(loaded, args, _mp, "all time", True)
        check("render: a declared rate date is printed beside the costs",
              "rates as of 2026-08-06" in _dated)
        check("render: with none declared it says so and names the exit, rather "
              "than printing dollars that look pinned to a table nobody named",
              "undated rates" in text and "usage.pricingAsOf" in text)
        check("render: it never falls back to the default table's date - that "
              "would manufacture a basis instead of stating one",
              "rates as of" not in text)

        no_cost = render(loaded, args, manifest, "all time", False)
        check("render: --no-cost drops every dollar figure", "$" not in no_cost)
        check("render: --no-cost drops the rate basis too - with no dollars on "
              "screen it dates a table nothing visible came from",
              "rates" not in no_cost and "undated" not in no_cost)

        empty = render([], args, manifest, "all time", True)
        check("render: empty ledger explains itself, not a traceback",
              "No usage recorded" in empty and "backfill" in empty)
        check("render: and says nothing about rates when there is no spend to "
              "price - a basis announced for a claim never made is noise",
              "rates" not in empty and "undated" not in empty)

        args_by = build_parser().parse_args(["--by", "model"])
        args_by.ledger_dir = ledger
        one = render(loaded, args_by, manifest, "all time", True)
        check("render: --by renders one focused table",
              "MODEL" in one and "BY PHASE" not in one)

        args_f = build_parser().parse_args(["--phase", "P1"])
        check("filter: --phase narrows rows",
              len(apply_filters(loaded, args_f)) == 2)
        args_f = build_parser().parse_args(["--author", "b@x.io"])
        check("filter: --author narrows rows",
              len(apply_filters(loaded, args_f)) == 1)
        args_f = build_parser().parse_args(["--model", "haiku"])
        check("filter: --model matches on substring",
              len(apply_filters(loaded, args_f)) == 1)
        args_f = build_parser().parse_args(["--attr", "unattributed"])
        check("filter: --attr with no matches yields nothing",
              apply_filters(loaded, args_f) == [])

        check("ledger: --since bounds the window",
              len(ul.read_ledger(ledger, since="2026-08-02")) == 1)

        # --- manifest resolution ------------------------------------------------
        # This used to resolve docs/audit/audit-plan.json and nothing else, so a
        # project keeping its manifest elsewhere loaded none and then read every
        # project value off {} - showCost included. The shipped example is exactly
        # that project.
        _mr = os.path.join(tmp, "mres")
        os.makedirs(os.path.join(_mr, ".claude"), exist_ok=True)
        os.makedirs(os.path.join(_mr, "docs", "audit"), exist_ok=True)
        _elsewhere = os.path.join(_mr, "audit-plan.json")
        for _p in (_elsewhere, os.path.join(_mr, "docs", "audit", "audit-plan.json")):
            with open(_p, "w", encoding="utf-8") as fh:
                json.dump({"meta": {}, "phases": [], "bugs": []}, fh)
        _cfgp = os.path.join(_mr, ".claude", "audit.config.json")
        _noargs = build_parser().parse_args([])

        with open(_cfgp, "w", encoding="utf-8") as fh:
            json.dump({"manifestPath": "audit-plan.json"}, fh)
        check("manifest: a configured manifestPath is honoured, not just the "
              "default location",
              resolve_manifest_path(_noargs, _mr) == os.path.normpath(_elsewhere))
        check("manifest: an explicit argument still outranks the config",
              resolve_manifest_path(
                  build_parser().parse_args(["some/other.json"]), _mr)
              == "some/other.json")

        with open(_cfgp, "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        check("manifest: a malformed config falls back instead of raising - the "
              "usage view is read-only and must not die on someone else's typo",
              resolve_manifest_path(_noargs, _mr)
              == os.path.normpath(os.path.join(_mr, DEFAULT_MANIFEST_REL)))
        os.remove(_cfgp)
        check("manifest: no config at all still finds the default location",
              resolve_manifest_path(_noargs, _mr)
              == os.path.normpath(os.path.join(_mr, DEFAULT_MANIFEST_REL)))

        with open(_cfgp, "w", encoding="utf-8") as fh:
            json.dump({"manifestPath": "nowhere/absent.json"}, fh)
        check("manifest: a configured path that does not exist falls back rather "
              "than reporting a file that is not there",
              resolve_manifest_path(_noargs, _mr)
              == os.path.normpath(os.path.join(_mr, DEFAULT_MANIFEST_REL)))
        check("manifest: nothing anywhere -> None, and the caller renders without "
              "project values rather than crashing",
              resolve_manifest_path(_noargs, os.path.join(tmp, "empty-proj")) is None)

        # --json path
        argv = ["--ledger-dir", ledger, "--project-dir", tmp, "--json"]
        import io
        buf, real = io.StringIO(), sys.stdout
        sys.stdout = buf
        try:
            code = main(argv)
        finally:
            sys.stdout = real
        payload = json.loads(buf.getvalue())
        check("json: exits 0", code == 0)
        check("json: totals match the ledger",
              payload["totals"]["out"] == 3500)
        check("json: every grouping present",
              all(k in payload for k in ("byPhase", "byTask", "byModel",
                                         "byAuthor", "byAgent", "byDay",
                                         "byAttribution", "heatmap")))
        check("json: heatmap is 7x24",
              len(payload["heatmap"]) == 7 and len(payload["heatmap"][0]) == 24)

        # backfill on a project with no transcripts must fail cleanly, not crash
        args_b = build_parser().parse_args(["--backfill"])
        args_b.transcript_dir = os.path.join(tmp, "no-such-dir")
        code, msg = backfill(args_b, tmp, ledger, manifest, None)
        check("backfill: missing transcripts -> exit 2 with guidance",
              code == 2 and "--transcript-dir" in msg)

        # The backfill lock. It used to keep the next run out for a full hour
        # after a crash, and the file named nobody — so "delete it if that is
        # stale" was advice the human had no way to act on.
        import platform as _pf
        import subprocess as _sp
        lockdir = os.path.dirname(acquire_lock(ledger, tmp)[0])
        lpath = os.path.join(lockdir, "usage.lock")
        check("lock: acquiring records this process's pid",
              json.load(open(lpath, encoding="utf-8")).get("pid") == os.getpid())
        got, err = acquire_lock(ledger, tmp)
        check("lock: a live backfill blocks the next one",
              got is None and "another usage backfill is running" in (err or ""))
        check("lock: and says on what basis", "pid %d" % os.getpid() in (err or ""))
        dead = _sp.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        with open(lpath, "w", encoding="utf-8") as fh:
            json.dump({"hostname": _pf.node(), "pid": dead.pid,
                       "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                  time.gmtime()),
                       "note": "usage backfill"}, fh)
        got, err = acquire_lock(ledger, tmp)
        check("lock: a crashed backfill does not block for the rest of the hour",
              got is not None and err is None)
        os.unlink(lpath)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for _, ok, _ in cases if ok)
    for label, ok, detail in cases:
        print("%s %s%s" % ("PASS" if ok else "FAIL", label,
                           (" (%s)" % detail) if detail and not ok else ""))
    print("\naudit-usage: %d/%d cases passed" % (passed, len(cases)))
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    raise SystemExit(main(sys.argv[1:]))
