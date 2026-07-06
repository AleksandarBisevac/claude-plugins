#!/usr/bin/env python3
"""
PostToolUse nudge (matcher: Edit|Write|MultiEdit) — non-blocking TDD reminder.

When a SOURCE file is modified and no TEST file has been touched in the session,
this hook injects a reminder Claude sees (`hookSpecificOutput.additionalContext`)
WITHOUT blocking anything. PostToolUse is used deliberately: PreToolUse has no
non-blocking Claude-visible channel (exit 2 would block the edit), while
PostToolUse + exit 0 + additionalContext is the canonical "nudge" mechanism.

Config: `.claude/audit.config.json` → `tddReminder` (see _config.DEFAULTS):
  enabled           bool  — master switch (default true)
  sourceGlobs       [str] — files that count as source (warn candidates)
  testGlobs         [str] — files that count as tests (touching one silences
                            the reminder for the rest of the session)
  throttleMinutes   int   — global minimum gap between warnings
  inProgressPolicy  str   — interplay with the /audit pipeline:
        "skip-gate-only" (default) — silent when the file is covered by an
            in_progress task whose tests.mode == "gate-only" (such tasks
            legitimately edit source without new tests)
        "skip-all"    — silent when covered by ANY in_progress task
        "warn-always" — ignore manifest coverage

Decision order (see `decide`):
  test file → RECORD it (BEFORE any warn logic — this ordering is the whole
  mechanism: the hook watches its own Edit stream to learn that tests exist);
  exempt / non-source / covered-by-task / test-already-touched / throttled →
  SILENT; otherwise → WARN (once per file, globally throttled).

State: <stateDir>/tdd-reminder-<session_id>.json
  {"testTouched": bool, "testFiles": [rel...], "warned": {rel: epoch}, "lastWarnAt": epoch}

Contract: ALWAYS exits 0. Any unexpected input / exception also exits 0 —
a reminder must never break legitimate work.

Run `python3 remind-tdd.py --selftest` to exercise the decision core.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _config  # noqa: E402

WARN_TEMPLATE = (
    "[tdd-reminder] %s was modified, but no test file has been touched in this "
    "session. If this change alters behavior, write or update a test first "
    "(red, then green). This is a non-blocking reminder; tune or disable it via "
    ".claude/audit.config.json -> tddReminder."
)


# --- state ----------------------------------------------------------------------
def _state_file(state_dir: Path, session_id: str) -> Path:
    return state_dir / ("tdd-reminder-%s.json" % session_id)


def _load_state(state_dir: Path, session_id: str) -> dict:
    try:
        with open(_state_file(state_dir, session_id), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"testTouched": False, "testFiles": [], "warned": {}, "lastWarnAt": 0}


def _save_state(state_dir: Path, session_id: str, state: dict) -> None:
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        with open(_state_file(state_dir, session_id), "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except Exception:
        pass


# --- core decision ----------------------------------------------------------------
def decide(data: dict, *, cfg=None, state_dir: Path = None, now: float = None):
    """Returns ("record"|"warn"|"silent", detail). `cfg`/`state_dir`/`now` are
    injectable for --selftest; state reads/writes go through the state file."""
    tool = data.get("tool_name", "")
    if tool not in ("Write", "Edit", "MultiEdit"):
        return ("silent", "unknown tool")

    ti = data.get("tool_input", {}) or {}
    file_path = ti.get("file_path", "")
    if not file_path:
        return ("silent", "no file_path")

    root = _config.repo_root(data)
    cfg = cfg if cfg is not None else _config.load(root)
    tr = _config.tdd_reminder(cfg)
    if not tr.get("enabled", True):
        return ("silent", "disabled")

    sd = state_dir if state_dir is not None else _config.state_dir(root, cfg)
    session_id = str(data.get("session_id", "") or "no-session")
    ts = now if now is not None else time.time()
    rel = _config.rel_path(root, file_path)

    # 1. Test file → record the touch BEFORE any warn logic.
    if _config.matches_exempt(rel, tr.get("testGlobs")):
        state = _load_state(sd, session_id)
        state["testTouched"] = True
        if rel not in state.get("testFiles", []):
            state.setdefault("testFiles", []).append(rel)
        _save_state(sd, session_id, state)
        return ("record", "test file touched: %s" % rel)

    # 2. Exempt (docs, manifest, configs...) → not a warn candidate.
    if _config.matches_exempt(rel, cfg.get("exemptGlobs")):
        return ("silent", "exempt path: %s" % rel)

    # 3. Not a source file → nothing to say.
    if not _config.matches_exempt(rel, tr.get("sourceGlobs")):
        return ("silent", "not a source file: %s" % rel)

    # 4. Interplay with the /audit pipeline (in_progress task coverage).
    policy = tr.get("inProgressPolicy") or "skip-gate-only"
    if policy != "warn-always":
        manifest_rel = cfg.get("manifestPath") or _config.DEFAULTS["manifestPath"]
        covering = _config.in_progress_task_map(root, manifest_rel).get(rel, [])
        if policy == "skip-all" and covering:
            return ("silent", "covered by in_progress task: %s" % rel)
        if policy == "skip-gate-only" and any(
            c.get("testsMode") == "gate-only" for c in covering
        ):
            return ("silent", "covered by gate-only in_progress task: %s" % rel)

    # 5. A test file was already touched this session → discipline satisfied.
    state = _load_state(sd, session_id)
    if state.get("testTouched"):
        return ("silent", "test already touched this session")

    # 6. Throttle: once per file, and a global minimum gap between warnings.
    if rel in (state.get("warned") or {}):
        return ("silent", "already warned for %s" % rel)
    throttle_s = float(tr.get("throttleMinutes") or 0) * 60.0
    if throttle_s and (ts - float(state.get("lastWarnAt") or 0)) < throttle_s:
        return ("silent", "inside throttle window")

    # 7. Warn.
    state.setdefault("warned", {})[rel] = ts
    state["lastWarnAt"] = ts
    _save_state(sd, session_id, state)
    return ("warn", WARN_TEMPLATE % rel)


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

    tmp = Path(tempfile.mkdtemp(prefix="remind-tdd-selftest-"))
    sd = tmp / "state"
    sd.mkdir(parents=True, exist_ok=True)
    # Pin repo_root to the temp dir regardless of the caller's environment.
    prev_env = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = str(tmp)

    cfg = dict(_config.DEFAULTS)
    t0 = 1_000_000.0

    def payload(file_path, *, sid, tool="Edit"):
        return {"tool_name": tool, "tool_input": {"file_path": file_path},
                "session_id": sid, "cwd": str(tmp)}

    results = []

    def check(name, expected, data, *, use_cfg=None, now=t0):
        try:
            verdict, _ = decide(data, cfg=use_cfg or cfg, state_dir=sd, now=now)
        except Exception as exc:  # pragma: no cover
            verdict = "EXC:%s" % exc
        ok = verdict == expected
        results.append(ok)
        print("%s %s (expected %s, got %s)"
              % ("PASS" if ok else "FAIL", name, expected, verdict))

    # (a) test-file edit → record; a later source edit in that session → silent
    sess_a = "tdd-session-a"
    check("a1 test file recorded", "record",
          payload("src/foo/bar.test.ts", sid=sess_a))
    check("a2 source after test touch", "silent",
          payload("src/foo/bar.ts", sid=sess_a))

    # (b) source edit with no test touched → warn; same file again → silent
    sess_b = "tdd-session-b"
    check("b1 source without test warns", "warn",
          payload("src/foo/a.ts", sid=sess_b))
    check("b2 same file again", "silent",
          payload("src/foo/a.ts", sid=sess_b))
    check("b3 second file inside throttle window", "silent",
          payload("src/foo/b.ts", sid=sess_b), now=t0 + 60)
    check("b4 second file after throttle window", "warn",
          payload("src/foo/b.ts", sid=sess_b), now=t0 + 11 * 60)

    # (c) exempt + non-source paths → silent
    check("c1 exempt .md", "silent", payload("README.md", sid="tdd-session-c"))
    check("c2 non-source file", "silent",
          payload("assets/logo.svg", sid="tdd-session-c"))

    # (d) file covered by a gate-only in_progress task → silent (default policy)
    manifest_dir = tmp / "docs" / "audit"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "audit-plan.json").write_text(json.dumps({
        "meta": {"version": 2},
        "phases": [{"id": "P0", "title": "p", "status": "in_progress", "tasks": [
            {"id": "P0.1", "title": "t", "status": "in_progress",
             "files": ["src/covered/mod.ts"], "tests": {"mode": "gate-only"}},
        ]}],
    }), encoding="utf-8")
    check("d1 gate-only in_progress coverage", "silent",
          payload("src/covered/mod.ts", sid="tdd-session-d"))
    # warn-always ignores that coverage
    cfg_wa = dict(cfg)
    cfg_wa["tddReminder"] = dict(_config.DEFAULTS["tddReminder"],
                                 inProgressPolicy="warn-always")
    check("d2 warn-always ignores coverage", "warn",
          payload("src/covered/mod.ts", sid="tdd-session-d2"), use_cfg=cfg_wa)

    # (e) disabled → silent
    cfg_off = dict(cfg)
    cfg_off["tddReminder"] = dict(_config.DEFAULTS["tddReminder"], enabled=False)
    check("e1 disabled", "silent",
          payload("src/foo/z.ts", sid="tdd-session-e"), use_cfg=cfg_off)

    # (f) warn detail is valid additionalContext JSON when serialized
    verdict, detail = decide(payload("src/foo/f.ts", sid="tdd-session-f"),
                             cfg=cfg, state_dir=sd, now=t0)
    blob = json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse", "additionalContext": detail}})
    ok = verdict == "warn" and json.loads(blob)["hookSpecificOutput"][
        "additionalContext"].startswith("[tdd-reminder]")
    results.append(ok)
    print("%s f1 warn payload serializes" % ("PASS" if ok else "FAIL"))

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
