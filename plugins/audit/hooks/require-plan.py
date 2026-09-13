#!/usr/bin/env python3
"""
Plan-first enforcement — registered under BOTH PreToolUse and PostToolUse
(matcher: Edit|Write|MultiEdit|NotebookEdit, and mcp__.*).

AN MCP SERVER'S WRITE TOOL IS THE SAME WRITE. It reaches no edit-tool matcher, so
until it was wired here a filesystem server's `write_file` walked past this gate
while `Edit` of the same path was refused — the same disagreement `sed -i` had, in
the other direction. `_mcp_plan_target` resolves WHICH path such a call is decided
on and hands it to the ordinary decision below, so the verdict is not a second
implementation that can drift: an MCP write to a phase shard meets the subagent
refusal and the lock, an MCP write to a source file meets the gate's tier.
`_config.mcp_payload` says what counts as a write and states the direction it is
allowed to be wrong in (under-coverage, never a refused read).

Enforces a "Plan-first development" workflow: a non-trivial code change must be
planned via a task in the audit manifest and executed through /audit, OR opted out
for a single change with the bypass keyword (armed by detect-plan-skip.py).

This is the PLUGIN version — every project-specific value comes from the consuming
repo's `.claude/audit.config.json` (loaded by _config.py) with safe defaults:
  manifestPath, exemptGlobs, trivialLineThreshold, stateDir, logsDir, bypassKeyword.

Decision order (ALLOW = silent exit 0; BLOCK = permissionDecision "deny" JSON
on stdout + exit 0 — the canonical PreToolUse protocol — PreToolUse only;
ASK = permissionDecision "ask" when planGate pins that tier):
  1. No file_path / unknown tool / parse error → ALLOW (never break legit work).
  1b. Target is OUTSIDE the consuming repository → ALLOW, naming the scope. Out
     of scope is not "unknown": a manifest names paths in its own tree, so no
     plan could ever cover this one (_config.within_root).
  2. Target matches an exempt glob (from config) → ALLOW.
  3. Target belongs to a task whose status == "in_progress" in the manifest →
     ALLOW. On the PostToolUse pass a covered edit may additionally carry the
     ownership advisory (_owner_note): additionalContext, once per
     session+area, never a verdict.
  4. A single-use bypass is armed for this session (and not older than
     BYPASS_TTL_SECONDS via its armedAtEpoch; a legacy slot without the field
     has no TTL) → ALLOW.
  5. Trivial-edit allowance: the FIRST non-exempt code file in a session with
     change magnitude <= trivialLineThreshold → ALLOW. A 2nd distinct
     non-exempt file, or a change over the threshold → the gate's tier decides
     (observe/warn/ask/deny — _config.plan_gate_mode).

Every verdict past step 5 also drops one line into the gate events feed
(_config.append_gate_event → <logsDir>/plan-gate-events.jsonl): deny and
ask.shown on the Pre pass (a denial has no Post), everything else when the
edit actually happened.

"Change magnitude" is max(added lines, added chars / 200, removed lines) — a
single-line minified blob and a large deletion both count as large.

TRANSACTIONAL STATE (decide at PreToolUse, commit at PostToolUse):
  PreToolUse only OBSERVES state — it neither consumes the bypass nor records
  the free-file slot, because the edit may still be denied by a sibling hook
  (guard-edits) or by the user's permission prompt. PostToolUse — which fires
  only after the tool actually ran — CONSUMES the bypass (single-use, logged)
  and RECORDS the free-file slot. Accepted residual: several edits batched in
  one assistant message can ride one armed bypass ("single-use per tool batch"),
  and two files racing the single free slot are both allowed once — the second
  file blocks from its NEXT edit onward.

Contract: a block emits {"hookSpecificOutput": {"permissionDecision": "deny",
"permissionDecisionReason": ...}} on stdout and exits 0 (the deprecated exit-2 +
stderr channel is indistinguishable from a hook crash). PostToolUse always
exits 0 silently. Any unexpected input / exception exits 0.

This hook carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test_require_plan.py` (hyphens become underscores - a
hyphenated name is not importable). A test of a hook may import from `scripts/`
even though the hook itself may not; see `plugins/audit/tests/_harness.py`.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _config  # noqa: E402


# --- helpers (shared implementations live in _config.py) -----------------------
_rel_path = _config.rel_path
_matches_exempt = _config.matches_exempt
_strip_line_suffix = _config.strip_line_suffix


def _change_magnitude(tool, ti):
    """Effective size of a change, in 'lines'.

    max(added lines, added chars / 200, removed lines): line count alone lets a
    20k-char single-line blob or a 2000-line deletion pass as 'trivial'. The
    old content of a Write is unknowable from tool_input — documented residual.

    An MCP payload is measured off the longest string it carries
    (`_config.mcp_payload`'s `body`), because which key holds the bytes is the
    server author's vocabulary and not a contract. Same residual, one server over:
    what the target held BEFORE the call is not in the payload.
    """
    def lines(text):
        s = str(text)
        return 0 if s == "" else len(s.splitlines())

    def char_lines(text):
        return (len(str(text)) + 199) // 200

    if str(tool).startswith("mcp__"):
        body = _config.mcp_payload(ti).get("body") or ""
        return max(lines(body), char_lines(body))
    if tool == "Write":
        t = ti.get("content", "")
        return max(lines(t), char_lines(t))
    if tool == "Edit":
        new, old = ti.get("new_string", ""), ti.get("old_string", "")
        return max(lines(new), char_lines(new), lines(old))
    if tool == "MultiEdit":
        new_l = new_c = old_l = 0
        for e in ti.get("edits", []) or []:
            new, old = e.get("new_string", ""), e.get("old_string", "")
            new_l += lines(new)
            new_c += char_lines(new)
            old_l += lines(old)
        return max(new_l, new_c, old_l)
    if tool == "NotebookEdit":
        t = ti.get("new_source", "")
        return max(lines(t), char_lines(t))
    return 0


def _ensure_dir(p):
    # ensure_local_dir also drops the `*` .gitignore marker - every dir this
    # hook creates (state, logs) is local scratch that must not reach git.
    _config.ensure_local_dir(p)


def _append_log(logs, line):
    try:
        _ensure_dir(logs)
        with open(logs / "plan-bypass.log", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


# The only denial in this plugin that is not about the plan. It is about who is
# holding the pen: another session has this manifest's lock and is alive, so this
# write would land on top of theirs. Says the holder, what they are doing, the
# basis for calling them alive, and the one command that resolves it.
# What a SUBAGENT is told when it reaches for the plan itself (F262). Its own
# constant rather than a branch inside the refusal below, because this is a
# different refusal: the file is not out of scope, it is out of AUTHORITY, and the
# remedy is not a wider scope but a message to the orchestrator.
#
# AND IT NAMES THE COMMAND. "Tell the orchestrator what you need" left the reader
# to invent the request, and a refusal a subagent cannot act on without a human is
# the shape `_declaration_note` already paid for twice. The three writes it may ask
# for each have one verb, so the report can carry it: the orchestrator runs the
# command, the subagent quotes it. Named as the ROUTE to a state, the way
# `_declaration_note` names `/audit:task start` - a respelt verb leaves the
# sentence around it true.
_SUBAGENT_MANIFEST = (
    "%s is the audit plan, and the plan belongs to the orchestrator.\n"
    "You are a subagent: your job is one task, and a task that edits the plan it "
    "is being judged by is a task nobody can review. This is why the exemption "
    "that lets the ORCHESTRATOR write here does not extend to you.\n"
    "Do this: STOP, and tell the orchestrator what you need, naming the command "
    "it has to run - a wider scope is `/audit:task scope <taskId> --files ...`, "
    "an unstarted task is `/audit:task start <taskId>`, new work is "
    "`/audit:task add \"<title>\" --phase <phaseId>`. Those are ITS commands, not "
    "yours to run: they write the plan. It owns those writes and will make them, "
    "then tell you to carry on.\n"
    "If you reached for %s to get past a plan-gate refusal on a source file, that "
    "is the case this rule exists for: report the refusal instead."
)

_LOCK_DENY = (
    "%s is under the %s lock, held by another LIVE session (%s).\n"
    "  doing: %s\n"
    "  basis: %s\n"
    "Writing it now would overwrite their work with no conflict and no warning —\n"
    "one working tree, so git never sees two versions.\n"
    "Wait for that run, or check it with:\n"
    "  python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/governance/audit-lock.py\" status\n"
    "If you believe that session is gone, do NOT edit around this — take the lock\n"
    "over properly so the record says who holds it:\n"
    "  python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/governance/audit-lock.py\" acquire %s --takeover"
)

_LOCK_WARN = (
    "%s is under the %s lock, held by %s — a session that is no longer running\n"
    "(%s). Nothing is writing against you, so this edit is allowed. But the lock is\n"
    "still there and the takeover was never performed, so the next session will be\n"
    "told this phase is held by someone who has not been here for a while. Clear it:\n"
    "  python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/governance/audit-lock.py\" acquire %s --takeover"
)


def _deny_payload(msg):
    """Canonical PreToolUse deny payload (printed to stdout with exit 0)."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "[require-plan] " + msg,
        }
    }


def _ask_payload(msg):
    """Canonical PreToolUse ask payload — the planGate:"ask" channel (the same
    shape guard-edits' strict mode uses). Deliberately NOT deny: ask hands the
    decision to the human's own prompt, once per edit. The dialog itself cannot
    be driven by a selftest, so the payload SHAPE is the pinned contract."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": "[require-plan] " + msg,
        }
    }


def _warn_payload(msg):
    """Non-blocking advisory, delivered on the PostToolUse pass.

    Deliberately NOT a PreToolUse decision. There is no `permissionDecision:
    "allow"` path in this hook and there must not be one: emitting `allow` would
    auto-approve the tool call and skip the user's own permission prompt, so an
    advisory would silently widen what the agent may do. `additionalContext` on
    Post is the same channel remind-tdd and guard-bash-writes already use."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "[require-plan] " + msg,
        }
    }


def block(msg):
    print(json.dumps(_deny_payload(msg)))
    sys.exit(0)


def _record_observed(state_dir, session_id, rel, reason):
    """Append to the observe tally for this session.

    Named `plan-gate-observed-<sid>.json` so detect-plan-skip's existing GC sweeps
    it: `_GC_PREFIXES` already matches `plan-gate-`. Distinct from
    `plan-gate-<sid>.json`, which is the free-file slot."""
    try:
        path = state_dir / ("plan-gate-observed-%s.json" % session_id)
        seen = {"files": [], "notified": False}
        if path.exists():
            with open(path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh) or {}
            if isinstance(loaded, dict):
                seen["files"] = loaded.get("files", []) or []
                seen["notified"] = bool(loaded.get("notified"))
        if rel not in seen["files"]:
            seen["files"].append(rel)
        _ensure_dir(state_dir)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(seen, fh)
    except Exception:
        pass


def _owner_note(root, cfg, state_dir, session_id, rel,
                manifest_rel, entries):
    """The ownership advisory for a COVERED edit (v0.34 D2), or None — which is
    the answer almost always.

    `meta.areas[tag].owner` is advisory by design: this note is the only thing
    the hook does with it, it rides additionalContext on the Post pass, and it
    can never change a verdict. Silence costs nothing and is the default in
    every direction — no owner declared anywhere (the default-off: a manifest
    that never says `owner` never pays past the map already in hand), an
    explicit `owner: null` ("nobody owns this"), the author IS the owner, or
    authorMode "none" (a project that refuses attribution is not nudged with
    it). The gates run cheapest first so the one subprocess — resolving the
    author the way journal-writes and the usage ledger do, `git config` under
    usage.authorMode — is paid only when a real mismatch is still possible.

    A mismatch is said ONCE per session+area (`owner-note-<sid>.json`, a state
    file detect-plan-skip's GC prefixes sweep): the point is coordination, and
    a nudge that repeats on every edit is a nudge nobody reads. Never raises.
    """
    try:
        task_id = None
        for e in entries or []:
            tid = (e or {}).get("taskId")
            if tid:
                task_id = tid
                break
        if not task_id:
            return None
        # The phase comes from the ASSEMBLED manifest — under the sharded
        # layout the index stubs carry no `area`, and an id-prefix convention
        # ("P1.1 belongs to P1") is a naming accident, not a fact.
        manifest = _config._load_manifest_assembled(Path(root) / manifest_rel)
        if not isinstance(manifest, dict):
            return None
        phase = None
        for ph in manifest.get("phases") or []:
            if isinstance(ph, dict) and any(
                    isinstance(t, dict) and t.get("id") == task_id
                    for t in ph.get("tasks") or []):
                phase = ph
                break
        if phase is None:
            return None
        areas = _config._areas_lib()
        if areas is None or not hasattr(areas, "owner_of"):
            return None
        owner, tag = areas.owner_of(manifest, phase)
        if not owner:
            return None
        note_file = state_dir / ("owner-note-%s.json" % session_id)
        mentioned = []
        try:
            if note_file.exists():
                with open(note_file, "r", encoding="utf-8") as fh:
                    loaded = json.load(fh) or {}
                if isinstance(loaded, dict):
                    mentioned = [t for t in loaded.get("areas") or []
                                 if isinstance(t, str)]
        except Exception:
            mentioned = []
        if tag in mentioned:
            return None
        mod = _config._ledger_lib()
        if mod is None:
            return None
        mode = (_config.usage_cfg(cfg) or {}).get("authorMode") or "email"
        author = mod.resolve_author(str(root), mode)
        if not author or author == owner:
            return None
        try:
            _ensure_dir(state_dir)
            with open(note_file, "w", encoding="utf-8") as fh:
                json.dump({"areas": mentioned + [tag]}, fh)
        except Exception:
            pass
        return ("heads-up, not a gate: %s belongs to phase %s (area '%s'), "
                "whose owner is %s; you are recorded as %s. Fine to continue "
                "- coordination is the point, say so in the handoff."
                % (rel, phase.get("id") or "?", tag, owner, author))
    except Exception:
        return None


def _declaration_note(root, manifest_rel, rel, manifest_exists):
    """The refusal's second sentence and the remedy each audience gets, keyed on
    WHICH of the two causes actually holds:
    {"stated": <sentence>|None, "subagent": <clause>, "orchestrator": <clause>}.

    The refusal used to state one cause for both. It told a subagent the file was
    "outside your task's `files`" and told the main agent to add a task for it
    "(status \"in_progress\")" — sentences that are only true when NO task
    declares the file. When one does and is merely unstarted, the first is flatly
    false and the second sends the orchestrator to write a second task declaring
    a file the plan already covers. The gate had the fact and dropped it:
    `_config.in_progress_task_map` filters every other status away before
    `decide` ever looks, so nothing downstream could tell the two apart.

    The state, not the verb, is the load-bearing half of the unstarted remedy:
    `in_progress` is what opens a task's `files`, and the command is named as the
    route to it. Written that way because the route may be respelled and the
    state cannot be — a refusal naming a remedy its reader cannot reach is the
    fault this repo has already paid for twice.

    BOTH SUBAGENT CLAUSES NAME A COMMAND, on those same terms. The unstarted one
    always did; the undeclared one said "it will either widen the scope … or add a
    task" and left the reader to invent the request, which is a refusal a subagent
    cannot act on without a human standing over it. The verbs are the
    orchestrator's and the clause says so — a subagent quoting `/audit:task scope`
    into its report is the point; running it is what the manifest refusal above
    exists to stop.

    `stated` is None when there is no manifest at all: "no task declares this"
    would be true of an empty file, a missing one and a plan that never mentions
    the path, and only one of those is worth a reader's line. That branch is
    reachable only through planGate:"deny"/enforce:true, whose own cause sentence
    already says the refusal holds regardless of what the plan contains."""
    declared = (_config.declaring_tasks(root, manifest_rel, rel)
                if manifest_exists else [])
    if not declared:
        return {
            "stated": ("No task in %s declares %s - it is in no task's `files` "
                       "and in no `fileIndex` row." % (manifest_rel, rel)
                       if manifest_exists else None),
            "subagent": ("report to the orchestrator that %s is outside your "
                         "task's `files` and why you need it, naming the "
                         "command it has to run. It will either widen the scope "
                         "(`/audit:task scope <taskId> --files ...`) and tell "
                         "you to carry on, or add a task for the work "
                         "(`/audit:task add \"<title>\" --phase <phaseId>`) - "
                         "its commands, not yours" % rel),
            "orchestrator": ("add a task covering this file to %s (status "
                             "\"in_progress\")" % manifest_rel),
        }
    named = ", ".join(
        "%s (status \"%s\")" % (d.get("taskId") or "?", d.get("status") or "?")
        for d in declared)
    first = declared[0].get("taskId") or "?"
    return {
        "stated": ("%s IS declared by %s - a task's `files` open only while its "
                   "own status is \"in_progress\"." % (rel, named)),
        "subagent": ("report to the orchestrator that %s is already declared by "
                     "%s and that the task has not been started. What has to "
                     "change is that task's status, to \"in_progress\" - not "
                     "the `files` list - and starting the task "
                     "(`/audit:task start %s`) is the route"
                     % (rel, named, first)),
        "orchestrator": ("the task declaring it has not been started, so move "
                         "%s to status \"in_progress\" (`/audit:task start %s` "
                         "is the route). Do not add a second task for a file "
                         "the plan already declares" % (first, first)),
    }


def _warned_files(state_dir, session_id):
    """The uncovered files this session has already been told about in full.

    `plan-gate-warned-<sid>.json`, the `_owner_note` throttle's shape: a list
    under one key, read defensively, and a name that starts with `plan-gate-`
    so detect-plan-skip's GC sweeps it with the rest of the session state.
    Never raises - a throttle that could break the gate would be a gate that
    fails for saying something twice."""
    try:
        path = Path(state_dir) / ("plan-gate-warned-%s.json" % session_id)
        if not path.exists():
            return []
        with open(path, "r", encoding="utf-8") as fh:
            loaded = json.load(fh) or {}
        if not isinstance(loaded, dict):
            return []
        return [f for f in loaded.get("files") or [] if isinstance(f, str)]
    except Exception:
        return []


def _record_warned(state_dir, session_id, files):
    """Write the list `_warned_files` reads. Best-effort, like every state write
    here: a failed write means the paragraph is said again, which is the
    harmless direction."""
    try:
        _ensure_dir(Path(state_dir))
        path = Path(state_dir) / ("plan-gate-warned-%s.json" % session_id)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"files": list(files)}, fh)
    except Exception:
        pass


def _uncovered_tally(count):
    """`N uncovered file(s)` - the running total of DISTINCT uncovered files
    this session has been told about.

    The total is the length of the warned slot, which the warn tier already
    holds; rendering it here is what keeps the caller from printing a plural
    noun against a count that disagrees with it, because a repeat of the very
    first file reaches this with the smallest total there is.
    """
    return "%d uncovered file%s" % (count, "" if count == 1 else "s")


def _slot_reason(files_list):
    """Why an edit is out of policy once the session's free slot is spent, with
    the file that spent it named.

    This sentence used to be frozen at "second distinct file in session". The
    slot holds one file, every uncovered file after it took that same wording,
    and a long session's last uncovered file was still announced as the second
    - in the message the model was asked to relay and in the gate-events row a
    later reader consults. The slot always had the name; what was wrong was an
    ordinal nothing was counting. Read by every tier, so no tier is left
    holding the old claim.
    """
    return ("this session's one free file was already spent on %s"
            % ", ".join(files_list))


# --- which path an MCP write is decided on ------------------------------------
def _mcp_plan_target(ti, root, cfg):
    """(the path this gate decides on, why) for an MCP call — (None, reason) when
    it decides on nothing.

    THE TWO QUESTIONS THE SHELL HALF ASKS, IN ITS ORDER, because one file is
    promised one verdict however it is written. guard-secrets-read resolves a
    `sed -i` target by asking first whether it is the PLAN — the manifest, its
    lockfile, a phase shard, via `governing_lock` and never via an extension — and
    then whether it is a SOURCE file, via `source_exts`, which deliberately excludes
    `.json` so that no consumer's package.json is gated. An MCP payload names its
    paths in VALUES instead of in shell grammar; the two questions are unchanged,
    and asking them here is what keeps this from being a second gate that can drift
    from the first.

    NOTHING IS DECIDED WITHOUT A WRITE BASIS. `_config.mcp_payload` says what counts
    as one and why the test is sufficient rather than necessary; the consequence
    here is that a read naming a source file returns (None, ...) and this gate never
    sees it.

    A payload naming SEVERAL writable paths is decided on the first that is not
    already exempt, and the others reach this gate through nothing — under-coverage,
    named, and the same residual `_source_write_hit` carries for a command that
    writes two files.
    """
    payload = _config.mcp_payload(ti)
    if payload["writeBasis"] is None:
        return (None, "mcp: nothing in the payload is evidence of a write")
    manifest_rel = str(cfg.get("manifestPath")
                       or _config.DEFAULTS["manifestPath"])
    exempt = cfg.get("exemptGlobs") or _config.DEFAULTS["exemptGlobs"]
    exts = _config.source_exts(cfg)
    fallback = None
    for loc in payload["locators"]:
        rel = _rel_path(root, loc)
        if (rel == manifest_rel or rel == manifest_rel + ".lock"
                or _config.governing_lock(manifest_rel, rel)):
            return (loc, "mcp write of the plan: %s" % rel)
        low = loc.lower()
        if not any(low.endswith(e) for e in exts):
            continue
        if not _config.within_root(root, loc):
            continue
        if _matches_exempt(rel, exempt):
            fallback = fallback if fallback is not None else loc
            continue
        return (loc, "mcp write of a source file: %s" % rel)
    if fallback is not None:
        return (fallback, "mcp write of an exempt source file")
    return (None, "mcp: names no plan file and no source file in this repository")


# --- core decision ------------------------------------------------------------
def decide(data, *, cfg=None, state_dir=None, logs_dir=None,
           event=None):
    """Pure-ish decision core. Returns ("allow", reason) or ("block", message).

    `event` selects the transactional side: "PreToolUse" (default) is read-only
    on state; "PostToolUse" commits state (consumes the bypass / records the
    free-file slot). `cfg`/`state_dir`/`logs_dir` override real values
    (used by --selftest).
    """
    tool = data.get("tool_name", "")
    is_mcp = str(tool).startswith("mcp__")
    if not is_mcp and tool not in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return ("allow", "unknown tool")

    if event is None:
        event = str(data.get("hook_event_name") or "PreToolUse")
    commit_state = event == "PostToolUse"

    ti = data.get("tool_input", {}) or {}
    root = _config.repo_root(data)
    cfg = cfg if cfg is not None else _config.load(root)
    if is_mcp:
        # The config has to be loaded before the target can be resolved: which
        # paths are the plan and which extensions are source both come out of it.
        # An edit tool keeps its cheaper order below.
        file_path, why = _mcp_plan_target(ti, root, cfg)
        if file_path is None:
            return ("allow", why)
    else:
        file_path = ti.get("file_path", "") or ti.get("notebook_path", "")
        if not file_path:
            return ("allow", "no file_path")
    threshold = int(cfg.get("trivialLineThreshold") or 80)
    manifest_rel = cfg.get("manifestPath") or "docs/audit/audit-plan.json"
    exempt = cfg.get("exemptGlobs") or []
    sd = state_dir if state_dir is not None else _config.state_dir(root, cfg)
    ld = logs_dir if logs_dir is not None else _config.logs_dir(root, cfg)
    rel = _rel_path(root, file_path)

    # 1b. OUT OF SCOPE IS NOT UNPLANNED. `rel` is os.path.relpath, so a file
    #     outside the consuming repository arrives here as
    #     `../../../private/tmp/probe.py` - an ordinary string every step below
    #     reads as repo source. Reported live: a helper script written to the
    #     system temp directory during a read-only /audit:sync status was
    #     refused for want of plan coverage no plan could ever have given it,
    #     because a manifest can only name paths in its own tree.
    #
    #     ALLOW, and say which scope. A file outside the repo is not "unknown",
    #     which is what the fail-open paths above are for; it is none of this
    #     gate's business, and the difference is worth printing - a silent pass
    #     here would be the same verdict with the reason thrown away. Placed
    #     before every step that follows because all of them are questions
    #     about a repo-relative path, the manifest clause included: nothing
    #     outside the tree can be the manifest, cover a task, or spend the
    #     session's one trivial-file slot.
    if not _config.within_root(root, file_path):
        return ("allow",
                "outside the repository at %s: %s" % (root, file_path))

    # 2a. the manifest itself, its lockfile and its phase shards ARE the plan —
    #     never gated, even when a custom manifestPath falls outside the exempt
    #     globs.
    #
    #     The shard clause is not decoration. In the sharded layout the
    #     orchestrator writes `<manifest dir>/phases/<phaseId>.json` on every
    #     bookkeeping step — task status, attempts, the commit SHA, the outcome —
    #     and exact equality with `manifestPath` does not match those. At the
    #     DEFAULT path it worked anyway, by accident: `docs/audit/**` is an exempt
    #     glob and swallows the shards. At a custom path there is no such glob, so
    #     the gate denied the orchestrator its own writes — and only AFTER phase
    #     entry set `status: in_progress`, which is what flips the gate to deny.
    #     A phase run therefore died one step into itself, on exactly the layout
    #     `/audit:migrate` produces.
    #
    #     Scoped to `<dir>/phases/*.json` rather than the manifest's directory:
    #     a manifest at the repo root (`"manifestPath": "plan.json"`) would make
    #     that directory `.` and hand every file in the repo a permanent bypass.
    #
    #     Exempt from the PLAN gate is not the same as unconditionally writable.
    #     A manifest write is checked against the concurrency lock instead — see
    #     step 2a-ii.
    # 2a-0. THE PLAN IS THE ORCHESTRATOR'S, AND THE EXEMPTION SAID OTHERWISE
    #     (F262). `agents/audit-executor.md` puts the manifest with the
    #     orchestrator, and this gate exempted it from everybody — so a subagent
    #     refused a source file could, and did, widen its own scope instead:
    #     measured on a live run, four tasks out of five took that route because
    #     it was the only door left open. The contract and the guard have to agree,
    #     and the guard is the half that can be checked.
    #
    #     `_config.is_subagent` is the one place that question is asked; the probe
    #     behind it is recorded there. The orchestrator is untouched: it is not a
    #     subagent, so every branch below runs for it exactly as before.
    if _config.is_subagent(data) and (
            rel == manifest_rel or rel == manifest_rel + ".lock"
            or _config.governing_lock(manifest_rel, rel)):
        return ("block", _SUBAGENT_MANIFEST % (rel, rel))

    if rel == manifest_rel or rel == manifest_rel + ".lock" or (
            _config.governing_lock(manifest_rel, rel)):
        # 2a-ii. The lock, enforced. audit-lock.py can tell a live holder from an
        #     abandoned one, but a verdict nothing consults is advice — the
        #     orchestrator takes the lock in prose, so a session that ignored an
        #     exit 3 was stopped by nothing and its writes landed on top of the
        #     winner's. This is where the exit code becomes binding.
        #
        #     Only a LIVE holder denies. An abandoned lock means nobody is writing
        #     against you, so blocking would add friction after a crash and protect
        #     nothing — it is surfaced on the Post pass instead. Everything
        #     unattributable (no lock, no sessionId in it, no git, no lock module)
        #     allows: an unattributable lock must never be able to deny.
        conflict = _config.manifest_lock_conflict(
            root, cfg, manifest_rel, rel, str(data.get("session_id", "") or ""))
        if conflict and conflict["live"]:
            return ("block", _LOCK_DENY % (
                rel, conflict["lock"], conflict["holder"], conflict["note"],
                conflict["basis"], conflict["lock"]))
        if conflict:
            return ("warn", _LOCK_WARN % (
                rel, conflict["lock"], conflict["holder"], conflict["basis"],
                conflict["lock"]))
        if rel == manifest_rel or rel == manifest_rel + ".lock":
            return ("allow", "manifest/lock path: %s" % rel)
        return ("allow", "phase shard of the manifest: %s" % rel)

    # 2b. exempt globs
    if _matches_exempt(rel, exempt):
        return ("allow", "exempt path: %s" % rel)

    session_id = str(data.get("session_id", "") or "no-session")

    # 3. covered by an in_progress task (exact match OR directory prefix match).
    #    A covered edit is allowed on every tier — but on the Post pass it may
    #    still carry the ownership advisory (_owner_note): when the area this
    #    task belongs to declares an `owner` who is not the recorded author, a
    #    one-per-session-per-area heads-up rides additionalContext. Advisory
    #    only: the verdict never hardens past "warn", and no gate event is
    #    written — this is coordination, not a gate verdict.
    tmap = _config.in_progress_task_map(root, manifest_rel)
    covering = _config.covering_key(tmap, rel)
    if covering is not None:
        if commit_state:
            note = _owner_note(root, cfg, sd, session_id, rel, manifest_rel,
                               tmap.get(covering))
            if note:
                return ("warn", note)
        return ("allow", "covered by in_progress task: %s" % rel)

    # 4. single-use bypass — observed at Pre, consumed at Post. An armed slot
    #    expires unused after BYPASS_TTL_SECONDS (via `armedAtEpoch`, written by
    #    detect-plan-skip): older than that, it is treated as never armed — the
    #    Pre pass falls through to the gate, and the Post pass deletes the slot
    #    and logs the expiry. A legacy slot WITHOUT the field is honoured with
    #    no TTL (fail-open; the 7-day state GC still sweeps it).
    bypass_file = sd / ("plan-bypass-%s.json" % session_id)
    try:
        if bypass_file.exists():
            expired = False
            try:
                with open(bypass_file, "r", encoding="utf-8") as fh:
                    info = json.load(fh) or {}
                armed_at = (info.get("armedAtEpoch")
                            if isinstance(info, dict) else None)
                if (isinstance(armed_at, (int, float))
                        and not isinstance(armed_at, bool)
                        and time.time() - armed_at
                        > _config.BYPASS_TTL_SECONDS):
                    expired = True
            except Exception:
                pass       # unreadable = legacy shape: honoured without TTL
            if expired:
                if commit_state:
                    try:
                        bypass_file.unlink()
                    except Exception:
                        pass
                    _append_log(
                        ld,
                        "%s session=%s bypass expired unused (armed more than "
                        "%d minutes ago)"
                        % (_now_iso(), session_id,
                           _config.BYPASS_TTL_SECONDS // 60),
                    )
                    _config.append_gate_event(ld, {
                        "event": "bypass.expired", "file": rel,
                        "reason": "expired unused", "sessionId": session_id})
                # fall through: an expired bypass is not armed
            elif not commit_state:
                return ("allow", "bypass armed: %s" % rel)
            else:
                try:
                    bypass_file.unlink()
                except Exception:
                    pass
                _append_log(
                    ld,
                    "%s session=%s consumed by successful edit of %s"
                    % (_now_iso(), session_id, rel),
                )
                _config.append_gate_event(ld, {
                    "event": "bypass.consumed", "file": rel, "mode": "allow",
                    "reason": "single-use bypass consumed",
                    "sessionId": session_id})
                return ("allow", "bypass consumed: %s" % rel)
    except Exception:
        pass

    # 5. trivial-edit allowance (per-session state; recorded at Post)
    gate_file = sd / ("plan-gate-%s.json" % session_id)
    files_list = []
    try:
        if gate_file.exists():
            with open(gate_file, "r", encoding="utf-8") as fh:
                files_list = (json.load(fh) or {}).get("files", []) or []
    except Exception:
        files_list = []

    if rel in files_list:
        return ("allow", "already being worked: %s" % rel)

    magnitude = _change_magnitude(tool, ti)

    if len(files_list) == 0 and magnitude <= threshold:
        if commit_state:
            files_list.append(rel)
            try:
                _ensure_dir(sd)
                with open(gate_file, "w", encoding="utf-8") as fh:
                    json.dump({"files": files_list}, fh)
            except Exception:
                pass
            _config.append_gate_event(ld, {
                "event": "allow.trivial", "file": rel, "mode": "allow",
                "reason": "first small file (magnitude %d)" % magnitude,
                "sessionId": session_id})
            return ("allow",
                    "recorded first trivial code file (magnitude %d): %s"
                    % (magnitude, rel))
        return ("allow",
                "first trivial code file (magnitude %d): %s" % (magnitude, rel))

    reason = (
        _slot_reason(files_list)
        if len(files_list) > 0
        else "change magnitude %d (> %d)" % (magnitude, threshold)
    )
    keyword = cfg.get("bypassKeyword") or _config.DEFAULTS["bypassKeyword"]

    # 6. This edit is out of policy. HOW LOUDLY to say so depends on how much the
    #    gate actually knows — see _config.plan_gate_mode. Everything above this
    #    point is unchanged by grading: an exempt file, a covered file or a first
    #    small file is allowed on every tier.
    state = _config.manifest_state(root, manifest_rel)
    mode = _config.plan_gate_mode(cfg, state)

    if mode == "observe":
        # Record what would have been blocked, so the next prompt can say so once.
        # This is the tier where the plugin has no plan to check against, so a deny
        # would be a decision made on no evidence.
        if commit_state:
            _record_observed(sd, session_id, rel, reason)
            _config.append_gate_event(ld, {
                "event": "observe", "file": rel, "mode": "observe",
                "reason": reason, "sessionId": session_id})
        return ("observe", "would have blocked (%s): %s" % (reason, rel))

    if mode == "warn":
        # THE PARAGRAPH IS SAID ONCE PER SESSION. The tier is advisory and the
        # sentence is correct, but the whole explanation was being relayed for
        # every uncovered file: a field session met a long run of distinct
        # files and read the same three lines for each of them, and an earlier
        # report counted the pre-throttle version across an afternoon's edits.
        # WHICH TIER THIS IS AND THE TWO ROUTES FORWARD ARE PROPERTIES OF THE
        # SESSION, not of the file - only the name and the running total change
        # from one file to the next - so the first uncovered file carries the
        # paragraph and every later one carries a line. A nudge that repeats is
        # a nudge nobody reads, which is the argument `_owner_note` already
        # makes for its own throttle; this is the same rule with the same state
        # shape. What is throttled is the RELAY TEXT alone: the gate event
        # below is still appended on every edit, so the log a later reader
        # consults is complete, and the decision is untouched. Pre reads the
        # throttle and Post writes it, the same transactional split every other
        # piece of state here follows.
        #
        # AND THE RELAY DEMAND DROPS "before continuing". This verdict reaches
        # a human only through main()'s PostToolUse branch - Pre prints nothing
        # for a warn - so the edit is on disk before the sentence can be read.
        # Asking for the relay "before continuing" named a moment that had
        # already gone; the paragraph says what is actually true instead.
        #
        # IT STAYS A WARNING, AND THAT IS THE DECISION. The same report asked
        # for the opposite ending: after enough uncovered edits with no phase
        # running, stop entirely and say so once. That is silence with a
        # counter in front of it. Field reports have named this tier as the
        # thing that got a phase started, and the same reporter credits a
        # sibling guard's notice with changing how he works - an operator
        # learns about the next uncovered file from the line beside the edit,
        # not from a tally nobody opens. So the repair is VOLUME, not silence.
        # `plugins/audit/tests/test_require_plan.py` holds that as a case: a
        # mutation letting this branch fall quiet once the session has already
        # warned turns it red, so the choice is kept by a check rather than by
        # this comment.
        warned = _warned_files(sd, session_id)
        repeat = rel in warned
        tally = len(warned) if repeat else len(warned) + 1
        if commit_state:
            _config.append_gate_event(ld, {
                "event": "warn", "file": rel, "mode": "warn",
                "reason": reason, "sessionId": session_id})
            if not repeat:
                _record_warned(sd, session_id, warned + [rel])
        if warned:
            return (
                "warn",
                "%s is not covered by an in_progress task (%s) - %s this "
                "session, said in full once already; the plan gate stays "
                "advisory."
                % (rel, reason, _uncovered_tally(tally)),
            )
        return (
            "warn",
            "Tell the human this verbatim: "
            "%s is not covered by an in_progress task (%s). The edit has "
            "already been made - this tier does not stop anything.\n"
            "The plan gate is advisory until a phase is running: start one with "
            "/audit:next or /audit:phase, or add a task covering this file to %s.\n"
            "Further uncovered files this session add one line each, naming the "
            "file and the running total - this paragraph is said once."
            % (rel, reason, manifest_rel),
        )

    if mode == "ask":
        # planGate:"ask" — every out-of-plan edit is handed to the human's own
        # permission prompt, once per edit (consistent with strictManifestState:
        # nothing is remembered, so approving one edit approves ONE edit).
        # main() prints the ask payload on Pre; on Post the edit having happened
        # IS the approval, so it stays silent — the ask.approved event is the
        # approval's only durable trace.
        _config.append_gate_event(ld, {
            "event": "ask.approved" if commit_state else "ask.shown",
            "file": rel, "mode": "ask", "reason": reason,
            "sessionId": session_id})
        return (
            "ask",
            "%s is not covered by an in_progress task (%s).\n"
            "planGate is set to \"ask\" in .claude/audit.config.json, so each "
            "edit outside the plan waits for your approval - approving covers "
            "this one edit. To stop being asked, add a task covering this file "
            "to %s, or set planGate to another tier."
            % (rel, reason, manifest_rel),
        )

    # The deny names its ACTUAL cause (F-F4): "a phase is in_progress" was
    # printed even when the denial came from enforce:true in an empty repo —
    # a flatly false sentence, shipped because nothing pinned the text.
    knob = _config.plan_gate_knob(cfg)
    if knob == "deny":
        cause = ("planGate is set to \"deny\" in .claude/audit.config.json - "
                 "refused regardless of what is running.")
    elif _config.enforce_always(cfg):
        cause = ("enforce: true is set in .claude/audit.config.json (legacy; "
                 "planGate: \"deny\" says the same) - refused regardless of "
                 "what is running.")
    else:
        cause = ("Phase %s is in_progress, so edits are held to the plan."
                 % (state.get("runningPhase") or "?"))
    if not commit_state:
        # Pre only: after a denial there is no Post pass to record anything.
        _config.append_gate_event(ld, {
            "event": "deny", "file": rel, "mode": "deny", "reason": reason,
            "sessionId": session_id})
    # WHICH of the two causes, named. This reads a SECOND, read-only map
    # (`_config.declaring_tasks`) that the verdict above never consults: the
    # decision is still `in_progress` coverage alone, so nothing here can widen
    # what the gate allows — a task the plan has not started opens no file, and
    # saying which task it is does not start it.
    note = _declaration_note(root, manifest_rel, rel, state.get("exists"))
    head = "Outside the running plan (%s): %s\n%s\n" % (reason, rel, cause)
    if note["stated"]:
        head += note["stated"] + "\n"
    # THE REMEDY BRANCHES BY AUDIENCE, and it did not (F251, F262). The old text
    # told every reader to "add a task covering this file to <manifest>" — but a
    # subagent may not edit the manifest (`agents/audit-executor.md` puts it with
    # the orchestrator) and has no channel to the human, so the one line addressed
    # to it sent it into an action it is forbidden to take. Measured: one executor
    # stopped and asked the operator which of two things IT should do, and across
    # another run the same refusal produced three different resolutions — content
    # put in the wrong module, work reverted for a worse UX, and four tasks where
    # the agent edited the manifest itself because `docs/audit/**` is exempt.
    #
    # `_config.is_subagent` is the one place that question is asked, and the probe
    # behind it is recorded there.
    if _config.is_subagent(data):
        return (
            "block",
            "%s"
            "YOU ARE A SUBAGENT, so this one is not yours to resolve: the "
            "manifest belongs to the orchestrator, and widening a scope from "
            "inside a task is how a plan stops describing the work.\n"
            "Do this: STOP, and %s - either way you will not be re-spawned.\n"
            # F284. THIS USED TO PROMISE THE WIDENING FLATLY, and at sign-off
            # that promise was false. `_config.in_progress_task_map` reads only
            # `in_progress` tasks, and sign-off runs when every task is `done` -
            # so nothing is covered there, and no widening of a finished task
            # changes that (F283's widening settles an index; it does not open an
            # edit). A live run spent three fix-run subagents finding that out.
            # A refusal that names a remedy the reader cannot reach is worse than
            # one that names none: it sends them to spend the spawn twice.

            "Do NOT: edit the manifest yourself (it is exempt from this gate, "
            "which does not make it yours), put the change somewhere it does "
            "not belong to dodge the refusal, or abandon work you have already "
            "done. All three have happened, and each was worse than stopping."
            % (head, note["subagent"]),
        )
    return (
        "block",
        "%s"
        "Two ways forward, weighed:\n"
        "  1. This is part of the work at hand -> %s. Preferred: the change "
        "lands in the plan, reviewed and recorded. If a subagent is running, "
        "widen its scope and message it to continue - do not re-spawn it.\n"
        "  2. This is genuinely a one-off -> the HUMAN types %s in their own "
        "prompt to opt out for one change. Agents cannot arm it; it is "
        "single-use, logged, and expires unused after %d minutes.\n"
        "Exempt regardless: %s, and the first single small (magnitude <= %d: "
        "lines added, chars/200, or lines removed - whichever is larger) "
        "non-exempt file per session."
        % (head, note["orchestrator"], keyword,
           _config.BYPASS_TTL_SECONDS // 60, ", ".join(exempt), threshold),
    )


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    event = str(data.get("hook_event_name") or "PreToolUse")
    try:
        verdict, msg = decide(data, event=event)
    except Exception:
        sys.exit(0)

    # PostToolUse cannot block — the edit already happened. It carries the two
    # non-blocking channels instead: the observe tally was written inside decide(),
    # and a warn is surfaced here as context.
    if event == "PostToolUse":
        if verdict == "warn":
            print(json.dumps(_warn_payload(msg)))
        sys.exit(0)

    if verdict == "block":
        block(msg)
    if verdict == "ask":
        print(json.dumps(_ask_payload(msg)))
        sys.exit(0)
    # observe and warn never gate on Pre. Printing nothing keeps the user's normal
    # permission prompt intact.
    sys.exit(0)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        # Answered rather than fallen through to main(), which would block on stdin
        # waiting for a hook payload that is never coming. It deliberately does NOT
        # print the `N/M cases passed` contract - that string is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("require-plan.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_require_plan.py - run that file instead.")
        sys.exit(0)
    main()
