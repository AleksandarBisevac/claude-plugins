#!/usr/bin/env python3
"""
PreToolUse guard (matcher: Edit|Write|MultiEdit|NotebookEdit).

Inspects the *incoming* text (new content) and the target path, and blocks:

  1. Token-logging ban (universal) — logging an auth token via
     console.* / Sentry / remoteLog. The token identifier names come from
     `.claude/audit.config.json` → guardEdits.tokenVars
     (default: accessToken, refreshToken, idToken). Prefix-only debug
     (token.slice(0, 6)) is allowed.

  2. Project custom rules (opt-in) — `.claude/audit.config.json` →
     guardEdits.customRules: a list of
        { "pathPrefix": "libs/x/", "bannedPattern": "<regex>", "message": "<why>" }
     Each rule blocks `bannedPattern` when `pathPrefix` occurs ANYWHERE in the
     edited path — a substring test, not a prefix test, and against the path the
     tool reported (usually absolute) rather than a repo-relative one. So
     "realtime/" matches both src/realtime/x.ts and libs/realtime/y.ts, which is
     what makes the rule usable in a monorepo where the same concern lives under
     several roots. The key keeps its name because configs in the field already
     use it; the documentation is what was wrong.
     Ships EMPTY by default — the plugin has no hardcoded project rules.

  3. Self-edit protection — edits targeting the INSTALLED plugin's own files
     (a model must not modify the hooks that govern it; upstream issue
     anthropics/claude-code#32376). Dev-mode exception: when the plugin
     directory lives INSIDE the consuming repo (a checkout of the plugin's own
     repository), editing is allowed — that's plugin development, not runtime.

  4. Bypass forgery — writing <stateDir>/plan-bypass-*.json directly would arm
     the plan-first opt-out without a user prompt. Those files may only be
     created by detect-plan-skip.py (i.e. by the USER typing the keyword).

  5. Journal edits — the audit trail under `journal.dir` (default: beside the
     manifest) is APPEND-ONLY and written by the plugin, never by hand. An edit
     there is either the accident this catches or the tamper `audit-journal.py
     verify` is built to name; refusing it costs nothing, because nothing
     legitimate writes those files with an edit tool.

Contract: a block emits {"hookSpecificOutput": {"permissionDecision": "deny",
"permissionDecisionReason": ...}} on stdout and exits 0 — the canonical
PreToolUse protocol (the exit-2 + stderr channel is deprecated).
Unexpected input exits 0 (never break legitimate work).
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _config  # noqa: E402

_HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_ROOT = os.path.dirname(_HOOKS_DIR)


# --- secret detection ---------------------------------------------------------
def _token_log_re(token_vars):
    """A logger call that passes a token as a *value* — as the SOLE/first arg
    (console.log(accessToken)), a later arg, an interpolation, a concat, an
    object value, or a property access (this.accessToken). Merely mentioning the
    word inside a string literal is not enough; a `.slice(...)` prefix debug is
    allowed."""
    alt = "|".join(re.escape(t) for t in token_vars) or "accessToken"
    return re.compile(
        r"(?:console\.\w+"
        r"|Sentry\.(?:captureMessage|captureException|addBreadcrumb|setExtra|setContext)"
        r"|remoteLog)\s*\(\s*"
        r"(?:[^)]*?(?:\$\{|,\s*|\+\s*|:\s*|\.\s*))?"
        r"(?:" + alt + r")\b"
        r"(?!\s*\.slice)",
        re.IGNORECASE | re.DOTALL,
    )


def _bearer_re(token_vars):
    alt = "|".join(re.escape(t) for t in token_vars + ["token"])
    return re.compile(r"[Bb]earer\s+\$\{?\s*(?:" + alt + r")\b", re.IGNORECASE)


# --- collection + deny helpers ------------------------------------------------
def collect(tool: str, ti: dict):
    if tool == "NotebookEdit":
        path = str(ti.get("notebook_path", "") or ti.get("file_path", ""))
        return path.replace("\\", "/"), str(ti.get("new_source", ""))
    path = str(ti.get("file_path", ""))
    chunks = []
    if tool == "Write":
        chunks.append(str(ti.get("content", "")))
    elif tool == "Edit":
        chunks.append(str(ti.get("new_string", "")))
    elif tool == "MultiEdit":
        for e in ti.get("edits", []) or []:
            chunks.append(str(e.get("new_string", "")))
    return path.replace("\\", "/"), "\n".join(chunks)


def _self_edit_target(path: str, root) -> bool:
    """True when `path` targets the installed plugin's own files while the plugin
    lives OUTSIDE the consuming repo. A plugin checkout inside the project
    (development) is exempt — there the plugin files ARE the project."""
    try:
        plugin_root = os.path.realpath(_PLUGIN_ROOT)
        proj = os.path.realpath(str(root))
        if plugin_root == proj or plugin_root.startswith(proj + os.sep):
            return False  # dev mode: plugin inside the consuming repo
        target = path if os.path.isabs(path) else os.path.join(proj, path)
        target = os.path.realpath(target)
        return target == plugin_root or target.startswith(plugin_root + os.sep)
    except Exception:
        return False


def _deny_payload(msg: str) -> dict:
    """Canonical PreToolUse deny payload (printed to stdout with exit 0)."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "[guard-edits] " + msg,
        }
    }


def _ask_payload(msg: str) -> dict:
    """Canonical PreToolUse ask payload — the strict-mode channel. NEVER deny:
    the orchestrator completes tasks through these same tools, and a deny here
    would refuse the pipeline its own bookkeeping."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": "[guard-edits] " + msg,
        }
    }


def block(msg: str) -> None:
    print(json.dumps(_deny_payload(msg)))
    sys.exit(0)


def ask(msg: str) -> None:
    print(json.dumps(_ask_payload(msg)))
    sys.exit(0)


# --- strict manifest state (journal.strictManifestState, default "off") -------
_STATE_RE = re.compile(r'"(?:status|completedAt|commit|attempts)"\s*:')


def _strict_mode(cfg):
    """"off" | "ask"; anything else (including absence) is off — opt-in."""
    try:
        block_ = (cfg or {}).get("journal")
        v = block_.get("strictManifestState") if isinstance(block_, dict) else None
        return v if v in ("off", "ask") else "off"
    except Exception:
        return "off"


def _state_map(obj):
    """{(kind, id): (status, completedAt, commit, attempts)} over a manifest,
    an index, or one shard body. What strict mode means by 'state'."""
    out = {}
    if not isinstance(obj, dict):
        return out
    plist = obj.get("phases")
    if isinstance(plist, list):
        candidates = plist
    elif obj.get("id") and isinstance(obj.get("tasks"), list):
        candidates = [obj]
    else:
        candidates = []
    for ph in candidates:
        if not isinstance(ph, dict):
            continue
        if ph.get("id"):
            out[("phase", ph["id"])] = json.dumps(
                [ph.get(k) for k in ("status", "completedAt", "commit",
                                     "attempts")], sort_keys=True, default=str)
        tlist = ph.get("tasks")
        for t in (tlist if isinstance(tlist, list) else []):
            if isinstance(t, dict) and t.get("id"):
                out[("task", t["id"])] = json.dumps(
                    [t.get(k) for k in ("status", "completedAt", "commit",
                                        "attempts")], sort_keys=True,
                    default=str)
    return out


def _touches_state(tool: str, ti: dict, path: str, root) -> bool:
    """Does this edit change task/phase STATE (status, completedAt, commit,
    attempts)? Write: a real diff against the on-disk file (every whole-manifest
    Write contains the word "status", so sniffing would ask on all of them).
    Edit/MultiEdit/NotebookEdit: fragment heuristic on the old/new strings.
    Unknowable -> False, fail open."""
    try:
        if tool == "Write":
            target = path if os.path.isabs(path) else os.path.join(str(root),
                                                                   path)
            try:
                with open(target, "r", encoding="utf-8") as fh:
                    old_obj = json.load(fh)
            except Exception:
                return False       # a new or unreadable file is not a flip
            try:
                new_obj = json.loads(str(ti.get("content", "")))
            except Exception:
                return False
            return _state_map(old_obj) != _state_map(new_obj)
        frags = []
        if tool == "Edit":
            frags = [str(ti.get("old_string", "")),
                     str(ti.get("new_string", ""))]
        elif tool == "MultiEdit":
            for e in ti.get("edits", []) or []:
                frags.append(str(e.get("old_string", "")))
                frags.append(str(e.get("new_string", "")))
        elif tool == "NotebookEdit":
            frags = [str(ti.get("new_source", ""))]
        return any(_STATE_RE.search(f) for f in frags)
    except Exception:
        return False


# --- decision -----------------------------------------------------------------
def decide(data: dict, *, cfg=None):
    """Pure decision core. Returns ("allow", reason) or ("block", message)."""
    tool = data.get("tool_name", "")
    if tool not in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return ("allow", "unknown tool")

    path, text = collect(tool, data.get("tool_input", {}) or {})
    root = _config.repo_root(data)
    cfg = cfg if cfg is not None else _config.load(root)

    # path-based blocks first — they apply even to empty/whitespace content
    if path:
        # 3. self-edit protection
        if _self_edit_target(path, root):
            return ("block",
                    "The audit plugin's own files are read-only at runtime "
                    "(self-edit protection): %s\n"
                    "A model must not modify the hooks that govern it. To change "
                    "the plugin, edit it in its own repository checkout." % path)

        # 4. bypass forgery
        state_rel = str(cfg.get("stateDir")
                        or _config.DEFAULTS["stateDir"]).strip("/")
        rel = _config.rel_path(root, path)
        base = rel.rsplit("/", 1)[-1]
        if rel.startswith(state_rel + "/") and base.startswith("plan-bypass-"):
            return ("block",
                    "Writing the plan-first bypass state directly is not allowed "
                    "(bypass forgery): %s\n"
                    "A bypass may only be armed by the USER including the bypass "
                    "keyword in their prompt." % rel)

        # 5. the append-only audit trail
        if _config.in_journal(root, cfg, path):
            return ("block",
                    "The audit journal is append-only: %s\n"
                    "It is written by the plugin (panel saves, the journal-writes "
                    "hook, audit-journal.py append) and never by hand — an edit "
                    "here is what `audit-journal.py verify` exists to detect. To "
                    "record something, append a row; to stop recording, set "
                    "journal.enabled false." % rel)

        # 6. opt-in strict manifest state (journal.strictManifestState: "ask").
        #    ASK, never deny — the orchestrator completes tasks through these
        #    same tools. Off by default; the journal + doctor detection stays
        #    the default defence.
        if _strict_mode(cfg) == "ask":
            manifest_rel = str(cfg.get("manifestPath")
                               or _config.DEFAULTS["manifestPath"])
            if (rel == manifest_rel
                    or _config.governing_lock(manifest_rel, rel)):
                ti = data.get("tool_input", {}) or {}
                if _touches_state(tool, ti, path, root):
                    return ("ask",
                            "journal.strictManifestState is \"ask\": this edit "
                            "changes task/phase state (status, completedAt, "
                            "commit or attempts) in %s -- confirm it is "
                            "intentional." % rel)

    if not text:
        return ("allow", "no text")

    # 1. project custom rules (opt-in)
    for rule in _config.custom_rules(cfg):
        try:
            prefix = str(rule.get("pathPrefix", ""))
            pattern = str(rule.get("bannedPattern", ""))
            if not prefix or not pattern:
                continue
            # SUBSTRING, not a prefix — see the module docstring. Pinned by c3/c4
            # in the selftest below, because four documents said "starts with"
            # while this line said something else for the whole life of the hook.
            if prefix in path and re.search(pattern, text):
                msg = rule.get("message") or (
                    "Blocked by a project custom rule: pattern %r is banned under %s."
                    % (pattern, prefix)
                )
                return ("block", str(msg))
        except Exception:
            continue

    # 2. token-logging ban (universal)
    token_vars = _config.token_vars(cfg)
    if _token_log_re(token_vars).search(text) or _bearer_re(token_vars).search(text):
        return ("block",
                "Blocked: this logs a full auth token.\n"
                "Never log %s / Authorization. For debug, log a prefix only: "
                "token.slice(0, 6) + ' len=' + token.length." % " / ".join(token_vars))

    return ("allow", "clean")


# --- cli ----------------------------------------------------------------------
def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    try:
        verdict, msg = decide(data)
    except Exception:
        sys.exit(0)

    if verdict == "block":
        block(msg)
    if verdict == "ask":
        ask(msg)
    sys.exit(0)


# --- selftest -----------------------------------------------------------------
def _selftest() -> int:
    import tempfile

    results = []
    tmp = tempfile.mkdtemp(prefix="guard-edits-selftest-")
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

    def check(name, expected, tool, path, text, *, cwd=tmp, cfg=cfg):
        ti = {"file_path": path, "content": text}
        if tool == "NotebookEdit":
            ti = {"notebook_path": path, "new_source": text}
        data = {"tool_name": tool, "tool_input": ti, "cwd": cwd}
        try:
            verdict, _ = decide(data, cfg=cfg)
        except Exception as exc:  # pragma: no cover
            verdict = "EXC:%s" % exc
        ok = verdict == expected
        results.append(ok)
        print("%s %s (expected %s, got %s)"
              % ("PASS" if ok else "FAIL", name, expected, verdict))

    # custom rule fires only under its pathPrefix
    check("c1 removeAllListeners under prefix blocked", "block", "Write",
          "src/realtime/useX.tsx", "qObject.removeAllListeners()")
    check("c2 removeAllListeners elsewhere allowed", "allow", "Write",
          "src/other/useX.tsx", "qObject.removeAllListeners()")
    # `pathPrefix` is matched as a SUBSTRING of the path the tool reported, which is
    # normally ABSOLUTE. Four documents said "starts with" instead; a rule written
    # to that description would have been believed to cover nothing (no real edit
    # path starts with "src/") while actually covering every occurrence anywhere in
    # the tree. These two pin the behaviour the docs now describe: an implementation
    # using str.startswith would fail c3, and one anchoring at the repo root would
    # fail c4.
    check("c3 the same rule fires from an ABSOLUTE path (a startswith match "
          "would not)", "block", "Write",
          "/Users/dev/checkout/src/realtime/useX.tsx", "q.removeAllListeners()")
    check("c4 and from a second root in a monorepo - the match is a substring, "
          "so one rule covers every place the concern lives", "block", "Write",
          "packages/web/src/realtime/useX.tsx", "q.removeAllListeners()")
    # token logging
    check("t1 logger with token value blocked", "block", "Write",
          "src/api.ts", "console.log('tok', %s)" % tok)
    check("t2 token prefix debug allowed", "allow", "Write",
          "src/api.ts", "console.log(%s.slice(0,6))" % tok)
    check("t3 innocent code allowed", "allow", "Write",
          "src/api.ts", "const x = 1 + 2;")
    check("t4 logger with token as SOLE arg blocked", "block", "Write",
          "src/api.ts", "console.log(%s)" % tok)
    check("t5 logger with token via property access blocked", "block", "Write",
          "src/api.ts", "console.log(this.%s)" % tok)
    check("t6 logger of a DIFFERENT identifier (token-prefix) allowed", "allow",
          "Write", "src/api.ts", "console.log(%sExpiry)" % tok)
    # NotebookEdit is covered too
    check("n1 notebook cell logging token blocked", "block", "NotebookEdit",
          "notebooks/train.ipynb", "console.log('t', %s)" % tok)
    check("n2 innocent notebook cell allowed", "allow", "NotebookEdit",
          "notebooks/train.ipynb", "print('hello')")

    # self-edit protection: plugin dir is OUTSIDE the tmp "project" → block,
    # even with empty content
    check("s1 editing an installed plugin file blocked", "block", "Write",
          os.path.join(_HOOKS_DIR, "guard-edits.py"), "tampered")
    check("s2 empty-content write to plugin file blocked", "block", "Write",
          os.path.join(_HOOKS_DIR, "hooks.json"), "")
    # dev mode: when cwd IS the repo containing the plugin → allow
    plugin_repo = os.path.dirname(os.path.dirname(_PLUGIN_ROOT))
    check("s3 dev-mode edit of plugin file allowed", "allow", "Write",
          os.path.join(_HOOKS_DIR, "guard-edits.py"), "dev change",
          cwd=plugin_repo)

    # bypass forgery
    check("f1 writing plan-bypass state blocked", "block", "Write",
          ".claude/state/plan-bypass-abc.json", "{}")
    check("f2 other state files allowed", "allow", "Write",
          ".claude/state/tdd-reminder-abc.json", "{}")

    # the append-only journal. Blocked with empty content too: the point is the
    # PATH, and a truncation to nothing is the most destructive edit of all.
    check("j1 editing a journal file blocked", "block", "Edit",
          "docs/audit/journal/2026-08.abc.jsonl", '{"v":1}')
    check("j2 truncating one is blocked as well", "block", "Write",
          "docs/audit/journal/2026-08.abc.jsonl", "")
    check("j3 a notebook path under the journal is no different", "block",
          "NotebookEdit", "docs/audit/journal/x.ipynb", "print(1)")
    # ...and the guard is about that directory alone. A neighbour whose name
    # merely starts the same way is ordinary work.
    check("j4 the manifest beside it is not the journal - and with "
          "journal.strictManifestState at its DEFAULT (off) a manifest write "
          "is allowed outright", "allow", "Write",
          "docs/audit/audit-plan.json", '{"meta":{"version":3}}')
    check("j5 a sibling directory with a similar name is not the journal",
          "allow", "Write", "docs/audit/journal-notes/why.md", "notes")
    check("j6 and a journal moved by config is protected where it actually is",
          "block", "Write", "trail/2026-08.abc.jsonl", "{}",
          cfg=_config._deep_merge(cfg, {"journal": {"dir": "trail"}}))
    check("j7 ...which means the default location is then no longer special",
          "allow", "Write", "docs/audit/journal/2026-08.abc.jsonl", "{}",
          cfg=_config._deep_merge(cfg, {"journal": {"dir": "trail"}}))

    # deny payload is canonical PreToolUse JSON
    blob = json.loads(json.dumps(_deny_payload("why")))
    hso = blob.get("hookSpecificOutput") or {}
    ok = (hso.get("hookEventName") == "PreToolUse"
          and hso.get("permissionDecision") == "deny"
          and str(hso.get("permissionDecisionReason", "")).startswith("[guard-edits]"))
    results.append(ok)
    print("%s j1 deny payload is canonical PreToolUse JSON" % ("PASS" if ok else "FAIL"))

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
            try:
                return decide(data, cfg=use_cfg)
            except Exception as exc:   # pragma: no cover
                return ("EXC:%s" % exc, "")

        def st_check(name, expected, tool, ti, use_cfg):
            v, _m = st_decide(tool, ti, use_cfg)
            ok = v == expected
            results.append(ok)
            print("%s %s (expected %s, got %s)"
                  % ("PASS" if ok else "FAIL", name, expected, v))

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
        ok = _v == "ask"
        results.append(ok)
        print("%s st7 strict NEVER denies - the verdict is ask, and the "
              "orchestrator keeps its own bookkeeping (got %s)"
              % ("PASS" if ok else "FAIL", _v))
        blob = json.loads(json.dumps(_ask_payload("why")))
        hso = blob.get("hookSpecificOutput") or {}
        ok = (hso.get("hookEventName") == "PreToolUse"
              and hso.get("permissionDecision") == "ask"
              and str(hso.get("permissionDecisionReason", ""))
              .startswith("[guard-edits]"))
        results.append(ok)
        print("%s st8 the ask payload is canonical PreToolUse JSON"
              % ("PASS" if ok else "FAIL"))
    finally:
        if _prev_pd is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = _prev_pd

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    main()
