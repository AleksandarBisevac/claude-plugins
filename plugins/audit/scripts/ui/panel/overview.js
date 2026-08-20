// ---------- Overview ----------
// The rollup arrives with tasks.byStatus, bugs.byStatus, areas and ready[] already
// computed, and this view used to drop all four on the floor: four grey total chips
// and a flat list of every phase. So the numbers you steer by — what is in
// progress, what is blocked, which bugs are open, what can start right now — were
// the numbers the panel had and would not show.
//
// The filter state lives OUT here for the same reason COMPF does: the 5s run-status
// poll repaints this view, so a filter held in the render closure would be wiped by
// a badge update the reader never asked for, five seconds after they set it.

// ---------- out-of-band change handling ----------
// Everything in this section must stay BELOW the Overview marker above, and a
// selftest holds it there: it slices the assembled page from pollRunStatus to that
// exact marker text and asserts the poll path never reaches into Settings. The full
// refetch lives out here, reached only through the fingerprint hand-off inside
// pollRunStatus — so moving either the marker or these functions across it silently
// changes what that assertion covers.
/**
 * Say, once, that the file moved under a form holding unsaved edits.
 *
 * Persistent rather than a toast: the reader may be mid-sentence and look up
 * minutes later, and the thing they need to know is still true. Idempotent, so
 * five disk changes during one edit leave one notice — a stack of identical
 * warnings reads as five different problems.
 * @param {'guards'|'comp'|'policy'} id - the view whose findings-slot gets the
 *   notice; a view with no slot on screen is a no-op
 * @returns {void}
 */
function staleNote(id){const slot=$('#'+id+' .findings-slot');
 if(!slot||slot.querySelector('[data-stale]'))return;
 slot.append(el('div',{class:'findings warn','data-stale':id},
  'The file changed on disk while this form holds unsaved edits. Save stays '
  +'safe — what was applied is echoed back and compared — and Discard now '
  +'reloads the file as it is on disk.'));}
/**
 * Re-read everything from disk and redraw the views that can be redrawn safely.
 *
 * Reached only from the poll's fingerprint hand-off — never on a timer — so by
 * the time it runs, the file really has changed. A clean view is re-rendered; a
 * dirty one keeps its edits and gets staleNote instead, because re-rendering it
 * would silently eat what somebody typed.
 *
 * Never rejects: a stale view beats a dead panel, so a failed read leaves the
 * page exactly as it was.
 * @returns {Promise<void>} resolves once the re-render is queued and the scroll
 *   position has been scheduled for restoration
 */
async function refreshFromDisk(){
 // BEFORE the state swap, and that is this line's position rather than
 // dirtyViews' business: the registered closures compare each form against
 // STATE, so a swapped STATE would misjudge every open form. What counts as
 // dirty - and why an unreadable surface counts - belongs to dirtyViews.
 const dirty=dirtyViews();
 const y=window.scrollY;
 try{
  STATE=await api('GET','/api/state');
  USAGE=await api('GET','/api/usage').catch(()=>USAGE);
  BANDS=null;MITEMS=null;
  const pol=await api('GET','/api/policy').catch(()=>null);
  renderViewer();
  // Only CLEAN views re-render: renderComp resets its patch and renderSettings
  // reclones cfg, so re-rendering a dirty one would eat the human's edits.
  // A dirty view keeps them and gets the persistent notice —
  // the applied-diff echo already covers the conflicting-save endgame.
  // The findings-slot NODES are carried across the re-render: an own save moves
  // the disk stamp too, and the refresh it triggers must not eat the "saved"
  // card whose 5s clock belongs to the node, or the refusal card someone has
  // not read yet.
  /**
   * Re-render one view while keeping whatever is in its findings slot.
   * @param {'guards'|'comp'|'policy'} id - the view's container id
   * @param {() => void} fn - that view's renderer, called for its side effect
   * @returns {void}
   */
  const reRender=(id,fn)=>{const slot=$('#'+id+' .findings-slot');
   const keep=slot?[...slot.childNodes]:[];
   fn();
   const s2=$('#'+id+' .findings-slot');
   if(s2&&keep.length)s2.append(...keep);};
  if(!dirty.guards)reRender('guards',renderSettings);else staleNote('guards');
  if(!dirty.comp)reRender('comp',renderComp);else staleNote('comp');
  if(pol){POLICY=pol;
   if(!dirty.policy){PDRAFT=pClone(POLICY&&POLICY.stored);
    reRender('policy',renderPolicy);}
   else staleNote('policy');}
  renderOver();
  renderUsage();
 }catch(e){/* a stale view beats a dead panel */}
 // The Usage chart remounts on its own rAF; put the reader back where they were.
 requestAnimationFrame(()=>window.scrollTo(0,y));}

// Overview follows the report's table — the same segments, the same three views,
// the same words. `segOf` is the client twin of _report_html._seg_of and is pinned
// against it by name; two surfaces disagreeing about which phases are "finished"
// is the kind of drift a reader reads as a bug in the plan.
/**
 * @type {Object<string, string[]>} which segments each of the three views shows.
 * Keyed by the value of the view select, so an unknown key falls back to `all`
 * rather than showing nothing.
 */
const SEG_VIEWS={active:['active','pending'],archived:['archived'],
  all:['active','pending','archived']};
/**
 * Which of the three segments a phase status belongs to.
 *
 * @param {string} st - a phase status from the manifest
 * @returns {'archived'|'active'|'pending'} a terminal status is archived, a
 *   status that needs a human is active, and everything else — an unknown status
 *   included — is pending, so a status this build has never heard of is still
 *   listed rather than dropped
 */
const segOf=st=>st==='done'||st==='cancelled'?'archived'
  :(st==='in_progress'||st==='blocked')?'active':'pending';
/**
 * @type {{q: string, ts: string, bs: string, byArea: boolean,
 *   sort: 'plan'|'progress'|'status', view: ('active'|'archived'|'all'|null),
 *   open: Object<string, boolean>}}
 * The Overview filter, hoisted out of the render because the 5s poll repaints
 * this view: held in the render closure it would be wiped by a badge update five
 * seconds after the reader set it. `open` and `view` ride it for the same reason
 * — a badge repaint must not fold every row somebody opened. `view: null` means
 * "not chosen yet" and is what lets the first render pick a default from the
 * plan; '' in a status filter means "no filter", never a status.
 */
const OVF={q:'',ts:'',bs:'',byArea:false,sort:'plan',view:null,open:{}};
// Nothing-to-see-first: the statuses that need a human come before the ones that
// do not, in the strips and in the status sort. Plan order is still the default —
// a plan is written in an order and that order means something.
/** @type {string[]} task statuses, most-in-need-of-a-human first */
const OVORDER=['in_progress','blocked','pending','done'];
/** @type {string[]} bug statuses, on the same principle */
const OVBUGORDER=['open','triaged','in_progress','fixed','wontfix'];
/**
 * Where a status sits in one of those orders.
 * @param {string[]} o - OVORDER or OVBUGORDER
 * @param {string} s - the status to place
 * @returns {number} its index, or the list's length for a status the order never
 *   names — which sorts every unknown status last without dropping it
 */
const ovRank=(o,s)=>{const i=o.indexOf(s);return i<0?o.length:i;};
/**
 * Whether anything the Clear button clears is set.
 *
 * Deliberately does NOT include `view` or `byArea`: those are ways of looking at
 * the whole plan rather than filters over it, and offering to "clear" them would
 * make the count line lie about what it is counting.
 * @returns {boolean} true when a search term or either status filter is set
 */
const ovAnyFilter=()=>!!(OVF.q.trim()||OVF.ts||OVF.bs);
/**
 * One strip pill: a legend entry and a filter toggle in a single control.
 *
 * @param {string} status - the machine status this pill means, '' for a cut that
 *   is not a status at all; it lands in data-status, which is what the CSS themes
 *   off AND what a reader inspecting the DOM is told the pill means
 * @param {number} n - the count, rendered bold and last
 * @param {string} text - the human label
 * @param {boolean} on - whether this pill is the active filter
 * @param {() => void} onclick - what pressing it does
 * @param {string} [tip] - the title attribute; omitted becomes ''
 * @param {string} [cls] - an extra class for a pill that needs its own colour
 *   rather than borrowing another status's machine value
 * @returns {HTMLButtonElement} a real button, so it is keyboard reachable and
 *   announced as pressable without a hand-written role/tabindex/keydown trio
 */
function ovPill(status,n,text,on,onclick,tip,cls){
 return el('button',{class:'ovpill'+(cls?' '+cls:''),type:'button','data-status':status||'',
  'aria-pressed':on?'true':'false',title:tip||'',onclick:onclick},text,el('b',{},String(n)));}
/**
 * Copy a command, and say so on the button that did it.
 *
 * A copy button that fails silently is worse than no copy button: the async
 * clipboard can be refused — an insecure context, a permission — and the reader
 * is left believing they have the command. So there are three outcomes and all
 * three are visible: the label flips to Copied, or the hidden-textarea fallback
 * runs and flips it, or a toast hands the reader the text to copy by hand.
 * @param {HTMLButtonElement} btn - the button pressed; its label is restored
 *   after 1.6s, read at call time so a re-render cannot strand the old text
 * @param {string} text - what to put on the clipboard
 * @returns {void}
 */
function ovCopy(btn,text){
 const done=()=>{const was=btn.textContent;btn.textContent='Copied';
  setTimeout(()=>{btn.textContent=was;},1600);};
 const manual=()=>{const ta=el('textarea',{style:'position:fixed;top:-1000px;opacity:0'});
  ta.value=text;document.body.append(ta);ta.select();
  let ok=false;try{ok=document.execCommand('copy');}catch(e){ok=false;}
  ta.remove();if(ok)done();else toast('could not copy — the command is '+text,'err');};
 copyText(text,done,manual);}
/**
 * An ISO stamp as 'YYYY-MM-DD HH:MM', to the minute.
 *
 * @param {*} v - an ISO timestamp, or anything falsy
 * @returns {string} the trimmed stamp; '' for a missing value, and the input
 *   unchanged when it carries no 'T' to cut at — a date-only value stays a date
 *   rather than being truncated to nothing
 */
const ovStamp=v=>{const s=String(v||'');if(!s)return '';
 const i=s.indexOf('T');return i<0?s:s.slice(0,i)+' '+s.slice(i+1,i+6);};
/**
 * A phase's tasks, in the columns the report's table uses — id, title, status,
 * risk (coloured TEXT, not a pill), commit and when it finished.
 *
 * Read-only on purpose: this tab is for reading the plan, and the one place that
 * edits it is named at the end rather than reached by accident.
 * @param {{id: string, desiredOutcome: (string|undefined)}} p - the phase, from
 *   the rollup
 * @returns {HTMLDivElement} the detail box; a phase with no tasks gets a
 *   sentence saying so rather than an empty table
 */
function ovDetail(p){
 const tasks=((STATE.composition||{}).tasks||[]).filter(t=>t.phaseId===p.id);
 const box=el('div',{class:'ovdetail','data-ovdetail':p.id});
 if(!tasks.length)box.append(el('div',{class:'mut small'},'This phase has no tasks.'));
 else{
  const tb=el('tbody');
  tasks.forEach(t=>{
   const when=ovStamp(t.completedAt||t.startedAt);
   tb.append(el('tr',{'data-ovtask':t.id||''},
    el('td',{class:'mono'},t.id||''),
    el('td',{class:'ovt'},t.title||''),
    el('td',{},el('span',{class:'st','data-status':t.status||''},label(t.status))),
    el('td',{},t.risk?el('span',{class:'rk','data-risk':t.risk},t.risk):null),
    el('td',{class:'mono'},t.commit?String(t.commit).slice(0,9):''),
    // A start stamp is labelled as one, or an unfinished task reads as finished.
    el('td',{class:'mut'},when+(t.completedAt?'':(when?' (started)':'')))));});
  box.append(el('table',{class:'ovtasks'},
    tableHead(['id','title','status','risk','commit','done (UTC)']),tb));}
 if(p.desiredOutcome)box.append(el('div',{class:'mut small'},'Desired: '+p.desiredOutcome));
 box.append(el('div',{class:'row',style:'margin-top:.4rem'},
   el('button',{class:'btn small','data-ovedit':p.id,type:'button',
     title:'Composition is where tasks, models and skills are changed',
     onclick:()=>openInComp(p.id)},'Edit in Composition')));
 return box;}

/**
 * Restack a view's cards into the order the theme asks for.
 *
 * The renderers append in their own order and stamp each top-level card with a
 * name; this reorders what is already DRAWN. Reordering after the fact rather
 * than parameterising every renderer keeps the ordering in one place — and a
 * card the theme does not name simply keeps its position at the end, so a theme
 * written today never hides a card added next year.
 * @param {string} view - the container id, which is also the key in
 *   `THEME.cards` and in a theme's `layout.order`
 * @returns {void} a missing container, an unread theme, or a view the order
 *   never names are all no-ops — the drawn order stands
 */
function applyCardOrder(view){
 const host=document.getElementById(view);
 if(!host||!THEME)return;
 // The DRAFT order when the editor is holding one, the saved theme otherwise —
 // tLayout answers that in one place, the same three-layer answer the colours
 // get. An order you can only see after saving is not a preview, and this is
 // the one part of the look that is judged by looking at another tab.
 const lay=tLayout();
 const want=(lay.order||{})[view];
 if(!Array.isArray(want)||!want.length)return;
 const named={};
 [...host.children].forEach(n=>{const k=n.getAttribute&&n.getAttribute('data-card');
  if(k)named[k]=n;});
 want.forEach(k=>{if(named[k])host.append(named[k]);});
 // Anything the order did not mention stays after it, in its drawn order.
 [...host.children].forEach(n=>{const k=n.getAttribute&&n.getAttribute('data-card');
  if(k&&want.indexOf(k)<0)host.append(n);});}

/**
 * Draw the whole Overview tab: the phase rollup, the plan gate, what is ready
 * now, and the bugs.
 *
 * Called by the 5s poll as well as by every filter control, which is what
 * shapes it: it may run at any moment under the reader's hands, so the caret is
 * saved and restored, the filter lives in OVF rather than in this closure, and
 * nothing here fetches. It reads STATE, RUNSTATUS and THEME and rebuilds.
 * @returns {void} returns early after one message when there is no manifest —
 *   a plan that does not exist is said out loud, not drawn as an empty table
 */
function renderOver(){const c=$('#over');const r=STATE.rollup;
 // The poll repaints this view under the reader's hands. Put the caret back where
 // it was, or typing a five-letter search while a colleague takes a phase lock
 // loses the last three letters and the focus with them.
 const act=document.activeElement,keepQ=!!(act&&act.id==='ovq'),
   caret=keepQ?act.selectionStart:0,
   keepBack=keepQ?null:focusKeep('#over');
 c.textContent='';
 // data-card names this card for the theme's layout.order. Stamped where the
 // card is BUILT, so a renamed card renames its ordering key with it.
 const card=el('div',{class:'card','data-card':'phases'});
 if(!r){card.append(el('div',{class:'mut'},'No manifest at '+STATE.manifestPath+'. Run /audit:init.'));c.append(card);return;}
 const vstate=r.valid?el('div',{class:'findings ok'},'✓ manifest valid ('+r.warnings+' warnings)')
   :manifestFindingsBox(r.findings,STATE.manifestFindings||[]);
 card.append(vstate);
 const rs=RUNSTATUS||STATE.runStatus||{index:null,phases:{}};
 if(rs.index){const h=rs.index.hostname||'?';const dead=rs.index.live===false;
  card.append(el('div',{class:'findings warn',title:rs.index.liveBasis||''},
   (dead?'⚠ index lock held by no live run':'⚙ index locked (structural op / id allocation)')
   +(h?' · '+h:'')+(rs.index.startedAt?' · since '+rs.index.startedAt:'')
   +(dead?' · '+(rs.index.liveBasis||''):'')));}

 // --- the two strips: legend and filter in one control ------------------------
 // Per-phase status counts come from the composition (the same manifest), because
 // the rollup carries done/total per phase and nothing finer — and "which phases
 // have work in progress" is the question the strip is for.
 const tasks=(STATE.composition||{}).tasks||[];
 const pStatus={};
 tasks.forEach(t=>{const m=pStatus[t.phaseId]=pStatus[t.phaseId]||{};
  const s=t.status||'';m[s]=(m[s]||0)+1;});
 const tBy=r.tasks.byStatus||{},bBy=r.bugs.byStatus||{};
 const tstrip=el('div',{class:'ovstrip'},el('span',{class:'ovlbl'},'Tasks'),
   el('span',{class:'mut'},r.tasks.total+' total'));
 Object.keys(tBy).sort((a,b)=>ovRank(OVORDER,a)-ovRank(OVORDER,b)).forEach(s=>{
  tstrip.append(ovPill(s,tBy[s],label(s),OVF.ts===s,
    ()=>{OVF.ts=OVF.ts===s?'':s;renderOver();},
    'show only phases carrying '+label(s).toLowerCase()+' tasks'));});
 const bstrip=el('div',{class:'ovstrip'},el('span',{class:'ovlbl'},'Bugs'),
   el('span',{class:'mut'},r.bugs.total+' total · '+r.bugs.open+' open'));
 Object.keys(bBy).sort((a,b)=>ovRank(OVBUGORDER,a)-ovRank(OVBUGORDER,b)).forEach(s=>{
  bstrip.append(ovPill(s,bBy[s],label(s),OVF.bs===s,
    ()=>{OVF.bs=OVF.bs===s?'':s;renderOver();},'show only '+label(s).toLowerCase()+' bugs'));});
 // Not a status — a severity cut across the open ones. It keeps its own class
 // rather than borrowing data-status="blocked" for the colour: the machine value
 // in data-status is what the CSS themes off AND what a reader inspecting the DOM
 // is told this pill means, and "blocked" would be a plain lie there.
 if(r.bugs.openHighSeverity)bstrip.append(ovPill('',r.bugs.openHighSeverity,
   'High severity, open',OVF.bs==='!high',()=>{OVF.bs=OVF.bs==='!high'?'':'!high';renderOver();},
   'open bugs filed high, critical, blocker, sev1 or p0','hi'));
 card.append(tstrip,bstrip);

 // --- tools: search, sort, group by area --------------------------------------
 const qIn=el('input',{type:'search',id:'ovq',value:OVF.q,
   placeholder:'search phases — id, title, area, outcome…','aria-label':'search phases'});
 qIn.addEventListener('input',()=>{OVF.q=qIn.value;renderOver();});
 const sortSel=el('select',{'aria-label':'sort phases',
   onchange:e=>{OVF.sort=e.target.value;renderOver();}});
 fillOptions(sortSel,[['plan','plan order'],['progress','progress'],
   ['status','status']],OVF.sort);
 const tools=el('div',{class:'ovtools'},qIn,el('span',{class:'filtlbl'},'sort:'),sortSel);
 const areaTags=Object.keys(r.areas||{});
 if(areaTags.length){
  const cb=el('input',{type:'checkbox',id:'ovarea'});cb.checked=OVF.byArea;
  cb.onchange=()=>{OVF.byArea=cb.checked;renderOver();};
  tools.append(el('label',{class:'inl',for:'ovarea'},cb,'group by area'));}
 // The same three views the report offers, defaulting the same way — a finished
 // plan opens on `all` rather than on an empty table. Decided once, on the first
 // render only, so a later choice of the reader's is never overwritten.
 if(OVF.view===null){
  const segs=new Set((r.phases||[]).map(p=>segOf(p.status)));
  OVF.view=(segs.has('active')||segs.has('pending'))?'active':'all';}
 const viewSel=el('select',{'aria-label':'which phases to show','data-ovview':'1',
   onchange:e=>{OVF.view=e.target.value;renderOver();}});
 fillOptions(viewSel,[['active','Active & pending'],
   ['archived','Archived (done & cancelled)'],['all','All phases']],OVF.view);
 tools.append(el('span',{class:'filtlbl'},'view:'),viewSel);
 const count=el('span',{class:'count',style:'margin-left:auto'});
 tools.append(count);
 if(ovAnyFilter())tools.append(el('button',{class:'btn small',type:'button','data-ovclear':'1',
   onclick:()=>{OVF.q='';OVF.ts='';OVF.bs='';renderOver();}},'Clear filters'));
 card.append(el('h2',{},'Phases'),tools);

 // --- phases -------------------------------------------------------------------
 const term=OVF.q.trim().toLowerCase();
 const hitP=p=>(!term||((p.id+' '+(p.title||'')+' '+(p.area||[]).join(' ')+' '
     +(p.desiredOutcome||'')).toLowerCase().includes(term)))
   &&(!OVF.ts||!!((pStatus[p.id]||{})[OVF.ts]));
 // Matched and in-view are two different sets on purpose: the difference between
 // them is what the "outside this view" line is able to report.
 const matched=r.phases.filter(hitP);
 const inView=p=>(SEG_VIEWS[OVF.view]||SEG_VIEWS.all).includes(segOf(p.status));
 const ordered=matched.filter(inView);
 const outside=matched.length-ordered.length;
 const pct=p=>p.total?100*p.done/p.total:0;
 if(OVF.sort==='progress')ordered.sort((a,b)=>pct(b)-pct(a));
 else if(OVF.sort==='status')ordered.sort((a,b)=>ovRank(OVORDER,a.status)-ovRank(OVORDER,b.status));
 /**
  * One phase as a pressable row, with its detail beneath when it is open.
  * @param {{id: string, status: string, title: (string|undefined),
  *   area: (string[]|undefined), done: number, total: number,
  *   desiredOutcome: (string|undefined)}} p - the phase, from the rollup
  * @returns {HTMLElement} the row itself when the phase is closed, or a wrapper
  *   holding the row and its detail when it is open — so the caller appends one
  *   node either way
  */
 function phaseRow(p){const w=Math.round(pct(p));
  const st=(rs.phases||{})[p.id]||{};let runBadge=null;
  if(st.lock){const h=st.lock.hostname||'?';const dead=st.lock.live===false;
   // "running" is a claim about a process. Say it only when the pid was probed
   // and answered; an abandoned lock says so, with the basis in the tooltip.
   runBadge=el('span',{class:'badge '+(dead?'held':'run'),
    title:(st.lock.liveBasis||'phase lock held')+(st.lock.startedAt?' · since '+st.lock.startedAt:'')},
    (dead?'○ lock, no live run':'● running')+(h?' · '+h:''));}
  else if(st.claim){const s=(st.claim.sessionId||'').slice(0,8);
   runBadge=el('span',{class:'badge claim',title:'claimed'+(st.claim.branch?' on '+st.claim.branch:'')},'◷ claimed'+(s?' · '+s:''));}
  const areaBadges=(p.area||[]).map(a=>el('span',{class:'badge area',title:'area'},a));
  // One control, not a row with a handler bolted on: keyboard reachable and
  // announced as pressable without a hand-written role/tabindex/keydown trio.
  // The row's own counts, in the report's words. A phase in progress with two
  // stuck tasks reads as "in progress" and nothing else without them, and the
  // bar cannot say a task was dropped.
  const nBlocked=(pStatus[p.id]||{}).blocked||0,nCancelled=(pStatus[p.id]||{}).cancelled||0;
  const open=!!OVF.open[p.id];
  // A click OPENS the phase here. It used to jump to Composition — a tab for
  // EDITING tasks, models and skills — so "let me look at this phase" landed
  // the reader in a form, with their Overview filters left behind. Composition
  // is still one press away, named, inside the detail.
  const row=el('button',{class:'ovrow'+(open?' open':''),type:'button',
    'data-status':p.status||'','data-phase':p.id,'aria-expanded':open?'true':'false',
    title:(open?'collapse ':'expand ')+p.id,
    onclick:()=>{OVF.open[p.id]=!open;renderOver();}},
   el('span',{class:'ovtri'}),
   el('span',{class:'pid'},p.id),
   el('span',{class:'ptitle'},p.title||''),
   el('span',{class:'st','data-status':p.status||''},label(p.status)),
   areaBadges,runBadge,
   // Only when the phase itself is not blocked: the status pill already says
   // that, and two words for one fact reads as two problems.
   nBlocked&&p.status!=='blocked'?el('span',{class:'pblocked',
     title:plural(nBlocked,'task in this phase is blocked',
       'tasks in this phase are blocked')},nBlocked+' blocked'):null,
   nCancelled?el('span',{class:'pcancelled',
     title:plural(nCancelled,'task in this phase was cancelled',
       'tasks in this phase were cancelled')},nCancelled+' cancelled'):null,
   OVF.ts?el('span',{class:'ovmatch'},((pStatus[p.id]||{})[OVF.ts]||0)+' '+label(OVF.ts).toLowerCase()):null,
   el('span',{class:'bar'},el('i',{style:'width:'+w+'%'})),
   el('span',{class:'mut'},p.done+'/'+p.total),
   // The line the plan is actually about. It was in the rollup all along and the
   // panel showed the title, which says what the phase is called, not what it is for.
   p.desiredOutcome?el('span',{class:'ovout',title:p.desiredOutcome},p.desiredOutcome):null);
  if(!open)return row;
  return el('div',{class:'ovwrap'},row,ovDetail(p));}
 if(!ordered.length){
  card.append(el('div',{class:'ovempty'},'No phase matches this filter. ',
    el('button',{class:'btn small',type:'button','data-ovclear':'1',
      onclick:()=>{OVF.q='';OVF.ts='';OVF.bs='';renderOver();}},'Clear filters')));}
 else if(OVF.byArea){
  // A phase with two tags is listed under both — the same rule the rollup counts
  // by, so the group headings add up to more than the plan when tags overlap, and
  // saying so here is cheaper than a reader discovering it by arithmetic.
  areaTags.sort().forEach(tag=>{
   const inTag=ordered.filter(p=>(p.area||[]).includes(tag));
   if(!inTag.length)return;
   const g=r.areas[tag]||{};
   card.append(el('div',{class:'ovgrp'},el('span',{class:'gname'},tag),
     el('span',{class:'mut'},inTag.length+' of '+g.phases+' phases · '+g.done+'/'+g.total+' tasks')));
   inTag.forEach(p=>card.append(phaseRow(p)));});
  const untagged=ordered.filter(p=>!(p.area||[]).length);
  if(untagged.length){card.append(el('div',{class:'ovgrp'},el('span',{class:'gname'},'untagged'),
    el('span',{class:'mut'},untagged.length+' phases')));
   untagged.forEach(p=>card.append(phaseRow(p)));}}
 else ordered.forEach(p=>card.append(phaseRow(p)));
 // Matches the VIEW is holding back — the report says this too, in the same
 // words, and for the same reason: a filter that quietly finds nothing is
 // indistinguishable from a plan that holds nothing.
 if(outside>0)card.append(el('div',{class:'ovoutside','data-ovoutside':String(outside)},
   outside+(outside===1?' phase matches':' phases match')+' outside this view — ',
   el('button',{class:'btn small',type:'button','data-ovviewall':'1',
     onclick:()=>{OVF.view='all';renderOver();}},'Show all phases')));
 count.textContent=ovAnyFilter()?(ordered.length+' / '+r.phases.length+' phases')
   :(r.phases.length+' phases · '+r.tasks.total+' tasks');
 c.append(card);

 // --- plan gate ----------------------------------------------------------------
 // The tier the gate is in, WHY (server-computed by the hooks' own functions —
 // never re-derived here), whether a single-use bypass is armed, and the tail
 // of the gate events feed. The block rides /api/runstatus and is part of
 // runStatusKey, so a fresh verdict repaints this card within one poll.
 const g=rs.gate;
 if(g){
  const gcard=el('div',{class:'card',id:'gatecard','data-card':'gate'});
  gcard.append(h2h('Plan gate',
    'The plan-first gate’s current tier, its source, and the newest verdicts '
    +'it delivered (from .claude/logs/plan-gate-events.jsonl). Deny and ask come '
    +'from require-plan/guard-secrets-read; the bypass rows from #no-plan.'));
  const strip=el('div',{class:'ovstrip'},
    el('span',{class:'st','data-status':g.mode||'','data-gate-tier':g.mode||''},label(g.mode)),
    el('span',{class:'mut'},g.source||''));
  if(g.bypassArmed)strip.append(el('span',{class:'badge held','data-bypass-armed':'1',
    title:'a single-use bypass (#no-plan) is armed and unexpired in some session — '
    +'the next non-trivial edit there rides it'},'⚑ bypass armed'));
  gcard.append(strip);
  const evs=g.events||[];
  // An empty feed is said out loud: a gate that has delivered no verdict yet
  // must not look like a card that failed to load its rows.
  if(!evs.length)gcard.append(el('div',{class:'mut'},
    'No gate events yet — verdicts land here as they happen.'));
  else{const tb=el('tbody');
   evs.forEach(e=>tb.append(el('tr',{},
     el('td',{class:'mono'},String(e.ts||'').replace('T',' ').replace('Z','')),
     el('td',{},el('span',{class:'badge','data-ev':e.event||''},e.event||'')),
     el('td',{class:'mono'},e.file||''),
     el('td',{class:'d'},e.reason||''))));
   gcard.append(el('div',{class:'regtblwrap'},el('table',{class:'regtbl'},
     tableHead(['when','event','file','why']),tb)));}
  c.append(gcard);}

 // --- ready now ----------------------------------------------------------------
 const tById={};tasks.forEach(t=>{tById[t.id]=t;});
 // Deliberately NOT scoped by the strips: this is the do-something-now list, and a
 // filter set to look at what is blocked must not empty the one card that says
 // where to start.
 const ready=r.ready||[];
 const rcard=el('div',{class:'card','data-card':'ready'});
 rcard.append(h2h('Ready now',
   'Tasks whose blockers are all done and whose phase is not gated — the ones /audit:run '
   +'will accept right now. Copy the command rather than retyping an id.'));
 // Nothing ready and nothing to do are different answers, and a reader deciding
 // what to work on needs to know which one they got.
 if(!ready.length)rcard.append(el('div',{class:'mut'},
   r.tasks.total?'Nothing is ready: every pending task is waiting on something, or there is nothing left to do.'
     :'No tasks yet.'));
 const RSHOW=8;
 ready.slice(0,RSHOW).forEach(id=>{const t=tById[id]||{};
  const cmd='/audit:run '+id;
  rcard.append(el('div',{class:'rdy'},el('code',{class:'rcmd'},cmd),
    el('span',{class:'rt',title:t.title||''},t.title||''),
    t.phaseId?el('span',{class:'mut'},t.phaseId):null,
    el('button',{class:'btn small',type:'button','data-copy':cmd,
      onclick:e=>ovCopy(e.currentTarget,cmd)},'Copy')));});
 // The remainder is COUNTED rather than dropped, and it names where the rest is.
 if(ready.length>RSHOW)rcard.append(el('div',{class:'mut'},
   '+'+(ready.length-RSHOW)+' more ready — see Composition'));
 c.append(rcard);

 // --- bugs ---------------------------------------------------------------------
 const bugs=STATE.bugs||[];
 if(bugs.length){
  const bcard=el('div',{class:'card','data-card':'bugs'});
  bcard.append(h2h('Bugs',
    'Status here is the EFFECTIVE status the totals above count: a bug materialized '
    +'into a task reads Fixed once that task is done, so the list and the pills can '
    +'never disagree.'));
  // The verdicts are read, never re-derived: `open` and `high` are decided by the
  // same Python functions the rollup counts with, so the rows and the pills above
  // cannot answer differently.
  const rows=bugs.filter(b=>OVF.bs?(OVF.bs==='!high'?(b.open&&b.high):b.status===OVF.bs):true);
  if(!rows.length)bcard.append(el('div',{class:'ovempty'},'No bug matches this filter.'));
  rows.slice(0,20).forEach(b=>{
   bcard.append(el('div',{class:'rdy'},el('span',{class:'mono'},b.id||''),
     el('span',{class:'rt',title:b.title||''},b.title||''),
     b.severity?el('span',{class:'sev'+(b.high?' high':'')},b.severity):null,
     el('span',{class:'st','data-status':b.status||''},label(b.status)),
     // A bug whose status came from its task should say where it came from, or it
     // reads as something somebody typed into the manifest by hand.
     b.taskId?el('span',{class:'mut',title:'materialized as '+b.taskId
       +(b.reported&&b.reported!==b.status?' (reported '+label(b.reported).toLowerCase()+')':'')},
       '→ '+b.taskId):null));});
  if(rows.length>20)bcard.append(el('div',{class:'mut'},'+'+(rows.length-20)+' more'));
  c.append(bcard);}

 // The theme's card order, applied to what was just drawn.
 applyCardOrder('over');
 restoreCaret(keepQ?$('#ovq'):null,caret,keepBack);}
