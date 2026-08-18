#!/usr/bin/env python3
"""
How the Usage section formats a number and draws a bar - the primitives every
fragment of it shares.

Split out of `_report_usage.py`, which was 1,477 lines, and this is the piece
all four of the others read. Nothing here knows what a phase or an author is:
it takes numbers and returns strings and SVG.

THE ONE DIVIDE RULE, IN TWO ANSWERS. `_fill_pct` and `_hover_share` are the two
answers to "there is no whole to divide by" - a BAR's and a share STRING's - and
they differ because of what sits beside them. A bar never travels alone (the
token count is printed next to the track), so an unmeasurable width draws an
empty track; a tooltip line travels alone, so it must say `?` rather than report
a confident `0%` that reads exactly like a measured one. Both go through
`_fmt.share_pct` / `_fmt.fmt_share`, once per divide. No `or 1` anywhere: that
is not a divide guard, it fabricates a denominator and turns an unmeasurable
share into a confident one.

`_fmt_tokens` / `_fmt_cost` / `_fmt_pct` delegate to `_fmt` (P10.6), the one
token/cost/share formatter shared with the panel and /audit:usage. The wrappers
exist for this section's own defaults, not for a second implementation.

`_tip` is written ONCE and used twice - as the `title` a browser shows natively
with JavaScript off, and as the payload the styled tooltip re-renders - so the
two can never drift apart.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__usage_viz.py` - see `plugins/audit/tests/_harness.py`.
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

import _fmt  # noqa: E402  (the one token/cost/share formatter)
import _report_html  # noqa: E402  (escaping and the shared fragment helpers)

e = _report_html.e


# --- constants + number formatting ---------------------------------------------
VIZ_SLOTS = 8
# One folding rule for every categorical list in the section. Past this many
# entities a reader stops comparing and starts scrolling, and the palette runs out
# of distinguishable hues — so the tail is folded and SAID, never silently cut.
TOP_N = 8


def _fmt_tokens(n, dp=1):
    """Token counts are a MAGNITUDE and are always compact — `3.2M`, never
    `3,230,000`. Eight digits are unreadable at a glance and unreadable in a
    tooltip; what a reader compares is the order of magnitude and one or two
    figures past it.

    `dp=2` is for hover: pointing at a bar buys you `3.23M` instead of `3.2M` —
    more precision than the label, without dumping the raw integer.

    Countables (messages, sessions, tasks) are NOT magnitudes and keep their
    thousand separators: `47,625` messages is a number you can act on, `47.6K`
    throws away the thing that made it a count.

    Delegates to _fmt.py (the one token/cost formatter); this wrapper exists
    only to keep this file's own default (`dp=1`) as its own default rather
    than relying on _fmt's `dp=None` sentinel."""
    return _fmt.fmt_tokens(n, dp=dp)


def _fmt_cost(x):
    return _fmt.fmt_cost(x)


def _fmt_pct(x):
    """An ALREADY-DERIVED rate — cache hit, attribution coverage, retried share
    of spend — rendered under the one share rule: `<1%` for a real-but-tiny
    rate, never the `0%` that reads as "none".

    These arrive as percentages rather than as a part and a whole: the divide
    happened in _usage_analytics, which rounds each to one decimal.
    `fmt_share(x, 100)` is that percentage read back as a share of a hundred —
    the same identity `_fmt.bar_cells(part, whole, 100)` already uses for the
    CSS fill, and byte-identical to the `"%.0f%%"` it replaces everywhere
    outside the 0-to-1 window.

    The floor therefore only reaches what survived that rounding: a rate under
    0.05% arrives here as `0.0` and is indistinguishable from a genuine zero.
    That is upstream's information to keep, not this renderer's to guess at —
    so `0.0` renders `0%`, which is what the number actually says."""
    return _fmt.fmt_share(x, 100)


def _model_slots(models):
    """model -> categorical slot, assigned by NAME (sorted), never by rank.

    Colour follows the entity: filtering or re-sorting the chart must not repaint
    the survivors. Past 8 models the tail folds into one 'other' slot rather than
    generating a 9th hue nothing can distinguish."""
    ordered = sorted(models)
    slots = {}
    for i, m in enumerate(ordered):
        slots[m] = (i + 1) if i < VIZ_SLOTS else VIZ_SLOTS
    return slots


def _delta(u, key):
    """`+12%` / `-4%` vs the previous period, or '' when there is nothing to compare
    against. A first-run report must not invent a trend.

    NOT floored, because this is not a share: `+0%` says "essentially unchanged",
    which is true and is what a reader wants from a delta, where `<1%` would
    claim a slice exists. The sign is part of the string too, and `+<1%` is not
    a thing anyone reads."""
    cmp_ = u.get("compare") or {}
    d = (cmp_.get("deltas") or {}).get(key)
    if d is None:
        return ""
    sign = "up" if d >= 0 else "down"
    return ('<span class="dl %s">%s%.0f%%</span>' % (sign, "+" if d >= 0 else "", d))


# --- shares: a bar's answer, and a share string's ------------------------------
def _fill_pct(part, whole):
    """How wide a bar's fill is, in percent — 0.0 when there is no whole.

    `_fmt.share_pct` owns the divide; this only names the BAR's answer to a share
    nobody can compute, which is not the share string's answer. No bar in this
    section travels alone: the ranked rows and the phase stacks each print their
    own token count beside the track, so an empty track sits next to the number
    that explains it, while a `width:` has nowhere to put a sentinel. Same
    asymmetry, same reasoning as `_fmt.bar_cells`, which returns 0 cells here.

    Not `_fmt.bar_cells(part, whole, 100)` itself: these tracks are drawn at one
    decimal, and the ranked list floors a real-but-tiny row at 0.8% — a whole-cell
    minimum would round that to 1.0% and change every measurable row that has it.

    Left unfloored when `_hover_share` adopted `fmt_share`'s `<1%`: a CSS width
    has no way to say "<1%", the ranked list's own 0.8% minimum is the geometric
    form of the same rule, and the token count printed beside the track already
    says what the empty-looking bar is worth."""
    pct = _fmt.share_pct(part, whole)
    return 0.0 if pct is None else pct


def _hover_share(part, whole):
    """`part` as a percentage of `whole` for a hover line — `<1%` for a
    real-but-tiny slice, `0%` only for a genuine zero, `?` when there is no
    whole to divide by.

    A PURE ALIAS for `_fmt.fmt_share`, and said out loud rather than dressed up:
    it adds nothing, not even the sentinel, which is fmt_share's own default. It
    keeps its name because `_fill_pct` and `_hover_share` are how the rest of
    this file names the two answers to "there is no whole" — a bar's and a share
    string's — and a name is cheaper to keep than a second copy of the rule,
    which is how the two drift.

    The mirror of `_fill_pct`: this string sits alone inside a tooltip with
    nothing beside it, so an unmeasurable share must say so rather than report a
    confident `0%` that reads exactly like a measured one — and, since this
    change, a MEASURABLE one must not say `0%` either. It used to reimplement
    fmt_share without the `<1%` floor on purpose, so that guarding the divide
    could not move a measurable share; that exception is over. A row at 0.03% of
    the grand total read `0%` here, and a slice that exists reported as nothing
    is the same lie `fmt_cost` refuses to tell about sub-cent spend. Saying what
    a row is worth is the tooltip's entire job.

    Note the floor is not only about rounding DOWN: `0.7%` read `1%` here too,
    overstating a slice that never reached one percent. `fmt_share` answers
    `<1%` to both."""
    return _fmt.fmt_share(part, whole)


# --- fragments: tooltips, tiles, sparklines ------------------------------------
def _tip(header, rows):
    """Hover text, written ONCE and used twice: as the `title` the browser shows
    natively when JavaScript is off, and as the payload the styled tooltip
    re-renders. One encoding means the two can never drift apart.

    Newline separates lines, tab separates a row's label from its value — both
    survive a native tooltip, so the fallback is readable rather than merely
    present."""
    body = "\n".join("%s\t%s" % (a, b) for a, b in rows if b is not None)
    return e(("%s\n%s" % (header, body)) if body else header)


def _tile(label, value, sub, delta=""):
    return ('<div class="tile"><div class="k">%s</div>'
            '<div class="v">%s%s</div><div class="s">%s</div></div>'
            % (e(label), e(value), delta, sub))


SPARK_COLS = 60
# A 140px sparkline cannot draw a year: at half a pixel per column the shape stops
# being a shape and the markup grows without adding information. Past this many
# days the columns are binned into equal-width buckets and the caption SAYS the bin
# size, so the reader knows the resolution they are looking at.


def _bin_days(days, limit=SPARK_COLS):
    """days -> (labels, index groups, bin size). Identity below the limit."""
    if len(days) <= limit:
        return list(days), [[i] for i in range(len(days))], 1
    size = -(-len(days) // limit)
    groups = [list(range(i, min(i + size, len(days))))
              for i in range(0, len(days), size)]
    labels = [days[g[0]] if len(g) == 1
              else "%s to %s" % (days[g[0]], days[g[-1]]) for g in groups]
    return labels, groups, size


def _spark(values, peak, colour, days=None, label="", width=140, height=30):
    """A tiny column sparkline for the small-multiples grid, in the series' own
    colour — the row already names the model, so an anonymous grey spark would
    throw away the identity the swatch beside it establishes.

    A sparkline is deliberately unlabelled: it shows shape, not values. Hover
    supplies the day and the count for the one column being pointed at, which is
    the only way to read a value off a 140px chart with no axis.

    The tooltip hangs off a full-height transparent rect, not off the visible bar:
    a quiet day draws 2px tall, and a 2px hit target is one nobody can hit. Zero
    days get neither — there is nothing to report, and titling them all would grow
    the section by hundreds of marks to say "0"."""
    if not values:
        return ""
    if not peak:
        # No `or 1`. `peak` is the SHARED peak of the whole small-multiples grid,
        # so a peak of zero says every panel in it recorded nothing — and against
        # a fabricated peak of 1 every column is still zero and skipped, leaving
        # an empty <svg> frame drawn to a scale nobody measured. The same answer
        # the daily trend gives (`_usage_trend`) and the same answer this section
        # gives a zero-token ledger: no shape to plot, so nothing is plotted.
        #
        # Only a whole EMPTY GRID takes this exit. A panel that is all zeros
        # against a real shared peak keeps its frame, because on a shared axis
        # that empty frame is the finding — this author ran nothing on this model
        # while the panel beside it ran plenty.
        return ""
    n = len(values)
    slot = float(width) / n
    bw = max(1.0, slot - 1.0)
    days = days or []
    bars, hits = [], []
    for i, v in enumerate(values):
        if not v:
            # A zero column draws a zero-height rect: markup that renders nothing.
            # On a shared axis most panels are mostly zeros, so emitting them cost
            # 74 KB of invisible <rect> in a 300-phase report.
            continue
        # A hairline, not a bar: on a shared scale with a 200x range most columns
        # land below a pixel, and a 1.5px floor made twenty different days look
        # identical — presence reading as magnitude. 1px is visibly "some, below
        # this chart's resolution", and the caption says so.
        bh = max(1.0, height * v / peak)
        bars.append('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" rx="1">'
                    "</rect>" % (i * slot, height - bh, bw, bh))
        if i < len(days):
            hits.append(
                '<rect class="hit" x="%.2f" y="0" width="%.2f" height="%d">'
                "<title>%s</title></rect>"
                % (i * slot, max(bw, 3.0), height,
                   _tip(days[i], [(label, _fmt_tokens(v, 2))] if label else [])))
    return ('<svg class="spark" viewBox="0 0 %d %d" preserveAspectRatio="none" '
            'aria-hidden="true" style="--sc:%s">%s%s</svg>'
            % (width, height, colour, "".join(bars), "".join(hits)))

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
        print("_usage_viz.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__usage_viz.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
