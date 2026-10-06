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
import shlex
import subprocess
import sys
import time

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
    # (qs) the double-quoted substitution reader, with no other layer in front
    # of it: the bodies it returns, and None for one it cannot read.
    _q = M._quoted_substitutions
    _qg = "git " + "stash"
    check("qs1 a quoted `)` inside a substitution does not end it - the whole "
          "body comes back", _q('echo "$(echo \')\'; ' + _qg + ')"')
          == ["echo ')'; " + _qg], repr(_q('echo "$(echo \')\'; ' + _qg + ')"')))
    check("qs2 a substitution that never closes is unreadable: None, not an "
          "empty list", _q('echo "$(' + _qg) is None
          and _q('echo "`' + _qg) is None, repr(_q('echo "$(' + _qg)))
    check("qs3 SECOND DIRECTION: a closed one is read and a single-quoted one "
          "is not a substitution at all",
          _q('echo "$(date)"') == ["date"] and _q("echo '$(date)'") == [])
    check("qs4 an inner body that will not parse makes the whole command "
          "unparseable (None) - the answer that sends every arm to the raw-text "
          "reading, never an empty list",
          M.git_calls('echo "`' + _qg + " '`" + '"') is None
          and M.git_calls('echo "$(date)"') == [],
          repr(M.git_calls('echo "`' + _qg + " '`" + '"')))

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

        # --- the verb has to be in SUBCOMMAND position --------------------------
        # The patterns read `\bgit\b[^|;&]*\bVERB\b`, which lets any text sit
        # between the two - so a COMMIT MESSAGE naming one of these operations was
        # graded as performing it. This refused a real commit documenting the rule,
        # and then refused the probe written to measure it. It is
        # `guard-secrets-read`'s class of defect in a second hook, and it earns the same
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
        # gh6g IS A RECORDED DECISION, REVERSED - INVERTED, NOT DELETED.
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
            check("%s REVERSED: a quoted argument spelling a whole "
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
        # KNOWN OPEN, named in SECURITY.md's "an interpreter program that starts
        # git from inside its own code ... is read as code, not searched for
        # git - the guard reads shell text, and a program's own calls are the
        # general residual". This guard parses the shell COMMAND text, so a
        # `git push --force` started from a `subprocess.run([...])` call inside
        # a `python3 -c` program never appears as shell text at all - the
        # refusal gh8 pins right above does not reach it. Pinned as a decision
        # beside its plain twin, so a fix that closes the residual turns this
        # row red rather than leaving it quietly disagreeing with the document.
        v, why = _decide(repo, 'python3 -c "import subprocess; '
                               "subprocess.run(['git', 'push', '--force', "
                               "'origin', 'main'])\"")
        check("gh8b KNOWN OPEN: a `python3 -c` program that starts `git push "
              "--force` from its own `subprocess.run` call is allowed - the "
              "interpreter residual SECURITY.md already names, beside gh8's "
              "plain refusal of the same operation",
              v == "allow", repr((v, why)))
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

        # --- git stash is refused, git stash list and show stay allowed,
        # --- and git push is untouched ----------------------------------------
        # Read as ONE case in four parts, because each part alone is a rule that
        # is either useless or harmful:
        #   * gh14 is parsing, with no repo in play at all;
        #   * gh15 is the refusal - the half the incident asked for;
        #   * gh16 is the ALLOW half, and it is the one that fails when the guard
        #     is weakened until it over-fires. A hook refusing `git stash list`
        #     gets switched off, and then gh15 protects nothing;
        #   * gh17 is the same allow half asked of PROSE, a path and a grep
        #     pattern - the same class, in a third hook.
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
                 "the same shape one verb over, unquoted this time - the earlier "
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
        # --- the three ways the token reading could UNDER-fire ---------------
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
        # --- THE SPELLINGS TABLE ------------------------------------------------
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
        # THE HEREDOC - gh32 IS A SECOND RECORDED DECISION REVERSED, INVERTED AND
        # NOT DELETED, for the same reason gh6g above is. It used to assert that a
        # heredoc body naming a forbidden command stays REFUSED, carried as a
        # "known cost" on the claim that nothing here could tell a `cat <<EOF`
        # body from an `sh <<EOF` one. Two things were wrong with that. The cost
        # was not a cost but a defect - a Bash call whose ONLY act was
        # `cat > probe.py <<'PYEOF'`, writing a file whose content carried a
        # force-push literal as a test payload, was refused with the force-push
        # reason, no push requested and no remote named, and the author's way past
        # it was to write the file with a different tool, which is a guard being
        # routed around. And the claim was false: `guard-secrets-read` had told
        # the two apart before, so the question was answerable and had an
        # answer in this very directory. It now lives in `_config.split_heredocs`,
        # which both guards call.
        #
        # BOTH DIRECTIONS ARE LOAD-BEARING HERE and the deny half is not
        # decoration: a body fed to a SHELL or an INTERPRETER is text a machine
        # runs, and dropping it too would turn the fix into a bypass anyone could
        # spell in one line.
        for _cid, _cmd, _what in (
                ("gh32", "cat <<'EOF' > NOTES.md\nnever run " + _G + "\nEOF",
                 "the case that used to say the opposite"),
                ("gh32a", "cat > fixtures/payloads.txt <<'EOF'\n"
                          "git push --force origin main\nEOF\n"
                          "python3 run-probe.py fixtures/payloads.txt",
                 "the reported shape - a file of test payloads, written and then "
                 "read by a runner. The BODY has to be bare words for this case "
                 "to separate the two versions: a payload wrapped in quotes was "
                 "already one shlex word and was already allowed, so writing it "
                 "that way would have been a case no mutation could redden"),
                ("gh32b", "cat > NOTES.md <<'EOF'\nnever run git push --force "
                          "origin main\nEOF\necho \"unbalanced",
                 "...and the same body where something AFTER the heredoc will not "
                 "parse, which is the only shape that reaches the raw-text "
                 "fallback once the body is gone. It is here because the "
                 "mutation that grades the unstripped text in that fallback "
                 "SURVIVED every other case in this block - the fallback is a "
                 "second reading and it has to read the same text"),
                ("gh32c", "cat > NOTES.md <<'EOF'\nnever run " + _G + " drop\nEOF",
                 "the stash arm, because a fix to one arm is not a fix to the "
                 "class"),
                ("gh32d", "git commit -F - <<'MSG'\ndocs: say why git rebase -i "
                          "is refused here\nMSG",
                 "a commit message on stdin is data git never executes, which is "
                 "the same rule gh6g draws for `-m`")):
            v, why = _decide(repo, _cmd)
            check("%s a heredoc body on its way into a FILE is data, not a "
                  "command: %s" % (_cid, _what), v == "allow", repr((v, why)))
        for _cid, _cmd, _what in (
                ("gh33a", "bash <<'EOF'\ngit push --force origin main\nEOF",
                 "a body fed to a shell IS a script, and this is the spelling the "
                 "old reasoning was right to be afraid of"),
                ("gh33b", "bash -s <<'EOF'\n" + _G + " drop\nEOF",
                 "the same, one arm over - `-s` reads the program from stdin"),
                ("gh33c", "cat <<'EOF' | bash\ngit push --force origin main\nEOF",
                 "`cat` does not execute it, but the PIPE hands it to something "
                 "that does, and what the far side does cannot be read here"),
                ("gh33d", "cat > NOTES.md <<'EOF'\ngit push --force origin main\n",
                 "a heredoc whose terminator never arrives is left in the text, "
                 "so an unreadable command is judged exactly as strictly as "
                 "before any of this existed")):
            v, why = _decide(repo, _cmd)
            check("%s ...and the body a machine WILL run is still graded: %s"
                  % (_cid, _what), v == "deny", repr((v, why)))
        # THE THREE BUCKETS, COUNTED RATHER THAN FOUND, and the counting is the
        # point: `in` would be satisfied by a version that kept all three bodies
        # (the pre-fix guard, gh32 red) and by one that dropped all three (a
        # one-line bypass, gh33a-gh33c red). Only the counts separate the three.
        _views = ("cat > notes.md <<'D'\ngit stash drop databody\nD\n"
                  "bash -s <<'S'\ngit stash drop shellbody\nS\n"
                  "python3 - <<'P'\ngit stash drop codebody\nP")
        # A LIMIT, MEASURED AND RECORDED RATHER THAN DISCOVERED. The head of the
        # heredoc line is tested for an interpreter at its END, so a REDIRECT
        # TARGET ending in one of those names reads as an invocation: `cat >
        # probe.sh <<EOF` is graded as a script and its content is still refused,
        # where `cat > probe.py <<EOF` is data. Narrowing it (`sh` may not follow
        # a dot) takes BOTH patterns, not one - the mutation that changed only
        # `_STDIN_SHELL` left this case green, because `_STDIN_INTERP` names `sh`
        # too and went on classifying the body. And it would be a WIDENING of
        # `guard-secrets-read`, which shares this classification: a file written
        # by `cat > deploy.sh <<EOF` would stop being graded as a script there
        # too. That is a security boundary and a decision of its own, so this
        # case records today's answer instead of quietly changing it.
        v, why = _decide(repo, "cat > probe.sh <<'EOF'\ngit push --force origin "
                               "main\nEOF")
        check("gh35 KNOWN LIMIT, and this case is its record: a heredoc whose "
              "redirect target ENDS IN an interpreter name (`probe.sh`) is still "
              "graded as a script, because the head is matched at its end and a "
              "filename sits there. The conservative direction, kept on purpose - "
              "the narrowing would widen a secret guard that shares the rule",
              v == "deny", repr((v, why)))

        # --- every `git` word counts, prose included ---------------------------
        # An emitter's arguments were once read as inert. Each fix of that
        # narrowing opened another pass (a later pipe, a comment ending in a
        # backslash, a file run by name or by git itself), so it was REMOVED: a
        # fail-loud guard keeps only what it can prove. `echo ... git stash`
        # prose is refused on purpose; the rewritten rows below (gp1, gp2, gp3,
        # gp7, gp17, gp19, gp23) pinned the removed allow and now pin the base.
        for _cid, _cmd, _want, _what in (
                ("gp1", "echo attempt used " + _G, "deny",
                 "an emitter's words are read like any other - the over-refusal "
                 "SECURITY.md states as deliberate"),
                ("gp2", "printf '%s\\n' an attempt used " + _G + " drop", "deny",
                 "the other text emitter, the same reading"),
                ("gp3", "echo attempt used " + _G + " > notes.md", "deny",
                 "...and an emitter writing a file, the same"),
                ("gp4", "true && " + _G + " push", "deny",
                 "after `&&` is command position, whatever came before"),
                ("gp5", _G, "deny", "the bare command, unchanged"),
                ("gp6", "bash -c '" + _G + "'", "deny",
                 "a shell's -c argument is a command line"),
                ("gp7", "bash -c 'echo " + _G + "'", "deny",
                 "...which is read by the same rule, emitter and all"),
                ("gp8", "echo " + _G + " | sh", "deny",
                 "an emitter PIPED into a shell hands the words to something "
                 "that runs them - the allow above holds only while the output "
                 "goes nowhere a shell reads"),
                ("gp9", "echo " + _G + " | xargs -I{} sh -c {}", "deny",
                 "any pipe keeps the conservative reading, not only into sh"),
                ("gp10", "$(echo " + _G + ")", "deny",
                 "a substitution in command position RUNS its output"),
                ("gp11", "echo `echo " + _G + "`", "deny",
                 "...and so does a backquoted one inside an argument"),
                ("gp12", "sudo " + _G, "deny", "sudo runs its argument"),
                ("gp13", "env FOO=1 " + _G, "deny", "env runs its argument"),
                ("gp13a", "echo '" + _G + "' | env FOO=1 sh", "deny",
                 "an assignment under env cannot hide a receiving shell"),
                ("gp14", "echo x | xargs " + _G + " drop", "deny",
                 "xargs runs its argument"),
                ("gp15", "timeout 5 " + _G, "deny",
                 "a prefix this guard has no table entry for is still read "
                 "conservatively - the narrowing is a closed list of programs "
                 "that never run arguments, not an open list of ones that do"),
                ("gp16", "echo done; " + _G, "deny",
                 "the emitter's reach ends at its own separator"),
                ("gp17", "FOO=1 echo " + _G, "deny",
                 "an assignment before the emitter changes nothing"),
                ("gp18", "echo " + _G + " 2>&1 | sh", "deny",
                 "a redirection does not end the command: its output still "
                 "reaches the pipe"),
                ("gp19", "echo " + _G + " > notes.md 2>&1", "deny",
                 "...nor does a redirection that ends in a file"),
                ("gp20", "$(echo " + _G + "; true)", "deny",
                 "an emitter OPENING a substitution is refused even when its "
                 "own command ends at a `;` - the substitution's output runs"),
                ("gp21", "echo " + _G + " > x.sh; sh x.sh", "deny",
                 "an emitter writing a SHELL SCRIPT is writing a command"),
                ("gp22", "echo " + _G + " >> ~/.bashrc", "deny",
                 "...and so is one writing a dotfile a shell sources"),
                ("gp23", "echo " + _G + " > notes.txt; sh notes.txt", "deny",
                 "the write-then-run shape the removed exemption let through"),
                # A SUBSTITUTION INSIDE DOUBLE QUOTES is one word to the lexer,
                # and it runs.
                ("gp24", 'echo "$(' + _G + ')"', "deny",
                 "a double-quoted substitution runs its command"),
                ("gp25", 'eval "$(echo ' + _G + ')"', "deny",
                 "...and eval runs what the substitution printed"),
                ("gp26", 'sh -c "$(echo ' + _G + ')"', "deny",
                 "...and so does a shell's -c"),
                ("gp27", 'echo "`' + _G + '`"', "deny",
                 "a double-quoted backquote runs its command too"),
                ("gp28", "echo '$(" + _G + ")'", "allow",
                 "while a SINGLE-quoted one is literal text"),
                # `xargs git` with no verb: the verb comes from stdin.
                ("gp29", "echo stash | xargs git", "deny",
                 "the verb arrives on stdin and cannot be read"),
                ("gp30", "echo x | xargs git log --oneline", "allow",
                 "...while a verb on the command line is graded as itself"),
                # A git command QUOTED AS ONE PHRASE is one word to the lexer.
                # Where that word goes decides whether it is a command: into a
                # shell, into a git hook, or into a file the same command runs.
                ("gp31", "echo '" + _G + "' | sh", "deny",
                 "a quoted phrase piped into a shell is the command it spells"),
                ("gp32", "printf '%s\\n' 'git push --force origin main' | bash",
                 "deny", "...a force-push, the same way"),
                ("gp33", "echo '" + _G + "' > .git/hooks/pre-commit", "deny",
                 "...and written into a git hook, which git runs on the next "
                 "commit with no second command at all"),
                ("gp34", "echo '" + _G + "' > .husky/pre-commit", "deny",
                 "...a hook manager's hook directory, the same"),
                ("gp35", "echo '" + _G + "' > x; sh x", "deny",
                 "...and written into a file this same command then runs"),
                ("gp36", "echo '" + _G + "' > \"$F\"; sh \"$F\"", "deny",
                 "...including a target the guard cannot resolve"),
                ("gp37", "echo '" + _G + " is refused here' > notes.md", "allow",
                 "while a quoted phrase written into a prose file nothing runs "
                 "is text"),
                ("gp38", "echo 'the stash was refused' | sh", "allow",
                 "...and a phrase naming no git command is nothing to refuse, "
                 "wherever it goes"),
                ("gp39", "echo '" + _G + "' > docs/pre-commit.md", "allow",
                 "...a file merely NAMED like a hook, with an extension, is not "
                 "one git runs"),
                ("gp40", "echo '" + _G + "' > x; cat x", "allow",
                 "...and a file the same command only reads is not run"),
                ("gp41", "echo '" + _G + "' > x && chmod +x x && ./x", "deny",
                 "...while one it runs by path is"),
                ("gp42", "echo '" + _G + "' > githooks/pre-push", "deny",
                 "...and a file named as a git hook is one, whatever directory "
                 "core.hooksPath names"),
                ("gp43", "echo '" + _G + "' > \"$HOOK\"", "deny",
                 "...and a target the reading cannot resolve may name one"),
                # Operators count only OUTSIDE quotes, and only a text emitter's
                # arguments are what its stage prints.
                ("gp44", 'git commit -m "never ' + _G + ' -> $HOOK output>$TMPDIR"',
                 "allow", "a quoted `>` in a commit message is text, not a redirect"),
                ("gp45", "git log --grep '" + _G + "' > \"$TMPDIR/hits.txt\"",
                 "allow", "...and a read whose argument names the phrase prints "
                 "the log, not its argument"),
                ("gp46", "grep -n '" + _G + " drop' SECURITY.md > \"$TMPDIR/g.txt\"",
                 "allow", "...a search, the same"),
                ("gp47", "echo '" + _G + "' >| .git/hooks/pre-commit", "deny",
                 "the clobber redirect is a redirect"),
                ("gp48", "(echo '" + _G + "') | sh", "deny",
                 "a group's output piped into a shell"),
                ("gp49", "{ echo '" + _G + "'; } | bash", "deny",
                 "...a brace group, the same"),
                ("gp50", "echo '" + _G + "' | fish", "deny",
                 "...any shell program, not only the POSIX family"),
                ("gp51", "echo '" + _G + "' | $SHELL", "deny",
                 "...and a program named by a variable may be one"),
                ("gp52", "echo '" + _G + "' | source /dev/stdin", "deny",
                 "...and sourcing stdin runs it"),
                ("gp53", "echo '" + _G + "' > >(sh)", "deny",
                 "a process substitution as the target runs what it is given"),
                ("gp54", "echo '" + _G + "' > githooks/PRE-COMMIT", "deny",
                 "a hook name is matched without regard to case"),
                ("gp55", "echo '" + _G + "' > sub/.husky/h", "deny",
                 "...and a hook manager's directory anywhere in the path"),
                ("gp56", "echo '" + _G + "' > hooks/pre-*", "deny",
                 "...and a glob in the target cannot be resolved"),
                ("gp57", "echo '" + _G + "' | tee .git/hooks/pre-commit", "deny",
                 "tee writes its input into the files it names"),
                ("gp58", "echo '" + _G + "' | tee notes.md", "allow",
                 "...while tee into a prose file is text"),
                ("gp59", "echo 'the rule: never " + _G + " -> $HOOK'", "allow",
                 "an emitter whose quoted text holds a `>` and an expansion "
                 "writes nowhere"),
                ("gp60", "(echo '" + _G + "'; true) | sh", "deny",
                 "...and every stage of a piped group reaches the shell, not "
                 "only its last"),
                # Compound commands, comments and receiving groups.
                ("gp61", "if true; then echo '" + _G + "' > .git/hooks/pre-commit; fi",
                 "deny", "an emitter after a reserved word is still an emitter"),
                # The allow twins gp61a, gp62a, gp64a, gp68a, gp69a, gp70a and
                # gp71a pin the compound reading against
                # OVER-firing. Each writes the phrase into notes.md or pipes it
                # into cat, and each goes red under one mutation: every member
                # of a receiving group read as a runner (gp64a), or a compound's
                # redirect and pipe handed to the stages before it as well as
                # its own (the rest, whose trailing group carries plain text).
                ("gp61a", "if true; then echo '" + _G + "'; fi > notes.md; "
                 "( echo hello ) > .git/hooks/pre-commit", "allow",
                 "...while a then-branch emitter redirected into notes.md is "
                 "text, and a later group's redirect is not its own"),
                ("gp62", "for x in 1; do echo '" + _G + "'; done | sh", "deny",
                 "...and a loop's output piped after `done` reaches every stage"),
                ("gp62a", "for x in 1; do echo '" + _G + "'; done | cat; "
                 "( echo hello ) | sh", "allow",
                 "...while a loop piped after `done` into cat is text, and a "
                 "later group's pipe is not the loop's"),
                ("gp63", "echo 'never " + _G + "' # see > $X", "allow",
                 "a comment's `>` is not a redirect"),
                ("gp64", "echo '" + _G + "' | (cd /tmp && sh)", "deny",
                 "a pipe into a group reaches every stage of it"),
                ("gp64a", "echo '" + _G + "' | (cd /tmp && cat)", "allow",
                 "...while a receiving group whose members only print runs "
                 "nothing"),
                ("gp65", "echo '" + _G + "' | sudo grep -c x \"$F\"", "allow",
                 "a wrapper's operand holding `$` is not the program"),
                ("gp66", "echo '" + _G + "' > docs/Update", "allow",
                 "a file named like a hook outside any hook directory is not "
                 "one"),
                ("gp67", "echo '" + _G + "' > >(cat)", "allow",
                 "a process substitution whose command only prints is not "
                 "a run"),
                ("gp68", "echo 'git push' '--force origin main' | sh", "deny",
                 "an emitter's words print as one line, so a phrase split "
                 "across arguments is read whole"),
                ("gp68a", "echo 'git push' '--force origin main' > notes.md; "
                 "( echo hello ) | sh", "allow",
                 "...while the same words written into notes.md are text"),
                ("gp69", "cat <<< '" + _G + "' | sh", "deny",
                 "cat fed a here-string prints it"),
                ("gp69a", "cat <<< '" + _G + "' > notes.md; ( echo hello ) | sh",
                 "allow", "...into notes.md, text"),
                ("gp70", "builtin echo '" + _G + "' | sh", "deny",
                 "`builtin` runs its argument"),
                ("gp70a", "builtin echo '" + _G + "' > notes.md; "
                 "( echo hello ) | sh", "allow", "...into notes.md, text"),
                ("gp71", "echo \"$(echo '" + _G + "')\" | sh", "deny",
                 "an inner emitter's substitution contributes what it prints"),
                ("gp71a", "echo \"$(echo '" + _G + "')\" > notes.md; "
                 "( echo hello ) | sh", "allow", "...into notes.md, text"),
                # Shapes the narrowings had dropped.
                ("gp72", "case x in a) echo in; (echo '" + _G + "') | sh;; esac",
                 "deny", "the word `in` inside a case arm does not reopen patterns"),
                ("gp73", "echo '" + _G + "' > >(tee .git/hooks/pre-commit)", "deny",
                 "a process substitution whose command tees into a hook"),
                ("gp74", "cd .git/hooks && echo '" + _G + "' > pre-commit", "deny",
                 "a bare hook name after a `cd` into the hooks directory"),
                ("gp75", "echo '" + _G + "' | sudo -u root \"$SH\"", "deny",
                 "a variable as the program behind a wrapper option with a value"),
                ("gp76", "echo '" + _G + "' | cat > .git/hooks/pre-commit", "deny",
                 "a pass-through cat carries its own redirect"),
                ("gp77", "echo '" + _G + "' | while read l; do eval \"$l\"; done",
                 "deny", "a receiving loop that evals what it read runs it"),
                ("gp78", "echo '" + _G + "' | while read l; do echo \"$l\"; done",
                 "allow", "...while one that only prints it does not"),
                # A `case` read in command position only; the body is READ.
                ("gs19", 'echo "$(echo worst case)"; echo stash | xargs git',
                 "deny", "a bare word `case` in a substitution does not make "
                 "the command unreadable, so a verb from stdin is still seen")):
            v, why = _decide(repo, _cmd)
            check("%s %s: %s" % (_cid, _want, _what), v == _want,
                  repr((v, why[:120])))

        # --- a line continuation is not a separator -----------------------------
        # bash removes backslash-newline before it reads a word, so the emitter
        # and the pipe on the next line are ONE pipeline. Read as two, the pipe
        # started a new command and the emitter's words were inert.
        _nl = "\\\n"
        for _cid, _cmd, _want, _what in (
                ("gc1", "echo git push --force origin main " + _nl + "  | sh",
                 "deny", "a force-push printed into a shell across a continuation"),
                ("gc2", "echo git rebase -i HEAD~2 " + _nl + " | sh", "deny",
                 "a rebase, the same way"),
                ("gc3", "echo " + _G + " " + _nl + "\t| bash", "deny",
                 "a stash, with a tab after the newline"),
                ("gc4", "git log --oneline " + _nl + "  -3", "allow",
                 "...while a continuation inside an ordinary read joins it and "
                 "is still that read"),
                # A COMMENT RUNS TO THE END OF ITS LINE, and a backslash at its end
                # does NOT continue it - bash starts the next line as a command.
                ("gc5", "true # note " + _nl + "git push --force origin main",
                 "deny", "a force-push on the line after a comment that ends in "
                 "a backslash"),
                ("gc6", "git status # note " + _nl + "git push --force origin main",
                 "deny", "...where joining would have made it an argument of "
                 "`git status`"),
                ("gc7", ": # " + _nl + _G, "deny", "...a stash, the same way"),
                ("gc8", "git " + _nl + "  stash", "deny",
                 "a continuation outside a comment is still joined"),
                # A `#` is a comment only where the ASSEMBLED word starts: after
                # a removed continuation or an escaped blank it is mid-word, and
                # the line goes on to the next command.
                ("gc9", "echo x" + _nl + "#;gi" + _nl + "t stash", "deny",
                 "a stash after a `#` that a removed continuation made mid-word"),
                ("gc10", "echo a\\ #;gi" + _nl + "t stash", "deny",
                 "...and after a `#` that follows an escaped blank"),
                ("gc11", "echo x" + _nl + "#;git push --for" + _nl
                 + "ce origin main", "deny", "a force-push, the same way"),
                ("gc12", "echo x # note" + _nl + "git log --oneline", "allow",
                 "...while a real comment's trailing backslash still ends the "
                 "line, and the read on the next one is graded as itself")):
            v, why = _decide(repo, _cmd)
            check("%s %s: %s" % (_cid, _want, _what), v == _want,
                  repr((v, why[:120])))

        # --- a piped heredoc body is graded as shell ----------------------------
        # A data reading of the far side was tried and REMOVED: each allow-list
        # of it missed a spelling that runs the body (a later stage, an option set
        # in the environment). The field report's need is met without it - the
        # heredoc fed straight to the script is data (gq25). gq1 and gq2 pinned
        # the removed allow and now pin the base.
        _body = "an attempt used " + _G + " and was refused"
        _D = _G + " drop"
        for _cid, _cmd, _want, _what in (
                ("gq1", "cat <<'EOF' | python3 x.py --technical -\n%s\nEOF"
                 % _body, "deny", "a piped body is shell, whatever the far side"),
                ("gq2", "cat <<'EOF' | node tools/log.mjs\n%s\nEOF" % _body,
                 "deny", "...for any far side"),
                ("gq30", "cat <<'EOF' | python3 echo.py | sh\n%s\nEOF" % _D,
                 "deny", "a later stage runs what the first one echoed"),
                ("gq31", "export NODE_OPTIONS='-r /dev/stdin'; "
                 "cat <<'EOF' | node e.js\n%s\nEOF" % _D, "deny",
                 "an interpreter option set in the environment runs the body"),
                ("gq3", "cat <<'EOF' | bash\n%s\nEOF" % (_G + " drop"), "deny",
                 "a bare shell on the far side runs the body"),
                ("gq4", "cat <<'EOF' | python3 -\n%s\nEOF" % (_G + " drop"),
                 "deny", "an interpreter reading its PROGRAM from stdin runs the "
                 "body, so the body stays in the graded text"),
                ("gq5", "cat <<'EOF' | python3 -m pdb x.py\n%s\nEOF" % _G,
                 "deny", "a code flag on the far side (`-m`, `-c`, `-e`) may run "
                 "what it reads - pdb executes its stdin - so it is not data"),
                ("gq6", "cat <<'EOF' | frobnicate --x\n%s\nEOF" % _G, "deny",
                 "an unknown far side keeps the conservative reading"),
                ("gq7", "cat <<EOF | python3 x.py -\n$(%s)\nEOF" % _G, "deny",
                 "an UNQUOTED delimiter lets the shell run a substitution in the "
                 "body before the script ever reads it"),
                ("gq8", "cat > notes.md <<EOF\n$(%s)\nEOF" % _G, "deny",
                 "...and so it does for a body on its way into a file - the same "
                 "class, closed where it was open"),
                ("gq9", "cat > notes.md <<'EOF'\n$(%s)\nEOF" % _G, "allow",
                 "while a QUOTED delimiter makes the same bytes inert text"),
                ("gq10", "cat <<'EOF' | sh deploy.sh\n%s\nEOF" % _G, "deny",
                 "a SHELL given a script is not on the data list - a shell "
                 "script reading its stdin is one `read`+`eval` from running it"),
                # Every spelling below reads its PROGRAM from stdin, or hands the
                # body to something that does. The data shape is one allow-list
                # entry, so each of these keeps the grading it had before it.
                ("gq11", "cat <<'EOF' | python3 -W ignore -\n%s\nEOF" % _D,
                 "deny", "an option's VALUE is not a script operand"),
                ("gq12", "cat <<'EOF' | perl -I lib -\n%s\nEOF" % _D, "deny",
                 "the same for perl's include path"),
                ("gq13", "cat <<'EOF' | deno run -\n%s\nEOF" % _D, "deny",
                 "a SUBCOMMAND is not a script operand"),
                ("gq14", "cat <<'EOF' | python3 /dev/fd/0\n%s\nEOF" % _D, "deny",
                 "a /dev path to stdin is the dash written out"),
                ("gq15", "cat <<'EOF' | python3 -i x.py\n%s\nEOF" % _D, "deny",
                 "-i reads stdin as commands after the script"),
                ("gq16", "cat <<'EOF' | PYTHONINSPECT=1 python3 x.py -\n%s\nEOF"
                 % _D, "deny", "...and so does its environment spelling"),
                ("gq17", "tee >(sh) <<'EOF' | python3 x.py -\n%s\nEOF" % _D,
                 "deny", "a head other than cat can hand the body to a shell"),
                ("gq18", "cat <<EOF | python3 x.py -\n%s\nEOF" % _D, "deny",
                 "an UNQUOTED delimiter is not vouched for as data"),
                ("gq19", "env python3 -W ignore - <<'EOF'\n%s\nEOF" % _D, "deny",
                 "a wrapper and an option in front of an interpreter's stdin "
                 "program, in the heredoc's own head"),
                ("gq20", "bash <(cat) <<'EOF'\n%s\nEOF" % _D, "deny",
                 "a shell reading the body through process substitution"),
                ("gq21", "sh <<<'EOF'\n%s\nEOF" % _D, "deny",
                 "a here-string is not a heredoc - the next line is a command"),
                ("gq22", "cat <<'EOF' && %s\nx\nEOF" % _D, "deny",
                 "the rest of the heredoc's own line is command text"),
                ("gq23", "cat <<'EOF' | xargs python3 x.py\n%s\nEOF" % _D,
                 "deny", "a wrapper on the far side is not a plain script run"),
                ("gq24", "cat <<'EOF' \\\n  | bash\n%s\nEOF" % _D, "deny",
                 "a heredoc line that continues is not read to its far side"),
                ("gq25", "python3 x.py --technical - <<'EOF'\n%s\nEOF" % _body,
                 "allow", "a script run fed the body directly is still data"),
                ("gq26", "sudo python3 tools/x.py - <<'EOF'\n%s\nEOF" % _body,
                 "allow", "...and so behind a wrapper - gq19 is the deny beside "
                 "it"),
                # Each spelling below reaches exactly one check: no process
                # substitution in the head, no option before the operand, no
                # shell reading the body - so removing that one check is what
                # lets it through.
                ("gq27", "awk '{system($0)}' <<'EOF' | python3 x.py -\n%s\nEOF"
                 % _D, "deny", "a head that is not cat is not vouched for - awk "
                 "runs each line it reads"),
                ("gq28", "cat <<'EOF' | python3 runner -\n%s\nEOF" % _D, "deny",
                 "an operand without the interpreter's extension is not a "
                 "script file the data shape can vouch for"),
                ("gq29", "cat <<<'EOF'\n%s\nEOF" % _D, "deny",
                 "a here-string read as a heredoc would drop the next line as "
                 "data - it is a command")):
            v, why = _decide(repo, _cmd)
            check("%s %s: %s" % (_cid, _want, _what), v == _want,
                  repr((v, why[:120])))
        check("gh34 the text the guard grades, per heredoc kind: the body going "
              "into a FILE is gone, the body fed to a shell and the body fed to "
              "an interpreter are both still there. An interpreter body is kept "
              "on purpose - it is a program, and dropping it would be a hole "
              "rather than a narrowing",
              [M.runnable(_views).count(w)
               for w in ("databody", "shellbody", "codebody")] == [0, 1, 1],
              repr([M.runnable(_views).count(w)
                    for w in ("databody", "shellbody", "codebody")]))
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
        # --- the reader's own limits refuse rather than pass -------------------
        for _cid, _cmd, _want, _what in (
                ("gs1", 'echo "$(echo \')\'; ' + _G + ')"', "deny",
                 "a quoted `)` inside a double-quoted substitution does not end it"),
                ("gs2", 'echo "$(' + _G + " ')" + '"', "deny",
                 "an inner body that will not parse falls to the raw-text reading "
                 "instead of contributing nothing"),
                ("gs3", 'echo "$(date)"', "allow",
                 "...while a substitution that runs no git is nothing to refuse"),
                # EVERY `reset --hard` is graded, not the first.
                ("gs4", "git reset --hard && git reset --hard HEAD~2", "deny",
                 "the second reset orphans a recorded commit"),
                ("gs5", "git reset --hard && git reset --hard HEAD", "allow",
                 "...while two resets that orphan nothing pass"),
                # A here-string fed to a shell or an interpreter is its program.
                ("gs6", "sh <<<'" + _G + "'", "deny",
                 "a here-string to a shell is a command"),
                ("gs7", 'bash <<< "git push --force origin main"', "deny",
                 "...a force-push, the same way"),
                ("gs8", "python3 <<< '" + _G + " drop'", "deny",
                 "...and to an interpreter it is code, read the way -c is"),
                ("gs9", "cat <<< '" + _G + "'", "allow",
                 "while a here-string to a program that only reads it is data"),
                # The reader is found past a wrapper that runs its argument,
                # the way the heredoc head is read.
                ("gs10", "env sh <<<'" + _G + "'", "deny",
                 "a here-string to a shell behind env"),
                ("gs11", "sudo bash <<< '" + _G + "'", "deny",
                 "...behind sudo"),
                ("gs12", "command sh <<< '" + _G + "'", "deny",
                 "...behind command"),
                ("gs13", "timeout 5 sh <<<'" + _G + "'", "deny",
                 "...behind a wrapper with its own operand"),
                ("gs14", "grep sh <<< '" + _G + "'", "allow",
                 "...while a shell's NAME as the argument of a program that "
                 "only reads its input is still data"),
                ("gs15", "env FOO=1 cat <<< '" + _G + "'", "allow",
                 "...and so is a reader behind a wrapper that is not a shell "
                 "or an interpreter"),
                # A `case` pattern's `)` is not the substitution's close.
                ("gs16", 'echo "$(case x in x) ' + _G + ';; esac)"', "deny",
                 "a stash in a case arm inside a double-quoted substitution"),
                ("gs17", 'echo "$(case x in x) git push --force origin main;; '
                 'esac)"', "deny", "...a force-push, the same way"),
                ("gs18", 'echo "$(case x in x) date;; esac)"', "allow",
                 "...while a case arm that runs no git is nothing to refuse"),
                ("gs20", 'echo "$(case x in (x) ' + _G + ';; esac)"', "deny",
                 "...and a pattern in its own parentheses reads the same")):
            v, why = _decide(repo, _cmd)
            check("%s %s: %s" % (_cid, _want, _what), v == _want,
                  repr((v, why[:120])))
    finally:
        _harness.remove_tree(tmp)

    # --- where a substitution ends -----------------------------------------------
    # Only a `case` in command position is the keyword, and inside one a
    # pattern's `)` is not the close.
    _body = "echo worst case) tail"
    check("se1 a bare word `case` leaves a substitution readable to its own `)`",
          M._substitution_end(_body, 0) == _body.index(")"),
          repr(M._substitution_end(_body, 0)))
    _body = "case x in x) date;; esac) tail"
    check("se2 ...while a keyword `case` carries the read past its patterns to "
          "the `)` after `esac`", M._substitution_end(_body, 0)
          == _body.index("esac)") + 4, repr(M._substitution_end(_body, 0)))
    _body = "echo $(case x in a) echo y;; esac) end) tail"
    check("se4 a case inside a nested substitution closes that one, not this",
          M._substitution_end(_body, 0) == _body.index(") tail"),
          repr(M._substitution_end(_body, 0)))
    _body = "( case x in a) echo y;; esac ) ) tail"
    check("se5 ...and a case inside a subshell, the same",
          M._substitution_end(_body, 0) == _body.index(") tail"),
          repr(M._substitution_end(_body, 0)))
    _body = "case a in (a) case b in b) date;; esac;; esac) tail"
    check("se6 ...and a nested case after a parenthesised pattern is in "
          "command position", M._substitution_end(_body, 0)
          == _body.index("esac) tail") + 4, repr(M._substitution_end(_body, 0)))
    _body = "case x in a) (echo y) ;; esac) tail"
    check("se7 ...while a subshell's `)` inside an open case arm closes the "
          "subshell, not a pattern", M._substitution_end(_body, 0)
          == _body.index(") tail"), repr(M._substitution_end(_body, 0)))
    _body = "case x in a) echo 1;; b) echo 2;; esac) tail"
    check("se8 ...and every arm's pattern is a pattern, not only the first: a "
          "second arm's `)` does not close the substitution",
          M._substitution_end(_body, 0) == _body.index("esac)") + 4,
          repr(M._substitution_end(_body, 0)))
    check("se3 ...and one with no `esac` never closes, which is unreadable",
          M._substitution_end("case x in x) date", 0) is None,
          repr(M._substitution_end("case x in x) date", 0)))

    # --- a git command is judged by the plan of the tree it runs in -----------
    # The recorded SHAs came from CLAUDE_PROJECT_DIR's manifest. A worktree's
    # plan records the commits ITS tasks made, which the main checkout's copy
    # does not hold until a merge - so a rebase of the worktree branch orphaned
    # them with nothing refused. The tree is the one git runs in: `-C <dir>`, or
    # the directory a `cd` moved the shell to, or the payload's own.
    _wt_ok, _wt = _harness.attempt(_harness.worktree_pair, "histguard wt-")
    if not _wt_ok:
        check("gw0 the worktree fixture builds (%s)" % (_wt,), False)
        return
    with open(os.path.join(_wt["wt"], "f.txt"), "w", encoding="utf-8") as fh:
        fh.write("x")
    _git(_wt["wt"], "add", "f.txt")
    _git(_wt["wt"], "-c", "user.email=t@t.t", "-c", "user.name=t",
         "commit", "-qm", "wt work")
    _wt_sha = _git(_wt["wt"], "rev-parse", "HEAD").stdout.decode().strip()
    _wt_man = os.path.join(_wt["wt"], _wt["manifest_rel"])
    with open(_wt_man, "r", encoding="utf-8") as fh:
        _doc = json.load(fh)
    _doc["phases"][1]["tasks"][0]["commit"] = _wt_sha
    with open(_wt_man, "w", encoding="utf-8") as fh:
        json.dump(_doc, fh)
    _prev = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = _wt["main"]
    # EVERY PATH GOES INTO A COMMAND QUOTED, the way a shell user must type it.
    # A fixture path is whatever the temp directory is: on windows it carries
    # backslashes, which an unquoted shell word reads as escapes (`C:\Users\x`
    # becomes `C:Usersx`), and anywhere it may carry a space, which splits it in
    # two. Either way the command names a directory that is not the fixture, and
    # a case expecting deny reads allow.
    _q_wt = shlex.quote(_wt["wt"])
    _escaped_wt = _wt["wt"].replace(" ", "\\ ")
    try:
        for _cid, _cwd, _cmd, _want, _what in (
                ("gw1", _wt["main"], "git -C %s rebase main" % _q_wt, "deny",
                 "`git -C <worktree>` rebases the worktree branch, whose plan "
                 "records a commit the rebase rewrites"),
                ("gw2", _wt["main"], "cd %s && git reset --hard HEAD~1"
                 % _q_wt, "deny",
                 "a `cd` into the worktree, then a reset that orphans the "
                 "commit ITS plan records"),
                ("gw2b", _wt["main"], "cd %s && git reset --hard HEAD~1"
                 % _escaped_wt, "deny",
                 "the same worktree reached through a backslash-escaped "
                 "space in its `cd` target"),
                ("gw12", _wt["main"], 'cd "$WT" && git rebase main', "deny",
                 "a `cd` whose target cannot be read at all does not place "
                 "the rewrite in the session's directory"),
                ("gw13", _wt["main"], 'git -C "$WT" rebase main', "deny",
                 "...and neither does a `-C` value that cannot be read"),
                ("gw12a", _wt["main"], 'cd "$WT" && git status', "allow",
                 "an unreadable `cd` followed by a read"),
                ("gw12b", _wt["main"], 'cd "$WT" && git reset --hard', "allow",
                 "...and by a reset with no ref"),
                ("gw13a", _wt["main"], 'git -C "$WT" status', "allow",
                 "...and an unreadable `-C` value on a read"),
                ("gw14", _wt["main"], "git -C %s rebase main '" % _q_wt,
                 "deny",
                 "an unparseable command does not place a rewrite in the "
                 "session just because its `-C` could not be read"),
                ("gw14b", _wt["main"], "git rebase main '", "allow",
                 "an unparseable rewrite that names no cd and no -C runs "
                 "where the session stands - a trailing quote is not a "
                 "directory change"),
                ("gw14c", _wt["main"],
                 "git commit --amend -m x # it's ready", "allow",
                 "an apostrophe in a trailing comment is not a directory "
                 "change, so the amend is judged in the session"),
                ("gw14e", _wt["main"],
                 "git commit --amend -m \"$(cat <<'EOF'\nit's ready\nEOF\n)\"",
                 "deny",
                 "the house commit-message form carries a shell heredoc, "
                 "whose effect on the current shell cannot be established"),
                ("gw14a", _wt["main"], "git -C %s status '" % _q_wt, "allow",
                 "an unparseable command that is not a rewrite stays allowed "
                 "- the mutation that denies every unreadable command"),
                ("gw3", _wt["wt"], "git commit --amend -m x", "deny",
                 "a session standing in the worktree amends the commit its plan "
                 "records"),
                ("gw4", _wt["main"], "git rebase main", "allow",
                 "the same verb in the main checkout, whose plan records "
                 "nothing - the tree is per command, not a switch")):
            v, why = M.decide({"tool_name": "Bash", "cwd": _cwd,
                               "tool_input": {"command": _cmd}})
            check("%s %s: %s" % (_cid, _want, _what), v == _want,
                  repr((v, why[:160])))
        _house = "git commit --amend -m \"$(cat <<'EOF'\nit's ready\nEOF\n)\""
        v, why = M.decide({"tool_name": "Bash", "cwd": _wt["wt"],
                           "tool_input": {"command": _house}})
        check("gw14d a shell heredoc in an amend makes its directory "
              "UNKNOWN rather than guessing the worktree: %r"
              % ((v, why[:160]),),
              v == "deny" and "cannot establish" in why)
        _cd_unread = "cd \"$WT\" && git rebase main '"
        v, why = M.decide({"tool_name": "Bash", "cwd": _wt["main"],
                           "tool_input": {"command": _cd_unread}})
        check("gw14f an unparseable rewrite that does carry an unreadable "
              "cd is still refused, and the reason names the cd: %r"
              % ((v, why[:160]),),
              v == "deny" and "`cd`" in why and "cannot be parsed" not in why)
        v, why = M.decide({"tool_name": "Bash",
                           "tool_input": {"command": _cd_unread}})
        check("gw14g the same unreadable cd is still refused when the "
              "payload names no cwd at all - a silent payload is not "
              "evidence the cd is readable: %r" % ((v, why[:160]),),
              v == "deny" and "`cd`" in why)
        v, why = M.decide({"tool_name": "Bash",
                           "tool_input": {"command": "git rebase main"}})
        check("gw14h ...while a rewrite that moves the shell nowhere stays "
              "allowed with no payload cwd at all - a silent payload is "
              "not evidence of an unplaced cd either: %r"
              % ((v, why[:160]),),
              v == "allow")
        # How grading GROWS with the run of quoted -C operands, not how long
        # it takes: an absolute bound measures the machine. The two sizes are
        # timed interleaved and the fastest sample of each kept, so a slow
        # runner or a scheduler stall inflates both sides or neither. The
        # trailing quote never closes, so the command is unparsed and graded
        # by the regex fallback, which is where the backtracking lived.
        def _rewrite_grading_time(operands):
            command = "git" + (' -C "a"' * operands) + " rebase '"
            start = time.perf_counter()
            M.always_refused(command)
            return time.perf_counter() - start

        _short, _long = [], []
        for _ in range(30):
            _short.append(_rewrite_grading_time(4))
            _long.append(_rewrite_grading_time(16))
        _base, _grown = min(_short), min(_long)
        _ratio = _grown / _base if _base > 0 else None
        # What a bound of six guarantees at four times the operands: red
        # against the backtracking regex, which grows by orders of magnitude
        # here; red against a quadratic only when its per-operand cost is
        # comparable to the call's fixed cost - a cheaper quadratic can stay
        # under it.
        check("gw15 a long run of quoted -C operands in an unparsed "
              "rewrite is graded without backtracking, measured as a ratio "
              "so the machine's speed cancels out",
              _ratio is not None and _ratio < 6,
              "fastest at 4 operands %r s, at 16 %r s, ratio %s"
              % (_base, _grown,
                 "unmeasurable: the timer did not resolve the short run"
                 if _ratio is None else "%.2f" % (_ratio,)))
        # A SECOND worktree, still at the base commit, so `HEAD~1` does not
        # resolve there: a reset asked about in the wrong tree is a question
        # git cannot answer, and an unanswerable question is an allow.
        _wt_b = os.path.join(_wt["root"], "main-B")
        _git(_wt["main"], "worktree", "add", "-q", _wt_b, "-b", "wt-b")
        _q_b = shlex.quote(_wt_b)
        for _cid, _cmd, _want, _what in (
                ("gw5", "git -C %s status; git -C %s reset --hard HEAD~1"
                 % (_q_b, _q_wt), "deny",
                 "the reset's `HEAD~1` is resolved in the tree the RESET runs "
                 "in, not in the first tree the command reached"),
                ("gw6", "git -C %s status; git -C %s commit --amend -m x"
                 % (_q_b, _q_wt), "deny",
                 "...and the amend's HEAD is the amended tree's"),
                ("gw7", "git -C %s status; git -C %s reset --hard HEAD"
                 % (_q_b, _q_wt), "allow",
                 "while a reset of the worktree onto ITS OWN HEAD, which holds "
                 "the recorded commit, is allowed - asked in the first tree, "
                 "HEAD there is the base and the reset read as orphaning it")):
            v, why = M.decide({"tool_name": "Bash", "cwd": _wt["main"],
                               "tool_input": {"command": _cmd}})
            check("%s %s: %s" % (_cid, _want, _what), v == _want,
                  repr((v, why[:160])))
    finally:
        if _prev is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = _prev


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_guard_history_rewrite.py --selftest\n")
    raise SystemExit(2)
