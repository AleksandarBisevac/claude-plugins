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

This hook carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test_guard_edits.py` (hyphens become underscores - a
hyphenated name is not importable). A test of a hook may import from `scripts/`
even though the hook itself may not; see `plugins/audit/tests/_harness.py`.
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
def collect(tool, ti):
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


def _self_edit_target(path, root):
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


def _deny_payload(msg):
    """Canonical PreToolUse deny payload (printed to stdout with exit 0)."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "[guard-edits] " + msg,
        }
    }


def _ask_payload(msg):
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


def block(msg):
    print(json.dumps(_deny_payload(msg)))
    sys.exit(0)


def ask(msg):
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


def _touches_state(tool, ti, path, root):
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
def decide(data, *, cfg=None):
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
            # in `plugins/audit/tests/test_guard_edits.py`, because four documents
            # said "starts with" while this line said something else for the whole
            # life of the hook.
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
def main():
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


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        # Answered rather than fallen through to main(), which would block on stdin
        # waiting for a hook payload that is never coming. It deliberately does NOT
        # print the `N/M cases passed` contract - that string is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("guard-edits.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_guard_edits.py - run that file instead.")
        sys.exit(0)
    main()
