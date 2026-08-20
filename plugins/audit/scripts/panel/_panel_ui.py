#!/usr/bin/env python3
"""
The panel's markup/CSS/JS, off disk as real files — stdlib only.

panel-server.py used to carry its whole page as one 3,765-line raw-string literal
assigned to UI_HTML: ~4 lines of head, ~820 lines of CSS inside `<style>...</style>`, ~28 lines of
HTML body markup, ~2,913 lines of JS inside `<script>...</script>`. Nothing in that
literal is Python — no editor highlighted it, no linter looked at it, and a diff on it
read as one indistinguishable wall of text regardless of which layer actually changed.

The three layers now live as real, editor-highlightable files under `ui/`:

  * `ui/panel-css/*.css` — everything between `<style>` and `</style>`, cut into
    ordered feature parts and joined in the cascade order `_ui_theme`'s
    `PANEL_CSS_PARTS` declares (the `/*__THEME_TOKENS__*/` placeholder included,
    in the first part; panel-server.py's substitution chain fills it in after
    this module hands back the assembled string).
  * `ui/panel/*.js` — everything between `<script>` and `</script>` (every
    `__*__` placeholder included, same reason), cut into the ordered feature parts
    `_JS_PARTS` below lists. It was one 5,141-line file until that cut; the parts
    are contiguous runs of it in its original sequence, so the assembled page is
    byte-for-byte what the single file produced. `ui/panel/README.md` says what
    each part is responsible for.
  * `ui/panel.html` — the rest of the original literal (the `<!doctype ...>` head
    and the body markup), with the CSS and JS block replaced by two insertion
    markers, `/*@CSS@*/` and `/*@JS@*/`, sitting exactly where those blocks sat,
    still inside their own `<style>`/`<script>` tags.

`raw_template()` reads those assets and splices css/js back into the markers,
returning the EXACT string the old literal held before panel-server.py's own
`.replace()` chain (THEME_TOKENS, LABELS, SETTINGS, FIELD_HELP, COMP_HELP,
CFG_ENUMS) runs on it — that chain is untouched and still lives in panel-server.py.
Byte-for-byte: this module does not touch `__AUDIT_TOKEN__`/`__AUDIT_PROJECT__`
either, since those are filled in per-request, not at import.

The result is cached in a module global — the assets are read once per process,
the same "read once, keep serving from memory" contract UI_HTML always had.

The read itself is not ours. `ui/` sits in front of this module and of
`_report_ui.py` alike, and the two are layer-2 peers that may not import each
other, so the directory, the `newline=""` open, the CR check and the
"exists and decodes" probe all live one layer down in `_ui_theme` — see
`read_asset` there for why the newline flag is load-bearing. What stays here
is the panel's own half: the markers, the splice, and what it pins about them.

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test__panel_ui.py`, byte-identical labels and all - see
`plugins/audit/tests/_harness.py`.
"""
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

import _ui_theme as _theme   # noqa: E402  (reached by bare basename: the preamble
                              # above put scripts/ and its subdirectories on the path)

CSS_MARK = "/*@CSS@*/"
JS_MARK = "/*@JS@*/"

# THE ORDER OF THIS TUPLE IS THE LOAD ORDER, and it is not alphabetical. The page
# receives ONE script, so every part shares one scope and every top-level
# `const`/`let` in it is in TDZ until its own line runs: `panel/core.js` declares
# `$`, `el`, `api` and `TOKEN`, which executable statements further down read, and
# `panel/boot.js` ends with the `boot()` call. Sorting this tuple leaves every
# Python suite green while the page dies on the first read of an undeclared name.
#
# It is a CUT and not a filing: each name is one contiguous run of the old
# `panel.js` in its original sequence, which is what makes the assembled page
# byte-for-byte what it was. `boot()` is DEFINED in `write-confirmation.js` and
# CALLED in `boot.js` because that is where the two sat; moving either would be a
# regrouping, and 680 substring assertions plus 26 index-bounded slices over
# `UI_HTML` are pinned to the order that ships.
#
# `import`/`export` between these files is not what joins them, and that is now a
# measured statement rather than an inherited one: real cross-file ES modules DO
# work over this panel's `http://127.0.0.1` origin (unlike the report's `file://`
# one), but reaching them needs a static route serving `text/javascript` and a new
# home for the eight `__*__` placeholders substituted into this text. Until that
# is decided, Python joins the parts.
_JS_PARTS = (
    # The shared layer first, for the reason `ui/shared/README.md` gives: the
    # order is the dependency direction, so a shared part cannot reach back into
    # a surface helper.
    "shared/plural.js",
    "shared/clipboard.js",
    "shared/dates.js",
    "shared/calendar.js",
    "shared/download.js",
    "shared/storage.js",
    "panel/core.js",
    "panel/write-confirmation.js",
    "panel/hints.js",
    "panel/help-drawer.js",
    "panel/settings.js",
    "panel/composition.js",
    "panel/ado-connector.js",
    "panel/theme-state.js",
    "panel/appearance-view.js",
    "panel/run-status.js",
    "panel/overview.js",
    "panel/policy-state.js",
    "panel/policy-view.js",
    "panel/usage-model.js",
    "panel/usage-filtering.js",
    "panel/usage-charts.js",
    "panel/usage-metrics.js",
    "panel/usage-cards.js",
    "panel/browse-dialog.js",
    "panel/usage-view.js",
    "panel/boot.js",
)

_cache = None

# THE ORDER OF THIS TUPLE IS THE CASCADE. Two rules of equal specificity are
# decided by which one is read last, so this sequence is behaviour: the reset
# before the shell, the shell before the views drawn in it, and each view's
# narrow-screen overrides after the rules they override. It is declared in
# `_ui_theme` and only pointed at here, because the theme lints run at that
# layer and must audit the sheet in the order that ships.
_CSS_PARTS = _theme.PANEL_CSS_PARTS


# --- template assembly --------------------------------------------------------
def raw_template(cache=True):
    """Return the pre-substitution UI_HTML string, assembled from ui/panel.*.

    `cache=False` forces a fresh read+splice (used by `tests/test__panel_ui.py`,
    which mutates the marker count to prove the exactly-once check can fail)."""
    global _cache
    if cache and _cache is not None:
        return _cache
    skeleton = _theme.read_asset("panel.html")
    css = "".join(_theme.read_asset(n) for n in _CSS_PARTS)
    js = "".join(_theme.read_asset(n) for n in _JS_PARTS)
    out = skeleton.replace(CSS_MARK, css, 1).replace(JS_MARK, js, 1)
    if cache:
        _cache = out
    return out


# The placeholders panel-server.py substitutes AFTER raw_template() returns —
# some at import (baked once into the module-level UI_HTML), one per request.
_IMPORT_TIME_PLACEHOLDERS = (
    "/*__THEME_TOKENS__*/", "__LABELS__", "__SETTINGS__", "__FIELD_HELP__",
    "__COMP_HELP__", "__CFG_ENUMS__",
)
_REQUEST_TIME_PLACEHOLDERS = ("__AUDIT_TOKEN__", "__AUDIT_PROJECT__")


if __name__ == "__main__":
    import sys
    from _output import safe_stdio      # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exits silently: `--selftest` is what every other
        # file here still accepts, so nothing would tell a reader whether this
        # one ran nothing or has nothing. It deliberately does NOT print the
        # suite contract - that literal is how `_output.selftest_coverage()`
        # tells an inline suite from a migrated one.
        print("_panel_ui.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__panel_ui.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
