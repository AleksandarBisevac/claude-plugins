#!/usr/bin/env python3
"""
The cases for `_scoped_commit.py` — what the two scoped commits share.

WHAT THIS FILE IS ABOUT. `commit-task-work.py`'s task commit and its `--state`
commit each stage a fixed allow-list and refuse everything else, and the parts
that decide "refuse" - and how each path is staged, and how the index is put
back - are here rather than in that command. Its suite proves both commits end
to end; this one proves the shared parts in both directions, because a helper
that is only ever seen agreeing with its caller may be asserting nothing.

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
import _journal_io                                 # noqa: E402
import _loader                                     # noqa: E402


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
    _close_evidence_cases(check, tmp)
    _earlier_attempt_cases(check, tmp)
    _undeclared_changes_cases(check, tmp, outside)
    _readers_share_the_question_cases(check)


# --- which paths an attempt changed that no task declares ----------------------
# Three readers ask it - the task commit, the close, the writer's set-aside - and
# each used to keep its own skip list, so a restore point the commit step named and
# left out was refused by the close. The function is one; these cases hold it, and
# hold the readers to calling it.
LONG_AGO = "2000-01-01T00:00:00Z"
RESTORE = ".claude/audit-backups/audit-plan.json.bak-20261022T155614Z"


def _undeclared_changes_cases(check, tmp, outside):
    repo = _repo(tmp, "undeclared")
    for rel in ("src/mine.py", "docs/book/journal.jsonl", RESTORE,
                ".claude/state/attempts/P1.1.json", ".claude/logs/gate.log",
                "stray.txt", ".claude/audit-backups-not/y"):
        _write(os.path.join(repo, *rel.split("/")), "x\n")
    asked = getattr(M, "undeclared_changes", None)
    got, why = (("missing", "missing") if asked is None else
                asked(repo, repo, {}, None, LONG_AGO, ["src"],
                      ["docs/book"]))
    shaped = isinstance(got, dict)
    during = got.get("during") if shaped else None
    check("sc-ua1 the one function answers which paths the attempt changed that "
          "no running task declares: what an owned entry covers is `covered`, the "
          "reader's bookkeeping and the plugin's state and log directories are "
          "gone, the plugin-owned restore point is named apart with its reason "
          "and is in NONE of during/predates/undated/strays, and a directory that "
          "only begins like a plugin-owned row stays a stray: %r" % ((got, why),),
          shaped and why == ""
          and sorted(during) == [".claude/audit-backups-not/y", "stray.txt"]
          and got["strays"] == during and got["undated"] == []
          and got["predates"] == [] and got["covered"] == ["src/mine.py"]
          and [p for p, _w in got["pluginOwned"]] == [RESTORE]
          and got["pluginOwned"][0][1].startswith("a restore point")
          and RESTORE not in during + got["strays"])

    # The other direction: the same tree with the restore point as the ONLY
    # change reports nothing to refuse and still names it - a function that
    # dropped plugin-owned state in silence passes the case above, since it
    # sees only what is missing from the strays.
    quiet = _repo(tmp, "undeclared-quiet")
    _write(os.path.join(quiet, *RESTORE.split("/")), "{}\n")
    only, _w = (("missing", "") if asked is None else
                asked(quiet, quiet, {}, None, LONG_AGO, [], []))
    check("sc-ua2 a restore point alone leaves nothing undeclared and is named: %r"
          % (only,),
          isinstance(only, dict) and only["strays"] == [] and only["during"] == []
          and [p for p, _w in only["pluginOwned"]] == [RESTORE])

    blind, blind_why = (("missing", "") if asked is None else
                        asked(outside, outside, {}, None, LONG_AGO, [], []))
    check("sc-ua3 a tree git will not list is a reason, never an empty answer: %r"
          % ((blind, blind_why[:60]),),
          blind is None and blind_why.startswith("git would not describe"))

    # A START SNAPSHOT DECIDES WHEN ONE EXISTS: the restore point's bytes at the
    # start do not matter - plugin-owned state is never attributed at all.
    record = {"paths": {"stray.txt": M.path_marks(repo, ["stray.txt"])["stray.txt"]}}
    kept, _w = (("missing", "") if asked is None else
                asked(repo, repo, {}, record, LONG_AGO, ["src"], ["docs/book"]))
    check("sc-ua4 with a start snapshot, a path dirty at the same bytes predates "
          "the attempt and the plugin-owned one is still named, not attributed: %r"
          % (kept,),
          isinstance(kept, dict) and kept["predates"] == ["stray.txt"]
          and kept["during"] == [".claude/audit-backups-not/y"]
          and [p for p, _w in kept["pluginOwned"]] == [RESTORE])

    # THE CONFIGURATION FILE IS THE PLUGIN'S ONLY WHILE GIT DOES NOT TRACK IT.
    # One answer for the commit, the close and the set-aside, so the case asks
    # the function and the table placement they all read. Each shape
    # below separates a wrong implementation from the right one: a committed config
    # edited (a table that exempts it by name keeps it out of every list), an
    # untracked config (a guard that refuses all config over-fires), a
    # committed and edited `.gitignore` (the other rows stay as they were), and
    # a git that cannot answer (the loud side).
    config_rel = ".claude/audit.config.json"
    ignore_rel = ".claude/.gitignore"
    held = _repo(tmp, "undeclared-config-tracked")
    _write(os.path.join(held, *config_rel.split("/")), "{}\n")
    _write(os.path.join(held, *ignore_rel.split("/")), "x\n")
    _git(held, "add", "-A")
    _git(held, "commit", "-q", "-m", "the project commits its config")
    _write(os.path.join(held, *config_rel.split("/")), '{"edited": true}\n')
    _write(os.path.join(held, *ignore_rel.split("/")), "x\ny\n")
    edited, _w = (("missing", "") if asked is None else
                  asked(held, held, {}, None, LONG_AGO, [], []))
    fresh = _repo(tmp, "undeclared-config-untracked")
    _write(os.path.join(fresh, *config_rel.split("/")), "{}\n")
    created, _w = (("missing", "") if asked is None else
                   asked(fresh, fresh, {}, None, LONG_AGO, [], []))
    unknown_refuses = getattr(M, "UNKNOWN_REFUSES", "missing")
    unknown_protects = getattr(M, "UNKNOWN_PROTECTS", "missing")
    placed = M.plugin_owned_rels(held, held, unknown_refuses)
    set_aside = M.split_plugin_owned([config_rel, ignore_rel], placed)
    blind_rows = M.plugin_owned_rels(outside, outside, unknown_refuses)
    check("sc-ua9 a TRACKED configuration file that was edited is an undeclared "
          "change - in during and strays, in no plugin-owned list, and not in "
          "the rows the set-aside places - while the ignore file beside it, "
          "tracked and edited, stays plugin-owned; the same file untracked is "
          "named and left out; and where git cannot say it is not exempted: %r"
          % ((edited, created, placed, blind_rows),),
          isinstance(edited, dict) and isinstance(created, dict)
          and edited["during"] == [config_rel] and edited["strays"] == [config_rel]
          and [p for p, _w in edited["pluginOwned"]] == [ignore_rel]
          and set_aside[0] == [config_rel]
          and [p for p, _w in set_aside[1]] == [ignore_rel]
          and created["strays"] == [] and created["during"] == []
          and [p for p, _w in created["pluginOwned"]] == [config_rel]
          and config_rel not in [rel for rel, _w in blind_rows])

    _tracking_unknown_cases(check, held, fresh, config_rel, ignore_rel,
                            unknown_refuses, unknown_protects)


def _rel_names(rows):
    return [rel for rel, _why in rows]


def _placed(project, when_unknown):
    """The rels `plugin_owned_rels` places under `project`, or the exception
    the call raised - a case about the argument must see a refusal as data."""
    try:
        return _rel_names(M.plugin_owned_rels(project, project, when_unknown))
    except Exception as exc:
        return "%s: %s" % (exc.__class__.__name__, exc)


def _tracking_unknown_cases(check, held, fresh, config_rel, ignore_rel,
                            unknown_refuses, unknown_protects):
    """Whether git tracks the configuration file has THREE answers, and the two
    kinds of reader want opposite things from the third. The commit and the
    close REFUSE what is not known to be the plugin's own; the set-aside
    REVERTS what is not protected, so for it an unknown must protect. Each case
    below is built to separate a direction chosen by the reader from one chosen
    by the function, and from an unknown that is read as tracked or untracked
    for everyone."""
    real_run_git = M.run_git

    def blind_to_tracking(git_root, args, *rest, **kwargs):
        # Only the tracked-or-not question: the status listing, which every
        # reader needs first, is still answered.
        if list(args[:3]) == ["ls-files", "-z", "--"]:
            return None, "", "git could not be run (fixture)"
        return real_run_git(git_root, args, *rest, **kwargs)

    known = [(_placed(held, how), _placed(fresh, how))
             for how in (unknown_refuses, unknown_protects)]
    check("sc-ua12 ALLOW: where git CAN answer, the direction argument changes "
          "nothing - a tracked configuration file is placed under neither, an "
          "untracked one under both, and the ignore file under both - so a "
          "function that applies the unknown rule to every answer goes red "
          "here: %r" % (known,),
          known[0] == known[1] and config_rel not in known[0][0]
          and ignore_rel in known[0][0] and config_rel in known[0][1])

    M.run_git = blind_to_tracking
    try:
        blind = dict((label, (_placed(held, how), _placed(fresh, how)))
                     for label, how in (("refuse", unknown_refuses),
                                        ("protect", unknown_protects)))
        refusal_commit = _commit_refusal(fresh, config_rel)
        refusal_close = _close_leftovers(fresh, config_rel)
    finally:
        M.run_git = real_run_git
    refusal_commit_known = _commit_refusal(fresh, config_rel)
    refusal_close_known = _close_leftovers(fresh, config_rel)
    check("sc-ua13 where git cannot say whether the configuration file is "
          "tracked, a reader that refuses does not place it and a reader that "
          "protects does - for an edited tracked file and an untracked one "
          "alike, and the ignore file is placed either way: %r" % (blind,),
          config_rel not in blind["refuse"][0] and config_rel not in blind["refuse"][1]
          and config_rel in blind["protect"][0] and config_rel in blind["protect"][1]
          and ignore_rel in blind["refuse"][0] and ignore_rel in blind["protect"][0])

    check("sc-ua14 the direction is a required argument with two values, so no "
          "reader gets one by default or by a misspelling: %r"
          % ((_placed_without_direction(fresh), _placed(fresh, "protects")),),
          _placed_without_direction(fresh).startswith("TypeError")
          and _placed(fresh, "protects").startswith("ValueError")
          and unknown_refuses != unknown_protects)

    check("sc-ua15 the commit step, asked while git cannot say whether an "
          "untracked configuration file is tracked, refuses it as an undeclared "
          "change instead of leaving it out; asked while git can say, it leaves "
          "it out and refuses nothing: %r"
          % ((refusal_commit, refusal_commit_known),),
          config_rel in refusal_commit[0] and refusal_commit[1] == []
          and refusal_commit_known[0] == ""
          and refusal_commit_known[1] == [config_rel])

    check("sc-ua16 the close, asked the same, counts the file among what the "
          "task left behind instead of naming it plugin-owned; asked while git "
          "can say, it is named plugin-owned and left out of both lists: %r"
          % ((refusal_close, refusal_close_known),),
          refusal_close[0] == [config_rel] and refusal_close[1] == []
          and refusal_close_known[0] == []
          and refusal_close_known[1] == [config_rel])


def _placed_without_direction(project):
    try:
        M.plugin_owned_rels(project, project)
    except Exception as exc:
        return "%s: %s" % (exc.__class__.__name__, exc)
    return "answered"


def _commit_refusal(repo, config_rel):
    """`(refusal text, plugin-owned paths named)` of the commit step's
    `attempt_refusal` over `repo` with a task that declares no files."""
    task = {"id": "P1.1", "status": "in_progress", "files": [], "attempts": 1,
            "startedAt": LONG_AGO}
    manifest = {"phases": [{"id": "P1", "tasks": [task]}]}
    targets = {"paths": [], "declared": [], "records": []}
    refusal, _notes, attribution = CTW.attempt_refusal(
        manifest, task, repo, repo, {}, targets, [])
    return refusal, list((attribution or {}).get("pluginOwned") or [])


def _close_leftovers(repo, config_rel):
    """`(left, plugin-owned paths named)` of the close's
    `_uncommitted_leftovers` over `repo` with a task that declares no files."""
    task = {"id": "P1.1", "status": "in_progress", "files": [], "attempts": 1,
            "startedAt": LONG_AGO}
    plan = {"phases": [{"id": "P1", "tasks": [task]}]}
    mpath = os.path.join(repo, "docs", "audit", "audit-plan.json")
    left, during, _basis, named = AT._uncommitted_leftovers(
        repo, {}, mpath, {}, repo, plan, task)
    return left + during, [path for path, _why in named]


# --- every reader asks it ------------------------------------------------------
# NOT A COMMENT, A SCAN. The defect is a reader computing the skip list itself,
# and a reader can do that in a way no one has written yet, so the check is on
# what the readers MAY NOT NAME rather than on the instance that was found.
READERS = (("governance", "commit-task-work.py"), ("manifest", "audit-task.py"),
           ("governance", "drive-phase.py"))
# The table of plugin-owned rows and the runtime directories are asked through
# `_scoped_commit` and nowhere else. `attempt_strays` is the retired door: a
# caller handing it a `skip` is exactly the reader-owned list.
ONLY_IN_THE_SHARED_FUNCTION = ("plugin_owned_under", "PLUGIN_OWNED_IN_CLAUDE",
                               "attempt_strays")
READER_NAMES = ("logs_dir",)
HOME_OF_THE_TABLE = ("_manifest_io.py", "_scoped_commit.py")


def _names_in(source):
    """Every identifier `source` reads or writes as a Name or an attribute -
    code only, so a comment or a docstring explaining the rule cannot trip it."""
    import ast
    names = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
    return names


def reader_violations(source, shared=ONLY_IN_THE_SHARED_FUNCTION):
    """The names in `source` a reader may not use, each as often as it appears."""
    names = _names_in(source)
    return sorted(n for n in names if n in shared + READER_NAMES)


def _calls_of(source, attr):
    import ast
    return len([n for n in ast.walk(ast.parse(source))
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == attr])


def _directions_of(source, name):
    """For each call of `name` (a bare name or an attribute), the last name of
    its third argument - `UNKNOWN_REFUSES` for `_scoped_commit.UNKNOWN_REFUSES`
    - or `-` when the call passes fewer than three arguments."""
    import ast
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        called = func.attr if isinstance(func, ast.Attribute) else \
            getattr(func, "id", None)
        if called != name:
            continue
        third = node.args[2] if len(node.args) >= 3 else None
        found.append(third.attr if isinstance(third, ast.Attribute) else
                     getattr(third, "id", "?") if third is not None else "-")
    return found


# WHAT A READER MAY DO WITH THE ANSWER. The names above catch the primitives
# that were found in a reader's own skip list, and nothing else: a reader that
# post-filters `changes["during"]` with a skip of its own names none of them.
# So the second half of the scan is on the SHAPE of the use, and reads the
# answer by key only - `R["key"]`, or `R is None` - which leaves a reader no
# way to rebuild it (`dict(R)`, `R.get`, iterating it, handing it on). The
# lists that decide a refusal (`UNDECLARED_KEYS`) may then be narrowed by a
# membership test against a value the reader computes (`p in recorded`) and by
# nothing else: any other condition on them - a prefix, a call, a literal or
# upper-case constant to test against - is a rule about which paths count,
# which is the shared function's alone. `covered` is outside that set on
# purpose: it is work in flight, and the close narrows it to its own task's
# files.
RESULT_KEYS = ("during", "predates", "undated", "strays", "covered", "mixed",
               "pluginOwned", "basis")
UNDECLARED_KEYS = ("during", "predates", "undated", "strays", "mixed",
                   "pluginOwned")


def _key_of(node):
    """The constant string a Subscript indexes with, or None (3.8 wraps it in
    an `Index`; later versions do not)."""
    index = node.slice
    if index.__class__.__name__ == "Index":
        index = index.value
    import ast
    if isinstance(index, ast.Constant) and isinstance(index.value, str):
        return index.value
    return None


def _asks(node):
    import ast
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "undeclared_changes")


def _only_membership(cond):
    """True for `x in y` / `x not in y` where `y` is not a literal and not an
    upper-case name - a test against what the reader computed, not against a
    list the reader wrote."""
    import ast
    if not (isinstance(cond, ast.Compare) and len(cond.ops) == 1
            and isinstance(cond.ops[0], (ast.In, ast.NotIn))):
        return False
    other = cond.comparators[0]
    if isinstance(other, (ast.Constant, ast.List, ast.Tuple, ast.Set, ast.Dict)):
        return False
    return not (isinstance(other, ast.Name) and other.id.isupper())


def result_scan(source):
    """`{"bound": n, "violations": [...]}` over every function in `source` that
    asks `undeclared_changes`: `bound` is how many answers were taken into a
    name (so a scan that reached nothing reads as nothing, not as clean), and
    each violation names a use of the answer other than by key, an ask whose
    answer is not bound to a name, or a narrowing of an undeclared list by
    anything but a membership test."""
    import ast
    bound, found = 0, set()
    for fn in ast.walk(ast.parse(source)):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        asked = [n for n in ast.walk(fn) if _asks(n)]
        if not asked:
            continue
        names, took = set(), []
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and _asks(node.value):
                took.append(node.value)
                target = node.targets[0]
                if isinstance(target, ast.Tuple) and target.elts:
                    target = target.elts[0]
                if isinstance(target, ast.Name):
                    names.add(target.id)
        bound += len(names)
        for node in asked:
            if not any(node is t for t in took):
                found.add("line %d: the answer is not bound to a name"
                          % (node.lineno,))
        parents = {}
        for node in ast.walk(fn):
            for child in ast.iter_child_nodes(node):
                parents[child] = node

        def list_read(node, tainted):
            if isinstance(node, ast.Subscript) \
                    and isinstance(node.value, ast.Name) \
                    and node.value.id in names \
                    and _key_of(node) in UNDECLARED_KEYS:
                return True
            return isinstance(node, ast.Name) and node.id in tainted

        tainted = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name) \
                    and list_read(node.value, ()):
                tainted.add(node.targets[0].id)
        for node in ast.walk(fn):
            if isinstance(node, ast.Name) and node.id in names \
                    and isinstance(node.ctx, ast.Load):
                up = parents.get(node)
                by_key = (isinstance(up, ast.Subscript) and up.value is node
                          and _key_of(up) in RESULT_KEYS)
                is_none = (isinstance(up, ast.Compare) and up.left is node
                           and all(isinstance(o, (ast.Is, ast.IsNot))
                                   for o in up.ops)
                           and all(isinstance(c, ast.Constant)
                                   and c.value is None for c in up.comparators))
                if not (by_key or is_none):
                    found.add("line %d: the answer `%s` is used other than by "
                              "key" % (node.lineno, node.id))
            if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp,
                                 ast.DictComp)):
                for gen in node.generators:
                    if list_read(gen.iter, tainted) and not all(
                            _only_membership(c) for c in gen.ifs):
                        found.add("line %d: an undeclared list is narrowed by "
                                  "a rule of the reader's own" % (node.lineno,))
            if isinstance(node, ast.For) and list_read(node.iter, tainted) \
                    and any(isinstance(n, ast.Continue)
                            for stmt in node.body for n in ast.walk(stmt)):
                found.add("line %d: an undeclared list is skipped through by "
                          "the reader" % (node.lineno,))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "filter" \
                    and any(list_read(a, tainted) for a in node.args):
                found.add("line %d: an undeclared list goes through filter()"
                          % (node.lineno,))
    return {"bound": bound, "violations": sorted(found)}


# The scripts/ walk of the table's home: how much of the tree it must reach
# before a clean verdict means anything. Well above the three readers and the
# two home modules, and well below the tree - the floor exists to refuse a walk
# that reached a handful of files, not to count the tree.
SCAN_FLOOR = 60


def scan_gaps(scanned):
    """Why a walk that read the `.py` files named in `scanned` cannot vouch for
    the tree: it read none, read fewer than `SCAN_FLOOR`, or missed a module the
    question is about."""
    gaps = []
    if not scanned:
        gaps.append("it read no `.py` file at all")
    elif len(scanned) < SCAN_FLOOR:
        gaps.append("it read %d `.py` files, fewer than the floor of %d"
                    % (len(scanned), SCAN_FLOOR))
    gaps.extend("it never reached %s" % (name,)
                for name in HOME_OF_THE_TABLE + tuple(n for _f, n in READERS)
                if name not in scanned)
    return gaps


def _readers_share_the_question_cases(check):
    import _output
    sources = {}
    for folder, name in READERS:
        with io.open(os.path.join(_output.SCRIPTS_DIR, folder, name),
                     encoding="utf-8") as fh:
            sources[name] = fh.read()
    found = dict((name, reader_violations(src)) for name, src in sources.items())
    check("sc-ua5 none of the three readers - the task commit, the close, the "
          "set-aside - names the plugin-owned table, the runtime-directory "
          "lookup or the retired door that took a caller's skip list: %r"
          % (found,), all(v == [] for v in found.values()))
    asks = dict((name, _calls_of(sources[name], "undeclared_changes"))
                for name in ("commit-task-work.py", "audit-task.py"))
    places = _calls_of(sources["drive-phase.py"], "plugin_owned_rels")
    check("sc-ua6 the commit and the close each ask `undeclared_changes` exactly "
          "once - a second ask in one reader is a second answer - and the "
          "set-aside asks the shared table: %r" % ((asks, places),),
          asks == {"commit-task-work.py": 1, "audit-task.py": 1} and places == 1)

    # WHICH WAY AN UNKNOWN GOES IS NAMED AT EVERY CALL, tree-wide. The direction
    # is a required argument, but a reader could still pass the wrong constant;
    # the commit and the close reach the rows only through `undeclared_changes`
    # (refusing), the set-aside asks directly (protecting), and nobody else asks.
    directions = {}
    for dirpath, _dirs, files in os.walk(_output.SCRIPTS_DIR):
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            with io.open(os.path.join(dirpath, name), encoding="utf-8") as fh:
                asked_with = _directions_of(fh.read(), "plugin_owned_rels")
            if asked_with:
                directions[name] = asked_with
    flipped = sources["drive-phase.py"].replace("_scoped_commit.UNKNOWN_PROTECTS",
                                                "_scoped_commit.UNKNOWN_REFUSES")
    bare = sources["drive-phase.py"].replace(
        'ctx["gitRoot"], _scoped_commit.UNKNOWN_PROTECTS))', 'ctx["gitRoot"]))')
    check("sc-ua17 under scripts/, `plugin_owned_rels` is asked in two places and "
          "each names its direction: the shared function refuses on an unknown, "
          "the set-aside protects; the scan reads a flipped constant and a "
          "missing argument as such (mutations landed: %s): %r"
          % (flipped != sources["drive-phase.py"]
             and bare != sources["drive-phase.py"], directions),
          directions == {"_scoped_commit.py": ["UNKNOWN_REFUSES"],
                         "drive-phase.py": ["UNKNOWN_PROTECTS"]}
          and flipped != sources["drive-phase.py"]
          and _directions_of(flipped, "plugin_owned_rels") == ["UNKNOWN_REFUSES"]
          and bare != sources["drive-phase.py"]
          and _directions_of(bare, "plugin_owned_rels") == ["-"])

    # THE SCAN MUST BE ABLE TO FAIL, in both directions: a reader that computes
    # the list itself is named, and the shared spelling is not.
    own = ("def f(project):\n    for p, w in _mio.plugin_owned_under(project):\n"
           "        pass\n    return hc.logs_dir(root, {})\n")
    shared_ok = ("def f():\n    return _scoped_commit.undeclared_changes(1)\n"
                 "# plugin_owned_under named in a comment is not code\n")
    check("sc-ua7 the scan names a reader's own skip list and passes the shared "
          "call: %r" % ((reader_violations(own), reader_violations(shared_ok)),),
          reader_violations(own) == ["logs_dir", "plugin_owned_under"]
          and reader_violations(shared_ok) == [])

    # THE TABLE'S HOME, tree-wide: whoever else reads the rows is a reader with a
    # list of its own, whichever file it sits in.
    scanned, outside = [], []
    for dirpath, _dirs, files in os.walk(_output.SCRIPTS_DIR):
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            scanned.append(name)
            if name in HOME_OF_THE_TABLE:
                continue
            with io.open(os.path.join(dirpath, name), encoding="utf-8") as fh:
                if "plugin_owned_under" in _names_in(fh.read()):
                    outside.append(name)
    # A WALK THAT READ NOTHING FINDS NOTHING, and `outside == []` over an empty
    # walk is the same green as over the whole tree: the verdict also stands on
    # what was read, and `scan_gaps` is shown to refuse an empty walk and a
    # short one.
    gaps = scan_gaps(scanned)
    check("sc-ua8 under scripts/, only the table's own module and the shared "
          "function read `plugin_owned_under`, over a walk that read %d `.py` "
          "files, reached both home modules and every reader (gaps: %r): %r"
          % (len(scanned), gaps, outside),
          outside == [] and gaps == []
          and scan_gaps([]) != [] and scan_gaps(["a.py", "b.py", "c.py"]) != []
          and len(scan_gaps(scanned[:SCAN_FLOOR - 1])) >= 1)

    # THE SHAPE OF THE USE, over the two readers that take the answer. `bound`
    # must be one each: a scan that reached no ask would report no violation.
    taken = dict((name, result_scan(sources[name]))
                 for name in ("commit-task-work.py", "audit-task.py"))
    check("sc-ua10 the commit and the close each take the answer into one name "
          "and read it by key only - no rebuilding it, no condition of their "
          "own on an undeclared list: %r" % (taken,),
          all(t["bound"] == 1 and t["violations"] == [] for t in taken.values()))

    # THE SCAN MUST SEE WHAT THE NAME LIST CANNOT. Each mutation is made in the
    # real source of the commit step and shown to have landed; the first is the
    # post-filter of `during` with a skip of its own, which names none of the
    # retired primitives and so passed sc-ua5.
    real = sources["commit-task-work.py"]
    anchor = 'during = strays["during"]'
    own_skip = real.replace(
        anchor, 'during = [p for p in strays["during"] '
                'if not p.startswith(".claude/")]')
    rebuilt = real.replace(anchor, 'during = dict(strays)["during"]')
    listed = real.replace(anchor, 'during = [p for p in strays["during"] '
                                  'if p not in SKIP_LIST]')
    through = real.replace(anchor, 'during = list(filter(lambda p: p, '
                                   'strays["during"]))')
    allowed = real.replace(anchor, 'during = [p for p in strays["during"] '
                                   'if p not in mine_elsewhere]')
    landed = real.count(anchor) == 1 and all(
        text != real for text in (own_skip, rebuilt, listed, through, allowed))
    old = reader_violations(own_skip)
    new = dict((label, result_scan(text)["violations"])
               for label, text in (("own_skip", own_skip), ("rebuilt", rebuilt),
                                   ("listed", listed), ("through", through),
                                   ("allowed", allowed)))
    check("sc-ua11 a reader post-filtering `strays[\"during\"]` with a skip of "
          "its own is named by the shape scan and was NOT by the name scan; so "
          "are rebuilding the answer, testing against an upper-case list and "
          "filter(); a membership test against a computed value is not "
          "(mutations landed: %s, name scan said %r): %r"
          % (landed, old, new),
          landed and old == []
          and all(len(new[k]) >= 1 for k in
                  ("own_skip", "rebuilt", "listed", "through"))
          and new["allowed"] == [])


# --- the span an attempt's commits are read over -------------------------------
NOT_ANCESTOR_CLAUSE = ("a start head that is not an ancestor of HEAD claims no "
                       "earlier commit and says so")
# The callers are entry points, loaded once here: the cases below are about the
# span every one of them reads, so they drive each of them over one fixture.
AT = _loader.load_script("audit-task.py", "at_for_scoped_commit")
CTW = _loader.load_script("commit-task-work.py", "ctw_for_scoped_commit")


def _span(reader, *args, **kwargs):
    """`reader(*args)`, or `("missing", None)` when the module holds no such
    function - a case over a reader that is not there fails its assertion
    rather than ending the run."""
    if reader is None:
        return "missing", None
    return reader(*args, **kwargs)


def _earlier_attempt_cases(check, tmp):
    """`attempt_span` names a span only when the recorded start head is an
    ancestor of the span's end. An object git still holds after a rebase or a
    reset is not one, and `start..HEAD` over it lists commits that are not the
    attempt's."""
    repo = _repo(tmp, "earlier")
    start = _git(repo, "rev-parse", "HEAD").strip()
    _write(os.path.join(repo, "keep", "a.txt"), "changed\n")
    _git(repo, "commit", "-q", "-am", "the attempt's work")
    work = _git(repo, "rev-parse", "HEAD").strip()
    # A commit git holds that no branch reaches: what a rebased-away head is.
    tree = _git(repo, "rev-parse", "HEAD^{tree}").strip()
    stray = _git(repo, "commit-tree", tree, "-p", start, "-m",
                 "left behind").strip()

    task = {"id": "P1.1", "attempts": 1, "files": ["keep/a.txt"]}
    plan = {"phases": [{"id": "P1", "tasks": [task]}]}
    reader = getattr(M, "attempt_span", None)

    honest = _span(reader, repo, repo, plan, task, ["keep/a.txt"], start)
    check("sc-ea1 ALLOW: a start head that IS an ancestor of HEAD still lists the "
          "commits since it that changed a declared file, and says nothing - the "
          "case that goes red if the ancestor test is made unconditional: %r"
          % (honest,),
          honest == ([("keep/a.txt", work)], ""))
    stale = _span(reader, repo, repo, plan, task, ["keep/a.txt"], stray)
    # `None`, not `[]`: an empty span is "the attempt committed nothing", which
    # a no-change close accepts; over a rebased-away start head the span is
    # unread, and reading it as empty let a close stand on work it never saw.
    check("sc-ea2 %s - as cannot-tell (None), never as an empty span: %r"
          % (NOT_ANCESTOR_CLAUSE, stale),
          stale[0] is None and "not an ancestor" in str(stale[1])
          and stray[:12] in str(stale[1]))
    gone = _span(reader, repo, repo, plan, task, ["keep/a.txt"], "0" * 40)
    check("sc-ea3 a start head git does not hold at all still claims nothing and "
          "says nothing, as before: %r" % (gone,), gone == ([], ""))
    other = dict(task, id="P1.2", commit=work)
    plan_other = {"phases": [{"id": "P1", "tasks": [task, other]}]}
    foreign = _span(reader, repo, repo, plan_other, task, ["keep/a.txt"], start)
    check("sc-ea4 a commit another task of the plan records as its own is left "
          "out of the span even when a start head bounds it - it is that task's "
          "work, whichever caller asks: %r" % (foreign,),
          foreign == ([], ""))
    _attempt_span_caller_cases(check, repo, start, work, stray)
    _declared_work_cases(check, tmp)


def _declared_work_cases(check, tmp):
    """`declared_work` is the one reading of which declared entries are work:
    the plan's spelling beside git's, a line suffix dropped, an entry outside
    the git root or under a record left out, each entry once, in plan order."""
    project = os.path.join(tmp, "dw-checkout", "app")
    os.makedirs(project)
    git_root = os.path.dirname(project)
    task = {"id": "P1.1", "files": [
        "src/b.py:10-20", "src/a.py", "src/b.py", "../../outside.txt",
        "docs/audit/phases/P1.json", "  "]}
    reader = getattr(M, "declared_work", None)
    got = _span(reader, task, project, git_root, ["app/docs/audit"])
    check("sc-dw1 the task's declared work is read once: plan spelling with its "
          "git-root path, the line suffix dropped, each entry once in plan "
          "order, an entry outside the git root and one under a record left "
          "out: %r" % (got,),
          got == [("src/b.py", "app/src/b.py"), ("src/a.py", "app/src/a.py")])
    # The readers it replaced, by name: a second copy left beside the one
    # reading is how the two came to differ in the first place.
    left = [name for mod, name in ((M, "_declared_names"),
                                   (CTW, "declared_names"),
                                   (AT, "_declared_work"),
                                   (M, "earlier_attempt_commits"),
                                   (AT, "_attempt_commits_read"),
                                   (AT, "_attempt_commits"))
            if hasattr(mod, name)]
    check("sc-dw2 no second reader of the declared work or of the attempt span "
          "is left beside the one each caller now goes through: %r" % (left,),
          left == [])


def _attempt_span_caller_cases(check, repo, start, work, stray):
    """Every caller reading the span over one start head off HEAD's history.

    The commit's (`commit-task-work.earlier_attempt`), the `done --commit`
    close's (`audit-task._close_evidence_refusal`) and the `done --no-change`
    close's (`audit-task._no_change_moves`): each must answer cannot-tell -
    never an empty span - and carry the reason naming the start head, since
    each reads the one span."""
    _write(os.path.join(repo, "other.txt"), "no declared file\n")
    _git(repo, "add", "other.txt")
    _git(repo, "commit", "-q", "-m", "a commit touching nothing declared")
    end = _git(repo, "rev-parse", "HEAD").strip()
    task = {"id": "P1.1", "attempts": 1, "files": ["keep/a.txt"],
            "status": "in_progress"}
    phase = {"id": "P1", "tasks": [task]}
    plan = {"phases": [phase]}
    rows = [{"action": "task.start",
             "details": {"taskId": "P1.1", "attempt": 1, "commit": stray}}]
    mpath = os.path.join(repo, "docs", "audit", "audit-plan.json")

    def close(head):
        return AT._close_evidence_refusal(
            repo, mpath, repo, task, end, True, [],
            attempt={"phase": phase, "plan": plan, "startHead": head,
                     "records": []})

    earlier = getattr(CTW, "earlier_attempt", None)
    committed = _span(earlier, plan, task, repo, repo, rows, ["keep/a.txt"])
    closed, closed_honest = close(stray), close(start)
    moved, notes = AT._no_change_moves(repo, repo, phase, task, plan=plan,
                                       start_head=stray)
    # Each caller is asked for the CANNOT-TELL answer, not an empty one: the
    # commit caller hands back None (its caller refuses on it), the done
    # --commit close refuses naming the start head, and the no-change reader
    # hands back None with the start head in its note, which its caller turns
    # into a refusal. An empty list in either None slot is the defect this
    # case exists for - an unread span read as "the attempt committed nothing".
    check("sc-as1 a start head off HEAD's history makes the one attempt-span "
          "reader claim no commit and say why, for both the commit and the done "
          "--commit callers (and the no-change close beside them), as "
          "cannot-tell naming the start head: commit %r, done --commit %r, "
          "no-change %r %r" % (committed, closed[:300], moved, notes),
          committed[0] is None and "not an ancestor" in str(committed[1])
          and stray[:12] in str(committed[1])
          and "not an ancestor" in closed and stray[:12] in closed
          and moved is None
          and any("not an ancestor" in n and stray[:12] in n for n in notes))
    # SECOND-DIRECTION CASE, for a reader made to refuse every start head: an
    # ancestor start head whose span holds the work still closes, and still
    # hands the commit caller that work's commit.
    honest = _span(earlier, plan, task, repo, repo,
                   [dict(rows[0], details=dict(rows[0]["details"],
                                               commit=start))], ["keep/a.txt"])
    check("sc-as2 ALLOW: the same callers over an ancestor start head claim the "
          "work's commit and refuse nothing: commit %r, done --commit %r"
          % (honest, closed_honest[:300]),
          honest == ([work], "") and closed_honest == "")


# --- what a close stands on ----------------------------------------------------
def _close_evidence_cases(check, tmp):
    """`close_evidence_refusal`'s `declared`, `tree` and `any_red_first`, asked
    directly: each case pairs the parameter's refusal with the call it must
    leave quiet, so neither an inert parameter nor one that always refuses
    passes."""
    project = os.path.join(tmp, "ce-project")
    os.makedirs(project)
    task = {"id": "P1.1", "files": ["src/a.py:1-3", "src/a.py", "src/b.py"],
            "tests": {"add": []}}
    proved = {"redFirst": {"status": "could-not-prove", "basis": "b"},
              "outcome": {"descriptive": "left in another tree"}}
    skipped = {"redFirst": {"status": M.RED_FIRST_NOT_ATTEMPTED, "basis": "b"},
               "outcome": {"descriptive": "blocked"}}

    loud = M.close_evidence_refusal(task, project, proved, False,
                                    declared=["src/a.py"], tree=project,
                                    any_red_first=True)
    unfiled = M.close_evidence_refusal(task, project, None, False,
                                       any_red_first=True)
    check("sc-ce1 `any_red_first` refuses an unchanged declared set beside "
          "`could-not-prove` and with no return filed; the first names "
          "`declared` (not the task's whole list), `tree` with the kept-tree "
          "pointer, and the red-first word: %r" % ((loud[:400], unfiled[:300]),),
          loud.count("(src/a.py)") == 1 and "src/b.py" not in loud
          and loud.count(project) == 2
          and "only plan and record files" in loud
          and "kept task tree" in loud and "`could-not-prove`" in loud
          and "--no-change" in loud
          and unfiled and "red-first" not in unfiled and "--no-change" in unfiled)

    # SECOND DIRECTION, for `any_red_first` read as always on: without it the
    # same `could-not-prove` return is no refusal, and `not-attempted` still is.
    narrow = M.close_evidence_refusal(task, project, proved, False)
    narrow_na = M.close_evidence_refusal(task, project, skipped, False)
    check("sc-ce2 without `any_red_first` a `could-not-prove` return over an "
          "unchanged declared set closes, and `not-attempted` still refuses: %r"
          % ((narrow, narrow_na[:200]),),
          narrow == "" and "`not-attempted`" in narrow_na)

    # OVER-FIRE DIRECTION: a changed declared set, or one that could not be
    # read, never refuses whatever the flag says.
    changed = M.close_evidence_refusal(task, project, proved, True,
                                       declared=["src/a.py"], tree=project,
                                       any_red_first=True)
    unread = M.close_evidence_refusal(task, project, proved, None,
                                      any_red_first=True)
    check("sc-ce3 ALLOW: `any_red_first` over a changed declared set, or one "
          "whose change could not be read, refuses nothing: %r"
          % ((changed, unread),), changed == "" and unread == "")

    default = M.close_evidence_refusal(task, project, proved, False,
                                       any_red_first=True)
    empty = M.close_evidence_refusal(task, project, proved, False, declared=[],
                                     any_red_first=True)
    check("sc-ce4 `declared` omitted names the task's own files once each, "
          "line suffix dropped; an empty `declared` says so; no `tree` names "
          "no tree: %r" % ((default[:300], empty[:200]),),
          "(src/a.py, src/b.py)" in default and default.count("src/a.py") == 1
          and ":1-3" not in default
          and "none outside the plan's records" in empty
          and project not in default and "kept task tree" not in default)


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
    # A PROSE PARAGRAPH LAST - a task's filed `claims` block, with no co-author
    # line after it - must not take the row trailer: git reads trailers from the
    # final paragraph only, so the nonce joined onto prose is a nonce no reader
    # finds. The block is the one a commit carries verbatim, so its bytes are
    # asserted untouched too.
    claims = "claims:\n1 audit-task.py:4700 is the refusal\n2 n/a - no check"
    prose = M.with_row_trailer(["chore(x): a subject", claims], "n3")
    framed = M.with_row_trailer(["chore(x): a subject", claims, coauthor], "n4")
    check("sc25b the row trailer keeps a paragraph of trailers: after a prose "
          "paragraph it is a paragraph of its own and git reads it, the prose "
          "kept byte-identical; with a co-author line last it joins that line "
          "as before: %r / %r"
          % (_trailers(repo, "\n\n".join(prose)), prose),
          _trailers(repo, "\n\n".join(prose)) == [M.row_trailer("n3")]
          and prose[1] == claims and len(prose) == 3
          and _trailers(repo, "\n\n".join(framed)) == [coauthor,
                                                        M.row_trailer("n4")]
          and framed[1] == claims and len(framed) == 3)

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

    # A HOOK THAT OPENS WITH A PROGRESS PREAMBLE and names the failing check last,
    # as lint-staged does: a refusal reason cut at its head keeps the preamble and
    # loses the check, so the withdrawn row could not say what failed. The reason
    # is run through the journal's own details normaliser, because "the row keeps
    # it" is a claim about the stored block and not about the string handed to it.
    hooks = os.path.join(repo, ".git", "hooks")
    preamble = "".join("[STARTED] step %d of the staged-files pipeline\n" % (i,)
                       for i in range(40))
    verdict = "\u2716 prettier --check found issues in lib/store.ts"
    _write(os.path.join(hooks, "pre-commit"),
           "#!/bin/sh\ncat >&2 <<'EOF'\n%s%s\nEOF\nexit 1\n" % (preamble, verdict))
    os.chmod(os.path.join(hooks, "pre-commit"), 0o755)
    del withdrawn[:]
    done = M.commit_with_rows(repo, ["keep/a.txt"],
                              M.classify(repo, [("keep/a.txt", True)]),
                              ["chore: a"], lambda paths: "foreign", rows,
                              lambda nonce, why: withdrawn.append(why) or "w")
    stored = _journal_io.normalise_details({"reason": withdrawn[0]}) if withdrawn \
        else {}
    check("sc30 a commit refused by a hook whose 2 KB output starts with a "
          "progress preamble and ends with the failing check records a "
          "withdrawn row whose details name lib/store.ts - the preamble does not "
          "crowd the check out, and the cut says how much it dropped: %r / %r"
          % (done["refused"][-300:], stored),
          len(preamble + verdict) > 1800 and not done["committed"]
          and len(withdrawn) == 1 and "lib/store.ts" in done["refused"]
          and "lib/store.ts" in (stored or {}).get("reason", "")
          and "chars elided" in done["refused"])

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
