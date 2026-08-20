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

These cases read `ui/panel.html`, `ui/panel.js` and the `ui/panel-css/` parts -
ASSETS, not another module's Python source - through `_theme.read_asset` /
`_theme.UI_DIR`, which resolve from `_ui_theme.py`'s own location. Nothing here is
computed from this file's path.

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
    # --- every asset file exists and decodes as utf-8 ---------------------------
    # Both layers are ordered parts now, and both tuples are read off the module
    # rather than restated: a part this suite does not know about is a part it
    # cannot fail to read.
    names = ("panel.html",) + tuple(M._CSS_PARTS) + tuple(M._JS_PARTS)
    unreadable = _theme.unreadable_assets(names)
    for name in names:
        check("%s exists and decodes as utf-8" % name, name not in unreadable)

    skeleton = _theme.read_asset("panel.html")
    css = "".join(_theme.read_asset(n) for n in M._CSS_PARTS)
    js = "".join(_theme.read_asset(n) for n in M._JS_PARTS)
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
    check("the JS between the tags is the ordered parts joined and nothing "
          "else - the splice adds no separator, which is what keeps the "
          "assembled page byte-for-byte what the single file produced",
          script_span == js)
    check("the parts carry no <script> tags - those live in panel.html",
          "<script" not in js and "</script>" not in js)
    # A part on disk that nothing LOADS is the expensive failure: the page
    # assembles without it, every substring pin keeps passing, and the feature
    # simply never ships. `declared_asset_drift()` compares the declared list
    # against the DIRECTORY; this compares it against what the page is BUILT
    # from, which is the half that catches a part declared and never joined.
    _declared_js = set(n for n in _theme.UI_ASSETS
                       if n.startswith("panel/") and n.endswith(".js"))
    check("every panel part on disk is loaded, and every loaded part is on disk "
          "- declared %d, assembled %d, difference %r"
          % (len(_declared_js), len(M._JS_PARTS),
             sorted(_declared_js.symmetric_difference(M._JS_PARTS))),
          _declared_js and _declared_js == set(M._JS_PARTS))
    check("the first part declares the primitives and the last one boots, which "
          "is what makes the order load-bearing rather than alphabetical - "
          "sorting the tuple would leave this suite green and the page dead on "
          "the first read of a name still in TDZ",
          M._JS_PARTS[0] == "panel/core.js"
          and M._JS_PARTS[-1] == "panel/boot.js"
          and list(M._JS_PARTS) != sorted(M._JS_PARTS))
    check("core.js really does declare what later parts read at load time, and "
          "boot.js really does end with the call - the names, not just the "
          "positions, so a rename cannot leave the ordering case green",
          "const $=" in _theme.read_asset(M._JS_PARTS[0])
          and _theme.read_asset(M._JS_PARTS[-1]).rstrip().endswith("boot().catch(e=>toast('load failed: '+e,'err'));"))

    # --- CSS brace balance, via _ui_theme's existing lints -----------------------
    # Over the JOIN, not per part: `@media` blocks and their rules could be split
    # across two parts and each half would still have to balance for the sheet to
    # parse, so the assembled string is the only honest subject.
    check("the joined panel-css/ parts balance their braces",
          css.count("{") == css.count("}"))
    check("no declaration in the joined panel-css/ parts is left unterminated",
          not _theme.unterminated_css_decls(css))
    # Every part ends with a newline. panel-server.py lints over
    # UI_HTML.splitlines(), so a part without one joins two lines - which can
    # hide a real offender or manufacture a false one, and no other case here
    # would see it.
    _no_nl = [n for n in M._CSS_PARTS if not _theme.read_asset(n).endswith("\n")]
    check("every panel-css/ part ends with a newline, so the join cannot weld "
          "two lines together (offenders: %r)" % (_no_nl,), not _no_nl)

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
    real_assets = ([("panel.html", skeleton), ("raw_template()", template)]
                   + [(n, _theme.read_asset(n)) for n in M._CSS_PARTS]
                   + [(n, _theme.read_asset(n)) for n in M._JS_PARTS])
    real_cr = _theme.cr_violations(real_assets)
    check("no \\r (CRLF) in any loaded ui/ asset or the assembled template "
          "(found in: %r)" % (real_cr,), not real_cr)

    # --- fixture red-proof: a CRLF asset IS named by the same helper ------------
    fixture_assets = [("panel.html", "<html>\r\n<body></body>\r\n</html>"),
                      ("panel.css", "body { color: red; }\n"),
                      ("panel/core.js", "console.log(1);\n")]
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
