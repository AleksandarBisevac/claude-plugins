#!/usr/bin/env python3
"""
The cases for `hooks/drive-without-model.py`, the UserPromptSubmit hook that runs
the drive itself when a typed verb's writer is a headless session.

EVERY CASE DRIVES THE REAL HOOK AS A PROCESS, in a fixture copy of the plugin's
layout: `hooks/` holds the real hook and the real `_config.py`, and `scripts/`
holds a stub `drive-phase.py` and a stub `audit-status.py`, because
`_config.find_script` walks from the `_config.py` that is running. The stub's
script is a file, `plan.json` beside it: what to print, what to exit with, whether
to hold until a SIGTERM. What the hook did is read from the stub's own record of
each call, so a case can say the drive was never started rather than infer it from
silence.

WHAT THE STUB'S EXIT CODES ARE. They are the real `drive-phase.py`'s constants,
loaded here, and every argv the hook hands the stub is put back through the real
`build_parser()`. A stub that invented its own numbers or accepted any argv would
leave the hook agreeing with the stub and with nothing else.

WHY A PASS-THROUGH CASE ASSERTS THE CALL COUNT AS WELL AS THE SILENCE. Printing
nothing and exiting 0 is what the hook does when it decides not to act and also
what it does after a needs-model answer; only the record tells the two apart.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import time

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402

HOOK_NAME = "drive-without-model.py"
HOOK_TIMEOUT = 60
WRITER = {"executor": {"writerModel": "claude-sonnet-5-5", "writerBudgetUsd": 5}}
TASKS_IDLE = {"total": 3, "byStatus": {"pending": 3}}
STATUS_READY = {"ready": ["P2.3", "P2.4"], "tasks": TASKS_IDLE}

STUB_DRIVE = """\
import json
import os
import signal
import sys
import time

here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "plan.json"), encoding="utf-8") as fh:
    plan = json.load(fh)
with open(os.path.join(here, "calls.jsonl"), "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:],
                         "project": os.environ.get("CLAUDE_PROJECT_DIR")}) + "\\n")
with open(os.path.join(here, "pid"), "w", encoding="utf-8") as fh:
    fh.write(str(os.getpid()))
if plan.get("hold"):
    got = []
    signal.signal(signal.SIGTERM, lambda signum, frame: got.append(signum))
    with open(os.path.join(here, "started"), "w", encoding="utf-8") as fh:
        fh.write("started")
    deadline = time.time() + 30
    while not got and time.time() < deadline:
        time.sleep(0.02)
    if got:
        with open(os.path.join(here, "terminated"), "w", encoding="utf-8") as fh:
            fh.write("terminated")
if plan.get("raise"):
    raise RuntimeError("the stub crashed on purpose")
sys.stdout.buffer.write(plan.get("out", "").encode("utf-8"))
sys.stdout.buffer.flush()
sys.exit(plan.get("exit", 0))
"""

STUB_STATUS = """\
import json
import os
import signal
import sys
import time

here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "plan.json"), encoding="utf-8") as fh:
    plan = json.load(fh)
with open(os.path.join(here, "status-calls.jsonl"), "a", encoding="utf-8") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
with open(os.path.join(here, "status-cwd"), "w", encoding="utf-8") as fh:
    fh.write(os.getcwd())
if plan.get("statusIgnoresStop"):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if plan.get("statusHold"):
    with open(os.path.join(here, "status-started"), "w", encoding="utf-8") as fh:
        fh.write("started")
    time.sleep(plan["statusHold"])
sys.stdout.write(plan.get("status", ""))
sys.exit(plan.get("statusExit", 0))
"""


# --- fixture ------------------------------------------------------------------
def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _make(root, name, plan=None, config=WRITER, manifest=True, drive=True,
          broken_config=False):
    """One case's tree: a plugin copy and a project. `config` is a dict, a raw
    string (a config file that does not parse) or None (no file). The hook is
    copied only when it exists, so on a tree without it each case fails its own
    assertion on the hook's missing-file exit rather than crashing the suite."""
    case = os.path.join(root, name)
    hooks = os.path.join(case, "plugin", "hooks")
    scripts = os.path.join(case, "plugin", "scripts")
    os.makedirs(hooks)
    os.makedirs(scripts)
    for filename in (HOOK_NAME, "py-launch.sh"):
        real = os.path.join(_harness.HOOKS_DIR, filename)
        if os.path.isfile(real):
            shutil.copy(real, os.path.join(hooks, filename))
    if broken_config:
        _write(os.path.join(hooks, "_config.py"), "raise RuntimeError('no config')\n")
    else:
        shutil.copy(os.path.join(_harness.HOOKS_DIR, "_config.py"),
                    os.path.join(hooks, "_config.py"))
    if drive:
        _write(os.path.join(scripts, "drive-phase.py"), STUB_DRIVE)
    _write(os.path.join(scripts, "audit-status.py"), STUB_STATUS)
    _write(os.path.join(scripts, "plan.json"), json.dumps(plan or {}))
    project = os.path.join(case, "proj")
    os.makedirs(project)
    if isinstance(config, dict):
        _write(os.path.join(project, ".claude", "audit.config.json"), json.dumps(config))
    elif isinstance(config, str):
        _write(os.path.join(project, ".claude", "audit.config.json"), config)
    if manifest:
        _write(os.path.join(project, "docs", "audit", "audit-plan.json"), "{}\n")
    return {"hook": os.path.join(hooks, HOOK_NAME), "scripts": scripts,
            "project": project, "launcher": os.path.join(hooks, "py-launch.sh")}


def _payload(fx, prompt, **extra):
    return json.dumps(dict({"hook_event_name": "UserPromptSubmit",
                            "session_id": "s1", "cwd": fx["project"],
                            "prompt": prompt}, **extra))


def _env(fx):
    return dict(os.environ, CLAUDE_PROJECT_DIR=fx["project"])


def _run(fx, stdin):
    """(exit, stdout, stderr) of the hook on `stdin`."""
    done = subprocess.run([sys.executable, fx["hook"]], input=stdin.encode("utf-8"),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          cwd=fx["project"], env=_env(fx), timeout=HOOK_TIMEOUT)
    return (done.returncode, done.stdout.decode("utf-8", "replace"),
            done.stderr.decode("utf-8", "replace"))


def _calls(fx):
    path = os.path.join(fx["scripts"], "calls.jsonl")
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _block(stdout):
    """The hook's JSON answer as a dict, or None when stdout holds no object."""
    try:
        doc = json.loads(stdout)
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def _blocks_with(stdout, text):
    """True when stdout is the block `text` should have become: the decision,
    the reason word for word, and the original prompt suppressed."""
    doc = _block(stdout) or {}
    specific = doc.get("hookSpecificOutput") or {}
    return (doc.get("decision") == "block" and doc.get("reason") == text
            and specific.get("hookEventName") == "UserPromptSubmit"
            and specific.get("suppressOriginalPrompt") is True)


def _wait_for(path, seconds=20):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if os.path.exists(path):
            return True
        time.sleep(0.02)
    return os.path.exists(path)


# --- answers ------------------------------------------------------------------
def _answer_cases(check, root, real):
    done_text = "audit P1 done: landed at abc1234"
    fx = _make(root, "done", {"out": done_text + "\n", "exit": real.AUTO_DONE})
    code, out, err = _run(fx, _payload(fx, "/audit:run P1.1"))
    calls = _calls(fx)
    check("dm1 a prompt that is exactly /audit:run <id> starts auto once, on that "
          "task, in the one-task form, in this project",
          len(calls) == 1 and calls[0]["argv"][:2] == ["auto", "P1.1"]
          and "--task" in calls[0]["argv"]
          and os.path.realpath(calls[0]["project"] or "")
          == os.path.realpath(fx["project"]),
          "calls=%r err=%r" % (calls, err))
    check("dm2 auto's done answer blocks the prompt with auto's text as the "
          "reason and the original prompt suppressed, exit 0",
          code == 0 and _blocks_with(out, done_text), "code=%r out=%r" % (code, out))

    args = real.build_parser().parse_args(calls[0]["argv"]) if calls else None
    check("dm3 the argv the hook hands auto is one the real drive-phase.py parser "
          "accepts, naming the task and the one-task flag",
          args is not None and args.action == "auto" and args.phase == "P1.1"
          and args.task_only is True
          and os.path.realpath(args.project_dir or "")
          == os.path.realpath(fx["project"]),
          "args=%r" % (args,))

    stop_text = "audit P1: stopped - the gate is red"
    fx = _make(root, "stop", {"out": stop_text + "\n", "exit": real.AUTO_STOP})
    code, out, _err = _run(fx, _payload(fx, "/audit:run P1.1"))
    check("dm4 auto's stop answer blocks the prompt with auto's text too",
          code == 0 and _blocks_with(out, stop_text), "code=%r out=%r" % (code, out))

    fx = _make(root, "needs", {"out": "audit P1 judge P1.1 | r | next: x\n",
                               "exit": real.AUTO_NEEDS_MODEL})
    code, out, err = _run(fx, _payload(fx, "/audit:run P1.1"))
    check("dm5 auto's needs-model answer prints nothing and exits 0, so the "
          "prompt goes on - after auto ran, which the record shows",
          code == 0 and out == "" and len(_calls(fx)) == 1,
          "code=%r out=%r err=%r calls=%r" % (code, out, err, _calls(fx)))

    wide = "audit P1 done: café → landed"
    fx = _make(root, "utf8", {"out": wide + "\n", "exit": real.AUTO_DONE})
    code, out, _err = _run(fx, _payload(fx, "/audit:run P1.1"))
    check("dm6 auto's text survives non-ASCII bytes on its stdout, whatever code "
          "page the hook runs under",
          code == 0 and _blocks_with(out, wide), "code=%r out=%r" % (code, out))

    fx = _make(root, "spaces", {"out": "ok\n", "exit": real.AUTO_DONE})
    code, out, _err = _run(fx, _payload(fx, "  /audit:run   P1.1 \n"))
    check("dm7 surrounding and repeated whitespace is still the verb as typed",
          code == 0 and _blocks_with(out, "ok") and len(_calls(fx)) == 1,
          "code=%r out=%r" % (code, out))


# --- the table ----------------------------------------------------------------
def _table_cases(check, root, real):
    for label, prompt, want, task_only in (
            ("dm8 /audit:phase <id> takes the same path as /audit:run",
             "/audit:phase P2", "P2", False),
            ("dm9 /audit:next takes the same path, on the first task audit-status "
             "lists under READY NOW", "/audit:next", "P2.3", False)):
        fx = _make(root, "verb-%s" % (want,),
                   {"out": "done text\n", "exit": real.AUTO_DONE,
                    "status": json.dumps(STATUS_READY)})
        code, out, err = _run(fx, _payload(fx, prompt))
        calls = _calls(fx)
        args = real.build_parser().parse_args(calls[0]["argv"]) if calls else None
        check(label,
              code == 0 and _blocks_with(out, "done text") and args is not None
              and args.action == "auto" and args.phase == want
              and args.task_only is task_only,
              "code=%r out=%r err=%r calls=%r" % (code, out, err, calls))

    fx = _make(root, "none-ready", {"status": json.dumps({"ready": [],
                                                          "tasks": TASKS_IDLE})})
    code, out, err = _run(fx, _payload(fx, "/audit:next"))
    check("dm10 /audit:next with nothing ready starts nothing and passes the prompt "
          "on: relaying what each task waits on is the command's own job - and "
          "says nothing on stderr, since nothing went wrong",
          code == 0 and out == "" and err == "" and _calls(fx) == [],
          "code=%r out=%r err=%r calls=%r" % (code, out, err, _calls(fx)))

    fx = _make(root, "status-down", {"statusExit": 2, "status": "not json"})
    code, out, err = _run(fx, _payload(fx, "/audit:next"))
    check("dm11 an audit-status that cannot answer passes the prompt on and says "
          "so on stderr",
          code == 0 and out == "" and _calls(fx) == [] and "audit-status" in err,
          "code=%r out=%r err=%r" % (code, out, err))

    fx = _make(root, "status-args", {"out": "t\n", "exit": real.AUTO_DONE,
                                     "status": json.dumps(STATUS_READY)})
    _run(fx, _payload(fx, "/audit:next"))
    asked = os.path.join(fx["scripts"], "status-calls.jsonl")
    status_argv = []
    if os.path.isfile(asked):
        with open(asked, encoding="utf-8") as fh:
            status_argv = json.loads(fh.readline())
    check("dm12 /audit:next asks audit-status for the machine form of the list the "
          "command reads", "--json" in status_argv, status_argv)

    with open(os.path.join(os.path.dirname(_harness.HOOKS_DIR), "commands",
                           "phase.md"), encoding="utf-8") as fh:
        text = fh.read()
    start = text.index("first token: ")
    end = text.index("or a\nphase id to run", start)
    words = text[start:end].replace("first token: ", "").replace("`", "")
    words = [w.strip() for w in words.replace(",", " ").split() if w.strip()]
    check("dm13 the subcommands commands/phase.md lists are what this suite "
          "passes through below (a new one is a row here)",
          sorted(words) == sorted(SUBVERBS), words)
    for verb in SUBVERBS:
        fx = _make(root, "sub-%s" % (verb,), {"out": "x\n", "exit": 0})
        code, out, _err = _run(fx, _payload(fx, "/audit:phase %s" % (verb,)))
        check("dm14 /audit:phase %s is a subcommand and passes the prompt on" % (verb,),
              code == 0 and out == "" and _calls(fx) == [],
              "code=%r out=%r calls=%r" % (code, out, _calls(fx)))


SUBVERBS = ("add", "retarget", "priority", "cancel", "signoff", "settle")


# --- passing through ----------------------------------------------------------
def _pass_through_cases(check, root, real):
    plan = {"out": "should not be seen\n", "exit": real.AUTO_DONE,
            "status": json.dumps(STATUS_READY)}
    for label, prompt, kwargs in (
            ("dm15 /audit:run <id> --dry-run", "/audit:run P1.1 --dry-run", {}),
            ("dm16 any other prompt", "please fix the login page", {}),
            ("dm17 a prompt merely containing the words",
             "what does /audit:run P1.1 do?", {}),
            ("dm18 a bare /audit:run with no id", "/audit:run", {}),
            ("dm19 /audit:next with an argument", "/audit:next --dry-run", {}),
            ("dm20 /audit:phase with no id", "/audit:phase", {}),
            ("dm21 /audit:phase <id> --dry-run", "/audit:phase P2 --dry-run", {}),
            ("dm22 a verb of another plugin", "/other:run P1.1", {}),
            ("dm23 no executor.writerModel", "/audit:run P1.1", {"config": {}}),
            ("dm24 an empty executor.writerModel", "/audit:run P1.1",
             {"config": {"executor": {"writerModel": ""}}}),
            ("dm25 the opt-out key set false", "/audit:run P1.1",
             {"config": dict(WRITER, executor=dict(
                 WRITER["executor"], driveWithoutModel=False))}),
            ("dm26 no plan", "/audit:run P1.1", {"manifest": False}),
            ("dm27 an unreadable config", "/audit:run P1.1",
             {"config": "{not json"})):
        fx = _make(root, label.split()[0], plan, **kwargs)
        code, out, err = _run(fx, _payload(fx, prompt))
        check("%s passes the prompt on: no block, no drive" % (label,),
              code == 0 and out == "" and _calls(fx) == [],
              "code=%r out=%r err=%r calls=%r" % (code, out, err, _calls(fx)))

    # THE ALLOW DIRECTION OF THE OPT-OUT: a mutation reading the key as off by
    # default is red here and green in every case above.
    fx = _make(root, "opt-in", {"out": "t\n", "exit": real.AUTO_DONE},
               config=dict(WRITER, executor=dict(WRITER["executor"],
                                                 driveWithoutModel=True)))
    code, out, _err = _run(fx, _payload(fx, "/audit:run P1.1"))
    check("dm28 the opt-out key set true is the same as the key absent: the drive "
          "runs", code == 0 and _blocks_with(out, "t") and len(_calls(fx)) == 1,
          "code=%r out=%r" % (code, out))

    fx = _make(root, "subagent", plan)
    code, out, _err = _run(fx, _payload(fx, "/audit:run P1.1", agent_id="a1"))
    check("dm29 a prompt a subagent carries is no typed verb: passes on",
          code == 0 and out == "" and _calls(fx) == [],
          "code=%r out=%r calls=%r" % (code, out, _calls(fx)))

    fx = _make(root, "garbage", plan)
    code, out, _err = _run(fx, "this is not JSON naming /audit:run")
    check("dm30 a payload that is not JSON passes on",
          code == 0 and out == "" and _calls(fx) == [],
          "code=%r out=%r calls=%r" % (code, out, _calls(fx)))

    fx = _make(root, "no-drive", plan, drive=False)
    code, out, err = _run(fx, _payload(fx, "/audit:run P1.1"))
    check("dm31 auto missing passes the prompt on and says so on stderr",
          code == 0 and out == "" and "drive-phase.py" in err,
          "code=%r out=%r err=%r" % (code, out, err))

    for label, crash, name in (
            ("dm32 auto exiting with its could-not-run code",
             {"exit": real.E_USAGE, "out": ""}, "crash-usage"),
            ("dm33 auto raising before any answer (exit 1, the stop code, with "
             "nothing on stdout)", {"raise": True}, "crash-raise"),
            ("dm34 auto exiting 0 with nothing on stdout", {"exit": 0, "out": ""},
             "crash-empty"),
            ("dm35 an exit code auto never answers with", {"exit": 7, "out": "x\n"},
             "crash-other")):
        fx = _make(root, name, crash)
        code, out, err = _run(fx, _payload(fx, "/audit:run P1.1"))
        check("%s passes the prompt on, with no block, and a line on stderr "
              "saying the drive did not answer" % (label,),
              code == 0 and out == "" and len(_calls(fx)) == 1
              and "drive-without-model" in err,
              "code=%r out=%r err=%r" % (code, out, err))


# --- cost on the prompts that are not ours --------------------------------------
def _prefilter_cases(check, root):
    fx = _make(root, "prefilter", {}, broken_config=True)
    code, out, err = _run(fx, _payload(fx, "please fix the login page"))
    check("dm36 a prompt naming no verb never reaches the shared config module: a "
          "_config.py that raises on import changes nothing",
          code == 0 and out == "" and err == "",
          "code=%r out=%r err=%r" % (code, out, err))

    fx = _make(root, "broken-config", {"out": "x\n", "exit": 0}, broken_config=True)
    code, out, err = _run(fx, _payload(fx, "/audit:run P1.1"))
    check("dm37 an internal error past the prefilter passes the prompt on and says "
          "so on stderr",
          code == 0 and out == "" and _calls(fx) == [] and "drive-without-model" in err,
          "code=%r out=%r err=%r" % (code, out, err))


# --- interruption -------------------------------------------------------------
def _interrupted_run(fx, target, prompt="/audit:run P1.1", gate="started",
                     sig=signal.SIGTERM):
    """Start the hook, wait for the stub to write `gate`, send `sig` to the
    process `target` starts, return (exit, stdout, started)."""
    argv = target["argv"](fx)
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, cwd=fx["project"], env=_env(fx))
    proc.stdin.write(_payload(fx, prompt).encode("utf-8"))
    proc.stdin.close()
    started = _wait_for(os.path.join(fx["scripts"], gate))
    if started:
        proc.send_signal(sig)
    out = proc.stdout.read().decode("utf-8", "replace")
    proc.stderr.read()
    proc.stdout.close()
    proc.stderr.close()
    return proc.wait(timeout=HOOK_TIMEOUT), out, started


def _no_drive_running(fx):
    """True when the stub drive never started, or the pid it recorded has gone.
    A second look, because a process that was just told to stop takes a moment."""
    path = os.path.join(fx["scripts"], "pid")
    if not os.path.isfile(path):
        return True
    with open(path, encoding="utf-8") as fh:
        pid = int(fh.read())
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.05)
    return False


def _interrupt_cases(check, root, real):
    mechanism = "the hook's SIGTERM is a posix signal it can trap and forward"
    if not hasattr(os, "killpg"):
        for label in INTERRUPT_LABELS:
            _harness.skip(check, label, mechanism, True)
        return
    direct = {"argv": lambda fx: [sys.executable, fx["hook"]]}
    stop_text = "audit P1: stopped - auto-interrupted: SIGTERM arrived"
    fx = _make(root, "term", {"hold": True, "out": stop_text + "\n",
                              "exit": real.AUTO_STOP})
    code, out, started = _interrupted_run(fx, direct)
    doc = _block(out) or {}
    reason = doc.get("reason") or ""
    check("dm38 SIGTERM to the hook reaches auto, and the hook then blocks with a "
          "line saying the drive was interrupted, the command that carries a stopped "
          "task on, and auto's text",
          started and code == 0
          and os.path.exists(os.path.join(fx["scripts"], "terminated"))
          and doc.get("decision") == "block" and "interrupted" in reason
          and "/audit:resume" in reason and stop_text in reason,
          "started=%r code=%r out=%r" % (started, code, out))

    # RETYPING IS NOT A RESUME. The hook would start `auto` afresh for the same
    # words, and for /audit:next on a different task, so the line must not offer
    # the prompt the user just typed as the way back.
    check("dm51 the interrupt line does not offer the typed verb as the way to "
          "resume: the hook does not resume, the /audit:resume command does",
          started and "/audit:run P1.1" not in reason.replace(stop_text, "")
          and "resume it" not in reason, "reason=%r" % (reason,))

    fx = _make(root, "term-crash", {"hold": True, "exit": real.E_USAGE, "out": ""})
    code, out, started = _interrupted_run(fx, direct)
    doc = _block(out) or {}
    check("dm39 an interrupted drive that exits with no answer still blocks and "
          "says it was interrupted: the prompt must not go on to a model after the "
          "user stopped it",
          started and code == 0 and doc.get("decision") == "block"
          and "interrupted" in (doc.get("reason") or ""),
          "started=%r code=%r out=%r" % (started, code, out))

    # py-launch.sh runs the interpreter rather than `exec`ing it, so a signal sent
    # to the launcher's own process stops at the launcher and the interpreter is
    # left running with no parent.
    launched = {"argv": lambda fx: ["sh", fx["launcher"], HOOK_NAME, "open"]}
    fx = _make(root, "term-launcher", {"hold": True, "out": stop_text + "\n",
                                       "exit": real.AUTO_STOP})
    _code, _out, started = _interrupted_run(fx, launched)
    check("dm40 SIGTERM sent only to the launcher reaches auto too: the hook sees "
          "its parent go and stops the drive rather than leaving it running unowned",
          started and os.path.exists(os.path.join(fx["scripts"], "terminated")),
          "started=%r files=%r" % (started, sorted(os.listdir(fx["scripts"]))))

    # The harness's own stop may be a SIGKILL of the launcher, which nothing can
    # trap: only the parent-gone watch can answer it.
    fx = _make(root, "kill-launcher", {"hold": True, "out": stop_text + "\n",
                                       "exit": real.AUTO_STOP})
    _code, _out, started = _interrupted_run(fx, launched, sig=signal.SIGKILL)
    check("dm54 the parent going away by SIGKILL stops the drive: no drive is left "
          "running",
          started and os.path.exists(os.path.join(fx["scripts"], "terminated"))
          and _no_drive_running(fx),
          "started=%r files=%r" % (started, sorted(os.listdir(fx["scripts"]))))

    # THE SIGNAL LANDS WHILE audit-status IS BEING READ, which is before any drive
    # exists. /audit:next is the only verb with that window. The hold is long
    # enough for the signal to arrive and short enough that the hook goes on to
    # the point where it would start a drive if it took nothing from the signal.
    during_status = {"hold": True, "out": stop_text + "\n", "exit": real.AUTO_STOP,
                     "status": json.dumps(STATUS_READY), "statusHold": 1.0}
    fx = _make(root, "term-status", during_status)
    code, out, started = _interrupted_run(fx, direct, prompt="/audit:next",
                                          gate="status-started")
    doc = _block(out) or {}
    check("dm52 SIGTERM to the hook during the audit-status read leaves no drive "
          "running, and a drive that did start was told to stop; the prompt does "
          "not go on to a model",
          started and code == 0 and doc.get("decision") == "block"
          and "interrupted" in (doc.get("reason") or "")
          and (_calls(fx) == []
               or os.path.exists(os.path.join(fx["scripts"], "terminated")))
          and _no_drive_running(fx),
          "started=%r code=%r out=%r calls=%r" % (started, code, out, _calls(fx)))

    # THE STATUS ANSWER ARRIVES ANYWAY. Stopping audit-status usually leaves no JSON,
    # which ends the run for an unrelated reason; a child that finishes its answer
    # hands the hook a valid task after the stop has already landed.
    fx = _make(root, "term-status-answers", dict(during_status, statusIgnoresStop=True))
    code, out, started = _interrupted_run(fx, direct, prompt="/audit:next",
                                          gate="status-started")
    doc = _block(out) or {}
    check("dm58 a stop that lands while audit-status finishes a good answer leaves "
          "no drive, and the prompt is still blocked as interrupted",
          started and code == 0 and _calls(fx) == []
          and doc.get("decision") == "block"
          and "interrupted" in (doc.get("reason") or ""),
          "started=%r code=%r out=%r calls=%r" % (started, code, out, _calls(fx)))

    # A STATUS READ SHORTER THAN ONE POLL OF THE PARENT. No poll tick lands inside
    # it, so only the check made before the drive starts can see the launcher gone;
    # without that check the drive runs until the first tick, which the record shows.
    fx = _make(root, "launcher-status-brief", dict(during_status, statusHold=0.1))
    _code, _out, started = _interrupted_run(fx, launched, prompt="/audit:next",
                                            gate="status-started")
    check("dm59 the launcher going away during a status read shorter than a poll "
          "starts no drive at all",
          started and _calls(fx) == [], "started=%r calls=%r" % (started, _calls(fx)))

    fx = _make(root, "launcher-status", during_status)
    _code, _out, started = _interrupted_run(fx, launched, prompt="/audit:next",
                                            gate="status-started")
    check("dm53 the launcher going away during the audit-status read leaves no "
          "drive running: the parent is read before anything that can take a signal",
          started and (_calls(fx) == []
                       or os.path.exists(os.path.join(fx["scripts"], "terminated")))
          and _no_drive_running(fx),
          "started=%r calls=%r files=%r" % (started, _calls(fx),
                                            sorted(os.listdir(fx["scripts"]))))


INTERRUPT_LABELS = ("dm38", "dm39", "dm40", "dm51", "dm52", "dm53", "dm54", "dm58",
                    "dm59")


def _platform_cases(check):
    hook = _loader.load(os.path.join(_harness.HOOKS_DIR, HOOK_NAME))
    argv = hook.stop_command(4242, "nt")
    check("dm55 on Windows the stop is taskkill over the tree, by that pid; "
          "TerminateProcess would leave auto's writers running",
          argv == ["taskkill", "/T", "/F", "/PID", "4242"], argv)
    # THE OTHER DIRECTION: taskkill on every platform is red here and green above.
    check("dm56 on posix the stop is the signal auto tears its own children down "
          "on: no external command",
          hook.stop_command(4242, "posix") is None, hook.stop_command(4242, "posix"))
    # A fixture value that is not this process's parent, so a real getppid compare
    # says gone: the Windows answer must not depend on it.
    stale = os.getppid() + 1
    check("dm57 the parent-gone check answers no on Windows, where getppid never "
          "changes, and does compare on posix",
          hook.parent_gone(stale, "nt") is False
          and hook.parent_gone(stale, "posix") is True
          and hook.parent_gone(os.getppid(), "posix") is False, stale)


def _launcher_cases(check, root, real):
    fx = _make(root, "launcher", {"out": "through the launcher\n",
                                  "exit": real.AUTO_DONE})
    done = subprocess.run(["sh", fx["launcher"], HOOK_NAME, "open"],
                          input=_payload(fx, "/audit:run P1.1").encode("utf-8"),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          cwd=fx["project"], env=_env(fx), timeout=HOOK_TIMEOUT)
    out = done.stdout.decode("utf-8", "replace")
    check("dm41 through py-launch.sh, the way hooks.json runs it, the block arrives "
          "whole and the exit is 0",
          done.returncode == 0 and _blocks_with(out, "through the launcher"),
          "code=%r out=%r err=%r" % (done.returncode, out, done.stderr))


# --- registration -------------------------------------------------------------
def _registration_cases(check):
    with open(os.path.join(_harness.HOOKS_DIR, "hooks.json"), encoding="utf-8") as fh:
        doc = json.load(fh)
    entries = [entry for group in doc["hooks"].get("UserPromptSubmit", [])
               for entry in group.get("hooks", [])
               if HOOK_NAME in entry.get("command", "")]
    check("dm42 the hook is registered once and carries no onFailure, so a hook "
          "that cannot start sends the prompt on instead of blocking every prompt",
          len(entries) == 1 and "onFailure" not in entries[0], entries)


# --- work already in progress -------------------------------------------------
def _in_progress_cases(check, root, real):
    busy = {"ready": ["P2.3"], "tasks": {"byStatus": {"in_progress": 1, "pending": 2}}}
    plan = {"out": "should not be seen\n", "exit": real.AUTO_DONE,
            "status": json.dumps(busy)}
    fx = _make(root, "next-busy", plan)
    code, out, err = _run(fx, _payload(fx, "/audit:next"))
    check("dm43 /audit:next with a task in progress passes the prompt on and starts "
          "nothing: READY NOW excludes that task, so the first entry is another one",
          code == 0 and out == "" and err == "" and _calls(fx) == [],
          "code=%r out=%r err=%r calls=%r" % (code, out, err, _calls(fx)))

    # THE ALLOW DIRECTION: a mutation reading any byStatus at all as busy is red
    # here and green in dm43.
    idle = {"ready": ["P2.3"], "tasks": {"byStatus": {"in_progress": 0, "pending": 2}}}
    fx = _make(root, "next-idle", {"out": "t\n", "exit": real.AUTO_DONE,
                                   "status": json.dumps(idle)})
    code, out, _err = _run(fx, _payload(fx, "/audit:next"))
    check("dm44 a recorded in_progress of zero is an idle plan: the drive starts",
          code == 0 and _blocks_with(out, "t") and len(_calls(fx)) == 1,
          "code=%r out=%r calls=%r" % (code, out, _calls(fx)))

    fx = _make(root, "next-blind", {"out": "x\n", "exit": real.AUTO_DONE,
                                    "status": json.dumps({"ready": ["P2.3"]})})
    code, out, err = _run(fx, _payload(fx, "/audit:next"))
    check("dm45 a status answer that does not say what is in progress passes the "
          "prompt on and says so on stderr: no count is no evidence the plan is idle",
          code == 0 and out == "" and _calls(fx) == [] and "audit-status" in err,
          "code=%r out=%r err=%r calls=%r" % (code, out, err, _calls(fx)))

    # The stub's shape is hand-written; this pins it to the real script's.
    plan_root = _harness.fixture_root("dm-status-")
    path = os.path.join(plan_root, "audit-plan.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(_harness.running_plan("P1", ["src/a.ts"], "P2"), fh)
    script = os.path.join(_harness.SCRIPTS_DIR, "status", "audit-status.py")
    done = subprocess.run([sys.executable, script, path, "--json"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          cwd=plan_root, timeout=HOOK_TIMEOUT)
    answer = _block(done.stdout.decode("utf-8", "replace")) or {}
    check("dm46 the real audit-status --json says in_progress where the hook reads "
          "it, and leaves that task out of READY NOW",
          ((answer.get("tasks") or {}).get("byStatus") or {}).get("in_progress") == 1
          and "P1.1" not in (answer.get("ready") or [None]),
          "code=%r answer=%r err=%r" % (done.returncode, sorted(answer), done.stderr))


# --- permission mode ----------------------------------------------------------
def _permission_cases(check, root, real):
    plan = {"out": "t\n", "exit": real.AUTO_DONE}
    fx = _make(root, "mode-plan", plan)
    code, out, err = _run(fx, _payload(fx, "/audit:run P1.1", permission_mode="plan"))
    check("dm47 permission_mode plan passes the prompt on and starts nothing: plan "
          "mode is read-only intent and the drive starts paid writers and commits",
          code == 0 and out == "" and _calls(fx) == [],
          "code=%r out=%r err=%r calls=%r" % (code, out, err, _calls(fx)))

    # THE ALLOW DIRECTION, for the mutation that passes through on any mode.
    fx = _make(root, "mode-default", plan)
    code, out, _err = _run(fx, _payload(fx, "/audit:run P1.1",
                                        permission_mode="default"))
    check("dm48 permission_mode default drives as before",
          code == 0 and _blocks_with(out, "t") and len(_calls(fx)) == 1,
          "code=%r out=%r calls=%r" % (code, out, _calls(fx)))


# --- which tree ---------------------------------------------------------------
def _worktree_cases(check, root, real):
    plan = {"out": "t\n", "exit": real.AUTO_DONE, "status": json.dumps(STATUS_READY)}
    ok, pair = _harness.attempt(_harness.worktree_pair, "drive-without-model-wt-")
    if not ok:
        check("dm49 builds a linked worktree fixture (%s)" % (pair,), False)
        return
    _write(os.path.join(pair["main"], ".claude", "audit.config.json"),
           json.dumps(WRITER))

    def driven(name, prompt):
        fx = dict(_make(root, name, plan), project=pair["wt"])
        stdin = _payload(fx, prompt).encode("utf-8")
        env = dict(os.environ, CLAUDE_PROJECT_DIR=pair["main"])
        done = subprocess.run([sys.executable, fx["hook"]], input=stdin,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              cwd=pair["wt"], env=env, timeout=HOOK_TIMEOUT)
        return fx, done

    fx, done = driven("wt-run", "/audit:run P48.1")
    calls = _calls(fx)
    args = real.build_parser().parse_args(calls[0]["argv"]) if calls else None
    check("dm49 a session in a linked worktree drives that worktree when "
          "CLAUDE_PROJECT_DIR names the main checkout, the tree _config.tree_for "
          "answers",
          args is not None and os.path.realpath(args.project_dir or "") == pair["wt"]
          and os.path.realpath(calls[0]["project"] or "") == pair["wt"],
          "calls=%r err=%r" % (calls, done.stderr))

    fx, done = driven("wt-next", "/audit:next")
    cwd_file = os.path.join(fx["scripts"], "status-cwd")
    status_cwd = ""
    if os.path.isfile(cwd_file):
        with open(cwd_file, encoding="utf-8") as fh:
            status_cwd = os.path.realpath(fh.read())
    asked = os.path.join(fx["scripts"], "status-calls.jsonl")
    status_argv = ""
    if os.path.isfile(asked):
        with open(asked, encoding="utf-8") as fh:
            status_argv = fh.read()
    check("dm50 /audit:next in a linked worktree asks audit-status about that "
          "worktree's plan, not the main checkout's",
          status_cwd == pair["wt"] and pair["main"] + os.sep not in status_argv,
          "cwd=%r argv=%r err=%r" % (status_cwd, status_argv, done.stderr))


# --- cases --------------------------------------------------------------------
def _cases(check):
    root = _harness.fixture_root("drive-without-model-")
    real = _loader.load_script("drive-phase.py")
    _answer_cases(check, root, real)
    _table_cases(check, root, real)
    _pass_through_cases(check, root, real)
    _prefilter_cases(check, root)
    _interrupt_cases(check, root, real)
    _launcher_cases(check, root, real)
    _platform_cases(check)
    _registration_cases(check)
    _in_progress_cases(check, root, real)
    _permission_cases(check, root, real)
    _worktree_cases(check, root, real)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_drive_without_model.py --selftest\n")
    raise SystemExit(2)
