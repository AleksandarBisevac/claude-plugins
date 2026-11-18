#!/usr/bin/env python3
"""
PreToolUse guard (matcher: Edit|Write|MultiEdit|NotebookEdit, and mcp__.*).

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

  6. Strict manifest state (opt-in, `journal.strictManifestState: "ask"`) — an
     edit that changes task or phase state in the manifest is ASKED.

  7. The audit config — a write to the file `_config.load` reads
     (`<tree>/_config.CONFIG_REL`, for the project and for a linked worktree of
     it wherever that worktree sits, one placed under the project included;
     which file a path names is `_config.audit_config_way`'s answer, by
     identity and by each directory's own rule on letter case, never by
     spelling - the same answer the write journal records a config row by) is
     REFUSED to a subagent (`_config.is_subagent`) and to
     a session the drive started (the launcher's mark, `_drive_started`), and
     ASKED of the main session. The plan gate exempts `.claude/**`, so without
     this an agent could switch the capability policy, the plan gate or the
     journal off with one Edit, and only a journal row would say so. Ask rather
     than deny for the main session, because the owner legitimately has it
     change config; the owner's own routes are /audit:panel (the panel server
     writes the file from its own process, which no tool hook sees) and a hand
     edit. A session the drive started has no human at its prompt, so it is
     refused instead; the host's hooks reference documents an ask there as
     denied, which was read and not probed (SECURITY.md quotes it), and the
     refusal does not rest on it. The refusal is this hook, so it holds where
     hooks run: a Claude Code version that runs no hooks inside a subagent runs
     none of this there (SECURITY.md, the capability policy's first flag). The
     rule holds in the plugin's own checkout too: rule 3's dev-mode exception is
     for plugin SOURCE, and this file is that checkout's governance, not its
     source.
     NOT covered, stated: a shell-form write (`sed -i`, a redirect, an
     interpreter) never reaches this hook; it is recorded by the journal and
     nothing refuses it. Nor does an MCP write whose payload carries no write
     basis (`_config.mcp_payload`): a body that is one line of JSON, or a move
     onto the config, is allowed. SECURITY.md carries both residuals.

WHICH OF THOSE AN MCP SERVER'S WRITE TOOL REACHES, AND WHICH IT CANNOT. An MCP
call reaches no edit-tool matcher, so before it was wired here a filesystem
server's `write_file` was outside every rule above. `_decide_mcp` is the branch,
and it is deliberately not all of them:

  - 3 (self-edit) is reached on the TARGET ALONE, whatever the operation, which
    is guard-secrets-read's argument for a secret file one guard over. The target
    set is the installed plugin's own directory *while it lives outside the
    consuming repo* — nothing an ordinary task does reads or writes there, so a
    refusal costs a retry on a call nobody makes, and it closes the shapes a write
    test cannot see (a rename, a delete).
  - 4 (bypass forgery), 5 (the append-only journal) and 7 (the audit config) are
    reached only with a WRITE BASIS in the payload (`_config.mcp_payload`),
    because unlike the plugin's own directory all three live INSIDE the repo and
    are ordinary things to read. Refusing a read there would be friction on
    honest traffic, which is the failure direction this side is not allowed to
    have.
  - 1 (project custom rules) and 2 (the token-logging ban) are NOT reached, and
    nothing replaces them. Both grade the TEXT THAT WILL BECOME FILE BYTES, and
    `collect()` can name that text only because an edit tool's schema is fixed. An
    MCP payload has no such field, reading argument keys is the thing this plugin
    does not do, and grading every string instead would refuse an issue body or a
    commit message that QUOTES the banned pattern rather than introduces it — the
    same operation-vs-text mistake `guard-secrets-read._shell_text` corrects for a
    read verb followed by a secret path. So an auth token logged by a source file
    written through an MCP server is not caught here: stated, because a gap a
    reader can see is worth more than a rule that fires on prose.
  - 6 (strict manifest state) is not reached either: it reads an old/new fragment
    pair off the edit tool's own schema, and an MCP payload carries no such pair.
    The write itself still reaches the journal, which is where that opt-in points
    its reader anyway.

Contract: a block emits {"hookSpecificOutput": {"permissionDecision": "deny",
"permissionDecisionReason": ...}} on stdout and exits 0 — the canonical
PreToolUse protocol (the exit-2 + stderr channel is deprecated).
Unexpected input exits 0 (never break legitimate work).

This hook carries no `--selftest` of its own any more; its cases live in
`tests/test_guard_edits.py` (hyphens become underscores - a
hyphenated name is not importable). A test of a hook may import from `scripts/`
even though the hook itself may not; see `tests/_harness.py`.
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


def block(msg):
    print(json.dumps(_config.deny_payload("[guard-edits] " + msg)))
    sys.exit(0)


def ask(msg):
    """The channel of rules 6 and 7, both of which the main session must be able
    to pass with the human's approval: the orchestrator completes tasks through
    these same tools, and the owner has it change config through them."""
    print(json.dumps(_config.ask_payload("[guard-edits] " + msg)))
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


# --- the MCP branch -----------------------------------------------------------
_MCP_SELF_EDIT = (
    "The audit plugin's own files are read-only at runtime (self-edit "
    "protection): %s\n"
    "A model must not modify the hooks that govern it, and this server calls the "
    "operation `%s` — a PreToolUse payload cannot tell a read of that file from a "
    "write to it, so the plugin's own directory is refused either way. To change "
    "the plugin, edit it in its own repository checkout."
)

_MCP_BYPASS = (
    "Writing the plan-first bypass state directly is not allowed (bypass "
    "forgery): %s\n"
    "A bypass may only be armed by the USER including the bypass keyword in their "
    "prompt. This call carries %s, which is what makes it a write; `%s` is the "
    "operation it asked for."
)

_MCP_JOURNAL = (
    "The audit journal is append-only: %s\n"
    "It is written by the plugin (panel saves, the journal-writes hook, "
    "audit-journal.py append) and never by hand — an edit here is what "
    "`audit-journal.py verify` exists to detect. This call carries %s, which is "
    "what makes it a write; `%s` is the operation it asked for. To record "
    "something, append a row; to stop recording, set journal.enabled false."
)


# --- the audit config -----------------------------------------------------------
_CONFIG_DENY = (
    "The audit config is the owner's, not an agent's: %s\n"
    "It holds the capability policy, the plan gate and the journal switch that "
    "govern this agent, so a subagent's edit-tool or MCP write to it is refused. "
    "The owner changes it through /audit:panel or by hand. If this task needs a "
    "config change, say so in your outcome and stop.%s"
)

_CONFIG_ASK = (
    "This writes the project's audit config: %s\n"
    "It holds the capability policy, the plan gate and the journal switch, so "
    "the owner decides each write to it. Approve only a change the owner asked "
    "for; the owner's own routes are /audit:panel or a hand edit.%s"
)

_CONFIG_DRIVE_DENY = (
    "The audit config is the owner's, not an agent's: %s\n"
    "This session was started by the audit drive (run-agent-session.py marks it "
    "with AUDIT_DRIVE_SESSION), so nobody is at its prompt to approve a "
    "write to the capability policy, the plan gate or the journal switch that "
    "govern it, and the write is refused as a subagent's is. The owner changes "
    "it through /audit:panel or by hand. If this task needs a config change, say "
    "so in your outcome and stop.%s"
)

# The environment name run-agent-session.py sets for every session it starts. A
# session the drive started is top-level, so its tool calls carry no agent id and
# `_config.is_subagent` cannot tell it from the owner's own session; this is the
# only witness of it. Spelled here and in the launcher, which this hook may not
# import; each side's suite writes the name out, so a rename goes red there.
_DRIVE_MARK = "AUDIT_DRIVE_SESSION"


def _drive_started():
    """Whether the launcher marked this session. An empty or blank value marks
    nothing, so a caller that clears the name by setting it empty is unmarked."""
    return bool(os.environ.get(_DRIVE_MARK, "").strip())


# The one clause a refusal or an ask gains, for a creating write whose spelling
# matched the config's only once case was set aside, where no directory on the
# path could be asked (`_config.audit_config_way` answers "case-blind").
_CASE_BLIND = (
    "\nThe path's spelling was matched to the config's without regard to case: "
    "no existing directory on it could say whether this volume tells case apart, "
    "so it is held as the config would be.")


def _config_verdict(data, rel, tail=""):
    """("block", msg) for a subagent or a session the drive started, ("ask",
    msg) for the main session.

    Ask, not deny, for the main session: the owner legitimately has it change
    config, and only the human at the prompt can tell that request from an agent
    switching its own governance off. A session the drive started has no human
    at its prompt, so it is refused like a subagent; what the host does with an
    ask nobody can answer is not what this rule rests on."""
    if _config.is_subagent(data):
        return ("block", _CONFIG_DENY % (rel, tail))
    if _drive_started():
        return ("block", _CONFIG_DRIVE_DENY % (rel, tail))
    return ("ask", _CONFIG_ASK % (rel, tail))


def _decide_mcp(data, cfg):
    """The rules an MCP call can reach. Returns ("allow", reason), ("block", msg)
    or, for the main session's write of the audit config, ("ask", msg).

    THE SPLIT BETWEEN THE TWO HALVES IS WHERE THE TARGET LIVES, and the module
    docstring argues it rule by rule. Self-edit is decided on the target alone
    because its target set sits OUTSIDE the consuming repo; the bypass state, the
    journal and the audit config sit inside it, where refusing a read would be
    friction on honest work, so those wait for a write basis.

    NO VERDICT READS THE SERVER'S NAME OR AN ARGUMENT KEY. The locators are values
    resolved by `_config.mcp_payload`; the operation is used in the sentence only,
    to name the call back to whoever made it.
    """
    home = _config.tree_for(data, _config.PROJECT_ONLY, cfg)
    root, cfg = home["project"], home["cfg"]
    payload = _config.mcp_payload(data.get("tool_input", {}) or {})
    op = _config.mcp_operation(data.get("tool_name", "")) or "?"

    for loc in payload["locators"]:
        if _self_edit_target(loc, root):
            return ("block", _MCP_SELF_EDIT % (loc, op))

    basis = payload["writeBasis"]
    if basis is None:
        return ("allow", "mcp: nothing in the payload is evidence of a write")

    state_rel = str(cfg.get("stateDir")
                    or _config.DEFAULTS["stateDir"]).strip("/")
    for loc in payload["locators"]:
        tree = _config.tree_for(data, loc, cfg, project=root)
        rel = tree["rel"] if tree["inside"] else ""
        if rel:
            base = rel.rsplit("/", 1)[-1]
            if rel.startswith(state_rel + "/") \
                    and base.startswith("plan-bypass-"):
                return ("block", _MCP_BYPASS % (rel, basis, op))
            if _config.in_journal(tree["root"], cfg, loc):
                return ("block", _MCP_JOURNAL % (rel, basis, op))
        # Asked of a locator outside every tree too: a symlinked `.claude`
        # resolves out of the repository while the project still loads it.
        found = _config.audit_config_way(
            _config.config_question(tree, loc, data))
        if found:
            return _config_verdict(
                data, rel or loc, "\nThis call carries %s, which is what "
                "makes it a write; `%s` is the operation it asked for.%s"
                % (basis, op, _CASE_BLIND if found == "case-blind" else ""))
    return ("allow", "mcp: names no path this guard holds")


# --- decision -----------------------------------------------------------------
def decide(data, *, cfg=None):
    """Pure decision core. Returns ("allow", reason), ("block", message) or
    ("ask", message) - the last from rules 6 and 7 only."""
    tool = data.get("tool_name", "")
    if str(tool).startswith("mcp__"):
        return _decide_mcp(data, cfg)
    if tool not in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return ("allow", "unknown tool")

    path, text = collect(tool, data.get("tool_input", {}) or {})
    # The rules below hold files of the PLAN's tree - its journal, its bypass
    # state, its manifest - so the tree that holds `path` is the one asked: a
    # linked worktree's journal is as append-only as the project's own.
    tree = _config.tree_for(data, path or _config.PROJECT_ONLY, cfg)
    root, cfg = tree["project"], tree["cfg"]

    # path-based blocks first — they apply even to empty/whitespace content
    if path:
        # 3. self-edit protection
        if _self_edit_target(path, root):
            return ("block",
                    "The audit plugin's own files are read-only at runtime "
                    "(self-edit protection): %s\n"
                    "A model must not modify the hooks that govern it. To change "
                    "the plugin, edit it in its own repository checkout." % path)

        # 4. bypass forgery. A path outside every tree of this project holds
        #    none of what 4-6 protect, so it goes straight to the text rules.
        state_rel = str(cfg.get("stateDir")
                        or _config.DEFAULTS["stateDir"]).strip("/")
        rel = tree["rel"] if tree["inside"] else ""
        base = rel.rsplit("/", 1)[-1]
        if rel.startswith(state_rel + "/") and base.startswith("plan-bypass-"):
            return ("block",
                    "Writing the plan-first bypass state directly is not allowed "
                    "(bypass forgery): %s\n"
                    "A bypass may only be armed by the USER including the bypass "
                    "keyword in their prompt." % rel)

        # 5. the append-only audit trail
        if tree["inside"] and _config.in_journal(tree["root"], cfg, path):
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
                if _touches_state(tool, ti, path, tree["root"]):
                    return ("ask",
                            "journal.strictManifestState is \"ask\": this edit "
                            "changes task/phase state (status, completedAt, "
                            "commit or attempts) in %s -- confirm it is "
                            "intentional." % rel)

        # 7. the audit config: refused to a subagent and to a session the drive
        #    started, asked of the main session.
        #    The path alone decides, so an empty Write is held like any other,
        #    and it is asked of a path outside every tree too: a symlinked
        #    `.claude` resolves out of the repository while the project still
        #    loads its config through it.
        found = _config.audit_config_way(
            _config.config_question(tree, path, data))
        if found:
            return _config_verdict(
                data, rel or path, _CASE_BLIND if found == "case-blind" else "")

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
            # in `tests/test_guard_edits.py`, because four documents
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
    main()
