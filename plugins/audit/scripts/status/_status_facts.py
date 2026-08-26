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
import _priority  # noqa: E402  (the ONE expression of execution order, and the skip note)

# --- vocabulary -----------------------------------------------------------------
CONDITIONS = ("invalid", "open-high-bugs", "open-bugs", "blocked-tasks",
              "in-progress", "over-budget", "budget-80", "invariant-breach",
              "failing-tests", "no-test-evidence")
# Neither budget condition is in the default gate. Spend is a signal, not a defect:
# a phase at 105% may be entirely justified, and failing someone's merge over it
# without them asking would make the whole gate something to switch off. Opt in with
# --fail-on when a budget is a commitment rather than an estimate.
#
# NEITHER TEST-EVIDENCE CONDITION IS IN IT EITHER, and `no-test-evidence` least of
# all: a repository that has never recorded a run carries no pointers anywhere, so
# a default holding it would fail every build on the day the plugin was upgraded --
# which is exactly the "adding a key changes behaviour for a config that does not
# set it" failure COMPATIBILITY.md refuses. `failing-tests` is out one step along
# the same road: a plan holding a red pointer somebody has already triaged would
# start blocking merges nobody asked it to block. Both are opt-in, and moving
# either into this tuple is a deliberate edit a case makes you make on purpose.
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
# `{phase id or task id: status}` — what a `blockedBy`/`dependsOn` ref resolves
# through. `ready_tasks` and `unmet_refs` each built this by hand, identically; it
# moved DOWN to `_manifest_io` when a third caller appeared that this module cannot
# serve — `_manifest_crossrefs` sits at layer 2 beside this one and needs the same
# map to say whether a PINNED phase is waiting on unfinished work. The name stays
# here because ~600 lines of rendering in `audit-status.py` spell it unqualified,
# and the tie-break reasoning went with the body. An alias, never a second walk.
_status_index = _mio.status_index


def _phase_positions(manifest):
    """`{id(phase dict): its index in phases[]}` — the manifest order, by object.

    Keyed by identity rather than by `phase["id"]` because a manifest with a
    duplicate or absent phase id is exactly the manifest the read-only surfaces
    must still render: an id-keyed map would give two phases one position and
    silently re-order the ready list of a plan the validator is already
    complaining about.
    """
    if not isinstance(manifest, dict):
        return {}
    return {id(ph): i for i, ph in enumerate(manifest.get("phases") or [])
            if isinstance(ph, dict)}


def ready_tasks(manifest):
    """Task ids ready to run — mirrors /audit's readiness rule: status pending,
    own blockedBy satisfied, own dependsOn all done, phase blockedBy satisfied
    ('satisfied' = referenced task/phase is done), then SORTED by phase priority.

    THE SORT IS THE WHOLE FEATURE AND IT CANNOT CHANGE THE SET. Readiness is
    decided above, exactly as before; `_priority.rank_ready` only re-orders what
    is already ready, so a `priority` can never make an unready task ready and
    can never step over a dependency. A manifest carrying no `priority` at all
    produces the list it produced before this sort existed — every key falls
    back to (phase index, walk order), which is the document order this loop
    already emitted.
    """
    status = _status_index(manifest)
    pos = _phase_positions(manifest)

    def satisfied(refs):
        return not _mio.unsatisfied(refs, status)

    rows = []
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
            rows.append((ph, pos.get(id(ph), len(pos)), len(rows), t["id"]))
    return _priority.rank_ready(rows)


def priority_note(manifest, ready=None):
    """The one sentence about a pin that could not be honoured, or None.

    Computed here rather than in each renderer so the CLI, the Markdown report,
    the HTML report and the panel all read ONE key. `rollup()` carries it as
    `priorityNote`; `audit-status.py` prints it under READY NOW.

    `ready` is accepted so `rollup()` does not compute the ready list twice —
    the note names the task running INSTEAD of the pinned phase, which is the
    first ready id.
    """
    if not isinstance(manifest, dict):
        return None
    order_list = ready if ready is not None else ready_tasks(manifest)
    pin = _priority.pinned_but_blocked(
        [p for p in (manifest.get("phases") or []) if isinstance(p, dict)],
        unmet_refs(manifest), finished=TERMINAL)
    return _priority.note(pin, order_list[0] if order_list else None)


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


# The word `proposed` as a status surface reads it. Spelled once here rather than
# at each site that asks, because it was asked twice with two different answers.
PARKED_PROPOSAL_STATUS = "proposed"


def is_parked_proposal(raw_status):
    """Whether a proposal's status AS WRITTEN means it is still parked.

    WHAT `parked` MEANS ON A STATUS SURFACE, decided here so the header and the
    PROPOSALS block cannot each decide it. They did: the header counted entries
    that were `proposed` AND carried a payload, the block counted every entry
    whose raw status was `proposed`, and a payload-less proposed entry made the
    two lines of one render disagree by one under the same word.

    The answer is the raw status alone, and it follows the decision the proposal
    ROWS already record: a status surface reads `statusRaw`, reports what is
    there, and never invents. Whether `/audit:propose materialize` can act on an
    entry is a different question with a different answer -- `hasPayload` on the
    row, which is what puts the copy-pasteable command on the line that has one.
    An entry with nothing drafted yet is still a decision waiting on a human, so
    folding the payload into the count left it out of the count of exactly that,
    while the block below went on listing it. Counted here and listed there, or
    neither -- counted in one place and not the other is the state that made one
    render print two numbers under one word.

    Takes the RAW value, not the entry, so both callers can pass what they hold:
    `rollup` walks `proposals[]` and has the dict, `_proposal_lines` has rows
    whose `statusRaw` is that same value carried through.
    """
    return raw_status == PARKED_PROPOSAL_STATUS


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


# --- test evidence ---------------------------------------------------------------
# `task.testEvidence` / `phase.testEvidence` is a POINTER at the run that last
# exercised that subject, together with the verdict the run reached. Three
# distinctions this whole section exists to keep, each of which some surface in this
# tree has already got wrong once:
#
#   * ABSENT IS NOT FAILURE. A manifest written before the field existed, a task
#     nobody has run, and a block somebody deleted are one single state -- "no run
#     was recorded" -- and rendering the worst reading of that silence is the
#     failure the schema and COMPATIBILITY.md both name by hand.
#   * `no-checks` IS NOT A PASS. It is exit 0 over a gate that found nothing to
#     check, which is precisely the shape a green build with no tests in it has.
#   * THE POINTER IS NOT RESOLVED HERE. Whether this checkout's evidence ledger
#     actually holds that `runId` is `verify-invariants.py`'s question and
#     `/audit:doctor`'s. Nothing here opens the ledger, so nothing here may word its
#     answer as though it had.
#
# WHICH WORDS CANNOT SIGN WORK OFF. `passed` is the only verdict that signs anything
# off, and `empty-gate` -- no gate was configured at all -- is a plan's choice
# rather than a result, so neither is below. Everything else the enum declares is:
# `failed` ran to completion and came back red; `no-checks` is the exit-0-that-is-
# not-a-verdict above; `timed-out` and `cancelled` were stopped rather than answered
# (the schema pairs those two in one sentence, and splitting them here would be this
# file inventing a distinction the record does not draw); `could-not-run` means the
# runner never started -- no interpreter, an unreadable command -- so there is no
# verdict at all, which is emphatically not the same claim as a failing test.
#
# SPELLED AS A POSITIVE SET, NEVER AS "everything except passed". The enum MAY GAIN
# MEMBERS -- COMPATIBILITY.md declines to promise the list is closed -- and a
# complement would fold a word this build has never heard of into `failed`, which is
# the one reading the schema forbids by name. An unrecognised word is carried
# through as itself (`unrecognised` in the summary below, the raw word in the CLI's
# `tests` column) and is judged by nothing.
NO_SIGN_OFF_EVIDENCE = frozenset({"failed", "no-checks", "timed-out", "cancelled",
                                  "could-not-run"})
PASSED_EVIDENCE = "passed"
NO_GATE_EVIDENCE = "empty-gate"
KNOWN_EVIDENCE = frozenset(NO_SIGN_OFF_EVIDENCE
                           | {PASSED_EVIDENCE, NO_GATE_EVIDENCE})


def evidence_status(holder):
    """A task's or phase's `testEvidence.status`, or None when it records none.

    None is "no run was recorded" and is NEVER a failure -- it is the one state a
    pre-field manifest, an unrun task and a deleted block all share.

    A block that is not an object, or one carrying no usable `status`, comes back as
    that same silence rather than as a word. A half-written block caches no verdict,
    and picking one for it would be this function answering a question the manifest
    did not: the schema requires all three keys at once precisely because dropping
    the whole block is always safe, so there is never a reason to have written half.
    """
    if not isinstance(holder, dict):
        return None
    block = holder.get("testEvidence")
    if not isinstance(block, dict):
        return None
    status = block.get("status")
    return status if isinstance(status, str) and status else None


def evidence_rows(manifest):
    """One row per phase and per task the plan carries, in document order.

    `{"scope", "id", "status", "subjectStatus"}`. `status` is the recorded verdict,
    None where none is recorded; `subjectStatus` is the subject's OWN workflow
    status, which is what lets a caller ask about `done` tasks specifically without
    walking the plan a second time.

    EVERY subject is a row, including every one carrying nothing. A walk that
    yielded only the subjects holding a pointer could not answer "which done task
    has none", and that question is half of what this block is for.

    Ids are carried as written, `None` included: a subject with no id is the
    validator's finding to report, and dropping it here would quietly shrink a gate
    the reader believes covers the plan.
    """
    if not isinstance(manifest, dict):
        return []
    rows = []
    for ph in (manifest.get("phases") or []):
        if not isinstance(ph, dict):
            continue
        rows.append({"scope": "phase", "id": ph.get("id"),
                     "status": evidence_status(ph),
                     "subjectStatus": ph.get("status")})
        for t in (ph.get("tasks") or []):
            if not isinstance(t, dict):
                continue
            rows.append({"scope": "task", "id": t.get("id"),
                         "status": evidence_status(t),
                         "subjectStatus": t.get("status")})
    return rows


def test_evidence_summary(manifest):
    """What the plan's `testEvidence` pointers SAY -- the block `rollup` carries.

    ALWAYS PRESENT AND ALWAYS COMPLETE, every list included even when empty, for the
    reason `priorityNote` is always a key: a block that appeared only when it had
    something to report could not be told from a block nobody computed.

    `failing` and `missingOnDone` are the two the gate reads, and they are
    deliberately different questions rather than two ways to trip one condition.
    `failing` is a RECORDED VERDICT that cannot sign work off. `missingOnDone` is a
    SUBJECT the plan calls `done` with no pointer at all -- an ABSENCE, which is not
    a verdict and must never be counted as one; that is why it is its own opt-in
    condition, and why a repository that has never recorded a run trips neither.

    BOTH READ BOTH SCOPES, and `missingOnDone` did not. A phase carries its own
    pointer -- `run-test-gate.py --record` writes `phase.testEvidence` at sign-off
    and no task pointer stands in for it -- and every other reader in this tree
    walks phases and tasks alike: `failing` above, `_doctor_completions`'
    pointer check, `_invariants`' `evidence-committed`. A `missingOnDone` filtered
    to `scope == "task"` left the one subject whose sign-off this condition exists
    to ask about answering nothing at all, while its sibling condition read that
    same subject happily -- one vocabulary, two scopes, and nothing saying so.

    `unrecognised` is the default arm the schema asks for, made visible instead of
    silent. A status word this build does not know trips nothing here -- folding it
    into `failed` is the reading the schema forbids -- and a consumer that wants to
    act on one now can, without this file having guessed what it means.

    NOTHING IS RESOLVED AGAINST THE LEDGER. Every row is what the manifest says
    about itself; whether a `runId` names a run this checkout holds is asked by
    `verify-invariants.py` and `_doctor_completions`, and answered nowhere near here.
    """
    rows = evidence_rows(manifest)
    recorded = [r for r in rows if r["status"] is not None]
    return {
        "recorded": len(recorded),
        "byStatus": _by_status_values([r["status"] for r in recorded]),
        "failing": [r for r in recorded
                    if r["status"] in NO_SIGN_OFF_EVIDENCE],
        "unrecognised": [r for r in recorded
                         if r["status"] not in KNOWN_EVIDENCE],
        "missingOnDone": [r for r in rows
                          if r["status"] is None
                          and r["subjectStatus"] == "done"],
    }


# Which of the block's keys name a subject list, DERIVED from the block itself
# over an empty plan rather than typed a second time. A subject list added to
# `test_evidence_summary` later is legal here without an edit, and `recorded` (an
# int) and `byStatus` (a dict) can never be written into this set by hand.
EVIDENCE_SUBJECT_KEYS = tuple(sorted(
    k for k, v in test_evidence_summary(None).items() if isinstance(v, list)))


def evidence_subjects(summary, key):
    """One of the test-evidence block's subject lists, off a rollup summary.

    `[]` when the block is absent, and here that really does mean "nothing to
    report" -- which is the OPPOSITE of `invariant_breaches` below, for the
    opposite reason. That block is INJECTED by a command that may or may not have
    run the checks, so its absence is "nobody looked". This one is computed by
    `rollup` unconditionally out of the manifest it was handed, so a summary
    without it is a caller that never built one rather than a read that failed:
    there is no unasked question for an empty list to be hiding.

    A KEY THAT NAMES NO SUBJECT LIST RAISES, which is the half `block.get(key) or
    []` got wrong. `recorded` is an int and `byStatus` a dict, so asking for either
    handed the caller the int or the dict back out of a function that promises a
    list -- and only when it was TRUTHY, so an empty plan answered correctly and a
    populated one did not, which is the shape nobody catches by trying it once.

    REFUSED RATHER THAN ANSWERED `[]`, because every caller is a gate condition and
    `[]` is the arm that reads "nothing to report": a mistyped key answered that
    way passes a build silently, which is worse news than the leak it replaces. A
    wrong key is a programming error, so it fails at the call with the legal set in
    the message. A legal key whose VALUE is not a list is still `[]` -- that is a
    hand-built summary, which is data rather than a caller, and the reasoning for
    an absent block applies to it unchanged.
    """
    if key not in EVIDENCE_SUBJECT_KEYS:
        raise ValueError(
            "%r names no test-evidence subject list; the subject lists are %s"
            % (key, ", ".join(EVIDENCE_SUBJECT_KEYS)))
    block = (summary or {}).get("testEvidence")
    if not isinstance(block, dict):
        return []
    value = block.get(key)
    return value if isinstance(value, list) else []


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
    # Where each phase sits in EXECUTION order, computed over `phases` — the same
    # filtered list every row below is built from, so `porder[i]` belongs to
    # `phase_entries[i]`. Over ALL of them and never over a view: a rank taken
    # across a subset is a different number, and the panel filters its rows in the
    # browser (search, status, which segment) long after this is stamped.
    #
    # UNCONDITIONAL, which is the whole point. `_report_html.phase_ranks` emits
    # nothing when no phase is pinned because it hides its sort control in the same
    # breath; the panel offers the control always, so a rank withheld here is a
    # client left to invent a fallback comparator — the very thing this key exists
    # to remove. With nothing pinned `ranks()` is the identity, so the option
    # degrades to plan order rather than to a second opinion about it.
    porder = _priority.ranks(phases)
    phase_entries = [{
        "id": p.get("id"), "title": p.get("title"),
        "status": p.get("status"), "area": areas_of(p.get("area")),
        "desiredOutcome": p.get("desiredOutcome"),
        # The tier as `_priority` reads it, not the raw field: `priority: "1"`
        # orders nothing, so a badge rendered off the raw value would advertise
        # a pin the run does not honour. `None` means unprioritised.
        "priority": _priority.tier_of(p),
        # The tier is what a READER understands; this is the ordering index, and
        # the two are not interchangeable. `priority` renders as a badge and is
        # never sorted on; `porder` sorts and is never rendered. Named after the
        # report's `data-porder` on purpose, so one grep finds every reader of the
        # one rank across both surfaces.
        "porder": porder[i],
        "done": sum(1 for t in (p.get("tasks") or [])
                    if isinstance(t, dict) and t.get("status") == "done"),
        # ca: counted separately, never folded into `done`. A bar that showed
        # 5/5 for three landed tasks and two dropped ones would be a lie in the
        # one direction that matters.
        "cancelled": sum(1 for t in (p.get("tasks") or [])
                         if isinstance(t, dict) and t.get("status") == "cancelled"),
        "total": sum(1 for t in (p.get("tasks") or []) if isinstance(t, dict)),
    } for i, p in enumerate(phases)]
    # group phases by each of their `area` tags (a phase with several tags counts
    # under each; untagged phases are simply not grouped)
    areas = {}
    for e in phase_entries:
        for a in e["area"]:
            g = areas.setdefault(a, {"phases": 0, "done": 0, "total": 0,
                                     "cancelled": 0})
            g["phases"] += 1
            g["done"] += e["done"]
            g["total"] += e["total"]
            # F192, at the THIRD site. The per-phase count and the plan-wide one
            # both explain a total that cannot be reached; this rollup carries the
            # same `done/total` and had no count to explain it with, so closing
            # only the two the report named would have left the third saying the
            # same unreachable thing.
            g["cancelled"] += e["cancelled"]
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
        # What the plan's `testEvidence` pointers SAY, never what the ledger holds.
        # Unconditional and whole, the same call `priorityNote` makes below: an
        # empty `failing` list and a block nobody computed must not look alike, and
        # the CLI, the report and the panel all read the one key rather than each
        # walking the plan for it.
        "testEvidence": test_evidence_summary(manifest),
        # "parked" is every entry whose status AS WRITTEN is 'proposed', payload
        # or not — `is_parked_proposal` holds the decision and says why. It used
        # to require a payload as well, which is a count of what
        # /audit:propose materialize can act on rather than of what is waiting on
        # a human, and it disagreed with the PROPOSALS block that prints beneath
        # it. Legacy free-form entries (a status outside the vocabulary) show up
        # in total/byStatus and are not parked.
        "proposals": {"total": len(props), "byStatus": _by_status(props),
                      "parked": sum(1 for x in props
                                    if is_parked_proposal(x.get("status")))},
        "ready": ready_tasks(manifest),
    }
    # The sister key to "ready", and the reason the priority feature needed no
    # change in four renderers: a pin the dependencies would not let through is
    # SAID once, here, and the CLI, both reports and the panel each print this
    # one string. `None` when there is nothing to say — a key that is always
    # present is a key no consumer has to probe for.
    out["priorityNote"] = priority_note(manifest, out["ready"])
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
        # A RECORDED verdict that cannot sign work off. Absence is not one of them
        # and cannot reach this arm: `test_evidence_summary` only ever puts a row
        # in `failing` when a status was actually written down.
        elif c == "failing-tests" and evidence_subjects(summary, "failing"):
            failed.append(c)
        # ...and the other question entirely: a SUBJECT the plan calls done with
        # no pointer at all, a phase as readily as a task - the same two scopes the
        # arm above reads, because a phase's sign-off records its own run. Opt-in,
        # and never folded into the one above - "the run was red" and "there is no
        # run" are different news with different repairs.
        elif c == "no-test-evidence" and evidence_subjects(summary,
                                                           "missingOnDone"):
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
