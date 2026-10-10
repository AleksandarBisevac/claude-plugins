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
    audit-lookup.py <manifest> brief <taskId>  --role executor|reviewer
    audit-lookup.py <manifest> brief <phaseId> --role phase
The reviewer's brief carries the executor's return AS FILED, so it is REFUSED
(exit `E_REFUSED`, nothing written) until that return is filed for the task's
current start; the phase reviewer's brief is refused while any task of the phase
has no commit yet, because the binding it asks for would have no diff.

READ-ONLY OVER THE RECORD. This never writes the manifest, the ledger or the
journal; the one file it writes is a brief, under `stateDir`.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_audit_lookup.py` - see `plugins/audit/tests/_harness.py`.
"""
import argparse
import json
import os
import pathlib
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
import _manifest_io as _mio  # noqa: E402  (layer 1: the loader, the id indexes)
import _manifest_vocab as _vocab  # noqa: E402  (layer 1: `_strip_line_suffix`, the one
#                                             reading of a `files` entry's range suffix)
import _manifest_phases as _phases  # noqa: E402  (own_gate_entries: the entries
#                                               `run-test-gate --own` runs)
import _journal_io  # noqa: E402  (layer 1: the trail this cross-checks against)
import _evidence_io as _evio  # noqa: E402  (layer 2: project/config resolution)
import _loader  # noqa: E402  (the one way scripts/ loads hooks/_config as a library)
import _areas  # noqa: E402  (resolve_skills: area skills first, then the task's)
import _filed_returns as _fr  # noqa: E402  (where `submit` filed a return, and
#                                            which tasks a phase review owes)
import _config_rules  # noqa: E402  (review_per_task_mode: the config's reading now)

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
BRIEF_ROLES = ("executor", "reviewer", "phase")
BRIEFS_DIRNAME = "briefs"

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


def _verbatim(text, absent):
    return [text] if isinstance(text, str) and text.strip() else [absent]


def wave_tree_lines(ctx, phase, task):
    """The lines that tell a wave member where it works: its own tree, the
    commit the tree was cut at, and the rules that follow from it. Read from the
    driver's state, where `add_tree` records the tree; a task with no tree there
    - width 1, or a phase not driven in waves - gets no line at all."""
    body, _problem = _fr.drive_state(ctx["state"], str(phase.get("id")))
    wave = body.get("wave") if isinstance(body.get("wave"), dict) else {}
    trees = wave.get("trees") if isinstance(wave.get("trees"), dict) else {}
    tree = trees.get(str(task.get("id")))
    if not isinstance(tree, str) or not tree:
        return []
    return ["tree: %s" % (tree,),
            "base: %s" % (wave.get("base"),),
            "You work in this tree, not the project's. Begin every command "
            "with `cd %s &&`, and edit only files under it." % (tree,),
            "Never commit there: the driver carries your bytes into the phase "
            "tree, and the orchestrator commits."]


def compose_executor_brief(manifest, phase, task, ctx, files, gate):
    """The executor's whole brief, as lines. `files` is `brief_lookup`'s payload
    and `gate` the `executor.runsGate` reading with its basis."""
    tid, pid = str(task.get("id")), str(phase.get("id"))
    attempts = task.get("attempts") or 0
    lines = ["# Brief for %s (executor)" % (tid,), "",
             "Computed by audit-lookup.py brief from %s at %s, plugin copy %s."
             % (ctx["manifest"], ctx["at"], ctx["plugin"]),
             "Task %s %r, attempt %s, started %s; phase %s %r."
             % (tid, task.get("title"), attempts, task.get("startedAt"), pid,
                phase.get("title")),
             "The rules and the return shape are agents/audit-executor.md's."]
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
        + ["gate, %s:" % (whose,)] + gate_lines(manifest, entries))
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
        outcome = task.get("outcome") or {}
        evidence = task.get("testEvidence") or {}
        lines += _section("Retry - what attempt %d left on the record"
                          % (attempts - 1,), [
            "outcome.technical (verbatim):",
            outcome.get("technical") or "none recorded",
            "testEvidence: runId %s, status %s, at %s"
            % (evidence.get("runId"), evidence.get("status"),
               evidence.get("at")) if evidence else
            "testEvidence: none recorded",
            "redFirst: %s" % (json.dumps(task.get("redFirst"), sort_keys=True)
                              if task.get("redFirst") else "none recorded"),
            "The working tree is the last attempt; this is what it answered."])
    lines += _section("Your return", executor_return_lines(
        manifest, phase, task, ctx))
    return lines


def red_command(manifest, phase, task):
    """The resolved gate command that names one of the task's `tests.add`
    files, or None: the command `submit` hands the red-first helper. Only a
    command naming the file is taken; a whole-project gate is a red the helper
    would grade against every test HEAD carries."""
    added = [str(a).split(":", 1)[0].strip()
             for a in ((task.get("tests") or {}).get("add") or [])
             if isinstance(a, str) and a.strip()]
    entries, _whose = _task_gate(manifest, phase, task)
    for _entry, cmd in _evio.resolved_commands(manifest, entries):
        if isinstance(cmd, str) and any(f and f in cmd for f in added):
            return cmd
    return None


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


def submit_command(ctx, node_id, role, tail=""):
    """The resolved `drive-phase.py submit` an agent's last act runs, as a
    fenced block carrying the return on stdin in a quoted heredoc."""
    return "\n".join([
        "```sh",
        "%s submit %s --role %s %s --project-dir %s%s <<'%s'" % (
            _script(ctx, "governance/drive-phase.py"), node_id, role,
            ctx["manifest"], ctx["project"], tail, RETURN_DELIMITER),
        "<the return object, as JSON>",
        RETURN_DELIMITER,
        "```"])


def executor_return_lines(manifest, phase, task, ctx):
    """The executor's filing: one `submit`, which checks the shape, runs the
    red-first helper when a test command follows `--`, takes the stamp and
    files the return once. A tdd task owes the command; it is printed resolved
    when a gate entry names a `tests.add` file, and asked for when none does."""
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
    return (["Your last act files the return object agents/audit-executor.md "
             "declares - it checks the shape, runs the red-first helper on the "
             "command after `--`, takes the stamp and files the return once. %s:"
             % (RETURN_ON_STDIN,), submit_command(ctx, tid, "executor", tail)]
            + note)


def _diff_lines(ctx, files):
    """The working tree's change to `files`, read from git, or why it is not."""
    paths = [_vocab._strip_line_suffix(f) for f in files or []
             if isinstance(f, str)]
    command = "git diff HEAD -- %s" % (" ".join(paths),)
    try:
        done = subprocess.run(["git", "-C", ctx["gitRoot"], "diff", "HEAD", "--"]
                              + paths, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=60)
        untracked = subprocess.run(
            ["git", "-C", ctx["gitRoot"], "ls-files", "--others",
             "--exclude-standard", "--"] + paths,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return ["`%s` could not be run here (%s); run it yourself." % (command, exc)]
    if done.returncode != 0:
        return ["`%s` exited %d here (%s); run it yourself."
                % (command, done.returncode,
                   done.stderr.decode("utf-8", "replace").strip()[:200])]
    lines = ["`%s`:" % (command,), "```diff",
             done.stdout.decode("utf-8", "replace").rstrip("\n") or "(empty)",
             "```"]
    new = untracked.stdout.decode("utf-8", "replace").split()
    if new:
        lines.append("Untracked declared files, which the diff above does not "
                     "show - read them whole: %s" % (", ".join(new),))
    return lines


def compose_reviewer_brief(manifest, phase, task, ctx, filed):
    """The task-mode reviewer's whole brief, as lines. `filed` is the
    executor's `(rel, text)` for the current start, text present."""
    tid = str(task.get("id"))
    entries, whose = _task_gate(manifest, phase, task)
    evidence = task.get("testEvidence") or {}
    lines = ["# Brief for %s (reviewer, mode: task)" % (tid,), "",
             "Computed by audit-lookup.py brief from %s at %s, plugin copy %s."
             % (ctx["manifest"], ctx["at"], ctx["plugin"]),
             "The rules and the return shape are agents/audit-reviewer.md's."]
    lines += _section("Description (verbatim)",
                      _verbatim(task.get("description"),
                                "The task records no description."))
    lines += _section("Phase desired outcome",
                      _verbatim(phase.get("desiredOutcome"),
                                "The phase records no desiredOutcome."))
    lines += _section("The executor's return, as filed (%s)" % (filed[0],),
                      [filed[1]])
    lines += _section("The recorded gate run", [
        "runId %s, status %s, at %s (task.testEvidence)"
        % (evidence.get("runId"), evidence.get("status"), evidence.get("at"))
        if evidence else "No run is recorded for this task (no "
        "task.testEvidence) - read that as absent, not as passed."])
    lines += _section("Gate commands, %s" % (whose,),
                      gate_lines(manifest, entries))
    lines += _section("The diff", _diff_lines(ctx, task.get("files")))
    lines += _section("Your return", [
        "File the return object agents/audit-reviewer.md declares - your one "
        "write. %s:" % (RETURN_ON_STDIN,),
        submit_command(ctx, tid, "reviewer")])
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
            done.returncode, done.stderr.decode("utf-8", "replace").strip()[:160]))
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
    try:
        done = subprocess.run(["git", "-C", ctx["gitRoot"], "-c",
                               "core.quotepath=off", "diff", "--no-renames",
                               "--diff-filter=M", "--name-only", base, head],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return ["Not computed: `%s` could not be run here (%s)." % (command, exc)]
    if done.returncode != 0:
        return ["Not computed: `%s` exited %d (%s)." % (
            command, done.returncode,
            done.stderr.decode("utf-8", "replace").strip()[:200])]
    paths = [p for p in done.stdout.decode("utf-8", "replace").splitlines()
             if _fr.is_test_path(p)]
    return (["`%s`, test paths only; a test file the phase added is not listed. "
             "Read each change against the task whose diff holds it:" % (command,)]
            + (["- %s" % (p,) for p in paths] or ["None."]))


def _review_owed(ctx, phase):
    """`(live, answered, problem)` - the config's `review.perTask` now (read only
    where a task with a commit records no key), and the commits filed phase
    returns already answer."""
    live, problem = None, None
    if any(t.get("commit") and _fr.review_key(t, phase, None)[1] == "config"
           for t in phase.get("tasks") or [] if isinstance(t, dict)):
        live, problem = _config_rules.review_per_task_mode(ctx["config"])
    filed = _fr.phase_returns(ctx["evidence"], str(phase.get("id")))
    unread = [why for _rel, _body, why in filed if why]
    return live, _fr.answered_entries(filed), problem or (
        "; ".join(unread) if unread else None)


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


def compose_phase_brief(manifest, phase, ctx):
    """The sign-off reviewer's whole brief, as lines: the request as saved and
    the choices it left open, the fixed question, every task with a diff on its
    own record, and under `review.perTask: phase` the tasks owed their three
    answers, the head this brief was computed at and the filing command keyed
    on it."""
    pid = str(phase.get("id"))
    head, head_why = _head(ctx)
    live, answered, owed_why = _review_owed(ctx, phase)
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
    lines += _section("Phase desired outcome",
                      _verbatim(phase.get("desiredOutcome"),
                                "The phase records no desiredOutcome."))
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
    for task in listed:
        tid = str(task.get("id"))
        entries, whose = _task_gate(manifest, phase, task)
        evidence = task.get("testEvidence") or {}
        rel, text = filed_return(ctx, task, "executor")
        answers, owed_by = mechanical.get(tid, ({}, {}))
        computed = answer_lines(answers, owed_by) if (
            not owed_why and _fr.owed_answer(task, phase, live, answered)) else []
        lines += _section("%s %s" % (tid, task.get("title") or ""), [
            "commit: %s" % (task.get("commit"),),
            "diff: git show %s -- %s"
            % (task.get("commit"), " ".join(str(f) for f in task.get("files")
                                            or [])),
            "files:"] + ["- %s" % (f,) for f in task.get("files") or []] + [
            "description (verbatim):",
            task.get("description") or "none recorded",
            _recorded_run_line(evidence, rows, rows_why),
            "gate commands, %s:" % (whose,)] + gate_lines(manifest, entries)
            + ["executor return (%s):" % (rel,),
               text if text is not None else
               "none filed for its current start",
               _owed_line(task, phase, live, answered)] + computed)
    lines += _section("Existing test files the phase modifies",
                      existing_test_lines(ctx, phase, head))
    if skipped:
        lines += _section("Tasks with no diff", [
            "Closed with no commit (a no-change close) or cancelled, so there "
            "is no diff to review: %s" % (", ".join(skipped),)])
    owed = [str(t.get("id")) for t in listed
            if _fr.owed_answer(t, phase, live, answered)]
    if owed_why:
        lines += _section("Review answers owed per task", [
            "Which tasks are owed their answers could not be read: %s. Sign-off "
            "and its filing refuse until it can." % (owed_why,)])
        return lines
    file_cmd = submit_command(ctx, pid, "reviewer",
                              " --head %s" % (head or "<head>",))
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


def brief_file(ctx, node_id, role, started_at=None):
    """Where a brief is written: under `stateDir`, keyed by the start a task
    brief belongs to, so a retry's brief never reads as the first one's."""
    name = ("phase.md" if role == "phase" else
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
    if role == "phase":
        held = phase_brief_refusal(phase)
        if held:
            return E_REFUSED, (
                "REFUSED: %s has task(s) with no commit yet (%s) - the phase "
                "review binds each task's answers to its commit, and those would "
                "have no diff. Close them first. No brief written."
                % (node_id, ", ".join(held)))
        lines = compose_phase_brief(manifest, phase, ctx)
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
    else:
        ok, gate = runs_gate_reading(ctx["project"], ctx["hc"])
        if not ok:
            return E_CONFIG, gate
        _found, files = brief_lookup(manifest, node_id)
        lines = compose_executor_brief(manifest, phase, task, ctx, files, gate)
    path = brief_file(ctx, node_id, role, (task or {}).get("startedAt"))
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError as exc:
        return E_USAGE, "the brief could not be written to %s (%s)" % (path, exc)
    return E_OK, path


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
    elif args.question == "brief" and args.role:
        code, said = write_brief(manifest, args.manifest, args.project, args.id,
                                 args.role)
        if args.as_json:
            print(json.dumps({"ok": code == E_OK, "id": args.id,
                              "role": args.role,
                              "written" if code == E_OK else "message": said},
                             indent=2, sort_keys=True))
        elif code == E_OK:
            print("brief for %s (%s) written: %s" % (args.id, args.role, said))
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
    from _output import safe_stdio, selftest_requested  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if selftest_requested(sys.argv[1:]):
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
