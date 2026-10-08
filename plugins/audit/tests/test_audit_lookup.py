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
import subprocess
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                      # noqa: E402
import _output                                      # noqa: E402  (CLIPPED_MARK, the cut a payload must never carry)
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

    # A PASSED run can carry a step that exited 1 with failing lines: the
    # failure a mute quarantined. The lookup says which mute, or the row reads
    # as a contradiction.
    r_muted = {"v": 1, "runId": "R-M", "ts": "2026-06-04T10:00:00Z",
               "scope": "task", "taskId": "P1.2", "status": "passed",
               "failed": [],
               "steps": [{"name": "unit", "exit": 1, "durationMs": 40,
                          "failing": ["cart > rejects a negative quantity"],
                          "failingSuites": ["src/cart.test.ts"],
                          "muted": [{"test": "src/cart.test.ts",
                                     "bugId": "B1", "until": "2026-10-01"}]}],
               "muted": [{"test": "src/cart.test.ts", "bugId": "B1",
                          "until": "2026-10-01"}]}
    found_m, payload_m = M.run_lookup([r_muted], "R-M")
    muted_lines = M._render_human("run", "R-M", found_m, payload_m)
    check("rl1m a MUTED step is explained: the run lookup prints "
          "`muted: <test> (bug <id>, until <date>)` under the step, so a "
          "passed run showing exit=1 and failing lines is not a "
          "contradiction: %r" % (muted_lines,),
          found_m is True
          and "    muted: src/cart.test.ts (bug B1, until 2026-10-01)"
          in muted_lines)
    check("rl1n ALLOW: a step no mute excused prints no `muted:` line: %r"
          % (M._render_human("run", "R-2", True,
                             M.run_lookup(run_rows, "R-2")[1]),),
          not any("muted:" in ln for ln in M._render_human(
              "run", "R-2", True, M.run_lookup(run_rows, "R-2")[1])))

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

        # --- CLI: brief also carries `executor.runsGate`, resolved ----------
        # A project of its own beside the manifest, so a config written here
        # never reaches the `run` cases below, which resolve `tmp` as theirs.
        proj = os.path.join(tmp, "proj")
        cfg_dir = os.path.join(proj, ".claude")
        os.makedirs(cfg_dir)
        cfg_path = os.path.join(cfg_dir, "audit.config.json")

        def _write_cfg(text):
            with open(cfg_path, "w", encoding="utf-8") as fh:
                fh.write(text)

        def _brief(*extra):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = M.main([mpath, "brief", "P1.1", "--project", proj]
                            + list(extra))
            return rc, out.getvalue(), err.getvalue()

        _write_cfg(json.dumps({"executor": {"runsGate": "full"}}))
        rc, text, _err = _brief()
        check("rg1 a config setting executor.runsGate to `full` puts that "
              "reading in brief's text, with the key and the file as its "
              "basis, beside the file answers it already printed: %r" % (text,),
              rc == M.E_OK
              and "executor.runsGate: full" in text
              and "set by executor.runsGate in .claude/audit.config.json" in text
              and "default" not in text
              and "last declared by P1.2" in text)
        rc, text, _err = _brief("--json")
        gate = json.loads(text)["answer"].get("runsGate") if rc == M.E_OK else None
        check("rg2 the same reading in --json: `runsGate` carries the word, "
              "default false, and the key as its basis: %r" % (gate,),
              gate is not None and gate.get("reading") == "full"
              and gate.get("default") is False
              and "executor.runsGate" in (gate.get("basis") or ""))

        os.remove(cfg_path)
        rc, text, _err = _brief()
        rc_j, text_j, _err = _brief("--json")
        gate = json.loads(text_j)["answer"].get("runsGate") if rc_j == M.E_OK else None
        check("rg3 with NO config file, brief prints own-tests and says it is "
              "the default because the file is absent - in text and in "
              "--json: %r / %r" % (text, gate),
              rc == M.E_OK
              and "executor.runsGate: own-tests (the default" in text
              and "no .claude/audit.config.json" in text
              and gate is not None and gate.get("reading") == "own-tests"
              and gate.get("default") is True)

        _write_cfg(json.dumps({"executor": {"maxHours": 2}}))
        rc, text, _err = _brief()
        check("rg4 a config file WITHOUT the key reads the same default, and "
              "the basis says the key is what is absent, not the file: %r"
              % (text,),
              rc == M.E_OK
              and "executor.runsGate: own-tests (the default" in text
              and "not set in .claude/audit.config.json" in text)

        # The allow twin of rg5: own-tests WRITTEN in the file is a setting,
        # not the default - catches a refusal or a basis that keys on the
        # word rather than on whether the key was present.
        _write_cfg(json.dumps({"executor": {"runsGate": "own-tests"}}))
        rc, text, _err = _brief()
        check("rg6 own-tests set explicitly is reported as SET, not as the "
              "default it happens to equal: %r" % (text,),
              rc == M.E_OK
              and "executor.runsGate: own-tests (set by executor.runsGate" in text
              and "default" not in text)

        _write_cfg(json.dumps({"executor": {"runsGate": "fast"}}))
        rc, text, err = _brief()
        rc_j, text_j, err_j = _brief("--json")
        check("rg5 an unrecognised value is a refusal: non-zero exit, the "
              "value named, and NO reading printed - never the default it "
              "might have been folded into - in text and in --json: "
              "%r %r %r / %r %r %r" % (rc, text, err, rc_j, text_j, err_j),
              rc not in (M.E_OK, M.E_NOMATCH) and rc_j == rc
              and "'fast'" in err and "'fast'" in err_j
              and text == "" and text_j == ""
              and "own-tests" not in err.split("one of")[0])

        _write_cfg("{not json")
        rc, text, err = _brief()
        check("rg7 a config file that does not parse is refused too, with "
              "the parse error named - the reading cannot be known, so "
              "printing the default would be a guess: %r %r %r"
              % (rc, text, err),
              rc not in (M.E_OK, M.E_NOMATCH) and text == ""
              and "audit.config.json" in err)
        os.remove(cfg_path)

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


def _cli(argv, cwd):
    """`(exit, stdout)` of this command run as the main loop runs it: a process."""
    import subprocess
    env = dict((k, v) for k, v in os.environ.items()
               if not k.startswith("CLAUDE") and k != "AUDIT_LOCK_TOKENS")
    done = subprocess.run(
        [sys.executable, _loader.script_path("audit-lookup.py")] + argv,
        cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True, encoding="utf-8")
    return done.returncode, done.stdout


def _in_process(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = M.main(argv)
    return code, out.getvalue()


def _success_line_cases(check):
    """A lookup's answer is a payload, printed whole, `--verbose` or not; a
    miss, in full, as it always was."""
    tmp = _harness.fixture_root("audit-lookup-sl-")
    mpath = os.path.join(tmp, "audit-plan.json")
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(_manifest(), fh)
    code, answer = _cli([mpath, "file", "src/a.py"], tmp)
    check("sl1 a `file` answer prints whole - the answer line AND its pointer, "
          "byte for byte what `main` prints - never folded into a success "
          "line: %r" % (answer,),
          code == M.E_OK
          and answer == _in_process([mpath, "file", "src/a.py"])[1]
          and len(answer.splitlines()) == 2
          and answer.splitlines()[1].startswith("pointer: "))
    vcode, verbose = _cli([mpath, "brief", "P1.1", "--verbose"], tmp)
    check("sl2 `--verbose` is accepted and prints the answer `main` prints, "
          "byte for byte: %r" % (verbose,),
          vcode == M.E_OK
          and verbose == _in_process([mpath, "brief", "P1.1"])[1]
          and len(verbose.splitlines()) > 1)
    bcode, brief = _cli([mpath, "brief", "P1.1"], tmp)
    check("sl3 a `brief` longer than the byte bound - the answer folded into an "
          "executor's spawn prompt - prints byte-identical to `--verbose`: "
          "nothing cut, `executor.runsGate` included: %r" % (brief,),
          bcode == M.E_OK and brief == verbose
          and len(brief.encode("utf-8")) > 200
          and "executor.runsGate: " in brief
          and _output.CLIPPED_MARK not in brief)
    miss = _cli([mpath, "file", "src/nope.py", "--verbose"], tmp)
    check("sl4 a miss prints as it always did, `--verbose` or not: %r"
          % (miss,),
          miss[0] == M.E_NOMATCH
          and miss == _cli([mpath, "file", "src/nope.py"], tmp)
          and miss[1] == _in_process([mpath, "file", "src/nope.py"])[1])


_BF_START = "2026-01-01T00:00:00Z"
_BF_REQUEST = "Make refunds add up exactly.\n  Keep the remainder rule as it is.\n"
_BF_EXEC = ('{"gates": {}, "outcome": {"technical": "t", "descriptive": "d"},\n'
            ' "testsAdded": ["bf_case"], "stamp": "audit-stamp: v2 x",\n'
            ' "redFirst": {"status": "proved", "basis": "exit 1", "at": "z"}}\n')


def _bf_manifest(attempts=1, request=_BF_REQUEST):
    phase = {"id": "P1", "title": "Refunds", "status": "in_progress",
             "desiredOutcome": "refunds add up to the order total",
             "testGate": ["test"],
             "tasks": [{"id": "P1.1", "title": "split", "status": "in_progress",
                        "description": "Split a refund across lines,\n"
                                       "  remainder to the last line.",
                        "files": ["src/refund.py", "tests/test_refund.py"],
                        "docs": ["docs/refunds.md"],
                        "skills": ["writing-python"],
                        "tests": {"mode": "tdd", "expectRedFirst": True,
                                  "add": ["tests/test_refund.py: sums exactly"],
                                  "gate": ["test", "unit:api",
                                           "python3 tests/test_refund.py"]},
                        "startedAt": _BF_START, "attempts": attempts,
                        "maxAttempts": 3}]}
    if request is not None:
        phase["request"] = request
    return {"meta": {"version": 2,
                     "buildCommands": {"test": "python3 -m pytest tests"}},
            "phases": [phase],
            "fileIndex": {"src/refund.py": ["P1.1"],
                          "tests/test_refund.py": ["P1.1"]},
            "bugs": []}


def _bf_signed_phase():
    """A phase of three closed tasks, each with its own commit, files and gate."""
    man = _bf_manifest()
    tasks = []
    for n, sha in ((1, "a" * 40), (2, "b" * 40), (3, "c" * 40)):
        tasks.append({"id": "P1.%d" % n, "title": "t%d" % n, "status": "done",
                      "description": "task %d asked this" % n,
                      "files": ["src/m%d.py" % n],
                      "tests": {"mode": "gate-only", "add": [],
                                "expectRedFirst": False,
                                "gate": ["test", "unit:api"] if n == 2
                                else ["python3 tests/t%d.py" % n]},
                      "commit": sha, "startedAt": _BF_START, "attempts": 1,
                      "maxAttempts": 3,
                      "testEvidence": {"runId": "run-%d" % n,
                                       "status": "passed", "at": "z"}})
    man["phases"][0]["tasks"] = tasks
    return man


def _brief_cases(check):
    """`brief --role` writes the whole brief to a file the agent is handed by
    path; the reviewer's waits for the executor's filed return; the phase
    reviewer's carries the request and every task's own record."""
    root = _harness.fixture_root("audit-lookup-bf-")
    # Read with a default so a module without them fails its cases rather
    # than raising out of the block before any case ran.
    refused = getattr(M, "E_REFUSED", "no E_REFUSED")

    def project(name, manifest):
        proj = os.path.join(root, name)
        os.makedirs(os.path.join(proj, ".claude"))
        with open(os.path.join(proj, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"manifestPath": "docs/audit/audit-plan.json"}, fh)
        mpath = os.path.join(proj, "docs", "audit", "audit-plan.json")
        os.makedirs(os.path.dirname(mpath))
        with open(mpath, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh)
        return proj, mpath

    def brief(proj, mpath, node_id, role):
        out, err = io.StringIO(), io.StringIO()
        # argparse answers an unknown flag with SystemExit; caught, so a parser
        # that does not know `--role` is a failed case and not an aborted run.
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = M.main([mpath, "brief", node_id, "--role", role,
                               "--project", proj])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue() + err.getvalue()

    def brief_file(proj, node_id, name):
        return os.path.join(proj, ".claude", "state", "briefs", node_id, name)

    def read(path):
        try:
            with open(path, "r", encoding="utf-8", newline="") as fh:
                return fh.read()
        except OSError:
            return None

    def file_exec(proj, start="20260101T000000Z", text=_BF_EXEC):
        path = os.path.join(proj, "docs", "audit", "evidence", "returns",
                            "P1.1", "%s.executor.json" % start)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)

    # ---- the executor's brief ---------------------------------------------
    proj, mpath = project("bf-exec", _bf_manifest())
    code, said = brief(proj, mpath, "P1.1", "executor")
    path = brief_file(proj, "P1.1", "20260101T000000Z.executor.md")
    text = read(path) or ""
    task = _bf_manifest()["phases"][0]["tasks"][0]
    check("bf1 `brief --role executor` writes the WHOLE brief to a file and "
          "says where in one line: the description verbatim, every declared "
          "file with who last declared it, the docs, the desired outcome, the "
          "skill, the runsGate reading and the resolved commands, the filing "
          "command among them: %r" % ((code, said),),
          code == M.E_OK and len(said.splitlines()) == 1 and path in said
          and task["description"] in text
          and all(f in text for f in task["files"])
          and "docs/refunds.md" in text
          and "refunds add up to the order total" in text
          and "writing-python" in text
          and "executor.runsGate: own-tests" in text
          and "submit P1.1 --role executor" in text
          and "--own --quiet" in text)
    _bf_bare = [ln.strip() for ln in text.splitlines()
                if "file-return" in ln or "stamp-verification.py" in ln]
    check("bf14 the executor's filing line is ONE call, the driver's `submit`, "
          "with this tdd task's test command after `--` - the gate entry naming "
          "its tests.add file - and the brief names no bare file-return, take or "
          "red step for the agent to run by hand: %r" % (_bf_bare,),
          "drive-phase.py\" submit P1.1 --role executor" in text
          and "-- python3 tests/test_refund.py" in text
          and _bf_bare == [])
    check("bf2 a first attempt's brief carries no retry section: %r"
          % (text[-200:],), "Retry" not in text)
    retry = _bf_manifest(attempts=2)
    retry["phases"][0]["tasks"][0]["outcome"] = {
        "technical": "attempt 1: gate red on bf_case"}
    retry["phases"][0]["tasks"][0]["testEvidence"] = {
        "runId": "run-red", "status": "failed", "at": "z"}
    proj2, mpath2 = project("bf-retry", retry)
    brief(proj2, mpath2, "P1.1", "executor")
    text2 = read(brief_file(proj2, "P1.1",
                            "20260101T000000Z.executor.md")) or ""
    check("bf3 SECOND DIRECTION: a retry's brief carries what the last attempt "
          "proved - its outcome.technical verbatim and its recorded run - which "
          "the main loop used to be trusted to paste: %r" % (text2[-300:],),
          "Retry" in text2 and "attempt 1: gate red on bf_case" in text2
          and "run-red" in text2)

    # ---- the reviewer's brief waits for the executor's filed return --------
    proj, mpath = project("bf-review", _bf_manifest())
    rpath = brief_file(proj, "P1.1", "20260101T000000Z.reviewer.md")
    code1, said1 = brief(proj, mpath, "P1.1", "reviewer")
    file_exec(proj, start="20251231T000000Z")
    code2, _said2 = brief(proj, mpath, "P1.1", "reviewer")
    check("bf4 the reviewer's brief is REFUSED, writing no brief, while the "
          "executor's return for the task's CURRENT start is unfiled - and one "
          "filed under an earlier start does not count: %r"
          % ((code1, said1[:160], code2),),
          code1 == refused and code2 == refused
          and "executor" in said1 and "submit P1.1 --role executor" in said1
          and not os.path.exists(rpath))
    file_exec(proj)
    code3, said3 = brief(proj, mpath, "P1.1", "reviewer")
    rtext = read(rpath) or ""
    check("bf5 ALLOW: once that return is filed the brief is written and "
          "carries it byte-identical, beside the description verbatim, the "
          "gate commands resolved through meta.buildCommands and the "
          "reviewer's own filing command: %r" % ((code3, said3),),
          code3 == M.E_OK and _BF_EXEC in rtext
          and task["description"] in rtext
          and "python3 -m pytest tests" in rtext
          and "submit P1.1 --role reviewer" in rtext and "file-return" not in rtext
          and "mode: task" in rtext)

    # ---- the phase reviewer's brief ----------------------------------------
    proj, mpath = project("bf-phase", _bf_signed_phase())
    code4, said4 = brief(proj, mpath, "P1", "phase")
    ptext = read(brief_file(proj, "P1", "phase.md")) or ""
    signed = _bf_signed_phase()["phases"][0]["tasks"]
    check("bf6 the phase reviewer's brief holds the saved request "
          "byte-identical and, for each of three tasks, its SHA, its files and "
          "every tests.gate entry byte-identical to the plan's, with its "
          "recorded run: %r" % ((code4, said4),),
          code4 == M.E_OK and _BF_REQUEST in ptext
          and all(t["commit"] in ptext and t["files"][0] in ptext
                  and t["testEvidence"]["runId"] in ptext
                  and all(g in ptext for g in t["tests"]["gate"])
                  for t in signed)
          and "where does a task choose something the request leaves open"
          in ptext.lower())
    check("bf7 a `key:project` gate entry the plan cannot resolve is printed "
          "with the entry kept and said to be unresolved, never dropped: %r"
          % ([ln for ln in ptext.splitlines() if "unit:api" in ln],),
          any("unit:api" in ln and "unresolved" in ln
              for ln in ptext.splitlines()))
    bare = _bf_signed_phase()
    del bare["phases"][0]["request"]
    proj2, mpath2 = project("bf-phase-bare", bare)
    brief(proj2, mpath2, "P1", "phase")
    ptext2 = read(brief_file(proj2, "P1", "phase.md")) or ""
    check("bf8 a phase with no saved request SAYS so rather than leaving the "
          "field empty: %r" % ([ln for ln in ptext2.splitlines()
                                if "request" in ln.lower()][:3],),
          "no request was saved" in ptext2.lower()
          and _BF_REQUEST not in ptext2)
    open_phase = _bf_signed_phase()
    open_phase["phases"][0]["tasks"][1].update(status="in_progress", commit=None)
    proj3, mpath3 = project("bf-phase-open", open_phase)
    code5, said5 = brief(proj3, mpath3, "P1", "phase")
    check("bf9 a phase brief over a task with no commit yet is refused and "
          "writes nothing - the binding would have no diff: %r"
          % ((code5, said5[:160]),),
          code5 == refused and "P1.2" in said5
          and not os.path.exists(brief_file(proj3, "P1", "phase.md")))

    # ---- the phase brief under `review.perTask` ------------------------------
    choices = _bf_signed_phase()
    choices["phases"][0]["openChoices"] = ["round half-even or half-up",
                                           "  refund shipping too?"]
    proj4, mpath4 = project("bf-phase-choices", choices)
    brief(proj4, mpath4, "P1", "phase")
    ptext4 = read(brief_file(proj4, "P1", "phase.md")) or ""
    none_left = _bf_signed_phase()
    none_left["phases"][0]["openChoices"] = []
    proj5, mpath5 = project("bf-phase-nochoices", none_left)
    brief(proj5, mpath5, "P1", "phase")
    ptext5 = read(brief_file(proj5, "P1", "phase.md")) or ""
    check("bf12 the phase brief prints each of `phase.openChoices` verbatim "
          "beside the request, says an empty list is the planner's answer that "
          "none was left, and says an absent one was never asked: %r"
          % ([ln for ln in ptext4.splitlines() if "refund" in ln.lower()][:4],),
          "- round half-even or half-up" in ptext4
          and "-   refund shipping too?" in ptext4
          and "left no choice open" in ptext5
          and "phase.openChoices is absent" in ptext)

    keyed = _bf_signed_phase()
    keyed["phases"][0]["tasks"][2]["reviewPerTask"] = "always"
    proj6, mpath6 = project("bf-phase-owed", keyed)
    for argv in (["init", "-q"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"], ["add", "-A"],
                 ["commit", "-qm", "fixture"]):
        subprocess.run(["git", "-C", proj6] + argv, capture_output=True,
                       timeout=60)
    head = subprocess.run(["git", "-C", proj6, "rev-parse", "HEAD"],
                          capture_output=True, timeout=60).stdout.decode().strip()
    answered = os.path.join(proj6, "docs", "audit", "evidence", "returns", "P1",
                            "%s.reviewer.json" % ("d" * 40,))
    os.makedirs(os.path.dirname(answered))
    with open(answered, "w", encoding="utf-8") as fh:
        json.dump({"findings": [], "intent": {"answer": "matches"},
                   "verdict": "clean",
                   "tasks": [{"id": "P1.2", "commit": "b" * 40,
                              "answer": "matches"}]}, fh)
    code7, said7 = brief(proj6, mpath6, "P1", "phase")
    ptext6 = read(brief_file(proj6, "P1", "phase.md")) or ""
    owed = [ln for ln in ptext6.splitlines() if ln.startswith("owed:")]
    check("bf13 under the shipped `review.perTask: phase` the phase brief names "
          "the head it was computed at, lists exactly the tasks owed their "
          "three answers - not the one a filed return already answers at its "
          "commit, not the one whose key reads `always` - asks the three "
          "questions, and names the filing command keyed on that head: %r"
          % ((code7, owed, head),),
          code7 == M.E_OK and len(head) == 40 and ("head: %s" % (head,)) in ptext6
          and owed == ["owed: P1.1"]
          and "submit P1 --role reviewer" in ptext6
          and "--head %s" % (head,) in ptext6 and "file-return" not in ptext6
          and "inherited" in ptext6.lower() and "red-first" in ptext6.lower()
          and "answered by returns/P1/" in ptext6)

    unowed = _bf_signed_phase()
    for task in unowed["phases"][0]["tasks"]:
        task["reviewPerTask"] = "always"
    proj7, mpath7 = project("bf-phase-unowed", unowed)
    for argv in (["init", "-q"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"], ["add", "-A"],
                 ["commit", "-qm", "fixture"]):
        subprocess.run(["git", "-C", proj7] + argv, capture_output=True,
                       timeout=60)
    head7 = subprocess.run(["git", "-C", proj7, "rev-parse", "HEAD"],
                           capture_output=True, timeout=60).stdout.decode().strip()
    code8, _said8 = brief(proj7, mpath7, "P1", "phase")
    ptext7 = read(brief_file(proj7, "P1", "phase.md")) or ""
    check("bf20 a phase brief owing no task its answers still names the filing "
          "command keyed on its head, with an empty `tasks` list - the step "
          "driver reads the review from the filed return, never from a final "
          "message: %r" % ([ln for ln in ptext7.splitlines()
                            if "submit" in ln or "tasks" in ln][:4],),
          code8 == M.E_OK and len(head7) == 40
          and "submit P1 --role reviewer" in ptext7
          and "--head %s" % (head7,) in ptext7
          and "`\"tasks\": []`" in ptext7
          and not [ln for ln in ptext7.splitlines() if ln.startswith("owed:")])

    # WHERE THE RETURN GOES. The reviewer has no Write tool and the plan gate
    # refuses an executor's write outside its task files, so a brief saying
    # "write it to a file" with no location costs a refused guess per agent.
    # The return travels on the submit's stdin as a quoted heredoc instead:
    # nothing is written, and a quoted delimiter keeps `$` and backticks in the
    # JSON as typed. Its closing line must start the line, or the shell never
    # ends the heredoc - which an indented code block would do to it.
    def heredoc_shape(text):
        lines = text.splitlines()
        opens = [i for i, ln in enumerate(lines)
                 if ln.rstrip().endswith("<<'AUDIT_RETURN'")]
        closes = [i for i, ln in enumerate(lines) if ln == "AUDIT_RETURN"]
        return {"opens": len(opens), "closes": len(closes),
                "ordered": bool(opens and closes and closes[0] > opens[0]),
                "submitOpens": bool(opens and "submit" in lines[opens[0]]),
                "toAFile": "to a file" in text or "return file" in text}
    _bf_shapes = dict((name, heredoc_shape(t)) for name, t in (
        ("executor", text), ("reviewer", rtext), ("phase-owed", ptext6),
        ("phase-unowed", ptext7)))
    check("bf21 every brief that files a return - the executor's, the task "
          "reviewer's and the phase reviewer's, owing answers or not - hands it "
          "on the submit's stdin as ONE quoted heredoc whose closing line "
          "starts its line, and none says to write a file, which the reviewer "
          "cannot and the plan gate refuses the executor: %r" % (_bf_shapes,),
          all(s == {"opens": 1, "closes": 1, "ordered": True,
                    "submitOpens": True, "toAFile": False}
              for s in _bf_shapes.values()))

    # A GREEN RUN THAT DID NOT MEASURE THE WORK. The gate exits 0 and still
    # prints NO OVERLAP or TREE CHANGED; the row keeps what those banners rest
    # on (`observations.coverage` empty, `observations.treeMutated` non-empty),
    # and the phase reviewer reads the task's recorded run from this brief.
    projb, mpathb = project("bf-phase-banner", _bf_signed_phase())
    ledger = os.path.join(projb, "docs", "audit", "evidence",
                          "2026-10.fixture.jsonl")
    os.makedirs(os.path.dirname(ledger), exist_ok=True)

    def _row(run_id, subject, coverage, mutated):
        return json.dumps({"v": 1, "runId": run_id, "ts": "2026-10-01T00:00:00Z",
                           "scope": "task", "taskId": subject, "status": "passed",
                           "failed": [], "steps": [],
                           "observations": {"ranTotal": 3, "coverage": coverage,
                                            "treeMutated": mutated}})
    with open(ledger, "w", encoding="utf-8", newline="") as fh:
        fh.write("\n".join([_row("run-1", "P1.1", [], []),
                            _row("run-2", "P1.2", ["src/m2.py"],
                                 ["src/elsewhere.py"]),
                            _row("run-3", "P1.3", ["src/m3.py"], [])]) + "\n")
    brief(projb, mpathb, "P1", "phase")
    btext = read(brief_file(projb, "P1", "phase.md")) or ""
    runs = dict((ln.split("runId ", 1)[1].split(",", 1)[0], ln)
                for ln in btext.splitlines()
                if ln.startswith("recorded run: runId "))
    check("bf22 a task whose recorded run printed NO OVERLAP or TREE CHANGED "
          "carries that banner beside the run in the phase brief, so the "
          "reviewer sees the gate did not measure the work - and a run that "
          "named the task's own file with the tree untouched carries neither "
          "(the over-fire twin): %r" % (runs,),
          "NO OVERLAP" in runs.get("run-1", "")
          and "TREE CHANGED" not in runs.get("run-1", "")
          and "TREE CHANGED" in runs.get("run-2", "")
          and "src/elsewhere.py" in runs.get("run-2", "")
          and "NO OVERLAP" not in runs.get("run-2", "")
          and runs.get("run-3", "") != ""
          and "NO OVERLAP" not in runs["run-3"]
          and "TREE CHANGED" not in runs["run-3"])
    no_row = [ln for ln in ptext.splitlines()
              if ln.startswith("recorded run: runId ")]
    check("bf23 a recorded run whose ledger row is not there says so - whether "
          "the gate printed a banner is then unknown, never read as none: %r"
          % (no_row,),
          no_row != [] and all("not found" in ln for ln in no_row))

    code6, said6 = brief(proj, mpath, "P1", "executor")
    check("bf11 a phase id asked for a task's role, or a task id for the "
          "phase's, is a miss rather than a brief about the wrong thing: %r"
          % ((code6, said6[:120]),),
          code6 == M.E_NOMATCH
          and brief(proj, mpath, "P1.1", "phase")[0] == M.E_NOMATCH)


def _selftest():
    def body(check):
        # Each block staged, so one that raises still lets the other run.
        _harness.stage(check, "al-block", _cases)
        _harness.stage(check, "sl-block", _success_line_cases)
        _harness.stage(check, "bf-block", _brief_cases)
    return _harness.run(body)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_audit_lookup.py --selftest\n")
    raise SystemExit(2)
