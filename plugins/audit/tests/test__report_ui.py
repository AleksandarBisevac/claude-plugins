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
    names = ("report.css",) + M._SCRIPT_PARTS
    unreadable = _theme.unreadable_assets(names)
    for name in names:
        check("%s exists and decodes as utf-8" % name, name not in unreadable)

    css_file = _theme.read_asset("report.css")
    js_file = "".join(_theme.read_asset(n) for n in M._SCRIPT_PARTS)

    # --- CSS starts with the TOKEN_CSS block: the tokens sit in front -----------
    check("CSS starts with the TOKEN_CSS block", M.CSS.startswith(_theme.TOKEN_CSS))
    check("CSS is TOKEN_CSS immediately followed by report.css's own content",
          M.CSS == _theme.TOKEN_CSS + css_file)

    # --- exactly one <script> open/close in SCRIPT -------------------------------
    check("exactly one <script> open tag in SCRIPT",
          M.SCRIPT.count("<script") == 1)
    check("exactly one </script> close tag in SCRIPT",
          M.SCRIPT.count("</script>") == 1)
    check("SCRIPT is ONE module script - a module has its own scope, so the "
          "parts need no wrapper and no top-level name reaches the page's "
          "globals; the tags are added by this module, never carried in a part",
          M.SCRIPT.startswith(M._SCRIPT_TAG_OPEN)
          and M.SCRIPT.endswith(M._SCRIPT_TAG_CLOSE)
          and 'type="module"' in M._SCRIPT_TAG_OPEN)
    inner = M.SCRIPT[len(M._SCRIPT_TAG_OPEN):-len(M._SCRIPT_TAG_CLOSE)]
    # What the page receives is the parts joined inside one module script. The
    # module boundary IS the scope, so there is no code wrapper for a difference
    # to hide in, and each part stays parseable on its own.
    check("the JS between the tags is the ordered parts joined, and nothing "
          "else - the module boundary is the scope, so there is no wrapper left "
          "to hide a difference in",
          inner == "\n" + js_file)
    # Inner IIFEs are ordinary code and appear in several parts; what must not
    # appear is the OUTER wrapper's own boundary, which would make the first and
    # last part unbalanced and defeat parsing them one at a time.
    check("no part carries the outer wrapper's boundary - the first does not "
          "open with it and the last does not close with it, so every part is "
          "brace-balanced on its own and `node --check` per part is meaningful",
          not _theme.read_asset(M._SCRIPT_PARTS[0]).startswith("(function () {")
          and not _theme.read_asset(M._SCRIPT_PARTS[-1]).rstrip().endswith("})();"))
    # A part on disk that nothing LOADS is the expensive failure: the page
    # assembles without it, every substring pin keeps passing, and the feature
    # simply never ships. The declared-asset list is compared against the
    # directory elsewhere; this compares it against what the page is BUILT from.
    _declared_js = set(n for n in _theme.UI_ASSETS
                       if n.startswith("report/") and n.endswith(".js"))
    check("every report part on disk is loaded, and every loaded part is on "
          "disk - declared %d, assembled %d, difference %r"
          % (len(_declared_js), len(M._SCRIPT_PARTS),
             sorted(_declared_js.symmetric_difference(M._SCRIPT_PARTS))),
          _declared_js and _declared_js == set(M._SCRIPT_PARTS))
    check("the first part declares and the last one boots, which is what makes "
          "the order load-bearing rather than alphabetical - sorting the tuple "
          "would leave this suite green and the page dead",
          M._SCRIPT_PARTS[0] == "report/page-state.js"
          and M._SCRIPT_PARTS[-1] == "report/exports.js"
          and list(M._SCRIPT_PARTS) != sorted(M._SCRIPT_PARTS))
    check("the parts carry no <script> tags — those live in this module",
          "<script" not in js_file and "</script>" not in js_file)

    # --- mutation proof: a doubled open tag is caught by the same check ----------
    # It must count the SAME literal the check above counts. Counting "<script>"
    # here while the check counts "<script" made this pass over any input at
    # all: the open tag carries an attribute, so the closed-angle spelling
    # occurs zero times and `0 != 1` is true of the un-mutated string too.
    doubled = M.SCRIPT.replace(M._SCRIPT_TAG_OPEN,
                               M._SCRIPT_TAG_OPEN * 2, 1)
    check("mutation proof: a doubled <script> open tag is caught by the same "
          "check that just passed (doubled count is %d, not 1)"
          % doubled.count("<script"), doubled.count("<script") != 1)
    check("...and the un-mutated string is what the same expression calls "
          "correct, so the proof above distinguishes them rather than being "
          "true of everything",
          M.SCRIPT.count("<script") == 1)

    # --- CSS lints, via _ui_theme's existing helpers (same ones panel/_panel_ui use)
    check("report.css braces balance", css_file.count("{") == css_file.count("}"))
    check("no declaration in report.css is left unterminated",
          not _theme.unterminated_css_decls(css_file))

    # --- nothing in ui/ escapes the flat CI selftest glob (scripts/*.py) --------
    ui_pyfiles = sorted(
        (_rel + "/" + _f if _rel != os.curdir else _f)
        for _base, _dirs, _files in os.walk(_theme.UI_DIR)
        for _rel in [os.path.relpath(_base, _theme.UI_DIR)]
        for _f in _files if _f.endswith(".py"))
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
