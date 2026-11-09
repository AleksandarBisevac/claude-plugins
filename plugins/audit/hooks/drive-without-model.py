#!/usr/bin/env python3
"""
UserPromptSubmit hook - runs the drive itself when the prompt is a typed run verb.

WHY THIS EXISTS. With `executor.writerModel` set, every writer is a headless
session, so what a typed `/audit:run <id>` or `/audit:phase <id>` asks of the main
loop is mostly to relay a script's output and launch the next `run:` line, and each
of those relays is a paid model turn. `drive-phase.py auto` does the mechanical
steps with no model; this hook is what starts it. On done and on stop it blocks the
prompt, so no model request is made and the answer is shown to the person; on a step
that needs a model or the human it prints nothing and the prompt goes on, and the
command text continues the drive from wherever it now stands.

THE PROMPT NAMES ITS TARGET, OR THIS HOOK DOES NOT ACT. `/audit:next` is not on the
table: its target would be chosen from plan state the drive itself changes, so a
second task or a stranded echo was what acting on it looked like. It passes through
and runs as it does with no hook.

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
the drive, and the parent's pid is read first, before stdin: read later, a launcher
that had already gone would be the parent the watch compared against, and it would
never see one go. An interrupted run always blocks, whatever `auto` answered,
because the person stopped it and the prompt must not then go on to a model. What it
cannot see, stated here because nothing tests it: a SIGKILL of this interpreter
itself, which leaves `auto` running.

PAST THE HOOK'S OWN `timeout` in `hooks.json` the harness ends the hook. It is set
far past any drive, so expiry is not a normal path; the watch above then stops `auto`
the same way, and the prompt goes on, as it does for any hook that failed.

ON WINDOWS THIS HOOK PASSES EVERY VERB THROUGH, until a real run there proves a
stop. No process can send another a signal it can catch, so `Esc` would end only the
launcher while `auto` and its writers went on spending, and the parent watch cannot
see that. `signals_reach_children` reads the mechanism, the way the suite's skip
does, and it is read before anything is imported past the string check.

THE TREE IS THE COMMAND'S, READ THE WAY THE COMMAND READS IT. The command's Bash
has no CLAUDE_PROJECT_DIR and `drive-phase.py`'s `project_context` falls back to
its working directory, so `auto` is started in the payload's `cwd` with that
variable removed and no `--project-dir`, and the settings are read from that same
directory. `_config.tree_for` is not the reader here: from a worktree under the
project it answers the project before git is asked. A payload that names no
directory, or a manifest whose own project would not be that directory, cannot be
made to agree, and the prompt passes through.

WHAT PASSES THROUGH ON PURPOSE, beyond the table: `permission_mode` plan, because
plan mode is read-only intent and the drive starts paid writers and commits.

Contract: always exit 0. `{"decision": "block", ...}` on stdout, or nothing.

This hook carries no `--selftest` of its own; its cases live in the suite
named after it (hyphens become underscores).
"""
import os
import sys

PREFIX = "[audit] drive-without-model"

# `drive-phase.py auto`'s three answers. A hook may not import `scripts/`, so they
# are written out here, and this hook's suite drives every path with the values
# read off the real module.
AUTO_DONE, AUTO_STOP, AUTO_NEEDS_MODEL = 0, 1, 3

# The subcommands `commands/phase.md` routes before it reads a phase id.
PHASE_SUBCOMMANDS = ("add", "retarget", "priority", "cancel", "signoff", "settle")

# One row per verb this hook may drive, each followed by exactly one id: `autoFlags`
# are what `auto` needs to read the id as the command does; `notIds` are words in
# the id's place that are something else. A prompt carrying anything more -
# `--dry-run`, `--confirm-high-risk` - is not on this table, so the command text
# handles it.
VERBS = {
    "/audit:run": {"autoFlags": ("--task",), "notIds": ()},
    "/audit:phase": {"autoFlags": (), "notIds": PHASE_SUBCOMMANDS},
}
VERB_MARKS = tuple(verb.encode("utf-8") for verb in VERBS)

# How often the wait looks at whether the launcher is still there. A signal does
# not wait for this: it wakes the wait at once.
PARENT_POLL_SECONDS = 0.5

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
    """`(verb, id, row)` when `prompt` is exactly a verb of `VERBS`, else
    None. Reads the whole prompt: a sentence mentioning a verb is not the verb."""
    import re
    words = (prompt or "").split()
    row = VERBS.get(words[0]) if words else None
    if row is None:
        return None
    args = words[1:]
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


def signals_reach_children():
    """False on a platform where no process can be sent a stoppable signal, which
    is where a drive could not be stopped from here at all."""
    return hasattr(os, "killpg")


def session_dir(data):
    """The directory the command's Bash stands in, or None when the payload does
    not name one that exists; the hook does not guess one."""
    cwd = data.get("cwd")
    return cwd if isinstance(cwd, str) and os.path.isdir(cwd) else None


def manifest_of_this_tree(tree, manifest):
    """True when `manifest` is the plan `auto` would take `tree` to be the project
    of: inside it, and no project marker between the two, so the walk
    `_output.project_of_manifest` takes ends at `tree`."""
    import _config
    if not _config.within_root(tree, manifest) or not os.path.isfile(str(manifest)):
        return False
    top = os.path.realpath(tree)
    here = os.path.dirname(os.path.realpath(str(manifest)))
    while here != top:
        parent = os.path.dirname(here)
        if parent == here or any(os.path.exists(os.path.join(here, marker))
                                 for marker in (".git", ".claude")):
            return False
        here = parent
    return True


def stop_signals():
    """The signals that mean stop."""
    import signal
    return [signal.SIGTERM, signal.SIGINT, signal.SIGHUP]


def parent_gone(parent):
    """True when the process that started this hook has gone: posix reparents, so
    `getppid` changes."""
    return os.getppid() != parent


def with_watch(parent, body):
    """`(body's value, interrupted)` of `body(run, stopped)`, with the stop signals
    taken and `parent` watched for as long as it runs.

    `run(argv, root, env)` is `(exit code, stdout bytes)`: the handlers stop
    the child rather than raise here, so its own answer is still read after it
    stops. `communicate` is retried after a timeout, which the docs promise loses no
    output; that timeout is only there to look at the parent. `stopped()` is whether
    a stop has landed, and looks at the parent itself, so it answers correctly
    before any child exists."""
    import signal
    import subprocess
    interrupted, children = [], []

    def stop_children():
        for proc in children:
            try:
                proc.terminate()
            except OSError:
                pass

    def stopped():
        if not interrupted and parent_gone(parent):
            interrupted.append("parent exited")
            stop_children()
        return bool(interrupted)

    def forward(signum, _frame):
        interrupted.append(signum)
        stop_children()

    def run(argv, root, env):
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                cwd=str(root), env=env)
        children.append(proc)
        if interrupted:
            stop_children()
        while True:
            try:
                out, _err = proc.communicate(timeout=PARENT_POLL_SECONDS)
                return proc.returncode, out or b""
            except subprocess.TimeoutExpired:
                stopped()

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
    tree = session_dir(data)
    if tree is None:
        return None
    cfg = _config.load(tree)
    manifest = os.path.join(tree, cfg.get("manifestPath")
                            or _config.DEFAULTS["manifestPath"])
    if not drive_applies(cfg) or not manifest_of_this_tree(tree, manifest):
        return None
    drive = _config.find_script("drive-phase.py")
    if drive is None:
        say("drive-phase.py not found; the prompt goes on")
        return None
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)

    def body(run, stopped):
        if stopped():
            return None
        return run([sys.executable, drive, "auto", target] + list(row["autoFlags"]),
                   tree, env)

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
    if not any(mark in raw for mark in VERB_MARKS) or not signals_reach_children():
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
