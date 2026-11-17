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
    finally:
        if prev is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = prev


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_guard_edits.py --selftest\n")
    raise SystemExit(2)
