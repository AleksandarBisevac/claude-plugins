#!/usr/bin/env python3
"""
What a commit-a-narrow-allow-list command is made of, in one place.

WHY THIS IS A MODULE RATHER THAN A PARAGRAPH IN EACH COMMAND. Three entry points
stage a fixed set of paths and commit them -- `commit-audit-state.py` (the
phase's manifest file, the journal and the evidence), `commit-manifest-index.py`
(the manifest INDEX, and nothing at all beside it) and `commit-task-work.py` (a
task's declared files and the records beside them) -- and everything except the
list itself is the same in all three: stage EXPLICITLY, each path by what git
holds for it (`classify`, `stage`), never `git add -A`; read the index back;
refuse when anything outside the allow-list is in it; commit with the list as
the pathspec; put the index back as it was found on any refusal after staging
(`stage_and_commit`); and report the outcome in one shape whichever of the ways
it went. No command can import another, because nothing may import a hyphenated
entry point, so a copy in each was the only alternative -- and a second copy of
a refusal rule is how one commit comes to carry what the other forbids.

WHAT IS DELIBERATELY NOT HERE: THE ALLOW-LIST ITSELF. Each command derives its
own, and they differ in exactly the entries that matter -- one may stage the
phase's shard and the records beside it and never the shared index, another may
stage only the shared index and never a phase's file. A shared builder taking a
flag would be one function holding several safety properties, which is the
shape in which a widened list stops being noticed.

THE GIT RUNNER IS NOT `_commit_trail._git`, and the difference is a decision
rather than an oversight -- see `run_git` below. `under_any` is likewise built on
`_invariants._under` rather than on a second prefix test: the writer decides what
may be staged and the checker decides what was allowed, and two spellings of
"inside" is how a guard comes to permit a path its reader forbids.

Reads git, and through `stage_and_commit` stages and commits the paths a caller
hands it and nothing else; which paths those are is always the caller's answer.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__scoped_commit.py`.
"""
import os
import shutil
import subprocess
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

import _evidence_io  # noqa: E402  (the one reader of a porcelain line's path)
import _invariants  # noqa: E402  (`_under`: the one answer to "is this inside")


# --- asking git ---------------------------------------------------------------
def run_git(git_root, args, timeout=60, stdin=None, index_file=None):
    """(code, stdout, stderr), or (None, "", why) when git could not be asked.

    `stdin` is bytes fed to git, for `update-index --index-info`; `index_file`
    points git at a temporary index (`GIT_INDEX_FILE`) instead of the real one.

    NOT `_commit_trail._git`, which `_invariants` reuses one module over, and the
    difference is the reason rather than an oversight: that runner sends stderr to
    DEVNULL, which is right for a READ whose absence is itself an answer and wrong
    for a WRITE whose refusal is the only thing a human can act on. `git commit`
    and `git add` explain themselves on stderr and nowhere else, so discarding it
    here would turn every refusal into a bare exit code -- and it would do as much
    to the reads below, whose `why` sentence would then carry an empty bracket
    where the reason belongs.
    """
    env = None
    if index_file is not None:
        env = dict(os.environ)
        env["GIT_INDEX_FILE"] = index_file
    try:
        done = subprocess.run(["git", "-C", git_root] + list(args),
                              input=stdin, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=timeout, env=env)
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

    `--no-renames` because with rename detection on git lists a staged rename by
    its NEW name alone: a `git mv` from outside the allow-list into it would read
    as clean, and the deletion of the source would be neither refused nor
    committed.
    """
    code, out, err = run_git(git_root, ["diff", "--cached", "--name-only",
                                        "--no-renames"])
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


# --- how each allowed path is staged ------------------------------------------
# What git holds for one allowed path decides how it is staged. Measured on git
# 2.50.1, and each is a way a single `git add -- <path>...` over the whole list
# goes wrong:
#
#   * IN_INDEX - an index entry - takes `git add -u --`: plain `git add --`
#     naming a tracked file under a gitignored directory exits 1 AND stages it;
#   * ON_DISK - on disk, not in the index - takes `git add --`, and the ignore
#     rule is honoured for exactly these: one git ignores is IGNORED and refused
#     before anything is staged, because `-f` is the operator's decision;
#   * HEAD_ONLY - in HEAD alone, the source of a staged `git mv` or a staged
#     `git rm` - is in neither call (both fail 128 on it) and reaches the commit
#     through its pathspec, which records the rename (`R100`) or the deletion;
#   * DELETED_ON_DISK - in HEAD, out of the index, still on disk and ignored:
#     `git rm --cached` and a `.gitignore` line, which is how a project stops
#     tracking a file it keeps. A pathspec commit reads the working tree for its
#     paths and so records nothing for it (`git commit -- <path>` answers
#     "nothing added to commit"); only the INDEX holds that deletion, so a commit
#     carrying one is made from the index - see `commit_from_index`;
#   * TRACKED_DIR - a directory on disk holding index entries. Its tracked
#     members take `git add -u --` and its untracked ones that git does not
#     ignore take `git add --`, named one by one: a directory gitignored AS A
#     WHOLE is not reported by `check-ignore` (exit 1 for `gen`, `/gen`,
#     `gen/**`, `gen/*`), and `git add -- gen` refuses it asking for `-f`.
IN_INDEX = "index"
ON_DISK = "disk"
TRACKED_DIR = "tracked-dir"
HEAD_ONLY = "head"
DELETED_ON_DISK = "deleted-kept"
IGNORED = "ignored"


def named(git_root, args, paths, nul=True):
    """The paths git prints for `args -- paths`, or None when git will not say.

    NUL-separated (`-z`) where the command allows it, so a path git would
    otherwise quote comes back verbatim; `check-ignore` takes `-z` only with
    `--stdin`, so it is read by line, and a path it quotes then fails to match
    and is left to `git add`, which applies the ignore rule itself. None rather
    than an empty list for `foreign_staged`'s reason: "git named nothing" is an
    answer and "git could not be asked" is not.
    """
    code, out, _err = run_git(
        git_root, list(args) + (["-z"] if nul else []) + ["--"] + list(paths))
    if code is None or code != 0:
        return None
    if not nul:
        return lines(out)
    return [f.replace("\\", "/") for f in out.split("\0") if f]


def covering(listed, paths):
    """The subset of `paths` that is, or holds, an entry of `listed`.

    A declared entry may be a DIRECTORY, and git lists what is inside it rather
    than the directory itself, so equality alone would call a tracked directory
    untracked.
    """
    return set(p for p in paths
               if any(_invariants._under(entry, p) for entry in listed))


def in_head(git_root, paths):
    """The subset of `paths` HEAD holds, or None when that is not established.

    A repository with no commit yet has an unborn HEAD, and there `ls-tree`
    fails; that is an answer - nothing is in HEAD - rather than an unknown, so
    it is asked for separately instead of being folded into the failure arm.
    """
    listed = named(git_root, ["ls-tree", "-r", "--name-only", "HEAD"], paths)
    if listed is not None:
        return covering(listed, paths)
    code, _out, _err = run_git(git_root, ["rev-parse", "--verify", "-q", "HEAD"])
    return set() if code == 1 else None


def classify(git_root, entries):
    """`{rel: kind}` for `(rel, on_disk)` pairs; a path git holds nowhere is absent.

    An EXACT index entry is `IN_INDEX`; a directory on disk holding index
    entries is `TRACKED_DIR`; any other path on disk - an untracked file, or a
    directory with nothing tracked in it - is `ON_DISK` unless git ignores it,
    and an ignored one is `DELETED_ON_DISK` when HEAD still holds it and
    `IGNORED` otherwise. A path not on disk is `IN_INDEX` when the index still holds it (an
    unstaged deletion) and `HEAD_ONLY` when only HEAD does.

    EVERY UNCERTAIN ANSWER IS THE ONE THAT SKIPS NOTHING, which is the loud
    direction: an index git will not list reads as holding everything, so the
    staging call fails and says why; a HEAD it will not list keeps an absent path
    in the pathspec, where the commit refuses a path git does not know; an ignore
    check it will not answer leaves the path to `git add`, which applies the rule
    itself. The other direction drops a path and commits a subset of the work
    while reporting success.
    """
    rels = [rel for rel, _on_disk in entries]
    if not rels:
        return {}
    index = named(git_root, ["ls-files"], rels)
    exact = set(rels) if index is None else set(index)
    held = set(rels) if index is None else covering(index, rels)
    kinds, loose, absent = {}, [], []
    for rel, on_disk in entries:
        if on_disk:
            if rel in exact:
                kinds[rel] = IN_INDEX
            elif rel in held:
                kinds[rel] = TRACKED_DIR
            else:
                loose.append(rel)
        elif rel in held:
            kinds[rel] = IN_INDEX
        else:
            absent.append(rel)
    if loose:
        ignored = named(git_root, ["check-ignore"], loose, nul=False) or []
        hidden = [rel for rel in loose if rel in ignored]
        kept = (in_head(git_root, hidden) or set()) if hidden else set()
        # A DIRECTORY holding nothing tracked and nothing `git add` would take
        # - empty, or only ignored files - has nothing of it to commit, and as a
        # pathspec it fails the whole commit ("did not match any file(s)"). So
        # it is left unclassified, which its caller reports as a skip.
        dirs = [rel for rel in loose if rel not in ignored
                and os.path.isdir(os.path.join(git_root, rel))]
        fresh = (named(git_root, ["ls-files", "--others", "--exclude-standard"],
                       dirs) if dirs else [])
        empty = set() if fresh is None else set(
            d for d in dirs if not covering(fresh, [d]))
        for rel in loose:
            if rel in empty:
                continue
            if rel not in ignored:
                kinds[rel] = ON_DISK
            else:
                kinds[rel] = DELETED_ON_DISK if rel in kept else IGNORED
    if absent:
        head = in_head(git_root, absent)
        for rel in absent:
            if head is None or rel in head:
                kinds[rel] = HEAD_ONLY
    return kinds


def stage(git_root, paths, kinds):
    """`""` when every path was staged by the call its kind needs, else git's words.

    `git add -u` for index entries and for the tracked members of a
    `TRACKED_DIR`, and `git add` for paths only on disk and for the untracked
    members of a `TRACKED_DIR` that git does not ignore - listed by
    `ls-files --others --exclude-standard`, so the ignore rule is applied by git
    and never forced past. A `HEAD_ONLY` or `DELETED_ON_DISK` path is in none.
    """
    dirs = [rel for rel in paths if kinds.get(rel) == TRACKED_DIR]
    fresh = []
    if dirs:
        fresh = named(git_root, ["ls-files", "--others", "--exclude-standard"],
                      dirs)
        if fresh is None:
            return "git would not list the untracked files under %s" % (
                ", ".join(dirs),)
    calls = ((["add", "-u", "--"],
              [rel for rel in paths if kinds.get(rel) in (IN_INDEX,
                                                          TRACKED_DIR)]),
             (["add", "--"],
              [rel for rel in paths if kinds.get(rel) == ON_DISK] + fresh))
    for argv, group in calls:
        if not group:
            continue
        code, out, err = run_git(git_root, argv + group)
        if code is None or code != 0:
            return "`git %s` refused (%s)" % (" ".join(argv[:-1]),
                                              (err or out).strip()[:200])
    return ""


def ignored_records(kinds):
    """The refusal a RECORD path git ignores earns, naming each, or "".

    For the commands whose every path is a record the commit is required to
    carry: dropping one is not the repair, un-ignoring it is.
    """
    ignored = sorted(rel for rel, kind in (kinds or {}).items()
                     if kind == IGNORED)
    if not ignored:
        return ""
    return ("git ignores %s, a record this commit is required to carry - remove "
            "the `.gitignore` rule that matches it (`git check-ignore -v %s` "
            "names the rule). Nothing was staged" % (", ".join(ignored),
                                                     ignored[0]))


# --- putting the index back ---------------------------------------------------
# What a refusal after staging says when the index was put back, and the other
# sentence when it could not be. Different repairs: one leaves nothing to undo,
# the other names what is still staged.
# SAID AS NARROWLY AS IT IS TRUE: what comes back is each allowed path's
# entries, stages and intent-to-add flag. `--index-info` writes no stat data and
# no skip-worktree or assume-unchanged bit, so "exactly as it was found" would
# claim more than the restore does.
INDEX_RESTORED = ("the allowed paths' index entries - their stages and "
                  "intent-to-add flags - were put back as they were found")
INDEX_NOT_RESTORED = ("and the git index could NOT be put back (%s), so what "
                      "this command staged is still staged: %s")

# The length of an object id, by the repository's object format. A removal line
# for `--index-info` carries a zero id, and one of the wrong length is
# "malformed index info" - so a sha1-length id restores nothing in a SHA-256
# repository.
_OID_LENGTH = {"sha1": 40, "sha256": 64}


def _zero_oid(git_root):
    """The all-zero object id for this repository's object format.

    `rev-parse --show-object-format` names the format; a git too old to answer
    predates SHA-256 repositories, so sha1's length is the right one there.
    """
    code, out, _err = run_git(git_root, ["rev-parse", "--show-object-format"])
    fmt = out.strip() if code == 0 else "sha1"
    return "0" * _OID_LENGTH.get(fmt, 40)


def snapshot(git_root, paths):
    """`(snap, why)` - the index entries under `paths`, as `ls-files -s` prints them.

    ENTRY BY ENTRY AND NOT `git write-tree`: a tree cannot hold an unmerged
    entry, so write-tree refuses an index in the middle of a conflict, and it
    drops the intent-to-add flag. `ls-files -s` keeps every stage of an unmerged
    path, and the intent-to-add paths - which it prints as ordinary entries of
    the empty blob - are read from `status --porcelain=v2` (` .A`) and restored
    with `git add -N`. Only the allowed paths are read, so the restore cannot
    touch anything anybody else staged.
    """
    code, out, err = run_git(git_root, ["ls-files", "-s", "-z", "--"]
                             + list(paths))
    if code is None or code != 0:
        return None, ("git would not list the index entries this commit would "
                      "stage (%s), so a failed staging could not be undone - "
                      "nothing was staged" % ((err or out).strip()[:200],))
    code2, st, err2 = run_git(git_root, ["status", "--porcelain=v2", "-z",
                                         "--untracked-files=no", "--"]
                              + list(paths))
    if code2 is None or code2 != 0:
        return None, ("git would not describe the index this commit would "
                      "stage (%s), so a failed staging could not be undone - "
                      "nothing was staged" % ((err2 or st).strip()[:200],))
    ita = [rec.split(" ", 8)[8] for rec in st.split("\0")
           if rec.startswith("1 .A ") and len(rec.split(" ", 8)) == 9]
    return {"entries": [e for e in out.split("\0") if e], "ita": ita}, ""


def restore(git_root, snap, paths):
    """`""` when every entry under `paths` is back as `snap` holds it, else why not.

    Every current entry under `paths` is removed (a mode-0 line removes all of a
    path's stages) and the snapshot's entries are written back through
    `update-index --index-info`, so an entry the operator had staged at its own
    bytes, a conflict's three stages and an intent-to-add path come back as
    they were, and a path this command added is gone again. Stat data and the
    skip-worktree / assume-unchanged bits are not restored; `INDEX_RESTORED`
    says only what is.
    """
    current = named(git_root, ["ls-files"], paths)
    if current is None:
        return "git would not list the index to put it back"
    ita = set(snap["ita"])
    zero = _zero_oid(git_root)
    feed = "".join("0 %s\t%s\0" % (zero, p) for p in sorted(set(current)))
    feed += "".join("%s\0" % (e,) for e in snap["entries"]
                    if e.split("\t", 1)[-1] not in ita)
    code, out, err = run_git(git_root, ["update-index", "-z", "--index-info"],
                             stdin=feed.encode("utf-8"))
    if code is None or code != 0:
        return (err or out).strip()[:200] or "git update-index exited %r" % (code,)
    if ita:
        code, out, err = run_git(git_root, ["add", "-N", "--"] + sorted(ita))
        if code is None or code != 0:
            return ((err or out).strip()[:200]
                    or "git add -N exited %r" % (code,))
    return ""


def restored(git_root, snap, paths, refused):
    """`refused`, with what became of the index after putting it back."""
    why = restore(git_root, snap, paths)
    tail = INDEX_RESTORED if not why else INDEX_NOT_RESTORED % (
        why, ", ".join(paths))
    return "%s - %s" % (refused, tail)


def _read_back(git_root, snap, paths, refuse_foreign):
    """`(refused, foreign)` - the index read back against `paths`, restored and
    refused when it holds anything else.

    Not belt and braces: the first read judged an index nothing had touched,
    and this one judges the index about to be committed - the only check that
    can see a path that arrived through the staging, as a declared directory's
    contents do.
    """
    foreign, why = foreign_staged(git_root, paths)
    if why:
        return restored(git_root, snap, paths, why), []
    if foreign:
        return restored(git_root, snap, paths, refuse_foreign(foreign)), foreign
    return "", []


def commit_from_index(git_root, paths, paragraphs, head):
    """`(sha, why)` - a commit of `head` plus the index's entries under `paths`,
    and nothing else. `sha` is set when a commit was made, `why` when this
    refuses; BOTH are set when the commit was made and HEAD had moved under it.

    FOR THE ONE COMMIT A PATHSPEC CANNOT MAKE. A `DELETED_ON_DISK` deletion is
    held only by the index, and a bare `git commit` carries the whole index -
    anything a sibling session staged between the read-back and the commit
    included. So the tree is built in a TEMPORARY index (`GIT_INDEX_FILE`):
    `read-tree` HEAD, the real index's entries under `paths` written over it
    (a path the real index no longer holds is removed), and then a real
    `git commit` run against that index. It is a real commit on purpose: the
    project's `pre-commit` and `commit-msg` hooks run on it exactly as on every
    other path - a project whose hook is its quality gate keeps that gate - and
    a hook that refuses leaves the real index untouched, because git only ever
    wrote the temporary one. The real index already holds exactly these entries
    for `paths`, so it needs no update afterwards.

    BOUND TO THE HEAD READ BEFORE STAGING, twice. The temporary index is built
    from `head`; if HEAD is already elsewhere just before the commit, nothing
    is committed. After it, the new commit's first parent must be `head`; if a
    commit landed in between, this refuses and names both SHAs, and resets
    nothing - the commit is there, and undoing it is a decision for whoever
    reads the refusal, not for this function.
    """
    if not head:
        return "", ("HEAD could not be read before staging, so a commit built "
                    "against it cannot be checked for having moved")
    tmp = tempfile.mkdtemp(prefix="audit-index-")
    index_file = os.path.join(tmp, "index")
    try:
        code, out, err = run_git(git_root, ["read-tree", head],
                                 index_file=index_file)
        if code != 0:
            return "", "git would not read HEAD into a temporary index (%s)" % (
                (err or out).strip()[:200],)
        code, real, err = run_git(git_root, ["ls-files", "-s", "-z", "--"]
                                  + list(paths))
        code2, held, err2 = run_git(git_root, ["ls-files", "-z", "--"]
                                    + list(paths), index_file=index_file)
        if code != 0 or code2 != 0:
            return "", "git would not list the entries to commit (%s)" % (
                (err or err2).strip()[:200],)
        zero = _zero_oid(git_root)
        feed = "".join("0 %s\t%s\0" % (zero, p)
                       for p in sorted(set(f for f in held.split("\0") if f)))
        feed += "".join("%s\0" % (e,) for e in real.split("\0") if e)
        code, out, err = run_git(git_root, ["update-index", "-z",
                                            "--index-info"],
                                 stdin=feed.encode("utf-8"),
                                 index_file=index_file)
        if code != 0:
            return "", "git would not build the temporary index (%s)" % (
                (err or out).strip()[:200],)
        code, now, _err = run_git(git_root, ["rev-parse", "--verify", "-q",
                                             "HEAD"])
        if code != 0 or now.strip() != head:
            return "", ("HEAD moved from %s to %s before the commit, so nothing "
                        "was committed" % (head, now.strip() or "nothing"))
        argv = ["commit", "-q"]
        for paragraph in paragraphs:
            argv.extend(["-m", paragraph])
        code, out, err = run_git(git_root, argv, index_file=index_file)
        if code != 0:
            return "", "git refused the commit (%s)" % (
                (err or out).strip()[:200],)
        code, sha, err = run_git(git_root, ["rev-parse", "HEAD"])
        code2, parent, _err2 = run_git(git_root, ["rev-parse", "HEAD^"])
        sha, parent = sha.strip(), parent.strip()
        if code != 0 or not sha:
            return "", ("the commit was made and git would not print its SHA "
                        "(%s)" % ((err or "").strip()[:200],))
        if code2 != 0 or parent != head:
            return sha, ("the commit %s was made on %s and not on %s, the HEAD "
                         "read before staging - a commit landed in between, so "
                         "this one may undo it. Nothing was reset: inspect "
                         "both and decide" % (sha, parent or "nothing", head))
        return sha, ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def stage_and_commit(git_root, paths, kinds, paragraphs, refuse_foreign):
    """Stage `paths` by kind, read the index back, commit; undo on any failure.

    Returns `{"committed", "sha", "staged", "refused", "foreign"}`. `refused` is
    empty exactly when a commit was made and named, and set beside `committed`
    and `sha` in the one case a commit was made and then refused (its HEAD had
    moved, `commit_from_index`); every refusal reached before the commit has put
    the index back and says so. `refuse_foreign(foreign)` is
    the caller's sentence for a path that arrived through the staging, because
    each command words its own allow-list.

    AN EXPLICIT PATHSPEC, which is not redundant with the read-back: the index
    does not arrive empty, and a bare `git commit` carries whatever else is in it
    even after both reads passed. The one exception is a `DELETED_ON_DISK` path,
    whose deletion only the index holds, and that commit is built by
    `commit_from_index` against the HEAD read here, before anything was staged.
    """
    out = {"committed": False, "sha": "", "staged": [], "refused": "",
           "foreign": []}
    code, head_out, _err = run_git(git_root, ["rev-parse", "--verify", "-q",
                                              "HEAD"])
    head = head_out.strip() if code == 0 else ""
    snap, why = snapshot(git_root, paths)
    if why:
        out["refused"] = why
        return out
    why = stage(git_root, paths, kinds)
    if why:
        out["refused"] = restored(git_root, snap, paths,
                                  "git refused to stage: %s" % (why,))
        return out
    out["refused"], out["foreign"] = _read_back(git_root, snap, paths,
                                                refuse_foreign)
    if out["refused"]:
        return out
    # `--no-renames` so the report names BOTH halves of a staged rename.
    code, staged_out, staged_err = run_git(
        git_root, ["diff", "--cached", "--name-only", "--no-renames"])
    if code is None or code != 0:
        out["refused"] = restored(git_root, snap, paths,
                                  "git would not list the staged paths (%s)"
                                  % ((staged_err or staged_out).strip()[:200],))
        return out
    out["staged"] = [p for p in lines(staged_out) if under_any(p, paths)]
    if any(kinds.get(p) == DELETED_ON_DISK for p in paths):
        sha, why = commit_from_index(git_root, paths, paragraphs, head)
        if why and not sha:
            out["refused"] = restored(git_root, snap, paths, why)
            return out
        # A commit made on a HEAD that moved is committed AND refused: the
        # caller reports the SHA and exits non-zero, and nothing is undone.
        out["committed"], out["sha"], out["refused"] = True, sha, why
        return out
    argv = ["commit"]
    for paragraph in paragraphs:
        argv.extend(["-m", paragraph])
    argv.extend(["--"] + list(paths))
    code, c_out, c_err = run_git(git_root, argv)
    if code is None or code != 0:
        out["refused"] = restored(git_root, snap, paths,
                                  "git refused the commit (%s)"
                                  % ((c_err or c_out).strip()[:200],))
        return out
    out["committed"] = True
    code, head, head_err = run_git(git_root, ["rev-parse", "HEAD"])
    out["sha"] = head.strip() if code == 0 else ""
    if not out["sha"]:
        out["refused"] = ("the commit was made and git would not print its SHA "
                          "(%s)" % ((head_err or "").strip()[:200],))
    return out


# --- the header a commitlint repository will take -----------------------------
# The bound `@commitlint/config-conventional` puts on a header, transcribed where
# the header is BUILT rather than only where it is graded. Both commands here open
# their subject with a fixed word and a phase id, and each repair that lengthened
# that opening spent some of this without anything downstream noticing -- while the
# part a caller supplies had no bound at all, so `--subject` could carry the header
# past the limit and a repository with husky+commitlint would refuse the commit
# AFTER the script had staged the files, leaving the caller to finish by hand. That
# is the failure the fixed opening exists to avoid, reached from the other end.
HEADER_MAX_CHARS = 100
# A CUT SAYS SO, in the trail's own words: a short subject and a shortened one read
# identically otherwise, and a reader of `git log` has no second field to check.
# Spent OUT OF the bound, so the bound stays a fact about the header.
SUBJECT_TRUNCATED = " [truncated]"


def fitted_header(fixed, subject, limit=HEADER_MAX_CHARS):
    """`fixed` + `subject` as one header line, cut IN THE SUBJECT to fit `limit`.

    WHICH END IS CUT IS THE WHOLE OF IT. `fixed` is what the command owns and
    what makes the line acceptable to a commitlint repository at all -- the
    conventional type and scope, the lowercase word no caller may displace, and
    the phase id `git log` finds the commit by. Cutting there to make room for a
    caller's prose would trade a refused commit for an unattributable one, so the
    caller's half is the half that gives.

    Returns `fixed` alone when there is no room left in it for any of the
    subject: a command whose own opening has outgrown the bound has a defect this
    function cannot repair, and pretending otherwise would put the marker in a
    header that is still too long. Each caller's cases pin that its opening
    leaves a caller room, which is the half that has to be measured rather than
    arranged here.
    """
    header = "%s%s" % (fixed, subject)
    if len(header) <= limit:
        return header
    room = limit - len(fixed) - len(SUBJECT_TRUNCATED)
    if room <= 0:
        return fixed
    return "%s%s%s" % (fixed, subject[:room], SUBJECT_TRUNCATED)


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

# SAID ON THE RUN THAT CREATES THE CONDITION, not on the next one. The row
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
