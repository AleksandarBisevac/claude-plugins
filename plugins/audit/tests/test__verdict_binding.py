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


def _cases(check):
    check("vb1 a gate measured under the same entries is not a mismatch",
          M.gate_mismatch({"steps": [{"name": "test"}]}, ["test"], "phase") is None)
    check("vb2 ...and one measured under other entries is, saying both",
          "[lint]" in (M.gate_mismatch({"steps": [{"name": "lint"}]}, ["test"],
                                       "phase") or ""))
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


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__verdict_binding.py --selftest\n")
    raise SystemExit(2)
