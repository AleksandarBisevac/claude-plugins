#!/usr/bin/env python3
"""
What a commit-a-narrow-allow-list command is made of, in one place.

WHY THIS IS A MODULE RATHER THAN A PARAGRAPH IN EACH COMMAND. Two entry points
here stage a fixed set of paths and commit them -- `commit-audit-state.py` (the
phase's manifest file, the journal and the evidence) and
`commit-manifest-index.py` (the manifest INDEX, and nothing at all beside it) --
and everything except the list itself is the same in both: stage EXPLICITLY
(`git add -- <path>...`, never `git add -A`), read the index back with `git diff
--cached --name-only`, refuse when anything outside the allow-list is in it, and
report the outcome in one shape whichever of the ways it went. Neither command
can import the other, because nothing may import a hyphenated entry point, so a
second copy was the only alternative -- and a second copy of a refusal rule is
how one commit comes to carry what the other forbids.

WHAT IS DELIBERATELY NOT HERE: THE ALLOW-LIST ITSELF. Each command derives its
own, and the two differ in exactly the entries that matter -- one may stage the
phase's shard and the records beside it and never the shared index, the other may
stage only the shared index and never a phase's file. A shared builder taking a
flag would be one function holding two safety properties, which is the shape in
which a widened list stops being noticed.

THE GIT RUNNER IS NOT `_commit_trail._git`, and the difference is a decision
rather than an oversight -- see `run_git` below. `under_any` is likewise built on
`_invariants._under` rather than on a second prefix test: the writer decides what
may be staged and the checker decides what was allowed, and two spellings of
"inside" is how a guard comes to permit a path its reader forbids.

Reads git. Stages nothing and commits nothing: the callers do that, with the
answers these functions give them.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__scoped_commit.py`.
"""
import os
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

import _evidence_io  # noqa: E402  (the one reader of a porcelain line's path)
import _invariants  # noqa: E402  (`_under`: the one answer to "is this inside")


# --- asking git ---------------------------------------------------------------
def run_git(git_root, args, timeout=60):
    """(code, stdout, stderr), or (None, "", why) when git could not be asked.

    NOT `_commit_trail._git`, which `_invariants` reuses one module over, and the
    difference is the reason rather than an oversight: that runner sends stderr to
    DEVNULL, which is right for a READ whose absence is itself an answer and wrong
    for a WRITE whose refusal is the only thing a human can act on. `git commit`
    and `git add` explain themselves on stderr and nowhere else, so discarding it
    here would turn every refusal into a bare exit code -- and it would do as much
    to the reads below, whose `why` sentence would then carry an empty bracket
    where the reason belongs.
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


def lines(text):
    """The non-empty lines of git output, forward-slashed.

    Forward slashes because `git diff --cached --name-only` prints them that way
    on every platform while an allow-list is built from `os.path` joins, and two
    spellings of one path would make the comparison below answer "not allowed" for
    a path that is.
    """
    return [ln.strip().replace("\\", "/") for ln in (text or "").splitlines()
            if ln.strip()]


# --- what may be staged, and what already is ----------------------------------
def under_any(path, allowed):
    """True when `path` is under ANY of `allowed`. The list form of `_under`.

    Separate rather than overloaded, because the two questions differ: "is this in
    the journal" takes one entry, "may this be staged at all" takes the whole
    allow-list, and a single name answering both is how a caller comes to pass a
    list where an entry was meant and get `False` for everything.
    """
    return any(_invariants._under(path, rel) for rel in (allowed or ()))


def foreign_staged(git_root, allowed):
    """`(paths, why)` - what is in the index that this commit may not carry.

    `why` is set when git would not describe the index at all, which is NOT an
    empty list: an unreadable index reported as "nothing foreign" is precisely the
    reading that lets a staged implementation file into a commit nobody reviewed.
    """
    code, out, err = run_git(git_root, ["diff", "--cached", "--name-only"])
    if code is None:
        return [], err
    if code != 0:
        return [], ("git would not list the staged paths (%s)"
                    % ((err or out).strip()[:200],))
    return [p for p in lines(out) if not under_any(p, allowed)], ""


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
    clean sheet these verbs exist to avoid.
    """
    code, out, err = run_git(git_root, ["status", "--porcelain",
                                        "--untracked-files=all", "--"]
                             + list(allowed))
    if code is None:
        return [], err
    if code != 0:
        return [], ("git would not describe the working tree (%s)"
                    % ((err or out).strip()[:200],))
    # `_evidence_io._path_of` rather than a slice: a porcelain line for a RENAME is
    # `XY <old> -> <new>` and only the second name exists now, which is a rule this
    # tree already writes down once. `git mv` into `journal/archive/` is exactly
    # that shape, so the case is real rather than theoretical.
    return [_evidence_io._path_of(ln) for ln in lines(out)], ""


# --- what happened ------------------------------------------------------------
def answer(skipped, committed=False, commit=None, staged=None, refused="",
           foreign=None, journalled=False, quiet=""):
    """One shape for every outcome, so a caller never has to infer one from another.

    `committed` is its own field rather than being read off an empty `staged`
    list: "there was nothing to commit" and "the commit carried nothing" are
    different claims, and a falsy list would render them identically. `quiet`
    carries WHICH of the do-nothing states this was, for the same reason.

    ONE SHAPE ACROSS BOTH COMMANDS, which is what makes `--json` worth reading: a
    caller that has to branch on which verb produced a payload has been handed two
    formats wearing one name.
    """
    return {"committed": committed, "commit": commit,
            "staged": list(staged or []), "skipped": list(skipped or []),
            "refused": refused, "foreign": list(foreign or []),
            "journalled": journalled, "quiet": quiet}


# WHAT A JOURNAL ROW DOES, SPELLED ONCE. Both commands here append a row that
# NAMES the commit's SHA, so the row is written after the commit and can never be
# inside it; this clause is what becomes of it afterwards.
# `commit-audit-state.ONLY_THE_TRAIL` composes this same constant into its
# refusal, because that refusal and the notice below are two different runs'
# answers to ONE fact - and two spellings of that fact is how the run that
# refuses and the run that commits come to disagree about where a row goes.
RIDES_ALONG = ("a journal row rides along with the next commit rather than "
               "earning one")

# F286: SAID ON THE RUN THAT CREATES THE CONDITION, not on the next one. The row
# lands after the commit, so a successful run leaves the trail uncommitted in a
# tree it has just reported as committed - and an operator who has not read this
# module meets the dirty file first and the explanation second, on a second run.
# Reported from a live project, which took two runs on a clean tree to work it
# out.
#
# IT IS SHARED BECAUSE BOTH VERBS HAVE THE PROPERTY, checked rather than assumed:
# `commit-manifest-index.py` never stages the journal at all - its allow-list is
# the index and nothing else - so its row is outside its commit too, and this
# line is a lie in neither. A line that were true of only one of them would
# belong in that command, not here.
#
# BOTH DIRECTIONS ARE PINNED IN `tests/test_commit_audit_state.py` (cas27, cas29)
# rather than beside this module's own cases, because the claim is only worth
# anything end to end: that it prints on a run that really committed AND really
# appended a row, and that it does not print on a run whose row could not be
# written at all.
TRAIL_ROW_WRITTEN = ("the journal row naming this commit was written AFTER it "
                     "and is therefore not in it, so the trail is left "
                     "uncommitted: %s" % (RIDES_ALONG,))


def render(result, prefix, out=print):
    """Print what happened, in the order somebody reading a terminal needs it.

    `prefix` is the command's own bracketed name and is the only thing that
    differs between the two callers - which is why this is one function. The lines
    themselves must not diverge: two verbs that report a refusal in two shapes
    teach a reader that the shape means something, and here it does not.

    THE LAST LINE IS A PAIR AND NEVER A DEFAULT. A row that was written and a row
    that could not be are different states of the world, so each gets its own
    sentence; `journalled` is what decides, because a line claiming the trail
    holds a row when it does not is worse than saying nothing at all.
    """
    for line in result["skipped"]:
        out("  degraded: %s" % (line,))
    if result["refused"]:
        out("%s REFUSED: %s" % (prefix, result["refused"]))
        for path in result["foreign"]:
            out("    already staged: %s" % (path,))
        return
    if not result["committed"]:
        out("%s %s" % (prefix, result["quiet"]))
        return
    out("%s committed %s" % (prefix, result["commit"][:12]))
    for path in result["staged"]:
        out("    %s" % (path,))
    if result["journalled"]:
        out("  %s" % (TRAIL_ROW_WRITTEN,))
    else:
        out("  the commit was made and the journal row could NOT be written, so "
            "nothing in the trail points at it")


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        print("_scoped_commit.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__scoped_commit.py - run that file "
              "instead.")
        sys.exit(0)
    print(__doc__.strip())
