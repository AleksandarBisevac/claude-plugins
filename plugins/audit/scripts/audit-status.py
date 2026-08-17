#!/usr/bin/env python3
"""
Headless status rollup + CI gate for the audit manifest — dependency-free (stdlib).

Turns the manifest into a machine-readable summary and, in gate mode, a CI
pass/fail signal — so a pipeline can block a merge on manifest state without
any Claude session involved.

Usage:
  audit-status.py <manifest> [--json [--discovery]] [--gate] [--phase <id>]
                             [--color auto|always|never]
                             [--fail-on <c1,c2,...>]
  audit-status.py --selftest

Modes: a bare invocation renders a human report; --json is for machines.
  --json    print the rollup as JSON
  --discovery  with --json only: add a `discovery` block (the skills/agents this
            project can actually see) so /audit:init and /audit:task suggest from
            ONE mechanical source instead of each scanning the filesystem in
            prose. Without the flag the --json payload is byte-identical to the
            pre-flag output (pinned by selftest dv1).
  --phase   scope the human render to one phase (totals stay whole-plan)
  --gate    evaluate fail conditions; exit 1 when any trips (prints a summary)

Conditions for --fail-on (comma list; the --gate default is
`invalid,open-high-bugs,blocked-tasks`):
  invalid          the structural validator reports findings
  open-high-bugs   high-or-worse severity bugs not yet fixed/wontfix
                   (high/critical/blocker/severe/fatal/urgent/sev0-1/s0-1/p0-1)
  open-bugs        ANY bug not yet fixed/wontfix
  blocked-tasks    any task with status "blocked"
  in-progress      any phase or task "in_progress" (for release-freeze gates)
  over-budget      a phase at or past 100% of its `budgetUSD`
  budget-80        a phase at or past 80% of its `budgetUSD`

Neither budget condition is in the --gate default: spend is a signal, not a defect,
and a phase at 105% may be entirely justified. Opt in when a budget is a commitment.

Exit codes: 0 pass · 1 gate failed · 2 usage error / unreadable manifest
(matching validate-manifest.py's convention).

This module carries no `--selftest` of its own any more; its 178 cases live in
`plugins/audit/tests/test_audit_status.py`, byte-identical labels and all - see
`plugins/audit/tests/_harness.py`. The `_fixture()` most of them start from went
with them (no caller outside the suite), and so did the guard that keeps two case
groups from claiming one id letter.
"""
import json
import os
import re
import sys

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

import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR index+shards)
import _areas  # noqa: E402  (meta.areas registry + the resolution every surface shares)
import _ui_theme as _theme  # noqa: E402  (the words a person reads for a machine value)
import _loader  # noqa: E402  (the one way scripts/ loads a sibling script as a library)
import _fmt  # noqa: E402  (the one token/cost formatter, since P10.6 — no indirection needed)
import _cli_fmt  # noqa: E402  (the one place CLI color lives - mode resolution + paint)

# --- config / loading -----------------------------------------------------------
CONDITIONS = ("invalid", "open-high-bugs", "open-bugs", "blocked-tasks",
              "in-progress", "over-budget", "budget-80")
# Neither budget condition is in the default gate. Spend is a signal, not a defect:
# a phase at 105% may be entirely justified, and failing someone's merge over it
# without them asking would make the whole gate something to switch off. Opt in with
# --fail-on when a budget is a commitment rather than an estimate.
DEFAULT_GATE = ("invalid", "open-high-bugs", "blocked-tasks")
# Warn threshold for the interactive path and the `budget-80` condition. 80% is far
# enough in to be real and early enough to act on.
BUDGET_WARN_PCT = 80.0
CLOSED_BUG = ("fixed", "wontfix")

# How many ready tasks /audit:status lists before folding. A wide-open plan can
# have hundreds; the count is always stated so the fold is never mistaken for the
# whole set.
READY_LIST_MAX = 12

# "open-high-bugs" must catch high-severity-or-worse, not only the literal word
# "high" — a bug filed as critical/blocker/sev1/p0 is the LAST thing a merge
# gate should wave through. Severity is free-text, so normalise (lowercase,
# drop non-alphanumerics) and match a vocabulary of high-or-worse terms.
HIGH_SEVERITIES = frozenset({
    "high", "critical", "crit", "blocker", "severe", "fatal", "urgent",
    "sev0", "sev1", "s0", "s1", "p0", "p1",
})


def _is_high_severity(severity):
    """True for high-or-worse free-text severities (see HIGH_SEVERITIES)."""
    return re.sub(r"[^a-z0-9]", "", str(severity or "").lower()) in HIGH_SEVERITIES


def _load_validator():
    """Import validate-manifest.py (hyphenated filename) as a library."""
    return _loader.load_script("validate-manifest.py", modname="validate_manifest",
                                cache=False)


# --- submodule conflict detection (preflight guard) -----------------------------
# The orchestrator commits from ONE git repo (the resolved gitRoot). Files that
# live inside a git SUBMODULE belong to a separate nested repo — the parent
# cannot stage them ("Pathspec is in submodule"), so a task touching them would
# fail at commit time. This flags them up front.

def parse_gitmodules(text):
    """Submodule paths (git-root-relative) from a .gitmodules file's text."""
    paths = []
    for line in str(text).splitlines():
        s = line.strip()
        # `.gitmodules` uses `path = <dir>` inside each [submodule "..."] block
        if s.lower().startswith("path") and "=" in s:
            val = s.split("=", 1)[1].strip().replace("\\", "/").strip("/")
            if val:
                paths.append(val)
    return paths


def _strip_git_root(path, git_root):
    """Project-relative file -> git-root-relative (drop the gitRoot prefix and any
    `:line` suffix)."""
    p = str(path).replace("\\", "/").split(":", 1)[0]
    gr = str(git_root or "").replace("\\", "/").strip("/")
    if gr and (p == gr or p.startswith(gr + "/")):
        return p[len(gr) + 1:]
    return p


def submodule_conflicts(manifest, submodule_paths, git_root=""):
    """List of (task_id, file, submodule) for each task file that lives inside a
    submodule. `files` are project-relative (gitRoot-prefixed); `submodule_paths`
    are git-root-relative. Path-boundary safe: 'vendor/child' matches
    'vendor/child/x' but NOT 'vendor/child-other/x'."""
    subs = [str(s).replace("\\", "/").strip("/") for s in (submodule_paths or []) if s]
    out = []
    # `_mio.iter_tasks` also absorbs the non-dict-root guard this used to open
    # with: a scalar manifest yields no pairs rather than raising (case nd3).
    for _ph, t in _mio.iter_tasks(manifest):
        for f in t.get("files") or []:
            rel = _strip_git_root(f, git_root)
            for s in subs:
                if rel == s or rel.startswith(s + "/"):
                    out.append((t.get("id"), f, s))
                    break
    return out


# --- gate rollup ----------------------------------------------------------------
def _status_index(manifest):
    """`{phase id or task id: status}` — what a `blockedBy`/`dependsOn` ref resolves
    through. `ready_tasks` and `unmet_refs` each built this by hand, identically.

    ONE id space, holding PHASES as well as tasks, is why this walk is hand-rolled
    rather than `_mio.iter_tasks`, and both halves of that matter:

      * a task may be blocked by a whole phase, INCLUDING a phase that carries no
        tasks of its own — and `iter_tasks` yields nothing at all for such a phase,
        so its status would be missing and every dependent task would read ready;
      * because phase and task ids share the map, WHICH ONE WINS on a collision is
        observable, and document order is what decides it here. Filling the phases
        in one pass and the tasks in another makes the task win instead. That is a
        `duplicate id` manifest either way (the validator reports it across phases
        + tasks + bugs), but this is the read-only surface that has to RENDER an
        invalid manifest rather than refuse it, so its tie-breaks are held fixed.
    """
    status = {}
    if not isinstance(manifest, dict):
        return status
    for ph in (manifest.get("phases") or []):
        if not isinstance(ph, dict):
            continue
        if ph.get("id"):
            status[ph["id"]] = ph.get("status")
        for t in (ph.get("tasks") or []):
            if isinstance(t, dict) and t.get("id"):
                status[t["id"]] = t.get("status")
    return status


def ready_tasks(manifest):
    """Task ids ready to run — mirrors /audit's readiness rule: status pending,
    own blockedBy satisfied, own dependsOn all done, phase blockedBy satisfied
    ('satisfied' = referenced task/phase is done)."""
    status = _status_index(manifest)

    def satisfied(refs):
        return not _mio.unsatisfied(refs, status)

    out = []
    # The phase arrives WITH the task, so its `blockedBy` needs no second lookup —
    # and a non-dict manifest yields no pairs, which is what makes the old
    # isinstance guard above redundant (case nd2 pins it).
    for ph, t in _mio.iter_tasks(manifest):
        if t.get("status") != "pending":
            continue
        if not satisfied(t.get("blockedBy")):
            continue
        if not satisfied(t.get("dependsOn")):
            continue
        if not satisfied(ph.get("blockedBy")):
            continue
        if t.get("id"):
            out.append(t["id"])
    return out


def _by_status(items):
    out = {}
    for it in items:
        s = it.get("status") if isinstance(it, dict) else None
        out[str(s)] = out.get(str(s), 0) + 1
    return out


def _by_status_values(values):
    out = {}
    for s in values:
        out[str(s)] = out.get(str(s), 0) + 1
    return out


# A phase's `area` -> its tags. Re-exported rather than reimplemented: the panel
# and this file each carried their own copy, and one of them would eventually have
# learned something the other had not. `_areas` also owns what a tag MEANS now
# (meta.areas), so normalisation had to move next to the lookup it feeds.
areas_of = _areas.areas_of


# A bug's status, DERIVING 'fixed' from its linked task. Re-exported rather than
# reimplemented, the same move `areas_of` above makes: this rule had two homes that
# could drift — here (layer 7) and `_report_html._bug_view` (layer 2) — and layer 2
# cannot import layer 7, so the copy was structural. `_manifest_io` is the only
# place underneath both readers. Its docstring carries the rule and says why the
# falsy-taskId guard is load-bearing; `_panel_state` reaches this name through
# `_cores()`, so the name stays.
effective_bug_status = _mio.effective_bug_status


# --- usage summary --------------------------------------------------------------
def usage_summary(manifest, manifest_path, project_dir=None):
    """Compact token-usage block for the rollup, or None when there is no ledger.

    Kept OUT of `rollup` so that function stays a pure dict -> dict transform; the
    ledger is I/O and belongs to the caller. Never raises: a missing, empty or
    unreadable ledger simply means no usage key, and every consumer treats that as
    "metering not in use" rather than an error."""
    try:
        ul = _loader.load_script("usage_ledger.py", modname="usage_ledger",
                                  cache=False)
    except Exception:
        return None

    meta_usage = ((manifest or {}).get("meta") or {}).get("usage") or {}
    rel = (meta_usage.get("ledgerDir")
           if isinstance(meta_usage, dict) else None) or os.path.join(
               ".claude", "usage")
    # Search upward from the manifest rather than assuming a fixed depth — see
    # usage_ledger.find_ledger_dir for why the fixed-depth version was dangerous.
    ledger_dir = ul.find_ledger_dir(
        manifest_path, rel, project_dir or os.environ.get("CLAUDE_PROJECT_DIR"))
    if not ledger_dir:
        return None

    try:
        rows = ul.read_ledger(ledger_dir)
    except Exception:
        return None
    if not rows:
        return None
    try:
        total = ul.totals(rows)
        by_phase = ul.aggregate(rows, "phase")
        return {
            "ledgerDir": ledger_dir,
            "pricingAsOf": meta_usage.get("pricingAsOf")
            if isinstance(meta_usage, dict) else None,
            "showCost": bool(meta_usage.get("showCost", True))
            if isinstance(meta_usage, dict) else True,
            "totals": total,
            "byPhase": {k: {"tokens": v["tokens"], "costUSD": v["costUSD"],
                            "msgs": v["msgs"]} for k, v in by_phase.items()},
            "byModel": {k: {"tokens": v["tokens"], "costUSD": v["costUSD"],
                            "msgs": v["msgs"]}
                        for k, v in ul.aggregate(rows, "model").items()},
            "byAuthor": {k: {"tokens": v["tokens"], "costUSD": v["costUSD"],
                             "msgs": v["msgs"]}
                         for k, v in ul.aggregate(rows, "author").items()},
            # `phase_budgets` is reused verbatim, not re-derived: it already returns
            # spent/budget/pct/over per phase and encodes the rule that 0, negative,
            # boolean and non-numeric all mean "no budget" rather than a budget of
            # zero. Re-implementing that here is how the three existing copies of it
            # would become four.
            "budgets": ul.phase_budgets(manifest, rows),
        }
    except Exception:
        return None


# --- discovery (--json --discovery only) ----------------------------------------
# The init/task suggestion helper (v0.38 B): ONE mechanical source for "which
# skills/agents exist here", so commands/init.md step 6.1 and commands/task.md's
# skills step offer real names from a payload instead of each scanning the
# filesystem in prose. Opt-in behind --discovery because the bare --json payload
# is a pinned machine surface (selftest dv1); the import is lazy AND inside the
# try so a broken discovery module can never take down the status/gate surface
# it merely enriches.

# Mirrors _panel_discovery._entry's own description cap; re-applied here so THIS
# payload's bound does not silently follow a future discovery-side change.
DISCOVERY_DESC_CAP = 280


def discovery_block(project, home=None):
    """{"skills": [{name, description, source}], "agents": [...]} for `project`.

    Rows come from _panel_discovery.discover (the panel's own scan: project
    .claude/, user ~/.claude/, installed plugins, this repo's plugins tree)
    trimmed to the three keys a suggestion needs -- `path` is dropped on
    purpose: an absolute path is machine-specific noise in a payload meant to
    be read back as names. Descriptions are clipped to DISCOVERY_DESC_CAP, the
    same cap discovery itself applies at ingest. An empty inventory is empty
    lists, never an error; ANY failure is {"skills": [], "agents": [],
    "error": "<one line>"} -- fail-open, because a status surface must keep
    answering when an enrichment cannot."""
    try:
        import _panel_discovery
        found = _panel_discovery.discover(project, home=home) or {}

        def rows(kind):
            out = []
            for e in found.get(kind) or []:
                if isinstance(e, dict):
                    out.append({
                        "name": e.get("name"),
                        "description": (e.get("description")
                                        or "")[:DISCOVERY_DESC_CAP],
                        "source": e.get("source"),
                    })
            return out

        return {"skills": rows("skills"), "agents": rows("agents")}
    except Exception as exc:
        msg = " ".join(("%s: %s" % (type(exc).__name__, exc)).split())
        return {"skills": [], "agents": [],
                "error": (msg or type(exc).__name__)[:200]}


# ca (F-P-4): the two ways a phase or task can be FINISHED. `done` is the work
# landed; `cancelled` is the work will not be done — the feature was dropped, the
# approach abandoned — and it is terminal in exactly the same sense. Readiness
# treats a cancelled blocker as settled on purpose: a plan whose dropped work
# still gates everything behind it deadlocks, and a deadlock nobody can clear is
# a worse answer than a ready task worth a second look.
TERMINAL = _mio.TERMINAL


def rollup(manifest, findings, warnings, usage=None):
    """The machine-readable summary --json, render-report and the panel consume.

    `usage` is the optional block from `usage_summary()`; it is passed in rather
    than read here so this stays a pure dict -> dict transform."""
    if not isinstance(manifest, dict):
        manifest = {}  # non-object root -> empty rollup, never an AttributeError
    phases = [p for p in (manifest.get("phases") or []) if isinstance(p, dict)]
    tasks = [t for _p, t in _mio.iter_tasks(manifest)]
    bugs = [b for b in (manifest.get("bugs") or []) if isinstance(b, dict)]
    task_by_id = _mio.tasks_by_id(manifest)
    bug_eff = [effective_bug_status(b, task_by_id) for b in bugs]
    open_bugs = [b for b, s in zip(bugs, bug_eff) if s not in CLOSED_BUG]
    phase_entries = [{
        "id": p.get("id"), "title": p.get("title"),
        "status": p.get("status"), "area": areas_of(p.get("area")),
        "desiredOutcome": p.get("desiredOutcome"),
        "done": sum(1 for t in (p.get("tasks") or [])
                    if isinstance(t, dict) and t.get("status") == "done"),
        # ca: counted separately, never folded into `done`. A bar that showed
        # 5/5 for three landed tasks and two dropped ones would be a lie in the
        # one direction that matters.
        "cancelled": sum(1 for t in (p.get("tasks") or [])
                         if isinstance(t, dict) and t.get("status") == "cancelled"),
        "total": sum(1 for t in (p.get("tasks") or []) if isinstance(t, dict)),
    } for p in phases]
    # group phases by each of their `area` tags (a phase with several tags counts
    # under each; untagged phases are simply not grouped)
    areas = {}
    for e in phase_entries:
        for a in e["area"]:
            g = areas.setdefault(a, {"phases": 0, "done": 0, "total": 0})
            g["phases"] += 1
            g["done"] += e["done"]
            g["total"] += e["total"]
    # The advisory owner (v0.34 D3), only for areas that DECLARE the key - no
    # key means no claim, and an explicit null is carried as null ("nobody"),
    # the same distinction _areas.owner_of draws.
    reg = _areas.registry(manifest)
    for tag, g in areas.items():
        entry = reg.get(tag) or {}
        if "owner" in entry:
            o = entry.get("owner")
            g["owner"] = o.strip() if isinstance(o, str) and o.strip() else None
    # Whether meta.areas registers anything at all (v0.37 B3): the fact that
    # decides if an UNTAGGED phase is a blind spot (defaults exist and skip it)
    # or just a phase in a free-text-tagging project (nothing to miss).
    areas_registered = bool(reg)
    props = [x for x in (manifest.get("proposals") or []) if isinstance(x, dict)]
    out = {
        "valid": not findings,
        "findings": len(findings),
        "warnings": len(warnings),
        "phases": phase_entries,
        "areas": areas,
        "areasRegistered": areas_registered,
        "tasks": {"total": len(tasks), "byStatus": _by_status(tasks)},
        "bugs": {"total": len(bugs), "byStatus": _by_status_values(bug_eff),
                 "open": len(open_bugs),
                 "openHighSeverity": sum(
                     1 for b in open_bugs
                     if _is_high_severity(b.get("severity")))},
        # "parked" counts only what /audit:propose materialize can act on —
        # status 'proposed' WITH a payload. Legacy free-form entries show up in
        # total/byStatus but are not parked work.
        "proposals": {"total": len(props), "byStatus": _by_status(props),
                      "parked": sum(1 for x in props
                                    if x.get("status") == "proposed"
                                    and isinstance(x.get("payload"), dict))},
        "ready": ready_tasks(manifest),
    }
    # Only present when a ledger exists, so consumers can treat "no key" as
    # "metering not in use" without a second probe.
    if usage:
        out["usage"] = usage
    return out


def unmet_refs(manifest):
    """Task/phase id -> the refs it waits on that are not `done` yet.

    Same 'satisfied' notion as `ready_tasks`, exposed per task so the renderer can
    say WHY something is not ready instead of only that it is not."""
    if not isinstance(manifest, dict):
        return {}
    status = _status_index(manifest)

    def unmet(refs):
        return _mio.unsatisfied(refs, status)

    # `_mio.iter_tasks` is deliberately NOT used here, for `_status_index`'s second
    # reason: this dict is keyed by phase ids AND task ids together, and the phase
    # rows have to be written in document order relative to the task rows or a
    # `duplicate id` manifest resolves to a different answer than it used to.
    out = {}
    for ph in (manifest.get("phases") or []):
        if not isinstance(ph, dict):
            continue
        pending = unmet(ph.get("blockedBy"))
        if ph.get("id") and pending:
            out[ph["id"]] = pending
        for t in (ph.get("tasks") or []):
            if not isinstance(t, dict) or not t.get("id"):
                continue
            waits = unmet(list(t.get("blockedBy") or [])
                          + list(t.get("dependsOn") or []))
            # A task inherits its phase's gate: it cannot start while the phase
            # is blocked, and saying so is more useful than an empty column.
            waits += ["%s (phase)" % r for r in pending]
            if waits:
                out[t["id"]] = waits
    return out


# --- human rendering ------------------------------------------------------------
# `_marker` and the layout below are the vocabulary commands/status.md used to hand
# to the model as prose. Moving it here is the same move commands/usage.md already
# made for itself: a status command that spends tokens re-tabulating a rollup it was
# just handed is paying twice for one answer, and the layout comes out different
# every run. The model reads nothing here — this renders from the manifest that is
# already loaded in this process, so nothing is re-read either.
_MARKERS = {"done": "[x]", "in_progress": "[~]", "blocked": "[!]",
            "pending": "[ ]", "cancelled": "[-]"}


def _marker(status):
    return _MARKERS.get(status, "[?]")


def _short(sha):
    s = str(sha or "")
    return s[:7] if s else "-"


def render_status(manifest, summary, width=18, only_phase=None, pt=None):
    """Plain-ASCII status report. Printed verbatim by /audit:status.

    Pure ASCII, no ANSI, no box-drawing — the same constraint audit-usage.py's
    selftest enforces on its own output, so this reads in any terminal. `pt` is
    a _cli_fmt.Painter; None (every pre-color caller) means plain, and a
    disabled painter returns its input unchanged, so plain mode stays
    byte-identical to the pre-color render."""
    pt = pt or _cli_fmt.PLAIN
    meta = (manifest or {}).get("meta") or {}
    lines = []
    title = meta.get("title") or "audit"
    repo = meta.get("repo") or "-"
    lines.append(pt.paint("AUDIT  %s   repo %s" % (title, repo), "header"))
    lines.append("")

    t_total = summary["tasks"]["total"]
    t_done = summary["tasks"]["byStatus"].get("done", 0)
    ph_done = sum(1 for p in summary["phases"] if p.get("status") == "done")
    bugs = summary["bugs"]
    lines.append("  %s  %d/%d tasks done - %d/%d phases signed off - "
                 "%d open bug(s) - %d ready now"
                 % (_fmt.fmt_bar(t_done, t_total, width), t_done, t_total,
                    ph_done, len(summary["phases"]), bugs["open"],
                    len(summary["ready"])))
    if not summary["valid"]:
        lines.append(pt.paint(
            "  INVALID MANIFEST: %d validator finding(s) - fix before "
            "running a phase" % summary["findings"], "finding"))
    # A park-all /audit:init leaves a valid plan with zero phases. Without this
    # line that plan reads as "nothing to do" on the one surface everyone
    # checks first, when the actual state is "everything is waiting for you".
    props_sum = summary.get("proposals") or {}
    if not summary["phases"] and props_sum.get("parked"):
        lines.append(pt.paint("  empty plan - %d parked proposal(s) waiting: "
                              "/audit:propose list" % props_sum["parked"],
                              "warn"))

    usage = summary.get("usage")
    if usage:
        lines.append("  " + _usage_line(summary, usage))
        lines += _budget_lines(summary, usage, pt=pt)

    unmet = unmet_refs(manifest)
    ready = set(summary["ready"])
    by_id = {p.get("id"): p for p in (manifest.get("phases") or [])
             if isinstance(p, dict)}
    # Scoping affects only which phases are LISTED. The overall line, the usage
    # line and the bug counts stay whole-plan on purpose: a phase view that
    # silently rescoped the totals would misreport the project.
    shown_phases = [p for p in summary["phases"]
                    if not only_phase or p.get("id") == only_phase]
    if only_phase:
        lines.append("  scoped to phase %s - totals above are whole-plan"
                     % only_phase)

    # Column widths are computed across EVERY task, then the header is printed once.
    # Per-phase tables re-printed their own header and re-derived their own widths,
    # so a fifty-phase manifest produced fifty header rows and fifty different
    # alignments — the columns stopped being columns.
    all_rows = {}
    for pe in shown_phases:
        ph = by_id.get(pe.get("id")) or {}
        rows = []
        for t in (ph.get("tasks") or []):
            if not isinstance(t, dict):
                continue
            tid = t.get("id") or "?"
            rows.append([
                "%s %s" % (_marker(t.get("status")), tid),
                _clip(_one_line(t.get("title")), 44),
                _theme.label(t.get("status")) or "?",
                t.get("model") or "-",
                _clip(", ".join(unmet.get(tid, [])) or "-", 26),
                _short(t.get("commit")),
                "READY" if tid in ready else "",
            ])
        all_rows[pe.get("id")] = rows

    cols = ("task", "title", "status", "model", "waiting on", "commit", "")
    widths = [len(c) for c in cols]
    for rows in all_rows.values():
        for r in rows:
            for i, cell in enumerate(r):
                widths[i] = max(widths[i], len(cell))

    def fmt_row(cells):
        return "     " + "  ".join("%-*s" % (widths[i], cells[i])
                                   for i in range(len(cols))).rstrip()

    lines.append("")
    lines.append(fmt_row(list(cols)))

    for pe in shown_phases:
        lines.append("")
        pdone, ptotal = pe.get("done", 0), pe.get("total", 0)
        ph = by_id.get(pe.get("id")) or {}
        head = "  %-4s %-26s %-11s %s %d/%d" % (
            pe.get("id") or "?", _clip(pe.get("title") or "", 26),
            _theme.label(pe.get("status")) or "?",
            _fmt.fmt_bar(pdone, ptotal, 12), pdone, ptotal)
        if ph.get("branch"):
            head += "  %s" % ph["branch"]
        lines.append(head)
        if pe.get("desiredOutcome"):
            lines.append("       desired: %s"
                         % _clip(_one_line(pe["desiredOutcome"]), 88))
        scope = _scope_line(manifest, ph, pe)
        if scope:
            lines.append(scope)
        if pe.get("id") in unmet and ph.get("status") != "done":
            lines.append("       blocked by: %s"
                         % _clip(", ".join(unmet[pe["id"]]), 70))
        for r in all_rows.get(pe.get("id")) or []:
            lines.append(fmt_row(r))

    lines.append("")
    if summary["ready"]:
        ready_list = summary["ready"]
        # A wide-open plan can have hundreds of ready tasks, and a 464-line list is
        # a list nobody reads. Fold it, and SAY the count — a silent cap would read
        # as "that is all of them", which is the worse failure.
        shown = ready_list[:READY_LIST_MAX]
        lines.append(pt.paint("  READY NOW  %d task(s)%s"
                              % (len(ready_list),
                                 "" if len(shown) == len(ready_list)
                                 else ", first %d shown" % len(shown)),
                              "header"))
        task_by_id = _mio.tasks_by_id(manifest)
        for tid in shown:
            t = task_by_id.get(tid) or {}
            lines.append("    %-9s %-44s %-7s run: /audit:run %s"
                         % (tid, _clip(_one_line(t.get("title")), 44),
                            t.get("model") or "-", tid))
        if len(shown) < len(ready_list):
            lines.append("    ... and %d more - /audit:next runs the first in order"
                         % (len(ready_list) - len(shown)))
    else:
        lines.append(pt.paint("  READY NOW  nothing - every pending task is "
                              "waiting on something, or the plan is complete",
                              "header"))

    lines += _area_lines(summary, pt=pt)
    lines += _bug_lines(manifest, summary, pt=pt)
    lines += _proposal_lines(manifest, summary, pt=pt)
    lines += _resumable_lines(manifest, summary, pt=pt)
    return "\n".join(lines)


def _scope_line(manifest, phase, entry):
    """`area: api, security   review: backend-review (area api)` — or nothing.

    Two facts that were computable and never shown. The area tags existed since
    v0.16 and appeared only in the report and the panel, so the terminal — the
    surface an orchestrator run actually watches — could not tell you which part of
    a monorepo a phase belonged to. And the review skill was resolvable but never
    resolved: a reader had to check the phase, then the registry, then meta, to
    learn who signs this phase off.

    The BASIS is printed with the answer. A reviewer chosen three levels away is
    otherwise a reviewer nobody can explain, and "backend-review" alone gives no
    hint about which of the three files to edit to change it.

    Nothing is printed when there is nothing to say — no tags and no reviewer is
    the ordinary single-app repo, and a line saying so on every phase would be
    this feature charging every project for a monorepo it does not have.
    """
    parts = []
    tags = (entry or {}).get("area") or areas_of((phase or {}).get("area"))
    if tags:
        parts.append("area: %s" % _clip(", ".join(tags), 44))
    skill, basis = _areas.resolve_review_skill(manifest, phase)
    if skill:
        parts.append("review: %s (%s)" % (_clip(skill, 40), basis))
    return "       " + "   ".join(parts) if parts else ""


def _one_line(text):
    return " ".join(str(text or "").split())


def _clip(text, limit):
    """Truncate with a visible marker, and never mid-word if a word boundary is
    close. A bare slice produced rows like 'Fix BUG-3: cart total off-by-one with st',
    which reads as corruption rather than as elision."""
    s = str(text or "")
    if len(s) <= limit:
        return s
    cut = s[:limit - 3]
    space = cut.rfind(" ")
    if space >= limit - 14:          # only back up to a word break if it is near
        cut = cut[:space]
    return cut.rstrip(" ,;:") + "..."


def _usage_line(summary, usage):
    """`usage: <tokens> tok - ~$<cost> equiv - this phase <tokens>`.

    The cost clause is dropped when `showCost` is false, because naming dollars
    would leak exactly what that setting exists to hide. The phase clause is
    dropped when nothing is running, because there is no phase to attribute to."""
    totals = usage.get("totals") or {}
    parts = ["usage: %s tok" % _fmt.fmt_tokens(totals.get("tokens"))]
    if usage.get("showCost"):
        parts.append("~%s equiv" % _fmt.fmt_cost(totals.get("costUSD")))
    running = [p.get("id") for p in summary["phases"]
               if p.get("status") == "in_progress"]
    if running:
        per = (usage.get("byPhase") or {}).get(running[0]) or {}
        if per:
            parts.append("this phase %s" % _fmt.fmt_tokens(per.get("tokens")))
    # The rate table behind this cost AND behind the budget lines under it, which
    # is why it belongs here rather than only in the report: those percentages are
    # what the preflight budget check acts on, and a number that can stop a phase
    # should say what priced it. No fallback to the default table's date — see
    # render-report._usage_context; manufacturing a basis is worse than stating
    # that the manifest declared none.
    if usage.get("showCost") and (totals.get("tokens") or 0):
        parts.append("rates as of %s" % usage["pricingAsOf"]
                     if usage.get("pricingAsOf")
                     else "rates undated (set usage.pricingAsOf)")
    return " - ".join(parts)


def _budget_lines(summary, usage, pt=None):
    """Budget lines, and only for phases that actually declare one.

    Renders nothing when no phase carries a `budgetUSD`, which is the common case —
    an empty "0 of 0" frame would be worse than silence, the same call
    `_budget_block` makes in the HTML report. Phases without a budget are counted in
    a footnote rather than drawn at 0%: an unbudgeted phase is not a phase at zero."""
    if not usage.get("showCost"):
        return []                       # a budget is a money claim; honour the setting
    budgets = usage.get("budgets") or {}
    rows = [p for p in (budgets.get("phases") or []) if p.get("budget")]
    if not rows:
        return []
    pt = pt or _cli_fmt.PLAIN
    out = []
    for p in sorted(rows, key=lambda x: -(x.get("pct") or 0)):
        pct = p.get("pct") or 0.0
        flag = ""
        if pct >= 100.0:
            flag = "  " + pt.paint("OVER", "finding")
        elif pct >= BUDGET_WARN_PCT:
            flag = "  " + pt.paint("WARN", "warn")
        # `pct` is ALREADY a percentage, so the whole is a literal 100 — a
        # percentage is a hundred-cell bar. bar_cells' clamp is what keeps an
        # over-budget phase (470%) inside its own bracket.
        out.append("  budget %-5s %s %3.0f%%  %s of %s%s"
                   % (p.get("id") or "?", _fmt.fmt_bar(pct, 100, 12), pct,
                      _fmt.fmt_cost(p.get("spent")), _fmt.fmt_cost(p.get("budget")),
                      flag))
    unbudgeted = len(budgets.get("phases") or []) - len(rows)
    if unbudgeted:
        out.append("  budget       %d phase(s) declare none - not shown, and not "
                   "phases at zero" % unbudgeted)
    return out


def _area_lines(summary, pt=None):
    """`BY AREA` — the per-area rollup, printed instead of only shipped in --json.

    `summary["areas"]` has been computed (and carried in --json) since the tags
    existed; this renders THAT block rather than re-deriving it, so the terminal
    and the machine can never disagree. Nothing is printed when no phase carries
    a tag — the ordinary single-app repo pays nothing for this, the same call
    `_scope_line` makes.

    The `untagged` footer keeps the columns honest: without it, phases carrying
    no tag would silently vanish from the one grouping a monorepo reader trusts.
    And the multi-tag caveat is stated only when a phase actually carries more
    than one tag — a phase tagged with N areas counts its tasks under each of
    the N, so the per-area column can sum past the plan total, and a reader who
    adds the column up deserves to be told why. A single-tag project has nothing
    to be warned about, so it is not."""
    areas = summary.get("areas") or {}
    if not areas:
        return []
    pt = pt or _cli_fmt.PLAIN
    phases = [p for p in (summary.get("phases") or []) if isinstance(p, dict)]
    untagged = [p for p in phases if not p.get("area")]
    rows = [(tag, g.get("phases", 0), g.get("done", 0), g.get("total", 0),
             g.get("owner"))
            for tag, g in sorted(areas.items())]
    if untagged:
        rows.append(("untagged", len(untagged),
                     sum(p.get("done", 0) for p in untagged),
                     sum(p.get("total", 0) for p in untagged), None))
    # The cross-cutting blind spot (v0.37 B3), said HERE and said ONCE. The
    # surface was a choice among three: the VALIDATOR would print a line per
    # untagged phase (a wall on a plan where untagged is common and perfectly
    # legal), a PANEL per-phase-row note repeats itself fifty times at fifty
    # phases, and this rollup is the one place a reader is already comparing
    # tags against phases - directly under the untagged row it explains.
    # Aggregated by construction (one line however many phases), and gated on
    # the registry existing: with no meta.areas there are no defaults to miss.
    advisory = bool(untagged) and bool(summary.get("areasRegistered"))
    out = ["", pt.paint("  BY AREA  %d tag(s) - %d of %d phase(s) tagged"
                        % (len(areas), len(phases) - len(untagged),
                           len(phases)), "header")]
    w = max(len(r[0]) for r in rows)
    for tag, n_ph, done, total, owner in rows:
        line = ("    %-*s  %2d phase(s)  %s %d/%d tasks"
                % (w, tag, n_ph, _fmt.fmt_bar(done, total, 12), done, total))
        if owner:
            # The advisory owner, from the same rollup --json ships - the
            # person to coordinate with, never an assignee.
            line += " - %s" % owner
        out.append(line)
    if advisory:
        out.append("    note: area defaults (skills, reviewer, owner) do not "
                   "apply to untagged phases - tag them, or leave them out of "
                   "the areas system on purpose")
    if any(len(p.get("area") or []) > 1 for p in phases):
        out.append("    note: a phase with several tags counts under each - "
                   "per-area sums can exceed the plan total")
    return out


def _bug_lines(manifest, summary, pt=None):
    bugs = [b for b in ((manifest or {}).get("bugs") or []) if isinstance(b, dict)]
    if not bugs:
        return []
    pt = pt or _cli_fmt.PLAIN
    # `_mio.tasks_by_id` drops a task with no id, where the index built here used
    # to key it under `None`. That is the shape `_manifest_io.effective_bug_status`
    # documents as the hazard it guards against — a bug with no `taskId` matching
    # the `None` key and reading 'fixed'. The guard still stands; the hazard it
    # guards against no longer reaches it from this file.
    tasks = _mio.tasks_by_id(manifest)
    ready = set(summary["ready"])
    out = ["", pt.paint("  BUGS  %d total - %d open (%d high severity)"
                        % (summary["bugs"]["total"], summary["bugs"]["open"],
                           summary["bugs"]["openHighSeverity"]), "header")]
    for b in bugs:
        eff = effective_bug_status(b, tasks)
        if eff in CLOSED_BUG:
            continue
        flag = ""
        if b.get("taskId") in ready:
            flag = "   its fix is READY: /audit:run %s" % b["taskId"]
        out.append("    %-8s %-11s %-5s %s%s"
                   % (b.get("id") or "?", _theme.label(eff) or "?",
                      b.get("severity") or "-",
                      _one_line(b.get("title"))[:44], flag))
    return out


def _proposal_lines(manifest, summary, pt=None):
    """Parked proposals — phases synthesized by /audit:init but not materialized.

    Listed only while parked (status 'proposed'): a materialized proposal is
    already visible as its phase, and a dropped one is history. A payload-bearing
    row carries the copy-pasteable materialize command; a legacy free-form entry
    (no payload) is listed without one — there is nothing to materialize.

    A status OUTSIDE that vocabulary (hand-written or older-init entries carry
    things like "open") is neither parked nor history — it used to be silently
    invisible here, which is the one failure a status surface must not have.
    Such entries are counted in a legacy footer that points at
    /audit:propose list, which reads them in full. The validator stays tolerant
    of them on purpose; counting is this surface's job, judging is not."""
    props = [x for x in ((manifest or {}).get("proposals") or [])
             if isinstance(x, dict)]
    parked = [x for x in props if x.get("status") == "proposed"]
    legacy = [x for x in props
              if x.get("status") not in ("proposed", "materialized", "dropped")]
    if not parked and not legacy:
        return []
    pt = pt or _cli_fmt.PLAIN
    sp = summary.get("proposals") or {}
    out = ["", pt.paint("  PROPOSALS  %d total - %d parked"
                        % (sp.get("total", len(props)), len(parked)),
                        "header")]
    for x in parked:
        payload = x.get("payload") if isinstance(x.get("payload"), dict) else {}
        ph = payload.get("phase") if isinstance(payload.get("phase"), dict) else {}
        tasks = ph.get("tasks") if isinstance(ph.get("tasks"), list) else []
        reserved = "-"
        if ph.get("id"):
            reserved = "%s (%d task%s)" % (ph["id"], len(tasks),
                                           "" if len(tasks) == 1 else "s")
        row = "    %-16s %-14s %s" % (
            x.get("id") or "?", reserved,
            _clip(_one_line(x.get("name") or x.get("id")), 40))
        if ph.get("id"):
            row += "   materialize: /audit:propose materialize %s" % (x.get("id") or "?")
        out.append(row)
    if legacy:
        out.append("    +%d legacy proposal(s) (free-form) - /audit:propose list"
                   % len(legacy))
    return out


def _resumable_lines(manifest, summary, pt=None):
    """Flag an interrupted run, which is the one state a reader must not miss."""
    pt = pt or _cli_fmt.PLAIN
    for p in ((manifest or {}).get("phases") or []):
        if not isinstance(p, dict):
            continue
        running_tasks = [t for t in (p.get("tasks") or [])
                         if isinstance(t, dict) and t.get("status") == "in_progress"]
        if p.get("status") == "in_progress" or running_tasks:
            where = " on %s" % p["branch"] if p.get("branch") else ""
            return ["", pt.paint(
                "  RESUMABLE  phase %s is %s%s - interrupted? "
                "run /audit:resume"
                % (p.get("id") or "?",
                   (_theme.label("in_progress") or "in progress").lower(),
                   where), "warn")]
    return []


# `_load_usage_fmt()` used to sit here: a runtime load of audit-usage.py — an ENTRY
# POINT, a peer at layer 7 — purely to borrow its `bar()`. The share bar now lives in
# _fmt (`fmt_bar`/`bar_cells`), which this file already imports for fmt_tokens/fmt_cost,
# so the four call sites take the same downward edge as everything else and the loader
# has nothing left to load. Its entry in _deps.KNOWN_LAYER_DEBT went with it — that
# list may only shrink, and only deliberately.


# --- gate evaluation ------------------------------------------------------------
def evaluate_gate(summary, conditions):
    """Return the list of FAILED condition names."""
    failed = []
    for c in conditions:
        if c == "invalid" and not summary["valid"]:
            failed.append(c)
        elif c == "open-high-bugs" and summary["bugs"]["openHighSeverity"] > 0:
            failed.append(c)
        elif c == "open-bugs" and summary["bugs"]["open"] > 0:
            failed.append(c)
        elif c == "blocked-tasks" and summary["tasks"]["byStatus"].get(
                "blocked", 0) > 0:
            failed.append(c)
        elif c == "in-progress" and (
                summary["tasks"]["byStatus"].get("in_progress", 0) > 0
                or any(p.get("status") == "in_progress"
                       for p in summary["phases"])):
            failed.append(c)
        elif c in ("over-budget", "budget-80") and budget_breaches(
                summary, BUDGET_WARN_PCT if c == "budget-80" else 100.0):
            failed.append(c)
    return failed


def _budget_detail(summary, threshold_pct):
    """Name the phases and their numbers, never just the count.

    "2 phase(s) over budget" sends the reader hunting; the whole point of tying spend
    to the plan is that it can say WHICH phase and by how much."""
    rows = budget_breaches(summary, threshold_pct)
    if not rows:
        return "no phase past %.0f%%" % threshold_pct
    parts = ["%s at %.0f%% (%s of %s)"
             % (p.get("id"), p.get("pct") or 0,
                _fmt.fmt_cost(p.get("spent")), _fmt.fmt_cost(p.get("budget")))
             for p in sorted(rows, key=lambda x: -(x.get("pct") or 0))[:3]]
    more = "" if len(rows) <= 3 else ", +%d more" % (len(rows) - 3)
    return "; ".join(parts) + more


def budget_breaches(summary, threshold_pct):
    """Phases at or past `threshold_pct` of their declared budget.

    Returns [] when nothing is metered or no phase declares a budget — a repo with
    no budgets must never trip a budget gate, and an unbudgeted phase is not a phase
    at zero. Reads the block `phase_budgets` already computed rather than recomputing
    a percentage from spend and budget, so the "what counts as a budget" rule lives
    in exactly one place."""
    budgets = ((summary or {}).get("usage") or {}).get("budgets") or {}
    out = []
    for p in budgets.get("phases") or []:
        pct = p.get("pct")
        if p.get("budget") and pct is not None and pct >= threshold_pct:
            out.append(p)
    return out


def _extract_opt(args, flag):
    """Pull `--flag value` out of args; return the value or None."""
    if flag in args:
        i = args.index(flag)
        if i + 1 >= len(args):
            return "__MISSING__"
        val = args[i + 1]
        del args[i:i + 2]
        return val
    return None


def main(argv):
    args = list(argv)
    want_json = "--json" in args
    want_gate = "--gate" in args
    want_discovery = "--discovery" in args
    for flag in ("--json", "--gate", "--discovery"):
        while flag in args:
            args.remove(flag)
    if want_discovery and not want_json:
        sys.stderr.write("usage: --discovery requires --json (it enriches the "
                         "machine payload only)\n")
        return 2

    # --submodules <.gitmodules path> [--git-root <prefix>]: preflight guard,
    # exits 1 when a task file lives inside a submodule. Standalone mode.
    gitmodules = _extract_opt(args, "--submodules")
    git_root_prefix = _extract_opt(args, "--git-root") or ""
    # --phase <id>: scope the HUMAN render to one phase. /audit:phase and
    # /audit:next need a deterministic entry view; their per-task progress lines are
    # emitted as the work happens and cannot be pre-rendered, so this covers the
    # half that can be, rather than pretending to cover both.
    only_phase = _extract_opt(args, "--phase")
    if only_phase == "__MISSING__":
        sys.stderr.write("usage: --phase <phaseId>\n")
        return 2
    if git_root_prefix == "__MISSING__":
        sys.stderr.write("usage: --git-root <prefix>\n")
        return 2
    # --color auto|always|never: ANSI for the human render only (--json and
    # --gate output stay plain). Resolution lives in _cli_fmt - the one place
    # CLI color lives.
    color = _extract_opt(args, "--color")
    if color is not None and color not in _cli_fmt.MODES:
        sys.stderr.write("usage: --color <%s>\n" % "|".join(_cli_fmt.MODES))
        return 2
    pt = _cli_fmt.painter(color or "auto")

    conditions = list(DEFAULT_GATE)
    if "--fail-on" in args:
        i = args.index("--fail-on")
        if i + 1 >= len(args):
            sys.stderr.write("usage: --fail-on <%s>[,...]\n" % "|".join(CONDITIONS))
            return 2
        conditions = [c.strip() for c in args[i + 1].split(",") if c.strip()]
        unknown = [c for c in conditions if c not in CONDITIONS]
        if unknown:
            sys.stderr.write("unknown condition(s): %s (known: %s)\n"
                             % (", ".join(unknown), ", ".join(CONDITIONS)))
            return 2
        del args[i:i + 2]
    if len(args) != 1:
        sys.stderr.write(
            "usage: audit-status.py <manifest> [--json [--discovery]] [--gate] "
            "[--phase <id>] [--color auto|always|never] [--fail-on <c1,c2,...>] "
            "[--submodules <.gitmodules> [--git-root <prefix>]]\n")
        return 2

    try:
        manifest = _mio.load_manifest(args[0])
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n" % (args[0], exc))
        return 2
    if not isinstance(manifest, dict):
        sys.stderr.write("ERROR: %s is not a JSON object (got %s)\n"
                         % (args[0], type(manifest).__name__))
        return 2

    if gitmodules is not None:
        if gitmodules == "__MISSING__":
            sys.stderr.write("usage: --submodules <path-to-.gitmodules>\n")
            return 2
        try:
            with open(gitmodules, "r", encoding="utf-8") as fh:
                sub_paths = parse_gitmodules(fh.read())
        except (FileNotFoundError, NotADirectoryError):
            sub_paths = []  # no .gitmodules => no submodules => clean
        except Exception as exc:
            sys.stderr.write("ERROR: cannot read %s: %s\n" % (gitmodules, exc))
            return 2
        conflicts = submodule_conflicts(manifest, sub_paths, git_root_prefix)
        if conflicts:
            for tid, f, sub in conflicts:
                print("SUBMODULE CONFLICT: task %s file '%s' is inside submodule '%s'"
                      % (tid, f, sub))
            print("\n%d task file(s) live inside a submodule — the orchestrator "
                  "cannot commit them from the parent repo. Point meta.gitRoot at "
                  "the submodule, or remove those files from the task(s)."
                  % len(conflicts))
            return 1
        print("OK: no task files inside submodules (%d submodule(s) checked)"
              % len(sub_paths))
        return 0

    vm = _load_validator()
    try:
        findings, warnings = vm.validate(manifest)
    except Exception as exc:  # defensive
        findings, warnings = ["internal validator error: %s" % exc], []

    summary = rollup(manifest, findings, warnings,
                     usage=usage_summary(manifest, args[0]))

    if want_discovery:
        # CLAUDE_PROJECT_DIR is how Claude Code names the project on every
        # invocation it makes; a plain CLI run means "here". The manifest is NOT
        # the anchor on purpose - it may live under docs/audit/ while the skills
        # live at the project root.
        summary["discovery"] = discovery_block(
            os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())

    if want_gate:
        failed = evaluate_gate(summary, conditions)
        summary["gate"] = {
            "conditions": conditions,
            "failed": failed,
            "passed": [c for c in conditions if c not in failed],
        }

    if want_json:
        print(json.dumps(summary, indent=2))
    elif not want_gate:
        # A bare invocation now renders for a human. It used to print raw JSON and
        # leave commands/status.md telling the model how to lay it out, which cost
        # tokens on every call and produced a different layout each time — the exact
        # thing commands/usage.md refuses to do. `--json` is unchanged for machines.
        if only_phase:
            known = [p.get("id") for p in summary["phases"]]
            if only_phase not in known:
                sys.stderr.write("ERROR: no phase %r in %s (have: %s)\n"
                                 % (only_phase, args[0], ", ".join(
                                     str(k) for k in known)))
                return 2
        print(render_status(manifest, summary, only_phase=only_phase, pt=pt))

    if want_gate:
        failed = summary["gate"]["failed"]
        if failed:
            for c in failed:
                detail = {
                    "invalid": "%d validator finding(s)" % summary["findings"],
                    "open-high-bugs": "%d open high-severity bug(s)"
                                      % summary["bugs"]["openHighSeverity"],
                    "open-bugs": "%d open bug(s)" % summary["bugs"]["open"],
                    "blocked-tasks": "%d blocked task(s)"
                                     % summary["tasks"]["byStatus"].get("blocked", 0),
                    "in-progress": "work in progress",
                    "over-budget": _budget_detail(summary, 100.0),
                    "budget-80": _budget_detail(summary, BUDGET_WARN_PCT),
                }.get(c, "")
                print("GATE FAILED: %s (%s)" % (c, detail))
            return 1
        print("GATE PASSED: %s" % ", ".join(conditions))
    return 0


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv:
        # Answers rather than falling through to `main`, which would read the flag
        # as a manifest path. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("audit-status.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_audit_status.py - run that file instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
