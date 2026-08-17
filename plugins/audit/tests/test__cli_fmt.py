#!/usr/bin/env python3
"""
The cases for `scripts/_cli_fmt.py`, moved out of it - the importable-helper shape.

The simplest of the three pilots and the one that shows the transformation with nothing
else in the way: `_cli_fmt` is an `_underscore.py` helper, so a plain `import` reaches it
once `_harness` has put `scripts/` on the path, and the only edit the case bodies needed
was the `M.` prefix.

M IS THE MODULE UNDER TEST, in this file and in every other one. A moved selftest
references its module's names bare (`enabled(...)`, `CODES[r]`), and those names have to
be re-attached to something. `globals().update(vars(mod))` would re-attach them
invisibly and hand ruff's F821 a body of names it cannot see declared; an explicit
`from _cli_fmt import (enabled, painter, CODES, RESET, strip, PLAIN, MODES)` would work
HERE and nowhere else, because the other two pilots are a hyphenated entry point and a
hook - neither is spellable in an `import` statement, and both must come through
`_loader`, which returns a module OBJECT. One style that works for all three beats two
styles chosen per file, and the prefix carries information the flat form loses: in
`M.strip(...)` versus `strip(...)`, only the first says which side of the boundary the
name is on.

The three stream fakes below moved with the cases: they were declared in `_cli_fmt.py`'s
own `# --- selftest ---` section and nothing outside it ever used them.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _cli_fmt as M                               # noqa: E402


# --- stream fakes -------------------------------------------------------------
class _Tty(object):
    def isatty(self):
        return True


class _Pipe(object):
    def isatty(self):
        return False


class _NoIsatty(object):
    pass


# --- cases --------------------------------------------------------------------
def _cases(check):
    tty, pipe = _Tty(), _Pipe()

    # -- mode resolution ------------------------------------------------------
    check("cf1 never is plain even on a TTY with no NO_COLOR",
          M.enabled("never", stream=tty, env={}) is False)
    check("cf2 always is colored even through a pipe",
          M.enabled("always", stream=pipe, env={}) is True)
    check("cf3 auto on a TTY with no NO_COLOR is colored",
          M.enabled("auto", stream=tty, env={}) is True)
    check("cf4 auto through a pipe is plain - the model-facing path",
          M.enabled("auto", stream=pipe, env={}) is False)
    check("cf5 NO_COLOR beats auto: a set variable turns a TTY plain",
          M.enabled("auto", stream=tty, env={"NO_COLOR": "1"}) is False)
    check("cf6 an explicit always outranks NO_COLOR - the documented decision: "
          "the flag is the more explicit signal and must not be a no-op",
          M.enabled("always", stream=tty, env={"NO_COLOR": "1"}) is True)
    check("cf7 an EMPTY NO_COLOR does not count as set (the spec's reading)",
          M.enabled("auto", stream=tty, env={"NO_COLOR": ""}) is True)
    check("cf8 a stream without isatty() resolves to plain, not a crash",
          M.enabled("auto", stream=_NoIsatty(), env={}) is False)

    # -- paint ----------------------------------------------------------------
    on, off = M.painter("always"), M.painter("never")
    check("cf9 every role paints: the code goes on and RESET closes it",
          all(on.paint("x", r) == M.CODES[r] + "x" + M.RESET for r in M.CODES))
    check("cf10 a disabled painter returns its input unchanged - identity, "
          "which is what makes plain mode byte-identical",
          all(off.paint("x", r) == "x" for r in M.CODES)
          and off.paint("x", "ok") is not None)
    check("cf11 an unknown role paints nothing rather than raising",
          on.paint("x", "no-such-role") == "x")
    check("cf12 painted text strips back to the plain text exactly - "
          "painting wraps content, never changes it",
          all(M.strip(on.paint(s, r)) == s
              for r in M.CODES
              for s in ("", "x", "[OK     ]", "USAGE  repo r   window w",
                        "100% #### [x] P1.1")))
    check("cf13 strip() on already-plain text is the identity",
          M.strip("no escapes here [x] 42%") == "no escapes here [x] 42%")
    check("cf14 every escape code is pure ASCII, so cp1252 CI cannot choke",
          all(ord(c) < 128 for c in M.RESET + "".join(M.CODES.values())))
    check("cf15 PLAIN is off and painter() honors each mode end to end",
          M.PLAIN.on is False and M.painter("never").on is False
          and M.painter("always").on is True
          and M.painter("auto", stream=pipe, env={}).on is False
          and M.painter("auto", stream=tty, env={}).on is True)
    check("cf16 MODES names exactly the flag's vocabulary",
          M.MODES == ("auto", "always", "never"))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__cli_fmt.py --selftest\n")
    raise SystemExit(2)
