#!/usr/bin/env python3
"""
Plan-first enforcement — registered under BOTH PreToolUse and PostToolUse
(matcher: Edit|Write|MultiEdit|NotebookEdit).

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
    """
    def lines(text):
        s = str(text)
        return 0 if s == "" else len(s.splitlines())

    def char_lines(text):
        return (len(str(text)) + 199) // 200

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
_SUBAGENT_MANIFEST = (
    "%s is the audit plan, and the plan belongs to the orchestrator.\n"
    "You are a subagent: your job is one task, and a task that edits the plan it "
    "is being judged by is a task nobody can review. This is why the exemption "
    "that lets the ORCHESTRATOR write here does not extend to you.\n"
    "Do this: STOP, and tell the orchestrator what you need - a wider `files` "
    "scope, a status change, a new task. It owns those writes and will make them, "
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
    if tool not in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return ("allow", "unknown tool")

    if event is None:
        event = str(data.get("hook_event_name") or "PreToolUse")
    commit_state = event == "PostToolUse"

    ti = data.get("tool_input", {}) or {}
    file_path = ti.get("file_path", "") or ti.get("notebook_path", "")
    if not file_path:
        return ("allow", "no file_path")

    root = _config.repo_root(data)
    cfg = cfg if cfg is not None else _config.load(root)
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
    #     `agent_id` is present on a subagent's payload and absent on the main
    #     agent's, which is `guard-bash-writes`' probe. The orchestrator is
    #     untouched: it has no `agent_id`, so every branch below runs for it
    #     exactly as before.
    if str(data.get("agent_id") or "").strip() and (
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
    covering = None
    if rel in tmap:
        covering = rel
    elif (rel + "/") in tmap:
        covering = rel + "/"
    else:
        for f in tmap:
            if f.endswith("/") and rel.startswith(f):
                covering = f
                break
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
        "second distinct file in session"
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
        # THE PARAGRAPH IS SAID ONCE PER FILE PER SESSION (F355). The tier is
        # advisory, the sentence is correct, and it was being relayed VERBATIM
        # on every Edit of an uncovered file - a field report counted it on some
        # sixty files across several hundred edits in one afternoon, and this
        # repository's own maintainer read it a dozen times in a day. A nudge
        # that repeats on every edit is a nudge nobody reads, which is the
        # argument `_owner_note` already makes for its own throttle; this is the
        # same rule with the same state shape. What is throttled is the RELAY
        # TEXT alone: the gate event below is still appended on every edit, so
        # the log a later reader consults is complete, and the decision is
        # untouched. Pre reads the throttle and Post writes it, the same
        # transactional split every other piece of state here follows.
        warned = _warned_files(sd, session_id)
        repeat = rel in warned
        if commit_state:
            _config.append_gate_event(ld, {
                "event": "warn", "file": rel, "mode": "warn",
                "reason": reason, "sessionId": session_id})
            if not repeat:
                _record_warned(sd, session_id, warned + [rel])
        if repeat:
            return (
                "warn",
                "%s is still not covered by an in_progress task (%s) - said in "
                "full once already this session; the plan gate stays advisory."
                % (rel, reason),
            )
        return (
            "warn",
            "Tell the human this verbatim before continuing: "
            "%s is not covered by an in_progress task (%s).\n"
            "The plan gate is advisory until a phase is running: start one with "
            "/audit:next or /audit:phase, or add a task covering this file to %s."
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
    # A subagent's payload carries `agent_id` and the main agent's does not, which
    # is the probe `guard-bash-writes` already relies on.
    if str((data or {}).get("agent_id") or "").strip():
        return (
            "block",
            "Outside the running plan (%s): %s\n"
            "%s\n"
            "YOU ARE A SUBAGENT, so this one is not yours to resolve: the "
            "manifest belongs to the orchestrator, and widening a scope from "
            "inside a task is how a plan stops describing the work.\n"
            "Do this: STOP, and report to the orchestrator that %s is outside "
            "your task's `files` and why you need it. It will either widen the "
            "scope and tell you to carry on, or add a task for the work - "
            "either way you will not be re-spawned.\n"
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
            % (reason, rel, cause, rel),
        )
    return (
        "block",
        "Outside the running plan (%s): %s\n"
        "%s\n"
        "Two ways forward, weighed:\n"
        "  1. This is part of the work at hand -> add a task covering this "
        "file to %s (status \"in_progress\"). Preferred: the change lands in "
        "the plan, reviewed and recorded. If a subagent is running, widen its "
        "scope and message it to continue - do not re-spawn it.\n"
        "  2. This is genuinely a one-off -> the HUMAN types %s in their own "
        "prompt to opt out for one change. Agents cannot arm it; it is "
        "single-use, logged, and expires unused after %d minutes.\n"
        "Exempt regardless: %s, and the first single small (magnitude <= %d: "
        "lines added, chars/200, or lines removed - whichever is larger) "
        "non-exempt file per session."
        % (reason, rel, cause, manifest_rel, keyword,
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
