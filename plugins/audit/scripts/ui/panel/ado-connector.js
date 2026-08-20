// --- the ADO connector card (meta.ado; saves via PUT /api/ado) -------------------
// A card inside the Composition tab, NOT a row of its form: `ado` is API-only meta
// (_META_API_ONLY server-side), so the composition dialog must never describe an
// edit its form cannot make. The card computes its OWN dotted rows — adoRows
// mirrors _ado_rows in _panel_write.py (presence-aware, dotted, sorted) — so its
// confirm dialog and the server's `applied` echo are two readings of one edit.
function adoRows(was,now){
 const flat=v=>(v&&typeof v==='object'&&!Array.isArray(v))?cfFlat(v):{};
 const a=flat(was),b=flat(now),rows=[];
 [...new Set([...Object.keys(a),...Object.keys(b)])].sort().forEach(p=>{
  const ina=(p in a),inb=(p in b);
  if(ina===inb&&cfSame(a[p],b[p]))return;
  rows.push(cfRow('meta','ado.'+p,ina?a[p]:null,inb?b[p]:null));});
 if(!rows.length&&!cfSame(was,now))rows.push(cfRow('meta','ado',was,now));
 return rows;}
let ADRAFT=null;
function renderAdoCard(c){
 const comp=STATE.composition||{},saved=(comp.meta||{}).ado??null;
 const st=comp.adoStatus||{configured:false,enabled:false,echo:false,
   linked:{tasks:0,bugs:0,phases:0},lastSyncedAt:null};
 ADRAFT=saved===null?null:JSON.parse(JSON.stringify(saved));
 const card=el('div',{class:'card',id:'adocard'});
 card.append(h2h('Azure DevOps connector (meta.ado)',MDESC.adoConnector,
   {comp:'adoConnector',label:'ADO connector'}));
 // The honesty banner: manifest EVIDENCE (links /audit:sync wrote), never a
 // network probe and never the form — the policy tab's data-pstate rule,
 // applied to the connector. It describes the FILE as saved.
 const n=st.linked.tasks+st.linked.bugs+st.linked.phases;
 const banner=!st.configured
  ?['unconfigured','warn','Not configured. Nothing syncs and nothing echoes. '
    +'Fill in organization + project below, or see /audit:sync.']
  :!st.enabled
  ?['off','warn','Turned off. Sync push/pull and the orchestration echo do '
    +'nothing; '+n+' linked item'+(n===1?'':'s')+' stay frozen, links kept.']
  :!n
  ?['unverified','warn','Configured, but no item has ever synced — everything '
    +'below is configuration, not evidence. Run /audit:sync push to link work '
    +'items.']
  :['linked','ok','Linked: '+st.linked.tasks+' task'+(st.linked.tasks===1?'':'s')
    +' · '+st.linked.bugs+' bug'+(st.linked.bugs===1?'':'s')+' · '
    +st.linked.phases+' phase'+(st.linked.phases===1?'':'s')
    +(st.lastSyncedAt?(' · last synced '+st.lastSyncedAt):'')
    +(st.echo?' · echo on':' · echo off')];
 card.append(el('div',{class:'findings '+banner[1],'data-adostate':banner[0]},
   banner[2]));
 // --- draft plumbing. Deleting a key is how "use the default" is written
 // (delPath's rule); an emptied draft reads as null — connector removed.
 const A=()=>(ADRAFT=ADRAFT||{});
 const pruneTop=()=>{if(ADRAFT&&!Object.keys(ADRAFT).length)ADRAFT=null;};
 // The id is the config path, which is already unique per field and is the string
 // a reader of audit.config.json recognises. Dots in an id are fine here -- `for`
 // is an exact-string match, not a selector, and fieldId() has been minting
 // `set-usage.bands` on the Guards form all along.
 const txt=(path,ph,lbl,help)=>{
  const tid='ado-'+path;
  const i=el('input',{id:tid,value:getPath(ADRAFT||{},path)??'',placeholder:ph||''});
  i.oninput=()=>{const v=i.value.trim();
   if(v)setPath(A(),path,v);else if(ADRAFT)delPath(ADRAFT,path);pruneTop();};
  return el('span',{class:'f'},flabel(lbl,help,null,tid),i);};
 // absent = ON for these three; the checkbox writes false or deletes the key.
 const onoff=(key,lbl,help)=>{
  const cb=el('input',{type:'checkbox',id:'ado-'+key});
  cb.checked=!ADRAFT||ADRAFT[key]!==false;
  cb.onchange=()=>{if(cb.checked){if(ADRAFT)delete ADRAFT[key];}
   else A()[key]=false;pruneTop();};
  return el('span',{class:'f cbf'},cb,flabel(lbl,help,null,'ado-'+key));};
 card.append(el('div',{class:'row'},
   onoff('enabled','Connector enabled',MDESC.adoEnabled),
   onoff('echo','Echo on task/phase transitions',MDESC.adoEcho),
   onoff('phaseWorkItems','PBI per phase',MDESC.adoPhaseWorkItems)));
 card.append(el('div',{class:'row'},
   txt('organization','<org> or https://dev.azure.com/<org>','Organization'),
   txt('project','project name','Project'),
   txt('areaPath','optional','Area path'),
   txt('iterationPath','optional (static)','Iteration path')));
 // ENH-1: the provenance tag — absent = audit-plugin, explicit null = none.
 const tagCur=ADRAFT?ADRAFT.tag:undefined;
 const tagIn=el('input',{id:'ado-tag',
   value:typeof tagCur==='string'?tagCur:'',placeholder:'audit-plugin'});
 // The <label> below wraps this box, and a wrapper is an association a source
 // check cannot verify: it holds only while the box stays the label's FIRST
 // labelable descendant, which is exactly the property F26 lost when a <button>
 // got there first. So the binding is explicit as well — same words, same click
 // target, but now `for` says which control they name and dropping it goes red.
 const tagNone=el('input',{type:'checkbox',id:'ado-tag-none',
   title:'no provenance tag at all'});
 tagNone.checked=tagCur===null;tagIn.disabled=tagCur===null;
 const tagApply=()=>{
  if(tagNone.checked){A().tag=null;tagIn.value='';tagIn.disabled=true;}
  else{tagIn.disabled=false;const v=tagIn.value.trim();
   if(v)A().tag=v;else if(ADRAFT)delete ADRAFT.tag;}
  pruneTop();};
 tagIn.oninput=tagApply;tagNone.onchange=tagApply;
 card.append(el('div',{class:'row'},
   txt('types.bug','Bug','Bug type'),
   txt('types.task','Task','Task type'),
   txt('types.pbi','auto-detect at first phase push','Phase (PBI) type',
     MDESC.adoTypes),
   el('span',{class:'f'},flabel('Provenance tag',MDESC.adoTag,null,'ado-tag'),
     el('span',{class:'inl'},tagIn,
       el('label',{class:'inl',for:'ado-tag-none'},tagNone,'no tag')))));
 // --- stateMap: one fixed row per manifest status. Empty box = the built-in
 // default (its placeholder); "never" writes null — the team moves that card.
 // The phase block exists because phase work items carry a DIFFERENT state
 // vocabulary (a Scrum PBI knows no "In Progress") — live-gate F1.
 const SMDEF={phase:{pending:'New',in_progress:'Active',
     blocked:'Active',done:'Closed'},
   task:{pending:'New',in_progress:'Active',
     blocked:'Active + tag blocked',done:'Closed'},
   bug:{open:'New',triaged:'Active',in_progress:'Active',fixed:'Resolved',
     wontfix:'Closed'}};
 const smTbl=kind=>{
  const tb=el('tbody');
  Object.keys(SMDEF[kind]).forEach(stt=>{
   const cur=getPath(ADRAFT||{},'stateMap.'+kind+'.'+stt);
   // The row's visible text is the status alone ("blocked"), and it repeats across
   // the phase, task and bug tables. The <thead> these grew under SC 1.3.1 names
   // the COLUMNS, not which of the three tables a row is in — the only thing that
   // says that is the flabel above the table, and a label is not a caption. So the
   // name still carries the kind as well as the status.
   const i=el('input',{value:typeof cur==='string'?cur:'',
     placeholder:SMDEF[kind][stt],
     'aria-label':kind+' '+stt+' maps to ADO state'});
   // One id per cell, not per column: this builder runs once per kind and once
   // per status inside that, so a constant here would mint duplicate ids across
   // the grids and a `for` that resolves to whichever box came first is worse
   // than no `for` at all — it would name the wrong transition, confidently.
   const nvId='ado-sm-'+kind+'-'+stt+'-never';
   const nv=el('input',{type:'checkbox',id:nvId,
     title:'never move state on this transition'});
   nv.checked=cur===null;i.disabled=cur===null;
   const apply=()=>{
    if(nv.checked){setPath(A(),'stateMap.'+kind+'.'+stt,null);
     i.value='';i.disabled=true;}
    else{i.disabled=false;const v=i.value.trim();
     if(v)setPath(A(),'stateMap.'+kind+'.'+stt,v);
     else if(ADRAFT)delPath(ADRAFT,'stateMap.'+kind+'.'+stt);}
    pruneTop();};
   i.oninput=apply;nv.onchange=apply;
   // SC 1.3.1: the manifest status IS this row's header, and it was a plain
   // <td> — so the checkbox in row three announced as "never" with nothing
   // saying never WHAT. The row axis is the one that carries the transition.
   tb.append(el('tr',{},el('th',{scope:'row',class:'mono'},stt),el('td',{},i),
     el('td',{},el('label',{class:'inl',for:nvId},nv,'never'))));});
  // ...and the column axis, announced (.vh) rather than painted. The legend a
  // sighted reader gets is adoStateMap's help on the label right above this
  // table; a visible header row would print those three words three times on
  // one card. display:none would take the header out of the accessibility
  // tree, which is the one thing it must not do.
  return el('div',{class:'f'},flabel(kind+' states',MDESC.adoStateMap),
    el('table',{class:'regtbl adosm'},
      el('thead',{},el('tr',{},
        el('th',{scope:'col'},el('span',{class:'vh'},'manifest status')),
        el('th',{scope:'col'},el('span',{class:'vh'},'ADO state')),
        el('th',{scope:'col'},el('span',{class:'vh'},'never move')))),tb));};
 card.append(el('div',{class:'row'},smTbl('phase'),smTbl('task'),smTbl('bug')));
 // --- the done move: Remaining Work + generated comments
 const rwCur=getPath(ADRAFT||{},'onComplete.remainingWork');
 const rw=el('input',{type:'number',min:'0',step:'any',id:'ado-rw',
   value:typeof rwCur==='number'?String(rwCur):'',placeholder:'not written'});
 const rwNever=el('input',{type:'checkbox',id:'ado-rw-never',
   title:'never touch Remaining Work'});
 rwNever.checked=rwCur===null;rw.disabled=rwCur===null;
 const rwApply=()=>{
  if(rwNever.checked){setPath(A(),'onComplete.remainingWork',null);
   rw.value='';rw.disabled=true;}
  else{rw.disabled=false;
   if(rw.value!=='')setPath(A(),'onComplete.remainingWork',Number(rw.value));
   else if(ADRAFT)delPath(ADRAFT,'onComplete.remainingWork');}
  pruneTop();};
 rw.oninput=rwApply;rwNever.onchange=rwApply;
 const cflag=(key,lbl)=>{const cid='ado-comments.'+key;
  const cb=el('input',{type:'checkbox',id:cid});
  cb.checked=!!getPath(ADRAFT||{},'comments.'+key);
  cb.onchange=()=>{if(cb.checked)setPath(A(),'comments.'+key,true);
   else if(ADRAFT)delPath(ADRAFT,'comments.'+key);pruneTop();};
  return el('span',{class:'f cbf'},cb,flabel(lbl,MDESC.adoComments,null,cid));};
 card.append(el('div',{class:'row'},
   el('span',{class:'f'},flabel('Remaining Work on done',
     MDESC.adoRemainingWork,null,'ado-rw'),
     el('span',{class:'inl'},rw,el('label',{class:'inl',for:'ado-rw-never'},rwNever,
       "don't touch"))),
   cflag('onBlocked','Comment when blocked'),
   cflag('onComplete','Comment on completion')));
 // --- sprint + pull scoping
 const team=el('input',{id:'ado-sprint.team',
   value:getPath(ADRAFT||{},'sprint.team')??'',
   placeholder:'empty = static iteration path'});
 team.oninput=()=>{const v=team.value.trim();
  if(v)setPath(A(),'sprint.team',v);
  else if(ADRAFT)delPath(ADRAFT,'sprint');pruneTop();};
 // Same reason, and this one is the case that proved it: this editor SAT inside a
 // <label>, and it bound that label only while it held no tags. Add one and the
 // chip's remove button takes the association. So the wrapper below is a <span>
 // now and this box keeps the name it always relied on -- the ariaName argument,
 // which fl6 requires of every listEditor call site. No forId: the only labelable
 // thing in a list editor is an <input> that draw() destroys and rebuilds, and the
 // id that does exist on these editors is on the <div>, where a `for` would
 // associate nothing while looking as if it did (renderField says the same).
 const tags=listEditor(()=>getPath(ADRAFT||{},'pull.tags')||[],
   a=>{if(a.length)setPath(A(),'pull.tags',a);
    else if(ADRAFT)delPath(ADRAFT,'pull.tags');pruneTop();},'tag…',null,
   'Pull tags: add a tag');
 card.append(el('div',{class:'row'},
   el('span',{class:'f'},flabel('Sprint team (current iteration)',
     MDESC.adoSprint,null,'ado-sprint.team'),team),
   txt('pull.areaPath','falls back to Area path','Pull area path',
     MDESC.adoPull),
   el('span',{class:'f'},flabel('Pull tags',MDESC.adoPull),tags)));
 // --- identityMap: a pair editor, edited directly — NEVER through delPath,
 // whose dotted paths would split the ledger keys (emails carry dots).
 const imWrap=el('div',{});
 const imDraw=()=>{imWrap.textContent='';
  const m=getPath(ADRAFT||{},'identityMap')||{};
  Object.keys(m).forEach(k=>imWrap.append(el('div',
    {class:'row','data-imrow':k},
    el('span',{class:'mono'},k),el('span',{class:'cfarr'},'→'),
    el('span',{class:'mono'},m[k]),
    el('button',{class:'btn small',type:'button','aria-label':'remove '+k,
      onclick:()=>{const im=A().identityMap||{};delete im[k];
       if(!Object.keys(im).length)delete ADRAFT.identityMap;
       pruneTop();imDraw();}},'×'))));
  const vals={};Object.keys(m).forEach(k=>{
   const lo=String(m[k]).toLowerCase();(vals[lo]=vals[lo]||[]).push(k);});
  const dup=Object.values(vals).find(a=>a.length>1);
  if(dup)imWrap.append(el('div',{class:'mut small','data-imdup':'1'},
   'two ledger identities share one ADO identity ('+dup.join(', ')
   +') — pull maps it back to the FIRST in map order'));
  // No visible text of any kind beside these two, so the placeholder's words are
  // the right name — they just have to survive the first keystroke.
  const ki=el('input',{placeholder:'ledger identity (git email/name)',
      'aria-label':'ledger identity (git email/name)'}),
    vi=el('input',{placeholder:'ADO identity (email/UPN)',
      'aria-label':'ADO identity (email/UPN)'});
  imWrap.append(el('div',{class:'row'},ki,vi,
    el('button',{class:'btn small',type:'button','data-imadd':'1',
      onclick:()=>{const k=ki.value.trim(),v=vi.value.trim();
       if(!k||!v)return;const o=A();o.identityMap=o.identityMap||{};
       o.identityMap[k]=v;ki.value='';vi.value='';imDraw();}},'add')));};
 imDraw();
 card.append(el('div',{class:'f'},flabel('Identity map (ledger → ADO)',
   MDESC.adoIdentityMap),imWrap));
 // --- save / discard. EDITS.ado feeds beforeunload and the disk-refresh
 // dirtiness check; the buttons listen on the CARD directly — re-registering
 // the comp view's shared updater from here would abort the composition
 // form's own listener.
 EDITS.ado=()=>adoRows(saved,ADRAFT);
 const save=el('button',{class:'btn primary','data-save':'ado',onclick:async()=>{
   const rows=adoRows(saved,ADRAFT);
   if(!rows.length){toast('nothing to save — no values changed');return;}
   if(!await confirmChanges({title:'Save ADO connector',rows,scope:'comp',
     verb:'Save '+rows.length+' change'+(rows.length===1?'':'s'),
     note:'writes '+STATE.manifestPath}))return;
   const res=await api('PUT','/api/ado',{ado:ADRAFT});
   if(!res.ok){
    card.querySelector('.findings-slot').replaceChildren(findingsBox(res));
    saveOutcome(res,rows,'the manifest',null);return;}
   STATE=await api('GET','/api/state');renderComp();renderOver();
   const slot=$('#adocard .findings-slot');
   if(slot)slot.replaceChildren(findingsBox(res));
   saveOutcome(res,rows,'the manifest',slot);}},'Save ADO connector');
 const discard=el('button',{class:'btn small','data-discard':'ado',
   type:'button',onclick:async()=>{
   const rows=adoRows(saved,ADRAFT);
   if(!rows.length)return;
   if(!await confirmChanges({title:'Discard unsaved connector edits',rows,
     danger:1,lock:false,
     verb:'Discard '+rows.length+' change'+(rows.length===1?'':'s'),
     note:'nothing is written; the card goes back to the saved manifest'}))
    return;
   renderComp();toast('discarded — the card is back to the saved manifest');}},
   'Discard');
 const upd=()=>{const n=adoRows(saved,ADRAFT).length;
  offState(discard,!n);
  discard.textContent=n?('Discard '+n+' change'+(n===1?'':'s')):'Discard';};
 ['input','change','click'].forEach(e=>
  card.addEventListener(e,()=>requestAnimationFrame(upd)));
 upd();
 card.append(el('div',{class:'row',style:'margin-top:.9rem'},save,discard),
   el('div',{class:'findings-slot'}));
 c.append(card);}
// One malformed manifest can emit a finding PER phase, per task and per indexed
// file: a 300-phase repo produced 1009 of them, joined into a single paragraph
// that filled the screen and told the reader nothing. But 1009 findings are not
// 1009 problems — they were four mistakes repeated. So group by shape, count each,
// show one real example, and keep the raw list one click away.
const FGROUP_MIN=6, FSHOW=6, FRAW=200;
function findingKind(s){
 const i=s.indexOf(': ');
 return (i>0?s.slice(i+2):s)
  .replace(/'[^']*'/g,"'*'").replace(/\[[^\]]*\]/g,'[*]').replace(/\d+/g,'#');}
// Named for the manifest specifically: findingsBox() already exists above for
// save-result feedback, and a second function of the same name would hoist over it
// and break every config save.
function manifestFindingsBox(n,list){
 const box=el('div',{class:'findings err'},
   el('b',{},'✗ '+n+' finding(s)'));
 if(list.length<FGROUP_MIN){
  box.append(' '+list.join(' · '));return box;}
 const by=new Map();
 for(const f of list){const k=findingKind(f);
  const g=by.get(k)||{n:0,eg:f};g.n++;by.set(k,g);}
 const groups=[...by.entries()].sort((a,b)=>b[1].n-a[1].n);
 const ul=el('ul',{class:'fgrp'});
 groups.slice(0,FSHOW).forEach(([k,g])=>ul.append(el('li',{},
   el('span',{class:'fn'},g.n+'×'),
   el('span',{},k,el('div',{class:'feg'},g.n>1?'e.g. '+g.eg:g.eg)))));
 box.append(el('div',{},groups.length===1?'one problem, repeated:'
   :groups.length+' distinct problems'
    +(groups.length>FSHOW?' ('+FSHOW+' most common shown)':'')+':'),ul);
 const ol=el('ol',{});
 list.slice(0,FRAW).forEach(f=>ol.append(el('li',{},f)));
 if(list.length>FRAW)ol.append(el('li',{},'… and '+(list.length-FRAW)+
   ' more — run /audit:validate for the complete list'));
 box.append(el('details',{class:'fall'},
   el('summary',{},'every finding, unfolded'),ol));
 return box;}

