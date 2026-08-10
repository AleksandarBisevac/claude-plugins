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
  * audit-status.py deliberately did NOT grow a fourth copy: it importlib-loads
    audit-usage's `fmt_tokens`/`fmt_cost` at runtime (see its own docstring) and
    calls them as `au.fmt_tokens(...)` / `au.fmt_cost(...)`.

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
"""


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
