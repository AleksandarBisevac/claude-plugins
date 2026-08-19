#!/usr/bin/env python3
"""
The panel's markup/CSS/JS, off disk as real files — stdlib only.

panel-server.py used to carry its whole page as one 3,765-line raw-string literal
assigned to UI_HTML: ~4 lines of head, ~820 lines of CSS inside `<style>...</style>`, ~28 lines of
HTML body markup, ~2,913 lines of JS inside `<script>...</script>`. Nothing in that
literal is Python — no editor highlighted it, no linter looked at it, and a diff on it
read as one indistinguishable wall of text regardless of which layer actually changed.

The three layers now live as real, editor-highlightable files under `ui/`:

  * `ui/panel.css` — everything between `<style>` and `</style>` (the
    `/*__THEME_TOKENS__*/` placeholder included; panel-server.py's substitution
    chain fills it in after this module hands back the assembled string).
  * `ui/panel.js`  — everything between `<script>` and `</script>` (every
    `__*__` placeholder included, same reason).
  * `ui/panel.html` — the rest of the original literal (the `<!doctype ...>` head
    and the body markup), with the CSS and JS block replaced by two insertion
    markers, `/*@CSS@*/` and `/*@JS@*/`, sitting exactly where those blocks sat,
    still inside their own `<style>`/`<script>` tags.

`raw_template()` reads the three files and splices css/js back into the markers,
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

_cache = None


# --- template assembly --------------------------------------------------------
def raw_template(cache=True):
    """Return the pre-substitution UI_HTML string, assembled from ui/panel.*.

    `cache=False` forces a fresh read+splice (used by `tests/test__panel_ui.py`,
    which mutates the marker count to prove the exactly-once check can fail)."""
    global _cache
    if cache and _cache is not None:
        return _cache
    skeleton = _theme.read_asset("panel.html")
    css = _theme.read_asset("panel.css")
    js = _theme.read_asset("panel.js")
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
