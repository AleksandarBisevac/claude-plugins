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
refuses - so the check would be off exactly where it matters.

Usage:
  verify-invariants.py <manifest> <phaseId> [--project DIR] [--json]
                       [--baseline FILE] [--write-baseline]
  verify-invariants.py <manifest> --all     [--project DIR] [--json]
                       [--baseline FILE] [--write-baseline]

Exit codes:
  0  answered - no breach found (gaps are printed, or counted in the one
     line a command run without `--verbose` prints, and do not fail)
  1  at least one breach - with a baseline in use, at least one it does not
     hold. A --write-baseline that succeeded exits 0: what it found is exactly
     what it just baselined, and the count it wrote is printed; a refused write
     is 2
  2  usage error, an unreadable manifest, a phase id that is not there, a
     baseline that cannot be read or written, or a check that raised

WHY A GAP EXITS 0 AND A BREACH EXITS 1. They are different claims. A breach is
evidence that a rule was broken; a gap is the absence of evidence either way - a
deleted branch reflog, an unmetered repository, a manifest state no commit
preserved. Failing a build on a gap would fail it on every finished phase (the
sign-off deletes the branch), and within a day the gate would be switched off.
Printing the gap where the verdict goes is the honest half: `partial` and
`no-basis` are words in the output, never silence.

THE BASELINE. A long history carries breaches nobody will ever repair - frozen
commits are not rewritten to fix their scope - and printing every one of them
on every run buries the one made today. `--write-baseline` records the current
breaches in `invariants-baseline.json` beside the manifest, and once that file
exists a run prints only what it does not hold, plus how many it does, and exits
1 only on a new one. It lives beside the manifest, next to the journal and
evidence directories and not inside either, because it is a record about THIS
plan's history that a clone must receive with the plan, and both of those
directories have readers that parse every file in them as their own rows.

What an entry is matched on, what is set aside rather than compared, and why the
write refuses while a phase is in flight are `_invariants`' - the gate reads the
same baseline through the same functions, so the two cannot disagree about which
breaches count. An entry that no longer matches is always printed, never
dropped, and the rule for a rewritten history is printed on every run that reads
a baseline.

Nothing mutates without `--write-baseline`: no lock is taken, no file is
written, and git is only read. With it, the one file written is the baseline,
under the `index` lock.
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
import _invariants  # noqa: E402  (the rule this command carries)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR shards)

USAGE = ("usage: verify-invariants.py <manifest> <phaseId|--all> "
         "[--project DIR] [--json] [--baseline FILE] [--write-baseline]\n")

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


# The baseline's names, spelled here because this command renders them. NOT
# copies: `_invariants` owns the file, the matching and the write, and
# `tests/test_verify_invariants.py` pins each to be that module's own object.
BASELINE_NAME = _invariants.BASELINE_NAME
REWRITE_RULE = _invariants.REWRITE_RULE
baseline_key = _invariants.baseline_key


# --- rendering ----------------------------------------------------------------
def render_phase(answer, known=None, clone=None):
    """The lines for one phase: a verdict per check, then what it rests on.

    `known` is the set of baselined fingerprints, or None when no baseline is
    in use. A baselined breach is counted on its check's line block rather than
    printed, which is the whole of what the baseline changes here.
    """
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
        baselined = 0
        for line, key in zip(check["breaches"], check["keys"]):
            if known is not None and baseline_key(_invariants._fingerprint(
                    answer["phaseId"], check["name"], line, key,
                    clone)) in known:
                baselined += 1
                continue
            lines.append("      BREACH: %s" % (line,))
        if baselined:
            lines.append("      baselined: %d breach(es) the baseline holds"
                         % (baselined,))
        for line in check["gaps"]:
            lines.append("      no basis: %s" % (line,))
    return lines


def _entry_line(entry):
    return "%s %s: %s" % (entry["phase"], entry["check"], entry["breach"])


def render_baseline(answer):
    """The verdict block when a baseline is in use: new, known, and stale."""
    lines = ["NEW BREACHES (%d):" % (len(answer["new"]),)]
    lines.extend("  %s" % (_entry_line(e),) for e in answer["new"])
    lines.append("BASELINE: %d baselined breach(es) still reported and not "
                 "listed above, from %s (%d entry(ies))"
                 % (answer["matched"], answer["path"], answer["entries"]))
    for why in sorted(answer["notComparedWhy"]):
        lines.append("  %d entry(ies) not compared: %s"
                     % (answer["notComparedWhy"][why], why))
    lines.append("  basis: %s" % (REWRITE_RULE,))
    if answer["unmatched"]:
        lines.append("BASELINE ENTRIES THAT NO LONGER MATCH (%d) - kept in the "
                     "file until --write-baseline is run again:"
                     % (len(answer["unmatched"]),))
        for entry in answer["unmatched"]:
            lines.append("  %s" % (_entry_line(entry),))
            lines.append("      %s" % (entry["reason"],))
    return lines


def render_written(answer):
    """What a --write-baseline run did to the file, removals by name."""
    lines = ["BASELINE WRITTEN: %d fingerprint(s) to %s, %d of them carried "
             "over uncompared from the previous file"
             % (answer["entries"], answer["path"], answer["kept"])]
    if answer["removed"]:
        lines.append("  removed %d entry(ies) that no longer matched:"
                     % (len(answer["removed"]),))
        lines.extend("    %s" % (_entry_line(e),) for e in answer["removed"])
    lines.append("  basis: %s" % (REWRITE_RULE,))
    return lines


def render(result, single, known=None):
    """The whole answer, phases first and the verdict last."""
    lines = []
    phases = [result] if single else result["phases"]
    for answer in phases:
        lines.extend(render_phase(answer, known,
                                  (result.get("baseline") or {}).get("clone")))
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
    if result.get("baseline"):
        lines.extend(render_baseline(result["baseline"]))
        return "\n".join(lines)
    breaches = result["breaches"]
    if breaches:
        lines.append("BREACHES (%d):" % (len(breaches),))
        for line in breaches:
            lines.append("  %s" % (line,))
    else:
        lines.append("No breach found in what could be examined. The `no basis` "
                     "lines above are what could not be.")
    if result.get("baselineWritten"):
        lines.extend(render_written(result["baselineWritten"]))
    return "\n".join(lines)


# --- the command --------------------------------------------------------------
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
    parser.add_argument("--baseline", default=None, metavar="FILE",
                        help="the breach baseline to compare against (default: "
                             "%s beside the manifest, used when it exists)"
                             % (BASELINE_NAME,))
    parser.add_argument("--write-baseline", action="store_true",
                        dest="write_baseline",
                        help="record this run's breaches as the baseline; later "
                             "runs then print only breaches it does not hold. "
                             "Refused while a phase it covers is in flight")
    return _claude_home.attach_usage_hint(parser)


def _baseline_answer(args, result, manifest, git_root):
    """`(key, block, known, error)` - what the baseline adds to `result`.

    `key` is the result field the block goes under, or None when no baseline is
    in use; `known` is the baselined keys the renderer hides; `error` is a
    sentence for exit 2.
    """
    if args.write_baseline:
        path = os.path.abspath(args.baseline if args.baseline is not None
                               else _invariants.baseline_path_for(args.manifest))
        block, why = _invariants.write_baseline(path, result, manifest, git_root)
        return ("baselineWritten" if block else None), block, None, why
    block, why = _invariants.apply_baseline(result, args.manifest, git_root,
                                            path=args.baseline)
    if why or not block:
        return None, None, None, why
    # What to hide is what matched, and a matched key is one of this run's own:
    # this run's keys less the new ones, with no second read of the file.
    new = set(baseline_key(e) for e in block["new"])
    known = set(baseline_key(e) for e in _invariants.fingerprints(
        result, block.get("clone"))) - new
    return "baseline", block, known, None


def success_line(lines):
    """A clean answer's one line: which phases, that no breach was found, and
    how many `no basis` lines - checks that could not be examined - the long
    form names. A written baseline is said as the record it wrote.

    None - the long form - when a baseline is compared (what still matches and
    what no longer does is the answer), or when no phase had started.
    """
    said = [ln.strip() for ln in lines if ln.strip()]
    written = [ln for ln in said if ln.startswith("BASELINE WRITTEN: ")]
    if written:
        return "[verify-invariants] %s" % (written[0],)
    if (not any(ln.startswith("No breach found") for ln in said)
            or any(ln.startswith(("NO PHASE HAS STARTED", "NEW BREACHES",
                                  "BASELINE")) for ln in said)):
        return None
    phases = [ln for ln in said if ln.startswith("PHASE ")]
    gaps = len([ln for ln in said if ln.startswith("no basis: ")])
    skipped = [ln for ln in said if ln.startswith("SKIPPED ")]
    return "[verify-invariants] %s: no breach found in what could be examined; " \
           "%d `no basis` line(s)%s%s" % (
               ", ".join(phases), gaps,
               " (`--verbose` names them)" if gaps else "",
               "; %s" % (skipped[0],) if skipped else "")


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

    try:
        if args.every:
            result = _invariants.check_manifest(manifest, args.manifest,
                                                git_root, project,
                                                ledger_dir=ledger_dir)
        else:
            result = _invariants.check_phase(manifest, args.phase, args.manifest,
                                             git_root, project,
                                             ledger_dir=ledger_dir)
    except Exception as exc:
        # EXIT 2, NOT THE 1 AN UNCAUGHT RAISE WOULD GIVE. 1 is "at least one
        # breach", and sign-off would read a crash as a finding about the work
        # instead of as a question that could not be asked.
        sys.stderr.write("ERROR: the invariant checks could not run: %s: %s\n"
                         % (type(exc).__name__, exc))
        return E_USAGE
    single = not args.every
    if single:
        if not result["found"]:
            known = [str(p.get("id")) for p in (manifest.get("phases") or [])
                     if isinstance(p, dict)]
            sys.stderr.write("ERROR: no phase %r in %s (have: %s)\n"
                             % (args.phase, args.manifest, ", ".join(known)))
            return E_USAGE

    try:
        key, block, known, why = _baseline_answer(args, result, manifest,
                                                  git_root)
    except Exception as exc:
        why = "the baseline could not be applied or written: %s: %s" % (
            type(exc).__name__, exc)
    if why:
        sys.stderr.write("ERROR: %s\n" % (why,))
        return E_USAGE
    if key:
        result[key] = block

    if args.as_json:
        out(json.dumps(result, indent=2, sort_keys=True))
    else:
        out(render(result, single, known))
    if key == "baselineWritten":
        return 0
    return E_BREACH if _invariants.counted_breaches(result) else 0


if __name__ == "__main__":
    from _output import safe_stdio, selftest_requested  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if selftest_requested(sys.argv[1:]):
        # Answers rather than falling through to a usage error, which would read
        # as a broken flag rather than as a moved suite. It deliberately does NOT
        # print the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("verify-invariants.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_verify_invariants.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(_output.terse_cli(main, sys.argv[1:], success_line))
