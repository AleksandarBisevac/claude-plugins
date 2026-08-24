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
    blob = json.loads(json.dumps(M._deny_payload("why")))
    hso = blob.get("hookSpecificOutput") or {}
    check("d1 deny payload is canonical PreToolUse JSON",
          hso.get("hookEventName") == "PreToolUse"
          and hso.get("permissionDecision") == "deny"
          and str(hso.get("permissionDecisionReason", "")).startswith("[guard-edits]"))

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
        blob = json.loads(json.dumps(M._ask_payload("why")))
        hso = blob.get("hookSpecificOutput") or {}
        check("st8 the ask payload is canonical PreToolUse JSON",
              hso.get("hookEventName") == "PreToolUse"
              and hso.get("permissionDecision") == "ask"
              and str(hso.get("permissionDecisionReason", ""))
              .startswith("[guard-edits]"))
    finally:
        if _prev_pd is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = _prev_pd


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_guard_edits.py --selftest\n")
    raise SystemExit(2)
