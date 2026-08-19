#!/usr/bin/env python3
"""
The audit report's Markdown twin — the same plan as a data table.

Moved out of render-report.py (P13.3) alongside `_report_page.py`, and it could
not stay behind when `render_html` left: the HTML report embeds this output
base64-encoded as its "Download .md" payload, so `_report_page` CALLS this
module. That single edge is the whole reason the split is two files rather than
one — `_report_page -> _report_md -> _report_html/_usage_markdown`, one way, no
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

Imports go one way only: `_report_html` (fragment helpers) and `_usage_markdown`
(the Usage block's own twin) are below this file; it must never import
`_report_page` or render-report.

It reads `_usage_md` from `_usage_markdown` (layer 4) rather than through
`_report_usage`, and that is a layer fact rather than a preference: when the
Usage section was cut into five, its assembly moved to layer 5 — beside this
file, not below it — so reaching the twin through the assembly would be a
sideways edge. Going to the twin directly is both legal and the shorter
sentence: the report's Markdown renderer calls the Usage section's Markdown
renderer.

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test__report_md.py`, byte-identical labels and all - see
`plugins/audit/tests/_harness.py`.
"""
import os
import sys
import time

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

import _report_html   # noqa: E402  (the shared lookups: dates, task index, bug view)
import _usage_markdown  # noqa: E402  (the Usage section's own Markdown twin)


# --- shared lookups -------------------------------------------------------------
# Aliased rather than reached through the module at every call site, the same
# convention _usage_viz uses for `e`: these names are what the code moved from
# render-report.py already spelled.
_short_date = _report_html._short_date
_tasks_by_id = _report_html._tasks_by_id
_bug_view = _report_html._bug_view
_usage_md = _usage_markdown._usage_md


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


# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv:
        # Answers rather than exits silently: `--selftest` is what every other
        # file here still accepts, so nothing would tell a reader whether this
        # one ran nothing or has nothing. It deliberately does NOT print the
        # suite contract - that literal is how `_output.selftest_coverage()`
        # tells an inline suite from a migrated one.
        print("_report_md.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__report_md.py - run that file instead.")
    sys.exit(0)
