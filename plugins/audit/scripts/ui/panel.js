
const TOKEN=__AUDIT_TOKEN__, PROJECT=__AUDIT_PROJECT__;
const $=(s,r=document)=>r.querySelector(s), el=(t,a={},...k)=>{const e=document.createElement(t);
 for(const[n,v]of Object.entries(a)){if(n==='class')e.className=v;else if(n==='html')e.innerHTML=v;
 else if(n.startsWith('on'))e.addEventListener(n.slice(2),v);else if(v!=null)e.setAttribute(n,v);}
 for(const c of k.flat()){if(c!=null)e.append(c.nodeType?c:document.createTextNode(c));}return e;};
const api=async(m,p,b)=>{const r=await fetch(p,{method:m,headers:{'X-Audit-Token':TOKEN,
 'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});return r.json();};
// For navigations rather than fetches: window.open cannot set a header, so the
// token has to ride in the query string (the guard accepts either).
const url=p=>p+'?t='+encodeURIComponent(TOKEN);
let STATE=null, REG={skills:[],agents:[],mcp:[]};
// Middle ellipsis, not a tail cut: the head says which machine/checkout this is
// and the tail says which project, and a plain truncation throws away whichever
// end the CSS happens to reach first. The full path stays in the tooltip, so
// nothing is lost — it is just no longer allowed to set the header's height.
function midElide(s,max){if(!s||s.length<=max)return s||'';
 const keep=max-1,head=Math.ceil(keep*0.38);return s.slice(0,head)+'…'+s.slice(s.length-(keep-head));}
$('#proj').textContent=midElide(PROJECT,56);
$('#proj').title=PROJECT;
// theme
const root=document.documentElement, TK='audit-panel-theme';
try{const s=localStorage.getItem(TK);if(s)root.setAttribute('data-theme',s);}catch(e){}
const isDark=()=>{const t=root.getAttribute('data-theme');return t?t==='dark':matchMedia('(prefers-color-scheme:dark)').matches;};
const paint=()=>$('#theme').textContent=isDark()?'☀':'☾';paint();
$('#theme').onclick=()=>{const n=isDark()?'light':'dark';root.setAttribute('data-theme',n);
 try{localStorage.setItem(TK,n);}catch(e){}paint();};
// Render the standalone report and open it. Opened through THIS origin (/report):
// a browser will not follow a file:// link from an http:// page, so handing over a
// filesystem path would give you a button that silently does nothing. The report
// itself already carries Save-as-PDF and a Markdown twin, so there is no PDF
// machinery here.
$('#report').onclick=async e=>{const b=e.currentTarget;
 const was=b.textContent;b.disabled=true;b.textContent='Rendering…';
 // Opened NOW, inside the click, and navigated once the render returns. Called
 // after the await it is no longer a user gesture, and a render that takes a
 // second or two is exactly when a browser silently blocks the popup — the
 // button then reports success and nothing appears.
 let win=null; try{win=window.open('','_blank','noopener');}catch(_e){}
 try{const r=await api('POST','/api/report',{});
  if(!r.ok){if(win)win.close();toast((r.findings||['render failed'])[0],'err');return;}
  if(!r.exists){if(win)win.close();
   toast('rendered, but no HTML report was written — check /audit:report','err');return;}
  toast('wrote '+(r.files||[]).length+' file(s)','ok');
  if(win){win.location=url('/report');}
  else{
   // Blocked anyway: leave a link rather than a button that did nothing.
   const a=$('#replink')||el('a',{id:'replink',class:'lnk',target:'_blank',rel:'noopener'},'open report ↗');
   a.href=url('/report');if(!a.parentNode)b.parentNode.insertBefore(a,b.nextSibling);}
 }catch(err){if(win)win.close();toast('render failed: '+err,'err');}
 finally{b.disabled=false;b.textContent=was;}};
// tabs
// Views are addressable, and each remembers where you were in it. Every switch
// used to slam the page back to the top and the URL never changed: a 50-phase
// Composition table lost your place the moment you glanced at Usage, and there
// was no way to link anyone to a tab — a reload always landed on Guards.
// The manifest's vocabulary is machine-facing: `in_progress` sorts, compares and
// survives serialization. It is not a thing to show anyone, and it was leaking
// into every status pill, every filter button and every phase row. The machine
// value stays in data-status (the CSS themes off it, the filters compare it);
// only the text changes.
const LABELS=__LABELS__;
const label=v=>LABELS[v]||(v?String(v).replace(/[_-]+/g,' ').replace(/^./,c=>c.toUpperCase()):'—');
const TABS=['guards','comp','over','usage','policy'],SCROLL={};
let CURTAB=null;
function showTab(t,push){
 if(!TABS.includes(t))t='guards';
 if(CURTAB)SCROLL[CURTAB]=window.scrollY;
 CURTAB=t;
 document.querySelectorAll('.tab').forEach(x=>{const on=x.dataset.t===t;x.classList.toggle('on',on);
  // Colour alone does not say which view you are in — a screen reader gets nothing
  // from a background change, and these four are exclusive views, not filters.
  if(on)x.setAttribute('aria-current','true');else x.removeAttribute('aria-current');});
 for(const id of TABS)$('#'+id).classList.toggle('hidden',id!==t);
 if(push!==false){const h='#/'+t;if(location.hash!==h)history.replaceState(null,'',h);}
 try{localStorage.setItem('audit-panel-tab',t);}catch(e){}
 // After the browser has laid the view out, not before it.
 requestAnimationFrame(()=>window.scrollTo({top:SCROLL[t]||0,behavior:'auto'}));}
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>showTab(t.dataset.t));
// Measured, not assumed. Below the shell breakpoint the five views become one
// horizontal strip, and on a phone the last of them is off the right-hand edge
// with nothing to suggest it exists.
function tabsOverflow(){const n=document.querySelector('.tabs');
 if(n)n.classList.toggle('scrolls',n.scrollWidth>n.clientWidth+1);}
addEventListener('resize',tabsOverflow);tabsOverflow();
addEventListener('hashchange',()=>{const t=(location.hash||'').replace(/^#\/?/,'');
 if(TABS.includes(t)&&t!==CURTAB)showTab(t,false);});
function initialTab(){const h=(location.hash||'').replace(/^#\/?/,'');
 if(TABS.includes(h))return h;
 try{const s=localStorage.getItem('audit-panel-tab');if(TABS.includes(s))return s;}catch(e){}
 return 'guards';}
function toast(msg,kind){const t=$('#toast');t.textContent=msg;t.className='show '+(kind||'');
 setTimeout(()=>t.className=t.className.replace('show','').trim(),2600);}
function findingsBox(res){const box=el('div');
 if(res.findings&&res.findings.length)box.append(el('div',{class:'findings err'},'✗ '+res.findings.join(' · ')));
 if(res.warnings&&res.warnings.length)box.append(el('div',{class:'findings warn'},'! '+res.warnings.join(' · ')));
 if(res.ok&&!(res.warnings&&res.warnings.length))box.append(el('div',{class:'findings ok'},'✓ saved'));
 return box;}
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

// --- the confirm dialog ---------------------------------------------------------
let CFDLG=null;
// Absent, empty-list and empty-string are three different values and the dialog
// says so. Collapsing them into one "not set" made a real change read as a no-op —
// "not set → not set" — which is precisely the row a reader would skim past.
function cfVal(v,cls){
 const none=v===null||v===undefined;
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
    el('td',{},cfVal(r.from,'was'),el('span',{class:'cfarr'},'→'),
      cfVal(r.to,'now')))));
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
  d.showModal();
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
 USAGE=await api('GET','/api/usage').catch(()=>null);BANDS=null;
 POLICY=await api('GET','/api/policy').catch(()=>null);PDRAFT=pClone(POLICY&&POLICY.stored);
 renderViewer();renderSettings();renderComp();renderOver();renderUsage();renderPolicy();
 // Restored last, once every view has content to scroll to.
 showTab(initialTab());
 RUNSTATUS=STATE.runStatus||null;startRunPoll();}
// ---------- shared: info hints + autocomplete ----------
// The help text, the form's shape and the enum choices all arrive from Python —
// see FIELD_HELP / SETTINGS_GROUPS / _cfg_enums in this file. They used to be a JS
// literal here, which is how the form came to cover only part of the config while
// nothing said so. HELP is keyed by dotted config path; MDESC covers the manifest
// levers the Composition tab edits, which are not config paths.
const SETTINGS=__SETTINGS__, HELP=__FIELD_HELP__, MDESC=__COMP_HELP__, ENUMS=__CFG_ENUMS__;
// Two depths, one control. Hovering says what this box is for in the panel's own
// words; pressing it opens the drawer, which adds what the SCHEMA says, the type,
// the enum, the default the hooks fall back to and the concept page behind it.
// `ref` decides whether there is a second depth at all — a hint on something the
// schemas do not document (a policy switch, a discovered capability) stays a
// tooltip rather than becoming a button that opens an empty page.
function hint(t,ref){if(!t&&!ref)return null;
 // No `data-tip` at all when there is no tooltip, rather than an empty one: the
 // bubble's content IS that attribute, so an empty string draws an empty box on
 // hover. Two fields hit this the moment the ⓘ stopped needing tooltip text to
 // exist — the cost-band pair, which has a schema entry and no microcopy.
 const h=el(ref?'button':'span',{class:'hint','data-tip':t||null},'i');
 // A <span tabindex=0> inside a <label> is not interactive content, so a click on
 // it also toggled the checkbox it was explaining. A real button is, which is what
 // stops that — and it is what a screen reader announces as something to press.
 if(ref){h.type='button';h.setAttribute('aria-label','What is '+hRefName(ref)+'?');
  // What this ⓘ is about, on the element itself: the live checks address one
  // field's hint rather than counting their way to it through a label's words.
  h.setAttribute('data-hint',ref.path||ref.comp||('topic:'+ref.topic));
  h.onclick=ev=>{ev.preventDefault();ev.stopPropagation();openHelp(ref);};}
 else h.tabIndex=0;
 // Measured at open time, not guessed from a breakpoint: whether the bubble fits
 // depends on where this particular hint sits, which CSS cannot ask.
 const place=()=>{const r=h.getBoundingClientRect();
  h.classList.toggle('flip',r.left+272>document.documentElement.clientWidth-8);};
 h.addEventListener('mouseenter',place);h.addEventListener('focus',place);
 return h;}
function flabel(text,tip,ref){return el('span',{class:'lbl'},text,hint(tip,ref));}
function h2h(text,tip,ref){return el('h2',{},text,hint(tip,ref));}
// Heading in the reader's words, with the JSON key beside it for whoever is
// editing .claude/audit.config.json by hand. Both audiences are real and they
// want different strings: "guardEdits.tokenVars" tells you nothing about what the
// setting DOES, and "Secrets never written to logs" cannot be typed into a file.
// The key keeps its own case on purpose — h2 is uppercased, and an uppercased
// camelCase key is not merely shouted, it is WRONG: config keys are
// case-sensitive, so copying it out of here would produce a setting that silently
// does nothing.
// The key is also the path the drawer looks the field up under, so every control in
// this form gets its reference entry without a second list saying which ones have
// one. A path the schema does not describe fails _help's own coverage selftest, so
// "the drawer opens on nothing" is a build failure rather than a dead ⓘ.
function klabel(text,key,tip){return el('span',{class:'lbl'},text,el('code',{class:'k2'},key),
 hint(tip,{path:key,doc:'config',label:text}));}

// ---------- the help drawer ----------
// What every field means, and how the four concepts work, answered from the
// plugin's own schemas and code — see scripts/_help.py and GET /api/help. Two
// rules hold this together and both are the reason it is worth having:
//
//   Nothing here is retyped. Field text is EXTRACTED from the two shipped schemas
//   at request time and concept pages DERIVE every executable rule from the
//   function that executes it, so this drawer cannot drift from the document your
//   editor validates against. A sentence written into this file would be a second
//   thing to keep true.
//
//   And no path is resolved here. `usage.pricing.opus.in` is a path into a
//   document; the help table is keyed by shapes (`usage.pricing.<name>.in`).
//   `_help.entry_for` is the one thing that knows the difference and it is asked
//   over HTTP — the same bargain the Policy tab strikes with verdicts.
let HELPDOC=null,HDLG=null,HVIEW=null;
const HCACHE=new Map(),HSTACK=[];
const hRefName=r=>r.label||r.path||(r.topic?'this':'')||'this';
async function helpDoc(){if(!HELPDOC)HELPDOC=await api('GET','/api/help');return HELPDOC;}
async function helpField(path,doc){const k=doc+'|'+path;
 if(!HCACHE.has(k))HCACHE.set(k,await api('GET','/api/help?doc='+encodeURIComponent(doc)
   +'&path='+encodeURIComponent(path)));
 return HCACHE.get(k);}
// Backticks are the only markup the topics use, and they use it for identifiers.
// An unbalanced pair renders verbatim rather than guessing which half was code —
// a mis-parsed identifier is worse than an un-styled one.
function hcode(s){const parts=String(s==null?'':s).split('`');
 if(parts.length%2===0)return [String(s)];
 return parts.map((x,i)=>i%2?el('code',{},x):x).filter(x=>x!=='');}
function hsec(title,...kids){return el('div',{class:'dsec'},
  title?el('h3',{},title):null,kids.flat().filter(Boolean));}
function helpDrawer(){
 if(!HDLG){HDLG=el('dialog',{class:'drawer','aria-label':'Help'});
  HDLG.addEventListener('click',ev=>{if(ev.target===HDLG)HDLG.close();});
  // The stack is per-opening. Left standing, a back button would offer to return
  // to a field somebody read ten minutes ago on another tab.
  HDLG.addEventListener('close',()=>{HSTACK.length=0;HVIEW=null;});
  document.body.append(HDLG);}
 return HDLG;}

// The paid half, named on every view because it is the answer when this drawer is
// not. It is not started from here and the card says so: a question the panel
// already answers for nothing should not quietly bill for a model. `agent:null` is
// an install without the guide — draw nothing rather than a hint pointing at it.
function hAgentCard(doc){const a=doc&&doc.agent;if(!a)return null;
 // Shut, for the same reason the policy tab's four limits are: it is read once and
 // remembered, and left open it is a permanent 250px footer over the page someone
 // came here to read — which on the concept pages cut the table off.
 const box=el('details',{class:'dagent','data-hagent':a.name});
 box.append(el('summary',{},el('b',{},'Not answered here? Ask '),
   el('code',{},a.qualified||a.name)));
 if(a.description)box.append(el('p',{},a.description));
 box.append(el('p',{},'Ask for it by name in a Claude Code session. ',
   el('b',{},'This panel will not start it for you'),
   ' — everything above is already written down, and spending a model on it would '
   +'be paying for a page you are looking at.'));
 box.append(el('div',{class:'dtools'},
   el('span',{class:'badge'},'read-only: '+(a.tools||[]).join(' · ')),
   a.model?el('span',{class:'badge'},'model '+a.model):null,
   a.effort?el('span',{class:'badge'},'effort '+a.effort):null));
 return box;}

// --- the three views -------------------------------------------------------
function hIndexView(doc){
 const body=el('div',{class:'dbody'});
 body.append(hsec(null,el('p',{},'Every field below is described by the plugin’s '
   +'own schemas, and every rule on a concept page is read from the code that runs '
   +'it. Nothing here was asked of a model, and none of it is about this project '
   +'in particular — for what is true HERE, see the Policy tab’s verdicts and '
   +'the audit trail.')));
 const list=el('ul',{class:'dlist'});
 (doc.topics||[]).forEach(t=>list.append(el('li',{},
   el('button',{class:'dtopic',type:'button','data-htopic':t.id,
     onclick:()=>hShow({kind:'topic',id:t.id},true)},
     el('b',{},t.title),el('span',{},t.summary)))));
 body.append(hsec('How it works',list));
 body.append(hsec('Every field',el('p',{},'Press the ',
   el('code',{},'i'),' beside any setting or lever for what it means, what it '
   +'accepts and what it falls back to when you leave it empty.')));
 return {title:'Help',body};}

function hTopicView(doc,id){
 const t=(doc.topics||[]).find(x=>x.id===id);
 const body=el('div',{class:'dbody'});
 if(!t){body.append(el('p',{class:'dmiss'},'No page with that name.'));
  return {title:'Help',body};}
 body.append(hsec(null,el('p',{class:'mut'},hcode(t.summary))));
 body.append(hsec(null,(t.paragraphs||[]).map(p=>el('p',{},hcode(p)))));
 if(t.table){const tb=el('tbody');
  (t.table.rows||[]).forEach(r=>tb.append(el('tr',{},
    (r||[]).map(cell=>el('td',{},hcode(cell))))));
  body.append(hsec(null,
    el('div',{class:'dtblwrap'},el('table',{class:'dtbl','data-htable':id},
      el('thead',{},el('tr',{},(t.table.columns||[]).map(c=>el('th',{},c)))),tb)),
    t.table.caption?el('p',{class:'dcap'},hcode(t.table.caption)):null));}
 if((t.sources||[]).length)body.append(hsec('Stated in full in',
   el('div',{class:'dsrc'},t.sources.map(s=>el('span',{},s)))));
 return {title:t.title,body};}

async function hFieldView(doc,ref){
 const body=el('div',{class:'dbody'});
 // A composition lever is not a config path; _help ships the map from the panel's
 // own name for it (`taskModel`) to the manifest path that documents it, so this
 // file does not carry a second one.
 const path=ref.path||(doc.composition||{})[ref.comp],
   which=ref.doc||(ref.comp?'manifest':'config');
 if(!path){body.append(el('p',{class:'dmiss'},'Nothing documents this control.'));
  return {title:ref.label||'Help',body};}
 const res=await helpField(path,which),e=(res&&res.entry)||null;
 body.append(hsec(null,el('code',{class:'dpath','data-hpath':path},path)));
 if(!res||!res.found){
  body.append(hsec(null,el('p',{class:'dmiss'},'The '+which+' schema has no entry '
    +'for this path, so there is nothing to show. That is a gap in the schema '
    +'rather than a setting without a meaning.')));
  return {title:ref.label||path,body};}
 // The schema's words first, because they are the ones your editor shows you and
 // the ones the file is validated against. Cited under the paragraph rather than
 // paraphrased into it.
 body.append(hsec('What it means',el('p',{},hcode(e.description||'')),
   el('div',{class:'dsrc'},
     el('span',{},((doc.schemas||{})[which])||(which+' schema')),
     res.key&&res.key!==path?el('span',{},'documented as '+res.key):null)));
 const facts=el('dl',{class:'dfacts','data-hfacts':'1'});
 const fact=(k,v)=>{facts.append(el('dt',{},k),el('dd',{},v));};
 if(e.type)fact('Type',Array.isArray(e.type)?e.type.join(' or '):String(e.type));
 if(e.enum)fact('One of',e.enum.join(', '));
 // The default is the value the HOOKS fall back to, flattened out of
 // _config.DEFAULTS rather than read off a sentence about it — which is what makes
 // "leave it empty and you get this" a fact rather than a promise.
 if('default' in e)fact('Default',hVal(e.default));
 if(e.minimum!=null)fact('At least',String(e.minimum));
 if(e.maximum!=null)fact('At most',String(e.maximum));
 if(facts.childNodes.length)body.append(hsec('Accepts',facts));
 // Second, and labelled as the panel's own: this is the microcopy beside the
 // control, which says what THIS FORM does about the setting (it refuses a regex
 // that will not compile; your list replaces the defaults). It is a different
 // claim about a different thing, so it gets its own heading instead of being run
 // together with the schema's sentence as if the two were one voice.
 const note=ref.comp?MDESC[ref.comp]:HELP[path];
 if(note)body.append(hsec('In this panel',el('p',{},note)));
 if(e.topic){const t=(doc.topics||[]).find(x=>x.id===e.topic);
  if(t)body.append(hsec('How this works',el('button',{class:'dtopic',type:'button',
    'data-htopic':t.id,onclick:()=>hShow({kind:'topic',id:t.id},true)},
    el('b',{},t.title),el('span',{},t.summary))));}
 return {title:ref.label||path,body};}

function hVal(v){return v===null?'null':(Array.isArray(v)
  ?(v.length?v.join(', '):'(empty list)')
  :(v===''?'(empty text)':String(v)));}

async function hShow(view,push){
 const d=helpDrawer();
 if(push&&HVIEW)HSTACK.push(HVIEW);
 HVIEW=view;
 if(!d.open)d.showModal();
 let doc;
 try{doc=await helpDoc();}
 catch(err){d.textContent='';
  d.append(el('div',{class:'dhead'},el('h2',{},'Help'),
    el('button',{class:'bx','aria-label':'close help',type:'button',
      onclick:()=>d.close()},'×')),
    el('div',{class:'dbody'},el('div',{class:'findings err'},
      'The help endpoint did not answer: '+err)));
  return;}
 const v=view.kind==='topic'?hTopicView(doc,view.id)
   :view.kind==='field'?await hFieldView(doc,view.ref)
   :hIndexView(doc);
 // Opened before the awaits so the press has an effect at once, and filled in ONE
 // go afterwards rather than staged — measured at 10 ms to build the payload and
 // 1 ms per field after that, so there is nothing to stage, and a header painted
 // early would only be the previous field's title for those 10 ms.
 d.textContent='';
 const head=el('div',{class:'dhead'});
 if(HSTACK.length)head.append(el('button',{class:'btn small','data-hback':'1',
   type:'button',onclick:()=>{const prev=HSTACK.pop();hShow(prev,false);}},'←'));
 head.append(el('h2',{},v.title),el('button',{class:'bx','aria-label':'close help',
   type:'button',onclick:()=>d.close()},'×'));
 d.append(head,v.body,hAgentCard(doc));
 v.body.scrollTop=0;}

function openHelp(ref){
 if(ref&&ref.topic)return hShow({kind:'topic',id:ref.topic},false);
 return hShow({kind:'field',ref:ref||{}},false);}
function openHelpIndex(){return hShow({kind:'index'},false);}
$('#helpbtn').onclick=()=>openHelpIndex();
// A custom autocomplete: menu opens directly under the input, limited height,
// clear items (name + source + description), keyboard + click select.
function comboWrap(inp,itemsFn,onChoose,onEnterFree){
 const wrap=el('div',{class:'combo'}),menu=el('div',{class:'combo-menu hidden'});
 let active=-1,shown=[];
 const close=()=>{menu.classList.add('hidden');active=-1;};
 const render=()=>{const q=inp.value.trim().toLowerCase();
  shown=itemsFn().filter(it=>it.name.toLowerCase().includes(q)).slice(0,60);
  menu.textContent='';
  if(!shown.length){close();return;}
  shown.forEach((it,i)=>menu.append(el('div',{class:'combo-it'+(i===active?' active':''),
    onmousedown:e=>{e.preventDefault();onChoose(it.name,close);}},
    el('span',{class:'combo-n mono'},it.name),
    it.source?el('span',{class:'src badge'},it.source):null,
    it.description?el('span',{class:'combo-d'},it.description):null)));
  menu.classList.remove('hidden');
  const a=menu.querySelector('.combo-it.active');if(a)a.scrollIntoView({block:'nearest'});};
 inp.setAttribute('autocomplete','off');
 inp.addEventListener('focus',render);
 inp.addEventListener('input',()=>{active=-1;render();});
 inp.addEventListener('keydown',e=>{
  if(e.key==='ArrowDown'){e.preventDefault();active=Math.min(active+1,shown.length-1);render();}
  else if(e.key==='ArrowUp'){e.preventDefault();active=Math.max(active-1,0);render();}
  else if(e.key==='Enter'){if(active>=0){e.preventDefault();onChoose(shown[active].name,close);}
   else if(onEnterFree&&inp.value.trim()){e.preventDefault();onEnterFree(inp.value.trim(),close);}}
  else if(e.key==='Escape'){close();}});
 inp.addEventListener('blur',()=>setTimeout(close,150));
 wrap.append(inp,menu);return wrap;}

// ---------- Settings ----------
// The view id stays `guards`: it is the hash route (#/guards), the screenshot name
// and what several selftests pin. An internal id is an address, not a description —
// renaming it would break every link anyone already has for the sake of a word only
// this file ever sees.
function listEditor(getArr,setArr,ph,validate){const wrap=el('div',{class:'pill-in'});
 const draw=()=>{wrap.textContent='';(getArr()||[]).forEach((v,i)=>{
   const bad=validate?validate(v):null;
   wrap.append(el('span',{class:'chip'+(bad?' bad':''),title:bad||null},v,
     el('button',{'aria-label':'remove '+v,
       onclick:()=>{const a=getArr().slice();a.splice(i,1);setArr(a);draw();}},'×')));});
   const inp=el('input',{placeholder:ph||'add…'});inp.addEventListener('keydown',e=>{
    if(e.key==='Enter'&&inp.value.trim()){const a=(getArr()||[]).slice();a.push(inp.value.trim());setArr(a);draw();}});
   wrap.append(inp);};draw();return wrap;}
// Does the browser's engine accept this pattern? A first pass only — the config is
// compiled by Python's `re` on save, and the two dialects are not the same, so this
// says "your browser rejects it", never "this is valid".
function reErr(src){if(!src)return null;
 try{new RegExp(src);return null;}catch(e){return String(e.message||e);}}
// Read/write a dotted config path. The form is described by path in Python, so the
// only alternative would be a getter and a setter per field, hand-written.
function getPath(o,p){let cur=o;for(const k of p.split('.')){
  if(cur==null||typeof cur!=='object')return undefined;cur=cur[k];}return cur;}
function setPath(o,p,v){const ks=p.split('.');let cur=o;
 for(const k of ks.slice(0,-1)){if(typeof cur[k]!=='object'||cur[k]===null)cur[k]={};cur=cur[k];}
 cur[ks[ks.length-1]]=v;}
// An empty field means "use the default", which is written by REMOVING the key, not
// by storing an empty string — a config listing every default is a config nobody can
// read, and it also freezes today's defaults into the file.
function delPath(o,p){const ks=p.split('.');let cur=o;
 for(const k of ks.slice(0,-1)){if(cur==null||typeof cur[k]!=='object')return;cur=cur[k];}
 delete cur[ks[ks.length-1]];
 // Drop the container too if this emptied it, so removing the last usage override
 // does not leave `"usage": {}` behind.
 if(ks.length>1){const par=getPath(o,ks.slice(0,-1).join('.'));
  if(par&&typeof par==='object'&&!Object.keys(par).length)delPath(o,ks.slice(0,-1).join('.'));}}
const fieldId=p=>'set-'+p;
// Every "set X in audit.config.json" notice elsewhere in the panel comes here, to
// the field itself. A notice that names a setting and cannot reach it is a dead end
// on the one surface built to edit that setting.
function gotoSetting(path){showTab('guards');
 requestAnimationFrame(()=>{const t=document.getElementById(fieldId(path));
  if(!t)return;t.scrollIntoView({block:'center',behavior:'auto'});
  try{t.focus({preventScroll:true});}catch(e){}
  t.classList.add('flash');setTimeout(()=>t.classList.remove('flash'),1600);});}
function settingsLink(text,path){
 return el('button',{class:'lnk',type:'button',onclick:()=>gotoSetting(path)},text);}

function renderSettings(){const c=$('#guards');c.textContent='';
 const cfg=JSON.parse(JSON.stringify(STATE.config||{})),d=STATE.defaults;
 const findings=el('div',{class:'findings-slot'});
 // What this form would change, against the config the server last served. Read by
 // Save (to list it), by Discard (to say what is being thrown away) and by
 // beforeunload (to decide whether it may interrupt at all).
 EDITS.guards=()=>configChanges(cfg);
 // One `cfg`, one Save: the four cards are one FILE, and saving a quarter of a
 // document is not a thing this API can do.
 const save=el('button',{class:'btn primary',onclick:async()=>{
   const rows=configChanges(cfg);
   if(!rows.length){toast('nothing to save — no settings changed');return;}
   if(!await confirmChanges({title:'Save settings',rows,scope:'guards',
     verb:'Save '+rows.length+' change'+(rows.length===1?'':'s'),
     note:'writes .claude/audit.config.json'}))return;
   const res=await api('PUT','/api/config',cfg);
   findings.replaceChildren(findingsBox(res));
   saveOutcome(res,rows,'the config',findings);
   if(res.ok){STATE.config=JSON.parse(JSON.stringify(cfg));}}},'Save settings');
 // Enabled only when there is something to discard, and it says how much: a
 // control that throws work away must not be reachable by an idle click, and
 // "Discard" alone does not tell you whether pressing it costs you anything.
 const discard=el('button',{class:'btn small','data-discard':'guards',
   type:'button',onclick:async()=>{
   const rows=configChanges(cfg);
   if(!rows.length)return;
   if(!await confirmChanges({title:'Discard unsaved settings',rows,danger:1,
     lock:false,verb:'Discard '+rows.length+' change'+(rows.length===1?'':'s'),
     note:'nothing is written; the form goes back to the saved file'}))return;
   renderSettings();toast('discarded — the form is back to the saved file');}},
   'Discard');
 // Every control in this form mutates `cfg` and none of them announces it, so the
 // counter is refreshed from the events that reach the view rather than from a
 // hook added to each of the twenty-odd field builders.
 onViewEdit('guards',()=>{const n=configChanges(cfg).length;
   discard.disabled=!n;
   discard.textContent=n?('Discard '+n+' change'+(n===1?'':'s')):'Discard';});
 const CUSTOM={
  'guardEdits.tokenVars':()=>tokenVarsField(cfg,d),
  'secretPatterns.extra':()=>secretPatternsField(cfg),
  'guardEdits.customRules':()=>customRulesField(cfg),
  'usage.bands':()=>bandsField(cfg),
  'usage.pricing':()=>pricingField(cfg,d)};
 for(const grp of SETTINGS){
  const card=el('div',{class:'card',id:'setgrp-'+grp.id});
  card.append(h2h(grp.title,null,grp.topic?{topic:grp.topic}:null));
  if(grp.blurb)card.append(el('p',{class:'blurb'},grp.blurb));
  // Ordinary fields flow into a shared row; a custom one gets its own heading and
  // closes the row before it. The row is APPENDED and replaced, never cloned —
  // cloneNode copies the elements and drops every listener on them, which would
  // leave a form that looks complete and edits nothing.
  let inline=el('div',{class:'row'}),was=null;
  const flush=()=>{if(inline.childNodes.length){card.append(inline);
    inline=el('div',{class:'row'});}};
  for(const f of grp.fields){
   const tip=HELP[f.path];
   if(f.kind==='custom'){
    flush();was=null;
    card.append(el('h3',{class:'sub2'},klabel(f.label,f.path,tip)),CUSTOM[f.path]());
    continue;}
   // Switches and boxes wrap differently — a checkbox is as wide as its words, a
   // text field claims 15rem — so mixing them in one flex row leaves a ragged edge
   // that reads as an accident. They get their own rows.
   const kind=f.kind==='bool'?'bool':'input';
   if(was&&kind!==was)flush();
   was=kind;
   inline.append(kind==='bool'?boolField(cfg,d,f,tip):scalarField(cfg,d,f,tip));}
  flush();
  c.append(card);}
 // Sticky, because the form is now four cards long and a Save you have to go
 // looking for is a Save people forget to press.
 c.append(el('div',{class:'savebar'},save,discard,
   el('span',{class:'mut small'},'writes .claude/audit.config.json'),findings));}

function boolField(cfg,d,f,tip){
 const cur=getPath(cfg,f.path),def=getPath(d,f.path)!==false;
 const cb=el('input',{type:'checkbox',id:fieldId(f.path)});
 cb.checked=cur===undefined?def:cur!==false;
 cb.onchange=()=>{if(cb.checked===def)delPath(cfg,f.path);else setPath(cfg,f.path,cb.checked);};
 return el('label',{class:'f cbf'},cb,klabel(f.label,f.path,tip));}

function scalarField(cfg,d,f,tip){
 const cur=getPath(cfg,f.path),def=getPath(d,f.path);
 let inp;
 if(f.kind==='enum'){
  // Options come from the validator's own tuple — see _cfg_enums.
  inp=el('select',{id:fieldId(f.path)},
    el('option',{value:''},'default'+(def?' ('+def+')':'')),
    (ENUMS[f.enum]||[]).map(v=>el('option',Object.assign({value:v},
      v===cur?{selected:'selected'}:{}),v)));}
 else if(f.kind==='list'){
  // The id lands on the editor, not the label: it is what gotoSetting() scrolls to
  // and focuses, and a label is neither focusable nor the thing you came to edit.
  const ed=listEditor(()=>getPath(cfg,f.path)??def??[],a=>setPath(cfg,f.path,a),
    f.placeholder||'add…');
  ed.id=fieldId(f.path);ed.tabIndex=-1;
  return el('label',{class:'f wide'},klabel(f.label,f.path,tip),ed);}
 else{const t=f.kind==='date'?'date':(f.kind==='int'||f.kind==='number')?'number':'text';
  // The placeholder is the DEFAULT, so an empty box says what leaving it empty
  // gets you. Some defaults are null and mean something anyway ("beside the
  // manifest"), and an empty box beside an empty placeholder says nothing at all —
  // so a field may supply that sentence itself.
  inp=el('input',Object.assign({type:t,id:fieldId(f.path),value:cur??'',
    placeholder:def==null?(f.placeholder||''):String(def)},
    f.min!=null?{min:String(f.min)}:{}));}
 inp.oninput=inp.onchange=()=>{const v=inp.value;
  if(v===''){delPath(cfg,f.path);return;}
  if(f.kind==='int')setPath(cfg,f.path,parseInt(v,10));
  else if(f.kind==='number')setPath(cfg,f.path,Number(v));
  else setPath(cfg,f.path,v);};
 return el('label',{class:'f'},klabel(f.label,f.path,tip),inp);}

// The three defaults are ACTIVE while this list is empty, and vanish the moment it
// is not — `_config.token_vars` returns the configured list only when it is
// non-empty. An empty box that silently means "accessToken, refreshToken, idToken"
// and a one-entry box that silently means "only that one" look identical, so both
// states say which they are.
function tokenVarsField(cfg,d){
 const defs=d.guardEdits.tokenVars;
 const box=el('div',{id:fieldId('guardEdits.tokenVars'),tabindex:'-1'});
 const note=el('div');
 const cur=()=>{const v=getPath(cfg,'guardEdits.tokenVars');return Array.isArray(v)?v:[];};
 // Only the notice is redrawn. Rebuilding the list editor would take the caret out
 // of the box you are typing in, every time you add a name.
 const draw=()=>{note.textContent='';
  const list=cur();
  if(!list.length){
   note.append(el('div',{class:'ghost'},
     el('span',{class:'mut small'},'defaults are active:'),
     defs.map(v=>el('span',{class:'chip ghosted'},v))));return;}
  const missing=defs.filter(v=>!list.includes(v));
  if(missing.length)note.append(el('div',{class:'findings warn'},
    'Your list REPLACES the defaults — it does not add to them. Not covered any '
    +'more: '+missing.join(', ')+'. ',
    el('button',{class:'lnk',type:'button',onclick:()=>{
      const merged=[...missing,...cur()];setPath(cfg,'guardEdits.tokenVars',merged);
      redraw(merged);}},'put them back')));};
 let redraw=()=>{};
 const list=listEditor(cur,a=>{if(a.length)setPath(cfg,'guardEdits.tokenVars',a);
   else delPath(cfg,'guardEdits.tokenVars');draw();},'identifier…');
 redraw=()=>{const fresh=listEditor(cur,a=>{
   if(a.length)setPath(cfg,'guardEdits.tokenVars',a);
   else delPath(cfg,'guardEdits.tokenVars');draw();},'identifier…');
  list.replaceWith(fresh);draw();};
 box.append(list,note);draw();return box;}

function secretPatternsField(cfg){
 const box=el('div',{id:fieldId('secretPatterns.extra'),tabindex:'-1'});
 const cur=()=>{const v=getPath(cfg,'secretPatterns.extra');return Array.isArray(v)?v:[];};
 box.append(listEditor(cur,a=>{if(a.length)setPath(cfg,'secretPatterns.extra',a);
   else delPath(cfg,'secretPatterns.extra');},'regex…  e.g.  \\.env$',reErr));
 box.append(el('p',{class:'blurb'},'Regexes, matched case-insensitively anywhere in '
  +'the path — so ".env" also matches secrets.envelope. Anchor it (\\.env$) when you '
  +'mean the file. A pattern your browser rejects is marked here; the save is '
  +'decided by Python’s engine, which is the one the hook uses.'));
 return box;}

function customRulesField(cfg){
 const wrap=el('div',{id:fieldId('guardEdits.customRules'),tabindex:'-1'});
 // The list is held here and written into `cfg` only when it has something in it.
 // It used to create `guardEdits.customRules: []` in the config the moment this
 // field RENDERED, so merely opening Settings on a project that had never set a
 // custom rule left an edit sitting in the form — invisible while a save wrote
 // whatever the form held, and, now that a save says what it is about to do, a
 // phantom row in the confirm dialog and a Discard button offering to throw away
 // a change nobody made.
 const cur=()=>{const v=getPath(cfg,'guardEdits.customRules');
  return Array.isArray(v)?v:[];};
 let arr=cur();
 const sync=()=>{if(arr.length)setPath(cfg,'guardEdits.customRules',arr);
  else delPath(cfg,'guardEdits.customRules');};
 const rules=()=>arr;
 const draw=()=>{wrap.textContent='';
  wrap.append(el('div',{class:'rule rulehead mut small'},
    el('span',{},'path contains'),el('span',{},'banned pattern (regex)'),
    el('span',{},'message shown when it fires'),el('span',{},'')));
  rules().forEach((r,i)=>{
   // `pathPrefix` is the key on disk and stays that, because configs in the field
   // already use it. The LABEL tells the truth about what it does: the hook tests
   // `prefix in path` against the path the tool reported, usually absolute.
   const pp=el('input',{value:r.pathPrefix||'',placeholder:'realtime/'});
   pp.oninput=()=>r.pathPrefix=pp.value;
   const bp=el('input',{value:r.bannedPattern||'',placeholder:'\\.removeAllListeners\\('});
   const err=el('div',{class:'ferr'});
   const lint=()=>{const e=reErr(bp.value);bp.classList.toggle('bad',!!e);
     err.textContent=e?'your browser rejects this pattern: '+e:'';};
   bp.oninput=()=>{r.bannedPattern=bp.value;lint();};lint();
   const ms=el('input',{value:r.message||'',placeholder:'why this is banned here'});
   ms.oninput=()=>r.message=ms.value;
   wrap.append(el('div',{class:'rule'},pp,bp,ms,
     el('button',{class:'btn small','aria-label':'remove rule '+(i+1),
       onclick:()=>{arr.splice(i,1);sync();draw();}},'×')),err);});
  wrap.append(el('button',{class:'btn small',onclick:()=>{
    arr.push({pathPrefix:'',bannedPattern:'',message:''});sync();draw();}},'+ rule'));
  wrap.append(el('p',{class:'blurb'},'The path test is a SUBSTRING match, not a '
   +'prefix — "realtime/" fires under src/realtime/ and packages/web/src/realtime/ '
   +'alike. A rule missing either field, or whose pattern will not compile, is '
   +'skipped in silence when the hook runs; saving here refuses it instead.'));};
 draw();return wrap;}

// The same predicate usage_ledger.cost_bands applies: 0 < high <= outlier, and
// anything else falls back to the relative basis. Said here, next to the pair,
// because the fallback is silent everywhere else.
function bandsField(cfg){
 const box=el('div',{id:fieldId('usage.bands'),tabindex:'-1'});
 const row=el('div',{class:'row'}),warn=el('div');
 const mk=(key,lbl)=>{const p='usage.bands.'+key;
  const inp=el('input',{type:'number',min:'0',step:'0.01',id:fieldId(p),
    value:getPath(cfg,p)??'',placeholder:'not set'});
  inp.oninput=()=>{if(inp.value==='')delPath(cfg,p);else setPath(cfg,p,Number(inp.value));lint();};
  return el('label',{class:'f'},klabel(lbl,p,null),inp);};
 const lint=()=>{const hi=getPath(cfg,'usage.bands.highUSD'),
   ou=getPath(cfg,'usage.bands.outlierUSD');
  warn.textContent='';
  if(hi==null&&ou==null){warn.append(el('div',{class:'findings ok'},
    'Both empty: bands calibrate from this project’s own completed tasks '
    +'(median and p90), once there are five of them.'));return;}
  if(hi==null||ou==null){warn.append(el('div',{class:'findings warn'},
    'Set BOTH or neither — one threshold alone is ignored and the bands fall back '
    +'to the project-relative basis.'));return;}
  if(!(hi>0&&hi<=ou))warn.append(el('div',{class:'findings warn'},
    'high must be above 0 and no greater than outlier. As written this pair is '
    +'ignored at runtime and the bands fall back to the project-relative basis — '
    +'silently, which is why it is said here.'));};
 row.append(mk('highUSD','high above'),mk('outlierUSD','outlier above'));
 box.append(row,warn);lint();
 return box;}

function pricingField(cfg,d){
 const wrap=el('div',{id:fieldId('usage.pricing'),tabindex:'-1'});
 const COLS=[['in','input'],['out','output'],['cacheW5m','cache w 5m'],
   ['cacheW1h','cache w 1h'],['cacheR','cache read']];
 const cur=()=>{const v=getPath(cfg,'usage.pricing');
  return (v&&typeof v==='object'&&!Array.isArray(v))?v:{};};
 const draw=()=>{wrap.textContent='';
  const over=cur(),models=[...new Set([...Object.keys(d.usage.pricing),...Object.keys(over)])].sort();
  const tbl=el('table',{class:'ptbl'},el('thead',{},el('tr',{},
    el('th',{},'model'),COLS.map(([,l])=>el('th',{class:'n'},l)),el('th',{}))));
  const tb=el('tbody');
  models.forEach(m=>{
   const def=(d.usage.pricing||{})[m]||{},row=over[m]||{};
   const tds=COLS.map(([k])=>{
    const inp=el('input',{type:'number',min:'0',step:'0.01',value:row[k]??'',
      placeholder:def[k]==null?'—':String(def[k]),'aria-label':m+' '+k});
    inp.oninput=()=>{const o=cur();
     if(inp.value===''){if(o[m])delete o[m][k];}
     else{o[m]=o[m]||{};o[m][k]=Number(inp.value);}
     if(o[m]&&!Object.keys(o[m]).length)delete o[m];
     if(Object.keys(o).length)setPath(cfg,'usage.pricing',o);
     else delPath(cfg,'usage.pricing');};
    return el('td',{class:'n'},inp);});
   tb.append(el('tr',{},el('td',{class:'mono'},m),tds,
     el('td',{},over[m]?el('button',{class:'btn small','aria-label':'reset '+m,
       title:'drop this override and use the shipped rate',
       onclick:()=>{const o=cur();delete o[m];
        if(Object.keys(o).length)setPath(cfg,'usage.pricing',o);
        else delPath(cfg,'usage.pricing');draw();}},'reset'):null)));});
  tbl.append(tb);wrap.append(el('div',{class:'ptblwrap'},tbl));
  const add=el('input',{placeholder:'add a model id…'});
  add.addEventListener('keydown',e=>{if(e.key!=='Enter'||!add.value.trim())return;
   const o=cur();o[add.value.trim()]=o[add.value.trim()]||{};
   setPath(cfg,'usage.pricing',o);add.value='';draw();});
  wrap.append(el('div',{class:'row'},add));
  wrap.append(el('p',{class:'blurb'},'Empty means the shipped rate shown in the box, '
   +'so only what you change is written. An unrecognised model id falls back to the '
   +'longest matching prefix and then to _default, which is priced at the top tier '
   +'on purpose: over-stating spend is the safer error for a cost display.'));};
 draw();return wrap;}
// ---------- Composition ----------
function skillPicker(current,onChange){
 const inp=el('input',{value:current??'',placeholder:'search a skill…  (empty = none)'});
 inp.addEventListener('input',()=>onChange(inp.value.trim()||null));
 return comboWrap(inp,()=>REG.skills,(name,close)=>{inp.value=name;onChange(name);close();});}
function skillChips(getArr,setArr){
 const box=el('div',{class:'chipwrap'}),chips=el('div',{class:'chips'});
 const inp=el('input',{placeholder:'search a skill to add…'});
 const draw=()=>{chips.textContent='';(getArr()||[]).forEach((v,i)=>chips.append(
   el('span',{class:'chip'},v,el('button',{onmousedown:e=>{e.preventDefault();const a=getArr().slice();a.splice(i,1);setArr(a);draw();}},'×'))));};
 const add=(name,close)=>{const n=(name||'').trim();
   if(n){const a=(getArr()||[]).slice();if(!a.includes(n)){a.push(n);setArr(a);draw();}}
   inp.value='';if(close)close();};
 const combo=comboWrap(inp,()=>REG.skills.filter(s=>!(getArr()||[]).includes(s.name)),add,add);
 draw();box.append(chips,combo);return box;}
// Composition's filter state lives OUT here, not in renderComp's closure. Two
// reasons, and the second is the one that made it necessary: a re-render (after a
// save, or a poll) used to drop you back to the unfiltered table, and Overview
// needs to hand this tab a phase to open. `apply` is published by renderComp so a
// caller can change the state without re-rendering — re-rendering would throw away
// whatever is half-typed in the composition form, which is the same mistake the
// run-status poll was fixed for.
const COMPF={q:'',status:'',needs:false,open:{},apply:null};
function openInComp(pid){COMPF.q=pid;COMPF.status='';COMPF.needs=false;COMPF.open[pid]=true;
 if(COMPF.apply)COMPF.apply();showTab('comp');}
function renderComp(){const c=$('#comp');c.textContent='';const comp=STATE.composition;
 const patch={meta:{},phases:{},tasks:{}};
 const meta=el('div',{class:'card'});meta.append(h2h('Phase sign-off review skill (meta.reviewSkill)',MDESC.reviewSkill,
   {comp:'reviewSkill',label:'Phase sign-off review skill'}));
 meta.append(el('div',{class:'row'},skillPicker(comp.meta.reviewSkill,v=>patch.meta.reviewSkill=v)));
 meta.append(h2h('meta.buildCommands (JSON)',MDESC.buildCommands,
   {comp:'buildCommands',label:'Build commands'}));
 const bc=el('textarea',{});bc.value=comp.meta.buildCommands?JSON.stringify(comp.meta.buildCommands,null,2):'';
 let bcBad=false;
 bc.oninput=()=>{try{patch.meta.buildCommands=bc.value.trim()?JSON.parse(bc.value):null;
   bcBad=false;bc.style.borderColor='';}
  catch(e){bcBad=true;bc.style.borderColor='var(--err)';}};
 meta.append(bc);c.append(meta);
 // tasks: filter toolbar + ONE compact collapsible table (scales to 50x20)
 const tcard=el('div',{class:'card'});tcard.append(h2h('Composition — phases · tasks · skills',MDESC.taskSkills,
   {comp:'taskSkills',label:'Task skills'}));
 const q=el('input',{type:'search',placeholder:'filter phases & tasks…',value:COMPF.q});
 const statusBar=el('span',{class:'filtset',style:'display:inline-flex;gap:.3rem;flex-wrap:wrap'});
 const needsBtn=el('button',{class:'filt',type:'button','aria-pressed':'false',title:'only tasks with no skills yet'},'needs skills');
 const expandBtn=el('button',{class:'btn small',type:'button'},'expand all');
 const count=el('span',{class:'count',style:'margin-left:auto'});
 tcard.append(el('div',{class:'comptools'},q,el('span',{class:'filtlbl'},'phase:'),statusBar,needsBtn,expandBtn,count));
 const tbody=el('tbody');
 tcard.append(el('div',{class:'comptblwrap'},el('table',{class:'comp'},
   // The two editable columns carry the reference for the whole column. A ⓘ per
   // row would be a thousand of them saying one thing.
   el('thead',{},el('tr',{},el('th',{},'id'),el('th',{},'title'),el('th',{},'status'),
     el('th',{},flabel('model',MDESC.taskModel,{comp:'taskModel',label:'Task model'})),
     el('th',{},flabel('skills',MDESC.taskSkills,{comp:'taskSkills',label:'Task skills'})))),tbody)));

 const open=COMPF.open;
 const phaseEls=[];const byPhase={};comp.tasks.forEach(t=>{(byPhase[t.phaseId]=byPhase[t.phaseId]||[]).push(t);});
 comp.phases.forEach(ph=>{
  const tasks=byPhase[ph.id]||[];
  const rev=el('input',{value:ph.reviewModel??'',placeholder:'review model'});
  rev.oninput=()=>{patch.phases[ph.id]={reviewModel:rev.value.trim()||null};};
  rev.onclick=e=>e.stopPropagation();
  const pr=el('tr',{class:'phase','data-status':ph.status||''});
  pr.append(el('td',{colspan:'5'},el('div',{class:'phtd'},
    el('span',{class:'tri'}),el('span',{class:'mono'},ph.id||''),el('strong',{},ph.title||''),
    (ph.area||[]).map(a=>el('span',{class:'badge area'},a)),
    el('span',{class:'st','data-status':ph.status||''},label(ph.status)),
    el('span',{class:'count'},tasks.length+(tasks.length===1?' task':' tasks')),
    el('span',{class:'comp-review'},flabel('review',MDESC.phaseReviewModel,
      {comp:'phaseReviewModel',label:'Phase review model'}),rev))));
  pr.onclick=()=>{open[ph.id]=!open[ph.id];refresh();};
  tbody.append(pr);
  const taskEls=[];
  tasks.forEach(t=>{
   const tp={};const model=el('input',{value:t.model??'',placeholder:'—'});
   model.oninput=()=>{tp.model=model.value.trim()||null;patch.tasks[t.id]=tp;};
   const getSkills=()=>tp.skills!==undefined?tp.skills:(t.skills||[]);
   const chips=skillChips(getSkills,a=>{tp.skills=a;patch.tasks[t.id]=tp;if(COMPF.needs)refresh();});
   const tr=el('tr',{class:'task','data-status':t.status||''});
   tr.append(el('td',{class:'tid'},t.id||''),el('td',{class:'ttitle',title:t.title||''},t.title||''),
     el('td',{},el('span',{class:'st','data-status':t.status||''},label(t.status))),
     el('td',{class:'tmodel'},model),el('td',{class:'tskills'},chips));
   tbody.append(tr);
   taskEls.push({id:t.id||'',title:t.title||'',tr,getSkills});
  });
  phaseEls.push({id:ph.id,title:ph.title||'',status:ph.status||'',area:(ph.area||[]).join(' '),tr:pr,tasks:taskEls});
 });
 [...new Set(comp.phases.map(p=>p.status).filter(Boolean))].sort().forEach(s=>{
  const b=el('button',{class:'filt',type:'button','data-status':s,'aria-pressed':'false'},label(s));
  b.onclick=()=>{COMPF.status=COMPF.status===s?'':s;syncFilters();refresh();};
  statusBar.append(b);});
 // aria-pressed alongside the class: which filter is on was carried by the accent
 // fill alone, which a screen reader never sees. Driven from COMPF rather than
 // toggled in place, so a filter set from elsewhere (Overview) shows here too.
 function syncFilters(){
  [...statusBar.children].forEach(x=>{const on=x.getAttribute('data-status')===COMPF.status;
   x.classList.toggle('on',on);x.setAttribute('aria-pressed',on?'true':'false');});
  needsBtn.classList.toggle('on',COMPF.needs);
  needsBtn.setAttribute('aria-pressed',COMPF.needs?'true':'false');}
 needsBtn.onclick=()=>{COMPF.needs=!COMPF.needs;syncFilters();refresh();};
 expandBtn.onclick=()=>{const anyClosed=phaseEls.some(P=>!open[P.id]);phaseEls.forEach(P=>open[P.id]=anyClosed);refresh();};
 const hit=(s,term)=>!term||s.toLowerCase().includes(term);
 function refresh(){
  COMPF.q=q.value;
  const term=q.value.trim().toLowerCase();const forced=(term!=='')||COMPF.needs;let visP=0,visT=0;
  phaseEls.forEach(P=>{
   const pText=hit(P.id+' '+P.title+' '+P.area,term);let anyT=false;
   P.tasks.forEach(T=>{const tHit=pText||hit(T.id+' '+T.title,term);
    const needHit=!COMPF.needs||((T.getSkills()||[]).length===0);T._m=tHit&&needHit;if(T._m)anyT=true;});
   const showP=(!COMPF.status||P.status===COMPF.status)&&(pText||anyT)&&(!COMPF.needs||anyT);
   P.tr.style.display=showP?'':'none';if(showP)visP++;
   const isOpen=showP&&(forced||!!open[P.id]);P.tr.classList.toggle('open',isOpen);
   P.tasks.forEach(T=>{const showT=showP&&isOpen&&T._m;T.tr.style.display=showT?'':'none';if(showT)visT++;});});
  count.textContent=(term||COMPF.status||COMPF.needs)?(visP+' / '+phaseEls.length+' phases · '+visT+' tasks')
    :(phaseEls.length+' phases · '+comp.tasks.length+' tasks');
  expandBtn.textContent=phaseEls.some(P=>!open[P.id])?'expand all':'collapse all';}
 // Published for whoever wants to scope this tab without rebuilding it.
 COMPF.apply=()=>{q.value=COMPF.q;syncFilters();refresh();};
 syncFilters();q.addEventListener('input',refresh);refresh();

 EDITS.comp=()=>compChanges(patch);
 const save=el('button',{class:'btn primary',onclick:async()=>{
   // The textarea only writes into the patch when its contents PARSE, so an
   // unparseable box would confirm — and then save — the last value that did. A
   // dialog that shows something other than what the form holds is worse than no
   // dialog, so this is refused at the door and the field says which one it is.
   if(bcBad){toast('meta.buildCommands is not valid JSON — fix it or clear it '
     +'before saving','err');bc.focus();return;}
   const rows=compChanges(patch);
   if(!rows.length){toast('nothing to save — no values changed');return;}
   if(!await confirmChanges({title:'Save composition',rows,scope:'comp',
     verb:'Save '+rows.length+' change'+(rows.length===1?'':'s'),
     note:'writes '+STATE.manifestPath}))return;
   const clean={meta:{},phases:patch.phases,tasks:patch.tasks};
   for(const k of Object.keys(patch.meta))clean.meta[k]=patch.meta[k];
   const res=await api('PUT','/api/composition',clean);
   if(!res.ok){c.querySelector('.findings-slot').replaceChildren(findingsBox(res));
    saveOutcome(res,rows,'the manifest',null);return;}
   // Re-render from the saved state. Without it the form kept showing the values
   // you typed rather than the values on disk — indistinguishable while they
   // agree, and silently wrong the moment the server normalised one or refused
   // part of a patch. COMPF is hoisted, so the filter, the search and which
   // phases were open all survive this.
   STATE=await api('GET','/api/state');renderComp();renderOver();
   const slot=$('#comp .findings-slot');
   if(slot)slot.replaceChildren(findingsBox(res));
   saveOutcome(res,rows,'the manifest',slot);}},'Save composition');
 const discard=el('button',{class:'btn small','data-discard':'comp',type:'button',
   onclick:async()=>{
   const rows=compChanges(patch);
   if(!rows.length)return;
   if(!await confirmChanges({title:'Discard unsaved composition edits',rows,
     danger:1,lock:false,
     verb:'Discard '+rows.length+' change'+(rows.length===1?'':'s'),
     note:'nothing is written; the table goes back to the saved manifest'}))return;
   renderComp();toast('discarded — the table is back to the saved manifest');}},
   'Discard');
 onViewEdit('comp',()=>{const n=compChanges(patch).length;
   discard.disabled=!n;
   discard.textContent=n?('Discard '+n+' change'+(n===1?'':'s')):'Discard';});
 tcard.append(el('div',{class:'row',style:'margin-top:.9rem'},save,discard),
   el('div',{class:'findings-slot'}));
 if(!STATE.manifestExists)tcard.append(el('div',{class:'findings warn'},'No manifest yet — run /audit:init first.'));
 if(STATE.manifestLocked)tcard.append(el('div',{class:'findings warn'},'Manifest is locked by a running /audit command.'));
 c.append(tcard);
 // building blocks — one table, sub-tabs switch context (skills / agents / mcp)
 const bb=el('div',{class:'card'});
 bb.append(h2h('Available building blocks (discovered)',
   'Skills & agents found in this project, your ~/.claude, and installed plugins — plus MCP servers in scope. Use these names in the pickers above.'));
 const datasets={skills:REG.skills,agents:REG.agents,
   mcp:(REG.mcp||[]).map(n=>({name:n,source:'mcp',description:''}))};
 const subtabs=el('div',{class:'subtabs'}),host=el('div',{class:'regtblwrap'});let cur='skills';
 const drawTbl=()=>{const items=datasets[cur]||[];const tb=el('tbody');
   if(!items.length)tb.append(el('tr',{},el('td',{colspan:'3',class:'mut'},'none found')));
   items.forEach(it=>tb.append(el('tr',{},el('td',{class:'mono'},it.name),
     el('td',{},it.source?el('span',{class:'src badge'},it.source):null),
     el('td',{class:'d'},it.description||''))));
   host.replaceChildren(el('table',{class:'regtbl'},
     el('thead',{},el('tr',{},el('th',{},'name'),el('th',{},'source'),el('th',{},'description'))),tb));};
 ['skills','agents','mcp'].forEach(k=>subtabs.append(el('button',{class:'subtab'+(k===cur?' on':''),
   onclick:e=>{cur=k;[...subtabs.children].forEach(x=>x.classList.toggle('on',x===e.currentTarget));drawTbl();}},
   k+' ('+(datasets[k]||[]).length+')')));
 drawTbl();bb.append(subtabs,host);c.append(bb);}
// One malformed manifest can emit a finding PER phase, per task and per indexed
// file: a 300-phase repo produced 1009 of them, joined into a single paragraph
// that filled the screen and told the reader nothing. But 1009 findings are not
// 1009 problems — they were four mistakes repeated. So group by shape, count each,
// show one real example, and keep the raw list one click away.
const FGROUP_MIN=6, FSHOW=6, FRAW=200;
function findingKind(s){
 const i=s.indexOf(': ');
 return (i>0?s.slice(i+2):s)
  .replace(/'[^']*'/g,"'*'").replace(/\[[^\]]*\]/g,'[*]').replace(/\d+/g,'#');}
// Named for the manifest specifically: findingsBox() already exists above for
// save-result feedback, and a second function of the same name would hoist over it
// and break every config save.
function manifestFindingsBox(n,list){
 const box=el('div',{class:'findings err'},
   el('b',{},'✗ '+n+' finding(s)'));
 if(list.length<FGROUP_MIN){
  box.append(' '+list.join(' · '));return box;}
 const by=new Map();
 for(const f of list){const k=findingKind(f);
  const g=by.get(k)||{n:0,eg:f};g.n++;by.set(k,g);}
 const groups=[...by.entries()].sort((a,b)=>b[1].n-a[1].n);
 const ul=el('ul',{class:'fgrp'});
 groups.slice(0,FSHOW).forEach(([k,g])=>ul.append(el('li',{},
   el('span',{class:'fn'},g.n+'×'),
   el('span',{},k,el('div',{class:'feg'},g.n>1?'e.g. '+g.eg:g.eg)))));
 box.append(el('div',{},groups.length===1?'one problem, repeated:'
   :groups.length+' distinct problems'
    +(groups.length>FSHOW?' ('+FSHOW+' most common shown)':'')+':'),ul);
 const ol=el('ol',{});
 list.slice(0,FRAW).forEach(f=>ol.append(el('li',{},f)));
 if(list.length>FRAW)ol.append(el('li',{},'… and '+(list.length-FRAW)+
   ' more — run /audit:validate for the complete list'));
 box.append(el('details',{class:'fall'},
   el('summary',{},'every finding, unfolded'),ol));
 return box;}

// ---------- live run status ----------
// Who is driving which phase changes WHILE you are looking at the panel — that is
// the whole point of the badges, and until now they were a snapshot taken at page
// load. A colleague taking a phase lock in another worktree appeared only if you
// happened to reload.
//
// It polls the narrow endpoint, never /api/state: re-rendering from full state
// would discard whatever is half-typed in the guards form, so "live" would have
// cost you your edits. And it only repaints Overview, which has no inputs.
//
// Stops while the tab is hidden. A backgrounded panel polling a colleague's laptop
// every few seconds forever is the kind of thing people notice in a battery graph
// and never forgive.
let RUNSTATUS=null, RUNPOLL=null;
function runStatusKey(rs){return JSON.stringify(rs&&{i:rs.index,p:rs.phases});}
async function pollRunStatus(){
 if(document.hidden)return;
 try{
  const next=await api('GET','/api/runstatus');
  if(runStatusKey(next)===runStatusKey(RUNSTATUS))return;   // no repaint on no change
  RUNSTATUS=next;
  if(!$('#over').classList.contains('hidden'))renderOver();
 }catch(e){/* a panel that dies because a poll failed is worse than a stale badge */}
}
function startRunPoll(){
 if(RUNPOLL)clearInterval(RUNPOLL);
 RUNPOLL=setInterval(pollRunStatus,5000);
}
document.addEventListener('visibilitychange',()=>{if(!document.hidden)pollRunStatus();});

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
const OVF={q:'',ts:'',bs:'',byArea:false,sort:'plan'};
// Nothing-to-see-first: the statuses that need a human come before the ones that
// do not, in the strips and in the status sort. Plan order is still the default —
// a plan is written in an order and that order means something.
const OVORDER=['in_progress','blocked','pending','done'];
const OVBUGORDER=['open','triaged','in_progress','fixed','wontfix'];
const ovRank=(o,s)=>{const i=o.indexOf(s);return i<0?o.length:i;};
const ovAnyFilter=()=>!!(OVF.q.trim()||OVF.ts||OVF.bs);
function ovPill(status,n,text,on,onclick,tip,cls){
 return el('button',{class:'ovpill'+(cls?' '+cls:''),type:'button','data-status':status||'',
  'aria-pressed':on?'true':'false',title:tip||'',onclick:onclick},text,el('b',{},String(n)));}
// A copy button that fails silently is worse than no copy button: clipboard.write
// can be refused, and the reader is left believing they have the command.
function ovCopy(btn,text){
 const done=()=>{const was=btn.textContent;btn.textContent='Copied';
  setTimeout(()=>{btn.textContent=was;},1600);};
 const manual=()=>{const ta=el('textarea',{style:'position:fixed;top:-1000px;opacity:0'});
  ta.value=text;document.body.append(ta);ta.select();
  let ok=false;try{ok=document.execCommand('copy');}catch(e){ok=false;}
  ta.remove();if(ok)done();else toast('could not copy — the command is '+text,'err');};
 try{navigator.clipboard.writeText(text).then(done,manual);}catch(e){manual();}}
function renderOver(){const c=$('#over');const r=STATE.rollup;
 // The poll repaints this view under the reader's hands. Put the caret back where
 // it was, or typing a five-letter search while a colleague takes a phase lock
 // loses the last three letters and the focus with them.
 const act=document.activeElement,keepQ=!!(act&&act.id==='ovq'),
   caret=keepQ?act.selectionStart:0;
 c.textContent='';
 const card=el('div',{class:'card'});
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
 [['plan','plan order'],['progress','progress'],['status','status']].forEach(([v,t])=>{
  const o=el('option',{value:v},t);if(OVF.sort===v)o.selected=true;sortSel.append(o);});
 const tools=el('div',{class:'ovtools'},qIn,el('span',{class:'filtlbl'},'sort:'),sortSel);
 const areaTags=Object.keys(r.areas||{});
 if(areaTags.length){
  const cb=el('input',{type:'checkbox',id:'ovarea'});cb.checked=OVF.byArea;
  cb.onchange=()=>{OVF.byArea=cb.checked;renderOver();};
  tools.append(el('label',{class:'inl',for:'ovarea'},cb,'group by area'));}
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
 const ordered=r.phases.filter(hitP);
 const pct=p=>p.total?100*p.done/p.total:0;
 if(OVF.sort==='progress')ordered.sort((a,b)=>pct(b)-pct(a));
 else if(OVF.sort==='status')ordered.sort((a,b)=>ovRank(OVORDER,a.status)-ovRank(OVORDER,b.status));
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
  return el('button',{class:'ovrow',type:'button','data-status':p.status||'','data-phase':p.id,
    title:'open '+p.id+' in Composition',onclick:()=>openInComp(p.id)},
   el('span',{class:'pid'},p.id),
   el('span',{class:'ptitle'},p.title||''),
   el('span',{class:'st','data-status':p.status||''},label(p.status)),
   areaBadges,runBadge,
   OVF.ts?el('span',{class:'ovmatch'},((pStatus[p.id]||{})[OVF.ts]||0)+' '+label(OVF.ts).toLowerCase()):null,
   el('span',{class:'bar'},el('i',{style:'width:'+w+'%'})),
   el('span',{class:'mut'},p.done+'/'+p.total),
   // The line the plan is actually about. It was in the rollup all along and the
   // panel showed the title, which says what the phase is called, not what it is for.
   p.desiredOutcome?el('span',{class:'ovout',title:p.desiredOutcome},p.desiredOutcome):null);}
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
 count.textContent=ovAnyFilter()?(ordered.length+' / '+r.phases.length+' phases')
   :(r.phases.length+' phases · '+r.tasks.total+' tasks');
 c.append(card);

 // --- ready now ----------------------------------------------------------------
 const tById={};tasks.forEach(t=>{tById[t.id]=t;});
 // Deliberately NOT scoped by the strips: this is the do-something-now list, and a
 // filter set to look at what is blocked must not empty the one card that says
 // where to start.
 const ready=r.ready||[];
 const rcard=el('div',{class:'card'});
 rcard.append(h2h('Ready now',
   'Tasks whose blockers are all done and whose phase is not gated — the ones /audit:run '
   +'will accept right now. Copy the command rather than retyping an id.'));
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
 if(ready.length>RSHOW)rcard.append(el('div',{class:'mut'},
   '+'+(ready.length-RSHOW)+' more ready — see Composition'));
 c.append(rcard);

 // --- bugs ---------------------------------------------------------------------
 const bugs=STATE.bugs||[];
 if(bugs.length){
  const bcard=el('div',{class:'card'});
  bcard.append(h2h('Bugs',
    'Status here is the EFFECTIVE status the totals above count: a bug materialized '
    +'into a task reads Fixed once that task is done, so the list and the pills can '
    +'never disagree.'));
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

 if(keepQ){const n=$('#ovq');if(n){n.focus();try{n.setSelectionRange(caret,caret);}catch(e){}}}}
// ---------- capability policy: the switchboard ----------
// `{"default":"deny","allow":["code-*"]}` is four words that decide the fate of
// every skill on the machine, and nobody can hold that cross-product in their
// head. This view IS the cross-product: one row per capability the project can
// actually reach, the verdict the guard would give it, and the reason.
//
// Two rules run through all of it.
//
// The verdicts are the SERVER's — computed by `_policy.resolve`, the function the
// hook itself calls — and are never recomputed here. A second matcher in the
// browser would eventually disagree with the guard, and disagreeing about a denial
// is the one thing a preview must not do. The consequence is that a verdict is
// true of the SAVED policy: an edited row is marked as pending rather than
// re-judged, and the verdicts are re-read from the server after every save.
//
// And the draft is the block AS WRITTEN (`stored`), never the merged one. PUT
// /api/policy replaces the block wholesale, so anything this form does not
// represent — a comment key, a pattern nobody clicked — would be destroyed by
// someone who came to flip one switch. Which is also why the raw rules are a table
// of their own further down: a rule the form cannot show is a rule it must not be
// trusted to save.
let POLICY=null;
// null means "no policy block on disk, and nothing typed yet". It is not {}: an
// empty object is a policy someone wrote, and writing one where there was none is
// a change this view must not make by rendering.
let PDRAFT=null;
const PKINDS=['skills','agents','mcp'];
const PKLABEL={skills:'Skills',agents:'Subagents',mcp:'MCP servers'};
const PF={kind:'skills',q:'',bad:false};
// The nodes the last save left behind — the ✓/✗ box and, if the file had moved
// under the reader, the mismatch warning. A save re-renders the whole view to pick
// up the server's fresh verdicts, which would otherwise throw away the one part of
// the page that says what just happened. Consumed once, so an edit made afterwards
// does not sit under a stale "saved".
let PNOTE=null;
const pClone=o=>(o==null?null:JSON.parse(JSON.stringify(o)));
// Every edit goes through here. It drops the last save's box — that box describes
// a file this form no longer matches — and redraws.
function pEdit(fn){PNOTE=null;fn();renderPolicy();}
function pBlock(){if(PDRAFT===null)PDRAFT={};return PDRAFT;}
const pKindCfg=(b,k)=>((b||{})[k]||{});
const pEnabled=()=>((PDRAFT||{}).enabled!==false);
const pOnViolation=()=>((PDRAFT||{}).onViolation||(POLICY&&POLICY.onViolation)||'deny');
const pDefault=k=>(pKindCfg(PDRAFT,k).default==='deny'?'deny':'allow');
// What a violation DOES, in the words the hook uses. Said next to the control that
// picks it, because "deny" and "warn" are not degrees of the same thing: one
// refuses the call and one lets it through with a sentence attached.
const PVIOL={deny:'refuse the call',ask:'ask for approval, per call',
 warn:'allow it and say so'};
// Where this row's rule is written, for one scope: '' (nothing), 'allow', 'deny'.
// EXACT names only, and deliberately so — a glob that happens to match is not this
// row's rule to move, and silently dropping `code-*` because somebody pressed
// Default on one skill it covers would change the verdict of every other one. A
// pattern is edited where it is written, in the rules table below.
function pRuleOf(block,kind,name,tag){
 const k=pKindCfg(block,kind);
 const src=tag?((k.areas||{})[tag]||{}):k;
 for(const l of ['deny','allow'])if((src[l]||[]).indexOf(name)>=0)return l;
 return '';}
function pSetRule(kind,name,tag,val){
 const b=pBlock(),k=b[kind]=b[kind]||{};
 let src=k;
 if(tag){const a=k.areas=k.areas||{};src=a[tag]=a[tag]||{};}
 ['allow','deny'].forEach(l=>{if(!Array.isArray(src[l]))return;
  const i=src[l].indexOf(name);if(i>=0)src[l].splice(i,1);});
 if(val){src[val]=src[val]||[];src[val].push(name);}
 pPrune();}
function pAddPattern(kind,list,tag,pattern){
 const b=pBlock(),k=b[kind]=b[kind]||{};
 let src=k;
 if(tag){const a=k.areas=k.areas||{};src=a[tag]=a[tag]||{};}
 src[list]=src[list]||[];
 if(src[list].indexOf(pattern)<0)src[list].push(pattern);}
function pDropPattern(kind,list,tag,pattern){
 const src=tag?((pKindCfg(PDRAFT,kind).areas||{})[tag]||{}):pKindCfg(PDRAFT,kind);
 const arr=src[list];if(!Array.isArray(arr))return;
 const i=arr.indexOf(pattern);if(i>=0)arr.splice(i,1);
 pPrune();}
// Emptying a list REMOVES it, and removing the last one removes its container —
// the same convention Settings writes with, for the same reason: a block listing
// every default is a block nobody can read, and `"areas":{"web":{"deny":[]}}` is
// a rule that looks like a rule and is not one.
function pPrune(){
 if(!PDRAFT)return;
 for(const kind of PKINDS){
  const k=PDRAFT[kind];if(!k||typeof k!=='object')continue;
  ['allow','deny'].forEach(l=>{if(Array.isArray(k[l])&&!k[l].length)delete k[l];});
  if(k.areas&&typeof k.areas==='object'){
   for(const tag of Object.keys(k.areas)){const r=k.areas[tag]||{};
    ['allow','deny'].forEach(l=>{if(Array.isArray(r[l])&&!r[l].length)delete r[l];});
    if(!Object.keys(r).length)delete k.areas[tag];}
   if(!Object.keys(k.areas).length)delete k.areas;}
  if(!Object.keys(k).length)delete PDRAFT[kind];}}
// The change rows, computed the same way Settings computes its own: this block is
// one key of the config, the server writes it through the one config writer, and
// the echo comes back as `config · policy.skills.deny · … -> …`. So the dialog is
// fed a whole config with this block swapped in, and cannot describe the save in a
// vocabulary the server does not answer in.
function policyChanges(){
 if(PDRAFT===null)return [];
 const cfg=JSON.parse(JSON.stringify(STATE.config||{}));
 cfg.policy=PDRAFT;
 return configChanges(cfg);}
// Every pattern in the draft, in the order `resolve` reads them: deny before
// allow, project before area. Annotated from the server's own matching where the
// server has seen the pattern — a rule typed a second ago has no match count and
// says so rather than borrowing the count of the one it replaced.
function pDraftRules(kind){
 const out=[],k=pKindCfg(PDRAFT,kind);
 const push=(scope,list)=>{const src=scope?((k.areas||{})[scope]||{}):k;
  (src[list]||[]).forEach(p=>out.push({scope:scope||null,list:list,pattern:p}));};
 push(null,'deny');push(null,'allow');
 Object.keys(k.areas||{}).sort().forEach(tag=>{push(tag,'deny');push(tag,'allow');});
 return out;}
const pRuleKey=r=>JSON.stringify([r.scope||null,r.list,r.pattern]);
function pServerRules(kind){const m={};
 ((POLICY.rules||{})[kind]||[]).forEach(r=>{m[pRuleKey(r)]=r;});return m;}

function renderPolicy(){
 const c=$('#policy');
 // The whole view redraws on every switch, so put back the two things a redraw
 // throws away: the caret in whichever box was being typed in, and how far down
 // the capability table the reader had scrolled.
 const act=document.activeElement,
   keepId=act&&act.id&&(act.id==='polq'||act.id==='poladdpat')?act.id:null,
   caret=keepId?act.selectionStart:0,
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
   'Described above: the policy as SAVED. You have '+pending.length+' unsaved '
   +'change'+(pending.length===1?'':'s')+' — verdicts are re-read from the server '
   +'once they are written.'));
 (POLICY.findings||[]).forEach(f=>head.append(
   el('div',{class:'findings err','data-pfinding':'1'},'✗ '+f)));
 (POLICY.warnings||[]).forEach(w=>head.append(el('div',{class:'findings warn'},'! '+w)));
 const enb=el('input',{type:'checkbox',id:'polenabled'});enb.checked=en;
 enb.onchange=()=>pEdit(()=>{const b=pBlock();
   if(enb.checked)delete b.enabled;else b.enabled=false;pPrune();});
 const ovSel=el('select',{id:'polonviol','aria-label':'what a violation does'});
 (POLICY.onViolationChoices||['deny']).forEach(v=>{
   const o=el('option',{value:v},v+' — '+(PVIOL[v]||''));
   if(pOnViolation()===v)o.selected=true;ovSel.append(o);});
 // Back to the shipped default is written by REMOVING the key, unless the file
 // states it — a block that spells out every default is a block nobody can read,
 // and this one is meant to be read in a pull request.
 ovSel.onchange=()=>pEdit(()=>{const b=pBlock();
   if(ovSel.value===(POLICY.onViolation||'deny')&&!(POLICY.stored||{}).onViolation)
    delete b.onViolation;
   else b.onViolation=ovSel.value;
   pPrune();});
 head.append(el('div',{class:'row'},
   el('label',{class:'f cbf'},enb,flabel('Policy enabled',
     'Off writes policy.enabled:false, which is how you keep the rules and stop '
     +'applying them.')),
   el('label',{class:'f'},flabel('On a violation','What the hook does when a call '
     +'breaks a rule. warn is deliberately NOT a permission grant — it lets the '
     +'call through and says so.'),ovSel)));
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
 head.append(pHonesty());
 c.append(head);

 // --- one kind at a time ------------------------------------------------------
 const card=el('div',{class:'card'});
 const kstrip=el('div',{class:'ovstrip'},el('span',{class:'ovlbl'},'Kind'));
 PKINDS.forEach(k=>kstrip.append(el('button',{class:'ovpill',type:'button','data-pk':k,
   'aria-pressed':PF.kind===k?'true':'false',
   title:'the '+PKLABEL[k].toLowerCase()+' this project can reach',
   onclick:()=>{PF.kind=k;PF.q='';PNOTE=null;renderPolicy();}},
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
 const q=PF.q.trim().toLowerCase();
 const shown=rows.filter(r=>(!q||(r.name+' '+(r.source||'')).toLowerCase().includes(q))
   &&(!PF.bad||r.verdict==='violation'));
 const qIn=el('input',{type:'search',id:'polq',value:PF.q,
   placeholder:'search '+PKLABEL[kind].toLowerCase()+'…',
   'aria-label':'search '+PKLABEL[kind].toLowerCase()});
 qIn.addEventListener('input',()=>{PF.q=qIn.value;renderPolicy();});
 const bad=el('input',{type:'checkbox',id:'polbad'});bad.checked=PF.bad;
 bad.onchange=()=>{PF.bad=bad.checked;renderPolicy();};
 const tools=el('div',{class:'ovtools'},qIn,
   el('label',{class:'inl',for:'polbad'},bad,'violations only'),
   el('span',{class:'count',style:'margin-left:auto'},
     shown.length===rows.length?(rows.length+' discovered')
       :(shown.length+' / '+rows.length)));
 if(q||PF.bad)tools.append(el('button',{class:'btn small',type:'button',
   'data-polclear':'1',onclick:()=>{PF.q='';PF.bad=false;renderPolicy();}},
   'Clear filters'));
 card.append(tools);
 const cols=POLICY.areaInfo||[];
 const head2=el('tr',{},el('th',{},'capability'),el('th',{},'source'),
   el('th',{},'rule'),
   cols.map(a=>el('th',{class:'ar'+(a.active?'':' dormant'),
     title:a.active
       ?('area '+a.tag+' has work in progress, so its rules apply right now')
       :('no phase tagged '+a.tag+' has work in progress, so its rules decide '
         +'nothing until one does')},
     a.tag,el('span',{class:'mut'},a.active?'live':'dormant'))),
   el('th',{},'verdict, and why'));
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
  tr.append(el('td',{},r.source?el('span',{class:'src badge'},r.source):null));
  tr.append(pCell(kind,r,null));
  cols.forEach(a=>tr.append(pCell(kind,r,a.tag)));
  tr.append(el('td',{class:'vd'},
    el('span',{class:'pv '+r.verdict},r.verdict==='violation'?'Violation':'Allowed'),
    el('span',{class:'pbasis'},r.basis||'')));
  tb.append(tr);});
 if(!shown.length)card.append(el('div',{class:'ovempty','data-polempty':'1'},
   rows.length?'No '+PKLABEL[kind].toLowerCase()+' match this filter. '
     :'Nothing of this kind was discovered for this project. A rule can still be '
      +'written for it below — it will apply the day something matches it.',
   rows.length?el('button',{class:'btn small',type:'button','data-polclear':'1',
     onclick:()=>{PF.q='';PF.bad=false;renderPolicy();}},'Clear filters'):null));
 else card.append(el('div',{class:'poltblwrap',id:'poltbl'},
   el('table',{class:'poltbl'},el('thead',{},head2),tb)));

 // --- the block as written ----------------------------------------------------
 card.append(el('h3',{class:'sub2'},flabel('Rules as written',
   'The block for this kind, in the order the guard reads it: deny before allow, '
   +'project before area. The switches above write exact names here; a pattern can '
   +'only be written and removed here.')));
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
    el('thead',{},el('tr',{},el('th',{},'scope'),el('th',{},'list'),
      el('th',{},'pattern'),el('th',{},'matches now'),el('th',{}))),rtb));}
 card.append(pAddRow(kind));
 c.append(card);

 // --- save --------------------------------------------------------------------
 const save=el('button',{class:'btn primary','data-psave':'1',onclick:async()=>{
   const chg=policyChanges();
   if(!chg.length){toast('nothing to save — the policy is unchanged');return;}
   if(!await confirmChanges({title:'Save capability policy',rows:chg,scope:'policy',
     verb:'Save '+chg.length+' change'+(chg.length===1?'':'s'),
     note:'writes .claude/audit.config.json'}))return;
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
 const discard=el('button',{class:'btn small','data-discard':'policy',type:'button',
   onclick:async()=>{
   const chg=policyChanges();
   if(!chg.length)return;
   if(!await confirmChanges({title:'Discard unsaved policy changes',rows:chg,danger:1,
     lock:false,verb:'Discard '+chg.length+' change'+(chg.length===1?'':'s'),
     note:'nothing is written; the form goes back to the saved block'}))return;
   pEdit(()=>{PDRAFT=pClone(POLICY&&POLICY.stored);});
   toast('discarded — the form is back to the saved policy');}},
   pending.length?('Discard '+pending.length+' change'+(pending.length===1?'':'s'))
     :'Discard');
 discard.disabled=!pending.length;
 c.append(el('div',{class:'savebar'},save,discard,
   el('span',{class:'mut small'},'writes .claude/audit.config.json'),findings));

 if(keepId){const n=document.getElementById(keepId);
  if(n){n.focus();try{n.setSelectionRange(caret,caret);}catch(e){}}}
 if(scrolled){const w=$('#poltbl');if(w)w.scrollTop=scrolled;}}

// How long ago, in words. The panel never decides whether that is TOO long: how
// stale a marker may be is /audit:doctor's judgement, and a second threshold here
// is a threshold that can disagree with it.
function pAgo(days){
 if(days==null)return 'at an unknown time';
 if(days<1/24)return 'within the hour';
 if(days<1)return 'today';
 return Math.round(days)+' day(s) ago';}

// One switch, for one capability, in one scope.
function pCell(kind,r,tag){
 const cur=pRuleOf(PDRAFT,kind,r.name,tag),
   was=pRuleOf(POLICY.stored,kind,r.name,tag),
   moved=cur!==was;
 const sel=el('select',{class:'prule','data-set':cur||null,
   'data-prule':r.name+(tag?('@'+tag):''),
   'aria-label':(tag?('rule for area '+tag+', '):'project rule for ')+r.name});
 [['','—'],['allow','allow'],['deny','deny']].forEach(([v,t])=>{
  const o=el('option',{value:v},t);if(cur===v)o.selected=true;sel.append(o);});
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
// ---------- usage ----------
// ONE filter state. The chart's dimension is DERIVED from it, never stored
// separately -- an earlier version kept a parallel drill-down object and filtered
// author in two places, which let you select one author, click another's line, and
// land in a permanently empty view whose controls said nothing was filtered. With a
// single author slot that state cannot be represented at all.
let USAGE=null;
const UF={model:'',author:'',phase:'',task:'',agent:'',attr:'',day:'',q:'',range:'all'};
const DIMS=['model','author','phase','task','agent','attr','day','q'];
// What a filter is CALLED where it is shown. The internal name is the fact-tuple
// field, which is the right name in the code and the wrong one on a chip: `attr` is
// not a word, and `q` is not a dimension anybody typed.
// `range` is not in DIMS and never wears a chip, but it is a filter a reader can
// be asked about by name, so it is named here with the rest rather than spelled
// out at the one place that asks.
const DLABEL={q:'text',attr:'attributed to',agent:'agent',day:'date',
 range:'time range'};
const fName=d=>DLABEL[d]||d;
const fVal=d=>d==='day'?UF.day.replace('..',' to ')
 :d==='range'?(UF.range==='all'?'all time':'last '+UF.range+' days'):UF[d];
let UORDER=[];                 // dimensions in the order they were set (Esc pops)
let UQT=null;                  // search debounce; the whole tab re-renders per change
const SHOWN={phase:8,model:8,author:8,task:8};   // ranked-list depth; 'other' pages
const F={ts:0,phase:1,task:2,model:3,author:4,agent:5,attr:6,tokens:7,cost:8,msgs:9};
const RISKS=['high','med','low','unrated'];
const TOP=8;
// Token counts are a MAGNITUDE and are always compact - '3.2M', never '3,230,000'.
// dp=2 is for hover: pointing at a bar buys '3.23M', more precision than the label
// without dumping the raw integer. Countables (messages, sessions) are not
// magnitudes and keep their separators - '47,625' is a number you can act on.
// Mirrors _fmt_tokens in render-report.py; the two must agree or one surface will
// quietly disagree with the other about the same number.
const uTok=(n,dp=1)=>{n=n||0;for(const[l,s]of[[1e9,'B'],[1e6,'M'],[1e3,'K']])
 if(Math.abs(n)>=l)return (n/l).toFixed(dp)+s;return String(Math.round(n));};
const uCost=x=>!x?'$0.00':(Math.abs(x)<0.01?'<$0.01':'$'+x.toFixed(2));
const uPct=x=>x==null?'—':x<1&&x>0?'<1%':x.toFixed(0)+'%';
// A share of nothing is not 0% and it is certainly not 100% — it is undefined, and
// the honest rendering of undefined is the same em dash a tile with no series
// already draws. EVERY printed percentage in this tab is computed here, because
// the idiom it replaces — `||1` on the denominator, written to dodge a divide by
// zero — answers a question that has no answer: `100*(1-0)/1` made the
// `attributed` tile read 100% over an empty selection, beside three honest zeros,
// on the one tile of the four that is coloured by polarity. A denominator may
// still carry `||1` where the quotient is a bar WIDTH or a sparkline's range —
// a scale is a drawing decision, not a claim — and nowhere else.
const uShare=(part,whole)=>whole?100*part/whole:null;

// Colour follows the entity, never its rank in the current view: a slot comes from
// the entity's spend rank across the WHOLE ledger, so filtering cannot repaint a
// series that already had a colour. Model colours live in their own map so a model
// keeps one identity whether the chart is showing authors or models.
//
// Past the 8 validated hues there is no stable map left to preserve — forty people
// cannot each keep a distinct colour. The earlier rule (sorted name, capped at 8)
// preserved the invariant by handing SEVEN of eight plotted authors the same red,
// which is the one failure a categorical palette cannot survive. So: whoever is in
// the global top 8 keeps their hue under every filter, and anyone else who reaches
// the chart takes a slot the current view leaves free. Survivors never repaint;
// newcomers gain a colour they did not have before.
//
// Models order by NAME, which is the rule render-report.py's _model_slots uses, so
// a model wears the same hue in the report and the panel. Authors order by spend,
// because there is no report chart to agree with and rank is the useful priority
// when only 8 of 40 can be coloured.
let USLOTS={}, MSLOTS={};
function uRanks(field,by){
 if(by==='name'){const o={};
  [...new Set(USAGE.facts.map(f=>f[field]))].sort().forEach((k,i)=>o[k]=i);
  return o;}
 const t={};
 for(const f of USAGE.facts)t[f[field]]=(t[f[field]]||0)+f[F.tokens];
 const o={};Object.keys(t).sort((a,b)=>t[b]-t[a]||(a<b?-1:1))
  .forEach((k,i)=>o[k]=i);return o;}
function uSlots(field,present,by){
 const rank=uRanks(field,by),used=new Set(),out={};
 const keys=[...new Set(present)].filter(k=>k&&k!=='other')
  .sort((a,b)=>(rank[a]==null?1e9:rank[a])-(rank[b]==null?1e9:rank[b]));
 for(const k of keys){const r=rank[k];
  if(r!=null&&r<8&&!used.has(r+1)){out[k]=r+1;used.add(r+1);}}
 let free=1;
 for(const k of keys){if(out[k])continue;
  while(free<=8&&used.has(free))free++;
  if(free<=8){out[k]=free;used.add(free);}}
 return out;}
function uCol(k){return USLOTS[k]?'var(--viz-'+USLOTS[k]+')':'var(--bar-neutral)';}
function uMCol(k){return MSLOTS[k]?'var(--viz-'+MSLOTS[k]+')':'var(--bar-neutral)';}

function setF(dim,val){
 UF[dim]=val||'';
 UORDER=UORDER.filter(d=>d!==dim);
 if(UF[dim])UORDER.push(dim);
 if(dim!=='day')SHOWN[dim]=TOP;      // a new scope starts from the top again
 renderUsage();}
function clearAll(){DIMS.forEach(d=>UF[d]='');UF.range='all';UORDER=[];
 DIMS.forEach(d=>{if(d in SHOWN)SHOWN[d]=TOP;});renderUsage();}

// Chart dimension is DERIVED: scoping to one author makes the interesting split
// their models. Nothing stores "which level am I on".
function chartDim(){return UF.author?'model':'author';}

// The text index behind the free-text box: everything about a row that a person
// could plausibly type, including the phase and task TITLES, which is what makes
// "checkout" find the work rather than only the id you would have to know already.
// Built once per fact and cached on the row, so the second keystroke rebuilds
// nothing across 20000 of them.
function uHay(f){
 if(f.h===undefined)f.h=[f[F.phase],f[F.task],f[F.model],f[F.author],f[F.agent],
   f[F.attr],(USAGE.phaseTitles||{})[f[F.phase]]||'',
   ((USAGE.taskMeta||{})[f[F.task]]||{}).title||''].join(' ').toLowerCase();
 return f.h;}

// Every filter EXCEPT the date window, in one place. uFiltered() applies it to the
// window on screen and uDelta() applies it to the window before, and a dimension
// that existed in only one of them would compare two different populations while
// the chip said "vs prior 30d". The delta used to re-list its dimensions inline,
// which is a copy that goes stale the moment a filter is added — as three were
// here.
function uMatch(f){
 return (!UF.model||f[F.model]===UF.model)
  &&(!UF.author||f[F.author]===UF.author)
  &&(!UF.phase||f[F.phase]===UF.phase)
  &&(!UF.task||f[F.task]===UF.task)
  &&(!UF.agent||f[F.agent]===UF.agent)
  &&(!UF.attr||f[F.attr]===UF.attr)
  &&(!UF.q||uHay(f).includes(UF.q.trim().toLowerCase()));}

function uFiltered(){if(!USAGE)return[];let out=USAGE.facts.filter(uMatch);
 if(UF.day){const[a,b]=UF.day.split('..');
  out=b?out.filter(f=>{const d=f[F.ts].slice(0,10);return d>=a&&d<=b;})
       :out.filter(f=>f[F.ts].slice(0,10)===a);}
 if(UF.range!=='all'){const d=new Date(Date.now()-parseInt(UF.range,10)*864e5)
   .toISOString().slice(0,10);out=out.filter(f=>f[F.ts].slice(0,10)>=d);}
 return out;}
const uAnyFilter=()=>UORDER.length>0||UF.range!=='all';

// Why the view is empty. "No rows match these filters" spread over eight controls
// is a puzzle, and one of the ways to empty this tab cannot be worked out from the
// screen at all: a range preset counts back from TODAY, so on a ledger whose last
// row is older than the window it selects nothing — which is the normal state of a
// FINISHED plan, and exactly when someone opens this tab to ask what it cost. That
// case is named outright, with both dates, because the reader's own conclusion
// would otherwise be that the metering never ran.
//
// The presets are deliberately NOT re-anchored on the data to make this go away: a
// control labelled "last 30 days" whose behaviour means "the last 30 days there
// happens to be data for" is a quieter defect than an empty result, and the label
// is what makes it one. (The report answers the neighbouring question differently
// and correctly — its presets measure back from the plan's own last day, and its
// labels say so.) An empty result that explains itself is the right answer here.
//
// Every count comes from uFiltered() with one slot temporarily blank — the same
// predicate the view itself runs. A second implementation of "what matches" is how
// an explanation ends up disagreeing with the thing it is explaining.
function uEmptyWhy(){
 const C=USAGE.counts||{};
 const toAll=()=>{UF.range='all';renderUsage();};
 if(UF.range!=='all'){
  const cut=new Date(Date.now()-parseInt(UF.range,10)*864e5)
    .toISOString().slice(0,10);
  if(C.to&&C.to<cut)return{why:'range-after-ledger',
   text:'The last '+UF.range+' days begin '+cut+', and the ledger ends '+C.to+
     ' — it stops before this window. Range presets count back from today, not '+
     'from the last day recorded.',
   fix:{key:'range',label:'Show all time',run:toAll}};}
 // Which single filter is doing it. Naming one and lifting one is the answer to a
 // question "clear filters" cannot answer: it throws away every filter that was
 // fine, so the reader learns nothing and has to rebuild the view to find out.
 for(const d of UORDER.concat(UF.range==='all'?[]:['range'])){
  const keep=UF[d];UF[d]=d==='range'?'all':'';
  const n=uFiltered().length;UF[d]=keep;
  if(!n)continue;
  return{why:d,
   text:'No rows match. It is the '+fName(d)+' filter ('+fVal(d)+') doing it: '+
     n+' row(s) match everything else.',
   fix:{key:d,label:d==='range'?'Show all time':'Remove the '+fName(d)+' filter',
     run:d==='range'?toAll:()=>setF(d,'')}};}
 return{why:'combination',
  text:'No rows match these filters, and no single one of them explains it — it '+
    'is the combination that selects nothing.'};}

// The from/to pair writes the SAME `UF.day` grammar the chart's click writes — one
// ISO day, or 'from..to' for a span — so a date typed here and a bin clicked there
// produce one filter, one chip and one way out. The pair also READS it, which is
// what keeps the two inputs showing the window a chart click just applied.
//
// Half a pair is completed from the LEDGER's own ends, never from today:
// "everything from 1 April" on a ledger that stopped in May means April to May, and
// completing it with the wall clock would silently widen the window past the data
// every day the project sits idle.
function uDayPair(){const[a,b]=(UF.day||'').split('..');return [a||'',b||a||''];}
function uSetDays(from,to){const C=USAGE.counts||{};
 const a=from||C.from||'',b=to||C.to||'';
 setF('day',(a||b)?(a===b?a:a+'..'+b):'');}

function uAgg(facts,key){const m=new Map();
 for(const f of facts){const k=f[F[key]]||'--';const s=m.get(k)||[0,0,0];
  s[0]+=f[F.tokens];s[1]+=f[F.cost];s[2]+=f[F.msgs];m.set(k,s);}
 return [...m.entries()].sort((a,b)=>b[1][0]-a[1][0]);}

// --- shared tooltip -------------------------------------------------------------
// One element, moved on hover. Compact by design: enough to stop you estimating
// against an axis, short enough to read without moving your eyes.
let TIP=null;
function tipEl(){if(!TIP){TIP=el('div',{class:'utip hidden'});document.body.append(TIP);}return TIP;}
function tipShow(ev,nodes){const t=tipEl();t.textContent='';
 (Array.isArray(nodes)?nodes:[nodes]).forEach(n=>t.append(n));
 t.classList.remove('hidden');tipMove(ev);}
function tipMove(ev){const t=tipEl(),pad=14,r=t.getBoundingClientRect();
 let x=ev.clientX+pad,y=ev.clientY+pad;
 if(x+r.width>innerWidth-8)x=ev.clientX-r.width-pad;
 if(y+r.height>innerHeight-8)y=ev.clientY-r.height-pad;
 t.style.left=Math.max(4,x)+'px';t.style.top=Math.max(4,y)+'px';}
function tipHide(){if(TIP)TIP.classList.add('hidden');}
function tipRow(colour,label,value){return el('div',{class:'utip-r'},
 colour?el('i',{style:'background:'+colour}):null,
 el('span',{class:'utip-k'},label),el('span',{class:'utip-v'},value));}
function bindTip(node,build){
 node.addEventListener('mouseenter',e=>tipShow(e,build()));
 node.addEventListener('mousemove',tipMove);
 node.addEventListener('mouseleave',tipHide);
 return node;}

// --- multi-line chart with crosshair --------------------------------------------
// Eight series over nine months of daily points is spaghetti: 250 marks across
// 680px is 2.7px per day, so what the eye gets is noise with a trend hidden in it.
// Past MAXPTS the days roll up into natural bins - week, four weeks, quarter -
// chosen as the smallest that fits, and the chart SAYS which one it used. Binning
// silently would be worse than the spaghetti: the reader would take a weekly total
// for a daily one.
const MAXPTS=60, LADDER=[1,7,28,91,364];
const BINNAME={1:'day',7:'week',28:'4 weeks',91:'quarter',364:'year'};
const dnum=d=>Date.UTC(+d.slice(0,4),+d.slice(5,7)-1,+d.slice(8,10))/864e5;
function uBin(days){
 if(days.length<2)return{size:1,bins:days.map(d=>[d,d])};
 const span=dnum(days[days.length-1])-dnum(days[0])+1;
 const size=LADDER.find(s=>Math.ceil(span/s)<=MAXPTS)||LADDER[LADDER.length-1];
 if(size===1)return{size:1,bins:days.map(d=>[d,d])};
 const start=dnum(days[0]),iso=n=>new Date(n*864e5).toISOString().slice(0,10);
 const bins=[];
 for(let a=0;a<span;a+=size)
  bins.push([iso(start+a),iso(start+Math.min(a+size,span)-1)]);
 return{size,bins};}
// Which bin a day falls in. Extracted because the sparklines bin the same days by
// the same ladder: two binary searches over one bin list is two chances for the
// chart and the tile above it to draw the same span at different resolutions.
function binAt(bins){return d=>{const n=dnum(d);let lo=0,hi=bins.length-1;
  while(lo<hi){const mid=(lo+hi+1)>>1;dnum(bins[mid][0])<=n?lo=mid:hi=mid-1;}
  return lo;};}

function uSeries(facts,dim){const per=new Map(),days=new Set();
 for(const f of facts){const d=f[F.ts].slice(0,10),k=f[F[dim]]||'--';
  days.add(d);const m=per.get(k)||new Map();
  m.set(d,(m.get(d)||0)+f[F.tokens]);per.set(k,m);}
 const ds=[...days].sort(),{size,bins}=uBin(ds);
 const at=binAt(bins);
 const idx=new Map(ds.map(d=>[d,at(d)]));
 const roll=m=>{const v=new Array(bins.length).fill(0);
  for(const[d,n]of m)v[idx.get(d)]+=n;return v;};
 let ent=[...per.entries()].map(([k,m])=>({key:k,
   total:[...m.values()].reduce((a,b)=>a+b,0),values:roll(m)}))
  .sort((a,b)=>b.total-a.total);
 if(ent.length>TOP){const tail=ent.slice(TOP);ent=ent.slice(0,TOP);
  ent.push({key:'other',total:tail.reduce((a,e)=>a+e.total,0),
    values:bins.map((_,i)=>tail.reduce((a,e)=>a+e.values[i],0))});}
 return {buckets:bins.map(b=>b[0]),bins:bins,binSize:size,entities:ent};}
// A bin is one filter value: an exact day, or "from..to" for a rolled-up range.
const binKey=b=>b[0]===b[1]?b[0]:b[0]+'..'+b[1];
const binLabel=b=>b[0]===b[1]?b[0]:b[0]+' to '+b[1];
const NS='http://www.w3.org/2000/svg';
const svgEl=(t,a)=>{const e=document.createElementNS(NS,t);
 for(const k in a)e.setAttribute(k,a[k]);return e;};
// W comes from measuring the container, and the viewBox is built at that exact
// pixel size, so the scale is 1:1 in both axes. It used to be a fixed 680 stretched
// to fit with preserveAspectRatio="none" - which scales the coordinate system
// non-uniformly and therefore scales the GLYPHS: at 942px the axis labels rendered
// 38% too wide, the 2px lines drew 2.8px on vertical runs and 2px on horizontal
// ones, and the end-of-series circles were ellipses. Rendering 1:1 fixes all four
// at once, which no amount of tuning inside a stretched space can.
function uChart(sr,dim,W){
 const H=190,PL=44,PB=20,PT=10;
 if(!sr.buckets.length)return el('div',{class:'mut'},'No data in this window.');
 const peak=Math.max(1,...sr.entities.flatMap(e=>e.values));
 const n=sr.buckets.length, iw=W-PL-6, ih=H-PB-PT;
 const X=i=>PL+(n<2?iw/2:iw*i/(n-1)), Y=v=>PT+ih-ih*v/peak;
 const svg=svgEl('svg',{class:'uchart',viewBox:'0 0 '+W+' '+H,role:'img',
   'aria-label':'Tokens per '+(sr.binSize===1?'day':BINNAME[sr.binSize])
     +', peak '+uTok(peak)+'. Click to filter to one.'});
 [0,0.5,1].forEach(fr=>{const y=PT+ih*fr;
  svg.appendChild(svgEl('line',{class:'g',x1:PL,y1:y,x2:W,y2:y}));
  const t=svgEl('text',{class:'ax',x:0,y:y+3});t.textContent=uTok(peak*(1-fr));
  svg.appendChild(t);});
 const cross=svgEl('line',{class:'cross hidden',y1:PT,y2:PT+ih});
 svg.appendChild(cross);
 sr.entities.forEach(e=>{
  const d=e.values.map((v,i)=>(i?'L':'M')+X(i).toFixed(1)+' '+Y(v).toFixed(1)).join('');
  svg.appendChild(svgEl('path',{class:'ln',d:d,stroke:uCol(e.key)}));
  // A 2px line is a poor click target, and clicking a LINE (that series) has to stay
  // distinct from clicking the plot (that day). A wider transparent companion path
  // gives the series a comfortable hit area; the click stops there so it never also
  // registers as a day selection.
  if(e.key!=='other'){
   const hit=svgEl('path',{class:'lnhit',d:d});
   hit.addEventListener('click',ev=>{ev.stopPropagation();
     setF(dim,UF[dim]===e.key?'':e.key);});
   const ttl=svgEl('title',{});ttl.textContent='Click to scope to '+e.key;
   hit.appendChild(ttl);
   svg.appendChild(hit);}
  const li=e.values.length-1;
  svg.appendChild(svgEl('circle',{class:'dot',cx:X(li),cy:Y(e.values[li]),r:3.5,
    fill:uCol(e.key)}));});
 [0,n-1].forEach(i=>{if(n<2&&i)return;const t=svgEl('text',{class:'ax',x:X(i),y:H-4,
   'text-anchor':i?'end':'start'});t.textContent=sr.buckets[i].slice(5);
  svg.appendChild(t);});
 // Crosshair: nearest bucket to the cursor, one tooltip row per series.
 const idxAt=ev=>{const r=svg.getBoundingClientRect();
  const rel=(ev.clientX-r.left)/r.width*W;
  return Math.max(0,Math.min(n-1,Math.round((rel-PL)/(n<2?1:iw/(n-1)))));};
 svg.addEventListener('mousemove',ev=>{const i=idxAt(ev);
  cross.setAttribute('x1',X(i));cross.setAttribute('x2',X(i));
  cross.classList.remove('hidden');
  const rows=[el('div',{class:'utip-h'},binLabel(sr.bins[i]))];
  sr.entities.filter(e=>e.values[i]).sort((a,b)=>b.values[i]-a.values[i])
   .forEach(e=>rows.push(tipRow(uCol(e.key),e.key,uTok(e.values[i]))));
  if(rows.length===1)rows.push(el('div',{class:'utip-r mut'},'no usage'));
  rows.push(el('div',{class:'utip-f'},'click to filter to this '
    +(sr.binSize===1?'day':BINNAME[sr.binSize])));
  tipShow(ev,rows);});
 svg.addEventListener('mouseleave',()=>{cross.classList.add('hidden');tipHide();});
 svg.addEventListener('click',ev=>setF('day',binKey(sr.bins[idxAt(ev)])));
 svg.classList.add('pick');
 return svg;}

// The chart is built at the container's true pixel width, and the container is not
// in the DOM while renderUsage() is assembling the card - so the first measurement
// can be 0. Draw once, measure again on the next frame, and re-draw on resize. The
// width guard makes every one of those a no-op unless the width actually moved.
function mountChart(sr,dim){
 const host=el('div',{class:'chartslot'});
 const draw=()=>{const w=Math.round(host.clientWidth);
  if(!w||w===host.__w)return;
  host.__w=w;host.replaceChildren(uChart(sr,dim,w));};
 requestAnimationFrame(()=>{draw();
  if(window.ResizeObserver&&!host.__ro){
   host.__ro=new ResizeObserver(()=>draw());host.__ro.observe(host);}});
 return host;}

// --- sparklines ------------------------------------------------------------------
// A KPI tile is one number, and one number cannot say whether it is the top of a
// climb or the bottom of one. The spark is that shape and nothing else: no axis, no
// labels, no interaction — everything needed to read it precisely is in the chart
// directly below, and a tile that tried to be a chart would be a worse one.
//
// Drawn at its intrinsic pixel size, NOT stretched to the tile, for the reason the
// main chart is drawn 1:1: a viewBox scaled non-uniformly scales the strokes with
// it, and at this size a 1.4px line becoming 2px on the verticals is the whole
// drawing. It bins by the same ladder the chart uses (via uBin/binAt), so the tile
// and the chart under it can never be showing two different resolutions, and the
// period it settled on is named in the tile's own tooltip rather than left implied.
const SPW=76,SPH=20;
function uDaily(facts){
 const per=new Map();
 for(const f of facts){const d=f[F.ts].slice(0,10);
  const s=per.get(d)||[0,0,0,0];      // tokens, cost, msgs, unattributed tokens
  s[0]+=f[F.tokens];s[1]+=f[F.cost];s[2]+=f[F.msgs];
  if(f[F.attr]==='unattributed')s[3]+=f[F.tokens];
  per.set(d,s);}
 const ds=[...per.keys()].sort();
 if(!ds.length)return{period:'day',series:{}};
 const{size,bins}=uBin(ds),at=binAt(bins);
 const acc=bins.map(()=>[0,0,0,0]);
 for(const[d,s]of per){const i=at(d);for(let k=0;k<4;k++)acc[i][k]+=s[k];}
 return{period:size===1?'day':BINNAME[size],
   series:{tokens:acc.map(v=>v[0]),cost:acc.map(v=>v[1]),msgs:acc.map(v=>v[2]),
     // A bucket with no tokens has no coverage to report; carrying 0% would draw a
     // cliff to the floor on a quiet day and call it a collapse in attribution.
     attributed:acc.map(v=>v[0]?100*(v[0]-v[3])/v[0]:null)}};}

// `zero` is not decoration, it is the claim the drawing makes. A magnitude is
// measured from nothing, so its baseline is 0 and the area under it means the
// quantity. A SHARE is not: attribution moving 96% -> 99% against a 0..100 axis is
// three pixels of a solid block, which is a sparkline that says nothing while
// looking like it says something. A share is therefore scaled to its own range and
// drawn as a line alone — no area, because there is no zero for the area to be
// measured from, and a filled shape would invite exactly that reading.
function uSpark(vals,label,zero){
 // Two points make a line; one makes a claim about a trend from a single sample.
 // Nulls are gaps (a bucket with no tokens has no share to report) and are dropped
 // rather than plotted as zero, which would draw a cliff on a quiet day.
 const v=(vals||[]).filter(x=>x!=null);
 if(v.length<2)return null;
 const hi=Math.max(...v),lo=zero?Math.min(0,Math.min(...v)):Math.min(...v);
 const rng=(hi-lo)||1;
 const X=i=>SPW*i/(v.length-1),Y=x=>1.5+(SPH-3)*(1-(x-lo)/rng);
 const d=v.map((x,i)=>(i?'L':'M')+X(i).toFixed(1)+' '+Y(x).toFixed(1)).join('');
 const svg=svgEl('svg',{class:'uspark',width:SPW,height:SPH,
   viewBox:'0 0 '+SPW+' '+SPH,role:'img','aria-label':label});
 if(zero)svg.appendChild(svgEl('path',{class:'sa',
   d:d+'L'+SPW.toFixed(1)+' '+SPH+'L0 '+SPH+'Z'}));
 svg.appendChild(svgEl('path',{class:'sl',d:d}));
 svg.appendChild(svgEl('circle',{class:'sd',cx:SPW,cy:Y(v[v.length-1]).toFixed(1),
   r:1.7}));
 return svg;}

// --- metrics, all recomputed under the current filter --------------------------
function uCoverage(facts){const by={},tot=facts.reduce((a,f)=>a+f[F.tokens],0);
 for(const f of facts)by[f[F.attr]]=(by[f[F.attr]]||0)+f[F.tokens];
 const un=by['unattributed']||0;
 return {attributed:uShare(tot-un,tot),task:uShare(by['task']||0,tot),by,tot};}
function uUnit(facts){const M=USAGE.taskMeta||{},cost={};
 for(const f of facts){const t=f[F.task];if(t&&t!=='--')cost[t]=(cost[t]||0)+f[F.cost];}
 const done=Object.keys(cost).filter(t=>(M[t]||{}).status==='done').map(t=>cost[t]);
 const remaining=Object.keys(M).filter(t=>['pending','in_progress','blocked']
   .includes((M[t]||{}).status)).length;
 const out={completed:done.length,remaining,gate:5,perTask:null,proj:null};
 if(done.length)out.perTask=done.reduce((a,b)=>a+b,0)/done.length;
 // Same gate as the report: a forecast off fewer than 5 samples is noise, so it is
 // suppressed rather than shown with false confidence.
 if(done.length>=5){const s=[...done].sort((a,b)=>a-b),q=p=>s[Math.max(0,
   Math.min(s.length-1,Math.round(p*(s.length-1))))];
  out.proj={low:q(.25)*remaining,high:q(.75)*remaining};}
 return out;}
function uRetry(facts){const M=USAGE.taskMeta||{};let tot=0,re=0,bl=0;
 const rs=new Set(),bs=new Set();
 for(const f of facts){tot+=f[F.cost];const t=M[f[F.task]];if(!t)continue;
  if((t.attempts||1)>1){re+=f[F.cost];rs.add(f[F.task]);}
  if(t.status==='blocked'){bl+=f[F.cost];bs.add(f[F.task]);}}
 return {tot,re,bl,rn:rs.size,bn:bs.size,
   overlap:[...rs].filter(x=>bs.has(x)).length};}
function uRouting(facts){const M=USAGE.taskMeta||{},acc={};
 for(const f of facts){const t=M[f[F.task]];if(!t)continue;
  const risk=t.risk||'unrated',model=f[F.model];
  acc[risk]=acc[risk]||{};
  const c=acc[risk][model]=acc[risk][model]||{cost:0,tasks:new Set(),att:[]};
  c.cost+=f[F.cost];
  if(!c.tasks.has(f[F.task])){c.tasks.add(f[F.task]);c.att.push(t.attempts||1);}}
 const rows=[];
 for(const risk in acc)for(const model in acc[risk]){const c=acc[risk][model];
  rows.push({risk,model,tasks:c.tasks.size,perTask:c.cost/c.tasks.size,
    att:c.att.reduce((a,b)=>a+b,0)/c.att.length});}
 rows.sort((a,b)=>RISKS.indexOf(a.risk)-RISKS.indexOf(b.risk)||
   a.model.localeCompare(b.model));
 return rows;}
// vs the window immediately before this one, same length. Null when there is no
// prior period -- a first-run dashboard must not invent a trend.
//
// "All time" has no window, so it gets one: the last 30 days of the LEDGER against
// the 30 before them, anchored on the last day that has data rather than on the
// wall clock. Anchoring on today would make the default view of a ledger that
// stopped two months ago compare an empty window with an empty window and show no
// trend at all, forever — which is exactly the state a project is in when someone
// opens the panel to ask what it cost.
//
// Both date ranges travel with the number in `basis`, because "+18%" against an
// unnamed period is not a measurement.
function uDelta(facts,days){
 if(!days.length)return null;
 const all=UF.range==='all',span=all?30:parseInt(UF.range,10);
 const iso=n=>new Date(n*864e5).toISOString().slice(0,10);
 const anchor=all?days[days.length-1]:iso(Math.floor(Date.now()/864e5));
 // One boundary convention: the window is [cut, anchor], the one before it is
 // [prevCut, cut). Under a range preset `cut` is the same cut uFiltered() applies,
 // so the "now" side is exactly the rows the tiles are counting and `facts` can be
 // used as-is; under "all time" `facts` is the whole ledger and has to be sliced.
 const cut=iso(dnum(anchor)-span+(all?1:0)),prevCut=iso(dnum(cut)-span);
 const day=f=>f[F.ts].slice(0,10);
 const now=all?facts.filter(f=>day(f)>=cut):facts;
 const base=USAGE.facts.filter(f=>{const d=day(f);
  return d>=prevCut&&d<cut&&uMatch(f);});
 if(!base.length||!now.length)return null;
 const sum=a=>{let t=0,c=0,m=0,un=0;
  for(const f of a){t+=f[F.tokens];c+=f[F.cost];m+=f[F.msgs];
   if(f[F.attr]==='unattributed')un+=f[F.tokens];}
  return{tokens:t,cost:c,msgs:m,attributed:t?100*(t-un)/t:null};};
 const A=sum(now),B=sum(base);
 const pc=(x,y)=>y?100*(x-y)/y:null;
 return {tokens:pc(A.tokens,B.tokens),cost:pc(A.cost,B.cost),
         msgs:pc(A.msgs,B.msgs),
         // A share compared with a share is a difference in POINTS. 90% to 95% is
         // five points, and calling it +5.6% would be a third number nobody asked
         // for and the one a reader would misread as the coverage itself.
         attributed:(A.attributed==null||B.attributed==null)
           ?null:A.attributed-B.attributed,
         label:'vs prior '+span+'d',
         basis:(all?'the ledger’s last '+span+' days':'the last '+span+' days')
           +' ('+cut+' to '+anchor+') against '+prevCut+' to '+iso(dnum(cut)-1)};}

// --- CSV export ------------------------------------------------------------------
// The rows behind the view, as a file, because the questions a spreadsheet is for
// are not the questions a dashboard is for. Numbers go out RAW — no thousands
// separators, no currency symbol, no locale — since the receiver parses them:
// '3,230,000' lands in Excel as text and every sum over the column is then wrong
// and silently so. (The panel's own selftest scans for toLocaleString on the screen
// side for the same reason, one surface up.)
function uCsvText(facts){
 const head=['ts','phase','task','model','author','agent','attr','tokens',
   'costUSD','msgs'];
 // RFC 4180: quote anything containing a comma, a quote or a newline, and double
 // the quotes inside. A task title with a comma in it is not exotic.
 const q=v=>{const s=v==null?'':String(v);
  return /[",\r\n]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s;};
 const out=[head.join(',')];
 for(const f of facts)out.push([f[F.ts],f[F.phase],f[F.task],f[F.model],
   f[F.author],f[F.agent],f[F.attr],f[F.tokens],f[F.cost].toFixed(6),f[F.msgs]]
  .map(q).join(','));
 return out.join('\r\n')+'\r\n';}
function uExport(facts){
 if(!facts.length){toast('nothing to export — no rows match these filters','err');
  return;}
 // The name says what the file IS. These are aggregated buckets, not raw ledger
 // lines, and at 20000 rows the server rolls them from hourly to daily — a file
 // called usage.csv on someone's disk three weeks later cannot be trusted to be
 // either. Span, resolution and whether a filter was applied all go in the name.
 const C=USAGE.counts||{};
 const name='usage-'+(C.from||'start')+'_'+(C.to||'end')+'-'
   +(USAGE.rolled?'daily':'hourly')+(uAnyFilter()?'-filtered':'')+'.csv';
 try{
  // U+FEFF: without a byte-order mark Excel reads a UTF-8 CSV in the local 8-bit
  // codepage and turns every non-ASCII author name into mojibake on open. Written
  // as an escape, never as the character itself — an invisible literal in the
  // source is unreviewable and ungreppable.
  const url=URL.createObjectURL(new Blob(['\ufeff'+uCsvText(facts)],
    {type:'text/csv;charset=utf-8'}));
  const a=el('a',{href:url,download:name});
  document.body.append(a);a.click();a.remove();
  // Revoked late, not immediately: some browsers have not started reading the blob
  // by the time click() returns, and a revoked URL there is a download that fails
  // with no error anywhere.
  setTimeout(()=>URL.revokeObjectURL(url),4000);
  toast(facts.length+' row(s) exported to '+name);
 }catch(e){toast('export failed: '+e,'err');}}

// --- render --------------------------------------------------------------------
function uBars(facts,dim,title){
 const g=uAgg(facts,dim);if(!g.length)return[];
 const grand=g.reduce((a,x)=>a+x[1][0],0);
 const limit=SHOWN[dim]||TOP;
 const head=g.slice(0,limit),tail=g.slice(limit);
 const peak=Math.max(...head.map(x=>x[1][0]))||1;
 const out=[el('h2',{},title)];
 for(const[k,v]of head){
  const meta=USAGE.taskMeta[k]||{};
  const nm=dim==='phase'
    ?(k==='--'?'-- unattributed':(k+' '+(USAGE.phaseTitles[k]||'')).trim())
    :(dim==='task'&&meta.title?(k+' '+meta.title):k);
  const active=UF[dim]===k;
  const row=el('div',{class:'urow pick'+(active?' on':''),
    onclick:()=>setF(dim,active?'':k)},
   el('span',{class:'unm'},nm),
   // Floor the width: a row that spent 0.08% of the peak rounds to 0.0% and
   // paints an empty track, which reads as "no data" rather than "a little".
   el('span',{class:'bar'},el('i',{style:'width:'+
     Math.max(v[0]?0.8:0,100*v[0]/peak).toFixed(1)+'%;'+
     'background:'+(dim==='model'?uMCol(k):'var(--bar-neutral)')})),
   el('span',{class:'uamt'},uTok(v[0])+(USAGE.showCost?' - '+uCost(v[1]):'')));
  bindTip(row,()=>[el('div',{class:'utip-h'},nm),
    tipRow(dim==='model'?uMCol(k):null,'tokens',uTok(v[0],2)),
    tipRow(null,'share',uPct(uShare(v[0],grand))),
    USAGE.showCost?tipRow(null,'cost',uCost(v[1])):null,
    tipRow(null,'messages',v[2].toLocaleString()),
    el('div',{class:'utip-f'},active?'click to clear this filter':'click to filter')
   ].filter(Boolean));
  out.push(row);}
 if(tail.length){
  const more=tail.reduce((a,x)=>[a[0]+x[1][0],a[1]+x[1][1]],[0,0]);
  out.push(el('div',{class:'urow pick tail',
    onclick:()=>{SHOWN[dim]=limit+TOP;renderUsage();}},
   el('span',{class:'unm mut'},'other ('+tail.length+') - show '+
     Math.min(TOP,tail.length)+' more'),
   el('span',{class:'bar'},el('i',{style:'width:'+(100*more[0]/peak).toFixed(1)+
     '%;background:var(--bar-neutral);opacity:.45'})),
   el('span',{class:'uamt'},uTok(more[0])+(USAGE.showCost?' - '+uCost(more[1]):''))));}
 // Expanding costs one click, so collapsing must too. This used to be an `else if`
 // on the tail being empty, which meant the way back only appeared after paging
 // through the whole list - thirty clicks at 233 rows. And paging is the wrong tool
 // for finding one row among hundreds, which is what `browse all` is for.
 const ctl=[];
 if(limit>TOP)ctl.push(el('button',{class:'lnk',
   onclick:()=>{SHOWN[dim]=TOP;renderUsage();}},'show top '+TOP+' only'));
 if(g.length>TOP)ctl.push(el('button',{class:'lnk',
   onclick:()=>openBrowse(dim,title,facts)},'browse all '+g.length+' →'));
 if(ctl.length){
  const bar=el('div',{class:'uctl'});
  ctl.forEach((b,i)=>{if(i)bar.append(el('span',{class:'mut'},'·'));bar.append(b);});
  out.push(bar);}
 return out;}

// --- phase budgets ---------------------------------------------------------------
// Spend against the PLAN rather than the calendar. Rendered only when some phase
// declares a budgetUSD, so it costs nothing in the common case where nobody has.
//
// Unlike the bands, this DOES follow the filter: "what has P1 cost me" is a
// question about the rows you are looking at, and a budget row that ignored an
// author filter while the bar above it obeyed one would be two truths on one
// screen. The caption says which rows it counted.
function uBudgets(facts){
 const B=USAGE.phaseBudgets||{};
 const ids=Object.keys(B);
 if(!ids.length)return [];
 const spent={};
 for(const f of facts){const p=f[F.phase]||'--';
  spent[p]=(spent[p]||0)+f[F.cost];}
 const rows=ids.map(id=>{const used=spent[id]||0,budget=B[id];
   return {id,budget,used,pct:100*used/budget,over:used>budget};})
  .sort((a,b)=>b.pct-a.pct);
 const out=[el('h2',{},'Budget')];
 if(UORDER.length)out.push(el('div',{class:'ucrumb mut'},
   'Counting only the rows the filters above leave in view.'));
 for(const r of rows){
  const nm=(r.id+' '+(USAGE.phaseTitles[r.id]||'')).trim();
  out.push(el('div',{class:'bud'+(r.over?' over':'')},
   el('span',{class:'unm'},nm),
   // The fill stops at the track; the number beside it does not, so an overrun
   // is legible instead of being a bar that looks merely full.
   el('span',{class:'bar'},el('i',{style:'width:'+Math.min(100,r.pct).toFixed(1)+'%'})),
   el('span',{class:'bpct'},r.pct.toFixed(0)+'%'),
   el('span',{class:'uamt'},uCost(r.used)+' of '+uCost(r.budget)
     +(r.over?' · over':''))));}
 const tb=rows.reduce((a,r)=>a+r.budget,0),ts=rows.reduce((a,r)=>a+r.used,0);
 out.push(el('div',{class:'bud total'},
   el('span',{class:'unm mut'},'All budgeted phases'),
   el('span',{class:'bar'}),el('span',{class:'bpct'}),
   el('span',{class:'uamt'},uCost(ts)+' of '+uCost(tb))));
 const missing=Object.keys(USAGE.phaseTitles||{}).filter(p=>!(p in B)).length;
 if(missing)out.push(el('div',{class:'mut small'},
   missing+' phase(s) have no budgetUSD set and are not listed - they are not '
   +'phases at zero.'));
 return out;}

// --- cost bands ------------------------------------------------------------------
// Mirrors cost_bands() in usage_ledger.py; the two must agree or the panel and the
// report will put the same task in different bands. Same gate, same thresholds,
// same fallback when the configured pair is malformed.
//
// Computed from the WHOLE ledger, never from the filtered view: a task is an
// outlier relative to the project, not relative to whatever slice you are looking
// at. Recalibrating per filter would make one of any three tasks an "outlier".
const BAND_GATE=5, BAND_ORDER=['typical','high','outlier'];
let BANDS=null;
function uBandInfo(){
 if(BANDS)return BANDS;
 const cfg=USAGE.bands||{},M=USAGE.taskMeta||{},cost={};
 for(const f of USAGE.facts){const t=f[F.task];
  if(t&&t!=='--'&&M[t])cost[t]=(cost[t]||0)+f[F.cost];}
 let hi=Number(cfg.highUSD),ou=Number(cfg.outlierUSD),basis='absolute',sample=0;
 if(!(isFinite(hi)&&isFinite(ou)&&hi>0&&hi<=ou)){
  const done=Object.keys(cost).filter(t=>(M[t]||{}).status==='done')
    .map(t=>cost[t]).sort((a,b)=>a-b);
  sample=done.length;
  if(done.length<BAND_GATE)
   return (BANDS={basis:null,sufficient:false,byTask:{},sample,gate:BAND_GATE});
  const pct=p=>done[Math.max(0,Math.min(done.length-1,
    Math.round(p/100*(done.length-1))))];
  hi=pct(50);ou=pct(90);basis='relative';}
 const byTask={},counts={typical:0,high:0,outlier:0};
 for(const t in cost){const b=cost[t]>ou?'outlier':cost[t]>hi?'high':'typical';
  byTask[t]=b;counts[b]++;}
 return (BANDS={basis,sufficient:true,high:hi,outlier:ou,byTask,counts,sample,
   gate:BAND_GATE});}
function bandOf(id){const b=uBandInfo();
 return b.sufficient?(b.byTask[id]||null):null;}

// --- browse dialog ---------------------------------------------------------------
// The ranked list is a summary: the top 8 by spend. Paging it eight at a time to
// reach P219 among 241 is 27 clicks and still gives you no way to re-rank by cost.
// This is the other half - search and sort over the whole dimension - and it reads
// from the SAME filtered facts the bars do, so it can never disagree with the page
// behind it. A native <dialog> brings the focus trap, the backdrop and Esc for free.
let BROWSE=null;
// `models` is omitted for the model dimension, where it would restate the row.
const BCOL={
 phase:[['id','id'],['title','title'],['models','models'],['tokens','tokens'],
        ['share','share'],['cost','cost'],['messages','msgs']],
 // `cost` band only on tasks: the band is defined per task, and calling a phase
 // an outlier would be a different claim from the one that was computed.
 task:[['id','id'],['title','title'],['status','status'],['risk','risk'],
       ['models','models'],['cost band','band'],['tokens','tokens'],
       ['share','share'],['cost','cost'],['messages','msgs']],
 model:[['model','id'],['tokens','tokens'],['share','share'],['cost','cost'],
        ['messages','msgs']],
 author:[['author','id'],['models','models'],['tokens','tokens'],['share','share'],
         ['cost','cost'],['messages','msgs']]};
const BNUM={tokens:1,share:1,cost:1,msgs:1};

function browseRows(dim,facts){
 const g=uAgg(facts,dim),grand=g.reduce((a,x)=>a+x[1][0],0);
 // Which models did this phase/task/person actually use? The aggregate throws
 // that away, and it is the question the ranked bar cannot answer: two phases
 // costing the same can be one opus run and one long haiku grind.
 const mix={};
 for(const f of facts){const k=f[F[dim]]||'--',m=f[F.model]||'unknown';
  (mix[k]=mix[k]||{})[m]=(mix[k][m]||0)+f[F.tokens];}
 return g.map(([k,v])=>{const meta=(USAGE.taskMeta||{})[k]||{};
  // Slot order, not token order: the palette was validated on THAT adjacency, so
  // drawing segments in any other sequence puts unvalidated pairs side by side.
  const per=mix[k]||{};
  const models=Object.keys(per).sort((a,b)=>(MSLOTS[a]||99)-(MSLOTS[b]||99))
    .map(m=>({model:m,tokens:per[m],pct:uShare(per[m],v[0])}));
  const top=[...models].sort((a,b)=>b.tokens-a.tokens)[0];
  return {id:k,
    title:dim==='phase'?(k==='--'?'unattributed':(USAGE.phaseTitles[k]||''))
      :dim==='task'?(k==='--'?'unattributed':(meta.title||'')):'',
    status:meta.status||'',risk:meta.risk||'',
    band:(dim==='task'?bandOf(k):null)||'',
    models:models,dominant:top?top.model:'',
    tokens:v[0],share:uShare(v[0],grand),cost:v[1],msgs:v[2]};});}

// A mini stack plus the dominant model NAMED. Identity is never colour alone, and
// at this size the segments are far too small to carry inline labels.
function modelCell(r){
 if(!r.models.length)return el('span',{class:'mut'},'—');
 const bar=el('span',{class:'mstack'});
 r.models.forEach(m=>bar.append(el('i',{style:'flex:'+Math.max(1,m.tokens)+' 0 0;'
   +'background:'+uMCol(m.model)})));
 const cell=el('span',{class:'mcell'},bar,
   el('span',{class:'mdom'},r.dominant.replace(/^claude-/,'')));
 cell.title=r.models.map(m=>m.model+'  '+uPct(m.pct)+'  '+uTok(m.tokens,2))
   .join('\n');
 return cell;}

function openBrowse(dim,title,facts){
 if(!BROWSE){BROWSE=el('dialog',{class:'browse'});
  // Clicking the backdrop is the same intent as Esc. The dialog element itself
  // fills the viewport, so a click whose target IS the dialog landed outside the
  // panel it contains.
  BROWSE.addEventListener('click',ev=>{if(ev.target===BROWSE)BROWSE.close();});
  document.body.append(BROWSE);}
 const rows=browseRows(dim,facts),cols=BCOL[dim]||BCOL.model;
 let sort='tokens',desc=true,q='';
 const head=el('div',{class:'bhead'},
   el('h3',{},title+' — '+rows.length),
   el('button',{class:'bx',title:'close','aria-label':'close',
     onclick:()=>BROWSE.close()},'✕'));
 // "All phases" would be a lie while the page is scoped to one author.
 const within=UORDER.length
   ? el('div',{class:'mut small'},'within: '+UORDER.map(d=>fName(d)+' '+fVal(d))
       .join(' · '))
   : null;
 // State the thresholds, or state why there are none. Either way the reader can
 // check the classification rather than take it on faith.
 const bi=dim==='task'?uBandInfo():null;
 const bandNote=!bi?null:el('div',{class:'mut small'},bi.sufficient
   ? 'cost band: '+(bi.basis==='absolute'
       ? 'configured thresholds'
       : 'this project’s own completed tasks, median/p90')
     +' — typical ≤ '+uCost(bi.high)+' · high ≤ '+uCost(bi.outlier)
     +' · outlier above'
   : ['cost band: not shown — needs '+bi.gate+' completed tasks to calibrate, '
      +'there are '+bi.sample+'. ',
      settingsLink('Set absolute thresholds instead','usage.bands'),
      ' to band by a budget rather than by this project’s own history.']);
 const search=el('input',{type:'search',placeholder:'search '+dim+'…'});
 // An <input type=search> eats the FIRST Escape to clear itself, so the dialog
 // only closed on the second press - which reads as the key being broken. One
 // Escape, one effect: close.
 search.addEventListener('keydown',ev=>{
   if(ev.key==='Escape'){ev.preventDefault();BROWSE.close();}});
 const count=el('span',{class:'count'});
 const tb=el('tbody');
 const thead=el('thead');

 const draw=()=>{
  const needle=q.trim().toLowerCase();
  const shown=rows.filter(r=>!needle
    ||(r.id+' '+r.title).toLowerCase().includes(needle));
  // A mix has no natural order, so the models column sorts by its dominant model.
  shown.sort((a,b)=>{const k=sort==='models'?'dominant':sort;
    const A=a[k],B=b[k];
    const c=BNUM[sort]?A-B:String(A).localeCompare(String(B));
    return desc?-c:c;});
  count.textContent=shown.length+' of '+rows.length;
  thead.replaceChildren(el('tr',{},...cols.map(([lbl,key])=>
    el('th',{class:(BNUM[key]?'n ':'')+'pick'+(sort===key?' on':''),
      onclick:()=>{if(sort===key)desc=!desc;else{sort=key;desc=!!BNUM[key];}draw();}},
     lbl,sort===key?el('span',{class:'sarrow'},desc?'▼':'▲'):null))));
  tb.replaceChildren(...shown.map(r=>{
   const active=UF[dim]===r.id;
   return el('tr',{class:'pick'+(active?' on':''),
     title:active?'click to clear this filter':'click to filter to this '+dim,
     onclick:()=>{setF(dim,active?'':r.id);BROWSE.close();}},
    ...cols.map(([,key])=>el('td',
      {class:BNUM[key]?'n':(key==='title'?'t':''),
       title:key==='title'?String(r.title||''):null},
      key==='models'?modelCell(r)
      // A dot alone would be status-colour-as-meaning; the word carries it.
      :key==='band'?(r.band?el('span',{class:'bandpill b-'+r.band},r.band)
                           :el('span',{class:'mut'},'—'))
      :key==='tokens'?uTok(r.tokens,2)
      // NOT uPct here: across 241 phases every share is under 1%, and a column
      // where every cell reads "<1%" sorts fine and tells you nothing. This is
      // the precision surface, so it gets the digits.
      :key==='share'?(r.share==null?'—'
        :(r.share<1?r.share.toFixed(2):r.share.toFixed(1))+'%')
      :key==='cost'?uCost(r.cost)
      :key==='msgs'?r.msgs.toLocaleString()
      :String(r[key]||'—'))));}));
  if(!shown.length)tb.replaceChildren(el('tr',{},
    el('td',{colspan:String(cols.length),class:'mut'},
      'Nothing matches "'+q.trim()+'".')));};

 search.addEventListener('input',()=>{q=search.value;draw();});
 draw();
 // replaceChildren is the native DOM API, not el(): it STRINGIFIES anything that
 // is not a Node, so passing the null `within` painted the literal text "null"
 // above the dialog. Filter before handing it over.
 BROWSE.replaceChildren(...[head,within,bandNote,
   el('div',{class:'comptools'},search,count),
   el('div',{class:'btblwrap'},el('table',{class:'btbl'},thead,tb)),
   el('div',{class:'mut small bfoot'},
     'click a header to sort · click a row to filter')].filter(Boolean));
 BROWSE.showModal();
 search.focus();}

function renderUsage(){const c=$('#usage');
 // Every filter change repaints this whole tab — and a filter change is exactly
 // what typing in the search box IS. Without this, the third letter of a five
 // letter search goes into a box that no longer exists, and the caret with it.
 const act=document.activeElement,keepQ=!!(act&&act.id==='uq'),
   caret=keepQ?act.selectionStart:0;
 c.textContent='';tipHide();
 const card=el('div',{class:'card'});
 const done=()=>{c.append(card);
  if(keepQ){const n=$('#uq');if(n){n.focus();try{n.setSelectionRange(caret,caret);}catch(e){}}}};
 if(!USAGE||!USAGE.facts.length){
  card.append(USAGE&&!USAGE.enabled
   ?el('div',{class:'mut'},'Token metering is off — ',
     settingsLink('turn it back on in Settings','usage.enabled'),'.')
   :el('div',{class:'mut'},'No usage recorded yet. Metering runs on the '
     +'Stop/SubagentStop hooks; "/audit:usage --backfill" reads transcripts already '
     +'on disk.'),
   el('div',{class:'mut',style:'margin-top:var(--sp-0)'},
     'ledger: '+((USAGE||{}).ledgerDir||'-'),' · ',
     settingsLink('change where it is written','usage.ledgerDir')));
  done();return;}

 // context line: the shape of the ledger, at zero card weight
 const K=USAGE.counts||{};
 const bits=[K.phases+' phases',K.authors+' people',K.models+' models',
   K.sessions+' sessions'];
 if(K.from)bits.push(K.from+' to '+K.to);
 // What the FACTS are bucketed at, which is not what the chart draws at — the
 // chart names its own period in its heading, so this says "ledger" out loud
 // rather than leaving two different resolutions on screen unlabelled.
 bits.push(USAGE.rolled?'daily ledger (rolled up)':'hourly ledger');
 // The rate table behind every dollar in this tab. `pricingAsOf` is served from the
 // MERGED config, so it is set even when this project never chose it — printing it
 // unconditionally would present the default table's date as the project's own.
 // `pricingAsOfDeclared` is the server saying which of the two it is.
 if(USAGE.showCost&&USAGE.pricingAsOfDeclared)bits.push('rates as of '+USAGE.pricingAsOf);
 const ctx=el('div',{class:'uctx'},bits.join(' - '));
 // This used to end the sentence with "set usage.pricingAsOf" — an instruction to
 // go and edit a file, printed on the surface built to edit that file. Now it is
 // the way there.
 if(USAGE.showCost&&!USAGE.pricingAsOfDeclared)ctx.append(' - ',
   settingsLink('rates undated: date them in Settings','usage.pricingAsOf'));
 card.append(ctx);

 // filters, on two rows: WHO and WHAT above, WHEN and the way out below.
 // Typeahead for the dimensions with hundreds of values, a plain select for the
 // two that have three — a select states its whole domain at a glance, which a
 // typeahead hides behind a keystroke, and hiding a two-value domain is silly.
 const uniq=dim=>[...new Set(USAGE.facts.map(f=>f[F[dim]]).filter(Boolean))].sort();
 const totalsFor=dim=>{const m=new Map();
  for(const f of USAGE.facts)m.set(f[F[dim]],(m.get(f[F[dim]])||0)+f[F.tokens]);
  return m;};
 const filt=el('div',{class:'ufil'});
 const r1=el('div',{class:'ufrow'}),r2=el('div',{class:'ufrow'});
 // Free text is the way in when you do not yet know which dimension the word you
 // remember belongs to. Debounced, because every change repaints the tab.
 const qIn=el('input',{type:'search',id:'uq',class:'usearch',value:UF.q,
   placeholder:'search rows — id, title, model, person, agent…',
   'aria-label':'search usage rows'});
 qIn.addEventListener('input',()=>{clearTimeout(UQT);
   UQT=setTimeout(()=>{if(qIn.value!==UF.q)setF('q',qIn.value);},220);});
 r1.append(qIn);
 // `task` joins the typeaheads: it was filterable by clicking a bar or a browse
 // row and by nothing you could type, which on 1000 tasks means it was filterable
 // only by the ones already in the top 8.
 ['model','author','phase','task'].forEach(dim=>{
  const all=uniq(dim),tot=totalsFor(dim);
  const inp=el('input',{type:'search',value:UF[dim],
    placeholder:'all '+dim+'s ('+all.length+')','aria-label':'filter by '+dim,
    onchange:e=>setF(dim,all.includes(e.target.value)?e.target.value:'')});
  r1.append(comboWrap(inp,()=>all.map(v=>({name:v,
    description:uTok(tot.get(v)||0)})),(name,close)=>{close();setF(dim,name);}));});
 // "My spend" — the author filter, pre-loaded with the name in the topbar. It is
 // the SAME string on both ends by construction: the server resolves it with
 // usage_ledger.resolve_author, which is the function that wrote the author column
 // on every row here. A toggle, not a jump: pressing it twice puts you back.
 const me=((STATE||{}).viewer||{}).author;
 if(me){
  const mine=USAGE.facts.filter(f=>f[F.author]===me).length,on=UF.author===me;
  // Rendered even when the count is zero, and saying so, because that is a fact
  // worth having: `usage.authorMode` may name you differently here (hash mode, a
  // repo-local user.email) and a chip that quietly disappeared would leave that
  // unanswerable. Pressing it lands on the empty state, which names the author
  // filter as the cause and offers to lift it.
  r1.append(el('button',{class:'filt'+(on?' on':''),type:'button','data-umine':'1',
    'aria-pressed':on?'true':'false',
    title:mine?('Scope to the '+mine+' row(s) recorded for '+me)
      :('No rows are recorded for '+me+' in this ledger'),
    onclick:()=>setF('author',on?'':me)},'my spend'));}
 [['agent','all agents'],['attr','all attributions']].forEach(([dim,none])=>{
  const vals=uniq(dim);
  if(!vals.length)return;
  const sel=el('select',{'aria-label':'filter by '+fName(dim),'data-uf':dim,
    onchange:e=>setF(dim,e.target.value)});
  sel.append(el('option',{value:''},none+' ('+vals.length+')'));
  vals.forEach(v=>{const o=el('option',{value:v},v);
   if(UF[dim]===v)o.selected=true;sel.append(o);});
  r2.append(sel);});
 // An absolute window, in the same UF.day grammar the chart's click writes.
 const dp=uDayPair();
 const mkDate=(which,val)=>el('input',{type:'date',value:val,
   'data-uf':which,'aria-label':which+' date',
   // The pickers open on the ledger, not on this century. Both ends are also
   // cross-constrained so the picker cannot offer a `to` before the `from`.
   min:which==='to'?(dp[0]||K.from||''):(K.from||''),
   max:which==='from'?(dp[1]||K.to||''):(K.to||''),
   onchange:e=>{const[a,b]=uDayPair();
     if(which==='from')uSetDays(e.target.value,b);else uSetDays(a,e.target.value);}});
 r2.append(el('span',{class:'udates'},
   el('span',{class:'filtlbl'},'from'),mkDate('from',dp[0]),
   el('span',{class:'filtlbl'},'to'),mkDate('to',dp[1])));
 r2.append(el('select',{'aria-label':'time range','data-uf':'range',
   onchange:e=>{UF.range=e.target.value;renderUsage();}},
  [['all','all time'],['7','last 7 days'],['30','last 30 days'],['90','last 90 days']]
   .map(([v,l])=>el('option',Object.assign({value:v},v===UF.range?{selected:'selected'}:{}),l))));
 r2.append(el('button',{class:'btn small push',type:'button','data-ucsv':'1',
   title:'Download the rows behind this view as CSV — one row per bucket, phase, '
     +'task, model, person, agent and attribution, with the filters applied',
   onclick:()=>uExport(uFiltered())},'Export CSV'));
 filt.append(r1,r2);
 card.append(filt);

 // active-filter chips: what is scoping the view, and a way out of each
 if(uAnyFilter()){
  const chips=el('div',{class:'uchips'});
  UORDER.forEach(d=>chips.append(el('button',{class:'uchip',title:'remove this filter',
    'data-uchip':d,onclick:()=>setF(d,'')},el('span',{class:'ck'},fName(d)),
    fVal(d),el('span',{class:'cx'},'x'))));
  chips.append(el('button',{class:'lnk',onclick:clearAll},'clear all'));
  card.append(chips);}

 const facts=uFiltered();
 const days=[...new Set(facts.map(f=>f[F.ts].slice(0,10)))].sort();
 const tot=facts.reduce((a,f)=>[a[0]+f[F.tokens],a[1]+f[F.cost],a[2]+f[F.msgs]],[0,0,0]);
 const cov=uCoverage(facts),unit=uUnit(facts),rt=uRetry(facts);
 const dl=uDelta(facts,days);
 const sp=uDaily(facts);
 // A tile is three things: the number, how it moved against the window before, and
 // the shape it moved in. `pp` says the delta is a difference in percentage POINTS
 // rather than a percentage change; `pol` marks the one metric whose direction is
 // worth judging, so only that one is coloured.
 const tile=(k,v,o)=>{o=o||{};
  const d=o.delta==null?null:o.delta;
  const box=el('div',{class:'utile'},el('div',{class:'k'},k),
    el('div',{class:'v'},v,d==null?null:el('span',
      {class:'dl '+(d>=0?'up':'down')+(o.pol?(d>=0?' good':' bad'):''),
       'data-dl':o.key||'',title:dl.basis},
      (d>=0?'+':'')+d.toFixed(o.pp?1:0)+(o.pp?' pts':'%'))));
  const s=o.series?uSpark(o.series,k+' per '+sp.period+', oldest to newest',!o.pp)
    :null;
  box.append(s
    ? el('div',{class:'utrend',
        title:k+' per '+sp.period+(o.pp?', scaled to its own range — a share has no'
          +' zero to draw an area from':', from zero')},s)
    // Not a blank: a tile with no spark has a reason, and the reason is short
    // enough to carry. Dropping the row instead would also shorten the card and
    // pull the tile grid out of line.
    : el('div',{class:'utrend',title:o.why||'no daily series for this metric'},'—'));
  return box;};
 const tiles=[tile('tokens',uTok(tot[0]),
   {key:'tokens',delta:dl&&dl.tokens,series:sp.series.tokens})];
 if(USAGE.showCost)tiles.push(tile('equivalent cost',uCost(tot[1]),
   {key:'cost',delta:dl&&dl.cost,series:sp.series.cost}));
 tiles.push(tile('messages',tot[2].toLocaleString(),
   {key:'msgs',delta:dl&&dl.msgs,series:sp.series.msgs}));
 if(unit.perTask!=null)tiles.push(tile('cost per task',uCost(unit.perTask),
   {why:'no daily trend: a task’s cost accrues over every day it ran and is only '
     +'complete when the task is, so there is no per-day cost-per-task to plot'}));
 tiles.push(tile('attributed',uPct(cov.attributed),
   {key:'attributed',delta:dl&&dl.attributed,pp:true,pol:1,
    series:sp.series.attributed}));
 card.append(el('div',{class:'utiles'},tiles));
 // Said once, under the row, rather than five times on five chips — and the exact
 // pair of date ranges is on each chip's own tooltip.
 if(dl)card.append(el('div',{class:'ucrumb mut small'},
   'Trend is '+dl.label+': '+dl.basis+'.'));

 if(!facts.length){
  const why=uEmptyWhy();
  const acts=el('div',{class:'uempty'});
  if(why.fix)acts.append(el('button',{class:'btn small','data-ufix':why.fix.key,
    onclick:why.fix.run},why.fix.label));
  // Kept, and kept second: it is the way out when the diagnosis is "the
  // combination", and the one control a reader already knows from every other tab.
  acts.append(el('button',{class:'btn small','data-uclear':'1',
    onclick:clearAll},'Clear filters'));
  card.append(el('div',{class:'mut','data-uwhy':why.why},why.text),acts);
  done();return;}

 const dim=chartDim();
 // Slots are handed out to the entities actually drawn, so a hue is never shared.
 const sr=uSeries(facts,dim);
 const plotted=sr.entities.map(e=>e.key);
 MSLOTS=uSlots(F.model,dim==='model'?plotted
   :uAgg(facts,'model').slice(0,TOP).map(r=>r[0]),'name');
 USLOTS=dim==='model'?MSLOTS:uSlots(F.author,plotted,'spend');
 const per=sr.binSize===1?'day':BINNAME[sr.binSize];
 card.append(el('h2',{},'Tokens per '+per+' by '+dim));
 card.append(el('div',{class:'ucrumb mut'},(UF.author
   ?'Scoped to '+UF.author+' - lines are their models. Click a line to scope to one, or clear the author filter to compare people again.'
   :'Click a line to scope to that person, or anywhere else to scope to that '+per+'.')
   +(sr.binSize===1?'':' Days are rolled up into '+per+
     ' totals - '+sr.buckets.length+' points instead of '+
     'one per day, which at this span would draw noise.')));
 card.append(mountChart(sr,dim));
 card.append(el('div',{class:'ulegend'},sr.entities.map(e=>
   el('b',{class:e.key==='other'?'':'pick',
     onclick:()=>{if(e.key!=='other')setF(dim,UF[dim]===e.key?'':e.key);}},
    el('i',{style:'background:'+uCol(e.key)}),e.key))));

 card.append(...uBars(facts,'phase','By phase'));
 card.append(...uBudgets(facts));
 card.append(...uBars(facts,'model','By model'));
 card.append(...uBars(facts,'author','By author'));
 card.append(...uBars(facts,'task','By task'));

 // economics - the same honesty caveats the report carries
 card.append(el('h2',{},'Unit economics'));
 if(unit.proj)card.append(el('div',{class:'ufact'},'Remaining '+unit.remaining+
   ' task(s) project to '+uCost(unit.proj.low)+' to '+uCost(unit.proj.high)+
   ' at the p25-p75 per-task rate.'));
 else card.append(el('div',{class:'mut small'},'Projection needs '+unit.gate+
   ' completed tasks to mean anything; there are '+unit.completed+
   '. A forecast off a smaller sample would be noise.'));
 if(rt.tot)card.append(el('div',{class:'ufact'},uCost(rt.re)+' on tasks that needed '+
   'more than one attempt ('+rt.rn+' task(s)) - '+uCost(rt.bl)+
   ' on tasks that ended blocked ('+rt.bn+' task(s)).'),
  el('div',{class:'mut small'},'Retried spend is not wasted spend: the ledger '+
   'buckets by hour, not by attempt, so a task that retried and then landed did not '+
   'burn every attempt for nothing. Only the blocked figure is spend with no '+
   'outcome'+(rt.overlap?' (the same task is in both figures here)':'')+'.'));

 const rows=uRouting(facts);
 if(rows.length){card.append(el('h2',{},'Model cost within each risk band'),
  el('div',{class:'mut small'},'Compared inside a band on purpose: hard work is '+
   'routed to the stronger model deliberately, so a raw spend-per-task comparison '+
   'across bands would flag that working system as a fault.'));
  const tbl=el('table',{class:'utbl'},el('thead',{},el('tr',{},
    ['risk','model','tasks','cost/task','mean attempts'].map(h=>el('th',{},h)))));
  const tb=el('tbody',{});let last='';
  rows.forEach(r=>{tb.append(el('tr',{},el('td',{},r.risk===last?'':r.risk),
    el('td',{class:'mono'},r.model),el('td',{},String(r.tasks)),
    el('td',{},uCost(r.perTask)),el('td',{},r.att.toFixed(1))));last=r.risk;});
  tbl.append(tb);card.append(tbl);}

 // The one recommendation in the tab. Computed server-side over the whole ledger
 // (see routingAdvice in usage_state), so it is a statement about the project and
 // says so whenever a filter is narrowing everything else on screen.
 const adv=USAGE.routingAdvice||[];
 if(adv.length){
  card.append(el('h2',{},'What the evidence supports'));
  if(UORDER.length)card.append(el('div',{class:'ucrumb mut'},
    'Across the whole ledger - this one does not follow the filters above.'));
  adv.forEach(a=>card.append(el('div',{class:'advice'},
    el('div',{},el('b',{},a.risk),' work is running on ',
      el('code',{},a.from),' - '+a.tasks+' task(s) at '
      +(a.fromMeanAttempts||0).toFixed(1)+' mean attempts. Those same tokens cost '
      +uCost(a.atToRates)+' at ',el('code',{},a.to),' rates versus '
      +uCost(a.atFromRates)+', ',el('b',{},uCost(a.saving)+' less ('
      +a.savingPct.toFixed(0)+'%)'),'.'),
    el('div',{class:'mut small'},a.to+' has already run '+a.evidenceTasks
      +' task(s) in this band here, at '+(a.evidenceAttempts||0).toFixed(1)
      +' mean attempts.'))));
  card.append(el('div',{class:'mut small'},
    'An upper bound, not a forecast: this re-prices the tokens that were actually '
    +'spent at the other model’s rates, and a different model would not emit '
    +'the same tokens. Both sides use today’s price table.'));}

 done();}

// Esc pops the most recently applied filter -- the fastest way back out of a scope
// you clicked into by accident.
document.addEventListener('keydown',e=>{
 if(e.key!=='Escape'||$('#usage').classList.contains('hidden'))return;
 if(document.querySelector('.combo-menu:not(.hidden)'))return;
 // A dialog closes itself on Esc. Without this guard that same keypress would
 // ALSO drop a filter - one key, two effects, one of them invisible.
 if(document.querySelector('dialog[open]'))return;
 // An <input type=search> clears ITSELF on Escape, the same trap the browse
 // dialog hit. Left alone, one press would empty the box and pop an unrelated
 // filter; so from inside the box, Escape means "drop the search" and nothing
 // else, and the state follows the box rather than diverging from it.
 const a=document.activeElement;
 if(a&&a.id==='uq'){if(UF.q)setF('q','');return;}
 if(UORDER.length){setF(UORDER[UORDER.length-1],'');}
 else if(UF.range!=='all'){UF.range='all';renderUsage();}});
boot().catch(e=>toast('load failed: '+e,'err'));
