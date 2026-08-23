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

import contextlib
import io
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


def _write(tmp, manifest, name="audit-plan.json"):
    """One manifest on disk; the door reads a PATH, not a dict."""
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)
    return path


def _run(argv):
    """`main(argv)` with stdout captured - (exit code, what it printed)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = M.main(argv)
    return code, buf.getvalue()


def _cells(line):
    """One printed row with the column padding collapsed, so ORDER is what is
    compared and column widths (which move with the longest value) are not."""
    return " ".join(line.split())


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

        # ---- the `list` table: printed by the script, not remembered ----
        # F91. This subcommand was the one `propose.md` described in prose and
        # rendered from prose, so what a user got was whatever the model recalled
        # - which, live, was an accurate SUMMARY and no table at all. The columns
        # below are `propose.md`'s own, in its order.
        lpath = _write(tmp, _manifest(
            [_prop("PROP-1", payload=_payload("P5", tasks=("a", "b")),
                   openQuestions=["ship it?"]),
             _prop("PROP-2", payload=None),
             _prop("PROP-3", "materialized", _payload("P1"),
                   materializedAs="P1"),
             _prop("PROP-4", "dropped", _payload("P8"), notes="dupe")],
            phases=[{"id": "P1", "tasks": []}]), name="list-plan.json")
        code, txt = _run([lpath, "list"])
        heads = [ln for ln in txt.split("\n") if ln.startswith("id ")]
        check("mz35 the header names every column propose.md specifies, in that "
              "order and exactly once: %r" % (heads,),
              code == 0 and len(heads) == 1
              and _cells(heads[0]) == "id status reserved phase (task count) "
                                      "name openQuestions")
        body = dict((ln.split()[0], _cells(ln)) for ln in txt.split("\n")
                    if ln.startswith("PROP-"))
        check("mz36 a payload-bearing row renders the reserved phase WITH its "
              "task count, the name, and the open questions: %r"
              % (body.get("PROP-1"),),
              body.get("PROP-1") == "PROP-1 proposed P5 (2 tasks) n PROP-1 "
                                    "ship it?")
        check("mz37 ...and a legacy free-form entry renders `-` for the payload "
              "column while still being LISTED - the row vanishing is the one "
              "failure a list must not have: %r" % (body.get("PROP-2"),),
              body.get("PROP-2") == "PROP-2 proposed - n PROP-2 -")
        check("mz38 the default hides materialized/dropped history and SAYS it "
              "did, rather than reading as 'that is all of them': %r" % (txt,),
              sorted(body) == ["PROP-1", "PROP-2"]
              and "materialized/dropped record(s) not shown" in txt
              and "list all" in txt)
        _c2, txt2 = _run([lpath, "list", "all"])
        check("mz39 ...and `all` adds the history rather than replacing the list",
              _c2 == 0
              and sorted(ln.split()[0] for ln in txt2.split("\n")
                         if ln.startswith("PROP-"))
              == ["PROP-1", "PROP-2", "PROP-3", "PROP-4"])
        _c3, txt3 = _run([lpath, "list", "--json"])
        check("mz40 `--json` prints ONE document and the same ids the table did",
              _c3 == 0
              and [r["id"] for r in json.loads(txt3)["rows"]]
              == ["PROP-1", "PROP-2"])
        with open(lpath, "r", encoding="utf-8") as fh:
            check("mz41 ...and listing writes nothing: `list` is read-only and "
                  "takes no lock", len(json.load(fh)["proposals"]) == 4)

        # Empty is a RESULT, and which empty it is decides what to do next.
        epath = _write(tmp, _manifest([]), name="empty-plan.json")
        _c4, txt4 = _run([epath, "list"])
        check("mz42 an empty result with no phases either points at /audit:init, "
              "because 'nothing parked' and 'no plan to park anything in' read "
              "alike and need different advice: %r" % (txt4,),
              _c4 == 0 and "no proposals" in txt4 and "/audit:init" in txt4)
        ppath = _write(tmp, _manifest([], phases=[{"id": "P0", "tasks": []}]),
                       name="planned-empty.json")
        _c5, txt5 = _run([ppath, "list"])
        # The other direction, and it is the case that would be cut in review: it
        # passes on any build where the pointer is missing entirely, and fails
        # only when the pointer becomes unconditional.
        check("mz43 ...while a plan that HAS phases and no proposals says so "
              "without sending the reader to /audit:init: %r" % (txt5,),
              _c5 == 0 and "no proposals" in txt5 and "/audit:init" not in txt5)
        check("mz44 an argument `list` does not understand is a usage error "
              "rather than a silent default listing",
              M.main([lpath, "list", "alll"]) == 2)
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
