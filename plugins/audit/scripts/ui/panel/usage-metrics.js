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
const SPW=76,SPH=20;
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
function uCoverage(facts){const by={},tot=facts.reduce((a,f)=>a+f[F.tokens],0);
 for(const f of facts)by[f[F.attr]]=(by[f[F.attr]]||0)+f[F.tokens];
 const un=by['unattributed']||0;
 return {attributed:uShare(tot-un,tot),task:uShare(by['task']||0,tot),by,tot};}
function uUnit(facts){const M=USAGE.taskMeta||{},cost={};
 for(const f of facts){const t=f[F.task];if(t&&t!=='--')cost[t]=(cost[t]||0)+f[F.cost];}
 const done=Object.keys(cost).filter(t=>(M[t]||{}).status==='done').map(t=>cost[t]);
 const remaining=Object.keys(M).filter(t=>['pending','in_progress','blocked']
   .includes((M[t]||{}).status)).length;
 const out={completed:done.length,remaining,gate:5,perTask:null,proj:null};
 if(done.length)out.perTask=done.reduce((a,b)=>a+b,0)/done.length;
 // Same gate as the report: a forecast off fewer than 5 samples is noise, so it is
 // suppressed rather than shown with false confidence.
 if(done.length>=5){const s=[...done].sort((a,b)=>a-b),q=p=>s[Math.max(0,
   Math.min(s.length-1,Math.round(p*(s.length-1))))];
  out.proj={low:q(.25)*remaining,high:q(.75)*remaining};}
 return out;}
function uRetry(facts){const M=USAGE.taskMeta||{};let tot=0,re=0,bl=0;
 const rs=new Set(),bs=new Set();
 for(const f of facts){tot+=f[F.cost];const t=M[f[F.task]];if(!t)continue;
  if((t.attempts||1)>1){re+=f[F.cost];rs.add(f[F.task]);}
  if(t.status==='blocked'){bl+=f[F.cost];bs.add(f[F.task]);}}
 return {tot,re,bl,rn:rs.size,bn:bs.size,
   overlap:[...rs].filter(x=>bs.has(x)).length};}
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

