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
