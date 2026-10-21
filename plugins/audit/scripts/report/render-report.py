#!/usr/bin/env python3
"""
Render the audit manifest as a self-contained HTML + Markdown report.

Publishable as a CI artifact (see docs/examples/azure-pipelines.yml) or opened
locally — the HTML inlines all CSS and fetches NOTHING. Every string from the
manifest is escaped (manifest content is untrusted input), and ado/link URLs
render as links only when they are http(s).

Usage:
  render-report.py [<manifest>] [--out-dir DIR] [--format html|md|both|artifact]
                                [--summary-file PATH] [--basename NAME]

  --format artifact writes <basename>.artifact.html: the same report with no
  document wrapper, for a host that supplies its own (a Claude Code Artifact).

With no <manifest>, the plan is found by `_manifest_io.resolve_manifest`: the
project's (CLAUDE_PROJECT_DIR, else the cwd) configured manifestPath, else
docs/audit/audit-plan.json; when neither exists it exits 2 naming where it looked.

Writes <basename>.html / <basename>.md into --out-dir (default: the manifest's
own directory) and prints the paths. `basename` is `--basename` › the manifest's
`meta.reportBasename` › `audit-report`, sanitized to [A-Za-z0-9-_].
Exit codes: 0 ok · 2 usage error / unreadable manifest.

WHAT IS STILL HERE AFTER THE SPLITS. The document itself is
`_report_page.render_html` and its Markdown twin is `_report_md.render_md`
(P13.3); the fragments they glue are `_report_html` (P13.1) and `_report_usage`
(P13.2). This file keeps `main()` — the arguments, the manifest read, the theme
resolve, the files it writes — and `_verdict`, which stays because the verdict at
the top of the report is the CLI gate's own word: it is computed here and INJECTED
into the page rather than composed a second time inside it (see the
`# --- the gate verdict ---` section).

It also keeps the cases, and that is the honest shape rather than a
leftover. They render a report through `main()` into a temp directory and then
assert about the emitted DOCUMENT — its markup, the ORDER things are emitted in,
the stylesheet, the embedded script. A fragment module cannot produce one, so
splitting those cases by whichever function happens to emit each string would
have left two suites and no complete one.

This module carries no `--selftest` of its own any more; its cases live in
`tests/test_render_report.py`, byte-identical labels and all - see
`tests/_harness.py`. `import re` and `import time` went with them:
every use of either in this file was inside that suite. The `--bench` mode left
too: the benchmark is `tools/bench-report.py` in the source repository now.
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

import _fmt                  # noqa: E402  (the no-domain number/text formatters, incl. plural)
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
import _status_facts          # noqa: E402  (the gate's conditions + verdict)
# The manifest rules, imported straight. Both call sites below used to spell
# `_load_status_lib()._load_validator()` — reaching the validator THROUGH the
# status command, because that was the only module that already knew how to load
# a hyphenated entry point. Both of those are plain low modules now, so the
# hop is gone along with the two `KNOWN_LAYER_DEBT` edges that paid for it.
import _manifest_rules        # noqa: E402  (the manifest rules)
import _report_ui             # noqa: E402  (CSS/SCRIPT, off disk as real files under ui/)
import _report_html           # noqa: E402  (HTML fragment builders: escaping, chips, cells, filter panel)
import _report_usage          # noqa: E402  (the Usage section: ledger load, charts, markdown twin)
import _evidence_view         # noqa: E402  (the test-execution record: the only read of it)
import _evidence_io           # noqa: E402  (WHEN this plan could first have recorded)
import _invariants            # noqa: E402  (git_root_for: where the third place asks ancestry)
import _manifest_vocab        # noqa: E402  (FULL_STATUS_UNKNOWN and the one ledger-read sentence)
import _report_md             # noqa: E402  (the Markdown twin)
import _report_page           # noqa: E402  (the whole document: vocab, table, render_html)
import _areas                 # noqa: E402  (plan_skill_refs: which names this plan uses)
import _live_copy             # noqa: E402  (which copy holds a phase in flight live)


# --- module aliases (CSS/SCRIPT, page + fragment + usage re-exports) ------------
# Chip and pipeline-rail colors live in the report's CSS theme tokens (see _CSS),
# keyed off the `data-status` / `data-risk` attributes the markup carries — so a
# single token set themes every status/risk consistently in both light and dark.
_CSS = _report_ui.CSS

# Inline, self-contained (no external fetch) filter/sort/search over the report
# tables. Progressive enhancement: the report is fully readable with JS off.
_SCRIPT = _report_ui.SCRIPT


def _load_status_lib():
    """`_status_facts` — the gate's own conditions and verdict.

    A plain import now, not a `_loader.load_script("audit-status.py")`: that was
    this file loading another entry point, one of the edges `_deps.KNOWN_LAYER_DEBT`
    recorded, and it pulled ~600 lines of terminal rendering in behind one call
    to `evaluate_gate`. Kept as a function because `_verdict` below reads it as
    "the module that owns the gate" and the suite substitutes it."""
    return _status_facts


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




# The Usage section lives in _report_usage.py (P13.2); `load_usage` is the half
# this file still calls, to hand the ledger to the page.
load_usage = _report_usage.load_usage

# ...and the test-execution record, on exactly the same footing: an entry point
# reads the disk and hands the result down, so nothing below this file has to
# know where a ledger lives. It answers None when the plan points at no run, and
# the page then renders as it did before any of this existed.
load_evidence = _evidence_view.load_evidence

# ...and WHEN this plan could first have recorded a run at all, on that same
# footing again. `_status_facts` computes the rollup and may not read it: that
# module is `_evidence_io`'s layer-mate, so the boundary is an entry point's job
# to fetch and hand down, exactly like the two loads above. `_evidence_view`
# reaches the same ledger for the run VIEWS and answers None when the plan points
# at nothing, which is why the boundary cannot be taken off it - a plan with no
# pointers anywhere is precisely the plan whose boundary matters most.
boundary_for = _evidence_io.boundary_for


def _full_run_block(manifest, manifest_path, project):
    """Per-MERGED-phase third-place verdict, or `{}` when this plan names no
    `meta.fullGate` at all - the report's own read of the SAME question
    `audit-status.py`'s `full_run_block` and `_panel_composition._phase_full_run`
    ask, so the word a reader sees here cannot disagree with the one they see
    on the CLI or the panel.

    MERGED IS `_evidence_io.merged_phase` - `mergedAt` set and an id - the one
    predicate the status, the panel and the doctor call too. An effective
    status of done is NOT this: a phase can be done without ever having
    merged, and a phase reads merged before its status catches up to done.

    THE ONE RESOLUTION OF THE GATE and THE ONE READ OF THE LEDGER, exactly as
    `audit-status.py`'s docstring states them - this file re-derives neither, it
    only asks the SAME two questions a second time because the report is a
    second process. `head` is added beside `full_status`'s own `answer`/`basis`/
    `runId` for a WHOLE answer only, so `_report_html._verified_line` can name
    the commit a whole-bearing run's head resolved to without reading the
    ledger itself; `mergedHead`, `phaseId` and `testGateBasis` are added on
    every entry so the renderer needs nothing from `manifest` either.

    A FAILURE IS AN UNKNOWN ON EVERY MERGED PHASE, never a block no phase id is
    a key of - `_full_run_unknown` below, and `audit-status.py`'s own
    `full_run_block` docstring for why.
    """
    # The runnable full gate: review-only entries are never run, so a run is
    # never counted against them, and a fullGate of only those is no third place.
    full_commands = _evidence_io.full_gate_commands(manifest)
    if not full_commands:
        return {}
    try:
        project_root, config = _evidence_io.project_config_for(
            manifest_path, project)
        git_root = _invariants.git_root_for(manifest, project_root)
    except Exception as exc:                       # defensive; see the docstring
        return _full_run_unknown(manifest,
                                 _manifest_vocab.LEDGER_LOCATION_FAILED % (exc,))
    try:
        rows = _evidence_io.read_rows(project_root, config=config)["rows"]
    except Exception as exc:                       # defensive; see the docstring
        return _full_run_unknown(manifest,
                                 _manifest_vocab.LEDGER_READ_FAILED % (exc,))
    out = {}
    for p in (manifest.get("phases") or []):
        if not _evidence_io.merged_phase(p):
            continue
        res = dict(_evidence_io.full_status(rows, p, git_root, full_commands))
        res["mergedHead"] = p.get("mergedHead")
        res["phaseId"] = p.get("id")
        res["testGateBasis"] = p.get("testGateBasis")
        run_id = res.get("runId")
        if run_id:
            run_row = _evidence_io.row_by_run(rows, run_id)
            if isinstance(run_row, dict):
                head = (run_row.get("testedState") or {}).get("head")
                if head:
                    res["head"] = str(head)
        out[p["id"]] = res
    return out


def _full_run_unknown(manifest, basis):
    """Every MERGED phase answering UNKNOWN for `basis`, carrying the keys
    `_report_html._verified_line` reads, so a failure renders as
    "unknown - <basis>" on each merged phase rather than as no line at all -
    the silence a plan with no `meta.fullGate` gets. The panel answers the same
    failure the same way."""
    return dict((p["id"], {"answer": _manifest_vocab.FULL_STATUS_UNKNOWN,
                           "basis": basis, "runId": None,
                           "mergedHead": p.get("mergedHead"),
                           "phaseId": p.get("id"),
                           "testGateBasis": p.get("testGateBasis")})
                for p in (manifest.get("phases") or [])
                if _evidence_io.merged_phase(p))

# The document itself lives in _report_page.py (P13.3) and its Markdown twin in
# _report_md.py — this file kept `main()`, the theme resolve and the suite that
# reads what `main()` writes. Aliased so the cases below, which are about
# the RENDERED DOCUMENT and can therefore live nowhere else, keep asking for
# these names unchanged.
_plural = _fmt.plural
PRIMARY_COLS = _report_page.PRIMARY_COLS
_OPTIONAL_COLS = _report_page._OPTIONAL_COLS
_present_columns = _report_page._present_columns
_held_by = _report_page._held_by
render_md = _report_md.render_md


# --- the gate verdict -----------------------------------------------------------
# The gate's conditions and verdict are `_status_facts`, imported
# straight above; this used to say the gate was reached through `_loader` as an
# edge the debt table records, which is the shape it had before that module came
# down a layer — and the sentence beside `_load_status_lib` already said so.
# The verdict is still computed HERE and injected into `_report_page`
# rather than fetched from inside it, but the reason is no longer a layer rule:
# what `_report_page` would be reaching for is the CLI gate's own word, and a
# renderer that composed a second opinion out of the same facts is what the
# injection exists to prevent. Retiring the injection is therefore a decision
# about who owns the verdict, not one the module map forces either way.
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
def stranded_marks(project, manifest, config):
    """`{skill name: basis}` for the names a CLONE of this repository would not load.

    THE REPOSITORY ALONE, and never a home directory. A report is a shared
    artifact — a CI upload, a `--share` link, a committed example this repo diffs
    against a fresh render — so a mark computed from the author's `~/.claude` would
    make one manifest render two different documents and turn
    `check-rendered-artifacts.py` into a machine-dependent gate. The repo scope
    exists for this caller.

    `{}` rather than a mark whenever the question was not asked or could not be
    answered: `portability: off`, or a scan that raised. An empty map renders
    exactly what this report rendered before the question existed, which is what
    keeps the committed artifacts byte-identical while the key is off.
    """
    if (config or {}).get("portability") == "off":
        return {}
    try:
        import _panel_discovery
        found = _panel_discovery.discover(
            project, scope=_panel_discovery.SCOPE_REPO) or {}
        travels = set()
        for entry in (found.get("skills") or []):
            if isinstance(entry, dict) and entry.get("travels") is True:
                travels.add(entry.get("name"))
        marks = {}
        for _where, name in _areas.plan_skill_refs(manifest):
            if name not in travels:
                marks[name] = ("does not resolve from anything this repository "
                               "carries, so a clone loads nothing for it")
        return marks
    except Exception:
        # A report that cannot be rendered is worse than one that says less.
        return {}


def render_html(manifest, summary, basename="audit-report", usage=None,
                fragment=False, css=None, show_proposals=True, evidence=None,
                portability=None, own=None, gate_summary=None):
    """The HTML report, with this file's gate verdict wired into it.

    The document itself is `_report_page.render_html`; the only thing added here
    is `_verdict`, which this file owns because the verdict is the CLI gate's own
    word rather than something a renderer composes (see the
    `# --- the gate verdict ---` note above). Keeping the injection in a wrapper
    rather than at every call site is what lets this signature stay what it has
    always been, with two optional arguments for a phase in flight elsewhere.

    `own` is this checkout's plan when `manifest` has a live copy laid over it,
    and `gate_summary` is the rollup of `own` alone. The verdict is taken over
    `gate_summary` when there is one: the gate certifies this checkout, as
    `/audit:status --gate` does, never work sitting in another worktree.
    """
    gate_of = gate_summary

    def verdict(shown):
        return _verdict(gate_of if gate_of is not None else shown)

    return _report_page.render_html(manifest, summary, basename, usage,
                                    fragment=fragment, css=css,
                                    verdict=verdict,
                                    show_proposals=show_proposals,
                                    evidence=evidence,
                                    portability=portability, own=own)


# --- cli ------------------------------------------------------------------------
def main(argv):
    args = list(argv)
    out_dir = None
    fmt = "both"
    summary_file = None
    cli_basename = None
    # A boolean flag, popped before the positional check below counts arguments.
    # Off by default: a parked proposal is part of the plan's story, and hiding it
    # by default is what made an all-parked report read as an empty one.
    show_proposals = "--no-proposals" not in args
    args = [a for a in args if a != "--no-proposals"]
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
    if fmt not in ("html", "md", "both", "artifact") or len(args) > 1:
        sys.stderr.write("usage: render-report.py [<manifest>] [--out-dir DIR] "
                         "[--format html|md|both|artifact] [--summary-file PATH] "
                         "[--basename NAME] [--no-proposals]\n")
        return 2

    resolved = _mio.resolve_manifest(
        os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd(),
        args[0] if args else None)
    manifest_path = resolved["path"]
    if manifest_path is None:
        sys.stderr.write(_mio.describe_unresolved(resolved) + "\n")
        return 2
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
    vm = _manifest_rules
    try:
        findings, warnings = vm.validate(manifest)
    except Exception as exc:  # defensive
        findings, warnings = ["internal validator error: %s" % exc], []
    # ONE BLOCK, TWO CONSUMERS. The gate's verdict and the badge beside each
    # subject are bucketed by the same `evidence_gap`, so they have to be given
    # the same boundary object - two calls to `boundary_for` would read the
    # ledger twice, and a run recorded between them would excuse a subject in one
    # half of the page and not the other.
    boundary = boundary_for(manifest_path)
    # The project root every disk read below resolves against - the in-flight
    # reader, the theme, the third place's own ledger read, and (a few lines
    # down) the panel config. The checkout the plan is in
    # (`_output.project_of_manifest`), the answer the gate recorded the evidence
    # under - not `CLAUDE_PROJECT_DIR`, which may name another checkout, and not
    # the manifest's own directory, which is `docs/audit` on a default plan and
    # read `docs/audit/docs/audit/evidence`, where nothing is ever recorded.
    _proj = _output.project_of_manifest(manifest_path)
    # A PHASE WORKED ON ELSEWHERE IS SHOWN AS ITS LIVE COPY HOLDS IT, read by
    # the one reader `/audit:status` and the panel use and laid over the plan
    # by the same `live_view`, so the three agree on what is ready. Every row
    # read from another copy names it, in the HTML and in the Markdown twin
    # the HTML embeds - this file is forwarded, and a forwarded report must
    # not pass another worktree's uncommitted state off as this checkout's.
    # What certifies stays on this checkout's own plan: the bug counts and the
    # bug table (`own`), the gate verdict (`gate_summary`), the validator, the
    # evidence and the usage ledger.
    live = lib.live_view(manifest, _live_copy.flight_for(
        manifest, manifest_path, _proj))
    plan = live["plan"]
    summary = lib.rollup(plan, findings, warnings, boundary=boundary,
                         copies=live["copies"], own=live["own"])
    if live["note"]:
        summary["liveCopyError"] = live["note"]
    gate_summary = (lib.rollup(manifest, findings, warnings, boundary=boundary)
                    if live["own"] is not None else None)
    usage = load_usage(manifest, manifest_path)
    full_run = _full_run_block(manifest, manifest_path, _proj)
    evidence = load_evidence(manifest, manifest_path, boundary=boundary,
                             full_run=full_run)

    # th: resolve the look once — project theme, then the user's, then
    # the built-in — and hand the compiled sheet to every writer below. A theme
    # that failed to load says so on stderr and the report still renders: a
    # look is decoration, and decoration never takes the document down.
    try:
        _cfg = _panel_cfg(_proj)
    except Exception:
        _cfg = {}
    _tokens, _tinfo = _theme.token_css_for(_proj, _cfg)
    # tokens + the report's own rules, assembled where that concatenation is
    # defined — the token block alone is not a stylesheet.
    _css = _report_ui.css_with_tokens(_tokens)
    _port = stranded_marks(_proj, manifest, _cfg)
    if _tinfo.get("error"):
        sys.stderr.write("WARNING: theme not applied - %s\n" % _tinfo["error"])

    basename = _report_basename(manifest.get("meta"), cli_basename)
    out_dir = out_dir or (os.path.dirname(os.path.abspath(manifest_path)) or ".")
    os.makedirs(out_dir, exist_ok=True)
    written = []
    if fmt in ("html", "both"):
        p = os.path.join(out_dir, basename + ".html")
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render_html(plan, summary, basename, usage,
                                 css=_css, show_proposals=show_proposals,
                                 evidence=evidence, portability=_port,
                                 own=live["own"], gate_summary=gate_summary))
        written.append(p)
    if fmt == "artifact":
        # A separate name, never the .html one. The standalone file is what people
        # open from disk and what CI diffs the live demo against; overwriting it
        # with a fragment would leave both looking fine and one of them broken.
        p = os.path.join(out_dir, basename + ".artifact.html")
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render_html(plan, summary, basename, usage,
                                 fragment=True, css=_css,
                                 show_proposals=show_proposals,
                                 evidence=evidence, portability=_port,
                                 own=live["own"], gate_summary=gate_summary))
        written.append(p)
    if fmt in ("md", "both"):
        p = os.path.join(out_dir, basename + ".md")
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render_md(plan, summary, usage, evidence, own=live["own"]))
        written.append(p)
    for p in written:
        print("wrote %s" % p)
    return 0


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    sys.exit(main(sys.argv[1:]))
