// ---------- the help drawer ----------
// What every field means, and how the concepts work, answered from the plugin's
// own schemas and code — see scripts/config/_help.py and GET /api/help. Two
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
/**
 * The drawer's whole state: the payload once fetched, the dialog once built, and
 * which view is showing.
 *
 * All three are null until the drawer is opened for the first time — nothing here
 * costs a request or an element until somebody presses an ⓘ.
 */
let HELPDOC=null,HDLG=null,HVIEW=null;
/**
 * One field's answer per doc-and-path, and the views walked through to get here.
 *
 * `HCACHE` maps `doc|path` to the server's answer, `{found, entry, key}`, and lives
 * as long as the session: field entries are documentation, so they cannot go stale
 * under the reader the way state can. `HSTACK` is per OPENING and cleared on close —
 * left standing, a back button would offer to return to a field somebody read ten
 * minutes ago on another tab.
 */
const HCACHE=new Map(),HSTACK=[];
/**
 * What to call the thing an ⓘ explains, for its accessible name.
 *
 * @param {{label: (string|undefined), path: (string|undefined), topic: (string|undefined)}} r -
 *   a hint's ref
 * @returns {string} the caption, else the config path, else the word "this" — a
 *   topic id is a slug and would read as jargon in a name
 */
const hRefName=r=>r.label||r.path||(r.topic?'this':'')||'this';
/**
 * The help payload — every field entry, every topic, the guide's card — fetched
 * once per session.
 *
 * @returns {Promise<{fields: Object<string, *>, composition: Object<string, string>, topics: Array<Object<string, *>>, agent: (Object<string, *>|null), schemas: Object<string, string>}>}
 *   the payload; it rejects if the endpoint does not answer, and the caller draws
 *   the failure rather than an empty drawer
 */
async function helpDoc(){if(!HELPDOC)HELPDOC=await api('GET','/api/help');return HELPDOC;}
/**
 * One field, resolved by the server.
 *
 * The drawer holds a path into a DOCUMENT and the help table is keyed by SHAPES —
 * `usage.pricing.opus.in` against `usage.pricing.<name>.in` — and `_help.entry_for`
 * is the one thing that knows the difference. Asking it over HTTP costs a localhost
 * round trip and buys the guarantee that no second implementation of that
 * resolution exists to drift.
 *
 * @param {string} path - the dotted path as the control asked for it
 * @param {'config'|'manifest'} doc - which schema to look it up in
 * @returns {Promise<{found: boolean, entry: (Object<string, *>|null), key: (string|undefined)}>}
 *   `found:false` is an answer, not an error: nothing documents that path
 */
async function helpField(path,doc){const k=doc+'|'+path;
 if(!HCACHE.has(k))HCACHE.set(k,await api('GET','/api/help?doc='+encodeURIComponent(doc)
   +'&path='+encodeURIComponent(path)));
 return HCACHE.get(k);}
/**
 * Split one sentence into text and code runs.
 *
 * Backticks are the only markup the topics use, and they use it for identifiers. An
 * unbalanced pair renders verbatim rather than guessing which half was code: a
 * mis-parsed identifier is worse than an un-styled one.
 *
 * @param {string|null|undefined} s - the sentence
 * @returns {Array<string|HTMLElement>} the pieces, ready to be passed as children;
 *   a single-item list holding the sentence verbatim when the backticks do not
 *   balance
 */
function hcode(s){const parts=String(s==null?'':s).split('`');
 if(parts.length%2===0)return [String(s)];
 return parts.map((x,i)=>i%2?el('code',{},x):x).filter(x=>x!=='');}
/**
 * One block of the drawer: an optional heading and whatever belongs under it.
 *
 * @param {string|null} title - the heading, or null for an untitled block
 * @param {...(Node|string|Array<Node|string|null>|null)} kids - the block's content;
 *   nulls are dropped, so a caller can pass a conditional child inline
 * @returns {HTMLDivElement} the block
 */
function hsec(title,...kids){return el('div',{class:'dsec'},
  title?el('h3',{},title):null,kids.flat().filter(Boolean));}
/**
 * The drawer element, built on first use and reused after that.
 *
 * @returns {HTMLDialogElement} the dialog, with its backdrop-click and close
 *   handling already wired
 */
function helpDrawer(){
 if(!HDLG){HDLG=el('dialog',{class:'drawer','aria-label':'Help'});
  HDLG.addEventListener('click',ev=>{if(ev.target===HDLG)HDLG.close();});
  // The stack is per-opening. Left standing, a back button would offer to return
  // to a field somebody read ten minutes ago on another tab.
  HDLG.addEventListener('close',()=>{HSTACK.length=0;HVIEW=null;});
  document.body.append(HDLG);}
 return HDLG;}

/**
 * The card naming the agent to ask when this drawer is not the answer.
 *
 * On every view, because that is when the question arises. It is deliberately not
 * startable from here, and the card says so: a question the panel already answers
 * for nothing should not quietly bill for a model. That is also why the card holds
 * no button at all — the browser gate counts them and fails on one.
 *
 * @param {{agent: ({name: string, qualified: string, description: (string|undefined), tools: string[], model: (string|null), effort: (string|null), readOnly: (boolean|undefined)}|null)}} doc -
 *   the help payload
 * @returns {HTMLDetailsElement|null} the card, or null on an install with no guide
 *   agent — nothing at all rather than a hint pointing at something absent.
 *   The badge reads the payload's own `readOnly` verdict and says only what it
 *   supports: read-only when true, NOT read-only when false, and neither when the
 *   payload did not declare it. It used to print "read-only" as fixed text while
 *   ignoring that flag, so an agent that gained an Edit tool stayed advertised as
 *   read-only
 */
/**
 * How to introduce an agent's tool list, given what the server said about it.
 *
 * Named `h*` like everything else in the drawer: `t*` is the theme code's prefix,
 * and every top-level name in this page shares one scope.
 *
 * @param {boolean|undefined} readOnly `_help.guide_card`'s own verdict
 * @returns {string} the prefix, including its separator
 */
function hToolClaim(readOnly){
 if(readOnly===true)return 'read-only: ';
 // Not "writes": a tool beyond the read-only set might be Bash or WebFetch, and
 // naming an effect the list does not prove would be the same mistake in the
 // other direction. What IS known is that the set is not the read-only one.
 if(readOnly===false)return 'NOT read-only: ';
 return 'tools: ';}

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
 // THE CLAIM CARRIES ITS BASIS, which is this repo's own rule and this badge
 // used to break it. The word "read-only" was fixed text and `a.readOnly` — which
 // `_help.guide_card` computes as `sorted(tools) == READ_ONLY_TOOLS` — was never
 // read. An agent that gained an `Edit` tool would still have been advertised as
 // read-only, with every gate green, on the surface whose entire job is telling
 // a reader what an agent may do.
 //
 // Three answers, because there are three states. `true` earns the claim.
 // `false` is a fact worth saying loudly on this surface. `undefined` means the
 // payload did not declare it, and then the tools are listed with NO claim
 // attached — a basis with no claim is noise, but a claim with no basis is worse.
 box.append(el('div',{class:'dtools'},
   el('span',{class:'badge'},hToolClaim(a.readOnly)+(a.tools||[]).join(' · ')),
   a.model?el('span',{class:'badge'},'model '+a.model):null,
   a.effort?el('span',{class:'badge'},'effort '+a.effort):null));
 return box;}

// --- the three views -------------------------------------------------------
/**
 * The drawer's front page: the concept pages, and where to find a field.
 *
 * It says what this drawer is and is not — schema-derived, project-independent —
 * because the reader's next question is whether any of it is about their repo.
 *
 * @param {{topics: Array<{id: string, title: string, summary: string}>}} doc - the
 *   help payload
 * @returns {{title: string, body: HTMLDivElement}} a view, for the shell to frame
 */
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

/**
 * One concept page: its summary, its paragraphs, its worked table, and where the
 * rule is stated in full.
 *
 * Every executable rule on the page was derived from the function that executes it,
 * so the sources at the foot are citations rather than further reading.
 *
 * @param {{topics: Array<{id: string, title: string, summary: string, paragraphs: (string[]|undefined), table: ({columns: string[], rows: string[][], caption: (string|undefined)}|undefined), sources: (string[]|undefined)}>}} doc -
 *   the help payload
 * @param {string} id - the topic id
 * @returns {{title: string, body: HTMLDivElement}} the view, or a "no page with
 *   that name" body — which is a stale link, and says so rather than opening blank
 */
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
      tableHead(t.table.columns||[]),tb)),
    t.table.caption?el('p',{class:'dcap'},hcode(t.table.caption)):null));}
 if((t.sources||[]).length)body.append(hsec('Stated in full in',
   el('div',{class:'dsrc'},t.sources.map(s=>el('span',{},s)))));
 return {title:t.title,body};}

/**
 * One field: what the schema says, what it accepts, what this form does about it,
 * and the concept page behind it.
 *
 * Two voices, kept apart on purpose. The schema's sentence comes first, because it
 * is the one an editor shows and the one the file is validated against, and it is
 * cited rather than paraphrased. The panel's own microcopy comes second under its
 * own heading — it describes what THIS FORM does, which is a different claim about
 * a different thing.
 *
 * @param {{composition: Object<string, string>, schemas: Object<string, string>, topics: Array<{id: string, title: string, summary: string}>}} doc -
 *   the help payload
 * @param {{path: (string|undefined), comp: (string|undefined), doc: (string|undefined), label: (string|undefined)}} ref -
 *   what to look up: a config path, or a composition lever mapped to its manifest
 *   path by the payload, so this file carries no second copy of that map
 * @returns {Promise<{title: string, body: HTMLDivElement}>} the view. Two different
 *   empty answers, and they are not the same news: no path at all means nothing
 *   documents this control, while a path the schema has no entry for is a gap in the
 *   schema and is named as one
 */
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

/**
 * A schema default, written so the three empty ones stay distinguishable.
 *
 * `null`, an empty list and an empty string are three different defaults, and a
 * reader deciding whether to leave a field alone needs to know which one they would
 * get. None of them may print as blank.
 *
 * @param {*} v - the default out of the schema entry
 * @returns {string} the value as words
 */
function hVal(v){return v===null?'null':(Array.isArray(v)
  ?(v.length?v.join(', '):'(empty list)')
  :(v===''?'(empty text)':String(v)));}

/**
 * Open the drawer on one view, and fill it in.
 *
 * The dialog is shown BEFORE the awaits so the press has an effect at once, and the
 * content goes in afterwards in one go rather than staged — measured at 10 ms to
 * build the payload and 1 ms per field after that, so there is nothing worth
 * staging, and a header painted early would only be the previous field's title for
 * those 10 ms.
 *
 * A failed request draws the failure inside the drawer instead of leaving it empty:
 * the reader pressed something, so something has to answer.
 *
 * @param {{kind: 'index'|'topic'|'field', id: (string|undefined), ref: (Object<string, *>|undefined)}} view -
 *   which view to show
 * @param {boolean} push - true to remember the current view, so the back button can
 *   return to it; false when this view IS the return
 * @returns {Promise<void>} resolves once the drawer holds the view
 */
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
 // Everything at once, now that the payload is here: see the note above on why
 // nothing is staged.
 d.textContent='';
 const head=el('div',{class:'dhead'});
 if(HSTACK.length)head.append(el('button',{class:'btn small','data-hback':'1',
   type:'button',onclick:()=>{const prev=HSTACK.pop();hShow(prev,false);}},'←'));
 head.append(el('h2',{},v.title),el('button',{class:'bx','aria-label':'close help',
   type:'button',onclick:()=>d.close()},'×'));
 d.append(head,v.body,hAgentCard(doc));
 v.body.scrollTop=0;}

/**
 * Open the drawer on whatever a hint refers to. This is what every ⓘ calls.
 *
 * A ref naming a topic goes straight to that page; anything else is a field. Never
 * pushes, because pressing an ⓘ starts a reading, it does not continue one.
 *
 * @param {{path: (string|undefined), comp: (string|undefined), topic: (string|undefined), doc: (string|undefined), label: (string|undefined)}|null} ref -
 *   a hint's ref; an empty ref still opens, and says nothing documents the control
 * @returns {Promise<void>} resolves once the drawer holds the view
 */
function openHelp(ref){
 if(ref&&ref.topic)return hShow({kind:'topic',id:ref.topic},false);
 return hShow({kind:'field',ref:ref||{}},false);}
/**
 * Open the drawer on its front page — what the topbar's help button does.
 *
 * @returns {Promise<void>} resolves once the drawer holds the index
 */
function openHelpIndex(){return hShow({kind:'index'},false);}
$('#helpbtn').onclick=()=>openHelpIndex();
// ---------- the combo menu behind every picker ----------
// A custom autocomplete: the menu opens directly under the input, at a limited
// height, with legible items (name + source + description) and both keyboard and
// click selection.
//
// THE menu is one element on <body> — the #hinttip rule applied to the second
// overlay this page has. It used to be a child of each combo's wrapper,
// position:fixed and placed from the input's viewport rect, and `tr.phase:hover
// >td{filter:...}` made that td the CONTAINING BLOCK of every fixed descendant:
// the phase row's review-model menu jumped ~550px on hover and grew the table
// frame's scroll box (measured 321->868px tall, 837->1194px wide — the "layout
// change" of the report). Hovering the menu itself counted as hovering the row,
// by DOM ancestry, so the menu fled from under the pointer. On <body> there is no
// ancestor to trap, clip or restack it, and a click inside it can no longer bubble
// into the row it was drawn for. Focus is singular, so one menu suffices: the
// combo whose input holds focus CLAIMS the element and fills it, and the loser's
// delayed close is a no-op on a menu it no longer holds.

/**
 * The one menu element, and the combo that currently owns it.
 *
 * `CMENU` is the shared listbox on <body>, null until the first combo needs it.
 * `CMOWNER` is the owning combo's handle — `{close, place}` — or null when no menu
 * is open. Ownership is what makes one shared element safe: a close arriving from a
 * combo that no longer owns the menu does nothing at all.
 */
let CMENU=null,CMOWNER=null;
/**
 * The menu element, built on first use and appended to the body.
 *
 * @returns {HTMLDivElement} the shared listbox
 */
function comboMenu(){
 if(!CMENU){CMENU=el('div',{class:'combo-menu hidden',id:'combomenu',role:'listbox'});
  // A mousedown ANYWHERE in the menu — padding, the overflow footer, the
  // scrollbar — must not blur the input, because the blur closes the menu a
  // moment later. The menu as a whole keeps the focus where it is; the items
  // still choose on their own mousedown.
  CMENU.addEventListener('mousedown',e=>e.preventDefault());
  document.body.append(CMENU);}
 return CMENU;}
/**
 * Close whatever menu is open. Re-renders and tab switches must call this: the
 * menu is not inside the view any more, so tearing the view down no longer takes
 * it along.
 *
 * @returns {void}
 */
function closeCombo(){if(CMOWNER)CMOWNER.close();}
/**
 * Whether a menu is open — read by the disk refresh, which must not rebuild a view
 * under an open one.
 *
 * @returns {boolean} true while the shared menu is showing
 */
const comboOpen=()=>!!(CMENU&&!CMENU.classList.contains('hidden'));
/**
 * Wrap an input into a combo box: type to filter, arrows and Enter to choose.
 *
 * The filter reads name, description and source together rather than the name
 * alone: "which skills mention security" and "which models did the ledger meter"
 * are questions a name cannot answer. Each item's haystack is built on first use
 * and cached ON THE ITEM under `.h`, the same trick and the same field name as
 * `uHay` in usage-filtering.js — which means the objects `itemsFn` hands back are
 * written to, and an items function that rebuilds them per call pays for the cache
 * without getting it. In the usage combos the description is a magnitude, so a
 * digit query matches token counts too; uniformity beats a per-site opt-out.
 *
 * The menu is capped in both directions: the list is sliced, and what did not fit
 * is reported as a count. The count is taken BEFORE the slice, and the footer is
 * appended to the menu rather than to the list the keyboard walks — a row that
 * cannot be chosen must not be reachable by ArrowDown.
 *
 * @param {HTMLInputElement} inp - the input to wrap; it is moved into the wrapper
 * @param {() => Array<{name: string, description: (string|undefined), source: (string|undefined), h: (string|undefined)}>} itemsFn -
 *   the current candidates, asked for on every keystroke so a registry that has
 *   since loaded is picked up
 * @param {(name: string, close: () => void) => void} onChoose - given the chosen
 *   name and the closer, because some call sites keep the menu open
 * @param {(text: string, close: () => void) => void} [onEnterFree] - Enter with
 *   nothing highlighted, for the fields that accept a value not in the list; without
 *   it, such an Enter does nothing
 * @returns {HTMLDivElement} the wrapper holding the input
 */
function comboWrap(inp,itemsFn,onChoose,onEnterFree){
 const wrap=el('div',{class:'combo'});
 let active=-1,shown=[];
 const me={};
 const close=()=>{active=-1;
  if(CMOWNER===me){const menu=comboMenu();menu.classList.add('hidden');menu.textContent='';CMOWNER=null;}};
 me.close=close;
 // Fixed-position, like the hint tip: placed at the input's own x where that
 // fits, clamped into the viewport where it does not, and flipped above the input
 // when the space below cannot hold it (390px is the width that decides all
 // three). An input that a re-render has removed closes its menu here — the
 // scroll/resize re-place is the one path that still runs for it.
 //
 // The height cap below is the menu's max-height from combobox.css, in px at the
 // default root size. Two numbers for one limit: change one and the flip decides
 // on a height the menu will not have.
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
 // After a choice, or after Escape, the input keeps focus with the menu closed —
 // so a click on it has to open the menu again rather than wait for a keystroke.
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
// One listener for the whole page, registered once: a fixed-position menu does not
// follow its input when anything scrolls, so an open menu is re-placed here. In the
// capture phase, because the tables that hold these inputs scroll inside their own
// frames rather than the page. The placer is read off the ELEMENT rather than off
// the owning combo, which dates from one menu per view; with a single shared menu
// this query can match at most one.
['scroll','resize'].forEach(ev=>addEventListener(ev,()=>{
 document.querySelectorAll('.combo-menu:not(.hidden)').forEach(m=>{
  if(m.__place)m.__place();});},{capture:true,passive:true}));

