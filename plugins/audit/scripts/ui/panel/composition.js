// ---------- Composition ----------
// ---------- model suggestions (mc) ----------
// One union, three sources, each named: the models the MANIFEST already routes
// to, the ids the RATE TABLE prices, and what the LEDGER has actually metered.
// The badge is the point — a model only one source spells is usually one slip
// from its cousins, and the validator cannot arbitrate that (it is an offline
// shape-checker with no ledger and no config), so the cross-source view lives
// here. A name in several sources keeps its most local badge: manifest first,
// then rates, then ledger.
let MITEMS=null;
function modelItems(){
 if(MITEMS)return MITEMS;
 const out=new Map();
 const add=(name,source,description)=>{
  if(name&&!out.has(name))out.set(name,{name,source,description});};
 const comp=(STATE&&STATE.composition)||{phases:[],tasks:[]};
 const useT={},useP={};
 (comp.tasks||[]).forEach(t=>{if(t.model)useT[t.model]=(useT[t.model]||0)+1;});
 (comp.phases||[]).forEach(p=>{if(p.reviewModel)useP[p.reviewModel]=(useP[p.reviewModel]||0)+1;});
 [...new Set([...Object.keys(useT),...Object.keys(useP)])].sort().forEach(m=>{
  const bits=[];
  if(useT[m])bits.push(useT[m]+' task(s)');
  if(useP[m])bits.push(useP[m]+' review(s)');
  add(m,'manifest','used by '+bits.join(', '));});
 const rates=Object.assign({},(((STATE||{}).defaults||{}).usage||{}).pricing||{},
   (((STATE||{}).config||{}).usage||{}).pricing||{});
 Object.keys(rates).sort().forEach(m=>{
  if(m==='_default')return;
  const r=rates[m]||{};
  add(m,'rates','$'+(r.in??'?')+' in / $'+(r.out??'?')+' out per MTok');});
 if(USAGE&&USAGE.facts&&USAGE.facts.length){
  const tot=new Map();
  for(const f of USAGE.facts)tot.set(f[F.model],(tot.get(f[F.model])||0)+f[F.tokens]);
  [...tot.keys()].sort().forEach(m=>{
   if(m)add(m,'ledger',uTok(tot.get(m))+' tokens in this ledger');});}
 return (MITEMS=[...out.values()]);}
// One slip apart: case-insensitively equal but spelled differently, or one
// substitution / insertion / deletion / adjacent transposition away — the same
// four typo shapes validate-manifest's md warning reads, spelled here a second
// time only because this half runs in a browser and that one runs offline.
function mdNear(a,b){if(a===b)return false;
 const x=a.toLowerCase(),y=b.toLowerCase();
 if(x===y)return true;
 if(Math.abs(x.length-y.length)>1)return false;
 if(x.length===y.length){const d=[];
  for(let i=0;i<x.length;i++)if(x[i]!==y[i])d.push(i);
  if(d.length===1)return true;
  return d.length===2&&d[1]===d[0]+1&&x[d[0]]===y[d[1]]&&x[d[1]]===y[d[0]];}
 const s=x.length<y.length?x:y,l=x.length<y.length?y:x;
 let i=0,j=0,used=false;
 while(i<s.length){if(s[i]===l[j]){i++;j++;continue;}
  if(used)return false;used=true;j++;}
 return true;}
// The three-source half of the typo check: a model the manifest spells that NO
// other source knows, one slip from a name the rates or the ledger do know.
// Non-blocking by design — the panel cannot know which spelling is intended,
// only that two sources disagree by one slip.
function modelHints(){
 const manifest=new Set(),other=new Set();
 const comp=(STATE&&STATE.composition)||{phases:[],tasks:[]};
 (comp.tasks||[]).forEach(t=>{if(t.model)manifest.add(t.model);});
 (comp.phases||[]).forEach(p=>{if(p.reviewModel)manifest.add(p.reviewModel);});
 const rates=Object.assign({},(((STATE||{}).defaults||{}).usage||{}).pricing||{},
   (((STATE||{}).config||{}).usage||{}).pricing||{});
 Object.keys(rates).forEach(m=>{if(m!=='_default')other.add(m);});
 if(USAGE&&USAGE.facts)USAGE.facts.forEach(f=>{if(f[F.model])other.add(f[F.model]);});
 const out=[];
 [...manifest].sort().forEach(m=>{
  if(other.has(m))return;              // spelled the same somewhere real
  const near=[...other].filter(o=>mdNear(m,o)).sort();
  if(near.length)out.push({model:m,near:near[0]});});
 return out;}
// The inventory half of the skills story (v0.37 B3): a name the manifest
// spells — in task.skills or in an area's defaults (comp.areaSkills, shipped
// by _composition_view) — that the DISCOVERY scan does not know. modelHints'
// shape on purpose: same .mut note, same cap, a hint and never a gate. No
// near-miss requirement here — the validator already runs the intra-manifest
// typo check offline; what only the panel can see is the inventory. Silent
// when discovery found nothing at all: against an empty inventory every name
// would read "unknown", and the note would be noise about the scan, not the
// manifest.
function skillHints(){
 if(!REG.skills||!REG.skills.length)return[];
 const known=new Set(REG.skills.map(s=>s.name));
 const comp=(STATE&&STATE.composition)||{tasks:[]};
 const spelled=new Set();
 (comp.tasks||[]).forEach(t=>{(Array.isArray(t.skills)?t.skills:[]).forEach(s=>spelled.add(s));});
 (comp.areaSkills||[]).forEach(s=>spelled.add(s));
 return [...spelled].sort().filter(n=>!known.has(n));}
function skillPicker(current,onChange,ariaName){
 const inp=el('input',{value:current??'',placeholder:'search a skill…  (empty = none)',
   'aria-label':ariaName||'search a skill'});
 inp.addEventListener('input',()=>onChange(inp.value.trim()||null));
 return comboWrap(inp,()=>REG.skills,(name,close)=>{inp.value=name;onChange(name);close();});}
// Three states in one control (v0.37 B1): a list of chips, an EMPTY row (with
// the "none applies" affordance that writes the explicit null), and the
// opted-out state itself — a muted chip saying so, never an empty row that
// looks unconsidered. Adding a skill from the opted-out state replaces the
// null (changed my mind); the × on the opt-out chip clears it back to [].
function skillChips(getArr,setArr,ariaName){
 const box=el('div',{class:'chipwrap'}),chips=el('div',{class:'chips'});
 const inp=el('input',{placeholder:'search a skill to add…',
   'aria-label':ariaName||'add a skill'});
 const draw=()=>{chips.textContent='';const cur=getArr();
   if(cur===null){chips.append(el('span',{class:'chip optout'},'none — opted out',
     el('button',{title:'clear the opt-out (back to unconsidered)',
       onmousedown:e=>{e.preventDefault();setArr([]);draw();}},'×')));
    return;}
   (cur||[]).forEach((v,i)=>chips.append(
    el('span',{class:'chip'},v,el('button',{onmousedown:e=>{e.preventDefault();const a=getArr().slice();a.splice(i,1);setArr(a);draw();}},'×'))));
   if(!(cur||[]).length)chips.append(el('button',{class:'chip ghosted optnone',type:'button',
     title:'write skills: null — "no skills apply here" is an answer, and it also stops the area default',
     onmousedown:e=>{e.preventDefault();setArr(null);draw();}},'none applies'));};
 const add=(name,close)=>{const n=(name||'').trim();
   if(n){const a=(getArr()||[]).slice();if(!a.includes(n)){a.push(n);setArr(a);draw();}}
   inp.value='';if(close)close();};
 const combo=comboWrap(inp,()=>REG.skills.filter(s=>!(getArr()||[]).includes(s.name)),add,add);
 draw();box.append(chips,combo);return box;}
// Composition's filter state lives OUT here, not in renderComp's closure. Two
// reasons, and the second is the one that made it necessary: a re-render (after a
// save, or a poll) used to drop you back to the unfiltered table, and Overview
// needs to hand this tab a phase to open. `apply` is published by renderComp so a
// caller can change the state without re-rendering — re-rendering would throw away
// whatever is half-typed in the composition form, which is the same mistake the
// run-status poll was fixed for.
const COMPF={q:'',status:'',needs:false,open:{},apply:null};
function openInComp(pid){COMPF.q=pid;COMPF.status='';COMPF.needs=false;COMPF.open[pid]=true;
 if(COMPF.apply)COMPF.apply();showTab('comp');}
function renderComp(){closeCombo();
 // Rebuilt from FOUR places, which is one more than any other view: its own Save,
 // its Discard, the ADO card's Save and Discard, and the 5s disk poll. MEASURED:
 // after a confirmed Save the dialog handed the caret back to the Save button at
 // 676ms and this function took it away again at 682ms — six milliseconds, and no
 // poll involved, which is how this view differs from #policy. The caret in the
 // filter box was lost the same way on a refreshFromDisk, offset and all.
 const keepBack=focusKeep('#comp');
 const c=$('#comp');c.textContent='';const comp=STATE.composition;
 MITEMS=null;   // STATE may have moved under us (save re-render, disk refresh)
 const patch={meta:{},phases:{},tasks:{}};
 const meta=el('div',{class:'card'});meta.append(h2h('Phase sign-off review skill (meta.reviewSkill)',MDESC.reviewSkill,
   {comp:'reviewSkill',label:'Phase sign-off review skill'}));
 meta.append(el('div',{class:'row'},skillPicker(comp.meta.reviewSkill,
   v=>patch.meta.reviewSkill=v,'Phase sign-off review skill')));
 meta.append(h2h('meta.buildCommands (JSON)',MDESC.buildCommands,
   {comp:'buildCommands',label:'Build commands'}));
 // It had no accessible name at all — not even a placeholder to fall back on —
 // which is SC 4.1.2 as well as SC 3.3.2. Named from its own <h2>.
 const bc=el('textarea',{'aria-label':'meta.buildCommands (JSON)'});
 bc.value=comp.meta.buildCommands?JSON.stringify(comp.meta.buildCommands,null,2):'';
 let bcBad=false;
 bc.oninput=()=>{try{patch.meta.buildCommands=bc.value.trim()?JSON.parse(bc.value):null;
   bcBad=false;bc.style.borderColor='';}
  catch(e){bcBad=true;bc.style.borderColor='var(--err)';}};
 meta.append(bc);c.append(meta);
 // tasks: filter toolbar + ONE compact collapsible table (scales to 50x20)
 const tcard=el('div',{class:'card'});tcard.append(h2h('Composition — phases · tasks · skills',MDESC.taskSkills,
   {comp:'taskSkills',label:'Task skills'}));
 // The toolbar and the two editable columns carry hand-back hooks, because this
 // view has no ids of its own and focusSel can only name an element by an id or a
 // data- attribute. `data-status` alone would not do for the filter buttons: inside
 // #comp it also sits on every phase row, every task row and every status pill, so
 // it names four hundred elements and focusBack correctly refuses to guess.
 const q=el('input',{type:'search',id:'compq',placeholder:'filter phases & tasks…',
   'aria-label':'filter phases & tasks',value:COMPF.q});
 const statusBar=el('span',{class:'filtset',style:'display:inline-flex;gap:.3rem;flex-wrap:wrap'});
 const needsBtn=el('button',{class:'filt',type:'button','data-compneeds':'1','aria-pressed':'false',title:'only tasks with no skills yet — an explicit "none applies" (null) is an answer, not a need'},'needs skills');
 const expandBtn=el('button',{class:'btn small',type:'button','data-compexpand':'1'},'expand all');
 const count=el('span',{class:'count',style:'margin-left:auto'});
 tcard.append(el('div',{class:'comptools'},q,el('span',{class:'filtlbl'},'phase:'),statusBar,needsBtn,expandBtn,count));
 // mc: the three-source near-miss hint (see modelHints). A note, not a gate.
 modelHints().slice(0,3).forEach(h=>tcard.append(
  el('div',{class:'mut small','data-mdhint':h.model},
   'model "'+h.model+'" is spelled only in this manifest; the rate table / '
   +'ledger know "'+h.near+'" — one slip apart. A hint, not a gate: if "'
   +h.model+'" is intended, it meters at _default rates until it is priced.')));
 // sk: the inventory hint for skills (see skillHints). A note, not a gate.
 skillHints().slice(0,3).forEach(n=>tcard.append(
  el('div',{class:'mut small','data-skhint':n},
   'skill "'+n+'" is spelled only in this manifest; discovery knows no such '
   +'skill — a hint, not a gate: a name that never resolves simply loads nothing.')));
 const tbody=el('tbody');
 tcard.append(el('div',{class:'comptblwrap'},el('table',{class:'comp'},
   // The two editable columns carry the reference for the whole column. A ⓘ per
   // row would be a thousand of them saying one thing.
   el('thead',{},el('tr',{},el('th',{},'id'),el('th',{},'title'),el('th',{},'status'),
     el('th',{},flabel('model',MDESC.taskModel,{comp:'taskModel',label:'Task model'})),
     el('th',{},flabel('skills',MDESC.taskSkills,{comp:'taskSkills',label:'Task skills'})))),tbody)));

 const open=COMPF.open;
 const phaseEls=[];const byPhase={};comp.tasks.forEach(t=>{(byPhase[t.phaseId]=byPhase[t.phaseId]||[]).push(t);});
 comp.phases.forEach(ph=>{
  const tasks=byPhase[ph.id]||[];
  // The visible word beside this box is "review", and it is the same word beside
  // all fifty of them — a <label> here would name fifty controls identically,
  // which conforms and helps nobody. The name folds in the phase id and still
  // contains the visible word, so SC 2.5.3 Label in Name holds as well.
  const rev=el('input',{value:ph.reviewModel??'','data-revmodel':ph.id||'',placeholder:'review model',
    'aria-label':'review model for phase '+(ph.id||'')});
  const setRev=v=>{patch.phases[ph.id]={reviewModel:v||null};};
  rev.oninput=()=>setRev(rev.value.trim());
  const revCombo=comboWrap(rev,modelItems,(name,close)=>{
    rev.value=name;setRev(name);close();});
  // The STOP moved from the input to its combo WRAPPER: the phase row toggles
  // on click, and the combo's menu is part of the same control — a click that
  // chooses a model must not also collapse the phase under the menu.
  revCombo.onclick=e=>e.stopPropagation();
  const pr=el('tr',{class:'phase','data-status':ph.status||''});
  pr.append(el('td',{colspan:'5'},el('div',{class:'phtd'},
    el('span',{class:'tri'}),el('span',{class:'mono'},ph.id||''),el('strong',{},ph.title||''),
    (ph.area||[]).map(a=>el('span',{class:'badge area'},a)),
    el('span',{class:'st','data-status':ph.status||''},label(ph.status)),
    el('span',{class:'count'},tasks.length+(tasks.length===1?' task':' tasks')),
    // Every row below reads done while the badge says in progress — a real
    // state (sign-off is part of the phase) that reads like a contradiction,
    // and on a live repo it did. Name the reason where the eye trips on it.
    (ph.status==='in_progress'&&tasks.length>0&&tasks.every(t=>t.status==='done'))
      ?el('span',{class:'count whynote'},
          'all tasks done — awaiting sign-off (/audit:review)')
      :null,
    el('span',{class:'comp-review'},flabel('review',MDESC.phaseReviewModel,
      {comp:'phaseReviewModel',label:'Phase review model'}),revCombo))));
  pr.onclick=()=>{open[ph.id]=!open[ph.id];refresh();};
  tbody.append(pr);
  const taskEls=[];
  tasks.forEach(t=>{
   // Same again one level down, and worse: these two are named by a COLUMN
   // HEADER ("model", "skills"), which a screen reader does not re-announce per
   // row, and the model box's placeholder is an em dash. Both fold in the task id.
   const tp={};const model=el('input',{value:t.model??'','data-tmodel':t.id||'',placeholder:'—',
     'aria-label':'model for task '+(t.id||'')});
   const setModel=v=>{tp.model=v||null;patch.tasks[t.id]=tp;};
   model.oninput=()=>setModel(model.value.trim());
   // mc: choosing from the menu writes the SAME patch the keystroke writes.
   const modelCombo=comboWrap(model,modelItems,(name,close)=>{
     model.value=name;setModel(name);close();});
   // Three-state read: an explicit null (opt-out) must SURVIVE this accessor —
   // `||[]` would flatten the one deliberate answer into "unconsidered".
   const getSkills=()=>tp.skills!==undefined?tp.skills:(t.skills===null?null:(t.skills||[]));
   const chips=skillChips(getSkills,a=>{tp.skills=a;patch.tasks[t.id]=tp;if(COMPF.needs)refresh();},
     'add a skill to task '+(t.id||''));
   const tr=el('tr',{class:'task','data-status':t.status||''});
   tr.append(el('td',{class:'tid'},t.id||''),el('td',{class:'ttitle',title:t.title||''},t.title||''),
     el('td',{},el('span',{class:'st','data-status':t.status||''},label(t.status))),
     el('td',{class:'tmodel'},modelCombo),el('td',{class:'tskills'},chips));
   tbody.append(tr);
   taskEls.push({id:t.id||'',title:t.title||'',tr,getSkills});
  });
  phaseEls.push({id:ph.id,title:ph.title||'',status:ph.status||'',area:(ph.area||[]).join(' '),tr:pr,tasks:taskEls});
 });
 [...new Set(comp.phases.map(p=>p.status).filter(Boolean))].sort().forEach(s=>{
  const b=el('button',{class:'filt',type:'button','data-status':s,'data-compfilt':s,'aria-pressed':'false'},label(s));
  b.onclick=()=>{COMPF.status=COMPF.status===s?'':s;syncFilters();refresh();};
  statusBar.append(b);});
 // aria-pressed alongside the class: which filter is on was carried by the accent
 // fill alone, which a screen reader never sees. Driven from COMPF rather than
 // toggled in place, so a filter set from elsewhere (Overview) shows here too.
 function syncFilters(){
  [...statusBar.children].forEach(x=>{const on=x.getAttribute('data-status')===COMPF.status;
   x.classList.toggle('on',on);x.setAttribute('aria-pressed',on?'true':'false');});
  needsBtn.classList.toggle('on',COMPF.needs);
  needsBtn.setAttribute('aria-pressed',COMPF.needs?'true':'false');}
 needsBtn.onclick=()=>{COMPF.needs=!COMPF.needs;syncFilters();refresh();};
 expandBtn.onclick=()=>{const anyClosed=phaseEls.some(P=>!open[P.id]);phaseEls.forEach(P=>open[P.id]=anyClosed);refresh();};
 const hit=(s,term)=>!term||s.toLowerCase().includes(term);
 function refresh(){
  COMPF.q=q.value;
  const term=q.value.trim().toLowerCase();const forced=(term!=='')||COMPF.needs;let visP=0,visT=0;
  phaseEls.forEach(P=>{
   const pText=hit(P.id+' '+P.title+' '+P.area,term);let anyT=false;
   P.tasks.forEach(T=>{const tHit=pText||hit(T.id+' '+T.title,term);
    // null is an ANSWER, not a need: only a real empty list counts as "needs".
    const sv=T.getSkills();
    const needHit=!COMPF.needs||(Array.isArray(sv)&&sv.length===0);T._m=tHit&&needHit;if(T._m)anyT=true;});
   const showP=(!COMPF.status||P.status===COMPF.status)&&(pText||anyT)&&(!COMPF.needs||anyT);
   P.tr.style.display=showP?'':'none';if(showP)visP++;
   const isOpen=showP&&(forced||!!open[P.id]);P.tr.classList.toggle('open',isOpen);
   P.tasks.forEach(T=>{const showT=showP&&isOpen&&T._m;T.tr.style.display=showT?'':'none';if(showT)visT++;});});
  count.textContent=(term||COMPF.status||COMPF.needs)?(visP+' / '+phaseEls.length+' phases · '+visT+' tasks')
    :(phaseEls.length+' phases · '+comp.tasks.length+' tasks');
  expandBtn.textContent=phaseEls.some(P=>!open[P.id])?'expand all':'collapse all';}
 // Published for whoever wants to scope this tab without rebuilding it.
 COMPF.apply=()=>{q.value=COMPF.q;syncFilters();refresh();};
 syncFilters();q.addEventListener('input',refresh);refresh();

 EDITS.comp=()=>compChanges(patch);
 const save=el('button',{class:'btn primary','data-save':'comp',onclick:async()=>{
   // The textarea only writes into the patch when its contents PARSE, so an
   // unparseable box would confirm — and then save — the last value that did. A
   // dialog that shows something other than what the form holds is worse than no
   // dialog, so this is refused at the door and the field says which one it is.
   if(bcBad){toast('meta.buildCommands is not valid JSON — fix it or clear it '
     +'before saving','err');bc.focus();return;}
   const rows=compChanges(patch);
   if(!rows.length){toast('nothing to save — no values changed');return;}
   if(!await confirmChanges({title:'Save composition',rows,scope:'comp',
     verb:'Save '+rows.length+' change'+(rows.length===1?'':'s'),
     note:'writes '+STATE.manifestPath}))return;
   const clean={meta:{},phases:patch.phases,tasks:patch.tasks};
   for(const k of Object.keys(patch.meta))clean.meta[k]=patch.meta[k];
   const res=await api('PUT','/api/composition',clean);
   if(!res.ok){c.querySelector('.findings-slot').replaceChildren(findingsBox(res));
    saveOutcome(res,rows,'the manifest',null);return;}
   // Re-render from the saved state. Without it the form kept showing the values
   // you typed rather than the values on disk — indistinguishable while they
   // agree, and silently wrong the moment the server normalised one or refused
   // part of a patch. COMPF is hoisted, so the filter, the search and which
   // phases were open all survive this.
   STATE=await api('GET','/api/state');renderComp();renderOver();
   const slot=$('#comp .findings-slot');
   if(slot)slot.replaceChildren(findingsBox(res));
   saveOutcome(res,rows,'the manifest',slot);}},'Save composition');
 const discard=el('button',{class:'btn small','data-discard':'comp',type:'button',
   onclick:async()=>{
   const rows=compChanges(patch);
   if(!rows.length)return;
   if(!await confirmChanges({title:'Discard unsaved composition edits',rows,
     danger:1,lock:false,
     verb:'Discard '+rows.length+' change'+(rows.length===1?'':'s'),
     note:'nothing is written; the table goes back to the saved manifest'}))return;
   renderComp();toast('discarded — the table is back to the saved manifest');}},
   'Discard');
 onViewEdit('comp',()=>{const n=compChanges(patch).length;
   offState(discard,!n);
   discard.textContent=n?('Discard '+n+' change'+(n===1?'':'s')):'Discard';});
 tcard.append(el('div',{class:'row',style:'margin-top:.9rem'},save,discard),
   el('div',{class:'findings-slot'}));
 if(!STATE.manifestExists)tcard.append(el('div',{class:'findings warn'},'No manifest yet — run /audit:init first.'));
 if(STATE.manifestLocked)tcard.append(el('div',{class:'findings warn'},'Manifest is locked by a running /audit command.'));
 c.append(tcard);
 renderAdoCard(c);
 // building blocks — one table, sub-tabs switch context (skills / agents / mcp)
 const bb=el('div',{class:'card'});
 bb.append(h2h('Available building blocks (discovered)',
   'Skills & agents found in this project, your ~/.claude, and installed plugins — plus MCP servers in scope. Use these names in the pickers above.'));
 const datasets={skills:REG.skills,agents:REG.agents,
   mcp:(REG.mcp||[]).map(n=>({name:n,source:'mcp',description:''}))};
 const subtabs=el('div',{class:'subtabs'}),host=el('div',{class:'regtblwrap'});let cur='skills';
 const drawTbl=()=>{const items=datasets[cur]||[];const tb=el('tbody');
   if(!items.length)tb.append(el('tr',{},el('td',{colspan:'3',class:'mut'},'none found')));
   items.forEach(it=>tb.append(el('tr',{},el('td',{class:'mono'},it.name),
     el('td',{},it.source?el('span',{class:'src badge'},it.source):null),
     el('td',{class:'d'},it.description||''))));
   host.replaceChildren(el('table',{class:'regtbl'},
     el('thead',{},el('tr',{},el('th',{},'name'),el('th',{},'source'),el('th',{},'description'))),tb));};
 ['skills','agents','mcp'].forEach(k=>subtabs.append(el('button',{class:'subtab'+(k===cur?' on':''),
   onclick:e=>{cur=k;[...subtabs.children].forEach(x=>x.classList.toggle('on',x===e.currentTarget));drawTbl();}},
   k+' ('+(datasets[k]||[]).length+')')));
 drawTbl();bb.append(subtabs,host);c.append(bb);
 // Last, after renderAdoCard and the blocks table: a hand-back that runs before
 // the view is finished aims at a node the rest of the build then replaces.
 focusBack(keepBack);}

