#!/usr/bin/env python3
"""
Journal recorder -- registered at BOTH PreToolUse and PostToolUse
(matcher: Edit|Write|MultiEdit|NotebookEdit), branching on `hook_event_name`
the way require-plan.py does.

Appends one row to the tamper-evident journal for every edit-tool write to the
MANIFEST (index or phase shard) or to `.claude/audit.config.json`. Nothing else is
recorded: the journal is the audit trail of the plan and the rules, not a log of
the repository.

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

Run `python3 journal-writes.py --selftest` to exercise the decision core.
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


def post_entries(data, *, cfg=None, root=None):
    """The PostToolUse pass. Returns the list of entries to append: the primary
    row (semantic when the pre-image allows, generic otherwise) followed by any
    completion-event rows. Empty list = nothing to record. Never raises.

    The disable loophole is closed HERE: when the config itself is the target,
    `journal.enabled` is judged against the pre-image, so a true->false flip is
    journalled as a final config.edit row instead of silencing its own record."""
    try:
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


def main() -> None:
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


# --- selftest -----------------------------------------------------------------
def _selftest() -> int:
    import shutil
    import tempfile

    results = []

    def check(name, cond, detail=""):
        results.append(bool(cond))
        print("%s %s%s" % ("PASS" if cond else "FAIL", name,
                           (" (%s)" % detail) if detail and not cond else ""))

    tmp = tempfile.mkdtemp(prefix="journal-writes-selftest-")
    prev_env = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = tmp
    cfg = _config._deep_merge(_config.DEFAULTS, {})

    def payload(tool, path, *, sid="sess-1", edits=None):
        if tool == "NotebookEdit":
            ti = {"notebook_path": path, "new_source": "x"}
        elif tool == "MultiEdit":
            ti = {"file_path": path, "edits": edits or [{}, {}]}
        else:
            ti = {"file_path": path, "content": "x"}
        return {"tool_name": tool, "tool_input": ti, "session_id": sid,
                "cwd": tmp}

    def verdict(tool, path, *, use_cfg=None, **kw):
        try:
            return decide(payload(tool, path, **kw), cfg=use_cfg or cfg, root=tmp)
        except Exception as exc:                       # pragma: no cover
            return ("EXC", str(exc))

    try:
        # --- what is recorded -------------------------------------------------
        v, e = verdict("Edit", "docs/audit/audit-plan.json")
        check("a1 an edit to the manifest index is journalled",
              v == "journal" and e["action"] == "manifest.edit"
              and e["target"] == "docs/audit/audit-plan.json", repr((v, e)))
        v, e = verdict("Write", "docs/audit/phases/P3.json")
        check("a2 a phase shard is the manifest too - under the sharded layout "
              "almost every write IS a shard, and only the index has that name",
              v == "journal" and e["action"] == "manifest.edit"
              and e["target"] == "docs/audit/phases/P3.json", repr((v, e)))
        v, e = verdict("Edit", ".claude/audit.config.json")
        check("a3 the config is journalled under its own action - the rules "
              "changing is a different event from the plan changing",
              v == "journal" and e["action"] == "config.edit", repr((v, e)))
        v, e = verdict("Edit", os.path.join(tmp, "docs", "audit", "audit-plan.json"))
        check("a4 an ABSOLUTE path is recognised and recorded repo-relative "
              "(the tool reports absolute paths)",
              v == "journal" and e["target"] == "docs/audit/audit-plan.json",
              repr((v, e)))
        v, e = verdict("NotebookEdit", "docs/audit/audit-plan.json")
        check("a5 a notebook edit reads its own path key", v == "journal")

        # --- what is not ------------------------------------------------------
        for path, why in ((".claude/audit.config.json.bak", "a backup is not the config"),
                          ("src/app.py", "ordinary source"),
                          ("docs/audit/notes.md", "a sibling of the manifest"),
                          ("docs/audit/phases/notes.txt", "not a shard"),
                          ("docs/audit/audit-plan.json.lock", "the lock file")):
            v, _ = verdict("Write", path)
            check("b %s is not journalled (%s)" % (path, why), v == "skip")
        v, _ = verdict("Bash", "docs/audit/audit-plan.json")
        check("b6 a non-edit tool is not this hook's business", v == "skip")
        v, _ = verdict("Edit", "")
        check("b7 a payload with no path is skipped, not guessed at", v == "skip")
        v, r = verdict("Edit", "docs/audit/journal/2026-08.a.jsonl")
        check("b8 the journal is never its own subject", v == "skip"
              and "not its own subject" in r)
        v, _ = verdict("Edit", "docs/audit/audit-plan.json", use_cfg=_config._deep_merge(
            cfg, {"journal": {"enabled": False}}))
        check("b9 a disabled journal records nothing", v == "skip")
        # A moved manifest takes its shards and its journal with it.
        moved = _config._deep_merge(cfg, {"manifestPath": "plan/audit.json"})
        v, e = verdict("Edit", "plan/phases/P1.json", use_cfg=moved)
        check("b10 a shard of a MOVED manifest is still the manifest",
              v == "journal" and e["action"] == "manifest.edit")
        v, _ = verdict("Edit", "docs/audit/audit-plan.json", use_cfg=moved)
        check("b11 ...and the old location stops being special", v == "skip")

        # --- what the row says ------------------------------------------------
        v, e = verdict("MultiEdit", "docs/audit/audit-plan.json",
                       edits=[{}, {}, {}])
        check("c1 a MultiEdit says how many edits it was - 'MultiEdit' alone hides "
              "how much moved", "MultiEdit (3 edits)" in e["summary"], e["summary"])
        check("c2 one edit is not pluralised",
              "(1 edit)" in decide(payload("MultiEdit", "docs/audit/audit-plan.json",
                                           edits=[{}]), cfg=cfg, root=tmp)[1]["summary"])
        check("c3 the row carries only the news, never the chain fields that "
              "audit-journal.py owns",
              set(e) == {"action", "target", "summary", "actor"}, repr(sorted(e)))
        check("c4 the actor names the session and how the write arrived",
              e["actor"]["sessionId"] == "sess-1" and e["actor"]["via"] == "hook")
        v, e = verdict("Edit", "docs/audit/audit-plan.json", sid="")
        check("c5 a payload with no session id still produces a row",
              v == "journal" and e["actor"]["sessionId"] is None)
        _none = _config._deep_merge(cfg, {"usage": {"authorMode": "none"}})
        v, e = verdict("Edit", "docs/audit/audit-plan.json", use_cfg=_none)
        check("c6 authorMode none is honoured here too - a project that refuses to "
              "record who spends must not have it recorded here instead",
              v == "journal" and e["actor"]["author"] is None, repr(e["actor"]))
        # F-B2: the ledger module behind _author loads through _config's cache.
        # Honest accounting: production calls _author once per hook process, so
        # the cache is a selftest/parity win (suites drive it dozens of times,
        # each uncached call re-executing a ~1800-line module) - plus the same
        # single-module identity _journal_lib and _areas_lib already have.
        _llib_fn = getattr(_config, "_ledger_lib", None)
        _llib = _llib_fn() if _llib_fn else None
        check("c7 _config caches the ledger module - the same object across "
              "two calls, and _author's answer is resolve_author's answer",
              _llib is not None and _llib is _llib_fn()
              and _author(tmp, cfg) == _llib.resolve_author(str(tmp), "email"))
        _saved_lib = dict(getattr(_config, "_LEDGER_LIB", None) or {})

        class _StubLedger:
            @staticmethod
            def resolve_author(_root, mode):
                return "stub-author:" + mode

        try:
            if hasattr(_config, "_LEDGER_LIB"):
                _config._LEDGER_LIB.update({"tried": True, "mod": _StubLedger})
            check("c8 _author reads THROUGH the cache - swap the cached module "
                  "and the answer follows it",
                  _author(tmp, cfg) == "stub-author:email")
        finally:
            if hasattr(_config, "_LEDGER_LIB"):
                _config._LEDGER_LIB.clear()
                _config._LEDGER_LIB.update(_saved_lib)

        # --- end to end: the hook actually writes a verifiable chain -----------
        # decide() alone proves the decision, not the wiring. Two writes go all the
        # way through the real module, and the chain is then verified.
        proj = os.path.join(tmp, "e2e")
        os.makedirs(os.path.join(proj, "docs", "audit"))
        with open(os.path.join(proj, "docs", "audit", "audit-plan.json"), "w",
                  encoding="utf-8") as fh:
            fh.write('{"meta":{"version":3}}')
        jmod = _config._load_journal_lib()
        check("d0 the journal module loads from the hooks side at all",
              jmod is not None)
        for i in range(2):
            v, e = decide(payload("Edit", "docs/audit/audit-plan.json",
                                  sid="e2e-%d" % i), cfg=cfg, root=proj)
            if v == "journal":
                jmod.append(proj, e)
        res = jmod.verify(proj)
        check("d1 two writes leave two rows, in two files - one per session, which "
              "is what keeps parallel worktrees conflict-free",
              res["rows"] == 2 and len(res["files"]) == 2, repr(res))
        check("d2 and the chain verifies", res["ok"] and not res["findings"],
              repr(res["findings"]))
        rows = jmod.read_all(proj)
        check("d3 the row records the manifest as it stood after the write, so a "
              "later change with no row to explain it is visible",
              all(r.get("stateHash") for r in rows), repr(rows))
        with open(os.path.join(proj, "docs", "audit", "audit-plan.json"), "w",
                  encoding="utf-8") as fh:
            fh.write('{"meta":{"version":3},"phases":[]}')
        check("d4 ...and it is: an out-of-band edit warns, without accusing",
              jmod.verify(proj)["ok"]
              and any("never saw" in w for w in jmod.verify(proj)["warnings"]))

        # --- failure is silent, always ---------------------------------------
        # A recorder that raises into a PostToolUse hook is a recorder that breaks
        # the write it was recording.
        try:
            _bad = decide({"tool_name": "Edit", "tool_input": None}, cfg=cfg,
                          root=tmp)
            ok = _bad[0] == "skip"
        except Exception as exc:                       # pragma: no cover
            ok = False
            print("     raised: %s" % exc)
        results.append(ok)
        print("%s e1 a malformed payload is skipped, never raised"
              % ("PASS" if ok else "FAIL"))
        # Driven through main() rather than read off the source: this is the whole
        # stdin-to-exit contract, and the one thing it must not do is speak.
        import io
        _stdin, _stdout = sys.stdin, sys.stdout
        _cap = io.StringIO()
        _code = None
        try:
            sys.stdin = io.StringIO(json.dumps(
                {"tool_name": "Edit", "session_id": "e2",
                 "tool_input": {"file_path": "docs/audit/audit-plan.json",
                                "new_string": "x"},
                 "cwd": proj}))
            sys.stdout = _cap
            os.environ["CLAUDE_PROJECT_DIR"] = proj
            try:
                main()
            except SystemExit as exc:
                _code = exc.code
        finally:
            sys.stdin, sys.stdout = _stdin, _stdout
            os.environ["CLAUDE_PROJECT_DIR"] = tmp
        check("e2 the hook exits 0 and prints NOTHING - a recorder that talks "
              "turns every manifest edit into a line of transcript nobody asked "
              "for", _code in (0, None) and _cap.getvalue() == "",
              repr((_code, _cap.getvalue()[:120])))
        check("e3 ...and it really did record that write - a hook that stays quiet "
              "by doing nothing would pass the case above",
              jmod.verify(proj)["rows"] == 3, repr(jmod.verify(proj)))

        # --- g: the Pre pass caches the pre-image ------------------------------
        # Edit fragments are not parseable JSON, so the only way to diff is to
        # remember the file as it stood BEFORE the write.
        pproj = os.path.join(tmp, "prepost")
        os.makedirs(os.path.join(pproj, "docs", "audit"))
        man_rel = "docs/audit/audit-plan.json"
        man_abs = os.path.join(pproj, man_rel)

        def write_manifest(obj):
            with open(man_abs, "w", encoding="utf-8") as fh:
                json.dump(obj, fh)

        def manifest_doc(status="in_progress", commit=None, completed=None,
                         phase_status="in_progress", merged=None):
            return {"meta": {"version": 2}, "phases": [
                {"id": "P1", "title": "p", "status": phase_status,
                 "mergedAt": merged,
                 "tasks": [{"id": "P1.1", "title": "t", "status": status,
                            "commit": commit, "completedAt": completed}]}]}

        write_manifest(manifest_doc())
        slot = pre_cache(payload("Edit", man_rel, sid="pp-1"), cfg=cfg,
                         root=pproj)
        check("g1 the Pre pass caches a manifest target and returns the slot",
              slot is not None and os.path.exists(slot), repr(slot))
        with open(slot, encoding="utf-8") as fh:
            slot_obj = json.load(fh)
        check("g2 the slot holds the path, a hash and the bytes themselves",
              slot_obj.get("path") == man_rel
              and str(slot_obj.get("sha256") or "").startswith("sha256:")
              and json.loads(slot_obj["content"])["phases"][0]["id"] == "P1",
              repr(slot_obj)[:200])
        check("g3 an ordinary source file leaves no slot",
              pre_cache(payload("Edit", "src/app.py", sid="pp-1"), cfg=cfg,
                        root=pproj) is None)
        check("g4 a disabled journal caches nothing (the Pre pass reads the "
              "pre-image config: on Pre, disk IS the pre-image)",
              pre_cache(payload("Edit", man_rel, sid="pp-1"),
                        cfg=_config._deep_merge(cfg, {"journal":
                                                      {"enabled": False}}),
                        root=pproj) is None)
        write_manifest(manifest_doc(status="pending"))
        pre_cache(payload("Edit", man_rel, sid="pp-1"), cfg=cfg, root=pproj)
        with open(slot, encoding="utf-8") as fh:
            slot_obj2 = json.load(fh)
        check("g5 a second Pre OVERWRITES the stale slot - a denied tool call "
              "self-heals on the next attempt",
              json.loads(slot_obj2["content"])
              ["phases"][0]["tasks"][0]["status"] == "pending")
        os.makedirs(os.path.join(pproj, "docs", "audit", "phases"),
                    exist_ok=True)
        big_rel = "docs/audit/phases/P9.json"
        with open(os.path.join(pproj, big_rel), "w", encoding="utf-8") as fh:
            fh.write('{"id":"P9","tasks":[],"pad":"'
                     + "x" * (5 * 1024 * 1024) + '"}')
        slot_big = pre_cache(payload("Edit", big_rel, sid="pp-1"), cfg=cfg,
                             root=pproj)
        with open(slot_big, encoding="utf-8") as fh:
            check("g6 a pre-image over the 5 MB cap is not cached whole - the "
                  "slot records the miss and the Post pass falls back",
                  json.load(fh).get("content") is None)

        # --- h: the Post pass diffs, summarises, and derives events ------------
        write_manifest(manifest_doc(status="in_progress"))
        pre_cache(payload("Edit", man_rel, sid="pp-2"), cfg=cfg, root=pproj)
        write_manifest(manifest_doc(status="done",
                                    completed="2026-08-11T00:00:00Z"))
        entries = post_entries(payload("Edit", man_rel, sid="pp-2"), cfg=cfg,
                               root=pproj)
        check("h1 a status flip yields a semantic summary, not 'Edit wrote ...'",
              len(entries) >= 1
              and "P1.1: status in_progress->done" in entries[0]["summary"]
              and "completedAt set" in entries[0]["summary"],
              repr([e.get("summary") for e in entries]))
        check("h2 ...with the structured changes in details",
              {"id": "P1.1", "field": "status", "from": "in_progress",
               "to": "done"} in (entries[0].get("details") or {})
              .get("changes", []), repr(entries[0].get("details")))
        comp = [e for e in entries if e.get("action") == "task.complete"]
        check("h3 ...and a task.complete row derived from the same diff - the "
              "HOOK is the only writer of these",
              len(comp) == 1 and comp[0]["details"] == {
                  "taskId": "P1.1", "phaseId": "P1", "from": "in_progress",
                  "to": "done", "completedAt": "2026-08-11T00:00:00Z"},
              repr(comp))
        check("h4 the Post pass consumed and deleted the slot",
              not os.path.exists(_slot_path(pproj, cfg,
                                            {"session_id": "pp-2"}, man_rel)))

        write_manifest(manifest_doc(status="done", completed="X"))
        pre_cache(payload("Write", man_rel, sid="pp-3"), cfg=cfg, root=pproj)
        write_manifest(manifest_doc(status="done", completed="X",
                                    commit="a" * 40))
        entries = post_entries(payload("Write", man_rel, sid="pp-3"), cfg=cfg,
                               root=pproj)
        commit_rows = [e for e in entries if e.get("action") == "task.commit"]
        check("h5 a Write is diffed by full content: commit null->SHA yields a "
              "task.commit row",
              len(commit_rows) == 1
              and commit_rows[0]["details"]["commit"] == "a" * 40
              and commit_rows[0]["details"]["taskId"] == "P1.1", repr(entries))
        check("h5b ...and no task.complete - the status did not move this time",
              not [e for e in entries if e.get("action") == "task.complete"])

        write_manifest(manifest_doc(status="done", completed="X",
                                    commit="a" * 40))
        pre_cache(payload("Edit", man_rel, sid="pp-4"), cfg=cfg, root=pproj)
        write_manifest(manifest_doc(status="done", completed="X",
                                    commit="a" * 40, phase_status="done",
                                    merged="2026-08-11T01:00:00Z"))
        entries = post_entries(payload("Edit", man_rel, sid="pp-4"), cfg=cfg,
                               root=pproj)
        sign = [e for e in entries if e.get("action") == "phase.signoff"]
        check("h6 a phase flipped to done yields a phase.signoff row carrying "
              "mergedAt",
              len(sign) == 1 and sign[0]["details"] == {
                  "phaseId": "P1", "from": "in_progress", "to": "done",
                  "mergedAt": "2026-08-11T01:00:00Z"}, repr(sign))

        # --- i: connector v2 events (task.blocked + ado.link) ------------------
        # Derived from the same diff as everything else, tested on the core
        # directly. D-1 rule: `ado` is NOT in TASK_FIELDS - only the id is
        # compared, so an echo's lastSyncedAt bump writes no row at all.
        i_base = manifest_doc(status="in_progress")
        i_blocked = manifest_doc(status="blocked")
        i_blocked["phases"][0]["tasks"][0]["attempts"] = 3
        d_i1 = semantic_diff(i_base, i_blocked)
        blk = [e for e in (d_i1 or {}).get("events", [])
               if e.get("action") == "task.blocked"]
        check("i1 a task entering blocked yields a task.blocked row - "
              "symmetric with task.complete",
              len(blk) == 1 and blk[0]["details"] == {
                  "taskId": "P1.1", "phaseId": "P1",
                  "from": "in_progress", "attempts": 3},
              repr(d_i1 and d_i1.get("events")))
        d_i2 = semantic_diff(i_blocked, i_base)
        check("i2 LEAVING blocked is a change row only, never a task.blocked "
              "event",
              d_i2 is not None and not [e for e in d_i2.get("events", [])
                                        if e.get("action") == "task.blocked"])
        i_linked = manifest_doc(status="in_progress")
        i_linked["phases"][0]["tasks"][0]["ado"] = {
            "id": 7, "url": "u", "lastSyncedAt": "t1"}
        d_i3 = semantic_diff(i_base, i_linked)
        link_rows = [e for e in (d_i3 or {}).get("events", [])
                     if e.get("action") == "ado.link"]
        check("i3 a task link (ado.id None->int) yields an ado.link row and "
              "an ado.id change row",
              len(link_rows) == 1 and link_rows[0]["details"] == {
                  "taskId": "P1.1", "phaseId": "P1", "adoId": 7}
              and any(c.get("field") == "ado.id" for c in d_i3["changes"]),
              repr(d_i3))
        i_bumped = json.loads(json.dumps(i_linked))
        i_bumped["phases"][0]["tasks"][0]["ado"]["lastSyncedAt"] = "t2"
        check("i4 a lastSyncedAt-only bump is NO row at all - the plan did "
              "not move, and the echo must not spam the journal",
              semantic_diff(i_linked, i_bumped) is None)
        i_ph = manifest_doc(status="in_progress")
        i_ph["phases"][0]["ado"] = {"id": 9, "url": "u", "lastSyncedAt": "t"}
        d_i5 = semantic_diff(i_base, i_ph)
        ph_rows = [e for e in (d_i5 or {}).get("events", [])
                   if e.get("action") == "ado.link"]
        check("i5 a phase PBI link yields an ado.link row too",
              len(ph_rows) == 1 and ph_rows[0]["details"] == {
                  "phaseId": "P1", "adoId": 9}, repr(d_i5))
        i_garbage = manifest_doc(status="in_progress")
        i_garbage["phases"][0]["tasks"][0]["ado"] = "WI-7"
        check("i6 a non-dict ado never crashes the diff and never links",
              semantic_diff(i_base, i_garbage) is None)

        write_manifest(manifest_doc())
        entries = post_entries(payload("Edit", man_rel, sid="pp-5"), cfg=cfg,
                               root=pproj)
        check("h7 a cache miss falls back to the generic summary, no details, "
              "no events",
              len(entries) == 1
              and entries[0]["summary"].startswith("Edit wrote ")
              and "details" not in entries[0], repr(entries))
        slot2 = pre_cache(payload("Edit", man_rel, sid="pp-6"), cfg=cfg,
                          root=pproj)
        with open(slot2, "w", encoding="utf-8") as fh:
            json.dump({"path": man_rel, "ts": "t", "sha256": "sha256:x",
                       "content": "{not json"}, fh)
        entries = post_entries(payload("Edit", man_rel, sid="pp-6"), cfg=cfg,
                               root=pproj)
        check("h8 an unparseable pre-image falls back to the generic summary",
              len(entries) == 1
              and entries[0]["summary"].startswith("Edit wrote "))
        slot3 = pre_cache(payload("Edit", man_rel, sid="pp-7"), cfg=cfg,
                          root=pproj)
        with open(slot3, "w", encoding="utf-8") as fh:
            json.dump({"path": man_rel, "ts": "t", "sha256": None,
                       "content": None}, fh)
        entries = post_entries(payload("Edit", man_rel, sid="pp-7"), cfg=cfg,
                               root=pproj)
        check("h9 an over-the-cap pre-image falls back too",
              len(entries) == 1
              and entries[0]["summary"].startswith("Edit wrote "))

        # --- k: the disable loophole, closed -----------------------------------
        # journal.enabled is judged against the PRE-IMAGE when the config itself
        # is the target, so the flip that would have silenced its own record is
        # written down as a final row - the last will.
        cfg_rel = _config.CONFIG_REL
        cfg_abs = os.path.join(pproj, cfg_rel)
        os.makedirs(os.path.dirname(cfg_abs), exist_ok=True)

        def write_cfg_file(obj):
            with open(cfg_abs, "w", encoding="utf-8") as fh:
                json.dump(obj, fh)

        write_cfg_file({"journal": {"enabled": True}})
        pre_cache(payload("Edit", cfg_rel, sid="pp-9"), cfg=cfg, root=pproj)
        write_cfg_file({"journal": {"enabled": False}})
        post_cfg = _config._deep_merge(cfg, {"journal": {"enabled": False}})
        entries = post_entries(payload("Edit", cfg_rel, sid="pp-9"),
                               cfg=post_cfg, root=pproj)
        check("k1 flipping journal.enabled true->false IS journalled, with the "
              "flip in details",
              len(entries) == 1 and entries[0]["action"] == "config.edit"
              and (entries[0].get("details") or {}).get("changes") ==
              [{"field": "journal.enabled", "from": True, "to": False}]
              and "journal.enabled" in entries[0]["summary"], repr(entries))
        write_cfg_file({"journal": {"enabled": False}})
        check("k2 a config edit while the journal was already off records "
              "nothing - the user's switch is honoured",
              pre_cache(payload("Edit", cfg_rel, sid="pp-10"), cfg=post_cfg,
                        root=pproj) is None
              and post_entries(payload("Edit", cfg_rel, sid="pp-10"),
                               cfg=post_cfg, root=pproj) == [])
        write_cfg_file({"journal": {"enabled": True}})
        entries = post_entries(payload("Edit", cfg_rel, sid="pp-11"), cfg=cfg,
                               root=pproj)
        check("k3 flipping it back ON is recorded (generically - there was no "
              "pre-image while it was off)",
              len(entries) == 1 and entries[0]["action"] == "config.edit")

        # --- w: the wiring - main() routes by hook_event_name ------------------
        wproj = os.path.join(tmp, "wire")
        os.makedirs(os.path.join(wproj, "docs", "audit"))
        wman = os.path.join(wproj, "docs", "audit", "audit-plan.json")

        def wwrite(status):
            with open(wman, "w", encoding="utf-8") as fh:
                json.dump({"meta": {"version": 2}, "phases": [
                    {"id": "P1", "title": "p", "status": "in_progress",
                     "tasks": [{"id": "P1.1", "title": "t", "status": status,
                                "commit": None,
                                "completedAt": "2026-08-11T02:00:00Z"
                                if status == "done" else None}]}]}, fh)

        def drive(event):
            import io
            _stdin, _stdout = sys.stdin, sys.stdout
            cap = io.StringIO()
            code = None
            try:
                sys.stdin = io.StringIO(json.dumps(
                    {"tool_name": "Edit", "session_id": "wire-1",
                     "hook_event_name": event,
                     "tool_input": {"file_path": "docs/audit/audit-plan.json",
                                    "new_string": "x"},
                     "cwd": wproj}))
                sys.stdout = cap
                os.environ["CLAUDE_PROJECT_DIR"] = wproj
                try:
                    main()
                except SystemExit as exc:
                    code = exc.code
            finally:
                sys.stdin, sys.stdout = _stdin, _stdout
                os.environ["CLAUDE_PROJECT_DIR"] = tmp
            return code, cap.getvalue()

        wwrite("in_progress")
        code, spoke = drive("PreToolUse")
        wslots = [f for f in os.listdir(os.path.join(wproj, ".claude", "state"))
                  if f.startswith("journal-preimage-")] if os.path.isdir(
                      os.path.join(wproj, ".claude", "state")) else []
        check("w1 the Pre pass through main() exits 0, prints nothing, and "
              "leaves a slot",
              code in (0, None) and spoke == "" and len(wslots) == 1,
              repr((code, spoke[:80], wslots)))
        wwrite("done")
        code, spoke = drive("PostToolUse")
        wres = jmod.verify(wproj)
        wrows = jmod.read_all(wproj)
        check("w2 the Post pass through main() appends the semantic row AND the "
              "task.complete row, and the chain verifies",
              code in (0, None) and spoke == "" and wres["ok"]
              and [r.get("action") for r in wrows] ==
              ["manifest.edit", "task.complete"]
              and wrows[1].get("details", {}).get("taskId") == "P1.1",
              repr((wres, [r.get("action") for r in wrows])))

        # --- j: the F-F3 sidecar -----------------------------------------------
        # The append above put the journal file into git status, and
        # guard-bash-writes' next Bash pass used to blame the shell command for
        # it. After every successful append, main() records the written file's
        # rel path in <stateDir>/bash-writes-plugin-<sid>.json -- ONE writer
        # (this hook), because hooks on the same event run in parallel and a
        # shared state file would race. guard-bash-writes reads it and skips
        # exactly those rels; its k group drives THIS writer, so the two sides
        # cannot drift about where the sidecar lives.
        _wsd = os.path.join(wproj, ".claude", "state")
        _wsides = ([f for f in os.listdir(_wsd)
                    if f.startswith("bash-writes-plugin-")]
                   if os.path.isdir(_wsd) else [])
        _wjfiles = jmod.journal_files(jmod.journal_dir(wproj, cfg))
        _wjrels = [os.path.relpath(p, wproj).replace(os.sep, "/")
                   for p in _wjfiles]
        _wslot = (os.path.join(_wsd, _wsides[0]) if _wsides else None)
        try:
            with open(_wslot, "r", encoding="utf-8") as fh:
                _wobj = json.load(fh)
        except Exception:
            _wobj = {}
        check("j1 the Post pass leaves a sidecar naming the journal file the "
              "append landed in",
              len(_wsides) == 1
              and sorted(_wobj.get("pluginWrote") or []) == sorted(_wjrels),
              repr((_wsides, _wobj, _wjrels)))
        check("j2 the sidecar name carries the bash-writes- prefix, so the "
              "existing state GC sweeps it",
              bool(_wsides) and _wsides[0].startswith("bash-writes-")
              and ("wire-1" in _wsides[0]))
        wwrite("in_progress")
        drive("PreToolUse")
        wwrite("done")
        drive("PostToolUse")
        try:
            with open(_wslot, "r", encoding="utf-8") as fh:
                _wobj2 = json.load(fh)
        except Exception:
            _wobj2 = {}
        check("j3 a second append to the same file does not duplicate the "
              "entry",
              sorted(_wobj2.get("pluginWrote") or []) == sorted(_wjrels),
              repr(_wobj2))
        check("j4 record_plugin_write never raises on garbage - it guards a "
              "PostToolUse hook",
              getattr(sys.modules[__name__], "record_plugin_write",
                      lambda *a: None)(None, None, None, None) is None)
        # A disabled journal appends nothing, so there is nothing to record.
        _joff = os.path.join(tmp, "joff")
        os.makedirs(os.path.join(_joff, "docs", "audit"), exist_ok=True)
        _joffcfg = _config._deep_merge(cfg, {"journal": {"enabled": False}})
        check("j5 a disabled journal leaves no sidecar (nothing was appended)",
              post_entries(payload("Edit", "docs/audit/audit-plan.json",
                                   sid="j5"), cfg=_joffcfg, root=_joff) == []
              and not os.path.isdir(os.path.join(_joff, ".claude", "state")))
    finally:
        if prev_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = prev_env
        shutil.rmtree(tmp, ignore_errors=True)

    # (i) the sidecar's state dir is self-ignoring
    tmp_i = tempfile.mkdtemp(prefix="jw-ignore-")
    try:
        _cfg_i = dict(_config.DEFAULTS)
        record_plugin_write(tmp_i, _cfg_i, {"session_id": "s-i"},
                            os.path.join(tmp_i, "docs", "audit", "journal",
                                         "j.jsonl"))
        check("i1 record_plugin_write's state dir carries a `*` .gitignore",
              os.path.exists(os.path.join(
                  tmp_i, str(_cfg_i["stateDir"]), ".gitignore")))
    finally:
        shutil.rmtree(tmp_i, ignore_errors=True)

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    main()
