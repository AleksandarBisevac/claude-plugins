#!/usr/bin/env python3
"""
The door `/audit:sync` knocks on to read the linked side of a board in one go.

`_ado_fetch` holds the rule; this turns it into a command, for the same reason
`check-ado-item.py` and `explain-ado-drift.py` are commands: the caller is
orchestrator PROSE, which reaches Python only through Bash, and a `python3 -c`
one-liner naming a source path is exactly the shape `guard-secrets-read` refuses
(F20/F22) - so the thing would be off on the machines that most need it.

AND BECAUSE PROSE CANNOT BE TESTED, WHICH IS THE DEFECT THAT PRODUCED THIS FILE.
`sync.md` step 3 said "batch-fetch the ADO side" and then named `az boards
work-item show`, which takes a single `--id`. The instruction asked for a batch
and named a per-item command, so the implementation looped: 62 linked items,
eleven minutes, one CLI start-up each. A sentence cannot be held to a chunk size,
a field list or a time bound; a module can, and
`plugins/audit/tests/test_fetch_ado_items.py` holds it to all three.

WHY IT IS A GATE, UNLIKE `explain-ado-drift.py`. That command exits 0 whatever the
answer, because "somebody else moved this card" is the normal state of a shared
board. This one is different: "the board did not answer" is not a normal state, it
is a failure, and a payload missing the chunk that timed out reads downstream as a
clean board for exactly those items. So:

  0 - every chunk answered (the payload is complete for the ids asked for)
  1 - at least one chunk did NOT answer; the payload is PARTIAL and says which ids
      it has no news about. Do not diff or push from it.
  2 - usage error, or a manifest/`meta.ado` that could not be read

Usage:
  fetch-ado-items.py <manifest>
  fetch-ado-items.py <manifest> --json
  fetch-ado-items.py <manifest> --out fetched.json     # the --items payload
  fetch-ado-items.py <manifest> --dry-run              # the queries, no call
  fetch-ado-items.py <manifest> --chunk 50 --timeout 30

The payload written by `--out` is exactly what `explain-ado-drift.py --items`
reads, minus `mapped` - that field is the manifest status translated through
`meta.ado.stateMap`, `commands/sync.md` owns that table, and a second copy here
would be a second answer.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_fetch_ado_items.py`.
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

import _ado_fetch as _fetch  # noqa: E402  (the rule this command carries)
import _manifest_io as _mio  # noqa: E402  (the loader that assembles both layouts)

USAGE = ("usage: fetch-ado-items.py <manifest> [--json] [--out <file>] "
         "[--dry-run] [--chunk <n>] [--timeout <seconds>]\n")


def _whole_number(argv, flag, floor):
    """(value, error) for `--flag <n>`, or (None, None) when the flag is absent.

    Refused rather than silently defaulted: a chunk size or a bound nobody chose is
    a limit nobody can check, which is the class of defect this whole file exists
    for.
    """
    if flag not in argv:
        return (None, None)
    idx = argv.index(flag)
    raw = argv[idx + 1] if len(argv) > idx + 1 else ""
    try:
        value = int(raw)
    except ValueError:
        return (None, "%s wants a whole number, got %r" % (flag, raw))
    if value < floor:
        return (None, "%s cannot be below %d (got %d)" % (flag, floor, value))
    return (value, None)


def plan_lines(shape, timeout):
    """What WOULD be asked, before anything is asked. Never a number alone."""
    linked, total = shape["linkedOf"]
    out = []
    # Said even at zero, and said as a RATIO: "nothing to fetch" and "nothing is
    # linked" are the same words for very different boards, and a bare 0 reads as
    # the first while meaning the second.
    out.append("%d of %d manifest item(s) carry an ado link"
               % (linked, total))
    if not linked:
        out.append("nothing to fetch - no phase, task or bug in this manifest "
                   "has an ado.id")
        return out
    out.append("%d id(s) in %d quer%s (chunk limit %d, bound %ds per query)"
               % (linked, len(shape["chunks"]),
                  "y" if len(shape["chunks"]) == 1 else "ies",
                  shape["chunk"], timeout))
    out.append("org %s, project %s"
               % (shape["organization"] or "?", shape["project"] or "?"))
    for i, length in shape["oversized"]:
        out.append("REFUSED: query %d is %d characters, past the service's %d "
                   "(VS403309) - lower --chunk"
                   % (i + 1, length, _fetch.WIQL_MAX_CHARS))
    return out


def result_lines(result, timeout):
    """The answer, with every count carrying what it is a count OF."""
    out = plan_lines(result["plan"], timeout)
    asked = len(result["plan"]["ids"])
    if not asked:
        return out
    out.append("fetched %d of %d linked item(s)" % (len(result["items"]), asked))
    # Named, never counted-and-dropped: an id the board has no row for is a work
    # item deleted or moved out of the project, and that is a thing to say rather
    # than a row to quietly leave out of a table that then looks complete.
    for one in result["missing"]:
        out.append("NO ROW: #%s - asked for, nothing came back (deleted, or "
                   "moved out of this project)" % (one,))
    # The failure half. A partial answer must never print like a whole one, so the
    # ids with no news are listed rather than summarised.
    for bad in result["failures"]:
        out.append("ADO %s: %s" % (bad["status"].upper().replace("_", " "),
                                   bad["detail"]))
        out.append("  no news about: %s"
                   % (", ".join("#%s" % (i,) for i in bad["ids"]),))
    if result["failures"]:
        out.append("THE PAYLOAD IS PARTIAL - do not diff or push from it; the "
                   "items above were not read, and an absent row is not an "
                   "unchanged one")
    return out


def main(argv):
    if not argv or argv[0].startswith("-"):
        sys.stderr.write(USAGE)
        return 2
    manifest_path = argv[0]

    chunk, err = _whole_number(argv, "--chunk", 1)
    if err:
        sys.stderr.write("ERROR: %s\n" % (err,))
        return 2
    timeout, terr = _whole_number(argv, "--timeout", 1)
    if terr:
        sys.stderr.write("ERROR: %s\n" % (terr,))
        return 2
    chunk = _fetch.DEFAULT_CHUNK if chunk is None else chunk
    timeout = _fetch.DEFAULT_TIMEOUT_S if timeout is None else timeout

    out_path = None
    if "--out" in argv:
        idx = argv.index("--out")
        out_path = argv[idx + 1] if len(argv) > idx + 1 else None
        if not out_path or out_path.startswith("--"):
            sys.stderr.write(USAGE)
            return 2

    # The manifest goes through the LOADER, never a bare `json.load`: on the sharded
    # layout the tasks - and every `ado` link on them - live in the phase shards, so
    # a raw read would plan a fetch for the index's bugs alone and call it complete.
    try:
        manifest = _mio.load_manifest(manifest_path)
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse manifest %s: %s\n"
                         % (manifest_path, exc))
        return 2
    if not isinstance(manifest, dict):
        sys.stderr.write("ERROR: manifest %s is not a JSON object\n"
                         % (manifest_path,))
        return 2
    if not _fetch.ado_of(manifest):
        sys.stderr.write("ERROR: %s has no meta.ado - run `/audit:sync connect` "
                         "before reading a board\n" % (manifest_path,))
        return 2

    shape = _fetch.plan(manifest, chunk)
    if "--dry-run" in argv:
        if "--json" in argv:
            print(json.dumps({"plan": shape, "timeout": timeout}, indent=2,
                             sort_keys=True))
        else:
            for line in plan_lines(shape, timeout):
                print(line)
        # A chunk the service would refuse is a refusal even in a dry run: the whole
        # point of printing the plan is to find that out before spending the calls.
        return 1 if shape["oversized"] else 0

    result = _fetch.fetch(manifest, size=chunk, timeout=timeout)

    if out_path:
        try:
            _mio.atomic_write_json(out_path, result["items"])
        except Exception as exc:
            sys.stderr.write("ERROR: cannot write %s: %s\n" % (out_path, exc))
            return 2

    if "--json" in argv:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for line in result_lines(result, timeout):
            print(line)
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to a usage error, which would read
        # as a broken flag rather than as a moved suite. It deliberately does NOT
        # print the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("fetch-ado-items.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_fetch_ado_items.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
