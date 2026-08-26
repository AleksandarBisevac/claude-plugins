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
