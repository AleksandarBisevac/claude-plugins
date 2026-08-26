#!/usr/bin/env python3
"""
The cases for `_panel_page.py`, moved out of it - an importable helper.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list. This is the biggest single move in the migration: 1,636 of
that file's 1,759 lines were this suite, and what stayed behind is the module rather
than its cases. Nearly every read in these cases is of one string, `M.UI_HTML` - the
panel's assembled page - and `grep -c "M.UI_HTML" plugins/audit/tests/test__panel_page.py`
counts them rather than this docstring claiming a figure that moves with every case
added.

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
import os
import re
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
import _output                                     # noqa: E402  (PLUGIN_ROOT: the schema this page's words must agree with)
from _output import safe_stdio                     # noqa: E402
import _help                                       # noqa: E402  (topic ids + COMPOSITION_PATHS)
import _loader                                     # noqa: E402  (as _panel_page imports it)
import _panel_settings                             # noqa: E402  (as _panel_page imports it)
import _panel_ui                                   # noqa: E402  (the raw template, uncached)
import _ui_theme as _theme                         # noqa: E402  (as _panel_page imports it)
import _ado_parent as _adop                        # noqa: E402  (the marker, in the other language)
import _ado_tracked as _adot                       # noqa: E402  (the field name, in the other language)
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
    # gp: the control for the endpoint that card renders the rows of (F110).
    # `POST /api/gate-events/prune` answered with a real verdict for a release
    # while nothing on the page named it, and `commands/logs.md` said so out
    # loud. These are SOURCE-PROPERTY pins and are labelled as such: that the
    # control is on this card, that it previews before it writes, and that no
    # path from the answer is rendered. Whether the button paints and the dialog
    # opens is a browser claim and belongs to `tools/capture-screenshots.mjs`.
    _gp_src = _over_src[_over_src.index("No gate events yet"):
                        _over_src.index("c.append(gcard);}")]
    check("gp: the prune control is built onto the Plan gate card itself, past "
          "the empty-feed branch - an empty events table is not an empty file "
          "(an unreadable row renders nowhere), so it is not a place to hide it",
          "gpControl()" in _gp_src
          and "'data-gpprune':'1'" in _over_src
          and "'data-gpctl':'1'" in _over_src)
    check("gp: it asks for a dry run and puts THAT answer in the confirm dialog "
          "before it posts for real - two calls, the shape /api/proposal already "
          "uses, because a destructive button whose preview is its own effect is "
          "not a preview",
          "Object.assign({dryRun:true},body)" in _over_src
          and "confirmChanges({" in _over_src
          and _over_src.index("dryRun:true")
          < _over_src.index("const done=await api('POST','/api/gate-events/prune',body)"))
    check("gp: the dialog lists EVERY class the server returned, zeros included "
          "- `_gate_feed` returns them all on purpose, and a count that appears "
          "only when it is non-zero cannot be told from one nobody computed",
          "Object.keys(cls).map(k=>cfRow(GPFEED,k,cls[k],0))" in _over_src)
    check("gp: and no path out of the answer reaches the page - `path` names the "
          "feed file under whoever ran it, the removed rows' paths are the thing "
          "being removed, and this card is what docs/screenshots/panel-gate.png "
          "is a committed render of",
          "dry.path" not in _over_src and "done.path" not in _over_src
          and "const GPFEED='plan-gate-events.jsonl';" in M.UI_HTML
          and "/" not in "plan-gate-events.jsonl")

    # gp/F162: the outcome a prune reports when it removed nothing. SOURCE-PROPERTY
    # pins, and labelled so rather than by the behaviour they stand near: what the
    # toast SAYS is text, and whether a reader can read it is a browser claim.
    # `gpReach` itself is a pure function at the panel's top level, which is the
    # shape `tools/ui-tests/` executes - the case that CALLS it with null and with
    # zero belongs there, and this suite cannot reach it.
    _reach_at = M.UI_HTML.index("const gpReach=")
    _reach = M.UI_HTML[_reach_at:M.UI_HTML.index("\n/**", _reach_at)]
    check("gp: a prune that removed nothing no longer reports the FILE as clean - "
          "that is the one thing a prune cannot know, because a whole shell "
          "command in an old row's `file` resolves inside the repository exactly "
          "as a relative path does and every class reads it as belonging",
          "every row in the feed still belongs" not in M.UI_HTML
          and "No row breaks a rule this prune can check" in _over_src)
    check("gp: ...and the reach is rendered beside that claim, off the answer's "
          "own `oldestKeptDays` and never re-derived here - age is the lever that "
          "reaches those rows, a claim about what a prune cannot see owes the "
          "number it is aimed with, and a clock on this side would be a second "
          "answer to a question the endpoint has already answered",
          "gpReach(dry.oldestKeptDays)" in _over_src
          and _over_src.count("gpReach(") == 1
          and "Date.now()" not in _reach and "new Date" not in _reach)
    check("gp: and an unknown reach cannot paint as a present one - `null` there "
          "means no kept row is stamped and never zero, so the arms share no "
          "wording and only the numeric one reaches the count formatter",
          "Number.isFinite(days)" in _reach
          and _reach.count("plural(") == 1
          and "||0" not in _reach and "|| 0" not in _reach
          and "unknown" in _reach)

    # gp/F164: the OTHER half of that statement. `audit-logs.render` prints the
    # `oldest` row and `_HISTORY` together and says so in its own docstring - the
    # note is what a prune cannot decide, the number is the basis that makes it
    # actionable - and the panel rendered the number alone. SOURCE-PROPERTY pins
    # across two files: that the panel says it at all, and that it says it in the
    # CLI's words rather than in a second set. Whether a reader can READ the hint
    # is a browser claim and belongs to `tools/capture-screenshots.mjs`.
    _logs = _loader.load_script("audit-logs.py", modname="audit_logs")
    _history = " ".join(_logs._HISTORY.split())
    _gpnote_src = M.UI_HTML[M.UI_HTML.index("const GPNOTE="):]
    _gpnote_src = _gpnote_src[:_gpnote_src.index("';") + 2]
    _gpnote = "".join(re.findall(r"'([^']*)'", _gpnote_src))
    # Derived FROM the CLI constant rather than retyped here: the panel carries
    # `_HISTORY` up to the one clause that is the CLI's alone (`oldest` is a row in
    # a terminal render and no part of this page). An empty expectation would make
    # `endswith` vacuous, so it is required to be non-empty in the same expression.
    _hist_cut = ", and `oldest` above is what to aim it with."
    _hist_run = _history[:_history.index(_hist_cut)] if _hist_cut in _history else ""
    check("gp/F164: the panel says what a prune CANNOT decide, in audit-logs.py's "
          "own `_HISTORY` words and not a second wording of them - one fact "
          "rendered twice in two spellings is two facts the day one is edited: %r"
          % (_gpnote[-60:],),
          bool(_hist_run) and _gpnote.endswith(_hist_run + ".")
          and _gpnote.startswith("Rows naming somewhere outside this repository"))
    check("gp/F164: ...and its home is the prune control's own persistent hint, "
          "beside the age box the sentence ends by naming as the lever - never "
          "the toast, which hides in under three seconds and carries one short "
          "line, so a paragraph there is the same defect one layer over",
          "el('span',{class:'mut small','data-gphint':'1'},GPNOTE)" in _over_src
          and "GPNOTE" not in _over_src[
              _over_src.index("async function gpPrune("):
              _over_src.index("function gpControl(")]
          and ".ovtools [data-gphint]{flex-basis:100%}" in M.UI_HTML)

    # gp/F170: ONE FIELD, ONE WORD, ON ONE CARD. That hint points at columns BY
    # NAME - the backticked words are the keys of a row as it sits in the feed file
    # - and the table it points at is a few pixels above it. The heading said "why"
    # where the sentence said `reason`, so one of the two names resolved on the page
    # and the other dead-ended. The hint is the half that cannot move: those are the
    # on-disk keys, and the panel carries `audit-logs._HISTORY` word for word (the
    # case above). So the heading took the field's name, which was also the better
    # heading - it was the only question word in any table head on this page.
    # DERIVED FROM THE CLI CONSTANT, not from a list typed here: retyping the names
    # would make this pass on the day someone reworded the hint and forgot the card.
    # `_hist_run` and not `_history`, because the clause the panel drops names
    # `oldest`, which is a row in a terminal render and no column of anything.
    # Bounded at BOTH ends of the gate card, not just its start. An open-ended
    # slice would find the next `tableHead(` anywhere below - Ready now has one -
    # so a gate card that lost its table would go on comparing headings, against
    # another card's. Closed, the missing endpoint raises instead, which is the
    # outcome to want.
    _gate_src = _over_src[_over_src.index("id:'gatecard'"):
                          _over_src.index("c.append(gcard);")]
    _gate_head = _gate_src[_gate_src.index("tableHead(["):]
    _gate_cols = re.findall(r"'([^']*)'", _gate_head[:_gate_head.index("])")])
    _hint_fields = re.findall(r"`([a-z]+)`", _hist_run)
    check("gp/F170: every field the prune hint names in backticks is a heading "
          "over the table beside it - a sentence that points at a column the "
          "reader cannot find on the card is a broken pointer, and one field "
          "spelled two ways is how it got broken: hint %r vs headings %r"
          % (_hint_fields, _gate_cols),
          # Both required non-empty: an empty needle set makes the subset test
          # true of anything, which is this case's own silent-pass shape.
          bool(_hint_fields) and bool(_gate_cols)
          and set(_hint_fields) <= set(_gate_cols))

    check("and it drops the container it emptied, so no \"usage\": {} is left behind",
          "if(par&&typeof par==='object'&&!Object.keys(par).length)" in M.UI_HTML)
    check("Settings keeps the route, the screenshot name and the pinned id it "
          "already had - an internal id is an address, not a description",
          # `aria-current` used to be asserted here too, and it was never this
          # pin's subject: it marks whichever tab LEADS the strip, which is now
          # Overview. The claim this case is named for is that the route id stayed
          # `guards` while the visible word is "Settings".
          "data-t=guards>Settings<" in M.UI_HTML
          and "$('#guards')" in M.UI_HTML)

    # ORDER BECAME LOAD-BEARING, so it gets a case that says so. It never had one
    # because it never decided anything: the landing was the hard-coded string
    # 'guards' and the strip was a separate hand-kept list, so the two could not
    # disagree in a way anyone noticed. `initialTab()` returns TABS[0] now and
    # `showTab` falls back to it, which makes the tuple the landing rule and the
    # strip what a reader sees. Two orders that drifted apart would highlight one
    # view and open another.
    _tabs_src = M.UI_HTML[M.UI_HTML.index("const TABS=["):
                          M.UI_HTML.index("],SCROLL={}")]
    _tab_ids = re.findall(r"'([a-z]+)'", _tabs_src)
    _strip_ids = re.findall(r'<button class="tab[^"]*" data-t=([a-z]+)', M.UI_HTML)
    check("the nav strip and TABS are ONE order, and its first entry is where the "
          "panel lands - Overview leads because \"where are we\" is the common "
          "visit, and Settings led only because it was built first",
          _tab_ids == _strip_ids and _tab_ids and _tab_ids[0] == "over"
          and "return TABS[0];}" in M.UI_HTML
          and "if(!TABS.includes(t))t=TABS[0];" in M.UI_HTML,
          repr({"TABS": _tab_ids, "strip": _strip_ids}))
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
    # --- and the version stamp is not on that line ------------------------------
    # CONSTRUCTS, not the behaviour. Whether the stamp is READABLE is settled in a
    # browser — capture-screenshots.mjs reads the topbar and compares it against
    # plugin.json — and no substring here can see a clip. What these hold is where
    # the stamp is BUILT and what it is drawn with, which is what the clip fed on:
    # appended to `#proj` it began after a path that had already spent the whole
    # line, so on any path long enough to elide the version was off the end of it.
    check("the version stamp is built beside the title rather than appended to "
          "the project path, and is still omitted when there is no version",
          "if(VERSION)$('#brand').append(" in M.UI_HTML
          and "$('#proj').append(" not in M.UI_HTML
          and "<div class=brand id=brand><h1>" in M.UI_HTML)
    check("the stamp is seated on the title's baseline, in the muted token at the "
          "smallest type step - the declarations, not the paint",
          ".brand{display:flex;align-items:baseline" in M.UI_HTML
          and ".stampv{font-family:var(--mono);font-size:var(--t-label);"
              "color:var(--muted)" in M.UI_HTML)
    check("whether there is room for it is MEASURED, and re-measured when the "
          "topbar's own contents change - the pill lands after this file runs and "
          "fires no resize, so a listener alone would decide once and be wrong",
          "function stampRoom(" in M.UI_HTML
          and "new ResizeObserver(stampRoom).observe(" in M.UI_HTML
          and "addEventListener('resize',stampRoom" in M.UI_HTML
          and ".brand:not(.roomy) .stampv{display:none}" in M.UI_HTML)

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
          "const OVF={q:'',ts:'',bs:'',byArea:false,sort:'plan',view:null,open:{},"
          "evOpen:{}};" in M.UI_HTML
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
          # The visible name moved to "Plan & models" - the ROUTE is still `comp`
          # and `openInComp` is still the function, the same split Settings has
          # carried since it was `guards`. The negative below keeps its old
          # wording on purpose: it names the string the removed behaviour used to
          # emit, so rewriting it would assert the absence of something that never
          # existed.
          and "onclick:()=>openInComp(p.id)},'Edit in Plan & models')" in M.UI_HTML
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
          "stamp to the minute - plus `tests`, which is what a run RECORDED "
          "about the task and is deliberately a column of its own beside the "
          "status the plan claims",
          "function ovDetail(" in M.UI_HTML
          and "tableHead(['id','title','status','tests','risk','commit',"
              "'done (UTC)'])" in M.UI_HTML
          and "class:'rk','data-risk':t.risk" in M.UI_HTML
          and ".rk[data-risk=\"high\"]{color:var(--err)}" in M.UI_HTML)

    # --- ev: recorded test runs, as the Overview shows them ---------------------
    # The slice below is bounded by the section marker and by `ovDetail`, which
    # makes that marker load-bearing source: `_harness.between` RAISES on a
    # marker that has moved, where a `.index()` pair would silently re-point at
    # something else and go on passing about a different span. Every negative
    # here is scoped to it, because "no truthy test on a three-valued field" is a
    # claim about THIS code and would be unenforceable over the whole page.
    _evsrc = _harness.between(M.UI_HTML, "// ---------- recorded test runs ----",
                              "function ovDetail(p){")
    _evwords = ["Passed", "Failed", "No checks ran", "Timed out", "Cancelled",
                "Could not run", "Empty gate", "No evidence",
                "No gate configured", "Pointer without evidence"]
    _evmissing = [w for w in _evwords if ("'%s'" % w) not in _evsrc]
    check("ev1 every badge the page can paint is spelled out, once, in one "
          "table - ten words for seven verdicts a run may cache and the three "
          "silences no run ever answers: %r missing" % (_evmissing,),
          not _evmissing and "const EVWORD={" in _evsrc)
    # THE ONE VOCABULARY WRITTEN IN TWO LANGUAGES, pinned rather than commented.
    # A word the ledger can cache and the page has no cell for renders through
    # the default arm, which is correct but silent; a word the page invents for a
    # verdict the schema does not have is a badge nothing can ever produce.
    _ev_schema_path = os.path.join(_output.PLUGIN_ROOT, "schema",
                                   "audit-plan.schema.json")
    with open(_ev_schema_path, encoding="utf-8") as _fh:
        _ev_schema = json.load(_fh)
    _ev_enum = (((_ev_schema.get("$defs") or {}).get("testEvidence") or {})
                .get("properties", {}).get("status", {}).get("enum") or [])
    _evword_block = _harness.between(_evsrc, "const EVWORD={", "};")
    _ev_uncovered = [w for w in _ev_enum
                     if ("'%s':" % w) not in _evword_block
                     and ("%s:" % w) not in _evword_block]
    # The three the PLAN answers rather than a run. They must NOT be schema
    # statuses: a manifest carrying `status: "no-gate"` would be a run claiming
    # to be a silence.
    _ev_plan_only = [k for k in ("none", "no-gate", "dangling") if k in _ev_enum]
    check("ev2 the badge table covers every status the SCHEMA lets a manifest "
          "cache (%r uncovered), and the three keys the page adds are the ones "
          "no run can report (%r wrongly in the enum) - a comment claiming two "
          "vocabularies agree is not a check" % (_ev_uncovered, _ev_plan_only),
          bool(_ev_enum) and not _ev_uncovered and not _ev_plan_only)
    check("ev3 an unrecognised verdict is NAMED rather than folded into "
          "'failed' - the schema leaves the enum open and says so, so the "
          "default arm humanises the word it did not recognise, and a run that "
          "cached no verdict says that instead of rendering the em dash "
          "`label('')` gives",
          " if(!k)return 'Verdict not recorded';" in _evsrc
          and "hasOwnProperty.call(EVWORD,k)" in _evsrc
          # ...and the humanised fallback is TYPE-CHECKED before it is painted.
          # `label` reads its own table with no own-property guard, so a status
          # word somebody typed into a manifest - `constructor`, `toString` -
          # comes back as a function off Object.prototype. Found by calling the
          # function in tools/ui-tests/evidence-badge.test.mjs, which no
          # substring pin could have found.
          and " return typeof word==='string'?word:k;}" in _evsrc
          # The negative, spelled as the two shapes a FOLD would take rather
          # than as the bare word: `EVORDER` legitimately lists `'failed'`, and
          # a negative on the word alone would have been red on arrival and
          # then loosened, which is how a check stops checking.
          and "||'failed'" not in _evsrc
          and ":'failed'" not in _evsrc)
    check("ev4 `ranTotal` IS THREE-VALUED. null is 'not knowable from this "
          "runner' and is emphatically not zero; only a positive zero earns 'no "
          "checks ran'. The words are the gate runner's own, so the panel and "
          "the terminal cannot describe one run two ways",
          "const evChecks=run=>run.ranTotal==null\n"
          " ?'check count not knowable from this runner'\n"
          " :(run.ranTotal===0?'no checks ran'" in _evsrc
          # The mutation this is here for: `!run.ranTotal` merges null into
          # zero, and `run.ranTotal?` merges zero into unknown.
          and "!run.ranTotal" not in _evsrc
          and "run.ranTotal?" not in _evsrc
          # ...and the MARKER answers the same question under the same
          # condition. This clause was added because a mutation that made the
          # marker unconditional survived every other case here: 'checks
          # unknown' beside a run that counted twelve is the same lie in a
          # different element.
          and "if(run.ranTotal==null)marks.push({text:'checks unknown',"
          in _evsrc)
    check("ev5 ...and one step down too: a step whose runner reports no count "
          "says so, where a step that ran and checked nothing shows its zero",
          "s.ran==null?'not knowable':String(s.ran)" in _evsrc
          and "s.ran||" not in _evsrc)
    check("ev6 `treeMutated` IS THREE-VALUED: null is 'no comparison was made', "
          "[] is a tree that was compared and is clean, a count is the finding. "
          "A TRUTHY TEST MERGES UNKNOWN INTO CLEAN, which is the defect this "
          "case exists for, so the null arm is FIRST and the finding arm reads "
          "a positive number",
          "if(run.treeMutated==null)marks.push({text:'tree unknown'" in _evsrc
          and "else if(run.treeMutated>0)marks.push({text:'tree mutated'" in _evsrc
          and "if(run.treeMutated)" not in _evsrc
          and "!run.treeMutated" not in _evsrc)
    check("ev7 ...and `coverage` the same way, where the middle value has its "
          "own sentence: a gate that ran and named none of this work's files is "
          "the third way a gate says nothing, not a clean bill",
          "if(run.coverage==null)marks.push({text:'coverage unknown'" in _evsrc
          and "else if(run.coverage===0)marks.push({text:'no overlap'" in _evsrc
          and "if(run.coverage)" not in _evsrc
          and "!run.coverage" not in _evsrc)
    check("ev8 every marker carries the BASIS that produced it, falling back to "
          "a sentence rather than to silence - 'unknown' with no reason beside "
          "it is the shape a reader cannot act on, and the ledger already holds "
          "all three",
          "why:run.treeBasis||" in _evsrc and "why:run.coverageBasis||" in _evsrc
          and "why:run.countsBasis||" in _evsrc
          and _evsrc.count("title:m.why") == 1)
    check("ev9 A BADGE IS THE STATUS AND THE MARKERS ARE BESIDE IT - two "
          "elements, two classes, never one word. A gate can fail AND rewrite "
          "the tree, and `run-test-gate.render` prints both for that reason",
          "el('span',{class:'st','data-evstatus':s.key||'unknown',title:s.why},"
          in _evsrc
          and "el('span',{class:'evmk','data-evmark':m.text,title:m.why}," in _evsrc
          # ...and `Passed` is the word alone. Nothing appends a check count to
          # it, so the badge cannot claim a check ran.
          and "passed:'Passed'" in _evsrc
          # A marker needs a run that MADE the observation: the three silences
          # carry none, and without this guard they render the contained
          # failure sentinel instead of their own sentence.
          and "function evMarks(run){\n if(!run)return [];" in _evsrc)
    check("ev10 the three silences are THREE BRANCHES WITH THREE SENTENCES, "
          "never one grey blob: no gate declared anywhere, a gate with no run "
          "recorded, and a pointer the ledger cannot answer. The middle one "
          "says out loud that it is not a failure",
          "?{key:'none',run:null," in _evsrc
          and ":{key:'no-gate',run:null," in _evsrc
          and "if(!run)return {key:'dangling',run:null," in _evsrc
          and "an absent record is not a failure." in _evsrc
          and "no test gate is declared here or on the phase" in _evsrc
          and "the evidence ledger does not hold it" in _evsrc)
    check("ev11 ...and the dangling sentence carries its BASIS - how many "
          "evidence files were read and how many lines could not be parsed - so "
          "a ledger that was never written and one that could not be understood "
          "are not the same claim, plus the verdict the plan had cached",
          "plural((ev&&ev.files)||0,'file read','files read')" in _evsrc
          and "plural((ev&&ev.unreadable)||0,'line unreadable',"
              "'lines unreadable')" in _evsrc
          and "The plan caches the verdict" in _evsrc)
    check("ev12 a run is decoded against the column names the SERVER shipped "
          "beside it, never against indices typed here - facts plus their "
          "field list is the Usage tab's shape, and a hand-written index is how "
          "a column added on one side reads as another on the other",
          "function evRow(row,fields){" in _evsrc
          and "(fields||[]).forEach((f,i)=>{out[f]=row[i];});" in _evsrc
          and "evRow(((ev||{}).runs||{})[rid],(ev||{}).fields)" in _evsrc
          and "evRow(raw,(STATE.evidence||{}).stepFields)" in _evsrc
          # ...and null for no row at all, never {}: an empty object answers
          # `undefined` to every three-valued read.
          and "if(!Array.isArray(row))return null;" in _evsrc)
    check("ev13 the feature is CONTAINED at its two doors, with a sentinel no "
          "real verdict can produce - a badge added to a table somebody opened "
          "for other reasons must not be able to blank the Overview, and a "
          "failure that renders like an answer is the silent pass this repo "
          "names",
          _evsrc.count("catch(cause){console.error('evidence badge failed for "
                       "'+id,cause);") == 1
          and _evsrc.count("catch(cause){console.error('evidence roll-up "
                           "failed',cause);") == 1
          and _evsrc.count("class:'evfail'") == 2
          and ".evfail{" in M.UI_HTML)
    _evdet_src = M.UI_HTML[M.UI_HTML.index("function ovDetail(p){"):
                           M.UI_HTML.index("function applyCardOrder(view){")]
    check("ev14 a phase shows BOTH measurements, LABELLED APART: its own "
          "sign-off run, and a roll-up over its tasks. One badge for the two "
          "would claim a measurement nobody made",
          "evLine('phase sign-off',pcell.badge)" in _evdet_src
          and "evLine('tasks',evRollCells(tasks,ev))" in _evdet_src
          and _evdet_src.count("evLine(") == 2
          and "const evLine=(lbl,...parts)=>el('div',{class:'evline'," in _evsrc)
    check("ev15 the roll-up counts the phase's OWN tasks and leads with what "
          "needs a human - EVORDER, which is OVORDER's rule one vocabulary "
          "over - and says so rather than showing an empty line when a phase "
          "has none",
          "function evTaskRoll(tasks,ev){" in _evsrc
          and "ovRank(EVORDER,a)-ovRank(EVORDER,b)" in _evsrc
          and "EVORDER=['failed'," in _evsrc
          and "'no tasks to count'" in _evsrc)
    check("ev16 which runs are OPEN rides OVF, keyed by subject id, so the 5s "
          "poll cannot fold a run somebody opened - and it is a second map "
          "rather than a second meaning for `open`, because the two nest",
          "OVF.evOpen[id]=!open;renderOver();" in _evsrc
          and "const open=!!OVF.evOpen[id];" in _evsrc
          # find(), not index(): a name that left OVF entirely must fail THIS
          # case rather than raise and strand every case below it.
          and 0 <= M.UI_HTML.find("evOpen:{}")
          < M.UI_HTML.find("function renderOver"))
    check("ev17 a subject with no recorded run is NOT a control - there is "
          "nothing to open, and a button onto an empty box is a promise the "
          "page cannot keep",
          "if(!s.run)return {badge:badge,detail:null};" in _evsrc
          and "'aria-expanded':open?'true':'false'," in _evsrc)
    check("ev18 the opened run prints what it answered AND the basis for what "
          "it could not, plus one row per step - and an empty step list is "
          "SAID, because a gate with no commands and a run whose steps nothing "
          "recorded look identical in an empty table",
          "'data-evbasis':pair[0]" in _evsrc
          and "'This run recorded no steps.'" in _evsrc
          and "tableHead(['step','exit','checks','took','outcome'])" in _evsrc)
    # TIMEZONE-PROOF, which the behavioural case in tools/ui-tests/dates.test.mjs
    # is not: it asserts that a day number is a whole number, and a
    # local-midnight parse is a whole number too on a UTC host. CI sets no TZ, so
    # its runner is UTC and that case passes either way. This one cannot: the
    # constructor is in the text.
    check("dates: a day number is built with Date.UTC, never by parsing the "
          "string - `new Date('2026-8-20')` is LOCAL midnight while the ledger's "
          "days are UTC dates, and the two differ by an offset that turns a day "
          "number into a fraction",
          # In shared/dates.js since the two heatmap calendars were factored -
          # a shared calendar cannot reach back into a surface for its own
          # primitives - which is why this reads the shared file's spacing.
          "const dnum = (d) => Date.UTC(+d.slice(0, 4), +d.slice(5, 7) - 1,"
          in M.UI_HTML
          # ...and the inverse formats through toISOString, which is UTC by
          # definition, so the round trip cannot drift.
          and "const dayIso = (n) => new Date(n * DAY_MS).toISOString()"
              ".slice(0, 10);" in M.UI_HTML
          # One constant, shared with the report rather than spelled again.
          and "const DAY_MS = 86400000;" in M.UI_HTML)
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
          # `focusBack` is reached through `restoreCaret` by the views that keep a
          # caret BY ID; the others call it directly. CAPTURE IS ONCE PER VIEW,
          # RESTORE IS ONCE PER EXIT, which is why these two no longer track
          # `focusKeep` one-for-one: Overview and Composition each return early
          # when there is no plan, and both of those empty states now carry a
          # settings link - a control the 5s poll would otherwise take the focus
          # off within five seconds. A view that stopped restoring anything still
          # drops one from each, which is what asserting both is for.
          and M.UI_HTML.count("focusBack(") == 6
          and M.UI_HTML.count("restoreCaret(") == 6   # one def, four tails, one early return
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
    # F102. A local write finishes faster than a person can see it, so a save with
    # no sentence after it is indistinguishable from a save that did nothing - and
    # it was reported as the question "does it save instantly, I see no loader".
    # The count was already here; `what` was spent only on the refusal sentence,
    # so the success one never said WHERE anything landed.
    #
    # Labelled as a property of the SOURCE on purpose: whether a reader sees the
    # sentence is the browser gates' question (capture-screenshots.mjs asserts
    # /^Saved · 1 change/ on the composition and settings saves, which is also why
    # the prefix has to stay at the FRONT of this string). What only source can
    # check is that one function composes all three clauses, so a sixth save
    # surface cannot report a different way.
    check("the save toast is built in one place from the count, the file it "
          "landed in, and whether it was recorded",
          "'Saved · '+plural(n,'change')+' to '+what+log" in M.UI_HTML
          # "not logged" only when a journal exists and refused: reporting the
          # absence of a feature as a failed save would cry wolf on every write.
          and "res.journaledWhy==='failed'?' · NOT logged':''" in M.UI_HTML
          # A caller's extra clause rides THAT toast. `toast` replaces the text of
          # one element, so a second call a statement later is the first message
          # deleted rather than a second message shown.
          and "+(hint?' — '+hint:''),diff?'warn':'ok');" in M.UI_HTML)
    # ...and the card that proved it: the theme save called showWriteResult and
    # then toasted again, so the only save surface with something more to say was
    # the one whose result was never on screen. The window is the theme Save
    # handler's tail; an endpoint that stops resolving RAISES here, which is the
    # outcome to want - a slice that silently re-anchors would go on passing about
    # a different span.
    _thtail = M.UI_HTML[M.UI_HTML.index("showWriteResult('#look',res,rows,'the theme'"):]
    _thtail = _thtail[:_thtail.index("'Save theme')")]
    check("a save reports exactly once - the theme card hands its extra clause "
          "to the same toast instead of firing a second one",
          "toast(" not in _thtail
          and "'reload to see the report wear it too'" in _thtail)
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
    # ...and now there is ONE helper, so what source text is the right instrument
    # for is narrower again: that each surface reaches it, by name, and that the
    # dead state and the count live inside it rather than in four callers. Whether
    # a Discard is actually dead on a freshly loaded page is behaviour, and
    # `assertSavebarCensus` reads it off the rendered document; the helper's own
    # cases are in tools/ui-tests/discard-footer.test.mjs.
    check("every writable surface builds its Discard through the one helper, "
          "and the dead state is the helper's to keep",
          "discardButton({key:'guards'" in M.UI_HTML
          and "discardButton({key:'comp'" in M.UI_HTML
          and "discardButton({key:'ado'" in M.UI_HTML
          and "discardButton({key:'policy'" in M.UI_HTML
          and "'data-discard':o.key" in M.UI_HTML
          # The count and the dead state, in one place and reachable by callers
          # on every keystroke that lands in the view.
          and "function refreshDiscard(b,n){\n offState(b,!n);" in M.UI_HTML
          and "b.textContent=n?('Discard '+plural(n,'change')):'Discard';"
              in M.UI_HTML
          # ...and no caller sets either any more.
          and "offState(discard," not in M.UI_HTML
          and "discard.textContent=" not in M.UI_HTML)

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

    # ov (P2/4): the outcome was on EVERY row, and across rows it is near-identical
    # prose - it doubled the row height and separated nothing. It moved to the row's
    # tooltip and to the head of the opened detail. The risk the removal carries is
    # that the SEARCH still reaches the outcome, so a row can be in a filtered list
    # because of a field the row no longer draws: a claim with its basis off screen.
    # The behaviour of the two helpers below is executed in
    # tools/ui-tests/overview-outcome.test.mjs; these are the source properties
    # that suite and the browser gate depend on.
    check("ovo1 no row carries an UNCONDITIONAL outcome line - that is the defect, "
          "and one call site left behind reintroduces it on every row",
          "p.desiredOutcome?el('span',{class:'ovout'" not in M.UI_HTML
          and ".ovout{" in M.UI_HTML)
    check("ovo2 the row's tooltip carries it, so hovering still answers what the "
          "phase is for without opening anything",
          "title:(open?'collapse ':'expand ')+p.id\n"
          "      +(p.desiredOutcome?' \u2014 '+p.desiredOutcome:'')," in M.UI_HTML)
    check("ovo3 a row that matched on the outcome ALONE shows it, windowed on the "
          "hit - the line is clipped to one line, so the head of an outcome is no "
          "proof the term the reader typed is on screen",
          "ovOutcomeIsBasis(p,term)?el('span',{class:'ovout','data-ovhit':'outcome',"
          in M.UI_HTML
          and "+ovExcerpt(p.desiredOutcome,term,64)):null);" in M.UI_HTML)
    # The two spellings of "which fields does the row draw" must be ONE, or the
    # filter can match on a field the basis test believes is visible - and then the
    # row is in the list with nothing on it carrying the term. There is no second
    # list: the filter reads ovShownText too.
    _ovfields = M.UI_HTML.count("(p.id+' '+(p.title||'')+' '+(p.area||[]).join(' ')")
    check("ovo4 the visible-field list exists ONCE and the search filter reads it, "
          "rather than spelling it out a second time",
          _ovfields == 1
          and "const ovShownText=p=>(p.id+' '+(p.title||'')+' '" in M.UI_HTML
          and "const hitP=p=>(!term||(ovShownText(p)+' '" in M.UI_HTML,
          repr(_ovfields))
    _ovdet = M.UI_HTML[M.UI_HTML.index("function ovDetail(p){"):
                       M.UI_HTML.index("function applyCardOrder(view){")]
    # find(), not index(): a detail that lost the line entirely must FAIL this case
    # rather than raise and take every case below it with it. And counted, because
    # index() reads the first hit - a second copy appended after the table is two
    # answers to one question and passed an ordering assertion.
    _ovpos = _ovdet.find("'Desired: '+p.desiredOutcome")
    _ovtab = _ovdet.find("tableHead([")
    check("ovo5 ...and the opened detail LEADS with the outcome, ONCE, above the "
          "task table: read after its tasks it is a footnote to them",
          _ovdet.count("'Desired: '+p.desiredOutcome") == 1
          and 0 <= _ovpos < _ovtab,
          repr((_ovpos, _ovtab)))
    check("ovo6 the search box still says it reaches the outcome, which is what "
          "makes the basis line owed rather than decorative",
          "id, title, area, outcome" in M.UI_HTML)
    check("overview: sort and group-by-area consume the rollup's own areas registry",
          # Through fillOptions since the five plain option loops became one; the
          # pair list is what identifies THIS select.
          "[['plan','plan order'],['progress','progress'],\n   "
          "['status','status'],['priority','priority']]"
          in M.UI_HTML
          and "OVF.byArea=cb.checked" in M.UI_HTML and "r.areas[tag]" in M.UI_HTML)
    # --- phase priority (the control, the badge, and the one shared number) ---
    check("pri1 the Composition tab offers a priority control per phase, and the "
          "value it sends is a NUMBER or null - a string tier would be refused by "
          "the write path, and the dialog would have promised it",
          "'data-priority':ph.id||''" in M.UI_HTML
          and "pp.priority=prio.value?Number(prio.value):null" in M.UI_HTML)
    check("pri2 ...and the phase patch is ONE object both controls write into. "
          "The old spelling replaced it on every keystroke, which was correct "
          "with a single control and silently drops the other now there are two",
          "const setRev=v=>{pp.reviewModel=v||null;patch.phases[ph.id]=pp;};"
          in M.UI_HTML
          and "patch.phases[ph.id]={reviewModel:" not in M.UI_HTML)
    check("pri3 the range comes from the config, then from the DEFAULTS the "
          "server hands over - not from a literal in the browser",
          "const cfg=((STATE||{}).config||{}).priority||{};" in M.UI_HTML
          and "const def=((STATE||{}).defaults||{}).priority||{};" in M.UI_HTML)
    check("pri4 THE ONE VALUE WRITTEN IN TWO LANGUAGES: prioMax()'s last-resort "
          "literal IS `hooks/_config.py`'s shipped maxTier. A comment claiming "
          "two implementations agree is not a check; this is",
          " return %d;}" % (_loader.load_hooks_config(modname="audit__config")
                            .DEFAULTS["priority"]["maxTier"],) in M.UI_HTML,
          repr(_loader.load_hooks_config(modname="audit__config")
               .DEFAULTS["priority"]["maxTier"]))
    check("pri5 a tier ABOVE the maximum is still offered, because nothing is "
          "clamped - a control that dropped it would silently unpin the phase on "
          "the next save",
          "if(ph.priority!=null&&ph.priority>maxTier)" in M.UI_HTML)
    check("pri6 the Overview badge says what the tier buys AND what it does not. "
          "'priority 1' on its own reads as 'skips the queue', which is the one "
          "thing it never does",
          "'priority '+p.priority" in M.UI_HTML
          and "runs first among the tasks that are ALREADY ready" in M.UI_HTML)
    check("pri7 the confirm dialog computes a priority row, so the client's list "
          "and the server's echo stay two readings of one pair of values",
          "if(('priority' in pv)&&!cfSame(p.priority,pv.priority))" in M.UI_HTML)
    # A PROPERTY OF THE SOURCE, and source text is the only instrument for it:
    # that the Overview's priority sort is one subtraction of a server-computed
    # rank and holds no rule of its own. It is NOT a claim that the sort works -
    # `tools/ui-tests/phase-order.test.mjs` runs that, and the shape a second
    # comparator would take is caught by name by `_deps.SHARED_CONCERNS`'s
    # "phase execution order" row. Counted rather than found: `index()` reads the
    # first hit, and a second sort appended elsewhere would be two answers to one
    # question with this assertion still green.
    check("pri8 the Overview sorts phases by `porder` - the number "
          "`_priority.ranks` computed, the same one the report stamps as "
          "`data-porder` - so the client is handed the order and never the rule",
          "else if(OVF.sort==='priority')ordered.sort((a,b)=>a.porder-b.porder);"
          in M.UI_HTML
          and M.UI_HTML.count("a.porder-b.porder") == 1,
          repr(M.UI_HTML.count("a.porder-b.porder")))
    # PROPERTIES OF THE SOURCE, not of the painted box: only the browser gates can
    # say the four controls line up. What source text CAN say is that one rule
    # decides their shape and that no width is declared twice - which is the thing
    # that was missing, since the priority menu shipped with no rule at all and
    # its <select> took the base control's size while the input beside it had been
    # sized by hand.
    #
    # It is THREE selectors for four fields now, and that is the change rather
    # than a loosening: a task's model box and a phase's review box are in the
    # same COLUMN, so `td.tmodel input` is both of them and the pair cannot drift
    # by construction instead of by two declarations agreeing. The width that used
    # to be a per-wrapper `--comp-ctl-w` parameter is a column property, so the
    # count clauses move with it - one declaration per column, and the parameter
    # gone rather than left behind unread.
    # The composition table's own block, so a count below is a count of THIS
    # table's rules rather than of the whole assembled sheet - where `input{width:`
    # appears in several components that have nothing to do with this one.
    _comp_css = M.UI_HTML[M.UI_HTML.index("/* composition: filter toolbar"):
                          M.UI_HTML.index(".comp .combo{flex:")]
    check("pri9 EVERY editable field of this table gets its box shape from one "
          "rule, and each column its width from ONE declaration - they were "
          "sized by hand or not at all, which is how a 41px skills box and a "
          "37px priority menu ended up beside a 30px model box. Counted per "
          "column rather than to a total, so adding a column extends the list "
          "here instead of quietly loosening it",
          "td.tmodel input,td.tskills input,td.phprio select,"
          "td.phparent :is(select,input){"
          in M.UI_HTML
          # Counted, not merely present. A `not in` on `td.phprio select{width:`
          # reads like the negative to write here and is worthless: the shared
          # rule's own selector list ENDS with `td.phprio select` and is followed
          # by `{`, so the clause would match the very thing it was meant to
          # forbid and could never fail. These count the structure instead.
          and M.UI_HTML.count("td.tmodel input{width:") == 1
          and M.UI_HTML.count("td.phprio select{width:") == 1
          # The parent column's menu and its number box are ALTERNATIVES in one
          # cell, never a pair, so they share the column's single declaration -
          # which is why this is one selector and not two.
          and M.UI_HTML.count("td.phparent :is(select,input){width:") == 1
          # ...and counted over the TABLE'S OWN BLOCK as well, because the
          # clauses above only forbid a second rule with the same selector. A
          # second width under a different selector is how the pair drifted
          # before, and it would be written here, next to the first. The block
          # holds exactly the per-column declarations named above and nothing
          # else, which is what these three totals say.
          and _comp_css.count("input{width:") == 1
          and _comp_css.count("select{width:") == 1
          and _comp_css.count(":is(select,input){width:") == 1
          # The parameter is GONE, not merely unused: a stranded custom property
          # is a second opinion about a width nothing reads.
          and "--comp-ctl-w" not in M.UI_HTML)
    # WHAT THIS PIN USED TO HOLD, and why the clause changed with the mechanism.
    # It read `flex:0 0 auto` inside the two wrappers, because both controls were
    # flex items in the phase row's own line and a flex item shrinks by default:
    # P8's title in this repo's own plan squeezed the review group to 175px for
    # 184px of content and the difference painted over the control beside it. The
    # wrappers are gone - the controls are table cells now, and a column cannot be
    # eaten by the content of another column - so the clause it asserted no longer
    # exists to assert.
    #
    # The BEHAVIOUR it was named for (a long title takes its room out of itself)
    # is measured where it can be: `assertCompositionColumns` in
    # tools/ui-checks/stage-tabs.mjs injects one and reads the column and table
    # widths. What is left here is the source property that browser check cannot
    # state - that there is ONE builder per row type and each emits one cell per
    # heading, so a sixth cell cannot appear in one row type alone.
    def _split_top(src):
        """`src` split on the commas at nesting depth zero, quote-aware.

        `src.split(",")` would cut inside every one of these entries - each is an
        object holding a `flabel(...)` call holding its own object - and would
        report a column count that grows with how ornate a heading is.

        NOT comment-aware, unlike `_ir_call` below, and that is a decision: a
        `//` comment inside the head array would read as an extra column here
        and this case would say so out loud, which is the direction a miscount
        should fail in. The remedy is to write the comment above the call, where
        the page already keeps it.
        """
        _out, _start, _d, _q, _k = [], 0, 0, "", 0
        while _k < len(src):
            _c = src[_k]
            if _q:
                if _c == "\\":
                    _k += 2
                    continue
                if _c == _q:
                    _q = ""
            elif _c in "'\"`":
                _q = _c
            elif _c in "([{":
                _d += 1
            elif _c in ")]}":
                _d -= 1
            elif _c == "," and _d == 0:
                _out.append(src[_start:_k].strip())
                _start = _k + 1
            _k += 1
        _tail = src[_start:].strip()
        if _tail:
            _out.append(_tail)
        return _out

    # The head, read out of the page rather than counted here: a number written
    # in this file would be a second statement of how wide the table is, free to
    # agree with neither builder. `tableHead([` takes one entry per column, and
    # the entries are separated at depth 1 of that array.
    _comp_head_src = M.UI_HTML[M.UI_HTML.index("tableHead(['id','title','status'"):]
    _comp_head_cols = _split_top(_comp_head_src[
        _comp_head_src.index("[") + 1:_comp_head_src.index("]),tbody")])
    check("pri10a the head is read off the page, and it is the id/title/status "
          "trio plus one entry per editable column - the number this file "
          "compares both row builders against, so nothing here holds a second "
          "opinion about how wide the table is: %d column(s)"
          % (len(_comp_head_cols),),
          len(_comp_head_cols) >= 4
          and _comp_head_cols[:3] == ["'id'", "'title'", "'status'"]
          and len([c for c in _comp_head_cols if "flabel(" in c])
          == len(_comp_head_cols) - 3,
          repr(_comp_head_cols))
    _comp_prow = M.UI_HTML[M.UI_HTML.index("const pr=el('tr',{class:'phase'"):
                           M.UI_HTML.index("pr.onclick=")]
    _comp_trow = M.UI_HTML[M.UI_HTML.index("const tr=el('tr',{class:'task'"):
                           M.UI_HTML.index("const tFrozen=")]
    check("pri10 both row builders emit one cell per heading, and nothing in "
          "this table spans - a phase row that SPANS the grid does not sit in "
          "it, which is how its two controls came to be under 'model' and "
          "'skills' by arithmetic rather than by belonging to them. The two "
          "counts are compared to EACH OTHER as well as to the head, because "
          "the failure a sixth column invites is one builder gaining a cell and "
          "the other not - which shifts every cell after it into the wrong "
          "column while both rows still look plausible",
          _comp_prow.count("el('td',") == _comp_trow.count("el('td',")
          == len(_comp_head_cols)
          and "colspan" not in _comp_prow
          and "colspan" not in _comp_trow
          and "el('td',{class:'tmodel'},revCombo)" in _comp_prow
          and "el('td',{class:'phprio'},prio)" in _comp_prow
          # A task has no lever of its own in this column - it inherits its
          # phase's tracking and its parent IS the phase's work item - so its
          # cell is EMPTY, and empty is the answer, not a missing cell.
          #
          # The sixth cell holds TWO phase levers now, and their ORDER is part
          # of the claim: `at` is above `ap` because where a phase hangs is a
          # question only once it belongs on the board at all.
          and "el('td',{class:'phparent'},at,atLine,ap,apId,apBoard,apNote)"
          in _comp_prow
          and "el('td',{class:'phparent'})" in _comp_trow,
          repr((_comp_prow.count("el('td',"), _comp_trow.count("el('td',"),
                _comp_head_cols)))
    # The head names the column, and column five holds two levers that can never
    # appear in the same row - so "skills" alone described half the table. The
    # cell INDEX is a browser claim (assertCompositionColumns); the words are
    # source, and this is the only place they exist.
    check("pri10b the fifth heading names BOTH of the things its column holds",
          "flabel('skills · priority',MDESC.taskSkills,{comp:'taskSkills',"
          in M.UI_HTML)
    # The reading order and the freeze both hang off ONE classifier. Pinning the
    # reuse is the point: a second done/cancelled list inside the composition tab
    # would be free to disagree with the Overview and the report about a status,
    # and the disagreement would show as a phase that is editable on one screen
    # and frozen on another.
    # --- ap: where a phase hangs on the board (phases[].adoParent) -------------
    # THE CONTROL IS IN THE PHASE ROW AND NOT ON THE CONNECTOR CARD, and that is
    # a fact about what each save can write rather than a layout preference:
    # `PUT /api/ado` replaces `meta.ado` and nothing else, so a per-phase edit
    # offered there would be a card describing a write it cannot make. The card
    # holds the FALLBACK id; the row holds the phase's own answer.
    check("ap1 the phase row carries an adoParent SELECT whose four kinds of "
          "option are the three stored states plus a typed id - the cached list "
          "is a convenience, so naming an id by hand can never stop being "
          "possible",
          "'data-adoparent':ph.id||''" in M.UI_HTML
          # F211 reordered this label: it used to open with `use the fallback — `
          # and spend the whole 9rem budget before reaching the id, so a
          # truncation lost the one thing the option is about.
          and "['fallback','fallback: '+apFallbackWords(c.fallback)]"
          in M.UI_HTML
          and "['none','none — uncategorised on purpose']" in M.UI_HTML
          and "['other','other id…']" in M.UI_HTML
          and "...(c.candidates||[]).map(x=>[String(x.id),apCandidateLabel(x)])"
          in M.UI_HTML)
    check("ap2 THE ONE VALUE WRITTEN IN TWO LANGUAGES: the marker the browser "
          "sends for 'no declaration' IS `_ado_parent`'s own key. A comment "
          "claiming the two agree is a comment; this is the check",
          "function apUseFallback(){return{%s:true};}" % (_adop._USE_FALLBACK_KEY,)
          in M.UI_HTML
          and "v.%s===true" % (_adop._USE_FALLBACK_KEY,) in M.UI_HTML,
          repr(_adop._USE_FALLBACK_KEY))
    check("ap3 the fallback option NAMES what it resolves to, and says so "
          "outright when nothing is set - an option that read the same either "
          "way would ask the reader to remember a number kept on another card",
          "return (fb&&fb.id!=null)?('#'+fb.id)" in M.UI_HTML
          and "'nothing is set (meta.ado.parentWorkItem is empty)'" in M.UI_HTML)
    check("ap4 an id the cache does not carry still SHOWS as that id: the "
          "choice degrades to 'other' with the box filled, because a parent "
          "named before the last fetch must not read as 'use the fallback'",
          "return (candidates||[]).some(c=>c.id===id)?String(id):'other';"
          in M.UI_HTML
          and "apId.hidden=(apChoice!=='other');" in M.UI_HTML)
    check("ap5 an UNFINISHED edit is said out loud rather than written as "
          "nothing: 'other id…' with an empty box drops the key AND paints the "
          "reason, which is the difference between a control that declines and "
          "one that silently does nothing",
          "if(out.write)pp.adoParent=out.value;else delete pp.adoParent;"
          in M.UI_HTML
          and "apNote.textContent=out.why;" in M.UI_HTML
          and "nothing is saved for '" in M.UI_HTML)
    check("ap6 a CANDIDATE pick carries the cache's basis and its moment, and a "
          "TYPED id carries neither - nobody looked at a typed id, and a stamp "
          "saying otherwise would be provenance invented for somebody else's "
          "record",
          "return{write:true,value:{id:n,source:'declared'},why:''};" in M.UI_HTML
          and "if((cache||{}).fetchedAt)d.observedAt=cache.fetchedAt;" in M.UI_HTML)
    check("ap7 the confirm dialog computes an adoParent row against the value "
          "the payload carries - the marker for an absent declaration, never "
          "undefined - so this side and the server's echo compute one `from`",
          "if(('adoParent' in pv)&&!cfSame(p.adoParent,pv.adoParent))"
          in M.UI_HTML)
    check("ap8 ...and the dialog renders the two values that would otherwise "
          "read as 'not set': null is the DECLARED nowhere and the marker is "
          "the absence of a declaration, and those are the two answers that "
          "differ most",
          "'none — uncategorised on purpose (null)'" in M.UI_HTML
          and "'use the fallback (meta.ado.parentWorkItem)'" in M.UI_HTML)
    # WHICH OF THE TWO EMPTIES, once, from the server. "nobody has fetched a
    # list" and "this board has no parent-shaped item" both reach a picker as
    # zero options, and the defect is rendering them the same - a filter
    # narrowed to nothing reading as all-clear.
    check("ap9 the candidate cache's state is painted with the SERVER's own "
          "sentence and carries the state as an attribute, so a browser gate "
          "can read which of the three it is without parsing prose",
          "'data-apcache':(comp.adoParents||{}).cache||'absent'" in M.UI_HTML
          and "(comp.adoParents||{}).basis||''" in M.UI_HTML
          # ONE copy: the legend's whole reason is that a per-phase sentence is
          # fifty copies of one sentence.
          and M.UI_HTML.count("'data-apcache'") == 1,
          repr(M.UI_HTML.count("'data-apcache'")))
    # --- ap: and what the BOARD says, which the cell used to leave out (F101) --
    # A PROPERTY OF THE SOURCE, and text is the right instrument for exactly one
    # part of it: that no two board states share a rendering. The defect was two
    # different facts painting the same pixels - a phase the board agrees with
    # and a phase nobody has compared - so "these four strings exist and there
    # are four of them" is the claim. What a person SEES is a browser claim and
    # is not made here.
    _apb_words = ["'board: #'", "'board: no work item yet'",
                  "'board: not asked'", "'board: not reported'"]
    check("ap10 every board state renders WORDS OF ITS OWN, counted rather than "
          "found: the fault this line exists for is two states painting one "
          "cell, so a branch that fell back to a neighbour's wording would be "
          "the same defect with more code",
          all(w in M.UI_HTML for w in _apb_words)
          and M.UI_HTML.count("'board: ") == len(_apb_words),
          repr((M.UI_HTML.count("'board: "),
                [w for w in _apb_words if w not in M.UI_HTML])))
    check("ap11 the state a gate reads and the words a person reads come from "
          "ONE list through ONE normaliser - an attribute taken straight off "
          "`.state` could name a state the words had already fallen back from, "
          "and the two would disagree about the same row",
          "const AP_BOARD=['unlinked','observed','never-asked'];" in M.UI_HTML
          and M.UI_HTML.count("const AP_BOARD") == 1
          and M.UI_HTML.count("AP_BOARD.includes(") == 1
          and "const st=apBoardState(b);" in M.UI_HTML
          and "'data-apboard':apBoardState(ph.adoParentBoard)" in M.UI_HTML
          and M.UI_HTML.count("'data-apboard'") == 1,
          repr((M.UI_HTML.count("const AP_BOARD"),
                M.UI_HTML.count("AP_BOARD.includes("),
                M.UI_HTML.count("'data-apboard'"))))
    check("ap12 the board line is written ONCE at render and no edit path "
          "rewrites it: a save moves the DECLARATION, and nothing typed in this "
          "panel can move where somebody's board hangs a card - a control that "
          "repainted it on change would be reporting an edit as an observation",
          M.UI_HTML.count("apBoard=") == 1
          and "apBoard" not in M.UI_HTML[M.UI_HTML.index("const apApply=()=>{"):
                                         M.UI_HTML.index("apId.hidden=(apChoice")],
          repr(M.UI_HTML.count("apBoard=")))
    # A COMPUTED pin, and the only kind that can hold this: the claim is that two
    # declarations carry the SAME width, and a literal on either side would go on
    # passing while the other moved. `.apnote` is a block inside `td.phparent`, so
    # in an auto-layout table its cap is what the column's max-content becomes
    # whenever the note is the widest thing in the cell - and the rule above it
    # measured 9rem as the whole budget this column has, at 1200px, with the table
    # already filling its frame exactly. The note used to be capped wider, which
    # was harmless only while its one wearer was empty until somebody typed into
    # the control; a board line is painted on every row at first paint, and
    # `board: #N · seen YYYY-MM-DD` is long enough to reach the old cap.
    _apn_ctl = re.search(r"td\.phparent :is\(select,input\)\{width:([^}]+)\}",
                         M.UI_HTML)
    _apn_note = re.search(r"\.apnote\{[^}]*max-width:([^;}]+)[;}]", M.UI_HTML)
    check("ap13 the note under the parent control is capped at the CONTROL's "
          "own width, so nothing written under that control can size the column "
          "wider than the control does. No selftest can see the overflow itself "
          "- a layout that overflows is still a layout that parses - which is "
          "exactly why the agreement is pinned instead",
          bool(_apn_ctl) and bool(_apn_note)
          and _apn_ctl.group(1).strip() == _apn_note.group(1).strip(),
          repr((_apn_ctl and _apn_ctl.group(1), _apn_note and _apn_note.group(1))))
    check("ap14 the lever's HELP names the second line and says it cannot be "
          "edited, which is the one thing the cell itself cannot say: two muted "
          "lines under one control, one of them a reason a save was refused and "
          "the other an observation no save can move, and only the help "
          "distinguishes them for somebody who has not read the source",
          "board" in M.COMPOSITION_HELP["phaseAdoParent"].lower()
          and "not editable" in M.COMPOSITION_HELP["phaseAdoParent"]
          and "function apBoardWords(b)" in M.UI_HTML)
    # --- at: whether a phase is on the board at all (phases[].adoTracked) ------
    # THE LEVER ABOVE THE PARENT IN THE SAME CELL, and the order is the claim:
    # where a phase hangs is a question only once it belongs on the board. What
    # is asserted below is what SOURCE can hold - that the three-valued answer
    # is read by identity, that no two answers share a rendering, and that the
    # declaration is offered as a declaration. What a person SEES is a browser
    # claim and is not made here.
    check("at1 the phase row carries an adoTracked SELECT offering the three "
          "answers a PERSON can give - and none of them is cached, fetched or "
          "scoped, which is why unlike the parent menu the three are fixed",
          "'data-adotracked':ph.id||''" in M.UI_HTML
          and "['default',AT_DEFAULT_WORDS]" in M.UI_HTML
          and "['true','on the board']" in M.UI_HTML
          and "['false','off the board']" in M.UI_HTML
          and M.UI_HTML.count("'data-adotracked'") == 1,
          repr(M.UI_HTML.count("'data-adotracked'")))
    check("at2 THE THREE-VALUED ANSWER IS READ BY IDENTITY, never by "
          "truthiness: null means nothing here has a basis, and a falsy read "
          "would file it under 'not on the board' - a claim nobody made, and "
          "the exact collapse this key was added to undo",
          "const t=(r||{}).tracked;" in M.UI_HTML
          and "if(t===true)return AT_ANSWERS[0];" in M.UI_HTML
          and "if(t===false)return AT_ANSWERS[1];" in M.UI_HTML
          and "if(t===null)return AT_ANSWERS[2];" in M.UI_HTML
          # A value outside the three is a DEFECT and not an old server - the
          # payload comes from the process serving this page - so it reports
          # itself rather than borrowing the commonest answer's word.
          and "return 'not-reported';}" in M.UI_HTML)
    check("at3 the answer a gate reads and the words a person reads come from "
          "ONE list through ONE normaliser - AP_BOARD's arrangement, for the "
          "same failure: an attribute taken straight off `.tracked` could name "
          "an answer the words had already fallen back from",
          "const AT_ANSWERS=['tracked','untracked','unanswered'];" in M.UI_HTML
          and M.UI_HTML.count("const AT_ANSWERS") == 1
          and M.UI_HTML.count("const a=atAnswer(r);") == 1
          and "'data-atstate':atAnswer(ph.adoTrackedResolved)" in M.UI_HTML
          and M.UI_HTML.count("'data-atstate'") == 1,
          repr((M.UI_HTML.count("const AT_ANSWERS"),
                M.UI_HTML.count("'data-atstate'"))))
    # A PROPERTY OF THE SOURCE, ap10's claim for this lever: that no two answers
    # paint the same line. Counted rather than found, because a branch falling
    # back to a neighbour's wording is the same defect with more code.
    _at_words = ["'tracking: not answered — nothing here has a basis'",
                 "'tracking: not reported'", "'tracking: '+(a==='tracked'",
                 "'tracking: unsaved edit · saved: '"]
    check("at4 every answer renders WORDS OF ITS OWN, and so does an unsaved "
          "edit - counted rather than found, because two answers painting one "
          "line is the whole fault class this lever was added to end",
          all(w in M.UI_HTML for w in _at_words)
          and M.UI_HTML.count("'tracking: ") == len(_at_words),
          repr((M.UI_HTML.count("'tracking: "),
                [w for w in _at_words if w not in M.UI_HTML])))
    check("at5 the line says WHAT THE ANSWER CAME FROM, which is half the "
          "sentence: an absent declaration and `true` are ONE answer from two "
          "places, so a line printing only the answer would show the default "
          "as if somebody had chosen it. The qualifier is read off the "
          "DECLARATION and never off the rule, so it can only qualify",
          "const how=(decl===true||decl===false)?'declared':'the default';"
          in M.UI_HTML
          and "atWords(ph.adoTrackedResolved,ph.adoTracked)" in M.UI_HTML)
    check("at6 `null` IS THE CLEAR here and it is a VALUE one control down - "
          "the difference is the schema typing this field boolean, so null is "
          "not a value it can hold. Absent reaches the row as null and null is "
          "what a save sends to put it back, which is what makes the round "
          "trip readable rather than a marker to remember",
          "if(choice==='default')return{write:true,value:null,why:''};"
          in M.UI_HTML
          and "if(decl===null||decl===undefined)return 'default';" in M.UI_HTML)
    check("at7 a stored value that is NEITHER true nor false lands on an "
          "option of its own that WRITES NOTHING and says why - a menu showing "
          "it as 'no declaration' would paint the default over somebody's "
          "attempt to keep a phase off a shared board, which is the one "
          "direction that puts work on it",
          "return AT_UNREADABLE;}" in M.UI_HTML
          and "[AT_UNREADABLE,'unreadable value']" in M.UI_HTML
          and "if(out.write)pp.adoTracked=out.value;else delete pp.adoTracked;"
          in M.UI_HTML
          and "neither true nor false — pick one " in M.UI_HTML)
    check("at8 an EDIT never recomputes the answer - it says it is unsaved and "
          "goes on quoting the saved one. The resolution is the server's, and "
          "a browser deriving it would be the second implementation of the one "
          "rule this key exists to have exactly one of; a line that kept "
          "showing the saved answer beside a changed menu would be the "
          "stale-reads-as-current defect one lever down (F101)",
          "at.value===atChoice?atSaved:('tracking: unsaved edit · saved: '"
          in M.UI_HTML
          and M.UI_HTML.count("atSaved=atWords(") == 1
          # ONE writer of that line: the render sets it and `atApply` replaces
          # it, and nothing else may.
          and M.UI_HTML.count("atLine.textContent=") == 1,
          repr(M.UI_HTML.count("atLine.textContent=")))
    check("at9 the lever has a reference OF ITS OWN, in the legend rather than "
          "the head - a <th> carries one ⓘ and this column now holds two phase "
          "levers - and the help says what the muted line is and that it is not "
          "editable, which is the one thing the cell itself cannot say",
          "{comp:'phaseAdoTracked'" in M.UI_HTML
          and _help.COMPOSITION_PATHS.get("phaseAdoTracked")
          == "phases[].adoTracked"
          and "not editable" in M.COMPOSITION_HELP["phaseAdoTracked"]
          # The two things a reader cannot get from the cell: which way an
          # absent declaration goes, and that a task has no lever of its own.
          and "default" in M.COMPOSITION_HELP["phaseAdoTracked"]
          and "inherit" in M.COMPOSITION_HELP["phaseAdoTracked"],
          repr(_help.COMPOSITION_PATHS.get("phaseAdoTracked")))
    # A SOURCE PROPERTY, and the only instrument for it: that the two controls
    # in this cell are declared to STACK. The column is capped at one control's
    # width because the browser gate measured the table filling its frame
    # exactly at 1200px, so a second control BESIDE it scrolls the panel
    # sideways - and no selftest can see that, because a layout that overflows
    # is still a layout that parses.
    check("at10 the two levers sharing this cell are stacked by a RULE, not by "
          "whatever happens to sit between them: a block element separates "
          "them today, and the day that line moves the controls would still "
          "have to stack or the column takes the table past its frame",
          "td.phparent select[data-adotracked]{display:block}" in M.UI_HTML
          and M.UI_HTML.count("td.phparent select[data-adotracked]") == 1)
    check("at11 THE FIELD NAME IS WRITTEN IN TWO LANGUAGES AND THIS IS THE "
          "CHECK: the key the browser puts in the patch, the key it computes a "
          "dialog row for and `_ado_tracked.FIELD` are one string. A comment "
          "saying they agree is a comment - and if they ever did not, the "
          "dialog would list nothing for a real change and the echo would then "
          "report the save as drift against a dialog that never looked",
          "pp.%s=out.value;else delete pp.%s;" % (_adot.FIELD, _adot.FIELD)
          in M.UI_HTML
          and "if(('%s' in pv)&&!cfSame(p.%s,pv.%s))"
          % (_adot.FIELD, _adot.FIELD, _adot.FIELD) in M.UI_HTML
          and "rows.push(cfRow(pid,'%s'," % (_adot.FIELD,) in M.UI_HTML,
          repr(_adot.FIELD))
    check("at12 ...and the dialog renders THIS field's null as what it is - "
          "the ABSENCE of a declaration, which resolves to tracked. It is the "
          "third meaning of null in one dialog (skills: opted out, adoParent: "
          "the declared nowhere) and the only one whose absence has a "
          "consequence, so 'not set' would leave the reader to work out which "
          "way it goes",
          "if(none&&field==='%s')" % (_adot.FIELD,) in M.UI_HTML
          # ONE SENTENCE, TWO READERS: the menu offers the option and the dialog
          # renders the value, and the literal exists once - so the two cannot
          # come to disagree about which way an absent declaration goes. The
          # identifier is what both sites carry.
          # TWO WIDTH BUDGETS, ONE ANSWER, AND THE LONG FORM IS DERIVED. The
          # menu sits in a 9rem select and the dialog has a whole row; one
          # sentence in both clipped the closed control to `no declaration — t`,
          # which a screenshot showed and no substring pin could. So the short
          # words are the constant and the sentence is BUILT from them - the
          # concatenation is what makes a disagreement about direction
          # unspellable, which is what the single literal used to buy.
          and "const AT_DEFAULT_WORDS='no declaration';" in M.UI_HTML
          and "const AT_DEFAULT_SENTENCE=AT_DEFAULT_WORDS+"
              "' — tracked, the default';" in M.UI_HTML
          and M.UI_HTML.count("' — tracked, the default'") == 1
          # Both readers named, rather than counted: an identifier is a word a
          # comment may also carry, and a count over the page would be pinning
          # how the prose beside it is worded.
          and "['default',AT_DEFAULT_WORDS]" in M.UI_HTML
          and "el('span',{class:'cfv '+cls+' unset'},AT_DEFAULT_SENTENCE)"
          in M.UI_HTML,
          repr(M.UI_HTML.count("' — tracked, the default'")))
    # F211. BOTH selects in the phase cell must be filled THROUGH the width
    # bound, and this is a property of the assembled text rather than of any
    # function's behaviour - so it is pinned here and deliberately not in
    # `ado-panel.test.mjs`, whose point is running the code instead of re-reading
    # it. The failure it guards is silent by construction: a control left
    # unbounded paints a clipped label while every other pin about it passes,
    # which is the whole of F211 and cost a screenshot to find the first time.
    #
    # The `fillOptions` SIGNATURE is pinned beside them, because a bound the
    # callers pass and the filler ignores is the same defect one layer down and
    # would leave both call sites looking correct.
    check("at13 both phase-cell selects are filled through PHCELL_OPTION_CHARS, "
          "and the filler takes a limit at all: %r"
          % (M.UI_HTML.count("PHCELL_OPTION_CHARS"),),
          "const fillOptions=(sel,pairs,cur,limit)=>{" in M.UI_HTML
          and "atOptions(ph.adoTracked),atChoice,PHCELL_OPTION_CHARS"
          in M.UI_HTML
          and "apOptions(apc),apChoice,\n    PHCELL_OPTION_CHARS" in M.UI_HTML
          # the bound reaches the option through ONE rule, not two spellings
          and "const optionText=(label,limit)=>{" in M.UI_HTML
          and "const {text,title}=optionText(t,limit);" in M.UI_HTML)
    # --- adf: the per-type field template on the connector card ---------------
    # A PROPERTY OF THE SOURCE, and text is the only instrument for it: that no
    # dotted-path writer is anywhere near a map whose KEYS carry dots. A browser
    # gate cannot state this - it can only find the day somebody's
    # `Microsoft.VSTS.Common.Activity` came back as four nested levels.
    # The script block, taken here rather than borrowed from a case further down:
    # a case that reaches forward for a name is a case whose order is load-bearing
    # in a file where nothing else's is.
    _adf_script = re.search(r"<script>([\s\S]*?)</script>", M.UI_HTML)
    _adf_js = _adf_script.group(1) if _adf_script else ""
    _adf_paths = sorted(set(re.findall(r"\b(?:set|del)Path\([^,]{1,40},\s*'([^']+)'",
                                       _adf_js)))
    _adf_bad = [q for q in _adf_paths
                if q.split(".")[0] in ("fields", "identityMap")]
    check("adf3 no setPath/delPath call names `fields` or `identityMap`: both "
          "split on dots, and both of those maps have keys that CONTAIN them - "
          "an ADO reference name and an email address. %d dotted path(s) read "
          "on this page, offenders %r" % (len(_adf_paths), _adf_bad),
          _adf_js != "" and len(_adf_paths) >= 5 and not _adf_bad,
          repr(_adf_paths[:6]))
    check("adf4 ...and the template editor writes through the direct-edit "
          "helpers instead, which is what makes that a mechanism rather than a "
          "habit somebody has to remember",
          "adoFieldSet(A().fields=A().fields||{},t,n,adoFieldValue(v));"
          in M.UI_HTML
          and "adoFieldDrop(A().fields||{},wit,name);" in M.UI_HTML
          and "fields[wit][name]=value;" in M.UI_HTML)
    check("adf5 removing the last field of a type PRUNES the type: an empty "
          "template is a validator warning ('it supplies nothing, remove the "
          "key'), so a card that left one behind would make a removal complain "
          "about the removal",
          "if(!Object.keys(t).length)delete fields[wit];" in M.UI_HTML)
    check("adf6 a stored value is printed as a LITERAL, not as text: `4` and "
          "`\"4\"` are different values to a board that requires a number, and "
          "a row showing both as 4 would hide the one decision this editor "
          "makes",
          "el('span',{class:'mono'},JSON.stringify(tpl[name]))" in M.UI_HTML)
    check("adf7 what a template may NOT name is left to `_ado_fields`, which "
          "holds both tables - a copy in the browser would be a second list "
          "free to disagree with the one the save is graded against. The card "
          "says where the answer comes from and lets the save name the field",
          "'data-fdnote':'1'" in M.UI_HTML
          and "refused when the manifest is validated" in M.UI_HTML
          # The tables themselves are NOT here.
          and "System.AreaPath" not in M.UI_HTML
          and "Microsoft.VSTS.TCM.ReproSteps" not in M.UI_HTML)
    # --- asc: the connector banner's shared-claim clause (F147) ---------------
    # PROPERTIES OF THE SOURCE, said as such. What a person SEES here is the
    # banner's wording and its tone, and only a browser gate can judge that;
    # what text is the right instrument for is that the clause exists once,
    # that its fallback arm is not the agreement arm, and that the state
    # reaches the DOM as a hook a gate can then read.
    check("asc1 the clause is one named function and its fallback arm is the "
          "NOT-COUNTED sentence, never the agreement one: a payload with no "
          "`shared` in it - an older server, or a project with no manifest - "
          "must not paint 'no work item claimed twice' over a plan nobody "
          "counted",
          M.UI_HTML.count("function adoSharedWords(") == 1
          and "return 'shared claims not counted';" in M.UI_HTML
          and "if(state==='none')return 'no work item claimed twice';"
          in M.UI_HTML
          and M.UI_HTML.count("'no work item claimed twice'") == 1)
    check("asc2 the state reaches the DOM as its own attribute rather than "
          "only as words inside a sentence, which is what lets a browser gate "
          "assert it - and `data-adostate` still names which of the banners "
          "this is, so a collision escalates the TONE and never renames the "
          "state",
          "'data-adoshared':(st.shared||{}).state||'uncounted'" in M.UI_HTML
          and "'data-adostate':banner[0]" in M.UI_HTML
          and "if((st.shared||{}).state==='shared')banner[1]='warn';"
          in M.UI_HTML)
    check("asc3 the clause is appended only on the banners that describe a "
          "manifest CARRYING links - the other two are about a plan with "
          "nothing on the board, where 'not counted' would blame the reader "
          "for a fetch nobody owed",
          "if(banner[0]==='linked'||banner[0]==='off'){" in M.UI_HTML
          and M.UI_HTML.count("adoSharedWords(st.shared)") == 1)
    check("pri11 Plan & models reads in the report's order - active work, then "
          "what has not started, then what is closed - through the SAME segment "
          "classifier the Overview and the report use, not a second copy of it",
          "const SEG_ORDER={active:0,pending:1,archived:2};" in M.UI_HTML
          and "SEG_ORDER[segOf(a[0].status)]-SEG_ORDER[segOf(b[0].status)]"
          in M.UI_HTML
          # decorated with the index, so plan order survives inside a segment
          and "comp.phases.map((p,i)=>[p,i])" in M.UI_HTML
          and "||(a[1]-b[1])" in M.UI_HTML)
    check("pri12 finished work is a RECORD, and EITHER status closes a task row: "
          "the phase's, because a task in a cancelled phase will never run, and "
          "the task's own, because a done task has already run - so its model and "
          "skills say what ran rather than what to run",
          "const frozen=segOf(ph.status)==='archived';" in M.UI_HTML
          and "const tFrozen=frozen||segOf(t.status)==='archived';" in M.UI_HTML
          # WIRED, both halves. Defining freezeControls and calling it on only one
          # of the two rows would leave a whole class of controls live.
          and "freezeControls(pr,frozenWhy)" in M.UI_HTML
          and "freezeControls(tr,tWhy)" in M.UI_HTML
          and "function freezeControls(root,why){" in M.UI_HTML)
    # A SOURCE property, and the negative is the whole point: `text-overflow` is
    # what a narrow column invites somebody to add back, and adding it would
    # restore exactly the defect this replaced - a title readable only on hover.
    # The tooltip that propped that up is asserted gone in the same case, because
    # leaving it behind is how the two halves drift apart.
    check("pri13 a task title WRAPS rather than being cut off, and nothing "
          "re-adds the ellipsis or the hover tooltip that used to stand in for "
          "the words it hid",
          "td.ttitle{max-width:18rem;white-space:normal;overflow-wrap:break-word}"
          in M.UI_HTML
          and "text-overflow" not in M.UI_HTML[
              M.UI_HTML.index("td.ttitle{"):M.UI_HTML.index("td.tskills{")]
          and "el('td',{class:'ttitle'},t.title||'')" in M.UI_HTML
          and "class:'ttitle',title:" not in M.UI_HTML)
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
          and "'policy'" in M.UI_HTML[M.UI_HTML.index("const TABS=["):
                                       M.UI_HTML.index("],SCROLL={}")])
    # --- pr (F-P-32): Proposals ------------------------------------------------
    # Parked phases had no surface in the panel at all: /audit:init can park every
    # synthesized phase, and the tab that shows the plan showed nothing. These pin
    # the constructs the browser checks depend on; the behaviour itself is driven
    # for real in tools/capture-screenshots.mjs.
    check("pr1 the proposals tab is registered, routable and has a view container",
          "data-t=props>Proposals<" in M.UI_HTML
          and "<div id=props" in M.UI_HTML
          and "function renderProposals()" in M.UI_HTML)
    check("pr2 ...and it paints inside a `.card`, the panel's structural unit - "
          "the responsive sweep waits for one before it measures, so a view "
          "without it times out instead of being checked",
          "class: 'card', 'data-propcard': '1'" in M.UI_HTML)
    check("pr3 every action goes through ONE endpoint, so no rule lives in the "
          "view: the closure, the lock and the revalidation stay in the script",
          "api('POST', '/api/proposal', body)" in M.UI_HTML
          and M.UI_HTML.count("propPost({") == 4)
    check("pr4 materialize PLANS before it writes, so the dialog can show what "
          "the write pulls in rather than reporting it afterwards",
          "action: 'plan'" in M.UI_HTML
          and M.UI_HTML.index("action: 'plan'")
              < M.UI_HTML.index("action: 'materialize'"))
    check("pr5 the drop reason is typed beside the button that uses it and the "
          "field carries a NAME - a placeholder vanishes exactly while the field "
          "is in use",
          "'aria-label': 'Why ' + p.id + ' is being declined'" in M.UI_HTML)
    check("pr6 an empty tab NAMES the absent basis instead of vanishing, the "
          "same rule a disappearing row broke",
          "data-propnone" in M.UI_HTML and "No parked proposals." in M.UI_HTML)
    check("pr7 a dropped proposal shows why, and a materialized one what it "
          "became - the two states that carry their own history",
          "'why declined'" in M.UI_HTML and "'became'" in M.UI_HTML)
    # --- pr: F93's JavaScript half --------------------------------------------
    # PROPERTIES OF THE SOURCE, every one of them, and that is why they are here
    # rather than in tools/ui-tests/proposals-cell.test.mjs. What the two
    # functions ANSWER is executed there, against the live Python they mirror;
    # what nothing can execute is that there is no SECOND spelling of either -
    # a duplicate composition passes every behavioural case, because the case
    # calls the one function and the copy sits in a branch it never reaches.
    _prop_js = M.UI_HTML[M.UI_HTML.index("function propReservedCell("):
                         M.UI_HTML.index("function renderProposals(")]
    check("pr8 the reserved cell is composed ONCE. F93 was this string existing "
          "in three spellings on the Python side; this file held the fourth and "
          "the fifth, and they differed in their SEPARATOR - the card joined "
          "with a middle dot and the confirm dialog with parentheses, so the "
          "same phase read as two different pieces of work",
          "function propReservedCell(row)" in M.UI_HTML
          and M.UI_HTML.count("function propReservedCell(") == 1
          # The composition itself, counted over the tab's own source: one
          # `phaseId + ' ('` and no surviving ` · ' + plural(` beside it.
          and _prop_js.count("row.phaseId + ' (' + plural(") == 1
          and _prop_js.count(".phaseId + ' · '") == 0
          and M.UI_HTML.count("propReservedCell(") == 3,
          repr((M.UI_HTML.count("function propReservedCell("),
                _prop_js.count("row.phaseId + ' (' + plural("),
                _prop_js.count(".phaseId + ' · '"),
                M.UI_HTML.count("propReservedCell("))))
    check("pr9 the count goes through the SHARED plural rule and no suffix of "
          "its own survives in this tab. Source is the only instrument for it: "
          "over every value a real row can carry the two expressions return the "
          "same string, so no behavioural fixture separates them - which is "
          "also why `_deps`' pluralisation needle read green over the copy that "
          "was here, since it is spelled without spaces and this file is not",
          _prop_js.count("plural(row.taskCount, 'task')") == 1
          and not re.search(r"===\s*1\s*\?\s*''\s*:\s*'s'", _prop_js)
          and not re.search(r"taskCount\s*\+\s*' task'", _prop_js),
          repr(_prop_js.count("plural(row.taskCount, 'task')")))
    check("pr10 the badge and the branch read `statusRaw`, never the "
          "normalised `status`. `proposal_rows` normalises an ABSENT status to "
          "`proposed`, so a surface that classifies off it classifies off an "
          "invention - and the catch-all this replaces told a record carrying "
          "an unknown word that its phase was live and this was the history "
          "trail, which is a claim about work nobody did",
          "function propStatusWords(p)" in M.UI_HTML
          and "if (p.statusKnown) return label(p.status);" in M.UI_HTML
          and "p.statusRaw === 'materialized'" in M.UI_HTML
          and "p.statusRaw === 'dropped'" in M.UI_HTML
          # The old readings are GONE, not merely outnumbered: either one
          # surviving in a branch would go on classifying the same records.
          and _prop_js.count("p.status === 'proposed'") == 0
          and _prop_js.count("p.status === 'dropped'") == 0,
          repr((_prop_js.count("p.status === 'proposed'"),
                _prop_js.count("p.status === 'dropped'"))))
    check("pr11 the parked COUNT reads `statusRaw` too, which is the reading "
          "`/audit:status`'s PROPOSALS block makes - the two print a number "
          "about one manifest and were free to disagree, with a record carrying "
          "no status counted as parked on one side and as legacy on the other",
          "props.filter((p) => p.statusRaw === 'proposed').length" in M.UI_HTML
          and "props.filter((p) => !p.statusKnown).length" in M.UI_HTML
          and M.UI_HTML.count("=== 'proposed').length") == 1,
          repr(M.UI_HTML.count("=== 'proposed').length")))
    # --- vb (F100): which build is serving this page ---------------------------
    # THE THREE-STATE RULE IS EXECUTED, in tools/ui-tests/version-banner.test.mjs,
    # against the real function and in both mutation directions. These pin the
    # constructs that suite depends on and one thing it cannot see: that the
    # banner is wired into the assembled page at all. A part on disk that nothing
    # joins loads no code, and every case in a sandbox that reads the same part
    # list would keep passing over it.
    check("vb1 the staleness banner ships INSIDE the page, and the part that "
          "carries it is joined rather than merely present on disk",
          "function vbBanner(state)" in M.UI_HTML
          and "function vbWords(state)" in M.UI_HTML
          and "vbCheck().catch(" in M.UI_HTML
          and "panel/version-banner.js" in _panel_ui._JS_PARTS)
    check("vb2 the gate is STRICT and there is exactly one of it: `stale` "
          "arrives as JSON, and a truthy read would raise the banner on a value "
          "nobody here understood. `false` and `null` are two different silences "
          "- a comparison that agreed, and one that never happened - and the "
          "endpoint reports three states so this surface can keep them three",
          "if (!state || state.stale !== true) return null;" in M.UI_HTML
          and M.UI_HTML.count("state.stale") == 1,
          repr(M.UI_HTML.count("state.stale")))
    check("vb3 the banner asks `/api/version` and nothing else does, so the "
          "installed half is read where it is compared rather than cached into "
          "some other payload that would then be as old as the page",
          # The CALL is counted, not the path: the path is written several times
          # more in the prose above it, and a count over the bare string would be
          # a count of how much this feature explains itself.
          M.UI_HTML.count("api('GET', '/api/version')") == 1,
          repr(M.UI_HTML.count("api('GET', '/api/version')")))
    check("vb4 it wears the panel's EXISTING notice rather than a second "
          "warning component, and `.buildstale` is placement plus the hook a "
          "browser gate reads",
          "el('div', { class: 'buildstale', 'data-buildstale': '1' }," in M.UI_HTML
          and "el('div', { class: 'findings warn', role: 'status' }," in M.UI_HTML
          and ".buildstale{" in M.UI_HTML)
    # A COMPUTED pin, because the claim is that two rules agree and neither
    # value is a token either could read. `.shell` measures the content column
    # and the notice sits above it; if the shell's gutters or its centre line
    # move, the sentence stops lining up with the thing it interrupts and
    # nothing else would say so.
    _vb_shell = re.search(r"\.shell\{[^}]*max-width:([^;]+);"
                          r"[^}]*padding:[^ ]+ ([^ ]+) [^;]+;", M.UI_HTML)
    _vb_band = re.search(r"\.buildstale\{max-width:([^;]+);[^}]*"
                         r"padding:0 ([^}]+)\}", M.UI_HTML)
    check("vb5 the banner's width and gutters are the shell's own, read out of "
          "the assembled sheet rather than trusted to a comment beside them",
          bool(_vb_shell) and bool(_vb_band)
          and _vb_shell.group(1) == _vb_band.group(1)
          and _vb_shell.group(2) == _vb_band.group(2),
          repr((_vb_shell and _vb_shell.groups(), _vb_band and _vb_band.groups())))
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
          # "the same path every other write uses" is now literally the same
          # function, which is what this case always claimed and could not check.
          "confirmSave({rows:tChangeRows,title:'Save theme'" in M.UI_HTML
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
          and "confirmSave({rows:tChangeRows," in M.UI_HTML
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
    # --- pc: one column per area does not scale ------------------------------
    # The tags come from the PLAN, so the width of this table was a function of how
    # many areas a project happens to tag: eight of them is eight selects on every
    # row and a sideways scroll of em-dashes. A column is drawn for an area that
    # CARRIES A RULE.
    #
    # These are SOURCE-PROPERTY pins and say so in their labels, because the
    # behaviour cannot be checked from here: `... in UI_HTML` cannot tell "only the
    # areas with a rule" from "all of them", from "none of them", or from the wrong
    # predicate entirely. Those are asserted where they can be executed, in
    # tools/ui-tests/policy-columns.test.mjs, and each wrong one is mutated in
    # tools/ui-tests/mutants.test.mjs. The strip's paint is driven in
    # capture-screenshots --check (assertPolicyWorks).
    check("pc1 there is ONE predicate for the column set and one reader of it - a "
          "second would be a second opinion about which rules are on screen "
          "(the answers themselves are in tools/ui-tests/policy-columns.test.mjs)",
          "function pCols(kind){" in M.UI_HTML
          and M.UI_HTML.count("pCols(") == 2
          and "const cset=pCols(kind),cols=cset.shown;" in M.UI_HTML)
    check("pc2 ...and liveness is not that predicate: `active` decides the LABEL "
          "on a column and never whether it exists, because a dormant area's rule "
          "is one status change away from being enforced",
          "ruled.has(a.tag)||PF.cols.indexOf(a.tag)>=0" in M.UI_HTML
          and "a.active?'live':'dormant'" in M.UI_HTML
          and "pStatesRule(areas[tag])" in M.UI_HTML)
    check("pc3 an area with no column is NAMED rather than dropped, in the panel's "
          "own strip grammar - the kind switch and the default switch above it are "
          "the same component, so this needed no rule of its own",
          "'data-pcols':'1'" in M.UI_HTML
          and "class:'ovpill',type:'button','data-pcol'" in M.UI_HTML
          and "'data-pcol':a.tag" in M.UI_HTML)
    check("pc4 ...the strip names the set it is listing, and BOTH branches of its "
          "sentence are written. The second looks vacuous - it says nothing is "
          "hidden when nothing is - and it is the only thing that fails if the "
          "claim becomes unconditional",
          "'Areas with no rule'" in M.UI_HTML
          and "'no column of their own — press one to add it'" in M.UI_HTML
          and "'every area has a column'" in M.UI_HTML
          and "cset.hidden.length" in M.UI_HTML)
    # THE WHOLE BODY, as bytes, and not a slice around it. A window bounded by
    # `.index("\n\n")` would shrink silently if a blank line were ever added inside
    # the function, and the negative clauses ("no pSetRule in here") would then keep
    # passing about three characters. Three lines are cheap to pin outright: any
    # edit to them is a review checkpoint, which is exactly what a control that
    # must not write anything deserves.
    check("pc5 revealing a column is NOT a second way to write a rule: the control "
          "moves PF.cols and nothing else, so pSetRule and pAddPattern stay the "
          "only writers",
          "function pToggleCol(tag){\n const i=PF.cols.indexOf(tag);\n"
          " if(i>=0)PF.cols.splice(i,1);else PF.cols.push(tag);}" in M.UI_HTML
          and "onclick:()=>{pToggleCol(a.tag);renderPolicy();}}" in M.UI_HTML)
    check("pc6 a reveal is scoped to the kind it was made in, and the strip is an "
          "OPTIONAL child of both copies of the table - append() stringifies a "
          "null where el() drops it, which is the browse dialog's lesson",
          "const PF={kind:'skills',q:'',bad:false,cols:[]};" in M.UI_HTML
          and "PF.kind=k;PF.q='';PF.cols=[];PNOTE=null;renderPolicy();" in M.UI_HTML
          and M.UI_HTML.count("cap.tools,cap.colstrip,cap.body].filter(Boolean));")
              == 2)
    check("emptying a list removes it, and the container with it - the same "
          "convention Settings writes the config with",
          "function pPrune(" in M.UI_HTML
          and "if(Array.isArray(k[l])&&!k[l].length)delete k[l];" in M.UI_HTML
          and "if(!Object.keys(k.areas).length)delete k.areas;" in M.UI_HTML)
    check("a save goes through the one confirm flow, writes through the one policy "
          "endpoint, and describes itself in the vocabulary the server echoes "
          "(four call sites: boot, PUT, the post-save re-read, refreshFromDisk)",
          # Through `confirmSave` now, which is where the confirm flow lives for
          # all four writable surfaces - the title is what identifies this one.
          "confirmSave({rows:policyChanges,\n     title:'Save capability policy'"
          in M.UI_HTML
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
                           "taskSkills", "phaseReviewModel", "phasePriority")
               if ("{comp:'%s'" % k) not in M.UI_HTML]
          and "(doc.composition||{})[ref.comp]" in M.UI_HTML
          and set(M.COMPOSITION_HELP) == set(_help.COMPOSITION_PATHS))
    # --- the branch-naming card (meta.branch) ---------------------------------
    # SOURCE PROPERTIES, and the labels say so. Each of these is a claim about how
    # the page is WRITTEN that no browser gate can make: the browser can prove the
    # card paints, and does (capture-screenshots --check boots the panel), but it
    # cannot prove the expansion rule was not quietly reimplemented beside it.
    _bcard = M.UI_HTML[M.UI_HTML.index("function branchCard("):
                       M.UI_HTML.index("// --- grouped manifest findings")]
    check("bn1 the branch card is WIRED: the composition view calls it, so a part "
          "that assembles but is never invoked cannot pass. Assembly alone would "
          "- both sides of the byte-identity check are built from the same tuple",
          # The call and the placement are two statements now: the card is built
          # with the other config cards and appended AFTER the table, which is what
          # putting the view's main object on top required. The claim is unchanged
          # and is spelled as its two halves - invoked, and actually placed - which
          # says it more exactly than one line doing both ever did.
          "const bcard=branchCard(comp,patch);" in M.UI_HTML
          and "c.append(tcard,meta,bcard);" in M.UI_HTML)
    check("bn2 the card writes patch.meta.branch and NOTHING else on the form's "
          "draft - it rides the Composition save, so a stray write to another "
          "meta key would be saved under a confirm dialog that never listed it",
          _bcard.count("patch.meta.") == 1
          and "patch.meta.branch=draft" in _bcard,
          repr([l for l in _bcard.splitlines() if "patch.meta." in l]))
    check("bn3 THE LOAD-BEARING ONE: the worked example is READ from the payload, "
          "never composed here. `_branch.expand`'s separator rule has cases - an "
          "empty placeholder takes the separator behind it - and a second copy in "
          "JS would be a second answer, with the branch git actually gets being "
          "the one nobody previewed. So the card may read info.example and must "
          "carry no substitution of its own",
          "info.example" in _bcard
          and ".replace('{" not in _bcard and '.replace("{' not in _bcard
          and "split('{" not in _bcard, repr(_bcard[:0]))
    check("bn4 every branch type the card offers carries what it is FOR. The "
          "types list doubles as the pre-approved git globs, so it is read by "
          "people deciding policy, and eight bare words teach none of them "
          "anything",
          "id:'branchtypehelp'" in _bcard and "info.typeHelp" in _bcard)
    check("bn5 the banner describes the FILE as saved, not the draft - the ADO "
          "card's rule, and the reason is the same: a banner that followed the "
          "draft would report a convention that is not the one running",
          "'data-branchstate':bstate" in _bcard
          and "info.basis" in _bcard)

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
          and "') against '+prevCut+' to '+dayIso(dnum(cut)-1)" in M.UI_HTML
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
          and "restoreCaret(keepQ?$('#uq'):null,caret,keepBack)" in M.UI_HTML
          and "if(n.setSelectionRange)try{n.setSelectionRange(caret,caret);}"
              in M.UI_HTML)

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
          "*DAY_MS)" in M.UI_HTML)
    # An explanation computed by a second copy of "what matches" is an explanation
    # that can contradict the view it is explaining.
    #
    # The last clause used to read `for(const d of UORDER.concat(` - the loop's
    # own spelling of "and the range too", which the chip row spelled a second
    # time and `uAnyFilter` a third. It is `uOnFilters()` in all three now, so
    # this clause names the shared list instead of one copy of it: the diagnosis
    # cannot blame a filter the chips do not show, or miss one they do.
    check("the diagnosis re-runs uFiltered with one slot blanked instead of "
          "re-implementing the match, and walks the same list the chips do",
          "const keep=UF[d];UF[d]=d==='range'?'all':'';" in _emp
          and "const n=uFiltered().length;UF[d]=keep;" in _emp
          and "for(const d of uOnFilters()){" in _emp)
    check("one filter doing the emptying is named, counted and liftable on its "
          "own — clear-all throws away the ones that were fine",
          "plural(n,'row matches','rows match')+' everything else.'" in _emp
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
    # not a claim). In any other position it manufactures an answer to a question
    # that has none.
    #
    # `attempts` USED TO BE EXEMPT HERE, on the stated ground that "one attempt is
    # the true default". It is not, and this rule's own sentence is what settles it:
    # `audit-task.py` writes `attempts: 0` for every new task, and two documented
    # paths take a count back DOWN while the ledger keeps the tokens - the
    # orchestrator reverting the increment after a specific failure, and
    # `/audit:run` resetting a blocked or re-opened task. So zero is a recorded
    # value and `||1` manufactured an answer for it: measured over one such task
    # and one that ran twice, `mean attempts` read 1.5 against a recorded average
    # of 1.0. Both readers go through `uAtt()` now, which answers a number, zero,
    # or null - and the exemption is gone from the regex, so the rule covers the
    # position it was carved out of.
    # The comment filter knew `//` and not `*`, so a JSDoc line QUOTING the retired
    # `||1` form was reported as an offender - prose naming the code is not the
    # code, the same lesson the stage-wiring guard in tools/ already carries. Both
    # comment syntaxes are excluded now; a line that merely mentions the shape can
    # explain why it is retired without tripping the rule against it.
    _or1 = [l.strip() for l in M.UI_HTML.splitlines()
            if "||1" in l and not l.lstrip().startswith(("//", "*", "/*"))
            and not re.search(r"peak|\(hi-lo\)", l)]
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

    # --- uf: the filters fold, and the active ones stay above it ----------------
    # The tab used to open on a wall of controls with no number in sight. They are
    # behind one <details> now, and the chips that were BELOW them are above it.
    #
    # ALL OF THESE ARE CLAIMS ABOUT SOURCE TEXT and they are labelled as such:
    # whether the fold actually paints, opens, and keeps its state under the
    # reader's hand is a browser claim and belongs to capture-screenshots.mjs.
    # What source text CAN say - and nothing else can - is that there is one list
    # of what is filtering, that the count on the summary is read off that same
    # list, and that nothing derives the fold's open state from the filters.
    _ru = M.UI_HTML[M.UI_HTML.index("function renderUsage()"):
                    M.UI_HTML.index("// --- Esc pops the last filter")]
    # `find`, not `index`: a missing literal has to report a FAILED case, not
    # raise out of the middle of the suite and take every case after it with it.
    _i_chips, _i_bar = (_ru.find("card.append(chips);"),
                        _ru.find("card.append(filt);"))
    check("uf1: the chip row is appended to the card BEFORE the sticky bar the "
          "fold sits in, so a tab whose fold is shut still leads with what is "
          "scoping it (chips at %d, bar at %d) - SOURCE order; that the shut "
          "fold really paints under them is capture-screenshots.mjs's"
          % (_i_chips, _i_bar),
          "const fold=el('details',{class:'fdetails','data-uffold':'1'," in _ru
          and "el('summary',{'data-ufilters':'1'},'Filters'," in _ru
          and 0 <= _i_chips < _i_bar)
    check("uf2: the chips and the count on the summary are ONE read of ONE list "
          "- a second read is how a chip row and a badge come to describe the "
          "same screen differently (reads of uOnFilters() in renderUsage: %d)"
          % (_ru.count("uOnFilters()"),),
          "const on=uOnFilters();" in _ru
          and "on.forEach(d=>chips.append(el('button',{class:'uchip'," in _ru
          and "on.length?el('span',{class:'fcount'},' · '+on.length+' on')"
              ":null" in _ru
          and _ru.count("uOnFilters()") == 1)
    # Counted over the whole of renderUsage rather than over a slice around the
    # <details>. The slice that used to sit here ended at `filt.append(fold,`,
    # which is the literal uf6 below is there to mutate - so proving uf6 red
    # RAISED out of this line and took every case after it with it. An endpoint
    # that another case exists to remove is not an endpoint.
    #
    # NO MODULE STATE FOR IT, and that is the measured shape rather than a
    # preference. The first version kept a `UFOPEN` flag written from the fold's
    # own `toggle` handler, and a browser driver reopened the fold, changed a
    # filter in the same turn and got it back SHUT every time: `toggle` is queued
    # as a task, so the repaint rebuilt the fold before the handler had run. A
    # hand at human speed never sees it. The state is read off the OUTGOING
    # element now - one place the fact lives, and the same thing proposals-view
    # does with its own <details>.
    check("uf3: the fold's open state is the READER's - read back off the "
          "outgoing element at the top of the pass, never held in a variable "
          "beside the DOM and never derived from the filters (reads of "
          "foldOpen: %d, `open:` in renderUsage: %d)"
          % (_ru.count("foldOpen"), _ru.count("open:")),
          "const foldOpen=!!c.querySelector('details[data-uffold][open]');" in _ru
          and "open:foldOpen?'':null" in _ru
          # Two: the read and the one use. A third would be something deciding
          # the fold for the reader - the "it opens itself whenever a filter is
          # on" mutation, which no other case here can see. And no `UFOPEN`
          # anywhere: a second home for this fact is the race described above.
          and _ru.count("foldOpen") == 2
          and "UFOPEN" not in M.UI_HTML
          and _ru.count("open:") == 1)
    check("uf4: the range preset wears a chip like every other filter - it is "
          "not a DIMS slot, so it was the one filter that could be on with "
          "nothing on screen naming it",
          "const uOnFilters=()=>UORDER.concat(UF.range==='all'?[]:['range']);"
          in M.UI_HTML
          and "const uAnyFilter=()=>uOnFilters().length>0;" in M.UI_HTML
          and "title:d==='range'?'back to all time':'remove this filter'," in _ru)
    check("uf5: and every way out of a filter goes through uLiftF, which is "
          "what keeps the range's own default out of every call site - blanking "
          "it instead reaches parseInt('') and throws on the Date (hand-written "
          "`UF.range='all';renderUsage();`: %d, hand-written `setF(d,'')`: %d)"
          % (M.UI_HTML.count("UF.range='all';renderUsage();"),
             M.UI_HTML.count("setF(d,'')")),
          "function uLiftF(d){" in M.UI_HTML
          and "if(d!=='range'){setF(d,'');return;}" in M.UI_HTML
          and "onclick:()=>uLiftF(d)}" in _ru
          and "const toAll=()=>uLiftF('range');" in M.UI_HTML
          and M.UI_HTML.count("UF.range='all';renderUsage();") == 1
          and M.UI_HTML.count("setF(d,'')") == 1)
    check("uf6: Export stayed OUTSIDE the fold - it is not a filter, and behind "
          "a summary saying 'Filters' nobody would find it again",
          "filt.append(fold,el('button',{class:'btn small push',type:'button',"
          in _ru
          and "r2.append(el('button',{class:'btn small push'" not in M.UI_HTML)
    check("uf7: the summary is a pill and a disclosure the platform draws, "
          "under the report's own component name, and the count badge sits on "
          "the SHUT control where it is the last thing left saying so",
          ".fdetails>summary{cursor:pointer;font:inherit;font-size:.78rem;"
          in M.UI_HTML
          and '.fdetails[open]>summary::after{content:"\\25B4"}' in M.UI_HTML
          and ".fdetails .fcount{font-weight:700;color:var(--accent);"
              "font-variant-numeric:tabular-nums}" in M.UI_HTML
          # The bar holds a fold and a button now, so a centred cross axis would
          # float Export halfway down an open fold.
          and "align-items:flex-start;margin:0 0 var(--sp-1)" in M.UI_HTML)

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
          and " polFullFill();\n restoreCaret(" in M.UI_HTML)
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
          and " polFullFill();\n restoreCaret(" in M.UI_HTML
          # The two branches collapsed into one call, and BEHAVIOUR IS
          # UNCHANGED rather than improved: every one of these views sets
          # `keepBack = keepId ? null : focusKeep(...)`, so a keepId that no
          # longer resolves reaches focusBack(null), which returns false and
          # does nothing - exactly what the old `if` with no `else` did. That
          # sameness is what makes one function able to serve both.
          and "restoreCaret(keepId?document.getElementById(keepId):null,caret,"
              "keepBack);\n if(scrolled){" in M.UI_HTML
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
          # The attr select: the option's VALUE stays the ledger's key because
          # that is what the filter matches on, and only the words are renamed -
          # which is why fillOptions takes [value, label] pairs at all.
          and "vals.map(v=>[v,uKey(v)])" in M.UI_HTML)
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
          and "function showTab(t,push){" in M.UI_HTML
          # The call WITH its own comment, which appears nowhere else - enough to
          # place it inside showTab without pinning the lines around it.
          and " closeCombo();   // the menu is on <body>," in M.UI_HTML)
    check("co: a mousedown anywhere in the menu keeps the input's focus, so a "
          "scrollbar drag or a click on the footer no longer closes it (F-P-1d)",
          "CMENU.addEventListener('mousedown',e=>e.preventDefault());" in M.UI_HTML)
    check("co: a click on the still-focused input reopens a closed menu (F-P-1c)",
          "inp.addEventListener('click',()=>{if(!(CMOWNER===me&&comboOpen()))render();});"
          in M.UI_HTML)
    # F90: this case used to be LABELLED with the deferral behaviour while
    # asserting only how the predicate is spelled, so it stayed green through a
    # release in which the behaviour did not hold - the poll consulted
    # `interacting()` three round trips before it acted on the answer. The
    # behaviour is driven in tools/ui-tests/refresh-deferral.test.mjs, which now
    # covers the await window; what is left here is the CONSTRUCTS that suite
    # depends on, labelled as constructs.
    check("co: the constructs behind the deferral - interacting() exists, "
          "answers an open combo first, DERIVES its selector from dirtyViews, "
          "and the poll re-asks it after the fetches instead of acting on the "
          "answer it got before them (F-P-1b, F90)",
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
          and "&&!interacting()){const back=FP;FP=fp;refreshFromDisk(back);}"
              in M.UI_HTML
          # The re-ask, and the rewind that keeps a deferred change from being
          # swallowed. Without both, the predicate above is correct and unused.
          and "if(interacting()){FP=fpBack;return;}" in M.UI_HTML)

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
          "refreshFromDisk(back);" in _poll
          and "!document.querySelector('dialog[open]')" in _poll
          and "if(FP===null)FP=fp;" in _poll)
    check("lv: refreshFromDisk is defined OUTSIDE the D9 slice - the poll "
          "path still never touches renderSettings",
          "async function refreshFromDisk(" in M.UI_HTML
          and M.UI_HTML.index("async function refreshFromDisk(")
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
        # The evidence badge is a control when there is a run to open, and the
        # pill inside it is .66rem type whose padding scales with density - so
        # the floor is DECLARED rather than measured once and hoped for, which
        # is the same repair `.btn.small` above already took.
        "button.evtog": ("min-height:24px", "button.evtog"),
        "button.chip.ghosted.optnone": ("ok", "86.7x29.4"),
        "button.dtopic": ("ok", "343x78.6"),
        "button.filt": ("ok", "47.6x29.2"),
        "button.ovpill": ("ok", "60.5x29.9"),
        # was ("ok", "301x147.2"), a TWO-LINE row: the abbreviated outcome
        # used to sit on its own line under the title. That line moved to the
        # row's tooltip and the opened detail, so the recorded figure stopped
        # describing the shape it is the evidence for. Re-measured in Chromium
        # at all three densities - 42.2 comfortable, 40.5 compact, 44.2
        # spacious - and the TIGHTEST is the one recorded, because that is the
        # reading the >= 24 verdict has to survive. The width is whatever the
        # container gives the row, which is why the old 301 does not reappear
        # and why only the height says anything here.
        "button.ovrow": ("ok", "860.4x40.5"),
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

        Quote-aware AND comment-aware, and the second half was learned the way
        the first was - by being wrong. A ')' inside a string literal
        ('(/audit:review)' is one of them, three lines from a table) closes the
        call early and hides everything after it. So does an APOSTROPHE inside a
        `//` comment: "a task model and a phase's review model" is written above
        this very table, and that lone quote opened a string that ran on to the
        next quote character in the CODE, after which every paren was counted
        inside-out. The census then reported the composition table as headerless
        with its `tableHead(` in plain sight - which is the loud direction; the
        same defect is equally able to hide a table that really has no header,
        and nothing would have said so.
        """
        _depth, _j, _quote = 0, i, ""
        while _j < len(js):
            _ch = js[_j]
            _nxt = js[_j + 1:_j + 2]
            if _quote:
                if _ch == "\\":
                    _j += 2
                    continue
                if _ch == _quote:
                    _quote = ""
            elif _ch == "/" and _nxt == "/":
                # To end of line. Checked AFTER the quote branch, so a `//` that
                # is really inside a string (a url) is still string content.
                _nl = js.find("\n", _j)
                _j = len(js) if _nl == -1 else _nl
                continue
            elif _ch == "/" and _nxt == "*":
                _end = js.find("*/", _j + 2)
                _j = len(js) if _end == -1 else _end + 2
                continue
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
        # A header cell, HOWEVER it is built. Three of these tables reached
        # `el('th'` directly until the fifteen hand-nested headers across the
        # panel became one `tableHead`/`headRow`; a census that only knew the old
        # spelling would have reported three headerless tables in a tab whose
        # headers had just been made harder to omit.
        _ir_tables.append((_cm.group(1) if _cm else "",
                           "el('th'" in _src or "tableHead(" in _src
                           or "headRow(" in _src))
    _ir_classes = [c for c, _ in _ir_tables]
    # The vacuity guard, first and for the same reason ts0 exists: ir1 narrows
    # this set, and a slice that found nothing would report a tab with no
    # headerless table on it. Counted, not merely found - "regtbl adosm" alone
    # would pass an `in` while the other two had drifted out of the slice.
    # THE SCANNER, DRIVEN OVER FIXTURES BOTH WAYS, because a census that
    # over-reports gets its subject "fixed" and one that under-reports reports a
    # clean tab it never read. The dirty fixtures are the two shapes that really
    # do end a call - a ')' outside any string, and one hidden behind an
    # apostrophe the scanner must NOT treat as a quote - and the clean ones are
    # the shapes it must read straight through.
    _IR_THROUGH = (
        # An apostrophe in a comment: the shape that shipped this defect.
        "(el('table',{},\n // a phase's review model\n tableHead(['a'])))",
        # A ')' inside a string literal, which is what the quote half is for.
        "(el('table',{},'(/audit:review)',tableHead(['a'])))",
        # A block comment carrying an unbalanced paren.
        "(el('table',{},/* count( */ tableHead(['a'])))",
        # A `//` inside a STRING is not a comment, and eating the rest of the
        # line there would swallow the header that follows it.
        "(el('table',{},'https://x',tableHead(['a'])))",
    )
    _ir_missed = [t for t in _IR_THROUGH if "tableHead(" not in _ir_call(t, 0)]
    _ir_short = [t for t in _IR_THROUGH if _ir_call(t, 0) != t]
    check("ir0a the call reader walks THROUGH a comment, a quoted ')' and a "
          "quoted '//' to the real end of the call: %d/%d fixture(s) lost their "
          "header %r, %d closed early %r"
          % (len(_ir_missed), len(_IR_THROUGH), _ir_missed,
             len(_ir_short), _ir_short),
          not _ir_missed and not _ir_short)
    check("ir0b ...and it still STOPS at the first real close, so a header "
          "belonging to the NEXT call is never read as this one's - which is "
          "how a reader that simply ran to the end of the file would pass "
          "every fixture above while asserting nothing",
          _ir_call("(el('table',{}))+el('x',{},tableHead(['a']))", 0)
          == "(el('table',{}))"
          and "tableHead(" not in _ir_call("(el('table',{}))+tableHead(['a'])", 0))
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
          # ONE spelling now, mapped over the three column names, where there
          # were three copies of it. The count was a proxy for "all three
          # columns are scoped" and it stopped being one the moment they came
          # from a map - so what is checked here is that the scope is applied
          # where the columns are BUILT, and the rendered grid is counted by
          # assertStateMapAxes in tools/capture-screenshots.mjs, which can see
          # the cells rather than the source that makes them.
          and M.UI_HTML.count("scope:'col'") == 1
          and "['manifest status','ADO state','never move'].map(h=>" in M.UI_HTML
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
    # --- F187: the two settings that had no control, and the declaration that
    # --- makes their absence measurable ---------------------------------------
    # SOURCE PROPERTIES ONLY. That the controls exist and save is proven by the
    # browser (`capture-screenshots --only panel` walks `[data-adosetting]` against
    # `_manifest_vocab.ado_settings()`); what a browser cannot prove is that the
    # declaration is DERIVED from the path each control writes to rather than typed
    # beside it, which is the thing that would rot.
    check("f187a the parent work item is typed as a number and refuses a value "
          "that is not a positive integer - a work item id pasted as a URL must "
          "leave the key alone rather than write NaN or 0",
          "id:'ado-parentWorkItem',type:'number'" in M.UI_HTML
          and "Number.isInteger(n)&&n>0" in M.UI_HTML
          and "'aria-label':'parent work item id'" in M.UI_HTML)
    check("f187b the tag vocabulary editor writes through `conventions` and "
          "prunes it when empty, so an emptied editor leaves no hollow block "
          "behind for the validator to warn about",
          "c.tagVocabulary=m;else delete c.tagVocabulary" in M.UI_HTML
          and "if(!Object.keys(c).length)delete ADRAFT.conventions" in M.UI_HTML)
    check("f187c ...and it renders an open axis as words rather than as `*`, "
          "which is the one value a reader would otherwise take for a literal tag",
          "any value (open axis)" in M.UI_HTML
          and "vals.length===1&&String(vals[0]).trim()==='*'" in M.UI_HTML)
    check("f187d every control declares the setting it belongs to, and the two "
          "shared helpers DERIVE that from the path they write to - a hand-typed "
          "attribute is a second vocabulary, and the check that reads it walks a "
          "rendered page precisely so no translation table exists to drift",
          "'data-adosetting':path.split('.')[0]" in M.UI_HTML
          and "'data-adosetting':key.split('.')[0]" in M.UI_HTML)

    _FL_LABELLED = {
        "placeholder:def==null?(f.placeholder||''):String(def)":
            "klabel(f.label,f.path,tip,fieldId(f.path)),inp);",
        "placeholder:'not set'":
            "klabel(lbl,p,null,fieldId(p)),inp);",
        # F187 moved these four wrappers: each now declares the meta.ado setting
        # it belongs to, stamped from the same path the control writes to, so the
        # browser check that walks the card reads the page instead of a translation
        # table. The association itself is unchanged - the <label> still wraps the
        # box - which is why they stay exemptions rather than gaining aria-labels.
        "placeholder:ph||''":
            "'data-adosetting':path.split('.')[0]},\n"
            "    flabel(lbl,help,null,tid),i);",
        "placeholder:'audit-plugin'":
            "'data-adosetting':'tag'},\n     flabel('Provenance tag',MDESC.adoTag,",
        "placeholder:'not written'":
            "'data-adosetting':'onComplete'},\n"
            "     flabel('Remaining Work on done',",
        "placeholder:'empty = static iteration path'":
            "'data-adosetting':'sprint'},\n"
            "     flabel('Sprint team (current iteration)',",
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
          len(_fl_le) == 6 and not _fl_unnamed)

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
    # F90/C6. This case's LABEL was already right - "a menu whose input lost
    # focus" - and its clauses checked only how the close was spelled, so it
    # stayed green while the guard closed menus whose input had just GAINED
    # focus. The handler runs on the very focus that opens one. The owner test
    # is the difference between the label and what the code did, so it is now
    # asserted rather than described.
    check("fo4 a STALE dropdown is closed rather than scrolled out from under - "
          "a fixed menu travels with the viewport, so scrolling cannot free "
          "anything - while the menu owned by the control that just took focus "
          "is exempt, because this handler runs on the focus that opened it",
          "over.classList.contains('combo-menu')" in M.UI_HTML
          and "if(CMOWNER&&CMOWNER.inp===n)return;" in M.UI_HTML
          and "if(!over.contains(n)){closeCombo();continue;}" in M.UI_HTML
          # ...and the owner is recorded at the only place that knows it.
          and "me.inp=inp;" in M.UI_HTML)
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
