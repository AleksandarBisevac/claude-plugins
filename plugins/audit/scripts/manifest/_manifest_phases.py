#!/usr/bin/env python3
"""
The one walk over every phase and every task, and the three checks it makes on
the way.

Split out of `_manifest_rules.py`. This is the half of that file's
`# --- validate: one walk ---` seam that PRODUCES the index rather than reading
it: `_walk_phases` visits each phase and each task once, checks the per-object
rules a phase carries (its parallel-run claim, its area tag, its budget, its
sign-off consistency) and returns five named accumulators the checks in
`_manifest_crossrefs` then read.

THE WALK STAYS ONE PASS ON PURPOSE, and that is the whole reason the index is a
return value rather than five separate walks: splitting it per-question would
visit every task four times and would let two of them disagree about which
objects were skipped as malformed.

`_check_claim`, `_check_area_tag` and `_check_areas` live here because the walk
is their only caller and a phase is their only subject. `_check_areas` is the
odd one - it is called by `validate()` directly rather than from inside the
loop, because two of its three questions are about the REGISTRY (`meta.areas`)
rather than about any one phase.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__manifest_phases.py` - see
`plugins/audit/tests/_harness.py`.
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

import _manifest_io as _mio  # noqa: E402  (TERMINAL: what 'finished' means everywhere)
import _areas  # noqa: E402  (meta.areas registry + the resolution every surface shares)
import _manifest_vocab as _vocab  # noqa: E402  (the words, and the shared shape checks)
import _ado_parent as _parent  # noqa: E402  (what an `adoParent` declaration may say)

# Thin module-level aliases, not copies: the bodies below were moved out of
# `_manifest_rules.py` unchanged, and an alias keeps them reading the same names
# while there is still exactly one definition of each. A case pins the identity.
CLAIM_KEYS = _vocab.CLAIM_KEYS
KNOWN_PHASE = _vocab.KNOWN_PHASE
KNOWN_TASK = _vocab.KNOWN_TASK
RISK = _vocab.RISK
STATUS = _vocab.STATUS
TESTS_MODE = _vocab.TESTS_MODE
TERMINAL = _mio.TERMINAL
_check_ado = _vocab._check_ado
_require_fields = _vocab._require_fields
_safe_list = _vocab._safe_list
_unknown_keys = _vocab._unknown_keys


# --- what a phase carries --------------------------------------------------------
def _check_claim(phase, pwhere, findings, warnings):
    """Validate an optional parallel-run `claim` on a phase (v0.15 sharded layout).

    A claim records which session/host/branch is running a phase so concurrent work
    across machines is coordinated (and a same-phase double-claim shows up as a shard
    merge conflict). Shape errors are findings; a claim missing recommended keys, or one
    left on a finished phase (stale — should be released), is a warning."""
    if "claim" not in phase:
        return
    claim = phase.get("claim")
    if claim is None:
        return
    if not isinstance(claim, dict):
        findings.append("%s: claim must be an object {sessionId, host, branch, at}, got %s"
                        % (pwhere, type(claim).__name__))
        return
    missing = [k for k in CLAIM_KEYS if not claim.get(k)]
    if missing:
        warnings.append("%s: claim is missing %s — a claim should identify the "
                        "session/host/branch holding the phase" % (pwhere, ", ".join(missing)))
    if phase.get("status") in ("done", "cancelled", "blocked"):
        warnings.append("%s: has a claim but status is %r — a finished/blocked phase should "
                        "release its claim (stale claim)" % (pwhere, phase.get("status")))


def _check_area_tag(phase, pwhere, findings):
    """A phase's `area` must be a tag or a list of them (v0.16 shape, v0.28 meaning).

    Shape only — WHICH tags are legal is not this function's business and is not
    anybody's: free text stays legal forever. But `area: 3` and `area: {...}`
    normalise to NO tags at all, so the phase silently leaves every grouping and
    resolves against no area. Silence is the reason this is worth a finding."""
    if "area" not in phase:
        return
    area = phase.get("area")
    if area is None or isinstance(area, str):
        return
    if not isinstance(area, list):
        findings.append("%s: area must be a tag or a list of tags, got %s"
                        % (pwhere, type(area).__name__))
        return
    bad = [a for a in area if not isinstance(a, str) or not a.strip()]
    if bad:
        findings.append("%s: every area tag must be a non-empty string (%d bad: %s)"
                        % (pwhere, len(bad),
                           _output.some_of(bad, render=repr)))


def _check_areas(manifest):
    """The `meta.areas` registry, and the phases that name it (v0.28).

    Returns (findings, warnings). It used to take both lists and write into
    them; every direct child of `validate()` returns its own pair now, so no
    caller can depend on the order two of them happen to run in, and a piece
    can be exercised from a case without being handed two lists to inspect
    afterwards.

    Three questions, and only the first can invalidate a manifest:

      * is the registry SHAPED like a registry — findings, same as any other
        wrong type in this file;
      * does every tag a phase carries have an entry — warnings, and ONLY when
        the manifest registers areas at all. A project that tags freely and
        registers nothing is using the v0.16 feature exactly as designed, and
        warning it would be this validator nagging about a feature not in use.
        A project that DOES register is one where an unregistered tag is nearly
        always a typo of a registered one — and a typo'd tag quietly resolves to
        no area, so the reviewer and the skills the author expected never happen;
      * do a phase's areas AGREE about its reviewer — a warning naming the
        winner, because written order decides and a silent tie-break is a
        reviewer nobody can explain.
    """
    findings, warnings = [], []
    meta = manifest.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    if "areas" in meta:
        f, w = _areas.validate_registry(meta.get("areas"))
        findings.extend(f)
        warnings.extend(w)
    for pid, tag in _areas.unregistered_tags(manifest):
        warnings.append("phase %s: area tag %r has no entry in meta.areas — it "
                        "groups and filters, but resolves to no root, no default "
                        "reviewer and no default skills (typo? free-text tags are "
                        "legal)" % (pid, tag))
    for phase in manifest.get("phases") or []:
        if not isinstance(phase, dict):
            continue
        clash = _areas.review_skill_conflicts(manifest, phase)
        if clash:
            # json.dumps, not %r: the values came out of a JSON file and go back to
            # someone editing one, and `None` is not something they can type there.
            # A null IS one of the disagreeing answers here — an area saying "tests
            # sign this off" disagrees with an area naming a reviewer.
            warnings.append(
                "phase %s: areas %s each set a different reviewSkill — written "
                "order decides, so %s (from area %s) is the one that runs"
                % (phase.get("id") or "?",
                   ", ".join("%s=%s" % (t, json.dumps(s)) for t, s in clash),
                   json.dumps(clash[0][1]), clash[0][0]))
    return (findings, warnings)


def _add_parent(obj, where, findings, warnings):
    """Fold `_ado_parent`'s shape check into the walk's two accumulators.

    A three-line adapter rather than a call at each of the two sites, because
    the walk writes into lists and `_ado_parent` returns a pair - and the day
    that mismatch is spelled out twice is the day one of the two forgets the
    warnings half. `_ado_parent` is at layer 1 beside `_manifest_vocab`, so
    this module reaches it downward like any other word it borrows.
    """
    pf, pw = _parent.declaration_findings(obj, where)
    findings.extend(pf)
    warnings.extend(pw)


# --- the walk --------------------------------------------------------------------
def _walk_phases(phases):
    """One pass over every phase and every task: (index, findings, warnings).

    THE INDEX IS WHY THIS WAS NEVER CUT OUT BEFORE. Five accumulating locals
    ride this single walk and each is read by a DIFFERENT check further down,
    which is exactly the coupling that kept `validate()` in one 354-line piece.
    Naming them turns the coupling into an argument:

      phase_ids     every phase id, document order   -> unique ids, proposals
      task_ids      every task id, document order    -> unique ids, refs,
                                                        fileIndex, bugs
      task_by_id    id -> the task object            -> bug reciprocity
      task_files    id -> its non-empty `files` list -> fileIndex, both ways
      bug_links     (twhere, task id, bugId) per link-> bug reciprocity

    `task_files` holds only tasks whose `files` is a non-empty list, because
    that is the question `_check_file_index` asks of it; a task with no files
    is absent rather than mapped to [], and the fileIndex check reads it with
    `.items()` only.

    The walk stays ONE pass on purpose. Splitting it per-question would visit
    every task four times to build four dicts, and would let two of them
    disagree about which objects were skipped as malformed.
    """
    f, w = [], []
    phase_ids, task_ids = [], []
    task_bug_links = []       # (twhere, task_id, bugId)
    task_by_id = {}
    task_files = {}           # task_id -> files list

    for pi, phase in enumerate(phases):
        if not isinstance(phase, dict):
            f.append("phases[%d]: not an object" % pi)
            continue
        pid = phase.get("id")
        pwhere = "phase %s" % (pid or ("phases[%d]" % pi))
        _require_fields(phase, pwhere, f)
        _unknown_keys(phase, KNOWN_PHASE, pwhere, w)
        # connector v2: phaseWorkItems writes a phase-level adoLink
        _check_ado(phase, pwhere, f)
        # U-PARENT: the AUTHORED half beside it. Shape only here - where the
        # parent resolves to and whether that place can be true are questions
        # about the whole plan, and `_manifest_crossrefs` asks them.
        _add_parent(phase, pwhere, f, w)
        if pid:
            phase_ids.append(pid)
        if phase.get("status") not in STATUS:
            f.append("%s: status %r not in %s" % (pwhere, phase.get("status"), list(STATUS)))
        _check_claim(phase, pwhere, f, w)
        _check_area_tag(phase, pwhere, f)
        # A budget of 0 or a negative one is not a budget, and a string is a typo
        # that would silently render as "no budget". Both are worth saying out loud.
        if "budgetUSD" in phase:
            budget = phase.get("budgetUSD")
            if isinstance(budget, bool) or not isinstance(budget, (int, float)):
                f.append("%s: budgetUSD must be a number, got %s"
                         % (pwhere, type(budget).__name__))
            elif budget <= 0:
                f.append("%s: budgetUSD must be greater than 0 (got %s) — omit the "
                         "key entirely for 'no budget'" % (pwhere, budget))

        tasks_val = phase.get("tasks")
        if "tasks" not in phase:
            w.append("%s: no 'tasks' key — the schema requires one (an empty "
                     "phase should carry an empty list)" % pwhere)
        elif not isinstance(tasks_val, list):
            f.append("%s: tasks must be an array, got %s"
                     % (pwhere, type(tasks_val).__name__))
        # A phase is 'done' only after sign-off, which requires every task done.
        # A done phase with a non-done task is a stale-status slip the schema
        # can't express (e.g. a hand-regenerated roadmap that flipped the phase
        # but not its tasks).
        if phase.get("status") == "done":
            # FINISHED, not done: a task the team cancelled is settled, and a
            # phase that signed off around it is not a slip. Only genuinely
            # unfinished work (pending / in_progress / blocked) contradicts it.
            not_done = [t.get("id") or "?" for t in _safe_list(tasks_val)
                        if isinstance(t, dict) and t.get("status") not in TERMINAL]
            if not_done:
                f.append("%s: status 'done' but %d task(s) are not finished (%s) "
                         "— a phase is done only after ALL its tasks are done "
                         "or cancelled (sign-off)"
                         % (pwhere, len(not_done),
                            _output.some_of(not_done)))
        for ti, task in enumerate(_safe_list(tasks_val)):
            if not isinstance(task, dict):
                f.append("%s tasks[%d]: not an object" % (pwhere, ti))
                continue
            tid = task.get("id")
            twhere = "task %s" % (tid or ("%s.tasks[%d]" % (pwhere, ti)))
            _require_fields(task, twhere, f)
            _unknown_keys(task, KNOWN_TASK, twhere, w)
            if tid:
                task_ids.append(tid)
                task_by_id[tid] = task
                files = task.get("files")
                if isinstance(files, list) and files:
                    task_files[tid] = files
            if task.get("status") not in STATUS:
                f.append("%s: status %r not in %s" % (twhere, task.get("status"), list(STATUS)))
            if (phase.get("status") == "pending"
                    and task.get("status") == "in_progress"):
                w.append("%s is in_progress but its %s is still 'pending' — "
                         "pre-0.3 manifest? /audit:resume expects the phase to "
                         "be 'in_progress' too" % (twhere, pwhere))
            tests = task.get("tests")
            if "tests" in task and tests is not None and not isinstance(tests, dict):
                f.append("%s: tests must be an object with a 'mode', got %s"
                         % (twhere, type(tests).__name__))
            if isinstance(tests, dict) and tests.get("mode") not in TESTS_MODE:
                f.append("%s: tests.mode %r not in %s" % (twhere, tests.get("mode"), list(TESTS_MODE)))
            if "risk" in task and task.get("risk") not in RISK:
                f.append("%s: risk %r not in %s" % (twhere, task.get("risk"), ["low", "med", "high", None]))
            _check_ado(task, twhere, f)
            _add_parent(task, twhere, f, w)
            # The id-prefix rule (workstream B) -- the hand-move detector.
            # /audit:task move renumbers a task into its target phase, so an id
            # that does not match `<phaseId>.<int>` means the object was dragged
            # by hand. A WARNING only: legacy manifests with free-form ids must
            # never go red over bookkeeping.
            if tid and pid and not re.match(
                    r"^%s\.\d+$" % re.escape(str(pid)), str(tid)):
                w.append("%s: id does not follow its phase's prefix (%s.<n>) "
                         "-- moved by hand? /audit:task move renumbers, "
                         "rewrites references and records a task.move row. "
                         "Informational; legacy ids stay legal" % (twhere, pid))
            if "movedFrom" in task:
                mf = task.get("movedFrom")
                if mf is not None and not isinstance(mf, dict):
                    w.append("%s: movedFrom should be an object "
                             "{id, phase, at}, got %s"
                             % (twhere, type(mf).__name__))
                elif isinstance(mf, dict):
                    lacking = [k for k in ("id", "phase", "at")
                               if not mf.get(k)]
                    if lacking:
                        w.append("%s: movedFrom is missing %s -- /audit:task "
                                 "move writes all three"
                                 % (twhere, ", ".join(lacking)))
            if task.get("bugId"):
                task_bug_links.append((twhere, tid, task["bugId"]))

    return ({"phase_ids": phase_ids, "task_ids": task_ids,
             "task_by_id": task_by_id, "task_files": task_files,
             "bug_links": task_bug_links}, f, w)

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
        print("_manifest_phases.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__manifest_phases.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
