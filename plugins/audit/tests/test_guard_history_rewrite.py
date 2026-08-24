#!/usr/bin/env python3
"""
The cases for `guard-history-rewrite.py` — and the ALLOW cases are the point.

A guard only ever seen refusing may be refusing everything, and a guard that
fires on correct work gets switched off, after which it protects nothing. So the
suite is written the other way round from the obvious one: the cases that matter
most are the ones asserting a command is **permitted**.

WHAT IS PINNED, and why each one is here rather than trusted:

- **`git reset --hard` with NO ref is ALLOWED.** It discards uncommitted work and
  moves no branch pointer, so nothing can stop being reachable. This is the
  common, legitimate case — abandoning a botched task attempt — and blocking it
  is how this guard would earn its way into someone's disabled-hooks list.
- **`git reset --hard <ref>` is decided by ANCESTRY, not by the word `reset`.**
  A reset onto a ref that still contains every recorded SHA is allowed; one that
  orphans a SHA is refused, naming the task that owns it.
- **A repo with no recorded SHAs is inert.** Nothing to orphan means nothing to
  refuse, and the guard says nothing at all rather than warning about a risk that
  does not exist yet.
- **Undecidable is ALLOW.** An unreadable manifest, a git that will not answer,
  a ref that does not resolve — all pass. A guard blocking on a typo would be
  worse than the trail it protects.
- **The refusal explains itself in the terms the reader can act on**: which task,
  which SHA, and what to do instead.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import json
import os
import subprocess
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402

M = _loader.load(os.path.join(_harness.HOOKS_DIR, "guard-history-rewrite.py"),
                 "guard_history_rewrite")


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args),
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def _repo_with_trail(tmp):
    """A real repo with three commits, the middle one recorded as a task.commit."""
    repo = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(repo, "docs", "audit"))
    subprocess.run(["git", "init", "-q", repo], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test User")
    shas = []
    for n in range(3):
        with open(os.path.join(repo, "f%d.txt" % n), "w", encoding="utf-8") as fh:
            fh.write("x")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "c%d" % n)
        shas.append(_git(repo, "rev-parse", "HEAD").stdout.decode().strip())
    manifest = {"meta": {"version": 2},
                "phases": [{"id": "P0", "title": "t", "status": "done",
                            "tasks": [{"id": "P0.1", "title": "t",
                                       "status": "done", "commit": shas[1]}]}]}
    with open(os.path.join(repo, "docs", "audit", "audit-plan.json"),
              "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)
    return repo, shas


def _decide(repo, command):
    return M.decide({"tool_name": "Bash", "cwd": repo,
                     "tool_input": {"command": command}})


def _cases(check):
    # --- parsing, before any repo exists --------------------------------------
    check("gh1 `reset --hard` with no ref parses as 'no target' - the empty "
          "string, not None, because None means 'this is not a reset at all' "
          "and the two lead to opposite verdicts",
          M.reset_target("git reset --hard") == ""
          and M.reset_target("git status") is None,
          repr((M.reset_target("git reset --hard"), M.reset_target("git status"))))
    check("gh2 ...and flags are not mistaken for the ref, which would send the "
          "ancestry check an unresolvable target and silently allow everything",
          M.reset_target("git reset --hard --quiet HEAD~2") == "HEAD~2",
          repr(M.reset_target("git reset --hard --quiet HEAD~2")))

    tmp = _harness.fixture_root("qg-histguard-")
    try:
        repo, shas = _repo_with_trail(tmp)

        # --- THE ALLOW CASES ---------------------------------------------------
        v, why = _decide(repo, "git reset --hard")
        check("gh3 THE CASE THIS GUARD EXISTS TO KEEP WORKING: `git reset --hard` "
              "with no ref is ALLOWED. It discards uncommitted work and moves no "
              "branch pointer, so no recorded commit can stop being reachable - "
              "and it is exactly what abandoning a botched task attempt looks like",
              v == "allow", repr((v, why)))
        v, why = _decide(repo, "git reset --hard HEAD")
        check("gh4 a reset onto a ref that still contains every recorded SHA is "
              "allowed - the verdict comes from ANCESTRY, not from the word "
              "'reset'",
              v == "allow", repr((v, why)))
        v, why = _decide(repo, "git status && git log --oneline")
        check("gh5 an ordinary read-only git command is allowed and says nothing",
              v == "allow" and why == "", repr((v, why)))
        v, why = _decide(repo, "git rebase --abort")
        check("gh6 `rebase --abort` is allowed: it UNDOES a rebase rather than "
              "performing one, and refusing the escape hatch would strand "
              "someone mid-conflict",
              v == "allow", repr((v, why)))

        # --- the refusals ------------------------------------------------------
        v, why = _decide(repo, "git reset --hard HEAD~2")
        check("gh7 a reset that orphans a recorded SHA is REFUSED, and names the "
              "task that owns it - a refusal the reader cannot act on is a "
              "refusal they will route around",
              v == "deny" and "P0.1" in why, repr((v, why)))
        v, why = _decide(repo, "git push --force origin main")
        check("gh8 force-push is refused outright: there is no ancestry question "
              "to ask, it replaces what other clones already have",
              v == "deny" and "force-push" in why, repr((v, why)))
        v, why = _decide(repo, "git checkout --orphan clean-start")
        check("gh9 an orphan branch is refused - it starts with no history, so "
              "every recorded commit is unreachable from it",
              v == "deny" and "orphan" in why, repr((v, why)))
        v, why = _decide(repo, "git rebase -i HEAD~3")
        check("gh10 rebase is refused, quoting the invariant it breaks rather "
              "than asserting it",
              v == "deny" and "orchestrator.md" in why, repr((v, why)))

        # --- inert when there is nothing to protect ----------------------------
        bare = os.path.join(tmp, "bare")
        os.makedirs(os.path.join(bare, "docs", "audit"))
        subprocess.run(["git", "init", "-q", bare], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        with open(os.path.join(bare, "docs", "audit", "audit-plan.json"),
                  "w", encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2}, "phases": []}, fh)
        v, why = _decide(bare, "git push --force origin main")
        check("gh11 a manifest with NO recorded SHAs makes the guard inert - "
              "nothing to orphan is nothing to refuse, and a guard that warned "
              "anyway would be teaching people to ignore it",
              v == "allow", repr((v, why)))
        v, why = _decide(os.path.join(tmp, "nowhere"), "git reset --hard HEAD~2")
        check("gh12 an unreadable manifest is ALLOW, not deny. A guard that "
              "blocked work because it could not read its own state would fail "
              "in the one direction it must never fail",
              v == "allow", repr((v, why)))
        check("gh13 a non-Bash tool is not this guard's business at all",
              M.decide({"tool_name": "Edit", "tool_input": {}})[0] == "allow")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_guard_history_rewrite.py --selftest\n")
    raise SystemExit(2)
