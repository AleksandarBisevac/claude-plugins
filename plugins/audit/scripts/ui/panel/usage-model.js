// ---------- usage ----------
// ONE filter state. The chart's dimension is DERIVED from it, never stored
// separately -- an earlier version kept a parallel drill-down object and filtered
// author in two places, which let you select one author, click another's line, and
// land in a permanently empty view whose controls said nothing was filtered. With a
// single author slot that state cannot be represented at all.
/**
 * One row of `USAGE.facts`: the ledger folded onto the fact key, positional so
 * that twenty thousand of them cross the wire without twenty thousand copies of
 * the key names. Read it through `F` below, never by a bare number.
 *
 * `uHay` additionally caches a lower-cased search string on the row as `.h`, so
 * a row searched once is not re-joined on the next keystroke.
 *
 * @typedef {[string, string, string, string, string, string, string, number,
 *   number, number]} UsageFact
 */

/**
 * `[tokens, cost, msgs]` — what every aggregation in this tab sums into. Also
 * positional, and unlike `UsageFact` it has no index constant of its own: its
 * readers spell `v[0]`, `v[1]`, `v[2]`.
 *
 * @typedef {[number, number, number]} UsageTriple
 */

/**
 * The whole `GET /api/usage` payload, or null before the first fetch and after
 * one that failed. `_panel_usage._usage_shape` is the one place the key set is
 * declared, so that is the thing to read when a key is in question here.
 *
 * @typedef {{
 *   facts: UsageFact[], fields: string[], showCost: boolean,
 *   phaseTitles: Object<string, string>,
 *   taskMeta: Object<string, {title: string}>,
 *   phaseAreas: Object<string, string[]>,
 *   phaseBudgets: Object<string, number>,
 *   counts: {phases: number, tasks: number, models: number, authors: number,
 *     sessions: number, days: number, from: string|null, to: string|null}
 * }} UsagePayload
 */

/** @type {UsagePayload|null} */
let USAGE=null;

/**
 * The one filter state. Every slot holds a single string, and '' means "not
 * filtering on this". `day` holds either one ISO day or `from..to`; `range` is
 * a preset in days or the literal 'all'; `bin` is the trend's resolution.
 *
 * @type {{model: string, author: string, phase: string, task: string,
 *   agent: string, attr: string, area: string, day: string, q: string,
 *   range: 'all'|'7'|'30'|'90'|'365', bin: 'auto'|'day'|'week'|'month'}}
 */
const UF={model:'',author:'',phase:'',task:'',agent:'',attr:'',area:'',day:'',q:'',range:'all',bin:'auto'};

/**
 * The slots of `UF` that wear a chip and can be lifted one at a time. `range`
 * and `bin` are knobs with controls of their own and are deliberately absent.
 * @type {string[]}
 */
const DIMS=['model','author','phase','task','agent','attr','area','day','q'];
// What a filter is CALLED where it is shown. The internal name is the fact-tuple
// field, which is the right name in the code and the wrong one on a chip: `attr` is
// not a word, and `q` is not a dimension anybody typed.
// `range` is not in DIMS and never wears a chip, but it is a filter a reader can
// be asked about by name, so it is named here with the rest rather than spelled
// out at the one place that asks.
/**
 * Only the dimensions whose internal name is the wrong word on screen. A
 * dimension absent from here is shown under its own name, which is why this is
 * a partial map and not a full one.
 * @type {Object<string, string>}
 */
const DLABEL={q:'text',attr:'attribution',agent:'agent',day:'date',
 range:'time range'};

/**
 * What a dimension is CALLED where it is shown.
 * @param {string} d - a `UF` slot name, from `DIMS` or 'range'
 * @returns {string} the shown name, falling back to the slot name itself
 */
const fName=d=>DLABEL[d]||d;

/**
 * What a dimension's current value READS AS on its chip. Three shapes, because
 * three of these filters are not plain values: a day slot may be a span, the
 * range is a preset rather than a datum, and everything else goes through
 * `uKey` — a chip is a sentence about what you are looking at, so it says the
 * word rather than the key it filters on.
 *
 * @param {string} d - a `UF` slot name, from `DIMS` or 'range'
 * @returns {string} the value as a reader should see it; '' when the slot is empty
 */
const fVal=d=>d==='day'?UF.day.replace('..',' to ')
 :d==='range'?(UF.range==='all'?'all time':'last '+UF.range+' days')
 :uKey(UF[d]);

/**
 * The dimensions currently set, oldest first, so Escape lifts the most recent.
 * Rebuilt from parameter order on a reload — see `uApplyFragment`.
 * @type {string[]}
 */
let UORDER=[];

/**
 * The free-text box's debounce handle. The whole tab re-renders per change, so
 * the keystrokes are collapsed rather than the render being made cheaper.
 * @type {number|null}
 */
let UQT=null;

/**
 * How deep each ranked list is currently shown, keyed by dimension. Session
 * furniture: never persisted, and reset to `TOP` whenever the scope changes.
 * @type {Object<string, number>}
 */
const SHOWN={phase:8,model:8,author:8,task:8};

/**
 * The column of a `UsageFact` by name. The payload ships its own `fields` list
 * in the same order; this is the client's index into it.
 * @type {{ts: number, phase: number, task: number, model: number,
 *   author: number, agent: number, attr: number, tokens: number,
 *   cost: number, msgs: number}}
 */
const F={ts:0,phase:1,task:2,model:3,author:4,agent:5,attr:6,tokens:7,cost:8,msgs:9};

/** Risk bands, worst first, so an `indexOf` on this sorts by severity. */
const RISKS=['high','med','low','unrated'];

/**
 * How many rows a ranked list shows before it pages, and the depth every list
 * goes back to when the scope changes. Not the palette's width: `uSlots` writes
 * its own bound, because a list getting longer must not repaint a chart.
 */
const TOP=8;
// --- the numbers, and the Python they mirror -----------------------------------
// toFixed breaks an exact tie AWAY from zero; Python's "%.*f" breaks it to EVEN.
// That shipped: 1250 tokens read '1.3K' here against _fmt.py's '1.2K', $0.125 read
// '$0.13' against '$0.12', and a 2.5% share read '3%' against '2%'. A different
// rounding MODE, not float noise - the inputs are exactly representable in binary.
//
// A double is an exact tie at `dp` places IFF x * 2^(dp+1) is an ODD integer. A tie
// is (2j+1)/(2*10^dp), and a double is only ever a dyadic rational, so 5^dp must
// divide (2j+1) - which leaves x = t/2^(dp+1) with t odd. Scaling by a power of two
// only shifts the exponent, so that test is exact. Scaling by 10^dp is NOT, and that
// is the trap: `n*100 === Math.round(n*100)` misclassifies the majority of values,
// which are not representable. A value that is not a tie (1.35, 3.05) fails this
// test and keeps toFixed's answer, which already agrees with Python.
//
// On a tie toFixed returns the away-from-zero neighbour, so its last digit is odd
// exactly when Python picks the other one - and stepping that digit down by one
// never borrows, because an odd digit is never 0.
//
// Written twice, once per dialect, because there is no build step that could share
// it with report.js's `fixedHalfEven`. That is the known cost, and
// tools/ui-tests/half-even.test.mjs holds the two copies equal against _fmt.py - a
// comment asserting they match is the thing that was already false here once.

/**
 * `x.toFixed(dp)`, but with Python's tie rule instead of JavaScript's: an exact
 * tie goes to the EVEN neighbour, which is what `"%.*f"` does and what every
 * `_fmt.py` formatter therefore does.
 *
 * A value that is not a tie is returned exactly as toFixed rendered it, because
 * toFixed already agrees with Python everywhere else. So this steps only the
 * cases toFixed gets wrong, and the test for "is it a tie" is the exact one
 * described above — scaling by a power of ten to ask the same question is not.
 *
 * @param {number} x - the value to render; a non-finite one is handed back as
 *   toFixed rendered it, since it has no tie to break
 * @param {number} dp - decimal places
 * @returns {string} the fixed-point rendering, rounded half-to-even
 */
function uFixedHalfEven(x,dp){
 const s=x.toFixed(dp);
 const scaled=x*Math.pow(2,dp+1);
 if(!isFinite(scaled)||Math.floor(scaled)!==scaled||scaled%2===0)return s;
 const last=s.charCodeAt(s.length-1)-48;
 return last%2===1?s.slice(0,-1)+String(last-1):s;}
// Token counts are a MAGNITUDE and are always compact - '3.2M', never '3,230,000'.
// dp=2 is for hover: pointing at a bar buys '3.23M', more precision than the label
// without dumping the raw integer. Countables (messages, sessions) are not
// magnitudes and keep their separators - '47,625' is a number you can act on.

/**
 * A token count as a compact magnitude, in the shape `_fmt.fmt_tokens`
 * (plugins/audit/scripts/_fmt.py) renders it — the ONE token formatter, which
 * the report's `_fmt_tokens` (scripts/report/_report_usage.py) also delegates
 * to.
 *
 * THE ROUNDING RULE, EXACTLY. The compacted value goes through
 * `uFixedHalfEven`, so an exact tie breaks to even the way Python's `"%.*f"`
 * does; it used to be a bare toFixed, which broke a tie away from zero and made
 * 1250 tokens read '1.3K' here against _fmt.py's '1.2K'. Below the smallest
 * magnitude the value is TRUNCATED toward zero, matching Python's `int(n)`; it
 * used to round, so uTok(2.6) said '3' where every other surface said '2'.
 *
 * THE TRUNCATION HAPPENS AT ENTRY, which is where Python's does. It used to
 * happen only on the path below the smallest magnitude, so a FRACTIONAL input at
 * or above 1000 had its fraction divided into the quotient while
 * `_fmt.fmt_tokens` and report.js's `fmtTokens` dropped it first — measured, 28
 * disagreements across a sweep of every magnitude boundary, against 0 for the
 * report. The live fractional caller is the trend chart's y-axis tick in
 * usage-charts.js; a ledger row carries integers and was never affected.
 *
 * Closing it was a paired change rather than a one-liner. Entry truncation makes
 * the old tail `String(Math.trunc(n))` redundant, and leaving it would have left
 * the mutation in tools/ui-tests/mutants.test.mjs applying and proving nothing —
 * a value already truncated cannot tell Math.trunc from Math.round. So the tail
 * went, the mutation moved to this line, and a second mutation was added for the
 * direction the first cannot express: not how it rounds, but WHERE it truncates.
 *
 * What agreement there is, is held by tools/ui-tests/number-format.test.mjs and
 * not by this comment.
 *
 * @param {number} n - a token count; a missing or zero-ish value renders as '0'
 * @param {number} [dp=1] - decimals kept past the magnitude letter; 2 is the
 *   hover precision
 * @returns {string} e.g. '3.2M', or the truncated integer below a thousand
 */
const uTok=(n,dp=1)=>{n=Math.trunc(n||0);
 for(const[l,s]of[[1e9,'B'],[1e6,'M'],[1e3,'K']])
 if(Math.abs(n)>=l)return uFixedHalfEven(n/l,dp)+s;return String(n);};

/**
 * A dollar amount, mirroring `_fmt.fmt_cost`: half-to-even at two places, and
 * spend that is real but under a cent says so rather than rendering '$0.00',
 * which reads as free. A true zero DOES render '$0.00' — the mirror-image lie
 * would be claiming a presence the data has none of.
 *
 * Verified against `_fmt.fmt_cost` across both branches, including the tie and
 * the negatives, in tools/ui-tests/number-format.test.mjs. `fmt_cost`'s
 * `show=False` arm has no twin here; whether cost is shown at all is decided by
 * `USAGE.showCost` at the call sites.
 *
 * @param {number} x - dollars
 * @returns {string} '$0.00', '<$0.01', or '$' and the amount
 */
const uCost=x=>!x?'$0.00':(Math.abs(x)<0.01?'<$0.01':'$'+uFixedHalfEven(x,2));

/**
 * A percentage, mirroring the formatting half of `_fmt.fmt_share`: half-to-even
 * at no decimals, `<1%` for a real slice that would otherwise round to nothing,
 * and an em dash for a share that could not be computed. It takes the number
 * `uShare` returns, so null arrives here rather than being invented upstream.
 *
 * ON MAGNITUDE, like `fmt_share` and like `uCost` beside it. This tested `x>0`
 * instead, and the note here argued the difference was unreachable because a
 * share of tokens is non-negative by construction. The argument was true and it
 * was still the wrong shape: two implementations of one number that differ
 * anywhere leave a reader to re-derive the reachability every time they touch
 * either, and a corpus without a negative in it could not tell them apart. They
 * agree now, and the cases include negatives so that stays checked rather than
 * argued. An exact zero still renders '0%' on both sides — a slice of nothing
 * does not exist, and '<1%' would invent a presence.
 *
 * @param {number|null} x - a percentage from `uShare`, not a fraction
 * @returns {string} 'NN%', '<1%', or '—' when there was nothing to take a share of
 */
const uPct=x=>x==null?'—':(x&&Math.abs(x)<1)?'<1%':uFixedHalfEven(x,0)+'%';
// A share of nothing is not 0% and it is certainly not 100% — it is undefined, and
// the honest rendering of undefined is the same em dash a tile with no series
// already draws. EVERY printed percentage in this tab is computed here, because
// the idiom it replaces — `||1` on the denominator, written to dodge a divide by
// zero — answers a question that has no answer: `100*(1-0)/1` made the
// `attributed` tile read 100% over an empty selection, beside three honest zeros,
// on the one tile of the four that is coloured by polarity. A denominator may
// still carry `||1` where the quotient is a bar WIDTH or a sparkline's range —
// a scale is a drawing decision, not a claim — and nowhere else.

/**
 * `part` as a percentage of `whole`, or null when there is no whole to divide
 * by, mirroring `_fmt.share_pct`. Deliberately NOT clamped to 100: a phase
 * tagged with several areas counts under each, so by-area columns genuinely sum
 * past the total and every by-area rendering says so. Clamping belongs to
 * whatever has a box to fit inside.
 *
 * Zero, NaN and missing all mean "unmeasurable" here, and that agreement with
 * `share_pct` is pinned on EACH SIDE SEPARATELY for NaN: the bridge that holds
 * the two equal passes values as JSON, and JSON has no NaN. It is the one value
 * they had actually drifted on - NaN is truthy in Python, so `not whole` let it
 * through and `fmt_share` rendered a percentage of NaN.
 *
 * @param {number} part
 * @param {number} whole - zero, NaN or missing all mean "unmeasurable"
 * @returns {number|null} the percentage, or null for every reader to render as
 *   unknown rather than as a number nobody could compute
 */
const uShare=(part,whole)=>whole?100*part/whole:null;

// --- which entity wears which hue ----------------------------------------------
// Colour follows the entity, never its rank in the current view: a slot comes from
// the entity's spend rank across the WHOLE ledger, so filtering cannot repaint a
// series that already had a colour. Model colours live in their own map so a model
// keeps one identity whether the chart is showing authors or models.
//
// Past the 8 validated hues there is no stable map left to preserve — forty people
// cannot each keep a distinct colour. The earlier rule (sorted name, capped at 8)
// preserved the invariant by handing SEVEN of eight plotted authors the same red,
// which is the one failure a categorical palette cannot survive. So: whoever is in
// the global top 8 keeps their hue under every filter, and anyone else who reaches
// the chart takes a slot the current view leaves free. Survivors never repaint;
// newcomers gain a colour they did not have before.
//
// Models order by NAME, which is the rule render-report.py's _model_slots uses, so
// a model wears the same hue in the report and the panel. Authors order by spend,
// because there is no report chart to agree with and rank is the useful priority
// when only 8 of 40 can be coloured.
/**
 * The palette slot each entity currently holds, rebuilt per render by
 * `uSlots`: `USLOTS` for whatever the chart is splitting by, `MSLOTS` for
 * models, so a model keeps one identity while the chart is showing authors.
 * @type {Object<string, number>}
 */
let USLOTS={}, MSLOTS={};

/**
 * Every value of one fact column, ranked, as a map from value to a
 * zero-based position. Computed over the WHOLE ledger and never over the
 * filtered rows, which is what makes a slot stable under filtering.
 *
 * @param {number} field - a column index from `F`
 * @param {'name'|'spend'} by - 'name' sorts lexically, which is the rule
 *   render-report.py's `_model_slots` uses, so a model wears one hue across both
 *   surfaces; 'spend' sorts by token total, descending, with the name breaking a
 *   tie so the order is total rather than iteration-dependent
 * @returns {Object<string, number>} value to rank
 */
function uRanks(field,by){
 if(by==='name'){const o={};
  [...new Set(USAGE.facts.map(f=>f[field]))].sort().forEach((k,i)=>o[k]=i);
  return o;}
 const t={};
 for(const f of USAGE.facts)t[f[field]]=(t[f[field]]||0)+f[F.tokens];
 const o={};Object.keys(t).sort((a,b)=>t[b]-t[a]||(a<b?-1:1))
  .forEach((k,i)=>o[k]=i);return o;}
/**
 * Hand each drawn entity a palette slot, in two passes. First pass: everyone in
 * the global top ranks keeps the slot their rank names, so a filter cannot
 * repaint a series that already had a colour. Second pass: everyone else takes
 * the lowest slot the first pass left free.
 *
 * Two series in one hue is the failure a categorical palette cannot survive, and
 * it only appears past the palette's width — exactly where nobody looks. The
 * capped-index rule this replaced gave forty authors one shared red. So the
 * invariant is that every DRAWN series gets a distinct slot; what a series
 * cannot be promised is that it gets a slot at all.
 *
 * The 'other' bucket and empty keys are dropped rather than coloured: they are
 * not entities.
 *
 * @param {number} field - a column index from `F`
 * @param {Iterable<string>} present - the keys actually being drawn
 * @param {'name'|'spend'} by - passed through to `uRanks`
 * @returns {Object<string, number>} key to a one-based slot; a key with no slot
 *   left is absent, and `uCol` renders it neutral
 */
function uSlots(field,present,by){
 const rank=uRanks(field,by),used=new Set(),out={};
 const keys=[...new Set(present)].filter(k=>k&&k!=='other')
  .sort((a,b)=>(rank[a]==null?1e9:rank[a])-(rank[b]==null?1e9:rank[b]));
 for(const k of keys){const r=rank[k];
  if(r!=null&&r<8&&!used.has(r+1)){out[k]=r+1;used.add(r+1);}}
 let free=1;
 for(const k of keys){if(out[k])continue;
  while(free<=8&&used.has(free))free++;
  if(free<=8){out[k]=free;used.add(free);}}
 return out;}
/**
 * The colour for one key of whatever the chart is currently splitting by.
 * @param {string} k - an entity key
 * @returns {string} a reference to the palette token for its slot, or to the
 *   neutral bar token for a key that got no slot — never a raw colour, so the
 *   theme still owns it
 */
function uCol(k){return USLOTS[k]?'var(--viz-'+USLOTS[k]+')':'var(--bar-neutral)';}

/**
 * The colour for one MODEL, from the model-only map, so a model keeps its hue
 * while the chart is split by something else.
 * @param {string} k - a model name
 * @returns {string} a reference to the palette token for its slot, or to the
 *   neutral bar token
 */
function uMCol(k){return MSLOTS[k]?'var(--viz-'+MSLOTS[k]+')':'var(--bar-neutral)';}

/**
 * Set one filter slot and redraw the tab. The single entry point for every
 * filter change, which is what keeps `UORDER` a true history of what was
 * applied — a chip, a chart click and a dropdown all arrive here.
 *
 * A dimension set to '' is REMOVED from the order rather than left in it, so
 * Escape never pops a filter that is not on.
 *
 * @param {string} dim - a `UF` slot name
 * @param {string} val - the new value; falsy clears the slot
 * @returns {void} it renders, so there is nothing to hand back
 */
function setF(dim,val){
 UF[dim]=val||'';
 UORDER=UORDER.filter(d=>d!==dim);
 if(UF[dim])UORDER.push(dim);
 if(dim!=='day')SHOWN[dim]=TOP;      // a new scope starts from the top again
 renderUsage();}
/**
 * Put every filter back to its default and redraw: the slots, the order, the
 * range and bin knobs, the stored twin and the fragment.
 *
 * @returns {void} it renders, so there is nothing to hand back
 */
function clearAll(){DIMS.forEach(d=>UF[d]='');UF.range='all';UF.bin='auto';UORDER=[];
 // Cleared HERE and not left to the render's persist pass: a pin that vouches
 // for this behaviour has to sit inside this function's own slice, and a pin
 // outside the function it vouches for vouches for nothing.
 storageDrop(UFSTORE);
 syncUFHash('');
 DIMS.forEach(d=>{if(d in SHOWN)SHOWN[d]=TOP;});renderUsage();}

