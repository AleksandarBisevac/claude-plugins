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


def _cases(check):
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
