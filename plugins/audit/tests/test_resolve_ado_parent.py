#!/usr/bin/env python3
"""
The cases for `resolve-ado-parent.py` — the door onto `_ado_parent`.

The rules live in `_ado_parent` and have their own suite; what is pinned HERE is
the door, and its exit-code contract is most of it:

- **"no parent anywhere" is EXIT 0.** Uncategorised work is an answer and a
  create, not an error. A door that exited non-zero over it would be switched
  off inside a day, and `conventions.requireParent` is the board saying
  otherwise — graded where the whole plan can be seen, not here.
- **Unreadable input is 2 and never 1.** Saying "this does not belong" about
  something we could not read is the confident wrong answer, and a caller
  reading 1 as a refusal would stop a push over a typo in a path.
- **A scope naming nothing is 2, not a clean 0.** "Resolved: nothing" about an
  id that does not exist reads exactly like a healthy plan.
- **The hierarchy is computed over the WHOLE plan and the VERDICT is scoped.**
  `rp20` is the case: a loop between two phases is still found when the scope is
  one of them, and `rp22` counts the out-of-scope refusals the report has to
  name rather than drop.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import io
import json
import os
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402

M = _loader.load_script("resolve-ado-parent.py", modname="resolve_ado_parent")

LEVELS = {"Task": 1, "Product Backlog Item": 2, "Feature": 3, "Epic": 4}


def _manifest(ado, phases):
    return {"meta": {"version": "0.3.0", "ado": ado}, "phases": phases,
            "bugs": []}


def _write(tmp, name, obj):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)
    return path


def _run(argv):
    """(exit code, stdout) — the printed answer is half this command's contract."""
    buf, real = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        code = M.main(argv)
    finally:
        sys.stdout = real
    return code, buf.getvalue()


def _cases(check):
    # --- argument parsing, before anything reads a file -----------------------
    check("rp1 no arguments is a usage error, not an accidental pass",
          M.main([]) == 2)
    check("rp2 the default scope is every item, so a caller that forgets to "
          "scope gets the whole plan rather than nothing: %r"
          % (M.parse_args(["m.json"])[0],),
          M.parse_args(["m.json"])[0]["scope"] == "all")
    for _argv, _why in ((["m.json", "--phase"], "a scope flag with no id"),
                        (["m.json", "--nope"], "an unknown flag"),
                        (["--json", "m.json"], "no manifest first")):
        _opts, _err = M.parse_args(_argv)
        check("rp3 %s is refused with a sentence rather than parsed into a "
              "default: %r" % (_why, _err), bool(_err))
    check("rp4 a --phase covers the tasks under it too, because a phase whose "
          "own parent is fine and whose tasks close a loop must not read as "
          "clean",
          M.in_scope({"kind": "task", "id": "P3.1"},
                     {"scope": "phase", "target": "P3"})
          and not M.in_scope({"kind": "task", "id": "P30.1"},
                             {"scope": "phase", "target": "P3"}))

    tmp = tempfile.mkdtemp(prefix="qg-adoparent-")
    try:
        # --- exit 2: the input, and only the input ----------------------------
        check("rp10 an unreadable manifest is exit 2 and NEVER 1 - a 1 would "
              "tell the caller this plan does not belong on the board",
              M.main([os.path.join(tmp, "no-such.json")]) == 2)
        _bad = os.path.join(tmp, "broken.json")
        with open(_bad, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        check("rp11 ...and so is a manifest that parses to nothing",
              M.main([_bad]) == 2)

        # --- exit 0: including the answer that looks like a failure -----------
        _none = _write(tmp, "none.json", _manifest(
            {"phaseWorkItems": False},
            [{"id": "P1", "title": "P1", "status": "pending",
              "tasks": [{"id": "P1.1", "title": "t", "status": "pending"}]}]))
        _code, _out = _run([_none])
        check("rp12 a plan with NO parent anywhere is EXIT 0 - uncategorised "
              "work is an answer and a create, not an error: rc=%d" % (_code,),
              _code == 0)
        check("rp13 ...and it SAYS so, with both counts, rather than printing a "
              "clean line that cannot be told from a plan nobody looked at: %r"
              % (_out.splitlines()[:1],),
              "0 refused" in _out and "2 uncategorised" in _out)
        check("rp14 ...and it names the missing basis for the type check "
              "instead of implying the ranks were consulted",
              "not cached" in _out and "not verified" in _out)

        _fine = _write(tmp, "fine.json", _manifest(
            {"parentWorkItem": 41, "phaseWorkItems": False,
             "types": {"pbi": "Product Backlog Item", "task": "Task"},
             "hierarchy": {"levels": LEVELS, "fetchedAt": "2026-08-24T00:00:00Z",
                           "basis": "captured for this case"}},
            [{"id": "P1", "title": "P1", "status": "pending", "ado": {"id": 800},
              "adoParent": {"id": 41, "type": "Feature"},
              "tasks": [{"id": "P1.1", "title": "t", "status": "pending",
                         "ado": {"id": 801},
                         "adoParent": {"id": 800,
                                       "type": "Product Backlog Item"}}]}]))
        _code, _out = _run([_fine])
        check("rp15 a legitimate ladder is exit 0 with nothing refused and "
              "nothing unverified: rc=%d %r" % (_code, _out.splitlines()[-1:]),
              _code == 0 and "0 refused" in _out and "0 not verified" in _out)
        check("rp16 ...and the cached hierarchy's own basis is printed, so a "
              "stale cache can be spotted rather than trusted: %r"
              % ([x for x in _out.splitlines() if "basis:" in x],),
              "captured for this case" in _out)

        # --- exit 1: a violation, and only in scope ---------------------------
        _loop = _write(tmp, "loop.json", _manifest(
            {"types": {"pbi": "Product Backlog Item"}},
            [{"id": "P1", "title": "P1", "status": "pending", "ado": {"id": 501},
              "adoParent": {"id": 500}, "tasks": []},
             {"id": "P2", "title": "P2", "status": "pending", "ado": {"id": 500},
              "adoParent": {"id": 501}, "tasks": []},
             {"id": "P3", "title": "P3", "status": "pending", "tasks": []}]))
        _code, _out = _run([_loop])
        check("rp17 two phases declaring each other is exit 1: rc=%d" % (_code,),
              _code == 1)
        check("rp18 ...and BOTH are named, counted rather than asserted "
              "present - one refusal would leave the other looking creatable: "
              "%r" % ([x for x in _out.splitlines() if "REFUSED [" in x],),
              len([x for x in _out.splitlines() if "REFUSED [" in x]) == 2)
        check("rp19 ...offline, with no meta.ado.hierarchy anywhere in that "
              "manifest - the structural tier needs no cache and no network",
              "not cached" in _out)
        _code, _out = _run([_loop, "--phase", "P1"])
        check("rp20 the loop is still found when the scope is ONE of the two "
              "phases, because a loop is a property of the graph and not of the "
              "item asked about: rc=%d" % (_code,),
              _code == 1)
        check("rp21 ...and the scope narrows the REPORT to that phase: %r"
              % ([x for x in _out.splitlines() if " -> " in x],),
              len([x for x in _out.splitlines() if " -> " in x]) == 1)
        # The bug this file found on the way: the printed refusals and the exit
        # code came from two separate walks, so a scoped run could exit 1 over a
        # loop it did not print. One walk, narrowed - and the case counts.
        check("rp28 ...and what it PRINTS as refused is what it exited over - "
              "one walk narrowed, never a second walk over the scoped rows: %r"
              % ([x for x in _out.splitlines() if "REFUSED [" in x],),
              len([x for x in _out.splitlines() if "REFUSED [" in x]) == 1
              and "1 refused" in _out)
        check("rp22 ...and the refusal it did NOT ask about is counted and "
              "named rather than dropped: %r"
              % ([x for x in _out.splitlines() if "outside this scope" in x],),
              "outside this scope: 1 refusal(s)" in _out and "P2" in _out)
        _code, _out = _run([_loop, "--phase", "P3"])
        check("rp23 ...and a phase that is clean stays exit 0 even while the "
              "plan around it is not - the verdict answers the question that "
              "was asked: rc=%d" % (_code,),
              _code == 0 and "outside this scope: 2 refusal(s)" in _out)
        check("rp24 a scope naming nothing is exit 2, not a clean 0 - "
              "'resolved: nothing' about an id that does not exist reads "
              "exactly like a healthy plan",
              M.main([_loop, "--phase", "P9"]) == 2
              and M.main([_loop, "--task", "P9.9"]) == 2)

        # --- --json carries the same verdict ----------------------------------
        _code, _out = _run([_loop, "--json"])
        _doc = json.loads(_out)
        check("rp25 --json exits with the SAME code as the printed form, so a "
              "script and a person cannot disagree about a board: rc=%d"
              % (_code,),
              _code == 1 and len(_doc["refusals"]) == 2)
        _code, _out = _run([_none, "--json"])
        _doc = json.loads(_out)
        check("rp26 ...and it carries `checked` so a consumer can tell 'nothing "
              "was wrong' from 'nothing was looked at': %r" % (_doc["checked"],),
              _code == 0 and _doc["checked"] == 0 and _doc["rows"])

        # --- the inert declaration reaches the operator -----------------------
        _inert = _write(tmp, "inert.json", _manifest(
            {"types": {"pbi": "Product Backlog Item"}},
            [{"id": "P1", "title": "P1", "status": "pending", "ado": {"id": 700},
              "tasks": [{"id": "P1.1", "title": "t", "status": "pending",
                         "adoParent": {"id": 900}}]}]))
        _code, _out = _run([_inert])
        check("rp27 a task's adoParent under phaseWorkItems is reported as "
              "INERT rather than silently ignored, and the run still exits 0 "
              "because nothing about it is unbuildable: rc=%d" % (_code,),
              _code == 0
              and len([x for x in _out.splitlines()
                       if x.startswith("WARNING:") and "INERT" in x]) == 1)
    finally:
        for name in sorted(os.listdir(tmp)):
            os.remove(os.path.join(tmp, name))
        os.rmdir(tmp)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_resolve_ado_parent.py --selftest\n")
    raise SystemExit(2)
