// ---------- usage ----------
// ONE filter state. The chart's dimension is DERIVED from it, never stored
// separately -- an earlier version kept a parallel drill-down object and filtered
// author in two places, which let you select one author, click another's line, and
// land in a permanently empty view whose controls said nothing was filtered. With a
// single author slot that state cannot be represented at all.
let USAGE=null;
const UF={model:'',author:'',phase:'',task:'',agent:'',attr:'',area:'',day:'',q:'',range:'all',bin:'auto'};
const DIMS=['model','author','phase','task','agent','attr','area','day','q'];
// What a filter is CALLED where it is shown. The internal name is the fact-tuple
// field, which is the right name in the code and the wrong one on a chip: `attr` is
// not a word, and `q` is not a dimension anybody typed.
// `range` is not in DIMS and never wears a chip, but it is a filter a reader can
// be asked about by name, so it is named here with the rest rather than spelled
// out at the one place that asks.
const DLABEL={q:'text',attr:'attribution',agent:'agent',day:'date',
 range:'time range'};
const fName=d=>DLABEL[d]||d;
const fVal=d=>d==='day'?UF.day.replace('..',' to ')
 :d==='range'?(UF.range==='all'?'all time':'last '+UF.range+' days')
 // uc: a chip is a sentence about what you are looking at, so it says the word
 // rather than the key it filters on.
 :uKey(UF[d]);
let UORDER=[];                 // dimensions in the order they were set (Esc pops)
let UQT=null;                  // search debounce; the whole tab re-renders per change
const SHOWN={phase:8,model:8,author:8,task:8};   // ranked-list depth; 'other' pages
const F={ts:0,phase:1,task:2,model:3,author:4,agent:5,attr:6,tokens:7,cost:8,msgs:9};
const RISKS=['high','med','low','unrated'];
const TOP=8;
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
// Mirrors _fmt.fmt_tokens in plugins/audit/scripts/_fmt.py - the ONE token/cost
// formatter, which the report's `_fmt_tokens` (scripts/report/_report_usage.py)
// also delegates to. Truncates at entry exactly as `int(n)` does there; it used to
// round, so uTok(2.6) said '3' where every other surface said '2'. The agreement is
// held by tools/ui-tests/number-format.test.mjs, not by this sentence.
const uTok=(n,dp=1)=>{n=n||0;for(const[l,s]of[[1e9,'B'],[1e6,'M'],[1e3,'K']])
 if(Math.abs(n)>=l)return uFixedHalfEven(n/l,dp)+s;return String(Math.trunc(n));};
const uCost=x=>!x?'$0.00':(Math.abs(x)<0.01?'<$0.01':'$'+uFixedHalfEven(x,2));
const uPct=x=>x==null?'—':x<1&&x>0?'<1%':uFixedHalfEven(x,0)+'%';
// A share of nothing is not 0% and it is certainly not 100% — it is undefined, and
// the honest rendering of undefined is the same em dash a tile with no series
// already draws. EVERY printed percentage in this tab is computed here, because
// the idiom it replaces — `||1` on the denominator, written to dodge a divide by
// zero — answers a question that has no answer: `100*(1-0)/1` made the
// `attributed` tile read 100% over an empty selection, beside three honest zeros,
// on the one tile of the four that is coloured by polarity. A denominator may
// still carry `||1` where the quotient is a bar WIDTH or a sparkline's range —
// a scale is a drawing decision, not a claim — and nowhere else.
const uShare=(part,whole)=>whole?100*part/whole:null;

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
let USLOTS={}, MSLOTS={};
function uRanks(field,by){
 if(by==='name'){const o={};
  [...new Set(USAGE.facts.map(f=>f[field]))].sort().forEach((k,i)=>o[k]=i);
  return o;}
 const t={};
 for(const f of USAGE.facts)t[f[field]]=(t[f[field]]||0)+f[F.tokens];
 const o={};Object.keys(t).sort((a,b)=>t[b]-t[a]||(a<b?-1:1))
  .forEach((k,i)=>o[k]=i);return o;}
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
function uCol(k){return USLOTS[k]?'var(--viz-'+USLOTS[k]+')':'var(--bar-neutral)';}
function uMCol(k){return MSLOTS[k]?'var(--viz-'+MSLOTS[k]+')':'var(--bar-neutral)';}

function setF(dim,val){
 UF[dim]=val||'';
 UORDER=UORDER.filter(d=>d!==dim);
 if(UF[dim])UORDER.push(dim);
 if(dim!=='day')SHOWN[dim]=TOP;      // a new scope starts from the top again
 renderUsage();}
function clearAll(){DIMS.forEach(d=>UF[d]='');UF.range='all';UF.bin='auto';UORDER=[];
 // Cleared HERE and not left to the render's persist pass: the pin for this
 // lives inside this function's own slice (the F-D1 lesson — a pin outside
 // the function it vouches for vouches for nothing).
 try{localStorage.removeItem(UFSTORE);}catch(e){}
 syncUFHash('');
 DIMS.forEach(d=>{if(d in SHOWN)SHOWN[d]=TOP;});renderUsage();}

