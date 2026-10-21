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

`brief --role executor|reviewer|phase` WRITES THE WHOLE SPAWN BRIEF TO A FILE,
and the agent is handed its path. The main loop used to compose each brief by
hand from `reference/execute-task.md`, and the brief then sat in its context for
the rest of the run; computed here it is the same every time, carries what a
retry owes (`attempts > 1`), and never passes through the main loop at all:
    audit-lookup.py <manifest> brief <taskId>  --role executor|writer|reviewer
    audit-lookup.py <manifest> brief <phaseId> --role phase
`--role writer` is not a brief: it writes the prompt a plain top-level session
is started on (`compose_writer_prompt`) - the task's own text in the layout the
baseline measured, with no path, rules, skills or submit in it.
The reviewer's brief carries the executor's return AS FILED, so it is REFUSED
(exit `E_REFUSED`, nothing written) until that return is filed for the task's
current start; the phase reviewer's brief is refused while any task of the phase
has no commit yet, because the binding it asks for would have no diff.

READ-ONLY OVER THE RECORD. This never writes the manifest, the ledger or the
journal; the one file it writes is a brief, under `stateDir`.

This module carries no `--selftest` of its own; its cases live in
`tests/test_audit_lookup.py` - see `tests/_harness.py`.
"""
import argparse
import json
import os
import pathlib
import re
import shlex
import subprocess
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

import _claude_home  # noqa: E402  (a usage error names this copy and a newer installed one)
import _manifest_io as _mio  # noqa: E402  (the loader, the id indexes)
import _manifest_vocab as _vocab  # noqa: E402  (`_strip_line_suffix`, the one
#                                             reading of a `files` entry's range suffix)
import _manifest_phases as _phases  # noqa: E402  (own_gate_entries: the entries
#                                               `run-test-gate --own` runs)
import _journal_io  # noqa: E402  (the trail this cross-checks against)
import _evidence_io as _evio  # noqa: E402  (project/config resolution)
import _excerpt  # noqa: E402  (a red step's output is quoted both ends, never head-cut)
import _loader  # noqa: E402  (the one way scripts/ loads hooks/_config as a library)
import _areas  # noqa: E402  (resolve_skills: area skills first, then the task's)
import _filed_returns as _fr  # noqa: E402  (where `submit` filed a return, and
#                                            which tasks a phase review owes)
import _config_rules  # noqa: E402  (review_per_task_mode: the config's reading now)
import _gate_feed  # noqa: E402  (review_asks: what the plan asks a reviewer to refuse)

E_OK = 0
E_NOMATCH = 1
E_USAGE = 2
E_CONFIG = 3
# A brief whose inputs are not on the record yet: the reviewer's before the
# executor's return is filed, the phase's before every task has a commit.
E_REFUSED = 4


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


# --- the computed brief ------------------------------------------------------
BRIEF_ROLES = ("executor", "writer", "reviewer", "phase")
BRIEFS_DIRNAME = _fr.BRIEFS_DIRNAME

# The one question a phase review asks of the request, fixed so every phase
# brief asks it in the same words.
PHASE_QUESTION = ("Where does a task choose something the request leaves open? "
                  "Name the task, the choice it made and the line of the request "
                  "that left it open.")

# A gate entry that names a `meta.buildCommands` key with a project after the
# colon: one token, a colon, no spaces.
_KEY_PROJECT = _fr.GATE_KEY_SHAPE


def _brief_context(manifest_path, project_arg):
    """Everything a brief resolves once: the roots, the manifest's path as the
    commands spell it, and the plugin copy THIS process is running."""
    project, config = _evio.project_config_for(manifest_path, project_arg)
    hc = hooks_config()
    return {"project": project, "config": config, "hc": hc,
            "gitRoot": os.path.abspath(os.path.join(
                project, (config or {}).get("gitRoot") or ".")),
            "manifest": _output.posix_rel(os.path.abspath(manifest_path),
                                          os.path.abspath(project)),
            "evidence": _evio.evidence_dir(project, config),
            "state": str(hc.state_dir(pathlib.Path(project), config or {})),
            "plugin": _output.PLUGIN_ROOT,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def _script(ctx, rel):
    return 'python3 "%s"' % (os.path.join(ctx["plugin"], "scripts",
                                          *rel.split("/")),)


def filed_return(ctx, task, role):
    """`(rel, text)` of `task`'s `role` return for its CURRENT start, or
    `(rel, None)` when none is filed there. A return under an earlier start is at
    another path, so it is never read as this start's."""
    rel = _fr.return_rel(str(task.get("id")), task.get("startedAt"), role)
    path = os.path.join(ctx["evidence"], *rel.split("/"))
    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            return rel, fh.read()
    except OSError:
        return rel, None


def previous_filed_return(ctx, task, role):
    """`(rel, body)` of the latest `role` return filed for `task` under a start
    STRICTLY BEFORE its current one - the attempt a retry left behind - or
    `(None, None)` when none exists. Read by scanning the task's own returns
    directory rather than by a start this caller is handed, because the only
    fact in front of a caller composing THIS attempt's brief is the CURRENT
    `startedAt`; the filed return the Retry section quotes is the one the
    attempt before it left, and `task.outcome`/`task.redFirst` are no
    substitute - those fields move only at `done`, so a retried, never-closed
    attempt leaves them exactly as they were before it ran."""
    tid = str(task.get("id"))
    current_key = _fr.return_start_key(task.get("startedAt"))
    base = os.path.join(ctx["evidence"], _fr.RETURNS_DIRNAME, tid)
    suffix = ".%s.json" % (role,)
    try:
        names = sorted(n for n in os.listdir(base) if n.endswith(suffix))
    except OSError:
        return None, None
    prior = [n for n in names if n[:-len(suffix)] < current_key]
    if not prior:
        return None, None
    rel = "%s/%s/%s" % (_fr.RETURNS_DIRNAME, tid, prior[-1])
    path = os.path.join(ctx["evidence"], *rel.split("/"))
    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            text = fh.read()
    except OSError:
        return rel, None
    try:
        body = json.loads(text)
    except ValueError:
        return rel, None
    return rel, body if isinstance(body, dict) else None


def retry_reason(ctx, phase, task):
    """The operator's own `--reason` beside the `--answer retry` that started
    this attempt, as `drive-phase.py` recorded it in the driver's state - or
    None when the driver recorded none (no reason was given, or this attempt
    was never reached through a retry). Keyed to THIS attempt's own start, so
    an earlier retry's reason is never read as this one's."""
    body, _problem = _fr.drive_state(ctx["state"], str(phase.get("id")))
    entry = (body.get("retryReason") or {}).get(str(task.get("id"))) or {}
    if not isinstance(entry, dict):
        return None
    if entry.get("start") != _fr.return_start_key(task.get("startedAt")):
        return None
    value = entry.get("value")
    return value if isinstance(value, str) and value.strip() else None


def gate_lines(manifest, entries):
    """One line per gate entry, the entry kept as written and its command beside
    it - or what stops it resolving, said rather than dropped."""
    build = ((manifest.get("meta") or {}).get("buildCommands") or {})
    build = build if isinstance(build, dict) else {}
    resolved = dict(_evio.resolved_commands(manifest, entries))
    lines = []
    for entry in entries or []:
        if not isinstance(entry, str) or not entry.strip():
            continue
        if entry in build:
            lines.append("- `%s` -> `%s`" % (entry, resolved.get(entry)))
        elif _KEY_PROJECT.match(entry):
            lines.append("- `%s` - unresolved: no meta.buildCommands entry "
                         "names it, so which tests it selects is not on the "
                         "record" % (entry,))
        else:
            lines.append("- `%s` (a literal command)" % (entry,))
    return lines or ["- none declared"]


def _task_gate(manifest, phase, task):
    """`(entries, whose)` - the task's own `tests.gate`, else its phase's."""
    return _fr.task_gate_entries(phase, task)


def own_tests_line(manifest, phase, task, run_gate):
    """What `own-tests` tells the executor to run: the `--own` command when the
    task's own gate selects its tests, else the gate's command that names a
    `tests.add` file, else that no entry names one - never a command that can
    only answer that it has nothing to run. Which entries are the task's own
    is `_manifest_phases.own_gate_entries`' answer, the one the runner's
    `--own` asks too."""
    if _phases.own_gate_entries(manifest, phase, task):
        return "Run your own added tests only: %s --own --quiet" % (run_gate,)
    added = [str(a).split(":", 1)[0].strip()
             for a in ((task.get("tests") or {}).get("add") or [])
             if isinstance(a, str) and a.strip()]
    if not added:
        return ("This task adds no test, so there is nothing of its own to "
                "run; the orchestrator's recorded run is the evidence.")
    cmd = red_command(manifest, phase, task)
    if cmd:
        return ("No gate entry is this task's own, so the own-tests run has "
                "nothing to run; run the suite command the gate names for your tests.add "
                "file: %s" % (cmd,))
    return ("No own-tests command to print: no gate entry names %s, so run "
            "the command that runs your new test - the one you put after "
            "`--` in the filing block below." % (", ".join(added),))


def _section(title, body_lines):
    return ["", "## %s" % (title,)] + list(body_lines)


def refuse_lines(manifest):
    """The reviewer's instructions from the plan's read-only gate entries, as a
    section, or [] when the plan declares none. A read of the diff has no
    command form, so this brief is the only place it is ever asked."""
    asks = _gate_feed.review_asks(manifest)
    if not asks:
        return []
    return _section("Refuse", [
        "The plan declares these checks as reads of the diff, not commands; "
        "nothing runs them, so you apply them:"]
        + ["- %s: %s" % (key, sentence) for key, sentence in asks])


def _verbatim(text, absent):
    return [text] if isinstance(text, str) and text.strip() else [absent]


def wave_tree(ctx, phase, task):
    """`(tree, base)` of a wave member - its own tree and the commit that tree
    was cut at - read from the driver's state, where `add_tree` records both;
    `(None, None)` for a task with no tree there (width 1, or a phase not
    driven in waves). The base is the task's own, since an adopted tree keeps
    the base it was cut from while its wave was cut later."""
    body, _problem = _fr.drive_state(ctx["state"], str(phase.get("id")))
    wave = body.get("wave") if isinstance(body.get("wave"), dict) else {}
    trees = wave.get("trees") if isinstance(wave.get("trees"), dict) else {}
    tree = trees.get(str(task.get("id")))
    if not isinstance(tree, str) or not tree:
        return None, None
    bases = wave.get("bases") if isinstance(wave.get("bases"), dict) else {}
    return tree, bases.get(str(task.get("id"))) or wave.get("base")


def wave_tree_lines(ctx, phase, task):
    """The lines that tell a wave member where it works: its own tree, the
    commit the tree was cut at, and the rules that follow from it; none for a
    task `wave_tree` finds no tree for."""
    tree, base = wave_tree(ctx, phase, task)
    if tree is None:
        return []
    return ["tree: %s" % (tree,),
            "base: %s" % (base,),
            "You work in this tree, not the project's. Begin every command "
            "with `cd %s &&`, and edit only files under it." % (tree,),
            "Never commit there: the driver carries your bytes into the phase "
            "tree, and the orchestrator commits."]


# What the executor owes when a runner's include has to change to collect its
# test: the preflight stops a task whose test no runner collects, and the
# executor's edit of the config is the other half. A fix for one directory was
# repeated by the next task in the testbed, one directory over.
WIDEN_RULE = ("When you widen a runner's include, widen it for the repo's test "
              "layout, not for the one directory in front of you.")


BIND_RULE = ("Return `casesAdded`: for each tests.add entry, by index, the case id "
             "the suite prints for the case you added (a list of ids when one entry "
             "covers several cases). The drive checks each id against the labels the "
             "suite printed; an entry with no id, or an id the suite did not print, "
             "is reported as a gap. Your titles are free wording.")


def compose_executor_brief(manifest, phase, task, ctx, files, gate):
    """The executor's whole brief, as lines. `files` is `brief_lookup`'s payload
    and `gate` the `executor.runsGate` reading with its basis.

    THE PART EVERY TASK SHARES COMES FIRST: the rules line and the return
    contract (no id, no command), then the task's own sections, and the
    task's `submit` command LAST. Two briefs then open on the same bytes up to
    `## Brief for <id>`, which is the prefix a prompt cache can reuse; the
    time and the task's record vary, so they come after it."""
    tid, pid = str(task.get("id")), str(phase.get("id"))
    attempts = task.get("attempts") or 0
    lines = ["# Executor brief", "",
             "The rules and the return shape are agents/audit-executor.md's."]
    lines += _section("Your return", executor_return_lines())
    lines += _section("Brief for %s" % (tid,), [
        "Computed by audit-lookup.py brief from %s at %s, plugin copy %s."
        % (ctx["manifest"], ctx["at"], ctx["plugin"]),
        "Task %s %r, attempt %s, started %s; phase %s %r."
        % (tid, task.get("title"), attempts, task.get("startedAt"), pid,
           phase.get("title"))])
    tree_lines = wave_tree_lines(ctx, phase, task)
    if tree_lines:
        lines += _section("Tree", tree_lines)
    skills = _areas.resolve_skills(manifest, phase, task)
    lines += _section("Skills", [
        "Invoke each via the Skill tool before touching code, in this order:"]
        + ["- %s" % (s,) for s in skills] if skills else [
        "No skill resolves for this task: no area default and no task skill."])
    lines += _section("Description (verbatim)",
                      _verbatim(task.get("description"),
                                "The task records no description."))
    lines += _section("Phase desired outcome",
                      _verbatim(phase.get("desiredOutcome"),
                                "The phase records no desiredOutcome."))
    if files["files"]:
        flines = [("- %s: last declared by %s (status: %s)"
                   % (e["path"], e["last"], e["lastStatus"]))
                  if e["last"] is not None else
                  "- %s: not in fileIndex yet" % (e["path"],)
                  for e in files["files"]]
        flines.append("pointer: %s" % (files["pointer"],))
    else:
        flines = ["The task declares no files yet."]
    lines += _section("Files", flines)
    docs = [d for d in (task.get("docs") or []) if isinstance(d, str)]
    lines += _section("Docs", ["- %s" % (d,) for d in docs]
                      or ["The task names no docs."])
    tests = task.get("tests") or {}
    entries, whose = _task_gate(manifest, phase, task)
    lines += _section("Tests", [
        "mode: %s; expectRedFirst: %s" % (tests.get("mode"),
                                          json.dumps(tests.get("expectRedFirst"))),
        "tests.add:"] + (["- %s" % (a,) for a in (tests.get("add") or [])]
                         or ["- none"])
        + ([BIND_RULE] if tests.get("add") else [])
        + ["gate, %s:" % (whose,)] + gate_lines(manifest, entries)
        + ([WIDEN_RULE] if tests.get("add") else []))
    reading = gate["reading"]
    run_gate = "%s %s %s --task %s" % (
        _script(ctx, "governance/run-test-gate.py"), ctx["manifest"], pid, tid)
    runs = {"full": "Run the whole gate: %s" % (run_gate,),
            "own-tests": own_tests_line(manifest, phase, task, run_gate),
            "never": "Run no gate yourself; report `\"gates\": {}`."}
    lines += _section("What you run", [
        "executor.runsGate: %s (%s)" % (reading, gate["basis"]),
        runs.get(reading, "The reading %r has no command here." % (reading,))])
    if attempts > 1:
        evidence = task.get("testEvidence") or {}
        _prior_rel, prior_body = previous_filed_return(ctx, task, "executor")
        prior_outcome = (prior_body or {}).get("outcome") or {}
        prior_red_first = (prior_body or {}).get("redFirst")
        # The filed return, never `task.outcome`/`task.redFirst` - those two
        # only move onto the task at `done` (`close_task`'s `red_first`/
        # `outcome` params), so a retried attempt that was never closed leaves
        # them exactly as an EARLIER attempt left them, which reads as "none
        # recorded" over a return that proved its red-first.
        reason = retry_reason(ctx, phase, task)
        lines += _section("Retry - what attempt %d left on the record"
                          % (attempts - 1,), [
            "operator's reason for --answer retry: %s"
            % (reason or "none recorded"),
            "outcome.technical (verbatim):",
            prior_outcome.get("technical") or "none recorded",
            "testEvidence: runId %s, status %s, at %s"
            % (evidence.get("runId"), evidence.get("status"),
               evidence.get("at")) if evidence else
            "testEvidence: none recorded",
            "redFirst: %s" % (json.dumps(prior_red_first, sort_keys=True)
                              if prior_red_first else "none recorded")]
            + red_step_lines(ctx, manifest, phase, task, evidence)
            + ["The working tree is the last attempt; this is what it answered."])
    lines += _section(SUBMIT_SECTION,
                      executor_submit_lines(manifest, phase, task, ctx))
    return lines


# --- the writer's prompt ---------------------------------------------------------
# The writer is a plain top-level session, so what it is handed is plain's own
# prompt for the task and nothing else: no brief path, no rules, no skills, no
# return contract. The layout is the one the owner's baseline measured, so a
# difference in what the session does is not a difference in what it was told.
# Three lines differ from that measured text on purpose: the commit sentence
# (the drive commits), the browser sentence (it names the drive as their runner)
# and the closing line (one answer per acceptance clause).

# A gate command is a browser gate when it runs one of these: the two
# screenshot/interaction drivers, the whole-suite runner that includes them, or
# the browser runner's own `test` subcommand. Read off the command's words, so a
# gate renamed in `meta.buildCommands` is still seen for what it runs.
BROWSER_GATE_SCRIPTS = ("capture-screenshots.mjs", "check-report-interactive.mjs",
                        "verify.sh")
BROWSER_GATE_TOKEN = ("playwright", "test")

ACCEPTANCE_MARK = "Acceptance:"
WRITER_COMMIT_LINE = ("Fix whatever does not pass. When everything is green, "
                      "leave the changes uncommitted: the drive commits them.")


def runs_browser(command):
    """Whether a resolved gate command opens a browser: a word's basename is one
    of `BROWSER_GATE_SCRIPTS`, or the words hold `playwright test` in a row."""
    words = [w.strip("\"'").rsplit("/", 1)[-1] for w in str(command or "").split()]
    token = list(BROWSER_GATE_TOKEN)
    return (any(w in BROWSER_GATE_SCRIPTS for w in words)
            or any(words[i:i + len(token)] == token for i in range(len(words))))


def acceptance_items(description):
    """The texts of the description's numbered Acceptance items, in order.

    Read after the LAST `Acceptance:` - a description numbers its own steps
    before it - and by sequence: `(2)` opens the second item only once `(1)`
    has opened the first, so a parenthesised number inside an item's own words
    (`the last of (7) lines`) stays in that item. A description with no
    `Acceptance:`, or no `(1)` after it, has no items."""
    text = description if isinstance(description, str) else ""
    at = text.rfind(ACCEPTANCE_MARK)
    if at < 0:
        return []
    body = text[at + len(ACCEPTANCE_MARK):]
    opens, want = [], 1
    for m in re.finditer(r"\((\d+)\)", body):
        if int(m.group(1)) == want:
            opens.append((m.start(), m.end()))
            want += 1
    return [body[end:(opens[i + 1][0] if i + 1 < len(opens) else len(body))].strip()
            for i, (_start, end) in enumerate(opens)]


def task_clauses(task):
    """`[{"n", "kind", "text"}]` - the clauses a task owes an answer to, numbered
    from one: its `tests.add` entries first, in order, then the numbered items of
    its description's Acceptance list. THE ONE NUMBERING: the writer's closing
    line is built from this list, and whatever reads the writer's answer is to
    read the same list rather than number the clauses a second time."""
    added = [a for a in ((task.get("tests") or {}).get("add") or [])
             if isinstance(a, str) and a.strip()]
    rows = ([("tests.add", a) for a in added]
            + [("acceptance", a) for a in acceptance_items(task.get("description"))])
    return [{"n": n, "kind": kind, "text": text}
            for n, (kind, text) in enumerate(rows, 1)]


def _clause_span(first, last):
    return ("clause %d" % first) if first == last else (
        "clauses %d to %d" % (first, last))


def writer_closing_line(task):
    """The one line that asks for an answer per clause, numbered by
    `task_clauses`; a task with no clause is told the empty object is the
    answer rather than asked for entries that do not exist."""
    clauses = task_clauses(task)
    if not clauses:
        return ("The task numbers no acceptance clause, so finish your last "
                "message with the empty JSON object {}.")
    parts = []
    for kind, what in (("tests.add", "the Tests to add entries in the order listed"),
                       ("acceptance", "the Acceptance items %s of the task description")):
        group = [c for c in clauses if c["kind"] == kind]
        if not group:
            continue
        if kind == "acceptance":
            what = what % ("(1)" if len(group) == 1 else "(1) to (%d)" % len(group))
        parts.append("%s %s %s" % (_clause_span(group[0]["n"], group[-1]["n"]),
                                   "is" if len(group) == 1 else "are", what))
    return ("Finish your last message with one JSON object holding one entry "
            "per acceptance clause, keyed by the clause's number: %s. Each entry "
            "is {\"delivered\": true, \"file\": \"<path>\", \"line\": <number>} "
            "naming the file and line that deliver the clause, or "
            "{\"delivered\": false, \"reason\": \"<why it is not delivered>\"}."
            % (", and ".join(parts),))


def _or_list(items):
    return items[0] if len(items) == 1 else (
        "%s or %s" % (", ".join(items[:-1]), items[-1]))


def compose_writer_prompt(manifest, phase, task):
    """The writer session's whole prompt, as lines: plain's own text for the
    task, composed from the task alone - no brief path, no rules, no skills, no
    submit - so two calls on the same task are the same bytes.

    A gate entry that names no `meta.buildCommands` key is a literal command, as
    the gate itself runs it (`_evio.resolved_commands`); a browser entry is left
    out of the commands to run and named, once, as the drive's. A plan whose
    gate has no browser entry gets no browser line: naming gates the task does
    not have would be a claim with no basis."""
    tests = task.get("tests") or {}
    files = [f for f in (task.get("files") or []) if isinstance(f, str)]
    added = [a for a in (tests.get("add") or []) if isinstance(a, str) and a.strip()]
    entries, _whose = _task_gate(manifest, phase, task)
    commands = [c for _name, c in _evio.resolved_commands(manifest, entries)]
    browser = [c for c in commands if runs_browser(c)]
    plain = [c for c in commands if not runs_browser(c)]
    lines = ["Implement the following task in this repository.", "",
             "Task: %s" % (task.get("title"),), ""]
    lines += _verbatim(task.get("description"), "The task records no description.")
    lines += ["", "Files the task declares:"]
    lines += ["- %s" % (f,) for f in files] or ["- none declared"]
    lines += ["", "Tests to add:"]
    lines += ["- %s" % (a,) for a in added] or ["- none"]
    lines += ["", "Before you finish, check that everything passes:"]
    lines += ["- %s" % (c,) for c in plain] or ["- none declared"]
    if browser:
        lines += ["", "Do not run %s: the drive runs the browser gates itself, "
                      "after your session ends." % (_or_list(browser),)]
    lines += ["", WRITER_COMMIT_LINE, "", writer_closing_line(task)]
    return lines


def red_step_lines(ctx, manifest, phase, task, evidence):
    """The red steps of the run the last attempt recorded, each with its command
    and what it printed (cut by `_excerpt`), or why they could not be read.
    A step's command is the row's own when the plan publishes it, else the gate
    entry of that name resolved, else the program the row kept."""
    run_id = (evidence or {}).get("runId")
    if not run_id:
        return ["red steps: not read - the task records no run"]
    try:
        rows = _evio.read_rows(ctx["project"], ctx["config"])["rows"]
    except Exception as exc:
        return ["red steps: not read - the ledger could not be read (%s)"
                % (str(exc) or exc.__class__.__name__,)]
    row = _evio.row_by_run(rows, run_id)
    if row is None:
        return ["red steps: not read - no ledger row carries runId %s" % (run_id,)]
    entries, _whose = _task_gate(manifest, phase, task)
    resolved = dict(_evio.resolved_commands(manifest, entries))
    red = [s for s in (row.get("steps") or [])
           if isinstance(s, dict) and _evio._step_failed(s)]
    if not red:
        return ["red steps: none - run %s has no step that exited red" % (run_id,)]
    out = []
    for step in red:
        name = step.get("name")
        command = (step.get("command") or resolved.get(name)
                   or "%s (command not stored)" % (step.get("program") or "?",))
        out.append("red step %s: %s" % (name, command))
        failing = [str(x) for x in step.get("failing") or []]
        suites = [str(x) for x in step.get("failingSuites") or []]
        if suites:
            out += failing_suite_lines(suites, failing)
        elif failing:
            # EACH RECORDED LINE, VERBATIM - `_evio`/`run-test-gate.py` already
            # bound this list (`MAX_FAILING`) before it ever reached the row,
            # so joining it back into one string and excerpting it a SECOND
            # time (as this used to) cuts an already-bounded record down
            # further and can drop a failing file's own name entirely behind
            # a bare "(+N more)" count. Printing every line this step named is
            # no wider than what the row already carries.
            out += ["  - %s" % (line,) for line in failing]
            if len(failing) >= _evio.MAX_FAILING:
                out.append("  (the row keeps at most %d failing lines and "
                           "names no failing files: any further failing file "
                           "is not recorded)" % (_evio.MAX_FAILING,))
        else:
            printed = _excerpt.reason_of(step.get("outcomeBasis") or "")
            out.append("  printed: %s"
                       % (printed or "nothing recorded for this step"))
    return out


def failing_suite_lines(suites, failing):
    """One entry per failing file the row names, each followed by the recorded
    FAIL lines that mention it. The row's line list is cut shorter than its
    file list, so a file can be named with no line of its own; that is printed
    as such, and a file list that itself reached its bound says further files
    are not recorded. Lines naming none of the files follow, unchanged."""
    out = []
    for suite in suites:
        own = [line for line in failing if suite in line]
        out.append("  - %s" % (suite,))
        out += ["      %s" % (line,) for line in own]
        if not own:
            out.append("      (no FAIL line recorded for this file: the row "
                       "keeps at most %d lines)" % (_evio.MAX_FAILING,))
    out += ["  - %s" % (line,) for line in failing
            if not any(suite in line for suite in suites)]
    if len(suites) >= _evio.MAX_PATHS:
        out.append("  (the row keeps at most %d failing files: any further "
                   "failing file is not recorded)" % (_evio.MAX_PATHS,))
    return out


def red_command(manifest, phase, task):
    """The resolved gate command that names one of the task's `tests.add`
    files, or None: the command `submit` hands the red-first helper -
    `_filed_returns.red_command`, the one reader the step driver asks too."""
    entries, _whose = _task_gate(manifest, phase, task)
    return _fr.red_command(task, _evio.resolved_commands(manifest, entries))


# The return travels on the submit's stdin, never through a file: the reviewer
# has no Write tool, and the plan gate refuses an executor's write outside its
# task's files, so "write it to a file" named a step one agent cannot take and
# the other is refused at. The delimiter is QUOTED so the shell leaves `$` and
# backticks inside the JSON as typed, and the block is fenced rather than
# indented because a heredoc ends only on a line that starts with its delimiter.
RETURN_DELIMITER = "AUDIT_RETURN"
RETURN_ON_STDIN = ("Put the return object in place of the middle line and run "
                   "the block as it stands - the object goes on the command's "
                   "stdin and nothing is written to disk")


def absolute_manifest(project, manifest, path=os.path):
    """`manifest` (spelled with `/`, as the plan records it) under `project`,
    in one separator style: joined alone, a Windows project would print
    `C:\\p\\docs/audit/audit-plan.json`, half of each. `path` is the path
    module to spell it with, so a test can ask for the Windows shape anywhere."""
    return path.normpath(path.join(project, manifest))


def submit_command(ctx, node_id, role, tail="", in_tree=False):
    """The resolved `drive-phase.py submit` an agent's last act runs, as a
    fenced block carrying the return on stdin in a quoted heredoc. A task in a
    tree of its own gets the phase tree's manifest spelled absolutely, and a
    line saying the command runs from the project: its own tree holds a
    committed copy of the relative path, with the task still pending."""
    manifest = ctx["manifest"]
    if in_tree:
        manifest = absolute_manifest(ctx["project"], manifest)
    block = [
        "```sh",
        "%s submit %s --role %s %s --project-dir %s%s <<'%s'" % (
            _script(ctx, "governance/drive-phase.py"), node_id, role,
            manifest, ctx["project"], tail, RETURN_DELIMITER),
        "<the return object, as JSON>",
        RETURN_DELIMITER,
        "```"]
    if in_tree:
        block.append("Run this command from the project (%s), not from your "
                     "tree: the plan it files against is the project's."
                     % (ctx["project"],))
    return "\n".join(block)


SUBMIT_SECTION = "Your return - the submit block"


def executor_return_lines():
    """The return contract, with nothing of the task in it: the same bytes in
    every executor brief, so it can sit in the prefix a prompt cache reuses.
    The command itself (the id, the tail) is `executor_submit_lines`', printed
    last."""
    return ["Your last act files the return object agents/audit-executor.md "
            "declares, with one `submit` call: it checks the shape, runs the "
            "red-first helper on the command after `--`, takes the stamp and "
            "files the return once. The command, resolved for this task, is "
            "the last section of this brief (%s). %s."
            % (SUBMIT_SECTION, RETURN_ON_STDIN)]


def executor_submit_lines(manifest, phase, task, ctx):
    """The executor's filing: one `submit`, as a block carrying the task's id.
    A tdd task owes the test command after `--`; it is printed resolved when a
    gate entry names a `tests.add` file, and asked for when none does."""
    tid = str(task.get("id"))
    tdd = (task.get("tests") or {}).get("mode") == "tdd"
    cmd = red_command(manifest, phase, task) if tdd else None
    if cmd:
        tail, note = " -- %s" % (cmd,), [
            "The command after `--` is the gate entry that names your tests.add "
            "file; narrow it to your cases if HEAD's own tests are red under it."]
    elif tdd:
        tail, note = " -- <the command that runs your new test>", [
            "This tdd task owes a test command after `--`, and no gate entry "
            "names its tests.add file, so name the one that runs your new test."]
    else:
        tail, note = "", [
            "Add `-- <test command>` to prove a regression test red in a "
            "throwaway tree; without it the `redFirst` you wrote is filed."]
    return ([submit_command(ctx, tid, "executor", tail,
                            wave_tree(ctx, phase, task)[0] is not None)]
            + note)


def _top(ctx):
    """The checkout's top for the brief's git root - where every diff below
    runs, so its pathspecs and its output share one base with the pair. The
    configured root is not always that top (a member project with no
    `gitRoot` set); when git cannot say, the configured root is kept and the
    git call that follows reports why it failed."""
    return hooks_config().checkout_top(ctx["gitRoot"]) or ctx["gitRoot"]


def _git_specs(ctx, files, top):
    """`files` as pathspecs read from `top` - each declared entry
    `_config.plan_to_git` places inside the checkout, its `:line` suffix
    dropped; an entry outside the checkout has no change git could list."""
    hc = hooks_config()
    specs = [hc.plan_to_git(_vocab._strip_line_suffix(f), top, ctx["project"])
             for f in files or [] if isinstance(f, str)]
    return [s for s in specs if s is not None]


def _diff_lines(ctx, files, tree=None, base=None):
    """The change to `files`, read from git, or why it is not: the phase
    tree's against HEAD, or - for a wave member, whose bytes are in its own
    tree until the driver integrates them - `tree`'s against `base`. `tree`
    is a checkout of the same repository, so the offset from its top to the
    project is the phase tree's and one set of pathspecs serves both."""
    hc = hooks_config()
    top = _top(ctx)
    paths = _git_specs(ctx, files, top)
    where, against = (tree, base) if tree else (top, "HEAD")
    command = "git %sdiff %s -- %s" % ("-C %s " % (tree,) if tree else "",
                                       against, " ".join(paths))
    if not paths:
        return ["`%s`: no declared file lies inside the checkout, so there is "
                "no change git could list." % (command,)]
    try:
        done = subprocess.run(["git", "-C", where, "diff", against, "--"]
                              + paths, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=60)
        # `--full-name` prints from the checkout's top, as `diff` reads.
        untracked = subprocess.run(
            ["git", "-C", where, "ls-files", "--others", "--full-name",
             "--exclude-standard", "--"] + paths,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return ["`%s` could not be run here (%s); run it yourself." % (command, exc)]
    if done.returncode != 0:
        return ["`%s` exited %d here (%s); run it yourself."
                % (command, done.returncode,
                   _excerpt.excerpt(done.stderr.decode("utf-8", "replace")))]
    lines = ["`%s`:" % (command,), "```diff",
             done.stdout.decode("utf-8", "replace").rstrip("\n") or "(empty)",
             "```"]
    new = [hc.git_to_plan(p, top, ctx["project"])
           for p in untracked.stdout.decode("utf-8", "replace").splitlines()
           if p]
    if new:
        lines.append("Untracked declared files, which the diff above does not "
                     "show - read them whole: %s" % (", ".join(new),))
    return lines


# Process bookkeeping, never code the reviewer judges: every diff this module
# computes for a phase brief leaves the project's docs/audit out, which
# `_diff_lines` itself does not need because a task-mode brief never spans more
# than one task.
DOCS_AUDIT = "docs/audit"


def _docs_audit_exclude(ctx, top):
    """The exclusion pathspec for the project's docs/audit, spelled from
    `top` - none when the checkout does not hold it, since a diff there
    cannot list it."""
    spec = hooks_config().plan_to_git(DOCS_AUDIT, top, ctx["project"])
    return [] if spec is None else [":(exclude)%s" % (spec,)]


# git's own hash for the empty tree, the same on every repository - the `against`
# side for a commit with no parent (a fixture's own root commit).
_EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def _task_commit_diff_lines(ctx, commit, files):
    """One owed task's own diff, computed once here instead of left as an
    instruction the reviewer re-derives: `commit`'s content restricted to
    `files`, docs/audit excluded. This is `git show <commit> -- <files>`'s
    patch half without its commit-message header, so concatenating every
    listed task's own diff, in order, equals one `git diff <base> <head>`
    over the union of their files - `commit`'s parent (or the empty tree for
    a root commit) against `commit` is the same comparison `git show` makes."""
    top = _top(ctx)
    paths = _git_specs(ctx, files, top)
    command = ("git show %s -- %s" % (commit, " ".join(paths)) if paths
              else "git show %s" % (commit,))
    if not paths and any(isinstance(f, str) for f in files or []):
        # An empty pathspec would widen the diff to the whole commit.
        return ["diff (%s): no declared file lies inside the checkout, so the "
                "commit holds no change to them." % (command,)]
    parent = "%s^" % (commit,)
    has_parent = subprocess.run(
        ["git", "-C", top, "rev-parse", "--verify", "--quiet",
         parent], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=60).returncode == 0
    against = parent if has_parent else _EMPTY_TREE_SHA
    try:
        done = subprocess.run(
            ["git", "-C", top, "diff", against, commit, "--"]
            + paths + _docs_audit_exclude(ctx, top),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return ["`%s` could not be run here (%s); run it yourself." % (command, exc)]
    if done.returncode != 0:
        return ["`%s` exited %d here (%s); run it yourself."
                % (command, done.returncode,
                   _excerpt.excerpt(done.stderr.decode("utf-8", "replace")))]
    out = done.stdout.decode("utf-8", "replace").rstrip("\n")
    return ["diff (%s, docs/audit excluded) - computed once, not re-derived:"
            % (command,), "```diff", out or "(empty)", "```"]


def _phase_diff_paths(ctx, base, head):
    """Every path `git diff <base> <head>` names, docs/audit excluded - or
    `(None, why)` when it could not be read."""
    top = _top(ctx)
    exclude = _docs_audit_exclude(ctx, top)
    command = "git diff --name-only %s %s -- %s" % (base, head,
                                                     " ".join(exclude))
    try:
        done = subprocess.run(
            ["git", "-C", top, "diff", "--name-only", base, head,
             "--"] + exclude,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "`%s` could not be run here (%s)." % (command, exc)
    if done.returncode != 0:
        return None, "`%s` exited %d (%s)." % (
            command, done.returncode,
            _excerpt.excerpt(done.stderr.decode("utf-8", "replace")))
    # git names these from the checkout's top, a task declares its files from
    # the project: one base, or a nested project's declared file reads as an
    # outside path and a checkout-root file of the same name reads as covered.
    hc = hooks_config()
    return [hc.git_to_plan(p, top, ctx["project"])
            for p in done.stdout.decode("utf-8", "replace").splitlines()
            if p], None


def _phase_scope_lines(ctx, phase, head):
    """The phase diff's whole path list and, named as such, every path it
    changed that no task in the phase declares - the scope no per-task diff
    can show, because each of those only ever reads one task's own files."""
    base = phase.get("baseRef")
    if not base:
        return ["Not computed: phase.baseRef is absent, so the phase's whole "
                "diff path list cannot be read."]
    if not head:
        return ["Not computed: the head could not be read."]
    paths, why = _phase_diff_paths(ctx, base, head)
    if why:
        return ["Not computed: %s" % (why,)]
    declared = set()
    for t in phase.get("tasks") or []:
        if isinstance(t, dict):
            declared.update(_vocab._strip_line_suffix(f)
                            for f in (t.get("files") or [])
                            if isinstance(f, str))
    outside = [p for p in paths if p not in declared]
    return (["Phase diff paths (git diff %s %s, docs/audit excluded):"
            % (base, head)]
            + (["- %s" % (p,) for p in paths] or ["none"])
            + ["Paths outside every task's declared files:"]
            + (["- %s" % (p,) for p in outside] or ["none"]))


def _filed_obj(text):
    """The executor's filed return as a dict, parsed once - `{}` when none is
    filed yet or the text on record does not parse as a JSON object, so a
    caller reading `testsAdded` off it gets an absent value rather than a
    raise. Never printed itself: the brief prints `text` AS FILED."""
    if not isinstance(text, str) or not text.strip():
        return {}
    try:
        obj = json.loads(text)
    except ValueError:
        return {}
    return obj if isinstance(obj, dict) else {}


# Probe 2 (24 reviewer runs, Opus/Sonnet/Haiku, over a real P5.3 brief
# section): the brief as filed, task text first with the claim labelled, and
# the claim hidden, each found 0/3 `diverges`; only a rule asking the reviewer
# to quote each clause worked, 3/3 on all three models. Computed here rather
# than added to `agents/audit-reviewer.md` - that file is already within a few
# bytes of `measure-context.py --gate`'s ceiling, and this text is per-brief,
# not loaded on every reviewer start.
CLAUSE_QUOTING_LINES = [
    "Quote each clause of the task's own description (below, labelled "
    "`## Task`) and judge the diff against THAT clause - never against the "
    "executor's restatement or its test titles. A scope difference between "
    "a clause and the diff is `diverges`, quoted both sides, even when the "
    "executor's own note agrees with its narrowed scope.",
    "Answer two things, not one: does the diff do what the clause asked, "
    "and separately, does the executor's claim (labelled `## Claim under "
    "review` below) describe the diff in front of you - `intent.note` "
    "quotes both.",
    "A finding whose `issue` contradicts a task clause is floored at `med` "
    "before it can file as `low`, but only by its spelling: start the issue "
    'with "%s" (the drive\'s `floor_contradicted_clause` matches that text '
    "and nothing else) - do not file it low yourself."
    % (_fr._CONTRADICTED_CLAUSE_MARKER,)]


def _filed_gaps(task, filed):
    """The tests.add gaps a filed return carries: the drive's own reading
    (`testsAddGaps`, written at `submit` against the labels the suite printed)
    when the return holds one, else the binding alone - what a return filed
    before the drive wrote that field can still be graded on."""
    held = filed.get(_fr.GAPS_FIELD)
    if isinstance(held, list):
        return [str(g) for g in held]
    return _fr.case_binding_gaps(task, filed.get(_fr.CASES_FIELD), None)


def _filed_unchecked(filed):
    """The `tests.add` entries a filed return records as never compared with a
    printed label (`testsAddUnchecked`, written at `submit`), or [] for a return
    that holds none - one filed before the field, or one whose submit graded
    every entry."""
    held = filed.get(_fr.UNCHECKED_FIELD)
    return [str(g) for g in held] if isinstance(held, list) else []


def _tests_add_review_lines(task, filed):
    """`tests.add`, the gaps the drive already named before any reviewer runs
    (`filed` is the executor's return as an object), and the two questions (4)
    asks of every declared test:
    can it fail on the unfixed code, and does it reach a real external
    service or side effect rather than a stub. Measured on the testbed with
    the same model: the plugin's executors alone shipped a lazy-load test
    that could not fail, an e2e that sent real mail, and a race asserting
    state the SSR HTML already had - none of the three a plain session
    shipped."""
    tests = task.get("tests") or {}
    add = [str(a) for a in tests.get("add") or []]
    gaps = _filed_gaps(task, filed)
    lines = ["tests.add:"] + (["- %s" % (a,) for a in add] or ["- none"])
    if gaps:
        lines += ["Declared with no filed counterpart (named by the drive, "
                 "before you run - not yours to re-derive):"] + (
            ["- %s" % (g,) for g in gaps])
    unchecked = _filed_unchecked(filed)
    if unchecked:
        lines += ["Ids the drive never compared with a printed label (the "
                  "submit's command did not run their suite - neither passed "
                  "nor failed, so verify them yourself):"] + (
            ["- %s" % (u,) for u in unchecked])
    if add:
        lines += ["Per declared test, ask: (1) can it fail on the unfixed "
                 "code - read the executor's `redFirst` word and basis, or "
                 "say it was never seen red; (2) does it reach a real "
                 "external service or side effect (mail, payment, network) "
                 "rather than a stub - name its file:line if it does."]
    return lines


def compose_reviewer_brief(manifest, phase, task, ctx, filed):
    """The task-mode reviewer's whole brief, as lines. `filed` is the
    executor's `(rel, text)` for the current start, text present. The task's
    own description and the executor's filed return are the LAST section,
    adjacent and in that order (`claim_section`) - everything else a reviewer
    needs (the gate, the diff) comes first, so nothing sits between the task's
    words and the claim graded against them."""
    tid = str(task.get("id"))
    entries, whose = _task_gate(manifest, phase, task)
    evidence = task.get("testEvidence") or {}
    filed_obj = _filed_obj(filed[1])
    lines = ["# Brief for %s (reviewer, mode: task)" % (tid,), "",
             "Computed by audit-lookup.py brief from %s at %s, plugin copy %s."
             % (ctx["manifest"], ctx["at"], ctx["plugin"]),
             "The rules and the return shape are agents/audit-reviewer.md's."]
    lines += _section("Phase desired outcome",
                      _verbatim(phase.get("desiredOutcome"),
                                "The phase records no desiredOutcome."))
    lines += _section("The intent question", CLAUSE_QUOTING_LINES)
    lines += _section("tests.add", _tests_add_review_lines(task, filed_obj))
    lines += _section("The recorded gate run", [
        "runId %s, status %s, at %s (task.testEvidence)"
        % (evidence.get("runId"), evidence.get("status"), evidence.get("at"))
        if evidence else "No run is recorded for this task (no "
        "task.testEvidence) - read that as absent, not as passed."])
    lines += _section("Gate commands, %s" % (whose,),
                      gate_lines(manifest, entries))
    lines += refuse_lines(manifest)
    tree, base = wave_tree(ctx, phase, task)
    if tree is not None:
        lines += _section("Tree", [
            "tree: %s" % (tree,), "base: %s" % (base,),
            "This task ran in a tree of its own and its bytes are not in the "
            "phase tree yet; the diff below is read in that tree against that "
            "base. Read its files there, not in the project."])
    lines += _section("The diff", _diff_lines(ctx, task.get("files"), tree, base))
    lines += [""] + _fr.claim_section(task, filed[1]).split("\n")
    lines += _section("Your return", [
        "File the return object agents/audit-reviewer.md declares - your one "
        "write. %s:" % (RETURN_ON_STDIN,),
        submit_command(ctx, tid, "reviewer", "", tree is not None)])
    return lines


def phase_brief_refusal(phase):
    """The task ids that leave a phase review nothing to bind, or []: a task
    still open, or one closed as done with neither a commit nor a no-change
    answer."""
    held = []
    for task in phase.get("tasks") or []:
        if not isinstance(task, dict) or task.get("status") == "cancelled":
            continue
        no_change = (task.get("outcome") or {}).get("noChange")
        if task.get("status") != "done" or not (task.get("commit") or no_change):
            held.append(str(task.get("id")))
    return held


def _choices_lines(phase):
    """`phase.openChoices` verbatim, one line each, or what its absence means."""
    choices = phase.get("openChoices")
    if not isinstance(choices, list):
        return ["No open choices were recorded (phase.openChoices is absent): "
                "nobody was asked which choices the request left open."]
    if not choices:
        return ["The planner recorded that the request left no choice open."]
    return ["- %s" % (c,) for c in choices]


def _head(ctx):
    """`(sha, None)` - the head this brief is computed at - or `(None, why)`."""
    try:
        done = subprocess.run(["git", "-C", ctx["gitRoot"], "rev-parse", "HEAD"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "git could not be run here (%s)" % (exc,)
    sha = done.stdout.decode("utf-8", "replace").strip()
    if done.returncode != 0 or not sha:
        return None, ("`git rev-parse HEAD` exited %d (%s)" % (
            done.returncode, _excerpt.excerpt(done.stderr.decode("utf-8", "replace"))))
    return sha, None


# The three per-task questions a phase review answers under `review.perTask:
# phase`, each by the rule `mode: task` applies to one task. The second and
# third are asked only where a task's own section says they are yours: the
# filing verb fills the mechanical ones (`_fr.complete_phase_return`).
PER_TASK_QUESTIONS = (
    "1. intent: does this task's diff do what its description asked, and does "
    "its executor's claim describe the diff?",
    "2. red-first, where its section says yours: was a test this task added "
    "ever seen red? Grade the executor's `redFirst` by its basis.",
    "3. inherited tests, where its section says yours: of the tests its gate "
    "commands select, would any still pass with the behaviour it names deleted?")


def answer_lines(answers, owed):
    """The two lines saying, for one owed task, whether the filing verb fills
    its red-first and inherited-test answers or the reviewer gives them - and,
    for a filled one, the word only a human settles that may be typed over it
    (`_fr.ESCALATIONS`)."""
    lines = []
    for label, word, basis in (("red-first", "redFirst", "redFirstBasis"),
                               ("inherited tests", "inheritedTests",
                                "inheritedTestsBasis")):
        if word in answers:
            ups = " or ".join("`%s`" % (u,) for u in _fr.ESCALATIONS[word])
            lines.append("%s: computed (%s) - the filing verb fills `%s` and "
                         "`%s`; leave both out of its entry, or type %s with "
                         "its basis to put it to a human, and the verb "
                         "records the override"
                         % (label, answers[word], word, basis, ups))
        else:
            lines.append("%s: yours - %s" % (label, owed.get(word)
                                             or "no rule computes it"))
    return lines


def existing_test_lines(ctx, phase, head):
    """The existing test files the phase's diff modifies - modified between
    `phase.baseRef` and the brief's head, a test path by `_fr.is_test_path` -
    or why the list cannot be computed. A test file the phase added is not
    listed, and neither is one it moved."""
    base = phase.get("baseRef")
    if not base:
        return ["Not computed: phase.baseRef is absent, so which test files "
                "existed when the phase began is not on the record."]
    if not head:
        return ["Not computed: the head could not be read."]
    command = "git diff --no-renames --diff-filter=M --name-only %s %s" % (
        base, head)
    top = _top(ctx)
    try:
        done = subprocess.run(["git", "-C", top, "-c",
                               "core.quotepath=off", "diff", "--no-renames",
                               "--diff-filter=M", "--name-only", base, head],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return ["Not computed: `%s` could not be run here (%s)." % (command, exc)]
    if done.returncode != 0:
        return ["Not computed: `%s` exited %d (%s)." % (
            command, done.returncode,
            _excerpt.excerpt(done.stderr.decode("utf-8", "replace")))]
    hc = hooks_config()
    paths = [hc.git_to_plan(p, top, ctx["project"])
             for p in done.stdout.decode("utf-8", "replace").splitlines() if p]
    paths = [p for p in paths if _fr.is_test_path(p)]
    return (["`%s`, test paths only; a test file the phase added is not listed. "
             "Read each change against the task whose diff holds it:" % (command,)]
            + (["- %s" % (p,) for p in paths] or ["None."]))


def _review_owed(ctx, phase):
    """`(live, answered, reviewed, problem)` - the config's `review.perTask` now
    (read only where a task with a commit records no key), the commits filed
    phase returns already answer, and every commit a filed round reviewed
    (`_fr.reviewed_entries`)."""
    live, problem = None, None
    if any(t.get("commit") and _fr.review_key(t, phase, None)[1] == "config"
           for t in phase.get("tasks") or [] if isinstance(t, dict)):
        live, problem = _config_rules.review_per_task_mode(ctx["config"])
    filed = _fr.phase_returns(ctx["evidence"], str(phase.get("id")))
    unread = [why for _rel, _body, why in filed if why]
    return (live, _fr.answered_entries(filed), _fr.reviewed_entries(filed),
            problem or ("; ".join(unread) if unread else None))


def shown_argument(tasks):
    """The `--shown` value naming `tasks` at the commit each records, in their
    order: what a phase brief showed, for the filing verb to record."""
    return _fr.shown_argument_of(shown_pairs(tasks))


def shown_pairs(tasks):
    """`(id, commit)` for each of `tasks`, in their order - the set a phase
    brief showed, as the record beside it and its `--shown` both name it."""
    return [(str(t.get("id")), t.get("commit")) for t in tasks]


def _owed_line(task, phase, live, answered):
    """What this task's entry is owed, said on its own line."""
    hit = answered.get((str(task.get("id")), task.get("commit")))
    if hit is not None:
        return "review answers: answered by %s at this commit" % (hit[0],)
    key, source = _fr.review_key(task, phase, live)
    if key != _fr.KEY_PHASE:
        return ("review answers: not owed here - review.perTask reads %s (%s)"
                % (key, source))
    if _fr.is_fix_task(task, phase):
        return ("review answers: not owed - a fix task the plan records as one "
                "(task.fixes), closed with its own basis")
    return "review answers: OWED - answer the three questions for this task"


def gate_banners(row):
    """The banners a green gate run still printed, read off its ledger row:
    NO OVERLAP when the run named none of the task's files (`coverage` empty -
    None is a run that could not be asked, which is not this), TREE CHANGED
    when files changed while it ran. Both say the gate did not measure the work
    the way its exit code reads."""
    obs = (row or {}).get("observations") or {}
    out = []
    if obs.get("coverage") == []:
        out.append("NO OVERLAP - the gate named none of this task's files, so "
                   "it did not measure this work")
    mutated = obs.get("treeMutated") or []
    if mutated:
        out.append("TREE CHANGED - files changed while it ran: %s"
                   % (", ".join(str(m) for m in mutated),))
    return out


def _recorded_run_line(evidence, rows, rows_why):
    """The `recorded run:` line of one task in the phase brief, with the gate's
    banners beside it, or why the row that would carry them was not read."""
    if not evidence:
        return "recorded run: none recorded"
    line = "recorded run: runId %s, status %s" % (evidence.get("runId"),
                                                 evidence.get("status"))
    if rows_why:
        return "%s (its ledger row could not be read: %s)" % (line, rows_why)
    row = _evio.row_by_run(rows, evidence.get("runId"))
    if row is None:
        return ("%s (its ledger row was not found, so whether the gate printed "
                "a banner is not known)" % (line,))
    banners = gate_banners(row)
    return "%s; %s" % (line, "; ".join(banners)) if banners else line


def phase_brief_parts(manifest, phase, ctx):
    """The sign-off reviewer's brief in the pieces a slice is cut from: the
    `header` (the request as saved, the choices it left open, the fixed
    question, the re-review scope), one `units` entry `(task, lines)` for every
    task with a diff on its own record, the `wide` sections that belong to the
    phase and not to a task, and what the closing sections are made of - `owed`
    (the task ids owed their three answers under `review.perTask: phase`),
    `shown` (the tasks the units show), the head this brief was computed at and
    `owed_why` where which tasks are owed could not be read. `head` is None
    when git did not answer."""
    pid = str(phase.get("id"))
    head, head_why = _head(ctx)
    live, answered, seen, owed_why = _review_owed(ctx, phase)
    lines = ["# Brief for %s (reviewer, mode: phase)" % (pid,), "",
             "Computed by audit-lookup.py brief from %s at %s, plugin copy %s."
             % (ctx["manifest"], ctx["at"], ctx["plugin"]),
             "head: %s" % (head,) if head else
             "head: not read - %s" % (head_why,),
             "The rules and the return shape are agents/audit-reviewer.md's."]
    lines += _section("The request, as saved", _verbatim(
        phase.get("request"),
        "No request was saved for this phase (phase.request is absent), so "
        "where a task chose what the request left open cannot be asked of "
        "the record."))
    lines += _section("The choices the request left open", _choices_lines(phase))
    lines += _section("The question", [PHASE_QUESTION])
    lines += refuse_lines(manifest)
    lines += _section("Phase desired outcome",
                      _verbatim(phase.get("desiredOutcome"),
                                "The phase records no desiredOutcome."))
    lines += _section("The intent question, per task", CLAUSE_QUOTING_LINES)
    listed, skipped = [], []
    for task in phase.get("tasks") or []:
        if not isinstance(task, dict) or not task.get("commit"):
            if isinstance(task, dict):
                skipped.append(str(task.get("id")))
            continue
        listed.append(task)
    rows, rows_why = [], ""
    try:
        read = _evio.read_rows(ctx["project"], ctx["config"])
        rows = read["rows"]
    except Exception as exc:
        rows_why = str(exc) or exc.__class__.__name__
    build = (manifest.get("meta") or {}).get("buildCommands") or {}
    mechanical = _fr.phase_answers(
        ctx["evidence"], phase, build,
        lambda entries: _evio.resolved_commands(manifest, entries))
    # A RE-REVIEW SHOWS WHAT NO EARLIER ROUND REVIEWED, AND NOTHING IT DID.
    # What an earlier round reviewed is read off its filed return at the
    # commit of each task: the `tasks` entries it answered, and the `shown`
    # list the filing verb records from this brief's own `--shown` - the one
    # record of a fix task, which is owed no entry. Its head is not used: an
    # ancestor test misreads a rewritten branch, and a task closed by hand
    # after the round is just as absent from the return as from that head.
    # So the shown set is every task with a diff at a commit no round
    # reviewed - every task closed since, and every fix since - and `owed`
    # below is drawn from the same set, which is why each owed task has a
    # section: a task still owed is shown even where a round's list names it.
    # With no filed return nothing is known reviewed, and all shows.
    def reviewed_by(task):
        return seen.get((str(task.get("id")), task.get("commit")))

    def is_shown(task):
        return (reviewed_by(task) is None
                or _fr.owed_answer(task, phase, live, answered))
    reviewed = [t for t in listed if not is_shown(t)]
    shown = [t for t in listed if is_shown(t)]
    fixers = [t for t in shown if _fr.is_fix_task(t, phase)]
    scope = []
    if reviewed:
        returns = sorted(set(reviewed_by(t) for t in reviewed))
        scope += [
            "An earlier round reviewed these, recorded by %s at the commit "
            "each records, so they are not repeated here: %s"
            % (", ".join(returns),
               ", ".join(str(t.get("id")) for t in reviewed)),
            "Shown below is every task no filed round reviewed at its commit "
            "- every task closed since, fix tasks included: %s"
            % (", ".join(str(t.get("id")) for t in shown) or "none",)]
    if fixers:
        scope += [
            "This phase already carries findings from an earlier review; "
            "its fix task(s) are among the tasks shown: %s"
            % (", ".join(str(t.get("id")) for t in fixers),),
            "A new `low` finding in these fixes is carried (`--answer carry "
            "--to <task or bug id>`), not looped into another fix and another "
            "round; only a `med` or `high` one owes a fix."]
    if scope:
        lines += _section("Re-review scope", scope)
    header, units = lines, []
    for task in shown:
        tid = str(task.get("id"))
        entries, whose = _task_gate(manifest, phase, task)
        evidence = task.get("testEvidence") or {}
        _rel, text = filed_return(ctx, task, "executor")
        answers, owed_by = mechanical.get(tid, ({}, {}))
        computed = answer_lines(answers, owed_by) if (
            not owed_why and _fr.owed_answer(task, phase, live, answered)) else []
        # The task's own description and its filed return are the LAST two
        # things in the section, adjacent and in that order (`claim_section`)
        # - everything a reviewer needs to ask about first (the gate, the
        # diff, the owed answers) comes before them, same rule as the
        # task-mode brief. Ordered before the nested `## Task` / `## Claim
        # under review` headers `claim_section` writes, not after: the
        # per-task body a re-review reads (`answer_lines` in
        # `test_audit_lookup.py`) is split at the next `## ` header, so text
        # placed after that nested pair would read as outside this task.
        units.append((task, _section("%s %s" % (tid, task.get("title") or ""), [
            "commit: %s" % (task.get("commit"),),
            "files:"] + ["- %s" % (f,) for f in task.get("files") or []]
            + _tests_add_review_lines(task, _filed_obj(text)) + [
            _recorded_run_line(evidence, rows, rows_why),
            "gate commands, %s:" % (whose,)] + gate_lines(manifest, entries)
            + _task_commit_diff_lines(ctx, task.get("commit"),
                                      task.get("files"))
            + [_owed_line(task, phase, live, answered)] + computed
            + [""] + _fr.claim_section(
                task, text if text is not None else
                "none filed for its current start").split("\n"))))
    wide = _section("Phase diff scope", _phase_scope_lines(ctx, phase, head))
    wide += _section("Existing test files the phase modifies",
                     existing_test_lines(ctx, phase, head))
    if skipped:
        wide += _section("Tasks with no diff", [
            "Closed with no commit (a no-change close) or cancelled, so there "
            "is no diff to review: %s" % (", ".join(skipped),)])
    owed = [str(t.get("id")) for t in shown
            if _fr.owed_answer(t, phase, live, answered)]
    return {"pid": pid, "head": head, "head_why": head_why, "header": header,
            "units": units, "wide": wide, "owed": owed, "owed_why": owed_why,
            "shown": shown}


def phase_closing_lines(ctx, parts, shown, owed, slice_of=None):
    """The brief's last sections for the `shown` tasks and the `owed` ids among
    them: which are owed their answers, and the filing command keyed on this
    head, this shown set and - for a slice `(n, total)` - this slice."""
    pid, head, head_why = parts["pid"], parts["head"], parts["head_why"]
    # The set this brief shows rides on its filing command, so the verb can
    # record what the round reviewed - fix tasks included, which no `tasks`
    # entry ever names - and the next round's brief leaves it out.
    file_cmd = submit_command(ctx, pid, "reviewer", " --head %s%s%s" % (
        head or "<head>",
        " --shown %s" % (shlex.quote(shown_argument(shown)),) if shown else "",
        " --slice %d/%d" % slice_of if slice_of else ""))
    lines = []
    if not owed:
        # FILED EVEN WHEN NOTHING IS OWED: the step driver reads the phase
        # review's findings from the filed return, so a return handed back
        # only as a final message would be a review it never sees.
        lines += _section("Review answers owed per task", [
            "None: no task here is owed its three answers by this review."])
        lines += _section("Your return", [
            "File the return object agents/audit-reviewer.md declares, with "
            "`\"tasks\": []` - the verb writes it once for this head. %s:"
            % (RETURN_ON_STDIN,),
            file_cmd if head else
            "The head could not be read (%s), so there is no head to file "
            "under: run this brief again where git answers." % (head_why,)])
        return lines
    lines += _section("Review answers owed per task", [
        "review.perTask reads `phase`, so no reviewer answered these tasks one "
        "by one: you do, by the rules `mode: task` applies to one task. Each "
        "line below is one task owed a `tasks` entry, bound to the commit named "
        "in its section above:"] + ["owed: %s" % (tid,) for tid in owed]
        + ["Ask of each:"] + list(PER_TASK_QUESTIONS))
    lines += _section("Your return", [
        "File the return object agents/audit-reviewer.md declares, with one "
        "`tasks` entry per task owed above - the verb refuses a return that "
        "leaves one out, and writes it once for this head. %s:"
        % (RETURN_ON_STDIN,),
        file_cmd if head else
        "The head could not be read (%s), so there is no head to file under: "
        "run this brief again where git answers." % (head_why,)])
    return lines


def compose_phase_brief(manifest, phase, ctx):
    """`(lines, head, shown)` - the sign-off reviewer's whole brief, as lines:
    the header, every task with a diff on its own record, and under
    `review.perTask: phase` the tasks owed their three answers, the head this
    brief was computed at and the filing command keyed on it. `head` is None
    when git did not answer; `shown` is the `(id, commit)` set its sections
    show, None when the brief stops before computing it."""
    return whole_phase_brief(ctx, phase_brief_parts(manifest, phase, ctx))


def whole_phase_brief(ctx, parts):
    """`compose_phase_brief`'s answer for `phase_brief_parts`' pieces."""
    lines = list(parts["header"])
    for _task, unit in parts["units"]:
        lines += unit
    lines += parts["wide"]
    if parts["owed_why"]:
        lines += _section("Review answers owed per task", [
            "Which tasks are owed their answers could not be read: %s. Sign-off "
            "and its filing refuse until it can." % (parts["owed_why"],)])
        return lines, parts["head"], None
    lines += phase_closing_lines(ctx, parts, parts["shown"], parts["owed"])
    return lines, parts["head"], shown_pairs(parts["shown"])


# --- a phase brief past the reader's budget ------------------------------------
# A reader takes a brief whole, so a phase of many tasks with large diffs wrote
# one nobody could take: two phase reviews were 2.5 and 2.3 megabytes and were
# possible only by cutting the brief by hand and adding the returns up by hand.
# A brief over the budget is cut instead at TASK boundaries - a task's section is
# the unit a reviewer answers, so a cut inside one would split a claim from its
# diff. Each slice holds the header, whole tasks and its own owed lines and
# filing command; `drive-phase.py` dispatches one reviewer per slice and files
# their returns as the one return. A single task whose section alone passes the
# budget is a slice of its own: there is nothing smaller to cut at.
PHASE_BRIEF_BUDGET = 400000
SLICE_ROOM = 2000     # bytes a slice's banner and index line may add to its estimate
SLICE_LINE = "slice %d/%d: %s"


def _bytes_of(lines):
    return sum(len(line.encode("utf-8")) + 1 for line in lines)


def pack_slices(ctx, parts, budget):
    """The `units` of `parts` grouped into slices, as lists of `(task, lines)`:
    each group is filled in plan order until the next task would take its
    estimated size past `budget`, the phase-wide sections counted in the first
    group. A group always holds at least one task."""
    owed = set(parts["owed"])

    def closing(group):
        tasks = [task for task, _unit in group]
        ids = [str(t.get("id")) for t in tasks if str(t.get("id")) in owed]
        return _bytes_of(phase_closing_lines(ctx, parts, tasks, ids, (99, 99)))

    fixed = _bytes_of(parts["header"]) + SLICE_ROOM
    groups, used = [[]], fixed + _bytes_of(parts["wide"])
    for pair in parts["units"]:
        grown = groups[-1] + [pair]
        cost = used + _bytes_of(pair[1]) + closing(grown)
        if groups[-1] and cost > budget:
            groups.append([pair])
            used = fixed + _bytes_of(pair[1])
        else:
            groups[-1] = grown
            used += _bytes_of(pair[1])
    return groups


def slice_lines(ctx, parts, group, number, total, budget, first):
    """One slice of the brief: the header under a title naming the slice, a
    banner saying what the reader holds, its task sections, the phase-wide
    sections where `first`, and the owed lines and filing command of its own
    tasks."""
    tasks = [task for task, _unit in group]
    ids = [str(t.get("id")) for t in tasks]
    owed = [tid for tid in parts["owed"] if tid in ids]
    head_lines = list(parts["header"])
    head_lines[0] = "# Brief for %s (reviewer, mode: phase, slice %d/%d)" % (
        parts["pid"], number, total)
    banner = [
        "This is slice %d of %d of one phase brief that outgrew the reader "
        "budget (%d bytes) and was cut at task boundaries. It holds whole: %s."
        % (number, total, budget, ", ".join(ids)),
        "Another reviewer holds each other slice. Answer the tasks owed below "
        "and file the return your slice prints under `## Your return`: the drive "
        "files the one phase return once every slice has filed."]
    lines = head_lines[:2] + banner + head_lines[2:]
    for _task, unit in group:
        lines += unit
    if first:
        lines += parts["wide"]
    lines += phase_closing_lines(ctx, parts, tasks, owed, (number, total))
    return lines, owed


def sliced_phase_brief(ctx, parts, whole_size, node_id, budget=PHASE_BRIEF_BUDGET):
    """`None` while the brief stays one file, else `{"index": text, "slices":
    [{"n", "path", "text", "tasks", "owed", "shown"}, ...]}` - the index file's
    text and each slice's file, the ids it holds, the ids it is owed and the
    `(id, commit)` pairs it shows. A brief stays whole when it fits `budget`,
    when git named no head to key a slice's filing on, when which tasks are owed
    could not be read, and when the tasks do not make more than one group."""
    if (whole_size <= budget or not parts["head"] or parts["owed_why"]
            or len(parts["units"]) < 2):
        return None
    groups = pack_slices(ctx, parts, budget)
    if len(groups) < 2:
        return None
    total = len(groups)
    slices = []
    for number, group in enumerate(groups, 1):
        lines, owed = slice_lines(ctx, parts, group, number, total, budget,
                                  number == 1)
        tasks = [task for task, _unit in group]
        slices.append({"n": number, "text": "\n".join(lines) + "\n",
                       "path": brief_file(ctx, node_id, "phase", None, number),
                       "tasks": [str(t.get("id")) for t in tasks],
                       "owed": owed, "shown": shown_pairs(tasks)})
    head = parts["header"]
    index = [head[0] + " - sliced", ""] + head[2:4] + [
        "The brief outgrew the reader budget (%d bytes) and is written as %d "
        "slices, one per reviewer; no reviewer reads this file." % (budget, total)]
    for one in slices:
        index += [SLICE_LINE % (one["n"], total, one["path"]),
                  "  tasks: %s" % (", ".join(one["tasks"]),)]
    return {"index": "\n".join(index) + "\n", "slices": slices}


def with_slices_text(record_text, slices):
    """The shown-set record `_fr.shown_brief_text` wrote, with a `slices` list
    added - each slice's number, the tasks it holds and is owed, and the pairs
    it shows - for the filing verb to hold a slice's return to."""
    body = json.loads(record_text)
    body["slices"] = [{"n": one["n"], "tasks": one["tasks"], "owed": one["owed"],
                       "shown": _fr.shown_record(one["shown"])}
                      for one in slices]
    return json.dumps(body, indent=2) + "\n"


def brief_target(manifest, node_id, role):
    """`(phase, task)` for a brief, or None when `node_id` is not the kind of
    node `role` briefs: a phase for `phase`, a task otherwise."""
    if role == "phase":
        for ph in manifest.get("phases") or []:
            if isinstance(ph, dict) and ph.get("id") == node_id:
                return ph, None
        return None
    for ph in manifest.get("phases") or []:
        for task in (ph.get("tasks") or []) if isinstance(ph, dict) else []:
            if isinstance(task, dict) and task.get("id") == node_id:
                return ph, task
    return None


def brief_file(ctx, node_id, role, started_at=None, part=None):
    """Where a brief is written: under `stateDir`, keyed by the start a task
    brief belongs to, so a retry's brief never reads as the first one's. `part`
    is the number of a slice of a phase brief that outgrew the reader budget."""
    name = ("phase.md" if role == "phase" and part is None else
            "phase.slice%d.md" % (part or 0) if role == "phase" else
            "%s.%s.md" % (_fr.return_start_key(started_at), role))
    return os.path.join(ctx["state"], BRIEFS_DIRNAME, node_id, name)


def write_brief(manifest, manifest_path, project_arg, node_id, role):
    """`(code, message)` - compute one brief and write it, or why not."""
    target = brief_target(manifest, node_id, role)
    if target is None:
        return E_NOMATCH, ("no %s %r in this manifest"
                           % ("phase" if role == "phase" else "task", node_id))
    phase, task = target
    ctx = _brief_context(manifest_path, project_arg)
    record, extra = None, []
    if role == "phase":
        held = phase_brief_refusal(phase)
        if held:
            return E_REFUSED, (
                "REFUSED: %s has task(s) with no commit yet (%s) - the phase "
                "review binds each task's answers to its commit, and those would "
                "have no diff. Close them first. No brief written."
                % (node_id, ", ".join(held)))
        parts = phase_brief_parts(manifest, phase, ctx)
        lines, head, shown = whole_phase_brief(ctx, parts)
        record = (None if head is None or shown is None else
                  (_fr.shown_brief_path(ctx["state"], node_id, head),
                   _fr.shown_brief_text(head, shown)))
        cut = sliced_phase_brief(ctx, parts, _bytes_of(lines), node_id)
        if cut is not None:
            # The index is what `written:` names, so the drive finds the head
            # and the slices there; the whole brief is not written at all.
            lines = cut["index"].rstrip("\n").split("\n")
            record = (record[0], with_slices_text(record[1], cut["slices"]))
            extra = [(one["path"], one["text"]) for one in cut["slices"]]
    elif not task.get("startedAt"):
        return E_REFUSED, ("REFUSED: %s records no start (`startedAt`), and a "
                           "brief belongs to one start - /audit:task start %s "
                           "first. No brief written." % (node_id, node_id))
    elif role == "reviewer":
        filed = filed_return(ctx, task, "executor")
        if filed[1] is None:
            return E_REFUSED, (
                "REFUSED: the reviewer's brief carries the executor's return as "
                "filed, and none is filed for %s's current start (%s). File it "
                "first: drive-phase.py submit %s --role executor. No brief "
                "written." % (node_id, filed[0], node_id))
        lines = compose_reviewer_brief(manifest, phase, task, ctx, filed)
    elif role == "writer":
        lines = compose_writer_prompt(manifest, phase, task)
    else:
        ok, gate = runs_gate_reading(ctx["project"], ctx["hc"])
        if not ok:
            return E_CONFIG, gate
        _found, files = brief_lookup(manifest, node_id)
        lines = compose_executor_brief(manifest, phase, task, ctx, files, gate)
    path = brief_file(ctx, node_id, role, (task or {}).get("startedAt"))
    writes = [(path, "\n".join(lines) + "\n")] + extra
    if record is not None:
        writes.append(record)
    for where, text in writes:
        try:
            os.makedirs(os.path.dirname(where), exist_ok=True)
            with open(where, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
        except OSError as exc:
            return E_USAGE, ("the brief could not be written to %s (%s)"
                             % (where, exc))
    return E_OK, path


def write_exact(stream, text):
    """Put `text` on `stream` as the UTF-8 bytes a brief is written in.

    A text stream is no route for those bytes: on Windows it turns every "\\n"
    into "\\r\\n", so a CRLF line a brief embeds leaves as "\\r\\r\\n", and its
    encoding is the console's code page, which cannot spell every character a
    brief carries. So the bytes go to the stream's own buffer. A stream with
    no buffer is an in-memory one, which neither translates nor encodes."""
    raw = getattr(stream, "buffer", None)
    if raw is None:
        stream.write(text)
        return
    stream.flush()
    raw.write(text.encode("utf-8"))
    raw.flush()


def read_brief(manifest, manifest_path, project_arg, node_id, role, part=None):
    """`(code, text)` - the brief `write_brief` wrote for `node_id`'s current
    start, read back unchanged, or why there is none. It composes nothing, so
    an agent reads the brief the drive dispatched it with - for a phase brief
    cut into slices, the slice `part` numbers."""
    if role is None:
        return E_USAGE, "--read reads one role's brief: give --role"
    if part is not None and role != "phase":
        return E_USAGE, "--slice reads a slice of a phase brief: give --role phase"
    target = brief_target(manifest, node_id, role)
    if target is None:
        return E_NOMATCH, ("no %s %r in this manifest"
                           % ("phase" if role == "phase" else "task", node_id))
    ctx = _brief_context(manifest_path, project_arg)
    path = brief_file(ctx, node_id, role, (target[1] or {}).get("startedAt"), part)
    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            return E_OK, fh.read()
    except OSError as exc:
        return E_NOMATCH, ("no %s brief is written for %s's current start (%s: "
                           "%s)" % (role, node_id, path, exc.strerror or exc))


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
    brief_p.add_argument(
        "--role", dest="role", default=None, choices=list(BRIEF_ROLES),
        help="write the whole spawn brief for this role to a file under "
             "stateDir and print its path: executor or reviewer for a task, "
             "phase for a phase")
    brief_p.add_argument(
        "--read", dest="read", action="store_true",
        help="with --role: print the brief already written for the current "
             "start, byte for byte, and write nothing")
    brief_p.add_argument(
        "--slice", dest="slice", type=int, default=None, metavar="N",
        help="with --read --role phase: print slice N of a phase brief that "
             "outgrew the reader budget and was written as slices")
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
    elif args.question == "brief" and args.read:
        code, said = read_brief(manifest, args.manifest, args.project, args.id,
                                args.role, args.slice)
        if code == E_OK:
            write_exact(sys.stdout, said)
        else:
            sys.stderr.write("audit-lookup.py: %s\n" % (said,))
        return code
    elif args.question == "brief" and args.role:
        code, said = write_brief(manifest, args.manifest, args.project, args.id,
                                 args.role)
        # MEASURED, NEVER GATED: this brief is a per-run artifact, not the
        # agent's static prompt `tools/measure-context.py --gate`'s
        # `AGENT_CEILINGS` bounds - printed so a brief that grew (a phase
        # brief's embedded diffs are the usual reason) is visible before it is
        # spent on a request, with no ceiling enforced here. Printed on
        # STDERR in the human form: stdout's "written: <path>" line is a
        # contract `drive-phase.py` parses with `written: (.+)$` to find the
        # path, and a size appended there would feed it a path that is not one.
        size = None
        if code == E_OK:
            try:
                size = os.path.getsize(said)
            except OSError:
                size = None
        if args.as_json:
            payload = {"ok": code == E_OK, "id": args.id, "role": args.role,
                      "written" if code == E_OK else "message": said}
            if size is not None:
                payload["bytes"] = size
            print(json.dumps(payload, indent=2, sort_keys=True))
        elif code == E_OK:
            print("brief for %s (%s) written: %s" % (args.id, args.role, said))
            if size is not None:
                sys.stderr.write("audit-lookup.py: %s is %d bytes\n"
                                 % (said, size))
        else:
            sys.stderr.write("audit-lookup.py: %s\n" % (said,))
        return code
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
    # `--read` prints a record through `write_exact`, and only reaches stdout's
    # buffer when `terse_cli` does not hold it: a held one is printed again
    # through the text layer, which on Windows writes a CRLF the brief carries
    # as CR CR LF. So it is a long-form flag, run unheld.
    sys.exit(_output.terse_cli(main, sys.argv[1:], success_line,
                               long_form=("--read",)))
