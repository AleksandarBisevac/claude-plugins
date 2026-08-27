#!/usr/bin/env python3
"""
Where a test-execution evidence record lives, and what it is allowed to say.

The gate runner already answers the two questions an exit code cannot -- did the
gate change the tree, and did anything actually run -- and then throws every one
of those answers away: `run-test-gate.py` performs no disk I/O at all. This module
is the memory it never had.

WHY NOT THE JOURNAL. `_journal_io.DETAILS_KEYS` is an allow-list, and the three
tests it states for a new key are that the key names A FIELD OF THE PLAN that
moved, that it is bounded, and that it exposes nothing new. An exit code, a
duration and a check count fail the first outright -- they are things the plugin
OBSERVED ABOUT THE MACHINE -- and `MAX_DETAILS_BYTES` would clip a multi-step run
besides. So the runs live here and the journal ANCHORS them: one row per recorded
run naming its `runId`, which is a plan field and passes all three.

WHY NOT THE USAGE LEDGER'S HOME EITHER. `<ledgerDir>` is local scratch that writes
its own `.gitignore`; this is evidence for an audit somebody hands to a client, so
it sits beside the manifest and is COMMITTED, exactly like the journal. The two
differ in what they are for, not in where they belong.

FILE LAYOUT
    <evidence dir>/<YYYY-MM>.<writerId>.jsonl     (default <manifest dir>/evidence)

One file per writer per month, which is the journal's argument and not a
decoration: two sessions in two git worktrees append at the same time, and a
single shared file would conflict on every merge -- the one thing the sharded
manifest layout exists to avoid. The writer id and the month come from
`_journal_io`, so the two records name the same writer the same way.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__evidence_io.py` -- see `plugins/audit/tests/_harness.py`.
"""
import binascii
import json
import os
import sys
import time

# The path bootstrap: byte-identical in every `.py` under `scripts/`, counted by
# `_output.path_preamble_violations()`. It walks UP to the directory holding
# `_output.py` instead of counting `dirname()` calls, so it does not encode how deep
# this file sits and keeps working if the file is moved into a subdirectory.
# `install_path()` then adds that directory AND every subdirectory of it holding a
# `.py`: the folders are LABELS, NOT NAMESPACES, and every sibling below is still
# reached by a bare basename.
_anchor_dir = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_anchor_dir, "_output.py")):
    _anchor_up = os.path.dirname(_anchor_dir)
    if _anchor_up == _anchor_dir:
        raise ImportError("audit plugin: walked to the filesystem root from %s "
                          "without finding _output.py - the scripts/ anchor is "
                          "gone and no sibling can be imported" % (__file__,))
    _anchor_dir = _anchor_up
if _anchor_dir not in sys.path:
    sys.path.insert(0, _anchor_dir)

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()

import _journal_io  # noqa: E402  (config loading, the writer id, the month)
import _locks  # noqa: E402  (whose phase lock, and is it live)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; the atomic write)
from _journal_io import command_facts, repo_relative_or_token  # noqa: E402

DEFAULT_DIRNAME = "evidence"


# --- where it lives -----------------------------------------------------------
def evidence_dir(project, config=None):
    """Absolute path of the evidence directory.

    `evidence.dir` when set, else `<manifest dir>/evidence` -- derived from
    `manifestPath` rather than hardcoded, for `journal_dir`'s reason: a repo that
    moved its plan must not end up with the record of it somewhere else entirely.

    THE RESOLUTION IS SHARED WITH THE JOURNAL'S, DELIBERATELY. Both answer "where
    does this manifest keep its committed record", and two expressions of that
    would put the trail and the evidence in different places the first time a repo
    set `manifestPath` to something unusual.
    """
    config = _journal_io.load_config(project) if config is None else config
    block = (config or {}).get("evidence")
    rel = block.get("dir") if isinstance(block, dict) else None
    if isinstance(rel, str) and rel.strip():
        return os.path.normpath(os.path.join(project, rel.strip()))
    manifest = (config or {}).get("manifestPath") or _journal_io.DEFAULT_MANIFEST
    return os.path.normpath(os.path.join(
        project, os.path.dirname(str(manifest)) or ".", DEFAULT_DIRNAME))


def in_evidence(project, path, config=None):
    """True when `path` (absolute or project-relative) is inside the evidence dir.

    The same shape as `_journal_io.in_journal`, and needed for the same reason:
    a guard that asks "did a shell command write into the record" has to be able
    to name the record without re-deriving where it is.
    """
    try:
        d = os.path.realpath(evidence_dir(project, config))
        p = path if os.path.isabs(path) else os.path.join(project, path)
        p = os.path.realpath(p)
        return p == d or p.startswith(d + os.sep)
    except Exception:
        return False


# --- what a row may carry -----------------------------------------------------
# ASSEMBLED FROM NAMED FIELDS, NEVER COPIED. `row_for` reads the keys below out of
# whatever it is handed and nothing else, which is what makes "no runner output is
# ever written here" a property of the WRITER rather than a habit each call site
# has to remember. The gate runner holds full merged stdout in memory while it
# counts checks and scrapes paths; none of it has a route into this file.
ROW_VERSION = 1
ACTION_RECORDED = "test.evidence.recorded"

# A run with more steps than this is a build, not a gate; more paths than this is
# a rewrite, not a diff. Both cuts are COUNTED beside the list they cut, because a
# truncation nobody announced reads as "that is all there was".
MAX_STEPS = 24
MAX_PATHS = 40

STEP_KEYS = ("name", "exit", "ran", "durationMs", "outcome", "timeoutSeconds",
             "teardown")
STATE_KEYS = ("head", "headBasis", "scopeDigest", "scopeBasis", "dirtyDigest",
              "dirtyBasis")
_PORCELAIN_RENAME = " -> "


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _path_of(entry):
    """The path a `git status --porcelain` line is about, or the entry itself.

    Porcelain is `XY <path>`, and a rename is `XY <old> -> <new>` where the NEW
    name is the one that exists now. Anything that does not look like a porcelain
    line is passed through, so a caller holding bare paths is not made to know
    which shape this expects."""
    text = str(entry or "")
    if len(text) > 3 and text[2] == " " and not text[:2].strip(" ?!MADRCU"):
        text = text[3:]
    if _PORCELAIN_RENAME in text:
        text = text.split(_PORCELAIN_RENAME)[-1]
    return text.strip().strip('"')


def _paths(project, entries):
    """`(kept, dropped)` - repo-relative paths, bounded, outside ones tokenised.

    THE REDACTION IS THE JOURNAL'S, not a second rule: this file is committed on
    purpose, and an absolute path in it names somebody's machine in a repository
    that goes to clients. `repo_relative_or_token` is where that question is
    already answered once."""
    kept = []
    for entry in (entries or [])[:MAX_PATHS]:
        kept.append(repo_relative_or_token(project, _path_of(entry)))
    return kept, max(0, len(entries or []) - MAX_PATHS)


def _step(project, step, published):
    """One step of the run, allow-listed - and its command decided, not copied.

    A COMMAND THE MANIFEST PUBLISHES IS STORED VERBATIM, and only that one. It is
    already committed in the plan, in plain text, so storing it exposes nothing
    new -- which is the third of the three tests `_journal_io` states for a field
    in a committed record. Anything else is an ad-hoc string this file has no
    claim about, so it gets the digest, byte length and program name that
    `command_facts` already produces for exactly this reason.
    """
    out = {}
    for key in STEP_KEYS:
        if key not in step:
            continue
        # `exit` and `ran` KEEP a None. `ran` is three-valued and its None means
        # "not knowable from this runner"; dropping the key would turn that into
        # "absent", which is the one reading a reader could mistake for zero.
        if step[key] is None and key not in ("exit", "ran"):
            continue
        out[key] = step[key]
    command = step.get("command")
    if command is None:
        return out
    if str(command) in set(str(c) for c in (published or [])):
        out["command"] = str(command)
    else:
        out.update(command_facts(str(command)))
    return out


def row_for(project, result, scope, ids, identity, published=None):
    """One evidence row: what ran, what it answered, and whose run it was.

    `result` is `run-test-gate.run_gate`'s dict. Only the fields named here cross
    into the row; an inventive caller cannot widen it, which is the same rule
    `_journal_io._normalise` applies to a journal row and for the same reason.
    """
    result = result if isinstance(result, dict) else {}
    ids = ids if isinstance(ids, dict) else {}
    identity = identity if isinstance(identity, dict) else {}
    steps = [s for s in (result.get("steps") or []) if isinstance(s, dict)]
    mutated, mut_dropped = _paths(project, result.get("treeMutated"))
    coverage, cov_dropped = _paths(project, result.get("overlap"))
    state = result.get("testedState") if isinstance(
        result.get("testedState"), dict) else {}
    row = {
        "v": ROW_VERSION,
        "runId": str(identity.get("runId") or ""),
        "ts": str(identity.get("ts") or _now()),
        "scope": str(scope or ""),
        "status": result.get("status"),
        "durationMs": result.get("durationMs"),
        "failed": list(result.get("failed") or []),
        "steps": [_step(project, s, published) for s in steps[:MAX_STEPS]],
        "testedState": dict((k, state.get(k)) for k in STATE_KEYS if k in state),
        "observations": {
            "ranTotal": result.get("ranTotal"),
            "countsBasis": result.get("countsBasis"),
            "treeMutated": None if result.get("treeMutated") is None else mutated,
            "treeBasis": result.get("treeBasis"),
            "coverage": None if result.get("overlap") is None else coverage,
            "coverageBasis": result.get("coverageBasis"),
        },
    }
    # THE BASIS FOR THE ONE STATUS WORD THAT HAS NO OTHER. `failed` is read back
    # off the steps, `timed-out` off a step's `outcome` and its `timeoutSeconds`,
    # `no-checks` off `ranTotal` -- but a run stopped by a signal keeps only the
    # steps that FINISHED, so nothing else on the row would say what happened to
    # the rest. Written only when there is something to write: a key present on
    # every row could not be told from one a build does not produce.
    if result.get("cancelledBy") is not None:
        row["cancelledBy"] = str(result["cancelledBy"])
    for key in ("taskId", "phaseId"):
        if ids.get(key) is not None:
            row[key] = str(ids[key])
    for key in ("attempt", "via", "sessionId"):
        if identity.get(key) is not None:
            row[key] = identity[key]
    # PRESENT ONLY WHEN SOMETHING WENT. A count that appears solely when non-zero
    # cannot be told from a count nobody computed, so its ABSENCE has to mean
    # "nothing was cut" and never "nobody looked".
    if steps[MAX_STEPS:]:
        row["stepsDropped"] = len(steps) - MAX_STEPS
    if mut_dropped:
        row["treeMutatedDropped"] = mut_dropped
    if cov_dropped:
        row["coverageDropped"] = cov_dropped
    # The three-valued fields keep their shape at the TOP level too, so a reader
    # that never opens `observations` still cannot mistake unknown for clean.
    row["treeMutated"] = row["observations"]["treeMutated"]
    return row


# --- writing and reading ------------------------------------------------------
def append_row(project, row, session_id=None, config=None):
    """Append one row; return the file it landed in.

    O_APPEND of one bounded line, with NO LOCK - the usage ledger's argument,
    which holds here because the file is per writer per month: the only writer
    that can race is this session with itself.
    """
    config = _journal_io.load_config(project) if config is None else config
    directory = evidence_dir(project, config)
    os.makedirs(directory, exist_ok=True)
    actor = {"sessionId": session_id} if session_id else {}
    path = _journal_io.file_for(
        directory, row.get("ts") or _now(), actor,
        fallback=None if _journal_io.has_session(actor)
        else _journal_io.writer_token(project, config))
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(_journal_io.canonical(row) + "\n")
    return path


def read_rows(project, config=None):
    """`{"rows", "files", "unreadable"}` - every recorded run, and what was lost.

    A TORN LINE IS COUNTED, not merely skipped. `usage_ledger.read_ledger` drops
    one in silence, which is right for telemetry and wrong here: silence about a
    lost EVIDENCE row is the failure this file exists to prevent. `files` is
    reported for the same reason - "no rows" and "no files" are different answers
    and a bare list could not tell them apart.
    """
    config = _journal_io.load_config(project) if config is None else config
    directory = evidence_dir(project, config)
    rows, unreadable, files = [], 0, 0
    try:
        names = sorted(n for n in os.listdir(directory) if n.endswith(".jsonl"))
    except Exception:
        return {"rows": [], "files": 0, "unreadable": 0}
    for name in names:
        files += 1
        try:
            with open(os.path.join(directory, name), "r",
                      encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
        except Exception:
            unreadable += 1
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception:
                unreadable += 1
                continue
            if isinstance(obj, dict):
                rows.append(obj)
            else:
                unreadable += 1
    return {"rows": rows, "files": files, "unreadable": unreadable}


def record(project, result, scope, ids, identity, published=None, config=None):
    """Append the row, then anchor it in the journal. Returns both outcomes.

    ORDER IS THE POINT. The ledger row is written FIRST and the journal row
    second, so the only reachable partial state is the harmless one: a run that
    happened with nothing yet pointing at it. The reverse would put a claim in a
    hash chain about a row that does not exist.

    THE ANCHOR IS NOT THE POINTER MOVING. This row's subject is the evidence
    file, and it says only that a run was recorded - which is true the moment it
    is written. The row that says the PLAN moved belongs to whoever moves it, and
    must not be written before that happens.

    Fail-soft on the journal half, `_journal_io.append`'s own contract: a run that
    was recorded must not be reported as unrecorded because the trail could not be
    written.
    """
    config = _journal_io.load_config(project) if config is None else config
    row = row_for(project, result, scope, ids, identity, published=published)
    path = append_row(project, row, session_id=identity.get("sessionId"),
                      config=config)
    details = {"runId": row["runId"]}
    for key in ("taskId", "phaseId"):
        if row.get(key):
            details[key] = row[key]
    appended = _journal_io.append(project, {
        "action": ACTION_RECORDED,
        "actor": {"sessionId": identity.get("sessionId"),
                  "via": identity.get("via") or "unknown"},
        "target": repo_relative_or_token(project, path),
        "summary": "%s run %s on %s: %s"
                   % (scope, row["runId"], ids.get("taskId")
                      or ids.get("phaseId") or "?", row.get("status")),
        "details": details,
    }, config=config)
    return {"row": row, "path": path, "appended": appended}


# --- the pointer: a cache the manifest keeps ----------------------------------
# THE LEDGER IS THE SOURCE OF TRUTH AND THIS IS A CACHE, which is what makes the
# write below the one allowed to fail. `COMPATIBILITY.md` already states that
# contract for `meta.ado`'s caches: deleting the block is always safe, absent
# means "never recorded", and every reader is written to that. So a refusal here
# costs a reader one lookup, never a fact.
POINTER_KEY = "testEvidence"
ACTION_MOVED = {"task": "task.testEvidence", "phase": "phase.testEvidence"}
RECONCILE_HINT = ("the run is recorded; re-run with --reconcile once the holder "
                  "is done to point the plan at it")


def pointer_for(row):
    """The three keys the manifest caches: identity, verdict, time.

    NOTHING COUNTABLE. An attempt number and a count of runs were both cut: the
    attempt is on the row where it is written once, and a count is derived by
    reading the ledger. A cached count is this repository's most repeated defect.
    """
    return {"runId": row.get("runId"), "status": row.get("status"),
            "at": row.get("ts")}


def lock_state(project, name, label, session_id=None, hint=""):
    """`(state, detail)` -- may this session write what `name` guards, and if not why.

    `free` | `ours` | `held` | `stale` | `unlockable`.

    `ours` EXISTS BECAUSE `_locks.acquire` IS NOT RE-ENTRANT. A gate recorded from
    inside its own phase run meets the lock that run already holds, and acquiring
    would refuse it -- which is every in-phase recording there is. So the holder's
    session is COMPARED rather than the lock re-taken.

    `unlockable` is the panel's documented third answer, kept for its reason: a
    project with no `.git` has no lock scheme and never had one, and refusing
    every such project would refuse a case that has an answer.

    A STALE LOCK IS NOT TAKEN OVER HERE. Taking one over is a decision a human
    makes with `audit-lock --takeover` after confirming the holder is dead; a
    cache write must not make it quietly.

    `hint` IS THE CALLER'S REPAIR AND NOT THIS FUNCTION'S. Two writers ask this
    question now and the repairs differ -- a refused pointer is caught up by
    `--reconcile`, a refused boundary needs nothing at all -- so a shared sentence
    here would send half the callers somewhere that cannot help them.
    """
    try:
        if not _locks.available(project):
            return "unlockable", "this project has no lock scheme"
        path = os.path.join(_locks.lock_dir(project), "%s.lock" % (name,))
        if not os.path.exists(path):
            return "free", ""
        info = _locks.read_lock(path)
        holder = info.get("sessionId")
        if holder and session_id and str(holder) == str(session_id):
            return "ours", "held by this session"
        live, basis = _locks.judge(info, path)
        if live:
            return "held", ("the %s lock is held by another live run (%s); %s"
                            % (label, basis, hint))
        return "stale", ("the %s lock looks abandoned (%s); confirm with a "
                         "human and use audit-lock --takeover, then %s"
                         % (label, basis, hint))
    except Exception as exc:
        return "held", ("the %s lock could not be read (%s); %s"
                        % (label, exc, hint))


def pointer_lock_state(project, phase_id, session_id=None):
    """`(state, detail)` -- may this session write the phase's shard, and if not why.

    The pointer's spelling of `lock_state`: the phase lock, and the repair a
    refused pointer names. It stays a named function because the phase lock is
    what the POINTER is about, and a call site spelling the lock name itself is
    one that can spell it differently next year.
    """
    return lock_state(project, "phase-%s" % (phase_id,), "phase",
                      session_id=session_id, hint=RECONCILE_HINT)


def _phase_file(manifest_path, phase_id):
    """`(path, sharded)` -- the file a phase's runtime fields live in.

    Read off the RAW index rather than derived, because `_shard_name` is the
    writer's rule and a reader that re-derived it would drift the first time it
    changed."""
    index = _mio.read_json(manifest_path)
    for stub in (index.get("phases") or []):
        if isinstance(stub, dict) and str(stub.get("id")) == str(phase_id):
            shard = stub.get("shard")
            if shard:
                return os.path.join(os.path.dirname(os.path.abspath(manifest_path)),
                                    str(shard)), True
            return os.path.abspath(manifest_path), False
    return None, _mio.is_sharded(index)


def _set_pointer(body, scope, ids, pointer, sharded):
    """`(previous, problem)` -- put the pointer in place, and say what it replaced.

    The previous value is returned because the journal row that records the move
    names both ends: a row saying only where a field landed cannot be read as a
    transition, and this field moves repeatedly over one task's life.
    """
    phases = [body] if sharded else [
        p for p in (body.get("phases") or [])
        if isinstance(p, dict) and str(p.get("id")) == str(ids.get("phaseId"))]
    if not phases:
        return None, "no phase %r in this manifest" % (ids.get("phaseId"),)
    phase = phases[0]
    if scope == "phase":
        previous = phase.get(POINTER_KEY)
        phase[POINTER_KEY] = pointer
        return previous, None
    for task in (phase.get("tasks") or []):
        if isinstance(task, dict) and str(task.get("id")) == str(ids.get("taskId")):
            previous = task.get(POINTER_KEY)
            task[POINTER_KEY] = pointer
            return previous, None
    return None, "no task %r in phase %r" % (ids.get("taskId"), ids.get("phaseId"))


def write_pointer(project, manifest_path, scope, ids, row, session_id=None,
                  config=None):
    """Point the plan at a recorded run. `{"written", "reason", "path"}`.

    WRITES THE SHARD AND NEVER THE INDEX. A task commit that carried the index is
    what makes two parallel phases conflict on merge, and the pointer is a runtime
    field, so it belongs in the phase body exactly as `status` and `attempts` do.

    Every `written: False` here is a DESIGNED outcome carrying a sentence, not an
    error path: a refused cache write leaves the ledger row standing, which is the
    only reachable partial state and the harmless one.
    """
    pointer = pointer_for(row)
    state, detail = pointer_lock_state(project, ids.get("phaseId"),
                                       session_id=session_id)
    if state in ("held", "stale"):
        return {"written": False, "reason": detail, "path": None}
    path, sharded = _phase_file(manifest_path, ids.get("phaseId"))
    if not path or not os.path.exists(path):
        return {"written": False,
                "reason": "no phase %r in this manifest" % (ids.get("phaseId"),),
                "path": None}
    try:
        body = _mio.read_json(path)
    except Exception as exc:
        return {"written": False, "reason": "cannot read %s: %s"
                % (_journal_io.repo_relative_or_token(project, path), exc),
                "path": None}
    previous, problem = _set_pointer(body, scope, ids, pointer, sharded)
    if problem:
        return {"written": False, "reason": problem, "path": None}
    taken = False
    if state == "free":
        taken = _locks.held(_locks.acquire(project, "phase-%s" % (ids.get("phaseId"),),
                                           note="recording test evidence",
                                           session=session_id,
                                           out=lambda *_a: None))
        if not taken:
            return {"written": False,
                    "reason": "the phase lock could not be taken; " + RECONCILE_HINT,
                    "path": None}
    try:
        _mio.atomic_write_json(path, body)
    finally:
        if taken:
            _locks.release(project, "phase-%s" % (ids.get("phaseId"),),
                           session=session_id, out=lambda *_a: None)
    # ONLY NOW. This row says the PLAN moved, and it is written after the move
    # rather than beside the attempt: a refused write above returns before
    # reaching here, so the chain can never assert a transition that did not
    # happen. That is the whole reason this is a second action and not the row
    # `record()` already wrote -- that one's subject is the evidence file and it
    # was true the moment it was written.
    details = {"runId": pointer.get("runId"), "field": POINTER_KEY,
               "from": (previous or {}).get("runId"), "to": pointer.get("runId")}
    for key in ("taskId", "phaseId"):
        if ids.get(key) is not None:
            details[key] = str(ids[key])
    _journal_io.append(project, {
        "action": ACTION_MOVED.get(scope, ACTION_MOVED["phase"]),
        "actor": {"sessionId": session_id, "via": "evidence"},
        "target": _journal_io.repo_relative_or_token(project, path),
        "summary": "%s %s now points at run %s (%s)"
                   % (scope, ids.get("taskId") or ids.get("phaseId"),
                      pointer.get("runId"), pointer.get("status")),
        "details": details,
    }, config=config)
    return {"written": True, "reason": None, "path": path}


def latest_by_subject(rows):
    """The newest recorded run per `(scope, id)`, keyed for a pointer write.

    NEWEST BY `ts` AND NOT BY FILE ORDER. Rows land in one file per writer per
    month, so two worktrees produce two files whose concatenation is in no
    meaningful order at all; reading position would make "the latest run" depend
    on a directory listing.

    A row missing the id its own scope needs is skipped rather than guessed at -
    it cannot be pointed at anything, and inventing a subject for it would put a
    pointer on a task that never ran.
    """
    best = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        scope = row.get("scope")
        subject = row.get("taskId") if scope == "task" else row.get("phaseId")
        if not scope or not subject or not row.get("runId"):
            continue
        key = (scope, str(subject))
        current = best.get(key)
        if current is None or str(row.get("ts") or "") >= str(current.get("ts") or ""):
            best[key] = row
    return best


def reconcile(project, manifest_path, session_id=None, config=None):
    """Re-derive every pointer from the ledger. The repair `write_pointer` names.

    THIS IS WHY THE POINTER MAY BE REFUSED AT ALL. A cache write that loses a race
    with another live session leaves the plan behind the record, and this is the
    pass that catches it up - so the refusal costs a reader one command and never a
    fact. The ledger is the source of truth; nothing here reads the manifest to
    decide what is true, only to decide what still needs saying.

    Returns `{"moved", "refused", "already", "unreadable", "subjects"}`. `moved`
    and `refused` carry sentences, because a reconcile that could not finish must
    say which subjects it left behind rather than reporting a smaller number.
    """
    config = _journal_io.load_config(project) if config is None else config
    read = read_rows(project, config=config)
    best = latest_by_subject(read["rows"])
    moved, refused, already = [], [], []
    for (scope, subject), row in sorted(best.items()):
        if scope == "task":
            ids = {"taskId": subject, "phaseId": row.get("phaseId")}
        else:
            ids = {"phaseId": subject}
        current = _current_pointer(manifest_path, scope, ids)
        if current and current.get("runId") == row.get("runId"):
            already.append("%s %s" % (scope, subject))
            continue
        out = write_pointer(project, manifest_path, scope, ids, row,
                            session_id=session_id, config=config)
        if out["written"]:
            moved.append("%s %s -> %s" % (scope, subject, row.get("runId")))
        else:
            refused.append("%s %s: %s" % (scope, subject, out.get("reason")))
    return {"moved": moved, "refused": refused, "already": already,
            "unreadable": read["unreadable"], "subjects": len(best)}


def _current_pointer(manifest_path, scope, ids):
    """The pointer a subject carries now, or None. Never raises."""
    try:
        path, sharded = _phase_file(manifest_path, ids.get("phaseId"))
        if not path or not os.path.exists(path):
            return None
        body = _mio.read_json(path)
        phases = [body] if sharded else [
            p for p in (body.get("phases") or [])
            if isinstance(p, dict) and str(p.get("id")) == str(ids.get("phaseId"))]
        if not phases:
            return None
        if scope == "phase":
            return phases[0].get(POINTER_KEY)
        for task in (phases[0].get("tasks") or []):
            if isinstance(task, dict) and str(task.get("id")) == str(ids.get("taskId")):
                return task.get(POINTER_KEY)
    except Exception:
        return None
    return None


# --- the boundary: when could a run have been recorded at all ------------------
# WHAT THE GATE COULD NOT ASK. `no-test-evidence` asks whether finished work is
# backed by a recorded run, and never whether it COULD have been. For a plan
# adopted mid-flight -- hundreds of tasks finished before this recorder existed --
# the answer is no for every one of them, and no setting helps: `--phase` scopes
# the human render and says so in its own help, not the gate. That work is not a
# lapse, it is an impossibility, and what separates the two is a moment:
#
#     boundary = min( meta.evidenceSince.at , the earliest ts in the ledger )
#
# EXCUSED WORK IS BEFORE THE BOUNDARY, SO THE EARLIER VALUE IS THE SAFER ONE, and
# that is the whole reason this is a `min` rather than either source alone. A
# boundary that moved LATER would silently widen the excuse, which is the failure
# direction that matters for a gate; one that moves earlier only ever fails work
# it used to excuse, loudly, where somebody sees it. Delete the key and the ledger
# still answers, archive the ledger and the key still answers -- only destroying
# both widens the excuse, and that is deliberate destruction rather than an
# accident.
#
# BOTH SOURCES ARE READ BY EXPLICIT COMPARISON, never by truthiness. "No key",
# "no ledger" and "a boundary at the epoch" are three different states, and the
# one thing that could flatten them is a reader spelling `if not boundary`.
SINCE_KEY = "evidenceSince"
ACTION_SINCE = "meta.evidenceSince"
# The sentence the block carries about itself. It is written ONLY on the path that
# derives `at` from the earliest row in the ledger, so it is true of every block
# this module writes; a second derivation would owe a second sentence rather than
# reusing this one.
SINCE_BASIS = ("the first run this plan recorded; work completed before it "
               "could not carry evidence")
# ...and what a refused stamp costs, which is not what a refused POINTER costs.
# `--reconcile` re-derives pointers from the ledger and does not touch this key,
# so naming it here would send a human to a repair that cannot make the write.
# Nothing has to: the ledger row is already standing, the boundary still derives
# from it, and the next recorded run with the lock free writes the key down.
SINCE_HINT = ("nothing is lost - the ledger still dates the boundary, and the "
              "next --record taken with the lock free writes the key")


def since_block(manifest):
    """`meta.evidenceSince` exactly as the plan states it, or None when it has none.

    THE BLOCK AND THE MOMENT ARE TWO QUESTIONS. A plan carrying no key and a plan
    carrying one that states no usable moment are different states with different
    repairs -- write the key, versus fix the key that is there -- and a reader
    handed only the moment could not tell them apart.
    """
    meta = manifest.get("meta") if isinstance(manifest, dict) else None
    block = meta.get(SINCE_KEY) if isinstance(meta, dict) else None
    return block if isinstance(block, dict) else None


def stated_at(block):
    """The moment a `meta.evidenceSince` block states, or None when it states none.

    A non-string or blank `at` answers None rather than raising: this is read on
    every gate verdict, and a hand-edited plan must not take the surface down. The
    caller is told which of the two silences it met by `boundary_of`'s basis.
    """
    at = block.get("at") if isinstance(block, dict) else None
    return at.strip() if isinstance(at, str) and at.strip() else None


def earliest_recorded(rows):
    """The earliest `ts` any recorded run carries, or None when none carries one.

    COMPARED AS STRINGS, which is `latest_by_subject`'s rule at the other end of
    the same list and correct for the same reason: every row is stamped by `_now`
    in one fixed UTC spelling, so lexical order IS chronological order and parsing
    would add a way to fail without adding an answer.
    """
    stamps = [r.get("ts") for r in rows or []
              if isinstance(r, dict) and isinstance(r.get("ts"), str)
              and r.get("ts").strip()]
    return min(stamps) if stamps else None


def boundary_of(block, ledger_at, unknown=None):
    """The boundary from two already-read sources. The pure half of the question.

    `{"at", "sources", "basis", "unknown"}`. `at` is None when NEITHER source
    answered, which is the state of a repository that has never recorded anything
    -- everything in it predates recording, and the basis says exactly that rather
    than leaving a reader to infer it from a null.

    `unknown` is the half that must not be folded into "absent". A source that
    could not be ASKED -- an unreadable plan, a torn ledger line -- may have held
    an EARLIER moment, so treating it as absent moves the boundary later and
    widens the excuse in silence. Every such source is named here, and a caller
    with a non-empty list is holding a boundary that may be later than the truth.
    """
    key_at = stated_at(block)
    stamps = [s for s in (key_at, ledger_at) if s is not None]
    at = min(stamps) if stamps else None
    if key_at is not None and ledger_at is not None:
        basis = ("the plan states recording began %s and the earliest recorded "
                 "run is %s; the earlier of the two is the boundary, because "
                 "work before it could not have been recorded" % (key_at, ledger_at))
    elif key_at is not None:
        basis = ("the plan states recording began %s; no run is readable in the "
                 "ledger to confirm it" % (key_at,))
    elif ledger_at is not None and block is not None:
        basis = ("the plan carries %s but it states no usable moment, so the "
                 "boundary is the earliest recorded run, %s"
                 % (SINCE_KEY, ledger_at))
    elif ledger_at is not None:
        basis = ("this plan carries no %s, so the boundary is the earliest "
                 "recorded run, %s" % (SINCE_KEY, ledger_at))
    else:
        basis = ("nothing says when recording began: this plan carries no %s and "
                 "no run is readable in its ledger, so no work in it could have "
                 "carried evidence" % (SINCE_KEY,))
    return {"at": at, "sources": {"key": key_at, "ledger": ledger_at},
            "basis": basis, "unknown": list(unknown or [])}


def evidence_boundary(project, manifest_path, config=None):
    """The boundary, read from the plan and the ledger. Never raises.

    The door `boundary_of` sits behind: this is the one that touches disk, so a
    surface asking "may this subject be excused" gets an answer on a repository
    with no plan, no ledger, or neither.
    """
    config = _journal_io.load_config(project) if config is None else config
    unknown, block = [], None
    try:
        block = since_block(_mio.read_json(manifest_path))
    except Exception as exc:
        # NOT "no key". An unreadable plan may hold an EARLIER moment than the
        # ledger's, and calling that absent moves the boundary later -- the one
        # direction that widens an excuse without saying anything.
        unknown.append("the plan could not be read (%s), so anything %s states "
                       "is unknown" % (exc, SINCE_KEY))
    read = read_rows(project, config=config)
    if read["unreadable"]:
        unknown.append("%d ledger row(s) could not be parsed, and one of them may "
                       "carry an earlier run than any that could"
                       % (read["unreadable"],))
    return boundary_of(block, earliest_recorded(read["rows"]), unknown=unknown)


def _since_from_rows(rows):
    """`{"at", "runId"}` for the earliest recorded run, or None when there is none.

    THE PROVENANCE AND THE MOMENT COME OFF THE SAME ROW, which is what makes the
    block's `basis` true: `at` is when the first recorded run happened and `runId`
    names that run, rather than naming whichever run happened to be writing the
    key. `runId` is dropped when the row carries none -- an empty string would be
    a pointer at nothing, and this block is read as provenance.
    """
    at = earliest_recorded(rows)
    if at is None:
        return None
    first = [r for r in rows if isinstance(r, dict) and r.get("ts") == at]
    run_id = str(first[0].get("runId") or "") if first else ""
    out = {"at": at}
    if run_id:
        out["runId"] = run_id
    out["basis"] = SINCE_BASIS
    return out


def _refused(reason, at=None):
    """The shape every declined stamp answers with, so a caller reads one dict."""
    return {"written": False, "reason": reason, "at": at, "path": None}


def _since_locks(phase_id):
    """Which locks a stamp must clear, in one fixed order.

    BOTH, AND THE REASON IS THE LAYOUT. `meta` lives on the INDEX, which is the
    `index` lock's subject -- that one is the write's own guard. The phase lock is
    here because in the SINGLE-FILE layout the index and the phase body are the
    same bytes: `write_pointer` takes `phase-<id>` and rewrites the whole
    document, so a stamp that ignored it would be the second writer of one file.
    In the sharded layout that second check can only ever cost a refusal, and a
    refusal costs nothing here while a lost update costs somebody's pointer --
    which is `_locks`'s own bias, one caller over.
    """
    names = [("index", "index")]
    if phase_id is not None:
        names.append(("phase-%s" % (phase_id,), "phase"))
    return names


def write_evidence_since(project, manifest_path, phase_id=None, session_id=None,
                         config=None):
    """Stamp `meta.evidenceSince` the first time this plan records a run.

    `{"written", "reason", "at", "path"}`. Every `written: False` is a designed
    outcome carrying a sentence -- an already-stamped plan, a plan with nothing to
    date the boundary from, a lock another session is holding -- and none of them
    is an error path, because the ledger row is standing in every one of them.

    WRITTEN ONCE, AND NEVER RE-DERIVED. A key already present is left exactly as
    it is: re-deriving it every run would make the boundary a value that MOVES,
    and the direction it would move is later, which widens the excuse. Once a
    human or a run has written it down it is the plan's own claim.

    IT IS THE INDEX THIS WRITES, unlike the pointer beside it, and that is
    affordable for one reason only: it happens once in a plan's life. `meta` lives
    on the index in the sharded layout, so a per-run write here would put every
    parallel phase back in each other's way -- the conflict the layout exists to
    avoid. One write, once, is not that.
    """
    config = _journal_io.load_config(project) if config is None else config
    try:
        body = _mio.read_json(manifest_path)
    except Exception as exc:
        return _refused("cannot read %s: %s"
                        % (repo_relative_or_token(project, manifest_path), exc))
    meta = body.get("meta") if isinstance(body, dict) else None
    if not isinstance(meta, dict):
        return _refused("this manifest has no meta object to carry the boundary")
    standing = since_block(body)
    if standing is not None:
        return _refused("%s already states %s; a boundary is derived once and "
                        "never moved" % (SINCE_KEY, stated_at(standing)),
                        at=stated_at(standing))
    derived = _since_from_rows(read_rows(project, config=config)["rows"])
    if derived is None:
        # THE BASIS IS THE THING THAT IS MISSING, so this is what gets said. A
        # stamp taken from the wall clock here would date the boundary from the
        # moment somebody happened to run the gate, and every task finished after
        # that moment and before this one would be excused by a claim with
        # nothing behind it.
        return _refused("no recorded run to date the boundary from")
    taken, refusal = [], None
    for name, label in _since_locks(phase_id):
        state, detail = lock_state(project, name, label, session_id=session_id,
                                   hint=SINCE_HINT)
        if state in ("held", "stale"):
            refusal = detail
            break
        if state == "free":
            if not _locks.held(_locks.acquire(project, name,
                                              note="stamping the evidence boundary",
                                              session=session_id,
                                              out=lambda *_a: None)):
                refusal = "the %s lock could not be taken; %s" % (label, SINCE_HINT)
                break
            taken.append(name)
    try:
        if refusal is not None:
            return _refused(refusal)
        meta[SINCE_KEY] = derived
        try:
            _mio.atomic_write_json(manifest_path, body)
        except Exception as exc:
            return _refused("cannot write %s: %s"
                            % (repo_relative_or_token(project, manifest_path), exc))
    finally:
        for name in taken:
            _locks.release(project, name, session=session_id, out=lambda *_a: None)
    # ONLY NOW, and for `write_pointer`'s reason one field over: this row asserts
    # that the PLAN moved, so it is written after the move and never beside the
    # attempt. A refused stamp returns above without reaching here, which is what
    # keeps the chain from claiming a transition that did not happen.
    details = {"field": SINCE_KEY, "from": None, "to": derived["at"]}
    if derived.get("runId"):
        details["runId"] = derived["runId"]
    if phase_id is not None:
        details["phaseId"] = str(phase_id)
    _journal_io.append(project, {
        "action": ACTION_SINCE,
        "actor": {"sessionId": session_id, "via": "evidence"},
        "target": repo_relative_or_token(project, manifest_path),
        # THE SENTENCE IS THE BLOCK'S OWN, spent out of the same constant the
        # plan carries rather than paraphrased here: a summary that restated the
        # basis in its own words would be a second copy free to drift from the
        # one a reader of the manifest sees.
        "summary": "the evidence boundary is %s: %s" % (derived["at"], SINCE_BASIS),
        "details": details,
    }, config=config)
    return {"written": True, "reason": None, "at": derived["at"],
            "path": manifest_path}


def new_run_id():
    """A fresh, opaque run id: a stamp plus randomness.

    THE STAMP IS A CONVENIENCE FOR A HUMAN READING THE RAW FILE AND NOTHING MORE.
    The id is documented as OPAQUE and the schema says so, because the moment a
    reader parses it the format becomes an interface nobody agreed to - which is
    why `at` is a field of its own rather than something a consumer slices out of
    here.
    """
    return "%s.%s" % (_now(), binascii.hexlify(os.urandom(3)).decode("ascii"))


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answered rather than falling through to the library notice below: CI
        # runs `--selftest` over every file here. It deliberately does NOT print
        # the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_evidence_io.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__evidence_io.py - run that file instead.")
        raise SystemExit(0)
    print("This is a library module; run with --selftest to exercise it.")
