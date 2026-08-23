#!/usr/bin/env python3
"""
The cases for `_journal_io.py` — the audit trail library, and the boundary that made it one.

`audit-journal.py`'s own cases live in `test_audit_journal.py` and run over these
same functions through that command's aliases; they are not repeated here. What
this file asserts is what that suite structurally cannot: that there is ONE
implementation of the row shape and the chain, that `audit-journal.py` re-exports
rather than copies, and that the module is small enough to be what
`hooks/_config.py` loads on every tool call — which was half the reason it came
down to layer 1.

THE MONKEYPATCH LESSON LIVES NEXT DOOR AND IS WORTH KNOWING HERE TOO. k5-k8 in
`test_audit_journal.py` swap `_git_anchor_finding` for a counting stub. The stub
has to be installed on the module that DEFINES `verify` — this one — because
`verify` looks the name up as a global of its own module. It was installed on the
command instead when the split happened, k5 (which asserts an empty call list)
went green while measuring nothing, and k6 (which asserts a non-empty one) is what
caught it. That is the second time the same bug has happened to that pair.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import os
import shutil
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _journal_io as M                            # noqa: E402

_CMD = _loader.load_script("audit-journal.py", modname="audit_journal_boundary")


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- the boundary ---------------------------------------------------------
    _shared = ("ROW_VERSION", "DETAILS_VERSION", "DETAILS_KEYS", "CHANGE_KEYS",
               "MAX_CHANGES", "MAX_VALUE_CHARS", "MAX_DETAILS_BYTES",
               "DEFAULT_DIRNAME", "ARCHIVE_DIRNAME", "DEFAULT_MANIFEST",
               "GENESIS", "LOCK_STALE_SECONDS", "LOCK_WAIT_SECONDS",
               "load_config", "enabled", "journal_dir", "in_journal", "canonical",
               "row_hash", "genesis_prev", "file_hash", "writer_id", "month_of",
               "file_for", "read_file", "journal_files", "read_all",
               "normalise_details", "append", "verify", "_normalise", "_append",
               "_git_status_sets", "_git_anchor_finding")
    _forked = sorted(n for n in _shared
                     if getattr(_CMD, n, None) is not getattr(M, n))
    check("b1 audit-journal.py re-exports all %d shared names as THIS module's "
          "own objects - not one is a second implementation: %r"
          % (len(_shared), _forked), _forked == [])
    _missing = sorted(n for n in _shared if not hasattr(_CMD, n))
    check("b2 ...and every one is actually present on audit-journal.py, so b1 "
          "cannot pass over a list that quietly got shorter: %r" % (_missing,),
          _missing == [])
    check("b3 `verify` is DEFINED here, not merely reachable from here - which "
          "is the fact k5-k8 next door depend on when they install a stub, and "
          "the one that silently stopped being true of `audit-journal.py`",
          M.verify.__module__ == M.__name__
          and _CMD.verify.__module__ == M.__name__)
    check("b4 the subcommands and `main` stayed with the command - what came "
          "down is the trail, not the CLI",
          callable(getattr(_CMD, "main", None)) and not hasattr(M, "main")
          and hasattr(_CMD, "cmd_verify") and not hasattr(M, "cmd_verify"))
    check("b5 ...and neither did argparse. hooks/_config.py resolves this file "
          "by path on every tool call to ask one question (`journal_dir`); an "
          "argument parser it never calls is pure startup cost",
          not hasattr(M, "argparse") and hasattr(_CMD, "argparse"))

    # --- where a journal lives (the question the hook asks) -------------------
    tmp = tempfile.mkdtemp(prefix="audit-journal-io-")
    try:
        proj = os.path.join(tmp, "repo")
        os.makedirs(os.path.join(proj, "docs", "audit"))
        cfg = {"manifestPath": "docs/audit/audit-plan.json"}
        check("d1 the journal sits beside the manifest, derived rather than "
              "hardcoded - a repo that moved its plan must not leave the record "
              "of it somewhere else",
              M.journal_dir(proj, cfg)
              == os.path.join(proj, "docs", "audit", "journal"))
        check("d2 journal.dir overrides it",
              M.journal_dir(proj, {"journal": {"dir": "trail"}})
              == os.path.join(proj, "trail"))
        check("d3 enabled defaults true, an explicit false is honoured, and a "
              "NON-BOOL is ignored rather than trusted",
              M.enabled({}) is True
              and M.enabled({"journal": {"enabled": False}}) is False
              and M.enabled({"journal": {"enabled": "false"}}) is True)

        # --- the chain --------------------------------------------------------
        p1 = M.append(proj, {"action": "task.start", "target": "P1.1",
                             "actor": {"sessionId": "s1"}}, config=cfg)
        check("c1 append reports the PATH it wrote, not a bare True - the "
              "journal-writes hook records it so guard-bash-writes can tell the "
              "plugin's own append from a shell write",
              isinstance(p1, str) and os.path.isfile(p1), repr(p1))
        M.append(proj, {"action": "task.done", "target": "P1.1",
                        "actor": {"sessionId": "s1"}}, config=cfg)
        rows, torn = M.read_file(p1)
        check("c2 the second row chains to the first, and neither is torn",
              len(rows) == 2 and rows[1]["prev"] == rows[0]["hash"] and not torn)
        check("c3 the first row's prev is derived from the FILE NAME, so a file "
              "cannot be renamed into another writer's slot and still verify",
              rows[0]["prev"] == M.genesis_prev(os.path.basename(p1)))
        res = M.verify(proj, cfg)
        check("c4 a clean chain verifies", res["ok"] and res["rows"] == 2
              and not res["findings"], repr(res["findings"]))

        # The fixture that separates a real chain check from one that only counts
        # rows: the forged row is well-formed JSON with a plausible shape, so
        # anything less than recomputing the hash would accept it.
        with open(p1, "a", encoding="utf-8") as fh:
            fh.write(M.canonical({"v": 1, "ts": rows[1]["ts"],
                                  "action": "task.done", "target": "P1.1",
                                  "actor": rows[1]["actor"], "summary": "",
                                  "stateHash": None, "prev": rows[1]["hash"],
                                  "hash": "0" * 64}) + "\n")
        res = M.verify(proj, cfg)
        check("c5 a forged row - valid JSON, right shape, right `prev`, wrong "
              "hash - is a FINDING. A check that only walked `prev` links would "
              "pass this fixture",
              not res["ok"] and res["findings"], repr(res["findings"])[:200])

        check("c6 append() never raises, even into a directory it cannot use: a "
              "save that SUCCEEDED must not be reported as failed because the "
              "journal was unwritable",
              M.append(os.path.join(tmp, "nope", "deeper"),
                       {"action": "x", "target": "y"},
                       config={"journal": {"dir": "\0bad"}}) is False)

        check("v1 verify on a project with no journal is not a failure - "
              "'there is nothing to check' and 'the chain is broken' are "
              "different answers and must not print the same way",
              M.verify(os.path.join(tmp, "empty"))["exists"] is False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # --- the row shape --------------------------------------------------------
    row = M._normalise({"action": "config.write", "target": ".claude/x.json"})
    check("n1 a normalised row carries the contract's fields and nothing invented",
          set(row) >= {"v", "ts", "action", "target", "summary", "actor"},
          repr(sorted(row)))
    check("n2 canonical() is stable across key order, which is what makes a hash "
          "over it mean anything",
          M.canonical({"b": 1, "a": 2}) == M.canonical({"a": 2, "b": 1}))
    check("n3 details are bounded: a value is evidence, not a payload",
          len(M.normalise_details({"changes": [{"id": "1", "field": "f",
                                                "from": "x" * 500,
                                                "to": "y"}]})["changes"][0]["from"])
          <= M.MAX_VALUE_CHARS + 8)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__journal_io.py --selftest\n")
    raise SystemExit(2)
