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

Reads git, the manifest, the journal and the ledger. Writes nothing, takes no
lock, and never raises for the caller: a check that cannot run reports that it
could not run.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__invariants.py`.
"""
import json
import os
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
import _journal_io  # noqa: E402  (the trail: where it lives, its rows, their stateHash)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR shards)
import _manifest_rules as _rules  # noqa: E402  (the validator this re-runs on old states)
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
CHECK_NAMES = ("commit-scope", "branch-history", "manifest-revalidated",
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


def result(name, basis, breaches, gaps, examined, applies=True):
    """One check's answer. `basis` travels with it, always.

    A verdict with no basis beside it is the thing this module exists to replace,
    so the basis is a required argument rather than an optional decoration - the
    caller cannot forget it, because there is nowhere to leave it out.
    """
    return {
        "name": name,
        "verdict": verdict_of(breaches, gaps, examined, applies),
        "basis": basis,
        "breaches": list(breaches),
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
                      "`files`, its phase's manifest file and the journal "
                      "directory - the three things orchestrator.md step 4c "
                      "allows a task commit to stage")


def commit_scope(phase, git_root, git_root_rel, phase_file_rel, index_rel,
                 journal_rel):
    """A task commit staged that task's files, its phase's manifest file, the journal.

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
            if journal_rel and (path == journal_rel
                                or path.startswith(journal_rel + "/")):
                continue
            if index_rel and path == index_rel and index_rel != phase_file_rel:
                breaches.append("%s: commit %s staged the manifest INDEX (%s). A "
                                "task commit changes only its own phase's shard - "
                                "the index is what parallel phases would then "
                                "conflict on" % (tid, sha[:12], index_rel))
                continue
            breaches.append("%s: commit %s staged %s, which is not in the task's "
                            "`files`, is not this phase's manifest file and is not "
                            "in the journal" % (tid, sha[:12], path))
    return result("commit-scope", COMMIT_SCOPE_BASIS, breaches, gaps, examined)


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
            breaches.append("the phase branch exists as %s%s. `push` is forbidden "
                            "in any form and the branch is local-only by design"
                            % (ref, " and its reflog records a push"
                               if pushed else ""))

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
                breaches.append("the branch tip moved from %s to %s without the "
                                "first being an ancestor of the second (%r) - a "
                                "forced update rewrote history the manifest's "
                                "SHAs point into"
                                % (older[:12], newer[:12], message))
        for _sha, message in rows:
            if any(word in message for word in _REWRITE_WORDS):
                breaches.append("the branch reflog records %r, a history rewrite "
                                "the orchestrator may not run without explicit "
                                "human confirmation" % (message,))

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
            breaches.append("the stash reflog records %r - the executor must "
                            "never run `git stash` in a shared working tree"
                            % (message,))
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
                findings = ["internal validator error: %s" % exc]
            for line in findings:
                breaches.append("%s: the manifest this commit recorded does NOT "
                                "validate - %s" % (sha[:12], line))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

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
            breaches.append("%s is risk \"high\" and the manifest routes it to "
                            "%r" % (tid, str(declared)))
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
            breaches.append("%s is risk \"high\" and the ledger records %s "
                            "answering for it" % (tid, model))
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
                      ["the phase is on branch %r and recorded no baseRef, so "
                       "what it forked from cannot be checked at all - step 1b "
                       "writes it before the branch is cut" % (str(branch),)],
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
        breaches.append("baseRef %s is not an ancestor of %r (%s), so this phase "
                        "was not cut from the branch it merges back into"
                        % (str(ref)[:12], parent, resolved["basis"]))
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

    checks = [
        commit_scope(phase, git_root, git_root_rel, phase_file_rel, index_rel,
                     journal_rel),
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


# --- cli ----------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        print("_invariants.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__invariants.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
