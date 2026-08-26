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


def pointer_lock_state(project, phase_id, session_id=None):
    """`(state, detail)` -- may this session write the phase's shard, and if not why.

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
    """
    try:
        if not _locks.available(project):
            return "unlockable", "this project has no lock scheme"
        path = os.path.join(_locks.lock_dir(project), "phase-%s.lock" % (phase_id,))
        if not os.path.exists(path):
            return "free", ""
        info = _locks.read_lock(path)
        holder = info.get("sessionId")
        if holder and session_id and str(holder) == str(session_id):
            return "ours", "held by this session"
        live, basis = _locks.judge(info, path)
        if live:
            return "held", ("the phase lock is held by another live run (%s); %s"
                            % (basis, RECONCILE_HINT))
        return "stale", ("the phase lock looks abandoned (%s); confirm with a "
                         "human and use audit-lock --takeover, then %s"
                         % (basis, RECONCILE_HINT))
    except Exception as exc:
        return "held", ("the phase lock could not be read (%s); %s"
                        % (exc, RECONCILE_HINT))


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
