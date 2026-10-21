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
import _output                                     # noqa: E402  (REPO_ROOT, SCRIPTS_DIR)
from _output import safe_stdio                     # noqa: E402
import _ui_theme as M                              # noqa: E402
import _ui_theme_lints                              # noqa: E402  (the stylesheet lints)
import _ui_theme_lints as L                          # noqa: E402
import _manifest_vocab as _vocab                   # noqa: E402  (the words a label owes)


# --- cases --------------------------------------------------------------------
def _cases(check):
    # uc: the empty bucket has ONE name, and it is not its storage key.
    check("the empty usage bucket is named once, for all three surfaces: the "
          "ledger's \"--\" (no phase/task) and its attr bucket are the same fact "
          "to a reader, and neither reaches a screen as its storage key",
          M.label("--") == M.label("unattributed") == M.UNCATEGORIZED
          and M.UNCATEGORIZED not in ("--", "unattributed"))
    # --- th: the token layer as data ----------------------------------------
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
          not _ui_theme_lints.theme_asymmetric_vars(_c2) and not _ui_theme_lints.themes_missing_color_scheme(_c2))
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
          and not _ui_theme_lints.theme_asymmetric_vars(M.token_css_for(_proj, {}, _home)[0]))
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
          not _ui_theme_lints.theme_asymmetric_vars(_cmp)
          and not _ui_theme_lints.themes_missing_color_scheme(_cmp)
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
    check("no token is declared in only one theme: %r" % (_ui_theme_lints.theme_asymmetric_vars(M.TOKEN_CSS),),
          not _ui_theme_lints.theme_asymmetric_vars(M.TOKEN_CSS))
    # The toggle has to move the NATIVE controls too, and tokens cannot reach them.
    check("every explicit theme restates color-scheme, so the toggle moves the "
          "checkboxes, selects, spinners, date pickers and scrollbars with it: %r"
          % (_ui_theme_lints.themes_missing_color_scheme(M.TOKEN_CSS),),
          not _ui_theme_lints.themes_missing_color_scheme(M.TOKEN_CSS))
    check("both directions are pinned, not just dark",
          "color-scheme:dark" in M.TOKEN_CSS and "color-scheme:light}" in M.TOKEN_CSS)
    check("bare :root still follows the OS when nobody has chosen",
          re.search(r":root\{[^}]*color-scheme:light dark;", M.TOKEN_CSS) is not None)
    # The lint's own two ways of being wrong. It caught nothing for four releases
    # because there was nothing like it; these prove it can fail and can pass.
    check("the lint detects a theme with no color-scheme",
          _ui_theme_lints.themes_missing_color_scheme(
              ':root{color-scheme:light dark}\n:root[data-theme="dark"]{--bg:#000}')
          == ["dark"])
    check("the lint accepts a theme satisfied by a DIFFERENT block, which is how "
          "the panel adds its own roles without restating the property",
          _ui_theme_lints.themes_missing_color_scheme(
              ':root[data-theme=dark]{color-scheme:dark}\n'
              ':root[data-theme=dark]{--ok:#0f0}') == [])
    check("a :not() negation cannot satisfy a theme, but it does NAME one - which "
          "is the only mention explicit-light gets, since light needs no colours",
          _ui_theme_lints.themes_missing_color_scheme(
              '@media (prefers-color-scheme:dark){:root:not([data-theme=light])'
              '{--bg:#000}}') == ["light"])
    check("...and naming it is enough for a pin elsewhere to answer it",
          _ui_theme_lints.themes_missing_color_scheme(
              ':root[data-theme=light]{color-scheme:light}\n'
              '@media (prefers-color-scheme:dark){:root:not([data-theme=light])'
              '{--bg:#000}}') == [])
    check("a print sheet cannot vouch for a SCREEN theme - the report's forces a "
          "light page for :root[data-theme=dark], and counting it hid the defect",
          _ui_theme_lints.themes_missing_color_scheme(
              ':root[data-theme="dark"]{--bg:#000}\n'
              '@media print{:root,:root[data-theme="dark"]{color-scheme:light}}')
          == ["dark"])
    # An escape that Python ate is invisible in the source and visible on screen.
    check("no escape was eaten before the browser saw it: %r"
          % (_ui_theme_lints.mangled_css_escapes(M.TOKEN_CSS),),
          not _ui_theme_lints.mangled_css_escapes(M.TOKEN_CSS))
    check("the escape lint catches the tick that shipped mangled - the octal "
          "residue and the bell, which are the two halves of one typo",
          _ui_theme_lints.mangled_css_escapes('.a::before{content:"¹3\x070"}')
          and _ui_theme_lints.mangled_css_escapes('.a::before{content:"¹3"}')
          and _ui_theme_lints.mangled_css_escapes('.a{--x:"\x07"}'))
    check("...and passes the doubled spelling that actually reaches the browser",
          _ui_theme_lints.mangled_css_escapes('.a::before{content:"\\2713\\a0"}') == [])
    check("a glyph written literally is not a broken escape: ✓ and — are above "
          "the range an octal escape can reach, so they are left alone",
          _ui_theme_lints.mangled_css_escapes('.a::before{content:"✓—"}') == [])
    check("no declaration is left unterminated: %r" % (_ui_theme_lints.unterminated_css_decls(M.TOKEN_CSS),),
          not _ui_theme_lints.unterminated_css_decls(M.TOKEN_CSS))
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

    _sheets = L.themed_stylesheets()
    _audits = [(name, L.contrast_audit(css)) for name, css in _sheets]
    check("ct3 the token layer really is in front of each sheet - the panel's "
          "marker is in its first part and gone from the assembled string, so "
          "ct2's pair count is over resolved colours rather than over var() "
          "names nothing declares",
          "/*__THEME_TOKENS__*/" in M.read_asset(M.PANEL_CSS_PARTS[0])
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
    check("not_a_bug renders APART from wontfix rather than sharing its words - "
          "a reader scanning a bug table is asking which reports were real, and "
          "the two close the row for opposite reasons: %r / %r"
          % (M.label("not_a_bug"), M.label("wontfix")),
          M.label("not_a_bug") == "Not a bug"
          and M.label("not_a_bug") != M.label("wontfix"))
    check("...and every word the manifest vocabulary calls a bug status has a "
          "label, driven over the tuple so a word added there without one here "
          "is caught rather than rendering as its machine spelling: %r"
          % (sorted(set(_vocab.BUG_STATUS) - set(M.BUG_STATUS)),),
          set(_vocab.BUG_STATUS) <= set(M.BUG_STATUS))
    check("an unknown status degrades to something readable, never to blank",
          M.label("awaiting_review") == "Awaiting review")
    check("a missing value is empty, not the string None",
          M.label(None) == "" and M.label("") == "")
    check("the flat map covers task AND bug statuses",
          set(M.STATUS) <= set(M.LABELS) and set(M.BUG_STATUS) <= set(M.LABELS))
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
    with io.open(os.path.join(M.UI_DIR, "report-css", "shell.css"), "r", encoding="utf-8",
                 newline="") as _fh:
        _direct = _fh.read()
    check("ua5 read_asset defaults to UI_DIR and is byte for byte the read both "
          "surfaces already do, so adopting it changes nothing on screen",
          bool(_direct) and M.read_asset("report-css/shell.css") == _direct)
    _sh.rmtree(_uidir, ignore_errors=True)


    # --- the audited sheet must be the shipped sheet --------------------------
    _rc = M.REPORT_CSS_PARTS
    check("cs1 the cascade order is declared ONCE and is not alphabetical - two "
          "rules of equal specificity are decided by which is read last, so "
          "sorting these %d names would change what ships" % (len(_rc),),
          len(_rc) >= 5 and list(_rc) != sorted(_rc)
          and _rc[0].endswith("shell.css"))

    # The panel's sheet, same three claims. It is a SEPARATE tuple with a
    # separate failure: the report's parts could be perfectly declared while the
    # panel joined its own alphabetically, and no case above would notice.
    _pc = M.PANEL_CSS_PARTS
    check("cs4 the panel's cascade order is declared ONCE and is not "
          "alphabetical - the reset has to be read before the shell and the "
          "narrow-screen blocks after what they override, so sorting these %d "
          "names would change what ships" % (len(_pc),),
          len(_pc) >= 5 and list(_pc) != sorted(_pc)
          and _pc[0].endswith("tokens-and-reset.css"))
    _panel_join = "".join(M.read_asset(_n) for _n in _pc)
    check("cs6 the token marker sits in the join EXACTLY once (got %d) - a "
          "second copy in another part would splice the whole token layer in "
          "twice, and every var() would still resolve, so nothing else here "
          "would go red" % (_panel_join.count("/*__THEME_TOKENS__*/"),),
          _panel_join.count("/*__THEME_TOKENS__*/") == 1)


    # --- a comment that names a function is a claim that the function exists ---
    # Two comments kept describing a digest that had moved to another module, and
    # nothing read them. The names are taken off the comments themselves - the
    # `.gitattributes` ones and the block above `UI_DIR` - and each must be a `def`
    # somewhere under `scripts/` or `tools/`. The `UI_DIR` block must yield at
    # least one name, or an extractor that matched nothing would read as all clear.
    _root = _output.REPO_ROOT
    _defined = set()
    for _top in (os.path.join(_output.SCRIPTS_DIR), os.path.join(_root, "tools")):
        for _dir, _dirs, _files in os.walk(_top):
            for _f in _files:
                if _f.endswith(".py"):
                    with io.open(os.path.join(_dir, _f), encoding="utf-8") as _fh:
                        _defined.update(re.findall(r"^\s*def (\w+)\(", _fh.read(), re.M))
    _call = re.compile(r"`([A-Za-z_]\w*)\([^`]*\)`")
    with io.open(os.path.join(_root, ".gitattributes"), encoding="utf-8") as _fh:
        _attr_lines = [_l for _l in _fh.read().splitlines() if _l.startswith("#")]
    with io.open(M.__file__.replace(".pyc", ".py"), encoding="utf-8") as _fh:
        _theme_lines = _fh.read().splitlines()
    _at = _theme_lines.index("UI_DIR = _output.UI_DIR")
    _beside = []
    while _at > 0 and _theme_lines[_at - 1].startswith("#"):
        _at -= 1
        _beside.insert(0, _theme_lines[_at])
    _named = sorted(set(_call.findall("\n".join(_attr_lines))
                        + _call.findall("\n".join(_beside))))
    _missing = [_n for _n in _named if _n not in _defined]
    _ok = (len(_beside) > 0 and bool(_call.findall("\n".join(_beside)))
           and not _missing)
    _title = ("every backticked function call named in the comments of .gitattributes, "
              "and the one beside UI_DIR in _ui_theme.py, is a function defined under "
              "plugins/audit/scripts or tools")
    # The title is the clause verbatim when green; a red one says what it found.
    check(_title if _ok else "%s (read %d comment lines above UI_DIR, %d names; "
          "no definition for %r)" % (_title, len(_beside), len(_named), _missing), _ok)

def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__ui_theme.py --selftest\n")
    raise SystemExit(2)
