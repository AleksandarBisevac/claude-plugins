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
import _manifest_phases                             # noqa: E402  (own_gate_entries, swapped in bf31)
import _gate_feed                                   # noqa: E402  (review_asks: the sentence the brief must carry)
import _clause_coverage as _cc                      # noqa: E402  (the one numbering the drive reads a writer's answer against)

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
                     "buildCommands": {"test": "python3 -m pytest"}},
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
    said_lines = said.splitlines()
    check("bf1 `brief --role executor` writes the WHOLE brief to a file and "
          "says where in one line - a byte count may follow on stderr, which "
          "`drive-phase.py` never reads, but the stdout line `written: (.+)$` "
          "parses stays the path alone: the description verbatim, every "
          "declared file with who last declared it, the docs, the desired "
          "outcome, the skill, the runsGate reading and the resolved "
          "commands, the filing command among them: %r" % ((code, said),),
          code == M.E_OK and len(said_lines) <= 2 and path in said_lines[0]
          and said_lines[0].rstrip().endswith(path)
          and task["description"] in text
          and all(f in text for f in task["files"])
          and "docs/refunds.md" in text
          and "refunds add up to the order total" in text
          and "writing-python" in text
          and "executor.runsGate: own-tests" in text
          and "submit P1.1 --role executor" in text
          and "--own --quiet" in text)

    # The brief's sentence is read off what `case_binding_gaps` accepts: the
    # binding it asks for is shown to draw no gap, an entry left unbound is
    # shown to draw one, and only then is the brief asked to name that binding.
    import _filed_returns as _fr
    bound_clean = _fr.case_binding_gaps(task, ["bf1"], ["bf1 any title at all"]) == []
    unbound_gap = len(_fr.case_binding_gaps(task, None, None)) == 1
    unprinted_gap = len(_fr.case_binding_gaps(task, ["bf2"], ["bf1 x"])) == 1
    rule_lines = [ln for ln in text.splitlines() if _fr.CASES_FIELD in ln]
    none_task = _bf_manifest()
    none_task["phases"][0]["tasks"][0]["tests"]["add"] = []
    proj_n, mpath_n = project("bf-exec-none", none_task)
    brief(proj_n, mpath_n, "P1.1", "executor")
    text_none = read(brief_file(proj_n, "P1.1", "20260101T000000Z.executor.md")) or ""
    check("tests/test_audit_lookup.py: an executor brief for a task "
          "with tests.add states, beside the list, that each entry is bound by "
          "returning `casesAdded`, and a brief for a task with no tests.add "
          "does not",
          len(rule_lines) == 1 and "by index" in rule_lines[0]
          and text.index("tests.add:") < text.index(rule_lines[0])
          and _fr.CASES_FIELD not in text_none and "tests.add:" in text_none)
    check("tests/test_audit_lookup.py: the sentence the brief prints "
          "names the binding case_binding_gaps grades (an id per entry, checked "
          "against what the suite printed) and no title or addMap route - read off "
          "the function's behaviour, not a second copy of the wording",
          bound_clean and unbound_gap and unprinted_gap
          and "printed" in text[text.index(rule_lines[0]):][:600]
          and "tests.addMap" not in text and "verbatim" not in rule_lines[0])

    def brief_streams(proj, mpath, node_id, role):
        """stdout and stderr kept APART - `drive-phase.py`'s
        `re.search(r"written: (.+)$", out.strip())` reads only the verb's
        stdout, so a regression here would feed it a byte count instead of a
        path and read as no brief at all."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = M.main([mpath, "brief", node_id, "--role", role,
                               "--project", proj])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    code1a, stdout1a, stderr1a = brief_streams(proj, mpath, "P1.1", "executor")
    check("bf1a RED TWIN: the size this brief's write prints goes to stderr, "
          "never appended to stdout's `written: <path>` line - the shape "
          "`drive-phase.py`'s `written: (.+)$` parses to find the brief file, "
          "so a size on that same line would hand it a path that is not one: "
          "%r" % ((code1a, stdout1a, stderr1a),),
          code1a == M.E_OK
          and stdout1a == ("brief for P1.1 (executor) written: %s\n" % (path,))
          and ("%s is " % (path,)) in stderr1a and "bytes" in stderr1a)
    _bf_bare = [ln.strip() for ln in text.splitlines()
                if "file-return" in ln or "stamp-verification.py" in ln]
    check("bf14 the executor's filing line is ONE call, the driver's `submit`, "
          "with this tdd task's test command after `--` - the gate entry naming "
          "its tests.add file - and the brief names no bare file-return, take or "
          "red step for the agent to run by hand: %r" % (_bf_bare,),
          "drive-phase.py\" submit P1.1 --role executor" in text
          and "-- python3 tests/test_refund.py" in text
          and _bf_bare == [])
    # WHICH COMMAND "WHAT YOU RUN" PRINTS UNDER own-tests. `run-test-gate.py
    # --own` keeps only a TASK's own gate entries pointed at nothing but its
    # tests.add paths; with none it answers "nothing of its own to run" and
    # exits non-zero, so printing it there hands the executor a dead request.
    def run_section(brief_text):
        lines = brief_text.splitlines()
        if "## What you run" not in lines:
            return []
        start = lines.index("## What you run") + 1
        end = next((i for i in range(start, len(lines))
                    if lines[i].startswith("## ")), len(lines))
        return lines[start:end]

    def suite_lines(section):
        return [ln for ln in section if "python3 tests/test_refund.py" in ln]

    own_run = run_section(text)
    check("bf28 a brief whose OWN gate selects its tests.add file prints the "
          "own-tests command once, and no suite-command fallback beside it - "
          "the case that goes red if the fallback fires always: %r" % (own_run,),
          sum(ln.count("--own --quiet") for ln in own_run) == 1
          and suite_lines(own_run) == [])

    borrowed = _bf_manifest()
    del borrowed["phases"][0]["tasks"][0]["tests"]["gate"]
    borrowed["phases"][0]["testGate"] = ["python3 tests/test_refund.py"]
    projg, mpathg = project("bf-exec-phase-gate", borrowed)
    brief(projg, mpathg, "P1.1", "executor")
    borrowed_run = run_section(read(brief_file(
        projg, "P1.1", "20260101T000000Z.executor.md")) or "")
    check("bf29 its twin, measured only by the PHASE's gate - which names the "
          "test file but is nothing of the task's own - prints the suite "
          "command that gate names and no own-tests line: %r" % (borrowed_run,),
          borrowed_run != []
          and not any("--own" in ln for ln in borrowed_run)
          and len(suite_lines(borrowed_run)) == 1)

    unnamed = _bf_manifest()
    unnamed["phases"][0]["tasks"][0]["tests"]["gate"] = ["test"]
    proju, mpathu = project("bf-exec-no-entry", unnamed)
    brief(proju, mpathu, "P1.1", "executor")
    unnamed_run = run_section(read(brief_file(
        proju, "P1.1", "20260101T000000Z.executor.md")) or "")
    check("bf30 a gate naming no tests.add file at all prints no own-tests "
          "line and no invented command - it says no entry names the file: %r"
          % (unnamed_run,),
          unnamed_run != []
          and not any("--own" in ln for ln in unnamed_run)
          and suite_lines(unnamed_run) == []
          and any("tests/test_refund.py" in ln and "no gate entry" in ln
                  for ln in unnamed_run))

    # ONE RULE, TWO CALLERS. The brief and `run-test-gate --own` both ask
    # `_manifest_phases.own_gate_entries`; the rule's own cases live in that
    # module's suite. What is pinned here is the delegation: the shared
    # function is swapped for one that answers the OPPOSITE of the truth on
    # each fixture, and both callers must follow it. A caller holding its own
    # copy of the rule keeps answering the truth and goes red.
    rtg = _loader.load_script("run-test-gate.py", modname="rtg_for_lookup")
    real_own = getattr(_manifest_phases, "own_gate_entries", None)
    _follow = {}
    try:
        for name, man, forced in (
                ("own", _bf_manifest(), []),
                ("unnamed", unnamed, ["python3 tests/test_refund.py"])):
            _manifest_phases.own_gate_entries = (
                lambda _m, _p, _t, forced=forced: list(forced))
            ph = man["phases"][0]
            cmds, _src, _err = rtg.own_gate_of(man, "P1", "P1.1")
            # Read with a default, so a module without it fails this case
            # instead of raising out of the block before the later cases run.
            line = getattr(M, "own_tests_line", lambda *a: "missing")(
                man, ph, ph["tasks"][0], "RUN")
            _follow[name] = (bool(cmds), "--own --quiet" in line)
    finally:
        if real_own is None:
            vars(_manifest_phases).pop("own_gate_entries", None)
        else:
            _manifest_phases.own_gate_entries = real_own
    check("bf31 the brief and run-test-gate's `--own` both answer through "
          "`_manifest_phases.own_gate_entries` - forced to say none where the "
          "task has its own entry, and some where it has none, both follow: %r"
          % (_follow,),
          _follow == {"own": (False, False), "unnamed": (True, True)})

    check("bf2 a first attempt's brief carries no retry section: %r"
          % (text[-200:],), "Retry" not in text)
    retry = _bf_manifest(attempts=2)
    retry["phases"][0]["tasks"][0]["testEvidence"] = {
        "runId": "run-red", "status": "failed", "at": "z"}
    proj2, mpath2 = project("bf-retry", retry)
    # The PRODUCTION shape: `outcome.technical` only ever moves onto the task
    # at `done` (`audit-task.py close_task`), so a retried attempt that never
    # closed leaves nothing there - what the Retry section quotes is the
    # FILED return the retried attempt actually left, at its own (earlier)
    # start.
    file_exec(proj2, start="20251231T000000Z",
             text='{"gates": {}, '
                  '"outcome": {"technical": "attempt 1: gate red on bf_case", '
                  '"descriptive": "d"},\n'
                  ' "testsAdded": ["bf_case"], "stamp": "audit-stamp: v2 x",\n'
                  ' "redFirst": {"status": "could-not-prove", '
                  '"basis": "no command given", "at": "z"}}\n')
    brief(proj2, mpath2, "P1.1", "executor")
    text2 = read(brief_file(proj2, "P1.1",
                            "20260101T000000Z.executor.md")) or ""
    check("bf3 SECOND DIRECTION: a retry's brief carries what the last attempt "
          "proved - its outcome.technical verbatim and its recorded run - which "
          "the main loop used to be trusted to paste: %r" % (text2[-300:],),
          "Retry" in text2 and "attempt 1: gate red on bf_case" in text2
          and "run-red" in text2)

    # ---- a retry names the red step and what it printed ---------------------
    smoke_cmd = "python3 smoke.py"
    smoke_line = "FAIL smoke_test: expected 3 got 4"
    row_result = {"status": "failed", "durationMs": 10, "failed": ["smoke"],
                  "ranTotal": 2, "coverageBasis": None, "treeBasis": "b",
                  "treeMutated": [], "overlap": None,
                  "steps": [{"name": "unit", "exit": 0},
                            {"name": "smoke", "command": smoke_cmd, "exit": 1,
                             "failing": [smoke_line]}]}
    proj3, mpath3 = project("bf-retry-row", retry)
    _evio.append_row(proj3, _evio.row_for(
        proj3, row_result, "task", {"taskId": "P1.1"},
        {"runId": "run-red", "ts": "2026-01-01T00:00:00Z", "attempt": 1,
         "via": "cli"}, published=[smoke_cmd]))
    brief(proj3, mpath3, "P1.1", "executor")
    text3 = read(brief_file(proj3, "P1.1",
                            "20260101T000000Z.executor.md")) or ""
    check("bf3a a retry after a red gate step names THAT step's command and its "
          "failing line, and does not list the green step beside it: %r"
          % (text3[text3.find("Retry"):][:600],),
          "red step smoke: %s" % (smoke_cmd,) in text3 and smoke_line in text3
          and "red step unit" not in text3)
    check("bf3b a retry whose recorded run has no ledger row SAYS the steps were "
          "not read and why, rather than printing 'none recorded' for them: %r"
          % (text2[text2.find("Retry"):][:600],),
          "red steps: not read" in text2 and "run-red" in text2.split(
              "red steps: not read")[1].splitlines()[0])
    cut = text3.split("## Your return - the submit block\n", 1)[-1]
    check("bf3c the submit block is the FIRST thing in the closing submit "
          "section, and the brief's last section: %r" % (cut[:200],),
          cut.startswith("```sh\n") and "submit P1.1 --role executor" in cut
          .split("```", 2)[1]
          and cut.count("\n## ") == 0)

    # ---- the retry section quotes the operator's own `--reason` -------------
    # `drive-phase.py` keys the reason it recorded to the attempt it belongs
    # to - the driver's state file, written the same way the wave tree's
    # state is (bf40) - so the brief reads it rather than inventing a second
    # place to carry it.
    projr, mpathr = project("bf-retry-reason", retry)
    reason_state = os.path.join(projr, ".claude", "state", "drive", "P1.json")
    os.makedirs(os.path.dirname(reason_state))
    with open(reason_state, "w", encoding="utf-8") as fh:
        json.dump({"retryReason": {"P1.1": {
            "start": "20260101T000000Z",
            "value": "flaky infra the first time; rerun as-is"}}}, fh)
    brief(projr, mpathr, "P1.1", "executor")
    textr = read(brief_file(projr, "P1.1", "20260101T000000Z.executor.md")) or ""
    check("bf53 a retry brief over an attempt whose answer carried --reason "
          "prints that reason verbatim in the Retry section: %r"
          % (textr[textr.find("Retry"):][:300],),
          "operator's reason for --answer retry: flaky infra the first time; "
          "rerun as-is" in textr)
    check("bf53a RED TWIN: an attempt with nothing recorded for this start says "
          "so plainly, never inventing a reason or leaving the line out: %r"
          % (text2[text2.find("Retry"):][:300],),
          "operator's reason for --answer retry: none recorded" in text2)

    # ---- the retry section names EVERY failing line a red sweep step -------
    # recorded, not just the ones a further, SECOND excerpt-cut would have
    # left inside its kept head/tail - `run-test-gate.py` already bounds a
    # step's `failing` to `MAX_FAILING` lines before it ever reaches the row,
    # so re-excerpting that bounded list drops names the row still carries.
    pad_before = ["FAIL  tests/test_pad%02d.py: exited 1 - a long "
                  "padding reason so the joined text crosses the excerpt's "
                  "own head and tail bound before the real target is reached"
                  % (i,) for i in range(1, 4)]
    target_line = "FAIL  tests/test__deps.py: exited 1 (rc16)"
    pad_after = ["FAIL  tests/test_pad%02d.py: exited 1 - more "
                 "trailing padding so the target sits well inside the middle "
                 "a single excerpt call would have elided, not its kept tail"
                 % (i,) for i in range(4, 8)]
    sweep_failing = pad_before + [target_line] + pad_after
    sweep_cmd = "python3 tools/sweep-selftests.py"
    sweep_row = {"status": "failed", "durationMs": 10, "failed": ["selftests"],
                 "ranTotal": 2, "coverageBasis": None, "treeBasis": "b",
                 "treeMutated": [], "overlap": None,
                 "steps": [{"name": "selftests", "command": sweep_cmd,
                            "exit": 1, "failing": sweep_failing}]}
    sweep_task = retry["phases"][0]["tasks"][0]
    sweep_task["testEvidence"] = {"runId": "run-sweep", "status": "failed",
                                  "at": "z"}
    projs, mpaths = project("bf-retry-sweep", retry)
    _evio.append_row(projs, _evio.row_for(
        projs, sweep_row, "task", {"taskId": "P1.1"},
        {"runId": "run-sweep", "ts": "2026-01-01T00:00:00Z", "attempt": 1,
         "via": "cli"}, published=[sweep_cmd]))
    brief(projs, mpaths, "P1.1", "executor")
    texts = read(brief_file(projs, "P1.1", "20260101T000000Z.executor.md")) or ""
    retry_section_s = texts[texts.find("Retry"):]
    check("bf54 a retry brief over a red sweep step names each failing file's "
          "own FAIL <case> line it recorded, including one far enough into "
          "the step's output that a single excerpt call over the whole list "
          "would have dropped it behind a bare count: %r"
          % (retry_section_s[:900],),
          target_line in retry_section_s
          and all(p.split(":", 1)[0] in retry_section_s
                  for p in pad_before + pad_after))

    # bf54 variant: more failing lines than the row's bound, over many files.
    # The row cuts `failing` to MAX_FAILING lines but keeps the file list, so
    # the files are read from `failingSuites`; the last files have no line.
    many = ["tests/test_many%02d.py" % (i,)
            for i in range(1, _evio.MAX_FAILING + 6)]
    many_failing = ["FAIL  %s: rc1 at a%d" % (p, i)
                    for i, p in enumerate(many)]
    many_row = {"status": "failed", "durationMs": 10, "failed": ["selftests"],
                "ranTotal": 2, "coverageBasis": None, "treeBasis": "b",
                "treeMutated": [], "overlap": None,
                "steps": [{"name": "selftests", "command": sweep_cmd,
                           "exit": 1, "failing": many_failing,
                           "failingSuites": many,
                           "failingSuitesBasis": "the sweep named them"}]}
    sweep_task["testEvidence"] = {"runId": "run-many", "status": "failed",
                                  "at": "z"}
    projm, mpathm = project("bf-retry-many", retry)
    _evio.append_row(projm, _evio.row_for(
        projm, many_row, "task", {"taskId": "P1.1"},
        {"runId": "run-many", "ts": "2026-01-01T00:00:00Z", "attempt": 1,
         "via": "cli"}, published=[sweep_cmd]))
    brief(projm, mpathm, "P1.1", "executor")
    textm = read(brief_file(projm, "P1.1", "20260101T000000Z.executor.md")) or ""
    retry_section_m = textm[textm.find("Retry"):]
    check("a red gate step with more failing lines than the recorded bound "
          "still names every failing file, each with its own FAIL lines, "
          "read from the row's failing suites (named %d of %d, own lines "
          "%d, unrecorded notes %d)"
          % (sum(1 for p in many if p in retry_section_m), len(many),
             retry_section_m.count("rc1 at a"),
             retry_section_m.count("no FAIL line recorded")),
          all(p in retry_section_m for p in many)
          and retry_section_m.count("rc1 at a") == _evio.MAX_FAILING
          and retry_section_m.count("no FAIL line recorded")
          == len(many) - _evio.MAX_FAILING)

    # ---- the retry section reads the FILED return, not the task's own -----
    # fields - `task.outcome`/`task.redFirst` move only at `done`
    # (`audit-task.py`'s `close_task`), so a retried attempt that was never
    # closed leaves them exactly as an earlier attempt left them. The Retry
    # section must read what attempt N-1 actually FILED instead.
    retry_fresh = _bf_manifest(attempts=2)
    projf, mpathf = project("bf-retry-filed", retry_fresh)
    file_exec(projf, start="20251231T000000Z",
             text='{"gates": {}, '
                  '"outcome": {"technical": "prior attempt: fixed the off-by-one", '
                  '"descriptive": "d"},\n'
                  ' "testsAdded": ["bf_case"], "stamp": "audit-stamp: v2 x",\n'
                  ' "redFirst": {"status": "proved", '
                  '"basis": "exit 1 before the fix, exit 0 after", "at": "z"}}\n')
    brief(projf, mpathf, "P1.1", "executor")
    textf = read(brief_file(projf, "P1.1", "20260101T000000Z.executor.md")) or ""
    retry_section_f = textf[textf.find("Retry"):]
    check("bf55 a retry brief over an attempt whose filed return carried a "
          "proved redFirst prints it, never 'none recorded' - reading the "
          "FILED return rather than `task.redFirst`, which this never-closed "
          "retry never set: %r" % (retry_section_f[:500],),
          "prior attempt: fixed the off-by-one" in retry_section_f
          and "proved" in retry_section_f
          and "exit 1 before the fix, exit 0 after" in retry_section_f
          and "redFirst: none recorded" not in retry_section_f
          and "outcome.technical (verbatim):\nnone recorded" not in retry_section_f)

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
          and "python3 -m pytest" in rtext
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
          and "recorded by returns/P1/" in ptext6)

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

    ro_man = _bf_manifest()
    ro_man["meta"]["buildCommands"]["claimsMatchCode"] = (
        "review-only: sign-off reviewer refuses diff prose")
    ro_proj, ro_mpath = project("bf-review-only", ro_man)
    file_exec(ro_proj)
    brief(ro_proj, ro_mpath, "P1.1", "reviewer")
    ro_text = read(brief_file(ro_proj, "P1.1",
                              "20260101T000000Z.reviewer.md")) or ""
    check("bf5a a plan carrying a review-only entry puts the catalog's `asks` "
          "sentence in the reviewer's brief as an instruction, and a plan "
          "without one adds no such section: %r"
          % (ro_text[ro_text.find("## Refuse"):][:300],),
          "## Refuse" in ro_text and _gate_feed.review_asks(ro_man)[0][1]
          in ro_text and "## Refuse" not in rtext)

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

    # ONE INSTRUCTION, SAID ONCE. `submit` itself ends on what to hand back,
    # so a brief repeating it is the same step read twice. Counted per brief,
    # and the twin holds that the submit the instruction belongs to is still
    # there - a brief that lost the whole filing block would pass the first.
    _bf_handback = dict((name, t.lower().count("hand back one line"))
                        for name, t in (("executor", text), ("reviewer", rtext),
                                        ("phase-owed", ptext6),
                                        ("phase-unowed", ptext7)))
    check("bf26 no brief repeats the hand-back instruction `submit` already "
          "prints when it finishes: %r" % (_bf_handback,),
          _bf_handback == {"executor": 0, "reviewer": 0, "phase-owed": 0,
                           "phase-unowed": 0})
    _bf_submits = dict((name, t.count("drive-phase.py\" submit"))
                       for name, t in (("executor", text), ("reviewer", rtext),
                                       ("phase-owed", ptext6),
                                       ("phase-unowed", ptext7)))
    check("bf27 SECOND DIRECTION: every one of those briefs still names the "
          "`drive-phase.py submit` its return is filed with, once: %r"
          % (_bf_submits,),
          _bf_submits == {"executor": 1, "reviewer": 1, "phase-owed": 1,
                          "phase-unowed": 1})

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

    # ---- what the phase brief computes for the reviewer -----------------------
    def git(repo, *argv):
        return subprocess.run(["git", "-C", repo, "-c", "user.email=t@t",
                               "-c", "user.name=t", "-c", "commit.gpgsign=false"]
                              + list(argv), capture_output=True, timeout=60)

    def put(repo, rel, text):
        path = os.path.join(repo, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text)

    grown = _bf_signed_phase()
    projg, mpathg = project("bf-phase-existing", grown)
    git(projg, "init", "-q")
    put(projg, "tests/test_old.py", "def test_old():\n    assert True\n")
    put(projg, "tests/test_untouched.py", "def test_same():\n    assert True\n")
    put(projg, "src/m1.py", "x = 1\n")
    git(projg, "add", "-A")
    git(projg, "commit", "-qm", "base")
    base = git(projg, "rev-parse", "HEAD").stdout.decode().strip()
    put(projg, "tests/test_old.py", "def test_appended():\n    assert True\n")
    put(projg, "tests/test_new.py", "def test_new():\n    assert True\n")
    put(projg, "src/m1.py", "y = 2\n")
    grown["phases"][0]["baseRef"] = base
    with open(mpathg, "w", encoding="utf-8") as fh:
        json.dump(grown, fh)
    git(projg, "add", "-A")
    git(projg, "commit", "-qm", "the phase")
    brief(projg, mpathg, "P1", "phase")
    gtext = read(brief_file(projg, "P1", "phase.md")) or ""
    section = gtext.split("## Existing test files the phase modifies", 1)
    listed = ([ln for ln in section[1].split("\n## ", 1)[0].splitlines()
               if ln.startswith("- ")] if len(section) == 2 else None)
    nobase = _bf_signed_phase()
    projn, mpathn = project("bf-phase-nobase", nobase)
    brief(projn, mpathn, "P1", "phase")
    ntext = read(brief_file(projn, "P1", "phase.md")) or ""
    check("bf24 the phase brief lists the existing test file the phase appended "
          "a test to - and not the test file it added, the one it left alone "
          "or the source file it changed - and a phase with no baseRef says "
          "the list cannot be computed rather than listing none: %r"
          % ((base, listed, [ln for ln in ntext.splitlines()
                             if "baseRef" in ln]),),
          len(base) == 40 and listed == ["- tests/test_old.py"]
          and "## Existing test files the phase modifies" in ntext
          and "phase.baseRef is absent" in ntext)

    mixed = _bf_signed_phase()
    mixed["phases"][0]["tasks"][0]["tests"]["gate"] = ["test"]
    mixed["phases"][0]["tasks"][2]["tests"]["gate"] = [
        "python3 tests/test_m3.py"]
    projm, mpathm = project("bf-phase-mech", mixed)
    git(projm, "init", "-q")
    git(projm, "add", "-A")
    git(projm, "commit", "-qm", "fixture")
    sv = _loader.load_script("stamp-verification.py",
                             modname="stamp_verification_for_bf")
    helper = sv.red_verdict(
        {"cmd": ["python3", "tests/t1.py"], "code": 1, "text": "Error\n",
         "problem": None, "second": None, "head": None, "fix": None},
        {"root": None, "implementation": [], "tests": ["tests/t1.py"],
         "cases": [], "symbols": [], "dropped": [], "new": [],
         "head_files": None, "head_defs": None, "head_modules": None,
         "path": None})[2]
    helper = dict(helper, source="red-first-helper")   # as `submit` marks it
    file_exec(projm, text=_BF_EXEC.replace(
        '{"status": "proved", "basis": "exit 1", "at": "z"}',
        json.dumps(helper)))
    brief(projm, mpathm, "P1", "phase")
    mtext = read(brief_file(projm, "P1", "phase.md")) or ""

    def answer_lines(tid):
        part = mtext.split("\n## %s " % (tid,), 1)
        body = part[1].split("\n## ", 1)[0] if len(part) == 2 else ""
        return [ln for ln in body.splitlines()
                if ln.startswith(("red-first:", "inherited tests:"))]
    lines_m = dict((tid, answer_lines(tid)) for tid in ("P1.1", "P1.2", "P1.3"))

    def says(tid, prefix, word):
        return any(ln.startswith(prefix) and word in ln for ln in lines_m[tid])
    check("bf25 for each task owed its answers the phase brief says which of "
          "the mechanical answers the filing verb fills - the red-first of "
          "a helper's block, `not-asked` for a gate running the whole project - "
          "and which stay the reviewer's, with the reason: a hand-typed "
          "red-first or none filed, a gate naming a test file, an entry that "
          "resolves to nothing: %r" % (lines_m,),
          all(len(v) == 2 for v in lines_m.values())
          and says("P1.1", "red-first:", "computed")
          and says("P1.1", "inherited tests:", "computed")
          and says("P1.2", "red-first:", "yours")
          and says("P1.2", "inherited tests:", "unit:api")
          and says("P1.3", "inherited tests:", "yours")
          and says("P1.3", "inherited tests:", "tests/test_m3.py"))
    check("bf32 a `computed` line also says the reviewer may type the answer "
          "only a human settles over it - `not-proved` for red-first, "
          "`flagged` for inherited tests, with a basis - and that the filing "
          "verb records the override; a `yours` line carries neither, so the "
          "words follow the computed answer and nothing else: %r" % (lines_m,),
          says("P1.1", "red-first:", "`not-proved`")
          and says("P1.1", "red-first:", "records the override")
          and says("P1.1", "inherited tests:", "`flagged`")
          and says("P1.1", "inherited tests:", "records the override")
          and not says("P1.2", "red-first:", "`not-proved`")
          and not says("P1.3", "inherited tests:", "`flagged`"))

    # ---- the phase brief's per-task diffs, computed once rather than left
    # for the reviewer to re-derive --------------------------------------------
    def task_diff_block(text, tid):
        """The fenced diff body of task `tid`'s own section in a phase brief,
        or None when that section carries no fenced diff."""
        part = text.split("\n## %s " % (tid,), 1)
        if len(part) != 2:
            return None
        body = part[1].split("\n## ", 1)[0]
        if "```diff\n" not in body:
            return None
        return body.split("```diff\n", 1)[1].split("\n```", 1)[0]

    proj8, mpath8 = project("bf-diff-concat", _bf_manifest())
    git(proj8, "init", "-q")
    put(proj8, "src/a.py", "x = 1\n")
    put(proj8, "src/b.py", "y = 1\n")
    git(proj8, "add", "-A")
    git(proj8, "commit", "-qm", "base")
    base8 = git(proj8, "rev-parse", "HEAD").stdout.decode().strip()
    put(proj8, "src/a.py", "x = 2\n")
    git(proj8, "add", "-A")
    git(proj8, "commit", "-qm", "task1")
    sha_t1 = git(proj8, "rev-parse", "HEAD").stdout.decode().strip()
    # A second task's commit also touches a file no task declares - the scope
    # the next check names, which a per-task diff (bound to that task's own
    # `files`) never shows.
    put(proj8, "src/b.py", "y = 2\n")
    put(proj8, "src/extra.py", "z = 1\n")
    git(proj8, "add", "-A")
    git(proj8, "commit", "-qm", "task2")
    sha_t2 = git(proj8, "rev-parse", "HEAD").stdout.decode().strip()
    man8 = _bf_manifest()
    man8["phases"][0]["baseRef"] = base8
    man8["phases"][0]["tasks"] = [
        {"id": "P1.1", "title": "t1", "status": "done", "description": "d1",
         "files": ["src/a.py"],
         "tests": {"mode": "gate-only", "add": [], "expectRedFirst": False,
                   "gate": ["python3 tests/t1.py"]},
         "commit": sha_t1, "startedAt": _BF_START, "attempts": 1,
         "maxAttempts": 3},
        {"id": "P1.2", "title": "t2", "status": "done", "description": "d2",
         "files": ["src/b.py"],
         "tests": {"mode": "gate-only", "add": [], "expectRedFirst": False,
                   "gate": ["python3 tests/t2.py"]},
         "commit": sha_t2, "startedAt": _BF_START, "attempts": 1,
         "maxAttempts": 3}]
    with open(mpath8, "w", encoding="utf-8") as fh:
        json.dump(man8, fh)
    brief(proj8, mpath8, "P1", "phase")
    text8 = read(brief_file(proj8, "P1", "phase.md")) or ""
    d1 = task_diff_block(text8, "P1.1")
    d2 = task_diff_block(text8, "P1.2")
    concatenated = "\n".join(p for p in (d1, d2) if p)
    expect = subprocess.run(
        ["git", "-C", proj8, "diff", base8, sha_t2, "--", "src/a.py",
         "src/b.py", ":(exclude)docs/audit"],
        capture_output=True, timeout=60
    ).stdout.decode("utf-8", "replace").rstrip("\n")
    check("bf50 the brief's per-task diffs - each `commit`'s own content "
          "restricted to that task's files, docs/audit excluded - "
          "concatenate to exactly `git diff <base> <head> -- "
          "':(exclude)docs/audit'` over the tasks' own files: %r"
          % ((d1, d2, expect),),
          d1 is not None and d2 is not None and expect != ""
          and concatenated == expect)
    outside_section = (text8.split("## Phase diff scope", 1)[1]
                       .split("\n## ", 1)[0] if
                       "## Phase diff scope" in text8 else "")
    check("bf51 a phase that changed a file no task declares (task2's commit "
          "also touched src/extra.py) names it, under the phase's whole diff "
          "path list, as outside every task's scope - and not src/a.py or "
          "src/b.py, which a task does declare: %r" % (outside_section,),
          "src/extra.py" in outside_section
          and "Paths outside every task's declared files:" in outside_section
          and outside_section.split("Paths outside every task's declared "
                                    "files:", 1)[1].count("src/a.py") == 0
          and outside_section.split("Paths outside every task's declared "
                                    "files:", 1)[1].count("src/b.py") == 0)

    # ---- what the phase reviewer is handed to judge from: the diff, each
    # task's gate results step by step, and the instruction to open the code --
    ledger8 = os.path.join(proj8, "docs", "audit", "evidence",
                           "2026-10.fixture.jsonl")
    os.makedirs(os.path.dirname(ledger8), exist_ok=True)
    gated = {"P1.1": ("run-8a", "passed", [{"name": "selftests", "exit": 0}]),
             "P1.2": ("run-8b", "failed", [
                 {"name": "selftests", "exit": 0},
                 {"name": "lint", "exit": 3, "outcome": "failed"}])}
    with open(ledger8, "w", encoding="utf-8", newline="") as fh:
        fh.write("\n".join(json.dumps({
            "v": 1, "runId": run_id, "ts": "2026-10-01T00:00:00Z",
            "scope": "task", "taskId": tid, "status": status, "failed": [],
            "steps": steps, "observations": {"ranTotal": len(steps)}})
            for tid, (run_id, status, steps) in sorted(gated.items())) + "\n")
    for task in man8["phases"][0]["tasks"]:
        run_id, status, _steps = gated[task["id"]]
        task["testEvidence"] = {"runId": run_id, "status": status, "at": "z"}
    with open(mpath8, "w", encoding="utf-8") as fh:
        json.dump(man8, fh)
    brief(proj8, mpath8, "P1", "phase")
    text8g = read(brief_file(proj8, "P1", "phase.md")) or ""

    def task_section(text, tid):
        part = text.split("\n## %s " % (tid,), 1)
        return part[1].split("\n## ", 1)[0] if len(part) == 2 else ""
    steps8 = dict((tid, [ln for ln in task_section(text8g, tid).splitlines()
                         if ln.startswith("gate results")])
                  for tid in ("P1.1", "P1.2"))
    opening = [ln for ln in text8g.splitlines()
               if "open each changed function" in ln.lower()]
    first_task = text8g.find("\n## P1.1 ")
    check("bf60 the phase-review brief carries the phase diff, each task's gate "
          "results and the instruction to open each changed function: every "
          "task's section holds its own diff and one line of its recorded run's "
          "steps, each with its exit - the red step on the task that ran it and "
          "on no other - and the instruction is said once, before the first "
          "task's section: %r" % ((steps8, opening),),
          task_diff_block(text8g, "P1.1") not in (None, "", "(empty)")
          and task_diff_block(text8g, "P1.2") not in (None, "", "(empty)")
          and len(steps8["P1.1"]) == 1 and len(steps8["P1.2"]) == 1
          and "selftests exit 0" in steps8["P1.1"][0]
          and "lint" not in steps8["P1.1"][0]
          and "selftests exit 0" in steps8["P1.2"][0]
          and "lint exit 3" in steps8["P1.2"][0]
          and len(opening) == 1 and first_task > 0
          and text8g.find(opening[0]) < first_task)

    # ---- a re-review brief carries only the fix tasks' diffs -----------------
    rereview = _bf_signed_phase()
    rereview["phases"][0]["review"] = {"findings": [
        {"id": "P1-R1", "severity": "med", "file": "src/m1.py:1",
         "issue": "x", "resolution": "y", "fixTask": "P1.4"}]}
    rereview["phases"][0]["tasks"].append({
        "id": "P1.4", "title": "fix1", "status": "done",
        "description": "fix the finding", "files": ["src/m1.py"],
        "fixes": ["P1-R1"],
        "tests": {"mode": "regression", "add": [], "expectRedFirst": False,
                  "gate": ["python3 tests/t1.py"]},
        "commit": "e" * 40, "startedAt": _BF_START, "attempts": 1,
        "maxAttempts": 3,
        "testEvidence": {"runId": "run-4", "status": "passed", "at": "z"}})
    proj9, mpath9 = project("bf-phase-rereview", rereview)
    # The earlier round is on the record the way a real one is: its filed
    # return answers the three tasks at their commits.
    round9 = os.path.join(proj9, "docs", "audit", "evidence", "returns", "P1",
                          "%s.reviewer.json" % ("9" * 40,))
    os.makedirs(os.path.dirname(round9))
    with open(round9, "w", encoding="utf-8") as fh:
        json.dump({"findings": [], "intent": {"answer": "matches"},
                   "verdict": "findings",
                   "tasks": [{"id": "P1.%d" % n, "commit": c * 40,
                              "answer": "matches"}
                             for n, c in ((1, "a"), (2, "b"), (3, "c"))]}, fh)
    brief(proj9, mpath9, "P1", "phase")
    text9 = read(brief_file(proj9, "P1", "phase.md")) or ""
    check("bf52 a re-review brief - this phase already carries a finding whose "
          "fix task is P1.4 - lists only that fix task's section, not the "
          "three tasks an earlier round already reviewed, and says so: %r"
          % ([ln for ln in text9.splitlines() if ln.startswith("## P1.")],),
          "## P1.4 fix1" in text9
          and "## P1.1 t1" not in text9
          and "## P1.2 t2" not in text9
          and "## P1.3 t3" not in text9
          and "## Re-review scope" in text9
          and "P1.4" in text9.split("## Re-review scope", 1)[1]
                            .split("\n## ", 1)[0])
    # The re-review brief also says what a NEW low found in a fix becomes: it
    # is carried, not looped into another fix and another round - read within
    # the section, so the same words elsewhere in the brief cannot satisfy it.
    _scope9 = (text9.split("## Re-review scope", 1)[1].split("\n## ", 1)[0]
               if "## Re-review scope" in text9 else "")
    check("bf52b the re-review scope says a new low in a fix is carried, not "
          "looped, names the carry answer, and that only a med or high one "
          "owes a fix: %r" % (_scope9,),
          "new `low`" in _scope9 and "carried" in _scope9
          and "not looped" in _scope9
          and "--answer carry --to" in _scope9
          and "`med` or `high`" in _scope9)

    # ---- a re-review shows what the earlier round did not review -------------
    # The earlier round is the filed phase return: it answers P1.1 at its
    # commit. P1.4 fixes that round's finding; P1.5 is an ordinary task closed
    # after it. A brief that shows only fix tasks owes P1.5 an answer while
    # giving it no section, so the sections and the owed list are both read.
    later = _bf_signed_phase()
    later_phase = later["phases"][0]
    later_phase["tasks"] = [later_phase["tasks"][0]]
    later_phase["review"] = {"findings": [
        {"id": "P1-R1", "severity": "med", "file": "src/m1.py:1",
         "issue": "x", "resolution": "y", "fixTask": "P1.4"}]}
    later_phase["tasks"] += [
        {"id": "P1.4", "title": "fix1", "status": "done",
         "description": "fix the finding", "files": ["src/m1.py"],
         "fixes": ["P1-R1"],
         "tests": {"mode": "regression", "add": [], "expectRedFirst": False,
                   "gate": ["python3 tests/t1.py"]},
         "commit": "e" * 40, "startedAt": _BF_START, "attempts": 1,
         "maxAttempts": 3},
        {"id": "P1.5", "title": "later1", "status": "done",
         "description": "a task added after the review", "files": ["src/m5.py"],
         "tests": {"mode": "gate-only", "add": [], "expectRedFirst": False,
                   "gate": ["python3 tests/t5.py"]},
         "commit": "f" * 40, "startedAt": _BF_START, "attempts": 1,
         "maxAttempts": 3}]
    proj10, mpath10 = project("bf-phase-rereview-later", later)
    first_round = os.path.join(proj10, "docs", "audit", "evidence", "returns",
                               "P1", "%s.reviewer.json" % ("9" * 40,))
    os.makedirs(os.path.dirname(first_round))
    with open(first_round, "w", encoding="utf-8") as fh:
        json.dump({"findings": [], "intent": {"answer": "matches"},
                   "verdict": "findings",
                   "tasks": [{"id": "P1.1", "commit": "a" * 40,
                              "answer": "matches"}]}, fh)
    brief(proj10, mpath10, "P1", "phase")
    text10 = read(brief_file(proj10, "P1", "phase.md")) or ""
    shown10 = [ln.split()[1] for ln in text10.splitlines()
               if ln.startswith("## P1.")]
    owed10 = [ln.split(": ", 1)[1] for ln in text10.splitlines()
              if ln.startswith("owed: ")]
    check("a re-review brief shows the fix tasks and every task closed after "
          "the earlier review, repeats none that round reviewed, and gives "
          "every owed task a section (P1.1 answered by the filed return, P1.4 "
          "its fix, P1.5 closed after it: sections, owed): %r"
          % ((shown10, owed10),),
          shown10 == ["P1.4", "P1.5"] and owed10 == ["P1.5"]
          and all(t in shown10 for t in owed10))

    # ---- a round's reviewed set is what its brief showed, not what it owed ---
    # A fix task is owed no answer, so no `tasks` entry can mark it reviewed;
    # the filed return's `shown` list does. Round one answered P1.1; round two
    # showed the fix tasks P1.4 and P1.6, owing neither. Since then P1.5 closed
    # and P1.6 was redone at a new commit, so round three shows those two and
    # repeats neither P1.1 nor P1.4. A reading keyed on the id alone would
    # drop P1.6 too, which is the other way to get this wrong.
    third = _bf_signed_phase()
    third_phase = third["phases"][0]
    third_phase["tasks"] = [third_phase["tasks"][0]]
    third_phase["review"] = {"findings": [
        {"id": "P1-R%d" % n, "severity": "med", "file": "src/m1.py:1",
         "issue": "x", "resolution": "y", "fixTask": "P1.%d" % n}
        for n in (4, 6)]}

    def closed(tid, commit, fixes=None):
        task = {"id": tid, "title": "t" + tid, "status": "done",
                "description": "closed " + tid, "files": ["src/%s.py" % (tid,)],
                "tests": {"mode": "gate-only", "add": [], "expectRedFirst": False,
                          "gate": ["python3 tests/t.py"]},
                "commit": commit, "startedAt": _BF_START, "attempts": 1,
                "maxAttempts": 3}
        if fixes:
            task["fixes"] = fixes
        return task
    third_phase["tasks"] += [closed("P1.4", "e" * 40, ["P1-R4"]),
                             closed("P1.5", "f" * 40),
                             closed("P1.6", "d" * 40, ["P1-R6"])]
    proj11, mpath11 = project("bf-phase-round-three", third)
    rounds11 = os.path.join(proj11, "docs", "audit", "evidence", "returns", "P1")
    os.makedirs(rounds11)
    for name, body in (
            ("9" * 40, {"tasks": [{"id": "P1.1", "commit": "a" * 40,
                                   "answer": "matches"}]}),
            ("8" * 40, {"tasks": [],
                        "shown": [{"id": "P1.4", "commit": "e" * 40},
                                  {"id": "P1.6", "commit": "c" * 40}]})):
        with open(os.path.join(rounds11, "%s.reviewer.json" % (name,)), "w",
                  encoding="utf-8") as fh:
            json.dump(dict(body, findings=[], verdict="findings",
                           intent={"answer": "matches"}), fh)
    git(proj11, "init", "-q")
    git(proj11, "add", "-A")
    git(proj11, "commit", "-qm", "round three")
    brief(proj11, mpath11, "P1", "phase")
    text11 = read(brief_file(proj11, "P1", "phase.md")) or ""
    shown11 = [ln.split()[1] for ln in text11.splitlines()
               if ln.startswith("## P1.")]
    owed11 = [ln.split(": ", 1)[1] for ln in text11.splitlines()
              if ln.startswith("owed: ")]
    check("Record what a round reviewed, not only what it owed (round three: "
          "the fix task P1.4 round two showed is not shown again, P1.5 closed "
          "since is, and so is P1.6, redone at a commit round two never "
          "showed; sections, owed): %r" % ((shown11, owed11),),
          shown11 == ["P1.5", "P1.6"] and owed11 == ["P1.5"])
    submit11 = [ln for ln in text11.splitlines() if " submit P1 " in ln]
    want11 = "--shown P1.5@%s,P1.6@%s" % ("f" * 40, "d" * 40)
    check("the phase brief's filing command carries the set it shows, each "
          "task at the commit its section names, so the filing verb records "
          "what this round reviewed: %r" % (submit11,),
          len(submit11) == 1 and submit11[0].count("--shown ") == 1
          and want11 in submit11[0])
    # The same set is recorded beside the brief, keyed by its head, in the
    # shape the filing verb reads (`test_audit_task.py` files against a record
    # hand-written in this shape). Every record in the folder is listed, so a
    # writer keying it on anything else, or writing two, reads as a failure.
    head11 = git(proj11, "rev-parse", "HEAD").stdout.decode().strip()
    folder11 = os.path.dirname(brief_file(proj11, "P1", "phase.md"))
    records11 = sorted(n for n in os.listdir(folder11)
                       if n.startswith("phase.shown."))
    body11 = read(os.path.join(folder11, records11[0])) if records11 else None
    check("the phase brief records the set it showed beside itself, keyed by "
          "the head it was computed at, each task at the commit its section "
          "names: %r" % ((head11, records11, body11),),
          records11 == ["phase.shown.%s.json" % (head11,)]
          and json.loads(body11 or "null") == {
              "head": head11,
              "shown": [{"id": "P1.5", "commit": "f" * 40},
                        {"id": "P1.6", "commit": "d" * 40}]})

    # ---- a wave task's brief says which tree it works in --------------------
    # The tree comes from the driver's state, which is where `add_tree` records
    # it; a task with no tree in that state (width 1) gets none of the lines.
    proj_w, mpath_w = project("bf-wave", _bf_manifest())
    plain_w = brief(proj_w, mpath_w, "P1.1", "executor")
    plain_text = read(brief_file(proj_w, "P1.1", "20260101T000000Z.executor.md")) or ""
    state_w = os.path.join(proj_w, ".claude", "state", "drive", "P1.json")
    os.makedirs(os.path.dirname(state_w))
    with open(state_w, "w", encoding="utf-8") as fh:
        json.dump({"wave": {"id": "P1-w1", "base": "b" * 40, "tasks": ["P1.1"],
                            "trees": {"P1.1": "/work/tree-P1.1", "P1.9": "/work/other"}}},
                  fh)
    brief(proj_w, mpath_w, "P1.1", "executor")
    wave_text = read(brief_file(proj_w, "P1.1", "20260101T000000Z.executor.md")) or ""
    wave_lines = wave_text.splitlines()
    check("bf40 a wave task's brief carries its own `tree:` and `base:` lines, "
          "the `cd <tree> &&` rule for every command and the never-commit rule, "
          "and not a sibling's tree: %r" % (plain_w[0],),
          "tree: /work/tree-P1.1" in wave_lines and ("base: " + "b" * 40) in wave_lines
          and "cd /work/tree-P1.1 &&" in wave_text
          and "never commit" in wave_text.lower()
          and "/work/other" not in wave_text)
    check("bf41 the same task's brief at width 1 (no tree in the driver's state) "
          "carries none of those lines: %r" % (plain_text[:80],),
          plain_text != "" and not any(
              ln.startswith(("tree:", "base:")) for ln in plain_text.splitlines())
          and "cd " not in plain_text and "never commit" not in plain_text.lower())

    abs_manifest = os.path.join(proj_w, "docs", "audit", "audit-plan.json")
    check("bf42 a wave task's submit block spells the phase tree's manifest "
          "absolutely and says the command runs from the project: %r"
          % (wave_text[-400:],),
          (" submit P1.1 --role executor %s --project-dir " % (abs_manifest,)) in wave_text
          and "Run this command from the project" in wave_text)
    import ntpath
    import posixpath
    win_abs = M.absolute_manifest("C:\\work\\proj", "docs/audit/audit-plan.json", ntpath)
    check("bf44 on the Windows shape the absolute manifest is one separator "
          "style, not the project's backslashes joined to the plan's slashes, "
          "and the POSIX shape is unchanged: %r" % (win_abs,),
          win_abs == "C:\\work\\proj\\docs\\audit\\audit-plan.json"
          and M.absolute_manifest("/w/p", "docs/audit/audit-plan.json", posixpath)
          == "/w/p/docs/audit/audit-plan.json")
    check("bf43 THE ALLOW TWIN: at width 1 the submit block keeps the relative "
          "manifest and carries no run-from-the-project line: %r" % (plain_text[-300:],),
          " submit P1.1 --role executor docs/audit/audit-plan.json --project-dir "
          in plain_text and "Run this command from the project" not in plain_text)

    # ---- the order: the stable part first, the task's own part last -------
    # The headings that belong to one task. A brief must carry several of
    # them, or an order check over it would be read over nothing.
    task_heads = ("## Tree", "## Skills", "## Description (verbatim)",
                  "## Phase desired outcome", "## Files", "## Docs", "## Tests",
                  "## What you run", "## Retry")
    rules_line = "The rules and the return shape are agents/audit-executor.md's."

    def order(body):
        lines = body.splitlines()
        heads = [i for i, ln in enumerate(lines) if ln.startswith(task_heads)]
        rules = lines.index(rules_line) if rules_line in lines else None
        ret = lines.index("## Your return") if "## Your return" in lines else None
        return {"rules": rules, "return": ret, "firstTask": min(heads or [None]),
                "taskHeads": len(heads)}

    orders = [order(t) for t in (text, text3, wave_text) if t]
    bad_order = [o for o in orders
                 if o["rules"] is None or o["return"] is None
                 or o["taskHeads"] < 6
                 or not o["rules"] < o["return"] < o["firstTask"]]
    check("bo1 every executor brief places the rules and return contract before "
          "the task-specific sections: %r" % (orders,),
          len(orders) == 3 and not bad_order)
    # The prefix a prompt cache reuses: two executor briefs for DIFFERENT
    # tasks must agree byte for byte up to the first task-specific heading.
    # The floor is the rules line plus the whole return contract, measured
    # from the text itself rather than written as a number: a brief that put
    # the id or the task's command back into that block shortens the shared
    # prefix to the rules line alone, which is below it.
    two_manifest = _bf_manifest()
    two_phase = two_manifest["phases"][0]
    second = json.loads(json.dumps(two_phase["tasks"][0]))
    second["id"] = "P1.2"
    second["title"] = "a second, differently named task"
    two_phase["tasks"].append(second)
    proj_two, mpath_two = project("bf-two", two_manifest)
    brief(proj_two, mpath_two, "P1.1", "executor")
    brief(proj_two, mpath_two, "P1.2", "executor")
    bytes_a = (read(brief_file(proj_two, "P1.1",
                               "20260101T000000Z.executor.md")) or "").encode("utf-8")
    bytes_b = (read(brief_file(proj_two, "P1.2",
                               "20260101T000000Z.executor.md")) or "").encode("utf-8")
    shared = len(os.path.commonprefix([bytes_a, bytes_b]))
    contract_end = (bytes_a.find(b"\n## Brief for") if bytes_a else -1)
    check("bo3 stable prefix (two executor briefs for different tasks share a byte prefix as "
          "long as the whole stable part - the rules line and the return "
          "contract, up to the first task heading - and the task's id is not "
          "in it: %r" % ((shared, contract_end),),
          bytes_a != bytes_b and contract_end > len(rules_line)
          and shared >= contract_end
          and b"P1.1" not in bytes_a[:shared] and b"submit P1.1" in bytes_a)

    # ---- the reviewer and phase briefs carry the clause rule and tests.add --
    def heads(body):
        return [ln for ln in body.splitlines() if ln.startswith("## ")]

    clause_marker = M.CLAUSE_QUOTING_LINES[0]
    rev_heads = heads(rtext)
    check("bo4 reviewer brief clause rule and order (the reviewer brief quotes the clause rule once, carries a "
          "tests.add section, and ends on '## Task' then '## Claim under "
          "review' directly before the return): %r" % (rev_heads,),
          rtext.count(clause_marker) == 1 and "## tests.add" in rev_heads
          and rev_heads[-3] == "## Task"
          and rev_heads[-2].startswith("## Claim under review")
          and rev_heads[-1] == "## Your return")
    phase_heads = heads(ptext)
    task_at = [i for i, h in enumerate(phase_heads) if h == "## Task"]
    check("bo5 phase brief clause rule and order (the phase brief quotes the clause rule once and, for each of its "
          "listed tasks, carries a tests.add line and a '## Task' heading "
          "followed at once by '## Claim under review'): %r" % (phase_heads,),
          ptext.count(clause_marker) == 1 and ptext.count("\ntests.add:") == len(signed)
          and len(task_at) == len(signed)
          and all(phase_heads[i + 1].startswith("## Claim under review")
                  for i in task_at))
    proj_e = os.path.join(root, "bf-exec")
    mpath_e = os.path.join(proj_e, "docs", "audit", "audit-plan.json")
    out_r, err_r = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out_r), contextlib.redirect_stderr(err_r):
        try:
            read_code = M.main([mpath_e, "brief", "P1.1", "--role", "executor",
                                "--read", "--project", proj_e])
        except SystemExit as exc:
            read_code = exc.code
    read_said = out_r.getvalue()
    on_disk = read(path) or ""
    proj_n, mpath_n = project("bf-unread", _bf_manifest())
    out_n, err_n = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out_n), contextlib.redirect_stderr(err_n):
        try:
            none_code = M.main([mpath_n, "brief", "P1.1", "--role", "executor",
                                "--read", "--project", proj_n])
        except SystemExit as exc:
            none_code = exc.code
    check("bo2 `brief --role executor --read` prints the brief written for the "
          "task's current start byte for byte and writes nothing; with none "
          "written it is a miss that says so: %r"
          % ((read_code, none_code, err_n.getvalue()[:160]),),
          read_code == M.E_OK and on_disk != "" and read_said == on_disk
          and none_code == M.E_NOMATCH and "no executor brief" in err_n.getvalue()
          and not os.path.exists(brief_file(proj_n, "P1.1",
                                            "20260101T000000Z.executor.md")))

    # A return filed on Windows carries CRLF, and a reviewer brief embeds it as
    # filed; the arrow is a character cp1252 cannot spell. The stand-in stdout
    # is what a Windows console pipe is: cp1252, strict, and every "\n"
    # written through it leaving as "\r\n".
    proj_w, mpath_w = project("bf-crlf", _bf_manifest())
    file_exec(proj_w, text=_BF_EXEC.replace("descriptive\": \"d\"",
                                            "descriptive\": \"d ← e\"")
              .replace("\n", "\r\n"))
    crlf_code, _crlf_said = brief(proj_w, mpath_w, "P1.1", "reviewer")
    try:
        with open(brief_file(proj_w, "P1.1", "20260101T000000Z.reviewer.md"),
                  "rb") as fh:
            written_w = fh.read()
    except OSError:
        written_w = b""
    raw_w = io.BytesIO()
    console = io.TextIOWrapper(raw_w, encoding="cp1252", errors="strict",
                               newline="\r\n")
    err_w = io.StringIO()
    with contextlib.redirect_stdout(console), contextlib.redirect_stderr(err_w):
        try:
            read_w = M.main([mpath_w, "brief", "P1.1", "--role", "reviewer",
                             "--read", "--project", proj_w])
        except Exception as exc:                                   # noqa: BLE001
            read_w = "%s: %s" % (type(exc).__name__, exc)
    console.flush()
    printed_w = raw_w.getvalue()
    check("tests/test_audit_lookup.py: a reviewer brief carrying "
          "non-cp1252 characters and CRLF-prone text, read back through brief "
          "--read under a cp1252 stdout, prints exactly the bytes that were "
          "written (the brief holds both, and the bytes printed are the "
          "file's): %r" % ((crlf_code, read_w, len(written_w), len(printed_w),
                            printed_w.count(b"\r\r\n")),),
          crlf_code == M.E_OK and read_w == M.E_OK
          and b"\r\n" in written_w and "←".encode("utf-8") in written_w
          and printed_w == written_w)

    code6, said6 = brief(proj, mpath, "P1", "executor")
    check("bf11 a phase id asked for a task's role, or a task id for the "
          "phase's, is a miss rather than a brief about the wrong thing: %r"
          % ((code6, said6[:120]),),
          code6 == M.E_NOMATCH
          and brief(proj, mpath, "P1.1", "phase")[0] == M.E_NOMATCH)


_NESTED_GIT = ("git",) + _harness.NO_AUTO_MAINTENANCE + (
    "-c", "user.email=t@t.t", "-c", "user.name=t",
    "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main")


def _nested_scope_cases(check):
    """A project that is a SUBDIRECTORY of its git root: git names the phase
    diff's paths from the root, a task declares its files from the project."""
    root = os.path.realpath(_harness.fixture_root("audit-lookup-nested-"))
    repo = os.path.join(root, "repo")
    proj = os.path.join(repo, "proj")

    def put(rel, text):
        path = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def git(*argv):
        return _harness.git(repo, *argv, prefix=_NESTED_GIT, timeout=30).strip()

    os.makedirs(proj)
    put("proj/src/a.py", "a = 1\n")
    put("src/a.py", "root a = 1\n")
    git("init", "-q")
    git("add", "-A")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    # The declared file, an undeclared sibling in the project, and a checkout-root
    # file that shares the declared file's NAME: spelled from the root, the
    # declared change reads `proj/src/a.py` (undeclared) and the root file
    # reads `src/a.py` (covered) - the reverse of the truth.
    put("proj/src/a.py", "a = 2\n")
    put("proj/src/extra.py", "z = 1\n")
    put("src/a.py", "root a = 2\n")
    git("add", "-A")
    git("commit", "-qm", "work")
    head = git("rev-parse", "HEAD")
    phase = {"id": "P1", "baseRef": base,
             "tasks": [{"id": "P1.1", "files": ["src/a.py"]}]}
    lines = M._phase_scope_lines({"project": proj, "gitRoot": repo}, phase, head)
    marker = "Paths outside every task's declared files:"
    outside = lines[lines.index(marker) + 1:] if marker in lines else None
    check("nl1 the phase-diff outside-declared list is computed on one base for a "
          "nested project (%r)" % (lines,),
          outside is not None
          and sorted(outside) == ["- ../src/a.py", "- src/extra.py"])
    # The allow direction: a project that IS its git root keeps its paths as
    # git spells them, so rebasing must be a no-op there.
    flat = {"project": repo, "gitRoot": repo}
    flat_lines = M._phase_scope_lines(flat, phase, head)
    flat_out = flat_lines[flat_lines.index(marker) + 1:]
    check("nl2 a project that is its own git root lists the undeclared paths as "
          "git spells them (%r)" % (flat_lines,),
          sorted(flat_out) == ["- proj/src/a.py", "- proj/src/extra.py"])


NESTED_MEMBER_CLAUSE = ("nested project - phase diff excludes member/docs/audit; "
                        "task-commit diff and _diff_lines are non-empty for a "
                        "declared changed file")


def _nested_member_cases(check):
    """A real `git init` with the project at `member/`: every diff this module
    computes for a brief is run from the checkout's top, so its pathspecs and
    its exclusion must be spelled from there and its paths read back."""
    root = os.path.realpath(_harness.fixture_root("audit-lookup-member-"))
    repo = os.path.join(root, "repo")
    proj = os.path.join(repo, "member")

    def put(top, rel, text):
        path = os.path.join(top, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def git(cwd, *argv):
        return _harness.git(cwd, *argv, prefix=_NESTED_GIT, timeout=30).strip()

    def label(n, which):
        return "nl%d %s (%s)" % (n, NESTED_MEMBER_CLAUSE, which)

    put(repo, "member/src/a.py", "a = 1\n")
    put(repo, "member/docs/audit/journal.jsonl", "{}\n")
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD")
    put(repo, "member/src/a.py", "a = 2\n")
    put(repo, "member/docs/audit/journal.jsonl", "{}\n{}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "work")
    head = git(repo, "rev-parse", "HEAD")
    ctx = {"project": proj, "gitRoot": repo}

    paths, why = M._phase_diff_paths(ctx, base, head)
    check(label(3, "the phase diff names the declared file in plan spelling "
                   "and leaves the member's docs/audit out: %r" % ((paths, why),)),
          why is None and paths == ["src/a.py"])
    # A member project whose config names no gitRoot hands the project itself
    # over as the git root; git still prints from the checkout's top.
    unset = M._phase_diff_paths({"project": proj, "gitRoot": proj}, base, head)
    check(label(7, "the same phase diff when the configured git root is the "
                   "project itself rather than the checkout's top: %r" % (unset,)),
          unset == (["src/a.py"], None))

    task_diff = M._task_commit_diff_lines(ctx, head, ["src/a.py"])
    check(label(4, "the task-commit diff of a declared changed file carries its "
                   "change: %r" % (task_diff,)),
          "(empty)" not in task_diff and "+a = 2" in "\n".join(task_diff))

    put(repo, "member/src/a.py", "a = 3\n")
    put(repo, "member/src/new.py", "n = 1\n")
    lines = M._diff_lines(ctx, ["src/a.py", "src/new.py"])
    text = "\n".join(lines)
    check(label(5, "_diff_lines against HEAD carries the declared change and "
                   "names the untracked declared file in plan spelling: %r"
                % (lines,)),
          "(empty)" not in lines and "+a = 3" in text
          and lines[-1].endswith(": src/new.py"))

    tree = os.path.join(root, "wave-tree")
    git(repo, "worktree", "add", "-q", "--detach", tree, head)
    put(tree, "member/src/a.py", "a = 4\n")
    wave = M._diff_lines(ctx, ["src/a.py"], tree, head)
    check(label(6, "_diff_lines in a wave member's tree carries the declared "
                   "change: %r" % (wave,)),
          "(empty)" not in wave and "+a = 4" in "\n".join(wave))


# The plain reference the owner's baseline measured, held as a literal: the
# writer's prompt is this text for the fixture task, line for line, except the
# lines the task names as deliberate differences. Held here and not derived
# from the module, so a template that drifts is a failed case and not a
# template that agrees with itself.
_WP_DESCRIPTION = ("Do (1) this and (2) that for refunds.\n"
                   "Acceptance: (1) the split sums exactly (2) the remainder "
                   "goes to the last of (7) lines (3) a zero refund is refused")
_WP_BASELINE = [
    "Implement the following task in this repository.",
    "",
    "Task: Split a refund across lines",
    "",
    _WP_DESCRIPTION,
    "",
    "Files the task declares:",
    "- src/refund.py",
    "- tests/test_refund.py",
    "",
    "Tests to add:",
    "- tests/test_refund.py: sums exactly",
    "- tests/test_refund.py: the remainder rule",
    "",
    "Before you finish, check that everything passes:",
    "- python3 tools/sweep-selftests.py",
    "- ruff check plugins/audit tools && vermin -t=3.8- --no-tips plugins/audit",
    "- python3 plugins/audit/scripts/report/render-report.py docs/audit/audit-plan.json --out-dir /tmp/audit-report",
    "",
    "@@BROWSER@@",
    "",
    "@@COMMIT@@",
    "",
    "@@CLOSING@@",
]
_WP_BROWSER = ["node tools/capture-screenshots.mjs --check",
               "node tools/check-report-interactive.mjs examples/acme-store/acme-store-audit.html"]


def _wp_manifest(gate=("selftests", "lint", "report", "shots", "interactive"),
                 add=("tests/test_refund.py: sums exactly",
                      "tests/test_refund.py: the remainder rule"),
                 description=_WP_DESCRIPTION):
    commands = {
        "selftests": "python3 tools/sweep-selftests.py",
        "lint": "ruff check plugins/audit tools && vermin -t=3.8- --no-tips plugins/audit",
        "report": "python3 plugins/audit/scripts/report/render-report.py "
                  "docs/audit/audit-plan.json --out-dir /tmp/audit-report",
        "shots": _WP_BROWSER[0],
        "interactive": _WP_BROWSER[1],
        # a user project's own gate, spelled the way a project may spell it
        "verifysh": "./scripts/verify.sh --fast"}
    task = {"id": "P1.1", "title": "Split a refund across lines",
            "status": "in_progress", "description": description,
            "files": ["src/refund.py", "tests/test_refund.py"],
            "docs": ["docs/refunds.md"], "skills": ["writing-python"],
            "tests": {"mode": "tdd", "expectRedFirst": True,
                      "add": list(add), "gate": list(gate)},
            "startedAt": _BF_START, "attempts": 1, "maxAttempts": 3}
    phase = {"id": "P1", "title": "Refunds", "status": "in_progress",
             "desiredOutcome": "refunds add up to the order total",
             "tasks": [task]}
    return {"meta": {"version": 2, "buildCommands": commands},
            "phases": [phase], "bugs": [],
            "fileIndex": {"src/refund.py": ["P1.1"],
                          "tests/test_refund.py": ["P1.1"]}}


# What this repository's own config names as left to the phase gate; the
# composition itself carries no such list, so a case that wants the browser
# sentence passes it, as `brief --role writer` passes the project's.
_WP_LEFT = ("capture-screenshots.mjs", "check-report-interactive.mjs")


def _wp_text(manifest, left=_WP_LEFT):
    phase = manifest["phases"][0]
    return "\n".join(M.compose_writer_prompt(
        manifest, phase, phase["tasks"][0], phase_gate_only=left)) + "\n"


def _writer_prompt_cases(check):
    """The writer's prompt is plain's own prompt composed from the task, with
    one closing line asking for an answer per acceptance clause."""
    man = _wp_manifest()
    text = _wp_text(man)
    lines = text.split("\n")[:-1]
    template = "\n".join(_WP_BASELINE).split("\n")
    # The three template lines that carry a deliberate difference: the browser
    # line (it names the drive, which the measured prompt could not), the commit
    # line and the closing line. Every other line must be the literal's.
    cut = [i for i, ln in enumerate(template) if ln.startswith("@@")]
    shape_ok = len(lines) == len(template)
    others_equal = shape_ok and all(lines[i] == template[i]
                                    for i in range(len(template))
                                    if i not in cut)
    commit = lines[cut[1]] if shape_ok else ""
    check("wp1 on the fixture task the writer prompt equals the baseline "
          "literal line for line - same number of lines, every line but the "
          "three marked ones identical: lines=%d template=%d"
          % (len(lines), len(template)), others_equal)
    check("wp2 the commit line is the one deliberate rewrite of the measured "
          "final sentence - the changes stay uncommitted and the drive commits "
          "them: %r" % (commit,),
          shape_ok and commit == "Fix whatever does not pass. When everything "
          "is green, leave the changes uncommitted: the drive commits them."
          and "commit the changes as one commit" not in text)

    browser = [ln for ln in lines if ln.startswith("Do not run")]
    gate_at = lines.index("Before you finish, check that everything passes:")
    gate_items = []
    for ln in lines[gate_at + 1:]:
        if not ln.startswith("- "):
            break
        gate_items.append(ln)
    check("wp3 no browser gate is listed among the commands to run, and the "
          "non-browser three are: %r" % (gate_items,),
          len(gate_items) == 3
          and not any("capture-screenshots" in g or "check-report-interactive"
                      in g or "playwright" in g or "verify.sh" in g
                      for g in gate_items))
    check("wp4 ONE line names the commands the project left to the phase gate, "
          "each once, and says that and nothing about who runs them: %r" % (browser,),
          len(browser) == 1
          and all(browser[0].count(c) == 1 for c in _WP_BROWSER)
          and "left to the phase gate" in browser[0]
          and "drive runs" not in browser[0] and "browser" not in browser[0])
    # THE USER PROJECT: its gate is ./scripts/verify.sh, a name this repository's
    # own gates share. With no config key the writer is told to run it, and is
    # told nothing about browsers; the key naming it is what leaves it to the
    # phase gate (the over-fire mutation: a hard-coded name set leaves it out of
    # the commands to run in the first case).
    user = _wp_manifest(gate=("selftests", "verifysh"))
    user_phase = user["phases"][0]
    user_task = user_phase["tasks"][0]
    default_lines = M.compose_writer_prompt(user, user_phase, user_task)
    named_lines = M.compose_writer_prompt(user, user_phase, user_task,
                                          phase_gate_only=("verify.sh",))
    check("wp13 a project whose gate is ./scripts/verify.sh and which sets no key "
          "is told to run it, and nothing is said about browser gates or about "
          "leaving anything to the drive: %r" % (default_lines[-8:],),
          "- ./scripts/verify.sh --fast" in default_lines
          and not [ln for ln in default_lines if ln.startswith("Do not")]
          and not [ln for ln in default_lines
                   if "browser" in ln or "phase gate" in ln])
    left = [ln for ln in named_lines if ln.startswith("Do not run")]
    check("wp14 the key naming verify.sh leaves that command to the phase gate, "
          "in those words, and takes it out of the commands to run: %r" % (left,),
          left == ["Do not run ./scripts/verify.sh --fast: left to the phase gate."]
          and "- ./scripts/verify.sh --fast" not in named_lines
          and "- python3 tools/sweep-selftests.py" in named_lines)
    pw = _wp_manifest(gate=("selftests",))
    pw["meta"]["buildCommands"]["pw"] = "npx playwright test --project=chromium"
    pw["phases"][0]["tasks"][0]["tests"]["gate"] = ["selftests", "pw"]
    pw_default = M.compose_writer_prompt(pw, pw["phases"][0],
                                         pw["phases"][0]["tasks"][0])
    pw_named = M.compose_writer_prompt(pw, pw["phases"][0],
                                       pw["phases"][0]["tasks"][0],
                                       phase_gate_only=("playwright test",))
    check("wp15 a multi-word entry matches its words in a row, and only when the "
          "key names it: playwright test is run by the writer by default and left "
          "to the phase gate when named; a different word order is not it: %r"
          % ([ln for ln in pw_named if ln.startswith("Do not")],),
          "- npx playwright test --project=chromium" in pw_default
          and not [ln for ln in pw_default if ln.startswith("Do not")]
          and [ln for ln in pw_named if ln.startswith("Do not run")]
          == ["Do not run npx playwright test --project=chromium: left to the "
              "phase gate."]
          and not M.left_to_phase_gate("npx test playwright", ("playwright test",))
          and M.left_to_phase_gate("\"./a/verify.sh\" --x", ("verify.sh",))
          and not M.left_to_phase_gate("./scripts/verify.sh", ()))
    plain = M.compose_writer_prompt(
        _wp_manifest(gate=("selftests", "lint")), _wp_manifest()["phases"][0],
        _wp_manifest(gate=("selftests", "lint"))["phases"][0]["tasks"][0])
    check("wp5 THE ALLOW TWIN of wp4: a gate with no browser entry gets no "
          "browser line, because naming gates the task does not have is a claim "
          "with no basis: %r" % ([ln for ln in plain if ln.startswith("Do not")],),
          not [ln for ln in plain if ln.startswith("Do not")]
          and "- python3 tools/sweep-selftests.py" in plain)

    forbidden = ("brief", "Skill", "skill", "submit", "AUDIT_RETURN",
                 "drive-phase", "audit-executor", "casesAdded", "redFirst",
                 "Invoke each", "executor", "docs/refunds.md", "writing-python",
                 "Refunds", "desired outcome")
    hits = [w for w in forbidden if w in text]
    check("wp6 the prompt carries no brief path, no guidance, no skills list, "
          "no submit instruction, no docs list and no phase outcome - none of "
          "those words appears: %r" % (hits,), not hits)

    closing = lines[-1]
    check("wp7 the closing line numbers the clauses the way the task does - the "
          "two tests.add entries are clauses 1 to 2 and the three Acceptance "
          "items, read after the LAST 'Acceptance:' and by sequence so the "
          "'(7)' inside item 2 and the '(1)' before the marker are not items, "
          "are clauses 3 to 5: %r" % (closing,),
          "clauses 1 to 2" in closing and "clauses 3 to 5" in closing
          and "(1) to (3)" in closing and "delivered" in closing
          and "reason" in closing)
    check("wp8 the clause list the closing line is built from, read straight "
          "off the task: %r" % ([(c["n"], c["kind"]) for c in M.task_clauses(
              man["phases"][0]["tasks"][0])],),
          [(c["n"], c["kind"]) for c in M.task_clauses(
              man["phases"][0]["tasks"][0])]
          == [(1, "tests.add"), (2, "tests.add"), (3, "acceptance"),
              (4, "acceptance"), (5, "acceptance")]
          and M.task_clauses(man["phases"][0]["tasks"][0])[3]["text"]
          .startswith("the remainder goes to the last of (7) lines"))

    task_one = man["phases"][0]["tasks"][0]
    last_n = _cc.task_clauses(task_one)[-1]["n"]
    check("wp8b ONE NUMBERING: the brief's clause list and the list the drive "
          "reads a writer's answer against are the same function and the same "
          "numbers for one fixture task - not two implementations that agree on "
          "it today - and the closing line's last clause is the list's last "
          "(%d): %r" % (last_n, closing),
          M.task_clauses is _cc.task_clauses
          and M.acceptance_items is _cc.acceptance_items
          and M.task_clauses(task_one) == _cc.task_clauses(task_one)
          and ("clauses 3 to %d" % (last_n,)) in closing)

    # The other order, which a numbering that put Acceptance first would pass
    # wp7 on: no tests.add entry, so the Acceptance items are clauses 1 to 3.
    bare = _wp_manifest(add=())
    bare_closing = _wp_text(bare).split("\n")[-2]
    tests_section = _wp_text(bare).split("Tests to add:\n")[1].split("\n")[0]
    check("wp9 a task with no tests.add entry numbers its Acceptance items "
          "from 1, says so in the section, and the closing line names no "
          "tests.add clause: %r / %r" % (tests_section, bare_closing),
          tests_section == "- none"
          and "clauses 1 to 3" in bare_closing
          and "Tests to add" not in bare_closing
          and bare_closing.count("clauses") == 1)

    none = _wp_manifest(add=(), description="Do the thing with no list.")
    none_closing = _wp_text(none).split("\n")[-2]
    check("wp10 a task that numbers no clause says so instead of asking for "
          "entries that do not exist - the empty object, not a gap: %r"
          % (none_closing,),
          "no acceptance clause" in none_closing and "{}" in none_closing
          and "clauses 1" not in none_closing)

    check("wp11 two calls give identical bytes: %r"
          % (_wp_text(man) == text,),
          _wp_text(man) == text and _wp_text(_wp_manifest()) == text)

    # --- the command, as the drive runs it -----------------------------------
    root = _harness.fixture_root("audit-lookup-wp-")
    proj = os.path.join(root, "proj")
    os.makedirs(os.path.join(proj, ".claude"))
    with open(os.path.join(proj, ".claude", "audit.config.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"manifestPath": "docs/audit/audit-plan.json",
                   "executor": {"phaseGateOnly": list(_WP_LEFT)}}, fh)
    mpath = os.path.join(proj, "docs", "audit", "audit-plan.json")
    os.makedirs(os.path.dirname(mpath))
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(man, fh)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = M.main([mpath, "brief", "P1.1", "--role", "writer",
                           "--project", proj])
        except SystemExit as exc:
            code = exc.code
    written = os.path.join(proj, ".claude", "state", "briefs", "P1.1",
                           "20260101T000000Z.writer.md")
    try:
        with open(written, "r", encoding="utf-8", newline="") as fh:
            on_disk = fh.read()
    except OSError:
        on_disk = None
    # The command adds the dependants section the composition alone leaves out;
    # the expected prompt is that composition with the same section, so every
    # other byte is still the measured baseline's (`wp1`).
    phase_one = man["phases"][0]
    deps = M.dependant_lines(M._brief_context(mpath, proj), phase_one["tasks"][0],
                             M.DEPENDANTS_ASK_WRITER)
    expected = "\n".join(M.compose_writer_prompt(
        man, phase_one, phase_one["tasks"][0], deps,
        phase_gate_only=_WP_LEFT)) + "\n"
    check("wp12 `brief P1.1 --role writer` exits 0 and writes exactly the "
          "prompt, with the dependants section, to a file of its own beside "
          "the executor's: code=%r file=%s"
          % (code, "found" if on_disk is not None else "missing"),
          code == M.E_OK and on_disk == expected
          and on_disk.replace("\n\nWho depends on this:\n%s" % (
              "\n".join(deps),), "") == text
          and written in out.getvalue())
    # A key the reader cannot use stops the brief by name; it is not read as the
    # empty default, which would put the browser gates back in the writer's list.
    with open(os.path.join(proj, ".claude", "audit.config.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"manifestPath": "docs/audit/audit-plan.json",
                   "executor": {"phaseGateOnly": "verify.sh"}}, fh)
    os.remove(written)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            bad_code = M.main([mpath, "brief", "P1.1", "--role", "writer",
                               "--project", proj])
        except SystemExit as exc:
            bad_code = exc.code
    check("wp16 a non-list executor.phaseGateOnly stops `brief --role writer` "
          "with the config exit code, naming the key, and writes no brief: "
          "code=%r said=%r"
          % (bad_code, (out.getvalue() + err.getvalue())[:120]),
          bad_code == M.E_CONFIG and not os.path.exists(written)
          and "executor.phaseGateOnly" in out.getvalue() + err.getvalue())
    shutil.rmtree(root, ignore_errors=True)


_DI_FILES = {
    "src/refund.py": "def split_refund(total, lines):\n    return total\n",
    "tests/test_refund.py": "import refund\n",
    "tools/check.sh": "python3 src/refund.py --check\n",
    "src/app.py": "print(split_refund(9, 3))\n",
}
_DI_ASK = "still correct"


def _di_project(root, name, manifest, files):
    """A git checkout holding the plan and `files`, all tracked - the plan too,
    so a scan that read the plan's own fileIndex as a dependant is visible."""
    proj = os.path.join(root, name)
    os.makedirs(os.path.join(proj, ".claude"))
    with open(os.path.join(proj, ".claude", "audit.config.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"manifestPath": "docs/audit/audit-plan.json"}, fh)
    mpath = os.path.join(proj, "docs", "audit", "audit-plan.json")
    os.makedirs(os.path.dirname(mpath))
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)
    for rel, text in files.items():
        path = os.path.join(proj, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    _harness.git(proj, "init", "-q")
    _harness.git(proj, "add", "-A")
    _harness.git(proj, "commit", "-q", "-m", "fixture")
    return proj, mpath


def _di_brief(proj, mpath, role):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = M.main([mpath, "brief", "P1.1", "--role", role,
                           "--project", proj])
        except SystemExit as exc:
            code = exc.code
    name = {"writer": "writer", "executor": "executor",
            "reviewer": "reviewer"}[role]
    path = os.path.join(proj, ".claude", "state", "briefs", "P1.1",
                        "20260101T000000Z.%s.md" % name)
    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            return code, fh.read()
    except OSError:
        return code, ""


def _di_section(text):
    """The `Who depends on this` section's lines, heading excluded - `None`
    when the heading is absent, so an absent section and an empty one differ."""
    lines = text.split("\n")
    # The briefs title it as a `##` heading, the writer's prose prompt as a
    # `Files the task declares:`-style line.
    heads = [i for i, ln in enumerate(lines)
             if ln.lstrip("#").strip().rstrip(":") == "Who depends on this"]
    if len(heads) != 1:
        return None
    body = []
    for ln in lines[heads[0] + 1:]:
        if ln.startswith("#") or (body and not ln.strip()):
            break
        if ln.strip():
            body.append(ln)
    return body


def _dependants_cases(check):
    """The executor's brief, the writer's prompt and the reviewer's brief name
    who depends on the task's files, and the first two ask for an answer per
    dependant."""
    root = _harness.fixture_root("audit-lookup-di-")
    proj, mpath = _di_project(root, "di", _bf_manifest(), _DI_FILES)
    code, text = _di_brief(proj, mpath, "executor")
    body = _di_section(text) or []
    joined = "\n".join(body)
    refund_at = [i for i, ln in enumerate(body) if "src/refund.py" in ln
                 and not ln.startswith(" ")]
    check("di1 the executor brief carries ONE 'Who depends on this' section "
          "listing src/refund.py's tracked dependants from _impact - the shell "
          "step naming its path, the test importing it, the file calling its "
          "function - and NOT the plan that merely indexes it: code=%r %r"
          % (code, body),
          code == M.E_OK and _di_section(text) is not None
          and len(refund_at) == 1
          and "tools/check.sh" in joined and "tests/test_refund.py" in joined
          and "src/app.py" in joined and "split_refund" in joined
          and "audit-plan.json" not in joined)
    asks = [ln for ln in body if _DI_ASK in ln]
    check("di2 the executor brief asks for an answer per listed dependant in "
          "the outcome - still correct (and why) or changed - in ONE line of "
          "the section: %r" % (asks,),
          len(asks) == 1 and "changed" in asks[0] and "why" in asks[0]
          and "outcome" in asks[0])

    wcode, wtext = _di_brief(proj, mpath, "writer")
    wbody = _di_section(wtext) or []
    check("di3 the writer prompt carries the same dependant list and the same "
          "one-line ask: code=%r %r" % (wcode, wbody),
          wcode == M.E_OK and _di_section(wtext) is not None
          and "tools/check.sh" in "\n".join(wbody)
          and "src/app.py" in "\n".join(wbody)
          and sum(1 for ln in wbody if _DI_ASK in ln) == 1)

    rpath = os.path.join(proj, "docs", "audit", "evidence", "returns", "P1.1",
                         "20260101T000000Z.executor.json")
    os.makedirs(os.path.dirname(rpath))
    with open(rpath, "w", encoding="utf-8", newline="") as fh:
        fh.write(_BF_EXEC)
    rcode, rtext = _di_brief(proj, mpath, "reviewer")
    rbody = _di_section(rtext) or []
    check("di4 the reviewer brief carries the same list, so the review can "
          "check each answer, and asks the reviewer to check them rather than "
          "to give them: code=%r %r" % (rcode, rbody),
          rcode == M.E_OK and _di_section(rtext) is not None
          and "tools/check.sh" in "\n".join(rbody)
          and any("check" in ln.lower() and "answer" in ln for ln in rbody))

    alone = _bf_manifest()
    proj_n, mpath_n = _di_project(root, "di-none", alone, {
        "src/refund.py": "X = 1\n", "tests/test_refund.py": "Y = 2\n"})
    ncode, ntext = _di_brief(proj_n, mpath_n, "executor")
    nbody = _di_section(ntext)
    wn_code, wn_text = _di_brief(proj_n, mpath_n, "writer")
    check("di5 a task whose files no tracked file names keeps the section and "
          "says so in ONE line, asking nothing - in the brief and the prompt: "
          "%r / %r" % (nbody, _di_section(wn_text)),
          ncode == M.E_OK and wn_code == M.E_OK
          and nbody is not None and len(nbody) == 1
          and _DI_ASK not in nbody[0] and "could not" not in nbody[0]
          and _di_section(wn_text) == nbody)

    # A task declaring more files than the brief's budget scans.
    many = _bf_manifest()
    count = 30
    pages = ["docs/p%02d.md" % n for n in range(count)]
    many_task = many["phases"][0]["tasks"][0]
    many_task["files"] = pages
    many_task["description"] = "Rewrite the last page, p29.md, first."
    page_files = dict((p, "page\n") for p in pages)
    page_files.update(dict(("refs/r%02d.txt" % n, "see p%02d.md\n" % n)
                           for n in range(count)))
    proj_m, mpath_m = _di_project(root, "di-many", many, page_files)
    mcode, mtext = _di_brief(proj_m, mpath_m, "executor")
    mbody = _di_section(mtext) or []
    cuts = [ln for ln in mbody if "declared files shown; the rest: " in ln]
    command = cuts[0].split("the rest: ", 1)[1] if cuts else ""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        try:
            lcode = M.main([mpath_m, "dependants", "P1.1", "--project", proj_m])
        except SystemExit as exc:
            lcode = exc.code
    listed = [ln for ln in out.getvalue().splitlines() if ln.startswith("- docs/p")]
    check("di6 a task past the brief's budget gets a bounded section that "
          "names the description's file, says how many of the declared files "
          "it shows and gives the command listing the rest; that command (the "
          "`dependants` verb) lists every declared file: code=%r cut=%r "
          "listed=%d" % (mcode, cuts, len(listed)),
          mcode == M.E_OK and len(cuts) == 1
          and ("of %d declared files shown" % (count,)) in cuts[0]
          and "dependants P1.1" in command and mpath_m in command
          and any(ln.startswith("- docs/p29.md") for ln in mbody)
          and lcode == M.E_OK and len(listed) == count
          and len(set(ln.split(":")[0] for ln in listed)) == count)
    _harness.remove_tree(root)


def _selftest():
    def body(check):
        # Each block staged, so one that raises still lets the other run.
        _harness.stage(check, "di-block", _dependants_cases)
        _harness.stage(check, "al-block", _cases)
        _harness.stage(check, "sl-block", _success_line_cases)
        _harness.stage(check, "bf-block", _brief_cases)
        _harness.stage(check, "nl-block", _nested_scope_cases)
        _harness.stage(check, "nm-block", _nested_member_cases)
        _harness.stage(check, "wp-block", _writer_prompt_cases)
        _harness.stage(check, "rq-block", _red_command_reader_cases)
        _harness.stage(check, "ow-block", _owed_red_first_brief_cases)
        _harness.stage(check, "co-block", _conventions_order_cases)
    return _harness.run(body)


def _conventions_order_cases(check):
    """The executor-skills bullet of manifest-conventions.md names the levels in
    the order `_areas.resolve_skills` resolves them, and names all three."""
    import _areas
    manifest = {"meta": {"defaultSkills": ["from-plan"],
                         "areas": {"api": {"skills": ["from-area"]}}}}
    resolved = _areas.resolve_skills(
        manifest, {"id": "P1", "area": "api"},
        {"id": "P1.1", "skills": ["from-task"]})
    path = os.path.join(_output.PLUGIN_ROOT, "reference",
                        "manifest-conventions.md")
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    start = text.find("**Executor skills**")
    end = text.find("\n- ", start + 1) if start >= 0 else -1
    bullet = " ".join(text[start:end if end > start else None].split()) \
        if start >= 0 else ""
    at_plan = bullet.find("meta.defaultSkills")
    at_area = bullet.find("meta.areas[tag].skills")
    at_task = bullet.find("task.skills")
    check("co1 the conventions bullet for executor skills states the three "
          "levels in the order the resolver applies them, plan default then "
          "each tag's area then the task, and no longer calls the area first: "
          "%r" % (bullet,),
          resolved == ["from-plan", "from-area", "from-task"]
          and 0 <= at_plan < at_area < at_task
          and "area first" not in bullet)

    # The brief's Skills section names every level the resolver read when
    # none answered - the plan default included - and an opted-out task is
    # told it opted out rather than that the plan declares nothing.
    bare = {"meta": {}}
    none_line = " ".join(M.skills_lines(bare, {"id": "P1"}, {"id": "P1.1"}))
    opted_line = " ".join(M.skills_lines(
        {"meta": {"defaultSkills": ["from-plan"]}}, {"id": "P1"},
        {"id": "P1.1", "skills": None}))
    listed = M.skills_lines({"meta": {"defaultSkills": ["from-plan"]}},
                            {"id": "P1"}, {"id": "P1.1"})
    check("co2 the brief's Skills section with nothing resolving names the "
          "plan default, the area default and the task's skills; an opted-out "
          "task is told it opted out; a resolving plan default is listed: %r"
          % ((none_line, opted_line, listed),),
          "meta.defaultSkills" in none_line and "area" in none_line
          and "task" in none_line
          and "skills: null" in opted_line
          and "meta.defaultSkills" not in opted_line
          and listed[1:] == ["- from-plan"])


def _red_command_reader_cases(check):
    """The brief's test command after `--` is `_filed_returns.red_command`'s
    answer over the task's resolved gate: one reader, so the brief and the
    drive cannot pick two commands for one task."""
    def plan(gate):
        task = {"id": "P1.1", "tests": {"mode": "tdd", "gate": [gate],
                                        "add": ["tests/test_a.py: a case"]}}
        phase = {"id": "P1", "tasks": [task]}
        return {"meta": {"buildCommands": {}}, "phases": [phase]}, phase, task
    got = []
    for gate in ("python3 tests/test_a.py_old", "python3 tests/test_a.py"):
        manifest, phase, task = plan(gate)
        resolved = M._evio.resolved_commands(manifest, [gate])
        got.append((M.red_command(manifest, phase, task),
                    M._fr.red_command(task, resolved)
                    if hasattr(M._fr, "red_command") else "absent"))
    check("rq1 the brief's red command is _filed_returns.red_command's answer "
          "over the same gate, so a gate naming tests/test_a.py_old gives none "
          "and one naming tests/test_a.py gives it: %r" % (got,),
          got == [(None, None), ("python3 tests/test_a.py", "python3 tests/test_a.py")])


def _owed_red_first_brief_cases(check):
    """The executor's brief asks for a test command after `--` of the task that
    owes a red-first proof, read off the stored `expectRedFirst`: the same tdd
    task with an empty `tests.add` and a gate naming no file, the field being
    all that differs between the two briefs."""
    root = _harness.fixture_root("audit-lookup-ow-")

    def brief_of(name, expect):
        manifest = _bf_manifest()
        tests = manifest["phases"][0]["tasks"][0]["tests"]
        tests.update({"add": [], "gate": ["test"], "expectRedFirst": expect})
        proj = os.path.join(root, name)
        os.makedirs(os.path.join(proj, ".claude"))
        with open(os.path.join(proj, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"manifestPath": "docs/audit/audit-plan.json"}, fh)
        mpath = os.path.join(proj, "docs", "audit", "audit-plan.json")
        os.makedirs(os.path.dirname(mpath))
        with open(mpath, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = M.main([mpath, "brief", "P1.1", "--role", "executor",
                           "--project", proj])
        path = os.path.join(proj, ".claude", "state", "briefs", "P1.1",
                            "20260101T000000Z.executor.md")
        try:
            with open(path, "r", encoding="utf-8", newline="") as fh:
                return code, fh.read()
        except OSError:
            return code, ""

    code_f, unowed = brief_of("ow-false", False)
    code_t, owed = brief_of("ow-true", True)
    submit_f = [ln for ln in unowed.splitlines() if "submit P1.1 --role executor" in ln]
    submit_t = [ln for ln in owed.splitlines() if "submit P1.1 --role executor" in ln]
    check("ow1 the brief of a tdd task whose stored expectRedFirst is false asks "
          "for no test command: the submit block carries no ` -- `, and the "
          "text says the red-first block is the driver's: %r" % (submit_f,),
          code_f == M.E_OK and len(submit_f) == 1 and " -- " not in submit_f[0]
          and "<the command that runs your new test>" not in unowed
          and "owes a test command" not in unowed
          and "no red-first proof is owed" in unowed)
    check("ow2 THE TWIN: the same task with expectRedFirst true is still asked "
          "for the command: %r" % (submit_t,),
          code_t == M.E_OK and len(submit_t) == 1
          and "-- <the command that runs your new test>" in submit_t[0]
          and "owes a test command" in owed)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_audit_lookup.py --selftest\n")
    raise SystemExit(2)
