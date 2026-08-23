#!/usr/bin/env python3
"""
The panel's ONE assembled page: UI_HTML / UI_TEMPLATE, and what they must say.

Moved out of panel-server.py. That file was 2,542 lines of which 1,927 were its
`--selftest`, and ~1,450 of those were assertions about the CSS and JavaScript in
`ui/panel-css/` and `ui/panel.js` — the assembled page, not the HTTP server that
happens to serve it. They lived in an entry point they had nothing to do with, and
a reader looking for "what does the panel's front end have to be true of" had to
read past a pidfile, a socket and six route handlers to find out. panel-server.py
keeps the handler, the lifecycle and the cases that test THOSE; it imports the two
names below and its `do_GET` is unchanged.

WHAT THIS FILE OWNS: the substitution chain that turns `_panel_ui.raw_template()`
into the page the browser gets, and the cases in `tests/` that read the
result.

THE BUILD ORDER IS LOAD-BEARING, AND IT IS THE REASON THIS IS ONE BLOCK AND NOT A
FUNCTION. Eight substitutions run in a fixed order; THEN `UI_TEMPLATE = UI_HTML`
takes the snapshot; THEN the default theme is substituted into `UI_HTML` alone.
So `UI_TEMPLATE` is the finished page with the theme block still a marker (do_GET
fills it per REQUEST, because a theme is a file on disk and the reader who just
saved one reloads to see it), and `UI_HTML` is that same page wearing the DEFAULT
theme — which is what every `... in UI_HTML` case below reads. Move the snapshot
one line earlier and the served page loses a substitution while every case here
still passes; `pg1` is the case that goes red for exactly that, and it is the only
one that can.

WHERE THIS SITS. Layer 4, beside `_panel_discovery` and `_report_usage`: it reaches
`usage_ledger` (L3, for the cost-band constant), `_panel_ui` and `_panel_settings`
(L2), `_ui_theme` and `_loader` (L1), and nothing else. It must never import
`_panel_state`, `_panel_write`, `_panel_discovery` or panel-server — one of its
cases says so — which is also why the cases that mix a page claim with a server
call (build_state, _run_status, help_field, the route slices) stayed behind rather
than dragging half the server down here. The `_help` edge this file used to carry
went with the suite: it was imported inside `_selftest()` and nowhere else.

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test__panel_page.py`, byte-identical labels and all - see
`plugins/audit/tests/_harness.py`. One of them, `pg2`, parses THIS file and fails
if it ever grows one of those four imports.
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

import _loader           # noqa: E402  (the one path-importlib loader for scripts/)
import _ui_theme as _theme  # noqa: E402  (tokens + labels shared with the report)
import _panel_ui         # noqa: E402  (the markup/CSS/JS, off disk as real files)
import _panel_settings   # noqa: E402  (settings-form schema + the validator's enums)

# The settings-form schema is settings-shape knowledge, not page assembly, so it
# lives in _panel_settings.py. Aliased here so the substitution chain below and
# every case that reads one of them spells the same short name panel-server.py
# always spelled — this is a move, and a moved line that has to be re-typed is a
# moved line that can be re-typed wrong.
FIELD_HELP = _panel_settings.FIELD_HELP
COMPOSITION_HELP = _panel_settings.COMPOSITION_HELP
SETTINGS_GROUPS = _panel_settings.SETTINGS_GROUPS
_cfg_enums = _panel_settings._cfg_enums
_META_API_ONLY = _panel_settings._META_API_ONLY
_META_FORM_KEYS = _panel_settings._META_FORM_KEYS


# --- the UI (self-contained; talks only to its own localhost API) ---------------
UI_HTML = _panel_ui.raw_template()

# Assembled once, at import: the shared token layer and the words both surfaces
# render. One substitution rather than a template engine, so every selftest that
# asks `... in UI_HTML` still sees the whole finished stylesheet.
UI_HTML = UI_HTML.replace("__LABELS__", json.dumps(_theme.LABELS, sort_keys=True))
# The build serving this page. Baked at import rather than substituted per request
# because it cannot change while the process lives, and a request-time placeholder
# would promise that it can.
UI_HTML = UI_HTML.replace("__AUDIT_VERSION__",
                          json.dumps(_output.plugin_version()))
# `ensure_ascii=False` because the page is served as UTF-8 and this prose contains
# em dashes and curly apostrophes like the rest of it. \uXXXX escapes would render
# identically but leave the copy unreadable in the source and ungreppable by the
# selftests, which is how a sentence gets edited in one place and pinned in another.
_JS_JSON = dict(sort_keys=True, ensure_ascii=False)
UI_HTML = UI_HTML.replace("__SETTINGS__", json.dumps(SETTINGS_GROUPS, **_JS_JSON))
UI_HTML = UI_HTML.replace("__FIELD_HELP__", json.dumps(FIELD_HELP, **_JS_JSON))
UI_HTML = UI_HTML.replace("__COMP_HELP__", json.dumps(COMPOSITION_HELP, **_JS_JSON))
# Loads validate-config, so it runs at import rather than in the string above. The
# enums are the validator's own tuples — see _cfg_enums.
UI_HTML = UI_HTML.replace("__CFG_ENUMS__", json.dumps(_cfg_enums(), sort_keys=True))
# The gate and percentile pair panel.js's cost-band mirror reads: usage_ledger.py's
# OWN COST_BAND_PARAMS constant, not a copy of its numbers. cost_bands() is computed
# from this same dict (see usage_ledger.py), so a change to either can no longer
# leave the panel classifying a task into a different band than the report does —
# there is exactly one place these numbers are written down.
_ulmod_for_ui = _loader.load_script("usage_ledger.py",
                                    modname="audit_usage_ledger")
UI_HTML = UI_HTML.replace("__COST_BAND_PARAMS__",
                          json.dumps(_ulmod_for_ui.COST_BAND_PARAMS, sort_keys=True))
# The contrast pairs the Appearance tab's live preview grades, from _ui_theme's OWN
# table rather than a copy of it. The panel used to carry four of these six, so a
# draft could report no warnings where the server reported two - and the two lists
# are concatenated for the reader, who cannot tell which half produced which.
UI_HTML = UI_HTML.replace("__CONTRAST_PAIRS__",
                          json.dumps([list(p) for p in _theme.CONTRAST_PAIRS]))
# th (F-P-6): the token block is substituted LAST, and into two copies.
# UI_TEMPLATE keeps the marker so do_GET can dress the page in THIS project's
# theme per request — a theme is a file on disk, and the reader who just saved
# one reloads to see it. UI_HTML is that same finished page wearing the DEFAULT,
# which is what every selftest below reads: `... in UI_HTML` must keep seeing a
# complete stylesheet, and the template must keep seeing every other
# substitution in this chain (it is captured after all of them for that reason).
UI_TEMPLATE = UI_HTML
UI_HTML = UI_HTML.replace("/*__THEME_TOKENS__*/", _theme.TOKEN_CSS)


# --- stylesheet lints -----------------------------------------------------------
# The stylesheet lints live in _ui_theme, beside the tokens they police, so the
# report and the panel are held to exactly the same rules by the same code. They
# came here with the cases that read them: they judge the assembled page, and
# panel-server.py no longer has one.
_undeclared_css_vars = _theme.undeclared_css_vars
_theme_asymmetric_vars = _theme.theme_asymmetric_vars
_themes_missing_color_scheme = _theme.themes_missing_color_scheme
_mangled_css_escapes = _theme.mangled_css_escapes


# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to the docstring dump, which would
        # exit 0 with no word about the flag. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_panel_page.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__panel_page.py - run that file instead.")
        raise SystemExit(0)
    print(__doc__.strip())
