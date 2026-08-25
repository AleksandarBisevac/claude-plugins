#!/usr/bin/env python3
"""
The report's plain CSS and inline JS, off disk as real files — stdlib only.

render-report.py used to carry both as raw-string literals: `_CSS` was
`_theme.TOKEN_CSS` concatenated with a 805-line triple-quoted string of plain
CSS, `_SCRIPT` was one 761-line r-string holding `<script>...</script>` whole.
Nothing in either literal was Python — no editor highlighted it, no linter
looked at it, and a diff on either read as one indistinguishable wall of text
regardless of which rule or which handler actually changed.

The two layers now live as real, editor-highlightable files under `ui/`,
mirroring `_panel_ui.py`'s split (same directory, same convention — the tags
that wrap a block live in the Python that assembles it, never in the asset):

  * `ui/report.css` — the plain-CSS part of `_CSS`, i.e. everything AFTER the
    `_theme.TOKEN_CSS +` concatenation. The token layer itself stays exactly
    where it was: built once in `_ui_theme.py` and shared with the panel, not
    duplicated into this file.
  * `ui/report.js`  — everything that sat BETWEEN `<script>` and `</script>`
    in the old `_SCRIPT` r-string. The tags themselves are not in the file;
    `SCRIPT` below adds them back, the same way `_panel_ui.raw_template()`
    keeps `<style>`/`<script>` in the skeleton rather than in the panel's own
    assets. That is what makes the reassembled `SCRIPT` byte-identical to
    the old literal, tag for tag.

`CSS` and `SCRIPT` are read once at import (module-global) — the same "read
once, keep serving from memory" contract `_CSS`/`_SCRIPT` always had.

The read itself is not ours. `ui/` sits in front of this module and of
`_panel_ui.py` alike, and the two are layer-2 peers that may not import each
other, so the directory, the `newline=""` open, the CR check and the
"exists and decodes" probe all live one layer down in `_ui_theme` — see
`read_asset` there for why the newline flag is load-bearing. What stays here
is the report's own half: which assets it names, and what it pins about them.

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test__report_ui.py`, byte-identical labels and all - see
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

_css_cache = None
_script_cache = None


# --- asset loading ------------------------------------------------------------
# THE ORDER OF THIS TUPLE IS THE CASCADE. Two rules of equal specificity are
# decided by which one is read last, so this sequence is behaviour: the shell
# before the components that sit in it, and the print and forced-colours blocks
# after the colours they override.
_CSS_PARTS = _theme.REPORT_CSS_PARTS


def _css(cache=True):
    """The plain-CSS part of `_CSS` (without the TOKEN_CSS prefix)."""
    global _css_cache
    if cache and _css_cache is not None:
        return _css_cache
    out = "".join(_theme.read_asset(n) for n in _CSS_PARTS)
    if cache:
        _css_cache = out
    return out


# The ordered parts of the report's one inline script, and the ORDER IS THE
# CONTRACT: `report.js` was a single file whose whole body sat inside one IIFE,
# so a naive split left every piece individually unparseable — the opening
# `(function () {` in the first and the closing `})();` in the last. The wrapper
# lives HERE now, which is what lets each part be a real, brace-balanced,
# `node --check`-able file while the assembled page is byte-for-byte what it was.
#
# Dropping the IIFE instead was never an option: roughly a hundred and thirty
# bindings would land in the global scope of a page that already carries
# `window.AUDIT_USAGE`, on a surface where every top-level name in the
# concatenated script shares ONE scope.
#
# THE ORDER OF THIS TUPLE IS THE LOAD ORDER, and it is not alphabetical.
# `report/page-state.js` resolves the elements and shared values every later part
# reads, and `report/exports.js` ends with the boot call, so first and last are
# fixed by what they do. Sorting this tuple leaves every Python suite green while
# the page dies: `chips.js` runs `phaseRows.forEach(...)` at load, and under
# alphabetical order `phaseRows` has not been declared yet.
_SCRIPT_PARTS = (
    # The shared layer first, and that order IS the dependency direction: a
    # shared part cannot call a surface helper because the surface has not been
    # declared yet. See `ui/shared/README.md`.
    "shared/theme.js",
    "shared/plural.js",
    "shared/clipboard.js",
    "shared/dates.js",
    "shared/calendar.js",
    "shared/download.js",
    "shared/storage.js",
    "report/page-state.js",
    "report/filters.js",
    "report/sorting.js",
    "report/chips.js",
    "report/areas.js",
    "report/authors.js",
    "report/date-range.js",
    "report/usage-range.js",
    "report/heatmap.js",
    "report/exports.js",
)
# The page receives ONE module script. A module has its own scope, so the parts
# need no wrapper of their own: every top-level binding stays out of the page's
# globals, which already carry `window.AUDIT_USAGE`. A module is also strict by
# default and runs after parsing, both of which this code is verified against in
# a browser rather than assumed.
#
# `import` is not available and never will be here: a module script is fetched
# with CORS semantics, and a page opened from disk has an opaque origin, so a
# cross-file import fails outright. The parts are therefore joined by this
# module, not by the browser.
_SCRIPT_TAG_OPEN = '<script type="module">'
_SCRIPT_TAG_CLOSE = "</script>"


def _script(cache=True):
    """`<script>...</script>`, assembled from the ordered `ui/report.*.js` parts.

    `cache=False` forces a fresh read (used by `tests/test__report_ui.py`)."""
    global _script_cache
    if cache and _script_cache is not None:
        return _script_cache
    body = "".join(_theme.read_asset(n) for n in _SCRIPT_PARTS)
    out = _SCRIPT_TAG_OPEN + "\n" + body + _SCRIPT_TAG_CLOSE
    if cache:
        _script_cache = out
    return out


CSS = _theme.TOKEN_CSS + _css()
SCRIPT = _script()


def css_with_tokens(token_css):
    """The report's stylesheet wearing a DIFFERENT token block (th, F-P-6).

    The concatenation lives here, in one place, for the reason `CSS` above does:
    a caller that assembled the sheet itself would eventually assemble it
    differently — and a report served the token block ALONE loses every rule in
    report.css, which is exactly the bug this function was extracted after."""
    return (token_css or _theme.TOKEN_CSS) + _css()


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
        print("_report_ui.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__report_ui.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
