#!/usr/bin/env python3
"""
Read off the tree is a first guess. Read off the ledger is a fact, if there is one.

`/audit:init`'s recon drafts `meta.buildCommands` from what the tree LOOKS like a
project can run - a real strength for a repository with no history, and a waste of
one everywhere else. The evidence ledger already carries every gate command that
ran, whether it passed, and how many times - `_evidence_io.command_tally` is the
whole answer, once a candidate command is in hand.

    propose-gates.py <manifest> --command "npm test" [--command "npm run lint" ...]
    propose-gates.py <manifest> --command "npm test" --project DIR --json

THE FAILURE MODE THIS IS WRITTEN AGAINST IS THE CONFIDENT ONE. A repository with
no recorded run must propose from the tree and SAY that is what it did - a
proposal presented as learned when it was guessed is worse than a guess presented
as one. So every entry below carries a `basis` ("tree" when nothing has ever run
under that exact command, "history" when something has) and a `claim`:

  tree           no recorded runs at all - the candidate is a first guess
  insufficient   history exists but is thinner than the floor below supports a
                 verdict from - noted, never rounded up into one
  never-failed   ran at or past the floor and has not failed once - a candidate
                 FOR REMOVAL, because a gate that never catches anything is a
                 gate a plan is paying for without ever being told why
  catches-things a candidate FOR EVERY PLAN - it has failed before, which is the
                 one thing a tree read can never say

NEVER A NUMBER WRITTEN HERE. `ranTotal`/`failed` are computed at the moment this
runs, from `_evidence_io.read_rows`, and printed - not typed into this docstring,
which is exactly the claim `_output.prose_number_claims()` exists to catch.

READ-ONLY. This never writes the manifest, the ledger or the journal; it is a
question `/audit:init`'s recon step asks before drafting `meta.buildCommands`,
not a step that mutates anything a validator would need to re-check.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_propose_gates.py` - see `plugins/audit/tests/_harness.py`.
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

import _evidence_io as _evio  # noqa: E402  (layer 2: the ledger, and the tally)

E_OK = 0
E_USAGE = 2


def classify(rows, command, floor=None):
    """One candidate command, folded into a claim with the basis that makes it.

    `floor` defaults to `_evidence_io.MIN_HISTORY_RUNS` - a caller in a case can
    still lower it to exercise the boundary without waiting for real history to
    accumulate that many runs.

    FOUR CLAIMS, NEVER A FIFTH BLENDED FROM TWO OF THEM: `tree` (nothing has run
    under this exact spelling), `insufficient` (something has, below the floor -
    reported honestly rather than rounded up either direction), `never-failed`
    (at or past the floor, no failure) and `catches-things` (at or past the
    floor, has failed). A caller that wants the raw counts alongside the claim
    always has them - `ranTotal`/`failed` are on every entry regardless of which
    claim it drew."""
    floor = _evio.MIN_HISTORY_RUNS if floor is None else floor
    ran, failed = _evio.command_tally(rows, command)
    if ran == 0:
        return {"command": command, "basis": "tree", "ranTotal": 0, "failed": 0,
                "claim": "tree",
                "note": "no recorded runs for this command; proposed from the "
                        "tree alone"}
    if ran < floor:
        return {"command": command, "basis": "history", "ranTotal": ran,
                "failed": failed, "claim": "insufficient",
                "note": "history exists but is thinner than the floor a verdict "
                        "needs; proposed from the tree, with what little history "
                        "there is noted rather than rounded up"}
    if failed == 0:
        return {"command": command, "basis": "history", "ranTotal": ran,
                "failed": failed, "claim": "never-failed",
                "note": "never failed across every recorded run; a candidate "
                        "for removal"}
    return {"command": command, "basis": "history", "ranTotal": ran,
            "failed": failed, "claim": "catches-things",
            "note": "has failed before; a candidate for every plan"}


def propose(manifest_path, commands, project_dir=None):
    """`{"manifestPath", "evidenceDir", "historyAvailable", "entries"}` for every
    candidate in `commands`, in the order given.

    `historyAvailable` is the repo-wide answer the confident failure mode needs:
    False means not one row exists anywhere in this manifest's ledger, so every
    entry below is `basis: "tree"` regardless of what it claims about itself -
    stated once here rather than left for a reader to infer from re-scanning
    every entry's own basis."""
    project, config = _evio.project_config_for(manifest_path, project_dir)
    read = _evio.read_rows(project, config)
    rows = read.get("rows") or []
    entries = [classify(rows, c) for c in commands]
    return {"manifestPath": manifest_path,
            "evidenceDir": _evio.evidence_dir(project, config),
            "historyAvailable": bool(rows),
            "entries": entries}


def render_human(result):
    """The human render: one line per candidate, the repo-wide note first when
    it changes what every line below means."""
    out = []
    if not result["historyAvailable"]:
        out.append("no evidence recorded for %s yet (%s) - every entry below is "
                   "a first guess from the tree"
                   % (result["manifestPath"], result["evidenceDir"]))
    for entry in result["entries"]:
        if entry["basis"] == "tree":
            out.append("%s: tree only - %s" % (entry["command"], entry["note"]))
        else:
            out.append("%s: history, ran %d, failed %d -> %s"
                       % (entry["command"], entry["ranTotal"], entry["failed"],
                          entry["note"]))
    return out


def build_parser():
    p = argparse.ArgumentParser(
        prog="propose-gates.py", add_help=True, allow_abbrev=False,
        description="Propose gate entries from evidence history where there is "
                    "some, and say so when there is none.")
    p.add_argument("manifest", help="path to the audit manifest being drafted "
                                    "or already in place")
    p.add_argument("--command", dest="commands", action="append", default=[],
                   metavar="CMD",
                   help="a candidate gate command (repeatable); matched "
                        "verbatim against recorded evidence")
    p.add_argument("--project", dest="project", default=None, metavar="DIR",
                   help="project root (default: CLAUDE_PROJECT_DIR, else the "
                        "manifest's own directory)")
    p.add_argument("--json", action="store_true", dest="as_json",
                   help="print the result as JSON instead of the human render")
    return p


def main(argv):
    args = build_parser().parse_args(argv)
    if not args.commands:
        sys.stderr.write("propose-gates.py: at least one --command is required\n")
        return E_USAGE
    try:
        result = propose(args.manifest, args.commands, project_dir=args.project)
    except Exception as exc:
        sys.stderr.write("propose-gates.py: could not read the evidence ledger: "
                         "%s\n" % (exc,))
        return E_USAGE
    if args.as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for line in render_human(result):
            print(line)
    return E_OK


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exiting silently: `--selftest` is what every other
        # file here accepts, so nothing would tell a reader whether this one ran
        # nothing or has nothing. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("propose-gates.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_propose_gates.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
