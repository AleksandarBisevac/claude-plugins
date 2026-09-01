/**
 * The capability table for one kind: its toolbar and its body, built once and
 * used by both the Policy tab and the expanded dialog.
 *
 * ONE builder on purpose. A "full screen" copy of a table that disagrees with
 * the table is worse than the scrolling it was meant to relieve, and two
 * builders would drift. Both copies read the same `PF` filter, so the search box
 * in either one narrows both.
 *
 * The rows are the SERVER's verdicts, rendered and never recomputed: a second
 * matcher in the browser would eventually disagree with the guard, and
 * disagreeing about a denial is the one thing a preview must not do.
 *
 * @param {string} kind - a kind from `PKINDS`
 * @param {PolicyRow[]} rows - the server's resolved rows for that kind
 * @param {boolean} full - true for the dialog's copy. It decides only the
 *   element ids, since a document may hold one element per id and both copies
 *   carry a search box, and whether the frame caps its own height — in the
 *   dialog the dialog is the frame. It also drops the Expand button, because an
 *   expand control in an expanded view says nothing
 * @returns {{tools: HTMLElement, colstrip: (HTMLElement|null),
 *   body: HTMLElement}} the toolbar, the area-column strip and the table,
 *   separately, so a caller can put them in different containers. `colstrip` is
 *   null when every area already has a column, because there is then nothing
 *   hidden to say anything about. `body` is the empty-state note when nothing
 *   matches, and that note distinguishes "nothing matches this filter" from
 *   "nothing of this kind was discovered" — the second is not a filter problem
 *   and offers no Clear
 */
function pCapTable(kind,rows,full){
 const q=PF.q.trim().toLowerCase();
 const strays=pStrays(),hid=rows.filter(pStray).length;
 const shown=rows.filter(r=>(!q||(r.name+' '+(r.source||'')).toLowerCase().includes(q))
   &&(!PF.bad||r.verdict==='violation')
   &&(strays||!pStray(r)));
 const qIn=el('input',{type:'search',id:full?'polqfull':'polq',value:PF.q,
   placeholder:'search '+PKLABEL[kind].toLowerCase()+'…',
   'aria-label':'search '+PKLABEL[kind].toLowerCase()});
 qIn.addEventListener('input',()=>{PF.q=qIn.value;renderPolicy();});
 const badId=full?'polbadfull':'polbad';
 const bad=el('input',{type:'checkbox',id:badId});bad.checked=PF.bad;
 bad.onchange=()=>{PF.bad=bad.checked;renderPolicy();};
 const strayId=full?'polstrayfull':'polstray';
 const strayBox=el('input',{type:'checkbox',id:strayId});strayBox.checked=strays;
 strayBox.onchange=()=>{PF.strays=strayBox.checked;renderPolicy();};
 const tools=el('div',{class:'ovtools'},qIn,
   el('label',{class:'inl',for:badId},bad,'violations only'),
   // The narrowing SAYS SO, and it is only offered when there is something to
   // say: a checkbox that hides nothing is a control that teaches the wrong
   // lesson about what is on screen.
   hid?el('label',{class:'inl',for:strayId,'data-polstray':'1',
     title:'Capabilities that resolve on this machine and would not survive a '
       +'clone — a skill in a home directory, or a plugin the committed '
       +'.claude/settings.json does not declare. A rule that NAMES one is shown '
       +'either way: hiding a refusal would misreport what the guard does.'},
     strayBox,'incl. '+hid+' that stay on this machine'):null,
   el('span',{class:'count',style:'margin-left:auto'},
     shown.length===rows.length?(rows.length+' discovered')
       :(shown.length+' / '+rows.length)));
 if(q||PF.bad)tools.append(el('button',{class:'btn small',type:'button',
   'data-polclear':'1',onclick:()=>{PF.q='';PF.bad=false;renderPolicy();}},
   'Clear filters'));
 // The control that gives this table the screen. Only in the tab: inside the
 // dialog the same affordance is the ✕, and an expand button in an expanded
 // view is a button that says nothing.
 if(!full)tools.append(el('button',{class:'btn small','data-polexpand':'1',
   type:'button','aria-label':'expand the capability table to full screen',
   title:'Expand — read the whole table without the frame. Esc closes it.',
   onclick:()=>polFullOpen()},'⤢ Expand'));
 // A column is drawn for an area that CARRIES A RULE — see `pCols`, which also
 // says why liveness is not the predicate. The areas with none are offered here by
 // name, pressed meaning "on screen": a hidden column must never be able to read
 // as "no rule here", so the ones without one are listed rather than dropped.
 const cset=pCols(kind),cols=cset.shown;
 const colstrip=cset.ruleless.length?el('div',{class:'ovstrip','data-pcols':'1'},
   el('span',{class:'ovlbl'},'Areas with no rule'),
   cset.ruleless.map(a=>el('button',{class:'ovpill',type:'button','data-pcol':a.tag,
     'aria-pressed':PF.cols.indexOf(a.tag)>=0?'true':'false',
     'aria-label':'the '+a.tag+' column',
     title:'no rule for '+PKLABEL[kind].toLowerCase()+' in area '+a.tag+', so no '
       +'column by default. Press to add one — it shows the column and writes '
       +'nothing.',
     onclick:()=>{pToggleCol(a.tag);renderPolicy();}},a.tag)),
   // The sentence is CONDITIONAL, and the empty case is the one worth having: with
   // every area on screen there is nothing hidden, and a line saying otherwise
   // would be the defect this strip exists to prevent, pointing the other way.
   el('span',{class:'mut small'},cset.hidden.length
     ?'no column of their own — press one to add it'
     :'every area has a column')):null;
 const head2=tableHead(['capability','source','rule'].concat(
   cols.map(a=>({attrs:{class:'ar'+(a.active?'':' dormant'),
     title:a.active
       ?('area '+a.tag+' has work in progress, so its rules apply right now')
       :('no phase tagged '+a.tag+' has work in progress, so its rules decide '
         +'nothing until one does')},
     label:a.tag,extra:el('span',{class:'mut'},a.active?'live':'dormant')})),
   ['verdict, and why']));
 const tb=el('tbody');
 shown.forEach(r=>{
  const tr=el('tr',{'data-pcap':r.name,'data-verdict':r.verdict});
  tr.append(el('td',{class:'nm'},r.name,
    r.required?el('span',{class:'badge req',title:'shipped by audit itself — the '
      +'panel refuses to write a policy denying it, and the guard would allow it '
      +'anyway. Not unremovable: disabling the plugin removes it, visibly.'},
      'required'):null,
    r.standIn?el('span',{class:'badge stand',title:'stands in for every tool of '
      +'this server'},'server'):null));
  tr.append(el('td',{},r.source?el('span',{class:'src badge'},r.source):null,
    r.travels===false?el('span',{class:'src badge stays',
      title:r.travelsBasis||''},'stays here'):null));
  if(r.travels===false)tr.classList.add('stranded');
  tr.append(pCell(kind,r,null));
  cols.forEach(a=>tr.append(pCell(kind,r,a.tag)));
  tr.append(el('td',{class:'vd'},
    el('span',{class:'pv '+r.verdict},r.verdict==='violation'?'Violation':'Allowed'),
    el('span',{class:'pbasis'},r.basis||'')));
  tb.append(tr);});
 // THREE empty states, not two. "Everything discovered stays on this machine" is
 // its own answer and its own repair — the Clear button would not bring those rows
 // back, because it is not what removed them.
 const allStray=!strays&&rows.length&&hid===rows.length;
 const body=!shown.length?el('div',{class:'ovempty','data-polempty':'1'},
   allStray
     ?('Every '+PKLABEL[kind].toLowerCase()+' discovered here stays on this '
       +'machine — none would survive a clone, so none is shown. A rule can still '
       +'be written below, and one that NAMES a capability is listed either way.')
     :(rows.length?'No '+PKLABEL[kind].toLowerCase()+' match this filter. '
       :'Nothing of this kind was discovered for this project. A rule can still be '
        +'written for it below — it will apply the day something matches it.'),
   allStray?el('button',{class:'btn small',type:'button','data-polstrayshow':'1',
     onclick:()=>{PF.strays=true;renderPolicy();}},'Show them')
   :(rows.length?el('button',{class:'btn small',type:'button','data-polclear':'1',
     onclick:()=>{PF.q='';PF.bad=false;renderPolicy();}},'Clear filters'):null))
 :el('div',{class:'poltblwrap'+(full?' full':''),id:full?'poltblfull':'poltbl'},
   el('table',{class:'poltbl'},head2,tb));
 return {tools:tools,colstrip:colstrip,body:body};}

/**
 * Draw the whole Policy tab from `POLICY` and `PDRAFT`.
 *
 * Called on every keystroke in the search box as well as on every edit, which
 * is why it is a full redraw with two things explicitly put back: the caret in
 * whichever box was being typed in, and how far down the capability table the
 * reader had scrolled.
 *
 * Reads a lot and returns nothing, in five parts, in this order: what is in
 * force and whether anything is enforcing it; the kind switch and the default;
 * the capability table; the block as written; the savebar. That order is the
 * argument the page is making — a verdict, then the rule behind it, then the way
 * to change it — so a section moved is a different page.
 *
 * @returns {void} the effect IS the DOM. With no policy readable it draws the
 *   refusal-to-edit note and returns early, rather than rendering an empty
 *   policy that a reader could then save over the unreadable one
 */
function renderPolicy(){closeCombo();
 const c=$('#policy');
 // The whole view redraws on every switch, so put back the two things a redraw
 // throws away: the caret in whichever box was being typed in, and how far down
 // the capability table the reader had scrolled.
 const act=document.activeElement,
   keepId=act&&act.id&&(act.id==='polq'||act.id==='polqfull'
     ||act.id==='poladdpat')?act.id:null,
   caret=keepId?act.selectionStart:0,
   // The three ids cover the boxes with a caret in them. Everything else this
   // redraw replaces — the Expand button above all, which is exactly where
   // closing the expanded table puts a keyboard reader — was dropped on the
   // floor, so a disk refresh landing a fifth of a second later threw them to
   // <body>. Nothing is taken from another view: focusKeep is scoped to #policy.
   keepBack=keepId?null:focusKeep('#policy'),
   scrolled=(()=>{const w=$('#poltbl');return w?w.scrollTop:0;})();
 c.textContent='';
 if(!POLICY){c.append(el('div',{class:'card'},el('div',{class:'findings warn'},
   'The capability policy could not be read from this project. Nothing here can be '
   +'edited until it can.')));return;}
 EDITS.policy=()=>policyChanges();
 const pending=policyChanges();
 const findings=el('div',{class:'findings-slot'});
 if(PNOTE){findings.append(...PNOTE);PNOTE=null;}

 // --- what is in force, and whether anything is enforcing it ------------------
 const head=el('div',{class:'card',id:'polhead'});
 head.append(h2h('Capability policy','Which skills, subagents and MCP tools may be '
   +'used in this project. Every verdict below is computed by _policy.resolve — the '
   +'same function guard-capabilities calls — and never by this page.',
   {topic:'policy'}));
 const active=POLICY.active,en=pEnabled();
 if(!en)head.append(el('div',{class:'findings warn','data-pstate':'off'},
   'Turned off. policy.enabled is false, so nothing below is enforced — the rules '
   +'stay written down and decide nothing.'));
 else if(!active)head.append(el('div',{class:'findings ok','data-pstate':'inert'},
   'Inert — every kind defaults to allow and no deny list has an entry, so there is '
   +'nothing this policy can refuse. That is how it ships.'));
 else if(POLICY.enforcement&&POLICY.enforcement.seen)
  head.append(el('div',{class:'findings ok','data-pstate':'enforced'},
   'Active, and the guard has run in this project — last seen '
   +pAgo(POLICY.enforcement.ageDays)+'.'));
 else head.append(el('div',{class:'findings warn','data-pstate':'unproven'},
   'Active, but nothing here has ever seen the guard run in this project. On some '
   +'Claude Code versions Skill / Task / MCP calls are not dispatched to plugin '
   +'hooks at all, and inside a subagent they may not be inherited '
   +'(anthropics/claude-code#43772). Until the marker appears, treat these verdicts '
   +'as documentation rather than enforcement — /audit:doctor says the same.'));
 // The saved state above describes the FILE, not the form. Say so the moment the
 // two differ, or a reader edits a switch, reads "inert" underneath it and
 // concludes the switch did nothing.
 if(pending.length)head.append(el('div',{class:'findings warn','data-ppend':'1'},
   'Described above: the policy as SAVED. You have '
   +plural(pending.length,'unsaved change')
   +' — verdicts are re-read from the server once they are written.'));
 (POLICY.findings||[]).forEach(f=>head.append(
   el('div',{class:'findings err','data-pfinding':'1'},'✗ '+f)));
 (POLICY.warnings||[]).forEach(w=>head.append(el('div',{class:'findings warn'},'! '+w)));
 const enb=el('input',{type:'checkbox',id:'polenabled'});enb.checked=en;
 enb.onchange=()=>pEdit(()=>{const b=pBlock();
   if(enb.checked)delete b.enabled;else b.enabled=false;pPrune();});
 const ovSel=el('select',{id:'polonviol','aria-label':'On a violation - what the hook does'});
 fillOptions(ovSel,(POLICY.onViolationChoices||['deny'])
   .map(v=>[v,v+' — '+(PVIOL[v]||'')]),pOnViolation());
 // Back to the shipped default is written by REMOVING the key, unless the file
 // states it — a block that spells out every default is a block nobody can read,
 // and this one is meant to be read in a pull request.
 ovSel.onchange=()=>pEdit(()=>{const b=pBlock();
   if(ovSel.value===(POLICY.onViolation||'deny')&&!(POLICY.stored||{}).onViolation)
    delete b.onViolation;
   else b.onViolation=ovSel.value;
   pPrune();});
 head.append(el('div',{class:'row'},
   el('span',{class:'f cbf'},enb,flabel('Policy enabled',
     'Off writes policy.enabled:false, which is how you keep the rules and stop '
     +'applying them.',null,'polenabled')),
   // ovSel keeps its aria-label, which still WINS the accessible name over this
   // <label>. The `for` is here for the pointer: it makes the visible words a
   // click target for the select, which the wrapping <label> used to give and a
   // <span> does not. Collapsing the two name sources into the <label> alone is a
   // change that has to re-run the browser census, not one to make blind.
   el('span',{class:'f'},flabel('On a violation','What the hook does when a call '
     +'breaks a rule. warn is deliberately NOT a permission grant — it lets the '
     +'call through and says so.',null,'polonviol'),ovSel)));
 // Which area rules are deciding anything TODAY. An area rule applies only while
 // some phase in that area has work in progress, so a column of denials for a
 // dormant area is inert — and becomes live the moment that phase starts, which is
 // the surprise this line exists to remove.
 const live=(POLICY.activeAreas||[]),
   dormant=(POLICY.areaInfo||[]).filter(a=>!a.active).map(a=>a.tag);
 if(dormant.length||live.length)head.append(el('div',{class:'mut','data-pdormant':'1'},
   'Area rules apply only while that area has work in progress. Live now: '
   +(live.join(', ')||'none')
   +(dormant.length?(' · dormant: '+dormant.join(', ')):'')));
 // BOTH LISTS COME FROM THE PLAN, so with no plan they are empty and the line
 // above did not render at all - and its absence reads as "no area rules here"
 // rather than "this cannot be answered yet". The rest of this view is honest
 // without a plan (the policy lives in the config and the guard enforces it
 // either way); this one half does not, so it says which half.
 else if(!STATE.rollup)head.append(el('div',{class:'mut','data-pnoplan':'1'},
   'Area rules are read from the plan, and there is none yet — so whether any '
   +'area rule is live cannot be answered here. Everything else on this page is '
   +'config, and the guard applies it with or without a plan.'));
 head.append(pHonesty());
 c.append(head);

 // --- one kind at a time ------------------------------------------------------
 const card=el('div',{class:'card'});
 const kstrip=el('div',{class:'ovstrip'},el('span',{class:'ovlbl'},'Kind'));
 PKINDS.forEach(k=>kstrip.append(el('button',{class:'ovpill',type:'button','data-pk':k,
   'aria-pressed':PF.kind===k?'true':'false',
   title:'the '+PKLABEL[k].toLowerCase()+' this project can reach',
   onclick:()=>{PF.kind=k;PF.q='';PF.cols=[];PNOTE=null;renderPolicy();}},
   PKLABEL[k],el('b',{},String(((POLICY.resolved||{})[k]||[]).length)))));
 card.append(kstrip);
 const kind=PF.kind,rows=((POLICY.resolved||{})[kind]||[]);
 const dstrip=el('div',{class:'ovstrip'},el('span',{class:'ovlbl'},'Everything else'),
   ['allow','deny'].map(v=>el('button',{class:'ovpill'+(v==='deny'?' hi':''),
     type:'button','data-pdefault':v,'aria-pressed':pDefault(kind)===v?'true':'false',
     title:v==='deny'
       ?'nothing runs unless a rule allows it — including anything installed later'
       :'everything not denied is allowed',
     onclick:()=>pEdit(()=>{const b=pBlock(),k=b[kind]=b[kind]||{};
       if(v==='deny')k.default='deny';else delete k.default;pPrune();})},v)));
 card.append(dstrip);
 card.append(el('p',{class:'blurb'},pDefault(kind)==='deny'
   ?('Default deny for '+PKLABEL[kind].toLowerCase()+': nothing runs unless it is '
     +'allowed below, and anything installed after today starts refused.')
   :('Default allow for '+PKLABEL[kind].toLowerCase()+': a deny rule is the only '
     +'thing that can refuse anything. An allow rule here has no effect at all, '
     +'which is what the validator warns about.')));
 if(kind==='mcp')card.append(el('p',{class:'blurb'},'What is discoverable is a '
   +'SERVER; a policy matches whole tool names. Each row therefore stands in for '
   +'the server as mcp__<server>__* — a rule aimed at one tool of that server will '
   +'not move it, which is true and better said than quietly averaged.'));

 // --- the capability table ----------------------------------------------------
 // Built by pCapTable so the tab and the expanded dialog are ONE view: same
 // rows, same filter state, same verdicts. Two builders would drift, and a
 // "full screen" copy of a table that disagrees with the table is worse than
 // the scrolling it was meant to relieve.
 const cap=pCapTable(kind,rows,false);
 // Filtered, never stringified: append() writes the literal word "null" for an
 // absent child, unlike el(). The browse dialog paid for that lesson once.
 card.append(...[cap.tools,cap.colstrip,cap.body].filter(Boolean));
 // --- the block as written ----------------------------------------------------
 card.append(el('h3',{class:'sub2'},flabel('Rules as written',
   'The block for this kind, in the order the guard reads it: deny before allow, '
   +'project before area. The switches above write exact names here; a pattern can '
   +'only be written and removed here.')));
 // Dead patterns — the server's own "names nothing" verdict (rules[].dead,
 // computed by _policy.dead_patterns beside the guard's matcher; this client only
 // renders it). Shaped like the composition tab's skillHints: a capped .mut note,
 // data- attributed for the browser checks, and silent while discovery saw nothing
 // at all — against an empty inventory every pattern would read dead, and the
 // note would be noise about the scan rather than the policy.
 if(['skills','agents','mcp'].some(k=>((POLICY.resolved||{})[k]||[]).length))
  ((POLICY.rules||{})[kind]||[]).filter(r=>r.dead).slice(0,3).forEach(r=>card.append(
   el('div',{class:'mut small','data-pdead':(r.scope||'project')+' '+r.list+' '+r.pattern},
    'policy.'+kind+'.'+(r.scope?'areas.'+r.scope+'.':'')+r.list+' "'+r.pattern
    +'" matches nothing installed here — a typo, a removed tool, or a teammate’s; '
    +'a pattern that names nothing '+(r.list==='deny'?'refuses':'allows')+' nothing.')));
 const srv=pServerRules(kind),drafted=pDraftRules(kind);
 if(!drafted.length)card.append(el('div',{class:'mut','data-polnorules':'1'},
   'No rules for '+PKLABEL[kind].toLowerCase()+'. With the default at '
   +pDefault(kind)+', that means '
   +(pDefault(kind)==='deny'?'nothing of this kind may run.':'everything may run.')));
 else{
  const rtb=el('tbody');
  drafted.forEach(r=>{
   const hit=srv[pRuleKey(r)];
   rtb.append(el('tr',{'data-prule':(r.scope||'project')+' '+r.list+' '+r.pattern},
     el('td',{},r.scope
       ?el('span',{class:'badge area',title:'applies only while this area has work '
         +'in progress'},r.scope)
       :el('span',{class:'mut'},'project')),
     el('td',{class:'lst','data-list':r.list},r.list),
     el('td',{class:'pat'},r.pattern),
     el('td',{class:'mut',title:hit&&hit.matches&&hit.matches.length
       ?hit.matches.join(', ')+(hit.n>hit.matches.length
         ?(' +'+(hit.n-hit.matches.length)+' more'):''):''},
       hit?(hit.n?(hit.n+' installed'):'nothing installed matches it today')
         :'not saved yet'),
     el('td',{},el('button',{class:'btn small',type:'button',
       'aria-label':'remove '+r.list+' rule '+r.pattern,
       onclick:()=>pEdit(()=>pDropPattern(kind,r.list,r.scope,r.pattern))},'×'))));});
  card.append(el('table',{class:'polrules'},
    tableHead(['scope','list','pattern','matches now',null]),rtb));}
 card.append(pAddRow(kind));
 c.append(card);

 // --- save --------------------------------------------------------------------
 const save=el('button',{class:'btn primary','data-psave':'1',onclick:async()=>{
   const chg=await confirmSave({rows:policyChanges,
     title:'Save capability policy',scope:'policy',
     empty:'the policy is unchanged',
     note:'writes .claude/audit.config.json'});
   if(!chg)return;
   const res=await api('PUT','/api/policy',{policy:PDRAFT||{}});
   findings.replaceChildren(findingsBox(res));
   saveOutcome(res,chg,'the config',findings);
   if(!res.ok)return;
   const cfg=JSON.parse(JSON.stringify(STATE.config||{}));
   cfg.policy=PDRAFT||{};STATE.config=cfg;
   // Re-read rather than assume: every verdict on this page is the server's, and
   // the only way they become true of what was just written is to ask again. The
   // box that says what happened is carried across the redraw, not re-derived.
   POLICY=await api('GET','/api/policy').catch(()=>POLICY);
   PDRAFT=pClone(POLICY&&POLICY.stored);
   PNOTE=[...findings.childNodes];
   renderPolicy();
 }},'Save policy');
 // Two things this surface does differently, both because `pEdit` re-renders the
 // whole view on every edit: revert restores the draft and lets pEdit repaint
 // (calling renderPolicy here would fight it), and the count is refreshed once
 // per render instead of from a view listener, since the render IS the refresh.
 const discard=discardButton({key:'policy',rows:policyChanges,
   title:'Discard unsaved policy changes',
   note:'nothing is written; the form goes back to the saved block',
   toast:'discarded — the form is back to the saved policy',
   revert:()=>pEdit(()=>{PDRAFT=pClone(POLICY&&POLICY.stored);})});
 refreshDiscard(discard,pending.length);
 c.append(el('div',{class:'savebar'},save,discard,
   el('span',{class:'mut small'},'writes .claude/audit.config.json'),findings));

 // The expanded copy is refilled from the same state, in the same pass — before
 // focus is restored, since the box the caret belongs in may be inside it.
 polFullFill();
 restoreCaret(keepId?document.getElementById(keepId):null,caret,keepBack);
 if(scrolled){const w=$('#poltbl');if(w)w.scrollTop=scrolled;}}

// How long ago, in words. The panel never decides whether that is TOO long: how
// stale a marker may be is /audit:doctor's judgement, and a second threshold here
// is a threshold that can disagree with it.
/**
 * How long ago, in words.
 *
 * Deliberately never says whether that is TOO long: how stale the enforcement
 * marker may be is /audit:doctor's judgement, and a second threshold here is a
 * threshold that can disagree with it.
 *
 * @param {number|null} days - age in days, fractional; null when the marker was
 *   found but its age could not be read
 * @returns {string} a phrase that fits after "last seen", including for null —
 *   which says the time is unknown rather than defaulting to a number
 */
function pAgo(days){
 if(days==null)return 'at an unknown time';
 if(days<1/24)return 'within the hour';
 if(days<1)return 'today';
 return plural(Math.round(days),'day')+' ago';}

// One switch, for one capability, in one scope.

/**
 * One cell of the capability table: the allow/deny/none select for this row in
 * this scope, plus an "unsaved" badge when the draft and the saved block
 * disagree about it.
 *
 * Both sides of that comparison go through `pRuleOf`, so the badge means "this
 * control would change the file" and not "this control looks different".
 *
 * A row the plugin ships is DISABLED here and says why. That is the one promise
 * this panel makes about its own components, kept mechanically: the server
 * refuses such a policy too — its validator calls it a finding — so this is the
 * friendly half of a rule enforced somewhere it cannot be edited around.
 *
 * @param {string} kind - a kind from `PKINDS`
 * @param {PolicyRow} r - the row this cell belongs to
 * @param {string|null} tag - an area tag, or null for the project column
 * @returns {HTMLTableCellElement} the cell; the change is written through
 *   `pEdit` on the select's own event, so this returns no handle to it
 */
function pCell(kind,r,tag){
 const cur=pRuleOf(PDRAFT,kind,r.name,tag),
   was=pRuleOf(POLICY.stored,kind,r.name,tag),
   moved=cur!==was;
 const sel=el('select',{class:'prule','data-set':cur||null,
   'data-prule':r.name+(tag?('@'+tag):''),
   'aria-label':(tag?('rule for area '+tag+', '):'project rule for ')+r.name});
 fillOptions(sel,[['','—'],['allow','allow'],['deny','deny']],cur);
 if(r.required){
  // The one promise this panel makes about its own components, kept mechanically:
  // the control cannot be moved at all. The server refuses such a policy too — the
  // validator calls it a FINDING — so this is the friendly half of a rule that is
  // enforced somewhere it cannot be edited around.
  sel.disabled=true;
  sel.title='required by audit — the panel refuses to write a policy denying it';}
 else sel.onchange=()=>pEdit(()=>pSetRule(kind,r.name,tag,sel.value));
 return el('td',{class:moved?'pend':null},sel,
   moved?el('span',{class:'badge pend',title:'unsaved: '
     +(was?('was '+was):'no rule')+' → '+(cur||'no rule')},'unsaved'):null);}

// Writing a pattern, which is the half the per-row switches cannot do.

/**
 * The add-a-rule row: a pattern box, which list, which scope, and the note that
 * says how a glob is matched.
 *
 * The per-row switches can only ever write EXACT names, so without this the form
 * could not express a rule like `code-*` — and a form that cannot express a rule
 * cannot be trusted to save one, because the PUT replaces the block wholesale.
 *
 * @param {string} kind - a kind from `PKINDS`
 * @returns {HTMLElement} the controls and the note. An empty or blank pattern is
 *   refused in silence rather than added: there is nothing to report about a
 *   press on an empty box
 */
function pAddRow(kind){
 const pat=el('input',{id:'poladdpat',placeholder:'pattern…  e.g.  code-*',
   'aria-label':'pattern to add'});
 const lst=el('select',{'aria-label':'which list'},
   el('option',{value:'deny'},'deny'),el('option',{value:'allow'},'allow'));
 const scope=el('select',{'aria-label':'scope'},el('option',{value:''},'project'),
   (POLICY.areaInfo||[]).map(a=>el('option',{value:a.tag},
     'area '+a.tag+(a.active?'':' (dormant)'))));
 const add=()=>{const p=pat.value.trim();if(!p)return;
   pEdit(()=>{pAddPattern(kind,lst.value,scope.value||null,p);pat.value='';});};
 pat.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();add();}});
 return el('div',{},
   el('div',{class:'poladd'},pat,lst,scope,
     el('button',{class:'btn small',type:'button','data-poladd':'1',onclick:add},
       'Add rule')),
   el('p',{class:'blurb'},'Shell-style globs, matched case-sensitively against the '
     +'whole name: code-* covers code-review and code-simplifier, and matches '
     +'nothing else. Deny beats allow, and one live area’s deny is enough. A '
     +'rule aimed at audit’s own components is refused when you save — with '
     +'the validator’s own words, because it would not take effect.'));}

// The four limits, from SECURITY.md, in the place someone is most likely to
// believe the opposite: a page full of verdicts looks like enforcement. Shut by
// default — read once, remembered — and never removed, because a switchboard that
// does not state them is selling something it cannot deliver.
/**
 * The four limits this policy cannot hold, from SECURITY.md, put on the surface
 * that most invites believing the opposite — a page full of verdicts looks like
 * enforcement.
 *
 * Shut by default, so it costs a reader nothing once they have read it, and
 * never removable: a switchboard that does not state these is selling something
 * it cannot deliver.
 *
 * @returns {HTMLDetailsElement} the disclosure. Native `<details>`, so opening
 *   and closing it needs no handler of ours
 */
function pHonesty(){
 const d=el('details',{class:'polhonest','data-polhonest':'1'});
 d.append(el('summary',{},'What this cannot hold — four limits'));
 d.append(el('ol',{},
  el('li',{},el('b',{},'Subagent hooks are not inherited on every version'),
    ' (anthropics/claude-code#43772). Inside a subagent the policy may never be '
    +'consulted. The only local evidence is the marker the guard leaves when it '
    +'runs, which is what the line above reports.'),
  el('li',{},el('b',{},'It denies the tool, not the knowledge.'),
    ' Denying a skill stops the Skill call. It does not unread a document the '
    +'model already has, and it does not stop the same work being done by hand.'),
  el('li',{},el('b',{},'Your own switch outranks it.'),
    ' Anyone can disable a plugin, and a disabled plugin’s hooks do not run — '
    +'which is why audit’s own components are not deniable here. The honest '
    +'claim is not "unremovable", it is "not removable quietly".'),
  el('li',{},el('b',{},'Hooks cannot gate hooks.'),
    ' Another plugin’s hooks run in the same session and nothing here can '
    +'refuse them. This panel inventories what is installed; it never claims to '
    +'enforce against it.')));
 return d;}
