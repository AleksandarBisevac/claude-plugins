#!/usr/bin/env python3
"""
The cases for `_usage_bench.py` - the timer over the analytics passes, and the
fixture it times them on.

Written at U3.2, when `_usage_analytics.py` was cut on its own section markers.
These nine cases were the `bn` group of `test__usage_analytics.py`. `_bench`,
`_bench_cases`, `_bench_rows`, `_bench_manifest`, `_time_best` and the `_BENCH_*`
constants are production code - a benchmark somebody runs, not a test - so only
the CASES ABOUT them are here, and
`python3 plugins/audit/scripts/usage/_usage_bench.py --bench` still runs the
benchmark itself.

TWO CASES ARE `globals()` REBINDS THAT FAIL IN OPPOSITE DIRECTIONS, and they are
why this file cannot be read as ordinary. `bn4` swaps each benchmarked function
for a counting spy; spelled `globals()[_label] = _spy` from here it would patch a
name nothing calls, every spy would record 0 hits and the case would name every
thunk as mislabelled. `bn5` finds the public passes the subject's own layer
DEFINES; spelled against this file's namespace it would find nothing, `_own_public
- _timed` would be `set()`, and the case would go red claiming the deliberate
omission had been fixed. They are `setattr(M, ...)` / `getattr(M, ...)` and
`vars(...)` / `__name__`, named on the modules that own them.

WHAT THE SPLIT CHANGED IN `bn5`, AND WHY IT IS STRONGER RATHER THAN LOOSER. The
passes are no longer defined in the module that times them: they live in
`_usage_spend`, `_usage_economics`, `_usage_routing` and `_usage_coverage`, and
`_usage_bench` imports them. So the filter runs over those FOUR modules and the
union is what must be timed - a pass added to any of them and left unmeasured
fails here. `task_index` left the answer at the same time and for the same
reason: it moved down into `_usage_core` with the split, so it is no longer one
of the passes this scan covers. It still runs inside four of the timed cases.

`sys` is imported here rather than prefixed, and that is load-bearing for `bn9`:
the case redirects `sys.stdout` to a StringIO to read what `--bench` prints. `M`'s
`print` resolves `sys.stdout` on the one shared `sys` module object, so the
redirection is seen; a per-module copy would capture nothing and `_out` would be
empty.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _usage_coverage                             # noqa: E402  (a pass source, for bn5)
import _usage_economics                            # noqa: E402  (a pass source, for bn5)
import _usage_routing                              # noqa: E402  (a pass source, for bn5)
import _usage_spend                                # noqa: E402  (a pass source, for bn5)
import _usage_bench as M                           # noqa: E402

# The four modules whose public passes this bench is responsible for timing. Named
# once here rather than three times below, and read through `vars()` rather than
# listed by hand - a pass added to any of them shows up without an edit.
_PASS_MODULES = (_usage_spend, _usage_economics, _usage_routing, _usage_coverage)


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- bn: the bench harness measures what it claims ----------------
    # A bench that silently measures the wrong thing is worse than none, so each
    # of these pins one way this one could be wrong while still printing
    # plausible numbers.
    check("bn1 the fixture is EXACTLY the size the bench prints beside every "
          "figure - a row count that drifted would make every per-row number "
          "under it wrong, and nothing else would notice",
          [len(M._bench_rows(k)) for k in (0, 1, 37, 1000)] == [0, 1, 37, 1000])
    check("bn2 ...and it is deterministic AND prefix-stable, which is what "
          "makes the 1k / 10k / 50k rows comparable to each other rather than "
          "three unrelated samples",
          M._bench_rows(200) == M._bench_rows(200)
          and M._bench_rows(200)[:100] == M._bench_rows(100))
    _bm = M._bench_manifest()
    _br = M._bench_rows(M._BENCH_SIZES[0])
    _b_bands, _b_unit = M.cost_bands(_bm, _br), M.unit_economics(_bm, _br)
    check("bn3 the fixture CLEARS every honesty gate in the passes it times, so "
          "each timed case does its real work - a suppressed cost_bands or a "
          "compare() with no prior window returns in microseconds, and the "
          "bench would print that guard clause as the cost of the function",
          _b_bands["sufficient"]
          and _b_bands["sample"] >= _usage_economics.COST_BAND_PARAMS["gate"]
          and _b_unit["projection"] is not None
          and M.coverage(_br)["total"] > 0
          and 0 < M.coverage(_br)["attributedPct"] < 100
          and len(M.monthly_activity(_bm, _br)["months"]) == M._BENCH_MONTHS
          and M.phase_budgets(_bm, _br)["budgeted"] > 0
          and len(M.routing(_bm, _br)["risks"]) == 3
          and M.retry_cost(_bm, _br)["retriedTasks"] > 0
          and M.compare(_br, M._BENCH_SINCE, M._BENCH_UNTIL)["prior"] is not None,
          "%r" % (_b_bands,))
    # The label -> function pairing, proven by SWAPPING the named global rather
    # than by reading the source. Both directions fail here: a thunk that
    # stopped calling its function (0 hits) and one that calls it twice or calls
    # its neighbour as well (2 hits) are both reported.
    #
    # `setattr(M, ...)`, not `globals()[...] = `. The thunks are lambdas defined
    # in `_usage_bench`, so the name each one resolves is that module's global -
    # which is still true after the split, because `_usage_bench` imports the
    # passes rather than reaching them through a module object.
    _mislabelled = []
    for _label, _thunk in M._bench_cases(_bm, _br):
        _real, _hits = getattr(M, _label), []

        def _spy(*a, **kw):
            _hits.append(1)
            return _real(*a, **kw)

        setattr(M, _label, _spy)
        try:
            _thunk()
        finally:
            setattr(M, _label, _real)
        if len(_hits) != 1:
            _mislabelled.append((_label, len(_hits)))
    check("bn4 every timed thunk calls the function its LABEL names, exactly "
          "once - a bench that prints one function's cost under another's name "
          "is worse than no bench, because it is believed",
          _mislabelled == [], repr(_mislabelled))
    _timed = set(lbl for lbl, _ in M._bench_cases(_bm, _br))
    # `vars(mod)` / `mod.__name__`, over the FOUR modules that define the passes
    # rather than over the one that times them - see the module docstring. The
    # `__module__` filter is what keeps a name `_usage_bench` merely imported out
    # of the answer, so it has to compare against each SUBJECT's `__name__`.
    _own_public = set(n for mod in _PASS_MODULES for n, v in vars(mod).items()
                      if not n.startswith("_") and callable(v)
                      and getattr(v, "__module__", None) == mod.__name__)
    check("bn5 every rows->dict pass DEFINED by the four analytics modules is "
          "timed; the only one that is not is named on purpose (band_of is a "
          "dict lookup) - so a pass added later and left unmeasured fails HERE "
          "rather than quietly missing from the table",
          _own_public - _timed == {"band_of"},
          repr(sorted(_own_public - _timed)))
    # The filter above narrows, and a filter that narrowed to nothing would make
    # bn5 pass by describing an empty room. Counted, not assumed.
    check("bn5b ...and it found the passes at all: 11 public passes across the "
          "four modules, 10 of them timed",
          len(_own_public) == 11 and len(_own_public & _timed) == 10,
          "%d found, %d timed" % (len(_own_public), len(_own_public & _timed)))
    # A scripted clock, not sleeps: elapsed 4.0, 1.0, 3.0 over three runs. The
    # three candidate answers are far apart on purpose - minimum 1.0, mean 2.67,
    # last 3.0 - so the fixture can tell a correct harness from either wrong one.
    _ticks = [0.0, 4.0, 4.0, 5.0, 5.0, 8.0]
    _read, _calls = [], []

    def _scripted_clock():
        _read.append(1)
        return _ticks[len(_read) - 1]

    def _counted():
        _calls.append(1)
        return "ok"

    _sec, _res = M._time_best(_counted, 3, clock=_scripted_clock)
    check("bn6 the timed section runs the callable exactly `repeats` times and "
          "hands back its result",
          len(_calls) == 3 and _res == "ok", "%d call(s)" % len(_calls))
    check("bn7 ...and reports the MINIMUM of those runs - never the mean "
          "(2.667) and never the last (3.0)", _sec == 1.0, repr(_sec))
    check("bn8 --selftest wins over --bench whichever order they arrive in, so "
          "CI's per-file sweep can never turn into a benchmark run; a bare "
          "invocation is still a usage error",
          M._mode(["--selftest"]) == "selftest" and M._mode(["--bench"]) == "bench"
          and M._mode(["--selftest", "--bench"]) == "selftest"
          and M._mode(["--bench", "--selftest"]) == "selftest"
          and M._mode([]) == "usage" and M._mode(["--nope"]) == "usage")
    # The printed contract, at a size the suite can afford. Counted, not merely
    # found: one timing line per case plus the two derived lines, so a figure
    # that silently stopped being printed fails instead of going unnoticed.
    import io
    _buf, _stdout = io.StringIO(), sys.stdout
    sys.stdout = _buf
    try:
        _rc = M._bench(sizes=(200,), repeats=2)
    finally:
        sys.stdout = _stdout
    _out = _buf.getvalue()
    _timing_lines = [ln for ln in _out.splitlines() if " ms " in ln]
    check("bn9 --bench exits 0 and prints, for every case, the size, a wall "
          "time in ms and the derived per-row figure - the three things a "
          "human needs in order to act on it",
          _rc == 0 and "rows=200" in _out and "best of 2 runs" in _out
          and "MINIMUM" in _out
          # ...and the header names the module that PRINTED it. Read off
          # `__name__`, not compared to a literal: the string it replaced said
          # `_usage_analytics` and survived that file's deletion, because
          # nothing had ever asked what it named.
          and _out.splitlines()[0].startswith(M.__name__ + " --bench")
          and len(_timing_lines) == len(M._bench_cases(_bm, _br)) + 2
          and all(any(lbl in ln for ln in _timing_lines)
                  for lbl, _ in M._bench_cases(_bm, _br))
          and all((" ms " in ln and " us" in ln) for ln in _timing_lines),
          repr(_out[:400]))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__usage_bench.py --selftest\n")
    raise SystemExit(2)
