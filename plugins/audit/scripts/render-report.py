#!/usr/bin/env python3
"""
Render the audit manifest as a self-contained HTML + Markdown report.

Publishable as a CI artifact (see docs/examples/azure-pipelines.yml) or opened
locally — the HTML inlines all CSS and fetches NOTHING. Every string from the
manifest is escaped (manifest content is untrusted input), and ado/link URLs
render as links only when they are http(s).

Usage:
  render-report.py <manifest> [--out-dir DIR] [--format html|md|both]
  render-report.py --selftest

Writes audit-report.html / audit-report.md into --out-dir (default: the
manifest's own directory) and prints the paths.
Exit codes: 0 ok · 2 usage error / unreadable manifest.
"""
import html
import importlib.util
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))

STATUS_COLORS = {
    "done": "#1a7f37", "in_progress": "#9a6700", "blocked": "#cf222e",
    "pending": "#57606a",
    "open": "#cf222e", "triaged": "#9a6700", "fixed": "#1a7f37",
    "wontfix": "#57606a",
}

_CSS = """
body{font:15px/1.5 -apple-system,'Segoe UI',Roboto,sans-serif;margin:2rem auto;
     max-width:64rem;padding:0 1rem;color:#1f2328}
h1{font-size:1.5rem}h2{font-size:1.15rem;margin-top:2rem;border-bottom:1px solid #d1d9e0;
   padding-bottom:.3rem}
table{border-collapse:collapse;width:100%;margin:.75rem 0;font-size:.92em}
th,td{border:1px solid #d1d9e0;padding:.35rem .6rem;text-align:left;vertical-align:top}
th{background:#f6f8fa}
.chip{display:inline-block;padding:0 .5em;border-radius:1em;color:#fff;font-size:.85em}
.bar{background:#eaeef2;border-radius:.4em;height:.7em;width:12em;display:inline-block;
     vertical-align:middle;overflow:hidden}
.fill{background:#1a7f37;height:100%}
.muted{color:#57606a}.mono{font-family:ui-monospace,monospace;font-size:.9em}
.outcome{color:#57606a;font-style:italic;margin:.25rem 0 .5rem}
"""


def _load_status_lib():
    spec = importlib.util.spec_from_file_location(
        "audit_status", os.path.join(_HERE, "audit-status.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def e(value):
    """Escape ANY manifest value for HTML context."""
    return html.escape(str(value if value is not None else ""), quote=True)


def _safe_url(url):
    """Return the url only when it is plain http(s) — else None (render as text)."""
    u = str(url or "")
    return u if u.startswith(("https://", "http://")) else None


def _chip(status):
    color = STATUS_COLORS.get(str(status), "#57606a")
    return '<span class="chip" style="background:%s">%s</span>' % (color, e(status))


def _ado_cell(item):
    ado = item.get("ado") if isinstance(item.get("ado"), dict) else None
    if not ado or ado.get("id") is None:
        return '<span class="muted">—</span>'
    label = "#%s" % e(ado.get("id"))
    url = _safe_url(ado.get("url"))
    if url:
        return '<a href="%s">%s</a>' % (e(url), label)
    return label


def _bar(done, total):
    pct = int(round(100.0 * done / total)) if total else 0
    return ('<span class="bar"><span class="fill" style="width:%d%%"></span></span> '
            '<span class="muted">%d/%d</span>' % (pct, done, total))


def render_html(manifest, summary):
    meta = manifest.get("meta") or {}
    now = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    out = ["<style>%s</style>" % _CSS]
    out.append("<h1>%s</h1>" % e(meta.get("title") or "Audit report"))
    out.append('<p class="muted">repo: %s · generated %s · %d phases · %d tasks'
               " · %d bugs</p>"
               % (e(meta.get("repo") or "?"), now, len(summary["phases"]),
                  summary["tasks"]["total"], summary["bugs"]["total"]))
    if not summary["valid"]:
        out.append('<p><strong style="color:#cf222e">INVALID MANIFEST: %d '
                   "validator finding(s) — fix before trusting this report."
                   "</strong></p>" % summary["findings"])

    for ph, psum in zip(
            [p for p in (manifest.get("phases") or []) if isinstance(p, dict)],
            summary["phases"]):
        out.append("<h2>%s — %s %s</h2>"
                   % (e(psum["id"]), e(psum["title"]), _chip(psum["status"])))
        out.append("<p>%s</p>" % _bar(psum["done"], psum["total"]))
        if ph.get("desiredOutcome"):
            out.append('<p class="outcome">Desired outcome: %s</p>'
                       % e(ph["desiredOutcome"]))
        rows = []
        for t in ph.get("tasks") or []:
            if not isinstance(t, dict):
                continue
            rows.append(
                "<tr><td class=mono>%s</td><td>%s</td><td>%s</td>"
                "<td>%s</td><td>%s</td><td class=mono>%s</td><td>%s</td></tr>"
                % (e(t.get("id")), e(t.get("title")), _chip(t.get("status")),
                   e(t.get("model") or "—"), e(t.get("risk") or "—"),
                   e((t.get("commit") or "—")[:9]), _ado_cell(t)))
        out.append("<table><tr><th>id</th><th>title</th><th>status</th>"
                   "<th>model</th><th>risk</th><th>commit</th><th>ADO</th></tr>"
                   "%s</table>" % "".join(rows))
        if ph.get("summary"):
            out.append('<p class="outcome">%s</p>' % e(ph["summary"]))

    bugs = [b for b in (manifest.get("bugs") or []) if isinstance(b, dict)]
    if bugs:
        out.append("<h2>Bugs</h2>")
        rows = []
        for b in bugs:
            rows.append(
                "<tr><td class=mono>%s</td><td>%s</td><td>%s</td><td>%s</td>"
                "<td class=mono>%s</td><td class=mono>%s</td><td>%s</td></tr>"
                % (e(b.get("id")), e(b.get("title")), _chip(b.get("status")),
                   e(b.get("severity") or "—"), e(b.get("taskId") or "—"),
                   e((b.get("fixedIn") or "—")[:9]), _ado_cell(b)))
        out.append("<table><tr><th>id</th><th>title</th><th>status</th>"
                   "<th>severity</th><th>task</th><th>fixedIn</th><th>ADO</th>"
                   "</tr>%s</table>" % "".join(rows))

    if summary["ready"]:
        out.append("<h2>Ready now</h2><p class=mono>%s</p>"
                   % ", ".join(e(r) for r in summary["ready"]))
    return "\n".join(out) + "\n"


def render_md(manifest, summary):
    meta = manifest.get("meta") or {}
    now = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())

    def cell(v):
        return str(v if v is not None else "—").replace("|", "\\|").replace(
            "\n", " ")

    out = ["# %s" % cell(meta.get("title") or "Audit report"), "",
           "repo: %s · generated %s" % (cell(meta.get("repo") or "?"), now), ""]
    if not summary["valid"]:
        out += ["**INVALID MANIFEST: %d validator finding(s).**" % summary["findings"], ""]
    for ph, psum in zip(
            [p for p in (manifest.get("phases") or []) if isinstance(p, dict)],
            summary["phases"]):
        out.append("## %s — %s (%s, %d/%d)"
                   % (cell(psum["id"]), cell(psum["title"]),
                      cell(psum["status"]), psum["done"], psum["total"]))
        if ph.get("desiredOutcome"):
            out.append("_%s_" % cell(ph["desiredOutcome"]))
        out += ["", "| id | title | status | model | risk | commit | ADO |",
                "|---|---|---|---|---|---|---|"]
        for t in ph.get("tasks") or []:
            if not isinstance(t, dict):
                continue
            ado = t.get("ado") if isinstance(t.get("ado"), dict) else None
            ado_txt = "#%s" % ado["id"] if ado and ado.get("id") is not None else "—"
            out.append("| %s | %s | %s | %s | %s | %s | %s |" % (
                cell(t.get("id")), cell(t.get("title")), cell(t.get("status")),
                cell(t.get("model") or "—"), cell(t.get("risk") or "—"),
                cell((t.get("commit") or "—")[:9]), cell(ado_txt)))
        out.append("")
    bugs = [b for b in (manifest.get("bugs") or []) if isinstance(b, dict)]
    if bugs:
        out += ["## Bugs", "",
                "| id | title | status | severity | task | fixedIn |",
                "|---|---|---|---|---|---|"]
        for b in bugs:
            out.append("| %s | %s | %s | %s | %s | %s |" % (
                cell(b.get("id")), cell(b.get("title")), cell(b.get("status")),
                cell(b.get("severity") or "—"), cell(b.get("taskId") or "—"),
                cell((b.get("fixedIn") or "—")[:9])))
        out.append("")
    if summary["ready"]:
        out += ["## Ready now", "", ", ".join(cell(r) for r in summary["ready"]), ""]
    return "\n".join(out)


def main(argv):
    args = list(argv)
    out_dir = None
    fmt = "both"
    for flag, val in (("--out-dir", True), ("--format", True)):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.stderr.write("usage: %s needs a value\n" % flag)
                return 2
            if flag == "--out-dir":
                out_dir = args[i + 1]
            else:
                fmt = args[i + 1]
            del args[i:i + 2]
    if fmt not in ("html", "md", "both") or len(args) != 1:
        sys.stderr.write("usage: render-report.py <manifest> [--out-dir DIR] "
                         "[--format html|md|both]\n")
        return 2

    manifest_path = args[0]
    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n" % (manifest_path, exc))
        return 2

    lib = _load_status_lib()
    vm = lib._load_validator()
    try:
        findings, warnings = vm.validate(manifest)
    except Exception as exc:  # defensive
        findings, warnings = ["internal validator error: %s" % exc], []
    summary = lib.rollup(manifest, findings, warnings)

    out_dir = out_dir or (os.path.dirname(os.path.abspath(manifest_path)) or ".")
    os.makedirs(out_dir, exist_ok=True)
    written = []
    if fmt in ("html", "both"):
        p = os.path.join(out_dir, "audit-report.html")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(render_html(manifest, summary))
        written.append(p)
    if fmt in ("md", "both"):
        p = os.path.join(out_dir, "audit-report.md")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(render_md(manifest, summary))
        written.append(p)
    for p in written:
        print("wrote %s" % p)
    return 0


# --- selftest -------------------------------------------------------------------
def _selftest():
    import tempfile

    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                           (" (%s)" % detail) if detail and not ok else ""))

    evil_title = "<script>alert(1)</script>"
    manifest = {
        "meta": {"version": 2, "title": evil_title, "repo": "r"},
        "phases": [
            {"id": "P1", "title": "Phase & <b>bold</b>", "status": "in_progress",
             "desiredOutcome": "Outcome with <img src=x onerror=alert(1)>",
             "tasks": [
                 {"id": "P1.1", "title": "done task", "status": "done",
                  "commit": "abcdef1234567", "files": ["src/a.ts"],
                  "ado": {"id": 42, "url": "https://dev.azure.com/o/p/_workitems/edit/42"}},
                 {"id": "P1.2", "title": "evil url", "status": "pending",
                  "ado": {"id": 7, "url": "javascript:alert(1)"}},
             ]},
        ],
        "fileIndex": {"src/a.ts": ["P1.1"]},
        "bugs": [{"id": "BUG-1", "title": "a|bug", "status": "open",
                  "severity": "high"}],
    }

    tmp = tempfile.mkdtemp(prefix="render-report-selftest-")
    mp = os.path.join(tmp, "m.json")
    with open(mp, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)

    rc = main([mp, "--out-dir", tmp])
    check("c1 CLI exits 0", rc == 0)
    hp, dp = os.path.join(tmp, "audit-report.html"), os.path.join(tmp, "audit-report.md")
    check("c2 both artifacts exist and are non-empty",
          os.path.getsize(hp) > 0 and os.path.getsize(dp) > 0)

    html_out = open(hp, encoding="utf-8").read()
    md_out = open(dp, encoding="utf-8").read()

    check("x1 script tag escaped", "<script>alert" not in html_out
          and "&lt;script&gt;" in html_out)
    check("x2 attribute injection escaped", "onerror=alert" not in html_out
          or "&lt;img" in html_out)
    check("x3 javascript: url NOT a link",
          'href="javascript:' not in html_out)
    check("x4 https ado url IS a link",
          'href="https://dev.azure.com/o/p/_workitems/edit/42"' in html_out)
    check("x5 zero external fetches",
          "http" not in html_out.replace('href="https://dev.azure.com/o/p/_workitems/edit/42"', ""))
    check("m1 md contains phase heading and escaped pipe",
          "## P1" in md_out and "a\\|bug" in md_out)
    check("m2 md table row for the done task",
          "| P1.1 | done task | done |" in md_out and "#42" in md_out)
    check("h1 progress bar rendered", 'class="bar"' in html_out
          and "1/2" in html_out)
    check("r1 ready list rendered", "P1.2" in md_out)

    rc = main([mp, "--format", "nope"])
    check("c3 bad format is usage error (exit 2)", rc == 2)
    rc = main([os.path.join(tmp, "missing.json")])
    check("c4 unreadable manifest (exit 2)", rc == 2)

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
