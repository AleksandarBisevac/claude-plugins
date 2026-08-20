/**
 * One usage fact: a POSITIONAL array, never an object. `F` (declared in
 * usage-model.js) maps a field name to its index, so a field is read as
 * `f[F.tokens]` and never as `f.tokens`. The server ships its own `fields`
 * list beside `facts` in the same order; `F` is this end of that agreement,
 * and indexing with a bare literal breaks it silently.
 *
 * The slots, in order: 0 `ts`, 1 `phase`, 2 `task`, 3 `model`, 4 `author`,
 * 5 `agent`, 6 `attr`, 7 `tokens`, 8 `cost` in USD, 9 `msgs`. None of them is
 * ever absent: a row with no phase or task carries the string `--`, and one
 * with no attribution carries `unattributed`.
 *
 * `ts` is `YYYY-MM-DDTHH` until the ledger outgrows the server's row cap, at
 * which point it is rolled to `YYYY-MM-DD` and there is no hour left to read.
 * That is why every reader here slices the string rather than parsing it, and
 * why the heatmap asks `USAGE.rolled` before drawing an hour axis at all.
 *
 * The array is not frozen: uHay() caches a lowercase search haystack on it as
 * `.h`, so the search box does not rebuild one per keystroke across 20000 rows.
 * @typedef {Array<string|number>} UsageFact
 */
// --- shared tooltip -------------------------------------------------------------
// One element, moved on hover. Compact by design: enough to stop you estimating
// against an axis, short enough to read without moving your eyes.
/**
 * The tooltip element, or null until the first hover builds it.
 * @type {HTMLDivElement|null}
 */
let TIP=null;
/**
 * The tooltip element, created on first call.
 * @returns {HTMLDivElement} The one tip node. It hangs off `document.body` and
 *   not off the view that opened it, because every filter change tears this tab
 *   down and rebuilds it - a tip parented inside would go with it mid-hover.
 */
function tipEl(){if(!TIP){TIP=el('div',{class:'utip hidden'});document.body.append(TIP);}return TIP;}
/**
 * Show the tooltip with `nodes` as its content, placed beside the pointer.
 * @param {MouseEvent} ev Event whose client coordinates place the tip.
 * @param {Node|Array<Node>} nodes Rows to show; a single Node is accepted bare.
 *   Callers filter their own nulls out first - `append` stringifies anything
 *   that is not a Node, so a null row paints the word "null".
 * @returns {void}
 */
function tipShow(ev,nodes){const t=tipEl();t.textContent='';
 (Array.isArray(nodes)?nodes:[nodes]).forEach(n=>t.append(n));
 t.classList.remove('hidden');tipMove(ev);}
/**
 * Keep the tooltip beside the pointer and inside the viewport.
 *
 * A tip that would overflow is FLIPPED to the other side of the cursor, not just
 * pushed back inside: pushing it back parks it on the mark being pointed at,
 * which is the one thing the reader is trying to look at. The final clamp to the
 * top-left gutter is the last resort for a tip too big to fit either way.
 * @param {MouseEvent} ev Current pointer position.
 * @returns {void}
 */
function tipMove(ev){const t=tipEl(),pad=14,r=t.getBoundingClientRect();
 let x=ev.clientX+pad,y=ev.clientY+pad;
 if(x+r.width>innerWidth-8)x=ev.clientX-r.width-pad;
 if(y+r.height>innerHeight-8)y=ev.clientY-r.height-pad;
 t.style.left=Math.max(4,x)+'px';t.style.top=Math.max(4,y)+'px';}
/**
 * Hide the tooltip. Safe before anything has ever been shown: with no tip built
 * yet there is nothing to hide, and none is built just to hide it.
 * @returns {void}
 */
function tipHide(){if(TIP)TIP.classList.add('hidden');}
/**
 * One label/value line of a tooltip.
 * @param {string|null} colour CSS colour for the leading swatch, or null for
 *   none - a row about the whole selection has no series to swatch.
 * @param {string} label Field name, in the words the chips use.
 * @param {string} value Already-formatted value. Formatting stays with the
 *   caller, so one tooltip can mix tokens, a share and a cost.
 * @returns {HTMLDivElement}
 */
function tipRow(colour,label,value){return el('div',{class:'utip-r'},
 colour?el('i',{style:'background:'+colour}):null,
 el('span',{class:'utip-k'},label),el('span',{class:'utip-v'},value));}
/**
 * Give a node a hover tooltip.
 * @param {Element} node Element to bind.
 * @param {() => Node|Array<Node>} build Called on each mouseenter, never once
 *   at bind time: the numbers a tip shows are recomputed under the current
 *   filter, and a tip built at bind time would report the previous view's.
 * @returns {Element} `node`, so a caller can bind it inline while building it.
 */
function bindTip(node,build){
 node.addEventListener('mouseenter',e=>tipShow(e,build()));
 node.addEventListener('mousemove',tipMove);
 node.addEventListener('mouseleave',tipHide);
 return node;}

// --- multi-line chart with crosshair --------------------------------------------
// Eight series over nine months of daily points is spaghetti: 250 marks across
// 680px is 2.7px per day, so what the eye gets is noise with a trend hidden in it.
// Past MAXPTS the days roll up into natural bins - week, four weeks, quarter -
// chosen as the smallest that fits, and the chart SAYS which one it used. Binning
// silently would be worse than the spaghetti: the reader would take a weekly total
// for a daily one.
/**
 * One bin of the time axis: `[firstDay, lastDay]` as ISO days, both inclusive.
 * A single-day bin repeats the same day on both ends.
 * @typedef {[string, string]} BinSpan
 */

/**
 * One plotted line.
 * @typedef {Object} SeriesEntity
 * @property {string} key Dimension value, or 'other' for the rolled-up tail.
 * @property {number} total Tokens across every bin.
 * @property {number[]} values Tokens per bin - one entry per bin, zeros kept,
 *   so the index into this array is also the index into `UsageSeries.bins`.
 */

/**
 * Everything the chart, its legend and its crosshair read, computed once per
 * render.
 * @typedef {Object} UsageSeries
 * @property {string[]} buckets First day of each bin, for the axis labels.
 * @property {BinSpan[]} bins The bins themselves, for the tooltip heading and
 *   the day filter a click writes.
 * @property {number} binSize Days per bin, a LADDER rung; 28 means a CALENDAR
 *   month, whose bins are therefore variable width.
 * @property {SeriesEntity[]} entities Biggest first, with 'other' last.
 */

/**
 * `MAXPTS` is the most points this chart will draw before days roll up into
 * bins, and `LADDER` is the bin widths in days, smallest first - the rung
 * chosen is the first whose bin count fits. The cap is a readability bound and
 * not a preference, which is why the bin select DISABLES a rung that would
 * exceed it and says so on the option, rather than quietly ignoring the choice.
 */
const MAXPTS=60, LADDER=[1,7,28,91,364];
/**
 * What a bin width is CALLED, keyed by its LADDER rung. The chart names the
 * period it settled on: a reader who took a weekly total for a daily one would
 * be wrong by seven times with nothing on screen to notice it by.
 * @type {Object<number, string>}
 */
const BINNAME={1:'day',7:'week',28:'month',91:'quarter',364:'year'};
/**
 * An ISO day as a whole number of days since the epoch - the only form the bin
 * arithmetic uses. Adding 7 to a day number cannot land on an hour that does
 * not exist, which is what a local-time walk does across a DST edge.
 * @param {string} d ISO day; a longer timestamp is sliced by the caller.
 * @returns {number} Days since 1970-01-01, UTC.
 */
const dnum=d=>Date.UTC(+d.slice(0,4),+d.slice(5,7)-1,+d.slice(8,10))/864e5;
/**
 * Two-digit form, for assembling ISO days and hours by hand.
 * @param {number} n Value to pad; 10 and above come back unchanged, so this
 *   pads and never truncates.
 * @returns {string}
 */
const p2=n=>String(n).padStart(2,'0');
// The 28 rung is a CALENDAR month, not a fixed 28-day stride: a plain 30-day
// rung would be dead code (28 always fits first), and a "4 weeks" bucket never
// matches the month a reader is asking about. Bins are cut at month boundaries
// - variable width, clipped to the data span at both ends - so a bin's label
// says the month it is and a click filters to that month. binAt's binary
// search runs over [start,end] pairs and never assumed a fixed stride.
/**
 * The calendar-month bins covering `days`, clipped to the data at both ends.
 * @param {string[]} days Every ISO day with data, ascending, at least one.
 * @returns {BinSpan[]} One bin per month the data touches. The widths vary,
 *   which is why binAt() searches over start/end pairs instead of dividing by
 *   a stride.
 */
function monthBins(days){
 const last=days[days.length-1],bins=[];
 let y=+days[0].slice(0,4),m=+days[0].slice(5,7),start=days[0];
 for(;;){
  const eom=y+'-'+p2(m)+'-'+p2(new Date(Date.UTC(y,m,0)).getUTCDate());
  if(eom>=last){bins.push([start,last]);break;}
  bins.push([start,eom]);
  m++;if(m>12){m=1;y++;}
  start=y+'-'+p2(m)+'-01';}
 return bins;}
/**
 * Which rung to bin at, and the bins themselves.
 *
 * `UF.bin` forces a rung when the reader picked one; otherwise the smallest
 * rung whose bin count fits under MAXPTS wins. The month rung is then checked
 * against its REAL bin count rather than `ceil(span/28)`, because partial
 * months at both ends can put it one over.
 * @param {string[]} days Every ISO day with data, ascending.
 * @returns {{size: number, bins: BinSpan[]}} `size` is a LADDER rung. Fewer
 *   than two days gives one bin per day; no days at all gives no bins, which is
 *   what makes uChart() draw its no-data note instead of an empty axis.
 */
function uBin(days){
 if(days.length<2)return{size:1,bins:days.map(d=>[d,d])};
 const span=dnum(days[days.length-1])-dnum(days[0])+1;
 const forced={day:1,week:7,month:28}[UF.bin];
 let size=forced||LADDER.find(s=>Math.ceil(span/s)<=MAXPTS)||LADDER[LADDER.length-1];
 if(size===28){const bins=monthBins(days);
  // Partial months at both ends can put the count one past ceil(span/28); a
  // forced month keeps its bins, auto escalates to the quarter rung instead.
  if(forced||bins.length<=MAXPTS)return{size:28,bins:bins};
  size=91;}
 if(size===1)return{size:1,bins:days.map(d=>[d,d])};
 const start=dnum(days[0]),iso=n=>new Date(n*864e5).toISOString().slice(0,10);
 const bins=[];
 for(let a=0;a<span;a+=size)
  bins.push([iso(start+a),iso(start+Math.min(a+size,span)-1)]);
 return{size,bins};}
// Which bin a day falls in. Extracted because the sparklines bin the same days by
// the same ladder: two binary searches over one bin list is two chances for the
// chart and the tile above it to draw the same span at different resolutions.
/**
 * A day-to-bin lookup over one bin list.
 * @param {BinSpan[]} bins Ascending, and never empty at any call site - an
 *   empty list would answer 0 for every day asked about.
 * @returns {(day: string) => number} Index of the bin a day falls in. A day
 *   before the first bin answers 0 and one after the last answers the last
 *   index; every caller only ever asks about days the bins were built from.
 */
function binAt(bins){return d=>{const n=dnum(d);let lo=0,hi=bins.length-1;
  while(lo<hi){const mid=(lo+hi+1)>>1;dnum(bins[mid][0])<=n?lo=mid:hi=mid-1;}
  return lo;};}

/**
 * Roll facts up into the lines the chart draws.
 *
 * The tail past TOP is summed into a single 'other' entity rather than dropped,
 * so the lines still add up to the total the tiles above them show. It is
 * appended after the sort, which is what keeps it last in the legend and out of
 * the click-to-filter path - there is no single value 'other' could filter to.
 * @param {UsageFact[]} facts Rows the filter bar has already narrowed.
 * @param {string} dim Field NAME, resolved through `F` here. uSlots() takes the
 *   resolved INDEX instead, so the two are not interchangeable.
 * @returns {UsageSeries}
 */
function uSeries(facts,dim){const per=new Map(),days=new Set();
 for(const f of facts){const d=f[F.ts].slice(0,10),k=f[F[dim]]||'--';
  days.add(d);const m=per.get(k)||new Map();
  m.set(d,(m.get(d)||0)+f[F.tokens]);per.set(k,m);}
 const ds=[...days].sort(),{size,bins}=uBin(ds);
 const at=binAt(bins);
 const idx=new Map(ds.map(d=>[d,at(d)]));
 const roll=m=>{const v=new Array(bins.length).fill(0);
  for(const[d,n]of m)v[idx.get(d)]+=n;return v;};
 let ent=[...per.entries()].map(([k,m])=>({key:k,
   total:[...m.values()].reduce((a,b)=>a+b,0),values:roll(m)}))
  .sort((a,b)=>b.total-a.total);
 if(ent.length>TOP){const tail=ent.slice(TOP);ent=ent.slice(0,TOP);
  ent.push({key:'other',total:tail.reduce((a,e)=>a+e.total,0),
    values:bins.map((_,i)=>tail.reduce((a,e)=>a+e.values[i],0))});}
 return {buckets:bins.map(b=>b[0]),bins:bins,binSize:size,entities:ent};}
// A bin is one filter value: an exact day, or "from..to" for a rolled-up range.
/**
 * A bin as the value `UF.day` stores.
 * @param {BinSpan} b
 * @returns {string} One ISO day, or `from..to` - the same grammar the from/to
 *   date inputs read and write, so a click here and a date typed there produce
 *   one filter, one chip and one way out.
 */
const binKey=b=>b[0]===b[1]?b[0]:b[0]+'..'+b[1];
/**
 * A bin in a reader's words, for the tooltip heading.
 * @param {BinSpan} b
 * @returns {string} One ISO day, or 'first to last' for a rolled-up span.
 */
const binLabel=b=>b[0]===b[1]?b[0]:b[0]+' to '+b[1];
const NS='http://www.w3.org/2000/svg';
/**
 * Build one SVG element with attributes.
 *
 * Its own builder rather than the shared DOM one: an SVG element created in the
 * HTML namespace lays out and never paints, which is a blank chart with no
 * error anywhere. Attributes only, so a listener is added by the caller.
 * @param {string} t Local name, e.g. 'path'.
 * @param {Object<string, string|number>} a Attributes; each is written with
 *   setAttribute, so numbers are stringified by the DOM.
 * @returns {SVGElement}
 */
const svgEl=(t,a)=>{const e=document.createElementNS(NS,t);
 for(const k in a)e.setAttribute(k,a[k]);return e;};
// W comes from measuring the container, and the viewBox is built at that exact
// pixel size, so the scale is 1:1 in both axes. It used to be a fixed 680 stretched
// to fit with preserveAspectRatio="none" - which scales the coordinate system
// non-uniformly and therefore scales the GLYPHS: at 942px the axis labels rendered
// 38% too wide, the 2px lines drew 2.8px on vertical runs and 2px on horizontal
// ones, and the end-of-series circles were ellipses. Rendering 1:1 fixes all four
// at once, which no amount of tuning inside a stretched space can.
/**
 * The chart itself: one path per series, three gridlines, and a crosshair that
 * reports every series at the bucket under the cursor.
 *
 * Two click targets, kept distinct on purpose: a wide transparent companion
 * path scopes to ONE SERIES and stops the event there, while a click anywhere
 * else on the plot scopes to the BUCKET under the pointer. Collapsed into one,
 * "show me this person" and "show me this week" would be the same gesture.
 * @param {UsageSeries} sr Series to draw.
 * @param {string} dim Field name a series click filters on.
 * @param {number} W Width in CSS pixels, measured from the live container.
 * @returns {SVGSVGElement|HTMLDivElement} The chart, or a plain note when the
 *   series has no buckets at all.
 */
function uChart(sr,dim,W){
 const H=190,PL=44,PB=20,PT=10;
 if(!sr.buckets.length)return el('div',{class:'mut'},'No data in this window.');
 const peak=Math.max(1,...sr.entities.flatMap(e=>e.values));
 const n=sr.buckets.length, iw=W-PL-6, ih=H-PB-PT;
 const X=i=>PL+(n<2?iw/2:iw*i/(n-1)), Y=v=>PT+ih-ih*v/peak;
 const svg=svgEl('svg',{class:'uchart',viewBox:'0 0 '+W+' '+H,role:'img',
   'aria-label':'Tokens per '+(sr.binSize===1?'day':BINNAME[sr.binSize])
     +', peak '+uTok(peak)+'. Click to filter to one.'});
 [0,0.5,1].forEach(fr=>{const y=PT+ih*fr;
  svg.appendChild(svgEl('line',{class:'g',x1:PL,y1:y,x2:W,y2:y}));
  const t=svgEl('text',{class:'ax',x:0,y:y+3});t.textContent=uTok(peak*(1-fr));
  svg.appendChild(t);});
 const cross=svgEl('line',{class:'cross hidden',y1:PT,y2:PT+ih});
 svg.appendChild(cross);
 sr.entities.forEach(e=>{
  const d=e.values.map((v,i)=>(i?'L':'M')+X(i).toFixed(1)+' '+Y(v).toFixed(1)).join('');
  svg.appendChild(svgEl('path',{class:'ln',d:d,stroke:uCol(e.key)}));
  // A 2px line is a poor click target, and clicking a LINE (that series) has to stay
  // distinct from clicking the plot (that day). A wider transparent companion path
  // gives the series a comfortable hit area; the click stops there so it never also
  // registers as a day selection.
  if(e.key!=='other'){
   const hit=svgEl('path',{class:'lnhit',d:d});
   hit.addEventListener('click',ev=>{ev.stopPropagation();
     setF(dim,UF[dim]===e.key?'':e.key);});
   const ttl=svgEl('title',{});ttl.textContent='Click to scope to '+e.key;
   hit.appendChild(ttl);
   svg.appendChild(hit);}
  const li=e.values.length-1;
  svg.appendChild(svgEl('circle',{class:'dot',cx:X(li),cy:Y(e.values[li]),r:3.5,
    fill:uCol(e.key)}));});
 [0,n-1].forEach(i=>{if(n<2&&i)return;const t=svgEl('text',{class:'ax',x:X(i),y:H-4,
   'text-anchor':i?'end':'start'});t.textContent=sr.buckets[i].slice(5);
  svg.appendChild(t);});
 // Crosshair: nearest bucket to the cursor, one tooltip row per series.
 const idxAt=ev=>{const r=svg.getBoundingClientRect();
  const rel=(ev.clientX-r.left)/r.width*W;
  return Math.max(0,Math.min(n-1,Math.round((rel-PL)/(n<2?1:iw/(n-1)))));};
 svg.addEventListener('mousemove',ev=>{const i=idxAt(ev);
  cross.setAttribute('x1',X(i));cross.setAttribute('x2',X(i));
  cross.classList.remove('hidden');
  const rows=[el('div',{class:'utip-h'},binLabel(sr.bins[i]))];
  sr.entities.filter(e=>e.values[i]).sort((a,b)=>b.values[i]-a.values[i])
   .forEach(e=>rows.push(tipRow(uCol(e.key),uKey(e.key),uTok(e.values[i]))));
  if(rows.length===1)rows.push(el('div',{class:'utip-r mut'},'no usage'));
  rows.push(el('div',{class:'utip-f'},'click to filter to this '
    +(sr.binSize===1?'day':BINNAME[sr.binSize])));
  tipShow(ev,rows);});
 svg.addEventListener('mouseleave',()=>{cross.classList.add('hidden');tipHide();});
 svg.addEventListener('click',ev=>setF('day',binKey(sr.bins[idxAt(ev)])));
 svg.classList.add('pick');
 return svg;}

// The chart is built at the container's true pixel width, and the container is not
// in the DOM while renderUsage() is assembling the card - so the first measurement
// can be 0. Draw once, measure again on the next frame, and re-draw on resize. The
// width guard makes every one of those a no-op unless the width actually moved.
/**
 * A container that draws the chart at its own measured width, and redraws it
 * when that width changes.
 * @param {UsageSeries} sr Series to draw.
 * @param {string} dim Field name a series click filters on.
 * @returns {HTMLDivElement} The container, still empty until the next frame.
 *   The width it caches on itself is what makes the first frame and every
 *   resize a no-op unless the width actually moved.
 */
function mountChart(sr,dim){
 const host=el('div',{class:'chartslot'});
 const draw=()=>{const w=Math.round(host.clientWidth);
  if(!w||w===host.__w)return;
  host.__w=w;host.replaceChildren(uChart(sr,dim,w));};
 requestAnimationFrame(()=>{draw();
  if(window.ResizeObserver&&!host.__ro){
   host.__ro=new ResizeObserver(()=>draw());host.__ro.observe(host);}});
 return host;}

