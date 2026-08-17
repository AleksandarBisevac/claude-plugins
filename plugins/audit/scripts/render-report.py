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

This module carries no `--selftest` of its own any more; its 239 cases live in
`plugins/audit/tests/test_render_report.py`, byte-identical labels and all - see
`plugins/audit/tests/_harness.py`. `import re` and `import time` went with them:
every use of either in this file was inside that suite. `--bench` stayed - the
benchmark is production code somebody runs, and only the `bn` cases moved.
"""
import json
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


# --- bench ----------------------------------------------------------------------
# WHY, AND WHY IT IS NOT A GATE. Until this landed there was not one `perf_counter`
# or benchmark in the repository, while several comments stated measured costs that
# nobody — including their author — could produce again. This prints numbers a human
# can run twice and compare; it is deliberately NOT a CI threshold, because a shared
# runner's noise floor is wider than the regressions worth catching and a gate that
# flaps teaches people to ignore it.
#
# PHASES SEPARATELY, NEVER ONE TOTAL. Earlier profiling claimed the ledger analytics
# dominate the HTML build several times over. Whether that is still true is exactly
# what a single total would hide — and the two grow with DIFFERENT things: the ledger
# pass with rows, everything else with the plan. So each phase is timed on its own
# and printed against the denominator that makes it comparable across scales.
#
# BEST-OF-N, NOT THE MEAN, and the definition of that has ONE home:
# `_usage_analytics._time_best`. See the note at the call site for why it is reached
# the way it is.
_BENCH_SCALES = ((10, 5), (50, 20))
_BENCH_REPEATS = 3

# Which denominator makes each phase comparable across scales. The ledger pass grows
# with ROWS; everything else grows with the PLAN. `bn5` pins that this table covers
# exactly the phases `_bench_phases` returns, so a phase added later without a
# denominator fails by name instead of printing a bare millisecond figure.
_BENCH_PER = {"validate": "task", "rollup": "task", "usage load": "row",
              "html": "task", "markdown": "task"}


def _bench_fixture(out_dir, phases, tasks):
    """Build the demo manifest AND a matching ledger in `out_dir`, by RUNNING the
    two generators. Returns {manifestPath, tasks, rows, ledgerDir}.

    `gen-demo-manifest.py` and `gen-demo-usage.py` already produce exactly this
    fixture, deterministically — hand-rolling a third one here would be a fixture
    that nothing else validates. They are run as COMMANDS, the same way ci.yml and
    tools/capture-screenshots.mjs build the demo, for two reasons:

      * both are entry points at layer 7, the same layer as this file, so loading
        one through `_loader` would add a peer edge to `_deps.KNOWN_LAYER_DEBT` —
        a list whose whole contract is that it may only ever SHRINK. A change that
        adds measurement must not enlarge the module graph;
      * out of process, the fixture build cannot contaminate what it is a fixture
        for: its imports, its loader cache and its garbage stay out of the very
        process whose timings this reports.

    A generator that fails raises with its stderr attached rather than leaving the
    caller to time an empty directory and report a suspiciously fast render.
    """
    import subprocess
    gen_manifest = os.path.join(_output.SCRIPTS_DIR, "gen-demo-manifest.py")
    gen_usage = os.path.join(_output.SCRIPTS_DIR, "gen-demo-usage.py")
    manifest_path = os.path.join(out_dir, "audit-plan.json")
    # The generators do not read it, but the bench must never be one environment
    # variable away from resolving a ledger somewhere else on this machine.
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    for cmd in ([sys.executable, gen_manifest, out_dir,
                 "--phases", str(phases), "--tasks", str(tasks)],
                [sys.executable, gen_usage, manifest_path]):
        proc = subprocess.run(cmd, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=env)
        if proc.returncode != 0:
            raise RuntimeError(
                "%s exited %d: %s" % (os.path.basename(cmd[1]), proc.returncode,
                                      (proc.stderr or b"").decode("utf-8",
                                                                  "replace").strip()))
    ledger_dir = os.path.join(out_dir, ".claude", "usage")
    rows = 0
    for name in sorted(os.listdir(ledger_dir)):
        if not name.endswith(".jsonl"):
            continue
        with open(os.path.join(ledger_dir, name), "r", encoding="utf-8") as fh:
            rows += sum(1 for line in fh if line.strip())
    return {"manifestPath": manifest_path, "ledgerDir": ledger_dir,
            "tasks": phases * tasks, "rows": rows}


def _bench_phases(manifest, manifest_path, project_dir):
    """`(label, thunk)` for the five phases of a render, in the order `main()`
    runs them.

    Each thunk hands its output to the next through one dict, because that is what
    `main()` does: the summary is rollup's output and both writers need it. Timing
    them separately is the whole point — see the section note above.

    `load_usage` is handed `project_dir` EXPLICITLY. Left to itself it falls back to
    `CLAUDE_PROJECT_DIR`, which every Claude Code session sets to the real
    repository — the bench would then load, time and report THIS repo's own live
    ledger instead of the fixture's, and the number would look perfectly reasonable.
    """
    lib = _load_status_lib()
    vm = lib._load_validator()
    out = {}

    def _validate():
        out["findings"], out["warnings"] = vm.validate(manifest)
        return out["findings"]

    def _rollup():
        out["summary"] = lib.rollup(manifest, out.get("findings") or [],
                                    out.get("warnings") or [])
        return out["summary"]

    def _usage():
        out["usage"] = load_usage(manifest, manifest_path,
                                  project_dir=project_dir)
        return out["usage"]

    def _html():
        return render_html(manifest, out["summary"], "bench", out["usage"])

    def _markdown():
        return render_md(manifest, out["summary"], out["usage"])

    return (("validate", _validate), ("rollup", _rollup), ("usage load", _usage),
            ("html", _html), ("markdown", _markdown))


def _bench(scales=None, repeats=None):
    """Time a full render at each scale. 0 when every scale ran, 1 if one failed.

    The fixture is built in a temp directory and DELETED before this returns, at
    every scale, including the failing ones — a bench that leaves a fixture behind
    is a bench whose next run measures something else.
    """
    import shutil
    import tempfile
    # ONE definition of best-of-N, in `_usage_analytics`, beside the note that
    # argues for the minimum over the mean. A second copy here is how two benches
    # start disagreeing about what "the time" means — the same way this repo's
    # token formatter drifted once it existed twice. Reached through `_loader`
    # rather than by `import` for a reason worth stating: a static import would
    # change `_deps.render()`'s module map, which is byte-pinned to a fence in
    # PLUGIN-BUILD-GUIDE.md, and a measurement-only change must not rewrite the
    # architecture guide. The runtime edge is L7 -> L2, strictly downward, so the
    # layer rule is satisfied either way.
    analytics = _loader.load_script("_usage_analytics.py",
                                    modname="usage_analytics_bench")
    scales = scales if scales is not None else _BENCH_SCALES
    repeats = repeats if repeats is not None else _BENCH_REPEATS
    print("render-report --bench  (python %s on %s)"
          % (sys.version.split()[0], sys.platform))
    print("fixture:  gen-demo-manifest.py + gen-demo-usage.py, run as commands "
          "into a temp dir that is deleted before this exits")
    print("timing:   best of %d runs per phase - the MINIMUM, not the mean, "
          "because other load can only make a call slower" % repeats)
    rc = 0
    for phases, tasks in scales:
        tmp = tempfile.mkdtemp(prefix="render-report-bench-")
        try:
            fx = _bench_fixture(tmp, phases, tasks)
            manifest = _mio.load_manifest(fx["manifestPath"])
            print("")
            print("%d phases x %d tasks (%s tasks, %s ledger rows)"
                  % (phases, tasks, "{:,}".format(fx["tasks"]),
                     "{:,}".format(fx["rows"])))
            seen = {}
            for label, thunk in _bench_phases(manifest, fx["manifestPath"], tmp):
                seconds, _ = analytics._time_best(thunk, repeats)
                seen[label] = seconds
                per = fx["rows"] if _BENCH_PER[label] == "row" else fx["tasks"]
                print("  %-11s %8.2f ms  (%7.2f us/%s)"
                      % (label, seconds * 1e3, seconds * 1e6 / max(1, per),
                         _BENCH_PER[label]))
            total = sum(seen.values())
            # A SUM of minima, not a measured whole-render time - said so rather
            # than printed as if one run had been observed taking it.
            print("  %-11s %8.2f ms  (%7.2f us/task)"
                  % ("sum of min", total * 1e3,
                     total * 1e6 / max(1, fx["tasks"])))
            if seen.get("html"):
                print("  the ledger pass is %.1fx the HTML build"
                      % (seen["usage load"] / seen["html"]))
        except Exception as exc:             # a failed scale must not read as fast
            sys.stderr.write("ERROR: bench failed at %d x %d: %s\n"
                             % (phases, tasks, exc))
            rc = 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return rc


def _mode(argv):
    """Which mode the flags ask for: 'selftest', 'bench' or 'render'.

    `--selftest` WINS over `--bench` when both are given. CI runs `--selftest` on
    every `.py` in the tree on two platforms; a suite that could turn into a
    benchmark run because a stray flag came along would be paid for on every push.
    A mode that can be entered by accident will be.
    """
    if "--selftest" in argv:
        return "selftest"
    if "--bench" in argv:
        return "bench"
    return "render"


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    _MODE = _mode(sys.argv[1:])
    if _MODE == "selftest":
        # Answers rather than exits silently: `--selftest` is what every other
        # file here still accepts, so nothing would tell a reader whether this
        # one ran nothing or has nothing. It deliberately does NOT print the
        # suite contract - that literal is how `_output.selftest_coverage()`
        # tells an inline suite from a migrated one. `--bench` still runs the
        # benchmark: that is production code, not a suite.
        print("render-report.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_render_report.py - run that file "
              "instead. --bench still works here.")
        raise SystemExit(0)
    if _MODE == "bench":
        sys.exit(_bench())
    sys.exit(main(sys.argv[1:]))
