#!/usr/bin/env python3
"""
The cases for `_ui_theme_lints.py` - the contrast audit, the asset reads' failure
shapes and the check that the audited stylesheet is the shipped one, which were the
second half of `_ui_theme.py` before the lints left the plugin.

`L` is the module under test and `M` is `_ui_theme`, whose token layer and asset read
the lints are built on. The cases for what stayed are in `tests/test__ui_theme.py`.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import io
import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _ui_theme as M                              # noqa: E402
import _ui_theme_lints as L                          # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    # uc: the empty bucket has ONE name, and it is not its storage key.
    import tempfile as _tf

    _sheets = L.themed_stylesheets()
    _audits = [(name, L.contrast_audit(css)) for name, css in _sheets]
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

    # The derivations, each proven in BOTH directions on a fixture. A predicate
    # that only ever says yes is not a predicate.
    _light = ":root{--bg:#ffffff;--faint:#dddddd;--ink:#767676;--mid:#8c8c8c}"
    _ground = _light + ".page{padding:1rem;background:var(--bg)}"
    check("ct6 a ground is DERIVED: a rule that paints a background, holds "
          "content (padding) and sets no ink of its own is one; the same rule "
          "with a fixed height is a swatch, and the same rule that sets its own "
          "colour hands nothing down",
          L.contrast_audit(_ground)["grounds"] == ["--bg"]
          and L.contrast_audit(
              _light + ".page{padding:1rem;height:2rem;background:var(--bg)}"
          )["grounds"] == []
          and L.contrast_audit(
              _light + ".page{padding:1rem;background:var(--bg);color:var(--ink)}"
          )["grounds"] == [])
    check("ct7 1.4.3 reads the co-declared pair when there is one and falls "
          "back to the grounds when there is not - and passes the same colours "
          "at a ratio that clears",
          L.contrast_audit(_ground + ".a{color:var(--faint);"
                           "background:var(--bg)}")["violations"]
          and L.contrast_audit(_ground + ".a{color:var(--faint)}")["violations"]
          and not L.contrast_audit(_ground + ".a{color:var(--ink)}")["violations"])
    check("ct8 large text takes the 3:1 floor and body text does not, so the "
          "same colour is a finding at one size and fine at the other - #8c8c8c "
          "measures %.2f:1, which is exactly between the two floors"
          % M.contrast_ratio("#8c8c8c", "#ffffff"),
          L.contrast_audit(_ground + ".a{color:var(--mid);font-size:.9rem}"
                           )["violations"]
          and not L.contrast_audit(_ground + ".a{color:var(--mid);"
                                   "font-size:1.6rem}")["violations"]
          and not L.contrast_audit(_ground + ".a{color:var(--mid);"
                                   "font-size:1.25rem;font-weight:700}"
                                   )["violations"])
    check("ct9 1.4.11 reaches a CONTROL boundary and not a decorative one - the "
          "same token, the same ratio, and only the rule that paints something "
          "a reader operates is a finding. A lint that failed both would have "
          "been routed around by dragging every hairline to 3:1",
          L.contrast_audit(_ground + "button.c{border:1px solid var(--faint)}"
                           )["violations"]
          and not L.contrast_audit(_ground + ".card{border:1px solid "
                                   "var(--faint)}")["violations"]
          # ...and the subject is the last compound: the BAR around a select is
          # not a control just because the select inside it is one.
          and not L.contrast_audit(
              _ground + ".bar select:focus{outline:none}"
              + ".bar{border:1px solid var(--faint)}")["violations"])
    check("ct10 a border the colour of its own fill is not a boundary - what "
          "identifies a solid button is the FILL against the page, so that is "
          "the pair judged, and it is judged rather than waved through",
          L.contrast_audit(
              _ground + "button.p{background:var(--faint);"
              "border-color:var(--faint)}")["violations"]
          and all("--faint on --bg" in v for v in L.contrast_audit(
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
          not L.contrast_audit(_dis)["violations"]
          and len(L.contrast_audit(_dis)["exempt"]) == 2
          # the excused line carries WHAT was excused and WHY, not just a count
          and all(w in L.contrast_audit(_dis)["exempt"][0]
                  for w in ("1.4.11", "--faint", "--bg", "disabled"))
          and L.contrast_audit(_ground + "button.c{border:1px solid "
                               "var(--faint)}")["violations"])
    # THE ROUTE AROUND THE GUARD, and the shape the first version shipped. It
    # deduplicated by pair as it walked, so the first rule to produce a pair
    # decided it for the whole sheet - and the panel's disabled-button rule sits
    # ABOVE the fields, so its correct exemption silenced nine controls below it.
    check("ct12 an excused rule cannot silence the same pair somewhere else: one "
          "disabled control and one live control wearing the same border is a "
          "FINDING, not an exemption",
          L.contrast_audit(_dis + "button.d{border:1px solid var(--faint)}"
                           )["violations"]
          and not L.contrast_audit(
              _dis + "button.d{border:1px solid var(--faint)}")["exempt"])
    check("ct13 a placeholder is excused and the same colour on the field "
          "itself is not - a hint about an empty field is quieter on purpose, "
          "and raising it makes an empty field look filled",
          not L.contrast_audit(_ground + "input.q::placeholder{color:var(--faint)}"
                               )["violations"]
          and L.contrast_audit(_ground + "input.q{color:var(--faint)}")["violations"])
    check("ct14 an exemption is a claim about the sheet and decays like one: "
          "over the real sheets it names nothing (%s), over an empty sheet it "
          "names every entry, and a TOKEN entry naming something no rule "
          "declares is reported too"
          % (L.contrast_exemption_problems("".join(c for _n, c in _sheets)) or "-",),
          not L.contrast_exemption_problems("".join(c for _n, c in _sheets))
          and len(L.contrast_exemption_problems("")) == len(L.CONTRAST_EXEMPTIONS)
          and L.contrast_exemption_problems(
              _light, (("token", "--gone", "1.4.11", "no reason survives it"),))
          and not L.contrast_exemption_problems(
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
          not L.contrast_audit(
              _dark + '@media print{:root,:root[data-theme="dark"]'
              "{--bg:#ffffff}}")["violations"]
          and L.contrast_audit(
              _dark + '@media screen{:root,:root[data-theme="dark"]'
              "{--bg:#ffffff}}")["violations"])
    check("ct16 a colour written as a FUNCTION is skipped and counted, never "
          "half-parsed: reading the first var() out of a color-mix would report "
          "the unmixed colour's ratio, and a wrong number is worse than a "
          "missing one",
          not L.contrast_audit(
              _ground + ".a{color:color-mix(in srgb,var(--faint) 50%,white)}"
          )["violations"]
          and L.contrast_audit(
              _ground + ".a{color:color-mix(in srgb,var(--faint) 50%,white)}"
          )["unresolved"] == 1
          and L.contrast_audit(_ground + ".a{color:var(--faint)}")["violations"])

    # --- ua: the ui/ read both surfaces share --------------------------------
    # _report_ui and _panel_ui are NOT imported here to check this end to end:
    # they sit a layer above, and reaching up for a test is the one shortcut
    # _deps.layer_violations() would be right to fail. These cases stand on
    # their own, against the real ui/ directory and against fixtures.
    # Derived, not restated: this tuple used to be a second copy of the same
    # list, and splitting report.js into ordered parts turned it red along
    # with two others. `ua_decl` below is what keeps the one copy honest.
    _ASSETS = L.UI_ASSETS
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

    # newline="" is the load-bearing half of read_asset. Proving it needs a file
    # that actually holds CRLF, read BOTH ways: a fixture with LF endings reads
    # identically with or without the flag and would prove nothing.
    _uidir = _tf.mkdtemp(prefix="audit-uiasset-")
    _crlf = "crlf-fixture.css"
    with io.open(os.path.join(_uidir, _crlf), "w", encoding="utf-8",
                 newline="") as _fh:
        _fh.write(":root{\r\n  --a:1px;\r\n}\r\n")

    # unreadable_assets. Two failure shapes, and each proves a different half.
    _notutf8 = "not-utf8.css"
    with io.open(os.path.join(_uidir, _notutf8), "wb") as _fh:
        _fh.write(b":root{--a:'\xff\xfe'}\n")
    check("ua9 unreadable_assets is silent about the real assets - all five "
          "exist and decode as utf-8 (%r)" % (L.unreadable_assets(_ASSETS),),
          not L.unreadable_assets(_ASSETS))
    check("ua10 ...and names one that is not there, in the order given - so the "
          "empty list above is an answer, not a no-op",
          L.unreadable_assets(("report-css/shell.css", "nope.css",
                               "report/page-state.js"))
          == ["nope.css"])
    check("ua11 ...and one that EXISTS and does not decode as utf-8, while the "
          "CRLF fixture beside it decodes fine. A check written as "
          "os.path.isfile would pass ua10 and still miss this half",
          L.unreadable_assets((_crlf, _notutf8), _uidir) == [_notutf8])
    _harness.remove_tree(_uidir)


    # --- the audited sheet must be the shipped sheet --------------------------
    _rc = M.REPORT_CSS_PARTS
    check("cs2 every declared part exists and every report-css asset is "
          "declared - a part on disk that the sheet does not join is a feature "
          "that silently never ships",
          set(_rc) == set(n for n in L.UI_ASSETS if n.startswith("report-css/")))
    _shipped = M.TOKEN_CSS + "".join(M.read_asset(_n) for _n in _rc)
    check("cs3 the sheet the theme lints audit IS the sheet the page receives, "
          "byte for byte - auditing a differently-ordered join would clear a "
          "palette nobody serves",
          dict(L.themed_stylesheets())["report"] == _shipped)

    # The panel's sheet, same three claims. It is a SEPARATE tuple with a
    # separate failure: the report's parts could be perfectly declared while the
    # panel joined its own alphabetically, and no case above would notice.
    _pc = M.PANEL_CSS_PARTS
    check("cs5 every declared panel part exists and every panel-css asset is "
          "declared - a part on disk that the sheet does not join is a feature "
          "that silently never ships",
          set(_pc) == set(n for n in L.UI_ASSETS if n.startswith("panel-css/")))
    _panel_join = "".join(M.read_asset(_n) for _n in _pc)
    check("cs7 the panel sheet the theme lints audit IS the one the browser "
          "receives, byte for byte - the marker replaced, the parts in "
          "declared order",
          dict(L.themed_stylesheets())["panel"]
          == _panel_join.replace("/*__THEME_TOKENS__*/", M.TOKEN_CSS))

def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__ui_theme_lints.py --selftest\n")
    raise SystemExit(2)
