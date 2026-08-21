// ---------- who is writing, what exactly, and whether it was recorded ----------
// Three questions the panel could not answer until now, and they are one flow: a
// save wrote whatever the form happened to hold, said "manifest saved", and left
// no trace of who did it or what changed. So: the topbar names you, Save shows the
// exact rows before it writes anything, the server echoes back what it really
// applied, and the journal (when this install has one) keeps the record.

/**
 * Name whoever is driving this panel, in the topbar.
 *
 * The name comes from the server, resolved by `usage_ledger.resolve_author` — the
 * same function and the same `usage.authorMode` that decide the `author` column
 * in the token ledger. That is what makes the Usage tab's "my spend" chip able to
 * filter on it: two ways of naming the same person would produce a filter that
 * silently matches nothing.
 *
 * Three answers, not two. A resolved name is shown as itself; `mode: none` is a
 * decision this project made, so it is stated as one and linked to the setting
 * that made it; anything else means the resolver could not answer, which earns
 * the same link and a different sentence. None of the three is a default
 * standing in for a missing basis.
 *
 * @returns {void} nothing; and nothing is drawn at all when the topbar slot is
 *   missing from the page, which is the defensive case rather than the narrow
 *   viewport — there the pill is still built and hidden by the CSS, which is why
 *   the confirm dialog repeats the name at the moment of the write
 */
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

/**
 * One abort controller per view id, so its edit listeners can be replaced rather
 * than added to.
 *
 * A re-render replaces a view's children but never the view element itself, so a
 * delegated listener added per render would stack up one more copy on every save.
 */
const VIEWAC={};
/**
 * Run `fn` now, and again after anything inside a view is edited.
 *
 * The listeners are delegated on the view element and registered under that
 * view's controller, which is aborted first — so wiring a view twice leaves one
 * set of listeners, not two. The callback is deferred to the next frame rather
 * than run inline: it reads the whole form, so it has to run after every handler
 * the edit itself triggers has finished writing to the draft.
 *
 * @param {string} id - id of the view element, which must exist
 * @param {() => void} fn - recomputes whatever depends on the form; called once
 *   immediately so the view is correct before anyone types
 * @returns {void}
 */
function onViewEdit(id,fn){
 if(VIEWAC[id])VIEWAC[id].abort();
 VIEWAC[id]=new AbortController();
 const opt={signal:VIEWAC[id].signal},run=()=>requestAnimationFrame(fn);
 ['input','change','click'].forEach(e=>$('#'+id).addEventListener(e,run,opt));
 fn();}

/**
 * Where each writable surface registers a way to ask it what is unsaved.
 *
 * Rows, not a boolean. A boolean answers "is something dirty"; three callers need
 * the ROWS — the confirm dialog lists them, Discard says how many are about to be
 * lost, and beforeunload only earns the right to interrupt a close when there
 * really are some.
 *
 * EMPTY, and every entry arrives when its view is wired. The keys are read off
 * the object, never off a list in the text — and the list that used to be here
 * proved that by going stale twice: it named three surfaces while four, then
 * five, registered. A partial enumeration reads as the whole set, so the
 * enumeration lives where it can fail — the registration cases in
 * test__panel_page.py, and the savebar census in tools/capture-screenshots.mjs,
 * which asks the LIVE page whether every view offering a Save has an entry here.
 *
 * A pre-declared `null` bought nothing either way: an unwired surface has
 * nothing unsaved, which is the same answer `editRows` gives for a missing key.
 *
 * @type {Object<string, () => Array<{target: string, field: string, from: *, to: *}>>}
 */
const EDITS={};
/**
 * What one surface has unsaved, asked of the surface itself.
 *
 * @param {string} k - a key of the registry above
 * @returns {Array<{target: string, field: string, from: *, to: *}>} the rows; an
 *   empty list for a surface that has not registered yet, and also for a surface
 *   whose own computation THREW — which reads as "nothing unsaved", the one
 *   direction this must not be wrong in, since it is what decides whether a close
 *   is interrupted
 */
function editRows(k){try{return (EDITS[k]?EDITS[k]():[])||[];}
 catch(cause){
  // NULL, not []. Every caller of this asks "is this surface clean", and an
  // empty list is the answer for CLEAN — so a throw used to make a surface with
  // unsaved edits indistinguishable from one with none. Three things then went
  // wrong at once and all three lose the reader's work: beforeunload declined to
  // interrupt the close, the 5s poll decided nobody was typing and tore the form
  // down, and Overview's refresh re-rendered a view it thought was clean.
  // `null` means "could not tell", and `surfaceDirty` treats it as dirty.
  console.error('editRows failed for '+k+'; treating it as dirty',cause);
  return null;}}

/**
 * Whether a surface has anything to lose — including "cannot tell".
 *
 * FAIL-SAFE, and the direction is the whole point: interrupting a close that did
 * not need interrupting costs one click, and not interrupting one that did costs
 * everything typed since the last save. `SECURITY.md`'s table says fail-open for
 * advisory paths and fail-loud for guards; this is a guard over the reader's own
 * work, so it errs toward keeping it.
 *
 * @param {string} k a key of EDITS
 * @returns {boolean} true when there are unsaved rows, or when reading failed
 */
function surfaceDirty(k){const r=editRows(k);return r===null||r.length>0;}
/**
 * Every unsaved row on every registered surface, in one list.
 *
 * @returns {Array<{target: string, field: string, from: *, to: *}>} the rows;
 *   empty when the panel is clean
 */
function dirtyRows(){return Object.keys(EDITS).reduce((a,k)=>a.concat(editRows(k)),[]);}
/**
 * Which VIEWS a disk refresh would leave alone, because they hold unsaved edits.
 *
 * Keyed by the view's container id, and that is NOT the same set as the registry
 * keys: the ADO card has an entry of its own but no container of its own - it
 * lives inside #comp - so its rows keep THAT view dirty.
 *
 * Asked in one place because both readers need the same answer. `refreshFromDisk`
 * decides from it which views to re-render, and `interacting()` decides from it
 * whether to defer the refresh at all. When the two spelled it separately they
 * disagreed about exactly this fold, and a caret resting in an untouched
 * Composition field then froze the live view for as long as the ADO card below it
 * was dirty - deferring a refresh that would have skipped #comp anyway.
 *
 * @returns {Object<string, boolean>} true for a view the refresh must not rebuild
 */
function dirtyViews(){return {guards:surfaceDirty('guards'),
 comp:surfaceDirty('comp')||surfaceDirty('ado'),
 policy:surfaceDirty('policy')};}
addEventListener('beforeunload',ev=>{
 // `some(surfaceDirty)` rather than `dirtyRows().length`: a surface whose rows
 // could not be computed counts as dirty, and its rows cannot appear in a list.
 if(!Object.keys(EDITS).some(surfaceDirty))return;   // never interrupt a clean close
 ev.preventDefault();ev.returnValue='';return '';});

// --- change rows: {target, field, from, to} -------------------------------------
// The same shape the server echoes back as `applied`, computed here from the form
// and there from the file. Values are compared through JSON so a skills list is
// compared by content, and undefined and null are the one thing they mean here:
// "no value".

/**
 * One value in the form both sides compare in: absent becomes null.
 *
 * @param {*} v - a value read off the form or off the state snapshot
 * @returns {*} `v`, or null when it was undefined
 */
const cfNorm=v=>v===undefined?null:v;
/**
 * Whether two values are the same CHANGE-wise.
 *
 * Compared through JSON, so a skills list is compared by content rather than by
 * identity — two arrays with the same members are not a change.
 *
 * @param {*} a - the value the file holds
 * @param {*} b - the value the form holds
 * @returns {boolean} true when there is nothing to write
 */
const cfSame=(a,b)=>JSON.stringify(cfNorm(a))===JSON.stringify(cfNorm(b));
/**
 * Build one change row.
 *
 * @param {string} target - what is being changed: 'meta', 'config', a phase id or
 *   a task id, and it is what the lock notice reads to name the phases at risk
 * @param {string} field - the field within that target, as the reader sees it
 * @param {*} from - the value the file holds
 * @param {*} to - the value about to be written
 * @returns {{target: string, field: string, from: *, to: *}} the row, with both
 *   values normalized so the dialog and the server's echo can be compared key for
 *   key
 */
const cfRow=(target,field,from,to)=>({target,field,from:cfNorm(from),to:cfNorm(to)});
/**
 * What a composition patch would change, read against the state snapshot.
 *
 * Field order matches the server's — `_META_FORM_KEYS`, then phases, then tasks
 * by `_TASK_KEYS` — so the dialog and the echo read as the same list rather than
 * as two lists.
 *
 * FORM keys, not every writable meta key: `meta.areas` and the ADO connector are
 * writable through their own endpoints and have no control on this form, so
 * computing a row for either would be the dialog describing an edit this form
 * cannot make. A phase or task the snapshot does not know is skipped for the same
 * reason — there is no "from" to show, so there is no honest row.
 *
 * @param {{meta: (Object<string, *>|undefined), phases: (Object<string, {reviewModel: *}>|undefined), tasks: (Object<string, {model: *, skills: *}>|undefined)}} patch -
 *   the patch this form would send
 * @returns {Array<{target: string, field: string, from: *, to: *}>} one row per
 *   real difference, in the server's field order; empty when nothing changed
 */
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
/**
 * Dotted leaf paths of a config object.
 *
 * A non-empty plain object is a branch; a list, an empty object and every scalar
 * are leaves. One row per PATH rather than per block, because "usage.bands.highUSD
 * changed" is a sentence somebody can check and "usage changed" is not.
 *
 * This mirrors `_flat_paths` in `_panel_write.py`, which is what the server
 * flattens with — the two have to agree on what a leaf is, or the dialog and the
 * echo would disagree about how many changes there were.
 *
 * @param {*} o - the object to flatten; anything that is not a plain object
 *   flattens to no leaves at all
 * @param {string} [pre] - path prefix for the recursion
 * @param {Object<string, *>} [out] - accumulator for the recursion
 * @returns {Object<string, *>} leaf value by dotted path
 */
function cfFlat(o,pre,out){out=out||{};
 if(o&&typeof o==='object'&&!Array.isArray(o))for(const k of Object.keys(o)){
  const p=pre?pre+'.'+k:k,v=o[k];
  if(v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).length)cfFlat(v,p,out);
  else out[p]=v;}
 return out;}
/**
 * What saving this config would change, path by path.
 *
 * @param {Object<string, *>} cfg - the config document the Guards form would write
 * @returns {Array<{target: 'config', field: string, from: *, to: *}>} one row per
 *   changed leaf, sorted by path; empty when nothing changed
 */
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
/**
 * What each dialog owes the caret when it closes.
 *
 * A WeakMap keyed by the dialog element, so a dialog that is dropped takes its
 * entry with it. The entry is set to null on close rather than deleted, because
 * whether the map HAS the key is also what keeps the close listener single.
 *
 * @type {WeakMap<HTMLDialogElement, {node: Element, sel: (string|null)}|null>}
 */
const DLGBACK=new WeakMap();
/**
 * Whether an attribute value is safe to write into a selector as a literal.
 *
 * A hook's VALUE joins the selector only when it can be quoted: most are short
 * identifiers, but the ⓘ carries a whole help sentence in its tip attribute, and
 * quoting free text into a selector is a syntax error waiting for its first
 * apostrophe.
 *
 * @param {string} v - the attribute value
 * @returns {boolean} true when it is short enough and holds no quote, backslash or
 *   closing bracket
 */
const selSafe=v=>v.length<=64&&!/["\\\]]/.test(v);
/**
 * Name an element so a rebuilt view can be searched for it again.
 *
 * The id when it has one, otherwise every data- hook it carries — which is why
 * behaviour reaches for those hooks rather than for styling classes.
 *
 * @param {Element|null} n - the element that holds the caret
 * @returns {string|null} a selector, or null when there is nothing nameable about
 *   it — an element with no id and no data- hook cannot be found again
 */
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
/**
 * Remember where the caret is, so a rebuild can hand it back.
 *
 * `within` scopes it both ways: a redraw of one view must not take the caret out
 * of another, and must not put it back into something that now belongs elsewhere.
 *
 * @param {string} [within] - selector for the view about to be rebuilt; when it is
 *   given, a caret outside that view is left alone
 * @returns {{node: Element, sel: (string|null), at: (number[]|null)}|null} what to
 *   restore — the node, a selector that survives the rebuild, and the caret offset
 *   inside the control — or null when there is nothing here to restore
 */
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
/**
 * Put the caret back where it was, and say whether it really got there.
 *
 * The surviving node is preferred; failing that, the remembered selector is
 * resolved against the rebuilt view. The caret offset is restored too, because
 * focus alone drops a reader who was mid-path back at offset 0.
 *
 * @param {{node: Element, sel: (string|null), at: (number[]|null|undefined)}|null} ref -
 *   what was remembered; a null ref is a no-op, not a failure to report, and an
 *   absent offset just means the opener had no caret to place
 * @returns {boolean} true only when the document AGREES the caret arrived — a
 *   control that has become unreachable accepts the call in silence
 */
/**
 * Put the caret back after a render replaced the element that held it.
 *
 * Four views spelled this: resolve the node, focus it, set the selection inside a
 * try, and otherwise fall back to the remembered reference. Two resolved by id
 * and two by selector, which is why the resolved NODE is the argument - passing
 * the id would have needed a second parameter to say which resolver to use.
 *
 * ONE call where there were two branches, and the behaviour is unchanged rather
 * than improved: each of those views keeps a reference only when it kept no
 * specific id, so a kept id that no longer resolves arrives here with a null
 * reference - and the fallback returns false on a null without touching
 * anything, which is exactly what the old `if` with no `else` did.
 *
 * Written without naming those two functions with their parentheses, because the
 * page's own selftest COUNTS both call sites and a comment is text like any
 * other. Third time today; the repair is always to reword, never to widen.
 *
 * @param {?Element} n - the control that held the caret, or null when there was
 *   none to keep or it is gone
 * @param {number} caret - where the caret sat inside it
 * @param {?Object} keepBack - the reference `focusKeep` returned, for the case
 *   where no specific control was kept
 * @returns {boolean} whether a control ended up focused
 */
/**
 * Ask a surface what it would write, refuse an empty save, and get consent.
 *
 * The three steps every Save begins with, in the same order, on all four writable
 * surfaces — and the only part of a save that IS the same on all four. What
 * follows differs completely: a different endpoint, a different payload, a
 * different re-render, so none of that is here.
 *
 * `rows` is asked here rather than passed, for the reason `discardButton` asks
 * again on the press: the form moves between renders, and confirming a list the
 * caller captured earlier would write something other than what is on screen.
 *
 * @param {{rows: function(): Array<Object>, title: string, scope: string,
 *   empty: string, note: string}} o - `empty` completes "nothing to save — …",
 *   `scope` is what the lock notice names, `note` says what file is touched
 * @returns {Promise<?Array<Object>>} the rows to write, or null when there was
 *   nothing to save or the reader declined — one answer for "do not proceed",
 *   because a caller has nothing different to do about the two
 */
async function confirmSave(o){
 const rows=o.rows();
 if(!rows.length){toast('nothing to save — '+o.empty);return null;}
 if(!await confirmChanges({title:o.title,rows:rows,scope:o.scope,
   verb:'Save '+plural(rows.length,'change'),note:o.note}))return null;
 return rows;}
/**
 * Paint what a write returned into a view's findings slot.
 *
 * @param {string} sel - the view container's selector, e.g. `'#comp'`
 * @param {Object} res - the write endpoint's answer
 * @returns {?Element} the slot, or null when the view has none rendered
 */
function showFindings(sel,res){
 const slot=$(sel+' .findings-slot');
 if(slot)slot.replaceChildren(findingsBox(res));
 return slot;}
/**
 * Paint it AND say what happened — the pair every save ends with.
 *
 * Split from `showFindings` rather than taking a flag, because the theme card
 * genuinely needs them apart: it paints before its re-render so that a REFUSAL is
 * readable on a path that returns without redrawing, and reports once, on
 * whichever slot survives. A boolean argument would have made one function serve
 * two shapes and told a reader nothing about why.
 *
 * @param {string} sel - the view container's selector
 * @param {Object} res - the write endpoint's answer
 * @param {Array<Object>} rows - the rows the dialog listed, for the applied-diff
 * @param {string} what - what was being written, for the refusal sentence
 * @returns {?Element} the slot
 */
function showWriteResult(sel,res,rows,what){
 const slot=showFindings(sel,res);
 saveOutcome(res,rows,what,slot);
 return slot;}
function restoreCaret(n,caret,keepBack){
 if(!n||!n.focus)return focusBack(keepBack);
 n.focus();
 // Guarded and TRIED: not every focusable control has a selection to set - a
 // <select> and a checkbox both throw - and any of these views may have kept one.
 if(n.setSelectionRange)try{n.setSelectionRange(caret,caret);}catch(cause){}
 return true;}
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
/**
 * Mark a control unavailable without taking it out of the tab order.
 *
 * UNAVAILABLE MUST NOT MEAN UNREACHABLE (WCAG 2.2 SC 2.4.3). `disabled` removes
 * the tab stop, so a reader who tabs to a Discard, presses it, and lands on the
 * rebuilt one has the caret taken to <body> and the next Tab restarts at the top
 * of the document. WAI-ARIA APG uses aria-disabled precisely so the control keeps
 * its place and its name and refuses the ACTIVATION instead. It costs one extra
 * tab stop per savebar; that is the trade, not an oversight.
 *
 * The refusal itself is not here — the platform enforces nothing about
 * aria-disabled, so it is enforced once, below, in the capture phase.
 *
 * @param {Element} n - the control
 * @param {boolean} off - true to mark it unavailable
 * @returns {Element} `n`, so the call can sit inside the expression that built it
 */
function offState(n,off){
 n.setAttribute('aria-disabled',off?'true':'false');
 return n;}
/**
 * The Discard control for one surface: dead while there is nothing to throw
 * away, saying how much when there is, and confirming before it does it.
 *
 * ONE OF THESE, not four. Every writable surface had its own copy of the same
 * eleven lines, and the four copies had already diverged in the way copies do:
 * the label was refreshed from the shared view listener in two of them, from a
 * bespoke set of card listeners on the ADO card (which cannot use the shared one
 * without aborting the composition form's), and once per render on the policy
 * view — correctly, since `pEdit` re-renders that view on every edit, so a
 * listener there would recompute what the render already did. Three mechanisms
 * for one rule, and none of them the part that actually varies.
 *
 * What genuinely differs per surface is the four fields below and nothing else.
 * `revert` is a function rather than a re-render name because the policy view
 * does not re-render to discard; it restores a draft and lets its own edit
 * plumbing repaint.
 *
 * The counting and the dead state are NOT parameters. A control that throws work
 * away must not be reachable by an idle click, and "Discard" alone does not tell
 * you whether pressing it costs you anything — so both are the helper's job, and
 * `refreshDiscard` is what a caller drives when the form changes under it.
 *
 * @param {{key: string, rows: function(): Array<Object>, title: string,
 *   note: string, toast: string, revert: function(): void}} o - `key` is the
 *   EDITS key and the `data-discard` hook; `rows` is asked afresh on every press
 *   because the form moves between renders
 * @returns {HTMLButtonElement} dead, until `refreshDiscard` is called with rows
 */
function discardButton(o){
 const b=el('button',{class:'btn small','data-discard':o.key,type:'button',
   onclick:async()=>{
   // Asked again here, never closed over: the count in the label is from the
   // last repaint, and what gets discarded has to be what the form holds NOW.
   const rows=o.rows();
   if(!rows.length)return;
   if(!await confirmChanges({title:o.title,rows:rows,danger:1,lock:false,
     verb:'Discard '+plural(rows.length,'change'),note:o.note}))return;
   o.revert();toast(o.toast);}},'Discard');
 return refreshDiscard(b,0);}
/**
 * Put a Discard control's count and dead state in step with the form.
 *
 * Split from `discardButton` because the two happen at different times: the
 * button is built once per render and this runs on every keystroke that reaches
 * the view.
 *
 * @param {HTMLButtonElement} b - the control `discardButton` returned
 * @param {number} n - how many unsaved rows the surface reports right now
 * @returns {HTMLButtonElement} `b`, so a builder can return the call
 */
function refreshDiscard(b,n){
 offState(b,!n);
 b.textContent=n?('Discard '+plural(n,'change')):'Discard';
 return b;}
/**
 * Say WHICH fields are unsaved, not just how many.
 *
 * F-P-15: the savebar counted ("Discard 1 change") and nothing on the form said
 * which of twenty-odd settings it meant. The count's basis existed - Discard
 * lists every row before anything is thrown away - but it was a click away, and
 * the Policy tab next door already marks its pending cells inline. Two surfaces
 * disagreeing about whether a claim shows its basis is the thing to fix.
 *
 * A CLASS and a WORD, not a colour alone: `pend` is the same name Policy uses
 * (`td.pend`, `.badge.pend`), and the badge means the mark survives forced
 * colours and does not ask the reader to distinguish two tints.
 *
 * Idempotent, because `onViewEdit` runs this on every keystroke that reaches the
 * view: the previous marks come off before the current ones go on.
 *
 * @param {string} viewId - the tab's element id, e.g. `guards`
 * @param {Array<{field: string}>} rows - what the surface reports as unsaved
 * @param {function(string): string} idOf - a row's field to its control's id
 * @returns {void}
 */
function markPending(viewId,rows,idOf){
 const root=$('#'+viewId);
 if(!root)return;
 [...root.querySelectorAll('.f.pend')].forEach(n=>n.classList.remove('pend'));
 [...root.querySelectorAll('[data-pendbadge]')].forEach(n=>n.remove());
 rows.forEach(r=>{
  const c=document.getElementById(idOf(r.field));
  const wrap=c&&c.closest?c.closest('.f'):null;
  if(!wrap||wrap.classList.contains('pend'))return;
  wrap.classList.add('pend');
  (wrap.firstElementChild||wrap).append(
    el('span',{class:'badge pend','data-pendbadge':'1'},'unsaved'));});}

// aria-disabled is a promise to assistive technology and the platform enforces
// none of it — unlike `disabled`, the browser still dispatches the click (and
// Enter/Space arrive as one). Kept here, once, in the capture phase: four handlers
// each re-checking their own emptiness would be four chances to disagree, and a
// control added later would inherit the promise without the refusal.
document.addEventListener('click',e=>{
 const n=e.target&&e.target.closest&&e.target.closest('[aria-disabled="true"]');
 if(n){e.preventDefault();e.stopPropagation();}},true);
/**
 * Open a modal dialog, and record what the caret is owed when it closes.
 *
 * EVERY dialog on this page opens through here — `.showModal()` is written exactly
 * once in this file and a selftest counts it, so a further dialog cannot be added
 * that quietly skips the restore.
 *
 * The close listener is wired once per element, not once per opening: these
 * dialogs are singletons, reused every time they are shown.
 *
 * @param {HTMLDialogElement} d - the dialog to show
 * @param {string} [sel] - a selector for the opener, when the caller knows a
 *   better one than the opener can name for itself
 * @returns {void}
 */
function dlgOpen(d,sel){
 if(!DLGBACK.has(d))d.addEventListener('close',()=>{
   const r=DLGBACK.get(d);DLGBACK.set(d,null);focusBack(r);});
 const a=document.activeElement;
 DLGBACK.set(d,{node:a,sel:sel||focusSel(a)});
 d.showModal();}

// --- the confirm dialog ---------------------------------------------------------
/** The one confirm dialog: built on first use, reused for every opening. */
let CFDLG=null;
/**
 * One side of a change row, as something a reader can check.
 *
 * Absent, empty-list and empty-string are three different values and the dialog
 * says so. Collapsing them into one "not set" made a real change read as a no-op —
 * "not set → not set" — which is precisely the row a reader would skim past.
 *
 * On a `skills` row null is not "not set" either: it is the explicit opt-out, the
 * one deliberate answer that value carries there, and it renders as one.
 *
 * @param {*} v - the value, already normalized so undefined cannot reach here
 * @param {'was'|'now'} cls - which side of the arrow this is
 * @param {string} field - the field name, because a null means something different
 *   on a `skills` row than anywhere else
 * @returns {HTMLSpanElement} the value, wearing the empty look where it is empty
 */
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
/**
 * Which phases a change list touches, so a lock notice can be about the phases
 * you are actually writing rather than about the manifest in general.
 *
 * A task id is mapped to its phase through the composition view rather than sliced
 * out of the string: task ids are the plan's to shape, not this file's to parse.
 *
 * @param {Array<{target: string}>} rows - the changes about to be written
 * @returns {string[]} the phase ids involved, each once; 'meta' and 'config' rows
 *   belong to no phase and are left out
 */
function cfTouched(rows){
 const byT={};((STATE.composition||{}).tasks||[]).forEach(t=>{byT[t.id]=t.phaseId;});
 const s=new Set();
 rows.forEach(r=>{if(r.target==='meta'||r.target==='config')return;
  s.add(byT[r.target]||r.target);});
 return [...s];}
/**
 * What the dialog can say about locks and runs elsewhere, and on what basis.
 *
 * Read from the live poll, not from the page-load snapshot: a dialog that says
 * "nothing is running" because nothing was running when the tab loaded is exactly
 * the reassurance this flow must not give. When the poll has never answered, the
 * snapshot is the fallback.
 *
 * Only a lock the server has positively reported dead is ignored. Anything else
 * counts as held, so an unconfirmed lock warns rather than reassures — the wrong
 * warning costs a reader one paragraph, and the wrong reassurance costs them the
 * write they were promised.
 *
 * @param {Array<{target: string}>} rows - the changes about to be written
 * @param {string} [scope] - the surface saving; only 'comp' has rows that name
 *   phases, so only it can compare them against what is running
 * @returns {{kind: 'warn'|'ok', text: string}|null} a warning when this write is
 *   going to be refused, a reassurance when something is running that these rows do
 *   not touch, and null when there is nothing to report
 */
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
 * Show the exact rows and wait for an answer.
 *
 * Resolves true only on the primary button; Esc, the backdrop, the × and Cancel all
 * resolve false, which is the point of using a native <dialog> — the focus trap,
 * the backdrop and Esc are the platform's rather than three hand-written listeners
 * that each forget one case.
 *
 * The promise settles exactly once whichever way the dialog leaves, so a caller
 * can await it and treat false as "do not write".
 *
 * @param {{title: string, rows: Array<{target: string, field: string, from: *, to: *}>, verb: string, scope: (string|undefined), note: (string|undefined), danger: (boolean|number|undefined), lock: (boolean|undefined)}} o -
 *   `verb` is the primary button's own words, and `note` the sentence under the
 *   list saying what will be written. A truthy `danger` puts the caret on Cancel
 *   and drops the author line, because a Discard writes nothing and naming an
 *   author would answer a question nobody asked. `lock:false` suppresses the lock
 *   notice for a write that cannot be refused by one.
 * @returns {Promise<boolean>} true only when the primary button was pressed
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
    tableHead(['what','field','change']),tb)));
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
/**
 * Whether what the server applied is what the dialog showed.
 *
 * @param {Array<{target: string, field: string, from: *, to: *}>} rows - what was
 *   shown before the write
 * @param {{ok: (boolean|undefined), applied: (Array<{target: string, field: string, from: *, to: *}>|undefined)}} res -
 *   the write endpoint's answer
 * @returns {{missing: number, extra: number, shown: number, applied: number}|null}
 *   the drift, or null in the two cases that are not drift: the two lists agree, or
 *   there is nothing to compare (a refusal, or a server that echoed no list)
 */
function appliedDiff(rows,res){
 if(!res||!res.ok||!Array.isArray(res.applied))return null;
 const key=r=>JSON.stringify([r.target,r.field,cfNorm(r.from),cfNorm(r.to)]);
 const mine=new Set(rows.map(key)),theirs=new Set(res.applied.map(key));
 const missing=[...mine].filter(k=>!theirs.has(k)).length;
 const extra=[...theirs].filter(k=>!mine.has(k)).length;
 return (missing||extra)?{missing,extra,shown:rows.length,
   applied:res.applied.length}:null;}
/**
 * Say what happened to a save: how many changes landed, and whether there is a
 * record of it.
 *
 * "not logged" is said only when a journal exists and refused the row — on an
 * install with no journal at all the clause is left off, rather than reporting the
 * absence of a feature as a failure of a save. A refusal and an unchanged save each
 * get their own sentence, because "nothing was written" and "nothing needed
 * writing" are not the same news.
 *
 * @param {{ok: (boolean|undefined), locked: (boolean|undefined), unchanged: (boolean|undefined), applied: (Array<Object>|undefined), journaled: (boolean|undefined), journaledWhy: (string|undefined)}} res -
 *   the write endpoint's answer
 * @param {Array<{target: string, field: string, from: *, to: *}>} rows - what the
 *   dialog showed, so the echo can be compared against it
 * @param {string} what - the thing that was being written, named for the refusal
 *   sentence ('the manifest', 'the config', 'the theme')
 * @param {Element|null} slot - where a drift note may be appended; null from a
 *   caller that has no slot yet, and the note is then simply not shown
 * @returns {void} It REPORTS; it does not answer. It used to hand back the drift,
 *   with `null` covering three unrelated outcomes — refused, unchanged, and saved
 *   exactly as shown — which no caller could tell apart and none of the seven
 *   read. A value that cannot be interpreted is a trap whose only guard is a
 *   comment saying so, and `appliedDiff` is right there for a caller that
 *   genuinely wants the drift.
 */
function saveOutcome(res,rows,what,slot){
 if(!res||!res.ok){
  toast(res&&res.locked?(what+' is locked — nothing was written')
    :('rejected — nothing was written'),'err');
  return;}
 if(res.unchanged){toast('nothing to save — no values changed');return;}
 const n=(res.applied||[]).length;
 const diff=appliedDiff(rows,res);
 const log=res.journaled?' · logged'
   :(res.journaledWhy==='failed'?' · NOT logged':'');
 toast('Saved · '+plural(n,'change')+log,diff?'warn':'ok');
 if(diff&&slot)slot.append(el('div',{class:'findings warn','data-cfdiff':'1'},
   'Saved, but not exactly what the dialog listed: '+diff.applied+' of the '
   +plural(diff.shown,'change shown was','changes shown were')+' applied'
   +(diff.extra?(', and '+plural(diff.extra,'other change was',
     'other changes were')):'')
   +'. The file moved between opening this view and saving — reload the panel to '
   +'see what it holds now.'));}

/**
 * The panel's whole start-up: fetch everything, render every view, put the reader
 * where they asked to be, and start the polls.
 *
 * Defined here because this is where the statement sat, and CALLED from the last
 * part — which is not a filing accident. It assigns state that later parts DECLARE,
 * and a top-level `let` is in TDZ until its own line has run, so calling this any
 * earlier would throw on the first of them.
 *
 * The order inside is load-bearing three times: the usage filters are restored
 * before the first Usage render, the theme baseline is captured before the
 * Appearance tab is drawn, and the tab is restored last, once every view has
 * content to scroll to.
 *
 * Two payloads are fetched WITHOUT a catch — the state and the registry — so a
 * server that cannot answer them leaves no views rather than half-populated ones.
 * Usage, policy and theme are each caught into null, because a view that can say
 * "no data" is better than a panel that will not open.
 *
 * @returns {Promise<void>} resolves once every view is drawn and the polls are
 *   running; it rejects when the state or registry request fails
 */
async function boot(){STATE=await api('GET','/api/state');REG=await api('GET','/api/registry');
 USAGE=await api('GET','/api/usage').catch(()=>null);BANDS=null;MITEMS=null;
 POLICY=await api('GET','/api/policy').catch(()=>null);PDRAFT=pClone(POLICY&&POLICY.stored);
 // The usage filters are restored BEFORE the first Usage render: the hash first
 // (a share link is an instruction somebody sent), this repo's stored filters
 // second, defaults last.
 {const h=location.hash||'',bang=h.indexOf('!');
  const got=bang>=0&&uApplyFragment(h.slice(bang+1));
  if(!got){const s=storageGet(UFSTORE);
   if(s)uApplyFragment(s);}}
 THEME=await api('GET','/api/theme').catch(()=>null);
 tCaptureBase();
 // Every one of these is contained - see runContained. Three calls rather than
 // one list because the ORDER between them is load-bearing: the initial tab is
 // restored once every view has content to scroll to, and RUNSTATUS is read by
 // the header the poller then keeps up to date.
 const broke=runContained([renderViewer,renderSettings,renderComp,renderOver,
   renderUsage,renderPolicy,renderProposals,renderAppearance]);
 const showInitialTab=()=>showTab(initialTab());
 broke.push(...runContained([showInitialTab]));
 RUNSTATUS=STATE.runStatus||null;FP=(RUNSTATUS||{}).fingerprint||null;
 broke.push(...runContained([startRunPoll,startTipPlacement]));
 // Named, not counted. A reader who can see WHICH part is missing knows what to
 // distrust on this page; a number would only say that something is.
 if(broke.length)toast('the panel is up, but these parts of it are not: '
   +broke.join(', ')+'. The console names the cause of each.','err');}
