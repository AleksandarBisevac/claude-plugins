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

A MATCH THAT FINDS NOTHING SAYS SO. `cancel` on an id this manifest does not have
at all, `bug` on an id not in `bugs[]`, `file` on a path `fileIndex` never
recorded, `brief` on a task id this manifest does not have (or that names a
phase, since `files` is a task field): all four exit non-zero with the plain
sentence that nothing was found, never a nearest guess dressed as an answer. An
id that DOES exist but was never cancelled is a different, legitimate answer -
not a miss - and says so too; so is a task `brief` finds that simply declares
no files yet.

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

import _manifest_io as _mio  # noqa: E402  (layer 1: the loader, the id indexes)
import _journal_io  # noqa: E402  (layer 1: the trail this cross-checks against)
import _evidence_io as _evio  # noqa: E402  (layer 2: project/config resolution)

E_OK = 0
E_NOMATCH = 1
E_USAGE = 2


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
        return True, {"id": node_id, "kind": kind, "cancelled": False,
                      "status": status,
                      "pointer": "%s.status in the manifest" % (node_id,)}
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
    than a synthesised one."""
    bugs = manifest.get("bugs") or []
    for i, bug in enumerate(bugs):
        if isinstance(bug, dict) and bug.get("id") == bug_id:
            return True, {"id": bug_id, "status": bug.get("status"),
                          "notes": bug.get("notes"),
                          "fixedIn": bug.get("fixedIn"),
                          "taskId": bug.get("taskId"),
                          "pointer": "bugs[%d] in the manifest" % (i,)}
    return False, "no bug %r in this manifest" % (bug_id,)


def file_lookup(manifest, path):
    """`(found, payload_or_message)` for "which task last touched `path`".

    EXACT KEY MATCH ONLY. `fileIndex` is a lookup because the plugin already
    maintains it as one - `path` must be spelled exactly as a task's `files`
    entry (and therefore the index key) spells it, project-dir-relative. A
    path this manifest never declared returns `found=False`; there is no
    nearest-match fallback, because a lookup that guessed at a similar path
    would be a search wearing a lookup's name."""
    fidx = manifest.get("fileIndex")
    declaring = fidx.get(path) if isinstance(fidx, dict) else None
    if not declaring:
        return False, "no task declares %r in fileIndex" % (path,)
    last = declaring[-1]
    task = _mio.tasks_by_id(manifest).get(last)
    return True, {"path": path, "declaringTasks": list(declaring), "last": last,
                  "lastStatus": task.get("status") if task else None,
                  "pointer": "fileIndex[%r][-1] of %d entries in the manifest"
                            % (path, len(declaring))}


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


# --- cli --------------------------------------------------------------------------
def _render_human(question, node_id, found, payload):
    if not found:
        return ["no match: %s" % (payload,)]
    if question == "cancel":
        if not payload["cancelled"]:
            return ["%s is not cancelled (status: %s)"
                   % (node_id, payload["status"])]
        lines = ["%s was cancelled: %s" % (node_id, payload["reasonText"]),
                "pointer: %s" % (payload["pointer"],)]
        if "journal" in payload:
            lines.append("journal: %s (%s)"
                         % (payload["journal"]["pointer"], payload["journal"]["ts"]))
        return lines
    if question == "bug":
        return ["%s: status=%s notes=%s fixedIn=%s"
               % (node_id, payload["status"], payload["notes"] or "(none)",
                  payload["fixedIn"] or "(none)"),
               "pointer: %s" % (payload["pointer"],)]
    if question == "brief":
        if not payload["files"]:
            return ["%s declares no files yet" % (node_id,)]
        lines = ["%s declares %d file(s):" % (node_id, len(payload["files"]))]
        for entry in payload["files"]:
            if entry["last"] is None:
                lines.append("  %s: not in fileIndex yet" % (entry["path"],))
            else:
                lines.append("  %s: last declared by %s (status: %s)"
                             % (entry["path"], entry["last"], entry["lastStatus"]))
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
             "one call, for a spawn prompt, instead of one `file` call per path")
    brief_p.add_argument("id")
    return p


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
    sys.exit(main(sys.argv[1:]))
