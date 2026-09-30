#!/usr/bin/env python3
"""
PreToolUse guard (matcher: Bash) — refuse a git command that would ORPHAN a
commit the manifest records, or STASH work the plan has not recorded yet.

`task.commit` holds the SHA of each task's commit and `bug.fixedIn` is derived
from it, which is why `reference/orchestrator.md` says "never rebase the phase
branch" and lists force-push among the invariants. Those are instructions to the
ORCHESTRATOR. A human at the same terminal is not the orchestrator, and the
damage is identical: `/audit:doctor` then reports "the manifest names a commit
git does not have" and the audit trail is a list of ghosts.

**THE GUARD BINDS TO THE OPERATION, NOT TO TEXT**, and that is the whole design.
It reads two ways, and the first one decides almost every call:

  * the command is TOKENIZED and the verb read from an ADJACENT token, so a
    forbidden command spelled inside a QUOTED ARGUMENT - a commit message, an
    `echo` into a notes file - is absent as an operation and is allowed. Writing
    about the rules is a daily operation in this repository and a guard that
    fires on it is the same defect as one that fires on a read - this REVERSED
    the known cost recorded before it;
  * a command `shlex` cannot parse falls back to the raw-text patterns, which
    over-fire on quoted text and are the conservative answer where nothing can
    be parsed at all.

**A HEREDOC BODY IS GRADED BY WHAT CONSUMES IT**, which is the third reading and
the one this document twice got wrong. `shlex` splits `<<'EOF'` at the `<` and
lexes the body as bare words, so every body used to arrive as command words: a
call whose ONLY act was `cat > probe.py <<'PYEOF'` - a file whose content carried
a force-push literal as a test payload - was refused with the force-push reason,
having requested no push and named no remote. The author's way past it was to
write the file with another tool, which is the routed-around outcome that makes
a guard worthless. The previous paragraph here called that a measured cost and
said nothing could tell the two apart; `guard-secrets-read` could, and had for a
while. So the question is asked once, in `_config.split_heredocs`: a body fed to an
interpreter or a shell (`python3 - <<PY`, `bash -s <<EOF`, `cat <<EOF | bash`) is
text a machine RUNS and every rule below still reads it, and a body on its way
into a file is data and is gone before the first token is read.

WHAT THAT GIVES UP, measured against the version before it rather than guessed
at. A file WRITTEN by one command and EXECUTED by a later one is no longer read:
`cat > probe.txt <<EOF` / a forbidden command / `EOF` / `sh probe.txt` was
refused before and is allowed now. It is one spelling of a gap that was already
open - the same two steps written `printf '...' > probe.txt` then `sh probe.txt`
were allowed before this change and after it, because a quoted argument was never
a command - and closing it means reading files, which this hook never does. The
`.sh` spelling of it is still refused, for a reason that is an accident rather
than a design: the heredoc's head is matched at its END, so a redirect target
named `probe.sh` reads as an `sh` invocation. `test_guard_history_rewrite.py`'s
gh35 records that, and says why narrowing it is a decision about
`guard-secrets-read` and not about this file.

`git reset --hard` shows the other half of the same idea - one spelling is not
one operation:

  git reset --hard                 discards uncommitted work, touches NO history.
                                   Legitimate and common - abandoning a botched
                                   task attempt is exactly this. ALLOWED.
  git reset --hard <ref>           allowed unless a recorded SHA stops being an
                                   ancestor of <ref>. That is a question git can
                                   answer: `git merge-base --is-ancestor`.
  git push --force / --orphan /    rewrite or discard published history
  filter-branch / filter-repo      wholesale. REFUSED while any SHA is recorded.

A guard that refused every `reset --hard` would fire on correct work, and a guard
that fires on correct work gets switched off - after which it protects nothing.
That failure mode is recorded in this project's own history - the
`guard-secrets-read` read-vs-write class was fixed for the same reason before it -
so the ancestry check is not an optimisation. It is the reason the guard is allowed to exist.

TWO ARMS, TWO ACTIVATION CONDITIONS, and they are not interchangeable. The
history arm asks whether a COMMIT the manifest records would stop being
reachable, so a manifest with no recorded SHAs has nothing to orphan and every
command passes. The **stash** arm (see its own block below) asks nothing
about commits: `git stash` removes work that was never committed, so it is
refused as soon as an audit plan exists on disk. Reading the second arm as the
first is how it would end up silent on a plan whose first task is still mid-edit.

WHAT IT DOES NOT DO. It never inspects the working tree, never runs a write, and
never blocks a command it cannot decide about ancestry: an unreadable
manifest, or a git that will not answer, resolves to ALLOW. An unparseable
command that carries a rewrite is the exception, and it is refused while a
plan exists, because the directory Git would run it in cannot be established
and the session is a guess. It does not refuse
`git push` without a force flag, and that is a decision rather than a gap - the
reasoning is beside `STASH_READS` and the claim is driven from
`tools/check-prohibitions.py`.

Contract: a block emits {"hookSpecificOutput": {"permissionDecision": "deny",
"permissionDecisionReason": ...}} on stdout and exits 0 - the canonical
PreToolUse protocol. Unexpected input exits 0 (never break legitimate work).

This hook carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_guard_history_rewrite.py`.
"""
import json
import os
import re
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _config  # noqa: E402  (hooks resolve scripts/ by basename through here)

# --- reading the command as an OPERATION --------------------------------------
# THE COMMAND IS TOKENIZED AND THE VERB IS READ FROM AN ADJACENT TOKEN.
# Everything below this block is the FALLBACK for a command that will not parse;
# this is the path that decides almost every call, and it exists because the
# text-matching version refused people for WRITING ABOUT THE RULES.
#
# The regexes further down grade the raw line, so a forbidden command spelled
# inside a quoted argument matched at the inner `git`. Measured against the
# shipped guard and this one:
#
#     shipped=REFUSE  here=REFUSE   git commit -m "never run git push --force"
#     shipped=ALLOW   here=REFUSE   git commit -m "docs: git stash is banned"
#     shipped=ALLOW   here=REFUSE   echo "never run git stash push" >> NOTES.md
#
# That was accepted as a KNOWN COST once (the case that recorded it was gh6g) and
# the maintainer has reversed it, because the cost is not symmetric: this repo
# documents "never `git stash`" in `reference/orchestrator.md`, `CLAUDE.md` and
# `SECURITY.md`, so writing about the rule is a DAILY operation here, and the
# guard would have refused the commit message for its own change. A guard that
# fires on writing about it is the same defect as one that fires on a read.
# (It also refused a HEREDOC whose body merely contained the string. That half is
# fixed now, one layer earlier: `runnable()` below drops a body nothing executes
# before the tokenizer sees it, so those words never reach this scan at all.)
#
# THE FIX IS THE CLASS, NOT THE CASE, and it is applied to BOTH arms - two arms
# with two rules is the shape the next reader mis-generalises. Tokenized, the
# whole of `-m "docs: git stash is banned"` is ONE word: the operation is absent,
# so the command is allowed for the reason it should be.
#
# WHAT KEEPS IT FROM UNDER-FIRING, which is the only way this can be worse than
# what it replaced. Three things, each with a case of its own:
#
#   * an unparseable command (`shlex` raises on unbalanced quotes) falls back to
#     the raw-text patterns below and stays conservatively REFUSED;
#   * shell punctuation is SPLIT OUT of tokens, not merely stripped from their
#     ends. `shlex.split("echo $(git stash)")` is `['echo', '$(git', 'stash)']`
#     and an exact-token match would allow it; so would `git stash;echo done`,
#     whose middle token is `stash;echo` and which the old regex refused. A
#     separator inside a token is a separator;
#   * a SHELL's `-c` argument is a command, so it is parsed as one. That is what
#     keeps `sh -c "git rebase -i"` caught, which the old comment credited to the
#     text match. `git commit -m` is not a shell and its argument is not a
#     command - which is the whole distinction this change turns on.
#
# THE SEPARATOR SET IS THE COMMAND SEPARATORS AND NOTHING ELSE, and the reason is
# an under-fire found by driving it. A wider set (`{`, `}`, `$`, quotes) split
# ARGUMENT VALUES apart as well as command words: `git stash show -p stash@{0}`
# came back with the arg `stash@` - harmless, since `show` is the sub-verb - but
# the same corruption reaches `git reset --hard HEAD@{2}`, whose ref becomes
# `HEAD@`, which git cannot resolve, which makes `orphaned_by` return nothing,
# which ALLOWS a reset that orphans recorded commits. A reflog ref is exactly the
# spelling somebody reaches for when they are moving a branch pointer around.
# `$(` and `${` need no help: splitting on `(` alone leaves `git` its own word,
# and quotes are gone by the time `shlex` returns.
#
# KNOWN RESIDUAL, measured rather than assumed. Prose no longer fires at all -
# `-m "git;stash"` splits at the `;` and the separator between them is what stops
# it, and `-m "git stash"` stays one word with a space in it, which is not the
# word `git`. What still fires is `git` and a verb quoted as SEPARATE shell words
# (`git commit -m git -m stash`), which is a command line and not a sentence.
# Wrappers whose ARGUMENT is a command, so it is parsed as one. A shell takes it
# behind a `-c` cluster; `eval` takes it as the next word. `sudo`, `env` and
# `xargs` need no entry - they leave the command as ordinary words, which the
# scan below already walks.
SHELLS = ("sh", "bash", "zsh", "dash", "ksh")
EVAL_WRAPPERS = ("eval",)

# Programs that run their argument's text as a program read from a here-string
# (`sh <<<'...'`, `python3 <<<'...'`): the word is graded as a command, through
# the same door as a shell's `-c`. A shell's word is shell; an interpreter's is
# code, read the way the heredoc body fed to it is.
HERESTRING_READERS = SHELLS + ("python", "python3", "node", "nodejs", "ruby",
                               "perl", "php", "deno", "bun")

# Global options that take a SEPARATE value, so the value cannot be mistaken for
# the verb: `git -C <path> rebase` is a rebase, and `<path>` is not the verb.
GLOBAL_VALUE_OPT = ("-C", "-c", "--git-dir", "--work-tree", "--namespace",
                    "--exec-path")

# Shell punctuation that ENDS a command word wherever it appears in one - a
# separator inside a token is a separator, which is why this splits rather than
# stripping the ends. `git stash;echo done` is one `shlex` token in the middle
# (`stash;echo`) and stripping would have allowed it.
_SEP_SPLIT = re.compile(r"([;&|()`<>\n]+)")
_SEP_ONLY = re.compile(r"^[;&|()`<>\n]+$")
_MAX_NEST = 3          # `sh -c "sh -c ..."`; a bound, not a feature


def runnable(command):
    """The text this command RUNS: the same command, minus any heredoc body that
    is on its way into a FILE.

    THE OPERATION IS `cat > probe.py`, NOT THE BYTES IT WRITES. A call whose only
    act was writing a probe file was refused for a force push, because the file's
    content carried one as a test payload - and the way past a guard like that is
    another tool, after which it guards nothing. A body fed to an interpreter or
    a shell is still text a machine runs and every rule below still reads it;
    `_config.split_heredocs` draws that line, and this file has no copy of it
    because a hook may not import another hook and two copies would drift.

    Every reading goes through here - `git_invocations` at its entry, and each
    arm's raw-text fallback - so the parse and the fallback can never grade
    different strings, and no call site can forget. It is its own function
    rather than a call inside the lexer for the same reason `shell_words` is not
    the place a policy lives: the lexer reads what it is handed, and a case can
    hand it a body on purpose.
    """
    return _config.runnable_text(command or "")


def shell_words(command):
    """(words, parsed) - the command as shell WORDS, separators marked as None.

    `parsed` is False when `shlex` could not read the line at all, and then
    `words` is empty and the caller MUST use the text patterns instead. It is a
    separate answer rather than an empty list because "no words" and "could not
    be read" lead to opposite verdicts, and the second one must never be quiet.

    THE LEXER IS BUILT BY HAND BECAUSE `shlex.split` DROPS NEWLINES.
    A newline is whitespace to it, so it never reaches a token, `_SEP_SPLIT`'s
    `\\n` was inert in both directions, and the FIRST verb's argument loop
    swallowed every command after it - `git_invocations` returned one pair for a
    whole multi-line script. Measured: `git status` newline `git push --force`
    was ALLOWED where the raw-text version refused it, and so was
    `git stash list` newline `git stash drop`, which is the exact shape
    `stash_operations` below says must be caught. A multi-line Bash call is the
    ordinary shape, so this was the spelling most likely to be typed.
    `punctuation_chars` does not help: it emits `; & | < >` and still not `\\n`.

    Taking `\\n` out of the whitespace set rather than splitting the string on it
    first is deliberate - splitting first would cut a QUOTED multi-line argument
    into unbalanced halves, `shlex` would raise, and every multi-line commit
    message would land in the conservative text fallback.
    """
    pieces, parsed = _shell_pieces(command)
    return ([None if sep else piece for piece, sep in pieces], parsed)


def _shell_pieces(command):
    """(pieces, parsed) - `shell_words` before the separators lose their
    spelling: each piece is (text, is_separator). `git_calls` needs to know
    WHICH separator ends a command, because a pipe hands the command's output
    to whatever is on its far side and a `;` does not."""
    try:
        # The shell removes backslash-newline before it reads a word, so this
        # does too: kept, the escaped newline split one pipeline into two.
        lex = shlex.shlex(_config.join_continuations(command or ""), posix=True)
        lex.whitespace_split = True
        lex.commenters = ""          # `shlex.split(comments=False)` does this too
        lex.whitespace = " \t\r"     # `\n` stays IN the token, for _SEP_SPLIT
        raw = list(lex)
    except ValueError:
        return ([], False)
    out = []
    for word in raw:
        for piece in _SEP_SPLIT.split(word):
            if not piece:
                continue
            out.append((piece, bool(_SEP_ONLY.match(piece))))
    return (out, True)


def program_name(word):
    """A command word's program name: basename, no `.exe`, folded to lower case.

    Comparing the whole word missed `/usr/bin/git push --force`, which the
    raw-text version caught because `\\bgit\\b` matches after a `/`. Windows
    spellings fold in here too - CI runs these suites on it, and `git.exe` is the
    same program.
    """
    name = (word or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def _is_shell_command_flag(word):
    """A shell's command flag: `-c`, and every CLUSTER it really appears in.

    This read `word.endswith("c")`, which accepts `-lc` and `-ic` and
    misses `-cx`, `-cv` and `-ce`. A cluster is a SET of short options, so the
    question is whether `c` is in it and not where it sits.
    """
    return (word.startswith("-") and not word.startswith("--")
            and "c" in word[1:])


def _has_option(args, name):
    """Is this long option present, in either spelling git accepts?

    `"--force-with-lease" in args` is exact-token equality, and the
    ORDINARY spelling passes a ref - `--force-with-lease=origin/main`. Every
    `=`-taking option goes through here for that reason. It also keeps the two
    force spellings apart: `--force-with-lease` is not `--force` and does not
    start with `--force=`, so the specific reason still wins.
    """
    return any(arg == name or arg.startswith(name + "=") for arg in args)


def _has_short_flag(args, letter):
    """Is this short option present, alone or inside a CLUSTER?

    `git push -fu origin main` is a force-push and `"-f" in args` cannot see it,
    because git's own parse-options clusters short flags. Pre-existing in the
    raw-text version too; closed here because the cost is one comprehension.
    """
    return any(arg.startswith("-") and not arg.startswith("--")
               and letter in arg[1:] for arg in args)


def help_requested(args):
    """Is this invocation asking for DOCUMENTATION rather than doing anything?

    `git stash --help` and `git rebase -h` print a manual page and exit, so
    refusing them refuses a READ - the failure mode this whole file is organised
    around, and `git stash --help` was being refused where the raw-text version
    allowed it.

    Only among the LEADING flags, and that narrowing has a measured reason:
    `git stash push -m --help` really does stash, and there `push` precedes the
    flag. The residual is a message whose value is literally `--help` passed
    before any sub-verb, which is a crafted string rather than a mistake.
    """
    for arg in args:
        if arg in ("--help", "-h"):
            return True
        if not arg.startswith("-"):
            return False
    return False


# The verb of a `git` that `xargs` runs with no verb on its own command line:
# the verb arrives on stdin, which this guard cannot read. A value, not an
# absence, because `echo stash | xargs git` is an operation this hook cannot
# name - refused while a plan exists, like a stash (see `decide`).
STDIN_VERB = "<stdin>"


def _quoted_substitutions(text):
    """The bodies of every `$(...)` and backquote INSIDE DOUBLE QUOTES in
    `text` - commands the shell runs that the lexer returns as one word.

    `echo "$(git stash)"` came back from `shlex` as the single word
    `$(git stash)`, split at its parentheses into `git stash` with a space in
    it, which is not the word `git`: the stash ran unread, and so did
    `eval "$(echo ...)"` and `sh -c "$(echo ...)"`. An unquoted substitution
    needs none of this - its parentheses are separators already. A single-
    quoted one is literal text and is skipped.

    -> the bodies, or None when a substitution never closes - an unreadable
    command, which the caller hands to the raw-text reading rather than
    reading as one that runs nothing. Quotes and escapes INSIDE `$( )` are
    tracked, so a quoted `)` does not end it early."""
    out, quote, i, n = [], None, 0, len(text)
    while i < n:
        ch = text[i]
        if quote == "'":
            if ch == "'":
                quote = None
            i += 1
            continue
        if ch == "\\":
            i += 2
            continue
        if ch == '"':
            quote = None if quote == '"' else '"'
            i += 1
            continue
        if ch == "'" and quote is None:
            quote = "'"
            i += 1
            continue
        if quote == '"' and text.startswith("$(", i):
            j = _substitution_end(text, i + 2)
            if j is None:
                return None
            out.append(text[i + 2:j])
            i = j + 1
            continue
        if quote == '"' and ch == "`":
            j = text.find("`", i + 1)
            if j < 0:
                return None
            out.append(text[i + 1:j])
            i = j + 1
            continue
        i += 1
    return out


# The names git runs as hooks. A file with one of these names is run by git
# itself on the next matching operation, wherever `core.hooksPath` points, so
# writing a command into one is running it with no second command at all.
_GIT_HOOK_NAMES = frozenset((
    "applypatch-msg", "pre-applypatch", "post-applypatch", "pre-commit",
    "pre-merge-commit", "prepare-commit-msg", "commit-msg", "post-commit",
    "pre-rebase", "post-checkout", "post-merge", "pre-push", "pre-receive",
    "update", "proc-receive", "post-receive", "post-update",
    "reference-transaction", "push-to-checkout", "pre-auto-gc", "post-rewrite",
    "sendemail-validate", "fsmonitor-watchman", "p4-changelist",
    "p4-prepare-changelist", "p4-post-changelist", "p4-pre-submit",
    "post-index-change"))
# The one kind of program whose arguments ARE what it prints. For any other
# program an argument naming a git phrase is a search term, a message or a
# path, and what reaches the far side is the program's own output.
_TEXT_EMITTERS = ("echo", "printf")
# Programs that print what arrives on their stdin, so a here-string fed to one
# is what it prints.
_STDIN_PRINTERS = ("cat",)
# Programs that run what arrives on their stdin, beside the shells.
_STDIN_RUNNERS = ("eval", "source", ".")
# Programs that run a file named as their argument.
_FILE_RUNNERS = ("source", ".", "make")
# Reserved words that may lead a simple command without being its program.
_RESERVED_LEAD = ("then", "do", "else", "elif", "if", "while", "until", "!",
                  "time", "{")
# Compound commands: the word that opens one and the word that closes it.
_COMPOUND = {"if": "fi", "while": "done", "until": "done", "for": "done",
             "select": "done", "case": "esac", "{": "}"}
# Longest first, so `>>` is not read as two `>`.
_OPERATORS = ("<<<", "&&", "||", ";;", ">>", ">|", ">&", "&>", "|&", "<<", "<&",
              ";", "|", "&", ">", "<", "(", ")", "\n")
_REDIRECTS = (">", ">>", ">|", "&>", ">&")
_GLOB = re.compile(r"[*?\[]")


def _op_tokens(text):
    """[(text, is_operator)] for `text`, or None when a quote never closes.

    OPERATORS COUNT ONLY OUTSIDE QUOTES, and a COMMENT is not text at all. The
    lexer `git_calls` shares splits a separator out of a token wherever it
    sits, which is the conservative reading for finding a git word - and the
    wrong one for deciding where a stage's output goes, because a `>` inside a
    commit message, or after a `#`, is text. A substitution or a backquote is
    kept whole inside its word."""
    out, cur, quote, i, n, has = [], [], None, 0, len(text), False
    while i < n:
        ch = text[i]
        if quote == "'":
            if ch == "'":
                quote = None
            else:
                cur.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            if text[i + 1] != "\n":
                cur.append(text[i + 1])
                has = True
            i += 2
            continue
        if text.startswith("$(", i):
            j = _substitution_end(text, i + 2)
            if j is None:
                return None
            cur.append(text[i:j + 1])
            has = True
            i = j + 1
            continue
        if ch == "`":
            j = text.find("`", i + 1)
            if j < 0:
                return None
            cur.append(text[i:j + 1])
            has = True
            i = j + 1
            continue
        if quote == '"':
            if ch == '"':
                quote = None
            else:
                cur.append(ch)
            i += 1
            continue
        if ch == "#" and not has:
            end = text.find("\n", i)
            i = n if end < 0 else end
            continue
        if ch in "'\"":
            quote = ch
            has = True
            i += 1
            continue
        if ch in " \t\r":
            if has:
                out.append(("".join(cur), False))
                cur, has = [], False
            i += 1
            continue
        op = next((o for o in _OPERATORS if text.startswith(o, i)), None)
        if op:
            if has:
                out.append(("".join(cur), False))
                cur, has = [], False
            out.append((op, True))
            i += len(op)
            continue
        cur.append(ch)
        has = True
        i += 1
    if quote:
        return None
    if has:
        out.append(("".join(cur), False))
    return out


def _new_stage():
    return {"words": [], "targets": [], "to": None, "here": []}


def _stages(tokens):
    """(stages, groups) for a command's tokens.

    Each stage represents a simple command: its `words`, the files its output is
    redirected into (`targets`), the here-strings fed to it (`here`), and `to`,
    the index of the stage its output is piped into. `groups` are the
    [start, end] stage ranges of each compound command - `( )`, `{ }`,
    `if ... fi`, a loop, `case ... esac` - whose pipe or redirect reaches every
    stage inside it. A `case` pattern's `(` and `)` are not a group."""
    out, groups, opened = [_new_stage()], [], []
    closed, pattern = None, False
    at = 0
    while at < len(tokens):
        text, is_op = tokens[at]
        at += 1
        cur = out[-1]
        top = opened[-1][1] if opened else None
        if not is_op:
            if not cur["words"] and text in _COMPOUND:
                opened.append((len(out) - 1, text))
                pattern = False
                if text == "{":
                    continue
            elif not cur["words"] and opened \
                    and text == _COMPOUND.get(top) and text != "{":
                closed = (opened.pop()[0], len(out) - 1)
                continue
            elif top == "case" and text == "in" \
                    and len(cur["words"]) == len(("case", "subject")):
                pattern = True
            cur["words"].append(text)
            closed = None
            continue
        if top == "case" and pattern and text in ("(", ")"):
            if text == ")":
                pattern = False
                out.append(_new_stage())
            continue
        if text == "(":
            if cur["words"] or cur["targets"]:
                out.append(_new_stage())
            opened.append((len(out) - 1, "("))
            continue
        if text == ")":
            if opened and top == "(":
                closed = (opened.pop()[0], len(out) - 1)
            continue
        members = range(closed[0], closed[1] + 1) if closed \
            else [len(out) - 1]
        if closed:
            groups.append(list(closed))
        if text in _REDIRECTS:
            target = _redirect_target(tokens, at)
            at = target[1]
            if target[0] is None or (text == ">&" and target[0].isdigit()):
                continue
            for m in members:
                out[m]["targets"].append(target[0])
            continue
        if text in ("<", "<<", "<&"):
            if at < len(tokens) and not tokens[at][1]:
                at += 1
            continue
        if text == "<<<":
            if at < len(tokens) and not tokens[at][1]:
                cur["here"].append(tokens[at][0])
                at += 1
            continue
        if text in ("|", "|&"):
            for m in members:
                out[m]["to"] = len(out)
        if text == ";;" and top == "case":
            pattern = True
        out.append(_new_stage())
        closed = None
    if closed:
        groups.append(list(closed))
    return (out, groups)


def _redirect_target(tokens, at):
    """(target or None, next index) for the redirect operator ending at `at`.

    A process substitution is followed rather than named: `>(sh)` runs what
    it is given, so it is recorded as the target `>(`; `>(cat)` only prints it,
    so it is no target at all."""
    if at >= len(tokens):
        return (None, at)
    if tokens[at] == ("(", True):
        depth, end = 1, at + 1
        while end < len(tokens) and depth:
            if tokens[end] == ("(", True):
                depth += 1
            elif tokens[end] == (")", True):
                depth -= 1
            end += 1
        inner, groups = _stages(tokens[at + 1:end - 1])
        runs = any(_runs_input(stage) or _output_runs(inner, groups, index)
                   or any(_target_runs(target, inner, index)
                          for target in _tee_targets(stage))
                   for index, stage in enumerate(inner))
        return (">(" if runs else None, end)
    if tokens[at][1]:
        return (None, at)
    return (tokens[at][0], at + 1)


def _program_words(stage):
    """The stage's words with the reserved words that lead it stepped over."""
    words = list(stage["words"])
    while words and words[0] in _RESERVED_LEAD:
        words = words[1:]
    return words


def _printed(stage, depth=0):
    """What a text-emitter stage prints, as one line, or "" for any other.

    `echo` prints its words joined by blanks, so a phrase split across
    arguments is one line on the far side. A `cat` fed a here-string prints it.
    A substitution inside a printed word contributes what an emitter inside it
    prints."""
    rest, candidates = _config.program_candidates(_program_words(stage))
    for word in candidates:
        name = program_name(word)
        if name in _STDIN_PRINTERS and stage["here"]:
            return " ".join(stage["here"])
        if name in _TEXT_EMITTERS and word in rest:
            words = rest[rest.index(word) + 1:]
            return " ".join(_expand_printed(w, depth) for w in words)
    return ""


def _expand_printed(word, depth):
    """`word` with each `$(...)` in it replaced by what its body prints."""
    if depth >= _MAX_NEST or "$(" not in word:
        return word
    out, i = [], 0
    while True:
        at = word.find("$(", i)
        if at < 0:
            out.append(word[i:])
            return "".join(out)
        end = _substitution_end(word, at + 2)
        if end is None:
            out.append(word[i:])
            return "".join(out)
        out.append(word[i:at])
        tokens = _op_tokens(word[at + 2:end]) or []
        inner, _groups = _stages(tokens)
        out.append(" ".join(p for p in (_printed(s, depth + 1) for s in inner)
                            if p))
        i = end + 1


def _runs_input(stage):
    """Whether the stage runs what arrives on its stdin."""
    rest, candidates = _config.program_candidates(_program_words(stage))
    if rest and ("$" in rest[0] or "`" in rest[0]):
        return True
    for word in candidates:
        if _config.is_shell(word):
            return True
        if program_name(word) in _STDIN_RUNNERS:
            args = rest[rest.index(word) + 1:] if word in rest else []
            return not args or args[0] in ("/dev/stdin", "-")
    return False


def _tee_targets(stage):
    """The files a `tee` stage writes its input into."""
    rest, candidates = _config.program_candidates(_program_words(stage))
    for word in candidates:
        if program_name(word) == "tee" and word in rest:
            return [w for w in rest[rest.index(word) + 1:]
                    if not w.startswith("-")]
    return []


def _passes_input(stage):
    """Whether `stage` carries its stdin to its own redirect target."""
    rest, candidates = _config.program_candidates(_program_words(stage))
    return any(program_name(word) in _STDIN_PRINTERS for word in candidates
               if word in rest)


def _read_variables(stages):
    """Names set by `read` in the receiving compound command."""
    names = []
    for stage in stages:
        words = _program_words(stage)
        if "read" not in words:
            continue
        index = words.index("read") + 1
        while index < len(words) and words[index].startswith("-"):
            index += 1
        if index < len(words):
            names.append(words[index])
    return names


def _runs_read_variable(stages):
    """Whether a receiving group evaluates a variable it read from its stdin."""
    names = _read_variables(stages)
    if not names:
        return False
    for stage in stages:
        rest, candidates = _config.program_candidates(_program_words(stage))
        for word in candidates:
            if program_name(word) not in _STDIN_RUNNERS or word not in rest:
                continue
            args = rest[rest.index(word) + 1:]
            if any(arg in ("$" + name, "${" + name + "}") for name in names
                   for arg in args):
                return True
    return False


def _runs_file(stage, target):
    """Whether `stage` runs the file `target` names."""
    words = _program_words(stage)
    if not words:
        return False
    plain = target[2:] if target.startswith("./") else target
    if words[0] in (target, "./" + plain):
        return True
    rest, candidates = _config.program_candidates(words)
    programs = [program_name(w) for w in candidates]
    if "make" in programs and os.path.basename(plain).lower() in (
            "makefile", "gnumakefile"):
        return True
    return any(_config.is_shell(w) or program_name(w) in _FILE_RUNNERS
               for w in candidates) and any(
        w in (target, plain, "./" + plain) for w in rest[1:])


def _stage_changes_to_hooks(stage):
    """Whether `stage` changes into a git hooks directory."""
    words = _program_words(stage)
    return (len(words) > 1 and program_name(words[0]) == "cd"
            and "hook" in words[1].replace("\\", "/").lower())


def _is_hook_path(target, stages, after):
    """Whether git runs `target` as a hook: anything under `.git/hooks/` or a
    `.husky/` directory, or a file named as a hook in a directory whose own
    name says it holds hooks (`core.hooksPath` may name any). Case is folded:
    the default filesystems of two supported platforms fold it too."""
    norm = "/" + target.replace("\\", "/").lower()
    if "/.git/hooks/" in norm or "/.husky/" in norm:
        return True
    parent, name = os.path.split(norm)
    if name not in _GIT_HOOK_NAMES:
        return False
    return ("hook" in os.path.basename(parent)
            or any(_stage_changes_to_hooks(stage) for stage in stages[:after]))


def _target_runs(target, stages, after):
    """Whether writing into `target` is running what was written."""
    if target == ">(" or "$" in target or "`" in target or _GLOB.search(target):
        return True
    if _is_hook_path(target, stages, after):
        return True
    return any(_runs_file(later, target) for later in stages[after + 1:])


def _receivers(stages, groups, to):
    """The stages a pipe into stage `to` feeds: the whole compound command
    that begins there, or that one stage."""
    spans = [g for g in groups if g[0] == to]
    if not spans:
        return [stages[to]]
    end = max(g[1] for g in spans)
    return stages[to:end + 1]


def _output_runs(stages, groups, at):
    """Whether what stage `at` prints is then RUN: piped into a program that
    runs its stdin, written (by a redirect or through `tee`) into a git hook,
    into a target the reading cannot resolve, or into a file a later stage of
    the same command runs."""
    stage = stages[at]
    targets = list(stage["targets"])
    to = stage["to"]
    while to is not None and to < len(stages):
        receivers = _receivers(stages, groups, to)
        if any(_runs_input(r) for r in receivers) or _runs_read_variable(receivers):
            return True
        tees = [t for r in receivers for t in _tee_targets(r)]
        passed = [t for r in receivers if _passes_input(r) for t in r["targets"]]
        if not tees and not passed:
            break
        targets += tees + passed + [t for r in receivers for t in r["targets"]]
        to = receivers[-1]["to"]
    return any(_target_runs(t, stages, at) for t in targets)


def _substitution_end(text, start):
    """The index of the `)` that closes a `$(` whose body starts at `start`, or
    None when it never closes. Parentheses count only outside quotes, and a
    backslash escapes the character after it, which is how the shell reads the
    body too.

    A `case` PATTERN'S `)` IS NOT A CLOSE. The depths at which a `case`
    opened in command position has not yet met its `esac` are kept as a stack;
    a `)` at the depth of the innermost open one ends a pattern, so the body
    is read to its real end rather than cut at the first arm - at any nesting,
    and after a parenthesised pattern too. A `case` that is an ordinary word (`echo worst case`) is not the
    keyword: only a word in command position counts."""
    depth, quote, j, n = 1, None, start, len(text)
    open_at, word, word_cmd, cmd_pos = [], [], False, True
    while j < n:
        ch = text[j]
        if quote == "'":
            if ch == "'":
                quote = None
        elif ch == "\\":
            if not word:
                word_cmd = cmd_pos
            word.append(ch)
            j += 1
        elif quote == '"':
            if ch == '"':
                quote = None
        elif ch in ("'", '"'):
            if not word:
                word_cmd = cmd_pos
            word.append(ch)
            quote = ch
        elif ch in " \t\n;&|()":
            if word:
                done = "".join(word)
                if word_cmd and done == "case":
                    open_at.append(depth)
                elif word_cmd and done == "esac" and open_at \
                        and open_at[-1] == depth:
                    open_at.pop()
                cmd_pos = done in _OPENS_COMMAND
                word = []
            if ch in "\n;&|(":
                cmd_pos = True
            if ch == "(":
                depth += 1
            elif ch == ")":
                if open_at and open_at[-1] == depth:
                    cmd_pos = True
                else:
                    depth -= 1
                    cmd_pos = False
                    if depth == 0:
                        return j
                    if open_at and open_at[-1] == depth:
                        cmd_pos = True
        else:
            if not word:
                word_cmd = cmd_pos
            word.append(ch)
        j += 1
    return None


# Reserved words after which the next word is again in command position.
_OPENS_COMMAND = ("then", "do", "else", "elif", "if", "while", "until", "!",
                  "{", "time")


def git_invocations(command, depth=0):
    """[(verb, [args]), ...] for every `git` this command RUNS, or None - the
    `git_calls` answer without the directory each one runs in."""
    calls = git_calls(command, depth)
    return None if calls is None else [(verb, args) for verb, args, _d in calls]


def git_calls(command, depth=0):
    """[(verb, [args], dir), ...] for every `git` this command RUNS, or None.
    `dir` is the `-C` value the invocation names, joined when there are
    several, or None - the directory git runs in is part of what it does.

    None means the command could not be parsed - the signal for the text
    fallback. An empty LIST means it parsed and runs no git, which is the
    ordinary answer and must not be confused with the first.

    A verb's args stop at a SEPARATOR, so `git push origin main; echo --force`
    is not read as a force-push - which it would be if the separators were
    thrown away rather than marked.

    They deliberately do NOT stop at a second `git`. That rule was tried and
    removed: it bought no coverage (`sudo git stash drop` and `xargs git stash
    drop` are found by the word scan either way) and it cost a false refusal on
    `git log --grep git --grep stash`, where the second `git` is a search term.

    The text is passed through `runnable()` FIRST: a heredoc body on its way into
    a file is not something this command runs, so it must not be able to
    contribute a verb. Doing it at this one door rather than at the four arms is
    what makes it impossible for one arm to forget, and the recursion below
    re-enters the same door, so no nesting depth is graded by a different rule.
    """
    text = runnable(command)
    pieces, parsed = _shell_pieces(text)
    if not parsed:
        return None
    words = [None if sep else piece for piece, sep in pieces]
    out = []
    # A here-string's word fed to a shell or an interpreter is the program it
    # runs: `sh <<<'git stash'` is a stash spelled as one quoted word. The
    # reader is found past a wrapper that runs its argument (`env sh <<<...`),
    # by the same step the heredoc head is read with.
    for at, (piece, sep) in enumerate(pieces):
        if not (sep and piece == "<<<") or depth >= _MAX_NEST:
            continue
        if at + 1 >= len(pieces) or pieces[at + 1][1]:
            continue
        start = at
        while start > 0 and not pieces[start - 1][1]:
            start -= 1
        _rest, readers = _config.program_candidates(
            piece for piece, _sep in pieces[start:at])
        if any(program_name(word) in HERESTRING_READERS for word in readers):
            nested = git_calls(pieces[at + 1][0], depth + 1)
            if nested is None:
                return None
            out.extend(nested)
    # A git command QUOTED AS ONE PHRASE is one word to the lexer, and it is a
    # command wherever a text emitter's output is run: the line the emitter
    # prints is read as a command line of its own, the way a shell's -c
    # argument is. The stages are read by their own lexer, which sees an
    # operator only outside quotes.
    if depth < _MAX_NEST:
        tokens = _op_tokens(_config.join_continuations(text))
        if tokens is None:
            return None
        stages, groups = _stages(tokens)
        for at, stage in enumerate(stages):
            line = _printed(stage)
            if not line or not _output_runs(stages, groups, at):
                continue
            nested = git_calls(line, depth + 1)
            if nested is None:
                return None
            out.extend(nested)
    # A substitution inside double quotes is one word to the lexer and a
    # command to the shell, so its body is read as one. A body this cannot
    # read makes the whole command unreadable (None), which sends every arm to
    # its raw-text reading - never to a reading that contributes nothing.
    if depth < _MAX_NEST:
        inners = _quoted_substitutions(_config.join_continuations(text))
        if inners is None:
            return None
        for inner in inners:
            nested = git_calls(inner, depth + 1)
            if nested is None:
                return None
            out.extend(nested)
    index, total = 0, len(words)
    while index < total:
        word = words[index]
        if word is None:
            index += 1
            continue
        program = program_name(word)
        if depth < _MAX_NEST and program in SHELLS:
            scan = index + 1
            while scan < total and words[scan] is not None:
                if _is_shell_command_flag(words[scan]) and scan + 1 < total \
                        and words[scan + 1]:
                    nested = git_calls(words[scan + 1], depth + 1)
                    out.extend(nested or [])
                    break
                scan += 1
        elif depth < _MAX_NEST and program in EVAL_WRAPPERS:
            # `eval "git push --force"` saw NO git: `eval` was in no
            # wrapper table, its argument stayed one token, and the fallback is
            # only reached when the line will not parse - which this one does.
            # It takes the command as its next word rather than behind a flag.
            scan = index + 1
            while scan < total and words[scan] is not None:
                if not words[scan].startswith("-"):
                    out.extend(git_calls(words[scan], depth + 1) or [])
                    break
                scan += 1
        if program != "git":
            index += 1
            continue
        index += 1
        cdir = None
        while index < total and words[index] is not None \
                and words[index].startswith("-"):
            opt = words[index]
            takes_value = opt in GLOBAL_VALUE_OPT
            index += 1
            if takes_value and index < total and words[index] is not None:
                if opt == "-C":
                    cdir = (words[index] if cdir is None
                            else os.path.join(cdir, words[index]))
                index += 1
        if index >= total or words[index] is None:
            # `git` with no verb after it - unless `xargs` runs it, in which
            # case the verb comes from stdin and is an operation unread.
            start = index - 1
            while start > 0 and words[start - 1] is not None:
                start -= 1
            if "xargs" in [program_name(w) for w in words[start:index]
                           if w is not None]:
                out.append((STDIN_VERB, [], cdir))
            continue
        verb = words[index]
        index += 1
        args = []
        while index < total and words[index] is not None:
            args.append(words[index])
            index += 1
        out.append((verb, args, cdir))
    return out


# --- the text fallback --------------------------------------------------------
# THE VERB HAS TO BE IN SUBCOMMAND POSITION, not merely somewhere in the
# line. These patterns used to read `\bgit\b[^|;&]*\bVERB\b`, which lets any text
# at all sit between the two — so a COMMIT MESSAGE naming one of these operations
# was graded as performing it. Measured, all four refused:
#
#     git commit -m "the remedy is a rebase this document forbids"
#     git commit -m "docs: never rebase the phase branch"
#     git commit -m "chore: document why filter-branch is refused"
#     git log --grep "rebase"                       <- a READ
#
# The last one is the tell: nothing about `git log` can rewrite anything. This is
# `guard-secrets-read` had the same defect in a second hook — a guard grading TEXT
# rather than the operation — and it has the same consequence, which is why it is
# fixed the
# same way rather than exempted. It refused this repository's own commit
# documenting the rule, and then refused the probe written to measure it, which is
# a guard teaching the person it protects to work around it.
#
# `git`, then GLOBAL OPTIONS ONLY, then the verb. `-C <path>` and `-c <k=v>` take a
# value and are spelled out so the value cannot be mistaken for the verb.
#
# THIS CONSIDERED NARROWING THE LONG-OPTION ARM TO GIT'S ACTUAL GLOBAL SET and
# measured no reason to. The worry was that a generic `--[a-z][a-z-]*` admits a
# POST-verb option whose separate value would then land in verb position, making
# `git log --grep stash` read as the operation. It cannot: the option group has to
# match CONTIGUOUSLY after `git`, and in that command the token after `git` is
# `log`, so the group matches nothing and `log` is the verb. Driven against both
# patterns, the only commands they disagree about are `git --grep stash` and
# `git --frobnicate stash` — neither is a command git accepts, and on those the
# generic arm refuses where a closed set would allow. So the narrowing would have
# traded a hand-kept table of git's global options for a slightly weaker guard, on
# input git itself rejects. Recorded here because the next reader will have the
# same worry, and the probe that settles it is a regex comparison over both.
_GIT_SUB = (r"\bgit\b(?:\s+(?:-C(?:\s+(?:\"[^\"]*\"|'[^']*'|\S+)|\S+)|-c\s+\S+"
            r"|--(?:git-dir|work-tree|namespace|exec-path)(?:=\S*|\s+\S+)"
            r"|--[a-z][a-z-]*))*\s+")

# THESE PATTERNS ARE NO LONGER THE PRIMARY READING. They decide only a command
# `shlex` could not parse, where their over-firing on quoted text is the
# conservative direction and the right one: an unparseable line naming a whole
# forbidden command is refused rather than guessed at. On everything else
# `git_invocations` above answers first, and it answers on the operation.

# Operations that rewrite or discard history wholesale. There is no ancestry
# question to ask about these: `--orphan` starts a branch with no history at all,
# `filter-branch` rewrites every SHA it touches, and a force-push replaces what
# other clones already have.
# ONE HOME PER REASON, because two readings of the command now share them and a
# refusal whose wording depended on which reading answered would be two guards.
WHY_FORCE = "force-push replaces history other clones already have"
WHY_LEASE = "force-push (--force-with-lease still replaces the remote's history)"
WHY_ORPHAN = ("an orphan branch starts with no history, so every recorded commit "
              "is unreachable from it")
WHY_FILTER = "filter-branch/filter-repo rewrites every SHA it touches"
WHY_REBASE = ("rebasing rewrites the SHAs recorded in the manifest "
              "(reference/orchestrator.md states this as an invariant)")

_ALWAYS = (
    (re.compile(_GIT_SUB + r"push\b[^|;&]*(--force\b(?!-with-lease)|(?<![\w-])-f(?![\w-]))"),
     WHY_FORCE),
    (re.compile(_GIT_SUB + r"push\b[^|;&]*--force-with-lease\b"), WHY_LEASE),
    (re.compile(_GIT_SUB + r"(checkout|switch)\b[^|;&]*--orphan\b"), WHY_ORPHAN),
    (re.compile(_GIT_SUB + r"filter-(branch|repo)\b"), WHY_FILTER),
    (re.compile(_GIT_SUB + r"rebase\b(?![^|;&]*--abort)"), WHY_REBASE),
)

_RESET_HARD = re.compile(_GIT_SUB + r"reset\b[^|;&]*--hard\b([^|;&]*)")
_AMEND = re.compile(_GIT_SUB + r"commit\b[^|;&]*--amend\b")
_FLAGS = re.compile(r"(^|\s)-{1,2}[A-Za-z][\w-]*(=\S*)?")


# --- the four arms, each on the operation with the text patterns behind it -----
# Every arm below takes the raw command and reads it through `git_invocations`,
# falling back to its own pattern above when the line will not parse. Each parses
# for itself rather than being handed a shared parse: `shlex.split` on a command
# line costs microseconds against a process spawn of tens of milliseconds, and
# `tools/bench-hooks.py --gate` is what guards the cost that is real here, which
# is what this module IMPORTS.
def always_refused(command):
    """The reason this command rewrites or discards history, or None.

    The verdict is the FIRST matching operation, and the two force-push spellings
    are asked in the order that keeps their reasons apart: `--force-with-lease`
    is named for what it is rather than reported as a plain force-push.
    """
    invocations = git_invocations(command)
    if invocations is None:
        text = runnable(command)       # the fallback grades the same text
        for pattern, why in _ALWAYS:
            if pattern.search(text):
                return why
        return None
    for verb, args in invocations:
        if help_requested(args):
            continue                       # documentation, not an operation
        if verb == "push":
            if _has_option(args, "--force-with-lease"):
                return WHY_LEASE
            if _has_option(args, "--force") or _has_short_flag(args, "f"):
                return WHY_FORCE
        if verb in ("checkout", "switch") and _has_option(args, "--orphan"):
            return WHY_ORPHAN
        if verb in ("filter-branch", "filter-repo"):
            return WHY_FILTER
        if verb == "rebase" and not _has_option(args, "--abort"):
            return WHY_REBASE
    return None


def amend_requested(command):
    """Does this command amend a commit? True/False, never a maybe."""
    invocations = git_invocations(command)
    if invocations is None:
        return bool(_AMEND.search(runnable(command)))
    return any(verb == "commit" and _has_option(args, "--amend")
               and not help_requested(args)
               for verb, args in invocations)

# --- the stash arm -------------------------------------------------------------
# `git stash` is the OTHER half of this hook and it asks a different question, so
# the two must not be read as one rule. Everything above asks "would a COMMIT the
# manifest records stop being reachable" — a question about published history, and
# one a repo with no recorded SHA cannot lose. Stash is the one git verb that
# removes work which was never committed at all: there is no commit to find it by
# and nothing in the plan that says it happened.
#
# It is not hypothetical. A `git stash push --keep-index` inside a compound command
# took a whole session's uncommitted work out of an audit checkout in one step,
# across tasks, with nothing asked and nothing refused — every guard in this plugin
# allowed it. `reference/orchestrator.md` lists `stash` among its invariants and
# repeats the ban in the executor prompt for the sharper reason: parallel tasks
# share ONE working tree, so a stash takes the siblings' edits with it.
#
# THE PUSH HALF OF THAT SENTENCE IS DELIBERATELY NOT ENFORCED, and this is the
# place the decision is recorded so a later reader does not read the gap as an
# oversight. A hook refusing `git push` would stop the human operator on every
# release; a guard that fires on correct work gets routed around within a day, and
# then it is not protecting the stash half either. `tools/check-prohibitions.py`
# carries the push row as advisory-with-a-reason and DRIVES both halves, so neither
# claim can quietly stop being true.
# `help` is in the READS because `git stash --help` and `-h` print a manual page
# and change nothing - see `help_requested`, which is what maps them here.
STASH_READS = ("list", "show", "help")
STASH_SUBCOMMANDS = ("apply", "branch", "clear", "create", "drop", "list",
                     "pop", "push", "save", "show", "store")
# `(?![\w-])` and not `\b`: a hyphen is a word BOUNDARY, so `\b` reads `git
# stash-list` as the verb plus an argument. There is no such git command, so the
# refusal would have been harmless and unexplainable, which is the worst pair.
_STASH = re.compile(_GIT_SUB + r"stash(?![\w-])([^|;&]*)")


def stash_operations(command):
    """Every `git stash` sub-verb this command performs, in written order.

    A LIST, and that is the whole reason this is not a `search`: the incident was
    a COMPOUND command, and `git stash list && git stash drop` reads first and
    destroys second. A scanner stopping at the first match would grade the line
    by its harmless half — which is the shape of evasion this hook has already
    been bitten by once, one verb over.

    `""` is a BARE `git stash`, which git performs as `push`. It is a value and
    not an absence because an empty list means "this command does not stash at
    all", and the two lead to opposite verdicts — the same distinction
    `reset_target` draws between `""` and None. An unrecognised first word is
    read as the bare form too (`git stash -- src/app.ts` is a partial push, and
    a sub-verb git has not shipped yet is refused rather than waved through).
    """
    invocations = git_invocations(command)
    if invocations is None:
        return _stash_operations_text(command)
    out = []
    for verb, args in invocations:
        if verb != "stash":
            continue
        if help_requested(args):
            # `git stash --help` and `-h` printed a manual page and were
            # REFUSED, because a leading flag fell through the skip below to the
            # bare form. `moving_stash` states the argument against that: a guard
            # that fires on a read is a guard people route around, and then the
            # destructive verbs are unguarded too.
            out.append("help")
            continue
        sub = ""
        for arg in args:
            if arg.startswith("-"):     # `--`, and any flag before the sub-verb
                continue
            sub = arg if arg in STASH_SUBCOMMANDS else ""
            break
        out.append(sub)
    return out


def _stash_operations_text(command):
    """`stash_operations` for a command that will NOT parse - the raw-text read.

    Its own function rather than an inline branch, so a case can reach it on
    purpose: a fallback nothing exercises is a fallback nobody knows is broken.
    """
    out = []
    for m in _STASH.finditer(runnable(command)):
        rest = _FLAGS.sub(" ", m.group(1) or "")
        sub = ""
        for word in rest.split():
            if word.startswith("-"):    # `--`, and any flag _FLAGS did not eat
                continue
            sub = word if word in STASH_SUBCOMMANDS else ""
            break
        out.append(sub)
    return out


def moving_stash(command):
    """The stash sub-verbs in this command that are not READS.

    `list` and `show` change nothing and MUST stay allowed: a guard that fires on
    a read is a guard people route around, and then the destructive verbs are
    unguarded too. The allowlist is closed rather than open for the reason the
    docstring above gives — `create` and `store` are plumbing nobody types, and
    refusing them costs a spelling while admitting them would mean grading a verb
    on a claim about what it does today.
    """
    return [sub for sub in stash_operations(command) if sub not in STASH_READS]


def manifest_rel(cfg):
    """Where this repo's manifest lives, defaulted. One home, because both arms
    of this hook ask for it now and a guard reading a different manifest in each
    would be inert in one of them for a reason nobody could see."""
    return cfg.get("manifestPath") or _config.DEFAULTS["manifestPath"]


def plan_present(root, cfg):
    """Is there an audit plan here at all? One stat, and the stash arm hangs on it.

    Every other pattern here turns itself on when the manifest RECORDS a SHA. The
    stash arm cannot use that signal: the work it protects is uncommitted, so the
    trail is empty by definition at the moment it matters. It must not be
    unconditional either — a plugin installed for the user that refused `git
    stash` in every unrelated repository is a plugin whose hooks get switched off,
    which is the same failure the ancestry check exists to avoid. A plan on disk
    is the narrowest honest answer to "is this checkout running under the
    orchestrator's invariants".
    """
    try:
        return os.path.exists(os.path.join(str(root), manifest_rel(cfg)))
    except Exception:
        return False


def _stash_reason(moves):
    """The refusal, in terms the reader can act on rather than a rule quoted at them."""
    spelled = ", ".join("`git stash %s`" % sub if sub else "`git stash`"
                        for sub in moves)
    return ("%s moves work between the working tree and the stash, and the stash "
            "is the one place git keeps work with NO commit to find it by and no "
            "name saying what it holds. reference/orchestrator.md lists `stash` "
            "among the invariants and repeats it in every executor prompt, "
            "because parallel tasks share one working tree - a stash there takes "
            "the sibling tasks' edits too. Commit instead: the task's own commit, "
            "or the audit-state commit that keeps a failed run's record. For a "
            "BASELINE use `git diff` or `git show HEAD:<file>`, which is what the "
            "orchestrator already tells subagents to do. `git stash list`, "
            "`git stash show` and `git stash --help` are reads and are not "
            "blocked." % (spelled,))


# --- the trail the history arm protects ---------------------------------------
def recorded_shas(root, cfg):
    """Every `task.commit` the manifest names, with the task that owns it.

    Reads the ASSEMBLED manifest: under the sharded layout the index stubs carry
    no tasks, so a raw read would find no SHAs and the guard would silently
    approve everything on exactly the repos most likely to have a long trail.
    """
    out = []
    try:
        manifest = _config._load_manifest_assembled(
            os.path.join(str(root), manifest_rel(cfg)))
        if not isinstance(manifest, dict):
            return out
        for phase in manifest.get("phases") or []:
            if not isinstance(phase, dict):
                continue
            for task in phase.get("tasks") or []:
                if isinstance(task, dict) and task.get("commit"):
                    out.append((str(task.get("id")), str(task.get("commit"))))
    except Exception:
        return []
    return out


def reset_targets(command):
    """[(target, index)] for EVERY `git reset --hard` this command runs - the
    index is the call's position in `git_calls(command)`, which `call_trees`
    pairs with its tree, or None when the command will not parse and the
    raw-text reading answered. Every reset is graded: the second of
    `git reset --hard && git reset --hard HEAD~5` orphans commits the first
    never touched."""
    calls = git_calls(command)
    if calls is None:
        target = reset_target(command)
        return [] if target is None else [(target, None)]
    out = []
    for index, call in enumerate(calls):
        verb, args = call[0], call[1]
        if verb != "reset" or not _has_option(args, "--hard") \
                or help_requested(args):
            continue
        out.append((next((a for a in args if not a.startswith("-")), ""), index))
    return out


def reset_target(command):
    """The ref a `git reset --hard` names, or "" when it names none.

    "" is the case the whole guard turns on: `git reset --hard` with no ref moves
    no branch pointer, so no commit can stop being reachable. None is the third
    answer - this is not a reset at all - and the three are kept apart because
    "" and None lead to opposite verdicts.
    """
    invocations = git_invocations(command)
    if invocations is None:
        m = _RESET_HARD.search(runnable(command))
        if not m:
            return None
        rest = _FLAGS.sub(" ", m.group(1) or "")
        words = [w for w in rest.split() if w and not w.startswith("-")]
        return words[0] if words else ""
    for verb, args in invocations:
        if verb != "reset" or not _has_option(args, "--hard") \
                or help_requested(args):
            continue
        # `--` separates refs from paths; a pathspec reset touches files, not
        # history, and a flag is never the ref.
        for arg in args:
            if not arg.startswith("-"):
                return arg
        return ""
    return None


def orphaned_by(root, git_root, target, shas):
    """Which recorded SHAs would stop being ancestors of `target`.

    Returns [] when git cannot answer — an unresolvable ref is a command that is
    about to fail on its own, and guessing here would block work over a typo.
    """
    import subprocess
    lost = []
    for task_id, sha in shas:
        try:
            out = subprocess.run(
                ["git", "-C", git_root or root, "merge-base", "--is-ancestor",
                 sha, target],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        except Exception:
            return []
        if out.returncode == 1:          # 1 = not an ancestor; >1 = git could not tell
            lost.append((task_id, sha))
        elif out.returncode > 1:
            return []
    return lost


def command_roots(project, trees):
    """The trees whose plans this command's git invocations answer to: the
    project first, then each linked worktree of it that one of them runs in.

    WHERE GIT RUNS IS PART OF WHAT IT DOES. `git -C <dir>` runs in `<dir>`,
    resolved from wherever the shell stands; the shell stands where the
    payload's `cwd` says, moved by any `cd` the command makes first
    (`_config.effective_cwd`, the reading `guard-secrets-read` places its write
    targets with). `_config.tree_for` then says whose tree each directory is.
    The recorded SHAs a worktree's plan holds are the commits ITS tasks made,
    which the project's copy does not carry until a merge - reading only the
    project's let a rebase of the worktree branch orphan them unrefused.

    The project stays first whatever the command did, and the union is the
    conservative direction for a guard: a commit recorded in either plan is
    one this command may not orphan. A `-C` value or a `cd` this cannot read
    is refused for a history rewrite while a plan exists, rather than placed
    in the project. `trees` is `call_trees`' answer."""
    roots = [project]
    for _call, tree in trees:
        if tree is not None and all(
                not _config._same_dir(tree, r) for r in roots):
            roots.append(tree)
    return roots


def call_trees(data, cfg, project, command, calls):
    """[(call, the linked worktree it runs in, or None for the project)] -
    one entry per git invocation, in written order.

    Refs resolve per working tree (`HEAD`, `HEAD~1`, `ORIG_HEAD`), so the tree
    a reset or an amend is asked about is ITS OWN, not the first one the
    command reached: in `git -C <a> status; git -C <b> reset --hard HEAD~1`
    the `HEAD~1` is `<b>`'s. A `-C` value this cannot resolve, and a command
    that does not parse, are rejected before this function for a history
    rewrite while a plan exists. An unparseable read is still one call where
    the shell stands, because a read orphans nothing."""
    base = _config.effective_cwd(runnable(command), (data or {}).get("cwd"))
    base = base or (data or {}).get("cwd") or ""
    out = []
    for call in (calls if calls is not None else [(None, None, None)]):
        cdir = call[2]
        if cdir is None:
            where = base
        elif not _config.resolvable_destination(cdir):
            where = ""
        elif os.path.isabs(cdir) or not base:
            where = cdir
        else:
            where = os.path.join(base, cdir)
        tree = None
        if where:
            placed = _config.tree_for(data, where, cfg, project=project)
            if placed["moved"] and placed["inside"]:
                tree = placed["root"]
        out.append((call, tree))
    return out


def unplaceable_directory(data, command, calls):
    """Which directory spelling prevents placing a git call, else None.

    `tree_for(data, None)` deliberately means the session directory, so a
    directory this reader cannot establish must be identified before that
    legitimate session reading is requested.
    """
    cwd = (data or {}).get("cwd")
    if cwd and _config.effective_cwd(runnable(command), cwd) is None:
        return "`cd` or `pushd` target"
    for call in calls or []:
        if call[2] is not None and not _config.resolvable_destination(call[2]):
            return "`git -C` target"
    return None


def _tree_of_verb(trees, project_git, match):
    """The git root to ask about the first invocation `match` accepts."""
    for call, tree in trees:
        if call[0] is not None and match(call):
            return tree if tree is not None else project_git
    return None


def decide(data):
    """("deny", reason) or ("allow", "").

    `subprocess` is imported inside the two branches that shell out to git rather
    than at module scope. This hook runs on EVERY Bash tool call, and it returns
    "allow" before touching git for a non-Bash call, an empty command, a repo with
    no recorded task SHAs, and any command that matches none of the rewrite
    patterns - which is nearly all of them. `subprocess` brings about a dozen
    modules with it (threading, selectors, select, signal, locale, warnings, ...),
    and every one of them was being paid for on calls that never spawn anything.
    `tools/bench-hooks.py --gate` is what keeps it out.
    """
    if (data.get("tool_name") or "") != "Bash":
        return ("allow", "")
    command = ((data.get("tool_input") or {}).get("command") or "")
    if not command.strip():
        return ("allow", "")

    home = _config.tree_for(data, _config.PROJECT_ONLY)
    root, cfg = home["project"], home["cfg"]

    # A command that parses and runs no git has nothing any arm below could
    # refuse - every arm reads `git_calls` - so it is answered before a
    # manifest is opened or a tree is placed.
    calls = git_calls(command)
    if calls == []:
        return ("allow", "")
    rewrite = (always_refused(command) or amend_requested(command)
               or any(target for target, _index in reset_targets(command)))
    # An unparseable command has no `-C` reading at all. Judging the rewrite
    # where the session stands is the bug: the unread `-C` may name another
    # tree, and a plan there is exactly what this guard exists to see.
    if calls is None and rewrite and plan_present(root, cfg):
        return ("deny",
                "this command carries a history rewrite, but it cannot be "
                "parsed, so the guard cannot establish where Git runs it. "
                "A `git -C` inside an unreadable command is not the session's "
                "directory. Pass a command that parses, with a literal "
                "`git -C <absolute path>` if the rewrite runs elsewhere.")
    unplaced = unplaceable_directory(data, command, calls)
    if unplaced and rewrite and plan_present(root, cfg):
        return ("deny",
                "this command carries a history rewrite, but its %s cannot "
                "be read, so the guard cannot establish where Git runs it. "
                "Use a literal directory, or `git -C <absolute path>`, so "
                "the rewrite can be checked against that tree's plan."
                % (unplaced,))
    trees = call_trees(data, cfg, root, command, calls)
    roots = command_roots(root, trees)

    # THE STASH ARM IS DECIDED BEFORE THE SHA CHECK, and the ordering is the
    # difference between the two halves of this hook rather than a preference.
    # A stash removes work that has never been committed, so waiting for a
    # recorded SHA would make this arm silent on exactly the repo where the
    # incident happened - a plan whose first task is still mid-edit. The regex
    # runs first and the stat only behind it, because this hook is on every
    # Bash call and `tools/bench-hooks.py --gate` is what keeps it cheap.
    moves = moving_stash(command)
    if moves and any(plan_present(r, cfg) for r in roots):
        return ("deny", _stash_reason(moves))
    if any(c[0] == STDIN_VERB for c in (calls or [])) \
            and any(plan_present(r, cfg) for r in roots):
        return ("deny", "`xargs git` takes its verb from stdin, which this "
                        "guard cannot read, so it cannot tell a `git log` from a "
                        "`git stash` or a force-push. Put the verb on the "
                        "command line (`xargs git log ...`) and it is graded "
                        "like any other git command.")

    shas = []
    for r in roots:
        shas.extend(s for s in recorded_shas(r, cfg) if s not in shas)
    if not shas:
        # Nothing to protect. Said here rather than left implicit: the guard is
        # inert on a repo with no trail, and that is an answer, not a miss.
        return ("allow", "")
    # Refs resolve per working tree, so each question below is asked in the
    # tree of the invocation it is about (`call_trees`); an unparseable
    # command that was not refused above falls back to the first worktree
    # it reaches, else the project.
    project_git = _config.git_root_dir(root, cfg)
    fallback_git = roots[1] if len(roots) > 1 else project_git

    why = always_refused(command)
    if why:
        return ("deny",
                "%s. The manifest records %d task commit SHA(s); "
                "`/audit:doctor` reports a SHA that resolves nowhere as a "
                "FINDING, and the trail cannot be rebuilt from the rewritten "
                "history. If this is deliberate, run it outside the audit "
                "checkout, or clear the affected `task.commit` values first "
                "so the manifest stops claiming a commit that will not exist."
                % (why, len(shas)))

    for target, index in reset_targets(command):
        if target == "":
            # The common, legitimate case, and the one this guard exists to keep
            # working: no ref means no branch pointer moves.
            continue
        reset_git = fallback_git
        if index is not None and calls and index < len(trees):
            tree = trees[index][1]
            reset_git = tree if tree is not None else project_git
        lost = orphaned_by(root, reset_git, target, shas)
        if lost:
            names = ", ".join("%s (%s)" % (t, s[:12]) for t, s in lost[:3])
            return ("deny",
                    "this reset would leave %d recorded commit(s) unreachable: "
                    "%s%s. Those SHAs are what `task.commit` names and what "
                    "`bug.fixedIn` is derived from. `git reset --hard` with NO "
                    "ref is not blocked - that discards uncommitted work and "
                    "touches no history."
                    % (len(lost), names, "" if len(lost) <= 3 else ", ..."))

    if amend_requested(command):
        import subprocess
        git_root = _tree_of_verb(
            trees, project_git,
            lambda c: c[0] == "commit" and _has_option(c[1], "--amend")
            and not help_requested(c[1])) or fallback_git
        head = ""
        try:
            out = subprocess.run(["git", "-C", git_root or root, "rev-parse", "HEAD"],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 timeout=10)
            if out.returncode == 0:
                head = out.stdout.decode("utf-8", "replace").strip()
        except Exception:
            return ("allow", "")
        for task_id, sha in shas:
            if head and sha.startswith(head[:12]) or (head and head.startswith(sha[:12])):
                return ("deny",
                        "amending would replace HEAD, which is the commit "
                        "`task.commit` records for %s (%s). "
                        "reference/orchestrator.md says the `task.commit` write "
                        "rides along with the NEXT commit for exactly this "
                        "reason - do NOT amend." % (task_id, sha[:12]))
    return ("allow", "")


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.exit(0)
    try:
        verdict, reason = decide(data)
        if verdict == "deny":
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "[guard-history-rewrite] " + reason,
                }
            }))
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        print("guard-history-rewrite.py has no inline --selftest; its cases live "
              "in plugins/audit/tests/test_guard_history_rewrite.py - run that "
              "file instead.")
        sys.exit(0)
    main()
