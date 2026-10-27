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

    # --- a phase branch checked out in the MAIN worktree ----------------------
    # Signed off from the main tree while it stands on the phase branch: the main
    # tree is never removed and never switched, so the branch can only be freed by
    # the operator. The plan has to say how, in commands they can run.
    on_main = M.parse_list(
        "worktree /main\nHEAD abc\nbranch refs/heads/feature/p2\n")
    foreign_main = M.cleanup_plan(
        on_main, "feature/p2", "dev", M.CONTAINED, False, cwd_tree=M.CWD_OUTSIDE,
        want_worktree=True, want_branch=True,
        owned={"ok": False, "why": "no audit-worktree.json in /main/.git - this "
                                   "worktree was not created by the plugin"},
        settled=SETTLED_OK)
    _fm_first = (foreign_main["blocked"] or [{"why": "", "remedy": ""}])[0]
    check("mt1 the MAIN worktree is refused for being the main worktree, ahead of "
          "provenance - a main tree carries no marker, so asking whose it is first "
          "told the operator to `git worktree remove` it: %r" % (_fm_first,),
          "MAIN worktree" in _fm_first["why"]
          and not any("worktree remove" in b["remedy"]
                      for b in foreign_main["blocked"]))
    check("mt2 ...and the branch half names the two commands that free it, run "
          "from the main tree: switch to the parent, then delete the branch - "
          "nothing is run, so no HEAD moves: %r / %r"
          % (foreign_main.get("followUp"), [b["remedy"] for b in
                                            foreign_main["blocked"]]),
          foreign_main.get("followUp") == {
              "from": "/main",
              "commands": ["git switch dev", "git branch -d feature/p2"],
              "note": None}
          and not foreign_main["steps"]
          and any("`git switch dev`" in b["remedy"]
                  and "`git branch -d feature/p2`" in b["remedy"]
                  for b in foreign_main["blocked"])
          and not any("must go first" in b["remedy"]
                      for b in foreign_main["blocked"]))
    parent_elsewhere = M.parse_list(
        "worktree /main\nHEAD abc\nbranch refs/heads/feature/p2\n\n"
        "worktree /wt-dev\nHEAD def\nbranch refs/heads/dev\n")
    _pe = _cp(parent_elsewhere, "feature/p2", "dev", M.CONTAINED, False,
              want_worktree=False, want_branch=True)
    check("mt3 with the parent checked out in another worktree, `git switch dev` "
          "cannot run in the main tree, so the command detaches at it instead - "
          "and says that leaves the main tree on a detached HEAD: %r"
          % (_pe.get("followUp"),),
          _pe.get("followUp") == {
              "from": "/main",
              "commands": ["git switch --detach dev", "git branch -d feature/p2"],
              "note": "leaves /main on a detached HEAD at dev"}
          and any("detached HEAD" in b["remedy"] for b in _pe["blocked"]))
    _linked = _cp(open_trees, "feature/p2", "dev", M.CONTAINED, False,
                  want_worktree=False, want_branch=True)
    check("mt4 SECOND DIRECTION: a branch held by a LINKED worktree gets no "
          "switch command - that worktree goes first, and the refusal still says "
          "so: %r" % (_linked,),
          _linked.get("followUp") is None
          and any("must go first" in b["remedy"] for b in _linked["blocked"]))
    check("mt5 ...and a plan with nothing blocked carries no follow-up either",
          _cp([], "feature/p2", "dev", M.CONTAINED, False, want_worktree=False,
              want_branch=True).get("followUp") is None)

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
    import _manifest_io as _mio_q
    signed = {"id": "P2", "status": "in_progress", "branch": "audit/p2",
              "review": {"status": "passed"}, "mergedAt": "2026-01-01T00:00:00Z",
              "tasks": [{"id": "P2.1", "status": "done"}]}
    check("q1s a phase signed off by the verb - stored status untouched, review "
          "passed, merged - is SETTLED when the caller hands in the derived status, "
          "so the cleanup a signed-off merge owes is not refused",
          M.phase_settled(signed, TERM, status_of=_mio_q.effective_phase_status)
          ["settled"] is True,
          M.phase_settled(signed, TERM, status_of=_mio_q.effective_phase_status)["why"])
    check("q1u SECOND DIRECTION: the same phase with no verdict recorded is not "
          "settled, derived status or not - finished work nobody signed off",
          M.phase_settled(dict(signed, review={"status": "pending"}), TERM,
                          status_of=_mio_q.effective_phase_status)["settled"] is False)
    import ast as _ast_q
    import _output as _out_q
    _callers = []
    for _rel, _path in _out_q.py_files(_out_q.SCRIPTS_DIR):
        if os.path.basename(_path) == "_worktrees.py":
            continue
        with open(_path, encoding="utf-8") as _fh:
            _tree = _ast_q.parse(_fh.read())
        for _node in _ast_q.walk(_tree):
            if (isinstance(_node, _ast_q.Call)
                    and isinstance(_node.func, _ast_q.Attribute)
                    and _node.func.attr in ("phase_settled", "observe_for_sweep")):
                _callers.append((os.path.basename(_path), _node.func.attr,
                                 any(k.arg == "status_of" for k in _node.keywords)))
    check("q1c EVERY caller of phase_settled / observe_for_sweep in the tree hands in "
          "the derived status - one that reads the stored field refuses the cleanup "
          "a signed-off merge owes, and it is found here by name rather than by the "
          "operator whose worktree was not removed: %r" % (_callers,),
          len(_callers) >= 4 and all(c[2] for c in _callers))
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
    # The filter that skipped a non-dict task removed it from the OPEN list
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

    # --- the plan must act on the record it MEASURED ----------------------------
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

    # --- standing-in is CONTAINMENT, and an unestablished cwd refuses ------------
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
    # The two sides of this comparison come from different places: git's porcelain
    # prints POSIX separators on every platform, `os.getcwd()` on Windows gives
    # backslashes. A boundary built from `os.sep` compares one spelling against the
    # other and answers False - silently returning wrong on one platform. Caught by
    # windows-latest on the 2.1.1 candidate; asserted here on every platform.
    _mixed = [{"path": "C:/x/repo-P1", "branch": "feature/p1"}]
    check("s5b a git-printed path and a Windows cwd are the same worktree - the "
          "separators differ because the two answers come from different places, "
          "and a guard that misses on that difference is not a guard",
          (M.standing_in(_mixed, "C:\\x\\repo-P1\\src", resolve=lambda p: p)
           or {}).get("path") == "C:/x/repo-P1",
          repr(M.standing_in(_mixed, "C:\\x\\repo-P1\\src", resolve=lambda p: p)))
    check("s5c ...and the boundary still holds across the spellings: "
          "`C:\\x\\repo-P1-old` is not inside `C:/x/repo-P1`",
          M.standing_in(_mixed, "C:\\x\\repo-P1-old", resolve=lambda p: p) is None,
          repr(M.standing_in(_mixed, "C:\\x\\repo-P1-old", resolve=lambda p: p)))
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
    # --- the marker has to describe the work that is in the tree ----------------
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

    # --- a task marker names ONE task, and a task tree is never swept ------------
    _tk = tempfile.mkdtemp()
    try:
        _tadm = os.path.join(_tk, "admin")
        os.makedirs(_tadm)
        with io.open(os.path.join(_tadm, M.PROVENANCE_FILE), "w",
                     encoding="utf-8") as _fh:
            _fh.write(json.dumps({"createdBy": M.PROVENANCE_MARK,
                                  "phaseId": "P1", "taskId": "P1.2",
                                  "base": "a" * 40, "phaseTree": "/x/repo",
                                  "at": "2026-01-01T00:00:00Z"}))
        _saved_adm, M.admin_dir = M.admin_dir, lambda _p, run=None: _tadm
        try:
            _mine = M.read_provenance("/x/repo-P1.2", expect_task="P1.2")
            check("tk1 a marker written for task P1.2 answers ours=True when "
                  "asked about P1.2 - the allow case, without which tk2 passes by "
                  "a reader that refuses every marker",
                  _mine["ours"] is True, repr(_mine["basis"][:80]))
            _other = M.read_provenance("/x/repo-P1.2", expect_task="P1.3")
            check("tk2 ...and the same marker is NOT ours for task P1.3, with the "
                  "refusal naming both tasks - `createdBy` alone proved the plugin "
                  "made A task tree, never THIS task's",
                  _other["ours"] is False and "P1.2" in _other["basis"]
                  and "P1.3" in _other["basis"], repr(_other["basis"]))
            _wide_t = M.read_provenance("/x/repo-P1.2")
            check("tk3 ...and without an expected task the wide question still "
                  "answers ours=True, so the report does not call a task tree a "
                  "stranger",
                  _wide_t["ours"] is True, repr(_wide_t["ours"]))
        finally:
            M.admin_dir = _saved_adm
        with io.open(os.path.join(_tadm, M.PROVENANCE_FILE), "w",
                     encoding="utf-8") as _fh:
            _fh.write(json.dumps({"createdBy": M.PROVENANCE_MARK,
                                  "phaseId": "P1", "branch": "feature/p1"}))
        _saved_adm, M.admin_dir = M.admin_dir, lambda _p, run=None: _tadm
        try:
            _phase_marker = M.read_provenance("/x/repo-P1", expect_task="P1.2")
            check("tk4 a PHASE marker (no taskId) is not a task's: asking about a "
                  "task of a phase worktree is a refusal, not a match on "
                  "createdBy",
                  _phase_marker["ours"] is False, repr(_phase_marker["basis"]))
        finally:
            M.admin_dir = _saved_adm
    finally:
        shutil.rmtree(_tk, ignore_errors=True)

    _ttrees = _trees("worktree /repo\nHEAD aaa\nbranch refs/heads/dev\n\n"
                     "worktree /wt-t1\nHEAD bbb\ndetached\n\n"
                     "worktree /wt-x\nHEAD ccc\ndetached\n")
    _tmark = {"/wt-t1": {"ok": True, "taskId": "P1.2", "phaseId": "P1"}}
    _tdirty = M.sweep_plan(
        _ttrees, {}, {}, {},
        {"/wt-t1": {"dirty": True, "lines": [" M src/a.js"]}},
        cwd_tree=M.CWD_OUTSIDE, verbs=("removeWorktrees",), task_by_path=_tmark)
    _kept = [k for k in _tdirty["kept"] if k["path"] == "/wt-t1"]
    check("ts1 the sweep KEEPS a dirty task tree and names the task and the dirty "
          "path - never an action, and never filed under strangers",
          len(_kept) == 1 and _kept[0].get("taskId") == "P1.2"
          and "src/a.js" in " ".join(r["why"] for r in _kept[0]["reasons"])
          and "P1.2" in " ".join(r["why"] for r in _kept[0]["reasons"])
          and not _tdirty["actions"]
          and "/wt-t1" not in [s["path"] for s in _tdirty["strangers"]],
          repr(_tdirty["kept"]))
    _tclean = M.sweep_plan(
        _ttrees, {}, {}, {}, {"/wt-t1": {"dirty": False, "lines": []}},
        cwd_tree=M.CWD_OUTSIDE, verbs=("removeWorktrees",), task_by_path=_tmark)
    check("ts2 ...a CLEAN task tree is kept as well: removing one is `task-remove`'s "
          "job, after integration, and a sweep that reaped it would race the wave",
          not _tclean["actions"]
          and [k["path"] for k in _tclean["kept"]] == ["/wt-t1"],
          repr(_tclean["kept"]))
    check("ts3 ...and a detached tree with NO task marker is still a stranger, "
          "counted in `examined` beside the task tree",
          [s["path"] for s in _tclean["strangers"]] == ["/wt-x"]
          and _tclean["examined"] == 2, repr(_tclean["strangers"]))

    _outside = M.cleanup_plan(
        open_trees, "feature/p2", "dev", M.CONTAINED, False, [],
        cwd_tree=M.CWD_OUTSIDE, owned=OWNED_OK, settled=SETTLED_OK)
    check("s8 ...and the caller that DID establish it, and is outside every "
          "worktree, still gets the removal - without this the refusal above is a "
          "guard that refuses everything and proves nothing",
          [s["action"] for s in _outside["steps"]] == ["worktree-remove",
                                                       "branch-delete"],
          repr([s["action"] for s in _outside["steps"]]))

    # --- the deletion is guarded on where the branch points ----------------------
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

    _advance_cases(check)


# --- a task tree brought to the phase head with its work carried ------------------
# A REAL repository, because what is under test is what git's checkout does to
# uncommitted work - a fake runner would encode the answer the move hopes for. The
# fixture's base holds a.txt, b.txt, d.txt and docs/r.json; the head moves b.txt
# and docs/r.json. A tree's work edits a.txt, deletes d.txt and adds n.txt, so all
# three shapes of uncommitted work ride the move.
_AV_WORK = {"a.txt": b"the task's edit of a\n", "n.txt": b"a file the task added\n"}


def _av_repo(prefix):
    """`(root, repo, base, head)`: a repository whose head moved b.txt and
    docs/r.json past `base`. Removed at exit through `fixture_root`."""
    root = os.path.realpath(_harness.fixture_root(prefix))
    repo = os.path.join(root, "repo")
    os.makedirs(os.path.join(repo, "docs"))
    for rel, body in (("a.txt", b"a at base\n"), ("b.txt", b"b at base\n"),
                      ("d.txt", b"d at base\n"), ("docs/r.json", b"{}\n")):
        with open(os.path.join(repo, *rel.split("/")), "wb") as fh:
            fh.write(body)
    for argv in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "base"]):
        _harness.git(repo, *argv)
    base = _harness.git(repo, "rev-parse", "HEAD").strip()
    for rel, body in (("b.txt", b"b at head\n"), ("docs/r.json", b"{\"at\": 1}\n")):
        with open(os.path.join(repo, *rel.split("/")), "wb") as fh:
            fh.write(body)
    for argv in (["add", "-A"], ["commit", "-qm", "the phase moved"]):
        _harness.git(repo, *argv)
    return root, repo, base, _harness.git(repo, "rev-parse", "HEAD").strip()


def _av_tree(root, repo, base, name, extra=None):
    """A detached tree of `repo` at `base` holding the task's work, plus `extra`
    ({rel: bytes}) written over it."""
    tree = os.path.join(root, name)
    _harness.git(repo, "worktree", "add", "-q", "--detach", tree, base)
    for rel, body in sorted(dict(_AV_WORK, **(extra or {})).items()):
        with open(os.path.join(tree, *rel.split("/")), "wb") as fh:
            fh.write(body)
    os.remove(os.path.join(tree, "d.txt"))
    return tree


def _av_bytes(tree, rels=("a.txt", "b.txt", "d.txt", "n.txt", "docs/r.json")):
    """{rel: bytes or None} - what the tree holds at each path."""
    found = {}
    for rel in rels:
        path = os.path.join(tree, *rel.split("/"))
        if os.path.exists(path):
            with open(path, "rb") as fh:
                found[rel] = fh.read()
        else:
            found[rel] = None
    return found


def _av_head(tree):
    return _harness.git(tree, "rev-parse", "HEAD").strip()


def _av_record(rel):
    """The caller's record rule, injected: this module may not import the
    layer-mate that holds the real one."""
    return rel == "docs" or rel.startswith("docs/")


def _advance_cases(check):
    try:
        root, repo, base, head = _av_repo("advance-")
    except RuntimeError as exc:
        _harness.could_not_run(check, "av1 a git fixture to move a tree over",
                               "%s" % (exc,))
        return
    # The allow direction: nothing the task changed moved between base and head.
    tree = _av_tree(root, repo, base, "t-clear")
    before = _av_bytes(tree)
    moved = M.advance_tree(tree, base, head)
    after = _av_bytes(tree)
    check("av1 a tree whose work touches none of the files that moved is brought "
          "to the head: HEAD is the head, the moved file holds the head's bytes, "
          "and the answer names what moved",
          moved.get("advanced") is True and _av_head(tree) == head
          and after["b.txt"] == b"b at head\n"
          and moved.get("moved") == ["b.txt", "docs/r.json"]
          and moved.get("from") == base and moved.get("to") == head,
          repr((moved, _av_head(tree)[:12])))
    check("av2 ...with the work intact byte for byte - the edited file, the added "
          "untracked file and the deletion all ride the move",
          after["a.txt"] == before["a.txt"] == _AV_WORK["a.txt"]
          and after["n.txt"] == _AV_WORK["n.txt"] and after["d.txt"] is None
          and sorted(moved.get("work") or []) == ["a.txt", "d.txt", "n.txt"],
          repr((after, moved.get("work"))))
    # The deny direction: the work edits b.txt, which the head moved too.
    tree_o = _av_tree(root, repo, base, "t-overlap", {"b.txt": b"the task's b\n"})
    before_o = _av_bytes(tree_o)
    refused = M.advance_tree(tree_o, base, head)
    check("av3 a tree whose work overlaps a moved file is refused BY NAME - the "
          "overlapping file listed, and only it",
          refused.get("advanced") is False
          and refused.get("overlap") == ["b.txt"]
          and "b.txt" in ((refused.get("refusal") or {}).get("why") or "")
          and "a.txt" not in ((refused.get("refusal") or {}).get("why") or ""),
          repr(refused))
    check("av4 ...and the refused tree is left untouched: HEAD still the base, "
          "every byte as it was",
          _av_head(tree_o) == base and _av_bytes(tree_o) == before_o,
          repr((_av_head(tree_o)[:12], _av_bytes(tree_o))))
    # A record path the drive refreshed is not the task's work: it is put back
    # and moves with the head. Without the records named it is an overlap.
    tree_r = _av_tree(root, repo, base, "t-records", {"docs/r.json": b"refreshed\n"})
    unnamed = M.advance_tree(tree_r, base, head)
    check("av5 a dirty record path the caller does NOT name as a record is work, "
          "and overlapping the head it is refused by name",
          unnamed.get("advanced") is False
          and unnamed.get("overlap") == ["docs/r.json"]
          and _av_head(tree_r) == base, repr(unnamed))
    named = M.advance_tree(tree_r, base, head, is_record=_av_record)
    check("av6 ...named as a record it is not work: the tree moves, the record "
          "holds the head's bytes and the task's work is intact",
          named.get("advanced") is True and _av_head(tree_r) == head
          and _av_bytes(tree_r)["docs/r.json"] == b"{\"at\": 1}\n"
          and _av_bytes(tree_r)["a.txt"] == _AV_WORK["a.txt"]
          and "docs/r.json" not in (named.get("work") or []), repr(named))
    # A failure mid-move: git's checkout reports success and a work file comes
    # out different. The byte check after the move is what sees it.
    tree_m = _av_tree(root, repo, base, "t-midmove")
    before_m = _av_bytes(tree_m)

    def scribbling(cwd, args, timeout=60):
        done = M._git(cwd, args)
        if args[:1] == ["checkout"] and head in args and done[0] == 0:
            with open(os.path.join(tree_m, "a.txt"), "wb") as fh:
                fh.write(b"bytes the move should never have written\n")
        return done
    broke = M.advance_tree(tree_m, base, head, run=scribbling)
    check("av7 a move whose result differs from the work by one byte is NOT an "
          "advance: it is undone, the tree is back at its base and every byte of "
          "the work is as it was",
          broke.get("advanced") is False and broke.get("restored") is True
          and broke.get("error") and _av_head(tree_m) == base
          and _av_bytes(tree_m) == before_m,
          repr((broke, _av_head(tree_m)[:12], _av_bytes(tree_m))))
    check("av8 ...and the backup taken before the move is gone once the work is "
          "back - nothing is kept when nothing was lost",
          not broke.get("kept"), repr(broke.get("kept")))
    tree_f = _av_tree(root, repo, base, "t-gitfails")
    before_f = _av_bytes(tree_f)

    def refusing(cwd, args, timeout=60):
        if args[:1] == ["checkout"] and head in args:
            return 1, "", "error: fixture: the checkout died"
        return M._git(cwd, args)
    died = M.advance_tree(tree_f, base, head, run=refusing)
    check("av9 a checkout git refuses leaves the work as it was and says git's "
          "words",
          died.get("advanced") is False and _av_head(tree_f) == base
          and _av_bytes(tree_f) == before_f
          and "the checkout died" in (died.get("error") or ""),
          repr(died))
    same = M.advance_tree(tree, head, head)
    check("av10 a tree already at the head is not moved and says so - the "
          "already-answer is not an advance",
          same.get("advanced") is False and same.get("already") is True
          and not same.get("refusal") and _av_head(tree) == head, repr(same))
    stale = M.advance_tree(tree_o, head, head)
    check("av11 a base that is not the tree's HEAD is refused before anything "
          "moves - the move is from the commit the tree stands on, never from a "
          "base somebody remembered",
          stale.get("advanced") is False and stale.get("refusal")
          and _av_head(tree_o) == base and _av_bytes(tree_o) == before_o,
          repr(stale))
    pure = M.advance_plan(base, head, ["a.txt", "docs/r.json", "b.txt"],
                          ["b.txt", "docs/r.json"], is_record=_av_record)
    check("av12 the plan is pure over the four lists: work is the changed paths "
          "outside the records, the overlap is work that moved",
          pure.get("work") == ["a.txt", "b.txt"] and pure.get("overlap") == ["b.txt"]
          and pure.get("ok") is False, repr(pure))
    _advance_after_cases(check)
    _advance_crash_cases(check)


def _av_pair(prefix, base_files, head_files, force=()):
    """`(root, repo, base, head)`: `base_files` committed, then `head_files`
    written over them and committed - each path in `force` added past the
    ignore rules, as a head that starts tracking an ignored path does."""
    root = os.path.realpath(_harness.fixture_root(prefix))
    repo = os.path.join(root, "repo")
    for files, label in ((base_files, "base"), (head_files, "head")):
        for rel, body in sorted(files.items()):
            path = os.path.join(repo, *rel.split("/"))
            if not os.path.isdir(os.path.dirname(path)):
                os.makedirs(os.path.dirname(path))
            with open(path, "wb") as fh:
                fh.write(body)
        if label == "base":
            _harness.git(repo, "init", "-q")
        _harness.git(repo, "add", "-A")
        for rel in force:
            if label == "head":
                _harness.git(repo, "add", "-f", rel)
        _harness.git(repo, "commit", "-qm", label)
        if label == "base":
            base = _harness.git(repo, "rev-parse", "HEAD").strip()
    return root, repo, base, _harness.git(repo, "rev-parse", "HEAD").strip()


def _av_plain_tree(root, repo, base, name, work):
    """A detached tree at `base` with `work` ({rel: bytes}) written in it."""
    tree = os.path.join(root, name)
    _harness.git(repo, "worktree", "add", "-q", "--detach", tree, base)
    for rel, body in sorted(work.items()):
        path = os.path.join(tree, *rel.split("/"))
        if not os.path.isdir(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))
        with open(path, "wb") as fh:
            fh.write(body)
    return tree


def _av_status(tree):
    """`{path: two-letter code}` git reports for the tree, ignored included."""
    out = _harness.git(tree, "status", "--porcelain", "-z", "--untracked-files=all",
                       "--ignored", "--no-renames")
    return dict((item[3:], item[:2]) for item in out.split("\0") if item)


def _advance_after_cases(check):
    """What the tree holds AFTER git's checkout is what decides a move: git
    exits 0 over a file it could not update, and a rule the head adds can turn
    the task's file into one no `add -A` will ever take."""
    root, repo, base, head = _av_pair("advance-ign-", {"a.txt": b"a\n"},
                                      {".gitignore": b"gen/\n"})
    tree = _av_plain_tree(root, repo, base, "t-ign",
                          {"gen/new_module.py": b"the task's only copy\n"})
    said = M.advance_tree(tree, base, head)
    check("av13 a head whose .gitignore covers the task's untracked file is no "
          "advance: the file would be ignored at the head and no integration "
          "would carry it, so the tree stays at its base with the file untracked "
          "(not ignored) and the answer names it",
          said.get("advanced") is False and _av_head(tree) == base
          and _av_status(tree).get("gen/new_module.py") == "??"
          and _av_bytes(tree, ("gen/new_module.py",))["gen/new_module.py"]
          == b"the task's only copy\n"
          and "gen/new_module.py" in (said.get("error") or "")
          + ((said.get("refusal") or {}).get("why") or ""),
          repr((said, _av_status(tree))))
    root, repo, base, head = _av_pair(
        "advance-trk-", {"a.txt": b"a\n", ".gitignore": b"local.cfg\n"},
        {"local.cfg": b"the head's committed cfg\n"}, force=("local.cfg",))
    tree = _av_plain_tree(root, repo, base, "t-trk",
                          {"local.cfg": b"the task tree's own cfg\n"})
    said = M.advance_tree(tree, base, head)
    check("av14 an ignored file in the tree at a path the head starts tracking is "
          "refused by name before anything moves - git would overwrite it "
          "without a word",
          said.get("advanced") is False and _av_head(tree) == base
          and _av_bytes(tree, ("local.cfg",))["local.cfg"]
          == b"the task tree's own cfg\n"
          and "local.cfg" in ((said.get("refusal") or {}).get("why") or ""),
          repr(said))
    root, repo, base, head = _av_pair(
        "advance-ro-", {"a.txt": b"a\n", "m.txt": b"m at base\n",
                        "z/locked.txt": b"z at base\n"},
        {"m.txt": b"m at head\n", "z/locked.txt": b"z at head\n"})
    tree = _av_plain_tree(root, repo, base, "t-ro", {"a.txt": b"the task's a\n"})
    locked = os.path.join(tree, "z")
    os.chmod(locked, 0o555)
    try:
        if os.access(locked, os.W_OK):
            _harness.skip(check, "av15 a file git could not update", "a directory "
                          "made read-only stays writable here (an administrator, "
                          "or a filesystem that ignores the mode)",
                          os.access(locked, os.W_OK))
        else:
            said = M.advance_tree(tree, base, head)
            os.chmod(locked, 0o755)
            check("av15 a file git could not update during the checkout (it exits "
                  "0 and says so on stderr) is no advance: the move is undone - "
                  "back at the base, the moved files holding the base's bytes, the "
                  "task's work as it was - and the answer names the file",
                  said.get("advanced") is False and said.get("restored") is True
                  and "z/locked.txt" in (said.get("error") or "")
                  and _av_head(tree) == base and _av_status(tree) == {"a.txt": " M"}
                  and _av_bytes(tree, ("a.txt", "m.txt", "z/locked.txt")) == {
                      "a.txt": b"the task's a\n", "m.txt": b"m at base\n",
                      "z/locked.txt": b"z at base\n"},
                  repr((said, _av_status(tree))))
    finally:
        os.chmod(locked, 0o755)
    root, repo, base, head = _av_pair(
        "advance-lock-", {"a.txt": b"a\n", "m.txt": b"m at base\n",
                          "z/locked.txt": b"z at base\n"},
        {"m.txt": b"m at head\n", "z/locked.txt": b"z at head\n"})
    tree = _av_plain_tree(root, repo, base, "t-lock", {"a.txt": b"the task's a\n"})
    locked = os.path.join(tree, "z")
    os.chmod(locked, 0o555)

    def lock_lifts(cwd, args, timeout=60):
        # The lock holds through the checkout and is gone by the undo - the
        # shape of a file another process held open for a moment.
        done = M._git(cwd, args)
        if args[:1] == ["checkout"] and head in args:
            os.chmod(locked, 0o755)
        return done
    try:
        if os.access(locked, os.W_OK):
            _harness.skip(check, "av24 a lock that lifts before the undo",
                          "a directory made read-only stays writable here",
                          os.access(locked, os.W_OK))
        else:
            said = M.advance_tree(tree, base, head, run=lock_lifts)
            check("av24 ...and once the file can be written again the undo "
                  "finishes: back at the base, every moved file holding the base's "
                  "bytes, only the task's work changed, nothing kept",
                  said.get("advanced") is False and said.get("restored") is True
                  and not said.get("kept") and _av_head(tree) == base
                  and _av_status(tree) == {"a.txt": " M"}
                  and _av_bytes(tree, ("a.txt", "m.txt", "z/locked.txt")) == {
                      "a.txt": b"the task's a\n", "m.txt": b"m at base\n",
                      "z/locked.txt": b"z at base\n"},
                  repr((said, _av_status(tree))))
    finally:
        os.chmod(locked, 0o755)
    root, repo, base, head = _av_pair("advance-case-", {"README": b"r\n", "a.txt": b"a\n"},
                                      {"other.txt": b"o\n"})
    _harness.git(repo, "mv", "README", "readme.tmp")
    _harness.git(repo, "mv", "readme.tmp", "readme")
    _harness.git(repo, "commit", "-qm", "a rename that changes only the case")
    head = _harness.git(repo, "rev-parse", "HEAD").strip()
    tree = _av_plain_tree(root, repo, base, "t-case", {"a.txt": b"the task's a\n"})
    said = M.advance_tree(tree, base, head)
    check("av25 ALLOW: a head that renames a tracked file by case alone is no "
          "ignored file in the way, on a filesystem that folds case too - the "
          "tree moves with its work",
          said.get("advanced") is True and _av_head(tree) == head
          and _av_status(tree) == {"a.txt": " M"}, repr(said))
    root, repo, base, head = _av_pair("advance-to-", {"a.txt": b"a\n", "b.txt": b"b\n"},
                                      {"b.txt": b"b at head\n"})
    tree = _av_plain_tree(root, repo, base, "t-timeout", {"a.txt": b"the task's a\n"})

    def timing_out(cwd, args, timeout=60):
        done = M._git(cwd, args)
        if args[:1] == ["checkout"] and head in args:
            return None, "", "git did not finish within its timeout"
        return done
    said = M.advance_tree(tree, base, head, run=timing_out)
    check("av16 a checkout whose answer never came (it ran, then the runner timed "
          "out) is undone back to the BASE - restored means HEAD is the base and "
          "every byte is as it was, not only the held paths",
          said.get("advanced") is False and said.get("restored") is True
          and _av_head(tree) == base and _av_status(tree) == {"a.txt": " M"}
          and _av_bytes(tree, ("a.txt", "b.txt")) == {
              "a.txt": b"the task's a\n", "b.txt": b"b\n"},
          repr((said, _av_head(tree)[:12], _av_status(tree))))
    root, repo, base, head = _av_pair(
        "advance-idx-", {"a.txt": b"a\n", "docs/plan.json": b"{}\n"},
        {"docs/j.jsonl": b"row at head\n", "docs/plan.json": b"{\"h\": 1}\n"})
    tree = _av_plain_tree(root, repo, base, "t-staged", {
        "a.txt": b"the task's a\n", "docs/j.jsonl": b"row at head\n",
        "docs/plan.json": b"{\"h\": 1}\n"})
    _harness.git(tree, "add", "-A")
    said = M.advance_tree(tree, base, head, is_record=_av_record)
    check("av17 a tree whose index holds the staged work and staged record paths "
          "(the integration stages with `add -A`) moves cleanly: the records "
          "follow the head in the index too, and only the work is left changed",
          said.get("advanced") is True and _av_head(tree) == head
          and _av_status(tree) == {"a.txt": "M "}, repr((said, _av_status(tree))))
    root, repo, base, head = _av_pair("advance-keep-", {"a.txt": b"a\n", "b.txt": b"b\n"},
                                      {"b.txt": b"b at head\n"})
    tree = _av_plain_tree(root, repo, base, "t-keep", {"a.txt": b"the task's a\n"})
    _harness.git(tree, "add", "a.txt")

    def scribble(cwd, args, timeout=60):
        done = M._git(cwd, args)
        if args[:1] == ["checkout"] and head in args and done[0] == 0:
            with open(os.path.join(tree, "a.txt"), "wb") as fh:
                fh.write(b"bytes the move should never have written\n")
        return done
    said = M.advance_tree(tree, base, head, run=scribble)
    check("av18 an undone move gives the index back as well as the bytes: the "
          "work the task had staged is staged again",
          said.get("restored") is True and _av_head(tree) == base
          and _av_status(tree) == {"a.txt": "M "}, repr((said, _av_status(tree))))
    root, repo, base, head = _av_pair("advance-stuck-", {"a.txt": b"a\n", "b.txt": b"b\n"},
                                      {"b.txt": b"b at head\n"})
    tree = _av_plain_tree(root, repo, base, "t-stuck", {"a.txt": b"the task's a\n"})

    def stuck(cwd, args, timeout=60):
        # The move comes out wrong, and git then refuses the way back.
        if args[:1] == ["checkout"] and "-f" in args:
            return 1, "", "error: fixture: the way back is refused"
        done = M._git(cwd, args)
        if args[:1] == ["checkout"] and head in args and done[0] == 0:
            with open(os.path.join(tree, "a.txt"), "wb") as fh:
                fh.write(b"bytes the move should never have written\n")
        return done
    said = M.advance_tree(tree, base, head, run=stuck)
    kept = said.get("kept") or ""
    check("av26 an undo that cannot finish says so - not restored, the copy kept "
          "and named with what is still wrong - and still writes the task's work "
          "back: restored is a checked claim, never git's exit",
          said.get("advanced") is False and said.get("restored") is False
          and kept and os.path.isfile(os.path.join(kept, M.COPY_INDEX))
          and kept in (said.get("error") or "")
          and "the way back is refused" in (said.get("error") or "")
          and _av_bytes(tree, ("a.txt",))["a.txt"] == b"the task's a\n",
          repr(said))


def _av_marked(tree, base):
    """Mark `tree` as task T1's at `base`, the way `task-add` does."""
    M.write_record(tree, {"createdBy": M.PROVENANCE_MARK, "taskId": "T1",
                          "phaseId": "P1", "base": base})
    return M.read_provenance(tree, expect_task="T1").get("record") or {}


class _Killed(BaseException):
    """The drive dying mid-move: not an Exception, so nothing catches it."""


def _advance_crash_cases(check):
    """A process killed in the middle of a move leaves the copy beside the tree;
    the next move reads it and finishes or forgets the move, rather than being
    blocked by it forever or diffing the work against a base the tree left."""
    root, repo, base, head = _av_pair("advance-crash-", {"a.txt": b"a\n", "b.txt": b"b\n"},
                                      {"b.txt": b"b at head\n"})
    tree = _av_plain_tree(root, repo, base, "t-crash", {"a.txt": b"the task's a\n"})
    _av_marked(tree, base)

    def dying_after(cwd, args, timeout=60):
        done = M._git(cwd, args)
        if args[:1] == ["checkout"] and head in args and done[0] == 0:
            raise _Killed("killed after the checkout")
        return done
    try:
        M.advance_task_tree(tree, "T1", head, run=dying_after)
    except _Killed:
        pass
    again = M.advance_task_tree(tree, "T1", head)
    record = M.read_provenance(tree, expect_task="T1").get("record") or {}
    copy = os.path.join(M.admin_dir(tree), M.ADVANCE_BACKUP)
    check("av19 a move killed after its checkout is finished by the next one - "
          "read as done, not undone and made again: the work reads back as it "
          "was, the marker names the head and the move, and the copy is gone",
          again.get("advanced") is True and again.get("resumed") is True
          and _av_head(tree) == head
          and record.get("base") == head and len(record.get("baseMoves") or []) == 1
          and not os.path.exists(copy)
          and _av_bytes(tree, ("a.txt",))["a.txt"] == b"the task's a\n",
          repr((again, record, os.path.exists(copy))))
    root, repo, base, head = _av_pair("advance-crash0-", {"a.txt": b"a\n", "b.txt": b"b\n"},
                                      {"b.txt": b"b at head\n"})
    tree = _av_plain_tree(root, repo, base, "t-crash0", {"a.txt": b"the task's a\n"})
    _av_marked(tree, base)

    def dying_before(cwd, args, timeout=60):
        if args[:1] == ["checkout"] and head in args:
            raise _Killed("killed before the checkout")
        return M._git(cwd, args)
    try:
        M.advance_task_tree(tree, "T1", head, run=dying_before)
    except _Killed:
        pass
    again = M.advance_task_tree(tree, "T1", head)
    record = M.read_provenance(tree, expect_task="T1").get("record") or {}
    check("av20 a move killed before its checkout leaves a copy the next move "
          "reads as stale - the tree still matches it at the base - so the move "
          "runs instead of being refused forever",
          again.get("advanced") is True and _av_head(tree) == head
          and record.get("base") == head
          and _av_bytes(tree, ("a.txt",))["a.txt"] == b"the task's a\n",
          repr((again, record)))
    root, repo, base, head = _av_pair("advance-race-", {"a.txt": b"a\n", "b.txt": b"b\n"},
                                      {"b.txt": b"b at head\n"})
    tree = _av_plain_tree(root, repo, base, "t-race", {"a.txt": b"the task's a\n"})
    copy = os.path.join(M.admin_dir(tree), M.ADVANCE_BACKUP)
    real_keep = M._keep_copy

    def racing(where, *rest, **kw):
        # A second mover made its copy between this one's look and its write.
        os.makedirs(where)
        with open(os.path.join(where, "index.json"), "w", encoding="utf-8") as fh:
            fh.write("{\"other\": 1}")
        return real_keep(where, *rest, **kw)
    M._keep_copy = racing
    try:
        raced = M.advance_tree(tree, base, head)
    finally:
        M._keep_copy = real_keep
    check("av21 a copy another mover made first is never deleted by this one: the "
          "move is refused and the other copy is still there",
          raced.get("advanced") is False and os.path.isfile(
              os.path.join(copy, "index.json")) and _av_head(tree) == base,
          repr((raced, os.path.exists(copy))))
    root, repo, base, head = _av_pair(
        "advance-rec-", {"a.txt": b"a\n", "docs/r.json": b"{}\n", "b.txt": b"b\n"},
        {"docs/r.json": b"{\"at\": 1}\n", "b.txt": b"b at head\n"})
    tree = _av_plain_tree(root, repo, base, "t-rec", {"a.txt": b"the task's a\n"})
    _av_marked(tree, base)
    moved = M.advance_task_tree(tree, "T1", head, is_record=_av_record)
    step = ((M.read_provenance(tree, expect_task="T1").get("record") or {})
            .get("baseMoves") or [{}])[-1]
    check("av22 the move the marker records names the files that moved under the "
          "work, not the caller's records",
          moved.get("advanced") is True and step.get("moved") == ["b.txt"],
          repr((moved, step)))
    before = M.read_provenance(tree, expect_task="T1").get("record") or {}
    wrote, why = M.write_record(tree, dict(before, unwritable=object()))
    after = M.read_provenance(tree, expect_task="T1").get("record") or {}
    check("av23 a marker that cannot be written leaves the old one whole - the "
          "record is serialised and written aside before it replaces anything",
          wrote == "" and why and after.get("base") == before.get("base") == head,
          repr((wrote, why, after)))
    _advance_kill_cases(check)
    _advance_low_cases(check)
    _advance_settle_cases(check)
    _advance_sync_cases(check)


def _advance_low_cases(check):
    """The edges a move meets in a real tree: a work file it cannot read, a
    lock a git left on the index, a tracked file the task made a directory."""
    root, repo, base, head = _av_pair("advance-unread-", {"a.txt": b"a\n", "b.txt": b"b\n"},
                                      {"b.txt": b"b at head\n"})
    tree = _av_plain_tree(root, repo, base, "t-unread", {"secret.key": b"k\n"})
    secret = os.path.join(tree, "secret.key")
    os.chmod(secret, 0o000)
    try:
        if os.access(secret, os.R_OK):
            _harness.skip(check, "av28 an unreadable work file", "a file made "
                          "unreadable stays readable here (an administrator, or a "
                          "filesystem that ignores the mode)", os.access(secret, os.R_OK))
        else:
            try:
                said = M.advance_tree(tree, base, head)
            except OSError as exc:
                said = {"raised": repr(exc)}
            check("av28 a work file the process cannot read is a refusal naming "
                  "it, before anything moves - not an exception out of the mover",
                  said.get("advanced") is False and "secret.key" in (
                      (said.get("refusal") or {}).get("why") or "")
                  and _av_head(tree) == base, repr(said))
    finally:
        os.chmod(secret, 0o644)
    root, repo, base, head = _av_pair("advance-lockidx-", {"a.txt": b"a\n", "b.txt": b"b\n"},
                                      {"b.txt": b"b at head\n"})
    tree = _av_plain_tree(root, repo, base, "t-lockidx", {"a.txt": b"the task's a\n"})
    index_lock = os.path.join(M.admin_dir(tree), "index.lock")

    def lock_left(cwd, args, timeout=60):
        done = M._git(cwd, args)
        if args[:1] == ["checkout"] and head in args and done[0] == 0:
            with open(os.path.join(tree, "a.txt"), "wb") as fh:
                fh.write(b"bytes the move should never have written\n")
        if args[:1] == ["checkout"] and "-f" in args:
            # A git killed mid-command leaves its lock beside the index.
            with open(index_lock, "wb") as fh:
                fh.write(b"a lock a killed git left\n")
        return done
    try:
        said = M.advance_tree(tree, base, head, run=lock_left)
        with open(index_lock, "rb") as fh:
            lock_bytes = fh.read()
    finally:
        if os.path.exists(index_lock):
            os.remove(index_lock)
    check("av29 an undo that finds a lock beside the index does not write the "
          "index under it: the lock is left as it was, the undo says the index "
          "was not put back, and the copy is kept",
          said.get("restored") is False and ".lock" in (said.get("error") or "")
          and said.get("kept") and lock_bytes == b"a lock a killed git left\n"
          and _av_bytes(tree, ("a.txt",))["a.txt"] == b"the task's a\n", repr(said))
    root, repo, base, head = _av_pair("advance-dirfile-", {"a.txt": b"a\n", "d.txt": b"d\n"},
                                      {"a.txt": b"a at head\n"})
    tree = _av_plain_tree(root, repo, base, "t-dirfile", {})
    os.remove(os.path.join(tree, "d.txt"))
    os.makedirs(os.path.join(tree, "d.txt"))
    with open(os.path.join(tree, "d.txt", "inside.txt"), "wb") as fh:
        fh.write(b"the task's file inside\n")
    said = M.advance_tree(tree, base, head)
    tree_h, base_h, head_h = _kill_fixture(99)
    half = os.path.join(M.admin_dir(tree_h), M.ADVANCE_BACKUP)
    os.mkdir(half)
    with open(os.path.join(half, "0.bin"), "wb") as fh:
        fh.write(b"a copy cut short before its index was written\n")
    resumed = M.advance_task_tree(tree_h, "T1", head_h, is_record=_av_record)
    check("av31 a copy cut short before its index.json (written last, and nothing "
          "moves before it is) is dropped and the move made",
          resumed.get("advanced") is True and not resumed.get("kept")
          and not os.path.exists(half) and not _kill_settled(tree_h, head_h),
          repr((resumed, _kill_settled(tree_h, head_h))))
    check("av30 a tracked file the task replaced with a directory is refused in "
          "words that say so, not only as a nested repository",
          said.get("advanced") is False and "replaced with a directory" in (
              (said.get("refusal") or {}).get("why") or "")
          and _av_head(tree) == base, repr(said))


def _refusing_drop():
    """`(install, restore)`: `os.rename` refuses to take a copy down - a handle
    another process holds open in it, as Windows does - and renames anything
    else."""
    real = M.os.rename

    def flaky(src, dst, *rest, **kw):
        if str(src).endswith(M.ADVANCE_BACKUP):
            raise PermissionError(13, "fixture: a handle is open in the copy")
        return real(src, dst, *rest, **kw)
    return (lambda: setattr(M.os, "rename", flaky),
            lambda: setattr(M.os, "rename", real))


def _settle_tree(prefix):
    """`(tree, base, head, copy)`: a marked tree at `base` whose work edits
    a.txt; the head moved b.txt, and c.txt is tracked and untouched."""
    root, repo, base, head = _av_pair(
        prefix, {"a.txt": b"a\n", "b.txt": b"b\n", "c.txt": b"c\n"},
        {"b.txt": b"b at head\n"})
    tree = _av_plain_tree(root, repo, base, "t", {"a.txt": b"the task's a\n"})
    _av_marked(tree, base)
    return tree, base, head, os.path.join(M.admin_dir(tree), M.ADVANCE_BACKUP)


# What an agent writes once it is handed the tree again: its own file further
# along, and a tracked file the work had not touched.
_NEWER = {"a.txt": b"the agent's later a\n", "c.txt": b"the agent's edit of c\n"}


def _write_newer(tree, extra=None):
    for rel, body in sorted(dict(_NEWER, **(extra or {})).items()):
        with open(os.path.join(tree, *rel.split("/")), "wb") as fh:
            fh.write(body)


def _held_still(tree, again, copy, head, before):
    """Whether `again` held the tree: kept and naming both newer paths, the
    copy still on disk, HEAD at `head`, and every byte and status as `before`."""
    rels = ("a.txt", "b.txt", "c.txt")
    said = again.get("error") or ""
    return (again.get("advanced") is False and again.get("kept") == copy
            and os.path.isdir(copy) and "a.txt" in said and "c.txt" in said
            and _av_head(tree) == head
            and (_av_bytes(tree, rels), _av_status(tree)) == before)


def _advance_settle_cases(check):
    """`kept` is read off the disk: a copy left beside the tree, for whatever
    reason, is a tree not settled. And a copy found there is never forced over
    bytes it does not account for - newer work keeps it, unchanged."""
    tree, base, head, copy = _settle_tree("advance-drop-")
    _ok, said = _armed([_refusing_drop()], lambda: M.advance_tree(tree, base, head))
    check("av32 a move that counted but whose copy will not come down answers "
          "kept, naming the copy still on disk - advanced, and not settled",
          said.get("advanced") is True and said.get("kept") == copy
          and os.path.isdir(copy) and copy in (said.get("error") or ""), repr(said))
    tree, base, head, copy = _settle_tree("advance-dropundo-")
    _ok, said = _armed([_refusing_drop()], lambda: M.advance_task_tree(
        tree, "T1", head, run=_scribbler(tree, head)))
    check("av33 an undone move whose copy will not come down answers kept too: "
          "restored, and the copy named and still on disk",
          said.get("advanced") is False and said.get("restored") is True
          and said.get("kept") == copy and os.path.isdir(copy), repr(said))
    _write_newer(tree)
    before = (_av_bytes(tree, ("a.txt", "b.txt", "c.txt")), _av_status(tree))
    again = M.advance_task_tree(tree, "T1", head)
    check("av34 work written after that answer is never forced over: the next "
          "move changes no byte, keeps the copy and names every path that "
          "diverged - the task's own file and a tracked file it had not touched",
          _held_still(tree, again, copy, base, before),
          repr((again, _av_bytes(tree, ("a.txt", "c.txt")))))
    tree, base, head, copy = _settle_tree("advance-killnewer-")
    killed, _said = _armed([], lambda: M.advance_task_tree(
        tree, "T1", head, run=_first_kill_runner(head, True)))
    _write_newer(tree)
    before = (_av_bytes(tree, ("a.txt", "b.txt", "c.txt")), _av_status(tree))
    again = M.advance_task_tree(tree, "T1", head)
    check("av35 work written after a kill and before the next move is never "
          "forced over either: that move changes no byte, keeps the copy and "
          "names the paths",
          killed and _held_still(tree, again, copy, head, before),
          repr((killed, again, _av_bytes(tree, ("a.txt", "c.txt")))))
    tree, _base, head = _kill_fixture(200)
    copy = os.path.join(M.admin_dir(tree), M.ADVANCE_BACKUP)
    _ok, first = _armed([_refusing_drop()], lambda: M.advance_task_tree(
        tree, "T1", head, is_record=_av_record))
    with open(os.path.join(tree, "docs", "r.json"), "wb") as fh:
        fh.write(b"{\"refreshed\": \"by the drive, from a later head\"}\n")
    again = M.advance_task_tree(tree, "T1", head, is_record=_av_record)
    check("av36 ALLOW: a recorded move whose copy stayed, in a tree whose records "
          "the drive has since refreshed and whose work is as the copy holds it, "
          "is settled by the next move - the copy dropped, nothing kept",
          first.get("advanced") is True and first.get("kept") == copy
          and not again.get("kept") and not os.path.exists(copy)
          and not again.get("error") and not _kill_settled(tree, head),
          repr((first.get("kept"), again, _kill_settled(tree, head))))
    tree, base, head, copy = _settle_tree("advance-recnewer-")
    _ok, first = _armed([_refusing_drop()], lambda: M.advance_task_tree(
        tree, "T1", head))
    _write_newer(tree)
    before = (_av_bytes(tree, ("a.txt", "b.txt", "c.txt")), _av_status(tree))
    again = M.advance_task_tree(tree, "T1", head)
    check("av37 ...and with newer work in it, the same recorded move's copy is "
          "kept and the paths named, nothing changed",
          first.get("advanced") is True and _held_still(tree, again, copy, head, before),
          repr((first.get("kept"), again)))
    # A git killed part way through its checkout: HEAD still at the base, one
    # file the head moves already written with the head's bytes. That state is
    # the move's own, so the next move puts it back and moves; a moved file
    # holding bytes neither commit has is not, and is held.
    for cid, body in (("av39", b"b at head\n"), ("av40", b"bytes neither commit has\n")):
        tree, base, head, copy = _settle_tree("advance-partial-%s-" % (cid,))
        killed, _said = _armed([], lambda: M.advance_task_tree(
            tree, "T1", head, run=_first_kill_runner(head, False)))
        with open(os.path.join(tree, "b.txt"), "wb") as fh:
            fh.write(body)
        before = (_av_bytes(tree, ("a.txt", "b.txt", "c.txt")), _av_status(tree))
        again = M.advance_task_tree(tree, "T1", head)
        if cid == "av39":
            check("av39 ALLOW: a checkout git left part way - HEAD at the base, a "
                  "file the head moves already holding the head's bytes - is the "
                  "move's own state: the next move puts it back and moves, nothing "
                  "kept",
                  killed and again.get("advanced") is True and not again.get("kept")
                  and _av_head(tree) == head and not os.path.exists(copy)
                  and _av_bytes(tree, ("a.txt", "b.txt")) == {
                      "a.txt": b"the task's a\n", "b.txt": b"b at head\n"},
                  repr((killed, again)))
        else:
            check("av40 ...and a file the head moves holding bytes NEITHER commit has "
                  "is newer work: held, named, no byte changed",
                  killed and again.get("advanced") is False
                  and again.get("kept") == copy and "b.txt" in (again.get("error") or "")
                  and _av_head(tree) == base
                  and (_av_bytes(tree, ("a.txt", "b.txt", "c.txt")),
                       _av_status(tree)) == before,
                  repr((killed, again)))


def _first_kill_runner(head, after):
    """A runner that dies at the checkout of `head`, before or after git runs
    it."""
    def dying(cwd, args, timeout=60):
        at = args[:3] == ["checkout", "-q", "--detach"] and head in args
        if at and not after:
            raise _Killed("before the checkout")
        done = M._git(cwd, args, timeout)
        if at and after:
            raise _Killed("after the checkout")
        return done
    return dying


def _advance_sync_cases(check):
    """The copy's `index.json` is written last so that one present means the
    copy is whole - which holds through a power cut only when every byte before
    it, and the names in its directory, reached the disk before it did."""
    tree, base, head, copy = _settle_tree("advance-sync-")
    events = []
    real_fsync, real_aside = M.os.fsync, M._write_aside

    def fsyncing(fd):
        events.append(("fsync", os.fstat(fd).st_ino))
        return real_fsync(fd)

    def aside(path, data, *rest, **kw):
        if os.path.basename(path) == M.COPY_INDEX:
            where = os.path.dirname(path)
            events.append(("index", sorted(
                os.stat(os.path.join(where, name)).st_ino for name in os.listdir(where)
                if not name.startswith(".")), os.stat(where).st_ino))
        return real_aside(path, data, *rest, **kw)

    def watching(cwd, args, timeout=60):
        if args[:1] == ["checkout"] and os.path.isdir(copy):
            events.append(("checkout", os.stat(os.path.join(copy, M.COPY_INDEX)).st_ino
                           if os.path.exists(os.path.join(copy, M.COPY_INDEX)) else None))
        return M._git(cwd, args, timeout)
    _ok, said = _armed([(lambda: setattr(M.os, "fsync", fsyncing),
                         lambda: setattr(M.os, "fsync", real_fsync)),
                        (lambda: setattr(M, "_write_aside", aside),
                         lambda: setattr(M, "_write_aside", real_aside))],
                       lambda: M.advance_tree(tree, base, head, run=watching))
    at = [i for i, e in enumerate(events) if e[0] == "index"]
    first_git = [i for i, e in enumerate(events) if e[0] == "checkout"]
    wrong = []
    if not at or not first_git:
        wrong.append("index.json was never written aside before a checkout")
    else:
        synced_before = set(e[1] for e in events[:at[0]] if e[0] == "fsync")
        files, where = events[at[0]][1], events[at[0]][2]
        wrong += ["a copy file not synced before index.json"] * bool(
            set(files) - synced_before)
        wrong += ["the copy's directory not synced before index.json"] * (
            os.name != "nt" and where not in synced_before)
        synced_after = set(e[1] for e in events[at[0]:first_git[0]] if e[0] == "fsync")
        index_ino = events[first_git[0]][1]
        wrong += ["index.json not synced before the first checkout"] * (
            index_ino not in synced_after)
        wrong += ["the directory not synced again before the first checkout"] * (
            os.name != "nt" and where not in synced_after)
    check("av38 the copy's files and its directory reach the disk before its "
          "index.json is written, and index.json and the directory again before "
          "git moves anything - so an index.json present means a whole copy",
          said.get("advanced") is True and not wrong
          and any(e[0] == "index" and e[1] for e in events),
          repr((wrong, events[:12], said.get("error"))))


# The task's work in the kill fixture, beside a deletion of d.txt; the record
# paths under docs/ hold the head's bytes, as a drive's refresh leaves them.
# Enough files that a write made once per held path is made more times than a
# fixed number of kills per point would reach.
_KILL_WORK = dict([("a.txt", b"the task's a\n"), ("n/new.txt", b"a file the task added\n")]
                  + [("w/%d.txt" % (i,), b"work file %d\n" % (i,)) for i in (1, 2, 3)])
# "git-before" and "git-after" are each git call that WRITES, killed before it
# runs and after: a kill before a read leaves the disk as the kill after the
# write before it does, so the writes are where the states a kill can leave
# differ. "rmtree" is a removal of the copy left half done; the rest are the
# module's own functions, each a point a process can die at.
_KILL_POINTS = ("git-before", "git-after", "rmtree", "_put", "_write_aside",
                "_write_synced", "write_record", "_keep_copy", "_drop_copy", "_undo",
                "_settle", "_resume")
_GIT_WRITES = ("checkout", "rm", "add", "reset", "read-tree", "update-index")


def _kill_repo(n):
    """`(root, repo, base, head)`: base holds a.txt, b.txt, d.txt and a record;
    the head moves b.txt and the records."""
    return _av_pair(
        "advance-kill%d-" % (n,),
        {"a.txt": b"a\n", "b.txt": b"b\n", "d.txt": b"d\n", "docs/r.json": b"{}\n"},
        {"b.txt": b"b at head\n", "docs/r.json": b"{\"h\": 1}\n",
         "docs/j.jsonl": b"row at head\n"})


def _kill_fixture(n, made=None):
    """`(tree, base, head)`: a marked task tree at `base` holding the work, its
    head having moved b.txt and the record paths - cut from `made` (a
    `_kill_repo`) when given, so a run of kills shares one repository."""
    root, repo, base, head = made or _kill_repo(n)
    tree = _av_plain_tree(root, repo, base, "t%d" % (n,), dict(_KILL_WORK, **{
        "docs/r.json": b"{\"h\": 1}\n", "docs/j.jsonl": b"row at head\n"}))
    os.remove(os.path.join(tree, "d.txt"))
    _av_marked(tree, base)
    return tree, base, head


def _kill_settled(tree, head):
    """What is wrong with `tree` after a killed move and the next one: [] when
    HEAD and the marker agree on the head, the work reads back, no copy is
    left, and what an integration would carry against the marker's base -
    the tracked paths that differ from it plus the untracked ones, records
    left out - is the work and only the work. Read without touching the
    index, so the reading changes nothing it reads."""
    wrong = []
    record = M.read_provenance(tree, expect_task="T1").get("record") or {}
    marked, steps = record.get("base"), record.get("baseMoves") or []
    if _av_head(tree) != head or marked != head:
        wrong.append("HEAD %s, marker %s" % (_av_head(tree)[:7], str(marked)[:7]))
    if [s.get("to") for s in steps] != [head]:
        wrong.append("the marker records %d moves, not the one to the head" % (len(steps),))
    if _av_bytes(tree, sorted(_KILL_WORK) + ["d.txt"]) != dict(_KILL_WORK, **{"d.txt": None}):
        wrong.append("work bytes")
    carried = set(_harness.git(tree, "diff", "--name-only", "-z", str(marked)).split("\0"))
    carried |= set(_harness.git(tree, "ls-files", "-o", "--exclude-standard", "-z").split("\0"))
    carried = sorted(p for p in carried if p and not _av_record(p))
    if carried != sorted(list(_KILL_WORK) + ["d.txt"]):
        wrong.append("integration would carry %s" % (carried,))
    if os.path.exists(os.path.join(M.admin_dir(tree), M.ADVANCE_BACKUP)):
        wrong.append("a copy is left")
    return wrong


def _kill_held(tree, head, again):
    """[] when `again` HELD the tree rather than settling it, and held it
    safely: kept and said why, the copy it keeps holding the task's work byte
    for byte, and one more move over the tree changing no byte of it."""
    kept = again.get("kept") or ""
    if not kept or not again.get("error"):
        return ["neither settled nor held: kept %r" % (kept,)]
    try:
        copied, _meta, _index = M._read_copy(kept)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return ["the kept copy %s cannot be read: %s" % (kept, exc)]
    lost = [rel for rel, body in sorted(_KILL_WORK.items())
            if (copied.get(rel) or (None, None))[1:2] != (body,)]
    lost += ["d.txt"] * (copied.get("d.txt") != ("absent",))
    if lost:
        return ["the kept copy does not hold the work: %s" % (lost,)]
    rels = sorted(_KILL_WORK) + ["b.txt", "d.txt", "docs/r.json", "docs/j.jsonl"]
    before = (_av_head(tree), _av_bytes(tree, rels), _av_status(tree))
    once_more = M.advance_task_tree(tree, "T1", head, is_record=_av_record)
    if (_av_head(tree), _av_bytes(tree, rels), _av_status(tree)) != before \
            or not once_more.get("kept"):
        return ["a move over the held tree changed it: %r" % (once_more,)]
    return []


def _kill_arm(point, k, hits):
    """`(install, restore)`: count each call of `point` in `hits[point]` and
    raise `_Killed` at call `k` (0 counts only) - None when the module has no
    such point. The git points count the writing git calls, through whatever
    runner the move was handed; "rmtree" a removal of the copy, left half
    done."""
    def hit():
        hits[point] = hits.get(point, 0) + 1
        return hits[point] == k
    if point in ("git-before", "git-after"):
        # Wraps whatever runner stands when installed, so both git points
        # count at once on the counting run.
        under = []

        def runner(run):
            fn = under[-1](run)

            def dying(cwd, args, timeout=60):
                if args[:1] and args[0] not in _GIT_WRITES:
                    return fn(cwd, args, timeout)
                dies = hit()
                if dies and point == "git-before":
                    raise _Killed("before git write %d" % (k,))
                done = fn(cwd, args, timeout)
                if dies:
                    raise _Killed("after git write %d" % (k,))
                return done
            return dying

        def install():
            under.append(M._runner)
            M._runner = runner
        return install, lambda: setattr(M, "_runner", under.pop())
    if point == "rmtree":
        real_rmtree = M.shutil.rmtree

        def half(path, *rest, **kw):
            if M.ADVANCE_BACKUP not in str(path) or not hit():
                return real_rmtree(path, *rest, **kw)
            held = sorted(os.listdir(path)) if os.path.isdir(path) else []
            if held:
                os.remove(os.path.join(path, held[0]))
            raise _Killed("rmtree #%d" % (k,))
        return (lambda: setattr(M.shutil, "rmtree", half),
                lambda: setattr(M.shutil, "rmtree", real_rmtree))
    real = getattr(M, point, None)
    if real is None:
        return None

    def armed(*args, **kw):
        if hit():
            raise _Killed("%s #%d" % (point, k))
        return real(*args, **kw)
    return (lambda: setattr(M, point, armed), lambda: setattr(M, point, real))


def _armed(arms, call):
    """`call()` with every arm installed: `(killed, answer)`."""
    for install, _restore in arms:
        install()
    try:
        return False, call()
    except _Killed:
        return True, None
    finally:
        for _install, restore in reversed(arms):
            restore()


def _scribbler(tree, head):
    """A runner whose checkout of `head` succeeds and then finds the task's
    a.txt holding bytes the move never should have written - so the move's own
    check fails and its undo runs."""
    def scribble(cwd, args, timeout=60):
        done = M._git(cwd, args, timeout)
        if args[:3] == ["checkout", "-q", "--detach"] and head in args \
                and done[0] == 0:
            with open(os.path.join(tree, "a.txt"), "wb") as fh:
                fh.write(b"bytes the move should never have written\n")
        return done
    return scribble


def _first_kill(after):
    """A move killed once at its checkout of the head - before git runs it, or
    after - so the move armed next starts by reading the copy that kill left:
    undoing it, or finishing it."""
    def prepare(tree, head):
        killed, _said = _armed([], lambda: M.advance_task_tree(
            tree, "T1", head, is_record=_av_record,
            run=_first_kill_runner(head, after)))
        return killed
    return prepare


# (name, the first kill or None, a move whose check fails, may the end be a
# hold, the window armed). A hold is the answer when a kill lands where the
# tree holds bytes neither the copy nor the move wrote - inside an undo after
# git's forced checkout, or after a check that found the work scribbled over -
# and the next move keeps the copy rather than force over them. The window is
# the calls made inside one function (to the end of the run when its flag is
# set): what the plain move already arms is not armed again.
_KILL_SCENARIOS = (
    ("a move", None, False, False, None),
    ("the resume that undoes a move killed before its checkout",
     _first_kill(False), False, True, ("_resume", False)),
    ("the resume that finishes a move killed after its checkout",
     _first_kill(True), False, False, ("_resume", False)),
    ("the undo of a move whose check fails, and what follows it", None, True,
     True, ("_undo", True)),
)


def _window_arm(name, hits, marks):
    """`(install, restore)`: record in `marks` the counts `hits` held when the
    function `name` was first entered ("in") and last left ("out")."""
    under = []

    def marked(*args, **kw):
        marks.setdefault("in", dict(hits))
        try:
            return under[-1](*args, **kw)
        finally:
            marks["out"] = dict(hits)

    def install():
        under.append(getattr(M, name))
        setattr(M, name, marked)
    return install, lambda: setattr(M, name, under.pop())


def _kill_outcome(tree, head, again, may_hold):
    """`(wrong, held)` for the move made after the kills."""
    wrong = _kill_settled(tree, head)
    if not (again.get("advanced") or again.get("already")) or again.get("kept"):
        wrong.append("the next move: %s" % ((again.get("error") or (
            again.get("refusal") or {}).get("why") or "not advanced")[:200],))
    if not wrong:
        return [], False
    if not may_hold:
        return wrong, False
    hold = _kill_held(tree, head, again)
    return (wrong + hold, False) if hold else ([], True)


def _advance_kill_cases(check):
    """A move killed at any point it reaches - every call of every point, in a
    plain move, in the resume that undoes or finishes a move an earlier kill
    cut short, and in a move whose own undo runs - and then made again ends
    with the tree, its marker and what an integration would carry agreeing, or
    held with the work safe in its copy. The calls are COUNTED on an unarmed
    run first and every one of them armed in turn, so no point is capped at a
    fixed number of kills and a write added later is armed too."""
    failures, counts, kills, holds, n = [], {}, 0, [], [0]

    def move(tree, head, scribbles):
        return lambda: M.advance_task_tree(
            tree, "T1", head, is_record=_av_record,
            run=_scribbler(tree, head) if scribbles else None)
    for name, prepare, scribbles, may_hold, window in _KILL_SCENARIOS:
        n[0] += 1
        made = _kill_repo(n[0])

        def fixture():
            n[0] += 1
            return _kill_fixture(n[0], made)
        tree, _base, head = fixture()
        if prepare is not None and not prepare(tree, head):
            failures.append((name, "the first kill never landed"))
            continue
        hits, marks = {}, {}
        arms = [_kill_arm(p, 0, hits) for p in _KILL_POINTS]
        missing = [p for p, a in zip(_KILL_POINTS, arms) if a is None]
        if missing:
            failures.append((name, "no such point in the module: %s" % (missing,)))
        arms = [a for a in arms if a] + ([_window_arm(window[0], hits, marks)]
                                         if window else [])
        _armed(arms, move(tree, head, scribbles))
        if window and "in" not in marks:
            failures.append((name, "%s was never entered" % (window[0],)))
            continue
        low = marks.get("in") or {}
        high = hits if not window or window[1] else marks.get("out") or {}
        for point in _KILL_POINTS:
            counts[point] = counts.get(point, 0) + high.get(point, 0) - low.get(point, 0)
            for k in range(low.get(point, 0) + 1, high.get(point, 0) + 1):
                tree, _base, head = fixture()
                if prepare is not None and not prepare(tree, head):
                    failures.append((name, "the first kill never landed"))
                    continue
                arm = _kill_arm(point, k, {})
                killed, _said = _armed([arm], move(tree, head, scribbles))
                if not killed:
                    failures.append(("%s: %s #%d" % (name, point, k), "never reached"))
                    continue
                kills += 1
                again = M.advance_task_tree(tree, "T1", head, is_record=_av_record)
                wrong, held = _kill_outcome(tree, head, again, may_hold)
                if wrong:
                    failures.append(("%s: %s #%d" % (name, point, k), wrong))
                if held:
                    holds.append("%s #%d" % (point, k))
    unreached = sorted(p for p in _KILL_POINTS if not counts.get(p))
    check("av27 a move killed at every call of every point it reaches - before "
          "and after each git write, each write of the copy, the marker, the "
          "index and the work, half way through dropping the copy, and inside "
          "the undo, the settle and the resume after a first kill - then made "
          "again ends settled (HEAD and the marker on the head, the work intact, "
          "no copy left, an integration carrying the work and nothing else) or "
          "held with the work whole in its copy and nothing forced",
          not failures and not unreached and kills > len(_KILL_POINTS)
          and max(c for p, c in counts.items() if not p.startswith("git")) > 3,
          repr((failures[:4], len(failures), unreached, kills, counts, holds[:8])))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__worktrees.py --selftest\n")
    raise SystemExit(2)
