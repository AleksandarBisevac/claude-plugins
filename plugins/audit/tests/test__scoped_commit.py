#!/usr/bin/env python3
"""
The cases for `_scoped_commit.py` — what the three committing commands share.

WHAT THIS FILE IS ABOUT. `commit-audit-state.py`, `commit-manifest-index.py` and
`commit-task-work.py` each stage a fixed allow-list and refuse everything else,
and the parts that decide "refuse" - and how each path is staged, and how the
index is put back - are here rather than in any of them. The suites beside those
commands prove each verb end to end; this one proves the shared parts in both
directions, because a helper that is only ever seen agreeing with its caller may
be asserting nothing.

EVERY GIT CASE RUNS AGAINST A REAL REPOSITORY. The claims are claims about what
git prints — a rename's two names, an untracked directory that porcelain would
otherwise collapse, an error message that arrives on stderr and nowhere else —
and a fake would encode the assumption instead of the behaviour.

THE STDERR CASE IS THE ONE THAT SAYS WHY THIS RUNNER EXISTS. `_commit_trail._git`
sends stderr to `DEVNULL`, which is right for a read whose absence is an answer;
here a refusal's only readable form is that stream, so `sc1` asserts it comes
back non-empty rather than asserting merely that the call failed.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import io
import os
import subprocess
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _scoped_commit as M                         # noqa: E402


def _git(repo, *args):
    """git in the fixture, or the reason it failed - a half-built repo is not one."""
    done = subprocess.run(["git", "-C", repo] + list(args),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if done.returncode != 0:
        raise RuntimeError("git %s failed in %s: %s"
                           % (" ".join(args), repo,
                              done.stdout.decode("utf-8", "replace")[:300]))
    return done.stdout.decode("utf-8", "replace")


def _write(path, text):
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _repo(tmp, name):
    """A repository with one commit: `keep/a.txt` tracked, nothing else.

    Small on purpose. The cases below each add exactly the one shape they are
    about, so a case that goes red names the shape rather than the fixture.
    """
    repo = os.path.join(tmp, name)
    os.makedirs(repo)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "fixture@example.com")
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "config", "commit.gpgsign", "false")
    _write(os.path.join(repo, "keep", "a.txt"), "a\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


# --- cases --------------------------------------------------------------------
def _cases(check):
    tmp = _harness.fixture_root("audit-scoped-commit-")
    repo = _repo(tmp, "repo")
    outside = os.path.join(tmp, "not-a-repo")
    os.makedirs(outside)

    ok_code, ok_out, ok_err = M.run_git(repo, ["rev-parse", "--git-dir"])
    bad_code, bad_out, bad_err = M.run_git(outside, ["diff", "--cached",
                                                     "--name-only"])
    check("sc1 the runner KEEPS stderr, which is the whole reason it is not "
          "`_commit_trail._git`: git explains a refusal there and nowhere else, "
          "so a runner that discarded it would turn every refusal into a bare "
          "exit code. The pair is over one function - a call that works returns "
          "output and no complaint, one that cannot returns the complaint: %r"
          % (bad_err.strip()[:80],),
          ok_code == 0 and ok_out.strip() and ok_err == ""
          and bad_code not in (0, None) and bad_err.strip())

    check("sc2 git's lines are forward-slashed and the blanks dropped - the "
          "allow-list is built from `os.path` joins, and two spellings of one "
          "path make the comparison answer 'not allowed' for a path that is: %r"
          % (M.lines("docs\\audit\\x.json\n\n  \nsrc/a.py\n"),),
          M.lines("docs\\audit\\x.json\n\n  \nsrc/a.py\n")
          == ["docs/audit/x.json", "src/a.py"]
          and M.lines("") == [] and M.lines(None) == [])

    check("sc3 the list form carries the separator and an empty list allows "
          "NOTHING: a sibling whose name merely starts the same way is outside, "
          "and an unresolved allow-list is the direction that cannot invent a "
          "pass. Asserted in both directions over one call, because 'it said no' "
          "also passes for a predicate that always says no",
          M.under_any("docs/audit/evidence/x.jsonl", ["docs/audit/evidence"])
          and M.under_any("docs/audit/evidence", ["docs/audit/evidence"])
          and not M.under_any("docs/audit/evidence-notes/x.jsonl",
                              ["docs/audit/evidence"])
          and not M.under_any("docs/audit/evidence/x.jsonl", [])
          and not M.under_any("docs/audit/evidence/x.jsonl", [""]))

    _write(os.path.join(repo, "keep", "b.txt"), "b\n")
    _write(os.path.join(repo, "stray.txt"), "stray\n")
    _git(repo, "add", "keep/b.txt", "stray.txt")
    seen, seen_why = M.foreign_staged(repo, ["keep"])
    check("sc4 what is staged OUTSIDE the allow-list comes back and what is "
          "inside it does not - the pair over one index, because a function that "
          "returned everything staged would also pass a case that only looked "
          "for the stray: %r" % (seen,),
          seen == ["stray.txt"] and seen_why == "")

    blind, blind_why = M.foreign_staged(outside, ["keep"])
    check("sc5 an index git will not describe yields a REASON and never an empty "
          "list. Read as 'nothing foreign', that answer is precisely what lets a "
          "staged source file into a commit nobody reviewed: %r"
          % (blind_why[:80],),
          blind == [] and blind_why and "would not list" in blind_why)

    _git(repo, "reset", "-q")
    _write(os.path.join(repo, "fresh", "deep", "n.txt"), "n\n")
    pending, pending_why = M.uncommitted(repo, ["fresh"])
    check("sc6 a file inside a WHOLLY untracked directory is named, not collapsed "
          "to the directory: without `--untracked-files=all` porcelain prints one "
          "`fresh/` entry, and a caller asking which paths would be carried gets a "
          "directory instead of an answer: %r" % (pending,),
          pending == ["fresh/deep/n.txt"] and pending_why == "")

    _git(repo, "mv", os.path.join("keep", "a.txt"), os.path.join("keep", "z.txt"))
    renamed, _why = M.uncommitted(repo, ["keep"])
    check("sc7 a RENAME is reported as the name that exists now. Porcelain writes "
          "`R  old -> new` and a slice off the front keeps the old one, which is a "
          "path no `git add` can stage: %r" % (renamed,),
          "keep/z.txt" in renamed
          and not any("->" in p for p in renamed))
    _git(repo, "reset", "-q", "--hard")

    nothing = M.answer([], quiet="there was nothing")
    empty = M.answer([], committed=True, commit="0" * 40, staged=[])
    check("sc8 'there was nothing to commit' and 'the commit carried nothing' are "
          "different claims, and `committed` is its own field so they cannot "
          "render the same. Read off a falsy `staged` list they would: %r / %r"
          % (nothing["committed"], empty["committed"]),
          nothing["committed"] is False and empty["committed"] is True
          and nothing["staged"] == [] and empty["staged"] == [])

    said = []
    M.render(M.answer(["a record went missing"], refused="the index holds work",
                      foreign=["src/a.py"]), "[a-verb]", out=said.append)
    check("sc9 a refusal prints the degraded lines, the verb's own name and every "
          "path it refused over - and stops there rather than falling through to "
          "the committed branch, which would print a SHA for a commit nobody "
          "made: %r" % (said,),
          said == ["  degraded: a record went missing",
                   "[a-verb] REFUSED: the index holds work",
                   "    already staged: src/a.py"])

    quiet_said, done_said = [], []
    M.render(M.answer([], quiet="nothing was uncommitted"), "[b-verb]",
             out=quiet_said.append)
    M.render(M.answer([], committed=True, commit="abcdef0123456789",
                      staged=["docs/audit/audit-plan.json"], journalled=False),
             "[b-verb]", out=done_said.append)
    check("sc10 the PREFIX is the only thing that differs between the two verbs "
          "using this renderer, and a commit whose journal row could not be "
          "written says so - the commit happened and nothing in the trail points "
          "at it, which is the one thing a reader cannot find out later: %r / %r"
          % (quiet_said, done_said),
          quiet_said == ["[b-verb] nothing was uncommitted"]
          and done_said[0] == "[b-verb] committed abcdef012345"
          and done_said[1] == "    docs/audit/audit-plan.json"
          and "journal row could NOT be written" in done_said[2])

    # --- the header a commitlint repository will take -------------------------
    # BOTH WRITERS OPEN WITH TEXT THEY OWN AND CLOSE WITH TEXT A CALLER GAVE
    # THEM, and every repair to the opening spent some of the one commitlint rule
    # nothing was measuring from inside the code. The caller's half had no bound
    # at all, so a long `--subject` produced a header a husky+commitlint repo
    # refuses AFTER the files are staged, leaving somebody to finish the commit
    # by hand - which is the failure the fixed opening exists to prevent,
    # reached from the other end.
    fixed = "chore(audit-index): phase P1 - "
    short = M.fitted_header(fixed, "carried alone")
    long_subject = "x" * (M.HEADER_MAX_CHARS * 2)
    cut = M.fitted_header(fixed, long_subject)
    check("sc11 a header with room to spare is returned untouched, so the "
          "overwhelming majority of commits read exactly as they did before "
          "anything was bounded: %r" % (short,),
          short == fixed + "carried alone"
          and M.SUBJECT_TRUNCATED not in short)
    check("sc12 ...and one that would overrun is cut IN THE SUBJECT: the "
          "opening the command owns survives whole, the header fits the bound, "
          "and the cut says so rather than leaving a short subject and a "
          "shortened one identical in `git log`: %r" % (cut,),
          cut.startswith(fixed) and len(cut) <= M.HEADER_MAX_CHARS
          and cut.endswith(M.SUBJECT_TRUNCATED)
          and len(cut) > len(fixed) + len(M.SUBJECT_TRUNCATED))
    # SECOND DIRECTION, and the one a clamp gets wrong by cutting the wrong end:
    # a command whose own opening has outgrown the bound has a defect this
    # function cannot repair, and writing the marker into a header that is still
    # too long would hide it behind a line that looks bounded.
    outgrown = "z" * (M.HEADER_MAX_CHARS + 10) + ": "
    check("sc13 ...and an opening with no room left for any of the subject "
          "comes back ALONE, marker included, because a cut that cannot be made "
          "in the caller's half is not a cut to make in the command's: %r"
          % (M.fitted_header(outgrown, "a subject nobody will read"),),
          M.fitted_header(outgrown, "a subject nobody will read") == outgrown)
    _row_cases(check, tmp)
    _staging_cases(check, tmp, outside)


# --- the row inside the commit -------------------------------------------------
def _trailers(repo, message):
    """What `git interpret-trailers --parse` reads out of `message`."""
    done = subprocess.run(["git", "-C", repo, "interpret-trailers", "--parse"],
                          input=message.encode("utf-8"), stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT)
    return done.stdout.decode("utf-8", "replace").splitlines()


def _refuse_commits(repo):
    hooks = os.path.join(repo, ".git", "hooks")
    _write(os.path.join(hooks, "pre-commit"), "#!/bin/sh\nexit 1\n")
    os.chmod(os.path.join(hooks, "pre-commit"), 0o755)
    _git(repo, "config", "core.hooksPath", hooks)


def _row_cases(check, tmp):
    repo = _repo(tmp, "rows")
    coauthor = "Co-Authored-By: A Person <a@example.com>"
    both = M.with_row_trailer(["chore(x): phase P1 - a subject", coauthor], "n1")
    alone = M.with_row_trailer(["chore(x): phase P1 - a subject"], "n2")
    check("sc25 the row trailer joins the LAST paragraph, so git still reads the "
          "co-author line as a trailer beside it - a paragraph of its own after "
          "the co-author would stop that one being a trailer - and with only a "
          "subject it becomes that paragraph: %r / %r"
          % (_trailers(repo, "\n\n".join(both)),
             _trailers(repo, "\n\n".join(alone))),
          len(both) == 2
          and _trailers(repo, "\n\n".join(both)) == [coauthor,
                                                      M.row_trailer("n1")]
          and _trailers(repo, "\n\n".join(alone)) == [M.row_trailer("n2")])

    seen, withdrawn = [], []

    def rows(nonce):
        seen.append(nonce)
        path = os.path.join(repo, "trail", "r.jsonl")
        _write(path, '{"nonce": "%s"}\n' % (nonce,))
        return [path], ""

    _write(os.path.join(repo, "keep", "a.txt"), "a2\n")
    kinds = M.classify(repo, [("keep/a.txt", True)])
    done = M.commit_with_rows(repo, ["keep/a.txt"], kinds, ["chore: a"],
                              lambda paths: "foreign", rows,
                              lambda nonce, why: withdrawn.append(nonce) or "w")
    carried = _git(repo, "show", "--name-only", "--pretty=format:",
                   "HEAD").split()
    body = _git(repo, "log", "-1", "--format=%B")
    check("sc26 the row is written BEFORE the commit, its file is added to an "
          "allow-list that did not hold it, and the commit carries it with the "
          "nonce the row was keyed by as its trailer - `carried` is read back "
          "from what git staged: %r / %r / %r" % (done, carried, body),
          done["committed"] and done["carried"] and done["journalled"]
          and done["withdrawn"] is None and len(seen) == 1
          and done["nonce"] == seen[0]
          and sorted(carried) == ["keep/a.txt", "trail/r.jsonl"]
          and M.row_trailer(seen[0]) in body.splitlines() and withdrawn == [])

    _write(os.path.join(repo, "keep", "a.txt"), "a3\n")
    _refuse_commits(repo)
    head = _git(repo, "rev-parse", "HEAD").strip()
    found = _git(repo, "ls-files", "-s")
    done = M.commit_with_rows(repo, ["keep/a.txt"],
                              M.classify(repo, [("keep/a.txt", True)]),
                              ["chore: a"], lambda paths: "foreign", rows,
                              lambda nonce, why: withdrawn.append(nonce) or "w")
    check("sc27 a commit a hook REFUSES after the row was written withdraws "
          "that row's nonce, once, puts the index back and claims no carried "
          "row - the row stays where it was written, in the working tree, and "
          "cannot be read as a commit: %r / %r" % (done, withdrawn),
          not done["committed"] and done["refused"]
          and M.INDEX_RESTORED in done["refused"]
          and withdrawn == [seen[-1]] and done["withdrawn"] is True
          and not done["carried"]
          and _git(repo, "rev-parse", "HEAD").strip() == head
          and _git(repo, "ls-files", "-s") == found)

    del withdrawn[:]
    done = M.commit_with_rows(
        repo, ["keep/a.txt"], M.classify(repo, [("keep/a.txt", True)]),
        ["chore: a"], lambda paths: "foreign",
        lambda nonce: (rows(nonce)[0], "a required row could not be written"),
        lambda nonce, why: withdrawn.append((nonce, why)) or "w")
    check("sc28 a row the commit REQUIRES that could not be written refuses "
          "before anything is staged, and withdraws the rows that did land: "
          "%r / %r" % (done, withdrawn),
          not done["committed"] and "Nothing was staged" in done["refused"]
          and withdrawn == [(seen[-1], "a required row could not be written")]
          and _git(repo, "ls-files", "-s") == found)

    said = {}
    for label, carried_flag in (("in", True), ("out", False)):
        lines = []
        M.render(M.answer([], committed=True, commit="abcdef0123456789",
                          staged=["keep/a.txt"], journalled=True,
                          done={"nonce": "n9", "carried": carried_flag}),
                 "[v]", out=lines.append)
        said[label] = lines[-1]
    check("sc29 the success line says the row is inside the commit only when "
          "git staged it, and says it is NOT otherwise - the pair over one "
          "flag, so neither sentence can become the default: %r" % (said,),
          said["in"] == "  " + M.ROW_CARRIED % ("Audit-Row", "n9")
          and said["out"] == "  " + M.ROW_NOT_CARRIED % ("Audit-Row", "n9"))


# --- how a path is staged, and putting the index back ------------------------
def _unborn(tmp, name):
    """A repository with no commit at all: HEAD names a branch that does not exist."""
    repo = os.path.join(tmp, name)
    os.makedirs(repo)
    _git(repo, "init", "-q")
    return repo


def _staging_cases(check, tmp, outside):
    unborn = _unborn(tmp, "unborn")
    check("sc14 in a repository with no commit yet, HEAD holds NOTHING - an "
          "answer, not an unknown: `ls-tree HEAD` fails there, and reading that "
          "failure as 'not established' would keep every absent declared path "
          "in a pathspec the first commit then refuses: %r"
          % (M.in_head(unborn, ["x.py"]),),
          M.in_head(unborn, ["x.py"]) == set())
    check("sc15 ...and a directory git will not describe at all is NOT "
          "established, which is the other answer and a different one: %r"
          % (M.in_head(outside, ["x.py"]),),
          M.in_head(outside, ["x.py"]) is None)

    snap, why = M.snapshot(outside, ["x.py"])
    check("sc16 an index this module cannot read is not snapshotted, and the "
          "refusal says nothing was staged - a staging it could not undo is not "
          "one it may start: %r" % (why,),
          snap is None and "nothing was staged" in why)
    said = M.restored(outside, {"entries": [], "ita": []}, ["x.py"], "boom")
    check("sc17 a restore that FAILS says so, names what is still staged and "
          "keeps the refusal it was restoring for - 'the index is as you left "
          "it' over an index that is not is the false clean sheet: %r" % (said,),
          said.startswith("boom - ") and "could NOT be put back" in said
          and "x.py" in said and M.INDEX_RESTORED not in said)

    # AN UNMERGED PATH AND AN INTENT-TO-ADD PATH, snapshotted and restored.
    repo = _repo(tmp, "conflict")
    _write(os.path.join(repo, "keep", "a.txt"), "stashed\n")
    _git(repo, "stash", "-q")
    _write(os.path.join(repo, "keep", "a.txt"), "other\n")
    _git(repo, "commit", "-q", "-am", "other")
    subprocess.run(["git", "-C", repo, "stash", "pop", "-q"],
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    _write(os.path.join(repo, "keep", "ita.txt"), "intent\n")
    _git(repo, "add", "-N", "--", "keep/ita.txt")
    paths = ["keep/a.txt", "keep/ita.txt"]
    found = _git(repo, "ls-files", "-s", "--", *paths)
    found_status = _git(repo, "status", "--porcelain=v2", "--", "keep/ita.txt")
    snap, why = M.snapshot(repo, paths)
    _write(os.path.join(repo, "keep", "a.txt"), "resolved\n")
    staged = M.stage(repo, paths, {"keep/a.txt": M.IN_INDEX,
                                   "keep/ita.txt": M.IN_INDEX})
    moved = _git(repo, "ls-files", "-s", "--", *paths)
    why_back = M.restore(repo, snap, paths)
    check("sc18 an index holding a CONFLICT is snapshotted and put back stage by "
          "stage - `git write-tree` refuses an unmerged index outright, so a "
          "snapshot built on it would refuse every commit made mid-conflict: "
          "%r / %r" % (why, why_back),
          why == "" and staged == "" and moved != found and why_back == ""
          and _git(repo, "ls-files", "-s", "--", *paths) == found
          and found.count("keep/a.txt") == 3)
    check("sc19 ...and an INTENT-TO-ADD path comes back intent-to-add rather "
          "than as a staged empty file, which `ls-files -s` alone cannot tell "
          "apart: %r" % (_git(repo, "status", "--porcelain=v2", "--",
                              "keep/ita.txt"),),
          found_status.startswith("1 .A ")
          and _git(repo, "status", "--porcelain=v2", "--",
                   "keep/ita.txt") == found_status)
    _review2_cases(check, tmp)


def _review2_cases(check, tmp):
    # AN IGNORED DIRECTORY, DECLARED WHOLE, HOLDING A TRACKED FILE.
    repo = _repo(tmp, "ignored-dir")
    _write(os.path.join(repo, "gen", "a.txt"), "v1\n")
    _write(os.path.join(repo, ".gitignore"), "gen\n")
    _git(repo, "add", "--", ".gitignore")
    _git(repo, "add", "-f", "--", "gen/a.txt")
    _git(repo, "commit", "-q", "-m", "tracked under an ignored dir")
    _write(os.path.join(repo, "gen", "a.txt"), "v2\n")
    _write(os.path.join(repo, "gen", "new.txt"), "untracked\n")
    kinds = M.classify(repo, [("gen", True)])
    done = M.stage_and_commit(repo, ["gen"], kinds, ["x"], lambda f: "foreign")
    shown = _git(repo, "show", "--name-only", "--pretty=format:", "HEAD").split()
    check("sc20 a directory git ignores AS A WHOLE, holding a tracked edited "
          "file, stages that file - `check-ignore` does not report the "
          "directory and `git add -- gen` refuses it - and its untracked "
          "member stays out, never forced: %r / %r" % (kinds, done),
          kinds == {"gen": M.TRACKED_DIR}
          and done["committed"] and not done["refused"] and shown == ["gen/a.txt"]
          and _git(repo, "ls-files", "--", "gen/new.txt").strip() == "")

    # THE KEPT-DELETION COMMIT, BUILT IN A TEMPORARY INDEX.
    repo = _repo(tmp, "kept-deletion")
    _write(os.path.join(repo, "f.cfg"), "cfg\n")
    _git(repo, "add", "--", "f.cfg")
    _git(repo, "commit", "-q", "-m", "cfg")
    _git(repo, "rm", "-q", "--cached", "--", "f.cfg")
    head = _git(repo, "rev-parse", "HEAD").strip()
    # A path somebody else staged in the meantime, which nothing allows.
    _write(os.path.join(repo, "keep", "b.txt"), "sibling\n")
    _git(repo, "add", "--", "keep/b.txt")
    sha, why = M.commit_from_index(repo, ["f.cfg"], ["drop f.cfg"], head)
    shown = _git(repo, "show", "--name-status", "--pretty=format:",
                 "HEAD").split("\n")
    check("sc21 a commit made from the index for a kept deletion carries EXACTLY "
          "the allow-list - a path a sibling staged meanwhile does not ride "
          "along, and stays staged for its owner: %r / %r" % (why, shown),
          why == "" and sha and [ln for ln in shown if ln.strip()]
          == ["D\tf.cfg"]
          and "keep/b.txt" in _git(repo, "diff", "--cached", "--name-only"))
    # The sibling's own commit moves HEAD to a tree the stale one does not
    # hold, so a commit built on the stale HEAD would undo it.
    _git(repo, "commit", "-q", "-m", "sibling", "--", "keep/b.txt")
    moved = _git(repo, "rev-parse", "HEAD").strip()
    sha2, why2 = M.commit_from_index(repo, ["f.cfg"], ["again"], head)
    check("sc22 ...and it refuses BEFORE committing when HEAD is no longer the "
          "HEAD it read - a commit built from the stale tree would undo the "
          "commits that moved it: %r" % (why2,),
          sha2 == "" and "before the commit" in why2
          and _git(repo, "rev-parse", "HEAD").strip() == moved)

    # A COMMIT LANDING BETWEEN THE CHECK AND THE COMMIT. Simulated at the one
    # moment it can happen: the runner makes a sibling commit just before it
    # hands `git commit` on.
    repo = _repo(tmp, "moved-head")
    _write(os.path.join(repo, "f.cfg"), "cfg\n")
    _git(repo, "add", "--", "f.cfg")
    _git(repo, "commit", "-q", "-m", "cfg")
    _git(repo, "rm", "-q", "--cached", "--", "f.cfg")
    head = _git(repo, "rev-parse", "HEAD").strip()
    real_run = M.run_git
    sibling = {}

    def _racing(git_root, args, **kwargs):
        if list(args[:1]) == ["commit"] and not sibling:
            tree = _git(repo, "rev-parse", "HEAD^{tree}").strip()
            sibling["sha"] = _git(repo, "commit-tree", tree, "-p", head,
                                  "-m", "sibling").strip()
            _git(repo, "update-ref", "HEAD", sibling["sha"], head)
        return real_run(git_root, args, **kwargs)
    M.run_git = _racing
    try:
        sha, why = M.commit_from_index(repo, ["f.cfg"], ["drop f.cfg"], head)
    finally:
        M.run_git = real_run
    check("sc24 a commit made on a HEAD that moved after the check is REPORTED - "
          "its SHA, the HEAD it landed on and the HEAD read before staging all "
          "named - and nothing is reset: %r" % (why,),
          sha and why and sibling.get("sha") in why and head in why
          and sha in why
          and _git(repo, "rev-parse", "HEAD").strip() == sha)

    # A SHA-256 REPOSITORY.
    repo = os.path.join(tmp, "sha256")
    os.makedirs(repo)
    made = subprocess.run(["git", "-C", repo, "init", "-q",
                           "--object-format=sha256"],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if made.returncode != 0:
        _harness.skip(check, "sc23 an index restore in a SHA-256 repository",
                      "this git cannot create a sha256 repository",
                      made.returncode != 0)
        return
    _git(repo, "config", "user.email", "fixture@example.com")
    _git(repo, "config", "user.name", "Fixture")
    _write(os.path.join(repo, "a.txt"), "a\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    found = _git(repo, "ls-files", "-s")
    snap, why = M.snapshot(repo, ["a.txt", "b.txt"])
    _write(os.path.join(repo, "a.txt"), "changed\n")
    _write(os.path.join(repo, "b.txt"), "new\n")
    _git(repo, "add", "--", "a.txt", "b.txt")
    why_back = M.restore(repo, snap, ["a.txt", "b.txt"])
    check("sc23 an index in a SHA-256 repository is put back too - the removal "
          "line's zero id is as long as the repository's object ids, and a "
          "sha1-length one is 'malformed index info' there: %r" % (why_back,),
          why == "" and why_back == "" and _git(repo, "ls-files", "-s") == found)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__scoped_commit.py --selftest\n")
    raise SystemExit(2)
