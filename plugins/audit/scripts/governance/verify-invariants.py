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

THE BASELINE. A long history carries breaches nobody will ever repair - frozen
commits are not rewritten to fix their scope - and printing every one of them
on every run buries the one made today. `--write-baseline` records the current
breaches as fingerprints in `invariants-baseline.json` beside the manifest, and
once that file exists a run prints only what it does not hold, plus how many it
does. It lives beside the manifest, next to the journal and evidence directories
and not inside either, because it is a committed record about THIS plan's history
that a clone must receive with the plan, and both of those directories have
readers that parse every file in them as their own rows.

A fingerprint is the phase, the check and the breach line, which names its
subject and the commit's SHA. Frozen history is SHA-stable, so that is enough to
match on; a REWRITE is not. A rebase, squash or amend gives a commit a new SHA,
so its breach comes back as new and its old entry matches nothing. Neither is
hidden: a baseline entry that no longer matches is always printed, with what git
says about the commit it names, and the output states the rule on every run
that reads a baseline.

Nothing mutates without `--write-baseline`: no lock is taken, no file is
written, and git is only read. With it, the one file written is the baseline.
"""
import argparse
import json
import os
import re
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

import _commit_trail  # noqa: E402  (does this clone still have a commit)
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


# --- the baseline -------------------------------------------------------------
BASELINE_NAME = "invariants-baseline.json"
BASELINE_VERSION = 1

# A commit SHA as the checks print one. The digit is required because an
# abbreviation of twelve hex characters with no digit in it is vanishingly rare,
# while an English word spelled only from a-f is not.
_SHA = re.compile(r"\b(?=[0-9a-f]*[0-9])[0-9a-f]{7,40}\b")

REWRITE_RULE = (
    "a fingerprint is the phase, the check and the breach line, which names its "
    "subject and commit SHA. A rebase, squash or amend gives a commit a new SHA, "
    "so its breach is listed as NEW and its old entry as no longer matching - "
    "review both, then re-run with --write-baseline")

BASELINE_ABOUT = (
    "Breach fingerprints verify-invariants.py reports as known rather than new. "
    "Written only by --write-baseline; commit it beside the manifest. %s."
    % (REWRITE_RULE[0].upper() + REWRITE_RULE[1:],))


def baseline_path_for(manifest_path):
    """Where the baseline lives: beside the manifest, next to its records."""
    return os.path.join(os.path.dirname(os.path.abspath(manifest_path)),
                        BASELINE_NAME)


def _key(entry):
    return (entry["phase"], entry["check"], entry["breach"])


def _entry(phase_id, check, line):
    commits = []
    for sha in _SHA.findall(line):
        if sha not in commits:
            commits.append(sha)
    return {"phase": str(phase_id), "check": check, "breach": line,
            "commits": commits}


def fingerprints(answers):
    """One entry per distinct breach across `answers`, in a total order."""
    seen = {}
    for answer in answers:
        for check in answer["checks"]:
            for line in check["breaches"]:
                entry = _entry(answer["phaseId"], check["name"], line)
                seen[_key(entry)] = entry
    return [seen[k] for k in sorted(seen)]


def read_baseline(path):
    """`(entries, None)`, or `(None, why)` when the file is not a baseline.

    A file that is there and cannot be read is an error and never an empty
    baseline: reading it as empty would print every frozen breach as new, and
    reading it as absent would print them all without saying a baseline was
    asked for.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            body = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, "cannot read the baseline %s: %s" % (path, exc)
    rows = body.get("entries") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        return None, ("the baseline %s has no `entries` list, so it is not a "
                      "file --write-baseline wrote" % (path,))
    entries = []
    for row in rows:
        if not (isinstance(row, dict)
                and all(isinstance(row.get(k), str)
                        for k in ("phase", "check", "breach"))):
            return None, ("the baseline %s holds an entry without a phase, a "
                          "check and a breach: %r" % (path, row))
        entries.append(_entry(row["phase"], row["check"], row["breach"]))
    return entries, None


def compare(entries, current, examined):
    """Split the baseline and the current breaches against each other.

    Only entries for a phase this run examined can be matched or not; the rest
    are counted as `notCompared`, because a single-phase run has said nothing
    about any other phase and calling their entries stale would be a claim
    about evidence it never read.
    """
    known = set(_key(e) for e in entries)
    now = set(_key(e) for e in current)
    in_scope = [e for e in entries if e["phase"] in examined]
    return {
        "matched": len([e for e in current if _key(e) in known]),
        "new": [e for e in current if _key(e) not in known],
        "unmatched": [e for e in in_scope if _key(e) not in now],
        "notCompared": len(entries) - len(in_scope),
    }


def _commit_state(git_root, sha, cut):
    """What git says about one commit a stale entry names, as a sentence."""
    state = _commit_trail.resolve(git_root, sha, cut=cut)
    if state == "absent":
        return ("commit %s is not in this clone - a rewrite whose old commits "
                "were collected, or history this clone never fetched" % (sha,))
    if state != "present":
        return ("whether commit %s is in this clone could not be asked (no git, "
                "or a shallow clone)" % (sha,))
    code, refs = _commit_trail._git(git_root, [
        "for-each-ref", "--contains", sha, "--count=1", "--format=%(refname)"])
    if code is None or code != 0:
        return "git would not say which refs contain commit %s" % (sha,)
    if not refs.strip():
        return ("commit %s is reachable from no branch or tag - a rebase, squash "
                "or amend rewrote it, or its branch was deleted" % (sha,))
    return "commit %s is still reachable" % (sha,)


def explain_unmatched(entries, git_root):
    """Each stale entry with `reason`: what became of the commits it names."""
    if not entries:
        return []
    cut = _commit_trail.is_shallow(git_root) is not False
    out = []
    for entry in entries:
        states = [_commit_state(git_root, sha, cut) for sha in entry["commits"]]
        gone = [s for s in states if not s.endswith("is still reachable")]
        if gone:
            reason = "; ".join(gone)
        else:
            reason = ("the breach is no longer reported - it was repaired, or "
                      "the check's wording changed%s"
                      % ("; " + "; ".join(states) if states else ""))
        row = dict(entry)
        row["reason"] = reason
        out.append(row)
    return out


def write_baseline(path, current, examined, previous):
    """Write the baseline -> `(written, removed)`.

    Entries for phases this run did not examine are carried over unchanged, so
    rewriting after one phase cannot erase another's. What it does remove is
    returned, because a rewrite is the one place an entry leaves the file, and
    it must not leave without being named.
    """
    kept = [e for e in (previous or []) if e["phase"] not in examined]
    now = set(_key(e) for e in current)
    removed = [e for e in (previous or [])
               if e["phase"] in examined and _key(e) not in now]
    merged = dict((_key(e), e) for e in kept + list(current))
    written = [merged[k] for k in sorted(merged)]
    _mio.atomic_write_json(path, {"about": BASELINE_ABOUT,
                                  "version": BASELINE_VERSION,
                                  "entries": written})
    return written, removed


# --- rendering ----------------------------------------------------------------
def render_phase(answer, known=None):
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
        for line in check["breaches"]:
            if known is not None and _key(_entry(answer["phaseId"], check["name"],
                                                 line)) in known:
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
    if answer["notCompared"]:
        lines.append("  %d entry(ies) for phases not examined in this run were "
                     "not compared" % (answer["notCompared"],))
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
             "over for phases not examined in this run"
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
        lines.extend(render_phase(answer, known))
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
                             "runs then print only breaches it does not hold")
    return parser


def _baseline_answer(args, result, single, git_root):
    """`(key, block, known, error)` - what the baseline adds to `result`.

    `key` is the result field the block goes under, or None when no baseline is
    in use; `known` is the baselined fingerprints the renderer hides, from the
    same read the block was built from; `error` is a sentence for exit 2.
    """
    explicit = args.baseline is not None
    path = os.path.abspath(args.baseline if explicit
                           else baseline_path_for(args.manifest))
    exists = os.path.isfile(path)
    answers = [result] if single else result["phases"]
    examined = set(str(a["phaseId"]) for a in answers)
    current = fingerprints(answers)
    previous = None
    if exists:
        previous, why = read_baseline(path)
        if why:
            return None, None, None, why
    if args.write_baseline:
        written, removed = write_baseline(path, current, examined, previous)
        block = {"path": path, "entries": len(written), "removed": removed,
                 "kept": len([e for e in written
                              if e["phase"] not in examined])}
        return "baselineWritten", block, None, None
    if not exists:
        if explicit:
            return None, None, None, ("no baseline at %s - write one with "
                                      "--write-baseline" % (path,))
        return None, None, None, None
    split = compare(previous, current, examined)
    split["unmatched"] = explain_unmatched(split["unmatched"], git_root)
    split.update({"path": path, "entries": len(previous),
                  "rewriteRule": REWRITE_RULE})
    return "baseline", split, set(_key(e) for e in previous), None


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

    try:
        key, block, known, why = _baseline_answer(args, result, single, git_root)
    except OSError as exc:
        why = "cannot write the baseline: %s" % (exc,)
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
    if key == "baseline":
        return E_BREACH if block["new"] else 0
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
