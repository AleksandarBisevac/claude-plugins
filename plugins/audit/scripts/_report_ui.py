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
    keeps `<style>`/`<script>` in the skeleton rather than in `panel.css`/
    `panel.js`. That is what makes the reassembled `SCRIPT` byte-identical to
    the old literal, tag for tag.

`CSS` and `SCRIPT` are read once at import (module-global) — the same "read
once, keep serving from memory" contract `_CSS`/`_SCRIPT` always had.

The read itself is not ours. `ui/` sits in front of this module and of
`_panel_ui.py` alike, and the two are layer-2 peers that may not import each
other, so the directory, the `newline=""` open, the CR check and the
"exists and decodes" probe all live one layer down in `_ui_theme` — see
`read_asset` there for why the newline flag is load-bearing. What stays here
is the report's own half: which assets it names, and what it pins about them.
"""
import os

import _ui_theme as _theme   # same dir; sys.path[0] when run standalone, or the
                              # importer's own sys.path.insert(0, _HERE) otherwise

_css_cache = None
_script_cache = None


# --- asset loading ------------------------------------------------------------
def _css(cache=True):
    """The plain-CSS part of `_CSS` (without the TOKEN_CSS prefix)."""
    global _css_cache
    if cache and _css_cache is not None:
        return _css_cache
    out = _theme.read_asset("report.css")
    if cache:
        _css_cache = out
    return out


def _script(cache=True):
    """`<script>...</script>`, assembled from ui/report.js.

    `cache=False` forces a fresh read (used by the selftest)."""
    global _script_cache
    if cache and _script_cache is not None:
        return _script_cache
    out = "<script>" + _theme.read_asset("report.js") + "</script>"
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


# --- selftest -----------------------------------------------------------------
def _selftest():
    ok = bad = 0

    def check(name, cond):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("PASS %s" % name)
        else:
            bad += 1
            print("FAIL %s" % name)

    # --- the two asset files exist and decode as utf-8 ---------------------------
    names = ("report.css", "report.js")
    unreadable = _theme.unreadable_assets(names)
    for name in names:
        check("%s exists and decodes as utf-8" % name, name not in unreadable)

    css_file = _theme.read_asset("report.css")
    js_file = _theme.read_asset("report.js")

    # --- CSS starts with the TOKEN_CSS block: the tokens sit in front -----------
    check("CSS starts with the TOKEN_CSS block", CSS.startswith(_theme.TOKEN_CSS))
    check("CSS is TOKEN_CSS immediately followed by report.css's own content",
          CSS == _theme.TOKEN_CSS + css_file)

    # --- exactly one <script> open/close in SCRIPT -------------------------------
    check("exactly one <script> open tag in SCRIPT", SCRIPT.count("<script>") == 1)
    check("exactly one </script> close tag in SCRIPT", SCRIPT.count("</script>") == 1)
    check("SCRIPT opens with <script> and closes with </script>, tags added by "
          "this module rather than carried in report.js",
          SCRIPT.startswith("<script>") and SCRIPT.endswith("</script>"))
    inner = SCRIPT[len("<script>"):-len("</script>")]
    check("the JS between the tags is exactly report.js's own content, unmodified",
          inner == js_file)
    check("report.js itself carries no <script> tags — those live in this module",
          "<script>" not in js_file and "</script>" not in js_file)

    # --- mutation proof: a doubled open tag is caught by the same check ----------
    doubled = SCRIPT.replace("<script>", "<script><script>", 1)
    check("mutation proof: a doubled <script> open tag is caught by the same "
          "check that just passed (doubled count is %d, not 1)"
          % doubled.count("<script>"), doubled.count("<script>") != 1)

    # --- CSS lints, via _ui_theme's existing helpers (same ones panel/_panel_ui use)
    check("report.css braces balance", css_file.count("{") == css_file.count("}"))
    check("no declaration in report.css is left unterminated",
          not _theme.unterminated_css_decls(css_file))

    # --- nothing in ui/ escapes the flat CI selftest glob (scripts/*.py) --------
    ui_pyfiles = [f for f in os.listdir(_theme.UI_DIR) if f.endswith(".py")]
    check("scripts/ui/ contains no .py files: %r" % (ui_pyfiles,), not ui_pyfiles)

    # --- LF contract: none of the loaded ui/ assets (nor the assembled CSS/ ----
    # SCRIPT) carry a "\r" — a CRLF checkout (e.g. windows-latest CI without a
    # .gitattributes eol=lf pin) would shift every cross-line selftest pin.
    real_assets = [("report.css", css_file), ("report.js", js_file),
                   ("CSS", CSS), ("SCRIPT", SCRIPT)]
    real_cr = _theme.cr_violations(real_assets)
    check("no \\r (CRLF) in any loaded ui/ asset or the assembled CSS/SCRIPT "
          "(found in: %r)" % (real_cr,), not real_cr)

    # --- fixture red-proof: a CRLF asset IS named by the same helper ------------
    fixture_assets = [("report.css", "body { color: red; }\r\n"),
                       ("report.js", "console.log(1);\n")]
    fixture_cr = _theme.cr_violations(fixture_assets)
    check("fixture proof: a CRLF report.css is named by the CR check "
          "(got %r, want ['report.css'])" % (fixture_cr,),
          fixture_cr == ["report.css"])

    # --- caching: repeat calls return the identical cached string ---------------
    a = _css()
    b = _css()
    check("_css() caches — repeat calls return the SAME object", a is b)
    check("_css(cache=False) bypasses the cache and still matches",
          _css(cache=False) == a)
    c = _script()
    d = _script()
    check("_script() caches — repeat calls return the SAME object", c is d)
    check("_script(cache=False) bypasses the cache and still matches",
          _script(cache=False) == c)

    print(("ALL PASS: %d/%d cases passed" if not bad else
           "SELFTEST FAILED: %d/%d cases passed") % (ok, ok + bad))
    return 1 if bad else 0


if __name__ == "__main__":
    import sys
    from _output import safe_stdio      # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    print(__doc__.strip())
