#!/usr/bin/env python3
"""
The cases for `_ui_theme.py`, moved out of it - an importable helper.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list. Nothing above layer 1 is imported here on purpose - the `ua`
cases already say why: `_report_ui` and `_panel_ui` sit a layer up, and reaching up
for a test is the shortcut `_deps.layer_violations()` would be right to fail.

ONE CASE FORCED A REAL CHANGE, AND IT IS `ua1`. It asserted that `UI_DIR` sits beside
the module, spelled `os.path.dirname(UI_DIR) == os.path.dirname(os.path.abspath(
__file__))`. Carried literally into `tests/` that comparison is FALSE, because
`__file__` is now this file and `ui/` is not beside it - the case would go red
pointing at a defect that is not there. It says the same thing about the SUBJECT
instead: `UI_DIR` is `scripts/ui`, named off `_harness.SCRIPTS_DIR`. The five
`isfile` checks and `ua2`'s mutation proof are untouched, and the new clause was
proven red by pointing `M.UI_DIR` at a directory that is not `scripts/ui`.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import io
import os
import re
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _ui_theme as M                              # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    # uc (F-P-2): the empty bucket has ONE name, and it is not its storage key.
    check("the empty usage bucket is named once, for all three surfaces: the "
          "ledger's \"--\" (no phase/task) and its attr bucket are the same fact "
          "to a reader, and neither reaches a screen as its storage key",
          M.label("--") == M.label("unattributed") == M.UNCATEGORIZED
          and M.UNCATEGORIZED not in ("--", "unattributed"))
    # --- th (F-P-6): the token layer as data --------------------------------
    check("th1 the stylesheet round-trips through the theme model BYTE FOR "
          "BYTE - the default theme is read OUT of TOKEN_CSS, so the two can "
          "never drift, and shipping the editor changes nothing on screen",
          M.compile_theme(M.DEFAULT_THEME) == M.TOKEN_CSS)
    check("th2 every themable token was actually found in the stylesheet - a "
          "name in THEME_GROUPS that no rule declares is an editor control "
          "that writes into nothing",
          sorted(M.DEFAULT_THEME) == sorted(M.THEME_TOKENS))
    _t2 = dict(M.DEFAULT_THEME)
    _t2["--accent"] = {"$value": "#7c3aed", "$dark": "#a78bfa"}
    _c2 = M.compile_theme(_t2)
    check("th3 a changed colour lands in the light block AND in both dark "
          "blocks - the OS-default one and the explicit toggle, or half the "
          "readers keep the old theme",
          "--accent:#7c3aed" in _c2 and _c2.count("--accent:#a78bfa") == 2
          and "--accent:#0d9488" not in _c2)
    check("th4 ...and nothing else moves", "--st-done:#15803d" in _c2
          and _c2.count("color-scheme") == M.TOKEN_CSS.count("color-scheme"))
    check("th5 a themed stylesheet still passes the sheet's own lints - parity "
          "and color-scheme are properties of the OUTPUT, not of the default",
          not M.theme_asymmetric_vars(_c2) and not M.themes_missing_color_scheme(_c2))
    check("th6 a single-valued token (shape/type) is written once, and a $dark "
          "on it is simply not asked for",
          "$dark" not in M.DEFAULT_THEME["--radius"]
          and "$dark" in M.DEFAULT_THEME["--accent"]
          and M.compile_theme({"--radius": {"$value": "2px"}}).count("--radius:2px") == 1)
    check("th7 no comment in this stylesheet carries a brace - the block "
          "scanner counts them, so a comment that did would corrupt a theme "
          "silently",
          not any("{" in m.group(0) or "}" in m.group(0)
                  for m in re.finditer(r"/\*.*?\*/", M.TOKEN_CSS, re.S)))
    # Validation: what a theme may say, and what it may never say.
    check("th8 an unknown token is a finding, not a silently ignored key",
          any("--brand-x" in f for f in
              M.validate_theme({"--brand-x": {"$value": "#fff"}})[0]))
    check("th9 a colour without its dark half is a finding - the parity lint "
          "refuses it downstream, and the missing half renders transparent",
          any("$dark" in f for f in
              M.validate_theme({"--accent": {"$value": "#fff"}})[0]))
    check("th10 a value that is not a value is refused: no rules, no url(), "
          "no second declaration",
          all(M.validate_theme({"--accent": {"$value": v, "$dark": "#fff"}})[0]
              for v in ("red;}body{display:none", "url(http://x/a.png)",
                        "#fff /* x */"))
          # ...and a real colour in any form this editor writes is accepted.
          and not M.validate_theme({"--accent": {"$value": "#7c3aed",
                                               "$dark": "rgba(167,139,250,.9)"}})[0])
    check("th11 shape and type take plain values, and the same rule about "
          "rules applies to them",
          not M.validate_theme({"--radius": {"$value": "2px"}})[0]
          and M.validate_theme({"--sans": {"$value": "x;}@import url(y)"}})[0])
    check("th12 contrast is measured and WARNED about, never refused - a "
          "theme is the reader's call",
          M.contrast_ratio("#ffffff", "#000000") == 21.0
          and any("below" in w for w in M.contrast_warnings(
              {"--text": {"$value": "#eeeeee", "$dark": "#eeeeee"}}))
          and not M.validate_theme(
              {"--text": {"$value": "#eeeeee", "$dark": "#eeeeee"}})[0])
    check("th13 a theme that overrides only the accent is still judged against "
          "the ground it will sit on, not against nothing",
          M.contrast_warnings({"--accent": {"$value": "#f8fafc",
                                          "$dark": "#f8fafc"}}))

    import json as _json
    import tempfile as _tf
    _root = _tf.mkdtemp(prefix="audit-theme-")
    _proj = os.path.join(_root, "proj")
    _home = os.path.join(_root, "home")
    for _d in (os.path.join(_proj, ".claude"), os.path.join(_home, ".claude")):
        os.makedirs(_d, exist_ok=True)

    def _write(path, obj):
        with io.open(path, "w", encoding="utf-8") as fh:
            fh.write(_json.dumps(obj))

    _pfile = os.path.join(_proj, ".claude", M.THEME_FILENAME)
    _ufile = os.path.join(_home, ".claude", M.THEME_FILENAME)
    check("th14 nothing on disk anywhere -> the built-in, said out loud",
          M.resolve_theme(_proj, {}, _home)["source"] == "default")
    _write(_ufile, {"tokens": {"--accent": {"$value": "#111111",
                                            "$dark": "#eeeeee"}}})
    check("th15 a user theme is found when the project has none",
          M.resolve_theme(_proj, {}, _home)["source"] == "user")
    _write(_pfile, {"tokens": {"--accent": {"$value": "#222222",
                                            "$dark": "#dddddd"}}})
    _r = M.resolve_theme(_proj, {}, _home)
    check("th16 ...and the PROJECT's wins when both exist - a team shares one "
          "look through the repo",
          _r["source"] == "project"
          and _r["theme"]["--accent"]["$value"] == "#222222")
    check("th17 the compiled sheet carries it, and still passes the lints",
          "--accent:#222222" in M.token_css_for(_proj, {}, _home)[0]
          and not M.theme_asymmetric_vars(M.token_css_for(_proj, {}, _home)[0]))
    check("th18 ui.theme naming the built-in short-circuits the search",
          M.resolve_theme(_proj, {"ui": {"theme": "slate-teal"}}, _home)["source"]
          == "default")
    _alt = os.path.join(_proj, "themes", "alt.json")
    os.makedirs(os.path.dirname(_alt), exist_ok=True)
    _write(_alt, {"tokens": {"--accent": {"$value": "#333333", "$dark": "#cccccc"}}})
    check("th19 ui.theme naming a path uses THAT file, wherever it sits",
          M.resolve_theme(_proj, {"ui": {"theme": "themes/alt.json"}},
                        _home)["theme"]["--accent"]["$value"] == "#333333")
    _write(_pfile, {"tokens": {"--accent": {"$value": "red;}body{display:none",
                                            "$dark": "#fff"}}})
    _bad = M.resolve_theme(_proj, {}, _home)
    check("th20 a theme carrying anything but values is REFUSED at the door, "
          "the reader falls back, and the reason is named rather than swallowed "
          "- a report is emailed and published",
          _bad["source"] != "project" and _bad["error"]
          and "display:none" not in M.token_css_for(_proj, {}, _home)[0])
    with io.open(_pfile, "w", encoding="utf-8") as _fh:
        _fh.write("{not json")
    check("th21 an unreadable theme degrades to the default look and says why "
          "- decoration must never take the page down",
          M.resolve_theme(_proj, {}, _home)["source"] != "project"
          and M.token_css_for(_proj, {}, _home)[0].startswith("\n/* ---- design tokens"))
    import shutil as _sh
    # --- th: density, layout, presets (second increment) ---------------------
    check("th22 comfortable is exactly the shipped sheet - the default density "
          "must be a no-op, or every byte-pin above is a lie",
          M.compile_theme(M.DEFAULT_THEME, layout={"density": "comfortable"})
          == M.TOKEN_CSS
          and M.compile_theme(M.DEFAULT_THEME, layout={}) == M.TOKEN_CSS)
    _cmp = M.compile_theme(M.DEFAULT_THEME, layout={"density": "compact"})
    _spa = M.compile_theme(M.DEFAULT_THEME, layout={"density": "spacious"})
    check("th23 density scales the SPACING scale in one move - eight steps from "
          "one decision, not eight hand-tuned values",
          "--sp-3:.8rem" in _cmp and "--sp-3:1.25rem" in _spa
          and "--sp-3:1rem" in M.TOKEN_CSS)
    check("th24 ...and type follows at a THIRD of it: a compact panel wants "
          "tighter air, not smaller words",
          "--t-3:.8167rem" in _cmp or "--t-3:.817rem" in _cmp
          or "--t-3:.8166rem" in _cmp)
    check("th25 a scaled sheet is still a sheet - the lints hold, and nothing "
          "but the scaled tokens moved",
          not M.theme_asymmetric_vars(_cmp)
          and not M.themes_missing_color_scheme(_cmp)
          and "--accent:#0d9488" in _cmp)
    check("th26 density multiplies the step a theme set BY HAND too - one "
          "meaning of 'compact', not one per theme",
          "--t-1:2.8rem" in M.compile_theme(
              dict(M.DEFAULT_THEME, **{"--t-1": {"$value": "3rem"}}),
              layout={"density": "compact"}))
    check("th27 _scale leaves what it cannot parse alone, rather than turning "
          "it into garbage",
          M._scale("cubic-bezier(.4,0,.2,1)", 0.8) == "cubic-bezier(.4,0,.2,1)"
          and M._scale("1.5rem", 2.0) == "3rem" and M._scale(".25rem", 0.8) == ".2rem")
    check("th28 the layout block is validated: a density outside the three is a "
          "finding, an unknown key is a warning, an order must be lists of names",
          M.validate_layout({"density": "roomy"})[0]
          and not M.validate_layout({"density": "compact"})[0]
          and M.validate_layout({"wat": 1})[1]
          and M.validate_layout({"order": {"over": ["a", 2]}})[0]
          and not M.validate_layout({"order": {"over": ["phases", "gate"]}})[0]
          and not M.validate_layout(None)[0])
    check("th29 the shell metrics are themable and single-valued - a rail width "
          "is one number, not a pair",
          "--nav-w" in M.THEME_TOKENS and "--nav-w" in M.THEME_SINGLE
          and M.compile_theme({"--nav-w": {"$value": "18rem"}}).count("--nav-w:18rem") == 1)
    # Presets are FILES, so the list is what is on disk.
    _pdir = os.path.join(_proj, ".claude", "themes")
    os.makedirs(_pdir, exist_ok=True)
    _write(os.path.join(_pdir, "midnight.json"),
           {"tokens": {"--accent": {"$value": "#111111", "$dark": "#eeeeee"}}})
    _names = [t["name"] for t in M.list_themes(_proj)]
    check("th30 the built-in is always offered, and every saved theme beside it",
          _names[0] == "slate-teal" and "midnight" in _names
          and M.list_themes(_proj)[1]["path"].replace(chr(92), "/")
          == ".claude/themes/midnight.json")
    _write(_pfile, {"tokens": {}, "layout": {"density": "compact",
                                             "order": {"over": ["phases"]}}})
    _lr = M.resolve_theme(_proj, {}, _home)
    check("th31 a theme's layout rides its file and reaches the compiler - "
          "density is part of the look, and the look is one file",
          M.theme_layout(_lr["theme"]).get("density") == "compact"
          and "--sp-3:.8rem" in M.token_css_for(_proj, {}, _home)[0])
    _write(_pfile, {"tokens": {}, "layout": {"density": "nope"}})
    check("th32 ...and an invalid layout is refused at the door like any other "
          "invalid theme, rather than half-applied",
          M.resolve_theme(_proj, {}, _home)["source"] != "project")

    _sh.rmtree(_root, ignore_errors=True)

    check("tokens declare a light :root", ":root{" in M.TOKEN_CSS)
    check("tokens declare both dark forms - the OS default AND the explicit "
          "toggle, or one of the two paths silently keeps light colours",
          "prefers-color-scheme:dark" in M.TOKEN_CSS
          and ':root[data-theme="dark"]' in M.TOKEN_CSS)
    check("no token is declared in only one theme: %r" % (M.theme_asymmetric_vars(M.TOKEN_CSS),),
          not M.theme_asymmetric_vars(M.TOKEN_CSS))
    # The toggle has to move the NATIVE controls too, and tokens cannot reach them.
    check("every explicit theme restates color-scheme, so the toggle moves the "
          "checkboxes, selects, spinners, date pickers and scrollbars with it: %r"
          % (M.themes_missing_color_scheme(M.TOKEN_CSS),),
          not M.themes_missing_color_scheme(M.TOKEN_CSS))
    check("both directions are pinned, not just dark",
          "color-scheme:dark" in M.TOKEN_CSS and "color-scheme:light}" in M.TOKEN_CSS)
    check("bare :root still follows the OS when nobody has chosen",
          re.search(r":root\{[^}]*color-scheme:light dark;", M.TOKEN_CSS) is not None)
    # The lint's own two ways of being wrong. It caught nothing for four releases
    # because there was nothing like it; these prove it can fail and can pass.
    check("the lint detects a theme with no color-scheme",
          M.themes_missing_color_scheme(
              ':root{color-scheme:light dark}\n:root[data-theme="dark"]{--bg:#000}')
          == ["dark"])
    check("the lint accepts a theme satisfied by a DIFFERENT block, which is how "
          "the panel adds its own roles without restating the property",
          M.themes_missing_color_scheme(
              ':root[data-theme=dark]{color-scheme:dark}\n'
              ':root[data-theme=dark]{--ok:#0f0}') == [])
    check("a :not() negation cannot satisfy a theme, but it does NAME one - which "
          "is the only mention explicit-light gets, since light needs no colours",
          M.themes_missing_color_scheme(
              '@media (prefers-color-scheme:dark){:root:not([data-theme=light])'
              '{--bg:#000}}') == ["light"])
    check("...and naming it is enough for a pin elsewhere to answer it",
          M.themes_missing_color_scheme(
              ':root[data-theme=light]{color-scheme:light}\n'
              '@media (prefers-color-scheme:dark){:root:not([data-theme=light])'
              '{--bg:#000}}') == [])
    check("a print sheet cannot vouch for a SCREEN theme - the report's forces a "
          "light page for :root[data-theme=dark], and counting it hid the defect",
          M.themes_missing_color_scheme(
              ':root[data-theme="dark"]{--bg:#000}\n'
              '@media print{:root,:root[data-theme="dark"]{color-scheme:light}}')
          == ["dark"])
    # An escape that Python ate is invisible in the source and visible on screen.
    check("no escape was eaten before the browser saw it: %r"
          % (M.mangled_css_escapes(M.TOKEN_CSS),),
          not M.mangled_css_escapes(M.TOKEN_CSS))
    check("the escape lint catches the tick that shipped mangled - the octal "
          "residue and the bell, which are the two halves of one typo",
          M.mangled_css_escapes('.a::before{content:"¹3\x070"}')
          and M.mangled_css_escapes('.a::before{content:"¹3"}')
          and M.mangled_css_escapes('.a{--x:"\x07"}'))
    check("...and passes the doubled spelling that actually reaches the browser",
          M.mangled_css_escapes('.a::before{content:"\\2713\\a0"}') == [])
    check("a glyph written literally is not a broken escape: ✓ and — are above "
          "the range an octal escape can reach, so they are left alone",
          M.mangled_css_escapes('.a::before{content:"✓—"}') == [])
    check("no declaration is left unterminated: %r" % (M.unterminated_css_decls(M.TOKEN_CSS),),
          not M.unterminated_css_decls(M.TOKEN_CSS))
    check("braces balance", M.TOKEN_CSS.count("{") == M.TOKEN_CSS.count("}"))
    # The sticky stack is geometry both surfaces pin against.
    check("the sticky stack is declared once, and derives",
          "--topbar-h:" in M.TOKEN_CSS and "--sticky-2:calc(var(--sticky-1)" in M.TOKEN_CSS
          and "--z-topbar:" in M.TOKEN_CSS)
    check("the shell's proportions are tokens, so the two surfaces cannot drift "
          "to 14.5rem and 13.5rem again",
          "--nav-w:" in M.TOKEN_CSS and "--shell-gap:" in M.TOKEN_CSS)

    # Labels: every status either surface can render must have words.
    check("every task status reads as words", all(
        M.label(s) and " " not in M.label(s).strip()[:1] for s in M.STATUS))
    check("no label leaks the machine spelling",
        not any("_" in v for v in M.LABELS.values()))
    check("in_progress reads as English", M.label("in_progress") == "In progress")
    check("wontfix keeps its apostrophe", M.label("wontfix").startswith("Won"))
    check("an unknown status degrades to something readable, never to blank",
          M.label("awaiting_review") == "Awaiting review")
    check("a missing value is empty, not the string None",
          M.label(None) == "" and M.label("") == "")
    check("the flat map covers task AND bug statuses",
          set(M.STATUS) <= set(M.LABELS) and set(M.BUG_STATUS) <= set(M.LABELS))

    # --- ua: the ui/ read both surfaces share --------------------------------
    # _report_ui and _panel_ui are NOT imported here to check this end to end:
    # they sit a layer above, and reaching up for a test is the one shortcut
    # _deps.layer_violations() would be right to fail. These cases stand on
    # their own, against the real ui/ directory and against fixtures.
    _ASSETS = ("report.css", "report.js", "panel.html", "panel.css", "panel.js")
    # `os.path.dirname(os.path.abspath(__file__))` is what this said inline, and
    # it meant "the directory `_ui_theme.py` sits in". From `tests/` that clause
    # is simply FALSE - `UI_DIR` is not beside this file - and a case that has to
    # be edited to keep passing is a case that must be edited to say the same
    # thing about the SUBJECT rather than about wherever the suite happens to
    # live. `_harness.SCRIPTS_DIR` names it directly and cannot follow the test
    # file if the test file moves again.
    check("ua1 UI_DIR is the scripts/ui/ directory beside this module, and it "
          "holds every asset the two surfaces assemble",
          os.path.basename(M.UI_DIR) == "ui"
          and M.UI_DIR == os.path.join(_harness.SCRIPTS_DIR, "ui")
          and all(os.path.isfile(os.path.join(M.UI_DIR, n)) for n in _ASSETS))
    check("ua2 mutation proof: the same isfile test says NO to a name that is "
          "not in ui/, so the all() above is a result rather than a vacuous "
          "truth over an empty or wrong directory",
          not os.path.isfile(os.path.join(M.UI_DIR, "no-such-asset.css")))

    # newline="" is the load-bearing half of read_asset. Proving it needs a file
    # that actually holds CRLF, read BOTH ways: a fixture with LF endings reads
    # identically with or without the flag and would prove nothing.
    _uidir = _tf.mkdtemp(prefix="audit-uiasset-")
    _crlf = "crlf-fixture.css"
    with io.open(os.path.join(_uidir, _crlf), "w", encoding="utf-8",
                 newline="") as _fh:
        _fh.write(":root{\r\n  --a:1px;\r\n}\r\n")
    _kept = M.read_asset(_crlf, _uidir)
    with io.open(os.path.join(_uidir, _crlf), "r", encoding="utf-8") as _fh:
        _translated = _fh.read()          # same file, Python's default newline=None
    check("ua3 read_asset hands back the bytes that are on disk: newline='' "
          "means no line-ending translation, so a CRLF fixture arrives carrying "
          "all three of its \\r (got %d)" % _kept.count("\r"),
          _kept.count("\r") == 3 and "\r\n" in _kept)
    check("ua4 ...and the SAME file read without newline='' is a DIFFERENT "
          "string - 3 \\r silently translated away. That difference is the "
          "whole reason for the flag, and why .gitattributes pins "
          "scripts/ui/** to eol=lf",
          _translated.count("\r") == 0 and _translated != _kept
          and _translated == _kept.replace("\r\n", "\n"))
    with io.open(os.path.join(M.UI_DIR, "report.css"), "r", encoding="utf-8",
                 newline="") as _fh:
        _direct = _fh.read()
    check("ua5 read_asset defaults to UI_DIR and is byte for byte the read both "
          "surfaces already do, so adopting it changes nothing on screen",
          bool(_direct) and M.read_asset("report.css") == _direct)

    # cr_violations. The fixture carries a real \r on purpose: an all-LF one
    # cannot tell a working check apart from `return []`.
    _mixed = [("panel.html", "<html>\n</html>\n"),
              ("panel.css", ":root{--a:1px}\r\n"),
              ("panel.js", "boot();\n")]
    check("ua6 cr_violations names exactly the asset carrying a \\r, and only "
          "it (got %r)" % (M.cr_violations(_mixed),),
          M.cr_violations(_mixed) == ["panel.css"])
    check("ua7 mutation proof in the other direction: an all-LF fixture names "
          "NOTHING. Looks vacuous, and is the only case that goes red if the "
          "check ever becomes `[name for name, _text in assets]`",
          M.cr_violations([(n, t.replace("\r\n", "\n")) for n, t in _mixed]) == [])
    check("ua8 a LONE \\r counts too - the check is about the byte, not about "
          "the CRLF pair, so old-Mac endings are not waved through",
          M.cr_violations([("report.css", "a{}\rb{}")]) == ["report.css"])

    # unreadable_assets. Two failure shapes, and each proves a different half.
    _notutf8 = "not-utf8.css"
    with io.open(os.path.join(_uidir, _notutf8), "wb") as _fh:
        _fh.write(b":root{--a:'\xff\xfe'}\n")
    check("ua9 unreadable_assets is silent about the real assets - all five "
          "exist and decode as utf-8 (%r)" % (M.unreadable_assets(_ASSETS),),
          not M.unreadable_assets(_ASSETS))
    check("ua10 ...and names one that is not there, in the order given - so the "
          "empty list above is an answer, not a no-op",
          M.unreadable_assets(("report.css", "nope.css", "report.js"))
          == ["nope.css"])
    check("ua11 ...and one that EXISTS and does not decode as utf-8, while the "
          "CRLF fixture beside it decodes fine. A check written as "
          "os.path.isfile would pass ua10 and still miss this half",
          M.unreadable_assets((_crlf, _notutf8), _uidir) == [_notutf8])
    _sh.rmtree(_uidir, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__ui_theme.py --selftest\n")
    raise SystemExit(2)
