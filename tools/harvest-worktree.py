#!/usr/bin/env python3
"""
A linked worktree's work, taken against the base that worktree ACTUALLY had.

    tools/harvest-worktree.py <worktree>               # patch + report
    tools/harvest-worktree.py <worktree> --out <path>  # ...to a named file
    tools/harvest-worktree.py <worktree> --json        # machine-readable
    tools/harvest-worktree.py <worktree> --base <rev>  # you name the base
    tools/harvest-worktree.py --selftest               # this file's own cases

IT PRODUCES A PATCH AND A REPORT, AND IT APPLIES NOTHING. Applying belongs to the
caller because the caller is the one who must run the suites the patch touches
afterwards and compare their case counts with what the agent reported - a clean
`git apply` proves only that the hunks matched. This file cannot do that half: it
does not know which suites the work is about, and a tool that changed the tree and
then handed the verification back would have moved the risky step away from the
only process that can watch it. `main()` writes a file and prints; there is no
apply path in it, and `h24` reads the source for every git verb that would write a
caller's tree, so this is a property of the module rather than a resolution.

WHY NOT `git diff main`. An orchestrator here took `git diff main` from a worktree
whose `main` had advanced since the agent started. Every commit `main` had gained
appeared in that patch REVERSED, because a patch says "make the tree look like this
worktree" and this worktree had never seen them. It applied cleanly and silently
reverted a sibling task's cases; nothing failed, and it was caught only because a
case count dropped and somebody looked. A branch name is a moving target and a base
is a fixed commit, so the repair is to name the commit - which is what
`established_base()` does.

WHERE THE BASE COMES FROM, AND WHY THAT IS THE RIGHT ANSWER. `established_base()`
reads the OLDEST entry of the worktree's own HEAD reflog, the `logs/HEAD` inside
`.git/worktrees/<name>/`, which git writes when `git worktree add` sets HEAD for the
first time and which no branch anywhere can move afterwards. That entry names the
commit this worktree started at, which is the definition of its base:

  * it survives the agent COMMITTING, because a commit APPENDS an entry and the
    oldest one stays oldest. So the work is `base..HEAD` plus whatever is dirty, and
    one `git diff <base>` - a base tree against the WORKING tree - carries both
    halves in a single patch;
  * it survives the agent moving its own branch, because nothing here reads a branch;
  * it survives the parent branch moving, for the same reason.

`git merge-base HEAD <parent>` was the alternative, and it needs a parent to name.
Git records no such thing for a worktree: an upstream is a guess, and the reflog line
reading "branch: Created from ..." belongs to the BRANCH, which may have existed long
before this worktree checked it out. A base derived from a name the tool picked would
be this file's own defect, one step quieter.

WHEN THE BASE IS NOT KNOWABLE, THIS REFUSES - `established_base()` returns a
`problem`, `main()` prints it, and the exit code is 1. Guessing is precisely the
failure, so there is no fallback. It is not knowable when:

  * the path is not inside a git worktree, or HEAD is unborn;
  * the path is the repository's MAIN worktree. Its HEAD reflog begins at `clone` or
    `init`, so the oldest entry is the repository's birth rather than any task's
    starting point, and nothing in it records when this session's work began;
  * the reflog is absent - `core.logAllRefUpdates` can be off - or will not parse;
  * the reflog's oldest surviving entry does not begin at the all-zero object id. A
    reflog beginning at a real commit has been expired or rewritten from the front,
    so the creation entry, the only one that means "base", is gone and the oldest
    survivor is merely some commit the worktree passed through;
  * the base is not an ancestor of HEAD, which is what a worktree rebased or reset
    onto something else looks like. A forward diff from a commit HEAD does not
    descend from carries every difference between the two histories as though the
    agent had written it.

`--base <rev>` is the way past the last of those and is deliberately a HUMAN's
argument rather than a fallback: a person naming one revision is consent, a tool
picking one is the guess this file exists to stop. It is validated exactly as a
derived base is - it must resolve to a commit and must be an ancestor of HEAD - and
the report says the base came from the flag, so an assertion is never printed where
a derivation would be.

WHAT THE REPORT CARRIES, AND WHY IT IS NOT ONE LINE. The same orchestrator read the
last line of a multi-file `git apply` and concluded the whole patch had landed when
most of it had not. So `render()` prints EVERY file on its own line with its own
added and deleted counts, every commit in `base..HEAD` on its own line, and the
totals a caller re-derives after applying; the verdict word is at the top and at the
bottom, and the verdicts are different WORDS rather than a number to be read.

IT ALSO NAMES THE THREE THINGS A `git status` CANNOT TELL APART. A clean worktree is
what "the agent wrote nothing" and "the agent committed and then the tree went clean"
both look like, and they mean opposite things. `committed`, `dirty` and the commit
list are three separate lines for that reason, so the pair is decidable from the
report alone rather than from a verdict word.

IT DOES NOT MUTATE THE WORKTREE, AND THAT IS CHECKED AT RUNTIME RATHER THAN PROMISED.
Untracked files have to be staged for a patch to carry them, so `produce_patch()`
stages them into a COPY of the index under `GIT_INDEX_FILE` and digests the real
index either side of the run; `index_untouched` is that comparison, it is printed,
and `h15` drives it.

Exit codes: 0 a patch was written - 1 refused, or git could not be asked - 2 usage
error - 3 nothing to apply, the base having been established and the worktree
holding no work.
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

# The path bootstrap, adapted: this file lives in tools/, outside scripts/, so the
# anchor is found by the known layout rather than by walking up for `_output.py`.
# Same shape as `tools/check-git-pipeline.py`, and for the same reason.
_here = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_here)
_scripts = os.path.join(REPO, "plugins", "audit", "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

import _output  # noqa: E402

# The verdicts, as words. A caller that reads the exit code and a reader who reads
# the last line must not be able to disagree, and two of these share an exit code -
# so the WORD is what separates "the agent wrote nothing" from "the agent's commits
# cancel out", and the code says only whether there is a patch to apply.
HARVESTED = "HARVESTED"
NOTHING = "NOTHING-TO-APPLY"
REFUSED = "REFUSED"

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
EXIT_NOTHING = 3

# `git add -N` takes the untracked paths as arguments, and a worktree can hold more
# of them than one command line will carry. Chunked rather than shelled through a
# file list, because the failure of an over-long argv is an OSError from the exec
# and not a git error anyone would recognise.
_ADD_CHUNK = 200

USAGE = ("usage: harvest-worktree.py <worktree> [--out PATH] [--base REV] "
         "[--json]\n       harvest-worktree.py --selftest\n")


# --- asking git ---------------------------------------------------------------
def git(args, cwd, env=None):
    """`(returncode, text)` for one git command: stdout and stderr, in order.

    Output is kept on a non-zero exit, because git writes the reason there and a
    helper that dropped it would turn every refusal below into "git said no".
    `core.quotePath=false` is pinned so a path with a non-ASCII byte in it arrives
    raw instead of `\\303\\251`-escaped - the file list and the patch have to name
    the same file.
    """
    argv = ["git", "-c", "core.quotePath=false"] + list(args)
    try:
        out = subprocess.run(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, timeout=300)
    except Exception as exc:                                   # noqa: BLE001
        return None, "git could not be run: %s" % (exc,)
    return out.returncode, out.stdout.decode("utf-8", "replace")


def git_bytes(args, cwd, env=None):
    """`(returncode, stdout_bytes, stderr_text)` for output that IS the product.

    Separate from `git()` on purpose: `git()` merges stderr into stdout, and a
    patch with a git warning spliced into it is a patch that will not apply. The
    bytes stay bytes for the same reason - a `--binary` diff is not text.
    """
    argv = ["git", "-c", "core.quotePath=false"] + list(args)
    try:
        out = subprocess.run(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, timeout=300)
    except Exception as exc:                                   # noqa: BLE001
        return None, b"", "git could not be run: %s" % (exc,)
    return out.returncode, out.stdout, out.stderr.decode("utf-8", "replace")


def _is_oid(text):
    """True for something shaped like an object id, under either hash algorithm."""
    return len(text) >= 40 and all(ch in "0123456789abcdef" for ch in text)


def _is_null_oid(text):
    """True for the all-zero object id git writes when a ref did not exist yet."""
    return _is_oid(text) and text.strip("0") == ""


def _sha256_file(path):
    """The digest of a file, or None when it cannot be read."""
    try:
        with io.open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except (IOError, OSError):
        return None


def resolve_worktree(path, env=None):
    """Where this worktree is, and whether it is a LINKED one.

    Returns `{"top", "git_dir", "common_dir", "linked", "branch", "problem"}`.

    `linked` is decided by comparing the worktree's own git directory with the
    repository's COMMON one, which is the only thing that actually distinguishes
    the two: a linked worktree's admin directory is `.git/worktrees/<name>` and the
    main worktree's is the common directory itself. Deciding it by whether `.git`
    is a file rather than a directory would be reading the spelling of a layout
    instead of asking git what it has.
    """
    out = {"top": None, "git_dir": None, "common_dir": None, "linked": False,
           "branch": None, "problem": None}
    if not os.path.isdir(path):
        out["problem"] = "%s is not a directory" % (path,)
        return out
    rc, text = git(["rev-parse", "--show-toplevel"], path, env)
    if rc != 0 or not text.strip():
        out["problem"] = ("%s is not inside a git worktree, so it has no base to "
                          "take work against: %s" % (path, text.strip()))
        return out
    top = text.strip().splitlines()[-1]
    out["top"] = top

    rc, text = git(["rev-parse", "--git-dir"], top, env)
    if rc != 0:
        out["problem"] = "git would not name the git directory of %s: %s" % (
            top, text.strip())
        return out
    git_dir = text.strip()
    if not os.path.isabs(git_dir):
        git_dir = os.path.join(top, git_dir)
    out["git_dir"] = git_dir

    rc, text = git(["rev-parse", "--git-common-dir"], top, env)
    if rc != 0:
        out["problem"] = "git would not name the common git directory of %s: %s" % (
            top, text.strip())
        return out
    common = text.strip()
    if not os.path.isabs(common):
        common = os.path.join(top, common)
    out["common_dir"] = common
    out["linked"] = os.path.realpath(git_dir) != os.path.realpath(common)

    rc, text = git(["symbolic-ref", "--quiet", "--short", "HEAD"], top, env)
    out["branch"] = text.strip() if rc == 0 and text.strip() else None
    return out


# --- the base, and when it is not knowable ------------------------------------
def reflog_origin(text):
    """`{"oid", "problem"}` - the commit the OLDEST entry of a HEAD reflog set.

    Pure, over the reflog's own text, so the three ways it can fail to answer are
    cases rather than fixtures. Git's format is `<old> <new> <who> <when>\\t<msg>`,
    one entry per line, oldest first.

    THE NULL-ID TEST IS THE WHOLE POINT. An entry whose OLD value is the all-zero
    id is one that set a ref which did not exist before, which for a per-worktree
    HEAD is the `git worktree add` that created it. If the oldest surviving entry
    starts at a real commit instead, entries have been expired or rewritten off the
    front and the creation entry is gone - the survivor is just a commit the
    worktree passed through on its way here, and taking it for the base would
    silently under-report the work by however much was trimmed.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return {"oid": None, "problem": "the HEAD reflog is empty, so nothing "
                                        "records what this worktree started at"}
    parts = lines[0].split(" ")
    if len(parts) < 2 or not _is_oid(parts[0]) or not _is_oid(parts[1]):
        return {"oid": None,
                "problem": "the HEAD reflog's oldest entry does not parse as one, "
                           "so the base cannot be read out of it: %r"
                           % (lines[0][:120],)}
    if not _is_null_oid(parts[0]):
        return {"oid": None,
                "problem": "the HEAD reflog's oldest surviving entry moves HEAD "
                           "from %s rather than from the null id, so the entry "
                           "that recorded this worktree's creation has been "
                           "expired or rewritten away and the base is no longer "
                           "recorded anywhere" % (parts[0][:12],)}
    return {"oid": parts[1], "problem": None}


def established_base(wt, explicit=None, env=None):
    """`{"base", "head", "basis", "problem"}` - the commit this worktree started at.

    `basis` travels with `base` and is never omitted: a commit id with no account
    of where it came from is the thing that made `git diff main` look reasonable.

    `explicit` is a revision a HUMAN named on the command line. It is accepted as a
    SOURCE and not as a shortcut - it goes through the same two validations a
    derived base does, because a base that is not an ancestor of HEAD produces a
    misleading patch whoever chose it.
    """
    out = {"base": None, "head": None, "basis": None, "problem": None}
    top = wt["top"]
    rc, text = git(["rev-parse", "--verify", "HEAD^{commit}"], top, env)
    if rc != 0 or not _is_oid(text.strip()):
        out["problem"] = ("HEAD does not resolve to a commit in %s - an unborn or "
                          "broken HEAD has no base: %s" % (top, text.strip()))
        return out
    head = text.strip()
    out["head"] = head

    if explicit is not None:
        rc, text = git(["rev-parse", "--verify", "%s^{commit}" % (explicit,)],
                       top, env)
        if rc != 0 or not _is_oid(text.strip()):
            out["problem"] = ("--base %s does not resolve to a commit in this "
                              "worktree: %s" % (explicit, text.strip()))
            return out
        base = text.strip()
        basis = "named by --base %s on the command line, not derived" % (explicit,)
    else:
        if not wt["linked"]:
            out["problem"] = (
                "%s is the repository's MAIN worktree, not a linked one. Its HEAD "
                "reflog begins at the clone or the init, so its oldest entry is "
                "the repository's birth and not any task's starting point - "
                "nothing here records when this session's work began. Pass "
                "--base <rev> if you know the commit the work started from."
                % (top,))
            return out
        log_path = os.path.join(wt["git_dir"], "logs", "HEAD")
        try:
            with io.open(log_path, encoding="utf-8", errors="replace") as fh:
                log_text = fh.read()
        except (IOError, OSError) as exc:
            out["problem"] = ("this worktree's HEAD reflog could not be read, so "
                              "what it started at is not recorded anywhere "
                              "(core.logAllRefUpdates off?): %s: %s"
                              % (log_path, exc))
            return out
        origin = reflog_origin(log_text)
        if origin["problem"] is not None:
            out["problem"] = "%s (%s)" % (origin["problem"], log_path)
            return out
        rc, text = git(["rev-parse", "--verify", "%s^{commit}" % (origin["oid"],)],
                       top, env)
        if rc != 0 or not _is_oid(text.strip()):
            out["problem"] = ("the HEAD reflog names %s as this worktree's "
                              "starting point and that object is not a commit "
                              "here: %s" % (origin["oid"][:12], text.strip()))
            return out
        base = text.strip()
        basis = ("the oldest entry of this worktree's own HEAD reflog (%s), "
                 "written when the worktree was created" % (log_path,))

    rc, text = git(["merge-base", "--is-ancestor", base, head], top, env)
    if rc == 1:
        out["problem"] = (
            "%s is not an ancestor of HEAD (%s), which is what a worktree rebased "
            "or reset onto something else looks like. A forward diff from a commit "
            "HEAD does not descend from carries every difference between the two "
            "histories as though the agent had written it, so this refuses rather "
            "than guessing. Name the commit the work sits on with --base <rev>."
            % (base[:12], head[:12]))
        return out
    if rc != 0:
        out["problem"] = ("git could not be asked whether %s is an ancestor of "
                          "HEAD, so the base is unverified: %s"
                          % (base[:12], text.strip()))
        return out

    out["base"] = base
    out["basis"] = basis
    return out


# --- what state the worktree is in --------------------------------------------
def _subject_of(rev, top, env=None):
    """One commit's subject line, or "" when git will not say."""
    rc, text = git(["log", "-1", "--format=%s", rev], top, env)
    return text.strip().splitlines()[0] if rc == 0 and text.strip() else ""


def work_state(top, base, env=None):
    """`{"commits", "merges", "dirty", "tracked_changes", "untracked", "problem"}`.

    The three facts a caller's next step depends on, asked separately. `commits` is
    what the agent committed on top of its base, `tracked_changes` and `untracked`
    are what it left in the tree, and each is reported even when the others are
    empty - "the agent wrote nothing" and "the agent committed and the tree is
    clean" are the pair this exists to tell apart.

    A MERGE in `base..HEAD` is recorded rather than refused. It means somebody
    refreshed this worktree from elsewhere, so the patch may carry work the agent
    did not write; that is a thing for the caller's eyes and not a thing this can
    decide, and the commit list beside it is what makes it checkable.
    """
    out = {"commits": [], "merges": [], "dirty": False, "tracked_changes": [],
           "untracked": [], "problem": None}
    sep = "\x1f"
    rc, text = git(["log", "--reverse",
                    "--format=%H" + sep + "%P" + sep + "%an" + sep + "%s",
                    "%s..HEAD" % (base,)], top, env)
    if rc != 0:
        out["problem"] = "git could not list %s..HEAD: %s" % (base[:12],
                                                              text.strip())
        return out
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split(sep)
        if len(fields) < 4:
            out["problem"] = "a commit line did not parse: %r" % (line[:120],)
            return out
        parents = fields[1].split()
        row = {"sha": fields[0], "author": fields[2], "subject": fields[3],
               "merge": len(parents) > 1}
        out["commits"].append(row)
        if row["merge"]:
            out["merges"].append(row["sha"])

    rc, text = git(["status", "--porcelain"], top, env)
    if rc != 0:
        out["problem"] = "git status failed in %s: %s" % (top, text.strip())
        return out
    for line in text.splitlines():
        if not line.strip():
            continue
        out["dirty"] = True
        if not line.startswith("??"):
            out["tracked_changes"].append(line.rstrip())

    rc, text = git(["ls-files", "--others", "--exclude-standard"], top, env)
    if rc != 0:
        out["problem"] = "git could not list untracked files in %s: %s" % (
            top, text.strip())
        return out
    out["untracked"] = [ln for ln in text.splitlines() if ln.strip()]
    return out


# --- the patch ----------------------------------------------------------------
def parse_numstat(text):
    """`{"rows": [(added, deleted, path)], "unparsed": [line]}`.

    `added`/`deleted` are None for a binary file, which git spells `-`. Rows that
    do not parse are HANDED BACK rather than dropped: a count nobody could read is
    a different answer from a file with no changes, and this whole file exists
    because a caller compared counts.
    """
    rows = []
    unparsed = []
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) < 3:
            unparsed.append(line[:120])
            continue
        added = None if fields[0] == "-" else fields[0]
        deleted = None if fields[1] == "-" else fields[1]
        path = "\t".join(fields[2:])
        try:
            added = None if added is None else int(added)
            deleted = None if deleted is None else int(deleted)
        except ValueError:
            unparsed.append(line[:120])
            continue
        rows.append((added, deleted, path))
    return {"rows": rows, "unparsed": unparsed}


def parse_name_status(text):
    """`{path: status_letter}` from `git diff --name-status --no-renames`."""
    out = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) < 2:
            continue
        out["\t".join(fields[1:])] = fields[0]
    return out


def produce_patch(wt, base, untracked, env=None):
    """`{"patch", "files", "insertions", "deletions", "index_untouched", "notes",
    "problem"}` - one patch carrying committed AND uncommitted work.

    ONE `git diff <base>` AND NOT TWO. With a single commit argument git compares
    that tree against the WORKING tree, so `base..HEAD` and whatever is dirty come
    out as one patch; taking `git diff base..HEAD` and `git diff HEAD` separately
    would hand the caller two patches that have to be applied in order and can each
    fail alone.

    UNTRACKED FILES ARE IN IT, STAGED INTO A COPY OF THE INDEX. A diff cannot see a
    file git does not know about, and for agent work the new files are usually the
    whole point - a patch that quietly omitted them is the silent loss this file is
    against. `git add -N` is what makes them visible, and pointing `GIT_INDEX_FILE`
    at a copy is what keeps that out of the worktree the agent is still holding.
    `index_untouched` digests the real index either side and is reported, so the
    claim is checked on every run rather than asserted here.

    `--no-renames` on the patch AND on both stat reads, so the file list and the
    patch describe exactly the same set. A rename is then a delete and an add,
    which is more bytes and no ambiguity: rename records make the numstat line
    three-valued and the reported paths stop matching the patched ones.
    """
    out = {"patch": b"", "files": [], "insertions": 0, "deletions": 0,
           "index_untouched": None, "notes": [], "problem": None}
    top = wt["top"]
    real_index = os.path.join(wt["git_dir"], "index")
    before = _sha256_file(real_index)

    handle, tmp_index = tempfile.mkstemp(prefix="harvest-worktree-index-")
    os.close(handle)
    try:
        staging = dict(os.environ if env is None else env)
        staging["GIT_INDEX_FILE"] = tmp_index
        if before is not None:
            shutil.copyfile(real_index, tmp_index)
        else:
            # No index on disk yet. An empty file is not a valid one, so the copy
            # is replaced by a fresh read of HEAD into the same path.
            os.remove(tmp_index)
            rc, text = git(["read-tree", "HEAD"], top, staging)
            if rc != 0:
                out["problem"] = "could not build a scratch index: %s" % (
                    text.strip(),)
                return out

        for start in range(0, len(untracked), _ADD_CHUNK):
            batch = untracked[start:start + _ADD_CHUNK]
            rc, text = git(["add", "-N", "--"] + batch, top, staging)
            if rc != 0:
                out["problem"] = ("untracked files could not be staged into the "
                                  "scratch index, so a patch built now would omit "
                                  "them: %s" % (text.strip(),))
                return out

        rc, raw, err = git_bytes(["diff", "--binary", "--no-renames", base],
                                 top, staging)
        if rc != 0:
            out["problem"] = "git diff against %s failed: %s" % (base[:12],
                                                                 err.strip())
            return out
        out["patch"] = raw

        rc, text = git(["diff", "--numstat", "--no-renames", base], top, staging)
        if rc != 0:
            out["problem"] = "git could not count the change: %s" % (text.strip(),)
            return out
        stats = parse_numstat(text)
        if stats["unparsed"]:
            out["notes"].append("some counts could not be read, so the totals "
                                "below are short by whatever those rows held: %r"
                                % (stats["unparsed"],))

        rc, text = git(["diff", "--name-status", "--no-renames", base], top,
                       staging)
        if rc != 0:
            out["problem"] = "git could not name the changed files: %s" % (
                text.strip(),)
            return out
        letters = parse_name_status(text)
    finally:
        try:
            os.remove(tmp_index)
        except (IOError, OSError):
            pass

    new_files = set(untracked)
    for added, deleted, path in stats["rows"]:
        out["files"].append({"path": path, "status": letters.get(path, "?"),
                             "added": added, "deleted": deleted,
                             "untracked_in_worktree": path in new_files})
        out["insertions"] += added or 0
        out["deletions"] += deleted or 0
    out["files"].sort(key=lambda row: row["path"])

    after = _sha256_file(real_index)
    out["index_untouched"] = before == after
    if not out["index_untouched"]:
        out["notes"].append("the worktree's index changed while this ran - either "
                            "something else is writing in there, or the scratch "
                            "index did not hold. Do not trust this patch as a "
                            "picture of a still tree.")
    return out


# --- putting it together ------------------------------------------------------
def harvest(path, explicit_base=None, env=None):
    """The whole answer for one worktree, as a dict. Never raises, never applies.

    `verdict` is the word; `exit_code` is what `main()` returns. Both come out of
    here so that the machine-readable shape and the printed one cannot disagree
    about what happened.
    """
    result = {"worktree": os.path.abspath(path), "verdict": REFUSED,
              "exit_code": EXIT_REFUSED, "problem": None, "linked": False,
              "branch": None, "base": None, "base_subject": None, "basis": None,
              "head": None, "head_subject": None, "committed": False,
              "commits": [], "merges": [], "dirty": False,
              "tracked_changes": [], "untracked": [], "files": [],
              "insertions": 0, "deletions": 0, "index_untouched": None,
              "notes": [], "patch_bytes": 0, "patch_sha256": None,
              "patch_path": None, "_patch": b""}

    wt = resolve_worktree(path, env)
    if wt["problem"] is not None:
        result["problem"] = wt["problem"]
        return result
    result.update({"worktree": wt["top"], "linked": wt["linked"],
                   "branch": wt["branch"]})

    found = established_base(wt, explicit_base, env)
    if found["problem"] is not None:
        result["problem"] = found["problem"]
        return result
    result.update({"base": found["base"], "basis": found["basis"],
                   "head": found["head"]})
    result["base_subject"] = _subject_of(found["base"], wt["top"], env)
    result["head_subject"] = _subject_of(found["head"], wt["top"], env)

    state = work_state(wt["top"], found["base"], env)
    if state["problem"] is not None:
        result["problem"] = state["problem"]
        return result
    result.update({"commits": state["commits"], "merges": state["merges"],
                   "committed": bool(state["commits"]), "dirty": state["dirty"],
                   "tracked_changes": state["tracked_changes"],
                   "untracked": state["untracked"]})
    if state["merges"]:
        result["notes"].append("base..HEAD contains a merge, so this worktree was "
                               "refreshed from somewhere else and the patch may "
                               "carry work the agent did not write. Read the "
                               "commit list below before applying.")

    built = produce_patch(wt, found["base"], state["untracked"], env)
    if built["problem"] is not None:
        result["problem"] = built["problem"]
        return result
    result.update({"files": built["files"], "insertions": built["insertions"],
                   "deletions": built["deletions"],
                   "index_untouched": built["index_untouched"],
                   "_patch": built["patch"],
                   "patch_bytes": len(built["patch"]),
                   "patch_sha256": hashlib.sha256(built["patch"]).hexdigest()})
    result["notes"].extend(built["notes"])

    if built["patch"]:
        result["verdict"] = HARVESTED
        result["exit_code"] = EXIT_OK
    else:
        result["verdict"] = NOTHING
        result["exit_code"] = EXIT_NOTHING
    return result


def public(result):
    """`result` without the keys that are not JSON - the patch's bytes are a file."""
    return dict((key, value) for key, value in result.items()
                if not key.startswith("_"))


def write_patch(result, out_path=None):
    """Write the patch and record where. Returns the path, or "" plus a problem.

    A patch is written only for `HARVESTED`. An empty file is a thing a caller can
    apply, and applying it succeeds, and a success that means "nothing happened" is
    the shape of report this whole file is a complaint about.
    """
    if result["verdict"] != HARVESTED:
        return "", ""
    target = out_path
    if target is None:
        target = os.path.join(tempfile.mkdtemp(prefix="harvest-worktree-"),
                              "work.patch")
    try:
        directory = os.path.dirname(os.path.abspath(target))
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        with io.open(target, "wb") as fh:
            fh.write(result["_patch"])
    except (IOError, OSError) as exc:
        return "", "the patch could not be written to %s: %s" % (target, exc)
    return target, ""


# --- the report ---------------------------------------------------------------
def _count_line(label, value):
    """One `label   value` row, aligned so the file list reads as a column."""
    return "%-12s %s" % (label, value)


def render(result, stream=None):
    """Print the report. Every file on its own line; the verdict top and bottom.

    The shape answers a specific misreading: an orchestrator read the LAST line of
    a multi-file `git apply` and took it for the whole outcome. So there is no line
    here that summarises the others - the totals are beside the list rather than
    instead of it, and a reader who scans only the first and last lines still gets
    a verdict word rather than a number.
    """
    fh = stream or sys.stdout
    lines = ["%s  %s" % (result["verdict"], result["worktree"])]
    if result["problem"] is not None:
        lines.append("")
        lines.append("the base this worktree's work must be taken against is not "
                     "knowable, so nothing was produced:")
        lines.append("  %s" % (result["problem"],))
        lines.append("")
        lines.append("%s  no patch written" % (REFUSED,))
        _output.write_lf_lines(lines, fh)
        return

    lines.append(_count_line("worktree", "%s  (%s, %s)" % (
        result["worktree"],
        "linked" if result["linked"] else "MAIN worktree",
        ("on " + result["branch"]) if result["branch"] else "detached HEAD")))
    lines.append(_count_line("base", "%s  %s" % (result["base"][:12],
                                                 result["base_subject"])))
    lines.append(_count_line("basis", result["basis"]))
    lines.append(_count_line("head", "%s  %s" % (result["head"][:12],
                                                 result["head_subject"])))
    lines.append(_count_line("committed", "yes" if result["committed"] else "no"))
    for row in result["commits"]:
        lines.append("  %s  %s  (%s)%s" % (
            row["sha"][:12], row["subject"], row["author"],
            "  MERGE" if row["merge"] else ""))
    lines.append(_count_line("dirty", "yes" if result["dirty"] else "no"))
    lines.append(_count_line("  tracked", "%d modified in the tree"
                             % (len(result["tracked_changes"]),)))
    lines.append(_count_line("  untracked", "%d not yet added to git"
                             % (len(result["untracked"]),)))
    lines.append(_count_line("index", "untouched" if result["index_untouched"]
                             else "CHANGED WHILE THIS RAN"))

    lines.append(_count_line("files", "%d" % (len(result["files"]),)))
    for row in result["files"]:
        lines.append("  %s  %-48s +%s  -%s%s" % (
            row["status"], row["path"],
            "?" if row["added"] is None else row["added"],
            "?" if row["deleted"] is None else row["deleted"],
            "  (new file)" if row["untracked_in_worktree"] else ""))
    lines.append(_count_line("totals", "%d files, +%d, -%d"
                             % (len(result["files"]), result["insertions"],
                                result["deletions"])))
    if result["patch_path"]:
        lines.append(_count_line("patch", "%s  (%d bytes)"
                                 % (result["patch_path"],
                                    result["patch_bytes"])))
        lines.append(_count_line("sha256", result["patch_sha256"]))
    for note in result["notes"]:
        lines.append("NOTE: %s" % (note,))

    lines.append("")
    if result["verdict"] == HARVESTED:
        lines.append("apply it yourself, then run the suites the files above "
                     "belong to and compare their case counts with what the agent "
                     "reported. This tool does not apply and does not verify.")
        lines.append("%s  %d files, +%d, -%d  ->  %s"
                     % (HARVESTED, len(result["files"]), result["insertions"],
                        result["deletions"], result["patch_path"]))
    else:
        lines.append("%s  the base was established and this worktree holds no "
                     "work against it%s"
                     % (NOTHING,
                        " - but it has commits on top of the base whose changes "
                        "cancel out, which is not the same as an agent that wrote "
                        "nothing" if result["committed"] else
                        ": no commits on top of the base, and a clean tree"))
    _output.write_lf_lines(lines, fh)


def main(argv, env=None, stream=None):
    """Parse, harvest, write, report. Returns the exit code and applies nothing."""
    path = None
    out_path = None
    explicit = None
    as_json = False
    rest = list(argv)
    while rest:
        arg = rest.pop(0)
        if arg in ("-h", "--help"):
            sys.stdout.write(USAGE)
            return EXIT_USAGE
        if arg == "--json":
            as_json = True
        elif arg == "--out":
            if not rest:
                sys.stderr.write("ERROR: --out needs a path\n" + USAGE)
                return EXIT_USAGE
            out_path = rest.pop(0)
        elif arg == "--base":
            if not rest:
                sys.stderr.write("ERROR: --base needs a revision\n" + USAGE)
                return EXIT_USAGE
            explicit = rest.pop(0)
        elif arg.startswith("-"):
            sys.stderr.write("ERROR: unknown option %s\n" % (arg,) + USAGE)
            return EXIT_USAGE
        elif path is None:
            path = arg
        else:
            sys.stderr.write("ERROR: one worktree at a time, got %s as well\n"
                             % (arg,) + USAGE)
            return EXIT_USAGE
    if path is None:
        sys.stderr.write("ERROR: name the worktree to harvest\n" + USAGE)
        return EXIT_USAGE

    result = harvest(path, explicit, env)
    written, problem = write_patch(result, out_path)
    if problem:
        result["verdict"] = REFUSED
        result["exit_code"] = EXIT_REFUSED
        result["problem"] = problem
    else:
        result["patch_path"] = written or None

    fh = stream or sys.stdout
    if as_json:
        _output.write_lf_lines([json.dumps(public(result), indent=1,
                                           sort_keys=True)], fh)
    else:
        render(result, fh)
    return result["exit_code"]


# --- selftest -----------------------------------------------------------------
FIXTURE_NAME = "Harvest Fixture"
FIXTURE_EMAIL = "harvest@example.invalid"


def fixture_env(root):
    """The environment every git call in the fixture gets - pinned, not inherited.

    Same reasoning as `tools/check-git-pipeline.py`: `git config user.name` falls
    back to `~/.gitconfig` and then to the system file, so a fixture that sets only
    a repo-local identity still answers with whoever is running the suite. The
    config paths point inside the fixture at a file that is never created, which
    git reads as an empty one.
    """
    env = dict(os.environ)
    nowhere = os.path.join(root, "no-such-gitconfig")
    env.update({
        "HOME": root,
        "USERPROFILE": root,
        "GIT_CONFIG_GLOBAL": nowhere,
        "GIT_CONFIG_SYSTEM": nowhere,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": FIXTURE_NAME,
        "GIT_AUTHOR_EMAIL": FIXTURE_EMAIL,
        "GIT_COMMITTER_NAME": FIXTURE_NAME,
        "GIT_COMMITTER_EMAIL": FIXTURE_EMAIL,
    })
    env.pop("GIT_INDEX_FILE", None)
    return env


def _write(path, text):
    """Write one fixture file, making its directory first."""
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def build_fixture(root):
    """A real repository with four real linked worktrees. `{"problem": str}` on
    failure, so a fixture that could not be built is a named failing case rather
    than a traceback.

    The four are the states a caller actually meets: one that committed, one that
    only has a dirty tree, one nobody touched, and one whose parent branch moved on
    without it. The last is the recorded fault, rebuilt: a sibling commit lands on
    `main` AFTER the worktree is created, so a patch taken against the branch name
    would revert it.
    """
    env = fixture_env(root)
    repo = os.path.join(root, "repo")
    os.makedirs(repo)
    steps = [["init", "-q", "--initial-branch=main", "."],
             ["config", "user.name", FIXTURE_NAME],
             ["config", "user.email", FIXTURE_EMAIL]]
    for step in steps:
        rc, text = git(step, repo, env)
        if rc != 0:
            return {"problem": "git %s failed: %s" % (step[0], text.strip())}
    _write(os.path.join(repo, "shared.txt"), "one\n")
    _write(os.path.join(repo, "sibling-cases.txt"), "case a\ncase b\n")
    for step in [["add", "-A"], ["commit", "-qm", "base commit"]]:
        rc, text = git(step, repo, env)
        if rc != 0:
            return {"problem": "git %s failed: %s" % (step[0], text.strip())}

    trees = {}
    for name in ("committed", "dirty", "clean", "moved"):
        target = os.path.join(root, "wt-" + name)
        rc, text = git(["worktree", "add", "-q", "-b", "task-" + name, target],
                       repo, env)
        if rc != 0:
            return {"problem": "git worktree add %s failed: %s" % (name,
                                                                   text.strip())}
        trees[name] = target

    # The worktree that committed, and then left its tree clean.
    _write(os.path.join(trees["committed"], "agent-new.txt"), "agent wrote this\n")
    _write(os.path.join(trees["committed"], "shared.txt"), "one\ntwo\n")
    for step in [["add", "-A"], ["commit", "-qm", "agent work, committed"]]:
        rc, text = git(step, trees["committed"], env)
        if rc != 0:
            return {"problem": "committed fixture: %s" % (text.strip(),)}

    # The worktree that committed nothing: one tracked edit, one new file.
    _write(os.path.join(trees["dirty"], "shared.txt"), "one\ndirty\n")
    _write(os.path.join(trees["dirty"], "brand-new.txt"), "never added\n")

    # `trees["clean"]` is left exactly as `git worktree add` made it.

    # The parent branch moves on, in the MAIN worktree, after every worktree above
    # already exists. This is the recorded fault's shape.
    _write(os.path.join(repo, "sibling-cases.txt"), "case a\ncase b\ncase c\n")
    for step in [["add", "-A"], ["commit", "-qm", "sibling task adds a case"]]:
        rc, text = git(step, repo, env)
        if rc != 0:
            return {"problem": "sibling commit failed: %s" % (text.strip(),)}
    _write(os.path.join(trees["moved"], "moved-agent.txt"), "the other agent\n")

    return {"problem": None, "root": root, "repo": repo, "env": env,
            "trees": trees}


def _harvest_text(path, fx, extra=None):
    """`(exit_code, printed)` for one `main()` run against the fixture."""
    held = io.StringIO()
    code = main([path] + list(extra or []), env=fx["env"], stream=held)
    return code, held.getvalue()


def _fixture_cases(check, fx):
    """Every case that needs the real repository. Split out so `run()` reports a
    fixture failure as one named case with the cheap ones already printed."""
    env = fx["env"]
    trees = fx["trees"]
    repo = fx["repo"]

    main_wt = resolve_worktree(repo, env)
    linked = resolve_worktree(trees["clean"], env)
    check("h1 a linked worktree is told from the main one by comparing its own git "
          "directory with the repository's common one, which is the only thing "
          "that distinguishes them: %r vs %r"
          % (main_wt["linked"], linked["linked"]),
          main_wt["problem"] is None and linked["problem"] is None
          and main_wt["linked"] is False and linked["linked"] is True)

    rc, tip_now = git(["rev-parse", "main"], repo, env)
    tip_now = tip_now.strip()
    found = established_base(linked, None, env)
    rc2, at_creation = git(["rev-parse", "main~1"], repo, env)
    at_creation = at_creation.strip()
    check("h2 the base of an untouched worktree is where main stood WHEN IT WAS "
          "CREATED, not where main stands now - the whole defect, asserted on a "
          "branch that really moved: base=%r, main now=%r"
          % (found["base"], tip_now),
          rc == 0 and rc2 == 0 and found["problem"] is None
          and found["base"] == at_creation and found["base"] != tip_now)
    check("h3 ...and the base never travels without the account of where it came "
          "from: %r" % (found["basis"],),
          found["basis"] is not None and "reflog" in found["basis"])

    committed = harvest(trees["committed"], None, env)
    check("h4 a worktree that COMMITTED reports its commits, a clean tree, and a "
          "patch - the state a bare `git status` cannot tell from an agent that "
          "wrote nothing: committed=%r dirty=%r files=%r"
          % (committed["committed"], committed["dirty"],
             [row["path"] for row in committed["files"]]),
          committed["problem"] is None and committed["committed"] is True
          and committed["dirty"] is False
          and [row["subject"] for row in committed["commits"]]
          == ["agent work, committed"]
          and sorted(row["path"] for row in committed["files"])
          == ["agent-new.txt", "shared.txt"]
          and committed["verdict"] == HARVESTED)

    dirty = harvest(trees["dirty"], None, env)
    new_rows = [row for row in dirty["files"] if row["untracked_in_worktree"]]
    check("h5 a worktree that only has a DIRTY TREE reports no commits and a patch "
          "that carries the untracked file as well - a diff cannot see a file git "
          "does not know about, and for agent work the new file is usually the "
          "point: committed=%r files=%r"
          % (dirty["committed"], [row["path"] for row in dirty["files"]]),
          dirty["problem"] is None and dirty["committed"] is False
          and dirty["dirty"] is True
          and sorted(row["path"] for row in dirty["files"])
          == ["brand-new.txt", "shared.txt"]
          and [row["path"] for row in new_rows] == ["brand-new.txt"]
          and b"+never added" in dirty["_patch"])

    clean = harvest(trees["clean"], None, env)
    check("h6 an UNTOUCHED worktree is reported as holding no work, with the base "
          "established and a distinct exit code - this is the allow case, and it "
          "is what goes red if the work test is widened: verdict=%r code=%r "
          "files=%r" % (clean["verdict"], clean["exit_code"], clean["files"]),
          clean["problem"] is None and clean["base"] is not None
          and clean["verdict"] == NOTHING and clean["exit_code"] == EXIT_NOTHING
          and clean["files"] == [] and clean["_patch"] == b""
          and clean["committed"] is False and clean["dirty"] is False)

    moved = harvest(trees["moved"], None, env)
    harvested_paths = sorted(row["path"] for row in moved["files"])
    rc, wrong_way = git(["diff", "--name-only", "main"], trees["moved"], env)
    wrong_paths = sorted(ln for ln in wrong_way.splitlines() if ln.strip())
    check("h7 when the PARENT BRANCH has moved since the worktree was created, the "
          "patch carries the agent's file and nothing else - while `git diff main` "
          "from the same worktree names the sibling's file too, which is the "
          "revert that shipped. Both taken here: ours=%r, `git diff main`=%r"
          % (harvested_paths, wrong_paths),
          moved["problem"] is None and rc == 0
          and harvested_paths == ["moved-agent.txt"]
          and "sibling-cases.txt" in wrong_paths
          and b"sibling-cases.txt" not in moved["_patch"])

    applied = _apply_elsewhere(fx, moved, "replay-moved")
    check("h8 ...and that patch really applies to a checkout of the base it names, "
          "producing the agent's file and leaving the sibling's alone: %r"
          % (applied,),
          applied["problem"] is None and applied["agent_file"] == "the other agent\n"
          and applied["sibling_file"] == "case a\ncase b\n")

    on_main = harvest(repo, None, env)
    check("h9 the MAIN worktree is refused rather than answered, because its HEAD "
          "reflog begins at the init and its oldest entry is the repository's "
          "birth: %r" % ((on_main["verdict"], (on_main["problem"] or "")[:70]),),
          on_main["verdict"] == REFUSED and on_main["base"] is None
          and "MAIN worktree" in (on_main["problem"] or ""))

    outside = harvest(os.path.join(fx["root"], "not-a-repo-at-all"), None, env)
    check("h10 a path that is not a directory at all is refused with that as the "
          "reason, not with a traceback: %r" % ((outside["problem"] or "")[:70],),
          outside["verdict"] == REFUSED
          and "not a directory" in (outside["problem"] or ""))

    trimmed = _trim_reflog(fx, trees["committed"])
    after_trim = harvest(trees["committed"], None, env)
    check("h11 a HEAD reflog whose creation entry has been expired off the front "
          "is refused - the oldest survivor is merely a commit the worktree passed "
          "through, and taking it for the base would under-report the work: %r"
          % ((after_trim["problem"] or "")[:90],),
          trimmed["problem"] is None and after_trim["verdict"] == REFUSED
          and "expired or rewritten away" in (after_trim["problem"] or ""))

    with_flag = harvest(trees["committed"], at_creation, env)
    check("h12 ...and `--base` is the way past it, with the report saying the base "
          "was NAMED rather than derived so an assertion is never printed where a "
          "derivation would be: %r" % (with_flag["basis"],),
          with_flag["problem"] is None and with_flag["base"] == at_creation
          and "not derived" in (with_flag["basis"] or "")
          and with_flag["verdict"] == HARVESTED)
    restored = _restore_reflog(fx, trees["committed"], trimmed)
    check("h13 (the fixture's reflog is put back, so the cases after this one see "
          "the worktree git made: %r)" % (restored,), restored is True)

    not_ancestor = harvest(trees["committed"], tip_now, env)
    check("h14 a base that is not an ancestor of HEAD is refused whoever chose it "
          "- a forward diff from there carries every difference between the two "
          "histories as though the agent had written it: %r"
          % ((not_ancestor["problem"] or "")[:70],),
          not_ancestor["verdict"] == REFUSED
          and "not an ancestor of HEAD" in (not_ancestor["problem"] or ""))

    check("h15 the real index is byte-identical after a run that had to stage "
          "untracked files, so the worktree the agent is still holding was not "
          "written to - checked on every run, not promised here: %r"
          % (dirty["index_untouched"],),
          dirty["index_untouched"] is True)

    code_h, text_h = _harvest_text(trees["dirty"], fx,
                                   ["--out", os.path.join(fx["root"], "d.patch")])
    code_n, text_n = _harvest_text(trees["clean"], fx)
    code_r, text_r = _harvest_text(fx["repo"], fx)
    firsts = [text_h.splitlines()[0].split()[0], text_n.splitlines()[0].split()[0],
              text_r.splitlines()[0].split()[0]]
    lasts = [text_h.strip().splitlines()[-1].split()[0],
             text_n.strip().splitlines()[-1].split()[0],
             text_r.strip().splitlines()[-1].split()[0]]
    check("h16 the three outcomes are three different WORDS at the top and at the "
          "bottom of the report, and their exit codes agree - a reader who scans "
          "one line and a caller who reads the code cannot disagree: %r %r %r"
          % (firsts, lasts, (code_h, code_n, code_r)),
          firsts == [HARVESTED, NOTHING, REFUSED]
          and lasts == [HARVESTED, NOTHING, REFUSED]
          and (code_h, code_n, code_r) == (EXIT_OK, EXIT_NOTHING, EXIT_REFUSED)
          and len(set(firsts)) == 3)

    listed = [ln for ln in text_h.splitlines()
              if "brand-new.txt" in ln or "shared.txt" in ln]
    check("h17 every file is on its own line with its own counts, beside the "
          "totals rather than instead of them - the misreading this answers was a "
          "caller taking the last line of a multi-file apply for the whole "
          "outcome: %r" % (listed,),
          len(listed) == 2
          and any(ln.strip().startswith("A ") for ln in listed)
          and any(ln.strip().startswith("M ") for ln in listed)
          and "totals" in text_h and "+1" in text_h)

    check("h18 a refused report offers no patch path at all, so there is nothing "
          "for a caller to apply when the base was never established: %r"
          % (text_r.strip().splitlines()[-1],),
          "no patch written" in text_r and ".patch" not in text_r)


def _apply_elsewhere(fx, result, name):
    """Apply `result`'s patch to a FRESH checkout of the base it names, and read
    back what landed. The only place in this suite that applies anything - the
    tool does not, and a patch nobody ever applied is a patch nobody has checked.
    """
    out = {"problem": None, "agent_file": None, "sibling_file": None}
    target = os.path.join(fx["root"], name)
    rc, text = git(["worktree", "add", "-q", "--detach", target, result["base"]],
                   fx["repo"], fx["env"])
    if rc != 0:
        out["problem"] = "replay worktree failed: %s" % (text.strip(),)
        return out
    patch = os.path.join(fx["root"], name + ".patch")
    with io.open(patch, "wb") as fh:
        fh.write(result["_patch"])
    rc, text = git(["apply", "--whitespace=nowarn", patch], target, fx["env"])
    if rc != 0:
        out["problem"] = "the patch did not apply: %s" % (text.strip(),)
        return out
    for key, rel in (("agent_file", "moved-agent.txt"),
                     ("sibling_file", "sibling-cases.txt")):
        try:
            with io.open(os.path.join(target, rel), encoding="utf-8") as fh:
                out[key] = fh.read()
        except (IOError, OSError) as exc:
            out["problem"] = "%s unreadable after apply: %s" % (rel, exc)
    return out


def _reflog_path(fx, tree):
    """The `logs/HEAD` of one linked worktree, through git rather than by guess."""
    wt = resolve_worktree(tree, fx["env"])
    if wt["problem"] is not None:
        return None
    return os.path.join(wt["git_dir"], "logs", "HEAD")


def _trim_reflog(fx, tree):
    """Drop the creation entry off the front of a worktree's HEAD reflog, the way
    `git reflog expire` would. `{"problem", "held"}` - `held` is the original text.
    """
    path = _reflog_path(fx, tree)
    if path is None:
        return {"problem": "could not locate the reflog", "held": None}
    try:
        with io.open(path, encoding="utf-8") as fh:
            held = fh.read()
        kept = [ln for ln in held.splitlines() if ln.strip()][1:]
        if not kept:
            return {"problem": "the fixture reflog has only the creation entry, "
                               "so trimming it proves nothing", "held": held}
        with io.open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(kept) + "\n")
    except (IOError, OSError) as exc:
        return {"problem": "could not trim the reflog: %s" % (exc,), "held": None}
    return {"problem": None, "held": held}


def _restore_reflog(fx, tree, trimmed):
    """Put a trimmed reflog back. True when the file reads as it did before."""
    path = _reflog_path(fx, tree)
    if path is None or trimmed.get("held") is None:
        return False
    try:
        with io.open(path, "w", encoding="utf-8") as fh:
            fh.write(trimmed["held"])
        with io.open(path, encoding="utf-8") as fh:
            return fh.read() == trimmed["held"]
    except (IOError, OSError):
        return False


def _cases(check):
    from _suite import remove_tree     # tools/_suite.py says why this is deferred

    check("h19 the reflog reader refuses an oldest entry that does not begin at "
          "the null id, and accepts one that does - the null id is what says an "
          "entry CREATED the ref, which for a per-worktree HEAD is the "
          "`git worktree add`",
          reflog_origin("0" * 40 + " " + "a" * 40 + " who <a@b> 1 +0000\n")["oid"]
          == "a" * 40
          and reflog_origin("b" * 40 + " " + "a" * 40 + " who <a@b> 1 +0000\n")
          ["oid"] is None
          and "expired or rewritten away" in reflog_origin(
              "b" * 40 + " " + "a" * 40 + " who <a@b> 1 +0000\n")["problem"])
    check("h20 ...and an empty or unparsable reflog is a stated problem rather "
          "than a silent absence of a base",
          reflog_origin("")["oid"] is None
          and "empty" in reflog_origin("")["problem"]
          and reflog_origin("not a reflog line\n")["oid"] is None
          and "does not parse" in reflog_origin("not a reflog line\n")["problem"])
    check("h21 a 64-character object id is an object id too, so this does not "
          "quietly stop working on a sha256 repository",
          reflog_origin("0" * 64 + " " + "c" * 64 + " who <a@b> 1 +0000\n")["oid"]
          == "c" * 64)

    # The paths here carry no Python extension on purpose. `tool_basename_drift()`
    # reads every `.py` basename literal under `tools/` and requires it to name a
    # file that exists, and it cannot tell a reference from a fixture - so a case
    # that only needs A PATH spells one that is not a module name, which is the
    # spelling that rule's docstring asks for instead of a table row.
    check("h22 a numstat row that cannot be read is handed back rather than "
          "dropped, because a count nobody could read and a file with no changes "
          "are different answers - and a binary file's `-` is a third one",
          parse_numstat("3\t1\tsrc/alpha.txt\n")["rows"]
          == [(3, 1, "src/alpha.txt")]
          and parse_numstat("-\t-\tlogo.png\n")["rows"]
          == [(None, None, "logo.png")]
          and parse_numstat("garbage\n")["unparsed"] == ["garbage"]
          and parse_numstat("x\ty\tsrc/zeta.txt\n")["unparsed"]
          == ["x\ty\tsrc/zeta.txt"])

    check("h23 `public()` drops the patch bytes and keeps everything a caller "
          "compares afterwards, so --json is serialisable without losing the "
          "counts",
          "_patch" not in public({"_patch": b"x", "files": [], "insertions": 2})
          and public({"_patch": b"x", "insertions": 2})["insertions"] == 2)

    check("h24 nothing in this module applies a patch: the git verbs it can reach "
          "are read-only ones plus the scratch-index staging, which is why the "
          "docstring's promise is a property of the source and not a resolution",
          _apply_verbs_in_source() == [])

    root = tempfile.mkdtemp(prefix="harvest-worktree-selftest-")
    try:
        fx = build_fixture(root)
        if fx.get("problem"):
            check("h25 the fixture repository and its four worktrees were built: %s"
                  % (fx["problem"],), False)
            return
        check("h25 the fixture repository and its four worktrees were built", True)
        _fixture_cases(check, fx)
    finally:
        # Git writes its loose objects read-only, and `shutil.rmtree` leaves them
        # behind on windows - silently, with `ignore_errors`. The sweep asserts the
        # scratch directory is empty afterwards, so that debris would convict this
        # suite rather than the removal.
        remove_tree(root)


def _apply_verbs_in_source():
    """Every git verb this module can invoke that WRITES the caller's tree.

    Read out of the source rather than asserted, because "it does not apply" is the
    claim the docstring makes about the whole file and a resolution is not a
    mechanism. The staging verbs are named as allowed: `add -N` and `read-tree`
    write an index under `GIT_INDEX_FILE`, which `produce_patch` points at a copy.
    """
    import ast
    writing = ("apply", "am", "cherry-pick", "checkout", "reset", "revert",
               "merge", "rebase", "stash", "restore", "commit", "push", "clean")
    allowed_callers = ("build_fixture", "_apply_elsewhere", "_fixture_cases")
    found = []
    with io.open(os.path.abspath(__file__), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    owners = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for child in ast.walk(node):
                owners[id(child)] = node.name
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else None
        if name not in ("git", "git_bytes") or not node.args:
            continue
        first = node.args[0]
        if not isinstance(first, ast.List) or not first.elts:
            continue
        verb = first.elts[0]
        # `ast.Constant`, not `ast.Str`: the alias was removed in 3.12 and this
        # tree holds a 3.8 floor, so the node to read is the one that exists in
        # both. A deprecation shim is not a thing to depend on in either direction.
        if not isinstance(verb, ast.Constant) or not isinstance(verb.value, str):
            continue
        if verb.value not in writing:
            continue
        if owners.get(id(node)) in allowed_callers:
            continue
        found.append((owners.get(id(node)), verb.value))
    return found


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    _output.safe_stdio()
    _args = sys.argv[1:]
    if "--selftest" in _args:
        raise SystemExit(_selftest())
    raise SystemExit(main(_args))
