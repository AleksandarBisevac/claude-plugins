#!/usr/bin/env python3
"""Commit the manifest INDEX on its own, or say there is nothing to commit.

WHY THIS EXISTS. In the sharded layout the index holds `meta`,
`fileIndex`, `bugs[]`, `deferred`, `proposals` and the phase stubs, and the
shards hold the task bodies. Structural commands write the index: `/audit:task
add --files ...` updates `fileIndex`, `/audit:phase add` appends a stub. But
`orchestrator.md` step 4c forbids a TASK commit from staging the index, and
`commit-audit-state.py` refuses it too -- both for the same stated reason, and
both correctly. So nothing committed the index at all: the structural edits piled
up in a working tree until somebody noticed and committed them by hand. Reported
from a live project, three times in one evening.

WHY IT IS A COMMIT OF ITS OWN AND NOT A WIDER ALLOW-LIST SOMEWHERE ELSE. The
sharded layout was introduced so two phases can run in parallel without meeting
on one file. A commit that carries a phase's work AND the shared index cannot be
landed, reordered or dropped without taking the work with it, which is what makes
that shape expensive when two branches meet. A commit that carries the shared
file ALONE can be landed on its own, cherry-picked on its own, or thrown away and
re-derived (`/audit:task scope` rebuilds `fileIndex`), and its conflicts are
confined to the file it carries. That is the whole design, and it is why widening
`commit-audit-state.py`'s list would have satisfied that script's own
verification -- its allow-list and its staged set are one list -- while
destroying the property both `_invariants` scope checks exist to defend.

WHAT IT STAGES: THE INDEX. Not the shard, not the journal, not the evidence, not
the task's files. The allow-list is one entry long and nothing downstream widens
it, and `_invariants`' `index-scope` re-derives the same rule from git after the
fact -- so the commits this makes are graded by something that did not make them.

HOW THE EXCLUSION IS ENFORCED RATHER THAN INTENDED. The path is staged EXPLICITLY
(by what git holds for it, never `git add -A`), the index is read back and
compared against the same allow-list BEFORE anything is committed, and the
commit carries the path as its pathspec; any refusal after staging puts the
index back as it was found. The git index is also read BEFORE staging: work
somebody else had already staged would otherwise ride along, and refusing before
touching anything leaves no half-made state to unpick. All of it is
`_scoped_commit`'s (`stage_and_commit`), shared with the other two scoped commits
rather than spelled three times, because two spellings of one refusal is how one
commit comes to carry what the other forbids.

UNDER THE INDEX LOCK, WHICH `commit-audit-state.py` DOES NOT TAKE -- and the
asymmetry is the point rather than an inconsistency. That command commits a
phase's OWN shard, which only that phase writes; this one commits the file every
structural command in the repository writes, so a concurrent `/audit:task add`
between the read and the commit would put half an edit into git. It is the same
lock `audit-task.py` and `set-priority.py` take, borrowed rather than retaken
when the caller already holds it.

IN THE SINGLE-FILE LAYOUT IT REFUSES, BY NAME. There the manifest IS the index --
`_invariants.manifest_files()` returns the identity pair -- so the ordinary task
and sign-off commits already carry it, and this route would commit the same bytes
a second time. The test is that pair and never a filename guess. It refuses by
declining to commit and saying which state it is in, and it still exits 0: a
single-file project has done nothing wrong by calling this, and a non-zero exit
would make every single-file sign-off read as failed and get the step deleted
within a day.

NEVER AN EMPTY COMMIT. Nothing staged means no commit and a line saying there was
nothing to commit, because a stream of empty commits is how a record stops being
read.

Usage:
  commit-manifest-index.py <manifest> <phaseId> [--project DIR] [--subject TEXT]
                           [--takeover] [--json]

`<phaseId>` is ATTRIBUTION, not scope: the index is shared, and the phase id says
which run made the structural change. It is what puts the commit in the subject
line and in the journal row, and it is how `index-scope` finds the commit to
grade at all -- nothing in the manifest points at one.

Exit codes:
  0  it ran - it committed, or there was nothing to commit and it said which
     (the single-file refusal is one of those, and is deliberately not a failure)
  1  it could not - git refused, the git index already held work this commit
     may not carry, or the index names a task or phase the shard committed at
     HEAD does not hold yet (commit that shard first; the refusal names it)
  2  usage error - the manifest will not load, or there is no such phase
  3  the index lock is held by a process that is alive - try again after it
  4  the lock is stale; a human confirms the holder is gone, then --takeover

Three and four are `_locks`' own codes, passed through rather than folded into
one, which is what `audit-task.py` and `set-priority.py` already do with the same
lock: "wait" and "somebody must look" are different instructions and a caller
that could not tell them apart would retry the one that never clears.
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

import _invariants  # noqa: E402  (the phase lookup, the git root, the layout test, the action name)
import _journal_io  # noqa: E402  (where the trail lives, and the append)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR shards)
import _panel_write  # noqa: E402  (the index lock, taken the way every structural write takes it)
import _scoped_commit  # noqa: E402  (the staging discipline and the answer shape, shared with the audit-state commit)

E_OK, E_FAIL, E_USAGE = 0, 1, 2

# A FIXED LITERAL SEPARATES THIS FROM A TASK COMMIT AND FROM AN AUDIT-STATE ONE,
# and it is not decoration. A task commit's type comes from `meta.commit.type`,
# which a manifest may set to anything, and its SCOPE is the phase id -- so a
# literal nothing in a manifest can reach has to go in the scope position, and
# `git log --grep audit-index` then tells the three classes apart for ever. A
# reader who meets one of these in a log has to be able to tell, without opening
# it, that it carries no implementation and no phase's own file.
#
# `chore` for `commit-audit-state.py`'s reason: the type has to be one
# commitlint's default enum accepts, or a repository with husky+commitlint
# refuses the commit AFTER this script has staged the file, leaving the caller to
# finish by hand. The phase id goes in the subject, where it is still greppable.
COMMIT_TYPE = "chore"
COMMIT_SCOPE = "audit-index"
DEFAULT_SUBJECT = "the shared index, carried alone so no phase's work rides with it"

# `SUBJECT_LEAD` for `commit-audit-state.py`'s reason, and this file carried
# the identical defect: with the phase id first, the subject after the colon IS
# sentence-case, which commitlint's default `subject-case` refuses along with
# start-case, pascal-case and upper-case. Every one of those is computed by a
# transform that capitalises the first character, so a fixed lowercase word this
# command owns -- ahead of `--subject`, where no caller can displace it -- is out
# of reach of all of them rather than of the one that bit. The phase id stays
# uppercase and stays in the subject, where `git log` still finds it, and the word
# is `phase` because the orchestrator's own sign-off subject already opens with it.
#
# IT NAMES THE PHASE WITHOUT CLAIMING TO BE SCOPED TO IT, which is the reading this
# file's `<phaseId>` needs: the conventional SCOPE says `audit-index` and that is
# what the commit is scoped to, while the subject's phase is attribution - which
# run made the structural change - exactly as the usage block above says.
SUBJECT_LEAD = "phase"

# What every line this command prints is stamped with. A constant because the
# renderer is `_scoped_commit`'s and takes it as an argument -- the lines are
# shared with the audit-state commit and the NAME is the only thing that differs.
PREFIX = "[commit-manifest-index]"

# The one thing this commit may carry, with the word its line is reported under.
INDEX_LABEL = "the manifest index"


# --- what this commit may carry -----------------------------------------------
def stage_targets(phase, manifest_path, git_root):
    """`{"paths", "skipped", "sameFile"}` - the allow-list, resolved. One entry.

    `paths` is git-root-relative and exists on disk; `skipped` carries one
    sentence per reason there is nothing to stage, and `sameFile` is True when
    `manifest_files` returned the identity pair, which is what the single-file
    layout looks like from here. A skip is REPORTED and never silent: "the index
    is outside the repository" and "there is no index because this is the
    single-file layout" leave the same empty list behind, and they are not the
    same finding.

    THE LIST IS THE SAFETY PROPERTY, exactly as it is in `commit-audit-state.py`.
    Nothing downstream widens it - the staging call takes this path and the index
    verification takes this same list - so a phase's shard has no route into the
    commit even while it sits modified in the working tree beside it.
    """
    index_abs, phase_file_abs = _invariants.manifest_files(manifest_path, phase)
    # `indexAbs` travels with the answer rather than being recomposed from `paths`:
    # the entry there is GIT-ROOT-relative and the journal's redaction is
    # PROJECT-relative, and a workspace whose repository is a subdirectory is
    # exactly the layout in which rebuilding one from the other writes the wrong
    # path into a file that goes to a client.
    out = {"paths": [], "skipped": [], "sameFile": False, "indexAbs": index_abs,
           "kinds": {}}
    if os.path.abspath(index_abs) == os.path.abspath(phase_file_abs):
        out["sameFile"] = True
        return out
    rel = _invariants._rel(index_abs, git_root)
    if rel is None:
        out["skipped"].append("%s lives outside the git root, so it cannot be "
                              "committed at all" % (INDEX_LABEL,))
        return out
    if not os.path.exists(index_abs):
        out["skipped"].append("%s does not exist, so there is nothing of it to "
                              "stage" % (INDEX_LABEL,))
        return out
    out["paths"].append(rel)
    # How the one path is staged, `_scoped_commit.classify`'s answer; it exists
    # on disk, which the check above required.
    out["kinds"] = _scoped_commit.classify(git_root, [(rel, True)])
    return out


def _foreign_after_staging(foreign):
    """The sentence for a path that arrived THROUGH the staging, naming it."""
    return ("staging produced paths outside the allow-list (%s), so nothing was "
            "committed" % (", ".join(foreign),))


# --- what the committed shards support ------------------------------------------
# `/audit:task add` writes a task into its phase's shard and its files into the
# index; `/audit:phase add` writes a stub into the index and a new shard beside it.
# Committing the index BEFORE the shard records a plan whose index names a task or
# a phase no committed shard holds - a commit that fails validation, which
# `verify-invariants`' `manifest-revalidated` then reports against every commit
# after it until the shard lands. The order is the shard first, and this is where it
# is enforced. Only a reference AHEAD of its shard is refused: one the committed
# shard holds (a widened scope, whose pairing sign-off settles) commits, and one no
# shard holds at all is the validator's to report, not this command's.
def _shard_at_head(git_root, rel):
    """The shard as HEAD holds it, parsed, or None when HEAD holds none."""
    code, out, _err = _scoped_commit.run_git(git_root, ["show", "HEAD:%s" % rel])
    if code != 0:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def _changed_shards(git_root, rels):
    """The shard paths git reports as differing from HEAD (modified, added or
    untracked), or None when git would not say - then every shard is read."""
    if not rels:
        return set()
    code, out, _err = _scoped_commit.run_git(
        git_root, ["status", "--porcelain", "--untracked-files=all", "--"] + rels)
    if code != 0:
        return None
    return set(line[3:].strip().strip('"') for line in out.splitlines()
               if len(line) > 3)


def _task_ids(doc):
    return set(t.get("id") for t in ((doc or {}).get("tasks") or [])
               if isinstance(t, dict) and t.get("id"))


def ahead_of_shards(git_root, manifest_path, index_doc):
    """[(reference, shardRel)] - what the index would record that only an
    UNCOMMITTED shard supports, each with the shard to commit first."""
    if not isinstance(index_doc, dict):
        return []
    base = os.path.dirname(os.path.abspath(manifest_path))
    ahead, now_ids, head_ids, stubs = [], {}, {}, []
    for stub in index_doc.get("phases") or []:
        if not isinstance(stub, dict) or not stub.get("shard"):
            continue
        path = os.path.join(base, stub["shard"])
        rel = os.path.relpath(path, git_root).replace(os.sep, "/")
        try:
            with open(path, encoding="utf-8") as fh:
                now = json.load(fh)
        except (OSError, ValueError):
            continue               # a shard that is not there is the validator's
        stubs.append((stub, rel, now))
    # ONE `git status` over every shard, and a `git show` only for the ones it
    # names. An unchanged shard IS its committed copy, so it needs no second read -
    # and this runs under the index lock, where a read per phase would make every
    # index commit wait on the size of the whole plan rather than on the change.
    changed = _changed_shards(git_root, [rel for _s, rel, _n in stubs])
    for stub, rel, now in stubs:
        for tid in _task_ids(now):
            now_ids[tid] = rel
        if changed is not None and rel not in changed:
            head_ids.update((tid, rel) for tid in _task_ids(now))
            continue
        head = _shard_at_head(git_root, rel)
        if head is None:
            ahead.append(("phase %s" % (stub.get("id"),), rel))
            continue
        head_ids.update((tid, rel) for tid in _task_ids(head))
    for path_key, ids in sorted((index_doc.get("fileIndex") or {}).items()):
        for tid in ids if isinstance(ids, list) else []:
            if tid in now_ids and tid not in head_ids:
                ahead.append(("task %s (fileIndex %r)" % (tid, path_key), now_ids[tid]))
    for bug in index_doc.get("bugs") or []:
        tid = bug.get("taskId") if isinstance(bug, dict) else None
        if tid in now_ids and tid not in head_ids:
            ahead.append(("task %s (%s's fix)" % (tid, bug.get("id")), now_ids[tid]))
    return ahead


# --- the commit ---------------------------------------------------------------
def commit_message(phase_id, subject, coauthor):
    """The message paragraphs: a conventional subject, and the co-author trailer.

    A LIST RATHER THAN ONE STRING, because that is how it reaches git: one `-m`
    per paragraph, so the trailer is a trailer and not a second sentence of the
    subject line.

    `SUBJECT_LEAD` COMES FIRST AND NOTHING MAY BE PUT AHEAD OF IT - that position
    is the whole of `commit-audit-state.py`'s fixed-lowercase-subject repair, and
    the constant says why. The shape is
    unconditional and is deliberately not read from `meta.commit`, for the reason
    `commit-audit-state.commit_message` states at length: that block holds a
    default type and a trailer and records nothing about which commitlint rules a
    repository configures.

    AND THE CALLER'S HALF IS BOUNDED, by the same rule set and for the same
    reason the type is: a header past `HEADER_MAX_CHARS` is refused by a
    commitlint repository AFTER this script has staged the file. Everything ahead
    of the caller's text is this command's and grew with each repair to it, so
    the bound is applied where the two meet rather than left as a hope about how
    long a `--subject` will be.
    """
    paragraphs = [_scoped_commit.fitted_header(
        "%s(%s): %s %s - " % (COMMIT_TYPE, COMMIT_SCOPE, SUBJECT_LEAD, phase_id),
        subject or DEFAULT_SUBJECT)]
    if coauthor:
        paragraphs.append(str(coauthor))
    return paragraphs


def _phase_id(phase):
    return str((phase or {}).get("id"))


def _coauthor(manifest):
    block = ((manifest or {}).get("meta") or {}).get("commit")
    value = block.get("coauthor") if isinstance(block, dict) else None
    return value if isinstance(value, str) and value.strip() else None


def record_row(project, phase_id, sha, index_abs, config=None):
    """Anchor the commit in the trail. Returns the file the row landed in, or False.

    THE TARGET IS THE INDEX, which is what this commit carried, and `commit` and
    `phaseId` are the only `details` keys - both checked to be on
    `_journal_io.DETAILS_KEYS` by this file's cases rather than assumed, because
    that allow-list DROPS an unknown key in silence and a row could otherwise
    carry neither while still reading as an action that happened.

    REDACTED THE WAY EVERY COMMITTED ROW IS, through `repo_relative_or_token`: a
    manifest configured outside the repository would otherwise write an absolute
    path -- somebody's home directory -- into a file that goes to a client.

    FAIL-SOFT, `_journal_io.append`'s own contract: a commit that HAPPENED must
    not be reported as not having happened because the trail could not be written.

    `append_from_cli`, NOT `append`: this command is run from Bash, and an
    append no writer claims is reported by `guard-bash-writes` as a shell write
    into the append-only trail on the next Bash command.

    AND THE ACTOR CARRIES THE SESSION, because the append names the FILE after
    it. A row written with no session lands in the file named for the checkout's
    writer token, while every other command-line verb in the same session -- the
    task verbs, the priority verb -- lands in the file named for the session. One
    session's trail then sits in a file named for it and a file named for the
    machine, and a reader following the run by hand has to know to open both.
    Nothing is lost either way (sign-off stages the whole directory), and the
    file name is the chain's genesis seed, so this is a thing to get right at the
    append and never afterwards.

    THROUGH `env_session_id`, which is this module's own reader of the variable:
    it sanitises and bounds the value before it becomes a path segment and a
    committed field, and it answers None -- not a substitute -- when the
    environment names no session, which is what leaves the writer-token fallback
    reachable for a verb run outside a session at all.
    """
    config = _journal_io.load_config(project) if config is None else config
    return _journal_io.append_from_cli(project, {
        "action": _invariants.ACTION_INDEX_COMMITTED,
        "actor": {"sessionId": _journal_io.env_session_id(),
                  "via": "commit-manifest-index"},
        "target": _journal_io.repo_relative_or_token(project, index_abs),
        "summary": "the manifest index was committed as %s for %s - the shared "
                   "file, with no phase's work beside it" % (sha[:12], phase_id),
        "details": {"commit": sha, "phaseId": str(phase_id)},
    }, config=config)


# The three ways this command does nothing, worded APART because they are
# different states of the world and a reader acts on them differently. Folded into
# one line they would all read as "all clear", and the last of them is the state a
# single-file project sits in permanently by design.
NOTHING_UNCOMMITTED = ("nothing uncommitted: the manifest index is already in "
                       "git. No commit was made, because an empty one records "
                       "nothing and buries the ones that do.")
NO_INDEX_TO_COMMIT = ("there is no index to commit here - the line above says "
                      "which way it went missing. Nothing was staged.")
SINGLE_FILE_LAYOUT = ("REFUSED, and this is the single-file layout: the manifest "
                      "IS the index there, so the task and sign-off commits "
                      "already carry it and this route would commit the same "
                      "bytes twice. `manifest_files` returning one path for both "
                      "is the test, not the filename. Run /audit:layout sharded "
                      "if you want the index committed apart from the phases.")


# --- cli ----------------------------------------------------------------------
def build_parser():
    """The argument parser, separated so a case can read the option table."""
    parser = argparse.ArgumentParser(
        prog="commit-manifest-index.py", add_help=True, allow_abbrev=False,
        description="Commit the manifest index on its own, or say there is "
                    "nothing to commit.")
    parser.add_argument("manifest")
    parser.add_argument("phase")
    parser.add_argument("--project", default=".",
                        help="the directory holding .claude/ and the records "
                             "(default: the current directory)")
    parser.add_argument("--subject", default=None,
                        help="the commit subject after the conventional prefix; "
                             "say what the structural change was")
    parser.add_argument("--takeover", action="store_true",
                        help="take the index lock from a holder a human has "
                             "confirmed is dead")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def commit_index(manifest, phase, manifest_path, project, git_root, subject=None,
                 config=None):
    """`(exitCode, answer)` - do the thing and say what happened. Prints nothing.

    A PAIR RATHER THAN AN EXIT CODE, for `run-test-gate.run_gate`'s reason: a
    function that returned only a verdict could not be exercised without a
    terminal around it, and every branch below is a branch a case has to reach.

    IT TAKES NO LOCK. The lock is `main`'s, wrapped around this whole call, so
    that the read, the decision, the staging and the commit are one critical
    section - and so that a case can drive every branch here without a lock
    directory being created beside a fixture.
    """
    config = _journal_io.load_config(project) if config is None else config
    targets = stage_targets(phase, manifest_path, git_root)
    allowed, skipped = targets["paths"], targets["skipped"]
    if targets["sameFile"]:
        return E_OK, _scoped_commit.answer(skipped, quiet=SINGLE_FILE_LAYOUT)

    # BEFORE STAGING, so a refusal leaves the git index exactly as it was found.
    # Work somebody else had already staged would otherwise be swept into a commit
    # whose entire promise is that it carries one file.
    foreign, why = _scoped_commit.foreign_staged(git_root, allowed)
    if why:
        return E_FAIL, _scoped_commit.answer(skipped, refused=why)
    if foreign:
        return E_FAIL, _scoped_commit.answer(
            skipped, foreign=foreign,
            refused="the git index already holds paths this commit may not "
                    "carry. A manifest-index commit carries the shared index and "
                    "nothing else, so it refuses rather than sweeping them in - "
                    "unstage them and re-run")
    # AHEAD OF THE DO-NOTHING ANSWERS: `git status` does not list an ignored
    # file, so an ignored index would otherwise read as "nothing uncommitted".
    ignored = _scoped_commit.ignored_records(targets["kinds"])
    if ignored:
        return E_FAIL, _scoped_commit.answer(skipped, refused=ignored)
    if not allowed:
        return E_OK, _scoped_commit.answer(skipped, quiet=NO_INDEX_TO_COMMIT)

    # DECIDED BEFORE ANYTHING IS STAGED. The do-nothing answer is reached from here
    # with the git index untouched, so declining costs nothing and undoes nothing.
    pending, why = _scoped_commit.uncommitted(git_root, allowed)
    if why:
        return E_FAIL, _scoped_commit.answer(skipped, refused=why)
    if not pending:
        return E_OK, _scoped_commit.answer(skipped, quiet=NOTHING_UNCOMMITTED)

    # THE SHARD FIRST. Refused before anything is staged, naming each reference
    # and the shard that holds it, so the remedy is one command away.
    ahead = ahead_of_shards(git_root, manifest_path, _mio.read_json(manifest_path))
    if ahead:
        shards = sorted(set(rel for _what, rel in ahead))
        return E_FAIL, _scoped_commit.answer(skipped, refused=(
            "the index names %s, which the shard committed at HEAD does not hold "
            "yet - committed now, it would record a plan that does not validate. "
            "Commit %s first (the task commit that carries it, or "
            "commit-audit-state.py <manifest> <phase>), then run this again"
            % ("; ".join(what for what, _rel in ahead), ", ".join(shards))))

    # STAGED, READ BACK AND COMMITTED BY `_scoped_commit.stage_and_commit`, the
    # sequence all three scoped commits share: the path staged by what git holds
    # for it, the index read back against this same list, a commit with the list
    # as its pathspec, and the index put back as it was found on any refusal
    # after staging.
    done = _scoped_commit.stage_and_commit(
        git_root, allowed, targets["kinds"],
        commit_message(_phase_id(phase), subject, _coauthor(manifest)),
        _foreign_after_staging)
    staged = done["staged"]
    if not done["committed"]:
        return E_FAIL, _scoped_commit.answer(skipped, staged=staged,
                                             foreign=done["foreign"],
                                             refused=done["refused"])
    sha = done["sha"]
    if not sha:
        # The commit exists and this process cannot name it. A failure rather than
        # a success with a blank field: the journal row is the only handle anything
        # has on such a commit, and a row naming nothing is worse than no row.
        return E_FAIL, _scoped_commit.answer(
            skipped, committed=True, staged=staged,
            refused="%s, so no journal row could name it" % (done["refused"],))

    journalled = bool(record_row(project, _phase_id(phase), sha,
                                 targets["indexAbs"], config=config))
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
        out("%s git is not on PATH, so the manifest index cannot be committed at "
            "all. Nothing was staged." % (PREFIX,))
        return E_FAIL

    # THE LOCK COMES BEFORE THE READ, `set-priority.py`'s sentence one file over:
    # the whole read-decide-stage-commit is serialized, so a `/audit:task add`
    # running beside this cannot land half an edit in the commit.
    lock = _panel_write.acquire_index_lock(project,
                                           _panel_write.read_config(project),
                                           os.path.abspath(args.manifest),
                                           args.takeover, out, PREFIX,
                                           "commit the manifest index")
    if isinstance(lock, int):
        # The lock module's own code, passed through: `_locks.E_LIVE` says wait
        # and `_locks.E_STALE` says a human has to look, and a caller handed one
        # code for both would retry the one that never clears. `acquire_index_lock`
        # has already printed the lock module's message.
        return lock
    try:
        code, answer = commit_index(manifest, phase, args.manifest, project,
                                    git_root, subject=args.subject)
    finally:
        # A RELEASE THE LOCK DECLINES SAYS ANOTHER RUN TOOK THIS OVER WHILE THE
        # COMMIT WAS BEING MADE, which a reader of this output needs more than
        # the commit line. Under `--json` it goes to stderr, where it cannot
        # break the one object stdout is carrying.
        _panel_write.release_index_lock(
            lock, out=(_panel_write.stderr_line if args.as_json else out))
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
        print("commit-manifest-index.py has no inline --selftest; its cases live "
              "in plugins/audit/tests/test_commit_manifest_index.py - run that "
              "file instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
