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

/**
 * The `GET /api/runstatus` payload: who holds the index lock, who holds each
 * phase lock or claim, the plan gate's current verdict, and the disk's change
 * stamp. Deliberately narrower than /api/state — see the note above.
 * @typedef {{
 *   index: ({hostname: (string|undefined), live: (boolean|undefined),
 *            liveBasis: (string|undefined), startedAt: (string|undefined)}|null),
 *   phases: Object<string, {lock: (object|undefined), claim: (object|undefined)}>,
 *   gate: ({mode: string, source: string, bypassArmed: (boolean|undefined),
 *           events: Array<{ts: string, event: string, file: string, reason: string}>}
 *          |undefined),
 *   fingerprint: (string|undefined)
 * }} RunStatus
 */

/**
 * THE POLL OWNS THESE THREE NAMES, and that is a constraint on callers rather
 * than a note about them: every 5s tick rewrites RUNSTATUS and can rewrite FP, so
 * a test or fixture that hand-assigns either is destroyed mid-check and goes red
 * once in N runs. Anything a check needs the panel to believe is installed at the
 * ENDPOINT instead, where the next poll re-serves it.
 *
 * `tools/capture-screenshots.mjs` enforces exactly that, and it derives the list
 * of owned names by reading the assignments out of pollRunStatus itself rather
 * than keeping its own copy — so a fourth polled global is covered the day it is
 * added, and renaming one of these does not quietly turn the guard off.
 *
 * `RUNSTATUS` is the last payload, `{RunStatus|null}`, null before the first
 * tick. `RUNPOLL` is the setInterval handle, `{number|null}`, so a restart can
 * clear the interval it replaces. `FP` is the disk change stamp this page has
 * already adopted, `{string|null}` — null means "not seen yet", which is why the
 * first sight of a stamp only seeds it and never triggers a refresh.
 */
let RUNSTATUS=null, RUNPOLL=null, FP=null;
/**
 * The part of a payload worth repainting for.
 *
 * The gate block IS in the key: a fresh gate event or a bypass arming repaints
 * Overview from the payload the poll already fetched. The fingerprint stays OUT,
 * because a moved disk stamp is handed off to refreshFromDisk instead — the poll
 * itself never refetches full state.
 * @param {RunStatus|null} rs - a payload, or null before the first tick
 * @returns {string} a JSON string to compare against the last one; 'null' for a
 *   missing payload, which is distinguishable from every real one
 */
function runStatusKey(rs){return JSON.stringify(rs&&{i:rs.index,p:rs.phases,g:rs.gate});}
/**
 * Whether a reader is mid-interaction, so a disk refresh must wait.
 *
 * The ledger's stamp moves after every Claude turn in the project, so without
 * this an open combo menu — or a field somebody had focused but not yet typed
 * into — was torn down every 5s under their hands. Deferring is safe because FP
 * stays put: the poll after the interaction ends picks the same change up.
 *
 * Scoped rather than blanket, and the scope is the point. A DIRTY form is never
 * rebuilt by the refresh (it keeps its edits and gets the stale note), so a caret
 * inside one defers nothing; Overview must keep refreshing while somebody types
 * in Composition. Only a caret in a form the refresh WOULD rebuild, or an open
 * menu anywhere, holds it back.
 * @returns {boolean} true to defer the refresh this tick
 */
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
/**
 * One tick: fetch the narrow payload, hand a moved disk stamp off, and repaint
 * Overview if — and only if — something a badge shows actually changed.
 *
 * It repaints Overview alone, and Overview has no inputs. Re-rendering from full
 * state would discard whatever is half-typed in the settings form, so the poll
 * path must never reach into a view that carries one; a selftest slices the
 * assembled page from this function to the Overview marker and asserts that.
 *
 * Assigns RUNSTATUS and FP, which it OWNS — see the note above their
 * declarations before writing either from anywhere else.
 * @returns {Promise<void>} resolves when the tick is done; a failed fetch
 *   resolves too, leaving a stale badge rather than killing the panel
 */
async function pollRunStatus(){
 if(document.hidden)return;
 try{
  const next=await api('GET','/api/runstatus');
  // The fingerprint is the disk's change stamp, and it deliberately does NOT
  // enter runStatusKey — the poll itself still never refetches full state. A
  // moved stamp hands off to refreshFromDisk (defined past the Overview
  // marker), which does. Deferred while any dialog is open — the browse table
  // holds references into the old USAGE.facts and a confirm is mid-decision —
  // and FP stays put, so the poll after the dialog closes picks the change up
  // rather than swallowing it.
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
/**
 * Start the 5s poll, replacing any interval already running.
 *
 * Idempotent on purpose: boot calls it, and so does anything that re-establishes
 * the session, so two live intervals would double the request rate on a
 * colleague's machine for the rest of the session.
 * @returns {void}
 */
function startRunPoll(){
 if(RUNPOLL)clearInterval(RUNPOLL);
 RUNPOLL=setInterval(pollRunStatus,5000);
}
// Coming back to the tab polls at once rather than waiting out the interval: the
// badges were frozen for as long as the tab was hidden, so the first thing a
// returning reader sees must not be up to 5s stale.
document.addEventListener('visibilitychange',()=>{if(!document.hidden)pollRunStatus();});
