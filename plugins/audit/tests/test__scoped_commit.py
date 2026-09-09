#!/usr/bin/env python3
"""
The cases for `_scoped_commit.py` — what two committing commands share.

WHAT THIS FILE IS ABOUT. `commit-audit-state.py` and `commit-manifest-index.py`
each stage a fixed allow-list and refuse everything else, and the parts that
decide "refuse" are here rather than in either of them. The suites beside those
two commands prove each verb end to end; this one proves the shared parts in both
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


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__scoped_commit.py --selftest\n")
    raise SystemExit(2)
