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
STATUS_READY = {"ready": ["P2.3", "P2.4"]}

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
import sys

here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "plan.json"), encoding="utf-8") as fh:
    plan = json.load(fh)
with open(os.path.join(here, "status-calls.jsonl"), "a", encoding="utf-8") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
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

    fx = _make(root, "none-ready", {"status": json.dumps({"ready": []})})
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
def _interrupted_run(fx, target):
    """Start the hook, wait for the stub to be running, signal `target(proc)`,
    return (exit, stdout, started)."""
    argv = target["argv"](fx)
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, cwd=fx["project"], env=_env(fx))
    proc.stdin.write(_payload(fx, "/audit:run P1.1").encode("utf-8"))
    proc.stdin.close()
    started = _wait_for(os.path.join(fx["scripts"], "started"))
    if started:
        proc.send_signal(signal.SIGTERM)
    out = proc.stdout.read().decode("utf-8", "replace")
    proc.stderr.read()
    proc.stdout.close()
    proc.stderr.close()
    return proc.wait(timeout=HOOK_TIMEOUT), out, started


def _interrupt_cases(check, root, real):
    mechanism = "the hook's SIGTERM is a posix signal it can trap and forward"
    if not hasattr(os, "killpg"):
        _harness.skip(check, "dm38", mechanism, True)
        _harness.skip(check, "dm39", mechanism, True)
        _harness.skip(check, "dm40", mechanism, True)
        return
    direct = {"argv": lambda fx: [sys.executable, fx["hook"]]}
    stop_text = "audit P1: stopped - auto-interrupted: SIGTERM arrived"
    fx = _make(root, "term", {"hold": True, "out": stop_text + "\n",
                              "exit": real.AUTO_STOP})
    code, out, started = _interrupted_run(fx, direct)
    doc = _block(out) or {}
    reason = doc.get("reason") or ""
    check("dm38 SIGTERM to the hook reaches auto, and the hook then blocks with a "
          "line saying the drive was interrupted, how to resume it, and auto's text",
          started and code == 0
          and os.path.exists(os.path.join(fx["scripts"], "terminated"))
          and doc.get("decision") == "block" and "interrupted" in reason
          and "/audit:run P1.1" in reason and stop_text in reason,
          "started=%r code=%r out=%r" % (started, code, out))

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


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_drive_without_model.py --selftest\n")
    raise SystemExit(2)
