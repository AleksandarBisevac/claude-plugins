#!/usr/bin/env python3
"""
The cases for `hooks/drive-without-model.py`, the UserPromptSubmit hook that runs
the drive itself when a typed verb's writer is a headless session.

EVERY CASE DRIVES THE REAL HOOK AS A PROCESS, in a fixture copy of the plugin's
layout: `hooks/` holds the real hook and the real `_config.py`, and `scripts/`
holds a stub `drive-phase.py`, because `_config.find_script` walks from the
`_config.py` that is running. The stub's script is a file, `plan.json` beside it:
what to print, what to exit with, whether to hold until a SIGTERM. What the hook did
is read from the stub's own record of each call, so a case can say the drive was
never started rather than infer it from silence. A stub `audit-status.py` answers
as the real one would and records being started, so a case can say the hook never
read it.

WHICH TREE A CASE EXPECTS is the real `project_context`'s answer to what the stub
recorded: its working directory, its CLAUDE_PROJECT_DIR and its argv. The hook has
no reader of its own for the drive's tree to agree with.

WHAT THIS SUITE PROVES ON WINDOWS is only that the hook stands aside. Every case
that needs the hook to act is skipped there by name, through `_harness.skip`.

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
    fh.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(),
                         "project": os.environ.get("CLAUDE_PROJECT_DIR")}) + "\\n")
if plan.get("markTree"):
    named = (sys.argv[sys.argv.index("--project-dir") + 1]
             if "--project-dir" in sys.argv else None)
    tree = named or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    with open(os.path.join(tree, "driven-here"), "w", encoding="utf-8") as fh:
        fh.write("driven")
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
import sys

here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "plan.json"), encoding="utf-8") as fh:
    plan = json.load(fh)
with open(os.path.join(here, "status-calls.jsonl"), "a", encoding="utf-8") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
sys.stdout.write(plan.get("status", ""))
sys.exit(plan.get("statusExit", 0))
"""

# Removes the mechanism the hook reads. Spelled as the mechanism rather than as
# `os.name`, because `pathlib` picks its class off that name and a hook past the
# check would find no file at all: such a run passes through for the wrong reason,
# green on a hook that never looked at the platform.
SIMULATE_NO_SIGNALS = """\
import os
import runpy
import sys

if sys.argv[1] == "no-signals":
    del os.killpg
path = sys.argv[2]
sys.path.insert(0, os.path.dirname(path))
sys.argv = [path]
runpy.run_path(path, run_name="__main__")
"""

# The hook's own `answer`, handed a parent id that is not its parent: the launcher
# having gone before the drive starts, which no signal can stage from outside.
PARENT_GONE = """\
import json
import os
import runpy
import sys

path = sys.argv[1]
sys.path.insert(0, os.path.dirname(path))
ns = runpy.run_path(path, run_name="under_test")
print(json.dumps(ns["answer"](sys.stdin.buffer.read(), os.getppid() + 1)))
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


def _run_from(fx, stdin, cwd, project):
    """(exit, stdout, stderr) of the hook started in `cwd` with `project` as
    CLAUDE_PROJECT_DIR - the session's own spelling of both, not the fixture's."""
    done = subprocess.run([sys.executable, fx["hook"]], input=stdin.encode("utf-8"),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          cwd=cwd, env=dict(os.environ, CLAUDE_PROJECT_DIR=project),
                          timeout=HOOK_TIMEOUT)
    return (done.returncode, done.stdout.decode("utf-8", "replace"),
            done.stderr.decode("utf-8", "replace"))


def _run_as(fx, stdin, mechanism):
    """(exit, stdout, stderr) of the hook with `os.killpg` removed (`no-signals`)
    or left alone (`as-is`), through the same bootstrap."""
    done = subprocess.run([sys.executable, "-c", SIMULATE_NO_SIGNALS, mechanism, fx["hook"]],
                          input=stdin.encode("utf-8"), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, cwd=fx["project"], env=_env(fx),
                          timeout=HOOK_TIMEOUT)
    return (done.returncode, done.stdout.decode("utf-8", "replace"),
            done.stderr.decode("utf-8", "replace"))


def _jsonl(path):
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _calls(fx):
    return _jsonl(os.path.join(fx["scripts"], "calls.jsonl"))


def _status_calls(fx):
    return _jsonl(os.path.join(fx["scripts"], "status-calls.jsonl"))


def _command_tree(real, record):
    """The project the real `drive-phase.py` reader settles on from what the stub
    recorded, or the ValueError it refuses with."""
    held_cwd = os.getcwd()
    held_env = os.environ.pop("CLAUDE_PROJECT_DIR", None)
    if record.get("project") is not None:
        os.environ["CLAUDE_PROJECT_DIR"] = record["project"]
    os.chdir(record["cwd"])
    try:
        args = real.build_parser().parse_args(record["argv"])
        return os.path.realpath(real.project_context(args)[1]["project"])
    except ValueError as exc:
        return "refused: %s" % (exc,)
    finally:
        os.chdir(held_cwd)
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
        if held_env is not None:
            os.environ["CLAUDE_PROJECT_DIR"] = held_env


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
          "task, in the one-task form, from the session's directory",
          len(calls) == 1 and calls[0]["argv"][:2] == ["auto", "P1.1"]
          and "--task" in calls[0]["argv"]
          and os.path.realpath(calls[0]["cwd"]) == os.path.realpath(fx["project"]),
          "calls=%r err=%r" % (calls, err))
    check("dm65 auto is started with no CLAUDE_PROJECT_DIR in its environment and "
          "no --project-dir, so it resolves its tree the way the command's Bash does",
          len(calls) == 1 and calls[0]["project"] is None
          and "--project-dir" not in calls[0]["argv"],
          "calls=%r err=%r" % (calls, err))
    check("dm2 auto's done answer blocks the prompt with auto's text as the "
          "reason and the original prompt suppressed, exit 0",
          code == 0 and _blocks_with(out, done_text), "code=%r out=%r" % (code, out))

    args = real.build_parser().parse_args(calls[0]["argv"]) if calls else None
    check("dm3 the argv the hook hands auto is one the real drive-phase.py parser "
          "accepts, naming the task and the one-task flag",
          args is not None and args.action == "auto" and args.phase == "P1.1"
          and args.task_only is True and args.project_dir is None,
          "args=%r" % (args,))

    # THE HOOK'S OWN PROCESS STANDS ELSEWHERE, so the case tells starting auto in
    # the session's directory from merely inheriting the hook's.
    fx = _make(root, "payload-cwd", {"out": "ok\n", "exit": real.AUTO_DONE})
    code, out, err = _run_from(fx, _payload(fx, "/audit:run P1.1"),
                               os.path.dirname(fx["project"]), fx["project"])
    calls = _calls(fx)
    check("dm66 auto starts in the directory the payload names as the session's, "
          "not the one the hook's own process happens to stand in",
          len(calls) == 1
          and os.path.realpath(calls[0]["cwd"]) == os.path.realpath(fx["project"]),
          "code=%r calls=%r err=%r" % (code, calls, err))

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
def _phase_verb_cases(check, root, real):
    fx = _make(root, "verb-phase", {"out": "done text\n", "exit": real.AUTO_DONE})
    code, out, err = _run(fx, _payload(fx, "/audit:phase P2"))
    calls = _calls(fx)
    args = real.build_parser().parse_args(calls[0]["argv"]) if calls else None
    check("dm8 /audit:phase <id> takes the same path as /audit:run, over the phase",
          code == 0 and _blocks_with(out, "done text") and args is not None
          and args.action == "auto" and args.phase == "P2" and args.task_only is False,
          "code=%r out=%r err=%r calls=%r" % (code, out, err, calls))


def _table_cases(check, root):
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


# --- /audit:next --------------------------------------------------------------
# Its target would have to be chosen from state the drive itself changes, so the
# hook never acts on it. Each row is a state a verb still in the table would read
# differently; the stub answers it, so a hook that asks gets told. dm70 is the
# prefilter's half: a config that raises is reached only by a prompt the hook takes.
NEXT_STATES = (
    ("dm60 with tasks ready",
     {"status": json.dumps(STATUS_READY)}, {}),
    ("dm61 with nothing ready",
     {"status": json.dumps({"ready": [], "tasks": TASKS_IDLE})}, {}),
    ("dm62 with a task already in progress",
     {"status": json.dumps({"ready": ["P2.3"],
                            "tasks": {"byStatus": {"in_progress": 1}}})}, {}),
    ("dm63 with a status that cannot answer",
     {"status": "not json", "statusExit": 2}, {}),
    ("dm70 under a config that cannot be read", {"status": json.dumps(STATUS_READY)},
     {"broken_config": True}),
)


def _next_cases(check, root, real):
    for label, plan, kwargs in NEXT_STATES:
        fx = _make(root, label.split()[0],
                   dict(plan, out="should not be seen\n", exit=real.AUTO_DONE), **kwargs)
        code, out, err = _run(fx, _payload(fx, "/audit:next"))
        check("%s: /audit:next passes on, starts nothing, reads no status and says "
              "nothing" % (label,),
              code == 0 and out == "" and err == "" and _calls(fx) == []
              and _status_calls(fx) == [],
              "code=%r out=%r err=%r calls=%r status=%r"
              % (code, out, err, _calls(fx), _status_calls(fx)))


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

    for label, cwd in (("dm67 a payload naming no working directory", None),
                       ("dm68 a working directory that does not exist", "gone")):
        fx = _make(root, label.split()[0], plan)
        doc = json.loads(_payload(fx, "/audit:run P1.1"))
        if cwd is None:
            del doc["cwd"]
        else:
            doc["cwd"] = os.path.join(fx["project"], cwd)
        code, out, _err = _run(fx, json.dumps(doc))
        check("%s cannot be told to agree with the command: passes on, no drive"
              % (label,), code == 0 and out == "" and _calls(fx) == [],
              "code=%r out=%r calls=%r" % (code, out, _calls(fx)))

    outside = _harness.fixture_root("dm-elsewhere-")
    _write(os.path.join(outside, "plan.json"), "{}\n")
    far = os.path.join(outside, "plan.json")
    fx = _make(root, "dm82", plan,
               config=dict(WRITER, manifestPath=far))
    code, out, _err = _run(fx, _payload(fx, "/audit:run P1.1"))
    check("dm82 a manifestPath outside the session's directory passes on: the "
          "drive would take that plan's tree for the project",
          code == 0 and out == "" and _calls(fx) == [],
          "code=%r out=%r calls=%r" % (code, out, _calls(fx)))

    fx = _make(root, "dm83", plan,
               config=dict(WRITER, manifestPath="sub/plan.json"))
    _write(os.path.join(fx["project"], "sub", "plan.json"), "{}\n")
    _write(os.path.join(fx["project"], "sub", ".claude", "marker"), "x")
    code, out, _err = _run(fx, _payload(fx, "/audit:run P1.1"))
    check("dm83 a manifest whose nearest project marker is not the session's "
          "directory passes on: the drive would read that directory's settings",
          code == 0 and out == "" and _calls(fx) == [],
          "code=%r out=%r calls=%r" % (code, out, _calls(fx)))

    # The command run from a subdirectory reads that subdirectory as its project and
    # finds no plan there; the hook must not find one by walking up.
    fx = _make(root, "dm69", plan)
    below = os.path.join(fx["project"], "src")
    os.makedirs(below)
    code, out, _err = _run_from(fx, _payload(dict(fx, project=below), "/audit:run P1.1"),
                                below, fx["project"])
    check("dm69 a session below the project passes on: the command resolves that "
          "directory, which holds no plan, whatever CLAUDE_PROJECT_DIR says",
          code == 0 and out == "" and _calls(fx) == [],
          "code=%r out=%r calls=%r" % (code, out, _calls(fx)))


def _drive_answer_cases(check, root, real):
    """The cases past the pass-through table that need the hook to reach auto."""
    # THE ALLOW DIRECTION OF THE OPT-OUT: a mutation reading the key as off by
    # default is red here and green in every case above.
    fx = _make(root, "opt-in", {"out": "t\n", "exit": real.AUTO_DONE},
               config=dict(WRITER, executor=dict(WRITER["executor"],
                                                 driveWithoutModel=True)))
    code, out, _err = _run(fx, _payload(fx, "/audit:run P1.1"))
    check("dm28 the opt-out key set true is the same as the key absent: the drive "
          "runs", code == 0 and _blocks_with(out, "t") and len(_calls(fx)) == 1,
          "code=%r out=%r" % (code, out))

    plan = {"out": "should not be seen\n", "exit": real.AUTO_DONE}
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

    fx = _make(root, "broken-config", {"out": "x\n", "exit": 0}, broken_config=True)
    code, out, err = _run(fx, _payload(fx, "/audit:run P1.1"))
    check("dm37 an internal error past the prefilter passes the prompt on and says "
          "so on stderr",
          code == 0 and out == "" and _calls(fx) == [] and "drive-without-model" in err,
          "code=%r out=%r err=%r" % (code, out, err))

    fx = _make(root, "mode-default", {"out": "t\n", "exit": real.AUTO_DONE})
    code, out, _err = _run(fx, _payload(fx, "/audit:run P1.1",
                                        permission_mode="default"))
    # THE ALLOW DIRECTION, for the mutation that passes through on any mode.
    check("dm48 permission_mode default drives as before",
          code == 0 and _blocks_with(out, "t") and len(_calls(fx)) == 1,
          "code=%r out=%r calls=%r" % (code, out, _calls(fx)))


# --- cost on the prompts that are not ours --------------------------------------
def _prefilter_cases(check, root):
    fx = _make(root, "prefilter", {}, broken_config=True)
    code, out, err = _run(fx, _payload(fx, "please fix the login page"))
    check("dm36 a prompt naming no verb never reaches the shared config module: a "
          "_config.py that raises on import changes nothing",
          code == 0 and out == "" and err == "",
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
    # words, so the line must not offer the prompt the user just typed as the way
    # back.
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


INTERRUPT_LABELS = ("dm38", "dm39", "dm40", "dm51", "dm54")


# --- windows ------------------------------------------------------------------
# No process on Windows can be told to stop by a signal another process sends, so
# the hook passes through there until a real run proves a stop. dm74 is the allow
# direction of the simulation: the same bootstrap with the mechanism left in place
# drives, so the silence above it comes from the mechanism and not from the
# bootstrap failing to start the hook.
def _windows_cases(check, root, real):
    for label, prompt in (("dm71 /audit:run <id>", "/audit:run P1.1"),
                          ("dm72 /audit:phase <id>", "/audit:phase P2"),
                          ("dm73 /audit:next", "/audit:next")):
        fx = _make(root, "win-%s" % (label.split()[0],),
                   {"out": "should not be seen\n", "exit": real.AUTO_DONE,
                    "status": json.dumps(STATUS_READY)})
        code, out, err = _run_as(fx, _payload(fx, prompt), "no-signals")
        check("%s on Windows passes the prompt on, starts no drive and says nothing"
              % (label,),
              code == 0 and out == "" and err == "" and _calls(fx) == []
              and _status_calls(fx) == [],
              "code=%r out=%r err=%r calls=%r" % (code, out, err, _calls(fx)))

    hook = _loader.load(os.path.join(_harness.HOOKS_DIR, HOOK_NAME))
    check("dm75 no Windows stop branch is left behind: the stop has one spelling",
          not hasattr(hook, "stop_command")
          and "taskkill" not in _harness.module_source(hook),
          sorted(n for n in dir(hook) if "stop" in n))


def _early_stop_case(check, root, real):
    fx = _make(root, "parent-gone", {"out": "should not be seen\n", "exit": real.AUTO_DONE})
    done = subprocess.run([sys.executable, "-c", PARENT_GONE, fx["hook"]],
                          input=_payload(fx, "/audit:run P1.1").encode("utf-8"),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          cwd=fx["project"], env=_env(fx), timeout=HOOK_TIMEOUT)
    doc = _block(done.stdout.decode("utf-8", "replace")) or {}
    check("dm81 a launcher already gone when the drive would start starts no drive "
          "and blocks the prompt as interrupted",
          _calls(fx) == [] and doc.get("decision") == "block"
          and "interrupted" in (doc.get("reason") or ""),
          "doc=%r calls=%r err=%r" % (doc, _calls(fx), done.stderr))


def _windows_allow_case(check, root, real):
    fx = _make(root, "win-allow", {"out": "t\n", "exit": real.AUTO_DONE})
    code, out, err = _run_as(fx, _payload(fx, "/audit:run P1.1"), "as-is")
    check("dm74 the same bootstrap with the mechanism present drives",
          code == 0 and _blocks_with(out, "t") and len(_calls(fx)) == 1,
          "code=%r out=%r err=%r calls=%r" % (code, out, err, _calls(fx)))


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


# --- permission mode ----------------------------------------------------------
def _permission_cases(check, root, real):
    plan = {"out": "t\n", "exit": real.AUTO_DONE}
    fx = _make(root, "mode-plan", plan)
    code, out, err = _run(fx, _payload(fx, "/audit:run P1.1", permission_mode="plan"))
    check("dm47 permission_mode plan passes the prompt on and starts nothing: plan "
          "mode is read-only intent and the drive starts paid writers and commits",
          code == 0 and out == "" and _calls(fx) == [],
          "code=%r out=%r err=%r calls=%r" % (code, out, err, _calls(fx)))


# --- which tree ---------------------------------------------------------------
# The linked worktree under the project, the one spot where the path-containment
# shortcut in `_config` answers before git, is the placement that disagreed; the
# sibling is the placement that always worked. Both are held to the real reader.
def _worktree_cases(check, root, real):
    plan = {"out": "t\n", "exit": real.AUTO_DONE, "markTree": True}
    ok, pair = _harness.attempt(_harness.worktree_pair, "drive-without-model-wt-")
    if not ok:
        check("dm49 builds a linked worktree fixture (%s)" % (pair,), False)
        return
    main, sibling = pair["main"], pair["wt"]
    nested = os.path.join(main, ".claude", "worktrees", "x")
    made, why = _harness.attempt(_harness.git, main, "worktree", "add", "-q", nested,
                                 "-b", "chore/nested",
                                 prefix=_harness.WORKTREE_PAIR_GIT, timeout=30)
    if not made:
        check("dm76 builds a worktree under the project (%s)" % (why,), False)
        return

    def config(tree, value):
        _write(os.path.join(tree, ".claude", "audit.config.json"), json.dumps(value))

    def drive(name, tree, prompt="/audit:run P41.1"):
        fx = dict(_make(root, name, plan), project=tree)
        return fx, _run_from(fx, _payload(fx, prompt), tree, main)

    config(main, WRITER)
    config(sibling, WRITER)
    fx, answer = drive("wt-sibling", sibling)
    calls = _calls(fx)
    check("dm49 a session in a sibling worktree drives that worktree when "
          "CLAUDE_PROJECT_DIR names the main checkout",
          len(calls) == 1 and _command_tree(real, calls[0]) == sibling,
          "calls=%r answer=%r tree=%r"
          % (calls, answer, calls and _command_tree(real, calls[0])))

    head = _harness.git(main, "rev-parse", "HEAD")
    before = _harness.git(main, "status", "--porcelain")
    config(nested, WRITER)
    fx, answer = drive("wt-nested", nested)
    calls = _calls(fx)
    check("dm76 a session in a worktree under the project drives that worktree, "
          "by the reader the command uses, with no project in auto's environment",
          len(calls) == 1 and calls[0]["project"] is None
          and "--project-dir" not in calls[0]["argv"]
          and os.path.realpath(calls[0]["cwd"]) == nested
          and _command_tree(real, calls[0]) == nested,
          "calls=%r answer=%r tree=%r"
          % (calls, answer, calls and _command_tree(real, calls[0])))
    check("dm77 the main checkout is untouched by that drive",
          not os.path.exists(os.path.join(main, "driven-here"))
          and os.path.exists(os.path.join(nested, "driven-here"))
          and _harness.git(main, "rev-parse", "HEAD") == head
          and _harness.git(main, "status", "--porcelain") == before,
          sorted(os.listdir(main)))

    # BOTH DIRECTIONS of "read from that same tree": a hook reading CLAUDE_PROJECT_DIR
    # is red in dm78 and in dm79, and one that ignores the setting is red only in dm78.
    config(main, WRITER)
    config(nested, {})
    fx, answer = drive("wt-setting-off", nested)
    check("dm78 the worktree's writerModel decides, not the main checkout's: "
          "none in the worktree, so no drive",
          answer[0] == 0 and answer[1] == "" and _calls(fx) == [],
          "answer=%r calls=%r" % (answer, _calls(fx)))

    config(main, {})
    config(nested, WRITER)
    fx, answer = drive("wt-setting-on", nested)
    check("dm79 and a writerModel only the worktree sets drives there",
          len(_calls(fx)) == 1 and _command_tree(real, _calls(fx)[0]) == nested,
          "answer=%r calls=%r" % (answer, _calls(fx)))

    config(main, WRITER)
    os.remove(os.path.join(nested, "docs", "audit", "audit-plan.json"))
    fx, answer = drive("wt-no-plan", nested)
    check("dm80 no plan in the session's own tree passes the prompt on, though the "
          "main checkout has one",
          answer[0] == 0 and answer[1] == "" and _calls(fx) == [],
          "answer=%r calls=%r" % (answer, _calls(fx)))


# --- cases --------------------------------------------------------------------
DRIVE_LABELS = (
    "dm1", "dm65", "dm2", "dm3", "dm66", "dm4", "dm5", "dm6", "dm7", "dm8", "dm28",
    "dm31", "dm32", "dm33", "dm34", "dm35", "dm37", "dm48", "dm41", "dm74", "dm49",
    "dm76", "dm77", "dm78", "dm79", "dm80", "dm81", "dm82", "dm83",
)


def _drive_cases(check, root, real):
    """Every case whose assertion needs the hook to act."""
    if not hasattr(os, "killpg"):
        for label in DRIVE_LABELS:
            _harness.skip(check, label, "the hook stands aside on Windows", True)
        return
    _answer_cases(check, root, real)
    _phase_verb_cases(check, root, real)
    _drive_answer_cases(check, root, real)
    _launcher_cases(check, root, real)
    _windows_allow_case(check, root, real)
    _early_stop_case(check, root, real)
    _worktree_cases(check, root, real)


def _cases(check):
    root = _harness.fixture_root("drive-without-model-")
    real = _loader.load_script("drive-phase.py")
    _drive_cases(check, root, real)
    _table_cases(check, root)
    _next_cases(check, root, real)
    _pass_through_cases(check, root, real)
    _prefilter_cases(check, root)
    _interrupt_cases(check, root, real)
    _windows_cases(check, root, real)
    _registration_cases(check)
    _permission_cases(check, root, real)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_drive_without_model.py --selftest\n")
    raise SystemExit(2)
