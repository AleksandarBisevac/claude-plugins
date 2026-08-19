#!/usr/bin/env python3
"""
The cases for `_panel_state.py`, moved out of it - an importable helper.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list.

WHAT IS LEFT HERE AFTER U3.1. The module was split six ways, and the cases went
with the code: `test__panel_paths.py`, `test__panel_viewer.py`,
`test__panel_composition.py`, `test__panel_policy.py`, `test__panel_runstate.py`
and `test__panel_usage.py`. What stays is the report export (which is still this
module's, because it carries the one recorded layer-debt edge) and the cases about
the BOUNDARY - the 35 re-exports, and the direction of every import across it.

THE `--name-only` SECURITY CASE MOVED with `_git_config_origins`, into
`test__panel_viewer.py`. It is called out here because a reader looking for it in
this file is looking for the right thing in the wrong place, and because the slice
it takes is the reason neither git-config helper may be renamed casually.

FOUR EXPRESSIONS COULD NOT MOVE LITERALLY when the cases first left the module, and
the reasoning is kept because it is what makes a moved case still ask about its
subject:

  * `_src_of_this_file()` - a three-line `open(__file__)` helper this module,
    `panel-server.py` and `_panel_write.py` each carried a copy of, with all six
    call sites inside the three `--selftest` blocks and none in the product. The
    copies are gone; `_harness.module_source(M)` takes the module, so a source
    slice reads its SUBJECT.
  * `[n for n in _moved if n in globals()]` - INTROSPECTION, not a rebind: "is
    every name this module took actually defined here". This file defines none of
    them, so it fails loudly rather than silently - but it is still asking the
    wrong module. It is `hasattr(M, n)`, and after the split it is also the case
    that proves every re-export resolves.
  * two paths built off the module's own directory: `<dir>/../hooks/
    guard-capabilities.py` and `<dir>/panel-server.py`. `scripts/` and `tests/` sit
    at the same depth, so the first would have resolved correctly by coincidence
    and the second incorrectly (there is no `tests/panel-server.py`). They are
    `_harness.HOOKS_DIR` and `_harness.SCRIPTS_DIR` now.
  * `globals()["_MAX_FACTS"] = 1` and `globals()["_resolve_viewer"] = ...` - both
    patched a module global from the wrong module. They are `M.<name>` patches, and
    both have since moved again, to the suites of the modules that own them: a
    patch applied to a RE-EXPORT would rebind this module's name and leave the
    definition every reader actually reads untouched, which is a case measuring
    nothing. That is why those two suites import their subject directly.

`_manifest_io` is imported here the way `_panel_state.py` imports it, because the
fixture writer goes straight through `_mio.atomic_write_json`.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import ast
import json
import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402  (script_path: resolve a sibling by basename)
import _deps                                       # noqa: E402  (the import graph, read from the AST)
import _manifest_io as _mio                        # noqa: E402  (as _panel_state imports it)
import _panel_state as M                           # noqa: E402


# The six modules `_panel_state` was cut into, in layer order. Spelled once, read
# by three cases below.
_SPLIT = ("_panel_paths", "_panel_viewer", "_panel_composition", "_panel_policy",
          "_panel_runstate", "_panel_usage")


# --- cases --------------------------------------------------------------------
def _cases(check):
    import shutil
    import tempfile

    _src = _harness.module_source(M)

    def _atomic_write_json(path, obj):
        """The selftest's own fixture writer. panel-server keeps the real
        `_atomic_write_json`; nothing in THIS module writes JSON, so rather than
        move a writer a read module has no use for, the fixtures go straight
        through `_manifest_io` — the same implementation that one delegates to."""
        _mio.atomic_write_json(path, obj, ensure_ascii=False, indent=2)

    tmp = tempfile.mkdtemp(prefix="panel-state-selftest-")
    proj = os.path.join(tmp, "proj")
    os.makedirs(os.path.join(proj, ".claude"), exist_ok=True)
    _atomic_write_json(M._config_path(proj), {"trivialLineThreshold": 40})
    mpath = M._manifest_path(proj, M.read_config(proj))
    os.makedirs(os.path.dirname(mpath), exist_ok=True)
    _atomic_write_json(mpath, {
        "meta": {"version": 2, "reviewSkill": None},
        "phases": [{"id": "P1", "title": "P", "status": "pending",
                    "review": {"model": "sonnet"},
                    "tasks": [{"id": "P1.1", "title": "T", "status": "pending"},
                              {"id": "P1.2", "title": "T2", "status": "pending"}]}]})

    # --- report export ------------------------------------------------------------
    # There is deliberately no path parameter on /report: the location is derived
    # from the project's own config, so there is nothing to traverse with.
    _rp = tempfile.mkdtemp(prefix="panel-report-")
    try:
        os.makedirs(os.path.join(_rp, "docs", "audit"), exist_ok=True)
        with open(os.path.join(_rp, "docs", "audit", "audit-plan.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2, "repo": "x"}, "phases": [
                {"id": "P1", "title": "A", "status": "done", "tasks": [
                    {"id": "P1.1", "title": "t", "status": "done"}]}]}, fh)
        check("no report exists before it is rendered",
              os.path.isfile(M.report_paths(_rp)[2]) is False)
        _res = M.render_report(_rp)
        check("export writes the html and its markdown twin, and reports both",
              _res["ok"] and len(_res["files"]) == 2
              and any(f.endswith(".html") for f in _res["files"])
              and any(f.endswith(".md") for f in _res["files"]))
        check("everything it writes stays inside the project",
              all(M._within(_rp, f) for f in _res["files"]))
        check("it hands back an in-origin href, not a filesystem path — a browser "
              "will not follow file:// from an http:// page",
              _res["href"] == "/report" and _res["exists"] is True)
    finally:
        shutil.rmtree(_rp, ignore_errors=True)
    _np = tempfile.mkdtemp(prefix="panel-noreport-")
    try:
        check("a project with no manifest refuses instead of raising",
              M.report_paths(_np) is None
              and M.render_report(_np)["ok"] is False)
    finally:
        shutil.rmtree(_np, ignore_errors=True)

    # --- the basename, and where it is asked (F47) ---------------------------------
    # `report_paths` used to reach `render-report.py` - an ENTRY POINT at layer 7 -
    # for `_report_basename`, a pure naming rule `_report_html` owns at layer 2.
    # That was one of the two call sites under the sole `_deps.KNOWN_LAYER_DEBT`
    # entry, and the only one with a downward home already built for it.
    #
    # NOTHING ABOVE COULD SEE THE DIFFERENCE, and that is why these cases exist.
    # Every fixture in this file writes a manifest with no `meta.reportBasename`,
    # so the derived name is "audit-report" whether the rule ran or the old
    # `except Exception: base = "audit-report"` fallback fired. A fixture that
    # cannot tell the two implementations apart is not evidence about either.
    _rb = tempfile.mkdtemp(prefix="panel-basename-")
    try:
        _rb_dir = os.path.join(_rb, "docs", "audit")
        os.makedirs(_rb_dir, exist_ok=True)
        _rb_name = "quarterly-audit"

        def _write_rb_manifest(meta):
            with open(os.path.join(_rb_dir, "audit-plan.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"meta": meta, "phases": [
                    {"id": "P1", "title": "A", "status": "done", "tasks": [
                        {"id": "P1.1", "title": "t", "status": "done"}]}]}, fh)

        _write_rb_manifest({"version": 2, "repo": "x",
                            "reportBasename": _rb_name})
        _rb_html = M.report_paths(_rb)[2]
        check("rb1 report_paths derives the report's name from meta.reportBasename "
              "- fixture declares %r, which is NOT the default, so this case fails "
              "on any implementation that answers the default regardless. Got %r"
              % (_rb_name, os.path.basename(_rb_html)),
              _rb_name != "audit-report"
              and os.path.basename(_rb_html) == _rb_name + ".html")

        _write_rb_manifest({"version": 2, "repo": "x"})
        _rb_default = M.report_paths(_rb)[2]
        check("rb2 ...and the OTHER direction: with the key absent the name falls to "
              "the rule's own 'audit-report', so rb1 is reading meta rather than "
              "echoing whatever the manifest happens to hold. The two fixtures "
              "differ only in that key and give different answers: %r vs %r"
              % (os.path.basename(_rb_html), os.path.basename(_rb_default)),
              os.path.basename(_rb_default) == "audit-report.html"
              and _rb_default != _rb_html)
    finally:
        shutil.rmtree(_rb, ignore_errors=True)

    # Same function object either way - the layer-2 module owns it, the layer-7
    # command aliases it - which is what makes the move above a change of ROUTE and
    # not of behaviour. Asserted rather than assumed: an alias that had drifted into
    # a copy would make rb1 and rb2 pass while the panel and the CLI disagreed.
    import _report_html as _rh
    _rr = M._load("audit_render_report", "render-report.py")
    check("rb3 `_report_html._report_basename` IS what render-report.py exports "
          "under that name - one function, two spellings, so asking at the owner "
          "cannot answer differently from asking at the command",
          _rh._report_basename is _rr._report_basename
          and M._report_html is _rh)

    # The route itself, read from the AST rather than from a grep: a `.py` literal
    # in a docstring or an error message is not a call, and the whole point of the
    # change is WHICH FUNCTION spells this one.
    _rr_lit = "render-report.py"
    _rr_funcs = {}
    for _node in ast.walk(ast.parse(_src)):
        if isinstance(_node, ast.FunctionDef):
            _rr_funcs[_node.name] = sum(
                1 for _sub in ast.walk(_node)
                if isinstance(_sub, ast.Constant) and _sub.value == _rr_lit)
    _rr_total = sum(_rr_funcs.values())
    check("rb4 the layer-7 load is spelled ONLY in `render_report`, the half that "
          "genuinely wants the whole pipeline: report_paths=%d render_report=%d, "
          "and %d such literal(s) in %d parsed function(s) overall - a walk that "
          "read nothing would report 0 functions and cannot pass this"
          % (_rr_funcs.get("report_paths", -1), _rr_funcs.get("render_report", -1),
             _rr_total, len(_rr_funcs)),
          len(_rr_funcs) > 0 and _rr_total > 0
          and _rr_funcs.get("report_paths") == 0
          and _rr_funcs.get("render_report", 0) >= 1)

    # The edge that REMAINS is still recorded, and still exactly one - the repair
    # narrowed a debt entry rather than retiring it, and a case that let it quietly
    # become zero here while `_deps`' own r2 pinned it would be two answers to one
    # question. Read off `_deps` so there is no second copy of the tuple.
    _rr_debt = [w for f, w in _deps.KNOWN_LAYER_DEBT
                if os.path.basename(f) == "_panel_state.py"]
    check("rb5 ...and this module is still the file `_deps.KNOWN_LAYER_DEBT` records "
          "the upward edge against (%d entr(y/ies): %r). Narrowing two call sites to "
          "one does not retire the edge, and this case is what stops the repair being "
          "read as one"
          % (len(_rr_debt), _rr_debt),
          len(_rr_debt) == 1 and "render-report" in _rr_debt[0])


    # --- isolation cases (P12.3): the moved boundary stays real -----------------
    _imports = [l for l in _src.split("\n")
                if l.startswith("import ") or l.startswith("from ")]
    check("this module never imports panel-server - the read side sits BELOW the "
          "server, so nothing that imports it can form a cycle",
          not any("panel_server" in l or "panel-server" in l for l in _imports))
    # `_loader.script_path`, not `join(_harness.SCRIPTS_DIR, ...)`: this reads
    # another file's SOURCE, so a joined root would keep working for exactly as long
    # as `panel-server.py` sits at the top of `scripts/` and would then fail as a
    # missing file rather than as the resolvable basename it still is.
    _panel_src = open(_loader.script_path("panel-server.py"),
                      encoding="utf-8").read()
    _moved = ["_load", "_cores", "_defaults", "_within", "_config_path",
              "_declared_as_of", "_manifest_path", "_viewer", "_read_json",
              "read_config", "_areas_of", "_bugs_view", "_skills_of",
              "_composition_view", "areas_state", "_JOURNAL", "_journalmod",
              "JOURNAL_PAGE", "journal_state", "help_state", "help_field",
              "_policy_rules", "_policy_enforcement", "_policy_areas_view",
              "policy_state", "_active_area_tags", "_audit_lock_dir",
              "_audit_lock_held", "_lockmod", "_lock_info", "_run_status",
              "usage_state", "report_paths", "render_report", "build_state"]
    _unaliased = [n for n in _moved
                  if "\n%s = _panel_state.%s\n" % (n, n) not in _panel_src]
    check("every name this module took is aliased back in panel-server, so a route "
          "or a selftest that still spells it there resolves to THIS one: %r"
          % (_unaliased,), not _unaliased)
    _defined = [n for n in _moved if hasattr(M, n)]
    check("...and every one of them is actually defined here rather than merely "
          "expected: %r" % ([n for n in _moved if not hasattr(M, n)],),
          len(_defined) == len(_moved))
    # `_journalmod`'s memo is ONE dict, not a copy per module: the write path in
    # panel-server swaps a stub module into it and this module's `journal_state`
    # has to see the same swap, or each side would test a journal the other does
    # not have.
    check("the journal memo is shared with panel-server by identity, not copied",
          "\n_JOURNAL = _panel_state._JOURNAL\n" in _panel_src
          and isinstance(M._JOURNAL, dict))

    # --- U3.1: the split boundary, in both directions ---------------------------
    # The five leaves may not reach back up. A cycle here would not be a lint
    # failure first - it would be an ImportError at panel start-up, on the one
    # code path a user meets before anything else.
    _edges, _broken = _deps.import_graph()
    _upward = [(s, d) for s, d in _edges
               if s in _SPLIT and d in ("_panel_state", "_panel_write")]
    check("u1 no module the split produced imports `_panel_state` or the write "
          "path above it - the read side sits BELOW both, and an edge back up is "
          "an ImportError at panel start-up before it is ever a lint failure: %r"
          % (_upward,), not _broken and not _upward)
    # ...and the other direction, which is what makes u1 non-vacuous: this module
    # really does reach all six. Without this, deleting an import would satisfy u1.
    _down = sorted(d for s, d in _edges if s == "_panel_state" and d in _SPLIT)
    check("u2 ...and `_panel_state` reaches every one of them, so u1 is a claim "
          "about a real edge set rather than an empty one: %r" % (_down,),
          _down == sorted(_SPLIT))
    # Only `_panel_paths` may be reached by the leaves; a leaf reaching a leaf
    # would mean the five do not share a layer, which is what lets `_panel_state`
    # fold them into one order.
    _sideways = [(s, d) for s, d in _edges
                 if s in _SPLIT and d in _SPLIT and d != "_panel_paths"]
    check("u3 the four sibling leaves reach only the shared base, never each "
          "other - a sideways edge is not strictly downward and would cost them "
          "their shared layer: %r" % (_sideways,), not _sideways)

    shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__panel_state.py --selftest\n")
    raise SystemExit(2)
