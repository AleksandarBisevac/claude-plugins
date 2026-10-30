#!/usr/bin/env python3
"""
What a commit-a-narrow-allow-list command is made of, in one place.

WHY THIS IS A MODULE RATHER THAN A PARAGRAPH IN EACH COMMIT. `commit-task-work.py`
makes two scoped commits - a task commit (a task's declared files and the records
beside them) and a `--state` commit (the phase's manifest file, the journal, the
evidence and the index, never a task's files) - and everything except the list
itself is the same in both: stage EXPLICITLY, each path by what git holds for it
(`classify`, `stage`), never `git add -A`; read the index back; refuse when
anything outside the allow-list is in it; commit with the list as the pathspec;
put the index back as it was found on any refusal after staging
(`stage_and_commit`); and report the outcome in one shape whichever of the ways
it went. Other entry points read pieces of it (`classify`, the attempt record),
and nothing may import a hyphenated entry point, so this module is where they
find them - a second copy of a refusal rule is how one commit comes to carry
what the other forbids.

WHAT IS DELIBERATELY NOT HERE: THE ALLOW-LIST ITSELF. Each commit derives its
own, in a function of its own, and they differ in exactly the entries that
matter - a task commit may stage the task's files and a state commit may never.
A shared builder taking a flag would be one function holding several safety
properties, which is the shape in which a widened list stops being noticed.

THE GIT RUNNER IS NOT `_commit_trail._git`, and the difference is a decision
rather than an oversight -- see `run_git` below. `under_any` is likewise built on
`_invariants._under` rather than on a second prefix test: the writer decides what
may be staged and the checker decides what was allowed, and two spellings of
"inside" is how a guard comes to permit a path its reader forbids.

Reads git, and through `stage_and_commit` stages and commits the paths a caller
hands it and nothing else; which paths those are is always the caller's answer.

THE JOURNAL ROW NAMING A COMMIT IS INSIDE IT (`commit_with_rows`). A row
written after its commit is never in it, so every scoped commit used to leave
the trail dirty on the tree it had just reported as committed, and no phase
could end clean. The row is now written first, keyed by a nonce the commit
message carries as a trailer, and staged into the same commit; a reader
resolves the SHA from the trailer (`_invariants.commits_carrying`). A commit
refused after the row was written leaves a second row withdrawing the nonce,
because the first cannot be taken back and must not be read as a commit that
exists.

This module carries no `--selftest` of its own; its cases live in
`tests/test__scoped_commit.py`.
"""
import binascii
import calendar
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

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

import _excerpt  # noqa: E402  (the one way a tool's output is quoted in a refusal)
import _invariants  # noqa: E402  (`_under`: the one answer to "is this inside"; the trailer)
import _task_outputs  # noqa: E402  (`covers`: the one rule for whether a declared path holds a file)
import _loader  # noqa: E402  (load_hooks_config: `plan_to_git`, the one door from a plan entry to git's pathspec)
import _journal_io  # noqa: E402  (the withdrawing row's append)
import _manifest_io as _mio  # noqa: E402  (atomic_write_text: the start snapshot's one writer)
import _manifest_phases as _phases  # noqa: E402  (tests_add_path: the file a `tests.add` entry names)
import _manifest_vocab as _vocab  # noqa: E402  (one reading of a `files` entry's line suffix)


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


# --- the commit HEAD names, asked again only when a ref moved ------------------
# A drive or a start asks for HEAD many times in one process, and most answers
# are the one before: nothing between them moved a ref. So git's answer is kept
# beside the commit the ref FILES name, and reused while those files still name
# it - `_config.git_place`'s shape, a memo bound to the disk facts it rests on,
# re-read on every call, so a commit this process made itself is seen as surely
# as one another process made.
#
# WHAT THE FILES ARE. `HEAD` in the tree's own git dir names either a commit (a
# detached HEAD) or a branch under `refs/heads/`; that branch's loose file in
# the common dir outranks any line of `packed-refs`, which answers only when
# there is no loose file. They are read as BYTES, never stat'ed - git replaces
# each by renaming a new file in - and the reading is checked against git once
# before anything is kept: an answer is kept only when git named the very commit
# the files name, which is what shows git reads these files at all.
#
# NOTHING IS KEPT where the files are not the whole story: a `reftable/` store,
# a HEAD naming anything but a commit or a branch under `refs/heads/`, a loose
# ref that is itself symbolic, a file holding anything but one object name, or
# a tree whose `.git` entry does not lead back to the common dir git named
# (`_own_git_dir`). Those are asked every time, as they always were.
#
# MODULE STATE, deliberately, for `_config._STANDING`'s reason: the callers in
# one process share the answers. `forget_heads()` empties it for a case that
# compares the memo with git asked fresh.
_HEADS = {}
_OBJECT_NAME = re.compile(r"\A(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


def _ref_file(path):
    """The bytes of one ref file, b"" when there is none, None when it cannot be
    read for any other reason."""
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except (FileNotFoundError, NotADirectoryError):
        return b""
    except OSError:
        return None


def _packed_name(packed, ref):
    """The object name `packed-refs` bytes give `ref`, or None - a line it cannot
    read included, since a reading that skips a line is not the files' answer."""
    want = ref.encode("utf-8")
    for line in packed.splitlines():
        if not line or line.startswith(b"#") or line.startswith(b"^"):
            continue
        name, sep, named = line.partition(b" ")
        if not sep:
            return None
        if named == want:
            return name.decode("ascii", "replace")
    return None


def _own_git_dir(top, common):
    """The git dir holding `top`'s own HEAD, read off its `.git` entry and
    checked against the common dir git named: the common dir itself for a
    `.git` directory or a `gitdir:` file naming it (a submodule's), the
    directory a `gitdir:` file names when that directory's `commondir` leads
    back to it (a linked worktree's). None when the entry says anything else - a
    tree git places by configuration rather than by its `.git` entry included."""
    dot = os.path.join(top, ".git")
    if os.path.isdir(dot):
        return common if os.path.realpath(dot) == common else None
    text = (_ref_file(dot) or b"").decode("utf-8", "replace").strip()
    if not text.startswith("gitdir: "):
        return None
    own = os.path.realpath(os.path.join(top, text[len("gitdir: "):]))
    if own == common:
        return own
    back = (_ref_file(os.path.join(own, "commondir")) or b"").decode(
        "utf-8", "replace").strip()
    if not back or os.path.realpath(os.path.join(own, back)) != common:
        return None
    return own


def _files_head(git_root):
    """`(key, named)` - where HEAD's files for `git_root` live, and the commit
    they name; None when the files are not the whole answer (the block above)."""
    # Two place questions rather than one, each under the key the lock
    # directory (`_locks.lock_dir`) and a tree's top (`_worktrees`,
    # `checkout_top`) are already asked by: in a process that asked those for
    # the same directory, neither costs git a question.
    hc = _loader.load_hooks_config(modname="audit__config")
    top = (hc.git_place(git_root, ["--show-toplevel"])[0] or [""])[0]
    common = (hc.git_place(git_root, ["--git-common-dir"])[0] or [""])[0]
    if not top or not common:
        return None
    common = os.path.realpath(os.path.join(str(git_root), common))
    git_dir = _own_git_dir(top, common)
    if git_dir is None or os.path.lexists(os.path.join(common, "reftable")):
        return None
    head = _ref_file(os.path.join(git_dir, "HEAD"))
    if not head:
        return None
    text = head.decode("utf-8", "replace").strip()
    key = (os.path.realpath(str(git_root)), git_dir, common)
    if _OBJECT_NAME.match(text):
        return key, text
    ref = text[len("ref: "):] if text.startswith("ref: refs/heads/") else ""
    if not ref or ".." in ref.split("/") or ref.endswith("/"):
        return None
    loose = _ref_file(os.path.join(common, *ref.split("/")))
    if loose is None:
        return None
    if loose:
        named = loose.decode("utf-8", "replace").strip()
        return (key, named) if _OBJECT_NAME.match(named) else None
    packed = _ref_file(os.path.join(common, "packed-refs"))
    named = _packed_name(packed, ref) if packed else None
    return (key, named) if named and _OBJECT_NAME.match(named) else None


def _ask_head(git_root):
    """`git rev-parse --verify -q HEAD` in `git_root`: git's answer, or None.
    `--verify` because without it an unborn branch whose tree holds an entry
    named `HEAD` - or `head`, where the filesystem folds case - is read as that
    path: git exits 0 and prints the word."""
    try:
        done = subprocess.run(["git", "-C", str(git_root), "rev-parse",
                               "--verify", "-q", "HEAD"],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def head_sha(git_root):
    """The commit HEAD names in `git_root`, or None when git will not say or
    says anything that is not a full object name - git's own answer, reused
    while the ref files still name it (the block above)."""
    files = _files_head(git_root)
    if files is not None and _HEADS.get(files[0]) == files[1]:
        return files[1]
    sha = _ask_head(git_root)
    sha = sha if sha is not None and _OBJECT_NAME.match(sha) else None
    if files is not None:
        if sha is not None and sha == files[1]:
            _HEADS[files[0]] = sha
        else:
            _HEADS.pop(files[0], None)
    return sha


def forget_heads():
    """Drop every kept HEAD answer; nothing needs it for correctness."""
    _HEADS.clear()


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
                    % (_excerpt.reason_of(err, out),))
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
    # `status_paths`, NUL-separated: a line read by `lines()` loses the blank
    # that opens a worktree-only status, so its path came back with the status
    # letter glued on - harmless while only the list's truth was read, wrong the
    # moment a path in it is compared. A rename lists both of its names.
    paths, why = status_paths(git_root, allowed)
    if paths is None:
        return [], why
    return paths, ""


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
               if any(_task_outputs.covers(p, entry) for entry in listed))


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
                                              _excerpt.reason_of(err, out))
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
                      "nothing was staged" % (_excerpt.reason_of(err, out),))
    code2, st, err2 = run_git(git_root, ["status", "--porcelain=v2", "-z",
                                         "--untracked-files=no", "--"]
                              + list(paths))
    if code2 is None or code2 != 0:
        return None, ("git would not describe the index this commit would "
                      "stage (%s), so a failed staging could not be undone - "
                      "nothing was staged" % (_excerpt.reason_of(err2, st),))
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
        return _excerpt.reason_of(err, out) or "git update-index exited %r" % (code,)
    if ita:
        code, out, err = run_git(git_root, ["add", "-N", "--"] + sorted(ita))
        if code is None or code != 0:
            return (_excerpt.reason_of(err, out)
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


def unborn_head(git_root):
    """True when HEAD names a branch that has no commit yet - git answers
    "no such revision" for HEAD while HEAD itself is a symbolic ref. A HEAD git
    cannot read for any other reason is not this, and answers False."""
    code, _out, _err = run_git(git_root, ["rev-parse", "--verify", "-q", "HEAD"])
    if code != 1:
        return False
    code, out, _err = run_git(git_root, ["symbolic-ref", "-q", "HEAD"])
    return code == 0 and bool(out.strip())


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

    AN UNBORN BRANCH IS A HEAD TOO - the state of a repository right after
    `/audit:init`, before its first commit. `head` is empty there and HEAD
    names a branch with no commit yet (`unborn_head`): the temporary index
    starts empty, and both bindings hold in that shape - the branch must still
    be unborn just before the commit, and the commit made must be a root.
    An empty `head` anywhere else is a HEAD that could not be read, and that
    refuses.
    """
    if not head and not unborn_head(git_root):
        return "", ("HEAD could not be read before staging, so a commit built "
                    "against it cannot be checked for having moved")
    was = head or "no commit (an unborn branch)"
    tmp = tempfile.mkdtemp(prefix="audit-index-")
    index_file = os.path.join(tmp, "index")
    try:
        code, out, err = run_git(git_root, ["read-tree", head] if head
                                 else ["read-tree", "--empty"],
                                 index_file=index_file)
        if code != 0:
            return "", "git would not read HEAD into a temporary index (%s)" % (
                _excerpt.reason_of(err, out),)
        code, real, err = run_git(git_root, ["ls-files", "-s", "-z", "--"]
                                  + list(paths))
        code2, held, err2 = run_git(git_root, ["ls-files", "-z", "--"]
                                    + list(paths), index_file=index_file)
        if code != 0 or code2 != 0:
            return "", "git would not list the entries to commit (%s)" % (
                _excerpt.reason_of(err, err2),)
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
                _excerpt.reason_of(err, out),)
        code, now, _err = run_git(git_root, ["rev-parse", "--verify", "-q",
                                             "HEAD"])
        now = now.strip() if code == 0 else ""
        if now != head:
            return "", ("HEAD moved from %s to %s before the commit, so nothing "
                        "was committed" % (was, now or "nothing"))
        argv = ["commit", "-q"]
        for paragraph in paragraphs:
            argv.extend(["-m", paragraph])
        code, out, err = run_git(git_root, argv, index_file=index_file)
        if code != 0:
            return "", "git refused the commit (%s)" % (
                _excerpt.reason_of(err, out),)
        code, sha, err = run_git(git_root, ["rev-parse", "HEAD"])
        code2, parent, _err2 = run_git(git_root, ["rev-parse", "--verify", "-q",
                                                  "HEAD^"])
        sha, parent = sha.strip(), (parent.strip() if code2 == 0 else "")
        if code != 0 or not sha:
            return "", ("the commit was made and git would not print its SHA "
                        "(%s)" % (_excerpt.reason_of(err),))
        if parent != head:
            return sha, ("the commit %s was made on %s and not on %s, the HEAD "
                         "read before staging - a commit landed in between, so "
                         "this one may undo it. Nothing was reset: inspect "
                         "both and decide" % (sha, parent or "nothing", was))
        return sha, ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def write_blob(git_root, rel, data):
    """`(oid, why)` - `data` (bytes) written into git's object store as the
    blob `rel` would hold, through the filters git applies to `rel` on `git
    add` (`hash-object --path`), so a line-ending rule is honoured as it is for
    a staged file."""
    code, out, err = run_git(git_root, ["hash-object", "-w", "--stdin",
                                        "--path", rel], stdin=data)
    if code is None or code != 0 or not out.strip():
        return "", "git would not store the blob for %s (%s)" % (
            rel, _excerpt.reason_of(err, out))
    return out.strip(), ""


def stage_blobs(git_root, blobs, head):
    """`""` when each `{rel: build}` entry was written into the git index at the
    blob `build(head)` answers - `(bytes, why)` - else the reason. The mode is
    the one the index already holds for the path, or a plain file's.

    THE BLOB IS BUILT HERE, FROM `head`, and not by the caller earlier: `head`
    is the commit `commit_from_index` builds onto and refuses to move past, so
    what the blob was derived from is exactly the parent the commit gets. A
    blob built from an earlier read would lay that read's index over whatever
    another session committed in between, and undo it in silence."""
    for rel in sorted(blobs or {}):
        data, why = blobs[rel](head)
        if why:
            return why
        oid, why = write_blob(git_root, rel, data)
        if why:
            return why
        code, out, _err = run_git(git_root, ["ls-files", "-s", "--", rel])
        mode = out.split()[0] if code == 0 and out.split() else "100644"
        code, out, err = run_git(git_root, [
            "update-index", "--add", "--cacheinfo",
            "%s,%s,%s" % (mode, oid, rel)])
        if code is None or code != 0:
            return "`git update-index --cacheinfo` refused %s (%s)" % (
                rel, _excerpt.reason_of(err, out))
    return ""


def stage_and_commit(git_root, paths, kinds, paragraphs, refuse_foreign,
                     blobs=None):
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
    even after both reads passed. The exceptions are a `DELETED_ON_DISK` path,
    whose deletion only the index holds, and a path in `blobs` (`{rel:
    build}`, each one of `paths`), committed at the blob `build(head)` answers
    for the HEAD read here (`stage_blobs`) rather than at the bytes the working
    tree holds - a pathspec'd commit would take the working file instead. Those
    commits are built by `commit_from_index` against that same HEAD.
    """
    out = {"committed": False, "sha": "", "staged": [], "refused": "",
           "foreign": []}
    blobs = dict(blobs or {})
    code, head_out, _err = run_git(git_root, ["rev-parse", "--verify", "-q",
                                              "HEAD"])
    head = head_out.strip() if code == 0 else ""
    snap, why = snapshot(git_root, paths)
    if why:
        out["refused"] = why
        return out
    why = (stage(git_root, [p for p in paths if p not in blobs], kinds)
           or stage_blobs(git_root, blobs, head))
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
                                  % (_excerpt.reason_of(staged_err, staged_out),))
        return out
    out["staged"] = [p for p in lines(staged_out) if under_any(p, paths)]
    if blobs or any(kinds.get(p) == DELETED_ON_DISK for p in paths):
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
                                  % (_excerpt.reason_of(c_err, c_out),))
        return out
    out["committed"] = True
    code, head, head_err = run_git(git_root, ["rev-parse", "HEAD"])
    out["sha"] = head.strip() if code == 0 else ""
    if not out["sha"]:
        out["refused"] = ("the commit was made and git would not print its SHA "
                          "(%s)" % (_excerpt.reason_of(head_err),))
    return out


# --- the row inside the commit -----------------------------------------------
def new_nonce():
    """A fresh nonce joining a row to the commit that will carry it.

    Random rather than derived from anything the commit holds: the commit does
    not exist yet, and a value computed from the paths or the time could repeat
    across two commits and join a row to the wrong one.
    """
    return binascii.hexlify(os.urandom(8)).decode("ascii")


def row_trailer(nonce):
    """The message line that says which rows this commit carries."""
    return "%s: %s" % (_invariants.ROW_TRAILER, nonce)


# A line git reads as a trailer: a token, a colon, a space and a value.
_TRAILER_LINE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*: \S")


def is_trailer_paragraph(paragraph):
    """True when every line of `paragraph` reads as a trailer - the only kind of
    final paragraph the row trailer may join."""
    lines = [ln for ln in (paragraph or "").splitlines() if ln.strip()]
    return bool(lines) and all(_TRAILER_LINE.match(ln) for ln in lines)


def with_row_trailer(paragraphs, nonce):
    """`paragraphs` with the row trailer kept in a paragraph of TRAILERS.

    Git reads trailers from the final paragraph only. So when that paragraph is
    already trailers - a co-author line - the row trailer joins it, because a
    paragraph of its own after the co-author would stop that one being a
    trailer. When it is anything else - the subject alone, or prose such as a
    task's filed `claims` block - the row trailer becomes a paragraph of its own:
    joined onto prose it would be a line no trailer reader finds, and the prose
    is carried byte-identical either way.
    """
    paragraphs = list(paragraphs)
    if len(paragraphs) > 1 and is_trailer_paragraph(paragraphs[-1]):
        return paragraphs[:-1] + ["%s\n%s" % (paragraphs[-1],
                                              row_trailer(nonce))]
    return paragraphs + [row_trailer(nonce)]


def carry(git_root, paths, kinds, files):
    """`(paths, kinds, outside)` - the allow-list widened by each row file.

    A row file already under an allowed entry changes nothing; the journal
    directory is on the state and task lists and holds it. One that is not - a
    journal directory that did not exist until this row created it is on no
    list - is added by name and
    classified the way every allowed path is. `outside` names the row files that
    cannot be carried at all (outside the git root, or ignored), which the caller
    reports rather than letting a row read as inside a commit it is not in.
    """
    paths, kinds, outside, fresh = list(paths), dict(kinds), [], []
    for path in files:
        rel = _invariants._rel(path, git_root)
        if rel is None:
            outside.append(path)
        elif not under_any(rel, paths) and rel not in fresh:
            fresh.append(rel)
    more = classify(git_root, [(rel, True) for rel in fresh]) if fresh else {}
    for rel in fresh:
        kind = more.get(rel)
        if kind in (None, IGNORED):
            outside.append(rel)
            continue
        paths.append(rel)
        kinds[rel] = kind
    return paths, kinds, outside


def withdraw(project, config, nonce, via, ids, reason):
    """Append the row withdrawing `nonce`. Returns the file, or False.

    `ids` are the `taskId`/`phaseId` the withdrawn rows carried, so a reader
    following one task finds the withdrawal beside the claim it cancels.
    Fail-soft like every append: a refusal already happened and is reported
    whether or not this row lands, and a row that could not be withdrawn is
    still resolved to nothing by a reader, which reports it as a gap.
    """
    details = dict(ids or {})
    details[_invariants.NONCE_KEY] = nonce
    details["reason"] = reason
    return _journal_io.append_from_cli(project, {
        "action": _invariants.ACTION_COMMIT_WITHDRAWN,
        "actor": {"sessionId": _journal_io.env_session_id(), "via": via},
        "target": str(details.get("taskId") or details.get("phaseId") or ""),
        "summary": "the commit announced by the rows keyed %s was not made, so "
                   "those rows name no commit: %s" % (nonce, reason),
        "details": details,
    }, config=config)


def commit_with_rows(git_root, paths, kinds, paragraphs, refuse_foreign,
                     write_rows, withdraw_rows, blobs=None):
    """`stage_and_commit`, carrying the journal rows that name the commit.
    `blobs` is passed through to it.

    `write_rows(nonce)` appends the rows keyed by `nonce` and returns
    `(files, refusal)`: the files they landed in, the anchoring row's first (an
    empty list is a journal that took no row, and the commit goes ahead without
    a trailer, as every append is fail-soft), and a sentence when a row the
    commit REQUIRES could not be written, which refuses before anything is
    staged. `withdraw_rows(nonce, reason)` appends the withdrawal.

    Returns `stage_and_commit`'s dict plus `nonce`, `journalled` (the anchoring
    row was written), `carried` (every row file is among the paths the commit
    staged, read back from git rather than intended) and `withdrawn` (None when
    nothing needed withdrawing, else whether the withdrawal landed).

    THE ORDER IS THE DESIGN. Every do-nothing answer is the caller's and is
    reached before this is called, so a row is written only for a commit that is
    about to be attempted. The row lands before `stage_and_commit` snapshots the
    index, so a refusal after staging puts the index back as it was found and
    leaves the row where it was written: in the working tree, claiming a nonce no
    commit carries, and followed by the row withdrawing it. A commit made on a
    HEAD that moved underneath is still a commit carrying the row, so nothing is
    withdrawn there.
    """
    nonce = new_nonce()
    files, refusal = write_rows(nonce)
    files = [f for f in (files or []) if f]
    if refusal:
        out = {"committed": False, "sha": "", "staged": [], "foreign": [],
               "refused": "%s. Nothing was staged" % (refusal,)}
        out.update({"nonce": nonce if files else "", "journalled": bool(files),
                    "carried": False,
                    "withdrawn": (bool(withdraw_rows(nonce, refusal))
                                  if files else None)})
        return out
    paths, kinds, outside = carry(git_root, paths, kinds, files)
    message = with_row_trailer(paragraphs, nonce) if files else list(paragraphs)
    done = stage_and_commit(git_root, paths, kinds, message, refuse_foreign,
                            blobs=blobs)
    rels = [_invariants._rel(f, git_root) for f in files]
    done["nonce"] = nonce if files else ""
    done["journalled"] = bool(files)
    done["carried"] = bool(files and done["committed"] and not outside
                           and all(rel in done["staged"] for rel in rels))
    done["withdrawn"] = None
    if files and not done["committed"]:
        done["withdrawn"] = bool(withdraw_rows(nonce, done["refused"]))
    return done


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


def coauthor_of(manifest):
    """`meta.commit.coauthor` when it is a string with something in it, else None.

    THE ONE DERIVATION of that key for the three commands, so a trailer one of
    them writes is a trailer the others write too: a value that is blank, or not
    a string, is the same "none" to all of them.
    """
    block = ((manifest or {}).get("meta") or {}).get("commit")
    value = block.get("coauthor") if isinstance(block, dict) else None
    return value if isinstance(value, str) and value.strip() else None


def commit_message(header, coauthor, claims=None):
    """The message paragraphs of a scoped commit: `header`, then the executor's
    `claims` when there are any, then the co-author trailer when there is one.

    A LIST RATHER THAN ONE STRING, because that is how it reaches git: one `-m`
    per paragraph, so the trailer is a trailer and not a second sentence of the
    subject line. The claims are a paragraph of their own, byte-identical, between
    the header and the trailers; `with_row_trailer` keeps the row trailer in a
    paragraph of trailers, so the claims paragraph never becomes the one git
    reads trailers from.

    THE HEADER IS THE CALLER'S, whole. What goes into it - the type, the scope,
    the lowercase lead, the id, and whether the subject is bounded by
    `fitted_header` - differs between the three commands on purpose, because each
    one's header is how a log tells its commit from the others; the order of the
    paragraphs after it is the one fact they share, and it lives here once.

    A claims or co-author value that is not a string with something in it adds no
    paragraph: an absent value and a blank one both read as "none filed".
    """
    paragraphs = [header]
    if isinstance(claims, str) and claims.strip():
        paragraphs.append(claims)
    if isinstance(coauthor, str) and coauthor.strip():
        paragraphs.append(coauthor)
    return paragraphs


# --- what this attempt changed ------------------------------------------------
# A task commit carries exactly its attempt: nothing that was in the tree before
# the attempt began, and nothing made during it left out in silence. The only
# way to tell the two apart afterwards is a record taken AT THE START, so `start`
# writes one - every dirty path with a digest of its bytes - and the committer and
# `done` compare the tree against it. A path dirty then at the same bytes now
# PREDATES the attempt; a path absent from it, or at other bytes, changed DURING
# it.
#
# THE DIGEST IS THE STAMP'S SPELLING (`_tree_stamp._dirty_paths`): the first
# characters of `_journal_io.file_hash`, null for a path whose bytes are not
# there to read. The record is a file rather than a stamp line, so it carries no
# path bound.
#
# KEPT ACROSS A RE-START, REMOVED BY THE CLOSE. A retry - and an unblock followed
# by a start - continues the same unfinished work, and an earlier attempt's own
# edits are this task's; a fresh record there would call them older dirt. A
# reopened task starts over, which is why `done` removes the record.
#
# WITH NO RECORD, a file's mtime against `startedAt` is the fallback, said as
# such wherever it decides anything. A re-start re-stamps `startedAt`, so a
# caller does not let the fallback call a declared file's change older dirt on
# a task recording more than one attempt: an earlier attempt's own edit would
# read as exactly that. An unblock resets the count, and there the fallback can
# still be wrong in that direction - the record is what does not.
ATTEMPT_DIR = "attempts"
ATTEMPT_RECORD_VERSION = 1
ATTEMPT_DIGEST_CHARS = 16

BASIS_SNAPSHOT = "the snapshot `start` recorded of every dirty path's bytes"
BASIS_MTIME = ("no start snapshot, so each file's mtime against the task's "
               "`startedAt` %s")
BASIS_NONE = ("no start snapshot and no `startedAt`, so which changes this "
              "attempt made is not asked")


def status_paths(git_root, pathspec=()):
    """`(paths, why)` - every path `git status` lists, untracked files one by
    one, read NUL-separated; `why` set, and `paths` None, when git would not say.

    `-z` BECAUSE A PATH GIT WOULD QUOTE IS NOT A DECLARED PATH. Without it a
    name with a space or a non-ASCII byte comes back in quotes, octal-escaped,
    and matches no `files` entry - so a leftover under that name was never
    found. A rename or copy carries two names, the new one first and its
    source after it, and both are listed: the source's removal is a change too.
    """
    code, out, err = run_git(git_root, ["status", "--porcelain", "-z",
                                        "--untracked-files=all", "--"]
                             + list(pathspec))
    if code is None:
        return None, err
    if code != 0:
        return None, ("git would not describe the working tree (%s)"
                      % (_excerpt.reason_of(err, out),))
    fields = out.split("\0")
    paths, i = [], 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 4:
            continue
        paths.append(entry[3:].replace("\\", "/"))
        if entry[0] in "RC" or entry[1] in "RC":
            if i < len(fields) and fields[i]:
                paths.append(fields[i].replace("\\", "/"))
            i += 1
    return sorted(set(paths)), ""


def path_marks(git_root, paths):
    """`{path: digest prefix or None}` for each of `paths`, read now."""
    marks = {}
    for path in paths:
        digest = _journal_io.file_hash(os.path.join(git_root, path))
        marks[path] = (None if digest is None
                       else digest.split(":", 1)[-1][:ATTEMPT_DIGEST_CHARS])
    return marks


def attempt_record_path(state_dir, task_id):
    """Where the start record of `task_id` lives under the state directory."""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(task_id))
    return os.path.join(str(state_dir), ATTEMPT_DIR, "%s.json" % (safe,))


def read_attempt(state_dir, task_id):
    """`(record, why)` - the start record of `task_id`, or None and why not."""
    path = attempt_record_path(state_dir, task_id)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            record = json.load(fh)
    except (OSError, IOError):
        return None, "no start snapshot was recorded for %s" % (task_id,)
    except ValueError as exc:
        return None, "the start snapshot %s does not parse (%s)" % (path, exc)
    if not isinstance(record, dict) or record.get("taskId") != str(task_id) \
            or not isinstance(record.get("paths"), dict):
        return None, ("the start snapshot %s is not one of %s's"
                      % (path, task_id))
    return record, ""


def record_attempt(state_dir, git_root, task_id, attempt, started_at):
    """`(said, why)` - write the start record of `task_id`, or keep the one a
    re-start of the same unfinished work already has. `said` is the sentence
    for the start's output; `why` is set when nothing could be recorded."""
    held, _problem = read_attempt(state_dir, task_id)
    if held is not None:
        return ("start snapshot kept from attempt %s (%d dirty path(s) then): a "
                "re-start continues the same work"
                % (held.get("attempt"), len(held["paths"])), "")
    paths, why = status_paths(git_root)
    if paths is None:
        return "", why
    record = {"v": ATTEMPT_RECORD_VERSION, "taskId": str(task_id),
              "attempt": attempt, "startedAt": started_at,
              "paths": path_marks(git_root, paths)}
    path = attempt_record_path(state_dir, task_id)
    try:
        _mio.atomic_write_text(path, json.dumps(record, indent=1,
                                                sort_keys=True) + "\n")
    except OSError as exc:
        return "", "the start snapshot could not be written to %s (%s)" % (
            path, exc)
    return ("start snapshot recorded: %d dirty path(s) predate this attempt"
            % (len(paths),), "")


def drop_attempt(state_dir, task_id):
    """Remove the start record of `task_id`; True when one was removed."""
    try:
        os.remove(attempt_record_path(state_dir, task_id))
        return True
    except OSError:
        return False


def _iso_seconds(text):
    """Seconds since the epoch for an ISO `...Z` moment, or None."""
    try:
        return calendar.timegm(time.strptime(str(text)[:19], "%Y-%m-%dT%H:%M:%S"))
    except (TypeError, ValueError):
        return None


def attribute(git_root, paths, record, started_at):
    """`{"during", "predates", "undated", "basis"}` over `paths` - which changes
    this attempt made, by `record` when there is one, else by mtime.

    `predates` with a record holds only paths at the SAME bytes as at the
    start; a path dirty then and changed since is `during` AND listed in
    `mixed`, because its diff holds both and no commit can carry one half."""
    out = {"during": [], "predates": [], "undated": [], "mixed": []}
    if record is not None:
        out["basis"] = BASIS_SNAPSHOT
        then = record["paths"]
        now = path_marks(git_root, paths)
        for path in paths:
            if path in then and then[path] == now[path]:
                out["predates"].append(path)
            else:
                out["during"].append(path)
                if path in then:
                    out["mixed"].append(path)
        return out
    start = _iso_seconds(started_at)
    if start is None:
        out["basis"] = BASIS_NONE
        out["undated"] = list(paths)
        return out
    out["basis"] = BASIS_MTIME % (started_at,)
    for path in paths:
        try:
            mtime = os.lstat(os.path.join(git_root, path)).st_mtime
        except OSError:
            out["undated"].append(path)
            continue
        (out["during"] if mtime >= start else out["predates"]).append(path)
    return out


def run_state_rels(project, config, git_root):
    """The plugin's own runtime directories, git-root relative: the state
    directory a start record lives in, and the logs beside it."""
    hc = _loader.load_hooks_config(modname="audit__config")
    root = pathlib.Path(project)
    rels = [_invariants._rel(str(hc.state_dir(root, config or {})), git_root),
            _invariants._rel(str(hc.logs_dir(root, config or {})), git_root)]
    return [rel for rel in rels if rel is not None]


# Whether git's index holds a path has three answers. The two readers of the
# plugin-owned rows want opposite things from the third: the commit and the
# close REFUSE what is not placed as the plugin's own, so for them an unknown
# leaves the path unplaced; the set-aside REVERTS or deletes what is not
# placed, so for it an unknown places the path. `plugin_owned_rels` takes the
# reader's side as a required argument.
TRACKED, UNTRACKED, UNKNOWN = "tracked", "untracked", "unknown"
# What a tracked ignore file's change holds, against HEAD's copy: only lines
# the plugin writes, or a line somebody else's.
PLUGIN_LINES_ONLY, FOREIGN_LINES = "plugin-lines-only", "foreign-lines"
UNKNOWN_REFUSES = "unknown-refuses"
UNKNOWN_PROTECTS = "unknown-protects"


def plugin_owned_rels(project, git_root, when_unknown):
    """`[(git-root-relative path, why), ...]` - `_manifest_io.PLUGIN_OWNED_IN_CLAUDE`
    placed under the project's `.claude/` and under the checkout's, which are
    two directories when the project sits below the git root and the one
    restore-point writer parks its copy in the checkout's.

    A row of `_manifest_io.PLUGIN_OWNED_WHILE_UNTRACKED` is placed only while
    git does not track it: the committed configuration file is a project file a
    task can edit, so its change is an undeclared one like any other. A row
    of `_manifest_io.PLUGIN_OWNED_WHILE_ONLY_ITS_LINES` that git tracks is
    placed only while its change adds nothing but lines the plugin writes
    (`_ignore_edit`): a task's own line in a committed ignore file is that
    task's edit. The commit, the close and the set-aside all place the rows
    here, so they agree on it wherever git can say.

    `when_unknown` is where they differ, and it has no default so that no
    reader takes a side by omission: `UNKNOWN_REFUSES` for a reader that
    refuses what is not placed (the commit and the close, through
    `undeclared_changes`) leaves such a row out; `UNKNOWN_PROTECTS` for a
    reader that reverts or deletes what is not placed (the set-aside) puts it
    in. Any other value raises `ValueError`."""
    if when_unknown not in (UNKNOWN_REFUSES, UNKNOWN_PROTECTS):
        raise ValueError("when_unknown must be %r or %r, not %r"
                         % (UNKNOWN_REFUSES, UNKNOWN_PROTECTS, when_unknown))
    placed, seen = [], set()
    for base in (project, git_root):
        claude = os.path.join(base, ".claude")
        for path, why in _mio.plugin_owned_under(claude):
            rel = _invariants._rel(path, git_root)
            if rel is None or rel in seen:
                continue
            seen.add(rel)
            name = os.path.relpath(path, claude).replace("\\", "/")
            by_lines = name in _mio.PLUGIN_OWNED_WHILE_ONLY_ITS_LINES
            asks = by_lines or name in _mio.PLUGIN_OWNED_WHILE_UNTRACKED
            placed.append((rel, why, by_lines, asks))
    states = _tracking(git_root, [rel for rel, _w, _b, asks in placed if asks])
    rows = []
    for rel, why, by_lines, asks in placed:
        if asks:
            state = states[rel]
            if state == TRACKED and by_lines:
                state = _ignore_edit(git_root, rel)
            if state in (TRACKED, FOREIGN_LINES) or (
                    state == UNKNOWN and when_unknown == UNKNOWN_REFUSES):
                continue
        rows.append((rel, why))
    return rows


def _ignore_edit(git_root, rel):
    """`PLUGIN_LINES_ONLY` when the tracked ignore file `rel` differs from
    HEAD's copy only by lines the plugin writes
    (`_manifest_io.adds_only_plugin_ignore_lines`), `FOREIGN_LINES` when the
    change holds anything else, and `UNKNOWN` when HEAD's copy or the one on
    disk could not be read - a path the index holds and HEAD does not included.

    A file deleted from disk is `FOREIGN_LINES`: no writer of the plugin
    deletes it. The reader's side of an unknown is `plugin_owned_rels`'s, as
    it is for `_tracking`."""
    code, before, _err = run_git(git_root, ["cat-file", "blob", "HEAD:" + rel])
    if code != 0:
        return UNKNOWN
    path = os.path.join(git_root, *rel.split("/"))
    if not os.path.lexists(path):
        return FOREIGN_LINES
    try:
        with open(path, "rb") as fh:
            after = fh.read().decode("utf-8", "replace")
    except OSError:
        return UNKNOWN
    return (PLUGIN_LINES_ONLY if _mio.adds_only_plugin_ignore_lines(before, after)
            else FOREIGN_LINES)


def _tracking(git_root, rels):
    """`{rel: TRACKED | UNTRACKED | UNKNOWN}` - whether git's index holds each of
    `rels`; `UNKNOWN` for one that cannot be spelled as a pathspec, or when
    `git ls-files` exits non-zero or could not be run. What an unknown means is
    the reader's, not this function's, so it is private and `plugin_owned_rels`,
    which takes the reader's side as an argument, is its one caller -
    `tests/test__scoped_commit.py` walks `scripts/` for any other.

    Each `rel` is spelled from the checkout's top, so it goes through
    `plan_to_git` as an entry of a project that IS the top: the pathspec is the
    one every other listing here is asked with.

    ONE LISTING FOR ALL OF THEM, and the same answer one listing each would give.
    A plain pathspec matches a listed path that is it or lies under it, so the
    paths git lists are matched back to each pathspec by that rule here; a
    pathspec git could read or print another way (`_plain_pathspec`) is asked
    alone. When the shared listing is refused, each
    pathspec is asked alone, so one that git rejects - outside the repository,
    say - leaves the others answered as they would have been."""
    hc = _loader.load_hooks_config(modname="audit__config")
    specs = dict((rel, hc.plan_to_git(rel, git_root, git_root)) for rel in rels)
    asked = sorted(set(spec for spec in specs.values() if spec is not None))
    shared = [spec for spec in asked if _plain_pathspec(spec)]
    if len(shared) < 2:
        shared = []
    queue = ([shared] if shared else []) + [[spec] for spec in asked
                                            if spec not in shared]
    answers = {}
    while queue:
        group = queue.pop(0)
        code, out, _err = run_git(git_root, ["ls-files", "-z", "--"] + group)
        if code != 0:
            if len(group) > 1:
                queue.extend([spec] for spec in group)
            continue
        listed = [p for p in out.split("\0") if p]
        for spec in group:
            answers[spec] = (bool(listed) if len(group) == 1
                             else any(_spec_holds(spec, p) for p in listed))
    return dict((rel, UNKNOWN if spec not in answers
                 else TRACKED if answers[spec] else UNTRACKED)
                for rel, spec in specs.items())


def _plain_pathspec(spec):
    """Whether git reads `spec` as the literal path it spells and prints it back
    the same way: no wildcard, no magic prefix, no empty, `.` or `..` segment, no
    backslash, and ASCII only - git may print a non-ASCII name in another
    Unicode form than it was asked in (`core.precomposeUnicode`)."""
    if (not spec or not spec.isascii() or spec.startswith((":", "/"))
            or any(c in spec for c in "*?[]\\")):
        return False
    return all(part not in ("", ".", "..") for part in spec.rstrip("/").split("/"))


def _spec_holds(spec, path):
    """Whether a plain pathspec matches a path git listed: the path itself, or
    one under it."""
    bare = spec.rstrip("/")
    return (path == spec and not spec.endswith("/")) or path.startswith(bare + "/")


def split_plugin_owned(paths, owned):
    """`(others, named)` - `paths` without the ones under a row of `owned`, and
    `[(path, why)]` for those that were."""
    others, named = [], []
    for path in paths:
        why = next((why for rel, why in owned
                    if _invariants._under(path, rel)), None)
        if why is None:
            others.append(path)
        else:
            named.append((path, why))
    return others, named


def undeclared_changes(git_root, project, config, record, started_at, owned,
                       bookkeeping):
    """`(changes, why)` - the ONE ANSWER to which paths an attempt changed that
    no in_progress task declares, and `(None, why)` when git would not list the
    tree.

    `changes` is `attribute`'s answer over the undeclared paths, plus:
    `covered` (the paths an entry of `owned` covers - work in flight, not this
    function's to judge), `strays` (the undeclared paths, whichever way they
    attribute) and `pluginOwned` (`[(path, why)]`, sorted: the plugin's own
    state, named and left out).

    `owned` is every declared entry of the in_progress tasks the caller counts
    as running, git-root relative. `bookkeeping` is the caller's own record
    paths - what a commit stages beside the task's files, what a close writes
    itself - which differ by reader and so arrive as an argument. Everything
    else a reader would have to know is decided here and nowhere else: the
    plugin's runtime directories (`run_state_rels`) and every row of
    `_manifest_io.PLUGIN_OWNED_IN_CLAUDE` (`plugin_owned_rels`) are never a
    task's edit, so a path the commit step leaves out as plugin-owned is
    never one the close refuses, nor one the set-aside reverts - except the
    committed configuration file, and a committed ignore file whose change
    adds a line the plugin does not write, which `plugin_owned_rels` leaves
    to the strays. A reader that kept a skip list of its own is the defect this
    function exists to remove. `tests/test__scoped_commit.py` fails by name
    when a reader names the primitives of one, and when a reader reads this
    answer other than by key or narrows an undeclared list by anything but a
    membership test (`result_scan`); a reader that reaches a skip by a route
    neither describes is not caught."""
    paths, why = status_paths(git_root)
    if paths is None:
        return None, why
    skip = list(bookkeeping) + run_state_rels(project, config, git_root)
    live = [p for p in paths if not under_any(p, skip)]
    mine = [p for p in live
            if any(_task_outputs.covers(entry, p) for entry in owned)]
    held = set(mine)
    rest = [p for p in live if p not in held]
    strays, named = split_plugin_owned(
        rest, plugin_owned_rels(project, git_root, UNKNOWN_REFUSES))
    changes = attribute(git_root, strays, record, started_at)
    changes["covered"] = mine
    changes["strays"] = strays
    changes["pluginOwned"] = sorted(set(named))
    return changes, ""


# --- what a close stands on ---------------------------------------------------
# A green gate over an unchanged tree proves only that nothing broke. So a close
# - the task commit, and `done --commit` after it - asks two things of the
# evidence before it calls the task finished: whether the task's declared files
# carry a change in what is being closed, and whether every file the task's
# `tests.add` names exists. Either answer refuses, naming the evidence; a task
# whose honest answer was that nothing needed to change closes through
# `--no-change`, which asks neither.
#
# THE TASK COMMIT ASKS THE FIRST QUESTION WHATEVER THE RED-FIRST WORD SAYS
# (`any_red_first`). Asked only beside a return saying `not-attempted`, it let
# a task run in a tree that never held its work - the finished change left in
# a kept worktree - come back `could-not-prove` and commit plan and record
# files alone: what the commit carries is the evidence, and what the return
# calls it is not. `done --commit` asks it of the whole attempt rather than of
# its SHA alone, because the change may already sit in an earlier commit since
# the task's start (`audit-task.py` `_close_evidence_refusal`).
RED_FIRST_NOT_ATTEMPTED = "not-attempted"


def absent_tests_add(task, project):
    """The paths the task's `tests.add` entries name that are not on disk under
    `project`, in the order the entries give them."""
    tests = task.get("tests") if isinstance(task.get("tests"), dict) else {}
    named = [_phases.tests_add_path(entry) for entry in tests.get("add") or []
             if isinstance(entry, str)]
    absent = []
    for path in named:
        if path and path not in absent \
                and not os.path.exists(os.path.join(project, path)):
            absent.append(path)
    return absent


def declared_work(task, project, git_root, records=()):
    """`[(name, rel), ...]` - the task's declared `files` that are its work: each
    entry in the plan's own spelling, its `:line-range` suffix dropped, beside
    its git-root-relative path (`_config.plan_to_git`), once each, in plan
    order. An entry outside the git root, or under one of the git-root-relative
    `records` paths, is not work and is left out.

    THE ONE READING OF IT. The task commit, the `done --commit` close and the
    refusal both of them print each ask which declared entries are work, and
    three readings of one list came to disagree about order and about what a
    record is - so every caller asks this one, narrowing by its own records."""
    hc = _loader.load_hooks_config(modname="audit__config")
    work, seen = [], set()
    for entry in task.get("files") or []:
        name = (_vocab._strip_line_suffix(entry).strip()
                if isinstance(entry, str) else "")
        if not name or name in seen:
            continue
        seen.add(name)
        rel = hc.plan_to_git(name, git_root, project)
        if rel is not None and not any(_task_outputs.covers(r, rel)
                                       for r in records or ()):
            work.append((name, rel))
    return work


def start_head_of(rows, task):
    """The HEAD the task's current attempt recorded on its newest `task.start`
    journal row (`rows`, the journal's full read), or None when no row of this
    attempt names one - a journal off, a start older than the record."""
    head = None
    for row in rows or []:
        details = row.get("details") if isinstance(row, dict) else None
        if (row.get("action") == "task.start" and isinstance(details, dict)
                and details.get("taskId") == task.get("id")
                and details.get("attempt") == task.get("attempts")):
            head = details.get("commit") or None
    return head if re.match(r"^[0-9a-fA-F]{7,40}$", head or "") else None


def _git_failure(what, code, err):
    """The clause naming a git call that did not answer, with its stderr."""
    return "`git %s` %s%s" % (
        what, "could not be run" if code is None else "exited %d" % (code,),
        ": %s" % (" ".join(err.split()),) if (err or "").strip() else "")


def _is_commit(git_root, ref):
    return run_git(git_root, ["rev-parse", "--verify", "-q",
                              "%s^{commit}" % (ref,)])[0] == 0


def attempt_span(git_root, project, plan, task, names, start_head, end="HEAD",
                 phase=None):
    """`(touched, why)` - each `(path, sha)` a commit of `task`'s attempt up to
    `end` changed, newest first, for the paths under `names` (the plan's own
    spelling of declared entries; each goes through `_config.plan_to_git` for
    git's pathspec, and each path git prints back through `git_to_plan`).
    `touched` is None - CANNOT TELL, never "no commits" - when git would not
    answer or the recorded start head bounds no span of `end`'s history, and
    `why` then names the call or the start head. Every caller refuses on None.

    THE ONLY READER OF THE ATTEMPT'S SPAN. The task commit asks it whether the
    work already sits in an earlier commit, `done --commit` whether the attempt
    changed anything declared, `done --no-change` how a declared file moved.
    Two readers of one span with different rules let a rebased branch close a
    task over another task's commits through one while the other refused.

    THE SPAN IS THE HEAD THE START RECORDED, AND NOTHING SOFTER. A clock reading
    (`--since startedAt`) has a second's grain and takes in a commit made just
    before the start. With no recorded head, or none git still holds, there is
    no span: `([], "")`, unless `phase` is given - then the span is the phase's
    `baseRef..end` cut by the task's `startedAt`, which is all a start from
    before the record can be asked about.

    A HEAD GIT HOLDS IS NOT YET A SPAN. After a rebase or a reset the recorded
    head can survive in the object store off `end`'s history, and `start..end`
    over it lists every commit since the merge base - commits that are not the
    attempt's. So the head must be an ancestor of `end`; when it is not, the
    answer is `(None, why)`: the span is unread, which is not the same answer
    as an empty one. `[]` there let `done --no-change` close over work the
    attempt had committed, because "no commit of the attempt" is what that
    close is asked to establish.

    A COMMIT ANOTHER TASK OF `plan` RECORDS AS ITS OWN IS NEVER IN IT, whichever
    bound the span has: it is that task's work."""
    hc = _loader.load_hooks_config(modname="audit__config")
    rels = [r for r in (hc.plan_to_git(n, git_root, project) for n in names)
            if r is not None]
    if not rels:
        return [], ""
    since = []
    if start_head and _is_commit(git_root, start_head):
        code, _out, err = run_git(git_root, ["merge-base", "--is-ancestor",
                                             start_head, end])
        if code == 1:
            return None, ("the start head %s recorded for this attempt is not an "
                        "ancestor of %s (the branch was rebased or reset "
                        "since), so no span from it names the attempt's commits"
                        % (start_head[:12], end if end == "HEAD" else end[:12]))
        if code != 0:
            return None, _git_failure("merge-base --is-ancestor", code, err)
        span = "%s..%s" % (start_head, end)
    elif phase is None:
        return [], ""
    else:
        base = phase.get("baseRef")
        span = ("%s..%s" % (base, end) if base and _is_commit(git_root, base)
                else end)
        since = (["--since=%s" % (task["startedAt"],)]
                 if task.get("startedAt") else [])
    whole = plan if plan is not None else {"phases": [phase] if phase else []}
    others = set(str(t.get("commit")) for t in _mio.tasks_by_id(whole).values()
                 if isinstance(t, dict) and t.get("commit")
                 and t.get("id") != task.get("id"))
    # A declared directory lists the files under it, so a commit line is told
    # apart by its own marker rather than by not being a declared path.
    code, out, err = run_git(git_root, ["log", "--format=@%H", "--name-only"]
                             + since + [span, "--"] + rels)
    if code != 0:
        return None, _git_failure("log %s" % (span,), code, err)
    touched, commit = [], None
    for line in [ln.strip() for ln in out.splitlines() if ln.strip()]:
        if line.startswith("@"):
            commit = line[1:]
        elif commit and commit not in others:
            touched.append((hc.git_to_plan(line, git_root, project), commit))
    return touched, ""


def close_evidence_refusal(task, project, executor, changed, declared=None,
                           tree=None, any_red_first=False, earlier=None,
                           earlier_why=""):
    """The sentence refusing a close whose evidence shows no work, or "".

    `executor` is the executor's filed return for the task's current start, or
    None; `changed` is whether the task's declared files carry a change in what
    is being closed - None when that could not be read, which asks only the
    `tests.add` question rather than guessing an answer to the other.
    `declared` names the files that question was asked of (the task's `files`
    when None); `tree` is the working tree the close is made from, whose bytes
    any verdict binding it measured, named when given. With `any_red_first` an
    unchanged declared set refuses whatever red-first the return records, and
    with none filed; without it, only beside `not-attempted`.

    `earlier` is the commits since the task's start that already changed a
    declared file (`attempt_span`): the work is then committed, so the repair
    is closing the task on that commit - `audit-task.py done <id> --commit
    <sha>` - and neither `--no-change` nor a tree to bring in fits.
    `earlier_why` is the reason that list could not be read - git did not
    answer, or the start head is off HEAD's history - said in the refusal
    rather than left out of it."""
    tid = str(task.get("id"))
    parts = []
    red = ((executor or {}).get("redFirst") or {}) \
        if isinstance(executor, dict) else {}
    word = red.get("status")
    if changed is False and (any_red_first or word == RED_FIRST_NOT_ATTEMPTED):
        said = ((executor.get("outcome") or {}).get("descriptive") or "").strip() \
            if isinstance(executor, dict) else ""
        names = list(declared) if declared is not None else [
            name for name, _rel in declared_work(task, project, project)]
        parts.append(
            "the task's declared files (%s) carry no change%s, so a green gate "
            "here proves only that nothing broke%s%s"
            % (", ".join(names) or "none outside the plan's records",
               " in %s - only plan and record files would be committed" % (tree,)
               if tree else "",
               "; the executor's filed return records red-first `%s`" % (word,)
               if isinstance(word, str) and word else "",
               " (its outcome: %r)" % (said[:120],) if said else ""))
        if tree and not earlier:
            parts.append("if the task's work sits in another worktree (a kept "
                         "task tree), bring it into %s first" % (tree,))
        if earlier_why:
            parts.append("whether the work already sits in an earlier commit "
                         "of this attempt could not be read - %s" % (earlier_why,))
    absent = absent_tests_add(task, project)
    if absent:
        parts.append("%s, named by the task's tests.add, %s not on disk"
                     % (", ".join(absent),
                        "is" if len(absent) == 1 else "are"))
    if not parts:
        return ""
    if earlier and changed is False:
        return ("%s. The task's work is already committed since its start (%s): "
                "close it on that commit with `audit-task.py done %s --commit "
                "%s`"
                % ("; ".join(parts), ", ".join(c[:12] for c in earlier[:3]),
                   tid, earlier[0][:12]))
    return ("%s. Restart it so the work is done (/audit:task start %s), or "
            "cancel it (/audit:task cancel %s --reason <why>); a task whose "
            "answer was that nothing needed to change closes with /audit:task "
            "done %s --no-change --reason <why>"
            % ("; ".join(parts), tid, tid, tid))


# --- the committed pair -------------------------------------------------------
# A commit carrying a plan record leaves the index and the shards git holds
# afterwards, and that pair has to validate. A shard's tasks declare files whose
# fileIndex rows live in the index, a bug link has a half in each file, and a new
# phase's stub mirrors its shard - so the commit carrying a shard carries the
# part of the index its phase owns, derived from that shard and laid over the
# index of the parent the commit is made on (`_invariants.owned_index`, the one
# function the grader re-derives the commit with from git afterwards).
index_rows_owed = _invariants.index_rows_owed


def rows_named(rows):
    """`path (taskId), ...` - the rows a refusal names, in the order given."""
    return ", ".join("%s (%s)" % (path, tid) for path, tid in rows)


def _document(path):
    """`(bytes, parsed)` of the JSON file at `path`, from ONE read, or
    `(None, None)` when it cannot be read or parsed."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
        return data, json.loads(data.decode("utf-8"))
    except (OSError, ValueError):
        return None, None


def index_to_carry(phase, manifest_path, git_root):
    """`{"rel", "shardRel", "phaseId", "head", "now", "nowBytes", "body",
    "bodyBytes", "needs", "doc", "unheld"}` - what the working shard of `phase`
    moves in the part of the index the phase owns, read against HEAD now, or
    None in the single-file layout (one file holds both halves) and when the
    index or the shard lives outside the git root.

    `head` is the index HEAD holds (None when it holds none), `now` the working
    index parsed and `nowBytes` its bytes (both None when it cannot be read),
    `body` the working shard parsed and `bodyBytes` the bytes it was parsed
    from (both None likewise) - the bytes `paired_blobs` commits the shard at,
    so the shard committed is the one the index part below was derived from.
    `needs` and `doc` are `_invariants.owned_index`
    of HEAD's index against the working shard - `doc` None when that moves
    nothing - and `unheld` the rows it adds that the WORKING index lacks too.
    Those no commit should paper over: the working plan itself fails
    validation there, and `audit-task.py reindex` is the repair, so a caller
    refuses on them.

    THIS IS THE DECISION, NOT THE BYTES. Whether the index rides is decided
    here; what it carries is `blob_builder`'s answer at the parent the commit
    is actually made on.
    """
    index_abs, phase_file_abs = _invariants.manifest_files(manifest_path, phase)
    if os.path.abspath(index_abs) == os.path.abspath(phase_file_abs):
        return None
    rel = _invariants._rel(index_abs, git_root)
    shard_rel = _invariants._rel(phase_file_abs, git_root)
    if rel is None or shard_rel is None:
        return None
    now_bytes, now = _document(index_abs)
    body_bytes, body = _document(phase_file_abs)
    pid = str((phase or {}).get("id"))
    head = _invariants.json_at(git_root, "HEAD", rel)
    needs, doc = _invariants.owned_index(
        head, now, body, _invariants.json_at(git_root, "HEAD", shard_rel), pid)
    lacking = index_rows_owed(now, body) if isinstance(now, dict) else []
    return {"rel": rel, "shardRel": shard_rel, "phaseId": pid, "head": head,
            "now": now if isinstance(now, dict) else None,
            "nowBytes": now_bytes if isinstance(now, dict) else None,
            "body": body, "bodyBytes": body_bytes if body is not None else None,
            "needs": needs,
            "doc": doc if doc is not None and doc != head else None,
            "unheld": [row for row in needs["rows"] if row in lacking]}


def paired_blobs(carry, kinds, index_build=None):
    """`{rel: build}` for `stage_and_commit`'s `blobs`: the shard of `carry`
    at the bytes `index_to_carry` read it as, whenever `kinds` (the commit's
    `{rel: kind}`) gives the shard a kind `stage` would add from the working
    file - an index entry, or a file only on disk - and the index at
    `index_build` when the index rides too. Empty for no `carry` - the
    single-file layout, where one file is both halves. Any other kind keeps
    what `stage` does with it: a shard deliberately untracked and ignored is
    committed as the deletion git holds, never added back.

    ONE READ FOR BOTH HALVES. The index part a commit carries is derived from
    `carry["body"]`; a shard staged from the working file later would commit
    whatever was written there in between - a task added while the commit ran
    - without the fileIndex rows it owes, and HEAD would hold a plan that
    does not validate. Committing the shard at the bytes its index part came
    from makes that split unreachable: a later write stays in the working tree,
    for the next commit to carry with its rows."""
    out = {}
    if not carry:
        return out
    if carry.get("bodyBytes") is not None \
            and kinds.get(carry["shardRel"]) in (IN_INDEX, ON_DISK):
        data = carry["bodyBytes"]
        out[carry["shardRel"]] = lambda _head: (data, "")
    if index_build is not None:
        out[carry["rel"]] = index_build
    return out


def blob_builder(git_root, carry, base=None):
    """`build(head) -> (bytes, why)`: the index to commit onto `head`, for
    `stage_and_commit`'s `blobs`. The owned part (`_invariants.owned_index`) is
    derived from the working shard against `head`'s own index and shard;
    everything else is `head`'s index - or `base`, a document the caller
    decided to carry whole."""
    def build(head):
        parent = _invariants.json_at(git_root, head, carry["rel"])
        _changes, doc = _invariants.owned_index(
            base if base is not None else parent, carry["now"], carry["body"],
            _invariants.json_at(git_root, head, carry["shardRel"]),
            carry["phaseId"])
        if doc is None:
            return None, ("the index %s holds at %s could not be read, so the "
                          "part this phase owns cannot be laid over it"
                          % (carry["rel"], (head or "HEAD")[:12]))
        return index_bytes(doc, carry), ""
    return build


def index_bytes(doc, carry):
    """The bytes of the index `doc`: the working file's own when `doc` is what
    it already holds, so the commit leaves no difference of spelling behind,
    else `_manifest_io.json_document`, the plugin's one spelling of a plan."""
    if carry.get("now") is not None and doc == carry["now"]:
        return carry["nowBytes"]
    return _mio.json_document(doc).encode("utf-8")


def unheld_rows_refusal(unheld):
    """The sentence a shard declaring files no index has a row for earns, or
    None."""
    if not unheld:
        return None
    return ("the shard this commit carries declares %s, and neither the index "
            "HEAD holds nor the working index has a fileIndex row for %s - the "
            "working plan does not validate ('missing from fileIndex'), so "
            "re-derive the index (audit-task.py reindex), then commit. Nothing "
            "was staged" % (rows_named(unheld),
                            "it" if len(unheld) == 1 else "them"))


# --- what happened ------------------------------------------------------------
def answer(skipped, committed=False, commit=None, staged=None, refused="",
           foreign=None, journalled=False, quiet="", done=None):
    """One shape for every outcome, so a caller never has to infer one from another.

    `committed` is its own field rather than being read off an empty `staged`
    list: "there was nothing to commit" and "the commit carried nothing" are
    different claims, and a falsy list would render them identically. `quiet`
    carries WHICH of the do-nothing states this was, for the same reason.

    ONE SHAPE ACROSS BOTH COMMANDS, which is what makes `--json` worth reading: a
    caller that has to branch on which verb produced a payload has been handed two
    formats wearing one name.

    `done` is `commit_with_rows`' answer when a commit was attempted, and the
    source of `nonce`, `carried` and `withdrawn` - what became of the rows that
    name the commit - so they are read off the attempt and never defaulted to a
    claim. Without it they say no row was written for a commit.
    """
    done = done or {}
    return {"committed": committed, "commit": commit,
            "staged": list(staged or []), "skipped": list(skipped or []),
            "refused": refused, "foreign": list(foreign or []),
            "journalled": journalled, "quiet": quiet,
            "nonce": done.get("nonce") or "",
            "carried": bool(done.get("carried")),
            "withdrawn": done.get("withdrawn")}


# WHAT BECAME OF THE ROW NAMING THE COMMIT, one sentence per state, said on the
# run that made it. `carried` is read back from what git staged, so the first
# sentence is printed only for a row that really is inside the commit.
ROW_CARRIED = ("the journal row naming this commit is inside it, keyed by its "
               "`%s: %s` trailer - `git log --grep` finds the commit from the "
               "row, after a rebase too")
ROW_NOT_CARRIED = ("the journal row naming this commit was written and is NOT "
                   "inside it - the journal is outside the git root or ignored "
                   "- so the trail is left uncommitted; its `%s: %s` trailer "
                   "still joins the two")
ROW_NOT_WRITTEN = ("the commit was made and the journal row could NOT be "
                   "written, so nothing in the trail points at it")
ROW_WITHDRAWN = ("the journal row written for this commit was withdrawn by a row "
                 "naming its nonce %s, so the trail claims no commit that does "
                 "not exist")
ROW_NOT_WITHDRAWN = ("the journal row written for this commit could NOT be "
                     "withdrawn, so it keys nonce %s to a commit that does not "
                     "exist - a reader finds no commit carrying it and reports "
                     "the gap")


def render(result, prefix, out=print):
    """Print what happened, in the order somebody reading a terminal needs it.

    `prefix` is the command's own bracketed name and is the only thing that
    differs between the two callers - which is why this is one function. The lines
    themselves must not diverge: two verbs that report a refusal in two shapes
    teach a reader that the shape means something, and here it does not.

    THE LAST LINE IS NEVER A DEFAULT. A row inside the commit, a row outside
    it, no row, and a withdrawn row are different states of the world, so each
    gets its own sentence; `journalled`, `carried` and `withdrawn` decide, because
    a line claiming the trail holds a row when it does not is worse than saying
    nothing at all.
    """
    for line in result["skipped"]:
        out("  degraded: %s" % (line,))
    if result["refused"]:
        out("%s REFUSED: %s" % (prefix, result["refused"]))
        for path in result["foreign"]:
            out("    already staged: %s" % (path,))
        withdrawn = result.get("withdrawn")
        if withdrawn is not None and not result["committed"]:
            out("  %s" % ((ROW_WITHDRAWN if withdrawn else ROW_NOT_WITHDRAWN)
                          % (result.get("nonce"),),))
        return
    if not result["committed"]:
        out("%s %s" % (prefix, result["quiet"]))
        return
    out("%s committed %s" % (prefix, result["commit"][:12]))
    for path in result["staged"]:
        out("    %s" % (path,))
    if not result["journalled"]:
        out("  %s" % (ROW_NOT_WRITTEN,))
    elif result.get("carried"):
        out("  %s" % (ROW_CARRIED % (_invariants.ROW_TRAILER,
                                     result.get("nonce")),))
    else:
        out("  %s" % (ROW_NOT_CARRIED % (_invariants.ROW_TRAILER,
                                         result.get("nonce")),))


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    print(__doc__.strip())
