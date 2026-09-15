#!/usr/bin/env python3
"""
The cases for `governance/propose-gates.py` - a plan proposal that reads what
history actually ran, and says so, rather than guessing from the tree in silence.

THE CONFIDENT FAILURE MODE IS THE ONE EVERY CASE IS AIMED AT: a manifest with no
recorded runs must say `basis: "tree"` for every entry, never blend a repo that
has SOME history into a claim about a command it has never itself seen run. `pg5`
is the case that goes red if that blending creeps in - a repo with real history
for one command and none for another must tell the two apart per entry, not per
project.

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
import _evidence_io                                 # noqa: E402

M = _loader.load_script("propose-gates.py", modname="propose_gates")


def _project(root):
    os.makedirs(os.path.join(root, ".claude"), exist_ok=True)
    return root


def _row(ts, run_id, steps):
    return {"v": 1, "runId": run_id, "ts": ts, "scope": "task",
            "taskId": "P1.1", "phaseId": "P1", "status": "passed",
            "steps": steps, "failed": []}


def _cases(check):
    tmp = _harness.fixture_root("propose-gates-")
    try:
        project = _project(tmp)
        manifest_path = os.path.join(project, "docs", "audit", "audit-plan.json")

        # pg1: nothing has ever run here - every entry reads `tree`, and the
        # repo-wide flag says so once rather than leaving a reader to re-derive
        # it from re-scanning every entry.
        result = M.propose(manifest_path, ["npm test", "npm run lint"])
        check("pg1 a manifest with no recorded runs proposes every candidate "
              "from the tree and SAYS that is what it did: %r" % (result,),
              result["historyAvailable"] is False
              and all(e["basis"] == "tree" and e["claim"] == "tree"
                      for e in result["entries"]))

        # A run BELOW the floor for "npm test" - real evidence, not enough of it.
        _evidence_io.append_row(project, _row("2026-01-01T00:00:00Z", "r1",
            [{"name": "test", "command": "npm test", "exit": 0}]))
        result = M.propose(manifest_path, ["npm test"])
        check("pg2 history thinner than the floor is reported as insufficient, "
              "never rounded up into never-failed just because nothing has "
              "failed YET: %r" % (result["entries"][0],),
              result["historyAvailable"] is True
              and result["entries"][0]["basis"] == "history"
              and result["entries"][0]["claim"] == "insufficient"
              and result["entries"][0]["ranTotal"] == 1)

        # Past the floor, and every run passed.
        _evidence_io.append_row(project, _row("2026-01-02T00:00:00Z", "r2",
            [{"name": "test", "command": "npm test", "exit": 0}]))
        result = M.propose(manifest_path, ["npm test"])
        check("pg3 a command that has run at or past the floor and never "
              "failed is a candidate FOR REMOVAL: %r" % (result["entries"][0],),
              result["entries"][0]["claim"] == "never-failed"
              and result["entries"][0]["ranTotal"] == 2
              and result["entries"][0]["failed"] == 0)

        # A failing run for a DIFFERENT command.
        _evidence_io.append_row(project, _row("2026-01-03T00:00:00Z", "r3",
            [{"name": "lint", "command": "npm run lint", "exit": 1}]))
        _evidence_io.append_row(project, _row("2026-01-04T00:00:00Z", "r4",
            [{"name": "lint", "command": "npm run lint", "exit": 0}]))
        result = M.propose(manifest_path, ["npm run lint"])
        check("pg4 a command that has failed before is a candidate FOR EVERY "
              "PLAN, not a removal candidate: %r" % (result["entries"][0],),
              result["entries"][0]["claim"] == "catches-things"
              and result["entries"][0]["failed"] == 1)

        # pg5: THE OVER-FIRE CASE. This project now has real history for
        # "npm test" and "npm run lint" - a candidate this repo has never run
        # under ANY spelling must still read `tree`, never borrow the repo's
        # historyAvailable flag into a per-entry claim it has no rows for.
        result = M.propose(manifest_path,
                           ["npm test", "npm run typecheck"])
        typecheck = [e for e in result["entries"]
                    if e["command"] == "npm run typecheck"][0]
        check("pg5 a candidate with no rows of its own reads `tree` even in a "
              "project with real history for OTHER commands - the widening "
              "this proposal must never do: %r" % (typecheck,),
              result["historyAvailable"] is True
              and typecheck["basis"] == "tree"
              and typecheck["claim"] == "tree")

        # The human render names both halves for a mixed result.
        lines = M.render_human(result)
        check("pg6 the human render spells the tree-only note differently "
              "from the history line, so a reader is never left guessing "
              "which basis a line drew from: %r" % (lines,),
              any("tree only" in ln for ln in lines)
              and any("history, ran" in ln for ln in lines))

        # --json / usage-error surface, over main() rather than over propose()
        # directly - this is the shape /audit:init's recon step actually calls.
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = M.main([manifest_path, "--command", "npm test", "--json"])
        payload = json.loads(out.getvalue())
        check("pg7 --json prints the same shape propose() returns, over main() "
              "rather than only over the library call",
              rc == M.E_OK and payload["entries"][0]["command"] == "npm test")

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = M.main([manifest_path])
        check("pg8 no --command at all is a usage error, not a silent empty "
              "report - a caller that forgot the flag learns that immediately",
              rc == M.E_USAGE and "--command" in err.getvalue())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_propose_gates.py --selftest\n")
    raise SystemExit(2)
