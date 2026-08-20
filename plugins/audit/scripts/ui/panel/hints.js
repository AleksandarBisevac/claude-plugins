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
  // A focusable element with no role and no name announces NOTHING, and eleven
  // of these were in the tab order doing exactly that (SC 4.1.2, F42). It is
  // deliberately NOT a <button>: there is no drawer behind a ref-less hint, and
  // a button that opens nothing is a worse lie than a missing name.
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
// the first two failures is the argument for it. Absolute (0.34) lived inside
// `table.comp thead th` — a sticky z-index:1 stacking context inside
// .comptblwrap's scroll frame — where a live repo found it painted under the
// model column, and where merely SHOWING it grew the frame's scrollable
// overflow: hover an ⓘ, get scrollbars. Fixed-as-pseudo (early 0.35) escaped
// the frame but still lived in the th, one transformed/filtered/containing
// ancestor from silently demoting back to absolute. A node on <body> has no
// ancestor to be trapped, clipped, restacked or resized by — and nothing exists
// at all until showTip() runs, so a tip can no longer affect ANY box's size,
// hovered or not. The pre-computed-placement machinery (per-hint custom
// properties, the synchronous observer, the before-paint microtask dance) is
// deleted with the failure class that required it: geometry is computed from
// the icon's live rect at show time, height MEASURED rather than estimated,
// and both chart tooltips (tipMove) and the combo menu already work this way.
//
// TIPW is a border-box width (the #hinttip rule restates box-sizing) and the
// clamp is the width: no second cap to disagree with it by a scrollbar.
const TIPW=272, TIPGUT=12;
let TIPFOR=null,TIPVIA='mouse';
function tipbox(){let b=document.getElementById('hinttip');
 if(!b){b=el('div',{id:'hinttip',role:'tooltip'});document.body.append(b);}
 return b;}
// `via` is what closes it. A pointer tip dies the moment the pointer rests on
// anything else — including the SYNTHETIC mouseover Chromium dispatches after a
// scroll moves new content under a stationary cursor, which is correct: the
// pointer is no longer on the icon. A focus tip ignores where the mouse happens
// to be parked (a keyboard user's tooltip must not close because content
// scrolled under an idle pointer) and closes on focusout instead.
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
function hideTip(){const b=document.getElementById('hinttip');
 if(b)b.style.display='none';TIPFOR=null;TIPVIA='mouse';}
// Delegated on the document: a hint that arrives with a re-render needs no
// per-node listener, and there is nothing to pre-place — a tip that is not
// shown does not exist. Scroll re-anchors an open tip to its icon's new rect
// (capture: the comp table scrolls inside its own frame); a re-render that
// replaces the icon under an open tip disconnects it, and the observer hides
// the tip rather than leaving it orphaned over a node that no longer exists.
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
// `forId` exists for the same reason klabel's does (F26): when this sits inside
// a <label>, the ⓘ is a labelable <button> and its text joins the field's
// accessible name. Where the wrapper holds TWO fields the pollution lands in
// the MIDDLE of the name -- "Provenance tag i no provenance tag at all no tag"
// against a visible "Provenance tag ... no tag" -- and SC 2.5.3 fails outright.
// Pass forId and the wrapper becomes a <span>, binding by `for` instead.
function flabel(text,tip,ref,forId){return el('span',{class:'lbl'},
 forId?el('label',{for:forId},text):text,hint(tip,ref,text));}
function h2h(text,tip,ref){return el('h2',{},text,hint(tip,ref,text));}
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
// The i is a <button>, and a <button> is a LABELABLE element -- so while it sat
// INSIDE the <label>, the label named IT and not the field: HTML resolves a
// label's control to its FIRST labelable descendant, and the button got there
// first. MEASURED in Chromium at b586fe7, not read off the source: 20 fields on
// Guards bound no label at all (`el.labels.length === 0`) and announced their own
// VALUE -- "docs/audit/audit-plan.json" where "The plan" was meant, "80" where
// "Free first touch, in lines" was, and three <select> announced nothing at all,
// which is SC 4.1.2 as well as 1.3.1 and 3.3.2. The six checkboxes that DID bind
// folded the i's own name in: "Meter token usage usage.enabled What is Meter
// token usage?".
//
// So the <label> holds the words and points at the field by id, and the i is its
// SIBLING -- beside the words on screen, outside the name in the tree. `closest
// ('label')` cannot see any of this, which is why it was measured with `labels`.
function klabel(text,key,tip,forId){return el('span',{class:'lbl'},
 el('label',forId?{for:forId}:{},text,el('code',{class:'k2'},key)),
 hint(tip,{path:key,doc:'config',label:text}));}

