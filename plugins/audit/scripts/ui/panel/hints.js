// ---------- shared: the substituted tables, and the ⓘ hint ----------
/**
 * The form's shape, its microcopy and its enum choices, all substituted at import
 * from `_panel_settings.py` (`SETTINGS_GROUPS`, `FIELD_HELP`, `COMPOSITION_HELP`,
 * `_cfg_enums`).
 *
 * They used to be a JS literal here, which is how the form came to cover only part
 * of the config while nothing said so: the set of settings the panel could edit was
 * whatever someone had remembered to type. Derived from Python, a setting the schema
 * knows and this form does not is a build failure rather than a silent gap.
 *
 * The help table is keyed by dotted config path; the composition table covers the
 * manifest levers the Composition tab edits, which are not config paths at all.
 */
const SETTINGS=__SETTINGS__, HELP=__FIELD_HELP__, MDESC=__COMP_HELP__, ENUMS=__CFG_ENUMS__;
/**
 * The ⓘ beside a field: two depths in one control.
 *
 * Hovering or focusing it says what this box is for in the panel's own words;
 * pressing it opens the drawer, which adds what the SCHEMA says, the type, the
 * enum, the default the hooks fall back to and the concept page behind it.
 *
 * `ref` decides whether there is a second depth at all, and therefore what this
 * even is: with a ref it is a real button, because a screen reader has to announce
 * something to press and because a focusable non-button inside a label toggles the
 * control it was explaining. Without one it is a span with a tab stop — a hint on
 * something the schemas do not document (a policy switch, a discovered capability)
 * must stay a tooltip rather than become a button that opens an empty page.
 *
 * No listener is attached here: the tip is opened by delegated listeners on the
 * document, so a hint that arrives with a re-render works without its author
 * remembering to wire anything.
 *
 * @param {string|null} t - the tooltip sentence; a hint with a ref may have none
 * @param {{path: (string|undefined), comp: (string|undefined), topic: (string|undefined), doc: (string|undefined), label: (string|undefined)}|null} ref -
 *   what the drawer should open on: a config path, a composition lever, or a
 *   concept page. Null for a tooltip-only hint
 * @param {string} [name] - what this hint explains, for the accessible name of the
 *   ref-less form. It must be the words BESIDE the ⓘ: a name built from the tooltip
 *   text reads well and fails SC 2.5.3, because the visible label is not in it
 * @returns {HTMLButtonElement|HTMLSpanElement|null} the control, or null when there
 *   is neither a tooltip nor a ref — nothing to say, so nothing in the tab order
 */
function hint(t,ref,name){if(!t&&!ref)return null;
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
 else{h.tabIndex=0;
  // A focusable element with no role and no name announces NOTHING, and eleven of
  // these were in the tab order doing exactly that (SC 4.1.2). It is deliberately
  // NOT a <button>: there is no drawer behind a ref-less hint, and a button that
  // opens nothing is a worse lie than a missing name.
  //
  // The name is the SAME SHAPE the ref branch uses, and that is not tidiness.
  // The first repair named it after the tooltip TEXT, which reads sensibly and
  // fails SC 2.5.3 on the spot: the words beside the ⓘ are the field's caption,
  // so a name built from anything else cannot contain them. The gate caught it —
  // nine controls — before it was committed. Naming it after what it explains
  // satisfies both criteria at once.
  if(name)h.setAttribute('aria-label','What is '+name+'?');}
 // No listener here on purpose — showTip/hideTip below are delegated on the
 // document, so a hint that arrives with a re-render is covered without its
 // author remembering to wire anything.
 return h;}
// ---------- where the ⓘ tip opens ----------
// One element on <body>, shown on demand — the third mechanism, and the shape of
// the first two failures is the argument for it. The first was absolute and lived
// inside `table.comp thead th` — a sticky z-index:1 stacking context inside
// .comptblwrap's scroll frame — where a live repo found it painted under the
// model column, and where merely SHOWING it grew the frame's scrollable
// overflow: hover an ⓘ, get scrollbars. The second was fixed-as-pseudo, which
// escaped the frame but still lived in the th, one transformed, filtered or
// containing ancestor away from silently demoting back to absolute. A node on
// <body> has no ancestor to be trapped, clipped, restacked or resized by — and
// nothing exists at all until a tip is shown, so a tip can no longer affect ANY
// box's size, hovered or not. The pre-computed-placement machinery (per-hint
// custom properties, the synchronous observer, the before-paint microtask dance)
// went with the failure class that required it: geometry is computed from the
// icon's live rect at show time, height MEASURED rather than estimated, and both
// chart tooltips (tipMove) and the combo menu already work this way.

/**
 * The tip's own width, and the margin it keeps from every viewport edge.
 *
 * A border-box width — the `#hinttip` rule restates box-sizing — and the clamp IS
 * the width, so there is no second cap that a scrollbar could make disagree with
 * it. Both are read by the geometry below and by nothing else.
 */
const TIPW=272, TIPGUT=12;
/**
 * Which hint the open tip belongs to, and what opened it.
 *
 * Both are null/'mouse' while no tip is showing. `TIPVIA` decides what CLOSES it,
 * which is not the same question for a pointer and for a keyboard.
 */
let TIPFOR=null,TIPVIA='mouse';
/**
 * The one tip element, created on first use.
 *
 * @returns {HTMLElement} the body-level tip node, reused for every hint
 */
function tipbox(){let b=document.getElementById('hinttip');
 if(!b){b=el('div',{id:'hinttip',role:'tooltip'});document.body.append(b);}
 return b;}
/**
 * Open the tip for one hint, placed against that hint's live rect.
 *
 * `via` is what CLOSES it. A pointer tip dies the moment the pointer rests on
 * anything else — including the SYNTHETIC mouseover Chromium dispatches after a
 * scroll moves new content under a stationary cursor, which is correct: the pointer
 * is no longer on the icon. A focus tip ignores where the mouse happens to be
 * parked, because a keyboard reader's tooltip must not close because content
 * scrolled under an idle cursor, and closes on focusout instead.
 *
 * The height is measured after the text is in, not estimated, which is what decides
 * whether the tip opens below the icon or above it. A hint with no tooltip text
 * closes any open tip rather than drawing an empty box.
 *
 * @param {Element} h - the hint whose tip this is; its tooltip text and its rect
 *   are both read off it here, so it must still be in the document
 * @param {'mouse'|'focus'} [via] - what opened it; the previous value is kept when
 *   this is a re-place after a scroll
 * @returns {void}
 */
function showTip(h,via){const t=(h.getAttribute('data-tip')||'').trim();
 if(!t){hideTip();return;}
 const b=tipbox();TIPFOR=h;TIPVIA=via||TIPVIA||'mouse';b.textContent=t;
 const r=h.getBoundingClientRect(),vw=document.documentElement.clientWidth,
   vh=document.documentElement.clientHeight,w=Math.min(TIPW,vw-2*TIPGUT);
 b.style.width=w+'px';b.style.display='block';
 b.style.left=Math.min(Math.max(TIPGUT,r.left),vw-TIPGUT-w)+'px';
 // Below the icon where the MEASURED height fits, above it where it does not —
 // a savebar hint must not open off the bottom edge, and measuring beats the
 // 220px estimate this replaced the moment a long microcopy shipped.
 const mh=b.offsetHeight;
 b.style.top=((r.bottom+6+mh>vh-TIPGUT&&r.top-6-mh>TIPGUT)
   ?r.top-6-mh:r.bottom+6)+'px';}
/**
 * Hide the tip and forget whose it was. Safe to call when nothing is open.
 *
 * @returns {void}
 */
function hideTip(){const b=document.getElementById('hinttip');
 if(b)b.style.display='none';TIPFOR=null;TIPVIA='mouse';}
/**
 * Wire every hint on the page, present and future, once.
 *
 * Delegated on the document: a hint that arrives with a re-render needs no per-node
 * listener, and there is nothing to pre-place — a tip that is not shown does not
 * exist. Scroll re-anchors an open tip to its icon's new rect, in the capture phase
 * because the composition table scrolls inside its own frame rather than the page.
 * A re-render that replaces the icon under an open tip disconnects that icon, and
 * the observer hides the tip rather than leaving it orphaned over a node that is no
 * longer there.
 *
 * Called once, from the boot sequence. Calling it twice would double every listener.
 *
 * @returns {void}
 */
function startTipPlacement(){
 document.addEventListener('mouseover',e=>{
  const h=e.target&&e.target.closest?e.target.closest('.hint'):null;
  if(h){if(h!==TIPFOR)showTip(h,'mouse');}
  else if(TIPFOR&&TIPVIA==='mouse')hideTip();});
 document.addEventListener('focusin',e=>{
  const h=e.target&&e.target.closest?e.target.closest('.hint'):null;
  if(h)showTip(h,'focus');else if(TIPFOR)hideTip();});
 document.addEventListener('focusout',()=>hideTip());
 ['scroll','resize'].forEach(ev=>addEventListener(ev,()=>{
  if(!TIPFOR)return;
  TIPFOR.isConnected?showTip(TIPFOR):hideTip();},{capture:true,passive:true}));
 new MutationObserver(()=>{if(TIPFOR&&!TIPFOR.isConnected)hideTip();})
  .observe(document.body,{childList:true,subtree:true});}
/**
 * A field's caption row: the words a reader sees, and the ⓘ beside them.
 *
 * `forId` exists for the same reason klabel's does. When this row sits inside a
 * <label>, the ⓘ is a labelable element and its text joins the field's accessible
 * name; where the wrapper holds TWO fields the pollution lands in the MIDDLE of the
 * name -- "Provenance tag i no provenance tag at all no tag" against a visible
 * "Provenance tag ... no tag" -- and SC 2.5.3 fails outright. Given forId, the row
 * puts the words in a <label> that binds by id, and the ⓘ stays its sibling: beside
 * the words on screen, outside the name in the tree.
 *
 * @param {string} text - the caption, which is also what the ⓘ says it explains
 * @param {string|null} tip - the tooltip sentence, or null for a hint that only
 *   opens the drawer
 * @param {{path: (string|undefined), comp: (string|undefined), topic: (string|undefined), doc: (string|undefined), label: (string|undefined)}|null} ref -
 *   what the drawer opens on, or null for a tooltip-only hint
 * @param {string} [forId] - id of the field these words label. Pass it whenever
 *   this row captions a control; without it the words are bare text and the row
 *   must not be placed inside a label of its own
 * @returns {HTMLSpanElement} the caption row
 */
function flabel(text,tip,ref,forId){return el('span',{class:'lbl'},
 forId?el('label',{for:forId},text):text,hint(tip,ref,text));}
/**
 * A section heading that carries its own ⓘ.
 *
 * @param {string} text - the heading
 * @param {string|null} tip - the tooltip sentence, or null
 * @param {{path: (string|undefined), comp: (string|undefined), topic: (string|undefined), doc: (string|undefined), label: (string|undefined)}|null} ref -
 *   what the drawer opens on, or null
 * @returns {HTMLHeadingElement} the heading, hint included
 */
function h2h(text,tip,ref){return el('h2',{},text,hint(tip,ref,text));}
/**
 * A settings caption: the words a reader wants, with the JSON key beside them.
 *
 * Both audiences are real and they want different strings — "guardEdits.tokenVars"
 * tells you nothing about what the setting DOES, and "Secrets never written to
 * logs" cannot be typed into .claude/audit.config.json. The key keeps its own case
 * on purpose: the heading is uppercased by the CSS, and an uppercased camelCase key
 * is not merely shouted, it is WRONG, because config keys are case-sensitive and
 * copying one out of here would produce a setting that silently does nothing.
 *
 * The key is also the path the drawer looks the field up under, so every control in
 * this form gets its reference entry without a second list saying which ones have
 * one. A path the schema does not describe fails `_help`'s own coverage selftest, so
 * "the drawer opens on nothing" is a build failure rather than a dead ⓘ.
 *
 * WHY THE ⓘ IS A SIBLING OF THE LABEL AND NOT INSIDE IT. The ⓘ is a button, and a
 * button is a LABELABLE element -- so while it sat inside the label, the label named
 * IT and not the field: HTML resolves a label's control to its FIRST labelable
 * descendant, and the button got there first. MEASURED in Chromium at b586fe7, not
 * read off the source: 20 fields on Guards bound no label at all
 * (`el.labels.length === 0`) and announced their own VALUE --
 * "docs/audit/audit-plan.json" where "The plan" was meant, "80" where "Free first
 * touch, in lines" was, and three selects announced nothing at all, which is
 * SC 4.1.2 as well as 1.3.1 and 3.3.2. The six checkboxes that DID bind folded the
 * ⓘ's own name in: "Meter token usage usage.enabled What is Meter token usage?".
 * `closest` over the label cannot see any of this, which is why it was measured
 * through `labels`.
 *
 * @param {string} text - the words a reader sees
 * @param {string} key - the dotted config path, shown beside the words and used as
 *   the drawer's lookup path
 * @param {string|null} tip - the tooltip sentence, or null when the schema entry is
 *   the only thing worth saying
 * @param {string} [forId] - id of the field these words label; without it the label
 *   binds nothing, so pass it for every real control
 * @returns {HTMLSpanElement} the caption row
 */
function klabel(text,key,tip,forId){return el('span',{class:'lbl'},
 el('label',forId?{for:forId}:{},text,el('code',{class:'k2'},key)),
 hint(tip,{path:key,doc:'config',label:text}));}

