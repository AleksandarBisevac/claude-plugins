
// ---------- the primitives every later part reads ----------
/**
 * The session token every request to this origin must carry, and the absolute
 * path of the project this panel was started in.
 *
 * Both are substituted into the script text by `panel-server.py` — the token per
 * request, JSON-encoded — rather than fetched, because the first fetch would
 * already need the token.
 */
const TOKEN=__AUDIT_TOKEN__, PROJECT=__AUDIT_PROJECT__;
// The build serving this page. Baked in at import, not fetched: it cannot change
// while the process lives, so a state round-trip would be a promise that it can.
const VERSION=__AUDIT_VERSION__;
/**
 * `$` — the first element matching a CSS selector.
 *
 * A caller naming an id from `panel.html`'s static skeleton dereferences the
 * result straight away, so a null there means the id was renamed rather than a
 * state to handle. A caller reaching into a rendered view has to expect null:
 * every render function rebuilds its subtree wholesale, so the node it is
 * looking for may not exist yet, or any more.
 *
 * @param {string} s - any CSS selector
 * @param {ParentNode} [r] - subtree to search; the whole document when omitted
 * @returns {Element|null} the first match, or null when nothing matches
 */
/**
 * `el` — the element builder every part of this panel builds DOM with, at
 * several hundred call sites. Three of its rules are not guessable from a call:
 *
 *   `class` sets className, `html` hands its value to innerHTML, and a key
 *   beginning `on` becomes a listener for the event named by the rest of it
 *   (`onclick` listens for 'click'), so a handler is passed as a function and
 *   never as a string. Every other key is an attribute.
 *
 *   An ATTRIBUTE whose value is null or undefined is skipped entirely, which is
 *   what lets a conditional attribute be written inline as `cond?'1':null`
 *   instead of as a second statement. The class, the innerHTML key and the
 *   handlers are not attributes and get no such treatment — a null class is
 *   written through and becomes the class name "null".
 *
 *   Children are flattened ONE level. An array of nodes may therefore be passed
 *   as a single argument, but an array of arrays may not — the inner array would
 *   reach the text-node branch and be stringified. Only null and undefined
 *   children are dropped: `0` and `false` arrive as the text "0" and "false".
 *
 * The innerHTML key takes markup, so nothing derived from the manifest, the
 * config or an API answer may go through it. Pass such a value as a child
 * instead, where it becomes a text node.
 *
 * @param {string} t - tag name
 * @param {Object<string, string|number|boolean|null|((ev: Event) => void)>} [a] -
 *   attributes, the class and innerHTML keys, and `on*` handlers, in one bag
 * @param {...(Node|string|number|Array<Node|string|number|null>|null)} k -
 *   children, flattened one level; a string becomes a text node
 * @returns {HTMLElement} the new element, already populated
 */
const $=(s,r=document)=>r.querySelector(s), el=(t,a={},...k)=>{const e=document.createElement(t);
 for(const[n,v]of Object.entries(a)){if(n==='class')e.className=v;else if(n==='html')e.innerHTML=v;
 else if(n.startsWith('on'))e.addEventListener(n.slice(2),v);else if(v!=null)e.setAttribute(n,v);}
 for(const c of k.flat()){if(c!=null)e.append(c.nodeType?c:document.createTextNode(c));}return e;};
/**
 * One call to the panel's own API, carrying the session token.
 *
 * Every request goes through here, so the token header is written once. The
 * answer is parsed as JSON unconditionally: an HTTP error status still RESOLVES,
 * with whatever JSON the server sent, which is why callers decide on the
 * payload's own `ok` and `findings` fields and never on a status code. It
 * rejects only when the network fails or the body is not JSON at all: the boot
 * sequence catches that for the payloads a view can do without, and deliberately
 * lets it through for the two nothing can be drawn without.
 *
 * @param {string} m - HTTP method
 * @param {string} p - path on this origin, e.g. /api/state
 * @param {Object<string, *>} [b] - payload, serialized as JSON; omit for a GET
 * @returns {Promise<Object<string, *>>} the parsed answer
 */
const api=async(m,p,b)=>{const r=await fetch(p,{method:m,headers:{'X-Audit-Token':TOKEN,
 'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});return r.json();};
/**
 * The same path, signed for a NAVIGATION rather than a fetch.
 *
 * A navigation cannot set a header, so the token has to ride in the query
 * string; the server's guard accepts either.
 *
 * @param {string} p - path on this origin
 * @returns {string} the path with the session token appended as a query
 */
const url=p=>p+'?t='+encodeURIComponent(TOKEN);
/**
 * The two payloads every view reads.
 *
 * `STATE` is the whole answer of GET /api/state — the config, the manifest's
 * composition view, findings, the rollup, who is viewing and what is running.
 * `REG` is what discovery found in this repo and globally, and starts as the
 * empty shape rather than null so a render that runs before boot's fetch iterates
 * nothing instead of throwing. `STATE` has no such shape, which is why nothing
 * is rendered until it lands.
 */
let STATE=null, REG={skills:[],agents:[],mcp:[]};
/**
 * Shorten a path from the MIDDLE, keeping both of its ends.
 *
 * Not a tail cut: the head says which machine or checkout this is and the tail
 * says which project, so a plain truncation throws away whichever end the CSS
 * happens to reach first. The whole path stays in the tooltip beside every call,
 * so nothing is lost — it is only no longer allowed to set the header's height.
 *
 * @param {string} s - the path to shorten
 * @param {number} max - widest result allowed, the ellipsis counted
 * @returns {string} `s` when it already fits, '' when there is nothing to
 *   shorten, otherwise head + ellipsis + tail at exactly `max` characters
 */
function midElide(s,max){if(!s||s.length<=max)return s||'';
 const keep=max-1,head=Math.ceil(keep*0.38);return s.slice(0,head)+'…'+s.slice(s.length-(keep-head));}
$('#proj').textContent=midElide(PROJECT,56);
$('#proj').title=PROJECT;
// Which installed plugin is serving this panel — the same component as the report's
// stamp (`.stampv`), because it answers the same question, but beside the product
// name rather than trailing the project path. It used to be appended to `#proj`,
// where it lost every contest for that line's width: the path is elided to fill it,
// so the stamp was pushed past the clip and was invisible on any project whose path
// is long enough to elide. Here nothing competes with it. The h1 already reads
// "audit", so the stamp carries the number alone rather than repeating the name.
// The panel is where the question actually gets asked: the plugin cache is keyed BY
// VERSION, so `marketplace update` followed by a reload can leave you driving a
// build you did not intend, with nothing on screen to say so. Omitted entirely when
// the version cannot be read: a stamp with no basis is worse than no stamp.
if(VERSION)$('#brand').append(el('span',{class:'stampv',
  title:'The plugin version serving this panel'},'v'+VERSION));
/**
 * Mark the header when it has room for the version stamp beside the title, so the
 * CSS can show it there — and leave it hidden when it has not.
 *
 * Measured, not assumed, for the same reason tabsOverflow() is: this column is
 * shrunk by whatever the topbar's buttons and the identity pill leave it, and a
 * stamp that does not fit takes its width out of the title instead, wrapping it
 * onto another line and making a sticky bar taller that everything below is
 * offset against. `.roomy` is added FIRST and kept only if the row still fits
 * inside the column, because the question is whether it fits when it is shown;
 * asking it while the stamp is hidden always answers yes.
 *
 * The observer is not belt and braces over the resize listener. The identity pill
 * is rendered from /api/state after this file has run and takes its width out of
 * this column when it lands, and no resize event is fired for that — the same
 * reason the report observes its own topbar rather than only listening to the
 * window.
 *
 * @returns {void}
 */
function stampRoom(){const b=$('#brand');if(!b||!$('.stampv'))return;
 b.classList.add('roomy');
 if(b.scrollWidth>b.clientWidth+1)b.classList.remove('roomy');}
stampRoom();
if(window.ResizeObserver&&$('#brand'))new ResizeObserver(stampRoom).observe($('#brand'));
addEventListener('resize',stampRoom,{passive:true});
// ---------- the light/dark choice, and the two topbar buttons ----------
/**
 * The element the chosen mode is written on, and the key it is remembered under.
 * One attribute is the whole authority: the CSS themes off it and `isDark` reads
 * it, so the stored value is copied onto the element rather than consulted twice.
 */
const root=document.documentElement, TK='audit-panel-theme';
// Applied before anything paints, and inside a try because reading storage can
// throw outright where it is blocked: a panel that cannot remember the choice
// must still open in the default one.
const s=storageGet(TK);if(s)root.setAttribute('data-theme',s);
// `isDark()` is `shared/theme.js`'s, concatenated ahead of this part. The panel
// carried its own for as long as the report carried another, and the two differed
// on whether `matchMedia` is guarded — see that file.
/**
 * Put the mode the button would switch TO on its face — a sun while dark is on,
 * a moon while it is not — because a control should say what pressing it does.
 *
 * @returns {string} the glyph it wrote; that is the assignment's value, and no
 *   caller reads it
 */
const paint=()=>$('#theme').textContent=isDark()?'☀':'☾';paint();
// The choice is written on the root element first, so everything reading the
// attribute agrees before anything repaints.
$('#theme').onclick=()=>{const n=isDark()?'light':'dark';root.setAttribute('data-theme',n);
 // The Appearance tab's live preview is per-mode, so it has to be redrawn for
 // the mode just chosen. Called unguarded: `tPaint` is a top-level `function` in
 // theme-state.js, and hoisting is per SCRIPT rather than per part, so it is
 // defined before this line can run — measured, not assumed. The `typeof` guard
 // that used to stand here read as a safety measure and was a branch that could
 // not be taken; the failure it named (a part missing from the join) is caught
 // loudly by test__panel_ui.py instead, which is the better place for it — a
 // silent skip here would come up unthemed with nothing saying why.
 tPaint();
 storageSet(TK,n);paint();};
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
  toast('wrote '+plural((r.files||[]).length,'file'),'ok');
  if(win){win.location=url('/report');}
  else{
   // Blocked anyway: leave a link rather than a button that did nothing.
   const a=$('#replink')||el('a',{id:'replink',class:'lnk',target:'_blank',rel:'noopener'},'open report ↗');
   a.href=url('/report');if(!a.parentNode)b.parentNode.insertBefore(a,b.nextSibling);}
 }catch(err){if(win)win.close();toast('render failed: '+err,'err');}
 finally{b.disabled=false;b.textContent=was;}};
// tabs
/**
 * The manifest's machine vocabulary in the words a reader gets, keyed by the
 * stored value.
 *
 * Substituted at import from `_ui_theme.LABELS`, which the report and the CLI
 * read too, so the three surfaces cannot drift into naming one state three ways.
 */
const LABELS=__LABELS__;
/**
 * The reader's word for a stored value.
 *
 * The manifest's vocabulary is machine-facing: `in_progress` sorts, compares and
 * survives serialization. It is not a thing to show anyone, and it was leaking
 * into every status pill, every filter button and every phase row. The machine
 * value stays in data-status — the CSS themes off it, the filters compare it —
 * and only the text changes here.
 *
 * A value the shared table does not name is humanised in place rather than shown
 * raw, so a state added to the manifest before it is added to the table still
 * reads as words.
 *
 * @param {string|null|undefined} v - a stored value, e.g. 'in_progress'
 * @returns {string} the shared label, the humanised value, or the em dash every
 *   other empty cell uses when there is no value at all
 */
const label=v=>LABELS[v]||(v?String(v).replace(/[_-]+/g,' ').replace(/^./,c=>c.toUpperCase()):'—');
/**
 * The ledger's storage key for spend with no phase or task behind it — ad-hoc
 * edits, `#no-plan`, sessions outside the plan.
 *
 * That is an answer, and it used to reach the screen as those two characters.
 * The shared label table names it, and the element builder below paints it in the
 * warn role: not a gate, not a finding, just the one row in a table a reader
 * should be able to find without hunting.
 */
const UNCAT='--';
/**
 * Whether a usage key is the uncategorised bucket, under either of its names.
 *
 * TWO storage keys, one fact: the group dimensions (phase/task/branch) write
 * "--" for a row with none, and the attr dimension writes "unattributed" for the
 * same spend seen from the other side. A reader meets one thing, so they get one
 * word.
 *
 * Deliberately a two-key predicate rather than the label table over any key: that
 * table humanises whatever it does not know, and "claude-opus-5" is not something
 * to prettify.
 *
 * @param {string} k - a storage key from a usage row
 * @returns {boolean} true for either spelling of "no phase, no task"
 */
const isUncat=k=>k===UNCAT||k==='unattributed';
/** Why that row exists, for the tooltip wherever its label is shown. */
const UNCAT_WHY='spend with no phase or task behind it - ad-hoc edits, #no-plan, '
 +'or sessions outside the plan. Counted, never hidden.';
/**
 * A usage key as text, with the empty bucket named instead of printed as its
 * storage key.
 *
 * @param {string} k - a storage key from a usage row
 * @returns {string} the shared label for the empty bucket, otherwise `k` itself
 */
const uKey=k=>isUncat(k)?label(UNCAT):k;
/**
 * The same key as something to put in a cell: the empty bucket carries its own
 * class and the explanatory tooltip, every other key stays plain text.
 *
 * The two branches return different KINDS on purpose — an ordinary key needs no
 * element unless a class was asked for, and the builder takes a string child as
 * readily as a node.
 *
 * @param {string} k - a storage key from a usage row
 * @param {string} [cls] - an extra class for the wrapper
 * @returns {HTMLSpanElement|string} a span for the empty bucket, or when `cls`
 *   asks for one; otherwise the key as text
 */
const uKeyEl=(k,cls)=>isUncat(k)
 ?el('span',{class:'uncat'+(cls?' '+cls:''),title:UNCAT_WHY},label(UNCAT))
 :(cls?el('span',{class:cls},String(k)):String(k));
/**
 * Every view, where the reader last was in each, and which one is showing.
 *
 * These ids are three things at once: the element ids in `panel.html`, the
 * `data-t` values on the tab buttons, and the names a `#/<tab>` link uses — so
 * renaming one breaks a link somebody saved.
 */
// ---------- tabs, the toast, and where the reader was ----------
// IN NAV ORDER, and that is now load-bearing rather than incidental: the first
// entry IS the panel's landing view and the fallback for an unrecognised
// fragment, so this tuple and the strip in panel.html are one order, not two
// hand-kept ones. Overview leads because the common visit is "where are we",
// not "I am changing config" - Settings was first only because it was built
// first.
const TABS=['over','comp','usage','policy','props','guards','look'],SCROLL={};
let CURTAB=null;
/**
 * Show one view, hide the rest, and put the reader back where they were in it.
 *
 * Views are addressable and each remembers its own offset. Every switch used to
 * slam the page back to the top while the URL never changed: a long Composition
 * table lost your place the moment you glanced at Usage, there was no way to link
 * anyone to a tab, and a reload always landed on Guards.
 *
 * An unrecognised name falls back to the first view rather than hiding all of
 * them, so a hand-typed or stale fragment cannot leave a blank page.
 *
 * @param {string} t - a view id; anything else becomes 'guards'
 * @param {boolean} [push] - false to route WITHOUT rewriting the fragment, which
 *   is what the hashchange listener passes so it cannot answer itself
 * @returns {void}
 */
function showTab(t,push){
 if(!TABS.includes(t))t=TABS[0];
 closeCombo();   // the menu is on <body>, not in the view being hidden
 if(CURTAB)SCROLL[CURTAB]=window.scrollY;
 CURTAB=t;
 document.querySelectorAll('.tab').forEach(x=>{const on=x.dataset.t===t;x.classList.toggle('on',on);
  // Colour alone does not say which view you are in — a screen reader gets nothing
  // from a background change, and these are exclusive views, not filters.
  if(on)x.setAttribute('aria-current','true');else x.removeAttribute('aria-current');});
 for(const id of TABS)$('#'+id).classList.toggle('hidden',id!==t);
 // The tab writer carries the usage-filter fragment with it, so switching views
 // does not throw away a filtered link somebody is about to copy.
 if(push!==false){const uf=uFragment();const h='#/'+t+(uf?'!'+uf:'');
  if(location.hash!==h)history.replaceState(null,'',h);}
 storageSet('audit-panel-tab',t);
 // After the browser has laid the view out, not before it.
 requestAnimationFrame(()=>window.scrollTo({top:SCROLL[t]||0,behavior:'auto'}));}
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>showTab(t.dataset.t));
/**
 * Mark the tab strip while it is really scrolling, so the CSS can show that
 * there is more of it than fits.
 *
 * Measured, not assumed. Below the shell breakpoint the views become one
 * horizontal strip, and on a phone the last of them sits off the right-hand edge
 * with nothing to suggest it exists. A media query cannot say whether the strip
 * overflowed; comparing the two widths can.
 *
 * @returns {void}
 */
function tabsOverflow(){const n=document.querySelector('.tabs');
 if(n)n.classList.toggle('scrolls',n.scrollWidth>n.clientWidth+1);}
addEventListener('resize',tabsOverflow);tabsOverflow();
// Both readers split on the FIRST '!': the fragment behind it is the usage
// filters' (fp), and `#/usage!m=opus` has to route like `#/usage` did.
addEventListener('hashchange',()=>{const t=(location.hash||'').replace(/^#\/?/,'').split('!')[0];
 if(TABS.includes(t)&&t!==CURTAB)showTab(t,false);});
/**
 * Which view to open on: the fragment first, because a link somebody sent is an
 * instruction; then the view this browser was last on; then Guards.
 *
 * @returns {string} one of the view ids, never anything else
 */
function initialTab(){const h=(location.hash||'').replace(/^#\/?/,'').split('!')[0];
 if(TABS.includes(h))return h;
 const s=storageGet('audit-panel-tab');if(TABS.includes(s))return s;
 // The first view, whatever it is. This was briefly a conditional - Overview when
 // no plan existed, Settings otherwise - and reordering the strip absorbed it: if
 // Overview leads because "where are we" is the common visit, that is as true of a
 // populated repo as of an empty one, and a landing that disagreed with the top of
 // the list would be its own surprise. Only the DEFAULT is decided here; an
 // explicit fragment is an instruction somebody sent and a remembered tab is this
 // reader's own choice, and both are answered above.
 return TABS[0];}
/**
 * The one transient banner, for an outcome nobody has to act on.
 *
 * Anything a reader may need to read twice — a refusal, a list of findings —
 * belongs in the save-note card below instead, which has no timer. This one's
 * lifetime is pinned: the screenshot gate's no-toast budget and its content
 * checks are calibrated against the value written here.
 *
 * @param {string} msg - the sentence to show
 * @param {'ok'|'err'|'warn'} [kind] - the role colour; neutral when omitted
 * @returns {void}
 */
function toast(msg,kind){const t=$('#toast');t.textContent=msg;t.className='show '+(kind||'');
 setTimeout(()=>t.className=t.className.replace('show','').trim(),2600);}
/**
 * Run each step, containing a failure to the step that caused it.
 *
 * THE RULE, not caution: the views and the live pollers are INDEPENDENT of one
 * another, and `boot()` used to run them as one sequence of bare calls. A throw
 * in any of them - a malformed ledger reaching renderUsage is the realistic one -
 * skipped every later view, the initial tab, the run poller and the tip
 * placement, and then the outer `boot().catch` reported "load failed" about a
 * load that had already succeeded. One broken view cost the whole panel and
 * misnamed the cause on the way out.
 *
 * The names come back rather than being reported from here, because WHO needs to
 * hear about it is the caller's question and not this function's.
 *
 * A step is named by its own identifier, so a caller passes NAMED functions; an
 * inline arrow has no name and would report as nothing at all, which is why the
 * one step boot() has to wrap is a named const. An unnamed step is reported as
 * `(anonymous)` rather than silently as an empty entry - it is a wiring mistake,
 * and a blank in a list of failures is the kind of thing a reader reads past.
 *
 * @param {Function[]} steps - each called with no arguments, in the order given
 * @returns {string[]} the names of the steps that threw, in the order they threw
 */
function runContained(steps){
 const broke=[];
 for(const step of steps){
  try{step();}
  catch(cause){const name=step.name||'(anonymous)';broke.push(name);
   console.error('panel step failed: '+name,cause);}}
 return broke;}
/**
 * One row of column headers, from a list of columns.
 *
 * Fifteen sites across eleven parts hand-nested `el('th',...)` from a list of
 * labels, and this is the row the SCOUT found rather than a reader: five agents
 * read the whole panel and none reported it, because each copy is short enough
 * to look like the cheapest thing available.
 *
 * A column is one of three things and no more, which is the point — a helper
 * that grew an optional field per caller would be the duplication again with
 * extra steps:
 *
 *   a STRING  — a plain header cell
 *   `null`    — an empty one, which every table with an action column needs
 *   an OBJECT — `{attrs, label, extra}`, where `attrs` goes to `el` verbatim
 *               rather than being re-listed here field by field
 *
 * Panel-only, so it lives here and not in `shared/`: `el()` is the panel's
 * builder and the report has none — it assembles its tables with
 * `createElement`, which is a different job and not one to unify by adding a
 * parameter to this.
 *
 * ONE function, not a `headRow` and a `tableHead`. The row was briefly its own
 * helper for the single caller that had a `<thead>` already; giving that caller
 * the whole `<thead>` instead was smaller than keeping a seam for it.
 *
 * @param {Array<?string|{attrs: (Object|undefined), label: (*|undefined),
 *   extra: (*|undefined)}>} cols - one entry per column, in order
 * @returns {HTMLTableSectionElement} the `<thead>`, holding one row
 */
const tableHead=cols=>el('thead',{},el('tr',{},cols.map(c=>
 (c==null||typeof c==='string')?el('th',{},c)
 :el('th',c.attrs||{},c.label,c.extra))));
/**
 * Fill a `<select>` with options, marking the one currently chosen.
 *
 * Five sites spelled this out: build the option, set `selected` when its value is
 * the current one, append. `[value, label]` pairs rather than bare values because
 * the value is what a change handler reads while the label is only words, and one
 * caller has them deliberately different - the option's value stays the ledger's
 * own key because that is what the filter matches on, and only the words a reader
 * picks from are renamed.
 *
 * Three other option loops are NOT here and should not be: two decorate
 * individual options (a title naming an area's owner, a disabled state over the
 * chart's point cap) and one decides `selected` through a path normalisation. A
 * per-option callback would have made this carry every caller's private business,
 * which is the duplication back with extra steps.
 *
 * @param {HTMLSelectElement} sel - appended to; options already there stay
 * @param {Array<[*, string]>} pairs - [value, label], in the order to show
 * @param {*} cur - the chosen value, compared strictly, as each site compared it
 * @returns {HTMLSelectElement} `sel`, so a builder can return the call
 */
/**
 * The number a box's text spells, or null when it does not spell one.
 *
 * A ROUND TRIP, NOT A PARSE, and that is the whole content of this function.
 * `Number()` is far more generous than anyone typing into a box: `'0x10'` is
 * 16, `'1e3'` is 1000, `'4e2'` is 400 and `' 4 '` is 4 — so a bare `Number()`
 * stores a value nobody wrote, and stores it silently. Only a spelling that
 * comes back identical is taken as that number, which is what leaves `007`,
 * `1.0.0` and `4e2` the strings a reader plainly typed.
 *
 * `null` is the ONE answer for "not a number", distinct from `0` and from
 * `NaN`, both of which are values a caller may legitimately be holding.
 *
 * Two callers today and one rule: the ADO parent id box (which then asks for a
 * positive integer) and the field-template value box (which keeps a number as a
 * number so a board requiring one is satisfied). It lives here rather than
 * beside either of them because a second copy would be a second answer about
 * what `4e2` means.
 *
 * @param {*} text - what a box holds; trimmed here so no caller has to
 * @returns {number|null} the number, or null when the text is not exactly one
 */
const typedNumber=text=>{
 const t=String(text==null?'':text).trim();
 if(t==='')return null;
 const n=Number(t);
 return (Number.isFinite(n)&&String(n)===t)?n:null;};
/**
 * What one option SHOWS, and the full text when that is not all of it.
 *
 * SEPARATE FROM `fillOptions` SO IT CAN BE TESTED. The test shim's `append` is a
 * no-op, so a select filled there has no children to inspect and a case asserting
 * the rendering would be asserting nothing. The rule is the part that can be wrong
 * without looking wrong, so the rule is what is reachable — the same arrangement
 * `apChoiceOf` / `apPatchValue` already use one file over.
 *
 * `title` is null when nothing was cut, so the attribute MEANS something when it
 * is there: a title on every option would make hovering one useless.
 *
 * @param {*} label - the option's full text
 * @param {number} [limit] - most characters it may show; omitted = no bound
 * @returns {{text: string, title: (string|null)}}
 */
const optionText=(label,limit)=>{
 const full=String(label==null?'':label);
 return (limit&&full.length>limit)
  ?{text:full.slice(0,limit-1)+'…',title:full}
  :{text:full,title:null};};
/**
 * Fill a `<select>`, optionally bounding what each option is allowed to SHOW.
 *
 * F211. A closed `<select>` renders one line and clips it — it does not wrap and
 * it does not ellipsise — so an option label longer than the control is a phrase
 * cut off mid-word. The composition table's parent picker is `width:9rem` and its
 * labels ran to `use the fallback — nothing is set (meta.ado.parentWorkItem is
 * empty)`, which the committed screenshot shows rendering as `use the fallback —`.
 * A substring pin cannot see it: the whole literal IS in the page, and only the
 * paint is wrong.
 *
 * THE BOUND IS A PARAMETER AND NOT A CONSTANT HERE, because it is a property of
 * the CONTROL and this function fills every select in the panel — the usage
 * filters and the model pickers are wider, and a single global bound would
 * truncate labels that already fit. A caller that knows its width passes one; a
 * caller that does not passes nothing and nothing changes for it.
 *
 * THE FULL TEXT IS NOT LOST, it moves to the option's `title`. Truncating without
 * that would trade a clipped label for a shortened one, which is the same defect
 * with better manners — and for a board candidate the part that gets cut is the
 * work item's title, the part a person is choosing BY.
 *
 * @param {HTMLSelectElement} sel - the select to fill
 * @param {Array<[string, string]>} pairs - [value, label]
 * @param {string} cur - the value to select
 * @param {number} [limit] - most characters an option may show; omitted = no bound
 * @returns {HTMLSelectElement} `sel`
 */
const fillOptions=(sel,pairs,cur,limit)=>{
 pairs.forEach(([v,t])=>{
  const {text,title}=optionText(t,limit);
  const o=el('option',title?{value:v,title}:{value:v},text);
  if(cur===v)o.selected=true;sel.append(o);});
 return sel;};
/** How long a plain success stays in a savebar's note slot before it dissolves. */
const SAVE_NOTE_MS=5000;
/**
 * The card that says what happened to a save, for the note slot above a savebar.
 *
 * Three outcomes and three lifetimes, and the difference between them is the
 * point: a refusal stays until it is dismissed or until the next Save or Discard
 * replaces the slot, warnings persist the same way, and a plain success dissolves
 * on its own. "✓ saved" used to sit in the slot for the rest of the session,
 * indistinguishable from a save that had just landed.
 *
 * @param {{ok: boolean, locked: (boolean|undefined), findings: (string[]|undefined), warnings: (string[]|undefined)}} res -
 *   what a write endpoint answered
 * @returns {HTMLDivElement} the card, which is empty when there is nothing to say
 */
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
