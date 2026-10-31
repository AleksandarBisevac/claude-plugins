#!/usr/bin/env python3
"""
PreToolUse hook (matcher: Bash) - refuse a git command whose effect is TREE-WIDE
destruction of UNCOMMITTED work, and name what would be lost. THIS REPO'S OWN
CONFIGURATION, not the audit plugin's product; it sits beside `guard-release.py`
and draws the same line.

WHAT IT IS FOR, in one command. `git reset --hard HEAD` was run here to undo a bad
patch. It undid the patch, and it also destroyed a skill revision waiting to be
committed, the audit manifest's index, and a phase's completion marks that existed
in no other file. All of it came back only because the commits beside it happened
to carry the same facts in their subjects - which is luck, not recovery. The
command that was meant was `git checkout -- <the paths>`.

THE SIBLING THIS COMPLETES. `plugins/audit/hooks/guard-history-rewrite.py` refuses
a force push, a rebase and a filter-branch because a rewritten history breaks the
recorded trail: it protects what is COMMITTED, and it deliberately ALLOWS
`git reset --hard` for exactly that reason - a reset touches no history. Nothing
protected the other half, and the other half is the work nobody has proven yet. A
discarded COMMIT is still in the reflog; discarded uncommitted work is in nothing.

WHAT IT REFUSES, and the boundary is the whole design. Not a verb - an OPERATION
whose file set is the whole tree:

  git reset --hard [<ref>]      discards every tracked change, staged and not.
                                git rejects a pathspec here itself ("Cannot do
                                hard reset with paths"), so there is no scoped
                                spelling of it to allow.
  git checkout/switch -f,       overwrites the tree from the target.
  git checkout . / -- . / <ref> .
  git restore .                 overwrites the worktree from the index (or from
                                --source). `--staged` ALONE is not on this list:
                                it rewrites the index and leaves every byte on
                                disk, so `git restore --staged .` - the modern
                                spelling of "unstage everything" - stays silent.
  git clean -f/-d/-x            removes files git does not track. What it would
                                remove is asked of `git clean -n` carrying the
                                same scope flags, not guessed from a status line.
  git stash / push / save       removes work from the tree without naming it.
                                Banned here in its own right - the invariant is
                                `plugins/audit/reference/orchestrator.md`'s
                                "never `git push`/force-push/`stash`" - and the
                                plugin's guard refuses it whenever an audit plan
                                is on disk. This arm asks a narrower question and
                                answers it with the file list that one cannot: it
                                fires only when the tree holds work to lose, and
                                says which work. The stash READS (`list`, `show`)
                                and the restores (`apply`, `pop`) are never
                                refused, for the reason `SECURITY.md` gives about
                                the sibling: a guard that fires on a read is one
                                people route around.

AND ONLY WHEN THERE IS SOMETHING TO LOSE. The verdict is the intersection of the
operation and the tree: every command above is ordinary and safe on a clean tree,
so a clean tree is silent. That is not a softening - it is what keeps this
installed. A guard that refuses `git clean -fdx` on a tree with nothing to clean
teaches the person it protects to route around it, and after that it protects
nothing.

A PATH-SCOPED UNDO IS NEVER REFUSED, dirty tree or not. `git checkout -- src/x.py`
and `git restore --staged <path>` are the remedy this refusal exists to steer
toward, and a guard that blocks the remedy it recommends is a guard that gets
removed within the day. One over-fire is accepted and stated rather than hidden:
`git checkout -f <word>` with no `--` is read as tree-wide, because whether
`<word>` is a branch or a path is a question only `git rev-parse` can answer and
the wrong answer here is the unrecoverable one. The cost is bounded by the remedy
being exactly equivalent - `git checkout -- <path>` needs no `-f`.

FAIL-CLOSED, and the basis is `SECURITY.md`'s own exception rather than a fresh
choice. That table puts advisory hooks on fail-open: a guard that crashes must not
stop legitimate work, and this hook keeps that everywhere it can - a payload that
will not parse, a tool that is not Bash, a command that runs no destructive
operation, all resolve to allow in silence. `guard-release.py` inverts it for one
reason, that the thing it protects is irreversible, and that reason is stronger
here: a pushed tag at least still exists as an object, while uncommitted work that
a reset discarded is in no reflog, no index and no object store. So when the
operation IS one of these and git cannot be asked whether the tree holds work, the
answer is a refusal that says which of the two happened. The cost of that is
bounded by the same fact that motivates it - outside a repository, or with no git
on PATH, the destructive command was going to fail anyway, so the refusal costs a
message and not an operation.

AND THERE IS NO OVERRIDE, which is a decision rather than an omission.
`arm-release-bypass.py` exists because "ship this release over a known bug" is a
real intention with no substitute: the maintainer wants the release, and no other
command produces one. Nothing here is like that. Every refusal below names a
substitute that reaches the same end state and loses nothing - the path-scoped
form, or a commit first, after which the very same command becomes recoverable
through the reflog. An override would be a switch whose only use is to do the
unrecoverable thing on purpose, and the incident this hook was written for is
precisely somebody doing the destructive thing on purpose while believing its
scope was narrower. A prompt-armed keyword would have been typed and the work
would still be gone.

THE REFUSAL NAMES THE WORK AND THE WAY FORWARD, capped. "You have uncommitted
changes" teaches nothing and a list of two hundred paths is not read, so it prints
enough paths to recognise the work, with a count of the rest.

Contract: a refusal emits {"hookSpecificOutput": {"permissionDecision": "deny",
"permissionDecisionReason": ...}} on stdout and exits 0 - the canonical PreToolUse
protocol.

Exit codes: 0 always (the decision travels in the payload, never in the code).
"""
import json
import os
import re
import subprocess
import sys

# --- reading the command ------------------------------------------------------
# THE SHAPES, IN TEXT, AND THEY HAVE TWO JOBS. This runs on every Bash call, so
# the first job is a cheap pre-filter: no match, no parse, no subprocess, no
# verdict. Over-inclusive on purpose - a quoted `git reset --hard` inside a commit
# message matches here and is then thrown out by the parse, which reads the
# operation.
#
# The second job is the fallback for a line the parser cannot read at all (an
# unbalanced quote, or a heredoc body the parser cannot place). There the table
# grades `executed_text()`'s view - the line with only its house-template
# heredoc bodies taken out, by the one reader `_config` shares - and grades the
# raw line when that view cannot be built. Every other quoted argument or body
# in such a line is graded as text: a reader that took them out unless a runner
# list named the command passed every runner the list missed.
#
# ONE TABLE, TWO USES. A separate pre-filter would be a second description of the
# same set, and the two would drift in the direction that matters - a shape
# present in the fallback and missing from the pre-filter never reaches it.
#
# THE TREE-WIDE DOT ends where a shell word can end, not only at a blank: a
# `.` closing a substitution (`$(git checkout -- .)`) or a quoted word is the
# same pathspec, and a boundary of blanks alone let the pre-filter wave that
# substitution through before the parser - which reads it - was ever asked.
_DOT = r"(?<![^\s\"'(=])\.(?![^\s\"');&|`])"
_SHAPES = (
    r"reset\b[^|;&\n]*--hard",
    r"(?:checkout|switch)\b[^|;&\n]*(?:--force\b|--discard-changes\b"
    r"|(?<![\w-])-[A-Za-z]*f[A-Za-z]*(?![\w-])|" + _DOT + ")",
    r"restore\b[^|;&\n]*" + _DOT,
    r"clean\b[^|;&\n]*(?<![\w-])-[A-Za-z]*[fdxX]",
    r"stash\b(?![^|;&\n]*\b(?:list|show|apply|pop|drop|branch|clear)\b)",
)
DESTRUCTIVE_TEXT = re.compile(r"\bgit\b[^|;&\n]*(?:" + "|".join(_SHAPES) + ")")

# Options that take a SEPARATE value, so the value is never mistaken for a
# pathspec: `git stash push -m .` stashes with a message, and `.` there is the
# message. Each entry is an option one of the graded verbs really accepts.
VALUE_OPTS = ("-b", "-B", "-c", "-C", "-m", "-e", "-s", "-t",
              "--message", "--source", "--exclude", "--orphan", "--conflict",
              "--pathspec-from-file", "--track")

# A pathspec that means "the whole tree". `:/` is git's root magic; `.` and `./`
# are what a person types. A pathspec naming anything else is SCOPED, and scoped
# is the remedy this hook recommends - it is never refused.
TREE_WIDE = (".", "./", ":/", ":/.", "*")

# `git stash` sub-verbs that read the stash or put work BACK. Never refused; a
# guard that fires on a read gets routed around, which `SECURITY.md` says of this
# hook's sibling in as many words.
STASH_KEEPS = ("list", "show", "apply", "pop", "drop", "branch", "clear",
               "create", "store")

# What a given operation would take away. Kept apart because they are different
# losses and a refusal that blurs them is a refusal that misnames the work: an
# index survives `git checkout -- .` and does not survive `git checkout -f`, and
# an untracked file survives every reset and is exactly what `git clean` is for.
LOSS_TRACKED = "tracked"        # every change to a tracked file, staged and not
LOSS_WORKTREE = "worktree"      # unstaged changes only; the index keeps the rest
LOSS_UNTRACKED = "untracked"    # files git does not track

# Enough paths to recognise the work, few enough that the refusal is read.
NAMED_CAP = 6
GIT_TIMEOUT = 5

REMEDY_PATHS = "`git checkout -- <path> [<path>...]` undoes only the files you name"
REMEDY_CLEAN = "`git clean -fd <path> [<path>...]` removes only under the paths you name"
REMEDY_COMMIT = ("commit the work first (stage the paths you mean, then "
                 "`git commit`) - after a commit the SAME command is recoverable, "
                 "because a discarded commit is in the reflog and discarded "
                 "uncommitted work is in nothing")


def parser():
    """The sibling's command parser, or None when it cannot be loaded.

    IMPORTED, NOT COPIED. `git_invocations` is where each of these edge cases
    was fixed in turn - a verb read from an adjacent token so a commit MESSAGE
    naming a command is not that command, a heredoc body graded by what
    consumes it, newlines kept inside tokens, short-flag clusters, `sh -c` and
    `eval` parsed as the commands they carry. A second copy of that surface here
    would be a second set of those bugs. `guard-release.py` draws the same line
    in its own
    `_effective`: the plugin's hooks may not import `scripts/`, and this file is
    not a plugin hook - it is this repository's configuration, and this
    repository always has `plugins/audit/` sitting next to it.

    BY PATH, because the sibling's name is hyphenated and `import` cannot spell
    it - the same route `arm-release-bypass.py` takes to `guard-release.py`.

    LAZILY, from the one branch that needs it. This hook runs on every Bash call
    and `DESTRUCTIVE_TEXT` has already said no by the time most of them get here;
    the load belongs to the commands that might destroy something, not to every
    `ls`.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(os.path.dirname(here))
    path = os.path.join(repo, "plugins", "audit", "hooks",
                        "guard-history-rewrite.py")
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "audit_repo_git_command_parser", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def has_long(args, *names):
    """Is one of these long options present, in either spelling git accepts?

    `--source=HEAD` and `--source HEAD` are one option, and exact-token equality
    sees only the second.
    """
    for name in names:
        for arg in args:
            if arg == name or arg.startswith(name + "="):
                return True
    return False


def has_short(args, letter):
    """Is this short option present, alone or inside a CLUSTER?

    `git clean -fdx` is three options in one word, and `"-d" in args` sees none of
    them. Case matters: `-x` and `-X` remove different files.
    """
    for arg in args:
        if arg.startswith("-") and not arg.startswith("--") and letter in arg[1:]:
            return True
    return False


def targets(args):
    """`(after_dashdash, before, after)` - the words this command names, split at `--`.

    The split is the difference between a word that MIGHT be a branch and one git
    was TOLD is a path, and it is also where a sub-verb lives: `git stash push --
    src/x.py` has its verb in `before` and its pathspec in `after`, and a reading
    that kept only one of the two lists would mistake one for the other. Option
    values are skipped so a message or a branch name cannot arrive as a pathspec.
    """
    before, after, seen, index = [], [], False, 0
    while index < len(args):
        arg = args[index]
        if seen:
            after.append(arg)
            index += 1
            continue
        if arg == "--":
            seen = True
            index += 1
            continue
        if arg.startswith("-"):
            index += 2 if (arg in VALUE_OPTS and index + 1 < len(args)) else 1
            continue
        before.append(arg)
        index += 1
    return (seen, before, after)


def scope(seen, before, after):
    """The words that decide how wide the operation is: the pathspecs when git was
    told which they are, and every bare word otherwise."""
    return after if seen else before


def tree_wide(words):
    return any(word in TREE_WIDE for word in words)


def judge(verb, args, helper=None):
    """The judgement for one git invocation, or None when it destroys nothing.

    THE DECISION IS THE OPERATION'S FILE SET, never the verb's spelling. Each arm
    below asks what this invocation would overwrite or remove and how wide that
    is; a scoped pathspec ends the question, because a scoped undo is the thing
    this hook recommends.
    """
    verb = (verb or "").lower()
    if helper is not None and helper.help_requested(args):
        return None                     # a manual page destroys nothing
    if verb == "reset":
        if not has_long(args, "--hard"):
            return None                 # --soft/--mixed/--merge/--keep all refuse
            # to lose work, or leave the worktree alone entirely
        return {"op": "git reset --hard", "kinds": (LOSS_TRACKED,),
                "probe": "status", "remedy": REMEDY_PATHS}
    if verb in ("checkout", "switch"):
        forced = (has_long(args, "--force", "--discard-changes")
                  or has_short(args, "f"))
        seen, before, after = targets(args)
        words = scope(seen, before, after)
        scoped = bool(words) and not tree_wide(words)
        if seen and scoped:
            return None                 # `git checkout -f -- src/x.py`: git was
            # TOLD these are paths, so the operation is those paths and no others
        if forced:
            return {"op": "git %s --force" % (verb,), "kinds": (LOSS_TRACKED,),
                    "probe": "status", "remedy": REMEDY_PATHS}
        if verb == "switch" or not tree_wide(words):
            return None                 # a plain branch switch: git refuses on its
            # own rather than clobbering, so there is nothing here to protect
        # `git checkout <ref> .` rewrites the index too; `git checkout -- .` does
        # not, and the refusal must not claim a loss the command would not cause.
        staged_too = any(word not in TREE_WIDE for word in before + after)
        return {"op": "git checkout .",
                "kinds": (LOSS_TRACKED,) if staged_too else (LOSS_WORKTREE,),
                "probe": "status", "remedy": REMEDY_PATHS}
    if verb == "restore":
        staged = has_long(args, "--staged") or has_short(args, "S")
        worktree = has_long(args, "--worktree") or has_short(args, "W")
        if staged and not worktree:
            return None                 # the index is rewritten and every byte
            # stays on disk: `git restore --staged .` loses no file content
        seen, before, after = targets(args)
        words = scope(seen, before, after)
        if not words or not tree_wide(words):
            return None                 # scoped, or no pathspec at all - which
            # git rejects itself, so refusing it would name a loss that cannot
            # happen
        return {"op": "git restore .",
                "kinds": (LOSS_TRACKED,) if staged else (LOSS_WORKTREE,),
                "probe": "status", "remedy": REMEDY_PATHS}
    if verb == "clean":
        if has_long(args, "--dry-run") or has_short(args, "n"):
            return None                 # a dry run is a read
        if not (has_long(args, "--force") or has_short(args, "f")
                or has_short(args, "d") or has_short(args, "x")
                or has_short(args, "X")):
            return None
        seen, before, after = targets(args)
        words = scope(seen, before, after)
        if words and not tree_wide(words):
            return None
        return {"op": "git clean", "kinds": (LOSS_UNTRACKED,), "args": args,
                "probe": "clean", "remedy": REMEDY_CLEAN}
    if verb == "stash":
        seen, before, after = targets(args)
        sub = before[0] if before else None
        if sub in STASH_KEEPS:
            return None                 # reads and restores
        if sub is not None and sub not in ("push", "save"):
            return None
        paths = after if seen else before[1:] if sub else before
        if paths and not tree_wide(paths):
            return None                 # `git stash push -- src/x.py` is scoped
        kinds = (LOSS_TRACKED,)
        if (has_long(args, "--include-untracked", "--all")
                or has_short(args, "u") or has_short(args, "a")):
            kinds = (LOSS_TRACKED, LOSS_UNTRACKED)
        return {"op": "git stash", "kinds": kinds, "probe": "status",
                "remedy": REMEDY_PATHS,
                "note": "`git stash` is an invariant violation here in its own "
                        "right - plugins/audit/reference/orchestrator.md lists it "
                        "beside push and force-push under never-violate"}
    return None


def reading(command):
    """`(judgement, how)` - what this command would destroy and how that was read.

    `how` is "operation" when the line parsed, and "text" when it did not and
    the shapes above decided instead. The caller reports which, because a
    verdict reached without parsing the line as given is a weaker claim and
    saying so is cheaper than being wrong about it quietly.

    The parser lifts house-template bodies before it tokenizes
    (`_config.split_heredocs` calls `lift_house_bodies`), so a line whose
    lifted view parses is a line that parsed. A line with a part that will not
    read alone is graded by BOTH readings the parser's `command_reading`
    hands back - the shapes over the lifted view, which assume the widest loss
    set, and then every call any parse of it found - so neither reading can
    allow what the other refuses.
    """
    if not DESTRUCTIVE_TEXT.search(command or ""):
        return (None, "operation")      # the cheap door: no shape, no parse
    helper = parser()
    invocations, strict = _parsed_calls(command, helper)
    if not strict:
        return (_first_judgement(invocations, helper), "operation")
    # A part will not read alone: the shapes grade all of it but the bodies
    # the house template lifts.
    view = executed_text(command, helper)
    if view is None or DESTRUCTIVE_TEXT.search(view):
        # The parser could not be loaded, or the text names a destructive shape
        # outside the house template: the widest loss set is assumed and the
        # refusal says it was read from text.
        return ({"op": "this command", "kinds": (LOSS_TRACKED, LOSS_UNTRACKED),
                 "probe": "status", "remedy": REMEDY_PATHS}, "text")
    # The shapes found nothing; a call a parse read is still an operation.
    found = _first_judgement(invocations, helper)
    return (found, "operation" if found is not None else "text")


def _parsed_calls(command, helper):
    """`([(verb, args)], strict)` - every git call the parser's readings
    found, and whether a part of the line will not read alone. A parser with
    no `command_reading` answers through `git_invocations`, where None is the
    strict reading with no calls; no parser at all is that too."""
    if helper is None:
        return [], True
    read = getattr(helper, "command_reading", None)
    if read is None:
        invocations = helper.git_invocations(command)
        return invocations or [], invocations is None
    calls, strict = read(command)
    return [(call[0], call[1]) for call in calls], strict


def _first_judgement(invocations, helper):
    for verb, args in invocations:
        found = judge(verb, args, helper)
        if found is not None:
            return found
    return None


# --- what an untokenizable line executes --------------------------------------
# FAIL CLOSED: A LINE THAT WILL NOT TOKENIZE IS GRADED WHOLE, minus only the
# heredoc bodies `_config.lift_house_bodies` lifts - the house template,
# `"$(cat <<'EOF'` ... `EOF` ... `)"` as the argument of a literal text sink,
# recognised whole by the one function every guard here shares. Nothing else
# in such a line is data: no quoted argument, no other heredoc.
#
# This used to be a second reader that took quoted arguments and heredoc bodies
# out as data unless a runner list named the command, and every runner the list
# missed was a pass: an expansion as the program word (`$SHELL -c`), a remote or
# wrapped runner (`ssh`, `su -c`, `flock -c`, `script -c`, `nix-shell --run`,
# `tar --to-command=`), a git alias, `find -exec`, `trap`. A list of the ways a
# program runs its argument is never finished, so there is no list.
#
# KNOWN COST, accepted rather than hidden: a line the parser cannot read that
# QUOTES one of the destructive shapes outside the house template - an argument
# to a script, a heredoc fed to one - is refused on a dirty tree, read as TEXT.
# A line the parser CAN read is graded on its operation and never comes here.


def executed_text(command, helper):
    """The text `command` EXECUTES as this fallback reads it - the line with
    each house-template body lifted out by `_config.lift_house_bodies` - or
    None when the shared reader could not be loaded or broke on the line.

    None sends the caller to the raw line, which is the conservative reading;
    it is a separate answer from a view equal to the line, which means nothing
    in it was the house template."""
    cfg = getattr(helper, "_config", None) if helper is not None else None
    lift = getattr(cfg, "lift_house_bodies", None)
    if lift is None:
        return None
    try:
        view, _lifted = lift(command or "")
    except Exception:
        return None                     # a reader that broke has read nothing
    return view


# --- asking git what is at stake ----------------------------------------------
def _git(cwd, args):
    """`(stdout, problem)` - exactly one of the two is None.

    A non-zero exit is a PROBLEM and not an empty answer. "git said nothing" and
    "git could not be asked" lead to opposite verdicts here, and collapsing them
    is how a guard comes to wave through the command it exists for.
    """
    try:
        proc = subprocess.run(["git"] + list(args), cwd=cwd,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=GIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return (None, "git did not answer within %d seconds" % (GIT_TIMEOUT,))
    except Exception as exc:
        return (None, "git could not be run (%s)" % (exc,))
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        return (None, "`git %s` failed: %s"
                % (" ".join(args), err[0] if err else "exit %d" % (proc.returncode,)))
    return (proc.stdout.decode("utf-8", "replace"), None)


def working_state(cwd):
    """`({kind: [(path, label), ...]}, problem)` - what this tree is holding.

    Read from `git status --porcelain`, whose first two columns are the index and
    the worktree. The split into kinds is what lets a refusal name the loss the
    command would actually cause rather than "you have changes".
    """
    out, problem = _git(cwd, ["status", "--porcelain"])
    if problem is not None:
        return (None, problem)
    state = {LOSS_TRACKED: [], LOSS_WORKTREE: [], LOSS_UNTRACKED: []}
    for line in out.splitlines():
        if len(line) < 4:
            continue
        index_col, tree_col, path = line[0], line[1], line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]     # a rename reports both names
        path = path.strip().strip('"')
        if index_col == "?" and tree_col == "?":
            state[LOSS_UNTRACKED].append((path, "untracked"))
            continue
        staged = index_col not in (" ", "?")
        unstaged = tree_col not in (" ", "?")
        label = ("staged and unstaged" if staged and unstaged
                 else "staged" if staged else "unstaged")
        state[LOSS_TRACKED].append((path, label))
        if unstaged:
            state[LOSS_WORKTREE].append((path, label))
    return (state, None)


def clean_state(cwd, args):
    """`([(path, label), ...], problem)` - what THIS `git clean` would remove.

    ASKED OF THE COMMAND ITSELF. `-d`, `-x`, `-X` and `--exclude` each change the
    file set, and `git clean -f` alone does not descend into an untracked
    DIRECTORY - so a refusal built from `??` lines would name files this command
    leaves alone. The scope flags are forwarded to a dry run, which is the same
    operation with its effect removed.
    """
    flags = ["clean", "-n"]
    for letter in ("d", "x", "X"):
        if has_short(args, letter):
            flags.append("-" + letter)
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "-e" and index + 1 < len(args):
            flags.extend(["-e", args[index + 1]])
            index += 2
            continue
        if arg.startswith("--exclude"):
            flags.append(arg)
        index += 1
    out, problem = _git(cwd, flags)
    if problem is not None:
        return (None, problem)
    found = []
    for line in out.splitlines():
        if line.startswith("Would remove "):
            found.append((line[len("Would remove "):].strip(), "untracked"))
    return (found, None)


def at_stake(cwd, judgement):
    """`([(path, label), ...], problem)` - the work this judgement's operation ends.

    Deduplicated by path across kinds so a file that is both staged and untracked
    in two readings is named once, and ordered so the refusal reads the same way
    twice on one tree.
    """
    if judgement.get("probe") == "clean":
        return clean_state(cwd, judgement.get("args") or [])
    state, problem = working_state(cwd)
    if problem is not None:
        return (None, problem)
    found, seen = [], set()
    for kind in judgement["kinds"]:
        for path, label in state.get(kind, []):
            if path in seen:
                continue
            seen.add(path)
            found.append((path, label))
    return (found, None)


# --- the refusal --------------------------------------------------------------
def named(entries):
    """The paths, capped, with the remainder counted rather than listed."""
    shown = ["%s (%s)" % (path, label) for path, label in entries[:NAMED_CAP]]
    rest = len(entries) - len(shown)
    if rest > 0:
        shown.append("and %d more" % (rest,))
    return ", ".join(shown)


def refusal(judgement, entries, problem, how):
    """The sentence a refused command reads. It names the work and the way out.

    A subagent must be able to act on this without a human, which is why the
    substitute is spelled as a command rather than described, and why the reason
    says what the substitute preserves.
    """
    head = "[guard-uncommitted] "
    tail = " Instead: %s; or %s." % (judgement["remedy"], REMEDY_COMMIT)
    note = judgement.get("note")
    if note:
        tail += " " + note + "."
    tail += (" There is no bypass for this one: every way out above reaches the "
             "same end state without losing anything.")
    if problem is not None:
        return (head + "`%s` destroys uncommitted work, and whether this tree "
                "holds any is UNKNOWN: %s. Uncommitted work is in no reflog, so "
                "this refuses rather than guessing." % (judgement["op"], problem)
                + tail)
    read_by = "" if how == "operation" else (
        " (read from the command's TEXT - it could not be tokenized, so the "
        "widest loss set was assumed)")
    return (head + "`%s` would destroy work this tree holds and git keeps "
            "nowhere else%s. %d file(s) would be lost: %s."
            % (judgement["op"], read_by, len(entries), named(entries)) + tail)


def decide(command, cwd):
    """`reason` when the call must be denied, else None.

    The whole rule in one function, so its cases need no hook payload and no
    stdin.
    """
    judgement, how = reading(command)
    if judgement is None:
        return None
    entries, problem = at_stake(cwd, judgement)
    if problem is not None:
        return refusal(judgement, None, problem, how)
    if not entries:
        return None                     # a clean tree: an ordinary, safe command
    return refusal(judgement, entries, None, how)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        # Fail-open, as `SECURITY.md`'s table has it: a payload this hook cannot
        # parse is not evidence about a working tree.
        return 0
    tool = payload.get("tool_name") or payload.get("toolName") or ""
    if tool != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command", "")
    cwd = (payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR")
           or os.getcwd())
    try:
        reason = decide(command, cwd)
    except Exception as exc:
        # The hook itself broke on a command that MATCHED a destructive shape.
        # Fail-closed for the same reason the unknown-tree branch is: there is
        # nothing to undo this with if the guess is wrong.
        if not DESTRUCTIVE_TEXT.search(command or ""):
            return 0
        reason = ("[guard-uncommitted] this command matches a tree-wide "
                  "destructive shape and the guard broke while judging it (%s). "
                  "Uncommitted work is in no reflog, so this refuses rather than "
                  "guessing: check `git status --porcelain` and undo by path "
                  "with `git checkout -- <path>`." % (exc,))
    if reason:
        sys.stdout.write(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason}}))
    return 0


# --- selftest -----------------------------------------------------------------
def _fixture(root, dirty):
    """A REAL git repository, because the verdict is a question asked of git.

    A fake `git status` would agree with whatever this file believes about
    porcelain columns, which is the one thing the end-to-end cases are here to
    check.
    """
    env = dict(os.environ)
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"})

    def run(*args):
        subprocess.run(["git"] + list(args), cwd=root, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=True)

    run("init", "-q")
    with open(os.path.join(root, "kept.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("committed\n")
    run("add", "kept.txt")
    run("commit", "-qm", "base")
    if not dirty:
        return
    with open(os.path.join(root, "kept.txt"), "a", encoding="utf-8", newline="\n") as fh:
        fh.write("an unstaged edit nobody has proven yet\n")
    with open(os.path.join(root, "staged.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("staged\n")
    run("add", "staged.txt")
    with open(os.path.join(root, "untracked.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("untracked\n")
    os.makedirs(os.path.join(root, "newdir"))
    with open(os.path.join(root, "newdir", "deep.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("inside an untracked directory\n")


def _rmtree_git_safe(path):
    """`shutil.rmtree` that survives a fixture holding a git repository.

    Git writes its loose objects read-only. POSIX removes them anyway because
    unlinking needs a writable DIRECTORY rather than a writable file, but windows
    checks the file's own attribute and `ignore_errors=True` leaves them behind
    with nothing said. Clearing every mode bit and retrying once is the fallback,
    run only when the first pass left something standing, so nothing is relaxed
    on the platform where nothing needed it.
    """
    import shutil
    shutil.rmtree(path, ignore_errors=True)
    if not os.path.exists(path):
        return
    for base, dirs, names in os.walk(path):
        for name in dirs + names:
            try:
                os.chmod(os.path.join(base, name), 0o700)
            except OSError:
                pass
    shutil.rmtree(path, ignore_errors=True)


def _selftest():
    import shutil
    import tempfile
    cases, failed = [], []

    def check(label, cond, detail=""):
        cases.append(label)
        if not cond:
            failed.append("%s (%s)" % (label, detail))
        print(("PASS " if cond else "FAIL ") + label)

    helper = parser()
    check("gu0 the sibling's command parser loads - every reading below is the "
          "operation rather than the text, and this is what makes that true",
          helper is not None)

    def verdict(command):
        return reading(command)[0]

    # --- the operations that are refused -------------------------------------
    check("gu1 `git reset --hard` is tree-wide destruction of tracked work",
          verdict("git reset --hard") is not None)
    check("gu2 ...and so is `git reset --hard <ref>`",
          verdict("git reset --hard origin/main") is not None)
    check("gu3 `git checkout -- .` overwrites the worktree, and the index "
          "survives it, so the loss named is the worktree one",
          (verdict("git checkout -- .") or {}).get("kinds") == (LOSS_WORKTREE,))
    check("gu4 `git checkout <ref> .` rewrites the index TOO, so the loss named "
          "is the wider one - a refusal must not misname the work",
          (verdict("git checkout HEAD .") or {}).get("kinds") == (LOSS_TRACKED,))
    check("gu5 `git checkout -f` discards the tree from the target",
          verdict("git checkout -f main") is not None)
    check("gu6 `git restore .` is tree-wide",
          verdict("git restore .") is not None)
    check("gu7 `git clean -fd` removes untracked files",
          (verdict("git clean -fd") or {}).get("kinds") == (LOSS_UNTRACKED,))
    check("gu8 `git stash` removes work from the tree without naming it",
          verdict("git stash") is not None)
    check("gu9 ...and `git stash -u` takes the untracked files with it, which "
          "the loss set has to say",
          (verdict("git stash -u") or {}).get("kinds")
          == (LOSS_TRACKED, LOSS_UNTRACKED))
    check("gu10 a destructive command in the SECOND half of a line is read - "
          "this is how the incident's command was actually typed",
          verdict("git status && git reset --hard HEAD") is not None)
    check("gu11 ...and one behind `sh -c`, because a shell's argument is a "
          "command and is parsed as one",
          verdict('sh -c "git clean -fdx"') is not None)

    # --- THE ALLOW CASES, which decide whether this survives its first week ---
    check("gu12 a PATH-SCOPED undo is never refused - it is the remedy this "
          "refusal steers toward, and a guard that blocks its own remedy is a "
          "guard somebody removes",
          verdict("git checkout -- src/x.py") is None)
    check("gu13 ...including the staged half of it",
          verdict("git restore --staged src/x.py") is None)
    check("gu14 ...and `git restore --staged .`, which rewrites the INDEX and "
          "leaves every byte on disk",
          verdict("git restore --staged .") is None)
    check("gu15 ...and a scoped clean", verdict("git clean -fd build/") is None)
    check("gu16 ...and a scoped stash push",
          verdict("git stash push -- src/x.py") is None)
    check("gu17 ...and a path-scoped checkout that git was TOLD is a path, even "
          "forced", verdict("git checkout -f -- src/x.py") is None)
    check("gu18 a plain branch switch is not destruction - git refuses on its "
          "own rather than clobbering",
          verdict("git checkout main") is None
          and verdict("git switch main") is None)
    check("gu19 a soft or mixed reset leaves the worktree alone",
          verdict("git reset --soft HEAD~1") is None
          and verdict("git reset HEAD~1") is None)
    check("gu20 a dry-run clean is a read",
          verdict("git clean -nd") is None)
    check("gu21 the stash READS and RESTORES are never refused - a guard that "
          "fires on a read is one people route around",
          all(verdict("git stash " + sub) is None
              for sub in ("list", "show -p", "apply", "pop", "drop")))
    check("gu22 `--help` is a manual page",
          verdict("git stash --help") is None
          and verdict("git clean -h") is None)
    check("gu23 anything that is not git is silent",
          verdict("rm -rf build && npm ci") is None)
    check("gu24 read-only git is silent",
          verdict("git status --porcelain") is None
          and verdict("git diff HEAD") is None
          and verdict("git log --oneline -5") is None)
    check("gu25 a destructive command WRITTEN ABOUT is not one performed - the "
          "verdict comes from the operation, and documenting these rules is a "
          "daily operation here",
          verdict('git commit -m "never run git reset --hard on a dirty tree"')
          is None)
    check("gu26 ...including in a heredoc on its way into a FILE",
          verdict("cat > NOTES.md <<'EOF'\ngit reset --hard is banned\nEOF")
          is None)

    # --- the tree decides, and the whole end-to-end rule ---------------------
    tmp = tempfile.mkdtemp(prefix="guard-uncommitted-")
    try:
        dirty = os.path.join(tmp, "dirty")
        clean = os.path.join(tmp, "clean")
        os.makedirs(dirty)
        os.makedirs(clean)
        _fixture(dirty, True)
        _fixture(clean, False)

        got = decide("git reset --hard HEAD", dirty)
        check("gu27 the incident's own command, on a tree holding work: REFUSED, "
              "and the refusal NAMES the files - %r" % (got,),
              got and "kept.txt" in got and "staged.txt" in got)
        check("gu28 ...and names the path-scoped way forward and the commit one, "
              "so a subagent can act on it without a human",
              got and "git checkout -- <path>" in got and "git commit" in got)
        check("gu29 ...and it does NOT claim the untracked files, which a hard "
              "reset leaves exactly where they are",
              got and "untracked.txt" not in got)

        # THE ALLOW CASES AGAIN, against a real tree. These are the ones a
        # widening of the deny must break, and they are here rather than only in
        # the text arm because the tree is half of every verdict.
        check("gu30 the SAME command on a CLEAN tree is silent - an ordinary, "
              "safe operation, and a guard that refused it would be switched off",
              decide("git reset --hard HEAD", clean) is None)
        check("gu31 ...and so is every other one of them on a clean tree",
              all(decide(cmd, clean) is None
                  for cmd in ("git checkout -- .", "git restore .",
                              "git clean -fdx", "git stash")))
        check("gu32 a path-scoped undo on a DIRTY tree stays silent",
              decide("git checkout -- kept.txt", dirty) is None
              and decide("git restore --staged staged.txt", dirty) is None)
        check("gu33 ...and so does ordinary non-git work on a dirty tree",
              decide("npm ci && node tools/x.mjs", dirty) is None)

        got = decide("git clean -fd", dirty)
        check("gu34 a clean names what CLEAN would remove, asked of `git clean "
              "-n` carrying the same scope flags - the untracked directory is in "
              "it because -d was given, and the tracked edits are not: %r"
              % (got,),
              got and "untracked.txt" in got and "newdir/" in got
              and "kept.txt" not in got)
        got = decide("git clean -f", dirty)
        check("gu35 ...and without -d the same tree loses the file but NOT the "
              "untracked directory, which a refusal built from `??` lines would "
              "have misnamed: %r" % (got,),
              got and "untracked.txt" in got and "newdir" not in got)

        got = decide("git stash", dirty)
        check("gu36 a stash refusal cites the invariant rather than restating "
              "it: %r" % (got,),
              got and "orchestrator.md" in got)

        # --- fail CLOSED, which is this hook's inversion of the house rule ----
        outside = os.path.join(tmp, "not-a-repo")
        os.makedirs(outside)
        got = decide("git reset --hard", outside)
        check("gu37 git that cannot be ASKED refuses and says so - uncommitted "
              "work is in no reflog, so the unknown direction is the one that "
              "cannot be taken back: %r" % (got,),
              got and "UNKNOWN" in got)
        check("gu38 ...and the fail-closed branch is scoped to what it protects: "
              "ordinary work outside a repository is untouched",
              decide("git status", outside) is None
              and decide("ls -la", outside) is None)

        # --- the text fallback, for a line that will not tokenize -------------
        check("gu39 a line `shlex` cannot read falls back to the shapes and "
              "stays conservative on a DIRTY tree",
              decide('git reset --hard "', dirty) is not None)
        check("gu40 ...and even that fallback is quiet on a clean tree, because "
              "the tree is half of every verdict",
              decide('git reset --hard "', clean) is None)
        check("gu41 ...and it says the line could not be tokenized as given, so "
              "the verdict is the weaker claim it is",
              "could not be tokenized" in (decide('git reset --hard "', dirty)
                                           or ""))

        # --- the cap ---------------------------------------------------------
        wide = os.path.join(tmp, "wide")
        os.makedirs(wide)
        _fixture(wide, False)
        for n in range(NAMED_CAP + 5):
            with open(os.path.join(wide, "f%02d.txt" % (n,)), "w",
                      encoding="utf-8", newline="\n") as fh:
                fh.write("x\n")
        got = decide("git clean -fd", wide)
        check("gu42 a refusal naming two hundred paths is not read, so the list "
              "is capped and the rest COUNTED: %r" % (got,),
              got and "and 5 more" in got
              and got.count(".txt (") == NAMED_CAP)

        # --- a line that will not tokenize: its DATA is not its operation -----
        # Each fixture below is built so `shlex` refuses it (an apostrophe in a
        # quoted-delimiter heredoc, or an odd double quote inside one), because
        # that is the branch which used to read every byte as a command.
        task_add = ("python3 plugins/audit/scripts/manifest/audit-task.py add "
                    "--phase P1 --title t --description-file - <<'EOF'\n"
                    "The guard refused this task's text, which quotes "
                    "`git stash` and `git checkout -- .`.\nEOF")
        subst_add = ("python3 audit-task.py add --phase P1 --description "
                     "\"$(cat <<'EOF'\nquote: \"git stash\" and \"git checkout "
                     "-- .\" are refused; the third quote is \" alone\nEOF\n)\"")
        stdin_note = ("audit-task.py note P1 \"never run git stash\" <<'EOF'\n"
                      "it's git checkout -- . that loses work\nEOF")
        check("gu43 an audit-task add whose heredoc description QUOTES a stash "
              "and a checkout is allowed on a dirty tree - the body is the "
              "description's bytes, not a command: %r"
              % (decide(task_add, dirty),),
              decide(task_add, dirty) is None)
        check("gu44 ...and so is the same description inside \"$(cat <<'EOF' "
              "...)\" with an odd quote in it, and a quoted argument beside a "
              "heredoc body: %r" % ((decide(subst_add, dirty),
                                     decide(stdin_note, dirty)),),
              decide(subst_add, dirty) is None
              and decide(stdin_note, dirty) is None)
        # The deny direction. A fallback that read NOTHING would pass gu43 and
        # gu44; these are the cases that go red under that over-narrowing.
        check("gu45 the SAME commands run outside the heredoc are still "
              "refused, alone and after the heredoc in one untokenizable line",
              decide("git stash", dirty) is not None
              and decide("git checkout -- .", dirty) is not None
              and decide(task_add + "\ngit stash", dirty) is not None
              and decide(task_add + "\ngit checkout -- .", dirty) is not None)
        check("gu46 an untokenizable line whose quoted or heredoc text IS "
              "executed is still refused: a heredoc fed to a shell, a "
              "command substitution inside double quotes, one inside an "
              "UNQUOTED-delimiter heredoc, and `sh -c \"...\"`",
              all(decide(cmd, dirty) is not None for cmd in (
                  "bash <<'EOF'\ngit stash\nit's\nEOF",
                  "echo \"$(git stash)\" it's",
                  "cat > n.md <<EOF\n$(git checkout -- .)\nit's\nEOF",
                  "sh -c \"git clean -fdx\" it's",
                  "echo `git reset --hard` it's")))
        check("gu47 ...and the data reading is quiet on a CLEAN tree too, while "
              "the shell-fed heredoc is quiet there for the tree's reason",
              decide(task_add, clean) is None
              and decide("bash <<'EOF'\ngit stash\nit's\nEOF", clean) is None)
        check("gu48 a quoted program word, a quoted git verb, an interpreter's "
              "inline code and a program run by path are read, untokenizable "
              "line or not",
              all(decide(cmd, dirty) is not None for cmd in (
                  "\"git\" stash; echo it's",
                  "git \"stash\"; echo it's",
                  "python3 -c \"import os; os.system('git stash')\" it's",
                  "cat > x.sh <<'EOF'\ngit stash\nEOF\n./x.sh it's")))
        check("gu49 ...and so is a quoted argument of an interpreter running "
              "a script file: no runner list decides what is data any more, "
              "the house template alone does: %r"
              % (decide("python3 tools/x.py --note \"never git stash\" it's",
                        dirty),),
              decide("python3 tools/x.py --note \"never git stash\" it's",
                     dirty) is not None)
        check("gu50 a dot closing a substitution is the tree-wide pathspec - "
              "the cheap pre-filter used to wave `$(git checkout -- .)` through "
              "before the parser was asked",
              decide("x=$(git checkout -- .)", dirty) is not None
              and decide("echo \"$(git restore .)\"", dirty) is not None)
        # Two untokenizable lines: one whose odd quote is in the command text,
        # and one whose odd quote is in a shell-fed BODY. A body the lexer
        # cannot read is never closed by hand into one it can, so both reach
        # the text reading.
        hd = decide("git stash\necho it's", dirty) or ""
        bd = decide("bash <<'EOF'\ngit stash\nit's\nEOF", dirty) or ""
        ex = decide(subst_add + "\ngit reset --hard", dirty) or ""
        check("gu51 the two readings say which they are: an untokenizable line "
              "and an untokenizable shell body are read as TEXT, and a "
              "house-form line - its odd quote lifted with its body - read as "
              "an operation, with no claim of text: %r" % ((hd, bd, ex),),
              "TEXT" in hd and "tokenized" in hd
              and "TEXT" in bd and "tokenized" in bd
              and ex and "TEXT" not in ex and "tokenized" not in ex)
        # Each line below was measured passing: the reading that took quoted
        # arguments out as data unless a runner list named the command never
        # named these, and the stray quote on the next line is what sends the
        # line to that reading at all.
        _st = "git " + "stash"
        _stray = "\necho '"
        runners = (
            "$SHELL -c '%s'" % _st,
            "\"${BASH}\" -c '%s'" % _st,
            "S=sh; $S -c '%s'" % _st,
            "printf '%s' | $SHELL" % _st,
            "nix-shell --run '%s'" % _st,
            "tar -xf a.tar --to-command='%s'" % _st,
            "ssh host '%s'" % _st,
            "script -qc '%s'" % _st,
            "flock /tmp/l -c '%s'" % _st,
            "su -c '%s'" % _st,
            "git -c alias.x='!%s' x" % _st,
            "find . -exec sh -c '%s' \\;" % _st,
            "trap '%s' EXIT" % _st,
        )
        passed = [cmd for cmd in runners if decide(cmd + _stray, dirty) is None]
        check("gu52 an untokenizable line is graded whole: a quoted command "
              "handed to an expansion as the program, a remote or wrapped "
              "runner, a git alias, find -exec or trap is refused on a dirty "
              "tree: %r" % (passed,), not passed and len(runners) == 13)
        # Two apostrophes in each body, so a body read as shell leaves the line
        # untokenizable and the shapes see it; with one, the stray quote and
        # the body's apostrophe pair up, the line parses, and the case could
        # not tell a lifted body from an unlifted one.
        house = (
            "git commit -m \"$(cat <<'EOF'\nsee %s, it's Bob's\nEOF\n)\"",
            "gh pr create --title t --body \"$(cat <<'EOF'\n%s: it's Bob's\n"
            "EOF\n)\"",
            "git commit -m \"`cat <<'EOF'\nsee %s, it's Bob's\nEOF\n`\"",
        )
        refused = [cmd for cmd in house
                   if decide((cmd % _st) + _stray, dirty) is not None]
        check("gu53 ...while the house template's body is lifted first, so a "
              "commit message, a pull request body and the backquoted form "
              "quoting a stash pass on a dirty tree: %r" % (refused,),
              not refused and len(house) == 3)
        # A quote the text leaves open does not carry into a shell body: an
        # apostrophe line in the body closed it, the stash read as the inside
        # of a quote, and the line parsed with nothing destructive in it.
        shaped = ("bash <<'EOF'\n%s\n'\nEOF\necho '" % _st,
                  "bash <<'EOF'\n%s\nEOF\necho '" % _st)
        passed = [cmd for cmd in shaped if decide(cmd, dirty) is None]
        check("gu54 a stash fed to a shell is refused on a dirty tree when the "
              "text opens a quote a body line closes, and in its twin with no "
              "closing line: %r" % (passed,), not passed and len(shaped) == 2)
        # A body that ends open only in the lexer's reading - a nested quoted
        # heredoc's apostrophe, a Python escape the shell does not have - is
        # not repaired with a closer: that made the verb line the inside of a
        # quote and the line an allowed operation.
        _rh = "git reset --" + "hard HEAD~1"
        misread = []
        for verb in (_rh, _st):
            misread += [
                "bash <<'EOF'\ncat <<'Y'\nit's\nY\n%s\nEOF" % verb,
                "bash <<'EOF'\ncat >f <<'Y'\nit's\nY\n%s\nEOF" % verb,
                "python3 - <<'PY'\nprint('it\\'s')\nimport os\n"
                "os.system(\"%s\")\nPY" % verb]
        passed = [cmd for cmd in misread if decide(cmd, dirty) is None]
        check("gu55 a reset and a stash run by a shell body holding a nested "
              "quoted heredoc with an apostrophe, and by a Python body with an "
              "escaped apostrophe, are refused on a dirty tree: %r" % (passed,),
              not passed and len(misread) == 6)
        # A body written to a file is data only while nothing in the command
        # runs the file: a later clause running it makes the body its program.
        # Each line parses, so the tokenized reading is the one asked.
        _wr = "cat > probe.sh <<'EOF'%s\n" + _st + "\nEOF%s"
        ran = (_wr % ("", "\nsh probe.sh"), _wr % ("; bash probe.sh", ""),
               _wr % (" && ./probe.sh", ""), _wr % ("", "\n. ./probe.sh"))
        passed = [cmd for cmd in ran if decide(cmd, dirty) is None]
        check("gu56 a stash in a body written to a file a later clause runs - "
              "by a shell, as the program word, dot-sourced - is refused on a "
              "dirty tree, while the same body only written passes: %r"
              % (passed,), not passed and len(ran) == 4
              and decide(_wr % ("", ""), dirty) is None)
    finally:
        _rmtree_git_safe(tmp)

    print("")
    print("%s: %d/%d cases passed"
          % ("ALL PASS" if not failed else "SELFTEST FAILED",
             len(cases) - len(failed), len(cases)))
    return 1 if failed else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    raise SystemExit(main())
