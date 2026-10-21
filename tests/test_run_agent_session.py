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

import json
import os
import shutil
import subprocess
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
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
}
argv = sys.argv[1:]
if "--agents" in argv:
    target = argv[argv.index("--agents") + 1]
    if os.path.isfile(target):
        with open(target, encoding="utf-8") as fh:
            record["agents_file"] = fh.read()
with open(os.environ["STUB_RECORD"], "w", encoding="utf-8") as fh:
    json.dump(record, fh)
mode = os.environ.get("STUB_MODE", "ok")
sid = os.environ.get("STUB_SESSION", "")
def emit(event):
    sys.stdout.write(json.dumps(event) + "\n")
emit({"type": "system", "subtype": "hook_started", "session_id": sid})
emit({"type": "system", "subtype": "init", "session_id": sid, "model": "x"})
emit({"type": "assistant", "session_id": sid,
      "message": {"content": [{"type": "text", "text": "done"}]}})
if mode == "ok":
    emit({"type": "result", "subtype": "success", "is_error": False,
          "session_id": sid, "total_cost_usd": float(os.environ["STUB_FIRST"])})
    emit({"type": "result", "subtype": "success", "is_error": False,
          "session_id": sid, "total_cost_usd": float(os.environ["STUB_LAST"])})
elif mode == "error0":
    emit({"type": "result", "subtype": "success", "is_error": True,
          "session_id": sid, "total_cost_usd": float(os.environ["STUB_LAST"])})
elif mode == "budget":
    emit({"type": "result", "subtype": "error_max_budget_usd", "is_error": True,
          "session_id": sid, "total_cost_usd": float(os.environ["STUB_LAST"])})
sys.stdout.flush()
raise SystemExit(int(os.environ.get("STUB_EXIT", "0")))
'''


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
         budget="2.5", state_is_file=False):
    """Run the script once. Returns (exit, stdout, stderr, record-or-None, dirs).

    `state_is_file` puts a regular FILE where the state dir should be, which no
    platform lets a directory be created under - the portable unwritable path."""
    tree = os.path.join(root, "tree-" + tag)
    scratch = os.path.join(root, "scratch-" + tag)
    state = os.path.join(root, "state-" + tag)
    for d in (tree, scratch) if state_is_file else (tree, scratch, state):
        os.makedirs(d)
    if state_is_file:
        with open(state, "w", encoding="utf-8") as fh:
            fh.write("not a directory\n")
    record = os.path.join(root, "record-%s.json" % tag)
    env = dict(os.environ)
    env.update({"PATH": bindir + os.pathsep + env.get("PATH", ""),
                "STUB_RECORD": record, "STUB_MODE": mode,
                "STUB_SESSION": SESSION, "STUB_FIRST": repr(FIRST_COST),
                "STUB_LAST": repr(LAST_COST), "STUB_EXIT": str(exit_code)})
    argv = [sys.executable, SCRIPT, "--role", role, "--task", "P9.1",
            "--tree", tree, "--scratch", scratch, "--state-dir", state,
            "--model", model, "--effort", "high", "--budget-usd", budget] + list(extra)
    proc = subprocess.run(argv, input=PROMPT.encode("utf-8"), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env=env, timeout=120)
    got = None
    if os.path.isfile(record):
        with open(record, encoding="utf-8") as fh:
            got = json.load(fh)
    return (proc.returncode, proc.stdout.decode("utf-8", "replace"),
            proc.stderr.decode("utf-8", "replace"), got,
            {"tree": tree, "scratch": scratch, "state": state})


def _after(argv, flag):
    """The value following `flag` in argv, or None when the flag is absent."""
    if flag not in argv:
        return None
    at = argv.index(flag)
    return argv[at + 1] if at + 1 < len(argv) else None


def _under(path, root):
    real, base = os.path.realpath(path), os.path.realpath(root)
    return real == base or real.startswith(base + os.sep)


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
              "the task's scratch",
              rec is not None and _under(rec["cwd"], dirs["tree"])
              and _under(rec["tmpdir"], dirs["scratch"])
              and os.path.realpath(rec["tmpdir"]) != os.path.realpath(dirs["scratch"]),
              repr(rec and (rec["cwd"], rec["tmpdir"])))
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
              and lines[0] == {"line": first[1].strip(), "exit": 0}
              and lines[1] == {"line": second[1].strip(), "exit": second[0]}
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
    finally:
        shutil.rmtree(root, ignore_errors=True)


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
