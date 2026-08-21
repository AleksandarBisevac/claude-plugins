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
      and not covered by an in_progress task → inject a NON-blocking
      additionalContext warning (once per file per session). PostToolUse cannot
      undo the write — but the model gets told, in-band, that it just
      sidestepped the plan gate.

State: <stateDir>/bash-writes-<session_id>.json
  {"toolEdited": [rel...], "seenDirty": [rel...], "warned": [rel...],
   "baselined": bool}
  `baselined` marks that the session's FIRST Bash pass has seeded seenDirty
  with the tree's pre-existing dirt (silently) — only dirt appearing after
  that baseline is ever attributed to a shell command.
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
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _config  # noqa: E402

# Mirrors journal-writes.py's `_SAFE_SID`: the sidecar read below is written by
# that hook, and the two must agree about how a session id becomes a file name.
# `test_guard_bash_writes.py`'s k1 drives the REAL writer, so a drift here goes red.
_SAFE_SID = re.compile(r"[^A-Za-z0-9._-]+")

# --- notice templates ---------------------------------------------------------
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
_WRITE_FLAGS = frozenset(("-i", "--in-place", "-delete", "-exec", "-execdir", "-ok"))


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
        for flag in rest:
            if flag in _WRITE_FLAGS or flag.startswith("--output"):
                return False
    return True


# --- state --------------------------------------------------------------------
def _state_file(state_dir: Path, session_id: str) -> Path:
    return state_dir / ("bash-writes-%s.json" % session_id)


def _load_state(state_dir: Path, session_id: str) -> dict:
    try:
        with open(_state_file(state_dir, session_id), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return {"toolEdited": list(data.get("toolEdited") or []),
                    "seenDirty": list(data.get("seenDirty") or []),
                    "warned": list(data.get("warned") or []),
                    "baselined": bool(data.get("baselined"))}
    except Exception:
        pass
    return {"toolEdited": [], "seenDirty": [], "warned": [], "baselined": False}


def _save_state(state_dir: Path, session_id: str, state: dict) -> None:
    try:
        _config.ensure_local_dir(state_dir)
        with open(_state_file(state_dir, session_id), "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except Exception:
        pass


def _plugin_wrote(state_dir: Path, session_id: str) -> set:
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


def _git_dirty(root) -> "list | None":
    """Repo-relative dirty/untracked paths, or None when git is unusable."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "-uall"], cwd=str(root),
            capture_output=True, timeout=5, text=True)
        if out.returncode != 0:
            return None
        files = []
        for line in out.stdout.splitlines():
            if len(line) < 4:
                continue
            path = line[3:].strip()
            if " -> " in path:  # rename: "R  old -> new"
                path = path.split(" -> ", 1)[1]
            files.append(path.strip('"').replace("\\", "/"))
        return files
    except Exception:
        return None


# --- decision -----------------------------------------------------------------
def decide(data: dict, *, cfg=None, state_dir: Path = None, dirty=None):
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
    if dirty is None:
        dirty = _git_dirty(_config.git_root_dir(root, cfg))
    if dirty is None:
        return ("silent", "not a git repo / git unusable")
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

    new = [f for f in dirty if f not in state["seenDirty"]]
    state["seenDirty"] = sorted(set(state["seenDirty"]) | set(dirty))

    manifest_rel = cfg.get("manifestPath") or _config.DEFAULTS["manifestPath"]
    exempt = cfg.get("exemptGlobs") or _config.DEFAULTS["exemptGlobs"]
    exts = _config.source_exts(cfg)
    plugin_wrote = _plugin_wrote(sd, session_id)
    in_prog = None
    suspicious = []
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
        parts.append(WARN_TEMPLATE % ", ".join(suspicious))

    _save_state(sd, session_id, state)
    if parts:
        return ("warn", "\n".join(parts))
    return ("silent", "no unplanned source writes")


# --- cli ----------------------------------------------------------------------
def main() -> None:
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
