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

The CSS lint helpers live here too, next to the stylesheet they police — and so
does the read that puts `scripts/ui/` in front of them (`UI_DIR`, `read_asset`,
`cr_violations`, `unreadable_assets`). `_report_ui` and `_panel_ui` are layer-2
peers and cannot import each other, so this is the lowest layer both can reach:
one io.open contract for the assets, instead of two copies kept in step by hand.

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test__ui_theme.py`, byte-identical labels and all - see
`plugins/audit/tests/_harness.py`. Both surfaces still depend on this module, so
that suite is still the gate; it just runs from one directory over.
"""
import io
import json
import os
import re
import sys

# The path bootstrap: byte-identical in every `.py` under `scripts/`, counted by
# `_output.path_preamble_violations()`. It walks UP to the directory holding
# `_output.py` instead of counting `dirname()` calls, so it does not encode how deep
# this file sits and keeps working if the file is moved into a subdirectory.
# `install_path()` then adds that directory AND every subdirectory of it holding a
# `.py`: the folders are LABELS, NOT NAMESPACES, and every sibling below is still
# reached by a bare basename.
_anchor_dir = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_anchor_dir, "_output.py")):
    _anchor_up = os.path.dirname(_anchor_dir)
    if _anchor_up == _anchor_dir:
        raise ImportError("audit plugin: walked to the filesystem root from %s "
                          "without finding _output.py - the scripts/ anchor is "
                          "gone and no sibling can be imported" % (__file__,))
    _anchor_dir = _anchor_up
if _anchor_dir not in sys.path:
    sys.path.insert(0, _anchor_dir)

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()

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
  /* Every ink below clears 4.5:1 against ALL THREE surfaces, not just --surface.
     The old values were measured against white alone, which is why --muted read
     4.76 on a card and 4.23 on --surface-2 -- the same token, two verdicts. */
  --bg:#f5f7fb;--surface:#ffffff;--surface-2:#eef2f7;--text:#0f172a;--muted:#606f85;
  --border:#e2e8f0;--border-strong:#cbd5e1;
  /* The boundary that IDENTIFIES a control, at 3:1 against every surface it sits
     on (SC 1.4.11). Deliberately not the decorative border token, which draws
     card edges, table rules and dividers -- none of which the criterion covers,
     and dragging that one to 3:1 would turn every hairline into a hard line.
     Two roles wearing one token is how the fields measured 1.23:1 while looking
     perfectly fine. */
  --field-border:#748eae;
  /* ...and the same boundary once the pointer is on it. It has to be a SEPARATE
     token, because the hover rules reached for --border-strong and that token is
     structure -- dialog edges, the segment rule above a phase row, a dashed
     marker -- which measures 1.32:1. So hovering a button made its edge FAINTER
     than at rest: the state that says "this does something" was removing the
     thing that identified it. Read as a bug, it is the same two-roles-one-token
     defect --field-border was split out to end, one state along. */
  --field-border-hover:#5a708f;
  /* --accent-solid is a FILL under white text, so it answers to both criteria at
     once and they pull in opposite directions: lighten it and the boundary
     against the card clears 1.4.11, darken it and the white label clears 1.4.3.
     The dark value sat between the two -- the primary button and the on-chip
     measured 2.91:1 against --surface-2 -- and was moved the smallest step that
     clears 3:1 while the white label keeps well over 4.5:1. */
  --accent:#0b7c72;--accent-solid:#0c857a;--ring:rgba(13,148,136,.35);
  --st-done:#157f3d;--st-prog:#f59e0b;--st-blocked:#d62323;--st-pending:#55637a;
  /* ca: cancelled is finished, not achieved. Deliberately the quietest ink on
     the sheet — dimmer than pending, and nowhere near done's green: an archive
     full of green would read as a plan delivered.
     It was #94a3b8, which measured 2.56:1 and was the worst text pair in the
     product. "Quietest" is an ORDER, not a licence to be unreadable, so the
     order is what is preserved: cancelled sits at the AA floor (4.51 on the
     worst surface) and pending was moved DOWN with it to 5.9 so the step
     between them stays visible. Reading them as one grey is the failure mode
     of raising only the one that failed. */
  --st-cancelled:#5c708b;
  /* Ink for a TINTED status badge. One solid-fill chip per status needed one ink
     and an exception (amber on white is unreadable, so in_progress alone got dark
     ink) — four statuses wearing three different grammars. A badge tinted from
     its own status colour carries readable ink of that same hue instead, and the
     exception disappears. Mirrors the --rk-*-fg pattern, which already worked. */
  --st-done-ink:#166534;--st-prog-ink:#854d0e;--st-blocked-ink:#b91c1c;
  --st-pending-ink:#475569;--st-cancelled-ink:#606f85;
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
  --border:#1f2b40;--border-strong:#33425c;--field-border:#546c96;
  --field-border-hover:#7288b4;
  --accent:#2dd4bf;--accent-solid:#0f7c73;--ring:rgba(45,212,191,.4);
  --st-done:#34d399;--st-prog:#fbbf24;--st-blocked:#f87171;--st-pending:#94a3b8;
  --st-cancelled:#7a8aa0;
  --st-done-ink:#6ee7b7;--st-prog-ink:#fcd34d;--st-blocked-ink:#fca5a5;
  --st-pending-ink:#cbd5e1;--st-cancelled-ink:#94a3b8;
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
/* The reduced-motion opt-out, in the token layer because it is a USER PREFERENCE
   like `prefers-color-scheme` beside it, and because it belongs to both surfaces.
   It lived in report.css alone (F25): the panel gated two decorations behind
   `no-preference` and left everything else running, so the `.btn` transition
   measured 0.22s inside a context launched with `reducedMotion:'reduce'` --
   200 elements still moving. Measured after: zero.

   No braces in this comment, deliberately. The block scanner counts them, and a
   comment that carried one would corrupt a theme silently -- which is why the
   rule it names cannot be quoted here in full.

   That is not merely an inconsistency. A CSS transition sits ABOVE important
   author declarations in the cascade, so a probe that mutates style and reads
   synchronously gets the transition's START value -- three measurements in this
   repo were reported "did not fire" on that basis and all three were sound.
   Any browser gate that mutates and measures inherits the trap; this removes it.

   Declares no custom property, so the theme compiler substitutes nothing here
   and `compile_theme(DEFAULT_THEME) == TOKEN_CSS` is unaffected. */
@media (prefers-reduced-motion:reduce){
  *{animation-duration:.001ms!important;animation-delay:0!important;transition-duration:.001ms!important}
}
:root[data-theme="light"]{color-scheme:light}
:root[data-theme="dark"]{
  color-scheme:dark;
  --bg:#0a1120;--surface:#111a2b;--surface-2:#172236;--text:#e6edf6;--muted:#93a4bd;
  --border:#1f2b40;--border-strong:#33425c;--field-border:#546c96;
  --field-border-hover:#7288b4;
  --accent:#2dd4bf;--accent-solid:#0f7c73;--ring:rgba(45,212,191,.4);
  --st-done:#34d399;--st-prog:#fbbf24;--st-blocked:#f87171;--st-pending:#94a3b8;
  --st-cancelled:#7a8aa0;
  --st-done-ink:#6ee7b7;--st-prog-ink:#fcd34d;--st-blocked-ink:#fca5a5;
  --st-pending-ink:#cbd5e1;--st-cancelled-ink:#94a3b8;
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
    # ca (F-P-4): the second terminal state — the work will not be done. Named
    # "Cancelled" rather than "Dropped"/"Deprecated" because that is the word
    # the trackers use for it (Linear Canceled, Jira Won't Do, GitHub closed as
    # not planned, ADO Removed), and a plan is read beside them.
    "cancelled": "Cancelled",
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
# The empty bucket, named once (F-P-2). The usage ledger groups spend by phase,
# task and branch with "--" standing for a row that has none, and its `attr`
# dimension carries "unattributed" for the same fact from the other side: work
# with no plan behind it — ad-hoc edits, `#no-plan`, sessions outside the plan.
# That is an ANSWER, not a missing value, and both keys used to reach the screen
# raw: the panel's ranked list said "-- unattributed", its browse table and chart
# legend said "--", the report said both, and the CLI said "--   unattributed"
# and "--      (no task)". Four spellings of one thing across three surfaces,
# each of which a reader met as a hole in the table. The word lives here, beside
# the statuses, for the same reason they do — `in_progress` is a key, "In
# progress" is what a person reads, and neither surface gets to pick its own.
# The STORAGE keys are untouched: the ledger still writes "--"/"unattributed",
# `/audit:usage --attr unattributed` still selects, and the CSV still exports the
# key, because a file that is parsed is not a surface that is read.
UNCATEGORIZED = "Uncategorized"
USAGE_BUCKET = {"--": UNCATEGORIZED, "unattributed": UNCATEGORIZED}
RISK = {"low": "Low", "med": "Medium", "high": "High"}
GATE_TIER = {"observe": "Observe", "warn": "Warn", "ask": "Ask", "deny": "Deny"}

# One flat map for the surfaces that render statuses and bug statuses in the same
# table cell. The two disagree on nothing: `in_progress` reads the same either way.
LABELS = dict(STATUS)
LABELS.update(BUG_STATUS)
# ...and the usage bucket, which every surface renders in the same tables.
LABELS.update(USAGE_BUCKET)

ALL = {"status": STATUS, "bugStatus": BUG_STATUS, "testsMode": TESTS_MODE,
       "risk": RISK, "gateTier": GATE_TIER, "usageBucket": USAGE_BUCKET}


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


# --- themes: the token layer as data ---------------------------------------------
# th (F-P-6). Everything above is ONE stylesheet, and every colour, radius and
# type step in it is already a custom property — which means the visual system
# is editable without touching a rule, IF something can read the values out and
# put different ones back. That is all a "theme" is here.
#
# THE COMPILER SUBSTITUTES, IT DOES NOT REGENERATE. `compile_theme` takes
# TOKEN_CSS and rewrites the VALUES of the tokens a theme names, in place. It
# was tempting to build the stylesheet from a data structure instead; that would
# have thrown away every comment above — the arguments for why the heatmap runs
# dark->light, why in_progress needed its own ink, why the sticky offsets are
# derived — and those comments are the reason the system holds. Substitution
# also makes the guarantee cheap to state and to check: a theme can change token
# values and NOTHING else, and `compile_theme(DEFAULT_THEME) == TOKEN_CSS` byte
# for byte (the `th1` case below).
#
# A theme file is JSON in the DTCG shape (`$value`, light/dark modes) — the
# format that reached its first stable version in 2025-10 — so the same file
# feeds Style Dictionary and friends without a converter.

# Which tokens a theme may touch, in the groups the editor shows them in. The
# runtime geometry (--topbar-h, --sticky-*, --z-*) and the shell metrics are
# deliberately ABSENT: those are measured at runtime or are layout contracts,
# not taste, and a theme that could move them could break the sticky stack in a
# way no colour ever can.
THEME_GROUPS = (
    ("brand", "Brand & surfaces",
     ("--bg", "--surface", "--surface-2", "--text", "--muted",
      "--border", "--border-strong", "--field-border", "--field-border-hover",
      "--accent", "--accent-solid", "--ring")),
    ("status", "Status & risk",
     ("--st-done", "--st-prog", "--st-blocked", "--st-pending", "--st-cancelled",
      "--st-done-ink", "--st-prog-ink", "--st-blocked-ink", "--st-pending-ink",
      "--st-cancelled-ink",
      "--rk-low-bg", "--rk-low-fg", "--rk-med-bg", "--rk-med-fg",
      "--rk-high-bg", "--rk-high-fg")),
    # Locked in the editor by default (not here — this is the vocabulary, not
    # the policy): this palette is validated for colour-vision deficiency and
    # for contrast against these very surfaces, and arbitrary values can make a
    # chart two readers see differently.
    ("charts", "Charts",
     ("--viz-1", "--viz-2", "--viz-3", "--viz-4", "--viz-5", "--viz-6",
      "--viz-7", "--viz-8",
      "--hm-0", "--hm-1", "--hm-2", "--hm-3", "--hm-4", "--hm-5", "--hm-6",
      "--hm-ink", "--bar-neutral", "--rail", "--rail-held")),
    ("shape", "Shape & motion",
     ("--radius", "--radius-lg", "--pill", "--shadow-sm", "--shadow-md",
      "--dur", "--ease")),
    ("type", "Type & fonts",
     ("--sans", "--mono", "--t-1", "--t-2", "--t-3", "--t-label")),
    # Measurements a reader legitimately disagrees about: how wide the section
    # rail is, and how much air sits between the rail and the content. The
    # sticky offsets are still absent — those are measured at runtime.
    ("layout", "Layout",
     ("--nav-w", "--shell-gap")),
)
THEME_TOKENS = tuple(t for _k, _title, names in THEME_GROUPS for t in names)
# Colour tokens carry a value per theme; the rest are declared once (the same
# split `theme_asymmetric_vars` already enforces on the stylesheet).
THEME_SINGLE = frozenset(("--radius", "--radius-lg", "--pill", "--dur", "--ease",
                          "--sans", "--mono", "--t-1", "--t-2", "--t-3",
                          "--t-label", "--nav-w", "--shell-gap"))
# ...with two exceptions that are colour-BEARING but not colours: the shadows
# are declared in both themes, so they are paired like a colour.
THEME_PAIRED = tuple(t for t in THEME_TOKENS if t not in THEME_SINGLE)


def _blocks(css):
    """(start, end) spans of the base :root block and of each dark block.

    Brace-counting is safe here because no comment in this stylesheet contains
    one — pinned by `th7`, so a future comment with a brace fails loudly rather
    than corrupting a theme."""
    out = {"light": None, "dark": []}
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
        span = (start, i - 1)
        head = m.group(0)
        if "prefers-color-scheme" in head or 'data-theme="dark"' in head \
                or "data-theme=dark" in head:
            out["dark"].append(span)
        elif "data-theme" not in head:
            if out["light"] is None:
                out["light"] = span
    return out


_VAL_RE = r"(?<![\w-])%s\s*:\s*([^;}]*)"


def _read_token(text, name):
    m = re.search(_VAL_RE % re.escape(name), text)
    return m.group(1).strip() if m else None


def extract_theme(css=None):
    """The stylesheet, read back as a theme. This IS the default theme: the
    values are never typed twice, so the two cannot drift."""
    css = TOKEN_CSS if css is None else css
    sp = _blocks(css)
    light = css[sp["light"][0]:sp["light"][1]] if sp["light"] else ""
    dark = css[sp["dark"][0][0]:sp["dark"][0][1]] if sp["dark"] else ""
    out = {}
    for name in THEME_TOKENS:
        lv = _read_token(light, name)
        if lv is None:
            continue
        if name in THEME_SINGLE:
            out[name] = {"$value": lv}
        else:
            out[name] = {"$value": lv, "$dark": _read_token(dark, name) or lv}
    return out


# The tokens density scales, and by how much. Spacing carries the change; type
# follows at a THIRD of it — a compact panel wants tighter air far more than it
# wants smaller words, and type that shrinks with the gaps is how "compact"
# turns into "unreadable". `comfortable` is exactly 1.0 in both, which is what
# keeps the byte-pin true for the default theme.
DENSITIES = {"compact": 0.8, "comfortable": 1.0, "spacious": 1.25}
_SPACING_TOKENS = ("--sp-0", "--sp-1", "--sp-2", "--sp-3", "--sp-4", "--sp-5",
                   "--sp-6", "--sp-7")
_TYPE_TOKENS = ("--t-1", "--t-2", "--t-3", "--t-label")
_NUM_UNIT = re.compile(r"^(-?\d*\.?\d+)(rem|em|px)$")


def _scale(value, factor):
    """A CSS length, scaled. Anything this cannot parse is returned unchanged —
    a density must never turn a value it did not understand into garbage."""
    m = _NUM_UNIT.match(str(value or "").strip())
    if not m or factor == 1.0:
        return value
    n = float(m.group(1)) * factor
    # Trimmed the way the stylesheet writes them: `.5rem`, not `0.500rem`.
    out = ("%.4f" % n).rstrip("0").rstrip(".")
    if out.startswith("0."):
        out = out[1:]
    return (out or "0") + m.group(2)


def _density_edits(css, density):
    """{token: scaled value} for a density, read off the sheet's own values."""
    if density in (None, "comfortable") or density not in DENSITIES:
        return {}
    f = DENSITIES[density]
    sp = _blocks(css)
    base = css[sp["light"][0]:sp["light"][1]] if sp["light"] else ""
    out = {}
    for name in _SPACING_TOKENS:
        v = _read_token(base, name)
        if v is not None:
            out[name] = _scale(v, f)
    # Type moves a third as far (see DENSITIES).
    tf = 1.0 + (f - 1.0) / 3.0
    for name in _TYPE_TOKENS:
        v = _read_token(base, name)
        if v is not None:
            out[name] = _scale(v, tf)
    return out


def compile_theme(theme, css=None, layout=None):
    """TOKEN_CSS with this theme's values substituted in. Unknown keys are
    ignored here — `validate_theme` is what reports them; a compiler that also
    judged would make every caller decide twice."""
    css = TOKEN_CSS if css is None else css
    theme = theme if isinstance(theme, dict) else {}
    sp = _blocks(css)
    edits = []          # (start, end, replacement), applied right-to-left
    # Density is a MULTIPLIER over whatever the scale currently says — including
    # a step the theme set by hand. The alternative (an explicit value opts out)
    # was tried and is worse: "compact" would then mean different things on two
    # themes, and a reader who nudged one type step would silently lose the
    # density on it alone.
    density = (layout or {}).get("density") if isinstance(layout, dict) else None
    scaled = _density_edits(css, density)
    factor = DENSITIES.get(density, 1.0)
    tfactor = 1.0 + (factor - 1.0) / 3.0
    names = list(THEME_TOKENS) + [n for n in scaled if n not in THEME_TOKENS]
    for name in names:
        entry = theme.get(name)
        if not isinstance(entry, dict):
            if name not in scaled:
                continue
            entry = {"$value": scaled[name]}
        val = entry.get("$value")
        dark = entry.get("$dark", val)
        if name in _TYPE_TOKENS and tfactor != 1.0:
            val, dark = _scale(val, tfactor), _scale(dark, tfactor)
        spans = [(sp["light"], val)] if sp["light"] else []
        if name not in THEME_SINGLE and name not in scaled:
            spans += [(d, dark) for d in sp["dark"]]
        for span, newval in spans:
            if span is None or newval is None:
                continue
            seg = css[span[0]:span[1]]
            m = re.search(_VAL_RE % re.escape(name), seg)
            if not m:
                continue
            # The LAST declaration in a block has no `;`, so the capture runs to
            # the closing brace and swallows the newline before it. Only the
            # value itself is replaced; the block's own shape is not a theme's
            # to change (this is what the byte-pin caught).
            start = span[0] + m.start(1)
            edits.append((start, start + len(m.group(1).rstrip()), str(newval)))
    for start, end, newval in sorted(edits, reverse=True):
        css = css[:start] + newval + css[end:]
    return css


# What a value may look like. Deliberately narrow: a theme sets VALUES, and a
# value that can carry `url(`, a second declaration or a comment could reach a
# report that gets emailed and published. The report is the reason this is a
# parser and not a passthrough.
_COLOURISH = re.compile(
    r"^(?:#[0-9a-f]{3,8}"
    r"|rgba?\([\d\s.,%/]+\)"
    r"|hsla?\([\d\s.,%/deg]+\)"
    r"|color-mix\(in srgb,[^;{}()]*(?:\([^()]*\))?[^;{}()]*\)"
    r"|transparent|currentColor|inherit)$", re.IGNORECASE)
_SAFE_PLAIN = re.compile(r"^[\w\s.,%#()'\"/+*-]+$")
_UNSAFE = re.compile(r"(?:url\s*\(|@import|expression\s*\(|/\*|\*/|[;{}<>])",
                     re.IGNORECASE)
_SHADOWISH = re.compile(r"^[\w\s.,%#()/-]+$")


def validate_theme(theme):
    """(findings, warnings) for a theme dict. Findings refuse the write;
    warnings are said out loud and written anyway — a contrast a reader chose
    is their call, an unknown token is not."""
    findings, warnings = [], []
    if not isinstance(theme, dict):
        return (["theme must be an object"], [])
    known = set(THEME_TOKENS)
    for name in sorted(theme):
        if name in ("$schema", "$description", "name", "history", "$layout"):
            continue
        if name not in known:
            findings.append("%s: not a token this theme may set (see "
                            "THEME_GROUPS for the list)" % name)
            continue
        entry = theme[name]
        if not isinstance(entry, dict) or "$value" not in entry:
            findings.append("%s: must be an object carrying $value" % name)
            continue
        vals = [("$value", entry.get("$value"))]
        if name not in THEME_SINGLE:
            if entry.get("$dark") in (None, ""):
                # The parity lint refuses a token declared in one theme only,
                # and it is right: the missing half renders transparent.
                findings.append("%s: needs a $dark value too — a colour set in "
                                "one theme only vanishes in the other" % name)
            else:
                vals.append(("$dark", entry.get("$dark")))
        for label, val in vals:
            if not isinstance(val, str) or not val.strip():
                findings.append("%s %s: must be a non-empty string" % (name, label))
                continue
            v = val.strip()
            if _UNSAFE.search(v):
                findings.append("%s %s: %r is not a value — a theme sets values, "
                                "never rules (no url(), no @import, no ';')"
                                % (name, label, v))
                continue
            if name in ("--shadow-sm", "--shadow-md"):
                ok = bool(_SHADOWISH.match(v))
            elif name in ("--sans", "--mono", "--ease", "--radius", "--radius-lg",
                          "--pill", "--dur", "--t-1", "--t-2", "--t-3",
                          "--t-label"):
                ok = bool(_SAFE_PLAIN.match(v))
            else:
                ok = bool(_COLOURISH.match(v))
                if not ok:
                    findings.append("%s %s: %r is not a colour this editor "
                                    "writes (#hex, rgb()/rgba(), hsl()/hsla(), "
                                    "color-mix(in srgb, …), transparent)"
                                    % (name, label, v))
                    continue
            if not ok:
                findings.append("%s %s: %r contains characters a value may not"
                                % (name, label, v))
    warnings.extend(contrast_warnings(theme))
    return (findings, warnings)


# The non-token half of a theme: how dense the page is, and the order the cards
# come in. Deliberately NOT tokens — a density is one decision over eight
# spacing steps, and an order is a list of names, neither of which is a value a
# stylesheet can hold.
def validate_layout(layout):
    """(findings, warnings) for a theme's `layout` block."""
    findings, warnings = [], []
    if layout is None:
        return (findings, warnings)
    if not isinstance(layout, dict):
        return (["layout must be an object"], warnings)
    for k in layout:
        if k not in ("density", "order"):
            warnings.append("unknown key layout.%s (ignored)" % k)
    d = layout.get("density")
    if d is not None and d not in DENSITIES:
        findings.append("layout.density must be one of %s"
                        % sorted(DENSITIES))
    order = layout.get("order")
    if order is not None:
        if not isinstance(order, dict):
            findings.append("layout.order must be an object of view -> [card ids]")
        else:
            for view, names in order.items():
                if not isinstance(names, list) or not all(
                        isinstance(x, str) and x.strip() for x in names):
                    findings.append("layout.order.%s must be a list of card ids"
                                    % view)
    return (findings, warnings)


def _rgb(value):
    """(r, g, b) 0-255 for the hex forms this editor writes, else None."""
    v = str(value or "").strip()
    if not v.startswith("#"):
        return None
    h = v[1:]
    if len(h) in (3, 4):
        h = "".join(c * 2 for c in h[:3])
    if len(h) in (6, 8):
        h = h[:6]
    else:
        return None
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def _lum(rgb):
    def chan(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg, bg):
    """WCAG contrast, or None when either value is not a plain hex colour."""
    a, b = _rgb(fg), _rgb(bg)
    if not a or not b:
        return None
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + 0.05) / (lo + 0.05), 2)


# The pairs a reader actually reads: body text and muted text on each of the
# three grounds. Not a full audit — a warning that names the pair it measured
# is worth more than a score nobody can act on.
# PUBLIC, because the panel's live preview reads this table rather than
# restating it: `_panel_page.py` JSON-dumps it into the page as
# `__CONTRAST_PAIRS__`. It used to be private and the panel carried its own copy
# of FOUR of these six, so a reader editing a theme could be told "no warnings"
# by the draft check while the server would have warned on two pairs - and both
# lists are concatenated into one the reader cannot split.
CONTRAST_PAIRS = (("--text", "--bg", 4.5), ("--text", "--surface", 4.5),
                   ("--text", "--surface-2", 4.5), ("--muted", "--surface", 4.5),
                   ("--muted", "--bg", 4.5), ("--accent", "--surface", 3.0))


def contrast_warnings(theme, base=None):
    """Readability warnings for a theme, measured against the DEFAULT values
    for anything the theme does not override — a theme that changes only the
    accent is still judged on the ground it will actually sit on."""
    base = DEFAULT_THEME if base is None else base
    out = []

    def val(name, mode):
        entry = theme.get(name) if isinstance(theme, dict) else None
        if not isinstance(entry, dict):
            entry = base.get(name) or {}
        return entry.get("$value") if mode == "light" else \
            entry.get("$dark", entry.get("$value"))

    for fg, bg, floor in CONTRAST_PAIRS:
        for mode in ("light", "dark"):
            ratio = contrast_ratio(val(fg, mode), val(bg, mode))
            if ratio is not None and ratio < floor:
                out.append("%s on %s in %s mode is %.2f:1 — below %.1f:1. A "
                           "warning, not a refusal: your theme, your readers."
                           % (fg, bg, mode, ratio, floor))
    return out


DEFAULT_THEME = extract_theme()


# --- where a theme comes from ----------------------------------------------------
# The skills-discovery rule, applied to looks: THIS project first, then you,
# then the built-in. A project theme is committed, so a team shares one look
# through git rather than through screenshots; anybody who does not want that
# simply never creates the project file. `ui.theme` in the config overrides the
# search with a preset name or an explicit path.
#
# Reading is fail-soft on purpose. A theme is decoration: a malformed file must
# degrade to the default look and SAY so, never take the panel or the report
# down with it — the same contract the usage ledger's torn-line tolerance has.
THEME_FILENAME = "audit.theme.json"
PRESETS = {"slate-teal": "the shipped look — Slate & Teal"}


def load_theme_file(path):
    """(theme, error). Never raises; an unreadable or invalid file yields
    ({}, why) so the caller can fall back and report."""
    try:
        with io.open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        return ({}, "unreadable (%s)" % exc)
    if not isinstance(data, dict):
        return ({}, "not a JSON object")
    theme = data.get("tokens") if isinstance(data.get("tokens"), dict) else data
    findings, _warnings = validate_theme(theme)
    if findings:
        return ({}, "invalid: %s" % findings[0])
    layout = data.get("layout") if isinstance(data.get("layout"), dict) else None
    lf, _lw = validate_layout(layout)
    if lf:
        return ({}, "invalid: %s" % lf[0])
    # The tokens ARE the theme (every caller reads it that way); the layout
    # rides alongside on the same object so nothing has to re-read the file.
    if layout:
        theme = dict(theme)
        theme["$layout"] = layout
    return (theme, None)


def resolve_theme(project, config=None, home=None):
    """The theme in effect, and where it came from.

    Returns {"theme", "source", "path", "name", "error"} — `source` is one of
    "config", "project", "user", "default", so every surface can SAY which file
    it is wearing instead of leaving a reader guessing why the panel changed."""
    cfg = config if isinstance(config, dict) else {}
    want = ((cfg.get("ui") or {}).get("theme")
            if isinstance(cfg.get("ui"), dict) else None)
    out = {"theme": {}, "source": "default", "path": None,
           "name": "slate-teal", "error": None}
    candidates = []
    if isinstance(want, str) and want.strip():
        w = want.strip()
        if w in PRESETS:
            out["name"] = w
            return out                      # the built-in IS the default sheet
        candidates.append(("config", w if os.path.isabs(w)
                           else os.path.join(project or ".", w)))
    else:
        candidates.append(("project",
                           os.path.join(project or ".", ".claude", THEME_FILENAME)))
        h = home or os.path.expanduser("~")
        candidates.append(("user", os.path.join(h, ".claude", THEME_FILENAME)))
    for source, path in candidates:
        if not os.path.isfile(path):
            if source == "config":
                out["error"] = "ui.theme points at %s, which is not a file" % path
            continue
        theme, err = load_theme_file(path)
        if err:
            # Named, not swallowed: a theme that silently did nothing would
            # send its author looking for the bug in the wrong place.
            out["error"] = "%s: %s" % (path, err)
            continue
        out.update({"theme": theme, "source": source, "path": path,
                    "name": os.path.splitext(os.path.basename(path))[0]})
        return out
    return out


def theme_layout(theme):
    """The layout block a resolved theme carries, or {}."""
    lay = (theme or {}).get("$layout") if isinstance(theme, dict) else None
    return lay if isinstance(lay, dict) else {}


def token_css_for(project, config=None, home=None):
    """(css, info) — the stylesheet this project should be served."""
    info = resolve_theme(project, config, home)
    info["layout"] = theme_layout(info["theme"])
    if not info["theme"]:
        return (TOKEN_CSS, info)
    return (compile_theme(info["theme"], layout=info["layout"]), info)


def list_themes(project, home=None):
    """Saved themes this project can switch to: the built-in, plus every
    `.claude/themes/*.json`. A preset is a FILE somebody saved, so the list is
    what is on disk rather than a registry to keep in step with it."""
    out = [{"name": "slate-teal", "path": None, "builtin": True}]
    for base in ([os.path.join(project or ".", ".claude", "themes")]
                 + ([os.path.join(home, ".claude", "themes")] if home else [])):
        try:
            names = sorted(os.listdir(base))
        except Exception:
            continue
        for fn in names:
            if not fn.endswith(".json"):
                continue
            out.append({"name": os.path.splitext(fn)[0],
                        "path": _output.posix_rel(os.path.join(base, fn),
                                                  project or "."),
                        "builtin": False})
    return out


# --- the ui/ assets on disk ------------------------------------------------------
# `_report_ui` and `_panel_ui` assemble their pages out of the same directory with
# the same io.open call, the same CR check and the same exception tuple — typed
# twice, down to the wording of the docstrings, because they are LAYER-2 PEERS and
# neither may import the other. This module is the lowest layer both already reach
# (both selftests call `unterminated_css_decls` below), so it is the only legal
# home for the read.
#
# Nothing here knows which surface is asking. The asset NAMES stay with the surface
# that owns them; what lives here is the contract every read of them obeys.
# Read from the anchor rather than joined here. The anchor's own walk needs the
# same directory (`ui_surface_digests()`, at layer 0, for the screenshot rule),
# and two joins of one path is how a restructure moves one of them.
UI_DIR = _output.UI_DIR


# Every file `scripts/ui/` holds, DECLARED once. Three suites used to carry their
# own copy of this tuple, and splitting `report.js` into ordered parts turned all
# three red at once — which is the cheap version of the failure. The expensive
# version is a part nobody declares: the page would assemble without it and every
# substring pin would go on passing against a script missing a whole feature.
#
# `ua_declared_assets()` compares this against the directory in BOTH directions,
# so a new part that is not declared fails, and a declared name that no longer
# exists fails too.
# Documentation is excluded BY NAME rather than assets being allowed by name.
# A whitelist makes every new kind of file default to unwatched; this way a part
# with an unfamiliar extension is reported instead of ignored, which is the loud
# direction.
# From the anchor for the same reason `UI_DIR` is: the screenshot rule's walk skips
# documentation too, and a suffix honoured by one of the two walks and not the other
# would be a README inside a digest, or an asset outside this comparison.
_DOC_SUFFIXES = _output.UI_DOC_EXT

# THE CASCADE ORDER of the report's stylesheet parts, declared once. Two rules
# of equal specificity are decided by which is read last, so this sequence is
# behaviour and not filing: the shell before what sits in it, and the print
# and forced-colours blocks after the colours they override.
#
# It lives HERE rather than beside the assembler because the theme lints run
# at this layer and must audit the sheet in the order that SHIPS. Sorting
# these names alphabetically would audit a sheet nobody serves.
REPORT_CSS_PARTS = (
    "report-css/shell.css",
    "report-css/summary.css",
    "report-css/controls.css",
    "report-css/badges.css",
    "report-css/tables.css",
    "report-css/gate-rail.css",
    "report-css/empty-state.css",
    "report-css/forced-colors.css",
    "report-css/motion-and-print.css",
    "report-css/ready-now.css",
    "report-css/segments.css",
    "report-css/usage.css",
    "report-css/print-segments.css",
)

# THE CASCADE ORDER of the panel's stylesheet parts, and it lives here for the
# same reason the report's does: the lints below audit the sheet in the order
# that SHIPS, so the one declaration has to sit where they can see it.
#
# The sequence is the file's own, cut and not regrouped: the token placeholder
# and the reset first, then the shell the five views are drawn in, then the
# primitives they compose from, then one view at a time. Some names say out loud
# that the order is not filing - `usage-narrow.css` holds the usage tab's
# below-34rem overrides, which sit AFTER the tooltip in the sheet and therefore
# in a part of their own; `usage-tables.css` and `overview-rows.css` are the
# runs their features resume in after another feature interrupts them. Sorting
# these names alphabetically would change what ships.
PANEL_CSS_PARTS = (
    "panel-css/tokens-and-reset.css",
    "panel-css/app-shell.css",
    "panel-css/base-controls.css",
    "panel-css/usage-tab.css",
    "panel-css/usage-heatmap.css",
    "panel-css/usage-tables.css",
    "panel-css/browse-dialog.css",
    "panel-css/identity-pill.css",
    "panel-css/confirm-dialog.css",
    "panel-css/help-drawer.css",
    "panel-css/tooltip.css",
    "panel-css/usage-narrow.css",
    "panel-css/settings-form.css",
    "panel-css/save-result.css",
    "panel-css/labels-and-hints.css",
    "panel-css/combobox.css",
    "panel-css/blocks-and-ado.css",
    "panel-css/status-colours.css",
    "panel-css/composition.css",
    "panel-css/overview-filters.css",
    "panel-css/appearance-table.css",
    "panel-css/overview-rows.css",
    "panel-css/policy.css",
    "panel-css/proposals.css",
)

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
    "shared/plural.js",
    "shared/storage.js",
    "shared/theme.js",
)


def declared_asset_drift(directory=None):
    """(missing_from_disk, undeclared_on_disk) -- UI_ASSETS against the directory.

    Both directions, because they fail differently: a declared name that is gone
    breaks every reader at import, loudly; an UNDECLARED file on disk is the
    quiet one -- the page assembles without it and the substring pins keep
    passing against a script that lost a feature.
    """
    root = UI_DIR if directory is None else directory
    walk_errors = []
    try:
        on_disk = set()
        # `onerror` is the whole guard: os.walk swallows an unreadable directory
        # by default, yielding nothing and raising nothing, so a missing tree
        # would come back as "no assets" and read as agreement.
        for base, _dirs, files in os.walk(root, onerror=walk_errors.append):
            rel = _output.posix_rel(base, root)
            for f in files:
                # Assets only. A directory may also carry documentation, which
                # is never assembled into a page and must not read as an
                # undeclared part; the extension is what separates the two.
                if f.startswith(".") or f.endswith(_DOC_SUFFIXES):
                    continue
                on_disk.add(f if rel == "." else (rel + "/" + f))
    except OSError:
        # Naming it beats returning the same empty pair a clean directory returns.
        return (list(UI_ASSETS), [])
    if walk_errors:
        return (["<unreadable: %s>" % (walk_errors[0],)], [])
    declared = set(n for n in UI_ASSETS if not n.endswith(_DOC_SUFFIXES))
    return (sorted(declared - on_disk), sorted(on_disk - declared))


def read_asset(name, directory=None):
    """One `ui/` asset, decoded as utf-8 with NO line-ending translation.

    `newline=""` is the load-bearing part, not a tidy default. Both surfaces
    assemble their page by concatenating these files and then prove the result
    BYTE FOR BYTE — the report pins `CSS == TOKEN_CSS + the joined report-css/
    parts` and that the text between its `<script>` tags is the joined report/
    parts unmodified; the panel pins that the spliced `<style>` span IS the
    joined panel-css/ parts — and every cross-line pin in either
    suite spans a newline. Read with Python's default universal-newline
    translation, a CRLF checkout (windows-latest CI with core.autocrlf rewriting
    the repo) hands back "\\n" where the file holds "\\r\\n", so those proofs would
    pass against bytes no browser ever receives. `.gitattributes` pins
    `plugins/audit/scripts/ui/** text eol=lf` for the other half of the same
    contract: the attribute keeps CRLF from happening, this flag keeps it VISIBLE
    when it does (see `cr_violations`).

    `directory` exists so a test can point the reader at a fixture tree; every
    caller in the tree takes the default."""
    root = UI_DIR if directory is None else directory
    with io.open(os.path.join(root, name), "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def cr_violations(assets):
    """Given [(name, text), ...], the names whose text carries a "\\r".

    `read_asset` translates nothing, so a CRLF checkout arrives here as a literal
    "\\r" in the loaded text rather than as nothing at all — which is the whole
    point of reading that way. A pure function of the pairs it is handed, with no
    filesystem access, so a test can feed it fixture content without touching
    UI_DIR.

    An empty `assets` yields an empty list, and that means "nothing was checked",
    not "every asset is LF". Both callers pass a fixed literal list of the assets
    they have just read, so the distinction cannot bite them; a caller that built
    the list by filtering would have to say the set was empty itself."""
    return [name for name, text in assets if "\r" in text]


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


if __name__ == "__main__":
    import sys
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exits silently: `--selftest` is what every other
        # file here still accepts, so nothing would tell a reader whether this
        # one ran nothing or has nothing. It deliberately does NOT print the
        # suite contract - that literal is how `_output.selftest_coverage()`
        # tells an inline suite from a migrated one.
        print("_ui_theme.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__ui_theme.py - run that file instead.")
        raise SystemExit(0)
    print(__doc__.strip())
