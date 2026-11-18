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

import json
import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
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


def _disk_calls(fn):
    """(result of fn(), {call: count}) over `_DISK_CALLS`. A call counts when no
    other counted call happened inside it - the leaf - so `realpath` counts as
    the `lstat` and `readlink` calls it makes, and an `isdir` that asks the disk
    itself, as it does on some platforms, counts once as `os.path.isdir`."""
    seen = []
    saved = [(owner, name, getattr(_owner(owner), name))
             for owner, name in _DISK_CALLS if hasattr(_owner(owner), name)]

    def counting(label, real):
        def call(*a, **k):
            mark = len(seen)
            try:
                return real(*a, **k)
            finally:
                if len(seen) == mark:
                    seen.append(label)
        return call
    for owner, name, real in saved:
        setattr(_owner(owner), name, counting("%s.%s" % (owner, name), real))
    try:
        out = fn()
    finally:
        for owner, name, real in saved:
            setattr(_owner(owner), name, real)
    by = {}
    for label in seen:
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
    # candidate tree's config path costs); and the same question with the
    # nested-tree half answered "no candidate". A listing is its own case.
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

    def _today(target, root):
        real = os.path.realpath(target)
        real_root = os.path.realpath(root)
        if _harness.attempt(os.stat, real)[0]:
            _harness.attempt(os.stat, os.path.join(real_root, *rel))
        else:
            at = real_root
            for name in rel:
                at = os.path.join(at, name)
                os.path.islink(at)
        top = _shaped(real)
        if top is not None and top != real_root:
            _config._holds_repository(top)

    def _kinds(by):
        return dict((k.rsplit(".", 1)[-1], n) for k, n in sorted(by.items()))

    plain_cfg = os.path.join(main, "docs", "cf-sample", *rel)
    os.makedirs(os.path.dirname(plain_cfg))
    costs, kinds = [], []
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
        listed = sum(now.get(n, 0) for n in _LISTINGS)
        name = os.path.basename(src) if not plain else "plain folder"
        costs.append((name, verdict, sum(before.values()),
                      sum(walked.values()), sum(now.values()), listed,
                      now == today and (plain or now == off)
                      and sum(now.values()) <= sum(before.values())))
        kinds.append((name, _kinds(walked), _kinds(now)))
    check("cf29 an ordinary write - an existing and a new source file, and a "
          "file merely named like the config in a plain folder - makes the "
          "config question's disk calls call for call: before the walk's, and "
          "for a write that creates its file a link question for the config's "
          "folder and its file, what resolving the project's config path "
          "costs, no more in total than before "
          "identity was asked, and none for the nested tree's identity (name, "
          "verdict, before identity, before the folder was resolved, now, "
          "listings, held): %r; by kind, before the folder was resolved and "
          "now: %r" % (costs, kinds),
          len(costs) == 3 and all(not v and held
                                  for _n, v, _b, _t, _now, _l, held in costs))
    check("cf29b ...and lists no directory, on any of them (listings: %r)"
          % ([(c[0], c[5]) for c in costs],),
          len(costs) == 3 and all(c[5] == 0 for c in costs))

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
    """cf31: each component of a creating write is judged in the directory that
    holds it - the volume's answers substituted by a model, so every host runs
    it. `_one_entry(directory, name, own)` and `_volume_folds(directory)` are
    answered from `model`, a directory's rule; every question is recorded."""
    top = os.path.realpath(fresh)
    cdir = os.path.join(top, rel[0])
    os.makedirs(cdir)
    with open(os.path.join(cdir, "settings.json"), "w", encoding="utf-8") as fh:
        fh.write("{}\n")

    def _run(model, path):
        asked = {"entry": [], "rule": []}

        def entry(directory, name, own):
            asked["entry"].append((directory, name, own))
            return bool(model.get(directory))

        def rule(directory):
            asked["rule"].append(directory)
            return model.get(directory)
        verdict = _with_attr("_one_entry", entry, lambda: _with_attr(
            "_volume_folds", rule, lambda: _cf_decide(
                cfg, "Write", _w(path), main, "agent-cf")[0], on=_config),
            on=_config)
        return verdict, asked

    up = _cap(rel[0])
    dir_only = os.path.join(top, up, rel[1])
    both = os.path.join(top, up, "Audit.Config.json")
    name_only = os.path.join(cdir, "Audit.Config.json")
    folds_above = {top: True, cdir: False}
    folds_below = {top: False, cdir: True}
    seen = []
    for label, model, path, want, entries, rules in (
            ("dir-variant, top folds, .claude tells case apart", folds_above,
             dir_only, "block", [(top, up, rel[0])], []),
            ("both variant, top folds, .claude tells case apart", folds_above,
             both, "allow", [(top, up, rel[0])], [cdir]),
            ("dir-variant, top tells case apart, .claude folds", folds_below,
             dir_only, "allow", [(top, up, rel[0])], []),
            ("name-variant, top tells case apart, .claude folds", folds_below,
             name_only, "block", [], [cdir])):
        verdict, asked = _run(model, path)
        seen.append((label, verdict, asked["entry"] == entries
                     and asked["rule"] == rules))
        if verdict != want or asked["entry"] != entries \
                or asked["rule"] != rules:
            seen[-1] = seen[-1] + ((want, entries, rules, asked),)
    check("cf31 STUBBED - each component of a creating write is judged in the "
          "directory that holds it: where the config's own component exists "
          "there by whether both names reach one entry, where it does not by "
          "that directory's own rule; a name in the project tree is never "
          "asked of the .claude below it, nor the reverse: %r" % (seen,),
          len(seen) == 4 and all(len(s) == 3 and s[1] == w and s[2]
                                 for s, w in zip(seen, ("block", "allow",
                                                        "allow", "block"))))
    os.remove(os.path.join(cdir, "settings.json"))
    os.rmdir(cdir)
    created = []
    for model, want in (({top: True}, "block"), ({top: False}, "allow")):
        verdict, asked = _run(model, both)
        created.append((model[top], verdict, asked["entry"], asked["rule"]))
    check("cf31b STUBBED: with no .claude yet, the directory the write would "
          "create takes the rule of the directory it would be created in - one "
          "question of the tree, asked once, held where it folds and allowed "
          "where it does not, and no identity question where nothing exists "
          "(folds, verdict, identity questions, rule questions asked of): %r"
          % ([(f, v, e, [os.path.relpath(d, main) for d in r])
              for f, v, e, r in created],),
          [c[1] for c in created] == ["block", "allow"]
          and all(c[2] == [] and c[3] == [top] for c in created))


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
# fixture and the loader is asked - for the project, for the tree the session
# stands in, and for the tree the path lies in as written - whether it now reads
# what was written. The hook holds the write exactly when one of them does. The
# trees are found here by a lexical walk for `.git`, never through the hook's own
# placement, so the oracle and the subject do not share an answer.
#
# A ROW IS ONE ARRANGEMENT: (id, layout, config present, spelling, measured, twin).
# `layout` is how the project's config folder is made and `spelling` how the write
# names the file and where the session stands; `_link_world` and `_link_spell`
# hold one branch per word. `measured` marks an arrangement the review ran as a
# process and found allowed; `twin` an allow twin, a write no loader reads.
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
)


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
    return {"proj": proj, "folder": folder, "dest": dest, "store": store,
            "base": base}


def _link_spell(world, spelling):
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
        # config: no loader the property asks reads it - the stated residual.
        link = os.path.join(proj, "lf.json")
        os.symlink(os.path.join(world["base"], "ext", *rel), link)
        return link, proj
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


def _lexical_tree(directory):
    """The nearest directory at or above `directory`, walked as SPELLED, holding a
    `.git` entry - the tree a path lies in as written - or None."""
    d = os.path.normpath(directory)
    while True:
        if os.path.lexists(os.path.join(d, ".git")):
            return d
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up


def _hook_verdict(proj, cwd, path, body, agent):
    """guard-edits.py run as the host runs it, for a Write of `path` from `cwd`:
    'block', 'ask', 'allow', or a word naming what else happened."""
    import subprocess
    data = {"hook_event_name": "PreToolUse", "tool_name": "Write",
            "session_id": "sess-ln", "cwd": cwd,
            "tool_input": {"file_path": path, "content": body}}
    if agent:
        data["agent_id"] = "a1b2c3d4e5f6"
        data["agent_type"] = "audit-executor"
    env = dict((k, v) for k, v in os.environ.items()
               if not k.startswith("CLAUDE") and k != _DRIVE_MARK)
    env["CLAUDE_PROJECT_DIR"] = proj
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    got = subprocess.run(
        [sys.executable, "-B", os.path.join(_harness.HOOKS_DIR,
                                            "guard-edits.py")],
        input=json.dumps(data).encode("utf-8"), capture_output=True,
        env=env, cwd=proj, timeout=60)
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
    of the trees' loaders reads it. -> (id, sub, main, trees that read, why)"""
    rid, layout, present, spelling = row[:4]
    world = _link_world(base, layout, present)
    path, cwd = _link_spell(world, spelling)
    body = json.dumps({"cfMark": rid}) + "\n"
    sub = _hook_verdict(world["proj"], cwd, path, body, True)
    main = _hook_verdict(world["proj"], cwd, path, body, False)
    full = path if os.path.isabs(path) else os.path.join(cwd, path)
    made, why = _harness.attempt(_link_write, full, body)
    trees = [t for t in (world["proj"], _lexical_tree(cwd),
                         _lexical_tree(os.path.dirname(full)))
             if t is not None and _of_this_repository(t, world["proj"])]
    reads = sorted(set(os.path.relpath(t, base) for t in trees
                       if _config.load(t).get("cfMark") == rid))
    if not made:
        # A write no tool can make (a link that cannot be followed): the
        # property has nothing to read, and the guard is owed the hold it gave
        # such a path before - fail closed, never a hold turned into an allow.
        reads = ["write not made: %s" % (why,)]
    return rid, sub, main, reads, "%s/%s/%s" % (
        layout, "present" if present else "absent", spelling)


def _link_write(full, body):
    """The write, made as a tool that creates missing directories makes it:
    through every link on the way, the missing ones at the place they name."""
    os.makedirs(os.path.realpath(os.path.dirname(full)), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(body)


def _of_this_repository(tree, proj):
    """Is the directory `tree` a tree of the repository at `proj` - the
    project, a repository placed under it as spelled, or a working tree sharing
    its git directory - asked of git here, apart from the hook."""
    if _spelled_inside(tree, proj):
        return True
    ok, mine = _harness.attempt(_harness.git, proj, "rev-parse",
                                "--git-common-dir")
    ok2, theirs = _harness.attempt(_harness.git, tree, "rev-parse",
                                   "--git-common-dir")
    return ok and ok2 and os.path.realpath(
        os.path.join(proj, mine.strip())) == os.path.realpath(
            os.path.join(tree, theirs.strip()))


def _spelled_inside(path, top):
    p, t = os.path.normpath(path), os.path.normpath(top)
    return p == t or p.startswith(t + os.sep)


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
        seen.append(got if ok else (row[0], "fixture", "fixture", [], repr(got)))
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
    agree = [s for s in seen if (held(s) if s[3] else quiet(s))]
    check("cf34 over a table of arrangements of the config folder - a real "
          "directory, a symlink inside the project, outside the repository, to "
          "another tree's config folder, into one, a chain, a relative link, a "
          "dangling link, a loop, the config file itself a dangling link, a "
          "nested worktree under it, a session in a linked worktree, a "
          "relative path, the project's config hard-linked into a sibling "
          "worktree, a symlink file at a sibling's config - the hook holds a write exactly when the loader then "
          "reads the written file for the project, the session's tree or the "
          "tree of this repository the path lies in (%d of %d rows agree); "
          "disagreeing: %r"
          % (len(agree), len(seen),
             [s for s in seen if s not in agree]),
          len(seen) == len(_LINK_ROWS) and len(agree) == len(seen)
          and any(s[3] for s in seen) and any(not s[3] for s in seen))
    twins = [by_id[r[0]] for r in _LINK_ROWS if r[5]]
    check("cf34b ...and the allow twins are allowed and no loader reads them: a "
          "file beside the config in the symlinked folder, a config-named file "
          "in a symlinked folder that is no tree's config folder, the same "
          "under a symlinked .claude of a plain subfolder, one outside every "
          "tree, and the config of an unrelated repository through its own "
          "symlinked .claude: %r" % (twins,),
          len(twins) == 5 and all(quiet(s) and not s[3] for s in twins))
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


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_guard_edits.py --selftest\n")
    raise SystemExit(2)
