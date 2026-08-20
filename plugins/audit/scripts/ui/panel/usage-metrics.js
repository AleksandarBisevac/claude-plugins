// --- sparklines ------------------------------------------------------------------
// A KPI tile is one number, and one number cannot say whether it is the top of a
// climb or the bottom of one. The spark is that shape and nothing else: no axis, no
// labels, no interaction — everything needed to read it precisely is in the chart
// directly below, and a tile that tried to be a chart would be a worse one.
//
// Drawn at its intrinsic pixel size, NOT stretched to the tile, for the reason the
// main chart is drawn 1:1: a viewBox scaled non-uniformly scales the strokes with
// it, and at this size a 1.4px line becoming 2px on the verticals is the whole
// drawing. It bins by the same ladder the chart uses (via uBin/binAt), so the tile
// and the chart under it can never be showing two different resolutions, and the
// period it settled on is named in the tile's own tooltip rather than left implied.
/**
 * The spark's intrinsic size in CSS pixels. It is drawn at exactly this size and
 * never stretched to the tile, which is what keeps its strokes at their declared
 * width.
 */
const SPW=76,SPH=20;
/**
 * The per-bin series behind the tile sparklines, binned by the same ladder the
 * chart uses so a tile and the chart under it can never show two resolutions.
 * @param {UsageFact[]} facts Rows the filter bar has already narrowed.
 * @returns {{period: string, series: {tokens: number[], cost: number[],
 *   msgs: number[], attributed: Array<number|null>}}} `period` is the bin width
 *   in words, which the tile's own tooltip reports. With no rows at all
 *   `series` is EMPTY rather than four arrays of zeros: uSpark() reads a missing
 *   key as "no series", which is what makes the tile say so instead of drawing a
 *   flat line through nothing.
 */
function uDaily(facts){
 const per=new Map();
 for(const f of facts){const d=f[F.ts].slice(0,10);
  const s=per.get(d)||[0,0,0,0];      // tokens, cost, msgs, unattributed tokens
  s[0]+=f[F.tokens];s[1]+=f[F.cost];s[2]+=f[F.msgs];
  if(f[F.attr]==='unattributed')s[3]+=f[F.tokens];
  per.set(d,s);}
 const ds=[...per.keys()].sort();
 if(!ds.length)return{period:'day',series:{}};
 const{size,bins}=uBin(ds),at=binAt(bins);
 const acc=bins.map(()=>[0,0,0,0]);
 for(const[d,s]of per){const i=at(d);for(let k=0;k<4;k++)acc[i][k]+=s[k];}
 return{period:size===1?'day':BINNAME[size],
   series:{tokens:acc.map(v=>v[0]),cost:acc.map(v=>v[1]),msgs:acc.map(v=>v[2]),
     // A bucket with no tokens has no coverage to report; carrying 0% would draw a
     // cliff to the floor on a quiet day and call it a collapse in attribution.
     attributed:acc.map(v=>v[0]?100*(v[0]-v[3])/v[0]:null)}};}

// `zero` is not decoration, it is the claim the drawing makes. A magnitude is
// measured from nothing, so its baseline is 0 and the area under it means the
// quantity. A SHARE is not: attribution moving 96% -> 99% against a 0..100 axis is
// three pixels of a solid block, which is a sparkline that says nothing while
// looking like it says something. A share is therefore scaled to its own range and
// drawn as a line alone — no area, because there is no zero for the area to be
// measured from, and a filled shape would invite exactly that reading.
/**
 * One sparkline: shape only - no axis, no labels, no interaction.
 * @param {Array<number|null>|undefined} vals One value per bin, oldest first.
 *   Nulls are GAPS and are dropped rather than plotted as zero.
 * @param {string} label Accessible name for the whole drawing.
 * @param {boolean} zero True for a magnitude, which is measured from 0 and gets
 *   a filled area under the line; false for a share, which is scaled to its own
 *   range and gets a line alone.
 * @returns {SVGSVGElement|null} null with fewer than two plottable points - one
 *   point is a claim about a trend from a single sample.
 */
function uSpark(vals,label,zero){
 // Two points make a line; one makes a claim about a trend from a single sample.
 // Nulls are gaps (a bucket with no tokens has no share to report) and are dropped
 // rather than plotted as zero, which would draw a cliff on a quiet day.
 const v=(vals||[]).filter(x=>x!=null);
 if(v.length<2)return null;
 const hi=Math.max(...v),lo=zero?Math.min(0,Math.min(...v)):Math.min(...v);
 const rng=(hi-lo)||1;
 const X=i=>SPW*i/(v.length-1),Y=x=>1.5+(SPH-3)*(1-(x-lo)/rng);
 const d=v.map((x,i)=>(i?'L':'M')+X(i).toFixed(1)+' '+Y(x).toFixed(1)).join('');
 const svg=svgEl('svg',{class:'uspark',width:SPW,height:SPH,
   viewBox:'0 0 '+SPW+' '+SPH,role:'img','aria-label':label});
 if(zero)svg.appendChild(svgEl('path',{class:'sa',
   d:d+'L'+SPW.toFixed(1)+' '+SPH+'L0 '+SPH+'Z'}));
 svg.appendChild(svgEl('path',{class:'sl',d:d}));
 svg.appendChild(svgEl('circle',{class:'sd',cx:SPW,cy:Y(v[v.length-1]).toFixed(1),
   r:1.7}));
 return svg;}

// --- metrics, all recomputed under the current filter --------------------------
/**
 * How much of the selection's spend is attributed, and to what.
 * @param {UsageFact[]} facts Rows the filter bar has already narrowed.
 * @returns {{attributed: number|null, task: number|null,
 *   by: Object<string, number>, tot: number}} `attributed` and `task` are
 *   percentages through uShare(), so both are null over an empty selection - a
 *   share of nothing is undefined, not 0% and certainly not 100%. `by` is tokens
 *   per attribution kind and `tot` the tokens they add up to.
 */
function uCoverage(facts){const by={},tot=facts.reduce((a,f)=>a+f[F.tokens],0);
 for(const f of facts)by[f[F.attr]]=(by[f[F.attr]]||0)+f[F.tokens];
 const un=by['unattributed']||0;
 return {attributed:uShare(tot-un,tot),task:uShare(by['task']||0,tot),by,tot};}
/**
 * Cost per completed task, and what the tasks still open would cost at that
 * rate.
 *
 * `remaining` is counted over the WHOLE plan rather than over the filtered rows:
 * a task that has not run yet has no rows to be filtered, so narrowing the view
 * must not make the work left to do shrink with it.
 * @param {UsageFact[]} facts Rows the filter bar has already narrowed.
 * @returns {{completed: number, remaining: number, gate: number,
 *   perTask: number|null, proj: {low: number, high: number}|null}} `perTask` is
 *   null with no completed task to average, and `proj` is null below `gate`
 *   samples - the caller prints the gate and the sample size rather than a
 *   forecast nobody should act on.
 */
function uUnit(facts){const M=USAGE.taskMeta||{},cost={};
 for(const f of facts){const t=f[F.task];if(t&&t!=='--')cost[t]=(cost[t]||0)+f[F.cost];}
 const done=Object.keys(cost).filter(t=>(M[t]||{}).status==='done').map(t=>cost[t]);
 const remaining=Object.keys(M).filter(t=>['pending','in_progress','blocked']
   .includes((M[t]||{}).status)).length;
 const out={completed:done.length,remaining,gate:5,perTask:null,proj:null};
 if(done.length)out.perTask=done.reduce((a,b)=>a+b,0)/done.length;
 // Same gate as the report: a forecast off too few samples is noise, so it is
 // suppressed rather than shown with false confidence. Branching on out.gate and
 // not on a second literal, because gate is the number the caller PRINTS - two
 // copies would let the message name a threshold the branch does not use.
 if(done.length>=out.gate){const s=[...done].sort((a,b)=>a-b),q=p=>s[Math.max(0,
   Math.min(s.length-1,Math.round(p*(s.length-1))))];
  out.proj={low:q(.25)*remaining,high:q(.75)*remaining};}
 return out;}
/**
 * What the selection spent on tasks that needed more than one attempt, and on
 * tasks that ended blocked.
 *
 * The same task can be in both sets, so `overlap` is reported rather than left
 * for a reader to assume the two figures are disjoint. `tot` is summed before
 * the plan lookup that can skip a row, so it counts every row - including spend
 * on a task the plan no longer knows about.
 * @param {UsageFact[]} facts Rows the filter bar has already narrowed.
 * @returns {{tot: number, re: number, bl: number, rn: number, bn: number,
 *   overlap: number}} Costs in USD (`tot`, `re`, `bl`) and task counts (`rn`
 *   retried, `bn` blocked, `overlap` in both).
 */
function uRetry(facts){const M=USAGE.taskMeta||{};let tot=0,re=0,bl=0;
 const rs=new Set(),bs=new Set();
 for(const f of facts){tot+=f[F.cost];const t=M[f[F.task]];if(!t)continue;
  if((t.attempts||1)>1){re+=f[F.cost];rs.add(f[F.task]);}
  if(t.status==='blocked'){bl+=f[F.cost];bs.add(f[F.task]);}}
 return {tot,re,bl,rn:rs.size,bn:bs.size,
   overlap:[...rs].filter(x=>bs.has(x)).length};}
/**
 * Cost per task and mean attempts, per model, WITHIN each risk band.
 *
 * Within a band on purpose: hard work is routed to the stronger model
 * deliberately, so comparing spend per task across bands would flag a working
 * system as a fault. Both figures are per DISTINCT task, so a task billed across
 * twenty hourly rows still counts once.
 * @param {UsageFact[]} facts Rows the filter bar has already narrowed.
 * @returns {Array<{risk: string, model: string, tasks: number,
 *   perTask: number, att: number}>} Ordered by risk band, then model name. A row
 *   whose task the plan does not know about is absent rather than unrated: there
 *   is no band to file it under, and inventing one would put it in a comparison
 *   it was never part of.
 */
function uRouting(facts){const M=USAGE.taskMeta||{},acc={};
 for(const f of facts){const t=M[f[F.task]];if(!t)continue;
  const risk=t.risk||'unrated',model=f[F.model];
  acc[risk]=acc[risk]||{};
  const c=acc[risk][model]=acc[risk][model]||{cost:0,tasks:new Set(),att:[]};
  c.cost+=f[F.cost];
  if(!c.tasks.has(f[F.task])){c.tasks.add(f[F.task]);c.att.push(t.attempts||1);}}
 const rows=[];
 for(const risk in acc)for(const model in acc[risk]){const c=acc[risk][model];
  rows.push({risk,model,tasks:c.tasks.size,perTask:c.cost/c.tasks.size,
    att:c.att.reduce((a,b)=>a+b,0)/c.att.length});}
 rows.sort((a,b)=>RISKS.indexOf(a.risk)-RISKS.indexOf(b.risk)||
   a.model.localeCompare(b.model));
 return rows;}
// vs the window immediately before this one, same length. Null when there is no
// prior period -- a first-run dashboard must not invent a trend.
//
// "All time" has no window, so it gets one: the last 30 days of the LEDGER against
// the 30 before them, anchored on the last day that has data rather than on the
// wall clock. Anchoring on today would make the default view of a ledger that
// stopped two months ago compare an empty window with an empty window and show no
// trend at all, forever — which is exactly the state a project is in when someone
// opens the panel to ask what it cost.
//
// Both date ranges travel with the number in `basis`, because "+18%" against an
// unnamed period is not a measurement.
/**
 * The tiles' trend: this window against the one immediately before it, of the
 * same length.
 * @param {UsageFact[]} facts Under a range preset, the rows already on screen;
 *   under "all time", the whole ledger, which this then slices itself.
 * @param {string[]} days Every ISO day in the selection, ascending. Only its
 *   last entry is read, and that is what anchors the all-time window on the
 *   LEDGER rather than on the clock.
 * @returns {{tokens: number|null, cost: number|null, msgs: number|null,
 *   attributed: number|null, label: string, basis: string}|null} null when
 *   either window is empty - a first-run dashboard must not invent a trend.
 *   `tokens`, `cost` and `msgs` are percentage CHANGES; `attributed` is a
 *   difference in percentage POINTS; `basis` names both date ranges, because a
 *   percentage against an unnamed period is not a measurement.
 */
function uDelta(facts,days){
 if(!days.length)return null;
 const all=UF.range==='all',span=all?30:parseInt(UF.range,10);
 const iso=n=>new Date(n*864e5).toISOString().slice(0,10);
 const anchor=all?days[days.length-1]:iso(Math.floor(Date.now()/864e5));
 // One boundary convention: the window is [cut, anchor], the one before it is
 // [prevCut, cut). Under a range preset `cut` is the same cut uFiltered() applies,
 // so the "now" side is exactly the rows the tiles are counting and `facts` can be
 // used as-is; under "all time" `facts` is the whole ledger and has to be sliced.
 const cut=iso(dnum(anchor)-span+(all?1:0)),prevCut=iso(dnum(cut)-span);
 const day=f=>f[F.ts].slice(0,10);
 const now=all?facts.filter(f=>day(f)>=cut):facts;
 const base=USAGE.facts.filter(f=>{const d=day(f);
  return d>=prevCut&&d<cut&&uMatch(f);});
 if(!base.length||!now.length)return null;
 const sum=a=>{let t=0,c=0,m=0,un=0;
  for(const f of a){t+=f[F.tokens];c+=f[F.cost];m+=f[F.msgs];
   if(f[F.attr]==='unattributed')un+=f[F.tokens];}
  return{tokens:t,cost:c,msgs:m,attributed:t?100*(t-un)/t:null};};
 const A=sum(now),B=sum(base);
 const pc=(x,y)=>y?100*(x-y)/y:null;
 return {tokens:pc(A.tokens,B.tokens),cost:pc(A.cost,B.cost),
         msgs:pc(A.msgs,B.msgs),
         // A share compared with a share is a difference in POINTS. 90% to 95% is
         // five points, and calling it +5.6% would be a third number nobody asked
         // for and the one a reader would misread as the coverage itself.
         attributed:(A.attributed==null||B.attributed==null)
           ?null:A.attributed-B.attributed,
         label:'vs prior '+span+'d',
         basis:(all?'the ledger’s last '+span+' days':'the last '+span+' days')
           +' ('+cut+' to '+anchor+') against '+prevCut+' to '+iso(dnum(cut)-1)};}

// --- CSV export ------------------------------------------------------------------
// The rows behind the view, as a file, because the questions a spreadsheet is for
// are not the questions a dashboard is for. Numbers go out RAW — no thousands
// separators, no currency symbol, no locale — since the receiver parses them:
// '3,230,000' lands in Excel as text and every sum over the column is then wrong
// and silently so. (The panel's own selftest scans for toLocaleString on the screen
// side for the same reason, one surface up.)
/**
 * The selection as CSV text.
 *
 * Quoting is RFC 4180 and nothing more: a field is wrapped in double quotes when
 * it holds a comma, a double quote, CR or LF, and inner quotes are doubled -
 * so surrounding spaces, an apostrophe and a semicolon all go out bare. Every
 * record ends with CRLF, the last one included. This is the second of the two
 * copies of that rule in the tree, report/exports.js holding the other, and
 * tools/ui-tests/csv-quote.test.mjs holds them equal field for field through
 * this function's real output rather than by reading the two side by side.
 * @param {UsageFact[]} facts Rows to write, in the order given.
 * @returns {string} A header row plus one record per fact. Numbers go out RAW -
 *   no separators, no currency, no locale - because "3,230,000" lands in a
 *   spreadsheet as text and every sum over the column is then wrong, silently.
 */
function uCsvText(facts){
 const head=['ts','phase','task','model','author','agent','attr','tokens',
   'costUSD','msgs'];
 // RFC 4180: quote anything containing a comma, a quote or a newline, and double
 // the quotes inside. A task title with a comma in it is not exotic.
 const q=v=>{const s=v==null?'':String(v);
  return /[",\r\n]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s;};
 const out=[head.join(',')];
 for(const f of facts)out.push([f[F.ts],f[F.phase],f[F.task],f[F.model],
   f[F.author],f[F.agent],f[F.attr],f[F.tokens],f[F.cost].toFixed(6),f[F.msgs]]
  .map(q).join(','));
 return out.join('\r\n')+'\r\n';}
/**
 * Write the selection to a CSV file the reader saves.
 * @param {UsageFact[]} facts Rows to export.
 * @returns {void} Reports through toast() in both directions: an empty selection
 *   says so instead of downloading a header with nothing under it, and a failure
 *   says so instead of being a button that did nothing.
 */
function uExport(facts){
 if(!facts.length){toast('nothing to export — no rows match these filters','err');
  return;}
 // The name says what the file IS. These are aggregated buckets, not raw ledger
 // lines, and at 20000 rows the server rolls them from hourly to daily — a file
 // called usage.csv on someone's disk three weeks later cannot be trusted to be
 // either. Span, resolution and whether a filter was applied all go in the name.
 const C=USAGE.counts||{};
 const name='usage-'+(C.from||'start')+'_'+(C.to||'end')+'-'
   +(USAGE.rolled?'daily':'hourly')+(uAnyFilter()?'-filtered':'')+'.csv';
 try{
  // U+FEFF: without a byte-order mark Excel reads a UTF-8 CSV in the local 8-bit
  // codepage and turns every non-ASCII author name into mojibake on open. Written
  // as an escape, never as the character itself — an invisible literal in the
  // source is unreviewable and ungreppable.
  const url=URL.createObjectURL(new Blob(['\ufeff'+uCsvText(facts)],
    {type:'text/csv;charset=utf-8'}));
  const a=el('a',{href:url,download:name});
  document.body.append(a);a.click();a.remove();
  // Revoked late, not immediately: some browsers have not started reading the blob
  // by the time click() returns, and a revoked URL there is a download that fails
  // with no error anywhere.
  setTimeout(()=>URL.revokeObjectURL(url),4000);
  toast(facts.length+' row(s) exported to '+name);
 }catch(e){toast('export failed: '+e,'err');}}

// --- render --------------------------------------------------------------------
/**
 * One ranked list: a heading, a bar row per value, and the controls that page or
 * browse the rest.
 * @param {UsageFact[]} facts Rows the filter bar has already narrowed.
 * @param {string} dim Field name to rank by, resolved through `F` by uAgg().
 * @param {string} title Heading text, reused as the browse dialog's own title so
 *   the dialog cannot be titled differently from the list that opened it.
 * @returns {Array<HTMLElement>} Nodes for the caller to append, and an EMPTY
 *   array when the dimension has no values at all - a heading with nothing under
 *   it reads as a broken card rather than an empty one.
 */
function uBars(facts,dim,title){
 const g=uAgg(facts,dim);if(!g.length)return[];
 const grand=g.reduce((a,x)=>a+x[1][0],0);
 const limit=SHOWN[dim]||TOP;
 const head=g.slice(0,limit),tail=g.slice(limit);
 const peak=Math.max(...head.map(x=>x[1][0]))||1;
 const out=[el('h2',{},title)];
 for(const[k,v]of head){
  const meta=USAGE.taskMeta[k]||{};
  const nm=isUncat(k)?label(UNCAT)
    :dim==='phase'?(k+' '+(USAGE.phaseTitles[k]||'')).trim()
    :(dim==='task'&&meta.title?(k+' '+meta.title):k);
  const active=UF[dim]===k;
  const row=el('div',{class:'urow pick'+(active?' on':''),
    onclick:()=>setF(dim,active?'':k)},
   el('span',{class:'unm'+(isUncat(k)?' uncat':''),
     title:isUncat(k)?UNCAT_WHY:null},nm),
   // Floor the width: a row that spent 0.08% of the peak rounds to 0.0% and
   // paints an empty track, which reads as "no data" rather than "a little".
   el('span',{class:'bar'},el('i',{style:'width:'+
     Math.max(v[0]?0.8:0,100*v[0]/peak).toFixed(1)+'%;'+
     'background:'+(dim==='model'?uMCol(k):'var(--bar-neutral)')})),
   el('span',{class:'uamt'},uTok(v[0])+(USAGE.showCost?' - '+uCost(v[1]):'')));
  bindTip(row,()=>[el('div',{class:'utip-h'},nm),
    tipRow(dim==='model'?uMCol(k):null,'tokens',uTok(v[0],2)),
    tipRow(null,'share',uPct(uShare(v[0],grand))),
    USAGE.showCost?tipRow(null,'cost',uCost(v[1])):null,
    tipRow(null,'messages',v[2].toLocaleString()),
    el('div',{class:'utip-f'},active?'click to clear this filter':'click to filter')
   ].filter(Boolean));
  out.push(row);}
 if(tail.length){
  const more=tail.reduce((a,x)=>[a[0]+x[1][0],a[1]+x[1][1]],[0,0]);
  out.push(el('div',{class:'urow pick tail',
    onclick:()=>{SHOWN[dim]=limit+TOP;renderUsage();}},
   el('span',{class:'unm mut'},'other ('+tail.length+') - show '+
     Math.min(TOP,tail.length)+' more'),
   el('span',{class:'bar'},el('i',{style:'width:'+(100*more[0]/peak).toFixed(1)+
     '%;background:var(--bar-neutral);opacity:.45'})),
   el('span',{class:'uamt'},uTok(more[0])+(USAGE.showCost?' - '+uCost(more[1]):''))));}
 // Expanding costs one click, so collapsing must too. This used to be an `else if`
 // on the tail being empty, which meant the way back only appeared after paging
 // through the whole list - thirty clicks at 233 rows. And paging is the wrong tool
 // for finding one row among hundreds, which is what `browse all` is for.
 const ctl=[];
 if(limit>TOP)ctl.push(el('button',{class:'lnk',
   onclick:()=>{SHOWN[dim]=TOP;renderUsage();}},'show top '+TOP+' only'));
 if(g.length>TOP)ctl.push(el('button',{class:'lnk',
   'data-browse':dim,
   onclick:()=>openBrowse(dim,title,facts)},'browse all '+g.length+' →'));
 if(ctl.length){
  const bar=el('div',{class:'uctl'});
  ctl.forEach((b,i)=>{if(i)bar.append(el('span',{class:'mut'},'·'));bar.append(b);});
  out.push(bar);}
 return out;}

