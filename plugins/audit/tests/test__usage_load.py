#!/usr/bin/env python3
"""
The cases for `_usage_load.py` — the Usage section's only read.

Everything else in the section takes the dict this builds and returns a string;
this is the one piece that touches a file, so the cases here are about what it
does when the file is not what it hoped for. `load_usage` returns **None** on
every one of those paths, and None is the answer that makes the section render
as nothing at all rather than as an empty frame.

THE COMPARISON WINDOW IS ANCHORED TO THE LEDGER'S OWN LAST DAY. That is what
makes a committed example report byte-stable across re-renders, and it is what
keeps `_pricing_stale` from turning a shipped fixture into a warning as the wall
clock moves. Both are pinned, and the staleness case is pinned in **both**
directions — a detector that always fires is as useless as one that never does.

`_hourly` regroups rows the ledger already keys by hour bucket. A day appears
only when it carries at least one parseable row; the client treats a missing day
as 24 zeros, so an absent key and a zero vector must stay distinguishable here.

Fixtures are built in a `tempfile.mkdtemp()` and deleted in `finally` — nothing
here is committed.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import io
import json
import os
import shutil
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _usage_load as M                            # noqa: E402
import _loader                                     # noqa: E402
import _report_html                                # noqa: E402
import _report_usage as _RU                        # noqa: E402

_UL = _loader.load_script("usage_ledger.py", modname="usage_ledger_for_cases")


def _write_project(root, rows, meta_usage=None):
    """A project with a manifest and a one-file ledger."""
    mdir = os.path.join(root, "docs", "audit")
    ldir = os.path.join(root, ".claude", "usage")
    os.makedirs(mdir)
    os.makedirs(ldir)
    meta = {"version": 2, "repo": "x"}
    if meta_usage is not None:
        meta["usage"] = meta_usage
    manifest = {"meta": meta,
                "phases": [{"id": "P0", "title": "P", "status": "pending",
                            "tasks": [{"id": "P0.1", "title": "T",
                                       "status": "done"}]}]}
    mpath = os.path.join(mdir, "audit-plan.json")
    with io.open(mpath, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(manifest))
    with io.open(os.path.join(ldir, "2026-07.jsonl"), "w", encoding="utf-8",
                 newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return manifest, mpath


def _row(ts, tokens=100, **kw):
    r = {"ts": ts, "model": "opus", "author": "a@x.example",
         "phaseId": "P0", "taskId": "P0.1", "msgs": 1,
         "in": tokens, "out": 0, "costUSD": 0.01}
    r.update(kw)
    return r


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- _hourly, the regrouping ---
    rows = [{"ts": "2026-07-01T03", "in": 5, "out": 0},
            {"ts": "2026-07-01T03", "in": 7, "out": 0},
            {"ts": "2026-07-02T00", "in": 1, "out": 0},
            {"ts": "junk", "in": 99, "out": 0}]
    got = M._hourly(rows, _UL)
    check("ul1 rows are regrouped into a 24-slot vector per calendar date, "
          "and two rows in one hour ADD rather than replace",
          got["2026-07-01"][3] == 12, got.get("2026-07-01"))
    check("ul2 ...and a day with no parseable row is an ABSENT key, not a "
          "vector of zeros - the client treats a missing day as 24 zeros, so "
          "the two must stay distinguishable",
          sorted(got) == ["2026-07-01", "2026-07-02"], sorted(got))
    check("ul3 ...and an unparseable bucket is skipped rather than counted "
          "into some default hour: 99 tokens appear nowhere",
          sum(sum(v) for v in got.values()) == 13,
          sum(sum(v) for v in got.values()))
    check("ul4 every emitted vector is 24 long",
          all(len(v) == 24 for v in got.values()))

    # --- _pricing_stale, both directions ---
    check("ul5 a price table more than max_days older than the ledger's "
          "NEWEST day is stale",
          M._pricing_stale("2026-01-01", "2026-07-01") is True)
    check("ul6 ...and one inside the window is not - the case that fails if "
          "the comparison is inverted or the threshold collapses to zero",
          M._pricing_stale("2026-06-25", "2026-07-01") is False)
    check("ul7 ...and it is compared against the LEDGER's last day, never the "
          "wall clock, so a committed example does not rot into a warning: "
          "the same as_of is fresh against a later `until` and stale against "
          "an earlier one",
          M._pricing_stale("2026-01-01", "2026-01-02") is False
          and M._pricing_stale("2026-01-01", "2026-07-01") is True)
    check("ul8 ...and an undated or unparseable table is NOT reported stale: "
          "'no date' is a different statement from 'an old date', and the "
          "context line is what says the first one",
          M._pricing_stale(None, "2026-07-01") is False
          and M._pricing_stale("nope", "2026-07-01") is False)

    # --- load_usage, against real projects ---
    root = tempfile.mkdtemp(prefix="audit-usage-load-")
    try:
        manifest, mpath = _write_project(
            os.path.join(root, "p1"),
            [_row("2026-07-01T03"), _row("2026-07-02T04", tokens=200)])
        u = M.load_usage(manifest, mpath, os.path.join(root, "p1"))
        check("ul9 a project with a ledger yields the payload the section "
              "plots, with the totals the ledger recorded",
              isinstance(u, dict) and u["totals"]["tokens"] == 300,
              (u or {}).get("totals"))
        check("ul10 ...and the comparison window is anchored to the ledger's "
              "own last day, which is what makes a committed example report "
              "byte-stable across re-renders",
              u["compareWindow"]["until"] == "2026-07-02",
              u["compareWindow"])
        check("ul11 ...and `counts` orients the reader in the data rather "
              "than measuring it: days, people, models, the span",
              u["counts"]["days"] == 2 and u["counts"]["from"] == "2026-07-01"
              and u["counts"]["to"] == "2026-07-02", u["counts"])
        check("ul12 ...and the per-date hour vectors ride along, because the "
              "7x24 heatmap aggregates the calendar AWAY and the report has "
              "no server to ask for it back",
              sorted(u["hourly"]) == ["2026-07-01", "2026-07-02"],
              sorted(u["hourly"]))
        check("ul13 ...and taskTitles comes through `_report_html._tasks_by_id` "
              "- the manifest index, aliased rather than re-walked here",
              u["taskTitles"] == {"P0.1": "T"}, u["taskTitles"])

        empty = os.path.join(root, "p2")
        _m2, mp2 = _write_project(empty, [])
        check("ul14 a ledger with no rows returns None, so the section "
              "renders as nothing rather than as an empty frame",
              M.load_usage(_m2, mp2, empty) is None)

        bare = os.path.join(root, "p3")
        os.makedirs(os.path.join(bare, "docs", "audit"))
        mp3 = os.path.join(bare, "docs", "audit", "audit-plan.json")
        with io.open(mp3, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({"meta": {"version": 2}, "phases": []}))
        check("ul15 ...and a project with NO ledger directory at all returns "
              "None too - the same answer, which is what lets the caller have "
              "one branch instead of two", M.load_usage({}, mp3, bare) is None)

        p4 = os.path.join(root, "p4")
        m4, mp4 = _write_project(p4, [_row("2026-07-01T03")],
                                 meta_usage={"showCost": False})
        u4 = M.load_usage(m4, mp4, p4)
        check("ul16 `meta.usage.showCost` is carried into the payload, so "
              "every renderer reads one decision instead of re-reading the "
              "manifest", u4["showCost"] is False, u4["showCost"])
        # The second direction: showCost defaults to ON, so ul16 would pass on
        # a version that hard-coded False.
        u1 = M.load_usage(manifest, mpath, os.path.join(root, "p1"))
        check("ul17 ...and it defaults to True when the manifest says nothing "
              "- the case that fails if the flag is hard-coded either way",
              u1["showCost"] is True, u1["showCost"])
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # --- the aliases ---
    _names = ("load_usage", "_iso_day", "_pricing_stale", "_hourly")
    _forked = [n for n in _names if getattr(_RU, n) is not getattr(M, n)]
    check("ul18 every name `_report_usage` re-exports from here IS this "
          "module's function - render-report reads `load_usage` off that "
          "module and must reach this one: %r" % (_forked,), _forked == [])
    check("ul19 ...and the task index it reads is `_report_html`'s, not a "
          "second walk of the manifest",
          M._report_html._tasks_by_id is _report_html._tasks_by_id)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__usage_load.py --selftest\n")
    raise SystemExit(2)
