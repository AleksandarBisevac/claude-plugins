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
 if(!d.open)dlgOpen(d);
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
// The filter reads name+description+source, not the name alone: "which skills
// mention security" and "which models did the ledger meter" are questions the
// name cannot answer. The haystack is built lazily and cached on the item (the
// uHay pattern), so the second keystroke rebuilds nothing. In the usage combos
// the description is a magnitude ("3.2M"), so a digit query matches token
// counts too — uniformity beats a per-site opt-out.
//
// THE menu is one element on <body> (F-P-1a), the #hinttip rule applied to the
// second overlay this page has: it used to be a child of each combo's wrapper,
// position:fixed and placed from the input's viewport rect — and `tr.phase:hover
// >td{filter:...}` made that td the CONTAINING BLOCK of every fixed descendant,
// so the phase row's review-model menu jumped ~550px on hover and grew the
// table frame's scroll box (measured 321->868px tall, 837->1194px wide: the
// "layout change" of the report). Hovering the menu itself counted as hovering
// the row (DOM ancestry), so the menu fled from under the pointer. On <body>
// there is no ancestor to trap, clip or restack it, and a click inside it can
// no longer bubble into the row it was drawn for. Focus is singular, so one
// menu suffices: the combo whose input has it CLAIMS the element (CMOWNER) and
// fills it; the loser's delayed close is a no-op on a menu it no longer holds.
let CMENU=null,CMOWNER=null;
function comboMenu(){
 if(!CMENU){CMENU=el('div',{class:'combo-menu hidden',id:'combomenu',role:'listbox'});
  // F-P-1d: a mousedown ANYWHERE in the menu — padding, the overflow footer,
  // the scrollbar — used to blur the input, and the blur closed the menu 150ms
  // later; only the items prevented it. The menu as a whole keeps the focus
  // where it is; the items still choose on their own mousedown.
  CMENU.addEventListener('mousedown',e=>e.preventDefault());
  document.body.append(CMENU);}
 return CMENU;}
// Re-renders and tab switches call this: the menu is not inside the view any
// more, so tearing the view down no longer takes it along.
function closeCombo(){if(CMOWNER)CMOWNER.close();}
const comboOpen=()=>!!(CMENU&&!CMENU.classList.contains('hidden'));
function comboWrap(inp,itemsFn,onChoose,onEnterFree){
 const wrap=el('div',{class:'combo'});
 let active=-1,shown=[];
 const me={};
 const close=()=>{active=-1;
  if(CMOWNER===me){const menu=comboMenu();menu.classList.add('hidden');menu.textContent='';CMOWNER=null;}};
 me.close=close;
 // Fixed-position, like showTip: placed at the input's own x where that fits,
 // clamped into the viewport where it does not, and flipped above the input
 // when the space below cannot hold it (390px is the width that decides all
 // three). An input that a re-render has removed closes its menu here — the
 // scroll/resize re-place is the one path that still runs for it.
 const place=()=>{const menu=comboMenu();
  if(CMOWNER!==me||menu.classList.contains('hidden'))return;
  if(!inp.isConnected){close();return;}
  const r=inp.getBoundingClientRect(),vw=document.documentElement.clientWidth,
    vh=innerHeight,gut=8;
  const w=Math.min(Math.max(r.width,180),vw-2*gut);
  menu.style.width=w+'px';
  menu.style.left=Math.min(Math.max(gut,r.left),vw-gut-w)+'px';
  const mh=Math.min(menu.scrollHeight,240);
  menu.style.top=(r.bottom+4+mh>vh-gut&&r.top-4-mh>gut
    ?r.top-4-mh:r.bottom+4)+'px';};
 me.place=place;
 const render=()=>{const q=inp.value.trim().toLowerCase();
  const menu=comboMenu();
  if(CMOWNER&&CMOWNER!==me)CMOWNER.close();
  CMOWNER=me;menu.__place=place;   // re-placed by the document-level scroll listener below
  const all=itemsFn().filter(it=>{
   if(it.h===undefined)it.h=(it.name+' '+(it.description||'')+' '+(it.source||'')).toLowerCase();
   return it.h.includes(q);});
  shown=all.slice(0,60);
  menu.textContent='';
  if(!shown.length){close();return;}
  shown.forEach((it,i)=>menu.append(el('div',{class:'combo-it'+(i===active?' active':''),role:'option',
    onmousedown:e=>{e.preventDefault();onChoose(it.name,close);}},
    el('span',{class:'combo-n mono'},it.name),
    it.source?el('span',{class:'src badge'},it.source):null,
    it.description?el('span',{class:'combo-d'},it.description):null)));
  // The footer is appended to the MENU and never enters `shown`: keyboard nav
  // indexes that array, and a row that cannot be chosen must not be reachable
  // by ArrowDown. The count is taken before the slice, so it is the truth.
  if(all.length>shown.length)menu.append(el('div',{class:'combo-more'},
    '…'+(all.length-shown.length)+' more — keep typing'));
  menu.classList.remove('hidden');place();
  const a=menu.querySelector('.combo-it.active');if(a)a.scrollIntoView({block:'nearest'});};
 inp.setAttribute('autocomplete','off');
 inp.addEventListener('focus',render);
 // F-P-1c: after a choice (or Escape) the input keeps focus and the menu is
 // closed — a click on it must open the menu again, not wait for a keystroke.
 inp.addEventListener('click',()=>{if(!(CMOWNER===me&&comboOpen()))render();});
 inp.addEventListener('input',()=>{active=-1;render();});
 inp.addEventListener('keydown',e=>{
  if(e.key==='ArrowDown'){e.preventDefault();active=Math.min(active+1,shown.length-1);render();}
  else if(e.key==='ArrowUp'){e.preventDefault();active=Math.max(active-1,0);render();}
  else if(e.key==='Enter'){if(active>=0){e.preventDefault();onChoose(shown[active].name,close);}
   else if(onEnterFree&&inp.value.trim()){e.preventDefault();onEnterFree(inp.value.trim(),close);}}
  else if(e.key==='Escape'){close();}});
 inp.addEventListener('blur',()=>setTimeout(close,150));
 wrap.append(inp);return wrap;}
// One listener for every combo, registered once: a fixed-position menu does not
// follow its input when something scrolls, so any open menu is re-placed. Only
// menus still in the DOM are found, so re-rendered views leak nothing.
['scroll','resize'].forEach(ev=>addEventListener(ev,()=>{
 document.querySelectorAll('.combo-menu:not(.hidden)').forEach(m=>{
  if(m.__place)m.__place();});},{capture:true,passive:true}));

