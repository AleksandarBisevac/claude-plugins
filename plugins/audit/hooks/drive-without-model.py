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

SIGTERM REACHES THE DRIVE. `Esc` during a hook is a SIGTERM to it, and a hook timeout
too, and the launcher runs this interpreter rather than `exec`ing it, so a signal
sent to the launcher alone stops at the launcher. Both are watched for: a signal
here and the parent going away are each forwarded to `auto`, which tears down its
own children. An interrupted drive always blocks, whatever `auto` answered, because
the person stopped it and the prompt must not then go on to a model.

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


def first_ready(root, manifest):
    """The task `/audit:next` would pick: the first entry of `audit-status.py
    --json`'s `ready`, the list its READY NOW block renders. None when nothing is
    ready, or when it could not be asked, which is said."""
    import json
    import subprocess
    import _config
    script = _config.find_script("audit-status.py")
    if script is None:
        say("audit-status.py not found; the prompt goes on")
        return None
    try:
        done = subprocess.run([sys.executable, script, str(manifest), "--json"],
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              cwd=str(root), timeout=STATUS_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as exc:
        say("audit-status could not run (%s); the prompt goes on" % (exc,))
        return None
    try:
        ready = json.loads(done.stdout.decode("utf-8", "replace"))["ready"]
    except (ValueError, KeyError, TypeError):
        say("audit-status exited %s with no ready list; the prompt goes on"
            % (done.returncode,))
        return None
    return ready[0] if isinstance(ready, list) and ready else None


def stop_signals():
    """The signals that mean stop, as this platform spells them."""
    import signal
    return [getattr(signal, name) for name in ("SIGTERM", "SIGINT", "SIGHUP")
            if hasattr(signal, name)]


def run_auto(drive, target, flags, root):
    """`(exit code, stdout bytes, interrupted)` of `auto`.

    The handlers forward a signal to the child rather than raising here, so the
    child's own answer is still read after it stops. `communicate` is retried
    after a timeout, which the docs promise loses no output; the timeout is only
    there to look at the parent."""
    import signal
    import subprocess
    interrupted, children = [], []

    def stop_child():
        for proc in children:
            try:
                proc.terminate()
            except OSError:
                pass

    def forward(signum, _frame):
        interrupted.append(signum)
        stop_child()

    displaced = [(sig, signal.signal(sig, forward)) for sig in stop_signals()]
    try:
        parent = os.getppid()
        proc = subprocess.Popen(
            [sys.executable, drive, "auto", target] + list(flags)
            + ["--project-dir", str(root)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, cwd=str(root),
            env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))
        children.append(proc)
        if interrupted:
            stop_child()
        while True:
            try:
                out, _err = proc.communicate(timeout=PARENT_POLL_SECONDS)
                return proc.returncode, out or b"", bool(interrupted)
            except subprocess.TimeoutExpired:
                if not interrupted and os.getppid() != parent:
                    interrupted.append("parent exited")
                    stop_child()
    finally:
        for sig, previous in displaced:
            signal.signal(sig, previous)


def blocked(reason):
    return {"decision": "block", "reason": reason,
            "hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                   "suppressOriginalPrompt": True}}


def read_answer(code, out, interrupted, typed):
    """What `auto`'s end means for the prompt: the block to print, or None for
    the prompt to go on. A done or a stop with nothing on stdout is no answer -
    an interpreter that dies before `auto` starts exits with the stop code."""
    text = out.decode("utf-8", "replace").strip()
    if interrupted:
        line = "[audit] the drive was interrupted; type %s again to resume it" % (typed,)
        return blocked("%s\n%s" % (line, text) if text else line)
    if code in (AUTO_DONE, AUTO_STOP) and text:
        return blocked(text)
    if code == AUTO_NEEDS_MODEL:
        return None
    say("auto exited %s with %s; the prompt goes on"
        % (code, "output it does not answer with" if text else "no answer"))
    return None


def answer(raw):
    """The block for this payload, or None for the prompt to go on."""
    import json
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import _config
    data = json.loads(raw.decode("utf-8", "replace"))
    parsed = parse_verb(_config.owner_prompt(data))
    if parsed is None:
        return None
    verb, target, row = parsed
    root = _config.repo_root(data)
    cfg = _config.load(root)
    manifest = root / (cfg.get("manifestPath") or _config.DEFAULTS["manifestPath"])
    if not drive_applies(cfg) or not manifest.is_file():
        return None
    drive = _config.find_script("drive-phase.py")
    if drive is None:
        say("drive-phase.py not found; the prompt goes on")
        return None
    chosen = target if row["takesId"] else first_ready(root, manifest)
    if chosen is None:
        return None
    code, out, interrupted = run_auto(drive, chosen, row["autoFlags"], root)
    typed = "%s %s" % (verb, target) if target else verb
    return read_answer(code, out, interrupted, typed)


def main():
    try:
        raw = sys.stdin.buffer.read()
    except Exception:
        return
    if VERB_MARK not in raw:
        return
    try:
        result = answer(raw)
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
