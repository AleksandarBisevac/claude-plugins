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
frozen in `_selftest` below, before either call site was touched):

  fmt_tokens(942)                == "942"    (below 1000: both variants agree)
  fmt_tokens(1000)               == "1.0K"   (both variants: one decimal default)
  fmt_tokens(2_000_000_000)      == "2.0B"
  _fmt_tokens(n)      (dp=1, the render-report default) == fmt_tokens(n) for every
      n tried — the two were ALREADY byte-identical at dp=1, so audit-usage's
      hard-coded "%.1f%s" is just `dp=1` with the parameter never exposed.
  _fmt_tokens(n, dp=2) adds hover precision ("3.23M") that audit-usage's CLI
      table never needed (a terminal has no hover state).
  _fmt_tokens(n, dp=0) rounds to a bare magnitude ("3M") — used nowhere yet, but
      exercised in the selftest below since the parameter must hold for any dp.
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
(probe run against the verbatim expressions, results in `_selftest` below):
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
"""


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


# --- selftest -------------------------------------------------------------------
def _selftest():
    cases = []

    def check(label, cond, detail=None):
        cases.append((label, bool(cond), detail))

    # Golden values, frozen from the two ORIGINAL implementations before either
    # call site was touched (audit-usage.py's fmt_tokens/fmt_cost/fmt_int and
    # render-report.py's _fmt_tokens/_fmt_cost, run pre-change).
    check("fmt_tokens: 0", fmt_tokens(0) == "0")
    check("fmt_tokens: 999 (below K, unchanged)", fmt_tokens(999) == "999")
    check("fmt_tokens: 1000 -> 1.0K", fmt_tokens(1000) == "1.0K")
    check("fmt_tokens: 1500 -> 1.5K", fmt_tokens(1500) == "1.5K")
    check("fmt_tokens: 1e6 -> 1.0M", fmt_tokens(1_000_000) == "1.0M")
    check("fmt_tokens: 2.5e6 -> 2.5M", fmt_tokens(2_500_000) == "2.5M")
    check("fmt_tokens: 1e9 -> 1.0B", fmt_tokens(1_000_000_000) == "1.0B")
    check("fmt_tokens: negative preserves sign", fmt_tokens(-1500) == "-1.5K")
    check("fmt_tokens: None -> 0", fmt_tokens(None) == "0")
    check("fmt_tokens: audit-usage golden 942", fmt_tokens(942) == "942")
    check("fmt_tokens: audit-usage golden 214300 -> 214.3K",
          fmt_tokens(214_300) == "214.3K")
    check("fmt_tokens: audit-usage golden 14700000 -> 14.7M",
          fmt_tokens(14_700_000) == "14.7M")
    check("fmt_tokens: audit-usage golden 2000000000 -> 2.0B",
          fmt_tokens(2_000_000_000) == "2.0B")
    # render-report's dp parameter, exactly as it was called (u26's own golden set)
    check("fmt_tokens: dp default == render-report's dp=1 default",
          fmt_tokens(3_230_000) == "3.2M")
    check("fmt_tokens: dp=2 hover precision", fmt_tokens(3_230_000, 2) == "3.23M")
    check("fmt_tokens: dp=2 golden 942", fmt_tokens(942, 2) == "942")
    check("fmt_tokens: dp=2 golden 2e9 -> 2.00B",
          fmt_tokens(2_000_000_000, 2) == "2.00B")
    check("fmt_tokens: dp=2 golden 214300 -> 214.30K",
          fmt_tokens(214_300, 2) == "214.30K")
    check("fmt_tokens: dp=0 bare magnitude", fmt_tokens(3_230_000, 0) == "3M")

    check("fmt_cost: 0 -> $0.00 (not suppressed)", fmt_cost(0) == "$0.00")
    check("fmt_cost: 0.004 -> <$0.01 (rounds-to-zero rule)",
          fmt_cost(0.004) == "<$0.01")
    check("fmt_cost: 0.01 -> $0.01", fmt_cost(0.01) == "$0.01")
    check("fmt_cost: 1.234 -> $1.23", fmt_cost(1.234) == "$1.23")
    check("fmt_cost: 1234.5 -> $1234.50", fmt_cost(1234.5) == "$1234.50")
    check("fmt_cost: audit-usage golden 42.1789 -> $42.18",
          fmt_cost(42.1789) == "$42.18")
    check("fmt_cost: None -> $0.00", fmt_cost(None) == "$0.00")
    check("fmt_cost: show=False suppresses (audit-usage's --no-cost shape)",
          fmt_cost(9.0, show=False) == "")
    check("fmt_cost: show=False suppresses even the <$0.01 case",
          fmt_cost(0.004, show=False) == "")

    check("fmt_int: 0", fmt_int(0) == "0")
    check("fmt_int: 999 (no separator below 1000)", fmt_int(999) == "999")
    check("fmt_int: 1000 -> 1,000 (grouping starts)", fmt_int(1000) == "1,000")
    check("fmt_int: audit-usage golden 47625 -> 47,625",
          fmt_int(47_625) == "47,625")
    check("fmt_int: negative preserves sign and groups",
          fmt_int(-1234) == "-1,234")
    check("fmt_int: None -> 0", fmt_int(None) == "0")

    # --- fmt_share ---------------------------------------------------------------
    # Golden values frozen from the THREE originals (audit-usage.py:356-358,
    # audit-usage.py:434-436, _report_usage.py:527-528) run verbatim before any
    # call site was touched. Only the whole-is-0 rows diverge, deliberately.
    #
    # These four values are chosen to separate implementations, not to be pretty:
    #   25/100    a clean 25% — the ONLY case that fails an implementation which
    #             has gone unconditional and answers "<1%" to everything.
    #   4/1000    0.4% — fails an implementation that lost the "<1%" branch
    #             ("0%") AND one that merely rounds ("0%").
    #   6/1000    0.6% — fails an implementation that tests `round(pct) == 0`
    #             instead of `pct < 1`, since "%.0f%%" rounds 0.6 UP to "1%".
    #   0/100     a true zero — fails an implementation where "<1%" fires on
    #             absence as well as smallness.
    check("fmt_share: 25/100 -> 25% (a share that is not small)",
          fmt_share(25, 100) == "25%")
    check("fmt_share: 4/1000 -> <1% (real slice, never 0%)",
          fmt_share(4, 1000) == "<1%")
    check("fmt_share: 6/1000 -> <1%, NOT the 1% that plain rounding gives",
          fmt_share(6, 1000) == "<1%" and "%.0f%%" % 0.6 == "1%")
    check("fmt_share: 0/100 -> 0% (absent is not small; <1% would invent a slice)",
          fmt_share(0, 100) == "0%")
    check("fmt_share: 1/100 -> 1% (boundary is exclusive, as in the originals)",
          fmt_share(1, 100) == "1%")
    check("fmt_share: 1499/100000 -> 1% (above 1, rounds down, not <1%)",
          fmt_share(1499, 100_000) == "1%")
    check("fmt_share: 999/100000 -> <1% (just under the boundary)",
          fmt_share(999, 100_000) == "<1%")
    check("fmt_share: 3/2 -> 150% (NOT clamped — audit-usage's area rows really "
          "do sum past the total)", fmt_share(3, 2) == "150%")
    check("fmt_share: None part -> 0% (a missing key is zero, as in fmt_tokens)",
          fmt_share(None, 100) == "0%")

    # The divide guard. The originals' `or 1` answered "0%" here (and "500%" for
    # 5-of-0); an unmeasurable share must not be reported as a measured one.
    check("fmt_share: 0/0 -> sentinel, not 0% (nothing to divide by)",
          fmt_share(0, 0) == "?")
    check("fmt_share: 5/0 -> sentinel, not the originals' fabricated 500%",
          fmt_share(5, 0) == "?")
    check("fmt_share: None whole -> sentinel", fmt_share(4, None) == "?")
    check("fmt_share: caller names the sentinel",
          fmt_share(0, 0, unknown="n/a") == "n/a")
    check("share_pct: no whole -> None, not a number",
          share_pct(0, 0) is None and share_pct(1, 2) == 50.0)

    # --- fmt_bar / bar_cells -----------------------------------------------------
    # Golden values frozen from audit-usage.bar(fraction, width) run verbatim,
    # with the fraction reshaped to the (part, whole) it was computed from.
    check("fmt_bar: golden bar(0.5, 18)", fmt_bar(1, 2, 18) ==
          "[#########.........]")
    check("fmt_bar: golden bar(1/3., 12)", fmt_bar(1, 3, 12) == "[####........]")
    check("fmt_bar: golden bar(7/12., 12)", fmt_bar(7, 12, 12) == "[#######.....]")
    check("fmt_bar: golden bar(1.0, 12) fills every cell",
          fmt_bar(12, 12, 12) == "[############]")
    check("fmt_bar: golden bar(0.0, 18) fills none",
          fmt_bar(0, 10, 18) == "[..................]")
    # Count the cells rather than asserting a substring: an unclamped bar still
    # CONTAINS "##########", it just also runs past the bracket.
    _over = fmt_bar(15, 10, 10)
    check("fmt_bar: over-100% clamps to a full box (audit-status' OVER budget)",
          _over.count("#") == 10 and _over.count(".") == 0 and len(_over) == 12)
    _neg = fmt_bar(-5, 10, 10)
    check("fmt_bar: negative clamps to an empty box",
          _neg.count("#") == 0 and _neg.count(".") == 10)
    _nowhole = fmt_bar(0, 0, 10)
    check("fmt_bar: no whole draws an empty box of the right width (the "
          "call site prints 0/0 beside it)",
          _nowhole == "[..........]" and len(_nowhole) == 12)
    check("fmt_bar: width is honoured for every fill (box never changes size)",
          all(len(fmt_bar(i, 10, 14)) == 16 for i in range(-2, 13)))

    # bar_cells at width=100 IS the report's CSS fill percentage (_report_html._bar).
    check("bar_cells: golden _bar(1, 2) pct", bar_cells(1, 2, 100) == 50)
    check("bar_cells: golden _bar(3, 7) pct", bar_cells(3, 7, 100) == 43)
    check("bar_cells: golden _bar(0, 0) pct", bar_cells(0, 0, 100) == 0)

    # min_fill, both directions. The first case is the trend bar's whole reason
    # to exist; the second is the one that looks vacuous and is the ONLY case
    # that goes red if min_fill becomes unconditional.
    check("bar_cells: min_fill gives a tiny-but-real day one cell",
          bar_cells(1, 100_000, 18, min_fill=True) == 1)
    check("bar_cells: without min_fill the same day rounds away (the boxed "
          "bars' frozen behaviour)", bar_cells(1, 100_000, 18) == 0)
    check("bar_cells: min_fill must NOT invent a cell for a true zero "
          "(second-direction case: catches an unconditional minimum)",
          bar_cells(0, 100_000, 18, min_fill=True) == 0)
    check("bar_cells: golden trend(50000, 100000, 18)",
          bar_cells(50_000, 100_000, 18, min_fill=True) == 9)
    check("bar_cells: min_fill still cannot exceed a zero-width box",
          bar_cells(1, 2, 0, min_fill=True) == 0)

    # Mutation proof: a real bug (dropping the "<$0.01" branch) must turn a
    # passing case red. Prove it here rather than merely asserting once.
    _real_fmt_cost = fmt_cost

    def _mutated_fmt_cost(x, show=True):
        if not show:
            return ""
        x = float(x or 0.0)
        return "$%.2f" % x  # the "<$0.01" branch is missing on purpose

    _mutant_result = _mutated_fmt_cost(0.004)
    check("mutation proof: dropping the <$0.01 branch breaks the 0.004 case "
          "(red proves the case can fail)",
          _mutant_result != "<$0.01" and _mutant_result == "$0.00")
    # restore (no module state was ever mutated; _real_fmt_cost is the real one)
    check("mutation proof: restored formatter still passes the same case",
          _real_fmt_cost(0.004) == "<$0.01")

    # Mutation proofs for fmt_share, in BOTH directions. A conditional fix has
    # two wrong implementations — it never fires, or it always fires — and the
    # case that catches the second looks vacuous, so it is named here on purpose.
    def _share_without_the_rule(part, whole):
        pct = share_pct(part, whole)
        return "%.0f%%" % pct      # the "<1%" branch is missing on purpose

    def _share_always_small(part, whole):
        pct = share_pct(part, whole)
        if abs(pct) < 1:           # the `pct and` guard is missing on purpose
            return "<1%"
        return "%.0f%%" % pct

    def _share_with_the_or_1_guard(part, whole):
        whole = float(whole or 0.0) or 1.0     # the originals' guard, restored
        share = 100.0 * float(part or 0.0) / whole
        return "<1%" if 0 < share < 1 else "%.0f%%" % share

    check("mutation proof (never fires): dropping the <1% branch renders a real "
          "0.4% slice as 0%, so the 4/1000 case goes red",
          _share_without_the_rule(4, 1000) == "0%" and fmt_share(4, 1000) == "<1%")
    check("mutation proof (always fires): dropping the non-zero guard renders a "
          "true 0 as <1%, so the 0/100 case goes red",
          _share_always_small(0, 100) == "<1%" and fmt_share(0, 100) == "0%")
    check("mutation proof (divide guard): the originals' `or 1` answers 0% for "
          "0/0 and fabricates 500% for 5/0, so both sentinel cases go red",
          _share_with_the_or_1_guard(0, 0) == "0%"
          and _share_with_the_or_1_guard(5, 0) == "500%"
          and fmt_share(0, 0) == "?" and fmt_share(5, 0) == "?")

    # Mutation proofs for the bar, also both directions.
    def _cells_without_the_clamp(part, whole, width, min_fill=False):
        pct = share_pct(part, whole)
        if pct is None:
            return 0
        cells = int(round(int(width) * pct / 100.0))
        if min_fill and pct and cells < 1:
            cells = 1
        return cells               # the 0..width clamp is missing on purpose

    def _cells_min_fill_unconditional(part, whole, width, min_fill=False):
        pct = share_pct(part, whole)
        if pct is None:
            return 0
        width = int(width)
        cells = int(round(width * pct / 100.0))
        if min_fill and cells < 1:  # the `pct and` guard is missing on purpose
            cells = 1
        return max(0, min(width, cells))

    _unclamped = _cells_without_the_clamp(15, 10, 10)
    check("mutation proof (bar): dropping the clamp draws 15 cells in a 10-cell "
          "box, so the OVER-budget case goes red",
          _unclamped == 15 and bar_cells(15, 10, 10) == 10)
    check("mutation proof (bar): an unconditional min_fill draws a cell for a "
          "true zero, so the zero-day case goes red",
          _cells_min_fill_unconditional(0, 100_000, 18, min_fill=True) == 1
          and bar_cells(0, 100_000, 18, min_fill=True) == 0)

    passed = sum(1 for _, ok, _ in cases if ok)
    for label, ok, detail in cases:
        line = "%s %s" % ("PASS" if ok else "FAIL", label)
        if not ok and detail is not None:
            line += "  (%r)" % (detail,)
        print(line)
    print("\n%s: %d/%d cases passed" % (
        "ALL PASS" if passed == len(cases) else "FAILURES", passed, len(cases)))
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    import sys
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: _fmt.py --selftest\n")
    raise SystemExit(2)
