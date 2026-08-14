#!/usr/bin/env python3
"""
The one place CLI color lives - stdlib only, ASCII only.

Three commands paint a terminal render (audit-usage.py, audit-status.py,
audit-doctor.py) and they must agree on WHEN: per-script color logic is how
one script respects NO_COLOR and its sibling does not. This module owns the
mode resolution and the paint API; consumers hold a Painter and never touch
an escape code themselves.

MODES (the `--color auto|always|never` flag; default auto):

  never   plain, unconditionally.
  always  colored, unconditionally - INCLUDING under NO_COLOR. Decided and
          pinned here: no-color.org specifies NO_COLOR as the switch that
          turns off color that would otherwise be on BY DEFAULT, and defers
          to explicit command-line options ("User-level configuration ...
          should override" it). An operator typing `--color always` is the
          most explicit signal there is; honoring the env var over the flag
          would make the flag a no-op with no spelling left that means
          "yes, really".
  auto    colored exactly when stdout is a TTY AND NO_COLOR is absent or
          EMPTY (an empty NO_COLOR does not count as set - the spec's own
          reading). The model-facing command path is a pipe, so auto stays
          plain there; a human running the same script in a terminal gets
          color. NO_COLOR beats auto: auto is "color by default", which is
          exactly the default the variable exists to switch off.

The escape codes are plain ASCII (ESC + "[..m"), so painted output survives
any PYTHONIOENCODING the cp1252 CI leg sets. `strip()` removes them and MUST
return the exact unpainted text - painting wraps content, never changes it.
Plain mode is byte-identical to the pre-color output by construction: a
disabled Painter returns its input unchanged.

Roles - the minimal set the three consumers actually use:

  ok / warn / finding   doctor's three levels (green / yellow / red)
  header                section headings (bold)
  dim                   footnote-ish caveats (faint)

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import os
import re
import sys

MODES = ("auto", "always", "never")

RESET = "\033[0m"

# SGR codes only, one per role. Kept deliberately tiny: a palette is a UI
# decision and this is a CLI, where restraint reads better than rainbow.
CODES = {
    "ok": "\033[32m",
    "warn": "\033[33m",
    "finding": "\033[31m",
    "header": "\033[1m",
    "dim": "\033[2m",
}

_ANSI_RE = re.compile("\033\\[[0-9;]*m")


# --- mode resolution --------------------------------------------------------
def enabled(mode, stream=None, env=None):
    """True when `mode` says to paint. See the module docstring for the table.

    `stream` defaults to the real sys.stdout and `env` to os.environ; both are
    injectable so the selftest can hand in a fake TTY and a fake environment
    instead of depending on how CI wires this process up. A stream with no
    (or a raising) isatty() counts as not-a-TTY - the safe answer is plain.
    """
    if mode == "never":
        return False
    if mode == "always":
        return True
    e = os.environ if env is None else env
    if e.get("NO_COLOR"):
        return False
    s = sys.stdout if stream is None else stream
    try:
        return bool(s.isatty())
    except Exception:
        return False


# --- paint ------------------------------------------------------------------
class Painter(object):
    """paint(text, role) -> text, wrapped in ANSI when this painter is on.

    A disabled painter returns its input UNCHANGED (identity, not a copy of
    the styling logic with the codes blanked) - that is what makes the three
    consumers' plain mode byte-identical to their pre-color output. An
    unknown role paints nothing rather than raising: a typo in a role name
    must degrade to plain text, never take the render down."""

    def __init__(self, on):
        self.on = bool(on)

    def paint(self, text, role):
        code = CODES.get(role)
        if not self.on or not code:
            return str(text)
        return code + str(text) + RESET


# The shared "color off" painter. Consumers default their render entry points
# to this so every existing caller (selftests included) keeps plain output
# without naming color at all.
PLAIN = Painter(False)


def painter(mode, stream=None, env=None):
    """The one constructor consumers call: `--color` value in, Painter out."""
    return Painter(enabled(mode, stream=stream, env=env))


def strip(text):
    """Remove every ANSI SGR escape - the exact inverse of paint()."""
    return _ANSI_RE.sub("", str(text))


# --- selftest ---------------------------------------------------------------
class _Tty(object):
    def isatty(self):
        return True


class _Pipe(object):
    def isatty(self):
        return False


class _NoIsatty(object):
    pass


def _selftest():
    cases = []

    def check(label, ok, detail=""):
        cases.append((label, bool(ok), detail))

    tty, pipe = _Tty(), _Pipe()

    # -- mode resolution ------------------------------------------------------
    check("cf1 never is plain even on a TTY with no NO_COLOR",
          enabled("never", stream=tty, env={}) is False)
    check("cf2 always is colored even through a pipe",
          enabled("always", stream=pipe, env={}) is True)
    check("cf3 auto on a TTY with no NO_COLOR is colored",
          enabled("auto", stream=tty, env={}) is True)
    check("cf4 auto through a pipe is plain - the model-facing path",
          enabled("auto", stream=pipe, env={}) is False)
    check("cf5 NO_COLOR beats auto: a set variable turns a TTY plain",
          enabled("auto", stream=tty, env={"NO_COLOR": "1"}) is False)
    check("cf6 an explicit always outranks NO_COLOR - the documented decision: "
          "the flag is the more explicit signal and must not be a no-op",
          enabled("always", stream=tty, env={"NO_COLOR": "1"}) is True)
    check("cf7 an EMPTY NO_COLOR does not count as set (the spec's reading)",
          enabled("auto", stream=tty, env={"NO_COLOR": ""}) is True)
    check("cf8 a stream without isatty() resolves to plain, not a crash",
          enabled("auto", stream=_NoIsatty(), env={}) is False)

    # -- paint ----------------------------------------------------------------
    on, off = painter("always"), painter("never")
    check("cf9 every role paints: the code goes on and RESET closes it",
          all(on.paint("x", r) == CODES[r] + "x" + RESET for r in CODES))
    check("cf10 a disabled painter returns its input unchanged - identity, "
          "which is what makes plain mode byte-identical",
          all(off.paint("x", r) == "x" for r in CODES)
          and off.paint("x", "ok") is not None)
    check("cf11 an unknown role paints nothing rather than raising",
          on.paint("x", "no-such-role") == "x")
    check("cf12 painted text strips back to the plain text exactly - "
          "painting wraps content, never changes it",
          all(strip(on.paint(s, r)) == s
              for r in CODES
              for s in ("", "x", "[OK     ]", "USAGE  repo r   window w",
                        "100% #### [x] P1.1")))
    check("cf13 strip() on already-plain text is the identity",
          strip("no escapes here [x] 42%") == "no escapes here [x] 42%")
    check("cf14 every escape code is pure ASCII, so cp1252 CI cannot choke",
          all(ord(c) < 128 for c in RESET + "".join(CODES.values())))
    check("cf15 PLAIN is off and painter() honors each mode end to end",
          PLAIN.on is False and painter("never").on is False
          and painter("always").on is True
          and painter("auto", stream=pipe, env={}).on is False
          and painter("auto", stream=tty, env={}).on is True)
    check("cf16 MODES names exactly the flag's vocabulary",
          MODES == ("auto", "always", "never"))

    passed = sum(1 for _, ok, _ in cases if ok)
    for label, ok, detail in cases:
        print("%s %s%s" % ("PASS" if ok else "FAIL", label,
                           (" (%s)" % detail) if detail and not ok else ""))
    print("\n_cli_fmt: %d/%d cases passed" % (passed, len(cases)))
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: _cli_fmt.py --selftest\n")
    raise SystemExit(2)
