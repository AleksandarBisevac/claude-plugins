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

import hashlib
import os
import platform
import shutil
import sys
import tempfile
import time

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


        # --- r: what a committed row is allowed to say ------------------------
        # A user found their own user name and their whole directory layout in a
        # COMMITTED row of this trail (CWE-532). The journal is committed on
        # purpose -- `_doctor_trail` warns when it is not -- so these are not log
        # lines that rotate away; they are artifacts that ship to whoever gets the
        # repository. Every case below is about the write side, because the hash
        # is computed immediately after and a committed row can never be corrected
        # without breaking `verify()` on every clone.
        _user = "aleksandarbisevac"
        _leak = ("SCRATCH=/private/tmp/claude-501/-Users-%s-Desktop-personal-"
                 "lisje-memento-4f2a/scratchpad/probe.py python3 probe.py" % _user)
        _leak_cwd = "/private/tmp/claude-501/-Users-%s-Desktop-personal" % _user

        _d1 = M.normalise_details({"command": "npm ci", "taskId": "P1.1"},
                                  project=proj)
        check("r1 a details block carrying a command stores a DIGEST and not the "
              "command - the allow-list is what closes the channel, so no writer "
              "can put command text in a row by mistake or on purpose: %r"
              % (sorted(_d1),),
              "command" not in _d1 and len(_d1["commandSha256"]) == 64
              and _d1["taskId"] == "P1.1")

        # LOOKS VACUOUS, IS NOT. It is the second-direction mutation: a splice
        # written unconditionally would pass r1 forever while stamping a digest of
        # the empty string onto every task.move and config.edit row in the trail.
        # This is the only case that fails when the branch becomes a blanket.
        _d2 = M.normalise_details({"taskId": "P1.1"}, project=proj)
        check("r2 a details block with NO command gains no digest, no byte count "
              "and no program - a row about the plan says nothing about a shell: "
              "%r" % (sorted(_d2),),
              set(_d2) == {"taskId"})

        _long = "echo " + ("y" * 400)
        _d3 = M.normalise_details({"command": _long}, project=proj)
        _whole = hashlib.sha256(_long.encode("utf-8")).hexdigest()
        _clipped = hashlib.sha256(
            _long[:M.MAX_VALUE_CHARS].encode("utf-8")).hexdigest()
        check("r3 the digest is of the command AS RECEIVED, never of the clipped "
              "form - a digest of a truncated command answers a different "
              "question from the one its reader believes they are asking, and "
              "afterwards the two are indistinguishable",
              _d3["commandSha256"] == _whole and _whole != _clipped
              and _d3["commandBytes"] == len(_long))

        # THE ROW THAT STARTED THIS, counted over the WHOLE canonical row rather
        # than asserted absent from one field: the leak was in `details.command`,
        # and a fix that moved it into `summary`, into `program` or into the file
        # name would pass any per-field assertion.
        _scratch = M._normalise(
            {"action": "bash.unsandboxed", "target": "",
             "summary": "Bash ran outside the harness sandbox",
             "details": {"command": _leak, "cwd": _leak_cwd},
             "actor": {"via": "hook", "host": "MacBook-Pro.local"}},
            project=proj)
        _text = M.canonical(_scratch)
        _counts = dict((frag, _text.count(frag))
                       for frag in (_user, "/private/tmp", "-Users-",
                                    "MacBook-Pro", "SCRATCH"))
        check("r4 the reported row, normalised, holds ZERO occurrences of the "
              "user name, of the temp root, of the dash-joined home spelling and "
              "of the machine name: %r" % (_counts,),
              set(_counts.values()) == set([0]))

        check("r5 `program` is the first token only when it is plainly a program "
              "name; the leaking row's first token is a shell assignment whose "
              "value is an absolute path, so it becomes the safe constant rather "
              "than the whole leak in the one field meant to be safe: %r"
              % (M.program_token(_leak),),
              M.program_token("pnpm test --filter api") == "pnpm"
              and M.program_token(_leak) == M.UNNAMED_PROGRAM
              and M.program_token("/usr/local/bin/node app.js")
              == M.UNNAMED_PROGRAM
              and M.program_token("") == M.UNNAMED_PROGRAM)

        # The fixture is chosen so the two spellings DISAGREE: over pure ASCII a
        # character count and a byte count are the same number, and the case would
        # pass against either implementation.
        _cafe = "brew install caf\u00e9"
        _d6 = M.normalise_details({"command": _cafe}, project=proj)
        check("r6 `commandBytes` counts UTF-8 BYTES, which is what was hashed - "
              "not characters: %r vs %r"
              % (_d6["commandBytes"], len(_cafe)),
              _d6["commandBytes"] == len(_cafe.encode("utf-8"))
              and _d6["commandBytes"] != len(_cafe))

        _outside = M.repo_relative_or_token(proj, _leak_cwd)
        check("r7 a cwd inside the repo becomes repo-relative, the root itself "
              "becomes `.`, and anything outside becomes EXACTLY the token - with "
              "no part of the path body surviving into it: %r" % (_outside,),
              M.repo_relative_or_token(proj, os.path.join(proj, "docs", "audit"))
              == "docs/audit"
              and M.repo_relative_or_token(proj, proj) == "."
              and _outside == M.OUTSIDE_TOKEN
              and _outside.count(_user) == 0)

        check("r8 a cwd that cannot be resolved at all lands on the token and "
              "NEVER on the input - `within_root` answers True when it cannot "
              "tell, which is right for a gate and exactly backwards here",
              M.repo_relative_or_token(None, "/Users/%s/x" % _user)
              == M.OUTSIDE_TOKEN
              and M.repo_relative_or_token(proj, "/private/tmp/\0/-Users-%s"
                                           % _user) == M.OUTSIDE_TOKEN
              and M.repo_relative_or_token(proj, "") == M.OUTSIDE_TOKEN)

        # CLIP ORDERING, which has its own case because both orderings look
        # correct in review and neither raises. Two arms, because the wrong order
        # fails in two different ways.
        _long_root = os.path.join(tmp, "root" + ("r" * 130))
        os.makedirs(os.path.join(_long_root, "work"))
        _d9a = M.normalise_details({"cwd": os.path.join(_long_root, "work")},
                                   project=_long_root)
        # Arm one: clipping FIRST cuts inside the root itself, so what reaches the
        # redactor is a path that is no longer inside anything and the row loses a
        # cwd it could have had.
        check("r9 a cwd under a root longer than the clip still resolves to its "
              "short relative form - the redaction runs BEFORE the bound, not "
              "after it: %r" % (_d9a,),
              _d9a["cwd"] == "work")
        # Arm two, and the one that is a LEAK rather than a loss: `_clip` spells a
        # structured value canonically, so clipping first hands the redactor a
        # STRING that is not absolute - which joins onto the repo root and comes
        # back looking repo-relative with the home directory still inside it.
        _d9b = M.normalise_details({"cwd": ["/Users/%s/secret" % _user]},
                                   project=proj)
        check("r9b a cwd that is not a string lands on the token, and no spelling "
              "of it survives into the row: %r"
              % (M.canonical(_d9b).count(_user),),
              _d9b["cwd"] == M.OUTSIDE_TOKEN
              and M.canonical(_d9b).count(_user) == 0)

        _r10 = M._normalise({"action": "config.write", "target": "x",
                             "actor": {"host": "MacBook-Pro.local",
                                       "via": "panel", "sessionId": "s1"}},
                            project=proj)
        check("r10 the actor carries NO `host`. It was written on every row and "
              "read by nothing - not `verify`, not the report, not the panel - "
              "while naming the machine of whoever ran the plugin. The rest of "
              "the actor is asserted too, so this cannot pass by dropping the "
              "block: %r" % (sorted(_r10["actor"]),),
              "host" not in _r10["actor"]
              and set(_r10["actor"]) == set(["author", "sessionId", "via"])
              and _r10["actor"]["via"] == "panel"
              and _r10["actor"]["sessionId"] == "s1"
              and M.canonical(_r10).count("MacBook-Pro") == 0)

        # THE FILE NAME IS THE ONE FIELD WITH NO REPAIR PATH: `genesis_prev()`
        # seeds the chain from the base name, so a machine name committed there
        # cannot be corrected afterwards without breaking `verify` on every clone.
        _nosess = os.path.join(tmp, "nosession")
        os.makedirs(_nosess)
        _np = M.append(_nosess, {"action": "config.write", "target": "",
                                 "actor": {"via": "cli"}},
                       config={"journal": {"dir": "j"}})
        _node = platform.node()
        check("r11 a writer with no session gets a pid, and the file it writes is "
              "named by a persisted random token - neither carries this machine's "
              "name: %r" % (os.path.basename(_np),),
              bool(_node) and _node not in M.writer_id({})
              and _node not in os.path.basename(_np)
              and M.writer_id({}) == "writer-%d" % os.getpid())
        # The arm a hostname could not pass. A host-derived id - digested or not -
        # gives two checkouts on one machine the SAME writer id; a per-checkout
        # random token gives them different ones, which is also the property that
        # keeps two clones from colliding on one file name after a merge.
        _nosess2 = os.path.join(tmp, "nosession2")
        os.makedirs(_nosess2)
        _np2 = M.append(_nosess2, {"action": "config.write", "target": "",
                                   "actor": {"via": "cli"}},
                        config={"journal": {"dir": "j"}})
        check("r11b two checkouts on one machine get DIFFERENT writer ids, which "
              "is what nothing derived from the machine can do: %r vs %r"
              % (os.path.basename(_np), os.path.basename(_np2)),
              os.path.basename(_np) != os.path.basename(_np2))
        _np3 = M.append(_nosess, {"action": "config.write", "target": "",
                                  "actor": {"via": "cli"}},
                        config={"journal": {"dir": "j"}})
        check("r11c ...and the token is STABLE within a checkout, so a month's "
              "rows stay one chain in one file rather than scattering across a "
              "file per process", _np3 == _np)

        # The other direction of r11c: state that is minted eagerly is state a
        # user finds in a repository that never needed it. An append WITH a
        # session id must leave no token behind at all.
        _sess = os.path.join(tmp, "withsession")
        os.makedirs(_sess)
        M.append(_sess, {"action": "config.write", "target": "",
                         "actor": {"sessionId": "3f33caa7-c0c9-4a4e-9c3b-a6db",
                                   "via": "hook"}},
                 config={"journal": {"dir": "j"}})
        check("r11d an append that HAS a session id neither reads nor creates a "
              "writer token - the fallback's state is resolved only where the "
              "fallback is used: %r" % (sorted(os.listdir(_sess)),),
              not os.path.exists(os.path.join(_sess, ".claude", "state",
                                              M.WRITER_TOKEN_FILE)))

        _uuid = "3f33caa7-c0c9-4a4e-9c3b-a6dbf4d111b9"
        check("r12 a real session id is byte-identical to what it always was, and "
              "a fallback never wins over one - the redaction is confined to the "
              "path that had no session at all",
              M.writer_id({"sessionId": _uuid}) == "3f33caa7-c0c9-4a4e-9c3b"
              and M.writer_id({"sessionId": _uuid}, fallback="deadbeefdeadbeef")
              == "3f33caa7-c0c9-4a4e-9c3b")

        # --- compatibility: old rows and new rows in one file -----------------
        _old = os.path.join(tmp, "oldrows")
        os.makedirs(os.path.join(_old, "j"))
        _fp = os.path.join(_old, "j", "%s.s-old.jsonl"
                           % time.strftime("%Y-%m", time.gmtime()))
        _orow = {"v": 2, "ts": "2026-01-01T00:00:00Z",
                 "actor": {"author": None, "sessionId": "s-old", "via": "hook",
                           "host": "MacBook-Pro.local"},
                 "action": "bash.unsandboxed", "target": "", "summary": "old",
                 "details": {"command": _leak, "cwd": _leak_cwd},
                 "stateHash": None, "prev": M.genesis_prev(os.path.basename(_fp))}
        _orow["hash"] = M.row_hash(_orow)
        with open(_fp, "w", encoding="utf-8") as fh:
            fh.write(M.canonical(_orow) + "\n")
        _ocfg = {"journal": {"dir": "j"}}
        M.append(_old, {"action": "bash.unsandboxed", "target": "",
                        "summary": "new", "details": {"command": "npm ci"},
                        "actor": {"sessionId": "s-old", "via": "hook"}},
                 config=_ocfg)
        _ov = M.verify(_old, _ocfg)
        check("r13 a row written before this change and a row written after it "
              "share one file and the chain still holds - `row_hash` sorts keys, "
              "so nothing about the old row's shape had to change: %r"
              % (_ov["findings"],),
              _ov["ok"] and _ov["rows"] == 2 and not _ov["findings"])

        # ALSO LOOKS VACUOUS, ALSO IS NOT: it asserts the leak is still there, on
        # purpose. Normalisation is a WRITE-side rule. A reader that helpfully
        # redacted an old row would change the bytes the hash was taken over and
        # turn `verify` into a liar about the only thing it exists to prove.
        _oread, _torn = M.read_file(_fp)
        check("r14 the old row is read back UNCHANGED, command and host and all - "
              "redacting on read would break its hash and make `verify` report "
              "tampering that never happened",
              not _torn and len(_oread) == 2
              and (_oread[0].get("details") or {}).get("command") == _leak
              and (_oread[0].get("actor") or {}).get("host")
              == "MacBook-Pro.local"
              and _oread[0].get("hash") == M.row_hash(_oread[0]),
              repr(sorted((_oread[0].get("details") or {}))))

        # --- target: absolute-inside collapses, absolute-outside does not ------
        _tin = os.path.join(proj, "docs", "audit", "audit-plan.json")
        _tout = os.path.join(tmp, "elsewhere", "f.json")
        check("r15 an absolute target INSIDE the repo is stored repo-relative - "
              "before `file_hash`, which resolves both spellings to one file",
              M._normalise({"action": "x", "target": _tin},
                           project=proj)["target"]
              == "docs/audit/audit-plan.json"
              and M._normalise({"action": "x", "target": "docs/x.json"},
                               project=proj)["target"] == "docs/x.json")
        check("r15b an absolute target OUTSIDE the repo is left ALONE, against "
              "the instinct: it is `verify`'s drift-map KEY and `file_hash`'s "
              "argument, so collapsing it to a constant would make two files "
              "collide on one key and invent drift between them. The lint reports "
              "that case instead",
              M._normalise({"action": "x", "target": _tout},
                           project=proj)["target"] == _tout)

        # THE TRAP, NAMED RATHER THAN DISCOVERED: one file keyed twice in the
        # drift map, once absolutely by an old row and once relatively by a new
        # one. Worst case one spurious WARNING; never a finding, and never `ok`
        # going false.
        _dproj = os.path.join(tmp, "drifttrap")
        os.makedirs(os.path.join(_dproj, "docs"))
        _dfile = os.path.join(_dproj, "docs", "plan.json")
        with open(_dfile, "w", encoding="utf-8") as fh:
            fh.write("{}")
        M.append(_dproj, {"action": "manifest.edit", "target": _dfile,
                          "actor": {"sessionId": "s-d"}}, config=_ocfg)
        _dv = M.verify(_dproj, _ocfg)
        check("r16 a repo whose old rows keyed a target absolutely still verifies "
              "clean once new rows key it relatively - the cost is at most a "
              "warning about one file counted twice: %r" % (_dv["findings"],),
              _dv["ok"] and not _dv["findings"])

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
