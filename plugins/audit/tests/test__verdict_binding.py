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
