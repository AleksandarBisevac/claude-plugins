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
(never `git add -A`), the git index is read BEFORE staging so work somebody else
had already staged cannot ride along, and it is read BACK afterwards and compared
against the same allow-list before anything is committed. A path outside the list
is NAMED in the refusal: "something is staged that should not be" sends a reader
to find it, and finding it is the step that gets skipped.

EACH PATH IS STAGED BY WHAT GIT HOLDS FOR IT, because one `git add -- <path>...`
over the whole list is wrong three ways (measured on git 2.50.1):

  * a path in the INDEX is staged with `git add -u --`. `git add --` naming a
    tracked file under a gitignored directory exits 1 AND stages it, so the
    plain call reports a refusal over an index it has already changed;
  * a path on disk and NOT in the index is staged with `git add --`, and the
    ignore rule is honoured for exactly these: one git ignores is refused before
    anything is staged, by name, and `-f` is never passed - forcing past an
    ignore rule is the operator's decision;
  * a path in HEAD ALONE - the source of a staged `git mv`, or a staged `git rm`
    - is in neither call, because both fail 128 on it, and it stays in the
    commit's pathspec, which is what records the rename (`R100`) or the
    deletion. Skipping it would commit the new name beside the old one: a copy.

A declared path in none of the three - the case the red-first workflow names
before writing it - is reported and passed over, since a pathspec matching
nothing fails the whole staging call.

A REFUSAL LEAVES THE INDEX AS IT WAS FOUND, AND AFTER STAGING THAT TAKES WORK.
Every refusal reached before staging touches nothing. For the ones after it - git
refusing the staging call, a path arriving through it, a commit a hook refuses -
the index is written to a tree first (`git write-tree`) and the allowed paths are
reset to that tree (`git reset <tree> -- <paths>`), which restores an entry the
operator had staged at its own bytes rather than merely unstaging it.

BOUND TO THE VERDICT IT WAS MEASURED UNDER. `reference/execute-task.md` records
the task's gate (`run-test-gate.py --task <id> --record`) before this commit, and
the row it writes carries `testedState.scopeDigest` - `_tree_stamp`'s digest of
the declared files as the gate read them. So this refuses unless the task's
NEWEST row is `passed` and that digest still matches the declared files it is
about to commit. HEAD and the dirty-path digest are deliberately not compared:
a sibling task committing between this task's gate and its commit moves both, and
that is the ordinary parallel run rather than stale work. A task nothing can
measure - its own `tests.gate` and its phase's `testGate` both empty - gets no row
from the recorder at all, so it commits and says it is bound to no verdict.
`--override-verdict <reason>` commits anyway and leaves a journal row naming the
run it went over and the reason; it is refused while the journal is off, because
an override recorded nowhere is a gate quietly removed.

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
                      [--override-verdict REASON] [--json]

Exit codes:
  0  it ran - it committed, or there was nothing to commit and it said which
  1  it could not - git refused, the git index already held paths this commit
     may not carry (each one named), a declared file is ignored, or the task's
     newest gate verdict is not `passed` on the work being committed
  2  usage error - the manifest will not load, there is no such task, or an
     override carries no reason

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
import _tree_stamp  # noqa: E402  (the declared-work digest a gate row records, recomputed here)

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

# What git holds for one allowed path, which decides how it is staged: `git add
# -u` for an index entry, `git add` for a path only on disk, neither for a path
# only in HEAD (the commit's pathspec records it), and a refusal for a path on
# disk that git ignores.
IN_INDEX = "index"
ON_DISK = "disk"
HEAD_ONLY = "head"
IGNORED = "ignored"

# The words an ignored declared path is named with. Ends the sentence rather than
# opening it so the path comes first; the decision it hands back is the whole
# content - `-f` is never passed here.
IGNORED_HINT = "ignored; -f is yours to decide"

# What a refusal after staging says when the index was put back, and the other
# sentence when it could not be. Different repairs: one leaves nothing to undo,
# the other names what is still staged.
INDEX_RESTORED = "the git index was put back exactly as it was found"
INDEX_NOT_RESTORED = ("and the git index could NOT be put back (%s), so what "
                      "this command staged is still staged: %s")

# The trail's word for a commit made over a verdict that would have refused it.
# Local for `ACTION_TASK_COMMITTED`'s reason: nothing outside this file reads it.
ACTION_VERDICT_OVERRIDDEN = "audit.task.verdict-overridden"

# The one status a commit is bound to without an override.
VERDICT_PASSED = "passed"

# A task with nothing to measure it. Said on every such commit, because a silent
# commit here reads exactly like one a green gate stood behind.
NO_GATE = ("no gate measures this task - neither its own `tests.gate` nor its "
           "phase's `testGate` declares an entry, so the recorder writes no "
           "verdict for it and this commit is bound to none; sign-off rests on "
           "review alone")


# --- what this commit may carry -----------------------------------------------
def _named(git_root, args, paths, nul=True):
    """The paths git prints for `args -- paths`, or None when git will not say.

    NUL-separated (`-z`) where the command allows it, so a path git would
    otherwise quote comes back verbatim; `check-ignore` takes `-z` only with
    `--stdin`, so it is read by line, and a path it quotes then fails to match
    and is left to `git add`, which applies the ignore rule itself. None rather
    than an empty list for `_scoped_commit.foreign_staged`'s reason: "git named
    nothing" is an answer and "git could not be asked" is not.
    """
    code, out, _err = _scoped_commit.run_git(
        git_root, list(args) + (["-z"] if nul else []) + ["--"] + list(paths))
    if code is None or code != 0:
        return None
    if not nul:
        return _scoped_commit.lines(out)
    return [f.replace("\\", "/") for f in out.split("\0") if f]


def _covering(listed, paths):
    """The subset of `paths` that is, or holds, an entry of `listed`.

    A declared entry may be a DIRECTORY, and git lists what is inside it rather
    than the directory itself, so equality alone would call a tracked directory
    untracked.
    """
    return set(p for p in paths
               if any(_invariants._under(entry, p) for entry in listed))


def _in_head(git_root, paths):
    """The subset of `paths` HEAD holds, or None when that is not established.

    A repository with no commit yet has an unborn HEAD, and there `ls-tree`
    fails; that is an answer - nothing is in HEAD - rather than an unknown, so
    it is asked for separately instead of being folded into the failure arm.
    """
    listed = _named(git_root, ["ls-tree", "-r", "--name-only", "HEAD"], paths)
    if listed is not None:
        return _covering(listed, paths)
    code, _out, _err = _scoped_commit.run_git(
        git_root, ["rev-parse", "--verify", "-q", "HEAD"])
    return set() if code == 1 else None


def classify(git_root, entries):
    """`{rel: kind}` for `(rel, on_disk)` pairs; a path git holds nowhere is absent.

    The kinds are `IN_INDEX`, `ON_DISK`, `HEAD_ONLY` and `IGNORED`, and the module
    docstring says what each is staged with. An EXACT index entry is `IN_INDEX`;
    a path on disk that is not one - an untracked file, or a directory - is
    `ON_DISK` unless git ignores it. A path not on disk is `IN_INDEX` when the
    index still holds it (an unstaged deletion) and `HEAD_ONLY` when only HEAD
    does.

    EVERY UNCERTAIN ANSWER IS THE ONE THAT SKIPS NOTHING, which is the loud
    direction: an index git will not list reads as holding everything, so the
    staging call below fails and says why; a HEAD it will not list keeps an
    absent path in the pathspec, where the commit refuses a path git does not
    know; an ignore check it will not answer leaves the path to `git add`, which
    applies the rule itself. The other direction drops a path and commits a
    subset of the work while reporting success.
    """
    rels = [rel for rel, _on_disk in entries]
    if not rels:
        return {}
    index = _named(git_root, ["ls-files"], rels)
    exact = set(rels) if index is None else set(index)
    held = set(rels) if index is None else _covering(index, rels)
    kinds, loose, absent = {}, [], []
    for rel, on_disk in entries:
        if on_disk:
            if rel in exact:
                kinds[rel] = IN_INDEX
            else:
                loose.append(rel)
        elif rel in held:
            kinds[rel] = IN_INDEX
        else:
            absent.append(rel)
    if loose:
        ignored = _named(git_root, ["check-ignore"], loose,
                         nul=False) or []
        for rel in loose:
            kinds[rel] = IGNORED if rel in ignored else ON_DISK
    if absent:
        head = _in_head(git_root, absent)
        for rel in absent:
            if head is None or rel in head:
                kinds[rel] = HEAD_ONLY
    return kinds


def stage_targets(manifest, phase, task, manifest_path, project, git_root,
                  config=None):
    """`{"paths", "declared", "kinds", "ignored", "skipped", "indexRel"}` - the
    allow-list, resolved.

    `paths` are git-root-relative and are the ONLY thing anything downstream may
    stage or commit; `declared` is the subset that came from the task's own
    `files`, kept apart so the refusal can say which half of the list a path
    failed against; `kinds` is `classify`'s answer for each of `paths`, which is
    how each is staged; `ignored` holds the declared paths git ignores, kept out
    of `paths` because nothing may stage them; `skipped` carries one sentence per
    entry that could not be reached; `indexRel` is the manifest index, carried so
    the refusal can name it as the specific mistake it is rather than as one more
    stray path.

    THE LIST IS THE SAFETY PROPERTY, exactly as it is in the other two scoped
    commits. Nothing downstream widens it - the staging calls take these paths and
    both index verifications take this same list - so a sibling file the editor
    happened to touch has no route into the commit even while it sits modified in
    the working tree beside them.

    A `:line-range` SUFFIX IS STRIPPED. `files` entries may carry one and git has
    never heard of it; staging `a/b.py:10-20` would either fail or, worse, create
    a pathspec that matches nothing and leave the real file uncommitted.
    """
    config = _journal_io.load_config(project) if config is None else config
    index_abs, phase_file_abs = _invariants.manifest_files(manifest_path, phase)
    candidates, skipped = [], []

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
        candidates.append((rel, name, os.path.exists(absolute), True))

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
        if rel not in [c[0] for c in candidates]:
            candidates.append((rel, label, True, False))

    # ONE CLASSIFICATION FOR THE WHOLE LIST, asked of git in a fixed number of
    # calls rather than one per path, so a task declaring many files does not pay
    # a process apiece.
    kinds = classify(git_root, [(rel, on_disk)
                                for rel, _name, on_disk, _mine in candidates])
    paths, declared, ignored = [], [], []
    for rel, name, _on_disk, mine in candidates:
        kind = kinds.get(rel)
        if kind is None:
            skipped.append("%s %s is neither in the working tree nor tracked by "
                           "git, so there is nothing of it to commit yet"
                           % (DECLARED_LABEL, name))
            continue
        if kind == IGNORED:
            ignored.append(rel)
            continue
        paths.append(rel)
        if mine:
            declared.append(rel)

    index_rel = _invariants._rel(index_abs, git_root)
    if index_rel is not None and os.path.abspath(index_abs) == os.path.abspath(
            phase_file_abs):
        # The single-file layout: the manifest IS the index, and step 4c's "do NOT
        # stage the index" is about the SHARDED index a parallel phase would
        # conflict on. Naming it here would refuse the manifest this commit is
        # required to carry.
        index_rel = None
    return {"paths": paths, "declared": declared,
            "kinds": dict((rel, kinds[rel]) for rel in paths),
            "ignored": ignored, "skipped": skipped, "indexRel": index_rel}


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


def ignored_refusal(ignored):
    """The sentence an ignored path in the allow-list earns, naming each, or None."""
    if not ignored:
        return None
    return ("%s - %s. A path git ignores is staged only with `git add -f`, and "
            "this command never passes it; add it yourself if it really is this "
            "task's work, or drop it from the task's `files`. Nothing was staged"
            % (", ".join(ignored), IGNORED_HINT))


# --- the verdict the work was measured under ------------------------------------
def _newest(rows):
    """The newest row by `ts`, a later row winning a tie, or None.

    BY `ts` AND NOT BY FILE ORDER, `_evidence_io.latest_by_subject`'s rule: rows
    land in one file per writer per month, so the concatenation of the ledger is
    in no meaningful order. A tie goes to the row read later, which within one
    writer's file is the row appended later.
    """
    best = None
    for row in rows:
        if best is None or str(row.get("ts") or "") >= str(best.get("ts") or ""):
            best = row
    return best


def verdict_binding(manifest_path, phase, task, project, config=None):
    """`{"state", "sentence", "row"}` - whether the task's newest verdict binds
    this commit.

    `state` is `"bound"` (a `passed` row whose declared-work digest matches the
    declared files now), `"no-gate"` (nothing declares a gate, so no row can
    exist) or `"refused"`; `sentence` says which, naming the run; `row` is the
    newest row for the task when there is one, so an override can name it.

    THE TASK'S ROWS ARE THE ONES CARRYING ITS ID, whatever their `scope`. A task
    with no gate of its own is measured by its phase's under `--task`, and that
    row reads `scope: phase` beside the task id; a sign-off run carries no task
    id and is not this task's verdict. `_evidence_io._same_subject` is that rule.

    A REPEATED VERDICT IS GRADED AGAINST THE RUN THAT MEASURED IT. A row the
    recorder repeated carries no `testedState` of its own and names its source
    in `reusedFrom`; the repeat was only made because the tree's content matched
    that run's, so the source's digest is the one that describes these bytes.

    AN UNREADABLE LEDGER LINE REFUSES, because it may be the newest row: a
    verdict read around a line that could not be read is not the newest verdict.
    """
    config = _journal_io.load_config(project) if config is None else config
    entries, _source = _mio.gate_entries(phase, task)
    task_id, phase_id = str(task.get("id")), str(phase.get("id"))
    if not entries:
        return {"state": "no-gate", "sentence": NO_GATE, "row": None}
    record = ("run `run-test-gate.py %s %s --task %s --record` on the work, then "
              "commit" % (manifest_path, phase_id, task_id))
    ledger = _evidence_io.read_rows(project, config)
    if ledger["unreadable"]:
        return {"state": "refused", "row": None, "sentence": (
            "%d line(s) of the evidence ledger could not be read, and one of "
            "them may be %s's newest verdict, so the verdict this commit stands "
            "under is not established" % (ledger["unreadable"], task_id))}
    ids = {"taskId": task_id, "phaseId": phase_id}
    rows = [r for r in ledger["rows"]
            if isinstance(r, dict) and _evidence_io._same_subject(r, ids)]
    newest = _newest(rows)
    if newest is None:
        return {"state": "refused", "row": None, "sentence": (
            "no gate verdict is recorded for %s, and its gate declares entries "
            "- %s" % (task_id, record))}
    run = "run %s at %s" % (newest.get("runId"), newest.get("ts"))
    if newest.get("status") != VERDICT_PASSED:
        return {"state": "refused", "row": newest, "sentence": (
            "%s's newest gate verdict is `%s` (%s), and a task commit is bound "
            "to `%s` - the gate is what decides the task is done. Fix the work "
            "and %s" % (task_id, newest.get("status"), run, VERDICT_PASSED,
                        record))}
    measured = newest
    if newest.get(_evidence_io.VERDICT_SOURCE) == _evidence_io.REUSED:
        source = (newest.get("reusedFrom") or {}).get("runId")
        found = [r for r in ledger["rows"]
                 if isinstance(r, dict) and source and r.get("runId") == source]
        measured = found[-1] if found else None
        if measured is None:
            return {"state": "refused", "row": newest, "sentence": (
                "%s's newest verdict (%s) repeats run %s, which is not in the "
                "ledger, so the tree it was measured on is not established - %s"
                % (task_id, run, source, record))}
    owns = list(task.get("files") or [])
    was = (measured.get("testedState") or {}).get("scopeDigest")
    now, basis = _tree_stamp.scope_digest(project, owns)
    field = _tree_stamp.field_state("scopeDigest", was, now,
                                    bool(_tree_stamp.declared_scope(owns)))
    if field == _tree_stamp.MOVED:
        return {"state": "refused", "row": newest, "sentence": (
            "%s's newest verdict is `%s` (%s), but the declared files have "
            "changed since it was measured - scopeDigest was %s and is %s now "
            "(%s). The green is about bytes this commit would not carry; %s"
            % (task_id, VERDICT_PASSED, run, was, now, basis, record))}
    if field == _tree_stamp.UNANSWERABLE:
        return {"state": "refused", "row": newest, "sentence": (
            "%s's newest verdict is `%s` (%s), and whether it was measured on "
            "the declared files as they stand is not established - scopeDigest "
            "was %s and is %s now (%s); %s"
            % (task_id, VERDICT_PASSED, run, was, now, basis, record))}
    if field == _tree_stamp.NOT_DECLARED:
        return {"state": "bound", "row": newest, "sentence": (
            "bound to %s (`%s`); the task declares no files, so the verdict word "
            "is bound and no declared-work digest could be" % (run,
                                                                VERDICT_PASSED))}
    return {"state": "bound", "row": newest, "sentence": (
        "bound to %s (`%s`) - the declared-work digest it recorded matches the "
        "declared files being committed. %s" % (run, VERDICT_PASSED,
                                                _tree_stamp.SCOPE_LIMIT))}


def override_row(project, task_id, phase_id, sha, verdict, reason, config=None):
    """The trail row a commit made over its verdict leaves. Returns the file, or False.

    It names the commit, the run it went over (when there was one) and the
    operator's reason, so the override is findable by any of the three.
    """
    config = _journal_io.load_config(project) if config is None else config
    details = {"commit": sha, "taskId": str(task_id), "phaseId": str(phase_id),
               "reason": reason}
    row = verdict.get("row") or {}
    if row.get("runId"):
        details["runId"] = str(row["runId"])
    return _journal_io.append_from_cli(project, {
        "action": ACTION_VERDICT_OVERRIDDEN,
        "actor": {"sessionId": _journal_io.env_session_id(),
                  "via": "commit-task-work"},
        "target": str(task_id),
        "summary": "%s was committed as %s over the verdict that refused it: %s"
                   % (task_id, sha[:12], verdict.get("sentence")),
        "details": details,
    }, config=config)


# --- putting the index back ---------------------------------------------------
def index_snapshot(git_root):
    """`(tree, why)` - the git index written as a tree, so it can be restored.

    Taken before the first staging call. `write-tree` refuses an index with
    unmerged entries, and then nothing is staged at all: a staging this command
    could not undo is not one it may start.
    """
    code, out, err = _scoped_commit.run_git(git_root, ["write-tree"])
    if code is None or code != 0 or not out.strip():
        return None, ("git would not write the index as a tree (%s), so a "
                      "failed staging could not be undone - nothing was staged"
                      % ((err or out).strip()[:200],))
    return out.strip(), ""


def restore_index(git_root, tree, paths):
    """`""` when every path in `paths` is back at its `tree` entry, else why not.

    `git reset <tree> -- <paths>` and not a plain unstage: an entry the operator
    had staged before this ran - an edit at bytes older than the working tree's,
    a `git mv` - is put back at those bytes, and a path this command added is
    removed again. Only the allowed paths are named, so whatever anybody else
    staged meanwhile is left alone.
    """
    code, out, err = _scoped_commit.run_git(git_root,
                                            ["reset", "-q", tree, "--"]
                                            + list(paths))
    if code is None or code != 0:
        return (err or out).strip()[:200] or "git reset exited %r" % (code,)
    return ""


def after_staging(git_root, tree, paths, skipped, refused, staged=None):
    """The answer for a failure after staging: the index restored, and saying so."""
    why = restore_index(git_root, tree, paths)
    tail = INDEX_RESTORED if not why else INDEX_NOT_RESTORED % (
        why, ", ".join(paths))
    return E_FAIL, _scoped_commit.answer(skipped, staged=staged,
                                         refused="%s - %s" % (refused, tail))


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
    parser.add_argument("--override-verdict", default=None, dest="override",
                        metavar="REASON",
                        help="commit even though the task's newest gate verdict "
                             "is not `passed` on this work; the reason is "
                             "written to the journal with the commit")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _stage(git_root, targets):
    """`""` when every allowed path was staged by the call its kind needs, else
    git's own words.

    Two calls at most, `git add -u` for index entries and `git add` for paths
    only on disk; a `HEAD_ONLY` path is in neither and reaches the commit through
    its pathspec alone. The module docstring says why each.
    """
    kinds = targets["kinds"]
    for argv, kind in ((["add", "-u", "--"], IN_INDEX), (["add", "--"], ON_DISK)):
        group = [rel for rel in targets["paths"] if kinds.get(rel) == kind]
        if not group:
            continue
        code, out, err = _scoped_commit.run_git(git_root, argv + group)
        if code is None or code != 0:
            return "`git %s` refused (%s)" % (" ".join(argv[:-1]),
                                              (err or out).strip()[:200])
    return ""


def commit_work(manifest, phase, task, manifest_path, project, git_root,
                subject=None, config=None, override=None):
    """`(exitCode, answer)` - do the thing and say what happened. Prints nothing.

    A PAIR RATHER THAN AN EXIT CODE, for `run-test-gate.run_gate`'s reason: a
    function that returned only a verdict could not be exercised without a
    terminal around it, and every branch below is a branch a case has to reach.

    `answer` is `_scoped_commit.answer`'s shape plus `verdict`, the
    `verdict_binding` this commit was decided under (None when it never got that
    far) and `overridden`, whether it was committed over that verdict.
    """
    config = _journal_io.load_config(project) if config is None else config
    code, answer = _commit_work(manifest, phase, task, manifest_path, project,
                                git_root, subject, config, override)
    answer.setdefault("verdict", None)
    answer.setdefault("overridden", False)
    return code, answer


def _commit_work(manifest, phase, task, manifest_path, project, git_root,
                 subject, config, override):
    targets = stage_targets(manifest, phase, task, manifest_path, project,
                            git_root, config=config)
    allowed, skipped = targets["paths"], targets["skipped"]
    task_id, phase_id = str(task.get("id")), str(phase.get("id"))

    # BEFORE STAGING, so a refusal leaves the git index exactly as it was found.
    foreign, why = _scoped_commit.foreign_staged(git_root, allowed)
    if why:
        return E_FAIL, _scoped_commit.answer(skipped, refused=why)
    refusal = foreign_refusal(foreign, targets)
    if refusal:
        return E_FAIL, _scoped_commit.answer(skipped, foreign=foreign,
                                             refused=refusal)
    # AHEAD OF BOTH DO-NOTHING ANSWERS: `git status` does not list an ignored
    # file, so an ignored declared file alone would otherwise read as "nothing
    # uncommitted" over work that is sitting right there.
    refusal = ignored_refusal(targets["ignored"])
    if refusal:
        return E_FAIL, _scoped_commit.answer(skipped, refused=refusal)
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

    # THE VERDICT, still before staging: a refusal here has nothing to undo.
    verdict = verdict_binding(manifest_path, phase, task, project, config=config)
    overriding = verdict["state"] == "refused" and override is not None
    if verdict["state"] == "refused" and not overriding:
        answer = _scoped_commit.answer(skipped, refused=(
            "%s. `--override-verdict <reason>` commits anyway and records the "
            "reason in the journal" % (verdict["sentence"],)))
        answer["verdict"] = verdict
        return E_FAIL, answer
    if overriding and not _journal_io.enabled(config):
        answer = _scoped_commit.answer(skipped, refused=(
            "`--override-verdict` was given and journal.enabled is false, so the "
            "override would be recorded nowhere - an override nobody can find "
            "afterwards is a gate quietly removed. The verdict: %s"
            % (verdict["sentence"],)))
        answer["verdict"] = verdict
        return E_FAIL, answer
    if verdict["state"] == "no-gate":
        skipped = skipped + [verdict["sentence"]]

    tree, why = index_snapshot(git_root)
    if why:
        return E_FAIL, _scoped_commit.answer(skipped, refused=why)
    why = _stage(git_root, targets)
    if why:
        return after_staging(git_root, tree, allowed, skipped,
                             "git refused to stage the task's paths: %s"
                             % (why,))

    # AND THE GIT INDEX IS READ BACK, which is not belt and braces. The first pass
    # judged an index this command had not touched; this one judges the index it is
    # about to commit, and it is the only check that can see a path that arrived
    # through the `git add` rather than past it - a declared entry that is a
    # DIRECTORY is exactly such a path.
    foreign, why = _scoped_commit.foreign_staged(git_root, allowed)
    if why:
        return after_staging(git_root, tree, allowed, skipped, why)
    refusal = foreign_refusal(foreign, targets)
    if refusal:
        code, answer = after_staging(git_root, tree, allowed, skipped, refusal)
        answer["foreign"] = list(foreign)
        return code, answer
    # `--no-renames` so the report names BOTH halves of a staged rename; with
    # rename detection on, git lists the new name alone and the source a
    # `HEAD_ONLY` path contributes would be missing from what is printed.
    code, staged_out, staged_err = _scoped_commit.run_git(
        git_root, ["diff", "--cached", "--name-only", "--no-renames"])
    if code is None or code != 0:
        return after_staging(git_root, tree, allowed, skipped,
                             "git would not list the staged paths (%s)"
                             % ((staged_err or staged_out).strip()[:200],))
    staged = _scoped_commit.lines(staged_out)

    argv_commit = ["commit"]
    for paragraph in commit_message(task_id, subject, manifest):
        argv_commit.extend(["-m", paragraph])
    # AN EXPLICIT PATHSPEC, which is step 4c's own rule and is not redundant with
    # the allow-list above: the git index does not arrive empty, and a bare
    # `git commit` carries whatever else is in it even after both reads passed. It
    # is also the only route a `HEAD_ONLY` path has into the commit.
    argv_commit.extend(["--"] + allowed)
    code, c_out, c_err = _scoped_commit.run_git(git_root, argv_commit)
    if code is None or code != 0:
        return after_staging(git_root, tree, allowed, skipped,
                             "git refused the commit (%s)"
                             % ((c_err or c_out).strip()[:200],), staged=staged)
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

    journalled = bool(record_row(project, task_id, phase_id, sha, config=config))
    answer = _scoped_commit.answer(skipped, committed=True, commit=sha,
                                   staged=staged, journalled=journalled)
    answer["verdict"] = verdict
    if not overriding:
        return E_OK, answer
    answer["overridden"] = True
    if override_row(project, task_id, phase_id, sha, verdict, override,
                    config=config):
        return E_OK, answer
    # THE COMMIT HAPPENED AND ITS OVERRIDE IS ON NO RECORD. Exit 1 with the SHA
    # still reported, `rev-parse`'s arm above: the operator is owed the one fact
    # the flag promised, and a success here would be a commit over a red verdict
    # that nothing points at.
    answer["refused"] = ("committed %s over the verdict that refused it, and the "
                         "journal row recording the override could NOT be "
                         "written - nothing in the trail says this commit went "
                         "over its gate. The verdict: %s"
                         % (sha[:12], verdict["sentence"]))
    return E_FAIL, answer


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

    override = args.override
    if override is not None and not override.strip():
        sys.stderr.write("ERROR: --override-verdict needs a reason - it is the "
                         "whole of what the journal row records\n")
        return E_USAGE
    code, answer = commit_work(manifest, phase, task, args.manifest, project,
                               git_root, subject=args.subject,
                               override=override.strip() if override else None)
    if args.as_json:
        out(json.dumps(answer, indent=2, sort_keys=True))
        return code
    _scoped_commit.render(answer, PREFIX, out=out)
    verdict = answer.get("verdict") or {}
    if answer.get("committed") and not answer.get("refused"):
        if answer.get("overridden"):
            out("  verdict: OVERRIDDEN, and the journal records it with the "
                "reason given - %s" % (verdict.get("sentence"),))
        elif verdict.get("state") == "bound":
            out("  verdict: %s" % (verdict.get("sentence"),))
            if override is not None:
                out("  --override-verdict was given and not needed: the verdict "
                    "binds this commit, so no override was recorded")
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
