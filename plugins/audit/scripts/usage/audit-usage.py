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

This module carries no `--selftest` of its own any more; its 106 cases live in
`plugins/audit/tests/test_audit_usage.py`, byte-identical labels and all - see
`plugins/audit/tests/_harness.py`.
"""
import argparse
import json
import os
import re
import sys
import time

# The path bootstrap: byte-identical in every `.py` under `scripts/`, counted by
# `_output.path_preamble_violations()`. It walks UP to the directory holding
# `_output.py` instead of counting `dirname()` calls, so it does not encode how deep
# this file sits and keeps working if the file is moved into a subdirectory.
# `install_path()` then adds that directory AND every subdirectory of it holding a
# `.py`: the folders are LABELS, NOT NAMESPACES, and every sibling below is still
# reached by a bare basename.
_anchor_dir = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_anchor_dir, "_output.py")):
    _anchor_up = os.path.dirname(_anchor_dir)
    if _anchor_up == _anchor_dir:
        raise ImportError("audit plugin: walked to the filesystem root from %s "
                          "without finding _output.py - the scripts/ anchor is "
                          "gone and no sibling can be imported" % (__file__,))
    _anchor_dir = _anchor_up
if _anchor_dir not in sys.path:
    sys.path.insert(0, _anchor_dir)

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()

import _loader  # noqa: E402  (the one way scripts/ loads a sibling script as a library)
import _locks  # noqa: E402  (lock paths + the liveness verdict, at layer 1)
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
    phases = {}
    for ph in ((manifest or {}).get("phases") or []):
        if isinstance(ph, dict) and ph.get("id"):
            phases[ph["id"]] = ph.get("title") or ""
    # The task half is a whole-manifest traversal, so it is the shared one. The
    # phase half is not - a phase with no tasks still needs its title here, and
    # `iter_tasks` yields nothing for one.
    tasks = {t["id"]: t.get("title") or ""
             for _, t in mio.iter_tasks(manifest) if t.get("id")}
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
    """`_locks`, the lock's read side, at layer 1.

    A plain import rather than a `_loader.load_script("audit-lock.py")`: that was
    this file (L7) loading an L7 peer, one of the edges `_deps.KNOWN_LAYER_DEBT`
    recorded. Still a function, because `acquire_lock` below reads it as "the
    module that owns the verdict" and there is one caller for a reason."""
    return _locks


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


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exits silently: `--selftest` is what every other
        # file here still accepts, so nothing would tell a reader whether this
        # one ran nothing or has nothing. It deliberately does NOT print the
        # suite contract - that literal is how `_output.selftest_coverage()`
        # tells an inline suite from a migrated one.
        print("audit-usage.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_audit_usage.py - run that file instead.")
        raise SystemExit(0)
    raise SystemExit(main(sys.argv[1:]))
