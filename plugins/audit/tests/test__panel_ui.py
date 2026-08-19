#!/usr/bin/env python3
"""
The cases for `_panel_ui.py`, moved out of it - an importable helper.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list. `_ui_theme` is imported as `_theme`, which is exactly how
`_panel_ui.py` itself spells it: the module UNDER TEST is `M`, every other
production module keeps the name production gives it.

`_IMPORT_TIME_PLACEHOLDERS` and `_REQUEST_TIME_PLACEHOLDERS` stay in `_panel_ui.py`
rather than moving here with the cases: they are the module's own statement of what
panel-server.py substitutes, not test data, and the loop below reads them off `M`.

These cases read `ui/panel.{html,css,js}` - ASSETS, not another module's Python
source - through `_theme.read_asset` / `_theme.UI_DIR`, which resolve from
`_ui_theme.py`'s own location. Nothing here is computed from this file's path.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _ui_theme as _theme                         # noqa: E402
import _panel_ui as M                              # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- the three asset files exist and decode as utf-8 ------------------------
    names = ("panel.html", "panel.css", "panel.js")
    unreadable = _theme.unreadable_assets(names)
    for name in names:
        check("%s exists and decodes as utf-8" % name, name not in unreadable)

    skeleton = _theme.read_asset("panel.html")
    css = _theme.read_asset("panel.css")
    js = _theme.read_asset("panel.js")
    template = M.raw_template(cache=False)

    # --- each insertion marker appears exactly once in the skeleton -------------
    check("the CSS marker appears exactly once in panel.html",
          skeleton.count(M.CSS_MARK) == 1)
    check("the JS marker appears exactly once in panel.html",
          skeleton.count(M.JS_MARK) == 1)

    # --- mutation proof: doubling a marker must fail the exactly-once case ------
    doubled = skeleton.replace(M.CSS_MARK, M.CSS_MARK + M.CSS_MARK, 1)
    check("mutation proof: a doubled CSS marker is caught by the same check "
          "that just passed (doubled count is %d, not 1)"
          % doubled.count(M.CSS_MARK),
          doubled.count(M.CSS_MARK) != 1)

    # --- every __*__ placeholder panel-server.py substitutes is present ---------
    for ph in M._IMPORT_TIME_PLACEHOLDERS + M._REQUEST_TIME_PLACEHOLDERS:
        check("assembled template still carries %s (panel-server.py's own "
              "substitution chain fills it in, unmodified)" % ph, ph in template)

    # --- exactly one <style> and one <script> block in the assembled string -----
    check("exactly one <style> block", template.count("<style>") == 1
          and template.count("</style>") == 1)
    check("exactly one <script> block", template.count("<script>") == 1
          and template.count("</script>") == 1)
    style_span = template[template.index("<style>") + len("<style>"):
                          template.index("</style>")]
    check("the CSS lives inside the <style> block, not beside it", style_span == css)
    script_span = template[template.index("<script>") + len("<script>"):
                           template.index("</script>")]
    check("the JS lives inside the <script> block, not beside it", script_span == js)

    # --- CSS brace balance, via _ui_theme's existing lints -----------------------
    check("panel.css braces balance", css.count("{") == css.count("}"))
    check("no declaration in panel.css is left unterminated",
          not _theme.unterminated_css_decls(css))

    # --- nothing in ui/ escapes the flat CI selftest glob (scripts/*.py) --------
    ui_pyfiles = sorted(
        (_rel + "/" + _f if _rel != os.curdir else _f)
        for _base, _dirs, _files in os.walk(_theme.UI_DIR)
        for _rel in [os.path.relpath(_base, _theme.UI_DIR)]
        for _f in _files if _f.endswith(".py"))
    check("scripts/ui/ contains no .py files: %r" % (ui_pyfiles,), not ui_pyfiles)

    # --- LF contract: none of the loaded ui/ assets (nor the assembled ------
    # template) carry a "\r" — a CRLF checkout (e.g. windows-latest CI without
    # a .gitattributes eol=lf pin) would shift every cross-line selftest pin.
    real_assets = [("panel.html", skeleton), ("panel.css", css), ("panel.js", js),
                   ("raw_template()", template)]
    real_cr = _theme.cr_violations(real_assets)
    check("no \\r (CRLF) in any loaded ui/ asset or the assembled template "
          "(found in: %r)" % (real_cr,), not real_cr)

    # --- fixture red-proof: a CRLF asset IS named by the same helper ------------
    fixture_assets = [("panel.html", "<html>\r\n<body></body>\r\n</html>"),
                      ("panel.css", "body { color: red; }\n"),
                      ("panel.js", "console.log(1);\n")]
    fixture_cr = _theme.cr_violations(fixture_assets)
    check("fixture proof: a CRLF panel.html is named by the CR check "
          "(got %r, want ['panel.html'])" % (fixture_cr,),
          fixture_cr == ["panel.html"])

    # --- caching: repeat calls return the identical cached string ---------------
    a = M.raw_template()
    b = M.raw_template()
    check("raw_template() caches — repeat calls return the SAME object",
          a is b)
    check("cache=False bypasses the cache and still matches",
          M.raw_template(cache=False) == a)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__panel_ui.py --selftest\n")
    raise SystemExit(2)
