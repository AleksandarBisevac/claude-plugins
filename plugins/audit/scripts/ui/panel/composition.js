// ---------- Composition ----------
/**
 * One phase row of the composition payload, flattened by `_composition_view`.
 *
 * @typedef {object} CompPhase
 * @property {string|null} id
 * @property {string|null} title
 * @property {string|null} status - a manifest phase status: pending, in_progress,
 *   blocked or done
 * @property {string|null} reviewModel - lifted out of the phase's review object,
 *   which is the only part of it this tab edits
 * @property {string[]} area - the phase's area tags
 * @property {string|null} reviewSkill
 * @property {number|null} priority - the tier as `_priority.tier_of` reads it, so
 *   a value the run does not honour never reaches a control. null is
 *   unprioritised, which is a class of its own rather than tier 0
 * @property {object|null} adoParent - the phase's own declaration in ONE value
 *   with three shapes: the use-fallback marker for an absent key, `null` for
 *   "hangs under nothing on purpose", or `{id, type, title, url, source,
 *   observedAt}`. The server spells absent with the marker rather than leaving
 *   the key off, because `undefined` would be a fourth thing meaning "the
 *   server did not say"
 * @property {{id: number|null, source: string, basis: string}} adoParentResolved -
 *   what the phase hangs under RIGHT NOW, from `_ado_parent.resolve` - which is
 *   not the same question as what it declares: an absent declaration resolves to
 *   the fallback and an unusable one resolves to nothing
 * @property {AdoParentBoard} adoParentBoard - what the BOARD says, which is a
 *   third question again. Both fields above are read out of the manifest, so
 *   without this one a phase the board agrees with and a phase nobody has ever
 *   compared paint the same cell
 * @property {boolean|null|*} adoTracked - the phase's own `adoTracked`
 *   declaration, and `null` is the ABSENCE of one. Null is safe here where it
 *   was not for `adoParent`: the schema types this field `boolean`, so null is
 *   not a value it can carry. Anything else that reaches this field is a stored
 *   value that is neither, and it travels verbatim so the control can say so
 * @property {{tracked: (boolean|null), basis: string}} adoTrackedResolved - the
 *   answer in force, from `_ado_tracked.resolve`. `tracked` is THREE-VALUED and
 *   `null` means nothing here has a basis to answer - read it with `atAnswer`,
 *   never with truthiness
 */

/**
 * The board side of one phase's parent, as `_panel_composition._board_parent`
 * reports it - three named states and never a live reading.
 *
 * NOTHING CACHES AN OBSERVED PARENT PER ITEM, which is why `observed` is the
 * narrow case rather than the usual one: it means a PULL wrote the declaration
 * off the board, at `observedAt`. `never-asked` is the honest majority - the
 * item is linked and nobody has compared the two sides - and it exists because
 * silence rendered as agreement is the defect this block was added for.
 *
 * @typedef {object} AdoParentBoard
 * @property {'unlinked'|'observed'|'never-asked'} state
 * @property {number|null} id - the observed parent, and only in `observed`
 * @property {string|null} observedAt - when the board was read, when it recorded it
 * @property {string} basis - the server's sentence for that state
 * @property {string} refresh - the command that asks the board
 */

/**
 * The two things the parent control needs that are not per-phase: what the
 * fallback resolves to, and whatever `/audit:sync parents` last cached.
 *
 * @typedef {object} AdoParents
 * @property {{id: number|null, source: string}} fallback - resolved, never read
 *   off `parentWorkItem` a second time
 * @property {Array<{id: number, type: ?string, title: ?string, state: ?string, url: ?string}>} candidates -
 *   cached evidence and never an authority: an id missing from it is not a wrong
 *   parent, only one created since the fetch
 * @property {string|null} fetchedAt - when the cache was written; null when
 *   there is no cache or it recorded no moment
 * @property {'absent'|'empty'|'items'} cache - which of the two empties this is.
 *   "nobody looked" and "the board had none in scope" are different answers and
 *   a menu that rendered both as zero options would say the second
 * @property {string} basis - the sentence for that state, built server-side so
 *   there is one wording rather than one per surface
 * @property {string} refresh - the command that re-derives the cache
 */

/**
 * One task row of the composition payload, in document order and carrying the id
 * of the phase that owns it.
 *
 * Four of these fields — risk, commit, startedAt and completedAt — are here for
 * the Overview rollup rather than for this tab, which ignores what it does not
 * edit. They ride this payload because it is the same manifest read either way.
 *
 * @typedef {object} CompTask
 * @property {string|null} id
 * @property {string|null} title
 * @property {string|null} phaseId
 * @property {string|null} status
 * @property {string|null} model
 * @property {string[]|null} skills - null is an ANSWER ("none applies"), not an
 *   absence, and it has to survive every accessor that touches it
 * @property {string|null} risk
 * @property {string|null} commit
 * @property {string|null} startedAt
 * @property {string|null} completedAt
 */

// ---------- model suggestions (mc) ----------
/**
 * A model id offered by the completion menus, and where it was seen.
 *
 * @typedef {object} ModelItem
 * @property {string} name - the model id, exactly as its source spells it
 * @property {'manifest'|'rates'|'ledger'} source - the most local source that
 *   knows it, which is what its badge shows
 * @property {string} description - what that source knows: how many rows route to
 *   it, what it costs, or how much it has metered
 */

/**
 * Memo for `modelItems`. Null means "not built yet", never "no models found" —
 * an empty union would be cached as an empty array.
 * @type {ModelItem[]|null}
 */
let MITEMS=null;
/**
 * Every model id worth offering, unioned from three sources and badged by which.
 *
 * One union, three sources, each named: the models the MANIFEST already routes
 * to, the ids the RATE TABLE prices, and what the LEDGER has actually metered.
 * The badge is the point — a model only one source spells is usually one slip
 * from its cousins, and the validator cannot arbitrate that, being an offline
 * shape-checker with no ledger and no config. So the cross-source view lives
 * here, on the one surface that can see all three.
 *
 * A name in several sources keeps its most local badge: manifest first, then
 * rates, then ledger. `_default` is not offered — it is the fallback price, not
 * a model anyone should route to by name.
 *
 * Cached, because a menu opens on a keystroke. The cache is dropped by hand
 * wherever STATE or USAGE may have moved under it — a save re-render, a disk
 * refresh — rather than expiring on a timer.
 *
 * @returns {ModelItem[]} manifest names first, then rate names, then ledger
 *   names, each group sorted and each name appearing once
 */
/**
 * The highest tier the phase-priority control offers.
 *
 * The project's `priority.maxTier` when it sets one, otherwise the DEFAULT the
 * server hands over in `STATE.defaults` — which is `hooks/_config.py`'s dict, the
 * one place the whole config's shape is stated. A literal here would be a second
 * copy of that setting, free to disagree with the validator and with
 * `set-priority.py` about what the panel is allowed to offer.
 *
 * It is a CEILING ON THE MENU, not on the value: nothing is clamped, so a phase
 * already pinned above it keeps its tier and the control offers that tier too.
 *
 * @returns {number} a positive integer; the shipped default when the config and
 *   the defaults block are both unusable, because a control with no range is a
 *   control that silently unpins every phase. That last-resort literal is the
 *   one value written twice in two languages, so the agreement is PINNED by a
 *   case against `hooks/_config.py` rather than asserted in this sentence
 */
function prioMax(){
 const cfg=((STATE||{}).config||{}).priority||{};
 const def=((STATE||{}).defaults||{}).priority||{};
 for(const v of [cfg.maxTier,def.maxTier])
  if(typeof v==='number'&&Number.isInteger(v)&&v>=1)return v;
 return 9;}

// ---------- where a phase hangs on the board (ap) ----------
// The per-phase half of `phases[].adoParent`. The connector CARD cannot hold
// this control: `PUT /api/ado` writes `meta.ado` and nothing else, so a card
// offering a per-phase edit would be describing a save it cannot make. What the
// card holds is the FALLBACK id; what this holds is the phase's own answer.
//
// Everything below is a pure function of the payload, on purpose: the option
// list, the choice a stored declaration maps to and the patch value a choice
// maps back to are the parts that can be wrong without looking wrong, so they
// are reachable from tools/ui-tests/ado-panel.test.mjs rather than asserted as
// source text. The DOM work stays in the row builder.

/**
 * The marker that spells "no declaration at all" in a patch.
 *
 * A FRESH object each call, mirroring `_ado_parent.use_fallback()` — one shared
 * instance would be handed to every row and one row's edit would become every
 * later row's marker. The key is the one value written in two languages here,
 * and a case pins this literal against `_ado_parent._USE_FALLBACK_KEY`.
 *
 * @returns {{useFallback: true}} a new marker
 */
function apUseFallback(){return{useFallback:true};}
/**
 * Is `v` the marker, and nothing else?
 *
 * Strict on both halves, as the Python is: `{useFallback:1}` is not it, and a
 * marker carrying any other key is a declaration somebody wrote.
 *
 * @param {*} v - a value off the payload or off a patch
 * @returns {boolean} true only for the marker itself
 */
function apIsFallback(v){return !!v&&typeof v==='object'&&!Array.isArray(v)
 &&Object.keys(v).length===1&&v.useFallback===true;}
/**
 * What the fallback resolves to, in words, for the option that offers it.
 *
 * NAMING IT IS THE POINT. "use the fallback" alone asks the reader to remember
 * a number that lives on another card; with the id in the option they can see
 * what choosing it does. When nothing is set that is also an answer and it is
 * said outright, rather than left as an option that looks the same either way.
 *
 * @param {{id: (number|null)}} fb - `adoParents.fallback`
 * @returns {string} the words after the label
 */
function apFallbackWords(fb){
 return (fb&&fb.id!=null)?('#'+fb.id)
  :'nothing is set (meta.ado.parentWorkItem is empty)';}
// How many characters an option in a phase-row cell may SHOW. F211: those cells
// carry ONE width declaration, in `panel-css/composition.css` under the
// `td.phparent` selector — the selector is not quoted here, because a pin counts
// that literal and a comment reproducing it makes the page carry it twice. A
// closed <select> clips — it does not wrap and it does not ellipsise — so a
// longer label is a phrase cut off mid-word. The committed screenshot is where
// the figure comes from: the
// parent picker rendered `use the fallback —` out of a label three times that,
// which is eighteen characters of a nine-rem control.
//
// IT IS A CHARACTER COUNT AND THEREFORE APPROXIMATE, which is a limit worth
// stating rather than dressing up: the panel's face is proportional, so `#111`
// and `WWWW` do not occupy the same width. It is deliberately set at what was
// OBSERVED to fit rather than at a computed ideal, and its job is to stop a label
// written as a sentence — the mistake that actually happened, twice — not to
// settle a two-character argument. The full text is never lost: `fillOptions`
// moves it to the option's `title`.
//
// THE LABELS LEAD WITH WHAT DECIDES, which is what makes truncation safe rather
// than merely tidy. `apCandidateLabel` opens with the id and the type — the two
// things the hierarchy check grades on — and the work item's title, which is
// unbounded because somebody else typed it, is the part that gets cut. The
// fallback option was reordered for the same reason: it used to open with `use
// the fallback — ` and spend the whole budget before reaching the id.
const PHCELL_OPTION_CHARS=18;
/**
 * One cached candidate as an option label.
 *
 * The type is in it because the hierarchy check grades a link BY TYPE, so a
 * reader choosing between a Feature and an Epic is choosing between two
 * different verdicts. The candidate's own board STATE is in it for the neighbour
 * of that reason: `_candidate_row` has always carried it and this label has
 * always dropped it, so a closed Feature and an active one were one option, and
 * hanging a phase under finished work is the mistake nothing else on this screen
 * would catch.
 *
 * IT IS LABELLED RATHER THAN JOINED IN AS A FOURTH FRAGMENT. `#77 · Epic ·
 * Payments · Closed` reads as a title that ends in a word; `state Closed` cannot.
 *
 * No moment rides here: every option in this menu came out of one cache, and the
 * line under the table (`.apcache`) already says when that cache was fetched and
 * how it was scoped. A per-option stamp would be that sentence fifty times.
 *
 * A candidate that recorded NONE of the three says so instead of showing a bare
 * number that could be anything - and "nothing recorded but the id" is computed
 * from the same list it describes, so a cache carrying only a state cannot make
 * it a false sentence.
 *
 * @param {{id: number, type: ?string, title: ?string, state: ?string}} c - a
 *   cached candidate
 * @returns {string} the option's label
 */
function apCandidateLabel(c){
 const bits=[c.type,c.title].filter(Boolean);
 if(c.state)bits.push('state '+c.state);
 return '#'+c.id+(bits.length?(' · '+bits.join(' · ')):' · nothing recorded but the id');}
/**
 * Which option a stored declaration selects.
 *
 * An id the cache does not carry lands on "other" WITH THE BOX FILLED, which is
 * the degrade this needs: the cache is a convenience, so a parent named before
 * the last fetch — or after it — must still show as the parent it is rather
 * than silently reading as "use the fallback".
 *
 * @param {*} decl - the row's `adoParent`
 * @param {Array<{id: number}>} candidates - the cached list
 * @returns {string} an option value: 'fallback', 'none', 'other' or an id
 */
function apChoiceOf(decl,candidates){
 if(apIsFallback(decl))return 'fallback';
 if(decl===null||decl===undefined)return 'none';
 const id=(typeof decl==='object'&&!Array.isArray(decl))?decl.id:null;
 if(typeof id!=='number'||!Number.isInteger(id)||id<1)return 'other';
 return (candidates||[]).some(c=>c.id===id)?String(id):'other';}
/**
 * The patch value one choice stands for — or the reason there is none.
 *
 * `write:false` carries the sentence saying what is missing, because the one
 * thing a control must not do is quietly write nothing: "other id…" chosen with
 * an empty box is an unfinished edit, and a save that silently skipped it would
 * report success for a change nobody made.
 *
 * A candidate pick carries the CACHE'S OWN BASIS — the type, the title, the url
 * and the moment they were observed — while a typed id carries none of it. That
 * asymmetry is the honest one: nobody looked at a typed id, and a stamp saying
 * otherwise would be provenance invented for somebody else's record.
 *
 * @param {string} choice - the select's value
 * @param {AdoParents} cache - the payload's `adoParents` block
 * @param {string} typed - the number box's raw text
 * @returns {{write: boolean, value: *, why: string}} `value` is only meaningful
 *   when `write` is true
 */
function apPatchValue(choice,cache,typed){
 if(choice==='fallback')return{write:true,value:apUseFallback(),why:''};
 if(choice==='none')return{write:true,value:null,why:''};
 if(choice==='other'){
  // Through `typedNumber`, which is the same rule the field-template box uses:
  // a bare Number() would read '4e2' as work item 400 and '0x10' as 16, and
  // would hang the phase under an id nobody typed without saying anything.
  const n=typedNumber(typed);
  if(n===null||!Number.isInteger(n)||n<1)
   return{write:false,value:undefined,
    why:'type a work item id (a positive whole number) — nothing is saved for '
     +'this phase until you do'};
  return{write:true,value:{id:n,source:'declared'},why:''};}
 const c=((cache||{}).candidates||[]).find(x=>String(x.id)===choice);
 if(!c)return{write:false,value:undefined,
  why:'that candidate is no longer in the cached list — re-run '
   +((cache||{}).refresh||'/audit:sync parents')+' or name the id directly'};
 const d={id:c.id,source:'declared'};
 if(c.type)d.type=c.type;
 if(c.title)d.title=c.title;
 if(c.url)d.url=c.url;
 if((cache||{}).fetchedAt)d.observedAt=cache.fetchedAt;
 return{write:true,value:d,why:''};}
/**
 * The option list, in the order the menu shows it.
 *
 * The fixed three always exist — falling through, hanging under nothing, and
 * naming an id by hand — because each is a real answer whether or not anything
 * was ever cached. The candidates sit between them, and WITH NO CACHE THERE ARE
 * SIMPLY NONE: the menu never renders "no candidates cached" and "this board
 * has no Features" as the same empty group, because neither is an option at
 * all. Which of the two it is, is said once in the line under the table.
 *
 * @param {AdoParents} cache - the payload's `adoParents` block
 * @returns {Array<[string, string]>} [value, label] pairs for `fillOptions`
 */
function apOptions(cache){
 const c=cache||{};
 return [['fallback','fallback: '+apFallbackWords(c.fallback)],
   ...(c.candidates||[]).map(x=>[String(x.id),apCandidateLabel(x)]),
   ['none','none — uncategorised on purpose'],
   ['other','other id…']];}
// The board states this build knows, spelled once: `apBoardState` normalises
// against it and `apBoardWords` renders off that, so the attribute a gate reads
// and the words a person reads can never name different states.
const AP_BOARD=['unlinked','observed','never-asked'];
/**
 * Which board state this row is in, with anything else named as such.
 *
 * A value outside the list is a DEFECT and not an old server - the payload
 * comes from the process serving this page - so it reports `not-reported`
 * rather than falling back to the commonest state, which would be a guess
 * wearing the words of an answer.
 *
 * @param {AdoParentBoard} b - the row's `adoParentBoard`
 * @returns {string} one of AP_BOARD, or 'not-reported'
 */
function apBoardState(b){
 const st=(b||{}).state;
 return AP_BOARD.includes(st)?st:'not-reported';}
/**
 * The board half of the parent cell, in one short line.
 *
 * THE DECLARATION IS THE OTHER HALF AND IT IS ALREADY PAINTED, which is what
 * makes the silence dangerous: a select reading `#101` with nothing beside it
 * looks the same whether the board agrees or nobody ever asked, and on the
 * board this was found on it was the second (F101). So `never-asked` says so
 * outright, and it is not an error - nothing is wrong with a phase nobody has
 * compared; what was wrong was showing it as agreement.
 *
 * The date is cut to its day: the cell is one control wide, and the moment is
 * on the title in full.
 *
 * @param {AdoParentBoard} b - the row's `adoParentBoard`
 * @returns {string} the words for the muted line under the control
 */
function apBoardWords(b){
 const st=apBoardState(b);
 if(st==='observed')return 'board: #'+b.id
   +(b.observedAt?(' · seen '+b.observedAt.slice(0,10)):' · moment not recorded');
 if(st==='unlinked')return 'board: no work item yet';
 if(st==='never-asked')return 'board: not asked';
 return 'board: not reported';}

// ---------- whether a phase is on the board at all (at) ----------
// THE QUESTION ONE STEP BEFORE THE ONE ABOVE, and that is why both levers share
// a cell with this one on top: where a phase hangs is only a question once it
// belongs on the board, and an operator who has just said "keep this off the
// board" should not read a parent picker as the next thing to fill in.
//
// IT IS A DECLARATION AND NOT A LINK, which is the whole reason the key exists.
// `phase.ado` is an `adoLink` that sync writes, and the `imported` half of
// `adoParent` is a record of somebody's board; a phase declaring an intention
// in either would be authoring into a record it does not own. So this control
// offers the three answers a PERSON can give, and never anything a fetch found.
//
// Pure functions of the payload, for the reason the `ap` block gives: which
// option a stored value selects and which patch value a choice stands for are
// the parts that can be wrong without looking wrong, so they are reachable from
// tools/ui-tests/ado-panel.test.mjs rather than asserted as source text.

// The three answers `_ado_tracked` can give, spelled once: `atAnswer` normalises
// against this list and `atWords` renders off that, so the attribute a gate
// reads and the words a person reads can never name different answers. Same
// arrangement as AP_BOARD, and for the same failure.
const AT_ANSWERS=['tracked','untracked','unanswered'];
// The option value for a stored declaration that is neither true nor false.
// Named because two places compare against it and a retyped literal in the
// second is how a control comes to offer an option nothing selects.
const AT_UNREADABLE='unreadable';
// The words for an absent declaration, spelled ONCE: the menu offers it as an
// option and the confirm dialog renders it as a `from` value, and those are two
// readers of one sentence. Retyped, the two would be free to disagree about
// which way an absent declaration goes — and the direction a reader could get
// wrong is the one that puts work on somebody's shared board.
const AT_DEFAULT_WORDS='no declaration';
// The same answer with room to breathe, DERIVED so the two cannot disagree about
// which way an absent declaration goes. Two readers, two width budgets: the menu
// sits in a 9rem select and the confirm dialog has a whole row. The first version
// used one long sentence in both and the screenshot showed why — the closed
// control read `no declaration — t`, clipped mid-word into something that says
// nothing. Every other option here is short for the same reason; the full
// sentence rides the control's `title` and the muted line under it.
const AT_DEFAULT_SENTENCE=AT_DEFAULT_WORDS+' — tracked, the default';
/**
 * Which of the three answers a resolved row carries.
 *
 * `tracked` IS THREE-VALUED AND IS READ BY IDENTITY. `null` means nothing here
 * has a basis to answer — a stored value that is neither true nor false, or an
 * index stub whose body was never read — and a truthiness test would file it
 * under "untracked", which is a claim nobody made and exactly the false
 * confidence this key was added to remove. Anything outside the three reports
 * `not-reported` rather than borrowing the commonest one's word: the payload
 * comes from the process serving this page, so an absent block is a defect and
 * not an old server.
 *
 * @param {{tracked: (boolean|null)}} r - the row's `adoTrackedResolved`
 * @returns {string} one of AT_ANSWERS, or 'not-reported'
 */
function atAnswer(r){
 const t=(r||{}).tracked;
 if(t===true)return AT_ANSWERS[0];
 if(t===false)return AT_ANSWERS[1];
 if(t===null)return AT_ANSWERS[2];
 return 'not-reported';}
/**
 * The answer in force, in one short line under the control.
 *
 * WHAT IT INHERITED FROM IS HALF THE SENTENCE. A phase that declares nothing is
 * tracked, and a phase that declares `true` is tracked, and those are the same
 * answer from two different places — so a line that printed only the answer
 * would show the default as if somebody had chosen it. The qualifier is read
 * off the DECLARATION and never off the rule: it says where the answer came
 * from, and `atAnswer` alone says what the answer is, so the two cannot
 * disagree about a row.
 *
 * The server's full sentence rides the control's `title`; this is the part that
 * fits under a 9rem control.
 *
 * @param {{tracked: (boolean|null)}} r - the row's `adoTrackedResolved`
 * @param {*} decl - the row's `adoTracked`, for where the answer came from
 * @returns {string} the words for the muted line under the control
 */
function atWords(r,decl){
 const a=atAnswer(r);
 if(a==='unanswered')return 'tracking: not answered — nothing here has a basis';
 if(a==='not-reported')return 'tracking: not reported';
 const how=(decl===true||decl===false)?'declared':'the default';
 return 'tracking: '+(a==='tracked'?'on the board':'off the board')+' — '+how;}
/**
 * Which option a stored declaration selects.
 *
 * A value that is neither boolean nor absent lands on its OWN option rather
 * than on the default's, which is the degrade this needs: `adoTracked: 1` is a
 * typo, and a menu that showed it as "no declaration" would paint the default
 * over somebody's attempt to keep a phase off a board.
 *
 * @param {*} decl - the row's `adoTracked`
 * @returns {string} an option value: 'default', 'true', 'false' or AT_UNREADABLE
 */
function atChoiceOf(decl){
 if(decl===true)return 'true';
 if(decl===false)return 'false';
 if(decl===null||decl===undefined)return 'default';
 return AT_UNREADABLE;}
/**
 * The option list, in the order the menu shows it.
 *
 * THE THREE ARE FIXED because each is a real answer about every phase: nothing
 * here is cached, fetched or scoped, so unlike the parent menu there is no
 * state in which one of them is unavailable. The unreadable option is added
 * only for the row that is in it, and it is not an answer — picking it writes
 * nothing, and the note under the control says so.
 *
 * @param {*} decl - the row's `adoTracked`
 * @returns {Array<[string, string]>} [value, label] pairs for `fillOptions`
 */
function atOptions(decl){
 const fixed=[['default',AT_DEFAULT_WORDS],
   ['true','on the board'],
   ['false','off the board']];
 return atChoiceOf(decl)===AT_UNREADABLE
  ?[[AT_UNREADABLE,'unreadable value'],...fixed]
  :fixed;}
/**
 * The patch value one choice stands for — or the reason there is none.
 *
 * `null` IS THE CLEAR HERE, AND IT IS A VALUE ON THE PARENT ROW. The difference
 * is a fact about the schema rather than a convention: `adoTracked` is typed
 * `boolean`, so null is not a value it can hold and the key's absence is the
 * only thing it can mean — which is why this needs no marker where `adoParent`
 * did. `_apply_ado_tracked` pops the key on null, and the payload spells an
 * absent declaration `null` too, so what the row shows for "nothing declared"
 * is exactly what a save sends to put it back.
 *
 * @param {string} choice - the select's value
 * @returns {{write: boolean, value: *, why: string}} `value` is only meaningful
 *   when `write` is true
 */
function atPatchValue(choice){
 if(choice==='default')return{write:true,value:null,why:''};
 if(choice==='true')return{write:true,value:true,why:''};
 if(choice==='false')return{write:true,value:false,why:''};
 return{write:false,value:undefined,
  why:'this phase declares something that is neither true nor false — pick one '
   +'of the three; nothing is saved for this phase until you do'};}

function modelItems(){
 if(MITEMS)return MITEMS;
 const out=new Map();
 const add=(name,source,description)=>{
  if(name&&!out.has(name))out.set(name,{name,source,description});};
 const comp=(STATE&&STATE.composition)||{phases:[],tasks:[]};
 // Keyed by MODEL NAME, which the schema declares plain free text.
 const useT=Object.create(null),useP=Object.create(null);
 (comp.tasks||[]).forEach(t=>{if(t.model)useT[t.model]=(useT[t.model]||0)+1;});
 (comp.phases||[]).forEach(p=>{if(p.reviewModel)useP[p.reviewModel]=(useP[p.reviewModel]||0)+1;});
 [...new Set([...Object.keys(useT),...Object.keys(useP)])].sort().forEach(m=>{
  const bits=[];
  if(useT[m])bits.push(plural(useT[m],'task'));
  if(useP[m])bits.push(plural(useP[m],'review'));
  add(m,'manifest','used by '+bits.join(', '));});
 const rates=Object.assign({},(((STATE||{}).defaults||{}).usage||{}).pricing||{},
   (((STATE||{}).config||{}).usage||{}).pricing||{});
 Object.keys(rates).sort().forEach(m=>{
  if(m==='_default')return;
  const r=rates[m]||{};
  add(m,'rates','$'+(r.in??'?')+' in / $'+(r.out??'?')+' out per MTok');});
 if(USAGE&&USAGE.facts&&USAGE.facts.length){
  const tot=new Map();
  for(const f of USAGE.facts)tot.set(f[F.model],(tot.get(f[F.model])||0)+f[F.tokens]);
  [...tot.keys()].sort().forEach(m=>{
   if(m)add(m,'ledger',uTok(tot.get(m))+' tokens in this ledger');});}
 return (MITEMS=[...out.values()]);}
/**
 * Are two model ids one slip apart?
 *
 * One slip means case-insensitively equal but spelled differently, or one
 * substitution, insertion, deletion or ADJACENT transposition away — the four
 * classic typo shapes. The cap at one slip is a false-positive discipline: at two
 * edits one real name reaches another real name, and every hit would be noise.
 *
 * Identical strings are NOT a near miss. The caller is looking for a spelling
 * that disagrees with another spelling, and agreement is the normal case.
 *
 * Symmetric in its arguments, which the caller relies on by comparing each pair
 * in one direction only.
 *
 * The same predicate is `_model_near_miss` in `_manifest_typos.py`, which the
 * offline validator uses. It is spelled a second time here only because this half
 * runs in a browser — the two have to keep agreeing, or the panel and the
 * validator will reach different verdicts about one pair of names.
 *
 * @param {string} a - one model id
 * @param {string} b - the other model id
 * @returns {boolean} true when they are one slip apart
 */
function mdNear(a,b){if(a===b)return false;
 const x=a.toLowerCase(),y=b.toLowerCase();
 if(x===y)return true;
 if(Math.abs(x.length-y.length)>1)return false;
 if(x.length===y.length){const d=[];
  for(let i=0;i<x.length;i++)if(x[i]!==y[i])d.push(i);
  if(d.length===1)return true;
  return d.length===2&&d[1]===d[0]+1&&x[d[0]]===y[d[1]]&&x[d[1]]===y[d[0]];}
 const shorter=x.length<y.length,s=shorter?x:y,l=shorter?y:x;
 let i=0,j=0,used=false;
 while(i<s.length){if(s[i]===l[j]){i++;j++;continue;}
  if(used)return false;used=true;j++;}
 return true;}
/**
 * Models the manifest spells that nothing else knows, each with the name it is
 * one slip from.
 *
 * The three-source half of the typo check: a model the manifest routes to that
 * NO other source knows, sitting one slip from a name the rates or the ledger do
 * know. A name the rate table already prices is never flagged, however odd it
 * looks — being priced is the evidence that it is meant.
 *
 * Non-blocking by design. The panel cannot know which spelling was intended, only
 * that two sources disagree by one character, so this is a note and never a gate.
 *
 * @returns {{model: string, near: string}[]} sorted by the manifest spelling;
 *   `near` is the alphabetically first neighbour when a name is close to several
 */
function modelHints(){
 const manifest=new Set(),other=new Set();
 const comp=(STATE&&STATE.composition)||{phases:[],tasks:[]};
 (comp.tasks||[]).forEach(t=>{if(t.model)manifest.add(t.model);});
 (comp.phases||[]).forEach(p=>{if(p.reviewModel)manifest.add(p.reviewModel);});
 const rates=Object.assign({},(((STATE||{}).defaults||{}).usage||{}).pricing||{},
   (((STATE||{}).config||{}).usage||{}).pricing||{});
 Object.keys(rates).forEach(m=>{if(m!=='_default')other.add(m);});
 if(USAGE&&USAGE.facts)USAGE.facts.forEach(f=>{if(f[F.model])other.add(f[F.model]);});
 const out=[];
 [...manifest].sort().forEach(m=>{
  if(other.has(m))return;              // spelled the same somewhere real
  const near=[...other].filter(o=>mdNear(m,o)).sort();
  if(near.length)out.push({model:m,near:near[0]});});
 return out;}
/**
 * Skill names the manifest spells that the discovery scan has never seen.
 *
 * The inventory half of the skills story: a name the manifest spells — in a
 * task's skills, or in an area's defaults, which ride the composition payload for
 * exactly this — that the DISCOVERY scan does not know. Shaped like modelHints on
 * purpose: the same muted note, the same cap, a hint and never a gate.
 *
 * No near-miss requirement here, because the validator already runs the
 * intra-manifest typo check offline. What only the panel can see is the
 * INVENTORY — which names actually resolve on this machine.
 *
 * Silent when discovery found nothing at all. Against an empty inventory every
 * name would read as unknown, and the note would then be reporting a failed scan
 * while looking like a report about the manifest.
 *
 * @returns {string[]} sorted, and empty both when every spelled name resolves and
 *   when there was no inventory to judge against — the two are indistinguishable
 *   here on purpose, because neither is something to act on
 */
function skillHints(){
 if(!REG.skills||!REG.skills.length)return[];
 const known=new Set(REG.skills.map(s=>s.name));
 return spelledSkills().filter(n=>!known.has(n));}
/**
 * Every skill name the manifest spells, sorted — the input to both notes below.
 *
 * @returns {string[]} sorted and deduped; empty when the manifest names none
 */
function spelledSkills(){
 const comp=(STATE&&STATE.composition)||{tasks:[]};
 const spelled=new Set();
 (comp.tasks||[]).forEach(t=>{(Array.isArray(t.skills)?t.skills:[]).forEach(s=>spelled.add(s));});
 (comp.areaSkills||[]).forEach(s=>spelled.add(s));
 return [...spelled].sort();}
/**
 * Which portability tier this project is on, read the way every other setting is.
 *
 * The shipped default arrives in `STATE.defaults`, so there is no second copy of
 * it here — a literal would be a fourth statement of a value the config schema,
 * the validator and the hooks' DEFAULTS already agree on.
 *
 * @returns {string} one of the validator's PORTABILITY_MODES
 */
function portabilityMode(){
 const cfg=(STATE&&STATE.config)||{},def=(STATE&&STATE.defaults)||{};
 return cfg.portability??def.portability??'strict';}
/**
 * Whether a discovered row may be OFFERED.
 *
 * `!==false` and not `===true` on purpose: an UNKNOWN verdict is not a refusal.
 * Hiding a row whose verdict could not be reached would turn a missing basis into
 * a decision, which is the one thing the grading refuses to do itself.
 *
 * @param {{travels?: boolean|null}} row
 * @returns {boolean}
 */
function travels(row){return !row||row.travels!==false;}
/**
 * The rows a picker may offer: everything under 'warn' and 'off', and only what a
 * clone would load under 'strict'.
 *
 * The TABLE below still lists every row — this narrows what may be CHOSEN, which
 * is a different question. A list that quietly shrank would read as "you do not
 * have that skill" and send its reader to debug discovery.
 *
 * @returns {Array<Object>} rows from REG.skills
 */
function pickableSkills(){
 const all=REG.skills||[];
 return portabilityMode()==='strict'?all.filter(travels):all;}
/**
 * The names this manifest spells that a clone of this repository would NOT load.
 *
 * Rendered beside `skillHints`, and separate from it because they are different
 * problems with different repairs: that one is a name nothing here can find, this
 * one is a name that resolves perfectly well HERE and nowhere else. Predicting the
 * refusal is the point — under 'strict' the alternative is teaching by refusal at
 * save time, after the choice has been made.
 *
 * @returns {Array<{name: string, basis: string}>} sorted; empty both when every
 *   spelled name travels and when there was no inventory to judge against
 */
function portabilityHints(){
 if(!REG.skills||!REG.skills.length||portabilityMode()==='off')return[];
 const by=new Map((REG.skills||[]).map(s=>[s.name,s]));
 return spelledSkills().map(n=>by.get(n)).filter(s=>s&&s.travels===false)
   .map(s=>({name:s.name,basis:s.travelsBasis||''}));}
/**
 * A one-skill box with a completion menu, for the settings that take a single
 * skill rather than a list.
 *
 * Reports every keystroke and not only a menu choice, because discovery is an
 * inventory rather than a whitelist: a name typed by hand is as legitimate as one
 * picked from the list, and a skill can be installed after this page was served.
 *
 * An empty box reports null rather than an empty string, so "no skill here" is
 * written as an absence and the key comes out of the manifest.
 *
 * @param {string|null|undefined} current - the saved value to start from
 * @param {(name: string|null) => void} onChange - handed the trimmed name, or
 *   null the moment the box is empty
 * @param {string} [ariaName] - accessible name for the box; the visible words
 *   beside it name a whole row, not this control
 * @returns {HTMLElement} the box inside its menu wrapper
 */
function skillPicker(current,onChange,ariaName,hook){
 // `hook` stamps a data- attribute so a caller can be REACHED by name. The
 // review-skill picker and the task adder both start their placeholder with
 // "search a skill", so a selector on that text plus `.first()` resolved by
 // document order - which held only while the config cards were above the table.
 // Putting the table first made the same selector land on an adder inside a
 // collapsed phase, and the browser gate spent its timeout on an invisible
 // control. A styling- or copy-based hook is a hook bound to a layout decision.
 const inp=el('input',{value:current??'',placeholder:'search a skill…  (empty = none)',
   'aria-label':ariaName||'search a skill'});
 if(hook)inp.setAttribute('data-skillpick',hook);
 inp.addEventListener('input',()=>onChange(inp.value.trim()||null));
 return comboWrap(inp,()=>pickableSkills(),(name,close)=>{inp.value=name;onChange(name);close();});}
/**
 * The three-state skill list for one task.
 *
 * A task's skills say one of three different things, and all three have to be
 * writable and to look different from each other: a list of chips; an EMPTY row,
 * carrying the "none applies" affordance that writes the explicit null; and the
 * opted-out state itself, which gets a muted chip saying so rather than an empty
 * row that looks merely unconsidered.
 *
 * Adding a skill while opted out replaces the null — that is "changed my mind".
 * Clearing the opt-out chip goes back to the empty list, which is unconsidered
 * again and not "no skills apply".
 *
 * The chip buttons prevent the default on mousedown, which stops the press from
 * pulling focus out of the add box; a focus change there closes the completion
 * menu, so the click would land on a box that had already moved.
 *
 * @param {() => string[]|null} getArr - reads the current value; null has to
 *   arrive intact, since it is the opt-out and not an absence
 * @param {(next: string[]|null) => void} setArr - hands back a new array, or null
 *   to opt out
 * @param {string} [ariaName] - accessible name for the add box; the callers fold
 *   the task id into it, because the column header names every one of these
 *   identically
 * @returns {HTMLDivElement} the chips above the add box
 */
function skillChips(getArr,setArr,ariaName){
 const box=el('div',{class:'chipwrap'}),chips=el('div',{class:'chips'});
 const inp=el('input',{placeholder:'search a skill to add…',
   'aria-label':ariaName||'add a skill'});
 const draw=()=>{chips.textContent='';const cur=getArr();
   if(cur===null){chips.append(el('span',{class:'chip optout'},'none — opted out',
     el('button',{title:'clear the opt-out (back to unconsidered)',
       onmousedown:e=>{e.preventDefault();setArr([]);draw();}},'×')));
    return;}
   (cur||[]).forEach((v,i)=>chips.append(
    el('span',{class:'chip'},v,el('button',{onmousedown:e=>{e.preventDefault();const a=getArr().slice();a.splice(i,1);setArr(a);draw();}},'×'))));
   if(!(cur||[]).length)chips.append(el('button',{class:'chip ghosted optnone',type:'button',
     title:'write skills: null — "no skills apply here" is an answer, and it also stops the area default',
     onmousedown:e=>{e.preventDefault();setArr(null);draw();}},'none applies'));};
 const add=(name,close)=>{const n=(name||'').trim();
   if(n){const a=(getArr()||[]).slice();if(!a.includes(n)){a.push(n);setArr(a);draw();}}
   inp.value='';if(close)close();};
 const combo=comboWrap(inp,()=>pickableSkills().filter(s=>!(getArr()||[]).includes(s.name)),add,add);
 draw();box.append(chips,combo);return box;}
/**
 * Composition's filter state, held OUT here rather than in renderComp's closure.
 *
 * Two reasons, and the second is the one that made it necessary: a re-render —
 * after a save, or a poll — used to drop you back to the unfiltered table; and
 * Overview needs to be able to hand this tab a phase to open.
 *
 * `apply` is published by renderComp so that a caller can change this state and
 * have the view on screen act on it WITHOUT being rebuilt. Rebuilding would throw
 * away whatever is half-typed in the composition form, which is the same mistake
 * the run-status poll was fixed for. It is null until renderComp has run once.
 *
 * @type {{q: string, status: string, needs: boolean,
 *   open: Object<string, boolean>, apply: (() => void)|null}}
 */
const COMPF={q:'',status:'',needs:false,open:{},apply:null};
/**
 * Open the Composition tab scoped to one phase.
 *
 * Overview's way in. The other filters are cleared rather than left alone,
 * because a status filter or a "needs skills" filter still standing from earlier
 * could hide the very phase this was asked to show — arriving at an empty table
 * is worse than arriving at an unfiltered one.
 *
 * The view is asked to act on the new state rather than being rebuilt, which is
 * what keeps a half-typed form alive across the jump.
 *
 * @param {string} pid - the phase id to search for and expand
 * @returns {void}
 */
function openInComp(pid){COMPF.q=pid;COMPF.status='';COMPF.needs=false;COMPF.open[pid]=true;
 if(COMPF.apply)COMPF.apply();showTab('comp');}
/**
 * Build the Composition tab: the manifest's routing levers, as one table.
 *
 * What this tab collects is a PATCH and never a document. Only the values that
 * were actually touched go into it, so a save sends the edits rather than a
 * rewritten manifest — which is what stops a field nobody opened from being
 * reformatted, reordered or normalised by a round trip through this form.
 *
 * The phases and their tasks share one collapsible table rather than a card each,
 * because everything here has to stay readable on a manifest with dozens of
 * phases. The filter state lives in COMPF so that it survives the re-render, and
 * this function republishes COMPF.apply on every build — the previous closure
 * refers to elements that have just been thrown away.
 *
 * A successful save re-renders from the state the server hands back rather than
 * from the patch. Without that the form kept showing the values that were typed
 * rather than the values on disk: indistinguishable while they agree, and
 * silently wrong the moment the server normalises one or refuses part of a patch.
 *
 * @returns {void} written into the #comp view. The manifest is untouched until
 *   Save is pressed and its confirm dialog is answered
 */
/**
 * Where a phase sits in the reading order, and whether its plan is still open.
 *
 * `segOf` is the Overview's classifier and the report's, and it is REUSED rather
 * than restated: done and cancelled are the archive, in_progress and blocked are
 * active, everything else is pending. A second copy of that mapping here is
 * exactly the defect the report spent a release removing, and it would be free to
 * disagree about a status one of the two had never heard of.
 *
 * @type {Object<string, number>} the report's segment order — active work first,
 *   then what has not started, then what is closed
 */
const SEG_ORDER={active:0,pending:1,archived:2};
/**
 * Take every control in a closed phase out of service.
 *
 * A done or cancelled phase is a RECORD, not a form: its models, skills and tier
 * decided what already ran, and editing them now would describe work that never
 * happened that way. The values stay legible — this disables the controls rather
 * than dropping them, so a reader can still see what the phase was run with.
 *
 * `disabled` and not the `.btn` convention of `aria-disabled`: that one exists to
 * keep a tab stop on a button whose refusal a reader has to be able to reach and
 * hear (F16). Nothing here is refusable — the phase is closed — so the standard
 * control is right, and a disabled control also fires no events, which is what
 * makes the patch object unreachable rather than merely discouraged.
 *
 * @param {HTMLElement} root - a row whose controls are to be frozen
 * @param {string} why - the reason, put on each control as its title
 * @returns {number} how many controls were frozen, so a caller can assert it
 */
function freezeControls(root,why){
 const cs=root.querySelectorAll('input,select,textarea,button');
 cs.forEach(c=>{c.disabled=true;c.title=why;});
 return cs.length;}

function renderComp(){closeCombo();
 // Rebuilt from FOUR places, which is one more than any other view: its own Save,
 // its Discard, the ADO card's Save and Discard, and the 5s disk poll. MEASURED:
 // after a confirmed Save the dialog handed the caret back to the Save button at
 // 676ms and this function took it away again at 682ms — six milliseconds, and no
 // poll involved, which is how this view differs from #policy. The caret in the
 // filter box was lost the same way on a refreshFromDisk, offset and all.
 const keepBack=focusKeep('#comp');
 const c=$('#comp');c.textContent='';const comp=STATE.composition;
 // NOTHING TO COMPOSE WITHOUT A PLAN. Every control below edits a `meta.*` key
 // of the manifest, so with none this view used to offer empty editors for an
 // object that does not exist - and the branch card, reading a `branchInfo` the
 // server never sent, printed a question mark and an empty string as its worked
 // example. Say it instead, in the shape Overview and Usage use. Settings stays
 // reachable and stays useful: `manifestPath` decides where the plan lands.
 if(!STATE.rollup){
  const none=el('div',{class:'card'});
  none.append(el('div',{class:'mut'},'Nothing to set here yet — these are all keys '
    +'of the plan, and there is no plan. "/audit:init" writes one.'),
   el('div',{class:'mut',style:'margin-top:var(--sp-0)'},
     'it would be written to: '+(STATE.manifestPath||'-'),' · ',
     settingsLink('change where it goes','manifestPath')));
  c.append(none);focusBack(keepBack);return;}
 MITEMS=null;   // STATE may have moved under us (save re-render, disk refresh)
 // `meta` is keyed by the three field names below it; the other two are keyed
 // by manifest ids and so carry no prototype - a patch written under
 // `__proto__` would otherwise be silently dropped and the save would report
 // nothing to save while the box on screen held an edit.
 const patch={meta:{},phases:Object.create(null),tasks:Object.create(null)};
 const meta=el('div',{class:'card'});meta.append(h2h('Phase sign-off review skill (meta.reviewSkill)',MDESC.reviewSkill,
   {comp:'reviewSkill',label:'Phase sign-off review skill'}));
 meta.append(el('div',{class:'row'},skillPicker(comp.meta.reviewSkill,
   v=>patch.meta.reviewSkill=v,'Phase sign-off review skill','reviewSkill')));
 meta.append(h2h('meta.buildCommands (JSON)',MDESC.buildCommands,
   {comp:'buildCommands',label:'Build commands'}));
 // It had no accessible name at all — not even a placeholder to fall back on —
 // which is SC 4.1.2 as well as SC 3.3.2. Named from its own <h2>.
 const bc=el('textarea',{'aria-label':'meta.buildCommands (JSON)'});
 bc.value=comp.meta.buildCommands?JSON.stringify(comp.meta.buildCommands,null,2):'';
 let bcBad=false;
 bc.oninput=()=>{try{patch.meta.buildCommands=bc.value.trim()?JSON.parse(bc.value):null;
   bcBad=false;bc.style.borderColor='';}
  catch(e){bcBad=true;bc.style.borderColor='var(--err)';}};
 // HELD, not appended here. The table below is what this view is FOR - the
 // README calls it the tab's main function - and it used to open on three
 // config cards with the table under them. Construction order is untouched
 // (these still build first, and the table's closures still read `patch`);
 // only the insertion point moves, which is the change that cannot break a
 // build-order dependency.
 meta.append(bc);
 // meta.branch rides this same form and this same save, so its card is appended
 // as a sibling of the meta card rather than owning an endpoint the way the ADO
 // connector does. It writes patch.meta.branch and nothing else.
 const bcard=branchCard(comp,patch);
 // tasks: filter toolbar + ONE compact collapsible table (scales to 50x20)
 const tcard=el('div',{class:'card'});tcard.append(h2h('Phases · tasks · skills',MDESC.taskSkills,
   {comp:'taskSkills',label:'Task skills'}));
 // The toolbar and the two editable columns carry hand-back hooks, because this
 // view has no ids of its own and focusSel can only name an element by an id or a
 // data- attribute. `data-status` alone would not do for the filter buttons: inside
 // #comp it also sits on every phase row, every task row and every status pill, so
 // it names four hundred elements and focusBack correctly refuses to guess.
 const q=el('input',{type:'search',id:'compq',placeholder:'filter phases & tasks…',
   'aria-label':'filter phases & tasks',value:COMPF.q});
 const statusBar=el('span',{class:'filtset',style:'display:inline-flex;gap:.3rem;flex-wrap:wrap'});
 const needsBtn=el('button',{class:'filt',type:'button','data-compneeds':'1','aria-pressed':'false',title:'only tasks with no skills yet — an explicit "none applies" (null) is an answer, not a need'},'needs skills');
 const expandBtn=el('button',{class:'btn small',type:'button','data-compexpand':'1'},'expand all');
 const count=el('span',{class:'count',style:'margin-left:auto'});
 tcard.append(el('div',{class:'comptools'},q,el('span',{class:'filtlbl'},'phase:'),statusBar,needsBtn,expandBtn,count));
 // mc: the three-source near-miss hint (see modelHints). A note, not a gate.
 modelHints().slice(0,3).forEach(h=>tcard.append(
  el('div',{class:'mut small','data-mdhint':h.model},
   'model "'+h.model+'" is spelled only in this manifest; the rate table / '
   +'ledger know "'+h.near+'" — one slip apart. A hint, not a gate: if "'
   +h.model+'" is intended, it meters at _default rates until it is priced.')));
 // sk: the inventory hint for skills (see skillHints). A note, not a gate.
 skillHints().slice(0,3).forEach(n=>tcard.append(
  el('div',{class:'mut small','data-skhint':n},
   'skill "'+n+'" is spelled only in this manifest; discovery knows no such '
   +'skill — a hint, not a gate: a name that never resolves simply loads nothing.')));
 // sp: the portability note, separate from the one above because it is a
 // different problem — this name resolves perfectly well HERE, and nowhere else.
 // Said BEFORE a save rather than at one: under strict the alternative is
 // teaching by refusal, after the choice has already been made.
 const skport=portabilityHints().slice(0,3);
 skport.forEach(h=>tcard.append(
  el('div',{class:'mut small','data-skport':h.name},
   'skill "'+h.name+'" resolves here but would not survive a clone — '+h.basis+'.')));
 // The tier is said ONCE, under the names it applies to, and not repeated on each
 // of them: three copies of one sentence read as three problems, which is the
 // wall `_warning_groups` exists to stop one surface over.
 if(skport.length)tcard.append(el('div',{class:'mut small',
   'data-skport-mode':portabilityMode()},
  portabilityMode()==='strict'
    ?'Portability is strict, so a save naming one of these is refused. Vendor it '
     +'under .claude/skills/, declare its plugin in the committed '
     +'.claude/settings.json, or set portability to "warn" in Settings.'
    :'Portability is "warn", so this is a note and nothing is refused.'));
 const tbody=el('tbody');
 // The reference for the two PHASE-row levers, once, above the columns they sit
 // in. Both of the last two columns hold TWO different things - column 4 a task's
 // model and a phase's review model, column 5 a task's skills and a phase's
 // priority - and a <th> carries one ⓘ, so the head explains the task lever and
 // this explains the phase one. It is right-aligned because those two columns are
 // at the row's right-hand end. Same rule as the head: the ⓘ explains the lever
 // ONCE for every row that has one. There is no second list of these names - the
 // drawer still opens on `comp` refs, so the help wiring is unchanged.
 tcard.append(el('div',{class:'phlegend'},
   el('span',{class:'phlegend-t'},'per phase:'),
   flabel('review model',MDESC.phaseReviewModel,
     {comp:'phaseReviewModel',label:'Phase review model'}),
   flabel('priority',MDESC.phasePriority,
     {comp:'phasePriority',label:'Phase priority'}),
   // The THIRD phase lever, and it is here for the same reason the other two
   // are rather than for a new one: a <th> carries one ⓘ, and the sixth column
   // now holds two phase levers. The heading explains the parent; this explains
   // the lever above it, which is the question the parent only matters after.
   flabel('on the board',MDESC.phaseAdoTracked,
     {comp:'phaseAdoTracked',label:'Phase ADO tracked'})));
 // The sixth column holds PHASE levers and no task one, so its ⓘ names one of
 // them rather than a task lever - which is why that heading carries its own
 // reference instead of joining the legend above the table. It names the parent;
 // the lever ABOVE the parent in the same cell is in that legend, because a <th>
 // carries one ⓘ and this column now holds two things. It is written HERE,
 // outside the head array: a comma inside that array is how a column is
 // separated from the next one, so a comment in there reads as a seventh column
 // to anything counting them.
 tcard.append(el('div',{class:'comptblwrap'},el('table',{class:'comp'},
   // The two editable columns carry the reference for the whole column. A ⓘ per
   // row would be a thousand of them saying one thing.
   //
   // "model" covers both row types honestly - a task model and a phase's review
   // model are both models. The fifth heading names BOTH of the things its column
   // holds, because they are different levers that can never appear in the same
   // row, and "skills" alone described half the table.
   tableHead(['id','title','status',
     {label:flabel('model',MDESC.taskModel,{comp:'taskModel',label:'Task model'})},
     {label:flabel('skills · priority',MDESC.taskSkills,{comp:'taskSkills',
       label:'Task skills'})},
     {label:flabel('ADO parent',MDESC.phaseAdoParent,{comp:'phaseAdoParent',
       label:'Phase ADO parent'})}]),tbody)));
 // WHICH OF THE THREE CACHE STATES THIS IS, once, under the table's own
 // reference line. Once and not per row for the reason the legend exists: fifty
 // copies of one sentence is what the phase levers were moved out of the rows to
 // stop. The sentence itself is the SERVER'S - `_panel_composition` builds it,
 // so the panel and anything else that reports the cache say the same thing.
 tcard.append(el('div',{class:'mut small apcache','data-apcache':(comp.adoParents||{}).cache||'absent'},
   (comp.adoParents||{}).basis||''));

 const open=COMPF.open;
 // No prototype: `byPhase.constructor` answered with Object itself, which is
 // truthy, so `.push` on it threw and took the whole Composition tab down.
 const phaseEls=[];const byPhase=Object.create(null);comp.tasks.forEach(t=>{(byPhase[t.phaseId]=byPhase[t.phaseId]||[]).push(t);});
 // Work you can still act on comes first, which is the order the report already
 // reads in and the Overview already filters by. Decorated rather than sorted in
 // place: `comp.phases` is the payload the poll hands over and the status filter
 // below still reads it, and the index tie-break keeps PLAN order inside each
 // segment - so this promotes the active phases without shuffling anything
 // within them, and two phases of the same segment never swap between renders.
 const ordered=comp.phases.map((p,i)=>[p,i])
   .sort((a,b)=>(SEG_ORDER[segOf(a[0].status)]-SEG_ORDER[segOf(b[0].status)])||(a[1]-b[1]))
   .map(x=>x[0]);
 ordered.forEach(ph=>{
  const tasks=byPhase[ph.id]||[];
  // A closed phase is a record: everything below is rendered, then frozen.
  const frozen=segOf(ph.status)==='archived';
  const frozenWhy='this phase is '+label(ph.status)
    +' — its plan is closed, so what it ran with is no longer editable';
  // The visible word beside this box is "review", and it is the same word beside
  // all fifty of them — a <label> here would name fifty controls identically,
  // which conforms and helps nobody. The name folds in the phase id and still
  // contains the visible word, so SC 2.5.3 Label in Name holds as well.
  // ONE patch object per phase, the shape the task rows already use. The old
  // spelling assigned a fresh `{reviewModel:…}` on every keystroke, which was
  // correct while a phase had exactly one control and silently DISCARDS the
  // other the moment it has two.
  const pp={};
  const rev=el('input',{value:ph.reviewModel??'','data-revmodel':ph.id||'',placeholder:'review model',
    'aria-label':'review model for phase '+(ph.id||'')});
  const setRev=v=>{pp.reviewModel=v||null;patch.phases[ph.id]=pp;};
  rev.oninput=()=>setRev(rev.value.trim());
  // Which phase the pipeline reaches for first AMONG THE WORK THAT IS ALREADY
  // READY. The range comes from the config (falling back to the shipped default
  // the server hands over), never from a literal here: a second copy of maxTier
  // in the browser is a second setting.
  const maxTier=prioMax();
  const tiers=Array.from({length:maxTier},(_x,i)=>String(i+1));
  // A tier ABOVE the maximum is still a real pin — nothing is clamped — so the
  // control offers it rather than silently resetting the phase to unprioritised.
  // Appended after the range, as the loop that built this by hand did.
  if(ph.priority!=null&&ph.priority>maxTier)tiers.push(String(ph.priority));
  // The same option builder the policy, overview and usage selects go through.
  // It chooses while it appends and compares STRICTLY, which is why the tier is
  // handed over as a string: an option's value is text, and `prio.value` below
  // reads it back as text. The hand-rolled version wrote `.value` after the
  // append instead, and the two agree everywhere except on a tier no option
  // carries — an impossible value now leaves the unprioritised option showing
  // rather than a blank box, which is the reading the change handler already had.
  // The em dash is this table's existing spelling of "unset": the task model box
  // one row down already shows `placeholder:'—'` for the same idea. It reads as
  // a value rather than as the sentence "no priority", which is what let the
  // menu stop being the widest thing in the row. The word this control goes by
  // is not lost with it - `aria-label` carries "priority for phase <id>", so the
  // announcement is unchanged and only the painted text got shorter.
  const prio=fillOptions(
    el('select',{'data-priority':ph.id||'','aria-label':'priority for phase '+(ph.id||'')}),
    [['','—'],...tiers.map(t=>[t,t])],
    ph.priority==null?'':String(ph.priority));
  prio.onchange=()=>{pp.priority=prio.value?Number(prio.value):null;
    patch.phases[ph.id]=pp;};
  // Same STOP as the review combo: the phase row toggles on click, and choosing
  // a tier must not also collapse the phase under the menu.
  prio.onclick=e=>e.stopPropagation();
  // ap: where THIS phase hangs on the board. One <select> over the three answers
  // plus whatever was cached, and a number box for the fourth case the cache can
  // never cover - an id created since the fetch, or a board nobody has fetched
  // at all. The box is revealed by the "other id…" option rather than shown
  // beside it, so the common row stays one control wide.
  const apc=comp.adoParents||{fallback:{id:null,source:'none'},candidates:[],
    cache:'absent',basis:'',refresh:'/audit:sync parents'};
  const apChoice=apChoiceOf(ph.adoParent,apc.candidates);
  const apDecl=(ph.adoParent&&typeof ph.adoParent==='object'
    &&!apIsFallback(ph.adoParent))?ph.adoParent:null;
  const apNote=el('span',{class:'mut small apnote'});
  // WHAT THE BOARD SAYS, beside what the manifest declares - and where nothing
  // has been asked, that is what it says (F101). Written once at render and
  // never touched by `apApply`: the declaration is what an edit changes, and
  // the board's answer is not something a save here can move. Same class as the
  // unfinished-edit note because it is the same kind of line under the same
  // control; the STATE is on a `data-` hook of its own, which is what a browser
  // gate reads rather than the prose.
  const apBoard=el('span',{class:'mut small apnote',
    'data-apboard':apBoardState(ph.adoParentBoard),
    title:(ph.adoParentBoard||{}).basis||null},apBoardWords(ph.adoParentBoard));
  const apId=el('input',{type:'number',min:'1',step:'1',
    'data-adoparentid':ph.id||'',placeholder:'work item id',
    'aria-label':'ADO parent work item id for phase '+(ph.id||''),
    value:(apDecl&&apDecl.id!=null)?String(apDecl.id):''});
  // The RESOLUTION, not the declaration: what this phase hangs under right now,
  // in `resolve`'s own words. It is supplementary — the control's accessible
  // name is its aria-label and does not depend on this — and it is the one place
  // a reader can see that an absent declaration is already doing something.
  // BOUNDED BY `PHCELL_OPTION_CHARS` (F211). A candidate's label is built from a
  // work item's TITLE, so nothing here can promise it is short; the id and the
  // type are what the hierarchy check grades on, they lead the label, and the
  // whole sentence stays on the option's `title`.
  const ap=fillOptions(el('select',{'data-adoparent':ph.id||'',
    'aria-label':'ADO parent for phase '+(ph.id||''),
    title:(ph.adoParentResolved||{}).basis||null}),apOptions(apc),apChoice,
    PHCELL_OPTION_CHARS);
  const apApply=()=>{
   apId.hidden=(ap.value!=='other');
   const out=apPatchValue(ap.value,apc,apId.value);
   // An unfinished edit says so rather than saving nothing quietly: the key is
   // dropped from the patch AND the reason is painted next to the control.
   if(out.write)pp.adoParent=out.value;else delete pp.adoParent;
   apNote.textContent=out.why;
   // Only registered once it carries something. An empty phase entry would make
   // `_touched_phase_ids` name this phase and rewrite a shard nobody edited.
   if(Object.keys(pp).length)patch.phases[ph.id]=pp;};
  apId.hidden=(apChoice!=='other');
  ap.onchange=apApply;apId.oninput=apApply;
  ap.onclick=e=>e.stopPropagation();apId.onclick=e=>e.stopPropagation();
  // at: whether THIS phase is on the board at all, ABOVE the parent for the
  // reading order — the parent is a question only once the answer here is yes.
  // The two controls STACK rather than sitting side by side, and that is a
  // measurement rather than a preference: `td.phparent :is(select,input)` caps
  // this column at the parent control's own width because the browser gate
  // measured the table filling its 1200px frame exactly, so a second control
  // BESIDE it would put the table past its frame and scroll the panel
  // sideways. The line between them is what breaks the flow, and the CSS says
  // so too rather than depending on it.
  const atChoice=atChoiceOf(ph.adoTracked);
  const atSaved=atWords(ph.adoTrackedResolved,ph.adoTracked);
  // ONE LINE WEARING THREE STATES, unlike the parent's two spans — and the
  // reason is that both facts here are about the same movable thing. The board
  // line beside `ap` is an observation no save can move, so it is written once
  // and left alone; the answer in force IS what this control edits, so a line
  // that kept quoting the saved answer beside a changed menu would be the
  // stale-reads-as-current defect one control lower down. It never RECOMPUTES
  // the answer: the resolution is the server's, and a browser deriving it would
  // be the second implementation of the one rule this key exists to have one of.
  const atLine=el('span',{class:'mut small apnote',
    'data-atstate':atAnswer(ph.adoTrackedResolved),
    title:(ph.adoTrackedResolved||{}).basis||null},atSaved);
  // Through the SAME bound as the parent picker, though every label here is
  // already inside it: one rule for one cell. Left unbounded, this control would
  // be the one place a future long label could be added without anything saying
  // so — and the vitest case bounding these labels would then be checking a
  // promise nothing kept.
  const at=fillOptions(el('select',{'data-adotracked':ph.id||'',
    'aria-label':'on the ADO board for phase '+(ph.id||''),
    title:(ph.adoTrackedResolved||{}).basis||null}),
    atOptions(ph.adoTracked),atChoice,PHCELL_OPTION_CHARS);
  const atApply=()=>{
   const out=atPatchValue(at.value);
   // An option that writes nothing says why, rather than saving nothing
   // quietly — `apApply`'s rule, and the only such option here is the one a
   // broken declaration put on the menu.
   if(out.write)pp.adoTracked=out.value;else delete pp.adoTracked;
   atLine.textContent=out.write
     ?(at.value===atChoice?atSaved:('tracking: unsaved edit · saved: '+atSaved))
     :out.why;
   if(Object.keys(pp).length)patch.phases[ph.id]=pp;};
  at.onchange=atApply;
  at.onclick=e=>e.stopPropagation();
  const revCombo=comboWrap(rev,modelItems,(name,close)=>{
    rev.value=name;setRev(name);close();});
  // The STOP moved from the input to its combo WRAPPER: the phase row toggles
  // on click, and the combo's menu is part of the same control — a click that
  // chooses a model must not also collapse the phase under the menu.
  revCombo.onclick=e=>e.stopPropagation();
  const pr=el('tr',{class:'phase','data-status':ph.status||''});
  // ONE CELL PER HEADING, the same five a task row emits. This used to be one
  // cell spanning the whole width with a flex line inside it, which meant the
  // head described the task rows and nothing else: the review box and the
  // priority menu were pushed to the right-hand end by an auto margin and landed
  // under "model" and "skills" by ARITHMETIC, not by belonging to them - and
  // with every phase collapsed the head described nothing on screen at all. The
  // id, title and status a phase shares with a task now sit in the same three
  // columns, and its two levers in the two the head names for them.
  //
  // What the title cell absorbed is everything that describes the PHASE rather
  // than naming a column: the disclosure triangle, the area badges, the task
  // count and the sign-off note. They wrap inside that cell (`.phsum`), which is
  // capped at the same width as a task title, so none of them can widen the
  // table.
  pr.append(el('td',{class:'phid'},el('span',{class:'mono'},ph.id||'')),
    el('td',{class:'ttitle'},el('div',{class:'phsum'},
      // The triangle and the title are ONE item of the wrapping line, because a
      // disclosure control belongs to the thing it discloses. As two items the
      // triangle kept its place and the title moved to the next line whenever
      // the pair did not fit - at 390px that left the control alone on line one
      // with nothing beside it to open.
      el('span',{class:'phname'},el('span',{class:'tri'}),
        el('strong',{},ph.title||'')),
      (ph.area||[]).map(a=>el('span',{class:'badge area'},a)),
      el('span',{class:'count'},tasks.length+(tasks.length===1?' task':' tasks')),
      // Every row below reads done while the badge says in progress — a real
      // state (sign-off is part of the phase) that reads like a contradiction,
      // and on a live repo it did. Name the reason where the eye trips on it.
      (ph.status==='in_progress'&&tasks.length>0&&tasks.every(t=>t.status==='done'))
        ?el('span',{class:'count whynote'},
            'all tasks done — awaiting sign-off (/audit:review)')
        :null)),
    el('td',{},el('span',{class:'st','data-status':ph.status||''},label(ph.status))),
    // The words and the ⓘ that used to sit beside each of these are in the
    // legend above the table — one reference per lever instead of one per phase,
    // which is the rule the task columns already follow. What names them here is
    // not the visible text: the review box says what it is through its own
    // placeholder, and both carry an aria-label that folds in the phase id, so
    // the accessible name never depended on the words removed.
    el('td',{class:'tmodel'},revCombo),
    el('td',{class:'phprio'},prio),
    el('td',{class:'phparent'},at,atLine,ap,apId,apBoard,apNote));
  // The row still TOGGLES when it is frozen — a closed phase is the one you most
  // often open to read. Only its controls go out of service.
  pr.onclick=()=>{open[ph.id]=!open[ph.id];refresh();};
  if(frozen){pr.setAttribute('data-frozen','1');freezeControls(pr,frozenWhy);}
  tbody.append(pr);
  const taskEls=[];
  tasks.forEach(t=>{
   // Same again one level down, and worse: these two are named by a COLUMN
   // HEADER ("model", "skills"), which a screen reader does not re-announce per
   // row, and the model box's placeholder is an em dash. Both fold in the task id.
   const tp={};const model=el('input',{value:t.model??'','data-tmodel':t.id||'',placeholder:'—',
     'aria-label':'model for task '+(t.id||'')});
   const setModel=v=>{tp.model=v||null;patch.tasks[t.id]=tp;};
   model.oninput=()=>setModel(model.value.trim());
   // mc: choosing from the menu writes the SAME patch the keystroke writes.
   const modelCombo=comboWrap(model,modelItems,(name,close)=>{
     model.value=name;setModel(name);close();});
   // Three-state read: an explicit null (opt-out) must SURVIVE this accessor —
   // `||[]` would flatten the one deliberate answer into "unconsidered".
   const getSkills=()=>tp.skills!==undefined?tp.skills:(t.skills===null?null:(t.skills||[]));
   const chips=skillChips(getSkills,a=>{tp.skills=a;patch.tasks[t.id]=tp;if(COMPF.needs)refresh();},
     'add a skill to task '+(t.id||''));
   const tr=el('tr',{class:'task','data-status':t.status||''});
   // No `title` on the title cell any more: it existed to recover text the
   // ellipsis had cut off, and the cell wraps now, so the words are all on
   // screen. Kept, it would be a hover tooltip repeating what is already
   // readable underneath it.
   tr.append(el('td',{class:'tid'},t.id||''),el('td',{class:'ttitle'},t.title||''),
     el('td',{},el('span',{class:'st','data-status':t.status||''},label(t.status))),
     el('td',{class:'tmodel'},modelCombo),el('td',{class:'tskills'},chips),
     // ONE CELL PER HEADING, in both builders. A task has no parent lever of its
     // own — under `phaseWorkItems` its parent IS the work item of its phase,
     // and with that off it is a manifest edit this table does not offer — so
     // the cell is empty rather than absent: a row with five cells under a six
     // column head shifts every cell after it into the wrong column.
     el('td',{class:'phparent'}));
   // EITHER closes a task row. The phase, because an unfinished task inside a
   // cancelled phase is never going to run; and the task's own status, because a
   // done task has already run and the model and skills on it are the record of
   // what ran, not a setting for next time. Same classifier for both — `segOf`
   // reads a status, and done/cancelled is the archive whichever of the two
   // carries it.
   const tFrozen=frozen||segOf(t.status)==='archived';
   const tWhy=frozen?frozenWhy
     :'this task is '+label(t.status)+' — it has already run, so what it ran '
      +'with is the record rather than a setting';
   if(tFrozen){tr.setAttribute('data-frozen','1');freezeControls(tr,tWhy);}
   tbody.append(tr);
   taskEls.push({id:t.id||'',title:t.title||'',tr,getSkills});
  });
  phaseEls.push({id:ph.id,title:ph.title||'',status:ph.status||'',area:(ph.area||[]).join(' '),tr:pr,tasks:taskEls});
 });
 [...new Set(comp.phases.map(p=>p.status).filter(Boolean))].sort().forEach(s=>{
  const b=el('button',{class:'filt',type:'button','data-status':s,'data-compfilt':s,'aria-pressed':'false'},label(s));
  b.onclick=()=>{COMPF.status=COMPF.status===s?'':s;syncFilters();refresh();};
  statusBar.append(b);});
 // aria-pressed alongside the class: which filter is on was carried by the accent
 // fill alone, which a screen reader never sees. Driven from COMPF rather than
 // toggled in place, so a filter set from elsewhere (Overview) shows here too.
 function syncFilters(){
  [...statusBar.children].forEach(x=>{const on=x.getAttribute('data-status')===COMPF.status;
   x.classList.toggle('on',on);x.setAttribute('aria-pressed',on?'true':'false');});
  needsBtn.classList.toggle('on',COMPF.needs);
  needsBtn.setAttribute('aria-pressed',COMPF.needs?'true':'false');}
 needsBtn.onclick=()=>{COMPF.needs=!COMPF.needs;syncFilters();refresh();};
 expandBtn.onclick=()=>{const anyClosed=phaseEls.some(P=>!open[P.id]);phaseEls.forEach(P=>open[P.id]=anyClosed);refresh();};
 const hit=(s,term)=>!term||s.toLowerCase().includes(term);
 function refresh(){
  COMPF.q=q.value;
  const term=q.value.trim().toLowerCase();const forced=(term!=='')||COMPF.needs;let visP=0,visT=0;
  phaseEls.forEach(P=>{
   const pText=hit(P.id+' '+P.title+' '+P.area,term);let anyT=false;
   P.tasks.forEach(T=>{const tHit=pText||hit(T.id+' '+T.title,term);
    // null is an ANSWER, not a need: only a real empty list counts as "needs".
    const sv=T.getSkills();
    const needHit=!COMPF.needs||(Array.isArray(sv)&&sv.length===0);T._m=tHit&&needHit;if(T._m)anyT=true;});
   const showP=(!COMPF.status||P.status===COMPF.status)&&(pText||anyT)&&(!COMPF.needs||anyT);
   P.tr.style.display=showP?'':'none';if(showP)visP++;
   const isOpen=showP&&(forced||!!open[P.id]);P.tr.classList.toggle('open',isOpen);
   P.tasks.forEach(T=>{const showT=showP&&isOpen&&T._m;T.tr.style.display=showT?'':'none';if(showT)visT++;});});
  count.textContent=(term||COMPF.status||COMPF.needs)?(visP+' / '+phaseEls.length+' phases · '+visT+' tasks')
    :(phaseEls.length+' phases · '+comp.tasks.length+' tasks');
  expandBtn.textContent=phaseEls.some(P=>!open[P.id])?'expand all':'collapse all';}
 // Published for whoever wants to scope this tab without rebuilding it.
 COMPF.apply=()=>{q.value=COMPF.q;syncFilters();refresh();};
 syncFilters();q.addEventListener('input',refresh);refresh();

 EDITS.comp=()=>compChanges(patch);
 const save=el('button',{class:'btn primary','data-save':'comp',onclick:async()=>{
   // The textarea only writes into the patch when its contents PARSE, so an
   // unparseable box would confirm — and then save — the last value that did. A
   // dialog that shows something other than what the form holds is worse than no
   // dialog, so this is refused at the door and the field says which one it is.
   if(bcBad){toast('meta.buildCommands is not valid JSON — fix it or clear it '
     +'before saving','err');bc.focus();return;}
   const rows=await confirmSave({rows:()=>compChanges(patch),
     title:'Save plan & models',scope:'comp',empty:'no values changed',
     note:'writes '+STATE.manifestPath});
   if(!rows)return;
   const clean={meta:{},phases:patch.phases,tasks:patch.tasks};
   for(const k of Object.keys(patch.meta))clean.meta[k]=patch.meta[k];
   const res=await api('PUT','/api/composition',clean);
   if(!res.ok){c.querySelector('.findings-slot').replaceChildren(findingsBox(res));
    saveOutcome(res,rows,'the manifest',null);return;}
   // Re-render from the saved state. Without it the form kept showing the values
   // you typed rather than the values on disk — indistinguishable while they
   // agree, and silently wrong the moment the server normalised one or refused
   // part of a patch. COMPF is hoisted, so the filter, the search and which
   // phases were open all survive this.
   STATE=await api('GET','/api/state');renderComp();renderOver();
   showWriteResult('#comp',res,rows,'the manifest');}},'Save plan & models');
 const discard=discardButton({key:'comp',rows:()=>compChanges(patch),
   title:'Discard unsaved composition edits',
   note:'nothing is written; the table goes back to the saved manifest',
   toast:'discarded — the table is back to the saved manifest',
   revert:renderComp});
 onViewEdit('comp',()=>refreshDiscard(discard,compChanges(patch).length));
 // Out of the card and into the view's own savebar, for the reason moving the
 // table exposed: this Save writes the config cards too, and inside the table it
 // would have sat ABOVE the fields it saves. Settings and Policy both put one
 // Save for several cards in a `.savebar` at the foot of the view; this is that
 // same shape, not a fourth arrangement.
 const savebar=el('div',{class:'savebar'},save,discard,
   el('span',{class:'mut small'},'writes '+STATE.manifestPath),
   el('div',{class:'findings-slot'}));
 if(!STATE.manifestExists)tcard.append(el('div',{class:'findings warn'},'No manifest yet — run /audit:init first.'));
 if(STATE.manifestLocked)tcard.append(el('div',{class:'findings warn'},'Manifest is locked by a running /audit command.'));
 c.append(tcard,meta,bcard);
 renderAdoCard(c);
 // building blocks — one table, sub-tabs switch context (skills / agents / mcp)
 const bb=el('div',{class:'card'});
 bb.append(h2h('Available building blocks (discovered)',
   'Skills & agents found in this project, your ~/.claude, and installed plugins — plus MCP servers in scope. Use these names in the pickers above. A row marked "stays here" resolves on this machine and would not survive a clone; under strict portability it is listed but not offered.'));
 // EVERY ROW STAYS VISIBLE, including the ones the pickers will not offer. This
 // table answers "what does this machine have"; the pickers answer "what may I
 // choose". A table that silently shrank would read as "you do not have that
 // skill" and send its reader to debug discovery instead of their settings.
 const datasets={skills:REG.skills,agents:REG.agents,mcp:REG.mcp};
 const subtabs=el('div',{class:'subtabs'}),host=el('div',{class:'regtblwrap'});let cur='skills';
 const drawTbl=()=>{const items=datasets[cur]||[];const tb=el('tbody');
   if(!items.length)tb.append(el('tr',{},el('td',{colspan:'3',class:'mut'},'none found')));
   items.forEach(it=>{const row=el('tr',{},el('td',{class:'mono'},it.name),
     el('td',{},it.source?el('span',{class:'src badge'},it.source):null,
       it.travels===false?el('span',{class:'src badge stays',
         title:it.travelsBasis||''},'stays here'):null),
     el('td',{class:'d'},it.description||''));
    if(it.travels===false)row.classList.add('stranded');
    tb.append(row);});
   host.replaceChildren(el('table',{class:'regtbl'},
     tableHead(['name','source','description']),tb));};
 ['skills','agents','mcp'].forEach(k=>subtabs.append(el('button',{class:'subtab'+(k===cur?' on':''),
   onclick:e=>{cur=k;[...subtabs.children].forEach(x=>x.classList.toggle('on',x===e.currentTarget));drawTbl();}},
   k+' ('+(datasets[k]||[]).length+')')));
 drawTbl();bb.append(subtabs,host);c.append(bb,savebar);
 // Last, after renderAdoCard and the blocks table: a hand-back that runs before
 // the view is finished aims at a node the rest of the build then replaces.
 focusBack(keepBack);}

