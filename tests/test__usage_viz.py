#!/usr/bin/env python3
"""
The cases for `_usage_viz.py` — how the Usage section formats a number and
draws a bar.

THE ONE DIVIDE RULE, IN TWO ANSWERS, is what most of these cases are about.
`_fill_pct` and `_hover_share` answer "there is no whole to divide by"
differently on purpose — a bar's answer and a share string's — and the reason is
what sits BESIDE each. A bar never travels alone (its token count is printed
next to the track), so an unmeasurable width draws an empty track; a tooltip
line travels alone, so it must say `?` rather than report a confident `0%` that
reads exactly like a measured one. Both directions have a case, because a rule
that fires on everything is as wrong as one that never fires.

`or 1` is the defect these guard against. It is not a divide guard: it
fabricates a whole of one token, and every number measured against it becomes a
confident claim about a ledger that recorded nothing.

The formatters delegate to `_fmt` and are pinned as delegations rather than
re-tested — `_fmt` has its own suite, and a second set of cases over the same
rounding would be a second opinion about it.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _usage_viz as M                             # noqa: E402
import _fmt                                        # noqa: E402
import _report_html                                # noqa: E402
import _report_usage as _RU                        # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- the two answers to "there is no whole" ---
    check("uv1 `_fill_pct` is 0.0 when there is no whole - a CSS width has "
          "nowhere to put a sentinel, and the token count printed beside the "
          "track already says what the empty bar is worth",
          M._fill_pct(7, 0) == 0.0, M._fill_pct(7, 0))
    check("uv2 ...and it is the real share when there IS one, which is the "
          "case that fails if the guard swallows every divide",
          M._fill_pct(50, 100) == 50.0, M._fill_pct(50, 100))
    check("uv3 `_hover_share` says `?` for the same input, because a tooltip "
          "line travels alone and a confident `0%` reads exactly like a "
          "measured one", M._hover_share(7, 0) == "?", M._hover_share(7, 0))
    check("uv4 ...and it floors a real-but-tiny slice at `<1%` rather than "
          "rounding it to `0%`, which is the same lie `fmt_cost` refuses to "
          "tell about sub-cent spend",
          M._hover_share(3, 10000) == "<1%", M._hover_share(3, 10000))
    check("uv5 ...and `0%` is reserved for a genuine zero - the case that "
          "fails if the floor becomes unconditional",
          M._hover_share(0, 100) == "0%", M._hover_share(0, 100))
    check("uv6 both go through `_fmt`, so there is ONE divide in the tree: "
          "`_hover_share` IS `fmt_share` and `_fill_pct` reads `share_pct`",
          M._hover_share(1, 3) == _fmt.fmt_share(1, 3)
          and M._fill_pct(1, 3) == _fmt.share_pct(1, 3))

    # --- the formatters ---
    check("uv7 tokens are a MAGNITUDE and are always compact; `dp=2` is the "
          "hover affordance, one more figure than the label",
          M._fmt_tokens(3230000) == _fmt.fmt_tokens(3230000, dp=1)
          and M._fmt_tokens(3230000, 2) == _fmt.fmt_tokens(3230000, dp=2)
          and M._fmt_tokens(3230000) != M._fmt_tokens(3230000, 2),
          "%s / %s" % (M._fmt_tokens(3230000), M._fmt_tokens(3230000, 2)))
    check("uv8 ...and the default is dp=1, which is the wrapper's whole "
          "reason to exist rather than relying on _fmt's own sentinel",
          M._fmt_tokens(2600) == M._fmt_tokens(2600, 1),
          M._fmt_tokens(2600))
    check("uv9 an already-derived rate is read back as a share of a hundred, "
          "so it gets the same `<1%` floor every other share gets",
          M._fmt_pct(0.4) == "<1%" and M._fmt_pct(0.0) == "0%",
          "%s / %s" % (M._fmt_pct(0.4), M._fmt_pct(0.0)))
    check("uv10 ...and a rate that rounded to 0.0 upstream renders `0%`: the "
          "floor only reaches what survived that rounding, and guessing past "
          "it would be this renderer inventing information",
          M._fmt_pct(0.0) == "0%")
    check("uv11 `_fmt_cost` is a pure delegation to the one cost formatter",
          M._fmt_cost(0.004) == _fmt.fmt_cost(0.004), M._fmt_cost(0.004))

    # --- delta: not a share, and the case that says why ---
    check("uv12 `_delta` renders nothing when there is no prior period - a "
          "first-run report must not invent a trend",
          M._delta({}, "tokens") == "", M._delta({}, "tokens"))
    _d = M._delta({"compare": {"deltas": {"tokens": 0.0}}}, "tokens")
    check("uv13 ...and a zero delta says `+0%`, NOT `<1%`: a percent change is "
          "not a share, and 'essentially unchanged' is true where 'a slice "
          "exists' would not be", "+0%" in _d and "<1%" not in _d, _d)
    _d = M._delta({"compare": {"deltas": {"tokens": -4.0}}}, "tokens")
    check("uv14 ...and a negative delta carries its sign and its direction "
          "class", "-4%" in _d and 'class="dl down"' in _d, _d)

    # --- slots: colour follows the entity ---
    _slots = M._model_slots(["z", "a", "m"])
    check("uv15 slots are assigned by NAME (sorted), never by rank, so "
          "filtering or re-sorting a chart cannot repaint the survivors",
          _slots == {"a": 1, "m": 2, "z": 3}, _slots)
    _many = M._model_slots([chr(ord("a") + i) for i in range(12)])
    check("uv16 ...and past VIZ_SLOTS the tail folds into one slot rather "
          "than generating hues nothing can distinguish",
          max(_many.values()) == M.VIZ_SLOTS
          and len([v for v in _many.values() if v == M.VIZ_SLOTS]) == 5,
          sorted(_many.items()))

    # --- tooltips, written once and used twice ---
    _t = M._tip("head", [("tokens", "1.2M"), ("cost", None)])
    check("uv17 `_tip` drops a row whose value is None, so an absent figure "
          "leaves no empty line behind",
          "tokens" in _t and "cost" not in _t, _t)
    check("uv18 ...and it separates rows by newline and label from value by "
          "tab, both of which survive a NATIVE title tooltip - the fallback "
          "is readable rather than merely present",
          "\n" in _t and "\t" in _t, repr(_t))
    check("uv19 ...and it escapes, because the header can carry a manifest "
          "string", "&lt;" in M._tip("<b>", []), M._tip("<b>", []))
    check("uv20 a header with no rows renders as just the header",
          M._tip("head", []) == "head", M._tip("head", []))

    # --- sparklines: the shape, and what is refused ---
    check("uv21 a sparkline with no values renders nothing", M._spark([], 5, "c") == "")
    check("uv22 ...and a shared peak of ZERO renders nothing rather than an "
          "empty frame drawn to a scale nobody measured - the `or 1` this "
          "file refuses, in its geometric form", M._spark([0, 0], 0, "c") == "")
    _sp = M._spark([0, 5], 5, "c", ["d1", "d2"], "m")
    check("uv23 ...while a zero column inside a real series emits no rect at "
          "all: on a shared axis most panels are mostly zeros, and emitting "
          "them cost 74 KB of invisible markup in a 300-phase report",
          _sp.count("<rect x=") == 1, _sp)
    check("uv24 ...and the hover target is a full-height transparent rect, "
          "not the visible bar: a quiet day draws 2px tall and a 2px hit "
          "target is one nobody can hit", 'class="hit"' in _sp, _sp)

    _labels, _groups, _size = M._bin_days(["a", "b", "c"])
    check("uv25 `_bin_days` is the identity below the column limit",
          _labels == ["a", "b", "c"] and _size == 1, (_labels, _size))
    _days = ["d%03d" % i for i in range(M.SPARK_COLS * 2 + 1)]
    _labels, _groups, _size = M._bin_days(_days)
    check("uv26 ...and past it the columns are binned, the bin SIZE is "
          "returned so the caption can state the resolution, and a multi-day "
          "bin is labelled as a range",
          _size > 1 and len(_labels) <= M.SPARK_COLS and " to " in _labels[0],
          (_size, len(_labels), _labels[0]))

    # --- the aliases ---
    check("uv27 `e` here IS `_report_html.e` - one escaper in the report "
          "stack, not a second one that could diverge on quoting",
          M.e is _report_html.e)
    _names = ("VIZ_SLOTS", "TOP_N", "SPARK_COLS", "_fmt_tokens", "_fmt_cost",
              "_fmt_pct", "_model_slots", "_delta", "_tip", "_tile",
              "_fill_pct", "_hover_share", "_bin_days", "_spark", "e")
    _forked = [n for n in _names if getattr(_RU, n) is not getattr(M, n)]
    check("uv28 every primitive `_report_usage` re-exports IS this module's "
          "object, so the 27 names that module's own suite reads are aliases "
          "rather than a second definition: %r" % (_forked,), _forked == [])


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__usage_viz.py --selftest\n")
    raise SystemExit(2)
