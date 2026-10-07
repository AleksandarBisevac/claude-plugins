#!/usr/bin/env python3
"""
The cases for `_filed_returns.py` - where a filed return lives, the shape each
role owes, the write-once create and the read.

WHAT IS PINNED, and why each one is here rather than trusted:

- **The shape is the brief's.** `fr6` reads the field list off
  `agents/audit-executor.md`'s own return block and deletes each declared field
  in turn, so a field the brief grows is one the check must refuse the absence
  of; `fr7` holds the red-first words equal to the schema enum. Neither keeps a
  second copy of what it compares.
- **Both directions.** Every refusal sits beside the whole return that files, so
  a check refusing everything fails here as surely as one refusing nothing.
- **A start is part of the path.** Two starts of one task read two files; a
  return under an earlier start is never this start's.
- **A file that will not parse is a problem, never an absence.**

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import json
import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _output                                     # noqa: E402  (PLUGIN_ROOT, the agent briefs)
import _refs                                       # noqa: E402  (the brief's return block, the schema enum)
import _filed_returns as M                         # noqa: E402

_START = "2026-01-01T00:00:00Z"


def _executor(**over):
    body = {"gates": {"python3 t.py": "pass"},
            "redFirst": {"status": "proved", "basis": "the run exited non-zero on its own case",
                         "at": "z"},
            "outcome": {"technical": "t", "descriptive": "d"},
            "testsAdded": ["one"], "stamp": "audit-stamp: v2 x"}
    body.update(over)
    return body


def _reviewer(answer="matches"):
    return {"findings": [], "intent": {"answer": answer}, "verdict": "clean"}


def _cases(check):
    root = _harness.fixture_root("filed-returns-")
    task = {"id": "P1.1", "startedAt": _START}

    check("rp1 the path is `returns/<task>/<start>.<role>.json`, the start "
          "spelled with letters and digits only: %r"
          % (M.return_rel("P1.1", _START, "executor"),),
          M.return_rel("P1.1", _START, "executor")
          == "returns/P1.1/20260101T000000Z.executor.json")
    later = dict(task, startedAt="2026-01-02T00:00:00Z")
    check("rp2 two starts of one task are two paths, and a task with no start "
          "has none - so an earlier start's return is never read as this one's",
          M.return_path(root, task, "executor")
          != M.return_path(root, later, "executor")
          and M.return_path(root, {"id": "P1.1"}, "executor") is None
          and M.return_path(root, task, "executor").startswith(root))

    # ---- the shape ----------------------------------------------------------
    with open(os.path.join(_output.PLUGIN_ROOT, "agents", "audit-executor.md"),
              "r", encoding="utf-8") as fh:
        block = _refs._return_block(fh.read()) or ""
    keys = _refs._return_keys(block)
    optional = [k for k in keys if '"%s": "optional:' % (k,) in block]
    unnamed = []
    for key in keys:
        if key in optional:
            continue
        body = _executor()
        body.pop(key, None)
        if not any("`%s" % (key,) in p for p in M.return_problems("executor", body)):
            unnamed.append(key)
    check("fr6 every field agents/audit-executor.md declares is one the check "
          "refuses the absence of, BY NAME - the keys read off the brief, so a "
          "field it grows is demanded here too; and a whole return has no "
          "problem: %r" % ((keys, optional, unnamed),),
          len(keys) >= 5 and unnamed == []
          and M.return_problems("executor", _executor()) == [])
    enum, problem = _refs._red_first_enum(_refs.REPO_ROOT)
    check("fr7 the red-first words are the schema's enum, in its order - the "
          "plugin runs from an installed copy where the schema is not where the "
          "lint reads it, so this tuple is kept here and this case keeps it from "
          "being a second vocabulary: %r" % ((M.RED_FIRST_WORDS, enum, problem),),
          problem is None and list(M.RED_FIRST_WORDS) == enum)
    bad_red = M.return_problems("executor", _executor(
        redFirst={"status": "not-proved", "basis": ""}))
    check("rp3 an executor word outside the vocabulary - the reviewer's own "
          "`not-proved` included - and an empty basis are each named: %r"
          % (bad_red,),
          any("not-proved" in p for p in bad_red)
          and any("redFirst.basis" in p for p in bad_red))
    check("rp4 the reviewer's shape: a word outside the three answers and a "
          "verdict outside its two are named, and a whole return files: %r"
          % (M.return_problems("reviewer", {"findings": [],
                                            "intent": {"answer": "yes"},
                                            "verdict": "ok"}),),
          len(M.return_problems("reviewer", {"findings": [],
                                             "intent": {"answer": "yes"},
                                             "verdict": "ok"})) == 2
          and M.return_problems("reviewer", _reviewer()) == [])
    check("rp5 a role the module does not know, or a body that is not an "
          "object, is a problem and never a pass",
          M.return_problems("phase", _reviewer()) != []
          and M.return_problems("executor", ["not", "an", "object"]) != [])
    check("rp6 `claims` is optional text: absent files, a non-text value is "
          "named",
          M.return_problems("executor", _executor()) == []
          and any("claims" in p for p in
                  M.return_problems("executor", _executor(claims=["x"]))))

    # ---- the write and the read ----------------------------------------------
    path = M.return_path(root, task, "executor")
    first = json.dumps(_executor(claims="claims:\n1 n/a")) + "\n"
    M.file_once(path, first)
    raised = False
    try:
        M.file_once(path, "{}")
    except FileExistsError:
        raised = True
    with open(path, "r", encoding="utf-8", newline="") as fh:
        kept = fh.read()
    check("rp7 the create is exclusive: a second write to one path raises and "
          "the first stays byte-identical", raised and kept == first)
    text, body, why = M.read_filed_return(path)
    none = M.read_filed_return(M.return_path(root, later, "executor"))
    check("rp8 a filed return reads back verbatim and parsed; one not filed "
          "reads as three Nones", text == first and body.get("stamp")
          and why is None and none == (None, None, None))
    broken = M.return_path(root, {"id": "P1.2", "startedAt": _START}, "executor")
    M.file_once(broken, "{not json")
    check("rp9 a file that is there and will not parse is a PROBLEM, never read "
          "as not filed: %r" % (M.read_filed_return(broken)[2],),
          M.read_filed_return(broken)[2] is not None
          and M.claims_from_return(root, {"id": "P1.2", "startedAt": _START})[1]
          is not None)
    claims, problem = M.claims_from_return(root, task)
    check("rp10 `claims_from_return` hands back the current start's `claims` "
          "verbatim, and None for a start with no return or a return without "
          "the field: %r" % (claims,),
          claims == "claims:\n1 n/a" and problem is None
          and M.claims_from_return(root, later) == (None, None)
          and M.claims_from_return(root, {"id": "P1.1"}) == (None, None))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__filed_returns.py --selftest\n")
    raise SystemExit(2)
