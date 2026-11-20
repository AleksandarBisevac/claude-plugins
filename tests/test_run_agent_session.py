#!/usr/bin/env python3
"""
The cases for `run-agent-session.py` - one role run as a headless top-level Claude
Code session, judged by what reaches the `claude` binary and by what the script
reads back out of the session's stream.

A STUB `claude` STANDS ON PATH, AND THE SCRIPT RUNS AS A COMMAND. The stub records
its argv, its stdin, its working directory, its TMPDIR and its process group into a
file, then writes a stream shaped like the one a recorded `claude -p
--output-format stream-json --verbose` session wrote: hook events and an `init`
before the turn, the `result` event last. Running the script as a subprocess rather
than calling `main()` in-process is what makes the PATH lookup, the stdin pipe and
the process group the real ones.

WHAT IS PINNED, and why each one is here rather than trusted:

- **The argv is read pair by pair** - the value that FOLLOWS `--model` must be the
  full id, the one after `--max-budget-usd` the budget - because a flag present with
  the wrong value is the shape a permissive CLI accepts and runs on.
- **The writer carries neither agent flag**, and the reviewer carries both; the
  writer's case is the one that goes red if the reviewer's flags leak into every
  role, the reviewer's the one that goes red if they are never added.
- **The prompt is a sentinel that cannot occur by accident**, checked equal on
  stdin and absent from EVERY argv element, so a prompt passed both ways is red.
- **The cost and the id come from the stream, and the fixture separates the
  readings**: two result events with different costs (a resumed session's results
  each carry the whole session's figure so far, and the last is the session's), so
  a reader of the first one prints the wrong number.
- **`--resume` is an equality on the remainder**: the argv with the resume pair
  removed must equal the plain argv exactly, so a resume that also moved or dropped
  another flag is red.
- **Each outcome's exit code is compared against every other code the module
  names**, so a budget stop or an I/O failure sharing E_SESSION's code is red, not
  only one returning some other single wrong value.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import REPO_ROOT, safe_stdio          # noqa: E402
import _loader                                     # noqa: E402

SCRIPT = os.path.join(_harness.SCRIPTS_DIR, "governance", "run-agent-session.py")
REVIEWER_MD = os.path.join(_harness._PLUGIN_DIR, "agents", "audit-reviewer.md")

MODEL = "claude-opus-5-5"
SESSION = "sess-stub-7f3a9c"
# A recorded id in the shape the CLI writes one (a UUID, as every recorded
# stream's session_id is).
RESUME_ID = "0f8e2a4c-1b3d-4e5f-9a7b-6c5d4e3f2a1b"
# Two results, the first with a decoy figure: the last result is the session's.
FIRST_COST = 0.1111
LAST_COST = 1.2345
# The time figures every stub result carries unless a case hands in others, in
# the names a recorded result event uses; the first of two results carries
# DECOY, which differs from each of these, so a reader of either result alone
# records a figure that is neither the sum nor the last.
TIMING = {"duration_ms": 48213, "duration_api_ms": 40107, "num_turns": 17}
# `duration_api_ms` grows from result to result, as it did in every recorded
# re-invoked stream read on 2026-11-18 (a writer's of 2026-11-12 went 132778,
# 175899, 192492 across its stretches), so
# the decoy's is the smaller; `duration_ms` and `num_turns` are each stretch's own.
DECOY = {"duration_ms": 1111, "duration_api_ms": 2222, "num_turns": 3}

# The prompt carries a space, both quote kinds and a non-ASCII character, so a
# prompt that went through argv or a lossy encoding cannot come back equal.
PROMPT = "PROMPT-SENTINEL-q81z do the task \"exactly\" as 'written' — then stop.\n"

STUB = r'''
import json, os, sys
record = {
    "argv": sys.argv[1:],
    "stdin": sys.stdin.buffer.read().decode("utf-8"),
    "cwd": os.getcwd(),
    "tmpdir": os.environ.get("TMPDIR", ""),
    "pid": os.getpid(),
    "pgrp": os.getpgrp() if hasattr(os, "getpgrp") else None,
    "agents_file": None,
    "skills_file": None,
    "skills_path": None,
    "env": {k: v for k, v in os.environ.items()
            if k.startswith(("CLAUDE", "AUDIT_"))
            or k in ("PATH", "HOME", "ORCH_KEEP_Q81Z", "TEMP", "TMP")},
}
argv = sys.argv[1:]
if "--agents" in argv:
    target = argv[argv.index("--agents") + 1]
    if os.path.isfile(target):
        with open(target, encoding="utf-8") as fh:
            record["agents_file"] = fh.read()
if "--append-system-prompt-file" in argv:
    target = argv[argv.index("--append-system-prompt-file") + 1]
    record["skills_path"] = target
    if os.path.isfile(target):
        with open(target, encoding="utf-8") as fh:
            record["skills_file"] = fh.read()
# A session's suites build fixtures in their TMPDIR, nested and non-empty, so a
# removal that only takes an empty directory leaves this behind.
tmp = os.environ.get("TMPDIR", "")
record["tmp_wrote"] = False
if tmp and os.path.isdir(tmp):
    deep = os.path.join(tmp, "fixture-q81z", "deep")
    os.makedirs(deep, exist_ok=True)
    with open(os.path.join(deep, "left.txt"), "w", encoding="utf-8") as fh:
        fh.write("a file the session's suites left\n")
    record["tmp_wrote"] = True
# Written whole and then renamed, so a case polling for it never reads half a file.
with open(os.environ["STUB_RECORD"] + ".part", "w", encoding="utf-8") as fh:
    json.dump(record, fh)
os.replace(os.environ["STUB_RECORD"] + ".part", os.environ["STUB_RECORD"])
mode = os.environ.get("STUB_MODE", "ok")
sid = os.environ.get("STUB_SESSION", "")
# A whole stream a case hands in as a file, written verbatim in place of every
# event below - the one way to put a shape the modes do not build on stdout.
if os.environ.get("STUB_STREAM"):
    with open(os.environ["STUB_STREAM"], encoding="utf-8") as fh:
        sys.stdout.write(fh.read())
    sys.stdout.flush()
    raise SystemExit(int(os.environ.get("STUB_EXIT", "0")))
def emit(event):
    sys.stdout.write(json.dumps(event) + "\n")
emit({"type": "system", "subtype": "hook_started", "session_id": sid})
emit({"type": "system", "subtype": "init", "session_id": sid, "model": "x"})
# Events a case hands in as a JSONL file, emitted between the init and the
# result with this session's id, as a session's own tool calls would be.
if os.environ.get("STUB_EVENTS"):
    with open(os.environ["STUB_EVENTS"], encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                emit(dict(json.loads(line), session_id=sid))
emit({"type": "assistant", "session_id": sid,
      "message": {"content": [{"type": "text", "text": "done"}]}})
# The time figures the last result carries, as a case hands them in; the first
# result of two carries the decoy figures, so a reader of one result alone
# records the wrong ones.
timing = json.loads(os.environ.get("STUB_TIMING") or "{}")
decoy = json.loads(os.environ.get("STUB_DECOY") or "{}")
# How the two results of an ok session sit against their init events, as a
# recorded re-invoked stream holds them: `paired` opens the second stretch with
# an init of its own (init, result, init, result); `unpaired` gives two results
# to the one init; `dangling` opens a second stretch that never wrote a result;
# `single` is one stretch, one result.
stretches = os.environ.get("STUB_STRETCHES") or "paired"
# Lines written verbatim between the init and the first result - JSON that is
# not an event object, which a reader of the stream meets as it is.
for raw in json.loads(os.environ.get("STUB_RAW") or "[]"):
    sys.stdout.write(raw + "\n")
if mode == "ok":
    if stretches != "single":
        emit(dict({"type": "result", "subtype": "success", "is_error": False,
                   "session_id": sid,
                   "total_cost_usd": float(os.environ["STUB_FIRST"])}, **decoy))
    if stretches in ("paired", "dangling"):
        emit({"type": "system", "subtype": "init", "session_id": sid, "model": "x"})
        emit({"type": "assistant", "session_id": sid,
              "message": {"content": [{"type": "text", "text": "woken"}]}})
    if stretches != "dangling":
        emit(dict({"type": "result", "subtype": "success", "is_error": False,
                   "session_id": sid,
                   "total_cost_usd": float(os.environ["STUB_LAST"])}, **timing))
elif mode == "error0":
    emit(dict({"type": "result", "subtype": "success", "is_error": True,
               "session_id": sid, "total_cost_usd": float(os.environ["STUB_LAST"])},
              **timing))
elif mode == "budget":
    emit(dict({"type": "result", "subtype": "error_max_budget_usd", "is_error": True,
               "session_id": sid, "total_cost_usd": float(os.environ["STUB_LAST"])},
              **timing))
elif mode == "hang":
    # A session still working when its caller gives up on it.
    sys.stdout.flush()
    import time
    time.sleep(300)
sys.stdout.flush()
raise SystemExit(int(os.environ.get("STUB_EXIT", "0")))
'''

# Two Skill calls and their results as a recorded plain writer session's stream
# holds them (claude-sonnet-5-5, 2026-11-02), trimmed to the fields a reader of
# the call uses: each call is one assistant event whose content is a `tool_use`
# named `Skill` with the skill in `input.skill`, at the top level of the session
# (`parent_tool_use_id` null). The third call is NOT from that stream: it is the
# same event with a `parent_tool_use_id`, the shape a subagent's own call has in
# the parent's stream, and the skill it loads is in the subagent's context, not
# the session's.
SKILL_EVENTS = [
    {"type": "assistant", "parent_tool_use_id": None,
     "message": {"role": "assistant", "content": [
         {"type": "tool_use", "id": "toolu_017rjURmLxTVzeffwhErF9dT", "name": "Skill",
          "input": {"skill": "writing-python"}, "caller": {"type": "direct"}}]}},
    {"type": "user", "parent_tool_use_id": None,
     "message": {"role": "user", "content": [
         {"type": "tool_result", "tool_use_id": "toolu_017rjURmLxTVzeffwhErF9dT",
          "content": "Launching skill: writing-python"}]},
     "tool_use_result": {"success": True, "commandName": "writing-python"}},
    {"type": "assistant", "parent_tool_use_id": None,
     "message": {"role": "assistant", "content": [
         {"type": "tool_use", "id": "toolu_01QvRAe1rcwUkaYrRPras5Mt", "name": "Skill",
          "input": {"skill": "before-you-claim"}, "caller": {"type": "direct"}}]}},
    {"type": "user", "parent_tool_use_id": None,
     "message": {"role": "user", "content": [
         {"type": "tool_result", "tool_use_id": "toolu_01QvRAe1rcwUkaYrRPras5Mt",
          "content": "Launching skill: before-you-claim"}]},
     "tool_use_result": {"success": True, "commandName": "before-you-claim"}},
    {"type": "assistant", "parent_tool_use_id": "toolu_0SubagentDispatchQ81z",
     "message": {"role": "assistant", "content": [
         {"type": "tool_use", "id": "toolu_0SubagentSkillQ81z", "name": "Skill",
          "input": {"skill": "no-silent-pass"}, "caller": {"type": "direct"}}]}},
]


def _install_stub(root):
    """A `claude` on a PATH directory of its own, running STUB under this
    interpreter. A shell wrapper on POSIX and a batch file on Windows, each quoting
    both paths, because the sweep's spaced leg puts TMPDIR under a directory with a
    space in it and an unquoted shebang would split there."""
    bindir = os.path.join(root, "bin")
    os.makedirs(bindir)
    stub_py = os.path.join(root, "claude_stub.py")
    with open(stub_py, "w", encoding="utf-8") as fh:
        fh.write(STUB)
    if os.name == "nt":
        with open(os.path.join(bindir, "claude.cmd"), "w", encoding="utf-8") as fh:
            fh.write('@"%s" "%s" %%*\r\n' % (sys.executable, stub_py))
    else:
        path = os.path.join(bindir, "claude")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, stub_py))
        os.chmod(path, 0o755)
    return bindir


def _run(root, bindir, role, extra=(), mode="ok", exit_code=0, model=MODEL, tag="r",
         budget="2.5", state_is_file=False, env_extra=None, scratch_dir=None,
         stop=None):
    """Run the script once. Returns (exit, stdout, stderr, record-or-None, dirs).

    `stop` names a signal (`"SIGTERM"`, `"SIGINT"`) sent to the script once the
    stub has started - what a caller's timeout or an interrupt does to a session
    still running; pair it with `mode="hang"`.

    `env_extra` is added to the script's own environment, the parent's as the
    orchestrator would hand it down.

    The parent's temp directory is one of the run's own under `root` (TMPDIR, TEMP
    and TMP all, so every platform's lookup finds it), so the session directories
    the script makes in it are removed with `root` and not left in the machine's
    temp. `env_extra` can name another.

    `scratch_dir` is the scratch to hand the script, when a case needs it somewhere
    particular; it is made here, as the drive's own would be.

    `state_is_file` puts a regular FILE where the state dir should be, which no
    platform lets a directory be created under - the portable unwritable path."""
    tree = os.path.join(root, "tree-" + tag)
    scratch = scratch_dir or os.path.join(root, "scratch-" + tag)
    state = os.path.join(root, "state-" + tag)
    parent_tmp = os.path.join(root, "tmp-" + tag)
    for d in (tree, scratch, parent_tmp) if state_is_file else (tree, scratch, state,
                                                                parent_tmp):
        os.makedirs(d, exist_ok=True)
    if state_is_file:
        with open(state, "w", encoding="utf-8") as fh:
            fh.write("not a directory\n")
    record = os.path.join(root, "record-%s.json" % tag)
    env = dict(os.environ)
    env.update({"PATH": bindir + os.pathsep + env.get("PATH", ""),
                "STUB_RECORD": record, "STUB_MODE": mode,
                "STUB_SESSION": SESSION, "STUB_FIRST": repr(FIRST_COST),
                "STUB_LAST": repr(LAST_COST), "STUB_EXIT": str(exit_code),
                "STUB_TIMING": json.dumps(TIMING), "STUB_DECOY": json.dumps(DECOY)})
    env.update(dict((name, parent_tmp) for name in ("TMPDIR", "TEMP", "TMP")))
    env.update(env_extra or {})
    argv = [sys.executable, SCRIPT, "--role", role, "--task", "P9.1",
            "--tree", tree, "--scratch", scratch, "--state-dir", state,
            "--model", model, "--effort", "high", "--budget-usd", budget] + list(extra)
    if stop is None:
        proc = subprocess.run(argv, input=PROMPT.encode("utf-8"), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=env, timeout=120)
        code, out, err = proc.returncode, proc.stdout, proc.stderr
    else:
        code, out, err = _stopped(root, tag, argv, env, record, stop)
    got = None
    if os.path.isfile(record):
        with open(record, encoding="utf-8") as fh:
            got = json.load(fh)
    return (code, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"), got,
            {"tree": tree, "scratch": scratch, "state": state, "parent_tmp": parent_tmp})


def _stopped(root, tag, argv, env, record, stop):
    """Start the script, wait for the stub's record (the session has started and
    written into its TMPDIR), send `stop` to the script's own pid, and collect it.
    The prompt is read from a file rather than a pipe so nothing is left to flush
    when the script is collected. Returns (exit, stdout bytes, stderr bytes); a
    script that outlives the signal is killed and reads as exit None."""
    prompt = os.path.join(root, "prompt-%s.txt" % tag)
    with open(prompt, "wb") as fh:
        fh.write(PROMPT.encode("utf-8"))
    with open(prompt, "rb") as stdin:
        proc = subprocess.Popen(argv, stdin=stdin, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env)
        deadline = time.time() + 60
        while (not os.path.isfile(record) and proc.poll() is None
               and time.time() < deadline):
            time.sleep(0.05)
        if proc.poll() is None:
            os.kill(proc.pid, getattr(signal, stop))
        try:
            out, err = proc.communicate(timeout=60)
            return proc.returncode, out, err
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            return None, out, err


def _session_dirs(parent_tmp):
    """The session directories left in a parent temp directory: every entry whose
    name starts `session-`, sorted."""
    if not os.path.isdir(parent_tmp):
        return []
    return sorted(n for n in os.listdir(parent_tmp) if n.startswith("session-"))


def _after(argv, flag):
    """The value following `flag` in argv, or None when the flag is absent."""
    if flag not in argv:
        return None
    at = argv.index(flag)
    return argv[at + 1] if at + 1 < len(argv) else None


def _under(path, root):
    real, base = os.path.realpath(path), os.path.realpath(root)
    return real == base or real.startswith(base + os.sep)


def _git_above(path):
    """The nearest directory above `path` (itself included) holding a `.git`, or None.
    Written out here and not asked of the script's own helper, so the case compares
    two readings; `path` is resolved first, so a symlinked temp root is judged by
    where it really lies."""
    here = os.path.realpath(path)
    while True:
        if os.path.lexists(os.path.join(here, ".git")):
            return here
        up = os.path.dirname(here)
        if up == here:
            return None
        here = up


def _tmpdir_records(scratch):
    """The session TMPDIR paths the scratch holds a record of: the content of every
    `*.tmpdir` file in it."""
    found = []
    for name in sorted(os.listdir(scratch)):
        if name.endswith(".tmpdir"):
            with open(os.path.join(scratch, name), encoding="utf-8") as fh:
                found.append(fh.read().strip())
    return found


def _fields(line):
    """`key=value` pairs of the one printed line. `stream=` is last and runs to the
    end of the line, because the sweep's spaced leg puts a space in that path."""
    head, sep, stream = line.partition(" stream=")
    out = {"stream": stream} if sep else {}
    for token in head.split():
        if "=" in token:
            key, _, value = token.partition("=")
            out[key] = value
    return out


def _reviewer_md():
    """The reviewer file's frontmatter text and body, split here by the fence alone
    - not through the script's own reader, so the case compares two readings."""
    with open(REVIEWER_MD, encoding="utf-8") as fh:
        text = fh.read()
    _, front, body = text.split("---\n", 2)
    return front, body


def _cases(check):
    check("ras0 the script exists where the plugin's entry points live",
          os.path.isfile(SCRIPT), SCRIPT)
    if not os.path.isfile(SCRIPT):
        return
    # Loaded only for its exit-code names, after ras0, so a missing script is one
    # failing case rather than an import error that hides every other case.
    M = _loader.load_script("run-agent-session.py", modname="run_agent_session")
    codes = [M.E_OK, M.E_SESSION, M.E_USAGE, M.E_COULD_NOT_RUN]
    # Read with a default so a module lacking one is a failing case, not an
    # escape that takes every later case with it.
    e_budget, e_io = getattr(M, "E_BUDGET", None), getattr(M, "E_IO", None)
    root = tempfile.mkdtemp(prefix="ras-")
    try:
        # Every run below hands the script a temp directory under `root`, and the
        # script refuses one with a `.git` above it. A suite run from a TMPDIR inside
        # a checkout would therefore fail every case with that refusal; this one
        # case names the cause instead, and the rest are not run.
        above = _git_above(root)
        check("ras59 the suite's own temp root %s has no .git above it (the ambient "
              "TMPDIR is %r); a checkout above it at %r would make the script refuse "
              "every run below" % (root, os.environ.get("TMPDIR"), above),
              above is None)
        if above is not None:
            return
        bindir = _install_stub(root)

        # --- the writer --------------------------------------------------------
        code, out, err, rec, dirs = _run(root, bindir, "writer", tag="w")
        argv = (rec or {}).get("argv") or []
        check("ras1 the writer's argv runs claude in print mode with the FULL model "
              "id, the effort, permission mode auto and stream-json output",
              rec is not None and "-p" in argv and _after(argv, "--model") == MODEL
              and _after(argv, "--effort") == "high"
              and _after(argv, "--permission-mode") == "auto"
              and _after(argv, "--output-format") == "stream-json",
              "exit %r argv %r err %r" % (code, argv, err[-300:]))
        check("ras2 ...stream-json in print mode carries --verbose: claude 2.1.305 "
              "refuses the pair without it (probed 2026-10-21: 'When using --print, "
              "--output-format=stream-json requires --verbose')",
              "--verbose" in argv, repr(argv))
        check("ras3 the writer's argv carries the caller's budget and --plugin-dir "
              "naming the running plugin",
              _after(argv, "--max-budget-usd") == "2.5"
              and _after(argv, "--plugin-dir") is not None
              and os.path.realpath(_after(argv, "--plugin-dir"))
              == os.path.realpath(_harness._PLUGIN_DIR), repr(argv))
        check("ras4 the writer's argv carries neither --agents nor --agent: the writer "
              "is a plain session, with no agent body",
              rec is not None and "--agents" not in argv and "--agent" not in argv,
              repr(argv))
        check("ras5 the writer's prompt arrives on stdin byte for byte - no agent body "
              "is prepended - and appears in no argv element",
              rec is not None and rec["stdin"] == PROMPT
              and not any("PROMPT-SENTINEL" in a for a in argv),
              repr((rec or {}).get("stdin")))
        lines = [ln for ln in out.splitlines() if ln.strip()]
        got = _fields(lines[-1]) if lines else {}
        check("ras6 it prints ONE line, and the cost on it is the LAST result event's "
              "total_cost_usd (the first result carries a decoy figure)",
              len(lines) == 1 and got.get("total_cost_usd") is not None
              and float(got["total_cost_usd"]) == LAST_COST, repr(out))
        check("ras7 ...the session id on it is the stream's, and the exit is claude's",
              got.get("session") == SESSION and got.get("exit") == "0" and code == 0,
              "exit %r out %r" % (code, out))
        check("ras19 ...and it carries the result's subtype and is_error, so a reader "
              "can tell a clean end from an error without opening the stream",
              got.get("subtype") == "success" and got.get("is_error") == "false",
              repr(out))
        stream = got.get("stream", "")
        check("ras8 the stream is saved under the state dir, holding what claude wrote",
              bool(stream) and _under(stream, dirs["state"]) and os.path.isfile(stream)
              and SESSION in open(stream, encoding="utf-8").read(), repr(stream))
        check("ras9 the session runs in the task's tree with a TMPDIR of its own under "
              "the PARENT's temp directory - not under the task's scratch, which the "
              "drive keeps inside the project",
              rec is not None and _under(rec["cwd"], dirs["tree"])
              and _under(rec["tmpdir"], dirs["parent_tmp"])
              and os.path.realpath(rec["tmpdir"]) != os.path.realpath(dirs["parent_tmp"])
              and not _under(rec["tmpdir"], dirs["scratch"]),
              repr(rec and (rec["cwd"], rec["tmpdir"], dirs["parent_tmp"])))
        if hasattr(os, "getpgrp"):
            check("ras10 the child is started in a process group of its own - its group "
                  "is not this suite's, and the child leads it",
                  rec is not None and rec["pgrp"] is not None
                  and rec["pgrp"] != os.getpgrp() and rec["pgrp"] == rec["pid"],
                  repr(rec and (rec["pgrp"], rec["pid"], os.getpgrp())))
        else:
            _harness.skip(check, "ras10 the child is started in a process group of "
                          "its own", "no os.getpgrp to read a group with",
                          not hasattr(os, "getpgrp"))

        # --- the reviewer ------------------------------------------------------
        code, out, err, rec, _d = _run(root, bindir, "reviewer", tag="v")
        argv = (rec or {}).get("argv") or []
        check("ras11 the reviewer's argv carries --agent audit-reviewer and --agents",
              _after(argv, "--agent") == "audit-reviewer"
              and _after(argv, "--agents") is not None,
              "exit %r argv %r err %r" % (code, argv, err[-300:]))
        front, body = _reviewer_md()
        agents = {}
        try:
            agents = json.loads((rec or {}).get("agents_file") or "{}")
        except ValueError:
            pass
        defn = agents.get("audit-reviewer") or {}
        check("ras12 ...and --agents is built from audit-reviewer.md: its body is the "
              "prompt with no frontmatter, its description and tools are the file's",
              defn.get("prompt", "").strip() == body.strip()
              and not defn.get("prompt", "").lstrip().startswith("---")
              and "description: '%s" % defn.get("description", "")[:40] in front
              and defn.get("tools") == ["Read", "Glob", "Grep", "Bash", "Skill"],
              repr(sorted(defn)) + " " + repr(defn.get("tools")))
        check("ras13 the reviewer's prompt arrives on stdin and is absent from argv too",
              rec is not None and rec["stdin"] == PROMPT
              and not any("PROMPT-SENTINEL" in a for a in argv),
              repr((rec or {}).get("stdin")))
        check("ras14 the reviewer shares the writer's model, effort, mode and budget",
              _after(argv, "--model") == MODEL and _after(argv, "--effort") == "high"
              and _after(argv, "--permission-mode") == "auto"
              and _after(argv, "--max-budget-usd") == "2.5", repr(argv))

        # --- no result event ---------------------------------------------------
        code, out, err, rec, dirs = _run(root, bindir, "writer", mode="noresult",
                                         tag="n")
        text = out + err
        streams = [os.path.join(dp, f) for dp, _dn, fs in os.walk(dirs["state"])
                   for f in fs if f.endswith(".jsonl")]
        check("ras15 a stream with no result event is could-not-run, names the saved "
              "stream, and exits non-zero though claude itself exited 0",
              code != 0 and "could-not-run" in text and len(streams) == 1
              and streams[0] in text and "total_cost_usd=" not in text,
              "exit %r text %r streams %r" % (code, text[-400:], streams))

        # --- a result, and a failing exit --------------------------------------
        code, out, err, rec, _d = _run(root, bindir, "writer", exit_code=1, tag="x")
        got = _fields(out.strip().splitlines()[-1]) if out.strip() else {}
        check("ras16 a session that wrote its result and exited 1 still prints its "
              "cost, prints exit=1, and the script exits E_SESSION",
              got.get("exit") == "1" and code == M.E_SESSION
              and float(got.get("total_cost_usd", "nan")) == LAST_COST,
              "exit %r out %r" % (code, out))

        # --- an error result from a claude that exited 0 -----------------------
        code, out, err, rec, _d = _run(root, bindir, "writer", mode="error0", tag="e0")
        got = _fields(out.strip().splitlines()[-1]) if out.strip() else {}
        check("ras24 a result saying is_error true is E_SESSION even when claude exited "
              "0: success needs the result's own word as well as the exit",
              code == M.E_SESSION and got.get("is_error") == "true"
              and got.get("exit") == "0", "exit %r out %r" % (code, out))

        # --- a budget stop -----------------------------------------------------
        code, out, err, rec, _d = _run(root, bindir, "writer", mode="budget",
                                       exit_code=1, tag="b")
        got = _fields(out.strip().splitlines()[-1]) if out.strip() else {}
        check("ras20 a budget stop (result subtype error_max_budget_usd, is_error, claude "
              "exit 1) has an exit code of its own - not E_SESSION's, not any other - "
              "and its line still prints the subtype, is_error, the cost and exit=1",
              e_budget is not None and code == e_budget and e_budget not in codes
              and got.get("subtype") == "error_max_budget_usd"
              and got.get("is_error") == "true" and got.get("exit") == "1"
              and float(got.get("total_cost_usd", "nan")) == LAST_COST,
              "exit %r out %r err %r" % (code, out, err[-300:]))

        # --- resume ------------------------------------------------------------
        code, out, err, rec, _d = _run(root, bindir, "writer",
                                       extra=["--resume", RESUME_ID], tag="rs")
        plain = _run(root, bindir, "writer", tag="pl")[3] or {}
        resumed = (rec or {}).get("argv") or []
        at = resumed.index("--resume") if "--resume" in resumed else -1
        rest = resumed[:at] + resumed[at + 2:] if at >= 0 else resumed
        check("ras17 --resume adds the recorded session id and changes nothing else in "
              "the argv",
              at >= 0 and resumed[at + 1] == RESUME_ID
              and rest == plain.get("argv") and len(resumed) == len(rest) + 2,
              "resumed %r plain %r" % (resumed, plain.get("argv")))

        # --- an alias is refused -----------------------------------------------
        code, out, err, rec, _d = _run(root, bindir, "writer", model="opus", tag="al")
        check("ras18 a model alias is refused before claude is started: exit 2, and the "
              "stub recorded nothing",
              code == 2 and rec is None and "opus" in err,
              "exit %r err %r rec %r" % (code, err[-200:], rec))

        # --- what is refused before claude starts ------------------------------
        for n, bad in enumerate(("--resume=--dangerously-skip-permissions",
                                 "--resume=sess-recorded-42")):
            code, out, err, rec, _d = _run(root, bindir, "writer", extra=[bad],
                                           tag="bad%d" % n)
            check("ras21 %s is refused before claude starts - a resume id has the "
                  "recorded UUID shape, so a flag cannot ride in as one: exit 2, and "
                  "the stub recorded nothing" % bad,
                  code == M.E_USAGE and rec is None,
                  "exit %r err %r rec %r" % (code, err[-200:], rec))
        for n, budget in enumerate(("inf", "Infinity", "nan", "0", "-1")):
            code, out, err, rec, _d = _run(root, bindir, "writer", budget=budget,
                                           tag="bud%d" % n)
            check("ras22 --budget-usd %s is refused: a ceiling is a finite positive "
                  "amount - exit 2, and the stub recorded nothing" % budget,
                  code == M.E_USAGE and rec is None,
                  "exit %r err %r rec %r" % (code, err[-200:], rec))

        # --- an I/O failure ----------------------------------------------------
        code, out, err, rec, dirs = _run(root, bindir, "writer", state_is_file=True,
                                         tag="io")
        check("ras23 a --state-dir nothing can be written under exits with a code of its "
              "own (not E_SESSION's, not any other), names the path, and raises no "
              "traceback - and claude was never started",
              e_io is not None and code == e_io and e_io not in codes + [e_budget]
              and dirs["state"] in out + err and "Traceback" not in err and rec is None,
              "exit %r out %r err %r" % (code, out[-300:], err[-300:]))

        # --- the environment the session starts in -------------------------------
        # The names a top-level session starts without, written out here and not
        # read from the script, so the case compares two lists.
        parent_session = ["CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_PID",
                          "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_CHILD_SESSION",
                          "CLAUDE_CODE_EXECPATH", "CLAUDE_CODE_MESSAGING_SOCKET",
                          "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_SESSION_ATTENDED",
                          "CLAUDE_CODE_SSE_PORT", "CLAUDE_EFFORT", "AUDIT_LOCK_TOKENS",
                          "CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL", "CLAUDE_PROJECT_DIR"]
        # Not session state: a provider switch a plain top-level session also
        # inherits. The prefix drop would take it without the keep list, which is
        # the over-drop this name is here to catch.
        # Every decoy name below is upper case: Windows upper-cases the keys of
        # os.environ, so a lower-case letter would reach the child as another
        # name and the stub's recorder, which filters on the exact spelling,
        # would never see it.
        kept_decoys = {"CLAUDE_CODE_USE_BEDROCK": "1", "ORCH_KEEP_Q81Z": "kept",
                       "HOME": os.path.join(root, "decoy-home")}
        # A CLAUDE_CODE_* name no list here or in the script has ever heard of - a
        # variable a later CLI release exports. A top-level session does not carry
        # it, so the writer must not either: only a prefix rule drops it.
        unlisted_session = ["CLAUDE_CODE_FUTURE_SESSION_FLAG_Q81Z"]
        # Credential names a plain top-level session inherits: every name of the
        # script's named keep list, written out here rather than read from it, so a
        # name misspelled there drops the variable and this case sees it lost - and
        # one name under the kept prefix.
        kept_credentials = {"CLAUDE_CODE_OAUTH_TOKEN": "tok-q81z",
                            "CLAUDE_CODE_API_KEY_HELPER_TTL_MS": "60000",
                            "CLAUDE_CODE_SKIP_BEDROCK_AUTH": "1",
                            "CLAUDE_CODE_SKIP_VERTEX_AUTH": "1",
                            "CLAUDE_CODE_SKIP_FOUNDRY_AUTH": "1",
                            "CLAUDE_CODE_USE_VERTEX": "1"}
        # The mark the launcher puts on the session it starts, so the config hold
        # in hooks/guard-edits.py refuses that session as it refuses a subagent.
        # Written out, not read from the script; and the parent carries the name
        # with ANOTHER value, so a launcher that only passes an inherited mark on,
        # or sets it only where absent, hands the child the parent's value.
        drive_mark, drive_value = "AUDIT_DRIVE_SESSION", "1"
        parent = dict((name, "parent-" + name) for name in parent_session)
        parent.update(dict((name, "parent-" + name) for name in unlisted_session))
        parent.update(kept_decoys)
        parent.update(kept_credentials)
        parent[drive_mark] = "parent-" + drive_mark
        code, out, err, rec, dirs = _run(root, bindir, "writer", tag="env",
                                         env_extra=parent)
        seen = (rec or {}).get("env") or {}
        check("ras31c the child session's environment carries the launcher's "
              "mark %s=%s, set by the launcher over whatever the parent carried: "
              "the child saw %r" % (drive_mark, drive_value, seen.get(drive_mark)),
              rec is not None and "env" in rec
              and seen.get(drive_mark) == drive_value, repr(seen))
        leaked_unlisted = sorted(name for name in unlisted_session if name in seen)
        check("ras30b a CLAUDE_CODE_* name on no list reaches no child either - the "
              "drop is by prefix, not by a closed list; leaked: %r" % (leaked_unlisted,),
              rec is not None and "env" in rec and not leaked_unlisted, repr(seen))
        lost_credentials = sorted(name for name, value in kept_credentials.items()
                                  if seen.get(name) != value)
        check("ras30c ...while the named credential and provider switches under the "
              "same prefix survive the drop; lost: %r" % (lost_credentials,),
              rec is not None and "env" in rec and not lost_credentials, repr(seen))
        leaked = sorted(name for name in parent_session if name in seen)
        check("ras30 the child environment carries none of the parent's Claude session "
              "variables (%d names written out in the case) - leaked: %r"
              % (len(parent_session), leaked),
              rec is not None and "env" in rec and not leaked, repr(seen))
        lost = sorted(name for name, value in kept_decoys.items()
                      if seen.get(name) != value)
        check("ras31 ...while the rest of the parent's environment is kept - PATH with "
              "the stub's directory, HOME, a provider switch and an unrelated "
              "variable - and the runner's own TMPDIR points at the session's "
              "directory; lost: %r" % (lost,),
              rec is not None and not lost and bindir in seen.get("PATH", "")
              and _under(rec["tmpdir"], dirs["parent_tmp"])
              and seen.get("TEMP") == rec["tmpdir"]
              and seen.get("TMP") == rec["tmpdir"], repr(seen))
        # What a Windows child would see: the keys of the parent's environment
        # upper-cased. Every decoy must survive that unchanged, and the stub's
        # recorder must name each kept decoy in the form it will be handed.
        decoy_names = (list(kept_decoys) + list(kept_credentials) + unlisted_session
                       + parent_session)
        shifted = sorted(name for name in decoy_names if name != name.upper())
        # The recorder takes every CLAUDE* and AUDIT_* name by prefix; any other
        # kept decoy is recorded only if the stub names it, so each is looked for.
        unrecorded = sorted(name for name in kept_decoys
                            if not name.startswith(("CLAUDE", "AUDIT_"))
                            and '"%s"' % name not in STUB)
        check("ras31b every child-environment decoy is named in upper case, so the "
              "same name reaches the child on a platform that upper-cases environment "
              "keys, and the stub's recorder filters on it; shifted: %r unrecorded: %r"
              % (shifted, unrecorded),
              decoy_names and not shifted and not unrecorded)

        # --- the session TMPDIR lies outside every checkout ------------------------
        # The drive keeps the task's scratch INSIDE the project, so a TMPDIR made under
        # it put every fixture a session's suites build inside the real checkout.
        checkout = os.path.join(root, "checkout")
        os.makedirs(os.path.join(checkout, ".git"))
        in_repo = os.path.join(checkout, ".claude", "state", "sessions", "scratch", "P9.1")
        premise = _git_above(in_repo)
        code, out, err, rec, dirs = _run(root, bindir, "writer", tag="gt",
                                         scratch_dir=in_repo)
        seen_tmp = (rec or {}).get("tmpdir") or ""
        check("ras32 with the scratch inside a git checkout the child's TMPDIR has no "
              ".git ancestor, is not under that checkout, and is a directory of its "
              "own under the parent's temp (the scratch's own ancestor is the "
              "checkout: %r)" % (premise,),
              premise is not None and os.path.realpath(premise) == os.path.realpath(checkout)
              and code == 0 and bool(seen_tmp) and _git_above(seen_tmp) is None
              and not _under(seen_tmp, checkout) and _under(seen_tmp, dirs["parent_tmp"])
              and os.path.realpath(seen_tmp) != os.path.realpath(dirs["parent_tmp"]),
              "exit %r tmpdir %r err %r" % (code, seen_tmp, err[-300:]))
        written = _tmpdir_records(in_repo)
        check("ras32b ...and the session's records stay in the scratch: one file there "
              "names the TMPDIR, so a reader finds a directory that no longer lies "
              "under it: %r" % (written,),
              rec is not None
              and [os.path.realpath(w) for w in written] == [os.path.realpath(seen_tmp)])
        shared = dict((name, os.path.join(root, "tmp-shared"))
                      for name in ("TMPDIR", "TEMP", "TMP"))
        os.makedirs(shared["TMPDIR"])
        two_scratch = os.path.join(root, "scratch-two")
        first = _run(root, bindir, "writer", tag="d1", env_extra=shared,
                     scratch_dir=two_scratch)
        second = _run(root, bindir, "writer", tag="d2", env_extra=shared,
                      scratch_dir=two_scratch)
        t1, t2 = ((x[3] or {}).get("tmpdir") or "" for x in (first, second))
        check("ras33 two sessions of one role, one scratch and one parent temp get two "
              "TMPDIRs (%r, %r), both under that parent temp, and the scratch names "
              "both" % (t1, t2),
              bool(t1) and bool(t2)
              and os.path.realpath(t1) != os.path.realpath(t2)
              and _under(t1, shared["TMPDIR"]) and _under(t2, shared["TMPDIR"])
              and sorted(os.path.realpath(w) for w in _tmpdir_records(two_scratch))
              == sorted(os.path.realpath(t) for t in (t1, t2)))
        repo2 = os.path.join(root, "checkout2")
        os.makedirs(os.path.join(repo2, ".git"))
        inner_tmp = os.path.join(repo2, "tmp")
        os.makedirs(inner_tmp)
        code, out, err, rec, dirs = _run(
            root, bindir, "writer", tag="it",
            env_extra=dict((name, inner_tmp) for name in ("TMPDIR", "TEMP", "TMP")))
        check("ras34 a parent temp directory that is itself inside a checkout is refused "
              "with a code of its own (io-error), naming that directory and telling "
              "the caller to repoint TMPDIR, with no fallback to another place: claude "
              "was never started, no traceback, and nothing was made in it",
              e_io is not None and code == e_io and inner_tmp in out + err
              and "point TMPDIR at a directory with no .git above it" in out + err
              and "Traceback" not in err and rec is None and os.listdir(inner_tmp) == [],
              "exit %r out %r err %r left %r" % (code, out[-300:], err[-300:],
                                                  os.listdir(inner_tmp)))

        # The basis of the drop list is stated where the list is, in this repository:
        # the prose naming it points at no file outside the repo (nothing here could
        # keep such a copy in step) and says what the rule drops and what it keeps.
        with open(SCRIPT, encoding="utf-8") as fh:
            script_text = fh.read()
        with open(os.path.join(REPO_ROOT, "PLUGIN-BUILD-GUIDE.md"),
                  encoding="utf-8") as fh:
            guide_text = fh.read()
        guide_at = guide_text.index("### `plugins/audit/scripts/governance/run-agent-session.py`")
        # The script's own section, to the next section's heading - a fixed
        # window cut the section short once a paragraph above the drop list grew.
        guide_end = guide_text.find("\n### ", guide_at + 1)
        guide_text = guide_text[guide_at:guide_end if guide_end > 0 else len(guide_text)]
        const_at = script_text.index("PARENT_SESSION_VARS = (")
        const_comment = script_text[script_text.rindex("\n\n", 0, const_at):const_at]
        outside = ("run-plain", "plain arm", "measurement harness", "quality-gates-internal")
        pointing = sorted(name for name in outside
                          if name in script_text or name in guide_text)
        check("ras30d the drop list's prose names no file outside this repository "
              "(%r), and states the rule - the prefix drop, the named keep list and "
              "why a top-level session starts without the names - in the script "
              "comment and in the guide; pointing: %r" % (outside, pointing),
              not pointing
              and all(word in const_comment for word in
                      ("CLAUDE_CODE_", "KEEP_SESSION_VARS", "KEEP_SESSION_PREFIXES",
                       "top-level"))
              and all(word in guide_text for word in
                      ("PARENT_SESSION_PREFIXES", "KEEP_SESSION_VARS",
                       "KEEP_SESSION_PREFIXES", "top-level")),
              "pointing %r comment %r" % (pointing, const_comment[:400]))
        # The comment names the lists' members, so it is held to them: a name added
        # to either tuple and not to the prose is red. Matched as a whole name, so
        # one name cannot pass by sitting inside a longer one.
        listed = list(M.PARENT_SESSION_VARS) + list(M.KEEP_SESSION_VARS)
        unnamed = sorted(name for name in listed if not re.search(
            r"(?<![A-Z0-9_])%s(?![A-Z0-9_])" % re.escape(name), const_comment))
        check("ras30e every name PARENT_SESSION_VARS and KEEP_SESSION_VARS hold is "
              "spelled out in the comment above them; unnamed: %r" % (unnamed,),
              bool(listed) and not unnamed)

        # --- the --record file ---------------------------------------------------
        # One JSON line per run, appended: the same printed command run twice
        # keeps both outcomes, since the driver notes each line once.
        kept = os.path.join(root, "records", "w.jsonl")
        first = _run(root, bindir, "writer", extra=["--record", kept], tag="rec1")
        second = _run(root, bindir, "writer", extra=["--record", kept], tag="rec2",
                      mode="budget")
        lines = _record_lines(kept)
        check("ras27 --record appends one line per run holding the printed line and "
              "this script's exit code, the directory made on the way: %r"
              % ((first[0], second[0], lines),),
              len(lines) == 2
              and lines[0] == dict({"line": first[1].strip(), "exit": 0,
                                    "skillsInvoked": []},
                                   **_timing_keys(first[1].strip(),
                                                  figures=_summed(DECOY, TIMING)))
              and lines[1] == dict({"line": second[1].strip(), "exit": second[0],
                                    "skillsInvoked": []},
                                   **_timing_keys(second[1].strip()))
              and second[0] == e_budget)
        refused = os.path.join(root, "records", "usage.jsonl")
        code, out, err, rec, dirs = _run(root, bindir, "writer", model="opus",
                                         extra=["--record", refused], tag="rec3")
        lines = _record_lines(refused)
        check("ras28 a usage refusal is recorded too, as `usage: <the message>` with "
              "exit 2, and claude was never started: %r" % ((code, lines, err),),
              code == 2 and rec is None and len(lines) == 1
              and lines[0]["exit"] == 2
              and lines[0]["line"].startswith("usage: --model 'opus'")
              and lines[0]["line"][len("usage: "):] in err)
        blocker = os.path.join(root, "records", "a-file")
        with open(blocker, "w", encoding="utf-8") as fh:
            fh.write("x\n")
        code, out, err, rec, dirs = _run(
            root, bindir, "writer", extra=["--record", os.path.join(blocker, "r.jsonl")],
            tag="rec4")
        check("ras29 a record that cannot be written is named on stderr and leaves "
              "the run's own exit code and line as they were: %r" % ((code, out, err),),
              code == 0 and out.startswith("session=%s " % SESSION)
              and "could not be written" in err and "Traceback" not in err)

        _timing_cases(check, M, root, bindir)
        _cleanup_cases(check, root, bindir, e_io)
        _skill_cases(check, M, root, bindir, e_io)

        # Every parent temp directory this suite handed the script, after every exit
        # path it drove - success, a failing exit, no result, a budget stop, a usage
        # refusal, an io-error, a stop signal.
        parents = sorted(os.path.join(root, n) for n in os.listdir(root)
                         if n.startswith("tmp-"))
        parents.append(inner_tmp)
        left = dict((p, _session_dirs(p)) for p in parents if _session_dirs(p))
        check("ras57 across every run this suite made, no parent temp directory "
              "(%d looked in) still holds a session directory: %r"
              % (len(parents), left),
              len(parents) > 10 and not left)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _cleanup_cases(check, root, bindir, e_io):
    """The session's own TMPDIR is removed when the session ends, however it ends.
    The stub writes a nested fixture into it, so each case also proves the
    directory existed and was not empty while the session ran - a run that never
    made the directory passes "nothing left" by construction, which is why every
    case requires `tmp_wrote`."""
    def gone(run):
        code, out, err, rec, dirs = run
        seen = (rec or {}).get("tmpdir") or ""
        return (rec is not None and rec.get("tmp_wrote") is True and bool(seen)
                and not os.path.lexists(seen)
                and _session_dirs(dirs["parent_tmp"]) == [])

    def shown(run):
        code, out, err, rec, dirs = run
        return "exit %r tmpdir %r left %r err %r" % (
            code, (rec or {}).get("tmpdir"), _session_dirs(dirs["parent_tmp"]),
            err[-300:])

    for role, tag, case in (("writer", "cw", "ras52"), ("reviewer", "cv", "ras53")):
        run = _run(root, bindir, role, tag=tag)
        check("%s a %s session that ends cleanly leaves no session temp directory "
              "behind, though its suites wrote a nested fixture into it: %s"
              % (case, role, shown(run)),
              run[0] == 0 and gone(run))

    failing = [("writer", "cx1", {"exit_code": 1}),
               ("reviewer", "cx2", {"exit_code": 1}),
               ("writer", "cx3", {"mode": "noresult"}),
               ("reviewer", "cx4", {"mode": "budget", "exit_code": 1})]
    runs = [(role, tag, _run(root, bindir, role, tag=tag, **kw))
            for role, tag, kw in failing]
    bad = [(role, tag, shown(run)) for role, tag, run in runs
           if run[0] == 0 or not gone(run)]
    check("ras54 a session that fails - claude exiting 1, no result event, a budget "
          "stop - exits non-zero and leaves no session temp directory behind, writer "
          "and reviewer alike: %r" % (bad,),
          len(runs) == len(failing) and not bad)

    # The record of the TMPDIR is written after the directory is made, so a scratch
    # nobody can write into fails the run with the directory already there.
    no_uid = not hasattr(os, "geteuid") or os.geteuid() == 0
    if no_uid:
        _harness.skip(check, "ras58 a run whose TMPDIR record cannot be written "
                      "leaves no session temp directory behind",
                      "no non-root POSIX uid, so a read-only directory is still "
                      "writable here", no_uid)
    else:
        locked = os.path.join(root, "scratch-locked")
        os.makedirs(locked)
        os.chmod(locked, 0o500)
        try:
            run = _run(root, bindir, "writer", tag="lk", scratch_dir=locked)
        finally:
            os.chmod(locked, 0o700)
        code, out, err, rec, dirs = run
        check("ras58 a run whose TMPDIR record cannot be written exits io-error naming "
              "the record, claude never started, and leaves no session temp directory "
              "behind: %s" % shown(run),
              e_io is not None and code == e_io and rec is None
              and "TMPDIR record" in out + err and locked in out + err
              and _session_dirs(dirs["parent_tmp"]) == [])

    if not hasattr(os, "killpg"):
        for case, word in (("ras55", "SIGTERM"), ("ras56", "SIGINT")):
            _harness.skip(check, "%s a session stopped by %s leaves no session temp "
                          "directory behind" % (case, word),
                          "no os.killpg: the script's group teardown on a stop "
                          "signal is POSIX-only", not hasattr(os, "killpg"))
        return
    for case, word, roles in (("ras55", "SIGTERM", ("writer", "reviewer")),
                              ("ras56", "SIGINT", ("writer",))):
        bad = []
        for role in roles:
            run = _run(root, bindir, role, tag="st-%s-%s" % (word.lower(), role),
                       mode="hang", stop=word)
            if run[0] is None or run[0] == 0 or not gone(run):
                bad.append((role, shown(run)))
        check("%s a session still running when its caller stops it with %s (what a "
              "timeout does) exits non-zero and leaves no session temp directory "
              "behind: %r" % (case, word, bad),
              not bad)


def _write_skill(base, name, body):
    """`<base>/<name>/SKILL.md` holding `body`; returns the file's path."""
    folder = os.path.join(base, name)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "SKILL.md")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(body)
    return path


def _digest(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _skill_text(name, token):
    """A SKILL.md whose description holds `<token>-DESC-k3v9` and whose body holds
    `<token>-BODY-k3v9`: the first is what a disclosed skill carries, the second
    what it must not."""
    return ("---\nname: %s\ndescription: %s-DESC-k3v9 what the skill is for\n---\n"
            "%s-BODY-k3v9\n" % (name, token, token))


def _description_of(text):
    """The `description:` line's value of a SKILL.md, its surrounding quotes
    taken off - read here by a line match, not through the script's parser, so
    the case compares two readings."""
    hit = re.search(r"^description:[ \t]*(.*)$", text, re.M)
    value = hit.group(1).strip() if hit else ""
    if len(value) > 1 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    return value


def _skill_cases(check, M, root, bindir, e_io):
    """The skills a session is started with. Every description and body is a
    sentinel that cannot occur by accident, and the project and user copies of
    `dup-skill` differ, so a resolver that took the wrong one of the two is red."""
    home = os.path.join(root, "home-sk")
    user_dir = os.path.join(home, ".claude", "skills")

    def project_dir(tag):
        """The project skills of the tree `_run` makes for `tag`."""
        return os.path.join(root, "tree-" + tag, ".claude", "skills")
    plugin_dir = os.path.join(_harness._PLUGIN_DIR, "skills")
    # An empty CLAUDE_CONFIG_DIR falls through to ~/.claude, which is HOME's.
    pinned = {"HOME": home, "USERPROFILE": home, "CLAUDE_CONFIG_DIR": ""}
    user_only = _write_skill(user_dir, "user-only", _skill_text("user-only", "USER-ONLY"))
    _write_skill(user_dir, "dup-skill", _skill_text("dup-skill", "USER-DUP"))
    dup_text = _skill_text("dup-skill", "PROJECT-DUP")
    _write_skill(project_dir("sk"), "dup-skill", dup_text)
    plugin_one = sorted(os.listdir(plugin_dir))[0]
    plugin_path = os.path.join(plugin_dir, plugin_one, "SKILL.md")
    with open(plugin_path, encoding="utf-8") as fh:
        plugin_text = fh.read()
    plugin_desc = _description_of(plugin_text)[:60]
    names = ["user-only", "dup-skill", plugin_one]
    flags = [x for n in names for x in ("--skill", n)]

    code, out, err, rec, dirs = _run(root, bindir, "writer", extra=flags, tag="sk",
                                     env_extra=pinned)
    argv = (rec or {}).get("argv") or []
    held = (rec or {}).get("skills_file") or ""
    at = [held.find(t) for t in ("USER-ONLY-DESC-k3v9", "USER-DUP-DESC-k3v9",
                                 plugin_desc)]
    check("ras35 the resolved skills reach the session as one "
          "--append-system-prompt-file under the task's scratch, holding each "
          "skill's description once in the order named, the personal copy of a "
          "name that the project also has and not the project's: %r"
          % ((code, argv, at, err[-200:]),),
          code == 0 and rec is not None and bool(plugin_desc)
          and _under(rec.get("skills_path") or "/", dirs["scratch"])
          and all(a >= 0 for a in at) and at == sorted(at)
          and held.count("USER-ONLY-DESC-k3v9") == 1
          and held.count("USER-DUP-DESC-k3v9") == 1
          and held.count("PROJECT-DUP-DESC-k3v9") == 0
          and argv.count("--append-system-prompt-file") == 1)
    check("ras36 ...each skill wrapped with its name, so a reader of the prompt can "
          "tell where one skill ends: %r" % (held[:300],),
          all(('<skill name="%s">' % n) in held for n in names)
          and held.count("</skill>") == len(names))
    check("ras37 ...and the prompt on stdin is the one given, byte for byte, in no "
          "argv element, with the skills' text in no argv element either",
          rec is not None and rec["stdin"] == PROMPT
          and not any("PROMPT-SENTINEL" in a or "k3v9" in a for a in argv))
    # The plugin skill's last line is body text unless that skill ends in a
    # checklist, which the prompt would carry; then the line is not looked for.
    plugin_tail = plugin_text.strip()[-60:]
    tail_is_body = "## Checklist" not in plugin_text
    check("ras60b ...and no skill's body reaches the prompt - neither a fixture's "
          "body sentinel nor the plugin skill's last line (looked for: %r): %r"
          % (tail_is_body, held[:300]),
          rec is not None and "BODY-k3v9" not in held
          and (not tail_is_body or plugin_tail not in held))

    # The mutation this guards: a flag added unconditionally.
    code, out, err, rec, dirs = _run(root, bindir, "writer", tag="sk0", env_extra=pinned)
    argv = (rec or {}).get("argv") or []
    check("ras38 with no --skill the argv carries no --append-system-prompt-file and "
          "no skills file is written under the scratch: %r" % (argv,),
          code == 0 and rec is not None and "--append-system-prompt-file" not in argv
          and rec["skills_file"] is None
          and not [f for f in os.listdir(dirs["scratch"]) if "skills" in f])

    code, out, err, rec, dirs = _run(root, bindir, "writer", tag="skm", env_extra=pinned,
                                     extra=["--skill", "user-only", "--skill",
                                            "no-such-skill-q81z"])
    named = [os.path.join(user_dir, "no-such-skill-q81z", "SKILL.md"),
             os.path.join(project_dir("skm"), "no-such-skill-q81z", "SKILL.md"),
             os.path.join(plugin_dir, "no-such-skill-q81z", "SKILL.md")]
    at = [err.find(p) for p in named]
    check("ras39 a skill that resolves nowhere refuses before claude starts: exit "
          "E_USAGE, the stub recorded nothing, and the message names the skill and "
          "every one of the %d places looked in, personal first, then the project's, "
          "then the plugin's: %r" % (len(named), err[-600:]),
          code == M.E_USAGE and rec is None and "no-such-skill-q81z" in err
          and all(a >= 0 for a in at) and at == sorted(at) and "Traceback" not in err)
    check("ras51 ...and the refusal says that ONLY those places are searched, so a "
          "reader does not go looking for the skill in a marketplace or another "
          "plugin: %r" % (err[-700:],),
          "only these places are searched" in err)

    # --- a plugin-qualified name resolves from that plugin alone ---------------
    for tag in ("skq", "skq2"):
        _write_skill(project_dir(tag), plugin_one, _skill_text("x", "SHADOW"))
    with open(os.path.join(_harness._PLUGIN_DIR, ".claude-plugin", "plugin.json"),
              encoding="utf-8") as fh:
        plugin_name = json.load(fh)["name"]
    code, out, err, rec, dirs = _run(root, bindir, "writer", tag="skq", env_extra=pinned,
                                     extra=["--skill", "%s:%s" % (plugin_name, plugin_one)])
    held = (rec or {}).get("skills_file") or ""
    check("ras40 `<plugin>:<skill>` is read from that plugin's own skills/ and not from "
          "a project or user skill of the same name: %r" % (held[:200],),
          code == 0 and "SHADOW-" not in held and plugin_desc in held)
    code, out, err, rec, dirs = _run(root, bindir, "writer", tag="skq2", env_extra=pinned,
                                     extra=["--skill", "other-plugin:%s" % plugin_one])
    check("ras41 ...and a name qualified by some other plugin refuses, naming it, "
          "without falling back to the project's or the user's copy: %r" % (err[-300:],),
          code == M.E_USAGE and rec is None and "other-plugin:%s" % plugin_one in err)
    code, out, err, rec, dirs = _run(root, bindir, "writer", tag="skt", env_extra=pinned,
                                     extra=["--skill", "../escape"])
    check("ras42 a name that could leave the skills directories is refused as usage: %r"
          % (err[-200:],), code == M.E_USAGE and rec is None and "../escape" in err)

    # --- the record carries each skill's digest ---------------------------------
    project_dup = _write_skill(project_dir("skr"), "dup-skill", dup_text)
    kept = os.path.join(root, "records", "sk.jsonl")
    code, out, err, rec, dirs = _run(root, bindir, "writer", tag="skr", env_extra=pinned,
                                     extra=["--record", kept, "--skill", "user-only",
                                            "--skill", "dup-skill"])
    lines = _record_lines(kept)
    listed = (lines[-1].get("skills") if lines else None) or []
    user_dup = os.path.join(user_dir, "dup-skill", "SKILL.md")
    expected = [{"name": "user-only", "path": user_only, "sha256": _digest(user_only)},
                {"name": "dup-skill", "path": user_dup, "sha256": _digest(user_dup)}]
    check("ras43 the --record line names each declared skill with its path and the "
          "sha256 of its file, in order - the personal dup-skill, whose digest "
          "differs from the project's: %r" % ((listed,),),
          code == 0 and len(lines) == 1 and listed == expected
          and expected[1]["sha256"] != _digest(project_dup))
    plain = os.path.join(root, "records", "plain.jsonl")
    _run(root, bindir, "writer", tag="skp", env_extra=pinned, extra=["--record", plain])
    check("ras44 a run with no skills records none: the line has no skills key, "
          "rather than an empty list standing for them",
          [sorted(x) for x in _record_lines(plain)]
          == [sorted(["exit", "line", "skillsInvoked"] + list(TIMING_FIELDS.values())
                     + ["startedAt"])])

    # --- the reviewer keeps its --agents body, and the skills ride beside it ----
    code, out, err, rec, dirs = _run(root, bindir, "reviewer", tag="skv", env_extra=pinned,
                                     extra=["--skill", "user-only"])
    argv = (rec or {}).get("argv") or []
    _front, body = _reviewer_md()
    try:
        defn = json.loads((rec or {}).get("agents_file") or "{}").get("audit-reviewer", {})
    except ValueError:
        defn = {}
    check("ras45 the reviewer gets the skills file AND keeps --agents/--agent with the "
          "file's own body, unchanged by the skills: %r" % ((code, argv, err[-200:]),),
          code == 0 and rec is not None
          and _after(argv, "--agent") == "audit-reviewer"
          and defn.get("prompt", "").strip() == body.strip()
          and "USER-ONLY-" not in (rec.get("agents_file") or "")
          and "USER-ONLY-DESC-k3v9" in (rec.get("skills_file") or "")
          and rec["stdin"] == PROMPT)

    # --- Claude Code's documented precedence: personal over project -------------
    # (code.claude.com/docs/en/skills, "Resolve skills that share a name": "Enterprise
    # over personal, and personal over project".) The project-only name is the other
    # direction: a resolver that stopped looking in the project would pass the
    # duplicate and fail this one.
    _write_skill(project_dir("skd"), "dup-skill", dup_text)
    _write_skill(project_dir("skd"), "project-only",
                 _skill_text("project-only", "PROJECT-ONLY"))
    code, out, err, rec, dirs = _run(root, bindir, "writer", tag="skd", env_extra=pinned,
                                     extra=["--skill", "dup-skill", "--skill", "project-only"])
    held = (rec or {}).get("skills_file") or ""
    check("ras47 a name held by both the personal and the project skills loads the "
          "PERSONAL copy once and never the project's, while a name only the project "
          "holds still loads from there: %r" % ((code, held[:400], err[-200:]),),
          code == 0 and held.count("USER-DUP-DESC-k3v9") == 1
          and held.count("PROJECT-DUP-DESC-k3v9") == 0
          and held.count("PROJECT-ONLY-DESC-k3v9") == 1)

    # A personal copy of a plugin's skill name must not answer `plugin:skill`.
    _write_skill(user_dir, plugin_one, _skill_text("x", "PERSONAL-SHADOW"))
    code, out, err, rec, dirs = _run(root, bindir, "writer", tag="skq3", env_extra=pinned,
                                     extra=["--skill", "%s:%s" % (plugin_name, plugin_one)])
    held = (rec or {}).get("skills_file") or ""
    check("ras48 `<plugin>:<skill>` is read from that plugin alone even when the "
          "personal skills hold a skill of the same bare name: %r" % (held[:200],),
          code == 0 and "PERSONAL-SHADOW-" not in held and plugin_desc in held)

    _disclosure_cases(check, root, bindir, pinned, project_dir)
    _invoked_cases(check, M, root, bindir, pinned)
    _precedence_cases(check, M, root, bindir, pinned)
    _skill_tail_cases(check, root, bindir, pinned, user_only, e_io)
    _pin_cases(check, M, root, bindir, pinned, user_dir, project_dir)


def _pin_cases(check, M, root, bindir, pinned, user_dir, project_dir):
    """A skill pinned with `--skill-pin NAME=DIGEST` starts a session only as the
    bytes pinned: every stop is the runner's usage exit before claude starts,
    naming the skill, the path it read and both digests; the matching and the
    unpinned skill start as before."""
    sibling = "print('pinned')\n"

    def plant(tag, extra=None):
        """The pinned project skill of tree `tag`, with a sibling file, and the
        digest of the bytes as planted - the pin."""
        path = _write_skill(project_dir(tag), "pinned-skill",
                            _skill_text("pinned-skill", "PINNED"))
        folder = os.path.dirname(path)
        with open(os.path.join(folder, "helper.py"), "w", encoding="utf-8",
                  newline="\n") as fh:
            fh.write(sibling)
        for rel, text in sorted((extra or {}).items()):
            with open(os.path.join(folder, rel), "w", encoding="utf-8",
                      newline="\n") as fh:
                fh.write(text)
        return path, _dir_digest(folder)

    def run(tag, flags):
        return _run(root, bindir, "writer", tag=tag, env_extra=pinned, extra=flags)

    path, digest = plant("pin-ok")
    flags = ["--skill", "pinned-skill", "--skill-pin", "pinned-skill=" + digest]
    code, out, err, rec, _dirs = run("pin-ok", flags)
    check("rap1 ALLOW: a pinned skill whose directory matches starts the session "
          "with it, as an unpinned one does: %r" % ((code, err[-300:]),),
          code == 0 and rec is not None
          and "PINNED-DESC-k3v9" in (rec.get("skills_file") or ""))

    stops = []
    for tag, change in (
            ("pin-md", lambda p: _write_text(p, _skill_text(
                "pinned-skill", "PINNED").replace("BODY-k3v9", "BODY-k3v8"))),
            ("pin-sib", lambda p: _write_text(os.path.join(os.path.dirname(p),
                                                            "helper.py"),
                                               sibling.replace("pinned", "pinneD"))),
            ("pin-add", lambda p: _write_text(os.path.join(os.path.dirname(p),
                                                            "added.md"), "x\n"))):
        path, digest = plant(tag)
        change(path)
        found = _dir_digest(os.path.dirname(path))
        code, out, err, rec, _dirs = run(tag, ["--skill", "pinned-skill",
                                               "--skill-pin", "pinned-skill=" + digest])
        stops.append((tag, code, rec is None, "pinned-skill" in err, path in err,
                       digest in err, found in err, found != digest))
    check("rap2 one changed byte in SKILL.md, one in a sibling file and a file added "
          "each refuse before claude starts - the usage exit a missing skill gets, "
          "the stub recording nothing - and the reason names the skill, the path, "
          "the pinned digest and the found one: %r" % (stops,),
          [s[1:] for s in stops]
          == [(M.E_USAGE, True, True, True, True, True, True)] * 3)

    path, digest = plant("pin-shadow")
    shadow = _write_skill(user_dir, "pinned-skill", _skill_text("pinned-skill", "MINE"))
    try:
        code, out, err, rec, _dirs = run("pin-shadow", [
            "--skill", "pinned-skill", "--skill-pin", "pinned-skill=" + digest])
    finally:
        shutil.rmtree(os.path.dirname(shadow))
    check("rap3 a personal copy shadowing the pinned project copy refuses, naming "
          "the PERSONAL path - the copy the session would have loaded: %r"
          % ((code, err[-400:]),),
          code == M.E_USAGE and rec is None and shadow in err and digest in err)

    code, out, err, rec, _dirs = run("pin-ghost", [
        "--skill", "ghost-pinned-q4", "--skill-pin", "ghost-pinned-q4=" + "a" * 64])
    check("rap4 a pinned name found nowhere refuses with the pin's words - the "
          "pinned digest and no found one - not as a pass: %r" % ((code, err[-400:]),),
          code == M.E_USAGE and rec is None and "ghost-pinned-q4" in err
          and "a" * 64 in err and "none" in err)

    path, digest = plant("pin-mixed")
    _write_skill(project_dir("pin-mixed"), "loose-skill",
                 _skill_text("loose-skill", "LOOSE"))
    code, out, err, rec, _dirs = run("pin-mixed", [
        "--skill", "pinned-skill", "--skill", "loose-skill",
        "--skill-pin", "pinned-skill=" + digest])
    check("rap5 ALLOW: an unpinned skill beside a matching pinned one is untouched "
          "and both start: %r" % ((code, err[-300:]),),
          code == 0 and rec is not None
          and "LOOSE-DESC-k3v9" in (rec.get("skills_file") or ""))

    bad = []
    # The reason is read, not only the exit: an argument parser that does not know
    # the flag refuses every one of these with the same exit, naming the value too.
    for tag, pin, why in (("pin-shape", "pinned-skill=ABC", "is not NAME=DIGEST"),
                          ("pin-other", "other-skill=" + digest,
                           "which this session is not started with"),
                          ("pin-noeq", "pinned-skill", "is not NAME=DIGEST")):
        plant(tag)
        code, out, err, rec, _dirs = run(tag, ["--skill", "pinned-skill",
                                               "--skill-pin", pin])
        bad.append((tag, code, rec is None, pin.split("=")[0] in err and why in err))
    check("rap6 a --skill-pin that is no digest, that pins a skill the session is not "
          "started with, or that has no `=` is a usage refusal naming it: %r" % (bad,),
          [b[1:] for b in bad] == [(M.E_USAGE, True, True)] * 3)


def _write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return path


def _dir_digest(folder):
    """A skill directory's digest computed here, apart from the module under test:
    SHA-256 over the sorted lines `<relative posix path> <sha256 of its bytes>`,
    CRLF read as LF in a file holding no NUL byte."""
    lines = []
    for here, _dirs, files in os.walk(folder):
        for name in files:
            full = os.path.join(here, name)
            with open(full, "rb") as fh:
                data = fh.read()
            if b"\0" not in data:
                data = data.replace(b"\r\n", b"\n")
            rel = os.path.relpath(full, folder).replace(os.sep, "/")
            lines.append("%s %s\n" % (rel, hashlib.sha256(data).hexdigest()))
    return hashlib.sha256("".join(sorted(lines)).encode("utf-8")).hexdigest()


def _skill_tail_cases(check, root, bindir, pinned, user_only, e_io):
    """The last of `_skill_cases`, run after its precedence cases: the note beside
    the flag the skills ride on, and a skill file that cannot be decoded."""
    # `claude --help` does not list the flag the skills ride on; the file must say
    # it was probed, when, and on which build, beside the flag.
    with open(SCRIPT, encoding="utf-8") as fh:
        source = fh.read()
    spot = source.find("--append-system-prompt-file")
    near = source[max(0, spot - 700):spot + 700]
    check("ras50 the script says beside --append-system-prompt-file that `claude "
          "--help` does not list it and that it was probed, with the date and the "
          "build",
          spot >= 0 and "does not list" in near and "2026-10-23" in near
          and "2.1.307" in near)
    # The first mention is the module docstring; the line that puts the flag in the
    # argv is the one a reader of the code meets, so the note must sit above it too.
    code_at = source.find('argv += ["--append-system-prompt-file"')
    above = source[max(0, code_at - 300):code_at]
    check("ras50b ...and the line that adds the flag to the argv carries the same "
          "note directly above it: %r" % (above[-300:],),
          code_at >= 0 and "does not list" in above and "2026-10-23" in above
          and "2.1.307" in above)

    # --- a skill file that cannot be read is an io-error, not a missing skill ---
    with open(user_only, "wb") as fh:
        fh.write(b"\xff\xfe not utf-8 \x80")
    code, out, err, rec, dirs = _run(root, bindir, "writer", tag="skio", env_extra=pinned,
                                     extra=["--skill", "user-only"])
    check("ras46 a name that resolves to a SKILL.md that cannot be decoded is named as "
          "an io-error with its own exit code and never as a missing skill: %r"
          % ((code, out[-200:], err[-200:]),),
          e_io is not None and code == e_io and rec is None and user_only in out + err
          and "Traceback" not in err)


LISTED_SKILL = """---
name: listed-skill
description: LISTED-DESC-k3v9 what the skill is for
---
# LISTED-TITLE-k3v9

LISTED-BODY-k3v9 the body a session loads on demand.

## Checklist

- [ ] LISTED-CHECK-k3v9 the first item
```text
## LISTED-FENCED-k3v9 a heading-shaped line inside a fence
```
### LISTED-SUB-k3v9 a subheading inside the checklist
- [ ] LISTED-LAST-k3v9 the last item

## LISTED-AFTER-HEAD-k3v9

LISTED-AFTER-k3v9 a section past the checklist.
"""

BARE_SKILL = """---
name: bare-skill
description: BARE-DESC-k3v9 what the skill is for
---
# BARE-TITLE-k3v9

BARE-BODY-k3v9 the body.

## Usage

BARE-USAGE-k3v9 a section that is not a checklist.
"""


def _elements(held):
    """`{name: inner text}` of every `<skill name="...">` element in the
    appended prompt, and the count of elements read (a name twice is two)."""
    found = re.findall(r'<skill name="([^"]+)">\n(.*?)\n</skill>', held, re.S)
    return dict(found), len(found)


def _section(text, heading):
    """The `## <heading>` section of `text` - its heading line through the line
    before the next level-one or level-two heading, or the end - read here
    without the script's reader. Fences are not looked into, which the fixtures
    the case uses this on do not need."""
    at = text.find("\n## %s\n" % heading)
    if at < 0:
        return ""
    rest = text[at + 1:]
    ends = [m.start() for m in re.finditer(r"^#{1,2} ", rest, re.M) if m.start() > 0]
    return rest[:ends[0]] if ends else rest


def _disclosure_cases(check, root, bindir, pinned, project_dir):
    """What the appended prompt holds of a skill: its name, its description and
    its `## Checklist` section when it has one - nothing of the body beside."""
    _write_skill(project_dir("sdc"), "listed-skill", LISTED_SKILL)
    _write_skill(project_dir("sdc"), "bare-skill", BARE_SKILL)
    _write_skill(project_dir("sdc"), "nodesc-skill",
                 "---\nname: nodesc-skill\n---\nNODESC-BODY-k3v9\n")
    real = os.path.join(REPO_ROOT, ".claude", "skills", "no-silent-pass", "SKILL.md")
    real_text = ""
    if os.path.isfile(real):
        with open(real, encoding="utf-8") as fh:
            real_text = fh.read()
        _write_skill(project_dir("sdc"), "no-silent-pass", real_text)
    code, out, err, rec, dirs = _run(
        root, bindir, "writer", tag="sdc", env_extra=pinned,
        extra=["--skill", "listed-skill", "--skill", "bare-skill",
               "--skill", "nodesc-skill", "--skill", "no-silent-pass"])
    held = (rec or {}).get("skills_file") or ""
    parts, count = _elements(held)
    listed = parts.get("listed-skill", "")
    present = ("LISTED-DESC-k3v9", "## Checklist", "LISTED-CHECK-k3v9",
               "LISTED-FENCED-k3v9", "LISTED-SUB-k3v9", "LISTED-LAST-k3v9")
    absent = ("LISTED-TITLE-k3v9", "LISTED-BODY-k3v9", "LISTED-AFTER-HEAD-k3v9",
              "LISTED-AFTER-k3v9")
    check("ras60 the appended prompt holds each skill once, wrapped with its name, "
          "and a skill with a Checklist section is disclosed by its description and "
          "that whole section - a fenced or deeper heading inside it included - and "
          "by no body token: counts %r, absent-but-there %r: %r"
          % (dict((t, listed.count(t)) for t in present),
             [t for t in absent if t in held], (code, listed[:400], err[-200:])),
          code == 0 and count == 4 and len(parts) == 4
          and all(listed.count(t) == 1 for t in present)
          and not [t for t in absent if t in held])
    check("ras60c ...and the prompt says, ahead of the first skill, that the Skill "
          "tool loads a skill's full instructions: %r" % (held[:300],),
          code == 0 and "Skill tool" in held[:max(0, held.find("<skill "))])
    bare = parts.get("bare-skill", "")
    check("ras61 a skill with no Checklist section is disclosed by its name and "
          "description only - no heading, no body line, no other section: %r"
          % (bare,),
          code == 0 and bare.count("BARE-DESC-k3v9") == 1 and "#" not in bare
          and "BARE-" not in bare.replace("BARE-DESC-k3v9", ""))
    nodesc = parts.get("nodesc-skill", "")
    check("ras62 a skill whose frontmatter has no description says so in its place "
          "rather than standing empty, and still carries no body: %r" % (nodesc,),
          code == 0 and "no description" in nodesc and "NODESC-BODY-k3v9" not in nodesc)
    want = _section(real_text, "Checklist").strip()
    desc = _description_of(real_text)
    title = next((ln for ln in real_text.splitlines() if ln.startswith("# ")), "")
    got = parts.get("no-silent-pass", "")
    check("ras63 the repository's own no-silent-pass, copied into the tree, is "
          "disclosed by its description and its Checklist section as the file "
          "holds them, and not by its title line %r: %r" % (title, got[:300]),
          code == 0 and bool(want) and bool(desc) and bool(title)
          and got.count(want) == 1 and got.count(desc) == 1 and title not in got)


def _invoked_cases(check, M, root, bindir, pinned):
    """The record names the skills the session invoked through the Skill tool,
    read off the saved stream."""
    events = os.path.join(root, "skill-events.jsonl")
    with open(events, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("".join(json.dumps(e) + "\n" for e in SKILL_EVENTS))
    kept = os.path.join(root, "records", "invoked.jsonl")
    code, out, err, rec, dirs = _run(
        root, bindir, "writer", tag="siv", env_extra=dict(pinned, STUB_EVENTS=events),
        extra=["--record", kept, "--skill", "user-only"])
    lines = _record_lines(kept)
    got = lines[-1].get("skillsInvoked") if lines else None
    check("ras64 the record carries skillsInvoked read from the stream's Skill "
          "tool_use calls, in the order made - and a call a subagent made, inside "
          "its own context, is not the session's: %r" % ((code, got, err[-200:]),),
          code == 0 and len(lines) == 1
          and got == ["writing-python", "before-you-claim"])
    none = os.path.join(root, "records", "none-invoked.jsonl")
    code, out, err, rec, dirs = _run(root, bindir, "writer", tag="sin", env_extra=pinned,
                                     extra=["--record", none, "--skill", "user-only"])
    lines = _record_lines(none)
    check("ras65 a stream with no Skill call records skillsInvoked as an empty list "
          "beside the declared skills: %r" % ((code, lines),),
          code == 0 and len(lines) == 1 and lines[0].get("skillsInvoked") == []
          and [s.get("name") for s in lines[0].get("skills") or []] == ["user-only"])
    refused = os.path.join(root, "records", "never-ran.jsonl")
    code, out, err, rec, dirs = _run(root, bindir, "writer", tag="sir", env_extra=pinned,
                                     model="opus", extra=["--record", refused,
                                                          "--skill", "user-only"])
    lines = _record_lines(refused)
    check("ras66 THE OTHER DIRECTION: a run that never started a session records no "
          "skillsInvoked key at all - no stream was read, so an empty list would "
          "claim a session that called nothing: %r" % ((code, lines),),
          code == M.E_USAGE and len(lines) == 1 and "skillsInvoked" not in lines[0])
    empty = os.path.join(root, "empty-stream.jsonl")
    with open(empty, "w", encoding="utf-8") as fh:
        fh.write("\n")
    torn = os.path.join(root, "torn-stream.jsonl")
    with open(torn, "w", encoding="utf-8") as fh:
        fh.write('{"type": "assist\n')
    readings = [M.invoked_skills(p) for p in (empty, torn, os.path.join(root, "gone"))]
    check("ras67 a stream holding no event - empty, or only a line that does not "
          "parse - is no reading, the same None an unreadable stream gives, never "
          "the empty list a session that called nothing gives: %r" % (readings,),
          readings == [None, None, None])
    calm = os.path.join(root, "calm-stream.jsonl")
    with open(calm, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "result", "subtype": "success"}) + "\n")
    check("ras68 THE OVER-FIRE TWIN: a stream holding an event and no Skill call "
          "reads as the empty list: %r" % (M.invoked_skills(calm),),
          M.invoked_skills(calm) == [])


# The words that find the precedence rule in the appended text. The headless
# session reads only its prompt and that text, so the rule has to say there which
# of the two wins and what the session does about a conflict.
RULE_ANCHOR = "follow the prompt"


def _sentence_with(text, words):
    """The sentence of `text` holding `words`, split here on a full stop, a
    question or an exclamation mark followed by whitespace - not through any
    reader of the script's - or "" when no sentence holds them."""
    return next((s for s in re.split(r"(?<=[.!?])\s+", text) if words in s), "")


def _precedence_cases(check, M, root, bindir, pinned):
    """Which wins when a skill and the task prompt disagree: the appended text of a
    session naming a skill says the prompt does, once, ahead of the skills, for the
    writer and the reviewer alike; a session naming no skill is handed exactly what
    it was handed before - no file, and the prompt unchanged."""
    preamble = getattr(M, "SKILLS_PREAMBLE", "")
    for role, tag in (("writer", "spw"), ("reviewer", "spv")):
        code, out, err, rec, dirs = _run(root, bindir, role, tag=tag, env_extra=pinned,
                                         extra=["--skill", "user-only"])
        held = (rec or {}).get("skills_file") or ""
        first = held.find("<skill ")
        head = held[:first] if first >= 0 else ""
        rule = _sentence_with(head, RULE_ANCHOR)
        check("ras82%s the text appended for a %s naming a skill says, ahead of the "
              "first skill and exactly once, that where a skill conflicts with the "
              "prompt the session follows the prompt and names the conflict in its "
              "closing answer - and that sentence is SKILLS_PREAMBLE's: count %d, "
              "sentence %r"
              % ("" if role == "writer" else "b", role, held.count(RULE_ANCHOR), rule),
              code == 0 and first >= 0
              and held.count(RULE_ANCHOR) == 1 and held.count("closing answer") == 1
              and "conflict" in rule and "closing answer" in rule
              and bool(rule) and rule in preamble
              and rec["stdin"] == PROMPT)
    # The baseline every measured run of a task with no skill was taken on: the
    # mutation this guards is the rule moved where a skill-less session reads it.
    code, out, err, rec, dirs = _run(root, bindir, "writer", tag="spn", env_extra=pinned)
    argv = (rec or {}).get("argv") or []
    check("ras83 THE OTHER DIRECTION: a session naming no skill is handed no appended "
          "file and the prompt byte for byte as given, the rule in neither its stdin "
          "nor its argv: %r" % ((code, argv, err[-200:]),),
          code == 0 and rec is not None and rec["skills_file"] is None
          and rec["skills_path"] is None
          and "--append-system-prompt-file" not in argv
          and rec["stdin"].encode("utf-8") == PROMPT.encode("utf-8")
          and not any(RULE_ANCHOR in a for a in argv + [rec["stdin"]]))
# The result event's time figures and the record keys each is kept under,
# written out here rather than read from the script, so a key misspelled there
# is a figure this suite sees missing.
TIMING_FIELDS = {"duration_ms": "durationMs", "duration_api_ms": "durationApiMs",
                 "num_turns": "numTurns"}
# The keys a record carried before the time figures, in the order it wrote them.
OLD_KEYS = ["line", "exit", "skillsInvoked"]
# The drive's parse of the printed line, written out here: the line keeps its
# fields, their order and their spelling, and `stream=` stays last.
DRIVE_LINE = re.compile(r"^session=(\S+) subtype=(\S+) is_error=(\S+) "
                        r"total_cost_usd=(\S+) exit=(\S+) stream=(.*)$")


def _started_of(stream):
    """The start time a stream's file name carries, as `YYYY-MM-DDTHH:MM:SSZ` -
    read here off the name's `YYYYMMDDTHHMMSSZ` stamp, not through the script."""
    hit = re.search(r"\.(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z\.",
                    os.path.basename(stream or ""))
    return "%s-%s-%sT%s:%s:%sZ" % hit.groups() if hit else None


def _timing_keys(line, timing=None, figures=None):
    """The keys a record of the printed `line` gains from a one-result stream
    carrying `timing` (TIMING by default) - or the record-named `figures`, when a
    case worked them out for a stream of several stretches - and the start time
    the line's stream name carries."""
    got = (dict(figures) if figures is not None else
           dict((TIMING_FIELDS[k], v) for k, v in (timing or TIMING).items()))
    got["startedAt"] = _started_of(_fields(line).get("stream"))
    return got


def _summed(first, last):
    """The record's figures for a two-stretch stream whose results carry `first`
    and `last`, worked out here rather than asked of the script: `duration_ms`
    and `num_turns` are each stretch's own and add up, `duration_api_ms` is the
    whole session's so far and is the last result's."""
    return {"durationMs": first["duration_ms"] + last["duration_ms"],
            "durationApiMs": last["duration_api_ms"],
            "numTurns": first["num_turns"] + last["num_turns"]}


def _stream_cost():
    """`tools/stream-cost.py`, the repository's reading of a stream's stretches,
    loaded so a case reads one stream through both copies of the pairing rule."""
    return _loader.load(os.path.join(REPO_ROOT, "tools", "stream-cost.py"),
                        modname="stream_cost_ras")


def _timing_cases(check, M, root, bindir):
    """The record carries how long the session took, read from its result events
    stretch by stretch; a figure the results do not carry as a usable number, or
    one whose stretches cannot be paired, is left out and named, never written
    as zero."""
    def recorded(tag, timing, **kw):
        kept = os.path.join(root, "records", "t-%s.jsonl" % tag)
        env = dict(kw.pop("env_extra", {}), STUB_TIMING=json.dumps(timing))
        run = _run(root, bindir, "writer", tag=tag, env_extra=env,
                   extra=["--record", kept], **kw)
        lines = _record_lines(kept)
        return run, (lines[-1] if len(lines) == 1 else None)

    figures = ("durationMs", "durationApiMs", "numTurns")
    summed = _summed(DECOY, TIMING)
    run, rec = recorded("tm", TIMING, env_extra={"STUB_STRETCHES": "single"})
    line = run[1].strip()
    stream = _fields(line).get("stream")
    started = _started_of(stream)
    check("ras69 a record written from a one-stretch stream whose result carries "
          "duration_ms, duration_api_ms and num_turns holds the three figures and "
          "the start time its stream's name carries: %r" % ((run[0], rec, started),),
          run[0] == 0 and rec is not None and started is not None
          and [rec.get(k) for k in figures] == [TIMING[k] for k in TIMING_FIELDS]
          and rec.get("startedAt") == started and "timingAbsent" not in rec)
    hit = DRIVE_LINE.match(line)
    check("ras69b ...the existing keys keep their order ahead of the new ones, and "
          "the printed line still parses as the drive reads it, its stream the "
          "real file: %r" % ((list(rec or {}), line),),
          rec is not None and list(rec)[:len(OLD_KEYS)] == OLD_KEYS
          and rec.get("line") == line and hit is not None
          and hit.group(6).strip() == stream and os.path.isfile(stream or "")
          and "durationMs" not in line and "duration_ms" not in line)

    run, rec = recorded("tn", TIMING, mode="noresult")
    absent = (rec or {}).get("timingAbsent") or {}
    streams = [os.path.join(dp, f) for dp, _dn, fs in os.walk(run[4]["state"])
               for f in fs if f.endswith(".jsonl")]
    check("ras70 a stream with no result event writes a record holding none of the "
          "three figures, naming each as absent because no result was read, a line "
          "saying no result was read, and the start time all the same: %r"
          % ((run[0], rec, streams),),
          run[0] != 0 and rec is not None and len(streams) == 1
          and not [k for k in figures if k in rec]
          and sorted(absent) == sorted(figures)
          and all("no result" in str(why) for why in absent.values())
          and "no result" in str(rec.get("line"))
          and rec.get("startedAt") == _started_of(streams[0]))

    bad = [("tstr", "a string", dict(TIMING, duration_ms="48213"), "string"),
           ("tneg", "a negative number", dict(TIMING, duration_ms=-5), "negative"),
           ("tbool", "a boolean", dict(TIMING, duration_ms=True), "not a number")]
    for tag, what, timing, word in bad:
        run, rec = recorded(tag, timing)
        absent = (rec or {}).get("timingAbsent") or {}
        check("ras71 a last result whose duration_ms is %s is recorded with no "
              "durationMs - not zero, not the value, not the first stretch's "
              "alone - and the reason names it, while the other two figures are "
              "kept: %r" % (what, (run[0], rec)),
              run[0] == 0 and rec is not None and "durationMs" not in rec
              and 0 not in [rec.get(k) for k in figures]
              and sorted(absent) == ["durationMs"]
              and word in str(absent["durationMs"]).lower()
              and "duration_ms" in str(absent["durationMs"])
              and rec.get("durationApiMs") == summed["durationApiMs"]
              and rec.get("numTurns") == summed["numTurns"])

    run, rec = recorded("tnone", {})
    absent = (rec or {}).get("timingAbsent") or {}
    check("ras71b a result carrying none of the three figures names each as absent "
          "with the result's own field name, and writes no figure: %r"
          % ((run[0], rec),),
          run[0] == 0 and rec is not None and not [k for k in figures if k in rec]
          and sorted(absent) == sorted(figures)
          and all(src in str(absent[dst]) for src, dst in TIMING_FIELDS.items()))

    # Two refusals at two points: a usage refusal before the skills are read, and
    # an io-error once they are and before claude starts - a figure set anywhere
    # between reading the skills and starting the session is red on the second.
    used, used_rec = recorded("tuse", TIMING, model="opus")
    failed, io_rec = recorded("tio", TIMING, state_is_file=True)
    check("ras72 THE OTHER DIRECTION: a run refused before any session started - a "
          "usage refusal, an io-error - records no figure, no start time and no "
          "absence: there was no session to time: %r"
          % ((used[0], used_rec, failed[0], io_rec),),
          used[0] == M.E_USAGE and used_rec is not None
          and sorted(used_rec) == ["exit", "line"]
          and failed[0] == M.E_IO and io_rec is not None
          and sorted(io_rec) == ["exit", "line"] and failed[3] is None)

    # The drive reads a record written before the time figures existed as it
    # reads one carrying them: the same reading but for the two figures the drive
    # times a session by - None for the old record, the recorded values for the
    # new - and the same note.
    D = _loader.load_script("drive-phase.py", modname="drive_phase_ras73")
    run, rec = recorded("tdr", TIMING)
    old = dict((k, v) for k, v in (rec or {}).items() if k in OLD_KEYS)
    paths = []
    for name, body in (("new", rec), ("old", old)):
        path = os.path.join(root, "records", "drive-%s.jsonl" % name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(body) + "\n")
        paths.append(path)
    readings = [D.read_sessions(p) for p in paths]
    notes = [D.session_note(1, r[0]) if len(r) == 1 else None for r in readings]
    first = readings[1][0] if len(readings[1]) == 1 else {}
    timed = ("startedAt", "durationMs")
    bare = [[dict((k, v) for k, v in r.items() if k not in timed) for r in each]
            for each in readings]
    figures = [[tuple(r.get(k) for k in timed) for r in each] for each in readings]
    check("ras73 a record with none of the new keys is read by the drive as before - "
          "the session, the cost and the stream off its line - and identically to "
          "the same record carrying them but for the start and the duration, which "
          "it reads as absent there, note included: %r" % ((readings, notes),),
          rec is not None and sorted(old) == sorted(OLD_KEYS)
          and bare[0] == bare[1] and notes[0] == notes[1]
          and figures[1] == [(None, None)]
          and figures[0] == [(rec.get("startedAt"), summed["durationMs"])]
          and rec.get("startedAt")
          and notes[0] is not None and first.get("session") == SESSION
          and float(first.get("cost") or "nan") == LAST_COST
          and first.get("stream") == _fields(run[1].strip()).get("stream"))

    named = tuple(TIMING_FIELDS[k] for k in TIMING)
    _stretch_cases(check, recorded, named, summed)
    _unusable_cases(check, M, recorded, named, summed)
    _table_cases(check, root, recorded)
    _nested_cases(check, root, recorded)


def _stream_reading(stream):
    """(duration_ms, num_turns, paired) as `tools/stream-cost.py` reads `stream`:
    its session result's two per-stretch counts, and whether its init events pair
    one to one with its result events - None when the tool cannot read it."""
    SC = _stream_cost()
    try:
        session = SC.parse(SC.load_events(stream))
    except (OSError, ValueError):
        return None
    result = session.get("result") or {}
    return (result.get("duration_ms"), result.get("num_turns"),
            SC.main_stretches(session)[1] is None)


def _stretch_cases(check, recorded, figures, summed):
    """A session woken by a background task runs in stretches, each opening with
    an init and closing with a result of its own; the record holds the whole
    session, and the repository's stream reader is asked the same stream."""
    run, rec = recorded("ts2", TIMING)
    stream = _fields(run[1].strip()).get("stream")
    tool = _stream_reading(stream)
    check("ras74 a stream of two paired stretches records the SUM of their "
          "duration_ms and num_turns - neither stretch's alone - and the last "
          "result's duration_api_ms, the whole session's; tools/stream-cost.py "
          "reads the same stream to the same two sums: %r"
          % ((run[0], rec, tool),),
          run[0] == 0 and rec is not None and "timingAbsent" not in rec
          and dict((k, rec.get(k)) for k in figures) == summed
          and tool == (summed["durationMs"], summed["numTurns"], True))

    for tag, shape, inits, results in (("tun", "unpaired", 1, 2),
                                       ("tdang", "dangling", 2, 1)):
        run, rec = recorded(tag, TIMING, env_extra={"STUB_STRETCHES": shape})
        absent = (rec or {}).get("timingAbsent") or {}
        stream = _fields(run[1].strip()).get("stream")
        tool = _stream_reading(stream) if shape == "unpaired" else None
        why = [str(absent.get(k)) for k in ("durationMs", "numTurns")]
        check("ras75 a stream of %d init events and %d result events (%s) "
              "cannot be split into stretches: durationMs and numTurns are left "
              "out and named with that reason, the init and result counts in it, "
              "while durationApiMs - a whole-session figure - is kept%s: %r"
              % (inits, results, shape,
                 "; tools/stream-cost.py reads the same stream as unpaired"
                 if shape == "unpaired" else "", (run[0], rec, tool)),
              run[0] == 0 and rec is not None
              and "durationMs" not in rec and "numTurns" not in rec
              and sorted(absent) == ["durationMs", "numTurns"]
              and all("init" in w and "result" in w and str(inits) in w
                      and str(results) in w for w in why)
              and rec.get("durationApiMs") == (TIMING if results == 2
                                               else DECOY)["duration_api_ms"]
              and (shape != "unpaired" or (tool is not None and tool[2] is False)))


def _unusable_cases(check, M, recorded, figures, summed):
    """A figure no float can hold is not a usable number, and whatever the
    stream holds, the reading of the time figures cannot stop the runner from
    printing its line and writing its record."""
    huge = 10 ** 400
    runs = (("thuge1", dict(TIMING, duration_ms=huge), DECOY, ["durationMs"]),
            ("thuge2", dict(TIMING, duration_api_ms=huge),
             dict(DECOY, num_turns=huge), ["durationApiMs", "numTurns"]))
    for tag, last, first, gone in runs:
        run, rec = recorded(tag, last, env_extra={"STUB_DECOY": json.dumps(first)})
        absent = (rec or {}).get("timingAbsent") or {}
        line = run[1].strip()
        check("ras76 an integer too large for a float in %s is recorded as "
              "absent with that reason, the other figures kept, and the runner "
              "still exits 0, prints its line and writes its record: %r"
              % (" and ".join(gone), (run[0], line, rec, run[2][-300:])),
              run[0] == 0 and DRIVE_LINE.match(line) is not None
              and rec is not None and rec.get("line") == line
              and sorted(absent) == sorted(gone)
              and all("too large" in str(absent[k]) for k in gone)
              and not [k for k in gone if k in rec]
              and all(rec.get(k) == summed[k] for k in figures if k not in gone))

    # JSON that is not an event object is no init and no result: a count that
    # took it for one, or a reader that asked it for a type, loses the sums.
    raw = ["[1, 2]", '"text"', "7", "null"]
    run, rec = recorded("traw", TIMING, env_extra={"STUB_RAW": json.dumps(raw)})
    line = run[1].strip()
    check("ras77 a stream holding JSON lines that are not event objects is read "
          "past them: the two paired stretches still record their sums, nothing "
          "named absent: %r" % ((run[0], line, rec, run[2][-300:]),),
          run[0] == 0 and DRIVE_LINE.match(line) is not None
          and rec is not None and rec.get("line") == line
          and "timingAbsent" not in rec
          and dict((k, rec.get(k)) for k in figures) == summed)

    # The reading itself failing, whatever made it fail: a reading of the stream
    # whose result list is not a list stands for every input no branch foresaw.
    stream = os.path.join("sessions", "P9.1.writer.20261118T010203Z.42.jsonl")
    broken = {"last": dict(TIMING, type="result"), "results": 7, "inits": 1,
              "problem": None}
    got = _harness.attempt(lambda: M.session_timing(broken, stream))
    held = got[1] if got[0] and isinstance(got[1], dict) else {}
    absent = held.get("absent") or {}
    check("ras78 a timing reading that raises does not raise out of "
          "session_timing: each figure is named absent with the failure in its "
          "reason, and the start stamp is still recorded: %r" % (got,),
          got[0] is True and sorted(absent) == sorted(figures)
          and all("could not be read" in str(absent[k]) and "TypeError" in str(absent[k])
                  for k in figures)
          and held.get("figures") == {"startedAt": "2026-11-18T01:02:03Z"})


# --- one table of streams, two readers ----------------------------------------
# Each row is a stream written out event by event, what the runner's record holds
# for it, and what tools/stream-cost.py reports for it - both as values here,
# never asked of either code. The two readers do not have to agree, and where
# they differ the row says how; what a row may not do is leave a reader's
# reading unwritten, so a sentence about how the two compare has this table to
# answer to.
_R1 = {"duration_ms": 1000, "duration_api_ms": 900, "num_turns": 3}
_R2 = {"duration_ms": 5000, "duration_api_ms": 4000, "num_turns": 10}


def _ev_init(uid):
    return {"type": "system", "subtype": "init", "session_id": SESSION,
            "model": "x", "uuid": uid}


def _ev_result(uid, figures, cost):
    return dict({"type": "result", "subtype": "success", "is_error": False,
                 "session_id": SESSION, "total_cost_usd": cost, "uuid": uid},
                **figures)


_EV_TEXT = {"type": "assistant", "session_id": SESSION, "uuid": "u-text",
            "message": {"content": [{"type": "text", "text": "done"}]}}
_FIGURES = ["durationMs", "durationApiMs", "numTurns"]
# (tag, what the stream is, its events, the runner's figures, the names the
# runner records as absent, the tool's (duration_ms, num_turns, paired)).
STREAM_TABLE = [
    ("xpair", "two paired stretches",
     [_ev_init("u-i1"), _ev_result("u-r1", _R1, 0.5),
      _ev_init("u-i2"), _ev_result("u-r2", _R2, 1.25)],
     {"durationMs": 6000, "durationApiMs": 4000, "numTurns": 13}, [],
     (6000, 13, True)),
    # The runner is the stricter reader here: two results under one init cannot
    # be split into stretches, so it records neither per-stretch sum, where the
    # tool adds both results up and says the stream is unpaired.
    ("xunp", "one init with two results",
     [_ev_init("u-i1"), _ev_result("u-r1", _R1, 0.5), _ev_result("u-r2", _R2, 1.25)],
     {"durationApiMs": 4000}, ["durationMs", "numTurns"],
     (6000, 13, False)),
    # A result repeated under one uuid is one event read twice: both readers
    # drop the copy, so the stream is the two paired stretches again.
    ("xdup", "two paired stretches, the last result repeated under one uuid",
     [_ev_init("u-i1"), _ev_result("u-r1", _R1, 0.5),
      _ev_init("u-i2"), _ev_result("u-r2", _R2, 1.25), _ev_result("u-r2", _R2, 1.25)],
     {"durationMs": 6000, "durationApiMs": 4000, "numTurns": 13}, [],
     (6000, 13, True)),
    ("xone", "a single stretch",
     [_ev_init("u-i1"), _EV_TEXT, _ev_result("u-r2", _R2, 1.25)],
     {"durationMs": 5000, "durationApiMs": 4000, "numTurns": 10}, [],
     (5000, 10, True)),
    # No result: the runner names all three figures absent; the tool has no
    # result to report and, with none to pair, does not call the stream unpaired.
    ("xnone", "no result at all",
     [_ev_init("u-i1"), _EV_TEXT],
     {}, _FIGURES,
     (None, None, True)),
]


def _tool_reading(stream):
    """(duration_ms, num_turns, paired) as tools/stream-cost.py reads `stream`,
    a stream with no result included: its result's two per-stretch counts, None
    each when it has none, and whether its inits and results pair."""
    SC = _stream_cost()
    session = SC.parse(SC.load_events(stream))
    result = session.get("result") or {}
    return (result.get("duration_ms"), result.get("num_turns"),
            SC.main_stretches(session)[1] is None)


def _table_cases(check, root, recorded):
    """Every row of STREAM_TABLE run through the runner and through the tool,
    and both readings held to the row."""
    os.makedirs(os.path.join(root, "streams"), exist_ok=True)
    for tag, what, events, figures, absent, tool_want in STREAM_TABLE:
        path = os.path.join(root, "streams", tag + ".jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("".join(json.dumps(e) + "\n" for e in events))
        run, rec = recorded(tag, {}, env_extra={"STUB_STREAM": path})
        rec = rec or {}
        got = dict((k, rec.get(k)) for k in _FIGURES if k in rec)
        gone = sorted(rec.get("timingAbsent") or {})
        # The tool reads the file the stub wrote verbatim: a run with no result
        # prints a could-not-run line, which carries no `stream=` field.
        tool = _harness.attempt(lambda: _tool_reading(path))
        check("ras79 STREAM TABLE, %s: the runner records %r with %r absent, "
              "and tools/stream-cost.py reports %r - both as written in the "
              "table: %r" % (what, figures, absent, tool_want,
                             (run[0], got, gone, tool, run[2][-300:])),
              bool(rec) and got == figures and gone == sorted(absent)
              and tool == (True, tool_want))


def _too_deep():
    """(line, "RecursionError") for the shallowest nested array this interpreter
    refuses to parse, or (line, None) when none up to the last depth tried is.

    Stepped up rather than fixed: up to 3.13 the parser stops at the recursion
    limit, while 3.14 measures its C stack and parses a line a hundred thousand
    deep. The runner runs under this same interpreter, so the depth found here is
    one its reader meets too - and a fixture that parsed would leave the case
    proving nothing about a reader that catches ValueError alone."""
    line = ""
    for depth in (10 ** 4, 10 ** 5, 10 ** 6, 10 ** 7):
        line = "[" * depth + "]" * depth
        try:
            json.loads(line)
        except RecursionError:
            return line, "RecursionError"
        except ValueError:
            return line, None
    return line, None


def _nested_cases(check, root, recorded):
    """A line JSON cannot parse for a reason other than a malformed value - one
    nested past the interpreter's limit - is a line the runner counts and reads
    past, not one that ends it after the session ran. The line runs to megabytes
    on 3.14, past what an environment variable carries, so it reaches the stub as
    a stream file."""
    deep, kind = _too_deep()

    def stream(tag, lines):
        path = os.path.join(root, "streams", tag + ".jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("".join(ln + "\n" for ln in lines))
        return recorded(tag, {}, env_extra={"STUB_STREAM": path})

    paired = [_ev_init("u-i1"), _ev_result("u-r1", _R1, 0.5),
              _ev_init("u-i2"), _ev_result("u-r2", _R2, 1.25)]
    run, rec = stream("tdeep", [json.dumps(paired[0]), deep]
                      + [json.dumps(e) for e in paired[1:]])
    line = run[1].strip()
    check("ras80 a stream holding a line nested too deep to parse (%s, not a "
          "ValueError) is read past it: the runner exits 0, prints its line, "
          "and records the two paired stretches' sums: %r"
          % (kind, (run[0], line[:200], rec, run[2][-300:])),
          kind == "RecursionError" and run[0] == 0 and DRIVE_LINE.match(line) is not None
          and rec is not None and rec.get("line") == line
          and "timingAbsent" not in rec
          and dict((k, rec.get(k)) for k in _FIGURES)
          == {"durationMs": 6000, "durationApiMs": 4000, "numTurns": 13})
    run, rec = stream("tdeepn", [json.dumps(paired[0]), deep, "{not json"])
    line = run[1].strip()
    check("ras81 ...and it is COUNTED as unparsed beside a malformed line: a "
          "stream with no result names both lines in its printed line, which "
          "is still printed and recorded: %r" % ((run[0], line, rec),),
          run[0] != 0 and "2 line(s) of it could not be parsed as JSON" in line
          and rec is not None and rec.get("line") == line)


def _record_lines(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return [json.loads(ln) for ln in fh if ln.strip()]
    except (OSError, ValueError):
        return []


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_run_agent_session.py --selftest\n")
    raise SystemExit(2)
