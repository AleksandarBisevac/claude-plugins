#!/usr/bin/env python3
"""
The cases for `hooks/py-launch.sh` - the launcher, driven as a shell script.

WHY THESE CASES CANNOT BE ASSERTIONS ABOUT ITS TEXT. The launcher decides what
happens when the interpreter is not there, or is there and does not work, or is
asked for a hook script that is not beside it. Every one of those is a property of
a PROCESS: which program got spawned, what reached its stdin, what came back on
stdout, what the exit status was. A reader of the source can be sure the right
branch is written and still be wrong about which branch a shell takes, and the
red team that found the two failures this file now pins was driving shims, not
reading. So every case here runs a real `sh` against a real directory of real
shims on `PATH`, and grades what comes back.

THE SHIMS ARE THE FIXTURE, and each stands for one shape:

  * an empty directory on `PATH` - no interpreter resolves at all, and since
    nothing else resolves either, a run that still prints its JSON is also the
    proof that the loud path needs no external tool;
  * a `python3` that exits nonzero without reading stdin - present to
    `command -v`, useless to a hook, and silent before this;
  * that same broken `python3` beside a `python` that works - the fallback chain
    the docstring promises, which a launcher resolving on `command -v` alone
    could never reach;
  * a `python3` that counts its own invocations and then hands off to the real
    interpreter - which is how the hot path is measured rather than argued
    about.

THE ALLOW CASES ARE THE LOAD-BEARING HALF. This script runs ahead of every hook
on every tool call, so a launcher that goes loud while the interpreter is fine is
worse than the silence being fixed: it prompts on every tool call and gets
uninstalled the same hour. `pl1`, `pl2` and `pl12` are that direction - a healthy
run stays silent, a healthy interpreter running a script that exits nonzero stays
silent, and the healthy path spawns the interpreter once.

`hooks/py-launch.sh` is copied into the fixture rather than driven where it sits,
because `$0` is how it finds its own directory and the not-beside-the-launcher
case is exactly a `$0` whose directory holds no hook. `pl14` holds the copy to the
shipped bytes so the rest of the file is about the launcher this plugin ships.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import io
import json
import os
import shutil
import stat
import subprocess
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402

LAUNCHER = os.path.join(_harness.HOOKS_DIR, "py-launch.sh")

PAYLOAD = '{"tool_name":"Edit","tool_input":{"file_path":"x.ts"}}'

# What the fixture hook prints in front of whatever reached its stdin. A marker
# rather than a bare echo of the payload: a case asserting only that the payload
# came back could be satisfied by a launcher that echoed its own argument.
MARKER = "HOOK-RAN:"

_HOOK_BODY = ("import sys\n"
              "sys.stdout.write(%r + sys.stdin.read())\n" % (MARKER,))

_CRASH_BODY = _HOOK_BODY + "sys.exit(3)\n"


# --- fixture ------------------------------------------------------------------
def _write(path, text, executable=False):
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    if executable:
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP
                 | stat.S_IXOTH)


def _shim_dir(root, name, body):
    """A directory holding one executable `python3`, returned as a PATH entry."""
    d = os.path.join(root, name)
    os.makedirs(d)
    _write(os.path.join(d, "python3"), body, executable=True)
    return d


def _drive(sh, launcher, script, mode, path_entry, stdin=PAYLOAD):
    """Run the launcher as `hooks.json` does and return {out, err, code}.

    `path_entry` is a directory holding exactly one interpreter (or nothing),
    and the shell has to be ABLE TO NAME IT as a `PATH` entry before it can
    search it - which a directory carrying a drive letter is not, on every
    shell. POSIX defines `PATH` as a colon-separated list, and a Windows
    absolute path always carries a colon right after the drive letter
    (`C:\\...`); a shell that applies that split literally to `path_entry`'s
    own bytes reads `C:\\Python312` as the two components `C` and
    `\\Python312`, and neither resolves anything. `git`'s own bundled `bash`
    survives this because its runtime pre-translates a Windows-shaped `PATH`
    before the shell's own split ever runs - a shell installed BESIDE that
    distribution, not built against its runtime, gets no such rewrite and
    hits the split raw. Proven equal for a real `dash` and a real `bash`
    here, neither MSYS-linked: handed a single `PATH` entry whose own path
    contains an embedded `:`, BOTH fail to resolve a shim that a colon-free
    directory resolves for both (`probe/mutations.py`) - so the divergence
    windows-latest reports is not "dash is worse at this than bash", it is
    "one of the two never has to parse the colon at all". `PATH` is set to
    the single-character literal `.` and the CHILD PROCESS'S CWD becomes
    `path_entry` instead - a directory that is merely the process's working
    directory is a `CreateProcess`/`fork`+`chdir` argument, native on every
    platform, and never something a shell parses as a delimited list.

    `PATH` is REPLACED rather than extended, which is what makes a shim a shim:
    prepending one leaves the machine's real `python3` reachable under `python`,
    and a case that meant to drive a broken interpreter would quietly drive a
    working one.

    `launcher` REACHES THE SCRIPT AS `$0`, FORWARD-SLASHED - the way
    `hooks.json` actually spells it (`"${CLAUDE_PLUGIN_ROOT}/hooks/py-launch.sh"`
    carries a literal `/` before `hooks/...` no matter what the root itself
    contains), and the reason `dir=${0%/*}` in the launcher can find. Handing
    it the raw fixture path instead - `os.path.join()`'s native separator,
    all-backslash on windows - names a `$0` the launcher's own `case "$0" in
    */*)` cannot see a slash in at all, which is indistinguishable from the
    hook genuinely not being beside it (pl7's own scenario, for an unrelated
    reason) and sent a healthy run down the same loud fallback. A fixture path
    is this machine's, not the subject's; what the subject actually receives
    is a bash-spelled `$0`, and that is what gets driven here. This one is
    unaffected by the `cwd` change above: `$0` is an argv string the launcher
    pattern-matches, never a `PATH` entry a shell splits, and the fixed launcher
    resolves `$script` from it directly rather than from the working directory
    - checked directly for both `dash` and `bash` here, not assumed from the
    `PATH` finding (`probe/mutations.py`).

    `sh` is usually the interpreter's own path, but may be a LIST - a binary
    found by bare name is not always a shell by itself. A `busybox` resolved
    this way is the multi-call binary, not a `sh`-named symlink to it; run
    directly its own dispatcher reads the next argument as an APPLET NAME, so
    the launcher's path is looked up as an applet, not executed as a script,
    and busybox refuses it ("applet not found") before the launcher's first
    line runs. `[busybox_path, "sh"]` selects the applet explicitly - the same
    selection every other name here gets for free from its own binary, and
    the same one a machine gets for free when `/bin/sh` IS that symlink.
    """
    env = dict(os.environ)
    env["PATH"] = "."
    argv = sh if isinstance(sh, list) else [sh]
    proc = subprocess.Popen(argv + [launcher.replace("\\", "/"), script, mode],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env, cwd=path_entry)
    out, err = proc.communicate(stdin.encode("utf-8"))
    return {"out": out.decode("utf-8", "replace"),
            "err": err.decode("utf-8", "replace"), "code": proc.returncode}


def _reason(blob):
    """The permissionDecisionReason of a launcher payload, or None.

    None for anything that is not the shape a host acts on - unparseable, not an
    `ask`, not on the event that carries a permission channel. A case comparing
    reason TEXT would otherwise pass over JSON no host would ever honour.
    """
    try:
        data = json.loads(blob)
    except ValueError:
        return None
    spec = data.get("hookSpecificOutput")
    if not isinstance(spec, dict):
        return None
    if spec.get("hookEventName") != "PreToolUse":
        return None
    if spec.get("permissionDecision") != "ask":
        return None
    return spec.get("permissionDecisionReason")


# --- cases --------------------------------------------------------------------
def _cases(check):
    sh = shutil.which("sh")
    if sh is None:
        _harness.skip(check, "pl0", "no POSIX `sh` on PATH, so the launcher - "
                      "which IS a POSIX shell script - cannot be driven here at "
                      "all, and a case reading its source instead would be "
                      "asserting about a file rather than about a process",
                      sh is None)
        return

    root = _harness.fixture_root("py-launch-selftest-")

    beside = os.path.join(root, "hooks")
    os.makedirs(beside)
    fixture_launcher = os.path.join(beside, "py-launch.sh")
    shutil.copyfile(LAUNCHER, fixture_launcher)
    _write(os.path.join(beside, "hook.py"), _HOOK_BODY)
    _write(os.path.join(beside, "crash.py"), _CRASH_BODY)

    empty_dir = os.path.join(root, "bin-empty")
    os.makedirs(empty_dir)

    broken_dir = _shim_dir(root, "bin-broken", "#!/bin/sh\nexit 1\n")

    mixed_dir = _shim_dir(root, "bin-mixed", "#!/bin/sh\nexit 1\n")
    # SINGLE-QUOTED: `sys.executable` is `os.path.join()`'s native separator,
    # all-backslash on windows, and an UNQUOTED backslash in shell source is
    # an escape character - each `\X` is read as a literal `X`, which strips
    # every separator and glues the path into one wrong word. Single quotes
    # are the one POSIX quoting form backslash cannot see through.
    _write(os.path.join(mixed_dir, "python"),
           "#!/bin/sh\nexec '%s' \"$@\"\n" % (sys.executable,), executable=True)

    counter = os.path.join(root, "spawns.log")
    # Both substitutions SINGLE-QUOTED for the same reason as the `python`
    # shim above: `counter` is this fixture's own `os.path.join()` path, and
    # on windows an unquoted backslash in it is stripped by the shell before
    # `printf` ever sees a filename - the write lands next to `root`, merged
    # into one wrong name, and the read below (a real path, never shell-quoted
    # because Python never quotes for a shell) then finds nothing there.
    counting_dir = _shim_dir(
        root, "bin-counting",
        "#!/bin/sh\nprintf 'x\\n' >> '%s'\nexec '%s' \"$@\"\n"
        % (counter, sys.executable))

    real_dir = os.path.dirname(sys.executable)

    # ------------------------------------------------- the allow cases, first
    ok = _drive(sh, fixture_launcher, "hook.py", "ask", real_dir)
    check("pl1 a working interpreter runs the hook and the launcher adds "
          "NOTHING - the payload reaches stdin whole, stdout is the hook's own "
          "and carries no permission decision, exit 0. This runs ahead of every "
          "tool call, so it is the case a loud fallback may never reach: %r"
          % (ok,),
          ok["out"] == MARKER + PAYLOAD and ok["code"] == 0
          and _reason(ok["out"]) is None)

    crash = _drive(sh, fixture_launcher, "crash.py", "ask", real_dir)
    check("pl2 a hook that exits NONZERO under a working interpreter is the "
          "hook's own failure, not the interpreter's - its status propagates "
          "unchanged and no prompt is appended to output it already wrote: %r"
          % (crash,),
          crash["out"] == MARKER + PAYLOAD and crash["code"] == 3
          and _reason(crash["out"]) is None)

    _drive(sh, fixture_launcher, "hook.py", "ask", counting_dir)
    with io.open(counter, encoding="utf-8") as fh:
        spawns = len([ln for ln in fh.read().split("\n") if ln.strip()])
    check("pl12 the healthy path spawns the interpreter ONCE - the probe that "
          "tells a broken interpreter from a working one is asked only after a "
          "nonzero status, so it costs a process on the failing path and none on "
          "the path taken before every tool call. Counted by a shim that records "
          "each invocation, because a budget argued from the source is not a "
          "measurement: %d" % (spawns,),
          spawns == 1)

    with io.open(counter, "w", encoding="utf-8") as fh:
        fh.write("")
    _drive(sh, fixture_launcher, "crash.py", "ask", counting_dir)
    with io.open(counter, encoding="utf-8") as fh:
        after_crash = len([ln for ln in fh.read().split("\n") if ln.strip()])
    check("pl13 ...and the failing path DOES pay for it, so pl12 is the probe "
          "being deferred rather than the probe being absent - a launcher that "
          "never probed would pass pl12 and leave the whole failure silent: %d"
          % (after_crash,),
          after_crash > spawns)

    # ------------------------------------------- found, but it does not work
    broken_ask = _drive(sh, fixture_launcher, "hook.py", "ask", broken_dir)
    broken_reason = _reason(broken_ask["out"])
    check("pl3 a `python3` that RESOLVES and then exits nonzero is the failure "
          "`command -v` cannot see, and it used to end in an unhandled hook "
          "error - which every blocking guard's fail-mode row grades as allow. "
          "It now reaches the same prompt a missing interpreter does: %r"
          % (broken_ask,),
          broken_reason is not None and broken_ask["code"] == 0
          and MARKER not in broken_ask["out"])

    broken_open = _drive(sh, fixture_launcher, "hook.py", "open", broken_dir)
    check("pl4 ...and in `open` mode it stays silent, because an advisory hook "
          "has no permission channel to print into and must never block work: %r"
          % (broken_open,),
          broken_open["out"] == "" and broken_open["code"] == 0)

    mixed = _drive(sh, fixture_launcher, "hook.py", "ask", mixed_dir)
    check("pl11 a broken `python3` beside a working `python` runs the hook "
          "under `python` - the fallback chain the usage line promises, which a "
          "launcher that stopped at the first name `command -v` answered for "
          "could never reach. Safe to try because an interpreter that cannot "
          "run has not read the payload either: %r" % (mixed,),
          mixed["out"] == MARKER + PAYLOAD and mixed["code"] == 0)

    # ------------------------------------------------- nothing resolves at all
    missing_ask = _drive(sh, fixture_launcher, "hook.py", "ask", empty_dir)
    missing_reason = _reason(missing_ask["out"])
    check("pl5 with an EMPTY `PATH` entry nothing resolves - no interpreter and "
          "no external tool of any kind - and the prompt is still printed, which "
          "is the behavioural proof that the loud path is shell builtins only: %r"
          % (missing_ask,),
          missing_reason is not None and missing_ask["code"] == 0)

    missing_open = _drive(sh, fixture_launcher, "hook.py", "open", empty_dir)
    check("pl6 ...and `open` is silent there too: %r" % (missing_open,),
          missing_open["out"] == "" and missing_open["code"] == 0)

    # --------------------------------------- the hook script is not beside it
    astray = os.path.join(root, "astray")
    os.makedirs(astray)
    astray_launcher = os.path.join(astray, "py-launch.sh")
    shutil.copyfile(LAUNCHER, astray_launcher)

    root_ask = _drive(sh, astray_launcher, "hook.py", "ask", real_dir)
    root_reason = _reason(root_ask["out"])
    check("pl7 a launcher whose own directory holds no such hook is what a "
          "plugin root pointing at the wrong tree looks like from inside, and "
          "what `$0` with no slash in it produces. The interpreter then failed "
          "to open the file and exited nonzero with nothing on stdout - a hook "
          "error, graded allow. It is now the prompt: %r" % (root_ask,),
          root_reason is not None and root_ask["code"] == 0
          and MARKER not in root_ask["out"])

    root_open = _drive(sh, astray_launcher, "hook.py", "open", real_dir)
    check("pl8 ...and silent under `open`: %r" % (root_open,),
          root_open["out"] == "" and root_open["code"] == 0)

    root_bare = _drive(sh, astray_launcher, "hook.py", "ask", empty_dir)
    check("pl9 the launcher never consults the interpreter it will not use - "
          "the not-beside case is decided before the resolution loop, so it "
          "reports the same way on a machine with no interpreter at all, where "
          "the missing-interpreter sentence would have been the wrong repair: "
          "%r" % (root_bare,),
          _reason(root_bare["out"]) == root_reason and root_reason is not None)

    reasons = (missing_reason, broken_reason, root_reason)
    check("pl10 each fallback names WHICH failure it is. The repairs differ - "
          "install an interpreter, fix the one you have, reinstall the plugin - "
          "so one sentence covering them would tell a reader nothing to act on: "
          "%r" % (reasons,),
          len(set(reasons)) == len(reasons) and all(reasons))

    # ------------------------------------------------------- what is under test
    with io.open(LAUNCHER, "rb") as fh:
        shipped = fh.read()
    with io.open(fixture_launcher, "rb") as fh:
        copied = fh.read()
    check("pl14 the fixture is a byte copy of the shipped launcher, so every "
          "case above is about the file this plugin installs rather than about "
          "a fork of it that drifted",
          shipped == copied and shipped)

    with io.open(os.path.join(_harness.HOOKS_DIR, "hooks.json"),
                 encoding="utf-8") as fh:
        wiring = json.load(fh)
    argued = []
    for event in wiring.get("hooks") or {}:
        for block in wiring["hooks"][event]:
            for entry in block.get("hooks") or []:
                parts = (entry.get("command") or "").split()
                argued.extend(p for p in parts if p.endswith(".py"))
    absent = sorted(set(p for p in argued
                        if not os.path.isfile(os.path.join(_harness.HOOKS_DIR,
                                                           p))))
    others = []
    for name in ("dash", "bash", "ksh", "zsh", "busybox"):
        found = shutil.which(name)
        if found:
            others.append(found)
    if not others:
        _harness.skip(check, "pl16", "only one shell is installed here, so a "
                      "case about the launcher behaving the same under another "
                      "could not tell a portable script from a lucky one",
                      not others)
    else:
        per_shell = []
        for other in others:
            # A `busybox` found by bare name is the multi-call binary, not a
            # `sh`-named symlink to it - see `_drive`'s docstring for why that
            # means an explicit applet argument rather than a bare path.
            argv = [other, "sh"] if os.path.basename(other) == "busybox" \
                else other
            healthy = _drive(argv, fixture_launcher, "hook.py", "ask", real_dir)
            failing = _drive(argv, fixture_launcher, "hook.py", "ask",
                             broken_dir)
            per_shell.append((os.path.basename(other),
                              healthy["out"] == MARKER + PAYLOAD
                              and healthy["code"] == 0
                              and _reason(failing["out"]) == broken_reason))
        check("pl16 every shell on this machine runs it the same way. Not "
              "portability for its own sake: `status` is read-only in zsh, so "
              "the variable holding the hook's exit code killed the launcher "
              "outright there - a whole shell's worth of users with no hooks "
              "and no message, found by driving it rather than by reading it: "
              "%r" % (per_shell,),
              all(ok for _name, ok in per_shell))

    check("pl15 every script `hooks.json` names really sits beside the "
          "launcher, so pl7's branch cannot fire on the shipped wiring. The "
          "allow direction of a refusal that runs ahead of every tool call, "
          "read off the registration file rather than from a list here: %r"
          % (absent,),
          argued and not absent)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_py_launch.py --selftest\n")
    raise SystemExit(2)
