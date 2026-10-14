#!/usr/bin/env python3
"""The plan gate's tiers, driven end to end through the launcher.

WHY THIS EXISTS. The selftests call `decide()` directly, so they cannot prove the
wiring: the launcher, the stdin contract and the emitted JSON shape. That check
lived as an inline shell block in the CI workflow, and a shell block in a workflow
is a gate no local run reaches - the gate's rules moved, the block went on
asserting the old ones, and both e2e legs went red on a push that every local gate
had passed. The body is a script now: CI calls it, and the selftest sweep runs the
same scenarios, so a change to the hook's tiers is red on a developer's machine
before it is red on a runner.

WHAT IT DRIVES. `plugins/audit/hooks/py-launch.sh require-plan.py ask` with a
PreToolUse payload on stdin and `CLAUDE_PROJECT_DIR` set, the way the harness
does. Each scenario builds its own project directory and uses a session id of its
own, so no scenario spends another's free file.

THE TIERS, as the evidence names them: no manifest observes (silence); a manifest
holding no phase warns (no permissionDecision); a manifest holding phases with
none running denies past the session's first small file; a running phase denies,
in a single-file and in a sharded layout; `enforce:true` denies with no manifest.

Exit codes: 0 every scenario held - 1 a scenario did not - 2 usage error.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

_here = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_here)
LAUNCHER = os.path.join(REPO, "plugins", "audit", "hooks", "py-launch.sh")

# Past the default free-file threshold on size alone, and under it when small.
BIG_LINES = 120
SMALL_LINES = 3

DONE_PHASE = {"meta": {"version": 2}, "phases": [
    {"id": "P1", "title": "p", "status": "done",
     "tasks": [{"id": "P1.1", "title": "t", "status": "done"}]}]}
NO_PHASE = {"meta": {"version": 2}, "phases": []}
RUNNING_PHASE = {"meta": {"version": 2}, "phases": [
    {"id": "P1", "title": "p", "status": "in_progress",
     "tasks": [{"id": "P1.1", "title": "t", "status": "pending"}]}]}
SHARD_INDEX = {"meta": {"version": 2},
               "phases": [{"id": "P1", "title": "p", "shard": "phases/P1.json"}]}
SHARD = RUNNING_PHASE["phases"][0]

USAGE = "usage: check-plan-gate-e2e.py [--selftest]\n"


def _write_json(path, value):
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w") as handle:
        json.dump(value, handle)


def edit_payload(project, session, lines):
    """The PreToolUse payload for one Edit of `lines` added lines."""
    return json.dumps({
        "tool_name": "Edit",
        "tool_input": {"file_path": "src/x.ts", "new_string": "x\n" * lines},
        "session_id": session, "cwd": project,
        "hook_event_name": "PreToolUse"})


def fire(project, session, lines, command=None):
    """Run the hook through the launcher; return (exit code, stdout, stderr).

    `command` replaces the launcher invocation, which is how the selftest hands
    the checker a hook that answers wrongly and watches the checker go red."""
    argv = command or ["sh", LAUNCHER, "require-plan.py", "ask"]
    env = dict(os.environ, CLAUDE_PROJECT_DIR=project)
    run = subprocess.run(argv, input=edit_payload(project, session, lines),
                         env=env, cwd=REPO, universal_newlines=True,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return run.returncode, run.stdout, run.stderr


def _hook_output(stdout):
    if not stdout.strip():
        return {}
    try:
        body = json.loads(stdout)
    except ValueError:
        return {}
    out = body.get("hookSpecificOutput") if isinstance(body, dict) else None
    return out if isinstance(out, dict) else {}


def decision(stdout):
    """The permissionDecision a hook's stdout carries, or None for silence or
    for output that is not the canonical JSON."""
    return _hook_output(stdout).get("permissionDecision")


def reason(stdout):
    return _hook_output(stdout).get("permissionDecisionReason") or ""


def _project(manifest=None, config=None, shard=None):
    project = tempfile.mkdtemp()
    if manifest is not None:
        _write_json(os.path.join(project, "docs", "audit", "audit-plan.json"),
                    manifest)
    if shard is not None:
        _write_json(os.path.join(project, "docs", "audit", "phases", "P1.json"),
                    shard)
    if config is not None:
        _write_json(os.path.join(project, ".claude", "audit.config.json"),
                    config)
    return project


# Each scenario: (label, project kwargs, lines, expected decision, text the
# reason must carry or None). A decision of None means "no permissionDecision".
SCENARIOS = (
    ("no manifest observes: silence, nothing denied",
     {}, BIG_LINES, None, None),
    ("a manifest holding no phase warns: no permissionDecision",
     {"manifest": NO_PHASE}, BIG_LINES, None, None),
    ("phases all done, none running, a big first edit: deny that names how to "
     "start a phase",
     {"manifest": DONE_PHASE}, BIG_LINES, "deny", "/audit:phase add"),
    ("phases all done, none running, a SMALL first edit: the free file allows it",
     {"manifest": DONE_PHASE}, SMALL_LINES, None, None),
    ("a running phase denies the edit no task covers",
     {"manifest": RUNNING_PHASE}, BIG_LINES, "deny", None),
    ("a running phase in a SHARDED manifest denies too: the assembled read "
     "reaches scripts/ through the launcher",
     {"manifest": SHARD_INDEX, "shard": SHARD}, BIG_LINES, "deny", None),
    ("enforce:true denies with no manifest at all",
     {"config": {"enforce": True}}, BIG_LINES, "deny", None),
)


def run_scenario(index, kwargs, lines, command=None):
    """(exit code, decision, reason, stdout, stderr) for one scenario in a
    fresh project."""
    project = _project(**kwargs)
    try:
        code, out, err = fire(project, "e2e-%d" % index, lines, command)
    finally:
        shutil.rmtree(project, ignore_errors=True)
    return code, decision(out), reason(out), out, err


def judge(expected, needle, result):
    """The failure sentence for one scenario, or None when it held."""
    code, got, why, out, err = result
    if code != 0:
        return "launcher exited %d (stderr: %s)" % (code, err.strip()[:200])
    if got != expected:
        return "expected permissionDecision %r, got %r (stdout: %s)" % (
            expected, got, out.strip()[:300])
    if needle is not None and needle not in why:
        return "reason lacks %r: %s" % (needle, why[:300])
    return None


def check(command=None):
    """Every scenario's failure sentence, in order; empty means all held."""
    failures = []
    for index, (label, kwargs, lines, expected, needle) in enumerate(SCENARIOS):
        problem = judge(expected, needle,
                        run_scenario(index, kwargs, lines, command))
        if problem is not None:
            failures.append("%s: %s" % (label, problem))
    return failures


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in argv:
        return _selftest()
    if argv:
        sys.stderr.write(USAGE)
        return 2
    failures = check()
    for line in failures:
        sys.stdout.write("FAIL: %s\n" % (line,))
    if failures:
        return 1
    sys.stdout.write("OK: %d scenarios held through the launcher\n"
                     % len(SCENARIOS))
    return 0


# --- selftest -----------------------------------------------------------------
def _red_indexes(command):
    return [i for i, s in enumerate(SCENARIOS)
            if judge(s[3], s[4], run_scenario(i, s[1], s[2], command))]


def _cases(check_case):
    for index, (label, kwargs, lines, expected, needle) in enumerate(SCENARIOS):
        problem = judge(expected, needle, run_scenario(index, kwargs, lines))
        check_case("s%d %s: %s" % (index, label, problem or "held"),
                   problem is None)

    # The other direction: a checker that cannot go red proves nothing. A hook
    # that says nothing at all must fail every scenario expecting a deny and
    # none expecting quiet; a hook that always denies must fail exactly the
    # scenarios expecting quiet.
    silent = [sys.executable, "-c", "import sys; sys.stdin.read()"]
    deny = [sys.executable, "-c",
            "import sys, json; sys.stdin.read(); print(json.dumps("
            "{'hookSpecificOutput': {'permissionDecision': 'deny', "
            "'permissionDecisionReason': '/audit:phase add'}}))"]
    wants_deny = [i for i, s in enumerate(SCENARIOS) if s[3] == "deny"]
    wants_quiet = [i for i, s in enumerate(SCENARIOS) if s[3] is None]
    red = _red_indexes(silent)
    check_case("m1 a hook that never answers is red on exactly the deny "
               "scenarios: red=%r" % (red,), red == wants_deny)
    red = _red_indexes(deny)
    check_case("m2 a hook that always denies is red on exactly the quiet "
               "scenarios: red=%r" % (red,), red == wants_quiet)

    check_case("d1 decision() reads silence and non-JSON as no decision",
               decision("") is None and decision("not json") is None
               and decision("[]") is None)


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    raise SystemExit(main())
