#!/usr/bin/env python3
"""
The cases for `_proc_group.py` - one child tree stopped whole, and a stop signal
turned into an exception so a caller's `finally` runs.

`test_run_test_gate.py` drives the teardown through the gate, which is where it
was first written and where most of its cases still live; what is pinned here is
the property the move was for: both entry points reach THIS module's objects, so
there is one teardown and not two that can come to disagree.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import json
import ntpath
import os
import signal
import subprocess
import sys
import time

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _proc_group as M                            # noqa: E402
import _loader                                     # noqa: E402

GATE = _loader.load_script("run-test-gate.py", modname="rtg_for_proc_group")
RED = _loader.load_script("stamp-verification.py", modname="sv_for_proc_group")
DERIVE = _loader.load_script("derive-phase-gate.py", modname="dpg_for_proc_group")

# A Windows-shaped install. The Windows cases read it through `ntpath` on EVERY
# host, so the bytes they expect are one spelling - backslashes - whether the
# suite runs on macOS, Linux or Windows; read through the host's `os.path` the
# expectation had been posix-spelled on one host and ntpath-spelled on another.
_GIT_ROOT = "C:\\Program Files\\Git"
_WIN_ENV = {"SystemRoot": "C:\\Windows"}
_BESIDE_PATH = (_GIT_ROOT + "\\usr\\bin", _GIT_ROOT + "\\mingw64\\bin")


def _fake_fs(files, path_hits, pathmod=ntpath):
    """`(isfile, which)` over an invented machine: `files` exist, and `which`
    answers from `path_hits` - no real filesystem or PATH is read. Paths are
    compared the way `pathmod` compares them, so `C:/x` and `c:\\X` are one
    file under `ntpath`, as they are on Windows."""
    def key(path):
        return pathmod.normcase(pathmod.normpath(path))
    norm = set(key(f) for f in files)

    def isfile(path):
        return key(path) in norm

    def which(name):
        return path_hits.get(name)
    return isfile, which


def _beside_git_cases(check):
    """The shell found beside `git` is the one run from a native process, so it
    is the one that owes its child the PATH a Git Bash would have given it."""
    git = _GIT_ROOT + "\\cmd\\git.exe"
    wrapper = _GIT_ROOT + "\\bin\\sh.exe"
    inner = _GIT_ROOT + "\\usr\\bin\\sh.exe"
    isfile, which = _fake_fs([wrapper, inner], {"git": git})
    got = M.locate_sh(isfile, which, _WIN_ENV, ntpath)
    check("pg15 BOTH SPELLINGS BESIDE `git`: `bin\\sh.exe` is preferred over "
          "`usr\\bin\\sh.exe`, and the shell comes with `<root>\\usr\\bin` and "
          "`<root>\\mingw64\\bin` for its child's PATH - without them a plan's "
          "`find`/`sort` resolve to System32's and `grep`/`sed` are missing "
          "(mutation: usr\\bin first again, or no entries -> red): %r" % (got,),
          got == (wrapper, _BESIDE_PATH, None))

    isfile, which = _fake_fs([inner], {"git": git})
    got = M.locate_sh(isfile, which, _WIN_ENV, ntpath)
    check("pg16 ...and the `usr\\bin` spelling alone, still beside `git`, owes "
          "its child the same PATH entries: %r" % (got,),
          got == (inner, _BESIDE_PATH, None))

    # THE ALLOW DIRECTION. A `/bin/sh` or a PATH `sh` already runs with the
    # PATH its caller has, so it is given none - the mutation that adds the
    # entries whatever the origin turns these red.
    isfile, which = _fake_fs([M.POSIX_SH, wrapper], {"sh": inner, "git": git})
    posix = M.locate_sh(isfile, which, _WIN_ENV, ntpath)
    isfile, which = _fake_fs([inner, wrapper], {"sh": inner, "git": git})
    on_path = M.locate_sh(isfile, which, _WIN_ENV, ntpath)
    check("pg17 `/bin/sh`, and an `sh` found on PATH, carry NO PATH entries - "
          "their child's environment is the caller's own, untouched: %r"
          % ((posix, on_path),),
          posix == (M.POSIX_SH, (), None) and on_path == (inner, (), None))

    env = {"Path": "C:\\Windows\\System32", "OTHER": "kept"}
    grown = M.shell_env(wrapper, env, (wrapper, _BESIDE_PATH, None), ntpath)
    same = M.shell_env(M.POSIX_SH, env, (M.POSIX_SH, (), None), ntpath)
    other = M.shell_env(M.POSIX_SH, env, (wrapper, _BESIDE_PATH, None), ntpath)
    inherited = M.shell_env(M.POSIX_SH, None, (M.POSIX_SH, (), None), ntpath)
    check("pg18 THE CHILD'S ENV: a beside-git shell's entries go AHEAD of the "
          "inherited PATH under the key the environment already spells it with, "
          "on a copy; a shell with no entries - or one that is not the shell "
          "the entries were found for - gets back the very env it was handed, "
          "and `None` stays `None` so the child inherits exactly as before: %r"
          % ((grown, same is env, other is env, inherited),),
          grown == {"Path": ";".join(_BESIDE_PATH + ("C:\\Windows\\System32",)),
                    "OTHER": "kept"}
          and env["Path"] == "C:\\Windows\\System32"
          and same is env and other is env and inherited is None)

    root = "C:\\Windows"
    check("pg19 THE SYSTEM DIRECTORY IS JUDGED THE WAY WINDOWS SPELLS IT, case "
          "and separator folded: `c:/WINDOWS/System32/sh.exe` is under "
          "SystemRoot `C:\\Windows`, and Git's own `bin\\sh.exe` is not "
          "(mutation: drop the case fold -> red): %r"
          % ((M._in_system_dir("c:/WINDOWS/System32/sh.exe",
                               {"SystemRoot": root}, ntpath),
              M._in_system_dir(wrapper, {"SystemRoot": root}, ntpath)),),
          M._in_system_dir("c:/WINDOWS/System32/sh.exe",
                           {"SystemRoot": root}, ntpath) is True
          and M._in_system_dir(wrapper, {"SystemRoot": root}, ntpath) is False)

    real_sh = M.resolve_sh()[0]
    if real_sh is None:
        _harness.skip(check, "pg20 the PATH reaches both sites' children",
                      "no POSIX shell here to start a child under", True)
        return
    marks = ("p945-usr-bin-mark", "p945-mingw-mark", "p945-inherited-mark")
    scratch = _harness.fixture_root("proc-group-path-")
    fake = tuple(os.path.join(scratch, m) for m in marks[:2])
    seen = {}
    real_locate, real_path = M.locate_sh, os.environ.get("PATH")
    os.environ["PATH"] = os.pathsep.join(
        [os.path.join(scratch, marks[2])] + ([real_path] if real_path else []))
    try:
        for label, entries in (("beside", fake), ("posix", ())):
            M.locate_sh = (lambda *_a, _e=entries: (real_sh, _e, None))
            _c, g_text, _f = GATE._shell(scratch, 'printf "%s" "$PATH"',
                                         timeout=10)
            d_text = DERIVE._spawn('printf "%s" "$PATH"', scratch, 10)["output"]
            seen[label] = (g_text, d_text)
    finally:
        M.locate_sh = real_locate
        if real_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = real_path

    def ordered(text):
        spots = [text.find(m) for m in marks]
        return -1 not in spots and spots == sorted(spots)
    check("pg20 THE PATH REACHES BOTH SITES' CHILDREN: under a beside-git shell "
          "the gate's step and the derivation's listing each see the two "
          "entries AHEAD of the inherited PATH, and under a shell with none "
          "they see the inherited PATH and no entry at all: %r" % (seen,),
          all(ordered(t) for t in seen["beside"])
          and all(marks[2] in t and marks[0] not in t and marks[1] not in t
                  for t in seen["posix"]))


def _shell_cases(check):
    """The one POSIX shell every plan command runs under."""
    isfile, which = _fake_fs([M.POSIX_SH], {"sh": "/opt/other/sh"})
    check("pg7 `/bin/sh` WINS WHENEVER IT EXISTS, whatever else PATH offers - "
          "the exact interpreter `shell=True` used on POSIX, so a POSIX machine "
          "runs every plan command as before: %r"
          % (M.resolve_sh(isfile, which, {}, ntpath),),
          M.resolve_sh(isfile, which, {}, ntpath) == (M.POSIX_SH, None))

    on_path = _GIT_ROOT + "\\usr\\bin\\sh.exe"
    isfile, which = _fake_fs([on_path], {"sh": on_path, "bash": on_path})
    check("pg8 NO `/bin/sh` (Windows): the `sh` on PATH - Git Bash's - is the "
          "shell: %r" % (M.resolve_sh(isfile, which, _WIN_ENV, ntpath),),
          M.resolve_sh(isfile, which, _WIN_ENV, ntpath) == (on_path, None))

    beside = _GIT_ROOT + "\\usr\\bin\\sh.exe"
    isfile, which = _fake_fs([beside], {"git": _GIT_ROOT + "\\cmd\\git.exe"})
    check("pg9 NO `sh` ON PATH BUT `git` IS (the default Windows install puts "
          "only `<root>\\cmd` there): the `sh.exe` Git ships beside it is found, "
          "spelled the same on every host: %r"
          % (M.resolve_sh(isfile, which, _WIN_ENV, ntpath),),
          M.resolve_sh(isfile, which, _WIN_ENV, ntpath) == (beside, None))

    wsl = "C:\\Windows\\System32\\bash.exe"
    isfile, which = _fake_fs([wsl], {"bash": wsl,
                                     "sh": "C:\\Windows\\System32\\sh.exe"})
    got = M.resolve_sh(isfile, which, _WIN_ENV, ntpath)
    argv, why = (None, None)
    real = M.resolve_sh
    try:
        M.resolve_sh = lambda: got
        argv, why = M.shell_argv("echo hi")
    finally:
        M.resolve_sh = real
    check("pg10 NOTHING USABLE - only the System32 WSL launcher - is a REFUSAL "
          "NAMING GIT FOR WINDOWS, never `cmd.exe`, never a bare `sh` or `bash` "
          "left for the OS to fail on (mutation: fall back to cmd, or to a bare "
          "'sh' -> red): %r" % ((got, argv, why),),
          got[0] is None and argv is None and why == got[1]
          and "Git for Windows" in (why or "")
          and "NOT handed to cmd.exe" in (why or ""))

    cmd = ("export P942_V='a b'; printf '[%s][%s][%s]' \"$0\" \"${P942_V}\" "
           "'$HOME'")
    argv, _why = M.shell_argv(cmd)
    if not os.path.isfile(M.POSIX_SH):
        _harness.skip(check, "pg11 POSIX byte-identical",
                      "no /bin/sh here, and the byte-identical claim is POSIX's",
                      True)
    else:
        via_argv = subprocess.run(argv, stdout=subprocess.PIPE).stdout
        via_shell = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE).stdout
        check("pg11 ON POSIX THE ARGV IS `shell=True`'s OWN, and a command using "
              "`export`, single quotes and `${VAR}` prints byte for byte what "
              "`shell=True` printed: %r" % ((argv, via_argv, via_shell),),
              argv == [M.POSIX_SH, "-c", cmd] and via_argv == via_shell
              and via_argv == b"[/bin/sh][a b][$HOME]")

    real = M.resolve_sh
    try:
        M.resolve_sh = lambda: (None, M.NO_POSIX_SH)
        g_code, g_text, g_facts = GATE._shell(os.getcwd(), "echo hi", timeout=5)
        d_res = DERIVE._spawn("echo hi", os.getcwd(), 5)
    finally:
        M.resolve_sh = real
    check("pg12 BOTH CALLERS TURN THE REFUSAL INTO COULD-NOT-RUN carrying the "
          "sentence: the gate's step is `%s` with the text, and the derivation's "
          "observation has no exit and the sentence as its error: %r"
          % (GATE.CANNOT_RUN, ((g_code, g_text, g_facts), d_res)),
          g_facts == {"outcome": GATE.CANNOT_RUN} and g_code == 127
          and M.NO_POSIX_SH in g_text
          and d_res["exit"] is None and d_res["error"] == M.NO_POSIX_SH)
    root = _harness.fixture_root("proc-group-nosh-")
    subprocess.run(["git", "init", "-q", root], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    mp = os.path.join(root, "audit-plan.json")
    with open(mp, "w") as fh:
        json.dump({"meta": {"version": 2, "buildCommands": {"lint": "true"}},
                   "phases": [{"id": "P1", "title": "p", "status": "in_progress",
                               "testGate": ["lint"], "tasks": [
                                   {"id": "P1.1", "title": "t",
                                    "status": "in_progress"}]}]}, fh)
    lines = []
    try:
        M.resolve_sh = lambda: (None, M.NO_POSIX_SH)
        code = GATE.main([mp, "P1", "--project-dir", root, "--no-reuse"],
                         out=lines.append)
    finally:
        M.resolve_sh = real
    text = "\n".join(lines)
    check("pg14 END TO END, A GATE ON A MACHINE WITH NO POSIX SHELL SAYS SO: not "
          "green, `GATE COULD NOT RUN`, and the sentence naming Git for Windows "
          "is in what the operator reads: %r" % ((code, text[-700:]),),
          code != GATE.E_OK and "GATE COULD NOT RUN" in text
          and "Git for Windows" in text and "GATE GREEN" not in text)
    check("pg13 ...and neither spawns through `shell=True` any more - the "
          "gate's kwargs carry no shell, so the argv's shell is the only one: "
          "%r" % (GATE._spawn_kwargs(),),
          "shell" not in GATE._spawn_kwargs()
          and getattr(DERIVE, "_proc_group", None) is M)


def _cases(check):
    _shell_cases(check)
    _beside_git_cases(check)
    shared = [(name, getattr(GATE, name) is getattr(M, target))
              for name, target in (("shares_our_group", "shares_our_group"),
                                   ("_tear_down", "tear_down"),
                                   ("_drain", "drain"),
                                   ("_arm_interrupt", "arm_interrupt"),
                                   ("_disarm_interrupt", "disarm_interrupt"))]
    check("pg1 run-test-gate's teardown and interrupt handling ARE this module's "
          "objects, not copies of them: %r" % (shared,),
          all(ok for _n, ok in shared))
    check("pg2 ...and stamp-verification's red run reaches the same module rather "
          "than a runner of its own",
          getattr(RED, "_proc_group", None) is M)

    kw = M.group_kwargs()
    check("pg3 the group kwargs carry the grouping and nothing else - a shell and "
          "the pipes are each caller's own: %r" % (kw,),
          set(kw) <= set(("start_new_session", "creationflags"))
          and (kw or not (hasattr(os, "setsid")
                          or hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"))))

    try:
        M.raiser("SIGTERM")(signal.SIGTERM, None)
        raised = None
    except KeyboardInterrupt as exc:
        raised = str(exc)
    check("pg4 a stop signal becomes a KeyboardInterrupt NAMING the signal, which "
          "is what carries it past every `except Exception` to the caller's "
          "`finally`: %r" % (raised,), raised == "SIGTERM")

    before = [signal.getsignal(getattr(signal, n)) for n in M.INTERRUPT_SIGNALS]
    previous = M.arm_interrupt()
    armed = [signal.getsignal(getattr(signal, n)) for n in M.INTERRUPT_SIGNALS]
    M.disarm_interrupt(previous)
    after = [signal.getsignal(getattr(signal, n)) for n in M.INTERRUPT_SIGNALS]
    check("pg5 arming replaces both handlers and disarming puts back exactly what "
          "was there",
          armed != before and after == before)

    if not hasattr(os, "killpg"):
        _harness.skip(check, "pg6 tear_down reaches a grandchild", "posix",
                      "no process groups to tear down on this platform")
        return
    marks = _harness.fixture_root("proc-group-")
    late = os.path.join(marks, "late")
    began = os.path.join(marks, "began")
    inner = ("import time; open(%r, 'w').close(); time.sleep(2); "
             "open(%r, 'w').close()" % (began, late))
    code = ("import subprocess, sys, time\n"
            "subprocess.Popen([sys.executable, '-c', %r])\ntime.sleep(30)\n"
            % (inner,))
    kwargs = M.group_kwargs()
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, **kwargs)
    for _i in range(100):
        if os.path.exists(began):
            break
        time.sleep(0.05)
    confirmed = M.tear_down(proc)
    M.drain(proc)
    time.sleep(3)
    check("pg6 tear_down kills the GROUP: the grandchild the child started - "
          "seen running - never writes, and the teardown says it was confirmed: "
          "began=%r confirmed=%r wrote=%r"
          % (os.path.exists(began), confirmed, os.path.exists(late)),
          os.path.exists(began) and confirmed is True
          and not os.path.exists(late))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__proc_group.py --selftest\n")
    raise SystemExit(2)
