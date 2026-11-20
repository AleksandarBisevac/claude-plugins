#!/usr/bin/env python3
"""
The cases for `_verdict_binding.py` - the one rule for whether a recorded gate
verdict binds the declared work as it stands now.

Its two callers carry their own end-to-end cases against real runs:
`test_commit_task_work.py` for a task commit and `test_audit_task.py` (`ve`, `gs`)
for a sign-off. These drive the rule itself over a ledger written by hand, so
each arm is reached with exactly the row that should reach it - the repeat whose
source is present or gone, the gate that changed after an `empty-gate` row, the
unparseable line that names another subject, the red nothing retired.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import json
import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _evidence_io                                # noqa: E402  (where the ledger lives)
import _tree_stamp                                 # noqa: E402  (the digest a row records)
import _verdict_binding as M                       # noqa: E402

PHASE = {"phaseId": "P1"}


def _project(root, rows, files=None):
    """A project whose ledger holds `rows`, and whose `src/a.py` holds `files`."""
    os.makedirs(os.path.join(root, ".claude"), exist_ok=True)
    with open(os.path.join(root, ".claude", "audit.config.json"), "w") as fh:
        json.dump({"manifestPath": "docs/audit/audit-plan.json"}, fh)
    os.makedirs(os.path.join(root, "src"), exist_ok=True)
    with open(os.path.join(root, "src", "a.py"), "w") as fh:
        fh.write(files or "a = 1\n")
    evidence = _evidence_io.evidence_dir(root)
    os.makedirs(evidence, exist_ok=True)
    with open(os.path.join(evidence, "2026-09.t.jsonl"), "w") as fh:
        for row in rows:
            fh.write((row if isinstance(row, str) else json.dumps(row)) + "\n")
    return os.path.join(root, "docs", "audit", "audit-plan.json")


def _measured(root, run_id, ts, status="passed", steps=("test",)):
    digest = _tree_stamp.scope_digest(root, ["src/a.py"])[0]
    return {"runId": run_id, "ts": ts, "scope": "phase", "phaseId": "P1",
            "status": status, "gateSource": "phase",
            "steps": [{"name": n} for n in steps],
            "testedState": {"scopeDigest": digest}}


def _bind(root, mpath, entries=("test",)):
    return M.binding(root, PHASE, list(entries), "phase", ["src/a.py"], mpath,
                     "run the gate", "no gate here")


def _derived_step_cases(check):
    """A task's recorded row carries the steps its gate declared AND the
    `affected/<arm>: <suites>` steps the recorder adds when the task gate is
    narrower than the phase gate. The prefix is spelled here as the ledger
    holds it - a row on disk is the contract - and pinned to the one module that
    defines it, so the fixture cannot drift from what the recorder writes."""
    prefix = getattr(_evidence_io, "DERIVED_STEP_PREFIX", None)
    derived = [{"name": "affected/related: tests/test_b.py"},
               {"name": "affected/python: tests/test_c.py, tests/test_d.py"}]
    digest = _evidence_io.gate_digest(["test"], None)

    def row(declared, gate_digest=digest, source="task", extra=None):
        return {"steps": [{"name": n} for n in declared] + derived
                + list(extra or []), "gateSource": source,
                _evidence_io.GATE_DIGEST_KEY: gate_digest}
    same = M.gate_mismatch(row(["test"]), ["test"], "task")
    other = M.gate_mismatch(row(["lint"]), ["test"], "task") or ""
    widened = M.gate_mismatch(row(["test"]), ["test", "lint"], "task") or ""
    narrowed = M.gate_mismatch(row(["test", "lint"]), ["test"], "task") or ""
    moved = M.gate_mismatch(row(["test"], gate_digest="sha256:other"),
                            ["test"], "task") or ""
    resourced = M.gate_mismatch(row(["test"], source="phase"),
                                ["test"], "task") or ""
    # A declared-looking step AFTER a derived one is not a shape the recorder
    # writes, so nothing past the first derived step is read as declared.
    interleaved = M.gate_mismatch(row(["test"], extra=[{"name": "lint"}]),
                                  ["test"], "task") or ""
    different = "a verdict about a different gate is not this gate's verdict"
    check("vb34 a recorded row whose steps are the declared entries followed by "
          "affected/related and affected/python steps has no gate mismatch, "
          "while a row whose declared part differs, or whose gateDigest "
          "differs, still has one: prefix %r / %r / %r / %r / %r / %r / %r / %r"
          % (prefix, same, other, widened, narrowed, moved, resourced,
             interleaved),
          prefix == "affected/"
          and all(str(s["name"]).startswith(prefix or "\0") for s in derived)
          and same is None
          and "measured under the gate [lint]" in other and different in other
          and "declares [test, lint]" in widened and different in widened
          and "[test, lint]" in narrowed and different in narrowed
          and "resolve to different commands now" in moved
          and "(phase gate)" in resourced and different in resourced
          and different in interleaved)


def _reserved_prefix_cases(check):
    """A gate entry spelled with the derived-step prefix cannot bind, and the
    refusal says that rather than blaming a different gate."""
    prefix = _evidence_io.DERIVED_STEP_PREFIX
    entry = prefix + "lint"
    # What the recorder wrote for such a task: the entry as a step, which
    # `declared_steps` reads as derived and so leaves out of the declared gate.
    measured = {"steps": [{"name": "test"}, {"name": entry}], "gateSource": "task"}
    refused = M.gate_mismatch(measured, ["test", entry], "task") or ""
    phase = M.gate_mismatch(measured, ["test", entry], "phase") or ""
    # THE SECOND DIRECTION: a task whose entries do not start with the prefix keeps
    # the sentence it always had, and does not mention a reserved prefix.
    plain = M.gate_mismatch({"steps": [{"name": "lint"}]}, ["test", "x" + entry],
                            "task") or ""
    check("vb35 a task whose own gate entry carries the derived-step prefix is "
          "refused with a sentence naming the reserved prefix: %r / %r"
          % (refused, plain),
          repr(entry) in refused and repr(prefix) in refused
          and "reserved" in refused and "task" in refused
          and "a verdict about a different gate" not in refused
          and repr(entry) in phase and "reserved" in phase
          and plain.startswith("it was measured under the gate")
          and "reserved" not in plain)


def _left_to_phase_gate_cases(check):
    """A task's recorded run leaves out an entry `executor.phaseGateOnly` names
    when the phase gate holds it, and lists it on the row under the left-out
    key. The row is one step short of the declaration for that reason alone,
    so it binds; a row one step short for any other reason - nothing listed,
    or a different entry listed - still does not. The key is spelled as the
    ledger holds it; a row on disk is the contract."""
    entries = ["sweep", "browser"]
    digest = _evidence_io.gate_digest(entries, None)

    def row(steps, left=None):
        measured = {"steps": [{"name": n} for n in steps], "gateSource": "task",
                    _evidence_io.GATE_DIGEST_KEY: digest}
        if left is not None:
            measured["leftToPhaseGate"] = [
                {"name": n, "arm": "declared", "basis": "executor.phaseGateOnly",
                 "matched": "browser.py"} for n in left]
        return measured
    bound = M.gate_mismatch(row(["sweep"], ["browser"]), entries, "task")
    every = M.gate_mismatch(row([], ["sweep", "browser"]), entries, "task")
    check("vb38 a row one step short of the declared gate BECAUSE the step is "
          "listed as left to the phase gate binds - and so does a row that left "
          "every entry: %r / %r" % (bound, every),
          bound is None and every is None)
    short = M.gate_mismatch(row(["sweep"]), entries, "task") or ""
    wrong = M.gate_mismatch(row(["sweep"], ["lint"]), entries, "task") or ""
    twice = M.gate_mismatch(row(["sweep", "browser"], ["browser"]), entries,
                            "task") or ""
    derived = M.gate_mismatch(
        {"steps": [{"name": "sweep"}], "gateSource": "task",
         _evidence_io.GATE_DIGEST_KEY: digest,
         "leftToPhaseGate": [{"name": "affected/phase-gate: browser",
                              "arm": "phase-gate",
                              "basis": "executor.phaseGateOnly",
                              "matched": "browser.py"}]},
        entries, "task") or ""
    different = "a verdict about a different gate is not this gate's verdict"
    check("vb39 THE REFUSING HALF: a row one step short with nothing listed, "
          "with a DIFFERENT entry listed, with the listed entry ALSO run, or "
          "with only a widened step of another arm listed, is still measured "
          "under a different gate: %r / %r / %r / %r"
          % (short, wrong, twice, derived),
          different in short and different in wrong and different in twice
          and different in derived)


def _joined_step_cases(check):
    """A task's declared entry and the affected steps run as one call are one
    recorded step, named for the entry followed by each affected step's name.
    The comparison is the one it always was, through
    `_evidence_io.declared_steps`, which reads such a step as its declared
    entry - so the row binds when that entry is the declared one, and does not
    when the joined step lacks it. The names are spelled as the ledger holds
    them; a row on disk is the contract."""
    own = "python3 tools/sweep.py tests/test_own.py"
    rel = "affected/related: tests/test_other.py"
    py = "affected/python: tests/test_core.py"
    entries = [own, "lint"]
    digest = _evidence_io.gate_digest(entries, None)

    def row(steps):
        return {"steps": [{"name": n} for n in steps], "gateSource": "task",
                _evidence_io.GATE_DIGEST_KEY: digest}
    joined = own + " + " + rel + " + " + py
    bound = M.gate_mismatch(row([joined, "lint"]), entries, "task")
    tail = M.gate_mismatch(row([joined, "lint", "affected/phase-gate: wide"]),
                           entries, "task")
    check("vb40 a row whose declared entry ran joined with the affected steps "
          "binds the gate it declared, with a widened step after it or not: "
          "%r / %r" % (bound, tail),
          bound is None and tail is None)
    different = "a verdict about a different gate is not this gate's verdict"
    lacking = [
        # the affected steps' names, the declared entry only after them
        M.gate_mismatch(row([rel + " + " + own, "lint"]), entries, "task"),
        # another entry in the declared slot
        M.gate_mismatch(row(["python3 tools/sweep.py tests/test_two.py + " + rel,
                             "lint"]), entries, "task"),
        # nothing in the declared slot at all
        M.gate_mismatch(row([" + " + rel, "lint"]), entries, "task"),
    ]
    check("vb41 THE REFUSING HALF: a joined step that lacks the declared entry "
          "at its head - the affected names first, another entry there, or "
          "nothing - is measured under a different gate and does not bind: %r"
          % (lacking,),
          all(different in (said or "") for said in lacking))
    spelled = own + " + " + rel
    reserved = M.gate_mismatch(row([spelled]), [spelled], "task") or ""
    check("vb42 a gate entry spelled the way a joined step is named cannot "
          "bind, and the refusal names the entry and the reserved spelling "
          "rather than blaming a different gate: %r" % (reserved,),
          repr(spelled) in reserved and "reserved" in reserved
          and different not in reserved)


def _cases(check):
    check("vb1 a gate measured under the same entries is not a mismatch",
          M.gate_mismatch({"steps": [{"name": "test"}]}, ["test"], "phase") is None)
    check("vb2 ...and one measured under other entries is, saying both",
          "[lint]" in (M.gate_mismatch({"steps": [{"name": "lint"}]}, ["test"],
                                       "phase") or ""))
    _derived_step_cases(check)
    _reserved_prefix_cases(check)
    _left_to_phase_gate_cases(check)
    _joined_step_cases(check)
    check("vb3 a red after the last green is unanswered; a green after it retires it",
          M.red_after_green([{"ts": "1", "status": "passed"},
                             {"ts": "2", "status": "failed"}]) is not None
          and M.red_after_green([{"ts": "1", "status": "failed"},
                                 {"ts": "2", "status": "passed"}]) is None)
    # Text order and moment order DISAGREE: the offset stamp spells a later
    # day and names an earlier moment.
    early_text, late_text = "2026-09-02T23:00:00Z", "2026-09-03T00:00:00+05:00"
    got_newest = M.newest([{"runId": "A", "ts": early_text},
                           {"runId": "B", "ts": late_text}])
    check("vb3b RED-FIRST: `newest` picks the row whose ts names the later "
          "MOMENT, never the later spelling: %r" % ((got_newest or {}).get(
              "runId"),),
          (got_newest or {}).get("runId") == "A")
    got_red = M.red_after_green([{"ts": early_text, "status": "passed"},
                                 {"ts": late_text, "status": "failed"}])
    check("vb3c RED-FIRST: `red_after_green` orders by moment too - a red "
          "whose ts spells a later day but names an EARLIER moment than the "
          "green was retired by it: %r" % (got_red,),
          got_red is None)
    check("vb4 a sentence names the task when there is one, else the phase",
          M.label_of({"taskId": "P1.2", "phaseId": "P1"}) == "P1.2"
          and M.label_of(PHASE) == "P1")

    root = _harness.fixture_root("verdict-binding")
    try:
        base = os.path.join(root, "measured")
        os.makedirs(base)
        mpath = _project(base, [])
        row = _measured(base, "R1", "2026-09-01T00:00:00Z")
        _project(base, [row])
        check("vb5 a passed row over the declared files as they stand binds",
              _bind(base, mpath)["state"] == "bound")
        reused = {"runId": "R2", "ts": "2026-09-02T00:00:00Z", "scope": "phase",
                  "phaseId": "P1", "status": "passed", "testedState": {},
                  _evidence_io.VERDICT_SOURCE: _evidence_io.REUSED,
                  "reusedFrom": {"runId": "R1"}}
        _project(base, [row, reused])
        got = _bind(base, mpath)
        check("vb6 a REPEATED verdict is graded against the run it repeats, so it "
              "binds while that run matches: %r" % (got["sentence"],),
              got["state"] == "bound" and got["measured"]["runId"] == "R1"
              and got["row"]["runId"] == "R2")
        _project(base, [reused])
        got = _bind(base, mpath)
        check("vb7 SECOND DIRECTION: a repeat whose source is gone is refused: %r"
              % (got["sentence"],),
              got["state"] == "refused" and "not in the ledger" in got["sentence"])
        # A ROW WHOSE STEPS ARE PART REPEATED: it took its own reading of the
        # tree, so it binds as a measured row does, and the sentence that
        # binds it says which steps it repeated and from which run. Spelled as
        # the ledger holds it.
        two = _measured(base, "R1", "2026-09-01T00:00:00Z",
                        steps=("tree", "plan"))
        part = dict(_measured(base, "R5", "2026-09-05T00:00:00Z",
                              steps=("tree", "plan")),
                    reusedFrom={"runId": "R1"})
        part[_evidence_io.VERDICT_SOURCE] = "part-reused"
        part["steps"][0]["reusedFrom"] = {"runId": "R1",
                                          "ts": "2026-09-01T00:00:00Z"}
        _project(base, [two, part])
        got = _bind(base, mpath, entries=("tree", "plan"))
        check("vb36 a commit binds to a PART-REPEATED row as to a measured one - "
              "the row itself is what measured the tree - and the sentence "
              "names the repeated step and the run it came from: %r"
              % (got["sentence"],),
              got["state"] == "bound" and got["measured"]["runId"] == "R5"
              and got["row"]["runId"] == "R5"
              and "tree repeated from run R1" in got["sentence"])
        _project(base, [two])
        got = _bind(base, mpath, entries=("tree", "plan"))
        check("vb37 SECOND DIRECTION: a row that repeated nothing binds with no "
              "such clause: %r" % (got["sentence"],),
              got["state"] == "bound" and "repeated from" not in got["sentence"])
        _project(base, [row], files="a = 2\n")
        got = _bind(base, mpath)
        check("vb8 changed declared files refuse the verdict: %r" % (got["sentence"],),
              got["state"] == "refused" and "changed" in got["sentence"])
        empty = dict(_measured(base, "R3", "2026-09-03T00:00:00Z",
                               status="empty-gate", steps=()))
        _project(base, [empty])
        got = _bind(base, mpath)
        check("vb9 an empty-gate row under a gate that has entries now is a "
              "different gate: %r" % (got["sentence"],),
              got["state"] == "refused" and "different gate" in got["sentence"])
        got = _bind(base, mpath, entries=())
        check("vb10 ...while under a gate still empty it is the recorded answer and "
              "the caller's own no-gate sentence is said",
              got["state"] == "no-gate" and got["sentence"].startswith("no gate here"))
        red = _measured(base, "R4", "2026-09-04T00:00:00Z", status="failed")
        _project(base, [row, red])
        got = _bind(base, mpath, entries=())
        check("vb11 emptying the gate does not retire a red recorded after the last "
              "green: %r" % (got["sentence"],),
              got["state"] == "refused" and "after the last green" in got["sentence"])
        _project(base, [row, '{"taskId": "P9.1", "torn'])
        got = _bind(base, mpath)
        check("vb12 an unparseable line that names a TASK is not a phase's row, so it "
              "is passed over and said: %r" % (got["notes"],),
              got["state"] == "bound" and got["notes"])
        _project(base, [row, '{"phaseId": "P1", "torn'])
        got = _bind(base, mpath)
        check("vb13 SECOND DIRECTION: one that could be the phase's row blocks",
              got["state"] == "refused" and M.VERIFY_COMMAND in got["sentence"])
        # A NEWER verdict for the phase sits in a second file whose bytes are
        # not UTF-8. Every ledger reader loses that file whole, so the older
        # green in the first file must not be bound as if the newer row had
        # never been recorded - the lost file is named, and the verdict refused.
        _project(base, [row])
        odd = os.path.join(_evidence_io.evidence_dir(base), "2026-09.odd.jsonl")
        newer = _measured(base, "R5", "2026-09-05T00:00:00Z", status="failed")
        newer["note"] = "BYTE"
        with open(odd, "wb") as fh:
            fh.write(json.dumps(newer).encode("utf-8").replace(
                b"BYTE", b"B\xffTE") + b"\n")
        got = _bind(base, mpath)
        check("vb14 RED-FIRST: a ledger file holding a byte that is not UTF-8 is "
              "lost to the binding and SAID - the verdict is refused naming that "
              "file as unreadable, never bound on an older row as though the "
              "file held nothing: %r" % (got["sentence"],),
              got["state"] == "refused"
              and "2026-09.odd.jsonl" in got["sentence"]
              and M.VERIFY_COMMAND in got["sentence"])
        check("vb14b RED-FIRST: a file lost WHOLE gets its own words - not "
              "'line(s) that will not parse', but what `verify` names for it "
              "and the step that clears it: %r" % (got["sentence"],),
              "line(s) that will not parse" not in got["sentence"]
              and "could not be read at all" in got["sentence"]
              and "restore the file from its committed copy"
              in got["sentence"])
        os.remove(odd)

        # A red stamped with a DATE beside a green stamped to the second: the
        # day is the start of that day, a moment after the green, so the red
        # is after the last green and is not retired.
        green = _measured(base, "R-G1", "2026-09-04T00:00:00Z")
        day_red = _measured(base, "R-D1", "2026-09-05", status="failed")
        _project(base, [green, day_red])
        got = _bind(base, mpath, entries=())
        check("vb15 RED-FIRST: a date-only red after a dated green is a red "
              "after the last green, and refuses as one: %r / %r"
              % ((M.red_after_green([green, day_red]) or {}).get("runId"),
                 got["sentence"]),
              (M.red_after_green([green, day_red]) or {}).get("runId")
              == "R-D1"
              and got["state"] == "refused"
              and "after the last green" in got["sentence"])
        junk_red = _measured(base, "R-J1", "not-a-moment", status="failed")
        _project(base, [green, junk_red])
        got = _bind(base, mpath)
        check("vb16 RED-FIRST: a subject row whose ts is no moment BLOCKS - it "
              "cannot be placed before or after the green, so it could be the "
              "newest verdict - naming the row and pointing at `%s`: %r"
              % (M.VERIFY_COMMAND, got["sentence"]),
              got["state"] == "refused" and "R-J1" in got["sentence"]
              and "not-a-moment" in got["sentence"]
              and M.VERIFY_COMMAND in got["sentence"])

        # A REPEATED verdict names its origin by runId, and two rows wear that
        # id: the origin is the NEWER by moment, read FIRST here, whose gate
        # is the gate now. File order would pick the older row, measured
        # under another gate.
        origin_new = _measured(base, "R-O", "2026-09-06T00:00:00Z")
        origin_old = _measured(base, "R-O", "2026-09-01T00:00:00Z",
                               steps=("lint",))
        repeat = {"runId": "R-RP", "ts": "2026-09-07T00:00:00Z",
                  "scope": "phase", "phaseId": "P1", "status": "passed",
                  "testedState": {},
                  _evidence_io.VERDICT_SOURCE: _evidence_io.REUSED,
                  "reusedFrom": {"runId": "R-O"}}
        _project(base, [origin_new, origin_old, repeat])
        got = _bind(base, mpath)
        check("vb18 RED-FIRST: a repeat's origin is the NEWEST row carrying "
              "its runId by moment, never the last in ledger order: %r / %r"
              % ((got["measured"] or {}).get("ts"), got["sentence"]),
              got["state"] == "bound"
              and (got["measured"] or {}).get("ts") == "2026-09-06T00:00:00Z")

        # A CLOSE NEVER VOUCHES FOR A VERDICT THAT NO LONGER HOLDS: it refuses on
        # every refusing arm but the two with no measurement to vouch for - no
        # run recorded, and an `empty-gate` answer under a gate with entries.
        _project(base, [row, red])
        got = _bind(base, mpath)
        check("vb19 RED-FIRST: a close over a red newest verdict is refused, "
              "the sentence naming the run: %r" % (got,),
              got["state"] == "refused" and got.get("arm") == M.ARM_RED
              and "R4" in (M.close_refusal(got) or ""))
        _project(base, [row, red, _measured(base, "R6", "2026-09-06T00:00:00Z")],
                 files="a = 3\n")
        got = _bind(base, mpath)
        check("vb20 RED-FIRST: a green newest verdict over declared files that "
              "changed since refuses a close as it refuses a commit - the close "
              "would vouch for a measurement of other bytes: %r"
              % (got["sentence"],),
              got.get("arm") == M.ARM_DIGEST_MOVED
              and M.close_refusal(got) == got["sentence"])
        _project(base, [])
        got = _bind(base, mpath)
        check("vb21 SECOND DIRECTION: a gate with no run recorded at all is "
              "refused for a commit and NOT for a close - there is no "
              "measurement to vouch for: %r" % (got["sentence"],),
              got["state"] == "refused" and got.get("arm") == M.ARM_NO_VERDICT
              and M.close_refusal(got) is None)
        _project(base, [empty])
        got = _bind(base, mpath)
        check("vb21b SECOND DIRECTION: ...and so is an `empty-gate` answer under "
              "a gate that has entries now: %r" % (got["sentence"],),
              got.get("arm") == M.ARM_EMPTY_GATE and M.close_refusal(got) is None)
        _project(base, [_measured(base, "R7", "2026-09-07T00:00:00Z",
                                  steps=("lint",))])
        got = _bind(base, mpath)
        check("vb21c RED-FIRST: a green measured under another gate refuses a "
              "close: %r" % (got["sentence"],),
              got.get("arm") == M.ARM_GATE_CHANGED
              and M.close_refusal(got) == got["sentence"])
        _project(base, [reused])
        got = _bind(base, mpath)
        check("vb21d RED-FIRST: a repeat whose source is gone refuses a close: %r"
              % (got["sentence"],),
              got.get("arm") == M.ARM_REPEAT_GONE
              and M.close_refusal(got) == got["sentence"])
        check("vb21e the arms a close refuses are every refusing arm but the two "
              "with no measurement: %r" % (M.CLOSE_REFUSING_ARMS,),
              sorted(M.CLOSE_REFUSING_ARMS) == sorted([
                  M.ARM_UNREADABLE, M.ARM_UNDATED, M.ARM_RED_AFTER_GREEN,
                  M.ARM_RED, M.ARM_REPEAT_GONE, M.ARM_GATE_CHANGED,
                  M.ARM_DIGEST_MOVED, M.ARM_DIGEST_UNANSWERABLE])
              and M.ARM_NO_VERDICT not in M.CLOSE_REFUSING_ARMS
              and M.ARM_EMPTY_GATE not in M.CLOSE_REFUSING_ARMS)
        _project(base, [row, '{"phaseId": "P1", "torn'])
        got = _bind(base, mpath)
        check("vb22 a line that will not parse and could be the newest verdict "
              "refuses a close too - it may be the red: %r" % (got["sentence"],),
              M.close_refusal(got) == got["sentence"])
        _project(base, [row, red])
        got = _bind(base, mpath, entries=())
        check("vb23 a red after the last green under a gate emptied since "
              "refuses a close, as it refuses a commit: %r" % (got["sentence"],),
              "R4" in (M.close_refusal(got) or ""))
        _project(base, [])
        got = _bind(base, mpath, entries=())
        check("vb24 ALLOW: the no-gate arm closes, its sentence said: %r"
              % (got["sentence"],),
              got["state"] == "no-gate" and M.close_refusal(got) is None)

        # A group signed off together: the carrier holds the run, every other
        # member points at it with `testEvidence.gradedBy`.
        plan = {"phases": [
            {"id": "P1", "tasks": [{"id": "P1.1", "files": ["a.py"]}]},
            {"id": "P2", "testEvidence": {"runId": "R", "gradedBy": "P1"},
             "tasks": [{"id": "P2.1", "files": ["b.py"]}]},
            {"id": "P3", "tasks": [{"id": "P3.1", "files": ["c.py"]}]}]}
        carrier, members = M.group_of(plan, plan["phases"][1])
        check("vb25 RED-FIRST: a group member's verdict is its carrier's run, "
              "over every member's files: %r"
              % ((carrier.get("id"), [m.get("id") for m in members]),),
              carrier.get("id") == "P1"
              and [m.get("id") for m in members] == ["P1", "P2"]
              and M.phase_files(members) == ["a.py", "b.py"])
        carrier, members = M.group_of(plan, plan["phases"][0])
        check("vb26 ...and the carrier asked itself finds the same group",
              [m.get("id") for m in members] == ["P1", "P2"])
        carrier, members = M.group_of(plan, plan["phases"][2])
        check("vb27 SECOND DIRECTION: a phase graded alone is its own carrier "
              "and its only member",
              carrier.get("id") == "P3" and [m.get("id") for m in members]
              == ["P3"])

        # TWO COPIES OF ONE LEDGER, read as one: a branch tip's and a worktree's.
        line_a = json.dumps({"runId": "A", "ts": "2026-09-01T00:00:00Z"})
        line_b = json.dumps({"runId": "B", "ts": "2026-09-02T00:00:00Z"})
        union = M.rows_of([("tip", line_a + "\n"),
                           ("tree", line_a + "\n" + line_b + "\n"),
                           ("lost", None)])
        check("vb28 RED-FIRST: the union of two copies holds each row once - the "
              "row both carry once, the row only the worktree carries still "
              "read: %r" % ([r.get("runId") for r in union],),
              sorted(r.get("runId") for r in union) == ["A", "B"])
        stale = {"state": "refused", "arm": M.ARM_DIGEST_MOVED, "sentence": "s",
                 "row": {"ts": "2026-09-01T00:00:00Z"}}
        late_red = {"state": "refused", "arm": M.ARM_RED, "sentence": "r",
                    "row": {"ts": "2026-09-01T06:00:00Z"}}
        early_red = dict(late_red, row={"ts": "2026-09-01T01:00:00Z"})
        signed = {"at": "2026-09-01T05:00:00Z"}
        check("vb29 RED-FIRST: a sign-off recorded with --no-evidence-reason "
              "answers a stale green: %r / %r"
              % (M.close_refusal(stale), M.close_refusal(stale, signed)),
              M.close_refusal(stale) == "s"
              and M.close_refusal(stale, signed) is None)
        check("vb30 SECOND DIRECTION: ...but not a red recorded after it, and a "
              "sign-off with no moment answers no red at all",
              M.close_refusal(late_red, signed) == "r"
              and M.close_refusal(early_red, signed) is None
              and M.close_refusal(early_red, {"at": None}) == "r")
        journal = [("j", json.dumps({"action": "phase.verdict",
                                     "ts": "2026-09-01T05:00:00Z",
                                     "details": {"phaseId": "P1"}}) + "\n"
                    + json.dumps({"action": "phase.verdict",
                                  "ts": "2026-09-01T07:00:00Z",
                                  "details": {"phaseId": "P2"}}) + "\n")]
        check("vb31 the sign-off moment is the newest phase.verdict row for THAT "
              "phase: %r" % (M.signoff_moment(journal, "P1"),),
              M.signoff_moment(journal, "P1") == "2026-09-01T05:00:00Z"
              and M.signoff_moment(journal, "P9") is None)
    finally:
        _harness.remove_tree(root)


def _tree_binding_cases(check):
    """A gate measured in another tree (`run-test-gate.py --tree`) binds the
    project's commit by CONTENT: the row carries the tree's digest and the head
    the tree had, and a commit made in the project after the tree's bytes were
    copied in moves HEAD without changing the declared bytes."""
    root = _harness.fixture_root("verdict-binding-tree")
    try:
        project = os.path.join(root, "project")
        tree = os.path.join(root, "tree")
        os.makedirs(project)
        os.makedirs(os.path.join(tree, "src"))
        with open(os.path.join(tree, "src", "a.py"), "w") as fh:
            fh.write("a = 2\n")
        git = ["git", "-C", project, "-c", "user.name=t", "-c", "user.email=t@t",
               "-c", "commit.gpgsign=false"]
        _harness.git(None, "init", "-q", project, prefix=("git",))
        mpath = _project(project, [])
        _harness.git(None, "add", "-A", prefix=git)
        _harness.git(None, "commit", "-qm", "base", prefix=git)
        head_then = _harness.git(None, "-C", project, "rev-parse", "HEAD",
                                 prefix=("git",)).strip()
        measured = _measured(tree, "R1", "2026-09-01T00:00:00Z")
        measured["testedState"]["head"] = head_then
        _project(project, [measured])
        got = _bind(project, mpath)
        check("vb32 a verdict measured over the TREE's bytes does not bind the "
              "project while its declared file still holds other bytes: %r"
              % (got["sentence"],), got["state"] == "refused")
        with open(os.path.join(project, "src", "a.py"), "w") as fh:
            fh.write("a = 2\n")
        _harness.git(None, "add", "-A", prefix=git)
        _harness.git(None, "commit", "-qm", "integrate", prefix=git)
        head_now = _harness.git(None, "-C", project, "rev-parse", "HEAD",
                                prefix=("git",)).strip()
        got = _bind(project, mpath)
        check("vb33 ...and once the tree's bytes are copied in and COMMITTED in "
              "the project it binds although HEAD is no longer the one the row "
              "was taken at (the binding compares content, not commits): %r"
              % ((got["sentence"], head_then[:8], head_now[:8]),),
              head_then != head_now and got["state"] == "bound")
    finally:
        _harness.remove_tree(root)


def _records_only(root, rows, files=None):
    """The project `_project` builds, with NO ledger: the plan holds phase P1's
    newest run as its record, `run_record` over that row with the run it
    repeats as `source` - what `run-test-gate.py --record` writes."""
    mpath = _project(root, [], files=files)
    os.remove(os.path.join(_evidence_io.evidence_dir(root), "2026-09.t.jsonl"))
    os.rmdir(_evidence_io.evidence_dir(root))
    newest = _evidence_io.latest_by_subject(rows).get(("phase", "P1"))
    by_id = dict((r["runId"], r) for r in rows)
    phase = {"id": "P1", "title": "one", "status": "in_progress",
             "testGate": ["test"], "tasks": []}
    if newest is not None:
        phase[_evidence_io.RECORD_KEY] = _evidence_io.run_record(
            newest, source=by_id.get((newest.get("reusedFrom") or {}).get(
                "runId")))
        phase[_evidence_io.POINTER_KEY] = _evidence_io.pointer_from_record(
            phase[_evidence_io.RECORD_KEY])
    os.makedirs(os.path.join(root, "docs", "audit", "phases"), exist_ok=True)
    with open(os.path.join(root, "docs", "audit", "phases", "P1.json"),
              "w") as fh:
        json.dump(phase, fh)
    with open(mpath, "w") as fh:
        json.dump({"meta": {"version": 3}, "phases": [
            {"id": "P1", "title": "one", "shard": "phases/P1.json"}]}, fh)
    return mpath


def _said(got):
    """What a binding answer decides: its state, its arm, the run it names and
    the run that measured the tree."""
    return (got.get("state"), got.get("arm"),
            (got.get("row") or {}).get("runId"),
            (got.get("measured") or {}).get("runId"))


def _record_binding_cases(check):
    """(vb43) The binding answers the same from a record as from the row it
    replaces, over the fixtures `_cases` reaches each arm with that a record can
    hold - a subject's newest run. The ledger-file arms (a torn line, a byte
    that is not text, a row naming no moment) are about the ledger file and
    have no record to compare."""
    root = _harness.fixture_root("verdict-binding-records")
    try:
        probe = os.path.join(root, "probe")
        os.makedirs(probe)
        _project(probe, [])
        row = _measured(probe, "R1", "2026-09-01T00:00:00Z")
        reused = {"runId": "R2", "ts": "2026-09-02T00:00:00Z", "scope": "phase",
                  "phaseId": "P1", "status": "passed", "testedState": {},
                  "gateSource": "phase",
                  _evidence_io.VERDICT_SOURCE: _evidence_io.REUSED,
                  "reusedFrom": {"runId": "R1", "ts": "2026-09-01T00:00:00Z",
                                 "status": "passed"}}
        two = _measured(probe, "R1", "2026-09-01T00:00:00Z",
                        steps=("tree", "plan"))
        part = dict(_measured(probe, "R5", "2026-09-05T00:00:00Z",
                              steps=("tree", "plan")),
                    reusedFrom={"runId": "R1"})
        part[_evidence_io.VERDICT_SOURCE] = _evidence_io.PART_REUSED
        part["steps"][0]["reusedFrom"] = {"runId": "R1",
                                          "ts": "2026-09-01T00:00:00Z"}
        empty = _measured(probe, "R3", "2026-09-03T00:00:00Z",
                          status="empty-gate", steps=())
        red = _measured(probe, "R4", "2026-09-04T00:00:00Z", status="failed")
        other = _measured(probe, "R7", "2026-09-07T00:00:00Z", steps=("lint",))
        table = [
            ("bound", [row], ("test",), None),
            ("repeat followed to its source", [row, reused], ("test",), None),
            ("part repeat", [two, part], ("tree", "plan"), None),
            ("files moved", [row], ("test",), "a = 2\n"),
            ("empty gate under entries", [empty], ("test",), None),
            ("empty gate under none", [empty], (), None),
            ("red after green, gate emptied", [row, red], (), None),
            ("red newest", [row, red], ("test",), None),
            ("another gate", [other], ("test",), None),
            ("nothing recorded", [], ("test",), None),
        ]
        differ, seen = [], {}
        for at, (name, rows, entries, files) in enumerate(table):
            rbase = os.path.join(root, "rows-%d" % (at,))
            cbase = os.path.join(root, "records-%d" % (at,))
            os.makedirs(rbase)
            os.makedirs(cbase)
            rpath = _project(rbase, rows, files=files)
            cpath = _records_only(cbase, rows, files=files)
            from_rows = _said(_bind(rbase, rpath, entries=entries))
            from_records = _said(_bind(cbase, cpath, entries=entries))
            seen[name] = from_records
            if from_rows != from_records:
                differ.append((name, from_rows, from_records))
        check("vb43 THE BINDING FROM A RECORD: each fixture, held as its "
              "newest run's record with no ledger at all, binds or refuses on "
              "the same arm, naming the same run and the same measuring run, as "
              "the same fixture held as ledger rows - differing: %r; from "
              "records: %r" % (differ, seen),
              differ == [] and len(seen) == len(table))
        check("vb44 ...and not because every answer is the same: from records "
              "alone a repeated verdict is followed to the run that measured "
              "it and BINDS there, a moved file refuses on the digest, and a "
              "red newest run refuses as red: %r"
              % ((seen.get("repeat followed to its source"),
                  seen.get("files moved"), seen.get("red newest")),),
              seen.get("repeat followed to its source") == ("bound", None, "R2",
                                                            "R1")
              and seen.get("files moved", ("",))[1] == M.ARM_DIGEST_MOVED
              and seen.get("red newest", ("",))[1] == M.ARM_RED)
    finally:
        _harness.remove_tree(root)


def _put_shard(root, phase):
    """`phase` as P1's shard of the plan `_project` points at."""
    os.makedirs(os.path.join(root, "docs", "audit", "phases"), exist_ok=True)
    with open(os.path.join(root, "docs", "audit", "phases", "P1.json"),
              "w") as fh:
        json.dump(phase, fh)
    with open(os.path.join(root, "docs", "audit", "audit-plan.json"),
              "w") as fh:
        json.dump({"meta": {"version": 3}, "phases": [
            {"id": "P1", "title": "one", "shard": "phases/P1.json"}]}, fh)


def _unread_binding_cases(check):
    """(vb45) A record the reader cannot read in full refuses the binding of
    its own subject naming what was not read - the unresolved paths of a
    share, or the field of a record that is not the record's shape - and never
    binds an older green row in its place; another subject's record read
    wrong refuses nothing here."""
    root = _harness.fixture_root("verdict-binding-unread")
    try:
        probe = os.path.join(root, "probe")
        os.makedirs(probe)
        mpath = _project(probe, [])
        green = _measured(probe, "R1", "2026-09-01T00:00:00Z")
        record = _evidence_io.run_record(green)
        shared = dict(record, **{
            _evidence_io.SHARED_KEY: ["testedState"],
            _evidence_io.VERDICT_SOURCE: _evidence_io.PART_REUSED,
            "reusedFrom": {"runId": "R0"},
            _evidence_io.REPEATED_RUN_KEY: dict(record, runId="R0")})
        shared.pop("testedState", None)
        shared[_evidence_io.REPEATED_RUN_KEY].pop("testedState", None)
        _put_shard(probe, {"id": "P1", "title": "one", "status": "in_progress",
                           "testGate": ["test"], "tasks": [],
                           _evidence_io.RECORD_KEY: shared})
        os.remove(os.path.join(_evidence_io.evidence_dir(probe),
                               "2026-09.t.jsonl"))
        got = _bind(probe, mpath)
        said = got.get("sentence") or ""
        check("vb45 RED-FIRST: a record whose shared path cannot be given back "
              "from the run it carries refuses on the unreadable arm NAMING "
              "the unresolved path and the share, not a missing digest: %r"
              % ((_said(got), said[-300:]),),
              got.get("state") == "refused"
              and got.get("arm") == M.ARM_UNREADABLE
              and "testedState" in said and _evidence_io.SHARED_KEY in said
              and "scopeDigest" not in said)
        older = os.path.join(root, "older")
        os.makedirs(older)
        mpath = _project(older, [_measured(older, "R1",
                                            "2026-09-01T00:00:00Z")])
        bad = dict(_evidence_io.run_record(
            _measured(older, "R2", "2026-09-02T00:00:00Z")), steps=5)
        _put_shard(older, {"id": "P1", "title": "one", "status": "in_progress",
                           "testGate": ["test"], "tasks": [],
                           _evidence_io.RECORD_KEY: bad})
        try:
            got = _bind(older, mpath)
        except Exception as exc:                               # noqa: BLE001
            got = {"state": "raised", "sentence": "%s: %s"
                   % (type(exc).__name__, exc)}
        said = got.get("sentence") or ""
        check("vb46 RED-FIRST: the subject's newest record malformed, an older "
              "green row of it in the ledger: the binding refuses on the "
              "unreadable arm naming the plan file and the field, and binds "
              "neither run: %r" % ((_said(got), said[-300:]),),
              got.get("state") == "refused"
              and got.get("arm") == M.ARM_UNREADABLE
              and "docs/audit/phases/P1.json" in said
              and "%s.steps" % (_evidence_io.RECORD_KEY,) in said)
        other = os.path.join(root, "other")
        os.makedirs(other)
        # The tree first, so the green row's digest is taken over the file.
        _project(other, [])
        mpath = _project(other, [_measured(other, "R1",
                                            "2026-09-01T00:00:00Z")])
        _put_shard(other, {"id": "P1", "title": "one", "status": "in_progress",
                           "testGate": ["test"],
                           "tasks": [{"id": "P1.1", "title": "t",
                                      "status": "in_progress",
                                      _evidence_io.RECORD_KEY: bad}]})
        try:
            got = _bind(other, mpath)
        except Exception as exc:                               # noqa: BLE001
            got = {"state": "raised", "sentence": "%s: %s"
                   % (type(exc).__name__, exc)}
        check("vb47 ALLOW: a malformed record of ANOTHER subject in the same "
              "file refuses nothing here - the phase's green binds - the case "
              "that goes red if every subject of the file were refused: %r"
              % (_said(got),),
              got.get("state") == "bound" and (got.get("row") or {}).get(
                  "runId") == "R1")
    finally:
        _harness.remove_tree(root)


def _vm_shards(root, bodies):
    """A plan under `root` (made by `_project` first) whose phases are
    `bodies`, one shard each."""
    os.makedirs(os.path.join(root, "docs", "audit", "phases"), exist_ok=True)
    for body in bodies:
        with open(os.path.join(root, "docs", "audit", "phases",
                               "%s.json" % (body["id"],)), "w") as fh:
            json.dump(body, fh)
    with open(os.path.join(root, "docs", "audit", "audit-plan.json"),
              "w") as fh:
        json.dump({"meta": {"version": 3}, "phases": [
            {"id": b["id"], "title": "one", "shard": "phases/%s.json"
             % (b["id"],)} for b in bodies]}, fh)


def _vm_run(root, run_id, ts, pid, status):
    """A phase-scope run of `pid`'s gate, measured on `src/a.py` as it is."""
    return dict(_measured(root, run_id, ts, status=status), phaseId=pid)


def _vm_member(root, member_record, member_tasks=()):
    """`(manifest path, carrier answer)` - carrier P1 holding a green run at
    10:00 that grades the group, member P2 holding `member_record` and
    `member_tasks`; no ledger, so every run is a record."""
    mpath = _project(root, [])
    os.remove(os.path.join(_evidence_io.evidence_dir(root), "2026-09.t.jsonl"))
    green = _vm_run(root, "C-GREEN", "2026-11-18T10:00:00Z", "P1", "passed")
    p1 = {"id": "P1", "title": "one", "status": "in_progress",
          "testGate": ["test"], "tasks": [],
          _evidence_io.RECORD_KEY: _evidence_io.run_record(green)}
    p2 = {"id": "P2", "title": "two", "status": "in_progress",
          "testGate": ["test"], "tasks": list(member_tasks)}
    if member_record is not None:
        p2[_evidence_io.RECORD_KEY] = member_record
    _vm_shards(root, [p1, p2])
    return mpath, {"state": "bound", "row": green, "measured": green,
                   "notes": []}


def _member_cases(check):
    """(vm) A group member's own runs are chosen by the one selection the
    binding uses, read from what the read returns: a member whose own record
    would not read refuses the landing naming that record, and a base run a
    member's task keeps is nobody's verdict, for the member check as for the
    binding."""
    root = _harness.fixture_root("verdict-binding-member-")
    try:
        said = {}
        for name, malformed in (("readable", False), ("malformed", True)):
            here = os.path.join(root, name)
            os.makedirs(here)
            _project(here, [])
            red = _evidence_io.run_record(_vm_run(
                here, "M-RED", "2026-11-18T11:00:00Z", "P2", "failed"))
            if malformed:
                red["steps"] = 5
            mpath, carrier = _vm_member(here, red)
            records = M.plan_records(here, mpath)[0]
            try:
                got = M.member_red([], "P2", carrier, "record the member",
                                   records=records)
            except Exception as exc:                           # noqa: BLE001
                got = {"arm": "raised", "sentence": "%s: %s"
                       % (type(exc).__name__, exc)}
            said[name] = got or {}
        bad = said["malformed"]
        check("vm1 RED-FIRST: a group member whose own newest record is a red "
              "that will not read, newer than the carrier's green, refuses the "
              "landing on the unreadable arm naming the plan file and the "
              "field - handed only the records the landing reads, never what "
              "that read lost: %r" % ((bad.get("arm"),
                                        (bad.get("sentence") or "")[-300:]),),
              bad.get("state") == "refused"
              and bad.get("arm") == M.ARM_UNREADABLE
              and "docs/audit/phases/P2.json" in (bad.get("sentence") or "")
              and "%s.steps" % (_evidence_io.RECORD_KEY,)
              in (bad.get("sentence") or ""))
        check("vm2 ...THE ORACLE: the same red, well-formed, refuses as the "
              "member's red naming its run - the malformed case is not refused "
              "for some other reason: %r" % ((said["readable"].get("arm"),
                                              (said["readable"].get("row") or {})
                                              .get("runId")),),
              said["readable"].get("arm") == M.ARM_RED
              and (said["readable"].get("row") or {}).get("runId") == "M-RED")

        # ONE SELECTION: a kept base run a member's task holds, newer than the
        # carrier's run and red, is a measurement of the base commit - the
        # binding gives the member no verdict from it, so the member check
        # must not refuse on it either.
        kb = os.path.join(root, "kept-base")
        os.makedirs(kb)
        _project(kb, [])
        step = {"name": "test", "exit": 1, "ran": 3, "measured": "measured",
                "durationMs": 9}
        task_red = _evidence_io.run_record({
            "v": 1, "runId": "T-RED", "ts": "2026-11-18T09:00:00Z",
            "scope": "task", "taskId": "P2.1", "phaseId": "P2",
            "status": "failed", "steps": [step],
            "testedState": {"head": "c0ffee12ab34"},
            _evidence_io.BASE_RED_KEY: {
                "head": "c0ffee12ab34", "verdict": "no-base",
                "atBase": [], "introduced": [], "unknown": [],
                "basis": "no run recorded at base"}})
        base = {"v": 1, "runId": "RB", "ts": "2026-11-18T11:30:00Z",
                "scope": _evidence_io.BASE_SCOPE, "status": "failed",
                _evidence_io.BASE_OF_KEY: "T-RED",
                "testedState": {"head": "c0ffee12ab34"}, "steps": [step]}
        task_red[_evidence_io.BASE_RED_KEY] = dict(
            task_red[_evidence_io.BASE_RED_KEY],
            **{_evidence_io.BASE_RUNS_KEY: [_evidence_io.kept_base(base)]})
        mpath, carrier = _vm_member(kb, None, member_tasks=[
            {"id": "P2.1", "title": "t", "status": "in_progress",
             _evidence_io.RECORD_KEY: task_red}])
        records, lost = M.plan_records(kb, mpath)
        member = M.member_red([], "P2", carrier, "record the member",
                              records=records)
        own = M.binding(kb, {"phaseId": "P2"}, ["test"], "phase", ["src/a.py"],
                        mpath, "run the gate", "no gate here", texts=[],
                        records=records, records_lost=lost)
        # THE FIXTURE MUST REACH THE SELECTION: the task's record reads, and
        # the kept base run is among the runs the member check is handed - a
        # record that would not read answers both questions on another arm.
        seen = [(r.get("scope"), r.get("runId"))
                for r in M.subject_runs([], records)]
        check("vm3 RED-FIRST, ONE SELECTION: a red base run kept on a member's "
              "task, newer than the carrier's green, is no verdict of the "
              "member - the binding gives the member none, and the member "
              "check agrees and refuses nothing, the record reading and its "
              "base run among the runs both are handed: binding=%r member=%r "
              "lost=%r runs=%r"
              % (_said(own), _said(member or {}), lost, seen),
              own.get("arm") == M.ARM_NO_VERDICT and own.get("row") is None
              and member is None and not lost
              and (_evidence_io.BASE_SCOPE, "RB") in seen
              and not any(str(i).startswith("unreadable-record:")
                          for _s, i in seen))
    finally:
        _harness.remove_tree(root)


def _selftest():
    def body(check):
        _cases(check)
        _harness.stage(check, "vb-tree-block", _tree_binding_cases)
        _harness.stage(check, "vb-record-block", _record_binding_cases)
        _harness.stage(check, "vb-unread-block", _unread_binding_cases)
        _harness.stage(check, "vb-base-block", _kept_base_binding_cases)
        _harness.stage(check, "vb-member-block", _member_cases)
    return _harness.run(body)


def _kb_phase_bodies(root, phase_status, base_status):
    """`(records, records_lost)` of a plan whose phase P1 holds its own run
    (`phase_status`, measured on the declared files as they stand) and whose
    task P1.1 holds a red keeping a NEWER base run (`base_status`) measured at
    the base commit - one whose tested state carries the same declared-work
    digest, as a base commit whose declared files the task has not changed
    does."""
    here = _tree_stamp.scope_digest(root, ["src/a.py"])[0]
    gate = _evidence_io.gate_digest(["test"], None)
    step = {"name": "test", "exit": 0 if phase_status == "passed" else 1,
            "ran": 3, "measured": "measured", "durationMs": 9}
    phase = {"v": 1, "runId": "PH", "ts": "2026-11-18T04:00:00Z",
             "scope": "phase", "phaseId": "P1", "status": phase_status,
             "gateSource": "phase", "gateDigest": gate, "steps": [step],
             "testedState": {"head": "h", "scopeDigest": here}}
    red = {"v": 1, "runId": "R1", "ts": "2026-11-18T04:04:19Z",
           "scope": "task", "taskId": "P1.1", "phaseId": "P1",
           "status": "failed", "steps": [dict(step, exit=1)],
           "testedState": {"head": "c0ffee12ab34"},
           _evidence_io.BASE_RED_KEY: {
               "head": "c0ffee12ab34", "verdict": "no-base",
               "atBase": [], "introduced": [], "unknown": [],
               "basis": "no run recorded at base"}}
    base = {"v": 1, "runId": "RB", "ts": "2026-11-18T04:30:00Z",
            "scope": _evidence_io.BASE_SCOPE, "status": base_status,
            _evidence_io.BASE_OF_KEY: "R1",
            "testedState": {"head": "c0ffee12ab34", "scopeDigest": here},
            "steps": [dict(step, exit=0 if base_status == "passed" else 1)]}
    task = _evidence_io.run_record(red)
    task[_evidence_io.BASE_RED_KEY] = dict(
        task[_evidence_io.BASE_RED_KEY],
        **{_evidence_io.BASE_RUNS_KEY: [_evidence_io.kept_base(base)]})
    bodies = [("docs/audit/phases/P1.json", {
        "id": "P1", _evidence_io.RECORD_KEY: _evidence_io.run_record(phase),
        "tasks": [{"id": "P1.1", _evidence_io.RECORD_KEY: task}]})]
    doc = _evidence_io.record_schema()[0]
    return (_evidence_io.records_of_bodies(bodies, doc),
            _evidence_io.unreadable_records(bodies, doc))


def _kept_base_binding_cases(check):
    """(vb-base) A base run a task's red keeps is a run of the BASE commit,
    measured for that task - no subject's evidence (`subject_key`) - so the
    phase's binding never reads it as the phase's newest verdict: the phase's
    own run decides, red or green, whatever the kept base run says."""
    root = _harness.fixture_root("verdict-binding-kept-base-")
    try:
        mpath = _project(root, [])
        said = {}
        for phase_status, base_status in (("passed", "failed"),
                                          ("failed", "passed")):
            records, lost = _kb_phase_bodies(root, phase_status, base_status)
            answer = M.binding(root, PHASE, ["test"], "phase", ["src/a.py"],
                               mpath, "run the gate", "no gate here", texts=[],
                               records=records, records_lost=lost)
            # The fixture must reach the binding: the task's record reads and
            # its kept base run is among the runs the binding is handed.
            reached = (not lost and ("base", "RB") in [
                (r.get("scope"), r.get("runId"))
                for r in M.subject_runs([], records)])
            said[phase_status] = (answer.get("state"), answer.get("arm"),
                                  (answer.get("row") or {}).get("runId"),
                                  reached)
        check("vb-base1 RED-FIRST: a phase whose own newest run is GREEN binds "
              "to that run - a newer RED base run kept on a task's record, "
              "read and handed to the binding, is not the phase's verdict and "
              "does not refuse it: %r" % (said["passed"],),
              said["passed"] == ("bound", None, "PH", True))
        check("vb-base2 RED-FIRST, THE OTHER DIRECTION: a phase whose own newest "
              "run is RED is refused on that red - a newer GREEN base run kept "
              "on a task's record, carrying the same declared-work digest, "
              "read and handed to the binding, never binds the phase over it: "
              "%r" % (said["failed"],),
              said["failed"] == ("refused", M.ARM_RED, "PH", True))
    finally:
        _harness.remove_tree(root)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__verdict_binding.py --selftest\n")
    raise SystemExit(2)
