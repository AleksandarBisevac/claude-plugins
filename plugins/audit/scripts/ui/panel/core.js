
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
 // th: the live preview is per-mode — repaint it for the mode just chosen.
 // Unguarded: `tPaint` is a top-level `function`, and hoisting is per SCRIPT
 // rather than per part, so it is defined before this line can run — measured,
 // not assumed. The `typeof` guard that stood here could not be taken.
 tPaint();
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
// uc (F-P-2): "--" is the ledger's storage key for spend with no phase or task
// behind it — ad-hoc edits, `#no-plan`, work outside the plan. That is an
// answer, and it used to reach the screen as those two characters. LABELS
// names it (shared with the report and the CLI, so the three cannot drift),
// and uKeyEl paints it in the warn role: not a gate, not a finding, just the
// one row in the table a reader should be able to find without hunting.
const UNCAT='--';
// TWO storage keys, one fact: the group dimensions (phase/task/branch) write
// "--" for a row with none, and the attr dimension writes "unattributed" for
// the same spend seen from the other side. A reader meets one thing, so they
// get one word. Deliberately a two-key predicate rather than label() over any
// key: label() humanises whatever it does not know, and "claude-opus-5" is not
// something to prettify.
const isUncat=k=>k===UNCAT||k==='unattributed';
const UNCAT_WHY='spend with no phase or task behind it - ad-hoc edits, #no-plan, '
 +'or sessions outside the plan. Counted, never hidden.';
const uKey=k=>isUncat(k)?label(UNCAT):k;
const uKeyEl=(k,cls)=>isUncat(k)
 ?el('span',{class:'uncat'+(cls?' '+cls:''),title:UNCAT_WHY},label(UNCAT))
 :(cls?el('span',{class:cls},String(k)):String(k));
const TABS=['guards','comp','over','usage','policy','look'],SCROLL={};
let CURTAB=null;
function showTab(t,push){
 if(!TABS.includes(t))t='guards';
 closeCombo();   // the menu is on <body>, not in the view being hidden
 if(CURTAB)SCROLL[CURTAB]=window.scrollY;
 CURTAB=t;
 document.querySelectorAll('.tab').forEach(x=>{const on=x.dataset.t===t;x.classList.toggle('on',on);
  // Colour alone does not say which view you are in — a screen reader gets nothing
  // from a background change, and these four are exclusive views, not filters.
  if(on)x.setAttribute('aria-current','true');else x.removeAttribute('aria-current');});
 for(const id of TABS)$('#'+id).classList.toggle('hidden',id!==t);
 // fp: the tab writer carries the usage-filter fragment, so switching views
 // does not throw away a filtered link somebody is about to copy.
 if(push!==false){const uf=uFragment();const h='#/'+t+(uf?'!'+uf:'');
  if(location.hash!==h)history.replaceState(null,'',h);}
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
// Both readers split on the FIRST '!': the fragment behind it is the usage
// filters' (fp), and `#/usage!m=opus` has to route like `#/usage` did.
addEventListener('hashchange',()=>{const t=(location.hash||'').replace(/^#\/?/,'').split('!')[0];
 if(TABS.includes(t)&&t!==CURTAB)showTab(t,false);});
function initialTab(){const h=(location.hash||'').replace(/^#\/?/,'').split('!')[0];
 if(TABS.includes(h))return h;
 try{const s=localStorage.getItem('audit-panel-tab');if(TABS.includes(s))return s;}catch(e){}
 return 'guards';}
function toast(msg,kind){const t=$('#toast');t.textContent=msg;t.className='show '+(kind||'');
 setTimeout(()=>t.className=t.className.replace('show','').trim(),2600);}
// The save-result card's lifecycle (sv): success dissolves after SAVE_NOTE_MS,
// a refusal stays until dismissed or until the next Save/Discard replaces the
// slot, warnings persist. "✓ saved" used to sit in the slot for the rest of
// the session — indistinguishable from a save that just landed.
const SAVE_NOTE_MS=5000;
function findingsBox(res){const box=el('div',{class:'savenote'});
 if(res.findings&&res.findings.length){
  // No timer on a refusal: a reader who glanced away must find the list still
  // there. It leaves through its own ×, or when the next Save/Discard
  // replaceChildren()s the slot this box lives in.
  const card=el('div',{class:'findings err'});
  card.append(el('div',{class:'nthead'},
    el('b',{},res.locked?'Locked — nothing was written'
      :'Save rejected — nothing was written'),
    el('button',{class:'notex','aria-label':'dismiss','data-notex':'1',
      type:'button',onclick:()=>card.remove()},'×')),
   el('div',{class:'fbody'},'✗ '+res.findings.join(' · ')));
  box.append(card);}
 if(res.warnings&&res.warnings.length)box.append(el('div',{class:'findings warn'},'! '+res.warnings.join(' · ')));
 if(res.ok&&!(res.warnings&&res.warnings.length)){
  const okd=el('div',{class:'findings ok'},'✓ saved');
  // The timer belongs to the NODE and is armed exactly once, here: renderPolicy
  // carries these nodes across its own redraw (PNOTE), and a timer re-armed per
  // render would reset the clock on every repaint. An opacity TRANSITION, not a
  // keyframe — the screenshot tool's settle() waits out getAnimations(), and an
  // idling keyframe would stall every shutter behind it. The fallback removal
  // covers a card whose transition never fires (a hidden tab paints nothing).
  setTimeout(()=>{okd.classList.add('fadeout');
   okd.addEventListener('transitionend',()=>okd.remove(),{once:true});
   setTimeout(()=>okd.remove(),600);},SAVE_NOTE_MS);
  box.append(okd);}
 return box;}
