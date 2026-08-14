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

Run `python3 require-plan.py --selftest` to exercise the core decision function.
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


def _change_magnitude(tool: str, ti: dict) -> int:
    """Effective size of a change, in 'lines'.

    max(added lines, added chars / 200, removed lines): line count alone lets a
    20k-char single-line blob or a 2000-line deletion pass as 'trivial'. The
    old content of a Write is unknowable from tool_input — documented residual.
    """
    def lines(text) -> int:
        s = str(text)
        return 0 if s == "" else len(s.splitlines())

    def char_lines(text) -> int:
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


def _ensure_dir(p: Path) -> None:
    # ensure_local_dir also drops the `*` .gitignore marker - every dir this
    # hook creates (state, logs) is local scratch that must not reach git.
    _config.ensure_local_dir(p)


def _append_log(logs: Path, line: str) -> None:
    try:
        _ensure_dir(logs)
        with open(logs / "plan-bypass.log", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


# The only denial in this plugin that is not about the plan. It is about who is
# holding the pen: another session has this manifest's lock and is alive, so this
# write would land on top of theirs. Says the holder, what they are doing, the
# basis for calling them alive, and the one command that resolves it.
_LOCK_DENY = (
    "%s is under the %s lock, held by another LIVE session (%s).\n"
    "  doing: %s\n"
    "  basis: %s\n"
    "Writing it now would overwrite their work with no conflict and no warning —\n"
    "one working tree, so git never sees two versions.\n"
    "Wait for that run, or check it with:\n"
    "  python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/audit-lock.py\" status\n"
    "If you believe that session is gone, do NOT edit around this — take the lock\n"
    "over properly so the record says who holds it:\n"
    "  python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/audit-lock.py\" acquire %s --takeover"
)

_LOCK_WARN = (
    "%s is under the %s lock, held by %s — a session that is no longer running\n"
    "(%s). Nothing is writing against you, so this edit is allowed. But the lock is\n"
    "still there and the takeover was never performed, so the next session will be\n"
    "told this phase is held by someone who has not been here for a while. Clear it:\n"
    "  python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/audit-lock.py\" acquire %s --takeover"
)


def _deny_payload(msg: str) -> dict:
    """Canonical PreToolUse deny payload (printed to stdout with exit 0)."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "[require-plan] " + msg,
        }
    }


def _ask_payload(msg: str) -> dict:
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


def _warn_payload(msg: str) -> dict:
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


def block(msg: str) -> None:
    print(json.dumps(_deny_payload(msg)))
    sys.exit(0)


def _record_observed(state_dir: Path, session_id: str, rel: str, reason: str) -> None:
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


def _owner_note(root, cfg, state_dir: Path, session_id: str, rel: str,
                manifest_rel: str, entries) -> str:
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


# --- core decision ------------------------------------------------------------
def decide(data: dict, *, cfg=None, state_dir: Path = None, logs_dir: Path = None,
           event: str = None):
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
        if commit_state:
            _config.append_gate_event(ld, {
                "event": "warn", "file": rel, "mode": "warn",
                "reason": reason, "sessionId": session_id})
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
    return (
        "block",
        "Outside the running plan (%s): %s\n"
        "%s\n"
        "Two ways forward, weighed:\n"
        "  1. This is part of the work at hand -> add a task covering this "
        "file to %s (status \"in_progress\"). Preferred: the change lands in "
        "the plan, reviewed and recorded.\n"
        "  2. This is genuinely a one-off -> the HUMAN types %s in their own "
        "prompt to opt out for one change. Agents cannot arm it; it is "
        "single-use, logged, and expires unused after %d minutes.\n"
        "If you are an agent reading this: ask the human which they want - do "
        "not recommend the bypass.\n"
        "Exempt regardless: %s, and the first single small (magnitude <= %d: "
        "lines added, chars/200, or lines removed - whichever is larger) "
        "non-exempt file per session."
        % (reason, rel, cause, manifest_rel, keyword,
           _config.BYPASS_TTL_SECONDS // 60, ", ".join(exempt), threshold),
    )


def main() -> None:
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


# --- selftest -----------------------------------------------------------------
def _selftest() -> int:
    import platform
    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="require-plan-selftest-"))
    sd = tmp / "state"
    ld = tmp / "logs"
    sd.mkdir(parents=True, exist_ok=True)
    ld.mkdir(parents=True, exist_ok=True)
    cfg = dict(_config.DEFAULTS)  # generic defaults, no project specifics

    # Pin the project dir. `decide` resolves the root via _config.repo_root, which
    # prefers CLAUDE_PROJECT_DIR over the payload's cwd — so run inside a real
    # session this suite was reading THIS repository's manifest. That was harmless
    # while the verdict ignored the manifest; now that its existence selects the
    # tier, an unpinned run would grade against whatever repo happens to be open.
    _prev_project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = str(tmp)

    # Most cases below predate evidence grading and assert the fully-enforced
    # behaviour, so they run with enforce:true. The tiers themselves are exercised
    # by group (k), against real manifest fixtures.
    cfg["enforce"] = True

    def write_manifest(obj):
        """Write a manifest at the default manifestPath inside the temp project."""
        d = tmp / "docs" / "audit"
        d.mkdir(parents=True, exist_ok=True)
        (d / "audit-plan.json").write_text(json.dumps(obj), encoding="utf-8")

    def clear_manifest():
        shutil.rmtree(tmp / "docs", ignore_errors=True)

    session = "selftest-session-1"
    big = "\n".join("line %d" % i for i in range(120))  # 120 lines > 80

    def payload(tool, file_path, *, new_string=None, old_string=None,
                content=None, edits=None, new_source=None, sid=session):
        ti = {}
        if tool == "NotebookEdit":
            ti["notebook_path"] = file_path
        else:
            ti["file_path"] = file_path
        if content is not None:
            ti["content"] = content
        if new_string is not None:
            ti["new_string"] = new_string
        if old_string is not None:
            ti["old_string"] = old_string
        if edits is not None:
            ti["edits"] = edits
        if new_source is not None:
            ti["new_source"] = new_source
        return {"tool_name": tool, "tool_input": ti, "session_id": sid,
                "cwd": str(tmp)}

    results = []

    def check(name, expected, data, *, event="PreToolUse"):
        try:
            verdict, _ = decide(data, cfg=cfg, state_dir=sd, logs_dir=ld,
                                event=event)
        except Exception as exc:  # pragma: no cover
            verdict = "EXC:%s" % exc
        ok = verdict == expected
        results.append(ok)
        print("%s %s (expected %s, got %s)"
              % ("PASS" if ok else "FAIL", name, expected, verdict))

    # (a) exempt paths → allow
    check("a1 .md file", "allow", payload("Write", "README.md", content="hi"))
    check("a2 manifest json (docs/audit/**)", "allow",
          payload("Write", "docs/audit/x.json", content="{}"))
    check("a3 *.spec.ts", "allow",
          payload("Write", "src/foo/bar.spec.ts", content="test('x',()=>{})"))

    # (q) A1 (v0.36): a build config named like a test is NOT a test file. With
    # the gate enforced, `tsconfig.test.json` used to ride the `**/*.test.*`
    # exemption straight through; a real test file keeps it.
    check("q1 tsconfig.test.json is gated - config, not a test", "block",
          payload("Edit", "tsconfig.test.json", new_string=big,
                  sid="selftest-session-q1"))
    check("q2 a real test file stays exempt", "allow",
          payload("Edit", "src/foo/cart.test.ts", new_string=big,
                  sid="selftest-session-q1"))

    # (a4-a6) the manifest + its lock are never gated, even with a custom
    # manifestPath OUTSIDE the exempt globs
    cfg_custom = dict(cfg)
    cfg_custom["manifestPath"] = "planning/plan.json"

    def check_custom(name, expected, data):
        try:
            verdict, _ = decide(data, cfg=cfg_custom, state_dir=sd, logs_dir=ld)
        except Exception as exc:  # pragma: no cover
            verdict = "EXC:%s" % exc
        ok = verdict == expected
        results.append(ok)
        print("%s %s (expected %s, got %s)"
              % ("PASS" if ok else "FAIL", name, expected, verdict))

    check_custom("a4 custom-path manifest edit allowed", "allow",
                 payload("Edit", "planning/plan.json", new_string=big,
                         sid="selftest-session-a4"))
    check_custom("a5 custom-path lockfile allowed", "allow",
                 payload("Write", "planning/plan.json.lock", content="{}",
                         sid="selftest-session-a4"))
    # a5b-a5d: the SHARDS of a custom-path manifest. The orchestrator writes
    # `<manifest dir>/phases/<phaseId>.json` on every bookkeeping step, and exact
    # equality with manifestPath does not match those. At the default path it
    # worked by accident — `docs/audit/**` swallows the shards — so a phase run on
    # a custom sharded path died one step in, right after phase entry set
    # `in_progress` and flipped the gate to deny. Found by running the pipeline in
    # a sandbox whose manifest was not at the default path.
    check_custom("a5b custom-path phase shard allowed", "allow",
                 payload("Edit", "planning/phases/P1.json", new_string=big,
                         sid="selftest-session-a5b"))
    check_custom("a5c custom-path bugfix shard allowed", "allow",
                 payload("Edit", "planning/phases/BF1.json", new_string=big,
                         sid="selftest-session-a5c"))
    # Scoped to phases/*.json, NOT to the manifest's directory: a manifest at the
    # repo root would make that directory `.` and bypass the gate for everything.
    check_custom("a5d a non-shard file beside the manifest is still gated", "block",
                 payload("Edit", "planning/notes.json", new_string=big,
                         sid="selftest-session-a5d"))
    check_custom("a5e a non-JSON file inside phases/ is still gated", "block",
                 payload("Edit", "planning/phases/notes.txt", new_string=big,
                         sid="selftest-session-a5e"))
    check_custom("a6 sibling file still gated", "block",
                 payload("Write", "planning/other.json", content=big,
                         sid="selftest-session-a6"))

    # (lk) The concurrency lock, ENFORCED. Everything above decides whether an edit
    # is in the plan; this decides whether this session is the one holding the pen.
    # It is the only denial here that is not about the plan, so it gets pinned in
    # both directions and on every fail-open path — an unattributable lock that
    # could deny would brick legitimate work in a plugin that fails open by design.
    import subprocess as _sp
    _git = shutil.which("git")
    if not _git:
        print("SKIP lk* (git is not on PATH)")
    else:
        lkroot = Path(tempfile.mkdtemp(prefix="require-plan-lock-"))
        _sp.run([_git, "init", "-q", str(lkroot)], check=True,
                stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        (lkroot / "audit" / "phases").mkdir(parents=True, exist_ok=True)
        # From DEFAULTS, not from `cfg` — earlier cases mutate that dict (enforce),
        # and the lock check must be pinned independently of whichever plan tier
        # happens to be in force when this block runs.
        lkcfg = dict(_config.DEFAULTS)
        lkcfg["manifestPath"] = "audit/plan.json"
        lockdir = Path(_config._load_lock_lib().lock_dir(str(lkroot)))
        lockdir.mkdir(parents=True, exist_ok=True)

        def put_lock(name, **fields):
            info = {"hostname": platform.node(), "startedAt": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "note": "phase run"}
            info.update(fields)
            with open(lockdir / (name + ".lock"), "w", encoding="utf-8") as fh:
                json.dump(info, fh)

        def lkok(name, cond):
            # This suite's `check` runs a payload; these are plain assertions
            # about the text of a refusal, which is the part a human acts on.
            results.append(bool(cond))
            print("%s %s" % ("PASS" if cond else "FAIL", name))

        def lk(name, expected, rel, sid, event="PreToolUse"):
            data = payload("Edit", str(lkroot / rel), new_string=big, sid=sid)
            data["cwd"] = str(lkroot)
            data["hook_event_name"] = event
            got, msg = decide(data, cfg=lkcfg, state_dir=sd, logs_dir=ld, event=event)
            ok = got == expected
            results.append(ok)
            print("%s %s (expected %s, got %s)"
                  % ("PASS" if ok else "FAIL", name, expected, got))
            return msg

        _prev_lk = os.environ.get("CLAUDE_PROJECT_DIR")
        os.environ["CLAUDE_PROJECT_DIR"] = str(lkroot)
        try:
            lk("lk0 no lock at all -> the shard is writable", "allow",
               "audit/phases/P1.json", "sess-B")

            # A live holder. os.getpid() is a pid that is certainly running.
            put_lock("phase-P1", sessionId="sess-A", pid=os.getpid())
            msg = lk("lk1 another LIVE session's phase lock denies the shard", "block",
                     "audit/phases/P1.json", "sess-B")
            lkok("lk1b the denial names the holder", "sess-A" in msg)
            lkok("lk1c and the basis for calling it live", "is running on this host" in msg)
            lkok("lk1d and the one command that resolves it",
                  "audit-lock.py\" acquire phase-P1 --takeover" in msg)
            lk("lk2 the holder itself still writes freely", "allow",
               "audit/phases/P1.json", "sess-A")
            lk("lk3 a lock on P1 says nothing about P2", "allow",
               "audit/phases/P2.json", "sess-B")
            lk("lk4 nor about the index", "allow", "audit/plan.json", "sess-B")

            # An abandoned holder is not a denial case: nobody is writing against
            # you, so blocking would add friction after a crash and protect nothing.
            dead = _sp.Popen([sys.executable, "-c", "pass"]); dead.wait()
            put_lock("phase-P1", sessionId="sess-A", pid=dead.pid)
            msg = lk("lk5 an ABANDONED holder warns instead of denying", "warn",
                     "audit/phases/P1.json", "sess-B")
            lkok("lk5b the warning still says the lock is there",
                  "no longer running" in msg and "--takeover" in msg)

            # Fail-open paths. Each of these must allow, and each is a different
            # reason the lock cannot be attributed to anyone.
            put_lock("phase-P1", pid=os.getpid())
            lk("lk6 a lock with no sessionId can never deny", "allow",
               "audit/phases/P1.json", "sess-B")
            put_lock("phase-P1", sessionId="sess-A", pid=os.getpid())
            lk("lk7 nor can it deny a session with no id of its own", "allow",
               "audit/phases/P1.json", "")
            with open(lockdir / "phase-P1.lock", "w", encoding="utf-8") as fh:
                fh.write("{not json")
            lk("lk8 an unreadable lock allows", "allow",
               "audit/phases/P1.json", "sess-B")

            # The index tier, and the boundary: a lock governs manifest paths only.
            os.unlink(lockdir / "phase-P1.lock")
            put_lock("index", sessionId="sess-A", pid=os.getpid())
            msg = lk("lk9 a live index lock denies an index write", "block",
                     "audit/plan.json", "sess-B")
            lkok("lk9b and names the index tier", "index lock" in msg)
            lk("lk10 but not a shard write", "allow", "audit/phases/P1.json", "sess-B")
            msg = lk("lk11 an ordinary source file is untouched by the lock",
                     "observe", "src/other.py", "sess-B")
            # Not `"lock" not in msg`: "blocked" contains "lock". Assert on the
            # phrases the lock verdict actually uses.
            lkok("lk11b and its verdict talks about the plan, never the lock",
                 "would have blocked" in msg
                 and "under the" not in msg and "audit-lock.py" not in msg)

            # Post cannot deny; main() is what enforces that, so pin it there.
            put_lock("phase-P1", sessionId="sess-A", pid=os.getpid())
            lk("lk12 the verdict is the same on the Post pass", "block",
               "audit/phases/P1.json", "sess-B", event="PostToolUse")
            lkok("lk12b but main() prints no deny payload on Post",
                  "PostToolUse" in _warn_payload("x")["hookSpecificOutput"]["hookEventName"])
        finally:
            if _prev_lk is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = _prev_lk
            shutil.rmtree(lkroot, ignore_errors=True)

    # (b) transactional slot: Pre allows but does NOT record; the matching Post
    #     records; only then does a second distinct file block.
    sess_b = "selftest-session-b"
    p_first = payload("Write", "src/foo/a.ts", content="export const a = 1;",
                      sid=sess_b)
    check("b1 first small file (Pre) allowed", "allow", p_first)
    gate = sd / ("plan-gate-%s.json" % sess_b)
    results.append(not gate.exists())
    print("%s b2 Pre did NOT record the slot" % ("PASS" if not gate.exists() else "FAIL"))
    check("b3 second small file BEFORE any Post still allowed", "allow",
          payload("Write", "src/foo/b.ts", content="export const b = 2;", sid=sess_b))
    check("b4 Post records the slot", "allow", p_first, event="PostToolUse")
    results.append(gate.exists())
    print("%s b5 Post recorded the slot" % ("PASS" if gate.exists() else "FAIL"))
    check("b6 second distinct file after Post blocks", "block",
          payload("Write", "src/foo/b.ts", content="export const b = 2;", sid=sess_b))
    check("b7 same first file again allowed", "allow", p_first)

    # (c) magnitude: many lines, single-line blob, deletion-heavy edit
    check("c1 large new file blocks", "block",
          payload("Write", "src/foo/huge.ts", content=big, sid="selftest-session-c"))
    check("c2 single-line 20k-char blob blocks", "block",
          payload("Write", "src/foo/min.js", content="x" * 20000,
                  sid="selftest-session-c2"))
    check("c3 deletion-heavy edit blocks", "block",
          payload("Edit", "src/foo/mod.ts", new_string="// removed",
                  old_string=big + big, sid="selftest-session-c3"))
    check("c4 big NotebookEdit blocks", "block",
          payload("NotebookEdit", "notebooks/train.ipynb", new_source=big,
                  sid="selftest-session-c4"))
    check("c5 small NotebookEdit is the free slot", "allow",
          payload("NotebookEdit", "notebooks/train.ipynb", new_source="print(1)",
                  sid="selftest-session-c5"))

    # (d) with no in_progress task (empty tmp manifest), an uncovered file blocks
    check("d1 uncovered file blocks", "block",
          payload("Edit", "src/example/module.ts", new_string=big,
                  sid="selftest-session-d"))

    # (e) armed bypass: Pre observes without consuming; Post consumes + logs
    sess_e = "selftest-session-e"
    bp = sd / ("plan-bypass-%s.json" % sess_e)
    bp.write_text(json.dumps({"ts": _now_iso(), "reason": "selftest"}),
                  encoding="utf-8")
    p_bypass = payload("Write", "src/foo/bypassed.ts", content=big, sid=sess_e)
    check("e1 armed bypass (Pre) allows", "allow", p_bypass)
    results.append(bp.exists())
    print("%s e2 Pre left the bypass armed" % ("PASS" if bp.exists() else "FAIL"))
    check("e3 Post consumes the bypass", "allow", p_bypass, event="PostToolUse")
    consumed = not bp.exists()
    results.append(consumed)
    print("%s e4 bypass consumed (single-use)" % ("PASS" if consumed else "FAIL"))

    # (f) bypass consumption writes to the provided logs_dir
    log_file = ld / "plan-bypass.log"
    wrote = log_file.exists() and "session=%s" % sess_e in log_file.read_text(
        encoding="utf-8")
    results.append(wrote)
    print("%s f1 bypass logged to provided logs_dir" % ("PASS" if wrote else "FAIL"))

    # (j) deny payload is canonical PreToolUse JSON
    blob = json.loads(json.dumps(_deny_payload("why")))
    hso = blob.get("hookSpecificOutput") or {}
    ok = (hso.get("hookEventName") == "PreToolUse"
          and hso.get("permissionDecision") == "deny"
          and str(hso.get("permissionDecisionReason", "")).startswith("[require-plan]"))
    results.append(ok)
    print("%s j1 deny payload is canonical PreToolUse JSON" % ("PASS" if ok else "FAIL"))

    # (k) evidence grading. Same out-of-policy edit at each tier; only the amount
    #     the gate knows changes. cfg_graded drops the enforce override the rest of
    #     this suite uses.
    cfg_graded = dict(cfg)
    cfg_graded["enforce"] = False

    def check_graded(name, expected, data, *, event="PreToolUse"):
        try:
            verdict, _ = decide(data, cfg=cfg_graded, state_dir=sd, logs_dir=ld,
                                event=event)
        except Exception as exc:  # pragma: no cover
            verdict = "EXC:%s" % exc
        ok = verdict == expected
        results.append(ok)
        print("%s %s (expected %s, got %s)"
              % ("PASS" if ok else "FAIL", name, expected, verdict))

    def offending(sid):
        return payload("Edit", "src/graded/mod.ts", new_string=big, sid=sid)

    clear_manifest()
    check_graded("k1 no manifest -> observe, never block", "observe",
                 offending("selftest-k1"))

    write_manifest({"meta": {"version": 2}, "phases": [
        {"id": "P1", "title": "p", "status": "done",
         "tasks": [{"id": "P1.1", "title": "t", "status": "done"}]}]})
    check_graded("k2 manifest present, nothing running -> warn", "warn",
                 offending("selftest-k2"))

    write_manifest({"meta": {"version": 2}, "phases": [
        {"id": "P1", "title": "p", "status": "in_progress",
         "tasks": [{"id": "P1.1", "title": "t", "status": "pending"}]}]})
    check_graded("k3 manifest + running phase -> block", "block",
                 offending("selftest-k3"))

    # A covered file is allowed on the strictest tier — grading changes only the
    # verdict for edits that were already out of policy.
    write_manifest({"meta": {"version": 2}, "phases": [
        {"id": "P1", "title": "p", "status": "in_progress", "tasks": [
            {"id": "P1.1", "title": "t", "status": "in_progress",
             "files": ["src/graded/covered.ts"]}]}]})
    check_graded("k4 a covered file is allowed even at the deny tier", "allow",
                 payload("Edit", "src/graded/covered.ts", new_string=big,
                         sid="selftest-k4"))
    check_graded("k5 an exempt glob is allowed at the deny tier", "allow",
                 payload("Write", "README.md", content=big, sid="selftest-k5"))

    # The free small-file slot survives grading, on every tier.
    clear_manifest()
    check_graded("k6 a first small file is still allowed under observe", "allow",
                 payload("Write", "src/graded/small.ts", content="const a = 1;",
                         sid="selftest-k6"))

    # Observe records at Post so the next prompt can report it once; Pre does not.
    clear_manifest()
    obs_sid = "selftest-k7"
    obs_file = sd / ("plan-gate-observed-%s.json" % obs_sid)
    check_graded("k7 observe on Pre writes no tally", "observe",
                 offending(obs_sid))
    ok = not obs_file.exists()
    results.append(ok)
    print("%s k8 Pre leaves the observe tally unwritten" % ("PASS" if ok else "FAIL"))
    check_graded("k9 observe on Post still observes", "observe",
                 offending(obs_sid), event="PostToolUse")
    try:
        tally = json.loads(obs_file.read_text(encoding="utf-8"))
    except Exception:
        tally = {}
    ok = tally.get("files") == ["src/graded/mod.ts"]
    results.append(ok)
    print("%s k10 Post records the file in the observe tally (%r)"
          % ("PASS" if ok else "FAIL", tally.get("files")))

    # The tally name has to fall under the existing GC prefixes or it leaks forever.
    ok = obs_file.name.startswith("plan-gate-")
    results.append(ok)
    print("%s k11 the tally filename is swept by detect-plan-skip's GC prefixes"
          % ("PASS" if ok else "FAIL"))
    ok = obs_file.name != ("plan-gate-%s.json" % obs_sid)
    results.append(ok)
    print("%s k12 the tally does not collide with the free-file slot"
          % ("PASS" if ok else "FAIL"))

    # enforce:true restores the pre-0.20 behaviour on the weakest evidence.
    check_graded("k13 enforce:false with no manifest observes", "observe",
                 offending("selftest-k13"))
    cfg_enforced = dict(cfg_graded)
    cfg_enforced["enforce"] = True
    try:
        verdict, _ = decide(offending("selftest-k14"), cfg=cfg_enforced,
                            state_dir=sd, logs_dir=ld)
    except Exception as exc:  # pragma: no cover
        verdict = "EXC:%s" % exc
    ok = verdict == "block"
    results.append(ok)
    print("%s k14 enforce:true blocks with no manifest at all (expected block, got %s)"
          % ("PASS" if ok else "FAIL", verdict))

    # The warn payload must not be a permissionDecision — emitting `allow` would
    # auto-approve the tool call and bypass the user's own prompt.
    wp = json.loads(json.dumps(_warn_payload("why")))
    hso = wp.get("hookSpecificOutput") or {}
    ok = ("permissionDecision" not in hso
          and hso.get("hookEventName") == "PostToolUse"
          and str(hso.get("additionalContext", "")).startswith("[require-plan]"))
    results.append(ok)
    print("%s k15 warn is additionalContext on Post, never a permissionDecision"
          % ("PASS" if ok else "FAIL"))

    # (g) the planGate knob, and the ask tier (v0.34 B1). Everything above
    # step 6 is untouched by pinning a tier: an exempt file, a covered file and
    # the first small file are allowed on EVERY tier, ask included (the k4/k5
    # rule, re-proven under the knob).
    def check_knob(name, expected, data, *, use_cfg, event="PreToolUse"):
        try:
            verdict, _ = decide(data, cfg=use_cfg, state_dir=sd, logs_dir=ld,
                                event=event)
        except Exception as exc:  # pragma: no cover
            verdict = "EXC:%s" % exc
        ok = verdict == expected
        results.append(ok)
        print("%s %s (expected %s, got %s)"
              % ("PASS" if ok else "FAIL", name, expected, verdict))

    cfg_ask = dict(cfg_graded)
    cfg_ask["planGate"] = "ask"
    clear_manifest()
    check_knob("g1 planGate:'ask' turns an out-of-policy edit into ask", "ask",
               offending("selftest-g1"), use_cfg=cfg_ask)
    check_knob("g2 an exempt file is allowed at the ask tier", "allow",
               payload("Write", "README.md", content=big, sid="selftest-g2"),
               use_cfg=cfg_ask)
    write_manifest({"meta": {"version": 2}, "phases": [
        {"id": "P1", "title": "p", "status": "in_progress", "tasks": [
            {"id": "P1.1", "title": "t", "status": "in_progress",
             "files": ["src/graded/covered.ts"]}]}]})
    check_knob("g3 a covered file is allowed at the ask tier", "allow",
               payload("Edit", "src/graded/covered.ts", new_string=big,
                       sid="selftest-g3"), use_cfg=cfg_ask)
    clear_manifest()
    check_knob("g4 the first small file is still free under ask", "allow",
               payload("Write", "src/graded/small.ts", content="const a=1;",
                       sid="selftest-g4"), use_cfg=cfg_ask)
    cfg_pin_deny = dict(cfg_graded)
    cfg_pin_deny["planGate"] = "deny"
    check_knob("g5 planGate:'deny' blocks with no manifest at all", "block",
               offending("selftest-g5"), use_cfg=cfg_pin_deny)
    write_manifest({"meta": {"version": 2}, "phases": [
        {"id": "P1", "title": "p", "status": "in_progress",
         "tasks": [{"id": "P1.1", "title": "t", "status": "pending"}]}]})
    cfg_pin_obs = dict(cfg_graded)
    cfg_pin_obs["planGate"] = "observe"
    check_knob("g6 planGate:'observe' observes even while a phase runs", "observe",
               offending("selftest-g6"), use_cfg=cfg_pin_obs)
    cfg_both = dict(cfg_graded)
    cfg_both.update(planGate="observe", enforce=True)
    check_knob("g7 planGate beats enforce when both are set", "observe",
               offending("selftest-g7"), use_cfg=cfg_both)
    check_knob("g8 ask is the verdict on the Post pass too - main() is what "
               "turns it into silence (the edit happened = the human approved)",
               "ask", offending("selftest-g8"), use_cfg=cfg_ask,
               event="PostToolUse")
    clear_manifest()

    # The ask payload's SHAPE is the pinned contract - the dialog itself cannot
    # be driven by a selftest (mirror of j1 and k15).
    ap = json.loads(json.dumps(_ask_payload("why")))
    hso = ap.get("hookSpecificOutput") or {}
    ok = (hso.get("hookEventName") == "PreToolUse"
          and hso.get("permissionDecision") == "ask"
          and str(hso.get("permissionDecisionReason", "")).startswith(
              "[require-plan]"))
    results.append(ok)
    print("%s g9 the ask payload is a canonical PreToolUse 'ask' decision"
          % ("PASS" if ok else "FAIL"))

    # main() routing: Pre prints the ask payload; Post prints nothing (silence
    # is the approval record - the gate event feed carries the trace).
    import io as _io
    gproj = Path(tempfile.mkdtemp(prefix="require-plan-ask-"))
    (gproj / ".claude").mkdir(parents=True, exist_ok=True)
    (gproj / ".claude" / "audit.config.json").write_text(
        json.dumps({"planGate": "ask"}), encoding="utf-8")

    def drive_main(event):
        _stdin, _stdout = sys.stdin, sys.stdout
        cap = _io.StringIO()
        code = None
        _prev = os.environ.get("CLAUDE_PROJECT_DIR")
        try:
            sys.stdin = _io.StringIO(json.dumps(
                {"tool_name": "Edit", "session_id": "ask-main",
                 "hook_event_name": event,
                 "tool_input": {"file_path": "src/asked.ts", "new_string": big},
                 "cwd": str(gproj)}))
            sys.stdout = cap
            os.environ["CLAUDE_PROJECT_DIR"] = str(gproj)
            try:
                main()
            except SystemExit as exc:
                code = exc.code
        finally:
            sys.stdin, sys.stdout = _stdin, _stdout
            if _prev is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = _prev
        return code, cap.getvalue()

    code, spoke = drive_main("PreToolUse")
    try:
        blob = json.loads(spoke) if spoke.strip() else {}
    except Exception:
        blob = {}
    ok = (code in (0, None) and (blob.get("hookSpecificOutput") or {})
          .get("permissionDecision") == "ask")
    results.append(ok)
    print("%s g10 main() on Pre prints the ask payload and exits 0"
          % ("PASS" if ok else "FAIL"))
    code, spoke = drive_main("PostToolUse")
    ok = code in (0, None) and spoke == ""
    results.append(ok)
    print("%s g11 main() on Post prints NOTHING for ask - the edit happening "
          "IS the approval" % ("PASS" if ok else "FAIL"))
    shutil.rmtree(gproj, ignore_errors=True)

    # (h) what a refusal SAYS, by actual cause (F-F4), and the bypass TTL (B4).
    # The deny used to claim "A phase is in_progress" whether or not one was -
    # enforce:true with an empty repo produced a sentence that was flatly false,
    # and nothing pinned the text, which is how the bug shipped.
    def deny_msg(use_cfg, sid):
        try:
            return decide(offending(sid), cfg=use_cfg, state_dir=sd,
                          logs_dir=ld)
        except Exception as exc:  # pragma: no cover
            return ("EXC", str(exc))

    def hok(name, cond, detail=""):
        results.append(bool(cond))
        print("%s %s%s" % ("PASS" if cond else "FAIL", name,
                           (" (%s)" % detail) if detail and not cond else ""))

    clear_manifest()
    cfg_leg = dict(cfg_graded)
    cfg_leg["enforce"] = True
    v, m = deny_msg(cfg_leg, "selftest-h1")
    hok("h1 enforce:true with NO phase running blames the config, not a "
        "phantom phase",
        v == "block" and "enforce: true" in m and "legacy" in m
        and "A phase is in_progress" not in m, repr(m))
    cfg_pin = dict(cfg_graded)
    cfg_pin["planGate"] = "deny"
    v, m = deny_msg(cfg_pin, "selftest-h2")
    hok("h2 planGate:'deny' names the knob and says it holds regardless of "
        "what is running",
        v == "block" and 'planGate is set to "deny"' in m
        and "regardless of what is running" in m, repr(m))
    write_manifest({"meta": {"version": 2}, "phases": [
        {"id": "P3", "title": "p", "status": "in_progress",
         "tasks": [{"id": "P3.1", "title": "t", "status": "pending"}]}]})
    v, m = deny_msg(cfg_graded, "selftest-h3")
    hok("h3 a real running phase is NAMED - 'phase P3', not 'a phase'",
        v == "block" and "Phase P3 is in_progress" in m, repr(m))
    hok("h4 the refusal tells an agent to ask the human and NOT to recommend "
        "the bypass",
        "ask the human" in m and "do not recommend the bypass" in m, repr(m))
    hok("h5 ...and states the bypass facts: the HUMAN types it, single-use, "
        "logged, 30-minute expiry",
        "HUMAN" in m and "single-use" in m and "30 minutes" in m
        and "Agents cannot arm it" in m, repr(m))
    clear_manifest()

    # The TTL itself (require-plan's half: honouring it). Armed slots carry
    # armedAtEpoch (written by detect-plan-skip); older than the TTL = never
    # armed, deleted + logged on the Post pass; a legacy slot without the
    # field is honoured WITHOUT a TTL.
    sess_h = "selftest-h-ttl"
    bp_h = sd / ("plan-bypass-%s.json" % sess_h)
    p_ttl = payload("Write", "src/ttl/big.ts", content=big, sid=sess_h)
    bp_h.write_text(json.dumps({"ts": _now_iso(), "reason": "fresh",
                                "armedAtEpoch": int(time.time())}),
                    encoding="utf-8")
    v, _m = decide(p_ttl, cfg=cfg, state_dir=sd, logs_dir=ld)
    hok("h6 a fresh armed bypass still allows on Pre", v == "allow")
    stale_epoch = int(time.time()) - _config.BYPASS_TTL_SECONDS - 120
    bp_h.write_text(json.dumps({"ts": _now_iso(), "reason": "stale",
                                "armedAtEpoch": stale_epoch}),
                    encoding="utf-8")
    v, _m = decide(p_ttl, cfg=cfg, state_dir=sd, logs_dir=ld)
    hok("h7 an EXPIRED bypass does not arm - the edit is gated as if none "
        "existed (Pre leaves the file for Post to clean)",
        v == "block" and bp_h.exists(), repr(v))
    v, _m = decide(p_ttl, cfg=cfg, state_dir=sd, logs_dir=ld,
                   event="PostToolUse")
    log_txt = ((ld / "plan-bypass.log").read_text(encoding="utf-8")
               if (ld / "plan-bypass.log").exists() else "")
    hok("h8 the Post pass deletes the expired slot and logs 'expired unused'",
        v == "block" and not bp_h.exists()
        and "expired unused" in log_txt, repr((v, bp_h.exists())))
    bp_h.write_text(json.dumps({"ts": _now_iso(), "reason": "legacy"}),
                    encoding="utf-8")
    v, _m = decide(p_ttl, cfg=cfg, state_dir=sd, logs_dir=ld)
    hok("h9 a legacy slot without armedAtEpoch is honoured WITHOUT a TTL "
        "(fail-open; the 7-day GC still sweeps it)", v == "allow")
    try:
        bp_h.unlink()
    except Exception:
        pass

    # (i) the gate events feed (v0.34 B3). Verdicts used to leave NO trace -
    # only the bypass had a log - so each branch now drops one compact line
    # into <logsDir>/plan-gate-events.jsonl. Pre records only what has no Post
    # (deny, ask.shown); everything else lands when the edit actually happened.
    def feed(p):
        f = p / _config.GATE_EVENTS_FILE
        if not f.exists():
            return []
        return [json.loads(line) for line in
                f.read_text(encoding="utf-8").splitlines() if line.strip()]

    clear_manifest()
    ild = tmp / "ev-observe"
    decide(offending("selftest-i1"), cfg=cfg_graded, state_dir=sd, logs_dir=ild)
    hok("i1 observe on Pre leaves no event - Pre records only deny/ask.shown",
        feed(ild) == [], repr(feed(ild)))
    decide(offending("selftest-i1"), cfg=cfg_graded, state_dir=sd, logs_dir=ild,
           event="PostToolUse")
    rows = feed(ild)
    hok("i2 observe on Post leaves ONE observe event naming file and session",
        len(rows) == 1 and rows[0].get("event") == "observe"
        and rows[0].get("file") == "src/graded/mod.ts"
        and rows[0].get("sessionId") == "selftest-i1", repr(rows))
    ild = tmp / "ev-deny"
    v, _m = decide(offending("selftest-i3"), cfg=cfg_pin, state_dir=sd,
                   logs_dir=ild)
    rows = feed(ild)
    hok("i3 a deny is recorded on Pre - there is no Post after a denial",
        v == "block" and len(rows) == 1 and rows[0].get("event") == "deny"
        and rows[0].get("mode") == "deny", repr(rows))
    ild = tmp / "ev-ask"
    decide(offending("selftest-i4"), cfg=cfg_ask, state_dir=sd, logs_dir=ild)
    decide(offending("selftest-i4"), cfg=cfg_ask, state_dir=sd, logs_dir=ild,
           event="PostToolUse")
    rows = feed(ild)
    hok("i4 ask leaves ask.shown on Pre and ask.approved on Post - the "
        "approval's only durable trace",
        [r.get("event") for r in rows] == ["ask.shown", "ask.approved"],
        repr(rows))
    ild = tmp / "ev-warn"
    write_manifest({"meta": {"version": 2}, "phases": [
        {"id": "P1", "title": "p", "status": "done",
         "tasks": [{"id": "P1.1", "title": "t", "status": "done"}]}]})
    v, m = decide(offending("selftest-i5"), cfg=cfg_graded, state_dir=sd,
                  logs_dir=ild, event="PostToolUse")
    rows = feed(ild)
    hok("i5 warn on Post leaves a warn event",
        v == "warn" and [r.get("event") for r in rows] == ["warn"], repr(rows))
    hok("i6 the warn text LEADS with the relay instruction - the cheap half "
        "of visibility, the feed is the durable half",
        m.startswith("Tell the human this verbatim before continuing"),
        repr(m[:80]))
    clear_manifest()
    ild = tmp / "ev-bypass"
    sess_i = "selftest-i7"
    bp_i = sd / ("plan-bypass-%s.json" % sess_i)
    bp_i.write_text(json.dumps({"ts": _now_iso(), "reason": "x",
                                "armedAtEpoch": int(time.time())}),
                    encoding="utf-8")
    p_i = payload("Write", "src/ev/i7.ts", content=big, sid=sess_i)
    decide(p_i, cfg=cfg, state_dir=sd, logs_dir=ild, event="PostToolUse")
    rows = feed(ild)
    hok("i7 a consumed bypass is bypass.consumed",
        [r.get("event") for r in rows] == ["bypass.consumed"], repr(rows))
    bp_i.write_text(json.dumps({"ts": _now_iso(), "reason": "x",
                                "armedAtEpoch": stale_epoch}), encoding="utf-8")
    decide(p_i, cfg=cfg, state_dir=sd, logs_dir=ild, event="PostToolUse")
    rows = feed(ild)
    hok("i8 an expired one is bypass.expired",
        rows and rows[-1].get("event") == "bypass.expired", repr(rows))
    ild = tmp / "ev-trivial"
    decide(payload("Write", "src/ev/small.ts", content="const a=1;",
                   sid="selftest-i9"), cfg=cfg_graded, state_dir=sd,
           logs_dir=ild, event="PostToolUse")
    rows = feed(ild)
    hok("i9 the recorded first small file is allow.trivial - the free slot is "
        "part of the gate's story too",
        [r.get("event") for r in rows] == ["allow.trivial"], repr(rows))
    ild = tmp / "ev-quiet"
    decide(payload("Write", "README.md", content=big, sid="selftest-i10"),
           cfg=cfg_graded, state_dir=sd, logs_dir=ild, event="PostToolUse")
    hok("i10 an exempt path leaves no feed line - the feed is verdicts, not "
        "an access log", feed(ild) == [])

    # (o) the ownership advisory on the covered path (v0.34 D2). Advisory by
    # construction: it rides additionalContext on the Post pass, never a
    # permissionDecision — Pre never speaks, no tier can turn it into a block,
    # and silence is the default in every direction (no owner declared
    # anywhere, explicit null, author matches, authorMode none). The git
    # subprocess behind the author is paid only past every cheaper gate, which
    # the call counter below pins.
    _ledmod = _config._ledger_lib()
    _orig_resolve = getattr(_ledmod, "resolve_author", None) if _ledmod else None
    _calls = {"n": 0}

    def _fake_resolve(_root, mode="email"):
        _calls["n"] += 1
        return None if mode == "none" else "sam@x.com"

    def ocheck(name, cond, detail=""):
        results.append(bool(cond))
        print("%s %s%s" % ("PASS" if cond else "FAIL", name,
                           (" (%s)" % detail) if detail and not cond else ""))

    if _ledmod is None:
        print("SKIP o* (usage_ledger module unavailable)")
    else:
        _ledmod.resolve_author = _fake_resolve
        try:
            def own_phase(pid, area, files):
                return {"id": pid, "title": "p", "status": "in_progress",
                        "area": area,
                        "tasks": [{"id": pid + ".1", "title": "t",
                                   "status": "in_progress", "files": files}]}

            write_manifest({"meta": {"version": 2, "areas": {
                "api": {"root": "services/api", "owner": "jane@x.com"},
                "web": {"root": "apps/web", "owner": "sam@x.com"},
                "lib": {"root": "lib", "owner": None},
                "sec": {"root": "sec", "owner": "raj@x.com"}}},
                "phases": [
                    own_phase("P1", "api", ["src/own/a.ts", "src/own/a2.ts"]),
                    own_phase("P2", "web", ["src/own/b.ts"]),
                    own_phase("P3", "lib", ["src/own/c.ts"]),
                    own_phase("P4", "sec", ["src/own/d.ts"])]})
            sess_o = "selftest-own-1"
            overdicts = []

            def own(file, sid=sess_o, event="PreToolUse", use_cfg=None):
                v, m = decide(payload("Edit", file, new_string=big, sid=sid),
                              cfg=use_cfg if use_cfg is not None else cfg_graded,
                              state_dir=sd, logs_dir=ld, event=event)
                overdicts.append(v)
                return v, m

            v, m = own("src/own/a.ts")
            ocheck("o1 Pre never speaks: a covered file with a mismatched owner "
                   "is a plain allow, and the author subprocess is never paid",
                   v == "allow" and _calls["n"] == 0, repr((v, _calls["n"])))
            v, m = own("src/own/a.ts", event="PostToolUse")
            ocheck("o2 Post on a mismatch is a warn with the measured wording - "
                   "heads-up, phase, area, owner, author, fine to continue",
                   v == "warn" and m.startswith("heads-up, not a gate:")
                   and "src/own/a.ts belongs to phase P1 (area 'api')" in m
                   and "whose owner is jane@x.com" in m
                   and "you are recorded as sam@x.com" in m
                   and "Fine to continue" in m
                   and "say so in the handoff" in m, repr((v, m)))
            note_file = sd / ("owner-note-%s.json" % sess_o)
            ocheck("o3 the throttle slot exists and its name starts with "
                   "'owner-note-' - the prefix detect-plan-skip's GC sweeps",
                   note_file.exists()
                   and note_file.name.startswith("owner-note-"),
                   repr(note_file))
            v, m = own("src/own/a2.ts", event="PostToolUse")
            ocheck("o4 the same session+area warns ONCE - a second covered edit "
                   "in the same area stays quiet",
                   v == "allow", repr((v, m)))
            v, m = own("src/own/d.ts", event="PostToolUse")
            ocheck("o5 a DIFFERENT area in the same session warns again - the "
                   "throttle is per session+area, not per session",
                   v == "warn" and "area 'sec'" in m
                   and "raj@x.com" in m, repr((v, m)))
            v, m = own("src/own/a.ts", sid="selftest-own-2",
                       event="PostToolUse")
            ocheck("o6 a NEW session is told once too - the note is session "
                   "state, not repo state",
                   v == "warn" and "jane@x.com" in m, repr((v, m)))
            v, m = own("src/own/b.ts", sid="selftest-own-3",
                       event="PostToolUse")
            ocheck("o7 the owner editing their own area hears nothing",
                   v == "allow", repr((v, m)))
            n_before = _calls["n"]
            v, m = own("src/own/c.ts", sid="selftest-own-3",
                       event="PostToolUse")
            ocheck("o8 an explicit null owner is 'nobody owns this' - silent, "
                   "and the author subprocess is never paid for it",
                   v == "allow" and _calls["n"] == n_before, repr((v, m)))
            cfg_none = _config._deep_merge(cfg_graded,
                                           {"usage": {"authorMode": "none"}})
            v, m = own("src/own/a.ts", sid="selftest-own-4",
                       event="PostToolUse", use_cfg=cfg_none)
            ocheck("o9 authorMode 'none' turns the advisory off silently - a "
                   "project that refuses attribution is not nudged about it",
                   v == "allow", repr((v, m)))
            write_manifest({"meta": {"version": 2, "areas": {
                "api": {"root": "services/api"}}},
                "phases": [own_phase("P1", "api", ["src/own/a.ts"])]})
            n_before = _calls["n"]
            v, m = own("src/own/a.ts", sid="selftest-own-5",
                       event="PostToolUse")
            ocheck("o10 no owner declared ANYWHERE is the default-off: silent, "
                   "zero cost past the manifest read, no knob needed",
                   v == "allow" and _calls["n"] == n_before, repr((v, m)))
            ocheck("o11 the advisory can never harden: every verdict above was "
                   "allow or warn, never block or ask",
                   overdicts and set(overdicts) <= {"allow", "warn"},
                   repr(overdicts))
            clear_manifest()
        finally:
            if _orig_resolve is not None:
                _ledmod.resolve_author = _orig_resolve

    if _prev_project_dir is None:
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
    else:
        os.environ["CLAUDE_PROJECT_DIR"] = _prev_project_dir

    # (i) _ensure_dir yields self-ignoring local dirs
    tmp_ig = Path(tempfile.mkdtemp(prefix="rp-ignore-"))
    try:
        _ensure_dir(tmp_ig / "state")
        _ok_ig = (tmp_ig / "state" / ".gitignore").exists()
        results.append(_ok_ig)
        print("%s i1 _ensure_dir drops a `*` .gitignore - state and logs "
              "never belong in git" % ("PASS" if _ok_ig else "FAIL"))
    finally:
        shutil.rmtree(tmp_ig, ignore_errors=True)

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    main()
