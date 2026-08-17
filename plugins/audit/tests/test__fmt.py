#!/usr/bin/env python3
"""
The cases for `scripts/_fmt.py`, moved out of it - an importable helper.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list.

The golden values below were frozen from the FIVE originals this module replaced,
run verbatim before any call site was touched - so the comments naming
`audit-usage.py:356-358` and `_report_usage.py:527-528` are the provenance of the
numbers, not a description of code that lives here. They moved with the cases.

The five mutation proofs also moved unchanged. Each defines a deliberately broken
re-implementation beside the real function and asserts that the two disagree on the
exact input a case pins - which is what makes those cases provably able to fail
rather than merely observed passing.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _fmt as M                                   # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    # Golden values, frozen from the two ORIGINAL implementations before either
    # call site was touched (audit-usage.py's fmt_tokens/fmt_cost/fmt_int and
    # render-report.py's _fmt_tokens/_fmt_cost, run pre-change).
    check("fmt_tokens: 0", M.fmt_tokens(0) == "0")
    check("fmt_tokens: 999 (below K, unchanged)", M.fmt_tokens(999) == "999")
    check("fmt_tokens: 1000 -> 1.0K", M.fmt_tokens(1000) == "1.0K")
    check("fmt_tokens: 1500 -> 1.5K", M.fmt_tokens(1500) == "1.5K")
    check("fmt_tokens: 1e6 -> 1.0M", M.fmt_tokens(1_000_000) == "1.0M")
    check("fmt_tokens: 2.5e6 -> 2.5M", M.fmt_tokens(2_500_000) == "2.5M")
    check("fmt_tokens: 1e9 -> 1.0B", M.fmt_tokens(1_000_000_000) == "1.0B")
    check("fmt_tokens: negative preserves sign", M.fmt_tokens(-1500) == "-1.5K")
    check("fmt_tokens: None -> 0", M.fmt_tokens(None) == "0")
    check("fmt_tokens: audit-usage golden 942", M.fmt_tokens(942) == "942")
    check("fmt_tokens: audit-usage golden 214300 -> 214.3K",
          M.fmt_tokens(214_300) == "214.3K")
    check("fmt_tokens: audit-usage golden 14700000 -> 14.7M",
          M.fmt_tokens(14_700_000) == "14.7M")
    check("fmt_tokens: audit-usage golden 2000000000 -> 2.0B",
          M.fmt_tokens(2_000_000_000) == "2.0B")
    # render-report's dp parameter, exactly as it was called (u26's own golden set)
    check("fmt_tokens: dp default == render-report's dp=1 default",
          M.fmt_tokens(3_230_000) == "3.2M")
    check("fmt_tokens: dp=2 hover precision", M.fmt_tokens(3_230_000, 2) == "3.23M")
    check("fmt_tokens: dp=2 golden 942", M.fmt_tokens(942, 2) == "942")
    check("fmt_tokens: dp=2 golden 2e9 -> 2.00B",
          M.fmt_tokens(2_000_000_000, 2) == "2.00B")
    check("fmt_tokens: dp=2 golden 214300 -> 214.30K",
          M.fmt_tokens(214_300, 2) == "214.30K")
    check("fmt_tokens: dp=0 bare magnitude", M.fmt_tokens(3_230_000, 0) == "3M")

    check("fmt_cost: 0 -> $0.00 (not suppressed)", M.fmt_cost(0) == "$0.00")
    check("fmt_cost: 0.004 -> <$0.01 (rounds-to-zero rule)",
          M.fmt_cost(0.004) == "<$0.01")
    check("fmt_cost: 0.01 -> $0.01", M.fmt_cost(0.01) == "$0.01")
    check("fmt_cost: 1.234 -> $1.23", M.fmt_cost(1.234) == "$1.23")
    check("fmt_cost: 1234.5 -> $1234.50", M.fmt_cost(1234.5) == "$1234.50")
    check("fmt_cost: audit-usage golden 42.1789 -> $42.18",
          M.fmt_cost(42.1789) == "$42.18")
    check("fmt_cost: None -> $0.00", M.fmt_cost(None) == "$0.00")
    check("fmt_cost: show=False suppresses (audit-usage's --no-cost shape)",
          M.fmt_cost(9.0, show=False) == "")
    check("fmt_cost: show=False suppresses even the <$0.01 case",
          M.fmt_cost(0.004, show=False) == "")

    check("fmt_int: 0", M.fmt_int(0) == "0")
    check("fmt_int: 999 (no separator below 1000)", M.fmt_int(999) == "999")
    check("fmt_int: 1000 -> 1,000 (grouping starts)", M.fmt_int(1000) == "1,000")
    check("fmt_int: audit-usage golden 47625 -> 47,625",
          M.fmt_int(47_625) == "47,625")
    check("fmt_int: negative preserves sign and groups",
          M.fmt_int(-1234) == "-1,234")
    check("fmt_int: None -> 0", M.fmt_int(None) == "0")

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
          M.fmt_share(25, 100) == "25%")
    check("fmt_share: 4/1000 -> <1% (real slice, never 0%)",
          M.fmt_share(4, 1000) == "<1%")
    check("fmt_share: 6/1000 -> <1%, NOT the 1% that plain rounding gives",
          M.fmt_share(6, 1000) == "<1%" and "%.0f%%" % 0.6 == "1%")
    check("fmt_share: 0/100 -> 0% (absent is not small; <1% would invent a slice)",
          M.fmt_share(0, 100) == "0%")
    check("fmt_share: 1/100 -> 1% (boundary is exclusive, as in the originals)",
          M.fmt_share(1, 100) == "1%")
    check("fmt_share: 1499/100000 -> 1% (above 1, rounds down, not <1%)",
          M.fmt_share(1499, 100_000) == "1%")
    check("fmt_share: 999/100000 -> <1% (just under the boundary)",
          M.fmt_share(999, 100_000) == "<1%")
    check("fmt_share: 3/2 -> 150% (NOT clamped — audit-usage's area rows really "
          "do sum past the total)", M.fmt_share(3, 2) == "150%")
    check("fmt_share: None part -> 0% (a missing key is zero, as in fmt_tokens)",
          M.fmt_share(None, 100) == "0%")

    # The divide guard. The originals' `or 1` answered "0%" here (and "500%" for
    # 5-of-0); an unmeasurable share must not be reported as a measured one.
    check("fmt_share: 0/0 -> sentinel, not 0% (nothing to divide by)",
          M.fmt_share(0, 0) == "?")
    check("fmt_share: 5/0 -> sentinel, not the originals' fabricated 500%",
          M.fmt_share(5, 0) == "?")
    check("fmt_share: None whole -> sentinel", M.fmt_share(4, None) == "?")
    check("fmt_share: caller names the sentinel",
          M.fmt_share(0, 0, unknown="n/a") == "n/a")
    check("share_pct: no whole -> None, not a number",
          M.share_pct(0, 0) is None and M.share_pct(1, 2) == 50.0)

    # --- fmt_bar / bar_cells -----------------------------------------------------
    # Golden values frozen from audit-usage.bar(fraction, width) run verbatim,
    # with the fraction reshaped to the (part, whole) it was computed from.
    check("fmt_bar: golden bar(0.5, 18)", M.fmt_bar(1, 2, 18) ==
          "[#########.........]")
    check("fmt_bar: golden bar(1/3., 12)", M.fmt_bar(1, 3, 12) == "[####........]")
    check("fmt_bar: golden bar(7/12., 12)", M.fmt_bar(7, 12, 12) == "[#######.....]")
    check("fmt_bar: golden bar(1.0, 12) fills every cell",
          M.fmt_bar(12, 12, 12) == "[############]")
    check("fmt_bar: golden bar(0.0, 18) fills none",
          M.fmt_bar(0, 10, 18) == "[..................]")
    # Count the cells rather than asserting a substring: an unclamped bar still
    # CONTAINS "##########", it just also runs past the bracket.
    _over = M.fmt_bar(15, 10, 10)
    check("fmt_bar: over-100% clamps to a full box (audit-status' OVER budget)",
          _over.count("#") == 10 and _over.count(".") == 0 and len(_over) == 12)
    _neg = M.fmt_bar(-5, 10, 10)
    check("fmt_bar: negative clamps to an empty box",
          _neg.count("#") == 0 and _neg.count(".") == 10)
    _nowhole = M.fmt_bar(0, 0, 10)
    check("fmt_bar: no whole draws an empty box of the right width (the "
          "call site prints 0/0 beside it)",
          _nowhole == "[..........]" and len(_nowhole) == 12)
    check("fmt_bar: width is honoured for every fill (box never changes size)",
          all(len(M.fmt_bar(i, 10, 14)) == 16 for i in range(-2, 13)))

    # bar_cells at width=100 IS the report's CSS fill percentage (_report_html._bar).
    check("bar_cells: golden _bar(1, 2) pct", M.bar_cells(1, 2, 100) == 50)
    check("bar_cells: golden _bar(3, 7) pct", M.bar_cells(3, 7, 100) == 43)
    check("bar_cells: golden _bar(0, 0) pct", M.bar_cells(0, 0, 100) == 0)

    # min_fill, both directions. The first case is the trend bar's whole reason
    # to exist; the second is the one that looks vacuous and is the ONLY case
    # that goes red if min_fill becomes unconditional.
    check("bar_cells: min_fill gives a tiny-but-real day one cell",
          M.bar_cells(1, 100_000, 18, min_fill=True) == 1)
    check("bar_cells: without min_fill the same day rounds away (the boxed "
          "bars' frozen behaviour)", M.bar_cells(1, 100_000, 18) == 0)
    check("bar_cells: min_fill must NOT invent a cell for a true zero "
          "(second-direction case: catches an unconditional minimum)",
          M.bar_cells(0, 100_000, 18, min_fill=True) == 0)
    check("bar_cells: golden trend(50000, 100000, 18)",
          M.bar_cells(50_000, 100_000, 18, min_fill=True) == 9)
    check("bar_cells: min_fill still cannot exceed a zero-width box",
          M.bar_cells(1, 2, 0, min_fill=True) == 0)

    # Mutation proof: a real bug (dropping the "<$0.01" branch) must turn a
    # passing case red. Prove it here rather than merely asserting once.
    _real_fmt_cost = M.fmt_cost

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
        pct = M.share_pct(part, whole)
        return "%.0f%%" % pct      # the "<1%" branch is missing on purpose

    def _share_always_small(part, whole):
        pct = M.share_pct(part, whole)
        if abs(pct) < 1:           # the `pct and` guard is missing on purpose
            return "<1%"
        return "%.0f%%" % pct

    def _share_with_the_or_1_guard(part, whole):
        whole = float(whole or 0.0) or 1.0     # the originals' guard, restored
        share = 100.0 * float(part or 0.0) / whole
        return "<1%" if 0 < share < 1 else "%.0f%%" % share

    check("mutation proof (never fires): dropping the <1% branch renders a real "
          "0.4% slice as 0%, so the 4/1000 case goes red",
          _share_without_the_rule(4, 1000) == "0%" and M.fmt_share(4, 1000) == "<1%")
    check("mutation proof (always fires): dropping the non-zero guard renders a "
          "true 0 as <1%, so the 0/100 case goes red",
          _share_always_small(0, 100) == "<1%" and M.fmt_share(0, 100) == "0%")
    check("mutation proof (divide guard): the originals' `or 1` answers 0% for "
          "0/0 and fabricates 500% for 5/0, so both sentinel cases go red",
          _share_with_the_or_1_guard(0, 0) == "0%"
          and _share_with_the_or_1_guard(5, 0) == "500%"
          and M.fmt_share(0, 0) == "?" and M.fmt_share(5, 0) == "?")

    # Mutation proofs for the bar, also both directions.
    def _cells_without_the_clamp(part, whole, width, min_fill=False):
        pct = M.share_pct(part, whole)
        if pct is None:
            return 0
        cells = int(round(int(width) * pct / 100.0))
        if min_fill and pct and cells < 1:
            cells = 1
        return cells               # the 0..width clamp is missing on purpose

    def _cells_min_fill_unconditional(part, whole, width, min_fill=False):
        pct = M.share_pct(part, whole)
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
          _unclamped == 15 and M.bar_cells(15, 10, 10) == 10)
    check("mutation proof (bar): an unconditional min_fill draws a cell for a "
          "true zero, so the zero-day case goes red",
          _cells_min_fill_unconditional(0, 100_000, 18, min_fill=True) == 1
          and M.bar_cells(0, 100_000, 18, min_fill=True) == 0)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__fmt.py --selftest\n")
    raise SystemExit(2)
