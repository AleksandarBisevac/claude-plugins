#!/usr/bin/env python3
"""Commit any uncommitted audit state, or say there is none.

WHY THIS EXISTS. Test evidence is written beside the manifest and is meant to be
COMMITTED -- it is the record somebody hands to a client. But the orchestrator
commits on success and only on success: a red gate leaves `status =
"in_progress"` and explicitly does NOT commit (`reference/orchestrator.md`
step 4), an infrastructure failure takes a STOP path that commits nothing either,
and the sign-off commit happens once every gate is green. So the rows that say
`failed`, `timed-out`, `cancelled` and `could-not-run` -- exactly the history the
evidence file exists to preserve -- can sit in a working tree for ever.

THE GAP IS NARROWER THAN "EVERY FAILURE", AND SAYING SO IS THE POINT. A task
commit stages the evidence directory, so it carries every row written since the
last commit: a run that fails at attempt one and succeeds at attempt two is
already durable, its failure included. What is NOT durable is a run whose task or
phase never subsequently commits at all. This command is for that case, and it is
safe to call when there is no such case -- a spurious call is a no-op that says
so.

WHAT IT STAGES, AND WHAT IT MUST NEVER STAGE. Three paths: the phase's manifest
file (the shard when sharded, else the single manifest), the journal directory
and the evidence directory. The task's `files` are NOT on that list and cannot be
put on it. That exclusion is the whole design -- a failed task's code is not
committed, and a verb that could sweep it in on the way to preserving a record
would be a commit nobody reviewed, made on the one path where nobody was going to
look.

HOW THE EXCLUSION IS ENFORCED RATHER THAN INTENDED. Paths are staged
EXPLICITLY (`git add -- <path>...`, never `git add -A`), and the index is read
back with `git diff --cached --name-only` and compared against the same
allow-list BEFORE anything is committed. The index is also read BEFORE staging:
work somebody else had already staged would otherwise ride along, and refusing
before touching anything leaves no half-made state to unpick. `_invariants`'
`audit-state-scope` check then re-derives the same rule from git after the fact,
so the commits this makes are graded by something that did not make them.

A DIRECTORY OUTSIDE `gitRoot` IS DEGRADED PAST, NOT FAILED ON -- the same
sentence step 4c already writes for the journal: if it is outside the repository
it cannot be committed, so proceed without it and say which one went missing.

NEVER AN EMPTY COMMIT. Nothing staged means no commit and a line saying there was
nothing to commit, because a stream of empty commits is how a record stops being
read.

AND NEVER A COMMIT THAT ONLY ANCHORS THE LAST ONE. The journal is CARRIED by an
audit-state commit and does not TRIGGER one: the row this command appends to
anchor its own commit lands after that commit, so a verb that treated a dirty
journal as work to do would commit the row announcing the previous commit, append
a row announcing that, and never stop. What triggers a commit is the phase's
manifest file or the evidence directory; the trail rides along with the next one,
which is the same sentence step 4c already writes for the `task.commit` row.

THE COST OF THAT IS STATED RATHER THAN LEFT TO BE DISCOVERED. Until a later commit
carries it, the anchoring row lives only in the working tree - so a CLONE of the
repository holds the audit-state commit and not the row naming it, and
`audit-state-scope` there answers `not-applicable` rather than `clean`. That is
the honest reading (nothing could be examined), and it is the same lag the
`task.commit` row already has.

Usage:
  commit-audit-state.py <manifest> <phaseId> [--project DIR] [--subject TEXT]
                        [--json]

Exit codes:
  0  it ran - it committed, or there was nothing uncommitted and it said which
  1  it could not - git refused, or the index already held work this commit may
     not carry
  2  usage error - the manifest will not load, or there is no such phase
"""
import argparse
import json
import os
import shutil
import subprocess
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

import _evidence_io  # noqa: E402  (where the evidence record lives)
import _invariants  # noqa: E402  (the phase lookup, the git root, the action name)
import _journal_io  # noqa: E402  (where the trail lives, and the append)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR shards)

E_OK, E_FAIL, E_USAGE = 0, 1, 2

# A CONVENTIONAL TYPE OF ITS OWN, and it is not decoration. A task commit's type
# comes from `meta.commit.type`, which a manifest may set to anything -- so a fixed
# literal is the only spelling a task commit cannot collide with, and `git log
# --grep` can separate the two for ever. A reader who meets one of these in a log
# has to be able to tell, without opening it, that it carries no implementation.
COMMIT_TYPE = "audit-state"
DEFAULT_SUBJECT = "the record of a run, without the work it ran on"

# The three things this commit may carry, each with the word its line is reported
# under. Ordered as the commit stages them, which is also the order step 4c names
# them in: the plan, then the trail, then the evidence.
MANIFEST_LABEL = "the phase's manifest file"
JOURNAL_LABEL = "the journal directory"
EVIDENCE_LABEL = "the evidence directory"


# --- git ----------------------------------------------------------------------
def _git(git_root, args, timeout=60):
    """(code, stdout, stderr), or (None, "", why) when git could not be asked.

    NOT `_commit_trail._git`, which `_invariants` reuses one module over, and the
    difference is the reason rather than an oversight: that runner sends stderr to
    DEVNULL, which is right for a READ whose absence is itself an answer and wrong
    for a WRITE whose refusal is the only thing a human can act on. `git commit`
    and `git add` explain themselves on stderr and nowhere else, so discarding it
    here would turn every refusal into a bare exit code.
    """
    try:
        done = subprocess.run(["git", "-C", git_root] + list(args),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=timeout)
    except Exception as exc:
        return None, "", "git could not be run (%s)" % (exc,)
    return (done.returncode,
            done.stdout.decode("utf-8", "replace"),
            done.stderr.decode("utf-8", "replace"))


def _lines(text):
    """The non-empty lines of git output, forward-slashed.

    Forward slashes because `git diff --cached --name-only` prints them that way
    on every platform while the allow-list is built from `os.path` joins, and two
    spellings of one path would make the comparison below answer "not allowed" for
    a path that is.
    """
    return [ln.strip().replace("\\", "/") for ln in (text or "").splitlines()
            if ln.strip()]


# --- what this commit may carry -----------------------------------------------
def _rel_inside(path, git_root):
    """`path` relative to `git_root`, or None when it is outside it.

    `_invariants._rel` rather than a second expression of it, for the reason that
    module states: a manifest or a record living outside the git root cannot be
    committed at all, and a caller that treated the escape as a `../..` path would
    compare it against a `git show` listing that can never contain it. Two answers
    to "is this inside the repository" is how a guard comes to allow a path its
    reader forbids.
    """
    return _invariants._rel(path, git_root)


def stage_targets(manifest, phase, manifest_path, project, git_root, config=None):
    """`{"paths", "journal", "skipped"}` - the allow-list for THIS phase, resolved.

    `paths` are git-root-relative and exist on disk; `journal` is the journal's
    own entry (or None), kept apart because it is the one path that may not
    TRIGGER a commit; `skipped` carries one sentence per thing that could not be
    reached, naming which of the three it was and why. A skip is REPORTED and
    never silent: "the evidence directory was outside the repository" and "the
    evidence directory does not exist" leave the same commit behind, and only one
    of them is a problem somebody should fix.

    THE LIST IS THE SAFETY PROPERTY. Nothing downstream widens it - the staging
    call takes these paths and the index verification takes this same list - so a
    file the task owns has no route into the commit even if it is sitting in the
    working tree beside them.
    """
    config = _journal_io.load_config(project) if config is None else config
    _index_abs, phase_file_abs = _invariants.manifest_files(manifest_path, phase)
    wanted = [(MANIFEST_LABEL, phase_file_abs),
              (JOURNAL_LABEL, _journal_io.journal_dir(project, config)),
              (EVIDENCE_LABEL, _evidence_io.evidence_dir(project, config))]
    paths, skipped, journal = [], [], None
    for label, absolute in wanted:
        rel = _rel_inside(absolute, git_root)
        if rel is None:
            skipped.append("%s lives outside the git root, so it cannot be "
                           "committed - proceeding without it" % (label,))
            continue
        if not os.path.exists(absolute):
            skipped.append("%s does not exist yet, so there is nothing of it to "
                           "stage" % (label,))
            continue
        if label == JOURNAL_LABEL:
            journal = rel
        if rel not in paths:
            paths.append(rel)
    return {"paths": paths, "journal": journal, "skipped": skipped}


def uncommitted(git_root, allowed):
    """`(paths, why)` - what is uncommitted under `allowed`, read WITHOUT staging.

    ASKED OF THE WORKING TREE AND NOT OF THE INDEX, deliberately. The decision to
    commit is taken before anything is staged, so declining leaves the index
    exactly as it was found - there is no half-made state to unpick and no `git
    reset` that has to guess what it was undoing.

    `--untracked-files=all` because git otherwise collapses a wholly untracked
    directory to one entry ending in `/`, and an evidence directory that has never
    been committed is exactly that case: the collapsed form names no file, so a
    caller asking which paths would be carried gets a directory instead of an
    answer.

    `why` is set when git would not describe the tree, which is NOT an empty list:
    reporting "nothing is uncommitted" for a tree git refused to read is the false
    clean sheet this whole verb exists to avoid.
    """
    code, out, err = _git(git_root, ["status", "--porcelain",
                                     "--untracked-files=all", "--"] + list(allowed))
    if code is None:
        return [], err
    if code != 0:
        return [], ("git would not describe the working tree (%s)"
                    % ((err or out).strip()[:200],))
    # `_evidence_io._path_of` rather than a slice: a porcelain line for a RENAME is
    # `XY <old> -> <new>` and only the second name exists now, which is a rule this
    # tree already writes down once. `git mv` into `journal/archive/` is exactly
    # that shape, so the case is real rather than theoretical.
    return [_evidence_io._path_of(ln) for ln in _lines(out)], ""


# One predicate, one signature, and it is `_invariants._under` rather than a
# second expression of it. The rule -- a path IS the entry or sits inside it, with
# the separator, so `evidence-notes/` is not inside `evidence/` -- has to be the
# same on both sides of this pair: the writer decides what may be staged and the
# checker decides what was allowed, and two spellings is how a guard comes to
# permit a path its reader forbids.
_under = _invariants._under


def _under_any(path, allowed):
    """True when `path` is under ANY of `allowed`. The list form of `_under`.

    Separate rather than overloaded, because the two questions differ: "is this in
    the journal" takes one entry, "may this be staged at all" takes the whole
    allow-list, and a single name answering both is how a caller comes to pass a
    list where an entry was meant and get `False` for everything.
    """
    return any(_under(path, rel) for rel in (allowed or ()))


def foreign_staged(git_root, allowed):
    """`(paths, why)` - what is in the index that this commit may not carry.

    `why` is set when git would not describe the index at all, which is NOT an
    empty list: an unreadable index reported as "nothing foreign" is precisely the
    reading that lets a staged implementation file into a commit nobody reviewed.
    """
    code, out, err = _git(git_root, ["diff", "--cached", "--name-only"])
    if code is None:
        return [], err
    if code != 0:
        return [], ("git would not list the staged paths (%s)"
                    % ((err or out).strip()[:200],))
    return [p for p in _lines(out) if not _under_any(p, allowed)], ""


# --- the commit ---------------------------------------------------------------
def commit_message(phase_id, subject, coauthor):
    """The message paragraphs: a conventional subject, and the co-author trailer.

    A LIST RATHER THAN ONE STRING, because that is how it reaches git: one `-m`
    per paragraph, so the trailer is a trailer and not a second sentence of the
    subject line.
    """
    lines = ["%s(%s): %s" % (COMMIT_TYPE, phase_id, subject or DEFAULT_SUBJECT)]
    if coauthor:
        lines.append(str(coauthor))
    return lines


def _phase_id(phase):
    return str((phase or {}).get("id"))


def _coauthor(manifest):
    block = ((manifest or {}).get("meta") or {}).get("commit")
    value = block.get("coauthor") if isinstance(block, dict) else None
    return value if isinstance(value, str) and value.strip() else None


def record_row(project, phase_id, sha, config=None):
    """Anchor the commit in the trail. Returns the file the row landed in, or False.

    THE TARGET IS THE EVIDENCE DIRECTORY AND DELIBERATELY NOT THE PHASE'S MANIFEST
    FILE. `_invariants._recorded_states` reads every row naming that file as a
    WRITE to it and counts the ones whose bytes no commit preserved; this row
    records a COMMIT, not an edit, and pointing it at the shard would inflate that
    denominator and manufacture a gap in `manifest-revalidated` out of a state
    that was in fact preserved.

    REDACTED THE WAY EVERY COMMITTED ROW IS, through `repo_relative_or_token`: an
    evidence directory configured outside the repository would otherwise write an
    absolute path -- somebody's home directory -- into a file that goes to a
    client.

    FAIL-SOFT, `_journal_io.append`'s own contract: a commit that HAPPENED must
    not be reported as not having happened because the trail could not be written.
    """
    config = _journal_io.load_config(project) if config is None else config
    target = _journal_io.repo_relative_or_token(
        project, _evidence_io.evidence_dir(project, config))
    return _journal_io.append(project, {
        "action": _invariants.ACTION_STATE_COMMITTED,
        "actor": {"via": "commit-audit-state"},
        "target": target,
        "summary": "audit state for %s committed as %s - the record of a run "
                   "with none of its work" % (phase_id, sha[:12]),
        "details": {"commit": sha, "phaseId": str(phase_id)},
    }, config=config)


# The two ways this command does nothing, worded APART because they are different
# states of the world and a reader acts on them differently. Folded into one line
# they would both read as "all clear", and the second one is the state a repository
# sits in permanently by design.
NOTHING_UNCOMMITTED = ("nothing uncommitted: the phase's manifest file, the "
                       "journal and the evidence are already in git. No commit "
                       "was made, because an empty one records nothing and "
                       "buries the ones that do.")
ONLY_THE_TRAIL = ("nothing uncommitted but the trail: the only thing not in git "
                  "is a journal row, and a journal row rides along with the next "
                  "commit rather than earning one. Committing it here would "
                  "anchor the last commit, need a row of its own, and never "
                  "stop.")


def render(answer, out=print):
    """Print what happened, in the order somebody reading a terminal needs it."""
    for line in answer["skipped"]:
        out("  degraded: %s" % (line,))
    if answer["refused"]:
        out("[commit-audit-state] REFUSED: %s" % (answer["refused"],))
        for path in answer["foreign"]:
            out("    already staged: %s" % (path,))
        return
    if not answer["committed"]:
        out("[commit-audit-state] %s" % (answer["quiet"],))
        return
    out("[commit-audit-state] committed %s" % (answer["commit"][:12],))
    for path in answer["staged"]:
        out("    %s" % (path,))
    if not answer["journalled"]:
        out("  the commit was made and the journal row could NOT be written, so "
            "nothing in the trail points at it")


# --- cli ----------------------------------------------------------------------
def build_parser():
    """The argument parser, separated so a case can read the option table."""
    parser = argparse.ArgumentParser(
        prog="commit-audit-state.py", add_help=True, allow_abbrev=False,
        description="Commit any uncommitted audit state for one phase, or say "
                    "there is none.")
    parser.add_argument("manifest")
    parser.add_argument("phase")
    parser.add_argument("--project", default=".",
                        help="the directory holding .claude/ and the records "
                             "(default: the current directory)")
    parser.add_argument("--subject", default=None,
                        help="the commit subject after the conventional prefix; "
                             "say what the run was, not what this script does")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _answer(skipped, committed=False, commit=None, staged=None, refused="",
            foreign=None, journalled=False, quiet=""):
    """One shape for every outcome, so a caller never has to infer one from another.

    `committed` is its own field rather than being read off an empty `staged`
    list: "there was nothing to commit" and "the commit carried nothing" are
    different claims, and a falsy list would render them identically. `quiet`
    carries WHICH of the do-nothing states this was, for the same reason.
    """
    return {"committed": committed, "commit": commit,
            "staged": list(staged or []), "skipped": list(skipped or []),
            "refused": refused, "foreign": list(foreign or []),
            "journalled": journalled, "quiet": quiet}


def commit_state(manifest, phase, manifest_path, project, git_root, subject=None,
                 config=None):
    """`(exitCode, answer)` - do the thing and say what happened. Prints nothing.

    A PAIR RATHER THAN AN EXIT CODE, for `run-test-gate.run_gate`'s reason: a
    function that returned only a verdict could not be exercised without a
    terminal around it, and every branch below is a branch a case has to reach.
    """
    config = _journal_io.load_config(project) if config is None else config
    targets = stage_targets(manifest, phase, manifest_path, project, git_root,
                            config=config)
    allowed, skipped = targets["paths"], targets["skipped"]

    # BEFORE STAGING, so a refusal leaves the index exactly as it was found. Work
    # somebody else had already staged would otherwise be swept into a commit
    # whose entire promise is that it carries none.
    foreign, why = foreign_staged(git_root, allowed)
    if why:
        return E_FAIL, _answer(skipped, refused=why)
    if foreign:
        return E_FAIL, _answer(
            skipped, foreign=foreign,
            refused="the index already holds paths this commit may not carry. An "
                    "audit-state commit stages the record and never the work, so "
                    "it refuses rather than sweeping them in - unstage them and "
                    "re-run")
    if not allowed:
        return E_OK, _answer(skipped, quiet=NOTHING_UNCOMMITTED)

    # DECIDED BEFORE ANYTHING IS STAGED. Both do-nothing answers are reached from
    # here with the index untouched, so declining costs nothing and undoes nothing.
    pending, why = uncommitted(git_root, allowed)
    if why:
        return E_FAIL, _answer(skipped, refused=why)
    if not pending:
        return E_OK, _answer(skipped, quiet=NOTHING_UNCOMMITTED)
    if all(_under(path, targets["journal"]) for path in pending):
        return E_OK, _answer(skipped, quiet=ONLY_THE_TRAIL)

    code, add_out, add_err = _git(git_root, ["add", "--"] + allowed)
    if code is None or code != 0:
        return E_FAIL, _answer(skipped,
                               refused="git refused to stage the record (%s)"
                                       % ((add_err or add_out).strip()[:200],))

    # AND THE INDEX IS READ BACK, which is not belt and braces. The first pass
    # judged an index this command had not touched; this one judges the index it
    # is about to commit, and it is the only check that can see a path that
    # arrived through one of the three directories rather than past them.
    foreign, why = foreign_staged(git_root, allowed)
    if why or foreign:
        return E_FAIL, _answer(
            skipped, foreign=foreign,
            refused=why or ("staging produced paths outside the allow-list, so "
                            "nothing was committed"))
    code, staged_out, staged_err = _git(git_root,
                                        ["diff", "--cached", "--name-only"])
    if code is None or code != 0:
        return E_FAIL, _answer(
            skipped, refused="git would not list the staged paths (%s)"
                             % ((staged_err or staged_out).strip()[:200],))
    # AND NO SECOND EMPTY-INDEX GUARD HERE. `pending` above already answered
    # "is there anything to commit", and a duplicate of it after `git add` is
    # reachable only if the tree moved under this process between the two
    # questions - which no case can produce, so nothing would ever have verified
    # it. The promise not to make an empty commit does not rest on it either way:
    # `git commit` refuses an empty index on its own, and that refusal is
    # reported below like any other.
    staged = _lines(staged_out)

    argv_commit = ["commit"]
    for paragraph in commit_message(_phase_id(phase), subject,
                                    _coauthor(manifest)):
        argv_commit.extend(["-m", paragraph])
    code, c_out, c_err = _git(git_root, argv_commit)
    if code is None or code != 0:
        return E_FAIL, _answer(
            skipped, staged=staged,
            refused="git refused the commit (%s) - the record is still staged"
                    % ((c_err or c_out).strip()[:200],))
    code, head, head_err = _git(git_root, ["rev-parse", "HEAD"])
    sha = head.strip() if code == 0 else ""
    if not sha:
        # The commit exists and this process cannot name it. A failure rather
        # than a success with a blank field: the journal row is the only handle
        # anything has on such a commit, and a row naming nothing is worse than
        # no row at all.
        return E_FAIL, _answer(
            skipped, committed=True, staged=staged,
            refused="the commit was made and git would not print its SHA (%s), "
                    "so no journal row could name it"
                    % ((head_err or "").strip()[:200],))

    journalled = bool(record_row(project, _phase_id(phase), sha, config=config))
    return E_OK, _answer(skipped, committed=True, commit=sha, staged=staged,
                         journalled=journalled)


def main(argv, out=print):
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return E_USAGE if exc.code else E_OK

    try:
        manifest = _mio.load_manifest(args.manifest)
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n"
                         % (args.manifest, exc))
        return E_USAGE
    if not isinstance(manifest, dict):
        sys.stderr.write("ERROR: manifest %s is not a JSON object\n"
                         % (args.manifest,))
        return E_USAGE
    phase = _invariants.phase_of(manifest, args.phase)
    if phase is None:
        known = [str(p.get("id")) for p in (manifest.get("phases") or [])
                 if isinstance(p, dict)]
        sys.stderr.write("ERROR: no phase %r in %s (have: %s)\n"
                         % (args.phase, args.manifest, ", ".join(known)))
        return E_USAGE

    project = os.path.abspath(args.project)
    git_root = _invariants.git_root_for(manifest, project)
    if not shutil.which("git"):
        out("[commit-audit-state] git is not on PATH, so audit state cannot be "
            "committed at all. Nothing was staged.")
        return E_FAIL

    code, answer = commit_state(manifest, phase, args.manifest, project,
                                git_root, subject=args.subject)
    if args.as_json:
        out(json.dumps(answer, indent=2, sort_keys=True))
    else:
        render(answer, out=out)
    return code


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to a usage error, which would read
        # as a broken flag rather than as a moved suite. It deliberately does NOT
        # print the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("commit-audit-state.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_commit_audit_state.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
