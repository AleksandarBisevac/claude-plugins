#!/usr/bin/env python3
"""
audit-task.py -- the non-interactive task writer for /audit:task add (v0.37 C1).

/audit:task add used to dictate a hand-template into the model's hands: every
newly created task MUST carry status/attempts/maxAttempts/commit/outcome/
startedAt/completedAt/verifiedBy plus explicit blockedBy/dependsOn and a tests
object (manifest-conventions.md -> New task template) -- and hand-templating
fifteen-odd fields per add is a CLASS of error: a missed field, a misspelled
enum, a fileIndex nobody extended. This script IS the template. The command
gathers answers; this writes them, the same way every time, exactly once.

Usage:
  audit-task.py add "<title>" [manifest] [--phase P2]
                [--skills a,b | --skills null] [--model m] [--files f1,f2]
                [--risk low|med|high] [--blocked-by id,id] [--depends-on id,id]
                [--description TEXT] [--tests-mode tdd|regression|gate-only]
                [--tests-add TEXT ...] [--gate CMD ...]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py --selftest

  <manifest> defaults to the project's configured manifestPath
  (.claude/audit.config.json, default docs/audit/audit-plan.json).
  --phase absent -> the single in_progress phase when that is unambiguous,
  else exit 2 naming the choices. --skills null is the explicit opt-out
  (v0.37 B1): written as JSON null, it STOPS the area fallback; absent/empty
  means "unconsidered" and is written as [] (the area default stays in
  force). A skill literally named "null" cannot be spelled from this flag;
  no such skill exists. --tests-add and --gate repeat (one value each).

Exit codes:
  0  task written, manifest valid
  1  refused invalid: the manifest had findings before the add (nothing
     written), or the add itself would leave it invalid (every written file
     rolled back byte-for-byte); the findings are printed either way
  2  usage: unknown/ambiguous/done/reserved phase, missing manifest, bad args
  3  the index lock is held by a LIVE run (audit-lock's standard message)
  4  the index lock looks abandoned -- rerun with --takeover once a human
     has confirmed (audit-lock's standard message)

Design decisions, each mirroring a precedent rather than inventing one:

  * PROJECT (F-C-1). Which root owns the journal, the lock, the config and
    the file-existence notes: an explicit --project-dir wins; else a NAMED
    manifest derives the project upward from ITSELF (first ancestor holding
    `.claude/` or `.git` -- naming another project's manifest from this cwd
    must not journal or lock into THIS repo, the class audit-usage's
    resolve_ledger already solved); else $CLAUDE_PROJECT_DIR, else the cwd.

  * LOCK. The whole read-allocate-write runs under the INDEX lock, taken via
    audit-lock.py's own module (`main(["acquire", "index", ...])`) -- ids are
    allocated under the lock so two sessions can never mint the same one
    (manifest-conventions.md -> ID allocation). A held or stale lock prints
    the lock module's OWN output: one message shape everywhere. Outside a git
    repo the `<manifest>.lock` working-tree file is the fallback guard,
    exactly as in _panel_write._acquire_write_lock.

  * ID. `<phaseId>.<n>`, n = highest existing numeric suffix + 1, computed
    over the WHOLE assembled manifest plus every still-parked proposal
    payload -- gaps are history and never re-minted. A --phase naming an id
    RESERVED by a parked proposal is refused toward /audit:propose
    materialize (materialization is a move; hand-minting into a reserved id
    would make it a collision).

  * WRITE. Through _manifest_io -- never raw json for the sharded case. The
    footprint is _panel_write._write_back's: the touched phase's shard, plus
    the index only when fileIndex changed (meta lives there; rewriting
    untouched shards would manufacture merge conflicts the sharded layout
    exists to avoid). After the write the manifest is re-read from disk and
    validated in-process; findings roll every written file back
    byte-for-byte and exit 1 -- this script refuses to leave an invalid
    manifest behind.

  * HEAL (v0.37 A4). Reuses _panel_write._heal_phase_status on the target
    phase: a write this code makes must not persist a pending phase that
    already holds an in_progress task. The validator warning stays as the
    backstop for hand edits.

  * JOURNAL. A `task.add` row through audit-journal's `append`, in-process --
    see _journal_add for why the journal-writes hook cannot see this write.

This module carries no `--selftest` of its own any more; its 83 cases live in
`plugins/audit/tests/test_audit_task.py`, byte-identical labels and all - see
`plugins/audit/tests/_harness.py`. The note on which id LETTERS the suite has
already taken went with them, because it is advice to whoever adds the next case.

Stdlib only, Python 3.8 compatible.
"""
import argparse
import json
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _manifest_io as _mio   # noqa: E402  (dual-format loader; single-file OR index+shards)
import _panel_write           # noqa: E402  (one answer to "where is the manifest", the
#                                            byte-shape writer, the A4 heal, the lock and
#                                            journal module handles -- reused by identity,
#                                            not reimplemented)

E_INVALID, E_USAGE, E_LIVE, E_STALE = 1, 2, 3, 4

# The conventions template (manifest-conventions.md -> New task template), as
# data: every field a new task is initialized with, in the order it is written.
_TEMPLATE_KEYS = ("id", "title", "status", "description", "files", "tests",
                  "model", "skills", "risk", "blockedBy", "dependsOn",
                  "attempts", "maxAttempts", "commit", "outcome", "startedAt",
                  "completedAt", "verifiedBy")


# --- flag parsing helpers ------------------------------------------------------
def _split_csv(val):
    """`a,b , c` -> ["a", "b", "c"]; None/empty -> []."""
    if not isinstance(val, str):
        return []
    return [part.strip() for part in val.split(",") if part.strip()]


def _parse_skills(val):
    """Three states, spelled the way the schema spells them (v0.37 B1):
    absent/empty -> [] (unconsidered; the area default stays in force);
    the literal `null` -> None (the explicit opt-out, JSON null in the file,
    stopping the area fallback); anything else -> the comma-split list."""
    if not isinstance(val, str) or not val.strip():
        return []
    if val.strip() == "null":
        return None
    return _split_csv(val)


# --- project resolution --------------------------------------------------------
def _project_of_manifest(mpath):
    """The project root a NAMED manifest belongs to: the first ancestor of the
    manifest (starting at its own directory) that holds a `.claude/` dir or a
    `.git` entry.

    MARKERLESS fallback (F-C-2): when the manifest sits in the default layout
    (`<T>/docs/audit/<file>`), the root is `<T>` -- taking the manifest's own
    directory doubled the layout (the journal's default rel re-appended
    `docs/audit` under `.../docs/audit`). Anywhere else the root is the
    manifest's own directory. Either way the root stays INSIDE the named
    manifest's tree, never another repo's."""
    start = os.path.dirname(os.path.abspath(mpath))
    cur = start
    while True:
        if os.path.isdir(os.path.join(cur, ".claude")) \
                or os.path.exists(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    if os.path.basename(start) == "audit" \
            and os.path.basename(os.path.dirname(start)) == "docs":
        return os.path.dirname(os.path.dirname(start))
    return start


def _resolve_project(args):
    """Which root owns the journal, the lock, the config and the file notes.

    F-C-1: keying this off the cwd while the manifest was explicitly named
    wrote the `task.add` journal row into the CWD repo's journal -- the exact
    class audit-usage's resolve_ledger solved ("When a manifest was named,
    search upward from IT"). The decision table:

      explicit --project-dir            -> it (the human said so)
      else a NAMED manifest             -> derived upward from the manifest
                                           ITSELF (beats CLAUDE_PROJECT_DIR:
                                           the env names the session's repo,
                                           the positional names THIS add's)
      else                              -> $CLAUDE_PROJECT_DIR, then the cwd
                                           (audit-usage's resolve_project
                                           order)
    """
    if args.project_dir:
        return os.path.abspath(args.project_dir)
    if args.manifest:
        return _project_of_manifest(args.manifest)
    return os.path.abspath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


# --- the lock ------------------------------------------------------------------
def _acquire_lock(project, config, mpath, takeover, out):
    """Take the index lock for the whole read-allocate-write. Returns a lock
    handle dict, or an int exit code AFTER printing the lock module's own
    message -- the standard shape a human already knows from audit-lock.py
    and the panel; this script adds only its own next step."""
    lockmod = _panel_write._lockmod()
    git_root = os.path.join(project, (config or {}).get("gitRoot") or ".")
    if lockmod is not None:
        lines = []
        argv = ["acquire", "index", "--project", git_root, "--note", "task add"]
        if takeover:
            argv.append("--takeover")
        try:
            code = lockmod.main(argv, out=lines.append)
        except Exception:
            code = None
        if code == 0:
            return {"held": True, "mod": lockmod, "project": git_root}
        if code == getattr(lockmod, "E_LIVE", 3):
            for line in lines:
                out(line)
            return E_LIVE
        if code == getattr(lockmod, "E_STALE", 4):
            for line in lines:
                out(line)
            out("[audit-task] once a human has confirmed, rerun this add "
                "with --takeover.")
            return E_STALE
        # Not a git repo (or the lock library refused for a reason of its
        # own): fall through to the legacy working-tree lockfile -- guard a
        # single clone rather than writing unguarded (_panel_write precedent).
    legacy = mpath + ".lock"
    try:
        fd = os.open(legacy, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        return {"held": True, "legacy": legacy}
    except FileExistsError:
        out("[audit-task] manifest is locked by a running /audit command "
            "(%s exists); try again once it finishes"
            % os.path.basename(legacy))
        return E_LIVE
    except OSError:
        return {"held": False}


def _release_lock(lock):
    """Give the lock back. Never raises: a write that succeeded must not be
    reported as failed because the release did (_panel_write precedent)."""
    if not lock or not lock.get("held"):
        return
    try:
        if lock.get("legacy"):
            os.unlink(lock["legacy"])
            return
        lock["mod"].main(["release", "index", "--project", lock["project"]],
                         out=lambda *_a, **_k: None)
    except Exception:
        pass


# --- phase resolution + id allocation ------------------------------------------
def _phase_label(ph):
    return "%s (%s)" % (ph.get("id"), ph.get("status"))


def _resolve_phase(assembled, want, out):
    """The target phase dict, or an int exit code after printing why not."""
    phases = [p for p in (assembled.get("phases") or []) if isinstance(p, dict)]
    if want:
        for ph in phases:
            if ph.get("id") == want:
                if ph.get("status") == "done":
                    out("[audit-task] phase %s is done -- done phases are "
                        "immutable history. Pick an open phase, or create a "
                        "new one via /audit:task's interactive flow." % want)
                    return E_USAGE
                return ph
        for prop in (assembled.get("proposals") or []):
            if not isinstance(prop, dict) or prop.get("status") != "proposed":
                continue
            payload = prop.get("payload")
            pphase = payload.get("phase") if isinstance(payload, dict) else None
            if isinstance(pphase, dict) and pphase.get("id") == want:
                out("[audit-task] phase %s is RESERVED by parked proposal %s "
                    "-- run /audit:propose materialize %s first "
                    "(materialization is a move; minting into a reserved id "
                    "by hand would collide)."
                    % (want, prop.get("id"), prop.get("id")))
                return E_USAGE
        out("[audit-task] no phase %s in the manifest; phases: %s"
            % (want, ", ".join(_phase_label(p) for p in phases) or "(none)"))
        return E_USAGE
    inprog = [p for p in phases if p.get("status") == "in_progress"]
    if len(inprog) == 1:
        return inprog[0]
    if not inprog:
        openp = [p for p in phases if p.get("status") != "done"]
        out("[audit-task] no in_progress phase to default to -- pass --phase. "
            "Open phases: %s"
            % (", ".join(_phase_label(p) for p in openp) or "(none)"))
        return E_USAGE
    out("[audit-task] --phase required -- %d phases are in_progress: %s"
        % (len(inprog), ", ".join(p.get("id") or "?" for p in inprog)))
    return E_USAGE


def _allocate_id(assembled, phase_id):
    """`<phaseId>.<n>`, n = highest existing numeric suffix + 1, over the
    WHOLE assembled manifest (a misfiled task still counts) plus every
    still-parked proposal payload (reserved ids stay reserved). Gaps are
    history: P2.1 + P2.3 allocate P2.4, never P2.2 again."""
    prefix = str(phase_id) + "."
    top = 0

    def _count(tasks):
        nonlocal top
        for t in tasks:
            if not isinstance(t, dict):
                continue
            tid = str(t.get("id") or "")
            if tid.startswith(prefix) and tid[len(prefix):].isdigit():
                top = max(top, int(tid[len(prefix):]))

    # The manifest's own tasks come from `_mio.iter_tasks`; the proposal payloads
    # below cannot, because a parked payload's phase is NOT in `manifest["phases"]`
    # yet — reserving its ids is the whole point of reading it separately.
    _count(t for _ph, t in _mio.iter_tasks(assembled))
    for prop in (assembled.get("proposals") or []):
        if not isinstance(prop, dict) or prop.get("status") != "proposed":
            continue
        payload = prop.get("payload")
        pphase = payload.get("phase") if isinstance(payload, dict) else None
        if isinstance(pphase, dict):
            _count(pphase.get("tasks") or [])
    return "%s%d" % (prefix, top + 1)


# --- write-back + rollback -----------------------------------------------------
def _snapshot(paths):
    """{path: bytes-or-None} for everything a rollback must restore."""
    snap = {}
    for path in paths:
        try:
            with open(path, "rb") as fh:
                snap[path] = fh.read()
        except OSError:
            snap[path] = None
    return snap


def _restore(snap):
    """Put every snapshotted file back byte-for-byte (temp + os.replace, the
    same atomicity the write had). A file that did not exist is removed."""
    for path, data in snap.items():
        if data is None:
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        d = os.path.dirname(path) or "."
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


def _write_paths(project, mpath, raw_index, phase_id):
    """The files an add MAY touch, for the pre-write snapshot: the manifest
    itself, plus the target phase's shard in the sharded layout."""
    paths = [mpath]
    if _mio.is_sharded(raw_index):
        base = os.path.dirname(os.path.abspath(mpath))
        for stub in (raw_index.get("phases") or []):
            if isinstance(stub, dict) and stub.get("id") == phase_id \
                    and "shard" in stub:
                paths.append(os.path.abspath(os.path.join(base, stub["shard"])))
    return paths


def _write_add(project, mpath, raw_index, assembled, phase_id, files_changed):
    """Persist the patched manifest into whichever layout it is stored in.
    SINGLE FILE: write the assembled dict; it IS the file. SHARDED: the
    touched phase's shard, and the index only when fileIndex changed --
    _panel_write._write_back's footprint, for its reasons. Returns the
    project-relative paths written (shard first, index-precedent order)."""
    if not _mio.is_sharded(raw_index):
        _panel_write._atomic_write_json(mpath, assembled)
        return [os.path.relpath(mpath, project)]
    base = os.path.dirname(os.path.abspath(mpath))
    by_pid = {p.get("id"): p for p in (assembled.get("phases") or [])
              if isinstance(p, dict)}
    written = []
    index_dirty = bool(files_changed)
    stub = None
    for entry in (raw_index.get("phases") or []):
        if isinstance(entry, dict) and entry.get("id") == phase_id:
            stub = entry
            break
    if stub is not None and "shard" in stub:
        spath = os.path.abspath(os.path.join(base, stub["shard"]))
        if not _panel_write._within(project, spath):
            raise ValueError("refused: shard path escapes project: %s"
                             % stub["shard"])
        body = dict(by_pid.get(phase_id) or {})
        body.pop("shard", None)   # the stub owns the pointer, never the body
        _panel_write._atomic_write_json(spath, body)
        written.append(os.path.relpath(spath, project))
    else:
        # Inline phase in a sharded index (mixed/defensive): its body lives in
        # the index itself, so the index write below must carry it.
        idx_phases = raw_index.get("phases") or []
        for i, entry in enumerate(idx_phases):
            if isinstance(entry, dict) and entry.get("id") == phase_id:
                idx_phases[i] = by_pid.get(phase_id) or entry
                index_dirty = True
    if index_dirty:
        idx = dict(raw_index)
        if files_changed:
            idx["fileIndex"] = assembled.get("fileIndex") or {}
        _panel_write._atomic_write_json(mpath, idx)
        written.append(os.path.relpath(mpath, project))
    return written


# --- the journal ---------------------------------------------------------------
def _journal_add(project, config, mpath, task_id, phase_id, title, healed):
    """One `task.add` row, appended in-process via audit-journal's `append`.

    Why this script writes its own row: the journal-writes HOOK observes
    Edit/Write/MultiEdit/NotebookEdit TOOL calls only (hooks.json's
    PostToolUse matcher) -- a manifest written by this script through
    os.replace never passes through a tool that hook can see.
    _panel_write._journal is the precedent (the panel's saves have exactly
    the same blindness), and /audit:task move's CLI append is the row-shape
    precedent: action + target + summary + allow-listed details
    ({taskId, phaseId} here, {fromId, toId, ...} there) -- no new shape is
    invented. Fail-soft by the same contract: a task that WAS written must
    never be reported as failed because the record of it could not be."""
    mod = _panel_write._journalmod()
    if mod is None or not hasattr(mod, "append"):
        return {"journaled": False, "journaledWhy": "unavailable"}
    summary = "%s added to %s: %s" % (task_id, phase_id, title)
    if healed:
        summary += "; " + "; ".join(_panel_write._fmt_change(r) for r in healed)
    # THE PLACEMENT RULE (F-C-2): the journal lands in a sane place INSIDE
    # the named manifest's tree -- never doubled, never outside. A project
    # with a config keeps its own answer (config=None -> audit-journal's
    # load_config resolves journal.dir/manifestPath/enabled exactly as
    # before). A project with NO config would get audit-journal's DEFAULT
    # manifestPath rel appended under the resolved root -- doubling the
    # layout, or conjuring docs/audit into a bare tree -- so the handed-over
    # config pins manifestPath to where the named manifest actually IS, and
    # the journal lands beside it (<manifest dir>/journal).
    cfg = None if config else \
        {"manifestPath": os.path.relpath(mpath, project)}
    try:
        ok = bool(mod.append(project, {
            "action": "task.add",
            # Persisted row: "/" separators regardless of platform, like every
            # other journal path (n3 pins it; Windows relpath says backslash).
            "target": os.path.relpath(mpath, project).replace(os.sep, "/"),
            "summary": summary,
            "details": {"taskId": task_id, "phaseId": phase_id},
            "actor": {"author": _panel_write._viewer(project,
                                                    config).get("author"),
                      "sessionId": os.environ.get("CLAUDE_CODE_SESSION_ID"),
                      "via": "cli"}}, config=cfg))
    except Exception:
        ok = False
    return {"journaled": True} if ok else {"journaled": False,
                                           "journaledWhy": "failed"}


# --- readiness (report only) ---------------------------------------------------
def _waiting_on(assembled, task):
    """The blockedBy/dependsOn refs that are not done yet -- what the report
    prints so the human knows whether /audit:run can start this now.

    Phases are walked directly and only the TASKS come from `_mio.iter_tasks`: a
    task can be blocked by a whole phase, and a phase with no tasks of its own
    yields nothing from `iter_tasks` -- so a one-pass index would forget it exists
    and report the dependent task as ready. Phase and task ids share this map, so
    a collision resolves task-wins rather than by document order; both callers
    reach here only after `vm.validate` has already refused the manifest that
    could have one (`duplicate id` is a finding, not a warning)."""
    status = {}
    for ph in (assembled.get("phases") or []):
        if isinstance(ph, dict) and ph.get("id"):
            status[ph["id"]] = ph.get("status")
    for _ph, t in _mio.iter_tasks(assembled):
        if t.get("id"):
            status[t["id"]] = t.get("status")
    refs = list(task.get("blockedBy") or []) + list(task.get("dependsOn") or [])
    return _mio.unsatisfied(refs, status)


# --- the add -------------------------------------------------------------------
def _build_task(task_id, title, args, phase):
    """The new task, fully template-initialized -- every field from the
    conventions' New task template, exactly once, in _TEMPLATE_KEYS order."""
    risk = args.risk or "low"
    # sonnet is the floor for all fix work; risk high escalates to opus unless
    # the caller chose explicitly (commands/task.md's long-standing rule).
    model = args.model or ("opus" if risk == "high" else "sonnet")
    mode = args.tests_mode or "gate-only"
    if args.gate:
        gate = list(args.gate)
    else:
        gate = [g for g in (phase.get("testGate") or []) if isinstance(g, str)]
    return {
        "id": task_id,
        "title": title,
        "status": "pending",
        "description": args.description or "",
        "files": _split_csv(args.files),
        "tests": {
            "mode": mode,
            "add": list(args.tests_add or []),
            # true iff tdd -- the machine-readable disambiguation of `add`.
            "expectRedFirst": mode == "tdd",
            "gate": gate,
        },
        "model": model,
        "skills": _parse_skills(args.skills),
        "risk": risk,
        "blockedBy": _split_csv(args.blocked_by),
        "dependsOn": _split_csv(args.depends_on),
        "attempts": 0,
        "maxAttempts": 3,
        "commit": None,
        "outcome": {"technical": None, "descriptive": None},
        "startedAt": None,
        "completedAt": None,
        "verifiedBy": [],
    }


def _locked_add(args, project, config, mpath, title, out):
    """Everything between acquire and release: read, allocate, mutate, write,
    validate-from-disk, roll back on findings, journal, report."""
    try:
        raw_index = _mio.read_json(mpath)
        assembled = _mio.load_manifest(mpath)
    except Exception as exc:
        out("[audit-task] cannot read/assemble manifest: %s" % exc)
        return E_USAGE
    if not isinstance(assembled, dict) or not isinstance(raw_index, dict):
        out("[audit-task] manifest root is not an object")
        return E_USAGE

    vm = _panel_write._cores()[0]
    pre_findings, _pre_w = vm.validate(assembled)
    if pre_findings:
        # Refusing BEFORE the write is what tells "your add broke it" apart
        # from "it was broken when you arrived" -- the rollback below is
        # reserved for the first.
        out("[audit-task] the manifest is already invalid -- nothing "
            "written; fix these first:")
        for line in pre_findings:
            out("FINDING: " + line)
        return E_INVALID

    phase = _resolve_phase(assembled, args.phase, out)
    if isinstance(phase, int):
        return phase
    phase_id = phase.get("id")

    task_id = _allocate_id(assembled, phase_id)
    task = _build_task(task_id, title, args, phase)
    missing = [f for f in task["files"]
               if not os.path.exists(os.path.join(project, f))]

    phase.setdefault("tasks", []).append(task)
    fidx = assembled.setdefault("fileIndex", {})
    for fpath in task["files"]:
        entry = fidx.setdefault(fpath, [])
        if task_id not in entry:
            entry.append(task_id)
    # v0.37 A4, at THIS write site too: reused from _panel_write, scoped to
    # the target phase -- the one shard this add writes anyway.
    healed = _panel_write._heal_phase_status({"phases": [phase]})

    snap = _snapshot(_write_paths(project, mpath, raw_index, phase_id))
    try:
        written = _write_add(project, mpath, raw_index, assembled, phase_id,
                             bool(task["files"]))
    except Exception as exc:
        _restore(snap)
        out("[audit-task] write failed -- manifest restored: %s" % exc)
        return E_INVALID
    try:
        findings, warnings = vm.validate(_mio.load_manifest(mpath))
    except Exception as exc:
        findings, warnings = ["cannot re-read the written manifest: %s"
                              % exc], []
    if findings:
        _restore(snap)
        out("[audit-task] REFUSED: the add would leave the manifest invalid "
            "-- every written file rolled back, nothing kept:")
        for line in findings:
            out("FINDING: " + line)
        return E_INVALID

    jres = _journal_add(project, config, mpath, task_id, phase_id, title,
                        healed)
    waiting = _waiting_on(assembled, task)
    if args.as_json:
        result = {"ok": True, "id": task_id, "phase": phase_id,
                  "title": title, "task": task, "written": written,
                  "healed": healed, "warnings": warnings,
                  "filesNotOnDisk": missing,
                  "ready": not waiting, "waitingOn": waiting}
        result.update(jres)
        out(json.dumps(result, indent=2, sort_keys=True))
        return 0
    out("[audit-task] %s added to %s -- %s" % (task_id, phase_id, title))
    out("  tests.mode %s  model %s  risk %s  skills %s"
        % (task["tests"]["mode"], task["model"], task["risk"],
           json.dumps(task["skills"])))
    if task["files"]:
        out("  files: %d (fileIndex updated)" % len(task["files"]))
    for fpath in missing:
        out("  note: not on disk (a new file?): %s" % fpath)
    for row in healed:
        out("  healed: %s" % _panel_write._fmt_change(row))
    for line in warnings:
        out("WARNING: " + line)
    if not jres.get("journaled") and jres.get("journaledWhy") == "failed":
        out("  journal: the audit trail did NOT take the task.add row")
    out("  written: %s" % ", ".join(written))
    if waiting:
        out("  waiting on: %s" % ", ".join(waiting))
    else:
        out("  ready now -- /audit:run %s" % task_id)
    return 0


# --- cancel: finished, but not done ---------------------------------------------
# ca (F-P-4, v0.40): a phase or task can end without landing — the feature was
# dropped, the approach abandoned — and until this verb the only way to say so
# was to hand-edit the manifest. Three things then went unrecorded, every time:
# WHY (the reason lived in somebody's memory), WHEN (no stamp), and THAT IT
# HAPPENED AT ALL (no journal row). The verb writes all three through the same
# lock / write / validate-from-disk / roll-back path `add` uses.
_NOW_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _utc_now():
    import time
    return time.strftime(_NOW_FMT, time.gmtime())


def _find_target(assembled, tid):
    """(kind, node, phase) for a task or phase id, or (None, None, None).

    Phases are swept first and in full, because a phase can be cancelled before
    it has a single task and `_mio.iter_tasks` yields nothing for such a phase.
    The task sweep then takes its owning phase from the pair rather than tracking
    it in an enclosing loop -- that phase is the third return value, and the one
    `_locked_cancel` writes the shard for."""
    for ph in (assembled.get("phases") or []):
        if isinstance(ph, dict) and ph.get("id") == tid:
            return "phase", ph, ph
    for ph, t in _mio.iter_tasks(assembled):
        if t.get("id") == tid:
            return "task", t, ph
    return None, None, None


def _cancel_task(task, reason, now):
    """Mark one task cancelled. The reason goes where the report already reads
    from — outcome.descriptive — so it shows up in the detail row without a
    field invented for it, and `completedAt` is the moment it stopped being
    work rather than the moment it landed (it never landed)."""
    task["status"] = "cancelled"
    if not task.get("completedAt"):
        task["completedAt"] = now
    outcome = task.get("outcome")
    if not isinstance(outcome, dict):
        outcome = {}
    prefix = "Cancelled: %s" % reason
    prev = (outcome.get("descriptive") or "").strip()
    outcome["descriptive"] = ("%s (was: %s)" % (prefix, prev)) if prev else prefix
    task["outcome"] = outcome
    return task


def _locked_cancel(args, project, config, mpath, tid, reason, out):
    try:
        raw_index = _mio.read_json(mpath)
        assembled = _mio.load_manifest(mpath)
    except Exception as exc:
        out("[audit-task] cannot read/assemble manifest: %s" % exc)
        return E_USAGE
    vm = _panel_write._cores()[0]
    pre_findings, _w = vm.validate(assembled)
    if pre_findings:
        out("[audit-task] the manifest is already invalid -- nothing written; "
            "fix these first:")
        for line in pre_findings:
            out("FINDING: " + line)
        return E_INVALID

    kind, node, phase = _find_target(assembled, tid)
    if kind is None:
        out("[audit-task] no task or phase with id %r in %s" % (tid, mpath))
        return E_USAGE
    if node.get("status") in ("done", "cancelled"):
        # Terminal is terminal. Re-writing a finished item's status here would
        # rewrite history with no record of what it said before.
        out("[audit-task] %s is already %s -- terminal work is not re-decided "
            "by this verb (edit the manifest deliberately if it is wrong)"
            % (tid, node.get("status")))
        return E_USAGE

    now = _utc_now()
    cascaded = []
    if kind == "task":
        _cancel_task(node, reason, now)
    else:
        node["status"] = "cancelled"
        prev = (node.get("summary") or "").strip()
        line = "Cancelled: %s" % reason
        node["summary"] = ("%s %s" % (prev, line)).strip() if prev else line
        # A claim on a finished phase is stale (the validator says so).
        node.pop("claim", None)
        # ...and the work still open inside it goes with it: a pending task
        # under a dropped phase is a task /audit:next would still offer.
        for t in (node.get("tasks") or []):
            if isinstance(t, dict) and t.get("status") not in ("done", "cancelled"):
                _cancel_task(t, "phase %s cancelled: %s" % (tid, reason), now)
                cascaded.append(t.get("id"))

    phase_id = phase.get("id")
    snap = _snapshot(_write_paths(project, mpath, raw_index, phase_id))
    try:
        written = _write_add(project, mpath, raw_index, assembled, phase_id, False)
    except Exception as exc:
        _restore(snap)
        out("[audit-task] write failed -- manifest restored: %s" % exc)
        return E_INVALID
    try:
        findings, warnings = vm.validate(_mio.load_manifest(mpath))
    except Exception as exc:
        findings, warnings = ["cannot re-read the written manifest: %s" % exc], []
    if findings:
        _restore(snap)
        out("[audit-task] REFUSED: the cancel would leave the manifest invalid "
            "-- every written file rolled back, nothing kept:")
        for line in findings:
            out("FINDING: " + line)
        return E_INVALID

    jres = _journal_cancel(project, config, mpath, kind, tid, phase_id,
                           reason, cascaded)
    if args.as_json:
        result = {"ok": True, "id": tid, "kind": kind, "phase": phase_id,
                  "reason": reason, "at": now, "cascaded": cascaded,
                  "written": written, "warnings": warnings}
        result.update(jres)
        out(json.dumps(result, indent=2, sort_keys=True))
        return 0
    out("[audit-task] %s %s cancelled -- %s" % (kind, tid, reason))
    if cascaded:
        out("  also cancelled inside it: %s" % ", ".join(c for c in cascaded if c))
    for line in warnings:
        out("WARNING: " + line)
    if not jres.get("journaled") and jres.get("journaledWhy") == "failed":
        out("  journal: the audit trail did NOT take the %s.cancel row" % kind)
    out("  written: %s" % ", ".join(written))
    return 0


def _journal_cancel(project, config, mpath, kind, tid, phase_id, reason,
                    cascaded):
    """One `task.cancel` / `phase.cancel` row — the same shape and the same
    fail-soft contract as _journal_add (see its docstring for why this script
    writes its own row at all). The REASON rides the summary: a trail that
    records the state change and not the why answers the wrong question a
    month later."""
    mod = _panel_write._journalmod()
    if mod is None or not hasattr(mod, "append"):
        return {"journaled": False, "journaledWhy": "unavailable"}
    summary = "%s cancelled: %s" % (tid, reason)
    if cascaded:
        summary += " (also %s)" % ", ".join(c for c in cascaded if c)
    cfg = None if config else {"manifestPath": os.path.relpath(mpath, project)}
    details = {"phaseId": phase_id, "reason": reason}
    details["taskId" if kind == "task" else "cancelledId"] = tid
    if cascaded:
        details["cascaded"] = [c for c in cascaded if c]
    try:
        ok = bool(mod.append(project, {
            "action": "%s.cancel" % kind,
            "target": os.path.relpath(mpath, project).replace(os.sep, "/"),
            "summary": summary,
            "details": details,
            "actor": {"author": _panel_write._viewer(project, config or {})},
        }, cfg))
    except Exception:
        return {"journaled": False, "journaledWhy": "failed"}
    return {"journaled": ok, "journaledWhy": None if ok else "failed"}


def cmd_cancel(args, out):
    project = _resolve_project(args)
    if not os.path.isdir(project):
        out("[audit-task] not a directory: %s" % project)
        return E_USAGE
    tid = (args.title or "").strip()          # positional: the id to cancel
    if not tid:
        out("[audit-task] cancel needs a task or phase id")
        return E_USAGE
    reason = (args.reason or "").strip()
    if not reason:
        # The whole point of the verb. A status flipped with no why is the
        # hand-edit this replaces, one layer up.
        out("[audit-task] cancel needs --reason \"<why>\" -- cancelling without "
            "a recorded reason is the hand-edit this verb exists to replace")
        return E_USAGE
    config = _panel_write.read_config(project)
    mpath = (os.path.abspath(args.manifest) if args.manifest
             else _panel_write._manifest_path(project, config))
    if not os.path.isfile(mpath):
        out("[audit-task] manifest not found: %s -- run /audit:init first" % mpath)
        return E_USAGE
    lock = _acquire_lock(project, config, mpath, args.takeover, out)
    if isinstance(lock, int):
        return lock
    try:
        return _locked_cancel(args, project, config, mpath, tid, reason, out)
    finally:
        _release_lock(lock)


def cmd_add(args, out):
    project = _resolve_project(args)
    if not os.path.isdir(project):
        out("[audit-task] not a directory: %s" % project)
        return E_USAGE
    title = (args.title or "").strip()
    if not title:
        out("[audit-task] add needs a non-empty title")
        return E_USAGE
    config = _panel_write.read_config(project)
    mpath = (os.path.abspath(args.manifest) if args.manifest
             else _panel_write._manifest_path(project, config))
    if not os.path.isfile(mpath):
        out("[audit-task] manifest not found: %s -- run /audit:init first"
            % mpath)
        return E_USAGE
    # The lock comes BEFORE the read: ids are allocated under it, so the
    # read-modify-write is serialized (manifest-conventions -> ID allocation).
    lock = _acquire_lock(project, config, mpath, args.takeover, out)
    if isinstance(lock, int):
        return lock
    try:
        return _locked_add(args, project, config, mpath, title, out)
    finally:
        _release_lock(lock)


def main(argv, out=print):
    p = argparse.ArgumentParser(prog="audit-task.py", add_help=True)
    p.add_argument("command", choices=["add", "cancel"])
    p.add_argument("title", nargs="?", default="")
    p.add_argument("manifest", nargs="?", default=None)
    p.add_argument("--phase", default=None)
    p.add_argument("--skills", default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--files", default=None)
    p.add_argument("--risk", choices=["low", "med", "high"], default=None)
    p.add_argument("--blocked-by", dest="blocked_by", default=None)
    p.add_argument("--depends-on", dest="depends_on", default=None)
    p.add_argument("--description", default="")
    p.add_argument("--tests-mode", dest="tests_mode",
                   choices=["tdd", "regression", "gate-only"], default=None)
    p.add_argument("--tests-add", dest="tests_add", action="append",
                   default=None)
    p.add_argument("--gate", action="append", default=None)
    p.add_argument("--project-dir", dest="project_dir", default=None)
    p.add_argument("--reason", default=None)
    p.add_argument("--takeover", action="store_true")
    p.add_argument("--json", action="store_true", dest="as_json")
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        return E_USAGE if exc.code else 0
    try:
        return cmd_cancel(args, out) if args.command == "cancel" \
            else cmd_add(args, out)
    except Exception as exc:                    # never leave a caller guessing
        out("[audit-task] internal error: %s" % exc)
        return E_INVALID


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to `main`, which would read the flag
        # as an unknown subcommand. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("audit-task.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_audit_task.py - run that file instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
