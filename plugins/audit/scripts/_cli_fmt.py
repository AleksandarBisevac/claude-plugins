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

This module carries no `--selftest` of its own any more; its 16 cases live in
`plugins/audit/tests/test__cli_fmt.py`, byte-identical labels and all. It is one of
the three pilots of that migration - see `plugins/audit/tests/_harness.py`.

Exit codes (as a command): 0 the pointer above - 2 usage error.
"""
import os
import re
import sys

# The path bootstrap: byte-identical in every `.py` under `scripts/`, counted by
# `_output.path_preamble_violations()`. It walks UP to the directory holding
# `_output.py` instead of counting `dirname()` calls, so it does not encode how deep
# this file sits and keeps working if the file is moved into a subdirectory.
# `install_path()` then adds that directory AND every subdirectory of it holding a
# `.py`: the folders are LABELS, NOT NAMESPACES, and every sibling below is still
# reached by a bare basename.
_anchor_dir = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_anchor_dir, "_output.py")):
    _anchor_up = os.path.dirname(_anchor_dir)
    if _anchor_up == _anchor_dir:
        raise ImportError("audit plugin: walked to the filesystem root from %s "
                          "without finding _output.py - the scripts/ anchor is "
                          "gone and no sibling can be imported" % (__file__,))
    _anchor_dir = _anchor_up
if _anchor_dir not in sys.path:
    sys.path.insert(0, _anchor_dir)

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()

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


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exits silently: `--selftest` is what every other
        # file here still accepts, so nothing would tell a reader whether this
        # one ran nothing or has nothing. It deliberately does NOT print the
        # suite contract - that literal is how `_output.selftest_coverage()`
        # tells an inline suite from a migrated one.
        print("_cli_fmt.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__cli_fmt.py - run that file instead.")
        raise SystemExit(0)
    sys.stderr.write("usage: _cli_fmt.py --selftest\n")
    raise SystemExit(2)
