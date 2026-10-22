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
         budget="2.5", state_is_file=False, env_extra=None, scratch_dir=None):
    """Run the script once. Returns (exit, stdout, stderr, record-or-None, dirs).

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
                "STUB_LAST": repr(LAST_COST), "STUB_EXIT": str(exit_code)})
    env.update(dict((name, parent_tmp) for name in ("TMPDIR", "TEMP", "TMP")))
    env.update(env_extra or {})
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
            {"tree": tree, "scratch": scratch, "state": state, "parent_tmp": parent_tmp})


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
        # Credential names a plain top-level session inherits - the named keep list.
        kept_credentials = {"CLAUDE_CODE_OAUTH_TOKEN": "tok-q81z",
                            "CLAUDE_CODE_USE_VERTEX": "1"}
        parent = dict((name, "parent-" + name) for name in parent_session)
        parent.update(dict((name, "parent-" + name) for name in unlisted_session))
        parent.update(kept_decoys)
        parent.update(kept_credentials)
        code, out, err, rec, dirs = _run(root, bindir, "writer", tag="env",
                                         env_extra=parent)
        seen = (rec or {}).get("env") or {}
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
        unrecorded = sorted(name for name in ("ORCH_KEEP_Q81Z",)
                            if '"%s"' % name not in STUB)
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
              "with a code of its own (io-error), naming that directory, with no "
              "fallback to another place: claude was never started, no traceback, and "
              "nothing was made in it",
              e_io is not None and code == e_io and inner_tmp in out + err
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
        guide_text = guide_text[guide_at:guide_at + 6000]
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
