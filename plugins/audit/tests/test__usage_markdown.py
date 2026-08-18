#!/usr/bin/env python3
"""
The cases for `_usage_markdown.py` — the Usage section's Markdown twin.

This table is not a summary of the charts and not decoration: three light-mode
categorical slots sit under 3:1 contrast, and this table IS the documented
relief for that. So the cases here are mostly about PARITY — the twin must hold
every number the charts encode in colour, must apply the same floors, and must
not know a month the page does not.

The floor matters more here than anywhere else, and for a reason that is easy to
get backwards: a `0%` printed here where the page prints `<1%` would make the
accessibility relief the *less* honest of the two documents.

Markdown carries the bare `<1%` and the bare `<$0.01` — no escaping — the way it
already carries every other formatter's output, and a case pins that, because
the HTML twin escapes both and a shared helper could quietly start escaping for
both.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _usage_markdown as M                        # noqa: E402
import _usage_viz as _viz                          # noqa: E402
import _ui_theme as _theme                         # noqa: E402
import _report_usage as _RU                        # noqa: E402
import _report_md as _RMD                          # noqa: E402


def _u(**kw):
    u = {"totals": {"tokens": 1000, "costUSD": 1.0, "msgs": 10, "sessions": 2,
                    "cacheHitPct": 50.0},
         "showCost": True, "pricingAsOf": "2026-06-01",
         "byPhase": {"P0": {"tokens": 600, "costUSD": 0.6, "msgs": 6}},
         "byModel": {"opus": {"tokens": 1000, "costUSD": 1.0, "msgs": 10}},
         "byAuthor": {}, "monthly": {}, "unit": {}, "retry": {},
         "cache": {}, "coverage": {}, "routing": {}}
    u.update(kw)
    return u


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- the cell escaper ---
    check("um1 a pipe is escaped and a newline is flattened - the only two "
          "metacharacters that would break a table row",
          M._md("a|b\nc") == "a\\|b c", M._md("a|b\nc"))
    check("um2 ...and None renders the em dash, so an absent value is a "
          "visible gap rather than the word 'None'", M._md(None) == "—",
          M._md(None))
    check("um3 ...and raw HTML passes through unescaped: this document is "
          "read by GitHub, and hardening is `render_html`'s job",
          M._md("<b>x</b>") == "<b>x</b>", M._md("<b>x</b>"))

    # --- the gate ---
    check("um4 no usage renders nothing at all",
          M._usage_md(None) == "" and M._usage_md({}) == "")
    check("um5 ...and a ledger with zero tokens renders nothing either: an "
          "empty table is not a measurement",
          M._usage_md({"totals": {"tokens": 0}}) == "")

    # --- the header line ---
    out = M._usage_md(_u())
    check("um6 the header carries the totals, the session count and the cache "
          "hit - the numbers the tiles show",
          "**Total:**" in out and "2 session(s)" in out
          and "cache hit 50%" in out, out.split("\n")[3])
    check("um7 ...and the rate date, the same basis the HTML context line "
          "states", "rates as of 2026-06-01" in out, "")
    out_nd = M._usage_md(_u(pricingAsOf=None))
    check("um8 ...and with costs shown but no date declared it says so, "
          "rather than falling back to a date this project never chose",
          "rates undated" in out_nd, "")
    out_nc = M._usage_md(_u(showCost=False))
    check("um9 ...and with showCost off it carries neither the cost nor the "
          "rate basis: a basis with no claim beside it is noise here too",
          "equiv" in out and "equiv" not in out_nc and "rates" not in out_nc,
          "")

    # --- the breakdown tables ---
    # ONE author, not none: an empty byAuthor cannot tell `> 1` from `> 0`,
    # which is how the first version of this case survived that mutation.
    out_one = M._usage_md(_u(byAuthor={"a": {"tokens": 10, "costUSD": 1.0,
                                             "msgs": 10}}))
    check("um10 By phase and By model always render; By author only when "
          "there is more than one author to compare, the same gate the chips "
          "use - so a SINGLE author still gets no table",
          "### By phase" in out and "### By model" in out
          and "### By author" not in out_one, "")
    out_two = M._usage_md(_u(byAuthor={"a": {"tokens": 6, "costUSD": 0.1,
                                             "msgs": 1},
                                       "b": {"tokens": 4, "costUSD": 0.1,
                                             "msgs": 1}}))
    check("um11 ...and two authors do render it - the case that fails if the "
          "gate is dropped or inverted", "### By author" in out_two, "")
    out_unc = M._usage_md(_u(byPhase={"--": {"tokens": 5, "costUSD": 0.1,
                                             "msgs": 1}}))
    check("um12 ...and the empty bucket wears the shared word, never the "
          "storage key: the Markdown twin is read by people too",
          _theme.UNCATEGORIZED in out_unc and "| -- |" not in out_unc, "")
    check("um13 ...and the cost COLUMN disappears with showCost off, header "
          "separator included - a half-dropped column would misalign every row",
          "| tokens | cost | msgs |" in out
          and "| tokens | msgs |" in out_nc, "")

    # --- the floors, which is the whole reason this table is the relief ---
    out_tiny = M._usage_md(_u(cache={"hitPct": 0.4,
                                     "inputCostVsFreshPct": 100},
                              coverage={"attributedPct": 0.4,
                                        "taskLevelPct": 0.0}))
    check("um14 every rate is floored exactly as its HTML twin is: a `0%` "
          "printed here where the page prints `<1%` would make the documented "
          "relief the less honest of the two documents",
          "<1% hit" in out_tiny, "")
    check("um15 ...and it carries the BARE `<1%`, unescaped, the way it "
          "already carries `_fmt_cost`'s bare `<$0.01`",
          "&lt;" not in out_tiny, "")
    check("um16 ...while a genuine zero still prints `0%` - the case that "
          "fails if the floor becomes unconditional",
          "0% of spend attributed" in M._usage_md(
              _u(coverage={"attributedPct": 0.0, "taskLevelPct": 0.0})), "")

    # --- the analytics parity ---
    out_e = M._usage_md(_u(unit={"costPerTask": 0.5, "completed": 4, "gate": 5},
                           retry={"totalCost": 1.0, "retriedCost": 0.4,
                                  "retriedTasks": 2, "retriedPct": 40.0,
                                  "blockedCost": 0.1, "blockedTasks": 1}))
    check("um17 the Economics list carries the same caveat the page does - "
          "retried spend is not wasted spend, because the ledger buckets by "
          "hour and not by attempt",
          "### Economics" in out_e
          and "Not the same as wasted spend" in out_e, "")
    check("um18 ...and a projection below the sample gate is reported as "
          "SUPPRESSED with both numbers, never omitted silently",
          "suppressed — needs 5 completed tasks, has 4" in out_e, "")
    out_m = M._usage_md(_u(monthly={
        "months": ["2026-06", "2026-07"],
        "ledger": {"2026-06": {"tokens": 5, "costUSD": 0.1, "msgs": 1},
                   "2026-07": {"tokens": 6, "costUSD": 0.1, "msgs": 1}},
        "plan": {"2026-06": {"tasksCompleted": 1}, "2026-07": {}}}))
    check("um19 the monthly table shares the HTML's two-active-months gate "
          "and its derivation note, so the twin cannot know months the page "
          "does not",
          "### Month by month" in out_m and "completedAt" in out_m, "")
    check("um20 ...and one active month renders no monthly table here either",
          "### Month by month" not in M._usage_md(_u(monthly={
              "months": ["2026-06"],
              "ledger": {"2026-06": {"tokens": 5, "msgs": 1}},
              "plan": {}})), "")
    out_r = M._usage_md(_u(routing={
        "risks": ["high"],
        "byRisk": {"high": {"opus": {"tasks": 3, "costPerTask": 0.5,
                                     "meanAttempts": 1.2}}}}))
    check("um21 the routing table carries the WHY as well as the numbers: "
          "compared inside a band on purpose, because hard work is routed to "
          "the stronger model deliberately",
          "### Model cost within each risk band" in out_r
          and "would flag that working system as a fault" in out_r, "")

    # --- the aliases, and who reads this module ---
    check("um22 `_report_md` reads `_usage_md` from HERE, not through "
          "`_report_usage` - which is what keeps the report's Markdown "
          "renderer strictly below the Usage section's assembly instead of "
          "beside it", _RMD._usage_md is M._usage_md)
    check("um23 ...and `_report_usage` still re-exports both names, because "
          "its own suite and render-report read them off that module",
          _RU._usage_md is M._usage_md and _RU._md is M._md)
    _drift = [n for n in ("_fmt_cost", "_fmt_pct", "_fmt_tokens")
              if getattr(M, n) is not getattr(_viz, n)]
    check("um24 ...and every formatter it prints through is `_usage_viz`'s "
          "object, which is what makes the floor parity above structural "
          "rather than coincidental: %r" % (_drift,), _drift == [])


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__usage_markdown.py --selftest\n")
    raise SystemExit(2)
