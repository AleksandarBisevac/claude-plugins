#!/usr/bin/env python3
"""
Render the audit manifest as a self-contained HTML + Markdown report.

Publishable as a CI artifact (see docs/examples/azure-pipelines.yml) or opened
locally — the HTML inlines all CSS and fetches NOTHING. Every string from the
manifest is escaped (manifest content is untrusted input), and ado/link URLs
render as links only when they are http(s).

Usage:
  render-report.py <manifest> [--out-dir DIR] [--format html|md|both|artifact]
                              [--summary-file PATH] [--basename NAME]

  --format artifact writes <basename>.artifact.html: the same report with no
  document wrapper, for a host that supplies its own (a Claude Code Artifact).
  render-report.py --selftest

Writes <basename>.html / <basename>.md into --out-dir (default: the manifest's
own directory) and prints the paths. `basename` is `--basename` › the manifest's
`meta.reportBasename` › `audit-report`, sanitized to [A-Za-z0-9-_].
Exit codes: 0 ok · 2 usage error / unreadable manifest.

WHAT IS STILL HERE AFTER THE SPLITS. The document itself is
`_report_page.render_html` and its Markdown twin is `_report_md.render_md`
(P13.3); the fragments they glue are `_report_html` (P13.1) and `_report_usage`
(P13.2). This file keeps `main()` — the arguments, the manifest read, the theme
resolve, the files it writes — and `_verdict`, which cannot move: the gate is
`audit-status.py`, an entry point, so the verdict is computed here and INJECTED
into the page rather than reached for from a module below (see the
`# --- the gate verdict ---` section).

It also keeps the ~230 cases, and that is the honest shape rather than a
leftover. They render a report through `main()` into a temp directory and then
assert about the emitted DOCUMENT — its markup, the ORDER things are emitted in,
the stylesheet, the embedded script. A fragment module cannot produce one, so
splitting those cases by whichever function happens to emit each string would
have left two suites and no complete one.
"""
import json
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, _HERE)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR index+shards)
import _ui_theme as _theme   # noqa: E402  (tokens + labels shared with the panel)


def _panel_cfg(project):
    """The project's .claude/audit.config.json, or {}. Read here rather than
    through the panel's reader: this script must stay usable from a bare
    checkout with nothing else running."""
    path = os.path.join(project, ".claude", "audit.config.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
import _loader                # noqa: E402  (the one way scripts/ loads a sibling script as a library)
import _report_ui             # noqa: E402  (CSS/SCRIPT, off disk as real files under ui/)
import _report_html           # noqa: E402  (HTML fragment builders: escaping, chips, cells, filter panel)
import _report_usage          # noqa: E402  (the Usage section: ledger load, charts, markdown twin)
import _report_md             # noqa: E402  (the Markdown twin)
import _report_page           # noqa: E402  (the whole document: vocab, table, render_html)


# --- module aliases (CSS/SCRIPT, page + fragment + usage re-exports) ------------
# Chip and pipeline-rail colors live in the report's CSS theme tokens (see _CSS),
# keyed off the `data-status` / `data-risk` attributes the markup carries — so a
# single token set themes every status/risk consistently in both light and dark.
_CSS = _report_ui.CSS

# Inline, self-contained (no external fetch) filter/sort/search over the report
# tables. Progressive enhancement: the report is fully readable with JS off.
_SCRIPT = _report_ui.SCRIPT


def _load_status_lib():
    return _loader.load_script("audit-status.py", modname="audit_status",
                                cache=False)


# HTML fragment builders (escaping, chips, cells, filter panel) live in
# _report_html.py (P13.1) — bottom of the report's module graph, imported by
# nothing upward. This file used to alias two dozen of them, for the reason the
# comment said out loud: so `render_html`/`render_md` could spell them unchanged.
# Those two left with P13.3 and took the reason with them, so what is aliased now
# is only what `main()` and the suite below still ask for by name; everything
# else is still reachable, and still spelled, as `_report_html.<name>`.
#
# `_report_basename` is not only this file's: `_panel_state` reads it off this
# module BY NAME when the panel's Export button asks where the report will land,
# so it is part of what render-report.py exports rather than an internal
# convenience. `main` and `_report_basename` are that whole exported surface.
_report_basename = _report_html._report_basename
_filter_panel = _report_html._filter_panel


# The stylesheet lints live beside the stylesheet they police, in _ui_theme,
# so the panel is held to the same rules. Aliased rather than renamed at the
# call sites: these names are what the selftest below asks for by hand.
_undeclared_css_vars = _theme.undeclared_css_vars
_unterminated_css_decls = _theme.unterminated_css_decls
_mangled_css_escapes = _theme.mangled_css_escapes
_theme_asymmetric_vars = _theme.theme_asymmetric_vars
_themes_missing_color_scheme = _theme.themes_missing_color_scheme


# The Usage section lives in _report_usage.py (P13.2); `load_usage` is the half
# this file still calls, to hand the ledger to the page.
load_usage = _report_usage.load_usage

# The document itself lives in _report_page.py (P13.3) and its Markdown twin in
# _report_md.py — this file kept `main()`, the theme resolve and the suite that
# reads what `main()` writes. Aliased so the ~230 cases below, which are about
# the RENDERED DOCUMENT and can therefore live nowhere else, keep asking for
# these names unchanged.
_plural = _report_page._plural
PRIMARY_COLS = _report_page.PRIMARY_COLS
_OPTIONAL_COLS = _report_page._OPTIONAL_COLS
_present_columns = _report_page._present_columns
_held_by = _report_page._held_by
render_md = _report_md.render_md


# --- the gate verdict -----------------------------------------------------------
# The gate is `audit-status.py`, an entry point, and `_loader` is how this file
# reaches one — an L7 -> L7 edge `_deps.KNOWN_LAYER_DEBT` already records. That
# is why the verdict is computed HERE and injected into `_report_page`
# (layer 6) rather than fetched from inside it: a helper reaching up to an entry
# point would be a new inversion, and `_deps.layer_violations()` reads runtime
# `_loader` calls, so it would report one.
_GATE_WORDS = {
    "invalid": lambda n: _plural(n, "validator finding"),
    "open-high-bugs": lambda n: _plural(n, "high-severity bug") + " still open",
    "blocked-tasks": lambda n: _plural(n, "blocked task"),
}


def _verdict(summary):
    """The gate's own verdict, not a second opinion composed here.

    Runs `evaluate_gate` with the same DEFAULT_GATE the CI job uses, so the word at
    the top of the report is the word the pipeline would print, and the conditions
    that produced it are named underneath. A hero that scored the plan by a private
    rule would be unverifiable — this one is reproducible with one command.
    """
    lib = _load_status_lib()
    try:
        failed = lib.evaluate_gate(summary, lib.DEFAULT_GATE)
    except Exception:                     # defensive: a hero must never be the crash
        return None, [], []
    counts = {
        "invalid": summary.get("findings") or 0,
        "open-high-bugs": summary["bugs"]["openHighSeverity"],
        "blocked-tasks": summary["tasks"]["byStatus"].get("blocked", 0),
    }
    why = [_GATE_WORDS[c](counts[c]) for c in failed if c in _GATE_WORDS]
    return ("blocked" if failed else "clear"), why, list(lib.DEFAULT_GATE)


# --- rendering ------------------------------------------------------------------
def render_html(manifest, summary, basename="audit-report", usage=None,
                fragment=False, css=None):
    """The HTML report, with this file's gate verdict wired into it.

    The document itself is `_report_page.render_html`; the only thing added here
    is `_verdict`, which reaches `audit-status.py` and therefore cannot live in a
    module below the entry points (see the `# --- the gate verdict ---` note
    above). Keeping the injection in a wrapper rather than at every call site is
    what lets this signature stay exactly what it has always been.
    """
    return _report_page.render_html(manifest, summary, basename, usage,
                                    fragment=fragment, css=css,
                                    verdict=_verdict)


# --- cli ------------------------------------------------------------------------
def main(argv):
    args = list(argv)
    out_dir = None
    fmt = "both"
    summary_file = None
    cli_basename = None
    for flag in ("--out-dir", "--format", "--summary-file", "--basename"):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.stderr.write("usage: %s needs a value\n" % flag)
                return 2
            val = args[i + 1]
            if flag == "--out-dir":
                out_dir = val
            elif flag == "--format":
                fmt = val
            elif flag == "--summary-file":
                summary_file = val
            else:
                cli_basename = val
            del args[i:i + 2]
    if fmt not in ("html", "md", "both", "artifact") or len(args) != 1:
        sys.stderr.write("usage: render-report.py <manifest> [--out-dir DIR] "
                         "[--format html|md|both|artifact] [--summary-file PATH] "
                         "[--basename NAME]\n")
        return 2

    manifest_path = args[0]
    try:
        manifest = _mio.load_manifest(manifest_path)
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n" % (manifest_path, exc))
        return 2
    if not isinstance(manifest, dict):
        sys.stderr.write("ERROR: %s is not a JSON object (got %s)\n"
                         % (manifest_path, type(manifest).__name__))
        return 2

    # --summary-file lets /audit:report pass an AI-authored narrative summary
    # WITHOUT mutating the manifest (the command stays read-only). It is injected
    # into the in-memory manifest's meta.reportSummary; the file is never rewritten.
    if summary_file:
        try:
            with open(summary_file, "r", encoding="utf-8") as fh:
                text = fh.read().strip()
            if text:
                meta = manifest.get("meta")
                if not isinstance(meta, dict):
                    meta = manifest["meta"] = {}
                meta["reportSummary"] = text
        except Exception as exc:
            sys.stderr.write("WARNING: could not read --summary-file %s: %s\n"
                             % (summary_file, exc))

    lib = _load_status_lib()
    vm = lib._load_validator()
    try:
        findings, warnings = vm.validate(manifest)
    except Exception as exc:  # defensive
        findings, warnings = ["internal validator error: %s" % exc], []
    summary = lib.rollup(manifest, findings, warnings)
    usage = load_usage(manifest, manifest_path)

    # th (F-P-6): resolve the look once — project theme, then the user's, then
    # the built-in — and hand the compiled sheet to every writer below. A theme
    # that failed to load says so on stderr and the report still renders: a
    # look is decoration, and decoration never takes the document down.
    _proj = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(
        os.path.abspath(manifest_path)) or "."
    try:
        _cfg = _panel_cfg(_proj)
    except Exception:
        _cfg = {}
    _tokens, _tinfo = _theme.token_css_for(_proj, _cfg)
    # tokens + the report's own rules, assembled where that concatenation is
    # defined — the token block alone is not a stylesheet.
    _css = _report_ui.css_with_tokens(_tokens)
    if _tinfo.get("error"):
        sys.stderr.write("WARNING: theme not applied - %s\n" % _tinfo["error"])

    basename = _report_basename(manifest.get("meta"), cli_basename)
    out_dir = out_dir or (os.path.dirname(os.path.abspath(manifest_path)) or ".")
    os.makedirs(out_dir, exist_ok=True)
    written = []
    if fmt in ("html", "both"):
        p = os.path.join(out_dir, basename + ".html")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(render_html(manifest, summary, basename, usage,
                                 css=_css))
        written.append(p)
    if fmt == "artifact":
        # A separate name, never the .html one. The standalone file is what people
        # open from disk and what CI diffs the live demo against; overwriting it
        # with a fragment would leave both looking fine and one of them broken.
        p = os.path.join(out_dir, basename + ".artifact.html")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(render_html(manifest, summary, basename, usage,
                                 fragment=True, css=_css))
        written.append(p)
    if fmt in ("md", "both"):
        p = os.path.join(out_dir, basename + ".md")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(render_md(manifest, summary, usage))
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

    # F-C-1: substring pins about MARKUP must not read the embedded scripts.
    # report.js and the payload blobs are embedded whole in every rendered
    # document, so a literal like `<th>` in script SOURCE counted as a table
    # column -- v0.36 D even shipped a `'<' + 'th>'` string-split in report.js
    # to dodge the cols: pin. The check was blind, not the product wrong.
    # Markup pins below read the document through this helper; pins that are
    # deliberately ABOUT script or the whole document (the x* escaping cases,
    # the _SCRIPT source pins, uh's JS-source counts) keep the full text.
    def _markup(doc):
        return re.sub(r"(?is)<script\b.*?</script\s*>", "", doc)

    evil_title = "<script>alert(1)</script>"
    manifest = {
        "meta": {"version": 2, "title": evil_title, "repo": "r",
                 "reportSummary": "closed all criticals & shipped v0.5.0"},
        "phases": [
            {"id": "P1", "title": "Phase & <b>bold</b>", "status": "in_progress",
             "desiredOutcome": "Outcome with <img src=x onerror=alert(1)>",
             "branch": "audit/p1-x", "mergedAt": "2026-07-09T00:00:00Z",
             "tasks": [
                 {"id": "P1.1", "title": "done task", "status": "done",
                  "commit": "abcdef1234567", "files": ["src/a.ts"], "risk": "high",
                  "model": "sonnet",
                  "startedAt": "2026-07-09T08:00:00Z",
                  "completedAt": "2026-07-09T09:30:00Z",
                  "outcome": {"descriptive": "did the thing cleanly"},
                  "ado": {"id": 42, "url": "https://dev.azure.com/o/p/_workitems/edit/42"}},
                 # A SECOND model, so the filter has something to choose between:
                 # one model renders one chip, and a set of one cannot tell a
                 # working filter from a filter that always matches.
                 {"id": "P1.2", "title": "evil url", "status": "pending",
                  "model": "opus",
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

    # th (F-P-6): a report is a FILE — mailed, published, opened months later —
    # so the theme is COMPILED INTO it rather than referenced. Rendered with a
    # project theme on disk, the stylesheet must carry that value and still be a
    # whole stylesheet (the token block alone loses every rule in report.css,
    # which is what the first version of this shipped).
    _thproj = os.path.join(tmp, "themed")
    os.makedirs(os.path.join(_thproj, ".claude"), exist_ok=True)
    with open(os.path.join(_thproj, ".claude", "audit.theme.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"tokens": {"--accent": {"$value": "#b5179e",
                                           "$dark": "#f72585"}}}, fh)
    _thm = os.path.join(_thproj, "m.json")
    with open(_thm, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)
    _prev = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = _thproj
    try:
        main([_thm, "--out-dir", _thproj])
    finally:
        if _prev is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = _prev
    with open(os.path.join(_thproj, "audit-report.html"), encoding="utf-8") as fh:
        _thhtml = fh.read()
    check("th-r1 the report wears the project's theme, compiled in",
          "--accent:#b5179e" in _thhtml and "--accent:#f72585" in _thhtml
          and "--accent:#0d9488" not in _thhtml)
    check("th-r2 ...and it is still the WHOLE stylesheet, not the token block "
          "alone - every rule report.css contributes must survive theming",
          "table.phases" in _thhtml and "prefers-reduced-motion" in _thhtml
          and 'id="audit-theme"' in _thhtml)
    check("th-r3 an untheme'd project renders exactly what it always did",
          "--accent:#0d9488" in _report_ui.CSS
          and _report_ui.css_with_tokens(None) == _report_ui.CSS)
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
    # exclude the ADO link and the opaque embedded-markdown blob (data, not a fetch)
    _marker = 'window.AUDIT_MD_B64="'
    _s = html_out
    if _marker in _s:
        _i = _s.index(_marker)
        _j = _s.index('"', _i + len(_marker))
        _s = _s[:_i] + _s[_j:]
    _s = _s.replace('href="https://dev.azure.com/o/p/_workitems/edit/42"', "")
    check("x5 zero external fetches (ado link + embedded md blob excluded)",
          "http" not in _s)
    # --- usage section ---------------------------------------------------------
    check("u1 no ledger -> no Usage section at all (back-compat)",
          'id="usage"' not in html_out and "## Usage" not in md_out)
    _u = {
        "totals": {"tokens": 1_500_000, "in": 1000, "out": 200_000,
                   "cacheW5m": 100_000, "cacheW1h": 0, "cacheR": 1_199_000,
                   "msgs": 42, "costUSD": 12.3456, "sessions": 3, "authors": 2,
                   "models": 2, "tasks": 4, "phases": 2, "cacheHitPct": 79.9},
        "byPhase": {"P1": {"tokens": 1_000_000, "costUSD": 8.0, "msgs": 30},
                    "--": {"tokens": 500_000, "costUSD": 4.3456, "msgs": 12}},
        "byModel": {"claude-opus-5": {"tokens": 900_000, "costUSD": 9.0, "msgs": 20},
                    "claude-haiku-4-5": {"tokens": 600_000, "costUSD": 3.3, "msgs": 22}},
        "byAuthor": {"a@x.io": {"tokens": 1_000_000, "costUSD": 8.0, "msgs": 30},
                     "b@x.io": {"tokens": 500_000, "costUSD": 4.3, "msgs": 12}},
        "byAgent": {}, "phaseTitles": {"P1": "Alpha"},
        "phaseModel": {"P1": {"claude-opus-5": 900_000, "claude-haiku-4-5": 100_000},
                       "--": {"claude-haiku-4-5": 500_000}},
        "daily": {"2026-08-01": 900_000, "2026-08-02": 600_000},
        "heatmap": [[0] * 24 for _ in range(7)],
        "showCost": True, "pricingAsOf": "2026-08-06",
        "counts": {"phases": 2, "people": 2, "models": 2, "sessions": 3,
                   "days": 2, "from": "2026-08-01", "to": "2026-08-02"},
    }
    _u["heatmap"][2][14] = 900_000
    _u["heatmap"][4][9] = 600_000
    _lib = _load_status_lib()
    _sum = _lib.rollup(manifest, [], [])
    uh = render_html(manifest, _sum, "audit-report", _u)
    um = render_md(manifest, _sum, _u)
    check("u2 Usage section renders when a ledger exists", 'id="usage"' in uh)
    # This case read `"2026-08-06" in uh` for four releases and asserted nothing:
    # render_html stamps `generated <today>`, so on the day it was written the
    # report's own timestamp satisfied it. It failed for the first time when the
    # clock rolled to the 7th — and what it uncovered was real. HTML surfaced
    # pricingAsOf ONLY through the >90-day stale notice, so the ordinary report
    # showed dollars with no way to see what priced them, while the Markdown twin
    # printed it every time. The phrase itself is asserted in _report_usage's
    # u4/u4b, off the section directly; what stays here is the half that needs a
    # whole document, because only a document carries the generation stamp.
    check("u4c and the date is not merely today's generation stamp "
          "(the trap this case sat in)",
          "rates as of %s" % time.strftime("%Y-%m-%d", time.gmtime()) not in uh)
    check("u10 heatmap opts out of the sticky thead used by the phases table",
          ".hm thead th{position:static" in uh)
    # A closed <details> clips its children in print media regardless of CSS, so
    # the PDF silently loses the detail block without this. Verified in-browser.
    check("u10b the disclosure is force-opened for printing, not just CSS-hinted",
          "beforeprint" in uh and "afterprint" in uh)
    check("u12 md twin carries the usage table (the contrast relief)",
          "## Usage" in um and "### By phase" in um and "### By model" in um)
    # Check the rendered ARTIFACT, not just the stylesheet: inline styles emitted
    # from Python land only in the output, and that is exactly where an undeclared
    # token hides.
    _missing = _undeclared_css_vars(_CSS + uh)
    check("u14b every fallback-less var(--token) is declared "
          "(an undeclared one paints transparent and logs nothing)",
          _missing == [], repr(_missing))
    _asym = _theme_asymmetric_vars(_CSS)
    check("u14c no colour token exists in only one theme (either direction)",
          _asym == [], repr(_asym))
    # Tokens paint our boxes; the UA paints the checkboxes, selects, spinners,
    # date picker and scrollbars from `color-scheme` alone. A theme that does not
    # restate it leaves those wearing the OS's theme while everything around them
    # follows the toggle — invisible in the stylesheet, obvious on screen.
    _nocs = _themes_missing_color_scheme(_CSS)
    check("u14i every explicit data-theme restates color-scheme, so the toggle "
          "moves the native controls with it", _nocs == [], repr(_nocs))
    # This stylesheet lives in a non-raw Python string, so every CSS escape has to
    # be written twice over. `content:"\2713\a0"` compiled to `¹3<BEL>0` and drew
    # exactly that on the one chip whose whole job was to state its own state
    # without colour — for as long as that chip has existed, with the suite green.
    _esc = _mangled_css_escapes(_CSS)
    check("u14j no CSS escape was eaten by Python before the browser saw it",
          _esc == [], repr(_esc))
    # A missing `;` after a custom property annexes the comment and declarations
    # that follow it. Silent, and it killed every animation in this stylesheet once.
    _unterm = _unterminated_css_decls(_CSS)
    check("u14d no custom-property declaration runs past its line without a ';' "
          "(it would annex whatever follows)", _unterm == [], repr(_unterm))
    check("u14e the annexing case is detected",
          _unterminated_css_decls(
              ":root{\n  --ease:linear\n  /* c */\n  --sp-0:.25rem;\n}") != [])
    check("u14f the last declaration in a block may legally omit its ';'",
          _unterminated_css_decls(":root{\n  --a:1px;\n  --b:2px\n}") == [])
    check("u14g --ease resolves to a single value (its shorthand users depend on it)",
          re.search(r"--ease:\s*cubic-bezier\([^)]*\);", _CSS) is not None)
    check("u14h --sp-0 survives as its own declaration",
          re.search(r"--sp-0:\s*\.25rem", _CSS) is not None)
    # The progress fill is a <span>. Inline boxes ignore width and height, so without
    # an explicit display the bar paints as an empty track at every percentage —
    # which is what shipped from the redesign until it was caught by a capture.
    check("u14i the progress fill declares a non-inline display "
          "(a <span> would otherwise ignore its width)",
          re.search(r"\.fill\{[^}]*display:\s*block", _CSS) is not None)
    # A reveal animation with only a `from` keyframe leaves its end state to be
    # synthesised, and `fill-mode:both` can then hold the element at the from-state.
    for _kf in ("fillIn", "fadeUp"):
        _body = re.search(r"@keyframes %s\{([^}]*\}[^}]*)\}" % _kf, _CSS)
        check("u14k %s declares both endpoints (from AND to)" % _kf,
              _body is not None and "to{" in _body.group(1), _kf)

    # --- accessibility of the interactive layer --------------------------------
    # Each of these shipped broken: the report is the product's most public artifact
    # and its controls were mouse-and-sighted-only.
    check("a1 the document declares a language "
          "(without it a screen reader guesses, and may read the whole report "
          "in the wrong voice)",
          '<html lang="en">' in html_out)
    check("a2 the document element is closed", html_out.rstrip().endswith("</html>"))

    # --- the gate rail (signature) --------------------------------------------
    # A phase row's class stays exactly `phase` whatever the gate is doing. The
    # first version carried held-ness in the class (`class="phase held"`), which
    # silently broke CI's `grep -c 'tr class="phase"'` on the scale demo — 37 of 40
    # phases counted, because three were held. Gate state is derived state and
    # belongs with `data-status`, not in the identity of the row.
    check("rail: a phase row is class=phase whatever its gate state, so counting "
          "phase rows cannot depend on the plan's shape",
          _markup(html_out).count('<tr class="phase"') == len(_sum["phases"]))
    # A purpose-built chain rather than the main fixture: A done, B blocked by A
    # (satisfied), C blocked by B (not). That is the whole point of the rail in
    # three phases — one gate that opened, one that has not.
    _rm = {"meta": {"title": "rail"}, "bugs": [], "phases": [
        {"id": "A", "title": "First", "status": "done",
         "tasks": [{"id": "A.1", "title": "t", "status": "done",
                    "commit": "abc1234def"}]},
        {"id": "B", "title": "Second", "status": "pending", "blockedBy": ["A"],
         "tasks": [{"id": "B.1", "title": "t", "status": "pending"}]},
        {"id": "C", "title": "Third", "status": "pending", "blockedBy": ["B"],
         "tasks": [{"id": "C.1", "title": "t", "status": "pending"}]}]}
    _rh = render_html(_rm, _load_status_lib().rollup(_rm, [], []), "r", None)
    check("rail: a held phase is marked with data-held, beside data-status",
          _markup(_rh).count('data-held="1"') == 2)   # phase C and its one task
    check("rail: it names what holds it, and links there - a closed gate with no "
          "sign on it is just a locked door",
          'class="heldby" href="#phase-B"' in _rh)
    check("rail: a gate whose blocker is DONE is drawn open - B is blocked by A "
          "and A is signed off, so nothing holds B",
          'id="phase-B"' in _rh and 'href="#phase-A"' not in _rh)
    check("rail: a phase blocked by a phase that IS done is not held - the gate "
          "draws dependency, not a restatement of status",
          _held_by({"blockedBy": ["P1"]}, {"P1"}) == []
          and _held_by({"blockedBy": ["P1", "P2"]}, {"P1"}) == ["P2"])
    check("rail: the line is one colour and the gates carry the state, so the "
          "spine is structure rather than a second copy of the status chip",
          "--rail:" in _CSS and "border-left:2px solid var(--st" not in _CSS)
    check("rail: a signed-off phase is stamped with a commit it actually has, "
          "short-formed, and labelled as the last commit rather than as a "
          "signature the manifest does not record",
          'class="stamp"' in _rh and ">abc1234<" in _rh
          and "Last commit recorded in this phase" in _rh)
    check("rail: an unsigned phase carries no stamp",
          _markup(_rh).count('class="stamp"') == 1)
    # The verdict is the gate's, not the report's.
    check("verdict: the hero states the same verdict --gate would, with the "
          "conditions that produced it named",
          'data-gate=' in html_out and "vd-word" in html_out
          and "Spend is deliberately not one of them" in html_out)
    check("verdict: the conditions are in the reader's words, with the flag "
          "names kept in the title for whoever will type them",
          "manifest validity" in html_out and "--fail-on" in html_out)
    check("verdict: the ready task is promoted into the hero and is copyable",
          'class="vd-run"' in html_out and "btn-copy" in html_out)

    # --- app shell -------------------------------------------------------------
    check("shell: navigation at the side, document actions on top",
          'class="topbar"' in html_out and 'class="snav"' in html_out
          and 'class="shell"' in html_out)
    # The nav and the anchors come from ONE list, so a section cannot be linked
    # without existing or exist without being linked.
    _anchors = set(re.findall(r'<(?:section|div|h2|h3)[^>]*id="([a-z0-9-]+)"', html_out))
    _links = set(re.findall(r'class="snav"[\s\S]*?</nav>', html_out)
                 and re.findall(r'<a href="#([a-z0-9-]+)"',
                                html_out[html_out.index('class="snav"'):
                                         html_out.index("</nav>")]))
    check("shell: every nav link points at a section that exists: %r"
          % sorted(_links - _anchors), _links and _links <= _anchors)
    check("shell: the nav is rendered server-side, so a report read with JS off - "
          "or printed - still has its contents list",
          "<nav class=\"snav\"" in html_out and 'href="#gate"' in html_out)
    check("shell: scroll-spy only ADDS position; it does not supply the links",
          "markSpy" in _SCRIPT and "aria-current" in _SCRIPT)
    # The observer this replaced watched each target inside a 15%-30% band of the
    # viewport. Most targets are <h2> elements a line and a half tall, so usually
    # NONE was in the band and the nav marked nothing at all. Order, not
    # visibility: whichever heading last passed under the bar is where you are.
    check("shell: the marker is decided by which heading last passed the fold, so "
          "one link is always marked - a band-based observer marked none",
          "new IntersectionObserver" not in _SCRIPT
          and "if (best < 0) best = 0;" in _SCRIPT
          and "getBoundingClientRect().top <= fold" in _SCRIPT)

    # --- the sticky stack ------------------------------------------------------
    # Four hand-tuned offsets (4.1rem nav, 3.6rem filter bar, 3.5rem headers,
    # 6.6rem below 72rem) were four guesses at ONE number. The bar measures 70px:
    # the filter bar pinned 12px under it and the column headers pinned ABOVE the
    # filter bar and were painted out entirely.
    check("sticky: one measured offset, and every pinned layer derives from it",
          "--topbar-h:" in _CSS and "--sticky-2:calc(var(--sticky-1)" in _CSS
          and "--sticky-3:calc(var(--sticky-2)" in _CSS
          and "top:var(--sticky-2)" in _CSS and "top:var(--sticky-3)" in _CSS)
    # Checked against declarations only: the prose above these rules still names
    # the old constants, and it should - it is the record of what went wrong.
    _css_decl = re.sub(r"/\*.*?\*/", "", _CSS, flags=re.S)
    check("sticky: no layer keeps a hand-tuned offset the bar can outgrow",
          not re.search(r"top:\s*(3\.4|3\.5|3\.6|4\.1|6\.6)rem", _css_decl))
    check("sticky: the column headers pin BELOW the bar that filters them, and "
          "paint under it rather than over it",
          "--z-sectools:15" in _CSS and "--z-thead:10" in _CSS
          and "z-index:var(--z-thead)" in _CSS
          and "z-index:var(--z-sectools)" in _CSS)
    check("sticky: the stack is restated at runtime, because its height depends "
          "on the title, the width and the reader's font size",
          "measureStack" in _SCRIPT and "--topbar-h" in _SCRIPT
          and "ResizeObserver" in _SCRIPT)
    # Anchors are how this report is navigated; every one of them landed under the
    # bar, which reads as "the link goes somewhere slightly below the heading".
    check("sticky: every anchor clears the stack instead of landing beneath it",
          "[id]{scroll-margin-top:calc(var(--sticky-2)" in _CSS)
    check("sticky: the scrollbar's width is reserved, so a short page and a long "
          "one do not centre the shell at two different offsets",
          "scrollbar-gutter:stable" in _CSS)

    # --- one missing element must not take the page down -----------------------
    check("guards: no early return above the print/download/copy/tooltip wiring - "
          "they have nothing to do with the phases table",
          "if (!grouped) return;" not in _SCRIPT
          and "grouped ? [].slice.call(grouped" in _SCRIPT)
    check("guards: a link inside a phase row is followed, not swallowed by the "
          "row's own expand/collapse",
          "closest('a,button,input,select,summary,label')" in _SCRIPT)
    check("guards: a chip's other classes survive being toggled",
          "classList.toggle('on', on)" in _SCRIPT
          and "x.className.split(' ')[0]" not in _SCRIPT)
    # A report outlives its tree: it gets mailed, archived, opened next week. When
    # someone reports a control that does not work, which renderer wrote the page
    # is the first thing worth knowing.
    check("stamp: the page names the plugin version that rendered it",
          'class="stampv"' in html_out and "audit " in html_out)

    # --- one badge grammar, and words instead of keys --------------------------
    check("badges: a status reads as English, with the machine value kept in the "
          "attribute so filtering and theming still compare keys",
          'data-status="in_progress"' in html_out
          and ">In progress<" in html_out
          and ">in_progress<" not in html_out)
    check("badges: one tinted grammar drives every status, so the amber "
          "special case is gone with the solid fill that required it",
          "--st-ink" in _CSS and "color-mix(in srgb,var(--st" in _CSS
          and "--chip-ink" not in _CSS)
    check("badges: the hue is carried by a dot, not only by the text colour",
          ".chip::before{" in _CSS)
    # The GLYPH, not just the selector. The selector-only version of this check was
    # green for the entire life of a chip that drew `¹30` where the tick belonged.
    check("filters: an active chip says so without relying on hue - and the tick "
          "reaches the browser as an escape, not as the octal wreckage of one",
          ".fchip.on::before" in _CSS
          and _mangled_css_escapes(
              _CSS[_CSS.index(".fchip.on::before"):][:120]) == [])
    # The markdown twin is a data table read by machines and by GitHub; it keeps
    # the machine spelling on purpose.
    check("badges: the markdown twin still speaks the manifest's own vocabulary",
          "| done |" in md_out or "| in_progress |" in md_out)
    # Built in JS, the whole filter bar was missing from any context that does not
    # run scripts - the one case where "gone" and "broken" look the same.
    check("filters: the chips are in the document, not created by the script",
          'class="fchip" data-ps=' in html_out
          and 'class="tf-chip" data-ts=' in html_out
          and 'aria-pressed="false"' in html_out
          and "createElement('button')" not in _SCRIPT)
    check("filters: the script attaches behaviour rather than building the UI",
          "function wireChips" in _SCRIPT and "buildChips" not in _SCRIPT)

    # --- c5: model + date filters, no auto-expand, match counts, hash state ----
    # These pin the SHAPE. Whether any of it works is settled in a browser by
    # tools/check-report-interactive.mjs, because a report whose script dies on
    # line one still contains every string below.
    check("c5: a task row carries what the filters compare, rather than making "
          "them read it back out of the rendered prose",
          'data-model="' in html_out and 'data-completed="' in html_out)
    check("c5: dates are cut to their date part, so a range test is a string "
          "comparison and an <input type=date> value can be one end of it",
          re.search(r'data-completed="\d{4}-\d{2}-\d{2}"', html_out) is not None
          and 'data-completed="20' in html_out
          and not re.search(r'data-(completed|started)="[^"]*T', html_out))
    check("c5: the model and date controls are in the document inside a native "
          "<details> - built in JS they would be missing from every no-script "
          "reader and every printed page, the same trap the status chips fell in",
          'class="fdetails"' in html_out
          and 'class="filterpanel"' in html_out
          and '<summary' in html_out
          and 'class="fchip" data-m=' in html_out
          and '<input type="date" id="audit-from"' in html_out)
    check("c5: a model chip is spelled the way the table spells it - a model name "
          "is an identifier, not a word this product chose",
          '<button type="button" class="fchip" data-m="opus" aria-pressed="false">'
          "opus</button>" in html_out)
    check("c5: the date picker opens on the months the plan actually covers",
          re.search(r'id="audit-from"[^>]*min="\d{4}-\d{2}-\d{2}"[^>]*'
                    r'max="\d{4}-\d{2}-\d{2}"', html_out) is not None)
    check("c5: the panel is out of flow, so opening it cannot move the sticky "
          "stack every anchor and column header is pinned against",
          ".filterpanel{position:absolute" in _CSS and ".fdetails{position:relative}" in _CSS)
    # The panel is a popover, so it answers to the two things every popover
    # answers to. A <details> does neither on its own — it closes only through its
    # own summary — and this one is absolutely positioned, so left open it covers
    # rows it has nothing to do with.
    check("filters: an outside click closes the More-filters panel",
          "details.fdetails[open]" in _SCRIPT and "!d.contains(ev.target)" in _SCRIPT)
    check("filters: Escape closes it and returns focus to the control that opened it",
          "if (ev.key !== 'Escape') return;" in _SCRIPT and "sum.focus()" in _SCRIPT)
    # Escape already means "clear the search" in the search box. One key doing two
    # things at once is worse than either.
    check("filters: Escape in the search box keeps its own meaning",
          "if (q && ev.target === q) return;" in _SCRIPT)
    # Room to read, not just room to fit: 27rem cleared the wrapping floor but left
    # four control rows crowded inside .75rem of padding.
    check("filters: the panel has room for its four rows",
          "min-width:32rem" in _CSS and "padding:1rem 1.1rem" in _CSS)
    check("filters: and still cannot outgrow a narrow viewport",
          "max-width:calc(100vw - 2rem)" in _CSS)
    # A relative span measured against the wall clock answers a different question
    # every morning — and would make the committed example a file that cannot stay
    # byte-equal to itself, which is precisely what ci.yml compares.
    check("c5: the presets measure back from the plan's own last recorded day, "
          "never from today",
          "var DMAX" in _SCRIPT
          and "Date.now()" not in _SCRIPT
          and "new Date()" not in _SCRIPT
          and "DMAX + 'T00:00:00Z'" in _SCRIPT)
    # --- C3: author chips scope the usage section, and only it -----------------
    # The chip markup itself is pinned in _report_usage's ua cases; what needs a
    # whole document is the WIRING - that report.js drives the chips, restores
    # the top-8 default, writes the summary line off the chip's own data
    # attributes, and carries the state in the hash as au=.
    check("c3: the author chips are in the document and report.js wires them "
          "rather than building them",
          'id="audit-authors"' in uh
          and "wireChips(authorBar, 'data-au'" in _SCRIPT)
    check("c3: releasing the chip restores the top-8 default by re-applying "
          "hidden from data-top, never by re-rendering",
          "c.getAttribute('data-author') !== auFilter" in _SCRIPT
          and ": !c.hasAttribute('data-top')" in _SCRIPT)
    check("c3: the summary line is assembled from the chip's own data "
          "attributes, not recomputed by a second implementation",
          "chip.getAttribute('data-tokens')" in _SCRIPT
          and "chip.getAttribute('data-share')" in _SCRIPT
          and "of all spend" in _SCRIPT)
    check("c3: the author filter is a link (au=) and restores from one",
          "put('au', auFilter)" in _SCRIPT and "if (HASH.au)" in _SCRIPT)
    check("c3: clear-all lifts the author scope with everything else "
          "(pinned INSIDE clearAll - the declaration up top spells the same "
          "bytes and satisfied a whole-script substring)",
          "auFilter = '';" in _SCRIPT.split("function clearAll()")[1])
    check("c3: hidden actually hides a rank row and a hidden smcell - the "
          "author-facing rules a UA default cannot win against",
          ".rank[hidden]{display:none}" in _CSS
          and ".smcell[hidden]{display:none}" in _CSS)
    check("c3: the task table is untouched by the author filter - no task or "
          "phase row carries an author, and refresh() never reads the state",
          re.search(r'<tr class="(?:task|phase)[^>]*data-author', uh) is None
          and "auFilter" not in _SCRIPT.split("function refresh()")[1]
              .split("function natCmp")[0])

    # --- D1: area chips finally read the data-area the renderer always emitted -
    # The phase-row emitter above has stamped space-joined tags into `data-area`
    # since areas landed; until D1 no script read it back. The chip markup is
    # pinned in _report_html's own selftest; what needs a whole document is the
    # WIRING - report.js reads the attribute, gates PHASES on it (multi-select,
    # any tag admits, no tags hides while a selection is active), and carries
    # the selection in the hash as a= - a key distinct from the author's au=.
    _ma = json.loads(json.dumps(manifest))
    _ma["phases"][0]["area"] = ["api", "web"]
    _mah = render_html(_ma, _lib.rollup(_ma, [], []), "audit-report", None)
    check("d1: a tagged plan renders the Area chip row and an untagged plan "
          "omits it (markup pinned in _report_html; this pins the document)",
          'id="audit-areas"' in _mah and 'data-a="api"' in _mah
          and 'id="audit-areas"' not in html_out)
    check("d1: report.js reads data-area off the phase row, splitting the "
          "space-joined tags the emitter writes",
          "getAttribute('data-area')" in _SCRIPT
          and "function areaOk" in _SCRIPT
          and "areaOk(pr)" in _SCRIPT)
    check("d1: the gate is multi-select and any selected tag admits a phase; "
          "with none selected it admits everything",
          "areaFilter.indexOf(tags[i])" in _SCRIPT
          and "if (!areaFilter.length) return true;" in _SCRIPT)
    check("d1: the area selection is a link (a=) and restores from one - "
          "spelled apart from the author's au=, which stays wired",
          "put('a', areaFilter.join(' '));" in _SCRIPT
          and "if (HASH.a)" in _SCRIPT
          and "put('au', auFilter)" in _SCRIPT and "if (HASH.au)" in _SCRIPT)
    check("d1: clear-all lifts the area gate with everything else, and both "
          "the way-back button and the panel count own it "
          "(the reset is pinned INSIDE clearAll - the declaration up top "
          "spells the same bytes and satisfied a whole-script substring)",
          "areaFilter = [];" in _SCRIPT.split("function clearAll()")[1]
          and "|| areaFilter.length > 0" in _SCRIPT
          and "(areaFilter.length ? 1 : 0)" in _SCRIPT)
    check("d1: the chips are wired, not built - report.js attaches behaviour "
          "to the server-rendered row",
          "wireChips(areaBar, 'data-a'" in _SCRIPT
          and "function paintAreas()" in _SCRIPT)

    # --- g: the global filter row (C1/C2) — document-level composition. --------
    # The row's own markup is pinned in _report_html's selftest; what needs a
    # whole document is what render_html feeds it and where it lands.
    check("g1 the sticky top bar carries the global filter row when there is "
          "anything to filter by, with both authors as options",
          'class="gfilters"' in uh
          and uh.index('class="gfilters"') < uh.index('<div class="shell">')
          and 'value="a@x.io"' in uh and 'value="b@x.io"' in uh)
    check("g2 the date bounds are the union of task dates AND ledger days - "
          "one range scopes both surfaces, so it must span both",
          _markup(uh).count('min="2026-07-09" max="2026-08-02"') == 2)
    check("g3 without a ledger the row still offers the task-date range, and "
          "no author select (nothing records an author)",
          'id="audit-gfrom"' in html_out
          and 'id="audit-au-select"' not in html_out)
    check("g4 a tagged plan earns the area select",
          'id="audit-area-select"' in _mah
          and 'id="audit-area-select"' not in html_out)
    _bare = {"meta": {"version": 2, "title": "b", "repo": "r"},
             "phases": [{"id": "P1", "title": "p", "status": "pending",
                         "tasks": [{"id": "P1.1", "title": "t",
                                    "status": "pending"}]}]}
    check("g5 nothing to filter by, no row at all",
          'class="gfilters"' not in render_html(
              _bare, _lib.rollup(_bare, [], []), "audit-report", None))
    check("g6 report.js wires the row over the SAME state as the panel and "
          "chips - one range entry point, both date pairs painted",
          "audit-au-select" in _SCRIPT and "audit-area-select" in _SCRIPT
          and "function setRange(" in _SCRIPT
          and "gFrom.value = dFrom" in _SCRIPT
          and "applyUsageRange();" in _SCRIPT.split("function refresh()")[1]
                                            .split("function natCmp")[0])
    check("g7 the row is a flex row OF the sticky bar (print drops it with the "
          "bar - the pinned .topbar print rule - and the range prints instead "
          "as the named line report.js writes into #audit-urange)",
          ".gfilters{flex-basis:100%" in _CSS
          and "audit-urange" in _SCRIPT)

    # --- rd: Ready now as a definition list (C4) --------------------------------
    check("rd1 Ready now is a definition list naming the ready task, and the "
          "old comma-joined mono line is gone",
          '<dl class="ready">' in html_out
          and ">P1.2</code>" in html_out
          and "Ready now</h2><p class=mono>" not in html_out)
    check("rd2 a ready task in a tagged phase wears the area chips inside the "
          "list (same .area-tag style as everywhere else)",
          '<dl class="ready">' in _mah
          and '<span class="area-tag">api</span>'
              in _mah[_mah.index('<dl class="ready">'):])
    check("rd3 the list is styled as a quiet queue, not cards",
          "dl.ready dt" in _CSS and "dl.ready dd" in _CSS)

    check("c5: filtering no longer forces its matches open - it offers a reason "
          "to open a row instead",
          "var open = showP && !!expanded[pid];" in _SCRIPT
          and "(term !== '' || tf !== '')" not in _SCRIPT)
    check("c5: and that reason is rendered - the match badge is in the row, "
          "hidden until there is something to say",
          'class="pmatch" hidden' in html_out
          and "' of ' + tasks.length + ' match'" in _SCRIPT)
    check("c5: the badge's `hidden` is honoured (a class with a display would "
          "otherwise beat it and pin '10 of 10 match' to every row at rest)",
          ".pmatch[hidden]{display:none}" in _CSS)
    check("c5: the count reports tasks as well as phases, now that a filter can "
          "narrow a phase from the inside without changing the phase count",
          "' of ' + totT + ' tasks'" in _SCRIPT)
    # Same trap as tr.taskfilter: with no script running every row is shown, so an
    # empty state that rendered by default would be a statement contradicted by
    # the table directly beneath it.
    check("c5: the empty state is hidden by default and revealed explicitly",
          "tr.norows{display:none}" in _CSS
          and 'class="norows"' in html_out
          and "'table-row' : 'none'" in _SCRIPT)
    check("c5: the way back out of an empty table does not live only INSIDE the "
          "empty table - the filter panel is drawn over that row",
          _markup(html_out).count('<button type="button" class="btn" data-clear')
          == 2
          and html_out.index("data-clear") < html_out.index('class="phases"'))
    check("c5: the view is a link, written with replaceState so it neither piles "
          "up history per keystroke nor throws on a file:// document",
          "history.replaceState(null, '', '#!'" in _SCRIPT
          and "try {" in _SCRIPT and "catch (e) {}" in _SCRIPT)
    check("c5: `#!` distinguishes filter state from the nav's plain fragments, "
          "and clearing filters strips only ours",
          "h.indexOf('#!') !== 0" in _SCRIPT
          and "(location.hash || '').indexOf('#!') === 0" in _SCRIPT)
    check("c5: the theme travels in the link only where this report owns the "
          "toggle - embedded, the host stamps data-theme on the same root",
          "if (themeBtn && parts.length) put('th'" in _SCRIPT)
    # The panel is emitted from the manifest, so a plan that records neither must
    # not ship an empty disclosure promising filters it cannot offer.
    _plain = {"meta": {}, "bugs": [], "phases": [
        {"id": "P1", "title": "x", "status": "pending",
         "tasks": [{"id": "P1.1", "title": "t", "status": "pending"}]}]}
    check("c5: a plan that records no models and no dates gets no panel at all",
          _filter_panel(_plain) == ""
          and 'class="fdetails"' not in render_html(
              _plain, _load_status_lib().rollup(_plain, [], []), "r", None))
    check("filters: a no-script reader is told why nothing filters",
          "<noscript>" in html_out)
    # Controls sit with what they act on.
    check("shell: document-level actions are in the top bar",
          html_out.index('id="audit-print"') < html_out.index('class="shell"'))
    check("shell: the phases filter sits on the phases table, not in the top bar - "
          "it does nothing while you are reading the usage charts",
          html_out.index('id="audit-q"') > html_out.index('class="shell"')
          and html_out.index('id="audit-q"') < html_out.index('class="phases"'))
    check("shell: prose pairs with the verdict on a wide screen instead of being "
          "set 130 characters wide",
          'class="topgrid"' in html_out and ".topgrid{" in _CSS
          and "min-width:78rem" in _CSS)
    check("shell: paper gets the document back - no bars, no nav, no section "
          "tools, and no disclosure arrow on a row already printed open",
          ".topbar,.snav,.toolbar,tr.taskfilter,.nojs,.tri{display:none!important}"
          in _CSS)
    # The no-script banner is screen-only: on paper there is no script to run and
    # no browser to open the file in, so it would be advice about nothing.
    check("shell: the no-script banner never reaches paper",
          ".nojs" in _CSS[_CSS.index("@media print"):])

    # ---- c6: the page belongs to the reader ------------------------------
    # Everything below is a string pin, and a string pin cannot tell whether a
    # print rule ever fires. The orientation itself is checked where it can be
    # measured - tools/check-report-interactive.mjs renders the report to PDF in
    # both orientations and reads the page box back out.
    _print = _CSS[_CSS.index("@page"):]
    check("c6: the stylesheet asks for a margin and does not dictate the sheet - "
          "`size` greys the print dialog's orientation control out",
          "@page{margin:1.4cm}" in _CSS and "size:" not in _print[:_print.index("}")])
    # The one place the reader was ever told a sheet size: the tooltip on the
    # control that opens the dialog. Scoped to that attribute rather than to the
    # whole document, which also carries the CSS comment explaining the removal
    # and a base64 blob in which "A4" turns up by chance.
    _ptitle = re.search(r'id="audit-print"[^>]*title="([^"]*)"', html_out)
    check("c6: the button no longer promises a sheet it does not choose - it "
          "says where the choice lives instead",
          bool(_ptitle) and "A4" not in _ptitle.group(1)
          and "orientation" in _ptitle.group(1))
    check("c6: a table spanning pages carries its column headers onto each one",
          "thead{display:table-header-group}" in _print)
    check("c6: no line stranded alone by a page break",
          "orphans:3;widows:3" in _print)
    check("c6: and no heading printed at the foot of a page, introducing nothing",
          "h1,h2,h3,h4,.sub{break-after:avoid;break-inside:avoid}" in _print)
    # Portrait inside a 1.4cm margin is ~688px == 43rem, so it MATCHES the 52rem
    # tablet rules while landscape (~1016px) does not. Allowing both orientations
    # is what made that divergence reachable.
    check("c6: portrait paper falls inside the tablet breakpoint, so the print "
          "sheet takes the small-screen scroll frame back off",
          ".tablewrap{overflow:visible" in _print
          and "table.phases,table.data{min-width:0" in _print
          and ".pmeta{position:static" in _print)
    # Paper prints the plan whole. Everything the screen's filter says about a
    # narrowed view is false on that page, and every one of those statements is
    # an inline style, so every one of them needs !important to take back.
    check("c6: paper prints every phase and every task, not the filtered "
          "leftovers - task rows under headings the filter hid",
          "tr.phase,tr.task,tr.taskdetail{display:table-row!important" in _print)
    check("c6: ...so the match badge and the empty state never reach it - "
          "'3 of 12 match' beside all twelve, 'no phase matched' above every one",
          ".pmatch,tr.norows{display:none!important}" in _print)
    check("c6: the pills that carry meaning in their fill print it - one tinted "
          "grammar now covers status, risk, holder, cost band and delta",
          ".chip,.fill,.rchip,.heldby,.bandpill,.dl,tr.phase>td::before,"
          in _CSS and ".rank .track i,.bud .track i{"
          "-webkit-print-color-adjust:exact;print-color-adjust:exact}" in _CSS)

    # ---- c7: the polish, and the one control that was unreachable ---------
    # The headline here is not polish. `.filterpanel` is hung out of flow at
    # `min-width:32rem`, and MIN-WIDTH BEATS MAX-WIDTH - so the `max-width:calc(
    # 100vw - 2rem)` written to cap it to the viewport never capped anything.
    # Measured on a 390px viewport before the fix: a 512px panel spanning x=-353
    # to x=159, both date inputs at -225..-100, i.e. entirely off the left of the
    # screen, with document.scrollWidth still 390 - so not even scrollable to.
    # The whole date-range filter was unreachable on a phone.
    #
    # These are string pins and they cannot see any of that: every one of them was
    # green while the panel was off-screen. The check with teeth is in
    # tools/check-report-interactive.mjs, which opens the panel at 390x780 and
    # asserts every control's box lies inside the viewport.
    _tablet = _CSS[_CSS.index("@media (max-width:52rem)"):]
    _tablet = _tablet[:_tablet.index("@media (max-width:40rem)")]
    check("c7: the filter panel comes back into the flow on a small screen, "
          "where out of flow it hung its date inputs off the side of the page",
          ".filterpanel{position:static;min-width:0;max-width:none" in _tablet)
    # In flow the panel's height is the BAR's height, and a sticky bar 62% of the
    # viewport tall is a control that covers the content it filters.
    check("c7: ...and the bar stops being sticky while it carries it, rather "
          "than pinning 62% of a phone screen over the table",
          ".sectools:has(.fdetails[open]){position:static}" in _tablet)
    _mobile = _CSS[_CSS.index("@media (max-width:40rem)"):]
    check("c7: a date field takes the row rather than being squeezed until the "
          "UA elides its year",
          ".frow input[type=date]{flex:1 1 100%" in _mobile)

    # Elevation that says "this is stuck", the same statement the top bar makes.
    # There is no selector for it, so the class is toggled from the ONE scroll
    # listener that already runs - and the condition is read out of the CSS rather
    # than recomputed, so where this bar sits has one definition.
    check("c7: the filter bar reads as a layer once it is stuck, not before",
          ".sectools.stuck{box-shadow:var(--shadow-sm)}" in _CSS
          and "transition:box-shadow var(--dur) var(--ease)" in _CSS)
    check("c7: ...decided from the bar's own resolved sticky offset, not from a "
          "scrollY threshold that goes wrong the moment anything above it moves",
          "getComputedStyle(sectools)" in _SCRIPT
          and "classList.toggle('stuck'" in _SCRIPT)
    # Two states this bar really reaches and a naive `top <= stickAt` gets wrong:
    # not sticky at all (narrow + panel open, above), and scrolled past with its
    # section, where the top is far ABOVE the stick line.
    check("c7: ...and it is not 'stuck' when it is not sticky, nor when the "
          "table has scrolled away and taken it with it",
          "cs.position === 'sticky'" in _SCRIPT and "sr.bottom > stickAt" in _SCRIPT)

    # A table row cannot be height-animated, so the reveal is opacity alone, and
    # it is a STARTING STYLE rather than a keyframe animation on purpose: an
    # unsupported at-rule is dropped with its block and the rows simply appear.
    # This sheet has already pinned two blocks at opacity 0 forever by animating a
    # reveal (`fadeUp`, when its easing token stopped resolving), which is why
    # check-report-interactive.mjs asserts every revealed row settles at 1.
    check("c7: an expanded task row fades in, so the reader can see which rows "
          "are the new ones",
          "@starting-style{tr.task{opacity:0}}" in _CSS
          and "tr.task{transition:opacity var(--dur) var(--ease)}" in _CSS)
    check("c7: ...on screen only - a transition caught mid-run would put a "
          "half-faded row on paper",
          "@media screen and (prefers-reduced-motion:no-preference){" in _CSS)

    # 168 heatmap cells and 11 rank rows, every one of them carrying a tooltip
    # the mark itself never advertised.
    check("c7: a heatmap cell says it is hoverable - and with an OUTLINE, which "
          "takes no space, so hovering one cell cannot nudge the other 167",
          ".hm i:hover{outline:2px solid var(--text);outline-offset:1px}" in _CSS
          and "cursor:help" in _CSS)
    check("c7: a rank row's bar brightens under the pointer, on the mark the "
          "tooltip is about",
          ".rank:hover .track i{filter:brightness(1.15)}" in _CSS)

    # The banner exists because a report is a file people SEND each other, and a
    # common way of opening one - an IDE preview pane - sandboxes inline <script>.
    # The page then renders completely, looks finished, and every interaction
    # silently does nothing. Reported as "the report is broken"; it took two
    # browsers, two origins, five viewports and real mouse input to establish that
    # the report was fine and the viewer was not. Now it says so itself.
    check("nojs: the banner is in the HTML, so it shows without any script",
          'id="audit-nojs"' in html_out)
    check("nojs: it names the likely cause and the one-step fix",
          "IDE preview" in html_out and "browser" in html_out)
    check("nojs: it says which features are affected, not just 'interactive'",
          all(w in html_out for w in ("Filtering", "search", "expanding")))
    # NOT inside the <noscript>. The report already had one ("Filtering and
    # collapsing need JavaScript"), and it was the right intent with a mechanism
    # that could not fire: <noscript> renders only when SCRIPTING IS DISABLED. An
    # IDE preview pane leaves scripting on and strips the inline <script>, so the
    # page ran no code and still showed no warning. That existing note stays - it
    # is correct for the disabled case and adds "every row is shown" - but it
    # cannot be the only signal.
    _banner = html_out[html_out.index('id="audit-nojs"'):]
    check("nojs: the banner renders unconditionally, not only when scripting is off",
          "<noscript" not in html_out[:html_out.index('id="audit-nojs"')]
          or html_out.index("</noscript>") > html_out.index('id="audit-nojs"'))
    check("nojs: and the older <noscript> note is still there for the disabled case",
          "<noscript>" in html_out)
    # Removal is the script's FIRST act, ahead of anything that can throw. If a
    # later line fails, the banner staying up is then true and useful.
    _first = _SCRIPT[:_SCRIPT.index("var count = document.getElementById")]
    check("nojs: the script removes it before any statement that could throw",
          "audit-nojs" in _first and "removeChild" in _first)
    check("nojs: removal is guarded, so a report rendered without it cannot throw",
          "if (_nojs && _nojs.parentNode)" in _SCRIPT)

    # --- table density follows the data ---------------------------------------
    _fresh = {"meta": {}, "bugs": [], "phases": [
        {"id": "P1", "title": "x", "status": "pending",
         "tasks": [{"id": "P1.1", "title": "t", "status": "pending"}]}]}
    check("cols: a plan with nothing done renders id/title/status and no more - "
          "six columns of em dashes describe the schema, not the work",
          _present_columns(_fresh) == [])
    _ado = json.loads(json.dumps(_fresh))
    _ado["phases"][0]["tasks"][0]["ado"] = {"id": 7}
    check("cols: ADO appears only for a repo that actually syncs to Azure DevOps",
          _present_columns(_ado) == ["ADO"])
    _done = json.loads(json.dumps(_fresh))
    _done["phases"][0]["tasks"][0].update(
        {"status": "done", "commit": "abc1234", "completedAt": "2026-01-02T00:00:00Z"})
    check("cols: a column appears as soon as ONE task fills it",
          _present_columns(_done) == ["commit", "done"])
    check("cols: a malformed task never silently removes a column",
          _present_columns({"phases": [{"tasks": [{"ado": "not-an-object"}]}]}) is not None)
    # The header, the cells and both colspans have to agree, or the table skews.
    # Counted over _markup(): report.js legitimately builds `<th>` rows for the
    # usage heatmap, and counting the whole document read its SOURCE as a
    # phantom column (F-C-1) -- the v0.36 `'<' + 'th>'` split in report.js
    # existed only to dodge this pin, and is gone now.
    _fh = render_html(_fresh, _load_status_lib().rollup(_fresh, [], []), "r", None)
    _fhm = _markup(_fh)
    check("cols: header, colspan and cells agree on the count",
          _fhm.count("<th>") == 3 and 'colspan="3"' in _fhm
          and "<th>ADO</th>" not in _fhm)
    # Scoped to the phases table: the bugs table has its own headers, and counting
    # <th> across the document measured both.
    _phead = html_out[html_out.index('<table class="phases"'):]
    _phead = _phead[:_phead.index("</thead>")]
    check("cols: the compact row carries the PRIMARY columns this plan has data "
          "for, and the rest of them live in the detail row rather than being "
          "dropped from the page",
          _phead.count("<th>") + _phead.count("<th data-col=")
          == 3 + len([c for c in _present_columns(manifest) if c in PRIMARY_COLS])
          and set(PRIMARY_COLS) < set(dict(_OPTIONAL_COLS)))
    check("cols: what the compact row leaves out, the detail row shows - a "
          "column moved off screen and nowhere else is a column deleted",
          all(k in _report_html._detail_row(
              {"id": "T", "model": "m", "outcome": {"descriptive": "d"},
               "ado": {"id": 7}},
              {"id": "P", "branch": "b"}, {}, 6, "active", "P")
              for k in (">model<", ">outcome<", ">work item<")))

    # --- sg: phase segmentation (D1, v0.36) -----------------------------------
    # On a large plan the Phases table is one long run. Segmentation groups the
    # rows into three blocks — active (in_progress/blocked), pending, done — so
    # the work in motion reads first, and the done run collapses into an
    # archive the reader can expand. The markup is pinned here; whether the
    # collapse and the toggle actually behave is asserted in a browser by
    # tools/check-report-interactive.mjs, because every string below survives a
    # dead script.
    _sgm = {"meta": {"title": "seg"}, "bugs": [], "phases": [
        {"id": "S1", "title": "first done", "status": "done",
         "tasks": [{"id": "S1.1", "title": "t", "status": "done",
                    "commit": "abc1234"}]},
        {"id": "S2", "title": "working", "status": "in_progress",
         "tasks": [{"id": "S2.1", "title": "t", "status": "in_progress"}]},
        {"id": "S3", "title": "queued", "status": "pending",
         "tasks": [{"id": "S3.1", "title": "t", "status": "pending"}]},
        {"id": "S4", "title": "stuck", "status": "blocked",
         "tasks": [{"id": "S4.1", "title": "t", "status": "blocked"}]}]}
    _sgh = render_html(_sgm, _lib.rollup(_sgm, [], []), "r", None)
    _sghm = _markup(_sgh)
    check("sg1 a mixed plan renders one seghead per non-empty segment, in "
          "active, pending, archived order",
          _sghm.count('<tr class="seghead"') == 3
          and _sgh.index('data-seg="active"') < _sgh.index('data-seg="pending"')
          < _sgh.index('data-seg="archived"'))
    check("sg2 phases are grouped under their segments - active rows first, "
          "then pending, then archived - whatever the manifest order",
          _sgh.index('id="phase-S2"') < _sgh.index('id="phase-S4"')
          < _sgh.index('id="phase-S3"') < _sgh.index('id="phase-S1"'))
    check("sg3 phase, taskfilter and task rows all carry data-seg, so the "
          "view gate and the print isolation can select whole segments",
          re.search(r'<tr class="phase" id="phase-S1"[^>]*data-seg="archived"',
                    _sgh) is not None
          and re.search(r'<tr class="taskfilter" data-phase="S1"[^>]*'
                        r'data-seg="archived"', _sgh) is not None
          and re.search(r'<tr class="task" data-phase="S1"[^>]*'
                        r'data-seg="archived"', _sgh) is not None)
    # vw (F-P-4): the archive toggle is gone. Which phases are on screen is a
    # NAMED view — active (the default) / archived / all — because "done rows
    # are hidden until you find the toggle" is a rule a reader has to discover,
    # and the one they discovered it through was an empty-looking plan. The
    # select is server-rendered (the chips rule) and starts on active.
    _blm = {"meta": {"title": "b"}, "bugs": [], "phases": [
        {"id": "B1", "title": "moving", "status": "in_progress", "tasks": [
            {"id": "B1.1", "title": "t", "status": "blocked"},
            {"id": "B1.2", "title": "t", "status": "cancelled"},
            {"id": "B1.3", "title": "t", "status": "done"}]}]}
    _blh = render_html(_blm, _lib.rollup(_blm, [], []), "r", None)
    check("bl a phase in progress says how many of its tasks are STUCK - the "
          "chip answers for the phase, and nothing answered for its contents",
          '<span class="pblocked"' in _blh and ">1 blocked<" in _blh)
    check("bl ...and how many were dropped, because a 1/3 bar on a phase whose "
          "other tasks were cancelled cannot say that by itself",
          '<span class="pcancelled"' in _blh and ">1 cancelled<" in _blh)
    check("bl a blocked PHASE does not repeat the word - its own chip carries it",
          '<span class="pblocked"' not in render_html(
              {"meta": {"title": "b"}, "bugs": [], "phases": [
                  {"id": "B2", "title": "stuck", "status": "blocked", "tasks": [
                      {"id": "B2.1", "title": "t", "status": "blocked"}]}]},
              _lib.rollup({"phases": [{"id": "B2", "status": "blocked", "tasks": [
                  {"id": "B2.1", "status": "blocked"}]}]}, [], []), "r", None))
    check("so the table says which column it is already sorted by, at load - "
          "the marker used to appear only on the first click, so a reader met "
          "an ordered table wearing no order at all",
          "if (initial && idx === 0)" in _SCRIPT
          and "th.setAttribute('aria-sort', 'ascending');" in _SCRIPT
          and "wireSort(grouped, true, true);" in _SCRIPT)
    check("vw1 the phases table carries a view select - active, archived, all - "
          "and no archive toggle survives anywhere",
          re.search(r'<select[^>]*id="audit-view"', _sgh) is not None
          and '<option value="active"' in _sgh
          and '<option value="archived"' in _sgh
          and '<option value="all"' in _sgh
          and "audit-arch" not in _sgh)
    check("vw2 the archive segment holds BOTH terminal states - a cancelled "
          "phase is finished, and filing it under pending would leave dropped "
          "work looking like work still to come",
          _report_html._seg_of("done") == "archived"
          and _report_html._seg_of("cancelled") == "archived"
          and _report_html._seg_of("blocked") == "active"
          and _report_html._seg_of("nonsense") == "pending")
    _sgd = {"meta": {"title": "alldone"}, "bugs": [], "phases": [
        {"id": "D1", "title": "a", "status": "done",
         "tasks": [{"id": "D1.1", "title": "t", "status": "done"}]},
        {"id": "D2", "title": "b", "status": "done",
         "tasks": [{"id": "D2.1", "title": "t", "status": "done"}]}]}
    _sgdh = render_html(_sgd, _lib.rollup(_sgd, [], []), "r", None)
    check("vw3 a plan with nothing active opens on ALL - the default view is "
          "'active', and a finished plan that greeted its reader with an empty "
          "table would be the archive toggle's own failure wearing a select",
          'data-defaultview="all"' in _sgdh
          and 'data-defaultview="active"' in _sgh
          and _markup(_sgdh).count('<tr class="seghead"') == 1
          and 'data-seg="archived"' in _sgdh)
    check("sg6 a single-segment plan still gets its one seghead - the home of "
          "the export controls",
          _fhm.count('<tr class="seghead"') == 1)
    check("vw4 report.js gates on the view, and a search that matches rows the "
          "view hides SAYS SO rather than reporting nothing - the old rule "
          "silently lifted the gate, which made the toggle a lie during a search",
          "viewMode" in _SCRIPT
          and "audit-view" in _SCRIPT
          and "archOpen" not in _SCRIPT
          and "data-outside" in _SCRIPT)
    check("vw5 the view survives a reload - in the shareable fragment first, "
          "and in localStorage when History is refused (a report opened over "
          "file:// is the common case, and that is where filters vanished)",
          "put('v', viewMode" in _SCRIPT
          and "localStorage" in _SCRIPT and "audit-view-" in _SCRIPT)
    check("sg8 print: a page break lands before every segment header except "
          "the first, and the header itself always prints",
          "tr.seghead{break-before:page;display:table-row!important}" in _print
          and "#phases tbody tr.seghead:first-child{break-before:auto}"
          in _print)
    check("sg9 the archive prints EXPANDED - the pinned whole-plan rule "
          "already forces every row onto paper, and the stylesheet argues the "
          "choice where the rules live",
          "tr.phase,tr.task,tr.taskdetail{display:table-row!important" in _print
          and "archive prints expanded" in _CSS.lower())

    # --- ex: per-segment export (D2, v0.36) -----------------------------------
    # CSV of the data, PNG of the charts (redrawn from the embedded data onto a
    # canvas - never DOM-to-canvas), and a print mode that isolates one
    # segment. All markup pinned here; the downloads themselves are driven in
    # tools/check-report-interactive.mjs, where the file that leaves the
    # browser is read back and checked.
    check("ex1 every seghead carries its CSV and Print controls, named by "
          "segment",
          _sghm.count("data-segcsv=") == 3 and _sghm.count("data-segprint=") == 3
          and 'data-segcsv="archived"' in _sghm
          and 'data-segprint="active"' in _sghm)
    check("ex2 the bugs table earns a CSV control beside its heading; a "
          "bugless plan renders none",
          'data-csv="bugs"' in _markup(html_out)
          and 'data-csv="bugs"' not in _sghm)
    check("ex3 the CSV leaves as RFC 4180 with Excel's BOM, through the same "
          "blob-anchor download the .md button uses",
          "replace(/\"/g, '\"\"')" in _SCRIPT and "\\ufeff" in _SCRIPT
          and "text/csv;charset=utf-8" in _SCRIPT)
    check("ex4 the chart exports redraw from data onto a canvas and leave as "
          "PNG",
          "toDataURL('image/png')" in _SCRIPT
          and 'data-png="trend"' in uh and 'data-png="heatmap"' in uh)
    check("ex5 print-to-PDF per segment: the button stamps body[data-printseg], "
          "print CSS isolates that segment, and afterprint restores the page",
          "data-printseg" in _SCRIPT
          and "body[data-printseg] .content>*:not(#phases){display:none"
              "!important}" in _print
          and 'body[data-printseg="active"]' in _print
          and 'body[data-printseg="pending"]' in _print
          and 'body[data-printseg="archived"]' in _print
          and "removeAttribute('data-printseg')" in _SCRIPT)
    check("ex6 the export controls never reach paper",
          ".segx,.secx{display:none!important}" in _print)

    # --- ow: advisory area owner chips (D4, v0.36) ----------------------------
    # meta.areas[tag].owner (v0.34, advisory) surfaces wherever the report
    # shows a tag: a small suffix on the tag chip, and a title on the filter
    # chip and the global select option - the same `owner: <who>` wording the
    # panel's area select already uses. Advisory only; an area with no owner
    # (or an explicit null) shows exactly what it always did.
    _mo = json.loads(json.dumps(manifest))
    _mo["phases"][0]["area"] = ["api", "web"]
    _mo["meta"]["areas"] = {"api": {"owner": "ana@x.io"},
                            "web": {"owner": None},
                            "infra": {"description": "unused"}}
    _moh = render_html(_mo, _lib.rollup(_mo, [], []), "audit-report", None)
    check("ow1 a registered owner rides the tag as a small advisory suffix on "
          "the phase row, with the panel's exact title wording",
          '<span class="area-tag" title="owner: ana@x.io">api'
          '<span class="aown">' in _moh)
    check("ow2 the filter chip and the global select option say the same "
          "through their titles",
          'data-a="api" title="owner: ana@x.io"' in _moh
          and '<option value="api" title="owner: ana@x.io">api</option>' in _moh)
    check("ow3 an area with no owner - or an explicit null - shows exactly "
          "what it always did",
          '<span class="area-tag">web</span>' in _moh
          and 'title="owner:' not in _mah)
    check("ow4 the Ready-now list wears the same suffix on its tags",
          '<dl class="ready">' in _moh
          and 'title="owner: ana@x.io"'
              in _moh[_moh.index('<dl class="ready">'):])
    _mx = json.loads(json.dumps(_mo))
    _mx["meta"]["areas"] = {"api": {"owner": '<script>alert(1)</script>'}}
    check("ow5 a hostile owner is escaped before it reaches an attribute",
          "<script>alert" not in render_html(
              _mx, _lib.rollup(_mx, [], []), "r", None).replace(_SCRIPT, ""))

    # --- scale: the filter must not re-query the DOM per phase ----------------
    # Measured on a 200-phase / 4000-task report: one keystroke took 145ms and a
    # five-character burst blocked the main thread for 508ms, because refresh()
    # called querySelectorAll ONCE PER PHASE inside its own loop over phases.
    _body = _SCRIPT[_SCRIPT.index("function refresh()"):]
    _body = _body[:_body.index("\n  function ", 10)] if "\n  function " in _body[10:] else _body
    check("scale: refresh() runs no DOM query per phase - that loop is O(phases x "
          "rows) and it ran on every keystroke",
          "querySelectorAll" not in _body and "querySelector(" not in _body)
    check("scale: the phase->tasks index is built once, up front",
          "var TASKS = {}, TFROW = {};" in _SCRIPT)
    check("scale: row text is lowercased once and kept, not re-derived per keystroke",
          "r.__auditText" in _SCRIPT)
    check("scale: sorting copies the index before ordering it, so the index is "
          "never left permuted behind the table",
          "tasksOf(pid).slice().sort(cmp)" in _SCRIPT)
    check("scale: typing is debounced - five characters is one pass, not five",
          "setTimeout(function () { qTimer = null; refresh(); }, 90)" in _SCRIPT)
    check("scale: Enter and Escape bypass the debounce, because they are decisions "
          "rather than typing",
          "ev.key !== 'Enter' && ev.key !== 'Escape'" in _SCRIPT)

    # --- fragment mode (publishable as a Claude Code Artifact) --------------
    # The host wraps what it is given in its own doctype/head/body, so every one
    # of these tags would nest a second document inside the first.
    _frc = main([mp, "--out-dir", tmp, "--format", "artifact"])
    _fp = os.path.join(tmp, "audit-report.artifact.html")
    check("artifact: --format artifact exits 0 and writes its own file",
          _frc == 0 and os.path.getsize(_fp) > 0)
    check("artifact: it never overwrites the standalone .html "
          "(that file is what CI diffs the live demo against)",
          os.path.getsize(hp) > 0 and open(hp, encoding="utf-8").read() == html_out)
    frag = open(_fp, encoding="utf-8").read()
    for tag in ("<!doctype", "<html", "</html>", "<meta charset",
                "<meta name=\"viewport\""):
        check("artifact: fragment carries no %s" % tag, tag not in frag.lower())
    check("artifact: fragment keeps the title (the host reads it to name the page)",
          "<title>" in frag)
    check("artifact: fragment keeps the whole stylesheet inline "
          "(a CSP blocks every external host, so a linked one would not load)",
          "<style>" in frag and ":root{" in frag)
    # Tags, not the substring " src=": this fixture's desiredOutcome deliberately
    # contains `<img src=x onerror=...>`, which the report ESCAPES. A naive
    # substring test fails on the very input that proves the escaping works.
    check("artifact: fragment loads nothing over the network "
          "(a CSP blocks every external host, so a resource tag is a blank space)",
          not any(t in frag.lower() for t in
                  ("<script src", "<img ", "<link ", "<iframe", "url(http")))
    check("artifact: and the hostile fixture is still escaped, not stripped",
          "&lt;img src=x" in frag)
    check("artifact: fragment drops the theme toggle, since the host owns the "
          "theme and stamps the same data-theme attribute",
          'id="audit-theme"' not in frag)
    check("artifact: the standalone report KEEPS its toggle "
          "(the fragment is the exception, not a rewrite)",
          'id="audit-theme"' in html_out)
    check("artifact: the persisted theme is reinstated only where the toggle "
          "exists, so an embedded report cannot override its host",
          "if (themeBtn) {" in _SCRIPT)
    check("artifact: the report body itself is unchanged - same phases table, "
          "same usage section, same markdown twin",
          '<table class="phases"' in frag
          and ("AUDIT_MD_B64" in frag) == ("AUDIT_MD_B64" in html_out))
    check("artifact: wide tables scroll inside their own box, not the page",
          ".tablewrap{" in frag and "overflow-x:auto" in frag)
    check("artifact: the fragment answers to the host's theme in BOTH directions",
          'data-theme="dark"' in frag and 'data-theme="light"' in frag)
    check("a3 sortable headers are focusable and announce their state",
          "aria-sort" in _SCRIPT and "'tabindex', '0'" in _SCRIPT
          and "'role', 'button'" in _SCRIPT)
    check("a4 sorting is operable from the keyboard, not click-only",
          "keydown" in _SCRIPT and "'Enter'" in _SCRIPT)
    check("a5 aria-sort is reset on the other columns, not left stale",
          _SCRIPT.count("aria-sort") >= 3)
    check("a6 filter chips expose their pressed state rather than colour alone",
          "aria-pressed" in _SCRIPT)
    check("a7 the per-phase task filter is revealed with an explicit display "
          "(clearing it would hand the row back to `tr.taskfilter{display:none}`)",
          "'table-row'" in _SCRIPT)
    check("a8 the rule that made it invisible is still the one being overridden",
          "tr.taskfilter{display:none}" in _CSS)
    check("a9 only headers that sort are styled as controls "
          "(three tables showed a pointer on headers that did nothing)",
          'thead th[role="button"]{cursor:pointer' in _CSS
          and "border-bottom:1px solid var(--border)}" in _CSS)
    check("a10 a bare thead th no longer claims to be clickable",
          not re.search(r"thead th\{[^}]*cursor:pointer", _CSS))
    check("a11 keyboard focus on a sortable header is visible",
          'thead th[role="button"]:focus-visible' in _CSS)

    check("u24 the hover layer re-renders the mark's own title — never a second "
          "copy of the numbers — so JS-off keeps the native tooltip",
          "__tip" in uh and "removeAttribute('title')" in uh
          and uh.count("split('\\t')") == 1)
    check("u24b hover is delegated, not one listener per mark",
          uh.count("addEventListener('mouseover'") == 1
          and "mouseenter" not in uh)
    check("u24c the floating tooltip is suppressed for print",
          "@media print{.rtip{display:none!important}" in uh)
    check("m1 md contains phase heading and escaped pipe",
          "## P1" in md_out and "a\\|bug" in md_out)
    check("m2 md table row for the done task",
          "| P1.1 | done task | done |" in md_out and "#42" in md_out)
    check("h1 progress bar rendered", 'class="bar"' in html_out
          and "1/2" in html_out)
    check("h2 overall header present (html + md)",
          'class="overall"' in html_out and "**Overall:**" in md_out
          and "phases signed off" in html_out)
    check("h3 task outcome shown + escaped", "did the thing cleanly" in html_out)
    check("h4 phase branch/mergedAt meta shown",
          "branch audit/p1-x" in html_out and "merged 2026-07-09" in html_out)
    check("h5 html has doctype + charset + title (standalone render, tab name)",
          html_out.lstrip().lower().startswith("<!doctype html>")
          and 'charset="utf-8"' in html_out and "<title>" in html_out)
    check("h6 collapsible grouped table + separate phase/task filters + script",
          'class="phases"' in html_out and 'tr class="phase"' in html_out
          and 'tr class="task"' in html_out and 'tr class="taskfilter"' in html_out
          and "aria-expanded" in html_out and 'id="audit-q"' in html_out
          and 'id="audit-phase-status"' in html_out and 'id="audit-expand"' in html_out
          and "<script>" in html_out and "addEventListener" in html_out)
    check("h7 phase + task rows carry data-phase/data-status (grouping + filter)",
          'data-phase="P1"' in html_out and 'data-status="done"' in html_out
          and 'data-status="pending"' in html_out and 'data-status="open"' in html_out)
    check("h8 AI summary box rendered + escaped (from meta.reportSummary)",
          '<div class="summary">' in html_out
          and "closed all criticals &amp; shipped" in html_out)
    check("h9 PDF (print) + Download .md buttons + embedded md + print CSS",
          'id="audit-print"' in html_out and 'id="audit-dl-md"' in html_out
          and 'window.AUDIT_MD_B64="' in html_out and "@page" in html_out
          and "@media print" in html_out)
    check("h10 done column: completion stamp to the MINUTE, its zone named once "
          "in the header, and both full timestamps still on hover",
          '<th data-col="done">done <span class="muted">UTC</span></th>' in html_out
          and "2026-07-09 09:30" in html_out
          and 'title="started 2026-07-09T08:00:00Z · completed '
          '2026-07-09T09:30:00Z"' in html_out)
    check("h11 risk chip (data-risk) + status token drives rail/chip",
          'class="rchip" data-risk="high"' in html_out and ">high</span>" in html_out
          and 'class="chip" data-status="done"' in html_out
          and '[data-status="blocked"]' in html_out and "--st-blocked" in html_out)
    check("h12 theme toggle + design tokens + dark + reduced-motion present",
          'id="audit-theme"' in html_out and ":root{" in html_out
          and "--accent" in html_out and "prefers-color-scheme:dark" in html_out
          and "prefers-reduced-motion" in html_out)
    # Counts the CLASS, not one exact tag: the phases wrapper gained an id when it
    # became a nav anchor, and an assertion that breaks on an added attribute was
    # testing the markup rather than the guarantee (both wide tables scroll in
    # their own box).
    check("h13 responsive: wide tables wrapped + mobile breakpoint",
          _markup(html_out).count('class="tablewrap"') == 2
          and ".tablewrap{overflow-x:auto" in html_out
          and "@media (max-width:40rem)" in html_out)
    check("m4 markdown twin has the done column with the completion date",
          "| done | ADO |" in md_out and "2026-07-09" in md_out)
    check("r1 ready list rendered", "P1.2" in md_out)

    rc = main([mp, "--format", "nope"])
    check("c3 bad format is usage error (exit 2)", rc == 2)
    rc = main([os.path.join(tmp, "missing.json")])
    check("c4 unreadable manifest (exit 2)", rc == 2)
    arr = os.path.join(tmp, "arr.json")
    with open(arr, "w", encoding="utf-8") as fh:
        json.dump(["not", "an", "object"], fh)
    check("c5 non-object JSON root is a usage error (exit 2)", main([arr]) == 2)
    # --summary-file injects the summary WITHOUT a reportSummary in the manifest
    sf = os.path.join(tmp, "sum.txt")
    with open(sf, "w", encoding="utf-8") as fh:
        fh.write("Injected via CLI summary file.")
    m2 = json.loads(json.dumps(manifest))
    m2["meta"].pop("reportSummary", None)
    mp2 = os.path.join(tmp, "m2.json")
    with open(mp2, "w", encoding="utf-8") as fh:
        json.dump(m2, fh)
    main([mp2, "--out-dir", tmp, "--format", "html", "--summary-file", sf])
    inj = open(os.path.join(tmp, "audit-report.html"), encoding="utf-8").read()
    check("c6 --summary-file injects the Summary box (manifest untouched)",
          '<div class="summary">' in inj and "Injected via CLI summary file." in inj)

    # --basename controls the output filenames AND the Download-.md name
    bdir = os.path.join(tmp, "bn")
    main([mp, "--out-dir", bdir, "--basename", "q3-audit"])
    bn_html = os.path.join(bdir, "q3-audit.html")
    check("c7 --basename writes q3-audit.html/.md + sets download name",
          os.path.exists(bn_html) and os.path.exists(os.path.join(bdir, "q3-audit.md"))
          and 'window.AUDIT_MD_NAME="q3-audit.md"'
          in open(bn_html, encoding="utf-8").read())
    # meta.reportBasename is honored, and a path-y value is sanitized to a bare
    # name INSIDE out_dir (the leading ../../ is dropped, not traversed).
    mb = json.loads(json.dumps(manifest))
    mb["meta"]["reportBasename"] = "../../etc/passwd"
    mpb = os.path.join(tmp, "mb.json")
    with open(mpb, "w", encoding="utf-8") as fh:
        json.dump(mb, fh)
    bdir2 = os.path.join(tmp, "bn2")
    main([mpb, "--out-dir", bdir2, "--format", "html"])
    check("c8 meta.reportBasename sanitized to a bare name (no path escape)",
          os.path.exists(os.path.join(bdir2, "passwd.html"))
          and not os.path.exists(os.path.join(bdir2, "audit-report.html"))
          and not os.path.exists(os.path.join(tmp, "etc", "passwd.html")))

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
