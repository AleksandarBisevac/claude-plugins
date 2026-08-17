#!/usr/bin/env python3
"""
The one token/cost formatter — stdlib only.

Before this module, the same magnitude table — `(1e9,"B"),(1e6,"M"),(1e3,"K")` —
and the same "never render real spend as $0.00" rule were typed out three times:

  * audit-usage.py: `fmt_tokens(n)` (CLI table shape — always one decimal),
    `fmt_cost(x, show=True)` (a `show` flag that renders "" instead of the CLI
    turning `--no-cost` into a column of blanks), `fmt_int(n)` (thousands-grouped
    countables: messages, sessions, tasks — deliberately NOT compacted, because a
    countable you can act on is not a magnitude).
  * render-report.py: `_fmt_tokens(n, dp=1)` (report shape — a `dp` parameter so
    a label reads `3.2M` at one decimal and the hover tooltip over the same bar
    reads `3.23M` at two, `dp=2`, without ever falling back to the raw integer)
    and `_fmt_cost(x)` (byte-identical logic to audit-usage's, just without the
    `show` flag — render-report never suppresses cost, it omits the tile instead).
  * audit-status.py deliberately did NOT grow a fourth copy: it used to
    importlib-load audit-usage's `fmt_tokens`/`fmt_cost` at runtime. That loader
    is gone — it reads them from here now, and the layer-debt entry it produced
    was retired with it.

Differences tabled BEFORE unifying (golden values run against the two originals,
frozen in `plugins/audit/tests/test__fmt.py`, before either call site was touched):

  fmt_tokens(942)                == "942"    (below 1000: both variants agree)
  fmt_tokens(1000)               == "1.0K"   (both variants: one decimal default)
  fmt_tokens(2_000_000_000)      == "2.0B"
  _fmt_tokens(n)      (dp=1, the render-report default) == fmt_tokens(n) for every
      n tried — the two were ALREADY byte-identical at dp=1, so audit-usage's
      hard-coded "%.1f%s" is just `dp=1` with the parameter never exposed.
  _fmt_tokens(n, dp=2) adds hover precision ("3.23M") that audit-usage's CLI
      table never needed (a terminal has no hover state).
  _fmt_tokens(n, dp=0) rounds to a bare magnitude ("3M") — used nowhere yet, but
      exercised in that test file since the parameter must hold for any dp.
  fmt_cost(x) and _fmt_cost(x) are byte-identical for every x tried (0, the
      "<$0.01" rounding-to-zero rule at 0.004, 0.01, 1.234, 1234.5) — the ONLY
      difference was audit-usage's `show` flag, which _fmt_cost never had because
      render-report never suppresses a cost tile, it omits the whole tile.
  fmt_int has no counterpart in render-report (render-report keeps its own
      thousands-separator calls for countables, guarded by its own selftest
      u27 — that rule stays local to render-report, not moved here).

Parameter mapping, this module -> the two originals:
  fmt_tokens(n, dp=None)  dp=None means "1 decimal", matching BOTH audit-usage's
                          fixed "%.1f%s" (no parameter existed) and
                          render-report's `_fmt_tokens(n, dp=1)` default.
                          audit-usage's call sites pass no dp (get dp=None -> 1).
                          render-report's call sites pass dp=2 for hover.
  fmt_cost(x, show=True)  show=True (default) reproduces render-report's
                          `_fmt_cost(x)` (no flag, always shown) AND audit-usage's
                          un-suppressed calls. show=False reproduces audit-usage's
                          `fmt_cost(x, show=False)` -> "".
  fmt_int(n)              unchanged; audit-usage's shape only.

The share and the bar (added later, same reason, five copies not three)
-----------------------------------------------------------------------
One rule runs through this whole module: **a real value must never render as
nothing.** fmt_cost already owns it for money (`<$0.01`, never `$0.00`). The
same rule was hand-written twice more, in two other shapes, and neither had a
home here:

  * The share. `pct = "<1%" if 0 < share < 1 else "%.0f%%" % share`, typed out
    at audit-usage.py:356-358 (group table), audit-usage.py:434-436 (area
    table) and _report_usage.py:527-528 (author chips). Now `fmt_share`.
  * The bar. Five renderings of one arithmetic:
      audit-usage.bar(fraction, width=18)   `[####......]`, clamped, no minimum
      audit-status.py                       owned no bar: it importlib-loaded
                                            audit-usage.py, an ENTRY POINT,
                                            purely to borrow `bar()`, and its
                                            loader docstring conceded the shape
                                            "has no home in _fmt.py". It does
                                            now, so both the loader and the
                                            _deps.KNOWN_LAYER_DEBT entry it
                                            produced are gone.
      audit-usage render_trend, twice       `"#" * max(1 if n else 0, ...)` —
                                            (:563 md, :575 ascii) no brackets,
                                            no padding, and a MINIMUM of one
                                            cell for a non-zero day
      _report_html._bar(done, total)        not a text bar: an int percentage
                                            fed to a CSS `--w` custom property
    Split into `bar_cells` (the arithmetic, and the only divide) and `fmt_bar`
    (the one boxed ASCII shape). The trend sparkline and the CSS width are
    `bar_cells` with no `fmt_bar` around them, because they are not boxes.

The divide is the interesting part. Every copy above guards it the same wrong
way — `grand = tot["tokens"] or 1`, `total = sum(...) or 1`, `if total else 0` —
which converts "there is no total to measure against" into a confident `0%` or
an empty bar. Frozen from the originals, `orig_share(5, 0)` returns `"500%"`:
the `or 1` did not prevent a bad answer, it invented one. `share_pct` returns
None instead and makes each caller say what unmeasurable looks like.

Golden values frozen from the five originals BEFORE any call site was touched
(probe run against the verbatim expressions, results in the test file above):
  bar(0.5, 18)      == "[#########.........]"   == fmt_bar(1, 2, 18)
  bar(1/3., 12)     == "[####........]"         == fmt_bar(1, 3, 12)
  bar(1.5, 10)      == "[##########]"           == fmt_bar(15, 10, 10)  (clamp)
  bar(-0.5, 10)     == "[..........]"           == fmt_bar(-5, 10, 10)
  _bar(3, 7)  pct   == 43                       == bar_cells(3, 7, 100)
  _bar(0, 0)  pct   == 0                        == bar_cells(0, 0, 100)
  trend(1, 100000, 18)     == "#"   == "#" * bar_cells(1, 100000, 18, True)
  trend(0, 100000, 18)     == ""    == "#" * bar_cells(0, 100000, 18, True)
  trend(50000, 100000, 18) == "#########"
  share(25, 100) == "25%"; share(4, 1000) == "<1%"; share(0, 100) == "0%"
  share(1499, 100000) == "1%"; share(999, 100000) == "<1%"
  share(3, 2) == "150%"  (NOT clamped — see share_pct on area overlap)
Only the whole-is-0 inputs deliberately diverge from the originals, and that
divergence is the point.

This module carries no `--selftest` of its own any more; its 72 cases live in
`plugins/audit/tests/test__fmt.py`, byte-identical labels and all - see
`plugins/audit/tests/_harness.py`.
"""
import os
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


# --- formatting -----------------------------------------------------------------
def fmt_tokens(n, dp=None):
    """Compact, right-alignable token MAGNITUDE — `3.2M`, never `3,230,000`.
    `dp` controls decimal places past the magnitude letter; `None` (the default)
    means one decimal, matching both originals' default rendering."""
    if dp is None:
        dp = 1
    n = int(n or 0)
    for limit, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if abs(n) >= limit:
            return "%.*f%s" % (dp, n / float(limit), suffix)
    return str(n)


def fmt_cost(x, show=True):
    """`$1.23`; `<$0.01` for real-but-sub-cent spend (never `$0.00` — that reads
    as free); `""` when `show=False` (audit-usage's `--no-cost` shape)."""
    if not show:
        return ""
    x = float(x or 0.0)
    if x and abs(x) < 0.01:
        return "<$0.01"          # never render real spend as $0.00
    return "$%.2f" % x


def fmt_int(n):
    """Thousands-grouped COUNTABLE — `47,625` messages, never `47.6K`. Countables
    are numbers you can act on; magnitudes (tokens) are not — see fmt_tokens."""
    return "{:,}".format(int(n or 0))


# --- shares and bars ------------------------------------------------------------
def share_pct(part, whole):
    """`part` as a percentage of `whole` — or `None` when there is no whole.

    `None` is the whole reason this function exists. Every hand-written copy of
    the share rule guards the divide with `or 1` (`grand = tot["tokens"] or 1`,
    `total = sum(...) or 1`), and an `or 1` does not prevent a wrong answer, it
    manufactures one: run verbatim, the original expression turns `5` of a total
    of `0` into `"500%"`, and `0` of `0` into `"0%"`. An unguarded divide is a
    defect; reporting `0%` for a number nobody could compute is the worse one,
    because it is indistinguishable from a real measurement. Callers must decide
    what unmeasurable looks like — see `fmt_share`'s `unknown`.

    Deliberately NOT clamped to 100. audit-usage's area rows genuinely sum past
    the total (a phase tagged with several areas counts under each) and print a
    footnote saying so; clamping here would silently delete that fact. Clamping
    belongs to `bar_cells`, which has a box to fit inside."""
    whole = float(whole or 0.0)
    if not whole:
        return None
    return 100.0 * float(part or 0.0) / whole


def fmt_share(part, whole, unknown="?"):
    """`25%`; `<1%` for a real-but-sub-one-percent slice (never `0%` — that
    reads as "none", the same lie `$0.00` tells about real spend); `unknown`
    when there is no whole to divide by.

    `fmt_share(0, 100)` is `"0%"`, on purpose, and the two rules only look like
    they collide. "Never print 0%" is about a slice that EXISTS and rounds away;
    a part of 0 does not exist, and rendering it `<1%` would invent a presence
    the data does not have — the mirror-image lie. So the sub-one-percent branch
    fires only for a non-zero share, exactly as fmt_cost's `<$0.01` fires only
    for non-zero spend. `abs()` mirrors fmt_cost too: shares are non-negative by
    construction here, and the two siblings must not drift apart on the edge
    case neither of them meets.

    Note the branch is not just rounding: `0.6%` renders `<1%`, where `"%.0f%%"`
    alone would round it UP to `1%` and overstate a slice that never reached
    one percent."""
    pct = share_pct(part, whole)
    if pct is None:
        return unknown
    if pct and abs(pct) < 1:
        return "<1%"             # never render a real slice as 0%
    return "%.0f%%" % pct


def bar_cells(part, whole, width, min_fill=False):
    """How many of `width` cells a `part`/`whole` bar fills — the arithmetic
    under every bar shape in the tree, so the shapes can differ without the
    maths differing. The report's CSS fill is this at `width=100`, because a
    percentage IS a hundred-cell bar.

    Clamped to `0..width`: a bar has a box. audit-status draws an over-budget
    phase at `pct > 100` and must not spill past its own bracket.

    `min_fill=True` gives a non-zero part at least one cell — the bar's version
    of `<1%` and `<$0.01`. A day with real tokens must not draw as a blank row.
    Defaults False because the boxed bars never carried the rule and adopting
    this must not change what they print.

    Returns 0 cells when `whole` is 0, where `fmt_share` returns a sentinel, and
    the asymmetry is deliberate: every bar in this tree is printed beside its
    own `done/total`, so the denominator is right there to contradict an empty
    bar. A share string travels alone and has nothing to contradict it."""
    pct = share_pct(part, whole)
    if pct is None:
        return 0
    width = int(width)
    cells = int(round(width * pct / 100.0))
    if min_fill and pct and cells < 1:
        cells = 1
    return max(0, min(width, cells))


def fmt_bar(part, whole, width=18):
    """`[#########.........]` — the boxed share bar that survives any terminal.

    Pure ASCII, no box-drawing characters: audit-status and audit-usage print
    into whatever terminal the user has, and both selftests assert ASCII-only
    output. Takes `(part, whole)` rather than a fraction so the divide happens
    once, here, under `share_pct`'s guard, instead of at each call site."""
    cells = bar_cells(part, whole, width)
    return "[" + "#" * cells + "." * (int(width) - cells) + "]"


if __name__ == "__main__":
    import sys
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exits silently: `--selftest` is what every other
        # file here still accepts, so nothing would tell a reader whether this
        # one ran nothing or has nothing. It deliberately does NOT print the
        # suite contract - that literal is how `_output.selftest_coverage()`
        # tells an inline suite from a migrated one.
        print("_fmt.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__fmt.py - run that file instead.")
        raise SystemExit(0)
    sys.stderr.write("usage: _fmt.py --selftest\n")
    raise SystemExit(2)
