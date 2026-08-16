#!/usr/bin/env python3
"""
The audit report's Markdown twin — the same plan as a data table.

Moved out of render-report.py (P13.3) alongside `_report_page.py`, and it could
not stay behind when `render_html` left: the HTML report embeds this output
base64-encoded as its "Download .md" payload, so `_report_page` CALLS this
module. That single edge is the whole reason the split is two files rather than
one — `_report_page -> _report_md -> _report_html/_report_usage`, one way, no
cycle.

Two audiences, one difference. `render_html` is the hardened artifact: every
manifest string is escaped, and it is what to hand a reader when the source is
untrusted and no sanitising renderer sits in front. This one escapes only the
MARKDOWN metacharacters that would break the table (pipes, newlines) and passes
raw HTML through to whatever renders it — which is why its table also keeps the
manifest's own machine vocabulary (`in_progress`, not "In progress") and the
manifest's own phase ORDER. It is read by GitHub and by diff tools, and
reordering rows or prettying values for a human would change every diff against
an earlier render for a purely presentational reason.

Imports go one way only: `_report_html` (fragment helpers) and `_report_usage`
(the Usage block's own twin) are below this file; it must never import
`_report_page` or render-report.
"""
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))

# Run as a command, `sys.path[0]` is already this directory; imported from
# elsewhere it might not be.
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _report_html   # noqa: E402  (the shared lookups: dates, task index, bug view)
import _report_usage  # noqa: E402  (the Usage section's own Markdown twin)


# --- shared lookups -------------------------------------------------------------
# Aliased rather than reached through the module at every call site, the same
# convention _report_usage uses for `e`: these names are what the code moved from
# render-report.py already spelled.
_short_date = _report_html._short_date
_tasks_by_id = _report_html._tasks_by_id
_bug_view = _report_html._bug_view
_usage_md = _report_usage._usage_md


# --- render_md ------------------------------------------------------------------
def render_md(manifest, summary, usage=None):
    """Markdown twin of render_html. Only Markdown metacharacters (pipes,
    newlines) are escaped here — raw HTML inside manifest strings is passed
    through and relies on the Markdown renderer (e.g. GitHub) to sanitise it.
    render_html is the hardened, self-contained output; prefer it when the
    source is untrusted and no sanitising renderer sits in front."""
    meta = manifest.get("meta") or {}
    now = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())

    def cell(v):
        return str(v if v is not None else "—").replace("|", "\\|").replace(
            "\n", " ")

    out = ["# %s" % cell(meta.get("title") or "Audit report"), "",
           "repo: %s · generated %s" % (cell(meta.get("repo") or "?"), now), ""]
    rsum = meta.get("reportSummary")
    if isinstance(rsum, str) and rsum.strip():
        out += ["> " + cell(rsum.strip()), ""]
    if not summary["valid"]:
        out += ["**INVALID MANIFEST: %d validator finding(s).**" % summary["findings"], ""]
    tdone = sum(p["done"] for p in summary["phases"])
    phdone = sum(1 for p in summary["phases"] if p["status"] == "done")
    out += ["**Overall:** %d/%d tasks done · %d/%d phases signed off · %d open bug(s) · %d ready now"
            % (tdone, summary["tasks"]["total"], phdone, len(summary["phases"]),
               summary["bugs"]["open"], len(summary["ready"])), ""]
    for ph, psum in zip(
            [p for p in (manifest.get("phases") or []) if isinstance(p, dict)],
            summary["phases"]):
        out.append("## %s — %s (%s, %d/%d)"
                   % (cell(psum["id"]), cell(psum["title"]),
                      cell(psum["status"]), psum["done"], psum["total"]))
        if ph.get("desiredOutcome"):
            out.append("_%s_" % cell(ph["desiredOutcome"]))
        out += ["", "| id | title | status | model | risk | commit | done | ADO |",
                "|---|---|---|---|---|---|---|---|"]
        for t in ph.get("tasks") or []:
            if not isinstance(t, dict):
                continue
            ado = t.get("ado") if isinstance(t.get("ado"), dict) else None
            ado_txt = "#%s" % ado["id"] if ado and ado.get("id") is not None else "—"
            done_txt = _short_date(t.get("completedAt")) or (
                "started " + _short_date(t.get("startedAt")) if t.get("startedAt") else "—")
            out.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
                cell(t.get("id")), cell(t.get("title")), cell(t.get("status")),
                cell(t.get("model") or "—"), cell(t.get("risk") or "—"),
                cell((t.get("commit") or "—")[:9]), cell(done_txt), cell(ado_txt)))
        out.append("")
    bugs = [b for b in (manifest.get("bugs") or []) if isinstance(b, dict)]
    if bugs:
        task_by_id = _tasks_by_id(manifest)
        out += ["## Bugs", "",
                "| id | title | status | severity | task | fixedIn |",
                "|---|---|---|---|---|---|"]
        for b in bugs:
            bstatus, bfixed = _bug_view(b, task_by_id)
            out.append("| %s | %s | %s | %s | %s | %s |" % (
                cell(b.get("id")), cell(b.get("title")), cell(bstatus),
                cell(b.get("severity") or "—"), cell(b.get("taskId") or "—"),
                cell(bfixed[:9])))
        out.append("")
    if summary["ready"]:
        out += ["## Ready now", "", ", ".join(cell(r) for r in summary["ready"]), ""]
    usage_md = _usage_md(usage)
    if usage_md:
        out.append(usage_md)
    return "\n".join(out)


# --- selftest -------------------------------------------------------------------
def _selftest():
    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                           (" (%s)" % detail) if detail and not ok else ""))

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
    md = render_md(manifest, summary)

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
    _blank = render_md(
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
          render_md(manifest, summary, _u).count("## Usage") == 1)

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    sys.exit(_selftest() if "--selftest" in sys.argv else 0)
