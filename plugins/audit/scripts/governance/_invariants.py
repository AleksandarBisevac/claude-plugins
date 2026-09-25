#!/usr/bin/env python3
"""
The orchestrator's invariants, re-derived from evidence after the run.

`README.md` and `plugins/audit/README.md` carry two columns: what a hook or a
script ENFORCES, and what the model FOLLOWS from `reference/orchestrator.md`.
The right-hand column is the honest half of this project's claim, and most of its
rows are marked `post-hoc` - the trace a breach would leave already sits in git,
in the phase's shard, in the journal and in the usage ledger, and what was
missing was the reader. This module is that reader. Every row it really covers
moves from the right column to the left, which is the only thing that turns a
policy into a guarantee.

WHAT IT REFUSES TO DO. A check answers from evidence or says it has none; it
never falls back to a default to fill a gap. That is why a verdict is one of five
words rather than a boolean:

    clean            something was examined and nothing contradicted the rule
    breach           the evidence contradicts the rule
    partial          examined, nothing wrong, and some of the evidence is gone
    no-basis         NOTHING could be examined - the loudest of the five, because
                     it is the one a boolean renders as "fine"
    not-applicable   the rule has no subject here (no high-risk task, no branch,
                     no recorded commit)

`clean` cannot be produced by looking at nothing: every check reports how many
subjects it actually examined, and a zero there becomes `no-basis` with the
reason printed beside it.

WHAT IT CANNOT SEE, said here rather than left for a reader to discover:

  * `git branch -d <branch>` at sign-off (orchestrator step 4e) takes the phase
    branch's reflog with it, so `branch-history` on a finished phase usually
    answers `no-basis` rather than `clean`.
  * A stash that was DROPPED rather than popped leaves no reflog entry, so a
    clean `refs/stash` is evidence and not proof.
  * A manifest state written between two commits left no bytes anywhere, so
    `manifest-revalidated` re-runs the validator on the states the phase
    COMMITTED and counts the journal rows whose bytes git no longer holds.
  * A push made from a different clone of the same repository writes nothing
    here.

None of those is a defect in this module; each is the shape of the evidence, and
a checker that smoothed them into `clean` would be the exact failure the README
section exists to stop.

Reads git, the manifest, the journal and the ledger, and does not raise for the
caller: a check that cannot run reports that it could not run. The one raise is
`result()`'s TypeError on a breach built without `found()`, which is a
programming error - `test__invariants.py` walks this file's syntax tree so CI
finds one before any run does. The one write is
`write_baseline`, which a caller reaches only by asking for it by name, and it
takes the `index` lock for its read-then-write.

THE BASELINE LIVES HERE AND NOT IN A COMMAND, because two surfaces give a verdict
over these checks - `verify-invariants.py` and `/audit:status --gate --fail-on
invariant-breach` - and a baseline one of them honoured would let the same history
pass one and fail the other. Both ask `apply_baseline` which breaches count.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__invariants.py`.
"""
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile

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

import _branch  # noqa: E402  (which branch a phase forks from, and the basis for it)
import _commit_trail  # noqa: E402  (is a recorded SHA still reachable, and the git runner)
import _evidence_io  # noqa: E402  (the test-evidence record: where it lives)
import _journal_io  # noqa: E402  (the trail: where it lives, its rows, their stateHash)
import _locks  # noqa: E402  (the index lock the baseline write is taken under)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR shards)
import _manifest_rules as _rules  # noqa: E402  (the validator this re-runs on old states)
import _manifest_crossrefs as _crossrefs  # noqa: E402  (FILEINDEX_PAIRING: the one finding a task commit cannot carry)
import _status_facts  # noqa: E402  (gitRoot-relative file paths, already one implementation)
import usage_ledger  # noqa: E402  (which model actually ran a task)

# The one git runner in the tree for this family of questions, reused rather than
# re-spelled. A second wrapper would be a second timeout, a second decoding rule,
# and a second answer to "what does it mean when git could not be asked" - which
# is the answer this whole module is built around.
_git = _commit_trail._git

# Project-relative file -> git-root-relative, and the `:line` suffix dropped. Same
# reason: `task.files` are written with the `meta.gitRoot` prefix, `git show
# --name-only` prints without it, and one transform between them is one rule.
_strip_git_root = _status_facts._strip_git_root

CLEAN = "clean"
BREACH = "breach"
PARTIAL = "partial"
NO_BASIS = "no-basis"
NA = "not-applicable"

# Output order, and the order `verify-invariants.py` prints. It matches the order
# the invariants appear in `reference/orchestrator.md`'s own sections rather than
# any notion of severity: a reader comparing the two documents should not have to
# re-sort one of them in their head.
#
# `audit-state-scope` and `index-scope` have no section of their own to sit
# beside, and they are placed next to `commit-scope` rather than at the end for
# that reason. Each asks `commit-scope`'s question -- what did this commit stage,
# and was it allowed to -- about a DIFFERENT commit, and the three allow-lists
# differ entry by entry: a task commit may stage the task's `files` and the audit
# state commit may not, and a manifest-index commit may stage the one path both
# the others forbid and nothing whatever besides. A reader comparing three
# commit-shaped rules needs them adjacent; separated, the differences that matter
# read as omissions.
CHECK_NAMES = ("commit-scope", "audit-state-scope", "index-scope",
               "evidence-committed", "branch-history", "manifest-revalidated",
               "high-risk-model", "base-ref")

# A commit whose file list `git show --name-only` will not print. Stated as a
# constant because the empty output it produces is indistinguishable from "this
# commit touched nothing", and the second reading is the one that passes.
_MERGE_PARENTS = 2


# --- shapes -------------------------------------------------------------------
def verdict_of(breaches, gaps, examined, applies):
    """The five-word verdict, from what was found and what could be looked at.

    `examined` is the guard that makes `clean` mean something. A filter that
    narrowed to nothing produces an empty `breaches` list, and without this it
    would print the calmest word in the vocabulary; here it prints the loudest.
    """
    if not applies:
        return NA
    if breaches:
        return BREACH
    if not examined:
        return NO_BASIS
    if gaps:
        return PARTIAL
    return CLEAN


def found(line, subject, sha=None, local=False):
    """One breach: the sentence a reader is shown, and the key it is known by.

    THE KEY IS WHAT A BASELINE MATCHES, AND IT HOLDS NO PROSE. `subject` names
    the thing that broke the rule - a path, a task and a path, a run id, a ref,
    or a validator finding reduced by `_manifest_rules.finding_subject` to its
    locus and ids - and `sha` the commit it is recorded against, which every
    caller resolves to the full id through git first, since the manifest records
    whatever abbreviation a close wrote. A reworded template or validator
    message, or a count that moves between runs, changes what is printed and
    never what is matched.

    `local` marks a breach read from evidence a clone does not receive - a
    reflog, the stash, a remote-tracking ref, the gitignored usage ledger.
    """
    return {"line": line, "subject": str(subject),
            "sha": str(sha) if sha else None, "local": bool(local)}


def full_sha(git_root, sha):
    """The full commit id `sha` names, or `sha` itself when git cannot say."""
    code, out = _git(git_root, ["rev-parse", "-q", "--verify",
                                "%s^{commit}" % (sha,)])
    full = out.strip() if code == 0 else ""
    return full or str(sha)


def result(name, basis, breaches, gaps, examined, applies=True):
    """One check's answer. `basis` travels with it, always.

    A verdict with no basis beside it is the thing this module exists to replace,
    so the basis is a required argument rather than an optional decoration - the
    caller cannot forget it, because there is nowhere to leave it out.

    `breaches` are `found()` records. `breaches` in the answer stays the list of
    sentences every renderer prints, and `keys` is the parallel list of what each
    one is matched by - so a breach without a key cannot be built at all.
    """
    for item in breaches:
        if not (isinstance(item, dict) and "line" in item and "subject" in item):
            raise TypeError("%s: a breach must be built with found(), got %r"
                            % (name, item))
    return {
        "name": name,
        "verdict": verdict_of(breaches, gaps, examined, applies),
        "basis": basis,
        "breaches": [b["line"] for b in breaches],
        "keys": [{"subject": b["subject"], "sha": b["sha"], "local": b["local"]}
                 for b in breaches],
        "gaps": list(gaps),
        "examined": examined,
    }


def _rel(path, root):
    """`path` relative to `root`, "/"-separated - or None when it is outside.

    None rather than a `../..` path on purpose: a manifest that lives outside the
    git root cannot be committed at all (the orchestrator's own step 4c says so),
    and a caller that treated the escape as a path would compare it against a
    `git show` listing that can never contain it.
    """
    try:
        rel = _output.posix_rel(os.path.abspath(path),
                                os.path.abspath(root))
    except Exception:
        return None
    if rel == ".." or rel.startswith("../"):
        return None
    return rel


def _under(path, rel):
    """True when `path` IS `rel` or sits inside it.

    THE SEPARATOR IS THE WHOLE FUNCTION, and it is shared rather than spelled at
    each arm because both allow-lists below carry the same trap: written as a bare
    `startswith`, a sibling directory called `evidence-notes/` reads as inside
    `evidence/` and the list admits the rest of the repository one rename away.
    A falsy `rel` is False rather than a match on everything - an unresolved
    directory allows nothing, which is the direction that cannot invent a pass.
    """
    return bool(rel) and (path == rel or path.startswith(rel + "/"))


def _git_available(git_root):
    """(ok, reason). `git` on PATH and a root to run it in, or why not."""
    if not git_root:
        return False, "no git root was resolved, so git could not be asked"
    if not shutil.which("git"):
        return False, "git is not on PATH, so nothing here could be asked"
    return True, ""


def phase_of(manifest, phase_id):
    """The phase dict with this id, or None. Never raises on a malformed manifest."""
    for phase in ((manifest or {}).get("phases") or []):
        if isinstance(phase, dict) and str(phase.get("id")) == str(phase_id):
            return phase
    return None


def manifest_files(manifest_path, phase):
    """(indexAbs, phaseFileAbs) - the index, and the file this phase lives in.

    In the sharded layout the phase's file is its shard and the index is a
    different file; in the single-file layout they are the same path, and the
    caller must not then read "the index was staged" out of a task commit that
    legitimately staged the only manifest there is.
    """
    index_abs = os.path.abspath(manifest_path)
    shard = (phase or {}).get("shard")
    if not shard:
        # The assembled phase carries no `shard` key; the index stub does. Read the
        # raw index rather than guessing a filename - `_shard_name` is the writer's
        # rule and a reader that re-derived it would drift the first time it changed.
        try:
            raw = _mio.read_json(index_abs)
        except Exception:
            return index_abs, index_abs
        for stub in (raw.get("phases") or []):
            if isinstance(stub, dict) and str(stub.get("id")) == str(
                    (phase or {}).get("id")) and stub.get("shard"):
                shard = stub["shard"]
                break
    if not shard:
        return index_abs, index_abs
    return index_abs, os.path.abspath(
        os.path.join(os.path.dirname(index_abs), str(shard)))


# --- where to look ------------------------------------------------------------
def git_root_for(manifest, project):
    """Where git runs: `project`, plus `meta.gitRoot` when the workspace nests.

    Here rather than in each caller because there are now two - the command and
    `/audit:status --gate` - and a workspace whose repository is a subdirectory is
    exactly the layout a second spelling gets wrong without saying anything.
    """
    rel = ((manifest or {}).get("meta") or {}).get("gitRoot") or "."
    return os.path.abspath(project if rel == "." else os.path.join(project, rel))


def ledger_dir_for(manifest, manifest_path):
    """This manifest's ledger directory, or None when it has none.

    Separate from `check_phase` on purpose: `ledger_dir=None` there MEANS "there
    is no ledger", and a library that quietly went looking would make an unmetered
    repository and a mislocated ledger read the same. Resolving is the caller's
    step, and this is the one implementation of it.
    """
    block = ((manifest or {}).get("meta") or {}).get("usage")
    try:
        return usage_ledger.find_ledger_dir(
            manifest_path,
            block.get("ledgerDir") if isinstance(block, dict) else None)
    except Exception:
        return None


# --- commit scope -------------------------------------------------------------
COMMIT_SCOPE_BASIS = ("git show --name-only <task.commit>, against that task's "
                      "`files`, its phase's manifest file, the journal directory "
                      "and the evidence directory - the four things "
                      "orchestrator.md step 4c allows a task commit to stage")


def commit_scope(phase, git_root, git_root_rel, phase_file_rel, index_rel,
                 journal_rel, evidence_rel=None):
    """A task commit staged that task's files, its phase's manifest file, the two
    records beside it.

    THE EVIDENCE DIRECTORY IS ALLOWED FOR THE JOURNAL'S REASON, one noun over. A
    task commit stages it so that the record of what ran reaches git with the
    change it describes rather than a week later - and a failed run's record
    reaches git at all, since the orchestrator does not commit a red gate. It
    defaults to None so a caller that has not resolved one is told nothing about
    evidence rather than being told there is none.

    THE INDEX IS ITS OWN FINDING. "Do NOT stage the index" is a separate sentence
    in step 4c and a separate failure: a task commit that carries the index is
    what makes two parallel phases conflict on merge, which is the property the
    sharded layout was introduced to buy. Folding it into the generic "a path
    that is not allowed" line would report the expensive mistake in the same
    words as a stray README.
    """
    breaches, gaps = [], []
    tasks = [t for t in (phase.get("tasks") or [])
             if isinstance(t, dict) and t.get("commit")]
    if not tasks:
        return result("commit-scope", COMMIT_SCOPE_BASIS, [], [], 0, applies=False)
    ok, why = _git_available(git_root)
    if not ok:
        return result("commit-scope", COMMIT_SCOPE_BASIS, [], [why], 0)

    examined = 0
    for task in tasks:
        tid = str(task.get("id"))
        sha = str(task.get("commit"))
        code, parents = _git(git_root, ["rev-list", "--parents", "-n", "1", sha])
        if code is None or code != 0:
            gaps.append("%s: the recorded commit %s does not resolve in this "
                        "clone, so its file list cannot be read (repair-commits.py "
                        "reports the same SHA)" % (tid, sha[:12]))
            continue
        sha = parents.split()[0] if parents.split() else sha
        if len(parents.split()) > _MERGE_PARENTS:
            gaps.append("%s: %s is a merge commit, and `git show --name-only` "
                        "prints no files for one - an empty list here would read "
                        "as a commit that staged nothing" % (tid, sha[:12]))
            continue
        code, out = _git(git_root, ["show", "--name-only", "--pretty=format:", sha])
        if code is None or code != 0:
            gaps.append("%s: git would not print the file list of %s"
                        % (tid, sha[:12]))
            continue
        examined += 1
        allowed = set()
        for name in (task.get("files") or []):
            rel = _strip_git_root(name, git_root_rel)
            if rel:
                allowed.add(rel.strip("/"))
        staged = [ln.strip().replace("\\", "/")
                  for ln in out.splitlines() if ln.strip()]
        for path in staged:
            if path in allowed:
                continue
            if phase_file_rel and path == phase_file_rel:
                continue
            if _under(path, journal_rel) or _under(path, evidence_rel):
                continue
            if index_rel and path == index_rel and index_rel != phase_file_rel:
                breaches.append(found(
                    "%s: commit %s staged the manifest INDEX (%s). A task commit "
                    "changes only its own phase's shard - the index is what "
                    "parallel phases would then conflict on"
                    % (tid, sha[:12], index_rel), "%s %s" % (tid, index_rel), sha))
                continue
            breaches.append(found(
                "%s: commit %s staged %s, which is not in the task's `files`, is "
                "not this phase's manifest file and is in neither the journal nor "
                "the evidence directory" % (tid, sha[:12], path),
                "%s %s" % (tid, path), sha))
    return result("commit-scope", COMMIT_SCOPE_BASIS, breaches, gaps, examined)


# --- audit-state scope --------------------------------------------------------
# The action an audit-state commit records, spelled ONCE and read from here by the
# writer and by the reader below. The writer is `commit-audit-state.py`, an ENTRY
# POINT: nothing may import a hyphenated command, so the constant cannot live
# beside the code that appends the row, and this module is the lowest one both
# halves can reach. A second spelling would not fail loudly -- the reader would
# simply find no rows and answer `not-applicable` for ever, which is the calmest
# word in the vocabulary sitting over a check that had stopped looking.
ACTION_STATE_COMMITTED = "audit.state.committed"

AUDIT_STATE_SCOPE_BASIS = (
    "git show --name-only <commit> for every `%s` journal row naming this phase - "
    "the rows are how such a commit is found at all, since nothing in the "
    "manifest points at one - against the phase's manifest file, the journal "
    "directory and the evidence directory. The task's `files` are deliberately "
    "NOT on that list: this commit exists to preserve the record of a run that "
    "failed, and the implementation it failed on must stay out of git"
    % (ACTION_STATE_COMMITTED,))


def recorded_commits(project, phase_id, action, noun, config=None):
    """`(shas, unnamed, why)` - the commits of one class this phase's trail records.

    `shas is None` means nobody could look and `why` says so; that is a different
    answer from an empty list, which means this phase has never made a commit of
    this class. `unnamed` counts rows that claim one and do not carry its SHA - a
    claim whose basis is missing, which is reported rather than dropped.

    FOUND THROUGH THE JOURNAL AND NOWHERE ELSE, because there is nowhere else:
    neither an audit-state commit nor a manifest-index commit is a `task.commit`,
    and the manifest names neither. That is exactly why the journal being OFF has
    to read as no-basis below rather than as nothing to check.

    ONE WALK FOR BOTH CLASSES, parameterised by the action and by the `noun` its
    two sentences name (article included, because "an audit-state commit" and "a
    manifest-index commit" do not share one). The readers differ in the action
    they look for and in nothing else, and a second copy of this loop would be a
    second answer to "was the journal readable" - the question whose wrong answer
    prints `not-applicable` over a check that had stopped looking.
    """
    config = _journal_io.load_config(project) if config is None else config
    if not _journal_io.enabled(config):
        return None, 0, ("the journal is disabled here, so %s leaves no row "
                         "naming it and none can be found - this is not evidence "
                         "that none was made" % (noun,))
    try:
        rows = _journal_io.read_all(project, config=config)
    except Exception as exc:                                   # defensive
        return None, 0, ("the journal could not be read (%s), so %s could not be "
                         "found" % (exc, noun))
    shas, unnamed = [], 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("action") or "") != action:
            continue
        details = row.get("details")
        details = details if isinstance(details, dict) else {}
        if str(details.get("phaseId") or "") != str(phase_id):
            continue
        sha = str(details.get("commit") or "")
        if not sha:
            unnamed += 1
        elif sha not in shas:
            shas.append(sha)
    return shas, unnamed, ""


def audit_state_commits(project, phase_id, config=None):
    """`(shas, unnamed, why)` - the audit-state commits this phase's trail records.

    A name of its own rather than the generic call at each site: the action and
    the noun that belong to this class are decided ONCE here, so a caller cannot
    pair the audit-state action with the index commit's sentences.
    """
    return recorded_commits(project, phase_id, ACTION_STATE_COMMITTED,
                            "an audit-state commit", config=config)


def audit_state_scope(phase, git_root, project, phase_file_rel, index_rel,
                      journal_rel, evidence_rel=None, config=None):
    """An audit-state commit carried the record, and none of the work.

    THE ALLOW-LIST IS `commit_scope`'s MINUS ONE ENTRY, and that entry is the
    point. A task commit may stage the task's `files`; this one may not, because
    it is made on the path where the gate went red - so a file the task owns
    appearing here is implementation reaching git on a run that was never signed
    off, which is the failure the whole verb exists to make impossible.

    THE INDEX KEEPS ITS OWN SENTENCE, for `commit_scope`'s reason one commit over:
    staging the shared index is what makes two parallel phases conflict on merge,
    and reporting it in the same words as a stray file would price the expensive
    mistake as the cheap one.
    """
    breaches, gaps = [], []
    shas, unnamed, why = audit_state_commits(project, (phase or {}).get("id"),
                                             config=config)
    if shas is None:
        return result("audit-state-scope", AUDIT_STATE_SCOPE_BASIS, [], [why], 0)
    if not shas and not unnamed:
        return result("audit-state-scope", AUDIT_STATE_SCOPE_BASIS, [], [], 0,
                      applies=False)
    if unnamed:
        gaps.append("%d journal row(s) record an audit-state commit for this "
                    "phase without naming it, so those commits cannot be read"
                    % (unnamed,))
    ok, git_why = _git_available(git_root)
    if not ok:
        return result("audit-state-scope", AUDIT_STATE_SCOPE_BASIS, [],
                      gaps + [git_why], 0)

    examined = 0
    for sha in shas:
        code, parents = _git(git_root, ["rev-list", "--parents", "-n", "1", sha])
        if code is None or code != 0:
            gaps.append("the recorded audit-state commit %s does not resolve in "
                        "this clone, so its file list cannot be read"
                        % (sha[:12],))
            continue
        sha = parents.split()[0] if parents.split() else sha
        if len(parents.split()) > _MERGE_PARENTS:
            gaps.append("%s is a merge commit, and `git show --name-only` prints "
                        "no files for one - an empty list here would read as a "
                        "commit that staged nothing" % (sha[:12],))
            continue
        code, out = _git(git_root, ["show", "--name-only", "--pretty=format:", sha])
        if code is None or code != 0:
            gaps.append("git would not print the file list of the audit-state "
                        "commit %s" % (sha[:12],))
            continue
        examined += 1
        staged = [ln.strip().replace("\\", "/")
                  for ln in out.splitlines() if ln.strip()]
        for path in staged:
            if phase_file_rel and path == phase_file_rel:
                continue
            if _under(path, journal_rel) or _under(path, evidence_rel):
                continue
            if index_rel and path == index_rel and index_rel != phase_file_rel:
                breaches.append(found(
                    "audit-state commit %s staged the manifest INDEX (%s). It "
                    "carries this phase's own file and the two records beside it "
                    "- the index is what parallel phases would then conflict on"
                    % (sha[:12], index_rel), index_rel, sha))
                continue
            breaches.append(found(
                "audit-state commit %s staged %s, which is neither this phase's "
                "manifest file nor anything in the journal or the evidence "
                "directory. An audit-state commit carries the RECORD of a run and "
                "never the work it ran on, so this is implementation reaching git "
                "on a run that was never signed off" % (sha[:12], path),
                path, sha))
    return result("audit-state-scope", AUDIT_STATE_SCOPE_BASIS, breaches, gaps,
                  examined)


# --- manifest-index scope -----------------------------------------------------
# The action a manifest-index commit records, spelled ONCE and read from here by
# the writer and by the reader below, for `ACTION_STATE_COMMITTED`'s reason word
# for word: the writer is `commit-manifest-index.py`, an ENTRY POINT nothing may
# import, so the constant cannot live beside the code that appends the row, and
# this module is the lowest one both halves can reach.
ACTION_INDEX_COMMITTED = "audit.index.committed"

INDEX_SCOPE_BASIS = (
    "git show --name-only <commit> for every `%s` journal row naming this phase - "
    "the rows are how such a commit is found at all, since nothing in the "
    "manifest points at one - against the manifest INDEX and nothing else at all. "
    "The phase's own manifest file is deliberately NOT on that list: a commit "
    "carrying the shared index AND a phase's file is exactly the shape two "
    "parallel phases conflict on, and carrying them in separate commits is the "
    "whole reason this class exists" % (ACTION_INDEX_COMMITTED,))


def index_commits(project, phase_id, config=None):
    """`(shas, unnamed, why)` - the manifest-index commits this phase's trail records.

    A name of its own beside `audit_state_commits`, for that function's reason:
    the action and the noun belonging to this class are decided once, here, so no
    caller can pair one class's action with the other's sentences.
    """
    return recorded_commits(project, phase_id, ACTION_INDEX_COMMITTED,
                            "a manifest-index commit", config=config)


def index_scope(phase, git_root, project, index_rel, phase_file_rel, config=None):
    """A manifest-index commit carried the index, and nothing at all beside it.

    THE ALLOW-LIST IS ONE ENTRY LONG, and that is the point rather than an
    austerity. `/audit:task add --files` and `/audit:phase add` write `fileIndex`
    and a phase stub into the shared index, and step 4c forbids a task commit from
    staging it -- so until this class existed nothing committed the index at all
    and the debt just accumulated. What makes the repair safe is the narrowness:
    a commit carrying ONLY the shared file can be landed, cherry-picked or
    re-derived on its own, while a commit carrying the index AND a phase's work
    cannot be separated from the work when two branches meet on that file.

    THE PHASE'S OWN MANIFEST FILE THEREFORE KEEPS ITS OWN SENTENCE, the mirror of
    the one `commit_scope` and `audit_state_scope` write about the index. There
    the index is the named intruder; here it is the only thing allowed and the
    shard is the intruder, and reporting that pair in the same words as a stray
    README would price the expensive mistake as the cheap one.

    IN THE SINGLE-FILE LAYOUT `manifest_files` returns the identity pair, so the
    index IS the phase's file and the sentence above has no subject. The writer
    refuses to make this commit there at all, so the rows this reads should not
    exist; the guard is kept anyway, because a check that would convict a
    hand-made commit of staging the only manifest there is would be reporting the
    layout rather than a breach.
    """
    breaches, gaps = [], []
    shas, unnamed, why = index_commits(project, (phase or {}).get("id"),
                                       config=config)
    if shas is None:
        return result("index-scope", INDEX_SCOPE_BASIS, [], [why], 0)
    if not shas and not unnamed:
        return result("index-scope", INDEX_SCOPE_BASIS, [], [], 0, applies=False)
    if unnamed:
        gaps.append("%d journal row(s) record a manifest-index commit for this "
                    "phase without naming it, so those commits cannot be read"
                    % (unnamed,))
    if not index_rel:
        # Nothing to compare against. A commit whose every path was called a
        # breach would be this module reporting a manifest that lives outside the
        # repository, which is a different finding and one `stage_targets` already
        # degrades past on the writing side.
        return result("index-scope", INDEX_SCOPE_BASIS, [],
                      gaps + ["the manifest index is not inside the git root, so "
                              "what such a commit staged cannot be compared "
                              "against it"], 0)
    ok, git_why = _git_available(git_root)
    if not ok:
        return result("index-scope", INDEX_SCOPE_BASIS, [], gaps + [git_why], 0)

    examined = 0
    for sha in shas:
        code, parents = _git(git_root, ["rev-list", "--parents", "-n", "1", sha])
        if code is None or code != 0:
            gaps.append("the recorded manifest-index commit %s does not resolve "
                        "in this clone, so its file list cannot be read"
                        % (sha[:12],))
            continue
        sha = parents.split()[0] if parents.split() else sha
        if len(parents.split()) > _MERGE_PARENTS:
            gaps.append("%s is a merge commit, and `git show --name-only` prints "
                        "no files for one - an empty list here would read as a "
                        "commit that staged nothing" % (sha[:12],))
            continue
        code, out = _git(git_root, ["show", "--name-only", "--pretty=format:", sha])
        if code is None or code != 0:
            gaps.append("git would not print the file list of the manifest-index "
                        "commit %s" % (sha[:12],))
            continue
        examined += 1
        staged = [ln.strip().replace("\\", "/")
                  for ln in out.splitlines() if ln.strip()]
        for path in staged:
            if path == index_rel:
                continue
            if (phase_file_rel and path == phase_file_rel
                    and phase_file_rel != index_rel):
                breaches.append(found(
                    "manifest-index commit %s staged this phase's manifest file "
                    "(%s) as well as the index (%s). The two in one commit is the "
                    "shape that makes parallel phases conflict on merge, and "
                    "keeping them apart is the only thing this commit class buys"
                    % (sha[:12], phase_file_rel, index_rel), phase_file_rel, sha))
                continue
            breaches.append(found(
                "manifest-index commit %s staged %s, and this class carries the "
                "manifest index (%s) and nothing else. A commit that carries the "
                "shared file alone can be landed or re-derived on its own; one "
                "that also carries work cannot be separated from it"
                % (sha[:12], path, index_rel), path, sha))
    return result("index-scope", INDEX_SCOPE_BASIS, breaches, gaps, examined)


# --- evidence committed -------------------------------------------------------
EVIDENCE_COMMITTED_BASIS = (
    "every `testEvidence.runId` in the phase's COMMITTED state at HEAD, against "
    "the `runId`s in the evidence rows HEAD holds - the plan and the record as a "
    "clone would receive them, not as this working tree happens to have them")


def _committed_run_ids(git_root, evidence_rel):
    """`(runIds, gaps)` - every `runId` the committed evidence rows carry.

    READ FROM HEAD AND NOT FROM DISK. The whole question is what a CLONE would
    find, and a row sitting unstaged in this working tree is exactly the case
    that looks fine here and reaches nobody.
    """
    ids, gaps = set(), []
    code, listing = _git(git_root, ["ls-tree", "-r", "--name-only", "HEAD",
                                    evidence_rel])
    if code is None or code != 0:
        return ids, ["git would not list the committed evidence directory, so "
                     "which rows HEAD holds is unknown"]
    for name in [ln.strip() for ln in listing.splitlines() if ln.strip()]:
        if not name.endswith(".jsonl"):
            continue
        code, blob = _git(git_root, ["show", "HEAD:" + name])
        if code is None or code != 0:
            gaps.append("git would not read the committed %s, so its rows could "
                        "not be counted" % (name,))
            continue
        for line in blob.splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                # A torn line is a gap and not a breach: it says a row could not
                # be read, never that a pointer is unsupported.
                gaps.append("a row in the committed %s is not readable JSON, so "
                            "it could not be matched against any pointer" % (name,))
                continue
            if isinstance(row, dict) and row.get("runId"):
                ids.add(str(row["runId"]))
    return ids, gaps


def _committed_pointers(git_root, phase_file_rel):
    """`(pointers, gaps)` - `(subject, runId)` for every pointer HEAD's plan carries.

    The PHASE's own pointer is collected beside its tasks': a sign-off gate's run
    is the one a reader most wants to follow, and walking only tasks would clear
    a phase pointing at nothing.
    """
    if not phase_file_rel:
        return [], ["this phase's manifest file is outside the git root, so its "
                    "committed state cannot be read"]
    code, blob = _git(git_root, ["show", "HEAD:" + phase_file_rel])
    if code is None or code != 0:
        return [], ["git would not read the committed %s, so the pointers it "
                    "carries are unknown" % (phase_file_rel,)]
    try:
        body = json.loads(blob)
    except Exception as exc:
        return [], ["the committed %s is not readable JSON (%s)"
                    % (phase_file_rel, exc)]
    phases = [body] if body.get("id") else [
        p for p in (body.get("phases") or []) if isinstance(p, dict)]
    out = []
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        for holder, subject in [(phase, "phase %s" % (phase.get("id"),))] + [
                (t, "task %s" % (t.get("id"),))
                for t in (phase.get("tasks") or []) if isinstance(t, dict)]:
            pointer = holder.get("testEvidence")
            if isinstance(pointer, dict) and pointer.get("runId"):
                out.append((subject, str(pointer["runId"])))
    return out, []


def evidence_committed(git_root, phase_file_rel, evidence_rel):
    """A committed pointer names a run the repository actually holds.

    THE OTHER HALF OF `audit-state-scope`. That one grades what a commit STAGED;
    this grades what the committed plan POINTS AT. A `testEvidence` block is a
    cache at a row in the ledger, so a pointer that survives a clone while its row
    does not is a plan referring to evidence that did not travel with it - and the
    working tree is exactly where that looks fine.

    THE CLAIM IS NARROWER THAN THE INVARIANT, AND THE DIFFERENCE IS STATED. It
    asks about HEAD and not about every state this phase ever committed: a pointer
    that was briefly unsupported and has since been repaired is not a fault a
    reader can act on, and reporting it forever would make the check noise. What
    a clone receives today is the thing worth grading.

    NOT-APPLICABLE, NEVER A BREACH, when the evidence directory sits outside the
    git root: it cannot be committed at all there, so the plan is not at fault for
    naming rows git was never going to hold. Step 4c degrades for that layout and
    so does this.
    """
    if not evidence_rel:
        return result("evidence-committed", EVIDENCE_COMMITTED_BASIS, [], [], 0,
                      applies=False)
    ok, why = _git_available(git_root)
    if not ok:
        return result("evidence-committed", EVIDENCE_COMMITTED_BASIS, [], [why], 0)
    pointers, gaps = _committed_pointers(git_root, phase_file_rel)
    if not pointers:
        # NOT-APPLICABLE rather than no-basis: there was nothing to resolve, and
        # `no-basis` is the word for a check that WANTED to look and could not.
        # Where a gap stopped the reading, it applies and the gap is what says so.
        return result("evidence-committed", EVIDENCE_COMMITTED_BASIS, [], gaps, 0,
                      applies=bool(gaps))
    known, more_gaps = _committed_run_ids(git_root, evidence_rel)
    gaps = gaps + more_gaps
    breaches = []
    for subject, run_id in pointers:
        if run_id not in known:
            breaches.append(found(
                "%s points at run %s, and no evidence row HEAD holds carries "
                "that id - the plan as cloned refers to a run the repository "
                "does not have" % (subject, run_id),
                "%s run %s" % (subject, run_id)))
    return result("evidence-committed", EVIDENCE_COMMITTED_BASIS, breaches, gaps,
                  len(pointers))


# --- branch history -----------------------------------------------------------
# THE TWO LIMITS BELONG IN THE BASIS, NOT IN THE GAPS, and the difference is not
# cosmetic. A gap that is appended on every run makes `clean` unreachable, and a
# verdict nothing can ever reach carries no information - within a week a reader
# learns that this check always says `partial` and stops reading it. These two are
# properties of the METHOD (true of every phase, healthy or not); a gap is meant to
# name evidence THIS phase has lost.
BRANCH_HISTORY_BASIS = ("the remote-tracking refs for the phase branch, that "
                        "branch's own reflog compared pairwise for ancestry, and "
                        "`git reflog show refs/stash`. Reads THIS clone only, so a "
                        "push made from another clone leaves nothing here; and a "
                        "stash DROPPED rather than popped leaves no reflog entry, "
                        "so a clean refs/stash is evidence and not proof")

# What a local `git push` writes into the remote-tracking ref's reflog. A `fetch`
# writes "fetch <remote>" instead, which is why the two can be told apart at all.
_PUSH_MESSAGE = "update by push"

# Reflog messages that name a rewrite by verb. The non-fast-forward test below
# catches the ones that MOVED the tip; these catch the ones that were run and
# happened to land somewhere reachable, which the ancestry test cannot see.
_REWRITE_WORDS = ("reset:", "rebase", "filter-branch", "branch: Reset to")


def _reflog(git_root, ref, fmt):
    """(entries, reason). `entries` is a list of lines; `reason` says why not."""
    code, out = _git(git_root, ["reflog", "show", "--format=" + fmt, ref])
    if code is None:
        return [], "git could not be asked for the reflog of %s" % (ref,)
    if code != 0:
        return [], ("git has no reflog for %s - the ref was deleted (sign-off "
                    "step 4e does exactly that), or core.logAllRefUpdates is off"
                    % (ref,))
    return [ln for ln in out.splitlines() if ln.strip()], ""


def branch_history(phase, git_root):
    """No push, no forced update, no stash on this phase's branch.

    THE FORCED-UPDATE TEST IS ANCESTRY, NOT VOCABULARY. Matching reflog messages
    finds `reset:` and `rebase` and misses everything spelled some other way; the
    question underneath all of them is whether the tip ever moved to a commit the
    previous tip is not an ancestor of. That is one `merge-base --is-ancestor` per
    consecutive pair and it is exact, so the word list is kept only for the
    rewrites that landed somewhere still reachable - where ancestry says nothing.
    """
    breaches, gaps = [], []
    branch = (phase or {}).get("branch")
    if not branch:
        return result("branch-history", BRANCH_HISTORY_BASIS, [], [], 0,
                      applies=False)
    ok, why = _git_available(git_root)
    if not ok:
        return result("branch-history", BRANCH_HISTORY_BASIS, [], [why], 0)

    examined = 0
    branch = str(branch)

    # -- push ------------------------------------------------------------------
    code, refs = _git(git_root, ["for-each-ref", "--format=%(refname)",
                                 "refs/remotes"])
    if code is None or code != 0:
        gaps.append("git would not list refs/remotes, so whether this branch "
                    "reached a remote is unknown")
    else:
        examined += 1
        tracking = [r.strip() for r in refs.splitlines()
                    if r.strip().endswith("/" + branch)]
        for ref in tracking:
            entries, _why = _reflog(git_root, ref, "%gs")
            pushed = [e for e in entries if e.startswith(_PUSH_MESSAGE)]
            breaches.append(found(
                "the phase branch exists as %s%s. `push` is forbidden in any form "
                "and the branch is local-only by design"
                % (ref, " and its reflog records a push" if pushed else ""),
                "remote %s" % (ref,), local=True))

    # -- forced update ---------------------------------------------------------
    entries, why = _reflog(git_root, branch, "%H %gs")
    if why:
        gaps.append(why)
    else:
        examined += 1
        rows = []
        for line in entries:
            parts = line.split(None, 1)
            rows.append((parts[0], parts[1] if len(parts) > 1 else ""))
        for i in range(len(rows) - 1):
            newer, message = rows[i]
            older = rows[i + 1][0]
            code, _out = _git(git_root, ["merge-base", "--is-ancestor",
                                         older, newer])
            if code == 1:
                breaches.append(found(
                    "the branch tip moved from %s to %s without the first being "
                    "an ancestor of the second (%r) - a forced update rewrote "
                    "history the manifest's SHAs point into"
                    % (older[:12], newer[:12], message),
                    "forced update from %s" % (older,), newer, local=True))
        for row_sha, message in rows:
            if any(word in message for word in _REWRITE_WORDS):
                breaches.append(found(
                    "the branch reflog records %r, a history rewrite the "
                    "orchestrator may not run without explicit human "
                    "confirmation" % (message,),
                    "reflog %s" % (message,), row_sha, local=True))

    # -- stash -----------------------------------------------------------------
    # NO `refs/stash` IS AN ANSWER, NOT A GAP - it is the normal state of a
    # repository nobody stashed in, so `_reflog`'s refusal counts as examined
    # exactly like a ref that was read. What it is NOT is proof: a stash dropped
    # rather than popped takes its entry with it, and the basis says so.
    entries, _why = _reflog(git_root, "refs/stash", "%gs")
    examined += 1
    # Case-insensitive: `git stash push -m x` writes "On <branch>: x" while a bare
    # `git stash` writes "WIP on <branch>: ...". Matching one spelling would pass
    # every repository that used the other.
    needle = ("on %s:" % branch).lower()
    for message in entries:
        if needle in message.lower():
            breaches.append(found(
                "the stash reflog records %r - the executor must never run `git "
                "stash` in a shared working tree" % (message,),
                "stash %s" % (message,), local=True))
    return result("branch-history", BRANCH_HISTORY_BASIS, breaches, gaps, examined)


# --- manifest revalidated -----------------------------------------------------
MANIFEST_VALID_BASIS = ("the manifest as it stood at each commit this phase "
                        "recorded, re-read with `git show` and run back through "
                        "the same validator `/audit:status` uses - plus the "
                        "journal rows whose stateHash names bytes git no longer "
                        "holds")


def _materialize(git_root, sha, index_rel, tmpdir):
    """Write the whole manifest as of `sha` into `tmpdir`. Returns its path, or None.

    The INDEX ALONE IS NOT THE MANIFEST under the sharded layout, and validating
    it alone would report every phase as an empty stub - so each shard the index
    names is fetched at the same commit and written beside it. `load_manifest`
    then assembles the two exactly as it does on disk, which is what keeps this
    from being a second opinion about what a manifest is.
    """
    code, text = _git(git_root, ["show", "%s:%s" % (sha, index_rel)])
    if code is None or code != 0:
        return None
    try:
        index = json.loads(text)
    except ValueError:
        return None
    out_path = os.path.join(tmpdir, index_rel.replace("/", os.sep))
    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    if not _mio.is_sharded(index):
        return out_path
    base = os.path.dirname(index_rel)
    for stub in (index.get("phases") or []):
        if not (isinstance(stub, dict) and stub.get("shard")):
            continue
        rel = "/".join(p for p in (base, str(stub["shard"])) if p)
        code, body = _git(git_root, ["show", "%s:%s" % (sha, rel)])
        if code is None or code != 0:
            return None
        shard_path = os.path.join(tmpdir, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(shard_path), exist_ok=True)
        with open(shard_path, "w", encoding="utf-8") as fh:
            fh.write(body)
    return out_path


def _recorded_states(project, phase_file_abs):
    """The stateHash of every journal row that recorded a write to this file.

    Rows, not writes: the journal is the only record that a write happened at
    all, and its `stateHash` is the only handle on the bytes that write left
    behind. A row whose hash matches nothing git still holds is the coverage gap
    this function exists to make countable.
    """
    try:
        rel = _output.posix_rel(phase_file_abs, project)
    except Exception:
        return []
    try:
        rows = _journal_io.read_all(project)
    except Exception:
        return []
    return [r.get("stateHash") for r in rows
            if isinstance(r, dict) and str(r.get("target") or "") == rel
            and r.get("stateHash")]


# `task <id>: file '<path>' missing from fileIndex (...)` - the crossref's own
# spelling, read back for the task id it names.
_PAIRING_TASK = re.compile(r"^task (\S+): file ")


def own_pairing_findings(findings, phase):
    """The pairing findings that name one of THIS phase's tasks.

    The live re-check validates the whole manifest, and another phase that is
    mid-flight has unpaired rows by construction (step 4c). Those are that
    phase's to settle; reported here they would be a breach charged to a phase
    that did nothing.
    """
    own = set(str(t.get("id")) for t in ((phase or {}).get("tasks") or [])
              if isinstance(t, dict))
    out = []
    for line in findings:
        if _crossrefs.FILEINDEX_PAIRING not in line:
            continue
        match = _PAIRING_TASK.match(line)
        if match and match.group(1) in own:
            out.append(line)
    return out


_VALIDATOR_CRASH = "internal validator error: %s"


def _validator_subject(line):
    """A validator finding's key: its locus and ids, or the crash as one fact.

    An exception's text is not an identity - it would make every run a new
    breach - so a validator that could not run is keyed on that alone.
    """
    if line.startswith(_VALIDATOR_CRASH.split("%", 1)[0]):
        return "validator could not run"
    return "validator %s" % (_rules.finding_subject(line),)


def manifest_revalidated(phase, git_root, project, index_rel, phase_file_rel,
                         phase_file_abs):
    """Every manifest state this phase COMMITTED still validates.

    THE CLAIM IS NARROWER THAN THE INVARIANT, AND THE DIFFERENCE IS STATED RATHER
    THAN PAPERED OVER. `orchestrator.md` says revalidate after every WRITE; a
    write between two commits left bytes nowhere, so nothing can re-run the
    validator on it. What is checkable is every state a commit preserved, and how
    many recorded writes fall outside that - which is the number this reports
    instead of a reassuring silence.
    """
    breaches, gaps = [], []
    # Two different quantities, kept apart on purpose: the crossref emits one
    # finding per task-and-file pair still unpaired AT THAT COMMIT, and the same
    # unresolved pair is reported again by every later commit until the chore
    # commit settles it. Summing findings across the commit loop below therefore
    # counts commits multiplied by unpaired rows, not either one - a repeated
    # edit read as a growing backlog. `pairing_deferred_commits` is incremented
    # once per commit that carried at least one such finding, which is the
    # quantity "task commit(s)" below actually names; the row count is read
    # straight off the CURRENT manifest further down, where it is unambiguous.
    pairing_deferred_commits = 0
    commits = []
    for task in (phase.get("tasks") or []):
        if isinstance(task, dict) and task.get("commit"):
            sha = str(task["commit"])
            if sha not in commits:
                commits.append(sha)
    if not commits:
        return result("manifest-revalidated", MANIFEST_VALID_BASIS, [], [], 0,
                      applies=False)
    ok, why = _git_available(git_root)
    if not ok:
        return result("manifest-revalidated", MANIFEST_VALID_BASIS, [], [why], 0)
    if not index_rel:
        return result("manifest-revalidated", MANIFEST_VALID_BASIS, [],
                      ["the manifest lives outside the git root, so no commit "
                       "carries a copy of it to re-validate"], 0)

    examined = 0
    seen_hashes = set()
    tmp = tempfile.mkdtemp(prefix="audit-invariants-")
    try:
        for sha in commits:
            full = full_sha(git_root, sha)
            work = os.path.join(tmp, sha[:12])
            os.makedirs(work, exist_ok=True)
            path = _materialize(git_root, sha, index_rel, work)
            if path is None:
                gaps.append("%s: the manifest as of this commit could not be "
                            "reassembled from git, so the validator could not be "
                            "re-run on it" % (sha[:12],))
                continue
            # The PHASE's file, not the index: the journal rows this is compared
            # against name the shard, and hashing the index instead would make
            # every recorded write look unrecoverable under the sharded layout.
            if phase_file_rel:
                state = _journal_io.file_hash(
                    os.path.join(work, phase_file_rel.replace("/", os.sep)))
                if state:
                    seen_hashes.add(state)
            try:
                state_manifest = _mio.load_manifest(path)
            except Exception as exc:
                gaps.append("%s: the manifest as of this commit will not load "
                            "(%s)" % (sha[:12], exc))
                continue
            examined += 1
            try:
                findings, _warnings = _rules.validate(state_manifest)
            except Exception as exc:                       # defensive
                findings = [_VALIDATOR_CRASH % (exc,)]
            # Counted per COMMIT, not per finding: the crossref emits one line
            # per task-and-file pair still unpaired at this commit, and a task
            # whose scope grew mid-run leaves the SAME pair unpaired in every
            # commit after it until the chore commit settles the index. Adding
            # every line across every commit would multiply commits by unpaired
            # rows - measured on two separate live runs, 39 breaches across 10
            # of 12 tasks, and 93 in one phase of another, both of them this
            # product wearing the name of a backlog. What matters here is only
            # whether THIS commit carried the deferral at all.
            commit_deferred_pairing = False
            for line in findings:
                # THE ONE FINDING A TASK COMMIT CANNOT AVOID. `task.files`
                # lives in the phase shard and `fileIndex` lives in the index, and
                # step 4c forbids a task commit from staging the index - for a
                # good reason, since two phases committing it in parallel conflict
                # on the same lines. So a task whose scope is corrected mid-run
                # commits a shard the committed index does not yet pair with, and
                # EVERY later commit in that phase reported it. It punished the
                # right instinct - fixing the plan when reality differed - and
                # there was no commit ordering that avoided it.
                #
                # Recorded as a gap rather than a breach HERE ONLY. `validate()`
                # keeps the finding for every whole-manifest caller, and the
                # pairing is asserted against the CURRENT state below, so this
                # exempts a moment rather than the rule: mid-phase it cannot be
                # true, by sign-off it must be.
                if _crossrefs.FILEINDEX_PAIRING in line:
                    commit_deferred_pairing = True
                    continue
                breaches.append(found(
                    "%s: the manifest this commit recorded does NOT validate - %s"
                    % (sha[:12], line), _validator_subject(line), full))
            if commit_deferred_pairing:
                pairing_deferred_commits += 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ...AND THE DEFERRAL IS PAID HERE. Exempting the pairing per commit
    # without asking it of anything would be a hole, not a fix: the rule is not
    # "never true", it is "not true YET". The manifest as it stands now is the
    # state sign-off is about to preserve, so that is where it is asked - and a
    # failure is a real breach, naming how many commits deferred it AND how many
    # rows are still unpaired, because those are two different numbers and
    # neither one's name covers the other.
    if pairing_deferred_commits:
        try:
            live_findings, _lw = _rules.validate(_mio.load_manifest(
                os.path.join(project, index_rel.replace("/", os.sep))))
        except Exception as exc:
            gaps.append("the pairing of task.files with fileIndex was deferred by "
                        "%d commit(s) and the current manifest could not be loaded "
                        "to settle it (%s)" % (pairing_deferred_commits, exc))
            live_findings = []
        still = own_pairing_findings(live_findings, phase)
        if still:
            breaches.extend(
                [found("the manifest as it stands STILL does not pair task.files "
                       "with fileIndex - %s" % (x,),
                       "unpaired %s" % (_rules.finding_subject(x),))
                 for x in still])
            # The counts are for the reader. The key names only the fact, so a
            # frozen phase's entry matches whatever the counts read next time.
            breaches.append(found(
                "%d task commit(s) deferred this pairing, leaving %d row(s) "
                "unpaired now, which step 4c makes unavoidable mid-phase; by "
                "sign-off it has to be settled - run `/audit:task scope <id> "
                "--files ...` to re-derive the index"
                % (pairing_deferred_commits, len(still)), "pairing deferred"))

    recorded = _recorded_states(project, phase_file_abs)
    unrecoverable = [h for h in recorded if h not in seen_hashes]
    if not recorded:
        gaps.append("the journal holds no row for this phase's manifest file, so "
                    "how many writes there were is not known here")
    elif unrecoverable:
        gaps.append("%d of the %d journal-recorded writes to this phase's "
                    "manifest file left bytes no commit preserved; the validator "
                    "cannot be re-run on those states"
                    % (len(unrecoverable), len(recorded)))
    return result("manifest-revalidated", MANIFEST_VALID_BASIS, breaches, gaps,
                  examined)


# --- high-risk model ----------------------------------------------------------
HIGH_RISK_BASIS = ("`task.model` (falling back to `phase.model`) for every "
                   "`risk: \"high\"` task, and the usage ledger's `model` for "
                   "the rows that carry that task's id")

# The one model name the invariant forbids, matched as a substring because a
# ledger row carries a full id (`claude-3-5-haiku-20241022`) while a manifest
# carries the short alias. Matching either spelling exactly would miss the other.
_FORBIDDEN_MODEL = "haiku"


def high_risk_model(phase, ledger_dir):
    """A `risk: "high"` task never ran on haiku - declared, and as metered.

    TWO SOURCES, BECAUSE THEY FAIL DIFFERENTLY. The manifest says what was asked
    for and is present even when metering is off; the ledger says what actually
    answered and is the only one that catches a spawn that ignored `task.model`.
    A check with only the first reports a compliant manifest as compliance; a
    check with only the second reports every unmetered repository as unknown.
    """
    breaches, gaps = [], []
    high = [t for t in (phase.get("tasks") or [])
            if isinstance(t, dict) and str(t.get("risk") or "").lower() == "high"]
    if not high:
        return result("high-risk-model", HIGH_RISK_BASIS, [], [], 0, applies=False)

    examined = 0
    rows_by_task = {}
    if ledger_dir:
        try:
            for row in usage_ledger.read_ledger(ledger_dir):
                if not isinstance(row, dict):
                    continue
                tid = str(row.get("taskId") or "")
                if tid:
                    rows_by_task.setdefault(tid, []).append(
                        str(row.get("model") or ""))
        except Exception as exc:
            gaps.append("the usage ledger at %s could not be read (%s), so what "
                        "actually ran is unknown" % (ledger_dir, exc))
    else:
        gaps.append("no usage ledger was found for this manifest, so only the "
                    "manifest's own routing could be checked - a spawn that "
                    "ignored `task.model` would leave no trace here")

    for task in high:
        tid = str(task.get("id"))
        examined += 1
        declared = task.get("model") or phase.get("model")
        if declared and _FORBIDDEN_MODEL in str(declared).lower():
            breaches.append(found(
                "%s is risk \"high\" and the manifest routes it to %r"
                % (tid, str(declared)),
                "%s declared %s" % (tid, str(declared))))
        models = rows_by_task.get(tid)
        if models is None:
            if ledger_dir:
                gaps.append("%s: the ledger has no row carrying this task id, so "
                            "which model answered is not recorded (the executor "
                            "is spawned with the id in its description exactly so "
                            "that it would be)" % (tid,))
            continue
        offenders = sorted(set(m for m in models
                               if _FORBIDDEN_MODEL in m.lower()))
        for model in offenders:
            breaches.append(found(
                "%s is risk \"high\" and the ledger records %s answering for it"
                % (tid, model), "%s metered %s" % (tid, model), local=True))
    return result("high-risk-model", HIGH_RISK_BASIS, breaches, gaps, examined)


# --- base ref -----------------------------------------------------------------
BASE_REF_BASIS = ("`git merge-base --is-ancestor <phase.baseRef> <parent>`, "
                  "where the parent is `phase.parentBranch ?? "
                  "meta.developmentBranch` as `_branch.parent_branch` resolves it")


def base_ref(manifest, phase, git_root):
    """`phase.baseRef` is on the branch the phase was supposed to fork from.

    ANCESTRY, NOT EQUALITY, and the difference is not a weakening. `baseRef` was
    the parent's tip at branch time and the parent has moved since - on any repo
    with other work in it, always. What survives that is the ancestry: a phase cut
    from the parent has a `baseRef` the parent still contains, and a phase cut
    from somewhere else does not. Equality would report every healthy phase on a
    busy repository as a breach, which is the fastest way to get a check switched
    off.
    """
    breaches, gaps = [], []
    resolved = _branch.parent_branch((manifest or {}).get("meta") or {}, phase)
    parent = resolved["branch"]
    # The RESOLVED parent and the key that chose it travel in the basis, not only
    # in the failure lines. A verdict rendered against the wrong branch is the one
    # mistake this check can make silently, and a reader comparing the printed
    # basis with the manifest is the only thing that catches it.
    basis = "%s - resolved here as %r (%s)" % (BASE_REF_BASIS, parent,
                                               resolved["basis"])
    ref = (phase or {}).get("baseRef")
    branch = (phase or {}).get("branch")
    if not ref and not branch:
        return result("base-ref", basis, [], [], 0, applies=False)
    if not ref:
        return result("base-ref", basis,
                      [found("the phase is on branch %r and recorded no baseRef, "
                             "so what it forked from cannot be checked at all - "
                             "step 1b writes it before the branch is cut"
                             % (str(branch),), "no baseRef on %s" % (str(branch),))],
                      [], 1)
    ok, why = _git_available(git_root)
    if not ok:
        return result("base-ref", basis, [], [why], 0)

    code, _out = _git(git_root, ["rev-parse", "-q", "--verify",
                                 "%s^{commit}" % str(ref)])
    if code is None or code != 0:
        return result("base-ref", basis, [],
                      ["the recorded baseRef %s does not resolve in this clone, "
                       "so it cannot be compared with %s (%s)"
                       % (str(ref)[:12], parent, resolved["basis"])], 0)
    code, _out = _git(git_root, ["rev-parse", "-q", "--verify",
                                 "%s^{commit}" % parent])
    if code is None or code != 0:
        return result("base-ref", basis, [],
                      ["the parent branch %r (%s) does not exist in this clone, "
                       "so there is nothing to compare the baseRef against"
                       % (parent, resolved["basis"])], 0)
    code, _out = _git(git_root, ["merge-base", "--is-ancestor", str(ref), parent])
    if code is None:
        return result("base-ref", basis, [],
                      ["git would not answer the ancestry question"], 0)
    if code != 0:
        breaches.append(found(
            "baseRef %s is not an ancestor of %r (%s), so this phase was not cut "
            "from the branch it merges back into"
            % (str(ref)[:12], parent, resolved["basis"]),
            "parent %s" % (parent,), full_sha(git_root, str(ref))))
    return result("base-ref", basis, breaches, gaps, 1)


# --- the whole phase ----------------------------------------------------------
def check_phase(manifest, phase_id, manifest_path, git_root, project,
                ledger_dir=None):
    """Every invariant, for one phase. `{"found": False}` when there is no such phase.

    `ledger_dir` is passed in rather than resolved here, and `None` MEANS "there
    is none" rather than "look it up". A library that quietly went looking would
    make the difference between an unmetered repository and a mislocated ledger
    invisible to the caller, and the whole point of this module is that the two
    read differently.
    """
    phase = phase_of(manifest, phase_id)
    if phase is None:
        return {"found": False, "phaseId": str(phase_id), "checks": [],
                "breaches": [], "gaps": []}
    git_root_rel = ((manifest or {}).get("meta") or {}).get("gitRoot") or ""
    if git_root_rel == ".":
        git_root_rel = ""            # "." is not a prefix any recorded file carries
    index_abs, phase_file_abs = manifest_files(manifest_path, phase)
    index_rel = _rel(index_abs, git_root)
    phase_file_rel = _rel(phase_file_abs, git_root)
    try:
        journal_rel = _rel(_journal_io.journal_dir(project), git_root)
    except Exception:
        journal_rel = None
    try:
        evidence_rel = _rel(_evidence_io.evidence_dir(project), git_root)
    except Exception:
        evidence_rel = None

    checks = [
        commit_scope(phase, git_root, git_root_rel, phase_file_rel, index_rel,
                     journal_rel, evidence_rel),
        # THE SAME `evidence_rel`, resolved once above and handed to both. Two
        # resolutions of "where does this manifest keep its evidence" is how one
        # check comes to allow a directory the other reports.
        audit_state_scope(phase, git_root, project, phase_file_rel, index_rel,
                          journal_rel, evidence_rel),
        # THE SAME `index_rel` AND `phase_file_rel` the two above are given, and
        # the argument order is the one that reads: this check's allow-list is
        # the index, and the phase's file is the thing it must NOT carry, so the
        # pair arrives the other way round from `audit_state_scope`'s.
        index_scope(phase, git_root, project, index_rel, phase_file_rel),
        evidence_committed(git_root, phase_file_rel, evidence_rel),
        branch_history(phase, git_root),
        manifest_revalidated(phase, git_root, project, index_rel,
                             phase_file_rel, phase_file_abs),
        high_risk_model(phase, ledger_dir),
        base_ref(manifest, phase, git_root),
    ]
    order = dict((name, i) for i, name in enumerate(CHECK_NAMES))
    checks.sort(key=lambda c: order.get(c["name"], len(order)))
    return {
        "found": True,
        "phaseId": str(phase_id),
        "branch": phase.get("branch"),
        "checks": checks,
        "breaches": ["%s: %s" % (c["name"], line)
                     for c in checks for line in c["breaches"]],
        "gaps": ["%s: %s" % (c["name"], line)
                 for c in checks for line in c["gaps"]],
    }


def started_phases(manifest):
    """Phase ids with something to check: a branch, a baseRef or a recorded commit.

    A pending phase has left no evidence, and running the checks over it would
    produce a page of `not-applicable` that buries the phases that matter. Which
    ids were skipped is still reported by the caller, so "we looked at three of
    eleven" never prints as "eleven are fine".
    """
    out = []
    for phase in ((manifest or {}).get("phases") or []):
        if not isinstance(phase, dict):
            continue
        started = bool(phase.get("branch") or phase.get("baseRef"))
        if not started:
            started = any(isinstance(t, dict) and t.get("commit")
                          for t in (phase.get("tasks") or []))
        if started:
            out.append(str(phase.get("id")))
    return out


def check_manifest(manifest, manifest_path, git_root, project, ledger_dir=None):
    """Every started phase, folded into one answer - what `--gate` reads.

    `skipped` is part of the answer rather than an omission: a gate that says
    "no breaches" over a manifest whose phases were all skipped has made a claim
    about nothing, and the caller needs the two apart to render either honestly.
    """
    ids = started_phases(manifest)
    all_ids = [str(p.get("id")) for p in ((manifest or {}).get("phases") or [])
               if isinstance(p, dict)]
    phases = [check_phase(manifest, pid, manifest_path, git_root, project,
                          ledger_dir=ledger_dir) for pid in ids]
    return {
        "checked": ids,
        "skipped": [pid for pid in all_ids if pid not in ids],
        "phases": phases,
        "breaches": ["%s %s" % (p["phaseId"], line)
                     for p in phases for line in p["breaches"]],
        "gaps": ["%s %s" % (p["phaseId"], line)
                 for p in phases for line in p["gaps"]],
    }


# --- the baseline -------------------------------------------------------------
BASELINE_NAME = "invariants-baseline.json"
BASELINE_VERSION = 3

# LOCALITY IS PER BREACH, NOT PER CHECK. A reflog, the stash, a remote-tracking
# ref and the gitignored usage ledger are one clone's evidence, so an entry built
# from one of them (`found(..., local=True)`) records WHICH clone wrote it, as a
# digest of that clone's git common dir - a path would name a machine in a
# committed file. On that clone it is compared like any other entry and can go
# stale; on any other it is set aside, since that clone never had the evidence.

# The three reasons an entry is set aside rather than compared, each a sentence.
NOT_COMPARED_PHASE = "its phase was not examined in this run"
NOT_COMPARED_BASIS = ("its check had no full basis in this run (a gap or no "
                      "basis), so a missing breach is not evidence of a repair")
NOT_COMPARED_LOCAL = ("it was read from another clone's own evidence (a reflog, "
                      "the stash, a remote-tracking ref or the usage ledger), "
                      "which this clone does not have")

REWRITE_RULE = (
    "an entry is matched on its phase, check, subject and full commit SHA - never "
    "on the printed sentence, so a reworded message still matches; a validator "
    "finding's subject is its locus and the ids it quotes, so rewording one "
    "matches too, while renaming its locus or ids does not. A rebase, squash "
    "or amend gives a commit a new SHA, so its breach is listed as NEW and its old "
    "entry as no longer matching - review both, then have a human re-run "
    "--write-baseline")

BASELINE_ABOUT = (
    "Breach fingerprints verify-invariants.py and /audit:status --gate report as "
    "known rather than new. Written only by --write-baseline, which refuses while "
    "a phase it covers is in flight; a human commits it on the development "
    "branch, outside any phase commit - a task, audit-state or manifest-index "
    "commit that staged it would breach its own scope. An entry read from one "
    "clone's own evidence carries that clone's digest and is compared only "
    "there. %s." % (REWRITE_RULE[0].upper() + REWRITE_RULE[1:],))


def clone_id(git_root):
    """A digest of this clone's git common dir, or None outside a repository.

    Every worktree of one clone shares the common dir, so they share the id; two
    clones of one repository do not.
    """
    ld = _locks.lock_dir(git_root)
    if not ld:
        return None
    return hashlib.sha256(os.path.dirname(ld).encode("utf-8")).hexdigest()[:16]


def baseline_path_for(manifest_path):
    """Where the baseline lives: beside the manifest, next to its records."""
    return os.path.join(os.path.dirname(os.path.abspath(manifest_path)),
                        BASELINE_NAME)


def _answers(result):
    """The per-phase answers in `result`, whichever of the two shapes it has."""
    return result["phases"] if "phases" in result else [result]


def baseline_key(entry):
    return (entry["phase"], entry["check"], entry["subject"], entry.get("sha"))


def _fingerprint(phase_id, check, line, key, clone):
    return {"phase": str(phase_id), "check": check, "subject": key["subject"],
            "sha": key["sha"], "breach": line,
            "clone": clone if key.get("local") else None}


def fingerprints(result, clone=None):
    """One entry per distinct breach in `result`, in a total order.

    `clone` is stamped on the entries read from local evidence, and only there.
    """
    seen = {}
    for answer in _answers(result):
        for check in answer.get("checks") or []:
            for line, key in zip(check["breaches"], check["keys"]):
                entry = _fingerprint(answer["phaseId"], check["name"], line, key,
                                     clone)
                seen[baseline_key(entry)] = entry
    return [seen[k] for k in sorted(seen, key=lambda k: tuple(x or "" for x in k))]


def read_baseline(path):
    """`(entries, None)`, or `(None, why)` when the file is not a baseline.

    A file that is there and cannot be read is an error and never an empty
    baseline: reading it as empty would print every frozen breach as new, and
    reading it as absent would print them all without saying one was asked for.
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
                        for k in ("phase", "check", "subject"))
                and (row.get("sha") is None or isinstance(row.get("sha"), str))
                and (row.get("clone") is None
                     or isinstance(row.get("clone"), str))):
            return None, ("the baseline %s holds an entry without a phase, a "
                          "check and a subject (an older baseline matched on the "
                          "printed sentence - write it again): %r" % (path, row))
        entries.append({"phase": row["phase"], "check": row["check"],
                        "subject": row["subject"], "sha": row.get("sha"),
                        "breach": str(row.get("breach") or ""),
                        "clone": row.get("clone")})
    return entries, None


def _check_bases(result):
    """`{(phaseId, check): True}` for every check this run read in full."""
    out = {}
    for answer in _answers(result):
        for check in answer.get("checks") or []:
            full = (not check["gaps"]
                    and check["verdict"] in (CLEAN, BREACH))
            out[(str(answer["phaseId"]), check["name"])] = full
    return out


def compare_baseline(entries, result, clone=None):
    """Split the baseline and this run's breaches against each other.

    Only an entry this run could have seen again is called unmatched. One whose
    phase was not examined, whose check had a gap, or whose check reads evidence
    no clone receives is set aside with the reason - a missing basis is the thing
    to say, and reading it as a repair would be a claim about evidence nobody
    read.
    """
    current = fingerprints(result, clone)
    examined = set(str(a["phaseId"]) for a in _answers(result))
    bases = _check_bases(result)
    known = set(baseline_key(e) for e in entries)
    now = set(baseline_key(e) for e in current)
    unmatched, aside = [], {}
    for entry in entries:
        if baseline_key(entry) in now:
            continue
        if entry["phase"] not in examined:
            why = NOT_COMPARED_PHASE
        elif entry.get("clone") and entry["clone"] != clone:
            why = NOT_COMPARED_LOCAL
        elif not bases.get((entry["phase"], entry["check"])):
            why = NOT_COMPARED_BASIS
        else:
            unmatched.append(entry)
            continue
        aside[why] = aside.get(why, 0) + 1
    return {
        "entries": len(entries),
        "matched": len([e for e in current if baseline_key(e) in known]),
        "new": [e for e in current if baseline_key(e) not in known],
        "unmatched": unmatched,
        "notCompared": sum(aside.values()),
        "notComparedWhy": aside,
    }


def _commit_state(git_root, sha, cut):
    """What git says about one commit a stale entry names, as a sentence."""
    state = _commit_trail.resolve(git_root, sha, cut=cut)
    if state == "absent":
        return ("commit %s is not in this clone - a rewrite whose old commits "
                "were collected, or history this clone never fetched" % (sha[:12],))
    if state != "present":
        return ("whether commit %s is in this clone could not be asked (no git, "
                "or a shallow clone)" % (sha[:12],))
    code, refs = _git(git_root, ["for-each-ref", "--contains", sha, "--count=1",
                                 "--format=%(refname)"])
    if code is None or code != 0:
        return "git would not say which refs contain commit %s" % (sha[:12],)
    if not refs.strip():
        return ("commit %s is reachable from no branch or tag - a rebase, squash "
                "or amend rewrote it, or its branch was deleted" % (sha[:12],))
    return None


def explain_unmatched(entries, git_root):
    """Each stale entry with `reason`: what became of the commit it names."""
    if not entries:
        return []
    cut = _commit_trail.is_shallow(git_root) is not False
    out = []
    for entry in entries:
        why = _commit_state(git_root, entry["sha"], cut) if entry.get("sha") else None
        row = dict(entry)
        row["reason"] = why or (
            "the check read its evidence in full and no longer reports this "
            "subject%s - it was repaired"
            % (" at a still-reachable commit" if entry.get("sha") else ""))
        out.append(row)
    return out


def apply_baseline(result, manifest_path, git_root, path=None):
    """`(block, None)`, `(None, None)` with no baseline, or `(None, why)`.

    `path` given means the caller named a baseline, and one that is not there is
    an error; left None it is the file beside the manifest, used when present.
    """
    explicit = path is not None
    path = os.path.abspath(path if explicit else baseline_path_for(manifest_path))
    if not os.path.isfile(path):
        if explicit:
            return None, ("no baseline at %s - a human writes one with "
                          "--write-baseline" % (path,))
        return None, None
    entries, why = read_baseline(path)
    if why:
        return None, why
    block = compare_baseline(entries, result, clone_id(git_root))
    block["unmatched"] = explain_unmatched(block["unmatched"], git_root)
    block["path"] = path
    block["rewriteRule"] = REWRITE_RULE
    return block, None


def counted_breaches(result):
    """The breach lines a verdict is taken on: every one, or only the new ones.

    The ONE answer both surfaces read, so a baseline that hides a frozen breach
    from `verify-invariants.py` hides it from the gate as well.
    """
    block = result.get("baseline")
    if not block:
        return list(result["breaches"])
    return ["%s %s: %s" % (e["phase"], e["check"], e["breach"])
            for e in block["new"]]


def in_flight(manifest, phase_ids):
    """The ids in `phase_ids` whose phase is not done or cancelled."""
    wanted = set(str(p) for p in phase_ids)
    return [str(p.get("id")) for p in ((manifest or {}).get("phases") or [])
            if isinstance(p, dict) and str(p.get("id")) in wanted
            and _mio.effective_phase_status(p) not in _mio.TERMINAL]


def _stored(entry):
    """An entry as the file holds it - `clone` only where it says something."""
    row = dict((k, entry[k]) for k in ("phase", "check", "subject", "sha",
                                        "breach"))
    if entry.get("clone"):
        row["clone"] = entry["clone"]
    return row


def write_baseline(path, result, manifest, git_root):
    """Write the baseline -> `(answer, None)` or `(None, why)`.

    REFUSED WHILE A PHASE IT COVERS IS IN FLIGHT. Baselining a breach is
    accepting it, and a run that could baseline its own breaches would sign
    itself off; the file is a human's, written after the work has landed.

    UNDER AN INDEX LOCK THIS CALL TOOK, READ AND WRITE BOTH. Each write is whole
    on its own, but two writers that each read the old file would have the
    second rename erase the first one's entries while both printed that they
    wrote them. A hold the session already had is refused rather than borrowed:
    two subagents of one session share that hold, so it keeps neither out.

    Entries this run did not compare are carried over unchanged, and what it
    removes is returned, because a rewrite is the one place an entry leaves the
    file and it must not leave without being named.
    """
    examined = [str(a["phaseId"]) for a in _answers(result)]
    busy = in_flight(manifest, examined)
    if busy:
        return None, ("--write-baseline refuses while a phase it covers is in "
                      "flight (%s): baselining a breach is accepting it, which a "
                      "phase run may not do for itself. A human writes the "
                      "baseline once the work has landed and commits it on the "
                      "development branch, outside any phase commit"
                      % (", ".join(busy),))
    if not _locks.available(git_root):
        return None, ("%s is not a git repository, so the baseline write has no "
                      "lock to serialize it" % (git_root,))
    code = _locks.acquire(git_root, "index", note="invariants baseline write",
                          out=lambda _line: None)
    if code == _locks.E_OURS:
        # HELD IS NOT TAKEN. A hold this session already has is also what a
        # parallel subagent of the same session sees, so writing under it would
        # serialize nothing between the two.
        return None, ("this session already holds the index lock, so the "
                      "baseline write could not take it for itself - write the "
                      "baseline outside that hold")
    if not _locks.took(code):
        return None, ("the index lock is not free (%s), so the baseline was not "
                      "written - `audit-lock.py status` says who holds it"
                      % (_locks.refusal(code, "index"),))
    try:
        previous = []
        if os.path.isfile(path):
            previous, why = read_baseline(path)
            if why:
                return None, why
        clone = clone_id(git_root)
        split = compare_baseline(previous, result, clone)
        stale = set(baseline_key(e) for e in split["unmatched"])
        kept = [e for e in previous if baseline_key(e) not in stale]
        merged = dict((baseline_key(e), e)
                      for e in kept + fingerprints(result, clone))
        written = [merged[k] for k in sorted(
            merged, key=lambda k: tuple(x or "" for x in k))]
        _mio.atomic_write_json(path, {
            "about": BASELINE_ABOUT, "version": BASELINE_VERSION,
            "entries": [_stored(e) for e in written]})
    finally:
        if _locks.took(code):
            _locks.release(git_root, "index", out=lambda _line: None)
    return {"path": path, "entries": len(written), "removed": split["unmatched"],
            "kept": split["notCompared"]}, None


# --- cli ----------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        print("_invariants.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__invariants.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
