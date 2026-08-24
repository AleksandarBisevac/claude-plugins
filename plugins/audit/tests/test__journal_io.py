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

import ast
import hashlib
import json
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


# --- what the re-export list must hold, derived rather than remembered --------
def _module_consts_and_funcs(tree):
    """({public module-level constant names}, {name: FunctionDef}) for a module.

    MODULE LEVEL ONLY -- `tree.body`, not `ast.walk`. A name bound inside a
    function is a local with a different lifetime, and folding the two together
    would call a three-line loop variable part of the row's shape."""
    consts, funcs = set(), {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and not tgt.id.startswith("_"):
                    consts.add(tgt.id)
        elif isinstance(node, ast.FunctionDef):
            funcs[node.name] = node
    return consts, funcs


def _row_shape_constants(path, root="_normalise"):
    """(names, rooted): every public module-level constant of `path` that
    BUILDING A ROW can read, found by walking out from `root` over the module's
    own functions.

    WHY THIS IS DERIVED AT ALL. `audit-journal.py` re-exports the row shape by
    hand and a case pins each LISTED name to be this module's own object -- which
    says nothing about a name nobody listed, so the two files drift and only a
    human notices. Deriving the set means a constant a row can carry and the
    command does not re-export fails a case BY NAME.

    WHERE THE LINE IS DRAWN, and why here: a constant is part of the row's shape
    exactly when producing a row can read it. That takes in the bounds, the
    versions, the allow-lists and the redaction vocabulary a row ends up carrying
    (`OUTSIDE_TOKEN`, `UNNAMED_PROGRAM` are values a row really holds); it leaves
    out the writer-state vocabulary, which names a gitignored scratch file no row
    has ever read, and the file-layout and lock constants, which say where a
    journal lives rather than what a row says.

    `rooted` is False when `root` is GONE from the module -- a rename would
    otherwise narrow the walk to nothing and read as "no constant is missing",
    which is the same lie as an empty filter reporting all clear."""
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    consts, funcs = _module_consts_and_funcs(tree)
    found, seen, queue = set(), set(), [root]
    while queue:
        name = queue.pop()
        if name in seen or name not in funcs:
            continue
        seen.add(name)
        for read in set(n.id for n in ast.walk(funcs[name])
                        if isinstance(n, ast.Name)):
            if read in consts:
                found.add(read)
            elif read in funcs:
                queue.append(read)
    return sorted(found), root in funcs


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- the boundary ---------------------------------------------------------
    _shared = ("ROW_VERSION", "DETAILS_VERSION", "DETAILS_KEYS", "CHANGE_KEYS",
               "MAX_CHANGES", "MAX_VALUE_CHARS", "MAX_DETAILS_BYTES",
               "MAX_SUMMARY_CHARS", "SUMMARY_TRUNCATED", "VALUE_TRUNCATED",
               "OUTSIDE_TOKEN", "UNNAMED_PROGRAM",
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

    # THE LIST ABOVE IS HAND-WRITTEN, WHICH IS WHAT b1 CANNOT SEE. b1 proves each
    # LISTED name is this module's own object; nothing proved the list named
    # everything, so a release that added a row-shape constant here and did not
    # re-export it left the two files disagreeing with every case still green.
    # b6 derives the row-shape set from THIS module's source instead, so the
    # missing name is reported by name rather than noticed by a reader.
    _derived, _rooted = _row_shape_constants(M.__file__)
    _unexported = sorted(n for n in _derived
                         if getattr(_CMD, n, None) is not getattr(M, n))
    _unlisted = sorted(set(_derived) - set(_shared))
    # The anchors are the guard against the derivation narrowing to nothing: an
    # empty set would satisfy both comparisons above and read as "no constant is
    # missing", which is the failure this whole case exists to stop.
    _anchors = set(["ROW_VERSION", "DETAILS_KEYS", "MAX_VALUE_CHARS",
                    "MAX_SUMMARY_CHARS"])
    check("b6 every public constant `_journal_io` can read while BUILDING a row "
          "is re-exported by audit-journal.py as this module's own object, and "
          "is in the list b1 counts - derived from the source, so a constant "
          "nobody re-exported fails by name. Not re-exported %r, not listed %r, "
          "walk rooted %r, anchors found %r"
          % (_unexported, _unlisted, _rooted,
             sorted(_anchors & set(_derived))),
          _rooted and _unexported == [] and _unlisted == []
          and _anchors <= set(_derived))
    # A DERIVATION THAT TOOK EVERYTHING PUBLIC would pass b6 only by dragging
    # names into the re-export list that have no business there, and this is the
    # case that says so. The writer-state vocabulary is public, is read by this
    # module, and names a gitignored scratch file no ROW has ever carried; the
    # second arm asserts those names still exist, so an exclusion list that had
    # rotted into typos could not pass by excluding nothing.
    _state_vocab = set(["WRITER_TOKEN_FILE", "PLUGIN_WRITE_SIDECAR",
                        "PLUGIN_WRITE_KEY", "MAX_WRITER_KEY_CHARS"])
    check("b7 SECOND-DIRECTION CASE: the derivation is NARROW - the writer-state "
          "vocabulary is public and reachable, and stays out of the row shape "
          "because no row reads it: %r" % (sorted(_state_vocab & set(_derived)),),
          not (_state_vocab & set(_derived))
          and _state_vocab <= set(dir(M)))

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

        # --- pw: the claim that keeps the plugin's own append off the shell ----
        # F-F3 for the journal-writes hook, F104 for the panel. Both leave the
        # same shape of claim in `stateDir` and guard-bash-writes subtracts it
        # before it reads the journal class; the fault F104 records is what the
        # MISSING claim looks like from the operator's chair - a warning about a
        # write into the audit trail, a chain that verifies clean, and no way to
        # tell the two apart without checking by hand.
        _pwp = os.path.join(tmp, "claim")
        os.makedirs(_pwp)
        _pwcfg = {"journal": {"dir": "j"}}
        _pw1 = M.append(_pwp, {"action": "config.write", "target": "",
                               "actor": {"via": "panel"}}, config=_pwcfg)
        _slot = M.record_plugin_write(_pwp, _pwcfg, "panel", _pw1)

        def _claimed(slot):
            with open(slot, "r", encoding="utf-8") as fh:
                return json.load(fh)

        _held = _claimed(_slot) if _slot else {}
        # The agreement, driven rather than asserted by a comment: `journal-writes`
        # still carries its own copy of this derivation (a hook may not import
        # `scripts/`, though it already loads THIS module to append at all), and a
        # sidecar written where the guard does not look is indistinguishable from
        # a plugin that appended nothing - F-F3 reopened in the quiet direction.
        _jw = _loader.load(os.path.join(_harness.HOOKS_DIR, "journal-writes.py"),
                           modname="journal_writes_for_pw", cache=False)
        _hookslot = _jw._sidecar_path(_pwp, {}, {"session_id": "panel"})
        check("pw1 the claim names the appended file REPO-RELATIVE, in the slot "
              "`journal-writes.py` would have used for the same key - one slot "
              "shape, two writers, and the guard looks in one place: %r"
              % (_held,),
              _held.get(M.PLUGIN_WRITE_KEY)
              == [os.path.relpath(_pw1, _pwp).replace(os.sep, "/")]
              # normpath on BOTH sides, not string equality: the hook joins the
              # config's `.claude/state` as one segment while this module goes
              # through pathlib, and on Windows those two spellings differ by a
              # separator while naming one file. A case that only ever ran on
              # posix would call that agreement.
              and os.path.normpath(_slot) == os.path.normpath(_hookslot))

        # COUNTED, not merely found: a writer that truncated the list on every
        # append would pass a presence assertion for ever, and the entry it
        # dropped is exactly the file a shell command then gets blamed for.
        _pw2 = M.append(_pwp, {"action": "config.write", "target": "",
                               "actor": {"sessionId": "s-other"}},
                        config=_pwcfg)
        M.record_plugin_write(_pwp, _pwcfg, "panel", _pw2)
        M.record_plugin_write(_pwp, _pwcfg, "panel", _pw1)
        _held2 = _claimed(_slot)
        check("pw2 a second append is ADDED and a repeat of the first is not - "
              "the claim accumulates without growing a duplicate: %r" % (_held2,),
              len(_held2.get(M.PLUGIN_WRITE_KEY) or []) == 2
              and _pw1 != _pw2
              and sorted(_held2[M.PLUGIN_WRITE_KEY])
              == sorted(os.path.relpath(p, _pwp).replace(os.sep, "/")
                        for p in (_pw1, _pw2)))

        check("pw3 a writer key made of separators names NO file rather than a "
              "file outside the state directory, and one carrying a traversal is "
              "sanitised into it - the key goes into a PATH: %r"
              % (os.path.basename(M.plugin_write_sidecar(_pwp, _pwcfg,
                                                         "../../etc/x") or ""),),
              M.plugin_write_sidecar(_pwp, _pwcfg, " . ") is None
              and M.record_plugin_write(_pwp, _pwcfg, "", _pw1) is None
              and os.path.dirname(M.plugin_write_sidecar(_pwp, _pwcfg,
                                                         "../../etc/x"))
              == os.path.dirname(_slot))

        check("pw4 nothing to claim is None and never an exception: `append` "
              "returning False, or an older one returning True, must not turn a "
              "save that SUCCEEDED into a save that failed",
              M.record_plugin_write(_pwp, _pwcfg, "panel", False) is None
              and M.record_plugin_write(_pwp, _pwcfg, "panel", "") is None)

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

        # THE OLD FILE NAMES KEEP VERIFYING, and that is a constraint rather than
        # a nicety (F111). The panel used to hand its lock identity to the journal
        # as a session id, so its committed file was named `<month>.panel-<pid>`;
        # `genesis_prev()` seeds the chain from exactly those bytes, so a project
        # that already holds one cannot have it renamed or rewritten without
        # breaking `verify()` on every clone that has it. The repair is therefore
        # forward-only: what the panel names NEXT changes, and the two generations
        # have to sit in one directory and both hold.
        _mixed = os.path.join(tmp, "mixedwriters")
        os.makedirs(os.path.join(_mixed, "j"))
        _mcfg = {"journal": {"dir": "j"}}
        _oldpanel = "%s.panel-51555.jsonl" % time.strftime("%Y-%m", time.gmtime())
        _oldpp = os.path.join(_mixed, "j", _oldpanel)
        _prow = {"v": 1, "ts": "2026-08-01T00:00:00Z",
                 "actor": {"author": None, "sessionId": "panel-51555",
                           "via": "panel"},
                 "action": "config.write", "target": "",
                 "summary": "written by a panel that named its own file",
                 "stateHash": None, "prev": M.genesis_prev(_oldpanel)}
        _prow["hash"] = M.row_hash(_prow)
        with open(_oldpp, "w", encoding="utf-8") as fh:
            fh.write(M.canonical(_prow) + "\n")
        # The actor the panel passes NOW: no session id, so the name comes from
        # the persisted token. Same month, same directory, same writer in every
        # sense a human would mean.
        _newpp = M.append(_mixed, {"action": "config.write", "target": "",
                                   "summary": "written by a panel that does not",
                                   "actor": {"author": None, "via": "panel"}},
                          config=_mcfg)
        _mv = M.verify(_mixed, _mcfg)
        check("r14b a directory holding the old `panel-<pid>` file AND the "
              "token-named file the panel writes now verifies clean, chain and "
              "all - the fix could not rename what is already committed: %r"
              % (_mv["findings"] + _mv["warnings"],),
              _mv["ok"] and not _mv["findings"] and not _mv["warnings"]
              and _mv["rows"] == 2 and len(_mv["files"]) == 2)
        check("r14c ...and the new file is NOT the old one under another name: "
              "the old chain is still seeded from its own basename, which is why "
              "appending beside it rather than into it is the only safe move: %r"
              % (os.path.basename(_newpp),),
              os.path.basename(_newpp) != _oldpanel
              and "panel-" not in os.path.basename(_newpp)
              and M.read_file(_oldpp)[0][0]["prev"] == M.genesis_prev(_oldpanel))

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

    # --- `reason` joined the allow-list ---------------------------------------
    # `/audit:task cancel` and `/audit:phase cancel` both pass one and
    # `commands/task.md` says the row carries it; the allow-list dropped it in
    # silence, so it was written, discarded and believed. rs3 is the half that
    # keeps the addition from turning the allow-list into a pass-through.
    _cancel = {"taskId": "P2.3", "phaseId": "P2",
               "reason": "search rewrite dropped; the endpoint stays as-is"}
    check("rs1 a cancel's reason SURVIVES into the row's details, spelled the "
          "way it was given",
          M.normalise_details(_cancel).get("reason")
          == "search rewrite dropped; the endpoint stays as-is",
          repr(M.normalise_details(_cancel)))
    # Read through `.get` with a default rather than by indexing: with the key
    # off the list again `normalise_details` returns None here, and a TypeError
    # would take the rest of this suite down instead of failing one case.
    _bounded = (M.normalise_details({"reason": "x" * 500}) or {}).get("reason")
    check("rs2 ...bounded like every other value. A key added to the list and "
          "not to the bound would be the one field a caller could use to put a "
          "payload in a committed file",
          len(_bounded or "") == M.MAX_VALUE_CHARS, repr(_bounded)[:40])
    check("rs3 SECOND-DIRECTION CASE: a key that is NOT on the list is still "
          "dropped. This passes on the pre-change code by construction and is "
          "the only case that fails if the loop stops consulting DETAILS_KEYS - "
          "`cancelledId` and `cascaded` are the two the cancel writer used to "
          "send into this silence, and they stay off the list on purpose: the "
          "cascade rides `changes`, and `phaseId` already carries the id",
          M.normalise_details({"phaseId": "P2", "cancelledId": "P2",
                               "cascaded": ["P2.1"], "nonsense": 1})
          == {"phaseId": "P2"},
          repr(M.normalise_details({"phaseId": "P2", "cancelledId": "P2",
                                    "cascaded": ["P2.1"], "nonsense": 1})))

    # ROWS WRITTEN BEFORE THE KEY WAS ADDED, captured from the pre-change tree
    # (`git archive HEAD`) rather than regenerated here -- a fixture the current
    # code produced could not tell "old rows still verify" from "the current code
    # agrees with itself". The hashes below are the bytes that were on disk. The
    # middle row is a `task.cancel` whose caller PASSED a reason: its `details`
    # carries `phaseId` and `taskId` and no reason at all, which is the defect
    # itself preserved, and it is why rs6 can tell the two versions apart.
    _PRE_CHANGE_FILE = "2026-01.s-old.jsonl"
    _PRE_CHANGE_ROWS = [
        ('{"action":"task.add","actor":{"author":"ada","sessionId":"s-old","'
         'via":"cli"},"details":{"phaseId":"P1","taskId":"P1.1"},"hash":"d05'
         '25a6b60f561f6001dec1f13e0f3816f92f8730568cd7cd562f46df162a030","pr'
         'ev":"genesis:84631db4c1e0fe9950fe7e365ef42e8f207d369c6003958b671ca'
         '7ab079a5fe1","stateHash":"sha256:a30ba769a3fb334ae854f96e7261f4528'
         '8ed17e8f1fd1f37177b3c9b870dcb85","summary":"P1.1 added to P1: seed'
         '","target":"docs/audit/audit-plan.json","ts":"2026-01-05T09:00:00Z'
         '","v":2}'),
        ('{"action":"task.cancel","actor":{"author":"ada","sessionId":"s-old'
         '","via":"cli"},"details":{"phaseId":"P1","taskId":"P1.1"},"hash":"'
         'ddc93bebff08968ce1bb742f9e30db767effad75fae66464663e622c7b5f9e58",'
         '"prev":"d0525a6b60f561f6001dec1f13e0f3816f92f8730568cd7cd562f46df1'
         '62a030","stateHash":"sha256:a30ba769a3fb334ae854f96e7261f45288ed17'
         'e8f1fd1f37177b3c9b870dcb85","summary":"P1.1 cancelled: endpoint '
         'stays as-is","target":"docs/audit/audit-plan.json","ts":"2026-01-0'
         '5T09:05:00Z","v":2}'),
        ('{"action":"phase.update","actor":{"author":"ada","sessionId":"s-ol'
         'd","via":"cli"},"details":{"field":"status","from":"pending","phas'
         'eId":"P1","to":"done"},"hash":"4134cc7d360214b946ca856752c2c1cdc02'
         'b47f1483df0915599e03735d434b8","prev":"ddc93bebff08968ce1bb742f9e3'
         '0db767effad75fae66464663e622c7b5f9e58","stateHash":"sha256:a30ba76'
         '9a3fb334ae854f96e7261f45288ed17e8f1fd1f37177b3c9b870dcb85","summar'
         'y":"P1 status pending -> done","target":"docs/audit/audit-plan.jso'
         'n","ts":"2026-01-05T09:09:00Z","v":2}'),
    ]
    _rtmp = tempfile.mkdtemp(prefix="audit-journal-oldrows-")
    try:
        _rproj = os.path.join(_rtmp, "repo")
        os.makedirs(os.path.join(_rproj, "docs", "audit"))
        # The bytes the fixture's `stateHash` was taken over. Written first, so
        # `verify` compares the world against the row rather than warning about
        # drift it cannot explain.
        with open(os.path.join(_rproj, "docs", "audit", "audit-plan.json"),
                  "w", encoding="utf-8") as fh:
            fh.write('{"phases": []}\n')
        _rcfg = {"journal": {"enabled": True,
                             "dir": os.path.join(_rproj, "journal")}}
        _rdir = os.path.join(_rproj, "journal")
        os.makedirs(_rdir)
        with open(os.path.join(_rdir, _PRE_CHANGE_FILE), "w",
                  encoding="utf-8") as fh:
            fh.write("\n".join(_PRE_CHANGE_ROWS) + "\n")
        _rrows = M.read_file(os.path.join(_rdir, _PRE_CHANGE_FILE))[0]
        check("rs4 the fixture really is PRE-change: its cancel row carries no "
              "reason, so rs6 below is measuring the addition and not the "
              "current code agreeing with itself",
              len(_rrows) == 3
              and "reason" not in _rrows[1]["details"]
              and _rrows[1]["action"] == "task.cancel",
              repr(_rrows[1].get("details")))
        _rver = M.verify(_rproj, _rcfg)
        check("rs5 every pre-change row STILL HASHES to the hex it was written "
              "with. The row hash covers whatever is in the row, so a key added "
              "to the allow-list must be invisible to a row that never had it",
              _rver["ok"] and not _rver["findings"] and _rver["rows"] == 3,
              repr(_rver["findings"] + _rver["warnings"]))
        _rhashes = [r["hash"] for r in _rrows]
        check("rs5b ...recomputed, not merely read back: `row_hash` over each "
              "stored row reproduces the stored hex. rs5 alone would pass on a "
              "verify that had quietly stopped hashing anything",
              [M.row_hash(r) for r in _rrows] == _rhashes, repr(_rhashes))
        # A NEW row appended onto the OLD chain, which is the migration that
        # actually happens: one journal file holding both.
        M.append(_rproj, {"ts": "2026-01-05T09:20:00Z", "action": "phase.cancel",
                          "actor": {"author": "ada", "sessionId": "s-old",
                                    "via": "cli"},
                          "target": "docs/audit/audit-plan.json",
                          "summary": "P1 cancelled: superseded",
                          "details": {"phaseId": "P1",
                                      "reason": "superseded"}},
                 config=_rcfg)
        _rrows2 = M.read_file(os.path.join(_rdir, _PRE_CHANGE_FILE))[0]
        check("rs6 a row written NOW carries the reason in its details...",
              len(_rrows2) == 4
              and _rrows2[3]["details"].get("reason") == "superseded",
              repr(_rrows2[3].get("details")))
        _rver2 = M.verify(_rproj, _rcfg)
        check("rs7 ...and the whole file still verifies with old and new rows "
              "chained together - the new row's `prev` is the old tail's hash, "
              "which is the only shape a live journal ever takes",
              _rver2["ok"] and not _rver2["findings"]
              and _rrows2[3]["prev"] == _rhashes[-1],
              repr(_rver2["findings"]))
    finally:
        shutil.rmtree(_rtmp, ignore_errors=True)

    # --- the cascade moved onto `changes`, and old cancel rows did not --------
    # A phase cancel closes the work still open inside it and handed those ids
    # over as `details.cascaded`, which the allow-list drops: the trail said a
    # phase had ended and never said what ended with it. The repair spells the
    # cascade as `changes` rather than putting a new key on the list, so
    # DETAILS_KEYS is unchanged -- and the row hash covers whatever is in the
    # row, so that has to be MEASURED against rows written before it rather
    # than reasoned about.
    #
    # THE ROW BELOW WAS WRITTEN BY THE PRE-CHANGE TREE and its hash is the hex
    # that was on disk. Its `details` are what that tree produced from a caller
    # passing `cancelledId` and `cascaded` as well -- both gone, the cascade
    # surviving only as prose in the summary, which is the defect preserved and
    # what lets cd3 tell the two versions apart. Regenerating it here would
    # compare the current code with itself and could not fail.
    _CASCADE_FILE = "2026-01.s-cascade.jsonl"
    _CASCADE_ROW = (
        ('{"action":"phase.cancel","actor":{"author":"ada","sessionId":"'
         's-cascade","via":"cli"},"details":{"phaseId":"P2","reason":"sh'
         'elved"},"hash":"00540ee78e6be7a0c3328efd0acabe09cf9dc70a9743b2'
         'd5376abea0d2cd4209","prev":"genesis:9716da542bf4f164d40135e08e'
         'f595d52119aff271d01cefff3a4f14ec4e3f17","stateHash":"sha256:a3'
         '0ba769a3fb334ae854f96e7261f45288ed17e8f1fd1f37177b3c9b870dcb85'
         '","summary":"P2 cancelled: shelved (also P2.2, P2.3, P2.4)","t'
         'arget":"docs/audit/audit-plan.json","ts":"2026-01-06T11:00:00Z'
         '","v":2}'))
    _ctmp = tempfile.mkdtemp(prefix="audit-journal-cascade-")
    try:
        _cproj = os.path.join(_ctmp, "repo")
        os.makedirs(os.path.join(_cproj, "docs", "audit"))
        with open(os.path.join(_cproj, "docs", "audit", "audit-plan.json"),
                  "w", encoding="utf-8") as fh:
            fh.write('{"phases": []}\n')
        _ccfg = {"journal": {"enabled": True,
                             "dir": os.path.join(_cproj, "journal")}}
        _cdir = os.path.join(_cproj, "journal")
        os.makedirs(_cdir)
        _cpath = os.path.join(_cdir, _CASCADE_FILE)
        with open(_cpath, "w", encoding="utf-8") as fh:
            fh.write(_CASCADE_ROW + "\n")
        _crows = M.read_file(_cpath)[0]
        check("cd1 the fixture really is PRE-change: the cascaded ids are in "
              "its SUMMARY and nowhere in its details, which is the silent drop "
              "itself and what makes cd3 a measurement of the repair",
              len(_crows) == 1
              and _crows[0]["action"] == "phase.cancel"
              and "P2.2" in _crows[0]["summary"]
              and "changes" not in _crows[0]["details"]
              and "cascaded" not in _crows[0]["details"],
              repr(_crows[0].get("details")))
        _cver = M.verify(_cproj, _ccfg)
        _chash = _crows[0]["hash"]
        check("cd2 ...and it STILL HASHES to the hex it was written with, "
              "recomputed by `row_hash` rather than read back - a cancel row "
              "already committed must not be disturbed by the writer above it "
              "learning a new shape",
              _cver["ok"] and not _cver["findings"] and _cver["rows"] == 1
              and M.row_hash(_crows[0]) == _chash,
              repr(_cver["findings"] + _cver["warnings"]))
        # A NEW-shape cancel row appended onto the OLD chain, which is the
        # migration that actually happens: one journal file holding both.
        M.append(_cproj, {"ts": "2026-01-06T11:30:00Z",
                          "action": "phase.cancel",
                          "actor": {"author": "ada", "sessionId": "s-cascade",
                                    "via": "cli"},
                          "target": "docs/audit/audit-plan.json",
                          "summary": "P3 cancelled: shelved (also P3.1)",
                          "details": {"phaseId": "P3", "reason": "shelved",
                                      "cancelledId": "P3",
                                      "changes": [{"id": "P3.1",
                                                   "field": "status",
                                                   "from": "in_progress",
                                                   "to": "cancelled"}]}},
                 config=_ccfg)
        _crows2 = M.read_file(_cpath)[0]
        _cdet2 = _crows2[1]["details"] if len(_crows2) > 1 else {}
        check("cd3 a row written NOW carries the cascade as a `changes` entry "
              "naming the status the task held - and `cancelledId` is STILL "
              "dropped beside it, so the repair added no vocabulary: %r"
              % (_cdet2,),
              len(_crows2) == 2
              and _cdet2.get("changes") == [{"id": "P3.1", "field": "status",
                                             "from": "in_progress",
                                             "to": "cancelled"}]
              and "cancelledId" not in _cdet2)
        _cver2 = M.verify(_cproj, _ccfg)
        check("cd4 ...and the whole file still verifies with the old and new "
              "cancel rows chained together - the new row's `prev` is the old "
              "one's hash, which is the only shape a live journal ever takes",
              _cver2["ok"] and not _cver2["findings"]
              and _crows2[1]["prev"] == _chash,
              repr(_cver2["findings"]))
    finally:
        shutil.rmtree(_ctmp, ignore_errors=True)

    # --- `summary` got a bound, and a cut one says so ------------------------
    # `details` is bounded three ways -- an allow-list, a clip per value, a cap
    # on the block -- and a block that hits the cap writes `truncated`, which
    # sends the reader to `summary`. `summary` had no bound at all, so the row
    # pointed at a field nothing had checked. A phase cancel is the case that
    # made it concrete: it names every task the cancel cascaded to.
    _long = "P4 cancelled: " + ("x" * M.MAX_SUMMARY_CHARS)
    _cut = M._clip_summary(_long)
    check("sm1 a summary past the bound is cut TO the bound, marker included - "
          "the marker is spent out of MAX_SUMMARY_CHARS rather than added on "
          "top of it, so the constant is a fact about the field a reader can "
          "measure: %r" % (len(_cut),),
          len(_cut) == M.MAX_SUMMARY_CHARS
          and _cut.endswith(M.SUMMARY_TRUNCATED)
          and _cut.count(M.SUMMARY_TRUNCATED) == 1)
    # Exactly AT the bound, not merely under it: an off-by-one here is the
    # difference between a field that is never cut for nothing and one that is.
    _exact = "y" * M.MAX_SUMMARY_CHARS
    _short = "P1.1 cancelled: endpoint stays as-is"
    check("sm2 SECOND-DIRECTION CASE: a summary that FITS comes back byte for "
          "byte and carries no marker, at the bound as well as under it. This "
          "passes on the pre-change code by construction and is the only case "
          "here that fails if the clip becomes unconditional - a marker on an "
          "uncut summary is the same lie as no marker on a cut one",
          M._clip_summary(_short) == _short
          and M._clip_summary(_exact) == _exact
          and M.SUMMARY_TRUNCATED not in M._clip_summary(_exact))
    _rowlong = M._normalise({"action": "phase.cancel", "summary": _long,
                             "target": "docs/audit/audit-plan.json"})
    check("sm3 ...and the bound is on the ROW, not on a helper nothing calls: "
          "`_normalise` is the one funnel every writer reaches `append` through, "
          "so the panel, the hook and audit-task all get it without asking",
          len(_rowlong["summary"]) == M.MAX_SUMMARY_CHARS
          and _rowlong["summary"].count(M.SUMMARY_TRUNCATED) == 1
          and M._normalise({"action": "a", "summary": _short})["summary"]
          == _short)

    # THE ROW BELOW WAS WRITTEN BY THE PRE-CHANGE TREE and its hash is the hex
    # that was on disk. Its summary is a phase cancel naming every cascaded task
    # id, unbounded, which is the defect preserved -- and it is what lets sm6
    # tell the two versions apart on ONE input. Regenerating it here would
    # compare the current code with itself and could not fail. The row hash
    # covers whatever is in the row, so "old rows still verify" has to be
    # measured against bytes this code did not produce.
    _SUM_FILE = "2026-01.s-wide.jsonl"
    _SUM_ROW = (
        '{"action":"phase.cancel","actor":{"author":"ada","sessionId":"'
        's-wide","via":"cli"},"details":{"phaseId":"P4","reason":"aband'
        'oned after the spike"},"hash":"b4c9f06129aa64e3d8ef7940006cc8b'
        '2134d145672859cea76a4503a958ee275","prev":"genesis:d1696f3c05a'
        'adffe1608eb45e3600f8149a85b46589943756a2118399f94c252","stateH'
        'ash":"sha256:a30ba769a3fb334ae854f96e7261f45288ed17e8f1fd1f371'
        '77b3c9b870dcb85","summary":"P4 cancelled: the whole approach w'
        'as abandoned after the spike (also P4.1, P4.2, P4.3, P4.4, P4.'
        '5, P4.6, P4.7, P4.8, P4.9, P4.10, P4.11, P4.12, P4.13, P4.14, '
        'P4.15, P4.16, P4.17, P4.18, P4.19, P4.20, P4.21, P4.22, P4.23,'
        ' P4.24, P4.25, P4.26, P4.27, P4.28, P4.29, P4.30, P4.31, P4.32'
        ', P4.33, P4.34, P4.35, P4.36, P4.37, P4.38, P4.39, P4.40, P4.4'
        '1, P4.42, P4.43, P4.44, P4.45, P4.46, P4.47, P4.48, P4.49, P4.'
        '50, P4.51, P4.52, P4.53, P4.54, P4.55, P4.56, P4.57, P4.58, P4'
        '.59, P4.60)","target":"docs/audit/audit-plan.json","ts":"2026-'
        '01-07T08:00:00Z","v":2}')
    _stmp = tempfile.mkdtemp(prefix="audit-journal-summary-")
    try:
        _sproj = os.path.join(_stmp, "repo")
        os.makedirs(os.path.join(_sproj, "docs", "audit"))
        with open(os.path.join(_sproj, "docs", "audit", "audit-plan.json"),
                  "w", encoding="utf-8") as fh:
            fh.write('{"phases": []}\n')
        _scfg = {"journal": {"enabled": True,
                             "dir": os.path.join(_sproj, "journal")}}
        _sdir = os.path.join(_sproj, "journal")
        os.makedirs(_sdir)
        _spath = os.path.join(_sdir, _SUM_FILE)
        with open(_spath, "w", encoding="utf-8") as fh:
            fh.write(_SUM_ROW + "\n")
        _srows = M.read_file(_spath)[0]
        _sfix = _srows[0]["summary"]
        check("sm4 the fixture really is PRE-change: its summary is past the "
              "bound and says nothing about being cut, which is the one-sided "
              "bound itself and what makes sm6 a measurement of the repair: %r"
              % (len(_sfix),),
              len(_srows) == 1 and len(_sfix) > M.MAX_SUMMARY_CHARS
              and M.SUMMARY_TRUNCATED not in _sfix
              and _srows[0]["action"] == "phase.cancel")
        _sver = M.verify(_sproj, _scfg)
        _shash = _srows[0]["hash"]
        check("sm5 ...and it STILL HASHES to the hex it was written with, "
              "recomputed by `row_hash` rather than read back. A bound added to "
              "a field changes how a NEW row hashes and must be invisible to "
              "one already committed",
              _sver["ok"] and not _sver["findings"] and _sver["rows"] == 1
              and M.row_hash(_srows[0]) == _shash,
              repr(_sver["findings"] + _sver["warnings"]))
        # The SAME summary the fixture was written from, through the current
        # normaliser: one input, two versions, two answers.
        _snow = M._normalise({"action": "phase.cancel", "summary": _sfix,
                              "target": "docs/audit/audit-plan.json"})["summary"]
        check("sm6 a row written NOW from the fixture's own summary is cut and "
              "SAYS it was cut, where the committed one was neither - and it "
              "still names the phase it opened with, because the cut takes the "
              "tail: %r" % (_snow[-40:],),
              _snow != _sfix and len(_snow) == M.MAX_SUMMARY_CHARS
              and _snow.count(M.SUMMARY_TRUNCATED) == 1
              and _snow.startswith("P4 cancelled:"))
        M.append(_sproj, {"ts": "2026-01-07T08:30:00Z",
                          "action": "phase.cancel",
                          "actor": {"author": "ada", "sessionId": "s-wide",
                                    "via": "cli"},
                          "target": "docs/audit/audit-plan.json",
                          "summary": _sfix,
                          "details": {"phaseId": "P4", "reason": "shelved"}},
                 config=_scfg)
        _srows2 = M.read_file(_spath)[0]
        _sver2 = M.verify(_sproj, _scfg)
        check("sm7 ...and the file verifies with the unbounded old row and the "
              "bounded new one chained together - the new row's `prev` is the "
              "old one's hash, which is the only shape a live journal takes",
              len(_srows2) == 2 and _sver2["ok"] and not _sver2["findings"]
              and _srows2[1]["prev"] == _shash
              and _srows2[1]["summary"] == _snow,
              repr(_sver2["findings"]))
    finally:
        shutil.rmtree(_stmp, ignore_errors=True)

    # --- ...and so did a `details` value -------------------------------------
    # `summary` got a bound AND a marker above. `_clip` had the bound and no
    # marker, one level down and inside the one block that ALSO writes
    # `truncated` when it drops change entries -- so a reader of these rows has
    # been taught that this row type announces a cut, and then a value the clip
    # shortened said nothing at all. A short value and a shortened one were
    # indistinguishable in a file that is committed on purpose.
    _vlong = "z" * (M.MAX_VALUE_CHARS * 3)
    _vcut = (M.normalise_details({"reason": _vlong}) or {}).get("reason") or ""
    check("vt1 a details value past the bound is cut TO the bound, marker "
          "included - spent out of MAX_VALUE_CHARS the way the summary's is, so "
          "the constant stays a fact about the field a reader can measure: %r"
          % (len(_vcut),),
          len(_vcut) == M.MAX_VALUE_CHARS
          and _vcut.endswith(M.VALUE_TRUNCATED)
          and _vcut.count(M.VALUE_TRUNCATED) == 1)
    # Exactly AT the bound, not merely under it: an off-by-one here is the
    # difference between a value that is never marked for nothing and one that is.
    _vexact = (M.normalise_details({"reason": "w" * M.MAX_VALUE_CHARS})
               or {}).get("reason")
    _vshort = (M.normalise_details({"reason": "endpoint stays as-is"})
               or {}).get("reason")
    check("vt2 SECOND-DIRECTION CASE: a value that FITS comes back byte for "
          "byte and carries no marker, at the bound as well as under it. This "
          "passes on the pre-change code by construction and is the only case "
          "here that fails if the clip becomes unconditional - a marker on an "
          "uncut value is the same lie as no marker on a cut one",
          _vshort == "endpoint stays as-is"
          and _vexact == "w" * M.MAX_VALUE_CHARS
          and M.VALUE_TRUNCATED not in (_vexact or ""))
    # COUNTED OVER THE WHOLE CANONICAL BLOCK, not asserted of the one field the
    # repair was written against: `changes` entries go through the same clip, and
    # a marker added at a single call site would pass any per-field assertion.
    _vdet = M.normalise_details({"reason": _vlong, "taskId": "P5.2",
                                 "changes": [{"id": "P5.1", "field": "outcome",
                                              "from": _vlong, "to": "done"}]})
    _vtext = M.canonical(_vdet)
    check("vt3 every value the block clips carries the marker, and every value "
          "that fits still does not: %r"
          % (_vtext.count(M.VALUE_TRUNCATED),),
          _vtext.count(M.VALUE_TRUNCATED) == 2
          and _vdet["changes"][0]["to"] == "done"
          and _vdet["taskId"] == "P5.2")
    _vstruct = (M.normalise_details({"reason": ["y" * 400]})
                or {}).get("reason") or ""
    check("vt3b a structured value is spelled canonically and THEN bounded, so "
          "the marker lands on what would actually be written - a canonical "
          "spelling cut mid-brace is not JSON any more and had nothing on it to "
          "say why: %r" % (_vstruct[-16:],),
          len(_vstruct) == M.MAX_VALUE_CHARS
          and _vstruct.startswith('["y')
          and _vstruct.endswith(M.VALUE_TRUNCATED))
    # THE TWO MARKERS MUST NOT ANSWER EACH OTHER'S QUESTION. `truncated` is a
    # claim about the change LIST; the in-band marker is a claim about ONE value.
    # Both arms are needed: a per-value marker that raised the flag would tell
    # every reader that entries were dropped when none were, and a flag that
    # stopped being written would lose the only thing that says entries WERE.
    _vflagless = M.normalise_details({"reason": _vlong,
                                      "changes": [{"id": "P5.1", "field": "f",
                                                   "from": "a", "to": "b"}]})
    _vflagged = M.normalise_details(
        {"reason": _vlong,
         "changes": [{"id": "P5.%d" % i, "field": "f", "from": "a", "to": "b"}
                     for i in range(M.MAX_CHANGES + 4)]})
    check("vt4 a value marked as cut does NOT set the block's `truncated` flag, "
          "and a change list that was cut still does - the two are never the "
          "same statement, so they cannot contradict each other: %r"
          % (sorted(_vflagless),),
          "truncated" not in _vflagless
          and _vflagless["reason"].endswith(M.VALUE_TRUNCATED)
          and _vflagged.get("truncated") is True
          and len(_vflagged["changes"]) == M.MAX_CHANGES)

    # THE ROW BELOW WAS WRITTEN BY THE PRE-CHANGE TREE and its hash is the hex
    # that was on disk. Its `reason` is a cancel justification the clip cut at
    # the bound and said nothing about, which is the silence itself preserved --
    # and it is what lets vt7 tell the two versions apart on ONE input.
    # Regenerating it here would compare the current code with itself and could
    # not fail. The row hash covers whatever is in the row, so "old rows still
    # verify" has to be measured against bytes this code did not produce.
    _VAL_FILE = "2026-01.s-value.jsonl"
    _VAL_REASON = ("the search rewrite is dropped: the endpoint stays as it is "
                   "until the ranking work lands, and the two teams agreed to "
                   "revisit it after the index migration")
    _VAL_ROW = (
        '{"action":"task.cancel","actor":{"author":"ada","sessionId":"s-value",'
        '"via":"cli"},"details":{"phaseId":"P5","reason":"the search rewrite is '
        'dropped: the endpoint stays as it is until the ranking work lands, and '
        'the two teams agreed to rev","taskId":"P5.2"},"hash":"a6a03341f148b7e6'
        'b8ed86382912b2f4b99f8545d172d88f920da9b98f151adc","prev":"genesis:5ae0'
        'b4d100d361fec025eb1a7074e0d546df3e64cacd02c9991d8b1b7354bd6d","stateHa'
        'sh":"sha256:a30ba769a3fb334ae854f96e7261f45288ed17e8f1fd1f37177b3c9b87'
        '0dcb85","summary":"P5.2 cancelled: superseded by the ranking work","ta'
        'rget":"docs/audit/audit-plan.json","ts":"2026-01-08T07:00:00Z","v":2}')
    _vtmp = tempfile.mkdtemp(prefix="audit-journal-value-")
    try:
        _vproj = os.path.join(_vtmp, "repo")
        os.makedirs(os.path.join(_vproj, "docs", "audit"))
        with open(os.path.join(_vproj, "docs", "audit", "audit-plan.json"),
                  "w", encoding="utf-8") as fh:
            fh.write('{"phases": []}\n')
        _vcfg = {"journal": {"enabled": True,
                             "dir": os.path.join(_vproj, "journal")}}
        _vdir = os.path.join(_vproj, "journal")
        os.makedirs(_vdir)
        _vpath = os.path.join(_vdir, _VAL_FILE)
        with open(_vpath, "w", encoding="utf-8") as fh:
            fh.write(_VAL_ROW + "\n")
        _vrows = M.read_file(_vpath)[0]
        _vfix = _vrows[0]["details"]["reason"]
        check("vt5 the fixture really is PRE-change: its reason sits exactly ON "
              "the bound with no marker, ending mid-word - which reads as a "
              "reason that ended there, and is the silent clip itself: %r"
              % (_vfix[-14:],),
              len(_vrows) == 1
              and _vfix == _VAL_REASON[:M.MAX_VALUE_CHARS]
              and M.VALUE_TRUNCATED not in _vfix
              and _vrows[0]["action"] == "task.cancel")
        _vver = M.verify(_vproj, _vcfg)
        _vhash = _vrows[0]["hash"]
        check("vt6 ...and it STILL HASHES to the hex it was written with, "
              "recomputed by `row_hash` rather than read back. A marker changes "
              "how a NEW row hashes and must be invisible to one already "
              "committed",
              _vver["ok"] and not _vver["findings"] and _vver["rows"] == 1
              and M.row_hash(_vrows[0]) == _vhash,
              repr(_vver["findings"] + _vver["warnings"]))
        # The SAME reason the fixture was written from, through the current
        # normaliser: one input, two versions, two answers.
        _vnow = M.normalise_details({"reason": _VAL_REASON})["reason"]
        check("vt7 a row written NOW from the fixture's own reason is cut and "
              "SAYS it was cut, where the committed one was cut and silent - "
              "and it still opens on the sentence, because the cut takes the "
              "tail: %r" % (_vnow[-24:],),
              _vnow != _vfix and len(_vnow) == M.MAX_VALUE_CHARS
              and _vnow.count(M.VALUE_TRUNCATED) == 1
              and _vnow.startswith("the search rewrite is dropped:"))
        M.append(_vproj, {"ts": "2026-01-08T07:30:00Z", "action": "task.cancel",
                          "actor": {"author": "ada", "sessionId": "s-value",
                                    "via": "cli"},
                          "target": "docs/audit/audit-plan.json",
                          "summary": "P5.3 cancelled: superseded",
                          "details": {"phaseId": "P5", "taskId": "P5.3",
                                      "reason": _VAL_REASON}},
                 config=_vcfg)
        _vrows2 = M.read_file(_vpath)[0]
        _vver2 = M.verify(_vproj, _vcfg)
        check("vt8 ...and the file verifies with the silently-clipped old row "
              "and the marked new one chained together - the new row's `prev` "
              "is the old one's hash, which is the only shape a live journal "
              "takes",
              len(_vrows2) == 2 and _vver2["ok"] and not _vver2["findings"]
              and _vrows2[1]["prev"] == _vhash
              # Measured against the BOUND and the marker, not against `_vnow`:
              # comparing the appended row with a value this same code just
              # produced is the current code agreeing with itself, and would
              # hold on the silent version too.
              and len(_vrows2[1]["details"]["reason"]) == M.MAX_VALUE_CHARS
              and _vrows2[1]["details"]["reason"].endswith(M.VALUE_TRUNCATED),
              repr(_vver2["findings"]))
    finally:
        shutil.rmtree(_vtmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__journal_io.py --selftest\n")
    raise SystemExit(2)
