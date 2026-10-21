#!/usr/bin/env python3
"""
The cases for `tools/bench-report.py` - the report benchmark that left
`render-report.py --bench`, and the fixture it times.

A bench that silently measures the wrong thing is worse than none. These run at the
smallest scale the fixture supports; the numbers are not asserted (a threshold on a
shared machine is the flaky gate this feature refuses to be), only that each timed
phase does the work its label claims, over the FIXTURE's ledger rather than this
repository's live one. `bn1` is the one case about the removal itself: the shipped
renderer answers `--bench` as an unknown argument now.

`M` is the benchmark, loaded by path because it lives under `tools/`, and `_R` is the
renderer it times, loaded by basename.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import io
import os
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _manifest_io                                # noqa: E402  (as the benchmark reads a plan)
import _usage_bench                                # noqa: E402  (the shared best-of-N timer)

M = _loader.load(os.path.join(_harness.TOOLS_DIR, "bench-report.py"),
                 modname="bench_report_under_test")
_R = _loader.load_script("render-report.py", modname="render_report_for_bench")


# --- cases --------------------------------------------------------------------
def _cases(check):
    tmp = _harness.fixture_root("bench-report-selftest-")
    # --- bn: the bench harness measures what it claims -------------------------
    # A bench that silently measures the wrong thing is worse than none. These run
    # at the smallest scale the fixture supports; the numbers are not asserted (a
    # threshold on a shared machine is the flaky gate this feature refuses to be),
    # only that each timed phase does the work its label claims, over the FIXTURE's
    # ledger rather than this repository's live one.
    check("bn1 the shipped renderer no longer carries a benchmark: `--bench` is an "
          "ordinary argument to it (a manifest path that does not resolve, so a "
          "usage error), and the module has neither the mode switch nor the "
          "benchmark it used to dispatch to",
          _R.main(["--bench"]) == 2
          and not hasattr(_R, "_bench") and not hasattr(_R, "_mode")
          and not hasattr(_R, "_bench_fixture"))
    _bd = os.path.join(tmp, "bench")
    os.makedirs(_bd, exist_ok=True)
    _fx = M._bench_fixture(_bd, 3, 2)
    # Recounted through the REAL ledger reader, not by running this file's own
    # counting loop a second time: a count re-derived the same way would agree
    # with itself however wrong it was, and every per-row figure the bench prints
    # divides by this number.
    _fx_rows = _loader.load_script("usage_ledger.py", modname="usage_ledger",
                                    cache=False).read_ledger(_fx["ledgerDir"])
    check("bn2 the fixture really is the size the bench prints beside every "
          "figure - the task count is the plan's own, and the row count agrees "
          "with what the ledger reader actually finds in the fixture",
          _fx["tasks"] == 6 and _fx["rows"] > 0
          and _fx["rows"] == len(_fx_rows),
          "%r vs reader %d" % (_fx, len(_fx_rows)))
    _bman = _manifest_io.load_manifest(_fx["manifestPath"])
    _bphases = M._bench_phases(_bman, _fx["manifestPath"], _bd)
    check("bn3 every phase named in the printed table has a denominator, and "
          "the table names no phase that is not timed - a phase added later "
          "without one fails HERE rather than printing a bare millisecond",
          set(M._BENCH_PER) == set(lbl for lbl, _ in _bphases)
          and set(M._BENCH_PER.values()) == {"row", "task"})
    # Run the phases IN ORDER and keep what each returned: a thunk that quietly
    # did nothing would still be timed, and would print a very fast number.
    _art = {}
    for _lbl, _thunk in _bphases:
        _art[_lbl] = _thunk()
    check("bn4 each timed phase produces that phase's own artifact - validate a "
          "findings list, rollup a summary, the ledger pass a totals dict, and "
          "the two writers a whole document each",
          isinstance(_art["validate"], list)
          and "phases" in _art["rollup"] and "tasks" in _art["rollup"]
          and isinstance(_art["usage load"], dict)
          and "totals" in _art["usage load"]
          and _art["html"].lstrip().lower().startswith("<!doctype html>")
          and "## " in _art["markdown"],
          repr(sorted(_art)))
    # THE trap this bench exists next to: CLAUDE_PROJECT_DIR is set to the real
    # repository in every Claude Code session, and load_usage falls back to it.
    # Pointed at the repo, the ledger pass would time a live, growing ledger and
    # print a number that looks entirely reasonable. Set it to a decoy and prove
    # the fixture's own ledger is still what got read.
    _decoy, _prev_pd = os.path.join(tmp, "decoy"), os.environ.get("CLAUDE_PROJECT_DIR")
    os.makedirs(_decoy, exist_ok=True)
    os.environ["CLAUDE_PROJECT_DIR"] = _decoy
    try:
        _scoped = dict((lbl, fn) for lbl, fn in
                       M._bench_phases(_bman, _fx["manifestPath"], _bd))["usage load"]()
    finally:
        if _prev_pd is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = _prev_pd
    check("bn5 the ledger pass reads the FIXTURE's ledger even when "
          "CLAUDE_PROJECT_DIR points elsewhere - project_dir is passed "
          "explicitly, so an ambient env var cannot redirect the bench onto "
          "this repository's own live ledger",
          isinstance(_scoped, dict)
          and _scoped["totals"]["tokens"]
          == _art["usage load"]["totals"]["tokens"]
          and _scoped["totals"]["tokens"] > 0,
          repr(_scoped is None))
    # DRY, pinned rather than asserted in a comment: best-of-N has one definition,
    # in _usage_bench. Two copies would let one take the mean.
    #
    # `not hasattr(M, "_time_best")`, not `"_time_best" not in globals()`. The
    # claim is about RENDER-REPORT holding no second copy, and inline that was
    # what `globals()` meant. From here `globals()` is this test file, which was
    # never going to define `_time_best` under any circumstances - so the clause
    # would be true forever and the half of the case that is actually load
    # bearing would have quietly stopped asking anything.
    _ua = _usage_bench
    check("bn6 the report bench times with the ledger bench's harness rather "
          "than a second copy - one definition of best-of-N, in one place",
          callable(_ua._time_best) and not hasattr(M, "_time_best"))
    # Exit code and the printed contract, at the smallest scale. Counted, not
    # merely found: one timing line per phase plus the sum line.

    def _tmp_bench_dirs():
        return set(d for d in os.listdir(tempfile.gettempdir())
                   if d.startswith("report-bench-"))

    _before_dirs = _tmp_bench_dirs()
    _bbuf, _bout = io.StringIO(), sys.stdout
    sys.stdout = _bbuf
    try:
        _brc = M._bench(scales=((3, 2),), repeats=2)
    finally:
        sys.stdout = _bout
    _btext = _bbuf.getvalue()
    _leftover = _tmp_bench_dirs() - _before_dirs
    _blines = [ln for ln in _btext.splitlines() if " ms " in ln]
    check("bn7 --bench exits 0 and prints, per phase, the size, a wall time in "
          "ms and the derived per-row or per-task figure - the three things a "
          "human needs in order to act on it",
          _brc == 0 and "best of 2 runs" in _btext and "MINIMUM" in _btext
          and "3 phases x 2 tasks" in _btext and "ledger rows" in _btext
          and len(_blines) == len(M._BENCH_PER) + 1
          and all(any(lbl in ln for ln in _blines) for lbl in M._BENCH_PER)
          and all(("us/row" in ln or "us/task" in ln) for ln in _blines),
          repr(_btext[:400]))
    check("bn8 ...and it leaves no fixture behind - measured as the temp dirs "
          "that appeared ACROSS the run, so a stale one from some other "
          "process cannot fail this and a real leak cannot hide behind one",
          _leftover == set(), repr(sorted(_leftover)))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_bench_report.py --selftest\n")
    raise SystemExit(2)
