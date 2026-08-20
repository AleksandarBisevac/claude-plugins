// --- phase budgets ---------------------------------------------------------------
// Spend against the PLAN rather than the calendar. Rendered only when some phase
// declares a budgetUSD, so it costs nothing in the common case where nobody has.
//
// Unlike the bands, this DOES follow the filter: "what has P1 cost me" is a
// question about the rows you are looking at, and a budget row that ignored an
// author filter while the bar above it obeyed one would be two truths on one
// screen. The caption says which rows it counted.
/**
 * Spend against each phase's declared budget.
 * @param {UsageFact[]} facts Rows the filter bar has already narrowed.
 * @returns {Array<HTMLElement>} Nodes for the caller to append, empty when no
 *   phase declares a `budgetUSD` at all. A declared budget is always positive:
 *   the server treats 0, a negative and a non-number alike as "no budget" and
 *   never ships one, which is what makes the percentage here safe to divide.
 */
function uBudgets(facts){
 const B=USAGE.phaseBudgets||{};
 const ids=Object.keys(B);
 if(!ids.length)return [];
 const spent={};
 for(const f of facts){const p=f[F.phase]||'--';
  spent[p]=(spent[p]||0)+f[F.cost];}
 const rows=ids.map(id=>{const used=spent[id]||0,budget=B[id];
   return {id,budget,used,pct:100*used/budget,over:used>budget};})
  .sort((a,b)=>b.pct-a.pct);
 const out=[el('h2',{},'Budget')];
 if(UORDER.length)out.push(el('div',{class:'ucrumb mut'},
   'Counting only the rows the filters above leave in view.'));
 for(const r of rows){
  const nm=(r.id+' '+((USAGE.phaseTitles||{})[r.id]||'')).trim();
  out.push(el('div',{class:'bud'+(r.over?' over':'')},
   el('span',{class:'unm'},nm),
   // The fill stops at the track; the number beside it does not, so an overrun
   // is legible instead of being a bar that looks merely full.
   el('span',{class:'bar'},el('i',{style:'width:'+Math.min(100,r.pct).toFixed(1)+'%'})),
   el('span',{class:'bpct'},r.pct.toFixed(0)+'%'),
   el('span',{class:'uamt'},uCost(r.used)+' of '+uCost(r.budget)
     +(r.over?' · over':''))));}
 const tb=rows.reduce((a,r)=>a+r.budget,0),ts=rows.reduce((a,r)=>a+r.used,0);
 out.push(el('div',{class:'bud total'},
   el('span',{class:'unm mut'},'All budgeted phases'),
   el('span',{class:'bar'}),el('span',{class:'bpct'}),
   el('span',{class:'uamt'},uCost(ts)+' of '+uCost(tb))));
 const missing=Object.keys(USAGE.phaseTitles||{}).filter(p=>!(p in B)).length;
 if(missing)out.push(el('div',{class:'mut small'},
   plural(missing,'phase has','phases have')
   +' no budgetUSD set and are not listed - they are not phases at zero.'));
 return out;}

// --- monthly overview -------------------------------------------------------
// The 12-month card. One computation site (usage_ledger.monthly_activity)
// feeds the report table and the CLI; this is the panel's surface of the same
// numbers. The LEDGER half is recomputed here from the filtered facts, so it
// follows the filter bar like everything else on this tab; the PLAN half
// (tasks/bugs/merges) needs the manifest, arrives server-shipped as
// USAGE.monthlyPlan, and is project-wide - the crumb says so, the same way
// the routing advice names its scope. The month AXIS comes from the whole
// ledger plus the plan, never from the filtered rows: an axis that collapsed
// under the filter it feeds would drop the row that was just clicked, taking
// the way back out with it.
/**
 * The 12-month card: ledger columns beside plan columns.
 * @param {UsageFact[]} facts Rows the filter bar has already narrowed. The
 *   ledger half is recomputed from these; the plan half arrives server-shipped
 *   and is project-wide, which the crumb says out loud.
 * @returns {Array<HTMLElement>} Nodes for the caller to append, empty while the
 *   ledger spans a single month - one month would only restate the tiles. A
 *   month with no activity is still a row: the axis is walked from the first key
 *   to the last, so a quiet month reads as quiet instead of vanishing and
 *   closing the gap around itself.
 */
function uMonthly(facts){
 const allMonths=new Set(USAGE.facts.map(f=>f[F.ts].slice(0,7)));
 const plan=USAGE.monthlyPlan||{};
 if(allMonths.size<2)return[];  // one ledger month would restate the tiles
 const keys=[...new Set([...allMonths,...Object.keys(plan)])].sort();
 const months=[];
 let y=+keys[0].slice(0,4),m=+keys[0].slice(5,7);
 const ey=+keys[keys.length-1].slice(0,4),em=+keys[keys.length-1].slice(5,7);
 while(y<ey||(y===ey&&m<=em)){months.push(y+'-'+p2(m));m++;if(m>12){m=1;y++;}}
 const show=months.slice(-12);
 const led=new Map();
 for(const f of facts){const k=f[F.ts].slice(0,7);
  const s=led.get(k)||[0,0,0];s[0]+=f[F.tokens];s[1]+=f[F.cost];s[2]+=f[F.msgs];
  led.set(k,s);}
 const out=[el('h2',{},'Monthly')];
 out.push(el('div',{class:'ucrumb mut'},
   'Ledger columns follow the filters above. '
   +'Plan counts are project-wide - they do not follow the filters. '
   +'Click a month to scope the view to it.'));
 const heads=['month','tokens'].concat(USAGE.showCost?['cost']:[])
   .concat(['msgs','tasks done','bugs','fixed','merged']);
 const tbl=el('table',{class:'utbl','data-umonthly':'1'},
   tableHead(heads));
 const tb=el('tbody');
 for(const k of show){
  const s=led.get(k)||[0,0,0],p=plan[k]||{};
  const end=k+'-'+p2(new Date(Date.UTC(+k.slice(0,4),+k.slice(5,7),0)).getUTCDate());
  const range=k+'-01..'+end;
  const active=UF.day===range;
  const tr=el('tr',{class:'pick'+(active?' on':''),'data-um':k,
    title:active?'click to clear this month filter':'click to filter to '+k,
    onclick:()=>setF('day',active?'':range)},
   el('td',{class:'mono'},k),el('td',{},uTok(s[0])));
  if(USAGE.showCost)tr.append(el('td',{},uCost(s[1])));
  tr.append(el('td',{},s[2].toLocaleString()),
    el('td',{},String(p.tasksCompleted||0)),
    el('td',{},String(p.bugsReported||0)),
    el('td',{},String(p.bugsFixed||0)),
    el('td',{},String(p.phasesMerged||0)));
  tb.append(tr);}
 tbl.append(tb);
 // Scrolls inside its own frame on a phone - eight columns must never push
 // the document sideways (the mobile overflow check drives this for real).
 out.push(el('div',{class:'umwrap'},tbl));
 return out;}

// --- tokens heatmap -----------------------------------------------------------
// Day-of-week x hour, derived at render time from the HOURLY fact timestamps
// (ts is "YYYY-MM-DDTHH" until the server rolls a huge ledger up to daily —
// then there is no hour left to draw and the section stays away, the same
// silence the report keeps for a ledger with no hourly grid). Semantics
// inherit the report's activity heatmap: granularity all/year/month/week/day,
// prev/next strictly bounded by the data (disabled AND muted at an edge,
// stepping OVER gap days), and the period on display NAMED. The custom range
// is deliberately NOT a new control: uFiltered() has already applied UF.day
// and UF.range, so the panel's own day filter — the one that persists via
// localStorage and rides the #/<tab>!from=..&to=.. hash — IS the range, and
// the label reads "Custom range" while any of it is on. Granularity and
// anchor are session furniture like SHOWN: deliberately not persisted.
/**
 * The heatmap's own navigation state: `g` is the granularity ('all', 'year',
 * 'month', 'week' or 'day') and `a` is the ISO day the shown period starts on,
 * empty while `g` is 'all'. `a` is CLAMPED back into the current bounds on every
 * render, because a filter change can move the ledger out from under a period
 * that was picked against the old one.
 * @type {{g: string, a: string}}
 */
let UHM={g:'all',a:''};
/** @type {string[]} Row labels, Monday first, matching weekdayIndex()'s own ordering. */
const UHM_WD=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
/** @type {string[]} Month names for the period label, January at index 0. */
const UHM_MON=['January','February','March','April','May','June','July',
 'August','September','October','November','December'];
/**
 * The day-of-week by hour grid, derived at render time from the hourly fact
 * timestamps.
 * @param {UsageFact[]} facts Rows the filter bar has already narrowed.
 * @returns {Array<HTMLElement>} Nodes for the caller to append, and an EMPTY
 *   array in two cases that are not the same thing: the server has rolled the
 *   ledger to daily, so there is no hour left to file spend under; or nothing in
 *   the selection carries a usable hour. Both keep the same silence the report
 *   keeps for a ledger with no hourly grid.
 */
function uHeatmap(facts){
 if(USAGE.rolled)return[];
 const perDay=new Map();
 for(const f of facts){
  const d=f[F.ts].slice(0,10),h=+f[F.ts].slice(11,13);
  if(!(h>=0&&h<24))continue;              // daily row: no hour to file under
  const v=perDay.get(d)||new Array(24).fill(0);
  v[h]+=f[F.tokens];perDay.set(d,v);}
 if(!perDay.size)return[];
 const ds=[...perDay.keys()].sort();
 const b={lo:ds[0],hi:ds[ds.length-1]};
 // The calendar itself is in shared/calendar.js — the report's heatmap spelled
 // the same five functions under the same names inside its own closure. Only the
 // DATA half stays here: this surface holds its recorded days as a sorted array,
 // and a plain loop is what keeps seek's bounded walk from allocating per step.
 const hasData=(a,z)=>{for(const d of ds)if(d>=a&&d<=z)return true;return false;};
 const seek=(g,s,dir)=>seekPeriod(g,s,dir,b,hasData);
 // Clamp the anchor into the CURRENT bounds: a filter change can move the
 // universe out from under a period picked against the old one.
 if(UHM.g!=='all'){
  if(!UHM.a)UHM.a=periodStart(UHM.g,b.hi);
  if(periodEnd(UHM.g,UHM.a)<b.lo||UHM.a>b.hi)UHM.a=periodStart(UHM.g,b.hi);}
 const s=UHM.g==='all'?b.lo:UHM.a, en=UHM.g==='all'?b.hi:periodEnd(UHM.g,s);
 const lo=s<b.lo?b.lo:s, hi=en>b.hi?b.hi:en;
 // rows: day/week keep the calendar (one row per date); coarser grains
 // aggregate by weekday, like the report's all-data view.
 const rows=[];
 if(UHM.g==='day'){
  rows.push({label:UHM_WD[weekdayIndex(lo)]+' '+lo,
    cells:perDay.get(lo)||new Array(24).fill(0)});}
 else if(UHM.g==='week'){
  for(let n=dnum(s);n<=dnum(en);n++){const d=dayIso(n);
   rows.push({label:UHM_WD[weekdayIndex(d)]+' '+d.slice(5),head:UHM_WD[weekdayIndex(d)]+' '+d,
     cells:(d>=lo&&d<=hi)?(perDay.get(d)||new Array(24).fill(0)):null});}}
 else{
  const agg=[...Array(7)].map(()=>new Array(24).fill(0));
  for(const[d,v]of perDay){if(d<lo||d>hi)continue;
   const t=agg[weekdayIndex(d)];for(let h=0;h<24;h++)t[h]+=v[h];}
  for(let w=0;w<7;w++)rows.push({label:UHM_WD[w],cells:agg[w]});}
 let peak=0;rows.forEach(r=>(r.cells||[]).forEach(v=>{if(v>peak)peak=v;}));
 const label=UHM.g==='day'?UHM_WD[weekdayIndex(lo)]+' '+lo
  :UHM.g==='week'?'Week of '+s+' to '+periodEnd('week',s)
  :UHM.g==='month'?UHM_MON[+s.slice(5,7)-1]+' '+s.slice(0,4)
  :UHM.g==='year'?s.slice(0,4)
  :((UF.day||UF.range!=='all')?'Custom range':'All data')
    +' · '+b.lo+' to '+b.hi;
 const out=[el('h2',{},'When the tokens are spent (UTC)')];
 out.push(el('div',{class:'ucrumb mut'},
  'Follows the filters above - the date filter is the custom range. '
  +'Hours are UTC.'));
 const nav=el('div',{class:'uhmnav'});
 [['all','All'],['year','Year'],['month','Month'],['week','Week'],
  ['day','Day']].forEach(([g,l])=>{
  const on=UHM.g===g;
  nav.append(el('button',{class:'filt'+(on?' on':''),type:'button',
    'data-uhg':g,'aria-pressed':on?'true':'false',
    onclick:()=>{if(UHM.g!==g){UHM.g=g;UHM.a='';renderUsage();}}},l));});
 const canPrev=UHM.g!=='all'&&seek(UHM.g,s,-1)!==null;
 const canNext=UHM.g!=='all'&&seek(UHM.g,s,1)!==null;
 const arrow=(dir,glyph,ok)=>{
  const a=el('button',{class:'btn small uhmarrow',type:'button',
    'data-uhm':dir,'aria-label':(dir==='prev'?'Previous':'Next')+' period',
    onclick:()=>{const s2=seek(UHM.g,UHM.a||s,dir==='prev'?-1:1);
      if(s2){UHM.a=s2;renderUsage();}}},glyph);
  if(!ok)a.disabled=true;
  return a;};
 nav.append(arrow('prev','‹',canPrev),
  el('span',{class:'uhmperiod','data-uhmperiod':'1'},label),
  arrow('next','›',canNext));
 out.push(nav);
 const tbl=el('table',{class:'uhm','data-hmpeak':String(peak)});
 // The corner cell, then one per hour with a label every sixth.
 tbl.append(tableHead([{attrs:{class:'uhmc'}}].concat(
   Array.from({length:24},(_x,h)=>h%6===0?p2(h):''))));
 const tb=el('tbody');
 rows.forEach(r=>{
  const tr=el('tr',{},el('th',{},r.label));
  for(let h=0;h<24;h++){
   const v=r.cells?(r.cells[h]||0):0;
   const lv=(!v||!peak)?0:Math.min(6,1+Math.floor(5*v/peak));
   // A native title, the area-owner precedent: 168 cells x a bindTip pair
   // each would be listener spam for one hover at a time.
   tr.append(el('td',{},el('i',{'data-l':String(lv),
     title:r.cells?(r.head||r.label)+' '+p2(h)+':00 - '+uTok(v,2)+' tokens'
       :(r.head||r.label)+' - outside the selected range'})));}
  tb.append(tr);});
 tbl.append(tb);
 // Its own scroll frame: 24 columns must never push the document sideways
 // (the same rule .umwrap follows, driven for real by the mobile sweep).
 out.push(el('div',{class:'uhmwrap'},tbl));
 const key=el('div',{class:'uhmkey mut small'},'0 ');
 for(let l=0;l<=6;l++)key.append(el('i',{'data-l':String(l)}));
 key.append(' '+uTok(peak,1)+' tokens/hour');
 out.push(key);
 return out;}

// --- person header ----------------------------------------------------------
// NOT a new tab: UF.author already is the drill-down (the chart flips to
// models, every bar and budget follows the filter). This is the header for
// that state - who this is, their all-time footprint, and what they touched -
// recomputed inline from USAGE.facts on each render, zero new state.
// All-time on purpose: the tiles below already answer the filtered question,
// and a header that moved with the date range would only restate them.
/**
 * The header for the author drill-down: who this is, their all-time footprint,
 * and what they touched.
 * @returns {Array<HTMLElement>} Nodes for the caller to append, empty unless an
 *   author filter is on - and empty too when that author has no rows at all,
 *   which is what makes the empty state below the one thing that explains it.
 *   Everything here is recomputed from the whole ledger per render, so it holds
 *   no state of its own.
 */
function uPerson(){
 if(!UF.author)return[];
 const who=UF.author;
 const mine=USAGE.facts.filter(f=>f[F.author]===who);
 if(!mine.length)return[];
 let tok=0,cost=0,msgs=0,first='',last='';
 const models=new Map(),tasks=new Set(),phases=new Set();
 for(const f of mine){
  tok+=f[F.tokens];cost+=f[F.cost];msgs+=f[F.msgs];
  models.set(f[F.model],(models.get(f[F.model])||0)+f[F.tokens]);
  if(f[F.task]&&f[F.task]!=='--')tasks.add(f[F.task]);
  if(f[F.phase]&&f[F.phase]!=='--')phases.add(f[F.phase]);
  const d=f[F.ts].slice(0,10);
  if(!first||d<first)first=d;
  if(!last||d>last)last=d;}
 let allTok=0,allCost=0;
 for(const f of USAGE.facts){allTok+=f[F.tokens];allCost+=f[F.cost];}
 const me=((STATE||{}).viewer||{}).author===who;
 const h=el('h2',{'data-person':who},who);
 if(me)h.append(' ',el('span',{class:'badge'},'my spend'));
 const out=[h,el('div',{class:'ucrumb mut'},
   'All time, whole ledger - this header does not follow the filters; '
   +'the tiles and bars below do.')];
 const bits=[uTok(tok)+' tokens ('+uPct(uShare(tok,allTok))+' of the project)'];
 if(USAGE.showCost)bits.push(uCost(cost)+' of '+uCost(allCost));
 bits.push(msgs.toLocaleString()+' messages');
 bits.push(plural(phases.size,'phase')+' and '+plural(tasks.size,'task')
   +' touched');
 if(first)bits.push('active '+(first===last?first:first+' to '+last));
 const named=[...models.entries()].sort((a,b)=>b[1]-a[1]).map(e=>e[0]);
 bits.push('models: '+named.slice(0,3).join(', ')
   +(named.length>3?' +'+(named.length-3)+' more':''));
 out.push(el('div',{class:'ufact','data-ptasks':String(tasks.size),
   'data-pphases':String(phases.size),'data-pmsgs':String(msgs)},
   bits.join(' - ')));
 const M=USAGE.taskMeta||{},split={};
 for(const t of tasks){const st=(M[t]||{}).status||'untracked';
  split[st]=(split[st]||0)+1;}
 const order=['done','in_progress','blocked','pending','untracked'];
 const parts=order.filter(k=>split[k])
   .map(k=>split[k]+' '+k.replace('_',' '));
 if(parts.length)out.push(el('div',{class:'mut small'},
   'Their touched tasks: '+parts.join(' - ')+'.'));
 // Advisory ownership: the areas whose meta.areas owner IS this
 // person, joined against the VALUES of the server-shipped areaOwners map.
 // A label, not an assignment - the same claim the manifest makes, no more.
 const owned=Object.entries(USAGE.areaOwners||{})
   .filter(([,o])=>o===who).map(([t])=>t).sort();
 if(owned.length)out.push(el('div',{class:'mut small','data-owns':owned.join(',')},
   'owns: '+owned.join(', ')+' (advisory - meta.areas owner, not an assignee)'));
 return out;}

// --- cost bands ------------------------------------------------------------------
// The boundaries are NOT restated here: COST_BAND_PARAMS below is usage_ledger.py's
// own COST_BAND_PARAMS constant, JSON-dumped into the page at serve time by the
// substitution chain in panel-server.py. This function still mirrors the SHAPE of
// cost_bands() — same fallback order, same comparisons — but the gate and the
// percentile pair it reads cannot drift from Python: they ARE Python's values, not
// a copy typed a second time.
//
// Computed from the WHOLE ledger, never from the filtered view: a task is an
// outlier relative to the project, not relative to whatever slice you are looking
// at. Recalibrating per filter would make one of any three tasks an "outlier".
/**
 * The band boundaries as usage_ledger.py declares them, substituted into this
 * text at serve time. Read rather than restated: a gate and a percentile pair
 * typed a second time here would be free to drift from the Python that bands the
 * same tasks on every other surface.
 * @type {{gate: number, percentileHigh: number, percentileOutlier: number}}
 */
const COST_BAND_PARAMS=__COST_BAND_PARAMS__;
/**
 * `BAND_GATE` is how many completed tasks the relative basis needs before it
 * will band anything at all; `BAND_ORDER` is the bands from cheapest to
 * dearest, which is the order any list of them is shown in.
 */
const BAND_GATE=COST_BAND_PARAMS.gate, BAND_ORDER=['typical','high','outlier'];
/**
 * The computed bands, memoised for as long as this ledger is the current one,
 * and null before the first call.
 *
 * Cleared wherever USAGE is replaced - the out-of-band refresh and the poll that
 * found the file changed both do it - because a band is a statement ABOUT a
 * ledger, and a memo that outlived its ledger would go on labelling tasks from
 * one that is gone.
 * @type {{basis: string|null, sufficient: boolean,
 *   byTask: Object<string, string>, sample: number, gate: number,
 *   high: (number|undefined), outlier: (number|undefined),
 *   counts: (Object<string, number>|undefined)}|null}
 */
let BANDS=null;
/**
 * Which tasks are typical, high or outlier by cost, and on what basis.
 *
 * Computed from the WHOLE ledger and never from the filtered view: a task is an
 * outlier relative to the project, not relative to whatever slice is on screen.
 * Recalibrating per filter would make one of any three tasks an outlier.
 * @returns {{basis: string|null, sufficient: boolean,
 *   byTask: Object<string, string>, sample: number, gate: number}} `basis` is
 *   'absolute' for a configured threshold pair, 'relative' for percentiles over
 *   this project's own completed tasks, and null when neither was possible - in
 *   which case `sufficient` is false and `sample` and `gate` are what the caller
 *   prints instead of a classification no reader could check.
 */
function uBandInfo(){
 if(BANDS)return BANDS;
 const cfg=USAGE.bands||{},M=USAGE.taskMeta||{},cost={};
 for(const f of USAGE.facts){const t=f[F.task];
  if(t&&t!=='--'&&M[t])cost[t]=(cost[t]||0)+f[F.cost];}
 let hi=Number(cfg.highUSD),ou=Number(cfg.outlierUSD),basis='absolute',sample=0;
 if(!(isFinite(hi)&&isFinite(ou)&&hi>0&&hi<=ou)){
  const done=Object.keys(cost).filter(t=>(M[t]||{}).status==='done')
    .map(t=>cost[t]).sort((a,b)=>a-b);
  sample=done.length;
  if(done.length<BAND_GATE)
   return (BANDS={basis:null,sufficient:false,byTask:{},sample,gate:BAND_GATE});
  const pct=p=>done[Math.max(0,Math.min(done.length-1,
    Math.round(p/100*(done.length-1))))];
  hi=pct(COST_BAND_PARAMS.percentileHigh);ou=pct(COST_BAND_PARAMS.percentileOutlier);
  basis='relative';}
 const byTask={},counts={typical:0,high:0,outlier:0};
 for(const t in cost){const b=cost[t]>ou?'outlier':cost[t]>hi?'high':'typical';
  byTask[t]=b;counts[b]++;}
 return (BANDS={basis,sufficient:true,high:hi,outlier:ou,byTask,counts,sample,
   gate:BAND_GATE});}
/**
 * One task's cost band.
 * @param {string} id Task id.
 * @returns {string|null} A member of BAND_ORDER, or null both for a task with no
 *   recorded cost and for every task while the sample is below the gate. The
 *   caller draws an em dash either way, and says beside the table which of the
 *   two it is.
 */
function bandOf(id){const b=uBandInfo();
 return b.sufficient?(b.byTask[id]||null):null;}

