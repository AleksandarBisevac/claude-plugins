#!/usr/bin/env python3
"""
PostToolUse watcher (matcher: Bash|Edit|Write|MultiEdit|NotebookEdit) — the
"complete control" for shell writes that PreToolUse text inspection cannot
decide (SECURITY.md bypass class #1; upstream anthropics/claude-code#29709:
heredocs piped into interpreters, obfuscated redirects, etc.).

Two branches by tool_name:
  Edit/Write/MultiEdit/NotebookEdit → RECORD the file as tool-edited (those
      files went through guard-edits + require-plan already) — unless it lands
      outside the watched tree, which is silent and records nothing.
  Bash → if the command is PROVABLY READ-ONLY, absorb whatever appeared and
      attribute nothing (F-P-24: with a second agent in the same checkout, "new
      to me" stopped meaning "written by this call", and a `git ls-files | grep`
      was blamed twice in one session for a file another session had just
      created). Otherwise diff `git status --porcelain` (run in the configured
      `gitRoot`, so it works when the git repo lives in a subdirectory) against
      the session's last-seen dirty set. Dirty paths are translated back to project-relative
      (gitRoot-prefixed) to match task files and exempt globs. NEW dirty files
      that are SOURCE files, not exempt, not the manifest/lock, not tool-edited,
      not claimed by another session, and not covered by an in_progress task →
      inject a NON-blocking additionalContext warning (once per file per
      session). PostToolUse cannot undo the write — but the model gets told,
      in-band, that it just sidestepped the plan gate.

Attribution is PER TREE, and the tree is git's own answer rather than an env var.
`_config.repo_root` (CLAUDE_PROJECT_DIR, else the payload cwd) says where the CONFIG
lives; it does not say which tree a command touched, and it stays pinned to the
primary checkout while an agent works inside a worktree. So `git status` used to run
in one tree while the command ran in another, and that tree's dirt was handed to this
command (F84). `_config.command_tree` asks git from the working directory the
payload names; a command from a tree this guard does not watch gets a notice naming
both trees, once per tree, instead of an attribution. That directory is the
SESSION's and not the shell's, so a command that only WALKS into another tree -
`cd <worktree> && x`, which is how an agent reaches one, its shell starting back in
the session's directory on every call - compares equal to the watched tree and slips
past the notice. There the `cd` is the evidence: `directory_change_basis` withdraws
the authorship claim and keeps the finding (F212).

Attribution reads the OTHER sessions in this checkout before it blames this one.
Parallel phases in one working tree are a feature of this product, so "new since
my last snapshot" was never the same claim as "written by this command". Every
session keeps its own `bash-writes-<sid>.json` naming what it edited through the
gated tools, and the mtime of that file says when it last acted: a path another
session claims, from a session that acted inside the window this pass covers, is
attributed there and said nothing about here. When somebody else was writing in
the window but nothing names an author, the finding is still reported and the
authorship claim is dropped — see UNPROVEN_TEMPLATE.

State: <stateDir>/bash-writes-<session_id>.json
  {"toolEdited": [rel...], "seenDirty": [rel...], "warned": [rel...],
   "baselined": bool, "gitTimeout": bool, "otherTrees": [abs path...]}
  `otherTrees` is the ONLY key here that is not a repo-relative path, and the
  difference is load-bearing: every rel in this file is a path in the ONE tree
  this guard watches, which is what lets a sibling session's rels be read as
  claims about the same files. That is now ENFORCED at the edit branch rather
  than assumed of it (`_config.within_root`): an Edit outside the tree used to
  land in `toolEdited` wearing relpath's `../..` escape, where no `git status`
  line could ever equal it. `otherTrees` names trees that were declined, so
  it is a list of absolute directories and never a claim about a file.
  `baselined` marks that the session's FIRST Bash pass has seeded seenDirty
  with the tree's pre-existing dirt (silently) — only dirt appearing after
  that baseline is ever attributed to a shell command.
  Written for THIS session and read for every other one in the same stateDir
  (`_other_sessions`), which is what makes a second writer visible at all. The
  file's mtime is its own timestamp: no field had to be added for the window.
Read-only sidecars: <stateDir>/bash-writes-plugin-<key>.json {"pluginWrote": [rel]}
  — journal files the plugin ITSELF appended to. Those rels are skipped before
  the journal check, so the plugin's own append is never blamed on the next
  shell command (F-F3). One slot per writer, each with a SINGLE writer, because
  hooks on one event run in parallel: `<sid>` is this session's, written by
  journal-writes.py, and `panel` is the panel server's, written by
  `_panel_write` (F104 — a detached process this plugin launched, whose appends
  the session's slot can never name because the session did not make them).
  A PEER SESSION'S slot is not read: see `_plugin_wrote`.

Config: `.claude/audit.config.json` → bashWriteCheck.enabled (default true).
Non-git repos, git errors/timeouts (5 s) → silent. ALWAYS exits 0.

This hook carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test_guard_bash_writes.py` (hyphens become underscores - a
hyphenated name is not importable). A test of a hook may import from `scripts/`
even though the hook itself may not; see `plugins/audit/tests/_harness.py`.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _config  # noqa: E402

# Mirrors journal-writes.py's `_SAFE_SID`: the sidecar read below is written by
# that hook, and the two must agree about how a session id becomes a file name.
# `test_guard_bash_writes.py`'s k1 drives the REAL writer, so a drift here goes red.
_SAFE_SID = re.compile(r"[^A-Za-z0-9._-]+")

# The sidecar's name and the panel's key, mirrored from `_journal_io`
# (`PLUGIN_WRITE_SIDECAR`, and `_panel_write.PANEL_JOURNAL_WRITER`) for the one
# reason a hook ever mirrors a constant: it may not import from `scripts/`. The
# (pw) group drives the REAL panel writer and reads it back through the function
# below, so a drift in either spelling goes red rather than going quiet -- and
# quiet is the direction that matters, because an empty sidecar is
# indistinguishable from "the plugin appended nothing".
PLUGIN_SIDECAR = "bash-writes-plugin-%s.json"
PANEL_WRITER = "panel"

# --- the git call -------------------------------------------------------------
# `-uall` is load-bearing, and the measurement is the reason it survives a profile:
# on a fixture of 4000 untracked, unignored files it costs ~86 ms against ~19 ms for
# `-unormal` - but `-unormal` collapses a new source file in a new directory to
# `?? src/`, which `_is_source` does not recognise, so the warning this hook exists
# to emit would simply disappear. Speed bought with silence is the one trade this
# guard must not make. Re-derive both numbers before changing the flag.
#
# `--no-optional-locks` is NOT a speed change (measured: none). It stops git taking
# the index lock, which matters because this plugin's headline feature is phases
# running in parallel worktrees. It goes BEFORE the subcommand - after it, git exits
# with `unknown option`.
GIT_STATUS_ARGV = ["git", "--no-optional-locks", "status", "--porcelain", "-uall"]
_GIT_TIMEOUT_SECONDS = 5

# --- notice templates ---------------------------------------------------------
# A repo whose `git status` cannot finish inside the budget is a repo where this
# guard is OFF. That is a fact about the session, not about the command that
# happened to be running, so it is said once and never repeated - a notice on every
# shell call in a large monorepo is a notice people disable.
TIMEOUT_TEMPLATE = (
    "[bash-write-guard] `git status` did not finish within %s seconds in this "
    "repository, so unplanned shell writes are NOT being detected for the rest of "
    "this session. This is said once. Usually it means a large untracked, "
    "unignored tree - adding it to .gitignore restores the guard. To switch the "
    "check off deliberately, set bashWriteCheck.enabled to false."
)

WARN_TEMPLATE = (
    "[bash-write-guard] That shell command modified source file(s) with no "
    "plan coverage: %s. Plan-first applies to shell writes too — add the "
    "file(s) to an in_progress task in the audit manifest, or use the "
    "Edit/Write tools (which the plan gate reviews). This is a non-blocking "
    "notice; the change itself was NOT reverted."
)

# The journal is append-only, and guard-edits refuses an EDIT to it. A shell write
# is the same act through the door that cannot be locked, so it is reported the
# moment it is seen — including the case where nothing was hidden and a script
# simply wrote there, because "the audit trail changed and the plugin did not do
# it" is worth one line either way. `verify` is named rather than described: it is
# the command that says whether the chain still holds.
JOURNAL_TEMPLATE = (
    "[bash-write-guard] That shell command wrote into the append-only audit "
    "journal: %s. The journal records who changed the plan and the config; it is "
    "written by the plugin (panel saves, the journal-writes hook, "
    "`audit-journal.py append`) and never by hand, and an edit tool would have "
    "been REFUSED here. This is a non-blocking notice; the change was NOT "
    "reverted. Run `audit-journal.py verify` to see whether the chain still holds "
    "- if verify says the chain holds and the newest row is fresh, this was "
    "likely the plugin itself (a panel save, or an edit and a shell command in "
    "one message). Otherwise, tell the human what wrote there."
)

# Same fact as require-plan's lock denial, delivered late because a shell write
# cannot be intercepted before it lands. Worded as what already happened, not as
# what to avoid — there is no avoiding it by the time this runs.
LOCKED_TEMPLATE = (
    "[bash-write-guard] That shell command wrote to manifest file(s) held by "
    "ANOTHER LIVE SESSION: %s. Through Edit/Write the plan gate would have "
    "refused this; a shell write cannot be caught before it lands, so it has "
    "already happened and was NOT reverted. The other session is still running "
    "and holds no knowledge of this change — it will write its own version over "
    "yours, or yours over its, with no conflict, because one working tree means "
    "git never sees two versions. Stop, tell the human, and reconcile by hand: "
    "`audit-lock.py status` shows who holds what."
)

# The same finding as WARN_TEMPLATE with the authorship claim removed, because the
# evidence for that claim is missing and something else in the window could account
# for the paths. Still said rather than swallowed — an unplanned source write is
# worth a line whoever made it — but what it reports is what IS established, which
# is the only version of the line a reader can act on. Telling somebody they wrote a
# file they did not is how a guard teaches people to route around it.
#
# THE SECOND SLOT IS A CLAUSE, NOT A SESSION LIST, and it became one when a second
# kind of other-author turned up. It used to read "session(s) %s were writing",
# which is the right sentence for a peer session and the wrong one for this
# session's OWN background job — a job that belongs to nobody else and so has no
# sibling state file to name. Two evidence kinds, one message shape: whoever built
# the clause says what it found, and this template stops needing to know.
UNPROVEN_TEMPLATE = (
    "[bash-write-guard] Source file(s) with no plan coverage became dirty while "
    "that shell command ran: %s. This guard CANNOT say the command wrote them: %s. "
    "What is established: the "
    "file(s) were clean at this session's previous look and are dirty now, and "
    "no in_progress task covers them. If the change is yours, put the file(s) on "
    "an in_progress task or use the Edit/Write tools (which the plan gate "
    "reviews); if it is not, it belongs to whatever the clause above names. This "
    "is a non-blocking notice; nothing was reverted."
)

# A command that ran in a WORKING TREE this guard is not watching, said once per
# tree. F84: the guard watches ONE tree - `git status` runs in the configured
# gitRoot, and every path in the session's state file is a path in that tree - but
# it was choosing that tree with `CLAUDE_PROJECT_DIR`, which answers where the
# CONFIG lives and stays pinned to the primary checkout while an agent works inside
# a worktree. So dirt a parallel session was making in the primary tree was handed
# to a read-only sweep running in the worktree. Both trees are named because a
# guard that quietly stopped covering one would be indistinguishable from a guard
# that found nothing there, and the way back is a fact about the setup rather than
# about the command, so it is said once.
OTHER_TREE_TEMPLATE = (
    "[bash-write-guard] That shell command ran in %s (%s), and this guard watches "
    "%s. It cannot say what the command wrote: it has looked only at the watched "
    "tree, and what is dirty there belongs to whoever is working there. So shell "
    "writes made from that tree are NOT being checked against the plan, and "
    "nothing is being attributed to this command. This is said once per tree. To "
    "guard a worktree, open its own session in it - `/audit:worktree` prints the "
    "command - and the hooks resolve their project directory to the worktree "
    "instead."
)

_EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")

# Commands that cannot change a file, whatever their arguments. An ALLOWLIST, not a
# list of writers: a writer this file has never heard of must keep being watched, so
# anything unrecognised stays attributable. `sed` and `find` are here because they
# are overwhelmingly used to read, and the flag check below removes the spellings
# that write.
#
# `cd`/`pushd`/`popd` MOVE THE SHELL, NOT A FILE, and their absence was the single
# most productive false positive this guard has had. Every segment is judged on its
# own, so a `cd` in front of a read left the WHOLE command unproven: `cd <dir> &&
# grep -n foo FILE` - the most ordinary shape in a session that works across two
# repositories - came back watched, and then inherited the blame for a write it had
# nothing to do with. Adding them removes an attribution and never a refusal:
# `cd x && rm -rf f` is still watched, because `rm` is still not on this list.
_READ_ONLY_CMDS = frozenset((
    "git", "grep", "rg", "ag", "cat", "head", "tail", "sed", "awk", "cut", "sort",
    "uniq", "wc", "tr", "jq", "find", "ls", "stat", "file", "basename", "dirname",
    "echo", "printf", "pwd", "true", "false", "test", "which", "type", "env",
    "date", "du", "df", "nl", "column", "comm", "diff", "cmp", "shasum", "md5sum",
    "xxd", "od", "realpath", "readlink", "seq", "yes", "tee", "xargs",
    "cd", "pushd", "popd",
))
# `xargs` was the absence that started F51. It runs another command, and the
# segment split already puts that command in a segment of its own —
# `find … | xargs wc -l` is `find …` and `xargs wc -l`, both judged. What made it
# a writer was simply not being on this list, and `find | xargs wc -l` is the
# measuring idiom this project's own documents reach for.
# Sub-commands of `git` that write. `git` itself is on the list above because
# `git status`/`log`/`diff` are the most common reads in any session.
_GIT_WRITES = frozenset((
    "add", "am", "apply", "branch", "checkout", "cherry-pick", "clean", "clone",
    "commit", "fetch", "gc", "init", "merge", "mv", "pull", "push", "rebase",
    "remote", "reset", "restore", "rm", "stash", "submodule", "switch", "tag",
    "worktree", "config", "update-index", "update-ref", "notes", "replace",
))
# Flags that turn a reader into a writer, matched as WHOLE tokens. `sed` also
# takes its backup suffix attached — `-i.bak`, `--in-place=.bak` — and an exact
# membership test called those an ordinary argument, so a real in-place write
# came back provably-read-only and the guard said nothing (F56). BSD `sed`
# refuses a bare `-i`, so the attached form is the only one that works on a Mac:
# the spelling that went unseen is the spelling anyone here would type.
# `_write_flag()` below is the membership test; this set is what it reads.
_WRITE_FLAGS = frozenset(("-i", "--in-place", "-delete"))
# Operators that end one command and begin another. Compared as TOKENS, so a
# `;` or a `&&` inside a quoted search pattern is text rather than syntax.
_OP_TOKENS = frozenset((";", "|", "||", "&&", "&"))
# Redirections. `>` and friends name a destination, so any surviving one puts the
# command on the watched side — but only the ones the SHELL would treat as a
# redirect. `grep -n "cost > 5"` names nothing (F51).
_REDIRECT_TOKENS = frozenset((">", ">>", "<", "<<", "<<<", ">&", "<&", ">|"))
# Substitution and expansion, again as tokens: grepping FOR `$(`, `${` or a
# backtick is not running a subshell.
_SUBST_TOKENS = frozenset(("`", "$", "(", ")"))
# `xargs` runs another command, exactly as `-exec` does, and the honest question
# is what THAT command is. Putting `xargs` on the allowlist without this made
# `find … | xargs rm` provably-read-only — the false-negative twin of the
# false positive it was added to fix. These flags take a value, so the value is
# not the command.
_XARGS_VALUE_FLAGS = frozenset((
    "-n", "-P", "-I", "-i", "-L", "-s", "-d", "-E", "-a",
    "--max-args", "--max-procs", "--replace", "--max-lines", "--max-chars",
    "--delimiter", "--eof", "--arg-file",
))
# `-exec` and its relatives are NOT among them, though they were. They run
# another command, and the only honest question is what THAT command is:
# `find . -name '*.py' -exec cat {} +` is a read, and calling it a write is how
# the most ordinary sweep in this repo got blamed for another session's file.
_EXEC_FLAGS = frozenset(("-exec", "-execdir", "-ok", "-okdir"))
# find ends an -exec clause with `;` or `+`. The `;` is written `\;` in a shell,
# and `_tokenize` resolves that escape — so what arrives here is a bare `;`,
# which is ALSO an operator token. The two are told apart by position and
# nothing else, which is why `_split_exec_clauses` runs before the operator
# split: a `;` that closes an open `-exec` is not a command separator.
#
# The old spellings are gone with the mechanism that needed them. The regex
# splitter used to eat the `;` before this set was consulted, so a lone trailing
# backslash had to count as an ending; there is no longer a stage that can eat it.
_EXEC_END = frozenset((";", "+"))
# The `cd` family again, asked a DIFFERENT question. They are on the allowlist
# above because they cannot touch a file; here they matter because they move the
# shell, and where the shell was is what decides which tree a write landed in
# (F212). One name, two questions, and the answers point opposite ways: `cd` makes
# a command safer to ignore and its LOCATION harder to establish.
_DIR_CHANGE_CMDS = frozenset(("cd", "pushd", "popd"))
# Marks that stop a `cd` argument being read as a literal directory. Every one of
# them is something the SHELL resolves and the payload does not carry: parameter
# and command substitution, a glob, a home reference. `-` (the previous directory)
# needs no entry - it is filtered out with the other option-looking words, which
# leaves no target at all, which is the same answer.
_UNRESOLVED_MARKS = ("$", "`", "*", "?", "~")


def _tokenize(text):
    """Shell words and operators, or None when the text cannot be parsed.

    THE WHOLE OF F51 IS THAT THIS DID NOT EXIST. Every decision below used to be
    taken on the raw string: the hostile scan ran `">" in text`, and the segment
    split was `re.split(r"&&|\\|\\||[|;]|\\n", text)`. Neither knows what a quote
    is, so `grep -n "cost > 5"` was a redirect, `grep -n "a && b"` was two
    commands, and `grep -n "READ_ONLY\\|read_only" f.py | head` was cut inside its
    own pattern into a fragment whose first word is not a command name. Grepping
    for shell punctuation is the most ordinary thing done in this repo.

    `punctuation_chars=True` is what makes an operator its own token instead of
    gluing it to the word beside it — without it `echo "x"; ls` yields `x;` and
    the split misses the `;` entirely.

    None means "the shell would read this differently than any split here can":
    unbalanced quotes, and anything else `shlex` refuses. Returning it keeps the
    command on the WATCHED side, which is the standing choice of this file —
    an unrecognised command is attributable, because the cost of a stray notice
    is a line of text and the cost of a miss is a write nobody was told about.
    Before this, an unbalanced quote reached the allowlist and passed.

    `shlex` IS IMPORTED HERE, NOT AT MODULE SCOPE, and `tools/bench-hooks.py`
    named this hook when it refused the eager version. Every hook pays its
    module-level imports on every matching tool call, and this one is on both a
    Bash and an Edit matcher — the Edit lane returns without ever asking about a
    command. Same reason `subprocess` is imported inside `_git_dirty` below.
    """
    import shlex
    try:
        lex = shlex.shlex(text, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        return list(lex)
    except ValueError:
        return None


def _drop_harmless_redirects(toks):
    """Remove redirect groups that name no file: `[fd]> /dev/null` and `[fd]>& fd`.

    The token-level twin of a regex that read `[0-9]*>>?\\s*/dev/null(?=\\s|$)`.
    That regex could not see `2>&1` at all, so its `&` reached the hostile scan
    and every stderr-merging read — `grep x f.py 2>&1`, and `ls >/dev/null 2>&1`
    where BOTH redirects are harmless — was watched. Descriptor duplication
    writes to a descriptor, never to a path.

    The `/dev/null.bak` distinction the old lookahead protected still holds, and
    for a better reason: the target is now a whole token, so it either equals
    `/dev/null` or it does not.
    """
    out, i = [], 0
    while i < len(toks):
        tok = toks[i]
        if tok in _REDIRECT_TOKENS and i + 1 < len(toks):
            target = toks[i + 1]
            harmless = (target == "/dev/null"
                        or (tok in (">&", "<&") and target.isdigit()))
            if harmless:
                if out and out[-1].isdigit():
                    out.pop()               # the leading descriptor, e.g. the 2 of 2>&1
                i += 2
                continue
        out.append(tok)
        i += 1
    return out


def _write_flag(tok):
    """Does this token turn a reader into a writer?

    Whole-token membership plus the attached-value spellings of the in-place
    family, which is F56: `-i.bak` and `--in-place=.bak` are the same capability
    as `-i` wearing a suffix, and only the bare form was ever matched.
    """
    if tok in _WRITE_FLAGS:
        return True
    if tok.startswith("--in-place="):
        return True
    if tok.startswith("--output"):
        return True
    return (tok.startswith("-i") and not tok.startswith("--") and len(tok) > 2)


def _xargs_command(rest):
    """The argv `xargs` will run, or [] when there is none to judge.

    Same contract as `_exec_clauses`: the flags are skipped, the first remaining
    word is the command, and an empty result proves nothing — which keeps a bare
    or malformed `xargs` on the watched side rather than inheriting `echo`'s
    harmlessness by default.
    """
    i = 0
    while i < len(rest):
        tok = rest[i]
        if not tok.startswith("-"):
            return rest[i:]
        if tok in _XARGS_VALUE_FLAGS:
            i += 2                          # the value is not the command
        else:
            i += 1
    return []


def _split_exec_clauses(toks):
    """Every `-exec`/`-ok` clause's argv, and the tokens left over.

    Each clause is judged in turn, so `-exec` costs a proof of the inner command
    rather than acting as a blanket write flag. A clause with no command comes
    back empty, and an empty command proves nothing — which is the answer that
    keeps a malformed find on the watched side.

    IT RETURNS THE REMAINDER because the clause has to leave the token stream
    before the operator split sees it. `find … -exec grep -l foo {} \\;` reaches
    here as a trailing `;`, and a `;` is how one command ends and another begins:
    left in place it cut the find in half and the empty second half proved
    nothing, so a case that had passed for as long as `-exec` has been judged
    went red. Consuming the terminator with its clause is what tells the two
    meanings of `;` apart.
    """
    clauses, rest, i = [], [], 0
    while i < len(toks):
        if toks[i] not in _EXEC_FLAGS:
            rest.append(toks[i])
            i += 1
            continue
        i += 1
        argv = []
        while i < len(toks) and toks[i] not in _EXEC_END:
            argv.append(toks[i])
            i += 1
        if i < len(toks):
            i += 1                    # the terminator belongs to the clause
        clauses.append(argv)
    return clauses, rest


def _segments(toks):
    """The token stream cut into COMMANDS at the shell's operators, each stripped
    of the prefixes that are not the command name.

    ONE CUT, TWO QUESTIONS. The read-only proof asks what each command IS; the
    directory question below asks whether it MOVES THE SHELL. Both need the same
    notion of where a command begins, and the second was written after the first,
    so a second copy of the split would have been a second opinion about `FOO=1 cd
    /x` waiting to disagree.

    `(` goes with the assignments: a subshell's first word is the command, and a
    `cd` inside one still moves the shell the rest of that subshell runs in. It
    changes nothing for the read-only proof, which refuses a `(` outright before
    this is ever reached.
    """
    segments, current = [], []
    for tok in toks:
        if tok in _OP_TOKENS:
            segments.append(current)
            current = []
        else:
            current.append(tok)
    segments.append(current)
    out = []
    for words in segments:
        # Leading VAR=value assignments are not the command.
        while words and (words[0] == "("
                         or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0])):
            words = words[1:]
        out.append(words)
    return out


def directory_change_basis(command, cwd, watching):
    """Why the payload's working directory is no longer evidence for where this
    command ran - or None when it still is.

    -> a clause for UNPROVEN_TEMPLATE's second slot, or None

    F212. `_config.command_tree` asks git which tree the command ran in, FROM THE
    PAYLOAD'S cwd - and that field is the SESSION's directory, not the shell's. The
    two agree for a session that sits in a worktree, which is the shape F84 was
    reported and fixed for. They come apart for a session that only VISITS one:
    `cd <worktree> && <writer>` leaves the payload naming the tree the session
    started in, `command_tree` matches it against the watched tree, and the
    equal-path short circuit answers "watched" without asking git anything. The
    watched tree's dirt is then handed to a command that never touched it.

    That shape is not exotic here. An agent's Bash calls each start in the
    session's directory - the harness resets the shell between them - so every
    command an agent runs in a phase worktree carries a `cd` in front of it, and
    the payload never learns.

    WHAT THIS RETURNS IS A WITHDRAWAL, NOT A NEW CLAIM, and the asymmetry is the
    design. It never says the command wrote somewhere; it says this guard cannot
    place the command, so the authorship half of the notice comes off while the
    finding stays. Reading a destination out of the command text to ACCUSE
    somebody would be the raw-string inference F51 was about; reading it to stop
    accusing costs nothing if it is wrong.

    So the claim survives only on positive evidence that the shell stayed put:
    every directory change in the command names a literal path that lands inside
    the watched tree. A change whose target the payload cannot resolve - an
    expansion, a substitution, a bare `cd`, a `popd` - is not guessed at.
    """
    toks = _tokenize((command or "").strip())
    if not toks:
        return None
    for words in _segments(toks):
        if not words or words[0] not in _DIR_CHANGE_CMDS:
            continue
        args = [w for w in words[1:] if not w.startswith("-")]
        if len(args) != 1 or any(m in args[0] for m in _UNRESOLVED_MARKS):
            return ("the command moved the shell with `%s` and this guard cannot "
                    "tell where to, so it cannot place the command in a working "
                    "tree at all; what is dirty in the tree it watches belongs to "
                    "whoever is working there" % words[0])
        dest = os.path.realpath(os.path.join(str(cwd or "."), args[0]))
        if not _config.within_root(watching, dest):
            return ("the command moved the shell to %s, which is not the tree "
                    "this guard watches, so what is dirty here belongs to "
                    "whoever is working in this tree" % dest)
    return None


def _command_is_read_only(command):
    """Can this shell command be proven unable to write? Default: NO.

    F-P-24. The guard used to decide from the TREE alone - it diffed
    `git status --porcelain` against its own last snapshot and attributed anything
    new to whatever Bash command ran next. With a second session working in the
    same checkout, "new" routinely means "somebody else wrote it", and the blame
    landed on a command that only read. Reported twice in one session, both times
    for a pure `git ls-files` + `grep`, and both times about a file another session
    had just created.
    
    The evidence has to be bound to the OPERATION, and this hook already had the
    operation in hand: `tool_input.command` was being read for the Edit branch and
    ignored for the Bash one. So this only ever REMOVES an attribution, and only
    when the command provably cannot write - an unrecognised command is still
    watched exactly as before.

    F51 IS WHY THIS TOKENIZES FIRST. Every check used to read the raw string, so
    a shell metacharacter inside a quoted SEARCH PATTERN was taken for shell
    syntax and the most ordinary command in this repo - grepping its own source
    for punctuation - was called a writer. `_tokenize` is the fix, and everything
    after it asks its questions of tokens.
    """
    toks = _tokenize((command or "").strip())
    if not toks:
        return False              # empty, or unparseable: both stay watched
    return _tokens_are_read_only(toks)


def _tokens_are_read_only(toks):
    """The proof itself, over shell TOKENS.

    Separate from `_command_is_read_only` so `-exec` and `xargs` can recurse on
    the argv they already hold instead of joining it back into a string and
    re-splitting it — a round trip that loses exactly the quoting F51 was about.
    """
    toks = _drop_harmless_redirects(toks)
    for tok in toks:
        if tok in _REDIRECT_TOKENS or tok in _SUBST_TOKENS:
            return False
    # BEFORE the operator split, because a clause's `\;` terminator arrives as a
    # bare `;` and would otherwise be read as the end of the command.
    clauses, toks = _split_exec_clauses(toks)
    for argv in clauses:
        if not argv or not _tokens_are_read_only(argv):
            return False
    segments = _segments(toks)
    if not any(segments):
        return False
    for words in segments:
        if not words:
            return False
        name = os.path.basename(words[0])
        if name not in _READ_ONLY_CMDS:
            return False
        rest = words[1:]
        if name == "git":
            subs = [w for w in rest if not w.startswith("-")]
            if not subs or subs[0] in _GIT_WRITES:
                return False
        if name == "tee":
            return False          # tee's whole purpose is a destination
        if name == "xargs":
            argv = _xargs_command(rest)
            if not argv or not _tokens_are_read_only(argv):
                return False
        for flag in rest:
            if _write_flag(flag):
                return False
    return True


# --- state --------------------------------------------------------------------
# PUBLIC because they are READ FROM OUTSIDE this file. `/audit:doctor` dates the
# copy that wrote a state file here by which of `default_state()`'s keys the file
# carries (F228) - the same evidence that identified a stale cached copy by hand,
# mechanised - and it tells a session slot from a plugin sidecar by these two
# name templates. A hand-written list over there would be a second statement of
# this file's shape, drifting the first time a key is added here.
STATE_FILE = "bash-writes-%s.json"


def default_state():
    """The state a session slot holds before anything has happened - and
    therefore the exact key set `_save_state` writes, every time."""
    return {"toolEdited": [], "seenDirty": [], "warned": [], "baselined": False,
            "gitTimeout": False, "otherTrees": [], "bgLaunches": []}


def _state_file(state_dir, session_id):
    return state_dir / (STATE_FILE % session_id)


def _load_state(state_dir, session_id):
    try:
        with open(_state_file(state_dir, session_id), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return {"toolEdited": list(data.get("toolEdited") or []),
                    "seenDirty": list(data.get("seenDirty") or []),
                    "warned": list(data.get("warned") or []),
                    "baselined": bool(data.get("baselined")),
                    "gitTimeout": bool(data.get("gitTimeout")),
                    "otherTrees": list(data.get("otherTrees") or []),
                    "bgLaunches": list(data.get("bgLaunches") or [])}
    except Exception:
        pass
    return default_state()


def _save_state(state_dir, session_id, state):
    try:
        _config.ensure_local_dir(state_dir)
        with open(_state_file(state_dir, session_id), "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except Exception:
        pass


def _sidecar_rels(state_dir, key):
    """The rels ONE plugin sidecar names, or an empty set on any miss.

    Empty is the honest answer to every failure here: a missing slot means that
    writer appended nothing, which is the ordinary state."""
    try:
        with open(state_dir / (PLUGIN_SIDECAR % key), "r", encoding="utf-8") as fh:
            obj = json.load(fh)
        wrote = obj.get("pluginWrote") if isinstance(obj, dict) else None
        return {str(x) for x in wrote} if isinstance(wrote, list) else set()
    except Exception:
        return set()


def _plugin_wrote(state_dir, session_id):
    """Journal files the PLUGIN ITSELF appended to, from every writer that can
    leave a claim here (F-F3, F104).

    Written by journal-writes.py after each successful append, as
    `<stateDir>/bash-writes-plugin-<sid>.json` `{"pluginWrote": [rel, ...]}`.
    Read-only here, and that is load-bearing: hooks registered on the same
    event run in PARALLEL, so each sidecar has exactly one writer (the hook
    that made the journal write) and this one only ever looks.

    TWO SLOTS, NOT ONE, AND NOT EVERY SLOT IN THE DIRECTORY. The panel server is
    a detached process this plugin launched, and it writes the journal too -- so
    its appends were reported as this session's shell writes, with a clean chain
    behind them and nothing but a manual check to say so (F104). It cannot use
    the session's slot: the session did not write those rows. It gets a fixed key
    of its own, because a panel is one per project (`panel-server` refuses a
    second) and a per-process key would fragment the claim exactly as it
    fragmented the journal.

    A PEER SESSION'S SLOT IS DELIBERATELY NOT READ. `test_guard_bash_writes`'s k2
    is the reason: a journal write nothing claims is the `sed`-shaped write this
    guard exists for, and honouring another session's claim would let a real
    tampering pass whenever that session had ever appended to the same file."""
    sid = _SAFE_SID.sub("-", str(session_id or "")).strip("-.")
    sid = (sid or "no-session")[:40]
    out = set()
    for key in (sid, PANEL_WRITER):
        out |= _sidecar_rels(state_dir, key)
    return out


_BG_LAUNCH_CAP = 20


def _now():
    """Wall clock, as its own function so a case can hand in a fixed one.

    `time` is a builtin C module, so this costs the hook import budget nothing
    measurable — re-derive with `tools/bench-hooks.py` rather than trusting that.
    """
    import time
    return time.time()


def record_background_launch(state, tool_input, now):
    """Note a detached Bash launch this session made, if it could write. -> bool.

    THE BLIND SPOT THIS CLOSES is the mirror of the one `_other_sessions` names, and
    it is invisible to that function by construction: a background job belongs to
    THIS session, so there is no sibling state file to claim its writes and
    `_other_sessions` skips `mine` on purpose. PostToolUse fires when the job is
    LAUNCHED, minutes before it writes, so the dirt lands inside a later pass's
    window and the blame goes to whatever foreground command ran next. Observed
    twice in one session, both times on a read in a different repository, while
    `tools/prove-gates.py` mutated this one in the background.

    ONLY A PROGRAM NAME IS KEPT, never the command text. `_journal_io` settled this
    for the same channel one file over (CWE-532, F136/F153): a command line carries
    paths, hostnames and occasionally a token, and this state file is not a place a
    redactor reaches. The first token answers the only question the verdict asks.

    WHERE `run_in_background` COMES FROM, AND WHAT IS STILL UNPROVEN ABOUT IT. It
    rides in `tool_input` beside `command` and `timeout` - read off a real session
    transcript on 2026-08-26 rather than assumed, since this whole branch is dead if
    the key arrives somewhere else. What that does NOT establish is delivery: the
    hooks that fire in a session come from the INSTALLED plugin, and this repo's
    marketplace entry is a `github` source, so a working-tree edit is not live and
    the end-to-end path could not be exercised here. The cases below drive `decide`
    with the transcript's shape, which is the strongest proof available without
    publishing. To close it after a release: reinstall, `/reload-plugins`, launch one
    backgrounded writer, and read `bgLaunches` out of this session's state file. If
    it is empty, the key does not survive the hook boundary and this branch is inert
    - which would be a finding, not a mystery.

    NOT BOUNDED BY `timeout`, WHICH WAS MEASURED RATHER THAN ASSUMED. The obvious
    window is the `timeout` the launch carries, and it does not hold: on 2026-08-26
    a background `prove-gates.py` launched with `timeout: 600000` ran 627 seconds and
    completed normally. A background job outlives its timeout, so a window closed on
    it would go quiet exactly while the job was still writing. There is no hook when
    a background job ends, so no honest end exists - which is why the launches are
    reported with their age and never silently expired.
    """
    if not isinstance(tool_input, dict) or not tool_input.get("run_in_background"):
        return False
    command = tool_input.get("command") or ""
    if _command_is_read_only(command):
        return False              # it cannot write later either
    toks = _tokenize(command.strip()) or []
    program = toks[0] if toks else "?"
    state["bgLaunches"] = (list(state.get("bgLaunches") or [])
                           + [{"program": program, "at": now}])[-_BG_LAUNCH_CAP:]
    return True


def background_basis(state, now):
    """The clause naming this session's unaccounted background jobs, or None.

    AGE IS IN IT BECAUSE NOTHING CAN REPORT COMPLETION. A bare count reads as "a job
    is running"; a count with an age lets the reader answer that themselves, which is
    the only version of the claim that is true. Ages are rendered whole-minute and
    the oldest is named, so a launch from an hour ago is visibly not an explanation.
    """
    launches = list(state.get("bgLaunches") or [])
    if not launches:
        return None
    ages = sorted(max(0, int(now - float(row.get("at") or now))) for row in launches)
    programs = sorted(set(str(row.get("program") or "?") for row in launches))
    return ("%d background job(s) this session launched (%s) are unaccounted for - "
            "no hook fires when one ends, so they cannot be ruled out; newest "
            "launched %dm ago, oldest %dm"
            % (len(launches), ", ".join(programs[:4]),
               ages[0] // 60, ages[-1] // 60))


def _state_mtime(state_dir, session_id):
    """When this session last wrote its state — one end of the window a pass
    covers. 0.0 when there is no file yet, which only happens before the
    baseline pass has run."""
    try:
        return os.path.getmtime(str(_state_file(state_dir, session_id)))
    except OSError:
        return 0.0


def _other_sessions(state_dir, session_id, since):
    """What the OTHER sessions in this checkout did inside this pass's window.

    -> {"claimed": {rel: sid}, "active": [sid...]}

    Parallel phases through worktrees are an advertised feature, so more than one
    writer in a tree is the normal case, not the edge one. This hook was deciding
    authorship from the TREE alone — anything new since its own snapshot belonged
    to whatever Bash command ran next — and the evidence that says otherwise was
    already on disk, unread: each session keeps its own `bash-writes-<sid>.json`,
    and `toolEdited` in it names the files that session put through the gated
    edit tools.

    `active` is bound to the WINDOW, not to a timeout: a sibling state file is
    rewritten on every tool call of its session, so a file touched after `since`
    means that session acted between this session's previous look at the tree and
    this one — exactly the interval the new dirt appeared in. An equal timestamp
    counts as OUTSIDE the window: on a filesystem with coarse mtimes the tie
    should leave the guard its voice rather than silence it.

    `seenDirty` is deliberately not a claim. Every session records every dirty
    path it SEES, so reading that as authorship would let two sessions exonerate
    each other for a file neither of them wrote. `warned` is a claim in the weaker
    sense that matters here: that session has already been told about the path, so
    repeating it is noise at best and a second wrong accusation at worst.

    KNOWN RESIDUAL, because a guard that hides its blind spot is worse than one
    that names it: a sibling state file is only rewritten when a hook fires for
    that session, so a session that spends the whole window inside ONE long tool
    call is invisible here, and its writes still reach the plain claim. The lock
    would close that case — a phase running in parallel holds one, and it carries
    a sessionId and a liveness verdict — but it names the holder of a MANIFEST
    path rather than the author of a source file, `manifest_lock_conflict()`
    already reads it for the paths it does govern, and reading it here would cost
    every warning a lock-directory scan. Consult it if the residual is ever
    observed rather than reasoned about.
    """
    claimed, active = {}, []
    try:
        names = sorted(os.listdir(str(state_dir)))
    except OSError:
        return {"claimed": claimed, "active": active}
    mine = _state_file(state_dir, session_id).name
    for name in names:
        if name == mine or name.startswith("bash-writes-plugin-"):
            continue
        if not name.startswith("bash-writes-") or not name.endswith(".json"):
            continue
        try:
            if os.path.getmtime(str(state_dir / name)) <= since:
                continue
            with open(str(state_dir / name), "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        sid = name[len("bash-writes-"):-len(".json")]
        active.append(sid)
        for rel in list(data.get("toolEdited") or []) + list(data.get("warned")
                                                             or []):
            claimed.setdefault(str(rel), sid)
    return {"claimed": claimed, "active": sorted(active)}


def _git_dirty(root):
    """(repo-relative dirty/untracked paths, None), or (None, reason) on failure.

    A TUPLE because the two failure modes are not the same event and used to be
    reported as one. Everything funnelled into `return None`, which `decide` read
    as "not a git repo" and answered with silence - so a repository big enough to
    blow the timeout ran with this guard permanently off and was never told. The
    reasons are `"timeout"` (say so, once), `"git-error"` and `"no-repo"`.

    `subprocess` is imported here rather than at module scope: this hook runs on
    the Edit matcher too, and that lane returns at "record" without ever reaching
    git, so the ~6.6 ms was bought for nothing on the more frequent of its two
    lanes.
    """
    import subprocess
    try:
        out = subprocess.run(
            GIT_STATUS_ARGV, cwd=str(root),
            capture_output=True, timeout=5, text=True)
        if out.returncode != 0:
            return (None, "no-repo")
        files = []
        for line in out.stdout.splitlines():
            if len(line) < 4:
                continue
            path = line[3:].strip()
            if " -> " in path:  # rename: "R  old -> new"
                path = path.split(" -> ", 1)[1]
            files.append(path.strip('"').replace("\\", "/"))
        return (files, None)
    except subprocess.TimeoutExpired:
        return (None, "timeout")
    except Exception:
        return (None, "git-error")


# --- decision -----------------------------------------------------------------
def decide(data, *, cfg=None, state_dir=None, dirty=None):
    """Returns ("record"|"warn"|"silent", detail). `dirty` is injectable for
    --selftest; real runs read `git status --porcelain`."""
    tool = data.get("tool_name", "")
    if tool not in _EDIT_TOOLS + ("Bash",):
        return ("silent", "unknown tool")

    root = _config.repo_root(data)
    cfg = cfg if cfg is not None else _config.load(root)
    if not _config.bash_write_check_enabled(cfg):
        return ("silent", "disabled")

    sd = state_dir if state_dir is not None else _config.state_dir(root, cfg)
    session_id = str(data.get("session_id", "") or "no-session")
    state = _load_state(sd, session_id)

    # branch 1: remember files edited through the gated tools
    if tool in _EDIT_TOOLS:
        ti = data.get("tool_input", {}) or {}
        fp = ti.get("file_path", "") or ti.get("notebook_path", "")
        if not fp:
            return ("silent", "no file_path")
        # OUT OF THE WATCHED TREE IS NOT A FILE THIS GUARD HAS AN OPINION ABOUT.
        # `rel_path` is os.path.relpath, so a target outside the project comes
        # back as `../../../private/tmp/probe.py`, and appending THAT to
        # `toolEdited` recorded a path no verdict below can ever read: every rel
        # in this state file is matched against a `git status` line from the
        # watched tree, and an escaped rel matches none of them (4e81429 named
        # it and left it, as dead state with no output behind it).
        #
        # It goes anyway, because dead is not the standard: this plugin manages
        # and references only the consuming repository, so a path outside it is
        # not kept in memory, not written to disk, and not quoted back in the
        # verdict's reason. The test before `rel_path` rather than after is the
        # same rule one step earlier - the escaped spelling is never built.
        #
        # `within_root` is _config's, shared with require-plan / remind-tdd /
        # guard-secrets-read, so "inside this repository" has one answer across
        # the hooks SECURITY.md promises will agree.
        if not _config.within_root(root, fp):
            return ("silent", "outside the watched tree")
        rel = _config.rel_path(root, fp)
        if rel not in state["toolEdited"]:
            state["toolEdited"].append(rel)
            _save_state(sd, session_id, state)
        return ("record", "tool-edited: %s" % rel)

    # branch 2: Bash — diff the working tree against what we last saw.
    # Run git in the configured gitRoot (subdir-aware) and translate the
    # gitRoot-relative paths back to project-relative to match everything else.
    #
    # THE LAUNCH IS NOTED BEFORE ANYTHING ELSE IN THIS BRANCH, and before any early
    # return. A detached job that could write must be on the record even when this
    # pass goes on to say nothing — git unusable, a baseline seed, a read-only
    # command — because what it explains is a LATER pass's dirt, not this one's.
    now = _now()
    if record_background_launch(state, data.get("tool_input") or {}, now):
        _save_state(sd, session_id, state)

    reason = None
    if dirty is None:
        dirty, reason = _git_dirty(_config.git_root_dir(root, cfg))
    if dirty is None:
        if reason == "timeout" and not state["gitTimeout"]:
            state["gitTimeout"] = True
            _save_state(sd, session_id, state)
            return ("warn", TIMEOUT_TEMPLATE % _GIT_TIMEOUT_SECONDS)
        return ("silent", "git unusable (%s)" % (reason or "no-repo"))
    prefix = _config.git_root_rel(cfg)
    if prefix:
        dirty = [prefix + "/" + p for p in dirty]

    # A2 (v0.36): the FIRST Bash pass of a session cannot know which dirty paths
    # existed before its command ran — PostToolUse only ever sees the after-state.
    # It used to attribute the WHOLE pre-existing dirty set to that command (live
    # find: a real repo's standing dirt, blamed on the session's first shell
    # call). So the first pass seeds the baseline: everything already dirty is
    # recorded as seen, silently, and only dirt appearing AFTER the baseline is
    # attributed. Accepted blind spot: a source write made by the very first Bash
    # command of a session lands inside the baseline unwarned — the alternative
    # blames every session for its predecessors' leftovers, which teaches people
    # to ignore the guard. A flag rather than "state file exists": the edit
    # branch above creates the file too, and an Edit-first session must not lose
    # its baseline pass.
    if not state.get("baselined"):
        state["baselined"] = True
        state["seenDirty"] = sorted(set(state["seenDirty"]) | set(dirty))
        _save_state(sd, session_id, state)
        return ("silent", "baseline seeded: %d pre-existing dirty path(s)"
                % len(dirty))

    # F-P-24: a command that cannot write is not the author of anything new.
    #
    # The new dirt is still ABSORBED into seenDirty rather than left pending: it
    # came from outside this session (another agent in the same checkout, an editor,
    # a build), and holding it back would only move the false accusation onto the
    # next command that happens to be a writer. Blaming nobody is the correct
    # answer, and it is the same reasoning the plugin already applies to its own
    # journal appends through the `pluginWrote` sidecar.
    #
    # This only ever REMOVES an attribution, and only where the command is provably
    # read-only. Anything unrecognised is watched exactly as before, so the guard
    # cannot be talked out of a real write by a spelling it has not seen.
    if _command_is_read_only((data.get("tool_input", {}) or {}).get("command")):
        absorbed = [f for f in dirty if f not in state["seenDirty"]]
        state["seenDirty"] = sorted(set(state["seenDirty"]) | set(dirty))
        _save_state(sd, session_id, state)
        return ("silent", "read-only command: %d path(s) appeared but not from "
                          "this call" % (len(absorbed),))

    # F84: THE TREE THE COMMAND RAN IN IS NOT THE TREE THIS GUARD WATCHES, so
    # nothing seen here belongs to it. `_config.repo_root` answers where the config
    # lives and CLAUDE_PROJECT_DIR wins there on purpose - a worktree should not
    # need its own copy of the project's config - but it is the wrong answer to
    # "which tree did this command touch", and an agent working inside a worktree is
    # where the two came apart. Reported rather than swallowed: a guard that goes
    # quiet in a tree looks exactly like a guard that found nothing in it.
    #
    # The dirt is ABSORBED, for the reason the read-only branch above absorbs it: it
    # came from outside this session, and holding it back would only move the false
    # accusation onto the next command that happens to be a writer.
    #
    # NO RECORD HERE LEARNS A TREE, and that is a decision rather than an omission.
    # Every rel in this state file - seenDirty, toolEdited, warned - and every rel in
    # a sibling session's file is a path in the watched tree, because every session
    # sharing this stateDir resolves the same project directory. One path space
    # describing one tree is what lets `_other_sessions` subtract a peer's claim from
    # this tree's dirt at all (9b45c54), and it is why the sidecar `journal-writes`
    # writes is found where this hook looks for it (F-F3). Measuring a second tree
    # here would put two path spaces in one file and make a tree field mandatory on
    # records that have none - after which an old record is AMBIGUOUS rather than
    # wrong, which is worse. So the second tree is declined, not half-measured.
    tree = _config.command_tree(data, root, cfg)
    if not tree["watched"]:
        state["seenDirty"] = sorted(set(state["seenDirty"]) | set(dirty))
        said = list(state.get("otherTrees") or [])
        if tree["tree"] in said:
            _save_state(sd, session_id, state)
            return ("silent", "command ran in another working tree (%s), already "
                              "said this session" % tree["tree"])
        said.append(tree["tree"])
        state["otherTrees"] = said
        _save_state(sd, session_id, state)
        return ("warn", OTHER_TREE_TEMPLATE % (tree["tree"], tree["basis"],
                                               tree["watching"]))

    # Read before this pass overwrites the file: it is the moment this session
    # last looked at the tree, and therefore the far end of the window in which
    # everything below became dirty.
    since = _state_mtime(sd, session_id)

    new = [f for f in dirty if f not in state["seenDirty"]]
    state["seenDirty"] = sorted(set(state["seenDirty"]) | set(dirty))

    manifest_rel = cfg.get("manifestPath") or _config.DEFAULTS["manifestPath"]
    exempt = cfg.get("exemptGlobs") or _config.DEFAULTS["exemptGlobs"]
    exts = _config.source_exts(cfg)
    plugin_wrote = _plugin_wrote(sd, session_id)
    in_prog = None
    plan_mode = None
    others = None
    suspicious = []
    attributed = []
    locked = []
    journalled = []
    for rel in new:
        if rel in state["toolEdited"] or rel in state["warned"]:
            continue
        # F-F3: the plugin's OWN journal appends (the journal-writes hook) put
        # the journal file into git status too. Skip exactly the files the
        # sidecar names, BEFORE the in_journal check -- or the plugin's own row
        # would be reported as a shell write into the audit trail on the next
        # Bash command. The file still entered seenDirty above, so it is not
        # rediscovered as new on the pass after this one.
        if rel in plugin_wrote:
            continue
        # Checked before the exempt globs: the journal lives beside the manifest,
        # so `docs/audit/**` — which is exempt from the plan gate on purpose —
        # would otherwise swallow a write into the audit trail without a word.
        if _config.in_journal(root, cfg, rel):
            journalled.append(rel)
            continue
        # A shell write to a manifest path is out of the PLAN gate's scope (.json
        # is not a source extension) but squarely inside the LOCK's. require-plan
        # denies that write when it arrives through Edit; through `sed -i` it
        # arrives here, after the fact, where the only honest thing left is to say
        # so. This hook exists precisely to cover the residual of bypass class 1.
        if rel == manifest_rel or _config.governing_lock(manifest_rel, rel):
            conflict = _config.manifest_lock_conflict(
                root, cfg, manifest_rel, rel, session_id)
            if conflict and conflict["live"]:
                locked.append((rel, conflict))
            continue
        if rel == manifest_rel + ".lock":
            continue
        if _config.matches_exempt(rel, exempt):
            continue
        if not any(rel.lower().endswith(x) for x in exts):
            continue
        # F52. THE PLAN-COVERAGE CLASS IS GRADED, and only this class: the journal
        # and lock classes above bind their claim to evidence of their own and mean
        # the same thing in a repo with no plan. This one does not. `in_progress_
        # files` returns an empty set both for "no manifest" and for "a manifest
        # with nothing running" — its own docstring in `_config` says so — so
        # without asking `manifest_state` the guard reads a repo that never opted
        # in as a repo where nothing is covered, and reports every shell write in
        # it. `plan_gate_mode` is the resolver `require-plan.py` was graded with
        # and this hook never called; its docstring is the argument: "in a repo
        # with no manifest there is no plan, so there is nothing to enforce."
        #
        # Resolved lazily and once, like `in_prog` beside it — the answer cannot
        # change inside one pass, and a session in a plan-less repo should not pay
        # to be told nothing.
        if plan_mode is None:
            plan_mode = _config.plan_gate_mode(
                cfg, _config.manifest_state(root, manifest_rel))
        if plan_mode == "observe":
            continue
        if in_prog is None:
            in_prog = _config.in_progress_files(root, manifest_rel)
        if rel in in_prog or any(
                rel.startswith(f) for f in in_prog if f.endswith("/")):
            continue
        # The last question before an accusation, and the one this hook never
        # asked: did somebody ELSE write this? Read lazily, so a session alone in
        # a tree never pays for the answer. Only the plan-coverage class is
        # routed through it — the journal and lock classes report a FILE whose
        # state changed rather than an author, and each already binds its claim
        # to evidence of its own (the plugin's sidecar; the lock's sessionId).
        if others is None:
            others = _other_sessions(sd, session_id, since)
        owner = others["claimed"].get(rel)
        if owner:
            attributed.append((rel, owner))
            continue
        suspicious.append(rel)

    # Every class that fired gets said, rather than the first one winning: a
    # command that wrote into a locked shard AND into the journal did two separate
    # things, and reporting one of them would leave the other to be found later by
    # someone with no idea what caused it.
    parts = []
    if locked:
        state["warned"].extend(r for r, _ in locked)
        parts.append(LOCKED_TEMPLATE % "; ".join(
            "%s (%s lock, held by %s — %s)" % (r, c["lock"], c["holder"], c["basis"])
            for r, c in locked))
    if journalled:
        state["warned"].extend(journalled)
        parts.append(JOURNAL_TEMPLATE % ", ".join(journalled))
    if suspicious:
        state["warned"].extend(suspicious)
        # BOTH KINDS OF OTHER-AUTHOR, joined rather than ranked. A peer session and
        # this session's own background job are independent explanations and can be
        # true at once; picking one would drop evidence the reader needs to tell
        # which it was.
        active = (others or {}).get("active") or []
        clauses = []
        # THE THIRD KIND OF OTHER-AUTHOR, and the one the payload hides. The two
        # below name somebody who could have written these paths; this one says
        # the command cannot be placed in this tree at all, so nobody has been
        # named yet. It goes first because it is about the command in hand.
        moved = directory_change_basis(
            (data.get("tool_input") or {}).get("command"), data.get("cwd"),
            tree["watching"])
        if moved:
            clauses.append(moved)
        if active:
            clauses.append("session(s) %s were writing in this checkout during the "
                           "same window, and nothing on disk names an author for "
                           "these paths" % (", ".join(active),))
        bg = background_basis(state, now)
        if bg:
            clauses.append(bg)
        if clauses:
            parts.append(UNPROVEN_TEMPLATE % (", ".join(suspicious),
                                              "; and ".join(clauses)))
        else:
            parts.append(WARN_TEMPLATE % ", ".join(suspicious))

    _save_state(sd, session_id, state)
    if parts:
        return ("warn", "\n".join(parts))
    if attributed:
        return ("silent", "attributed to another session: %s" % "; ".join(
            "%s (%s)" % (rel, who) for rel, who in attributed))
    return ("silent", "no unplanned source writes")


# --- cli ----------------------------------------------------------------------
def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    try:
        verdict, detail = decide(data)
        if verdict == "warn":
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": detail,
                }
            }))
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        # Answered rather than fallen through to main(), which would block on stdin
        # waiting for a hook payload that is never coming. It deliberately does NOT
        # print the `N/M cases passed` contract - that string is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("guard-bash-writes.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_guard_bash_writes.py - run that file instead.")
        sys.exit(0)
    main()
