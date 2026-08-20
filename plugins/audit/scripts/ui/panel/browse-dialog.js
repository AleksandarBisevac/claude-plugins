// --- browse dialog ---------------------------------------------------------------
// The ranked list is a summary: the top 8 by spend. Paging it eight at a time to
// reach P219 among 241 is 27 clicks and still gives you no way to re-rank by cost.
// This is the other half - search and sort over the whole dimension - and it reads
// from the SAME filtered facts the bars do, so it can never disagree with the page
// behind it. A native <dialog> brings the focus trap, the backdrop and Esc for free.
/**
 * The one dialog element, built on first open and reused for the rest of the
 * session - a singleton, which is why its backdrop and close listeners are
 * wired once here rather than per opening.
 * @type {HTMLDialogElement|null}
 */
let BROWSE=null;
/**
 * The columns each dimension shows, as `[heading, key]` pairs: the heading is
 * words for the reader, the key is what a browseRows() row carries and what the
 * sort and the cell renderer both look up. A dimension with no entry falls back
 * to the model columns.
 * @type {Object<string, Array<[string, string]>>}
 */
// `models` is omitted for the model dimension, where it would restate the row.
const BCOL={
 phase:[['id','id'],['title','title'],['models','models'],['tokens','tokens'],
        ['share','share'],['cost','cost'],['messages','msgs']],
 // `cost` band only on tasks: the band is defined per task, and calling a phase
 // an outlier would be a different claim from the one that was computed.
 task:[['id','id'],['title','title'],['status','status'],['risk','risk'],
       ['models','models'],['cost band','band'],['tokens','tokens'],
       ['share','share'],['cost','cost'],['messages','msgs']],
 model:[['model','id'],['tokens','tokens'],['share','share'],['cost','cost'],
        ['messages','msgs']],
 author:[['author','id'],['models','models'],['tokens','tokens'],['share','share'],
         ['cost','cost'],['messages','msgs']]};
/**
 * Which row keys hold numbers. A numeric column right-aligns, sorts by
 * subtraction rather than by locale compare, and opens on its largest value
 * where a text column opens on its first.
 * @type {Object<string, number>}
 */
const BNUM={tokens:1,share:1,cost:1,msgs:1};

/**
 * One row per value of the dimension, carrying everything the dialog can show,
 * sort or search on.
 * @param {string} dim Field name to group by.
 * @param {UsageFact[]} facts The filtered rows the ranked bars were built from.
 * @returns {Array<{id: string, title: string, status: string, risk: string,
 *   band: string, models: Array<{model: string, tokens: number,
 *   pct: number|null}>, dominant: string, tokens: number, share: number|null,
 *   cost: number, msgs: number}>} Ordered by tokens, biggest first. Every text
 *   field is a string and never null, so a cell renders without a per-field
 *   absence check; `share` is the one that can be null, because a share of
 *   nothing has no value to print.
 */
function browseRows(dim,facts){
 const g=uAgg(facts,dim),grand=g.reduce((a,x)=>a+x[1][0],0);
 // Which models did this phase/task/person actually use? The aggregate throws
 // that away, and it is the question the ranked bar cannot answer: two phases
 // costing the same can be one opus run and one long haiku grind.
 const mix={};
 for(const f of facts){const k=f[F[dim]]||'--',m=f[F.model]||'unknown';
  (mix[k]=mix[k]||{})[m]=(mix[k][m]||0)+f[F.tokens];}
 return g.map(([k,v])=>{const meta=(USAGE.taskMeta||{})[k]||{};
  // Slot order, not token order: the palette was validated on THAT adjacency, so
  // drawing segments in any other sequence puts unvalidated pairs side by side.
  const per=mix[k]||{};
  const models=Object.keys(per).sort((a,b)=>(MSLOTS[a]||99)-(MSLOTS[b]||99))
    .map(m=>({model:m,tokens:per[m],pct:uShare(per[m],v[0])}));
  const top=[...models].sort((a,b)=>b.tokens-a.tokens)[0];
  return {id:k,
    title:isUncat(k)?UNCAT_WHY
      :dim==='phase'?((USAGE.phaseTitles||{})[k]||'')
      :dim==='task'?(meta.title||''):'',
    status:meta.status||'',risk:meta.risk||'',
    band:(dim==='task'?bandOf(k):null)||'',
    models:models,dominant:top?top.model:'',
    tokens:v[0],share:uShare(v[0],grand),cost:v[1],msgs:v[2]};});}

/**
 * The model-mix cell: a proportional stack of the models this row used, plus the
 * dominant one NAMED.
 *
 * Named because identity is never colour alone, and at this size the segments
 * are far too small to carry inline labels. The segment order is the one
 * browseRows() fixed - slot order, since the palette was validated on that
 * adjacency - so this must not re-sort them by size.
 * @param {{models: Array<{model: string, tokens: number, pct: number|null}>,
 *   dominant: string}} r One row from browseRows().
 * @returns {HTMLSpanElement} The cell, or a muted em dash when the row used no
 *   model at all.
 */
function modelCell(r){
 if(!r.models.length)return el('span',{class:'mut'},'—');
 const bar=el('span',{class:'mstack'});
 r.models.forEach(m=>bar.append(el('i',{style:'flex:'+Math.max(1,m.tokens)+' 0 0;'
   +'background:'+uMCol(m.model)})));
 const cell=el('span',{class:'mcell'},bar,
   el('span',{class:'mdom'},r.dominant.replace(/^claude-/,'')));
 cell.title=r.models.map(m=>m.model+'  '+uPct(m.pct)+'  '+uTok(m.tokens,2))
   .join('\n');
 return cell;}

/**
 * Open the browse dialog for one dimension.
 * @param {string} dim Field name being browsed; a row click filters on it.
 * @param {string} title Heading, the same words the ranked list that opened this
 *   was headed with.
 * @param {UsageFact[]} facts The filtered rows those bars were built from.
 * @returns {void} The dialog's own state - the search needle, the sort key and
 *   its direction - lives in this call's closure and nowhere else, so opening it
 *   again starts clean and closing it leaves nothing behind on the page.
 */
function openBrowse(dim,title,facts){
 if(!BROWSE){BROWSE=el('dialog',{class:'browse'});
  // Clicking the backdrop is the same intent as Esc. The dialog element itself
  // fills the viewport, so a click whose target IS the dialog landed outside the
  // panel it contains.
  BROWSE.addEventListener('click',ev=>{if(ev.target===BROWSE)BROWSE.close();});
  document.body.append(BROWSE);}
 const rows=browseRows(dim,facts),cols=BCOL[dim]||BCOL.model;
 let sort='tokens',desc=true,q='';
 const head=el('div',{class:'bhead'},
   el('h3',{},title+' — '+rows.length),
   el('button',{class:'bx',title:'close','aria-label':'close',
     onclick:()=>BROWSE.close()},'✕'));
 // "All phases" would be a lie while the page is scoped to one author.
 const within=UORDER.length
   ? el('div',{class:'mut small'},'within: '+UORDER.map(d=>fName(d)+' '+fVal(d))
       .join(' · '))
   : null;
 // State the thresholds, or state why there are none. Either way the reader can
 // check the classification rather than take it on faith.
 const bi=dim==='task'?uBandInfo():null;
 const bandNote=!bi?null:el('div',{class:'mut small'},bi.sufficient
   ? 'cost band: '+(bi.basis==='absolute'
       ? 'configured thresholds'
       : 'this project’s own completed tasks, median/p90')
     +' — typical ≤ '+uCost(bi.high)+' · high ≤ '+uCost(bi.outlier)
     +' · outlier above'
   : ['cost band: not shown — needs '+bi.gate+' completed tasks to calibrate, '
      +'there are '+bi.sample+'. ',
      settingsLink('Set absolute thresholds instead','usage.bands'),
      ' to band by a budget rather than by this project’s own history.']);
 // Not on the two tabs that were measured — this dialog is closed, so the probe
 // never saw it — but the same defect, and the same fix. The rest of the Usage
 // tab's boxes already carry a name; this one was the exception.
 const search=el('input',{type:'search',placeholder:'search '+dim+'…',
   'aria-label':'search '+dim+'s'});
 // An <input type=search> eats the FIRST Escape to clear itself, so the dialog
 // only closed on the second press - which reads as the key being broken. One
 // Escape, one effect: close.
 search.addEventListener('keydown',ev=>{
   if(ev.key==='Escape'){ev.preventDefault();BROWSE.close();}});
 const count=el('span',{class:'count'});
 const tb=el('tbody');
 const thead=el('thead');

 const draw=()=>{
  const needle=q.trim().toLowerCase();
  const shown=rows.filter(r=>!needle
    ||(r.id+' '+r.title).toLowerCase().includes(needle));
  // A mix has no natural order, so the models column sorts by its dominant model.
  shown.sort((a,b)=>{const k=sort==='models'?'dominant':sort;
    const A=a[k],B=b[k];
    const c=BNUM[sort]?A-B:String(A).localeCompare(String(B));
    return desc?-c:c;});
  count.textContent=shown.length+' of '+rows.length;
  thead.replaceChildren(el('tr',{},...cols.map(([lbl,key])=>
    el('th',{class:(BNUM[key]?'n ':'')+'pick'+(sort===key?' on':''),
      onclick:()=>{if(sort===key)desc=!desc;else{sort=key;desc=!!BNUM[key];}draw();}},
     lbl,sort===key?el('span',{class:'sarrow'},desc?'▼':'▲'):null))));
  tb.replaceChildren(...shown.map(r=>{
   const active=UF[dim]===r.id;
   return el('tr',{class:'pick'+(active?' on':''),
     title:active?'click to clear this filter':'click to filter to this '+dim,
     onclick:()=>{setF(dim,active?'':r.id);BROWSE.close();}},
    ...cols.map(([,key])=>el('td',
      {class:BNUM[key]?'n':(key==='title'?'t':''),
       title:key==='title'?String(r.title||''):null},
      key==='models'?modelCell(r)
      // A dot alone would be status-colour-as-meaning; the word carries it.
      :key==='band'?(r.band?el('span',{class:'bandpill b-'+r.band},r.band)
                           :el('span',{class:'mut'},'—'))
      :key==='tokens'?uTok(r.tokens,2)
      // NOT uPct here: across 241 phases every share is under 1%, and a column
      // where every cell reads "<1%" sorts fine and tells you nothing. This is
      // the precision surface, so it gets the digits.
      :key==='share'?(r.share==null?'—'
        :(r.share<1?r.share.toFixed(2):r.share.toFixed(1))+'%')
      :key==='cost'?uCost(r.cost)
      :key==='msgs'?r.msgs.toLocaleString()
      // The id column is where the empty bucket lands, so this is the cell
      // that has to name it rather than print the ledger's storage key.
      :key==='id'?uKeyEl(r.id)
      :String(r[key]||'—'))));}));
  if(!shown.length)tb.replaceChildren(el('tr',{},
    el('td',{colspan:String(cols.length),class:'mut'},
      'Nothing matches "'+q.trim()+'".')));};

 search.addEventListener('input',()=>{q=search.value;draw();});
 draw();
 // replaceChildren is the native DOM API, not el(): it STRINGIFIES anything that
 // is not a Node, so passing the null `within` painted the literal text "null"
 // above the dialog. Filter before handing it over.
 BROWSE.replaceChildren(...[head,within,bandNote,
   el('div',{class:'comptools'},search,count),
   el('div',{class:'btblwrap'},el('table',{class:'btbl'},thead,tb)),
   el('div',{class:'mut small bfoot'},
     'click a header to sort · click a row to filter')].filter(Boolean));
 // A row click applies the filter BEFORE closing, and that repaints this whole
 // tab — so by the time the dialog closes the button that opened it has already
 // been replaced. Hence the explicit selector: the node is never the answer here.
 dlgOpen(BROWSE,'#usage [data-browse="'+dim+'"]');
 search.focus();}

