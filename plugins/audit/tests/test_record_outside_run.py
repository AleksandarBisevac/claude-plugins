#!/usr/bin/env python3
"""
The cases for `record-outside-run.py` — a suite that ran where this plugin could
not see it, and the row that stops a gate crediting itself with its effects.

`record-outside-run.py` is hyphenated, so it comes through
`_loader.load_script`; `test_record_risk_confirmation.py` is the precedent for
that and for the one-`tempfile.mkdtemp()`-removed-in-a-`finally` shape.

WHAT IS PINNED, and why each one is here rather than trusted:

- **BOTH DIRECTIONS OF THE OVERLAP.** A row written for a window that touches a
  recorded gate run contests it; one written for a window that does not, does
  not. Either case alone also passes for a version that answers the same way
  always, which is the mutation this whole feature has to survive — a rule that
  reported every run as contested would be switched off within a day, and one
  that reported none is the state this command was written to end.
- **The row has NO subject, asserted rather than assumed.** `latest_by_subject`
  and `reusable_run` are the readers that would turn an outside suite into
  evidence for a task, and the cases drive both of them over a ledger holding
  one of these rows.
- **`runner` is what makes the row what it is.** Absent means the gate, so a
  writer that failed to set it would file an outside suite as a run this plugin
  made — and every window case would still pass.
- **A window that will not parse is a refusal, not a guess.** The window is the
  whole value of the row.
- **The stamp reader is the LEDGER's.** A writer parsing instants its own way
  would disagree with the module deciding whether two of them overlap, by a time
  zone — so the round trip through `_evidence_io.window_of` is asserted rather
  than the string being compared to itself.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import io
import json
import os
import shutil
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _evidence_io as _ev                         # noqa: E402
import _journal_io                                 # noqa: E402
import _loader                                     # noqa: E402

M = _loader.load_script("record-outside-run.py", modname="record_outside_run")

LABEL = "pre-push hook: npm test  (second terminal)"


def _manifest():
    return {"meta": {"version": 2},
            "phases": [{"id": "P1", "title": "One", "status": "in_progress",
                        "tasks": [{"id": "P1.1", "title": "a",
                                   "status": "in_progress"}]}]}


def _gate_row(project, run_id, started_at, ts):
    """A row shaped as `run-test-gate` writes one: a task-scoped GATE run, which
    is what the outside row has to be able to contest.

    Written through `_evidence_io.record` rather than hand-appended, because the
    claim is about a row the product really produces - a dict with the right keys
    would prove that this suite can build one.
    """
    result = {"status": "failed", "durationMs": 60000, "failed": ["test"],
              "steps": []}
    identity = {"runId": run_id, "via": "cli", "sessionId": None,
                _ev.STARTED_KEY: started_at, "ts": ts}
    return _ev.record(project, result, "task", {"taskId": "P1.1", "phaseId": "P1"},
                      identity)["row"]


def _cases(check):
    root = tempfile.mkdtemp(prefix="record-outside-run-selftest-")

    def project():
        d = tempfile.mkdtemp(dir=root)
        os.makedirs(os.path.join(d, ".claude"))
        os.makedirs(os.path.join(d, "docs", "audit"))
        with io.open(os.path.join(d, ".claude", "audit.config.json"),
                     "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"manifestPath": "docs/audit/audit-plan.json"}))
        mpath = os.path.join(d, "docs", "audit", "audit-plan.json")
        with io.open(mpath, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(_manifest(), indent=2))
        return d, mpath

    def run(argv):
        lines = []
        held = sys.stderr
        sys.stderr = io.StringIO()
        try:
            code = M.main(argv, out=lines.append)
        finally:
            sys.stderr = held
        return code, "\n".join(lines)

    def rows(proj):
        return _ev.read_rows(proj)["rows"]

    try:
        # --- the window, asked directly ---------------------------------------
        started, ts, ms, why = M.window("2026-09-01T10:00:00Z",
                                        "2026-09-01T10:05:00Z", None)
        check("w1 an explicit end is taken as given, and the duration is derived "
              "from the pair rather than asked for twice: %r"
              % ((started, ts, ms),),
              why == "" and started == "2026-09-01T10:00:00Z"
              and ts == "2026-09-01T10:05:00Z" and ms == 300000)
        started, ts, ms, why = M.window("2026-09-01T10:00:00Z", None, 120000)
        check("w2 ...and a duration the runner measured reaches the same end: %r"
              % ((started, ts, ms),),
              why == "" and ts == "2026-09-01T10:02:00Z" and ms == 120000)
        for bad in ("yesterday", "2026-09-01 10:00:00", "", None, "1756720800"):
            _s, _t, _m, why = M.window(bad, None, None)
            check("w3 --started %r is refused rather than guessed at: the window "
                  "is the whole value of this row, so one with no readable start "
                  "answers the only question it was written for with 'not "
                  "knowable'" % (bad,),
                  bool(why), repr(why))
        _s, _t, _m, why = M.window("2026-09-01T10:05:00Z", "2026-09-01T10:00:00Z",
                                   None)
        check("w4 an end BEFORE the start describes no interval, and an overlap "
              "computed over a negative one is arithmetic nobody can read back",
              bool(why), repr(why))

        # --- the row the command writes ---------------------------------------
        d, mp = project()
        gate = _gate_row(d, "run-gate-1", "2026-09-01T10:00:00Z",
                         "2026-09-01T10:10:00Z")
        code, out = run([mp, "--project", d, "--label", LABEL,
                         "--started", "2026-09-01T10:05:00Z",
                         "--ended", "2026-09-01T10:06:00Z", "--json"])
        answer = json.loads(out) if code == 0 else {}
        written = [r for r in rows(d) if r.get("runId") == answer.get("runId")]
        row = written[0] if written else {}
        check("o1 the row is written and the command says which run it is: %r / %r"
              % (code, answer.get("runId")),
              code == 0 and len(written) == 1 and bool(answer.get("runId")))
        check("o2 ...and it carries `runner: outside`, which is the ONE field "
              "that makes it what it is. Absent means the gate - every row "
              "written before the key existed was the wrapper's - so a writer "
              "that failed to set it would file an outside suite as a run this "
              "plugin made, and every window case here would still pass: %r"
              % (_ev.runner_of(row),),
              _ev.runner_of(row) == _ev.RUNNER_OUTSIDE)
        check("o3 ...and the operator's label is stored as the step's `name`, "
              "byte for byte. A `command` would be digested to a hash and a "
              "program token, which is right for a string nobody published and "
              "useless here: the label IS the identification a reader of a "
              "contested verdict needs: %r" % (row.get("steps"),),
              [s.get("name") for s in (row.get("steps") or [])] == [LABEL])
        window = _ev.window_of(row)
        check("o4 ...and the LEDGER reads the window back as the one that was "
              "given, through its own parser rather than this file's: a writer "
              "reading instants its own way would disagree with the module that "
              "decides whether two of them overlap, by a time zone: %r"
              % (window,),
              window[1] - window[0] == 60
              and "recorded" in (window[2] or ""))

        # --- both directions of the overlap ------------------------------------
        check("o5 the gate run whose window this one lands inside IS reported as "
              "contested, on the run that writes the row - the operator "
              "recording an outside suite is the one person able to act on the "
              "answer, and telling them on somebody else's gate run later is "
              "telling the wrong reader: %r" % (answer.get("contests"),),
              answer.get("contests") == ["run-gate-1"])
        contested, _basis = _ev.contested_by(rows(d), gate)
        check("o6 ...and the gate's own question now answers the same way, which "
              "is the whole point: before this row existed `contested_by` could "
              "only ever return an empty list, which is a check that cannot "
              "fire: %r" % ([r.get("runId") for r in (contested or [])],),
              contested is not None
              and [r.get("runId") for r in contested] == [answer["runId"]])
        verdict = _ev.attribution_of(gate, rows(d))
        check("o7 ...so the red is CONTESTED rather than the gate's to claim, "
              "and the basis names the rival: %r" % (verdict,),
              verdict["attributed"] is False
              and verdict["contested"] == [answer["runId"]])

        d2, mp2 = project()
        gate2 = _gate_row(d2, "run-gate-2", "2026-09-01T10:00:00Z",
                          "2026-09-01T10:10:00Z")
        code, out = run([mp2, "--project", d2, "--label", "a later suite",
                         "--started", "2026-09-01T11:00:00Z",
                         "--ended", "2026-09-01T11:05:00Z", "--json"])
        answer2 = json.loads(out) if code == 0 else {}
        verdict2 = _ev.attribution_of(gate2, rows(d2))
        check("o8 SECOND-DIRECTION CASE: an outside run that did NOT share the "
              "window contests nothing, and the gate's verdict stays its own. A "
              "rule that reported every run as contested would pass every case "
              "above and be routed around within a day: %r / %r"
              % (answer2.get("contests"), verdict2["attributed"]),
              code == 0 and answer2.get("contests") == []
              and verdict2["attributed"] is True)

        # --- the bound: the row has no subject ---------------------------------
        subjects = _ev.latest_by_subject(rows(d))
        check("o9 the outside row is in NO subject's pointer map - it carries no "
              "task or phase id, so nothing can point a plan at it and no task "
              "can be closed against it: %r" % (sorted(subjects),),
              all(key[0] in ("task", "phase") for key in subjects)
              and all(r.get("runId") != answer["runId"]
                      for r in subjects.values()))
        check("o10 ...and its scope is a word of its OWN rather than `task` or "
              "`phase`, so every subject reader answers exactly as it did before "
              "instead of special-casing a row with no id: %r"
              % (row.get("scope"),),
              row.get("scope") == M.SCOPE_OUTSIDE
              and M.SCOPE_OUTSIDE not in ("task", "phase"))
        check("o11 ...and `reusable_run` cannot return it whatever it is asked, "
              "because the row carries no reuse identity at all - a suite this "
              "plugin did not run must never stand in for a measurement it owes",
              _ev.reusable_run(rows(d), M.SCOPE_OUTSIDE, {},
                               row.get(_ev.REUSE_KEY), ("passed", "failed"))
              is None
              and _ev.reusable_run(rows(d), "task",
                                   {"taskId": "P1.1", "phaseId": "P1"},
                                   row.get(_ev.REUSE_KEY), ("failed",)) is None,
              repr(row.get(_ev.REUSE_KEY)))

        # --- the verdict, which is absent unless it was given -------------------
        check("o12 no `--status` means the row records no verdict: nobody told "
              "this command what the outside suite answered, and a word invented "
              "to fill the field would be a claim with no basis under it: %r"
              % (row.get("status"),),
              row.get("status") is None)
        d3, mp3 = project()
        code, out = run([mp3, "--project", d3, "--label", "x",
                         "--started", "2026-09-01T10:00:00Z",
                         "--duration-ms", "1000", "--status", "failed", "--json"])
        answer3 = json.loads(out) if code == 0 else {}
        row3 = [r for r in rows(d3) if r.get("runId") == answer3.get("runId")][0]
        check("o13 ...and a verdict that WAS given is written through as given: "
              "%r" % (row3.get("status"),),
              row3.get("status") == "failed")

        # --- refusals -----------------------------------------------------------
        d4, mp4 = project()
        code, _out = run([mp4, "--project", d4, "--label", "   ",
                          "--started", "2026-09-01T10:00:00Z"])
        check("e1 a blank label is refused: a rival nobody can identify is a row "
              "that names a problem and not a suite: %r" % (code,), code == 2)
        code, _out = run([os.path.join(d4, "no-such.json"), "--project", d4,
                          "--label", "x", "--started", "2026-09-01T10:00:00Z"])
        check("e2 a manifest that will not load is a usage error: %r" % (code,),
              code == 2)
        code, _out = run([mp4, "--project", d4, "--label", "x",
                          "--started", "not-an-instant"])
        check("e3 ...and so is a start nothing can read, which is the refusal "
              "`window` above produces and this is the door it reaches: %r"
              % (code,), code == 2)
        check("e4 ...and none of the three wrote a row, so a refused call leaves "
              "the ledger exactly as it found it: %r" % (len(rows(d4)),),
              len(rows(d4)) == 0)

        # --- the trail ----------------------------------------------------------
        trail = [r for r in _journal_io.read_all(d)
                 if r.get("action") == _ev.ACTION_RECORDED]
        check("t1 the row is anchored in the journal by the ledger's own "
              "recorder, so an outside run leaves the same kind of trail a gate "
              "run does rather than a second shape wearing one name: %r"
              % ([r.get("details", {}).get("runId") for r in trail],),
              any(r.get("details", {}).get("runId") == answer["runId"]
                  for r in trail))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_record_outside_run.py --selftest\n")
    raise SystemExit(2)
