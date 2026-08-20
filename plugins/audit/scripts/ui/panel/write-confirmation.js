// ---------- who is writing, what exactly, and whether it was recorded ----------
// Three questions the panel could not answer until now, and they are one flow: a
// save wrote whatever the form happened to hold, said "manifest saved", and left
// no trace of who did it or what changed. So: the topbar names you, Save shows the
// exact rows before it writes anything, the server echoes back what it really
// applied, and the journal (when this install has one) keeps the record.

// The name comes from the server, resolved by usage_ledger.resolve_author — the
// same function and the same usage.authorMode that decide the `author` column in
// the token ledger. That is what makes the Usage tab's "my spend" chip able to
// filter on it: two ways of naming the same person would produce a filter that
// silently matches nothing.
function renderViewer(){
 const v=(STATE&&STATE.viewer)||{},w=$('#who');
 if(!w)return;
 w.hidden=false;w.textContent='';w.append(el('span',{class:'wk'},'viewing as'));
 if(v.author){
  w.append(el('b',{title:v.author},v.author));
  w.title='Resolved from git config in '+(v.mode||'email')+' mode (usage.authorMode). '
   +'This is the name written into the token ledger, so Usage → my spend filters on '
   +'exactly this string.';
  return;}
 // `none` is a decision this project made, not a failure to find you — and it is
 // the reason the ledger has no author column to filter on either. Anything else
 // means the resolver could not answer, which is worth the same link.
 w.append(settingsLink(v.mode==='none'?'not recorded':'unknown','usage.authorMode'));
 w.title=v.mode==='none'
  ?'usage.authorMode is "none": this project records no author, here or in the '
   +'token ledger.'
  :'Could not resolve a name from git config or the environment.';}

// A re-render replaces a view's children but never the view element itself, so a
// delegated listener added per render would stack up one more copy on every save.
// One controller per view, aborted at the top of that view's own wiring.
const VIEWAC={};
function onViewEdit(id,fn){
 if(VIEWAC[id])VIEWAC[id].abort();
 VIEWAC[id]=new AbortController();
 const opt={signal:VIEWAC[id].signal},run=()=>requestAnimationFrame(fn);
 ['input','change','click'].forEach(e=>$('#'+id).addEventListener(e,run,opt));
 fn();}

// Unsaved edits, registered per surface rather than tracked with a boolean. A
// boolean answers "is something dirty"; three callers need the ROWS — the confirm
// dialog lists them, Discard says how many are about to be lost, and beforeunload
// only earns the right to interrupt a close if there really are some.
const EDITS={guards:null,comp:null,policy:null};
function editRows(k){try{return (EDITS[k]?EDITS[k]():[])||[];}catch(e){return[];}}
function dirtyRows(){return Object.keys(EDITS).reduce((a,k)=>a.concat(editRows(k)),[]);}
addEventListener('beforeunload',ev=>{
 if(!dirtyRows().length)return;              // never interrupt a clean close
 ev.preventDefault();ev.returnValue='';return '';});

// --- change rows: {target, field, from, to} -------------------------------------
// The same shape the server echoes back as `applied`, computed here from the form
// and there from the file. Values are compared through JSON so a skills list is
// compared by content, and undefined and null are the one thing they mean here:
// "no value".
const cfNorm=v=>v===undefined?null:v;
const cfSame=(a,b)=>JSON.stringify(cfNorm(a))===JSON.stringify(cfNorm(b));
const cfRow=(target,field,from,to)=>({target,field,from:cfNorm(from),to:cfNorm(to)});
// Field order matches the server's (_META_FORM_KEYS, then phases, then tasks by
// _TASK_KEYS) so the dialog and the echo read as the same list, not two lists.
// FORM keys, not every writable meta key: `meta.areas` is writable through
// /api/areas and has no control here, so computing a row for it would be the
// dialog describing an edit this form cannot make.
function compChanges(patch){
 const comp=STATE.composition||{meta:{},phases:[],tasks:[]},rows=[];
 for(const k of ['reviewSkill','buildCommands'])
  if(patch.meta&&(k in patch.meta)&&!cfSame(comp.meta[k],patch.meta[k]))
   rows.push(cfRow('meta',k,comp.meta[k],patch.meta[k]));
 const byP={};(comp.phases||[]).forEach(p=>{byP[p.id]=p;});
 Object.keys(patch.phases||{}).sort().forEach(pid=>{
  const p=byP[pid],pv=patch.phases[pid]||{};
  if(!p||!('reviewModel' in pv))return;
  if(!cfSame(p.reviewModel,pv.reviewModel))
   rows.push(cfRow(pid,'review model',p.reviewModel,pv.reviewModel));});
 const byT={};(comp.tasks||[]).forEach(t=>{byT[t.id]=t;});
 Object.keys(patch.tasks||{}).sort().forEach(tid=>{
  const t=byT[tid],tv=patch.tasks[tid]||{};
  if(!t)return;
  ['model','skills'].forEach(k=>{if(!(k in tv))return;
   if(!cfSame(t[k],tv[k]))rows.push(cfRow(tid,k,t[k],tv[k]));});});
 return rows;}
// Dotted leaf paths, matching _flat_paths in this file: a non-empty object is a
// branch, everything else is a leaf. "usage.bands.highUSD changed" is a sentence
// somebody can check; "usage changed" is not.
function cfFlat(o,pre,out){out=out||{};
 if(o&&typeof o==='object'&&!Array.isArray(o))for(const k of Object.keys(o)){
  const p=pre?pre+'.'+k:k,v=o[k];
  if(v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).length)cfFlat(v,p,out);
  else out[p]=v;}
 return out;}
function configChanges(cfg){
 const a=cfFlat(STATE.config||{}),b=cfFlat(cfg||{}),rows=[];
 [...new Set([...Object.keys(a),...Object.keys(b)])].sort().forEach(p=>{
  const ina=(p in a),inb=(p in b);
  // Presence as well as value: deleting a key is how "use the default" is
  // written, and a key whose value was already null would otherwise vanish.
  if(ina===inb&&cfSame(a[p],b[p]))return;
  rows.push(cfRow('config',p,ina?a[p]:null,inb?b[p]:null));});
 return rows;}

// --- handing the caret back -----------------------------------------------------
// ONE rule, and two places that need it: anything which REPLACES the element
// holding the caret has to hand the caret back.
//
// A native <dialog> already does half of it — it restores the element that was
// focused when showModal() was called. But it restores THE NODE, and every view
// here is rebuilt wholesale by its render*: after a rebuild the opener is a
// different node in the same place, the platform's restore lands on a detached
// element, and the reader is dropped on <body> — the next Tab then starts at the
// top of the document, several stops from where they were.
//
// MEASURED, not reasoned about. Driving the Policy tab's expanded table 20 times
// with the 5s disk poll live: the caret reached the Expand button within 50ms of
// Esc on 20 of 20 closes, and was then taken away again by the poll's redraw on
// 9 of them — 200ms after the close on the one that the browser gate happened to
// be looking at. The close was never the broken half; the redraw was.
//
// So an element is remembered twice: as the node (exact, and correct whenever it
// survived) and as a selector that resolves again in the rebuilt view (durable).
const DLGBACK=new WeakMap();
// Name an element so the rebuilt view can be searched for it: the id when it has
// one, otherwise every data- hook it carries. A hook's VALUE joins the selector
// only when it is safe to write into one — most are short identifiers, but the ⓘ
// carries a whole help sentence in data-tip, and quoting free text into a
// selector is a syntax error waiting for its first apostrophe.
const selSafe=v=>v.length<=64&&!/["\\\]]/.test(v);
function focusSel(n){
 if(!n||!n.attributes)return null;
 // CSS.escape, because Settings names its fields after DOTTED config paths —
 // #set-usage.bands.highUSD, #set-tddReminder.enabled — and '#'+id reads those
 // dots as class combinators. MEASURED: the hand-back worked on
 // #set-manifestPath and #set-planGate and silently restored NOTHING on every
 // dotted id in the form, which is most of it, because the selector matched an
 // element with id "set-usage" carrying class "bands" that does not exist.
 // css-escape is Baseline widely available (since 2022-07-15).
 if(n.id)return '#'+CSS.escape(n.id);
 const hooks=[...n.attributes].filter(a=>a.name.slice(0,5)==='data-')
   .map(a=>'['+a.name+(selSafe(a.value)?'="'+a.value+'"':'')+']').join('');
 return hooks||null;}
// Remember the caret before a rebuild. `within` scopes it both ways: a redraw of
// one view must not take the caret out of another, and must not put it back into
// something that now belongs elsewhere.
function focusKeep(within){
 const a=document.activeElement;
 if(!a||!a.closest||(within&&!a.closest(within)))return null;
 const s=focusSel(a);
 // WHERE in the box, not only which box. Focus alone puts a reader who was in the
 // middle of a path back at offset 0, which is the same defect one level down —
 // and it is why renderPolicy, renderOver and renderAppearance each grew their own
 // id+selectionStart special case. Carried here once instead. Reading
 // selectionStart THROWS on the input types that have no selection (number, date,
 // colour) rather than returning null, so it is asked for inside the try.
 let at=null;
 try{at=a.selectionStart==null?null:[a.selectionStart,a.selectionEnd];}
 catch(e){at=null;}
 return {node:a,sel:s?((within?within+' ':'')+s):null,at:at};}
function focusBack(ref){
 if(!ref)return false;
 let n=(ref.node&&ref.node.isConnected)?ref.node:null;
 if(!n&&ref.sel){const m=document.querySelectorAll(ref.sel);
  // Exactly one, or nothing. A hook that names several controls cannot say WHICH
  // of them had the caret, and guessing puts the reader somewhere they have never
  // been — worse than the top of the document, because it looks deliberate.
  n=m.length===1?m[0]:null;}
 if(!n||!n.focus)return false;
 n.focus();
 if(ref.at&&n.setSelectionRange)try{n.setSelectionRange(ref.at[0],ref.at[1]);}catch(e){}
 // ASK THE DOCUMENT, do not assume .focus() took. A disabled control accepts the
 // call in silence and keeps the caret on <body>. That is how this line was
 // earned: the four Discard buttons used to disable themselves on a successful
 // discard, so the selector still resolved to exactly one node, .focus() did
 // nothing, and the old `return true` reported a hand-back that had not happened.
 // The Discards no longer do that (see offState below), but the check stays —
 // every OTHER control that can go unreachable between keep and restore fails the
 // same way, and this is the only place that can notice.
 return document.activeElement===n;}
// UNAVAILABLE MUST NOT MEAN UNREACHABLE (WCAG 2.2 SC 2.4.3).
// `disabled` removes the tab stop, so a reader who tabs to a Discard, presses it,
// and lands on the rebuilt one has the caret taken to <body> and the next Tab
// restarts at the top of the document. WAI-ARIA APG uses aria-disabled precisely
// so the control keeps its place and its name and refuses the ACTIVATION instead.
// It costs one extra tab stop per savebar; that is the trade, not an oversight.
function offState(n,off){
 n.setAttribute('aria-disabled',off?'true':'false');
 return n;}
// aria-disabled is a promise to assistive technology and the platform enforces
// none of it — unlike `disabled`, the browser still dispatches the click (and
// Enter/Space arrive as one). Kept here, once, in the capture phase: four handlers
// each re-checking their own emptiness would be four chances to disagree, and a
// control added later would inherit the promise without the refusal.
document.addEventListener('click',e=>{
 const n=e.target&&e.target.closest&&e.target.closest('[aria-disabled="true"]');
 if(n){e.preventDefault();e.stopPropagation();}},true);
// showModal(), plus the close that hands the caret back. EVERY dialog on this
// page opens through here — `.showModal()` is written exactly once in this file
// and a selftest counts it, so a fifth dialog cannot be added that quietly skips
// the restore. The close listener is wired once per element; these are
// singletons, reused for every opening.
function dlgOpen(d,sel){
 if(!DLGBACK.has(d))d.addEventListener('close',()=>{
   const r=DLGBACK.get(d);DLGBACK.set(d,null);focusBack(r);});
 const a=document.activeElement;
 DLGBACK.set(d,{node:a,sel:sel||focusSel(a)});
 d.showModal();}

// --- the confirm dialog ---------------------------------------------------------
let CFDLG=null;
// Absent, empty-list and empty-string are three different values and the dialog
// says so. Collapsing them into one "not set" made a real change read as a no-op —
// "not set → not set" — which is precisely the row a reader would skim past.
// On a `skills` row null is not "not set" either: it is the explicit opt-out
// (v0.37 B1), the one deliberate answer, and it renders as one.
function cfVal(v,cls,field){
 const none=v===null||v===undefined;
 if(none&&field==='skills')
  return el('span',{class:'cfv '+cls},'none — opted out (null)');
 const empty=none||v===''||(Array.isArray(v)&&!v.length);
 return el('span',{class:'cfv '+cls+(empty?' unset':'')},
   none?'not set'
    :(Array.isArray(v)&&!v.length?'(empty list)'
      :(v===''?'(empty text)'
        :(typeof v==='object'?JSON.stringify(v):String(v)))));}
// Which phases a change list touches, so the lock notice can be about the phases
// you are actually writing rather than about the manifest in general. A task id is
// mapped through the composition view rather than sliced out of the string: task
// ids are the plan's to shape, not this file's to parse.
function cfTouched(rows){
 const byT={};((STATE.composition||{}).tasks||[]).forEach(t=>{byT[t.id]=t.phaseId;});
 const s=new Set();
 rows.forEach(r=>{if(r.target==='meta'||r.target==='config')return;
  s.add(byT[r.target]||r.target);});
 return [...s];}
// Live, from the 5s poll — not from the page-load snapshot. A dialog that opens to
// say "nothing is running" because nothing was running when the tab loaded is
// exactly the reassurance this flow must not give.
function cfLock(rows,scope){
 const rs=RUNSTATUS||(STATE||{}).runStatus||{index:null,phases:{}};
 const idx=rs.index&&rs.index.live!==false;
 const livePhases=Object.keys(rs.phases||{}).filter(pid=>{
  const l=(rs.phases[pid]||{}).lock;return l&&l.live!==false;});
 if(idx)return{kind:'warn',text:'An /audit command holds the manifest lock right '
  +'now. This write will be refused while it does — nothing here is lost if it is.'};
 if(scope==='comp'){
  const hit=cfTouched(rows).filter(p=>livePhases.includes(p));
  if(hit.length)return{kind:'warn',text:'Running elsewhere right now: '+hit.join(', ')
   +'. A phase that is being worked cannot be edited here until that run finishes, '
   +'so this write will be refused.'};}
 if(livePhases.length)return{kind:'ok',text:'Running elsewhere: '+livePhases.join(', ')
  +' — none of them touched by these changes.'};
 return null;}
/**
 * Show the exact rows and wait for an answer. Resolves true only on the primary
 * button; Esc, the backdrop, the × and Cancel all resolve false, which is the
 * point of using a native <dialog> — the focus trap, the backdrop and Esc are the
 * platform's rather than three hand-written listeners that each forget one case.
 */
function confirmChanges(o){
 return new Promise(resolve=>{
  if(!CFDLG){CFDLG=el('dialog',{class:'confirm'});
   // Clicking the backdrop is the same intent as Esc. The dialog element fills the
   // viewport, so a click whose target IS the dialog landed outside the panel.
   CFDLG.addEventListener('click',ev=>{if(ev.target===CFDLG)CFDLG.close();});
   document.body.append(CFDLG);}
  const d=CFDLG;let done=false;
  const settle=v=>{if(done)return;done=true;resolve(v);};
  d.addEventListener('close',()=>settle(false),{once:true});
  d.textContent='';
  d.append(el('div',{class:'bhead'},el('h2',{},o.title),
    el('button',{class:'bx','aria-label':'close',type:'button',
      onclick:()=>d.close()},'×')));
  const tb=el('tbody');
  o.rows.forEach(r=>tb.append(el('tr',{'data-cfrow':r.target+' '+r.field},
    el('td',{class:'tgt'},r.target),el('td',{class:'fld'},r.field),
    el('td',{},cfVal(r.from,'was',r.field),el('span',{class:'cfarr'},'→'),
      cfVal(r.to,'now',r.field)))));
  d.append(el('div',{class:'cflist'},el('table',{class:'cftbl'},
    el('thead',{},el('tr',{},el('th',{},'what'),el('th',{},'field'),
      el('th',{},'change'))),tb)));
  const lk=o.lock===false?null:cfLock(o.rows,o.scope);
  if(lk)d.append(el('div',{class:'cflock'},
    el('div',{class:'findings '+lk.kind},lk.text)));
  const cancel=el('button',{class:'btn small push',type:'button',
    'data-cfcancel':'1',onclick:()=>d.close()},'Cancel');
  const go=el('button',{class:'btn primary',type:'button','data-cfgo':'1',
    onclick:()=>{settle(true);d.close();}},o.verb);
  // The identity is repeated here, at the moment of the write, and not only in the
  // topbar: below 34rem the topbar pill is dropped for want of room, and "who is
  // this being recorded as" is a question that matters most on the screen where
  // there is least room to answer it. Not on the Discard dialog — nothing is
  // written there, so a name would be answering a question nobody asked.
  const who=((STATE||{}).viewer||{}).author;
  d.append(el('div',{class:'cffoot'},
    el('span',{class:'mut small','data-cfwho':who&&!o.danger?'1':null},
      (who&&!o.danger?'as '+who+' · ':'')+(o.note||'')),cancel,go));
  dlgOpen(d);
  // A destructive primary must not be one Enter away from a keyboard that opened
  // the dialog by pressing Enter on a button.
  (o.danger?cancel:go).focus();});}

// --- what came back -------------------------------------------------------------
// The server recomputes the change list against the document it is about to write
// and echoes it as `applied`. Comparing it with what the dialog showed is the only
// way this flow tells "your save landed" apart from "your save landed on a
// manifest that is no longer the one you were reading" — a second tab, or an
// /audit run, having moved it in between. Without the comparison a confirm dialog
// makes that case WORSE: it adds a screenful of reassurance about stale values.
function appliedDiff(rows,res){
 if(!res||!res.ok||!Array.isArray(res.applied))return null;
 const key=r=>JSON.stringify([r.target,r.field,cfNorm(r.from),cfNorm(r.to)]);
 const mine=new Set(rows.map(key)),theirs=new Set(res.applied.map(key));
 const missing=[...mine].filter(k=>!theirs.has(k)).length;
 const extra=[...theirs].filter(k=>!mine.has(k)).length;
 return (missing||extra)?{missing,extra,shown:rows.length,
   applied:res.applied.length}:null;}
// One sentence for what happened to your changes: how many landed, and whether
// there is a record of it. "not logged" is said only when a journal exists and
// refused the row — on an install with no journal at all the clause is left off
// rather than reporting the absence of a feature as a failure of a save.
function saveOutcome(res,rows,what,slot){
 if(!res||!res.ok){
  toast(res&&res.locked?(what+' is locked — nothing was written')
    :('rejected — nothing was written'),'err');
  return null;}
 if(res.unchanged){toast('nothing to save — no values changed');return null;}
 const n=(res.applied||[]).length;
 const diff=appliedDiff(rows,res);
 const log=res.journaled?' · logged'
   :(res.journaledWhy==='failed'?' · NOT logged':'');
 toast('Saved · '+n+' change'+(n===1?'':'s')+log,diff?'warn':'ok');
 if(diff&&slot)slot.append(el('div',{class:'findings warn','data-cfdiff':'1'},
   'Saved, but not exactly what the dialog listed: '+diff.applied+' of the '
   +diff.shown+' change(s) shown were applied'
   +(diff.extra?(', and '+diff.extra+' other change(s) were'):'')
   +'. The file moved between opening this view and saving — reload the panel to '
   +'see what it holds now.'));
 return diff;}

async function boot(){STATE=await api('GET','/api/state');REG=await api('GET','/api/registry');
 USAGE=await api('GET','/api/usage').catch(()=>null);BANDS=null;MITEMS=null;
 POLICY=await api('GET','/api/policy').catch(()=>null);PDRAFT=pClone(POLICY&&POLICY.stored);
 // fp: restore the usage filters BEFORE the first renderUsage — the hash first
 // (a share link is an instruction somebody sent), this repo's stored filters
 // second, defaults last.
 {const h=location.hash||'',bang=h.indexOf('!');
  const got=bang>=0&&uApplyFragment(h.slice(bang+1));
  if(!got){let s=null;try{s=localStorage.getItem(UFSTORE);}catch(e){}
   if(s)uApplyFragment(s);}}
 THEME=await api('GET','/api/theme').catch(()=>null);
 tCaptureBase();
 renderViewer();renderSettings();renderComp();renderOver();renderUsage();renderPolicy();renderAppearance();
 // Restored last, once every view has content to scroll to.
 showTab(initialTab());
 RUNSTATUS=STATE.runStatus||null;FP=(RUNSTATUS||{}).fingerprint||null;
 startRunPoll();startTipPlacement();}
