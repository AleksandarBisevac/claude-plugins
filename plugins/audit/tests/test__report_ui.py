#!/usr/bin/env python3
"""
The cases for `_report_ui.py`, moved out of it - an importable helper.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list. `_ui_theme` is imported as `_theme`, which is exactly how
`_report_ui.py` itself spells it: the module UNDER TEST is `M`, every other
production module keeps the name production gives it.

These cases read `ui/report.css` and `ui/report.js` - ASSETS, not another module's
Python source - and they reach them through `_theme.read_asset` / `_theme.UI_DIR`,
both of which resolve from `_ui_theme.py`'s own location. Nothing here is computed
from this file's path, so moving one directory over changes nothing.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _ui_theme as _theme                         # noqa: E402
import _report_ui as M                             # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- the two asset files exist and decode as utf-8 ---------------------------
    names = ("report.css", "report.js")
    unreadable = _theme.unreadable_assets(names)
    for name in names:
        check("%s exists and decodes as utf-8" % name, name not in unreadable)

    css_file = _theme.read_asset("report.css")
    js_file = _theme.read_asset("report.js")

    # --- CSS starts with the TOKEN_CSS block: the tokens sit in front -----------
    check("CSS starts with the TOKEN_CSS block", M.CSS.startswith(_theme.TOKEN_CSS))
    check("CSS is TOKEN_CSS immediately followed by report.css's own content",
          M.CSS == _theme.TOKEN_CSS + css_file)

    # --- exactly one <script> open/close in SCRIPT -------------------------------
    check("exactly one <script> open tag in SCRIPT", M.SCRIPT.count("<script>") == 1)
    check("exactly one </script> close tag in SCRIPT",
          M.SCRIPT.count("</script>") == 1)
    check("SCRIPT opens with <script> and closes with </script>, tags added by "
          "this module rather than carried in report.js",
          M.SCRIPT.startswith("<script>") and M.SCRIPT.endswith("</script>"))
    inner = M.SCRIPT[len("<script>"):-len("</script>")]
    check("the JS between the tags is exactly report.js's own content, unmodified",
          inner == js_file)
    check("report.js itself carries no <script> tags — those live in this module",
          "<script>" not in js_file and "</script>" not in js_file)

    # --- mutation proof: a doubled open tag is caught by the same check ----------
    doubled = M.SCRIPT.replace("<script>", "<script><script>", 1)
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
                   ("CSS", M.CSS), ("SCRIPT", M.SCRIPT)]
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
    a = M._css()
    b = M._css()
    check("_css() caches — repeat calls return the SAME object", a is b)
    check("_css(cache=False) bypasses the cache and still matches",
          M._css(cache=False) == a)
    c = M._script()
    d = M._script()
    check("_script() caches — repeat calls return the SAME object", c is d)
    check("_script(cache=False) bypasses the cache and still matches",
          M._script(cache=False) == c)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__report_ui.py --selftest\n")
    raise SystemExit(2)
