#!/usr/bin/env python3
"""
The door onto `_invariants`: check one phase, or every phase that has started.

WHY THIS COMMAND EXISTS. `README.md` and `plugins/audit/README.md` split the
plugin's rules into two columns - what a hook or a script ENFORCES, and what the
model FOLLOWS from `reference/orchestrator.md`. The right-hand column's third
field names, per row, what would catch a breach after the fact: `post-hoc` where
the evidence already sits in git, the shard, the journal or the ledger; `nothing`
where it does not exist. When those tables were written no checker shipped, and
naming an unwritten script would have been the same defect the tables repair. This
is that script, and every `post-hoc` row it actually reads moves to the left
column.

It is a command rather than a helper for the reason `check-ado-item.py` is one:
the caller is orchestrator PROSE, which reaches Python only through Bash, and a
`python3 -c` one-liner naming a source path is the shape `guard-secrets-read`
refuses (F20/F22) - so the check would be off exactly where it matters.

Usage:
  verify-invariants.py <manifest> <phaseId> [--project DIR] [--json]
  verify-invariants.py <manifest> --all     [--project DIR] [--json]

Exit codes:
  0  answered - no breach found (gaps are printed and do not fail)
  1  at least one breach
  2  usage error, an unreadable manifest, or a phase id that is not there

WHY A GAP EXITS 0 AND A BREACH EXITS 1. They are different claims. A breach is
evidence that a rule was broken; a gap is the absence of evidence either way - a
deleted branch reflog, an unmetered repository, a manifest state no commit
preserved. Failing a build on a gap would fail it on every finished phase (the
sign-off deletes the branch), and within a day the gate would be switched off.
Printing the gap where the verdict goes is the honest half: `partial` and
`no-basis` are words in the output, never silence.

Nothing here mutates: no lock is taken, no file is written, and git is only read.
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

import _invariants  # noqa: E402  (the rule this command carries)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR shards)

USAGE = ("usage: verify-invariants.py <manifest> <phaseId|--all> "
         "[--project DIR] [--json]\n")

E_BREACH, E_USAGE = 1, 2

# The five verdicts, each with the sentence that says what it is claiming. Printed
# beside every check because a one-word verdict is the thing this whole command
# exists to stop shipping on its own.
VERDICT_HELP = {
    _invariants.CLEAN: "examined, nothing contradicted the rule",
    _invariants.BREACH: "the evidence contradicts the rule",
    _invariants.PARTIAL: "examined, nothing wrong, and some evidence is gone",
    _invariants.NO_BASIS: "NOTHING could be examined - not a pass",
    _invariants.NA: "the rule has no subject in this phase",
}


# The read side, spelled here because this command asks the same two questions
# `/audit:status --gate` does. NOT copies: `_invariants` owns both, and
# `tests/test_verify_invariants.py` pins each name to be that module's own object.
ledger_dir_for = _invariants.ledger_dir_for
git_root_for = _invariants.git_root_for


def render_phase(answer):
    """The lines for one phase: a verdict per check, then what it rests on."""
    lines = ["PHASE %s%s" % (answer["phaseId"],
                             " (branch %s)" % answer["branch"]
                             if answer.get("branch") else "")]
    width = max(len(name) for name in _invariants.CHECK_NAMES)
    for check in answer["checks"]:
        lines.append("  %-*s  %-15s %s" % (width, check["name"],
                                           check["verdict"],
                                           VERDICT_HELP.get(check["verdict"], "")))
        # The basis, on every check and not only on the failing ones. A reader who
        # can see WHY a clean verdict is clean can tell it from a check that was
        # never wired up; one who cannot has to trust the word.
        lines.append("      basis: %s" % (check["basis"],))
        for line in check["breaches"]:
            lines.append("      BREACH: %s" % (line,))
        for line in check["gaps"]:
            lines.append("      no basis: %s" % (line,))
    return lines


def render(result, single):
    """The whole answer, phases first and the verdict last."""
    lines = []
    phases = [result] if single else result["phases"]
    for answer in phases:
        lines.extend(render_phase(answer))
        lines.append("")
    if not single:
        if result["skipped"]:
            # Named rather than dropped: a gate that reports "no breaches" over a
            # manifest whose phases were every one of them skipped has made a
            # claim about nothing.
            lines.append("SKIPPED (nothing started, so no evidence exists): %s"
                         % ", ".join(result["skipped"]))
        if not result["checked"]:
            lines.append("NO PHASE HAS STARTED: nothing was examined, and that is "
                         "not the same as nothing being wrong.")
    breaches = result["breaches"]
    if breaches:
        lines.append("BREACHES (%d):" % (len(breaches),))
        for line in breaches:
            lines.append("  %s" % (line,))
    else:
        lines.append("No breach found in what could be examined. The `no basis` "
                     "lines above are what could not be.")
    return "\n".join(lines)


def build_parser():
    """The argument parser, separated so a case can read the option table."""
    parser = argparse.ArgumentParser(
        prog="verify-invariants.py", add_help=True, allow_abbrev=False,
        description="Post-hoc check of the orchestrator's invariants for a phase.")
    parser.add_argument("manifest")
    parser.add_argument("phase", nargs="?", default=None,
                        help="the phase id to check; omit it and pass --all")
    parser.add_argument("--all", action="store_true", dest="every",
                        help="every phase that has started (branch, baseRef or a "
                             "recorded commit)")
    parser.add_argument("--project", default=".",
                        help="the directory holding .claude/ and the journal "
                             "(default: the current directory)")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv, out=print):
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return E_USAGE if exc.code else 0
    if bool(args.phase) == bool(args.every):
        # Both or neither. Refused rather than picking one, because the two
        # invocations answer about different subjects and a silently chosen
        # default would put the wrong subject under the right-looking verdict.
        sys.stderr.write(USAGE)
        return E_USAGE

    try:
        manifest = _mio.load_manifest(args.manifest)
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n" % (args.manifest, exc))
        return E_USAGE
    if not isinstance(manifest, dict):
        sys.stderr.write("ERROR: manifest %s is not a JSON object\n"
                         % (args.manifest,))
        return E_USAGE

    project = os.path.abspath(args.project)
    git_root = git_root_for(manifest, project)
    ledger_dir = ledger_dir_for(manifest, args.manifest)

    if args.every:
        result = _invariants.check_manifest(manifest, args.manifest, git_root,
                                            project, ledger_dir=ledger_dir)
        single = False
    else:
        result = _invariants.check_phase(manifest, args.phase, args.manifest,
                                         git_root, project,
                                         ledger_dir=ledger_dir)
        if not result["found"]:
            known = [str(p.get("id")) for p in (manifest.get("phases") or [])
                     if isinstance(p, dict)]
            sys.stderr.write("ERROR: no phase %r in %s (have: %s)\n"
                             % (args.phase, args.manifest, ", ".join(known)))
            return E_USAGE
        single = True

    if args.as_json:
        out(json.dumps(result, indent=2, sort_keys=True))
    else:
        out(render(result, single))
    return E_BREACH if result["breaches"] else 0


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to a usage error, which would read
        # as a broken flag rather than as a moved suite. It deliberately does NOT
        # print the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("verify-invariants.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_verify_invariants.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
