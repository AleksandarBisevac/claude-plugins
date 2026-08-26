// ---------- Overview ----------
// The rollup arrives with tasks.byStatus, bugs.byStatus, areas and ready[] already
// computed, and this view used to drop all four on the floor: four grey total chips
// and a flat list of every phase. So the numbers you steer by — what is in
// progress, what is blocked, which bugs are open, what can start right now — were
// the numbers the panel had and would not show.
//
// The filter state lives OUT here for the same reason COMPF does: the 5s run-status
// poll repaints this view, so a filter held in the render closure would be wiped by
// a badge update the reader never asked for, five seconds after they set it.

// ---------- out-of-band change handling ----------
// Everything in this section must stay BELOW the Overview marker above, and a
// selftest holds it there: it slices the assembled page from pollRunStatus to that
// exact marker text and asserts the poll path never reaches into Settings. The full
// refetch lives out here, reached only through the fingerprint hand-off inside
// pollRunStatus — so moving either the marker or these functions across it silently
// changes what that assertion covers.
/**
 * Say, once, that the file moved under a form holding unsaved edits.
 *
 * Persistent rather than a toast: the reader may be mid-sentence and look up
 * minutes later, and the thing they need to know is still true. Idempotent, so
 * five disk changes during one edit leave one notice — a stack of identical
 * warnings reads as five different problems.
 * @param {'guards'|'comp'|'policy'} id - the view whose findings-slot gets the
 *   notice; a view with no slot on screen is a no-op
 * @returns {void}
 */
function staleNote(id){const slot=$('#'+id+' .findings-slot');
 if(!slot||slot.querySelector('[data-stale]'))return;
 slot.append(el('div',{class:'findings warn','data-stale':id},
  'The file changed on disk while this form holds unsaved edits. Save stays '
  +'safe — what was applied is echoed back and compared — and Discard now '
  +'reloads the file as it is on disk.'));}
/**
 * Re-read everything from disk and redraw the views that can be redrawn safely.
 *
 * Reached only from the poll's fingerprint hand-off — never on a timer — so by
 * the time it runs, the file really has changed. A clean view is re-rendered; a
 * dirty one keeps its edits and gets staleNote instead, because re-rendering it
 * would silently eat what somebody typed.
 *
 * Never rejects: a stale view beats a dead panel, so a failed read leaves the
 * page exactly as it was.
 * @returns {Promise<void>} resolves once the re-render is queued and the scroll
 *   position has been scheduled for restoration
 */
async function refreshFromDisk(fpBack){
 const y=window.scrollY;
 try{
  // Fetched into LOCALS, so nothing global has moved yet if this tick bails.
  const st=await api('GET','/api/state');
  const us=await api('GET','/api/usage').catch(()=>USAGE);
  const pol=await api('GET','/api/policy').catch(()=>null);
  // F90. The caller answered `interacting()` three round trips ago, and it
  // answers a question about a person who is free to change their mind inside
  // that window: whoever opened a combo menu while these were in flight had it
  // closed by `renderComp`, which opens with `closeCombo()`, on a decision
  // taken before they touched anything. The predicate was never wrong - it is
  // consulted at the wrong moment - so re-ask it HERE, where the answer is
  // about to be used. FP rewinds to what it was, which is the same promise the
  // dialog branch makes: the poll after the interaction lands this change
  // rather than swallowing it.
  if(interacting()){FP=fpBack;return;}
  // BEFORE the state swap, and that is this line's position rather than
  // dirtyViews' business: the registered closures compare each form against
  // STATE, so a swapped STATE would misjudge every open form. What counts as
  // dirty - and why an unreadable surface counts - belongs to dirtyViews.
  // It is read after the fetches for the same reason as the re-check above: a
  // form the reader dirtied while they were in flight is dirty NOW.
  const dirty=dirtyViews();
  STATE=st;USAGE=us;
  BANDS=null;MITEMS=null;
  renderViewer();
  // Only CLEAN views re-render: renderComp resets its patch and renderSettings
  // reclones cfg, so re-rendering a dirty one would eat the human's edits.
  // A dirty view keeps them and gets the persistent notice —
  // the applied-diff echo already covers the conflicting-save endgame.
  // The findings-slot NODES are carried across the re-render: an own save moves
  // the disk stamp too, and the refresh it triggers must not eat the "saved"
  // card whose 5s clock belongs to the node, or the refusal card someone has
  // not read yet.
  /**
   * Re-render one view while keeping whatever is in its findings slot.
   * @param {'guards'|'comp'|'policy'} id - the view's container id
   * @param {() => void} fn - that view's renderer, called for its side effect
   * @returns {void}
   */
  const reRender=(id,fn)=>{const slot=$('#'+id+' .findings-slot');
   const keep=slot?[...slot.childNodes]:[];
   fn();
   const s2=$('#'+id+' .findings-slot');
   if(s2&&keep.length)s2.append(...keep);};
  // Proposals first, and unconditionally: it holds no draft to protect, so
 // `dirtyViews` has nothing to say about it and there is no edit to eat.
 renderProposals();
 if(!dirty.guards)reRender('guards',renderSettings);else staleNote('guards');
  if(!dirty.comp)reRender('comp',renderComp);else staleNote('comp');
  if(pol){POLICY=pol;
   if(!dirty.policy){PDRAFT=pClone(POLICY&&POLICY.stored);
    reRender('policy',renderPolicy);}
   else staleNote('policy');}
  renderOver();
  renderUsage();
 }catch(e){/* a stale view beats a dead panel */}
 // The Usage chart remounts on its own rAF; put the reader back where they were.
 requestAnimationFrame(()=>window.scrollTo(0,y));}

// Overview follows the report's table — the same segments, the same three views,
// the same words. `segOf` is the client twin of _report_html._seg_of and is pinned
// against it by name; two surfaces disagreeing about which phases are "finished"
// is the kind of drift a reader reads as a bug in the plan.
/**
 * @type {Object<string, string[]>} which segments each of the three views shows.
 * Keyed by the value of the view select, so an unknown key falls back to `all`
 * rather than showing nothing.
 */
const SEG_VIEWS={active:['active','pending'],archived:['archived'],
  all:['active','pending','archived']};
/**
 * Which of the three segments a phase status belongs to.
 *
 * @param {string} st - a phase status from the manifest
 * @returns {'archived'|'active'|'pending'} a terminal status is archived, a
 *   status that needs a human is active, and everything else — an unknown status
 *   included — is pending, so a status this build has never heard of is still
 *   listed rather than dropped
 */
const segOf=st=>st==='done'||st==='cancelled'?'archived'
  :(st==='in_progress'||st==='blocked')?'active':'pending';
/**
 * @type {{q: string, ts: string, bs: string, byArea: boolean,
 *   sort: 'plan'|'progress'|'status', view: ('active'|'archived'|'all'|null),
 *   open: Object<string, boolean>, evOpen: Object<string, boolean>}}
 * The Overview filter, hoisted out of the render because the 5s poll repaints
 * this view: held in the render closure it would be wiped by a badge update five
 * seconds after the reader set it. `open` and `view` ride it for the same reason
 * — a badge repaint must not fold every row somebody opened. `view: null` means
 * "not chosen yet" and is what lets the first render pick a default from the
 * plan; '' in a status filter means "no filter", never a status.
 *
 * `evOpen` is which recorded test runs are open, keyed by SUBJECT id — a phase
 * id or a task id, which never collide. It is a second map rather than a second
 * meaning for `open` because the two nest: a reader who opened a phase and then
 * one of its runs must not lose the run when a poll repaints the phase.
 */
// `open` and `evOpen` are keyed by a phase or task id and get no prototype:
// `OVF.evOpen['constructor']` read back as a function, so that subject's
// evidence rendered expanded before anyone pressed it, and the first press
// collapsed it.
const OVF={q:'',ts:'',bs:'',byArea:false,sort:'plan',view:null,
 open:Object.create(null),evOpen:Object.create(null)};
// Nothing-to-see-first: the statuses that need a human come before the ones that
// do not, in the strips and in the status sort. Plan order is still the default —
// a plan is written in an order and that order means something.
/** @type {string[]} task statuses, most-in-need-of-a-human first */
const OVORDER=['in_progress','blocked','pending','done'];
/** @type {string[]} bug statuses, on the same principle */
const OVBUGORDER=['open','triaged','in_progress','fixed','wontfix'];
/**
 * Where a status sits in one of those orders.
 * @param {string[]} o - OVORDER or OVBUGORDER
 * @param {string} s - the status to place
 * @returns {number} its index, or the list's length for a status the order never
 *   names — which sorts every unknown status last without dropping it
 */
const ovRank=(o,s)=>{const i=o.indexOf(s);return i<0?o.length:i;};
/**
 * Whether anything the Clear button clears is set.
 *
 * Deliberately does NOT include `view` or `byArea`: those are ways of looking at
 * the whole plan rather than filters over it, and offering to "clear" them would
 * make the count line lie about what it is counting.
 * @returns {boolean} true when a search term or either status filter is set
 */
const ovAnyFilter=()=>!!(OVF.q.trim()||OVF.ts||OVF.bs);
/**
 * One strip pill: a legend entry and a filter toggle in a single control.
 *
 * @param {string} status - the machine status this pill means, '' for a cut that
 *   is not a status at all; it lands in data-status, which is what the CSS themes
 *   off AND what a reader inspecting the DOM is told the pill means
 * @param {number} n - the count, rendered bold and last
 * @param {string} text - the human label
 * @param {boolean} on - whether this pill is the active filter
 * @param {() => void} onclick - what pressing it does
 * @param {string} [tip] - the title attribute; omitted becomes ''
 * @param {string} [cls] - an extra class for a pill that needs its own colour
 *   rather than borrowing another status's machine value
 * @returns {HTMLButtonElement} a real button, so it is keyboard reachable and
 *   announced as pressable without a hand-written role/tabindex/keydown trio
 */
function ovPill(status,n,text,on,onclick,tip,cls){
 return el('button',{class:'ovpill'+(cls?' '+cls:''),type:'button','data-status':status||'',
  'aria-pressed':on?'true':'false',title:tip||'',onclick:onclick},text,el('b',{},String(n)));}
/**
 * Copy a command, and say so on the button that did it.
 *
 * A copy button that fails silently is worse than no copy button: the async
 * clipboard can be refused — an insecure context, a permission — and the reader
 * is left believing they have the command. So there are three outcomes and all
 * three are visible: the label flips to Copied, or the hidden-textarea fallback
 * runs and flips it, or a toast hands the reader the text to copy by hand.
 * @param {HTMLButtonElement} btn - the button pressed; its label is restored
 *   after 1.6s, read at call time so a re-render cannot strand the old text
 * @param {string} text - what to put on the clipboard
 * @returns {void}
 */
function ovCopy(btn,text){
 const done=()=>{const was=btn.textContent;btn.textContent='Copied';
  setTimeout(()=>{btn.textContent=was;},1600);};
 const manual=()=>{const ta=el('textarea',{style:'position:fixed;top:-1000px;opacity:0'});
  ta.value=text;document.body.append(ta);ta.select();
  let ok=false;try{ok=document.execCommand('copy');}catch(e){ok=false;}
  ta.remove();if(ok)done();else toast('could not copy — the command is '+text,'err');};
 copyText(text,done,manual);}
/**
 * An ISO stamp as 'YYYY-MM-DD HH:MM', to the minute.
 *
 * @param {*} v - an ISO timestamp, or anything falsy
 * @returns {string} the trimmed stamp; '' for a missing value, and the input
 *   unchanged when it carries no 'T' to cut at — a date-only value stays a date
 *   rather than being truncated to nothing
 */
const ovStamp=v=>{const s=String(v||'');if(!s)return '';
 const i=s.indexOf('T');return i<0?s:s.slice(0,i)+' '+s.slice(i+1,i+6);};
/**
 * The phase text a ROW puts on screen: its id, its title and its area tags.
 *
 * One spelling, read by the search filter and by the match-basis test, because
 * those two must never disagree about which fields are visible — a field the
 * filter matches on and this list forgets is a row with no basis on it.
 * @param {{id: string, title: (string|undefined), area: (string[]|undefined)}} p -
 *   the phase, from the rollup
 * @returns {string} the three fields joined by spaces, lower-cased for matching
 */
const ovShownText=p=>(p.id+' '+(p.title||'')+' '+(p.area||[]).join(' ')).toLowerCase();
/**
 * Did the search term match this phase ONLY where the row does not show it?
 *
 * The row carries no outcome line any more, and the search still reaches the
 * outcome. So a row can sit in a filtered list with nothing on it containing the
 * term. That, and only that, is when the row owes the reader the outcome: when a
 * visible field already carries the term, showing it again is the noise this
 * change removed.
 * @param {{desiredOutcome: (string|undefined)}} p - the phase, from the rollup
 * @param {string} term - the search term; case is normalised here rather than
 *   trusted from the caller, so one lower-casing missed upstream cannot make
 *   this quietly answer false
 * @returns {boolean} true when the outcome is the only basis for the match
 */
const ovOutcomeIsBasis=(p,term)=>{const t=String(term||'').toLowerCase();
 return !!t&&String(p.desiredOutcome||'').toLowerCase().includes(t)
   &&!ovShownText(p).includes(t);};
/**
 * A window of `text` around the first case-insensitive hit for `term`.
 *
 * Windowed rather than truncated, and that is the whole reason it exists: the
 * outcome line is clipped to ONE line, so the head of a long outcome is all a
 * row can show — and a hit further in would be claimed by a row and be off
 * screen. Centring on the hit is what makes the basis actually visible.
 * @param {string} text - the full outcome
 * @param {string} term - the term to centre on; when it does not occur, the head
 *   is returned rather than nothing, so a caller that got its own condition
 *   wrong still renders the field instead of an empty span
 * @param {number} width - how many characters of context to keep in total; a
 *   term longer than that widens the window rather than being cut in half
 * @returns {string} the window, with an ellipsis on each side that was cut
 */
function ovExcerpt(text,term,width){
 const s=String(text||''),w=Math.max(String(term||'').length,width|0);
 if(s.length<=w)return s;
 const at=term?s.toLowerCase().indexOf(String(term).toLowerCase()):-1;
 if(at<0)return s.slice(0,w).trim()+'…';
 // Centre the hit, then clamp to both ends: a hit near the tail must not be
 // pushed back off screen by a window that walked past the end of the string.
 const pad=Math.floor((w-String(term).length)/2);
 const from=Math.min(Math.max(at-pad,0),Math.max(s.length-w,0)),to=from+w;
 return (from>0?'…':'')+s.slice(from,to).trim()+(to<s.length?'…':'');}

// ---------- recorded test runs ----------
// A BADGE IS THE STATUS AND NOTHING ELSE; the observations sit BESIDE it. Not a
// layout preference: a gate can fail AND rewrite the tree, and
// `run-test-gate.render` prints those as two sentences for the reason it states
// there — a reader who fixed the failure would otherwise meet the rewrite
// afterwards. The same holds for a run that passed while nothing ran, and for
// one whose tree comparison could not be made at all.
//
// Everything below reads FACTS the server shipped — `STATE.evidence.runs`, one
// positional row per run the plan points at, read against `.fields` — rather
// than a verdict somebody rendered, so the three-valued observations stay
// three-valued all the way to the pixel.
/**
 * @type {Object<string, string>} the word for each verdict, and for the three
 * silences no run ever answers. NOT exhaustive on purpose: the manifest schema
 * leaves the status enum open, so `evWord` names an unrecognised verdict instead
 * of folding it into 'failed'.
 */
const EVWORD={passed:'Passed',failed:'Failed','no-checks':'No checks ran',
 'timed-out':'Timed out',cancelled:'Cancelled','could-not-run':'Could not run',
 'empty-gate':'Empty gate',none:'No evidence','no-gate':'No gate configured',
 dangling:'Pointer without evidence'};
/**
 * @type {string[]} verdicts, most-in-need-of-a-human first. OVORDER's rule one
 * vocabulary over, so a phase's roll-up leads with what is wrong rather than
 * with whatever its first task happened to say.
 */
const EVORDER=['failed','could-not-run','timed-out','cancelled','no-checks',
 'dangling','empty-gate','none','no-gate','passed'];
/**
 * The word for a verdict.
 * @param {string} k - a verdict key, from the ledger or from evState
 * @returns {string} the table's word; an unrecognised verdict is humanised and
 *   shown AS ITSELF, and a run that cached no verdict says so rather than
 *   rendering the em dash `label('')` gives, which reads as "nothing here"
 */
function evWord(k){
 // Own-property read: a status word comes out of a file a human may edit, and
 // `EVWORD['constructor']` inherits a function that would reach the page.
 if(Object.prototype.hasOwnProperty.call(EVWORD,k))return EVWORD[k];
 if(!k)return 'Verdict not recorded';
 const word=label(k);
 // ...and `label` reads ITS table without that guard, so the same word comes
 // back as `Object.prototype.constructor`. Found by calling this function
 // rather than by reading it. The raw word is the honest fallback, because
 // naming what was not recognised is this arm's whole contract; the guard
 // belongs in `label` and is not fixed here, in a change about something else.
 return typeof word==='string'?word:k;}
/**
 * A positional fact row as an object, read against the column names shipped
 * beside it.
 * @param {*} row - one entry of `STATE.evidence.runs`, or one step inside it
 * @param {string[]|undefined} fields - the matching `fields`/`stepFields` list
 * @returns {Object<string, *>|null} null when there is no row at all — never an
 *   empty object, because every three-valued read would then answer `undefined`
 *   and a caller could not tell that from a run that observed nothing
 */
function evRow(row,fields){
 if(!Array.isArray(row))return null;
 // The field NAMES come out of the evidence ledger, so the row this builds
 // carries no prototype - `row.constructor` would otherwise answer for a
 // column the ledger never had.
 const out=Object.create(null);(fields||[]).forEach((f,i)=>{out[f]=row[i];});return out;}
/**
 * What one subject's test evidence amounts to — as facts, not as a rendered cell.
 *
 * FOUR ANSWERS, AND THEY ARE NOT ONE GREY BLOB. No gate declared anywhere is a
 * fact about the PLAN: nothing could have run. No pointer is a fact about the
 * LEDGER: nothing has run yet, which is never "failed". A pointer whose run the
 * ledger does not hold is a third thing, and the only one that says the record
 * itself is wrong. Only the fourth reads a verdict.
 * @param {{testEvidence: *, gateSource: (string|null|undefined)}} node - the
 *   composition row for a task or a phase
 * @param {{runs: (Object<string, Array<*>>|undefined), fields: (string[]|undefined),
 *   files: (number|undefined), unreadable: (number|undefined)}} ev -
 *   `STATE.evidence`
 * @returns {{key: string, why: string, run: (Object<string, *>|null)}} `run` is
 *   null for all three silences, which is what makes a marker beside them
 *   impossible: an observation needs a run that made it
 */
function evState(node,ev){
 const row=node||{},pointer=row.testEvidence,src=row.gateSource;
 if(pointer==null)return src
  ?{key:'none',run:null,
    why:'no run has been recorded for this subject. The '+src+"'s gate is what "
      +'would grade it — an absent record is not a failure.'}
  :{key:'no-gate',run:null,
    why:'no test gate is declared here or on the phase, so no run could have '
      +'been recorded. Nothing has been proven either way.'};
 const rid=(typeof pointer==='object'&&typeof pointer.runId==='string')
   ?pointer.runId:'';
 const run=rid?evRow(((ev||{}).runs||{})[rid],(ev||{}).fields):null;
 if(!run)return {key:'dangling',run:null,
   why:'the plan points at '+(rid?'run '+rid:'a block naming no run')
     +' and the evidence ledger does not hold it — '
     +plural((ev&&ev.files)||0,'file read','files read')+', '
     +plural((ev&&ev.unreadable)||0,'line unreadable','lines unreadable')
     +'. The plan caches the verdict "'
     +((pointer&&pointer.status)||'not recorded')+'".'};
 return {key:(typeof run.status==='string')?run.status:'',run:run,
   why:'run '+(run.runId||'?')+(run.at?', recorded '+ovStamp(run.at)+' UTC':'')};}
/**
 * The observations that sit beside a badge — never inside it.
 *
 * EVERY ONE OF THESE IS THREE-VALUED, AND A TRUTHY TEST MERGES TWO OF THE THREE.
 * `null` is "no comparison was made", `0` is "compared, and there was nothing",
 * a positive number is the finding. A gate that rewrote the tree and a gate
 * nobody could ask about are not the same thing, and `!x` calls them both clean.
 * @param {Object<string, *>|null} run - a decoded run, or null when there is none
 * @returns {Array<{text: string, why: string}>} empty when there is no run —
 *   a marker with no run behind it would be an observation nobody made
 */
function evMarks(run){
 if(!run)return [];
 const marks=[];
 if(run.treeMutated==null)marks.push({text:'tree unknown',
   why:run.treeBasis||'no tree comparison was made, so a rewrite cannot be '
     +'ruled out'});
 else if(run.treeMutated>0)marks.push({text:'tree mutated',
   why:plural(run.treeMutated,'file was','files were')+' rewritten by the gate '
     +'itself. A gate is a measurement: this run cannot sign anything off.'});
 if(run.coverage==null)marks.push({text:'coverage unknown',
   why:run.coverageBasis||'the overlap with this work could not be asked for'});
 else if(run.coverage===0)marks.push({text:'no overlap',
   why:'the gate ran and named none of the files this work owns — the third way '
     +'a gate says nothing, after doing too much and doing nothing'});
 if(run.ranTotal==null)marks.push({text:'checks unknown',
   why:run.countsBasis||'check count not knowable from this runner'});
 return marks;}
/**
 * What the run says about how many checks ran. THREE ANSWERS, NEVER TWO.
 * @param {Object<string, *>} run - a decoded run
 * @returns {string} `null` is "not knowable from this runner" and is emphatically
 *   not zero; rendering it as a count of nothing is the defect this exists for
 */
const evChecks=run=>run.ranTotal==null
 ?'check count not knowable from this runner'
 :(run.ranTotal===0?'no checks ran':plural(run.ranTotal,'check ran','checks ran'));
/**
 * A duration in the unit a reader can hold.
 * @param {number} ms - milliseconds, as the ledger recorded them
 * @returns {string} seconds past a second, milliseconds below it
 */
const evMs=ms=>ms>=1000?(ms/1000).toFixed(ms>=10000?0:1)+'s':Math.round(ms)+'ms';
/**
 * One subject's verdict, with its observations beside it.
 * @param {{key: string, why: string, run: (Object<string, *>|null)}} s - evState's answer
 * @returns {HTMLSpanElement} the pill and the markers, in one inline box
 */
function evBadge(s){
 return el('span',{class:'evb'},
  el('span',{class:'st','data-evstatus':s.key||'unknown',title:s.why},
    evWord(s.key)),
  evMarks(s.run).map(m=>el('span',{class:'evmk','data-evmark':m.text,title:m.why},
    m.text)));}
/**
 * One recorded run, opened: what it answered, and the basis for what it could not.
 *
 * The bases are printed rather than summarised. "unknown" without the sentence
 * that produced it is the shape a reader cannot act on, and the ledger already
 * carries all three of them.
 * @param {Object<string, *>} run - a decoded run
 * @returns {HTMLDivElement}
 */
function evDetail(run){
 const box=el('div',{class:'evdet','data-evrun':run.runId||''});
 box.append(el('div',{class:'mut'},'run '+(run.runId||'?')
   +(run.at?' · '+ovStamp(run.at)+' UTC':'')
   +(run.attempt!=null?' · attempt '+run.attempt:'')
   +(run.durationMs!=null?' · '+evMs(run.durationMs):'')
   +' · '+evChecks(run)));
 [['tree',run.treeBasis],['coverage',run.coverageBasis],
  ['checks',run.countsBasis]].forEach(pair=>{
   if(pair[1])box.append(el('div',{class:'evbasis','data-evbasis':pair[0]},
     pair[0]+': '+pair[1]));});
 const steps=Array.isArray(run.steps)?run.steps:[];
 // An empty step list is SAID. A gate with no commands and a run whose steps
 // nothing recorded look identical in an empty table, and the first is a real
 // answer a reader acts on.
 if(!steps.length)box.append(el('div',{class:'mut'},'This run recorded no steps.'));
 else{const tb=el('tbody');
  steps.forEach(raw=>{const s=evRow(raw,(STATE.evidence||{}).stepFields);
   if(!s)return;
   tb.append(el('tr',{'data-evstep':s.name||''},
     el('td',{class:'mono'},s.name||''),
     el('td',{class:'mono'},s.exit==null?'—':String(s.exit)),
     // The same three answers one step down. `0` is a step that ran and checked
     // nothing; `null` is a runner that does not report counts at all.
     el('td',{},s.ran==null?'not knowable':String(s.ran)),
     el('td',{class:'mut'},s.durationMs==null?'':evMs(s.durationMs)),
     el('td',{class:'mut'},s.outcome||'')));});
  box.append(el('table',{class:'evsteps'},
    tableHead(['step','exit','checks','took','outcome']),tb));}
 return box;}
/**
 * A subject's badge, and its run beneath when the reader has opened it.
 *
 * A subject with no recorded run is NOT a control: there is nothing to open, and
 * a button onto an empty box is a promise the page cannot keep.
 *
 * CONTAINED, and this is the one door into the feature from the phase detail.
 * An evidence badge is an addition to a table somebody opened for other reasons,
 * so a throw here must cost the badge and not the whole Overview — `runContained`
 * is boot's version of the same rule. The fallback is a sentinel no real verdict
 * can produce, because a failure that renders like an answer is the thing this
 * repo names silent.
 * @param {string} id - the subject id, which is the key `OVF.evOpen` holds
 * @param {object} node - the composition row carrying testEvidence/gateSource
 * @param {object} ev - `STATE.evidence`
 * @returns {{badge: HTMLElement, detail: (HTMLElement|null)}}
 */
function evCell(id,node,ev){
 try{
  const s=evState(node,ev),badge=evBadge(s);
  if(!s.run)return {badge:badge,detail:null};
  const open=!!OVF.evOpen[id];
  return {badge:el('button',{class:'evtog',type:'button','data-evtog':id,
    'aria-expanded':open?'true':'false',
    title:(open?'hide ':'show ')+'what this run did',
    onclick:()=>{OVF.evOpen[id]=!open;renderOver();}},badge),
   detail:open?evDetail(s.run):null};
 }catch(cause){console.error('evidence badge failed for '+id,cause);
  return {badge:el('span',{class:'evfail'},'evidence unavailable'),detail:null};}}
/**
 * The phase's tasks counted by what their evidence says.
 *
 * A SECOND MEASUREMENT, NEVER MERGED WITH THE FIRST. The phase's own sign-off run
 * graded the phase; these graded tasks. One badge for both would claim a
 * measurement nobody made.
 * @param {Array<object>} tasks - the phase's composition rows
 * @param {object} ev - `STATE.evidence`
 * @returns {Array<{key: string, n: number}>} most-in-need-of-a-human first
 */
function evTaskRoll(tasks,ev){
 const counts=new Map();
 tasks.forEach(t=>{const k=evState(t,ev).key;counts.set(k,(counts.get(k)||0)+1);});
 return [...counts.keys()].sort((a,b)=>ovRank(EVORDER,a)-ovRank(EVORDER,b))
  .map(k=>({key:k,n:counts.get(k)}));}
/**
 * The roll-up as cells, contained for `evCell`'s reason and with its own sentinel.
 * @param {Array<object>} tasks - the phase's composition rows
 * @param {object} ev - `STATE.evidence`
 * @returns {Node|Array<Node>} a sentence when there is nothing to count, one
 *   pill per verdict otherwise
 */
function evRollCells(tasks,ev){
 try{
  if(!tasks.length)return el('span',{class:'mut'},'no tasks to count');
  return evTaskRoll(tasks,ev).map(r=>el('span',{class:'st','data-evstatus':r.key,
    title:plural(r.n,'task in this phase says','tasks in this phase say')+' '
      +evWord(r.key).toLowerCase()},r.n+' '+evWord(r.key)));
 }catch(cause){console.error('evidence roll-up failed',cause);
  return el('span',{class:'evfail'},'roll-up unavailable');}}
/**
 * One labelled evidence line inside a phase's detail.
 * @param {string} lbl - what the line is a measurement OF; the label is the
 *   whole point, since two unlabelled badges read as one contradiction
 * @param {...(Node|Array<Node>|null)} parts - what to put beside it
 * @returns {HTMLDivElement}
 */
const evLine=(lbl,...parts)=>el('div',{class:'evline','data-evline':lbl},
 el('span',{class:'evlbl'},lbl),parts);
/**
 * A phase's tasks, in the columns the report's table uses and in ITS order — id,
 * title, status, risk (coloured TEXT, not a pill), commit, when it finished, and
 * then `tests` — led by what the phase is FOR.
 *
 * `tests` trails the plan's own columns because that is where the report puts it,
 * and the two tables are meant to read the same way; `tools/ui-checks/stage-tabs.mjs`
 * is what holds them together.
 *
 * The outcome leads rather than trailing the table: this is where it lives now
 * that the row does not carry it, and a purpose read after its tasks is a
 * footnote to them.
 *
 * Read-only on purpose: this tab is for reading the plan, and the one place that
 * edits it is named at the end rather than reached by accident.
 * @param {{id: string, desiredOutcome: (string|undefined)}} p - the phase, from
 *   the rollup
 * @returns {HTMLDivElement} the detail box; a phase with no tasks gets a
 *   sentence saying so rather than an empty table
 */
function ovDetail(p){
 const tasks=((STATE.composition||{}).tasks||[]).filter(t=>t.phaseId===p.id);
 const ev=STATE.evidence||{};
 // The ROLLUP phase carries the progress bar; the COMPOSITION phase carries the
 // pointer and the gate. Looked up rather than assumed present: a phase the
 // rollup knows and the composition does not gets the same honest "no evidence"
 // as one that has never been run.
 const cph=((STATE.composition||{}).phases||[]).find(x=>x.id===p.id)||{};
 const box=el('div',{class:'ovdetail','data-ovdetail':p.id});
 if(p.desiredOutcome)box.append(el('div',{class:'mut small','data-ovpurpose':p.id},
   'Desired: '+p.desiredOutcome));
 // BOTH, LABELLED APART. The phase's own sign-off run and the roll-up over its
 // tasks measure different things over different files, and a reader shown one
 // of them alone would take it for the other.
 const pcell=evCell(p.id,cph,ev);
 box.append(evLine('phase sign-off',pcell.badge));
 if(pcell.detail)box.append(pcell.detail);
 box.append(evLine('tasks',evRollCells(tasks,ev)));
 if(!tasks.length)box.append(el('div',{class:'mut small'},'This phase has no tasks.'));
 else{
  const tb=el('tbody');
  tasks.forEach(t=>{
   const when=ovStamp(t.completedAt||t.startedAt);
   const cell=evCell(t.id||'',t,ev);
   tb.append(el('tr',{'data-ovtask':t.id||''},
    el('td',{class:'mono'},t.id||''),
    el('td',{class:'ovt'},t.title||''),
    el('td',{},el('span',{class:'st','data-status':t.status||''},label(t.status))),
    el('td',{},t.risk?el('span',{class:'rk','data-risk':t.risk},t.risk):null),
    el('td',{class:'mono'},t.commit?String(t.commit).slice(0,9):''),
    // A start stamp is labelled as one, or an unfinished task reads as finished.
    el('td',{class:'mut'},when+(t.completedAt?'':(when?' (started)':''))),
    // Everything the PLAN says, and then whether anything MEASURED it. Last,
    // because that is where the report's table carries it.
    el('td',{},cell.badge)));
   // The opened run gets a row of its own, spanning the table, so the columns
   // above it keep the widths every other row agreed on.
   if(cell.detail)tb.append(el('tr',{'data-evdetail':t.id||''},
     el('td',{colspan:'7'},cell.detail)));});
  box.append(el('table',{class:'ovtasks'},
    tableHead(['id','title','status','risk','commit','done (UTC)','tests']),tb));}
 box.append(el('div',{class:'row',style:'margin-top:.4rem'},
   el('button',{class:'btn small','data-ovedit':p.id,type:'button',
     title:'Plan & models is where tasks, models and skills are changed',
     onclick:()=>openInComp(p.id)},'Edit in Plan & models')));
 return box;}

/**
 * Restack a view's cards into the order the theme asks for.
 *
 * The renderers append in their own order and stamp each top-level card with a
 * name; this reorders what is already DRAWN. Reordering after the fact rather
 * than parameterising every renderer keeps the ordering in one place — and a
 * card the theme does not name simply keeps its position at the end, so a theme
 * written today never hides a card added next year.
 * @param {string} view - the container id, which is also the key in
 *   `THEME.cards` and in a theme's `layout.order`
 * @returns {void} a missing container, an unread theme, or a view the order
 *   never names are all no-ops — the drawn order stands
 */
function applyCardOrder(view){
 const host=document.getElementById(view);
 if(!host||!THEME)return;
 // The DRAFT order when the editor is holding one, the saved theme otherwise —
 // tLayout answers that in one place, the same three-layer answer the colours
 // get. An order you can only see after saving is not a preview, and this is
 // the one part of the look that is judged by looking at another tab.
 const lay=tLayout();
 const want=(lay.order||{})[view];
 if(!Array.isArray(want)||!want.length)return;
 const named={};
 [...host.children].forEach(n=>{const k=n.getAttribute&&n.getAttribute('data-card');
  if(k)named[k]=n;});
 want.forEach(k=>{if(named[k])host.append(named[k]);});
 // Anything the order did not mention stays after it, in its drawn order.
 [...host.children].forEach(n=>{const k=n.getAttribute&&n.getAttribute('data-card');
  if(k&&want.indexOf(k)<0)host.append(n);});}

/**
 * Draw the whole Overview tab: the phase rollup, the plan gate, what is ready
 * now, and the bugs.
 *
 * Called by the 5s poll as well as by every filter control, which is what
 * shapes it: it may run at any moment under the reader's hands, so the caret is
 * saved and restored, the filter lives in OVF rather than in this closure, and
 * nothing here fetches. It reads STATE, RUNSTATUS and THEME and rebuilds.
 * @returns {void} returns early after one message when there is no manifest —
 *   a plan that does not exist is said out loud, not drawn as an empty table
 */
function renderOver(){const c=$('#over');const r=STATE.rollup;
 // The poll repaints this view under the reader's hands. Put the caret back where
 // it was, or typing a five-letter search while a colleague takes a phase lock
 // loses the last three letters and the focus with them.
 const act=document.activeElement,keepQ=!!(act&&act.id==='ovq'),
   caret=keepQ?act.selectionStart:0,
   keepBack=keepQ?null:focusKeep('#over');
 c.textContent='';
 // data-card names this card for the theme's layout.order. Stamped where the
 // card is BUILT, so a renamed card renames its ordering key with it.
 const card=el('div',{class:'card','data-card':'phases'});
 // THIS IS THE FIRST SCREEN OF THE PRODUCT, not a footnote. With no plan yet
 // `initialTab()` lands here, so it carries what Usage's empty state already
 // carries and what this one did not: what is missing, what the command does,
 // where the file will appear, and the way to move it BEFORE it is written -
 // `manifestPath` is a Settings field, so choosing it afterwards means moving a
 // file. Same shape as usage-view.js on purpose; a second empty-state dialect
 // would be the inconsistency this replaces.
 if(!r){card.append(
   el('div',{class:'mut'},'No plan yet. "/audit:init" interviews you about scope, '
     +'reads the codebase with read-only explorers, and proposes phases for your '
     +'approval before it writes anything.'),
   el('div',{class:'mut',style:'margin-top:var(--sp-0)'},
     'it would be written to: '+(STATE.manifestPath||'-'),' · ',
     settingsLink('change where it goes','manifestPath')));
  // The 5s poll repaints this view, and this card now HOLDS a control - without
  // the same restore the tail does, a reader tabbing to that link loses it
  // within five seconds. The old bare-sentence branch had nothing to focus.
  c.append(card);restoreCaret(keepQ?$('#ovq'):null,caret,keepBack);return;}
 const vstate=r.valid?el('div',{class:'findings ok'},'✓ manifest valid ('+r.warnings+' warnings)')
   :manifestFindingsBox(r.findings,STATE.manifestFindings||[]);
 card.append(vstate);
 const rs=RUNSTATUS||STATE.runStatus||{index:null,phases:{}};
 if(rs.index){const h=rs.index.hostname||'?';const dead=rs.index.live===false;
  card.append(el('div',{class:'findings warn',title:rs.index.liveBasis||''},
   (dead?'⚠ index lock held by no live run':'⚙ index locked (structural op / id allocation)')
   +(h?' · '+h:'')+(rs.index.startedAt?' · since '+rs.index.startedAt:'')
   +(dead?' · '+(rs.index.liveBasis||''):'')));}

 // --- the two strips: legend and filter in one control ------------------------
 // Per-phase status counts come from the composition (the same manifest), because
 // the rollup carries done/total per phase and nothing finer — and "which phases
 // have work in progress" is the question the strip is for.
 const tasks=(STATE.composition||{}).tasks||[];
 // Two levels, two outside keys: the phase id and the task status.
 const pStatus=Object.create(null);
 tasks.forEach(t=>{const m=pStatus[t.phaseId]=pStatus[t.phaseId]||Object.create(null);
  const s=t.status||'';m[s]=(m[s]||0)+1;});
 const tBy=r.tasks.byStatus||{},bBy=r.bugs.byStatus||{};
 const tstrip=el('div',{class:'ovstrip'},el('span',{class:'ovlbl'},'Tasks'),
   el('span',{class:'mut'},r.tasks.total+' total'));
 Object.keys(tBy).sort((a,b)=>ovRank(OVORDER,a)-ovRank(OVORDER,b)).forEach(s=>{
  tstrip.append(ovPill(s,tBy[s],label(s),OVF.ts===s,
    ()=>{OVF.ts=OVF.ts===s?'':s;renderOver();},
    'show only phases carrying '+label(s).toLowerCase()+' tasks'));});
 const bstrip=el('div',{class:'ovstrip'},el('span',{class:'ovlbl'},'Bugs'),
   el('span',{class:'mut'},r.bugs.total+' total · '+r.bugs.open+' open'));
 Object.keys(bBy).sort((a,b)=>ovRank(OVBUGORDER,a)-ovRank(OVBUGORDER,b)).forEach(s=>{
  bstrip.append(ovPill(s,bBy[s],label(s),OVF.bs===s,
    ()=>{OVF.bs=OVF.bs===s?'':s;renderOver();},'show only '+label(s).toLowerCase()+' bugs'));});
 // Not a status — a severity cut across the open ones. It keeps its own class
 // rather than borrowing data-status="blocked" for the colour: the machine value
 // in data-status is what the CSS themes off AND what a reader inspecting the DOM
 // is told this pill means, and "blocked" would be a plain lie there.
 if(r.bugs.openHighSeverity)bstrip.append(ovPill('',r.bugs.openHighSeverity,
   'High severity, open',OVF.bs==='!high',()=>{OVF.bs=OVF.bs==='!high'?'':'!high';renderOver();},
   'open bugs filed high, critical, blocker, sev1 or p0','hi'));
 card.append(tstrip,bstrip);

 // --- tools: search, sort, group by area --------------------------------------
 const qIn=el('input',{type:'search',id:'ovq',value:OVF.q,
   placeholder:'search phases — id, title, area, outcome…','aria-label':'search phases'});
 qIn.addEventListener('input',()=>{OVF.q=qIn.value;renderOver();});
 const sortSel=el('select',{'aria-label':'sort phases',
   onchange:e=>{OVF.sort=e.target.value;renderOver();}});
 fillOptions(sortSel,[['plan','plan order'],['progress','progress'],
   ['status','status'],['priority','priority']],OVF.sort);
 const tools=el('div',{class:'ovtools'},qIn,el('span',{class:'filtlbl'},'sort:'),sortSel);
 const areaTags=Object.keys(r.areas||{});
 if(areaTags.length){
  const cb=el('input',{type:'checkbox',id:'ovarea'});cb.checked=OVF.byArea;
  cb.onchange=()=>{OVF.byArea=cb.checked;renderOver();};
  tools.append(el('label',{class:'inl',for:'ovarea'},cb,'group by area'));}
 // The same three views the report offers, defaulting the same way — a finished
 // plan opens on `all` rather than on an empty table. Decided once, on the first
 // render only, so a later choice of the reader's is never overwritten.
 if(OVF.view===null){
  const segs=new Set((r.phases||[]).map(p=>segOf(p.status)));
  OVF.view=(segs.has('active')||segs.has('pending'))?'active':'all';}
 const viewSel=el('select',{'aria-label':'which phases to show','data-ovview':'1',
   onchange:e=>{OVF.view=e.target.value;renderOver();}});
 fillOptions(viewSel,[['active','Active & pending'],
   ['archived','Archived (done & cancelled)'],['all','All phases']],OVF.view);
 tools.append(el('span',{class:'filtlbl'},'view:'),viewSel);
 const count=el('span',{class:'count',style:'margin-left:auto'});
 tools.append(count);
 if(ovAnyFilter())tools.append(el('button',{class:'btn small',type:'button','data-ovclear':'1',
   onclick:()=>{OVF.q='';OVF.ts='';OVF.bs='';renderOver();}},'Clear filters'));
 card.append(el('h2',{},'Phases'),tools);

 // --- phases -------------------------------------------------------------------
 const term=OVF.q.trim().toLowerCase();
 const hitP=p=>(!term||(ovShownText(p)+' '
     +String(p.desiredOutcome||'').toLowerCase()).includes(term))
   &&(!OVF.ts||!!((pStatus[p.id]||{})[OVF.ts]));
 // Matched and in-view are two different sets on purpose: the difference between
 // them is what the "outside this view" line is able to report.
 const matched=r.phases.filter(hitP);
 const inView=p=>(SEG_VIEWS[OVF.view]||SEG_VIEWS.all).includes(segOf(p.status));
 const ordered=matched.filter(inView);
 const outside=matched.length-ordered.length;
 const pct=p=>p.total?100*p.done/p.total:0;
 if(OVF.sort==='progress')ordered.sort((a,b)=>pct(b)-pct(a));
 else if(OVF.sort==='status')ordered.sort((a,b)=>ovRank(OVORDER,a.status)-ovRank(OVORDER,b.status));
 // Priority as a SORT OPTION, never as the default: the written plan is the
 // plan, and priority is an overlay on which of its ready tasks runs first.
 //
 // ORDERED BY A NUMBER THE SERVER COMPUTED, and the rule is nowhere on this
 // side. `porder` is `_priority.ranks` — the same function behind the report's
 // `data-porder` — so the panel, the report and the orchestrator's own walk
 // cannot hold separate opinions about order. This line used to re-express
 // sort_key here as an absent-tier class test and a tier compare beside it. It
 // was correct, nothing held it correct, and nothing would have said so the day
 // the comparator changed. `p.priority` stays on the badge, where a tier is what
 // a reader understands; an ordering index is not a thing to show them.
 else if(OVF.sort==='priority')ordered.sort((a,b)=>a.porder-b.porder);
 /**
  * One phase as a pressable row, with its detail beneath when it is open.
  * @param {{id: string, status: string, title: (string|undefined),
  *   area: (string[]|undefined), done: number, total: number,
  *   priority: (number|null|undefined), desiredOutcome: (string|undefined)}} p -
  *   the phase, from the rollup
  * @returns {HTMLElement} the row itself when the phase is closed, or a wrapper
  *   holding the row and its detail when it is open — so the caller appends one
  *   node either way
  */
 function phaseRow(p){const w=Math.round(pct(p));
  const st=(rs.phases||{})[p.id]||{};let runBadge=null;
  if(st.lock){const h=st.lock.hostname||'?';const dead=st.lock.live===false;
   // "running" is a claim about a process. Say it only when the pid was probed
   // and answered; an abandoned lock says so, with the basis in the tooltip.
   runBadge=el('span',{class:'badge '+(dead?'held':'run'),
    title:(st.lock.liveBasis||'phase lock held')+(st.lock.startedAt?' · since '+st.lock.startedAt:'')},
    (dead?'○ lock, no live run':'● running')+(h?' · '+h:''));}
  else if(st.claim){const s=(st.claim.sessionId||'').slice(0,8);
   runBadge=el('span',{class:'badge claim',title:'claimed'+(st.claim.branch?' on '+st.claim.branch:'')},'◷ claimed'+(s?' · '+s:''));}
  const areaBadges=(p.area||[]).map(a=>el('span',{class:'badge area',title:'area'},a));
  // One control, not a row with a handler bolted on: keyboard reachable and
  // announced as pressable without a hand-written role/tabindex/keydown trio.
  // The row's own counts, in the report's words. A phase in progress with two
  // stuck tasks reads as "in progress" and nothing else without them, and the
  // bar cannot say a task was dropped.
  const nBlocked=(pStatus[p.id]||{}).blocked||0,nCancelled=(pStatus[p.id]||{}).cancelled||0;
  const open=!!OVF.open[p.id];
  // A click OPENS the phase here. It used to jump to Composition — a tab for
  // EDITING tasks, models and skills — so "let me look at this phase" landed
  // the reader in a form, with their Overview filters left behind. Composition
  // is still one press away, named, inside the detail.
  const row=el('button',{class:'ovrow'+(open?' open':''),type:'button',
    'data-status':p.status||'','data-phase':p.id,'aria-expanded':open?'true':'false',
    title:(open?'collapse ':'expand ')+p.id
      +(p.desiredOutcome?' — '+p.desiredOutcome:''),
    onclick:()=>{OVF.open[p.id]=!open;renderOver();}},
   el('span',{class:'ovtri'}),
   el('span',{class:'pid'},p.id),
   el('span',{class:'ptitle'},p.title||''),
   el('span',{class:'st','data-status':p.status||''},label(p.status)),
   areaBadges,runBadge,
   // The pin, where the eye already looks for what a phase IS. It says what the
   // tier buys and what it does not, because "priority 1" alone reads as
   // "skips the queue" and it does not: a dependency always wins.
   p.priority!=null?el('span',{class:'badge prio',
     title:'runs first among the tasks that are ALREADY ready - never over a '
       +'dependency'},'priority '+p.priority):null,
   // Only when the phase itself is not blocked: the status pill already says
   // that, and two words for one fact reads as two problems.
   nBlocked&&p.status!=='blocked'?el('span',{class:'pblocked',
     title:plural(nBlocked,'task in this phase is blocked',
       'tasks in this phase are blocked')},nBlocked+' blocked'):null,
   nCancelled?el('span',{class:'pcancelled',
     title:plural(nCancelled,'task in this phase was cancelled',
       'tasks in this phase were cancelled')},nCancelled+' cancelled'):null,
   OVF.ts?el('span',{class:'ovmatch'},((pStatus[p.id]||{})[OVF.ts]||0)+' '+label(OVF.ts).toLowerCase()):null,
   el('span',{class:'bar'},el('i',{style:'width:'+w+'%'})),
   el('span',{class:'mut'},p.done+'/'+p.total),
   // The outcome, ONLY when it is the reason this row is in the list. It used to
   // be on every row, where it read as near-identical prose that doubled the row
   // height and separated nothing; it is on the tooltip and in the detail now.
   // Windowed on the hit, because the line is clipped to one line and the head of
   // an outcome need not contain the term the reader typed.
   ovOutcomeIsBasis(p,term)?el('span',{class:'ovout','data-ovhit':'outcome',
     title:p.desiredOutcome},'matched in outcome: '
     +ovExcerpt(p.desiredOutcome,term,64)):null);
  if(!open)return row;
  return el('div',{class:'ovwrap'},row,ovDetail(p));}
 if(!ordered.length){
  card.append(el('div',{class:'ovempty'},'No phase matches this filter. ',
    el('button',{class:'btn small',type:'button','data-ovclear':'1',
      onclick:()=>{OVF.q='';OVF.ts='';OVF.bs='';renderOver();}},'Clear filters')));}
 else if(OVF.byArea){
  // A phase with two tags is listed under both — the same rule the rollup counts
  // by, so the group headings add up to more than the plan when tags overlap, and
  // saying so here is cheaper than a reader discovering it by arithmetic.
  areaTags.sort().forEach(tag=>{
   const inTag=ordered.filter(p=>(p.area||[]).includes(tag));
   if(!inTag.length)return;
   const g=r.areas[tag]||{};
   card.append(el('div',{class:'ovgrp'},el('span',{class:'gname'},tag),
     el('span',{class:'mut'},inTag.length+' of '+g.phases+' phases · '+g.done+'/'+g.total+' tasks')));
   inTag.forEach(p=>card.append(phaseRow(p)));});
  const untagged=ordered.filter(p=>!(p.area||[]).length);
  if(untagged.length){card.append(el('div',{class:'ovgrp'},el('span',{class:'gname'},'untagged'),
    el('span',{class:'mut'},untagged.length+' phases')));
   untagged.forEach(p=>card.append(phaseRow(p)));}}
 else ordered.forEach(p=>card.append(phaseRow(p)));
 // Matches the VIEW is holding back — the report says this too, in the same
 // words, and for the same reason: a filter that quietly finds nothing is
 // indistinguishable from a plan that holds nothing.
 if(outside>0)card.append(el('div',{class:'ovoutside','data-ovoutside':String(outside)},
   outside+(outside===1?' phase matches':' phases match')+' outside this view — ',
   el('button',{class:'btn small',type:'button','data-ovviewall':'1',
     onclick:()=>{OVF.view='all';renderOver();}},'Show all phases')));
 count.textContent=ovAnyFilter()?(ordered.length+' / '+r.phases.length+' phases')
   :(r.phases.length+' phases · '+r.tasks.total+' tasks');
 c.append(card);

 // --- plan gate ----------------------------------------------------------------
 // The tier the gate is in, WHY (server-computed by the hooks' own functions —
 // never re-derived here), whether a single-use bypass is armed, and the tail
 // of the gate events feed. The block rides /api/runstatus and is part of
 // runStatusKey, so a fresh verdict repaints this card within one poll.
 const g=rs.gate;
 if(g){
  const gcard=el('div',{class:'card',id:'gatecard','data-card':'gate'});
  gcard.append(h2h('Plan gate',
    'The plan-first gate’s current tier, its source, and the newest verdicts '
    +'it delivered (from .claude/logs/plan-gate-events.jsonl). Deny and ask come '
    +'from require-plan/guard-secrets-read; the bypass rows from #no-plan.'));
  const strip=el('div',{class:'ovstrip'},
    el('span',{class:'st','data-status':g.mode||'','data-gate-tier':g.mode||''},label(g.mode)),
    el('span',{class:'mut'},g.source||''));
  if(g.bypassArmed)strip.append(el('span',{class:'badge held','data-bypass-armed':'1',
    title:'a single-use bypass (#no-plan) is armed and unexpired in some session — '
    +'the next non-trivial edit there rides it'},'⚑ bypass armed'));
  gcard.append(strip);
  const evs=g.events||[];
  // An empty feed is said out loud: a gate that has delivered no verdict yet
  // must not look like a card that failed to load its rows.
  if(!evs.length)gcard.append(el('div',{class:'mut'},
    'No gate events yet — verdicts land here as they happen.'));
  else{const tb=el('tbody');
   // `e.file` ARRIVES REDACTED (F113): _panel_runstate._redacted_event puts every
   // row through the journal's repo_relative_or_token before the payload leaves
   // the server, so an out-of-repo row carries its class and not the operator's
   // home directory. Do not reconstruct a fuller path here to make the cell more
   // informative — the CLI refuses to echo exactly this string, and this card is
   // the one docs/screenshots/panel-gate.png is a committed render of.
   evs.forEach(e=>tb.append(el('tr',{},
     el('td',{class:'mono'},String(e.ts||'').replace('T',' ').replace('Z','')),
     el('td',{},el('span',{class:'badge','data-ev':e.event||''},e.event||'')),
     el('td',{class:'mono'},e.file||''),
     el('td',{class:'d'},e.reason||''))));
   // `reason`, NOT `why` (F170). The prune hint two elements down points at a
   // column by name - "an absolute path in `reason`" - and its sibling in the
   // same sentence, `file`, already lands on a heading. One of the two resolving
   // and the other not is the reader's problem, and the pointer is the half that
   // cannot move: those backticked words are the keys of the row as it sits in
   // plan-gate-events.jsonl, `audit-logs._HISTORY` is where they are written, and
   // a case pins the panel to that constant word for word. A heading is the
   // cheaper end AND the correct one - `why` was the only question word in any
   // table head on this page, against `what`, `field`, `capability`, `pattern`.
   gcard.append(el('div',{class:'regtblwrap'},el('table',{class:'regtbl'},
     tableHead(['when','event','file','reason']),tb)));}
  // Appended UNCONDITIONALLY, including under "No gate events yet", and that is
  // the one placement decision here that is not cosmetic: an empty table does
  // NOT mean an empty file. `_panel_runstate` drops a row it cannot parse
  // silently, so a feed made entirely of unreadable lines renders as no events
  // at all — and unreadable rows are one of the three classes the prune exists
  // to clear. Hiding the control on `!evs.length` would hide it in exactly the
  // case that needs it.
  gcard.append(gpControl());
  c.append(gcard);}

 // --- ready now ----------------------------------------------------------------
 const tById=Object.create(null);tasks.forEach(t=>{tById[t.id]=t;});
 // Deliberately NOT scoped by the strips: this is the do-something-now list, and a
 // filter set to look at what is blocked must not empty the one card that says
 // where to start.
 const ready=r.ready||[];
 const rcard=el('div',{class:'card','data-card':'ready'});
 rcard.append(h2h('Ready now',
   'Tasks whose blockers are all done and whose phase is not gated — the ones /audit:run '
   +'will accept right now. Copy the command rather than retyping an id.'));
 // Nothing ready and nothing to do are different answers, and a reader deciding
 // what to work on needs to know which one they got.
 if(!ready.length)rcard.append(el('div',{class:'mut'},
   r.tasks.total?'Nothing is ready: every pending task is waiting on something, or there is nothing left to do.'
     :'No tasks yet.'));
 const RSHOW=8;
 ready.slice(0,RSHOW).forEach(id=>{const t=tById[id]||{};
  const cmd='/audit:run '+id;
  rcard.append(el('div',{class:'rdy'},el('code',{class:'rcmd'},cmd),
    el('span',{class:'rt',title:t.title||''},t.title||''),
    t.phaseId?el('span',{class:'mut'},t.phaseId):null,
    el('button',{class:'btn small',type:'button','data-copy':cmd,
      onclick:e=>ovCopy(e.currentTarget,cmd)},'Copy')));});
 // The remainder is COUNTED rather than dropped, and it names where the rest is.
 if(ready.length>RSHOW)rcard.append(el('div',{class:'mut'},
   '+'+(ready.length-RSHOW)+' more ready — see Plan & models'));
 c.append(rcard);

 // --- bugs ---------------------------------------------------------------------
 const bugs=STATE.bugs||[];
 if(bugs.length){
  const bcard=el('div',{class:'card','data-card':'bugs'});
  bcard.append(h2h('Bugs',
    'Status here is the EFFECTIVE status the totals above count: a bug materialized '
    +'into a task reads Fixed once that task is done, so the list and the pills can '
    +'never disagree.'));
  // The verdicts are read, never re-derived: `open` and `high` are decided by the
  // same Python functions the rollup counts with, so the rows and the pills above
  // cannot answer differently.
  const rows=bugs.filter(b=>OVF.bs?(OVF.bs==='!high'?(b.open&&b.high):b.status===OVF.bs):true);
  if(!rows.length)bcard.append(el('div',{class:'ovempty'},'No bug matches this filter.'));
  rows.slice(0,20).forEach(b=>{
   bcard.append(el('div',{class:'rdy'},el('span',{class:'mono'},b.id||''),
     el('span',{class:'rt',title:b.title||''},b.title||''),
     b.severity?el('span',{class:'sev'+(b.high?' high':'')},b.severity):null,
     el('span',{class:'st','data-status':b.status||''},label(b.status)),
     // A bug whose status came from its task should say where it came from, or it
     // reads as something somebody typed into the manifest by hand.
     b.taskId?el('span',{class:'mut',title:'materialized as '+b.taskId
       +(b.reported&&b.reported!==b.status?' (reported '+label(b.reported).toLowerCase()+')':'')},
       '→ '+b.taskId):null));});
  if(rows.length>20)bcard.append(el('div',{class:'mut'},'+'+(rows.length-20)+' more'));
  c.append(bcard);}

 // The theme's card order, applied to what was just drawn.
 applyCardOrder('over');
 restoreCaret(keepQ?$('#ovq'):null,caret,keepBack);}

// ---------- the Plan gate feed's prune control ----------
// THE CARD IS WHERE THE ROWS ARE SHOWN, SO THE CONTROL BELONGS THERE — the words
// are `_panel_write.prune_gate_events`'s own, and this is the half that shipped
// late: `POST /api/gate-events/prune` answered with a real verdict while a sweep
// of the page for any control mentioning it found nothing, so `/audit:logs prune`
// was the only door onto a rule the panel already served (F110).
//
// NO RULE LIVES HERE. The endpoint classifies, refuses and rewrites; this asks it
// twice — once with `dryRun` for the confirm dialog, once for real — which is the
// shape the proposals tab already uses for `plan` then `materialize`. A
// destructive button whose preview is its own effect is not a preview.
//
// THE COUNTS ARE THE WHOLE PAYLOAD THIS MAY RENDER. `audit-logs.py` refuses to
// echo a removed row's path on the argument that printing it puts it back, the
// server redacts the same cell out of the events table above (F113), and the
// answer's `path` field names the feed FILE — an absolute path under whoever ran
// it. None of the three is read here, and this card is the one
// docs/screenshots/panel-gate.png is a committed render of.
/** The feed's basename, as the confirm dialog's "what" column names it. */
const GPFEED='plan-gate-events.jsonl';
/**
 * What a prune CANNOT decide — the half of `/audit:logs prune`'s answer the panel
 * used to drop (F164).
 *
 * ONE FACT, ONE SENTENCE, WHEREVER IT IS RENDERED. `audit-logs.render` treats how
 * far back the feed reaches and what a prune cannot decide as a single statement
 * and prints them together: the `oldest` row is the number, `_HISTORY` is the
 * note, and the note is what makes the number actionable. The panel rendered the
 * number alone. Everything after the first sentence here is `audit-logs._HISTORY`
 * word for word — a case reads that constant and fails if the two ever diverge —
 * because a second wording of one fact is two facts as soon as one of them is
 * edited.
 *
 * IT IS A PERSISTENT HINT AND NOT A TOAST. The toast hides itself in under three
 * seconds and every other line on this page is one line long, so a paragraph
 * there is a claim rendered where nobody can read it — the same defect one layer
 * over. It belongs beside the age box because the sentence ends by naming age as
 * the lever, and that box is the lever.
 */
const GPNOTE='Rows naming somewhere outside this repository, and rows nothing can '
 +'parse, go either way. A row written by an older release can hold a whole shell '
 +'command in its `file` cell, or an absolute path in `reason`. Both writers are '
 +'fixed; nothing in a row records which release wrote it, so this prune keeps them '
 +'rather than guessing at a shape and removing on the guess. Age is the lever that '
 +'reaches them.';
/**
 * @type {{days: string, busy: boolean}} the control's own state.
 *
 * Hoisted out of the render for the reason OVF is: the 5s poll repaints Overview
 * whenever a verdict lands, so a threshold held in the render closure would be
 * wiped from under a reader mid-type by the very feed they are about to prune.
 * `busy` keeps a second click out while the round trip is in flight — the dialog
 * is modal, but the two API calls around it are not.
 */
const GPF={days:'',busy:false};
/**
 * How far back the feed still reaches, said so that "unknown" cannot read as zero.
 *
 * `oldestKeptDays` is the age of the OLDEST KEPT row and it is `null` — never 0 —
 * when no kept row carries a readable stamp. Those are different answers and a
 * reader acts on them differently: one can be aimed at with "older than" and the
 * other cannot be aimed at all. So each gets its own clause and neither borrows
 * the other's; a `||0` here would paint "nothing would say" as "the feed starts
 * today", which is the substitution `_gate_feed.classify` refuses at the writing
 * end for the same reason.
 *
 * `Number.isFinite` rather than `typeof x==='number'`, which admits NaN — and NaN
 * is exactly the value `plural` truncates to 0, so the loose test would put the
 * confusion back through the formatter.
 * @param {number|null} days - the answer's `oldestKeptDays`
 * @returns {string} a clause naming the reach, or naming that there is none
 */
const gpReach=days=>Number.isFinite(days)
  ?'the feed reaches back '+plural(days,'day')
  :'no kept row is stamped, so its reach is unknown';
/**
 * Ask for a preview, show it, and prune only if the reader says so.
 *
 * The dialog lists EVERY class the server returned, including the ones at zero,
 * because `_gate_feed` returns them all on purpose: a count that appears only
 * when it is non-zero cannot be told from a count nobody computed. Filtering the
 * empty ones out here would put that back.
 *
 * The toast reports what the SECOND call did, not what the preview said, and
 * names both when they differ. The gate keeps appending between the two calls —
 * that race is stated in `_gate_feed.prune`'s own docstring — so the preview is a
 * forecast and the outcome is the fact.
 * @returns {Promise<void>} resolves once the outcome has been reported; a refusal
 *   and a cancel both resolve, leaving the feed as it was
 */
async function gpPrune(){
 if(GPF.busy)return;
 const typed=GPF.days.trim();
 const days=typedNumber(typed);
 // Refused here AND at the endpoint, which is not the rule written twice: the
 // server owns what a legal threshold is and says so in `findings`, and this
 // exists so a half-typed box spends no round trip and gets its answer beside
 // the control rather than as a finding about a request nobody meant to send.
 if(typed&&(days===null||!Number.isInteger(days)||days<1)){
  toast('Older than: a whole number of days, at least 1.','err');return;}
 const body=days===null?{}:{olderThanDays:days};
 GPF.busy=true;
 try{
  const dry=await api('POST','/api/gate-events/prune',
    Object.assign({dryRun:true},body));
  if(!dry.ok){toast((dry.findings||['the feed could not be read'])[0],'err');return;}
  // Three different answers, and the first two are not failures. A feed nobody
  // has written yet and a feed with nothing left to remove both end here, said
  // apart, because `exists` is the field that separates them.
  if(!dry.exists){toast('No gate events feed yet — nothing to clean up.');return;}
  // THE CLAIM IS ABOUT THE RULE, NOT ABOUT THE FILE (F162). This used to report
  // the FILE as clean, which is the one thing a prune cannot know — the wording
  // is not quoted here, because a case downstream asserts it is gone from the
  // page and a comment is source text like any other. A row an older release
  // wrote can hold a whole shell command in `file`, and a command line resolves
  // inside the repository exactly as a relative path does — the very property
  // that made the leak invisible — so every class here reads it as belonging.
  // `_gate_feed.classify` refuses to guess at that shape and says so; what the
  // product owes instead is the reach, because age is the only lever that gets
  // at those rows and this is the number it is aimed with. `/audit:logs prune`
  // prints the same pair beside its own `oldest` row.
  if(!dry.removed){
   toast('No row breaks a rule this prune can check — '
     +gpReach(dry.oldestKeptDays)+'.');
   return;}
  const cls=dry.classes||{};
  const rows=[cfRow(GPFEED,'rows',dry.kept+dry.removed,dry.kept)].concat(
    Object.keys(cls).map(k=>cfRow(GPFEED,k,cls[k],0)));
  if(!await confirmChanges({
    title:'Clean up the gate events feed',danger:1,lock:false,verb:'Prune',
    rows:rows,
    note:'counts only — a removed row’s path is never shown, here or by '
     +'/audit:logs prune. This feed is telemetry, so the prune takes no manifest '
     +'lock and writes no journal row.'}))return;
  const done=await api('POST','/api/gate-events/prune',body);
  if(!done.ok){toast((done.findings||['the prune was refused'])[0],'err');return;}
  toast(plural(done.removed,'row')+' removed · '+plural(done.kept,'row')+' kept'
    +(done.removed===dry.removed?'':' · the preview said '+dry.removed
      +', and the gate appended in between'),'ok');
  // The events tail rides /api/runstatus and is part of runStatusKey, so one
  // tick repaints this card off the pruned file. Awaited rather than left to the
  // interval: a reader who just pressed Prune should not watch the rows they
  // removed for up to five more seconds.
  await pollRunStatus();
 }finally{GPF.busy=false;}}
/**
 * The control itself: an optional age threshold and the button that previews.
 *
 * The age box is empty by default and stays optional, which is `_gate_feed`'s
 * decision rather than this form's — out-of-repository and unreadable rows are
 * removed on evidence, while "old" is not the same claim as "does not belong", so
 * there is no default number to prefill here and inventing one would be a
 * threshold with no basis.
 * @returns {HTMLDivElement} the row of controls, ready to append to the card
 */
function gpControl(){
 const box=el('input',{type:'number',min:'1',step:'1',id:'gpdays',
   value:GPF.days,placeholder:'optional',
   'aria-label':'also remove gate events older than this many days'});
 box.addEventListener('input',()=>{GPF.days=box.value;});
 // GPNOTE comes LAST and takes its own flex line (`[data-gphint]`), so the button
 // stays beside the box it acts on rather than floating against the middle of a
 // paragraph, and the sentence gets the card's width instead of the gap between
 // two controls. The unit stays welded to the box as its own short label.
 return el('div',{class:'ovtools','data-gpctl':'1'},
   el('span',{class:'filtlbl'},'older than:'),box,
   el('span',{class:'mut small'},'days (optional)'),
   el('button',{class:'btn small',type:'button','data-gpprune':'1',
     title:'preview what a prune would remove, then confirm',
     onclick:()=>gpPrune()},'Clean up…'),
   el('span',{class:'mut small','data-gphint':'1'},GPNOTE));}
