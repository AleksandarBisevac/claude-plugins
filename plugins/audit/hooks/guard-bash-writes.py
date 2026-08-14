#!/usr/bin/env python3
"""
PostToolUse watcher (matcher: Bash|Edit|Write|MultiEdit|NotebookEdit) — the
"complete control" for shell writes that PreToolUse text inspection cannot
decide (SECURITY.md bypass class #1; upstream anthropics/claude-code#29709:
heredocs piped into interpreters, obfuscated redirects, etc.).

Two branches by tool_name:
  Edit/Write/MultiEdit/NotebookEdit → RECORD the file as tool-edited (those
      files went through guard-edits + require-plan already).
  Bash → diff `git status --porcelain` (run in the configured `gitRoot`, so it
      works when the git repo lives in a subdirectory) against the session's
      last-seen dirty set. Dirty paths are translated back to project-relative
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

Run `python3 guard-bash-writes.py --selftest` to exercise the decision core.
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
# The k1 selftest drives the REAL writer, so a drift here goes red.
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


# --- selftest -----------------------------------------------------------------
def _selftest() -> int:
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="bash-writes-selftest-"))
    sd = tmp / "state"
    sd.mkdir(parents=True, exist_ok=True)
    cfg = _config._deep_merge(_config.DEFAULTS, {})
    # Pin repo_root regardless of the caller's session env (it checks
    # CLAUDE_PROJECT_DIR before stdin cwd).
    prev_env = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = str(tmp)

    results = []

    def payload(tool, *, sid, file_path=None, command="x"):
        ti = {"command": command} if tool == "Bash" else {"file_path": file_path}
        return {"tool_name": tool, "tool_input": ti, "session_id": sid,
                "cwd": str(tmp)}

    def check(name, expected, data, *, dirty=None, use_cfg=None):
        try:
            verdict, _ = decide(data, cfg=use_cfg or cfg, state_dir=sd,
                                dirty=dirty)
        except Exception as exc:  # pragma: no cover
            verdict = "EXC:%s" % exc
        ok = verdict == expected
        results.append(ok)
        print("%s %s (expected %s, got %s)"
              % ("PASS" if ok else "FAIL", name, expected, verdict))

    def seed(sid, *, use_cfg=None, state_dir=None, cwd=None, dirty=()):
        """Run the session's baseline pass (A2) with a known dirty set, so each
        case below tests ATTRIBUTION of new dirt, not the baseline itself
        (which the (m) group pins)."""
        data = payload("Bash", sid=sid)
        if cwd is not None:
            data["cwd"] = str(cwd)
        decide(data, cfg=use_cfg or cfg,
               state_dir=state_dir if state_dir is not None else sd,
               dirty=list(dirty))

    # (a) a bash-only new source file → warn once, then stays silent
    s = "bw-a"
    seed(s)
    check("a1 new dirty source file warns", "warn",
          payload("Bash", sid=s), dirty=["src/shell.ts"])
    check("a2 same file again is silent", "silent",
          payload("Bash", sid=s), dirty=["src/shell.ts"])

    # (b) tool-edited files never warn (they went through the gates)
    s = "bw-b"
    seed(s)
    check("b1 Edit records", "record",
          payload("Edit", sid=s, file_path="src/tool.ts"))
    check("b2 dirty tool-edited file is silent", "silent",
          payload("Bash", sid=s), dirty=["src/tool.ts"])

    # (c) exempt / non-source / manifest / lock → silent
    s = "bw-c"
    for _sid in (s, "bw-c2", "bw-c3", "bw-c4"):
        seed(_sid)
    check("c1 exempt .md silent", "silent",
          payload("Bash", sid=s), dirty=["NOTES.md"])
    check("c2 non-source ext silent", "silent",
          payload("Bash", sid="bw-c2"), dirty=["out.log"])
    check("c3 test file silent (exempt glob)", "silent",
          payload("Bash", sid="bw-c3"), dirty=["src/a.spec.ts"])
    check("c4 manifest + lock silent", "silent",
          payload("Bash", sid="bw-c4"),
          dirty=["docs/audit/audit-plan.json",
                 "docs/audit/audit-plan.json.lock"])

    # (d) in_progress-covered file → silent
    manifest_dir = tmp / "docs" / "audit"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "audit-plan.json").write_text(json.dumps({
        "meta": {"version": 2},
        "phases": [{"id": "P0", "title": "p", "status": "in_progress", "tasks": [
            {"id": "P0.1", "title": "t", "status": "in_progress",
             "files": ["src/covered/mod.ts"], "tests": {"mode": "gate-only"}},
        ]}],
    }), encoding="utf-8")
    seed("bw-d")
    check("d1 in_progress-covered file silent", "silent",
          payload("Bash", sid="bw-d"), dirty=["src/covered/mod.ts"])

    # (e) two new files → one warn naming both; disabled config → silent
    s = "bw-e"
    seed(s)
    try:
        verdict, detail = decide(payload("Bash", sid=s), cfg=cfg, state_dir=sd,
                                 dirty=["src/one.py", "src/two.py"])
        ok = verdict == "warn" and "src/one.py" in detail and "src/two.py" in detail
    except Exception:
        ok = False
    results.append(ok)
    print("%s e1 one warning names every new file" % ("PASS" if ok else "FAIL"))
    cfg_off = _config._deep_merge(_config.DEFAULTS,
                                  {"bashWriteCheck": {"enabled": False}})
    check("e2 disabled config silent", "silent",
          payload("Bash", sid="bw-e2"), dirty=["src/x.ts"], use_cfg=cfg_off)

    # (m) A2 (v0.36): pre-existing dirt is the session's BASELINE, not the first
    # command's crime. On the first Bash pass of a session the guard cannot know
    # which dirty paths predate the command, so it seeds seenDirty silently and
    # only attributes dirt that appears AFTER that (live find: a real repo's
    # standing dirty files were all blamed on the session's first command).
    s = "bw-m1"
    check("m1 first pass: a pre-existing dirty source file is baseline, silent",
          "silent", payload("Bash", sid=s), dirty=["src/preexisting.ts"])
    check("m2 a NEW dirty file on a later pass is attributed and warned", "warn",
          payload("Bash", sid=s), dirty=["src/preexisting.ts", "src/fresh.ts"])
    s = "bw-m4"
    check("m4a an Edit-first session records through the edit branch", "record",
          payload("Edit", sid=s, file_path="src/tool-first.ts"))
    check("m4b ...and its first BASH pass still seeds the baseline silently - "
          "the flag lives in state, not in the state file's existence",
          "silent", payload("Bash", sid=s), dirty=["src/left-by-others.ts"])
    check("m4c ...while dirt after the baseline is still caught", "warn",
          payload("Bash", sid=s),
          dirty=["src/left-by-others.ts", "src/mine.ts"])

    # (j) the append-only journal. guard-edits REFUSES an edit tool here; a shell
    # write is the same act through the door that cannot be locked, so the only
    # honest thing left is to say it happened.
    for _sid in ("bw-j1", "bw-j4", "bw-j5"):
        seed(_sid)
    try:
        verdict, detail = decide(payload("Bash", sid="bw-j1"), cfg=cfg,
                                 state_dir=sd,
                                 dirty=["docs/audit/journal/2026-08.a.jsonl"])
        ok = verdict == "warn" and "append-only audit journal" in detail \
            and "audit-journal.py verify" in detail
    except Exception:
        ok = False
    results.append(ok)
    print("%s j1 a shell write into the journal warns, and names the command that "
          "checks the chain" % ("PASS" if ok else "FAIL"))
    # The journal lives under docs/audit/, which is EXEMPT from the plan gate on
    # purpose — so a check that ran after the exempt globs would see nothing at all.
    ok = _config.matches_exempt("docs/audit/journal/2026-08.a.jsonl",
                                _config.DEFAULTS["exemptGlobs"])
    results.append(ok)
    print("%s j2 (and it really is inside an exempt path, which is what makes the "
          "order load-bearing)" % ("PASS" if ok else "FAIL"))
    check("j3 the same file again is silent - one warning per file per session",
          "silent", payload("Bash", sid="bw-j1"),
          dirty=["docs/audit/journal/2026-08.a.jsonl"])
    # Two classes at once are two facts, and reporting one would leave the other
    # to be found later by someone with no idea what caused it.
    try:
        verdict, detail = decide(payload("Bash", sid="bw-j4"), cfg=cfg,
                                 state_dir=sd,
                                 dirty=["docs/audit/journal/2026-08.a.jsonl",
                                        "src/two-at-once.py"])
        ok = verdict == "warn" and "audit journal" in detail \
            and "src/two-at-once.py" in detail
    except Exception:
        ok = False
    results.append(ok)
    print("%s j4 a journal write and an unplanned source write are both reported"
          % ("PASS" if ok else "FAIL"))
    check("j5 a neighbour whose name merely starts the same is ordinary work",
          "silent", payload("Bash", sid="bw-j5"),
          dirty=["docs/audit/journal-notes/why.md"])

    # (k) F-F3: the plugin's OWN journal append lands in git status too, and it
    # used to be blamed on the next shell command -- journal-writes appends a
    # row at PostToolUse, the journal file goes dirty, and the next Bash pass
    # reported "That shell command wrote into the append-only audit journal"
    # about a write the plugin itself made. The fix is a sidecar with ONE
    # writer (journal-writes), read here; k1 drives the REAL writer so the two
    # sides cannot drift about where the sidecar lives.
    import importlib.util as _ilu
    _jw_spec = _ilu.spec_from_file_location(
        "journal_writes_for_k",
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "journal-writes.py"))
    _jw = _ilu.module_from_spec(_jw_spec)
    _jw_spec.loader.exec_module(_jw)
    kproj = tmp / "ff3"
    (kproj / "docs" / "audit").mkdir(parents=True, exist_ok=True)
    (kproj / "docs" / "audit" / "audit-plan.json").write_text(
        '{"meta":{"version":3}}', encoding="utf-8")
    ksd = kproj / ".claude" / "state"
    kcfg = _config._deep_merge(_config.DEFAULTS, {})
    ksid = "bw-k1"
    kdata = {"tool_name": "Edit", "session_id": ksid,
             "tool_input": {"file_path": "docs/audit/audit-plan.json",
                            "new_string": "x"},
             "cwd": str(kproj)}
    os.environ["CLAUDE_PROJECT_DIR"] = str(kproj)
    try:
        for _sid in (ksid, "bw-k2"):
            seed(_sid, use_cfg=kcfg, state_dir=ksd, cwd=kproj)
        _jmod = _config._load_journal_lib()
        _entries = _jw.post_entries(kdata, cfg=kcfg, root=str(kproj))
        _written = []
        for _e in _entries:
            _p = _jmod.append(str(kproj), _e, config=kcfg)
            if _p:
                # exactly the wiring journal-writes' main() performs after a
                # successful append; getattr so the RED run (before the
                # sidecar exists) fails the case instead of crashing the suite
                getattr(_jw, "record_plugin_write",
                        lambda *a: None)(str(kproj), kcfg, kdata, _p)
                _written.append(_p)
        _jrel = (_config.rel_path(kproj, _written[0]) if _written
                 else "append-failed")
        _kpayload = {"tool_name": "Bash", "tool_input": {"command": "x"},
                     "session_id": ksid, "cwd": str(kproj)}
        try:
            _v, _ = decide(_kpayload, cfg=kcfg, state_dir=ksd, dirty=[_jrel])
        except Exception as _exc:                       # pragma: no cover
            _v = "EXC:%s" % _exc
        ok = bool(_written) and _v == "silent"
        results.append(ok)
        print("%s k1 the plugin's own journal append is SILENT on the next "
              "Bash pass - the sidecar names it, so the shell is not blamed "
              "for it (got %s for %s)" % ("PASS" if ok else "FAIL", _v, _jrel))
        # A journal write the sidecar does NOT name is still the guard's
        # business: that is the sed-shaped write the template exists for.
        _v2, _d2 = decide({"tool_name": "Bash", "tool_input": {"command": "x"},
                           "session_id": "bw-k2", "cwd": str(kproj)},
                          cfg=kcfg, state_dir=ksd, dirty=[_jrel])
        ok = _v2 == "warn" and "append-only audit journal" in _d2
        results.append(ok)
        print("%s k2 a session WITHOUT a sidecar entry still warns about the "
              "same journal file - the guard's purpose survives the fix"
              % ("PASS" if ok else "FAIL"))
        ok = "likely the plugin itself" in JOURNAL_TEMPLATE
        results.append(ok)
        print("%s k3 the journal warning tells the reader how to read a clean "
              "verify: a fresh chained row was likely the plugin itself"
              % ("PASS" if ok else "FAIL"))
    finally:
        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp)

    # (f) REAL git integration: init a repo, dirty it, no `dirty` injection
    s = "bw-f"
    gitrepo = tmp / "repo"
    (gitrepo / "src").mkdir(parents=True, exist_ok=True)
    os.environ["CLAUDE_PROJECT_DIR"] = str(gitrepo)
    try:
        subprocess.run(["git", "init", "-q"], cwd=str(gitrepo), check=True,
                       capture_output=True, timeout=10)
        # baseline pass BEFORE the shell write exists (real git, no injection)
        decide({"tool_name": "Bash", "tool_input": {"command": "x"},
                "session_id": s, "cwd": str(gitrepo)}, cfg=cfg, state_dir=sd)
        (gitrepo / "src" / "made-by-shell.go").write_text("package x\n",
                                                          encoding="utf-8")
        data = {"tool_name": "Bash", "tool_input": {"command": "x"},
                "session_id": s, "cwd": str(gitrepo)}
        verdict, detail = decide(data, cfg=cfg, state_dir=sd)
        ok = verdict == "warn" and "src/made-by-shell.go" in detail
    except Exception as exc:  # pragma: no cover
        ok = False
        print("   (git integration error: %s)" % exc)
    finally:
        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp)
    results.append(ok)
    print("%s f1 real git status detects the shell write" % ("PASS" if ok else "FAIL"))

    # (fl) A shell write to a manifest path held by another LIVE session. Through
    # Edit this is denied by require-plan; through `sed -i` it lands, and the only
    # honest thing left is to say who it landed on top of. Previously invisible
    # twice over: manifest_rel was skipped outright, and .json is not a source ext.
    import platform as _pf
    import time as _time
    lockrepo = tmp / "lockrepo"
    (lockrepo / "audit" / "phases").mkdir(parents=True, exist_ok=True)
    os.environ["CLAUDE_PROJECT_DIR"] = str(lockrepo)
    cfg_lock = _config._deep_merge(_config.DEFAULTS,
                                   {"manifestPath": "audit/plan.json"})
    try:
        subprocess.run(["git", "init", "-q"], cwd=str(lockrepo), check=True,
                       capture_output=True, timeout=10)
        lockdir = _config._load_lock_lib().lock_dir(str(lockrepo))
        os.makedirs(lockdir, exist_ok=True)
        with open(os.path.join(lockdir, "phase-P1.lock"), "w",
                  encoding="utf-8") as fh:
            json.dump({"hostname": _pf.node(), "pid": os.getpid(),
                       "sessionId": "sess-A", "note": "phase P1",
                       "startedAt": _time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                   _time.gmtime())}, fh)
        # baseline passes BEFORE the shard write exists (real git, no injection)
        for _sid in ("sess-B", "sess-B2"):
            decide({"tool_name": "Bash", "tool_input": {"command": "x"},
                    "session_id": _sid, "cwd": str(lockrepo)},
                   cfg=cfg_lock, state_dir=sd)
        (lockrepo / "audit" / "phases" / "P1.json").write_text(
            '{"id":"P1"}\n', encoding="utf-8")
        data = {"tool_name": "Bash", "tool_input": {"command": "sed -i ..."},
                "session_id": "sess-B", "cwd": str(lockrepo)}
        verdict, detail = decide(data, cfg=cfg_lock, state_dir=sd)
        ok_l = (verdict == "warn" and "audit/phases/P1.json" in detail
                and "sess-A" in detail and "ANOTHER LIVE SESSION" in detail)
        # And the same write by the HOLDER is not a warning.
        with open(os.path.join(lockdir, "phase-P1.lock"), "r+",
                  encoding="utf-8") as fh:
            info = json.load(fh)
            info["sessionId"] = "sess-B"
            fh.seek(0), fh.truncate()
            json.dump(info, fh)
        data2 = {"tool_name": "Bash", "tool_input": {"command": "sed -i ..."},
                 "session_id": "sess-B2", "cwd": str(lockrepo)}
        v2, _ = decide(data2, cfg=cfg_lock, state_dir=sd)
        ok_own = v2 == "warn"          # sess-B2 is not the holder either
        data3 = {"tool_name": "Bash", "tool_input": {"command": "sed -i ..."},
                 "session_id": "sess-B", "cwd": str(lockrepo)}
        v3, _ = decide(data3, cfg=cfg_lock, state_dir=sd)
        ok_own = ok_own and v3 == "silent"
    except Exception as exc:  # pragma: no cover
        ok_l = ok_own = False
        print("   (lock integration error: %s)" % exc)
    finally:
        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp)
    results.append(ok_l)
    print("%s fl1 a shell write onto another live session's shard is surfaced"
          % ("PASS" if ok_l else "FAIL"))
    results.append(ok_own)
    print("%s fl2 and the lock's own holder is not warned about its own write"
          % ("PASS" if ok_own else "FAIL"))

    # (g) non-git directory → silent
    check("g1 non-git dir silent", "silent",
          payload("Bash", sid="bw-g"))

    # (h) NESTED gitRoot: project dir is NOT git, git repo is in a subdir.
    # With gitRoot config the guard runs git there and reports project-relative.
    proj = tmp / "proj"
    sub = proj / "sub"
    (sub / "src").mkdir(parents=True, exist_ok=True)
    os.environ["CLAUDE_PROJECT_DIR"] = str(proj)
    cfg_nested = _config._deep_merge(_config.DEFAULTS, {"gitRoot": "sub"})
    try:
        subprocess.run(["git", "init", "-q"], cwd=str(sub), check=True,
                       capture_output=True, timeout=10)
        # baseline pass BEFORE the shell write exists (real git, no injection)
        decide({"tool_name": "Bash", "tool_input": {"command": "x"},
                "session_id": "bw-h", "cwd": str(proj)},
               cfg=cfg_nested, state_dir=sd)
        (sub / "src" / "shellmade.ts").write_text("export const x=1\n",
                                                  encoding="utf-8")
        data = {"tool_name": "Bash", "tool_input": {"command": "x"},
                "session_id": "bw-h", "cwd": str(proj)}
        verdict, detail = decide(data, cfg=cfg_nested, state_dir=sd)
        # project-relative path is gitRoot-prefixed: sub/src/shellmade.ts
        ok = verdict == "warn" and "sub/src/shellmade.ts" in detail
    except Exception as exc:  # pragma: no cover
        ok = False
        print("   (nested git integration error: %s)" % exc)
    finally:
        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp)
    results.append(ok)
    print("%s h1 nested gitRoot: git runs in subdir, path project-relative"
          % ("PASS" if ok else "FAIL"))

    if prev_env is None:
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
    else:
        os.environ["CLAUDE_PROJECT_DIR"] = prev_env

    # (i) session state lands in a self-ignoring dir
    import shutil as _sh
    tmp_i = Path(tempfile.mkdtemp(prefix="gbw-ignore-"))
    try:
        _save_state(tmp_i / "state", "s-i",
                    {"toolEdited": [], "seenDirty": [], "warned": []})
        _ok_i = (tmp_i / "state" / ".gitignore").exists()
        results.append(_ok_i)
        print("%s i1 _save_state's dir carries a `*` .gitignore"
              % ("PASS" if _ok_i else "FAIL"))
    finally:
        _sh.rmtree(tmp_i, ignore_errors=True)

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    main()
