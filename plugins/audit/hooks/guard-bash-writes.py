#!/usr/bin/env python3
"""
PostToolUse watcher (matcher: Bash|Edit|Write|MultiEdit|NotebookEdit) — the
"complete control" for shell writes that PreToolUse text inspection cannot
decide (SECURITY.md bypass class #1; upstream anthropics/claude-code#29709:
heredocs piped into interpreters, obfuscated redirects, etc.).

Two branches by tool_name:
  Edit/Write/MultiEdit/NotebookEdit → RECORD the file as tool-edited (those
      files went through guard-edits + require-plan already).
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
   "baselined": bool}
  `baselined` marks that the session's FIRST Bash pass has seeded seenDirty
  with the tree's pre-existing dirt (silently) — only dirt appearing after
  that baseline is ever attributed to a shell command.
  Written for THIS session and read for every other one in the same stateDir
  (`_other_sessions`), which is what makes a second writer visible at all. The
  file's mtime is its own timestamp: no field had to be added for the window.
Read-only sidecar: <stateDir>/bash-writes-plugin-<sid>.json {"pluginWrote": [rel]}
  — journal files the plugin ITSELF appended to (written by journal-writes.py,
  the single writer; hooks on one event run in parallel). Those rels are
  skipped before the journal check, so the plugin's own append is never
  blamed on the next shell command (F-F3).

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

# The same finding as WARN_TEMPLATE with the authorship claim removed, because
# the evidence for that claim is missing: another session was writing in this
# checkout inside the same window, and nothing on disk names an author for these
# paths. Still said rather than swallowed — an unplanned source write is worth a
# line whoever made it — but what it reports is what IS established, which is the
# only version of the line a reader can act on. Telling somebody they wrote a
# file they did not is how a guard teaches people to route around it.
UNPROVEN_TEMPLATE = (
    "[bash-write-guard] Source file(s) with no plan coverage became dirty while "
    "that shell command ran: %s. This guard CANNOT say the command wrote them: "
    "session(s) %s were writing in this checkout during the same window, and "
    "nothing on disk names an author for these paths. What is established: the "
    "file(s) were clean at this session's previous look and are dirty now, and "
    "no in_progress task covers them. If the change is yours, put the file(s) on "
    "an in_progress task or use the Edit/Write tools (which the plan gate "
    "reviews); if it is not, it belongs to the other session. This is a "
    "non-blocking notice; nothing was reverted."
)

_EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")

# Commands that cannot change a file, whatever their arguments. An ALLOWLIST, not a
# list of writers: a writer this file has never heard of must keep being watched, so
# anything unrecognised stays attributable. `sed` and `find` are here because they
# are overwhelmingly used to read, and the flag check below removes the spellings
# that write.
_READ_ONLY_CMDS = frozenset((
    "git", "grep", "rg", "ag", "cat", "head", "tail", "sed", "awk", "cut", "sort",
    "uniq", "wc", "tr", "jq", "find", "ls", "stat", "file", "basename", "dirname",
    "echo", "printf", "pwd", "true", "false", "test", "which", "type", "env",
    "date", "du", "df", "nl", "column", "comm", "diff", "cmp", "shasum", "md5sum",
    "xxd", "od", "realpath", "readlink", "seq", "yes", "tee",
))
# Sub-commands of `git` that write. `git` itself is on the list above because
# `git status`/`log`/`diff` are the most common reads in any session.
_GIT_WRITES = frozenset((
    "add", "am", "apply", "branch", "checkout", "cherry-pick", "clean", "clone",
    "commit", "fetch", "gc", "init", "merge", "mv", "pull", "push", "rebase",
    "remote", "reset", "restore", "rm", "stash", "submodule", "switch", "tag",
    "worktree", "config", "update-index", "update-ref", "notes", "replace",
))
# Flags that turn a reader into a writer.
_WRITE_FLAGS = frozenset(("-i", "--in-place", "-delete"))
# `-exec` and its relatives are NOT among them, though they were. They run
# another command, and the only honest question is what THAT command is:
# `find . -name '*.py' -exec cat {} +` is a read, and calling it a write is how
# the most ordinary sweep in this repo got blamed for another session's file.
_EXEC_FLAGS = frozenset(("-exec", "-execdir", "-ok", "-okdir"))
# find ends an -exec clause with `;` or `+`. The `;` is written `\;`, and by the
# time this runs the segment splitter below has already eaten the `;` as a
# separator — so a lone trailing backslash is an ending too.
_EXEC_END = frozenset((";", "\\;", "+", "\\"))
# A redirect to /dev/null writes nothing, whatever the descriptor. `2>/dev/null`
# is the most ordinary read idiom there is, and the blanket `>` scan below read
# it as hostile — so a command that discards stderr could not be proven to read,
# and inherited the tree's dirt. The lookahead is what separates `/dev/null`
# from `/dev/null.bak`.
_DEVNULL_REDIRECT = re.compile(r"[0-9]*>>?\s*/dev/null(?=\s|$)")


def _exec_clauses(words):
    """The argv of every `-exec`/`-ok` clause in a find command.

    Each is judged by `_command_is_read_only` in turn, so `-exec` costs a proof
    of the inner command rather than acting as a blanket write flag. A clause
    with no command comes back empty, and an empty command proves nothing —
    which is the answer that keeps a malformed find on the watched side.
    """
    clauses, i = [], 0
    while i < len(words):
        if words[i] not in _EXEC_FLAGS:
            i += 1
            continue
        i += 1
        argv = []
        while i < len(words) and words[i] not in _EXEC_END:
            argv.append(words[i])
            i += 1
        clauses.append(argv)
    return clauses


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
    """
    text = (command or "").strip()
    if not text:
        return False
    # Removed BEFORE the hostile scan rather than exempted inside it: what is
    # left is then scanned in full, so a second redirect to a REAL file in the
    # same command is still there to be caught.
    text = _DEVNULL_REDIRECT.sub(" ", text)
    # Anything that can name a destination, spawn a shell, or substitute another
    # command is out of scope for a proof. `>` covers redirection wherever it
    # appears, including inside a quoted awk program.
    for hostile in (">", "<<", "`", "$(", "${", "&"):
        if hostile in text:
            return False
    segments = [seg for seg in re.split(r"&&|\|\||[|;]|\n", text)
                if seg.strip()]
    if not segments:
        return False
    for seg in segments:
        words = seg.split()
        # Leading VAR=value assignments are not the command.
        while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words = words[1:]
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
        for argv in _exec_clauses(rest):
            if not _command_is_read_only(" ".join(argv)):
                return False
        for flag in rest:
            if flag in _WRITE_FLAGS or flag.startswith("--output"):
                return False
    return True


# --- state --------------------------------------------------------------------
def _state_file(state_dir, session_id):
    return state_dir / ("bash-writes-%s.json" % session_id)


def _load_state(state_dir, session_id):
    try:
        with open(_state_file(state_dir, session_id), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return {"toolEdited": list(data.get("toolEdited") or []),
                    "seenDirty": list(data.get("seenDirty") or []),
                    "warned": list(data.get("warned") or []),
                    "baselined": bool(data.get("baselined")),
                    "gitTimeout": bool(data.get("gitTimeout"))}
    except Exception:
        pass
    return {"toolEdited": [], "seenDirty": [], "warned": [], "baselined": False,
            "gitTimeout": False}


def _save_state(state_dir, session_id, state):
    try:
        _config.ensure_local_dir(state_dir)
        with open(_state_file(state_dir, session_id), "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except Exception:
        pass


def _plugin_wrote(state_dir, session_id):
    """Journal files THIS session's own plugin hooks appended to (F-F3).

    Written by journal-writes.py after each successful append, as
    `<stateDir>/bash-writes-plugin-<sid>.json` `{"pluginWrote": [rel, ...]}`.
    Read-only here, and that is load-bearing: hooks registered on the same
    event run in PARALLEL, so the sidecar has exactly one writer (the hook
    that made the journal write) and this one only ever looks. Empty set on
    any miss -- a missing sidecar means nothing was appended by the plugin."""
    try:
        sid = _SAFE_SID.sub("-", str(session_id or "")).strip("-.")
        sid = (sid or "no-session")[:40]
        with open(state_dir / ("bash-writes-plugin-%s.json" % sid),
                  "r", encoding="utf-8") as fh:
            obj = json.load(fh)
        wrote = obj.get("pluginWrote") if isinstance(obj, dict) else None
        return {str(x) for x in wrote} if isinstance(wrote, list) else set()
    except Exception:
        return set()


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
        rel = _config.rel_path(root, fp)
        if rel not in state["toolEdited"]:
            state["toolEdited"].append(rel)
            _save_state(sd, session_id, state)
        return ("record", "tool-edited: %s" % rel)

    # branch 2: Bash — diff the working tree against what we last saw.
    # Run git in the configured gitRoot (subdir-aware) and translate the
    # gitRoot-relative paths back to project-relative to match everything else.
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
        active = (others or {}).get("active") or []
        if active:
            parts.append(UNPROVEN_TEMPLATE % (", ".join(suspicious),
                                              ", ".join(active)))
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
