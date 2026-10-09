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
carries the shared index and the one journal file holding the row that names
the commit, and nothing else; this one carries the WORK. Each
derives its own allow-list and none of them shares a builder, because a shared
builder taking a flag would be one function holding three safety properties -
the shape in which a widened list stops being noticed. What they do share is
`_scoped_commit`: how each path is staged, the two index reads, the pathspec'd
commit, putting the index back on a refusal, and the answer shape, so no two of
them can disagree about what "refused" means.

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

EACH PATH IS STAGED BY WHAT GIT HOLDS FOR IT - `_scoped_commit.classify`, whose
comment block says what each kind is staged with and why a single `git add --
<path>...` is wrong for it. The consequences a caller sees: the source of a staged
`git mv` or `git rm` is committed as the rename or deletion it is; a tracked file
under a gitignored directory is staged as the tracked file it is; an untracked
declared file git ignores is refused by name before anything is staged, `-f`
being the operator's decision; and a file taken out of the index with `git rm
--cached` and then ignored is committed as the deletion the operator made. A
declared path git holds nowhere - the case the red-first workflow names before
writing it - is reported and passed over.

A REFUSAL LEAVES THE INDEX AS IT WAS FOUND. Every refusal reached before staging
touches nothing; every one after it puts the allowed paths' index entries back
from a snapshot (`_scoped_commit.snapshot`), including an entry the operator had
staged at its own bytes, a conflict's stages and an intent-to-add path.

BOUND TO THE VERDICT IT WAS MEASURED UNDER. `reference/execute-task.md` records
the task's gate (`run-test-gate.py --task <id> --record`) before this commit, and
the row it writes carries `testedState.scopeDigest` - `_tree_stamp`'s digest of
the declared files as the gate read them - and `scopeListDigest`, the digest of
the declared list itself. So this refuses unless the task's NEWEST row is
`passed`, was measured under the gate the task declares now, and its digest
still matches the declared files it is about to commit; a changed LIST is told
apart from changed CONTENT in the refusal. Both sides compute the digest through
`_tree_stamp.scope_digest` over the same normalised scope with the same record
paths left out, so a `:line-range` entry, a directory entry and a task that
declares its own manifest file are all compared on the bytes they name. HEAD and
the dirty-path digest are deliberately not compared: a sibling task committing
between this task's gate and its commit moves both, and that is the ordinary
parallel run rather than stale work. A task nothing can measure - a task gate
cleared on purpose (`gateBasis: cleared`), or its own `tests.gate` and its
phase's `testGate` both empty (`_manifest_io.gate_entries`) - commits and says
it is bound to no verdict, in a sentence that says which of the two it is,
unless a red was recorded under its gate after the last green - neither
emptying the gate nor the `empty-gate` row `--record` then writes retires that
red. With no such red, the `empty-gate` row is the gate's recorded answer and
binds it, and the same row under a gate that has entries now is a gate changed
after the measurement and is refused. "Measured under the gate" is the row's
steps, their dropped count, and its `gateDigest` of what each entry resolves to.
`--override-verdict <reason>` commits anyway and leaves a journal row naming the
run it went over and the reason; it is refused while the journal is off, because
an override recorded nowhere is a gate quietly removed.

WHY IT DOES NOT WRITE `task.commit`. The SHA is only knowable after the commit
this makes, and the shard is inside that commit - so writing it here would need a
second commit or an amend, and `orchestrator.md` forbids the amend. The SHA is
printed instead and `/audit:task done <taskId> --commit <sha>` records it, riding
along with the next commit exactly as step 4c already says. Two verbs, one each
for the thing git owns and the thing the plan owns.

THE ROW NAMING THE COMMIT IS INSIDE IT. `audit.task.committed` - and, for an
override, the row recording it - is written before the commit, keyed by the
nonce the commit message carries as its `Audit-Row` trailer, and carried by the
commit through the journal directory on the allow-list
(`_scoped_commit.commit_with_rows`). An override whose row cannot be written is
refused before anything is staged, so no commit goes over its gate unrecorded;
a commit refused after the rows were written leaves a row withdrawing them.

NEVER AN EMPTY COMMIT. Nothing staged means no commit and a line saying so,
because a stream of empty commits is how a record stops being read.

Usage:
  commit-task-work.py <manifest> <taskId> [--project DIR] [--subject TEXT]
                      [--override-verdict REASON] [--json]

Exit codes:
  0  it ran - it committed, or there was nothing to commit and it said which
  1  it could not - git refused, the git index already held paths this commit
     may not carry (each one named), a declared file or a record path is
     ignored, the index could not be read to be put back, or the task's newest
     gate verdict does not bind the work being committed
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

import _claude_home  # noqa: E402  (a usage error names this copy and a newer installed one)
import _evidence_io  # noqa: E402  (where the evidence ledger lives)
import _filed_returns  # noqa: E402  (the executor's filed return, for its `claims`)
import _invariants  # noqa: E402  (the git root, the manifest file pair, the under-test)
import _journal_io  # noqa: E402  (where the trail lives, and the append)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR shards)
import _manifest_vocab as _vocab  # noqa: E402  (one reading of a `files` entry's line suffix)
import _scoped_commit  # noqa: E402  (the staging discipline and the answer shape, shared with the other two scoped commits)
import _verdict_binding as _vb  # noqa: E402  (the one rule for whether a recorded verdict binds the work)

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

# The words an ignored declared path is named with. Ends the sentence rather than
# opening it so the path comes first; the decision it hands back is the whole
# content - `-f` is never passed here.
IGNORED_HINT = "ignored; -f is yours to decide"

# Shared with the other scoped commits, re-exported so a reader of this command's
# output finds the sentence it printed here.
INDEX_RESTORED = _scoped_commit.INDEX_RESTORED

# The trail's word for a commit made over a verdict that would have refused it.
# Local for `ACTION_TASK_COMMITTED`'s reason: nothing outside this file reads it.
ACTION_VERDICT_OVERRIDDEN = "audit.task.verdict-overridden"

# The one status a commit is bound to without an override, and the status
# `run-test-gate.py --record` writes for a gate that declares no command (its
# `EMPTY_GATE`; a case pins the two spellings equal) - the binding rule's own
# words, re-exported so a reader of this command's output finds them here.
VERDICT_PASSED = _vb.VERDICT_PASSED
VERDICT_EMPTY_GATE = _vb.VERDICT_EMPTY_GATE

# A task with nothing to measure it. Said on every such commit, because a silent
# commit here reads exactly like one a green gate stood behind.
NO_GATE = ("no gate measures this task - neither its own `tests.gate` nor its "
           "phase's `testGate` declares an entry, so this commit is bound to no "
           "verdict; sign-off rests on review alone")

# A task whose gate was cleared ON PURPOSE (`gateBasis: cleared`). Its own
# sentence, because the phase may still declare entries - `NO_GATE` would be
# false there. `%s` says what grades it at sign-off.
CLEARED_GATE = ("its task gate was cleared on purpose (`gateBasis: cleared`), "
                "so no gate of its own measures it and this commit is bound to "
                "no verdict; %s")

# The command that shows an unreadable ledger line for what it is.
VERIFY_COMMAND = _vb.VERIFY_COMMAND


# --- what this commit may carry -----------------------------------------------
def stage_targets(manifest, phase, task, manifest_path, project, git_root,
                  config=None):
    """The allow-list, resolved: `{"paths", "declared", "kinds", "ignored",
    "ignoredRecords", "skipped", "indexRel"}`.

    `paths` are git-root-relative and are the ONLY thing anything downstream may
    stage or commit; `declared` is the subset that came from the task's own
    `files`, kept apart so the refusal can say which half of the list a path
    failed against; `kinds` is `_scoped_commit.classify`'s answer for each of
    `paths`, which is how each is staged; `ignored` and `ignoredRecords` hold the
    declared paths and the record paths git ignores, kept out of `paths` because
    nothing may stage them and apart from each other because their repairs
    differ; `skipped` carries one sentence per entry that could not be reached;
    `indexRel` is the manifest index, carried so the refusal can name it as the
    specific mistake it is rather than as one more stray path.

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
            # A journal that does not exist yet is created by the row this
            # commit writes and carried from there, so it is not a skip.
            if not (label == JOURNAL_LABEL and _journal_io.enabled(config)):
                skipped.append("%s does not exist yet, so there is nothing of it "
                               "to stage" % (label,))
            continue
        if rel not in [c[0] for c in candidates]:
            candidates.append((rel, label, True, False))

    # ONE CLASSIFICATION FOR THE WHOLE LIST, asked of git in a fixed number of
    # calls rather than one per path, so a task declaring many files does not pay
    # a process apiece.
    kinds = _scoped_commit.classify(
        git_root, [(rel, on_disk) for rel, _name, on_disk, _mine in candidates])
    paths, declared, ignored, ignored_records = [], [], [], []
    for rel, name, on_disk, mine in candidates:
        kind = kinds.get(rel)
        if kind is None and on_disk:
            skipped.append("%s is a directory holding no file git would "
                           "commit - nothing tracked, and nothing untracked "
                           "that git does not ignore - so there is nothing of "
                           "it to commit"
                           % ("%s %s" % (DECLARED_LABEL, name) if mine
                              else name,))
            continue
        if kind is None:
            skipped.append("%s %s is neither in the working tree nor tracked by "
                           "git, so there is nothing of it to commit yet"
                           % (DECLARED_LABEL, name))
            continue
        if kind == _scoped_commit.IGNORED:
            if mine:
                ignored.append(rel)
            else:
                ignored_records.append((name, rel))
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
            "ignored": ignored, "ignoredRecords": ignored_records,
            "skipped": skipped, "indexRel": index_rel}


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
            "are its work - and a widened scope is a new declared scope, so "
            "record the gate again before committing" % (", ".join(foreign),))


def ignored_refusal(ignored, ignored_records):
    """The sentence the ignored paths in the allow-list earn, naming each, or None.

    A DECLARED path and a RECORD path are worded apart because the repairs are
    opposite: a declared file may simply not be the task's work, while a record
    this commit is required to carry cannot be dropped - it has to be
    un-ignored.
    """
    parts = []
    if ignored:
        parts.append("%s - %s. A path git ignores is staged only with `git add "
                     "-f`, and this command never passes it; add it yourself if "
                     "it really is this task's work, or drop it from the task's "
                     "`files`" % (", ".join(ignored), IGNORED_HINT))
    if ignored_records:
        parts.append("%s - git ignores it, and it is a record this commit is "
                     "required to carry, so dropping it is not the repair: "
                     "remove the `.gitignore` rule that matches it (`git "
                     "check-ignore -v %s` names the rule)"
                     % ("; ".join("%s (%s)" % (label, rel)
                                  for label, rel in ignored_records),
                        ignored_records[0][1]))
    if not parts:
        return None
    return "%s. Nothing was staged" % (". ".join(parts),)


# --- the verdict the work was measured under ------------------------------------
def verdict_binding(manifest_path, phase, task, project, config=None,
                    manifest=None):
    """`{"state", "sentence", "row", "notes"}` - whether the task's newest verdict
    binds this commit: `_verdict_binding.binding` over the task's ids, the gate
    that measures it and its declared files. The rule is that module's and is
    shared with `audit-task.py signoff`; what is this command's own is the task's
    words - which gate measures it, the run that would supply a verdict, and the
    sentence for a task no gate measures.

    THE TASK'S ROWS ARE THE ONES CARRYING ITS ID, whatever their `scope`. A task
    with no gate of its own is measured by its phase's under `--task`, and that
    row reads `scope: phase` beside the task id; a sign-off run carries no task
    id and is not this task's verdict.

    WHICH EMPTY GATE IS SAID IN ITS OWN WORDS: a task gate cleared on purpose
    (`gateBasis: cleared`) is graded at sign-off by its phase's `testGate` when
    that has entries, so `NO_GATE`'s "nor its phase's" would be false for it.
    """
    entries, source = _mio.gate_entries(phase, task)
    build = ((manifest or {}).get("meta") or {}).get("buildCommands")
    task_id, phase_id = str(task.get("id")), str(phase.get("id"))
    record = ("run `run-test-gate.py %s %s --task %s --record` on the work, then "
              "commit" % (manifest_path, phase_id, task_id))
    if _mio.gate_cleared(task.get("tests")):
        phase_gate = _mio.declared_gate_entries((phase or {}).get("testGate"))
        no_gate = CLEARED_GATE % (
            "the phase's `testGate` grades it at sign-off" if phase_gate else
            "the phase's `testGate` is empty too, so sign-off rests on review "
            "alone",)
    else:
        no_gate = NO_GATE
    answer = _vb.binding(project, {"taskId": task_id, "phaseId": phase_id},
                         entries, source, list(task.get("files") or []),
                         manifest_path, record, no_gate, config=config,
                         build=build)
    if answer["state"] == "refused" and answer["row"] is not None \
            and not entries:
        answer["sentence"] += ", or commit over it with a reason"
    return answer


def override_row(project, task_id, phase_id, nonce, verdict, reason,
                 config=None):
    """The trail row a commit made over its verdict leaves. Returns the file, or False.

    It names the commit - by `nonce`, the commit's `Audit-Row` trailer, since it
    is written before the commit and carried by it - the run it went over (when
    there was one) and the operator's reason, so the override is findable by
    any of them.
    """
    config = _journal_io.load_config(project) if config is None else config
    details = {_invariants.NONCE_KEY: nonce, "taskId": str(task_id),
               "phaseId": str(phase_id), "reason": reason}
    row = verdict.get("row") or {}
    if row.get("runId"):
        details["runId"] = str(row["runId"])
    return _journal_io.append_from_cli(project, {
        "action": ACTION_VERDICT_OVERRIDDEN,
        "actor": {"sessionId": _journal_io.env_session_id(),
                  "via": "commit-task-work"},
        "target": str(task_id),
        "summary": "%s was committed as the commit carrying `%s` over the "
                   "verdict that refused it: %s"
                   % (task_id, _scoped_commit.row_trailer(nonce),
                      verdict.get("sentence")),
        "details": details,
    }, config=config)


# --- the commit ---------------------------------------------------------------
def commit_message(task_id, subject, manifest, claims=None):
    """The message paragraphs: a conventional subject, the executor's filed
    `claims` when it carried one, and the co-author trailer.

    THE CLAIMS ARE A PARAGRAPH OF THEIR OWN, byte-identical, after the subject
    and before the trailers. The plugin commits through its own `git commit`
    subprocess, so a repository hook that asks a Bash command for a `claims:`
    block never sees this commit; the block the executor filed is what reaches
    the message instead. A return without one gives the message it always did -
    the plugin has no ground to require a block a project may not ask for.
    `_scoped_commit.with_row_trailer` keeps the row trailer in a paragraph of
    trailers, its own when there is no co-author line, so the claims paragraph
    never becomes the one git reads trailers from.

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
    if isinstance(claims, str) and claims.strip():
        paragraphs.append(claims)
    coauthor = block.get("coauthor")
    if isinstance(coauthor, str) and coauthor.strip():
        paragraphs.append(coauthor)
    return paragraphs


def claims_from_return(manifest_path, project, task):
    """`(claims, refusal)` - the `claims` text of the executor's return filed for
    `task`'s current start, under THIS manifest's evidence directory, or None.
    A filed return that will not parse is a refusal, never an absence."""
    proj, cfg = _evidence_io.project_config_for(manifest_path, project)
    claims, problem = _filed_returns.claims_from_return(
        _evidence_io.evidence_dir(proj, cfg), task)
    if problem:
        return None, ("the executor's filed return %s - nothing was committed, "
                      "because a commit that dropped its claims would read as "
                      "one whose return carried none" % (problem,))
    return claims, None


def record_row(project, task_id, phase_id, nonce, config=None):
    """Anchor the commit in the trail. Returns the file the row landed in, or False.

    WRITTEN BEFORE THE COMMIT AND CARRIED BY IT, so it names the commit by
    `nonce`, the value of the commit's `Audit-Row` trailer: the SHA does not
    exist yet, and a row inside a commit cannot hold the hash of that commit.

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
        "summary": "%s's work was committed as the commit carrying `%s` - the "
                   "files the task declares, the phase's manifest file and the "
                   "records beside them"
                   % (task_id, _scoped_commit.row_trailer(nonce)),
        "details": {_invariants.NONCE_KEY: nonce, "taskId": str(task_id),
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
                             "does not bind this work; the reason is written to "
                             "the journal with the commit")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return _claude_home.attach_usage_hint(parser)


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
    refusal = ignored_refusal(targets["ignored"], targets["ignoredRecords"])
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
    verdict = verdict_binding(manifest_path, phase, task, project, config=config,
                              manifest=manifest)
    skipped = skipped + list(verdict.get("notes") or [])
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
    # The executor's filed return for the task's current start, for its
    # `claims`. Still before staging: a return that is there and will not parse
    # refuses with nothing to undo, rather than committing as if none was filed.
    claims, why = claims_from_return(manifest_path, project, task)
    if why:
        return E_FAIL, _scoped_commit.answer(skipped, refused=why)

    def rows(nonce):
        """The rows naming this commit, written before it: the anchor, and the
        override's when there is one - which the commit REQUIRES, so a failed
        one refuses before anything is staged."""
        anchor = record_row(project, task_id, phase_id, nonce, config=config)
        files = [anchor] if anchor else []
        if not overriding:
            return files, ""
        recorded = override_row(project, task_id, phase_id, nonce, verdict,
                                override, config=config)
        if not recorded:
            return files, (
                "the journal row recording the override could NOT be written, "
                "so this commit would go over its gate with nothing in the "
                "trail saying so - nothing was committed. The verdict: %s"
                % (verdict["sentence"],))
        return files + [recorded], ""

    done = _scoped_commit.commit_with_rows(
        git_root, allowed, targets["kinds"],
        commit_message(task_id, subject, manifest, claims=claims),
        lambda paths: foreign_refusal(paths, targets), rows,
        lambda nonce, why: _scoped_commit.withdraw(
            project, config, nonce, "commit-task-work",
            {"taskId": task_id, "phaseId": phase_id}, why))
    if not done["committed"]:
        answer = _scoped_commit.answer(skipped, staged=done["staged"],
                                       foreign=done["foreign"],
                                       refused=done["refused"], done=done)
        answer["verdict"] = verdict
        return E_FAIL, answer
    sha = done["sha"]
    if sha and done["refused"]:
        # Committed on a HEAD that moved underneath: the SHA is reported and
        # nothing is undone, with the exit code saying it needs a look.
        answer = _scoped_commit.answer(skipped, committed=True, commit=sha,
                                       staged=done["staged"],
                                       refused=done["refused"],
                                       journalled=done["journalled"], done=done)
        answer["verdict"] = verdict
        answer["overridden"] = overriding
        return E_FAIL, answer
    if not sha:
        # The commit exists and this process cannot name it. A failure rather than
        # a success with a blank field: `/audit:task done` needs the SHA, and a
        # caller told "committed" with nothing to pass it would close the task
        # against no commit at all.
        return E_FAIL, _scoped_commit.answer(
            skipped, committed=True, staged=done["staged"],
            journalled=done["journalled"], done=done,
            refused="%s, so nothing can name it to `/audit:task done`"
                    % (done["refused"],))

    answer = _scoped_commit.answer(skipped, committed=True, commit=sha,
                                   staged=done["staged"],
                                   journalled=done["journalled"], done=done)
    answer["verdict"] = verdict
    answer["overridden"] = overriding
    return E_OK, answer


def success_line(lines):
    """A commit's one line: the SHA it wrote, how many paths it carries, and
    the verdict it rests on.

    None - the long form - for a run that committed with anything beside those
    to say: a degraded step, a journal row outside the commit or never written.
    """
    head = lines[0].strip() if lines else ""
    if not head.startswith("%s committed " % (PREFIX,)):
        return None
    carried = _scoped_commit.ROW_CARRIED.split("%")[0]
    paths = [ln for ln in lines[1:] if ln.startswith("    ") and ln.strip()]
    rest = [ln.strip() for ln in lines[1:] if ln.strip() and ln not in paths]
    verdict = [ln for ln in rest if ln.startswith("verdict: ")]
    if any(not ln.startswith((carried, "verdict: ")) for ln in rest):
        return None
    return "%s (%d path(s), its journal row inside it)%s" % (
        head, len(paths),
        "; %s" % (verdict[0].split(" - ")[0],) if verdict else "")


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
    from _output import safe_stdio, selftest_requested  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if selftest_requested(sys.argv[1:]):
        # Answers rather than falling through to a usage error, which would read
        # as a broken flag rather than as a moved suite. It deliberately does NOT
        # print the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("commit-task-work.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_commit_task_work.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(_output.terse_cli(main, sys.argv[1:], success_line))
