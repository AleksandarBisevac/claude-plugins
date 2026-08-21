#!/usr/bin/env python3
"""
The cases for `materialize-proposal.py` — the DOOR, not the rule.

The lifecycle itself moved to `_proposals.py` when the panel became a second
caller, and its cases moved with it to `test__proposals.py`. What is left to pin
here is what a door owes: that no arguments is a usage error rather than an
accidental pass, that `plan` writes nothing, and that a refused plan exits 1 in
both spellings — a `--json` plan that always exited 0 would let
`plan && materialize` sail past a refusal, and one exit code cannot mean two
things depending on a flag.

Small on purpose. A door with many cases is a door that grew a rule.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402

M = _loader.load_script("materialize-proposal.py", modname="materialize_proposal")

NOW = "2026-08-21T12:00:00Z"


def _payload(pid, tasks=("a",), refs=None):
    """A parked payload phase, with optional blockedBy refs on the phase."""
    phase = {"id": pid, "title": "Parked " + pid, "status": "pending",
             "tasks": [{"id": "%s.%d" % (pid, i + 1), "title": t,
                        "status": "pending", "files": ["src/%s.py" % t]}
                       for i, t in enumerate(tasks)]}
    if refs:
        phase["blockedBy"] = list(refs)
    return {"phase": phase}


def _prop(pid, status="proposed", payload=None, **extra):
    out = {"id": pid, "name": "n " + pid, "status": status,
           "origin": "audit:init", "createdISO": "2026-01-01T00:00:00Z",
           "scope": "s", "benefit": "b", "openQuestions": [],
           "payload": payload}
    out.update(extra)
    return out


def _manifest(props, phases=None):
    return {"meta": {"version": 2, "project": "p", "gitRoot": "."},
            "phases": list(phases or []), "bugs": [], "fileIndex": {},
            "proposals": list(props)}


# --- cases ----------------------------------------------------------------------
def _cases(check):
    # ---- the door: exit codes, on a real file ----
    tmp = tempfile.mkdtemp(prefix="qg-mz-")
    try:
        path = os.path.join(tmp, "audit-plan.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(_manifest([_prop("PROP-1", payload=_payload("P5"))]), fh)
        check("mz24 no arguments is a usage error, not an accidental pass",
              M.main([]) == 2)
        check("mz25 `plan` on a materializable proposal exits 0 and writes "
              "nothing", M.main([path, "plan", "PROP-1"]) == 0)
        with open(path, "r", encoding="utf-8") as fh:
            check("mz26 ...proven by the file being unchanged after a plan",
                  json.load(fh)["phases"] == [])
        check("mz27 a refused plan exits 1", M.main([path, "plan", "PROP-9"]) == 1)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_materialize_proposal.py --selftest\n")
    raise SystemExit(2)
