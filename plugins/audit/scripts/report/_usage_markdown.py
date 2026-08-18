#!/usr/bin/env python3
"""
The Usage section's Markdown twin - the same numbers as a table.

Split out of `_report_usage.py`. This is not decoration and not a summary of the
charts: three light-mode categorical slots sit under 3:1 contrast, and the
documented relief for that is a table carrying the same numbers - so this file
has to hold every figure the charts encode in colour, and a gate it did not
share with the HTML would make the relief the less honest of the two.

Every rate here is floored through `_fmt_pct` exactly as its HTML twin is, and
Markdown carries the bare `<1%` the way it already carries `_fmt_cost`'s bare
`<$0.01`. The monthly table keeps the same two-active-months gate and the same
derivation note, because the twin must not know months the page does not.

`_report_md.py` reads `_usage_md` from HERE rather than through
`_report_usage`, which is what keeps the report's Markdown renderer strictly
below the Usage section's assembly instead of beside it.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__usage_markdown.py` - see
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

import _ui_theme as _theme  # noqa: E402  (the one place a machine value gets its words)

import _usage_viz as _viz  # noqa: E402  (the section's number formatting and marks)

# Thin module-level aliases, not copies: the bodies below were moved out of
# `_report_usage.py` unchanged, and an alias keeps them reading the same names
# while there is still exactly one definition of each. A case pins the identity.
_fmt_cost = _viz._fmt_cost
_fmt_pct = _viz._fmt_pct
_fmt_tokens = _viz._fmt_tokens


# --- the cell escaper ----------------------------------------------------------
def _md(v):
    """Markdown cell escaper — same contract as render_md's local `cell`: only the
    metacharacters that would break a pipe table."""
    return str(v if v is not None else "—").replace("|", "\\|").replace("\n", " ")


# --- the table view ------------------------------------------------------------
def _usage_md(u):
    """The table view of the Usage section. This is not decoration: three light-mode
    categorical slots sit under 3:1 contrast, and the documented relief for that is
    a table carrying the same numbers. It also keeps the Markdown twin honest."""
    if not u or not u.get("totals", {}).get("tokens"):
        return ""
    t = u["totals"]
    show_cost = u.get("showCost", True)
    lines = ["", "## Usage", ""]
    head = "**Total:** %s tokens" % _fmt_tokens(t["tokens"])
    if show_cost:
        head += " · ~%s equiv" % _fmt_cost(t["costUSD"])
    head += " · %s msgs · %d session(s) · cache hit %s" % (
        "{:,}".format(t["msgs"]), t["sessions"], _fmt_pct(t["cacheHitPct"]))
    if show_cost:                       # see _usage_context for why there is no fallback
        head += (" · rates as of %s" % u["pricingAsOf"] if u.get("pricingAsOf")
                 else " · rates undated (set usage.pricingAsOf)")
    lines += [head, ""]

    def block(title, data, key_label):
        if not data:
            return []
        cols = "| %s | tokens | %smsgs |" % (key_label, "cost | " if show_cost else "")
        sep = "|---|---:|%s---:|" % ("---:|" if show_cost else "")
        rows = []
        for k, v in sorted(data.items(), key=lambda kv: -kv[1]["tokens"]):
            # One decimal, matching the ranked list this table mirrors. The
            # two-decimal form is the hover affordance, and Markdown has no hover.
            # uc (F-P-2): the Markdown twin is read by people too — the same
            # word as the HTML and the CLI, never the storage key.
            cells = [_theme.UNCATEGORIZED if k == "--" else k,
                     _fmt_tokens(v["tokens"])]
            if show_cost:
                cells.append(_fmt_cost(v["costUSD"]))
            cells.append("{:,}".format(v["msgs"]))
            rows.append("| %s |" % " | ".join(_md(c) for c in cells))
        return ["### %s" % title, "", cols, sep] + rows + [""]

    lines += block("By phase", u["byPhase"], "phase")
    lines += block("By model", u["byModel"], "model")
    if len(u.get("byAuthor") or {}) > 1:
        lines += block("By author", u["byAuthor"], "author")

    # The monthly overview, same gate and same derivation note as the HTML —
    # the twin must not know months the page does not, or vice versa.
    _ma = u.get("monthly") or {}
    _mm = _ma.get("months") or []
    _mled = _ma.get("ledger") or {}
    _mplan = _ma.get("plan") or {}
    if len([m for m in _mm
            if (_mled.get(m) or {}).get("tokens")
            or (_mled.get(m) or {}).get("msgs")]) >= 2:
        cols = ("| month | tokens | %smsgs | tasks done | bugs | fixed | "
                "merged |" % ("cost | " if show_cost else ""))
        sep = "|---|---:|%s---:|---:|---:|---:|---:|" % (
            "---:|" if show_cost else "")
        lines += ["### Month by month", "",
                  "Plan columns count the whole project by event month (task "
                  "completedAt, bug reportedAt, the linked task's completedAt "
                  "for a fix, phase mergedAt).", "", cols, sep]
        for m in _mm:
            lg = _mled.get(m) or {}
            pl = _mplan.get(m) or {}
            cells = [m, _fmt_tokens(lg.get("tokens", 0))]
            if show_cost:
                cells.append(_fmt_cost(lg.get("costUSD", 0.0)))
            cells += ["{:,}".format(lg.get("msgs", 0)),
                      str(pl.get("tasksCompleted", 0)),
                      str(pl.get("bugsReported", 0)),
                      str(pl.get("bugsFixed", 0)),
                      str(pl.get("phasesMerged", 0))]
            lines.append("| %s |" % " | ".join(_md(c) for c in cells))
        lines.append("")

    # The analytics carry the same honesty caveats as the HTML. This is not a
    # summary of the charts — for the three light-mode palette slots that sit under
    # 3:1 contrast, this table IS the documented relief, so it has to hold every
    # number the charts encode in colour.
    unit, retry = u.get("unit") or {}, u.get("retry") or {}
    cache, cov = u.get("cache") or {}, u.get("coverage") or {}
    # Every rate here is floored through `_fmt_pct`, exactly as its HTML twin is:
    # this table IS the documented relief for the light-mode palette slots, so a
    # `0%` it prints where the page prints `<1%` would make the relief the less
    # honest of the two. Markdown carries the bare `<1%` the way it already
    # carries `_fmt_cost`'s bare `<$0.01`.
    facts = []
    if cache:
        facts.append("- **Cache:** %s hit; the input side bills at %s of "
                     "fresh-token rates."
                     % (_fmt_pct(cache.get("hitPct", 0)),
                        _fmt_pct(cache.get("inputCostVsFreshPct", 100))))
        if cache.get("worstPhase"):
            facts.append("- **Lowest cache phase:** %s at %s."
                         % (_md(cache["worstPhase"][0]),
                            _fmt_pct(cache["worstPhase"][1])))
    if cov:
        facts.append("- **Attribution:** %s of spend attributed (%s to a "
                     "specific task)." % (_fmt_pct(cov.get("attributedPct", 0)),
                                          _fmt_pct(cov.get("taskLevelPct", 0))))
    if unit.get("costPerTask") is not None:
        facts.append("- **Cost per completed task:** %s across %d task(s)."
                     % (_fmt_cost(unit["costPerTask"]), unit.get("completed", 0)))
    if unit.get("sufficient") and unit.get("projection"):
        facts.append("- **Projection:** remaining %d task(s) at the p25-p75 rate = "
                     "%s to %s." % (unit["remaining"],
                                    _fmt_cost(unit["projection"]["low"]),
                                    _fmt_cost(unit["projection"]["high"])))
    elif unit.get("completed") is not None:
        facts.append("- **Projection:** suppressed — needs %d completed tasks, has "
                     "%d." % (unit.get("gate", 5), unit.get("completed", 0)))
    if retry.get("totalCost"):
        facts.append("- **Retried tasks:** %s across %d task(s) (%s of spend). "
                     "Not the same as wasted spend — the ledger buckets by hour, "
                     "not by attempt."
                     % (_fmt_cost(retry["retriedCost"]), retry["retriedTasks"],
                        _fmt_pct(retry["retriedPct"])))
        facts.append("- **Blocked tasks:** %s across %d task(s) — spend with no "
                     "outcome." % (_fmt_cost(retry["blockedCost"]),
                                   retry["blockedTasks"]))
    if facts:
        lines += ["### Economics", ""] + facts + [""]

    rt = u.get("routing") or {}
    if rt.get("risks"):
        lines += ["### Model cost within each risk band", "",
                  "Compared inside a band on purpose: hard work is routed to the "
                  "stronger model deliberately, so a raw spend-per-task comparison "
                  "across bands would flag that working system as a fault.", "",
                  "| risk | model | tasks | cost/task | mean attempts |",
                  "|---|---|---:|---:|---:|"]
        for risk in rt["risks"]:
            for model, c in sorted(rt["byRisk"][risk].items()):
                lines.append("| %s | %s | %d | %s | %.1f |" % (
                    _md(risk), _md(model), c["tasks"],
                    _fmt_cost(c["costPerTask"]), c["meanAttempts"] or 0))
        lines.append("")
    return "\n".join(lines)

# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exiting silently: `--selftest` is what every other
        # file here accepts, so nothing would tell a reader whether this one ran
        # nothing or has nothing. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_usage_markdown.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__usage_markdown.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
