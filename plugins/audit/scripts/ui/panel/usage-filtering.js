// ---------- filter persistence (fp) ----------
// A filtered Usage view is a LINK and it survives a reload. The grammar is
// `#/<tab>!k=v&…`: the tab route keeps the slot it always had and the filters
// ride behind the first `!` — the same marker the report uses to keep its
// filter fragment out of its own nav's way. Keys mirror the report's where
// the two surfaces overlap (m, au, a, day as from/to) so a habit learned on
// one transfers; ph/tk/ag/at/q are panel dimensions, r/b the range and bin
// knobs. UORDER is rebuilt from parameter ORDER, so Esc pops filters in the
// sequence they were applied even after a reload. SHOWN depths are session
// furniture and deliberately not carried. The store is keyed per PROJECT —
// filters describe one repo's plan; the theme and the active tab stay global
// on purpose (they describe the reader, not the repo).
const UFKEY={model:'m',author:'au',area:'a',phase:'ph',task:'tk',agent:'ag',attr:'at',q:'q'};
const UFDIM={};for(const d in UFKEY)UFDIM[UFKEY[d]]=d;
const UFSTORE='audit-panel-uf:'+PROJECT;
function uFragment(){
 const parts=[];
 const put=(k,v)=>{if(v)parts.push(k+'='+encodeURIComponent(v));};
 UORDER.forEach(d=>{
  if(d==='day'){const p=uDayPair();put('from',p[0]);put('to',p[1]);}
  else put(UFKEY[d],UF[d]);});
 if(UF.range!=='all')put('r',UF.range);
 if(UF.bin!=='auto')put('b',UF.bin);
 return parts.join('&');}
function uApplyFragment(frag){
 let any=false;
 (frag||'').split('&').forEach(pair=>{
  if(!pair)return;
  const i=pair.indexOf('='),k=i<0?pair:pair.slice(0,i);
  let v=i<0?'':pair.slice(i+1);
  try{v=decodeURIComponent(v);}catch(e){v='';}
  if(!v)return;
  const d=UFDIM[k];
  if(d){UF[d]=v;UORDER=UORDER.filter(x=>x!==d);UORDER.push(d);any=true;return;}
  if(k==='from'||k==='to'){
   const cur=(UF.day||'').split('..'),a=k==='from'?v:(cur[0]||''),
     b=k==='to'?v:(cur[1]||cur[0]||'');
   UF.day=(a||b)?(a===b?a:a+'..'+b):'';
   if(UF.day&&!UORDER.includes('day'))UORDER.push('day');
   any=true;return;}
  if(k==='r'&&['7','30','90','365'].includes(v)){UF.range=v;any=true;return;}
  if(k==='b'&&['day','week','month'].includes(v)){UF.bin=v;any=true;}});
 return any;}
// Empty filters take the fragment OFF (the report's own syncHash rule): a
// bare `#/usage` must not grow a trailing `!`.
function syncUFHash(frag){
 const h='#/'+(CURTAB||initialTab())+(frag?'!'+frag:'');
 try{if(location.hash!==h)history.replaceState(null,'',h);}catch(e){}}
function persistUF(){
 const frag=uFragment();
 try{if(frag)localStorage.setItem(UFSTORE,frag);
  else localStorage.removeItem(UFSTORE);}catch(e){}
 syncUFHash(frag);}

// Chart dimension is DERIVED: scoping to one author makes the interesting split
// their models. Nothing stores "which level am I on".
function chartDim(){return UF.author?'model':'author';}

// The text index behind the free-text box: everything about a row that a person
// could plausibly type, including the phase and task TITLES, which is what makes
// "checkout" find the work rather than only the id you would have to know already.
// Built once per fact and cached on the row, so the second keystroke rebuilds
// nothing across 20000 of them.
function uHay(f){
 if(f.h===undefined)f.h=[f[F.phase],f[F.task],f[F.model],f[F.author],f[F.agent],
   f[F.attr],(USAGE.phaseTitles||{})[f[F.phase]]||'',
   ((USAGE.taskMeta||{})[f[F.task]]||{}).title||'',
   (uAreas(f)||[]).join(' ')].join(' ').toLowerCase();
 return f.h;}

// A row's area is its PHASE's tags, joined at read time from the phaseAreas map
// the server ships (area is a property of the plan, not of the moment of spend).
// null - not [] - for a row with no tags: a phase the plan never tagged, a phase
// it never heard of, and a row with no phase at all are one 'untagged' bucket,
// which is the same bucket the CLI's BY AREA table keeps.
function uAreas(f){const a=(USAGE.phaseAreas||{})[f[F.phase]];
 return a&&a.length?a:null;}

// Every filter EXCEPT the date window, in one place. uFiltered() applies it to the
// window on screen and uDelta() applies it to the window before, and a dimension
// that existed in only one of them would compare two different populations while
// the chip said "vs prior 30d". The delta used to re-list its dimensions inline,
// which is a copy that goes stale the moment a filter is added — as three were
// here.
function uMatch(f){
 return (!UF.model||f[F.model]===UF.model)
  &&(!UF.author||f[F.author]===UF.author)
  &&(!UF.phase||f[F.phase]===UF.phase)
  &&(!UF.task||f[F.task]===UF.task)
  &&(!UF.agent||f[F.agent]===UF.agent)
  &&(!UF.attr||f[F.attr]===UF.attr)
  // A multi-tag phase matches ANY of its tags - one row can answer to two areas,
  // which is why every by-area rendering warns its columns can exceed the total.
  &&(!UF.area||(UF.area==='untagged'?!uAreas(f)
    :(uAreas(f)||[]).includes(UF.area)))
  &&(!UF.q||uHay(f).includes(UF.q.trim().toLowerCase()));}

function uFiltered(){if(!USAGE)return[];let out=USAGE.facts.filter(uMatch);
 if(UF.day){const[a,b]=UF.day.split('..');
  out=b?out.filter(f=>{const d=f[F.ts].slice(0,10);return d>=a&&d<=b;})
       :out.filter(f=>f[F.ts].slice(0,10)===a);}
 if(UF.range!=='all'){const d=new Date(Date.now()-parseInt(UF.range,10)*864e5)
   .toISOString().slice(0,10);out=out.filter(f=>f[F.ts].slice(0,10)>=d);}
 return out;}
const uAnyFilter=()=>UORDER.length>0||UF.range!=='all';

// Why the view is empty. "No rows match these filters" spread over eight controls
// is a puzzle, and one of the ways to empty this tab cannot be worked out from the
// screen at all: a range preset counts back from TODAY, so on a ledger whose last
// row is older than the window it selects nothing — which is the normal state of a
// FINISHED plan, and exactly when someone opens this tab to ask what it cost. That
// case is named outright, with both dates, because the reader's own conclusion
// would otherwise be that the metering never ran.
//
// The presets are deliberately NOT re-anchored on the data to make this go away: a
// control labelled "last 30 days" whose behaviour means "the last 30 days there
// happens to be data for" is a quieter defect than an empty result, and the label
// is what makes it one. (The report answers the neighbouring question differently
// and correctly — its presets measure back from the plan's own last day, and its
// labels say so.) An empty result that explains itself is the right answer here.
//
// Every count comes from uFiltered() with one slot temporarily blank — the same
// predicate the view itself runs. A second implementation of "what matches" is how
// an explanation ends up disagreeing with the thing it is explaining.
function uEmptyWhy(){
 const C=USAGE.counts||{};
 const toAll=()=>{UF.range='all';renderUsage();};
 if(UF.range!=='all'){
  const cut=new Date(Date.now()-parseInt(UF.range,10)*864e5)
    .toISOString().slice(0,10);
  if(C.to&&C.to<cut)return{why:'range-after-ledger',
   text:'The last '+UF.range+' days begin '+cut+', and the ledger ends '+C.to+
     ' — it stops before this window. Range presets count back from today, not '+
     'from the last day recorded.',
   fix:{key:'range',label:'Show all time',run:toAll}};}
 // Which single filter is doing it. Naming one and lifting one is the answer to a
 // question "clear filters" cannot answer: it throws away every filter that was
 // fine, so the reader learns nothing and has to rebuild the view to find out.
 for(const d of UORDER.concat(UF.range==='all'?[]:['range'])){
  const keep=UF[d];UF[d]=d==='range'?'all':'';
  const n=uFiltered().length;UF[d]=keep;
  if(!n)continue;
  return{why:d,
   text:'No rows match. It is the '+fName(d)+' filter ('+fVal(d)+') doing it: '+
     n+' row(s) match everything else.',
   fix:{key:d,label:d==='range'?'Show all time':'Remove the '+fName(d)+' filter',
     run:d==='range'?toAll:()=>setF(d,'')}};}
 return{why:'combination',
  text:'No rows match these filters, and no single one of them explains it — it '+
    'is the combination that selects nothing.'};}

// The from/to pair writes the SAME `UF.day` grammar the chart's click writes — one
// ISO day, or 'from..to' for a span — so a date typed here and a bin clicked there
// produce one filter, one chip and one way out. The pair also READS it, which is
// what keeps the two inputs showing the window a chart click just applied.
//
// Half a pair is completed from the LEDGER's own ends, never from today:
// "everything from 1 April" on a ledger that stopped in May means April to May, and
// completing it with the wall clock would silently widen the window past the data
// every day the project sits idle.
function uDayPair(){const[a,b]=(UF.day||'').split('..');return [a||'',b||a||''];}
function uSetDays(from,to){const C=USAGE.counts||{};
 const a=from||C.from||'',b=to||C.to||'';
 setF('day',(a||b)?(a===b?a:a+'..'+b):'');}

function uAgg(facts,key){const m=new Map();
 for(const f of facts){const k=f[F[key]]||'--';const s=m.get(k)||[0,0,0];
  s[0]+=f[F.tokens];s[1]+=f[F.cost];s[2]+=f[F.msgs];m.set(k,s);}
 return [...m.entries()].sort((a,b)=>b[1][0]-a[1][0]);}

