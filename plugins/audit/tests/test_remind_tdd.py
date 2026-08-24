#!/usr/bin/env python3
"""
The cases for `hooks/remind-tdd.py`, moved out of it - the hook shape.

The third pilot is here to settle one question: `hooks/` may import nothing from
`scripts/` (they run on every tool call, from a launcher that may not have `scripts/`
on its path, and `_deps.layer_violations()` fails the build on a static import across
that line) - so may a TEST of a hook? Yes, and this file does both: `_output.safe_stdio`
comes from `scripts/`, `_config` from `hooks/`. The isolation rule is about what a hook
costs at import time under a launcher; a test runs once, from a shell, with no tool call
behind it and no launcher above it. Nothing about the hook's own imports changes.

`remind-tdd.py` is hyphenated, so - exactly as with `test_migrate_manifest.py` - the file
name substitutes an underscore and the module comes through `_loader`. Not
`_loader.load_script`, which resolves against `scripts/`: this one is loaded by path out
of `_harness.HOOKS_DIR`.

`_expect` IS THE DOMAIN WRAPPER, AND IT STAYS HERE. `remind-tdd`'s selftest did not call
`check(label, cond)` - it called `check(name, expected, payload)` and ran `decide()` for
you. Twelve of the 48 suites wrap `check` like that, and none of the wrappers is the same
shape, which is why `_harness` unifies only the runner underneath: a wrapper that knows
what a verdict is belongs beside the cases that need one. It borrows `_harness.attempt`
for the guard the original hand-rolled (`except Exception as exc: verdict = "EXC:%s"`),
and the expected/got text that used to print on EVERY line is now a detail, printed only
when a case fails - see `_harness`'s docstring for that decision.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _config                                     # noqa: E402

M = _loader.load(os.path.join(_harness.HOOKS_DIR, "remind-tdd.py"),
                 modname="remind_tdd")


# --- cases --------------------------------------------------------------------
def _cases(check):
    import shutil as _sh_r

    tmp = Path(tempfile.mkdtemp(prefix="remind-tdd-selftest-"))
    sd = tmp / "state"
    sd.mkdir(parents=True, exist_ok=True)
    # Pin repo_root to the temp dir regardless of the caller's environment.
    prev_env = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = str(tmp)

    cfg = dict(_config.DEFAULTS)
    t0 = 1000000.0

    def payload(file_path, sid, tool="Edit"):
        ti = ({"notebook_path": file_path} if tool == "NotebookEdit"
              else {"file_path": file_path})
        return {"tool_name": tool, "tool_input": ti,
                "session_id": sid, "cwd": str(tmp)}

    def _expect(name, expected, data, use_cfg=None, now=t0):
        """One case: run `decide` on `data` and compare its verdict to `expected`.

        Guarded through `_harness.attempt` rather than left to escape: `decide`
        reads a manifest and writes state, so a broken fixture raises from inside a
        case argument - and with nothing printed until the suite ends, that used to
        take every other case's result with it."""
        ok, got = _harness.attempt(M.decide, data, cfg=use_cfg or cfg,
                                   state_dir=sd, now=now)
        verdict = got[0] if ok else got
        check(name, verdict == expected,
              "expected %s, got %s" % (expected, verdict))

    try:
        # (a) test-file edit -> record; a later source edit in that session -> silent
        sess_a = "tdd-session-a"
        _expect("a1 test file recorded", "record",
                payload("src/foo/bar.test.ts", sess_a))
        _expect("a2 source after test touch", "silent",
                payload("src/foo/bar.ts", sess_a))

        # (b) source edit with no test touched -> warn; same file again -> silent
        sess_b = "tdd-session-b"
        _expect("b1 source without test warns", "warn",
                payload("src/foo/a.ts", sess_b))
        _expect("b2 same file again", "silent",
                payload("src/foo/a.ts", sess_b))
        _expect("b3 second file inside throttle window", "silent",
                payload("src/foo/b.ts", sess_b), now=t0 + 60)
        _expect("b4 second file after throttle window", "warn",
                payload("src/foo/b.ts", sess_b), now=t0 + 11 * 60)

        # (c) exempt + non-source paths -> silent
        _expect("c1 exempt .md", "silent", payload("README.md", "tdd-session-c"))
        _expect("c2 non-source file", "silent",
                payload("assets/logo.svg", "tdd-session-c"))

        # (d) file covered by a gate-only in_progress task -> silent (default policy)
        manifest_dir = tmp / "docs" / "audit"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / "audit-plan.json").write_text(json.dumps({
            "meta": {"version": 2},
            "phases": [{"id": "P0", "title": "p", "status": "in_progress", "tasks": [
                {"id": "P0.1", "title": "t", "status": "in_progress",
                 "files": ["src/covered/mod.ts"], "tests": {"mode": "gate-only"}},
            ]}],
        }), encoding="utf-8")
        _expect("d1 gate-only in_progress coverage", "silent",
                payload("src/covered/mod.ts", "tdd-session-d"))
        # warn-always ignores that coverage
        cfg_wa = dict(cfg)
        cfg_wa["tddReminder"] = dict(_config.DEFAULTS["tddReminder"],
                                     inProgressPolicy="warn-always")
        _expect("d2 warn-always ignores coverage", "warn",
                payload("src/covered/mod.ts", "tdd-session-d2"), use_cfg=cfg_wa)

        # (e) disabled -> silent
        cfg_off = dict(cfg)
        cfg_off["tddReminder"] = dict(_config.DEFAULTS["tddReminder"], enabled=False)
        _expect("e1 disabled", "silent",
                payload("src/foo/z.ts", "tdd-session-e"), use_cfg=cfg_off)

        # (g) NotebookEdit counts as a source edit (notebook_path, *.ipynb glob)
        _expect("g1 notebook edit without test warns", "warn",
                payload("notebooks/train.ipynb", "tdd-session-g",
                        tool="NotebookEdit"))

        # (h) A1 (v0.36): a build config named like a test must not SATISFY the
        # discipline. `tsconfig.test.json` matched testGlobs' `**/*.test.*`, so one
        # config edit marked the whole session as having touched tests and every
        # later source edit went unreminded.
        sess_h = "tdd-session-h"
        _expect("h1 tsconfig.test.json is not a test touch", "silent",
                payload("tsconfig.test.json", sess_h))
        _expect("h2 ...so a later source edit in the same session still warns", "warn",
                payload("src/foo/h.ts", sess_h))

        # (i) the state dir this hook creates must be SELF-IGNORING. It used to be
        # made with a bare mkdir, which left stateDir as the one local dir with no
        # `*` .gitignore inside, and audit-doctor.check_local_artifacts then reported
        # the plugin's own directory as a hygiene finding. A fresh dir is used on
        # purpose: the marker has to be created by the hook, not inherited. The
        # state-file half of the assertion is the other-direction guard - a "fix"
        # that made the directory and stopped writing the state would pass the
        # marker check alone, and every later case in this file would still pass
        # because they use a different state dir.
        sd_i = tmp / "state-selfignoring"          # deliberately NOT pre-created
        sess_i = "tdd-session-i"
        verdict_i, _ = M.decide(payload("src/foo/i.ts", sess_i),
                                cfg=cfg, state_dir=sd_i, now=t0)
        marker_i = sd_i / ".gitignore"
        check("i1 the state dir it creates carries the `*` .gitignore marker "
              "(and the state file still lands in it)",
              verdict_i == "warn"
              and marker_i.is_file()
              and marker_i.read_text(encoding="utf-8") == _config.LOCAL_IGNORE_MARKER
              and M._state_file(sd_i, sess_i).is_file())

        # (r) A NUDGE ABOUT A FILE OUTSIDE THE REPOSITORY. This hook decides
        # nothing, so the defect here is not a refusal - it is a claim. `rel` is
        # os.path.relpath, so a helper written to the system temp directory
        # arrived as `../../../private/tmp/probe.py`, matched `**/*.py` under
        # sourceGlobs like any other source file, and the user was told to write
        # a test for it. The same scope question the plan gate now asks, asked
        # before anything is said out loud.
        tmp_r = Path(tempfile.mkdtemp(prefix="remind-tdd-outside-"))
        try:
            _expect("r1 a source file OUTSIDE the repository says nothing - "
                    "this hook has no standing to nudge about a tree it does "
                    "not govern", "silent",
                    payload(str(tmp_r / "probe.py"), "tdd-session-r"))
            _expect("r2 ...and an in-repo source file in the SAME session "
                    "still warns, so r1 is not the reminder switching itself "
                    "off", "warn",
                    payload("src/foo/r.ts", "tdd-session-r"))
            _expect("r3 an out-of-repo TEST file does not satisfy the "
                    "reminder either - scope is decided before the test-file "
                    "branch, or a stray file elsewhere would silence a whole "
                    "session", "silent",
                    payload(str(tmp_r / "probe.test.ts"), "tdd-session-r2"))
            _expect("r4 ...while the in-repo test file it mimics still counts",
                    "record", payload("src/foo/r.test.ts", "tdd-session-r2"))
        finally:
            _sh_r.rmtree(tmp_r, ignore_errors=True)

        # (f) warn detail is valid additionalContext JSON when serialized
        verdict, detail = M.decide(payload("src/foo/f.ts", "tdd-session-f"),
                                   cfg=cfg, state_dir=sd, now=t0)
        blob = json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUse", "additionalContext": detail}})
        check("f1 warn payload serializes",
              verdict == "warn" and json.loads(blob)["hookSpecificOutput"][
                  "additionalContext"].startswith("[tdd-reminder]"))
    finally:
        # In `finally` because `_harness.run` now CATCHES an escaping exception and
        # carries on printing: a leaked CLAUDE_PROJECT_DIR would then be read by
        # whatever ran next in the same process.
        if prev_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = prev_env


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_remind_tdd.py --selftest\n")
    raise SystemExit(2)
