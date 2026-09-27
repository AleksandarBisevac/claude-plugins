#!/usr/bin/env python3
"""
The cases for `status/audit-lookup.py` - one question, one answer, one pointer.

THE DISCIPLINE EVERY CASE HOLDS TO: a lookup that matches nothing SAYS SO
(`al1`, `al5`, `al7`) and never reads a sibling id or a similar path as the
answer instead - `al7` is the over-fire case, a path that almost matches an
indexed one, and it must come back exactly as unmatched as a path sharing
nothing with the index at all. An id that exists but does not apply to the
question (a task that was never cancelled) is a different, legitimate answer
and not a miss (`al2`).

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import contextlib
import io
import json
import os
import shutil
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                      # noqa: E402
import _journal_io                                  # noqa: E402
import _evidence_io as _evio                        # noqa: E402

M = _loader.load_script("audit-lookup.py", modname="audit_lookup")


def _manifest():
    return {
        "phases": [
            {"id": "P1", "status": "done", "tasks": [
                {"id": "P1.1", "status": "done",
                 "files": ["src/a.py", "src/c.py"]},
                {"id": "P1.2", "status": "cancelled",
                 "outcome": {"descriptive": "Cancelled: superseded by P1.3"}},
                {"id": "P1.3", "status": "pending"},
            ]},
            {"id": "P2", "status": "cancelled", "summary": "Cancelled: scope dropped",
             "tasks": []},
        ],
        "bugs": [
            {"id": "BUG-1", "status": "wontfix", "notes": "not reachable in prod",
             "fixedIn": None, "taskId": None},
        ],
        "fileIndex": {
            "src/a.py": ["P1.1", "P1.2"],
            "src/b.py": ["P1.1"],
        },
    }


def _cases(check):
    man = _manifest()

    # --- cancel -------------------------------------------------------------
    found, msg = M.cancel_lookup(man, [], "P9.9")
    check("al1 an id this manifest does not have at all is the one true miss "
          "- found is False and the message names the id: %r" % (msg,),
          found is False and "P9.9" in msg)

    found, payload = M.cancel_lookup(man, [], "P1.1")
    check("al2 a task that exists but was never cancelled is a legitimate "
          "answer, not a miss - `cancelled: False` with its real status: %r"
          % (payload,),
          found is True and payload["cancelled"] is False
          and payload["status"] == "done")

    found, payload = M.cancel_lookup(man, [], "P1.2")
    check("al3 a cancelled TASK's reason comes off `outcome.descriptive`, "
          "exactly where the cancel verb itself writes it, with a pointer at "
          "that field: %r" % (payload,),
          found is True and payload["cancelled"] is True
          and "superseded by P1.3" in payload["reasonText"]
          and payload["pointer"] == "P1.2.outcome.descriptive in the manifest")

    found, payload = M.cancel_lookup(man, [], "P2")
    check("al4 a cancelled PHASE's reason comes off `summary` instead - the "
          "field the cancel verb actually writes for a phase, never "
          "`outcome` which phases do not carry: %r" % (payload,),
          found is True and payload["kind"] == "phase"
          and "scope dropped" in payload["reasonText"]
          and payload["pointer"] == "P2.summary in the manifest")

    # A journal row for the SAME task, plus a decoy row for its phase under one
    # id that could be confused for the other if matching read `target`
    # instead of `details`.
    rows = [
        {"action": "phase.cancel", "ts": "2026-01-01T00:00:00Z",
         "details": {"phaseId": "P1", "reason": "phase-level reason"},
         "_file": "2026-01.a.jsonl"},
        {"action": "task.cancel", "ts": "2026-01-02T00:00:00Z",
         "details": {"taskId": "P1.2", "phaseId": "P1",
                    "reason": "superseded by P1.3"},
         "_file": "2026-01.a.jsonl"},
    ]
    found, payload = M.cancel_lookup(man, rows, "P1.2")
    check("al5 the journal cross-check matches by `details.taskId`, never by "
          "a shared phase id or the row's shard `target` - the decoy "
          "phase.cancel row above must not be picked up for the task's own "
          "question: %r" % (payload.get("journal"),),
          payload["journal"]["reason"] == "superseded by P1.3"
          and payload["journal"]["ts"] == "2026-01-02T00:00:00Z")

    found, payload = M.cancel_lookup(man, [], "P1.2")
    check("al6 with NO journal rows at all the manifest's own fields still "
          "answer the question - the journal cross-check is a bonus pointer, "
          "never a requirement for the answer to exist: %r" % (payload,),
          found is True and "journal" not in payload)

    # --- bug ------------------------------------------------------------------
    found, msg = M.bug_lookup(man, "BUG-9")
    check("al7 a bug id not in `bugs[]` is a true miss: %r" % (msg,),
          found is False and "BUG-9" in msg)

    found, payload = M.bug_lookup(man, "BUG-1")
    check("al8 a bug's conclusion is its own `status`/`notes` - there is no "
          "separate resolution field in this schema, so this is the honest "
          "answer rather than an invented one: %r" % (payload,),
          found is True and payload["status"] == "wontfix"
          and payload["notes"] == "not reachable in prod"
          and payload["pointer"] == "bugs[0] in the manifest")

    # --- stored against derived ------------------------------------------------
    # The answer is the DERIVED value, and where the stored one differs both are
    # printed with the basis - a lookup that echoed the stored field would give the
    # stale answer the derivation exists to correct.
    stale = _manifest()
    stale["phases"].append({"id": "P3", "status": "in_progress",
                            "review": {"status": "passed"},
                            "tasks": [{"id": "P3.1", "status": "done",
                                       "commit": "abc1234", "bugId": "BUG-2"}]})
    stale["bugs"].append({"id": "BUG-2", "status": "triaged", "notes": None,
                          "fixedIn": None, "taskId": "P3.1"})
    found, payload = M.bug_lookup(stale, "BUG-2")
    lines = M._render_human("bug", "BUG-2", found, payload)
    check("al30 a bug whose fix task is done reads its DERIVED status and "
          "fixedIn, and the render says what is stored, what is derived, and on "
          "what basis: %r / %r" % (payload, lines),
          found is True and payload["status"] == "fixed"
          and payload["fixedIn"] == "abc1234"
          and payload["stored"] == {"status": "triaged", "fixedIn": None}
          and any("stored triaged, derived fixed" in ln
                  and "fixedIn stored None, derived abc1234" in ln
                  and "(fix task P3.1 is done at abc1234)" in ln for ln in lines))
    found, payload = M.cancel_lookup(stale, [], "P3")
    lines = M._render_human("cancel", "P3", found, payload)
    check("al31 a phase's status is the derived one too, with the stored value "
          "and basis beside it where they differ: %r" % (lines,),
          payload["status"] == "done" and payload["stored"] == "in_progress"
          and any("stored in_progress, derived done" in ln
                  and "review.status passed" in ln for ln in lines))
    found, payload = M.bug_lookup(man, "BUG-1")
    lines = M._render_human("bug", "BUG-1", found, payload)
    check("al32 SECOND DIRECTION: where stored and derived agree nothing about a "
          "difference is said - the case that goes red when the line is printed "
          "unconditionally: %r" % (lines,),
          "stored" not in payload and not any("derived" in ln for ln in lines))

    # --- file -------------------------------------------------------------
    found, msg = M.file_lookup(man, "src/c.py")
    check("al9 a path fileIndex never recorded is a miss - no nearest-path "
          "guess: %r" % (msg,), found is False)

    found, msg = M.file_lookup(man, "src/a")
    check("al10 THE OVER-FIRE CASE: a path that is a PREFIX of an indexed one "
          "must read exactly as unmatched as one sharing nothing with the "
          "index - a lookup that matched on prefix would be a search wearing "
          "a lookup's name: %r" % (msg,), found is False)

    found, payload = M.file_lookup(man, "src/a.py")
    check("al11 the LAST entry in fileIndex[path] is the answer, by the "
          "index's own append-only convention - never the first or a count: "
          "%r" % (payload,),
          found is True and payload["last"] == "P1.2"
          and payload["lastStatus"] == "cancelled"
          and payload["declaringTasks"] == ["P1.1", "P1.2"])

    # A RANGED DECLARATION: `add`/`scope` key the row by the PATH, so a lookup of
    # the entry as the task spells it must find that row, not report it absent.
    _rg = _manifest()
    _rg["phases"][0]["tasks"].append({"id": "P1.4", "status": "pending",
                                      "files": ["src/q.ts:10-20"]})
    _rg["fileIndex"]["src/q.ts"] = ["P1.4"]
    found, payload = M.file_lookup(_rg, "src/q.ts:10-20")
    found_b, brief = M.brief_lookup(_rg, "P1.4")
    check("al40 a `:line-range` entry is looked up by its PATH - the key the gate, "
          "the validator and the writers use - and keeps the entry as typed in "
          "the answer: %r" % ((payload, brief),),
          found is True and payload["last"] == "P1.4"
          and payload["path"] == "src/q.ts:10-20" and found_b is True
          and brief["files"][0]["last"] == "P1.4")
    found, msg = M.file_lookup(_rg, "src/q")
    check("al41 SECOND DIRECTION: the match is still exact on the path - a prefix "
          "of the key is a miss: %r" % (msg,), found is False)

    # --- brief --------------------------------------------------------------
    # The one thing a spawn prompt is missing: `task.files` is already handed
    # to an executor, but who last declared each of those paths is not - and
    # that is the question `brief_lookup` answers in one call, folding
    # `file_lookup` over a task's own `files` instead of leaving an agent to
    # grep the manifest or the journal for it.
    found, msg = M.brief_lookup(man, "P9.9")
    check("al14 a task id this manifest does not have at all is a miss, "
          "exactly like the other three questions: %r" % (msg,),
          found is False and "P9.9" in msg)

    found, msg = M.brief_lookup(man, "P2")
    check("al15 a PHASE id is a miss here, never an empty-files answer - "
          "`files` is a task field, and brief_lookup does not inherit "
          "cancel_lookup's phase reading just because a phase id resolves "
          "fine there: %r" % (msg,),
          found is False)

    found, payload = M.brief_lookup(man, "P1.3")
    check("al16 a task that declares no files yet is a legitimate answer, "
          "not a miss - the question was answerable and the plan simply "
          "names nothing here yet: %r" % (payload,),
          found is True and payload["files"] == [])

    found, payload = M.brief_lookup(man, "P1.1")
    check("al17 brief_lookup is file_lookup folded over the task's OWN "
          "files, in the task's own declared order - one entry per "
          "declared path, including one `fileIndex` never recorded, so a "
          "caller does not have to tell the two cases apart itself: %r"
          % (payload,),
          found is True and payload["files"] == [
              {"path": "src/a.py", "declaringTasks": ["P1.1", "P1.2"],
               "last": "P1.2", "lastStatus": "cancelled"},
              {"path": "src/c.py", "declaringTasks": [], "last": None,
               "lastStatus": None},
          ])

    # --- run ------------------------------------------------------------------
    # A long gate runs in the background under `run_in_background` and its
    # verdict is read from the evidence ledger, not from a truncated terminal -
    # these rows are shaped exactly as `_evio.row_for` writes them, MAX_FAILING
    # truncation already applied by the writer, never re-derived here.
    r1 = {"v": 1, "runId": "R-1", "ts": "2026-06-01T10:00:00Z",
          "scope": "task", "taskId": "P1.1", "status": "passed", "failed": [],
          "steps": [{"name": "lint", "exit": 0, "durationMs": 120}]}
    r2 = {"v": 1, "runId": "R-2", "ts": "2026-06-02T10:00:00Z",
          "scope": "task", "taskId": "P1.1", "status": "failed",
          "failed": ["gate"],
          "steps": [{"name": "gate", "exit": 1, "durationMs": 500,
                     "outcome": "failed",
                     "failing": ["AssertionError: x != y"],
                     "failingBasis": "jest summary line",
                     "failingSuites": ["tests/test_x.py"],
                     "failingSuitesBasis": "1 suite named"}],
          "verdictSource": "reused",
          "reusedFrom": {"runId": "R-1", "ts": "2026-06-01T10:00:00Z",
                         "status": "passed"}}
    r3 = {"v": 1, "runId": "R-3", "ts": "2026-06-03T10:00:00Z",
          "scope": "phase", "phaseId": "P1", "status": "passed", "failed": [],
          "steps": [{"name": "selftests", "exit": 0, "durationMs": 300}]}
    run_rows = [r1, r2, r3]

    found, payload = M.run_lookup(run_rows, "R-2")
    check("rl1 a known runId answers the bounded render of that one row - "
          "status, per-step exit/duration/outcome, the failing lines and "
          "failingSuites with their bases EXACTLY as recorded, and "
          "verdictSource/reusedFrom because this row is a repeat: %r"
          % (payload,),
          found is True and payload["status"] == "failed"
          and payload["steps"][0]["failing"] == ["AssertionError: x != y"]
          and payload["steps"][0]["failingSuites"] == ["tests/test_x.py"]
          and payload["verdictSource"] == "reused"
          and payload["reusedFrom"]["runId"] == "R-1")

    found, msg = M.run_lookup(run_rows, "R-9")
    check("rl2 an unknown runId is a miss worded like `bug`'s own unknown-id "
          "miss - never 'no such run', which reads as a stronger claim than "
          "an unreadable ledger is entitled to: %r" % (msg,),
          found is False and "R-9" in msg)

    found, payload = M.run_lookup(run_rows, "latest", task_id="P1.1")
    check("rl3 'latest' with --task answers the NEWEST recorded row for that "
          "task - never the first with a matching subject, which is exactly "
          "the mutation this case is written to catch on a fixture holding "
          "two rows for the same task: %r" % (payload,),
          found is True and payload["runId"] == "R-2")

    found, payload = M.run_lookup(run_rows, "latest", phase_id="P1")
    check("rl4 'latest' with --phase reads the phase's own subject key, not "
          "the task's: %r" % (payload,),
          found is True and payload["runId"] == "R-3")

    found, msg = M.run_lookup(run_rows, "latest", task_id="P9.9")
    check("rl5 'latest' for a subject with no recorded run at all is a miss "
          "too, worded for the subject rather than a runId: %r" % (msg,),
          found is False and "P9.9" in msg)

    found, msg = M.run_lookup([], "R-9", unreadable=2)
    check("rl6 an unreadable ledger is SAID, never read as 'no such run' - "
          "the miss folds in how many ledger files could not be read, so a "
          "caller does not mistake a run that is genuinely absent for one "
          "sitting in a file nothing here could open: %r" % (msg,),
          found is False and "2" in msg and "could not be read" in msg)

    aliased_rows = [{"v": 1, "runId": "R-old", "ts": "2026-06-01T10:00:00Z",
                     "scope": "task", "taskId": "P1.1old", "status": "passed",
                     "failed": [], "steps": []}]
    found, payload = M.run_lookup(
        aliased_rows, "latest", task_id="P1.9",
        aliases={("task", "P1.1old"): ("task", "P1.9")})
    check("rl7 a task moved to a new id still answers 'latest' under the new "
          "id - the alias map `subject_aliases` builds is read exactly as "
          "`_evio.latest_by_subject` reads it elsewhere: %r" % (payload,),
          found is True and payload["runId"] == "R-old")

    r4 = {"v": 1, "runId": "R-4", "ts": "2026-06-04T10:00:00Z",
          "scope": "task", "taskId": "P1.1", "status": "could-not-run",
          "failed": [],
          "steps": [{"name": "unit", "exit": 1, "durationMs": 90,
                     "outcome": "could-not-run",
                     "outcomeBasis": "no test files found",
                     "derivedGap": True}]}
    found, payload = M.run_lookup([r1, r4], "R-4")
    check("rl8 a `could-not-run` row keeps its step's `outcomeBasis` and "
          "`derivedGap` in the rendered payload - the reason nothing was "
          "measured, not only the word that says nothing was: %r"
          % (payload,),
          found is True
          and "outcomeBasis" in payload["steps"][0]
          and payload["steps"][0]["outcomeBasis"] == "no test files found"
          and payload["steps"][0].get("derivedGap") is True)
    lines = M._render_human("run", "R-4", found, payload)
    check("rl9 `audit-lookup run <runId>` NAMES why the step could not run, "
          "in its human rendering, and marks a derived-run gap as such rather "
          "than leaving a reader to guess from the bare outcome word: %r"
          % (lines,),
          any("no test files found" in line for line in lines)
          and any("derived" in line.lower() for line in lines))

    found, payload = M.run_lookup([r1], "R-1")
    lines_r1 = M._render_human("run", "R-1", found, payload)
    check("rl10 THE ALLOW CASE: a PASSED step's rendered lines read exactly "
          "as they did before either key existed - no `outcomeBasis`/"
          "`derivedGap` line appears for a step that carries neither: %r"
          % (lines_r1,),
          lines_r1 == ["run R-1 (task P1.1): passed",
                      "  lint: exit=0 durationMs=120",
                      "pointer: evidence ledger row for runId 'R-1'"])

    # --- CLI: main(), a real manifest on disk, --json and the exit code ----
    tmp = _harness.fixture_root("audit-lookup-")
    try:
        os.makedirs(os.path.join(tmp, "docs", "audit"))
        mpath = os.path.join(tmp, "docs", "audit", "audit-plan.json")
        with open(mpath, "w", encoding="utf-8") as fh:
            json.dump(man, fh)
        _journal_io.append(tmp, {"action": "task.cancel", "actor": "probe",
                                 "ts": "2026-01-02T00:00:00Z",
                                 "details": {"taskId": "P1.2", "phaseId": "P1",
                                            "reason": "superseded by P1.3"}})

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = M.main([mpath, "cancel", "P1.2", "--json"])
        payload = json.loads(out.getvalue())
        check("al12 the CLI answers a real manifest+journal pair and exits 0 "
              "on a match, with the journal cross-check attached: %r"
              % (payload,),
              rc == M.E_OK and payload["found"] is True
              and payload["answer"]["journal"]["reason"]
              == "superseded by P1.3")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = M.main([mpath, "file", "src/nope.py"])
        check("al13 a CLI miss exits non-zero rather than zero-with-a-message "
              "- a caller scripting this cannot mistake a miss for a match: "
              "%r" % (rc,),
              rc == M.E_NOMATCH and "no match" in out.getvalue())

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = M.main([mpath, "brief", "P1.1", "--json"])
        payload = json.loads(out.getvalue())
        check("al18 the CLI answers `brief` for a real manifest on disk and "
              "exits 0 on a match: %r" % (payload,),
              rc == M.E_OK and payload["found"] is True
              and payload["answer"]["files"][0]["last"] == "P1.2")

        # --- CLI: run, through a real evidence ledger on disk -----------------
        # `mpath` already sits at the DEFAULT `docs/audit/audit-plan.json`
        # location, so the ledger's own default resolution finds it with no
        # config override - the same path `project_config_for` would compute.
        _evio.append_row(tmp, dict(r1))
        _evio.append_row(tmp, dict(r2))

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = M.main([mpath, "run", "R-2", "--json"])
        payload = json.loads(out.getvalue())
        check("al20 the CLI answers `run` for a real evidence ledger on disk, "
              "read through the same `--project` resolution `cancel` already "
              "uses: %r" % (payload,),
              rc == M.E_OK and payload["found"] is True
              and payload["answer"]["runId"] == "R-2"
              and payload["answer"]["verdictSource"] == "reused")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = M.main([mpath, "run", "latest", "--task", "P1.1", "--json"])
        payload = json.loads(out.getvalue())
        check("al21 the CLI wires `latest` --task through to the newest "
              "recorded run for that task: %r" % (payload,),
              rc == M.E_OK and payload["found"] is True
              and payload["answer"]["runId"] == "R-2")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = M.main([mpath, "run", "latest"])
        check("al22 `run latest` with NEITHER --phase nor --task is a usage "
              "error (exit 2), not a miss (exit 1) - the caller asked an "
              "ambiguous question, not one this ledger could answer 'no' to: "
              "%r" % (rc,),
              rc == M.E_USAGE)

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = M.main([mpath, "run", "latest", "--phase", "P1", "--task",
                        "P1.1"])
        check("al23 SECOND DIRECTION: `run latest` with BOTH --phase and "
              "--task is the same usage error, not a silent pick of one: %r"
              % (rc,), rc == M.E_USAGE)

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = M.main([mpath, "run", "R-9"])
        check("al24 an unknown runId through the real CLI exits non-zero "
              "with the miss sentence, exactly as `bug`/`file`/`brief` do "
              "for their own unknowns: %r" % (rc,),
              rc == M.E_NOMATCH and "no" in out.getvalue().lower())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_audit_lookup.py --selftest\n")
    raise SystemExit(2)
