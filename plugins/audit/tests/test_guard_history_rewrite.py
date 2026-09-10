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

        # --- F278: the verb has to be in SUBCOMMAND position ------------------
        # The patterns read `\bgit\b[^|;&]*\bVERB\b`, which lets any text sit
        # between the two - so a COMMIT MESSAGE naming one of these operations was
        # graded as performing it. This refused a real commit documenting the rule,
        # and then refused the probe written to measure it. It is
        # `guard-secrets-read`'s F267 in a second hook, and it earns the same
        # repair: grade the operation, not the text.
        #
        # THE PAIR IS THE POINT. gh6b-gh6e are the "prose is not an operation" half
        # and gh7 onward are the "still refused" half; either alone is a rule that
        # refuses everything or nothing.
        for _cid, _cmd, _what in (
                ("gh6b", 'git commit -m "docs: the remedy is a rebase this '
                         'document forbids"', "a message ABOUT the rule"),
                ("gh6c", 'git log --grep "rebase"',
                         "a READ - nothing about `git log` rewrites anything"),
                ("gh6d", 'git commit -m "chore: say why filter-branch is refused"',
                         "a second verb, same shape"),
                ("gh6e", 'git commit -m "never reset --hard onto a recorded SHA"',
                         "the reset arm, which had the same defect")):
            v, why = _decide(repo, _cmd)
            check("%s naming an operation is not performing it: %s"
                  % (_cid, _what), v == "allow", repr((v, why)))
        # ...and the global-option forms still reach the verb, so the narrowing
        # did not buy its quiet by going blind to a spelling git accepts.
        v, why = _decide(repo, "git -C . rebase -i main")
        check("gh6f a global option before the verb does NOT hide it - `git -C "
              "<path> rebase` is the spelling a script uses, and a guard that "
              "missed it would be quiet in exactly the automated case",
              v == "deny", repr((v, why)))
        # gh6g IS A RECORDED DECISION, REVERSED (F283) - INVERTED, NOT DELETED.
        # It used to assert the OPPOSITE: that a message spelling a whole
        # forbidden command is still refused, carried as a "known cost" and
        # defended because the same raw-text property kept an
        # `sh -c "git rebase -i"` evasion caught.
        #
        # **The maintainer reversed it after measuring the cost**, which is not
        # symmetric between the two arms:
        #
        #   shipped=REFUSE  now=REFUSE  git commit -m "never run git push --force"
        #   shipped=ALLOW   now=REFUSE  git commit -m "docs: git stash is banned"
        #   shipped=ALLOW   now=REFUSE  echo "never run git stash push" >> NOTES.md
        #
        # Twelve of fifteen commands behaved; the three that did not are one
        # class - the literal inside quoted argument text. This repository
        # documents "never `git stash`" in `reference/orchestrator.md`,
        # `CLAUDE.md` and `SECURITY.md`, so WRITING ABOUT THE RULE is a daily
        # operation here: it refused a heredoc whose body merely contained the
        # string, and it would have refused the commit message of the change that
        # introduced it. A guard that fires on writing about the rule is the same
        # defect as one that fires on a read.
        #
        # A deleted case reads as an oversight; an inverted one with its reason is
        # a record. The fix is the CLASS and it is applied to BOTH arms on
        # purpose. gh24 is where the `sh -c` evasion the old reasoning leaned on
        # is kept caught, by parsing a shell's `-c` argument as the command it is.
        for _cid, _cmd, _arm in (
                ("gh6g", 'git commit -m "git rebase -i is banned here"',
                 "the rebase arm - the case that used to say the opposite"),
                ("gh6h", 'git commit -m "never run git push --force"',
                 "the force-push arm, which behaved this way in neither tree"),
                ("gh6i", 'git commit -m "docs: git stash is banned"',
                 "the stash arm - the commit message of P32.8 itself"),
                ("gh6j", 'echo "never run git stash push" >> NOTES.md',
                 "not a git command at all, and it was refused")):
            v, why = _decide(repo, _cmd)
            check("%s REVERSED (F283): a quoted argument spelling a whole "
                  "forbidden command is ALLOWED - %s. Tokenized, the message is "
                  "ONE word, so the operation is absent and the refusal has "
                  "nothing to bind to" % (_cid, _arm),
                  v == "allow" and why == "", repr((_cmd, v, why)))

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
        # EVERY SPELLING, not one per arm. Found by a red-first probe: dropping
        # `-f` from the force-push check SURVIVED, because gh8 asserts `--force`
        # and nothing asserted the short form. A guard hand-written per spelling
        # needs a case per spelling, and the ones below were each untested -
        # `-f`, `--force-with-lease`, `switch --orphan` and `filter-repo`.
        for _cid, _cmd, _needle in (
                ("gh29a", "git push -f origin main", "force-push"),
                ("gh29b", "git push --force-with-lease origin main",
                 "force-with-lease"),
                ("gh29c", "git switch --orphan clean-start", "orphan"),
                ("gh29d", "git filter-repo --path src", "filter-branch"),
                ("gh29e", "git -c user.name=x rebase main", "orchestrator.md")):
            v, why = _decide(repo, _cmd)
            check("%s every spelling of a refused operation is refused, not one "
                  "per arm: %r" % (_cid, _cmd),
                  v == "deny" and _needle in why, repr((v, why)))

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

        # --- F281: git stash is refused, git stash list and show stay allowed,
        # --- and git push is untouched ----------------------------------------
        # Read as ONE case in four parts, because each part alone is a rule that
        # is either useless or harmful:
        #   * gh14 is parsing, with no repo in play at all;
        #   * gh15 is the refusal - the half the incident asked for;
        #   * gh16 is the ALLOW half, and it is the one that fails when the guard
        #     is weakened until it over-fires. A hook refusing `git stash list`
        #     gets switched off, and then gh15 protects nothing;
        #   * gh17 is the same allow half asked of PROSE, a path and a grep
        #     pattern - the F267/F278 class, in a third hook.
        # `_G` builds the verb rather than spelling it, so this file's own text
        # cannot be mistaken for the command by anything that greps sources.
        _G = "git " + "stash"
        check("gh14 the sub-verb is parsed out, and a BARE `%s` is the empty "
              "string rather than None: git performs it as `push`, so it is an "
              "operation. None means 'this command does not stash at all', and "
              "the two lead to opposite verdicts (as with `reset_target`)" % _G,
              M.stash_operations(_G) == [""]
              and M.stash_operations("git status") == []
              and M.stash_operations(_G + " list") == ["list"],
              repr((M.stash_operations(_G), M.stash_operations("git status"),
                    M.stash_operations(_G + " list"))))
        for _sub in ("", " push", " save", " pop", " apply", " drop", " clear",
                     " branch rescue", " push --keep-index", " -- src/app.ts",
                     " -p"):
            v, why = _decide(repo, _G + _sub)
            check("gh15 `%s%s` is REFUSED - the stash is the one place git keeps "
                  "work with no commit to find it by, and the refusal names what "
                  "to do instead" % (_G, _sub),
                  v == "deny" and "stash" in why and "git diff" in why,
                  repr((v, why)))
        for _sub in (" list", " show", " list --stat", " show -p stash@{0}"):
            v, why = _decide(repo, _G + _sub)
            check("gh16 THE OVER-FIRE CASE: `%s%s` is a READ and stays ALLOWED. "
                  "This is what fails if the allowlist is dropped, and a guard "
                  "that refuses a read is one people route around - after which "
                  "gh15 is protecting nothing" % (_G, _sub),
                  v == "allow" and why == "", repr((v, why)))
        for _cid, _cmd, _what in (
                ("gh17a", 'git commit -m "never stash your work"',
                 "the WORD in a commit message"),
                ("gh17b", "cat notes/stash.md", "a filename"),
                ("gh17c", "git show HEAD:src/stash.py", "a path inside a read"),
                ("gh17d", "git log --grep stash", "an UNQUOTED grep pattern"),
                ("gh17e", 'git log --grep "stash"', "a quoted grep pattern"),
                ("gh17f", "git --no-pager log --grep stash",
                 "...and behind a real global option"),
                ("gh17g", "grep -rn stash plugins/", "a grep of the tree"),
                ("gh17h", "git stashes", "a longer word starting with the verb"),
                ("gh17i", "git log --grep rebase",
                 "the same shape one verb over, unquoted this time - the F278 "
                 "case was written with quotes, so this is the half that was "
                 "believed rather than measured"),
                ("gh17j", "git " + "stash-list",
                 "a hyphenated name git does not have. `\\b` treats the hyphen "
                 "as a boundary and would refuse it, with a message describing "
                 "an operation the reader never asked for - which is the pair "
                 "`(?![\\w-])` is there to avoid")):
            v, why = _decide(repo, _cmd)
            check("%s naming is not performing: %s" % (_cid, _what),
                  v == "allow", repr((v, why)))
        # COMPOUND COMMANDS, which is how the incident actually happened: a stash
        # buried in a chain. The first row is the one a `search` would get wrong -
        # it reads first and destroys second, so grading the line by its first
        # match would call it a read.
        for _cid, _cmd in (
                ("gh18a", _G + " list && " + _G + " drop"),
                ("gh18b", "npm test && " + _G + " push --keep-index"),
                ("gh18c", "(cd sub; " + _G + " pop)"),
                ("gh18d", "git -C . " + "stash" + " pop")):
            v, why = _decide(repo, _cmd)
            check("%s a stash inside a compound command is still a stash: %r"
                  % (_cid, _cmd), v == "deny", repr((v, why)))
        v, why = _decide(repo, "git status | grep " + "stash")
        check("gh18e ...and a pipe whose SECOND half merely greps for the word "
              "is not one",
              v == "allow" and why == "", repr((v, why)))
        # --- F283: the three ways the token reading could UNDER-fire -----------
        # This is the only way the reversal can be worse than what it replaced, so
        # each hole has its own case and each was proven red by removing the thing
        # that closes it.
        #
        # 1. A SHELL's `-c` argument IS a command, so it is parsed as one. This is
        #    the evasion gh6g's old reasoning was defending, kept caught by a
        #    means that can tell a shell from `git commit -m`.
        for _cid, _cmd in (
                ("gh24a", 'sh -c "' + _G + ' pop"'),
                ("gh24b", "bash -lc '" + _G + " drop'"),
                ("gh24c", 'sh -c "git rebase -i"')):
            v, why = _decide(repo, _cmd)
            check("%s a shell's `-c` argument is a COMMAND and is read as one: "
                  "%r stays refused. `git commit -m` is not a shell and its "
                  "argument is not a command - that distinction is the whole "
                  "change" % (_cid, _cmd), v == "deny", repr((v, why)))
        # 2. AN UNPARSEABLE COMMAND FALLS BACK TO THE RAW-TEXT PATTERNS and stays
        #    conservatively refused. `shlex` raises on an unbalanced quote, and
        #    "could not be read" must never resolve to "allowed".
        for _cid, _cmd in (
                ("gh25a", _G + ' push --keep-index "unbalanced'),
                ("gh25b", 'git rebase -i "unbalanced')):
            v, why = _decide(repo, _cmd)
            check("%s an UNPARSEABLE command reaches the text fallback and is "
                  "still refused: %r. This case exists to exercise that path - a "
                  "fallback nothing reaches is a fallback nobody knows is broken"
                  % (_cid, _cmd),
                  v == "deny" and M.git_invocations(_cmd) is None,
                  repr((v, M.git_invocations(_cmd))))
        # 3. SHELL PUNCTUATION IS SPLIT OUT OF TOKENS, not stripped from their
        #    ends. `shlex.split` glues it on, so an exact-token match without
        #    this allows every one of these - and the last two were REFUSED by
        #    the raw-text version, so they would have been a straight regression.
        for _cid, _cmd in (
                ("gh26a", "echo $(" + _G + ")"),
                ("gh26b", "echo `" + _G + "`"),
                ("gh26c", _G + ";echo done"),
                ("gh26d", _G + ">out.txt"),
                ("gh26e", "{ " + _G + " pop; }"),
                ("gh26f", "sudo " + _G + " drop"),
                ("gh26g", "xargs -n1 " + _G + " drop")):
            v, why = _decide(repo, _cmd)
            check("%s a separator glued to a token is still a separator: %r is "
                  "refused. Stripping only the ENDS of a token allows "
                  "`stash;echo`, which the raw-text version caught" % (_cid, _cmd),
                  v == "deny", repr((v, why)))
        # ...and the reverse of that normalisation, which is the reason its
        # character set is the command separators and NOTHING else. A wider set
        # split ARGUMENT VALUES too: `HEAD@{2}` became `HEAD@`, git cannot
        # resolve that, `orphaned_by` then finds nothing, and a reset that
        # orphans recorded commits is ALLOWED. Measured, not imagined.
        check("gh27 a reflog ref survives tokenizing intact - `HEAD@{2}` and "
              "`main@{yesterday}`, not `HEAD@`. A separator set wide enough to "
              "split a ref turns the ancestry question into one git cannot "
              "answer, and an unanswerable question is an ALLOW",
              M.reset_target("git reset --hard HEAD@{2}") == "HEAD@{2}"
              and M.reset_target("git reset --hard 'main@{yesterday}'")
              == "main@{yesterday}",
              repr((M.reset_target("git reset --hard HEAD@{2}"),
                    M.reset_target("git reset --hard 'main@{yesterday}'"))))
        v, why = _decide(repo, _G + " show -p stash@{0}")
        check("gh27b ...and the same ref shape on the READ side stays allowed, "
              "which is what would have hidden gh27: the sub-verb `show` "
              "answers before the mangled argument is ever looked at",
              v == "allow" and why == "", repr((v, why)))
        # --- F284: THE SPELLINGS TABLE ----------------------------------------
        # THIS IS THE DURABLE HALF OF THE WHOLE FILE. Every regression a code
        # review found in the tokenizer was a SPELLING of an operation the guard
        # already knew: a newline instead of `&&`, `/usr/bin/git` instead of
        # `git`, `eval` instead of `sh -c`, `--force-with-lease=ref` instead of
        # `--force-with-lease`, `-cx` instead of `-lc`. Each was allowed here and
        # refused by the raw-text version it replaced, and NOTHING said so,
        # because the suite asserted one spelling per operation.
        #
        # So the table is organised by AXIS rather than by verb - separator,
        # invocation, wrapper, option - and a narrowing of the tokenizer now
        # fails by this case's name with the spellings it broke listed. The
        # newline rows are first because that is the ordinary shape of a
        # multi-line Bash call and the one most likely to be typed.
        _spellings = (
            # separator: && ; | newline ( ) { }
            ("sep-and", _G + " list && " + _G + " drop"),
            ("sep-semi", _G + " list; " + _G + " drop"),
            ("sep-pipe", _G + " list | grep x; " + _G + " drop"),
            ("sep-newline", _G + " list\n" + _G + " drop"),
            ("sep-newline-force", "git status\ngit push --force origin main"),
            ("sep-newline-3", "echo hi\ngit status\ngit rebase -i main"),
            ("sep-subshell", "(cd sub && " + _G + " pop)"),
            ("sep-brace", "{ " + _G + " pop; }"),
            ("sep-backtick", "echo `" + _G + " drop`"),
            ("sep-dollar-paren", "echo $(" + _G + " drop)"),
            # invocation: bare, pathed, .exe, -C, -c k=v
            ("inv-bare", _G + " drop"),
            ("inv-pathed", "/usr/bin/" + _G + " drop"),
            ("inv-pathed-force", "/usr/bin/git push --force origin main"),
            ("inv-exe", "C:\\\\tools\\\\git.exe " + "stash" + " drop"),
            ("inv-dash-C", "git -C . " + "stash" + " drop"),
            ("inv-dash-c-kv", "git -c user.name=x rebase main"),
            ("inv-dash-C-force", "git -C . push --force origin main"),
            # wrapper: sh -c, sh -lc, sh -cx, bash -lc, eval, xargs, sudo, env
            ("wrap-sh-c", 'sh -c "' + _G + ' drop"'),
            ("wrap-sh-lc", "sh -lc '" + _G + " drop'"),
            ("wrap-sh-cx", 'sh -cx "' + _G + ' drop"'),
            ("wrap-sh-xc", 'sh -xc "git rebase -i main"'),
            ("wrap-bash-lc", "bash -lc '" + _G + " drop'"),
            ("wrap-eval", "eval '" + _G + " drop'"),
            ("wrap-eval-force", 'eval "git push --force origin main"'),
            ("wrap-xargs", "xargs -n1 " + _G + " drop"),
            ("wrap-sudo", "sudo " + _G + " drop"),
            ("wrap-env", "env FOO=1 " + _G + " drop"),
            # option spelling, on the arm where each is the operation
            ("opt-force", "git push --force origin main"),
            ("opt-f", "git push -f origin main"),
            ("opt-f-cluster", "git push -fu origin main"),
            ("opt-lease", "git push --force-with-lease origin main"),
            ("opt-lease-ref",
             "git push --force-with-lease=origin/main origin main"),
            ("opt-force-eq", "git push --force=all origin main"),
            ("opt-orphan", "git checkout --orphan clean"),
            ("opt-orphan-switch", "git switch --orphan clean"),
            # ...and the sub-verb spellings of the stash arm itself
            ("stash-bare", _G),
            ("stash-implicit-path", _G + " -- src/app.ts"),
            ("stash-flag-only", _G + " -p"),
            ("stash-m-help", _G + " push -m --help"),
        )
        _allowed = []
        for _sid, _cmd in _spellings:
            if _decide(repo, _cmd)[0] != "deny":
                _allowed.append((_sid, _cmd))
        check("gh30 EVERY SPELLING of an operation the guard knows is refused, "
              "axis by axis - separator, invocation, wrapper, option, sub-verb. "
              "This is the case that makes a narrowing of the tokenizer fail by "
              "name: every review finding against it was a spelling, allowed "
              "here and refused by the raw-text version, with nothing to say so. "
              "ALLOWED: %r" % (_allowed,), _allowed == [])
        # ...and the OTHER direction of the same table, because a version that
        # refused everything would pass gh30 and be useless. These are reads and
        # prose in the same spellings.
        _refused = []
        for _sid, _cmd in (
                ("read-newline", _G + " list\n" + _G + " show"),
                ("read-help", _G + " --help"),
                ("read-help-short", _G + " -h"),
                ("read-rebase-help", "git rebase --help"),
                ("read-pathed", "/usr/bin/" + _G + " list"),
                ("read-wrapped", 'sh -c "' + _G + ' list"'),
                ("prose-newline",
                 'git commit -m "docs"\necho "never run ' + _G + '"'),
                ("prose-message", 'git commit -m "docs: ' + _G + ' is banned"'),
                ("push-plain", "git push origin main"),
                ("push-plain-newline", "git status\ngit push origin main")):
            if _decide(repo, _cmd)[0] != "allow":
                _refused.append((_sid, _cmd))
        check("gh31 ...and the same axes on the ALLOW side: a read is a read "
              "however it is spelled, and `--help`/`-h` print a manual page and "
              "change nothing. Without this row gh30 is satisfied by a guard "
              "that refuses every command it is shown. REFUSED: %r" % (_refused,),
              _refused == [])
        # THE HEREDOC, as a KNOWN COST rather than a discovery. The module
        # docstring used to claim a heredoc body is allowed like a commit message
        # and it is not: `shlex` splits `<<'EOF'` at the `<` and lexes the body as
        # bare words. It stays refused on purpose - whether a heredoc body is DATA
        # or a COMMAND depends on what consumes it, and `sh <<EOF` is a script.
        v, why = _decide(repo, "cat <<'EOF' > NOTES.md\nnever run " + _G
                         + "\nEOF")
        check("gh32 KNOWN COST: a heredoc body naming a forbidden command is "
              "REFUSED, unlike a commit message. `cat <<EOF` is data and "
              "`sh <<EOF` is a script, and nothing here can tell them apart, so "
              "the conservative direction is kept and written down instead of "
              "being claimed away",
              v == "deny", repr((v, why)))
        v, why = _decide(repo, "git log --grep git --grep " + "stash")
        check("gh28 a second `git` in an ARGUMENT does not start an invocation - "
              "a verb's args stop at a separator and nothing else. Stopping them "
              "at `git` was tried, bought no coverage (gh26f and gh26g find "
              "theirs by the word scan) and refused this read",
              v == "allow" and why == "", repr((v, why)))
        # THE ARM DOES NOT WAIT FOR A RECORDED SHA, and this pairs with gh11.
        # Same repo, same emptiness: force-push is allowed there because nothing
        # can be orphaned, and a stash is NOT, because the work it removes was
        # never committed. If the stash check is moved below the SHA gate this is
        # the case that goes red - and it is the exact repo the incident happened
        # on, a plan whose first task has not committed yet.
        v, why = _decide(bare, _G)
        check("gh20 a plan with NO recorded SHAs still refuses a stash, where "
              "gh11 shows the same plan allowing a force-push. The two arms ask "
              "different questions and are activated by different evidence",
              v == "deny", repr((v, why)))
        v, why = _decide(bare, "git push origin main")
        check("gh21 `git push origin main` WITHOUT a force flag is ALLOWED, and "
              "that is a recorded decision rather than a gap: a hook refusing it "
              "would stop the human operator on every release, and a guard "
              "routed around stops protecting the half that mattered. "
              "tools/check-prohibitions.py carries the reason",
              v == "allow" and why == "", repr((v, why)))
        noplan = os.path.join(tmp, "noplan")
        os.makedirs(noplan)
        v, why = _decide(noplan, _G + " push --keep-index")
        check("gh22 ...and with NO audit plan on disk the stash arm is inert. "
              "A guard that refused `%s` in every unrelated repository on the "
              "machine is a guard whose hooks get switched off, which is the "
              "failure mode this whole file is organised around" % _G,
              v == "allow" and why == "", repr((v, why)))
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
