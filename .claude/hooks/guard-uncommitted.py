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
# The second job is the fallback for a line `shlex` cannot read at all (an
# unbalanced quote). There the same table is the whole reading, and its
# over-firing on quoted text is the conservative direction: an unparseable line
# that names one of these operations is refused when the tree is dirty rather than
# guessed at. That is the shape `guard-history-rewrite.py` settled on, for the
# same reason.
#
# ONE TABLE, TWO USES. A separate pre-filter would be a second description of the
# same set, and the two would drift in the direction that matters - a shape
# present in the fallback and missing from the pre-filter never reaches it.
_SHAPES = (
    r"reset\b[^|;&\n]*--hard",
    r"(?:checkout|switch)\b[^|;&\n]*(?:--force\b|--discard-changes\b"
    r"|(?<![\w-])-[A-Za-z]*f[A-Za-z]*(?![\w-])|(?<!\S)\.(?!\S))",
    r"restore\b[^|;&\n]*(?<!\S)\.(?!\S)",
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

    `how` is "operation" when the line parsed, "text" when it did not and the
    shapes above decided instead. The caller reports which, because a verdict
    reached by text is a weaker claim and saying so is cheaper than being wrong
    about it quietly.
    """
    if not DESTRUCTIVE_TEXT.search(command or ""):
        return (None, "operation")      # the cheap door: no shape, no parse
    helper = parser()
    invocations = helper.git_invocations(command) if helper is not None else None
    if invocations is not None:
        for verb, args in invocations:
            found = judge(verb, args, helper)
            if found is not None:
                return (found, "operation")
        return (None, "operation")
    # The line will not tokenize, or the parser could not be loaded. The text
    # matched a destructive shape and nothing can narrow it, so the widest loss
    # set is assumed and the refusal says it was read from text.
    return ({"op": "this command", "kinds": (LOSS_TRACKED, LOSS_UNTRACKED),
             "probe": "status", "remedy": REMEDY_PATHS}, "text")


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
    with open(os.path.join(root, "kept.txt"), "w") as fh:
        fh.write("committed\n")
    run("add", "kept.txt")
    run("commit", "-qm", "base")
    if not dirty:
        return
    with open(os.path.join(root, "kept.txt"), "a") as fh:
        fh.write("an unstaged edit nobody has proven yet\n")
    with open(os.path.join(root, "staged.txt"), "w") as fh:
        fh.write("staged\n")
    run("add", "staged.txt")
    with open(os.path.join(root, "untracked.txt"), "w") as fh:
        fh.write("untracked\n")
    os.makedirs(os.path.join(root, "newdir"))
    with open(os.path.join(root, "newdir", "deep.txt"), "w") as fh:
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
        check("gu41 ...and it says the verdict was read from text rather than "
              "from the operation",
              "TEXT" in (decide('git reset --hard "', dirty) or ""))

        # --- the cap ---------------------------------------------------------
        wide = os.path.join(tmp, "wide")
        os.makedirs(wide)
        _fixture(wide, False)
        for n in range(NAMED_CAP + 5):
            with open(os.path.join(wide, "f%02d.txt" % (n,)), "w") as fh:
                fh.write("x\n")
        got = decide("git clean -fd", wide)
        check("gu42 a refusal naming two hundred paths is not read, so the list "
              "is capped and the rest COUNTED: %r" % (got,),
              got and "and 5 more" in got
              and got.count(".txt (") == NAMED_CAP)
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
