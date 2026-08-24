#!/usr/bin/env python3
"""
Journal recorder -- registered at BOTH PreToolUse and PostToolUse
(matcher: Edit|Write|MultiEdit|NotebookEdit), branching on `hook_event_name`
the way require-plan.py does, and at PostToolUse on Bash for one narrow event.

Appends one row to the tamper-evident journal for every edit-tool write to the
MANIFEST (index or phase shard) or to `.claude/audit.config.json`. Nothing else is
recorded: the journal is the audit trail of the plan and the rules, not a log of
the repository.

THE ONE EXCEPTION, and why it earns the exception (P0-S). A Bash call carrying
`dangerouslyDisableSandbox: true` runs with the only layer that can actually
CONTAIN a read switched off, and until P0-S no part of this plugin saw it -- a
live session read a secret through direnv that way and left no deny, no gate
message and no row. `bash.unsandboxed` records a DIGEST of the command, its byte
length, its program name, and the cwd relative to the repo. It prevents nothing
(PostToolUse is after the fact) and it is not meant to: it turns an invisible
event into tamper-evident history, which is what this file is for. An ordinary
sandboxed Bash call is still nobody's business here, and the flag -- not the tool
name -- is what is read, so the journal cannot decay into a shell log.

THIS HOOK STILL PASSES THE RAW COMMAND, and that is the design rather than an
oversight. The journal is committed on purpose, so command text in a row is
CWE-532 in a file that ships; the redaction therefore lives at the ONE boundary
every writer goes through -- `_journal_io.normalise_details`, before the hash --
so the panel, `audit-task.py` and the CLI are covered by the same implementation
and no second hook has to grow `hashlib` on the critical path of every tool call.

THE TWO PASSES. Edit fragments are not parseable JSON, so a field-level diff can
only come from remembering the file as it stood BEFORE the write. The Pre pass
caches the target's bytes into a per-session slot under stateDir (overwritten
every time -- a denied tool call self-heals on the next attempt) and exits 0
silently, always. The Post pass consumes the slot, diffs old vs new JSON by id
over the state fields, turns "Edit wrote <path>" into "P2.3: status
in_progress->done, completedAt set" with the structured changes in the row's
`details`, and emits ADDITIONAL chained rows derived from the same diff:

    task.complete   a task's status moved to done
    task.commit     a task's commit moved null -> SHA
    phase.signoff   a phase's status moved to done

This HOOK is the only writer of those actions -- a prose instruction to append
them would be a second writer, and two writers means duplicate rows. Tokens are
deliberately NOT in these rows: metering lands on Stop/SessionEnd, so any number
written here would be wrong; the cross-anchor is the ledger, joined by taskId.

THE DISABLE LOOPHOLE, CLOSED. `journal.enabled` used to be read from the config
AFTER the write, so flipping it true->false silenced the very row that would
have recorded the flip. The Post pass now judges `enabled` against the PRE-IMAGE
config when the config itself is the target, so the flip is journalled as a
final config.edit row -- the last will. Nothing overrides the user's switch:
once off, edits record nothing.

Fail-open at every step: no cache, unparseable JSON, an over-the-cap file --
each falls back to today's generic "<tool> wrote <path>" summary, never to a
broken write.

WHY A HOOK AND NOT A PROMPT. The orchestrator could be told to journal its writes,
and it would — most of the time. A model that forgets, or a session that never read
the instruction, produces a gap that looks exactly like a covered-up change; the
one thing an audit trail cannot afford is to be as reliable as compliance. This
runs mechanically, after the write, whatever wrote it and whatever it was told.

WHAT IT CANNOT SEE, stated here rather than discovered later:
  * shell writes (`sed -i`, `>`), which never reach a tool matcher. guard-bash-writes
    reports those separately, and `verify` sees the file move with no row to explain
    it (out-of-band drift).
  * a write while the plugin is disabled. Nothing in Claude Code can outlive the
    user's own switch, and SECURITY.md says so.

CONTRACT: PostToolUse, mode `open`, NO stdout. A recorder that talks turns every
manifest edit into a line of transcript nobody asked for, and additionalContext is
context the model then has to read. Failure is silent by design — a journal that
cannot be written must never break the write it was recording. ALWAYS exits 0.

This hook carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test_journal_writes.py` (hyphens become underscores - a
hyphenated name is not importable). A test of a hook may import from `scripts/`
even though the hook itself may not; see `plugins/audit/tests/_harness.py`.
"""
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _config  # noqa: E402

_EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")

# The pre-image cache. 5 MB is far above any real manifest; past it the slot
# records the miss and the Post pass falls back to the generic summary.
_PREIMAGE_MAX_BYTES = 5 * 1024 * 1024
_SAFE_SID = re.compile(r"[^A-Za-z0-9._-]+")

# The state fields a diff reports. Everything else on a task or a phase is
# content, and the journal records that the plan MOVED, not what it says.
TASK_FIELDS = ("status", "startedAt", "completedAt", "commit", "attempts",
               "outcome", "verifiedBy", "model", "skills")
PHASE_FIELDS = ("status", "mergedAt", "branch")


# --- helpers ------------------------------------------------------------------
def _target_of(tool, ti):
    ti = ti if isinstance(ti, dict) else {}
    if tool == "NotebookEdit":
        return str(ti.get("notebook_path", "") or ti.get("file_path", ""))
    return str(ti.get("file_path", ""))


def _how(tool, ti):
    """The one detail worth keeping about the write itself. A MultiEdit is n edits
    in one call, and 'MultiEdit' alone would hide how much moved."""
    if tool == "MultiEdit":
        n = len((ti or {}).get("edits") or [])
        return "MultiEdit (%d edit%s)" % (n, "" if n == 1 else "s")
    return tool


def _author(root, cfg):
    """Who the ledger would call this person, under the project's own authorMode.

    The SAME function the usage ledger writes its author column with, so the
    journal's `who` and the ledger's `who` are one identity and `my spend` in the
    panel can line up with `my changes` here. Costs one `git config` read, and only
    on a manifest or config write — never on an ordinary edit.

    The module arrives through `_config._ledger_lib()` (F-B2) — the same cached
    one-load seam the journal and areas modules use. In production that saves
    almost nothing (one call per hook process); the win is parity and the
    selftests, which call this dozens of times per run."""
    try:
        mod = _config._ledger_lib()
        if mod is None:
            return None
        mode = (_config.usage_cfg(cfg) or {}).get("authorMode") or "email"
        return mod.resolve_author(str(root), mode)
    except Exception:
        return None


# --- decision -----------------------------------------------------------------
def classify(data, *, cfg, root):
    """What kind of target this write hits. Returns (action, rel, tool, ti);
    `action` is None with the reason in `rel`'s place when it is nobody's
    business. Shared by the Pre and Post passes so the two can never disagree
    about what counts as the manifest."""
    tool = data.get("tool_name", "")
    if tool not in _EDIT_TOOLS:
        return (None, "not an edit tool", tool, {})
    ti = data.get("tool_input", {}) or {}
    path = _target_of(tool, ti)
    if not path:
        return (None, "no path", tool, ti)
    rel = _config.rel_path(root, path)
    manifest_rel = cfg.get("manifestPath") or _config.DEFAULTS["manifestPath"]

    # The journal itself is never journalled. guard-edits refuses that write
    # anyway, so this only matters when the guards are off — and a recorder that
    # records the recording is a loop nobody wants to read.
    if _config.in_journal(root, cfg, rel):
        return (None, "the journal is not its own subject", tool, ti)

    if rel == manifest_rel or _config.governing_lock(manifest_rel, rel):
        return ("manifest.edit", rel, tool, ti)
    if rel == _config.CONFIG_REL:
        return ("config.edit", rel, tool, ti)
    return (None, "not a manifest or config path", tool, ti)


def _entry(action, rel, tool, ti, data, root, cfg):
    """The row's news — action, target, summary, actor. Everything that makes it
    a CHAIN (v, ts, stateHash, prev, hash) belongs to audit-journal.py and is
    deliberately not invented here."""
    return {
        "action": action,
        "target": rel,
        "summary": "%s wrote %s" % (_how(tool, ti), rel),
        "actor": {"author": _author(root, cfg),
                  "sessionId": str(data.get("session_id") or "") or None,
                  "via": "hook"},
    }


def decide(data, *, cfg=None, root=None):
    """Pure decision core. Returns ("journal", entry) or ("skip", reason)."""
    root = root if root is not None else _config.repo_root(data)
    cfg = cfg if cfg is not None else _config.load(root)
    action, rel, tool, ti = classify(data, cfg=cfg, root=root)
    if action is None:
        return ("skip", rel)
    if not _config.journal_enabled(cfg):
        return ("skip", "journal disabled")
    return ("journal", _entry(action, rel, tool, ti, data, root, cfg))


# --- the pre-image cache ------------------------------------------------------
def _slot_path(root, cfg, data, rel):
    """<stateDir>/journal-preimage-<sessionId>.<sha256(rel)[:12]>.json — one slot
    per (session, target), so parallel sessions never clobber each other's
    pre-image and the same session's retries overwrite their own."""
    state_rel = str(cfg.get("stateDir") or _config.DEFAULTS["stateDir"])
    sid = _SAFE_SID.sub("-", str(data.get("session_id") or "")).strip("-.")
    sid = (sid or "no-session")[:40]
    digest = hashlib.sha256(rel.encode("utf-8")).hexdigest()[:12]
    return os.path.join(str(root), state_rel,
                        "journal-preimage-%s.%s.json" % (sid, digest))


def pre_cache(data, *, cfg=None, root=None):
    """The PreToolUse pass: remember the target as it stands, so the Post pass
    can diff. Returns the slot path when one was written, else None.

    Never raises, never blocks, never speaks. The slot is overwritten every
    time; a file over the cap (or absent) leaves `content` null, which the Post
    pass reads as "fall back to the generic summary"."""
    try:
        root = root if root is not None else _config.repo_root(data)
        cfg = cfg if cfg is not None else _config.load(root)
        if not _config.journal_enabled(cfg):
            return None            # on Pre, the config on disk IS the pre-image
        action, rel, _tool, _ti = classify(data, cfg=cfg, root=root)
        if action is None:
            return None
        slot = _slot_path(root, cfg, data, rel)
        sha, content = None, None
        target = os.path.join(str(root), rel)
        try:
            if os.path.getsize(target) <= _PREIMAGE_MAX_BYTES:
                with open(target, "rb") as fh:
                    raw = fh.read(_PREIMAGE_MAX_BYTES + 1)
                sha = "sha256:" + hashlib.sha256(raw).hexdigest()
                content = raw.decode("utf-8", "replace")
        except OSError:
            pass                   # no such file yet: the slot records that too
        _config.ensure_local_dir(os.path.dirname(slot))
        with open(slot, "w", encoding="utf-8") as fh:
            json.dump({"path": rel,
                       "ts": _config.utc_stamp(),
                       "sha256": sha, "content": content}, fh)
        return slot
    except Exception:
        return None


def _consume_preimage(root, cfg, data, rel):
    """Load AND delete the slot for `rel`. None on any miss — a miss is a
    fallback, never an error."""
    try:
        slot = _slot_path(root, cfg, data, rel)
        with open(slot, "r", encoding="utf-8") as fh:
            obj = json.load(fh)
        try:
            os.unlink(slot)
        except OSError:
            pass
        if isinstance(obj, dict) and obj.get("path") == rel:
            return obj
    except Exception:
        pass
    return None


# --- the diff -----------------------------------------------------------------
def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _collect(obj):
    """(phases_by_id, tasks_by_id, phase_of_task) out of a single-file manifest,
    a sharded index, or one shard body (which IS a phase). Empty on anything
    else — an empty diff is a generic summary, not a crash."""
    phases, tasks, owner = {}, {}, {}
    if not isinstance(obj, dict):
        return phases, tasks, owner
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
        pid = ph.get("id")
        if pid:
            phases[pid] = ph
        tlist = ph.get("tasks")
        for t in (tlist if isinstance(tlist, list) else []):
            if isinstance(t, dict) and t.get("id"):
                tasks[t["id"]] = t
                owner[t["id"]] = pid
    return phases, tasks, owner


def _render(val):
    """A field value as short evidence text; audit-journal bounds it again."""
    if val is None or isinstance(val, (str, int, float, bool)):
        return val
    try:
        return json.dumps(val, sort_keys=True, separators=(",", ":"))[:120]
    except Exception:
        return type(val).__name__


def semantic_diff(old_obj, new_obj):
    """State diff of two manifest documents, by id.

    Returns {"changes", "summary", "events"} or None when nothing this hook
    tracks moved. The events are the completion records: derived from the SAME
    comparison that produced the changes, so they cannot disagree with it."""
    try:
        old_phases, old_tasks, _old_owner = _collect(old_obj)
        new_phases, new_tasks, new_owner = _collect(new_obj)
        changes, phrases, events = [], [], []
        for tid in new_tasks:
            if tid not in old_tasks:
                changes.append({"id": tid, "field": "task",
                                "from": None, "to": "added"})
                phrases.append("%s added" % tid)
        for tid in old_tasks:
            if tid not in new_tasks:
                changes.append({"id": tid, "field": "task",
                                "from": "present", "to": "removed"})
                phrases.append("%s removed" % tid)
        for tid, new_task in new_tasks.items():
            old_task = old_tasks.get(tid)
            if old_task is None:
                continue
            frags = []
            for field in TASK_FIELDS:
                ov, nv = old_task.get(field), new_task.get(field)
                if ov == nv:
                    continue
                changes.append({"id": tid, "field": field,
                                "from": _render(ov), "to": _render(nv)})
                if field == "status":
                    frags.append("status %s->%s" % (ov, nv))
                elif ov is None:
                    frags.append("%s set" % field)
                elif nv is None:
                    frags.append("%s cleared" % field)
                else:
                    frags.append("%s changed" % field)
                if field == "status" and nv == "done" and ov != "done":
                    events.append({"action": "task.complete",
                                   "summary": "%s done" % tid,
                                   "details": {
                                       "taskId": tid,
                                       "phaseId": new_owner.get(tid),
                                       "from": ov, "to": nv,
                                       "completedAt":
                                       new_task.get("completedAt")}})
                if field == "status" and nv == "blocked" and ov != "blocked":
                    events.append({"action": "task.blocked",
                                   "summary": "%s blocked" % tid,
                                   "details": {
                                       "taskId": tid,
                                       "phaseId": new_owner.get(tid),
                                       "from": ov,
                                       "attempts":
                                       new_task.get("attempts")}})
                if (field == "commit" and ov is None
                        and isinstance(nv, str) and nv):
                    events.append({"action": "task.commit",
                                   "summary": "%s commit %s" % (tid, nv[:12]),
                                   "details": {"taskId": tid,
                                               "phaseId": new_owner.get(tid),
                                               "commit": nv}})
            # `ado` is deliberately NOT in TASK_FIELDS: only the ID is compared,
            # so a sync/echo lastSyncedAt bump writes no row (the plan did not
            # move), while the link itself - the tamper-evident half - is.
            oa, na = old_task.get("ado"), new_task.get("ado")
            ov_id = oa.get("id") if isinstance(oa, dict) else None
            nv_id = na.get("id") if isinstance(na, dict) else None
            if ov_id != nv_id:
                changes.append({"id": tid, "field": "ado.id",
                                "from": _render(ov_id), "to": _render(nv_id)})
                frags.append("ado.id set" if ov_id is None else
                             ("ado.id cleared" if nv_id is None
                              else "ado.id changed"))
                if ov_id is None and isinstance(nv_id, int):
                    events.append({"action": "ado.link",
                                   "summary": "%s linked to ADO #%s"
                                   % (tid, nv_id),
                                   "details": {"taskId": tid,
                                               "phaseId": new_owner.get(tid),
                                               "adoId": nv_id}})
            if frags:
                phrases.append("%s: %s" % (tid, ", ".join(frags)))
        for pid, new_phase in new_phases.items():
            old_phase = old_phases.get(pid)
            if old_phase is None:
                continue
            frags = []
            for field in PHASE_FIELDS:
                ov, nv = old_phase.get(field), new_phase.get(field)
                if ov == nv:
                    continue
                changes.append({"id": pid, "field": field,
                                "from": _render(ov), "to": _render(nv)})
                if field == "status":
                    frags.append("status %s->%s" % (ov, nv))
                elif ov is None:
                    frags.append("%s set" % field)
                else:
                    frags.append("%s changed" % field)
                if field == "status" and nv == "done" and ov != "done":
                    events.append({"action": "phase.signoff",
                                   "summary": "%s signed off" % pid,
                                   "details": {"phaseId": pid,
                                               "from": ov, "to": nv,
                                               "mergedAt":
                                               new_phase.get("mergedAt")}})
            # phase PBI link (meta.ado.phaseWorkItems) - same id-only rule as
            # the task loop above.
            oa, na = old_phase.get("ado"), new_phase.get("ado")
            ov_id = oa.get("id") if isinstance(oa, dict) else None
            nv_id = na.get("id") if isinstance(na, dict) else None
            if ov_id != nv_id:
                changes.append({"id": pid, "field": "ado.id",
                                "from": _render(ov_id), "to": _render(nv_id)})
                frags.append("ado.id set" if ov_id is None else
                             ("ado.id cleared" if nv_id is None
                              else "ado.id changed"))
                if ov_id is None and isinstance(nv_id, int):
                    events.append({"action": "ado.link",
                                   "summary": "%s linked to ADO #%s"
                                   % (pid, nv_id),
                                   "details": {"phaseId": pid,
                                               "adoId": nv_id}})
            if frags:
                phrases.append("%s: %s" % (pid, ", ".join(frags)))
        if not changes:
            return None
        summary = "; ".join(phrases)
        if len(summary) > 300:
            summary = summary[:297] + "..."
        return {"changes": changes, "summary": summary, "events": events}
    except Exception:
        return None


def _journal_flip(old_obj, new_obj):
    """Did `journal.enabled` move between two config documents? Judged on the
    EFFECTIVE value (absent = true), so deleting the key reads as the flip it
    is. Returns one change dict, or None."""
    try:
        ov = _config.journal_enabled(old_obj if isinstance(old_obj, dict) else {})
        nv = _config.journal_enabled(new_obj if isinstance(new_obj, dict) else {})
        if ov != nv:
            return {"field": "journal.enabled", "from": ov, "to": nv}
    except Exception:
        pass
    return None


def sandbox_disabled(ti):
    """True when a Bash call asked to run OUTSIDE the harness sandbox.

    A JSON boolean is what the harness sends; the string form is accepted too,
    because a payload is not this hook's to validate and testing `is True` alone
    would grade `"true"` as sandboxed -- a default quietly filling a gap on the
    side that records nothing.

    Deliberately a SECOND copy of guard-secrets-read's reader rather than a shared
    one: hooks may not import each other, and `_config` is the config/manifest
    core, not a place for tool-payload trivia. Both are three lines over one
    documented field; the day that field grows a shape, this comment is the
    pointer to the other copy."""
    value = (ti or {}).get("dangerouslyDisableSandbox")
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def unsandboxed_entries(data, *, cfg=None, root=None):
    """P0-S: one row for a Bash run that went around the harness sandbox.

    THE FLAG IS READ BEFORE ANYTHING ELSE, and that is a design choice, not an
    optimisation detail: this hook is now wired to every Bash call, and resolving
    the repo root and loading the config for each one would charge every command
    in the session for an event that is rare. A sandboxed call leaves here having
    touched nothing.

    WHY THIS IS A JOURNAL ROW AND NOT A GUARD. PostToolUse is after the fact, so
    it stops nothing, and `dangerouslyDisableSandbox` is legitimate -- it is the
    documented escape hatch, and refusing all of them would simply get the plugin
    turned off. What was wrong was that the event was INVISIBLE: no deny, no gate
    message, no row, nothing for `/audit:doctor` or `verify` to find afterwards.
    guard-secrets-read refuses the narrow combination that reaches the environment
    layer; everything else is recorded here, and a recorded bypass is a bypass
    somebody can audit.

    The user's switch still wins: `journal.enabled` false records nothing, exactly
    as for an edit."""
    ti = data.get("tool_input", {}) or {}
    if not sandbox_disabled(ti):
        return []
    root = root if root is not None else _config.repo_root(data)
    cfg = cfg if cfg is not None else _config.load(root)
    if not _config.journal_enabled(cfg):
        return []
    command = str(ti.get("command", ""))
    return [{
        "action": "bash.unsandboxed",
        # No file moved, so no target and no stateHash. `_normalise` allows an
        # empty target; inventing one would put a hash of nothing in the chain.
        "target": "",
        "summary": "Bash ran outside the harness sandbox (recorded, not prevented)",
        "details": {"command": command, "cwd": str(data.get("cwd") or root)},
        "actor": {"author": _author(root, cfg),
                  "sessionId": str(data.get("session_id") or "") or None,
                  "via": "hook"},
    }]


def post_entries(data, *, cfg=None, root=None):
    """The PostToolUse pass. Returns the list of entries to append: the primary
    row (semantic when the pre-image allows, generic otherwise) followed by any
    completion-event rows. Empty list = nothing to record. Never raises.

    The disable loophole is closed HERE: when the config itself is the target,
    `journal.enabled` is judged against the pre-image, so a true->false flip is
    journalled as a final config.edit row instead of silencing its own record."""
    try:
        if data.get("tool_name") == "Bash":
            return unsandboxed_entries(data, cfg=cfg, root=root)
        root = root if root is not None else _config.repo_root(data)
        cfg = cfg if cfg is not None else _config.load(root)
        action, rel, tool, ti = classify(data, cfg=cfg, root=root)
        if action is None:
            return []
        pre = _consume_preimage(root, cfg, data, rel)   # consumed regardless
        old_obj = None
        if pre is not None and isinstance(pre.get("content"), str):
            try:
                old_obj = json.loads(pre["content"])
            except Exception:
                old_obj = None
        enabled = _config.journal_enabled(cfg)
        if action == "config.edit" and old_obj is not None:
            enabled = _config.journal_enabled(
                old_obj if isinstance(old_obj, dict) else {})
        if not enabled:
            return []
        entry = _entry(action, rel, tool, ti, data, root, cfg)
        events = []
        if old_obj is not None:
            new_obj = _read_json(os.path.join(str(root), rel))
            if action == "config.edit":
                flip = (_journal_flip(old_obj, new_obj)
                        if new_obj is not None else None)
                if flip is not None:
                    entry["summary"] = ("journal.enabled %s->%s"
                                        % (str(flip["from"]).lower(),
                                           str(flip["to"]).lower()))
                    entry["details"] = {"changes": [flip]}
            else:
                diff = (semantic_diff(old_obj, new_obj)
                        if new_obj is not None else None)
                if diff is not None:
                    entry["summary"] = diff["summary"]
                    entry["details"] = {"changes": diff["changes"]}
                    for ev in diff["events"]:
                        events.append({"action": ev["action"], "target": rel,
                                       "summary": ev["summary"],
                                       "details": ev["details"],
                                       "actor": dict(entry["actor"])})
        return [entry] + events
    except Exception:
        return []


# --- the F-F3 sidecar -----------------------------------------------------------
def _sidecar_path(root, cfg, data):
    """<stateDir>/bash-writes-plugin-<sid>.json -- where this session's plugin-made
    journal writes are named. The `bash-writes-` prefix is already in
    detect-plan-skip's GC tuple, so the sidecar ages out with the rest of the
    session state."""
    state_rel = str(cfg.get("stateDir") or _config.DEFAULTS["stateDir"])
    sid = _SAFE_SID.sub("-", str(data.get("session_id") or "")).strip("-.")
    sid = (sid or "no-session")[:40]
    return os.path.join(str(root), state_rel,
                        "bash-writes-plugin-%s.json" % sid)


def record_plugin_write(root, cfg, data, written_path):
    """Note a journal file THIS hook just appended to -- {"pluginWrote": [rel]}.

    The append above put that file into `git status`, and guard-bash-writes'
    next Bash pass used to blame the shell command for it (F-F3). That guard
    reads this sidecar and skips exactly the rels named here.

    ONE writer, this hook, on purpose: hooks registered on the SAME event run
    in parallel, so folding this into guard-bash-writes' own state file
    (`bash-writes-<sid>.json`) would be two processes writing one file with no
    lock. A sidecar with a single writer has no race to lose. Returns the slot
    path, or None -- never raises (it runs inside a PostToolUse hook)."""
    try:
        rel = _config.rel_path(root, str(written_path))
        slot = _sidecar_path(root, cfg, data)
        wrote = []
        try:
            with open(slot, "r", encoding="utf-8") as fh:
                obj = json.load(fh)
            if isinstance(obj, dict) and isinstance(obj.get("pluginWrote"),
                                                    list):
                wrote = [str(x) for x in obj["pluginWrote"]]
        except Exception:
            pass
        if rel not in wrote:
            wrote.append(rel)
            _config.ensure_local_dir(os.path.dirname(slot))
            with open(slot, "w", encoding="utf-8") as fh:
                json.dump({"pluginWrote": wrote}, fh)
        return slot
    except Exception:
        return None


# --- cli ----------------------------------------------------------------------
def _journal_lib():
    return _config._load_journal_lib()


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        if str(data.get("hook_event_name") or "PostToolUse") == "PreToolUse":
            pre_cache(data)
        else:
            entries = post_entries(data)
            if entries:
                mod = _journal_lib()
                if mod is not None:
                    root = str(_config.repo_root(data))
                    cfg = _config.load(root)
                    for entry in entries:
                        written = mod.append(root, entry)
                        if written:
                            record_plugin_write(root, cfg, data, written)
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        # Answered rather than fallen through to main(), which would block on stdin
        # waiting for a hook payload that is never coming. It deliberately does NOT
        # print the `N/M cases passed` contract - that string is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("journal-writes.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_journal_writes.py - run that file instead.")
        sys.exit(0)
    main()
