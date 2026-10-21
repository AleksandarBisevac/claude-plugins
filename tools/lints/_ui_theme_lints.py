#!/usr/bin/env python3
"""
The stylesheet lints and the contrast audit - development code, kept out of the
shipped plugin.

`_ui_theme` is the token layer both surfaces import, and the lints that police the
assembled stylesheet used to live beside it: undeclared custom properties,
unterminated declarations, asymmetric light/dark tokens, mangled escapes, a missing
`color-scheme`, and the contrast audit over the theme. They judge what the assets
ASSEMBLE to, never what a user asks for, so nothing a running panel or report calls
reads them; they leave with the other development modules to `tools/lints/`, under
a basename that collides with nothing in `scripts/`.

What stayed in `_ui_theme.py` is the token layer, the theme compiler and loader, the
labels, and the one read that puts `scripts/ui/` in front of the surfaces.

`install_path()` never puts this directory on `sys.path`, so a development caller
(the harness, a tool) adds it itself.

This module carries no `--selftest`; its cases live in `tests/test__ui_theme_lints.py`.
"""
import os
import re
import sys
import _output

# The path bootstrap for a development module that lives OUTSIDE the plugin: it
# walks UP to the directory that holds `plugins/audit/scripts/_output.py` instead
# of counting `dirname()` calls, so it does not encode how deep this file sits.
# `install_path()` then adds `scripts/` and every subdirectory of it holding a
# `.py`, so every sibling below is reached by a bare basename.
_anchor_root = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_anchor_root, "plugins", "audit", "scripts",
                                      "_output.py")):
    _anchor_up = os.path.dirname(_anchor_root)
    if _anchor_up == _anchor_root:
        raise ImportError("audit lints: walked to the filesystem root from %s "
                          "without finding plugins/audit/scripts/_output.py - the "
                          "repository root is gone and no sibling can be imported"
                          % (__file__,))
    _anchor_root = _anchor_up
_anchor_dir = os.path.join(_anchor_root, "plugins", "audit", "scripts")
if _anchor_dir not in sys.path:
    sys.path.insert(0, _anchor_dir)


_output.install_path()

from _ui_theme import (  # noqa: E402
    PANEL_CSS_PARTS, REPORT_CSS_PARTS, THEME_SINGLE,
    THEME_TOKENS, TOKEN_CSS, contrast_ratio, read_asset)



# ...with two exceptions that are colour-BEARING but not colours: the shadows
# are declared in both themes, so they are paired like a colour.
THEME_PAIRED = tuple(t for t in THEME_TOKENS if t not in THEME_SINGLE)

# Every file `scripts/ui/` holds, DECLARED once. Three suites used to carry their
# own copy of this tuple, and splitting `report.js` into ordered parts turned all
# three red at once. NOTHING COMPARES THIS WITH THE DIRECTORY ANY MORE - the lint
# that did, in both directions, was retired - so a part added under `ui/` is
# declared here by its author, and the failure that leaves is the quiet one: the
# page assembles without the part and every substring pin goes on passing against
# a script missing a whole feature. Documentation beside the parts is not an asset.
UI_ASSETS = (
    "panel-css/app-shell.css",
    "panel-css/appearance-table.css",
    "panel-css/base-controls.css",
    "panel-css/blocks-and-ado.css",
    "panel-css/browse-dialog.css",
    "panel-css/combobox.css",
    "panel-css/composition.css",
    "panel-css/confirm-dialog.css",
    "panel-css/help-drawer.css",
    "panel-css/identity-pill.css",
    "panel-css/labels-and-hints.css",
    "panel-css/overview-filters.css",
    "panel-css/overview-rows.css",
    "panel-css/policy.css",
    "panel-css/proposals.css",
    "panel-css/save-result.css",
    "panel-css/settings-form.css",
    "panel-css/status-colours.css",
    "panel-css/tokens-and-reset.css",
    "panel-css/tooltip.css",
    "panel-css/usage-heatmap.css",
    "panel-css/usage-narrow.css",
    "panel-css/usage-tab.css",
    "panel-css/usage-tables.css",
    "panel.html",
    "panel/ado-connector.js",
    "panel/branch-convention.js",
    "panel/appearance-view.js",
    "panel/boot.js",
    "panel/browse-dialog.js",
    "panel/composition.js",
    "panel/core.js",
    "panel/help-drawer.js",
    "panel/hints.js",
    "panel/overview.js",
    "panel/policy-state.js",
    "panel/policy-view.js",
    "panel/proposals-view.js",
    "panel/run-status.js",
    "panel/settings.js",
    "panel/theme-state.js",
    "panel/usage-cards.js",
    "panel/usage-charts.js",
    "panel/usage-filtering.js",
    "panel/usage-metrics.js",
    "panel/usage-model.js",
    "panel/usage-view.js",
    "panel/version-banner.js",
    "panel/write-confirmation.js",
    "report-css/badges.css",
    "report-css/controls.css",
    "report-css/empty-state.css",
    "report-css/forced-colors.css",
    "report-css/gate-rail.css",
    "report-css/motion-and-print.css",
    "report-css/print-segments.css",
    "report-css/ready-now.css",
    "report-css/segments.css",
    "report-css/shell.css",
    "report-css/summary.css",
    "report-css/tables.css",
    "report-css/usage.css",
    "report/areas.js",
    "report/authors.js",
    "report/chips.js",
    "report/date-range.js",
    "report/exports.js",
    "report/filters.js",
    "report/heatmap.js",
    "report/page-state.js",
    "report/sorting.js",
    "report/usage-range.js",
    "shared/clipboard.js",
    "shared/dates.js",
    "shared/calendar.js",
    "shared/download.js",
    "shared/lookup.js",
    "shared/plural.js",
    "shared/storage.js",
    "shared/theme.js",
)


def unreadable_assets(names, directory=None):
    """The named `ui/` assets that are missing or do not decode as utf-8.

    Returned in the order given, so a caller can still report one case per asset
    rather than one verdict for the set. Both surfaces ask this first, before any
    pin about the content: the failure it catches is not a bad stylesheet but a
    file renamed, dropped from the package, or committed in another encoding —
    and every later pin would then die with a traceback pointing at the wrong
    thing.

    The exception tuple is the policy here, and it is why this is a function
    rather than an `os.path.isfile` at each site: an asset that EXISTS and does
    not decode is exactly the half `isfile` cannot see."""
    bad = []
    for name in names:
        try:
            read_asset(name, directory)
        except (IOError, OSError, UnicodeDecodeError):
            bad.append(name)
    return bad


# --- contrast: the two criteria, computed rather than measured -------------------
# SC 1.4.3 (Contrast Minimum) and SC 1.4.11 (Non-text Contrast) are the only rules
# in this product whose verdict is a NUMBER, and a number is the kind of claim that
# rots the moment somebody edits a swatch. The finding that produced this section
# was a browser probe: it named its failing pairs once, in a report, and the palette
# moved underneath it inside a week. So the ratios are COMPUTED here, off the
# stylesheet, and re-derived on every run instead of being written down.
#
# WHAT "USED AGAINST" MEANS, because that is the whole difficulty. CSS declares
# colours; it does not declare which colour sits on which, since that is the DOM's
# business. Three derivations, each weaker than the one above it:
#
#   1. CO-DECLARED. One rule sets `color` and `background` - the pair is stated
#      outright and nothing is inferred. Buttons, chips and badges are here.
#   2. THE GROUNDS. A rule that sets `color` and no background inherits one from an
#      ancestor. The candidate ancestors are DERIVED, not listed: a background token
#      painted by a rule that declares `padding` (so it holds content), declares no
#      `color` of its own (so its content inherits ink), and pins no `height` or
#      `width` (so it is a container rather than a swatch or a bar). Run over each
#      sheet separately, that predicate lands on the same small set both times -
#      which is why it is trustworthy enough to build on, and `contrast_audit()`
#      returns the set so a case can pin it.
#   3. THE BOUNDARIES. A `border`/`outline` colour on a rule that paints a CONTROL,
#      against those same grounds. "Control" is derived too: the rule's SUBJECT (the
#      last compound of each comma-separated selector) names a form element, or
#      carries a class that is somewhere else given `cursor:pointer` or a `:focus`
#      style. A card edge, a table rule and a divider are not controls, and 1.4.11
#      does not reach them - which is the difference `--border` and `--field-border`
#      were split apart to express.
#
# WHAT THIS CANNOT SEE, and in which DIRECTION, which is the half that matters:
#
#   * UNDER-reports. A colour written as `color-mix()`, `rgba()`, `hsl()` or a
#     gradient is unresolvable and is SKIPPED, never guessed - the tinted status
#     badges, the heatmap cells and the translucent focus ring are all in that
#     class. `contrast_audit()` returns how many such values it stepped over, so
#     the silence is a number on screen rather than an absence.
#   * UNDER-reports. Inheritance is approximated by the grounds. Text that really
#     sits on a fill this walk never paired it with is not judged at all.
#   * UNDER-reports. `opacity`, `filter` and overlapping stacking contexts change
#     what a reader sees and are ignored entirely.
#   * OVER-reports. A rule with no `font-size` of its own is judged as body text at
#     the 4.5 floor, even where it inherits a heading size that would earn 3.0.
#   * OVER-reports. A class that is a button in one place and a plain span in
#     another counts as a control everywhere here; telling those apart needs the
#     DOM. The panel's chip is exactly that shape.
#
# Over-reporting is the loud direction and is left as it is. Under-reporting is the
# quiet one, so every instance of it above is counted or named rather than implied.
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_HEX_ONLY = re.compile(r"^#[0-9a-fA-F]{3,8}$")
_VAR_ONLY = re.compile(r"^var\(\s*(--[\w-]+)\s*\)$")
# Anything whose value is a colour FUNCTION rather than a colour. Listed rather
# than approximated: a partial parse that read the first `var()` out of
# `color-mix(in srgb,var(--st-prog) 45%,transparent)` would report the solid
# amber as if it were the mixed result, which is a wrong number rather than a
# missing one - and a wrong number is what this whole section exists to stop.
_COLOUR_FN = re.compile(r"(color-mix|gradient|rgba?\(|hsla?\(|lab\(|lch\(|"
                        r"oklab\(|oklch\(|image-set|url\()")
_BORDER_SHORTHAND = re.compile(
    r"^(?:[\d.]+(?:px|rem|em)\s+)?"
    r"(?:solid|dashed|dotted|double|groove|ridge|inset|outset)\s+"
    r"var\(\s*(--[\w-]+)\s*\)$")
_BORDER_COLOUR_KEYS = ("border-color", "outline-color", "border-top-color",
                       "border-bottom-color", "border-left-color",
                       "border-right-color", "border-inline-start-color",
                       "border-block-end-color")
_BORDER_SHORTHAND_KEYS = ("border", "border-top", "border-bottom", "border-left",
                          "border-right", "border-inline-start",
                          "border-block-end", "outline")
# Every property whose value can carry a colour this walk would want to read.
# `unresolved` counts the ones written as a colour FUNCTION, so the size of the
# blind spot is reported instead of being left to be inferred from silence.
_COLOUR_BEARING = ("color", "background", "background-color", "fill", "stroke") \
    + _BORDER_COLOUR_KEYS + _BORDER_SHORTHAND_KEYS
# The elements a reader operates. `summary` is here because the report's filter
# panel IS a `<details>`, and its edge is the only thing that says so.
_FORM_ELEMENT = re.compile(r"^(a|button|input|select|textarea|summary|label)"
                           r"(?=[^\w-]|$)")
_FOCUS_PSEUDO = re.compile(r":focus(?:-visible|-within)?\b")
_CLASS_NAME = re.compile(r"\.([A-Za-z][\w-]*)")
_LENGTH = re.compile(r"^(\d*\.?\d+)(rem|em|px)$")

# The floors, named so a case can read them rather than re-spell them.
TEXT_FLOOR = 4.5
LARGE_TEXT_FLOOR = 3.0
NON_TEXT_FLOOR = 3.0
# WCAG's own definition of large text: 18pt, or 14pt bold. In this sheet's units
# that is 24px / 1.5rem, and 18.66px / 1.1667rem at weight 700 or more.
_LARGE_PX = 24.0
_LARGE_BOLD_PX = 18.66
_ROOT_PX = 16.0

# The shapes that are NOT failures, each with the reason it is not one and the
# criterion it is excused from. Kept as data rather than as an `if` in the walk
# for one reason: `contrast_exemption_problems()` can then check that every entry
# still describes something the stylesheet contains, so an exemption cannot
# outlive the rule it was written for and go on quietly excusing whatever moves
# into its place.
CONTRAST_EXEMPTIONS = (
    ("selector", ":disabled", "1.4.11",
     "An inactive control is exempt from 1.4.11 by the criterion's own text, and "
     "from 1.4.3 by the Incidental exception. Dimming is how a control says it "
     "will not answer; a disabled control forced back to 3:1 says nothing."),
    ("selector", 'aria-disabled="true"', "1.4.11",
     "The same exemption for the SAME state spelled the accessible way. These "
     "controls carry aria-disabled rather than `disabled` so they keep their tab "
     "stop (SC 2.4.3), and the exemption has to follow the state, not the "
     "attribute that happens to express it."),
    ("selector", "::placeholder", "1.4.3",
     "Placeholder text is a hint about an EMPTY field, and it is deliberately "
     "quieter than the value that replaces it. Raising it to 4.5 makes an empty "
     "field look filled, which is the failure the hint exists to prevent."),
)
# NO ENTRY FOR --border, AND THE FIRST DRAFT HAD ONE. It read like the obvious
# exemption - the token layer already says in so many words that --border is the
# decorative rule and 1.4.11 does not cover card edges - and it excused every
# pair it named, including the ones that were the whole point: --border was ALSO
# what the surviving form controls were still wearing, at a ratio near 1:1. A
# token cannot be excused by name when the same token wears two roles; the role
# is a property of the RULE, which is why `_is_control()` decides it and no list
# does. The exemption is deleted rather than narrowed, because a narrowed one
# would have gone green over those same rules the moment one changed shape.
#
# The `token` kind is still supported and still checked - a later token that
# really is excusable everywhere it appears can be written here - and a case
# proves an entry naming a token nothing declares is reported.


def _no_comments(css):
    """`css` with comments removed - they hold colours and selectors as prose."""
    return _CSS_COMMENT.sub("", css)


def _without_print(css):
    """`css` with every `@media print` block cut out.

    Load-bearing, and the precedent is one function up: the report's print sheet
    re-declares `--bg`, `--text` and friends for `:root,:root[data-theme="dark"]`,
    so a token walk that reads it comes away believing the DARK theme is a white
    page with dark ink and measures a palette nobody sees. `themes_missing_color_
    scheme()` was wrong in exactly that way once and went green over a restored
    defect; this walk hit the same trap and reported ratios near 1.3:1 for a dark
    ramp that is nowhere near that.
    """
    spans = []
    for at in re.finditer(r"@media([^{]*)\{", css):
        if "print" not in at.group(1):
            continue
        depth, i = 1, at.end()
        while i < len(css) and depth:
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        spans.append((at.start(), i))
    kept, last = [], 0
    for lo, hi in spans:
        kept.append(css[last:lo])
        last = hi
    kept.append(css[last:])
    return "".join(kept)


def _css_rules(css):
    """[(selector, {property: value}), ...] for every rule block in `css`.

    At-rules are flattened rather than modelled: a rule inside `@media
    (max-width:70rem)` paints the same colours on the same selector, and the
    criteria do not care how wide the window is. Brace counting is safe because
    comments are gone by the time this runs.
    """
    out, stack, selector, body = [], [], [], []
    for ch in css:
        if ch == "{":
            stack.append("".join(selector).strip())
            selector, body = [], []
        elif ch == "}":
            text = "".join(body).strip()
            if text and stack:
                out.append((stack[-1], _declarations(text)))
            if stack:
                stack.pop()
            selector, body = [], []
        else:
            if stack:
                body.append(ch)
            selector.append(ch)
    return out


def _declarations(text):
    """`prop:value;prop:value` as a dict, later wins - the cascade's own rule."""
    out = {}
    for part in text.split(";"):
        if ":" in part and "{" not in part:
            name, _sep, value = part.partition(":")
            out[name.strip().lower()] = value.strip()
    return out


def _solid_colour(value):
    """A token name, a hex literal, or None when the value is not one colour.

    None means "this walk cannot judge it", never "this is fine" - see
    `_COLOUR_FN` for why a half-parse would be worse than no parse.
    """
    v = (value or "").strip()
    if not v or _COLOUR_FN.search(v):
        return None
    m = _VAR_ONLY.match(v)
    if m:
        return m.group(1)
    return v if _HEX_ONLY.match(v) else None


def _background_colour(decls):
    """The rule's own background, or None when it paints none this walk can read."""
    for key in ("background-color", "background"):
        if key in decls:
            return _solid_colour(decls[key])
    return None


def _boundary_colour(decls):
    """The rule's border/outline colour, longhand first, then the shorthand."""
    for key in _BORDER_COLOUR_KEYS:
        if key in decls:
            return _solid_colour(decls[key])
    for key in _BORDER_SHORTHAND_KEYS:
        if key in decls:
            v = decls[key].strip()
            if _COLOUR_FN.search(v):
                return None
            m = _BORDER_SHORTHAND.match(v)
            if m:
                return m.group(1)
    return None


def _subjects(selector):
    """The last compound of each comma-separated selector - what the rule paints.

    `.gfilters select` paints the SELECT, not the bar around it, and reading the
    whole selector for interactivity is what made the bar look like a control.
    """
    out = []
    for part in selector.split(","):
        parts = [p for p in re.split(r"[\s>+~]+", part.strip()) if p]
        if parts:
            out.append(parts[-1])
    return out


def _interactive_classes(rules):
    """Class names that name something a reader operates, harvested off the sheet.

    A class earns the label when a rule whose SUBJECT carries it also names a form
    element, declares `cursor:pointer`, or styles a `:focus` state. Focus is the
    strongest of the three - only a focusable thing gets one - and `:hover` is
    deliberately absent, because rows and cards hover too.
    """
    out = set()
    for selector, decls in rules:
        pointer = decls.get("cursor", "").strip() == "pointer"
        for subject in _subjects(selector):
            if pointer or _FOCUS_PSEUDO.search(subject) \
                    or _FORM_ELEMENT.match(subject):
                out |= set(_CLASS_NAME.findall(subject))
    return out


def _is_control(selector, decls, interactive):
    """True when this rule paints something a reader operates."""
    if decls.get("cursor", "").strip() == "pointer":
        return True
    for subject in _subjects(selector):
        if _FORM_ELEMENT.match(subject):
            return True
        if set(_CLASS_NAME.findall(subject)) & interactive:
            return True
    return False


def ground_tokens(rules):
    """The background tokens large enough to be what text inherits its ground from.

    Derived, never listed - see the section header for the predicate and for what
    it costs. Returned sorted so a case can pin the set rather than its size.
    """
    out = set()
    for _selector, decls in rules:
        if "color" in decls:
            continue
        bg = _background_colour(decls)
        if bg and bg.startswith("--") and "padding" in decls \
                and "height" not in decls and "width" not in decls:
            out.add(bg)
    return sorted(out)


def _px(value):
    """A CSS length in px, or None. `em` is treated as `rem` - see the caller."""
    m = _LENGTH.match((value or "").strip())
    if not m:
        return None
    n = float(m.group(1))
    return n if m.group(2) == "px" else n * _ROOT_PX


def _text_floor(decls):
    """4.5, or 3.0 when this rule's OWN type is large by WCAG's definition.

    A rule that declares no `font-size` is judged at 4.5 even if it inherits a
    heading size - the over-report named in the section header, and the safe
    direction to be wrong in.
    """
    size = _px(decls.get("font-size", ""))
    if size is None:
        return TEXT_FLOOR
    weight = decls.get("font-weight", "").strip()
    bold = weight in ("bold", "bolder") or (weight.isdigit() and int(weight) >= 700)
    if size >= _LARGE_PX or (bold and size >= _LARGE_BOLD_PX):
        return LARGE_TEXT_FLOOR
    return TEXT_FLOOR


def _theme_values(css):
    """({token: light value}, {token: dark value}) read off every :root block.

    Every one of them, not the first: the panel adds a second base block for the
    three roles the report has no equivalent of, and those roles carry ink.
    """
    light, dark = {}, {}
    for m in re.finditer(r"(@media[^{]*prefers-color-scheme\s*:\s*dark[^{]*\{\s*)?"
                         r":root(\[[^\]]*\]|:not\([^)]*\))?\s*\{", css):
        start = m.end()
        depth, i = 1, start
        while i < len(css) and depth:
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        head = m.group(0)
        if "prefers-color-scheme" in head or "data-theme=dark" in head \
                or 'data-theme="dark"' in head:
            target = dark
        elif "data-theme" in head:
            continue                      # an explicit LIGHT block: the base already is
        else:
            target = light
        for name, value in re.findall(r"(--[\w-]+)\s*:\s*([^;}]*)",
                                      css[start:i - 1]):
            target[name] = value.strip()
    return (light, dark)


def _exempt(selector, colour, criterion):
    """The reason this pair is excused, or None. Selectors first, then tokens."""
    for kind, needle, crit, why in CONTRAST_EXEMPTIONS:
        if crit != criterion:
            continue
        if kind == "selector" and needle in selector:
            return why
        if kind == "token" and needle == colour:
            return why
    return None


def contrast_exemption_problems(css, exemptions=None):
    """Exemptions that no longer describe anything in `css`.

    An exemption is a claim about the stylesheet, so it decays like any other.
    One that names a token nobody declares any more, or a selector shape nobody
    writes any more, has stopped excusing the thing it was written for and is
    quietly excusing whatever moves in next - which is how a guard becomes its
    own defect class. Both halves are checked, because both have to be true for
    the entry to mean what it says.

    `exemptions` overrides the shipped tuple. It is there so both KINDS stay
    reachable from a case: the shipped list is selector-shaped today, and a
    `token` branch nothing exercises is a branch nobody has seen work.
    """
    text = _no_comments(css)
    out = []
    for kind, needle, crit, _why in (CONTRAST_EXEMPTIONS if exemptions is None
                                     else exemptions):
        if kind == "token":
            if not re.search(r"(?<![\w-])%s\s*:" % re.escape(needle), text):
                out.append("%s exemption names %s, which no rule declares"
                           % (crit, needle))
        elif needle not in text:
            out.append("%s exemption names %s, which no selector uses"
                       % (crit, needle))
    return out


def contrast_audit(css):
    """WCAG 1.4.3 and 1.4.11 over an ASSEMBLED stylesheet, both themes.

    Returns a dict rather than a list because the count is half the answer: a
    comparison over no pairs passes for every palette ever written, so `pairs`
    and `unresolved` travel with `violations` and a case pins all three.

      grounds     the derived container backgrounds, sorted
      pairs       distinct (criterion, theme, foreground, background) tuples measured
      unresolved  values skipped because they are not one solid colour
      exempt      pairs excused, each carrying the reason from CONTRAST_EXEMPTIONS
      violations  one readable line per failing pair, sorted worst first
    """
    text = _without_print(_no_comments(css))
    light, dark = _theme_values(text)
    rules = _css_rules(text)
    grounds = ground_tokens(rules)
    interactive = _interactive_classes(rules)

    def value(colour, theme):
        if not colour.startswith("--"):
            return colour
        table = light if theme == "light" else dark
        return table.get(colour, light.get(colour))

    # Judged per RULE and only then folded by pair, which is not how the first
    # version worked and is the difference between a lint and a lint-shaped hole.
    # It deduplicated as it walked, so the FIRST rule to produce a pair decided
    # it - and `.btn[aria-disabled="true"]:hover` sits above the fields in the
    # sheet, so its perfectly correct exemption silenced --border on every
    # control below it. A pair is excused only when EVERY rule that produces it
    # is excused; one unexcused rule is a finding whatever stands above it.
    measured, seen_rule, excused, findings = set(), set(), {}, {}
    unresolved = 0
    for selector, decls in rules:
        for key in _COLOUR_BEARING:
            if key in decls and _COLOUR_FN.search(decls[key]):
                unresolved += 1
        ink = _solid_colour(decls.get("color", "")) if "color" in decls else None
        own = _background_colour(decls)
        edge = _boundary_colour(decls)
        wanted = []
        if ink:
            floor = _text_floor(decls)
            wanted += [("1.4.3", ink, bg, floor)
                       for bg in ([own] if own else grounds)]
        if edge and _is_control(selector, decls, interactive):
            if own and own == edge:
                # A border the colour of its own fill is not a boundary. What
                # identifies the control is then the FILL against the page, which
                # is the pair a solid primary button actually stands or falls on.
                wanted += [("1.4.11", own, bg, NON_TEXT_FLOOR) for bg in grounds]
            else:
                wanted += [("1.4.11", edge, bg, NON_TEXT_FLOOR)
                           for bg in ([own] if own else []) + grounds]
        for criterion, fg, bg, floor in wanted:
            for theme in ("light", "dark"):
                ratio = contrast_ratio(value(fg, theme), value(bg, theme))
                if ratio is None:
                    continue
                key = (criterion, theme, fg, bg)
                measured.add(key)
                if (key, selector, floor) in seen_rule or ratio >= floor:
                    continue
                seen_rule.add((key, selector, floor))
                why = _exempt(selector, fg, criterion)
                if why:
                    excused.setdefault(key, "%s %s on %s in %s: %s"
                                       % (criterion, fg, bg, theme, why))
                elif key not in findings:
                    findings[key] = (ratio, floor, selector)
    violations = ["%s %s on %s in %s is %.2f:1, below %.1f:1 (first at %s)"
                  % (k[0], k[2], k[3], k[1], v[0], v[1], v[2])
                  for k, v in sorted(findings.items(), key=lambda kv: kv[1][0])]
    exempt = [line for key, line in excused.items() if key not in findings]
    return {"grounds": grounds, "pairs": len(measured), "unresolved": unresolved,
            "exempt": sorted(exempt), "violations": violations}


def themed_stylesheets():
    """[(surface, assembled css), ...] - the token layer in front of each sheet.

    The five lints above all run against the ASSEMBLED string, and so does this
    one: the panel's parts declare no `--bg` between them to measure against, so
    a walk over one would resolve nothing, find no pairs and report a clean sheet.
    The join is the same one the surfaces do (`_panel_page` substitutes the
    marker, `render-report` concatenates), spelled again here only because both
    of those sit a layer up and this module may not import them.
    """
    # Both sheets are ordered parts, joined in CASCADE order - the tuples above,
    # never a filter over the alphabetically-sorted UI_ASSETS. A differently
    # ordered join would have these lints clear a palette nobody is served.
    panel = "".join(read_asset(n) for n in PANEL_CSS_PARTS)
    report = "".join(read_asset(n) for n in REPORT_CSS_PARTS)
    return [("panel", panel.replace("/*__THEME_TOKENS__*/", TOKEN_CSS)),
            ("report", TOKEN_CSS + report)]


# --- the stylesheet lints ----------------------------------------------------------


# --- stylesheet lints ------------------------------------------------------------
def undeclared_css_vars(css):
    """Custom properties referenced by var() but never declared anywhere.

    This check exists because the failure mode is SILENT and total: an undeclared
    `var(--x)` makes the whole declaration invalid at computed-value time, so the
    property falls back to its INITIAL value rather than to the stylesheet rule
    underneath it. An undeclared colour token therefore paints transparent — a bar
    chart with no bars — and logs nothing. That is exactly how `--bar-neutral`
    shipped invisible in light mode once."""
    declared = set(re.findall(r"(--[A-Za-z0-9_-]+)\s*:", css))
    # Only FALLBACK-LESS references are dangerous. `var(--x, something)` degrades
    # gracefully by design, and tokens set inline per element from Python (--w on a
    # progress fill, --sc on a sparkline) are always written that way for exactly
    # this reason.
    used = set(re.findall(r"var\(\s*(--[A-Za-z0-9_-]+)\s*\)", css))
    return sorted(used - declared)


def unterminated_css_decls(css):
    """Custom-property declarations that run past their line without a `;`.

    A custom property's value is almost anything up to the next `;` or the block's
    closing `}` — comments and later declarations included. So a missing semicolon
    does not raise; it silently ANNEXES whatever follows. One missing `;` after
    `--ease` swallowed a five-line comment plus the `--sp-0` declaration, which cost
    two things at once: `--ease` became a garbage multi-line value, making every
    `animation`/`transition` shorthand that referenced it invalid at computed-value
    time (so the report's progress-bar fill, card and button transitions and the
    heading fade were all dead), and `--sp-0` was never declared at all.

    `_undeclared_css_vars` cannot see this: the annexed text still reads as
    `--sp-0:` to a regex looking for declarations, so the token appears declared.
    That is why this is a separate check rather than a stricter one.

    Omitting the `;` on the LAST declaration in a block is legal and common, so a
    line only counts when more content follows before the block closes."""
    bad, lines = [], css.split("\n")
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not re.search(r"--[A-Za-z0-9_-]+\s*:", line):
            continue
        if line.endswith((";", "{", "}")):
            continue
        # Unterminated. Harmless only if the block ends before any further content.
        for nxt in lines[i + 1:]:
            nxt = nxt.strip()
            if not nxt:
                continue
            if nxt.startswith("}"):
                break                      # last declaration in its block — legal
            bad.append("line %d: %s" % (i + 1, line[:72]))
            break
    return bad


def theme_asymmetric_vars(css):
    """Colour tokens that exist in one theme but not the other - in EITHER direction.

    The light `:root` is the base token set; the dark blocks are overrides. There are
    two distinct silent failures here, and the first version of this check only
    caught one of them:

      * declared in light, missing from dark -> the token vanishes in dark mode
      * declared ONLY in a dark block        -> it vanishes in LIGHT mode, which is
        exactly how `--bar-neutral` shipped as invisible bars

    Both render transparent with nothing in the console, so both are checked."""
    # EVERY unqualified `:root{...}` rule, not just the first. A stylesheet may
    # declare its base tokens in more than one block — the panel adds a small one
    # for roles the report has no equivalent of — and reading only the first made
    # every token in the others look like it existed in dark mode alone.
    # `:root[data-theme=dark]` and `:root:not(...)` do not match this pattern.
    light_blocks = re.findall(r":root\s*\{([^}]*)\}", css)
    if not light_blocks:
        return []
    light_vars = set()
    for block in light_blocks:
        light_vars |= set(re.findall(r"(--[A-Za-z0-9_-]+)\s*:", block))
    dark_vars = set()
    for block in re.findall(
            r"(?:prefers-color-scheme\s*:\s*dark|data-theme=.?dark)[^{]*\{(.*?)\}\}?",
            css, re.S):
        dark_vars |= set(re.findall(r"(--[A-Za-z0-9_-]+)\s*:", block))
    if not dark_vars:
        return []
    # spacing / type / motion / font / layout tokens are theme-independent by design
    # and are deliberately declared once, in the base only. The sticky-stack
    # offsets and paint order (--topbar-h, --sticky-*, --z-*) are geometry, not
    # colour: a dark report pins its bar in exactly the same place.
    neutral = ("--sp-", "--t-", "--dur", "--ease", "--radius", "--pill",
               "--sans", "--mono", "--shadow",
               "--topbar-h", "--strip-h", "--sectools-h", "--sticky-", "--z-",
               "--nav-w", "--shell-gap")

    def colourish(names):
        return {v for v in names if not any(v.startswith(n) for n in neutral)}

    return sorted("%s (light only)" % v
                  for v in colourish(light_vars) - dark_vars) + \
        sorted("%s (dark only)" % v for v in colourish(dark_vars) - light_vars)


def mangled_css_escapes(css):
    """CSS escapes eaten by Python before the browser ever saw them.

    A CSS escape is a backslash, and a backslash in a non-raw Python string is an
    escape too — so `content:"\\2713\\a0"` written inside a plain `\"\"\"...\"\"\"`
    block never reaches the stylesheet. Python reads `\\271` as an OCTAL byte and
    `\\a` as the bell character, and the browser is handed `content:"¹3<BEL>0"`.
    It renders it faithfully: the filter chip whose whole job was to say it is on
    without relying on hue showed `¹30` instead of a tick, in every report shipped
    since that chip was added — while the selftest stayed green, because it
    asserted that the SELECTOR existed and never what it drew.

    The spelling that works is `\\\\2713\\\\a0`, which the panel's copy of the same
    rule already had. Two files, one glyph, and nothing able to see them disagree:
    the same shape as every other defect this module exists to catch.

    Two signatures, because the accident has two halves and each is silent alone:

      * a raw control character anywhere in the sheet. `\\a`, `\\f`, `\\v`, `\\0`
        cannot survive as text and are never intentional in CSS.
      * a character in U+0080-U+00FF inside a `content:` value. That is precisely
        the range a Python octal escape can produce (`\\377` is the largest), and
        nothing legitimate lands there — a real glyph written literally (✓ ▶ —)
        sits above U+00FF, and everything else in a content string is ASCII.
    """
    bad = []
    for i, ch in enumerate(css):
        if ord(ch) < 0x20 and ch not in "\n\t":
            bad.append("raw control char %r near %r"
                       % (ch, css[max(0, i - 44):i + 6].strip()))
    for m in re.finditer(r"content\s*:\s*([\"'])(.*?)\1", css):
        for ch in m.group(2):
            if 0x80 <= ord(ch) <= 0xFF:
                bad.append("octal-escape residue %r in %r" % (ch, m.group(0)))
                break
    return bad


def themes_missing_color_scheme(css):
    """Explicit theme choices that never restate `color-scheme`.

    Custom properties paint OUR boxes. Native UI — checkbox, radio, `<select>`
    menu, number spinner, `<input type=date>` picker, scrollbar — is painted by
    the UA from `color-scheme` alone, and no amount of care in the tokens beside
    it reaches them. Declare `color-scheme:light dark` once on bare `:root` and
    it resolves from `prefers-color-scheme` *and ignores the toggle*: on an
    OS-light machine the dark theme ships with light checkboxes, a light select
    menu and light scrollbars, and the inverse is just as true. That shipped for
    four releases, and reading the stylesheet is what made it look fine — the
    property is present, it is the OVERRIDE that was absent.

    Checked per theme VALUE rather than per rule, because a surface may legally
    add a second block for the same theme: the panel carries
    `:root[data-theme=dark]{--ok:...}` for three roles the report has no
    equivalent of, and it has no business restating `color-scheme` — the shared
    token block already did. So the question is "is this theme met by a
    color-scheme anywhere in this stylesheet", not "does every block carry one".

    A negation cannot SATISFY a theme — `:root:not([data-theme=light])` styles the
    absence of a choice, which the base `light dark` already covers — but it does
    NAME one, and that is the only place some themes appear. `light` needs no
    colour overrides at all (the base :root is light), so the one rule that
    mentions it is the negation guarding the OS-dark block; harvesting names from
    negations is what makes the explicit-light case checkable rather than
    invisible, and dropping the light pin red rather than green.

    `@media print` is skipped in both directions, and that exclusion is load-
    bearing rather than tidy: the report's print sheet forces a light page for
    `:root,:root[data-theme="dark"]`, so without it a `color-scheme:light` meant
    for paper counted as satisfying the dark theme on screen — and the first
    version of this check went green with the screen defect fully restored."""
    def themes_named_in(selector_text):
        return set(re.findall(r"\[data-theme\s*=\s*[\"']?([A-Za-z-]+)",
                              selector_text))

    print_spans = []
    for at in re.finditer(r"@media([^{]*)\{", css):
        if "print" not in at.group(1):
            continue
        depth, i = 1, at.end()
        while i < len(css) and depth:
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        print_spans.append((at.start(), i))

    seen, satisfied = set(), set()
    for rule in re.finditer(r"([^{}]*?)\{([^{}]*)\}", css):
        if any(lo <= rule.start() < hi for lo, hi in print_spans):
            continue
        selector, block = rule.group(1), rule.group(2)
        negated = " ".join(re.findall(r":not\(([^)]*)\)", selector))
        chosen = themes_named_in(re.sub(r":not\([^)]*\)", "", selector))
        seen |= chosen | themes_named_in(negated)
        if chosen and re.search(r"(?<![-\w])color-scheme\s*:", block):
            satisfied |= chosen
    return sorted(seen - satisfied)
