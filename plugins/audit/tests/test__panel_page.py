#!/usr/bin/env python3
"""
The cases for `_panel_page.py`, moved out of it - an importable helper.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list. This is the biggest single move in the migration: 1,636 of
that file's 1,759 lines were this suite (it is 134 lines now), and 663 of the reads
in these cases are of one string, `M.UI_HTML` - the panel's assembled page.

ONE CASE COULD NOT MOVE LITERALLY, AND IT IS `pg2`. It reads the SUBJECT's source and
fails if `_panel_page.py` ever imports panel-server or the panel's read/write sides -
the import rule that is the whole reason a layer-4 home exists for that file. Inline
that was `open(__file__)`; from here it would read THIS file, which imports none of
the four and never will, so the case could only ever pass. It is `M.__file__` now,
and was proven red by planting `import _panel_state` in the subject: the literal form
stays green on a violating module, the re-pointed form fails and names it.

`_loader`, `_panel_ui`, `_panel_settings` and `_ui_theme` are imported here the way
`_panel_page.py` imports them, because these cases compare against those modules' own
objects (`_theme.TOKEN_CSS`, `_panel_ui.raw_template(cache=False)`,
`_panel_settings._validate_config()`). Everything the SUBJECT owns - `UI_HTML`,
`UI_TEMPLATE`, the settings-form aliases and the four stylesheet lints - carries the
`M.` prefix.

`_help` MOVED WITH THE CASES, AND THAT RETIRES AN IMPORT EDGE. It was imported inside
`_selftest()` rather than at module scope, deliberately, so a server whose start-up
cost is paid on every `/audit:panel` never loaded it; `_deps` reads function bodies,
so it was still a real (downward, L4 -> L3) edge in the module map. With the suite
here, `_panel_page` no longer reaches `_help` at all and the generated fence in
PLUGIN-BUILD-GUIDE.md was regenerated to say so. Nothing was in KNOWN_LAYER_DEBT for
it - the edge was downward - so no entry retired.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import re
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _help                                       # noqa: E402  (topic ids + COMPOSITION_PATHS)
import _loader                                     # noqa: E402  (as _panel_page imports it)
import _panel_settings                             # noqa: E402  (as _panel_page imports it)
import _panel_ui                                   # noqa: E402  (the raw template, uncached)
import _ui_theme as _theme                         # noqa: E402  (as _panel_page imports it)
import _panel_page as M                            # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- build order ----------------------------------------------------------
    # The one claim no `... in UI_HTML` case can make, and the only thing that goes
    # red if the snapshot point moves. UI_TEMPLATE is taken AFTER the last
    # substitution and BEFORE the theme one, so restoring the default theme into it
    # must reproduce UI_HTML byte for byte. Take the snapshot one line earlier and
    # UI_TEMPLATE still carries `__COST_BAND_PARAMS__` (or __CFG_ENUMS__, or any of
    # the eight) - every case below still passes, and every page do_GET serves is
    # broken. Proven red by moving `UI_TEMPLATE = UI_HTML` up one line.
    check("pg1 UI_TEMPLATE is UI_HTML with ONLY the theme block left as a marker: "
          "the snapshot sits after every other substitution, so dressing it in the "
          "default theme reproduces UI_HTML exactly",
          M.UI_TEMPLATE.replace("/*__THEME_TOKENS__*/", _theme.TOKEN_CSS) == M.UI_HTML
          and "/*__THEME_TOKENS__*/" in M.UI_TEMPLATE
          and "/*__THEME_TOKENS__*/" not in M.UI_HTML)

    # --- stylesheet integrity ---------------------------------------------------
    # The existing CSS checks look at custom properties; nothing checked structure,
    # and an unbalanced brace had been shipping. A stray `}` at top level is merely
    # discarded, but the same slip one nesting level deeper silently terminates a
    # block and drops every rule after it, with nothing in the console.
    _css = re.search(r"<style>([\s\S]*?)</style>", M.UI_HTML)
    check("panel stylesheet is present", _css is not None)
    if _css:
        _sheet = _css.group(1)
        _depth, _stray = 0, []
        for _i, _line in enumerate(_sheet.split("\n"), 1):
            for _ch in _line:
                if _ch == "{":
                    _depth += 1
                elif _ch == "}":
                    _depth -= 1
                    if _depth < 0:
                        _stray.append(_i)
                        _depth = 0
        check("panel stylesheet has no stray '}' (%r)" % (_stray[:3],), not _stray)
        check("panel stylesheet closes every block (depth %d)" % _depth, _depth == 0)


    # The confirm dialog computes its rows in the browser and the server recomputes
    # them from the file; a key on one list and not the other is a mismatch warning
    # about nothing. Derived, so adding a meta key cannot leave the two out of step.
    check("the dialog's meta fields are exactly the ones the FORM can edit",
          "for(const k of %s)" % json.dumps(list(M._META_FORM_KEYS)).replace(
              '"', "'").replace(", ", ",") in M.UI_HTML,
          )
    check("an API-only meta key is deliberately absent from that list - the "
          "dialog must not describe an edit this form cannot make",
          all("'%s'" % k not in M.UI_HTML.split("function compChanges")[1][:400]
              for k in M._META_API_ONLY))

    # c6's server half (the change rows a save echoes) and the journal call site
    # moved to _panel_write.py (P12.4). What stays below and further down is the
    # browser's half of the same contract, pinned against UI_HTML.

    check("the UI badges an abandoned lock differently from a running one",
          "no live run" in M.UI_HTML and ".badge.held" in M.UI_HTML)

    check("D9: and the poll repaints ONLY Overview - re-rendering from full state "
          "would discard whatever is half-typed in the settings form",
          "if(!$('#over').classList.contains('hidden'))renderOver();" in M.UI_HTML
          and "renderSettings()" not in M.UI_HTML[M.UI_HTML.index("async function pollRunStatus"):
                                                M.UI_HTML.index("// ---------- Overview")])
    check("D9: it skips identical payloads rather than repainting on a timer",
          "runStatusKey(next)===runStatusKey(RUNSTATUS)" in M.UI_HTML)
    check("D9: it stops while the tab is hidden, and catches up on return",
          "if(document.hidden)return;" in M.UI_HTML
          and "visibilitychange" in M.UI_HTML)
    check("D9: a failed poll leaves a stale badge rather than killing the panel",
          "catch(e){/* a panel that dies because a poll failed" in M.UI_HTML)

    check("UI renders area badges (per tag) + area-searchable composition",
          ".badge.area" in M.UI_HTML and "P.area" in M.UI_HTML
          and "(p.area||[]).map" in M.UI_HTML)

    # UI template integrity (token/project placeholders present, no stray %)
    check("UI has token placeholder", "__AUDIT_TOKEN__" in M.UI_HTML)
    check("UI has project placeholder", "__AUDIT_PROJECT__" in M.UI_HTML)

    # `list:` alone was the spelling here, and it is not a datalist — it matched
    # `{scope, list: 'deny', pattern}` in the policy view, which is a field name.
    # A native datalist needs the ATTRIBUTE, which in this file's `el()` calls is
    # always `list:'…'`, and the element it points at.
    check("UI uses the custom combobox, not a native datalist",
          "function comboWrap(" in M.UI_HTML and "combo-menu" in M.UI_HTML
          and "<datalist" not in M.UI_HTML and "list:'" not in M.UI_HTML)
    check("UI labels carry info hints", "function hint(" in M.UI_HTML and "data-tip" in M.UI_HTML)

    # --- Settings: the whole config, named by what it does ---------------------
    # The coverage checks (SETTINGS_GROUPS/FIELD_HELP derived against
    # validate-config's own key sets) live in _panel_settings.py's own selftest
    # (P12.1); the cases that need a server call (the exempt key's route, the
    # bands key the validator accepts) stayed in panel-server.py. What is here
    # needs the assembled page.
    #
    # `_vc` is the validator itself, reached through _panel_settings' own cached
    # loader rather than through _panel_state._cores(): the loader's memo is keyed
    # by realpath, so this is the SAME module object panel-server gets, and this
    # file may not reach _panel_state (layer 5) from layer 4.
    _vc = _panel_settings._validate_config()
    check("a field whose default is null can still say what empty means - an "
          "empty box beside an empty placeholder says nothing at all",
          "placeholder:def==null?(f.placeholder||''):String(def)" in M.UI_HTML
          and "beside the manifest" in M.UI_HTML)
    check("the form's shape, its help and its enums are injected from Python - "
          "the JS literal they replaced is what let the two drift",
          "const DESC={" not in M.UI_HTML
          and "const SETTINGS=" in M.UI_HTML and "__SETTINGS__" not in M.UI_HTML
          and "__FIELD_HELP__" not in M.UI_HTML and "__CFG_ENUMS__" not in M.UI_HTML
          and M.FIELD_HELP["usage.pricingAsOf"] in M.UI_HTML)
    # `warn-always` was documented in four places, implemented, and rejected by the
    # validator — so following the docs produced a config the panel refused to save.
    # A hand-kept <option> list is that failure with one more place to forget.
    check("the enum choices ARE the validator's tuples, not a copy of them",
          json.dumps(M._cfg_enums(), sort_keys=True) in M.UI_HTML
          and set(M._cfg_enums()["inProgressPolicy"]) == set(_vc.IN_PROGRESS_POLICY)
          and set(M._cfg_enums()["authorMode"]) == set(_vc.AUTHOR_MODES))
    check("an empty field REMOVES the key rather than writing an empty string - a "
          "config listing every default is unreadable and freezes today's defaults",
          "function delPath(" in M.UI_HTML and "delPath(cfg,f.path)" in M.UI_HTML)
    # --- gt: the planGate control (v0.34 B1) ------------------------------------
    # One statement of the gate's tier: the select's preset reads the LEGACY
    # enforce flag, and any change writes planGate while deleting enforce.
    _pgf = (M.UI_HTML[M.UI_HTML.index("function planGateField("):]
            if "function planGateField(" in M.UI_HTML else "")
    _pgf = _pgf[:_pgf.index("\nfunction ")] if "\nfunction " in _pgf else _pgf
    check("gt: the planGate control is a custom field wired into the CUSTOM map",
          "function planGateField(" in M.UI_HTML
          and "'planGate':()=>planGateField(cfg)" in M.UI_HTML)
    check("gt: its preset reads planGate FIRST and the legacy enforce:true as "
          "'deny' - inside the field's own slice (the F-D1 lesson)",
          "cfg.planGate??(cfg.enforce===true?'deny':'')" in _pgf)
    check("gt: a change writes planGate and deletes enforce - one statement of "
          "the tier survives a save",
          "setPath(cfg,'planGate',v)" in _pgf
          and "delPath(cfg,'planGate')" in _pgf
          and "delPath(cfg,'enforce')" in _pgf)
    check("gt: the legacy preset says out loud where it came from and what "
          "saving does about it",
          "legacy enforce: true" in _pgf and "rewrites it as planGate" in _pgf)
    check("gt: the tier choices are the validator's own tuple, served through "
          "_cfg_enums like every other enum on the form",
          M._cfg_enums().get("planGate") == list(_vc.PLAN_GATE_MODES)
          and "ENUMS.planGate" in _pgf)
    # The Overview card fed by the polled gate block. Its code lives in
    # renderOver, BELOW the Overview marker, so the D9 slice (pollRunStatus ->
    # marker never touches renderSettings) stays intact by construction.
    _over_src = M.UI_HTML[M.UI_HTML.index("function renderOver("):]
    check("gt: the Overview draws a Plan gate card from the polled payload - "
          "tier + source, the bypass indicator, and the events table",
          "id:'gatecard'" in _over_src and "'Plan gate'" in _over_src
          and "rs.gate" in _over_src
          and "'data-bypass-armed':'1'" in _over_src
          and "'data-ev':e.event||''" in _over_src
          and "No gate events yet" in _over_src)

    check("and it drops the container it emptied, so no \"usage\": {} is left behind",
          "if(par&&typeof par==='object'&&!Object.keys(par).length)" in M.UI_HTML)
    check("Settings keeps the route, the screenshot name and the pinned id it "
          "already had - an internal id is an address, not a description",
          "data-t=guards aria-current=\"true\">Settings<" in M.UI_HTML
          and "$('#guards')" in M.UI_HTML)
    check("one Save for four cards, and it is reachable from all of them",
          M.UI_HTML.count("'/api/config'") == 1 and ".savebar{position:sticky" in M.UI_HTML)
    # --- the three facts the form has to state out loud ------------------------
    check("tokenVars: an empty box means the three defaults are ACTIVE, and says so "
          "rather than looking like nothing is protected",
          "'defaults are active:'" in M.UI_HTML and "chip ghosted" in M.UI_HTML)
    check("tokenVars: and a non-empty one warns that the list REPLACES them, "
          "naming what stopped being covered",
          "Your list REPLACES the defaults" in M.UI_HTML
          and "'put them back'" in M.UI_HTML)
    check("secret patterns say regex-not-glob, with the anchor a reader needs",
          "matched case-insensitively anywhere in " in M.UI_HTML
          and "\\\\.env$" in M.UI_HTML)
    check("custom rules are labelled 'path contains' and say SUBSTRING, because "
          "four documents said 'starts with' while the hook tested `prefix in path`",
          "'path contains'" in M.UI_HTML
          and "The path test is a SUBSTRING match, not a '" in M.UI_HTML
          and "starts with" not in M.UI_HTML)
    check("both guard fields state the silent skip - a malformed rule is dropped "
          "without a word at runtime, and saving here refuses it instead",
          M.UI_HTML.count("skipped in silence") >= 1
          and "dropped in silence at runtime" in M.FIELD_HELP["secretPatterns.extra"])
    check("a regex the browser rejects is marked, and the microcopy does NOT claim "
          "the reverse - Python's engine is the one that decides on save",
          "function reErr(" in M.UI_HTML
          and "your browser rejects this pattern: " in M.UI_HTML
          and "decided by Python’s engine" in M.UI_HTML)
    check("the band pair is linted against the SAME predicate cost_bands applies, "
          "and names the fallback that is otherwise silent",
          "if(!(hi>0&&hi<=ou))" in M.UI_HTML
          and "fall back to the project-relative basis" in M.UI_HTML)

    check("pricing rows write only what you change - an empty cell keeps the "
          "shipped rate rather than storing a copy of it",
          "if(inp.value===''){if(o[m])delete o[m][k];}" in M.UI_HTML
          and "delPath(cfg,'usage.pricing')" in M.UI_HTML)
    check("the key beside a heading keeps its own case - h2 is uppercased and a "
          "config key is case-sensitive, so an uppercased one cannot be pasted back",
          ".k2{" in M.UI_HTML and "text-transform:none" in M.UI_HTML[
              M.UI_HTML.index(".k2{"):M.UI_HTML.index(".k2{") + 200])
    # --- the project path is one line -----------------------------------------
    # The RULE, not the string: the comment above it names `word-break:break-all`
    # to say what was removed and why, and a substring test over the whole document
    # cannot tell the fix from the note explaining it.
    _sub = M.UI_HTML[M.UI_HTML.index(".sub{"):]
    _sub = _sub[:_sub.index("}")]
    check("the project path is middle-elided rather than wrapped across the header",
          "function midElide(" in M.UI_HTML and "midElide(PROJECT" in M.UI_HTML
          and "word-break" not in _sub and "text-overflow:ellipsis" in _sub)
    check("and the full path survives in the tooltip, so nothing is lost",
          "$('#proj').title=PROJECT" in M.UI_HTML)

    # --- app shell -------------------------------------------------------------
    check("shell: navigation at the side, actions on top",
          '<div class=shell>' in M.UI_HTML and '<nav class=tabs' in M.UI_HTML
          and '<main class=view>' in M.UI_HTML)
    check("shell: the four sections are ONE list that changes presentation, not "
          "two menus - a column above 70rem, a strip below it",
          ".tabs{display:flex;flex-direction:column" in M.UI_HTML
          and "@media(max-width:70rem){\n .tabs{flex-direction:row" in M.UI_HTML)
    check("shell: the active view is announced, not only coloured - these are "
          "exclusive views and a background change tells a screen reader nothing",
          'aria-current="true"' in M.UI_HTML and "x.setAttribute('aria-current'" in M.UI_HTML
          and "x.removeAttribute('aria-current')" in M.UI_HTML)
    # A view still never inherits ANOTHER view's scroll position — but it keeps its
    # own. Slamming to the top meant a glance at Usage cost you your place in a
    # 50-phase Composition table, every time.
    check("shell: each view remembers where you were in it, and never inherits "
          "another view's position",
          "SCROLL[CURTAB]=window.scrollY" in M.UI_HTML
          and "SCROLL[t]||0" in M.UI_HTML
          and "requestAnimationFrame(()=>window.scrollTo" in M.UI_HTML)
    check("shell: views are addressable, so a tab can be linked and a reload does "
          "not always land on Guards",
          "history.replaceState(null,''" in M.UI_HTML and "'#/'+t" in M.UI_HTML
          and "addEventListener('hashchange'" in M.UI_HTML
          and "function initialTab()" in M.UI_HTML)
    check("shell: the scrollbar's width is reserved, so a short view and a long "
          "one do not centre the shell at two different offsets",
          "scrollbar-gutter:stable" in M.UI_HTML)
    # Verbatim containment, so the two surfaces cannot drift to 14.5rem and
    # 13.5rem again without this failing; and declared ONCE, so the copy this
    # replaced cannot quietly come back alongside it.
    check("shell: the panel renders the shared token layer, not a hand-kept copy",
          _theme.TOKEN_CSS in M.UI_HTML
          and M.UI_HTML.count("--nav-w:") == 1
          and M.UI_HTML.count("--bg:#f5f7fb") == 1)
    check("shell: a saved-or-refused result is announced, not only shown",
          "id=toast role=status aria-live=polite" in M.UI_HTML)
    # `in_progress` was reaching people in the status pill, the phase row and the
    # filter buttons — the three places you look to find out how the work is going.
    check("labels: statuses read as words, with the machine value kept in "
          "data-status so theming and filtering still compare keys",
          "const LABELS=" in M.UI_HTML and '"in_progress": "In progress"' in M.UI_HTML
          and "label(ph.status)" in M.UI_HTML and "label(t.status)" in M.UI_HTML
          and "label(p.status)" in M.UI_HTML
          and "},ph.status||'—')" not in M.UI_HTML)
    check("labels: Overview colours its status the same way Composition does - "
          "same data, one treatment",
          "el('span',{class:'badge'},p.status" not in M.UI_HTML)
    check("labels: a status filter announces whether it is on",
          "'aria-pressed':'false'},label(s))" in M.UI_HTML)
    # Both of these were exposed by widening the shell, and both were guards tied
    # to the viewport rather than to the thing overflowing.
    check("shell: a wide data table scrolls inside its own box at every width, "
          "not only under 48rem",
          ".comptblwrap{border:1px solid var(--border);border-radius:var(--radius);\n"
          " overflow-x:auto" in M.UI_HTML
          and "@media(max-width:48rem){.comptblwrap{overflow-x:auto}}" not in M.UI_HTML)
    # The tip is ONE element on <body> (0.35.1, third mechanism): a pseudo inside
    # the hint's own box was buried by the comp table's stacking contexts as
    # absolute, and as fixed sat one transformed ancestor from silently demoting
    # back - a live repo paid for each. On <body> nothing can trap, clip or
    # resize it, and nothing exists until showTip() runs, so a tip can no longer
    # grow ANY box's scrollable overflow, hovered or not.
    check("shell: the hint tip is a single body-level element, not a pseudo "
          "inside the box that carries the hint",
          "#hinttip{position:fixed" in M.UI_HTML
          and "document.body.append(b)" in M.UI_HTML
          and "::after{content:attr(data-tip)" not in M.UI_HTML)
    check("shell: an unshown tip does not exist in layout, so it cannot push "
          "any box sideways before anyone hovers it",
          "#hinttip{position:fixed;z-index:200;display:none" in M.UI_HTML)
    # F9's clamp survives the mechanism change: 272px of tip in a 375px column
    # still has no correct anchor, so the geometry is computed - the icon's own
    # x where that fits, the nearest edge where it does not, MEASURED height
    # deciding below-or-above. All of it in JS: the sheet holds no coordinate,
    # so a stale stylesheet cannot disagree with the script about placement.
    check("shell: the open tip is clamped into the viewport with measured "
          "height, and the stylesheet holds none of the geometry",
          "Math.min(Math.max(TIPGUT,r.left),vw-TIPGUT-w)" in M.UI_HTML
          and "const mh=b.offsetHeight;" in M.UI_HTML
          and "--tipx" not in M.UI_HTML and "--tipshift" not in M.UI_HTML
          and ".hint.flip" not in M.UI_HTML)
    # An open tip must not outlive its anchor: the 5s poll re-renders forms
    # under a stationary pointer, replacing the icon node - the observer hides
    # the orphan, and scroll re-anchors a live one (capture: the comp table
    # scrolls inside its own frame).
    check("shell: a tip whose anchor was re-rendered away is hidden, and a "
          "scrolled anchor re-places its tip",
          "TIPFOR.isConnected?showTip(TIPFOR):hideTip()" in M.UI_HTML
          and "if(TIPFOR&&!TIPFOR.isConnected)hideTip()" in M.UI_HTML
          # Boot starts it. The spelling changed when the boot sequence moved
          # inside runContained, so that a throw in one view stops costing the
          # tip placement and the run poller; WHICH steps boot contains is
          # driven for real in tools/ui-tests/boot-containment.test.mjs, and
          # this clause only keeps the call site from disappearing.
          and "runContained([startRunPoll,startTipPlacement])" in M.UI_HTML)
    # F8. Both halves of one rule: a settings row is allowed to shrink, and the
    # words inside it are allowed to wrap. Either one alone leaves the row exactly
    # as wide as its content, which on a 390px screen was 447px of DOCUMENT.
    # The selector is `.f.cbf`, not `label.f.cbf`: a field's container stopped
    # being a <label> when the i had to move out of it (SC 1.3.1 - a <button> is
    # labelable and was taking the association). The NEGATIVE is the load-bearing
    # half. Left in, the element-qualified rule would still match the checkbox row,
    # which IS still a <label>'s neighbour, so this case would go on passing while
    # every OTHER field silently lost its layout - and a screenshot is what it
    # would have taken to notice.
    check("shell: a checkbox row may shrink, so a long setting name cannot set the "
          "page's width - and the rule is not element-qualified, because the "
          "container is a <div> now",
          ".f.cbf{flex-direction:row;align-items:baseline;gap:.4rem;"
          "flex:0 1 auto;min-width:0}" in M.UI_HTML
          and "label.f.cbf{" not in M.UI_HTML
          and "label.f{" not in M.UI_HTML
          and "label.f.wide{" not in M.UI_HTML)
    check("shell: and the label inside it wraps, which is the only reason "
          "shrinking has anywhere to go",
          ".lbl{display:inline-flex;align-items:center;gap:var(--sp-0);"
          "flex-wrap:wrap;min-width:0}" in M.UI_HTML)
    check("UI building blocks are a tabbed table", "regtbl" in M.UI_HTML and "subtab" in M.UI_HTML)
    check("composition is a compact collapsible filterable table",
          "comptools" in M.UI_HTML and "table.comp" in M.UI_HTML and "needs skills" in M.UI_HTML
          and "tr.phase" in M.UI_HTML and "class:'tsk'" not in M.UI_HTML)

    # --- overview (panel c4) ------------------------------------------------
    # The rollup already carried tasks.byStatus, bugs.byStatus, areas and ready[];
    # the tab showed four grey total chips and threw the rest away.
    check("overview: the status strips are the legend AND the filter, one control "
          "for one set of numbers",
          "function ovPill" in M.UI_HTML and ".ovpill{" in M.UI_HTML
          and "OVF.ts=OVF.ts===s?'':s" in M.UI_HTML
          and "OVF.bs=OVF.bs===s?'':s" in M.UI_HTML
          # the four grey totals the strips replace
          and "'ready '+ (r.ready||[]).length" not in M.UI_HTML)
    check("overview: a selected pill is not selected by colour alone",
          '.ovpill[aria-pressed=true]::before{content:"\\2713\\a0"' in M.UI_HTML
          and "'aria-pressed':on?'true':'false'" in M.UI_HTML)
    check("overview: high-severity is a severity cut, not a status - it never "
          "borrows another status's machine value for its colour",
          "'High severity, open'" in M.UI_HTML
          and ".ovpill.hi{--st:var(--err)}" in M.UI_HTML
          and "ovPill('blocked'" not in M.UI_HTML)
    # A filter held in the render closure is wiped by the 5s run-status poll five
    # seconds after it is set — the same repaint D9 deliberately kept narrow.
    check("overview: the filter state is hoisted out of the render, so the poll "
          "cannot wipe it - the VIEW and which phases are open ride it too, or "
          "a 5s badge repaint would fold every row a reader opened",
          "const OVF={q:'',ts:'',bs:'',byArea:false,sort:'plan',view:null,open:{}};"
          in M.UI_HTML
          and M.UI_HTML.index("const OVF=") < M.UI_HTML.index("function renderOver"))
    check("overview: and the caret survives a repaint mid-search",
          "act.id==='ovq'" in M.UI_HTML and "n.setSelectionRange(caret,caret)" in M.UI_HTML)
    check("overview: a phase row is a real button - keyboard reachable without a "
          "hand-written role/tabindex/keydown trio",
          "const row=el('button',{class:'ovrow'+(open?' open':''),type:'button',"
          in M.UI_HTML
          and "role:'button'" not in M.UI_HTML)
    # ov (F-P-5): pressing a phase used to LEAVE this tab for Composition — the
    # tab that edits tasks, models and skills. "Show me this phase" answered
    # with a form, and the Overview filters left behind. It opens in place now;
    # Composition is a named button inside the detail, not the default.
    check("overview: a phase opens IN PLACE, and going to Composition is an "
          "explicit, named press rather than what a click happens to do",
          "onclick:()=>{OVF.open[p.id]=!open;renderOver();}" in M.UI_HTML
          and "onclick:()=>openInComp(p.id)},'Edit in Composition')" in M.UI_HTML
          and "title:'open '+p.id+' in Composition',onclick:()=>openInComp(p.id)"
          not in M.UI_HTML)
    check("overview: ...and openInComp still exists for that press, unchanged",
          "function openInComp(pid){COMPF.q=pid;" in M.UI_HTML
          and "if(COMPF.apply)COMPF.apply();showTab('comp');" in M.UI_HTML)
    check("ov: Overview follows the report's table - the same segments, the "
          "same three views, the same default rule, and the same sentence when "
          "a match falls outside the view",
          "const segOf=st=>st==='done'||st==='cancelled'?'archived'" in M.UI_HTML
          and "const SEG_VIEWS={active:['active','pending'],archived:['archived']," in M.UI_HTML
          and "data-ovview" in M.UI_HTML
          and "data-ovoutside" in M.UI_HTML
          and "' phases match')+' outside this view" in M.UI_HTML)
    check("ov: the phase detail is the report's task columns, read-only - id, "
          "title, status, risk as coloured TEXT, commit and the completion "
          "stamp to the minute",
          "function ovDetail(" in M.UI_HTML
          and "el('th',{},'risk'),el('th',{},'commit'),el('th',{},'done (UTC)')"
          in M.UI_HTML
          and "class:'rk','data-risk':t.risk" in M.UI_HTML
          and ".rk[data-risk=\"high\"]{color:var(--err)}" in M.UI_HTML)
    check("composition's filter state is hoisted too, so it survives a re-render",
          "const COMPF={q:'',status:'',needs:false,open:{},apply:null};" in M.UI_HTML
          and "const open=COMPF.open;" in M.UI_HTML
          and "COMPF.apply=()=>{q.value=COMPF.q;syncFilters();refresh();};" in M.UI_HTML)
    # --- c6: confirm before write, and who is writing --------------------------
    # These are string pins, and string pins cannot tell a working panel from a
    # dead one — the whole inline script is one <script>, so a missing paren kills
    # every view while every `'…' in UI_HTML` here still passes. The behaviour is
    # driven for real in tools/capture-screenshots.mjs (assertConfirmFlowWorks,
    # assertViewerIdentity); these guard the constructs those checks depend on.
    check("the topbar names the identity a write will be recorded under",
          "<span class=who id=who hidden></span>" in M.UI_HTML
          and "function renderViewer()" in M.UI_HTML
          and "runContained([renderViewer,renderSettings," in M.UI_HTML)
    check("the write dialog names the identity too — the topbar pill is dropped "
          "below 34rem, which is where the question is least easy to answer",
          "'data-cfwho':who&&!o.danger?'1':null" in M.UI_HTML
          and "(who&&!o.danger?'as '+who+' · ':'')" in M.UI_HTML
          and "@media(max-width:34rem){.who{display:none}}" in M.UI_HTML)
    check("no author resolved -> a way to the setting that decides it, not a blank",
          "settingsLink(v.mode==='none'?'not recorded':'unknown','usage.authorMode')"
          in M.UI_HTML)
    # THE ENUMERATION IS HERE, and it is hand-kept, which is why it is not the
    # only thing checking it. The literal used to carry a partial list of its own
    # and went stale twice - three names while four, then five, registered - so
    # the registry now starts empty and the list lives where a miss fails by
    # name. What this cannot see is a NEW writable surface that never registers;
    # assertSavebarCensus in tools/capture-screenshots.mjs asks the live page
    # that question, by cross-checking every view offering a Save against
    # Object.keys(EDITS).
    check("unsaved work is registered per surface, and every writable surface "
          "known today registers — a surface that forgets is one beforeunload "
          "cannot protect",
          "const EDITS={};" in M.UI_HTML
          and "EDITS.comp=()=>compChanges(patch);" in M.UI_HTML
          and "EDITS.guards=()=>configChanges(cfg);" in M.UI_HTML
          and "EDITS.policy=()=>policyChanges();" in M.UI_HTML
          and "EDITS.ado=()=>adoRows(saved,ADRAFT);" in M.UI_HTML
          # The theme card: registered last of the five, because its draft lives
          # in memory only and a closing tab used to take it silently.
          and "EDITS.look=()=>tChangeRows();" in M.UI_HTML)
    # `some(surfaceDirty)`, not `dirtyRows().length`. A surface whose change
    # computation THROWS used to answer `[]` - the same answer as a clean one - so
    # the close was not interrupted and the reader lost everything typed since the
    # last save. `surfaceDirty` answers true for "cannot tell", and the behaviour
    # is asserted in tools/ui-tests/dirty-surface.test.mjs, which a substring pin
    # cannot do: the difference is what happens when a callback raises.
    # The guide card's badge used to print "read-only:" as FIXED TEXT while
    # `_help.guide_card` computed a `readOnly` verdict the page never read - a
    # claim with no basis, on the surface that exists to tell a reader what an
    # agent may do, and nothing asserted the badge's text at all. The wording is
    # decided by `hToolClaim` now; its three answers are asserted in
    # tools/ui-tests/claims.test.mjs and what belongs here is the WIRING.
    # The axis-label guard tested the VALUE where it had to test the POSITION.
    # `[0,n-1].forEach(i=>{if(n<2&&i)return;...})` over one bucket walks [0,0], so
    # `i` is 0 on both passes and the same date was drawn twice - once
    # left-anchored and once right-anchored at the same x. The arithmetic is
    # covered in tools/ui-tests/usage-edges.test.mjs; what belongs here is that
    # the shipped source really takes the index.
    check("ax1 the one-bucket axis guard tests the position, not the value",
          "[0,n-1].forEach((i,j)=>{if(n<2&&j)return;" in M.UI_HTML
          and "'text-anchor':j?'end':'start'" in M.UI_HTML
          and "[0,n-1].forEach(i=>{if(n<2&&i)return;" not in M.UI_HTML)
    # `api()` hands back `r.json()` whatever the status, so a server error that
    # serialises cleanly is a truthy object with no `facts`.
    check("ax2 the Usage tab checks the SHAPE of the payload before indexing it, "
          "so a JSON error response reaches the empty state instead of throwing",
          "if(!USAGE||!Array.isArray(USAGE.facts)||!USAGE.facts.length){" in M.UI_HTML)
    # Every reader of these two maps guards the CONTAINER. Two sites did not, and
    # two spellings of one read is how the live failure eventually arrives.
    check("ax3 no reader indexes USAGE.taskMeta or USAGE.phaseTitles without "
          "guarding the container first",
          "USAGE.taskMeta[" not in M.UI_HTML
          and "USAGE.phaseTitles[" not in M.UI_HTML
          and "(USAGE.taskMeta||{})[" in M.UI_HTML
          and "(USAGE.phaseTitles||{})[" in M.UI_HTML)

    check("hg1 the guide card's tool badge reads the payload's own readOnly "
          "verdict, and the fixed claim it used to print is gone",
          "hToolClaim(a.readOnly)+(a.tools||[]).join(' · ')" in M.UI_HTML
          and "'read-only: '+(a.tools" not in M.UI_HTML
          and "if(readOnly===true)return 'read-only: ';" in M.UI_HTML
          and "if(readOnly===false)return 'NOT read-only: ';" in M.UI_HTML)

    check("beforeunload interrupts a close when there is something to lose OR "
          "when the panel cannot tell whether there is",
          "addEventListener('beforeunload',ev=>{" in M.UI_HTML
          and "if(!Object.keys(EDITS).some(surfaceDirty))return;" in M.UI_HTML
          and "function surfaceDirty(k){const r=editRows(k);return r===null"
              "||r.length>0;}" in M.UI_HTML)
    check("a re-render does not stack up one more delegated listener per save",
          "if(VIEWAC[id])VIEWAC[id].abort();" in M.UI_HTML
          and M.UI_HTML.count("onViewEdit('") == 2)
    # --- handing the caret back: one rule, every dialog and every redraw ------
    # A <dialog> restores the NODE that was focused at showModal(). Every view
    # here is rebuilt wholesale by its render*, so after a rebuild that node is
    # detached and the platform's restore lands on nothing - the reader is left
    # on <body>, and the next Tab starts at the top of the document.
    check("every dialog opens through ONE opener, so a fifth cannot be added "
          "that quietly skips the hand-back",
          # Counted, not merely found: `in` would still pass with four dialogs
          # calling showModal() directly and one going through the opener.
          M.UI_HTML.count(".showModal();") == 1
          and M.UI_HTML.count("dlgOpen(") == 5          # one def, four dialogs
          and "function dlgOpen(d,sel){" in M.UI_HTML
          and "const r=DLGBACK.get(d);DLGBACK.set(d,null);focusBack(r);});"
          in M.UI_HTML)
    check("the caret is remembered as a node AND as a selector - the node is "
          "right whenever it survived, the selector is what a rebuilt view has",
          "return {node:a,sel:s?((within?within+' ':'')+s):null,at:at};}"
          in M.UI_HTML
          and "let n=(ref.node&&ref.node.isConnected)?ref.node:null;" in M.UI_HTML
          and "if(!n&&ref.sel){const m=document.querySelectorAll(ref.sel);"
          in M.UI_HTML)
    # ...and WHERE in the box, which is the half renderPolicy, renderOver and
    # renderAppearance each grew their own id+selectionStart special case for.
    # Carried in the shared layer now, which is why renderSettings and renderComp
    # need none: measured with the caret at offset 1 of #compq, one
    # refreshFromDisk, offset 1 afterwards (it was 0, and unfocused, before).
    check("the caret's OFFSET is remembered too, and asked for inside the try - "
          "selectionStart THROWS on number/date/colour inputs rather than "
          "returning null, so reading it outside would kill the hand-back for "
          "every view that holds one",
          "try{at=a.selectionStart==null?null:[a.selectionStart,a.selectionEnd];}"
          in M.UI_HTML
          and "catch(e){at=null;}" in M.UI_HTML
          and "if(ref.at&&n.setSelectionRange)try{n.setSelectionRange("
              "ref.at[0],ref.at[1]);}catch(e){}" in M.UI_HTML)
    # The silent pass this replaces: `n.focus();return true;`. A DISABLED control
    # accepts .focus() without complaint and leaves the caret on <body>, which is
    # exactly what the rebuilt Discard buttons do - they are disabled the moment
    # the discard succeeds. Measured on all three savebars: the selector resolved
    # to 1 match, focus() was called, activeElement was <body>, and the old code
    # returned true. The claim now costs a question to the document.
    check("a hand-back reports what the DOCUMENT says, not what .focus() was "
          "asked to do - a disabled control takes the call in silence",
          "return document.activeElement===n;}" in M.UI_HTML
          and "n.focus();return true;}" not in M.UI_HTML)
    check("a hook that names several controls restores NOTHING rather than "
          "guessing - focus put somewhere the reader has never been looks "
          "deliberate, which is worse than the top of the document",
          "n=m.length===1?m[0]:null;" in M.UI_HTML)
    check("a free-text hook value stays out of the selector - the ⓘ carries a "
          "whole help sentence in data-tip and its first apostrophe would be a "
          "syntax error",
          "const selSafe=v=>v.length<=64&&!/[\"\\\\\\]]/.test(v);" in M.UI_HTML
          and "(selSafe(a.value)?'=\"'+a.value+'\"':'')" in M.UI_HTML)
    # An id is not a selector until it is escaped, and this form's ids are DOTTED
    # config paths. Measured: #set-manifestPath and #set-planGate handed the caret
    # back, and every dotted id in the same form - which is most of it - restored
    # NOTHING, because '#set-usage.bands.highUSD' asks for an element with id
    # "set-usage" carrying two classes. focusBack refuses a selector that matches
    # none, so it failed the way it is designed to and said nothing.
    check("an id goes through CSS.escape before it becomes a selector - Settings "
          "names its fields after dotted config paths, where a raw '#'+id reads "
          "the dots as class combinators",
          "if(n.id)return '#'+CSS.escape(n.id);" in M.UI_HTML
          and "'#'+n.id;" not in M.UI_HTML)
    # The second-direction case (this fix is a conditional, so it has two wrong
    # implementations): never firing is the original bug, always firing is a
    # redraw of one view stealing the caret out of another. Scoping is what
    # stops that, and this is the case that goes red if the scope is dropped.
    check("a redraw hands the caret back only WITHIN the view it rebuilt, so "
          "one view's repaint cannot take it out of another",
          "if(!a||!a.closest||(within&&!a.closest(within)))return null;"
          in M.UI_HTML
          and M.UI_HTML.count("focusKeep(") == 7      # one def, six views
          and M.UI_HTML.count("focusBack(") == 8      # one def, dlgOpen, six views
          and "focusKeep('#policy')" in M.UI_HTML
          and "focusKeep('#usage')" in M.UI_HTML
          and "focusKeep('#over')" in M.UI_HTML
          and "focusKeep('#look')" in M.UI_HTML
          # The two the first pass left out. Every view that a render* rebuilds
          # wholesale is now in this list, and the count is what keeps a seventh
          # from being added without one.
          and "focusKeep('#guards')" in M.UI_HTML
          and "focusKeep('#comp')" in M.UI_HTML)
    # A savebar Save carried neither an id nor a data- hook, so focusSel could not
    # name it and the caret a confirm dialog gave back had nowhere to go across the
    # re-render that followed.
    #
    # THE COUNT THAT USED TO BE HERE IS GONE ON PURPOSE. It read
    # `count("'data-save':'") == 3`, which was the only thing in this suite
    # forbidding the five copy-pasted footers from becoming one helper: one helper
    # emitting five footers writes that literal ONCE, so the count would have gone
    # red for a change that made the page better. What the count was reaching for -
    # every footer's Save is nameable, and a new writable view cannot arrive
    # without one - cannot be said in source text at all once the emitter is
    # shared, so it is said in the browser instead:
    # `assertSavebarCensus` in tools/capture-screenshots.mjs enumerates the
    # rendered controls by LABEL and checks each one's hook. What stays here is the
    # half source text can still carry: each hook that ships today is present by
    # name.
    check("every savebar Save can be NAMED after its view is rebuilt - the "
          "measured hole was Save, not Discard: the caret came back to it at "
          "676ms and renderComp took it away again at 682ms",
          "'data-save':'guards'" in M.UI_HTML
          and "'data-save':'comp'" in M.UI_HTML
          and "'data-save':'ado'" in M.UI_HTML
          and "'data-psave':'1'" in M.UI_HTML
          and "'data-thsave':'1'" in M.UI_HTML)
    # #comp had no ids and no hooks at all, so the hand-back would have restored
    # nothing for the whole view. data-status alone will not do for the filter
    # buttons: inside #comp it also sits on every phase row, every task row and
    # every status pill, so focusSel's selector names hundreds and focusBack
    # correctly refuses to guess between them.
    check("the Composition toolbar and its two editable columns carry hooks the "
          "rebuilt view can be searched for, and the filter buttons carry one "
          "that data-status could not be",
          "id:'compq'" in M.UI_HTML
          and "'data-compneeds':'1'" in M.UI_HTML
          and "'data-compexpand':'1'" in M.UI_HTML
          and "'data-status':s,'data-compfilt':s" in M.UI_HTML
          and "'data-revmodel':ph.id||''" in M.UI_HTML
          and "'data-tmodel':t.id||''" in M.UI_HTML)
    check("the dialog is the platform's here too — focus trap, backdrop, Esc",
          "el('dialog',{class:'confirm'})" in M.UI_HTML
          # ...opened through the shared opener, never showModal() direct. The
          # bare "d.showModal()" this replaces went on passing after the change
          # because dlgOpen's own body satisfies it - a pin that survives by
          # matching somewhere else is a pin that has stopped saying anything.
          and "cancel,go));\n  dlgOpen(d);" in M.UI_HTML
          and "if(ev.target===CFDLG)CFDLG.close()" in M.UI_HTML
          and "dialog.confirm::backdrop" in M.UI_HTML)
    check("a destructive primary is not one Enter away from the button that opened "
          "the dialog",
          "(o.danger?cancel:go).focus();" in M.UI_HTML)
    check("absent, empty list and empty text are three values, and the dialog says "
          "which — collapsing them made a real change read as 'not set -> not set'",
          "?'(empty list)'" in M.UI_HTML and "?'(empty text)'" in M.UI_HTML
          and "none?'not set'" in M.UI_HTML)
    check("the change rows the dialog lists are the shape the server echoes",
          "const cfRow=(target,field,from,to)=>({target,field,"
          "from:cfNorm(from),to:cfNorm(to)});" in M.UI_HTML
          and "function compChanges(patch)" in M.UI_HTML
          and "function configChanges(cfg)" in M.UI_HTML)
    check("what came back is compared with what was shown, not merely trusted",
          "function appliedDiff(rows,res)" in M.UI_HTML
          and "res.applied.map(key)" in M.UI_HTML
          and "'data-cfdiff':'1'" in M.UI_HTML)
    check("the save toast says how many landed and whether it was recorded",
          "'Saved · '+n+' change'+(n===1?'':'s')+log" in M.UI_HTML
          # "not logged" only when a journal exists and refused: reporting the
          # absence of a feature as a failed save would cry wolf on every write.
          and "res.journaledWhy==='failed'?' · NOT logged':''" in M.UI_HTML)
    check("a save re-reads from disk afterwards, and the filter survives it",
          "STATE=await api('GET','/api/state');renderComp();renderOver();" in M.UI_HTML)
    check("an unparseable buildCommands box cannot be confirmed as something else",
          "if(bcBad){toast('meta.buildCommands is not valid JSON" in M.UI_HTML)
    # Same retirement as the Save hooks above, and the same reason: the two counts
    # here (`'data-discard':'` == 4 and `offState(discard,!n);` == 3) required four
    # footers to stay four. The per-view names are what survives in source; "every
    # writable view offers a way back, and the control is dead while there is
    # nothing to throw away" is checked against the rendered page by
    # `assertSavebarCensus`, which also carries the ONE exemption by name: the
    # theme card has a Save and no Discard, because it offers an undo trail
    # instead. That asymmetry is why the retired counts read 4 against 5.
    check("Discard exists on every writable surface, counts what it would throw "
          "away, and is dead while there is nothing to throw",
          "'data-discard':'guards'" in M.UI_HTML
          and "'data-discard':'comp'" in M.UI_HTML
          and "'data-discard':'ado'" in M.UI_HTML
          and "'data-discard':'policy'" in M.UI_HTML
          and "offState(discard," in M.UI_HTML
          and "offState(discard,!pending.length);" in M.UI_HTML)

    # --- WCAG 2.2 SC 1.4.11 Non-text Contrast: the exemption, by name -----------
    # The five normative exceptions are NOT interchangeable and this register uses
    # the same vocabulary as the 2.5.8 one below, deliberately: a reader who has
    # learned one should not have to learn a second grammar for the other.
    _NTC_EXCEPTIONS = ("inactive", "decoration", "invisible", "user-agent",
                       "essential")
    _ntc_name = "user-agent"
    _ntc_note = ("non-text-contrast: input[type=checkbox] - exception=%s"
                 % _ntc_name)
    check("ntc1 the checkbox's 1.4.11 exemption is claimed by a NAME from the "
          "five, and the name is spelled where the rule is",
          _ntc_name in _NTC_EXCEPTIONS and _ntc_note in M.UI_HTML)
    # The exception is "appearance determined by the user agent and NOT MODIFIED
    # by the author". That is a claim about this stylesheet, so it is checked
    # against this stylesheet rather than believed: a rule that sets the box's
    # own geometry or swaps its appearance would forfeit it silently.
    _ntc_sheet = re.search(r"<style>([\s\S]*?)</style>", M.UI_HTML).group(1)
    _ntc_bad = [d for d in re.findall(r"[^{}]*checkbox[^{}]*\{([^{}]*)\}",
                                      _ntc_sheet)
                if re.search(r"(^|;)\s*(appearance|width|height)\s*:", d)]
    check("ntc2 ...and the claim still holds: no rule naming a checkbox sets its "
          "appearance, width or height, which is what the exception rests on: %r"
          % (_ntc_bad,),
          not _ntc_bad)

    # --- F16: unavailable must not mean unreachable (WCAG 2.2 SC 2.4.3) ---------
    # `disabled` takes the control OUT of the tab order and accepts .focus() in
    # silence, so after a successful Discard the caret stayed on <body> and the
    # next Tab restarted from the top of the document. WAI-ARIA APG uses
    # aria-disabled for exactly this case: the control keeps its tab stop and its
    # accessible name and refuses the activation instead. The cost is one extra
    # tab stop per savebar, which is the point rather than a side effect.
    check("f16a no Discard reaches for the disabled ATTRIBUTE — that is the whole "
          "defect, and a single one left behind reintroduces it",
          "discard.disabled" not in M.UI_HTML)
    check("f16b offState writes the attribute in BOTH directions — a control that "
          "goes unavailable and never comes back is the same bug in a hat",
          "function offState(n,off){" in M.UI_HTML
          and "n.setAttribute('aria-disabled',off?'true':'false');" in M.UI_HTML)
    # The half a static file can still get wrong: aria-disabled is a PROMISE to
    # assistive technology and the platform enforces none of it — unlike `disabled`
    # the browser still dispatches the click. One capture-phase guard keeps the
    # promise for every control that makes it, including ones added later, rather
    # than leaving each handler to re-check a condition it already checked.
    check("f16c one capture-phase guard refuses activation for anything claiming "
          "aria-disabled, rather than trusting four handlers to agree",
          "closest('[aria-disabled=\"true\"]')" in M.UI_HTML
          and "},true);" in M.UI_HTML)
    check("f16d the unavailable state is DRAWN, not only announced — aria-disabled "
          "carries no user-agent styling the way :disabled does",
          '[aria-disabled="true"]{opacity:' in M.UI_HTML)
    check("Usage: my-spend filters on the very string the topbar shows",
          "const me=((STATE||{}).viewer||{}).author;" in M.UI_HTML
          and "onclick:()=>setF('author',on?'':me)},'my spend')" in M.UI_HTML
          and "'data-umine':'1'" in M.UI_HTML)
    check("a field must not write into the form merely by rendering — that is an "
          "unsaved change nobody made",
          "const cur=()=>{const v=getPath(cfg,'guardEdits.customRules');" in M.UI_HTML
          and "setPath(cfg,'guardEdits.customRules',[])" not in M.UI_HTML)

    check("overview: the phase row says what the phase is FOR, not only what it "
          "is called",
          "p.desiredOutcome?el('span',{class:'ovout'" in M.UI_HTML
          and ".ovout{" in M.UI_HTML)
    check("overview: sort and group-by-area consume the rollup's own areas registry",
          "['plan','plan order'],['progress','progress'],['status','status']" in M.UI_HTML
          and "OVF.byArea=cb.checked" in M.UI_HTML and "r.areas[tag]" in M.UI_HTML)
    check("overview: an empty result says so and offers the way back",
          "No phase matches this filter." in M.UI_HTML
          and "'data-ovclear':'1'" in M.UI_HTML)
    check("overview: ready-now hands over the command, with a fallback when the "
          "clipboard refuses",
          "const cmd='/audit:run '+id;" in M.UI_HTML and "function ovCopy" in M.UI_HTML
          and "document.execCommand('copy')" in M.UI_HTML
          and "could not copy — the command is " in M.UI_HTML)

    # _bugs_view: the bug rows behind the strip. Every derived field is decided in
    # Python by the SAME functions the rollup counts with — pinned in
    # _panel_state.py (P12.3). What stays here is the other half of that claim:
    # the browser being handed the verdicts rather than deriving its own.
    check("the browser is handed those verdicts rather than re-deriving them",
          "b.open&&b.high" in M.UI_HTML and "STATE.bugs" in M.UI_HTML
          and "severity" not in M.UI_HTML[M.UI_HTML.index("const rows=bugs.filter"):
                                        M.UI_HTML.index("const rows=bugs.filter") + 120])

    # --- usage tab ---------------------------------------------------------
    check("usage tab is registered and has a view container",
          "data-t=usage" in M.UI_HTML and "<div id=usage" in M.UI_HTML
          and "'usage'" in M.UI_HTML)
    # The rate basis behind every dollar in this tab. It reads the DECLARED flag,
    # never `pricingAsOf` alone: usage_cfg() merges defaults, so that value is set
    # even for a project that never chose it, and printing it unconditionally would
    # present the default table's date as the project's own.
    check("the usage tab names the rate table behind its costs",
          "rates as of '+USAGE.pricingAsOf" in M.UI_HTML
          and "'rates undated: date them in Settings','usage.pricingAsOf'" in M.UI_HTML)
    check("and it decides on pricingAsOfDeclared, not on the merged value, so a "
          "default date is never shown as the project's own",
          "USAGE.pricingAsOfDeclared" in M.UI_HTML)
    check("withheld with the dollars when showCost is off",
          "if(USAGE.showCost&&USAGE.pricingAsOfDeclared)bits.push" in M.UI_HTML
          and "if(USAGE.showCost&&!USAGE.pricingAsOfDeclared)ctx.append" in M.UI_HTML)
    # Every one of these used to end with an instruction to go and edit a JSON file
    # by hand - printed on the surface whose whole job is editing that file.
    check("no notice in Usage tells you to set a config value without taking you "
          "to it",
          "function gotoSetting(" in M.UI_HTML
          and "function settingsLink(" in M.UI_HTML
          and M.UI_HTML.count("settingsLink(") >= 5
          and ".claude/audit.config.json)" not in M.UI_HTML
          and "Set usage.bands.highUSD/outlierUSD" not in M.UI_HTML)
    check("and arriving there says which field you were sent to, rather than "
          "scrolling somewhere silently",
          "t.classList.add('flash')" in M.UI_HTML and ".flash{outline:" in M.UI_HTML)

    # --- c7: the policy switchboard ------------------------------------------
    # String pins, and they cannot tell a working panel from a dead one — the
    # inline script is one <script>, so a missing paren kills every view while
    # every `'…' in UI_HTML` here still passes. The behaviour is driven for real
    # in tools/capture-screenshots.mjs (assertPolicyWorks), against a fixture with
    # its own HOME; these guard the constructs those checks depend on.
    check("the policy tab is registered, routable and has a view container",
          "data-t=policy>Policy<" in M.UI_HTML and "<div id=policy" in M.UI_HTML
          and "const TABS=['guards','comp','over','usage','policy','look']"
          in M.UI_HTML)
    # --- th (F-P-6): Appearance ------------------------------------------------
    # The panel and the report share ONE token layer, and every value in it is a
    # custom property — so "change the look" is "change those values", and the
    # server compiles them by substitution (see _ui_theme's th1: the default
    # theme compiles back to the shipped stylesheet byte for byte). What the
    # browser checks drive is in capture-screenshots --check; these pin the
    # constructs those behaviours rest on.
    check("th-p1 Appearance is a tab of its own, routable, with a container - "
          "Settings is paths and the gate, and a look is neither",
          "data-t=look>Appearance<" in M.UI_HTML and "<div id=look" in M.UI_HTML
          and "function renderAppearance(" in M.UI_HTML)

    check("th-p3 the editor reads the vocabulary and the DEFAULT from the "
          "server - a second copy of the default in the browser is how 'what "
          "did I change' starts disagreeing with itself",
          "GET','/api/theme'" in M.UI_HTML
          and "THEME.default" in M.UI_HTML and "function tChanges(" in M.UI_HTML)
    check("th-p4 the preview is the panel itself: the draft is written onto "
          ":root and cleared token by token, so a revert leaves nothing behind",
          "function tPaint(" in M.UI_HTML
          and "root.style.setProperty(c.token" in M.UI_HTML
          and "TPAINTED.forEach(n=>root.style.removeProperty(n));" in M.UI_HTML)
    check("th-p5 saving goes through the same confirm-and-echo path every other "
          "write here uses, and says what file it writes",
          "confirmChanges({title:'Save theme'" in M.UI_HTML
          and "PUT','/api/theme'" in M.UI_HTML
          and "writes .claude/audit.theme.json" in M.UI_HTML)
    check("th-p6 the chart palette opens deliberately - locked by default, "
          "unlocked by a named press, and the contrast/CVD argument is stated "
          "where the press is",
          "data-thunlock" in M.UI_HTML
          and "colour-vision deficiency" in M.UI_HTML
          and "TUNLOCK" in M.UI_HTML)
    check("th-p7 three ways back, and they are different things: revert one "
          "row, undo one step, reset the whole file",
          "data-threvert" in M.UI_HTML and "data-thundo" in M.UI_HTML
          and "data-threset" in M.UI_HTML
          and "removes .claude/audit.theme.json" in M.UI_HTML)
    check("th-p9 density is ONE control over the spacing scale, previewed with "
          "the same arithmetic the compiler does - and the preview reads the "
          "UNSCALED values it captured once, or every keystroke would compound",
          "data-thdensity" in M.UI_HTML
          and "const TDENSITY={compact:0.8,comfortable:1,spacious:1.25};" in M.UI_HTML
          and "function tCaptureBase(" in M.UI_HTML
          and "TBASE[n]" in M.UI_HTML)
    check("th-p10 a view's card order is applied to what was DRAWN, and a card "
          "the theme never heard of keeps its place rather than vanishing",
          "function applyCardOrder(" in M.UI_HTML
          and "applyCardOrder('over');" in M.UI_HTML
          and "if(k&&want.indexOf(k)<0)host.append(n);" in M.UI_HTML)
    check("th-p11 every reorderable card is NAMED where it is built, so a "
          "renamed card renames its ordering key with it",
          M.UI_HTML.count("'data-card':'") >= 4
          and "'data-card':'phases'" in M.UI_HTML
          and "'data-card':'gate'" in M.UI_HTML)
    check("th-p12 switching theme is a one-key config edit, and Save as keeps a "
          "named copy AND wears it",
          "data-thpreset" in M.UI_HTML and "{use:sel.value}" in M.UI_HTML
          and "data-thsaveas" in M.UI_HTML and "saveAs:name.trim()" in M.UI_HTML)

    # THREE PLACES SAY HOW MUCH IS UNSAVED and they must read ONE function. The
    # pill in the head, the out-of-band repaint that keeps it current under a
    # drag, and the rows the save sends. Two of them have already drifted twice:
    # once when the repaint counted `tChanges()` while the render counted tokens
    # plus layout, and again when both counted the DEFAULT-relative set while the
    # word on screen said "unsaved". The values are driven in
    # tools/ui-tests/theme-surface.test.mjs and the pill is read from the live
    # page by capture-screenshots.mjs; this is the part those two cannot see -
    # that the three sites ask the SAME question.
    check("th-p13 the pill, the repaint and the save all count tChangeRows - "
          "one question, asked once",
          "const nch=tChangeRows().length;" in M.UI_HTML
          and "const n=tChangeRows().length;" in M.UI_HTML
          and "const rows=tChangeRows();" in M.UI_HTML
          # ...and the default-relative set is still what the CHANGES CARD shows,
          # which says so in its own header. Two meanings, both named.
          and "const changes=tChanges().concat(tLayChanges());" in M.UI_HTML
          and "this is the theme minus the default" in M.UI_HTML)

    check("th-p8 export hands over a FILE and import takes only JSON - the "
          "compiled .css goes one way, so no importer ever parses CSS",
          "data-thexport" in M.UI_HTML and "function tImport(" in M.UI_HTML
          and "accept:'.json,application/json'" in M.UI_HTML
          and "not JSON — a theme is exported as .json" in M.UI_HTML)
    check("the verdicts shown are the SERVER's — the browser is handed them and "
          "never matches a pattern itself, because two matchers eventually "
          "disagree about a denial",
          "POLICY.resolved" in M.UI_HTML and "r.verdict" in M.UI_HTML
          and "fnmatch" not in M.UI_HTML
          and "function pResolve" not in M.UI_HTML)
    check("...so an edited row is marked pending rather than re-judged, and the "
          "verdicts are re-read from the server after a save",
          "moved?el('span',{class:'badge pend'" in M.UI_HTML
          and "POLICY=await api('GET','/api/policy')" in M.UI_HTML)
    # EVERY assignment, not one of them. The first version of this pin asked
    # whether the string appeared at all — and it appears four times (boot, save,
    # discard, and v0.34's refreshFromDisk), so a mutation that pointed one of
    # them at the merged block left it green. A wholesale PUT built from defaults
    # would write every default into the file the first time anyone pressed Save.
    _pdraft = re.findall(r"PDRAFT=pClone\(([^)]*)\)", M.UI_HTML)
    check("the draft is the block AS WRITTEN, not the merged one - and that is "
          "true of every place the draft is set, not merely somewhere",
          _pdraft == ["POLICY&&POLICY.stored"] * 4
          and "pRuleOf(POLICY.stored,kind,r.name,tag)" in M.UI_HTML)
    # THE PIN THAT USED TO BE HERE ASSERTED A SPELLING, AND THE SPELLING DID NOT
    # DELIVER ITS OWN CLAIM. It read
    #   "for(const l of ['deny','allow'])if((src[l]||[]).indexOf(name)>=0)"
    # and its label promised "an EXACT name only". On a LIST that holds; on a
    # string it does not, because `indexOf` is then a substring search - a
    # hand-written `"deny": "nope"` made pRuleOf answer 'deny' for the capability
    # `op`, which is a rule reported for something nothing had denied, in the view
    # that decides whether a skill may run at all. The pin could not see it: it
    # checked the characters, not the behaviour, and the characters were exactly
    # what it wanted.
    #
    # The property is checked where it can be observed instead —
    # tools/ui-tests/policy-shape.test.mjs calls pRuleOf against a real list and
    # asserts that a name which is a PREFIX of a stored entry does not match, and
    # against a malformed one and asserts no rule is reported. Three of the four
    # walkers additionally THREW on that shape, and a throw inside renderPolicy
    # blanks the tab while every `'…' in UI_HTML` pin here keeps passing.
    #
    # What stays here is what source text can carry: the walkers exist and the
    # rows are addressable.
    check("the rule walkers are all present and the rows are addressable - the "
          "EXACT-match property itself is asserted by behaviour in "
          "tools/ui-tests/policy-shape.test.mjs, because a pin on the body "
          "claimed it and did not have it",
          "function pRuleOf(" in M.UI_HTML
          and "function pDraftRules(" in M.UI_HTML and "'data-prule'" in M.UI_HTML)
    check("...and neither walker reads a rule list without checking it IS a list "
          "- the two named helpers are the only way in, so a fifth walker cannot "
          "reintroduce the shape that blanked the tab",
          "const pList=(src,list)=>Array.isArray(src&&src[list])?src[list]:[];"
          in M.UI_HTML
          and "if(!Array.isArray(src[list]))src[list]=[];" in M.UI_HTML
          and "(src[l]||[]).indexOf(name)" not in M.UI_HTML)
    check("...and every pattern in the block is therefore listed and removable, "
          "with what the server says it matches today",
          "'not saved yet'" in M.UI_HTML and "'nothing installed matches it today'"
          in M.UI_HTML and "'data-poladd':'1'" in M.UI_HTML)
    check("a saved pattern the server marks dead gets its own .mut note near the "
          "rules (v0.38) - the verdict is rules[].dead, computed server-side "
          "beside the guard's matcher; capped like the composition hints, and "
          "silent while discovery saw nothing at all",
          "'data-pdead'" in M.UI_HTML
          and "matches nothing installed here" in M.UI_HTML
          and ".filter(r=>r.dead).slice(0,3)" in M.UI_HTML)
    check("audit's own components cannot be denied from here, and the row says why",
          "sel.disabled=true;" in M.UI_HTML
          and "required by audit — the panel refuses to write a policy denying it"
          in M.UI_HTML)
    check("every verdict carries the basis that makes it true, as the report's "
          "routing advice and the lock verdict do",
          "el('span',{class:'pbasis'},r.basis||'')" in M.UI_HTML
          and ".pbasis{" in M.UI_HTML)
    check("the page says whether anything is ENFORCING this, in four states, and "
          "never implies enforcement from a policy alone",
          M.UI_HTML.count("'data-pstate':'") == 4
          and "anthropics/claude-code#43772" in M.UI_HTML
          and "'data-pstate':'unproven'" in M.UI_HTML)
    check("the four limits are on the surface that most invites believing the "
          "opposite, and they are the ones SECURITY.md states",
          "What this cannot hold — four limits" in M.UI_HTML
          and "It denies the tool, not the knowledge." in M.UI_HTML
          and "Hooks cannot gate hooks." in M.UI_HTML
          and "not removable quietly" in M.UI_HTML)
    check("area columns come from the server's own view of them and say which are "
          "deciding anything today",
          "POLICY.areaInfo" in M.UI_HTML and "a.active?'live':'dormant'" in M.UI_HTML)
    check("emptying a list removes it, and the container with it - the same "
          "convention Settings writes the config with",
          "function pPrune(" in M.UI_HTML
          and "if(Array.isArray(k[l])&&!k[l].length)delete k[l];" in M.UI_HTML
          and "if(!Object.keys(k.areas).length)delete k.areas;" in M.UI_HTML)
    check("a save goes through the one confirm flow, writes through the one policy "
          "endpoint, and describes itself in the vocabulary the server echoes "
          "(four call sites: boot, PUT, the post-save re-read, refreshFromDisk)",
          "confirmChanges({title:'Save capability policy'" in M.UI_HTML
          and M.UI_HTML.count("'/api/policy'") == 4
          and "function policyChanges(){" in M.UI_HTML
          and "return configChanges(cfg);}" in M.UI_HTML)
    check("the box saying what a save did survives the redraw that follows it, "
          "instead of being wiped by the re-read it triggers",
          "PNOTE=[...findings.childNodes];" in M.UI_HTML
          and "if(PNOTE){findings.append(...PNOTE);PNOTE=null;}" in M.UI_HTML)
    check("the widest table this UI draws scrolls inside its own frame",
          ".poltblwrap{" in M.UI_HTML and "overflow:auto" in M.UI_HTML)
    # --- c8: the help drawer --------------------------------------------------
    # Same warning as c7's block, one release later: these are string pins over a
    # single inline script, and they cannot tell a working drawer from a dead
    # page. The drawer is DRIVEN in tools/capture-screenshots.mjs
    # (assertHelpDrawerWorks), every oracle computed from the /api/help payload
    # rather than from the drawer's own output; these guard the constructs those
    # checks stand on, and the server side they talk to.
    check("the drawer is a native <dialog>, for the focus trap, Esc, the backdrop "
          "and - the one that matters here - handing focus back to the field",
          "el('dialog',{class:'drawer'" in M.UI_HTML
          and "dialog.drawer{" in M.UI_HTML
          and "if(!d.open)dlgOpen(d);" in M.UI_HTML)
    check("the ⓘ that opens it is a real BUTTON. A focusable span inside a <label> "
          "is not interactive content, so pressing it also toggled the checkbox "
          "it was explaining, and a screen reader announced it as text",
          "el(ref?'button':'span',{class:'hint'" in M.UI_HTML
          and "h.type='button'" in M.UI_HTML)
    check("...and every Settings control gets one from the key it is already "
          "labelled with, rather than from a second list of which fields have help",
          "hint(tip,{path:key,doc:'config',label:text})" in M.UI_HTML)
    check("no path is resolved in the browser: `usage.pricing.opus.in` is a path "
          "into a DOCUMENT and the table is keyed by shapes, and exactly one thing "
          "knows the difference",
          "'/api/help?doc='" in M.UI_HTML
          and "normalise_path" not in M.UI_HTML
          and "'.<name>.'" not in M.UI_HTML
          and "function hNormalise" not in M.UI_HTML)

    # The point of extracting rather than restating, asserted where it would
    # actually be broken: not one word of a concept page is in this file. A
    # sentence copied here would render identically and be a second thing to keep
    # true — which is the bug `_help` exists to avoid, reappearing in its consumer.
    _typed = [t["id"] for t in _help.topics()
              if t["title"] in M.UI_HTML or t["summary"] in M.UI_HTML
              or any(p in M.UI_HTML for p in t["paragraphs"])]
    check("no concept page is retyped into the UI - the drawer renders what the "
          "payload serves, and there is nowhere else for it to come from: %r"
          % _typed, not _typed)
    check("a field's concept page is the one the PAYLOAD links it to",
          "e.topic" in M.UI_HTML and "x.id===e.topic" in M.UI_HTML)
    check("the guide card is drawn from the payload's agent and not at all when "
          "there is none - a hint offering an agent this install does not ship is "
          "a dead end", "const a=doc&&doc.agent;if(!a)return null;" in M.UI_HTML
          and "(a.tools||[]).join(' · ')" in M.UI_HTML)
    check("...and it names the agent rather than offering to spend one: the whole "
          "point of the zero-token half is that it is the default",
          "This panel will not start it for you" in M.UI_HTML
          and "'/api/task'" not in M.UI_HTML and "spawnAgent" not in M.UI_HTML)
    check("the index is reachable from the topbar, not only from a field",
          "id=helpbtn" in M.UI_HTML and "$('#helpbtn').onclick=()=>openHelpIndex()"
          in M.UI_HTML)
    check("a group heading that has a concept page opens it; the three that have "
          "none draw no hint at all",
          "grp.topic?{topic:grp.topic}:null" in M.UI_HTML
          and [g["id"] for g in M.SETTINGS_GROUPS if g.get("topic")]
          == ["paths", "journal"]
          and {g["topic"] for g in M.SETTINGS_GROUPS if g.get("topic")}
          <= {t["id"] for t in _help.topics()})
    check("the composition levers are explained through _help's own map from the "
          "panel's name for a lever to the manifest path that documents it",
          not [k for k in ("reviewSkill", "buildCommands", "taskModel",
                           "taskSkills", "phaseReviewModel")
               if ("{comp:'%s'" % k) not in M.UI_HTML]
          and "(doc.composition||{})[ref.comp]" in M.UI_HTML
          and set(M.COMPOSITION_HELP) == set(_help.COMPOSITION_PATHS))
    check("backticks are the topics' only markup, and an unbalanced pair renders "
          "verbatim rather than guessing which half was code",
          "if(parts.length%2===0)return [String(s)];" in M.UI_HTML)

    # UI_HTML carries the stylesheet AND the JS that writes inline styles, which
    # is where an undeclared token actually hides.
    _css = M.UI_HTML[M.UI_HTML.index("<style>"):M.UI_HTML.index("</style>")]
    _missing = M._undeclared_css_vars(M.UI_HTML)
    check("every var(--token) in the panel CSS is declared "
          "(an undeclared one paints transparent and logs nothing): %r" % _missing,
          _missing == [])
    _asym = M._theme_asymmetric_vars(_css)
    check("no colour token exists in only one theme (either direction): %r"
          % _asym, _asym == [])
    # Settings alone ships a <select>, an <input type=date> and four number
    # inputs; all six are painted by the UA from `color-scheme`, which no custom
    # property can reach. A theme that does not restate it renders our dark cards
    # with the OS's light spinners and menu.
    _nocs = M._themes_missing_color_scheme(_css)
    check("every explicit data-theme restates color-scheme, so the toggle moves "
          "the selects, spinners, date picker and scrollbars too: %r" % _nocs,
          _nocs == [])
    # This sheet is a non-raw Python string too. The report's copy of the filter
    # chip's tick shipped as `¹3<BEL>0` for want of a doubled backslash; this one
    # was written correctly, and neither suite could see that they differed.
    _esc = M._mangled_css_escapes(_css)
    check("no CSS escape was eaten by Python before the browser saw it: %r" % _esc,
          _esc == [])
    check("usage colours come from the same validated palette as the report",
          "--viz-1:#2a78d6" in M.UI_HTML and "--viz-1:#3987e5" in M.UI_HTML)
    # Two series in the same hue is the one failure a categorical palette cannot
    # survive, and it only appears past 8 entities — which is exactly where nobody
    # looks. `Math.min(i+1,8)` gave 40 authors ONE red between 33 of them. The
    # invariant (every drawn series a distinct slot) is asserted in-browser against
    # a 40-author fixture; these pin the construct that guarantees it.
    check("hues are never shared: slots go to the entities actually drawn, and "
          "the capped-index rule that collided is gone",
          "Math.min(i+1,8)" not in M.UI_HTML
          and "function uRanks" in M.UI_HTML
          and "while(free<=8&&used.has(free))free++;" in M.UI_HTML
          and "uSlots(F.author,plotted,'spend')" in M.UI_HTML)
    check("slot order is global spend rank, so a filter never repaints a survivor",
          "for(const f of USAGE.facts)t[f[field]]" in M.UI_HTML
          and "sort((a,b)=>t[b]-t[a]" in M.UI_HTML)
    # A model must wear one hue across BOTH surfaces, so the panel orders models by
    # the same key render-report.py's _model_slots does. Authors have no report
    # chart to agree with, so they order by spend — the useful priority when only
    # 8 of 40 can be coloured.
    check("models slot by name (matching the report), authors by spend",
          "uSlots(F.model,dim==='model'?plotted" in M.UI_HTML
          and "'name')" in M.UI_HTML
          and "uSlots(F.author,plotted,'spend')" in M.UI_HTML
          and "if(by==='name')" in M.UI_HTML)
    check("a tiny non-zero bar still paints (0.0% reads as no data)",
          "Math.max(v[0]?0.8:0,100*v[0]/peak)" in M.UI_HTML)
    # One number format, and it is easy to break one call site at a time: the label
    # reads 3.2M while the tooltip opening over it reads 3,230,000. Every raw
    # thousands-separated number in the panel must be a COUNTABLE — in the fact
    # tuple that is index 2 (msgs) — never a token magnitude at index 0.
    # The fact tuple is [ts,phase,task,model,author,agent,attr,tokens,cost,msgs],
    # and the aggregate tuple is [tokens,cost,msgs] — so a countable receiver ends
    # in `[2]` or names msgs outright. Anything else is a magnitude and must be
    # compact.
    _loc = re.findall(r"([\w.\[\]]+)\.toLocaleString\(\)", M.UI_HTML)
    _badloc = [x for x in _loc if not (x.endswith("[2]") or x.endswith("msgs"))]
    check("no token value is rendered with thousand separators "
          "(counts may be; magnitudes may not): %r"
          % (_badloc or "ok, %d countables" % len(_loc)),
          _badloc == [] and bool(_loc))
    # The middle term used to read `(n/l).toFixed(dp)+s`. It moved on purpose,
    # and the negative half is what stops it moving back: a bare toFixed breaks
    # an exact tie AWAY from zero where Python's "%.*f" breaks it to EVEN, so
    # 1250 tokens printed "1.3K" in this panel and "1.2K" in every Python
    # surface of the same number.
    check("tokens are compact at one decimal, two on hover, matching the report",
          "const uTok=(n,dp=1)=>" in M.UI_HTML
          and "uFixedHalfEven(n/l,dp)+s" in M.UI_HTML
          and "(n/l).toFixed(dp)" not in M.UI_HTML
          and "uTok(v[0],2)" in M.UI_HTML)
    # Named rather than banned: the SVG coordinates, bar widths and the browse
    # dialog's extra-precision share column pinned elsewhere in this file are
    # DRAWING decisions and still call toFixed directly. Only the three
    # formatters that claim to mirror _fmt.py owe Python's tie rule. What the
    # helper actually computes is compared against `_fmt.py` itself, on both
    # surfaces, in tools/ui-tests/half-even.test.mjs — a substring can only say
    # that the call is spelled right.
    check("the three _fmt.py mirrors round a tie the way Python does, and uTok "
          "truncates at ENTRY like int(n) - it used to truncate only on the "
          "sub-1000 path, so a fraction at or above a magnitude was divided in "
          "and disagreed with Python; the pin moved with the code because entry "
          "truncation covers every path rather than one",
          "function uFixedHalfEven(x,dp){" in M.UI_HTML
          and "'$'+uFixedHalfEven(x,2)" in M.UI_HTML
          and "uFixedHalfEven(x,0)+'%'" in M.UI_HTML
          and "const uTok=(n,dp=1)=>{n=Math.trunc(n||0);" in M.UI_HTML
          and "String(Math.round(n))" not in M.UI_HTML)

    # --- reversible tail + browse dialog -----------------------------------------
    # The collapse used to hang off `else if(limit>TOP)` — it only appeared once
    # you had paged to the end of the tail, which at 233 rows is thirty clicks
    # before the way back exists.
    check("the collapse is unconditional, not gated on the tail being exhausted",
          "else if(limit>TOP)" not in M.UI_HTML
          and "if(limit>TOP)ctl.push(" in M.UI_HTML
          and "'show top '+TOP+' only'" in M.UI_HTML)
    check("browse-all appears whenever the list folds, and states the full count",
          "if(g.length>TOP)ctl.push(" in M.UI_HTML
          and "'browse all '+g.length" in M.UI_HTML)
    check("the dialog is the platform's, so focus trap/backdrop/Esc are not ours",
          "el('dialog',{class:'browse'})" in M.UI_HTML
          # ...and the row click applies the filter BEFORE closing, which repaints
          # this tab - so the button that opened the dialog is already a different
          # node by the time it closes. The selector is what gets the caret back,
          # and the button carries the hook it names.
          and "dlgOpen(BROWSE,'#usage [data-browse=\"'+dim+'\"]');" in M.UI_HTML
          and "'data-browse':dim," in M.UI_HTML
          and "dialog.browse::backdrop" in M.UI_HTML
          and "ev.target===BROWSE" in M.UI_HTML)
    check("Esc closes the dialog without also dropping a filter",
          "if(document.querySelector('dialog[open]'))return;" in M.UI_HTML)
    check("the dialog reads the same filtered facts as the bars, and says so "
          "when the page is scoped",
          "openBrowse(dim,title,facts)" in M.UI_HTML
          and "'within: '+UORDER.map(" in M.UI_HTML)
    check("search reports what it hid; sort toggles direction on re-click",
          "shown.length+' of '+rows.length" in M.UI_HTML
          and "if(sort===key)desc=!desc;else{sort=key;desc=!!BNUM[key];}" in M.UI_HTML
          and "desc?'▼':'▲'" in M.UI_HTML)
    check("a dialog row applies the filter and closes; an active row clears it",
          "setF(dim,active?'':r.id);BROWSE.close();" in M.UI_HTML)
    # <input type=search> consumes the first Escape to clear itself, so the dialog
    # only closed on the second press and the key read as broken.
    check("one Escape closes the dialog even from inside the search field",
          "if(ev.key==='Escape'){ev.preventDefault();BROWSE.close();}" in M.UI_HTML)
    # Across 241 phases every share is below 1%, and uPct floors those to "<1%" —
    # a column of identical cells that sorts correctly and says nothing.
    check("the share column keeps digits instead of flooring to <1%",
          "r.share<1?r.share.toFixed(2):r.share.toFixed(1)" in M.UI_HTML)
    # replaceChildren() stringifies non-Nodes, so an absent optional child painted
    # the literal word "null" into the dialog. el() tolerates nulls; this does not.
    check("optional dialog children are filtered, never stringified",
          "].filter(Boolean));" in M.UI_HTML
          and "BROWSE.replaceChildren(...[head,within," in M.UI_HTML)
    check("columns follow the dimension: only tasks carry status and risk",
          "task:[['id','id'],['title','title'],['status','status'],['risk','risk']"
          in M.UI_HTML and "author:[['author','id']" in M.UI_HTML)
    # Two phases costing the same can be one opus run and one long haiku grind —
    # the aggregate cannot say which, so the mix is carried alongside it.
    check("phase/task/author rows carry a model mix; the model dimension does not",
          "['models','models']" in M.UI_HTML
          and M.UI_HTML.count("['models','models']") == 3
          and "model:[['model','id'],['tokens','tokens']" in M.UI_HTML)
    check("mix segments are emitted in slot order (validated adjacency), and the "
          "dominant model is named rather than left to colour",
          "(MSLOTS[a]||99)-(MSLOTS[b]||99)" in M.UI_HTML
          and "el('span',{class:'mdom'},r.dominant" in M.UI_HTML
          and "cell.title=r.models.map(" in M.UI_HTML)
    check("a mix has no natural order, so that column sorts by dominant model",
          "const k=sort==='models'?'dominant':sort;" in M.UI_HTML)

    check("no budget anywhere renders nothing at all",
          "if(!ids.length)return [];" in M.UI_HTML)
    check("the burn-down follows the filter, and says which rows it counted",
          "for(const f of facts){const p=f[F.phase]" in M.UI_HTML
          and "Counting only the rows the filters above leave in view." in M.UI_HTML)
    check("the fill caps at the track while the number does not",
          "Math.min(100,r.pct).toFixed(1)" in M.UI_HTML
          and "r.pct.toFixed(0)+'%'" in M.UI_HTML)
    check("unbudgeted phases are counted, never drawn as a phase at zero",
          "are not listed - they are not " in M.UI_HTML
          and "phases at zero." in M.UI_HTML)

    check("the button opens through this origin with the token in the query "
          "string (window.open cannot set a header)",
          "const url=p=>p+'?t='+encodeURIComponent(TOKEN)" in M.UI_HTML
          and "win.location=url('/report')" in M.UI_HTML)
    # Opened during the click, navigated after the render returns. The other order
    # is a popup opened outside a user gesture, which Safari and a strict Firefox
    # block silently — leaving a button that reports success and does nothing.
    _rep = M.UI_HTML[M.UI_HTML.index("$('#report').onclick"):]
    _rep = _rep[:_rep.index("// tabs")]
    check("the window is opened inside the gesture, before the await, and a "
          "blocked popup still leaves a link",
          _rep.index("window.open('','_blank'") < _rep.index("await api('POST','/api/report'")
          and "id:'replink'" in _rep)
    check("a render that wrote no HTML says so instead of opening a 404",
          "if(!r.exists)" in _rep)

    # --- routing advice -----------------------------------------------------------
    # The only server-computed metric in the tab: the counterfactual re-prices the
    # per-tier token counts, which `facts` no longer carry.
    check("advice says it does NOT follow the filters, unlike everything else",
          "does not follow the filters above." in M.UI_HTML
          and "const adv=USAGE.routingAdvice||[];" in M.UI_HTML)
    check("the caveat travels with the number, not just in the docs",
          "An upper bound, not a forecast" in M.UI_HTML
          and "would not emit " in M.UI_HTML)
    check("no advice renders nothing at all",
          "if(adv.length){" in M.UI_HTML)

    # --- contrast pairs, substituted rather than restated -------------------------
    # The Appearance tab's live preview graded FOUR pairs while _ui_theme graded
    # six, and the two result lists are concatenated for the reader - so a draft
    # could report no warnings where the server reported two, in one list nobody
    # can attribute. The panel reads _ui_theme.CONTRAST_PAIRS now, substituted by
    # _panel_page.py the way __COST_BAND_PARAMS__ already was.
    #
    # Asserted against the module's OWN table rather than against six literals
    # written here: a pin that restated the pairs would be a third copy of them.
    _cp = _theme.CONTRAST_PAIRS
    check("cp1 every contrast pair _ui_theme declares reaches the page, and the "
          "placeholder is gone - %d pair(s)" % (len(_cp),),
          len(_cp) >= 5
          and "__CONTRAST_PAIRS__" not in M.UI_HTML
          and all(('"%s", "%s"' % (fg, bg)) in M.UI_HTML for fg, bg, _f in _cp))
    check("cp2 ...and the panel no longer carries a table of its own: the "
          "literal it used to open with is gone, so a fifth copy cannot hide "
          "behind a passing cp1",
          "const TPAIRS=[['--text','--bg'" not in M.UI_HTML
          and "const TPAIRS=[[" in M.UI_HTML)
    # The two the panel was blind to, by name. cp1 would pass if _ui_theme itself
    # lost them, and losing them is the regression that matters most: it is the
    # accessibility check quietly measuring less.
    check("cp3 the two pairs the panel used to miss are still in the table",
          any(fg == "--text" and bg == "--surface-2" for fg, bg, _f in _cp)
          and any(fg == "--muted" and bg == "--bg" for fg, bg, _f in _cp))

    # --- cost bands ---------------------------------------------------------------
    # cost_bands() and panel.js's uBandInfo() used to be held together only by a
    # comment ("Mirrors cost_bands() in usage_ledger.py") asserted present in the
    # page — a pin on PROSE, not on the numbers it described. usage_ledger.py now
    # owns ONE serializable constant (COST_BAND_PARAMS) that cost_bands() itself
    # reads from, panel-server.py serializes verbatim into the page as
    # __COST_BAND_PARAMS__, and panel.js reads back instead of restating. These
    # cases assert the placeholder and the injected value directly — a boundary
    # can now only drift if this file stops sourcing it from usage_ledger.py.
    _ulmod = _loader.load_script("usage_ledger.py",
                                 modname="audit_usage_ledger_check")
    _raw_tpl = _panel_ui.raw_template(cache=False)
    check("the cost-band-params placeholder appears exactly once in the raw "
          "template, before substitution",
          _raw_tpl.count("__COST_BAND_PARAMS__") == 1)
    check("panel.js reads the boundaries from the placeholder instead of "
          "restating the gate/percentiles as literals",
          "const COST_BAND_PARAMS=__COST_BAND_PARAMS__;" in _raw_tpl
          and "const BAND_GATE=COST_BAND_PARAMS.gate" in _raw_tpl
          and "pct(COST_BAND_PARAMS.percentileHigh)" in _raw_tpl
          and "pct(COST_BAND_PARAMS.percentileOutlier)" in _raw_tpl
          and "const BAND_GATE=5" not in _raw_tpl)
    check("the assembled UI_HTML carries usage_ledger's OWN COST_BAND_PARAMS "
          "(the module constant, not a copy) as the substituted JSON, and the "
          "placeholder is gone",
          "__COST_BAND_PARAMS__" not in M.UI_HTML
          and json.dumps(_ulmod.COST_BAND_PARAMS, sort_keys=True) in M.UI_HTML
          and list(_ulmod.BAND_ORDER) == ["typical", "high", "outlier"])
    # A task is an outlier relative to the PROJECT. Recalibrating per filter would
    # make one of any three tasks an outlier the moment you scoped to three.
    check("bands are computed from the whole ledger, never the filtered view",
          "for(const f of USAGE.facts){const t=f[F.task];" in M.UI_HTML
          and "uBandInfo()" in M.UI_HTML and "BANDS=null;" in M.UI_HTML)
    check("a malformed threshold pair falls back to the relative basis",
          "if(!(isFinite(hi)&&isFinite(ou)&&hi>0&&hi<=ou))" in M.UI_HTML)
    check("below the gate nothing is banded, and the dialog says what is missing",
          "return (BANDS={basis:null,sufficient:false,byTask:{},sample,gate:BAND_GATE})"
          in M.UI_HTML
          and "needs '+bi.gate+' completed tasks to calibrate" in M.UI_HTML)
    check("the thresholds themselves are printed, so the reader can check them",
          "typical ≤ '+uCost(bi.high)" in M.UI_HTML
          and "high ≤ '+uCost(bi.outlier)" in M.UI_HTML)
    check("the band is a labelled pill, never a bare status colour",
          "el('span',{class:'bandpill b-'+r.band},r.band)" in M.UI_HTML
          and ".bandpill{" in M.UI_HTML)
    check("only tasks carry a band — a phase is not the thing that was measured",
          "['cost band','band']" in M.UI_HTML
          and M.UI_HTML.count("['cost band','band']") == 1
          and "band:(dim==='task'?bandOf(k):null)" in M.UI_HTML)
    # A malformed 300-phase manifest emits a finding per phase, per task and per
    # indexed file — 1009 of them, previously joined into one paragraph that
    # filled the screen. They were four mistakes repeated, so the banner groups.
    check("findings group by shape with counts instead of one endless join",
          "function manifestFindingsBox" in M.UI_HTML
          and "function findingKind" in M.UI_HTML
          # a second findingsBox() would hoist over the save-result one
          and M.UI_HTML.count("function findingsBox") == 1
          and "el('span',{class:'fn'},g.n+'\\u00d7')" not in M.UI_HTML
          and "g.n+'×'" in M.UI_HTML
          and "'✗ '+r.findings+' finding(s): '" not in M.UI_HTML)
    check("a short finding list is still listed plainly, not force-grouped",
          "if(list.length<FGROUP_MIN)" in M.UI_HTML and "FGROUP_MIN=6" in M.UI_HTML)
    check("the raw list stays reachable and its own cap is stated",
          "every finding, unfolded" in M.UI_HTML
          and "' more — run /audit:validate for the complete list'" in M.UI_HTML)
    check("usage filtering is client-side (no round-trip per change)",
          "function uFiltered" in M.UI_HTML and "renderUsage()" in M.UI_HTML)
    # 250 daily points across 680px is 2.7px per mark: eight series of that is
    # noise. Rolling up is only honest if the chart says it rolled up, so the
    # heading, the crumb, the tooltip footer and the aria-label all name the bin.
    check("a long span rolls up into natural bins instead of drawing spaghetti",
          "const MAXPTS=60, LADDER=[1,7,28,91,364]" in M.UI_HTML
          and "function uBin" in M.UI_HTML
          and "LADDER.find(s=>Math.ceil(span/s)<=MAXPTS)" in M.UI_HTML)
    check("the roll-up is stated everywhere the period is named, never silent",
          "'Tokens per '+per+' by '+dim" in M.UI_HTML
          and "Days are rolled up into " in M.UI_HTML
          and "'click to filter to this '" in M.UI_HTML
          and "BINNAME[sr.binSize]" in M.UI_HTML)
    check("a rolled-up bin is still one clickable filter (from..to), and the "
          "chip spells the range out",
          "const binKey=b=>b[0]===b[1]?b[0]:b[0]+'..'+b[1]" in M.UI_HTML
          and "const[a,b]=UF.day.split('..')" in M.UI_HTML
          and "UF.day.replace('..',' to ')" in M.UI_HTML)

    # --- usage C1: calendar-month bin + forced-bin control ------------------
    # A plain 30-day rung would be dead code (28 always wins first), so the 28
    # rung IS the calendar month: variable bins cut at month boundaries, which
    # binAt's [start,end] binary search already supports.
    check("c1: the 28 rung is a calendar month cut at month boundaries, not a "
          "28-day stride wearing the name",
          "function monthBins(days)" in M.UI_HTML
          and "28:'month'" in M.UI_HTML and "'4 weeks'" not in M.UI_HTML
          and "if(forced||bins.length<=MAXPTS)return{size:28,bins:bins}" in M.UI_HTML)
    check("c1: a forced-bin control exists (auto/day/week/month), shares uBin "
          "with the tile sparklines, and disables impossible options with the "
          "reason on the option itself",
          "'data-uf':'bin'" in M.UI_HTML
          and "bin:'auto'" in M.UI_HTML
          and "const forced={day:1,week:7,month:28}[UF.bin]" in M.UI_HTML
          and "'would draw '+pts[v]+' points; the chart caps at '+MAXPTS"
          in M.UI_HTML)
    check("c1: a forced bin the span has outgrown resets to auto rather than "
          "drawing a chart the select no longer offers, and clear-all resets "
          "it with everything else",
          "if(UF.bin!=='auto'&&pts[UF.bin]>MAXPTS)UF.bin='auto'" in M.UI_HTML
          and "UF.bin='auto';" in M.UI_HTML.split("function clearAll()")[1][:220])
    check("c1: the range presets offer the last 12 months",
          "['365','last 12 months']" in M.UI_HTML)

    # --- usage C2: the Monthly card -----------------------------------------
    # One computation site (usage_ledger.monthly_activity) feeds the report
    # table and the CLI; the card is the panel's surface. Ledger half follows
    # the filters (client-side), plan half is server-shipped and project-wide.
    check("c2: the monthly card recomputes its ledger half client-side from "
          "the filtered facts and ships its plan half from the server",
          "function uMonthly(facts)" in M.UI_HTML
          and "USAGE.monthlyPlan||{}" in M.UI_HTML
          and "Plan counts are project-wide - they do not follow the filters."
          in M.UI_HTML)
    check("c2: the month axis comes from the whole ledger plus the plan - so "
          "filtering cannot drop the row that was just clicked - and one "
          "ledger month renders no card",
          "new Set(USAGE.facts.map(f=>f[F.ts].slice(0,7)))" in M.UI_HTML
          and "if(allMonths.size<2)return[]" in M.UI_HTML)
    check("c2: clicking a month writes the existing day-range grammar, first "
          "of the month to its true end, toggling off on a second click",
          "k+'-01..'+end" in M.UI_HTML
          and "onclick:()=>setF('day',active?'':range)" in M.UI_HTML)

    # --- usage C4: the person header ----------------------------------------
    # NOT a new tab: UF.author already is the drill-down. The header is
    # recomputed from USAGE.facts on each render - zero new state.
    check("c4: a person header renders while an author filter is on, with "
          "zero new state",
          "function uPerson()" in M.UI_HTML
          and "if(!UF.author)return[]" in M.UI_HTML
          and "card.append(...uPerson())" in M.UI_HTML)
    check("c4: it is all-time and says so, while everything below follows "
          "the filters",
          "'All time, whole ledger - this header does not follow the filters; '"
          in M.UI_HTML)
    check("c4: the viewer's own header wears the my-spend badge, compared "
          "against the same STATE.viewer string the topbar and the chip use",
          "((STATE||{}).viewer||{}).author===who" in M.UI_HTML
          and "el('span',{class:'badge'},'my spend')" in M.UI_HTML)
    check("c4: the counts a browser check recomputes ride in attributes, so "
          "the check compares numbers, not prose",
          "'data-ptasks':String(tasks.size)" in M.UI_HTML
          and "'data-pphases':String(phases.size)" in M.UI_HTML
          and "'data-pmsgs':String(msgs)" in M.UI_HTML)
    check("c4: touched tasks are split by status through taskMeta",
          "'Their touched tasks: '+parts.join(' - ')+'.'" in M.UI_HTML)

    # --- usage c5: filters, trends, export ---------------------------------
    # Derived, not enumerated. A filter added to UF and forgotten in DIMS is a
    # filter `clear all` cannot clear and Esc cannot pop — it stays on for the rest
    # of the session with a chip beside it that does nothing. The two lists must be
    # the same set, so the test compares them rather than restating either.
    _uf_keys = set(re.findall(r"(\w+):''", re.search(
        r"const UF=\{(.*?)\};", M.UI_HTML, re.S).group(1)))
    _dims = set(re.findall(r"'(\w+)'", re.search(
        r"const DIMS=\[(.*?)\];", M.UI_HTML, re.S).group(1)))
    check("every filter in UF is in DIMS, so clear-all and Esc reach all of them "
          "(UF-only: %r, DIMS-only: %r)"
          % (sorted(_uf_keys - _dims), sorted(_dims - _uf_keys)),
          _uf_keys == _dims and len(_dims) >= 8)
    # The delta used to re-list model/author/phase/task inline. Adding agent, attr
    # and free text to uFiltered alone would have left the trend comparing the
    # whole prior month against a filtered current one, and labelling it "vs prior
    # 30d" while doing it.
    _dl = M.UI_HTML[M.UI_HTML.index("function uDelta("):
                  M.UI_HTML.index("// --- CSV export")]
    check("one predicate scopes both windows: uFiltered and uDelta share uMatch, "
          "and the delta re-lists no dimension of its own",
          "function uMatch(f){" in M.UI_HTML
          and "USAGE.facts.filter(uMatch)" in M.UI_HTML
          and "&&uMatch(f);" in _dl
          and "UF.model" not in _dl and "UF.author" not in _dl)
    check("free text reads titles, not only ids, so a word from the plan finds "
          "the work",
          "function uHay(f)" in M.UI_HTML
          and "(USAGE.phaseTitles||{})[f[F.phase]]" in M.UI_HTML
          and "((USAGE.taskMeta||{})[f[F.task]]||{}).title" in M.UI_HTML)
    # A ledger's last day, never today's: the panel's own demo ledger ends in May,
    # and a wall-clock anchor makes the default view of it compare two empty
    # windows and show no trend at all, forever.
    check("all-time still gets a trend, anchored on the ledger's last day",
          "const all=UF.range==='all',span=all?30:parseInt(UF.range,10)" in M.UI_HTML
          and "const anchor=all?days[days.length-1]" in M.UI_HTML
          and "label:'vs prior '+span+'d'" in M.UI_HTML)
    check("and it carries both date ranges, because a percentage against an "
          "unnamed period is not a measurement",
          "basis:(all?'the ledger" in M.UI_HTML
          and "') against '+prevCut+' to '+iso(dnum(cut)-1)" in M.UI_HTML
          and "'Trend is '+dl.label+': '+dl.basis" in M.UI_HTML)
    check("a share moves in POINTS, a magnitude in per cent",
          "attributed:(A.attributed==null||B.attributed==null)" in _dl
          and "?null:A.attributed-B.attributed" in _dl
          and "(o.pp?' pts':'%')" in M.UI_HTML)
    # Colour said "spending more is good" for four releases, on the one chip whose
    # job is to report a direction.
    check("direction is a glyph before it is a hue, and only the metric with a "
          "polarity is coloured",
          '.dl.up::before{content:"\\25b2\\a0"' in M.UI_HTML
          and '.dl.down::before{content:"\\25bc\\a0"' in M.UI_HTML
          and "(o.pol?(d>=0?' good':' bad'):'')" in M.UI_HTML
          and ".dl{" in M.UI_HTML
          and "color:var(--muted);background:var(--surface-2)}" in M.UI_HTML)
    check("a magnitude spark is drawn from zero with an area, a share is scaled "
          "to its own range with none",
          "function uSpark(vals,label,zero)" in M.UI_HTML
          and "zero?Math.min(0,Math.min(...v)):Math.min(...v)" in M.UI_HTML
          and "if(zero)svg.appendChild(svgEl('path',{class:'sa'" in M.UI_HTML
          and "uSpark(o.series,k+' per '+sp.period+', oldest to newest',!o.pp)"
          in M.UI_HTML)
    _spk = M.UI_HTML[M.UI_HTML.index("function uSpark("):
                   M.UI_HTML.index("// --- metrics,")]
    check("the spark is drawn 1:1 like the chart, not stretched to the tile "
          "(a scaled viewBox scales the strokes with it)",
          "const SPW=76,SPH=20" in M.UI_HTML
          and "width:SPW,height:SPH" in _spk
          and "preserveAspectRatio" not in _spk)
    check("a tile with no daily series says why instead of drawing a flat line",
          "no daily trend: a task" in M.UI_HTML
          and "title:o.why||'no daily series for this metric'" in M.UI_HTML)
    # A quiet day has no share to report. Plotting it as 0% draws a cliff to the
    # floor and calls it a collapse in attribution.
    check("an empty bucket is a gap in a share series, never a zero",
          "attributed:acc.map(v=>v[0]?100*(v[0]-v[3])/v[0]:null)" in M.UI_HTML
          and "const v=(vals||[]).filter(x=>x!=null);" in M.UI_HTML)
    # The from/to pair and a click on the chart write ONE filter, in one grammar,
    # with one chip and one way out.
    check("the date pair reads and writes the same UF.day grammar the chart does",
          "function uDayPair(){const[a,b]=(UF.day||'').split('..')" in M.UI_HTML
          and "setF('day',(a||b)?(a===b?a:a+'..'+b):'')" in M.UI_HTML)
    check("half a pair is completed from the ledger's own ends, not from today",
          "const a=from||C.from||'',b=to||C.to||''" in M.UI_HTML
          and "Date.now" not in M.UI_HTML[M.UI_HTML.index("function uSetDays"):
                                        M.UI_HTML.index("function uAgg")])
    _csv = M.UI_HTML[M.UI_HTML.index("function uCsvText("):
                   M.UI_HTML.index("// --- render ---")]
    check("the CSV ships raw numbers: a separator makes every sum over the "
          "column wrong, and silently",
          "toLocaleString" not in _csv
          and "f[F.cost].toFixed(6)" in _csv and "f[F.tokens]," in _csv)
    check("and quotes per RFC 4180, so a comma in a title does not shift a column",
          '/[",\\r\\n]/.test(s)' in _csv
          and "'\"'+s.replace(/\"/g,'\"\"')+'\"'" in _csv
          and "out.join('\\r\\n')" in _csv)
    check("the file names what it is — span, resolution and whether a filter was "
          "on — so it can still be trusted three weeks later",
          "'usage-'+(C.from||'start')+'_'+(C.to||'end')+'-'" in _csv
          and "(USAGE.rolled?'daily':'hourly')" in _csv
          and "(uAnyFilter()?'-filtered':'')+'.csv'" in _csv)
    check("the blob URL outlives the click, stated EXACTLY ONCE for the whole "
          "page - it used to be restated at every download site, and the four "
          "sites had drifted to three different delays with one revoking "
          "synchronously (got %d)"
          % (M.UI_HTML.count("URL.revokeObjectURL(url), 4000"),),
          M.UI_HTML.count("URL.revokeObjectURL") == 1
          and "setTimeout(() => URL.revokeObjectURL(url), 4000)" in M.UI_HTML)
    check("...and the export still says so when it cannot run, rather than being "
          "a button that does nothing",
          "toast('export failed: '+e,'err')" in _csv
          and "nothing to export" in _csv)
    check("the BOM is an escape, not an invisible character in the source",
          "'\\ufeff'+uCsvText(facts)" in _csv
          and "﻿" not in M.UI_HTML)
    # <input type=search> clears itself on Escape - the trap the browse dialog
    # already hit once. One key, one effect.
    check("Escape inside the search box drops the search and nothing else",
          "if(a&&a.id==='uq'){if(UF.q)setF('q','');return;}" in M.UI_HTML)
    check("and the box keeps focus and caret when the filter repaints the tab",
          "keepQ=!!(act&&act.id==='uq')" in M.UI_HTML
          and "if(keepQ){const n=$('#uq');" in M.UI_HTML
          and "n.setSelectionRange(caret,caret)" in M.UI_HTML)

    # --- usage D4: the area filter ------------------------------------------
    # The server ships `phaseAreas` with the facts (_panel_state pins its key
    # parity and derivation); the client joins row.phaseId -> tags per row, at
    # read time, so re-tagging a phase re-files its whole history. These pins
    # hold the strings; the behaviour — counts against an in-page recomputation,
    # the select's hiding rule — lives in capture-screenshots.mjs --check,
    # because a string pin cannot see a dead page.
    check("d4: rows join their phase's area tags through ONE helper - the "
          "match, the haystack and the select all share it",
          "function uAreas(f){const a=(USAGE.phaseAreas||{})[f[F.phase]];"
          in M.UI_HTML
          and "return a&&a.length?a:null;}" in M.UI_HTML)
    check("d4: the area filter matches ANY tag of a multi-tag phase, and "
          "'untagged' is the absence of tags, never a tag's equal",
          "&&(!UF.area||(UF.area==='untagged'?!uAreas(f)" in M.UI_HTML
          and ":(uAreas(f)||[]).includes(UF.area)))" in M.UI_HTML)
    check("d4: free text finds rows by area name - the haystack ends with the "
          "row's own tags",
          "(uAreas(f)||[]).join(' ')].join(' ').toLowerCase()" in M.UI_HTML)
    check("d4: the select hides when no tag reaches a row, and offers "
          "'untagged' exactly when untagged spend exists",
          "'data-uf':'area'" in M.UI_HTML
          and "if(tags.size){" in M.UI_HTML
          and "untagged?['untagged']:[]" in M.UI_HTML
          and "'all areas ('+vals.length+')'" in M.UI_HTML)

    # --- usage ow (v0.34 D3): the advisory area owner on the Usage tab -------
    # The server ships `areaOwners` {tag: owner} with the facts (_panel_state
    # pins its key parity and derivation). Two read-only surfaces consume it:
    # the person header's "owns:" line (a join of UF.author against the map's
    # VALUES) and a native title tooltip on the area select's options. String
    # pins here; the rendered truth lives in capture-screenshots.mjs --check.
    check("ow: the person header joins the author against areaOwners VALUES "
          "and renders an owns: line with a data-owns hook",
          "const owned=Object.entries(USAGE.areaOwners||{})" in M.UI_HTML
          and ".filter(([,o])=>o===who).map(([t])=>t).sort();" in M.UI_HTML
          and "'owns: '+owned.join(', ')" in M.UI_HTML
          and "'data-owns':owned.join(',')" in M.UI_HTML)
    check("ow: ...and says it is advisory in the line itself - a label, "
          "never an assignment",
          "(advisory - meta.areas owner, not an assignee)" in M.UI_HTML)
    check("ow: each area option carries its owner as a title tooltip, and "
          "an ownerless tag carries none",
          "const ow=(USAGE.areaOwners||{})[v];" in M.UI_HTML
          and "if(ow)o.title='owner: '+ow;" in M.UI_HTML)

    # --- F5: an empty usage view explains itself ---------------------------
    # The range presets count back from the wall clock, so on a ledger that
    # stopped in May every preset but 90 selects nothing. That is the normal end
    # state of a finished plan, and precisely when someone opens this tab to ask
    # what it cost — and "No rows match these filters" left them with metering
    # never ran as the only conclusion on offer.
    _emp = M.UI_HTML[M.UI_HTML.index("function uEmptyWhy()"):
                   M.UI_HTML.index("function uDayPair()")]
    check("an empty usage view names its reason in an attribute, not only in "
          "prose a reader (or a check) has to parse",
          "const why=uEmptyWhy();" in M.UI_HTML
          and "'data-uwhy':why.why" in M.UI_HTML)
    check("a preset window beginning after the ledger's last day says so, with "
          "both dates",
          "why:'range-after-ledger'" in _emp
          and "if(C.to&&C.to<cut)" in _emp
          and "'The last '+UF.range+' days begin '+cut+', and the ledger ends '"
          "+C.to" in _emp)
    check("and offers the view that does hold the data, beside the bare "
          "clear-filters rather than instead of it",
          "label:'Show all time',run:toAll" in _emp
          and "'data-ufix':why.fix.key" in M.UI_HTML
          and "'data-uclear':'1'" in M.UI_HTML)
    # Re-anchoring the presets on the ledger would empty nothing and lie instead:
    # a control whose label says "today" and whose behaviour means "whenever the
    # data stopped". The empty state is the fix; the arithmetic was never wrong.
    check("the presets still measure back from today — the explanation is the "
          "fix, not a silently re-anchored window",
          "if(UF.range!=='all'){const d=new Date(Date.now()-parseInt(UF.range,10)"
          "*864e5)" in M.UI_HTML)
    # An explanation computed by a second copy of "what matches" is an explanation
    # that can contradict the view it is explaining.
    check("the diagnosis re-runs uFiltered with one slot blanked instead of "
          "re-implementing the match",
          "const keep=UF[d];UF[d]=d==='range'?'all':'';" in _emp
          and "const n=uFiltered().length;UF[d]=keep;" in _emp
          and "for(const d of UORDER.concat(" in _emp)
    check("one filter doing the emptying is named, counted and liftable on its "
          "own — clear-all throws away the ones that were fine",
          "n+' row(s) match everything else.'" in _emp
          and "'Remove the '+fName(d)+' filter'" in _emp)
    check("and where no single filter explains it, the page says so rather than "
          "blaming one at random",
          "why:'combination'" in _emp
          and "is the combination that selects nothing." in _emp)
    check("`range` carries a human name and a human value like every other "
          "filter, so it can be named where it is blamed",
          "range:'time range'" in M.UI_HTML
          and ":d==='range'?(UF.range==='all'?'all time':'last '+UF.range+' days')"
          in M.UI_HTML)

    # --- F6: a share of nothing is undefined, not 100% ---------------------
    # `uCoverage` divided by `tot||1` — the `||1` written to dodge a divide by
    # zero — so an empty selection returned 100*(1-0)/1 and the `attributed` tile
    # reported PERFECT coverage of no rows at all, beside three honest zeros, on
    # the one tile of the four that is coloured by polarity. It was also a second
    # implementation of `usage_ledger.coverage()`, which has always returned a
    # sentinel for an empty ledger rather than a number — two copies of one
    # calculation disagreeing at the boundary neither was tested on.
    #
    # The guard is the rule, not the patch: `||1` on a denominator is legitimate
    # for a bar's WIDTH and a sparkline's RANGE (a scale is a drawing decision,
    # not a claim) and for `attempts`, where one attempt is the true default. In
    # any other position it manufactures an answer to a question that has none.
    _or1 = [l.strip() for l in M.UI_HTML.splitlines()
            if "||1" in l and not l.lstrip().startswith("//")
            and not re.search(r"peak|\(hi-lo\)|attempts", l)]
    check("no percentage divides by a `||1` denominator — offenders: %r" % _or1,
          not _or1)
    check("every printed share goes through one helper that returns null when "
          "there is nothing to take a share of",
          "const uShare=(part,whole)=>whole?100*part/whole:null;" in M.UI_HTML
          and "return {attributed:uShare(tot-un,tot),task:uShare(by['task']||0,tot)"
          in M.UI_HTML
          and "tipRow(null,'share',uPct(uShare(v[0],grand)))" in M.UI_HTML
          and "share:uShare(v[0],grand)" in M.UI_HTML
          and "pct:uShare(per[m],v[0])" in M.UI_HTML)
    check("and null prints as the same em dash a tile with no series draws, "
          "rather than as a number",
          "const uPct=x=>x==null?'—':" in M.UI_HTML
          and "tile('attributed',uPct(cov.attributed)" in M.UI_HTML)
    # A null reaching .toFixed throws, and in the browse dialog that is the whole
    # table gone — the share column and the model tooltip are its two readers.
    check("both readers of a share that can now be null say so instead of "
          "throwing on .toFixed",
          "key==='share'?(r.share==null?'—'" in M.UI_HTML
          and "m.model+'  '+uPct(m.pct)+'  '+uTok(m.tokens,2)" in M.UI_HTML)
    # The other direction of the same rule: a scale is not a claim, and nulling
    # one would blank every bar and every sparkline in the tab.
    check("a bar's width and a sparkline's range still floor their denominator, "
          "because a scale is a drawing decision and not a measurement",
          "const peak=Math.max(...head.map(x=>x[1][0]))||1;" in M.UI_HTML
          and "const rng=(hi-lo)||1;" in M.UI_HTML)

    # --- v0.34 C1 (cs): combo search over name+description+source -------------
    # String pins over one inline script, as ever: the behaviour (the footer
    # count recomputed in-page, description search on a controlled registry)
    # is driven in tools/capture-screenshots.mjs --check.
    check("cs: the combo filters on name, description AND source through one "
          "lazily built haystack per item (the uHay pattern)",
          "(it.name+' '+(it.description||'')+' '+(it.source||'')).toLowerCase()"
          in M.UI_HTML
          and "if(it.h===undefined)it.h=" in M.UI_HTML
          and "it.name.toLowerCase().includes(q)" not in M.UI_HTML)
    check("cs: the count is taken BEFORE the 60-item slice and the overflow "
          "footer says how much is unshown",
          "shown=all.slice(0,60);" in M.UI_HTML
          and "combo-more" in M.UI_HTML
          and "' more — keep typing'" in M.UI_HTML
          and "if(all.length>shown.length)" in M.UI_HTML)
    check("cs: the footer lives OUTSIDE the keyboard-nav array, so ArrowDown "
          "can never land on a row that cannot be chosen",
          "active=Math.min(active+1,shown.length-1)" in M.UI_HTML
          and "shown.push" not in M.UI_HTML)
    check("cs: the menu is position:fixed and re-placed on scroll, so the "
          "composition table's own frame cannot clip it at its bottom edge",
          ".combo-menu{position:fixed" in M.UI_HTML
          and "menu.__place=place;" in M.UI_HTML
          and "m.__place()" in M.UI_HTML)

    # --- F-P-3 (px): the capability table, expanded ---------------------------
    # Behaviour is driven in capture-screenshots --check (assertPolicyExpand):
    # same rows in both views, one filter, Esc gives the focus back. These pin
    # the constructs that make those properties structural rather than lucky.
    check("px: ONE builder feeds the Policy tab and its expanded dialog, so the "
          "two cannot list different capabilities",
          "function pCapTable(kind,rows,full){" in M.UI_HTML
          and "const cap=pCapTable(kind,rows,false);" in M.UI_HTML
          and "const cap=pCapTable(kind,rows,true);" in M.UI_HTML)
    check("px: the dialog lives on <body> and is refilled by every renderPolicy "
          "- the tab is rebuilt on each keystroke, and a dialog inside it would "
          "be destroyed mid-type",
          "document.body.append(POLFULL);" in M.UI_HTML
          and "function polFullFill(" in M.UI_HTML
          and " polFullFill();\n if(keepId){" in M.UI_HTML)
    check("px: Esc is handled on the dialog, not on its search box - a type=search "
          "eats the first Escape to clear itself (the browse dialog's trap), and "
          "the tab's copy of that box must not close anything",
          "POLFULL.addEventListener('keydown',ev=>{" in M.UI_HTML
          and "if(ev.key==='Escape'){ev.preventDefault();POLFULL.close();}});" in M.UI_HTML)
    # The bespoke close listener this replaces DID hand the caret back, and the
    # browser gate still went red about one run in nine. Measured over 20 opens
    # with the 5s disk poll live: focus reached the Expand button inside 50ms
    # every time, and the poll's redraw of this tab then took it away again on 9
    # of them. So the pin is on BOTH halves - the hand-back, and the redraw that
    # has to keep it - because only the pair is the fix.
    check("px: closing hands the caret back to the control that opened it, and "
          "the tab's own redraw keeps it there",
          "dlgOpen(POLFULL,'#policy [data-polexpand]');" in M.UI_HTML
          and "keepBack=keepId?null:focusKeep('#policy')," in M.UI_HTML
          and " polFullFill();\n if(keepId){" in M.UI_HTML
          and "}}}\n else focusBack(keepBack);\n if(scrolled){" in M.UI_HTML
          and "POLBACK" not in M.UI_HTML)
    check("px: the dialog IS the frame - the table inside drops the 34rem cap "
          "rather than scrolling a frame inside a frame",
          ".poltblwrap.full{max-height:none" in M.UI_HTML
          and "dialog.polfull{width:calc(100vw - 2rem);height:calc(100vh - 2rem)"
          in M.UI_HTML
          # ...and the layout mode is [open]-qualified, or the CLOSED dialog
          # outranks the UA's display:none and eats clicks on the tab below.
          and "dialog.polfull[open]{display:flex" in M.UI_HTML
          and "box-shadow:var(--shadow-md);display:flex" not in M.UI_HTML)

    # --- F-P-2 (uc): spend with no plan behind it is NAMED, and highlighted ---
    # "--" is the ledger's storage key for a row with no phase/task; it used to
    # reach the screen as those two characters (and, in the ranked list, as
    # "-- unattributed"), which reads as a missing value rather than as the
    # answer it is. The word comes from the shared LABELS map, so the panel, the
    # report and the CLI cannot drift apart again; the warn role says how much
    # of the bill has no plan behind it without turning into a gate.
    check("uc: the empty bucket's word comes from the shared label map, never "
          "spelled in the panel's own source",
          "const UNCAT='--';" in M.UI_HTML
          and "label(UNCAT)" in M.UI_HTML
          and "'-- unattributed'" not in M.UI_HTML
          and _theme.UNCATEGORIZED in M.UI_HTML)
    check("uc: every place a group key reaches the screen names it - the "
          "ranked lists, the browse table's id column, the chart legend, its "
          "crosshair tip and the filter chips",
          "const uKey=" in M.UI_HTML
          and "const isUncat=k=>k===UNCAT||k==='unattributed';" in M.UI_HTML
          and "const nm=isUncat(k)?label(UNCAT)" in M.UI_HTML          # ranked list
          and ":key==='id'?uKeyEl(r.id)" in M.UI_HTML                 # browse table
          and "}),uKey(e.key)))));" in M.UI_HTML                      # legend
          and "tipRow(uCol(e.key),uKey(e.key)" in M.UI_HTML           # crosshair
          and ":uKey(UF[d]);" in M.UI_HTML                            # filter chips
          and "el('option',{value:v},uKey(v))" in M.UI_HTML)          # the attr select
    check("uc: the label wears the warn role, as text and not as a badge",
          ".uncat{color:var(--warn)" in M.UI_HTML)
    # --- F-P-1 (co): the combo menu is ONE overlay on <body> ------------------
    # Reproduced in a real browser before the fix (repro numbers in the plan):
    # a filter on tr.phase:hover>td made the td the containing block of the
    # fixed menu inside it, so the menu jumped ~550px on hover and grew the
    # table frame's scroll box. The behaviour is driven in capture-screenshots
    # --check (assertComboOverlay); these pin the constructs it relies on.
    check("co: THE menu is one element appended to document.body (the #hinttip "
          "rule), claimed by the combo whose input has focus - no ancestor can "
          "trap, clip or restack it",
          "id:'combomenu'" in M.UI_HTML
          and "document.body.append(CMENU);" in M.UI_HTML
          and "if(CMOWNER&&CMOWNER!==me)CMOWNER.close();" in M.UI_HTML
          and "wrap.append(inp,menu);" not in M.UI_HTML)
    check("co: a re-render or a tab switch closes the menu explicitly, since "
          "tearing the view down no longer takes it along",
          "function closeCombo(" in M.UI_HTML
          and M.UI_HTML.count("closeCombo();") >= 5
          and "function showTab(t,push){\n if(!TABS.includes(t))t='guards';\n closeCombo();"
          in M.UI_HTML)
    check("co: a mousedown anywhere in the menu keeps the input's focus, so a "
          "scrollbar drag or a click on the footer no longer closes it (F-P-1d)",
          "CMENU.addEventListener('mousedown',e=>e.preventDefault());" in M.UI_HTML)
    check("co: a click on the still-focused input reopens a closed menu (F-P-1c)",
          "inp.addEventListener('click',()=>{if(!(CMOWNER===me&&comboOpen()))render();});"
          in M.UI_HTML)
    check("co: the disk refresh defers while a combo is open or a control in a "
          "CLEAN form is focused, exactly as it defers for an open dialog - FP "
          "stays put and the poll after the interaction lands it; a dirty form "
          "defers nothing, since the refresh never rebuilds it (F-P-1b)",
          "function interacting(" in M.UI_HTML
          and "if(comboOpen())return true;" in M.UI_HTML
          # The selector is DERIVED from dirtyViews, never typed here as a
          # second list - the two spellings disagreed about the ADO fold, and a
          # caret in a clean Composition field then froze the live view. Which
          # carets defer is driven for real in
          # tools/ui-tests/refresh-deferral.test.mjs; these keep the derivation.
          and "const views=dirtyViews();" in M.UI_HTML
          and "const v=a.closest(Object.keys(views).map(id=>'#'+id).join(','));"
              in M.UI_HTML
          # ...and ONLY there: a caret in Overview's or Usage's search box is a
          # filter, whose state the refresh preserves, so it defers nothing.
          and "return !!v&&!views[v.id];}" in M.UI_HTML
          and "&&!interacting()){FP=fp;refreshFromDisk();}" in M.UI_HTML)

    # --- v0.34 C2 (mc): the model combo, three sources -------------------------
    # The ledger-only listing and the collapse-safety of the review combo are
    # driven in capture-screenshots.mjs --check; these pin the constructs.
    check("mc: modelItems unions manifest, rates and ledger, with an honest "
          "description per source and _default skipped",
          "function modelItems(" in M.UI_HTML
          and "add(m,'manifest','used by '+bits.join(', '));" in M.UI_HTML
          and "' out per MTok');" in M.UI_HTML
          and "' tokens in this ledger'" in M.UI_HTML
          and "if(m==='_default')return;" in M.UI_HTML)
    check("mc: the union is cached and invalidated whenever STATE/USAGE are "
          "refetched, so a keystroke never re-scans 20000 facts",
          "return (MITEMS=[...out.values()]);" in M.UI_HTML
          and M.UI_HTML.count("MITEMS=null") >= 2)
    check("mc: the task model, the phase review model and the pricing add "
          "box all ride the combo",
          "comboWrap(model,modelItems," in M.UI_HTML
          and "comboWrap(rev,modelItems," in M.UI_HTML
          and "comboWrap(add,modelItems," in M.UI_HTML)
    check("mc: choosing from the menu writes the SAME patch the keystroke "
          "writes",
          "model.value=name;setModel(name);close();" in M.UI_HTML
          and "rev.value=name;setRev(name);close();" in M.UI_HTML)
    check("mc: the stopPropagation moved from the review input to its combo "
          "WRAPPER - a click on the menu must not collapse the phase row",
          "revCombo.onclick=e=>e.stopPropagation();" in M.UI_HTML
          and "rev.onclick=e=>e.stopPropagation();" not in M.UI_HTML)
    check("mc: the three-source near-miss hint is a .mut note, never a "
          "finding - the panel cannot know which spelling was intended, and "
          "the validator cannot see the ledger or the rate table at all",
          "function modelHints(" in M.UI_HTML
          and "class:'mut small','data-mdhint'" in M.UI_HTML)

    # --- v0.34 C3 (sv): the save-result card's lifecycle -----------------------
    # The card that never left: "✓ saved" used to sit in the findings slot for
    # the rest of the session, indistinguishable from a save that just landed.
    # The lifecycle (present -> gone after SAVE_NOTE_MS; error card closable)
    # is driven in capture-screenshots.mjs --check; these pin the constructs.
    check("sv: the success card dissolves after SAVE_NOTE_MS through an "
          "opacity TRANSITION, never a keyframe (the browser checks' settle() "
          "waits out getAnimations, and a keyframe would stall every shutter)",
          "const SAVE_NOTE_MS=5000;" in M.UI_HTML
          and "okd.classList.add('fadeout')" in M.UI_HTML
          and ".savenote .findings.ok{transition:opacity" in M.UI_HTML
          and "@keyframes fadeout" not in M.UI_HTML)
    check("sv: the timer belongs to the NODE, armed once at creation, so "
          "renderPolicy's PNOTE carry cannot re-arm it - plus a fallback "
          "removal for a card whose transition never fires (hidden tab)",
          M.UI_HTML.count("okd.classList.add('fadeout')") == 1
          and "setTimeout(()=>okd.remove(),600)" in M.UI_HTML)
    _fb = M.UI_HTML[M.UI_HTML.index("function findingsBox"):]
    _fb = _fb[:_fb.index("return box;}")]
    _fberr = _fb[_fb.index("res.findings&&res.findings.length"):
                 _fb.index("res.warnings&&res.warnings.length")]
    check("sv: the error card is a bold title + the findings body + a dismiss "
          "button, and carries NO timer of its own - a refusal must outlive "
          "a glance away",
          "'Save rejected — nothing was written'" in _fberr
          and "'Locked — nothing was written'" in _fberr
          and "'data-notex':'1'" in _fberr
          and "'aria-label':'dismiss'" in _fberr
          and "setTimeout" not in _fberr)
    _fbwarn = _fb[_fb.index("res.warnings&&res.warnings.length"):
                  _fb.index("if(res.ok")]
    check("sv: warnings persist - no timer and no dismiss machinery; the next "
          "Save/Discard's replaceChildren is what clears them",
          "findings warn" in _fbwarn and "setTimeout" not in _fbwarn)
    check("sv: the #toast banner keeps its 2600ms - the noToast budget and "
          "the 900ms content checks are calibrated against it",
          ".trim(),2600)" in M.UI_HTML)
    check("sv: a multi-finding card scrolls inside itself on a phone rather "
          "than owning the screen",
          "@media(max-width:34rem){.savenote .fbody{max-height" in M.UI_HTML)

    # --- v0.34 C4 (fp): usage-filter persistence --------------------------------
    # Reload/share-link/clearAll round trips are driven in
    # capture-screenshots.mjs --check; these pin the grammar and the wiring.
    check("fp: the hash grammar is '#/<tab>!k=v&...' - both hash READERS "
          "split on the FIRST '!', and the tab writer carries the fragment",
          M.UI_HTML.count(".split('!')[0]") == 2
          and "const uf=uFragment();const h='#/'+t+(uf?'!'+uf:'');" in M.UI_HTML)
    check("fp: the codec mirrors the report's keys where the two overlap "
          "(m/au/a, day as from/to) and encodes the same way",
          "const UFKEY={model:'m',author:'au',area:'a',phase:'ph',task:'tk',"
          "agent:'ag',attr:'at',q:'q'};" in M.UI_HTML
          and "put('from',p[0]);put('to',p[1]);" in M.UI_HTML
          and "parts.push(k+'='+encodeURIComponent(v))" in M.UI_HTML)
    check("fp: the store is keyed per PROJECT - filters describe one repo's "
          "plan, while the theme and the active tab stay global on purpose",
          "const UFSTORE='audit-panel-uf:'+PROJECT;" in M.UI_HTML)
    _boot = M.UI_HTML[M.UI_HTML.index("async function boot()"):]
    # The endpoint was `startRunPoll()` until the boot sequence moved inside
    # runContained and the bare calls became names in a list. It raised rather
    # than drifting, which is the good outcome for a slice endpoint - the window
    # is the same span of boot() either way, and a pin that silently resized
    # would have gone on passing about something else.
    _boot = _boot[:_boot.index("runContained([startRunPoll")]
    check("fp: restore runs in boot() BEFORE the first renderUsage - hash "
          "over storage over defaults",
          "uApplyFragment(h.slice(bang+1))" in _boot
          and "storageGet(UFSTORE)" in _boot
          and _boot.index("uApplyFragment") < _boot.index("renderUsage"))
    check("fp: clearAll clears the store AND the fragment INSIDE its own "
          "slice (the F-D1 lesson: a pin outside the function it vouches for "
          "vouches for nothing)",
          "storageDrop(UFSTORE)" in
          M.UI_HTML.split("function clearAll()")[1][:400]
          and "syncUFHash('')" in M.UI_HTML.split("function clearAll()")[1][:400])
    check("fp: empty filters take the fragment OFF (the report's syncHash "
          "rule), and the write-through lives in renderUsage so every "
          "mutation path persists",
          "else storageDrop(UFSTORE)" in M.UI_HTML
          and "persistUF();" in M.UI_HTML.split("function renderUsage()")[1][:250])
    _ufrag = M.UI_HTML[M.UI_HTML.index("function uFragment()"):]
    _ufrag = _ufrag[:_ufrag.index("function uApplyFragment")]
    check("fp: SHOWN depths are session furniture and never enter the codec",
          "SHOWN" not in _ufrag)

    _poll = M.UI_HTML[M.UI_HTML.index("async function pollRunStatus"):
                    M.UI_HTML.index("// ---------- Overview")]
    check("lv: a changed fingerprint hands off to refreshFromDisk, is "
          "DEFERRED while any dialog is open (FP stays put, so the next poll "
          "retries), and the first sight only seeds",
          "refreshFromDisk();" in _poll
          and "!document.querySelector('dialog[open]')" in _poll
          and "if(FP===null)FP=fp;" in _poll)
    check("lv: refreshFromDisk is defined OUTSIDE the D9 slice - the poll "
          "path still never touches renderSettings",
          "async function refreshFromDisk()" in M.UI_HTML
          and M.UI_HTML.index("async function refreshFromDisk()")
          > M.UI_HTML.index("// ---------- Overview"))
    _rfd = M.UI_HTML[M.UI_HTML.index("function staleNote("):M.UI_HTML.index("const OVF=")]
    check("lv: dirtiness is judged BEFORE the state swap and only clean views "
          "re-render - a dirty one keeps its edits and gets the persistent "
          "notice instead",
          "const dirty=dirtyViews();" in _rfd
          and "if(!dirty.guards)reRender('guards',renderSettings);"
              "else staleNote('guards');" in _rfd
          and "if(!dirty.comp)reRender('comp',renderComp);"
              "else staleNote('comp');" in _rfd
          and "else staleNote('policy');" in _rfd)
    check("lv: the findings-slot nodes are CARRIED across the refresh render "
          "(the PNOTE move) - an own save moves the stamp too, and the "
          "refresh must not eat the card whose 5s clock belongs to the node",
          "const keep=slot?[...slot.childNodes]:[];" in _rfd
          and "if(s2&&keep.length)s2.append(...keep);" in _rfd)
    check("lv: renderUsage and renderOver always re-render (UF and the caret "
          "restore already survive them), caches are dropped, and the scroll "
          "position is put back after the chart remounts",
          "renderOver();" in _rfd and "renderUsage();" in _rfd
          and "BANDS=null;MITEMS=null;" in _rfd
          and "const y=window.scrollY;" in _rfd
          and "requestAnimationFrame(()=>window.scrollTo(0,y));" in _rfd)
    check("lv: FP is seeded from the boot payload, so a fresh panel does not "
          "double-fetch on its first poll",
          "FP=(RUNSTATUS||{}).fingerprint||null;" in M.UI_HTML)
    check("lv: the stale notice is added once per view and names what Save "
          "and Discard will do about the moved file",
          "'data-stale':id" in M.UI_HTML
          and "slot.querySelector('[data-stale]')" in M.UI_HTML)

    # usage_state's own cases (facts, the roll-up cap, the declared rate basis)
    # moved to _panel_state.py (P12.3); everything above is the tab that reads it.

    # --- WCAG 2.2 SC 2.5.8 Target Size (Minimum): a census, not a wish list ------
    # 24 x 24 CSS px, or a named exception. The exceptions are five and they are
    # NOT interchangeable: Spacing (nothing else inside the target's 24px circle),
    # Equivalent (the same function reachable at full size elsewhere), Inline (a
    # target in a sentence, sized by the line-height of the prose), User agent (the
    # box is the browser's and the author did not touch it), Essential.
    #
    # The half that can fail on something nobody thought about is the CENSUS: every
    # interactive shape is read out of the assembled page itself, so adding
    # `el('button',{class:'zzz'})` grows a key this register does not have and ts1
    # goes red before anyone has measured anything. A hand-kept list of the ones
    # somebody remembered would pass forever.
    #
    # The NUMBERS are the browser's, never this file's - Playwright at 390px and
    # 1200px, all six tabs, all four dialogs, keeping the smallest instance of each
    # shape. A static file cannot compute a rendered box and does not pretend to.
    #
    # AND AT ALL THREE DENSITIES (F30, measured 2026-08-19). `--sp-*` are scaled by
    # `layout.density` - compact .8, comfortable 1.0, spacious 1.25 - and the
    # spacing migration keeps moving declarations onto that scale, so compact can
    # walk a control under the floor without a line of CSS changing. It does: NINE
    # shapes move, and `.btn.small` crossed - 24.0 to 22.3 - which is why it now
    # declares `min-width:24px` instead of clearing the floor by coincidence.
    #
    # The first pass at this measured the COUNT under 24px per density and read
    # 175 / 176 / 175, and concluded density changes nothing. It changes plenty:
    # an aggregate was stable while the shapes underneath it moved, and the one
    # that crossed was the +1. Compare per shape, or a total will hide the thing
    # it is made of. Proven to be three real readings rather than one page
    # measured thrice by reading `--sp-3` each round - 1rem / .8rem / 1.25rem.
    #
    # The reason it does not move is worth keeping: the shapes that are under 24
    # are under it by their GLYPH size (`.hint` is 1.02rem square, `.chip button`
    # 6.4x12), and their target comes from a `::after` overlay declared in px. A
    # `getBoundingClientRect()` on the element measures the glyph and not the
    # target - which is why a raw census of rects reads 175 "failures" that are
    # not failures, and why this register grades the MECHANISM instead.
    # What it checks instead is that the MECHANISM each non-conforming shape leans
    # on is still in the stylesheet, which is the part a later edit can quietly
    # remove: delete the ::after overlay or the min-width and ts2 names the shape.
    #
    #   ok                 measured >= 24x24; the evidence is the measurement
    #   hit                the glyph is under 24 and an ::after overlay carries the
    #                      target; the overlay rule must declare 24px both ways
    #   <prop>:<value>     reached through that declaration, which must still
    #                      resolve to >= 24 CSS px
    #   exception=<name>   one of the five, and the stylesheet must carry the
    #                      reason beside the rule so the next reader does not
    #                      re-open it
    _TS_EXCEPTIONS = ("spacing", "equivalent", "inline", "user-agent", "essential")
    _TARGET_SIZE = {
        # the three hand-styled glyph buttons: 24x24 hit area, glyph untouched
        "button": ("hit", ".chip button"),           # the x that drops a chip
        "button.hint": ("hit", ".hint"),             # the i that opens the drawer
        "button.notex": ("hit", ".savenote .notex"),  # the x on a save note
        # one dimension short, and the pixels go into space that was already there
        "button.bx": ("min-width:24px", ".bx"),
        "button.btn.small.uhmarrow": ("min-width:24px", ".uhmarrow"),
        "input.thpick": ("height:1.5rem", ".thpick"),
        "select.prule": ("min-height:24px", "select.prule"),
        "summary": ("min-height:24px", ":where(summary)"),
        # exceptions, argued in the stylesheet beside the rule
        "a.lnk": ("exception=inline", ".lnk"),
        "button.lnk": ("exception=inline", ".lnk"),
        "input[type=checkbox]": ("exception=user-agent", "input[type=checkbox]"),
        # measured >= 24x24 already
        "button.btn.primary": ("ok", "105.4x39.8"),
        # was ("ok", "25.6x29.2") - a measurement at ONE density, and its
        # horizontal padding is `--sp-1`, which density scales: 22.3 under
        # compact. The floor is declared now instead of being a coincidence.
        "button.btn.small": ("min-width:24px", ".btn.small"),
        "button.btn.small.push": ("ok", "56.8x29.2"),
        "button.chip.ghosted.optnone": ("ok", "86.7x29.4"),
        "button.dtopic": ("ok", "343x78.6"),
        "button.filt": ("ok", "47.6x29.2"),
        "button.ovpill": ("ok", "60.5x29.9"),
        "button.ovrow": ("ok", "301x147.2"),
        "button.subtab": ("ok", "72.3x30"),
        "button.tab": ("ok", "60.1x38.7"),
        "button.tab.on": ("ok", "62.2x38.7"),
        "button.uchip": ("ok", "157.5x28.4"),
        "input": ("ok", "104x29.9"),
        "input.thtext": ("ok", "176x27.8"),
        "input.usearch": ("ok", "205x29.9"),
        "input[type=date]": ("ok", "120.3x32"),
        "input[type=number]": ("ok", "96x28.3"),
        "input[type=search]": ("ok", "150.5x29.9"),
        "select": ("ok", "69x27"),
        "textarea": ("ok", "204x72"),
    }
    _TS_TAGS = ("button", "input", "select", "textarea", "summary", "a")

    def _ts_shapes(js, html):
        """Every interactive shape the page can paint, keyed tag.class.class."""
        seen, unpainted = {}, {}
        for _m in re.finditer(r"el\(([^,]{1,40}),\{", js):
            _tags = [t for t in _TS_TAGS if ("'" + t + "'") in _m.group(1)]
            if not _tags:
                continue
            _i, _depth, _j = _m.end() - 1, 0, _m.end() - 1
            while _j < len(js):
                if js[_j] == "{":
                    _depth += 1
                elif js[_j] == "}":
                    _depth -= 1
                    if _depth == 0:
                        break
                _j += 1
            _body = js[_i:_j]
            _cls = re.search(r"class:'([^']*)'", _body)
            _typ = re.search(r"type:'([^']*)'", _body)
            # Never laid out, so never a target: the theme file picker sits behind
            # a real button at display:none. Counted rather than dropped, so
            # losing the exclusion is visible.
            #
            # The download anchor used to land here too, via `download:` in an
            # `el()` call. It is built in `shared/download.js` now, with raw
            # `createElement` - because a shared part ships into the report as
            # well and the report has no `el()`. So this census, which reads
            # `el()` calls, cannot see it any more. Nothing is lost: it was in
            # the excluded bucket, never in `seen`, so no target-size verdict
            # ever depended on it.
            _where = unpainted if ("display:none" in _body
                                   or "download:" in _body) else seen
            for _t in _tags:
                if _cls:
                    _k = _t + "." + ".".join(_cls.group(1).split())
                elif _typ:
                    _k = _t + "[type=" + _typ.group(1) + "]"
                else:
                    _k = _t
                _where[_k] = _where.get(_k, 0) + 1
        for _m in re.finditer(r"<(button|input|select|textarea|summary|a)\b([^>]*)>",
                              html):
            _cls = re.search(r'class="?([A-Za-z0-9_ -]*)"?', _m.group(2))
            _k = _m.group(1) + ("." + ".".join(_cls.group(1).split()) if _cls else "")
            seen[_k] = seen.get(_k, 0) + 1
        return seen, unpainted

    _ts_script = re.search(r"<script>([\s\S]*?)</script>", M.UI_HTML)
    _ts_markup = re.sub(r"<(style|script)>[\s\S]*?</\1>", "", M.UI_HTML)
    _ts_seen, _ts_unpainted = _ts_shapes(
        _ts_script.group(1) if _ts_script else "", _ts_markup)
    # The vacuity guard, first: everything below narrows this set, and a set that
    # narrowed to nothing would report a page with no undersized control on it.
    check("ts0 the census reads the page rather than a list somebody kept up to "
          "date - %d shapes found, %d never painted (%r)"
          % (len(_ts_seen), len(_ts_unpainted), sorted(_ts_unpainted)),
          _ts_script is not None and len(_ts_seen) >= 25
          and sorted(_ts_unpainted) == ["input[type=file]"])
    _ts_missing = sorted([k for k in _ts_seen if k not in _TARGET_SIZE])
    _ts_stale = sorted([k for k in _TARGET_SIZE if k not in _ts_seen])
    check("ts1 every interactive shape the page can create carries a target-size "
          "verdict, and every verdict still has a shape - unlisted %r, stale %r"
          % (_ts_missing, _ts_stale),
          not _ts_missing and not _ts_stale)

    _ts_sheet = re.search(r"<style>([\s\S]*?)</style>", M.UI_HTML).group(1)
    _ts_bodies = re.findall(r"([^{}]+)\{([^{}]*)\}",
                            re.sub(r"/\*[\s\S]*?\*/", "", _ts_sheet))

    def _ts_decls(sel):
        """Every declaration block whose selector LIST names `sel` exactly."""
        return [" ".join(b.split()) for raw, b in _ts_bodies
                if sel in [p.strip() for p in " ".join(raw.split()).split(",")]]

    def _ts_px(v):
        """A length in CSS px, or None when it is not an absolute one."""
        _m = re.match(r"^([0-9.]+)(px|rem)$", v.strip())
        return None if not _m else float(_m.group(1)) * (16.0 if _m.group(2) == "rem"
                                                         else 1.0)

    _ts_bad = []
    for _k in sorted(_TARGET_SIZE):
        _verdict, _ev = _TARGET_SIZE[_k]
        if _verdict == "ok":
            _m = re.match(r"^([0-9.]+)x([0-9.]+)$", _ev)
            if not _m or float(_m.group(1)) < 24 or float(_m.group(2)) < 24:
                _ts_bad.append("%s: listed ok on a measurement of %r" % (_k, _ev))
        elif _verdict == "hit":
            if not [b for b in _ts_decls(_ev + "::after")
                    if "width:24px" in b and "height:24px" in b]:
                _ts_bad.append("%s: no %s::after rule declaring 24x24 - the glyph "
                               "is under 24 and nothing carries the target"
                               % (_k, _ev))
        elif _verdict.startswith("exception="):
            _name = _verdict.split("=", 1)[1]
            _note = "target-size: %s — exception=%s" % (_ev, _name)
            if _name not in _TS_EXCEPTIONS:
                _ts_bad.append("%s: %r is not one of the five SC 2.5.8 exceptions"
                               % (_k, _name))
            elif _note not in _ts_sheet:
                _ts_bad.append("%s: the stylesheet does not carry %r, so the next "
                               "reader has to re-open the question" % (_k, _note))
        else:
            _prop, _, _val = _verdict.partition(":")
            if (_ts_px(_val) or 0) < 24:
                _ts_bad.append("%s: %s does not reach 24 CSS px" % (_k, _verdict))
            elif not [b for b in _ts_decls(_ev)
                      if re.search(r"(^|;)\s*%s\s*:\s*%s\s*(;|$)"
                                   % (re.escape(_prop), re.escape(_val)), b)]:
                _ts_bad.append("%s: the stylesheet has no %s{%s}"
                               % (_k, _ev, _verdict))
    check("ts2 each verdict is substantiated where it is claimed - an overlay by "
          "an ::after that really declares 24px, a declaration by that "
          "declaration still resolving to 24, an exception by its reason sitting "
          "in the stylesheet: %r" % (_ts_bad,),
          not _ts_bad)

    # The other direction, and the one a register cannot see: a rule that PINS an
    # interactive box under 24. `min-*:0` is skipped because it removes a flex
    # floor rather than imposing a size, and the three `hit` selectors are skipped
    # because being under 24 is the whole point of them - ts2 is what holds their
    # overlay in place.
    _ts_cls = set()
    for _k in _TARGET_SIZE:
        for _c in _k.split(".")[1:]:
            _ts_cls.add(_c.split("[")[0])
    _ts_hit = set([e for v, e in _TARGET_SIZE.values() if v == "hit"])
    _ts_pinned = []
    for _raw, _body in _ts_bodies:
        for _part in [p.strip() for p in " ".join(_raw.split()).split(",")]:
            if not _part or _part.startswith("@") or _part in _ts_hit:
                continue
            _last = re.split(r"[ >+~]", _part)[-1]
            _tag = re.match(r"^[a-z]+", _last)
            _names = set(re.findall(r"\.([A-Za-z0-9_-]+)", _last))
            if not ((_tag and _tag.group(0) in _TS_TAGS) or (_names & _ts_cls)):
                continue
            for _d in re.finditer(r"(^|;)\s*(width|height|min-width|min-height)"
                                  r"\s*:\s*([^;]+)", " ".join(_body.split())):
                _px = _ts_px(_d.group(3))
                if _px is None or _px >= 24 or _px == 0:
                    continue
                _ts_pinned.append("%s{%s:%s}" % (_part, _d.group(2),
                                                 _d.group(3).strip()))
    check("ts3 no rule pins an interactive box under 24 CSS px behind the "
          "register's back - %r" % (sorted(set(_ts_pinned)),),
          not _ts_pinned)

    # --- WCAG 2.2 SC 1.3.1 Info and Relationships: the Composition tab's tables --
    # MEASURED IN CHROMIUM, never read off the source: the Composition tab paints
    # FIVE <table> elements and three of them carried no <th> at all - the ADO
    # connector's phase / task / bug stateMap grids, which are one builder (smTbl)
    # called three times. Every cell was a <td>, so the accessibility tree got a
    # 3x4 grid of loose text and neither column nor row could be announced: the
    # checkbox in row three was "never", with nothing saying never WHAT.
    #
    # The header row is real markup hidden from the eye, not a visible redesign.
    # The column legend a sighted reader gets is `adoStateMap`'s help text
    # ("Manifest status -> ADO state per transition. Empty cell = the built-in
    # default; 'never move' = ...") sitting in the label's i above each grid; a
    # visible header row would repeat those three words on all three grids of an
    # already tall card. So the <th> exists and is clipped, and the row header -
    # the manifest status - stays visible exactly where its <td> was.
    #
    # THE CENSUS IS OVER A SLICE, not a list somebody kept up to date: every
    # el('table') between renderComp and the end of renderAdoCard. A sixth table
    # added to either function has to declare a header row or ir1 names it.
    _ir_script = re.search(r"<script>([\s\S]*?)</script>", M.UI_HTML)
    _ir_js = _ir_script.group(1) if _ir_script else ""
    _ir_a = _ir_js.find("function renderComp(){")
    _ir_b = _ir_js.find("function findingKind(s){")
    _ir_slice = _ir_js[_ir_a:_ir_b] if (0 <= _ir_a < _ir_b) else ""

    def _ir_call(js, i):
        """One el(...) call's source, from its '(' to the matching ')'.

        Quote-aware, unlike the brace walk above it: a ')' inside a string
        literal ('(/audit:review)' is one of them, three lines from a table)
        would otherwise close the call early and hide everything after it.
        """
        _depth, _j, _quote = 0, i, ""
        while _j < len(js):
            _ch = js[_j]
            if _quote:
                if _ch == "\\":
                    _j += 2
                    continue
                if _ch == _quote:
                    _quote = ""
            elif _ch in "'\"":
                _quote = _ch
            elif _ch == "(":
                _depth += 1
            elif _ch == ")":
                _depth -= 1
                if _depth == 0:
                    return js[i:_j + 1]
            _j += 1
        return ""

    _ir_tables = []
    for _m in re.finditer(r"el\('table',\{([^}]*)\}", _ir_slice):
        _src = _ir_call(_ir_slice, _ir_slice.index("(", _m.start()))
        _cm = re.search(r"class:'([^']*)'", _m.group(1))
        _ir_tables.append((_cm.group(1) if _cm else "", "el('th'" in _src))
    _ir_classes = [c for c, _ in _ir_tables]
    # The vacuity guard, first and for the same reason ts0 exists: ir1 narrows
    # this set, and a slice that found nothing would report a tab with no
    # headerless table on it. Counted, not merely found - "regtbl adosm" alone
    # would pass an `in` while the other two had drifted out of the slice.
    check("ir0 the census reads the Composition tab out of the assembled page - "
          "%d table builder(s) between renderComp and renderAdoCard: %r"
          % (len(_ir_tables), _ir_classes),
          _ir_script is not None and _ir_slice != ""
          and _ir_classes == ["comp", "regtbl", "regtbl adosm"])
    _ir_bare = sorted([c for c, has in _ir_tables if not has])
    check("ir1 SC 1.3.1: every table the Composition tab builds emits header "
          "cells - the three stateMap grids it paints were 12 and 15 <td> with "
          "no <th> anywhere: %r" % (_ir_bare,),
          not _ir_bare)
    # Both directions. A <thead> bolted on while the status stayed a <td> passes
    # ir1 and still loses the row axis, which is the axis that carries meaning
    # here - the column says what kind of value, the row says which transition.
    check("ir2 SC 1.3.1: the stateMap grid names both axes - three "
          "<th scope=col> from the one builder, and a <th scope=row> where the "
          "manifest status used to be a <td>, so the never box in row three is "
          "announced as never/in_progress rather than as a loose checkbox",
          "el('th',{scope:'row',class:'mono'},stt)" in M.UI_HTML
          and "el('td',{class:'mono'},stt)" not in M.UI_HTML
          and M.UI_HTML.count("scope:'col'") == 3
          and "smTbl('phase'),smTbl('task'),smTbl('bug')" in M.UI_HTML)
    # The half a substring pin cannot see, so the numbers are the browser's:
    # `table-layout:fixed` takes its column widths from the table's FIRST ROW,
    # and that row is now the <th> row. Chromium at 1200px, the rule naming
    # :is(th,td), measures the three columns at 90 / 682 / 67 CSS px; mutated
    # back to `td` alone it measures 280 / 280 / 280 - a silent relayout of the
    # whole card that every `... in UI_HTML` case above shrugged at while it was
    # tried. The NEGATIVE pin is what holds it: the old rule must be GONE, not
    # merely joined by a new one, because both can be true at once and only the
    # browser can tell you which won.
    check("ir3 the header row is markup, hidden from the eye only - the clip "
          "and the fixed-layout widths both name th, and the row header is "
          "dressed back down to the cell it replaced",
          "table.adosm :is(th,td):first-child{width:5.6rem" in M.UI_HTML
          and "table.adosm :is(th,td):last-child{width:4.2rem}" in M.UI_HTML
          and "table.adosm td:first-child{" not in M.UI_HTML
          and "table.adosm td:last-child{" not in M.UI_HTML
          and ".vh{position:absolute" in M.UI_HTML
          and "clip-path:inset(50%)" in M.UI_HTML
          and "table.adosm thead th{" in M.UI_HTML
          and "table.adosm tbody th{" in M.UI_HTML
          # MEASURED over CDP Accessibility.getFullAXTree: Chromium folds
          # text-transform into the computed accessible NAME, so regtbl's
          # uppercase reached a row that paints nothing and these announced as
          # "MANIFEST STATUS". The header row is the deliverable here, so the
          # reset is pinned rather than left to the next reflow of that rule.
          and "text-transform:none;letter-spacing:normal}" in M.UI_HTML)

    def _re_starts(hay, needle):
        """Every index at which `needle` occurs - the census counts, never finds."""
        _out, _i = [], hay.find(needle)
        while _i >= 0:
            _out.append(_i)
            _i = hay.find(needle, _i + 1)
        return _out

    _JS_QUOTES = ("'", '"', "`")

    def _el_calls(js, tag):
        """Every `el('<tag>', ...)` construction in `js`, as its whole source span.

        Balanced over parentheses, skipping string literals - and MEASURED rather
        than assumed, because the obvious justification for the skipping is not the
        true one. Over today's script a walk that ignored strings entirely agrees
        with this one on all 7 spans: the tempting example,
        `flabel('Sprint team (current iteration)', ...)`, has a BALANCED pair inside
        its literal and costs a naive count nothing. What does bite is the
        half-measure - a walker that knows only `'`, the quote this file writes
        almost everything in, disagrees on ONE span: `"don't touch"` at the
        Remaining-Work row, where a single apostrophe inside a double-quoted string
        leaves it in string state to the end of the file and the span swallows the
        `cflag()` calls after it. So all three quote characters are tracked, and
        backslash escapes with them, on the rule rather than on the census - which
        literals happen to be on the page today is not something to depend on.
        `fw2` carries that case as a fixture.

        WHAT IT CANNOT SEE, AND THE DIRECTION IS THE POINT. This is TEXT over the
        assembled script, so it finds a `<label>` only where the tag name is a
        quoted literal in an `el()` call. A label built by `document.createElement`,
        by `el()` with a computed tag, or through `el()`'s `html:` (innerHTML)
        attribute is invisible to it. Each of those is a row it fails to produce,
        never a row it invents: the error is UNDER-counting, which is the quiet
        direction -- a clean result means "no offender of this shape", not "no
        offender". `fw3` below keeps that gap measured rather than assumed.
        """
        _needle, _out = "el('%s'," % tag, []
        _i = js.find(_needle)
        while _i >= 0:
            _depth, _quote, _k = 0, "", js.find("(", _i)
            while _k < len(js):
                _ch = js[_k]
                if _quote:
                    if _ch == "\\":
                        _k += 2
                        continue
                    if _ch == _quote:
                        _quote = ""
                elif _ch in _JS_QUOTES:
                    _quote = _ch
                elif _ch == "(":
                    _depth += 1
                elif _ch == ")":
                    _depth -= 1
                    if _depth == 0:
                        break
                _k += 1
            _out.append(js[_i:_k + 1])
            _i = js.find(_needle, _i + 1)
        return _out

    def _fl_in_label(js):
        """Every el('label', ...) span in `js` that holds a flabel(), one line each.

        THE RULE, and it is one line: a `<label>`'s accessible name is its OWN
        SUBTREE, and flabel() appends the i to the span it returns - so wherever
        that span sits inside a `<label>`, the i's text is inside the name. That is
        true of the `<span tabindex=0>` i as much as the `<button>` one, which is
        exactly the half `kl1` cannot see: kl1 asks whether anything LABELABLE can
        get between the label and its field, and a span is not labelable.

        STRICTER THAN "unless it binds by `for`", on purpose and stated so it is a
        choice rather than an oversight. No `for` rescues this shape: the wrapper's
        name is its subtree however the association is made, and a `<label>` inside
        a `<label>` is not valid content either. The binding that DOES fix it is
        flabel's own `el('label',{for:forId},text)` -- which holds the words and
        nothing else, and so reads clean here by construction (`fw1`).
        """
        return [" ".join(_c.split()) for _c in _el_calls(js, "label")
                if "flabel(" in _c]

    _ts_js = _ts_script.group(1) if _ts_script else ""

    # --- WCAG 2.2 SC 1.3.1 / 3.3.2 / 4.1.2: the i stopped stealing the label ----
    # MEASURED IN CHROMIUM over `element.labels`, which is the only thing that can
    # see this: a <button> is a LABELABLE element, so while the i sat inside a
    # field's <label> the label named the BUTTON - HTML resolves a label's control
    # to its first labelable descendant. 20 fields on Guards bound no label at all
    # and announced their own VALUE ("docs/audit/audit-plan.json" where "The plan"
    # was meant); three <select> announced nothing, which is 4.1.2 too.
    #
    # `closest('label')` reports all 20 as labelled and always did. THAT is why the
    # cases below pin construction rather than presence, and why the number they
    # rest on came from a browser: no substring pin can distinguish a <label> that
    # names this field from one that names something else inside it.
    check("kl0 the i is the <label>'s SIBLING, not its descendant - the words and "
          "the JSON key are inside, the button is outside, so it cannot take the "
          "association and cannot fold its own name into the field's",
          "function klabel(text,key,tip,forId){return el('span',{class:'lbl'},"
          in M.UI_HTML
          and "el('label',forId?{for:forId}:{},text,el('code',{class:'k2'},key)),"
          in M.UI_HTML
          and "hint(tip,{path:key,doc:'config',label:text}));}" in M.UI_HTML)
    # Both directions, and the negative is the one that matters: a container that
    # went back to being a <label> would put the button inside it again, and every
    # positive above would still be true.
    # NOT "no <label> exists": several remain and are correct. The invariant is
    # narrower and is the actual rule - a container may stay a <label> exactly
    # while nothing labelable can get between it and its field. klabel() ALWAYS
    # builds a button (it always passes a ref), so a klabel inside a <label> is the
    # defect itself; flabel() called with a ref builds one too.
    #
    # TWO DELIBERATE CHANGES HERE, and F41 forced both. The census was keyed on
    # `el('label',{class:'f` over 150-character windows, and F41's repair emptied
    # that set - which failed this case rather than passing it, because the
    # vacuity guard is real. Keying it on EVERY el('label', ...) construction
    # instead is strictly more: it now also reads the `class:'inl'` wrappers, which
    # this case has never looked at, and a fixed-width window that could run past
    # the end of a call into the next statement is replaced by the call's own
    # balanced span. What it no longer covers on its own is the flabel-without-a-ref
    # case, which was never this case's claim: `fw0` below owns that, and owns it
    # for a stronger reason than labelability.
    _kl_ctr = _el_calls(_ts_js, "label")
    _kl_steal = [" ".join(c.split())[:64] for c in _kl_ctr if "klabel(" in c]
    _kl_ref = [" ".join(c.split())[:64] for c in _kl_ctr
               if re.search(r"flabel\([^)]*,[^)]*,[^)]*\{", c)]
    check("kl1 a container may still be a <label> only while nothing labelable can "
          "get between it and its field: %d el('label') construction(s) read, %d "
          "holding a klabel (which always builds a <button>), %d passing flabel a "
          "ref (which makes one) - and the four klabel builders hand the control's "
          "id to the <label> that names it, the list editor excepted because its "
          "id is on a <div>"
          % (len(_kl_ctr), len(_kl_steal), len(_kl_ref)),
          _kl_ctr and not _kl_steal and not _kl_ref
          and "el('div',{class:'f'},klabel(f.label,f.path,tip,fieldId(f.path)),inp)"
              in M.UI_HTML
          and "el('div',{class:'f'},klabel(lbl,p,null,fieldId(p)),inp)" in M.UI_HTML
          and "el('div',{class:'f cbf'},cb,klabel(f.label,f.path,tip,fieldId(f.path)))"
              in M.UI_HTML
          and "el('div',{class:'f wide'},klabel(f.label,f.path,tip),ed)" in M.UI_HTML)

    # --- F41: the i is inside the wrapper's NAME, not merely labelable ----------
    # F26 repaired klabel and stopped. The rule it discovered was never written
    # down as a check, so it reached exactly the one builder somebody edited: NINE
    # call sites put flabel() inside an el('label', ...) and all nine kept the
    # defect. Two of them (`ado-tag`, `ado-rw`) were caught at 9415a43 only because
    # their wrapper held a SECOND field, which pushed the i's text into the MIDDLE
    # of the name -- "Provenance tag i no provenance tag at all no tag" -- and
    # failed SC 2.5.3 outright. The other seven put the i AFTER the visible words,
    # so 2.5.3 held and nothing looked at them again.
    #
    # kl1 above cannot see them and never could. It asks whether anything LABELABLE
    # sits between the label and its field, and a two-argument flabel builds a
    # `<span tabindex=0>`, which is not labelable. The association was fine. The
    # NAME was not: a label's accessible name is its own subtree, so the i's "i"
    # is in the name of every field those seven wrappers bound - the same fold-in
    # F26 measured on the six checkboxes that DID bind ("Meter token usage
    # usage.enabled What is Meter token usage?").
    #
    # And the span i inside a <label> is a live functional bug on top of that: it
    # is not interactive content, so a click on it activates the wrapper's control.
    # Three of the seven wrapped a CHECKBOX -- reading the hint toggled the setting
    # it was explaining. hint() in panel.js records that this is exactly why the i
    # becomes a real <button> when it has a ref; the span case was left standing.
    _fw_labels = _el_calls(_ts_js, "label")
    _fw_flabels = _ts_js.count("flabel(")
    _fw_bad = [_c[:104] for _c in _fl_in_label(_ts_js)]
    check("fw0 no flabel() sits inside an el('label', ...): a <label>'s accessible "
          "name is its OWN SUBTREE, so a wrapper holding one announces the i's "
          "stray \"i\" whether or not that i is labelable - which is the half kl1 "
          "is blind to. Read %d el('label') construction(s) against %d flabel() "
          "call(s) in the script; offenders %r"
          % (len(_fw_labels), _fw_flabels, _fw_bad),
          len(_fw_labels) >= 6 and _fw_flabels >= 10 and not _fw_bad)

    # THE REPAIR MUST READ CLEAN, or the lint forbids its own remedy and the next
    # person deletes the lint instead of the defect. The pinned builder text
    # gained hint()'s third argument under F42 — the ref-less i is named after
    # what it explains now, instead of being a focusable element announcing
    # nothing — which changes the literal without touching the property this
    # case is about: the builder still binds by `for` and still holds only the
    # words. Two shapes have to survive it:
    # flabel's own `el('label',{for:forId},text)`, which is the fix, and a repaired
    # call site, whose wrapper is a <span> and so is not scanned at all.
    _fw_bound = [_c for _c in _fw_labels if "for:forId" in _c]
    check("fw1 the remedy is not itself a finding: the two label BUILDERS bind by "
          "`for` and hold only the words (%d of them), and a repaired site - "
          "wrapper turned <span>, flabel given its 4th argument - leaves the "
          "scanned set entirely" % (len(_fw_bound),),
          len(_fw_bound) == 2
          and not [_c for _c in _fw_bound if "flabel(" in _c]
          and "forId?el('label',{for:forId},text):text,hint(tip,ref,text));}"
              in M.UI_HTML
          and not _fl_in_label(
              "el('span',{class:'f'},flabel(lbl,help,null,'ado-x'),i)"))

    # A guard that overreaches gets routed around and becomes its own defect class,
    # so both directions are driven over fixtures rather than assumed from a green
    # run on the page. The negatives are the shapes that are CORRECT and must stay
    # correct: a <label> with no flabel in it at all, and a two-argument flabel in
    # any wrapper that is not a <label> - a <span>, a <div>, a <th> - where the i
    # is beside the words and inside nobody's name.
    #
    # The third positive is why this check is stricter than "unless it binds by
    # `for`": a wrapper that binds by `for` is STILL a finding, because the name is
    # the subtree and `for` moves the association, not the i. A <label> inside a
    # <label> is not valid content either.
    #
    # The last CLEAN fixture is the quoting rule, and it is the one that has ever
    # been wrong in measurement: a walker that knew only `'` reads the apostrophe
    # in "don't" as an opening quote, never closes it, and runs the span on until
    # it has swallowed the flabel() that follows - a FALSE POSITIVE on a correct
    # <label>. It is copied from the shape the page really has at the
    # Remaining-Work row, where a `cflag()` call is the next argument along.
    _FW_CLEAN = ("el('label',{class:'inl'},tagNone,'no tag')",
                 "el('label',{class:'inl',for:'ovarea'},cb,'group by area')",
                 "el('div',{class:'f'},flabel(kind+' states',MDESC.adoStateMap),b)",
                 "el('span',{class:'f'},flabel('Provenance tag',MDESC.adoTag,"
                 "null,'ado-tag'),y)",
                 "el('th',{},flabel('model',MDESC.taskModel,{comp:'taskModel'}))",
                 "el('label',{class:'inl',for:'ado-rw-never'},nv,\"don't touch\"),"
                 "el('div',{},flabel(lbl,MDESC.adoComments))")
    _FW_DIRTY = ("el('label',{class:'f'},flabel(lbl,help),i)",
                 "el('label',{class:'f cbf'},cb,flabel(lbl,help))",
                 "el('label',{class:'f',for:'x'},flabel(lbl,help),i)",
                 "el('label',{class:'f'},flabel('Sprint team (current iteration)',"
                 "MDESC.adoSprint),team)")
    _fw_fp = [_s for _s in _FW_CLEAN if _fl_in_label(_s)]
    _fw_fn = [_s for _s in _FW_DIRTY if not _fl_in_label(_s)]
    check("fw2 the rule fires on the class and nothing else, driven over fixtures "
          "in both directions rather than trusted from a green page: %d/%d correct "
          "shapes wrongly flagged %r, %d/%d offending shapes missed %r"
          % (len(_fw_fp), len(_FW_CLEAN), _fw_fp,
             len(_fw_fn), len(_FW_DIRTY), _fw_fn),
          not _fw_fp and not _fw_fn)

    # SAY WHAT IT CANNOT SEE. The scanner is text over the assembled script, so it
    # sees a <label> only where the tag is a quoted literal in an el() call. Three
    # routes would build one without writing that, and each produces a row the
    # scanner never emits -- so the error is UNDER-counting, the quiet direction:
    # "no offenders" would read the same on a page full of them. The claim here is
    # not that the routes are impossible; it is that all three are MEASURED and
    # today carry no <label>, which is what makes the census above complete.
    _fw_ce = _ts_js.count("document.createElement(") - 1   # el()'s own is the one
    _fw_html = _ts_js.count("html:")                       # el()'s innerHTML hatch
    _fw_calc = re.findall(r"\bel\((?!')([^,)]{1,40})", _ts_js)
    _fw_calc_label = [_t for _t in _fw_calc if "'label'" in _t]
    # el()'s own call passes a variable tag, so a LITERAL-tag createElement is by
    # construction one of the routes this census cannot see. Naming the tags is
    # what keeps "one route exists" from weakening the claim: the route is only a
    # blind spot for <label> if it can build one.
    _fw_ce_tags = sorted(re.findall(r"document\.createElement\('([a-z]+)'\)", _ts_js))
    check("fw3 the blind spot is measured, not assumed - and it under-counts, "
          "which is the direction that reads as \"nothing wrong\": %d "
          "createElement outside el()'s own, %d html:/innerHTML attribute(s), %d "
          "el() call(s) with a computed tag, %d of those able to yield 'label' "
          "(the one is hint()'s `ref?'button':'span'`). The createElement is "
          "shared/download.js building %r, which cannot be a <label>: a shared "
          "part ships into the report too, and the report has no el()."
          % (_fw_ce, _fw_html, len(_fw_calc), len(_fw_calc_label), _fw_ce_tags),
          _fw_ce == 1 and _fw_ce_tags == ["a"] and _fw_html == 0
          and len(_fw_calc) == 1 and not _fw_calc_label)

    # The rule that is easy to read as cosmetic and is not. MEASURED: without it
    # Chromium names the field "The planmanifestPath" - it builds a name by walking
    # boxes, so two inline children of the new <label> collapse in the NAME exactly
    # as they collapse on screen. The visible defect and the announced one are one
    # defect, and one rule fixes both.
    check("kl2 the <label> inside .lbl is itself a row, which is what keeps the "
          "words and the key apart on screen AND in the accessible name",
          ".lbl>label{display:inline-flex;align-items:center;gap:var(--sp-0);"
          "flex-wrap:wrap;min-width:0}" in M.UI_HTML)
    # --- WCAG 2.2 SC 3.3.2 Labels or Instructions: a placeholder is not a name ---
    # MEASURED in Chromium before this section existed: 68 of 100 form fields on
    # the Composition tab and 4 of 90 on Guards had NO programmatic label at all -
    # `aria-label`, `aria-labelledby`, a `label[for]`, or a wrapping `<label>`. Every
    # one of them was "labelled" by a `placeholder`, which is the one accname source
    # of last resort: it is gone the moment a character is typed, so the field a
    # reader is IN is the field with no name. One - the buildCommands `<textarea>` -
    # had not even that, which is SC 4.1.2 as well.
    #
    # The half that can fail on something nobody thought about is the CENSUS: every
    # placeholder-bearing field is read out of the assembled page, so a new
    # `el('input',{placeholder:'…'})` is an offender the moment it is written. A
    # hand-kept list of the ones somebody remembered would pass forever.
    #
    # WHY aria-label AND NOT A <label> AT THESE SITES, since a real association is
    # the better tool where visible text exists. Nothing here has visible text that
    # NAMES ONE FIELD:
    #   - the 50 per-phase review boxes share one visible word ("review"), and the
    #     per-task model/skills boxes are named by a COLUMN HEADER - a `<label>`
    #     would give fifty controls the same name, which conforms and helps nobody.
    #     The aria-label carries the row's own id and still contains the visible
    #     word, so SC 2.5.3 Label in Name holds too;
    #   - reviewSkill, buildCommands, planGate, tokenVars and secretPatterns are
    #     each named by an `<h2>`/`<h3>` that also carries the JSON key and the i
    #     button. A heading is not a label, and `aria-labelledby` at it would fold
    #     "What is Build commands?" (the hint's own name) into the field's;
    #   - the identity-map pair and the ADO state boxes have no adjacent visible
    #     text at all.
    # Where a wrapping `<label>` IS the association, the field carries no aria-label
    # and _FL_LABELLED below records which `<label>` names it instead.
    _FL_TAGS = ("input", "select", "textarea")

    def _fl_fields(js):
        """Every el('input'|'select'|'textarea', {...}) attribute object, flattened."""
        _out = []
        for _m in re.finditer(r"el\('(%s)'," % "|".join(_FL_TAGS), js):
            _i = js.find("{", _m.end())
            if _i < 0:
                continue
            _depth, _j = 0, _i
            while _j < len(js):
                if js[_j] == "{":
                    _depth += 1
                elif js[_j] == "}":
                    _depth -= 1
                    if _depth == 0:
                        break
                _j += 1
            _out.append((_m.group(1), " ".join(js[_i:_j + 1].split())))
        return _out

    # The fields whose name comes from a <label> WRAPPING them, which is why they
    # carry no aria-label - adding one would replace a real association with a
    # weaker one. Each value is the construction that does the wrapping, and it has
    # to still be in the script: delete the <label> and the entry stops being true.
    # Confirmed by the same browser probe, which tests `closest('label')` and did
    # not report one of these six.
    # HOW AN EXEMPTION IS GROUNDED, and this is the half that was wrong. Each value
    # used to be the construction that WRAPS the field, on the reading that a
    # wrapping <label> means the field is named. It does not. A <label> names its
    # first LABELABLE descendant, and klabel()'s i is a <button> -- so twenty fields
    # sat exempted here while the browser bound them nothing at all and announced
    # their own value. A source string cannot see that, which means this table
    # would have stayed green through the whole defect. It is not enough for an
    # exemption to be true; it has to be able to STOP being true.
    #
    # So the two klabel entries name the EXPLICIT association -- the control's own
    # id, handed to the <label> that names it -- because tree position is precisely
    # what failed. TWO of the flabel entries now bind by `for` as well (F28): their
    # wrapper held a SECOND field, so the <label> collected that field's text too
    # and the accessible name read "Provenance tag i no provenance tag at all no
    # tag" against a visible "Provenance tag ... no tag" -- SC 2.5.3, measured, and
    # the reason the wrapper is a <span> here.
    #
    # NOW EVERY ENTRY NAMES AN EXPLICIT BINDING, and F41 is what finished that. The
    # remaining flabel entries used to stay POSITIONAL on the reading that a
    # two-argument flabel builds a <span>, which is not labelable, so nothing could
    # get between those wrappers and their field. True, and beside the point: a
    # <label>'s accessible name is its own subtree, so the i's "i" was in the name
    # of every field they bound whether or not it could steal the association. The
    # wrappers are <span> now and each field is reached by `for` - so this table no
    # longer has two kinds of entry in it, and `fw0` above is the check that stops
    # a third from being written.
    _FL_LABELLED = {
        "placeholder:def==null?(f.placeholder||''):String(def)":
            "klabel(f.label,f.path,tip,fieldId(f.path)),inp);",
        "placeholder:'not set'":
            "klabel(lbl,p,null,fieldId(p)),inp);",
        "placeholder:ph||''":
            "return el('span',{class:'f'},flabel(lbl,help,null,tid),i);",
        "placeholder:'audit-plugin'":
            "el('span',{class:'f'},flabel('Provenance tag',MDESC.adoTag,null,'ado-tag'),",
        "placeholder:'not written'":
            "el('span',{class:'f'},flabel('Remaining Work on done',",
        "placeholder:'empty = static iteration path'":
            "el('span',{class:'f'},flabel('Sprint team (current iteration)',",
    }

    _fl_all = _fl_fields(_ts_script.group(1) if _ts_script else "")
    _fl_ph = [(t, b) for t, b in _fl_all if "placeholder:" in b]
    # The vacuity guard, first. Everything below narrows this set, and a scanner
    # that matched nothing would report a page on which no field is mislabelled.
    # The four landmarks are one per shape the scanner has to reach: renderComp's
    # per-row boxes, a nested helper (skillChips), the Guards form, and the one
    # field built through `Object.assign(` rather than a bare object literal. A
    # regex that silently stopped reaching one of them is caught here rather than
    # passing quietly. They are all `el()` ATTRIBUTES on purpose - `'identifier…'`
    # reads like a fifth landmark and is not one: it is an ARGUMENT to listEditor,
    # so a census keyed on attributes must not claim to see it.
    _fl_marks = [m for m in ("placeholder:'review model'",
                             "placeholder:'search a skill to add…'",
                             "placeholder:'add a model id…'",
                             "placeholder:def==null?(f.placeholder||''):String(def)")
                 if not any(m in b for _, b in _fl_ph)]
    check("fl0 the census reads the assembled page rather than a list somebody "
          "kept up to date - %d form fields, %d of them placeholder-bearing, "
          "landmarks missing %r" % (len(_fl_all), len(_fl_ph), _fl_marks),
          _ts_script is not None and len(_fl_all) >= 40 and len(_fl_ph) >= 20
          and not _fl_marks)

    _fl_bad = [t + " " + b[:78] for t, b in _fl_ph
               if "'aria-label'" not in b and "'aria-labelledby'" not in b
               and not [k for k in _FL_LABELLED if k in b]]
    check("fl1 every field that shows a placeholder also carries a programmatic "
          "name - a placeholder vanishes on input, so a field labelled by one is "
          "nameless exactly while it is being used: %r" % (_fl_bad,),
          not _fl_bad)

    _fl_stale = sorted([k for k, v in _FL_LABELLED.items()
                        if not [b for _, b in _fl_ph if k in b]
                        or v not in M.UI_HTML])
    check("fl2 every exemption still describes the page: the field is still "
          "built, and the <label> named as its association is still the thing "
          "wrapping it - %r" % (_fl_stale,),
          not _fl_stale)

    # The two controls that had no placeholder to fall back on either. The
    # textarea's accessible name was the empty string, which is SC 4.1.2 (Name,
    # Role, Value) as much as SC 3.3.2.
    check("fl3 the two controls with no placeholder AND no wrapping label - the "
          "buildCommands textarea and the plan-gate select - are named from "
          "their visible headings",
          "el('textarea',{'aria-label':'meta.buildCommands (JSON)'})" in M.UI_HTML
          and "el('select',{id:fieldId('planGate'),"
              "'aria-label':'How hard the gate pushes'}" in M.UI_HTML)

    # A name is only useful if it tells one row from the next. Fifty boxes called
    # "review model" is a conforming page and an unusable one, so each carries the
    # id of the phase or task it edits - and still contains the visible word
    # ("review", "model", "skills"), which is what SC 2.5.3 Label in Name asks.
    # The skill box is the odd one of the four and the pin says so rather than
    # pretending otherwise: its input is built inside skillChips, so renderComp
    # cannot set the attribute and passes the NAME instead - the third argument,
    # landing on `'aria-label':name||'add a skill'` one function away. Written
    # first as `'aria-label':'add a skill to task '+(t.id||'')` and proven wrong by
    # this case going red on the finished fix, which is the only reason it is
    # right now.
    check("fl4 a per-row field is named by its row, not by its column: the phase "
          "review box and the task model box fold the id into the attribute, the "
          "task skill box folds it into the argument skillChips names it from, "
          "and the ADO state boxes fold in the kind and the status",
          "'aria-label':'review model for phase '+(ph.id||'')" in M.UI_HTML
          and "'aria-label':'model for task '+(t.id||'')" in M.UI_HTML
          and "'add a skill to task '+(t.id||'')" in M.UI_HTML
          and "'aria-label':ariaName||'add a skill'" in M.UI_HTML
          and "'aria-label':kind+' '+stt+' maps to ADO state'" in M.UI_HTML)

    # listEditor is shared by five call sites and only three of them need a name:
    # the other two hand it to a caller that already wraps it in a <label>, and an
    # aria-label there would REPLACE "Paths the guards skip" with "add…". So the
    # name is a parameter, passed where it is needed and left off where it is not -
    # `el()` drops a null attribute, which is what makes that safe.
    # The parameter is `ariaName`, not `name`, and the pin carries that on purpose:
    # in all three of these functions `name` ALREADY means a skill id or a model id
    # in the comboWrap callback a line below, and one identifier meaning two things
    # in one function is how a reader loses the thread. `label` was unavailable for
    # the same class of reason - it is a global function in this file.
    # THE HOLE fl1 LEAVES, and it let three fields through. listEditor's box is
    # built once and shared by five callers, so its attribute object reads
    # `'aria-label':ariaName||null` -- which fl1's source-text census counts as a
    # name whether or not a caller passed one. Nothing above can tell a name from a
    # null name, so the CALL SITES are counted instead.
    #
    # And the wrapping label is not the answer for any of them. MEASURED: an editor
    # holding one chip binds `labels` 0, because the chip's own "remove" <button>
    # becomes the label's first labelable descendant; empty, the same editor binds
    # 1. A field labelled only while it is empty is not labelled, and that is a
    # state no census taken on a loaded page would necessarily catch.
    _fl_le = [M.UI_HTML[m:m + 460] for m in _re_starts(M.UI_HTML, "listEditor(")
              if not M.UI_HTML[m - 9:m].endswith("function ")]
    _fl_unnamed = [c[:52] for c in _fl_le
                   if not re.search(r",\s*(null|reErr|[A-Za-z_$][\w$]*)\s*,\s*"
                                    r"(?:'[^']+'|[A-Za-z_$][\w$.]*\s*\+)", c)]
    check("fl6 every listEditor call site passes a name, because the box cannot be "
          "named from inside the helper and cannot be named by the <label> around "
          "it either - one chip and the chip's remove button takes that label: "
          "%d call site(s), %d passing nothing" % (len(_fl_le), len(_fl_unnamed)),
          len(_fl_le) == 5 and not _fl_unnamed)

    check("fl5 listEditor takes the name rather than inventing one, and the two "
          "Guards editors that are not inside a <label> pass it - the tokenVars "
          "one twice, because it is rebuilt in place when the defaults notice "
          "changes and a redraw that dropped the name would be invisible",
          "function listEditor(getArr,setArr,ph,validate,ariaName)" in M.UI_HTML
          and "el('input',{placeholder:ph||'add…','aria-label':ariaName||null})"
              in M.UI_HTML
          and M.UI_HTML.count(
              "'Secrets never written to logs: add an identifier'") == 2
          and M.UI_HTML.count(
              "'Extra files treated as secrets: add a pattern'") == 1)

    # --- WCAG 2.2 SC 4.1.2 Name, Role, Value: the fields fl1 cannot reach --------
    # EVERYTHING ABOVE IS SCOPED TO A PLACEHOLDER, and that scope is the reason
    # the 4.1.2 half of this finding needed a browser at all. The buildCommands
    # <textarea> carried no placeholder, so `_fl_ph` could never have contained
    # it and no case here could have named it; what it got instead was fl3, two
    # controls pinned as literal strings - which is a hand-kept list of the ones
    # somebody remembered, the exact shape fl0's own comment says passes forever.
    # 4.1.2 asks for a name on EVERY control, so the census below is over every
    # field the script builds and the count in its label says how many of them
    # fl1 never looks at.
    #
    # WHAT COUNTS AS A NAME HERE, and neither half is mere presence:
    #   - `aria-label` / `aria-labelledby` in the attribute object; or
    #   - an `id` that a <label> ACTUALLY binds. The vocabulary of bound ids is
    #     read out of the page rather than listed: every `for:` value, plus every
    #     4th argument handed to klabel()/flabel(), which is precisely what those
    #     two builders turn into their `<label for>`. Drop that argument at a
    #     call site and the field keeps its id, keeps its <label> and announces
    #     its own value again - F26 in the one direction nothing here watched,
    #     because the field's own attribute object does not change.
    # A WRAPPING <label> IS DELIBERATELY NOT ONE OF THEM. _FL_LABELLED above
    # records the whole reason: a <label> names its FIRST LABELABLE DESCENDANT,
    # so tree position is an association no source check can verify, and twenty
    # fields once sat exempted on it while the browser bound them nothing at all.
    # The three `class:'inl'` checkboxes that were still positional - the
    # provenance-tag opt-out, the stateMap "never" boxes and the Remaining-Work
    # one - carry an explicit `for` now for that reason and no other: same words,
    # same click target, an association that can go red. Every el('label') the
    # script builds binds by `for` as a result, and fl8 is what keeps it that way
    # rather than a case of its own - a field that went back to leaning on tree
    # position has no aria-* and no bound id, so it lands in the offender list.
    def _nv_args(js, i):
        """The top-level arguments of the call whose '(' follows index `i`.

        Depth- and quote-aware, and MEASURED rather than assumed: over today's
        script a splitter that ignored string literals entirely disagrees with
        this one on two of these calls, and on `flabel('Policy enabled', 'Off
        writes policy.enabled:false, which is how you keep the rules and stop
        applying them.', null, 'polenabled')` it reads the 4th argument as
        `null` - a FALSE offender on a checkbox that is correctly bound. A
        walker that knew only `'` agrees with this one today; all three quote
        characters are tracked on the rule rather than on the census, the same
        way `_el_calls` above does and for the same reason - which literals
        happen to sit on the page today is not a thing to depend on.
        """
        _k = js.find("(", i)
        if _k < 0:
            return []
        _depth, _quote, _out, _start, _j = 0, "", [], _k + 1, _k
        while _j < len(js):
            _ch = js[_j]
            if _quote:
                if _ch == "\\":
                    _j += 2
                    continue
                if _ch == _quote:
                    _quote = ""
            elif _ch in _JS_QUOTES:
                _quote = _ch
            elif _ch in "([{":
                _depth += 1
            elif _ch in ")]}":
                _depth -= 1
                if _depth == 0:
                    _out.append(js[_start:_j])
                    return [" ".join(_a.split()) for _a in _out]
            elif _ch == "," and _depth == 1:
                _out.append(js[_start:_j])
                _start = _j + 1
            _j += 1
        return []

    def _nv_attr(attrs, key):
        """The value of `key:` in a flattened el() attribute object, or ''.

        Anchored to `{` or `,` so it reads a whole attribute name and not the
        tail of a longer one - `id` is a suffix of plenty of plausible attribute
        names. MEASURED: today it changes no answer, because no attribute name
        in any of these objects ends in `id`. The anchor is on the RULE for the
        same reason `_el_calls` tracks all three quote characters - which names
        happen to sit on the page today is not a thing to depend on.
        """
        _m = re.search(r"(?:^|[{,])\s*%s\s*:" % key, attrs)
        if not _m:
            return ""
        _depth, _quote, _j = 0, "", _m.end()
        while _j < len(attrs):
            _ch = attrs[_j]
            if _quote:
                if _ch == "\\":
                    _j += 2
                    continue
                if _ch == _quote:
                    _quote = ""
            elif _ch in _JS_QUOTES:
                _quote = _ch
            elif _ch in "([{":
                _depth += 1
            elif _ch in ")]}":
                if _depth == 0:
                    break
                _depth -= 1
            elif _ch == "," and _depth == 0:
                break
            _j += 1
        return " ".join(attrs[_m.end():_j].split())

    _NV_BUILDERS = ("klabel(", "flabel(")
    _nv_for = sorted(set(re.findall(r"\bfor\s*:\s*([^,}]+)", _ts_js)))
    _nv_4th = set()
    for _nv_b in _NV_BUILDERS:
        for _nv_i in _re_starts(_ts_js, _nv_b):
            _nv_a = _nv_args(_ts_js, _nv_i + len(_nv_b) - 1)
            if len(_nv_a) >= 4:
                _nv_4th.add(_nv_a[3])
    _nv_bound = set(_nv_for) | _nv_4th
    # The vacuity guard, and it guards the half that CAN go quiet. An empty
    # vocabulary makes every id-bound field an offender, so fl8 goes red and says
    # so - the loud direction. What would go quiet is a vocabulary that swallowed
    # something it should not, so the two sources are counted separately and the
    # landmarks are one per shape the reader has to reach: the builders' own
    # parameter, a literal id written at a call site, an id computed per row, and
    # a bare identifier passed through a local.
    _NV_MARKS = ("forId", "'ado-tag-none'", "nvId", "'ado-sprint.team'", "cid")
    _nv_missing = [_m for _m in _NV_MARKS if _m not in _nv_bound]
    check("fl7 which ids a <label> really binds is read out of the page, not "
          "listed: %d `for:` value(s) and %d 4th argument(s) to klabel/flabel, "
          "%d distinct id(s) between them; landmarks missing %r"
          % (len(_nv_for), len(_nv_4th), len(_nv_bound), _nv_missing),
          _ts_js != "" and len(_nv_for) >= 5 and len(_nv_4th) >= 8
          and not _nv_missing)

    # The two controls no reader can reach, and each basis sits IN the attribute
    # object it exempts, so it cannot quietly stop being true: make either one
    # perceivable and the key stops matching and the field becomes an offender.
    # That is the property _FL_LABELLED had to be rewritten twice to get.
    #   - the theme import <input type=file>, which `display:none` takes out of
    #     the accessibility tree entirely - the button beside it is what the
    #     reader operates, and it has its own name;
    #   - the copy fallback's <textarea>, which is appended, selected, read by
    #     execCommand and removed inside one synchronous block. Offscreen is NOT
    #     the exemption - offscreen is still announced - so the second half of
    #     the basis is the removal, asserted below.
    _NV_UNREACHABLE = {
        "style:'display:none'": "theme import file input",
        "style:'position:fixed;top:-1000px;opacity:0'": "copy fallback buffer",
    }
    _nv_bare = []
    for _nv_t, _nv_ab in _fl_all:
        _nv_id = _nv_attr(_nv_ab, "id")
        if "'aria-label'" in _nv_ab or "'aria-labelledby'" in _nv_ab:
            continue
        if _nv_id and _nv_id in _nv_bound:
            continue
        _nv_bare.append((_nv_t, _nv_ab))
    _nv_off = [_t + " " + _b[:78] for _t, _b in _nv_bare
               if not [_k for _k in _NV_UNREACHABLE if _k in _b]]
    _nv_stale = sorted([_k for _k in _NV_UNREACHABLE
                        if not [_b for _, _b in _nv_bare if _k in _b]])
    check("fl8 SC 4.1.2: every field the panel builds is named by something a "
          "reader can hear - %d field(s) read, %d reaching no aria-* and no "
          "bound id, of which %d are unreachable by construction (%r stale); "
          "unnamed and reachable: %r"
          % (len(_fl_all), len(_nv_bare),
             len(_nv_bare) - len(_nv_off), _nv_stale, _nv_off),
          not _nv_off and not _nv_stale
          # The copy buffer's exemption is the removal, not the offset.
          and "ta.remove();" in M.UI_HTML)

    # A guard that overreaches gets routed around, so the binder is driven over
    # fixtures in both directions rather than trusted from a green page. The
    # POSITIVES are the two shapes that really do name a field; the NEGATIVES are
    # the two ways a call site loses the binding while its own attribute object
    # and its <label> both stay exactly as they were - the 4th argument dropped,
    # and the `for` written to an id nothing carries.
    def _nv_binds(field_src, page_src):
        """True if the field built by `field_src` is bound by `page_src`."""
        _ab = " ".join(_fl_fields(field_src)[0][1].split())
        _id = _nv_attr(_ab, "id")
        _vocab = set(re.findall(r"\bfor\s*:\s*([^,}]+)", page_src))
        for _b in _NV_BUILDERS:
            for _i in _re_starts(page_src, _b):
                _a = _nv_args(page_src, _i + len(_b) - 1)
                if len(_a) >= 4:
                    _vocab.add(_a[3])
        return bool(_id) and _id in _vocab
    _NV_YES = (("el('input',{type:'checkbox',id:'x'})",
                "el('label',{class:'inl',for:'x'},cb,'never')"),
               ("el('input',{id:tid,placeholder:ph||''})",
                "flabel(lbl,help,null,tid)"))
    _NV_NO = (("el('input',{id:tid,placeholder:ph||''})",
               "flabel(lbl,help,null)"),
              ("el('input',{type:'checkbox',id:'x'})",
               "el('label',{class:'inl',for:'y'},cb,'never')"))
    _nv_fn = [_f for _f, _p in _NV_YES if not _nv_binds(_f, _p)]
    _nv_fp = [_f for _f, _p in _NV_NO if _nv_binds(_f, _p)]
    check("fl9 the binder fires on the association and not on its neighbourhood, "
          "driven over fixtures both ways: %d/%d bound shapes missed %r, %d/%d "
          "unbound shapes wrongly cleared %r"
          % (len(_nv_fn), len(_NV_YES), _nv_fn, len(_nv_fp), len(_NV_NO), _nv_fp),
          not _nv_fn and not _nv_fp)

    # SAY WHAT fl8 CANNOT SEE, AND WHICH WAY EACH BLIND SPOT ERRS - they are not
    # the same direction, which is why they are listed apart rather than together.
    # fl8 is text over the assembled script: it reads a field only where the tag
    # is a quoted literal in an el() call, and a name only where the attribute is
    # written into that same call.
    #   - A field built by document.createElement or by el() with a computed tag
    #     is a row fl8 never emits, so it reads as no finding: UNDER-counting,
    #     the quiet direction. fw3 above measures both routes at zero.
    #   - A field NAMED after construction, by setAttribute('aria-label', ...),
    #     is a row fl8 does emit and judges wrongly: it would be reported as an
    #     offender while a reader hears its name. That is the loud direction and
    #     still a wrong answer, so it is measured here rather than assumed away.
    _nv_late = [_m for _m in re.findall(r"setAttribute\('([^']+)'", _ts_js)
                if _m in ("aria-label", "aria-labelledby")]
    check("fl9a the blind spot is measured rather than assumed: %d "
          "setAttribute('aria-label'|'aria-labelledby') call(s) in the script, "
          "all of them on the i rather than on a field - a name written after "
          "construction is invisible to fl8 and would read as an offender"
          % (len(_nv_late),),
          len(_nv_late) == 2
          and "h.setAttribute('aria-label','What is '+hRefName(ref)+'?');"
              in M.UI_HTML
          and "if(name)h.setAttribute('aria-label','What is '+name+'?');}"
              in M.UI_HTML)

    # --- WCAG 2.2 SC 2.4.11 Focus Not Obscured (Minimum) ------------------------
    # MEASURED by driving real Tab presses, not `.focus()`: 72 of 942 focus stops
    # across six tabs and two viewports landed ENTIRELY under pinned chrome -- 60
    # under `.top`, 11 under `.savebar`, 1 under `.ufil`. Shift+Tab far worse than
    # Tab, because backwards traversal walks up into the header.
    #
    # THE BEHAVIOUR IS PINNED BY THE BROWSER GATE, not by these lines: only
    # `tools/capture-screenshots.mjs`'s 2.4.11 walk can see whether a control is
    # covered, and it fails at 17 of 353 with this feature switched off. What the
    # cases here add is the half a browser gate is bad at -- catching the feature
    # being DELETED, which would leave that walk measuring a page that no longer
    # tries.
    check("fo1 the panel repairs an obscured focus, and does it on real focus "
          "rather than on a scroll listener",
          "function keepFocusClear(){" in M.UI_HTML
          and "document.addEventListener('focusin'" in M.UI_HTML
          and "try{keepFocusClear();}" in M.UI_HTML)
    check("fo2 the correction terminates on PROGRESS, not on a tuned count: a "
          "pass that moves nothing stops it, and the ceiling is only a spin "
          "guard - a fixed 3 left 10 of the 72, 6 left 5, 8 left 2, 16 left none",
          "if(now===was)return;" in M.UI_HTML
          and "for(let pass=0;pass<16;pass++){" in M.UI_HTML)
    check("fo3 which viewport HALF the chrome sits in decides the direction, not "
          "how its edges compare - comparing edges reads a bottom bar backwards "
          "the moment the control is fully under it, which left every savebar "
          "case unrepaired",
          "const atTop=(c.top+c.bottom)/2<innerHeight/2;" in M.UI_HTML
          and "const by=atTop?-(c.bottom-r.top+GAP):(r.bottom-c.top+GAP);"
              in M.UI_HTML)
    check("fo4 an open dropdown is closed rather than scrolled out from under - "
          "a fixed menu travels with the viewport, so scrolling cannot free "
          "anything, and a menu whose input lost focus has nothing to choose for",
          "over.classList.contains('combo-menu')&&!over.contains(n)" in M.UI_HTML
          and "closeCombo();continue;" in M.UI_HTML)
    check("fo5 the repair cannot be the reason the panel fails to come up",
          "catch(cause){console.error('keepFocusClear failed',cause);}"
          in M.UI_HTML)

    # --- isolation: the moved boundary stays real -------------------------------
    # This file is BELOW panel-server and below the panel's read/write sides. It
    # holds page claims only, which is what lets it sit at layer 4; an import of
    # any of those four would be an upward or peer edge and a new KNOWN_LAYER_DEBT
    # entry. _deps.py fails the build on it, and this says the same thing in the
    # file's own suite so the reason is readable where the mistake would be made.
    _self_src = open(M.__file__, encoding="utf-8").read()
    _imports = [l for l in _self_src.split("\n")
                if l.startswith("import ") or l.strip().startswith("import ")
                or l.startswith("from ")]
    _forbidden = [l for l in _imports
                  if any(n in l for n in ("panel_server", "panel-server",
                                          "_panel_state", "_panel_write",
                                          "_panel_discovery"))]
    check("pg2 this file imports neither panel-server nor the panel's read/write "
          "sides - the page is assembled below all three, which is the whole "
          "reason a layer-4 home exists for it: %r" % (_forbidden,),
          not _forbidden)

def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__panel_page.py --selftest\n")
    raise SystemExit(2)
