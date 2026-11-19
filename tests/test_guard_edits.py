#!/usr/bin/env python3
"""
The cases for `hooks/guard-edits.py`, moved out of it - a hook, hyphenated.

The module comes through `_loader.load` by path out of `_harness.HOOKS_DIR`;
`_config` is imported directly, the way the hook imports it, because the fixtures
build their configs with `_config._deep_merge(_config.DEFAULTS, ...)`.

THE PATHS THE SELF-EDIT CASES BUILD COME OFF THE SUBJECT, NOT OFF THIS FILE. `s1`,
`s2` and `s3` need "a file inside the installed plugin" and "the repository that
contains the plugin", and the hook decides both against its OWN module-level
`_PLUGIN_ROOT` (derived from the hook's `__file__`). So they are spelled `M._HOOKS_DIR`
and `M._PLUGIN_ROOT` - the same objects `_self_edit_target` compares against - rather
than re-derived from this file's location, which is the fourth shape the guide forbids
carrying literally. `M._HOOKS_DIR == _harness.HOOKS_DIR` holds, and that is the point:
if it ever stopped holding, the subject's spelling would be the correct one.

`_HOOKS_DIR` and `_PLUGIN_ROOT` are the only location-dependent expressions in this
suite. The rest of the AST scan came back empty: no `globals()`, no `vars()`, no bare
`__file__`, no `split(a)[1].split(b)[0]`.

THE TWO DOMAIN WRAPPERS STAY HERE. `check(name, expected, tool, path, text)` and
`st_check(name, expected, tool, ti, cfg)` both ran `decide()` for the caller and printed
`(expected X, got Y)` on EVERY line, green ones included. They now hand that text to
the harness as a DETAIL, which is rendered only on failure - see `_harness`'s docstring
for that decision. The case labels are unchanged.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import collections
import itertools
import json
import os
import shutil
import sys
import time

import _harness                                   # sets sys.path for scripts/ + hooks/
from _output import safe_stdio, some_of            # noqa: E402
import _loader                                     # noqa: E402
import _config                                     # noqa: E402

M = _loader.load(os.path.join(_harness.HOOKS_DIR, "guard-edits.py"),
                 modname="guard_edits")


# --- cases --------------------------------------------------------------------
def _cases(check):
    tmp = _harness.fixture_root("guard-edits-selftest-")
    # token identifier assembled at runtime so this SOURCE file never contains a
    # literal logger-call-with-token (which the guard itself would flag).
    tok = "access" + "Token"
    cfg = _config._deep_merge(_config.DEFAULTS, {
        "guardEdits": {
            "tokenVars": ["accessToken", "refreshToken", "idToken"],
            "customRules": [
                {
                    "pathPrefix": "src/realtime/",
                    "bannedPattern": r"\.removeAllListeners\s*\(",
                    "message": "removeAllListeners() nukes sibling listeners — use a ref.",
                }
            ],
        }
    })

    def _expect(name, expected, tool, path, text, cwd=tmp, use_cfg=None):
        """One case: run `decide` on a synthesised payload, compare the verdict.

        Guarded through `_harness.attempt` rather than the hand-rolled
        `except Exception as exc: verdict = "EXC:%s"` the inline form carried."""
        ti = {"file_path": path, "content": text}
        if tool == "NotebookEdit":
            ti = {"notebook_path": path, "new_source": text}
        data = {"tool_name": tool, "tool_input": ti, "cwd": cwd}
        ok, got = _harness.attempt(M.decide, data,
                                   cfg=cfg if use_cfg is None else use_cfg)
        verdict = got[0] if ok else got
        check(name, verdict == expected,
              "expected %s, got %s" % (expected, verdict))

    # custom rule fires only under its pathPrefix
    _expect("c1 removeAllListeners under prefix blocked", "block", "Write",
            "src/realtime/useX.tsx", "qObject.removeAllListeners()")
    _expect("c2 removeAllListeners elsewhere allowed", "allow", "Write",
            "src/other/useX.tsx", "qObject.removeAllListeners()")
    # `pathPrefix` is matched as a SUBSTRING of the path the tool reported, which is
    # normally ABSOLUTE. Four documents said "starts with" instead; a rule written
    # to that description would have been believed to cover nothing (no real edit
    # path starts with "src/") while actually covering every occurrence anywhere in
    # the tree. These two pin the behaviour the docs now describe: an implementation
    # using str.startswith would fail c3, and one anchoring at the repo root would
    # fail c4.
    _expect("c3 the same rule fires from an ABSOLUTE path (a startswith match "
            "would not)", "block", "Write",
            "/Users/dev/checkout/src/realtime/useX.tsx", "q.removeAllListeners()")
    _expect("c4 and from a second root in a monorepo - the match is a substring, "
            "so one rule covers every place the concern lives", "block", "Write",
            "packages/web/src/realtime/useX.tsx", "q.removeAllListeners()")
    # token logging
    _expect("t1 logger with token value blocked", "block", "Write",
            "src/api.ts", "console.log('tok', %s)" % tok)
    _expect("t2 token prefix debug allowed", "allow", "Write",
            "src/api.ts", "console.log(%s.slice(0,6))" % tok)
    _expect("t3 innocent code allowed", "allow", "Write",
            "src/api.ts", "const x = 1 + 2;")
    _expect("t4 logger with token as SOLE arg blocked", "block", "Write",
            "src/api.ts", "console.log(%s)" % tok)
    _expect("t5 logger with token via property access blocked", "block", "Write",
            "src/api.ts", "console.log(this.%s)" % tok)
    _expect("t6 logger of a DIFFERENT identifier (token-prefix) allowed", "allow",
            "Write", "src/api.ts", "console.log(%sExpiry)" % tok)
    # NotebookEdit is covered too
    _expect("n1 notebook cell logging token blocked", "block", "NotebookEdit",
            "notebooks/train.ipynb", "console.log('t', %s)" % tok)
    _expect("n2 innocent notebook cell allowed", "allow", "NotebookEdit",
            "notebooks/train.ipynb", "print('hello')")

    # self-edit protection: plugin dir is OUTSIDE the tmp "project" → block,
    # even with empty content
    _expect("s1 editing an installed plugin file blocked", "block", "Write",
            os.path.join(M._HOOKS_DIR, "guard-edits.py"), "tampered")
    _expect("s2 empty-content write to plugin file blocked", "block", "Write",
            os.path.join(M._HOOKS_DIR, "hooks.json"), "")
    # dev mode: when cwd IS the repo containing the plugin → allow
    plugin_repo = os.path.dirname(os.path.dirname(M._PLUGIN_ROOT))
    _expect("s3 dev-mode edit of plugin file allowed", "allow", "Write",
            os.path.join(M._HOOKS_DIR, "guard-edits.py"), "dev change",
            cwd=plugin_repo)

    # bypass forgery
    _expect("f1 writing plan-bypass state blocked", "block", "Write",
            ".claude/state/plan-bypass-abc.json", "{}")
    _expect("f2 other state files allowed", "allow", "Write",
            ".claude/state/tdd-reminder-abc.json", "{}")

    # the append-only journal. Blocked with empty content too: the point is the
    # PATH, and a truncation to nothing is the most destructive edit of all.
    _expect("j1 editing a journal file blocked", "block", "Edit",
            "docs/audit/journal/2026-08.abc.jsonl", '{"v":1}')
    _expect("j2 truncating one is blocked as well", "block", "Write",
            "docs/audit/journal/2026-08.abc.jsonl", "")
    _expect("j3 a notebook path under the journal is no different", "block",
            "NotebookEdit", "docs/audit/journal/x.ipynb", "print(1)")
    # ...and the guard is about that directory alone. A neighbour whose name
    # merely starts the same way is ordinary work.
    _expect("j4 the manifest beside it is not the journal - and with "
            "journal.strictManifestState at its DEFAULT (off) a manifest write "
            "is allowed outright", "allow", "Write",
            "docs/audit/audit-plan.json", '{"meta":{"version":3}}')
    _expect("j5 a sibling directory with a similar name is not the journal",
            "allow", "Write", "docs/audit/journal-notes/why.md", "notes")
    _expect("j6 and a journal moved by config is protected where it actually is",
            "block", "Write", "trail/2026-08.abc.jsonl", "{}",
            use_cfg=_config._deep_merge(cfg, {"journal": {"dir": "trail"}}))
    _expect("j7 ...which means the default location is then no longer special",
            "allow", "Write", "docs/audit/journal/2026-08.abc.jsonl", "{}",
            use_cfg=_config._deep_merge(cfg, {"journal": {"dir": "trail"}}))

    # deny payload is canonical PreToolUse JSON
    # The hook's own name in front of the reason is pinned byte for byte by
    # test__config.py's shared-payload case; this one holds the shape.
    blob = json.loads(json.dumps(_config.deny_payload("why")))
    hso = blob.get("hookSpecificOutput") or {}
    check("d1 deny payload is canonical PreToolUse JSON",
          hso.get("hookEventName") == "PreToolUse"
          and hso.get("permissionDecision") == "deny"
          and hso.get("permissionDecisionReason") == "why")

    # --- st: opt-in strict manifest state (journal.strictManifestState) -------
    # "ask", never deny: the orchestrator completes tasks through these SAME
    # tools, and a deny here would deny the pipeline its own bookkeeping. Off by
    # default; detection (the journal + doctor) stays the default defence.
    _prev_pd = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = tmp
    try:
        strict_cfg = _config._deep_merge(
            cfg, {"journal": {"strictManifestState": "ask"}})
        man = "docs/audit/audit-plan.json"

        def st_decide(tool, ti, use_cfg):
            data = {"tool_name": tool, "tool_input": ti, "cwd": tmp}
            ok, got = _harness.attempt(M.decide, data, cfg=use_cfg)
            return (got if ok else (got, ""))

        def st_check(name, expected, tool, ti, use_cfg):
            v, _m = st_decide(tool, ti, use_cfg)
            check(name, v == expected, "expected %s, got %s" % (expected, v))

        st_check("st1 strict asks on a status flip via Edit", "ask", "Edit",
                 {"file_path": man,
                  "old_string": '"status": "in_progress"',
                  "new_string": '"status": "done"'}, strict_cfg)
        st_check("st2 an ordinary manifest edit stays allowed in strict",
                 "allow", "Edit",
                 {"file_path": man,
                  "old_string": '"title": "Old title"',
                  "new_string": '"title": "New title"'}, strict_cfg)
        st_check("st3 the DEFAULT is off: the same state flip passes untouched",
                 "allow", "Edit",
                 {"file_path": man,
                  "old_string": '"status": "in_progress"',
                  "new_string": '"status": "done"'}, cfg)
        # A Write is compared against the on-disk file, not sniffed for key
        # names -- every whole-manifest Write contains the word "status".
        os.makedirs(os.path.join(tmp, "docs", "audit"), exist_ok=True)
        _st_doc = {"meta": {"version": 2}, "phases": [
            {"id": "P1", "title": "p", "status": "in_progress", "tasks": [
                {"id": "P1.1", "title": "t", "status": "in_progress",
                 "commit": None, "attempts": 1}]}]}
        with open(os.path.join(tmp, "docs", "audit", "audit-plan.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(_st_doc, fh)
        import copy as _copy
        _st_done = _copy.deepcopy(_st_doc)
        _st_done["phases"][0]["tasks"][0]["status"] = "done"
        st_check("st4 strict asks on a Write whose STATE differs from disk",
                 "ask", "Write",
                 {"file_path": man, "content": json.dumps(_st_done)},
                 strict_cfg)
        _st_titled = _copy.deepcopy(_st_doc)
        _st_titled["phases"][0]["tasks"][0]["title"] = "renamed"
        st_check("st4b a Write changing only content fields is allowed in "
                 "strict, though it contains the word status", "allow",
                 "Write",
                 {"file_path": man, "content": json.dumps(_st_titled)},
                 strict_cfg)
        st_check("st5 a phase shard is governed too", "ask", "Edit",
                 {"file_path": "docs/audit/phases/P1.json",
                  "old_string": '"completedAt": null',
                  "new_string": '"completedAt": "2026-08-11T00:00:00Z"'},
                 strict_cfg)
        st_check("st6 an ordinary source file is never strict's business",
                 "allow", "Edit",
                 {"file_path": "src/app.py",
                  "old_string": '"status": "a"',
                  "new_string": '"status": "b"'}, strict_cfg)
        _v, _m = st_decide("Edit", {"file_path": man,
                                    "old_string": '"attempts": 1',
                                    "new_string": '"attempts": 0'}, strict_cfg)
        check("st7 strict NEVER denies - the verdict is ask, and the "
              "orchestrator keeps its own bookkeeping (got %s)" % (_v,),
              _v == "ask")
        blob = json.loads(json.dumps(_config.ask_payload("why")))
        hso = blob.get("hookSpecificOutput") or {}
        check("st8 the ask payload is canonical PreToolUse JSON",
              hso.get("hookEventName") == "PreToolUse"
              and hso.get("permissionDecision") == "ask"
              and hso.get("permissionDecisionReason") == "why")
    finally:
        if _prev_pd is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = _prev_pd

    # --- mc: an MCP server's write tool ---------------------------------------
    # It reaches no edit-tool matcher, so before `_decide_mcp` it was outside
    # every rule this file holds. The cases below pin WHICH rules it reaches and
    # which it does not, because "widened" with no line between the two is the
    # shape that lets a gap be read as coverage.
    #
    # THE SERVER SEGMENT IS DELIBERATELY DIFFERENT IN EVERY CASE. `mcp__fs__`,
    # `mcp__filesystem__` and `mcp__github__` are one server under three
    # operator spellings, and a verdict that moved with the spelling would go red
    # here rather than in somebody's repository.
    def _mcp(name, expected, tool, ti, cwd=tmp, use_cfg=None):
        data = {"tool_name": tool, "tool_input": ti, "cwd": cwd}
        ok, got = _harness.attempt(M.decide, data,
                                   cfg=cfg if use_cfg is None else use_cfg)
        verdict = got[0] if ok else got
        check(name, verdict == expected,
              "expected %s, got %s" % (expected, verdict))

    _plugin_file = os.path.join(M._HOOKS_DIR, "guard-edits.py")
    _mcp("mc1 an MCP write into the installed plugin is refused, as the Edit "
         "of the same path is", "block", "mcp__fs__write_file",
         {"path": _plugin_file, "content": "tampered\n"})
    # The TARGET alone, whatever the operation - the one rule here that does not
    # wait for a write basis, and the sentence in the module docstring says why.
    # A read payload: one short single-line scalar, nothing a write test can see.
    _mcp("mc2 ...and so is a READ of it, because a PreToolUse payload cannot "
         "tell the two apart and nothing ordinary reads that directory",
         "block", "mcp__filesystem__read_text_file", {"path": _plugin_file})
    _mcp("mc3 dev mode still exempts the plugin's own checkout on this lane too",
         "allow", "mcp__fs__write_file",
         {"path": _plugin_file, "content": "dev change\n"},
         cwd=os.path.dirname(os.path.dirname(M._PLUGIN_ROOT)))

    _mcp("mc4 an MCP write of the bypass state is forgery here as well", "block",
         "mcp__fs__write_file",
         {"path": ".claude/state/plan-bypass-abc.json", "content": "{}\n"})
    _mcp("mc5 an MCP write into the journal is refused - the trail is "
         "append-only whatever wrote it", "block", "mcp__github__push_files",
         {"files": [{"path": "docs/audit/journal/2026-08.abc.jsonl",
                     "content": "{}"}]})
    # THE ALLOW CASE FOR THE INSIDE-THE-REPO HALF, and the reason those two rules
    # wait for a write basis while self-edit does not: the journal is committed
    # and meant to be read, so a guard that refused this would be friction on
    # honest work and would be routed around within a day.
    _mcp("mc6 a READ of a journal file is not refused - no write basis in the "
         "payload, and the trail is committed to be read", "allow",
         "mcp__filesystem__read_text_file",
         {"path": "docs/audit/journal/2026-08.abc.jsonl"})
    _mcp("mc7 ...nor is a rename of one, which is the UNDER-coverage the write "
         "test is chosen to have: short single-line scalars carry no basis",
         "allow", "mcp__fs__move_file",
         {"source": "docs/audit/journal/2026-08.abc.jsonl",
          "destination": "docs/audit/journal/2026-09.abc.jsonl"})
    _mcp("mc8 an ordinary MCP write elsewhere in the repo is this guard's "
         "business in no rule at all", "allow", "mcp__fs__write_file",
         {"path": "src/api.ts", "content": "const x = 1;\n"})
    # THE RULE THAT IS NOT REACHED, pinned as a rule and not as an accident. The
    # module docstring says the token-logging ban stays on the edit tools because
    # only their schema can name the text that will become file bytes; if somebody
    # later runs the regex over every string in an MCP payload, this goes red and
    # they have to come and read that paragraph.
    _mcp("mc9 the token-logging ban is NOT reached through an MCP payload - "
         "stated in the docstring, pinned here, and the cost of the other "
         "choice is refusing a commit message that quotes the pattern",
         "allow", "mcp__fs__write_file",
         {"path": "src/api.ts", "content": "console.log(%s)\n" % tok})

    # (tf) A LINKED WORKTREE'S JOURNAL IS A JOURNAL. The trail and the bypass
    # state were located under CLAUDE_PROJECT_DIR only, so from a session
    # started in the main checkout, an edit into a phase worktree's journal was
    # nobody's business - the one file the plugin promises is append-only,
    # rewritable by hand one tree over.
    _tf_ok, _tf = _harness.attempt(_harness.worktree_pair, "guard-edits-wt-")
    if not _tf_ok:
        check("tf0 the worktree fixture builds (%s)" % (_tf,), False)
    else:
        _prev_tf = os.environ.get("CLAUDE_PROJECT_DIR")
        os.environ["CLAUDE_PROJECT_DIR"] = _tf["main"]
        try:
            _tf_j = os.path.join(_tf["wt"], "docs", "audit", "journal",
                                 "2026-09.abc.jsonl")
            _expect("tf1 an Edit into a linked worktree's journal is refused as "
                    "the append-only trail it is", "block", "Edit", _tf_j,
                    '{"v":1}', cwd=_tf["main"])
            _expect("tf2 ...and a plan-first bypass forged into the worktree's "
                    "state directory is refused as forgery", "block", "Write",
                    os.path.join(_tf["wt"], ".claude", "state",
                                 "plan-bypass-x.json"), "{}", cwd=_tf["main"])
            _mcp("tf3 ...and an MCP write into it is refused on the same "
                 "evidence, not skipped as a path outside the project",
                 "block", "mcp__fs__write_file",
                 {"path": _tf_j, "content": '{"v": 1, "hash": "x"}\n' * 3})
            _expect("tf4 ...while an ordinary source file in the worktree is "
                    "nothing these rules hold - the re-root found the journal, "
                    "it did not widen the journal to the worktree", "allow",
                    "Write", os.path.join(_tf["wt"], "src", "app.ts"), "x",
                    cwd=_tf["main"])
        finally:
            if _prev_tf is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = _prev_tf

    _config_cases(check, cfg, tmp, _tf if _tf_ok else None)
    _volume_pair_cases(check, cfg)
    _link_cases(check)
    _generated_cases(check)
    _process_count_cases(check)
    _registration_cases(check)
    _member_cases(check)
    _relative_registration_cases(check)
    _topology_cases(check)


# --- cf: the audit config is the owner's, not an agent's ------------------------
# The plan gate exempts `.claude/**`, so before this rule an agent could switch the
# capability policy, the plan gate or the journal off with one Edit, and only a
# journal row recorded it. A subagent is refused; the orchestrator is ASKED,
# because the owner legitimately has the main session change config.
#
# EVERY REFUSING CASE HAS A TWIN THAT IS QUIET, so an implementation that fires
# on every `.claude/` path, on the basename, on a path SUFFIX, on any tool, or
# on the subagent bit alone goes red here rather than in somebody's session.
_CF_ROUTES = ("/audit:panel", "by hand")
_CF_BODY = '{"policy": {"enabled": false}}\n'
# The name the launcher marks the sessions it starts with, written out here and
# not read from the hook or the launcher: the hook reads it, the launcher sets it,
# and `tests/test_run_agent_session.py` spells it out too, so a rename on either
# side turns a case red instead of passing a name compared with itself.
_DRIVE_MARK = "AUDIT_DRIVE_SESSION"


def _cf_decide(cfg, tool, ti, cwd, agent, mark=None):
    """The verdict with the launcher's mark set to `mark`, or absent for None.

    Every case pins the mark, set or absent, rather than inheriting the caller's:
    a suite run from inside a session the drive started would otherwise read every
    main-session ask below as a refusal."""
    data = {"tool_name": tool, "tool_input": ti, "cwd": cwd}
    if agent:
        data["agent_id"] = agent
    prev = os.environ.pop(_DRIVE_MARK, None)
    if mark is not None:
        os.environ[_DRIVE_MARK] = mark
    try:
        ok, got = _harness.attempt(M.decide, data, cfg=cfg)
    finally:
        os.environ.pop(_DRIVE_MARK, None)
        if prev is not None:
            os.environ[_DRIVE_MARK] = prev
    return (got[0], got[1] or "") if ok else (got, "")


def _config_cases(check, cfg, tmp, tf):
    def _cf(name, expected, tool, ti, agent="agent-cf", cwd=tmp, words=(),
            mark=None):
        verdict, reason = _cf_decide(cfg, tool, ti, cwd, agent, mark=mark)
        missing = [w for w in words if w not in reason]
        check(name, verdict == expected and not missing,
              "expected %s, got %s; reason lacks %s: %r"
              % (expected, verdict, missing, reason[:300]))

    def _w(path):
        return {"file_path": path, "content": _CF_BODY}

    prev = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = tmp
    conf = os.path.join(tmp, *_config.CONFIG_REL.split("/"))
    try:
        # The file under test is the one the hooks read their config from, shown
        # by having `_config.load` read a marker out of it, not by a spelling.
        os.makedirs(os.path.dirname(conf), exist_ok=True)
        with open(conf, "w", encoding="utf-8") as fh:
            json.dump({"cfProbe": 7}, fh)
        check("cf0 the fixture's config path is the file _config.load reads",
              _config.load(tmp).get("cfProbe") == 7, _config.load(tmp))
        os.remove(conf)

        # acceptance 1 and 2: deny to a subagent, ask of the main session
        _cf("cf1 a subagent's Write to the project's audit config is refused, "
            "naming the owner's routes", "block", "Write", _w(conf),
            words=_CF_ROUTES)
        _cf("cf2 the same Write from the main session is asked, not refused",
            "ask", "Write", _w(conf), agent=None, words=("audit config",))
        _cf("cf2b an EMPTY Write is held too - the path decides, and truncating "
            "the config to nothing switches every setting back to its default",
            "block", "Write", {"file_path": conf, "content": ""})
        if os.name != "nt":
            # The decision reads the resolved file, not the spelling.
            os.makedirs(os.path.dirname(conf), exist_ok=True)
            os.symlink(os.path.dirname(conf), os.path.join(tmp, "cf-link"))
            _cf("cf2c a subagent's Write through a symlink to .claude/ is the "
                "same file and is refused", "block", "Write",
                _w(os.path.join(tmp, "cf-link", os.path.basename(conf))))
        _cf("cf3 a subagent's Edit spelled relative to the session's directory "
            "is the same file", "block", "Edit",
            {"file_path": _config.CONFIG_REL, "old_string": "true",
             "new_string": "false"})
        _cf("cf4 ...and a MultiEdit of it", "block", "MultiEdit",
            {"file_path": conf, "edits": [{"old_string": '"observe"',
                                           "new_string": '"deny"'}]})
        _cf("cf5 ...and a NotebookEdit naming it", "block", "NotebookEdit",
            {"notebook_path": conf, "new_source": _CF_BODY})
        _cf("cf6 a subagent's MCP write of it is refused as the Edit is",
            "block", "mcp__fs__write_file", {"path": conf, "content": _CF_BODY})
        _cf("cf7 the main session's MCP write of it is asked", "ask",
            "mcp__filesystem__write_file", {"path": conf, "content": _CF_BODY},
            agent=None)

        # A session the drive started is a top-level session: its tool calls carry
        # no agent id, and nobody sits at its prompt. The launcher's mark is what
        # tells it apart from the owner's own session. Each refusal has its twin:
        # the same payload unmarked, and the mark set to nothing, are asked; a Read
        # under the mark is not held; and the mark changes no other verdict.
        _cf("cf20 a session the drive started (the launcher's mark, no agent id) "
            "is refused the config write, in words naming the drive", "block",
            "Write", _w(conf), agent=None, mark="1", words=("drive",))
        _cf("cf20b ...and its MCP write of it, as a subagent's is", "block",
            "mcp__fs__write_file", {"path": conf, "content": _CF_BODY},
            agent=None, mark="1")
        _cf("cf21 the same Write with no mark is the owner's session and is "
            "asked, not refused", "ask", "Write", _w(conf), agent=None,
            mark=None)
        _cf("cf21b the mark set to an empty value marks nothing - asked",
            "ask", "Write", _w(conf), agent=None, mark="")
        _cf("cf21c a marked session's Read of the config is never held",
            "allow", "Read", {"file_path": conf}, agent=None, mark="1")
        _src = {"file_path": os.path.join(tmp, "src", "cf-app.ts"),
                "content": "export const a = 1;\n"}
        _plain = _cf_decide(cfg, "Write", _src, tmp, None, mark=None)[0]
        _marked = _cf_decide(cfg, "Write", _src, tmp, None, mark="1")[0]
        check("cf21d the mark changes no verdict but the config's: a marked "
              "session's write of an ordinary source file answers what an "
              "unmarked one does (%s vs %s)" % (_marked, _plain),
              _plain == "allow" and _marked == _plain)

        # The config spelled in other letter cases. Whether that is the same file
        # is the filesystem's answer, so it is read off the scratch directory the
        # config sits in - a probe file and its upper-cased name - never off the
        # platform's name. Where case folds, the variant IS the config and is held
        # as the config is; where it does not, the variant names another file
        # (absent here) and the rule does not fire. The config exists for the
        # case, since a variant spelling is matched to it by `samefile`.
        cdir = os.path.dirname(conf)
        os.makedirs(cdir, exist_ok=True)
        with open(conf, "w", encoding="utf-8") as fh:
            fh.write(_CF_BODY)
        probe = os.path.join(cdir, "cf-fold-probe")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("\n")
        folds = os.path.exists(os.path.join(cdir, "CF-FOLD-PROBE"))
        os.remove(probe)
        name = os.path.basename(conf)
        variants = (os.path.join(cdir, name.upper()),
                    os.path.join(cdir, "Audit.Config.Json"),
                    os.path.join(os.path.dirname(cdir),
                                 os.path.basename(cdir).upper(), name))
        seen = [(v, agent is None, _cf_decide(cfg, "Write", _w(v), tmp, agent)[0])
                for v in variants for agent in ("agent-cf", None)]
        want = [(v, main, ("ask" if main else "block") if folds else "allow")
                for v, main, _got in seen]
        os.remove(conf)
        check("cf19 the config's path in another letter case - file name upper, "
              "mixed, directory upper - is held as the config where the scratch "
              "filesystem folds case (folds=%s): a subagent refused, the main "
              "session asked; where it does not fold, it is another file and "
              "allowed" % (folds,),
              seen == want and len(seen) == 6,
              "got %r" % ([(os.path.relpath(v, tmp), m, g) for v, m, g in seen],))

        # the allow twins: the rule is one file, a write, of THIS project
        for agent, who, k in (("agent-cf", "subagent", "s"),
                              (None, "main session", "m")):
            _cf("cf8%s a %s's write to .claude/settings.json is not this rule's"
                % (k, who), "allow", "Write",
                _w(os.path.join(tmp, ".claude", "settings.json")), agent=agent)
            _cf("cf9%s a %s's write to a skill under .claude/ is not this rule's"
                % (k, who), "allow", "Write",
                _w(os.path.join(tmp, ".claude", "skills", "x", "SKILL.md")),
                agent=agent)
            _cf("cf10%s a %s's write to a file merely named audit.config.json "
                "elsewhere in the tree is untouched" % (k, who), "allow",
                "Write", _w(os.path.join(tmp, "docs", "audit.config.json")),
                agent=agent)
            _cf("cf11%s a %s's write to a nested .claude/audit.config.json (a "
                "path-suffix match would refuse it) is untouched" % (k, who),
                "allow", "Write",
                _w(os.path.join(tmp, "sub", *_config.CONFIG_REL.split("/"))),
                agent=agent)
            _cf("cf12%s a %s's Read of the config is never asked" % (k, who),
                "allow", "Read", {"file_path": conf}, agent=agent)
            _cf("cf13%s a %s's MCP read of the config is never asked - no write "
                "basis in the payload" % (k, who), "allow",
                "mcp__filesystem__read_text_file", {"path": conf}, agent=agent)

        # Dev mode: rule 3 exempts the plugin's own checkout from the
        # installed-plugin rule, because editing plugin source is the work there.
        # The config is not plugin source - it governs that checkout's own agents
        # as it governs any project's - so this rule applies there unchanged.
        repo = os.path.dirname(os.path.dirname(M._PLUGIN_ROOT))
        os.environ["CLAUDE_PROJECT_DIR"] = repo
        rconf = os.path.join(repo, *_config.CONFIG_REL.split("/"))
        _cf("cf14 in the plugin's own checkout a subagent's write to its audit "
            "config is still refused", "block", "Write", _w(rconf), cwd=repo)
        _cf("cf15 ...and the main session's is still asked", "ask", "Write",
            _w(rconf), cwd=repo, agent=None)
        _cf("cf16 ...while the dev-mode exception for plugin source still holds "
            "for the same subagent", "allow", "Write",
            _w(os.path.join(M._HOOKS_DIR, "guard-edits.py")), cwd=repo)
    finally:
        if os.path.exists(conf):
            os.remove(conf)
        if prev is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = prev
    if tf is None:
        return
    # A linked worktree's config is the config that tree's hooks read when a
    # session runs there, and the one a merge carries back: the same rule.
    prev = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = tf["main"]
    try:
        wconf = os.path.join(tf["wt"], *_config.CONFIG_REL.split("/"))
        _cf("cf17 a subagent's write to a linked worktree's audit config is "
            "refused from a session in the main checkout", "block", "Write",
            _w(wconf), cwd=tf["main"])
        _cf("cf18 ...while a write to a file beside it in that worktree's "
            ".claude/ is not", "allow", "Write",
            _w(os.path.join(tf["wt"], ".claude", "settings.json")),
            cwd=tf["main"])

        # A linked worktree placed UNDER the project - where the harness puts an
        # isolated subagent's tree, and where a worktree root inside the project
        # puts the drive's - is a working tree of the repository all the same. A
        # containment test calls it the project, and its config then reads as a
        # nested file the rule does not hold; so it is a REAL `git worktree add`
        # here, beside a plain folder of the same shape that is no tree (cf11's
        # twin at this depth) and must stay allowed.
        nested = os.path.join(tf["main"], ".claude", "worktrees", "agent-cf")
        plain = os.path.join(tf["main"], ".claude", "worktrees", "plain-cf")
        built, why = _harness.attempt(
            _harness.git, tf["main"], "worktree", "add", "-q", nested, "-b",
            "nested/agent-cf", prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
        check("cf22 the nested worktree fixture builds and is a linked tree "
              "(%s)" % (why if not built else "built",),
              built and os.path.isfile(os.path.join(nested, ".git")))
        _config.forget_git_standing()
        nconf = os.path.join(nested, *_config.CONFIG_REL.split("/"))
        _cf("cf22b a subagent's write to the config of a linked worktree nested "
            "under the project is refused, from a session in the project",
            "block", "Write", _w(nconf), cwd=tf["main"], words=_CF_ROUTES)
        _cf("cf22c ...and from a session whose directory is that worktree",
            "block", "Write", _w(nconf), cwd=nested)
        _cf("cf22d ...while the main session's write of it is asked", "ask",
            "Write", _w(nconf), cwd=tf["main"], agent=None)
        os.makedirs(plain)
        _cf("cf22e a plain folder of the same shape, which holds no repository, "
            "keeps its answer: its .claude/audit.config.json is untouched",
            "allow", "Write",
            _w(os.path.join(plain, *_config.CONFIG_REL.split("/"))),
            cwd=tf["main"])
        _cf("cf22f ...and a file beside the nested worktree's config is not "
            "this rule's", "allow", "Write",
            _w(os.path.join(nested, ".claude", "settings.json")),
            cwd=tf["main"])
        _spelling_cases(check, cfg, tf, nested, _cf, _w)
    finally:
        if prev is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = prev


# --- cf: which file a path names, asked of the disk, not of the spelling ----------
# The config of a tree nested under the project, written through a spelling that
# differs from the plugin's in letter case. Whether that spelling names the config
# is the volume's answer, so the cases that depend on it ask the volume they run
# on - an existing directory reached under its case-swapped name, asked here
# apart from the hook - and assert what that volume owes: held where names fold,
# allowed where they do not. Each such label prints which volume it ran on, so a
# run on one kind is never read as having held the other. The other kind is
# driven through a stubbed answer as well, and those labels say STUBBED.
def _swapped_exists(path):
    """True when `path`'s last component, case-swapped, names the same entry -
    the volume folds names there. Asked of the disk, independently of the hook."""
    head, name = os.path.split(path)
    other = os.path.join(head, name.swapcase())
    return (other != path and os.path.exists(other)
            and os.path.samefile(other, path))


def _cap(name):
    """`name` with its first letter upper-cased: `.Claude` for `.claude`."""
    for i, ch in enumerate(name):
        if ch.isalpha():
            return name[:i] + ch.upper() + name[i + 1:]
    return name


def _with_attr(name, value, fn, on=None):
    """`fn()` with `<module>.<name>` replaced by `value`, restored whatever
    happens - the module `on`, or the hook when None. Which file a path names is
    `_config`'s question, so its parts are stubbed there (`on=_config`). A name
    the module does not define is set and then removed again, so a case run
    against a build without it fails on its assertion, not on a lookup."""
    mod = M if on is None else on
    prev = getattr(mod, name, _with_attr)
    setattr(mod, name, value)
    try:
        return fn()
    finally:
        if prev is _with_attr:
            delattr(mod, name)
        else:
            setattr(mod, name, prev)


def _config_way(tree):
    """`_config.audit_config_way(tree)`, or a word saying the build has none -
    so a case run against such a build fails on its assertion."""
    fn = getattr(_config, "audit_config_way", None)
    if fn is None:
        return "NO _config.audit_config_way"
    return fn(tree)


# --- cf: what the config question asks of the disk ---------------------------------
# ONE TABLE: every function of `os` and `os.path` that asks the disk and that the
# guard, or the config question it calls in `_config`, can reach - each wrapped by
# the counter. A listing is here in both of its forms; `os.walk` is built on
# `scandir` and is counted through it. `_NOT_DISK` is the short list of calls that
# are string work or read the process's own directory. `cf30` reads both sources
# and names any `os.` or `os.path.` call that is in neither list, so a call added
# to the hook is counted or argued, never silently missed.
_DISK_CALLS = (
    ("os", "stat"), ("os", "lstat"), ("os", "readlink"), ("os", "listdir"),
    ("os", "scandir"), ("os", "access"),
    ("os.path", "exists"), ("os.path", "lexists"), ("os.path", "isdir"),
    ("os.path", "isfile"), ("os.path", "islink"), ("os.path", "ismount"),
    ("os.path", "realpath"), ("os.path", "samefile"), ("os.path", "getsize"),
    ("os.path", "getmtime"),
)
_LISTINGS = ("os.listdir", "os.scandir")
_NOT_DISK = ("os.path.join", "os.path.split", "os.path.dirname",
             "os.path.basename", "os.path.normcase", "os.path.normpath",
             "os.path.samestat", "os.path.isabs", "os.path.abspath",
             "os.fspath")


def _owner(name):
    return os.path if name == "os.path" else os


def _disk_record(fn, outer=False):
    """(result of fn(), [(call, first argument)]) over `_DISK_CALLS`, in the
    order the calls ended.

    By default a call is recorded when no other counted call happened inside it
    - the leaf - so `realpath` records as the `lstat` and `readlink` calls it
    makes, and an `isdir` that asks the disk itself, as it does on some
    platforms, records once as `os.path.isdir`. That measure is the host's: a
    posix `realpath` is built from counted calls and a windows one is not, so
    two leaf counts compare equal only where both sides make the same library
    calls. With `outer`, a call is recorded only when no counted call is in
    progress - the call the code under test makes itself, once, whatever the
    library builds it from - which is the same measure on every host."""
    seen, depth = [], [0]
    saved = [(owner, name, getattr(_owner(owner), name))
             for owner, name in _DISK_CALLS if hasattr(_owner(owner), name)]

    def counting(label, real):
        def call(*a, **k):
            mark, top = len(seen), depth[0] == 0
            depth[0] += 1
            try:
                return real(*a, **k)
            finally:
                depth[0] -= 1
                if (top if outer else len(seen) == mark):
                    seen.append((label, a[0] if a else None))
        return call
    for owner, name, real in saved:
        setattr(_owner(owner), name, counting("%s.%s" % (owner, name), real))
    try:
        out = fn()
    finally:
        for owner, name, real in saved:
            setattr(_owner(owner), name, real)
    return out, seen


def _disk_calls(fn, outer=False):
    """(result of fn(), {call: count}) over `_DISK_CALLS`, counted as
    `_disk_record` records them."""
    out, seen = _disk_record(fn, outer)
    by = {}
    for label, _arg in seen:
        by[label] = by.get(label, 0) + 1
    return out, by


def _os_calls_in(tree_node):
    """Every `os.<name>(...)` and `os.path.<name>(...)` call under the AST node,
    spelled `os.<name>` / `os.path.<name>`."""
    import ast
    out = []
    for node in ast.walk(tree_node):
        if not isinstance(node, ast.Call) or not isinstance(node.func,
                                                             ast.Attribute):
            continue
        val = node.func.value
        if isinstance(val, ast.Name) and val.id == "os":
            out.append("os." + node.func.attr)
        elif (isinstance(val, ast.Attribute) and val.attr == "path"
              and isinstance(val.value, ast.Name) and val.value.id == "os"):
            out.append("os.path." + node.func.attr)
    return out


def _question_reach(src, entry):
    """The module-level functions of the source `src` that `entry` reaches by
    bare-name calls, `entry` included - the part of `_config` the config
    question runs. {} when `src` defines no `entry`."""
    import ast
    defs = dict((n.name, n) for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef))
    if entry not in defs:
        return {}
    reach, todo = {}, [entry]
    while todo:
        name = todo.pop()
        if name in reach or name not in defs:
            continue
        reach[name] = defs[name]
        todo.extend(n.func.id for n in ast.walk(defs[name])
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name))
    return reach


def _spelling_cases(check, cfg, tf, nested, _cf, _w):
    main = tf["main"]
    rel = _config.CONFIG_REL.split("/")
    folds = _swapped_exists(nested)
    vol = "volume folds case: %s" % (folds,)
    held, asked = ("block", "ask") if folds else ("allow", "allow")
    nconf = os.path.join(nested, *rel)
    os.makedirs(os.path.dirname(nconf), exist_ok=True)
    with open(nconf, "w", encoding="utf-8") as fh:
        fh.write(_CF_BODY)
    variants = (os.path.join(nested, _cap(rel[0]), rel[1]),
                os.path.join(nested, rel[0], "Audit.Config.json"),
                os.path.join(nested, rel[0].upper(), rel[1].upper()))
    seen = [(v, agent is None,
             _cf_decide(cfg, "Write", _w(v), main, agent)[0])
            for v in variants for agent in ("agent-cf", None)]
    want = [(v, m, asked if m else held) for v, m, _g in seen]
    check("cf23 the EXISTING config of a nested worktree through a spelling in "
          "another letter case - directory, file name, both - is refused to a "
          "subagent and asked of the main session where names fold, and is "
          "another file, allowed, where they do not (%s)" % (vol,),
          seen == want and len(seen) == 6,
          "got %r" % ([(os.path.relpath(v, main), m, g) for v, m, g in seen],))

    # The creating write: a nested worktree whose config does not exist yet,
    # first with no `.claude` directory at all, then with an empty one.
    fresh = os.path.join(main, ".claude", "worktrees", "agent-cf2")
    built, why = _harness.attempt(
        _harness.git, main, "worktree", "add", "-q", fresh, "-b",
        "nested/agent-cf2", prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
    check("cf24 the second nested worktree fixture builds, with no config and "
          "no .claude directory (%s)" % (why if not built else "built",),
          built and not os.path.exists(os.path.join(fresh, rel[0])))
    if not built:
        return
    _config.forget_git_standing()
    exact = os.path.join(fresh, *rel)
    dir_case = os.path.join(fresh, _cap(rel[0]), rel[1])
    _cf("cf24b a creating write of a nested worktree's config, spelled as the "
        "plugin spells it, is refused - the twin every volume owes", "block",
        "Write", _w(exact), cwd=main, words=_CF_ROUTES)
    _cf("cf24c a creating write through a directory spelled in another case, "
        "no .claude existing yet, is held as the config where names fold and "
        "allowed where they do not (%s)" % (vol,), held, "Write", _w(dir_case),
        cwd=main)
    _cf("cf24d ...and the main session's is asked where names fold (%s)"
        % (vol,), asked, "Write", _w(dir_case), cwd=main, agent=None)
    os.makedirs(os.path.join(fresh, rel[0]))
    _cf("cf24e a creating write of the file name in another case, its "
        ".claude existing and empty, is held where names fold and allowed "
        "where they do not (%s)" % (vol,), held, "Write",
        _w(os.path.join(fresh, rel[0], "Audit.Config.JSON")), cwd=main)
    os.rmdir(os.path.join(fresh, rel[0]))

    # The volume's answer substituted: the half this volume cannot show.
    v_no = _with_attr("_volume_folds", lambda d: False, lambda: _cf_decide(
        cfg, "Write", _w(dir_case), main, "agent-cf")[0], on=_config)
    v_no_exact = _with_attr("_volume_folds", lambda d: False, lambda: _cf_decide(
        cfg, "Write", _w(exact), main, "agent-cf")[0], on=_config)
    check("cf25 STUBBED - the volume's answer substituted, not asked: "
          "told names do not fold, a creating write through a directory in "
          "another case is another file and allowed (%s), while the exact "
          "spelling is still refused (%s)" % (v_no, v_no_exact),
          v_no == "allow" and v_no_exact == "block")
    v_yes = _with_attr("_volume_folds", lambda d: True, lambda: _cf_decide(
        cfg, "Write", _w(dir_case), main, "agent-cf")[0], on=_config)
    check("cf25b STUBBED: told names fold, the same creating write is refused "
          "(%s)" % (v_yes,), v_yes == "block")
    v_none = _with_attr("_volume_folds", lambda d: None, lambda: _cf_decide(
        cfg, "Write", _w(dir_case), main, "agent-cf"), on=_config)
    v_none_exact = _with_attr("_volume_folds", lambda d: None,
                              lambda: _cf_decide(cfg, "Write", _w(exact), main,
                                                 "agent-cf"), on=_config)
    blind = "without regard to case"
    check("cf25c STUBBED: where the volume cannot be asked, a creating write "
          "in another case is refused and the refusal says the spelling was "
          "matched without regard to case; the exact spelling's refusal does "
          "not say it",
          v_none[0] == "block" and blind in v_none[1]
          and v_none_exact[0] == "block" and blind not in v_none_exact[1],
          "got %r / %r" % (v_none, v_none_exact))

    def _raises(d):
        raise OSError("volume unreadable")
    v_err = _with_attr("_volume_folds", _raises, lambda: _cf_decide(
        cfg, "Write", _w(dir_case), main, "agent-cf")[0], on=_config)
    v_err_plain = _with_attr("_volume_folds", _raises, lambda: _cf_decide(
        cfg, "Write", _w(os.path.join(fresh, "src", "app.ts")), main,
        "agent-cf")[0], on=_config)
    check("cf25d an error asking the volume lands where the config's other "
          "disk errors land - a case-variant config path is still refused "
          "(%s) - while an ordinary write beside it is allowed (%s)"
          % (v_err, v_err_plain),
          v_err == "block" and v_err_plain == "allow")

    # One question for every tree: the project's own config and a nested one
    # are both answered by the same function, which is shown by answering it
    # "not the config" and seeing both writes go through.
    asked_of = []

    def _never(path, top):
        asked_of.append(top)
        return None
    pconf = os.path.join(main, *rel)
    got = _with_attr("_names_audit_config", _never, lambda: [
        _cf_decide(cfg, "Write", _w(p), main, "agent-cf")[0]
        for p in (pconf, nconf)], on=_config)
    check("cf26 the project's config and a nested tree's are judged by one "
          "function: answered 'not the config', both writes are allowed (%s) "
          "and it was asked of both trees" % (got,),
          got == ["allow", "allow"]
          and os.path.realpath(main) in [os.path.realpath(t) for t in asked_of]
          and os.path.realpath(nested) in [os.path.realpath(t)
                                           for t in asked_of])

    # A hard link is the same file under another name; a copy is another file.
    with open(pconf, "w", encoding="utf-8") as fh:
        fh.write(_CF_BODY)
    link = os.path.join(main, "cf-notes.json")
    copy = os.path.join(main, "cf-copy.json")
    made, why = _harness.attempt(os.link, pconf, link)
    if made:
        _cf("cf27 a hard link to the project's config under another name is "
            "the config and is refused", "block", "Write", _w(link), cwd=main)
    else:
        check("cf27 the hard link fixture builds (%s)" % (why,), False)
    with open(copy, "w", encoding="utf-8") as fh:
        fh.write(_CF_BODY)
    _cf("cf27b ...while a copy of it under that kind of name is another file "
        "and allowed", "allow", "Write", _w(copy), cwd=main)
    if os.name != "nt":
        alias = os.path.join(main, "cf-alias.json")
        os.symlink(nconf, alias)
        _cf("cf27c a symlink under another name pointing at a nested "
            "worktree's config is that config and is refused", "block",
            "Write", _w(alias), cwd=main)

    # What must stay quiet, on every volume.
    deep = os.path.join(nested, "src", "deep")
    os.makedirs(os.path.join(deep, rel[0]))
    for cid, label, path in (
            ("cf28", "a deep plain folder named .claude inside the nested "
             "worktree's source, which is not that tree's config",
             os.path.join(deep, *rel)),
            ("cf28b", "...the same through a case-variant spelling",
             os.path.join(deep, _cap(rel[0]), "Audit.Config.json")),
            ("cf28c", "a file whose name only starts like the config's",
             os.path.join(nested, rel[0], rel[1] + ".bak")),
            ("cf28d", "the config's name directly under the worktree root",
             os.path.join(nested, rel[1]))):
        _cf("%s %s is allowed (%s)" % (cid, label, vol), "allow", "Write",
            _w(path), cwd=main)
    other = main + "2"
    os.makedirs(os.path.join(other, rel[0]))
    _harness.git(other, "init", "-q", prefix=_harness.WORKTREE_PAIR_GIT)
    _cf("cf28e an unrelated repository whose name has the project's as a "
        "prefix keeps its answer: its config is not this project's", "allow",
        "Write", _w(os.path.join(other, rel[0], _cap(rel[1]))),
        cwd=main)

    # An ordinary write costs the disk what the question makes by its sequence,
    # call by call, and no more in total than before the identity question
    # existed. Counted over every call of `_DISK_CALLS` (`_disk_calls`), for an
    # existing and a new source file and for a file merely named like the
    # config in a plain folder. Four references: the sequence the question made
    # for such a write before identity (resolve the path, resolve the config,
    # resolve the path again, compare the two as files when both exist); the
    # sequence it made once identity was asked and before the config's folder
    # was resolved (`_walked`: resolve both, read the path, read the config when
    # the path exists, and ask the folder the config-shaped name hangs off
    # whether it holds a repository); the sequence it makes now (`_today`: the
    # same, and for a write that would create its file, the config's folder and
    # file each asked whether it is a link, which is what resolving the
    # candidate tree's config path costs; and only for a file named as the
    # config is, the config itself, then the two folders, read for whether the
    # write is it, the directory the config would hang off asked as spelled
    # and resolved whether it holds a repository, the common directory read
    # for the repository's registrations - its registrations directory listed,
    # each registration that is a file read and its directory asked whether it
    # exists - and each registered tree not yet asked resolved and asked the
    # identity question); and the same question with the nested-tree half
    # answered "no candidate". Only the file named as the config pays more
    # than before identity was asked, and lists one directory: the
    # registrations'. A listing is its own case.
    #
    # The call-for-call comparisons hold whichever way a call is counted, since
    # both sides make the same library calls. The budget against the question
    # before identity does not: it compares sequences with different numbers
    # of `realpath` calls, and a posix `realpath` is built from counted calls
    # while a windows one is not, so on posix the library's own cost decided
    # it. The budget is therefore counted as the question's own source asks
    # (`_disk_calls(..., outer=True)`), the same on every host - and by that
    # measure a write that creates its file may pay more than before by the
    # link questions above, one per component of `CONFIG_REL`, which the
    # budget allows it and no other write; the case prints both totals.
    def _before(target, own):
        os.path.realpath(target)
        os.path.realpath(own)
        os.path.realpath(target)
        if os.path.exists(target) and os.path.exists(own):
            os.path.samefile(target, own)

    def _shaped(real):
        head, name = os.path.split(real)
        head2, name2 = os.path.split(head)
        same = (name2.casefold(), name.casefold()) == tuple(
            p.casefold() for p in rel)
        return head2 if same else None

    def _walked(target, root):
        real = os.path.realpath(target)
        real_root = os.path.realpath(root)
        if _harness.attempt(os.stat, real)[0]:
            _harness.attempt(os.stat, os.path.join(real_root, *rel))
        top = _shaped(real)
        if top is not None and top != real_root:
            _config._holds_repository(top)

    def _is_repository_entry(at):
        """A git entry that is a repository: one stat of the entry, then, for
        a directory, one lstat of the HEAD it holds."""
        import stat
        dotgit = os.path.join(at, ".git")
        found, st = _harness.attempt(os.stat, dotgit)
        if not found:
            return False
        if stat.S_ISDIR(st.st_mode):
            return os.path.lexists(os.path.join(dotgit, "HEAD"))
        return False

    def _checkout_walk(project):
        """The walk from the project up to the first directory whose git entry
        is a repository: the project resolved, then one entry asked per
        directory and the HEAD in the one that ends it - one directory here,
        the project being its checkout's top."""
        at = os.path.realpath(project)
        while not _is_repository_entry(at):
            at = os.path.dirname(at)
        return at

    def _registrations(project):
        """The trees `project`'s repository registers, read as git keeps them
        - the main checkout's own common directory here, found by the walk."""
        common = os.path.join(_checkout_walk(project), ".git")
        os.path.isdir(common)
        os.path.isfile(os.path.join(common, "commondir"))
        os.path.isfile(os.path.join(common, "HEAD"))
        os.path.isdir(os.path.join(common, "objects"))
        os.path.isdir(os.path.join(common, "refs"))
        regs = os.path.join(common, "worktrees")
        found = []
        for name in sorted(os.listdir(regs)):
            reg = os.path.join(regs, name)
            if not os.path.isfile(os.path.join(reg, "gitdir")):
                continue
            with open(os.path.join(reg, "gitdir"), "r", encoding="utf-8") as fh:
                dotgit = fh.readline().strip()
            at = os.path.dirname(os.path.normpath(os.path.join(reg, dotgit)))
            if os.path.isdir(at):
                found.append(at)
        return found

    def _named_tail(target, real, real_root):
        for top in (_shaped(os.path.normpath(target)), _shaped(real)):
            if top is not None:
                _config._holds_repository(top)
        for at in _registrations(main):
            resolved = os.path.realpath(at)
            if resolved != real_root:
                _config._names_audit_config(real, resolved)

    def _today(target, root):
        real = os.path.realpath(target)
        named = os.path.basename(real).casefold() == rel[-1].casefold()
        real_root = os.path.realpath(root)
        own = os.path.join(real_root, *rel)
        if _harness.attempt(os.stat, real)[0]:
            _harness.attempt(os.stat, own)
        else:
            at = real_root
            for name in rel:
                at = os.path.join(at, name)
                os.path.islink(at)
            if named and not _harness.attempt(os.stat, own)[0]:
                _harness.attempt(os.stat, os.path.dirname(real))
                _harness.attempt(os.stat, os.path.dirname(own))
        top = _shaped(real)
        if top is not None and top != real_root:
            _config._holds_repository(top)
        if named:
            _named_tail(target, real, real_root)

    def _kinds(by):
        return dict((k.rsplit(".", 1)[-1], n) for k, n in sorted(by.items()))

    plain_cfg = os.path.join(main, "docs", "cf-sample", *rel)
    os.makedirs(os.path.dirname(plain_cfg))
    costs, kinds, budget = [], [], []
    for src, plain in ((os.path.join(nested, "src", "app.ts"), False),
                       (os.path.join(nested, "src", "cf-new.ts"), False),
                       (plain_cfg, True)):
        data = {"tool_name": "Write", "tool_input": _w(src), "cwd": main,
                "agent_id": "agent-cf"}
        tree = _config.tree_for(data, src, cfg)
        asked = _config.config_question(tree, src, data) if hasattr(
            _config, "config_question") else tree
        root = str(tree["root"])
        target = os.path.join(root, *str(tree["rel"]).split("/"))
        own = os.path.join(root, *rel)
        _, before = _disk_calls(lambda: _before(target, own))
        _, walked = _disk_calls(lambda: _walked(target, root))
        _, today = _disk_calls(lambda: _today(target, root))
        verdict, now = _disk_calls(lambda: _config_way(asked))
        _, off = _disk_calls(lambda: _with_attr(
            "_config_shaped_top", lambda real: None,
            lambda: _config_way(asked), on=_config))
        _, before_own = _disk_calls(lambda: _before(target, own), outer=True)
        _, now_own = _disk_calls(lambda: _config_way(asked), outer=True)
        links = 0 if os.path.exists(target) else len(rel)
        listed = sum(now.get(n, 0) for n in _LISTINGS)
        name = os.path.basename(src) if not plain else "plain folder"
        within = sum(now_own.values()) <= sum(before_own.values()) + links
        costs.append((name, verdict, sum(before.values()),
                      sum(walked.values()), sum(now.values()), listed,
                      now == today and (plain or (now == off and within))))
        kinds.append((name, _kinds(walked), _kinds(now)))
        if not plain:
            budget.append((name, sum(before_own.values()),
                           sum(now_own.values()), links, within))
    _, walk = _disk_calls(lambda: _checkout_walk(main))
    check("cf29 an ordinary write - an existing and a new source file - and a "
          "file merely named like the config in a plain folder make the config "
          "question's disk calls call for call: before the walk's, and for a "
          "write that creates its file a link question for the config's "
          "folder and its file, what resolving the project's config path "
          "costs; the ordinary ones none for the nested tree's identity and no "
          "more in total than before identity was asked beside the link "
          "questions a creating write pays, counted as the question's own "
          "source asks (a library call once, whatever this host builds it "
          "from); the config-named one the registrations read and each "
          "registered tree asked - those found from the checkout the project lies in, the walk to it adding "
          "%d calls for a project at its checkout's top %r and no member place "
          "asked (name, verdict, before identity, before the folder was "
          "resolved, now, listings, held): %r; by kind, before the folder was "
          "resolved and now: %r; as the question's own source asks (name, "
          "before identity, now, link questions allowed, within): %r"
          % (sum(walk.values()), _kinds(walk), costs, kinds, budget),
          len(costs) == 3 and len(budget) == 2
          and all(not v and held
                  for _n, v, _b, _t, _now, _l, held in costs))
    check("cf29b ...and the ordinary ones list no directory, the config-named "
          "one the registrations' alone (listings: %r)"
          % ([(c[0], c[5]) for c in costs],),
          [c[5] for c in costs] == [0, 0, 1])

    _table_case(check)
    _walk_cases(check, cfg, main, fresh, rel, _w)


def _table_case(check):
    """cf30: the counter's table against the source it counts."""
    import ast
    gsrc = _harness.module_source(M)
    reach = _question_reach(_harness.module_source(_config), "audit_config_way")
    calls = _os_calls_in(ast.parse(gsrc))
    for node in reach.values():
        calls.extend(_os_calls_in(node))
    counted = set("%s.%s" % pair for pair in _DISK_CALLS)
    unknown = sorted(set(c for c in calls
                         if c not in counted and c not in _NOT_DISK))
    unwrapped = sorted("%s.%s" % (o, n) for o, n in _DISK_CALLS
                       if not hasattr(_owner(o), n))
    check("cf30 the disk-call counter's table is complete against the source: "
          "every os. and os.path. call in guard-edits.py and in the part of "
          "_config the config question reaches (%s) is counted or named as "
          "touching no disk, and every counted name exists here - unknown %r, "
          "unwrapped %r" % (", ".join(sorted(reach)) or "NOTHING REACHED",
                            unknown, unwrapped),
          "_volume_folds" in reach and "_names_audit_config" in reach
          and calls and not unknown and not unwrapped)


def _walk_cases(check, cfg, main, fresh, rel, _w):
    """cf31, cf31b: each component of a creating write is judged in the
    directory that holds it, asked of the walk that judges it
    (`_config._case_walk`) with both of the volume's answers substituted:
    `_one_entry(directory, name, own)` and `_volume_folds(directory)` are
    answered from `model`, a directory's rule, and every question is recorded.

    The walk is driven, not the hook, because the hook asks the real disk
    before it reaches the walk - `_one_place` looks the written folder up as
    spelled, which finds the config's folder on a volume that folds case and
    nothing on one that tells case apart, and a windows `realpath` returns the
    folder in its stored letter case - so the hook's answer is the host's and
    a model substituted under it is not what decides. The questions the walk
    asks that are NOT substituted are recorded as well, and each must be of a
    path spelled as the config's own below the directory the case made, an
    answer no host can change. That, and not the word in the label, is what
    lets every host run these two.

    cf31c and cf31d: what the hook answers end to end for the same writes, on
    the real volume the suite stands on, read from the disk."""
    top = os.path.realpath(fresh)
    cdir = os.path.join(top, rel[0])
    os.makedirs(cdir)
    with open(os.path.join(cdir, "settings.json"), "w", encoding="utf-8") as fh:
        fh.write("{}\n")
    walk = getattr(_config, "_case_walk", None)
    own_spelled = [os.path.join(top, *rel[:i + 1]) for i in range(len(rel))]

    def _rel(path):
        return os.path.relpath(path, top) if isinstance(path, str) else path

    def _run(model, parts):
        """(the walk's word, the substituted questions, every unsubstituted
        question not of a path spelled as the config's own)."""
        asked = {"entry": [], "rule": []}

        def entry(directory, name, own):
            asked["entry"].append((_rel(directory), name, own))
            return bool(model.get(directory))

        def rule(directory):
            asked["rule"].append(_rel(directory))
            return model.get(directory)
        if walk is None:
            return "NO _config._case_walk", asked, []
        word, calls = _disk_record(lambda: _with_attr(
            "_one_entry", entry, lambda: _with_attr(
                "_volume_folds", rule, lambda: walk(top, tuple(parts),
                                                    tuple(rel)),
                on=_config), on=_config), outer=True)
        stray = [(call, _rel(arg)) for call, arg in calls
                 if arg not in own_spelled]
        return word, asked, stray

    up = _cap(rel[0])
    here = os.curdir
    folds_above = {top: True, cdir: False}
    folds_below = {top: False, cdir: True}
    seen = []
    for label, model, parts, want, entries, rules in (
            ("dir-variant, top folds, .claude tells case apart", folds_above,
             (up, rel[1]), "folded", [(here, up, rel[0])], []),
            ("both variant, top folds, .claude tells case apart", folds_above,
             (up, "Audit.Config.json"), None, [(here, up, rel[0])], [rel[0]]),
            ("dir-variant, top tells case apart, .claude folds", folds_below,
             (up, rel[1]), None, [(here, up, rel[0])], []),
            ("name-variant, top tells case apart, .claude folds", folds_below,
             (rel[0], "Audit.Config.json"), "folded", [], [rel[0]])):
        word, asked, stray = _run(model, parts)
        right = (word == want and asked["entry"] == entries
                 and asked["rule"] == rules and not stray)
        seen.append((label, word, right) if right else (
            label, word, right, {"want": (want, entries, rules),
                                 "asked": asked, "unsubstituted": stray}))
    check("cf31 STUBBED, the same on every host - each component of a creating "
          "write is judged in the directory that holds it: where the config's "
          "own component exists there by whether both names reach one entry, "
          "where it does not by that directory's own rule; a name in the "
          "project tree is never asked of the .claude below it, nor the "
          "reverse; and the walk asks the disk nothing it was not handed but "
          "paths spelled as the config's own (row, the walk's word, right): %r"
          % (seen,),
          len(seen) == 4 and all(s[2] for s in seen))

    dir_only = os.path.join(top, up, rel[1])
    both = os.path.join(top, up, "Audit.Config.json")
    top_folds = _swapped_exists(cdir)
    cdir_folds = not _swapped_differs(cdir)
    ends = [(_rel(p), agent is None,
             _cf_decide(cfg, "Write", _w(p), main, agent)[0])
            for p in (dir_only, both) for agent in ("agent-cf", None)]
    held = (top_folds, top_folds, top_folds and cdir_folds,
            top_folds and cdir_folds)
    want = [(r, m, ("ask" if m else "block") if h else "allow")
            for (r, m, _g), h in zip(ends, held)]
    vol = ("read from the disk: the project tree folds case: %s, its .claude "
           "folds case: %s; host %s" % (top_folds, cdir_folds, sys.platform))
    halves = (
        ("cf31c the hook end to end, on a real volume that folds case: .claude "
         "existing and the config absent, a creating write through the "
         "folder's name in another case, and through folder and file both, is "
         "held - refused to a subagent, asked of the main session - each name "
         "judged by the rule of the directory it is looked up in"),
        ("cf31d ...and on a real volume that tells case apart the same writes "
         "are another file and allowed"))
    # Which half runs is the disk's answer just read, so the half not run is
    # printed as not run here - never as passed - and the other kind of volume
    # runs it: a CI runner on one, or a case-sensitive disk image under TMPDIR.
    ran, other = halves if top_folds else halves[::-1]
    check("%s (%s): %r" % (ran, vol, ends), ends == want and len(ends) == 4,
          "want %r" % (want,))
    _harness.skip(check, other, "the volume this suite stands on %s (%s); "
                  "this half runs on a volume that %s" % (
                      "folds case" if top_folds else "tells case apart", vol,
                      "tells case apart" if top_folds else "folds case"), True)

    os.remove(os.path.join(cdir, "settings.json"))
    os.rmdir(cdir)
    created = []
    for model, want in (({top: True}, "folded"), ({top: False}, None)):
        word, asked, stray = _run(model, (up, "Audit.Config.json"))
        created.append((model[top], word, asked["entry"], asked["rule"],
                        stray))
    check("cf31b STUBBED, the same on every host: with no .claude yet, the "
          "directory the write would create takes the rule of the directory "
          "it would be created in - one question of the tree, asked once, "
          "folded where it folds and another file where it does not, no "
          "identity question where nothing exists, and nothing else asked of "
          "the disk but paths spelled as the config's own (folds, the walk's "
          "word, identity questions, rule questions asked of, unsubstituted): "
          "%r" % (created,),
          [c[1] for c in created] == ["folded", None]
          and all(c[2] == [] and c[3] == [here] and not c[4]
                  for c in created))


_IMAGE_TOOL = "hdiutil"


def _swapped_differs(directory):
    """Whether `directory` tells case apart: a probe file made there is not
    reached under its upper-cased name. Asked of the disk, apart from the hook."""
    probe = os.path.join(directory, "cf-case-probe")
    with open(probe, "w", encoding="utf-8") as fh:
        fh.write("\n")
    try:
        return not os.path.exists(os.path.join(directory, "CF-CASE-PROBE"))
    finally:
        os.remove(probe)


def _volume_pair_cases(check, cfg):
    """cf32: the same question on REAL directories with different case rules - a
    disk image mounted at the project's `.claude`, made with the rule the host's
    own volume does not have. macOS builds it with `hdiutil`, unprivileged; a
    host without that tool is skipped by name, and the image is detached in a
    `finally` whatever the cases did."""
    import shutil
    import subprocess
    label = ("cf32 a creating write through a name differing in case, on real "
             "directories with different rules (a disk image mounted at the "
             "project's .claude)")
    tool = shutil.which(_IMAGE_TOOL)
    if tool is None:
        _harness.skip(check, label, "no %s on this host to build a directory "
                      "with a case rule of its own" % (_IMAGE_TOOL,), True)
        return
    base = os.path.realpath(_harness.fixture_root("guard-edits-vol-"))
    proj = os.path.join(base, "proj")
    mount = os.path.join(proj, ".claude")
    os.makedirs(mount)
    host_tells = _swapped_differs(proj)
    fs = "APFS" if host_tells else "Case-sensitive APFS"
    image = os.path.join(base, "cf-case.dmg")
    prev = os.environ.get("CLAUDE_PROJECT_DIR")
    attached = False
    try:
        made = subprocess.run(
            [tool, "create", "-quiet", "-size", "4m", "-fs", fs, "-volname",
             "cfcase", "-o", image], capture_output=True, timeout=120)
        if made.returncode == 0:
            made = subprocess.run(
                [tool, "attach", "-quiet", "-nobrowse", "-noautoopen",
                 "-mountpoint", mount, image], capture_output=True,
                timeout=120)
            attached = made.returncode == 0
        if not attached:
            _harness.could_not_run(check, label, "%s refused: %s" % (
                _IMAGE_TOOL, _harness.tail_bytes(
                    made.stderr.decode("utf-8", "replace").strip(), 400)))
            return
        with open(os.path.join(mount, "settings.json"), "w",
                  encoding="utf-8") as fh:
            fh.write("{}\n")
        mount_tells = _swapped_differs(mount)
        os.environ["CLAUDE_PROJECT_DIR"] = proj
        rel = _config.CONFIG_REL.split("/")
        dir_variant = os.path.join(proj, _cap(rel[0]), rel[1])
        name_variant = os.path.join(mount, "Audit.Config.json")
        got = [(os.path.relpath(p, proj), agent is None,
                _cf_decide(cfg, "Write", {"file_path": p, "content": _CF_BODY},
                           proj, agent)[0])
               for p in (dir_variant, name_variant)
               for agent in ("agent-cf", None)]
        want = [(r, m, ("ask" if m else "block") if held else "allow")
                for (r, m, _g), held in zip(got, (not host_tells,
                                                  not host_tells,
                                                  not mount_tells,
                                                  not mount_tells))]
        check("%s: the project tree tells case apart: %s, the mounted .claude "
              "tells case apart: %s, host %s - a name is held where the "
              "directory it is looked up in folds case, and is another file "
              "where it does not: %r" % (label, host_tells, mount_tells,
                                         sys.platform, got),
              host_tells != mount_tells and got == want and len(got) == 4,
              "want %r" % (want,))
        check("cf32b ...and nothing was created: the config is absent after "
              "the hook was asked", not os.path.exists(
                  os.path.join(mount, rel[1])))
        # The real twin of cf31's substituted row with both names in another
        # case: held only where both directories they are looked up in fold,
        # and here one of them tells case apart, whichever the host's is.
        both_got = [(agent is None, _cf_decide(
            cfg, "Write", {"file_path": os.path.join(
                proj, _cap(rel[0]), "Audit.Config.json"), "content": _CF_BODY},
            proj, agent)[0]) for agent in ("agent-cf", None)]
        both_held = not host_tells and not mount_tells
        check("cf32e ...and a name differing in case in both the folder and "
              "the file is held only where both directories it is looked up in "
              "fold - one of them tells case apart here, so it is another file "
              "and allowed (project tree tells case apart: %s, mounted .claude "
              "tells case apart: %s): %r" % (host_tells, mount_tells, both_got),
              both_got == [(m, ("ask" if m else "block") if both_held
                            else "allow") for m in (False, True)])
        # A repository nested INSIDE the mounted directory, its `.claude`
        # present: there the config's own directory exists, so a name differing
        # in case is judged by identity, in the mount - which answers "one
        # entry" only where the mount folds.
        inner = os.path.join(mount, "worktrees", "cf-inner")
        os.makedirs(os.path.join(inner, ".git"))
        os.makedirs(os.path.join(inner, rel[0]))
        with open(os.path.join(inner, rel[0], "settings.json"), "w",
                  encoding="utf-8") as fh:
            fh.write("{}\n")
        inner_got = [(os.path.relpath(p, proj), _cf_decide(
            cfg, "Write", {"file_path": p, "content": _CF_BODY}, proj,
            "agent-cf")[0])
            for p in (os.path.join(inner, _cap(rel[0]), rel[1]),
                      os.path.join(inner, rel[0], rel[1]))]
        check("cf32d ...and a repository nested inside the mounted directory "
              "is judged by that directory's rule: its config through a "
              "directory name in another case is held only where the mount "
              "folds, the exact spelling always (mount tells case apart: %s): "
              "%r" % (mount_tells, inner_got),
              [g for _r, g in inner_got]
              == ["allow" if mount_tells else "block", "block"])
    finally:
        if prev is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = prev
        if attached:
            gone = subprocess.run([tool, "detach", "-quiet", mount],
                                  capture_output=True, timeout=120)
            if gone.returncode != 0:
                gone = subprocess.run([tool, "detach", "-quiet", "-force",
                                       mount], capture_output=True,
                                      timeout=120)
            check("cf32c the disk image is detached again (%s)"
                  % (gone.stderr.decode("utf-8", "replace").strip()
                     or "detached",), gone.returncode == 0)


# --- cf: the config a session would load, its folder a symlink ---------------------
# The property, by doing. For each arrangement the hook runs as a process for its
# verdict, a subagent's and the main session's; then the write is made in the
# fixture and the loader is asked, for every tree the fixture built, whether it now
# reads what was written. The hook holds the write exactly when one of the trees
# of this repository, or of a repository nested under the project, does. The
# trees are the ones the builders record as they make them - none is found by a
# walk - so the oracle and the subject do not share an answer. A tree the
# property does not cover (another repository, a worktree whose registration is
# gone, a repository nested under another tree) is recorded apart as FOREIGN and
# its loader asked too, so a row the documents list as not matched shows here as
# allowed while a loader reads it.
#
# A ROW IS ONE ARRANGEMENT: (id, layout, config present, spelling, measured, twin).
# `layout` is how the project's config folder is made and `spelling` how the write
# names the file and where the session stands; `_link_world` and `_link_spell`
# hold one branch per word. `measured` marks an arrangement the review ran as a
# process and found allowed; `twin` an allow twin, a write no loader reads.
# `_LINK_RESIDUAL` names the rows a tree of this repository reads and the hook
# lets through, each with the reason it is not matched.
_LINK_ROWS = (
    ("ln1", "real", False, "link", False, False),
    ("ln2", "real", True, "link", False, False),
    ("ln3", "in-project", False, "link", True, False),
    ("ln4", "in-project", True, "link", True, False),
    ("ln5", "in-project", False, "dest", True, False),
    ("ln6", "in-project", True, "dest", True, False),
    ("ln7", "outside", False, "link", True, False),
    ("ln8", "outside", True, "link", True, False),
    ("ln9", "outside", False, "dest", True, False),
    ("ln10", "outside", True, "dest", True, False),
    ("ln11", "other-tree", False, "link", False, False),
    ("ln12", "other-tree", True, "link", False, False),
    ("ln13", "other-tree", False, "dest", False, False),
    ("ln14", "other-tree", True, "dest", False, False),
    ("ln15", "in-other-tree", False, "link", False, False),
    ("ln16", "in-other-tree", True, "link", False, False),
    ("ln17", "chain", False, "link", False, False),
    ("ln18", "chain", True, "dest", False, False),
    ("ln19", "relative", False, "link", False, False),
    ("ln20", "relative", True, "link", False, False),
    ("ln21", "dangling", False, "link", False, False),
    ("ln22", "dangling", False, "dest", False, False),
    ("ln23", "outside", False, "rel-cwd-link", False, False),
    ("ln24", "outside", True, "rel-cwd-dest", False, False),
    ("ln25", "outside", False, "nested-w", False, False),
    ("ln26", "outside", False, "nested-p", False, False),
    ("ln27", "outside", True, "name-case", False, False),
    ("ln28", "outside", True, "beside", False, True),
    ("ln29", "plain-link", False, "linked", False, True),
    ("ln30", "plain-link", False, "sub-link", False, True),
    ("ln31", "real", False, "no-tree", False, True),
    ("ln32", "loop", False, "link", False, False),
    ("ln33", "file-link", False, "link", False, False),
    ("ln34", "file-link", False, "file-dest", False, False),
    ("ln35", "session-tree", False, "session-dest", False, False),
    ("ln36", "unrelated", False, "unrelated", False, True),
    ("ln37", "sibling", True, "hard-link-out", False, False),
    ("ln38", "sibling", False, "file-link-out", False, False),
    ("ln39", "outside", False, "name-case", False, False),
    ("ln40", "sibling", True, "hard-link-in", False, False),
    ("ln41", "sibling", False, "nested-in-other", False, False),
    ("ln42", "real", False, "pruned", False, False),
    ("ln43", "sibling", True, "hard-link-session", False, False),
)

# The rows a tree of this repository reads while the hook allows the write.
_LINK_RESIDUAL = {
    "ln40": "a hard link under another name to another tree's existing config, "
            "written from a session that stands in no tree that loads it: the "
            "name is no config's and identity is asked only of the trees "
            "already asked",
}


def _link_world(base, layout, present):
    """A repository at `base/proj` whose config folder is arranged as `layout`
    says, with the config at the folder's destination when `present`.
    -> {"proj", "folder" (the folder as the project spells it), "dest" (the
    directory it reaches, spelled at the destination), "store"}"""
    rel = _config.CONFIG_REL.split("/")
    proj = os.path.join(base, "proj")
    os.makedirs(os.path.join(proj, "src"))
    with open(os.path.join(proj, "src", "x.ts"), "w", encoding="utf-8") as fh:
        fh.write("export const x = 1;\n")
    for argv in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "c"]):
        _harness.git(proj, *argv, prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
    folder = os.path.join(proj, rel[0])
    store = os.path.join(base, "store")
    os.makedirs(store)
    if layout in ("real", "plain-link", "unrelated"):
        dest = folder
        os.makedirs(folder)
    elif layout == "file-link":
        # The config FILE a dangling link: a write through it creates the
        # file it names, under that name.
        os.makedirs(folder)
        dest = store
        os.symlink(os.path.join(store, "conf.json"),
                   os.path.join(folder, rel[1]))
    elif layout == "loop":
        dest = os.path.join(proj, rel[0] + "2")
        os.symlink(rel[0] + "2", folder)
        os.symlink(rel[0], dest)
    elif layout == "sibling":
        # A real folder, and a sibling linked worktree with a config of its own.
        dest = folder
        os.makedirs(folder)
        ext = os.path.join(base, "ext")
        _harness.git(proj, "worktree", "add", "-q", ext, "-b", "ext",
                     prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
        os.makedirs(os.path.join(ext, rel[0]))
        with open(os.path.join(ext, *rel), "w", encoding="utf-8") as fh:
            json.dump({"cfMark": "ext"}, fh)
    elif layout == "session-tree":
        # The project's own folder is real; a sibling linked worktree, where
        # the session stands, has its `.claude` linked out of the repository.
        os.makedirs(folder)
        ext = os.path.join(base, "ext")
        _harness.git(proj, "worktree", "add", "-q", ext, "-b", "ext",
                     prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
        dest = os.path.join(store, "xdir")
        os.makedirs(dest)
        os.symlink(dest, os.path.join(ext, rel[0]))
    elif layout in ("in-project", "relative"):
        dest = os.path.join(proj, "config", "claude")
        os.makedirs(dest)
        os.symlink(dest if layout == "in-project"
                   else os.path.join("config", "claude"), folder)
    elif layout == "outside":
        dest = os.path.join(store, "claude-dir")
        os.makedirs(dest)
        os.symlink(dest, folder)
    elif layout == "chain":
        dest = os.path.join(store, "real")
        os.makedirs(dest)
        hop = os.path.join(base, "hop")
        os.symlink(dest, hop)
        os.symlink(hop, folder)
    elif layout in ("other-tree", "in-other-tree"):
        ext = os.path.join(base, "ext")
        _harness.git(proj, "worktree", "add", "-q", ext, "-b", "ext",
                     prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
        dest = os.path.join(ext, rel[0])
        if layout == "in-other-tree":
            dest = os.path.join(dest, "shared")
        os.makedirs(dest)
        os.symlink(dest, folder)
    elif layout == "dangling":
        dest = os.path.join(store, "missing")
        os.symlink(dest, folder)
    else:
        raise ValueError("no layout %r" % (layout,))
    with open(os.path.join(dest if os.path.isdir(dest) else store,
                           "settings.json"), "w", encoding="utf-8") as fh:
        fh.write("{}\n")
    if present:
        with open(os.path.join(dest, rel[1]), "w", encoding="utf-8") as fh:
            json.dump({"cfMark": "pre"}, fh)
    ext = os.path.join(base, "ext")
    made_ext = layout in ("sibling", "session-tree", "other-tree",
                          "in-other-tree")
    return {"proj": proj, "folder": folder, "dest": dest, "store": store,
            "base": base, "trees": [proj, ext] if made_ext else [proj]}


def _link_spell(world, spelling):
    """(the path the Write names, the session's directory, the trees this
    spelling built that the property covers, the trees it built that it does
    not) for `spelling`."""
    path, cwd = _link_spelled(world, spelling)
    base = world["base"]
    if spelling in ("nested-w", "nested-p"):
        return path, cwd, [os.path.join(world["folder"], "worktrees", "w1")], []
    if spelling == "unrelated":
        return path, cwd, [], [os.path.join(base, "other")]
    if spelling == "nested-in-other":
        return path, cwd, [], [os.path.join(base, "ext", "vendor", "lib")]
    if spelling == "pruned":
        return path, cwd, [], [os.path.join(base, "gone")]
    return path, cwd, [], []


def _link_spelled(world, spelling):
    """(the path the Write names, the session's directory) for `spelling`."""
    rel = _config.CONFIG_REL.split("/")
    proj, folder, dest = world["proj"], world["folder"], world["dest"]
    if spelling == "link":
        return os.path.join(folder, rel[1]), proj
    if spelling == "dest":
        return os.path.join(dest, rel[1]), proj
    if spelling == "beside":
        return os.path.join(folder, "settings.json"), proj
    if spelling == "name-case":
        return os.path.join(folder, rel[1].upper()), proj
    if spelling == "rel-cwd-link":
        return rel[1], folder
    if spelling == "rel-cwd-dest":
        return rel[1], dest
    if spelling in ("nested-w", "nested-p"):
        nested = os.path.join(folder, "worktrees", "w1")
        _harness.git(proj, "worktree", "add", "-q", nested, "-b", "w1",
                     prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
        return (os.path.join(nested, *rel),
                nested if spelling == "nested-w" else proj)
    if spelling in ("linked", "sub-link"):
        notes = os.path.join(world["store"], "notes")
        os.makedirs(notes)
        if spelling == "linked":
            os.symlink(notes, os.path.join(proj, "linked"))
            return os.path.join(proj, "linked", rel[1]), proj
        os.makedirs(os.path.join(proj, "sub"))
        os.symlink(notes, os.path.join(proj, "sub", rel[0]))
        return os.path.join(proj, "sub", *rel), proj
    if spelling == "no-tree":
        out = os.path.join(world["base"], "outside", rel[0])
        os.makedirs(out)
        return os.path.join(out, rel[1]), proj
    if spelling == "hard-link-out":
        # The project's config, hard-linked into the sibling worktree.
        link = os.path.join(world["base"], "ext", "src", "hl.json")
        os.link(os.path.join(dest, rel[1]), link)
        return link, proj
    if spelling == "file-link-out":
        # A symlink FILE in the project at the sibling worktree's existing
        # config: its resolved name is the config's, so the worktree the
        # registrations name is asked, and its loader reads the write.
        link = os.path.join(proj, "lf.json")
        os.symlink(os.path.join(world["base"], "ext", *rel), link)
        return link, proj
    if spelling in ("hard-link-in", "hard-link-session"):
        # The sibling worktree's config, hard-linked into the project: from a
        # session in the project, and from one standing in that worktree's
        # source, the tree found by walking up from the session's directory.
        link = os.path.join(proj, "src", "hl-in.json")
        os.link(os.path.join(world["base"], "ext", *rel), link)
        return link, (proj if spelling == "hard-link-in"
                      else os.path.join(world["base"], "ext", "src"))
    if spelling == "nested-in-other":
        # A repository nested under the sibling worktree, not under the
        # project, with a config folder of its own.
        lib = os.path.join(world["base"], "ext", "vendor", "lib")
        os.makedirs(os.path.join(lib, rel[0]))
        _harness.git(lib, "init", "-q", prefix=_harness.WORKTREE_PAIR_GIT,
                     timeout=30)
        return os.path.join(lib, *rel), proj
    if spelling == "pruned":
        # A worktree whose registration is gone: its `.git` file still names
        # the directory git kept for it, which no longer exists.
        gone = os.path.join(world["base"], "gone")
        _harness.git(proj, "worktree", "add", "-q", gone, "-b", "gone",
                     prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
        _harness.remove_tree(os.path.join(proj, ".git", "worktrees", "gone"))
        os.makedirs(os.path.join(gone, rel[0]))
        return os.path.join(gone, *rel), proj
    if spelling == "file-dest":
        return os.path.join(world["store"], "conf.json"), proj
    if spelling == "session-dest":
        return (os.path.join(dest, rel[1]),
                os.path.join(world["base"], "ext"))
    if spelling == "unrelated":
        # Another repository, no tree of this one, its `.claude` linked out.
        other = os.path.join(world["base"], "other")
        os.makedirs(other)
        _harness.git(other, "init", "-q", prefix=_harness.WORKTREE_PAIR_GIT,
                     timeout=30)
        odir = os.path.join(world["store"], "odir")
        os.makedirs(odir)
        os.symlink(odir, os.path.join(other, rel[0]))
        return os.path.join(other, *rel), proj
    raise ValueError("no spelling %r" % (spelling,))


def _tool_input(tool, path, body):
    """The payload `tool` carries for a write of `body` to `path`."""
    if tool.startswith("mcp__"):
        return {"path": path, "content": body}
    if tool == "Edit":
        return {"file_path": path, "old_string": "1", "new_string": "2"}
    return {"file_path": path, "content": body}


def _hook_verdict(proj, cwd, path, body, agent, tool="Write", env_extra=None,
                  timeout=60):
    """guard-edits.py run as the host runs it, for a write of `path` by `tool`
    from `cwd`: 'block', 'ask', 'allow', or a word naming what else happened.
    A run past `timeout` seconds raises `subprocess.TimeoutExpired`."""
    import subprocess
    data = {"hook_event_name": "PreToolUse", "tool_name": tool,
            "session_id": "sess-ln", "cwd": cwd,
            "tool_input": _tool_input(tool, path, body)}
    if agent:
        data["agent_id"] = "a1b2c3d4e5f6"
        data["agent_type"] = "audit-executor"
    env = dict((k, v) for k, v in os.environ.items()
               if not k.startswith("CLAUDE") and k != _DRIVE_MARK)
    env["CLAUDE_PROJECT_DIR"] = proj
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(env_extra or {})
    got = subprocess.run(
        [sys.executable, "-B", os.path.join(_harness.HOOKS_DIR,
                                            "guard-edits.py")],
        input=json.dumps(data).encode("utf-8"), capture_output=True,
        env=env, cwd=proj, timeout=timeout)
    out = got.stdout.decode("utf-8", "replace").strip()
    err = got.stderr.decode("utf-8", "replace")
    if got.returncode == 2:
        return "block"
    if got.returncode != 0 or "Traceback" in err:
        return "rc%d:%s" % (got.returncode, err.strip()[-160:])
    if not out:
        return "allow"
    try:
        said = json.loads(out).get("hookSpecificOutput", {})
    except ValueError:
        return "unreadable:%s" % (out[:160],)
    word = said.get("permissionDecision")
    return {"deny": "block"}.get(word, word or "allow")


def _link_row(base, row):
    """One arrangement: the hook's two verdicts, then the write made, then which
    of the trees the fixture built read it.
    -> (id, sub, main, trees the property covers that read, why, foreign trees
    that read)"""
    rid, layout, present, spelling = row[:4]
    world = _link_world(base, layout, present)
    path, cwd, more, foreign = _link_spell(world, spelling)
    body = json.dumps({"cfMark": rid}) + "\n"
    sub = _hook_verdict(world["proj"], cwd, path, body, True)
    main = _hook_verdict(world["proj"], cwd, path, body, False)
    full = path if os.path.isabs(path) else os.path.join(cwd, path)
    made, why = _harness.attempt(_link_write, full, body)

    def read_by(trees):
        return sorted(set(os.path.relpath(t, base) for t in trees
                          if _config.load(t).get("cfMark") == rid))
    reads = read_by(world["trees"] + more)
    if not made:
        # A write no tool can make (a link that cannot be followed): the
        # property has nothing to read, and the guard is owed the hold it gave
        # such a path before - fail closed, never a hold turned into an allow.
        reads = ["write not made: %s" % (why,)]
    return rid, sub, main, reads, "%s/%s/%s" % (
        layout, "present" if present else "absent", spelling), read_by(foreign)


def _link_write(full, body):
    """The write, made as a tool that creates missing directories makes it:
    through every link on the way, the missing ones at the place they name."""
    os.makedirs(os.path.realpath(os.path.dirname(full)), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(body)


def _link_cases(check):
    """cf33, cf34, cf34b: the arrangements of `_LINK_ROWS`, each in a fixture
    of its own."""
    label = ("cf33 a project whose config folder is a symlink: the hook run as "
             "a process over the arrangements of a symlinked config folder")
    base = os.path.realpath(_harness.fixture_root("guard-edits-link-"))
    probe = os.path.join(base, "probe-link")
    linked, why = _harness.attempt(os.symlink, base, probe)
    if not linked:
        _harness.skip(check, label, "no symlink can be made here (%s)" % (why,),
                      os.name == "nt" or not hasattr(os, "symlink"))
        return
    os.remove(probe)
    seen = []
    for i, row in enumerate(_LINK_ROWS):
        ok, got = _harness.attempt(_link_row, os.path.join(base, "r%d" % i), row)
        seen.append(got if ok else (row[0], "fixture", "fixture", [], repr(got),
                                    []))
    by_id = dict((s[0], s) for s in seen)

    def held(s):
        return s[1] == "block" and s[2] == "ask"

    def quiet(s):
        return s[1] == "allow" and s[2] == "allow"
    measured = [by_id[r[0]] for r in _LINK_ROWS if r[4]]
    check("cf33 with the config folder a symlink inside the project or outside "
          "the repository, the hook run as a process refuses a subagent's write "
          "of the config and asks the main session's - config present or "
          "absent, spelled through the link or at its destination; not held: "
          "%r" % ([s for s in measured if not held(s)],),
          len(measured) == 8 and all(held(s) and s[3] for s in measured))
    agree = [s for s in seen if s[0] not in _LINK_RESIDUAL
             and (held(s) if s[3] else quiet(s))]
    check("cf34 over a table of arrangements of the config folder - a real "
          "directory, a symlink inside the project, outside the repository, to "
          "another tree's config folder, into one, a chain, a relative link, a "
          "dangling link, a loop, the config file itself a dangling link, a "
          "nested worktree under it, a session in a linked worktree, a "
          "relative path, the project's config hard-linked into a sibling "
          "worktree, a symlink file at a sibling's config, a sibling's config "
          "hard-linked into the project from a session standing in the "
          "sibling - the hook holds a "
          "write exactly when the loader, asked for every tree of this "
          "repository the fixture built, then reads the written file (%d of %d "
          "rows agree, the residual rows %r apart); disagreeing: %r"
          % (len(agree), len(seen) - len(_LINK_RESIDUAL), sorted(_LINK_RESIDUAL),
             [s for s in seen if s not in agree
              and s[0] not in _LINK_RESIDUAL]),
          len(seen) == len(_LINK_ROWS)
          and len(agree) == len(seen) - len(_LINK_RESIDUAL)
          and any(s[3] for s in seen) and any(not s[3] for s in seen))
    twins = [by_id[r[0]] for r in _LINK_ROWS if r[5]]
    check("cf34b ...and the allow twins are allowed and no loader of a tree of "
          "this repository reads them: a file beside the config in the "
          "symlinked folder, a config-named file in a symlinked folder that is "
          "no tree's config folder, the same under a symlinked .claude of a "
          "plain subfolder, one outside every tree, and the config of an "
          "unrelated repository through its own symlinked .claude: %r"
          % (twins,),
          len(twins) == 5 and all(quiet(s) and not s[3] for s in twins))
    unmatched = [by_id[r] for r in ("ln36", "ln40", "ln41", "ln42")]
    check("cf34c what the documents list as not matched is allowed while a "
          "loader reads the write - another repository's config outside the "
          "project (ln36), a hard link under another name to another tree's "
          "config (ln40, %s), a repository nested under a tree other than the "
          "project (ln41), a worktree whose registration is gone (ln42): %r"
          % (_LINK_RESIDUAL["ln40"], unmatched,),
          all(quiet(s) and (s[3] or s[5]) for s in unmatched)
          and [bool(s[3]) for s in unmatched] == [False, True, False, False])
    _link_mcp_cases(check, os.path.join(base, "mcp"))
    _candidate_error_cases(check, os.path.join(base, "err"))


def _link_mcp_cases(check, base):
    """cf33b: an MCP write carries the same question through a symlinked
    folder - the locator resolves out of the repository as the edit tool's
    path does."""
    world = _link_world(base, "outside", False)
    proj = world["proj"]
    rel = _config.CONFIG_REL.split("/")
    cfg = _config._deep_merge(_config.DEFAULTS, {})
    prev = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = proj
    try:
        seen = [(name, agent is None, _cf_decide(
            cfg, "mcp__fs__write_file", {"path": path, "content": _CF_BODY},
            proj, agent)[0])
            for name, path in (("config", os.path.join(proj, *rel)),
                               ("beside", os.path.join(proj, rel[0],
                                                       "settings.json")))
            for agent in ("agent-cf", None)]
    finally:
        if prev is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = prev
    check("cf33b a subagent's MCP write of the config through a .claude linked "
          "out of the repository is refused and the main session's asked, "
          "while a file beside it is not held: %r" % (seen,),
          seen == [("config", False, "block"), ("config", True, "ask"),
                   ("beside", False, "allow"), ("beside", True, "allow")])


def _candidate_error_cases(check, base):
    """cf35: an error asking one candidate tree costs that tree only. The
    project's `.claude` links into a sibling linked worktree's, so the write is
    the project's config and that worktree's at once, and the question is
    asked of both - the worktree first, as `tree_for` placed the path there."""
    world = _link_world(base, "other-tree", False)
    proj = world["proj"]
    conf = os.path.join(proj, *_config.CONFIG_REL.split("/"))
    cfg = _config._deep_merge(_config.DEFAULTS, {})
    ext = os.path.realpath(os.path.dirname(world["dest"]))
    real = _config._names_audit_config
    asked = []

    def failing(only):
        def ask(path, top):
            asked.append(top)
            if only is None or top == only:
                raise OSError("candidate unreadable")
            return real(path, top)
        return ask
    prev = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = proj
    try:
        one = _with_attr("_names_audit_config", failing(ext), lambda: _cf_decide(
            cfg, "Write", {"file_path": conf, "content": _CF_BODY}, proj,
            "agent-cf")[0], on=_config)
        n_one = list(asked)
        every = _with_attr("_names_audit_config", failing(None),
                           lambda: _cf_decide(
                               cfg, "Write", {"file_path": conf,
                                              "content": _CF_BODY}, proj,
                               "agent-cf")[0], on=_config)
    finally:
        if prev is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = prev
    check("cf35 STUBBED - the question raising for the tree the path was "
          "placed in, the project is still asked and the write of its config "
          "through the link is refused (%s, asked of %r)"
          % (one, [os.path.relpath(t, base) for t in n_one]),
          one == "block" and n_one[:1] == [ext]
          and os.path.realpath(proj) in n_one)
    check("cf35b STUBBED: raising for every tree, the question answers 'not "
          "the config' and the write is allowed - the guard's fail-open row in "
          "SECURITY.md's table, stated rather than hidden (%s)" % (every,),
          every == "allow")


# --- cf: the property over a product of named dimensions ---------------------------
# `_LINK_ROWS` is a list someone wrote; this is generated. Each dimension is a named
# tuple of values, an arrangement is one value of each, and the arrangements are
# their product. A combination that cannot exist is skipped by a named predicate
# carrying its reason, and the case prints how many each predicate skipped, so a
# predicate grown too wide shows as a count rather than as missing rows. The bulk is
# the guard's `decide` in this process; one representative per family, and every
# measured arrangement, is then the hook run as a process, and the two must agree.
# The oracle owes the module nothing: the world builder records every place it
# makes that a loader could be handed - the project and its checkout's top, each
# worktree's top and, for a member project, each worktree's member place, each
# repository it initialises - and after the write the loader is asked for each
# of them. No tree is found by a walk, so a
# defect in how the module finds its trees cannot be shared by the oracle. A family
# the property names and the module cannot see is a RESIDUAL (`_GEN_RESIDUAL`),
# named with its reason: its rows are owed an allow while a loader reads them, so
# the documents' list of what is not matched is a list of rows that ran.
_Dim = collections.namedtuple("_Dim", "name values")
_GEN_DIMS = (
    _Dim("whose", ("project", "session-tree", "linked-out", "nested-worktree",
                   "nested-repo")),
    # How the tree's config folder is made: a real directory, a symlink, a chain
    # of two, a dangling link, a symlink to a directory that is a repository, a
    # real folder that is itself a repository, a real folder holding an empty
    # git entry.
    _Dim("folder", ("real", "link", "chain", "dangling", "link-repo", "repo",
                    "git-entry")),
    # Where a link's destination lies: inside the tree whose config it is,
    # inside the project, or outside every tree.
    _Dim("dest", ("owner", "project", "outside")),
    _Dim("present", (False, True)),
    # Where the project lies in its checkout: at the top, or below it - a
    # member project, `top/<_GEN_MEMBER>`, whose every tree has a member place
    # `<tree>/<_GEN_MEMBER>` beside its top.
    _Dim("member", ("top", "down")),
    # Which place of the owner's tree the config is: its top, or the member's
    # place in it. A project at its checkout's top has none apart from the top.
    _Dim("place", ("top", "member")),
    # How the write names the file: through the config folder as the tree spells
    # it, at the folder's destination, or - the allow twin - a config-named file
    # in a plain folder of the tree that holds an empty git entry, under a
    # directory holding another, which is no tree's config folder.
    _Dim("form", ("link", "dest", "plain")),
    # Which component carries a letter-case variant, counted from the file name
    # (0) up to the fixture's own directory; None is no variant.
    _Dim("level", (None, 0, 1, 2, 3, 4, 5, 6)),
    _Dim("session", ("project", "owner")),
    _Dim("tool", ("Write", "mcp__fs__write_file")),
)
_Arr = collections.namedtuple("_Arr", [d.name for d in _GEN_DIMS])
# The dimensions one fixture world is built from; the rest vary over a world.
_GEN_WORLD_DIMS = ("whose", "folder", "dest", "present", "member", "place")
# The dimensions a family is counted by: the case fails when one value ran none.
_GEN_FAMILY_DIMS = ("whose", "folder", "dest", "member", "place")
# The member's place below its checkout's top, for a member project: two
# directories, so a member path cut to its last component or a walk stopped one
# directory above the project answers wrong here. `_member_world` keeps the
# one-directory row.
_GEN_MEMBER = os.path.join("a", "b")
_GEN_BODY_KEY = "cfMark"
_GEN_PLAN = {"meta": {"version": 3, "developmentBranch": "main"}, "phases": []}
_GEN_MCP = "mcp__fs__write_file"

# The arrangements a review ran as processes and found allowed while a loader read
# the write. First round: a linked worktree outside the project, its config folder
# linked out of the repository, written through the link from the project
# (absent, present, by an MCP tool); and the project's linked-out folder written
# at its destination with the directory above that destination in another case.
# Later rounds: a nested worktree's or a nested repository's config folder a
# symlink to a repository; an outside worktree's folder a symlink to a
# repository or itself one; an outside worktree's config written at its link's
# destination, inside the project and outside it. Then the member project: an
# outside worktree's member place written directly, its top's config folder
# linked out of the repository written at the destination and through the link,
# and the checkout's top written at its folder's destination.
def _gen_at(whose, folder, dest, present, form, level, session, tool,
            member="top", place="top"):
    """An arrangement, the project at its checkout's top unless said."""
    return _Arr(whose, folder, dest, present, member, place, form, level,
                session, tool)


_GEN_MEASURED = (
    ("a-absent", _gen_at("linked-out", "link", "outside", False, "link", None,
                         "project", "Write")),
    ("a-present", _gen_at("linked-out", "link", "outside", True, "link", None,
                          "project", "Write")),
    ("a-mcp", _gen_at("linked-out", "link", "outside", False, "link", None,
                      "project", _GEN_MCP)),
    ("b-case-above", _gen_at("project", "link", "outside", False, "dest", 2,
                             "project", "Write")),
    ("h1-nested-wt", _gen_at("nested-worktree", "link-repo", "outside", False,
                             "link", None, "project", "Write")),
    ("h1-nested-wt-mcp", _gen_at("nested-worktree", "link-repo", "outside",
                                 True, "link", None, "project", _GEN_MCP)),
    ("h1-nested-repo", _gen_at("nested-repo", "link-repo", "outside", True,
                               "link", None, "project", "Write")),
    ("h2-ext-link-repo", _gen_at("linked-out", "link-repo", "outside", False,
                                 "link", None, "project", "Write")),
    ("h2-ext-repo", _gen_at("linked-out", "repo", "owner", True, "link", None,
                            "project", _GEN_MCP)),
    ("m2-ext-dest-in-project", _gen_at("linked-out", "link", "project", False,
                                       "dest", None, "project", "Write")),
    ("u3b-ext-dest-outside", _gen_at("linked-out", "link", "outside", False,
                                     "dest", None, "project", "Write")),
    ("member-wt-place", _gen_at("linked-out", "real", "owner", False, "link",
                                None, "project", "Write", "down", "member")),
    ("member-wt-top-dest", _gen_at("linked-out", "link", "outside", False,
                                   "dest", None, "project", "Write", "down")),
    ("member-wt-top-link", _gen_at("linked-out", "link", "outside", False,
                                   "link", None, "project", "Write", "down")),
    ("member-top-dest", _gen_at("project", "link", "outside", False, "dest",
                                None, "project", "Write", "down")),
)


def _gen_is_project(arr):
    """The owner is the project itself - not the top of a member project's
    checkout, which is another place of the same tree."""
    return arr.whose == "project" and (arr.member == "top"
                                       or arr.place == "member")


def _gen_owner_is_project(arr, world):
    return _gen_is_project(arr) and arr.session == "owner"


def _gen_no_member_place(arr, world):
    return arr.member == "top" and arr.place == "member"


def _gen_nested_repo_member(arr, world):
    return arr.whose == "nested-repo" and arr.place == "member"


def _gen_member_spelled_once(arr, world):
    return arr.member == "down" and arr.level is not None


def _gen_session_tree_elsewhere(arr, world):
    return arr.whose == "session-tree" and arr.session != "owner"


def _gen_linked_out_standing_there(arr, world):
    return arr.whose == "linked-out" and arr.session == "owner"


def _gen_dangling_holds_nothing(arr, world):
    return arr.folder == "dangling" and arr.present


def _gen_no_destination(arr, world):
    return arr.folder in _GEN_UNLINKED and arr.dest != "owner"


def _gen_project_is_owner(arr, world):
    return _gen_is_project(arr) and arr.dest == "project"


def _gen_plain_once(arr, world):
    return arr.form == "plain" and arr.folder != "real"


def _gen_nested_repo_at_destination(arr):
    """A repository nested under the project that is no tree of this one, its
    config written at its folder's destination from a session standing
    elsewhere: no component of that path hangs off the repository, and only
    the registrations, which do not name it, could."""
    return (arr.whose == "nested-repo" and arr.form == "dest"
            and arr.session != "owner")


# Each family the property names and the module cannot see, with its reason.
_GEN_RESIDUAL = (
    ("nested-repo-at-destination", _gen_nested_repo_at_destination,
     "a nested repository that is no tree of this repository is asked only by "
     "the directory its config's components hang off, and a write at its "
     "folder's destination hangs off none of it"),
)


def _gen_residual(arr):
    """The name of the residual family `arr` falls in, or None."""
    for name, pred, _why in _GEN_RESIDUAL:
        if pred(arr):
            return name
    return None


def _gen_dest_is_link(arr, world):
    return arr.form == "dest" and _gen_link_path(world) == _gen_dest_path(world)


def _gen_level_above_fixture(arr, world):
    return arr.level is not None and arr.level >= len(
        _gen_parts(_gen_raw_path(world, arr), world["base"]))


def _gen_nothing_to_swap(arr, world):
    if arr.level is None or _gen_level_above_fixture(arr, world):
        return False
    parts = _gen_parts(_gen_raw_path(world, arr), world["base"])
    name = parts[len(parts) - 1 - arr.level]
    return name.swapcase() == name


# Every predicate, with the reason it names. Order is the order they are asked.
_GEN_SKIPS = (
    ("no-member-place", _gen_no_member_place,
     "a project at its checkout's top has no member place apart from the "
     "top"),
    ("nested-repo-has-no-member-place", _gen_nested_repo_member,
     "a repository nested under the project is no tree of this one, so it has "
     "no member place; it is asked at its top"),
    ("owner-is-project", _gen_owner_is_project,
     "the project's config standing in its owner is the row standing in the "
     "project"),
    ("session-tree-elsewhere", _gen_session_tree_elsewhere,
     "the session's tree is the tree the session stands in; standing elsewhere "
     "is the linked-out family"),
    ("linked-out-standing-there", _gen_linked_out_standing_there,
     "standing in that worktree makes it the session's tree, a family of its "
     "own"),
    ("dangling-holds-nothing", _gen_dangling_holds_nothing,
     "a folder linked to a place not made yet holds no config"),
    ("no-destination", _gen_no_destination,
     "a folder that is no link lies in its own tree; it has no destination "
     "elsewhere"),
    ("project-is-owner", _gen_project_is_owner,
     "the project's own config folder linked into the project is the 'owner' "
     "row"),
    ("plain-once", _gen_plain_once,
     "the plain folder is the same whatever the tree's config folder is"),
    ("dest-is-link", _gen_dest_is_link,
     "a folder that resolves to its own spelling has no destination apart "
     "from it"),
    ("level-above-fixture", _gen_level_above_fixture,
     "that component lies above the fixture's own directory"),
    ("nothing-to-swap", _gen_nothing_to_swap,
     "the component has no letter whose case can change"),
    ("member-spelled-once", _gen_member_spelled_once,
     "a letter-case variant is a question of the path's spelling, asked the "
     "same below a member's place as at a top; a member world asks where the "
     "tree is opened, spelled as it is"),
)


# The folder kinds that are no link: they lie in their own tree.
_GEN_UNLINKED = ("real", "repo", "git-entry")


def _gen_init(at):
    """A repository initialised at `at`, made here as the fixture's own act."""
    _harness.git(at, "init", "-q", prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)


def _gen_world_of(base, arr):
    """`_gen_world` for the world dimensions of `arr`."""
    return _gen_world(base, *[getattr(arr, n) for n in _GEN_WORLD_DIMS])


def _gen_world(base, whose, folder, dest, present, member="top", place="top"):
    """A repository at `base/proj` - the project there, or for a member
    project at `base/proj/app` - and the tree whose config the family is
    about, at its top or at the member's place in it as `place` says, its
    config folder arranged as `folder` says - a link's destination where
    `dest` says - the config at the folder's destination when `present`.
    -> {"base", "proj" (the project), "top" (its checkout's top), "owner",
    "trees" (every place this builder made that a loader could be handed: the
    project and its checkout's top, each worktree's top and member place,
    each repository it initialised)}"""
    rel = _config.CONFIG_REL.split("/")
    top = os.path.join(base, "proj")
    sub = _GEN_MEMBER if member == "down" else ""
    proj = os.path.join(top, sub) if sub else top
    store = os.path.join(base, "store")
    os.makedirs(os.path.join(proj, "src"))
    os.makedirs(os.path.join(proj, "docs", "audit"))
    os.makedirs(store)
    with open(os.path.join(proj, "src", "x.ts"), "w", encoding="utf-8") as fh:
        fh.write("export const x = 1;\n")
    with open(os.path.join(proj, "docs", "audit", "audit-plan.json"), "w",
              encoding="utf-8") as fh:
        json.dump(_GEN_PLAN, fh)
    for argv in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "c"]):
        _harness.git(top, *argv, prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
    trees = [top, proj] if sub else [proj]
    if whose == "project":
        owner = top
    else:
        os.makedirs(os.path.join(proj, rel[0]))
    if whose in ("session-tree", "linked-out"):
        owner = os.path.join(base, "ext")
        _harness.git(top, "worktree", "add", "-q", owner, "-b", "ext",
                     prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
    elif whose == "nested-worktree":
        owner = os.path.join(proj, rel[0], "worktrees", "w1")
        _harness.git(top, "worktree", "add", "-q", owner, "-b", "w1",
                     prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
    elif whose == "nested-repo":
        # An unrelated repository, reached through a symlinked folder of the
        # project: it lies under the project as written and nowhere as resolved.
        os.makedirs(os.path.join(store, "vendor", "lib"))
        _gen_init(os.path.join(store, "vendor", "lib"))
        os.symlink(os.path.join(store, "vendor"), os.path.join(proj, "vendor"))
        owner = os.path.join(proj, "vendor", "lib")
    if whose in ("session-tree", "linked-out", "nested-worktree"):
        # A worktree checks the member's place out too, and a loader can be
        # handed either.
        trees.append(owner)
        if sub:
            trees.append(os.path.join(owner, sub))
    elif whose == "nested-repo":
        trees.append(owner)
    if place == "member" and sub:
        owner = os.path.join(owner, sub)
    at = os.path.join(owner, rel[0])
    place = {"owner": os.path.join(owner, "config"),
             "project": os.path.join(proj, "shared"),
             "outside": store}[dest]
    target = os.path.join(place, "c-" + folder)
    if folder in _GEN_UNLINKED:
        os.makedirs(at)
        if folder == "repo":
            _gen_init(at)
            trees.append(at)
        elif folder == "git-entry":
            # An empty git entry: no repository, and nothing to decide by.
            open(os.path.join(at, ".git"), "w").close()
    elif folder in ("link", "link-repo"):
        os.makedirs(target)
        if folder == "link-repo":
            # A dotfiles or shared-settings repository the folder links to.
            _gen_init(target)
            trees.append(target)
        os.symlink(target, at)
    elif folder == "chain":
        os.makedirs(target)
        os.symlink(target, os.path.join(base, "hop"))
        os.symlink(os.path.join(base, "hop"), at)
    elif folder == "dangling":
        # Two levels not made yet: a write through it creates them.
        os.symlink(os.path.join(target, "cdir"), at)
    else:
        raise ValueError("no folder kind %r" % (folder,))
    if present and folder != "dangling":
        with open(os.path.join(at, rel[1]), "w", encoding="utf-8") as fh:
            json.dump({_GEN_BODY_KEY: "pre"}, fh)
    # The allow twin's plain folder: an empty git entry in it and another in a
    # directory above it - no repository either way.
    plain = os.path.dirname(os.path.join(owner, "notes", "sub", *rel))
    os.makedirs(plain)
    for stray in (os.path.join(owner, "notes"), plain):
        open(os.path.join(stray, ".git"), "w").close()
    return {"base": base, "proj": proj, "top": top, "owner": owner,
            "trees": trees}


def _gen_link_path(world):
    return os.path.join(world["owner"], *_config.CONFIG_REL.split("/"))


def _gen_dest_path(world):
    rel = _config.CONFIG_REL.split("/")
    return os.path.join(os.path.realpath(os.path.join(world["owner"], rel[0])),
                        rel[1])


def _gen_plain_path(world):
    return os.path.join(world["owner"], "notes", "sub",
                        *_config.CONFIG_REL.split("/"))


def _gen_raw_path(world, arr):
    return {"link": _gen_link_path, "dest": _gen_dest_path,
            "plain": _gen_plain_path}[arr.form](world)


def _gen_parts(path, base):
    """The components of `path` from the fixture's own directory down."""
    return [os.path.basename(base)] + os.path.relpath(path, base).split(os.sep)


def _gen_spell(world, arr):
    """(the path the write names, the session's directory) for `arr`."""
    path = _gen_raw_path(world, arr)
    if arr.level is not None:
        parts = _gen_parts(path, world["base"])
        i = len(parts) - 1 - arr.level
        parts[i] = parts[i].swapcase()
        path = os.path.join(os.path.dirname(world["base"]), *parts)
    cwd = world["proj"] if arr.session == "project" else world["owner"]
    return path, cwd


def _gen_skip(arr, world):
    """The name of the first predicate that rules `arr` out, or None."""
    for name, pred, _why in _GEN_SKIPS:
        if pred(arr, world):
            return name
    return None


def _gen_missing_top(directory):
    """The highest directory on the way to `directory`, resolved, that does not
    exist yet - what a write creating its parents leaves behind - or None."""
    top, d = None, os.path.realpath(directory)
    while not os.path.lexists(d):
        top, d = d, os.path.dirname(d)
    return top


def _gen_reads(world, arr, path, cwd, mark):
    """Make the write, ask the loader of every tree the world's builder made,
    put the world back as it was.
    -> sorted trees (relative to the fixture) whose loader read `mark`."""
    full = path if os.path.isabs(path) else os.path.join(cwd, path)
    existed = os.path.exists(full)
    old = None
    if existed:
        with open(full, "r", encoding="utf-8") as fh:
            old = fh.read()
    created = _gen_missing_top(os.path.dirname(full))
    try:
        made, why = _harness.attempt(_link_write, full,
                                     json.dumps({_GEN_BODY_KEY: mark}) + "\n")
        if not made:
            return ["write not made: %s" % (why,)]
        return sorted(set(os.path.relpath(t, world["base"])
                          for t in world["trees"]
                          if _config.load(t).get(_GEN_BODY_KEY) == mark))
    finally:
        if existed:
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(old)
        elif os.path.lexists(full) and not created:
            os.remove(full)
        if created and os.path.lexists(created):
            _harness.remove_tree(created)


def _gen_decide(world, arr, path, cwd, agent):
    """The guard's verdict in this process, the project named as the host names
    it."""
    cfg = _config._deep_merge(_config.DEFAULTS, {})
    prev = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = world["proj"]
    try:
        return _cf_decide(cfg, arr.tool, _tool_input(arr.tool, path, _CF_BODY),
                          cwd, agent)[0]
    finally:
        if prev is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = prev


def _gen_worlds():
    """The world dimensions' product, in `_GEN_WORLD_DIMS` order."""
    dims = [d.values for d in _GEN_DIMS if d.name in _GEN_WORLD_DIMS]
    return list(itertools.product(*dims))


def _gen_world_ruled_out(key):
    """The skip predicate that rules out every arrangement of the world `key`
    before it is built - so a world no arrangement would run is never made -
    or None. Asked of an arrangement carrying the world's values, with no
    world, so only a predicate that reads no world can answer here."""
    probe = _Arr(*(key + (None,) * (len(_GEN_DIMS) - len(key))))
    for name, pred, _why in _GEN_SKIPS:
        if name in _GEN_WORLD_SKIPS and pred(probe, None):
            return name
    return None


# The predicates that read only the world's own dimensions.
_GEN_WORLD_SKIPS = ("no-member-place", "nested-repo-has-no-member-place",
                    "dangling-holds-nothing", "no-destination",
                    "project-is-owner")


def gen_sweep(base, visit):
    """Build each world once, and for every arrangement of it that no predicate
    rules out call `visit(world, arr, path, cwd)`. -> (records, skipped by
    predicate name, ran by family - keyed (dimension, value) over
    `_GEN_FAMILY_DIMS` - the worlds by their `_GEN_WORLD_DIMS` values).
    `visit` leaves the world as it found it."""
    rest = [d.values for d in _GEN_DIMS if d.name not in _GEN_WORLD_DIMS]
    tails = list(itertools.product(*rest))
    records, skipped = [], dict((s[0], 0) for s in _GEN_SKIPS)
    ran = dict(((d.name, v), 0) for d in _GEN_DIMS
               if d.name in _GEN_FAMILY_DIMS for v in d.values)
    worlds = {}
    for n, key in enumerate(_gen_worlds()):
        why = _gen_world_ruled_out(key)
        if why is not None:
            skipped[why] += len(tails)
            continue
        world = _gen_world(os.path.join(base, "g%d" % n), *key)
        worlds[key] = world
        _config.forget_git_standing()
        for tail in tails:
            arr = _Arr(*(key + tail))
            why = _gen_skip(arr, world)
            if why is not None:
                skipped[why] += 1
                continue
            path, cwd = _gen_spell(world, arr)
            records.append(visit(world, arr, path, cwd))
            for name in _GEN_FAMILY_DIMS:
                ran[(name, getattr(arr, name))] += 1
    return records, skipped, ran, worlds


def _gen_label(arr):
    return "%s/%s/%s/%s%s/%s/%s/%s" % (
        arr.whose, arr.folder, "present" if arr.present else "absent",
        "" if arr.member == "top" else "member-%s-place/" % (arr.place,),
        arr.form,
        "case@%d" % arr.level if arr.level is not None else "plain",
        "in-" + arr.session, "mcp" if arr.tool.startswith("mcp__") else arr.tool)


def _generated_cases(check):
    """cf36, cf36b, cf36c: the property over the generated arrangements."""
    label = ("cf36 over arrangements generated from named dimensions, the hook "
             "holds a write exactly when a loader then reads it")
    base = os.path.realpath(_harness.fixture_root("guard-edits-gen-"))
    probe = os.path.join(base, "probe-link")
    linked, why = _harness.attempt(os.symlink, base, probe)
    if not linked:
        _harness.skip(check, label, "no symlink can be made here (%s)" % (why,),
                      os.name == "nt" or not hasattr(os, "symlink"))
        return
    os.remove(probe)
    started = time.time()

    def visit(world, arr, path, cwd):
        sub = _gen_decide(world, arr, path, cwd, "agent-cf")
        main = _gen_decide(world, arr, path, cwd, None)
        reads = _gen_reads(world, arr, path, cwd, "gen")
        return arr, sub, main, reads

    seen, skipped, ran, worlds = gen_sweep(base, visit)

    def agrees(rec):
        arr, sub, main, reads = rec
        if reads and _gen_residual(arr) is None:
            return sub == "block" and main == "ask"
        return sub == "allow" and main == "allow"
    bad = [(_gen_label(r[0]), r[1], r[2], r[3]) for r in seen if not agrees(r)]
    n_held = sum(1 for r in seen if r[3] and _gen_residual(r[0]) is None)
    residual = dict((name, [0, 0]) for name, _p, _w in _GEN_RESIDUAL)
    for r in seen:
        name = _gen_residual(r[0])
        if name is not None:
            residual[name][0] += 1
            residual[name][1] += 1 if r[3] else 0
    none_ran = sorted("%s=%s" % k for k, n in ran.items() if not n)
    check("cf36 over arrangements generated from named dimensions - %s - the "
          "hook's question holds a write exactly when the loader, asked for "
          "every place the fixture built that a loader could be handed - each "
          "tree's top and, for a member project, each tree's member place - "
          "then reads the written file: ran %d "
          "(%d read by a loader) per family %r, skipped %r, in %.1fs; families "
          "that ran none %r; residual families allowed while read (ran, read) "
          "%r; disagreeing %d: [%s]"
          % (", ".join("%s %d" % (d.name, len(d.values)) for d in _GEN_DIMS),
             len(seen), n_held, sorted(ran.items()), skipped,
             time.time() - started, none_ran, residual, len(bad),
             some_of(bad, render=repr)),
          not bad and not none_ran and 0 < n_held < len(seen)
          and all(read for _n, read in residual.values()))

    # The hook as a process: every measured arrangement, and per family the
    # first arrangement a loader reads and the first none reads.
    picks = list(_GEN_MEASURED)
    for whose in _GEN_DIMS[0].values:
        for member in ("top", "down"):
            for want in (True, False):
                hit = [r for r in seen if r[0].whose == whose
                       and r[0].member == member and bool(r[3]) == want]
                if hit:
                    picks.append(("%s%s-%s" % (
                        whose, "" if member == "top" else "-member",
                        "read" if want else "unread"), hit[0][0]))
    by_arr = dict((r[0], r) for r in seen)
    named = set(n for n, _a in _GEN_MEASURED)
    measured, rep = [], []
    for name, arr in picks:
        world = worlds[tuple(getattr(arr, n) for n in _GEN_WORLD_DIMS)]
        path, cwd = _gen_spell(world, arr)
        proc = tuple(_hook_verdict(world["proj"], cwd, path, _CF_BODY, a,
                                   tool=arr.tool) for a in (True, False))
        rec = by_arr.get(arr)
        inproc = (rec[1], rec[2]) if rec else ("not generated",)
        reads = rec[3] if rec else []
        line = (name, _gen_label(arr), proc, inproc, reads)
        (measured if name in named else rep).append(line)
    check("cf36b the measured arrangements - a linked worktree's config outside "
          "the project, its folder linked out of the repository, written through "
          "the link from the project absent, present and by an MCP tool; the "
          "project's linked-out folder written at its destination with the "
          "directory above it in another case; a nested worktree's and a "
          "nested repository's folder a symlink to a repository; an outside "
          "worktree's folder a symlink to a repository or itself one; an "
          "outside worktree's config written at its link's destination inside "
          "the project and outside it; in a member project, an outside "
          "worktree's member place written directly, its top's linked-out "
          "folder written at the destination and through the link, and the "
          "checkout's top written at its folder's destination - run as the "
          "hook process are held "
          "exactly where a loader reads the write, and each one spelled with no "
          "case variant is read on every volume: %r" % (measured,),
          len(measured) == len(_GEN_MEASURED)
          and all(m[2] == (("block", "ask") if m[4] else ("allow", "allow"))
                  for m in measured)
          and all(m[4] for m, (_n, a) in zip(measured, _GEN_MEASURED)
                  if a.level is None))
    check("cf36c ...and the hook run as a process gives the in-process verdict on "
          "one representative per family and project placement, read and "
          "unread: disagreeing %r of %d, member representatives %d"
          % ([r for r in rep if r[2] != r[3]], len(rep),
             sum(1 for r in rep if "-member-" in r[0])),
          len(rep) >= 2 * len(_GEN_DIMS[0].values)
          and any("-member-" in r[0] for r in rep)
          and all(r[2] == r[3] for r in rep))
    # Read off the worlds the sweep built, not off the constant: the member
    # rows above hold a member path of more than one directory only while
    # every member world puts its project that far below its checkout's top.
    member_worlds = [w for k, w in worlds.items()
                     if k[_GEN_WORLD_DIMS.index("member")] == "down"]
    depths = sorted(set(len(os.path.relpath(w["proj"], w["top"]).split(os.sep))
                        for w in member_worlds))
    deep_held = sum(1 for r in seen if r[0].member == "down" and r[3]
                    and _gen_residual(r[0]) is None)
    check("cf36d ...and every member world the sweep built puts its project "
          "more than one directory below its checkout's top, its worktrees' "
          "member places as deep, with arrangements read by a loader among "
          "them (worlds %d, depths %r, member arrangements held %d)"
          % (len(member_worlds), depths, deep_held),
          bool(member_worlds) and min(depths) >= 2 and deep_held > 0)


# --- cf: what an ordinary write starts, from each place a session stands ---------
# Counted at the process boundary: a `git` first on PATH that appends a line per
# call to a log and runs the real one. The ceiling is what the tree before the
# hold followed the loader started for the same write, measured there with this
# shim and pinned here, beside what the placement of the path alone starts - the
# only part of the guard that ran git then.
_PROC_CEILING = (
    ("in-project", 0), ("in-project-new", 0), ("in-nested", 0),
    ("in-linked", 2), ("in-linked-new", 2), ("linked-on-project", 0),
)


def _proc_world(base):
    proj = os.path.join(base, "proj")
    os.makedirs(os.path.join(proj, "src"))
    with open(os.path.join(proj, "src", "x.ts"), "w", encoding="utf-8") as fh:
        fh.write("export const x = 1;\n")
    for argv in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "c"]):
        _harness.git(proj, *argv, prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
    os.makedirs(os.path.join(proj, ".claude"))
    ext = os.path.join(base, "ext")
    nested = os.path.join(proj, ".claude", "worktrees", "w0")
    for at, branch in ((ext, "ext"), (nested, "w0")):
        _harness.git(proj, "worktree", "add", "-q", at, "-b", branch,
                     prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
    return proj, ext, nested


def _proc_shim(base, real):
    shim = os.path.join(base, "shim")
    os.makedirs(shim)
    with open(os.path.join(shim, "git"), "w", encoding="utf-8") as fh:
        fh.write('#!/bin/sh\nprintf \'%%s\\n\' "$*" >> "$CF_GIT_LOG"\n'
                 'exec "%s" "$@"\n' % (real,))
    os.chmod(os.path.join(shim, "git"), 0o755)
    return shim


def _proc_count(log, run):
    if os.path.exists(log):
        os.remove(log)
    out = run()
    if not os.path.exists(log):
        return out, 0
    with open(log, "r", encoding="utf-8") as fh:
        return out, sum(1 for _ in fh)


def _placement_run(proj, cwd, tool, path, env):
    """`_config.tree_for` alone for the same payload, as a process."""
    import subprocess
    code = ("import json,sys;sys.path.insert(0,%r);import _config;"
            "d=json.loads(sys.stdin.read());"
            "_config.tree_for(d,%r,_config.load(%r))"
            % (_harness.HOOKS_DIR, path, proj))
    data = {"tool_name": tool, "cwd": cwd,
            "tool_input": _tool_input(tool, path, "x\n")}
    return subprocess.run([sys.executable, "-B", "-c", code],
                          input=json.dumps(data).encode("utf-8"),
                          capture_output=True, env=env, cwd=proj, timeout=60)


def _process_count_cases(check):
    """cf37, cf37b: an ordinary write's processes and listings."""
    label = ("cf37 an ordinary write starts no more git processes than before "
             "the hold followed the loader")
    real = shutil.which("git")
    if os.name == "nt" or real is None or not os.path.exists("/bin/sh"):
        _harness.skip(check, label, "no POSIX shell to stand a git shim on PATH",
                      os.name == "nt" or not os.path.exists("/bin/sh"))
        return
    base = os.path.realpath(_harness.fixture_root("guard-edits-proc-"))
    proj, ext, nested = _proc_world(base)
    shim = _proc_shim(base, real)
    log = os.path.join(base, "git.log")
    rows = (("in-project", proj, "Edit", os.path.join(proj, "src", "x.ts")),
            ("in-project-new", proj, "Write",
             os.path.join(proj, "src", "new.ts")),
            ("in-nested", nested, "Edit", os.path.join(nested, "src", "x.ts")),
            ("in-linked", ext, "Edit", os.path.join(ext, "src", "x.ts")),
            ("in-linked-new", ext, "Write", os.path.join(ext, "src", "new.ts")),
            ("linked-on-project", ext, "Edit",
             os.path.join(proj, "src", "x.ts")))
    ceiling = dict(_PROC_CEILING)
    extra = {"PATH": shim + os.pathsep + os.environ.get("PATH", ""),
             "CF_GIT_LOG": log}
    env = dict((k, v) for k, v in os.environ.items()
               if not k.startswith("CLAUDE") and k != _DRIVE_MARK)
    env.update(extra)
    env["CLAUDE_PROJECT_DIR"] = proj
    counts, listed = [], []
    for name, cwd, tool, path in rows:
        hook = [_proc_count(log, lambda: _hook_verdict(
            proj, cwd, path, "x\n", True, tool=tool, env_extra=extra))
            for _ in range(2)]
        place = _proc_count(log, lambda: _placement_run(proj, cwd, tool, path,
                                                        env))
        counts.append((name, hook[0][0], max(h[1] for h in hook), place[1],
                       ceiling[name]))
        verdict, by = _disk_calls(lambda: _gen_decide(
            {"proj": proj}, _gen_at("project", "real", "owner", False, "link",
                                    None, "project", tool), path, cwd,
            "agent-cf"))
        listed.append((name, verdict, sum(by.get(n, 0) for n in _LISTINGS)))
    check("cf37 an ordinary write - an existing and a new source file - with the "
          "session standing in the project, in a nested worktree and in a linked "
          "worktree outside it starts no more git processes per hook run than "
          "the tree before the hold followed the loader (pinned, measured there "
          "by this shim) and none beyond what placing the path starts (row, "
          "verdict, hook, placement, ceiling): %r" % (counts,),
          len(counts) == len(_PROC_CEILING)
          and all(v == "allow" and h <= c and h <= p
                  for _n, v, h, p, c in counts))
    check("cf37b ...and the guard's question lists no directory for any of them "
          "(row, verdict, listings): %r" % (listed,),
          len(listed) == len(_PROC_CEILING)
          and all(v == "allow" and n == 0 for _r, v, n in listed))


# --- cf: the registrations a config-named write reads, and nothing else does ------
# Every worktree the repository registers is asked about a write that could be a
# config, and only about such a write: an ordinary one must not pay for it. So the
# config question is counted here three ways - the registration files it opens
# (`<common>/worktrees/<name>/gitdir`), the directories it lists, and the
# processes it starts - for ordinary writes from each place a session stands and
# for config-named ones. The placement (`tree_for`) runs outside the count: what
# it starts is `cf37`'s. A registration left behind by a removed worktree, one that
# is a directory, one that is a pipe and a worktree whose common-directory file is
# a pipe are then put in the repository, and the hook, run as a process under a
# deadline, must give every verdict it gives without them and raise nothing.
_REG_TIMEOUT = 15


def _reg_world(base):
    """A project with a nested and an outside linked worktree - the outside
    one's config folder a link to a directory outside every tree - a stale
    registration (its worktree's directory removed) and a registration that is
    a directory. -> (proj, ext, nested, common directory)"""
    proj = os.path.join(base, "proj")
    os.makedirs(os.path.join(proj, "src"))
    with open(os.path.join(proj, "src", "x.ts"), "w", encoding="utf-8") as fh:
        fh.write("export const x = 1;\n")
    for argv in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "c"]):
        _harness.git(proj, *argv, prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
    os.makedirs(os.path.join(proj, ".claude"))
    ext = os.path.join(base, "ext")
    nested = os.path.join(proj, ".claude", "worktrees", "w0")
    gone = os.path.join(base, "gone")
    for at, branch in ((ext, "ext"), (nested, "w0"), (gone, "gone")):
        _harness.git(proj, "worktree", "add", "-q", at, "-b", branch,
                     prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
    _harness.remove_tree(gone)
    os.makedirs(os.path.join(base, "store", "ecfg"))
    os.symlink(os.path.join(base, "store", "ecfg"), os.path.join(ext, ".claude"))
    common = os.path.join(proj, ".git")
    os.makedirs(os.path.join(common, "worktrees", "as-dir", "gitdir"))
    return proj, ext, nested, common


def _reg_counted(fn, common):
    """(fn(), registration files opened, directories listed, processes
    started) while `fn` runs."""
    import builtins
    import subprocess
    regs = os.path.join(os.path.realpath(common), "worktrees") + os.sep
    opened, listed, started = [], [], []
    real = (builtins.open, os.listdir, os.scandir, subprocess.Popen)

    def counting_open(file, *a, **k):
        name = os.fspath(file) if isinstance(file, (str, bytes)) or hasattr(
            file, "__fspath__") else None
        if (isinstance(name, str) and os.path.basename(name) == "gitdir"
                and os.path.realpath(name).startswith(regs)):
            opened.append(name)
        return real[0](file, *a, **k)

    def counting_listdir(*a, **k):
        listed.append(a[0] if a else ".")
        return real[1](*a, **k)

    def counting_scandir(*a, **k):
        listed.append(a[0] if a else ".")
        return real[2](*a, **k)

    class CountingPopen(real[3]):
        def __init__(self, *a, **k):
            started.append(a[0] if a else k.get("args"))
            super().__init__(*a, **k)
    builtins.open, os.listdir, os.scandir = (counting_open, counting_listdir,
                                             counting_scandir)
    subprocess.Popen = CountingPopen
    try:
        out = fn()
    finally:
        builtins.open, os.listdir, os.scandir, subprocess.Popen = real
    return out, opened, listed, started


def _reg_question(cfg, path, cwd):
    """The config question for a subagent's Write of `path` from `cwd`, the
    placement made first and outside whatever counts the question."""
    data = {"tool_name": "Write", "cwd": cwd, "agent_id": "agent-cf",
            "tool_input": {"file_path": path, "content": "x\n"}}
    tree = _config.tree_for(data, path, cfg)
    ask = getattr(_config, "config_question", None)
    return lambda: _config_way(ask(tree, path, data) if ask else tree)


def _registration_cases(check):
    """cf38, cf38b, cf38c: what the registrations cost and what a broken one
    changes."""
    label = ("cf38 an ordinary write reads no registration, lists no directory "
             "and starts no process")
    base = os.path.realpath(_harness.fixture_root("guard-edits-reg-"))
    built, world = _harness.attempt(_reg_world, base)
    if not built:
        check("%s: the fixture builds (%s)" % (label, world), False)
        return
    proj, ext, nested, common = world
    rel = _config.CONFIG_REL.split("/")
    cfg = _config._deep_merge(_config.DEFAULTS, {})
    prev = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = proj
    try:
        _config.forget_git_standing()
        ordinary, named = [], []
        for name, cwd, path in (
                ("in-project", proj, os.path.join(proj, "src", "x.ts")),
                ("in-project-new", proj, os.path.join(proj, "src", "n.ts")),
                ("in-nested", nested, os.path.join(nested, "src", "x.ts")),
                ("in-linked", ext, os.path.join(ext, "src", "x.ts")),
                ("in-linked-new", ext, os.path.join(ext, "src", "n.ts")),
                ("linked-on-project", ext, os.path.join(proj, "src", "x.ts"))):
            way, opened, listed, started = _reg_counted(
                _reg_question(cfg, path, cwd), common)
            ordinary.append((name, way, len(opened), len(listed), len(started)))
        # Config-named writes no tree asked without the registrations answers:
        # one no tree loads, and the outside worktree's config written at its
        # folder's destination, which only that worktree loads.
        for name, cwd, path, want in (
                ("plain-folder", proj,
                 os.path.join(proj, "docs", "sample", *rel), False),
                ("outside-destination", proj,
                 os.path.join(base, "store", "ecfg", rel[1]), True)):
            way, opened, listed, started = _reg_counted(
                _reg_question(cfg, path, cwd), common)
            named.append((name, bool(way) == want, len(opened),
                          [os.path.relpath(os.path.realpath(d), base)
                           for d in listed], len(started)))
    finally:
        if prev is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = prev
    check("cf38 an ordinary write - an existing and a new source file - with the "
          "session standing in the project, in a nested worktree and in a "
          "linked worktree outside it makes the config question read no "
          "registration, list no directory and start no process (row, answer, "
          "registrations read, listings, processes): %r" % (ordinary,),
          len(ordinary) == 6
          and all(not w and o == 0 and n == 0 and p == 0
                  for _r, w, o, n, p in ordinary))
    worktrees = os.path.relpath(os.path.join(common, "worktrees"), base)
    check("cf38b ...while a config-named write no tree asked without them "
          "answers reads the registrations - the repository's worktrees listed "
          "and each registration that is a file opened - and still starts no "
          "process, a stale registration and one that is a directory among "
          "them: a file no tree loads allowed, the outside worktree's config "
          "at its folder's destination held (row, answer right, registrations "
          "read, listed, processes): %r" % (named,),
          len(named) == 2
          and all(ok and o >= 3 and worktrees in ls and p == 0
                  for _r, ok, o, ls, p in named))
    _malformed_registration_cases(check, base, proj, ext, common, rel)
    _main_tree_cases(check, os.path.join(base, "main-tree"), rel, cfg)


def _main_tree_cases(check, base, rel, cfg):
    """cf38d: the project itself a linked worktree, so the repository's main
    tree is another tree, found only as the directory holding the common git
    directory. The main checkout's and a sibling worktree's `.claude` each a
    link to a directory outside every tree, each config written at that
    destination from a session standing in the project."""
    main = os.path.join(base, "main")
    os.makedirs(os.path.join(main, "src"))
    with open(os.path.join(main, "src", "x.ts"), "w", encoding="utf-8") as fh:
        fh.write("export const x = 1;\n")
    for argv in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "c"]):
        _harness.git(main, *argv, prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
    proj, side = os.path.join(base, "proj"), os.path.join(base, "side")
    for at, branch in ((proj, "proj"), (side, "side")):
        _harness.git(main, "worktree", "add", "-q", at, "-b", branch,
                     prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
    for tree, store in ((main, "mcfg"), (side, "scfg")):
        os.makedirs(os.path.join(base, "store", store))
        os.symlink(os.path.join(base, "store", store),
                   os.path.join(tree, rel[0]))
    os.makedirs(os.path.join(base, "store", "plain"))
    prev = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = proj
    try:
        _config.forget_git_standing()
        seen = [(name, _cf_decide(cfg, "Write", {
            "file_path": os.path.join(base, "store", store, rel[1]),
            "content": _CF_BODY}, proj, "agent-cf")[0], want)
            for name, store, want in (("main-destination", "mcfg", "block"),
                                      ("sibling-destination", "scfg", "block"),
                                      ("no-tree's-folder", "plain", "allow"))]
    finally:
        if prev is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = prev
    check("cf38d with the project itself a linked worktree, the main checkout's "
          "config and a sibling worktree's, each written at its linked-out "
          "folder's destination from a session in the project, are refused to "
          "a subagent - the main tree found beside the common directory, the "
          "sibling in its registration - while a config-named file in a folder "
          "no tree links to is allowed (row, got, want): %r" % (seen,),
          len(seen) == 3 and all(g == w for _n, g, w in seen))


def _malformed_registration_cases(check, base, proj, ext, common, rel):
    """cf38c: a registration that is a pipe, and a worktree whose common-directory
    file is a pipe, beside the stale one and the directory: each verdict stands,
    nothing is raised, nothing waits on a pipe."""
    label = ("cf38c a registration or a common-directory file that is no regular "
             "file changes no verdict")
    if not hasattr(os, "mkfifo"):
        _harness.skip(check, label, "no named pipe can be made here",
                      os.name == "nt")
        return
    odd = os.path.join(base, "odd")
    _harness.git(proj, "worktree", "add", "-q", odd, "-b", "odd",
                 prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
    os.makedirs(os.path.join(common, "worktrees", "as-pipe"))
    os.mkfifo(os.path.join(common, "worktrees", "as-pipe", "gitdir"))
    pointer = os.path.join(common, "worktrees", "odd", "commondir")
    os.remove(pointer)
    os.mkfifo(pointer)
    import subprocess
    seen = []
    for name, cwd, path, want in (
            ("project-config", proj, os.path.join(proj, *rel), "block"),
            ("outside-config", proj, os.path.join(ext, *rel), "block"),
            ("source", proj, os.path.join(proj, "src", "x.ts"), "allow"),
            ("plain-folder", proj, os.path.join(proj, "docs", "s", *rel),
             "allow"),
            ("stale-config", proj, os.path.join(base, "gone", *rel), "allow"),
            ("odd-source", odd, os.path.join(odd, "src", "x.ts"), "allow"),
            ("odd-on-project", odd, os.path.join(proj, *rel), "block")):
        try:
            got = _hook_verdict(proj, cwd, path, _CF_BODY, True,
                                timeout=_REG_TIMEOUT)
        except subprocess.TimeoutExpired:
            got = "no answer within %ds" % (_REG_TIMEOUT,)
        seen.append((name, got, want))
    check("cf38c a registration that is a pipe, one that is a directory, one "
          "whose worktree is gone, and a worktree whose common-directory file "
          "is a pipe leave every verdict standing - the hook run as a process "
          "answers each within %ds and raises nothing (row, got, want): %r"
          % (_REG_TIMEOUT, seen),
          len(seen) == 7 and all(g == w for _n, g, w in seen))


# --- cf: a project that is a directory below its checkout's top --------------------
# A member project: the session's project is `R/a/b` while the repository's git
# entry is at `R`. A loader can be handed the checkout's top `R`, the project, a
# registered worktree's top `W`, and the member's own place in it `W/a/b`; a plain
# repository with no linked worktree has `P` and `P/app` alone. The member path is
# two directories in the first and one in the second, because a member path cut
# to its last component, or a walk that stops one directory above the project,
# still answers right at one directory. Each row is the hook run as a process for
# a subagent and for the main session, the write then made, and the loader asked
# for every one of those places - listed by the builder, never found by a walk -
# so the oracle shares nothing with the module.
_MEMBER_DEEP = os.path.join("a", "b")
_MEMBER_SHALLOW = "app"


def _member_repo(top, branch_dir, member):
    """A repository at `top` whose tracked files lie under `top/<member>`,
    committed so a worktree of it checks `member` out too."""
    os.makedirs(os.path.join(top, member, "src"))
    with open(os.path.join(top, member, "src", "x.ts"), "w",
              encoding="utf-8") as fh:
        fh.write("export const x = 1;\n")
    for argv in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "c"]):
        _harness.git(top, *argv, prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
    if branch_dir:
        _harness.git(top, "worktree", "add", "-q", branch_dir, "-b", "w",
                     prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)


def _member_world(base):
    """R with the project R/a/b and a worktree W outside it; P a plain member
    repository, P/app its project, no linked worktree. R's, W's and P's config
    folders are links to directories outside every tree; W/a/b's is a real
    folder. -> {"base", "proj", "place", "pproj", "trees" (every place a loader
    could be handed), ...}"""
    rel = _config.CONFIG_REL.split("/")
    top, wt, plain = (os.path.join(base, n) for n in ("R", "W", "P"))
    _member_repo(top, wt, _MEMBER_DEEP)
    _member_repo(plain, None, _MEMBER_SHALLOW)
    store = os.path.join(base, "store")
    for tree, name in ((top, "rcfg"), (wt, "wcfg"), (plain, "pcfg")):
        os.makedirs(os.path.join(store, name))
        os.symlink(os.path.join(store, name), os.path.join(tree, rel[0]))
    proj, place = (os.path.join(t, _MEMBER_DEEP) for t in (top, wt))
    pproj = os.path.join(plain, _MEMBER_SHALLOW)
    os.makedirs(os.path.join(place, rel[0]))
    os.makedirs(os.path.join(wt, "notes"))
    return {"base": base, "top": top, "wt": wt, "plain": plain,
            "store": store, "proj": proj, "place": place, "pproj": pproj,
            "trees": [top, proj, wt, place, plain, pproj]}


def _member_rows(world):
    """(name, project, cwd, path, held) for every row the member cases run."""
    rel = _config.CONFIG_REL.split("/")
    top, wt, plain, store = (world[k] for k in ("top", "wt", "plain", "store"))
    proj, place, pproj = (world[k] for k in ("proj", "place", "pproj"))
    return (
        ("wt-member-place", proj, proj, os.path.join(place, *rel), True),
        ("wt-top-at-destination", proj, proj,
         os.path.join(store, "wcfg", rel[1]), True),
        ("wt-top-through-link", proj, proj, os.path.join(wt, *rel), True),
        ("top-at-destination", proj, proj, os.path.join(store, "rcfg", rel[1]),
         True),
        ("plain-top-at-destination", pproj, pproj,
         os.path.join(store, "pcfg", rel[1]), True),
        ("plain-top-through-link", pproj, pproj, os.path.join(plain, *rel),
         True),
        # The allow twins: ordinary writes in the member project and in its
        # worktree; a config-named file in a folder of the worktree that is no
        # place a loader is handed (red when every subdirectory of a
        # registered tree is asked); one in the directory the walk passes
        # between the project and its checkout (red when every directory the
        # walk passes is asked as a tree); one in the directory above the
        # checkout (red when every directory above the project is asked).
        ("ordinary-in-project", proj, proj, os.path.join(proj, "src", "x.ts"),
         False),
        ("ordinary-in-worktree", proj, place,
         os.path.join(place, "src", "x.ts"), False),
        ("worktree-folder-no-place", proj, proj,
         os.path.join(wt, "notes", *rel), False),
        ("between-project-and-checkout", proj, proj,
         os.path.join(os.path.dirname(proj), *rel), False),
        ("above-the-checkout", proj, proj,
         os.path.join(world["base"], *rel), False),
    )


def _member_cases(check):
    """cf39, cf39b, cf39c: the member project's trees, as processes."""
    label = ("cf39 a member project's config-named writes are held where a "
             "loader reads them")
    base = os.path.realpath(_harness.fixture_root("guard-edits-member-"))
    probe = os.path.join(base, "probe-link")
    linked, why = _harness.attempt(os.symlink, base, probe)
    if not linked:
        _harness.skip(check, label, "no symlink can be made here (%s)" % (why,),
                      os.name == "nt" or not hasattr(os, "symlink"))
        return
    os.remove(probe)
    built, world = _harness.attempt(_member_world, base)
    if not built:
        check("%s: the fixture builds (%s)" % (label, world), False)
        return
    seen = []
    for name, proj, cwd, path, held in _member_rows(world):
        sub = _hook_verdict(proj, cwd, path, _CF_BODY, True)
        main = _hook_verdict(proj, cwd, path, _CF_BODY, False)
        reads = (_gen_reads(world, None, path, cwd, name)
                 if os.path.basename(path) == os.path.basename(
                     _config.CONFIG_REL) else [])
        seen.append((name, (sub, main), reads, held))
    deny = [s for s in seen if s[3]]
    allow = [s for s in seen if not s[3]]
    check("cf39 in a member project - the project R/a/b two directories below "
          "its checkout's top R, a registered worktree W, and a plain member "
          "repository P/app one directory down with no linked worktree - a "
          "config-named write that the checkout's "
          "top, the worktree's top or the member's place in the worktree "
          "would load, written through a linked-out folder, at its "
          "destination or directly, is refused to a subagent and asked of the "
          "main session, the hook run as a process, each one read by a "
          "loader of a place the builder listed (row, (sub, main), read by): "
          "%r" % (deny,),
          len(deny) == 6
          and all(v == ("block", "ask") and r for _n, v, r, _h in deny))
    check("cf39b ...while its allow twins stay quiet - an ordinary write in the "
          "member project and in its worktree's member place, a config-named "
          "file in a worktree folder that is no place a loader is handed, one "
          "in the directory between the project and its checkout, and one in "
          "the directory above the checkout - none read by a loader "
          "(row, (sub, main), read by): %r" % (allow,),
          len(allow) == 5
          and all(v == ("allow", "allow") and not r for _n, v, r, _h in allow))
    # The depth is the fixture's, read off what it built: the rows above hold
    # a member path of more than one directory only while the world has one.
    depths = sorted(len(os.path.relpath(world[p], world[t]).split(os.sep))
                    for p, t in (("proj", "top"), ("place", "wt"),
                                 ("pproj", "plain")))
    held_deep = [s[0] for s in deny if s[0].startswith(("wt-", "top-"))]
    check("cf39e ...and the member path those rows hold is two directories "
          "deep below the checkout's top and below the worktree's - the "
          "worktree's member place and its top, the checkout's top - with one "
          "plain repository one directory deep (member depths built %r, deep "
          "rows held %r)" % (depths, held_deep),
          depths == [1, 2, 2] and len(held_deep) == 4
          and all(v == ("block", "ask") and r for n, v, r, _h in deny
                  if n in held_deep))
    _member_cost_case(check, world)
    _member_hard_link_case(check, world)


def _member_hard_link_case(check, world):
    """cf39d: what a member project does not match, run so the documents can
    say so. The tree a session stands in is asked of every write, found by a
    walk from the session's directory that compares the repository it meets
    with the project's own git entry; a member project has none, so a session
    standing in a worktree's member place has no tree of its own asked, and a
    hard link under a name that is not the config's, placed in the project, to
    that place's existing config is not matched - the registrations are read
    for a config-named write alone, and an ordinary write walks to no
    checkout."""
    rel = _config.CONFIG_REL.split("/")
    proj, place = world["proj"], world["place"]
    conf = os.path.join(place, *rel)
    link = os.path.join(proj, "notes", "hl.json")
    os.makedirs(os.path.dirname(link))
    with open(conf, "w", encoding="utf-8") as fh:
        json.dump({_GEN_BODY_KEY: "pre"}, fh)
    made, why = _harness.attempt(os.link, conf, link)
    if not made:
        _harness.skip(check, "cf39d a hard link to a member place's config",
                      "no hard link can be made here (%s)" % (why,),
                      not hasattr(os, "link"))
        return
    try:
        got = tuple(_hook_verdict(proj, place, link, _CF_BODY, a)
                    for a in (True, False))
        reads = _gen_reads(world, None, link, place, "cf39d")
    finally:
        os.remove(link)
        os.remove(conf)
    check("cf39d NOT MATCHED, run so the documents can say it: in a member "
          "project, a hard link placed in the project under a name that is not "
          "the config's, to the existing config of a worktree's member place, "
          "written from a session standing in that place - its tree is not "
          "found for a member project, and identity is asked only of the trees "
          "asked of every write - is allowed while that place's loader reads "
          "it ((sub, main), read by): %r, %r" % (got, reads),
          got == ("allow", "allow")
          and reads == [os.path.relpath(place, world["base"])])


def _member_cost_case(check, world):
    """cf39c: an ordinary write in a member project, in process."""
    cfg = _config._deep_merge(_config.DEFAULTS, {})
    proj = world["proj"]
    common = os.path.join(world["top"], ".git")
    # The git entries a walk from the project up to its checkout would ask
    # about beyond the project's own, which the session's tree is compared
    # with: those of the directories above it. A session standing in a
    # worktree has its own tree found by a walk from there, which an ordinary
    # write made before this rule too.
    walk, at = set(), os.path.dirname(proj)
    while os.path.dirname(at) != at:
        walk.add(os.path.join(at, ".git"))
        at = os.path.dirname(at)
    prev = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = proj
    rows = []
    try:
        _config.forget_git_standing()
        for name, cwd, path in (
                ("in-project", proj, os.path.join(proj, "src", "x.ts")),
                ("in-project-new", proj, os.path.join(proj, "src", "n.ts")),
                ("in-worktree", world["place"],
                 os.path.join(world["place"], "src", "x.ts"))):
            question = _reg_question(cfg, path, cwd)
            (way, touched), opened, listed, started = _reg_counted(
                lambda: _git_entries_touched(question), common)
            rows.append((name, way, len(opened), len(listed), len(started),
                         [t for t in touched if t in walk]))
    finally:
        if prev is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = prev
    check("cf39c ...and an ordinary write there - an existing and a new source "
          "file in the member project, one in its worktree's member place - "
          "makes the config question read no registration, list no directory, "
          "start no process and ask the disk about no git entry above the "
          "project - no walk to its checkout (row, answer, registrations read, "
          "listings, processes, git entries on that walk asked of): %r"
          % (rows,),
          len(rows) == 3
          and all(not w and o == 0 and n == 0 and p == 0 and not t
                  for _r, w, o, n, p, t in rows))


def _git_entries_touched(fn):
    """(fn(), every path whose last component is `.git` that a counted disk
    call was handed while `fn` ran) - the walk to the checkout's git entry,
    seen by what it asks rather than by its name."""
    touched = []
    saved = [(owner, name, getattr(_owner(owner), name))
             for owner, name in _DISK_CALLS if hasattr(_owner(owner), name)]

    def recording(real):
        def call(*a, **k):
            if a and isinstance(a[0], str) and os.path.basename(
                    a[0].rstrip("/\\")) == ".git":
                touched.append(a[0])
            return real(*a, **k)
        return call
    for owner, name, real in saved:
        setattr(_owner(owner), name, recording(real))
    try:
        out = fn()
    finally:
        for owner, name, real in saved:
            setattr(_owner(owner), name, real)
    return out, touched


# --- cf: a registration git wrote relative, and one cut at the bound ----------------
# `git worktree add` writes the registration relative to its own directory under
# `worktree.useRelativePaths` (git 2.48 on). Where the installed git does not, the
# registration file is rewritten relative by hand after an ordinary add - the
# plugin reads that file and nothing else of git's, and the loader oracle needs no
# git - and the label says which was done, so an older git runs the same row and
# never skips it.
def _relative_registration(base):
    """A project with a worktree W registered relative, W's config folder a link
    out of every tree. -> (proj, wt, store, how the registration was made)"""
    proj, wt = os.path.join(base, "proj"), os.path.join(base, "W")
    os.makedirs(os.path.join(proj, "src"))
    with open(os.path.join(proj, "src", "x.ts"), "w", encoding="utf-8") as fh:
        fh.write("export const x = 1;\n")
    for argv in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "c"]):
        _harness.git(proj, *argv, prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
    _harness.git(proj, "-c", "worktree.useRelativePaths=true", "worktree",
                 "add", "-q", wt, "-b", "w", prefix=_harness.WORKTREE_PAIR_GIT,
                 timeout=30)
    reg = os.path.join(proj, ".git", "worktrees", "W", "gitdir")
    with open(reg, "r", encoding="utf-8") as fh:
        written = fh.readline().strip()
    how = "by git"
    if os.path.isabs(written):
        with open(reg, "w", encoding="utf-8") as fh:
            fh.write(os.path.relpath(os.path.join(wt, ".git"),
                                     os.path.dirname(reg)) + "\n")
        how = "by hand, this git wrote it absolute"
    store = os.path.join(base, "store", "wcfg")
    os.makedirs(store)
    os.symlink(store, os.path.join(wt, _config.CONFIG_REL.split("/")[0]))
    return proj, wt, store, how


def _relative_registration_cases(check):
    """cf40, cf40b: a relative registration held; a cut pointer asks no tree."""
    label = "cf40 a worktree registered relative is held"
    base = os.path.realpath(_harness.fixture_root("guard-edits-relreg-"))
    probe = os.path.join(base, "probe-link")
    linked, why = _harness.attempt(os.symlink, base, probe)
    if not linked:
        _harness.skip(check, label, "no symlink can be made here (%s)" % (why,),
                      os.name == "nt" or not hasattr(os, "symlink"))
        return
    os.remove(probe)
    built, made = _harness.attempt(_relative_registration, base)
    if not built:
        check("%s: the fixture builds (%s)" % (label, made), False)
        return
    proj, wt, store, how = made
    rel = _config.CONFIG_REL.split("/")
    reg = os.path.join(proj, ".git", "worktrees", "W", "gitdir")
    with open(reg, "r", encoding="utf-8") as fh:
        pointer = fh.readline().strip()
    world = {"base": base, "trees": [proj, wt]}
    seen = []
    for name, path, held in (
            ("at-destination", os.path.join(store, rel[1]), True),
            ("through-link", os.path.join(wt, *rel), True),
            ("store-beside", os.path.join(base, "store", "x", rel[1]),
             False)):
        verdicts = tuple(_hook_verdict(proj, proj, path, _CF_BODY, a)
                         for a in (True, False))
        seen.append((name, verdicts, _gen_reads(world, None, path, proj, name),
                     held))
    check("cf40 a worktree whose registration is written relative (%s: %r) - "
          "its config folder a link out of every tree - has its config, at the "
          "folder's destination and through the link, refused to a subagent "
          "and asked of the main session, each read by its loader, while a "
          "config-named file beside that destination is allowed and read by "
          "none (row, (sub, main), read by, held): %r" % (how, pointer, seen),
          not os.path.isabs(pointer) and len(seen) == 3
          and all(v == (("block", "ask") if h else ("allow", "allow"))
                  and bool(r) == h for _n, v, r, h in seen))
    _cut_pointer_case(check, base, proj, store, rel)
    _gone_registration_case(check, base, proj, rel)
    _separate_git_dir_case(check, os.path.join(base, "sep"), rel)


def _gone_registration_case(check, base, proj, rel):
    """cf40c: a worktree under the project whose registration is gone is held
    by the reading of a repository nested under the project - its `.git` file
    still stands - while one outside the project is not matched (`ln42`)."""
    gone = os.path.join(proj, rel[0], "worktrees", "gone")
    _harness.git(proj, "worktree", "add", "-q", gone, "-b", "gone",
                 prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
    _harness.remove_tree(os.path.join(proj, ".git", "worktrees", "gone"))
    os.makedirs(os.path.join(gone, rel[0]))
    path = os.path.join(gone, *rel)
    got = tuple(_hook_verdict(proj, proj, path, _CF_BODY, a)
                for a in (True, False))
    reads = _gen_reads({"base": base, "trees": [proj, gone]}, None, path, proj,
                       "cf40c")
    check("cf40c a worktree under the project whose registration is gone - its "
          "admin directory removed, its .git file left - has its config refused "
          "to a subagent and asked of the main session, held as a repository "
          "nested under the project, and read by its loader ((sub, main), read "
          "by): %r, %r" % (got, reads),
          got == ("block", "ask")
          and reads == [os.path.relpath(gone, base)])


def _separate_git_dir_case(check, base, rel):
    """cf40d: what is not matched, run so the documents can say it. A
    repository made with its git directory apart from its checkout keeps its
    common directory under a name that is not `.git`, so the directory beside
    it is no main tree, and the main checkout is found by nothing the
    question reads from a project that is a linked worktree of it."""
    main, project = os.path.join(base, "M"), os.path.join(base, "P")
    os.makedirs(os.path.join(main, "src"))
    with open(os.path.join(main, "src", "x.ts"), "w", encoding="utf-8") as fh:
        fh.write("export const x = 1;\n")
    _harness.git(base, "init", "-q", "--separate-git-dir",
                 os.path.join(base, "G.git"), main,
                 prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
    for argv in (["add", "-A"], ["commit", "-qm", "c"],
                 ["worktree", "add", "-q", project, "-b", "p"]):
        _harness.git(main, *argv, prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
    store = os.path.join(base, "store", "mcfg")
    os.makedirs(store)
    os.symlink(store, os.path.join(main, rel[0]))
    path = os.path.join(store, rel[1])
    got = tuple(_hook_verdict(project, project, path, _CF_BODY, a)
                for a in (True, False))
    reads = _gen_reads({"base": base, "trees": [project, main]}, None, path,
                       project, "cf40d")
    check("cf40d NOT MATCHED, run so the documents can say it: with the git "
          "directory made apart from the checkout and the project a linked "
          "worktree of it, the main checkout's config, written at its "
          "linked-out folder's destination, is allowed while the main "
          "checkout's loader reads it ((sub, main), read by): %r, %r"
          % (got, reads),
          got == ("allow", "allow") and reads == ["M"])


def _cut_pointer_case(check, base, proj, store, rel):
    """cf40b: a registration longer than the bound asks no tree. A
    config-named file no tree loads is the write asked about, so every
    candidate tree is asked before the answer; the registration's name sorts
    before every other, so it is read first."""
    cfg = _config._deep_merge(_config.DEFAULTS, {})
    held = os.path.join(store, rel[1])
    loose = os.path.join(base, "store", "x", rel[1])
    prev = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = proj

    def asked_trees():
        asked = []
        real = _config._names_audit_config

        def recording(target, tree, *a, **k):
            asked.append(tree)
            return real(target, tree, *a, **k)

        def verdict(path):
            return _with_attr("_names_audit_config", recording,
                              lambda: _cf_decide(cfg, "Write", {
                                  "file_path": path, "content": _CF_BODY},
                                  proj, "agent-cf")[0], on=_config)
        got = (verdict(held), verdict(loose))
        return got, sorted(set(os.path.relpath(t, base) for t in asked))
    try:
        _config.forget_git_standing()
        before = asked_trees()
        cut = os.path.join(proj, ".git", "worktrees", "0-cut")
        os.makedirs(cut)
        with open(os.path.join(cut, "gitdir"), "w", encoding="utf-8") as fh:
            fh.write("/" + "a" * (2 * 1024 * 1024) + "\n")
        _config.forget_git_standing()
        after = asked_trees()
    finally:
        if prev is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = prev
    check("cf40b a registration whose pointer is a line of two mebibytes - read "
          "only up to the bound, so it may be cut - asks no tree: the trees "
          "asked and the verdicts, for the worktree's config at its "
          "destination and for a config-named file no tree loads, are those "
          "without it ((held, loose), trees asked) without %r, with %r"
          % (before, after),
          before == after and before[0] == ("block", "allow") and before[1])


# --- cf: the checkout a member project's walk finds, whatever its layout -----------
# A member project finds its checkout by a walk up from the project to the first
# git entry that is a repository. That checkout's top is a tree a loader is handed
# however git keeps its common directory: apart from it (a separate git
# directory), or inside a superproject's (a submodule). A git entry that is no
# repository - an empty directory, a file naming no git directory - is passed
# over as git passes over it. Each world lists the places a loader could be
# handed - every top git itself names from the project, each with its member
# place - and the rows are the hook run as a process; the twins are an ordinary
# write in each world and a config-named write no listed place reads.
def _topo_repo(top, files):
    """Each of `files` (relative) written under `top`, plus a committed
    repository there."""
    for rel_path in files:
        full = os.path.join(top, rel_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write("export const x = 1;\n")
    for argv in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "c"]):
        _harness.git(top, *argv, prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)


def _topo_link_out(tree, store):
    """`tree`'s config folder a link to `store`, made here.
    -> the config file at the link's destination."""
    os.makedirs(store)
    os.symlink(store, os.path.join(tree, _config.CONFIG_REL.split("/")[0]))
    return os.path.join(store, _config.CONFIG_REL.split("/")[1])


def _topo_sepgit(base):
    """R made with its git directory apart at G.git; the project R/a/b."""
    rel = _config.CONFIG_REL.split("/")
    top = os.path.join(base, "R")
    os.makedirs(os.path.join(top, "a", "b", "src"))
    with open(os.path.join(top, "a", "b", "src", "x.ts"), "w",
              encoding="utf-8") as fh:
        fh.write("export const x = 1;\n")
    _harness.git(base, "init", "-q", "--separate-git-dir",
                 os.path.join(base, "G.git"), top,
                 prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
    for argv in (["add", "-A"], ["commit", "-qm", "c"]):
        _harness.git(top, *argv, prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
    proj = os.path.join(top, "a", "b")
    dest = _topo_link_out(top, os.path.join(base, "store", "rcfg"))
    return {"name": "separate-git-dir", "base": base, "proj": proj,
            "trees": [top, proj],
            "rows": (("sepgit-top-at-destination", proj, dest, True),
                     ("sepgit-ordinary", proj,
                      os.path.join(proj, "src", "x.ts"), False),
                     ("sepgit-between-project-and-checkout", proj,
                      os.path.join(top, "a", *rel), False))}


def _topo_submodule(base):
    """S a repository holding the submodule S/sub, made from a local one; the
    project S/sub/app."""
    src, sup = os.path.join(base, "libsrc"), os.path.join(base, "S")
    _topo_repo(src, [os.path.join("app", "src", "x.ts")])
    _topo_repo(sup, [os.path.join("src", "s.ts")])
    _harness.git(sup, "-c", "protocol.file.allow=always", "submodule", "add",
                 "-q", src, "sub", prefix=_harness.WORKTREE_PAIR_GIT,
                 timeout=30)
    sub = os.path.join(sup, "sub")
    proj = os.path.join(sub, "app")
    dest = _topo_link_out(sub, os.path.join(base, "store", "scfg"))
    return {"name": "submodule", "base": base, "proj": proj,
            "trees": [sup, sub, proj],
            "rows": (("submodule-top-at-destination", proj, dest, True),
                     ("submodule-ordinary", proj,
                      os.path.join(proj, "src", "x.ts"), False))}


def _topo_stray_entry(base):
    """R with the project R/mid/app, an empty directory R/mid/.git between
    them, and a worktree W of R outside it."""
    rel = _config.CONFIG_REL.split("/")
    top, wt = os.path.join(base, "R"), os.path.join(base, "W")
    _topo_repo(top, [os.path.join("mid", "app", "src", "x.ts")])
    _harness.git(top, "worktree", "add", "-q", wt, "-b", "w",
                 prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
    os.makedirs(os.path.join(top, "mid", ".git"))
    proj = os.path.join(top, "mid", "app")
    place = os.path.join(wt, "mid", "app")
    rdest = _topo_link_out(top, os.path.join(base, "store", "rcfg"))
    wdest = _topo_link_out(wt, os.path.join(base, "store", "wcfg"))
    return {"name": "empty-git-entry-between", "base": base, "proj": proj,
            "trees": [top, proj, wt, place],
            "rows": (("stray-top-at-destination", proj, rdest, True),
                     ("stray-wt-top-at-destination", proj, wdest, True),
                     ("stray-wt-member-place", proj,
                      os.path.join(place, *rel), True),
                     ("stray-ordinary", proj,
                      os.path.join(proj, "src", "x.ts"), False))}


def _topo_no_repository(base):
    """X holding an empty directory X/.git and Y holding a file Y/.git that
    names no git directory, nothing above either a repository; the projects
    X/app and Y/app, each folder's config linked out."""
    worlds_rows, trees = [], []
    for name, entry in (("X", "dir"), ("Y", "file")):
        at = os.path.join(base, name)
        proj = os.path.join(at, "app")
        os.makedirs(os.path.join(proj, "src"))
        with open(os.path.join(proj, "src", "x.ts"), "w",
                  encoding="utf-8") as fh:
            fh.write("export const x = 1;\n")
        if entry == "dir":
            os.makedirs(os.path.join(at, ".git"))
        else:
            with open(os.path.join(at, ".git"), "w", encoding="utf-8") as fh:
                fh.write("not a pointer to a git directory\n")
        dest = _topo_link_out(at, os.path.join(base, "store", name.lower()))
        trees.append(proj)
        worlds_rows.append(("no-repo-%s-entry-at-destination" % (entry,), proj,
                            dest, False))
        worlds_rows.append(("no-repo-%s-entry-ordinary" % (entry,), proj,
                            os.path.join(proj, "src", "x.ts"), False))
    return {"name": "no-repository-above", "base": base, "proj": None,
            "trees": trees, "rows": tuple(worlds_rows)}


_TOPO_BUILDERS = (("t1", _topo_sepgit), ("t2", _topo_submodule),
                  ("t3", _topo_stray_entry), ("t0", _topo_no_repository))
# The allow twins each world owes, so a twin dropped from a builder is red.
_TOPO_TWINS = (("t1", 2), ("t2", 1), ("t3", 1), ("t0", 4))


def topology_worlds(base):
    """Each topology world built under `base`, or the reason it could not be.
    -> [(tag, built, world or reason)]"""
    out = []
    for tag, build in _TOPO_BUILDERS:
        at = os.path.join(base, tag)
        os.makedirs(at)
        built, world = _harness.attempt(build, at)
        out.append((tag, built, world))
    return out


def _topo_unbuildable(why):
    """Whether `why`, a fixture's failure, is this git lacking what the world
    needs - an option it does not know - rather than a broken fixture."""
    return any(w in str(why) for w in ("unknown option", "usage: git"))


def _topology_cases(check):
    """cf41, cf41b, cf41c: the checkout found by a member project's walk."""
    label = ("cf41 a member project's checkout top is asked whatever its "
             "repository's layout")
    base = os.path.realpath(_harness.fixture_root("guard-edits-topo-"))
    probe = os.path.join(base, "probe-link")
    linked, why = _harness.attempt(os.symlink, base, probe)
    if not linked:
        _harness.skip(check, label, "no symlink can be made here (%s)" % (why,),
                      os.name == "nt" or not hasattr(os, "symlink"))
        return
    os.remove(probe)
    seen, skipped = [], []
    for tag, built, world in topology_worlds(base):
        if not built:
            if not _topo_unbuildable(world):
                check("%s: the %s world builds (%s)" % (label, tag, world),
                      False)
                return
            skipped.append((tag, str(world)[:160]))
            continue
        for name, cwd, path, held in world["rows"]:
            proj = world["proj"] or cwd
            sub = _hook_verdict(proj, cwd, path, _CF_BODY, True)
            main = _hook_verdict(proj, cwd, path, _CF_BODY, False)
            reads = (_gen_reads(world, None, path, cwd, name)
                     if os.path.basename(path) == os.path.basename(
                         _config.CONFIG_REL) else [])
            seen.append((tag, name, (sub, main), reads, held))
    for tag, why in skipped:
        _harness.skip(check, "cf41 the %s world" % (tag,),
                      "this git cannot build it: %s" % (why,), True)

    def held_right(rows):
        return all(v == ("block", "ask") and r for _t, _n, v, r, _h in rows)
    outside = [s for s in seen if s[0] in ("t1", "t2") and s[4]]
    stray = [s for s in seen if s[0] == "t3" and s[4]]
    twins = [s for s in seen if not s[4]]
    want_outside = 2 - sum(1 for t, _w in skipped if t in ("t1", "t2"))
    check("cf41 in a member project of a repository made with its git "
          "directory apart (R/a/b, G.git) and of a project inside a submodule "
          "(S/sub/app), the checkout top's config written at its linked-out "
          "folder's destination is refused to a subagent and asked of the main "
          "session, the hook run as a process, each read by the top's loader "
          "(world, row, (sub, main), read by): %r" % (outside,),
          len(outside) == want_outside and held_right(outside))
    check("cf41b ...and with an empty directory R/mid/.git between the project "
          "R/mid/app and its checkout R - no repository, passed over as git "
          "passes over it - R's config and its worktree W's, each at its "
          "linked-out folder's destination, and the config of W's member "
          "place W/mid/app are held, each read by a loader (world, row, (sub, "
          "main), read by): %r" % (stray,),
          len(stray) == (0 if "t3" in dict(skipped) else 3)
          and held_right(stray))
    check("cf41c ...while their allow twins stay quiet - an ordinary write in "
          "each of those projects, a config-named file in the directory "
          "between a member project and its checkout, and a directory holding "
          "an empty git entry, or a .git file naming no git directory, with "
          "nothing above it a repository: its config at its linked-out "
          "folder's destination is asked of no tree, none of them read by a "
          "place the fixture listed (world, row, (sub, main), read by): %r"
          % (twins,),
          len(twins) == sum(n for t, n in _TOPO_TWINS if t not in dict(skipped))
          and any(s[0] == "t0" for s in twins)
          and all(v == ("allow", "allow") and not r
                  for _t, _n, v, r, _h in twins))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_guard_edits.py --selftest\n")
    raise SystemExit(2)
