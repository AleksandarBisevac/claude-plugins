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
import _output                                     # noqa: E402  (posix_rel: the one path spelling)
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


def _scripts_modules():
    """Every `.py` under `scripts/`, wherever it sits. `__pycache__` is not source."""
    out = []
    for dirpath, dirs, files in os.walk(_harness.SCRIPTS_DIR):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in sorted(files):
            if name.endswith(".py"):
                out.append(os.path.join(dirpath, name))
    return sorted(out)


def _journal_append_sites(path):
    """[(lineno, name)] for every JOURNAL append in `path`, and for no list.

    THE ARITY IS THE DISCRIMINATOR, not the name. `list.append` takes exactly one
    argument and a journal append takes `(project, entry)`, so a call to `append`,
    `_append` or `append_from_cli` carrying two or more arguments is one of these
    and a one-argument call never is. A name test alone would call every list in
    the tree a journal writer; pw7 is the case that says this one does not."""
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    sites = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        else:
            continue
        if name in ("append", "_append", "append_from_cli"):
            sites.append((node.lineno, name))
    return sites


def _names_used(path):
    """Every identifier a module NAMES, plus the strings it hands `getattr`.

    PROSE IS EXCLUDED ON PURPOSE and that is the whole reason this reads the AST:
    a docstring saying a file leaves a claim is not a file leaving one, and every
    writer this rule is about explains itself in prose. `getattr` is in because
    `_panel_write` reaches its recorder through one - an older journal module has
    no `record_plugin_write`, and that miss is the fail-soft branch."""
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "getattr" and len(node.args) >= 2
              and isinstance(node.args[1], ast.Constant)
              and isinstance(node.args[1].value, str)):
            used.add(node.args[1].value)
    return used


def _unclaimed_journal_writers(owner):
    """Journal appends under `scripts/` that leave the write guard nothing to
    subtract, as `path:line`. Also returns every site it derived, so an empty
    finding list cannot be read as "all clear" by a walk that found nothing.

    THE RULE: a journal append puts its file into `git status`, and
    `guard-bash-writes` reports a journal file no writer claimed as a shell write
    into the append-only trail. So a site is settled when it goes through
    `append_from_cli`, or when the file files the claim by hand - which
    `audit-journal.py` does because it needs the ROW that only the raising
    `_append` returns, and `_panel_write` does under the panel's own key. `owner`
    is where both entry points are defined and is settled by definition."""
    findings, sites = [], []
    for path in _scripts_modules():
        found = _journal_append_sites(path)
        if not found:
            continue
        sites.extend((path, line, name) for line, name in found)
        if os.path.basename(path) == owner:
            continue
        claims = "record_plugin_write" in _names_used(path)
        for line, name in found:
            if name != "append_from_cli" and not claims:
                findings.append("%s:%d" % (os.path.basename(path), line))
    return findings, sites


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
               "ENV_SESSION_VAR", "MAX_SESSION_ID_CHARS", "MAX_AGENT_CHARS",
               "MERGE_ACTION", "MERGE_VIA",
               "DEFAULT_DIRNAME", "ARCHIVE_DIRNAME", "DEFAULT_MANIFEST",
               "GENESIS", "LOCK_STALE_SECONDS", "LOCK_WAIT_SECONDS",
               "load_config", "enabled", "journal_dir", "in_journal", "canonical",
               "row_hash", "genesis_prev", "file_hash", "writer_id",
               "env_session_id", "month_of",
               "file_for", "rows_from_text", "read_file", "journal_files",
               "read_all", "writer_of", "session_index",
               "normalise_details", "append", "row_content", "rows_digest",
               "merge_rows", "merge_text", "write_merged", "anchor_verdict",
               "rows_unaccounted",
               "deleted_from_worktree", "tracked_but_gone",
               "gone_finding", "gone_findings",
               "verify", "_normalise", "_append",
               "_git_status_sets", "_git_anchor_finding")

    def with_env(value, fn):
        """Run `fn()` with `$CLAUDE_CODE_SESSION_ID` pinned, then put it back.

        EVERY CASE THAT WRITES A ROW DEPENDS ON THIS VARIABLE, and
        the suite runs both where it is set (inside a Claude Code session) and
        where it is not (CI). A case reading whatever the machine happened to
        export would assert a different shape on each, which is exactly the
        platform-shaped silent pass this repository is arranged against - and it
        is not hypothetical: `r10` went red the moment the field landed, on this
        machine only. `None` pins the variable ABSENT, which is the state every
        case written before the field assumed."""
        held = os.environ.get(M.ENV_SESSION_VAR)
        try:
            if value is None:
                os.environ.pop(M.ENV_SESSION_VAR, None)
            else:
                os.environ[M.ENV_SESSION_VAR] = value
            return fn()
        finally:
            if held is None:
                os.environ.pop(M.ENV_SESSION_VAR, None)
            else:
                os.environ[M.ENV_SESSION_VAR] = held
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
                        "PLUGIN_WRITE_KEY", "MAX_WRITER_KEY_CHARS",
                        "CLI_JOURNAL_WRITER"])
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

        # --- rt: the same question asked of a SENTENCE ------------------------
        # `redacted_text` is what admits a runner's own output into a committed
        # row, so every case above has a counterpart here: the field it guards is
        # the only one on an evidence row whose content this plugin did not
        # compose, and it is hash-chained like the rest.
        _frame = ("    at Object.<anonymous> (/Users/%s/work/shop/src/a.test.ts"
                  ":12:5)" % _user)
        _rt1 = M.redacted_text(proj, _frame)
        check("rt1 a path token inside a sentence is answered by the same map "
              "that answers one standing alone - the outside path becomes the "
              "token, the words around it survive, and the user name is gone "
              "from the whole line: %r" % (_rt1,),
              M.OUTSIDE_TOKEN in _rt1 and _rt1.count(_user) == 0
              and _rt1.startswith("    at Object.")
              # ...and the allow arm, which is the half that decides whether
              # anybody can read a redacted row: a repo-relative path a runner
              # printed is information, and a redactor that swallowed it too
              # would leave the field as useless as the silence it replaces.
              and M.redacted_text(proj, "FAILED tests/a_test.py::t - boom")
              == "FAILED tests/a_test.py::t - boom")

        _rt2 = [M.redacted_text(proj, t) for t in
                ("~/work/shop/src/a.ts blew up",
                 "C:\\Users\\%s\\shop\\a.ts blew up" % _user,
                 "\\\\build01\\share\\a.ts blew up")]
        check("rt2 the three spellings `repo_relative_or_token` would have taken "
              "for RELATIVE land on the token instead. It asks `os.path.isabs`, "
              "which is False on posix for a `~` path, a drive-letter path and a "
              "UNC share - so each would have been joined onto the repo root and "
              "handed back looking local with the machine still inside it. "
              "Measured: before that arm existed the first came back unchanged "
              "and the second came back as `C:/Users/...`: %r" % (_rt2,),
              [t.split(" ", 1)[0] for t in _rt2]
              == [M.OUTSIDE_TOKEN] * 3
              and sum(t.count(_user) for t in _rt2) == 0
              and all(t.endswith("blew up") for t in _rt2))

        # REDACT, THEN BOUND. The first fixture written for this asserted the
        # LEAK - that bounding first would keep a prefix of a home directory -
        # and the mutation battery reported it SURVIVED, because the claim is
        # false of a tail clip: the head of a token is what makes it
        # recognisable, and a tail cut never removes it. What the order really
        # decides is what the budget is SPENT on, so that is what this asserts.
        _far = ("at fn (/Users/%s/work/%s/a.ts) expected 90 received 100"
                % (_user, "d" * M.MAX_VALUE_CHARS))
        _rt3 = M.redacted_text(proj, _far)
        check("rt3 a long outside path collapses BEFORE the bound is spent, so "
              "the sentence after it - the part naming what actually went wrong "
              "- survives and the line is never cut at all. Bounding first would "
              "spend `MAX_VALUE_CHARS` on bytes that are about to become a "
              "token, and hand the reader a truncated frame with the finding "
              "missing off the end: %r" % (_rt3,),
              _rt3 == "at fn (%s) expected 90 received 100" % (M.OUTSIDE_TOKEN,)
              and not _rt3.endswith(M.VALUE_TRUNCATED)
              and len(_far) > M.MAX_VALUE_CHARS
              # ...and the leak is gone in EITHER order, which is why it is
              # asserted here and not claimed as this ordering's doing.
              and _rt3.count(_user) == 0)

        check("rt4 a lone separator is not a path, so ordinary prose survives - "
              "the over-firing direction, which is how a redactor stops being "
              "read as careful and starts being read as broken. And a value that "
              "is not a string is spelled before it is judged rather than "
              "reaching the regex as an object: %r"
              % (M.redacted_text(proj, "1 / 2 is not a path"),),
              M.redacted_text(proj, "1 / 2 is not a path")
              == "1 / 2 is not a path"
              and M.redacted_text(proj, "suite > renders a/b split")
              == "suite > renders a/b split"
              and M.redacted_text(proj, None) == ""
              and M.redacted_text(proj, 12) == "12")

        # ONE GRAMMAR, TWO BUDGETS. The evidence ledger's basis sentences carry
        # no value-sized bound and never did, so the second reader of this rule
        # could either clip a field it does not own or copy the substitution
        # into a table of its own. Neither is a choice worth offering, so the
        # rule and the bound are separate functions and this is what says the
        # bounded one is still the unbounded one wearing a cut.
        _rt5 = M.redacted_paths(proj, _far)
        check("rt5 `redacted_paths` answers every token the bounded form does "
              "and stops there: the same substitution, no cut, and the bounded "
              "form is that result clipped rather than a second pass over the "
              "text: %r" % (len(_rt5),),
              _rt5 == _rt3 and _rt5.count(_user) == 0
              and M.redacted_paths(proj, _frame) == M.redacted_text(proj,
                                                                    _frame))
        _rt6 = M.redacted_paths(proj, "x " + ("d" * (M.MAX_VALUE_CHARS * 2)))
        check("rt6 ...and a sentence longer than a journal value's budget comes "
              "back whole from it while the bounded form announces its cut - "
              "the case that fails if the two are collapsed back together: %r"
              % (len(_rt6),),
              len(_rt6) > M.MAX_VALUE_CHARS
              and not _rt6.endswith(M.VALUE_TRUNCATED)
              and M.redacted_text(
                  proj, "x " + ("d" * (M.MAX_VALUE_CHARS * 2))
              ).endswith(M.VALUE_TRUNCATED))

        # The environment is pinned ABSENT so this asserts the actor's key set
        # exactly, on a machine inside a session and on one that is not. `sa2`
        # next door is the other direction, with it set.
        _r10 = with_env(None, lambda: M._normalise(
            {"action": "config.write", "target": "x",
             "actor": {"host": "MacBook-Pro.local", "via": "panel",
                       "sessionId": "s1"}}, project=proj))
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
        # The journal-writes hook and the panel each file that claim in
        # `stateDir`, and guard-bash-writes subtracts it before it reads the
        # journal class; a MISSING claim looks like this from the operator's
        # chair - a warning about a write into the audit trail, a chain that
        # verifies clean, and no way to tell the two apart without checking by
        # hand.
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
        # a plugin that appended nothing - the same missing-claim gap reopened in
        # the quiet direction.
        _jw = _loader.load(os.path.join(_harness.HOOKS_DIR, "journal-writes.py"),
                           modname="journal_writes_for_pw", cache=False)
        _hookslot = _jw._sidecar_path(_pwp, {}, {"session_id": "panel"})
        check("pw1 the claim names the appended file REPO-RELATIVE, in the slot "
              "`journal-writes.py` would have used for the same key - one slot "
              "shape, two writers, and the guard looks in one place: %r"
              % (_held,),
              _held.get(M.PLUGIN_WRITE_KEY)
              == [_output.posix_rel(_pw1, _pwp)]
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
              == sorted(_output.posix_rel(p, _pwp)
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

        # THE KEY A CLI FILES UNDER AND THE KEY THE HOOK READS ARE TWO
        # LITERALS IN TWO FILES that may not share an import - `guard-bash-writes`
        # is a hook and the layer rule forbids it reaching into `scripts/` - so the
        # mirror is pinned the way `PLUGIN_SIDECAR` already is. DRIVEN, not
        # compared: `append_from_cli` is run and the slot it produced is the one
        # the hook's own template names for the hook's own constant, so a rename on
        # either side is red rather than quiet. Quiet is the direction that bites,
        # because a claim filed under a key nobody reads is indistinguishable from
        # a plugin that appended nothing.
        _gbw = _loader.load(os.path.join(_harness.HOOKS_DIR,
                                         "guard-bash-writes.py"),
                            modname="guard_bash_writes_for_pw", cache=False)
        _cliproj = os.path.join(tmp, "cliclaim")
        os.makedirs(_cliproj)
        _clipath = M.append_from_cli(_cliproj, {
            "action": "state.committed", "target": "",
            "actor": {"via": "commit-audit-state"}}, config=_pwcfg)
        _clislot = M.plugin_write_sidecar(_cliproj, _pwcfg, M.CLI_JOURNAL_WRITER)
        _cliheld = _claimed(_clislot) if _clislot and os.path.exists(_clislot) \
            else {}
        _clihook = os.path.join(os.path.dirname(_clislot or ""),
                                _gbw.PLUGIN_SIDECAR % _gbw.CLI_WRITER)
        check("pw5 a CLI's append files its claim under the key the HOOK reads: "
              "`append_from_cli` wrote %r and guard-bash-writes looks for %r - "
              "two literals in two files a hook may not import across, so the "
              "mirror is driven rather than asserted"
              % (os.path.basename(_clislot or ""), os.path.basename(_clihook)),
              bool(_clipath)
              and _gbw.CLI_WRITER == M.CLI_JOURNAL_WRITER
              and os.path.normpath(_clislot) == os.path.normpath(_clihook)
              and _cliheld.get(M.PLUGIN_WRITE_KEY)
              == [_output.posix_rel(_clipath, _cliproj)])

        # THE RULE, NOT THE INSTANCE. The gap was reported against one command and
        # was true of every script that appends: only the journal-writes hook and the
        # panel had ever filed a claim, so each of the others made the next Bash
        # command draw a notice about a write this plugin had just made. A case
        # pinning that one command would have left the class open and the next
        # writer added would reopen it in silence.
        _unclaimed, _sites = _unclaimed_journal_writers(os.path.basename(M.__file__))
        _anchors = set(["commit-audit-state.py", "audit-task.py",
                        "close-phase.py", "_panel_write.py"])
        _seen = set(os.path.basename(p) for p, _l, _n in _sites)
        check("pw6 every journal append under `scripts/` leaves the write guard "
              "something to subtract - through `append_from_cli`, or by filing "
              "the claim by hand where the ROW is needed too. Unclaimed %r, "
              "anchors found %r" % (_unclaimed, sorted(_anchors & _seen)),
              _unclaimed == [] and _anchors <= _seen)
        # SECOND-DIRECTION CASE, and the one that stops pw6 being satisfied by a
        # walk that swept the whole tree in: the discriminator is the ARITY, so a
        # module that appends to lists all day and never to the journal is not a
        # journal writer and is not being asked for a claim it does not owe.
        _lists = os.path.join(_harness.SCRIPTS_DIR, "_output.py")
        check("pw7 ...and the derivation is NARROW: `_output.py` appends to lists "
              "and never to the trail, so it is not in the writer set and pw6 is "
              "not passing by demanding a claim of every file: %r"
              % (_journal_append_sites(_lists),),
              _journal_append_sites(_lists) == []
              and os.path.basename(_lists) not in _seen)

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
        # a nicety. The panel used to hand its lock identity to the journal
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

        # --- ag: which AGENT of the session, and which is not an agent at all --
        # `sessionId` is shared by an orchestrator and every subagent it spawns,
        # so the trail could name the SESSION that changed the plan and never the
        # WRITER inside it. Two guards refuse a subagent the manifest; a refusal
        # with no record of who tripped it is half an answer.
        _ag_sub = with_env(None, lambda: M._normalise(
            {"action": "manifest.edit", "target": "",
             "actor": {"sessionId": "s1", "via": "hook",
                       "agent": "a6773d750dcfc821b"}}))
        _ag_orc = with_env(None, lambda: M._normalise(
            {"action": "manifest.edit", "target": "",
             "actor": {"sessionId": "s1", "via": "hook", "agent": "main"}}))
        check("ag1 a row caused by a SUBAGENT names it, and a row caused by the "
              "ORCHESTRATOR says so in words - two values in one field, not one "
              "value and a blank, because a reader of a committed file cannot "
              "tell 'the orchestrator did it' from 'nobody recorded it': "
              "%r vs %r" % (_ag_sub["actor"].get("agent"),
                            _ag_orc["actor"].get("agent")),
              _ag_sub["actor"]["agent"] == "a6773d750dcfc821b"
              and _ag_orc["actor"]["agent"] == "main"
              and _ag_sub["actor"]["agent"] != _ag_orc["actor"]["agent"])
        check("ag2 SECOND DIRECTION for r10: an agent adds exactly ONE key to "
              "the actor and no other, so a field that started carrying "
              "anything else fails here rather than being noticed by a reader",
              set(_ag_orc["actor"]) == set(["author", "sessionId", "via",
                                            "agent"]),
              repr(sorted(_ag_orc["actor"])))
        # THE WRITERS THAT ARE NOT AGENTS. The panel and the CLI append rows too
        # and no agent made them, so this module invents nothing: naming one
        # would be a guess, and the guess it would make is the orchestrator.
        _ag_panel = with_env(None, lambda: M._normalise(
            {"action": "config.write", "target": "",
             "actor": {"sessionId": "s1", "via": "panel"}}))
        check("ag3 a writer that names no agent gets no field - the panel and "
              "the CLI are not agents, and a default here would put a writer's "
              "name on a row it did not write: %r"
              % (sorted(_ag_panel["actor"]),),
              "agent" not in _ag_panel["actor"])
        for _blank in ("", "   ", None, "///"):
            _ag_b = with_env(None, lambda: M._normalise(
                {"action": "config.write", "target": "",
                 "actor": {"sessionId": "s1", "via": "hook",
                           "agent": _blank}}))
            check("ag4 an agent name that is blank or sanitises away leaves NO "
                  "field rather than an empty one: a row repeating a blank back "
                  "at its reader is the ambiguity the word exists to close "
                  "(%r)" % (_blank,),
                  "agent" not in _ag_b["actor"])
        _ag_junk = with_env(None, lambda: M._normalise(
            {"action": "config.write", "target": "",
             "actor": {"sessionId": "s1", "via": "hook",
                       "agent": "../../etc/passwd"}}))
        check("ag5 an agent name is sanitised and bounded before it reaches a "
              "COMMITTED row, exactly as the session ids beside it are - no "
              "separator and no traversal survives: %r"
              % (_ag_junk["actor"]["agent"],),
              _ag_junk["actor"]["agent"] == "etc-passwd"
              and len(M.agent_token("c" * 300)) == M.MAX_AGENT_CHARS)
        # THE CHAIN OVER A MIXED FILE. The field changes a row's BYTES, and the
        # hash covers whatever fields are present - so the question is not
        # whether a new row verifies but whether a file holding both generations
        # does. Same writer, same month, same file: an append reads the tail it
        # is chaining onto, and that tail is a row written before the field.
        _agp = os.path.join(tmp, "agentmix")
        os.makedirs(os.path.join(_agp, "j"))
        _agcfg = {"journal": {"dir": "j"}}
        _agactor = {"author": None, "sessionId": "ag-sess-1", "via": "hook"}
        _agname = "%s.ag-sess-1.jsonl" % time.strftime("%Y-%m", time.gmtime())
        _agold = {"v": 1, "ts": time.strftime("%Y-%m-%dT00:00:00Z",
                                              time.gmtime()),
                  "actor": dict(_agactor), "action": "manifest.edit",
                  "target": "", "summary": "written before the field existed",
                  "stateHash": None, "prev": M.genesis_prev(_agname)}
        _agold["hash"] = M.row_hash(_agold)
        with open(os.path.join(_agp, "j", _agname), "w",
                  encoding="utf-8") as fh:
            fh.write(M.canonical(_agold) + "\n")
        _agnewp = with_env(None, lambda: M.append(
            _agp, {"action": "manifest.edit", "target": "",
                   "summary": "written by a subagent",
                   "actor": dict(_agactor, agent="a6773d750dcfc821b")},
            config=_agcfg))
        _agver = M.verify(_agp, _agcfg)
        _agrows = M.read_file(os.path.join(_agp, "j", _agname))[0]
        check("ag6 one file holding a row from before the field and a row "
              "carrying it verifies clean, chain and all - the new row's `prev` "
              "is the OLD row's hash, so the two generations are one chain and "
              "not two: %r" % (_agver["findings"] + _agver["warnings"],),
              _agver["ok"] and not _agver["findings"]
              and not _agver["warnings"] and _agver["rows"] == 2
              and os.path.basename(_agnewp or "") == _agname
              and _agrows[1]["prev"] == _agold["hash"]
              and _agrows[0]["hash"] == _agold["hash"])
        check("ag7 ...and the old row is still readable as what it is: no "
              "agent, so nothing was back-filled onto a row nobody could ask. "
              "A migration that guessed here would have written the "
              "orchestrator over an unknown writer",
              "agent" not in _agrows[0]["actor"]
              and _agrows[1]["actor"]["agent"] == "a6773d750dcfc821b")

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

    # --- `attempt` joined the allow-list ---------------------------------------
    # `/audit:task scope` now accepts a WIDENING of `files` on a task that is
    # already running, and without the attempt on the row a trail cannot tell a
    # scope written BEFORE the work from one that grew DURING it - every reader
    # would take the second for the first. Same three tests `reason` and `runId`
    # passed: `task.attempts` is a field of the PLAN and not something observed
    # about the machine, the value is bounded like every other, and the number is
    # already in the manifest the row is about.
    _widen = {"taskId": "P2.3", "phaseId": "P2", "attempt": 2,
              "changes": [{"id": "P2.3", "field": "files",
                           "from": ["a.ts"], "to": ["a.ts", "b.ts"]}]}
    check("wa1 a widening's attempt SURVIVES into the row's details as a "
          "number, beside the changes it dates",
          M.normalise_details(_widen).get("attempt") == 2,
          repr(M.normalise_details(_widen)))
    # A RECORDED ZERO IS A VALUE, which is `_manifest_io.recorded_attempt`'s whole
    # shape: two documented paths take the count back down, so 0 is a thing the
    # plan SAYS. A clip or a truthiness test that dropped it would leave the row
    # unable to tell "scoped before any attempt" from "nobody recorded one", and
    # those are the two readings this key exists to separate.
    check("wa2 ...and a recorded ZERO survives too - the one value a truthiness "
          "test would silently turn into an absent key, which is the exact "
          "ambiguity the key was added to remove",
          M.normalise_details({"taskId": "P2.3", "attempt": 0})
          == {"taskId": "P2.3", "attempt": 0},
          repr(M.normalise_details({"taskId": "P2.3", "attempt": 0})))

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

    # --- mu/av/sa: a divergence, its merge, and the session a file belongs to --
    def _merge_cases(check):
        """One journal file on two branches, both written by the REAL writer.

        A hand-composed chain proves nothing about what `append` produces, so
        both sides here start from the same copied bytes -- which is what a
        branch actually is -- and every row on either side goes through
        `append`."""
        mcfg = {"journal": {"dir": "j"}}
        mtmp = tempfile.mkdtemp(prefix="journal-merge-")
        try:
            def put(root, action, summary, ts):
                return M.append(root, {"action": action, "target": "",
                                       "summary": summary, "ts": ts,
                                       "actor": {"sessionId": "s-div",
                                                 "via": "hook"}}, config=mcfg)

            def only(root):
                return M.journal_files(M.journal_dir(root, mcfg))[0]

            base = os.path.join(mtmp, "base")
            os.makedirs(base)
            put(base, "manifest.edit", "base-1", "2026-05-01T00:00:00Z")
            put(base, "manifest.edit", "base-2", "2026-05-01T00:00:01Z")
            name = os.path.basename(only(base))
            ours_root = os.path.join(mtmp, "ours")
            theirs_root = os.path.join(mtmp, "theirs")
            for root in (ours_root, theirs_root):
                shutil.copytree(base, root)
            # `theirs-1` sits BETWEEN ours' two rows, which is the shape the old
            # byte-prefix anchor could not survive: ours' second row keeps its
            # content and gets a new `prev`, so HEAD's bytes stop being a prefix
            # of a sound resolution. av4 is that half.
            put(ours_root, "task.complete", "ours-1", "2026-05-02T00:00:00Z")
            put(ours_root, "task.commit", "ours-2", "2026-05-05T00:00:00Z")
            put(theirs_root, "task.complete", "theirs-1", "2026-05-03T00:00:00Z")
            ours = M.read_file(only(ours_root))[0]
            theirs = M.read_file(only(theirs_root))[0]
            check("mu0 the fixture is a real divergence written by the real "
                  "writer: two shared rows, then two on one side and one on the "
                  "other, and neither file is a prefix of the other",
                  len(ours) == 4 and len(theirs) == 3
                  and M._common_prefix(ours, theirs) == 2
                  and ours[2]["hash"] != theirs[2]["hash"],
                  repr((len(ours), len(theirs))))

            res = M.merge_rows(ours, theirs, name)
            _sums = [r.get("summary") for r in res["rows"]]
            check("mu1 the union comes out in TIMESTAMP order with the other "
                  "side's row interleaved, and a `%s` row last: %r"
                  % (M.MERGE_ACTION, _sums),
                  res["ok"] and not res["refusals"]
                  and _sums[:5] == ["base-1", "base-2", "ours-1", "theirs-1",
                                    "ours-2"]
                  and res["rows"][-1]["action"] == M.MERGE_ACTION,
                  repr(res["refusals"] or _sums))
            check("mu2 nothing is dropped and nothing is added but the marker: "
                  "%d in, %d out" % (len(ours) + len(theirs) - res["shared"],
                                     len(res["rows"])),
                  res["shared"] == 2 and res["oursOnly"] == 2
                  and res["theirsOnly"] == 1
                  and len(res["rows"]) == len(ours) + len(theirs)
                  - res["shared"] + 1, repr(res))
            # SECOND DIRECTION, and the one that says re-chaining is not forgery:
            # a merge that rewrote a row's content would still produce a file
            # that verifies, so the assertion has to be about CONTENT and not
            # about the chain holding.
            #
            # COUNTED, NOT MERELY FOUND. This asserted `set(_in) <= set(_out)`
            # while its label claimed every row survives byte for byte, and set
            # inclusion cannot see a row that arrived twice or a duplicate that
            # was dropped -- the shape the label was promising to catch. The
            # expectation is spelled out instead: ours' rows plus the rows
            # theirs holds BEYOND the shared prefix, each exactly once, which is
            # what a union of two divergent copies is. The shared rows come
            # through `ours[:shared]` and equal-hash rows have equal content, so
            # which side they are read off does not matter. The marker is the
            # one row the merge adds, and mu1 is what pins it last.
            #
            # WHAT THIS FIXTURE CANNOT SHOW, said rather than implied: every row
            # in it says something different, so no duplicate exists here to be
            # dropped. mu14 is the fixture that carries one -- the same content
            # recorded by both copies -- and counts it out loud. What the count
            # buys HERE is the other half inclusion could not see: a row the
            # merge emitted more times than it was handed.
            _in = ([M.row_content(r) for r in ours]
                   + [M.row_content(r) for r in theirs[res["shared"]:]])
            _out = [M.row_content(r) for r in res["rows"][:-1]]
            _drift = sorted([(_in.count(c), _out.count(c), c[:48])
                             for c in set(_in) | set(_out)
                             if _in.count(c) != _out.count(c)])
            check("mu3 every input row's CONTENT survives byte for byte and "
                  "arrives exactly as often as it went in - only `prev`/`hash` "
                  "were recomputed, which is the whole claim re-chaining rests "
                  "on. Rows whose count moved: %r" % (_drift,),
                  sorted(_in) == sorted(_out))
            check("mu4 ...and `relinked` counts only the rows whose link "
                  "actually moved, so it is smaller than the tail: %d re-linked "
                  "of %d rows" % (res["relinked"], len(res["rows"])),
                  res["relinked"] == 2, repr(res["relinked"]))
            # `.get` and a guarded index THROUGHOUT this group, because a case
            # that raises is a case that took every case after it down with it
            # and named none of them: proving these red means deleting the
            # marker and deleting the field, and both make a key absent.
            _marker = res["rows"][-1] if res["rows"] else {}
            check("mu5 the marker row says what was done to the file and names "
                  "both inputs by a digest, so the trail itself records the "
                  "re-chaining rather than leaving it to git alone",
                  (_marker.get("actor") or {}).get("via") == M.MERGE_VIA
                  and name in (_marker.get("summary") or "")
                  and M.rows_digest(ours) in (_marker.get("summary") or "")
                  and M.rows_digest(theirs) in (_marker.get("summary") or "")
                  and _marker.get("target") == ""
                  and _marker.get("stateHash", "unset") is None,
                  repr(_marker))
            # The half that makes the verb usable rather than merely present:
            # the file it writes has to be one `verify` calls clean.
            M.write_merged(only(ours_root), M.merge_text(res["rows"]))
            _mver = M.verify(ours_root, mcfg)
            check("mu6 the merged file WRITES BACK and verifies clean - every "
                  "row hashes to its own contents and follows the row before "
                  "it, from the genesis the file name seeds",
                  _mver["ok"] and not _mver["findings"]
                  and _mver["rows"] == len(res["rows"]),
                  repr(_mver["findings"]))

            # --- the three refusals, each on its own fixture ------------------
            # An abandoned first attempt at the tie fixture stood here: two
            # locals and a whole `merge_rows` whose result nothing read, which
            # is a case that looks like coverage and is none. `ruff`'s own
            # unused-local rule cannot see it either, because the underscore
            # prefix every local in
            # this suite wears matches its dummy-variable pattern. The tie
            # fixture that works is the one below, built one row DEEPER.
            _same_ts = os.path.join(mtmp, "same-ts")
            shutil.copytree(base, _same_ts)
            put(_same_ts, "task.cancel", "collides", "2026-05-02T00:00:00Z")
            _collide = M.read_file(only(_same_ts))[0]
            _res_tie = M.merge_rows(ours, _collide, name)
            check("mu7 REFUSAL 1: two rows at ONE timestamp saying different "
                  "things is refused, and the refusal names both and says why "
                  "nothing can order them: %s"
                  % (_output.some_of(_res_tie["refusals"]),),
                  not _res_tie["ok"] and not _res_tie["rows"]
                  and len(_res_tie["refusals"]) == 1
                  and "2026-05-02T00:00:00Z" in _res_tie["refusals"][0]
                  and "task.complete(" in _res_tie["refusals"][0]
                  and "task.cancel(" in _res_tie["refusals"][0],
                  repr(_res_tie["refusals"]))
            _broken = [dict(r) for r in theirs]
            _broken[2] = dict(_broken[2])
            _broken[2]["summary"] = "edited after it was written"
            _res_broken = M.merge_rows(ours, _broken, name)
            check("mu8 REFUSAL 2: a row that does not hash to its own contents "
                  "is refused and SAID to have been already broken - a merge "
                  "would have recomputed that hash and laundered it: %s"
                  % (_output.some_of(_res_broken["refusals"]),),
                  not _res_broken["ok"] and not _res_broken["rows"]
                  and any("does not hash to its own contents" in f
                          and "already broken" in f
                          for f in _res_broken["refusals"]),
                  repr(_res_broken["refusals"]))
            _other = os.path.join(mtmp, "stranger")
            os.makedirs(_other)
            put(_other, "manifest.edit", "not-related-1",
                "2026-05-01T00:00:00Z")
            put(_other, "manifest.edit", "not-related-2",
                "2026-05-01T00:00:01Z")
            _stranger_file = only(_other)
            _stranger = M.read_file(_stranger_file)[0]
            _res_far = M.merge_rows(ours, _stranger, name)
            check("mu9 REFUSAL 3: two files that share no leading row are two "
                  "unrelated chains rather than one divergence, and unioning "
                  "them would invent a common past: %s"
                  % (_output.some_of(_res_far["refusals"]),),
                  not _res_far["ok"] and not _res_far["rows"]
                  and any("share no leading row" in f
                          for f in _res_far["refusals"]),
                  repr(_res_far["refusals"]))
            # THE FIXTURE HAD TO BE CHECKED, not assumed: the stranger is a
            # different PROJECT but the same writer and month, so it carries the
            # same file name and begins at the SAME genesis. That is what makes
            # mu9 the no-common-prefix refusal rather than the genesis one -
            # two whole files, both valid under this name, sharing no history.
            check("mu9b ...and mu9 is that refusal and not the genesis one: the "
                  "stranger is a whole file under this very name, so only its "
                  "history is unrelated: %r"
                  % ([f[:32] for f in _res_far["refusals"]],),
                  os.path.basename(_stranger_file) == name
                  and _stranger[0]["prev"] == M.genesis_prev(name)
                  and len(_res_far["refusals"]) == 1,
                  repr(os.path.basename(_stranger_file)))

            _res_torn = M.merge_rows(ours, theirs, name, torn=("theirs",))
            check("mu10 a TORN input is refused: a partial line is not a row, "
                  "so a merge that read past it would drop those bytes with "
                  "nothing in the output to say they were ever there",
                  not _res_torn["ok"]
                  and any("partial line" in f for f in _res_torn["refusals"]),
                  repr(_res_torn["refusals"]))
            _undated = [dict(r) for r in theirs]
            _undated[2] = dict(_undated[2])
            del _undated[2]["ts"]
            _undated[2]["hash"] = M.row_hash(_undated[2])
            _res_undated = M.merge_rows(ours, _undated, name)
            check("mu11 a divergent row with NO timestamp is refused - "
                  "timestamp order is the only order a merge has between two "
                  "copies, so there is nowhere to put it",
                  not _res_undated["ok"]
                  and any("carry no timestamp" in f
                          for f in _res_undated["refusals"]),
                  repr(_res_undated["refusals"]))
            _res_name = M.merge_rows(ours, theirs, "2026-05.someone-else.jsonl")
            check("mu12 a name that does not seed these chains is refused: the "
                  "genesis is derived from the BASENAME, so writing the result "
                  "under the wrong name would produce a file that cannot verify",
                  not _res_name["ok"]
                  and any("does not begin at the genesis" in f
                          for f in _res_name["refusals"]),
                  repr(_res_name["refusals"]))

            # --- and the answers that are NOT refusals ------------------------
            _res_ff = M.merge_rows(ours, ours[:2], name)
            check("mu13 one side being a PREFIX of the other is no divergence "
                  "and no error: the longer copy already holds every row, "
                  "nothing is re-chained and no marker row is added",
                  _res_ff["ok"] and _res_ff["relinked"] == 0
                  and not _res_ff["divergent"]
                  and len(_res_ff["rows"]) == len(ours)
                  and _res_ff["rows"][-1]["action"] != M.MERGE_ACTION
                  and any("no divergence" in n for n in _res_ff["notes"]),
                  repr((_res_ff["notes"], _res_ff["relinked"])))
            # A row both sides recorded IDENTICALLY right after the split folds
            # into the common prefix instead (same content, same `prev`, so the
            # same hash) - which is why the tie has to be built one row DEEPER,
            # where the two copies place the same content on different pasts.
            _twin = os.path.join(mtmp, "twin")
            shutil.copytree(base, _twin)
            put(_twin, "task.cancel", "twin-only", "2026-05-03T00:00:00Z")
            put(_twin, "task.commit", "ours-2", "2026-05-05T00:00:00Z")
            _res_twin = M.merge_rows(ours, M.read_file(only(_twin))[0], name)
            check("mu14 a row BOTH copies recorded at one timestamp, saying the "
                  "same thing, is kept TWICE and counted out loud - dropping "
                  "one is a guess that two identical rows were one event, and a "
                  "union guesses nothing: %r" % (_res_twin["notes"],),
                  _res_twin["ok"] and _res_twin["identical"] == 2
                  and [r.get("summary")
                       for r in _res_twin["rows"]].count("ours-2") == 2
                  and any("BOTH copies are kept" in n
                          for n in _res_twin["notes"]),
                  repr((_res_twin["identical"], _res_twin["notes"])))
            # `a` is deliberately NOT in timestamp order: a stable sort on `ts`
            # would emit a2, b1, a1 and thereby reorder `a` against itself,
            # which is the one thing a merge of two recorded chains may not do.
            _a = [{"ts": "2026-05-09T00:00:00Z", "side": "a1"},
                  {"ts": "2026-05-04T00:00:00Z", "side": "a2"}]
            _b = [{"ts": "2026-05-06T00:00:00Z", "side": "b1"}]
            _order = [r["side"] for r in M._merge_tails(_a, _b)]
            check("mu15 the interleave is a MERGE and never a sort: each side "
                  "comes out in the order it went in even when its own rows are "
                  "not in timestamp order, where a sort would have reordered "
                  "one against itself: %r" % (_order,),
                  [s for s in _order if s.startswith("a")] == ["a1", "a2"]
                  and _order == ["b1", "a1", "a2"])

            # `write_merged` RAISES where `append` returns False, and the two
            # contracts are opposite on purpose: `append` records a write that
            # already succeeded, so a failure there must not be reported as the
            # write failing - while this IS the write, and a caller told it went
            # fine would go on to commit a conflicted file.
            #
            # THE FIXTURE HAS TO REACH `os.replace`, AND THE FIRST ONE DID NOT.
            # It named a path under a directory that does not exist, so
            # `_acquire` died opening the lock beside it and the try/except this
            # case is named for was never entered - proved by mutation: turning
            # that block's `raise` into a `return` of the path, which reports a
            # write that failed as one that succeeded, left the whole suite
            # green. The leftover half could not fail either, because it
            # searched the temp ROOT while the temporary would have been written
            # one directory down, in a directory that was not there.
            #
            # A destination that EXISTS AS A DIRECTORY reaches it: the lock is
            # taken beside it, the temporary is written, and no platform will
            # rename a file onto a directory. The three properties of that
            # branch then fail apart, which is why they are three cases.
            _blocked = os.path.join(mtmp, "blocked")
            os.makedirs(_blocked)
            _dest = os.path.join(_blocked, "x.jsonl")
            os.makedirs(_dest)
            _bad = _harness.attempt(M.write_merged, _dest, "{}")
            check("mu16 a merge that could not be written says so by RAISING, "
                  "where `append` in the same position returns False - and the "
                  "destination it could not replace is untouched: %r" % (_bad,),
                  _bad[0] is False and os.path.isdir(_dest))
            check("mu16b ...and it leaves no half-written temporary behind IN "
                  "THE DIRECTORY IT WOULD HAVE WRITTEN ONE INTO - `.jsonl` is "
                  "what `journal_files` matches, so such a file would never be "
                  "read, but it would sit in `git status` as an untracked file "
                  "in the trail's own directory, which is exactly the shape "
                  "`guard-bash-writes` reports: %r"
                  % (sorted(os.listdir(_blocked)),),
                  not [n for n in os.listdir(_blocked)
                       if n.endswith(".merged")])
            # SECOND DIRECTION on the same branch, and the only thing that can
            # reach the `finally`: an append and a merge take ONE lock per file,
            # so a write that raised while holding it would refuse every writer
            # after it for the lock's whole stale window - a journal that has
            # gone read-only with nothing saying so.
            os.rmdir(_dest)
            _after = _harness.attempt(M.write_merged, _dest, "{}")
            # `isfile` as well as the outcome, because proving the mv cases red
            # means mutating `write_merged` into one that RETURNS without
            # writing - and an unguarded `open` here would then raise, take
            # every case after it out of the run and name none of them.
            # The assertion below still fails when nothing was written.
            _wrote = None
            if _after[0] is True and os.path.isfile(_dest):
                with open(_dest, "r", encoding="utf-8") as fh:
                    _wrote = fh.read()
            check("mu16c ...and the lock it took is RELEASED even though the "
                  "write raised, so the next writer of that file is not turned "
                  "away by a lock nobody holds: %r" % (_after,),
                  _after[0] is True and _wrote == "{}")

            # --- mv: the grade and the replace are ONE lock hold ---------------
            # The command used to read the target, grade the result against it
            # and only then call this - so the read happened before any lock
            # existed and a row appended in between was graded by nobody and
            # deleted by `os.replace`, at exit 0, with `verify` calling the
            # survivors clean. The repair is that `write_merged` reads, grades
            # and replaces inside one `_acquire`, and the grader is what the
            # caller hands in.
            #
            # ASSERTED FROM INSIDE THE GRADER, which is the only place the
            # question can be asked without a race: while it runs, does the
            # lock file exist? Moving the grade call back outside the
            # `_acquire`/`_release` pair turns mv1 red with nothing else
            # touched. The neighbour case next door drives a REAL concurrent
            # append through two processes; this one is the deterministic pin
            # under it.
            def _val(obj, key):
                """`obj[key]`, or None when `obj` cannot be asked.

                A CASE THAT RAISES TAKES EVERY CASE AFTER IT OUT OF THE RUN AND
                NAMES NONE, and proving the mv cases red means changing
                what `write_merged` RETURNS - the bare path it used to, or a
                dict missing the key - so an unguarded index is precisely the
                shape that would go down instead of going red."""
                try:
                    return obj[key]
                except Exception:
                    return None

            _lockstate = {"held": None, "saw": None, "unreadable": "unset"}
            _mvdir = os.path.join(mtmp, "onehold")
            os.makedirs(_mvdir)
            _mvfile = os.path.join(_mvdir, "held.jsonl")
            with open(_mvfile, "w", encoding="utf-8") as fh:
                fh.write("first\n")

            def _watching_grade(text, unreadable):
                _lockstate["held"] = os.path.exists(_mvfile + ".lock")
                _lockstate["saw"] = text
                _lockstate["unreadable"] = unreadable
                return []

            _mv = M.write_merged(_mvfile, "second\n", _watching_grade)
            with open(_mvfile, "r", encoding="utf-8") as fh:
                _mvafter = fh.read()
            check("mv1 the grader runs with the lock ALREADY HELD, so no append "
                  "can land between the bytes it graded and the bytes "
                  "`os.replace` overwrites -- which is the whole point of "
                  "holding the lock across both, and the lock file's existence "
                  "is the only evidence of it that cannot itself race: %r"
                  % (_lockstate["held"],),
                  _lockstate["held"] is True)
            check("mv2 ...and it is handed what the file held AT THAT MOMENT, "
                  "read inside the same hold rather than by the caller before "
                  "it: %r" % (_lockstate["saw"],),
                  _lockstate["saw"] == "first\n"
                  and _lockstate["unreadable"] is None)
            check("mv3 ...and with nothing refused the write went through and "
                  "the lock was released, so the next writer is not turned "
                  "away by a lock nobody holds",
                  _val(_mv, "written") is True and _val(_mv, "refusals") == []
                  and _mvafter == "second\n"
                  and not os.path.exists(_mvfile + ".lock"))
            # SECOND DIRECTION, and the mutation this repair could have made
            # instead: a grader whose answer is ignored. A refusal is not an
            # exception - nothing was attempted - so it comes back as data, and
            # the bytes on disk are what says it was honoured.
            _refuse = M.write_merged(_mvfile, "third\n",
                                     lambda text, unreadable: ["no"])
            with open(_mvfile, "r", encoding="utf-8") as fh:
                _mvrefused = fh.read()
            check("mv4 a grader that refuses stops the write and says so as "
                  "DATA rather than by raising - nothing was attempted, so "
                  "there is no failure to report - and the file is byte for "
                  "byte the one it was handed: %r" % (_refuse,),
                  _val(_refuse, "written") is False
                  and _val(_refuse, "refusals") == ["no"]
                  and _mvrefused == "second\n"
                  and not os.path.exists(_mvfile + ".merged"))
            _dry = {"held": None}

            def _dry_grade(text, unreadable):
                _dry["held"] = os.path.exists(_mvfile + ".lock")
                return []

            _mvdry = M.write_merged(_mvfile, "fourth\n", _dry_grade,
                                    dry_run=True)
            with open(_mvfile, "r", encoding="utf-8") as fh:
                _mvstill = fh.read()
            check("mv5 `dry_run` grades under the same hold and writes nothing, "
                  "so a preview is graded against a file nothing was appending "
                  "to either -- the flag that withholds the write must not also "
                  "withhold the question",
                  _dry["held"] is True and _val(_mvdry, "written") is False
                  and _val(_mvdry, "refusals") == []
                  and _mvstill == "second\n")
            # An UNREADABLE target reaches the grader as one, rather than as an
            # empty read that would clear a merge of everything nobody could
            # see. A directory is how "there and unreadable" is spelled
            # portably: `open` raises on it everywhere, while a mode of 000 is
            # no obstacle to root, which is who CI containers usually are.
            _mvdirtarget = os.path.join(_mvdir, "adir.jsonl")
            os.makedirs(_mvdirtarget)
            _seen = {}

            def _dir_grade(text, unreadable):
                _seen["text"], _seen["why"] = text, unreadable
                return ["unreadable"] if unreadable is not None else []

            _mvbad = M.write_merged(_mvdirtarget, "x\n", _dir_grade)
            check("mv6 a target that is THERE and cannot be read reaches the "
                  "grader as unreadable and not as an empty file, so the "
                  "refusal is the grader's to make rather than a reassuring "
                  "blank the guard clears: %r" % (_seen.get("why"),),
                  _seen.get("text") == "" and _seen.get("why")
                  and _val(_mvbad, "written") is False
                  and _val(_mvbad, "refusals") == ["unreadable"]
                  and os.path.isdir(_mvdirtarget))

            # --- av: what the git anchor asks now ----------------------------
            _committed = M.merge_text(ours[:3])
            _appended = M.merge_text(ours)
            _av1 = M.anchor_verdict(_committed, _appended)
            check("av1 an APPEND leaves every committed row where it was, so "
                  "the verdict holds and says how many rows arrived alongside",
                  _av1["held"] and _av1["extra"] == 1
                  and _av1["committedRows"] == 3, repr(_av1))
            _edited = [dict(r) for r in ours]
            _edited[0] = dict(_edited[0])
            _edited[0]["summary"] = "nothing happened"
            _rechained, _ = M._rechain(_edited, name)
            _av2 = M.anchor_verdict(_committed, M.merge_text(_rechained))
            check("av2 a committed row whose CONTENT was edited fails the "
                  "verdict and is named by row and action, even though the "
                  "whole file was re-chained and every hash is correct - which "
                  "is the forgery the byte prefix caught and this must keep "
                  "catching",
                  not _av2["held"] and _av2["row"] == 1
                  and _av2["action"] == "manifest.edit", repr(_av2))
            _av3 = M.anchor_verdict(_committed, M.merge_text(ours[:2]))
            check("av3 a committed row REMOVED fails the verdict too - the "
                  "cheapest forgery that leaves the remaining chain intact",
                  not _av3["held"] and _av3["row"] == 3, repr(_av3))
            # HEAD is OURS' WHOLE FILE here, which is what a branch commits, and
            # the reason this is the case the byte prefix could not survive:
            # `ours-2` keeps its content and gets a new `prev`, so the committed
            # bytes stop being a prefix of a resolution that dropped nothing.
            _committed4 = M.merge_text(ours)
            _merged4 = M.merge_text(res["rows"])
            _av4 = M.anchor_verdict(_committed4, _merged4)
            check("av4 THE CASE THE OLD PROXY COULD NOT SURVIVE: after a merge "
                  "the other side's row sits BETWEEN two committed ones, so "
                  "HEAD's bytes are no longer a prefix (%r) - and every "
                  "committed row is still present, in order, with its content "
                  "unchanged, which is the property that replaced it"
                  % (_merged4.startswith(_committed4),),
                  _av4["held"] and _av4["divergesAt"] == 4
                  and _av4["committedRows"] == 4
                  and not _merged4.startswith(_committed4), repr(_av4))
            _av5 = M.anchor_verdict(_committed,
                                    M.merge_text([ours[1], ours[0], ours[2]]))
            check("av5 committed rows REORDERED fail the verdict - the property "
                  "is presence AND order, and a check that only asked whether "
                  "each row was somewhere in the file would pass this",
                  not _av5["held"], repr(_av5))
            _av6 = M.anchor_verdict("", _appended)
            check("av6 nothing committed yet holds trivially and says so with a "
                  "zero rather than an empty-set silence",
                  _av6["held"] and _av6["committedRows"] == 0, repr(_av6))
            # THE CASE THE DOCSTRING ANTICIPATES AND NOTHING PINNED: a committed
            # copy re-spelled by something that does not write canonical JSON.
            # The bytes differ, so the fast prefix path in `_git_anchor_finding`
            # fails and this runs - and then nothing diverged at all, which is
            # the ONE way `divergesAt` comes back None while `held` is true. The
            # key is asserted absent rather than defaulted, because the reader
            # of that key is prose that says which row the two copies part at,
            # and there is no such row here. `_git_anchor_finding` currently
            # substitutes the first row for the missing one and tells the reader
            # the file parted from its committed copy at the beginning; that is
            # a defect in the WARNING, not in this verdict, and it is reachable
            # only from a real repository, which `check-git-pipeline.py` owns.
            _respelt = "".join(
                json.dumps(r, sort_keys=False, indent=None,
                           separators=(", ", ": ")) + "\n" for r in ours[:3])
            _av7 = M.anchor_verdict(_respelt, _committed)
            check("av7 a committed copy re-spelled non-canonically holds: every "
                  "row's content is the same content, so nothing diverged and "
                  "`divergesAt` is ABSENT rather than a row number no reader "
                  "could act on - and nothing arrived alongside",
                  _av7["held"] and _av7["divergesAt"] is None
                  and _av7["extra"] == 0
                  and _av7["committedRows"] == _av7["workingRows"]
                  and _respelt != _committed, repr(_av7))

            # --- ru: presence WITHOUT order, for the conflicted-file path -----
            # `rows_unaccounted` is the from_index half of the same repair that
            # added `anchor_verdict`. Its whole reason to exist apart from
            # `anchor_verdict` is that it must NOT
            # ask about order: the text it grades is a conflicted working copy,
            # two index stages with markers between them, an order no chain
            # ever had. So the pair below is the specification - reordering is
            # fine, absence is not - and ru3 is the one that separates this
            # from the rule one function up.
            _ru_rows = M.rows_from_text(_committed)[0]
            _ru_shuffled = M.merge_text(list(reversed(_ru_rows)))
            _ru1 = M.rows_unaccounted(_committed, _ru_shuffled)
            check("ru1 every row present but REORDERED is accounted for - the "
                  "property `anchor_verdict` deliberately refuses and this one "
                  "must allow, or a genuine conflict resolution is refused for "
                  "the order git left in the file",
                  _ru1["missing"] == 0 and _ru1["row"] is None
                  and _ru1["haveRows"] == len(_ru_rows), repr(_ru1))
            _ru2 = M.rows_unaccounted(_committed,
                                      M.merge_text(_ru_rows[:1]))
            check("ru2 ...and a row the result does not carry AT ALL is the "
                  "finding, named by position and action so the sentence reads "
                  "like the other refusal's",
                  _ru2["missing"] == len(_ru_rows) - 1 and _ru2["row"] == 2
                  and _ru2["action"], repr(_ru2))
            # A conflicted file legitimately holds the same row TWICE - both
            # sides appended identical content to their own tails - while the
            # union holds it once. A COUNTING test calls that a loss.
            _ru_dup = _committed + M.merge_text(_ru_rows[-1:])
            _ru3 = M.rows_unaccounted(_ru_dup, _committed)
            check("ru3 a row the file carries TWICE and the result once is NOT "
                  "a loss - this is a set question, and the opposite of the "
                  "count-do-not-find rule that applies to `mu3`, because here "
                  "the duplication is what resolving a conflict produces",
                  _ru3["missing"] == 0, repr(_ru3))
            # ALL OF THEM, NOT THE FIRST OF THEM. `row`/`action` name
            # whichever unaccounted row sits earliest in the file, and the
            # caller has to tell a row somebody TYPED while resolving from a
            # `journal.merge` row a previous run of the verb left - two
            # findings with two repairs. Which one `row` happened to name
            # depended on the wall-clock second the two runs landed in, because
            # the marker's timestamp moves; the whole list is what lets the
            # caller sort them by what they ARE.
            _ru4 = M.rows_unaccounted(_committed, M.merge_text(_ru_rows[1:2]))
            # `.get` with a list default, for the same reason every read in the
            # mu group is guarded: proving this red means DELETING the key, and
            # an unguarded index would take every case after it down while
            # naming none of them.
            _ru4gone = _ru4.get("unaccounted")
            _ru4gone = _ru4gone if isinstance(_ru4gone, list) else []
            check("ru4 every unaccounted row comes back, in file order, with "
                  "the position and the action of each - and `missing` is the "
                  "length of that list rather than a second opinion about it: "
                  "%r" % (_ru4.get("unaccounted"),),
                  [pair[0] for pair in _ru4gone] == [1, 3]
                  and _ru4["missing"] == len(_ru4gone)
                  and _ru4["row"] == _ru4gone[0][0]
                  and _ru4["action"] == _ru4gone[0][1]
                  and all(isinstance(pair[1], str) for pair in _ru4gone),
                  repr(_ru4))
            # SECOND DIRECTION, and the one that reads as vacuous and is not:
            # an empty list is what a caller partitions to nothing, and a key
            # that came back None or absent instead would make every caller's
            # filter raise or silently skip. ru1 already asserts `missing` is
            # zero here; this asserts the SHAPE the callers iterate.
            check("ru5 ...and a result that accounts for everything hands back "
                  "an empty list rather than None, so a caller that partitions "
                  "it finds nothing instead of failing to look",
                  _ru1.get("unaccounted", "absent") == []
                  and _ru3.get("unaccounted", "absent") == [])

            # --- aw: the prose the anchor's WARNING actually says -------------
            # THE HIGHEST-STAKES TEXT IN THE MODULE AND NOTHING COULD REACH IT.
            # It was built at `_git_anchor_finding`'s return, which needs a real
            # repository, and the one gate that has one asserts the FINDING's
            # words. Both defects below sat in it green: a pointer at a merge
            # commit that exists under only one of the two readings this check
            # cannot distinguish, and a substituted row number for the reading
            # where no row diverged at all (av7's input).
            with open(M.__file__, "r", encoding="utf-8") as fh:
                _jio_tree = ast.parse(fh.read(), filename=M.__file__)
            _, _jio_funcs = _module_consts_and_funcs(_jio_tree)
            _anchor_reads = set(
                n.id for n in ast.walk(_jio_funcs["_git_anchor_finding"])
                if isinstance(n, ast.Name))
            check("aw0 the text the cases below judge is the text the ANCHOR "
                  "emits: `_git_anchor_finding` names `_anchor_warning` rather "
                  "than formatting its own, so re-inlining the string would "
                  "fail here instead of leaving these cases grading a helper "
                  "nothing calls: %r"
                  % (sorted(n for n in _anchor_reads
                            if n.startswith("_anchor")),),
                  "_anchor_warning" in _anchor_reads)
            # `.find` and never `.index` for the ORDER conjunct below: a missing
            # substring has to be this case going red, not a ValueError taking
            # every case after it down with it and naming none of them.
            #
            # AND THE VERDICTS ARE THE REAL ONES, not two dicts written here to
            # the shape this text expects: `_av4` is the post-merge file av4
            # already graded and `_av7` the re-spelling, so the row numbers in
            # the sentence below are numbers a real divergence produced.
            _indistinct = "NOTHING IN THIS CHECK CAN TELL THOSE APART"
            _aw_div = M._anchor_warning(name, _av4, name)
            check("aw1 the divergent reading names the row the copies part at "
                  "and the rows that arrived, and says outright that NOTHING "
                  "HERE separates a resolution from a row spliced between "
                  "committed ones - the evidence that would is named instead "
                  "of assumed: %r" % (_aw_div,),
                  "from row 4 on" in _aw_div and _indistinct in _aw_div
                  and M.MERGE_ACTION in _aw_div and name in _aw_div)
            # The sentence used to end "the merge commit is where you check
            # which side the extra rows came from", which is a place that exists
            # under the merge reading and under no other. A merge commit may
            # still be NAMED - it is where the answer is when there was one -
            # but never as the place to look without the disclaimer beside it,
            # which is what this counts rather than merely finds.
            check("aw2 ...and it does not send the reader to a merge commit as "
                  "if one must exist: the words are there only in the sentence "
                  "that also says the two readings are indistinguishable, and "
                  "the old unconditional pointer is gone",
                  "where you check which side" not in _aw_div
                  and _aw_div.count("merge commit") == 1
                  and _aw_div.find("merge commit")
                  > _aw_div.find(_indistinct) > -1)
            _aw_same = M._anchor_warning(name, _av7, name)
            # Every number is stripped by removing the FILE NAME, which is the
            # only thing in this sentence entitled to carry digits: what the old
            # text put here was a row number, and asserting the absence of one
            # literal spelling of it would pass the next substitution just as
            # quietly.
            _aw_same_nums = [c for c in _aw_same.replace(name, "")
                             if c.isdigit()]
            check("aw3 SECOND DIRECTION, on av7's input: where NO row diverged "
                  "the reading gets its own sentence, and it carries NO NUMBER "
                  "AT ALL beyond the file's own name and no pointer at a merge "
                  "- there was no merge and no row to name. This said `from row "
                  "1 on` about a divergence that did not happen: %r"
                  % (_aw_same,),
                  "no row diverged" in _aw_same
                  and "from row" not in _aw_same
                  and "merge commit" not in _aw_same
                  and _aw_same_nums == [] and name in _aw_same)

            # --- an: the answer for a question that could not be put ---------
            # THE ANCHOR USED TO ANSWER `None` TWICE OVER: once for a file whose
            # committed past it had read and found intact, and once for every
            # inability to read one at all - no git, an untracked file, itself
            # raising. So the state this check exists for was reported with the
            # same byte as the state where it never looked, and a reader could
            # not tell a clean tree from a broken anchor. These grade the third
            # answer: `status` says whether the question was PUT, `why` says
            # which inability stopped it, and neither is ever a finding.
            _an_reads = set(
                n.id for n in ast.walk(_jio_funcs["_git_anchor_finding"])
                if isinstance(n, ast.Name))
            check("an0 the third answer and the pointer are both BUILT rather "
                  "than spelled at each return: `_git_anchor_finding` names "
                  "`_anchor_unasked` and `_anchor_pointer`, so a return that "
                  "went back to a bare None - or an invocation re-inlined at "
                  "one branch and not the other - fails here rather than "
                  "leaving the cases below grading helpers nothing calls: %r"
                  % (sorted(n for n in _an_reads if n.startswith("_anchor")),),
                  "_anchor_unasked" in _an_reads
                  and "_anchor_pointer" in _an_reads
                  and "_anchor_asked" in _an_reads)
            check("an1 the pointer names the OBJECT the anchor landed on, "
                  "directory and all: git resolves a bare `HEAD:<name>` from "
                  "the repository ROOT while the anchor reads it beside the "
                  "file, and under the archive seam the committed copy is one "
                  "level up - so a reader handed the bare name chases a path "
                  "git holds nothing at: %r"
                  % ((M._anchor_pointer("/j", "m.jsonl"),
                      M._anchor_pointer("/j/archive", "m.jsonl", up=True)),),
                  M._anchor_pointer("/j", "m.jsonl")
                  == "git -C /j show HEAD:./m.jsonl"
                  and M._anchor_pointer("/j/archive", "m.jsonl", up=True)
                  == "git -C /j/archive show HEAD:../m.jsonl")
            check("an2 ...and both messages carry that invocation verbatim, "
                  "which is the half a reader acts on - the warning for a file "
                  "whose links moved and the one for a file whose bytes were "
                  "rewritten with no row diverging",
                  M._anchor_pointer("/j", name)
                  in M._anchor_warning(name, _av4, M._anchor_pointer("/j", name))
                  and M._anchor_pointer("/j", name)
                  in M._anchor_warning(name, _av7,
                                       M._anchor_pointer("/j", name)))
            _an_dir = tempfile.mkdtemp(prefix="journal-anchor-")
            try:
                _an_file = os.path.join(_an_dir, "m.jsonl")
                with open(_an_file, "w", encoding="utf-8") as _fh:
                    _fh.write("{}\n")
                _an_none = M._git_anchor_finding(_an_file)
                check("an3 a file no committed copy can be read for answers "
                      "`could-not-ask` WITH THE REASON, and carries neither a "
                      "finding nor a warning - the answer a clean file used to "
                      "be indistinguishable from: %r" % (_an_none,),
                      _an_none["status"] == M.ANCHOR_CANNOT
                      and isinstance(_an_none["why"], str)
                      and _an_none["why"] != ""
                      and _an_none["finding"] is None
                      and _an_none["warning"] is None)
            finally:
                shutil.rmtree(_an_dir, ignore_errors=True)

            # --- sa: the session a writer id cannot name ---------------------
            _sa_actor = {"sessionId": "payload-id-aaaa", "via": "hook"}
            _sa1 = with_env("env-id-bbbb", lambda: M._normalise(
                {"action": "manifest.edit", "target": "",
                 "actor": dict(_sa_actor)}))
            check("sa1 a row records the OTHER id its session answers to, which "
                  "is what makes a file named for the payload id resolvable: "
                  "%r" % (sorted(_sa1["actor"]),),
                  _sa1["actor"].get("envSessionId") == "env-id-bbbb"
                  and _sa1["actor"].get("sessionId") == "payload-id-aaaa")
            check("sa2 SECOND DIRECTION for r10: with the environment naming a "
                  "session the actor gains exactly ONE key and no other, so a "
                  "field that started carrying anything else fails here rather "
                  "than being noticed by a reader",
                  set(_sa1["actor"]) == set(["author", "sessionId", "via",
                                             "envSessionId"]),
                  repr(sorted(_sa1["actor"])))
            _sa3 = with_env("payload-id-aaaa", lambda: M._normalise(
                {"action": "manifest.edit", "target": "",
                 "actor": dict(_sa_actor)}))
            check("sa3 ...and it is recorded ONLY when it differs: an "
                  "environment naming the same session adds nothing, because a "
                  "field repeating the one beside it is noise rather than a "
                  "mapping",
                  "envSessionId" not in _sa3["actor"],
                  repr(sorted(_sa3["actor"])))
            check("sa4 junk in the environment is sanitised and bounded rather "
                  "than written into a committed row as it arrived - no path "
                  "separator and no traversal survives - and an empty one is "
                  "None rather than an empty string: %r"
                  % (with_env("../../etc/passwd", M.env_session_id),),
                  with_env("../../etc/passwd", M.env_session_id)
                  == "etc-passwd"
                  and with_env("x" * 200, lambda: len(M.env_session_id()))
                  == M.MAX_SESSION_ID_CHARS
                  and with_env("   ", M.env_session_id) is None
                  and with_env(None, M.env_session_id) is None)
            _sa_root = os.path.join(mtmp, "mapped")
            os.makedirs(_sa_root)
            with_env("env-id-bbbb", lambda: M.append(
                _sa_root, {"action": "manifest.edit", "target": "",
                           "summary": "mapped", "ts": "2026-05-07T00:00:00Z",
                           "actor": dict(_sa_actor)}, config=mcfg))
            _idx = with_env("env-id-bbbb",
                            lambda: M.session_index(_sa_root, mcfg))
            _ent = (_idx["files"] or [{}])[0]
            check("sa5 `session_index` reads the file's opaque name back to "
                  "both ids and marks it as this session's - which no reader "
                  "could do from the name alone: %r" % (_ent.get("file"),),
                  _ent.get("writer") == "payload-id-aaaa"
                  and _ent.get("sessionIds") == [("payload-id-aaaa", 1)]
                  and _ent.get("envSessionIds") == [("env-id-bbbb", 1)]
                  and _ent.get("mine") and _idx["mine"] == [_ent.get("file")]
                  and not _idx["unmapped"], repr(_ent))
            _idx2 = with_env("someone-else-entirely",
                             lambda: M.session_index(_sa_root, mcfg))
            check("sa6 SECOND DIRECTION: an environment naming a session that "
                  "wrote nothing here matches NO file, and the empty match is "
                  "reported as empty rather than as agreement",
                  not _idx2["mine"] and _idx2["env"] == "someone-else-entirely"
                  and (_idx2["files"] or [{}])[0].get("mine") is False,
                  repr(_idx2["mine"]))
            _idx3 = with_env(None, lambda: M.session_index(base, mcfg))
            check("sa7 a file whose rows carry no alias is listed under "
                  "`unmapped`, because absence means EITHER the ids agreed OR "
                  "the rows predate the field and nothing here can tell those "
                  "apart",
                  _idx3["unmapped"] == [os.path.basename(only(base))]
                  and _idx3["env"] is None, repr(_idx3["unmapped"]))
            check("sa8 the writer id comes off the NAME by partitioning once "
                  "from the left, so a session id carrying dots is not cut at "
                  "the first of them",
                  M.writer_of("2026-05.a.b.c.jsonl") == "a.b.c"
                  and M.writer_of("nonsense") == "",
                  repr(M.writer_of("2026-05.a.b.c.jsonl")))
        finally:
            shutil.rmtree(mtmp, ignore_errors=True)

    with_env(None, lambda: _merge_cases(check))
    _gone_cases(check)


def _gone_cases(check):
    """A file git TRACKS that the working tree does not have.

    THE CLASSIFICATION IS GRADED HERE AND THE REPOSITORY IS DRIVEN NEXT DOOR.
    `deleted_from_worktree` takes the NUL-split porcelain listing and a predicate
    saying what is on disk, so every status shape below - including the two that
    need a `git rm --cached` and a staged `git mv` to produce - is a fixture here
    rather than a repository nobody builds. `tools/check-git-pipeline.py` owns the
    end-to-end drive (g22), where a real commit is really deleted; what these
    cases hold is the grading it would take a dozen fixtures to reach, and the
    fail-open direction, which is the one that decides whether a machine with no
    git accuses its owner.

    Every listing is spelled the way `status --porcelain -z` hands one over: the
    entries are NUL-TERMINATED, not NUL-separated, so a real split leaves a
    trailing empty string. Building them any other way would test a parser the
    module never runs."""
    JD = "docs/audit/journal/"

    def listing(*entries):
        return list(entries) + [""]

    def disk(*present):
        held = set(present)
        return lambda p: p in held

    _gw1 = M.deleted_from_worktree(listing(" D " + JD + "2026-01.a.jsonl"),
                                   disk())
    check("gw1 a tracked file deleted from the working tree is named - the "
          "whole finding, and the thing the chain could not see because every "
          "pass walks the files that ARE on disk: %r" % (_gw1,),
          _gw1 == [JD + "2026-01.a.jsonl"])

    # MEASURED, NOT ASSUMED: `git rm --cached <f>` prints BOTH of these lines for
    # one file that is sitting right there. A check reading the `D` alone reports
    # a file its reader can open as gone, which is the accusation that gets a
    # guard switched off - so this is the allow case the deny side must not eat.
    _gw2 = M.deleted_from_worktree(
        listing("D  " + JD + "b.jsonl", "?? " + JD + "b.jsonl"),
        disk(JD + "b.jsonl"))
    check("gw2 ALLOW: a staged deletion of a file that is STILL ON DISK "
          "(`git rm --cached`, which porcelain prints as `D ` and `??` "
          "together) is not named - git tracking it and the worktree lacking it "
          "are two conditions and only the pair is the question: %r" % (_gw2,),
          _gw2 == [])

    _gw3 = M.deleted_from_worktree(
        listing("R  " + JD + "archive/c.jsonl", JD + "c.jsonl",
                " D " + JD + "d.jsonl"),
        disk(JD + "archive/c.jsonl"))
    check("gw3 ALLOW: a staged `git mv` into archive/ - what the `archive` "
          "subcommand does - leaves its ORIGIN absent from disk for a reason "
          "git itself supplies, so the origin is not named while a real "
          "deletion beside it still is: %r" % (_gw3,),
          _gw3 == [JD + "d.jsonl"])

    # What CONSUMING the origin token buys, made observable: a tracked path may
    # itself look like a status line, and a parser that read the origin as an
    # entry would grade it as one. The name is legal in a journal directory.
    _gw4 = M.deleted_from_worktree(
        listing("R  " + JD + "archive/e.jsonl", "xD gone.jsonl"),
        disk(JD + "archive/e.jsonl"))
    check("gw4 ...and the origin token is CONSUMED rather than skipped by luck: "
          "an origin path that would itself parse as a status line is not read "
          "as one: %r" % (_gw4,), _gw4 == [])

    _gw5 = M.deleted_from_worktree(
        listing("RD " + JD + "archive/f.jsonl", JD + "f.jsonl"), disk())
    check("gw5 ...while a rename whose DESTINATION was then deleted is named at "
          "its destination - the origin is still git's business and the file is "
          "still gone: %r" % (_gw5,), _gw5 == [JD + "archive/f.jsonl"])

    _gw6a = M.deleted_from_worktree(
        listing(" M " + JD + "g.jsonl", "?? " + JD + "h.jsonl",
                "UU " + JD + "i.jsonl"),
        disk(JD + "g.jsonl", JD + "h.jsonl", JD + "i.jsonl"))
    check("gw6 ALLOW: modified, untracked and conflicted files that are all on "
          "disk name nothing - only a status carrying a `D` is git saying the "
          "worktree lost the file: %r" % (_gw6a,), _gw6a == [])

    # THE SAME THREE, ABSENT, and this is the case that makes the status test
    # load-bearing rather than decoration. It is a RACE and not a hypothesis:
    # git scanned the directory, this stats it a moment later, and anything can
    # have happened in between - so an UNTRACKED file that vanished in that
    # window would be reported as a deleted trail by a rule that read the disk
    # alone, which is precisely the never-tracked-and-absent case that must stay
    # silent. The verdict is git's, taken at the moment git took it; a later stat
    # is not evidence to overrule it with, and the next `verify` sees the real
    # ` D` if there is one.
    _gw6b = M.deleted_from_worktree(
        listing(" M " + JD + "g.jsonl", "?? " + JD + "h.jsonl",
                "UU " + JD + "i.jsonl"), disk())
    check("gw6b ALLOW, AND THE HALF THE DISK CHECK CANNOT DO: the same three "
          "statuses with none of the files on disk STILL name nothing - a "
          "modified, untracked or conflicted path that disappeared between "
          "git's scan and this stat is not git saying it was deleted, and an "
          "untracked file is not tracked however absent it is: %r" % (_gw6b,),
          _gw6b == [])

    check("gw7 ALLOW: a directory with nothing to report is the empty list, "
          "which is what a fresh project and a fully committed one both look "
          "like",
          M.deleted_from_worktree(listing(), disk()) == []
          and M.deleted_from_worktree([""], disk()) == [])

    _gw8 = M.deleted_from_worktree(
        listing(" D " + JD + "archive/2025-12.a.jsonl",
                " D " + JD + "2026-01.a.jsonl"), disk())
    check("gw8 a journal directory removed WHOLE is the same deletion with more "
          "files in it, and every one is named, sorted so two runs report the "
          "same order: %r" % (_gw8,),
          _gw8 == [JD + "2026-01.a.jsonl", JD + "archive/2025-12.a.jsonl"])

    # `git -C <a path that is not there>` cannot be asked WHEREVER this suite
    # runs, which is what makes the sentinel deterministic - a directory that
    # merely has no `.git` of its own may still sit inside somebody's checkout.
    _tmp = tempfile.mkdtemp(prefix="journal-gone-")
    try:
        _nowhere = os.path.join(_tmp, "not-a-repository-at-all")
        _gw9 = M.tracked_but_gone(_nowhere, os.path.join(_nowhere, "journal"))
        check("gw9 ALLOW: git that cannot be asked answers None, the word this "
              "module already uses for an unasked question - NOT the empty list, "
              "because 'no git here' and 'nothing is missing' are two states and "
              "only one of them is reassuring: %r" % (_gw9,), _gw9 is None)
        check("gw10 ...and the finding builder turns that into no findings at "
              "all rather than raising or inventing one, which is what a "
              "project that has never been a git repository must see",
              M.gone_findings(_nowhere, os.path.join(_nowhere, "journal")) == [])
        _fresh = os.path.join(_tmp, "fresh-project")
        os.makedirs(os.path.join(_fresh, "docs", "audit", "journal"))
        _gw11 = M.verify(_fresh)
        check("gw11 ALLOW, AND THE ONE EVERY SURFACE PAYS: a project whose "
              "journal directory holds nothing git ever tracked verifies clean "
              "and silent - a never-tracked file that is absent is absence, not "
              "evidence: %r" % (_gw11["findings"],),
              _gw11["ok"] is True and _gw11["findings"] == [])
    finally:
        shutil.rmtree(_tmp, ignore_errors=True)

    _gw12 = M.gone_finding("docs/audit/journal/2026-01.a.jsonl")
    check("gw12 the finding NAMES the file and carries both commands that "
          "answer for it - the content git still holds, and the commit that "
          "removed it. A deletion says nothing about intent, so a sentence that "
          "only accused would leave its reader nowhere to go: %r" % (_gw12,),
          _gw12.count("docs/audit/journal/2026-01.a.jsonl") == 3
          and "git checkout -- docs/audit/journal/2026-01.a.jsonl" in _gw12
          and "git log --diff-filter=D -- docs/audit/journal/2026-01.a.jsonl"
          in _gw12)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__journal_io.py --selftest\n")
    raise SystemExit(2)
