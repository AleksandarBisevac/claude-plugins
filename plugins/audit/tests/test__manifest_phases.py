#!/usr/bin/env python3
"""
The cases for `_manifest_phases.py` — the one walk, and what a phase carries.

`_walk_phases` is the only function in the validator that produces rather than
consumes: it visits each phase and each task once and returns a five-key INDEX
that every check in `_manifest_crossrefs` then reads. The suite treats that
index as the module's real output — a rule that stops emitting a finding is
visible from `validate()`, but an index that quietly stops recording a task id
is not, and it would silently turn four downstream checks into no-ops.

THE WALK STAYS ONE PASS. `task_files` holds only tasks whose `files` is a
non-empty list, because that is the question `_check_file_index` asks of it;
a task with no files is ABSENT rather than mapped to `[]`, and a case pins that
distinction because the fileIndex check reads it with `.items()`.

The per-phase rules here are the ones a schema cannot express: a parallel-run
claim left on a finished phase, an `area` that normalises to no tags at all, a
`budgetUSD` of zero, and a phase marked done over tasks that are not finished —
where FINISHED means done or cancelled, since a cancelled task is settled.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _manifest_phases as M                       # noqa: E402
import _manifest_io as _mio                        # noqa: E402
import _manifest_vocab as _vocab                   # noqa: E402
import _manifest_rules as _rules                   # noqa: E402


def _phase(**kw):
    p = {"id": "P0", "title": "P", "status": "pending", "tasks": []}
    p.update(kw)
    return p


def _task(tid, **kw):
    t = {"id": tid, "title": tid, "status": "pending"}
    t.update(kw)
    return t


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- the index ---
    idx, f, w = M._walk_phases([_phase(tasks=[
        _task("P0.1", files=["src/a.ts"]), _task("P0.2")])])
    check("mp1 the walk records every phase and task id in document order",
          idx["phase_ids"] == ["P0"] and idx["task_ids"] == ["P0.1", "P0.2"],
          idx)
    check("mp2 ...and `task_files` holds ONLY the tasks with a non-empty "
          "`files` list: a task with none is absent rather than mapped to [], "
          "which is exactly the question _check_file_index asks of it",
          idx["task_files"] == {"P0.1": ["src/a.ts"]}, idx["task_files"])
    check("mp3 ...and `task_by_id` indexes the task OBJECT, which is what "
          "makes the bug<->task link checkable from one side",
          idx["task_by_id"]["P0.2"]["title"] == "P0.2", "")
    idx, f, w = M._walk_phases([_phase(tasks=[_task("P0.1", bugId="BUG-1")])])
    check("mp4 ...and a task's bugId is recorded as a (where, id, bugId) link "
          "rather than resolved here - resolution needs the bugs[] half the "
          "walk has not seen",
          idx["bug_links"] == [("task P0.1", "P0.1", "BUG-1")],
          idx["bug_links"])
    idx, f, w = M._walk_phases([_phase(tasks=[])])
    check("mp5 a phase with no tasks still yields every index key, so a "
          "downstream check can read them without asking whether the walk "
          "found anything",
          sorted(idx) == ["bug_links", "phase_ids", "task_by_id", "task_files",
                          "task_ids"], sorted(idx))

    # --- the per-object rules ---
    _, f, _ = M._walk_phases(["not a phase"])
    check("mp6 a non-object phase is a finding naming its index, and the walk "
          "continues rather than raising", len(f) == 1 and "phases[0]" in f[0],
          f)
    _, f, _ = M._walk_phases([_phase(status="doing")])
    check("mp7 a status outside the vocabulary is a finding that prints the "
          "vocabulary", len(f) == 1 and "not in" in f[0], f)
    _, f, _ = M._walk_phases([_phase(status="done", tasks=[
        _task("P0.1", status="pending")])])
    check("mp8 a phase marked done over an unfinished task is a finding - "
          "sign-off means EVERY task is done or cancelled",
          any("not finished" in x for x in f), f)
    _, f, _ = M._walk_phases([_phase(status="done", tasks=[
        _task("P0.1", status="cancelled")])])
    check("mp9 ...but a CANCELLED task is settled, so a phase that signed off "
          "around it is not a slip - the case that fails if TERMINAL is "
          "narrowed back to `done`", f == [], f)

    _, f, w = M._walk_phases([_phase(status="done",
                                     claim={"sessionId": "s", "host": "h",
                                            "branch": "b"})])
    check("mp10 a claim left on a finished phase is a WARNING: it is stale "
          "bookkeeping, not a broken document",
          any("stale claim" in x for x in w), w)
    _, f, w = M._walk_phases([_phase(claim={"sessionId": "s"})])
    check("mp11 ...and a claim missing the keys that identify its holder is a "
          "warning naming them", any("host, branch" in x for x in w), w)
    _, f, w = M._walk_phases([_phase(claim="mine")])
    check("mp12 ...while a non-object claim is a FINDING: it is a shape the "
          "orchestrator would misread", len(f) == 1 and "claim must be" in f[0],
          f)

    _, f, _ = M._walk_phases([_phase(area=3)])
    check("mp13 `area: 3` is a finding, because it normalises to NO tags at "
          "all - the phase silently leaves every grouping and resolves "
          "against no area", len(f) == 1 and "area must be" in f[0], f)
    _, f, _ = M._walk_phases([_phase(area=["app", "web"])])
    check("mp14 ...and a list of tags is legal, which is the case that fails "
          "if the shape check is tightened to a bare string", f == [], f)

    _, f, _ = M._walk_phases([_phase(budgetUSD=0)])
    check("mp15 a budget of zero is a finding pointing at the exit: omit the "
          "key for 'no budget', because a zero renders as a phase at 0%",
          len(f) == 1 and "greater than 0" in f[0], f)
    _, f, _ = M._walk_phases([_phase(budgetUSD=True)])
    check("mp16 ...and a boolean budget is a finding too: bool is an int "
          "subclass, so `true` would otherwise pass as the number 1",
          len(f) == 1 and "must be a number" in f[0], f)

    _, f, w = M._walk_phases([_phase(tasks=[_task("T9")])])
    check("mp17 a task id that does not follow its phase's prefix is a "
          "WARNING, never a finding: legacy free-form ids stay legal",
          f == [] and any("phase's prefix" in x for x in w), (f, w))

    # --- _check_areas, the registry half ---
    f, w = M._check_areas({"meta": {"areas": {"app": {"root": "src"}}},
                           "phases": [_phase(area="app")]})
    check("mp18 a registered tag a phase uses is silent",
          f == [] and w == [], "f=%r w=%r" % (f, w))
    f, w = M._check_areas({"meta": {"areas": {"app": {"root": "src"}}},
                           "phases": [_phase(area="ap")]})
    check("mp19 ...and an unregistered tag is a WARNING once the manifest "
          "registers areas at all, because then it is nearly always a typo",
          f == [] and any("has no entry in meta.areas" in x for x in w), w)
    f, w = M._check_areas({"meta": {}, "phases": [_phase(area="ap")]})
    check("mp20 ...while a project that tags freely and registers NOTHING "
          "gets no warning: that is the v0.16 feature used as designed, and "
          "this is the case that fails if the gate goes away",
          f == [] and w == [], "f=%r w=%r" % (f, w))

    # --- the aliases ---
    _names = ("_check_claim", "_check_area_tag", "_check_areas",
              "_walk_phases")
    _forked = [n for n in _names if getattr(_rules, n) is not getattr(M, n)]
    check("mp21 every name `_manifest_rules` re-exports from here IS this "
          "module's function: %r" % (_forked,), _forked == [])
    check("mp22 ...and TERMINAL here is `_manifest_io`'s tuple, not a second "
          "list of the words that mean finished", M.TERMINAL is _mio.TERMINAL)
    _shared = ("_unknown_keys", "_safe_list", "_require_fields", "_check_ado",
               "STATUS", "TESTS_MODE", "RISK", "CLAIM_KEYS", "KNOWN_PHASE",
               "KNOWN_TASK")
    _drift = [n for n in _shared if getattr(M, n) is not getattr(_vocab, n)]
    check("mp23 ...and every word and shape check it reads is "
          "`_manifest_vocab`'s object: %r" % (_drift,), _drift == [])

    # mp24-mp26: the U-BOARD wiring. `_ado_tracked` owns the rule and this file
    # owns whether the walk ASKS it — two separate failures, and the wiring is the
    # one that disappears without a trace: the rule keeps passing its own suite
    # while no manifest is ever graded by it.
    _ph = _phase(tasks=[_task("P0.1")])
    _ph["adoTracked"] = "yes"
    _idx, _f, _w = M._walk_phases([_ph])
    check("mp24 a phase's mistyped `adoTracked` reaches the walk's findings - "
          "the rule lives in `_ado_tracked`, and this is the case that goes red "
          "if the walk stops asking it: %r" % (_f,),
          [x for x in _f if "adoTracked" in x] != [])
    # THE SCOPE HALF, and it is the direction that would go unnoticed: a task
    # inherits its phase's answer and declares nothing, so a finding on a TASK
    # would be the validator refusing a key the resolver never reads.
    _ph2 = _phase(tasks=[_task("P0.1")])
    _ph2["tasks"][0]["adoTracked"] = "yes"
    _idx2, _f2, _w2 = M._walk_phases([_ph2])
    check("mp25 ...while the same value on a TASK raises no adoTracked finding: "
          "the declaration is a phase's alone and a task inherits, so grading it "
          "here would refuse a key nothing reads: %r" % (_f2,),
          [x for x in _f2 if "adoTracked" in x] == [])
    _ph3 = _phase(tasks=[_task("P0.1")])
    _ph3["adoTracked"] = False
    _idx3, _f3, _w3 = M._walk_phases([_ph3])
    check("mp26 ...and a WELL-FORMED declaration is silent, so the check cannot "
          "be satisfied by one that always fires: %r" % (_f3,),
          [x for x in _f3 if "adoTracked" in x] == [])


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__manifest_phases.py --selftest\n")
    raise SystemExit(2)
