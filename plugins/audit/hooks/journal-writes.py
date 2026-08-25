#!/usr/bin/env python3
"""
Journal recorder -- registered at PreToolUse on the edit tools and at
PostToolUse on the edit tools AND on Bash, branching on `hook_event_name` the way
require-plan.py does.

Appends one row to the tamper-evident journal for every write to the MANIFEST
(index or phase shard) or to `.claude/audit.config.json`, whatever made it.
Nothing else is recorded: the journal is the audit trail of the plan and the
rules, not a log of the repository.

WHICH TOOL WROTE IT IS NO LONGER THE QUESTION (F194). The derived rows below used
to exist only for a write that arrived through an edit tool, because `classify()`
reads `file_path` and a Bash payload has none. A session that wrote the manifest
through `python3 -c` -- a harness mode that prefers Bash, a script, a different
orchestrator -- left a chain that verified perfectly over a history missing the
very events the trail exists to record, which is the worst of the four
combinations available. Scoping the recorder to the tools the model was expected
to use is the same dependency WHY A HOOK AND NOT A PROMPT rejects, one layer
down: the model's choice of TOOL instead of its memory. So the Bash pass asks the
question of the FILE -- is the digest still the one the slot remembers -- and the
slot is refreshed after every recorded row so its baseline is the manifest as of
the last row in the journal, whoever wrote it.

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
snapshots the target's bytes into a per-(session, target) slot under stateDir
(overwritten every time -- a denied tool call self-heals on the next attempt) and
exits 0 silently, always. The Post pass READS the slot, diffs old vs new JSON by
id over the state fields, turns "Edit wrote <path>" into "P2.3: status
in_progress->done, completedAt set" with the structured changes in the row's
`details`, emits ADDITIONAL chained rows derived from the same diff, and then
REFRESHES the slot:

    task.complete   a task's status moved to done
    task.commit     a task's commit moved null -> SHA
    phase.signoff   a phase's status moved to done

This HOOK is the only writer of those actions -- a prose instruction to append
them would be a second writer, and two writers means duplicate rows. Tokens are
deliberately NOT in these rows: metering lands on Stop/SessionEnd, so any number
written here would be wrong; the cross-anchor is the ledger, joined by taskId.

THE REFRESH IS WHAT MAKES THE POST PASS TOOL-AGNOSTIC (F194). The Post pass used
to CONSUME the slot -- load and delete -- which made the pre-image a one-shot for
the Pre pass that wrote it. A Pre pass only runs for an edit tool, so the next
write of the session had a baseline only if it too arrived through one. Refreshed
instead, the slot always holds the target as of the last row this hook wrote, and
the PRE pass stays: the slot is keyed per (session, target), so without it the
FIRST write of every session would have no baseline and lose its derived rows.
Pre seeds, Post keeps fresh.

WHAT THE BASH PASS CANNOT DO, and what it says instead. A Bash payload names no
path, so the pass sweeps the paths this hook records -- the manifest index, the
phase shards beside it, the config -- and compares each digest against its slot.
A path with NO slot cannot be judged at all: the pass seeds one and claims
nothing, because a row asserting a change it has no basis for is worse than no
row. A path that moved with no PARSEABLE pre-image is the other half, and there
the write IS known: the row is the generic summary plus `DERIVATION_MISSED`,
which turns a silent gap into a stated one. Both halves are also why the slot is
seeded on the way past rather than only when something moved.

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
  * a write by something that is not a tool call at all -- another terminal, a
    background job, a `git checkout`. guard-bash-writes reports what it can, and
    `verify` sees the file move with no row to explain it (out-of-band drift).
    A shell write INSIDE a Bash call (`sed -i`, `>`, `python3 -c`) is no longer in
    this list: the Bash pass sees the digest move and records it.
  * a path this hook does not record. The Bash sweep is a closed list on purpose;
    widening it to the repository is how the journal would decay into a shell log.
  * a manifest whose bytes cannot be read at all, on either side of the write.
    The digest is taken at every size, so the cap costs the field-level DIFF and
    not the detection; an unreadable file costs both, and the pass says nothing
    rather than guessing.
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

# What a row says when the write is known and the pre-image is not (F194). The gap
# used to be silence: a generic "<tool> wrote <path>" row, indistinguishable from a
# write where nothing this hook tracks had moved. A reader, `verify` and `doctor`
# can all act on a stated gap; none of them can act on silence. It rides in
# `details.reason`, an existing `_journal_io.DETAILS_KEYS` entry -- that allow-list
# DROPS what it does not know, so a freshly invented key would have left a row
# that verifies perfectly and says nothing.
DERIVATION_MISSED = ("no pre-image, so the completion records "
                     "(task.complete, task.commit, phase.signoff) were NOT "
                     "derived from this write")


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


def _snapshot(path):
    """(digest, text) of a file: the digest at ANY size, the text only under the
    cap. (None, None) when the bytes cannot be read at all.

    THE DIGEST IS THE DETECTION AND THE TEXT IS THE DIFF, and F194 is why those are
    two answers now instead of one. The old reader took neither past the cap, so a
    large manifest was not merely undiffable -- a write to it could not even be
    NOTICED, because noticing is a digest comparison. Both come out of ONE read, so
    the digest can never describe bytes the text did not."""
    try:
        digest = hashlib.sha256()
        text = None
        with open(path, "rb") as fh:
            head = fh.read(_PREIMAGE_MAX_BYTES + 1)
            digest.update(head)
            if len(head) <= _PREIMAGE_MAX_BYTES:
                text = head.decode("utf-8", "replace")
            else:
                for chunk in iter(lambda: fh.read(65536), b""):
                    digest.update(chunk)
        return "sha256:" + digest.hexdigest(), text
    except OSError:
        return None, None          # no such file yet: the slot records that too


def _write_slot(root, cfg, data, rel):
    """Snapshot `rel` into its (session, target) slot, overwriting whatever was
    there. Returns the slot path, or None when it could not be written.

    THE ONE WRITER, and both passes go through it (F194). Pre seeds the slot before
    an edit-tool write; Post refreshes it after reading, so the baseline is the
    target as of the last row in the journal rather than as of the last EDIT. Never
    raises: a slot that cannot be written costs a generic summary next time, never
    a broken write."""
    try:
        slot = _slot_path(root, cfg, data, rel)
        sha, text = _snapshot(os.path.join(str(root), rel))
        _config.ensure_local_dir(os.path.dirname(slot))
        with open(slot, "w", encoding="utf-8") as fh:
            json.dump({"path": rel,
                       "ts": _config.utc_stamp(),
                       "sha256": sha, "content": text}, fh)
        return slot
    except Exception:
        return None


def pre_cache(data, *, cfg=None, root=None):
    """The PreToolUse pass: remember the target as it stands, so the Post pass
    can diff. Returns the slot path when one was written, else None.

    Never raises, never blocks, never speaks. IT STAYS, and F194 is where that was
    decided rather than assumed: the slot is keyed per (session, target), so with
    no Pre pass the FIRST write of every session would have no baseline and would
    lose its derived rows -- a regression wearing the shape of a simplification."""
    try:
        root = root if root is not None else _config.repo_root(data)
        cfg = cfg if cfg is not None else _config.load(root)
        if not _config.journal_enabled(cfg):
            return None            # on Pre, the config on disk IS the pre-image
        action, rel, _tool, _ti = classify(data, cfg=cfg, root=root)
        if action is None:
            return None
        return _write_slot(root, cfg, data, rel)
    except Exception:
        return None


def _read_preimage(root, cfg, data, rel):
    """Load the slot for `rel` WITHOUT deleting it. None on any miss -- a miss is a
    fallback, never an error.

    It used to delete (F194), which made the pre-image a one-shot belonging to the
    Pre pass that wrote it. A Pre pass runs only for an edit tool, so the session's
    next write had a baseline only if it too arrived through one. `_write_slot` is
    the one writer now, and the Post pass calls it on the way past."""
    try:
        slot = _slot_path(root, cfg, data, rel)
        with open(slot, "r", encoding="utf-8") as fh:
            obj = json.load(fh)
        if isinstance(obj, dict) and obj.get("path") == rel:
            return obj
    except Exception:
        pass
    return None


def _parse_preimage(pre):
    """The pre-image as a parsed document, or None when there is not one to parse
    -- no slot, an over-the-cap slot, or bytes that are not JSON.

    ONE PREDICATE for all three, because the row says the same thing about all
    three: the write happened, and what moved inside it is not knowable."""
    if not isinstance(pre, dict) or not isinstance(pre.get("content"), str):
        return None
    try:
        return json.loads(pre["content"])
    except Exception:
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


# --- the unsandboxed Bash run ------------------------------------------------
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

    THE FLAG IS STILL READ BEFORE ANYTHING ELSE IN HERE, and the reason it used to
    give is no longer the reason. It said that resolving the repo root and loading
    the config on every Bash call would charge every command in the session for a
    rare event -- true then, and F194 spent exactly that: `bash_entries` resolves
    both before this function is reached, because deciding whether the manifest
    moved needs the config that says where the manifest IS. What survives is the
    narrower guarantee: a sandboxed call still builds no row and reads no command
    text, and this function still costs nothing to call.

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


# --- the rows a write owes ---------------------------------------------------
def _manifest_rows(entry, rel, old_obj, new_obj):
    """(primary, chained) for a write to the manifest: the diff folded into the
    primary row, plus the completion rows derived from the SAME comparison.

    ONE HOME FOR BOTH LANES. The edit lane learns the path from the payload and the
    Bash lane learns it from the digest that moved; past that point the row is
    identical, so a second copy is how the two lanes would come to disagree about
    what a `task.complete` row says.

    A missing document on EITHER side is the stated gap, not a quiet generic row:
    the write is known to have happened and the field-level answer is not
    available, which is the F194 shape whatever produced it."""
    row = dict(entry)
    if old_obj is None or new_obj is None:
        row["summary"] = "%s (%s)" % (row["summary"], DERIVATION_MISSED)
        row["details"] = {"reason": DERIVATION_MISSED}
        return row, []
    diff = semantic_diff(old_obj, new_obj)
    if diff is None:
        return row, []             # nothing this hook tracks moved: not a gap
    row["summary"] = diff["summary"]
    row["details"] = {"changes": diff["changes"]}
    return row, [{"action": ev["action"], "target": rel,
                  "summary": ev["summary"], "details": ev["details"],
                  "actor": dict(row["actor"])}
                 for ev in diff["events"]]


def _config_rows(entry, old_obj, new_obj):
    """(primary, chained) for a write to the config. Never chains -- the config's
    news is the flip itself, folded into the one row, and there is no derived row
    to lose. Shaped like `_manifest_rows` so `post_entries` and `bash_entries`
    read one way for both targets."""
    row = dict(entry)
    flip = (_journal_flip(old_obj, new_obj)
            if old_obj is not None and new_obj is not None else None)
    if flip is not None:
        row["summary"] = ("journal.enabled %s->%s"
                          % (str(flip["from"]).lower(), str(flip["to"]).lower()))
        row["details"] = {"changes": [flip]}
    return row, []


def _bash_targets(root, cfg):
    """The paths a Bash call could have written that this hook records, in a
    stable order: the manifest index, the phase shards beside it, the config.

    A CLOSED LIST ON PURPOSE. A Bash payload carries a command and no `file_path`,
    so the pass cannot ask "what did this write" and has to ask "which of the
    paths I record moved". Widening the list to the repository is precisely how the
    journal would decay into a shell log, which THE ONE EXCEPTION above is careful
    not to do. A shard that does not exist is not listed and a directory that
    cannot be read contributes nothing -- both cost the sweep a path, never a
    crash."""
    manifest_rel = (cfg.get("manifestPath")
                    or _config.DEFAULTS["manifestPath"])
    out = [manifest_rel]
    mdir = os.path.dirname(manifest_rel)
    shard_dir = (mdir + "/" if mdir else "") + "phases"
    try:
        names = sorted(os.listdir(os.path.join(str(root), shard_dir)))
    except OSError:
        names = []
    out.extend(shard_dir + "/" + name for name in names
               if name.endswith(".json"))
    out.append(_config.CONFIG_REL)
    return out


def bash_entries(data, *, cfg=None, root=None):
    """The PostToolUse pass for Bash: the unsandboxed row, plus whatever the paths
    this hook records did while the shell ran. F194.

    THE QUESTION IS ASKED OF THE FILE, NOT OF THE PAYLOAD. `classify()` reads
    `file_path` and returns None for anything that is not an edit tool, which was
    the whole root: a session writing the manifest through `python3 -c` produced a
    chain that verified over a history with no `task.complete` in it. Here each
    recorded path's digest is compared against its slot, so the tool that made the
    write stops being part of the answer.

    NO SLOT IS NOT A CHANGE. A path with no slot has no baseline, so the pass seeds
    one and claims nothing -- a row asserting a move it cannot see would be a claim
    with no basis, and the first Bash call of every session would file one. The
    seeding is what makes the session's NEXT write diffable whatever writes it.

    A MOVE WITH NO PARSEABLE PRE-IMAGE IS THE OTHER HALF, and there the write is
    known: the row carries `DERIVATION_MISSED` instead of the diff, which is the
    point of the exercise -- silence became a stated gap.

    The user's switch still wins, with the same exception the edit lane has: when
    the CONFIG itself moved, `journal.enabled` is judged against the pre-image, so
    a shell that flips the switch off is journalled by its own last row."""
    root = root if root is not None else _config.repo_root(data)
    cfg = cfg if cfg is not None else _config.load(root)
    rows = unsandboxed_entries(data, cfg=cfg, root=root)
    enabled = _config.journal_enabled(cfg)
    # With the switch off the ONLY path that can still owe a row is the config, and
    # only because of the flip that turned it off - judged against the pre-image, as
    # on the edit lane. Sweeping the manifest here would be the plugin doing work
    # after being told to stop, and stating a shard directory it must not read.
    for rel in (_bash_targets(root, cfg) if enabled else [_config.CONFIG_REL]):
        # The journal is never its own subject, on this lane too. guard-edits
        # refuses that write and no default layout puts a journal file behind one
        # of these names, so this is the structural half of a property that would
        # otherwise hold by luck.
        if _config.in_journal(root, cfg, rel):
            continue
        pre = _read_preimage(root, cfg, data, rel)
        now_sha = _snapshot(os.path.join(str(root), rel))[0]
        if pre is None:
            if enabled and now_sha is not None:
                _write_slot(root, cfg, data, rel)
            continue
        if now_sha is None or now_sha == pre.get("sha256"):
            continue               # unreadable, or it did not move
        old_obj = _parse_preimage(pre)
        is_cfg = (rel == _config.CONFIG_REL)
        allowed = enabled
        if is_cfg and old_obj is not None:
            allowed = _config.journal_enabled(old_obj)
        if not allowed:
            continue
        entry = _entry("config.edit" if is_cfg else "manifest.edit",
                       rel, "Bash", {}, data, root, cfg)
        new_obj = (_read_json(os.path.join(str(root), rel))
                   if old_obj is not None else None)
        primary, chained = (_config_rows(entry, old_obj, new_obj) if is_cfg
                            else _manifest_rows(entry, rel, old_obj, new_obj))
        rows.append(primary)
        rows.extend(chained)
        if enabled:
            _write_slot(root, cfg, data, rel)
    return rows


def post_entries(data, *, cfg=None, root=None):
    """The PostToolUse pass. Returns the list of entries to append: the primary
    row (semantic when the pre-image allows, generic otherwise) followed by any
    completion-event rows. Empty list = nothing to record. Never raises.

    Bash is handed to `bash_entries`, which asks the FILE what moved because the
    payload names no path; everything else goes through `classify()` as before. The
    outer `except` is the fail-open net for BOTH lanes -- it runs at PostToolUse, so
    anything that escapes here breaks the write it was recording.

    The disable loophole is closed HERE: when the config itself is the target,
    `journal.enabled` is judged against the pre-image, so a true->false flip is
    journalled as a final config.edit row instead of silencing its own record."""
    try:
        if data.get("tool_name") == "Bash":
            return bash_entries(data, cfg=cfg, root=root)
        root = root if root is not None else _config.repo_root(data)
        cfg = cfg if cfg is not None else _config.load(root)
        action, rel, tool, ti = classify(data, cfg=cfg, root=root)
        if action is None:
            return []
        pre = _read_preimage(root, cfg, data, rel)
        old_obj = _parse_preimage(pre)
        # REFRESHED, NOT CONSUMED (F194), and here rather than after the row is
        # built so that every path out of this function leaves the same baseline
        # behind. The slot now holds the target as of the last write this hook
        # SAW, which is what lets the next write be diffed whatever makes it. The
        # current config gates it, not the pre-image judgement below: once the
        # switch is off there is no next row for a baseline to serve.
        enabled = _config.journal_enabled(cfg)
        if enabled:
            _write_slot(root, cfg, data, rel)
        if action == "config.edit" and old_obj is not None:
            enabled = _config.journal_enabled(
                old_obj if isinstance(old_obj, dict) else {})
        if not enabled:
            return []
        entry = _entry(action, rel, tool, ti, data, root, cfg)
        new_obj = (_read_json(os.path.join(str(root), rel))
                   if old_obj is not None else None)
        primary, chained = (_config_rows(entry, old_obj, new_obj)
                            if action == "config.edit"
                            else _manifest_rows(entry, rel, old_obj, new_obj))
        return [primary] + chained
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
