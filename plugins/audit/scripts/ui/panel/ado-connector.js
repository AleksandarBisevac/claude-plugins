// --- the ADO connector card (meta.ado; saves via PUT /api/ado) -------------------
// A card inside the Composition tab, NOT a row of its form. `ado` is API-only
// meta — it is listed in _META_API_ONLY, and the composition endpoint will not
// accept it — so no ado change may ever reach the composition dialog: a dialog
// that describes an edit its own save cannot make is a dialog that lies. This
// card therefore keeps its own draft, computes its own rows, runs its own confirm
// and writes through its own endpoint.
/**
 * The dotted rows for one connector edit: exactly what this card would change.
 *
 * Mirrors `_ado_rows` in `_panel_write.py` — presence-aware, dotted and sorted —
 * so the confirm dialog here and the server's `applied` echo are two readings of
 * one edit rather than two opinions about it.
 *
 * Presence-aware matters because absent and null are different edits: a key that
 * disappears restores a default, and a key set to null says "never do this".
 * Comparing values alone would report those as the same change, or as none.
 *
 * A change the flattening cannot express — the whole connector appearing or
 * disappearing, which has no single dotted path — falls back to one row for `ado`
 * itself, so a real edit is never reported as an empty list.
 *
 * @param {object|null} was - the connector as the manifest holds it, null when
 *   there is none
 * @param {object|null} now - the draft, null once the form has been emptied
 * @returns {{target: string, field: string, from: *, to: *}[]} one row per
 *   changed path, sorted by path; empty only when nothing changed
 */
function adoRows(was,now){
 const flat=v=>(v&&typeof v==='object'&&!Array.isArray(v))?cfFlat(v):{};
 const a=flat(was),b=flat(now),rows=[];
 [...new Set([...Object.keys(a),...Object.keys(b)])].sort().forEach(p=>{
  const ina=(p in a),inb=(p in b);
  if(ina===inb&&cfSame(a[p],b[p]))return;
  rows.push(cfRow('meta','ado.'+p,ina?a[p]:null,inb?b[p]:null));});
 if(!rows.length&&!cfSame(was,now))rows.push(cfRow('meta','ado',was,now));
 return rows;}
/**
 * One typed template value, as the literal ADO will be sent.
 *
 * A BOX GIVES TEXT AND THE BOARD WANTS A TYPE. `OriginalEstimate` has to arrive
 * as a number and `Activity` as a string, and the manifest stores whichever it
 * is told — so the box has to decide, and the decision has to be one a reader
 * can predict from what they typed.
 *
 * The number half is `typedNumber`'s round trip, shared with the ADO parent id
 * box rather than spelled twice — the two are one question ("does this text
 * spell that number?") and two answers to it would disagree about `4e2` on some
 * afternoon. What is decided HERE is only what to do when the answer is no: the
 * text stands as the string it plainly is, which keeps a version like `1.0.0`
 * and a padded id like `007` intact.
 *
 * @param {string} text - exactly what was typed, already trimmed
 * @returns {string|number|boolean} the literal to store
 */
function adoFieldValue(text){
 if(text==='true')return true;
 if(text==='false')return false;
 const n=typedNumber(text);
 return n===null?text:n;}
/**
 * One field added to a per-type template, WITHOUT going through a dotted path.
 *
 * THIS IS THE WHOLE REASON IT IS A FUNCTION. `setPath`/`delPath` split on dots,
 * and an ADO reference name is full of them —
 * `Microsoft.VSTS.Common.Activity` is ONE key, and a dotted writer would file it
 * as four nested levels, producing a `meta.ado.fields` the validator refuses and
 * the board never sees. `identityMap` avoids the same shredder for the same
 * reason (email addresses carry dots) and the two are the only editors on this
 * card that touch their keys directly.
 *
 * Mutates `fields` in place and returns it, as `identityMap`'s editor does: this
 * is the draft, and a copy would leave the card editing something the Save never
 * reads.
 *
 * @param {Object<string, Object<string, *>>} fields - the draft's `fields` map
 * @param {string} wit - the work item type name, matched exactly as
 *   `_ado_fields.template_for` matches it
 * @param {string} name - the ADO field, reference or display spelling
 * @param {string|number|boolean} value - the literal
 * @returns {Object<string, Object<string, *>>} `fields`
 */
function adoFieldSet(fields,wit,name,value){
 fields[wit]=fields[wit]||{};
 fields[wit][name]=value;
 return fields;}
/**
 * One field removed, pruning a type that has none left.
 *
 * Pruning matters because an empty template is a WARNING from the validator —
 * "it supplies nothing, remove the key" — so a card that left `{"Task": {}}`
 * behind would make removing the last field print a complaint about the removal.
 *
 * @param {Object<string, Object<string, *>>} fields - the draft's `fields` map
 * @param {string} wit - the work item type name
 * @param {string} name - the ADO field, spelled as it is stored
 * @returns {Object<string, Object<string, *>>} `fields`, possibly emptied
 */
function adoFieldDrop(fields,wit,name){
 const t=fields[wit];
 if(!t)return fields;
 delete t[name];
 if(!Object.keys(t).length)delete fields[wit];
 return fields;}
/**
 * The banner's clause about work items MORE THAN ONE manifest item claims.
 *
 * Two manifest items pointing at one card is a real arrangement on a real
 * board — an import that adopts a card somebody had already linked by hand
 * makes one — and nothing anywhere refuses it: a link's shape is validated and
 * the uniqueness of its target never is. So a push writes every claimant to the
 * same card and the last one wins, and until this clause existed no surface
 * said so.
 *
 * THREE ANSWERS AND NEVER TWO, which is the whole reason it is a function.
 * `shared` names the cards, `none` says each is claimed once, and ANYTHING ELSE
 * — no link walked yet, or a payload with no `shared` in it at all — says that
 * nothing was counted. Folding that last case into `none` would print agreement
 * where there is only silence, the same collapse `_shared_claims` and the
 * candidate cache before it exist to prevent.
 *
 * @param {{state: string, items: {adoId: number, claimants: string[]}[]}|null|undefined} shared -
 *   `adoStatus.shared` as the server sends it
 * @returns {string} one clause, never empty
 */
function adoSharedWords(shared){
 const state=(shared||{}).state,items=(shared||{}).items||[];
 if(state==='shared')return plural(items.length,'work item')
  +' claimed by more than one item ('+items.map(x=>'#'+x.adoId).join(', ')+')';
 if(state==='none')return 'no work item claimed twice';
 return 'shared claims not counted';}
/**
 * The connector draft every control on this card edits.
 *
 * Null is a VALUE here and not an absence: it means "no connector in the
 * manifest", which is what an emptied form has to be able to say. So every write
 * goes through the local accessor that materialises the object on first use, and
 * every delete prunes back to null once nothing is left — which is what keeps
 * "the connector was removed" distinguishable from "nothing was changed".
 *
 * @type {object|null}
 */
let ADRAFT=null;
/**
 * Build the Azure DevOps connector card and append it to the Composition view.
 *
 * The banner at the top reports manifest EVIDENCE — the links a sync actually
 * wrote — and never a network probe and never the form. It describes the file as
 * SAVED, so a form full of unsaved organization and project names still reads as
 * unconfigured, which is the honest answer to "does this sync yet".
 *
 * Every field writes into ADRAFT rather than into the manifest, and the shape of
 * that draft is the API's: a key deleted means "use the default", an explicit
 * null means "never do this", and the two are different edits all the way to the
 * server. That is why the never/don't-touch checkboxes exist beside boxes that
 * could otherwise just be left empty.
 *
 * Resets ADRAFT from STATE on every call, so this is also how the card is
 * discarded back to disk.
 *
 * @param {HTMLElement} c - the Composition view to append the card into. It is
 *   rebuilt on every renderComp, so nothing may hold this card across one: the
 *   save handler below looks its own findings slot up again from the document
 *   after a successful write, because the re-render it triggers has already
 *   replaced the element the handler closed over
 * @returns {void}
 */
function renderAdoCard(c){
 const comp=STATE.composition||{},saved=(comp.meta||{}).ado??null;
 const st=comp.adoStatus||{configured:false,enabled:false,echo:false,
   linked:{tasks:0,bugs:0,phases:0},lastSyncedAt:null,shared:null};
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
    +'nothing; '+plural(n,'linked item stays','linked items stay')
    +' frozen, links kept.']
  :!n
  ?['unverified','warn','Configured, but no item has ever synced — everything '
    +'below is configuration, not evidence. Run /audit:sync push to link work '
    +'items.']
  :['linked','ok','Linked: '+plural(st.linked.tasks,'task')
    +' · '+plural(st.linked.bugs,'bug')+' · '+plural(st.linked.phases,'phase')
    +(st.lastSyncedAt?(' · last synced '+st.lastSyncedAt):'')
    +(st.echo?' · echo on':' · echo off')];
 // The shared-claim clause rides on the states that describe a manifest
 // CARRYING links: `off` keeps them and `linked` counts them. The remaining
 // banners are about a plan with nothing on the board, where the question has
 // no subject — and a clause reading "not counted" there would blame the
 // reader for a fetch nobody owed. A collision escalates the TONE and never
 // the name: `data-adostate` still says which banner this is, so a card whose
 // links are all fine and a card whose links collide stay the same banner
 // making different news.
 if(banner[0]==='linked'||banner[0]==='off'){
  banner[2]+=' · '+adoSharedWords(st.shared);
  if((st.shared||{}).state==='shared')banner[1]='warn';}
 card.append(el('div',{class:'findings '+banner[1],'data-adostate':banner[0],
   'data-adoshared':(st.shared||{}).state||'uncounted'},banner[2]));
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
  // The setting this control belongs to, taken from the path it WRITES to, so
  // the declaration and the write can never name two different keys.
  return el('span',{class:'f','data-adosetting':path.split('.')[0]},
    flabel(lbl,help,null,tid),i);};
 // absent = ON for these three; the checkbox writes false or deletes the key.
 const onoff=(key,lbl,help)=>{
  const cb=el('input',{type:'checkbox',id:'ado-'+key});
  cb.checked=!ADRAFT||ADRAFT[key]!==false;
  cb.onchange=()=>{if(cb.checked){if(ADRAFT)delete ADRAFT[key];}
   else A()[key]=false;pruneTop();};
  return el('span',{class:'f cbf','data-adosetting':key.split('.')[0]},
    cb,flabel(lbl,help,null,'ado-'+key));};
 card.append(el('div',{class:'row'},
   onoff('enabled','Connector enabled',MDESC.adoEnabled),
   onoff('echo','Echo on task/phase transitions',MDESC.adoEcho),
   onoff('phaseWorkItems','PBI per phase',MDESC.adoPhaseWorkItems)));
 card.append(el('div',{class:'row'},
   txt('organization','<org> or https://dev.azure.com/<org>','Organization'),
   txt('project','project name','Project'),
   txt('areaPath','optional','Area path'),
   txt('iterationPath','optional (static)','Iteration path')));
 // The provenance tag, in three states: absent means the default audit-plugin
 // tag, a string means that tag, and an explicit null means no tag at all.
 const tagCur=ADRAFT?ADRAFT.tag:undefined;
 const tagIn=el('input',{id:'ado-tag',
   value:typeof tagCur==='string'?tagCur:'',placeholder:'audit-plugin'});
 // The <label> below wraps this box, and a wrapper is an association a source
 // check cannot verify: it holds only while the box stays the label's FIRST
 // labelable descendant, and any button that lands ahead of it silently takes
 // the association away. So the binding is explicit as well — same words, same
 // click target, but now `for` says which control they name and dropping it
 // goes red.
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
   el('span',{class:'f','data-adosetting':'tag'},
     flabel('Provenance tag',MDESC.adoTag,null,'ado-tag'),
     el('span',{class:'inl'},tagIn,
       el('label',{class:'inl',for:'ado-tag-none'},tagNone,'no tag')))));
 // --- stateMap: one fixed row per manifest status. Empty box = the built-in
 // default (its placeholder); "never" writes null — the team moves that card.
 // The phase block exists because phase work items carry a DIFFERENT state
 // vocabulary from tasks and bugs: a Scrum PBI knows no "In Progress", so one
 // shared map would send a state the board refuses.
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
  return el('div',{class:'f','data-adosetting':'stateMap'},
    flabel(kind+' states',MDESC.adoStateMap),
    el('table',{class:'regtbl adosm'},
      tableHead(['manifest status','ADO state','never move'].map(h=>
        ({attrs:{scope:'col'},label:el('span',{class:'vh'},h)}))),tb));};
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
  return el('span',{class:'f cbf','data-adosetting':'comments'},
    cb,flabel(lbl,MDESC.adoComments,null,cid));};
 card.append(el('div',{class:'row'},
   el('span',{class:'f','data-adosetting':'onComplete'},
     flabel('Remaining Work on done',MDESC.adoRemainingWork,null,'ado-rw'),
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
 // which fl6 requires of every list-editor call site. No forId: the only labelable
 // thing in a list editor is an <input> that draw() destroys and rebuilds, and the
 // id that does exist on these editors is on the <div>, where a `for` would
 // associate nothing while looking as if it did (scalarField says the same).
 const tags=listEditor(()=>getPath(ADRAFT||{},'pull.tags')||[],
   a=>{if(a.length)setPath(A(),'pull.tags',a);
    else if(ADRAFT)delPath(ADRAFT,'pull.tags');pruneTop();},'tag…',null,
   'Pull tags: add a tag');
 card.append(el('div',{class:'row'},
   el('span',{class:'f','data-adosetting':'sprint'},
     flabel('Sprint team (current iteration)',MDESC.adoSprint,null,
       'ado-sprint.team'),team),
   txt('pull.areaPath','falls back to Area path','Pull area path',
     MDESC.adoPull),
   el('span',{class:'f','data-adosetting':'pull'},
     flabel('Pull tags',MDESC.adoPull),tags)));
 // --- F187: the two settings that had no control at all. `requireParent` is a
 // gate that refuses every create with nowhere to hang, `parentWorkItem` is the
 // manifest-wide answer to "where", and `tagVocabulary` decides which tags an
 // item may carry — all three were preconditions a reader could satisfy only by
 // editing the manifest by hand, which is a gate people switch off instead.
 //
 // The parent is an INTEGER and typed as one: a work item id that arrived as a
 // string validates nowhere, and coercing silently would hide a paste of a URL.
 const pwCur=ADRAFT?ADRAFT.parentWorkItem:undefined;
 const pw=el('input',{id:'ado-parentWorkItem',type:'number',min:'1',step:'1',
   value:typeof pwCur==='number'?String(pwCur):'',placeholder:'e.g. 101',
   // The placeholder is an EXAMPLE and vanishes on the first keystroke, so it
   // cannot be this box's name - `fl1` is the rule and it caught this one.
   'aria-label':'parent work item id'});
 pw.oninput=()=>{const v=pw.value.trim();
  if(v===''){if(ADRAFT)delete ADRAFT.parentWorkItem;}
  // Number('') is 0 and Number('12a') is NaN; neither is an id. An unparseable
  // box leaves the key ALONE rather than writing a number the board cannot have.
  else{const n=Number(v);if(Number.isInteger(n)&&n>0)A().parentWorkItem=n;}
  pruneTop();};
 const reqP=el('input',{type:'checkbox',id:'ado-conventions.requireParent'});
 reqP.checked=!!getPath(ADRAFT||{},'conventions.requireParent');
 reqP.onchange=()=>{if(reqP.checked)setPath(A(),'conventions.requireParent',true);
  else if(ADRAFT)delPath(ADRAFT,'conventions.requireParent');pruneTop();};
 card.append(el('div',{class:'row'},
   el('span',{class:'f','data-adosetting':'parentWorkItem'},
     flabel('Parent work item',MDESC.adoParentWorkItem,null,
       'ado-parentWorkItem'),pw),
   el('span',{class:'f cbf','data-adosetting':'conventions'},
     reqP,flabel('Require a parent',MDESC.adoRequireParent,null,
       'ado-conventions.requireParent'))));
 // --- tagVocabulary: prefix → allowed values. Edited as a PAIR list like
 // identityMap and for the same reason — a prefix is a key and a dotted-path
 // writer would split one carrying a dot. The value cell is a comma list, and
 // `*` alone is the open axis (`release:2026-08` without a monthly edit).
 const tvWrap=el('div',{});
 const tvGet=()=>getPath(ADRAFT||{},'tagVocabulary')
   ||((ADRAFT||{}).conventions||{}).tagVocabulary||{};
 const tvSet=m=>{const c=A().conventions=A().conventions||{};
  if(Object.keys(m).length)c.tagVocabulary=m;else delete c.tagVocabulary;
  if(!Object.keys(c).length)delete ADRAFT.conventions;pruneTop();};
 const tvDraw=()=>{tvWrap.textContent='';
  const m=((ADRAFT||{}).conventions||{}).tagVocabulary||{};
  Object.keys(m).forEach(k=>{
   const vals=Array.isArray(m[k])?m[k]:[];
   const open=vals.length===1&&String(vals[0]).trim()==='*';
   tvWrap.append(el('div',{class:'row','data-tvrow':k},
     el('span',{class:'mono'},k+':'),
     el('span',{class:'mono'},open?'any value (open axis)':vals.join(', ')||'(none)'),
     el('button',{class:'btn small',type:'button','aria-label':'remove '+k,
       onclick:()=>{const c=((ADRAFT||{}).conventions||{}).tagVocabulary||{};
        const next={};Object.keys(c).forEach(x=>{if(x!==k)next[x]=c[x];});
        tvSet(next);tvDraw();}},'×')));});
  const pi=el('input',{placeholder:'prefix (or * for bare tags)',
      'aria-label':'tag prefix, or * for bare tags'}),
    vi=el('input',{placeholder:'values, comma separated — or * for any',
      'aria-label':'allowed values, comma separated, or * for any'});
  const add=()=>{const k=pi.value.trim();if(!k)return;
   const vals=vi.value.split(',').map(x=>x.trim()).filter(Boolean);
   const cur=((ADRAFT||{}).conventions||{}).tagVocabulary||{};
   const next={};Object.keys(cur).forEach(x=>{next[x]=cur[x];});
   next[k]=vals;tvSet(next);pi.value='';vi.value='';tvDraw();};
  tvWrap.append(el('div',{class:'row'},pi,vi,
    el('button',{class:'btn small',type:'button',onclick:add},'add')));};
 tvDraw();
 card.append(el('div',{class:'f','data-adosetting':'conventions'},
   flabel('Tag vocabulary',MDESC.adoTagVocabulary),tvWrap));
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
 card.append(el('div',{class:'f','data-adosetting':'identityMap'},
   flabel('Identity map (ledger → ADO)',MDESC.adoIdentityMap),imWrap));
 // --- fields: the per-type template, edited DIRECTLY for identityMap's reason
 // and a sharper version of it — an ADO reference name IS dotted, so a dotted
 // writer would shred `Microsoft.VSTS.Common.Activity` into four levels every
 // single time rather than only on the keys that happen to carry a dot.
 const fdWrap=el('div',{});
 const fdDraw=()=>{fdWrap.textContent='';
  const f=(ADRAFT&&ADRAFT.fields&&typeof ADRAFT.fields==='object'
    &&!Array.isArray(ADRAFT.fields))?ADRAFT.fields:{};
  Object.keys(f).forEach(wit=>{
   const tpl=(f[wit]&&typeof f[wit]==='object')?f[wit]:{};
   Object.keys(tpl).forEach(name=>fdWrap.append(el('div',
     {class:'row','data-fdrow':wit+' '+name},
     el('span',{class:'badge'},wit),
     el('span',{class:'mono'},name),el('span',{class:'cfarr'},'→'),
     // JSON.stringify and not String(): `4` and `\"4\"` are different literals
     // to a board that requires a number, and a row printing both as 4 would
     // hide the one thing this editor has to decide.
     el('span',{class:'mono'},JSON.stringify(tpl[name])),
     el('button',{class:'btn small',type:'button',
       'aria-label':'remove '+wit+' '+name,
       onclick:()=>{adoFieldDrop(A().fields||{},wit,name);
        if(ADRAFT.fields&&!Object.keys(ADRAFT.fields).length)delete ADRAFT.fields;
        pruneTop();fdDraw();}},'×'))));});
  // No visible words beside these three, so the placeholders are the name — and
  // they have to survive the first keystroke, which is what the aria-labels are
  // for. Same shape as the identity pair above it.
  const fti=el('input',{placeholder:'work item type (Task, Bug…)',
      'aria-label':'work item type this template is for'}),
    fni=el('input',{placeholder:'ADO field (Activity or Microsoft.VSTS.Common.Activity)',
      'aria-label':'ADO field reference or display name'}),
    fvi=el('input',{placeholder:'literal value',
      'aria-label':'literal value written to that field'});
  fdWrap.append(el('div',{class:'row'},fti,fni,fvi,
    el('button',{class:'btn small',type:'button','data-fdadd':'1',
      onclick:()=>{const t=fti.value.trim(),n=fni.value.trim(),v=fvi.value.trim();
       if(!t||!n||!v)return;
       adoFieldSet(A().fields=A().fields||{},t,n,adoFieldValue(v));
       fti.value='';fni.value='';fvi.value='';fdDraw();}},'add')));
  // WHAT IS LEGAL IS NOT DECIDED HERE. `_ado_fields` holds both tables — the
  // fields the connector itself maps and the fields ADO reports read-only — and
  // a copy of either in the browser would be a second list free to disagree with
  // the one the save is graded against. So the card says where the answer comes
  // from and lets the save name the field.
  fdWrap.append(el('div',{class:'mut small','data-fdnote':'1'},
    'Literals only — no substitutions: a value that looks like a placeholder is '
    +'written to the board as those characters. A field the connector already '
    +'maps (title, state, area, iteration, tags) or one ADO reports as '
    +'read-only is refused when the manifest is validated, and the save names '
    +'which.'));};
 fdDraw();
 card.append(el('div',{class:'f','data-adosetting':'fields'},
   flabel('Field template (work item type → field → value)',
     MDESC.adoFields),fdWrap));
 // --- save / discard. EDITS.ado feeds beforeunload and the disk-refresh
 // dirtiness check; the buttons listen on the CARD directly — re-registering
 // the comp view's shared updater from here would abort the composition
 // form's own listener.
 EDITS.ado=()=>adoRows(saved,ADRAFT);
 const save=el('button',{class:'btn primary','data-save':'ado',onclick:async()=>{
   const rows=await confirmSave({rows:()=>adoRows(saved,ADRAFT),
     title:'Save ADO connector',scope:'comp',empty:'no values changed',
     note:'writes '+STATE.manifestPath});
   if(!rows)return;
   const res=await api('PUT','/api/ado',{ado:ADRAFT});
   if(!res.ok){
    card.querySelector('.findings-slot').replaceChildren(findingsBox(res));
    saveOutcome(res,rows,'the manifest',null);return;}
   STATE=await api('GET','/api/state');renderComp();renderOver();
   showWriteResult('#adocard',res,rows,'the manifest');}},'Save ADO connector');
 const discard=discardButton({key:'ado',rows:()=>adoRows(saved,ADRAFT),
   title:'Discard unsaved connector edits',
   note:'nothing is written; the card goes back to the saved manifest',
   toast:'discarded — the card is back to the saved manifest',
   revert:renderComp});
 const upd=()=>refreshDiscard(discard,adoRows(saved,ADRAFT).length);
 ['input','change','click'].forEach(e=>
  card.addEventListener(e,()=>requestAnimationFrame(upd)));
 upd();
 card.append(el('div',{class:'row',style:'margin-top:.9rem'},save,discard),
   el('div',{class:'findings-slot'}));
 c.append(card);}
// --- grouped manifest findings ---------------------------------------------------
// One malformed manifest can emit a finding PER phase, per task and per indexed
// file: a 300-phase repo produced 1009 of them, joined into a single paragraph
// that filled the screen and told the reader nothing. But 1009 findings are not
// 1009 problems — they were four mistakes repeated. So group by shape, count each,
// show one real example, and keep the raw list one click away.
//
// FGROUP_MIN is the length below which grouping is not worth it and the findings
// are simply listed; FSHOW caps the groups on display; FRAW caps the unfolded raw
// list, which points at the validator for the rest rather than pretending to be
// complete.
const FGROUP_MIN=6, FSHOW=6, FRAW=200;
/**
 * The SHAPE of a finding, with everything specific to one occurrence removed.
 *
 * Two findings that differ only in which id, path or number they name are one
 * mistake repeated, so the grouping key has to ignore exactly those parts: the
 * "where" prefix ahead of the first colon goes, quoted and bracketed values
 * become a placeholder, and every run of digits becomes one character. What is
 * left is the sentence the validator wrote.
 *
 * @param {string} s - one finding, as the validator phrased it
 * @returns {string} the grouping key; two findings with the same key are the same
 *   mistake in different places
 */
function findingKind(s){
 const i=s.indexOf(': ');
 return (i>0?s.slice(i+2):s)
  .replace(/'[^']*'/g,"'*'").replace(/\[[^\]]*\]/g,'[*]').replace(/\d+/g,'#');}
// Named for the manifest specifically: findingsBox() already exists above for
// save-result feedback, and a second function of the same name would hoist over it
// and break every config save.
/**
 * The manifest's validation findings, grouped by shape.
 *
 * A short list is not grouped at all — below the threshold, grouping costs the
 * reader more than it saves. Above it, the groups are ordered by how many
 * findings they hold, each shows one real example, and the raw list stays one
 * click away so that nothing here is only a summary.
 *
 * @param {number} n - the number of findings the validator reported. Deliberately
 *   NOT `list.length`: the count comes from the validation result and the list
 *   from the state payload, so a list that was truncated or has gone stale cannot
 *   quietly reduce the number of problems the header claims
 * @param {string[]} list - the findings themselves, as far as they were shipped
 * @returns {HTMLDivElement} the box: the count, the grouped shapes with an
 *   example each, and a <details> holding the raw list up to its own cap
 */
function manifestFindingsBox(n,list){
 const box=el('div',{class:'findings err'},
   el('b',{},'✗ '+plural(n,'finding')));
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

