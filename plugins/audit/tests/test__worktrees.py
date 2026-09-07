#!/usr/bin/env python3
"""
The cases for `_worktrees.py` — what git lists, whose phase it is, and what may go.

WHAT IS PINNED, and why each one is here rather than trusted:

- **The parser fixture is CAPTURED OUTPUT, not hand-written.** `PORCELAIN` below is
  the byte output of `git worktree list --porcelain` from a probe repository built to
  hold all five record shapes at once. A fixture written by the same hand as the
  parser agrees with the parser by construction and proves nothing about git.
- **`locked` with a reason and `locked` bare are both pinned**, because git prints
  both and an implementation that reads the reason as the flag passes on the first
  and fails on the second — and a locked worktree reading as unlocked is one a sweep
  would try to remove.
- **A `prunable` record still holds its branch.** Measured: git refuses `branch -d`
  AND `fetch` for a branch whose worktree directory was deleted by hand. A parser
  that frees it produces a plan git rejects with an error naming a path that no
  longer exists.
- **`same_tree` is driven through an INJECTED resolver.** The realpath-vs-abspath bug
  is invisible on ubuntu and live on macOS, so a case that used the real filesystem
  would be green in CI on the broken version. The injection is what makes it fire
  everywhere.
- **The three-answer family, with the could-not-ask row written out.** `merged_into` must
  answer UNKNOWN for a ref that does not resolve. `code == 0` — the shape live in
  `_doctor_policy.check_branch_naming` today — turns that into a definite
  "not contained", which is an accusation nobody can act on.
- **`CONTAINED` is a substring of `NOT_CONTAINED`, and one case says so.** A caller
  testing membership rather than equality would read every refusal as an approval.
  The hazard is pinned so the constants cannot be renamed into a trap.
- **The cleanup ORDER, asserted as an index comparison.** Both steps being present
  passes on the order git rejects; only the comparison fails on it.
- **Branch deletion gated on `contained`, never on git.** Measured: `git branch -d`
  grades against HEAD and deletes a branch that never reached its declared parent,
  exit 0. The case that would go red if this delegated to git.
- **The empty sweep and the all-clean sweep, in BOTH directions.** One of the two
  looks vacuous and is the only case that fails when the empty branch becomes
  unconditional.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import io
import json
import os
import shutil
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _worktrees as M                             # noqa: E402

# Captured from a probe repository holding every shape at once: the main worktree, a
# detached one, a locked one WITH a reason, a locked one WITHOUT, and a prunable one.
# Reproduce with `git worktree list --porcelain` after `git worktree add --detach`,
# `git worktree lock --reason ...`, and deleting one worktree directory by hand.
PORCELAIN = (
    "worktree /private/tmp/probe4/repo\n"
    "HEAD 62293d274ffcfeffbb2876848c1214a2bdf8f861\n"
    "branch refs/heads/main\n"
    "\n"
    "worktree /private/tmp/probe4/wt-detached\n"
    "HEAD 62293d274ffcfeffbb2876848c1214a2bdf8f861\n"
    "detached\n"
    "\n"
    "worktree /private/tmp/probe4/wt-locked\n"
    "HEAD 62293d274ffcfeffbb2876848c1214a2bdf8f861\n"
    "branch refs/heads/feature/locked\n"
    "locked phase P3 is mid-run; do not reap\n"
    "\n"
    "worktree /private/tmp/probe4/wt-lockednoreason\n"
    "HEAD 62293d274ffcfeffbb2876848c1214a2bdf8f861\n"
    "branch refs/heads/feature/lockednr\n"
    "locked\n"
    "\n"
    "worktree /private/tmp/probe4/wt-prunable\n"
    "HEAD 62293d274ffcfeffbb2876848c1214a2bdf8f861\n"
    "branch refs/heads/feature/prunable\n"
    "prunable gitdir file points to non-existent location\n"
)

# A bare repository's record carries NEITHER a HEAD nor a branch (captured).
BARE = "worktree /private/tmp/probe4/bare.git\nbare\n"

# A fresh repository's worktree: forty zeros, which is not a commit (captured).
UNBORN = ("worktree /private/tmp/probe5/empty\n"
          "HEAD 0000000000000000000000000000000000000000\n"
          "branch refs/heads/main\n")

# The path is printed RAW — git does not quote or escape it. The value is chosen so
# the `line.split()` version yields "/private/tmp/probe4/wt", a path that exists
# nowhere, rather than a merely different string.
SPACED = ("worktree /private/tmp/probe4/wt with space\n"
          "HEAD 62293d274ffcfeffbb2876848c1214a2bdf8f861\n"
          "branch refs/heads/feature/spaced\n")


def _run(table):
    """A fake git. `table` maps the first two argv words to (code, stdout, stderr),
    so a case drives the 128 and the could-not-run branches a fixture cannot reach."""
    def run(git_root, args, timeout=None):
        key = " ".join(args[:2])
        return table.get(key, table.get("*", (0, "", "")))
    return run


def _trees(text=PORCELAIN):
    return M.parse_list(text)


# The two preconditions that authorise a deletion, satisfied. They are WRAPPERS and
# not defaults in the product: `cleanup_plan` and `sweep_plan` fail CLOSED, so a case
# that forgot them would refuse rather than reap and would pass for the wrong reason
# - and every case below is about what happens once permission exists. The cases that
# WITHHOLD permission call the real functions directly, which is what keeps these
# wrappers from quietly becoming the product's behaviour.
OWNED_OK = {"ok": True, "why": "fixture: the plugin created this worktree"}
SETTLED_OK = {"ok": True, "why": "fixture: signed off, no open task, mergedAt set"}


def _cp(*a, **kw):
    kw.setdefault("owned", OWNED_OK)
    kw.setdefault("settled", SETTLED_OK)
    # ...and where the caller is standing, for the same reason: these three are
    # PRECONDITIONS that now all refuse when unanswered, so a case about a different
    # refusal has to satisfy them or it proves nothing about the one it names. `s7`
    # is the case that asserts the absent answer refuses.
    kw.setdefault("cwd_tree", M.CWD_OUTSIDE)
    return M.cleanup_plan(*a, **kw)


def _sp(trees, wanted, parents, contained, dirty, **kw):
    kw.setdefault("owned_by_path",
                  dict((r.get("path"), OWNED_OK) for r in trees or []))
    kw.setdefault("settled_by_branch",
                  dict((b, SETTLED_OK) for b in (wanted or {})))
    kw.setdefault("cwd_tree", M.CWD_OUTSIDE)
    return M.sweep_plan(trees, wanted, parents, contained, dirty, **kw)


def _cases(check):
    trees = _trees()

    # --- the parser, against captured bytes -----------------------------------
    check("p1 the captured five-shape sample parses to five records - COUNTED, "
          "because a fixture and a parser written by one hand agree by "
          "construction and a presence check would not notice a dropped record",
          len(trees) == 5, "%d record(s)" % (len(trees),))
    check("p2 a detached record has branch IS None, not '' - a falsy check would "
          "let a detached tree answer a lookup for a branch named ''",
          trees[1]["branch"] is None and trees[1]["detached"] is True,
          repr(trees[1]["branch"]))
    check("p3 `locked <reason>` AND bare `locked` both set locked=True - git "
          "prints both, and reading the reason as the flag misses half of them",
          trees[2]["locked"] is True and trees[3]["locked"] is True
          and trees[3]["lockReason"] == "",
          "with-reason=%r bare=%r" % (trees[2]["locked"], trees[3]["locked"]))
    check("p4 the locked reason survives as decoration, so a refusal can echo "
          "git's own words instead of inventing its own",
          trees[2]["lockReason"] == "phase P3 is mid-run; do not reap",
          repr(trees[2]["lockReason"]))
    check("p5 a PRUNABLE record keeps its branch - git still refuses `branch -d` "
          "and `fetch` for a branch whose worktree directory is gone, so a parser "
          "that frees it plans something git rejects",
          trees[4]["prunable"] is True
          and trees[4]["branch"] == "feature/prunable",
          repr((trees[4]["prunable"], trees[4]["branch"])))
    check("p6 only the FIRST record is the main worktree, which is what git's own "
          "ordering guarantees and what keeps the main tree out of every sweep",
          trees[0]["isMain"] is True
          and not any(r["isMain"] for r in trees[1:]),
          repr([r["isMain"] for r in trees]))
    check("p7 an all-zero HEAD is reported as UNBORN and never travels as a SHA - "
          "handing it to merge-base gives `fatal: Not a valid object name`",
          M.parse_list(UNBORN)[0]["unborn"] is True,
          repr(M.parse_list(UNBORN)[0]["head"]))
    check("p8 a bare record has no HEAD and no branch, and holds nothing",
          M.parse_list(BARE)[0]["bare"] is True
          and M.parse_list(BARE)[0]["head"] == ""
          and M.parse_list(BARE)[0]["branch"] is None,
          repr(M.parse_list(BARE)[0]))
    check("p9 a path containing a space parses WHOLE - git does not quote it, and "
          "the split() version yields a path that exists nowhere",
          M.parse_list(SPACED)[0]["path"] == "/private/tmp/probe4/wt with space",
          repr(M.parse_list(SPACED)[0]["path"]))
    check("p10 the -z spelling parses to the same records as the plain one, so "
          "the newline-safe form is not a second parser to keep in step",
          M.parse_list(PORCELAIN.replace("\n", "\0"), nul=True) == trees,
          "%d vs %d" % (len(M.parse_list(PORCELAIN.replace("\n", "\0"), nul=True)),
                        len(trees)))

    # --- the -z flag is younger than the command it modifies ------------------
    # `git worktree list --porcelain -z` arrives in git 2.36; Ubuntu 22.04 LTS ships
    # 2.34 and Debian 11 ships 2.30. Without a fallback every verb, sign-off's
    # cleanup, the panel's table and the doctor's residue row fail on a default LTS
    # install with `unknown switch 'z'` - which reads as a broken plugin.
    _z_calls = []

    def _old_git(_root, args, timeout=None):
        _z_calls.append(list(args))
        if "-z" in args:
            return (129, "", "error: unknown switch `z'\nusage: git worktree "
                            "list [-v | --porcelain]\n")
        return (0, PORCELAIN, "")

    _old = M.list_worktrees("/repo", run=_old_git)
    check("z1 a git that refuses -z is asked again WITHOUT it, rather than "
          "reporting the repository unreadable - the module already carries the "
          "newline parser and p10 pins the two equal, so the plain spelling is a "
          "real answer here and not a default invented to fill a gap",
          not _old["error"] and _old["trees"] == trees,
          "error=%r trees=%d" % (_old["error"], len(_old["trees"])))
    check("z2 ...and the basis SAYS which spelling answered, because newline "
          "safety in a path is what the fallback gives up and a reader deciding "
          "whether to trust a path needs to know which one they got",
          _old["basis"].endswith("--porcelain")
          and len(_z_calls) == 2 and "-z" in _z_calls[0]
          and "-z" not in _z_calls[1],
          "%r / %r" % (_old["basis"], _z_calls))

    def _broken_repo(_root, args, timeout=None):
        return (128, "", "fatal: not a git repository\n")

    _broken = M.list_worktrees("/repo", run=_broken_repo)
    check("z3 ...and a git that failed at the JOB is NOT retried as if it were "
          "old. 128 is spent on several things, so the retry is decided on the "
          "message naming the option rather than on an exit code",
          _broken["error"] and "not a git repository" in _broken["error"],
          repr(_broken["error"]))

    # --- parse_error: the three ways the list is not an answer ----------------
    check("e1 git that could not be run yields a sentence, not an empty list "
          "presented as 'no worktrees'",
          M.parse_error(None, "git is not on PATH", []) != "",
          repr(M.parse_error(None, "git is not on PATH", [])))
    check("e2 a non-zero exit yields git's own first line",
          "not a git repository" in M.parse_error(
              128, "fatal: not a git repository (or any of the parent "
                   "directories): .git\n", []),
          repr(M.parse_error(128, "fatal: not a git repository\n", [])))
    check("e3 exit 0 with NO records is an ERROR - the main worktree is always a "
          "record, so a healthy repository cannot list none, and reporting that "
          "as 'no worktrees' is the clean sheet this module exists to avoid",
          M.parse_error(0, "", []) != "", repr(M.parse_error(0, "", [])))
    check("e4 ...and the ALLOW case: a healthy list reports no error at all. "
          "This is the row that goes red if the guard above becomes unconditional",
          M.parse_error(0, "", trees) == "", repr(M.parse_error(0, "", trees)))

    # --- same_tree: realpath, proven through an injected resolver -------------
    def _fake_resolve(p):
        # IDEMPOTENT, which the one-line `replace` version is not: `/private/tmp/x`
        # contains `/tmp/` and would resolve to `/private/private/tmp/x`, so the
        # case would fail against a CORRECT same_tree. A fixture that lies about
        # the platform is worse than no fixture, because the red it produces sends
        # the reader to the wrong file.
        return "/private" + p if p.startswith("/tmp/") else p

    check("i1 two spellings of one directory compare EQUAL under a resolver - the "
          "abspath version answers 'different' for one directory on macOS, where "
          "/tmp and every mkdtemp() are symlinks, and is right on ubuntu. The "
          "injection is what makes this case fire on both",
          M.same_tree("/tmp/x/repo", "/private/tmp/x/repo",
                      resolve=_fake_resolve) is True,
          "resolver applied")
    check("i2 ...and two genuinely different directories still compare unequal, "
          "so the resolver is not collapsing everything to True",
          M.same_tree("/tmp/x/repo", "/tmp/y/repo",
                      resolve=_fake_resolve) is False,
          "distinct paths stay distinct")
    check("i3 an empty path is never 'the same tree' as anything - a caller with "
          "no cwd must not match the first record",
          M.same_tree("", "/private/tmp/x") is False, "empty compares False")

    # --- holder_of / standing_in / phase_trees --------------------------------
    check("h1 the holder of a branch is found by name, and the basis names the "
          "path - a branch whose holder cannot be explained is a refusal nobody "
          "can act on",
          M.holder_of(trees, "feature/locked")["tree"]["path"]
          == "/private/tmp/probe4/wt-locked",
          M.holder_of(trees, "feature/locked")["basis"])
    check("h2 a PRUNABLE record is still returned as the holder - treating it as "
          "free is what produces a plan git rejects",
          M.holder_of(trees, "feature/prunable")["tree"] is not None,
          repr(M.holder_of(trees, "feature/prunable")["tree"] is not None))
    check("h3 a branch nothing holds returns tree=None WITH a basis saying so, "
          "rather than a bare None a caller has to interpret",
          M.holder_of(trees, "feature/nobody")["tree"] is None
          and M.holder_of(trees, "feature/nobody")["basis"] != "",
          M.holder_of(trees, "feature/nobody")["basis"])
    check("s1 standing_in finds the worktree the process is inside - git does NOT "
          "ask this, and removes the directory the caller is sitting in silently "
          "with exit 0, so this is the only place it can be asked",
          M.standing_in(trees, "/private/tmp/probe4/wt-locked")["path"]
          == "/private/tmp/probe4/wt-locked",
          "found")
    check("s2 ...and a cwd outside every worktree yields None rather than the "
          "first record",
          M.standing_in(trees, "/somewhere/else") is None, "None")

    split = M.phase_trees(trees, {"feature/locked": "P3"})
    check("f1 the main worktree is never a phase tree and never a stranger - it "
          "is not a linked worktree and is out of every sweep by construction",
          all(r["path"] != "/private/tmp/probe4/repo"
              for r in split["named"] + split["strangers"]),
          "%d named, %d strangers" % (len(split["named"]),
                                      len(split["strangers"])))
    check("f2 a worktree the plan does not name is REPORTED as a stranger, not "
          "filtered away - a silent skip over somebody's unrelated worktree is "
          "indistinguishable from not having looked",
          len(split["strangers"]) == 3,
          repr([r["branch"] for r in split["strangers"]]))
    check("f3 a named worktree carries its phase id, so a report can say whose "
          "it is instead of printing a path",
          split["named"][0]["phaseId"] == "P3", repr(split["named"][0]["phaseId"]))

    # --- merged_into: three answers, and the 128 that must not be answer two ---
    check("m1 exit 0 is CONTAINED",
          M.merged_into("r", "b", "p", run=_run(
              {"merge-base --is-ancestor": (0, "", "")}))["answer"] == M.CONTAINED,
          "0 -> contained")
    check("m2 exit 1 is NOT_CONTAINED",
          M.merged_into("r", "b", "p", run=_run(
              {"merge-base --is-ancestor": (1, "", "")}))["answer"]
          == M.NOT_CONTAINED, "1 -> not-contained")
    check("m3 exit 128 - a parentBranch this clone does not have - is UNKNOWN and "
          "NOT 'not contained'. `merged = (returncode == 0)` is the shape live in "
          "_doctor_policy today, and it prints a definite accusation for a "
          "question git refused to answer",
          M.merged_into("r", "b", "no/such", run=_run(
              {"merge-base --is-ancestor":
               (128, "", "fatal: Not a valid object name no/such\n")}))["answer"]
          == M.UNKNOWN,
          M.merged_into("r", "b", "no/such", run=_run(
              {"merge-base --is-ancestor": (128, "", "fatal: bad\n")}))["answer"])
    check("m4 ...and the UNKNOWN answer is never CONTAINED either - the failure "
          "mode in the other direction is a merge skipped as 'already landed'",
          M.merged_into("r", "b", "p", run=_run(
              {"merge-base --is-ancestor": (128, "", "fatal: bad\n")}))["answer"]
          != M.CONTAINED, "not silently contained")
    check("m5 a runner that RAISES is UNKNOWN, not an answer - git missing from "
          "PATH must not read as a verdict",
          M.merged_into("r", "b", "p", run=_run(
              {"merge-base --is-ancestor": (None, "", "git is not on PATH")}
          ))["answer"] == M.UNKNOWN, "could not be asked")
    check("m6 NOT_CONTAINED carries the squash sentence - is-ancestor answers 1 "
          "for work that DID land via a squash merge, so a bare 'never merged' "
          "would be false about a real and common workflow",
          "squash" in M.merged_into("r", "b", "p", run=_run(
              {"merge-base --is-ancestor": (1, "", "")}))["detail"],
          M.merged_into("r", "b", "p", run=_run(
              {"merge-base --is-ancestor": (1, "", "")}))["detail"][:60])
    check("m7 CONTAINED is a SUBSTRING of NOT_CONTAINED, and this row exists so "
          "the constants cannot be renamed into a trap: a caller testing "
          "membership rather than equality reads every refusal as an approval",
          M.CONTAINED in M.NOT_CONTAINED and M.CONTAINED != M.NOT_CONTAINED,
          "%r in %r" % (M.CONTAINED, M.NOT_CONTAINED))

    # --- ref_exists: the precondition the no-checkout merge cannot do without --
    check("r1 a resolving ref is True WITH its sha",
          M.ref_exists("r", "dev", run=_run(
              {"rev-parse --verify": (0, "abc123\n", "")}))["exists"] is True,
          "True")
    check("r2 exit 1 is False - the ref is absent, which is a real answer",
          M.ref_exists("r", "dev", run=_run(
              {"rev-parse --verify": (1, "", "")}))["exists"] is False, "False")
    check("r3 anything else is None, never False - `git fetch . <b>:<p>` CREATES "
          "the target and exits 0, so a could-not-ask rendered as 'absent' would "
          "let a typo'd parentBranch become a new branch and a success report",
          M.ref_exists("r", "dev", run=_run(
              {"rev-parse --verify": (128, "", "fatal: bad\n")}))["exists"] is None,
          "None")

    # --- dirtiness ------------------------------------------------------------
    check("d1 status lines mean dirty, and the NAMES come back - the operator has "
          "to read them before anything irreversible happens",
          M.dirtiness("/w", run=_run({"status --porcelain": (
              0, " M a.txt\n?? b.txt\n", "")}))["lines"] == [" M a.txt", "?? b.txt"],
          repr(M.dirtiness("/w", run=_run({"status --porcelain": (
              0, " M a.txt\n?? b.txt\n", "")}))["lines"]))
    check("d2 no status lines mean clean - the allow case, which goes red if the "
          "predicate is tightened until everything reads as dirty",
          M.dirtiness("/w", run=_run({"status --porcelain": (0, "", "")}))["dirty"]
          is False, "clean")
    check("d3 a status git would not give is None and NOT False - 'clean' and "
          "'unreadable' are the two answers a boolean renders identically, and "
          "one of them leads to a worktree removal nobody sanctioned",
          M.dirtiness("/w", run=_run({"status --porcelain": (
              128, "", "fatal: not a git repository\n")}))["dirty"] is None,
          "None")

    # --- merge_plan -----------------------------------------------------------
    p_held = M.merge_plan(trees, "feature/x", "feature/locked", M.NOT_CONTAINED,
                          True, False)
    check("g1 a parent held by another worktree is merged IN THAT WORKTREE - `git "
          "switch` cannot reach it: `fatal: '<p>' is already used by worktree at "
          "'<path>'`, exit 128",
          p_held["mode"] == "in-parent-worktree"
          and p_held["argv"][:2] == ["-C", "/private/tmp/probe4/wt-locked"],
          repr(p_held["argv"]))
    p_free = M.merge_plan(trees, "feature/x", "dev", M.NOT_CONTAINED, True, False)
    check("g2 a parent held nowhere is fast-forwarded WITHOUT a checkout, and the "
          "refspec carries NO leading '+' - the plus is the force spelling, and "
          "git's own ff check is the whole safety of this path",
          p_free["mode"] == "no-checkout"
          and p_free["argv"] == ["fetch", ".", "feature/x:refs/heads/dev"],
          repr(p_free["argv"]))
    check("g3 ...and the held case is NOT planned as no-checkout. Second "
          "direction: git exits 128 either way, so this case exists to fail "
          "BEFORE the write and to fail when someone simplifies the branch away",
          p_held["mode"] != "no-checkout", p_held["mode"])
    check("g4 an ALREADY CONTAINED branch plans zero git writes. Asked before "
          "either write path because the fetch path CANNOT SEE this state: it "
          "reports an already-landed phase as `! [rejected] (non-fast-forward)` "
          "exit 1, byte-identical to a real divergence, while merge --ff-only "
          "calls it `Already up to date.` exit 0",
          M.merge_plan(trees, "feature/x", "dev", M.CONTAINED, True, False)["argv"]
          == [],
          M.merge_plan(trees, "feature/x", "dev", M.CONTAINED, True,
                       False)["mode"])
    check("g5 an UNKNOWN containment refuses - a could-not-ask is never a merge, "
          "and it is never a 'not merged' either",
          M.merge_plan(trees, "feature/x", "dev", M.UNKNOWN, True,
                       False)["mode"] == "refuse",
          "refuse")
    p_absent = M.merge_plan(trees, "feature/x", "typo", M.NOT_CONTAINED, False,
                            False)
    check("g6 an absent parent ref REFUSES rather than fetching - measured, the "
          "fetch would create `typo`, print `* [new branch]` and exit 0, so the "
          "phase would report as merged into a branch that command invented",
          p_absent["mode"] == "refuse" and p_absent["argv"] == [],
          p_absent["refusal"]["why"])
    p_dirty = M.merge_plan(trees, "feature/x", "feature/locked", M.NOT_CONTAINED,
                           True, True, [" M a.txt"])
    check("g7 a dirty parent worktree refuses, AND the refusal says the rule is "
          "the plugin's - measured, git fast-forwards over unrelated dirt and "
          "exits 0, so a message implying git refused is one the operator "
          "disproves in a single command, and a guard disproved once is routed "
          "around",
          p_dirty["mode"] == "refuse"
          and "not git" in p_dirty["refusal"]["remedy"],
          p_dirty["refusal"]["remedy"][:70])
    check("g8 ...and a CLEAN parent worktree produces no refusal at all - the "
          "allow case for g7",
          p_held["refusal"] is None, repr(p_held["refusal"]))
    check("g9 no plan, in any mode, ever contains `switch` - moving an operator's "
          "HEAD is a side effect no script takes on its own",
          all("switch" not in (pl["argv"] or [])
              for pl in (p_held, p_free, p_absent, p_dirty)),
          "no switch planned")

    # --- cleanup_plan ---------------------------------------------------------
    clean = _cp(trees, "feature/locked", "dev", M.CONTAINED, False,
                           want_worktree=True, want_branch=True)
    check("c1 a LOCKED worktree is not removed, and git's own reason is echoed "
          "rather than replaced",
          not any(s["action"] == "worktree-remove" for s in clean["steps"])
          and any("mid-run" in b["why"] for b in clean["blocked"]),
          repr([b["why"][:50] for b in clean["blocked"]]))

    open_trees = M.parse_list(
        "worktree /main\nHEAD abc\nbranch refs/heads/dev\n\n"
        "worktree /wt-p2\nHEAD def\nbranch refs/heads/feature/p2\n")
    both = _cp(open_trees, "feature/p2", "dev", M.CONTAINED, False,
                          want_worktree=True, want_branch=True)
    order = [s["action"] for s in both["steps"]]
    check("c2 worktree removal comes STRICTLY BEFORE branch deletion - asserted "
          "as an index comparison, because 'both are present' passes on exactly "
          "the order git rejects with `cannot delete branch '<b>' used by "
          "worktree at '<path>'`",
          "worktree-remove" in order and "branch-delete" in order
          and order.index("worktree-remove") < order.index("branch-delete"),
          repr(order))
    check("c3 a DIRTY worktree is not removed, the branch is not deleted either, "
          "and the refusal warns that removal also destroys IGNORED files - a "
          ".env under that path goes with it and git status never mentioned it",
          not _cp(open_trees, "feature/p2", "dev", M.CONTAINED, True,
                             [" M x.py"], want_worktree=True,
                             want_branch=True)["steps"]
          and any("IGNORED" in b["remedy"] for b in _cp(
              open_trees, "feature/p2", "dev", M.CONTAINED, True, [" M x.py"],
              want_worktree=True, want_branch=True)["blocked"]),
          "refused, ignored files named")
    check("c4 a worktree whose dirtiness could NOT be read is kept, not removed - "
          "an unanswered question is not a clean tree",
          not _cp(open_trees, "feature/p2", "dev", M.CONTAINED, None,
                             want_worktree=True, want_branch=False)["steps"],
          "kept")
    not_cont = _cp(open_trees, "feature/p2", "dev", M.NOT_CONTAINED,
                              False, want_worktree=False, want_branch=True)
    check("c5 a branch NOT contained in its parent is never deleted, and the "
          "refusal says why git would not have stopped it: measured, `git branch "
          "-d` grades against HEAD and deleted a branch whose declared parent was "
          "develop while it had only reached main, exit 0",
          not not_cont["steps"] and any("HEAD" in b["remedy"]
                                        for b in not_cont["blocked"]),
          not_cont["blocked"][0]["remedy"][:70])
    check("c6 ...and the ALLOW case: a contained branch with nothing holding it "
          "IS deleted. This is the row that goes red if the gate above is "
          "tightened until it refuses everything",
          any(s["action"] == "branch-delete" for s in _cp(
              [], "feature/p2", "dev", M.CONTAINED, False,
              want_worktree=False, want_branch=True)["steps"]),
          "deleted")
    standing = _cp(open_trees, "feature/p2", "dev", M.CONTAINED, False,
                              cwd_tree="/wt-p2", want_worktree=True,
                              want_branch=False)
    check("c7 the worktree this process is STANDING IN is refused - git does not "
          "ask this at all: measured, it removes the caller's own directory "
          "silently, exit 0, with empty stdout and empty stderr",
          not standing["steps"]
          and any("standing inside" in b["why"] for b in standing["blocked"]),
          "refused")
    check("c8 the MAIN worktree is never removed, whatever else is true of it",
          not any(s["action"] == "worktree-remove" for s in _cp(
              open_trees, "dev", "main", M.CONTAINED, False,
              want_worktree=True, want_branch=False)["steps"]),
          "main spared")
    check("c9 a verb the caller did not ask for produces no step - cleanup is "
          "never implied by a successful merge",
          _cp(open_trees, "feature/p2", "dev", M.CONTAINED, False,
                         want_worktree=False, want_branch=False)["steps"] == [],
          "nothing asked, nothing planned")

    # --- provenance and settlement: whose worktree, and are we finished -------
    # THE THREE CLASSES, and only the third may be reaped: somebody else's worktree,
    # ours with the phase still running, ours and finished. Branch name and merge
    # state cannot tell the first from the third, which is why these are separate
    # questions rather than a stricter reading of the ones above.
    foreign = M.cleanup_plan(open_trees, "feature/p2", "dev", M.CONTAINED, False,
                             want_worktree=True, want_branch=False,
                             owned={"ok": False, "why": "no marker in its admin dir"},
                             settled=SETTLED_OK)
    check("o1 a worktree the plugin did not create is NEVER removed, however "
          "cleanly its branch landed - a colleague's worktree and ours are "
          "indistinguishable by branch name and merge state, and deleting theirs "
          "destroys a working copy nobody asked us to touch",
          not foreign["steps"] and any("did not create" in b["remedy"]
                                       or "only removes worktrees it started"
                                       in b["remedy"] for b in foreign["blocked"]),
          foreign["blocked"][0]["why"][:70])
    # BOTH would refuse, so the ORDER is what this measures: a foreign worktree
    # whose branch also has not landed must be refused for being foreign. Told it is
    # a merge problem, the reader merges - and comes back to a refusal they cannot
    # act on, because the second reason was never the one that mattered.
    both_wrong = M.cleanup_plan(open_trees, "feature/p2", "dev", M.NOT_CONTAINED,
                                False, want_worktree=True, want_branch=False,
                                owned={"ok": False,
                                       "why": "no audit-worktree.json in its admin "
                                              "directory"},
                                settled=SETTLED_OK)
    check("o2 ...and provenance is asked BEFORE containment: when both would "
          "refuse, the reason reported is whose directory it is, not the state of "
          "the branch. Asserted as the FIRST reason and not as presence, because "
          "both are present and only the order tells the reader what to do",
          both_wrong["blocked"]
          and "admin" in both_wrong["blocked"][0]["why"]
          and "contained" not in both_wrong["blocked"][0]["why"],
          both_wrong["blocked"][0]["why"][:70])
    unfinished = M.cleanup_plan(open_trees, "feature/p2", "dev", M.CONTAINED,
                                False, want_worktree=True, want_branch=True,
                                owned=OWNED_OK,
                                settled={"ok": False,
                                         "why": "phase P2 is 'in_progress', not "
                                                "'done' - sign-off has not passed"})
    check("o3 OUR worktree with the phase still running is not reaped either - a "
          "branch can be contained in its parent while the phase is mid-flight, "
          "and 'the commits are safe' is not 'the plugin is finished'",
          not unfinished["steps"]
          and any("sign-off" in b["why"] for b in unfinished["blocked"]),
          unfinished["blocked"][0]["why"][:70])
    check("o4 ...and the BRANCH is not deleted on that path either, for the same "
          "reason - a merged branch of a running phase is still where the work is",
          not any(s["action"] == "branch-delete" for s in unfinished["steps"]),
          repr([s["action"] for s in unfinished["steps"]]))
    # ISOLATED, with no worktree in the way. With one, the worktree half refuses
    # first and the branch half is never reached - so a `settled` that defaulted to
    # permission would survive every case above. This is the only shape that sees it.
    check("o4b the BRANCH half fails closed on its own: no worktree holds it, the "
          "branch is contained, and an unestablished `settled` still refuses. "
          "Isolated deliberately - with a worktree present the first half refuses "
          "and this gate is never asked",
          not M.cleanup_plan([], "feature/p2", "dev", M.CONTAINED, False,
                             want_worktree=False, want_branch=True)["steps"],
          "no settled -> no deletion")
    check("o4c ...and the ALLOW case for it, so o4b is not a gate that refuses "
          "everything",
          any(s["action"] == "branch-delete" for s in M.cleanup_plan(
              [], "feature/p2", "dev", M.CONTAINED, False,
              want_worktree=False, want_branch=True,
              settled=SETTLED_OK)["steps"]),
          "settled -> deleted")
    check("o5 FAIL CLOSED: omitting the preconditions entirely refuses, rather "
          "than reaping by omission. Every existing call site would otherwise have "
          "gained permission the day these were added, which is exactly the "
          "accident they exist to prevent",
          not M.cleanup_plan(open_trees, "feature/p2", "dev", M.CONTAINED, False,
                             want_worktree=True, want_branch=True)["steps"],
          "no owned/settled -> nothing planned")

    # `phase_settled`: three marks, and the FIRST missing one is the reason.
    TERM = ("done", "cancelled")
    done_phase = {"id": "P2", "status": "done", "mergedAt": "2026-01-01T00:00:00Z",
                  "tasks": [{"id": "P2.1", "status": "done"},
                            {"id": "P2.2", "status": "cancelled"}]}
    check("q1 a phase that signed off, has every task terminal and records "
          "mergedAt is SETTLED - the allow case, without which every refusal "
          "below could be a predicate that refuses everything",
          M.phase_settled(done_phase, TERM)["settled"] is True,
          M.phase_settled(done_phase, TERM)["why"][:60])
    check("q2 a CANCELLED task counts as finished - it is a terminal status, and "
          "reading it as open would strand every phase that dropped one task",
          M.phase_settled(done_phase, TERM)["settled"] is True,
          "cancelled is terminal")
    check("q3 a phase that has not signed off is not settled, whatever else is "
          "true of it",
          M.phase_settled(dict(done_phase, status="in_progress"),
                          TERM)["settled"] is False,
          M.phase_settled(dict(done_phase, status="in_progress"), TERM)["why"][:60])
    open_task = dict(done_phase,
                     tasks=[{"id": "P2.1", "status": "done"},
                            {"id": "P2.2", "status": "in_progress"}])
    check("q4 a phase marked done while a task is still open is not settled, AND "
          "the task is named - the reader has to know which one to look at",
          M.phase_settled(open_task, TERM)["settled"] is False
          and "P2.2" in M.phase_settled(open_task, TERM)["why"],
          M.phase_settled(open_task, TERM)["why"][:70])
    check("q5 a phase with no mergedAt is not settled - nothing says the merge "
          "happened, and 'the branch is contained' is a different claim that a "
          "cherry-pick or an early merge can also make true",
          M.phase_settled(dict(done_phase, mergedAt=None),
                          TERM)["settled"] is False,
          M.phase_settled(dict(done_phase, mergedAt=None), TERM)["why"][:60])
    # F247. The filter that skipped a non-dict task removed it from the OPEN list
    # rather than refusing on it, so a `tasks` array of bare ids read as a phase
    # whose every task is terminal - and `settled` is one of the two PERMISSION
    # gates, not a report. The sweep does not revalidate the manifest, so a
    # half-written or hand-edited one reaches this directly.
    for _bad, _label in ((["P2.1", "P2.2"], "a list of bare ids"),
                         ({"P2.1": {"status": "done"}}, "an object, not an array"),
                         ([{"id": "P2.1", "status": "done"}, None], "a null task")):
        _got = M.phase_settled(dict(done_phase, tasks=_bad), TERM)
        check("q6 a `tasks` entry this cannot read REFUSES rather than counting as "
              "finished (%s) - every other unreadable input in this module refuses, "
              "and the old `why` asserted 'every task is terminal' about a list it "
              "never looked at" % (_label,),
              _got["settled"] is False and "could not be read" in _got["why"],
              repr(_got))

    # --- sweep_plan: the two do-nothing states, worded apart ------------------
    empty = _sp([], {}, {}, {}, {}, verbs=("removeWorktrees",))
    check("w1 a sweep with nothing to look at reports empty=True AND examined=0 - "
          "the field exists because 'there was no linked worktree' and 'every "
          "worktree was examined and all were healthy' are two states of the "
          "world that a falsy actions list renders identically",
          empty["empty"] is True and empty["examined"] == 0,
          "examined=%d empty=%r" % (empty["examined"], empty["empty"]))
    healthy = _sp(
        open_trees, {"feature/p2": "P2"}, {"feature/p2": "dev"},
        {"feature/p2": M.NOT_CONTAINED},
        {"/wt-p2": {"dirty": False, "lines": []}},
        verbs=("removeWorktrees", "deleteBranches"))
    check("w2 ...and the OTHER direction: a sweep that examined a worktree and "
          "found nothing to do reports empty=False. This is the row that looks "
          "vacuous and is the only one that fails when the empty branch becomes "
          "unconditional",
          healthy["empty"] is False and healthy["examined"] == 1
          and healthy["actions"] == [],
          "examined=%d actions=%d" % (healthy["examined"],
                                      len(healthy["actions"])))
    check("w3 every worktree left alone carries a REASON - a sweep that did "
          "nothing and printed only a number lets the reader infer health",
          healthy["kept"] and healthy["kept"][0]["reasons"],
          repr(healthy["kept"][0]["reasons"][0]["why"][:60]))
    ready = _sp(
        open_trees, {"feature/p2": "P2"}, {"feature/p2": "dev"},
        {"feature/p2": M.CONTAINED},
        {"/wt-p2": {"dirty": False, "lines": []}},
        verbs=("removeWorktrees", "deleteBranches"))
    check("w4 a contained, clean worktree IS swept - the allow case, without "
          "which every refusal above could be a sweep that refuses everything",
          len(ready["actions"]) == 1
          and [s["action"] for s in ready["actions"][0]["steps"]]
          == ["worktree-remove", "branch-delete"],
          repr([s["action"] for s in ready["actions"][0]["steps"]]))
    spared = _sp(
        open_trees, {"feature/p2": "P2"}, {"feature/p2": "dev"},
        {"feature/p2": M.CONTAINED},
        {"/wt-p2": {"dirty": True, "lines": ["?? .env"]}},
        verbs=("removeWorktrees", "deleteBranches"))
    check("w5 a CONTAINED branch whose worktree is DIRTY is spared and named - "
          "this is the case a one-axis sweep ('merged, therefore go') would have "
          "destroyed, and the one the 2026-08-26 hand-prune had to prove by hand",
          spared["actions"] == [] and spared["kept"][0]["dirtyLines"] == ["?? .env"],
          repr(spared["kept"][0]["dirtyLines"]))
    strangers = _sp(
        open_trees, {}, {}, {}, {}, verbs=("removeWorktrees", "deleteBranches"))
    check("w6 a worktree the plan does not name is never touched AND is reported "
          "- surviving without being named is a silent skip",
          strangers["actions"] == [] and len(strangers["strangers"]) == 1,
          repr([r["branch"] for r in strangers["strangers"]]))
    check("w7 a verb the caller did not name performs nothing, so 'sweep "
          "everything' is never inferred from having found something to do",
          _sp(open_trees, {"feature/p2": "P2"}, {"feature/p2": "dev"},
                       {"feature/p2": M.CONTAINED},
                       {"/wt-p2": {"dirty": False, "lines": []}},
                       verbs=())["actions"] == [],
          "no verbs, no actions")

    # --- F244: the plan must act on the record it MEASURED --------------------
    # `git worktree add --force <path> <branch>` legally puts two records on one
    # branch. The measurements are per RECORD (owned by path, dirty by path); a
    # cleanup that re-resolves by branch takes the first holder, so both safety
    # answers end up being about a directory that is not in the argv.
    twins = [{"path": "/main", "branch": "main", "isMain": True},
             {"path": "/a", "branch": "feature/p2"},     # stranger, dirty
             {"path": "/b", "branch": "feature/p2"}]     # ours, clean
    twin_plan = M.sweep_plan(
        twins, {"feature/p2": "P2"}, {"feature/p2": "dev"},
        {"feature/p2": M.CONTAINED},
        {"/a": {"dirty": True, "lines": ["?? work.py"]},
         "/b": {"dirty": False, "lines": []}},
        cwd_tree=M.CWD_OUTSIDE, verbs=("removeWorktrees", "deleteBranches"),
        owned_by_path={"/main": {"ok": False, "why": "the main worktree"},
                       "/a": {"ok": False, "why": "no marker - somebody else's"},
                       "/b": OWNED_OK},
        settled_by_branch={"feature/p2": SETTLED_OK})
    _removes = [s["argv"][2] for a in twin_plan["actions"] for s in a["steps"]
                if s["action"] == "worktree-remove"]
    check("w8 with two worktrees on ONE branch, every removal names the worktree "
          "whose provenance and cleanliness were measured - the plan kept /a as "
          "somebody else's and must not then remove it: %r" % (_removes,),
          "/a" not in _removes)
    check("w9 ...and the action row reports the path the argv actually removes. "
          "Two names for one act means the applied list, the CLI output and the "
          "journal all record a directory that still exists",
          all(s["argv"][2] == a["path"]
              for a in twin_plan["actions"] for s in a["steps"]
              if s["action"] == "worktree-remove"),
          repr([(a["path"], [s["argv"] for s in a["steps"]])
                for a in twin_plan["actions"]]))
    check("w10 ...and the branch is NOT deleted while another record still holds "
          "it - git refuses `cannot delete branch used by worktree`, and one of "
          "the two holders is a worktree this plan may never touch",
          not [s for a in twin_plan["actions"] for s in a["steps"]
               if s["action"] == "branch-delete"],
          repr([s["action"] for a in twin_plan["actions"] for s in a["steps"]]))

    # --- F245: standing-in is CONTAINMENT, and an unestablished cwd refuses ----
    nested = [{"path": "/x/repo-P1", "branch": "feature/p1"},
              {"path": "/x/repo-P1-old", "branch": "feature/old"}]
    check("s4 the caller is inside a worktree when it is inside a SUBDIRECTORY of "
          "it, not only when it is exactly at its root. One `cd src` used to turn "
          "the refusal into the deletion, and git removes that directory silently "
          "with exit 0",
          (M.standing_in(nested, "/x/repo-P1/src/deep", resolve=lambda p: p)
           or {}).get("path") == "/x/repo-P1",
          repr(M.standing_in(nested, "/x/repo-P1/src/deep", resolve=lambda p: p)))
    check("s5 ...and a sibling whose path merely STARTS WITH another's is not "
          "inside it - `/x/repo-P1-old` is its own worktree, and a prefix test "
          "without a separator boundary would call it a child",
          (M.standing_in(nested, "/x/repo-P1-old", resolve=lambda p: p)
           or {}).get("path") == "/x/repo-P1-old",
          repr(M.standing_in(nested, "/x/repo-P1-old", resolve=lambda p: p)))
    _deep = [{"path": "/x/repo", "branch": "main", "isMain": True},
             {"path": "/x/repo/worktrees/P1", "branch": "feature/p1"}]
    check("s6 ...and when the cwd is inside two records the INNERMOST wins, which "
          "is the one git resolves such a path to. A worktree nested under the "
          "main one is inside both",
          (M.standing_in(_deep, "/x/repo/worktrees/P1/src", resolve=lambda p: p)
           or {}).get("path") == "/x/repo/worktrees/P1",
          repr(M.standing_in(_deep, "/x/repo/worktrees/P1/src",
                             resolve=lambda p: p)))
    _unset = M.cleanup_plan(
        open_trees, "feature/p2", "dev", M.CONTAINED, False, [],
        owned=OWNED_OK, settled=SETTLED_OK)
    check("s7 FAIL CLOSED: a caller that did not establish where it is standing "
          "gets a refusal, not a removal. `owned` and `settled` already refuse on "
          "an absent answer; this was the one precondition where 'not measured' "
          "and 'measured, and outside every worktree' were the same value - and "
          "the panel passed the absent one literally",
          not [s for s in _unset["steps"] if s["action"] == "worktree-remove"]
          and any("where this process is standing" in b["why"]
                  for b in _unset["blocked"]),
          repr([b["why"][:70] for b in _unset["blocked"]]))
    # --- F246: the marker has to describe the work that is in the tree --------
    _mk = tempfile.mkdtemp()
    try:
        _adm = os.path.join(_mk, "admin")
        os.makedirs(_adm)
        with io.open(os.path.join(_adm, M.PROVENANCE_FILE), "w",
                     encoding="utf-8") as _fh:
            _fh.write(json.dumps({"createdBy": M.PROVENANCE_MARK,
                                  "phaseId": "P1", "branch": "feature/p1",
                                  "at": "2026-01-01T00:00:00Z"}))
        _fake_admin = lambda _p, run=None: _adm            # noqa: E731
        _saved, M.admin_dir = M.admin_dir, _fake_admin
        try:
            _same = M.read_provenance("/x/repo-P1", expect_branch="feature/p1")
            check("pv6 a marker written for this branch still answers ours=True - "
                  "without this the binding below is a rule that refuses "
                  "everything and proves nothing",
                  _same["ours"] is True, repr(_same["basis"][:60]))
            _moved = M.read_provenance("/x/repo-P1", expect_branch="feature/p2")
            check("pv7 ...and a marker written for ANOTHER branch does not "
                  "authorise this one. `createdBy` alone proved the plugin made A "
                  "worktree, never THIS one, so a `git switch` inside a phase "
                  "worktree handed P1's open directory to P2's settlement verdict",
                  _moved["ours"] is False
                  and "does not describe the work in it" in _moved["basis"],
                  repr(_moved["basis"][:110]))
            check("pv8 ...and the refusal names BOTH sides - the phase and branch "
                  "the marker was written for, and the branch found in the tree. "
                  "'not ours' would send the reader looking for a colleague who "
                  "does not exist",
                  "P1" in _moved["basis"] and "feature/p1" in _moved["basis"]
                  and "feature/p2" in _moved["basis"], repr(_moved["basis"]))
            _wide = M.read_provenance("/x/repo-P1")
            check("pv9 ...while the WIDE question - did we make this at all - is "
                  "still askable, because the panel's table reports provenance and "
                  "must not call a switched worktree a stranger",
                  _wide["ours"] is True, repr(_wide["ours"]))
        finally:
            M.admin_dir = _saved
    finally:
        shutil.rmtree(_mk, ignore_errors=True)

    _outside = M.cleanup_plan(
        open_trees, "feature/p2", "dev", M.CONTAINED, False, [],
        cwd_tree=M.CWD_OUTSIDE, owned=OWNED_OK, settled=SETTLED_OK)
    check("s8 ...and the caller that DID establish it, and is outside every "
          "worktree, still gets the removal - without this the refusal above is a "
          "guard that refuses everything and proves nothing",
          [s["action"] for s in _outside["steps"]] == ["worktree-remove",
                                                       "branch-delete"],
          repr([s["action"] for s in _outside["steps"]]))

    # --- F249: the deletion is guarded on where the branch points -------------
    # `git branch -d` grades from HEAD. On the no-checkout merge path the parent is
    # by construction checked out NOWHERE, so HEAD is never the parent - measured on
    # a real repository, a branch proven contained in `develop` is refused with
    # `error: the branch 'feature/p1' is not fully merged`, exit 1, after its
    # worktree has already gone. `update-ref -d <ref> <old>` is not `-D`: it deletes
    # only while the ref still points where we looked, so it refuses the one thing a
    # force delete would not.
    _guarded = M.cleanup_plan(
        open_trees, "feature/p2", "dev", M.CONTAINED, False, [],
        cwd_tree=M.CWD_OUTSIDE, owned=OWNED_OK, settled=SETTLED_OK,
        branch_sha="0123456789abcdef0123456789abcdef01234567")
    _del = [s for s in _guarded["steps"] if s["action"] == "branch-delete"]
    check("bd1 with the branch's sha known the deletion is guarded on it, rather "
          "than re-asking git a question about HEAD that the manifest never asked",
          _del and _del[0]["argv"] == ["update-ref", "-d", "refs/heads/feature/p2",
                                       "0123456789abcdef0123456789abcdef01234567"],
          repr(_del[0]["argv"] if _del else None))
    check("bd2 ...and it is never `-D`. The schema forbids that spelling because "
          "it discards unmerged work; the guarded form refuses a ref that MOVED, "
          "which is the case a force delete would happily run through",
          all("-D" not in s["argv"] for s in _guarded["steps"]),
          repr([s["argv"] for s in _guarded["steps"]]))
    _fallback = [s for s in _outside["steps"] if s["action"] == "branch-delete"]
    check("bd3 ...and with NO sha the old command stays, because there is nothing "
          "to guard on - a fallback that silently force-deleted would be worse "
          "than git's over-cautious refusal",
          _fallback and _fallback[0]["argv"] == ["branch", "-d", "feature/p2"],
          repr(_fallback[0]["argv"] if _fallback else None))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__worktrees.py --selftest\n")
    raise SystemExit(2)
