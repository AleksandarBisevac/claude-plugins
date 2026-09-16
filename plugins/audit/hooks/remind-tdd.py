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

THE NUDGE IS WORDED IN THE MODE THE TASK WAS GIVEN (`_warn_text`). Three test
disciplines are ordered by `agents/audit-executor.md`, and this hook knew one of
them: it exempted "gate-only" and said "write or update a test first (red, then
green)" to everything else — including a "regression" task, whose brief orders the
opposite order (implement the change, THEN add the tests locking the corrected
behaviour). So an executor's first source edit under a regression task drew advice
contradicting its own work order, and an agent told two things by one system does
one of them for the wrong reason. A regression task still owes tests, so silence
would be the wrong repair; REGRESSION_TEMPLATE says which order instead, and names
the task the mode came from.

Only the two policies that read the manifest can word it that way: under
"warn-always" the operator has asked for manifest coverage to be ignored, so no
task is consulted and the generic wording stands.

THIS HOOK ASKS NOTHING ABOUT WHO IS EDITING, and that is a decision rather than a
gap. `require-plan.py` branches on `_config.is_subagent` because its two audiences
have different REMEDIES - a subagent may not edit the manifest, so the line telling
it to sent it into a forbidden action. Here both audiences get the same remedy,
write the test, and the only thing that varies is the ORDER - which is a property
of the covering task, not of the writer, and is already read above. The one thing a
subagent branch could do, stay silent because the executor's brief carries its mode,
would remove the reminder from the only agent editing source under a task.

Decision order (see `decide`):
  a path OUTSIDE the consuming repository → SILENT, before anything else: the
  nudge is a claim about a file, and a scratch file in another tree is not one
  this hook has standing to make (it also used to spend the session's throttle);
  test file → RECORD it (BEFORE any warn logic — this ordering is the whole
  mechanism: the hook watches its own Edit stream to learn that tests exist);
  exempt / non-source / covered-by-task / test-already-touched / throttled →
  SILENT; otherwise → WARN (once per file, throttled per session), worded in the
  covering task's test mode on the FIRST warn of the session and as a short
  pointer back to it on every warn after - a batch touching many distinct files
  must not paste the whole paragraph once per file.

AN MCP SERVER'S WRITE TOOL IS DELIBERATELY NOT ON THIS MATCHER. The mechanism
above is "the hook watches its own Edit stream", and both halves of that stream
would be wrong from an MCP payload: a read of a test file would be RECORDED as a
test touched (silencing the nudge for the rest of the session on no evidence), and
a write with no write basis in its payload names nothing this hook could warn
about. `_config.mcp_payload` says what a write basis is and why it is deliberately
incomplete. The cost of leaving it out is one reminder, not one guard — this hook
refuses nothing and never has — so the incomplete signal is worth less here than
the false silence would cost.

State: <stateDir>/tdd-reminder-<session_id>.json
  {"testTouched": bool, "testFiles": [rel...], "warned": {rel: epoch},
   "lastWarnAt": epoch, "fullShown": bool}

Contract: ALWAYS exits 0. Any unexpected input / exception also exits 0 —
a reminder must never break legitimate work.

This hook carries no `--selftest` of its own any more; its cases live in
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _config  # noqa: E402

WARN_TEMPLATE = (
    "[tdd-reminder] %s was modified, but no test file has been touched in this "
    "session. If this change alters behavior, write or update a test first "
    "(red, then green). This is a non-blocking reminder; tune or disable it via "
    ".claude/audit.config.json -> tddReminder."
)

# The same reminder, in the order a `regression` task was actually ordered to work
# in. Both templates open with the same `[tdd-reminder]` tag, which is what main()
# hands to additionalContext and what a reader filters a transcript on.
REGRESSION_TEMPLATE = (
    "[tdd-reminder] %s was modified, but no test file has been touched in this "
    "session. Task %s is mode \"regression\", so the order is implement first, "
    "then add the test(s) locking the corrected behavior - do NOT write them "
    "red first. Adding none is what this is reminding you about. This is a "
    "non-blocking reminder; tune or disable it via .claude/audit.config.json "
    "-> tddReminder."
)

# Every warn after the first ONE THIS SESSION uses this instead of a template
# above. A batch that touches many distinct source files in close succession
# fires this hook once per file, and `throttleMinutes` only governs how SOON a
# new file may warn at all - a project that lowers it for tighter nudging must
# not get the whole paragraph back on every file of a wide edit, which is the
# same paragraph landing in the model's context once per file rather than once.
# The tag stays first so a transcript filter on `[tdd-reminder]` still finds it.
POINTER_TEMPLATE = (
    "[tdd-reminder] %s was modified with no test file touched yet - see this "
    "session's first tdd-reminder note above for the full explanation and how "
    "to turn it off."
)


# --- state ----------------------------------------------------------------------
def _state_file(state_dir, session_id):
    return state_dir / ("tdd-reminder-%s.json" % session_id)


def _load_state(state_dir, session_id):
    try:
        with open(_state_file(state_dir, session_id), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"testTouched": False, "testFiles": [], "warned": {}, "lastWarnAt": 0,
            "fullShown": False}


def _save_state(state_dir, session_id, state):
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


# --- the nudge's wording ----------------------------------------------------------
def regression_task(covering):
    """The id of an in_progress task covering this file whose ordered test mode is
    "regression", or None when none of them is.

    -> "P2.5" | None

    A file can be covered by more than one in_progress task, and the modes may
    differ. The FIRST regression decides, and a mixed set is deliberately not an
    error: the generic wording is the one that is wrong for a regression task, so
    when any covering task orders that mode the nudge says so.
    """
    for entry in covering or []:
        if entry.get("testsMode") == "regression":
            return entry.get("taskId") or "?"
    return None


def _warn_text(rel, covering):
    """The reminder for `rel`, worded in the mode its covering task was given.

    `covering` is the in_progress-task list for this file - EMPTY when no task
    covers it and empty as well under inProgressPolicy "warn-always", which asks
    for the manifest to be ignored. Both produce the generic wording, which is the
    right one: with no task there is no ordered mode, and with the manifest
    deliberately ignored there is nothing this hook is entitled to read a mode out
    of.
    """
    task_id = regression_task(covering)
    if task_id is not None:
        return REGRESSION_TEMPLATE % (rel, task_id)
    return WARN_TEMPLATE % rel


# --- core decision ----------------------------------------------------------------
def decide(data, *, cfg=None, state_dir=None, now=None):
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

    # 0. Outside the consuming repository. This hook decides nothing, so the
    #    defect here is not a refusal but a CLAIM: `rel` is os.path.relpath, so
    #    a helper written to the system temp directory arrived as
    #    `../../../private/tmp/probe.py`, matched `**/*.py` like any other
    #    source file, and the user was told to write a test for it. Worse in the
    #    other direction than it looks - the warn also spent the session's
    #    throttle, so the next in-repo edit that DID deserve a reminder was
    #    silenced by a scratch file in another tree.
    #
    #    Decided before the test-file branch, not after: an out-of-repo file
    #    named like a test must not record `testTouched` either, or a stray
    #    `/tmp/x.test.ts` would satisfy the reminder for the whole session.
    if not _config.within_root(root, file_path):
        return ("silent",
                "outside the repository at %s: %s" % (root, file_path))

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

    # 4. Interplay with the audit pipeline (in_progress task coverage). The list
    #    outlives this step: step 7 words the nudge in the covering task's mode
    #    (_warn_text), so the same read answers both "say nothing?" and "say it
    #    how?". It stays EMPTY under "warn-always" - that policy asks for the
    #    manifest to be ignored, and reading it anyway to pick a wording would be
    #    the setting half-honoured.
    covering = []
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

    # 7. Warn. The full paragraph rides ONCE per session, on whichever file
    #    triggers it first; every later file in the same session - however many,
    #    however soon after - gets the short pointer instead. `fullShown` is
    #    orthogonal to the throttle above: the throttle decides whether a NEW
    #    file may warn at all, this decides how much text that warn costs, and a
    #    project that lowers the throttle for tighter nudging must not get the
    #    whole paragraph back on every file of a wide edit.
    state.setdefault("warned", {})[rel] = ts
    state["lastWarnAt"] = ts
    if state.get("fullShown"):
        text = POINTER_TEMPLATE % rel
    else:
        state["fullShown"] = True
        text = _warn_text(rel, covering)
    _save_state(sd, session_id, state)
    return ("warn", text)


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
        print("remind-tdd.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_remind_tdd.py - run that file instead.")
        sys.exit(0)
    main()
