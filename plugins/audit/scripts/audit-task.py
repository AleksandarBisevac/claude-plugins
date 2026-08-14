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

    for ph in (assembled.get("phases") or []):
        if isinstance(ph, dict):
            _count(ph.get("tasks") or [])
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
    prints so the human knows whether /audit:run can start this now."""
    status = {}
    for ph in (assembled.get("phases") or []):
        if not isinstance(ph, dict):
            continue
        if ph.get("id"):
            status[ph["id"]] = ph.get("status")
        for t in (ph.get("tasks") or []):
            if isinstance(t, dict) and t.get("id"):
                status[t["id"]] = t.get("status")
    refs = list(task.get("blockedBy") or []) + list(task.get("dependsOn") or [])
    return [r for r in refs if status.get(r) != "done"]


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
    p.add_argument("command", choices=["add"])
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
    p.add_argument("--takeover", action="store_true")
    p.add_argument("--json", action="store_true", dest="as_json")
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        return E_USAGE if exc.code else 0
    try:
        return cmd_add(args, out)
    except Exception as exc:                    # never leave a caller guessing
        out("[audit-task] internal error: %s" % exc)
        return E_INVALID


# --- selftest ------------------------------------------------------------------
# Letters taken in this file (NEW file -- fresh letter space): a (add + phase
# resolution), i (reserved/parked ids), t (template fields), s (skills
# three-state), x (fileIndex), r (validator rollback), k (lock), y (layout:
# sharded/single), j (--json + journal row), h (A4 heal at this write site),
# u (usage errors).
def _selftest():
    import contextlib
    import shutil
    import subprocess

    results = []

    def check(name, cond):
        results.append(bool(cond))
        print("%s %s" % ("PASS" if cond else "FAIL", name))

    def run(argv):
        lines = []
        code = main(argv, out=lines.append)
        return code, "\n".join(lines)

    def base_manifest():
        return {
            "meta": {"version": 2, "buildCommands": {"test": "true"}},
            "phases": [
                {"id": "P1", "title": "Shipped", "status": "done",
                 "testGate": ["test"],
                 "tasks": [{"id": "P1.1", "title": "old", "status": "done"}]},
                {"id": "P2", "title": "Live", "status": "in_progress",
                 "testGate": ["test"],
                 "tasks": [
                     {"id": "P2.1", "title": "a", "status": "done",
                      "files": ["src/a.ts"]},
                     {"id": "P2.3", "title": "b", "status": "pending"}]},
                {"id": "P3", "title": "Parked work", "status": "pending",
                 "testGate": [], "tasks": []},
            ],
            "fileIndex": {"src/a.ts": ["P2.1"]},
            "bugs": [],
        }

    tmp = tempfile.mkdtemp(prefix="audit-task-selftest-")

    def mk(name, manifest, sharded=False, git=False):
        proj = os.path.join(tmp, name)
        os.makedirs(os.path.join(proj, ".claude"), exist_ok=True)
        _panel_write._atomic_write_json(
            os.path.join(proj, ".claude", "audit.config.json"),
            {"manifestPath": "docs/audit/audit-plan.json"})
        mpath = os.path.join(proj, "docs", "audit", "audit-plan.json")
        os.makedirs(os.path.dirname(mpath), exist_ok=True)
        if sharded:
            _mio.save_sharded(mpath, manifest)
        else:
            _panel_write._atomic_write_json(mpath, manifest)
        if git:
            subprocess.run(["git", "init", "-q", proj], check=True,
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        return proj, mpath

    def task_in(mpath, tid):
        try:
            m = _mio.load_manifest(mpath)
            for ph in m.get("phases") or []:
                for t in (ph.get("tasks") or []):
                    if isinstance(t, dict) and t.get("id") == tid:
                        return t
        except Exception:
            pass
        return None

    try:
        # ---- (a) add + phase resolution -----------------------------------
        proj, mpath = mk("a-single", base_manifest())
        code, txt = run(["add", "New guard", "--phase", "P2",
                         "--project-dir", proj])
        check("a1 explicit --phase add exits 0", code == 0)
        check("a2 gaps are history: P2.1 + P2.3 allocate P2.4, P2.2 is "
              "never re-minted", task_in(mpath, "P2.4") is not None)
        code, txt = run(["add", "Default phase", "--project-dir", proj])
        check("a3 --phase absent lands in the single in_progress phase",
              code == 0 and task_in(mpath, "P2.5") is not None)

        two = base_manifest()
        two["phases"][2]["status"] = "in_progress"
        proj2, _m2 = mk("a-two-inprog", two)
        code, txt = run(["add", "X", "--project-dir", proj2])
        check("a4 two in_progress phases -> exit 2, --phase required",
              code == 2)
        check("a4b ...naming BOTH choices", "P2" in txt and "P3" in txt)

        idle = base_manifest()
        idle["phases"][1]["status"] = "pending"
        proj3, _m3 = mk("a-idle", idle)
        code, txt = run(["add", "X", "--project-dir", proj3])
        check("a5 no in_progress phase -> exit 2 naming the open phases",
              code == 2 and "P2" in txt and "P3" in txt)

        code, txt = run(["add", "X", "--phase", "P1", "--project-dir", proj])
        check("a6 a done phase refuses -- immutable history",
              code == 2 and "immutable" in txt)
        check("a6b ...and nothing landed in it",
              len((_mio.load_manifest(mpath)["phases"][0].get("tasks"))) == 1)
        code, txt = run(["add", "X", "--phase", "P9", "--project-dir", proj])
        check("a7 unknown phase -> exit 2 listing what exists",
              code == 2 and "P2" in txt)
        empty_proj = os.path.join(tmp, "a-empty")
        os.makedirs(empty_proj, exist_ok=True)
        code, txt = run(["add", "X", "--project-dir", empty_proj])
        check("a8 missing manifest -> exit 2 pointing at /audit:init",
              code == 2 and "init" in txt)
        code, txt = run(["add", "   ", "--project-dir", proj])
        check("a9 an empty title is a usage error", code == 2)

        # ---- (i) reserved / parked ids ------------------------------------
        code, _txt = run(["add", "Third", "--phase", "P2",
                          "--project-dir", proj])
        check("i1 sequential adds keep counting (P2.6 after P2.5)",
              code == 0 and task_in(mpath, "P2.6") is not None)

        def prop(status):
            return {"id": "PROP-1", "name": "Parked phase", "status": status,
                    "origin": "audit:init",
                    "createdISO": "2026-01-01T00:00:00Z",
                    "scope": "x", "benefit": "y", "openQuestions": [],
                    "materializedAs": None, "materializedAt": None,
                    "payload": {"phase": {
                        "id": "P4", "title": "Parked", "status": "pending",
                        "tasks": [{"id": "P4.1", "title": "t",
                                   "status": "pending"}]}}}

        resv = base_manifest()
        resv["proposals"] = [prop("proposed")]
        proj4, _m4 = mk("i-reserved", resv)
        code, txt = run(["add", "X", "--phase", "P4", "--project-dir", proj4])
        check("i2 a phase id RESERVED by a parked proposal refuses toward "
              "/audit:propose materialize",
              code == 2 and "PROP-1" in txt and "materialize" in txt)
        dropped = base_manifest()
        dropped["proposals"] = [prop("dropped")]
        proj5, _m5 = mk("i-dropped", dropped)
        code, txt = run(["add", "X", "--phase", "P4", "--project-dir", proj5])
        check("i3 a dropped proposal releases the id -- plain unknown-phase "
              "refusal, no proposal named",
              code == 2 and "PROP-1" not in txt)

        # ---- (t) the template ---------------------------------------------
        t = task_in(mpath, "P2.4") or {}
        check("t1 every template field initialized, each exactly once",
              set(t.keys()) == set(_TEMPLATE_KEYS))
        check("t2 the conventions template values are the ones written",
              t.get("status") == "pending" and t.get("attempts") == 0
              and t.get("maxAttempts") == 3 and t.get("commit") is None
              and t.get("outcome") == {"technical": None, "descriptive": None}
              and t.get("startedAt") is None and t.get("completedAt") is None
              and t.get("verifiedBy") == [] and t.get("blockedBy") == []
              and t.get("dependsOn") == [])
        check("t3 tests default: gate-only, no red-first, gate from the "
              "phase's testGate",
              t.get("tests") == {"mode": "gate-only", "add": [],
                                 "expectRedFirst": False, "gate": ["test"]})
        check("t4 model floors at sonnet, risk defaults low",
              t.get("model") == "sonnet" and t.get("risk") == "low")

        code, _txt = run(["add", "Risky", "--phase", "P2",
                          "--project-dir", proj,
                          "--risk", "high", "--tests-mode", "tdd",
                          "--tests-add", "repro must fail first",
                          "--blocked-by", "P2.1", "--depends-on", "P2.3",
                          "--description", "why and how"])
        t = task_in(mpath, "P2.7") or {}
        check("t5 risk high without --model escalates to opus",
              code == 0 and t.get("model") == "opus"
              and t.get("risk") == "high")
        check("t6 tdd sets expectRedFirst true and carries the authored test",
              (t.get("tests") or {}).get("mode") == "tdd"
              and (t.get("tests") or {}).get("expectRedFirst") is True
              and (t.get("tests") or {}).get("add")
              == ["repro must fail first"])
        check("t7 blockedBy/dependsOn/description land as given",
              t.get("blockedBy") == ["P2.1"] and t.get("dependsOn") == ["P2.3"]
              and t.get("description") == "why and how")
        code, _txt = run(["add", "Explicit model", "--phase", "P2",
                          "--project-dir", proj, "--risk", "high",
                          "--model", "sonnet"])
        check("t8 an explicit --model wins over the risk escalation",
              code == 0 and (task_in(mpath, "P2.8") or {}).get("model")
              == "sonnet")

        # ---- (s) skills: the three states ---------------------------------
        check("s1 skills absent -> [] (unconsidered; area default in force)",
              (task_in(mpath, "P2.4") or {}).get("skills") == [])
        code, _txt = run(["add", "With skills", "--phase", "P2",
                          "--project-dir", proj,
                          "--skills", "clean-typescript,web-security"])
        check("s2 --skills a,b lands as the list",
              code == 0 and (task_in(mpath, "P2.9") or {}).get("skills")
              == ["clean-typescript", "web-security"])
        code, _txt = run(["add", "Opted out", "--phase", "P2",
                          "--project-dir", proj, "--skills", "null"])
        s3t = task_in(mpath, "P2.10") or {}
        check("s3 --skills null is the explicit opt-out: key present, "
              "value None", code == 0 and "skills" in s3t
              and s3t.get("skills") is None)
        with open(mpath, encoding="utf-8") as fh:
            raw = fh.read()
        check("s3b ...written as JSON null in the file, not flattened "
              "or dropped", '"skills": null' in raw)

        # ---- (x) fileIndex -------------------------------------------------
        code, txt = run(["add", "Indexed", "--phase", "P2",
                         "--project-dir", proj,
                         "--files", "src/a.ts,src/new.ts"])
        fidx = (_mio.load_manifest(mpath).get("fileIndex") or {})
        check("x1 an existing fileIndex entry is EXTENDED, other tasks kept",
              code == 0 and fidx.get("src/a.ts") == ["P2.1", "P2.11"])
        check("x1b a new file gets a fresh entry",
              fidx.get("src/new.ts") == ["P2.11"])
        check("x2 a file not on disk is noted (new-file paths stay allowed), "
              "never refused", code == 0 and "src/new.ts" in txt)

        # ---- (r) validator rollback ----------------------------------------
        before = open(mpath, "rb").read()
        code, txt = run(["add", "Bad ref", "--phase", "P2",
                         "--project-dir", proj, "--blocked-by", "P9.9"])
        check("r1 a reference the validator refuses -> exit 1 with the "
              "findings", code == 1 and "does not resolve" in txt)
        check("r2 ...and the manifest is rolled back byte-for-byte",
              open(mpath, "rb").read() == before)

        dup = base_manifest()
        dup["phases"][1]["tasks"].append({"id": "P2.1", "title": "dup",
                                          "status": "pending"})
        projd, mpathd = mk("r-preinvalid", dup)
        befored = open(mpathd, "rb").read()
        code, txt = run(["add", "X", "--phase", "P2", "--project-dir", projd])
        check("r3 an ALREADY-invalid manifest refuses before any write",
              code == 1 and "already" in txt.lower()
              and open(mpathd, "rb").read() == befored)

        # ---- (y) the sharded layout ----------------------------------------
        projs, mpaths = mk("y-sharded", base_manifest(), sharded=True)
        idx_raw = _mio.read_json(mpaths)
        check("y0 fixture really is sharded", _mio.is_sharded(idx_raw))
        sbase = os.path.dirname(mpaths)
        shard_of = {s.get("id"): os.path.join(sbase, s["shard"])
                    for s in idx_raw["phases"] if isinstance(s, dict)}
        p1_before = open(shard_of["P1"], "rb").read()
        idx_before = open(mpaths, "rb").read()
        code, _txt = run(["add", "Sharded add", "--phase", "P2",
                          "--project-dir", projs])
        check("y1 the task lands in the phase SHARD and survives a reload",
              code == 0 and (task_in(mpaths, "P2.4") or {}).get("title")
              == "Sharded add")
        check("y2 an untouched phase's shard is not rewritten",
              open(shard_of["P1"], "rb").read() == p1_before)
        check("y3 no --files -> the index itself is untouched",
              open(mpaths, "rb").read() == idx_before)
        code, _txt = run(["add", "Sharded indexed", "--phase", "P2",
                          "--project-dir", projs, "--files", "src/new.ts"])
        check("y4 --files updates the fileIndex ON THE INDEX",
              code == 0 and (_mio.load_manifest(mpaths).get("fileIndex")
                             or {}).get("src/new.ts") == ["P2.5"])
        check("y4b ...and the untouched shard is still byte-identical",
              open(shard_of["P1"], "rb").read() == p1_before)
        p2_before = open(shard_of["P2"], "rb").read()
        idx_before2 = open(mpaths, "rb").read()
        code, _txt = run(["add", "Bad", "--phase", "P2",
                          "--project-dir", projs, "--blocked-by", "NOPE",
                          "--files", "src/x.ts"])
        check("y5 sharded rollback restores shard AND index byte-for-byte",
              code == 1 and open(shard_of["P2"], "rb").read() == p2_before
              and open(mpaths, "rb").read() == idx_before2)

        # ---- (h) the A4 heal ------------------------------------------------
        healm = base_manifest()
        healm["phases"][2]["tasks"] = [{"id": "P3.1", "title": "hand-flipped",
                                        "status": "in_progress"}]
        projh, mpathh = mk("h-heal", healm)
        code, txt = run(["add", "Heal me", "--phase", "P3",
                         "--project-dir", projh])
        p3 = [p for p in _mio.load_manifest(mpathh)["phases"]
              if p.get("id") == "P3"][0]
        check("h1 a pending phase holding an in_progress task is healed in "
              "the same write (v0.37 A4, reused from _panel_write)",
              code == 0 and p3.get("status") == "in_progress")
        check("h2 ...and the heal is reported",
              "pending -> in_progress" in txt)

        # ---- (j) --json + the journal ---------------------------------------
        projj, _mj = mk("j-json", base_manifest())
        code, txt = run(["add", "Json add", "--phase", "P2",
                         "--project-dir", projj, "--json"])
        parsed = None
        try:
            parsed = json.loads(txt)
        except Exception:
            pass
        check("j1 --json emits one parseable object",
              code == 0 and isinstance(parsed, dict))
        check("j1b ...naming the id and the task it wrote",
              bool(parsed) and parsed.get("id") == "P2.4"
              and (parsed.get("task") or {}).get("status") == "pending")
        jm = _panel_write._journalmod()
        rows = jm.read_all(projj) if jm else []
        addrows = [r for r in rows if r.get("action") == "task.add"]
        check("j2 a task.add row is journaled through audit-journal's append",
              len(addrows) == 1)
        check("j2b ...with the allow-listed details a reader joins on",
              bool(addrows)
              and (addrows[0].get("details") or {}).get("taskId") == "P2.4"
              and (addrows[0].get("details") or {}).get("phaseId") == "P2")
        check("j2c ...and the result reports the journal outcome",
              bool(parsed) and parsed.get("journaled") is True)

        # ---- (k) the lock ----------------------------------------------------
        if not shutil.which("git"):
            print("SKIP k* (git not installed)")
        else:
            projk, mpathk = mk("k-lock", base_manifest(), git=True)
            lockmod = _panel_write._lockmod()
            check("k0 the lock library loads", lockmod is not None)
            if lockmod is not None:
                held = lockmod.main(
                    ["acquire", "index", "--project", projk,
                     "--note", "phase P2 run", "--session", "sess-A",
                     "--pid", str(os.getpid())], out=lambda *_a: None)
                check("k0b fixture lock taken", held == 0)
                kb = open(mpathk, "rb").read()
                code, txt = run(["add", "Locked out", "--phase", "P2",
                                 "--project-dir", projk])
                check("k1 a live holder refuses with exit 3", code == 3)
                check("k1b ...printing the lock's own standard shape",
                      "HELD by a live run" in txt and "sess-A" in txt)
                check("k1c ...and nothing was written",
                      open(mpathk, "rb").read() == kb)
                deadp = subprocess.Popen([sys.executable, "-c", "pass"])
                deadp.wait()
                lpath = os.path.join(lockmod.lock_dir(projk), "index.lock")
                info = lockmod.read_lock(lpath)
                info["pid"] = deadp.pid
                lockmod._write_lock(lpath, info)
                code, txt = run(["add", "Stale", "--phase", "P2",
                                 "--project-dir", projk])
                check("k2 an abandoned holder -> exit 4, offering --takeover",
                      code == 4 and "--takeover" in txt)
                check("k2b ...but nothing is seized or written yet",
                      open(mpathk, "rb").read() == kb)
                code, txt = run(["add", "Taken over", "--phase", "P2",
                                 "--project-dir", projk, "--takeover"])
                check("k3 --takeover seizes the abandoned lock and writes",
                      code == 0 and (task_in(mpathk, "P2.4") or {}).get("title")
                      == "Taken over")
                check("k4 the lock is released after the write",
                      not os.path.exists(lpath))
        projl, mpathl = mk("k-legacy", base_manifest())
        open(mpathl + ".lock", "w").close()
        code, txt = run(["add", "X", "--phase", "P2", "--project-dir", projl])
        check("k5 outside a git repo the working-tree lockfile still refuses",
              code == 3 and "locked" in txt)
        os.remove(mpathl + ".lock")

        # ---- (n) named-manifest project resolution (F-C-1) -------------------
        # Naming another project's manifest from this cwd must not journal (or
        # lock, or note file existence) into THIS repo -- the class
        # audit-usage's resolve_ledger already solved. cwd and
        # CLAUDE_PROJECT_DIR are both pinned to a "home" project that must
        # come out untouched.
        projn_home, _mnh = mk("n-home", base_manifest())
        projn_foreign, mpn = mk("n-foreign", base_manifest())
        oldcwd = os.getcwd()
        oldenv = os.environ.get("CLAUDE_PROJECT_DIR")

        def _pin(cwd, env):
            os.chdir(cwd)
            if env is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = env

        def _unpin():
            os.chdir(oldcwd)
            if oldenv is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = oldenv

        try:
            _pin(projn_home, projn_home)
            code, txt = run(["add", "Foreign add", mpn, "--phase", "P2"])
        finally:
            _unpin()
        jm2 = _panel_write._journalmod()
        frows = [r for r in (jm2.read_all(projn_foreign) if jm2 else [])
                 if r.get("action") == "task.add"]
        check("n1 a NAMED manifest journals beside ITSELF, not into the "
              "cwd/env repo (F-C-1)", code == 0 and len(frows) == 1)
        check("n2 ...and the cwd/env repo's journal is untouched (no dir "
              "even exists)",
              not os.path.isdir(os.path.join(projn_home, "docs", "audit",
                                             "journal")))
        check("n3 ...and the row's target is manifest-relative, not a "
              "../../ crawl out of the wrong root",
              bool(frows)
              and frows[0].get("target") == "docs/audit/audit-plan.json")

        projn_f2, mpn2 = mk("n-foreign2", base_manifest())
        projn_h2, _mn2 = mk("n-home2", base_manifest())
        code, _txt = run(["add", "Explicit wins", mpn2, "--phase", "P2",
                          "--project-dir", projn_h2])
        h2rows = [r for r in (jm2.read_all(projn_h2) if jm2 else [])
                  if r.get("action") == "task.add"]
        check("n4 an explicit --project-dir wins over the named manifest's "
              "own root -- the human said so",
              code == 0 and len(h2rows) == 1)

        projn_sh, mpsh = mk("n-sharded-foreign", base_manifest(),
                            sharded=True)
        try:
            _pin(projn_home, projn_home)
            code, _txt = run(["add", "Sharded foreign", mpsh,
                              "--phase", "P2"])
        finally:
            _unpin()
        check("n5 a NAMED sharded manifest is writable from a foreign cwd "
              "-- the shard guard scopes to the manifest's OWN project",
              code == 0 and (task_in(mpsh, "P2.4") or {}).get("title")
              == "Sharded foreign")

        projn_env, mpe = mk("n-env", base_manifest())
        try:
            _pin(tmp, projn_env)
            code, _txt = run(["add", "Env project", "--phase", "P2"])
        finally:
            _unpin()
        check("n6 with nothing named, CLAUDE_PROJECT_DIR answers before the "
              "cwd (audit-usage's resolve_project order)",
              code == 0 and task_in(mpe, "P2.4") is not None)

        # F-C-2: MARKERLESS trees (no .claude, no .git anywhere above). The
        # fallback root must keep the journal in a sane place INSIDE the
        # manifest's tree -- never doubled, never outside.
        def mk_bare(name, manifest, rel="docs/audit/audit-plan.json"):
            proj = os.path.join(tmp, name)
            mp = os.path.join(proj, rel)
            os.makedirs(os.path.dirname(mp), exist_ok=True)
            _panel_write._atomic_write_json(mp, manifest)
            return proj, mp

        projb, mpb = mk_bare("n-markerless", base_manifest())
        try:
            _pin(projn_home, projn_home)
            code, _txt = run(["add", "Markerless", mpb, "--phase", "P2"])
        finally:
            _unpin()
        brows = [r for r in (jm2.read_all(projb) if jm2 else [])
                 if r.get("action") == "task.add"]
        check("n7 a markerless default-layout tree journals beside its "
              "manifest, where default readers find it (F-C-2)",
              code == 0 and len(brows) == 1)
        check("n7b ...and the layout is not doubled -- docs/audit/docs "
              "never appears",
              not os.path.exists(os.path.join(projb, "docs", "audit",
                                              "docs")))

        projb2, mpb2 = mk_bare("n-bare-layout", base_manifest(),
                               rel="plan.json")
        try:
            _pin(projn_home, projn_home)
            code, _txt = run(["add", "Bare layout", mpb2, "--phase", "P2"])
        finally:
            _unpin()
        jdir = os.path.join(projb2, "journal")
        jtext = ""
        if os.path.isdir(jdir):
            for fn in os.listdir(jdir):
                with open(os.path.join(jdir, fn), encoding="utf-8") as fh:
                    jtext += fh.read()
        check("n8 a bare non-default layout (x/plan.json) journals at "
              "x/journal, beside the manifest",
              code == 0 and '"task.add"' in jtext)
        check("n8b ...without conjuring docs/audit into the tree",
              not os.path.exists(os.path.join(projb2, "docs")))

        # ---- (u) usage -------------------------------------------------------
        with open(os.devnull, "w") as _null, \
                contextlib.redirect_stderr(_null):
            code, _txt = run(["frobnicate", "X"])
            check("u1 an unknown subcommand is a usage error", code == 2)
            code, _txt = run([])
            check("u2 bare invocation is a usage error", code == 2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
