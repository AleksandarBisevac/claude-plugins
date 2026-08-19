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
import shutil
import tempfile
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
          # The DEFAULT, read from the module rather than spelled here. It used to
          # be the literal #0d9488; once the AA work moved --accent that literal
          # existed nowhere and the clause passed without substituting anything —
          # a pin that survives the value it was pinning is asserting nothing.
          and ("--accent:%s" % M.DEFAULT_THEME["--accent"]["$value"]) not in _c2)
    check("th4 ...and nothing else moves",
          ("--st-done:%s" % M.DEFAULT_THEME["--st-done"]["$value"]) in _c2
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
          # Read from the default rather than spelled: density scales spacing and
          # type, and the point here is that a COLOUR is untouched by it. Spelling
          # the hex made this go red for the AA token move, which is not what it
          # is watching for.
          and ("--accent:%s" % M.DEFAULT_THEME["--accent"]["$value"]) in _cmp)
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

    # --- ct: WCAG 1.4.3 and 1.4.11, computed off the sheet ---------------------
    # The finding these answer was a browser probe that named its failing pairs
    # once and went stale inside a week. Everything below re-derives.
    #
    # THE FUNCTION IS VERIFIED BEFORE ANY COLOUR IS JUDGED BY IT. Three published
    # values, one per decade of the range: the maximum, the AA boundary case that
    # every checker is calibrated on, and the teal that carried the original
    # finding. A contrast lint that agrees with itself and with nothing else is a
    # very confident way to be wrong.
    check("ct1 the ratio matches three published values - 21:1 for black on "
          "white, 4.54:1 for #767676 (the AA boundary grey), 3.74:1 for the teal "
          "the finding named (got %.2f / %.2f / %.2f)"
          % (M.contrast_ratio("#000000", "#ffffff"),
             M.contrast_ratio("#767676", "#ffffff"),
             M.contrast_ratio("#0d9488", "#ffffff")),
          M.contrast_ratio("#000000", "#ffffff") == 21.0
          and M.contrast_ratio("#767676", "#ffffff") == 4.54
          and M.contrast_ratio("#0d9488", "#ffffff") == 3.74
          # ...and it is symmetric, which is what makes "foreground" and
          # "background" a description rather than an argument order.
          and M.contrast_ratio("#0d9488", "#ffffff")
          == M.contrast_ratio("#ffffff", "#0d9488"))

    _sheets = M.themed_stylesheets()
    _audits = [(name, M.contrast_audit(css)) for name, css in _sheets]
    # THE VACUITY GUARD. "No violations" over no pairs is true of every palette
    # ever written, and the way to get there by accident is one line: the panel's
    # sheet carries a MARKER where the token layer goes, so a walk over the raw
    # file resolves nothing at all and reports a clean bill of health.
    check("ct2 the walk found pairs on both surfaces (%s) and the grounds it "
          "derived are the page's, not a guess (%s) - a comparison over zero "
          "pairs passes for any palette, which is how this check would lie"
          % (", ".join("%s %d" % (n, a["pairs"]) for n, a in _audits),
             _audits[0][1]["grounds"]),
          all(a["pairs"] > 40 for _n, a in _audits)
          and all(a["grounds"] == ["--bg", "--surface", "--surface-2"]
                  for _n, a in _audits))
    check("ct3 the token layer really is in front of each sheet - the panel's "
          "marker is in the asset and gone from the assembled string, so ct2's "
          "pair count is over resolved colours rather than over var() names "
          "nothing declares",
          "/*__THEME_TOKENS__*/" in M.read_asset("panel.css")
          and all("/*__THEME_TOKENS__*/" not in css for _n, css in _sheets)
          and all(":root{" in css for _n, css in _sheets))
    check("ct4 no text pair is under 4.5:1 and no control boundary under 3:1, "
          "on either surface, in either theme: %s"
          % ("; ".join(v for _n, a in _audits for v in a["violations"])
             or "clean"),
          not any(a["violations"] for _n, a in _audits))
    check("ct5 ...and what it stepped over is a number rather than a silence - "
          "color-mix() and rgba() are unresolvable and are skipped, never "
          "guessed (%s)"
          % ", ".join("%s %d" % (n, a["unresolved"]) for n, a in _audits),
          all(a["unresolved"] > 0 for _n, a in _audits))

    # The derivations, each proven in BOTH directions on a fixture. A predicate
    # that only ever says yes is not a predicate.
    _light = ":root{--bg:#ffffff;--faint:#dddddd;--ink:#767676;--mid:#8c8c8c}"
    _ground = _light + ".page{padding:1rem;background:var(--bg)}"
    check("ct6 a ground is DERIVED: a rule that paints a background, holds "
          "content (padding) and sets no ink of its own is one; the same rule "
          "with a fixed height is a swatch, and the same rule that sets its own "
          "colour hands nothing down",
          M.contrast_audit(_ground)["grounds"] == ["--bg"]
          and M.contrast_audit(
              _light + ".page{padding:1rem;height:2rem;background:var(--bg)}"
          )["grounds"] == []
          and M.contrast_audit(
              _light + ".page{padding:1rem;background:var(--bg);color:var(--ink)}"
          )["grounds"] == [])
    check("ct7 1.4.3 reads the co-declared pair when there is one and falls "
          "back to the grounds when there is not - and passes the same colours "
          "at a ratio that clears",
          M.contrast_audit(_ground + ".a{color:var(--faint);"
                           "background:var(--bg)}")["violations"]
          and M.contrast_audit(_ground + ".a{color:var(--faint)}")["violations"]
          and not M.contrast_audit(_ground + ".a{color:var(--ink)}")["violations"])
    check("ct8 large text takes the 3:1 floor and body text does not, so the "
          "same colour is a finding at one size and fine at the other - #8c8c8c "
          "measures %.2f:1, which is exactly between the two floors"
          % M.contrast_ratio("#8c8c8c", "#ffffff"),
          M.contrast_audit(_ground + ".a{color:var(--mid);font-size:.9rem}"
                           )["violations"]
          and not M.contrast_audit(_ground + ".a{color:var(--mid);"
                                   "font-size:1.6rem}")["violations"]
          and not M.contrast_audit(_ground + ".a{color:var(--mid);"
                                   "font-size:1.25rem;font-weight:700}"
                                   )["violations"])
    check("ct9 1.4.11 reaches a CONTROL boundary and not a decorative one - the "
          "same token, the same ratio, and only the rule that paints something "
          "a reader operates is a finding. A lint that failed both would have "
          "been routed around by dragging every hairline to 3:1",
          M.contrast_audit(_ground + "button.c{border:1px solid var(--faint)}"
                           )["violations"]
          and not M.contrast_audit(_ground + ".card{border:1px solid "
                                   "var(--faint)}")["violations"]
          # ...and the subject is the last compound: the BAR around a select is
          # not a control just because the select inside it is one.
          and not M.contrast_audit(
              _ground + ".bar select:focus{outline:none}"
              + ".bar{border:1px solid var(--faint)}")["violations"])
    check("ct10 a border the colour of its own fill is not a boundary - what "
          "identifies a solid button is the FILL against the page, so that is "
          "the pair judged, and it is judged rather than waved through",
          M.contrast_audit(
              _ground + "button.p{background:var(--faint);"
              "border-color:var(--faint)}")["violations"]
          and all("--faint on --bg" in v for v in M.contrast_audit(
              _ground + "button.p{background:var(--faint);"
              "border-color:var(--faint)}")["violations"]))

    # The exemptions: the legitimate shape passes, and the exemption cannot be
    # used as a route around the guard.
    _dis = _ground + 'button.c[aria-disabled="true"]{border:1px solid var(--faint)}'
    check("ct11 a disabled control is excused with the reason attached, and the "
          "SAME token on the SAME element without the disabled state is a "
          "finding - the exemption follows the state, not the token. Excused "
          "once per theme (the fixture declares one, so both read the same), "
          "counted rather than merely present",
          not M.contrast_audit(_dis)["violations"]
          and len(M.contrast_audit(_dis)["exempt"]) == 2
          # the excused line carries WHAT was excused and WHY, not just a count
          and all(w in M.contrast_audit(_dis)["exempt"][0]
                  for w in ("1.4.11", "--faint", "--bg", "disabled"))
          and M.contrast_audit(_ground + "button.c{border:1px solid "
                               "var(--faint)}")["violations"])
    # THE ROUTE AROUND THE GUARD, and the shape the first version shipped. It
    # deduplicated by pair as it walked, so the first rule to produce a pair
    # decided it for the whole sheet - and the panel's disabled-button rule sits
    # ABOVE the fields, so its correct exemption silenced nine controls below it.
    check("ct12 an excused rule cannot silence the same pair somewhere else: one "
          "disabled control and one live control wearing the same border is a "
          "FINDING, not an exemption",
          M.contrast_audit(_dis + "button.d{border:1px solid var(--faint)}"
                           )["violations"]
          and not M.contrast_audit(
              _dis + "button.d{border:1px solid var(--faint)}")["exempt"])
    check("ct13 a placeholder is excused and the same colour on the field "
          "itself is not - a hint about an empty field is quieter on purpose, "
          "and raising it makes an empty field look filled",
          not M.contrast_audit(_ground + "input.q::placeholder{color:var(--faint)}"
                               )["violations"]
          and M.contrast_audit(_ground + "input.q{color:var(--faint)}")["violations"])
    check("ct14 an exemption is a claim about the sheet and decays like one: "
          "over the real sheets it names nothing (%s), over an empty sheet it "
          "names every entry, and a TOKEN entry naming something no rule "
          "declares is reported too"
          % (M.contrast_exemption_problems("".join(c for _n, c in _sheets)) or "-",),
          not M.contrast_exemption_problems("".join(c for _n, c in _sheets))
          and len(M.contrast_exemption_problems("")) == len(M.CONTRAST_EXEMPTIONS)
          and M.contrast_exemption_problems(
              _light, (("token", "--gone", "1.4.11", "no reason survives it"),))
          and not M.contrast_exemption_problems(
              _light, (("token", "--faint", "1.4.11", "declared right there"),)))

    # The two trap doors, each of which produced a wrong NUMBER rather than a
    # missing one - which is worse, and is why both are pinned.
    _dark = (":root{--bg:#ffffff;--ink:#111111}"
             '@media (prefers-color-scheme:dark){:root:not([data-theme="light"])'
             "{--bg:#000000;--ink:#eeeeee}}"
             ".page{padding:1rem;background:var(--bg)}.a{color:var(--ink)}")
    check("ct15 @media print is cut out before the walk: the report's print "
          "sheet re-declares the DARK tokens as a white page, and reading it "
          "measures a palette nobody sees. Renaming that block to @media screen "
          "makes the same fixture fail, which is what proves the cut is doing it",
          not M.contrast_audit(
              _dark + '@media print{:root,:root[data-theme="dark"]'
              "{--bg:#ffffff}}")["violations"]
          and M.contrast_audit(
              _dark + '@media screen{:root,:root[data-theme="dark"]'
              "{--bg:#ffffff}}")["violations"])
    check("ct16 a colour written as a FUNCTION is skipped and counted, never "
          "half-parsed: reading the first var() out of a color-mix would report "
          "the unmixed colour's ratio, and a wrong number is worse than a "
          "missing one",
          not M.contrast_audit(
              _ground + ".a{color:color-mix(in srgb,var(--faint) 50%,white)}"
          )["violations"]
          and M.contrast_audit(
              _ground + ".a{color:color-mix(in srgb,var(--faint) 50%,white)}"
          )["unresolved"] == 1
          and M.contrast_audit(_ground + ".a{color:var(--faint)}")["violations"])

    # The tokens the audit moved, pinned by the PROPERTY that made each value
    # right rather than by the hex, so a future retune is judged, not blocked.
    _fb = M.DEFAULT_THEME["--field-border"]
    _fbh = M.DEFAULT_THEME["--field-border-hover"]
    check("ct17 the hover boundary is a token of its own and is STRONGER than "
          "the resting one in both themes - it used to be --border-strong, "
          "which is structure, so hovering a button made its edge fainter than "
          "at rest (light %.2f:1 over %.2f:1, dark %.2f:1 over %.2f:1)"
          % (M.contrast_ratio(_fbh["$value"], "#ffffff"),
             M.contrast_ratio(_fb["$value"], "#ffffff"),
             M.contrast_ratio(_fbh["$dark"], "#111a2b"),
             M.contrast_ratio(_fb["$dark"], "#111a2b")),
          M.contrast_ratio(_fbh["$value"], "#ffffff")
          > M.contrast_ratio(_fb["$value"], "#ffffff")
          and M.contrast_ratio(_fbh["$dark"], "#111a2b")
          > M.contrast_ratio(_fb["$dark"], "#111a2b")
          and "--field-border-hover" in M.THEME_TOKENS
          and M.TOKEN_CSS.count("--field-border-hover:") == 3)
    _as = M.DEFAULT_THEME["--accent-solid"]
    check("ct18 --accent-solid answers both criteria at once and they pull "
          "opposite ways: the fill has to clear 3:1 against the card it sits on "
          "AND carry white at 4.5:1. Light %.2f/%.2f, dark %.2f/%.2f"
          % (M.contrast_ratio(_as["$value"], "#eef2f7"),
             M.contrast_ratio("#ffffff", _as["$value"]),
             M.contrast_ratio(_as["$dark"], "#172236"),
             M.contrast_ratio("#ffffff", _as["$dark"])),
          M.contrast_ratio(_as["$value"], "#eef2f7") >= 3.0
          and M.contrast_ratio("#ffffff", _as["$value"]) >= 4.5
          and M.contrast_ratio(_as["$dark"], "#172236") >= 3.0
          and M.contrast_ratio("#ffffff", _as["$dark"]) >= 4.5)
    check("ct19 the amber fill is never ink: --st-prog is a FILL and unreadable "
          "as text on every surface here (%.2f:1 on white), which is what "
          "--st-prog-ink exists for - neither sheet uses the fill as a colour"
          % M.contrast_ratio(
              M.DEFAULT_THEME["--st-prog"]["$value"], "#ffffff"),
          M.contrast_ratio(M.DEFAULT_THEME["--st-prog"]["$value"], "#ffffff") < 4.5
          and not any(re.search(r"(?<![-\w])color\s*:\s*var\(--st-prog\)", css)
                      for _n, css in _sheets))

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
    # Derived, not restated: this tuple used to be a second copy of the same
    # list, and splitting report.js into ordered parts turned it red along
    # with two others. `ua_decl` below is what keeps the one copy honest.
    _ASSETS = M.UI_ASSETS
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
          M.unreadable_assets(("report.css", "nope.css",
                               "report/page-state.js"))
          == ["nope.css"])
    check("ua11 ...and one that EXISTS and does not decode as utf-8, while the "
          "CRLF fixture beside it decodes fine. A check written as "
          "os.path.isfile would pass ua10 and still miss this half",
          M.unreadable_assets((_crlf, _notutf8), _uidir) == [_notutf8])
    _sh.rmtree(_uidir, ignore_errors=True)

    # --- assets live in feature directories, so every walk must descend --------
    _ua_nested = [n for n in M.UI_ASSETS if "/" in n]
    check("ua12 the declared asset list carries files from feature "
          "subdirectories (%d of %d), so a walk that stopped at the top level "
          "would disagree with it rather than pass quietly"
          % (len(_ua_nested), len(M.UI_ASSETS)),
          _ua_nested and M.declared_asset_drift() == ([], []))
    _ua_tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(_ua_tmp, "sub"))
        with io.open(os.path.join(_ua_tmp, "sub", "extra.js"), "w") as _fh:
            _fh.write("var x = 1;\n")
        with io.open(os.path.join(_ua_tmp, "sub", "NOTES.md"), "w") as _fh:
            _fh.write("# notes\n")
        _missing, _undeclared = M.declared_asset_drift(_ua_tmp)
        check("ua13 a file added inside a subdirectory is REPORTED as undeclared "
              "- the walk descends, and an asset nobody declared is the quiet "
              "failure (got %r)" % (_undeclared,),
              _undeclared == ["sub/extra.js"])
        check("ua14 ...and documentation beside it is not, because a README is "
              "never assembled into a page - only %r suffixes count"
              % (M._ASSET_SUFFIXES,),
              "sub/NOTES.md" not in _undeclared)
    finally:
        shutil.rmtree(_ua_tmp, ignore_errors=True)



def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__ui_theme.py --selftest\n")
    raise SystemExit(2)
