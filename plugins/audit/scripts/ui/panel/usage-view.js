// --- the Usage tab, assembled ---------------------------------------------------
/**
 * Rebuild the whole Usage tab from USAGE and the current filter state.
 *
 * One function for the whole tab, and that is a decision rather than drift: every
 * control here writes a filter, and every filter moves every number on the page,
 * so a partial repaint would leave a set of panels each answering a slightly
 * different question. Nothing on this tab caches a rendered number - the cards
 * below are all recomputed from the facts on each pass.
 *
 * Three things it must not do. It must not drop the caret: a repaint replaces
 * every control, including the search box being typed into and the browse button
 * the dialog just handed focus back to, so focus is captured before the teardown
 * and restored in `done()` - which is the only place the card is appended, on all
 * three exit paths, so an exit that skipped it would leave a blank tab. It must
 * not mutate a filter as a side effect of drawing; the single exception is the
 * bin select, which drops back to auto when the reader's saved choice would
 * exceed the chart's point cap, because the alternative is a control set to a
 * value the chart refuses to honour. And it must not compute a number a helper
 * already owns - the metrics, the series and the bands each have one home.
 * @returns {void}
 */
function renderUsage(){closeCombo();const c=$('#usage');
 persistUF();  // every filter change repaints this tab, so this one call is the
               // write-through for every path that can mutate a filter
 // Every filter change repaints this whole tab — and a filter change is exactly
 // what typing in the search box IS. Without this, the third letter of a five
 // letter search goes into a box that no longer exists, and the caret with it.
 const act=document.activeElement,keepQ=!!(act&&act.id==='uq'),
   caret=keepQ?act.selectionStart:0,
   // ...and the same for every control here that is not that box — the browse-all
   // buttons are replaced by this redraw too, and one of them is where closing
   // the browse dialog puts the caret.
   keepBack=keepQ?null:focusKeep('#usage');
 c.textContent='';tipHide();
 const card=el('div',{class:'card'});
 const done=()=>{c.append(card);
  if(keepQ){const n=$('#uq');if(n){n.focus();try{n.setSelectionRange(caret,caret);}catch(e){}}}
  else focusBack(keepBack);};
 // `USAGE.facts` and not just `USAGE`: `api()` returns `r.json()` whatever the
 // status, so a server error that is valid JSON arrives here as a truthy object
 // with no `facts` - and `USAGE.facts.length` threw, blanking the tab with a
 // console trace instead of saying anything.
 if(!USAGE||!Array.isArray(USAGE.facts)||!USAGE.facts.length){
  card.append(USAGE&&!USAGE.enabled
   ?el('div',{class:'mut'},'Token metering is off — ',
     settingsLink('turn it back on in Settings','usage.enabled'),'.')
   :el('div',{class:'mut'},'No usage recorded yet. Metering runs on the '
     +'Stop/SubagentStop hooks; "/audit:usage --backfill" reads transcripts already '
     +'on disk.'),
   el('div',{class:'mut',style:'margin-top:var(--sp-0)'},
     'ledger: '+((USAGE||{}).ledgerDir||'-'),' · ',
     settingsLink('change where it is written','usage.ledgerDir')));
  done();return;}

 // context line: the shape of the ledger, at zero card weight
 const K=USAGE.counts||{};
 const bits=[K.phases+' phases',K.authors+' people',K.models+' models',
   K.sessions+' sessions'];
 if(K.from)bits.push(K.from+' to '+K.to);
 // What the FACTS are bucketed at, which is not what the chart draws at — the
 // chart names its own period in its heading, so this says "ledger" out loud
 // rather than leaving two different resolutions on screen unlabelled.
 bits.push(USAGE.rolled?'daily ledger (rolled up)':'hourly ledger');
 // The rate table behind every dollar in this tab. `pricingAsOf` is served from the
 // MERGED config, so it is set even when this project never chose it — printing it
 // unconditionally would present the default table's date as the project's own.
 // `pricingAsOfDeclared` is the server saying which of the two it is.
 if(USAGE.showCost&&USAGE.pricingAsOfDeclared)bits.push('rates as of '+USAGE.pricingAsOf);
 const ctx=el('div',{class:'uctx'},bits.join(' - '));
 // This used to end the sentence with "set usage.pricingAsOf" — an instruction to
 // go and edit a file, printed on the surface built to edit that file. Now it is
 // the way there.
 if(USAGE.showCost&&!USAGE.pricingAsOfDeclared)ctx.append(' - ',
   settingsLink('rates undated: date them in Settings','usage.pricingAsOf'));
 card.append(ctx);

 // filters, on two rows: WHO and WHAT above, WHEN and the way out below.
 // Typeahead for the dimensions with hundreds of values, a plain select for the
 // two that have three — a select states its whole domain at a glance, which a
 // typeahead hides behind a keystroke, and hiding a two-value domain is silly.
 const uniq=dim=>[...new Set(USAGE.facts.map(f=>f[F[dim]]).filter(Boolean))].sort();
 const totalsFor=dim=>{const m=new Map();
  for(const f of USAGE.facts)m.set(f[F[dim]],(m.get(f[F[dim]])||0)+f[F.tokens]);
  return m;};
 const filt=el('div',{class:'ufil'});
 const r1=el('div',{class:'ufrow'}),r2=el('div',{class:'ufrow'});
 // Free text is the way in when you do not yet know which dimension the word you
 // remember belongs to. Debounced, because every change repaints the tab.
 const qIn=el('input',{type:'search',id:'uq',class:'usearch',value:UF.q,
   placeholder:'search rows — id, title, model, person, agent…',
   'aria-label':'search usage rows'});
 qIn.addEventListener('input',()=>{clearTimeout(UQT);
   UQT=setTimeout(()=>{if(qIn.value!==UF.q)setF('q',qIn.value);},220);});
 r1.append(qIn);
 // `task` joins the typeaheads: it was filterable by clicking a bar or a browse
 // row and by nothing you could type, which on 1000 tasks means it was filterable
 // only by the ones already in the top 8.
 ['model','author','phase','task'].forEach(dim=>{
  const all=uniq(dim),tot=totalsFor(dim);
  const inp=el('input',{type:'search',value:UF[dim],
    placeholder:'all '+dim+'s ('+all.length+')','aria-label':'filter by '+dim,
    onchange:e=>setF(dim,all.includes(e.target.value)?e.target.value:'')});
  r1.append(comboWrap(inp,()=>all.map(v=>({name:v,
    description:uTok(tot.get(v)||0)})),(name,close)=>{close();setF(dim,name);}));});
 // "My spend" — the author filter, pre-loaded with the name in the topbar. It is
 // the SAME string on both ends by construction: the server resolves it with
 // usage_ledger.resolve_author, which is the function that wrote the author column
 // on every row here. A toggle, not a jump: pressing it twice puts you back.
 const me=((STATE||{}).viewer||{}).author;
 if(me){
  const mine=USAGE.facts.filter(f=>f[F.author]===me).length,on=UF.author===me;
  // Rendered even when the count is zero, and saying so, because that is a fact
  // worth having: `usage.authorMode` may name you differently here (hash mode, a
  // repo-local user.email) and a chip that quietly disappeared would leave that
  // unanswerable. Pressing it lands on the empty state, which names the author
  // filter as the cause and offers to lift it.
  r1.append(el('button',{class:'filt'+(on?' on':''),type:'button','data-umine':'1',
    'aria-pressed':on?'true':'false',
    title:mine?('Scope to the '+plural(mine,'row')+' recorded for '+me)
      :('No rows are recorded for '+me+' in this ledger'),
    onclick:()=>setF('author',on?'':me)},'my spend'));}
 [['agent','all agents'],['attr','all attributions']].forEach(([dim,none])=>{
  const vals=uniq(dim);
  if(!vals.length)return;
  const sel=el('select',{'aria-label':'filter by '+fName(dim),'data-uf':dim,
    onchange:e=>setF(dim,e.target.value)});
  sel.append(el('option',{value:''},none+' ('+vals.length+')'));
  // The option VALUE stays the ledger's key (it is what setF filters on);
  // only the words a reader picks from are named.
  vals.forEach(v=>{const o=el('option',{value:v},uKey(v));
   if(UF[dim]===v)o.selected=true;sel.append(o);});
  r2.append(sel);});
 // Area - the plan's partition of the work, joined from row.phaseId at read time
 // (uAreas). Options are the tags that actually attribute spend in THIS ledger,
 // not the plan's whole registry: a tag whose phases have no rows would select
 // nothing and say nothing. Hidden when no tag reaches a row - a select whose
 // only option is 'untagged' partitions nothing. 'untagged' is offered exactly
 // when untagged spend exists (the ledger keeps an untagged bucket; hiding it
 // here would make the tagged shares add up to a lie).
 {const tags=new Set();let untagged=false;
  USAGE.facts.forEach(f=>{const a=uAreas(f);
   if(a)a.forEach(t=>tags.add(t));else untagged=true;});
  if(tags.size){
   const vals=[...tags].sort().concat(untagged?['untagged']:[]);
   const sel=el('select',{'aria-label':'filter by area','data-uf':'area',
     onchange:e=>setF('area',e.target.value)});
   sel.append(el('option',{value:''},'all areas ('+vals.length+')'));
   vals.forEach(v=>{const o=el('option',{value:v},v);
    // The advisory owner rides as a native tooltip - visible on hover,
    // silent for tags with no declared owner (and for 'untagged').
    const ow=(USAGE.areaOwners||{})[v];
    if(ow)o.title='owner: '+ow;
    if(UF.area===v)o.selected=true;sel.append(o);});
   r2.append(sel);}}
 // An absolute window, in the same UF.day grammar the chart's click writes.
 const dp=uDayPair();
 const mkDate=(which,val)=>el('input',{type:'date',value:val,
   'data-uf':which,'aria-label':which+' date',
   // The pickers open on the ledger, not on this century. Both ends are also
   // cross-constrained so the picker cannot offer a `to` before the `from`.
   min:which==='to'?(dp[0]||K.from||''):(K.from||''),
   max:which==='from'?(dp[1]||K.to||''):(K.to||''),
   onchange:e=>{const[a,b]=uDayPair();
     if(which==='from')uSetDays(e.target.value,b);else uSetDays(a,e.target.value);}});
 r2.append(el('span',{class:'udates'},
   el('span',{class:'filtlbl'},'from'),mkDate('from',dp[0]),
   el('span',{class:'filtlbl'},'to'),mkDate('to',dp[1])));
 r2.append(el('select',{'aria-label':'time range','data-uf':'range',
   onchange:e=>{UF.range=e.target.value;renderUsage();}},
  [['all','all time'],['7','last 7 days'],['30','last 30 days'],['90','last 90 days'],
   ['365','last 12 months']]
   .map(([v,l])=>el('option',Object.assign({value:v},v===UF.range?{selected:'selected'}:{}),l))));
 // Forced bin for the chart AND the tile sparklines - they share uBin, so one
 // control moves both and the two can never show different resolutions. Auto
 // follows the ladder; an option that would draw more than MAXPTS points is
 // disabled and its tooltip says why - the cap is the chart's own readability
 // bound, not a preference.
 {const ds=[...new Set(uFiltered().map(f=>f[F.ts].slice(0,10)))].sort();
  const span=ds.length>1?dnum(ds[ds.length-1])-dnum(ds[0])+1:ds.length;
  const pts={day:span,week:Math.ceil(span/7),
    month:ds.length>1?monthBins(ds).length:1};
  if(UF.bin!=='auto'&&pts[UF.bin]>MAXPTS)UF.bin='auto';
  const sel=el('select',{'aria-label':'chart bin','data-uf':'bin',
    onchange:e=>{UF.bin=e.target.value;renderUsage();}});
  [['auto','auto bin'],['day','by day'],['week','by week'],['month','by month']]
   .forEach(([v,l])=>{const o=el('option',{value:v},l);
    if(v!=='auto'&&pts[v]>MAXPTS){o.disabled=true;
     o.title='would draw '+pts[v]+' points; the chart caps at '+MAXPTS;}
    if(UF.bin===v)o.selected=true;sel.append(o);});
  r2.append(sel);}
 r2.append(el('button',{class:'btn small push',type:'button','data-ucsv':'1',
   title:'Download the rows behind this view as CSV — one row per bucket, phase, '
     +'task, model, person, agent and attribution, with the filters applied',
   onclick:()=>uExport(uFiltered())},'Export CSV'));
 filt.append(r1,r2);
 card.append(filt);

 // active-filter chips: what is scoping the view, and a way out of each
 if(uAnyFilter()){
  const chips=el('div',{class:'uchips'});
  UORDER.forEach(d=>chips.append(el('button',{class:'uchip',title:'remove this filter',
    'data-uchip':d,onclick:()=>setF(d,'')},el('span',{class:'ck'},fName(d)),
    fVal(d),el('span',{class:'cx'},'x'))));
  chips.append(el('button',{class:'lnk',onclick:clearAll},'clear all'));
  card.append(chips);}

 card.append(...uPerson());

 const facts=uFiltered();
 const days=[...new Set(facts.map(f=>f[F.ts].slice(0,10)))].sort();
 const tot=facts.reduce((a,f)=>[a[0]+f[F.tokens],a[1]+f[F.cost],a[2]+f[F.msgs]],[0,0,0]);
 const cov=uCoverage(facts),unit=uUnit(facts),rt=uRetry(facts);
 const dl=uDelta(facts,days);
 const sp=uDaily(facts);
 // A tile is three things: the number, how it moved against the window before, and
 // the shape it moved in. `pp` says the delta is a difference in percentage POINTS
 // rather than a percentage change; `pol` marks the one metric whose direction is
 // worth judging, so only that one is coloured.
 const tile=(k,v,o)=>{o=o||{};
  const d=o.delta==null?null:o.delta;
  const box=el('div',{class:'utile'},el('div',{class:'k'},k),
    el('div',{class:'v'},v,d==null?null:el('span',
      {class:'dl '+(d>=0?'up':'down')+(o.pol?(d>=0?' good':' bad'):''),
       'data-dl':o.key||'',title:dl.basis},
      (d>=0?'+':'')+d.toFixed(o.pp?1:0)+(o.pp?' pts':'%'))));
  const s=o.series?uSpark(o.series,k+' per '+sp.period+', oldest to newest',!o.pp)
    :null;
  box.append(s
    ? el('div',{class:'utrend',
        title:k+' per '+sp.period+(o.pp?', scaled to its own range — a share has no'
          +' zero to draw an area from':', from zero')},s)
    // Not a blank: a tile with no spark has a reason, and the reason is short
    // enough to carry. Dropping the row instead would also shorten the card and
    // pull the tile grid out of line.
    : el('div',{class:'utrend',title:o.why||'no daily series for this metric'},'—'));
  return box;};
 const tiles=[tile('tokens',uTok(tot[0]),
   {key:'tokens',delta:dl&&dl.tokens,series:sp.series.tokens})];
 if(USAGE.showCost)tiles.push(tile('equivalent cost',uCost(tot[1]),
   {key:'cost',delta:dl&&dl.cost,series:sp.series.cost}));
 tiles.push(tile('messages',tot[2].toLocaleString(),
   {key:'msgs',delta:dl&&dl.msgs,series:sp.series.msgs}));
 if(unit.perTask!=null)tiles.push(tile('cost per task',uCost(unit.perTask),
   {why:'no daily trend: a task’s cost accrues over every day it ran and is only '
     +'complete when the task is, so there is no per-day cost-per-task to plot'}));
 tiles.push(tile('attributed',uPct(cov.attributed),
   {key:'attributed',delta:dl&&dl.attributed,pp:true,pol:1,
    series:sp.series.attributed}));
 card.append(el('div',{class:'utiles'},tiles));
 // Said once, under the row, rather than five times on five chips — and the exact
 // pair of date ranges is on each chip's own tooltip.
 if(dl)card.append(el('div',{class:'ucrumb mut small'},
   'Trend is '+dl.label+': '+dl.basis+'.'));

 if(!facts.length){
  const why=uEmptyWhy();
  const acts=el('div',{class:'uempty'});
  if(why.fix)acts.append(el('button',{class:'btn small','data-ufix':why.fix.key,
    onclick:why.fix.run},why.fix.label));
  // Kept, and kept second: it is the way out when the diagnosis is "the
  // combination", and the one control a reader already knows from every other tab.
  acts.append(el('button',{class:'btn small','data-uclear':'1',
    onclick:clearAll},'Clear filters'));
  card.append(el('div',{class:'mut','data-uwhy':why.why},why.text),acts);
  done();return;}

 const dim=chartDim();
 // Slots are handed out to the entities actually drawn, so a hue is never shared.
 const sr=uSeries(facts,dim);
 const plotted=sr.entities.map(e=>e.key);
 MSLOTS=uSlots(F.model,dim==='model'?plotted
   :uAgg(facts,'model').slice(0,TOP).map(r=>r[0]),'name');
 USLOTS=dim==='model'?MSLOTS:uSlots(F.author,plotted,'spend');
 const per=sr.binSize===1?'day':BINNAME[sr.binSize];
 card.append(el('h2',{},'Tokens per '+per+' by '+dim));
 card.append(el('div',{class:'ucrumb mut'},(UF.author
   ?'Scoped to '+UF.author+' - lines are their models. Click a line to scope to one, or clear the author filter to compare people again.'
   :'Click a line to scope to that person, or anywhere else to scope to that '+per+'.')
   +(sr.binSize===1?'':' Days are rolled up into '+per+
     ' totals - '+sr.buckets.length+' points instead of '+
     'one per day, which at this span would draw noise.')));
 card.append(mountChart(sr,dim));
 card.append(el('div',{class:'ulegend'},sr.entities.map(e=>
   el('b',{class:(e.key==='other'?'':'pick')+(isUncat(e.key)?' uncat':''),
     title:isUncat(e.key)?UNCAT_WHY:null,
     onclick:()=>{if(e.key!=='other')setF(dim,UF[dim]===e.key?'':e.key);}},
    el('i',{style:'background:'+uCol(e.key)}),uKey(e.key)))));

 card.append(...uBars(facts,'phase','By phase'));
 card.append(...uBudgets(facts));
 card.append(...uBars(facts,'model','By model'));
 card.append(...uBars(facts,'author','By author'));
 card.append(...uBars(facts,'task','By task'));
 card.append(...uMonthly(facts));
 card.append(...uHeatmap(facts));

 // economics - the same honesty caveats the report carries
 card.append(el('h2',{},'Unit economics'));
 if(unit.proj)card.append(el('div',{class:'ufact'},'Remaining '
   +plural(unit.remaining,'task projects','tasks project')
   +' to '+uCost(unit.proj.low)+' to '+uCost(unit.proj.high)+
   ' at the p25-p75 per-task rate.'));
 else card.append(el('div',{class:'mut small'},'Projection needs '+unit.gate+
   ' completed tasks to mean anything; there are '+unit.completed+
   '. A forecast off a smaller sample would be noise.'));
 if(rt.tot)card.append(el('div',{class:'ufact'},uCost(rt.re)+' on tasks that needed '+
   'more than one attempt ('+plural(rt.rn,'task')+') - '+uCost(rt.bl)+
   ' on tasks that ended blocked ('+plural(rt.bn,'task')+').'),
  el('div',{class:'mut small'},'Retried spend is not wasted spend: the ledger '+
   'buckets by hour, not by attempt, so a task that retried and then landed did not '+
   'burn every attempt for nothing. Only the blocked figure is spend with no '+
   'outcome'+(rt.overlap?' (the same task is in both figures here)':'')+'.'));

 const rows=uRouting(facts);
 if(rows.length){card.append(el('h2',{},'Model cost within each risk band'),
  el('div',{class:'mut small'},'Compared inside a band on purpose: hard work is '+
   'routed to the stronger model deliberately, so a raw spend-per-task comparison '+
   'across bands would flag that working system as a fault.'));
  const tbl=el('table',{class:'utbl'},el('thead',{},el('tr',{},
    ['risk','model','tasks','cost/task','mean attempts'].map(h=>el('th',{},h)))));
  const tb=el('tbody',{});let last='';
  rows.forEach(r=>{tb.append(el('tr',{},el('td',{},r.risk===last?'':r.risk),
    el('td',{class:'mono'},r.model),el('td',{},String(r.tasks)),
    el('td',{},uCost(r.perTask)),el('td',{},r.att.toFixed(1))));last=r.risk;});
  // Framed like its monthly twin above. Unframed it was the panel's widest
  // offender: 332px intrinsic in a card with no scroll frame, so the DOCUMENT
  // scrolled sideways below 369px - 49px of it at 320px. The width ladder found
  // it; the old 320px assertion could not, because it only ever ran on `guards`.
  tbl.append(tb);card.append(el('div',{class:'umwrap'},tbl));}

 // The one recommendation in the tab. Computed server-side over the whole ledger
 // (see routingAdvice in usage_state), so it is a statement about the project and
 // says so whenever a filter is narrowing everything else on screen.
 const adv=USAGE.routingAdvice||[];
 if(adv.length){
  card.append(el('h2',{},'What the evidence supports'));
  if(UORDER.length)card.append(el('div',{class:'ucrumb mut'},
    'Across the whole ledger - this one does not follow the filters above.'));
  adv.forEach(a=>card.append(el('div',{class:'advice'},
    el('div',{},el('b',{},a.risk),' work is running on ',
      el('code',{},a.from),' - '+plural(a.tasks,'task')+' at '
      +(a.fromMeanAttempts||0).toFixed(1)+' mean attempts. Those same tokens cost '
      +uCost(a.atToRates)+' at ',el('code',{},a.to),' rates versus '
      +uCost(a.atFromRates)+', ',el('b',{},uCost(a.saving)+' less ('
      +a.savingPct.toFixed(0)+'%)'),'.'),
    el('div',{class:'mut small'},a.to+' has already run '
      +plural(a.evidenceTasks,'task')
      +' in this band here, at '+(a.evidenceAttempts||0).toFixed(1)
      +' mean attempts.'))));
  card.append(el('div',{class:'mut small'},
    'An upper bound, not a forecast: this re-prices the tokens that were actually '
    +'spent at the other model’s rates, and a different model would not emit '
    +'the same tokens. Both sides use today’s price table.'));}

 done();}

// --- Esc pops the last filter ---------------------------------------------------
// The fastest way back out of a scope you clicked into by accident. Bound on the
// document, so it has to stand aside for every other Esc consumer on the page --
// each guard below is one of them.
document.addEventListener('keydown',e=>{
 if(e.key!=='Escape'||$('#usage').classList.contains('hidden'))return;
 if(document.querySelector('.combo-menu:not(.hidden)'))return;
 // A dialog closes itself on Esc. Without this guard that same keypress would
 // ALSO drop a filter - one key, two effects, one of them invisible.
 if(document.querySelector('dialog[open]'))return;
 // An <input type=search> clears ITSELF on Escape, the same trap the browse
 // dialog hit. Left alone, one press would empty the box and pop an unrelated
 // filter; so from inside the box, Escape means "drop the search" and nothing
 // else, and the state follows the box rather than diverging from it.
 const a=document.activeElement;
 if(a&&a.id==='uq'){if(UF.q)setF('q','');return;}
 if(UORDER.length){setF(UORDER[UORDER.length-1],'');}
 else if(UF.range!=='all'){UF.range='all';renderUsage();}});
