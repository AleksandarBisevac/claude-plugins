#!/usr/bin/env python3
"""
UserPromptSubmit hook - runs the drive itself when the prompt is a typed run verb.

WHY THIS EXISTS. With `executor.writerModel` set, every writer is a headless
session, so what a typed `/audit:run`, `/audit:next` or `/audit:phase` asks of the
main loop is mostly to relay a script's output and launch the next `run:` line,
and each of those relays is a paid model turn. `drive-phase.py auto` does the
mechanical steps with no model; this hook is what starts it. On done and on stop it
blocks the prompt, so no model request is made and the answer is shown to the
person; on a step that needs a model or the human it prints nothing and the prompt
goes on, and the command text continues the drive from wherever it now stands.

WHY A STRING CHECK COMES FIRST. This hook fires on every prompt of every session,
so a prompt that does not name a verb must cost a process start and a substring
test and nothing else: `_config`, `json` and `subprocess` are imported only past it.

FAIL-OPEN IS THE SAFE DIRECTION HERE. A prompt that passes through runs the command
as it runs with no hook at all, and the drive's own lock and state decide what that
does. So every failure below - an unreadable config, a missing script, a crash -
lets the prompt go on and says so on stderr; none of them blocks.

A STOP REACHES THE DRIVE, from the moment one can arrive. `Esc` during a hook is a
SIGTERM to it, and the launcher runs this interpreter rather than `exec`ing it, so a
signal sent to the launcher alone stops at the launcher. Both are watched for across
the `audit-status` read as well as the drive, and the parent's pid is read first,
before stdin: read later, a launcher that had already gone would be the parent the
watch compared against, and it would never see one go. An interrupted run always
blocks, whatever `auto` answered, because the person stopped it and the prompt must
not then go on to a model. What it cannot see, stated here because nothing tests
it: a SIGKILL of this interpreter itself, which leaves `auto` running.

PAST THE HOOK'S OWN `timeout` in `hooks.json` the harness ends the hook. It is set
far past any drive, so expiry is not a normal path; the watch above then stops `auto`
the same way, and the prompt goes on, as it does for any hook that failed.

ON WINDOWS `terminate()` is TerminateProcess, which gives `auto` no chance to take
its writers down, so `stop_command` names `taskkill /T /F` for the tree. `getppid`
never changes there, so `parent_gone` answers no rather than guess: a launcher
killed on Windows leaves the drive to end on its own. The interrupt cases skip on
that platform; `stop_command` and `parent_gone` take an `osname`, so their Windows
answers are asserted anywhere, and the live path is checked by hand: an Esc during a
drive, then `tasklist | findstr /I "claude python"` shows no writer left.

THE TREE IS `_config.tree_for`'s. The command this hook stands in for runs in the
session's tree, and `CLAUDE_PROJECT_DIR` may name the main checkout from a linked
worktree, so reading that variable first could drive a different tree from the one
the pass-through command would.

WHAT PASSES THROUGH ON PURPOSE, beyond the table: `permission_mode` plan, because
plan mode is read-only intent and the drive starts paid writers and commits; and
`/audit:next` when the plan holds a task in progress, because `ready` excludes that
task, so its first entry is a different one - `commands/next.md` continues it.

Contract: always exit 0. `{"decision": "block", ...}` on stdout, or nothing.

This hook carries no `--selftest` of its own; its cases live in the suite
named after it (hyphens become underscores).
"""
import os
import sys

VERB_MARK = b"/audit:"
PREFIX = "[audit] drive-without-model"

# `drive-phase.py auto`'s three answers. A hook may not import `scripts/`, so they
# are written out here, and this hook's suite drives every path with the values
# read off the real module.
AUTO_DONE, AUTO_STOP, AUTO_NEEDS_MODEL = 0, 1, 3

# The subcommands `commands/phase.md` routes before it reads a phase id.
PHASE_SUBCOMMANDS = ("add", "retarget", "priority", "cancel", "signoff", "settle")

# One row per verb this hook may drive: `takesId` is whether exactly one id must
# follow it, or nothing may; `autoFlags` are what `auto` needs to read the id as
# the command does; `notIds` are words in the id's place that are something else.
# A prompt carrying anything more - `--dry-run`, `--confirm-high-risk` - is not on
# this table, so the command text handles it.
VERBS = {
    "/audit:run": {"takesId": True, "autoFlags": ("--task",), "notIds": ()},
    "/audit:next": {"takesId": False, "autoFlags": (), "notIds": ()},
    "/audit:phase": {"takesId": True, "autoFlags": (), "notIds": PHASE_SUBCOMMANDS},
}

# How often the wait looks at whether the launcher is still there. A signal does
# not wait for this: it wakes the wait at once.
PARENT_POLL_SECONDS = 0.5
STATUS_TIMEOUT_SECONDS = 60
STOP_TIMEOUT_SECONDS = 30

# A stop that landed while a drive was running, and one that landed before any was.
INTERRUPTED = ("[audit] the drive was interrupted; /audit:resume continues a task "
               "it left in progress")
INTERRUPTED_EARLY = "[audit] interrupted before the drive started; no task was run"


def say(message):
    """One line on stderr, which the harness keeps out of the model's context."""
    try:
        sys.stderr.write("%s: %s\n" % (PREFIX, message))
        sys.stderr.flush()
    except Exception:
        pass


def parse_verb(prompt):
    """`(verb, id or None, row)` when `prompt` is exactly a verb of `VERBS`, else
    None. Reads the whole prompt: a sentence mentioning a verb is not the verb."""
    import re
    words = (prompt or "").split()
    row = VERBS.get(words[0]) if words else None
    if row is None:
        return None
    args = words[1:]
    if not row["takesId"]:
        return (words[0], None, row) if not args else None
    if len(args) != 1 or args[0] in row["notIds"]:
        return None
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", args[0]):
        return None
    return words[0], args[0], row


def drive_applies(cfg):
    """True when this project asked for a headless writer and has not turned the
    hook off. A config that could not be read yields the defaults, which name no
    writer, so a broken one answers no here too."""
    import _config
    if not _config.drive_without_model_enabled(cfg):
        return False
    executor = cfg.get("executor")
    model = executor.get("writerModel") if isinstance(executor, dict) else None
    return isinstance(model, str) and bool(model)


def first_ready(run, root, manifest, env):
    """The task `/audit:next` would pick: the first entry of `audit-status.py
    --json`'s `ready`, the list its READY NOW block renders. None when nothing is
    ready, when a task is already in progress (the command continues that one), or
    when it could not be asked, which is said."""
    import json
    import subprocess
    import _config
    script = _config.find_script("audit-status.py")
    if script is None:
        say("audit-status.py not found; the prompt goes on")
        return None
    try:
        code, out = run([sys.executable, script, str(manifest), "--json"],
                        root, env, STATUS_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as exc:
        say("audit-status could not run (%s); the prompt goes on" % (exc,))
        return None
    try:
        doc = json.loads(out.decode("utf-8", "replace"))
        ready = doc["ready"]
    except (ValueError, KeyError, TypeError):
        say("audit-status exited %s with no ready list" % (code,))
        return None
    if not isinstance(ready, list) or not ready:
        return None
    counts = (doc.get("tasks") or {}).get("byStatus")
    if not isinstance(counts, dict):
        say("audit-status did not say what is in progress; the prompt goes on")
        return None
    return None if counts.get("in_progress") else ready[0]


def stop_signals():
    """The signals that mean stop, as this platform spells them."""
    import signal
    return [getattr(signal, name) for name in ("SIGTERM", "SIGINT", "SIGHUP")
            if hasattr(signal, name)]


def stop_command(pid, osname=None):
    """The argv that takes `pid` and its whole tree down where a signal cannot, or
    None where `terminate()` reaches a process that tears its own children down."""
    if (osname or os.name) != "nt":
        return None
    return ["taskkill", "/T", "/F", "/PID", str(pid)]


def parent_gone(parent, osname=None):
    """True when the process that started this hook has gone. POSIX reparents, so
    `getppid` changes; Windows keeps the old id for the life of the process, so
    there the honest answer is that this cannot tell, and it says no."""
    if (osname or os.name) == "nt":
        return False
    return os.getppid() != parent


def stop_process(proc):
    """Stop `proc` and what it started. A Windows tree `taskkill` could not take
    down is said, since the writers under it are still running and spending."""
    import subprocess
    argv = stop_command(proc.pid)
    if argv is not None:
        try:
            done = subprocess.run(argv, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  timeout=STOP_TIMEOUT_SECONDS)
            if done.returncode == 0 or proc.poll() is not None:
                return
            say("taskkill exited %s; its writers may still be running" % (done.returncode,))
        except (OSError, subprocess.SubprocessError) as exc:
            say("taskkill could not run (%s); its writers may still be running" % (exc,))
    try:
        proc.terminate()
    except OSError:
        pass


def with_watch(parent, body):
    """`(body's value, interrupted)` of `body(run, stopped)`, with the stop signals
    taken and `parent` watched for as long as it runs.

    `run(argv, root, env, limit)` is `(exit code, stdout bytes)`: the handlers stop
    the child rather than raise here, so its own answer is still read after it
    stops. `communicate` is retried after a timeout, which the docs promise loses no
    output; that timeout is only there to look at the parent. `stopped()` is whether
    a stop has landed, and looks at the parent itself, so it answers correctly
    before any child exists."""
    import signal
    import subprocess
    import time
    interrupted, children = [], []

    def stop_children():
        for proc in children:
            stop_process(proc)

    def stopped():
        if not interrupted and parent_gone(parent):
            interrupted.append("parent exited")
            stop_children()
        return bool(interrupted)

    def forward(signum, _frame):
        interrupted.append(signum)
        stop_children()

    def run(argv, root, env, limit=None):
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                cwd=str(root), env=env)
        children.append(proc)
        if interrupted:
            stop_children()
        deadline = None if limit is None else time.monotonic() + limit
        while True:
            try:
                out, _err = proc.communicate(timeout=PARENT_POLL_SECONDS)
                return proc.returncode, out or b""
            except subprocess.TimeoutExpired:
                stopped()
                if deadline is not None and time.monotonic() > deadline:
                    stop_process(proc)
                    proc.communicate()
                    raise subprocess.TimeoutExpired(argv, limit)

    displaced = [(sig, signal.signal(sig, forward)) for sig in stop_signals()]
    try:
        return body(run, stopped), bool(interrupted)
    finally:
        for sig, previous in displaced:
            signal.signal(sig, previous)


def blocked(reason):
    return {"decision": "block", "reason": reason,
            "hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                   "suppressOriginalPrompt": True}}


def read_answer(code, out, interrupted):
    """What `auto`'s end means for the prompt: the block to print, or None for
    the prompt to go on. A done or a stop with nothing on stdout is no answer -
    an interpreter that dies before `auto` starts exits with the stop code."""
    text = out.decode("utf-8", "replace").strip()
    if interrupted:
        return blocked("%s\n%s" % (INTERRUPTED, text) if text else INTERRUPTED)
    if code in (AUTO_DONE, AUTO_STOP) and text:
        return blocked(text)
    if code == AUTO_NEEDS_MODEL:
        return None
    say("auto exited %s with %s; the prompt goes on"
        % (code, "output it does not answer with" if text else "no answer"))
    return None


def answer(raw, parent):
    """The block for this payload, or None for the prompt to go on."""
    import json
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import _config
    data = json.loads(raw.decode("utf-8", "replace"))
    parsed = parse_verb(_config.owner_prompt(data))
    if parsed is None or data.get("permission_mode") == "plan":
        return None
    target, row = parsed[1], parsed[2]
    tree = _config.tree_for(data)
    root, cfg = tree["root"], tree["cfg"]
    manifest = root / (cfg.get("manifestPath") or _config.DEFAULTS["manifestPath"])
    if not drive_applies(cfg) or not manifest.is_file():
        return None
    drive = _config.find_script("drive-phase.py")
    if drive is None:
        say("drive-phase.py not found; the prompt goes on")
        return None
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))

    def body(run, stopped):
        chosen = target if row["takesId"] else first_ready(run, root, manifest, env)
        if chosen is None or stopped():
            return None
        return run([sys.executable, drive, "auto", chosen] + list(row["autoFlags"])
                   + ["--project-dir", str(root)], root, env)

    outcome, interrupted = with_watch(parent, body)
    if outcome is None:
        return blocked(INTERRUPTED_EARLY) if interrupted else None
    return read_answer(outcome[0], outcome[1], interrupted)


def main():
    parent = os.getppid()
    try:
        raw = sys.stdin.buffer.read()
    except Exception:
        return
    if VERB_MARK not in raw:
        return
    try:
        result = answer(raw, parent)
    except Exception as exc:                                   # noqa: BLE001
        say("internal error (%s: %s); the prompt goes on"
            % (type(exc).__name__, exc))
        return
    if result is None:
        return
    import json
    try:
        print(json.dumps(result))
        sys.stdout.flush()
    except Exception as exc:                                   # noqa: BLE001
        say("could not print the answer (%s)" % (exc,))


if __name__ == "__main__":
    main()
    sys.exit(0)
