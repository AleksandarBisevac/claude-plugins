#!/usr/bin/env python3
"""
The shared visual system for the audit plugin's two surfaces — dependency-free.

The HTML report (`render-report.py`) and the control panel (`panel-server.py`)
are separate programs that a reader experiences as one product: they open the
panel, export a report, and expect the same colours, the same spacing and the
same words for the same things. Until this module existed both carried their own
copy of the token block, kept in step by hand — and had already drifted (the nav
column was 14.5rem in one and 13.5rem in the other, the gap 2.5rem and 2rem) with
nothing in either test suite able to see it, because each file only ever checked
itself.

One definition, imported by both, so parity is a property of the build rather
than of somebody remembering.

  TOKEN_CSS  the whole token layer: colour (light + both dark forms), spacing,
             type, motion, and the geometry of the sticky stack
  LABELS     machine value -> the words a person reads. Statuses travel through
             this system as `in_progress`; nobody should ever SEE `in_progress`.
  label()    lookup with a graceful fallback, so an unknown status degrades to
             something readable instead of blank

The CSS lint helpers live here too, next to the stylesheet they police.
"""
import re

TOKEN_CSS = """
/* ---- design tokens (Slate & Teal) ---------------------------------------- */
:root{
  /* `color-scheme` is the ONLY part of the visual system the custom properties
     below cannot reach: checkboxes, <select> menus, number spinners, the
     <input type=date> picker and the scrollbars are painted by the UA, which
     reads this and nothing else. So it has to be restated wherever a theme is
     chosen, or a reader who presses the toggle gets our dark surface wearing
     the OS's light controls. Three states, three declarations:

       no data-theme          -> `light dark`, follow the OS (here)
       data-theme="light"     -> pin light  (below)
       data-theme="dark"      -> pin dark   (below)

     `themes_missing_color_scheme()` fails the build if one goes missing. */
  color-scheme:light dark;
  --sans:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,system-ui,sans-serif;
  --mono:ui-monospace,'SF Mono','JetBrains Mono',Menlo,Consolas,monospace;
  --bg:#f5f7fb;--surface:#ffffff;--surface-2:#eef2f7;--text:#0f172a;--muted:#64748b;
  --border:#e2e8f0;--border-strong:#cbd5e1;
  --accent:#0d9488;--accent-solid:#0d9488;--ring:rgba(13,148,136,.35);
  --st-done:#15803d;--st-prog:#f59e0b;--st-blocked:#dc2626;--st-pending:#64748b;
  /* Ink for a TINTED status badge. One solid-fill chip per status needed one ink
     and an exception (amber on white is unreadable, so in_progress alone got dark
     ink) — four statuses wearing three different grammars. A badge tinted from
     its own status colour carries readable ink of that same hue instead, and the
     exception disappears. Mirrors the --rk-*-fg pattern, which already worked. */
  --st-done-ink:#166534;--st-prog-ink:#854d0e;--st-blocked-ink:#b91c1c;
  --st-pending-ink:#475569;
  --rk-low-bg:#dcfce7;--rk-low-fg:#166534;--rk-med-bg:#fef9c3;--rk-med-fg:#854d0e;
  --rk-high-bg:#fee2e2;--rk-high-fg:#b91c1c;
  /* Usage viz. Categorical slots carry MODEL identity (assigned by name, never by
     rank, so a filter can't repaint the survivors). Palette validated for CVD and
     contrast against this report's own surfaces with the dataviz validator:
     light worst-adjacent CVD dE 9.1 / normal-vision 19.6 - dark 8.4 / 19.3. Three
     light slots sit under 3:1, which the per-phase token/cost table relieves. */
  --viz-1:#2a78d6;--viz-2:#eb6834;--viz-3:#1baf7a;--viz-4:#eda100;
  --viz-5:#e87ba4;--viz-6:#008300;--viz-7:#4a3aa7;--viz-8:#e34948;
  /* Sequential single-hue ramp for the day x hour heatmap: light -> dark, zero
     recedes into the surface. Never a rainbow. */
  --hm-0:#eef2f7;--hm-1:#cde2fb;--hm-2:#9ec5f4;--hm-3:#6da7ec;
  --hm-4:#3987e5;--hm-5:#256abf;--hm-6:#0d366b;--hm-ink:#ffffff;
  /* Magnitude-only bars (phase, author, task). Deliberately NOT --accent and
     deliberately low-chroma: it must not read as a series colour. Validated
     against all 8 viz slots on this surface - worst normal-vision dE 16.4,
     worst CVD dE 7.5, which the 6-8 band permits because every bar wearing it
     carries a direct text label. */
  --bar-neutral:#5c636d;
  /* The gate rail. The line is STRUCTURE and carries no state — it is one colour
     the whole way down, so the only thing that changes along it is the gates. It
     dims below a gate that is closed, because nothing behind that gate can be
     worked on. Before this the left border repeated each row's status colour,
     which made the spine a second copy of the chip beside it rather than a
     drawing of what holds what. */
  --rail:#9aa8bd;--rail-held:#dfe5ee;
  --radius:9px;--radius-lg:14px;--pill:999px;
  --shadow-sm:0 1px 2px rgba(15,23,42,.05),0 2px 8px rgba(15,23,42,.06);
  --shadow-md:0 10px 30px rgba(15,23,42,.14);
  --dur:.22s;--ease:cubic-bezier(.4,0,.2,1);
  /* 8pt spacing scale + 3 text levels. Introduced so spacing stops being
     ad-hoc: every margin/padding/gap below snaps to one of these steps, which is
     what makes the vertical rhythm read as deliberate rather than accidental.
     Spacing and type are theme-independent, so unlike the colour tokens these are
     declared ONCE and are not repeated in the dark blocks. */
  --sp-0:.25rem;--sp-1:.5rem;--sp-2:.75rem;--sp-3:1rem;
  --sp-4:1.5rem;--sp-5:2rem;--sp-6:3rem;--sp-7:4rem;
  --t-1:1.7rem;--t-2:1.0625rem;--t-3:.875rem;--t-label:.68rem;
  /* ---- the sticky stack ---------------------------------------------------
     Three things pin to the top of this document — the bar, the mobile nav strip
     and the table's filter row — and a fourth (the column headers) has to pin
     below all of them. Every one of those offsets used to be a hand-tuned
     constant: 4.1rem for the nav, 3.6rem for the filter bar, 3.5rem for the
     headers, 6.6rem for the filter bar again below 72rem. Four guesses at one
     number, and none of them was right: the bar measures 70px, so the filter bar
     pinned 12px UNDER it and the column headers pinned above the filter bar and
     were painted out of existence entirely.

     Now there is one measurement and everything derives from it. --topbar-h is
     restated at runtime from the bar's own height (it depends on the title, the
     viewport and the font), so the stack cannot drift from what is on screen;
     the values here are the no-JS fallback and are deliberately generous. */
  --topbar-h:4.4rem;--strip-h:0rem;--sectools-h:3.9rem;
  --sticky-1:var(--topbar-h);
  --sticky-2:calc(var(--sticky-1) + var(--strip-h));
  --sticky-3:calc(var(--sticky-2) + var(--sectools-h));
  /* Painting order for those same layers. Lower pins deeper: the column headers
     must slide UNDER the filter bar, which slides under the bar. */
  --z-topbar:30;--z-strip:20;--z-sectools:15;--z-thead:10;
  /* The shell both surfaces are built on. These were hard-coded separately in
     each and had already drifted — 14.5rem beside 13.5rem, 2.5rem beside 2rem —
     which is small enough that nobody notices and exactly large enough that the
     two stop feeling like one product. */
  --nav-w:14.5rem;--shell-gap:2.5rem;
}
/* dark tokens: OS default (JS off) + explicit toggle. --theme=light pins light. */
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#0a1120;--surface:#111a2b;--surface-2:#172236;--text:#e6edf6;--muted:#93a4bd;
  --border:#1f2b40;--border-strong:#33425c;
  --accent:#2dd4bf;--accent-solid:#0f766e;--ring:rgba(45,212,191,.4);
  --st-done:#34d399;--st-prog:#fbbf24;--st-blocked:#f87171;--st-pending:#94a3b8;
  --st-done-ink:#6ee7b7;--st-prog-ink:#fcd34d;--st-blocked-ink:#fca5a5;
  --st-pending-ink:#cbd5e1;
  --rk-low-bg:rgba(52,211,153,.16);--rk-low-fg:#6ee7b7;--rk-med-bg:rgba(251,191,36,.16);
  --rk-med-fg:#fcd34d;--rk-high-bg:rgba(248,113,113,.16);--rk-high-fg:#fca5a5;
  --viz-1:#3987e5;--viz-2:#d95926;--viz-3:#199e70;--viz-4:#c98500;
  --viz-5:#d55181;--viz-6:#008300;--viz-7:#9085e9;--viz-8:#e66767;
  --bar-neutral:#a6adb8;
  --rail:#4a5c7d;--rail-held:#1b2740;
  /* Dark heatmap steps are SELECTED for the dark surface, not an inverted copy:
     zero still recedes into the surface, so the ramp runs dark -> light. */
  --hm-0:#172236;--hm-1:#104281;--hm-2:#184f95;--hm-3:#1c5cab;
  --hm-4:#2a78d6;--hm-5:#5598e7;--hm-6:#9ec5f4;--hm-ink:#07130f;
  --shadow-sm:0 1px 2px rgba(0,0,0,.4);--shadow-md:0 12px 34px rgba(0,0,0,.5)
}}
/* An explicit LIGHT choice needs no colour overrides — the base :root already is
   light — but it does need this one line, or an OS-dark reader who presses the
   toggle reads a white page through dark checkboxes and a dark date picker. */
:root[data-theme="light"]{color-scheme:light}
:root[data-theme="dark"]{
  color-scheme:dark;
  --bg:#0a1120;--surface:#111a2b;--surface-2:#172236;--text:#e6edf6;--muted:#93a4bd;
  --border:#1f2b40;--border-strong:#33425c;
  --accent:#2dd4bf;--accent-solid:#0f766e;--ring:rgba(45,212,191,.4);
  --st-done:#34d399;--st-prog:#fbbf24;--st-blocked:#f87171;--st-pending:#94a3b8;
  --st-done-ink:#6ee7b7;--st-prog-ink:#fcd34d;--st-blocked-ink:#fca5a5;
  --st-pending-ink:#cbd5e1;
  --rk-low-bg:rgba(52,211,153,.16);--rk-low-fg:#6ee7b7;--rk-med-bg:rgba(251,191,36,.16);
  --rk-med-fg:#fcd34d;--rk-high-bg:rgba(248,113,113,.16);--rk-high-fg:#fca5a5;
  --viz-1:#3987e5;--viz-2:#d95926;--viz-3:#199e70;--viz-4:#c98500;
  --viz-5:#d55181;--viz-6:#008300;--viz-7:#9085e9;--viz-8:#e66767;
  --bar-neutral:#a6adb8;
  --rail:#4a5c7d;--rail-held:#1b2740;
  /* Dark heatmap steps are SELECTED for the dark surface, not an inverted copy:
     zero still recedes into the surface, so the ramp runs dark -> light. */
  --hm-0:#172236;--hm-1:#104281;--hm-2:#184f95;--hm-3:#1c5cab;
  --hm-4:#2a78d6;--hm-5:#5598e7;--hm-6:#9ec5f4;--hm-ink:#07130f;
  --shadow-sm:0 1px 2px rgba(0,0,0,.4);--shadow-md:0 12px 34px rgba(0,0,0,.5)
}
"""


# --- words ----------------------------------------------------------------------
# The manifest's vocabulary is machine-facing by design: `in_progress` is a stable
# key that sorts, compares and survives serialization. It is not, and was never
# meant to be, a thing to show someone. Both surfaces render these instead, and
# keep the machine value in a data-attribute so filtering still compares keys.
STATUS = {
    "pending": "Pending",
    "in_progress": "In progress",
    "blocked": "Blocked",
    "done": "Done",
}
BUG_STATUS = {
    "open": "Open",
    "triaged": "Triaged",
    "in_progress": "In progress",
    "fixed": "Fixed",
    "wontfix": "Won\u2019t fix",
}
TESTS_MODE = {
    "tdd": "TDD (red first)",
    "regression": "Regression",
    "gate-only": "Gate only",
}
RISK = {"low": "Low", "med": "Medium", "high": "High"}
GATE_TIER = {"observe": "Observe", "warn": "Warn", "deny": "Deny"}

# One flat map for the surfaces that render statuses and bug statuses in the same
# table cell. The two disagree on nothing: `in_progress` reads the same either way.
LABELS = dict(STATUS)
LABELS.update(BUG_STATUS)

ALL = {"status": STATUS, "bugStatus": BUG_STATUS, "testsMode": TESTS_MODE,
       "risk": RISK, "gateTier": GATE_TIER}


def label(value, mapping=None):
    """The words for a machine value.

    An unrecognised value is humanised rather than dropped: a manifest may carry a
    status this build has never heard of, and showing `some_new_state` as "Some new
    state" is strictly better than showing nothing at all.
    """
    m = mapping if isinstance(mapping, dict) else LABELS
    if not isinstance(value, str) or not value:
        return ""
    if value in m:
        return m[value]
    pretty = value.replace("_", " ").replace("-", " ").strip()
    return pretty[:1].upper() + pretty[1:] if pretty else value


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


def _selftest():
    """Both surfaces depend on this module, so it carries its own gate."""
    ok = bad = 0

    def check(name, cond):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("PASS %s" % name)
        else:
            bad += 1
            print("FAIL %s" % name)

    check("tokens declare a light :root", ":root{" in TOKEN_CSS)
    check("tokens declare both dark forms - the OS default AND the explicit "
          "toggle, or one of the two paths silently keeps light colours",
          "prefers-color-scheme:dark" in TOKEN_CSS
          and ':root[data-theme="dark"]' in TOKEN_CSS)
    check("no token is declared in only one theme: %r" % (theme_asymmetric_vars(TOKEN_CSS),),
          not theme_asymmetric_vars(TOKEN_CSS))
    # The toggle has to move the NATIVE controls too, and tokens cannot reach them.
    check("every explicit theme restates color-scheme, so the toggle moves the "
          "checkboxes, selects, spinners, date pickers and scrollbars with it: %r"
          % (themes_missing_color_scheme(TOKEN_CSS),),
          not themes_missing_color_scheme(TOKEN_CSS))
    check("both directions are pinned, not just dark",
          "color-scheme:dark" in TOKEN_CSS and "color-scheme:light}" in TOKEN_CSS)
    check("bare :root still follows the OS when nobody has chosen",
          re.search(r":root\{[^}]*color-scheme:light dark;", TOKEN_CSS) is not None)
    # The lint's own two ways of being wrong. It caught nothing for four releases
    # because there was nothing like it; these prove it can fail and can pass.
    check("the lint detects a theme with no color-scheme",
          themes_missing_color_scheme(
              ':root{color-scheme:light dark}\n:root[data-theme="dark"]{--bg:#000}')
          == ["dark"])
    check("the lint accepts a theme satisfied by a DIFFERENT block, which is how "
          "the panel adds its own roles without restating the property",
          themes_missing_color_scheme(
              ':root[data-theme=dark]{color-scheme:dark}\n'
              ':root[data-theme=dark]{--ok:#0f0}') == [])
    check("a :not() negation cannot satisfy a theme, but it does NAME one - which "
          "is the only mention explicit-light gets, since light needs no colours",
          themes_missing_color_scheme(
              '@media (prefers-color-scheme:dark){:root:not([data-theme=light])'
              '{--bg:#000}}') == ["light"])
    check("...and naming it is enough for a pin elsewhere to answer it",
          themes_missing_color_scheme(
              ':root[data-theme=light]{color-scheme:light}\n'
              '@media (prefers-color-scheme:dark){:root:not([data-theme=light])'
              '{--bg:#000}}') == [])
    check("a print sheet cannot vouch for a SCREEN theme - the report's forces a "
          "light page for :root[data-theme=dark], and counting it hid the defect",
          themes_missing_color_scheme(
              ':root[data-theme="dark"]{--bg:#000}\n'
              '@media print{:root,:root[data-theme="dark"]{color-scheme:light}}')
          == ["dark"])
    check("no declaration is left unterminated: %r" % (unterminated_css_decls(TOKEN_CSS),),
          not unterminated_css_decls(TOKEN_CSS))
    check("braces balance", TOKEN_CSS.count("{") == TOKEN_CSS.count("}"))
    # The sticky stack is geometry both surfaces pin against.
    check("the sticky stack is declared once, and derives",
          "--topbar-h:" in TOKEN_CSS and "--sticky-2:calc(var(--sticky-1)" in TOKEN_CSS
          and "--z-topbar:" in TOKEN_CSS)
    check("the shell's proportions are tokens, so the two surfaces cannot drift "
          "to 14.5rem and 13.5rem again",
          "--nav-w:" in TOKEN_CSS and "--shell-gap:" in TOKEN_CSS)

    # Labels: every status either surface can render must have words.
    check("every task status reads as words", all(
        label(s) and " " not in label(s).strip()[:1] for s in STATUS))
    check("no label leaks the machine spelling",
        not any("_" in v for v in LABELS.values()))
    check("in_progress reads as English", label("in_progress") == "In progress")
    check("wontfix keeps its apostrophe", label("wontfix").startswith("Won"))
    check("an unknown status degrades to something readable, never to blank",
          label("awaiting_review") == "Awaiting review")
    check("a missing value is empty, not the string None",
          label(None) == "" and label("") == "")
    check("the flat map covers task AND bug statuses",
          set(STATUS) <= set(LABELS) and set(BUG_STATUS) <= set(LABELS))

    print(("ALL PASS: %d/%d cases passed" if not bad else
           "SELFTEST FAILED: %d/%d cases passed") % (ok, ok + bad))
    return 1 if bad else 0


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    print(__doc__.strip())
