#!/usr/bin/env python3
"""
The door `/audit:sync` knocks on to find out who moved a linked work item last.

`_ado_drift` holds the rule; this turns it into a command, for the same two reasons
`check-ado-item.py` is a command: a `python3 -c` one-liner naming a source path is
exactly the shape `guard-secrets-read` refuses (F20/F22), so the check would be off
on the machines that most need it — and prose cannot be tested.

WHY THIS IS NOT A GATE. `check-ado-item.py` exits 1 to mean "do not create this
item": a refusal. There is no refusal here. "Somebody else moved this card" is
often perfectly fine — on a board with several teams it is the normal case — so a
non-zero exit would label a healthy state an error, and the first thing anyone
would do is stop reading it. The exit code says whether the QUESTION could be
answered, never what the answer was:

  0 - answered (rows printed; read them, or --json them)
  2 - usage error, or input that could not be read

The caller keeps its existing consent gate. This only makes sure the gate is asked
with the truth in hand: which updates would overwrite a change made after our last
sync, and which cards were not ours to begin with.

Usage:
  explain-ado-drift.py <manifest> --items <file.json>
  explain-ado-drift.py <manifest> --items -              # payload on stdin
  explain-ado-drift.py <manifest> --items f.json --json
  explain-ado-drift.py <manifest> --items f.json --tolerance 600

The payload is what the command already fetched for its diff:

  [{"id": 5120,
    "fields": {"System.State": "Closed",
               "System.ChangedBy": {"displayName": "Ana Kovac"},
               "System.ChangedDate": "2026-08-21T19:40:00Z"},
    "mapped": "Active"}]

`mapped` is optional and is the manifest status already translated through
`meta.ado.stateMap` — `commands/sync.md` owns that table, and a second copy here
would be a second answer. Omit it and each row says the state comparison was not
supplied rather than implying the item is in sync.

THE MANIFEST IS READ THROUGH `_manifest_io.load_manifest`, NEVER WITH A BARE
`json.load`. Both storage layouts are current — `layout` is a CHOICE, not a version
— and on the SHARDED one the file at `<manifest>` is an INDEX whose phases are
stubs: the tasks, and every `ado` link on them, live in the phase shards beside it.
A raw read therefore hands `_ado_drift.join()` a manifest with no tasks in it, and
the join has no way to tell that from a manifest whose tasks are genuinely
unlinked — so every shard-held link comes back as `NOT IN MANIFEST`, which is a
confident wrong answer about somebody's board and the exact failure this command
exists to prevent. It was that, on a real board, until the loader was wired in
here; the loader is where the two layouts are made to read the same, and going
around it is how a consumer stops being layout-agnostic without anything saying so.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_explain_ado_drift.py`.
"""
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

import _ado_drift as _drift  # noqa: E402  (the rule this command carries)
import _manifest_io as _mio  # noqa: E402  (the loader that assembles both layouts)

USAGE = ("usage: explain-ado-drift.py <manifest> --items <file.json|-> "
         "[--json] [--tolerance <seconds>]\n")

HEAD = ("kind", "manifest", "ado", "state (mapped -> ado)", "verdict")

ORIGIN_WORDS = {_drift.ORIGIN_CREATED: "created here",
                _drift.ORIGIN_IMPORTED: "imported from ADO",
                _drift.UNKNOWN: "origin unknown"}


def _read_json(path, what):
    """(value, error). Reads `-` from stdin, like check-ado-item.py does.

    THE `--items` PAYLOAD, AND NOTHING ELSE. That payload is one JSON document the
    caller just wrote, so a plain parse is the whole job. The manifest is not that
    shape — it may be an index with its phases on disk beside it — and reading it
    here is the bug this file was fixed for; `_read_manifest` below is its door.
    """
    try:
        if path == "-":
            return (json.load(sys.stdin), None)
        with open(path, "r", encoding="utf-8") as fh:
            return (json.load(fh), None)
    except Exception as exc:
        return (None, "cannot read/parse %s %s: %s" % (what, path, exc))


def _read_manifest(path):
    """(assembled manifest, error). The SHARD WALK, which `_read_json` cannot do.

    Same `(value, error)` shape and same message prefix as `_read_json` above, so
    the caller's exit-2 branch is unchanged — but the value is the ASSEMBLED
    manifest, which on the sharded layout means the phase bodies have been read
    off disk and merged into their index stubs.

    A shard that will not open raises here and reaches the operator as a refusal
    naming THAT file (the path travels in the exception), not as a drift table
    missing a phase. The alternative — skipping the unreadable shard and joining
    what is left — would report every link it held as `NOT IN MANIFEST`, which is
    the same wrong answer as the raw read, arrived at one layer down.
    """
    try:
        return (_mio.load_manifest(path), None)
    except Exception as exc:
        return (None, "cannot read/parse manifest %s: %s" % (path, exc))


def _state_cell(row):
    """`Active -> Closed`, or the ADO state alone when nothing was mapped."""
    if row.get("mapped") is None:
        return "? -> %s" % (row.get("adoState") or "?",)
    return "%s -> %s" % (row["mapped"], row.get("adoState") or "?")


def table(rows):
    """The rows as aligned lines, header first. Empty in, empty out."""
    if not rows:
        return []
    body = [(r.get("kind") or "?", str(r.get("id") or "?"),
             "#%s" % (r.get("adoId"),), _state_cell(r),
             "%s [%s]" % (r.get("verdict") or "?",
                          ORIGIN_WORDS.get((r.get("origin") or {}).get("origin"),
                                           "origin unknown")))
            for r in rows]
    widths = [max(len(HEAD[i]), max(len(line[i]) for line in body))
              for i in range(len(HEAD))]
    fmt = "  ".join("%-" + str(w) + "s" for w in widths)
    return [(fmt % HEAD).rstrip(), (fmt % tuple("-" * w for w in widths)).rstrip()] \
        + [(fmt % line).rstrip() for line in body]


def summary_lines(result):
    """The lines a confirm gate needs, and never a number without its subject."""
    counts = _drift.summarize(result)
    origins = result.get("origins") or {}
    out = []
    out.append("%d fetched item(s) matched a manifest link (tolerance %ds)"
               % (counts["total"], result.get("tolerance") or 0))
    # The number the confirm gate exists for. Said even when it is zero: "none of
    # these would overwrite anyone" is an answer the operator wants in hand, and a
    # line that appears only on bad news reads as absent-because-fine either way.
    out.append("%d would overwrite a change made after our last sync"
               % (counts["external"],))
    out.append("%d ours to push, %d already in sync, %d unknown (no basis), "
               "%d state not compared"
               % (counts["localAhead"], counts["inSync"], counts["unknown"],
                  counts["uncompared"]))
    out.append("origins: %d created here, %d imported, %d unknown "
               "(links written before origin existed)"
               % (origins.get(_drift.ORIGIN_CREATED, 0),
                  origins.get(_drift.ORIGIN_IMPORTED, 0),
                  origins.get(_drift.UNKNOWN, 0)))
    for item in (result.get("unlinked") or []):
        out.append("NOT IN MANIFEST: #%s - %s" % (item.get("adoId"),
                                                  item.get("why")))
    # Named rather than counted-and-dropped: "we did not look at it" and "it is
    # fine" are different answers, and a table of the fetched half reads as both.
    for item in (result.get("unfetched") or []):
        out.append("NOT FETCHED: %s %s -> #%s - nothing is claimed about it"
                   % (item.get("kind"), item.get("id"), item.get("adoId")))
    return out


def advice_lines(result):
    """What to do, per row that has a basis for an answer."""
    out = []
    for row in (result.get("rows") or []):
        what = row.get("advice")
        if what:
            out.append("%s %s (#%s): %s" % (row.get("kind"), row.get("id"),
                                            row.get("adoId"), what))
    return out


def main(argv):
    if not argv or argv[0].startswith("-") or "--items" not in argv:
        sys.stderr.write(USAGE)
        return 2
    manifest_path = argv[0]
    idx = argv.index("--items")
    items_path = argv[idx + 1] if len(argv) > idx + 1 else None
    if not items_path or items_path.startswith("--"):
        sys.stderr.write(USAGE)
        return 2

    tolerance = _drift.DEFAULT_TOLERANCE_S
    if "--tolerance" in argv:
        tidx = argv.index("--tolerance")
        raw = argv[tidx + 1] if len(argv) > tidx + 1 else ""
        try:
            tolerance = int(raw)
        except ValueError:
            sys.stderr.write("ERROR: --tolerance wants whole seconds, got %r\n"
                             % (raw,))
            return 2
        if tolerance < 0:
            sys.stderr.write("ERROR: --tolerance cannot be negative (%d)\n"
                             % (tolerance,))
            return 2

    manifest, err = _read_manifest(manifest_path)
    if err:
        sys.stderr.write("ERROR: %s\n" % (err,))
        return 2
    items, err = _read_json(items_path, "items")
    if err:
        sys.stderr.write("ERROR: %s\n" % (err,))
        return 2

    # Shape before substance, and exit 2 rather than an empty table: a list is the
    # documented payload, and answering "no drift" about something we could not
    # read is the confident-wrong-answer this command exists to avoid.
    if not isinstance(items, list):
        sys.stderr.write("ERROR: --items wants a JSON list of "
                         "{id, fields[, mapped]}, got %s\n"
                         % (type(items).__name__,))
        return 2
    if not isinstance(manifest, dict):
        sys.stderr.write("ERROR: manifest %s is not a JSON object\n"
                         % (manifest_path,))
        return 2

    result = _drift.join(manifest, items, tolerance=tolerance)

    if "--json" in argv:
        print(json.dumps({"result": result, "summary": _drift.summarize(result)},
                         indent=2, sort_keys=True))
        return 0

    for line in table(result["rows"]):
        print(line)
    if result["rows"]:
        print("")
    for line in summary_lines(result):
        print(line)
    advice = advice_lines(result)
    if advice:
        print("")
        for line in advice:
            print(line)
    return 0


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to a usage error, which would read
        # as a broken flag rather than as a moved suite. It deliberately does NOT
        # print the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("explain-ado-drift.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_explain_ado_drift.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
