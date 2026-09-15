#!/usr/bin/env python3
"""Commit ONE task's work, staging what that task declares and refusing the rest.

WHY THIS EXISTS. The successful task commit was the one git operation this plugin
described in prose and did not script. `reference/orchestrator.md` step 4c spells
the staging list, the pathspec, the message shape and the exclusions in a
paragraph the model reads at the end of every task, under time pressure, after
the work is already done - and what a paragraph gets in that position is
generalisation. Four scope breaches on one program came from widening two words
of it: a file "obviously" part of the change, a sibling the editor had also
touched, the shared index because the phase file was allowed. Every one of them
is a commit nobody reviewed, made against the record everything else is graded
by.

Prose cannot refuse. This can.

THE THIRD SCOPED COMMIT, AND THE SHAPE IS ITS SIBLINGS'. `commit-audit-state.py`
carries the RECORD of a run and never the work; `commit-manifest-index.py`
carries the shared index and nothing else; this one carries the WORK. Each
derives its own allow-list and none of them shares a builder, because a shared
builder taking a flag would be one function holding three safety properties -
the shape in which a widened list stops being noticed. What they do share is
`_scoped_commit`: the staging discipline, the two index reads and the answer
shape, so no two of them can disagree about what "refused" means.

WHAT IT STAGES. Exactly the four things step 4c allows, each named in the output:
the task's own `files`, the phase's manifest file (the shard when sharded), the
journal directory and the evidence directory. Nothing else, and the manifest
INDEX explicitly not - a task commit carrying the index is what makes two
parallel phases conflict on merge, which is the property the sharded layout was
introduced to buy. `_invariants.commit_scope` re-derives that same list from git
afterwards, so the commits this makes are graded by something that did not make
them, and the two lists are written against one paragraph rather than against
each other.

HOW THE EXCLUSION IS ENFORCED RATHER THAN INTENDED. Paths are staged EXPLICITLY
(`git add -- <path>...`, never `git add -A`), the git index is read BEFORE
staging so work somebody else had already staged cannot ride along, and it is
read BACK afterwards and compared against the same allow-list before anything is
committed. A path outside the list is NAMED in the refusal: "something is
staged that should not be" sends a reader to find it, and finding it is the step
that gets skipped.

A DECLARED FILE THAT DOES NOT EXIST IS NOT AN ERROR, AND THAT COSTS A GIT CALL.
The red-first workflow has a task naming the case it will write before anything
is there, and `git add -- <path>` does not shrug at a pathspec matching nothing -
it fails the whole staging call, so one such entry would refuse every commit that
task ever makes. The test cannot be the working tree alone either: a task may
DELETE a file it declares, and that path is absent from the tree and is exactly
what has to be staged. So the question is asked of git - absent from the tree AND
untracked is reported and passed over, absent but tracked is a deletion and is
staged.

WHY IT DOES NOT WRITE `task.commit`. The SHA is only knowable after the commit
this makes, and the shard is inside that commit - so writing it here would need a
second commit or an amend, and `orchestrator.md` forbids the amend. The SHA is
printed instead and `/audit:task done <taskId> --commit <sha>` records it, riding
along with the next commit exactly as step 4c already says. Two verbs, one each
for the thing git owns and the thing the plan owns.

NEVER AN EMPTY COMMIT. Nothing staged means no commit and a line saying so,
because a stream of empty commits is how a record stops being read.

Usage:
  commit-task-work.py <manifest> <taskId> [--project DIR] [--subject TEXT]
                      [--json]

Exit codes:
  0  it ran - it committed, or there was nothing to commit and it said which
  1  it could not - git refused, or the git index already held paths this commit
     may not carry (each one named)
  2  usage error - the manifest will not load, or there is no such task

IT TAKES NO LOCK, and that is the asymmetry with `commit-manifest-index.py`
rather than an omission: this commit touches the phase's own shard, which only
that phase's run writes, and the task's own files, which the plan gate has
already bound to one task. The index lock exists for the file every structural
command in the repository writes, and this commit refuses that file.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_commit_task_work.py`.

Stdlib only, Python 3.8 compatible.
"""
import argparse
import json
import os
import shutil
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

import _evidence_io  # noqa: E402  (where the evidence ledger lives)
import _invariants  # noqa: E402  (the git root, the manifest file pair, the under-test)
import _journal_io  # noqa: E402  (where the trail lives, and the append)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR shards)
import _manifest_vocab as _vocab  # noqa: E402  (one reading of a `files` entry's line suffix)
import _scoped_commit  # noqa: E402  (the staging discipline and the answer shape, shared with the other two scoped commits)

E_OK, E_FAIL, E_USAGE = 0, 1, 2

# What every line this command prints is stamped with. A constant because the
# renderer is `_scoped_commit`'s and takes it as an argument -- the lines are
# shared with the other two scoped commits and the NAME is the only thing that
# differs.
PREFIX = "[commit-task-work]"

# The default conventional type when the manifest names none. A TASK commit's type
# is the manifest's to choose (`meta.commit.type`) -- unlike the other two scoped
# commits, whose types are fixed literals so `git log` can tell those classes apart
# -- because this commit carries implementation and a project's own convention is
# the right one for it. `feat` is not the default: a fallback that claims a feature
# on work nobody described would be a wrong word written by a default.
DEFAULT_COMMIT_TYPE = "chore"

# The word the subject opens with, ahead of anything a caller passes. Its siblings
# carry the same constant for the same reason: with the id first the subject after
# the colon IS sentence-case, which commitlint's default `subject-case` refuses
# along with start-case, pascal-case and upper-case. A fixed lowercase word this
# command owns is out of reach of all of them.
SUBJECT_LEAD = "audit"

DEFAULT_SUBJECT = "the task's own files, and the record beside them"

# The labels each allow-list entry is reported under. Written out because a skip is
# REPORTED and never silent, and "the journal directory is outside the repository"
# and "the journal directory does not exist yet" leave the same commit behind while
# being different things to know.
MANIFEST_LABEL = "the phase's manifest file"
JOURNAL_LABEL = "the journal directory"
EVIDENCE_LABEL = "the evidence directory"
DECLARED_LABEL = "the task's declared file"

# The action the trail records for this commit. LOCAL to this file, unlike
# `_invariants.ACTION_STATE_COMMITTED` and `ACTION_INDEX_COMMITTED`, and the
# difference is a fact about the readers rather than an inconsistency: those two
# classes are findable ONLY through the journal, so a reader in `_invariants` has
# to share their spelling. A task commit is named by `task.commit` in the plan
# itself, which is what `_invariants.commit_scope` reads, so nothing outside this
# file needs this word and putting it one module down would be a constant with one
# reader.
ACTION_TASK_COMMITTED = "audit.task.committed"

# The three ways this command does nothing, worded APART because they are different
# states of the world and a reader acts on them differently.
NOTHING_UNCOMMITTED = ("nothing uncommitted: this task's files and the records "
                       "beside them are already in git. No commit was made, "
                       "because an empty one records nothing and buries the ones "
                       "that do.")
NOTHING_TO_STAGE = ("there is nothing this commit may carry - the lines above "
                    "say which way each entry went missing. Nothing was staged.")


# --- what this commit may carry -----------------------------------------------
def tracked(git_root, paths):
    """The subset of `paths` git already tracks, as a set.

    ONE CALL FOR THE WHOLE LIST rather than one per path: the answer is only
    needed for entries that are not on disk, and asking git once keeps a task
    declaring many files from paying a process apiece.

    EVERYTHING IS 'TRACKED' WHEN GIT CANNOT BE ASKED, which is the loud
    direction. The alternative is to drop the path here and commit a subset of
    the task's work while reporting success; keeping it means the staging call
    below fails and says why. This function decides what to SKIP, so its
    uncertain answer must be the one that skips nothing.
    """
    if not paths:
        return set()
    code, out, _err = _scoped_commit.run_git(git_root,
                                             ["ls-files", "--"] + list(paths))
    if code is None or code != 0:
        return set(paths)
    return set(_scoped_commit.lines(out))


def stage_targets(manifest, phase, task, manifest_path, project, git_root,
                  config=None):
    """`{"paths", "declared", "skipped", "indexRel"}` - the allow-list, resolved.

    `paths` are git-root-relative and are the ONLY thing anything downstream may
    stage; `declared` is the subset that came from the task's own `files`, kept
    apart so the refusal can say which half of the list a path failed against;
    `skipped` carries one sentence per entry that could not be reached; `indexRel`
    is the manifest index, carried so the refusal can name it as the specific
    mistake it is rather than as one more stray path.

    THE LIST IS THE SAFETY PROPERTY, exactly as it is in the other two scoped
    commits. Nothing downstream widens it - the staging call takes these paths and
    both index verifications take this same list - so a sibling file the editor
    happened to touch has no route into the commit even while it sits modified in
    the working tree beside them.

    A `:line-range` SUFFIX IS STRIPPED. `files` entries may carry one and git has
    never heard of it; staging `a/b.py:10-20` would either fail or, worse, create
    a pathspec that matches nothing and leave the real file uncommitted.
    """
    config = _journal_io.load_config(project) if config is None else config
    index_abs, phase_file_abs = _invariants.manifest_files(manifest_path, phase)
    paths, declared, skipped = [], [], []

    # RESOLVED FIRST, ASKED OF GIT SECOND. The `ls-files` question is only worth
    # asking about entries that are not on disk, and it is asked once for all of
    # them - see `tracked` for why its uncertain answer keeps a path rather than
    # dropping it.
    candidates, absent = [], []
    for entry in (task.get("files") or []):
        name = _vocab._strip_line_suffix(entry)
        if not name.strip():
            continue
        absolute = os.path.join(project, str(name))
        rel = _invariants._rel(absolute, git_root)
        if rel is None:
            skipped.append("%s %s lives outside the git root, so it cannot be "
                           "committed at all" % (DECLARED_LABEL, name))
            continue
        if rel in [c[0] for c in candidates]:
            continue
        candidates.append((rel, name))
        if not os.path.exists(absolute):
            absent.append(rel)
    on_disk_or_in_git = tracked(git_root, absent)
    for rel, name in candidates:
        if rel in absent and rel not in on_disk_or_in_git:
            skipped.append("%s %s is neither in the working tree nor tracked by "
                           "git, so there is nothing of it to commit yet"
                           % (DECLARED_LABEL, name))
            continue
        paths.append(rel)
        declared.append(rel)

    for label, absolute in ((MANIFEST_LABEL, phase_file_abs),
                            (JOURNAL_LABEL, _journal_io.journal_dir(project,
                                                                    config)),
                            (EVIDENCE_LABEL, _evidence_io.evidence_dir(project,
                                                                       config))):
        rel = _invariants._rel(absolute, git_root)
        if rel is None:
            skipped.append("%s lives outside the git root, so it cannot be "
                           "committed - proceeding without it" % (label,))
            continue
        if not os.path.exists(absolute):
            skipped.append("%s does not exist yet, so there is nothing of it to "
                           "stage" % (label,))
            continue
        if rel not in paths:
            paths.append(rel)

    index_rel = _invariants._rel(index_abs, git_root)
    if index_rel is not None and os.path.abspath(index_abs) == os.path.abspath(
            phase_file_abs):
        # The single-file layout: the manifest IS the index, and step 4c's "do NOT
        # stage the index" is about the SHARDED index a parallel phase would
        # conflict on. Naming it here would refuse the manifest this commit is
        # required to carry.
        index_rel = None
    return {"paths": paths, "declared": declared, "skipped": skipped,
            "indexRel": index_rel}


def foreign_refusal(foreign, targets):
    """The sentence a staged path outside the allow-list earns, NAMING it.

    THE INDEX IS ITS OWN SENTENCE, for `_invariants.commit_scope`'s reason one
    step later: "do NOT stage the index" is a separate rule and a separate
    failure, and reporting the expensive mistake in the same words as a stray
    README is what makes a reader skim past it.

    Returns None when `foreign` is empty, so the caller's branch reads as a
    question rather than as a string test.
    """
    if not foreign:
        return None
    index_rel = targets.get("indexRel")
    if index_rel and index_rel in foreign:
        return ("the manifest INDEX (%s) is staged, and a task commit may not "
                "carry it. A task commit changes only its own phase's shard - "
                "the index is what two parallel phases would then conflict on, "
                "which is the whole reason the sharded layout exists. Unstage "
                "it and commit it with commit-manifest-index.py" % (index_rel,))
    return ("the git index holds paths this commit may not carry: %s. A task "
            "commit carries that task's declared `files`, its phase's manifest "
            "file, the journal and the evidence - and refuses rather than "
            "sweeping anything else in. Unstage them, or declare them on the "
            "task with `/audit:task scope <taskId> --files ...` if they really "
            "are its work" % (", ".join(foreign),))


# --- the commit ---------------------------------------------------------------
def commit_message(task_id, subject, manifest):
    """The message paragraphs: a conventional subject, and the co-author trailer.

    A LIST RATHER THAN ONE STRING, because that is how it reaches git: one `-m`
    per paragraph, so the trailer is a trailer and not a second sentence of the
    subject line.

    THE TYPE IS THE MANIFEST'S AND THE SCOPE IS THE TASK ID, which is the shape
    `orchestrator.md` step 4c already prescribes and the shape `/audit:doctor`
    and every reader of a log expects of implementation work. Its two siblings fix
    both halves to literals instead, because their whole point is to be tellable
    apart from a task commit at a glance; this is the class they are being told
    apart FROM.
    """
    block = ((manifest or {}).get("meta") or {}).get("commit")
    block = block if isinstance(block, dict) else {}
    ctype = block.get("type")
    ctype = ctype if isinstance(ctype, str) and ctype.strip() \
        else DEFAULT_COMMIT_TYPE
    paragraphs = ["%s(%s): %s - %s" % (ctype.strip(), task_id, SUBJECT_LEAD,
                                       subject or DEFAULT_SUBJECT)]
    coauthor = block.get("coauthor")
    if isinstance(coauthor, str) and coauthor.strip():
        paragraphs.append(coauthor)
    return paragraphs


def record_row(project, task_id, phase_id, sha, config=None):
    """Anchor the commit in the trail. Returns the file the row landed in, or False.

    A ROW BEFORE `/audit:task done` RUNS, which is what it is for. The durable
    record of a task commit is `task.commit` in the plan, written by that verb
    afterwards - so between this commit and that write there is a commit nothing
    points at, and a run that dies in the gap leaves one for ever. This row closes
    the gap and is redundant the moment the verb runs, which is the right
    direction for a record to be redundant in.

    FAIL-SOFT, `_journal_io.append`'s own contract: a commit that HAPPENED must
    not be reported as not having happened because the trail could not be written.

    `append_from_cli`, NOT `append`: this command is run from Bash, and an append
    no writer claims is reported by `guard-bash-writes` as a shell write into the
    append-only trail on the next Bash command.
    """
    config = _journal_io.load_config(project) if config is None else config
    return _journal_io.append_from_cli(project, {
        "action": ACTION_TASK_COMMITTED,
        "actor": {"sessionId": _journal_io.env_session_id(),
                  "via": "commit-task-work"},
        "target": str(task_id),
        "summary": "%s's work was committed as %s - the files the task declares, "
                   "the phase's manifest file and the records beside them"
                   % (task_id, sha[:12]),
        "details": {"commit": sha, "taskId": str(task_id),
                    "phaseId": str(phase_id)},
    }, config=config)


# --- cli ----------------------------------------------------------------------
def build_parser():
    """The argument parser, separated so a case can read the option table."""
    parser = argparse.ArgumentParser(
        prog="commit-task-work.py", add_help=True, allow_abbrev=False,
        description="Commit one task's work, staging what that task declares "
                    "and refusing the rest.")
    parser.add_argument("manifest")
    parser.add_argument("task")
    parser.add_argument("--project", default=".",
                        help="the directory holding .claude/ and the records "
                             "(default: the current directory)")
    parser.add_argument("--subject", default=None,
                        help="the commit subject after the conventional prefix; "
                             "say what the task did")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def commit_work(manifest, phase, task, manifest_path, project, git_root,
                subject=None, config=None):
    """`(exitCode, answer)` - do the thing and say what happened. Prints nothing.

    A PAIR RATHER THAN AN EXIT CODE, for `run-test-gate.run_gate`'s reason: a
    function that returned only a verdict could not be exercised without a
    terminal around it, and every branch below is a branch a case has to reach.
    """
    config = _journal_io.load_config(project) if config is None else config
    targets = stage_targets(manifest, phase, task, manifest_path, project,
                            git_root, config=config)
    allowed, skipped = targets["paths"], targets["skipped"]

    # BEFORE STAGING, so a refusal leaves the git index exactly as it was found.
    foreign, why = _scoped_commit.foreign_staged(git_root, allowed)
    if why:
        return E_FAIL, _scoped_commit.answer(skipped, refused=why)
    refusal = foreign_refusal(foreign, targets)
    if refusal:
        return E_FAIL, _scoped_commit.answer(skipped, foreign=foreign,
                                             refused=refusal)
    if not allowed:
        return E_OK, _scoped_commit.answer(skipped, quiet=NOTHING_TO_STAGE)

    # DECIDED BEFORE ANYTHING IS STAGED. The do-nothing answer is reached from
    # here with the git index untouched, so declining costs nothing and undoes
    # nothing.
    pending, why = _scoped_commit.uncommitted(git_root, allowed)
    if why:
        return E_FAIL, _scoped_commit.answer(skipped, refused=why)
    if not pending:
        return E_OK, _scoped_commit.answer(skipped, quiet=NOTHING_UNCOMMITTED)

    code, add_out, add_err = _scoped_commit.run_git(git_root,
                                                    ["add", "--"] + allowed)
    if code is None or code != 0:
        return E_FAIL, _scoped_commit.answer(
            skipped, refused="git refused to stage the task's paths (%s)"
                             % ((add_err or add_out).strip()[:200],))

    # AND THE GIT INDEX IS READ BACK, which is not belt and braces. The first pass
    # judged an index this command had not touched; this one judges the index it is
    # about to commit, and it is the only check that can see a path that arrived
    # through the `git add` rather than past it - a declared entry that is a
    # DIRECTORY is exactly such a path.
    foreign, why = _scoped_commit.foreign_staged(git_root, allowed)
    if why:
        return E_FAIL, _scoped_commit.answer(skipped, refused=why)
    refusal = foreign_refusal(foreign, targets)
    if refusal:
        return E_FAIL, _scoped_commit.answer(skipped, foreign=foreign,
                                             refused=refusal)
    code, staged_out, staged_err = _scoped_commit.run_git(
        git_root, ["diff", "--cached", "--name-only"])
    if code is None or code != 0:
        return E_FAIL, _scoped_commit.answer(
            skipped, refused="git would not list the staged paths (%s)"
                             % ((staged_err or staged_out).strip()[:200],))
    staged = _scoped_commit.lines(staged_out)

    argv_commit = ["commit"]
    for paragraph in commit_message(str(task.get("id")), subject, manifest):
        argv_commit.extend(["-m", paragraph])
    # AN EXPLICIT PATHSPEC, which is step 4c's own rule and is not redundant with
    # the allow-list above: the git index does not arrive empty, and a bare
    # `git commit` carries whatever else is in it even after both reads passed.
    argv_commit.extend(["--"] + allowed)
    code, c_out, c_err = _scoped_commit.run_git(git_root, argv_commit)
    if code is None or code != 0:
        return E_FAIL, _scoped_commit.answer(
            skipped, staged=staged,
            refused="git refused the commit (%s) - the index is still staged"
                    % ((c_err or c_out).strip()[:200],))
    code, head, head_err = _scoped_commit.run_git(git_root, ["rev-parse", "HEAD"])
    sha = head.strip() if code == 0 else ""
    if not sha:
        # The commit exists and this process cannot name it. A failure rather than
        # a success with a blank field: `/audit:task done` needs the SHA, and a
        # caller told "committed" with nothing to pass it would close the task
        # against no commit at all.
        return E_FAIL, _scoped_commit.answer(
            skipped, committed=True, staged=staged,
            refused="the commit was made and git would not print its SHA (%s), "
                    "so nothing can name it to `/audit:task done`"
                    % ((head_err or "").strip()[:200],))

    journalled = bool(record_row(project, str(task.get("id")),
                                 str(phase.get("id")), sha, config=config))
    return E_OK, _scoped_commit.answer(skipped, committed=True, commit=sha,
                                       staged=staged, journalled=journalled)


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

    phase, task = None, None
    for candidate_phase, candidate_task in _mio.iter_tasks(manifest):
        if str(candidate_task.get("id")) == str(args.task):
            phase, task = candidate_phase, candidate_task
            break
    if task is None:
        sys.stderr.write("ERROR: no task %r in %s\n" % (args.task, args.manifest))
        return E_USAGE

    project = os.path.abspath(args.project)
    git_root = _invariants.git_root_for(manifest, project)
    if not shutil.which("git"):
        out("%s git is not on PATH, so nothing can be committed at all. Nothing "
            "was staged." % (PREFIX,))
        return E_FAIL

    code, answer = commit_work(manifest, phase, task, args.manifest, project,
                               git_root, subject=args.subject)
    if args.as_json:
        out(json.dumps(answer, indent=2, sort_keys=True))
    else:
        _scoped_commit.render(answer, PREFIX, out=out)
    return code


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to a usage error, which would read
        # as a broken flag rather than as a moved suite. It deliberately does NOT
        # print the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("commit-task-work.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_commit_task_work.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
