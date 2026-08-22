#!/usr/bin/env python3
"""
The cases for `_report_md.py`, moved out of it - an importable helper.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list.

A straight move: every case runs `M.render_md` over a literal manifest and reads
the string back. Nothing here touches a path, a file or another module's source.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _report_md as M                             # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    # The whole-document cases (what render-report's CLI writes, and that the
    # HTML carries this text base64-encoded) live with the entry point, which is
    # the only thing that can render a whole document. What is asserted here is
    # what this function decides on its own: the table's escaping, its vocabulary
    # and its order.
    manifest = {
        "meta": {"title": "twin", "repo": "r"},
        "phases": [
            {"id": "P2", "title": "second", "status": "in_progress",
             "tasks": [{"id": "P2.1", "title": "a|piped\ntitle",
                        "status": "in_progress"}]},
            {"id": "P1", "title": "first", "status": "done",
             "tasks": [{"id": "P1.1", "title": "t", "status": "done",
                        "commit": "abcdef1234567",
                        "completedAt": "2026-07-09T09:30:00Z"}]},
        ],
        "bugs": [{"id": "BUG-1", "title": "b|ug", "status": "open",
                  "severity": "high"}],
    }
    summary = {
        "valid": True, "findings": 0, "ready": ["P2.1"],
        "tasks": {"total": 2, "byStatus": {"done": 1, "in_progress": 1}},
        "bugs": {"total": 1, "open": 1, "openHighSeverity": 1},
        "phases": [
            {"id": "P2", "title": "second", "status": "in_progress",
             "done": 0, "total": 1},
            {"id": "P1", "title": "first", "status": "done",
             "done": 1, "total": 1},
        ],
    }
    md = M.render_md(manifest, summary)

    # A pipe in a title splits the row into two columns and every value after it
    # lands under the wrong header. Counted per line rather than asserted
    # present: the escape has to survive on the row it is ON, and a filter that
    # deleted the whole title would also satisfy "no bare pipe here".
    _row = [ln for ln in md.splitlines() if ln.startswith("| P2.1 ")][0]
    check("md1 a pipe inside a title is escaped, so one hostile title cannot "
          "shift every cell in its row into the wrong column",
          "a\\|piped" in _row and _row.count("\\|") == 1
          and _row.count("|") == 10)   # 9 separators + the one escaped pipe
    # A newline is the other way a single cell breaks a table: the row simply
    # ends early and the remainder becomes prose.
    check("md2 ...and a newline inside one becomes a space rather than ending "
          "the row",
          "a\\|piped title" in _row and "\n" not in _row)
    check("md3 the bugs table escapes the same way",
          "| BUG-1 | b\\|ug |" in md)
    # `cell(None)` has to print the dash rather than `str(None)`. It needs its
    # own plan: every optional column above arrives pre-defaulted (`t.get("model")
    # or "—"`), so `cell` is never handed a None on that fixture and a `str(v)`
    # mutation would pass — the fixture, not the assertion, is what separates the
    # two implementations. A task with no title at all is the shape that does.
    _blank = M.render_md(
        {"meta": {}, "bugs": [], "phases": [
            {"id": "P0", "title": None, "status": "pending",
             "tasks": [{"id": "P0.1", "title": None, "status": "pending"}]}]},
        {"valid": True, "findings": 0, "ready": [],
         "tasks": {"total": 1, "byStatus": {}},
         "bugs": {"total": 0, "open": 0, "openHighSeverity": 0},
         "phases": [{"id": "P0", "title": None, "status": "pending",
                     "done": 0, "total": 1}]})
    # The second half is the mutation in the other direction: a cell function
    # that dashed EVERYTHING satisfies the first half on its own, so the row
    # that records a commit and a completion date is asserted to still carry
    # them.
    _done_row = [ln for ln in md.splitlines() if ln.startswith("| P1.1 ")][0]
    check("md4 a value the manifest does not record prints an em dash, never "
          "the word None - and a value it DOES record still prints",
          "None" not in _blank and "| P0.1 | — | pending |" in _blank
          and _row.count("—") == 5
          and "| abcdef123 |" in _done_row and "| 2026-07-09 |" in _done_row
          and _done_row.count("—") == 3)
    # The HTML groups its phases into segments (active before archived); this
    # table is read by machines and by diff tools, so it keeps MANIFEST order —
    # P2 before P1 — and reordering it would change every diff against an
    # earlier render for a presentational reason.
    check("md5 phases keep the manifest's own order, not the HTML's segments",
          md.index("## P2 —") < md.index("## P1 —"))
    check("md6 ...and the manifest's own vocabulary: the machine spelling, "
          "because GitHub and `diff` read this, not a person scanning a page",
          "| in_progress |" in md and "In progress" not in md)
    # The Usage block is _report_usage's twin, appended here. Both directions:
    # a plan with no ledger must not grow an empty heading, which is the shape
    # the "always render the section" mutation takes.
    check("md7 no ledger, no Usage block at all", "## Usage" not in md)
    _u = {"totals": {"tokens": 1000, "in": 10, "out": 10, "cacheW5m": 0,
                     "cacheW1h": 0, "cacheR": 980, "msgs": 2, "costUSD": 0.5,
                     "sessions": 1, "authors": 1, "models": 1, "tasks": 1,
                     "phases": 1, "cacheHitPct": 98.0},
          "byPhase": {"P1": {"tokens": 1000, "costUSD": 0.5, "msgs": 2}},
          "byModel": {"claude-opus-5": {"tokens": 1000, "costUSD": 0.5,
                                        "msgs": 2}},
          "byAuthor": {"a@x.io": {"tokens": 1000, "costUSD": 0.5, "msgs": 2}},
          "byAgent": {}, "phaseTitles": {"P1": "first"},
          "phaseModel": {"P1": {"claude-opus-5": 1000}},
          "daily": {"2026-08-01": 1000}, "heatmap": [[0] * 24 for _ in range(7)],
          "showCost": True, "pricingAsOf": "2026-08-06",
          "counts": {"phases": 1, "people": 1, "models": 1, "sessions": 1,
                     "days": 1, "from": "2026-08-01", "to": "2026-08-01"}}
    check("md8 ...and a ledger appends it once, not twice",
          M.render_md(manifest, summary, _u).count("## Usage") == 1)

    # --- the pin that could not be honoured -----------------------------------
    # ONE `summary` key reaches four surfaces; this is the Markdown twin's leg.
    _pnote = dict(summary)
    _pnote["priorityNote"] = "P5 holds priority 1 but is waiting on P2"
    check("md9 SECOND-DIRECTION CASE: with no note the Ready section is exactly "
          "what it always was. It reads vacuous and is the only case that fails "
          "if the note becomes unconditional",
          "> " not in md.split("## Ready now")[1], repr(md.split("## Ready now")[1]))
    check("md10 the note prints under Ready now, once, as a quote",
          M.render_md(manifest, _pnote).count(
              "> P5 holds priority 1 but is waiting on P2") == 1,
          repr(M.render_md(manifest, _pnote).split("## Ready now")[1][:120]))
    _empty = dict(_pnote)
    _empty["ready"] = []
    check("md11 ...and it prints with an EMPTY ready list too, under a heading "
          "of its own: 'nothing is ready' and 'the phase you pinned is blocked' "
          "are different news, and folding the second into the silence of the "
          "first is the failure the note exists to stop",
          "## Ready now" in M.render_md(manifest, _empty)
          and "> P5 holds priority 1" in M.render_md(manifest, _empty),
          repr(M.render_md(manifest, _empty)[-300:]))
    _quiet = dict(summary)
    _quiet["ready"] = []
    check("md12 SECOND-DIRECTION CASE: an empty ready list with NO note draws no "
          "Ready section at all, which is what md11 would otherwise be reading",
          "## Ready now" not in M.render_md(manifest, _quiet))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__report_md.py --selftest\n")
    raise SystemExit(2)
