#!/usr/bin/env python3
"""
PostToolUse nudge (matcher: Edit|Write|MultiEdit|NotebookEdit) — non-blocking
TDD reminder.

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
  throttleMinutes   int   — per-session minimum gap between warnings
                            (concurrent sessions throttle independently)
  inProgressPolicy  str   — interplay with the audit pipeline:
        "skip-gate-only" (default) — silent when the file is covered by an
            in_progress task whose tests.mode == "gate-only" (such tasks
            legitimately edit source without new tests)
        "skip-all"    — silent when covered by ANY in_progress task
        "warn-always" — ignore manifest coverage

Decision order (see `decide`):
  test file → RECORD it (BEFORE any warn logic — this ordering is the whole
  mechanism: the hook watches its own Edit stream to learn that tests exist);
  exempt / non-source / covered-by-task / test-already-touched / throttled →
  SILENT; otherwise → WARN (once per file, throttled per session).

State: <stateDir>/tdd-reminder-<session_id>.json
  {"testTouched": bool, "testFiles": [rel...], "warned": {rel: epoch}, "lastWarnAt": epoch}

Contract: ALWAYS exits 0. Any unexpected input / exception also exits 0 —
a reminder must never break legitimate work.

This hook carries no `--selftest` of its own any more; its 16 cases live in
`plugins/audit/tests/test_remind_tdd.py` (hyphens become underscores - a hyphenated
name is not importable). It is one of the three pilots of that migration; see
`plugins/audit/tests/_harness.py`. A test of a hook may import from `scripts/` even
though the hook itself may not - the isolation rule is about what a hook costs at
import time under a launcher, and a test has no launcher above it.
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
        # ensure_local_dir, never a bare mkdir: it also drops the `*` .gitignore
        # marker every other dir-creating writer leaves. Without it this hook was
        # the one creator of stateDir that made it unprotected, and
        # audit-doctor.check_local_artifacts then reported the plugin's own
        # directory as a hygiene finding. Never raises (hook context).
        _config.ensure_local_dir(state_dir)
        with open(_state_file(state_dir, session_id), "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except Exception:
        pass


# --- core decision ----------------------------------------------------------------
def decide(data: dict, *, cfg=None, state_dir: Path = None, now: float = None):
    """Returns ("record"|"warn"|"silent", detail). `cfg`/`state_dir`/`now` are
    injectable for --selftest; state reads/writes go through the state file."""
    tool = data.get("tool_name", "")
    if tool not in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return ("silent", "unknown tool")

    ti = data.get("tool_input", {}) or {}
    file_path = ti.get("file_path", "") or ti.get("notebook_path", "")
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

    # 4. Interplay with the audit pipeline (in_progress task coverage).
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

    # 6. Throttle: once per file, and a minimum gap between warnings WITHIN THIS
    #    SESSION. Not global — the state is loaded per session_id, so two
    #    concurrent sessions throttle independently, which is what the header
    #    docstring has always said and these two lines did not.
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


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        # Answered rather than fallen through to main(), which would block on stdin
        # waiting for a hook payload that is never coming. It deliberately does NOT
        # print the `N/M cases passed` contract - that string is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("remind-tdd.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_remind_tdd.py - run that file instead.")
        sys.exit(0)
    main()
