#!/usr/bin/env python3
"""
PreToolUse hook (matcher: Bash) — refuse to publish a release while the plan
carries an open bug. THIS REPO'S OWN CONFIGURATION, not the audit plugin's product.

WHAT IT IS FOR. `v2.0.0` and `v2.0.1` were both released while four bugs sat
`open` in the manifest, and a bug reported during the second one went into a
scratch plan file no gate reads. Twenty-one gates were green and every one of them
was honest: not one asked whether the plan still carried an open bug. This is that
question, asked at the only moment it cannot be skipped - the command that
publishes.

WHAT COUNTS AS PUBLISHING, and the line is drawn where the consequence is. A tag
that has been pushed is never moved here and a Release is a page the world lands
on, so those are refused. `git push origin main` is NOT: pushing code is not
releasing it, and a guard that blocked ordinary work would be routed around within
a day - which is the failure mode `guard-false-positive-class` is about. Creating
a tag LOCALLY is refused too, because a local tag is what the push then publishes
and refusing only the push leaves a trap already loaded.

A SECOND LIST HOLDS THE SAME RELEASE, BESIDE THE BUGS: a merged phase whose
full-run answer is not WHOLE refuses exactly the same commands, for the reason
the manifest's "third place" exists at all: a merge is not the same claim as a
full suite having actually run against it. PROVISIONAL - no green, measured,
clean, verbatim full run yet recorded whose head contains what that phase
merged into - holds it, and so does UNKNOWN, a phase whose ancestry the
evidence cannot ask at all: a guard that cannot answer refuses. Each is named
with the basis `full_status` gave. `read_held_phases` asks the plugin's own
`full_status` this question rather than restating it, the way `read_bugs`
already asks `effective_bug_status` rather than reading a stored field. A
plan naming no third place (`meta.fullGate` absent) has no phase to hold, so
this guard then judges the bugs alone.

THE WAY PAST IT is `arm-release-bypass.py`: the maintainer types the keyword and a
single-use slot appears. Nothing the model writes can arm it. That is why the
switch is on the prompt and not on this command - a guard the caller can satisfy
by writing the right words is not a guard. The message it prints names the
held phases beside the bugs, through this file's own `read_held_phases`, so
what is being shipped over is never understated.

FAIL-LOUD, NOT FAIL-OPEN, AND THAT IS THE OPPOSITE OF THIS REPO'S OTHER HOOKS.
`SECURITY.md`'s table puts advisory paths on fail-open: a guard that crashes must
not stop legitimate work. This one inverts it for one reason - the thing it
protects is irreversible. A pushed tag cannot be taken back, so a guard that
cannot read the manifest must refuse rather than wave a release through on its own
malfunction. It names which list it could not read, and reports the other.

Contract: a block emits {"hookSpecificOutput": {"permissionDecision": "deny",
"permissionDecisionReason": ...}} on stdout and exits 0 - the canonical PreToolUse
protocol.

Exit codes: 0 always (the decision travels in the payload, never in the code).
"""
import json
import os
import re
import subprocess
import sys
import time

STATE_REL = os.path.join(".claude", "state")
MANIFEST_REL = os.path.join("docs", "audit", "audit-plan.json")
# The command that records a merged phase's `mergedHead` after the fact - the
# remedy an unanswerable phase's refusal names.
CLOSE_PHASE_REL = os.path.join("plugins", "audit", "scripts", "git",
                               "close-phase.py")
# The words that mean a bug will not hold a release. `fixed` is what the plugin's
# derivation produces; the rest are the verdicts a person wrote, and a bug closed
# with one this tuple has not learned would hold every release until somebody
# rewrote its status to a word that is less true. A hook may not import the
# plugin, so this restates rather than reads — and `gr` cases below drive the
# plugin's own vocabulary against it so the two cannot come apart in silence.
CLOSED = ("fixed", "wontfix", "not_a_bug")
KEYWORD = "#release-with-bugs"
# How this file names the two ways a merged phase holds a release, mapped once
# from `full_status`'s own answers in `read_held_phases`. They are this file's
# words for its message, kept apart because each is settled differently.
HELD_PROVISIONAL = "provisional"
HELD_UNANSWERABLE = "unanswerable"
# How much of `full_status`'s basis a rendered phase keeps - wide enough that an
# UNKNOWN basis, which names two commit ids before it says why git could not
# answer, keeps its reason. `arm-release-bypass.py` renders on this same cap.
BASIS_CAP = 240
# How many phases of one kind a refusal lists before summarising the rest. A
# plan with many legacy merges would otherwise refuse with a wall of text;
# `/audit:status` is where the whole list is read, and the arming message
# still names every one, because that is the moment they are shipped over.
REFUSAL_PHASE_CAP = 5

# What publishes. Each match is anchored at a command boundary (start of line,
# `&&`, `;`, `|`) so a word appearing inside a filename or a commit message
# cannot trip it. `-C` belongs to THAT invocation, not to the first `git` word
# in the command: a quoted operand may contain spaces, and a tag push carries
# the same option the tag creation does.
_BOUNDARY = r"(?:^|[;&|]\s*|\s&&\s*|\s\|\|\s*)\s*"
# A quoted operand must not also match the unquoted arm. Those two arms
# matching the same text is what made a failed search retry every split of
# a long `-C` run, and a hook that does not finish is a hook that does not
# refuse. No empty arm: that split is the same retry.
_C_OPTS = (r"(?:\s+-C(?:\s+\"[^\"]*\"|\s+'[^']*'|\s+[^\s\"']\S*"
           r"|[^\s\"']\S*))*")
_GIT_AT = _BOUNDARY + r"git(?P<copts>" + _C_OPTS + r")\s+"
_TAG_AT = re.compile(_GIT_AT + r"tag\b(?P<rest>[^;&|\n]*)")
_PUSH_AT = re.compile(_GIT_AT + r"push\b(?P<rest>[^;&|\n]*)")
_GH_AT = re.compile(_BOUNDARY + r"gh\s+release\s+create\b")
_PUSH_PUBLISHES = re.compile(
    r"(?:--tags\b|--follow-tags\b|\brefs/tags/|\sv\d+\.\d+)")
_C_OPERAND = re.compile(r"-C(?:\s+(\"[^\"]*\"|'[^']*'|\S+)|\S*)")
# Listing and deleting are not a release. A bare `git tag` lists. These are
# words of the tag invocation, not a lookahead over the rest of the command:
# a later `echo -l`, or the same letters inside a quoted message, must not
# un-publish a tag that was actually created.
# `--sort`, `--format`, `--column` and `--no-column` do not force list mode.
# With a tag name beside them, git creates the tag.
_TAG_FORCE_LIST = ("-l", "--list", "--contains", "--no-contains",
                   "--points-at", "--merged", "--no-merged")
_TAG_NOT_CREATE = ("--verify", "-v", "-d", "--delete")
_TAG_VALUE = ("-m", "-F", "--message", "--file", "--sort", "--format",
              "-u", "--local-user")


def project_dir():
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def shell_path(rel):
    """`rel` spelled for a shell a reader pastes into: forward slashes only.

    The `*_REL` constants are built with `os.path.join`, so on windows they hold
    backslashes - and the reader there types into Git Bash, where an unquoted
    backslash escapes the next character and `plugins\\audit\\...` reaches the
    program as `pluginsaudit...`. Python on windows opens a forward-slash path as
    readily as a backslash one, so this spelling is correct on every platform.
    Every segment those constants join is a fixed name with no backslash in it,
    which is why any backslash here can only be a separator.
    """
    return str(rel).replace("\\", "/")


def remove_tree(path):
    """`shutil.rmtree` that also works on a fixture containing a git repository.

    A COPY OF `plugins/audit/tests/_harness.remove_tree`, which holds the
    measurement that chose it: git writes its loose objects read-only, windows
    refuses to unlink a read-only file, and `ignore_errors=True` hides that, so a
    plain removal leaves `.git/objects/**` behind there and says nothing. This
    file is a repository hook and may not import the test harness, so it keeps a
    copy, and `gr48` compares the two statement for statement.

    THE COPY DIFFERS IN WHERE `shutil` IS IMPORTED, and in nothing else. Only the
    selftest removes anything, and this hook starts on every Bash call; a
    module-level import is a measurable start-up cost on every one of them for a
    function no ordinary call reaches (`python3 -X importtime -c "import shutil"`
    shows it). `gr48` drops that leading import before comparing.
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


def removal_copy_drift(own_source, home_source, name="remove_tree"):
    """Why this file's `name` no longer runs the home's statements, or None.

    Both functions are compared with their docstrings dropped - the home carries
    the measurement and this copy carries the pointer, so they must read
    differently - and with this copy's leading `import shutil` dropped, the one
    difference `remove_tree` above states. A source that does not parse, or that
    has lost the function, is reported by side rather than read as agreement.
    """
    import ast

    def shape(source, side, drop_import):
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError) as exc:
            return None, "%s does not parse: %s" % (side, exc)
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or node.name != name:
                continue
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                body = body[1:]
            if drop_import and body and isinstance(body[0], ast.Import) \
                    and [a.name for a in body[0].names] == ["shutil"]:
                body = body[1:]
            if not body:
                return None, "%s carries `%s` with no statements" % (side, name)
            return "\n".join(ast.dump(stmt) for stmt in body), None
        return None, "%s carries no module-level `def %s`" % (side, name)

    own, why = shape(own_source, "this hook's copy", True)
    if why is not None:
        return why
    home, why = shape(home_source, "the harness home", False)
    if why is not None:
        return why
    if own != home:
        return ("this hook's `%s` no longer runs the statements the harness "
                "home does - one of the two was changed without the other"
                % (name,))
    return None


def _invocation_words(rest):
    """Words of one invocation, or None when a quote does not close.

    Stops at an unquoted comment. Does not raise: an apostrophe in a comment
    or a message is not a directory change, and a reader that raises on it
    turns a release into an UNKNOWN refusal.
    """
    words = []
    text = rest or ""
    index, end = 0, len(text)
    while index < end:
        while index < end and text[index] in " \t":
            index += 1
        if index >= end or text[index] in ";|&\n" or text[index] == "#":
            break
        if text[index] in "'\"":
            quote = text[index]
            close = text.find(quote, index + 1)
            if close < 0:
                return None
            words.append(text[index + 1:close])
            index = close + 1
            continue
        start = index
        while index < end and text[index] not in " \t;|&\n":
            if text[index] == "\\" and index + 1 < end:
                index += 2
                continue
            index += 1
        words.append(text[start:index])
    return words


def _option_name(word):
    if word.startswith("--") and "=" in word:
        return word.split("=", 1)[0]
    return word


def _forces_list(word):
    """An option that puts `git tag` in list mode, name or not."""
    if _option_name(word) in _TAG_FORCE_LIST:
        return True
    return (len(word) >= 2 and word[0] == "-" and not word.startswith("--")
            and word[1] == "n"
            and (len(word) == 2 or word[2:].isdigit()))


def _skips_next(word):
    """True when the next word is this option's value, not a tag name."""
    if word.startswith("--") and "=" in word:
        return False
    return _option_name(word) in _TAG_VALUE


def _tag_creates(rest):
    """True when this tag invocation creates a tag.

    An invocation whose words cannot be read is treated as creating: a release
    guard that cannot tell a list from a create must refuse the create, not
    wave it through. A bare invocation lists. So does one that carries no tag
    name: `--sort` and `--format` without a name list, and with a name they
    create. A sort key or a message is not that name.
    """
    words = _invocation_words(rest)
    if words is None:
        return True
    if not words:
        return False
    if any(_forces_list(word) or _option_name(word) in _TAG_NOT_CREATE
           for word in words):
        return False
    index, total = 0, len(words)
    while index < total:
        word = words[index]
        if _skips_next(word):
            index += 2
            continue
        if word.startswith("-"):
            index += 1
            continue
        return True
    return False


def _unquote(word):
    if len(word) >= 2 and word[0] == word[-1] and word[0] in "'\"":
        return word[1:-1]
    return word


def _c_operands(copts):
    """The `-C` operands of one invocation, in the order git applies them.

    [] when that invocation names none. None when `-C` has no operand.
    """
    found = []
    for match in _C_OPERAND.finditer(copts or ""):
        operand = match.group(1)
        if operand is None:
            glued = match.group(0)
            if glued == "-C":
                return None
            found.append(glued[2:])
            continue
        found.append(_unquote(operand))
    return found


def _publishers(command, cfg_mod=None):
    """Every publishing invocation, as `(reason, operands)`.

    `operands` is that git's `-C` chain, [] when it names none, None when an
    operand is missing. A `gh` release names no git `-C`. Each publishing
    invocation is returned: a later one, in another tree, is still a release.

    A clause begins where a shell can begin a command. Matching only there
    keeps a `git tag` example inside a quoted argument from reading as a
    publisher, while `command_clauses` still separates every live publisher.
    `runnable_text` removes heredoc data before either reader sees it.
    """
    found = []
    cfg_mod = cfg_mod or _hooks_config(project_dir())
    text = str(command or "")
    clauses = (cfg_mod.command_clauses(cfg_mod.runnable_text(text))
               if cfg_mod is not None else [text])
    for clause in clauses:
        match = _TAG_AT.match(clause)
        if match and _tag_creates(clause[match.start("rest"):]):
            found.append(("creates a git tag",
                          _c_operands(match.group("copts"))))
        match = _PUSH_AT.match(clause)
        if match and _PUSH_PUBLISHES.search(match.group("rest") or ""):
            found.append(("pushes a tag", _c_operands(match.group("copts"))))
        if _GH_AT.match(clause):
            found.append(("publishes a GitHub Release", []))
    return found


def publishing(command):
    """`reason` when `command` would publish a release, else None.

    Read over the WHOLE command string rather than the first word: a release is
    routinely typed as `git tag -a v1 -m … && git push origin v1`, and a guard
    that only inspected the head of the line would wave the second half through.
    """
    found = _publishers(command)
    return found[0][0] if found else None


def _effective(project):
    """The plugin's own `effective_bug_status`, or None when it cannot be reached.

    IMPORTED, NOT REIMPLEMENTED, and the first draft of this file got it wrong:
    it read the raw `status` field and reported five open bugs where
    `/audit:status` reported one. A bug materialized into a task reads `fixed`
    once that task is done - the orchestrator never writes `bugs[]` during a run
    - so the stored field lags on purpose, and a second reading of it is a second
    answer that had already disagreed before this comment was written.

    The plugin's own hooks may not import `scripts/`; this one is not a plugin
    hook. It is this repository's configuration, and this repository always has
    `plugins/audit/scripts/` sitting next to it.

    LAZILY, from inside the one branch that needs it: this hook runs on every
    Bash call, and `publishing()` has already said no by the time most of them
    get here. The import cost belongs to a release, not to every `ls`.

    Resolved from THIS FILE's own repository rather than from `project`, because
    those are two different things: `project` is where the manifest is, and the
    plugin's code is wherever this hook was checked out. The fallback keeps a
    caller that hands over a different project working when its own tree carries
    the plugin.
    """
    here = os.path.dirname(os.path.abspath(__file__))       # .claude/hooks
    repo = os.path.dirname(os.path.dirname(here))
    for root in (repo, project):
        scripts = os.path.join(root, "plugins", "audit", "scripts")
        if not os.path.isdir(scripts):
            continue
        for entry in (scripts, os.path.join(scripts, "manifest")):
            if entry not in sys.path:
                sys.path.insert(0, entry)
        try:
            import _manifest_io
            return _manifest_io
        except Exception:
            continue
    return None


def _evidence_modules(project):
    """`(_evidence_io, _worktrees, _manifest_vocab)`, or None when they cannot
    be reached - the lazy load `read_held_phases` needs, patterned on
    `_effective`'s load of `_manifest_io` for the same reason: most Bash calls
    never reach the publishing branch, so the cost of reaching
    `scripts/governance`, `scripts/git` and `scripts/manifest` belongs to a
    release alone, not to every command this hook is asked about.
    """
    here = os.path.dirname(os.path.abspath(__file__))       # .claude/hooks
    repo = os.path.dirname(os.path.dirname(here))
    for root in (repo, project):
        scripts = os.path.join(root, "plugins", "audit", "scripts")
        if not os.path.isdir(scripts):
            continue
        for entry in (scripts, os.path.join(scripts, "governance"),
                      os.path.join(scripts, "git"),
                      os.path.join(scripts, "manifest")):
            if entry not in sys.path:
                sys.path.insert(0, entry)
        try:
            import _evidence_io
            import _worktrees
            import _manifest_vocab
            return (_evidence_io, _worktrees, _manifest_vocab)
        except Exception:
            continue
    return None


def _hooks_config(project):
    """The plugin's own `plugins/audit/hooks/_config`, loaded lazily and by
    the same two-root search `_effective` and `_evidence_modules` use.

    THIS FILE IS NOT A PLUGIN HOOK - its own docstring says so - but the tree
    a release command targets is exactly the question `_config.tree_for`
    already answers for every hook that does count as one, and a second
    answer to that question invented here could disagree with the first the
    day a linked worktree entered the picture.
    """
    here = os.path.dirname(os.path.abspath(__file__))       # .claude/hooks
    repo = os.path.dirname(os.path.dirname(here))
    for root in (repo, project):
        hooks = os.path.join(root, "plugins", "audit", "hooks")
        if not os.path.isfile(os.path.join(hooks, "_config.py")):
            continue
        if hooks not in sys.path:
            sys.path.insert(0, hooks)
        try:
            import _config
            return _config
        except Exception:
            continue
    return None


def _shell_moves(cfg_mod, command):
    """True when a clause starts with cd, pushd or popd.

    `command_clauses` is the reader `effective_cwd` walks, so a missing
    payload cwd is unknown only when that walk would have had a directory
    change to follow. A comment's apostrophe must not count as one.
    """
    for clause in cfg_mod.command_clauses(cfg_mod.runnable_text(command or "")):
        parts = clause.split(None, 1)
        if parts and parts[0].lower() in ("cd", "pushd", "popd"):
            return True
    return False


def _session_base(cfg_mod, data, project, command):
    """Where the shell stands for this command, or None when that cannot be read.

    A payload that names no cwd, and a command that does not move the shell,
    answers to `project`. An unreadable `cd` does not.
    """
    cwd = data.get("cwd")
    if cwd:
        target = cfg_mod.effective_cwd(command or "", cwd)
        if target is None:
            return None
        return target
    if _shell_moves(cfg_mod, command):
        return None
    return project


def _apply_c_chain(cfg_mod, base, operands):
    """The directory git uses after each `-C`, or None if one cannot be read.

    Each relative operand joins onto the directory so far; an absolute one
    replaces it. `.` and `..` are normalised, which is what a later `-C .`
    means: stay where the previous `-C` landed, not the session. `base` when
    the invocation names no `-C`.
    """
    if operands is None:
        return None
    target = base
    for operand in operands:
        if not cfg_mod.resolvable_destination(operand):
            return None
        if os.path.isabs(operand):
            target = os.path.normpath(operand)
        else:
            target = os.path.normpath(os.path.join(target, operand))
    return target


def _placed_root(cfg_mod, data, project, target):
    placed = cfg_mod.tree_for(data, target, project=project)
    root = placed.get("root")
    return str(root) if root else project


def resolved_tree(payload, project):
    """The tree whose PLAN the first publishing invocation answers to.

    `_config.tree_for`, asked about THIS COMMAND's own effective working
    directory - never `CLAUDE_PROJECT_DIR` alone. A release typed from a
    linked worktree publishes over THAT worktree's plan, which may carry a
    provisional phase the project's own copy does not, so judging it against
    the project unconditionally would be asking the wrong tree the question
    this file exists to ask.

    Falls back to `project` when `_config` cannot be reached. An unreadable
    directory change instead answers None: placing it in `project` would
    silently judge a release where the shell does not run it. A payload that
    names no cwd, and a command that does not move the shell, is not that
    case - it answers to `project`, which is the tree the call was given.
    `decide` asks the same chain walker of every publishing invocation; this
    function is the first of them, which is the question its own cases ask.
    """
    cfg_mod = _hooks_config(project)
    if cfg_mod is None:
        return project
    data = payload if isinstance(payload, dict) else {}
    if not data:
        return project
    command = (data.get("tool_input") or {}).get("command", "")
    try:
        target = _session_base(cfg_mod, data, project, command)
        if target is None:
            return None
        publishers = _publishers(command, cfg_mod)
        operands = publishers[0][1] if publishers else []
        target = _apply_c_chain(cfg_mod, target, operands)
        if target is None:
            return None
        return _placed_root(cfg_mod, data, project, target)
    except Exception:
        return project


def _release_trees(payload, project, command, publishers):
    """`(reason, tree)` for every publishing invocation.

    `tree` is None when that invocation's directory cannot be read. A call
    with no payload answers to `project`, which is the tree it was given.
    """
    paired = [(why, project) for why, _operands in publishers]
    if not payload:
        return paired
    cfg_mod = _hooks_config(project)
    data = payload if isinstance(payload, dict) else {}
    if cfg_mod is None or not data:
        return paired
    try:
        base = _session_base(cfg_mod, data, project, command)
        if base is None:
            return [(why, None) for why, _operands in publishers]
        out = []
        for why, operands in publishers:
            target = _apply_c_chain(cfg_mod, base, operands)
            if target is None:
                out.append((why, None))
                continue
            out.append((why, _placed_root(cfg_mod, data, project, target)))
        return out
    except Exception:
        return paired


def _read_plan(mio, project):
    """`(manifest, problem)` - the plan both lists are read from, or why it
    could not be read.

    THE ASSEMBLED manifest, not the raw index. This repository's own plan is
    SHARDED: `json.load` returns phases that are stubs carrying no tasks, so
    every bug's linked task went missing and five bugs read open where
    `/audit:status` reported one. `_panel_write` carries the same scar in its
    own docstring - it read the raw index too, and every per-task edit was
    refused for a task the panel had just listed.

    THE RAISING LOADER, never the `_safe` one. The safe loader answers `{}`
    for a missing or unparsable file, and `{}` reads as a plan naming no third
    place - so the phase list would report "nothing held" for a file nobody
    read. The exception is the basis the refusal names.
    """
    try:
        data = mio.load_manifest(os.path.join(project, MANIFEST_REL))
    except Exception as exc:
        return (None, "%s could not be read (%s)" % (MANIFEST_REL, exc))
    if not isinstance(data, dict):
        return (None, "%s did not parse as a manifest object" % (MANIFEST_REL,))
    return (data, None)


def read_bugs(project):
    """`(open_bugs, problem)` — the plan's open bugs, or why they are unknown.

    The two are returned apart because they are different answers. `([], None)`
    is a plan with nothing open; `(_, "…")` is a plan nobody could read, and
    reporting that as "nothing open" would let a release through on the strength
    of a broken file.

    "Open" is the EFFECTIVE status, which is the plugin's rule and not one of
    this file's own - see `_effective`.
    """
    mio = _effective(project)
    if mio is None:
        return ([], "the plugin's own bug rule could not be loaded from "
                    "plugins/audit/scripts, so `open` cannot be decided here")
    data, problem = _read_plan(mio, project)
    if problem:
        return ([], problem)
    bugs = data.get("bugs")
    if not isinstance(bugs, list):
        return ([], "%s carries no `bugs` list" % (MANIFEST_REL,))
    try:
        by_id = mio.tasks_by_id(data)
    except Exception as exc:
        return ([], "the plan's tasks could not be indexed (%s), so a bug's "
                    "effective status is unknown" % (exc,))
    out = []
    for bug in bugs:
        if not isinstance(bug, dict):
            continue
        try:
            status = mio.effective_bug_status(bug, by_id)
        except Exception:
            status = bug.get("status")
        if str(status or "").lower() not in CLOSED:
            out.append((bug.get("id") or "?", bug.get("severity") or "?",
                        bug.get("title") or ""))
    return (out, None)


def read_held_phases(project):
    """`(held, problem)` - every merged phase whose full-run answer holds a
    release, as `(phaseId, kind, basis, headRecorded)` - `kind` one of
    `HELD_PROVISIONAL` or `HELD_UNANSWERABLE`, `basis` `full_status`'s own,
    `headRecorded` whether the phase records a `mergedHead` - or why that
    cannot be decided at all.

    `headRecorded` IS WHAT TELLS THE TWO CAUSES OF UNKNOWN APART, read off the
    phase rather than parsed out of the basis prose: no `mergedHead` at all is
    repaired by recording one, while a recorded head git could not relate to
    any run's head (an unreachable commit, a shallow clone) is repaired by
    making the commits reachable, and recording the head again changes
    nothing. `full_status` returns no structured field for the cause.

    ASKED OF THE PLUGIN'S OWN VOCABULARY rather than a rule invented here:
    `full_status` already answers whole, provisional, unknown or not-declared
    from the ledger alone, and `merged_phase` already says which phases it is
    asked about. A second reading of either in this file would be the defect
    `read_bugs`'s docstring warns about - two answers to one question, with
    this file at risk of being the one that lies.

    TWO ANSWERS HOLD A RELEASE, NOT ONE. PROVISIONAL is a phase no measured
    full run yet contains. UNKNOWN is a phase whose ancestry cannot be asked at
    all - no `mergedHead`, or a head git could not answer about - and dropping
    it would let a release through over a phase the plan's own evidence cannot
    vouch for, which is this file's fail-loud rule broken one phase at a time.
    Both are returned, each with the answer that put it here, because they are
    settled differently: a full run settles the first, and no run can settle
    the second until its own cause is repaired - recording the missing
    `mergedHead`, or, when one is recorded, making both commits present so
    git can answer.

    UNREADABLE IS A REFUSAL, NEVER "NOTHING HELD". A manifest that will not
    parse, or a ledger carrying a file that could not be read or verified,
    means the caller cannot know whether any phase holds, so it says so
    rather than let a release through on a file nobody could read.

    No `meta.fullGate` at all means nothing is held and this returns
    `([], None)` - the guard then judges the bugs alone.
    """
    mio = _effective(project)
    if mio is None:
        return ([], "the plugin's own evidence rule could not be loaded from "
                    "plugins/audit/scripts, so a merged phase's full-run "
                    "answer cannot be decided here")
    modules = _evidence_modules(project)
    if modules is None:
        return ([], "the plugin's own evidence reader could not be loaded "
                    "from plugins/audit/scripts, so a merged phase's "
                    "full-run answer cannot be decided here")
    evidence_io, _worktrees, vocab = modules
    holding = {vocab.FULL_STATUS_PROVISIONAL: HELD_PROVISIONAL,
               vocab.FULL_STATUS_UNKNOWN: HELD_UNANSWERABLE}
    data, problem = _read_plan(mio, project)
    if problem:
        return ([], problem)
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    full_gate = meta.get("fullGate")
    if not full_gate:
        return ([], None)
    full_commands = [c for _name, c in
                     evidence_io.resolved_commands(data, full_gate)]
    ledger = evidence_io.read_rows(project)
    if ledger.get("unreadable"):
        return ([], "the evidence ledger carries file(s) that could not be "
                    "read or verified: %s"
                    % (", ".join(ledger.get("unreadableFiles") or []),))
    rows = ledger.get("rows") or []
    phases = data.get("phases")
    phases = phases if isinstance(phases, list) else []
    out = []
    for phase in phases:
        if not evidence_io.merged_phase(phase):
            continue
        status = evidence_io.full_status(rows, phase, project, full_commands)
        kind = holding.get(status.get("answer"))
        if kind:
            out.append((phase.get("id"), kind, status.get("basis") or "",
                        bool(phase.get("mergedHead"))))
    return (out, None)


def bypass_armed(project, session_id, now=None):
    """True iff the maintainer armed a bypass that has not expired.

    Read here and CONSUMED nowhere: PreToolUse may run more than once for one
    intention, and a slot deleted on the first read would refuse the second half
    of `git tag … && git push …`. It expires on its own TTL instead, which is
    what makes it single-use in the sense that matters - it cannot authorise a
    later release.
    """
    now = time.time() if now is None else now
    path = os.path.join(project, STATE_REL,
                        "release-bypass-%s.json" % (session_id or "none",))
    try:
        with open(path, "r", encoding="utf-8") as fh:
            slot = json.load(fh)
    except Exception:
        return False
    armed = slot.get("armedAtEpoch")
    ttl = slot.get("ttlSeconds")
    if not isinstance(armed, (int, float)) or not isinstance(ttl, (int, float)):
        return False
    return (now - armed) <= ttl


def _phase_parts(picked, label, with_basis=True):
    """The sentence naming the phases in `picked` - the first
    `REFUSAL_PHASE_CAP` of them, the rest summarised - or None when there is
    none. `with_basis` False renders ids alone, for a bucket whose label
    already states the whole basis (`full_status`'s would only repeat the id
    the entry starts with)."""
    if not picked:
        return None
    shown = picked[:REFUSAL_PHASE_CAP]
    listed = "; ".join(("%s (%s)" % (h[0], h[2][:BASIS_CAP])) if with_basis
                       else str(h[0]) for h in shown)
    rest = len(picked) - len(shown)
    if rest:
        listed += "; and %d more - `/audit:status` lists them" % (rest,)
    return "%d merged phase(s) %s: %s" % (len(picked), label, listed)


def refusal(why, bugs, bug_problem, held, phase_problem):
    """The sentence a refused release reads, naming what to do about each
    thing that holds it.

    EACH LIST ON ITS OWN, because each is read on its own and settled a
    different way. A list that could not be read is named UNKNOWN with the
    reason; a list that was read is named by what it holds, even when that is
    nothing - so an unreadable bug list never hides a phase that really does
    hold the release, and the reverse. The sentence about refusing rather
    than guessing is said only when a list really could not be read: said on
    every refusal it would stop telling a reader anything."""
    parts = []
    if bug_problem:
        parts.append("whether the plan carries an open bug is UNKNOWN: %s"
                     % (bug_problem,))
    elif bugs:
        listed = "; ".join("%s (%s) %s" % (b[0], b[1], b[2][:70]) for b in bugs)
        parts.append("%d bug(s) are open in the plan: %s - close them"
                     % (len(bugs), listed))
    else:
        parts.append("the plan carries no open bug")
    if phase_problem:
        parts.append("whether the full run has settled each merged phase is "
                     "UNKNOWN: %s" % (phase_problem,))
    else:
        provisional = _phase_parts(
            [h for h in held if h[1] == HELD_PROVISIONAL],
            "are provisional - no measured full run yet contains what they "
            "merged into")
        if provisional:
            provisional += (" - record the full run that settles each "
                            "(/audit:review <phase> --full, or the "
                            "pre-push/CI step)")
        unanswerable = [h for h in held if h[1] == HELD_UNANSWERABLE]
        unrecorded = _phase_parts(
            [h for h in unanswerable if not h[3]],
            "are unanswerable - no mergedHead is recorded, so the evidence "
            "cannot say whether any full run contains what they merged into",
            with_basis=False)
        if unrecorded:
            unrecorded += (
                " - record the mergedHead each lacks by re-running "
                "`python3 %s %s <phase> --project <dir>`; a phase that "
                "re-run refuses to backfill (a squash merge, whose task "
                "commits the parent does not contain) stays unanswerable, "
                "and only the keyword releases over it"
                % (shell_path(CLOSE_PHASE_REL), shell_path(MANIFEST_REL)))
        unreachable = _phase_parts(
            [h for h in unanswerable if h[3]],
            "are unanswerable - a mergedHead is recorded, but git could not "
            "answer whether a full run's head contains it (see the basis)")
        if unreachable:
            # Every cause of this bucket - an unreachable commit, a shallow
            # clone, git missing or timing out - is named by the basis, and
            # the remedy below covers each without reading that prose. A run
            # row carrying no head never lands here: the evidence rule skips
            # it, so an older full run that contains the merge still makes
            # the phase whole, and otherwise the phase is refused as
            # provisional, with the full-run remedy.
            unreachable += (
                " - make both commits present here (git fetch, or unshallow "
                "the clone); recording the mergedHead again changes nothing, "
                "and until git can answer only the keyword releases over it")
        found = [p for p in (provisional, unrecorded, unreachable) if p]
        parts.extend(found or ["no merged phase is provisional or "
                               "unanswerable"])
    unread = ""
    if bug_problem or phase_problem:
        unread = (" A pushed tag is never moved here, so a list that could "
                  "not be read refuses rather than guessing - repair it.")
    return ("this command %s, and %s.%s Or type %s in your own message to "
            "release over all of it. The keyword only counts from you, which "
            "is why it is read off the prompt and not off this command."
            % (why, "; and ".join(parts), unread, KEYWORD))


def decide(command, project, session_id, now=None, payload=None):
    """`reason` when the call must be denied, else None. The whole rule, in one
    pure-ish function so its cases need no hook payload.

    `payload` is OPTIONAL and used for exactly one thing: resolving which
    tree each publishing invocation answers to. A case passing no `payload`
    reads `project` as the tree directly. One clean publisher does not
    answer for a later one.
    """
    publishers = _publishers(command)
    if not publishers:
        return None
    trees = _release_trees(payload, project, command, publishers)
    if any(tree is None for _why, tree in trees):
        return ("Release target is UNKNOWN: the command's directory change "
                "cannot be read, so this guard cannot establish which plan "
                "the publishing command answers to. Use a literal directory "
                "and retry.")
    for why, tree in trees:
        bugs, bug_problem = read_bugs(tree)
        held, phase_problem = read_held_phases(tree)
        if not (bugs or bug_problem or held or phase_problem):
            continue
        if bypass_armed(project, session_id, now):
            return None
        return refusal(why, bugs, bug_problem, held, phase_problem)
    return None


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        # Nothing to judge. This is the one fail-open branch: a payload this hook
        # cannot parse is not evidence about a release.
        return 0
    tool = payload.get("tool_name") or payload.get("toolName") or ""
    if tool != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command", "")
    reason = decide(command, project_dir(),
                    str(payload.get("session_id") or ""),
                    payload=payload)
    if reason:
        sys.stdout.write(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "[guard-release] " + reason}}))
    return 0


def _selftest():
    import shutil
    import tempfile
    cases, failed = [], []

    def check(label, cond, detail=""):
        cases.append(label)
        if not cond:
            failed.append("%s (%s)" % (label, detail))
        print(("PASS " if cond else "FAIL ") + label)

    # --- what counts as publishing -------------------------------------------
    check("gr1 creating an annotated tag is publishing",
          publishing('git tag -a v2.0.2 -m "notes"'))
    check("gr2 pushing a tag by name is publishing",
          publishing("git push origin v2.0.2"))
    check("gr3 --tags is publishing", publishing("git push --tags"))
    check("gr4 a GitHub Release is publishing",
          publishing("gh release create v2.0.2 --verify-tag"))
    check("gr5 a release typed as ONE line is caught in its second half - this "
          "is how a release is actually typed, and a guard reading only the "
          "head of the line would wave it through",
          publishing('git tag -a v1 -m x && git push origin v1'))
    # THE SECOND DIRECTION, and the cases that keep this guard from being routed
    # around: ordinary work must not trip it. A guard that fires on a read gets
    # disabled, which is the class `guard-false-positive-class` records.
    check("gr6 pushing a BRANCH is not publishing - pushing code is not "
          "releasing it", not publishing("git push origin main"))
    check("gr7 setting upstream on a branch is not publishing",
          not publishing("git push -u origin audit/some-branch"))
    check("gr8 LISTING or DELETING tags is not publishing",
          not publishing("git tag -l") and not publishing("git tag -d v1"))
    check("gr8b a bare `git tag`, `--contains` and `--points-at` list, "
          "they do not publish",
          publishing("git tag") is None
          and publishing("git tag --contains HEAD") is None
          and publishing("git tag --points-at HEAD") is None)
    check("gr8c a quoted `-C` path that contains a space is still a tag "
          "creation",
          publishing('git -C "my folder" tag -a v1 -m x'))
    check("gr8d a tag push with `-C` is publishing - the verb is `push`, "
          "not the option in front of it",
          publishing("git -C /tmp/wt push origin v1.2.3")
          and publishing('git -C "my folder" push --tags'))
    check("gr8e a list flag in a LATER command does not un-publish a tag "
          "creation",
          publishing('git tag -a v1 -m x && echo -l'))
    check("gr8f a list flag inside a quoted message does not un-publish",
          publishing('git tag -a v1 -m "notes -l"'))
    check("gr8g --sort, --format, --column and --no-column with a tag "
          "name create a tag; without a name they list",
          publishing("git tag --sort=v:refname v1")
          and publishing("git tag --format='%(refname)' v1")
          and publishing("git tag --column v1")
          and publishing("git tag --no-column v1")
          and publishing("git tag --sort=v:refname") is None
          and publishing("git tag --format='%(refname)'") is None
          and publishing("git tag --column") is None
          and publishing("git tag --no-column") is None)
    check("gr8h a list pattern whose quotes contain a separator is not "
          "a tag creation, while a name containing one still is",
          publishing("git tag -l 'v1;x'") is None
          and publishing('git tag -l "v1&x"') is None
          and publishing("git tag -l 'v1|x'") is None
          and publishing("git tag -a 'v1;x' -m m"))
    # How grading GROWS with the run of quoted -C operands, not how long it
    # takes: an absolute bound measures the machine. The two sizes are timed
    # interleaved and the fastest sample of each kept, so a slow runner or a
    # scheduler stall inflates both sides or neither.
    def _grading_time(operands):
        command = "git" + (' -C "a"' * operands) + " status"
        start = time.perf_counter()
        publishing(command)
        return time.perf_counter() - start

    _short, _long = [], []
    for _ in range(30):
        _short.append(_grading_time(4))
        _long.append(_grading_time(16))
    _base, _grown = min(_short), min(_long)
    _ratio = _grown / _base if _base > 0 else None
    # What a bound of six guarantees at four times the operands: red against
    # the backtracking regex, which grows by orders of magnitude here; red
    # against a quadratic only when its per-operand cost is comparable to the
    # call's fixed cost - a cheaper quadratic can stay under it.
    check("gr60 a long run of quoted -C operands that do not publish is "
          "graded without backtracking, measured as a ratio so the "
          "machine's speed cancels out",
          _ratio is not None and _ratio < 6,
          "fastest at 4 operands %r s, at 16 %r s, ratio %s"
          % (_base, _grown,
             "unmeasurable: the timer did not resolve the short run"
             if _ratio is None else "%.2f" % (_ratio,)))
    check("gr9 reading releases is not publishing",
          not publishing("gh release view v2.0.1")
          and not publishing("gh release list"))
    check("gr10 the words inside a commit message do not trip it",
          not publishing('git commit -m "prepare gh release create notes"'))
    quoted_publishers = (
        "echo '; git tag -a v1 -m x'",
        'echo "; git tag -a v1 -m x"',
        "cat > note.txt <<'EOF'\necho '; git tag -a v1 -m x'\nEOF",
        'python3 - <<\'PY\'\nprint("; git tag -a v1 -m x")\nPY',
    )
    check("gr63 RED-FIRST: a publisher-looking phrase in single quotes, "
          "double quotes, file data or Python source is not a publisher: %r"
          % ([_publishers(command) for command in quoted_publishers],),
          all(not _publishers(command) for command in quoted_publishers))
    check("gr63b ALLOW-TWIN: a tag after a live separator remains a publisher",
          publishing("echo ready; git tag -a v1 -m x")
          == "creates a git tag")

    # --- the rule, end to end -------------------------------------------------
    tmp = tempfile.mkdtemp(prefix="guard-release-")
    try:
        os.makedirs(os.path.join(tmp, "docs", "audit"))
        os.makedirs(os.path.join(tmp, STATE_REL))
        mpath = os.path.join(tmp, MANIFEST_REL)

        def write_bugs(bugs, phases=None):
            with open(mpath, "w", encoding="utf-8") as fh:
                json.dump({"meta": {"version": 2}, "phases": phases or [],
                           "bugs": bugs}, fh)

        # THE DEFECT THIS FILE SHIPPED IN ITS FIRST DRAFT, as a case: a bug whose
        # fix task is `done` reads FIXED even though its stored status still says
        # open, because the orchestrator does not write `bugs[]` during a run.
        # Reading the raw field reported five open bugs where `/audit:status`
        # reported one, and this is the fixture that tells the two apart.
        write_bugs([{"id": "BUG-9", "status": "open", "severity": "med",
                     "title": "materialized and finished", "taskId": "P1.1"}],
                   phases=[{"id": "P1", "title": "p", "status": "done",
                            "tasks": [{"id": "P1.1", "title": "t",
                                       "status": "done", "bugId": "BUG-9"}]}])
        check("gr10b a bug whose fix task is done is CLOSED, on the plugin's own "
              "rule rather than on this file's reading of a stored field",
              decide("git push origin v2.0.2", tmp, "s1") is None)

        write_bugs([{"id": "BUG-2", "status": "open", "severity": "med",
                     "title": "a real one"}])
        got = decide("git push origin v2.0.2", tmp, "s1")
        check("gr11 a release with an open bug is REFUSED, and the refusal names "
              "the bug and the way past it: %r" % (got,),
              got and "BUG-2" in got and KEYWORD in got)
        check("gr11b ...and a plan that WAS read does not claim the guard is "
              "refusing rather than guessing - there was nothing to guess, "
              "and a sentence on every refusal stops meaning anything: %r"
              % (got,),
              bool(got) and "guessing" not in got)
        # THE SECOND-DIRECTION CASE, and the one that looks vacuous: with the plan
        # clean, the same command must go through untouched. A guard that refused
        # unconditionally would pass gr11 and fail here, and it would be the last
        # release this repository ever cut.
        write_bugs([{"id": "BUG-1", "status": "fixed", "severity": "high",
                     "title": "closed"}])
        check("gr12 ...and with every bug closed the same command is allowed",
              decide("git push origin v2.0.2", tmp, "s1") is None)
        write_bugs([{"id": "BUG-2", "status": "open", "severity": "med",
                     "title": "a real one"}])
        check("gr13 ordinary work is allowed even with bugs open - only the "
              "publishing commands are judged",
              decide("git push origin main", tmp, "s1") is None)

        # --- the vocabulary this file RESTATES, driven against its owner -------
        # A hook may not import the plugin, so `CLOSED` above is a copy - and a
        # copy nothing compares is a copy that goes stale silently. The failure
        # is one-directional and expensive: the plugin learns a word that closes
        # a bug, this file does not, and every release afterwards is held by a
        # bug the tracker considers settled. So the source is READ rather than
        # imported, and a file that cannot be read is a FAILURE here rather than
        # a case that quietly passes.
        import ast

        # `<repo>/.claude/hooks/<this file>` - three levels, resolved off
        # `__file__` rather than off the cwd, because the selftest sweep runs
        # every child in a scratch directory it must leave alone.
        repo = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))

        def literal(rel, name):
            """The value assigned to `name` at the top level of `rel`, or None."""
            try:
                with open(os.path.join(repo, rel), "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read())
            except Exception:
                return None
            for node in tree.body:
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == name:
                        try:
                            return ast.literal_eval(node.value)
                        except Exception:
                            return None
            return None

        vocab = literal(os.path.join("plugins", "audit", "scripts", "manifest",
                                     "_manifest_vocab.py"), "BUG_STATUS")
        human = literal(os.path.join("plugins", "audit", "scripts", "manifest",
                                     "_manifest_io.py"), "HUMAN_BUG_VERDICT")
        check("gr13b the plugin's own bug vocabulary was READ, so the two cases "
              "below are comparisons rather than two Nones agreeing: %r / %r"
              % (vocab, human),
              bool(vocab) and bool(human))
        check("gr13c every word this file treats as closed is a word the plugin "
              "defines - a status invented here would silently stop holding "
              "releases for a bug nothing can be in: %r"
              % (sorted(set(CLOSED) - set(vocab or ())),),
              bool(vocab) and set(CLOSED) <= set(vocab))
        check("gr13d ...and the set is EXACTLY the plugin's own: `fixed`, which "
              "its derivation produces, plus every human verdict it names. An "
              "inclusion alone would pass on a copy that had missed a word, "
              "which is the direction that costs a release: %r vs %r"
              % (sorted(CLOSED), sorted({"fixed"} | set(human or ()))),
              bool(human) and set(CLOSED) == ({"fixed"} | set(human)))
        # AND THE OTHER DIRECTION, so the tuple cannot be widened until it closes
        # everything: at least one word of the vocabulary must still hold a
        # release, or this guard has been turned off by a rewrite of one line.
        check("gr13e SECOND-DIRECTION CASE: some bug status is still OPEN as far "
              "as this guard is concerned - a `CLOSED` widened to the whole "
              "vocabulary would pass every case above and refuse nothing ever "
              "again: %r" % (sorted(set(vocab or ()) - set(CLOSED)),),
              bool(vocab) and bool(set(vocab) - set(CLOSED)))
        # ...and driven end to end on the word that was added, rather than
        # asserted about the tuple alone: a set comparison cannot see a `decide`
        # that reads a different constant.
        write_bugs([{"id": "BUG-7", "status": "not_a_bug", "severity": "high",
                     "title": "investigated; the behaviour is correct"}])
        check("gr13f a bug closed as a verified negative does not hold a "
              "release, driven through `decide` rather than inferred from the "
              "tuple",
              decide("git push origin v2.0.2", tmp, "s1") is None)
        write_bugs([{"id": "BUG-2", "status": "open", "severity": "med",
                     "title": "a real one"}])

        # --- the bypass, both directions -------------------------------------
        slot = os.path.join(tmp, STATE_REL, "release-bypass-s1.json")
        with open(slot, "w", encoding="utf-8") as fh:
            json.dump({"armedAtEpoch": time.time(), "ttlSeconds": 3600}, fh)
        check("gr14 an armed bypass lets the release through",
              decide("git push origin v2.0.2", tmp, "s1") is None)
        check("gr15 ...and it is scoped to the SESSION that armed it - another "
              "session's release is still refused",
              decide("git push origin v2.0.2", tmp, "s2") is not None)
        # An acknowledgement that never expires is an acknowledgement about some
        # other release. Driven by passing the clock rather than by sleeping.
        check("gr16 an EXPIRED bypass does not authorise anything",
              decide("git push origin v2.0.2", tmp, "s1",
                     now=time.time() + 7200) is not None)
        with open(slot, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        check("gr17 an unreadable slot is not an armed one",
              decide("git push origin v2.0.2", tmp, "s1") is not None)
        os.remove(slot)

        # --- fail LOUD, which is this hook's inversion of the house rule ------
        with open(mpath, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        got = decide("git push origin v2.0.2", tmp, "s1")
        check("gr18 a manifest that cannot be READ refuses the release and says "
              "so - a pushed tag cannot be taken back, so this is the one guard "
              "here that must not fail open - and it says so of BOTH lists, "
              "since neither was read; a loader answering `{}` for the file "
              "would report the phase list as holding nothing: %r" % (got,),
              bool(got) and "open bug is UNKNOWN" in got
              and "merged phase is UNKNOWN" in got and "guessing" in got)
        os.remove(mpath)
        check("gr19 ...and a MISSING manifest refuses on the same grounds",
              decide("git push origin v2.0.2", tmp, "s1") is not None)
        check("gr20 but an unreadable manifest still does not block ordinary "
              "work - the failure is scoped to what it protects",
              decide("git push origin main", tmp, "s1") is None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # THE REAL PLAN, and it is the only fixture that could have caught the second
    # defect: this repository's manifest is SHARDED, so a raw `json.load` sees
    # phases that are stubs with no tasks and every materialized bug reads open.
    # A hand-built single-file fixture agrees with both readings and proves
    # nothing, which is why this case asks the plugin the same question and
    # demands the two answers match.
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(os.path.dirname(here))
    if os.path.isfile(os.path.join(repo, MANIFEST_REL)):
        mine = read_bugs(repo)[0]
        mio = _effective(repo)
        theirs = None
        try:
            data = mio.load_manifest_safe(os.path.join(repo, MANIFEST_REL))
            by_id = mio.tasks_by_id(data)
            theirs = [b.get("id") for b in (data.get("bugs") or [])
                      if str(mio.effective_bug_status(b, by_id)).lower()
                      not in CLOSED]
        except Exception as exc:
            theirs = "could not ask: %s" % (exc,)
        check("gr21 over the REAL sharded plan this guard counts exactly what "
              "the plugin's own rule counts - mine=%r theirs=%r"
              % ([b[0] for b in mine], theirs),
              [b[0] for b in mine] == theirs)

    # --- provisional phases hold a release too, asked of the plugin's own
    # `full_status` rather than a second rule invented here. A FRESH fixture,
    # never this repository's real plan: that plan may carry an open bug on
    # any given day, so only a fixture plan can isolate "no open bug, one provisional phase".
    tmp2 = tempfile.mkdtemp(prefix="guard-release-full-")
    try:
        os.makedirs(os.path.join(tmp2, "docs", "audit"))
        os.makedirs(os.path.join(tmp2, STATE_REL))
        mpath2 = os.path.join(tmp2, MANIFEST_REL)

        def write_plan(meta_extra, phases, bugs=None):
            meta = {"version": 2}
            meta.update(meta_extra or {})
            with open(mpath2, "w", encoding="utf-8") as fh:
                json.dump({"meta": meta, "phases": phases or [],
                           "bugs": bugs or []}, fh)

        modules = _evidence_modules(tmp2)
        check("gr22 the evidence and ancestry modules load from this "
              "repository's own scripts/ - what read_held_phases needs to "
              "ask full_status anything at all",
              modules is not None)

        # RED-FIRST: a merged phase with a declared fullGate and NO recorded
        # full run at all reads PROVISIONAL (full_status's own "no full-scope
        # run has ever been recorded" answer) - and that alone must hold a
        # release exactly like an open bug does.
        write_plan({"fullGate": ["full"],
                   "buildCommands": {"full": "echo full"}},
                  [{"id": "P1", "title": "p", "status": "done",
                    "mergedAt": "2026-01-01T00:00:00Z",
                    "mergedHead": "a" * 40, "tasks": []}])
        provisional, problem = read_held_phases(tmp2)
        check("gr23 RED-FIRST: a merged phase this ledger has never recorded "
              "a full run for reads PROVISIONAL, with no problem to report: "
              "%r / %r" % (provisional, problem),
              problem is None and [p[0] for p in provisional] == ["P1"])
        got = decide("git tag -a v1 -m x", tmp2, "s1")
        check("gr24 RED-FIRST: no open bug and one provisional phase "
              "still REFUSES `git tag v1` - the mutation this guards is "
              "`decide` reading only the bugs: %r" % (got,),
              got and "P1" in got and "provisional" in got)

        # ALLOW: the SAME plan with no meta.fullGate at all has
        # nothing provisional to ask about, and behaves exactly as it did
        # before this function existed.
        write_plan({}, [{"id": "P1", "title": "p", "status": "done",
                        "mergedAt": "2026-01-01T00:00:00Z",
                        "mergedHead": "a" * 40, "tasks": []}])
        check("gr25 ALLOW: no meta.fullGate at all means nothing is "
              "provisional, and the release goes through",
              decide("git tag -a v1 -m x", tmp2, "s1") is None)

        # ALLOW: ordinary work is never refused by a provisional
        # phase either - only the publishing commands are judged.
        write_plan({"fullGate": ["full"],
                   "buildCommands": {"full": "echo full"}},
                  [{"id": "P1", "title": "p", "status": "done",
                    "mergedAt": "2026-01-01T00:00:00Z",
                    "mergedHead": "a" * 40, "tasks": []}])
        check("gr26 ALLOW: `git push origin main` is not refused by a "
              "provisional phase - it is not a publishing command",
              decide("git push origin main", tmp2, "s1") is None)

        # WHICH PHASES ARE ASKED is the plugin's shared `merged_phase`, not a
        # second reading of `mergedAt` spelled here: a phase carrying a merge
        # stamp but no id has no name a verdict could be printed under, so
        # no surface grades it. Read as provisional (no full run recorded),
        # a local `mergedAt` check would hold this release over a phase
        # named "?" - the value that tells the two readings apart.
        write_plan({"fullGate": ["full"],
                   "buildCommands": {"full": "echo full"}},
                  [{"title": "id-less", "status": "done",
                    "mergedAt": "2026-01-01T00:00:00Z",
                    "mergedHead": "a" * 40, "tasks": []}])
        got = decide("git tag -a v1 -m x", tmp2, "s1")
        check("gr35 RED-FIRST: a phase with a merge stamp and NO id is not "
              "asked about, on the plugin's shared `merged_phase` rather "
              "than a local `mergedAt` check - the release goes through: %r"
              % (got,),
              got is None)

        # RED-FIRST: an unreadable ledger is a PROBLEM, never "nothing
        # provisional" - fail-loud extended to this second list.
        edir = os.path.join(tmp2, "docs", "audit", "evidence")
        os.makedirs(edir, exist_ok=True)
        with open(os.path.join(edir, "2026-01.broken.jsonl"), "w",
                  encoding="utf-8") as fh:
            fh.write('{"not": "chained"}\n{also not valid json\n')
        provisional, problem = read_held_phases(tmp2)
        check("gr27 RED-FIRST: a ledger carrying a torn line is a PROBLEM, "
              "not an empty provisional list: %r / %r"
              % (provisional, problem),
              provisional == [] and bool(problem))
        got = decide("git tag -a v1 -m x", tmp2, "s1")
        check("gr28 ...and `decide` refuses over that problem, naming it "
              "UNKNOWN exactly like an unreadable manifest does: %r" % (got,),
              got and "UNKNOWN" in got)
        os.remove(os.path.join(edir, "2026-01.broken.jsonl"))

        # ALLOW: the same phase made WHOLE by a real recorded full run whose
        # head really does contain mergedHead - a REAL repo, never two
        # strings compared for equality, for the reason `test__evidence_io`'s
        # own fixture states: a mutation comparing `head == mergedHead` would
        # still pass against two equal fixture strings.
        evidence_io = modules[0]
        git = ["git", "-c", "user.email=t@t.t", "-c", "user.name=t",
              "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"]

        def sh(*args):
            subprocess.run(git + list(args), cwd=tmp2, check=True,
                          capture_output=True, timeout=30)

        def rev():
            out = subprocess.run(git + ["rev-parse", "HEAD"], cwd=tmp2,
                                 check=True, capture_output=True, timeout=30)
            return out.stdout.decode("utf-8").strip()

        sh("init", "-q")
        with open(os.path.join(tmp2, "a.txt"), "w", encoding="utf-8") as fh:
            fh.write("1\n")
        sh("add", "-A")
        sh("commit", "-qm", "one")
        merged_head = rev()
        with open(os.path.join(tmp2, "a.txt"), "w", encoding="utf-8") as fh:
            fh.write("2\n")
        sh("add", "-A")
        sh("commit", "-qm", "two")
        full_head = rev()

        write_plan({"fullGate": ["full"], "nodePreamble": "export X=1",
                   "buildCommands": {"full": "echo full"}},
                  [{"id": "P1", "title": "p", "status": "done",
                    "mergedAt": "2026-01-01T00:00:00Z",
                    "mergedHead": merged_head, "tasks": []}])
        with open(mpath2, "r", encoding="utf-8") as fh:
            plan = json.load(fh)
        full_commands = [c for _n, c in
                        evidence_io.resolved_commands(plan, ["full"])]
        row = {
            "v": evidence_io.ROW_VERSION, "runId": "run-whole",
            "ts": "2026-01-02T00:00:00Z", "scope": evidence_io.FULL_SCOPE,
            "status": "passed",
            "steps": [{"name": "gate", "command": c, "exit": 0,
                      "durationMs": 1000} for c in full_commands],
            "testedState": {"head": full_head},
            "observations": {"ranTotal": 1, "countsBasis": "1 check",
                             "dirtyOutside": []},
        }
        evidence_io.append_row(tmp2, row, writer="selftest")
        provisional, problem = read_held_phases(tmp2)
        check("gr29 ALLOW: a real recorded full run whose head really "
              "contains mergedHead reads WHOLE, not provisional: %r / %r"
              % (provisional, problem),
              problem is None and provisional == [])
        check("gr30 ALLOW: ...and the release goes through",
              decide("git tag -a v1 -m x", tmp2, "s1") is None)

        # THE MUTATION THIS PROVES AGAINST, DRIVEN RATHER THAN ASSERTED: the
        # SAME row read against the bare `meta.fullGate` entries - no
        # `resolved_commands`, no preamble - does not match this run's
        # published commands, so a `read_held_phases` that skipped the
        # resolution would disqualify a run that really did measure the
        # declared gate and hold this release open forever.
        bare = evidence_io.full_status(
            evidence_io.read_rows(tmp2).get("rows") or [],
            {"id": "P1", "mergedHead": merged_head}, tmp2, ["full"])
        vocab = modules[2]
        check("gr31 the bare fullGate entry (no preamble, no buildCommands "
              "resolution) does NOT read WHOLE against this run's published "
              "commands - the shape a preamble-skipping mutation would "
              "break: %r" % (bare,),
              bare["answer"] != vocab.FULL_STATUS_WHOLE)

        # --- a merged phase the evidence cannot ANSWER for holds a release
        # too. `full_status` reads UNKNOWN when ancestry cannot be asked at
        # all (no mergedHead) - and a guard that dropped that answer would
        # let a release through over a phase nobody can vouch for, which is
        # the fail-open this file exists to refuse. P1 stays WHOLE beside it,
        # so the refusal is owed to the unanswerable phase alone.
        unanswerable = [{"id": "P1", "title": "p", "status": "done",
                         "mergedAt": "2026-01-01T00:00:00Z",
                         "mergedHead": merged_head, "tasks": []},
                        {"id": "P2", "title": "q", "status": "done",
                         "mergedAt": "2026-01-03T00:00:00Z", "tasks": []}]
        write_plan({"fullGate": ["full"], "nodePreamble": "export X=1",
                   "buildCommands": {"full": "echo full"}}, unanswerable)
        got = decide("git tag -a v1 -m x", tmp2, "s1")
        check("gr36 RED-FIRST: a merged phase with no mergedHead (full_status "
              "UNKNOWN) REFUSES `git tag v1`, naming the phase and the basis "
              "- the missing mergedHead, stated once by the bucket rather "
              "than repeated per entry: %r" % (got,),
              bool(got) and "P2" in got and "no mergedHead is recorded" in got
              and "P1" not in got)
        check("gr36b ...and it names the command that records a mergedHead "
              "after the fact, as the provisional remedy names its own, and "
              "what happens when that backfill refuses: %r" % (got,),
              bool(got) and "plugins/audit/scripts/git/close-phase.py "
              "docs/audit/audit-plan.json <phase> --project <dir>" in got
              and "squash" in got)
        # THE OTHER CAUSE OF UNKNOWN: a mergedHead IS recorded, but git cannot
        # establish whether a run's head contains it (an unreachable commit, a
        # shallow clone). Re-running close-phase does nothing for it - a head
        # is already recorded - so naming that command here would send the
        # reader to a remedy that cannot work.
        write_plan({"fullGate": ["full"], "nodePreamble": "export X=1",
                   "buildCommands": {"full": "echo full"}},
                  [unanswerable[0],
                   {"id": "P3", "title": "r", "status": "done",
                    "mergedAt": "2026-01-03T00:00:00Z",
                    "mergedHead": "c" * 40, "tasks": []}])
        got = decide("git tag -a v1 -m x", tmp2, "s1")
        check("gr36c RED-FIRST: a phase whose recorded mergedHead git cannot "
              "resolve is refused and named, and its remedy is making the "
              "heads reachable - never the close-phase re-run, which cannot "
              "help a phase that already records a head, and never a run "
              "that carries its head, a cause this answer no longer has: %r"
              % (got,),
              bool(got) and "P3" in got and "close-phase.py" not in got
              and "unshallow" in got and "carries its head" not in got)

        # A PLAN WITH MANY LEGACY MERGES, none recording a mergedHead. The
        # fixture is sized to exceed the refusal's cut, so the tail must be
        # summarised, and each entry's basis must not repeat the phase id
        # the entry already starts with.
        many = [{"id": "Q%02d" % (i,), "title": "m", "status": "done",
                 "mergedAt": "2026-01-03T00:00:00Z", "tasks": []}
                for i in range(1, 13)]
        write_plan({"fullGate": ["full"], "nodePreamble": "export X=1",
                   "buildCommands": {"full": "echo full"}}, many)
        got = decide("git tag -a v1 -m x", tmp2, "s1")
        check("gr46 RED-FIRST: a refusal over more held phases than it lists "
              "names the first ones and summarises the rest, pointing at "
              "/audit:status for the whole list: %r" % (got,),
              bool(got) and "Q01" in got and "Q12" not in got
              and "more - `/audit:status` lists them" in got)
        check("gr47 ...and an entry with no mergedHead is not followed by a "
              "basis that repeats its own id: %r" % (got,),
              bool(got) and "phase Q01 records" not in got)
        write_plan({"fullGate": ["full"], "nodePreamble": "export X=1",
                   "buildCommands": {"full": "echo full"}}, unanswerable)
        check("gr37 ...and that refusal does not call either LIST unknown - "
              "both were read; one phase in one of them has no answer: %r"
              % (got,),
              bool(got) and "UNKNOWN" not in got)
        check("gr38 ALLOW: `git push origin main` is untouched by an "
              "unanswerable phase - it is not a publishing command",
              decide("git push origin main", tmp2, "s1") is None)
        slot2 = os.path.join(tmp2, STATE_REL, "release-bypass-s1.json")
        with open(slot2, "w", encoding="utf-8") as fh:
            json.dump({"armedAtEpoch": time.time(), "ttlSeconds": 3600}, fh)
        check("gr39 the maintainer's armed bypass covers an unanswerable "
              "phase exactly as it covers an open bug...",
              decide("git tag -a v1 -m x", tmp2, "s1") is None)
        check("gr40 ...and only for the session that armed it",
              decide("git tag -a v1 -m x", tmp2, "s2") is not None)
        os.remove(slot2)

        # EACH LIST IS REPORTED ON ITS OWN. A plan with no `bugs` list cannot
        # answer the bug question while the phase question reads fine, and
        # the refusal must say exactly that - calling both unknown hides the
        # phase that really does hold the release.
        with open(mpath2, "r", encoding="utf-8") as fh:
            plan = json.load(fh)
        del plan["bugs"]
        with open(mpath2, "w", encoding="utf-8") as fh:
            json.dump(plan, fh)
        got = decide("git tag -a v1 -m x", tmp2, "s1")
        check("gr41 RED-FIRST: the bug list unreadable, the phase list "
              "readable - the refusal names the bug list UNKNOWN, names P2 "
              "with its basis, and does not call the phase list unknown: %r"
              % (got,),
              bool(got) and "open bug is UNKNOWN" in got and "P2" in got
              and "no mergedHead is recorded" in got
              and "merged phase is UNKNOWN" not in got)
        # ...and the mirror: the bugs readable with one open, the ledger torn.
        write_plan({"fullGate": ["full"], "nodePreamble": "export X=1",
                   "buildCommands": {"full": "echo full"}}, unanswerable,
                  bugs=[{"id": "BUG-2", "status": "open", "severity": "med",
                         "title": "a real one"}])
        torn = os.path.join(edir, "2026-01.torn.jsonl")
        with open(torn, "w", encoding="utf-8") as fh:
            fh.write('{"not": "chained"}\n{also not valid json\n')
        got = decide("git tag -a v1 -m x", tmp2, "s1")
        check("gr42 RED-FIRST: the bug list readable, the ledger torn - the "
              "refusal names BUG-2, names the phase list UNKNOWN, and does "
              "not call the bug list unknown: %r" % (got,),
              bool(got) and "BUG-2" in got and "merged phase is UNKNOWN" in got
              and "open bug is UNKNOWN" not in got)
        os.remove(torn)

        # --- the tree a release is judged against comes from
        # `_config.tree_for`, never `CLAUDE_PROJECT_DIR` read a second time --
        check("gr32 resolved_tree with NO payload leaves the tree exactly as "
              "`project` - the reading every call above this point made, "
              "unconditionally",
              resolved_tree(None, tmp2) == tmp2)
        payload_here = {"cwd": tmp2,
                        "tool_input": {"command": "git tag -a v1 -m x"}}
        check("gr33 resolved_tree asked about a command whose shell never "
              "leaves the session's own directory answers with that SAME "
              "directory - `tree_for` reached and agreeing, not a second "
              "tree invented for the ordinary call",
              resolved_tree(payload_here, tmp2) == tmp2)
        payload_unknown = {"cwd": tmp2, "tool_input": {
            "command": 'cd "$WT" && git tag -a v1 -m x'}}
        check("gr33a an unreadable `cd` is UNKNOWN, never the session "
              "directory: %r" % (resolved_tree(payload_unknown, tmp2),),
              resolved_tree(payload_unknown, tmp2) is None)
        got = decide('cd "$WT" && git tag -a v1 -m x', tmp2, "s1",
                     payload=payload_unknown)
        check("gr33b an UNKNOWN release target refuses before it reads a plan: "
              "%r" % (got,), bool(got) and "UNKNOWN" in got)
        wt = tempfile.mkdtemp(prefix="guard-release-wt-")
        shutil.rmtree(wt)
        subprocess.run(git + ["worktree", "add", "-b", "gr34-side", wt],
                      cwd=tmp2, check=True, capture_output=True, timeout=30)
        try:
            payload_elsewhere = {"cwd": tmp2, "tool_input": {
                "command": "cd %s && git tag -a v1 -m x" % (wt,)}}
            moved = resolved_tree(payload_elsewhere, tmp2)
            check("gr34 ...and a command that `cd`s into a LINKED WORKTREE "
                  "before tagging is judged against THAT worktree's own "
                  "plan, never `project`'s - a release typed there must "
                  "answer for what IT carries, not for wherever "
                  "CLAUDE_PROJECT_DIR happened to point: %r"
                  % (moved,),
                  moved is not None
                  and os.path.realpath(moved) == os.path.realpath(wt))
            payload_cdir = {"cwd": tmp2, "tool_input": {
                "command": "git -C %s tag -a v1 -m x" % (wt,)}}
            check("gr34c `git -C` into the linked worktree answers to its "
                  "plan too: %r" % (resolved_tree(payload_cdir, tmp2),),
                  os.path.realpath(resolved_tree(payload_cdir, tmp2))
                  == os.path.realpath(wt))
            payload_cdir_unknown = {"cwd": tmp2, "tool_input": {
                "command": 'git -C "$WT" tag -a v1 -m x'}}
            got = decide('git -C "$WT" tag -a v1 -m x', tmp2, "s1",
                        payload=payload_cdir_unknown)
            check("gr34d an unreadable `git -C` release target refuses UNKNOWN: "
                  "%r" % (got,),
                  resolved_tree(payload_cdir_unknown, tmp2) is None
                  and bool(got) and "UNKNOWN" in got)

            def write_tree_plan(path, bugs):
                os.makedirs(os.path.join(path, "docs", "audit"), exist_ok=True)
                with open(os.path.join(path, MANIFEST_REL), "w",
                          encoding="utf-8") as fh:
                    json.dump({"meta": {"version": 2}, "phases": [],
                               "bugs": bugs}, fh)

            qwt = "'" + wt.replace("'", "'\\''") + "'"
            write_tree_plan(tmp2, [])
            write_tree_plan(wt, [])
            clean_cd = "cd %s && git tag -a v1 -m x" % qwt
            payload_clean = {"cwd": tmp2,
                             "tool_input": {"command": clean_cd}}
            got = decide(clean_cd, tmp2, "s1", payload=payload_clean)
            check("gr53 ALLOW: a resolvable `cd` into a clean tree reaches "
                  "`decide` and is allowed - every other payload case "
                  "expects a refusal, so a guard that refuses every "
                  "directory change would still be green: %r" % (got,),
                  got is None)
            write_tree_plan(wt, [{"id": "BUG-WT", "status": "open",
                                  "severity": "med", "title": "worktree"}])
            later = "git status; git -C %s tag -a v1 -m x" % qwt
            got = decide(later, tmp2, "s1", payload={
                "cwd": tmp2, "tool_input": {"command": later}})
            check("gr51 a `-C` on a LATER git is the tree the tag answers "
                  "to, not the first `git` word: %r" % (got,),
                  bool(got) and "BUG-WT" in got and "directory change" not in got)
            earlier = "git -C %s status; git tag -a v1 -m x" % qwt
            got = decide(earlier, tmp2, "s1", payload={
                "cwd": tmp2, "tool_input": {"command": earlier}})
            check("gr51b the FIRST git's `-C` does not move a later tag "
                  "that names none - the mutation that follows any `-C`: %r"
                  % (got,),
                  got is None)
            pushed = "git status; git -C %s push origin v1.2.3" % qwt
            got = decide(pushed, tmp2, "s1", payload={
                "cwd": tmp2, "tool_input": {"command": pushed}})
            check("gr55 a tag push with `-C` on a later git answers to that "
                  "tree: %r" % (got,),
                  bool(got) and "BUG-WT" in got)
            second = "git tag -a v1 -m x && git -C %s tag -a v2 -m y" % qwt
            got = decide(second, tmp2, "s1", payload={
                "cwd": tmp2, "tool_input": {"command": second}})
            check("gr61 a second tag, in another tree, is judged too: %r"
                  % (got,),
                  bool(got) and "BUG-WT" in got)
            both_clean = "git tag -a v1 -m x && git tag -a v2 -m y"
            got = decide(both_clean, tmp2, "s1", payload={
                "cwd": tmp2, "tool_input": {"command": both_clean}})
            check("gr61b two tags in the clean session are allowed - the "
                  "mutation that refuses every compound command: %r" % (got,),
                  got is None)
            second_push = ("git tag -a v1 -m x && git -C %s push origin "
                           "v1.2.3" % qwt)
            got = decide(second_push, tmp2, "s1", payload={
                "cwd": tmp2, "tool_input": {"command": second_push}})
            check("gr61c a later tag push into another tree is judged too: "
                  "%r" % (got,),
                  bool(got) and "BUG-WT" in got)
            unread_second = ('git tag -a v1 -m x && git -C "$WT" tag -a '
                             'v2 -m y')
            got = decide(unread_second, tmp2, "s1", payload={
                "cwd": tmp2, "tool_input": {"command": unread_second}})
            check("gr61d an unreadable -C on a later publisher is UNKNOWN, "
                  "not the first publisher's clean tree: %r" % (got,),
                  bool(got) and "UNKNOWN" in got)
            chain = "git -C %s -C . tag -a v1 -m x" % qwt
            got = decide(chain, tmp2, "s1", payload={
                "cwd": tmp2, "tool_input": {"command": chain}})
            check("gr62 a relative -C resolves against the previous -C, "
                  "not the session: %r" % (got,),
                  bool(got) and "BUG-WT" in got)
            qtmp = "'" + tmp2.replace("'", "'\\''") + "'"
            replaced = "git -C %s -C %s tag -a v1 -m x" % (qwt, qtmp)
            got = decide(replaced, tmp2, "s1", payload={
                "cwd": tmp2, "tool_input": {"command": replaced}})
            check("gr62b an absolute later -C replaces the earlier one - "
                  "the mutation that always follows the first -C: %r"
                  % (got,),
                  got is None)
            spaced = wt + " space"
            subprocess.run(git + ["worktree", "add", "-b", "gr-space", spaced],
                          cwd=tmp2, check=True, capture_output=True, timeout=30)
            try:
                write_tree_plan(spaced, [{"id": "BUG-SP", "status": "open",
                                          "severity": "med", "title": "spaced"}])
                qsp = '"' + spaced + '"'
                spaced_cmd = "git -C %s tag -a v1 -m x" % qsp
                got = decide(spaced_cmd, tmp2, "s1", payload={
                    "cwd": tmp2, "tool_input": {"command": spaced_cmd}})
                check("gr54 a quoted `-C` path containing a space is followed "
                      "into that tree: %r" % (got,),
                      bool(got) and "BUG-SP" in got)
            finally:
                subprocess.run(git + ["worktree", "remove", "--force", spaced],
                              cwd=tmp2, check=True, capture_output=True,
                              timeout=30)
            note = "git tag -a v1 -m x # it's ready"
            payload_note = {"cwd": tmp2, "tool_input": {"command": note}}
            got = decide(note, tmp2, "s1", payload=payload_note)
            check("gr56 an apostrophe in a trailing comment is not a "
                  "directory change: %r" % (got,),
                  got is None)
            heredoc = "git tag -a v1 -F - <<EOF\nit's a note\nEOF"
            payload_doc = {"cwd": tmp2, "tool_input": {"command": heredoc}}
            got = decide(heredoc, tmp2, "s1", payload=payload_doc)
            check("gr56b an apostrophe in a heredoc message body is not a "
                  "directory change either: %r" % (got,),
                  got is None)
            payload_nocwd = {"tool_input": {"command": "git tag -a v1 -m x"}}
            got = decide("git tag -a v1 -m x", tmp2, "s1",
                         payload=payload_nocwd)
            check("gr57 a payload with no cwd and no directory change "
                  "answers to `project`, not UNKNOWN: %r / %r"
                  % (got, resolved_tree(payload_nocwd, tmp2)),
                  got is None
                  and os.path.realpath(resolved_tree(payload_nocwd, tmp2))
                  == os.path.realpath(tmp2))
            file_data_cd = ("cat > note.txt <<'EOF'\ncd /no/such/dir\nEOF\n"
                            "git tag -a v1 -m x")
            data_cd_payload = {"tool_input": {"command": file_data_cd}}
            got = decide(file_data_cd, tmp2, "s1", payload=data_cd_payload)
            check("gr64 RED-FIRST: a no-cwd payload whose file-data heredoc "
                  "names `cd` stays placeable and allows the clean release: %r"
                  % (got,),
                  got is None
                  and os.path.realpath(resolved_tree(data_cd_payload, tmp2))
                  == os.path.realpath(tmp2))
            data_cwd_cd = ("cat > note.txt <<'EOF'\ncd %s\nEOF\n"
                           "git tag -a v1 -m x" % wt)
            data_cwd_payload = {"cwd": tmp2,
                                "tool_input": {"command": data_cwd_cd}}
            got = decide(data_cwd_cd, tmp2, "s1", payload=data_cwd_payload)
            check("gr64c RED-FIRST: a payload cwd stays the release tree when "
                  "file data names a linked-worktree `cd`: %r" % (got,),
                  got is None
                  and os.path.realpath(resolved_tree(data_cwd_payload, tmp2))
                  == os.path.realpath(tmp2))
            decoy_cd = ("cd %s; bash <<'EOF'\ncd %s\nEOF\n"
                        "git tag -a v1 -m x" % (wt, tmp2))
            decoy_payload = {"cwd": tmp2, "tool_input": {"command": decoy_cd}}
            got = decide(decoy_cd, tmp2, "s1", payload=decoy_payload)
            check("gr65 RED-FIRST: a Bash heredoc makes the release target "
                  "UNKNOWN rather than guessing which shell runs its `cd`: %r"
                  % (got,),
                  resolved_tree(decoy_payload, tmp2) is None
                  and bool(got) and "UNKNOWN" in got)
            eval_cd = ('eval "$(cat <<\'EOF\'\ncd %s\nEOF\n)"\n'
                       "git tag -a v1 -m x" % wt)
            eval_payload = {"cwd": tmp2, "tool_input": {"command": eval_cd}}
            got = decide(eval_cd, tmp2, "s1", payload=eval_payload)
            check("gr66 RED-FIRST: an eval heredoc that can move the parent "
                  "shell makes the release target UNKNOWN: %r" % (got,),
                  resolved_tree(eval_payload, tmp2) is None
                  and bool(got) and "UNKNOWN" in got)
            source_cd = ("source /dev/stdin <<'EOF'\ncd %s\nEOF\n"
                         "git tag -a v1 -m x" % wt)
            dot_cd = (". /dev/stdin <<'EOF'\ncd %s\nEOF\n"
                      "git tag -a v1 -m x" % wt)
            source_got = decide(source_cd, tmp2, "s1", payload={
                "cwd": tmp2, "tool_input": {"command": source_cd}})
            dot_got = decide(dot_cd, tmp2, "s1", payload={
                "cwd": tmp2, "tool_input": {"command": dot_cd}})
            check("gr67 RED-FIRST: source and dot heredocs that can move the "
                  "parent shell make the release target UNKNOWN: %r / %r"
                  % (source_got, dot_got,),
                  all(bool(got) and "UNKNOWN" in got
                      for got in (source_got, dot_got)))
            shell_cd = ("bash <<'EOF'\ncd /no/such/dir\nEOF\n"
                        "git tag -a v1 -m x")
            shell_cd_payload = {"tool_input": {"command": shell_cd}}
            got = decide(shell_cd, tmp2, "s1", payload=shell_cd_payload)
            check("gr64b ALLOW-TWIN: the identical `cd` fed to Bash leaves "
                  "the no-cwd release target UNKNOWN: %r" % (got,),
                  resolved_tree(shell_cd_payload, tmp2) is None
                  and bool(got) and "UNKNOWN" in got)
            moved_nocwd = {"tool_input": {
                "command": "cd /no/such/dir && git tag -a v1 -m x"}}
            check("gr57b ...and a payload with no cwd that DOES move the "
                  "shell is still UNKNOWN - the mutation that treats a "
                  "missing cwd as always the project",
                  resolved_tree(moved_nocwd, tmp2) is None)
            write_tree_plan(tmp2, [{"id": "BUG-2", "status": "open",
                                    "severity": "med", "title": "a real one"}])
            slot_note = os.path.join(tmp2, STATE_REL, "release-bypass-s1.json")
            with open(slot_note, "w", encoding="utf-8") as fh:
                json.dump({"armedAtEpoch": time.time(), "ttlSeconds": 3600},
                          fh)
            got = decide(note, tmp2, "s1", payload=payload_note)
            check("gr58 the keyword still releases a tag whose comment has "
                  "an apostrophe: %r" % (got,),
                  got is None)
            os.remove(slot_note)
            got = decide(note, tmp2, "s1", payload=payload_note)
            check("gr58b without the keyword that same command names the "
                  "bug, not a directory change: %r" % (got,),
                  bool(got) and "BUG-2" in got and "directory change" not in got)
            listed = 'cd "$WT" && git tag --contains HEAD'
            got = decide(listed, tmp2, "s1", payload={
                "cwd": tmp2, "tool_input": {"command": listed}})
            check("gr59 listing tags behind an unreadable `cd` is not a "
                  "release: %r" % (got,),
                  got is None)
            bare = 'git -C "$WT" tag'
            got = decide(bare, tmp2, "s1", payload={
                "cwd": tmp2, "tool_input": {"command": bare}})
            check("gr59b a bare `git tag` behind an unreadable `-C` is not "
                  "a release either: %r" % (got,),
                  got is None)
        finally:
            subprocess.run(git + ["worktree", "remove", "--force", wt],
                          cwd=tmp2, check=True, capture_output=True,
                          timeout=30)

        # A NEWEST FULL RUN THAT RECORDS NO HEAD is not an ancestry question
        # git failed to answer: the evidence rule skips the row. Here no
        # older run contains the merge, so the phase reads PROVISIONAL,
        # holds the release as one, and gets the full-run remedy - never the
        # fetch/unshallow one, which cannot supply a head the row never
        # recorded, and never close-phase.
        tmp4 = tempfile.mkdtemp(prefix="guard-release-nohead-")
        try:
            os.makedirs(os.path.join(tmp4, "docs", "audit"))
            plan4 = {"meta": {"version": 2, "fullGate": ["full"],
                              "buildCommands": {"full": "echo full"}},
                     "phases": [{"id": "P4", "title": "s", "status": "done",
                                 "mergedAt": "2026-01-03T00:00:00Z",
                                 "mergedHead": "d" * 40, "tasks": []}],
                     "bugs": []}
            with open(os.path.join(tmp4, MANIFEST_REL), "w",
                      encoding="utf-8") as fh:
                json.dump(plan4, fh)
            cmds4 = [c for _n, c in
                     evidence_io.resolved_commands(plan4, ["full"])]
            evidence_io.append_row(tmp4, {
                "v": evidence_io.ROW_VERSION, "runId": "run-nohead",
                "ts": "2026-01-02T00:00:00Z", "scope": evidence_io.FULL_SCOPE,
                "status": "passed",
                "steps": [{"name": "gate", "command": c, "exit": 0,
                           "durationMs": 1000} for c in cmds4],
                "testedState": {},
                "observations": {"ranTotal": 1, "countsBasis": "1 check",
                                 "dirtyOutside": []}}, writer="selftest")
            got = decide("git tag -a v1 -m x", tmp4, "s1")
            check("gr36d RED-FIRST: a phase whose newest full run records no "
                  "head is refused as PROVISIONAL, its basis naming the "
                  "missing tested head, its remedy the full run - never "
                  "unanswerable, unshallow or close-phase: %r" % (got,),
                  bool(got) and "P4" in got
                  and "1 merged phase(s) are provisional" in got
                  and "names no tested head" in got
                  and "/audit:review <phase> --full" in got
                  and "unanswerable" not in got
                  and "unshallow" not in got
                  and "close-phase.py" not in got)
        finally:
            shutil.rmtree(tmp4, ignore_errors=True)

        # --- deny pins on the tree a release is judged against: a release
        # typed in this repository is refused over this plan, and a plan
        # missing from it refuses UNKNOWN rather than reading as clean.
        payload_in = {"cwd": tmp2, "tool_input": {
            "command": "git tag -a v1 -m x"}}
        got = decide("git tag -a v1 -m x", tmp2, "s1", payload=payload_in)
        check("gr44 a tag typed in THIS repository, placed through the "
              "payload, is refused over this plan: %r" % (got,),
              bool(got) and "BUG-2" in got)
        os.rename(mpath2, mpath2 + ".away")
        got = decide("git tag -a v1 -m x", tmp2, "s1", payload=payload_in)
        check("gr45 ...and a MISSING plan inside this repository still "
              "refuses, UNKNOWN: %r" % (got,),
              bool(got) and "UNKNOWN" in got)
        os.rename(mpath2 + ".away", mpath2)
    finally:
        # The fixture holds a git repository, whose loose objects windows will
        # not unlink - the plain call left this directory behind there.
        remove_tree(tmp2)

    # --- the removal copy, and the shell-facing spelling --------------------
    here_src = os.path.abspath(__file__)
    home_path = os.path.join(repo, "plugins", "audit", "tests", "_harness.py")
    try:
        with open(here_src, encoding="utf-8") as fh:
            own_src = fh.read()
        with open(home_path, encoding="utf-8") as fh:
            home_src = fh.read()
        drift = removal_copy_drift(own_src, home_src)
    except OSError as exc:
        drift = "could not read a side: %s" % (exc,)
    check("gr48 this hook's `remove_tree` runs the statements "
          "plugins/audit/tests/_harness.py's does, bar its lazy import - "
          "nothing else compares the two, so this is what keeps the copy a "
          "copy: %r" % (drift,), drift is None)
    one = ('def remove_tree(path):\n    """home"""\n'
           '    shutil.rmtree(path, ignore_errors=True)\n')
    lazy = ('def remove_tree(path):\n    """copy"""\n    import shutil\n'
            '    shutil.rmtree(path, ignore_errors=True)\n')
    moved = ('def remove_tree(path):\n    """copy"""\n    import shutil\n'
             '    shutil.rmtree(path)\n')
    # THE SECOND DIRECTION: the docstring and the lazy import are the
    # differences the copy is REQUIRED to have, so a comparison that stopped
    # dropping either would convict the arrangement it exists to police.
    check("gr49 a copy differing only by its docstring and its lazy import is "
          "not drift, while one whose statements moved is reported, and a "
          "side that lost the function or will not parse is named: %r"
          % ([removal_copy_drift(lazy, one), removal_copy_drift(moved, one),
              removal_copy_drift("x = 1\n", one),
              removal_copy_drift(lazy, "def remove_tree(:\n")],),
          removal_copy_drift(lazy, one) is None
          and "no longer runs" in (removal_copy_drift(moved, one) or "")
          and "this hook's copy carries no" in (
              removal_copy_drift("x = 1\n", one) or "")
          and "the harness home does not parse" in (
              removal_copy_drift(lazy, "def remove_tree(:\n") or ""))
    win_rel = "plugins\\audit\\scripts\\git\\close-phase.py"
    check("gr50 a shell-facing path is spelled with forward slashes whatever "
          "separator built it - Git Bash reads an unquoted backslash as an "
          "escape: %r %r" % (shell_path(win_rel), shell_path(CLOSE_PHASE_REL)),
          shell_path(win_rel) == "plugins/audit/scripts/git/close-phase.py"
          and shell_path(CLOSE_PHASE_REL)
          == "plugins/audit/scripts/git/close-phase.py")

    print("")
    print("%s: %d/%d cases passed"
          % ("ALL PASS" if not failed else "SELFTEST FAILED",
             len(cases) - len(failed), len(cases)))
    return 1 if failed else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    raise SystemExit(main())
