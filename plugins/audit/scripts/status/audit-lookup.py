#!/usr/bin/env python3
"""
One question, one answer - never the whole plan for the sake of one row of it.

An agent asking "why was this task cancelled", "what did this bug conclude" or
"which task last touched this file" today has one way to find out: render the
whole manifest, or the whole journal, and read past everything else in it to find
the one row that answers the question. That cost grows with the project, not with
the question. This is the answer to each of those, read where the plugin
already keeps it and handed back with the pointer that lets a reader check it:

    audit-lookup.py <manifest> cancel <taskOrPhaseId> [--json]
    audit-lookup.py <manifest> bug <bugId> [--json]
    audit-lookup.py <manifest> file <path> [--json]
    audit-lookup.py <manifest> brief <taskId> [--json]
    audit-lookup.py <manifest> run <runId> [--json]
    audit-lookup.py <manifest> run latest (--phase <id> | --task <id>) [--json]

THE FILE QUESTION IS A LOOKUP, NOT A SEARCH. `fileIndex` already records which
tasks declared a path, in the order they were added - `manifest-conventions.md`'s
own rule ("never remove other tasks' ids") makes the LAST entry the most recently
declared task for that path, structurally, not by inference. So this reads the
key `path` names, exactly, and nothing else: a path the index does not carry gets
told so. IT NEVER RETURNS THE NEAREST THING - there is no fuzzy or prefix match
here, because a lookup that guessed at a similar path would be answering a
question nobody asked.

`brief` IS `file` FOLDED OVER ONE TASK'S OWN DECLARED FILES, so a spawn prompt
can carry the answer instead of the question. An executor is already handed
`task.files`; what it lacked was the one fact it would otherwise grep the
manifest or the journal for - who else last declared each of those same paths -
and answering that per path at spawn time is what turns "explore the tree" from
an agent's default first move into a deliberate step it has to justify, because
the plan already told it what grepping would have found.

`brief` ALSO CARRIES `executor.runsGate`, RESOLVED, because that word goes into
the same spawn prompt and was the one other fact the orchestrator had to look up
for it by hand. The reading is `hooks/_config.executor_gate_policy`'s, reached
through `_loader` because a script may not import `hooks/`, and it is printed
with its basis: the key and the file that set it, or that it is the default
because the file or the key is absent. A value outside the vocabulary, or a
config file that does not parse, is a REFUSAL - exit `E_CONFIG`, the problem
named on stderr, nothing on stdout - never the default, because printing the
default there would make a typo read as a decision.

A MATCH THAT FINDS NOTHING SAYS SO. `cancel` on an id this manifest does not have
at all, `bug` on an id not in `bugs[]`, `file` on a path `fileIndex` never
recorded, `brief` on a task id this manifest does not have (or that names a
phase, since `files` is a task field), `run` on a `runId` (or a `latest`
subject) the evidence ledger never recorded: all five exit non-zero with the
plain sentence that nothing was found, never a nearest guess dressed as an
answer. An id that DOES exist but was never cancelled is a different,
legitimate answer - not a miss - and says so too; so is a task `brief` finds
that simply declares no files yet.

`run` IS THE ONE QUESTION THAT READS THE EVIDENCE LEDGER RATHER THAN THE
MANIFEST OR THE JOURNAL. A gate that runs under `run_in_background` (longer
than the Bash tool's foreground bound) writes its verdict there long before its
own terminal is read again, so the orchestrator reads the row back instead of a
truncated terminal: `runId`, `ts`, `scope`/`subject`, `status`, `failed`, per
step `name`/`exit`/`durationMs`/`outcome`, and the failing lines and
`failingSuites` with their bases EXACTLY as `_evio.row_for` already bounded and
redacted them - never re-derived or re-cut here. `latest` in place of a runId,
with `--phase <id>` or `--task <id>`, answers the newest recorded row for that
subject (`_evio.latest_by_subject`) instead of one that must already be known.
AN UNREADABLE LEDGER FILE IS SAID, NEVER READ AS "no such run": a miss folds in
how many ledger files could not be read, because the run in question may be
sitting in one of those rather than one that never happened.

READ-ONLY. This never writes the manifest, the ledger or the journal.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_audit_lookup.py` - see `plugins/audit/tests/_harness.py`.
"""
import argparse
import json
import os
import sys

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

import _claude_home  # noqa: E402  (a usage error names this copy and a newer installed one)
import _manifest_io as _mio  # noqa: E402  (layer 1: the loader, the id indexes)
import _manifest_vocab as _vocab  # noqa: E402  (layer 1: `_strip_line_suffix`, the one
#                                             reading of a `files` entry's range suffix)
import _journal_io  # noqa: E402  (layer 1: the trail this cross-checks against)
import _evidence_io as _evio  # noqa: E402  (layer 2: project/config resolution)
import _loader  # noqa: E402  (the one way scripts/ loads hooks/_config as a library)

E_OK = 0
E_NOMATCH = 1
E_USAGE = 2
E_CONFIG = 3


# --- shared resolution ----------------------------------------------------------
def _find_node(manifest, node_id):
    """`(kind, node)` for a phase or task id, or `(None, None)`.

    Phases first and in full, because a phase can be cancelled before it has a
    single task - the same reason `audit-task.py`'s own `_find_target` sweeps
    phases before tasks."""
    for ph in (manifest.get("phases") or []):
        if isinstance(ph, dict) and ph.get("id") == node_id:
            return "phase", ph
    task = _mio.tasks_by_id(manifest).get(node_id)
    if task is not None:
        return "task", task
    return None, None


def _latest_cancel_row(rows, kind, node_id):
    """The newest `<kind>.cancel` journal row naming `node_id`, or None.

    `rows` is `_journal_io.read_all`'s output - oldest first - so the last
    match is the newest one, exactly as `fileIndex`'s own append-only order
    makes its last entry the most recent declaration. Matched on `details`,
    never on `target`: a task's cancel row's `target` is the SHARD PATH the
    write landed in, which several tasks in one phase share, while
    `details.taskId`/`details.phaseId` is the identity this question is about."""
    action = "%s.cancel" % (kind,)
    field = "taskId" if kind == "task" else "phaseId"
    hits = [r for r in (rows or [])
            if r.get("action") == action
            and (r.get("details") or {}).get(field) == node_id]
    return hits[-1] if hits else None


# --- the three questions ----------------------------------------------------------
def cancel_lookup(manifest, journal_rows, node_id):
    """`(found, payload_or_message)` for "why was `node_id` cancelled".

    An id this manifest does not have at all is the one case that returns
    `found=False` - a lookup that matches nothing says so and stops there,
    never reading a sibling id as the answer. An id that exists but was never
    cancelled is a legitimate answer of its own (`cancelled: False`), not a
    miss: the question was answerable, and the answer is that it does not
    apply."""
    kind, node = _find_node(manifest, node_id)
    if node is None:
        return False, "no task or phase %r in this manifest" % (node_id,)
    status = node.get("status")
    if status != "cancelled":
        # A phase's status is DERIVED, and the answer is the derivation's; the
        # stored value rides beside it only where the two differ.
        payload = {"id": node_id, "kind": kind, "cancelled": False,
                   "status": status,
                   "pointer": "%s.status in the manifest" % (node_id,)}
        if kind == "phase":
            derived = _mio.effective_phase_status(node)
            if derived != status:
                payload.update(status=derived, stored=status,
                               basis=_mio.phase_basis(node))
        return True, payload
    if kind == "task":
        reason_text = (node.get("outcome") or {}).get("descriptive") or ""
        field = "outcome.descriptive"
    else:
        reason_text = node.get("summary") or ""
        field = "summary"
    payload = {"id": node_id, "kind": kind, "cancelled": True,
              "reasonText": reason_text,
              "pointer": "%s.%s in the manifest" % (node_id, field)}
    row = _latest_cancel_row(journal_rows, kind, node_id)
    if row is not None:
        payload["journal"] = {"file": row.get("_file"), "ts": row.get("ts"),
                              "reason": (row.get("details") or {}).get("reason"),
                              "pointer": "action %s.cancel in %s"
                                        % (kind, row.get("_file"))}
    return True, payload


def bug_lookup(manifest, bug_id):
    """`(found, payload_or_message)` for "what did bug `bug_id` conclude".

    The manifest's own bug fields ARE the conclusion: there is no separate
    `resolution`/`conclusion` key in this schema, only `status` and the
    operator's own `notes`, carried verbatim by `/audit:bug close` - so that
    is what this reports, with the exact array index as the pointer rather
    than a synthesised one.

    `status` and `fixedIn` are the DERIVED values (`_mio.derived_disagreements`), which a
    linked fix task that is done moves to `fixed` and its commit; where the stored
    ones differ, `stored` carries them and `basis` says why."""
    bugs = manifest.get("bugs") or []
    for i, bug in enumerate(bugs):
        if isinstance(bug, dict) and bug.get("id") == bug_id:
            payload = {"id": bug_id, "status": bug.get("status"),
                       "notes": bug.get("notes"),
                       "fixedIn": bug.get("fixedIn"),
                       "taskId": bug.get("taskId"),
                       "pointer": "bugs[%d] in the manifest" % (i,)}
            drift = [r for r in _mio.derived_disagreements(manifest)
                     if r["kind"] == "bug" and r["id"] == bug_id]
            if drift:
                payload["stored"] = {"status": bug.get("status"),
                                     "fixedIn": bug.get("fixedIn")}
                payload["basis"] = drift[0]["basis"]
                for row in drift:
                    payload[row["field"]] = row["derived"]
            return True, payload
    return False, "no bug %r in this manifest" % (bug_id,)


def _drift_line(payload):
    """`stored X, derived Y (basis)` -- or None where stored and derived agree."""
    stored = payload.get("stored")
    if stored is None:
        return None
    if isinstance(stored, dict):
        pairs = [(field, stored.get(field), payload.get(field))
                 for field in ("status", "fixedIn")
                 if stored.get(field) != payload.get(field)]
    else:
        pairs = [("status", stored, payload.get("status"))]
    return "%s (%s)" % ("; ".join("%sstored %s, derived %s"
                                  % ("" if field == "status" else field + " ",
                                     was, now)
                                  for field, was, now in pairs),
                        payload.get("basis"))


def file_lookup(manifest, path):
    """`(found, payload_or_message)` for "which task last touched `path`".

    EXACT PATH MATCH ONLY. `fileIndex` is a lookup because the plugin already
    maintains it as one, keyed by the PATH a `files` entry names - a
    `:line-range` suffix stripped, the way the plan gate, the validator and the
    writers all read it - so `path` is compared on that same stripped form and
    kept as typed in the answer. A row an older writer keyed by the raw entry
    joins the same path. A path this manifest never declared returns
    `found=False`; there is no nearest-match fallback, because a lookup that
    guessed at a similar path would be a search wearing a lookup's name."""
    fidx = manifest.get("fileIndex")
    key = _vocab._strip_line_suffix(path)
    declaring = []
    if isinstance(fidx, dict):
        rows = [fidx.get(key)] + [ids for k, ids in sorted(fidx.items())
                                  if k != key and _vocab._strip_line_suffix(k) == key]
        for ids in rows:
            for tid in (ids if isinstance(ids, list) else []):
                if tid not in declaring:
                    declaring.append(tid)
    if not declaring:
        return False, "no task declares %r in fileIndex" % (path,)
    last = declaring[-1]
    task = _mio.tasks_by_id(manifest).get(last)
    return True, {"path": path, "declaringTasks": list(declaring), "last": last,
                  "lastStatus": task.get("status") if task else None,
                  "pointer": "fileIndex[%r][-1] of %d entries in the manifest"
                            % (key, len(declaring))}


def brief_lookup(manifest, task_id):
    """`(found, payload_or_message)` for "what does `task_id`'s own spawn brief
    owe about the files it declares" - `file_lookup` folded over every path
    in `task.files`, ONE CALL rather than one per path.

    An executor is already handed `task.files` in its spawn prompt
    (`reference/execute-task.md` step 3); what it is NOT handed is the one
    question it would otherwise grep the manifest or the journal to answer -
    which task last declared each of those same paths. `file_lookup` already
    answers that per path; this is the fold that makes it a single lookup at
    spawn time instead of `len(task.files)` of them, so exploring the tree
    for a fact the plan already carries becomes a deliberate, justified step
    rather than an agent's default first move.

    TASK ONLY, unlike `cancel_lookup` above: `files` is a task field, so a
    phase id here is a miss rather than an answer with an empty list -
    `cancel_lookup` reads a phase for a different reason and `brief_lookup`
    does not inherit it. A task with no declared files is a legitimate answer
    (`files: []`), never a miss: the question was answerable and the plan
    simply names nothing for this task yet."""
    kind, node = _find_node(manifest, task_id)
    if node is None or kind != "task":
        return False, "no task %r in this manifest" % (task_id,)
    entries = []
    for path in (node.get("files") or []):
        found, payload = file_lookup(manifest, path)
        entries.append({
            "path": path,
            "declaringTasks": payload["declaringTasks"] if found else [],
            "last": payload["last"] if found else None,
            "lastStatus": payload["lastStatus"] if found else None,
        })
    return True, {"id": task_id, "files": entries,
                  "pointer": "%s.files against fileIndex in the manifest"
                            % (task_id,)}


# --- executor.runsGate ------------------------------------------------------
def hooks_config():
    """`hooks/_config`, through `_loader` - the module that owns
    `executor_gate_policy`, `RUNS_GATE_MODES` and `CONFIG_REL`."""
    return _loader.load_hooks_config(modname="audit__config")


def runs_gate_reading(project, hc=None):
    """`(ok, payload_or_message)` for "which reading of `executor.runsGate`
    does the executor get".

    The WORD is `executor_gate_policy`'s and nobody else's; this adds only the
    basis, which that function cannot give because it reads a merged config
    where an absent key and a key set to the default look the same. So the
    project's own file is read as written, and the policy is asked about that
    dict - for which absent and default are still one answer, by its contract.

    A refusal (`ok=False`) is a value outside the vocabulary or a file that
    does not parse as a JSON object: the reading cannot be known, and the
    message names why instead of standing in a default for it."""
    hc = hc if hc is not None else hooks_config()
    rel = hc.CONFIG_REL
    try:
        with open(os.path.join(project, rel), "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (FileNotFoundError, NotADirectoryError):
        return True, {"reading": hc.executor_gate_policy({}), "default": True,
                      "basis": "the default - no %s" % (rel,)}
    except Exception as exc:
        return False, ("%s cannot be read (%s: %s) - no executor.runsGate "
                       "reading is printed, because the default would be a "
                       "guess at what the file says"
                       % (rel, type(exc).__name__, exc))
    if not isinstance(raw, dict):
        return False, ("%s is a JSON %s, not an object - no executor.runsGate "
                       "reading is printed" % (rel, type(raw).__name__))
    reading = hc.executor_gate_policy(raw)
    block = raw.get("executor")
    keyed = isinstance(block, dict) and "runsGate" in block
    if reading is None:
        return False, ("executor.runsGate is %r in %s, not one of %s - no "
                       "reading is printed, because folding it into the "
                       "default would make a typo read as a decision"
                       % (block["runsGate"], rel,
                          ", ".join(hc.RUNS_GATE_MODES)))
    if keyed:
        return True, {"reading": reading, "default": False,
                      "basis": "set by executor.runsGate in %s" % (rel,)}
    return True, {"reading": reading, "default": True,
                  "basis": "the default - executor.runsGate not set in %s"
                           % (rel,)}


# --- run ---------------------------------------------------------------------
# The step fields `run_lookup` reports, in the order the row already carries
# them - `_evio.STEP_KEYS` minus `ran`, `measured`, `timeoutSeconds`,
# `teardown`, `suiteReader` and the retry bookkeeping (`retriedAfterSignal`/
# `retryBasis`): each of those is a fact about how or whether a step was
# measured or retried, not a fact this lookup's caller is asking for.
# `failing`/`failingSuites` cross through EXACTLY as `_evio._step` bounded
# them at write time (`MAX_FAILING`/`MAX_PATHS`), never re-cut here - a
# second cut would be a second, possibly disagreeing, opinion about where
# the line is. `outcomeBasis`/`derivedGap` are the same rule applied to WHY a
# `could-not-run` step has no verdict: a derived-run gap, a missing
# interpreter and a runner's own no-verdict signature all set that one word,
# and without these two this lookup told a caller nothing more than the
# terminal it was meant to stand in for already scrolled past. `muted` is the
# mute that excused a step's failure, so a passed run beside a non-zero step
# says why.
_RUN_STEP_KEYS = ("name", "exit", "durationMs", "outcome",
                  "failing", "failingBasis", "failingSuites", "failingSuitesBasis",
                  "outcomeBasis", "derivedGap", "muted")


def _run_payload(row):
    """The bounded render of one evidence row - never raw runner output.

    `subject` is read off whichever of `taskId`/`phaseId` the row's own
    `scope` names, the same branch `_evio.latest_by_subject` takes to build its
    key - a row recording one and rendering the other would be answering a
    different row's question."""
    scope = row.get("scope")
    subject = row.get("taskId") if scope == "task" else row.get("phaseId")
    payload = {
        "runId": row.get("runId"), "ts": row.get("ts"), "scope": scope,
        "subject": subject, "status": row.get("status"),
        "failed": list(row.get("failed") or []),
        "steps": [dict((k, s[k]) for k in _RUN_STEP_KEYS if k in s)
                  for s in (row.get("steps") or []) if isinstance(s, dict)],
        "pointer": "evidence ledger row for runId %r" % (row.get("runId"),),
    }
    if row.get(_evio.VERDICT_SOURCE) is not None:
        payload[_evio.VERDICT_SOURCE] = row[_evio.VERDICT_SOURCE]
    if isinstance(row.get("reusedFrom"), dict):
        payload["reusedFrom"] = dict(row["reusedFrom"])
    return payload


def run_lookup(rows, run_id, phase_id=None, task_id=None, aliases=None,
              unreadable=0):
    """`(found, payload_or_message)` for "what did run `run_id` record" - or,
    with `run_id == "latest"`, the newest recorded run for the ONE subject
    named by `phase_id`/`task_id`.

    THE ANSWER TO "a gate ran in the background; what did it say", which today
    can only be read from a terminal a long gate may already have scrolled
    past. `rows` is `_evio.read_rows(...)["rows"]`; a specific `run_id` goes
    through `_evio.row_by_run`, `"latest"` through `_evio.latest_by_subject`
    keyed exactly as that function keys its own answers (`aliases` is
    `_evio.subject_aliases(manifest)`, so a task moved to a new id still
    answers under it).

    AN UNKNOWN RUN IS A MISS, worded like every other question here - never
    "no such run", which would claim more than a ledger this caller may not
    have read in full is entitled to. `unreadable` (a count of ledger files
    `_evio.read_rows` could not read) is folded into that same miss rather
    than swallowed: the run may be genuinely absent, or sitting in one of the
    files nothing here could open, and a caller deciding whether to re-run a
    gate needs to know which."""
    if run_id == "latest":
        scope = "phase" if phase_id else "task"
        subject = phase_id if phase_id else task_id
        key = (aliases or {}).get((scope, str(subject)), (scope, str(subject)))
        row = _evio.latest_by_subject(rows, aliases).get(key)
        label = "%s %r" % (scope, subject)
    else:
        row = _evio.row_by_run(rows, run_id)
        label = "run %r" % (run_id,)
    if row is None:
        message = "no recorded %s in the evidence ledger" % (label,)
        if unreadable:
            message += (" (%d ledger file(s) could not be read - the miss "
                        "may be there rather than a run that never happened)"
                        % (unreadable,))
        return False, message
    return True, _run_payload(row)


# --- cli --------------------------------------------------------------------------
def _render_human(question, node_id, found, payload):
    if not found:
        return ["no match: %s" % (payload,)]
    if question == "cancel":
        if not payload["cancelled"]:
            lines = ["%s is not cancelled (status: %s)"
                     % (node_id, payload["status"])]
            if _drift_line(payload):
                lines.append("  %s" % (_drift_line(payload),))
            return lines
        lines = ["%s was cancelled: %s" % (node_id, payload["reasonText"]),
                "pointer: %s" % (payload["pointer"],)]
        if "journal" in payload:
            lines.append("journal: %s (%s)"
                         % (payload["journal"]["pointer"], payload["journal"]["ts"]))
        return lines
    if question == "bug":
        lines = ["%s: status=%s notes=%s fixedIn=%s"
                 % (node_id, payload["status"], payload["notes"] or "(none)",
                    payload["fixedIn"] or "(none)")]
        if _drift_line(payload):
            lines.append("  %s" % (_drift_line(payload),))
        return lines + ["pointer: %s" % (payload["pointer"],)]
    if question == "brief":
        if not payload["files"]:
            lines = ["%s declares no files yet" % (node_id,)]
        else:
            lines = ["%s declares %d file(s):"
                     % (node_id, len(payload["files"]))]
            for entry in payload["files"]:
                if entry["last"] is None:
                    lines.append("  %s: not in fileIndex yet" % (entry["path"],))
                else:
                    lines.append("  %s: last declared by %s (status: %s)"
                                 % (entry["path"], entry["last"],
                                    entry["lastStatus"]))
            lines.append("pointer: %s" % (payload["pointer"],))
        gate = payload.get("runsGate")
        if gate is not None:
            lines.append("executor.runsGate: %s (%s)"
                         % (gate["reading"], gate["basis"]))
        return lines
    if question == "run":
        lines = ["run %s (%s %s): %s"
                 % (payload["runId"], payload["scope"], payload["subject"],
                    payload["status"])]
        for step in payload["steps"]:
            outcome = " outcome=%s" % (step["outcome"],) if step.get("outcome") else ""
            lines.append("  %s: exit=%s durationMs=%s%s"
                         % (step.get("name"), step.get("exit"),
                            step.get("durationMs"), outcome))
            for line in step.get("failing") or []:
                lines.append("    failing: %s" % (line,))
            for suite in step.get("failingSuites") or []:
                lines.append("    failingSuite: %s" % (suite,))
            # A PASSED run can hold a step that exited non-zero: the failure a
            # mute quarantined. Naming the mute is what keeps that row from
            # reading as a contradiction.
            for mute in step.get("muted") or []:
                if isinstance(mute, dict):
                    lines.append("    muted: %s (bug %s, until %s)"
                                 % (mute.get("test"), mute.get("bugId"),
                                    mute.get("until")))
            # WHY, WHEN THE STEP HAS NO VERDICT. Printed only for a step that
            # carries the field - a step recorded before it existed, or one
            # that measured cleanly, says nothing here rather than an empty
            # basis reading as a claim. `derivedGap` is named beside it rather
            # than folded into the same sentence, because it is a fact this
            # lookup can render on its own without re-parsing the basis text
            # a build might phrase differently tomorrow.
            if step.get("outcomeBasis"):
                lines.append("    basis: %s" % (step["outcomeBasis"],))
            if step.get("derivedGap"):
                lines.append("    derivedGap: this step answered a narrower "
                             "question than the phase's derived gate declared")
        if _evio.VERDICT_SOURCE in payload:
            lines.append("verdictSource: %s" % (payload[_evio.VERDICT_SOURCE],))
        if "reusedFrom" in payload:
            lines.append("reusedFrom: %s" % (payload["reusedFrom"],))
        lines.append("pointer: %s" % (payload["pointer"],))
        return lines
    # question == "file"
    return ["%s: last declared by %s (status: %s), %d task(s) total"
           % (node_id, payload["last"], payload["lastStatus"],
              len(payload["declaringTasks"])),
           "pointer: %s" % (payload["pointer"],)]


def build_parser():
    # `--project`/`--json` are declared on a PARENT parser and inherited by
    # every subcommand, never on the top-level parser alone: argparse's
    # subparsers action consumes every token after the subcommand name into
    # the SUBPARSER's own namespace, so a flag typed after `cancel <id>`
    # (the natural place to type it) would otherwise be reported as
    # unrecognised rather than accepted.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", dest="project", default=None, metavar="DIR",
                        help="project root (default: CLAUDE_PROJECT_DIR, else "
                             "the manifest's own directory)")
    common.add_argument("--json", action="store_true", dest="as_json",
                        help="print the answer as JSON instead of the human "
                             "render")
    p = argparse.ArgumentParser(
        prog="audit-lookup.py", add_help=True, allow_abbrev=False,
        parents=[common],
        description="Answer one question about the plan's trail, with a "
                    "pointer, instead of rendering the whole plan.")
    p.add_argument("manifest", help="path to the audit manifest")
    sub = p.add_subparsers(dest="question")
    sub.required = True
    cancel_p = sub.add_parser("cancel", parents=[common],
                              help="why was this task/phase cancelled")
    cancel_p.add_argument("id")
    bug_p = sub.add_parser("bug", parents=[common],
                           help="what did this bug conclude")
    bug_p.add_argument("id")
    file_p = sub.add_parser("file", parents=[common],
                            help="which task last touched this file")
    file_p.add_argument("path")
    brief_p = sub.add_parser(
        "brief", parents=[common],
        help="who last declared each file this task itself declares - "
             "one call, for a spawn prompt, instead of one `file` call per "
             "path - and the executor.runsGate reading, with its basis")
    brief_p.add_argument("id")
    run_p = sub.add_parser(
        "run", parents=[common],
        help="the evidence ledger row a background gate is read from")
    run_p.add_argument("id", metavar="runId", help="a runId, or 'latest'")
    run_p.add_argument("--phase", dest="phase", default=None, metavar="ID",
                       help="with `latest`: the newest run recorded for this "
                            "phase")
    run_p.add_argument("--task", dest="task", default=None, metavar="ID",
                       help="with `latest`: the newest run recorded for this "
                            "task")
    return _claude_home.attach_usage_hint(p)


def success_line(lines):
    """None, always: a lookup's answer is a PAYLOAD, printed whole.

    What this prints is the answer the caller asked for rather than a report
    that something was done - `brief` is folded verbatim into an executor's
    spawn prompt - so there is no shorter line to say it in, and a cut one
    would hand the caller part of an answer. The command still goes through
    `_output.terse_cli`, so `--verbose` is accepted here as on every verb the
    main loop calls, and prints the same bytes.
    """
    return None


def main(argv):
    args = build_parser().parse_args(argv)
    try:
        manifest = _mio.load_manifest(args.manifest)
    except Exception as exc:
        sys.stderr.write("audit-lookup.py: cannot read %s: %s\n"
                         % (args.manifest, exc))
        return E_USAGE

    if args.question == "cancel":
        project, config = _evio.project_config_for(args.manifest, args.project)
        try:
            journal_rows = _journal_io.read_all(project, config)
        except Exception:
            journal_rows = []
        found, payload = cancel_lookup(manifest, journal_rows, args.id)
        node_id = args.id
    elif args.question == "bug":
        found, payload = bug_lookup(manifest, args.id)
        node_id = args.id
    elif args.question == "brief":
        found, payload = brief_lookup(manifest, args.id)
        node_id = args.id
        if found:
            project, _config = _evio.project_config_for(args.manifest,
                                                        args.project)
            ok, gate = runs_gate_reading(project)
            if not ok:
                sys.stderr.write("audit-lookup.py: %s\n" % (gate,))
                return E_CONFIG
            payload["runsGate"] = gate
    elif args.question == "run":
        if args.id == "latest":
            if bool(args.phase) == bool(args.task):
                sys.stderr.write(
                    "audit-lookup.py: `run latest` needs exactly one of "
                    "--phase or --task\n")
                return E_USAGE
        elif args.phase or args.task:
            sys.stderr.write(
                "audit-lookup.py: --phase/--task only apply to `run "
                "latest`\n")
            return E_USAGE
        project, config = _evio.project_config_for(args.manifest, args.project)
        try:
            read = _evio.read_rows(project, config)
        except Exception as exc:
            sys.stderr.write(
                "audit-lookup.py: cannot read the evidence ledger: %s\n"
                % (exc,))
            return E_USAGE
        aliases = _evio.subject_aliases(manifest)
        found, payload = run_lookup(
            read["rows"], args.id, phase_id=args.phase, task_id=args.task,
            aliases=aliases, unreadable=read["unreadable"])
        node_id = args.id
    else:
        found, payload = file_lookup(manifest, args.path)
        node_id = args.path

    if args.as_json:
        print(json.dumps({"found": found,
                          "answer" if found else "message": payload},
                         indent=2, sort_keys=True))
    else:
        for line in _render_human(args.question, node_id, found, payload):
            print(line)
    return E_OK if found else E_NOMATCH


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exiting silently: `--selftest` is what every other
        # file here accepts, so nothing would tell a reader whether this one ran
        # nothing or has nothing. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("audit-lookup.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_audit_lookup.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(_output.terse_cli(main, sys.argv[1:], success_line))
