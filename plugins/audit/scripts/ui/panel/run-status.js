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
let RUNSTATUS=null, RUNPOLL=null, FP=null;
// gt: the gate block IS in the key — a fresh gate event or a bypass arming
// repaints Overview from the payload the poll already fetched. The
// fingerprint stays OUT (it hands off to refreshFromDisk; the D9 rule).
function runStatusKey(rs){return JSON.stringify(rs&&{i:rs.index,p:rs.phases,g:rs.gate});}
// F-P-1b: a moved disk stamp re-renders every CLEAN view — and the ledger's
// stamp moves after every Claude turn in the project (the Stop hook meters
// it), so an open combo menu, or a field the reader had focused but not typed
// into yet, was torn down every <=5s under their hands. Deferred exactly like
// an open dialog: FP stays put and the poll after the interaction ends picks
// the change up. Scoped, not blanket: a DIRTY form is never rebuilt by the
// refresh (it keeps its edits and gets the stale note), so a caret inside one
// defers nothing — Overview must keep refreshing while someone types in
// Composition. Only a caret in a form the refresh WOULD rebuild, or an open
// menu anywhere, holds it back.
function interacting(){
 if(comboOpen())return true;
 const a=document.activeElement;
 if(!(a&&a.matches&&a.matches('input,textarea,select')))return false;
 // Only a caret in a form the refresh would REBUILD holds it back, and only
 // while that form is clean (a dirty one is left alone anyway, with the stale
 // note). A caret in Overview's or Usage's search box defers NOTHING: those are
 // filters, their state is hoisted out of the render on purpose, and a reader
 // who leaves the cursor in a search box must not freeze the live view for the
 // rest of the session — which is exactly what the first version of this did,
 // caught by the out-of-band write test one step later.
 const v=a.closest('#comp,#guards,#policy');
 return !!v&&editRows(v.id).length===0;}
async function pollRunStatus(){
 if(document.hidden)return;
 try{
  const next=await api('GET','/api/runstatus');
  // lv: the fingerprint is the disk's change stamp, and it deliberately does
  // NOT enter runStatusKey — the poll itself still never refetches full state
  // (the D9 rule). A moved stamp hands off to refreshFromDisk (defined past
  // the Overview marker), which does. Deferred while any dialog is open — the
  // browse table holds references into the old USAGE.facts and a confirm is
  // mid-decision — and FP stays put, so the poll after the dialog closes
  // picks the change up rather than swallowing it.
  const fp=next.fingerprint;
  if(fp&&fp!==FP){
   if(FP===null)FP=fp;
   else if(!document.querySelector('dialog[open]')&&!interacting()){FP=fp;refreshFromDisk();}
  }
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

