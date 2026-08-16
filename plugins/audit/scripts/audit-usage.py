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
                                          month|session|branch|attr]
                   [--phase ID] [--task ID] [--model NAME] [--author WHO]
                   [--area TAG] [--attr task|phase|window|unattributed]
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
import _fmt  # noqa: E402  (the one token/cost formatter, since P10.6)
import _areas  # noqa: E402  (phase_tags: the read-time area join the ledger receives)
import _cli_fmt  # noqa: E402  (the one place CLI color lives - mode resolution + paint)
import _ui_theme as _theme  # noqa: E402  (the one place a machine value gets its words)


def _load(name, filename):
    return _loader.load_script(filename, modname=name)


ul = _load("usage_ledger", "usage_ledger.py")
mio = _load("_manifest_io", "_manifest_io.py")

DEFAULT_LEDGER = os.path.join(".claude", "usage")


# --- formatting -----------------------------------------------------------------
# Thin re-exports of _fmt.py (the one token/cost formatter — see its docstring for
# the difference table between this CLI's shapes and render-report's). audit-status.py
# now imports _fmt directly for these (P14.2) rather than reaching them through this
# module's loader; these wrappers stay as this CLI's own call shape (and in case any
# other consumer still loads this module for them).
#
# `bar(fraction, width)` used to live here too — the boxed share bar, the copy
# _fmt's docstring names first. It is gone rather than re-exported: it took a
# PRE-DIVIDED fraction, and every caller therefore did the divide itself behind
# a `grand = tot["tokens"] or 1` that turned "there is no total" into a confident
# 0% (and 5-of-0 into 500%). `_fmt.fmt_bar(part, whole, width)` takes the pair so
# the divide happens once, under `share_pct`'s guard. Its golden values are the
# ones frozen from THIS function — see _fmt._selftest's `fmt_bar: golden bar(...)`
# rows — so the pins moved with the code rather than being dropped.
def fmt_tokens(n):
    """Compact, right-alignable token counts (CLI shape: always one decimal)."""
    return _fmt.fmt_tokens(n)


def fmt_cost(x, show=True):
    return _fmt.fmt_cost(x, show=show)


def fmt_int(n):
    return _fmt.fmt_int(n)


def _md_cell(v):
    """A `|` inside a cell is a column break to a markdown parser."""
    return str(v).replace("|", "\\|")


def table(rows, headers, aligns=None, indent="  ", fmt="ascii"):
    """Fixed-width ASCII table, or a markdown pipe table when `fmt` is "md".

    md exists because the /audit:usage command echoes this output verbatim
    into a markdown renderer, where the ASCII shape dies twice: runs of
    spaces fold, and adjacent lines merge into one paragraph. The same
    `aligns` drive both shapes (`>` becomes `---:`)."""
    if not rows:
        return []
    cols = len(headers)
    aligns = aligns or (["<"] + [">"] * (cols - 1))
    if fmt == "md":
        out = ["| " + " | ".join(_md_cell(h) for h in headers) + " |",
               "|" + "|".join("---:" if aligns[i] == ">" else "---"
                              for i in range(cols)) + "|"]
        for row in rows:
            out.append("| " + " | ".join(_md_cell(c) for c in row) + " |")
        return out
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
def apply_filters(rows, args, tags_by_phase=None):
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
    kept = [r for r in rows if keep(r)]
    if getattr(args, "area", None):
        # The SAME join aggregate_area uses (usage_ledger.rows_for_area), so a
        # filtered dashboard and the BY AREA table cannot disagree about which
        # rows an area owns. `--area untagged` selects the untagged bucket.
        kept = ul.rows_for_area(kept, tags_by_phase or {}, args.area)
    return kept


# --- rendering ------------------------------------------------------------------
def render(rows, args, manifest, window, show_cost, pt=None):
    phase_titles, task_titles = titles_of(manifest)
    tot = ul.totals(rows)
    repo = next((r.get("repo") for r in rows if r.get("repo")), "-")
    out = []

    fmt = getattr(args, "format", "ascii") or "ascii"
    md = fmt == "md"
    # `pt` is a _cli_fmt.Painter; None (every pre-color caller) means plain.
    # md NEVER colors regardless of the flag: a markdown surface is not a
    # terminal, and the /audit:usage command echoes this output into a
    # renderer that would print the escapes as garbage.
    if pt is None or md:
        pt = _cli_fmt.PLAIN

    # The md header is a bullet list because markdown merges adjacent plain
    # lines into one paragraph — three aligned lines would render as a blob.
    out.append(("**USAGE**  repo %s - window %s" % (repo, window)) if md
               else pt.paint("USAGE  repo %s   window %s" % (repo, window),
                             "header"))
    out.append("")
    sep = " - " if md else "   "
    head = ("- **Total** %s tokens" if md
            else "  Total   %s tokens") % fmt_tokens(tot["tokens"])
    if show_cost:
        head += sep + "~%s equiv" % fmt_cost(tot["costUSD"])
    head += sep + "%s msgs" % fmt_int(tot["msgs"]) + sep + \
        "%s sessions" % tot["sessions"]
    if tot["authors"] > 1:
        head += sep + "%d authors" % tot["authors"]
    out.append(head)
    out.append(("- " if md else "          ")
               + "in %s - out %s - cache write %s - cache read %s%s"
               "(cache hit %.0f%%)" % (
                   fmt_tokens(tot["in"]), fmt_tokens(tot["out"]),
                   fmt_tokens(tot["cacheW5m"] + tot["cacheW1h"]),
                   fmt_tokens(tot["cacheR"]), " " if md else "   ",
                   tot["cacheHitPct"]))
    # The rate table behind every dollar above. This is the third surface of the
    # same gap: the JSON payload has carried `pricingAsOf` all along and the
    # terminal printed a cost with no basis at all, exactly as the HTML report did
    # before 0.22.0. There is no fallback to the default table's date here either
    # — see render-report._usage_context for why manufacturing one is worse than
    # admitting the manifest never declared it.
    if show_cost and rows:
        as_of = ((((manifest or {}).get("meta") or {}).get("usage") or {})
                 .get("pricingAsOf"))
        out.append(("- " if md else "          ") + "costs priced at %s" % (
            "rates as of %s" % as_of if as_of
            else "undated rates - set usage.pricingAsOf"))
    if not rows:
        out.append("")
        out.append(pt.paint("  No usage recorded for this window.", "warn"))
        out.append("  Metering starts once the plugin's hooks have run at least "
                   "one turn; `/audit:usage --backfill` reads existing transcripts.")
        return "\n".join(out)

    def label_for(by, key):
        # uc (F-P-2): one word for the empty bucket, shared with the report and
        # the panel. It used to be spelled twice here alone ("--   unattributed"
        # and "--      (no task)") and differently again on the other two
        # surfaces; the storage key stays "--" in the ledger and in --attr.
        if key == "--":
            return _theme.UNCATEGORIZED
        if by == "phase":
            return ("%-4s %s" % (key, phase_titles.get(key, ""))).rstrip()
        if by == "task":
            return ("%-7s %s" % (key, task_titles.get(key, ""))).rstrip()
        # `--by attr` groups on the attribution bucket itself, whose "not
        # attributed" member is the SAME fact under its other key.
        return _theme.label(key) if by == "attr" else key

    def group_table(by, title, limit=None, extra=None):
        agg = ul.aggregate(rows, by)
        if not agg:
            return []
        items = sorted(agg.items(), key=lambda kv: -kv[1]["tokens"])
        if limit:
            items = items[:limit]
        # The REAL total, not `... or 1`. That guard did not prevent a bad answer,
        # it manufactured one: a zero total rendered every row's share as "0%",
        # which is indistinguishable from a measured zero. _fmt.share_pct owns the
        # divide now and says "?" when there is nothing to divide by.
        grand = tot["tokens"]
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
            row += [fmt_int(v["msgs"]),
                    "%s %4s" % (_fmt.fmt_bar(v["tokens"], grand),
                                _fmt.fmt_share(v["tokens"], grand))]
            if extra:
                row.append(extra[1](key, v))
            body.append(tuple(row))
        rendered = table(body, headers, aligns, fmt=fmt)
        if rendered and not md:
            rendered[0] = pt.paint(rendered[0], "header")
        return [""] + rendered

    if args.by:
        out += group_table(args.by, args.by.upper(), limit=args.top)
        return "\n".join(out)

    out += group_table("phase", "BY PHASE")
    out += render_by_area(manifest, rows, tot, show_cost, fmt=fmt, pt=pt)
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
        out.append(("" if md else "  ") + pt.paint(band_note(bands), "dim"))
        out += routing_advice_lines(
            ul.routing(manifest, rows,
                       (meta_usage or {}).get("pricing")).get("advice") or [],
            fmt=fmt, pt=pt)
    out += render_monthly(manifest, rows, show_cost, fmt=fmt, pt=pt)
    out += render_trend(rows, fmt=fmt, pt=pt)
    return "\n".join(out)


def render_by_area(manifest, rows, tot, show_cost, fmt="ascii", pt=None):
    """BY AREA table: ledger spend joined to `phase.area` tags at read time
    (usage_ledger.aggregate_area over _areas.phase_tags), rendered only when the
    plan tags anything at all — a project that never wrote an area keeps today's
    dashboard byte for byte.

    A multi-tag phase counts its rows under EACH of its tags, so area rows can
    sum PAST the total line; when such a phase exists the footer says so rather
    than letting the columns quietly disagree with the header. `untagged` (no
    tags, unknown phase, or no phase on the row) always sorts last - it is a
    residue, not an area."""
    tags_by_phase = _areas.phase_tags(manifest)
    if not any(tags_by_phase.values()):
        return []
    agg = ul.aggregate_area(rows, tags_by_phase)
    if not agg:
        return []
    items = sorted(agg.items(),
                   key=lambda kv: (kv[0] == ul.UNTAGGED_AREA, -kv[1]["tokens"]))
    grand = tot["tokens"]       # the real total — see group_table on the `or 1`
    headers = ["BY AREA", "tokens"]
    aligns = ["<", ">"]
    if show_cost:
        headers.append("cost")
        aligns.append(">")
    headers += ["msgs", "phases", "share"]
    aligns += [">", ">", "<"]
    body = []
    for key, v in items:
        row = [key, fmt_tokens(v["tokens"])]
        if show_cost:
            row.append(fmt_cost(v["costUSD"]))
        row += [fmt_int(v["msgs"]), str(v["phases"]),
                "%s %4s" % (_fmt.fmt_bar(v["tokens"], grand),
                            _fmt.fmt_share(v["tokens"], grand))]
        body.append(tuple(row))
    pt = pt or _cli_fmt.PLAIN
    rendered = table(body, headers, aligns, fmt=fmt)
    if rendered and fmt != "md":
        rendered[0] = pt.paint(rendered[0], "header")
    out = [""] + rendered
    if any(len(tags) > 1 for tags in tags_by_phase.values()):
        note = ("a phase tagged with several areas counts under each of "
                "its tags, so area rows can sum past the total")
        out += ["", "*%s*" % note] if fmt == "md" \
            else ["  " + pt.paint(note, "dim")]
    return out


def render_monthly(manifest, rows, show_cost, fmt="ascii", pt=None):
    """Calendar-month table: ledger spend beside plan progress, one row per
    month, from usage_ledger.monthly_activity — the same computation site the
    report table and the panel card read, so the three surfaces cannot drift.

    Rendered only when the rows in view span at least two calendar months: a
    one-month table would restate the totals line. The ledger columns follow
    the CLI filters (they are computed from the filtered rows); the plan
    columns count the whole project by event month, and the footer says so."""
    months_seen = {ul.bucket_month(r.get("ts")) for r in rows} - {"unknown"}
    if len(months_seen) < 2:
        return []
    ma = ul.monthly_activity(manifest, rows)
    if not ma["months"]:
        return []
    headers = ["MONTHLY", "tokens"]
    aligns = ["<", ">"]
    if show_cost:
        headers.append("cost")
        aligns.append(">")
    headers += ["msgs", "tasks done", "bugs", "fixed", "merged"]
    aligns += [">"] * 5
    body = []
    for m in ma["months"]:
        led, plan = ma["ledger"][m], ma["plan"][m]
        row = [m, fmt_tokens(led["tokens"])]
        if show_cost:
            row.append(fmt_cost(led["costUSD"]))
        row += [fmt_int(led["msgs"]), str(plan["tasksCompleted"]),
                str(plan["bugsReported"]), str(plan["bugsFixed"]),
                str(plan["phasesMerged"])]
        body.append(tuple(row))
    pt = pt or _cli_fmt.PLAIN
    rendered = table(body, headers, aligns, fmt=fmt)
    if rendered and fmt != "md":
        rendered[0] = pt.paint(rendered[0], "header")
    out = [""] + rendered
    note = ("plan columns count the whole project by event month (task "
            "completed, bug reported, linked fix task completed, phase "
            "merged) - they do not follow the filters above")
    out += ["", "*%s*" % note] if fmt == "md" \
        else ["  " + pt.paint(note, "dim")]
    return out


def routing_advice_lines(advice, fmt="ascii", pt=None):
    """The one recommendation the CLI makes. Silent unless the ledger's own
    evidence clears every gate — which on a well-routed project is normal.
    md nests the two evidence lines under their advice bullet; markdown
    would otherwise merge all three into one paragraph."""
    if not advice:
        return []
    md = fmt == "md"
    pt = pt or _cli_fmt.PLAIN
    out = ["", "**WHAT THE EVIDENCE SUPPORTS**" if md
           else pt.paint("  WHAT THE EVIDENCE SUPPORTS", "header")]
    if md:
        out.append("")
    for a in advice:
        out.append(("- " if md else "  ")
                   + "%s work is running on %s - %d task(s) at %.1f mean attempts"
                   % (a["risk"], a["from"], a["tasks"], a["fromMeanAttempts"] or 0))
        out.append(("  - " if md else "    ")
                   + "those same tokens cost %s at %s rates vs %s  ->  %s less (%.0f%%)"
                   % (fmt_cost(a["atToRates"]), a["to"],
                      fmt_cost(a["atFromRates"]), fmt_cost(a["saving"]),
                      a["savingPct"]))
        out.append(("  - " if md else "    ")
                   + "%s has already run %d task(s) in this band here, at %.1f "
                   "mean attempts" % (a["to"], a["evidenceTasks"],
                                      a["evidenceAttempts"] or 0))
    caveat = ("upper bound, not a forecast: the same tokens re-priced at the "
              "other model's rates")
    out += ["", "*%s*" % caveat] if md else ["  " + pt.paint(caveat, "dim")]
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


def render_trend(rows, width=28, fmt="ascii", pt=None):
    """Daily column chart plus the peak/quiet read the trend is actually for.
    md renders it as a day/tokens/trend table — a bare `#` column would lose
    its leading alignment in a markdown renderer and the bars would float."""
    daily = ul.aggregate(rows, "day")
    days = sorted(k for k in daily if k != "unknown")
    if not days:
        return []
    md = fmt == "md"
    pt = pt or _cli_fmt.PLAIN
    # The real peak, not `... or 1`. `bar_cells(min_fill=True)` is the sparkline's
    # own arithmetic — a day with real tokens gets at least one cell, a true zero
    # gets none — and it returns 0 cells when there is no peak to measure against.
    # The `peak and` in `_is_peak` is what the `or 1` was silently doing: with a
    # divisor forced to 1, `n == peak` could never hold on an all-zero ledger, so
    # no day was labelled. Naming every zero day "peak 0" would manufacture a
    # high-water mark out of nothing, which is the same defect one line up.
    peak = max(daily[d]["tokens"] for d in days)
    if md:
        out = ["", "**TREND**  daily tokens", ""]
        body = []
        for d in days[-30:]:
            n = daily[d]["tokens"]
            body.append((d[5:], fmt_tokens(n),
                         "#" * _fmt.bar_cells(n, peak, width, min_fill=True)
                         + (" peak" if _is_peak(n, peak) else "")))
        out += table(body, ["day", "tokens", "trend"], ["<", ">", "<"],
                     fmt="md")
    else:
        out = ["", pt.paint("  TREND  daily tokens", "header")]
        for d in days[-30:]:
            n = daily[d]["tokens"]
            marker = "   peak %s" % fmt_tokens(n) if _is_peak(n, peak) else ""
            out.append("  %s  %s%s" % (
                d[5:],
                "#" * _fmt.bar_cells(n, peak, width, min_fill=True),
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
        out += ["", " - ".join(bits)] if md else ["  " + " - ".join(bits)]
    return out


def _is_peak(n, peak):
    """Is this day the trend's high-water mark? A ledger of nothing has none —
    every day ties at zero, and labelling them all "peak 0" would invent a
    measurement, the same way `share = tokens / (total or 1)` invented one."""
    return bool(peak) and n == peak


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
    p.add_argument("--area", default=None,
                   help="only spend whose phase carries this area tag "
                        "('untagged' selects spend no area owns)")
    p.add_argument("--attr", choices=["task", "phase", "window", "unattributed"])
    p.add_argument("--since", default=None, help="7d | 2w | 3m | YYYY-MM-DD")
    p.add_argument("--until", default=None, help="YYYY-MM-DD")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--format", choices=["ascii", "md"], default="ascii",
                   help="md renders pipe tables and bullets for surfaces that "
                        "display markdown (the /audit:usage command passes it); "
                        "ascii is the terminal/pipe shape")
    p.add_argument("--color", choices=list(_cli_fmt.MODES), default="auto",
                   help="ANSI color for the ascii render (auto colors only a "
                        "TTY and respects NO_COLOR; --format md and --json "
                        "never color)")
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
    tags_by_phase = _areas.phase_tags(manifest)
    rows = apply_filters(ul.read_ledger(ledger_dir, since, args.until), args,
                         tags_by_phase)
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
            "byMonth": ul.aggregate(rows, "month"),
            "byArea": ul.aggregate_area(rows, tags_by_phase),
            "byAttribution": ul.aggregate(rows, "attr"),
            "heatmap": ul.heatmap(rows),
            "monthly": ul.monthly_activity(manifest, rows),
            "bands": ul.cost_bands(
                manifest, rows, meta_usage if isinstance(meta_usage, dict) else {}),
            "routing": ul.routing(manifest, rows, meta_usage.get("pricing")),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(render(rows, args, manifest, window, show_cost,
                 pt=_cli_fmt.painter(args.color)))
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
    # The two `bar(fraction)` unit cases that used to sit here are gone with the
    # function. Their golden values were frozen INTO _fmt's suite before either
    # call site moved (`fmt_bar: golden bar(0.5, 18)`, the over-100% clamp, the
    # negative clamp), so the pins relocated rather than being dropped — and this
    # file now pins the thing it actually owns instead: the rendered share cell,
    # which unit-testing `bar` never exercised. See the (sb) block below.
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
        # uc (F-P-2): a row with no phase and no task is ordinary — ad-hoc
        # edits, `#no-plan`, work outside the plan — and it used to print as
        # the ledger's storage key ("--   unattributed", "--      (no task)"),
        # three spellings of one fact across three surfaces. The word now comes
        # from the shared label map, so the CLI, the report and the panel say
        # the same thing.
        _uc_rows = list(loaded) + [dict(loaded[0], phaseId=None, taskId=None,
                                        attr="unattributed",
                                        sessionId="s-adhoc")]
        _uc_text = render(_uc_rows, args, manifest, "all time", True)
        check("uc: spend with no phase/task is named from the shared label map, "
              "and the storage key never reaches the terminal",
              _theme.UNCATEGORIZED in _uc_text
              and "unattributed" not in _uc_text
              and "(no task)" not in _uc_text)
        _args_attr = build_parser().parse_args(["--by", "attr"])
        _args_attr.ledger_dir = ledger
        _uc_attr = render(_uc_rows, _args_attr, manifest, "all time", True)
        check("uc: ...including the attribution table itself, where the bucket "
              "IS the row - the CLI's own `--attr unattributed` selector is "
              "untouched, because a flag is typed, not read",
              _theme.UNCATEGORIZED in _uc_attr
              and "unattributed" not in _uc_attr
              and "task" in _uc_attr.lower())

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

        # --- month bucket (mo) ----------------------------------------------
        check("mo1 --by month is a legal choice, derived from GROUP_KEYS",
              "month" in ul.GROUP_KEYS
              and build_parser().parse_args(["--by", "month"]).by == "month")
        args_mo = build_parser().parse_args(["--by", "month"])
        args_mo.ledger_dir = ledger
        mo_text = render(loaded, args_mo, manifest, "all time", True)
        check("mo2 --by month renders one focused monthly table",
              "MONTH" in mo_text and "2026-08" in mo_text
              and "BY PHASE" not in mo_text)
        check("mo3 the json payload carries byMonth",
              payload.get("byMonth", {}).get("2026-08", {}).get("out") == 3500)

        # --- monthly overview (ma) ------------------------------------------
        check("ma1 a single-month ledger shows no MONTHLY table - one row "
              "would restate the totals line",
              "MONTHLY" not in text)
        check("ma2 the json payload carries the monthly overview even then",
              payload.get("monthly", {}).get("months") == ["2026-08"])
        _l2 = os.path.join(tmp, "usage2")
        _extra = dict(rows[0])
        _extra["ts"] = "2026-07-20T10"
        _extra["sessionId"] = "s-jul"
        ul.append_rows(_l2, rows + [_extra])
        _loaded2 = ul.read_ledger(_l2)
        _man2 = json.loads(json.dumps(manifest))
        _man2["phases"][0]["tasks"][0]["status"] = "done"
        _man2["phases"][0]["tasks"][0]["completedAt"] = "2026-08-01T10:00:00Z"
        _man2["bugs"] = [{"id": "BUG-1", "status": "open",
                          "reportedAt": "2026-07-02T10:00:00Z"}]
        _mtext = render(_loaded2, args, _man2, "all time", True)
        check("ma3 a two-month ledger renders the MONTHLY table with both months",
              "MONTHLY" in _mtext and "2026-07" in _mtext and "2026-08" in _mtext)
        check("ma4 plan columns ride beside the ledger columns",
              "tasks done" in _mtext and "merged" in _mtext)
        check("ma5 the plan columns say they are project-wide and do not follow "
              "the filters",
              "do not follow the filters" in _mtext)
        check("ma6 the monthly table is plain ASCII",
              all(ord(c) < 128 for c in _mtext))
        check("ma7 --no-cost drops the monthly cost column too",
              "cost" not in "\n".join(
                  ln for ln in render(_loaded2, args, _man2, "all time",
                                      False).splitlines()
                  if "MONTHLY" in ln))

        # --- areas (da): read-time join, --area filter, BY AREA table -------
        # Area is a property of the PLAN: the same ledger re-reads differently
        # when a phase is re-tagged, and a project that never wrote an area
        # keeps today's dashboard byte for byte.
        check("da1 a plan with no area tags renders no BY AREA table",
              "BY AREA" not in text)
        _man_a = json.loads(json.dumps(manifest))
        _man_a["phases"][0]["area"] = "backend"
        _man_a["phases"][1]["area"] = ["backend", "web"]
        _atext = render(loaded, args, _man_a, "all time", True)
        check("da2 tagged phases render BY AREA with one row per tag",
              "BY AREA" in _atext and "backend" in _atext and "web" in _atext)
        check("da3 the multi-tag caveat prints exactly when a phase carries "
              "more than one tag - single-tag projects stay quiet",
              "sum past the total" in _atext)
        _man_b = json.loads(json.dumps(manifest))
        _man_b["phases"][0]["area"] = "backend"
        _btext = render(loaded, args, _man_b, "all time", True)
        check("da4 ...and stays silent when no phase is multi-tagged",
              "BY AREA" in _btext and "sum past the total" not in _btext)
        check("da5 spend of an untagged phase lands in an 'untagged' row that "
              "sorts last - a residue, not an area",
              "untagged" in _btext
              and _btext.index("untagged") > _btext.index("backend"))
        check("da6 the BY AREA table is plain ASCII",
              all(ord(c) < 128 for c in _atext))
        _tags_a = _areas.phase_tags(_man_a)
        args_da = build_parser().parse_args(["--area", "backend"])
        check("da7 --area keeps exactly the rows whose phase carries the tag",
              len(apply_filters(loaded, args_da, _tags_a)) == 3
              and len(apply_filters(
                  loaded, build_parser().parse_args(["--area", "web"]),
                  _tags_a)) == 1
              and apply_filters(
                  loaded, build_parser().parse_args(["--area", "nope"]),
                  _tags_a) == [])
        check("da8 --area untagged selects the spend no area owns",
              len(apply_filters(
                  loaded, build_parser().parse_args(["--area", "untagged"]),
                  _areas.phase_tags(_man_b))) == 1)
        check("da9 a no-tag plan's json byArea buckets everything untagged - "
              "an honest shape, not a missing key",
              payload.get("byArea", {}).get("untagged", {}).get("out") == 3500)
        _map = os.path.join(tmp, "area-plan.json")
        with open(_map, "w", encoding="utf-8") as fh:
            json.dump(_man_a, fh)
        buf2, real2 = io.StringIO(), sys.stdout
        sys.stdout = buf2
        try:
            code2 = main([_map, "--ledger-dir", ledger, "--project-dir", tmp,
                          "--json"])
        finally:
            sys.stdout = real2
        payload2 = json.loads(buf2.getvalue())
        check("da10 json byArea joins through the named manifest's tags",
              code2 == 0
              and payload2.get("byArea", {}).get("backend", {}).get("out") == 3500
              and payload2.get("byArea", {}).get("web", {}).get("out") == 2000)
        buf3, real3 = io.StringIO(), sys.stdout
        sys.stdout = buf3
        try:
            code3 = main([_map, "--ledger-dir", ledger, "--project-dir", tmp,
                          "--json", "--area", "web"])
        finally:
            sys.stdout = real3
        check("da11 --area narrows the whole json payload, totals included",
              code3 == 0
              and json.loads(buf3.getvalue())["totals"]["out"] == 2000)

        # --- markdown format (md): --format md for markdown surfaces --------
        # The /audit:usage command echoes stdout verbatim into a markdown
        # renderer, where the ASCII layout dies twice: runs of spaces fold,
        # and consecutive lines merge into one paragraph. md mode emits pipe
        # tables and bullets instead. ascii stays the default - terminals,
        # pipes and CI keep today's bytes.
        check("md1 the default format is ascii and carries no pipe tables",
              build_parser().parse_args([]).format == "ascii"
              and "|" not in text)
        args_md = build_parser().parse_args(["--format", "md"])
        args_md.ledger_dir = ledger
        md_text = render(loaded, args_md, manifest, "all time", True)
        check("md2 --format md renders pipe tables with an alignment row",
              "\n| BY PHASE |" in md_text and "---:" in md_text)
        check("md3 the header block is bulleted so markdown cannot merge its "
              "lines into one paragraph",
              md_text.startswith("**USAGE**") and "\n- **Total** " in md_text)
        check("md4 md output is still pure ASCII with no ANSI escapes",
              all(ord(c) < 128 for c in md_text) and "\033" not in md_text)
        args_by_md = build_parser().parse_args(["--by", "model",
                                                "--format", "md"])
        args_by_md.ledger_dir = ledger
        _one_md = render(loaded, args_by_md, manifest, "all time", True)
        check("md5 --by renders one focused md table",
              "\n| MODEL |" in _one_md and "BY PHASE" not in _one_md)
        check("md6 the trend renders as a table under a bold heading",
              "**TREND**" in md_text and "\n| day |" in md_text)
        check("md7 --no-cost drops the cost column in md too",
              "| cost |" in md_text
              and "| cost |" not in render(loaded, args_md, manifest,
                                           "all time", False))
        _man_p = json.loads(json.dumps(manifest))
        _man_p["phases"][0]["title"] = "Alpha | Beta"
        check("md8 a pipe inside a cell is escaped, not a column break",
              "Alpha \\| Beta" in render(loaded, args_md, _man_p,
                                         "all time", True))
        check("md9 the multi-tag area caveat survives in md",
              "sum past the total" in render(loaded, args_md, _man_a,
                                             "all time", True))
        check("md10 an empty ledger explains itself in md as well",
              "No usage recorded" in render([], args_md, manifest,
                                            "all time", True))
        _amd = "\n".join(routing_advice_lines([{
            "risk": "low", "from": "claude-opus-5", "to": "claude-sonnet-5",
            "tasks": 7, "fromMeanAttempts": 1.0, "atFromRates": 157.75,
            "atToRates": 94.65, "saving": 63.10, "savingPct": 40.0,
            "evidenceTasks": 5, "evidenceAttempts": 1.0}], fmt="md"))
        check("md11 advice lines are bullets in md so they stay separate lines",
              "**WHAT THE EVIDENCE SUPPORTS**" in _amd and "\n- " in _amd)
        buf4, real4 = io.StringIO(), sys.stdout
        sys.stdout = buf4
        try:
            code4 = main([_map, "--ledger-dir", ledger, "--project-dir", tmp,
                          "--json", "--format", "md"])
        finally:
            sys.stdout = real4
        check("md12 --json is format-agnostic - the payload stays json",
              code4 == 0
              and json.loads(buf4.getvalue())["totals"]["out"] == 3500)

        # --- color (co): --color through _cli_fmt ---------------------------
        # Plain mode must stay byte-identical to the pre-color dashboard: a
        # disabled painter is the identity, and every pre-color caller (this
        # selftest included) passes no painter at all. md never colors.
        check("co1 --color defaults to auto and accepts the three modes",
              build_parser().parse_args([]).color == "auto"
              and build_parser().parse_args(["--color", "always"]).color
              == "always"
              and build_parser().parse_args(["--color", "never"]).color
              == "never")
        check("co2 a never/off painter renders byte-identically to the "
              "pre-color dashboard",
              render(loaded, args, manifest, "all time", True,
                     pt=_cli_fmt.painter("never")) == text)
        _painted = render(loaded, args, manifest, "all time", True,
                          pt=_cli_fmt.painter("always"))
        check("co3 a painted dashboard carries ANSI and strips back to the "
              "plain bytes exactly - painting never changes content",
              "\033[" in _painted and _cli_fmt.strip(_painted) == text)
        check("co4 painted output is still pure ASCII (ANSI escapes are "
              "ASCII, so the cp1252 leg keeps passing)",
              all(ord(c) < 128 for c in _painted))
        check("co5 --format md never colors, even with an always painter - "
              "byte-identical to the unpainted md render",
              render(loaded, args_md, manifest, "all time", True,
                     pt=_cli_fmt.painter("always")) == md_text)
        check("co6 the paint lands on the section headers and notes (bold "
              "BY PHASE header row, dim band note)",
              "\033[1m  BY PHASE" in _painted and "\033[2m" in _painted)

        # --- shares and bars (sb): the two table call sites, through _fmt ----
        # Both tables used to divide by `grand = tot["tokens"] or 1`. That is
        # not a guard: it does not prevent a bad answer, it manufactures one.
        # Run verbatim it renders a row of 5 out of a total of 0 as "500%", and
        # every row of a zero-total ledger as "0%" - indistinguishable from a
        # measured zero. _fmt.share_pct owns the divide now and returns None,
        # which fmt_share renders as "?".
        #
        # Every case below reads the share CELLS, not the whole document: the
        # dashboard prints "(cache hit 0%)" in its header, so `"0%" in text` is
        # true on any ledger and asserts nothing. And each collects EVERY cell
        # rather than finding one - a sentinel that leaked into half the rows
        # would pass a presence assertion.
        _shares_re = re.compile(r"\[[#.]+\]\s+(\S+)")
        _zero_counts = {"in": 0, "out": 0, "cacheW5m": 0, "cacheW1h": 0,
                        "cacheR": 0, "costUSD": 0.0}
        _zero_rows = [dict(loaded[0], sessionId="s-z1", **_zero_counts),
                      dict(loaded[2], sessionId="s-z2", **_zero_counts)]
        # `_man_a` (the da block's tagged plan), not `manifest`: BY AREA is the
        # SECOND call site and it divides by its own `grand`. Rendered against an
        # untagged plan that table never appears, and its copy of the bug would
        # sit here uncaught while this case reported green.
        _ztext = render(_zero_rows, args, _man_a, "all time", True)
        _zshares = _shares_re.findall(_ztext)
        check("sb1 a ledger totalling zero tokens reports EVERY share as "
              "unmeasurable, not as a measured 0% - the `or 1` guard's answer",
              "BY AREA" in _ztext and len(_zshares) >= 6
              and set(_zshares) == {"?"}, repr(_zshares))
        _real_shares = _shares_re.findall(_atext)
        check("sb2 ...and a real ledger never shows the sentinel (the "
              "second-direction case: this one goes red if the guard becomes "
              "unconditional, and passes on the pre-fix code by construction)",
              "BY AREA" in _atext and len(_real_shares) >= 6
              and "?" not in _real_shares, repr(_real_shares))
        _mixed = list(loaded) + [dict(loaded[0], sessionId="s-zerorow",
                                      phaseId="P3", taskId="P3.9",
                                      **_zero_counts)]
        _mshares = _shares_re.findall(render(_mixed, args, _man_a,
                                             "all time", True))
        check("sb3 a genuinely empty row inside a real total still prints 0% - "
              "absent is not unmeasurable, and the sentinel must not spread",
              "0%" in _mshares and "?" not in _mshares, repr(_mshares))
        check("sb4 the share box is the same width at every fill, so the "
              "column stays a column",
              set(len(b) for b in re.findall(r"\[[#.]+\]", text)) == {20})
        # The trend, whose `peak = max(...) or 1` was the third `or 1`. With the
        # divisor forced to 1, `n == peak` could never hold on an all-zero
        # ledger; with the real peak it holds for every day, so the marker needs
        # its own guard. Labelling every empty day "peak 0" invents a high-water
        # mark, which is the same defect as the manufactured share.
        check("sb5 a trend with nothing in it names no peak day",
              "TREND" in _ztext and "peak 0" not in _ztext
              and "peak hour" in _ztext)
        check("sb6 ...while a real ledger still names its peak day",
              "peak " in text.split("TREND")[-1])
        _tiny = [dict(loaded[0], ts="2026-08-05T09", sessionId="s-big",
                      **dict(_zero_counts, out=1_000_000)),
                 dict(loaded[0], ts="2026-08-06T09", sessionId="s-tiny",
                      **dict(_zero_counts, out=1))]
        _ttext = render(_tiny, args, manifest, "all time", True)
        check("sb7 a real-but-tiny day still draws a cell (bar_cells' "
              "min_fill) - a day with spend must not render as a blank row",
              "\n  08-06  #" in _ttext, _ttext.split("TREND")[-1])
        check("sb8 ...and in md too, which builds the same sparkline a second "
              "time - one adopted call site does not vouch for the other",
              "| 08-06 | 1 | # |" in render(_tiny, args_md, manifest,
                                            "all time", True))

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
