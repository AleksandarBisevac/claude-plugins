#!/usr/bin/env python3
"""
PostToolUse watcher (matcher: Bash|Edit|Write|MultiEdit|NotebookEdit) — the
"complete control" for shell writes that PreToolUse text inspection cannot
decide (SECURITY.md bypass class #1; upstream anthropics/claude-code#29709:
heredocs piped into interpreters, obfuscated redirects, etc.).

Two branches by tool_name:
  Edit/Write/MultiEdit/NotebookEdit → RECORD the file as tool-edited (those
      files went through guard-edits + require-plan already).
  Bash → diff `git status --porcelain` against the session's last-seen dirty
      set. NEW dirty files that are SOURCE files, not exempt, not the
      manifest/lock, not tool-edited, and not covered by an in_progress task
      → inject a NON-blocking additionalContext warning (once per file per
      session). PostToolUse cannot undo the write — but the model gets told,
      in-band, that it just sidestepped the plan gate.

State: <stateDir>/bash-writes-<session_id>.json
  {"toolEdited": [rel...], "seenDirty": [rel...], "warned": [rel...]}

Config: `.claude/audit.config.json` → bashWriteCheck.enabled (default true).
Non-git repos, git errors/timeouts (5 s) → silent. ALWAYS exits 0.

Run `python3 guard-bash-writes.py --selftest` to exercise the decision core.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _config  # noqa: E402

WARN_TEMPLATE = (
    "[bash-write-guard] That shell command modified source file(s) with no "
    "plan coverage: %s. Plan-first applies to shell writes too — add the "
    "file(s) to an in_progress task in the audit manifest, or use the "
    "Edit/Write tools (which the plan gate reviews). This is a non-blocking "
    "notice; the change itself was NOT reverted."
)

_EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def _state_file(state_dir: Path, session_id: str) -> Path:
    return state_dir / ("bash-writes-%s.json" % session_id)


def _load_state(state_dir: Path, session_id: str) -> dict:
    try:
        with open(_state_file(state_dir, session_id), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return {"toolEdited": list(data.get("toolEdited") or []),
                    "seenDirty": list(data.get("seenDirty") or []),
                    "warned": list(data.get("warned") or [])}
    except Exception:
        pass
    return {"toolEdited": [], "seenDirty": [], "warned": []}


def _save_state(state_dir: Path, session_id: str, state: dict) -> None:
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        with open(_state_file(state_dir, session_id), "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except Exception:
        pass


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

    # branch 2: Bash — diff the working tree against what we last saw
    if dirty is None:
        dirty = _git_dirty(root)
    if dirty is None:
        return ("silent", "not a git repo / git unusable")

    new = [f for f in dirty if f not in state["seenDirty"]]
    state["seenDirty"] = sorted(set(state["seenDirty"]) | set(dirty))

    manifest_rel = cfg.get("manifestPath") or _config.DEFAULTS["manifestPath"]
    exempt = cfg.get("exemptGlobs") or _config.DEFAULTS["exemptGlobs"]
    exts = _config.source_exts(cfg)
    in_prog = None
    suspicious = []
    for rel in new:
        if rel in state["toolEdited"] or rel in state["warned"]:
            continue
        if rel == manifest_rel or rel == manifest_rel + ".lock":
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

    if suspicious:
        state["warned"].extend(suspicious)
        _save_state(sd, session_id, state)
        return ("warn", WARN_TEMPLATE % ", ".join(suspicious))

    _save_state(sd, session_id, state)
    return ("silent", "no unplanned source writes")


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

    # (a) a bash-only new source file → warn once, then stays silent
    s = "bw-a"
    check("a1 new dirty source file warns", "warn",
          payload("Bash", sid=s), dirty=["src/shell.ts"])
    check("a2 same file again is silent", "silent",
          payload("Bash", sid=s), dirty=["src/shell.ts"])

    # (b) tool-edited files never warn (they went through the gates)
    s = "bw-b"
    check("b1 Edit records", "record",
          payload("Edit", sid=s, file_path="src/tool.ts"))
    check("b2 dirty tool-edited file is silent", "silent",
          payload("Bash", sid=s), dirty=["src/tool.ts"])

    # (c) exempt / non-source / manifest / lock → silent
    s = "bw-c"
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
    check("d1 in_progress-covered file silent", "silent",
          payload("Bash", sid="bw-d"), dirty=["src/covered/mod.ts"])

    # (e) two new files → one warn naming both; disabled config → silent
    s = "bw-e"
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

    # (f) REAL git integration: init a repo, dirty it, no `dirty` injection
    s = "bw-f"
    gitrepo = tmp / "repo"
    (gitrepo / "src").mkdir(parents=True, exist_ok=True)
    os.environ["CLAUDE_PROJECT_DIR"] = str(gitrepo)
    try:
        subprocess.run(["git", "init", "-q"], cwd=str(gitrepo), check=True,
                       capture_output=True, timeout=10)
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

    # (g) non-git directory → silent
    check("g1 non-git dir silent", "silent",
          payload("Bash", sid="bw-g"))

    if prev_env is None:
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
    else:
        os.environ["CLAUDE_PROJECT_DIR"] = prev_env

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    main()
