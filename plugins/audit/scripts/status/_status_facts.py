#!/usr/bin/env python3
"""
What the manifest SAYS, as a machine-readable answer — the half of status nobody prints.

`audit-status.py` does two things that look like one: it computes the facts (which
tasks are ready, what each phase adds up to, which gate conditions failed, which
files sit inside a submodule) and it renders them for a person. Only the first is
shared. This module is that first half, and `audit-status.py` is the command that
prints it.

WHY THE SPLIT EXISTS. Three modules wanted the facts and none of them wanted the
rendering: `_panel_state` (layer 5) needs `rollup` for the panel's overview,
`audit-doctor` needs `submodule_conflicts` for its preflight, and `render-report`
needs `evaluate_gate` for the verdict at the top of the report. All three reached
them the only way a hyphenated entry point can be reached —
`_loader.load_script("audit-status.py")` — and `_deps.layer_violations()` counts
those calls, so three of the seventeen entries in `KNOWN_LAYER_DEBT` were this one
file being used as a library. Layer 2 is where all three can import it, and it is
low enough because everything here reaches only `_manifest_io` and `_areas` at
layer 1.

THE REPORT'S GATE VERDICT IS THE CASE WORTH KNOWING ABOUT. `render-report.py`
computes the verdict at layer 7 and INJECTS it into `_report_page` (layer 6),
specifically so a helper never reaches up to an entry point for it. That dance was
forced by the gate living inside a command; `evaluate_gate` and `DEFAULT_GATE` are
here now, so the constraint is gone even though the injection stayed — changing
the wiring is a separate question from retiring the edge, and one change should
not quietly answer both.

PURE, AND THAT IS WHAT MAKES IT SHAREABLE. Every function here takes parsed JSON
(or, for `parse_gitmodules`, text a caller already read) and returns a value. No
file is opened, no process is run, no module state is written. `usage_summary`
and `discovery_block` do read the world, so they stayed in `audit-status.py`
where a command can own their failure modes.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__status_facts.py` — see `plugins/audit/tests/_harness.py`.
"""
import re
import os
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

# --- vocabulary -----------------------------------------------------------------
CONDITIONS = ("invalid", "open-high-bugs", "open-bugs", "blocked-tasks",
              "in-progress", "over-budget", "budget-80", "invariant-breach")
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
        elif c == "invariant-breach" and invariant_breaches(summary) is not None:
            failed.append(c)
    return failed


def invariant_breaches(summary):
    """The post-hoc breach list, or None when it was never computed. Never [].

    THREE STATES, AND A BOOLEAN WOULD HAVE TWO. The block arrives INJECTED by
    `audit-status.py`, which is where the git and ledger reads live (this module
    is layer 2 and `_invariants` is layer 4); the gate itself only reads what it
    was handed. So the interesting question is not "were there breaches" but
    "was anything read at all" — and a summary with no block is a summary nobody
    asked, which must not pass as a clean one. `None` is "no breaches, and the
    evidence was read"; a list is what was found; and an ABSENT block is also a
    list, holding the one sentence that says so.

    `evaluate_gate` therefore trips on `is not None`, which reads oddly until you
    see that it is the only spelling under which the missing block fails.
    """
    block = (summary or {}).get("invariants")
    if not isinstance(block, dict) or not isinstance(block.get("breaches"), list):
        return ["the invariant checks did not run, so nothing about them was "
                "verified - this is not a pass"]
    return block["breaches"] or None


# `_budget_detail` sat here between these two and went back to `audit-status.py`
# with the rest of the rendering: it turns `budget_breaches` into an English
# sentence with currency in it, which needs `_fmt` and is a thing a COMMAND says.
# Keeping it would have put a formatter in the module whose whole claim is that it
# only computes — and would have made `_fmt` a dependency of every consumer of the
# rollup.


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


# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exiting silently: `--selftest` is what every other
        # file here accepts, so nothing would tell a reader whether this one ran
        # nothing or has nothing. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_status_facts.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__status_facts.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
