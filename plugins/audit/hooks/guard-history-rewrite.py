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
    fires on it is the same defect as one that fires on a read (F283, which
    REVERSED the known cost recorded before it);
  * a command `shlex` cannot parse falls back to the raw-text patterns, which
    over-fire on quoted text and are the conservative answer where nothing can
    be parsed at all.

**A HEREDOC IS NOT A QUOTED ARGUMENT, and this document used to claim it was.**
`shlex` splits `<<'EOF'` at the `<` and lexes the body as bare words, so
`cat <<'EOF' > NOTES.md` / `never run git stash` / `EOF` is REFUSED. That is left
as it is rather than fixed, because whether a heredoc body is DATA or a COMMAND
depends on what consumes it - `cat <<EOF` is data, `sh <<EOF` is a script, and
`guard-secrets-read` already grades an interpreter heredoc as a body. Refusing
both is the conservative direction; the cost is that writing one of these rules
into a file through a heredoc is refused, and the way past it is an editor or an
`echo`. Measured cost, stated rather than discovered.

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
That failure mode is recorded in this project's own history (F-P-24, and the
`guard-secrets-read` read-vs-write class before it), so the ancestry check is not
an optimisation. It is the reason the guard is allowed to exist.

TWO ARMS, TWO ACTIVATION CONDITIONS, and they are not interchangeable. The
history arm asks whether a COMMIT the manifest records would stop being
reachable, so a manifest with no recorded SHAs has nothing to orphan and every
command passes. The **stash** arm (F281, see its own block below) asks nothing
about commits: `git stash` removes work that was never committed, so it is
refused as soon as an audit plan exists on disk. Reading the second arm as the
first is how it would end up silent on a plan whose first task is still mid-edit.

WHAT IT DOES NOT DO. It never inspects the working tree, never runs a write, and
never blocks a command it cannot decide: an unparseable command, an unreadable
manifest, or a git that will not answer all resolve to ALLOW. It does not refuse
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
# F283. THE COMMAND IS TOKENIZED AND THE VERB IS READ FROM AN ADJACENT TOKEN.
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
# (It also refused a HEREDOC whose body merely contained the string, and that
# half is NOT fixed - see the module docstring for why refusing it is the
# deliberate direction rather than the remaining bug.)
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


def shell_words(command):
    """(words, parsed) - the command as shell WORDS, separators marked as None.

    `parsed` is False when `shlex` could not read the line at all, and then
    `words` is empty and the caller MUST use the text patterns instead. It is a
    separate answer rather than an empty list because "no words" and "could not
    be read" lead to opposite verdicts, and the second one must never be quiet.

    F284. THE LEXER IS BUILT BY HAND BECAUSE `shlex.split` DROPS NEWLINES.
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
    try:
        lex = shlex.shlex(command or "", posix=True)
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
            out.append(None if _SEP_ONLY.match(piece) else piece)
    return (out, True)


def program_name(word):
    """A command word's program name: basename, no `.exe`, folded to lower case.

    F284: comparing the whole word missed `/usr/bin/git push --force`, which the
    raw-text version caught because `\\bgit\\b` matches after a `/`. Windows
    spellings fold in here too - CI runs these suites on it, and `git.exe` is the
    same program.
    """
    name = (word or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def _is_shell_command_flag(word):
    """A shell's command flag: `-c`, and every CLUSTER it really appears in.

    F284: this read `word.endswith("c")`, which accepts `-lc` and `-ic` and
    misses `-cx`, `-cv` and `-ce`. A cluster is a SET of short options, so the
    question is whether `c` is in it and not where it sits.
    """
    return (word.startswith("-") and not word.startswith("--")
            and "c" in word[1:])


def _has_option(args, name):
    """Is this long option present, in either spelling git accepts?

    F284: `"--force-with-lease" in args` is exact-token equality, and the
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


def git_invocations(command, depth=0):
    """[(verb, [args]), ...] for every `git` this command RUNS, or None.

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
    """
    words, parsed = shell_words(command)
    if not parsed:
        return None
    out = []
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
                    nested = git_invocations(words[scan + 1], depth + 1)
                    out.extend(nested or [])
                    break
                scan += 1
        elif depth < _MAX_NEST and program in EVAL_WRAPPERS:
            # F284. `eval "git push --force"` saw NO git: `eval` was in no
            # wrapper table, its argument stayed one token, and the fallback is
            # only reached when the line will not parse - which this one does.
            # It takes the command as its next word rather than behind a flag.
            scan = index + 1
            while scan < total and words[scan] is not None:
                if not words[scan].startswith("-"):
                    out.extend(git_invocations(words[scan], depth + 1) or [])
                    break
                scan += 1
        if program != "git":
            index += 1
            continue
        index += 1
        while index < total and words[index] is not None \
                and words[index].startswith("-"):
            takes_value = words[index] in GLOBAL_VALUE_OPT
            index += 1
            if takes_value and index < total and words[index] is not None:
                index += 1
        if index >= total or words[index] is None:
            continue                       # `git` with no verb after it
        verb = words[index]
        index += 1
        args = []
        while index < total and words[index] is not None:
            args.append(words[index])
            index += 1
        out.append((verb, args))
    return out


# --- the text fallback --------------------------------------------------------
# F278. THE VERB HAS TO BE IN SUBCOMMAND POSITION, not merely somewhere in the
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
# `guard-secrets-read`'s F267 in a second hook — a guard grading TEXT rather than
# the operation — and it has the same consequence, which is why it is fixed the
# same way rather than exempted. It refused this repository's own commit
# documenting the rule, and then refused the probe written to measure it, which is
# a guard teaching the person it protects to work around it.
#
# `git`, then GLOBAL OPTIONS ONLY, then the verb. `-C <path>` and `-c <k=v>` take a
# value and are spelled out so the value cannot be mistaken for the verb.
#
# F281 CONSIDERED NARROWING THE LONG-OPTION ARM TO GIT'S ACTUAL GLOBAL SET and
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
_GIT_SUB = (r"\bgit\b(?:\s+(?:-C\s+\S+|-c\s+\S+"
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
        for pattern, why in _ALWAYS:
            if pattern.search(command or ""):
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
        return bool(_AMEND.search(command or ""))
    return any(verb == "commit" and _has_option(args, "--amend")
               and not help_requested(args)
               for verb, args in invocations)

# --- the stash arm (F281) -----------------------------------------------------
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
            # F284. `git stash --help` and `-h` printed a manual page and were
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
    for m in _STASH.finditer(command or ""):
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


def reset_target(command):
    """The ref a `git reset --hard` names, or "" when it names none.

    "" is the case the whole guard turns on: `git reset --hard` with no ref moves
    no branch pointer, so no commit can stop being reachable. None is the third
    answer - this is not a reset at all - and the three are kept apart because
    "" and None lead to opposite verdicts.
    """
    invocations = git_invocations(command)
    if invocations is None:
        m = _RESET_HARD.search(command or "")
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

    root = _config.repo_root(data)
    cfg = _config.load(root)

    # THE STASH ARM IS DECIDED BEFORE THE SHA CHECK, and the ordering is the
    # difference between the two halves of this hook rather than a preference.
    # A stash removes work that has never been committed, so waiting for a
    # recorded SHA would make this arm silent on exactly the repo where the
    # incident happened - a plan whose first task is still mid-edit. The regex
    # runs first and the stat only behind it, because this hook is on every
    # Bash call and `tools/bench-hooks.py --gate` is what keeps it cheap.
    moves = moving_stash(command)
    if moves and plan_present(root, cfg):
        return ("deny", _stash_reason(moves))

    shas = recorded_shas(root, cfg)
    if not shas:
        # Nothing to protect. Said here rather than left implicit: the guard is
        # inert on a repo with no trail, and that is an answer, not a miss.
        return ("allow", "")
    git_root = _config.git_root_dir(root, cfg)

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

    target = reset_target(command)
    if target is not None:
        if target == "":
            # The common, legitimate case, and the one this guard exists to keep
            # working: no ref means no branch pointer moves.
            return ("allow", "")
        lost = orphaned_by(root, git_root, target, shas)
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
