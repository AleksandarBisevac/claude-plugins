// ---------- capability policy: the switchboard ----------
// `{"default":"deny","allow":["code-*"]}` is four words that decide the fate of
// every skill on the machine, and nobody can hold that cross-product in their
// head. This view IS the cross-product: one row per capability the project can
// actually reach, the verdict the guard would give it, and the reason.
//
// Two rules run through all of it.
//
// The verdicts are the SERVER's — computed by `_policy.resolve`, the function the
// hook itself calls — and are never recomputed here. A second matcher in the
// browser would eventually disagree with the guard, and disagreeing about a denial
// is the one thing a preview must not do. The consequence is that a verdict is
// true of the SAVED policy: an edited row is marked as pending rather than
// re-judged, and the verdicts are re-read from the server after every save.
//
// And the draft is the block AS WRITTEN (`stored`), never the merged one. PUT
// /api/policy replaces the block wholesale, so anything this form does not
// represent — a comment key, a pattern nobody clicked — would be destroyed by
// someone who came to flip one switch. Which is also why the raw rules are a table
// of their own further down: a rule the form cannot show is a rule it must not be
// trusted to save.
/**
 * One kind's rules, as they are written in the config file.
 *
 * `default` is absent for allow and the string 'deny' for deny — the shipped
 * default is written by REMOVING the key, so a block never spells out a default
 * nobody chose. Every list is a list of shell-style GLOBS, of which an exact
 * name is the degenerate case.
 *
 * @typedef {{default?: 'allow'|'deny', allow?: string[], deny?: string[],
 *   areas?: Object<string, {allow?: string[], deny?: string[]}>}} PolicyKind
 */

/**
 * The `policy` key of `.claude/audit.config.json`, as written.
 *
 * @typedef {{enabled?: boolean, onViolation?: 'deny'|'ask'|'warn',
 *   skills?: PolicyKind, agents?: PolicyKind, mcp?: PolicyKind}} PolicyBlock
 */

/**
 * One capability the project can reach, with the verdict the guard would give
 * it. Computed by `_policy.resolve` on the server and never recomputed here.
 *
 * `verdict` is the guard's own vocabulary: 'allow' or 'violation'. The table
 * renders 'violation' and treats everything else as allowed, which is the safe
 * direction — a verdict word this client has never heard of shows as allowed,
 * exactly as `_policy.resolve` itself allows on any internal error rather than
 * refusing work for a reason nobody can read.
 *
 * @typedef {{name: string, source: string|null, standIn: boolean,
 *   verdict: 'allow'|'violation', basis: string, rule: string|null,
 *   area: string|null, required: boolean}} PolicyRow
 */

/**
 * One pattern the SAVED block states, with what it matches today.
 *
 * @typedef {{scope: string|null, list: 'allow'|'deny', pattern: string,
 *   matches: string[], n: number, dead: boolean}} PolicyRule
 */

/**
 * The whole `GET /api/policy` payload, or null when the policy could not be
 * read at all — which the view renders as a refusal to edit rather than as an
 * empty policy. `_panel_policy.policy_state` is where the key set is declared.
 *
 * @typedef {{
 *   policy: PolicyBlock, stored: PolicyBlock|null, active: boolean,
 *   onViolation: 'deny'|'ask'|'warn'|null, activeAreas: string[],
 *   areas: string[], required: string[], kinds: string[],
 *   onViolationChoices: Array<'deny'|'ask'|'warn'>,
 *   findings: string[], warnings: string[],
 *   enforcement: {seen: boolean, ageDays: number|null},
 *   areaInfo: Array<{tag: string, active: boolean, registered: boolean,
 *     description: string|null}>,
 *   resolved: Object<string, PolicyRow[]>, rules: Object<string, PolicyRule[]>
 * }} PolicyState
 */

/** @type {PolicyState|null} */
let POLICY=null;

// null means "no policy block on disk, and nothing typed yet". It is not {}: an
// empty object is a policy someone wrote, and writing one where there was none is
// a change this view must not make by rendering.
/** @type {PolicyBlock|null} */
let PDRAFT=null;

/**
 * The three kinds a policy can decide, in the order the tab shows them. The
 * server ships its own `kinds` list; these are the keys this form knows how to
 * render, and a kind in one and not the other is a gap, not a default.
 * @type {string[]}
 */
const PKINDS=['skills','agents','mcp'];

/**
 * What each kind is called on screen. 'MCP servers' rather than 'MCP tools'
 * because a row of that kind stands in for a whole server.
 * @type {Object<string, string>}
 */
const PKLABEL={skills:'Skills',agents:'Subagents',mcp:'MCP servers'};

/**
 * What the capability table is showing: which kind, the search text, whether it
 * is cut down to violations, and which RULELESS areas the reader has asked for a
 * column for. Shared by the tab and the expanded dialog, so expanding never
 * costs you your place.
 *
 * `cols` is cleared when the kind changes, the way `q` is: "which area has no
 * column here" is asked per kind, and a tag revealed while reading skills says
 * nothing about subagents.
 * @type {{kind: string, q: string, bad: boolean, cols: string[]}}
 */
const PF={kind:'skills',q:'',bad:false,cols:[]};
// --- the draft, and what it is compared against ---------------------------------
// The nodes the last save left behind — the ✓/✗ box and, if the file had moved
// under the reader, the mismatch warning. A save re-renders the whole view to pick
// up the server's fresh verdicts, which would otherwise throw away the one part of
// the page that says what just happened. Consumed once, so an edit made afterwards
// does not sit under a stale "saved".
/** @type {Node[]|null} */
let PNOTE=null;

/**
 * A deep copy, so the draft is never the same object as the server's payload —
 * editing a switch must not silently rewrite the thing the "unsaved" badges are
 * being compared against.
 *
 * @param {*} o - any JSON-shaped value
 * @returns {*} a structural copy, and null for null or undefined, because the
 *   draft distinguishes "no block on disk" from "an empty block someone wrote"
 */
const pClone=o=>(o==null?null:JSON.parse(JSON.stringify(o)));

// Every edit goes through here. It drops the last save's box — that box describes
// a file this form no longer matches — and redraws.

/**
 * Apply one draft edit and repaint the tab.
 *
 * @param {() => void} fn - mutates `PDRAFT`; it is called between dropping the
 *   previous save's outcome box and the redraw, so an edit can never sit under a
 *   stale "saved"
 * @returns {void}
 */
function pEdit(fn){PNOTE=null;fn();renderPolicy();}

/**
 * The draft block, created empty on first write.
 *
 * Only for the WRITE paths: reading through this would materialise a block on a
 * project that has none, and an empty block is a policy someone wrote.
 *
 * @returns {PolicyBlock} the live draft — mutated in place by its callers
 */
function pBlock(){if(PDRAFT===null)PDRAFT={};return PDRAFT;}

/**
 * One kind's rules out of a block, for READING.
 *
 * @param {PolicyBlock|null} b - a block, or null
 * @param {string} k - a kind from `PKINDS`
 * @returns {PolicyKind} the kind's rules, or a fresh empty object — so every
 *   reader can spell `.deny` without a guard. Never the live sub-object when the
 *   key is missing, so a reader cannot accidentally create one
 */
const pKindCfg=(b,k)=>((b||{})[k]||{});

/**
 * Is the draft policy switched on? Only the explicit `false` turns it off:
 * absent means on, which is how the shipped block reads.
 * @returns {boolean}
 */
const pEnabled=()=>((PDRAFT||{}).enabled!==false);

/**
 * What a violation does, in the draft. Falls through the draft, then the
 * server's merged view, then 'deny' — which is the shipped default and not a
 * guess: `_policy` treats an absent key the same way.
 * @returns {'deny'|'ask'|'warn'}
 */
const pOnViolation=()=>((PDRAFT||{}).onViolation||(POLICY&&POLICY.onViolation)||'deny');

/**
 * What one kind does with everything no rule names, in the draft.
 *
 * Anything other than the exact string 'deny' resolves to 'allow', which agrees
 * with `_policy.resolve`'s own last step — the guard denies by default only on
 * `default == "deny"`, so a typo in the file is permissive on both sides rather
 * than on one.
 *
 * @param {string} k - a kind from `PKINDS`
 * @returns {'allow'|'deny'}
 */
const pDefault=k=>(pKindCfg(PDRAFT,k).default==='deny'?'deny':'allow');
// What a violation DOES, in the words the hook uses. Said next to the control that
// picks it, because "deny" and "warn" are not degrees of the same thing: one
// refuses the call and one lets it through with a sentence attached.
/** @type {Object<string, string>} */
const PVIOL={deny:'refuse the call',ask:'ask for approval, per call',
 warn:'allow it and say so'};
// --- one capability's rule, read and written ------------------------------------
// Where this row's rule is written, for one scope: '' (nothing), 'allow', 'deny'.
// EXACT names only, and deliberately so — a glob that happens to match is not this
// row's rule to move, and silently dropping `code-*` because somebody pressed
// Default on one skill it covers would change the verdict of every other one. A
// pattern is edited where it is written, in the rules table below.
/**
 * Which list, if either, names this capability EXACTLY in one scope.
 *
 * This is not a verdict and must never be read as one: it says where the row's
 * own switch is written, so the select can show it and `pCell` can compare the
 * draft against the saved block. The verdict is the server's, and deny beats
 * allow there, which is why this returns the FIRST of deny then allow rather
 * than reporting both.
 *
 * Exact names only, deliberately: a glob that happens to cover this row is not
 * this row's rule to move.
 *
 * The lists are `string[]` when the file is well formed. A hand-edited config
 * can hold `"deny": "nope"` instead — a shape `_policy.validate_policy` reports
 * as a finding and `_panel_policy._policy_rules` explicitly guards — and this
 * does not guard it: `indexOf` on a string is a SUBSTRING search, so such a file
 * makes this claim a rule exists where none does. See the Faults list; the
 * repair belongs with the two siblings below that throw outright on the same
 * shape.
 *
 * @param {PolicyBlock|null} block - the draft, or the saved block
 * @param {string} kind - a kind from `PKINDS`
 * @param {string} name - the capability's whole name
 * @param {string|null} tag - an area tag, or null for the project scope
 * @returns {''|'allow'|'deny'} '' when no list in that scope names it
 */
/**
 * One rule list, as a list — `[]` when what is stored there is not one.
 *
 * A person can hand-write `"deny": "nope"` into `.claude/audit.config.json`.
 * `_policy.validate_policy` calls that a finding and `_panel_policy._policy_rules`
 * guards it with `isinstance(patterns, list)`, so the server has always known the
 * shape exists; four walkers here did not. Three of them threw, and a throw
 * inside `renderPolicy` blanks the Policy tab — which no substring pin can see,
 * because the page still serves its whole static shell.
 *
 * READ-ONLY. It never repairs the stored value: the malformed list is the
 * reader's config and the server already reports it. Use `pListFor` where a write
 * genuinely needs an array.
 *
 * @param {Object} src the scope object — a kind block, or one of its areas
 * @param {string} list `'deny'` or `'allow'`
 * @returns {string[]} the patterns, or empty when the value is not a list
 */
const pList=(src,list)=>Array.isArray(src&&src[list])?src[list]:[];

/**
 * The same list, ready to be written to, replacing a non-list with a fresh one.
 *
 * Replacing is the reader's own act here: they are moving a rule, so the list
 * they are moving it into has to be a list. A malformed value is not silently
 * preserved and not silently merged — it is discarded by the edit that needed it
 * to be an array, and the server's finding is what named it in the first place.
 *
 * @param {Object} src the scope object
 * @param {string} list `'deny'` or `'allow'`
 * @returns {string[]} the array now stored at `src[list]`
 */
const pListFor=(src,list)=>{
 if(!Array.isArray(src[list]))src[list]=[];
 return src[list];};

function pRuleOf(block,kind,name,tag){
 const k=pKindCfg(block,kind);
 const src=tag?((k.areas||{})[tag]||{}):k;
 // MEMBERSHIP, not indexOf on whatever is there. `indexOf` on a STRING is a
 // substring search, so a hand-written `"deny": "nope"` answered 'deny' for the
 // capability `op` — a rule reported for something nothing had denied, in the
 // view that decides whether a skill may run.
 for(const l of ['deny','allow'])if(pList(src,l).includes(name))return l;
 return '';}
/**
 * Move one capability's rule in one scope: into allow, into deny, or out of
 * both.
 *
 * Removes the name from BOTH lists before adding it back, so the two can never
 * both hold it — a state the file can express and the guard would resolve as a
 * denial, silently, whatever the select was showing.
 *
 * Creates the containers it needs and prunes afterwards, so a switch flipped and
 * flipped back leaves the block exactly as it was rather than leaving an empty
 * list behind.
 *
 * @param {string} kind - a kind from `PKINDS`
 * @param {string} name - the capability's whole name
 * @param {string|null} tag - an area tag, or null for the project scope
 * @param {''|'allow'|'deny'} val - '' removes the rule
 * @returns {void} it mutates `PDRAFT`; the caller redraws
 */
function pSetRule(kind,name,tag,val){
 const b=pBlock(),k=b[kind]=b[kind]||{};
 let src=k;
 if(tag){const a=k.areas=k.areas||{};src=a[tag]=a[tag]||{};}
 ['allow','deny'].forEach(l=>{if(!Array.isArray(src[l]))return;
  const i=src[l].indexOf(name);if(i>=0)src[l].splice(i,1);});
 // pListFor, not `||[]`: a string is truthy, so `src[val]||[]` kept it and the
 // push threw. The remove loop above already guarded; this half did not.
 if(val)pListFor(src,val).push(name);
 pPrune();}
/**
 * Add one glob to one list in one scope, if it is not already there.
 *
 * The half the per-row switches cannot do, and the reason the raw rules table
 * exists: `PUT /api/policy` replaces the block wholesale, so a rule this form
 * cannot show is a rule it must not be trusted to save.
 *
 * Deliberately does NOT prune: nothing was emptied, and the caller has just
 * asked for a list to exist.
 *
 * @param {string} kind - a kind from `PKINDS`
 * @param {'allow'|'deny'} list
 * @param {string|null} tag - an area tag, or null for the project scope
 * @param {string} pattern - a shell-style glob; the caller has already trimmed
 *   it and refused an empty one
 * @returns {void} it mutates `PDRAFT`; a duplicate is a silent no-op, because
 *   the list is a set and adding twice is not an error the reader made
 */
function pAddPattern(kind,list,tag,pattern){
 const b=pBlock(),k=b[kind]=b[kind]||{};
 let src=k;
 if(tag){const a=k.areas=k.areas||{};src=a[tag]=a[tag]||{};}
 const arr=pListFor(src,list);
 if(!arr.includes(pattern))arr.push(pattern);}
/**
 * Remove one glob from one list in one scope, then prune whatever that emptied.
 *
 * Reads the draft directly rather than through `pBlock`, so removing from a
 * project that has no block cannot bring one into existence.
 *
 * @param {string} kind - a kind from `PKINDS`
 * @param {'allow'|'deny'} list
 * @param {string|null} tag - an area tag, or null for the project scope
 * @param {string} pattern
 * @returns {void} it mutates `PDRAFT`; a list that is missing or is not a list
 *   is left alone rather than being replaced by one
 */
function pDropPattern(kind,list,tag,pattern){
 const src=tag?((pKindCfg(PDRAFT,kind).areas||{})[tag]||{}):pKindCfg(PDRAFT,kind);
 const arr=src[list];if(!Array.isArray(arr))return;
 const i=arr.indexOf(pattern);if(i>=0)arr.splice(i,1);
 pPrune();}
// Emptying a list REMOVES it, and removing the last one removes its container —
// the same convention Settings writes with, for the same reason: a block listing
// every default is a block nobody can read, and `"areas":{"web":{"deny":[]}}` is
// a rule that looks like a rule and is not one.
/**
 * Drop every empty list, every area left with nothing, and every kind left with
 * nothing, from the draft.
 *
 * Runs after each removal rather than at save time, so what the change dialog
 * describes is what will be written.
 *
 * @returns {void} it mutates `PDRAFT`, and does nothing at all when there is no
 *   draft — pruning must not be the thing that creates a block
 */
function pPrune(){
 if(!PDRAFT)return;
 for(const kind of PKINDS){
  const k=PDRAFT[kind];if(!k||typeof k!=='object')continue;
  ['allow','deny'].forEach(l=>{if(Array.isArray(k[l])&&!k[l].length)delete k[l];});
  if(k.areas&&typeof k.areas==='object'){
   for(const tag of Object.keys(k.areas)){const r=k.areas[tag]||{};
    ['allow','deny'].forEach(l=>{if(Array.isArray(r[l])&&!r[l].length)delete r[l];});
    if(!Object.keys(r).length)delete k.areas[tag];}
   if(!Object.keys(k.areas).length)delete k.areas;}
  if(!Object.keys(k).length)delete PDRAFT[kind];}}
// --- what changed, and every rule as written ------------------------------------
// The change rows, computed the same way Settings computes its own: this block is
// one key of the config, the server writes it through the one config writer, and
// the echo comes back as `config · policy.skills.deny · … -> …`. So the dialog is
// fed a whole config with this block swapped in, and cannot describe the save in a
// vocabulary the server does not answer in.
/**
 * The unsaved change rows for this tab, in the vocabulary the server echoes
 * back.
 *
 * The policy is ONE key of the config and the server writes it through the one
 * config writer, so the diff is computed by handing `configChanges` a whole
 * config with this block swapped in. Diffing the block alone would describe the
 * save in a vocabulary the echo does not answer in.
 *
 * @returns {Array<{target: 'config', field: string,
 *   from: string|boolean|string[]|null, to: string|boolean|string[]|null}>}
 *   one row per changed config path, as `config · policy.skills.deny · … -> …`.
 *   `field` is the dotted path, arrays arrive whole because a rule list is one
 *   value to a reader, and null means the key is ABSENT on that side — which is
 *   how "use the shipped default" is written. [] when nothing has been typed,
 *   which is also what an untouched project returns: a null draft cannot differ
 *   from the file
 */
function policyChanges(){
 if(PDRAFT===null)return [];
 const cfg=JSON.parse(JSON.stringify(STATE.config||{}));
 cfg.policy=PDRAFT;
 return configChanges(cfg);}
// Every pattern in the draft, in the order `resolve` reads them: deny before
// allow, project before area. Annotated from the server's own matching where the
// server has seen the pattern — a rule typed a second ago has no match count and
// says so rather than borrowing the count of the one it replaced.
/**
 * Every pattern the DRAFT states for one kind, in resolution order.
 *
 * Deny before allow, project before area, areas alphabetically — the order
 * `_policy.resolve` reads them in, so the table can be read top-down as the
 * reason. That ordering is also written on the server, in
 * `_panel_policy._policy_rules`; this exists because the server has never seen
 * the draft, and the two must state the same order or the same block reads
 * differently before and after a save.
 *
 * Unlike the server's version this does not check that a list IS a list — see
 * `pRuleOf` and the Faults list. On a hand-edited `"deny": "nope"` it throws,
 * and it is called from the render, so the whole tab goes blank.
 *
 * @param {string} kind - a kind from `PKINDS`
 * @returns {Array<{scope: string|null, list: 'allow'|'deny', pattern: string}>}
 *   the draft's rules; [] for a kind with none, which the caller renders as the
 *   default's consequence rather than as an empty table
 */
function pDraftRules(kind){
 const out=[],k=pKindCfg(PDRAFT,kind);
 const push=(scope,list)=>{const src=scope?((k.areas||{})[scope]||{}):k;
  pList(src,list).forEach(p=>out.push({scope:scope||null,list:list,pattern:p}));};
 push(null,'deny');push(null,'allow');
 Object.keys(k.areas||{}).sort().forEach(tag=>{push(tag,'deny');push(tag,'allow');});
 return out;}
/**
 * The identity of one rule, for joining a drafted rule to the server's copy of
 * it. Scope, list and pattern together: the same pattern in two lists, or in
 * two scopes, is two different rules.
 *
 * @param {{scope: string|null, list: string, pattern: string}} r
 * @returns {string} a stable key — `||null` folds '' and undefined onto the
 *   project scope, which is how both sides spell it
 */
const pRuleKey=r=>JSON.stringify([r.scope||null,r.list,r.pattern]);

/**
 * The server's rules for one kind, keyed for lookup, so a drafted rule can be
 * annotated with what it matches today.
 *
 * @param {string} kind - a kind from `PKINDS`
 * @returns {Object<string, PolicyRule>} keyed by `pRuleKey`. A rule typed a
 *   second ago is simply absent, which is what lets the table say "not saved
 *   yet" rather than borrowing the match count of the rule it replaced
 */
function pServerRules(kind){const m={};
 ((POLICY.rules||{})[kind]||[]).forEach(r=>{m[pRuleKey(r)]=r;});return m;}

// --- which area columns the table draws -----------------------------------------
// ONE COLUMN PER AREA DOES NOT SCALE. The tags come from the plan, not from this
// file, so eight areas is eight selects on every row and a sideways scroll of `—`.
// A column is drawn for an area that CARRIES A RULE, and the reader can ask for any
// of the others by name.
//
// "Carries a rule" and "is active" are DIFFERENT PREDICATES and the difference is
// the whole reason this is written down. An area rule applies only while some phase
// in that area has work in progress, so a dormant area's rules decide nothing today
// - and decide everything the moment that phase starts. Hiding a dormant area that
// carries a rule would therefore hide a rule that is one status change from being
// enforced, which is exactly the surprise the `dormant` label exists to remove. So
// liveness decides how a column is LABELLED and never whether it exists.
//
// Revealing a column writes nothing. The cells inside one are the same `pCell`
// selects as any other column, so `pSetRule` stays the one writer and `pAddPattern`
// stays the only way to state a glob - a pill decides what is on screen and that is
// all it decides.

/**
 * Does this scope state a rule at all?
 *
 * Generous on purpose. A non-empty list is a rule, and so is a MALFORMED value:
 * `"deny": "nope"` is something a person wrote into the config, the server
 * reports it as a finding, and a column that vanished on it would be hiding the
 * reader's own file. An EMPTY list is not a rule - the same reading `pPrune`
 * takes when it deletes one, and `"areas":{"web":{"deny":[]}}` is a rule that
 * looks like a rule and is not one.
 *
 * @param {Object} src - a scope object: one area's `{allow, deny}`
 * @returns {boolean} whether either list states anything
 */
const pStatesRule=src=>['deny','allow'].some(l=>{const v=src&&src[l];
 return Array.isArray(v)?v.length>0:v!=null;});

/**
 * The area tags one block states a rule for, in one kind.
 *
 * @param {PolicyBlock|null} block - the draft, or the saved block
 * @param {string} kind - a kind from `PKINDS`
 * @returns {string[]} the tags, in whatever order the object holds them; the
 *   caller orders them by `areaInfo`, which is the server's own order
 */
function pRuledAreas(block,kind){
 const areas=pKindCfg(block,kind).areas;
 if(!areas||typeof areas!=='object')return [];
 return Object.keys(areas).filter(tag=>pStatesRule(areas[tag]));}

/**
 * Which area columns the capability table draws, which it leaves out, and which
 * ones are the reader's to ask for.
 *
 * BOTH BLOCKS ARE CONSULTED, draft and saved, and the union is deliberate: a
 * reader who puts a cell back to `—` empties that area and `pPrune` removes it,
 * so a draft-only predicate would take the column away in the same repaint that
 * put the "unsaved" badge inside it - the edit and the evidence of the edit would
 * disappear together.
 *
 * @param {string} kind - a kind from `PKINDS`
 * @returns {{shown: Object[], hidden: Object[], ruleless: Object[]}} `areaInfo`
 *   entries in the server's order. `ruleless` is every area with no rule for this
 *   kind, drawn or not, and `hidden` is the part of it that has no column right
 *   now - what the strip above the table has to name, because an area without a
 *   column must never read as an area without a rule
 */
function pCols(kind){
 const info=(POLICY&&POLICY.areaInfo)||[];
 const ruled=new Set(pRuledAreas(PDRAFT,kind)
   .concat(pRuledAreas(POLICY&&POLICY.stored,kind)));
 const drawn=a=>ruled.has(a.tag)||PF.cols.indexOf(a.tag)>=0;
 return {shown:info.filter(drawn),hidden:info.filter(a=>!drawn(a)),
   ruleless:info.filter(a=>!ruled.has(a.tag))};}

/**
 * Put one ruleless area's column on screen, or take it away again.
 *
 * @param {string} tag - an area tag
 * @returns {void} it moves `PF.cols` and touches no policy at all; the caller
 *   redraws. An area that carries a rule is not offered this control, because a
 *   column that could be hidden while it decides something is a column that can
 *   read as "no rule here"
 */
function pToggleCol(tag){
 const i=PF.cols.indexOf(tag);
 if(i>=0)PF.cols.splice(i,1);else PF.cols.push(tag);}

// --- the capability table, given the whole viewport -----------------------------
// ONE builder (pCapTable, below) serves the Policy tab and the expanded dialog.
// Its `full` flag decides only the element ids — a document may hold one element
// per id, and both copies carry a search box — and whether the frame caps its own
// height, since in the dialog the DIALOG is the frame.
//
// A native <dialog>, so the focus trap, the backdrop and Esc are the platform's:
// the browse dialog's pattern, for the same reason — this is a LIST, and reading
// a verdict per area means reading across it. Three constraints hold it together.
// It lives on <body>, because renderPolicy rebuilds the whole tab on every
// keystroke and a dialog inside the tab would be destroyed mid-type. It is
// refilled from the same builder the tab uses, so the two cannot disagree about
// a verdict. And the box it types into writes the TAB's filter, so expanding
// never costs you your place.

/**
 * The expanded capability table, built on first open and reused after that.
 * @type {HTMLDialogElement|null}
 */
let POLFULL=null;

/**
 * Refill the expanded table from the current state, in place.
 *
 * Called by `renderPolicy` in the same pass as the tab, BEFORE focus is
 * restored, since the box the caret belongs in may be inside this dialog.
 *
 * @returns {void} a no-op while the dialog does not exist, is closed, or has no
 *   policy to show — all three are ordinary states, not failures
 */
function polFullFill(){
 if(!POLFULL||!POLFULL.open||!POLICY)return;
 const kind=PF.kind,rows=((POLICY.resolved||{})[kind]||[]);
 const cap=pCapTable(kind,rows,true);
 POLFULL.replaceChildren(...[
   el('div',{class:'bhead'},
     el('h3',{},PKLABEL[kind]+' — what this project can reach'),
     el('button',{class:'bx',title:'close','aria-label':'close',
       onclick:()=>POLFULL.close()},'\u2715')),
   cap.tools,cap.colstrip,cap.body].filter(Boolean));}
/**
 * Open the expanded capability table, building it the first time.
 *
 * @returns {void} it opens the dialog and fills it; the caret hand-back on close
 *   is the shared opener's job, not this function's
 */
function polFullOpen(){
 if(!POLFULL){POLFULL=el('dialog',{class:'polfull'});
  POLFULL.addEventListener('click',ev=>{if(ev.target===POLFULL)POLFULL.close();});
  // An <input type=search> eats the FIRST Escape to clear itself, so a dialog
  // whose caret sits in one closes on the SECOND press — which reads as the key
  // being broken (the browse dialog hit this first). Handled on the dialog, not
  // on the box: the box is built by pCapTable and the tab's copy of it must not
  // close anything. One Escape, one effect.
  POLFULL.addEventListener('keydown',ev=>{
    if(ev.key==='Escape'){ev.preventDefault();POLFULL.close();}});
  document.body.append(POLFULL);}
 // Esc and the ✕ both land in dlgOpen's close handler, which gives the caret back
 // to the control that opened it — a dialog that closes into nowhere leaves a
 // keyboard reader at the top of the document. The selector is passed explicitly
 // because the node is gone by then: typing in the dialog re-renders the tab
 // underneath, which replaces that button. Keeping it AFTER the close is
 // renderPolicy's job, not this one's.
 dlgOpen(POLFULL,'#policy [data-polexpand]');polFullFill();}
