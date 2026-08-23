// SC 2.4.11 Focus Not Obscured (Minimum, AA): when a control takes focus, no
// part of it may be ENTIRELY hidden by author content. The browser scrolls a
// tabbed-to control just into view and stops -- which, with chrome pinned to an
// edge, lands it UNDERNEATH that chrome.
//
// MEASURED before this existed, driving real Tab presses rather than .focus():
// 85 of 942 focus stops across six tabs and two viewports were entirely covered
// -- 60 by `.top`, 13 by an open `.combo-menu`, 11 by `.savebar`, 1 by `.ufil`.
// Shift+Tab is far worse than Tab, because backwards traversal walks up into the
// header rather than down away from it.
//
// NOT `scroll-padding`, and the second reason is the one that decides it: it is
// absent from the Baseline snapshot (missing = treat as Limited), and it cannot
// touch the fixed `.combo-menu` at all, which is 13 of the 85. Measuring what is
// actually on top and moving the control clear covers every source at once, and
// needs no list of nested scrollers to keep up to date.
/**
 * Move a control that has just taken focus out from under any chrome pinned over
 * it, so no part of it is left entirely hidden (WCAG 2.2 SC 2.4.11).
 *
 * THE RULE THAT DECIDES HOW IT IS CALLED: this is registered at the foot of this
 * file inside its own try/catch, and that is a rule rather than caution - an
 * accessibility repair must never be the reason the panel fails to come up.
 * Nothing else on the page reads anything it produces, so a throw here costs
 * this one behaviour and the console line that names it, and boot() still runs.
 *
 * Every correction it makes is a scroll, or the closing of a stale dropdown. It
 * never moves, hides or re-parents the control that took focus, which is what
 * bounds a wrong correction to "still under the chrome" rather than to a control
 * the reader can no longer find.
 * @returns {void} It installs one `focusin` listener for the life of the page.
 *   Nothing removes it: there is no state to tear down, and a reader who has
 *   started tabbing does not stop.
 */
function keepFocusClear(){
 const GAP=8;
 // What is painted over this control at a point, when that thing is chrome
 // pinned to an edge. An ordinary sibling overlapping by accident is a
 // different defect and deliberately not this one's business.
 const pinnedOver=(n,x,y)=>{
  if(x<0||y<0||x>innerWidth-1||y>innerHeight-1)return null;
  const hit=document.elementFromPoint(x,y);
  if(!hit||hit===n||n.contains(hit)||hit.contains(n))return null;
  for(let p=hit;p&&p!==document.body;p=p.parentElement){
   const cs=getComputedStyle(p);
   if(cs.position==='fixed'||cs.position==='sticky')return p;}
  return null;};
 // The box whose scrolling actually changes where these two sit RELATIVE to each
 // other. Not simply the nearest scrolling ancestor: page-level chrome lives
 // outside the inner frames, so scrolling an inner frame moves the control
 // within it and not out from under `.top` at all. Measured -- a first version
 // took the nearest one and left 30 of 60 topbar cases untouched. The frame has
 // to CONTAIN the blocker for scrolling it to help; when none does, the page is
 // what moves.
 const mover=(n,over)=>{
  for(let p=n.parentElement;p&&p!==document.body;p=p.parentElement){
   const cs=getComputedStyle(p);
   if(/auto|scroll/.test(cs.overflowY)&&p.scrollHeight>p.clientHeight+2
      &&p.contains(over))return p;}
  return null;};
 document.addEventListener('focusin',e=>{
  const n=e.target;
  if(!n||!n.getClientRects||!n.getClientRects().length)return;
  // Two frames, not one: the browser's own scroll-into-view has to finish, or
  // this measures the position the control is leaving instead of the one it
  // lands on -- and then "corrects" a distance that no longer exists.
  requestAnimationFrame(()=>requestAnimationFrame(()=>{
   // The chrome STACKS -- a control freed from the page header can land under a
   // filter bar pinned inside its own frame -- so one correction settles one
   // layer.
   //
   // TERMINATION IS PROGRESS, NOT THE COUNT. The loop stops when a pass moves
   // nothing, which is the real answer to "is there more to do"; the ceiling
   // exists only so a layout that cannot be satisfied cannot spin. It is set
   // high enough not to be the binding constraint, because for a while it WAS:
   // measured against the same 72 failures, a ceiling of 3 left 10, 6 left 5,
   // 8 left 2, and 16 left none. A ceiling tuned until the number looks good is
   // a threshold on a proxy -- the honest fix was to stop letting it bind. In
   // practice almost every focus needs no pass at all and none needs many.
   for(let pass=0;pass<16;pass++){
    const r=n.getBoundingClientRect();
    if(!r.width||!r.height)return;
    const cx=r.left+r.width/2;
    const over=pinnedOver(n,cx,r.top+1)||pinnedOver(n,cx,r.top+r.height/2)
      ||pinnedOver(n,cx,r.bottom-1);
    if(!over)return;
    // An open dropdown is not chrome to scroll out from under -- it is STALE.
    // Tab walks past a combo's input and the menu stays up, then covers whatever
    // takes focus next; scrolling cannot help, because a fixed menu travels with
    // the viewport. Closing it is the right answer independently of 2.4.11: a
    // menu whose input no longer has focus has nothing to choose for.
    if(over.classList&&over.classList.contains('combo-menu')){
     // ...unless the menu BELONGS to the control that just took focus. This
     // handler runs on the very focus that OPENS it: two frames after the click
     // `render()` has already placed the menu against the input, so sampling the
     // input's own edges finds it, and `!over.contains(n)` is true because an
     // input is not inside its own menu. Without this test the guard closed the
     // menu the reader had just asked for - F90, which read as "the combo does
     // not open on the first click" and cost five wrong diagnoses. There is
     // nothing to correct in that case either: `place()` owns where a menu sits
     // relative to its own input, and scrolling to escape it would fight it.
     if(CMOWNER&&CMOWNER.inp===n)return;
     if(!over.contains(n)){closeCombo();continue;}}
    const c=over.getBoundingClientRect();
    // Which HALF of the viewport the chrome sits in, not how its edges compare
    // to the control's. Comparing edges gets a bottom bar backwards the moment
    // the control is fully underneath it -- the control's top is then BELOW the
    // bar's top, which reads as "chrome above" and scrolls the wrong way.
    // Measured: that single misreading left every savebar case unrepaired (11
    // before, 10 after) while the topbar cases fell 60 -> 10.
    const atTop=(c.top+c.bottom)/2<innerHeight/2;
    // The control has to travel DOWN out from under top chrome, UP out from
    // under bottom chrome; the page (or frame) moves the other way.
    const by=atTop?-(c.bottom-r.top+GAP):(r.bottom-c.top+GAP);
    if(!by)return;
    const box=mover(n,over);
    const was=box?box.scrollTop:(document.scrollingElement||document.documentElement).scrollTop;
    if(box)box.scrollBy(0,by);else scrollBy(0,by);
    const now=box?box.scrollTop:(document.scrollingElement||document.documentElement).scrollTop;
    // Nothing moved: this box is at its limit, and repeating the same scroll is
    // how a loop turns into a spin. Whatever is left is a layout problem, not a
    // scrolling one, and pretending otherwise would hide it.
    if(now===was)return;}}));});}

// Guarded, by the rule stated above keepFocusClear: the failure is logged and
// boot() runs anyway.
try{keepFocusClear();}
catch(cause){console.error('keepFocusClear failed',cause);}

boot().catch(e=>toast('load failed: '+e,'err'));
