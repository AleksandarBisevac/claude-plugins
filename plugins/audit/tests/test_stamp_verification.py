#!/usr/bin/env python3
"""
The cases for `stamp-verification.py` — the door, not the arithmetic.

`test__tree_stamp.py` proves the identity fields and the three-word comparison
against a real repository, one moved thing at a time. What is left for the door is
everything a caller can get wrong, and everything the exit code promises.

- **Three answers need three exit codes.** `unestablished` sharing 0 makes an
  ungradeable comparison read as "unchanged", which is the false clean sheet the
  whole design refuses; sharing 1 makes it read as "the tree moved" and sends a
  reader to re-run work that may be perfectly current. `sv5` reads the map off the
  module's own verdict words, so a fourth verdict cannot be added without a code.
- **A stamp that cannot be READ is not a stamp that matched.** Every refusal here
  exits 2, and `sv13` is the case that asserts the one thing that must never
  happen: an unreadable stamp coming back 0.
- **The scope rides inside the stamp.** `compare` refuses a `--files`/`--task` of
  its own, because a comparison handed a second file set silently answers about a
  different question — which is the held-model-of-state failure this command was
  built for, reappearing inside the tool meant to catch it.
- **`--task` reads the plan.** A hand-typed file list beside a manifest is the
  same failure one step earlier, so the door takes the declared scope off the task
  and `sv8` asserts both routes reach the same digest.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import io
import json
import os
import subprocess
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
import _output                                     # noqa: E402
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _tree_stamp                                 # noqa: E402

M = _loader.load_script("stamp-verification.py", modname="stamp_verification")


def _git(repo, *args):
    """A git command that must succeed, with the identity a fresh runner lacks."""
    subprocess.run(["git", "-C", repo,
                    "-c", "user.email=fixture@example.invalid",
                    "-c", "user.name=fixture",
                    "-c", "commit.gpgsign=false"] + list(args),
                   check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)


def _write(path, text):
    with open(path, "w") as fh:
        fh.write(text)


def _seeded_repo(prefix):
    root = _harness.fixture_root(prefix)
    subprocess.run(["git", "init", "-q", root], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.makedirs(os.path.join(root, "src"))
    _write(os.path.join(root, "src", "mine.py"), "v = 1\n")
    _git(root, "add", "src/mine.py")
    _git(root, "commit", "-q", "-m", "seed")
    return root


def _run(argv, stdin_text=None):
    """`(code, text)` from one invocation, stderr silenced the way `run()` does.

    The door writes its refusals to stderr, so a case that only collected stdout
    would grade a refusal by its exit code alone and could not tell one refusal
    from another."""
    lines = []
    held = sys.stderr
    sys.stderr = io.StringIO()
    try:
        code = M.main(argv, out=lines.append,
                      stdin=io.StringIO(stdin_text or ""))
        errs = sys.stderr.getvalue()
    finally:
        sys.stderr = held
    return code, "\n".join(lines) + errs


MANIFEST = {
    "meta": {"version": 3, "repo": "fixture", "title": "fixture",
             "createdISO": "2026-01-01T00:00:00Z", "developmentBranch": "main",
             "branchPrefix": "audit", "gitRoot": ".",
             "buildCommands": {"test": "true"}},
    "phases": [{"id": "P1", "title": "one", "status": "in_progress",
                "tasks": [{"id": "P1.1", "title": "t", "status": "pending",
                           "files": ["src/mine.py"]},
                          {"id": "P1.2", "title": "u", "status": "pending",
                           "files": []}]}]}


# --- take: the stamp, and where its scope comes from --------------------------
def _take_cases(check):
    repo = _seeded_repo("stamp-door-take-")
    code, text = _run(["take", "--project", repo, "--files", "src/mine.py"])
    check("sv1 `take` exits 0 and prints the one line a report or a commit "
          "message carries - the token is the whole product, so a run that "
          "printed the fields and not the line would have produced nothing to "
          "carry: exit=%r" % (code,),
          code == 0 and _tree_stamp.STAMP_TOKEN in text)

    stamp, problem = _tree_stamp.parse_stamp(text)
    check("sv2 ...and what it printed parses back, which is the only property "
          "that makes the line worth printing: %r" % (problem,),
          problem is None and stamp.get("scope") == ["src/mine.py"])

    man_path = os.path.join(repo, "audit-plan.json")
    _write(man_path, json.dumps(MANIFEST))
    code_task, text_task = _run(["take", "--project", repo,
                                 "--manifest", man_path, "--task", "P1.1"])
    by_task, _p = _tree_stamp.parse_stamp(text_task)
    check("sv3 `--task` takes the declared scope OFF THE PLAN, and reaches the "
          "same digest a hand-typed list does. The hand-typed list is the held "
          "model of state this command is about, so the plan has to be a route: "
          "exit=%r" % (code_task,),
          code_task == 0
          and by_task.get("scope") == stamp.get("scope")
          and by_task.get("scopeDigest") == stamp.get("scopeDigest"))

    code_empty, text_empty = _run(["take", "--project", repo,
                                   "--manifest", man_path, "--task", "P1.2"])
    empty, _p2 = _tree_stamp.parse_stamp(text_empty)
    check("sv4 a task that declares NO files is a stamp with no scope digest and "
          "a sentence saying why - not an error, and not a digest over an empty "
          "list, which would compare equal across every such run and read as "
          "agreement: exit=%r" % (code_empty,),
          code_empty == 0 and empty.get("scope") == []
          and empty.get("scopeDigest") is None
          and "declares no files" in text_empty)

    both = _run(["take", "--project", repo, "--files", "src/mine.py",
                 "--manifest", man_path, "--task", "P1.1"])
    no_man = _run(["take", "--project", repo, "--task", "P1.1"])
    missing = _run(["take", "--project", repo, "--manifest", man_path,
                    "--task", "P9.9"])
    unread = _run(["take", "--project", repo, "--manifest",
                   os.path.join(repo, "nope.json"), "--task", "P1.1"])
    check("sv5 every way of naming the wrong work is a refusal with its own "
          "sentence and exit 2 - two scopes at once, a task with no manifest, a "
          "task that is not there (the message lists what is), and a manifest "
          "that will not read: %r"
          % ([c for c, _t in (both, no_man, missing, unread)],),
          [c for c, _t in (both, no_man, missing, unread)] == [2, 2, 2, 2]
          and "P1.1" in missing[1])


# --- compare: three answers, three exit codes ---------------------------------
def _compare_cases(check):
    repo = _seeded_repo("stamp-door-compare-")
    _code, taken = _run(["take", "--project", repo, "--files", "src/mine.py"])

    quiet_code, quiet_text = _run(["compare", "--project", repo], stdin_text=taken)
    check("sv6 THE ALLOW CASE: an untouched tree is `current` and exits 0, read "
          "off STDIN because a commit message or a report is what a caller "
          "already has in hand. A stamp that cried stale here would be ignored "
          "within a day: exit=%r" % (quiet_code,),
          quiet_code == 0 and _tree_stamp.CURRENT in quiet_text)

    _write(os.path.join(repo, "src", "mine.py"), "v = 2\n")
    stale_code, stale_text = _run(["compare", "--project", repo,
                                   "--stamp", taken])
    check("sv7 an edited tree is `stale`, exits 1, and NAMES the field that "
          "moved. 'Stale' with no cause sends the reader back to re-run "
          "everything: exit=%r" % (stale_code,),
          stale_code == M.E_STALE and _tree_stamp.STALE in stale_text
          and "scopeDigest" in stale_text)

    plain = _harness.fixture_root("stamp-door-nogit-")
    _dead_code, dead = _run(["take", "--project", plain])
    dead_code, dead_text = _run(["compare", "--project", plain], stdin_text=dead)
    check("sv8 THE THIRD ANSWER: a directory git cannot describe is "
          "`unestablished` on its OWN exit code, neither 0 nor 1. Sharing 0 "
          "would make an ungradeable comparison read as unchanged; sharing 1 "
          "would send a reader to re-run work that may be current: exit=%r"
          % (dead_code,),
          dead_code == M.E_UNESTABLISHED
          and _tree_stamp.UNESTABLISHED in dead_text
          and _tree_stamp.CURRENT not in dead_text.splitlines()[0])

    check("sv9 the three codes really are three, and every verdict the module "
          "declares has one - read off `_tree_stamp`'s own words, so a fourth "
          "verdict cannot be added and left sharing a neighbour's code: %r"
          % (M.EXIT_FOR,),
          set(M.EXIT_FOR) == set(_tree_stamp.VERDICT_HELP)
          and len(set(M.EXIT_FOR.values())) == len(M.EXIT_FOR)
          and M.EXIT_FOR[_tree_stamp.CURRENT] == 0)

    scoped = _run(["compare", "--project", repo, "--files", "src/mine.py"],
                  stdin_text=taken)
    tasked = _run(["compare", "--project", repo, "--task", "P1.1"],
                  stdin_text=taken)
    check("sv10 `compare` refuses a scope of its own. The scope rides inside the "
          "stamp, and a second one here would let the comparison answer about a "
          "different file set than the stamp was taken over - this command's own "
          "defect, reappearing inside it: %r"
          % ([c for c, _t in (scoped, tasked)],),
          [c for c, _t in (scoped, tasked)] == [2, 2])

    both_sources = _run(["compare", "--project", repo, "--stamp", taken,
                         "--stamp-file", os.path.join(repo, "nope.txt")])
    no_file = _run(["compare", "--project", repo, "--stamp-file",
                    os.path.join(repo, "nope.txt")])
    garbage = _run(["compare", "--project", repo], stdin_text="gates are green\n")
    check("sv13 A STAMP THAT CANNOT BE READ IS NOT A STAMP THAT MATCHED. Two "
          "sources, a file that is not there, and a document carrying no token "
          "all exit 2 - never 0, which is the one answer that would let the "
          "claim go on being cited: %r"
          % ([c for c, _t in (both_sources, no_file, garbage)],),
          [c for c, _t in (both_sources, no_file, garbage)] == [2, 2, 2])


# --- the machine-readable half and the command's own shape --------------------
def _shape_cases(check):
    repo = _seeded_repo("stamp-door-json-")
    code, text = _run(["take", "--project", repo, "--files", "src/mine.py",
                       "--json"])
    payload = json.loads(text)
    check("sv11 `take --json` carries the stamp, the full basis for every field, "
          "and the line to paste - a caller that got only the digests would have "
          "to re-derive the sentence that bounds them: exit=%r" % (code,),
          code == 0 and set(payload) == set(("stamp", "state", "line"))
          and payload["line"].startswith(_tree_stamp.STAMP_TOKEN)
          and all(payload["state"].get(key)
                  for _f, key, _l in _tree_stamp.FIELD_LIMIT))

    _cmp_code, cmp_text = _run(["compare", "--project", repo, "--json"],
                               stdin_text=payload["line"])
    verdict = json.loads(cmp_text)
    check("sv12 `compare --json` carries the verdict AND the per-field words it "
          "was assembled from, so a caller can act on which part moved rather "
          "than on the one word: %r" % (verdict["verdict"],),
          verdict["verdict"] == _tree_stamp.CURRENT
          and [e["field"] for e in verdict["fields"]]
          == list(_tree_stamp.IDENTITY_FIELDS))

    bad_verb = _run(["stamp"])
    check("sv14 a verb this command does not have is a usage error and not a "
          "silent default - guessing which of two actions was meant is the "
          "guess this whole command exists to stop: %r" % (bad_verb[0],),
          bad_verb[0] == M.E_USAGE)

    coverage = _output.selftest_coverage()
    mine = ["scripts/governance/stamp-verification.py",
            "scripts/governance/_tree_stamp.py"]
    check("sv15 both new files are classified `covered` - a suite in tests/ and "
          "no inline one. Asked of `selftest_coverage()` rather than of the "
          "source text, because the classifier reads STRING LITERALS and a file "
          "explaining the rule in a comment would fail a grep while being "
          "perfectly compliant: %r"
          % ([name for name in mine if name not in coverage["covered"]],),
          all(name in coverage["covered"] for name in mine)
          and not [d for d in coverage["defects"] if any(n in d for n in mine)])


def _cases(check):
    _harness.stage(check, "sv-take", _take_cases)
    _harness.stage(check, "sv-compare", _compare_cases)
    _harness.stage(check, "sv-shape", _shape_cases)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_stamp_verification.py --selftest\n")
    raise SystemExit(2)
