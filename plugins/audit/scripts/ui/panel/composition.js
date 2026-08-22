// ---------- Composition ----------
/**
 * One phase row of the composition payload, flattened by `_composition_view`.
 *
 * @typedef {object} CompPhase
 * @property {string|null} id
 * @property {string|null} title
 * @property {string|null} status - a manifest phase status: pending, in_progress,
 *   blocked or done
 * @property {string|null} reviewModel - lifted out of the phase's review object,
 *   which is the only part of it this tab edits
 * @property {string[]} area - the phase's area tags
 * @property {string|null} reviewSkill
 * @property {number|null} priority - the tier as `_priority.tier_of` reads it, so
 *   a value the run does not honour never reaches a control. null is
 *   unprioritised, which is a class of its own rather than tier 0
 */

/**
 * One task row of the composition payload, in document order and carrying the id
 * of the phase that owns it.
 *
 * Four of these fields — risk, commit, startedAt and completedAt — are here for
 * the Overview rollup rather than for this tab, which ignores what it does not
 * edit. They ride this payload because it is the same manifest read either way.
 *
 * @typedef {object} CompTask
 * @property {string|null} id
 * @property {string|null} title
 * @property {string|null} phaseId
 * @property {string|null} status
 * @property {string|null} model
 * @property {string[]|null} skills - null is an ANSWER ("none applies"), not an
 *   absence, and it has to survive every accessor that touches it
 * @property {string|null} risk
 * @property {string|null} commit
 * @property {string|null} startedAt
 * @property {string|null} completedAt
 */

// ---------- model suggestions (mc) ----------
/**
 * A model id offered by the completion menus, and where it was seen.
 *
 * @typedef {object} ModelItem
 * @property {string} name - the model id, exactly as its source spells it
 * @property {'manifest'|'rates'|'ledger'} source - the most local source that
 *   knows it, which is what its badge shows
 * @property {string} description - what that source knows: how many rows route to
 *   it, what it costs, or how much it has metered
 */

/**
 * Memo for `modelItems`. Null means "not built yet", never "no models found" —
 * an empty union would be cached as an empty array.
 * @type {ModelItem[]|null}
 */
let MITEMS=null;
/**
 * Every model id worth offering, unioned from three sources and badged by which.
 *
 * One union, three sources, each named: the models the MANIFEST already routes
 * to, the ids the RATE TABLE prices, and what the LEDGER has actually metered.
 * The badge is the point — a model only one source spells is usually one slip
 * from its cousins, and the validator cannot arbitrate that, being an offline
 * shape-checker with no ledger and no config. So the cross-source view lives
 * here, on the one surface that can see all three.
 *
 * A name in several sources keeps its most local badge: manifest first, then
 * rates, then ledger. `_default` is not offered — it is the fallback price, not
 * a model anyone should route to by name.
 *
 * Cached, because a menu opens on a keystroke. The cache is dropped by hand
 * wherever STATE or USAGE may have moved under it — a save re-render, a disk
 * refresh — rather than expiring on a timer.
 *
 * @returns {ModelItem[]} manifest names first, then rate names, then ledger
 *   names, each group sorted and each name appearing once
 */
/**
 * The highest tier the phase-priority control offers.
 *
 * The project's `priority.maxTier` when it sets one, otherwise the DEFAULT the
 * server hands over in `STATE.defaults` — which is `hooks/_config.py`'s dict, the
 * one place the whole config's shape is stated. A literal here would be a second
 * copy of that setting, free to disagree with the validator and with
 * `set-priority.py` about what the panel is allowed to offer.
 *
 * It is a CEILING ON THE MENU, not on the value: nothing is clamped, so a phase
 * already pinned above it keeps its tier and the control offers that tier too.
 *
 * @returns {number} a positive integer; the shipped default when the config and
 *   the defaults block are both unusable, because a control with no range is a
 *   control that silently unpins every phase. That last-resort literal is the
 *   one value written twice in two languages, so the agreement is PINNED by a
 *   case against `hooks/_config.py` rather than asserted in this sentence
 */
function prioMax(){
 const cfg=((STATE||{}).config||{}).priority||{};
 const def=((STATE||{}).defaults||{}).priority||{};
 for(const v of [cfg.maxTier,def.maxTier])
  if(typeof v==='number'&&Number.isInteger(v)&&v>=1)return v;
 return 9;}

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
  if(useT[m])bits.push(plural(useT[m],'task'));
  if(useP[m])bits.push(plural(useP[m],'review'));
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
/**
 * Are two model ids one slip apart?
 *
 * One slip means case-insensitively equal but spelled differently, or one
 * substitution, insertion, deletion or ADJACENT transposition away — the four
 * classic typo shapes. The cap at one slip is a false-positive discipline: at two
 * edits one real name reaches another real name, and every hit would be noise.
 *
 * Identical strings are NOT a near miss. The caller is looking for a spelling
 * that disagrees with another spelling, and agreement is the normal case.
 *
 * Symmetric in its arguments, which the caller relies on by comparing each pair
 * in one direction only.
 *
 * The same predicate is `_model_near_miss` in `_manifest_typos.py`, which the
 * offline validator uses. It is spelled a second time here only because this half
 * runs in a browser — the two have to keep agreeing, or the panel and the
 * validator will reach different verdicts about one pair of names.
 *
 * @param {string} a - one model id
 * @param {string} b - the other model id
 * @returns {boolean} true when they are one slip apart
 */
function mdNear(a,b){if(a===b)return false;
 const x=a.toLowerCase(),y=b.toLowerCase();
 if(x===y)return true;
 if(Math.abs(x.length-y.length)>1)return false;
 if(x.length===y.length){const d=[];
  for(let i=0;i<x.length;i++)if(x[i]!==y[i])d.push(i);
  if(d.length===1)return true;
  return d.length===2&&d[1]===d[0]+1&&x[d[0]]===y[d[1]]&&x[d[1]]===y[d[0]];}
 const shorter=x.length<y.length,s=shorter?x:y,l=shorter?y:x;
 let i=0,j=0,used=false;
 while(i<s.length){if(s[i]===l[j]){i++;j++;continue;}
  if(used)return false;used=true;j++;}
 return true;}
/**
 * Models the manifest spells that nothing else knows, each with the name it is
 * one slip from.
 *
 * The three-source half of the typo check: a model the manifest routes to that
 * NO other source knows, sitting one slip from a name the rates or the ledger do
 * know. A name the rate table already prices is never flagged, however odd it
 * looks — being priced is the evidence that it is meant.
 *
 * Non-blocking by design. The panel cannot know which spelling was intended, only
 * that two sources disagree by one character, so this is a note and never a gate.
 *
 * @returns {{model: string, near: string}[]} sorted by the manifest spelling;
 *   `near` is the alphabetically first neighbour when a name is close to several
 */
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
/**
 * Skill names the manifest spells that the discovery scan has never seen.
 *
 * The inventory half of the skills story: a name the manifest spells — in a
 * task's skills, or in an area's defaults, which ride the composition payload for
 * exactly this — that the DISCOVERY scan does not know. Shaped like modelHints on
 * purpose: the same muted note, the same cap, a hint and never a gate.
 *
 * No near-miss requirement here, because the validator already runs the
 * intra-manifest typo check offline. What only the panel can see is the
 * INVENTORY — which names actually resolve on this machine.
 *
 * Silent when discovery found nothing at all. Against an empty inventory every
 * name would read as unknown, and the note would then be reporting a failed scan
 * while looking like a report about the manifest.
 *
 * @returns {string[]} sorted, and empty both when every spelled name resolves and
 *   when there was no inventory to judge against — the two are indistinguishable
 *   here on purpose, because neither is something to act on
 */
function skillHints(){
 if(!REG.skills||!REG.skills.length)return[];
 const known=new Set(REG.skills.map(s=>s.name));
 const comp=(STATE&&STATE.composition)||{tasks:[]};
 const spelled=new Set();
 (comp.tasks||[]).forEach(t=>{(Array.isArray(t.skills)?t.skills:[]).forEach(s=>spelled.add(s));});
 (comp.areaSkills||[]).forEach(s=>spelled.add(s));
 return [...spelled].sort().filter(n=>!known.has(n));}
/**
 * A one-skill box with a completion menu, for the settings that take a single
 * skill rather than a list.
 *
 * Reports every keystroke and not only a menu choice, because discovery is an
 * inventory rather than a whitelist: a name typed by hand is as legitimate as one
 * picked from the list, and a skill can be installed after this page was served.
 *
 * An empty box reports null rather than an empty string, so "no skill here" is
 * written as an absence and the key comes out of the manifest.
 *
 * @param {string|null|undefined} current - the saved value to start from
 * @param {(name: string|null) => void} onChange - handed the trimmed name, or
 *   null the moment the box is empty
 * @param {string} [ariaName] - accessible name for the box; the visible words
 *   beside it name a whole row, not this control
 * @returns {HTMLElement} the box inside its menu wrapper
 */
function skillPicker(current,onChange,ariaName,hook){
 // `hook` stamps a data- attribute so a caller can be REACHED by name. The
 // review-skill picker and the task adder both start their placeholder with
 // "search a skill", so a selector on that text plus `.first()` resolved by
 // document order - which held only while the config cards were above the table.
 // Putting the table first made the same selector land on an adder inside a
 // collapsed phase, and the browser gate spent its timeout on an invisible
 // control. A styling- or copy-based hook is a hook bound to a layout decision.
 const inp=el('input',{value:current??'',placeholder:'search a skill…  (empty = none)',
   'aria-label':ariaName||'search a skill'});
 if(hook)inp.setAttribute('data-skillpick',hook);
 inp.addEventListener('input',()=>onChange(inp.value.trim()||null));
 return comboWrap(inp,()=>REG.skills,(name,close)=>{inp.value=name;onChange(name);close();});}
/**
 * The three-state skill list for one task.
 *
 * A task's skills say one of three different things, and all three have to be
 * writable and to look different from each other: a list of chips; an EMPTY row,
 * carrying the "none applies" affordance that writes the explicit null; and the
 * opted-out state itself, which gets a muted chip saying so rather than an empty
 * row that looks merely unconsidered.
 *
 * Adding a skill while opted out replaces the null — that is "changed my mind".
 * Clearing the opt-out chip goes back to the empty list, which is unconsidered
 * again and not "no skills apply".
 *
 * The chip buttons prevent the default on mousedown, which stops the press from
 * pulling focus out of the add box; a focus change there closes the completion
 * menu, so the click would land on a box that had already moved.
 *
 * @param {() => string[]|null} getArr - reads the current value; null has to
 *   arrive intact, since it is the opt-out and not an absence
 * @param {(next: string[]|null) => void} setArr - hands back a new array, or null
 *   to opt out
 * @param {string} [ariaName] - accessible name for the add box; the callers fold
 *   the task id into it, because the column header names every one of these
 *   identically
 * @returns {HTMLDivElement} the chips above the add box
 */
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
/**
 * Composition's filter state, held OUT here rather than in renderComp's closure.
 *
 * Two reasons, and the second is the one that made it necessary: a re-render —
 * after a save, or a poll — used to drop you back to the unfiltered table; and
 * Overview needs to be able to hand this tab a phase to open.
 *
 * `apply` is published by renderComp so that a caller can change this state and
 * have the view on screen act on it WITHOUT being rebuilt. Rebuilding would throw
 * away whatever is half-typed in the composition form, which is the same mistake
 * the run-status poll was fixed for. It is null until renderComp has run once.
 *
 * @type {{q: string, status: string, needs: boolean,
 *   open: Object<string, boolean>, apply: (() => void)|null}}
 */
const COMPF={q:'',status:'',needs:false,open:{},apply:null};
/**
 * Open the Composition tab scoped to one phase.
 *
 * Overview's way in. The other filters are cleared rather than left alone,
 * because a status filter or a "needs skills" filter still standing from earlier
 * could hide the very phase this was asked to show — arriving at an empty table
 * is worse than arriving at an unfiltered one.
 *
 * The view is asked to act on the new state rather than being rebuilt, which is
 * what keeps a half-typed form alive across the jump.
 *
 * @param {string} pid - the phase id to search for and expand
 * @returns {void}
 */
function openInComp(pid){COMPF.q=pid;COMPF.status='';COMPF.needs=false;COMPF.open[pid]=true;
 if(COMPF.apply)COMPF.apply();showTab('comp');}
/**
 * Build the Composition tab: the manifest's routing levers, as one table.
 *
 * What this tab collects is a PATCH and never a document. Only the values that
 * were actually touched go into it, so a save sends the edits rather than a
 * rewritten manifest — which is what stops a field nobody opened from being
 * reformatted, reordered or normalised by a round trip through this form.
 *
 * The phases and their tasks share one collapsible table rather than a card each,
 * because everything here has to stay readable on a manifest with dozens of
 * phases. The filter state lives in COMPF so that it survives the re-render, and
 * this function republishes COMPF.apply on every build — the previous closure
 * refers to elements that have just been thrown away.
 *
 * A successful save re-renders from the state the server hands back rather than
 * from the patch. Without that the form kept showing the values that were typed
 * rather than the values on disk: indistinguishable while they agree, and
 * silently wrong the moment the server normalises one or refuses part of a patch.
 *
 * @returns {void} written into the #comp view. The manifest is untouched until
 *   Save is pressed and its confirm dialog is answered
 */
function renderComp(){closeCombo();
 // Rebuilt from FOUR places, which is one more than any other view: its own Save,
 // its Discard, the ADO card's Save and Discard, and the 5s disk poll. MEASURED:
 // after a confirmed Save the dialog handed the caret back to the Save button at
 // 676ms and this function took it away again at 682ms — six milliseconds, and no
 // poll involved, which is how this view differs from #policy. The caret in the
 // filter box was lost the same way on a refreshFromDisk, offset and all.
 const keepBack=focusKeep('#comp');
 const c=$('#comp');c.textContent='';const comp=STATE.composition;
 // NOTHING TO COMPOSE WITHOUT A PLAN. Every control below edits a `meta.*` key
 // of the manifest, so with none this view used to offer empty editors for an
 // object that does not exist - and the branch card, reading a `branchInfo` the
 // server never sent, printed a question mark and an empty string as its worked
 // example. Say it instead, in the shape Overview and Usage use. Settings stays
 // reachable and stays useful: `manifestPath` decides where the plan lands.
 if(!STATE.rollup){
  const none=el('div',{class:'card'});
  none.append(el('div',{class:'mut'},'Nothing to set here yet — these are all keys '
    +'of the plan, and there is no plan. "/audit:init" writes one.'),
   el('div',{class:'mut',style:'margin-top:var(--sp-0)'},
     'it would be written to: '+(STATE.manifestPath||'-'),' · ',
     settingsLink('change where it goes','manifestPath')));
  c.append(none);focusBack(keepBack);return;}
 MITEMS=null;   // STATE may have moved under us (save re-render, disk refresh)
 const patch={meta:{},phases:{},tasks:{}};
 const meta=el('div',{class:'card'});meta.append(h2h('Phase sign-off review skill (meta.reviewSkill)',MDESC.reviewSkill,
   {comp:'reviewSkill',label:'Phase sign-off review skill'}));
 meta.append(el('div',{class:'row'},skillPicker(comp.meta.reviewSkill,
   v=>patch.meta.reviewSkill=v,'Phase sign-off review skill','reviewSkill')));
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
 // HELD, not appended here. The table below is what this view is FOR - the
 // README calls it the tab's main function - and it used to open on three
 // config cards with the table under them. Construction order is untouched
 // (these still build first, and the table's closures still read `patch`);
 // only the insertion point moves, which is the change that cannot break a
 // build-order dependency.
 meta.append(bc);
 // meta.branch rides this same form and this same save, so its card is appended
 // as a sibling of the meta card rather than owning an endpoint the way the ADO
 // connector does. It writes patch.meta.branch and nothing else.
 const bcard=branchCard(comp,patch);
 // tasks: filter toolbar + ONE compact collapsible table (scales to 50x20)
 const tcard=el('div',{class:'card'});tcard.append(h2h('Phases · tasks · skills',MDESC.taskSkills,
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
   tableHead(['id','title','status',
     {label:flabel('model',MDESC.taskModel,{comp:'taskModel',label:'Task model'})},
     {label:flabel('skills',MDESC.taskSkills,{comp:'taskSkills',
       label:'Task skills'})}]),tbody)));

 const open=COMPF.open;
 const phaseEls=[];const byPhase={};comp.tasks.forEach(t=>{(byPhase[t.phaseId]=byPhase[t.phaseId]||[]).push(t);});
 comp.phases.forEach(ph=>{
  const tasks=byPhase[ph.id]||[];
  // The visible word beside this box is "review", and it is the same word beside
  // all fifty of them — a <label> here would name fifty controls identically,
  // which conforms and helps nobody. The name folds in the phase id and still
  // contains the visible word, so SC 2.5.3 Label in Name holds as well.
  // ONE patch object per phase, the shape the task rows already use. The old
  // spelling assigned a fresh `{reviewModel:…}` on every keystroke, which was
  // correct while a phase had exactly one control and silently DISCARDS the
  // other the moment it has two.
  const pp={};
  const rev=el('input',{value:ph.reviewModel??'','data-revmodel':ph.id||'',placeholder:'review model',
    'aria-label':'review model for phase '+(ph.id||'')});
  const setRev=v=>{pp.reviewModel=v||null;patch.phases[ph.id]=pp;};
  rev.oninput=()=>setRev(rev.value.trim());
  // Which phase the pipeline reaches for first AMONG THE WORK THAT IS ALREADY
  // READY. The range comes from the config (falling back to the shipped default
  // the server hands over), never from a literal here: a second copy of maxTier
  // in the browser is a second setting.
  const maxTier=prioMax();
  const prio=el('select',{'data-priority':ph.id||'',
    'aria-label':'priority for phase '+(ph.id||'')});
  prio.append(el('option',{value:''},'no priority'));
  for(let i=1;i<=maxTier;i++)prio.append(el('option',{value:String(i)},String(i)));
  // A tier ABOVE the maximum is still a real pin — nothing is clamped — so the
  // control offers it rather than silently resetting the phase to "no priority".
  if(ph.priority!=null&&ph.priority>maxTier)
   prio.append(el('option',{value:String(ph.priority)},String(ph.priority)));
  prio.value=ph.priority==null?'':String(ph.priority);
  prio.onchange=()=>{pp.priority=prio.value?Number(prio.value):null;
    patch.phases[ph.id]=pp;};
  // Same STOP as the review combo: the phase row toggles on click, and choosing
  // a tier must not also collapse the phase under the menu.
  prio.onclick=e=>e.stopPropagation();
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
      {comp:'phaseReviewModel',label:'Phase review model'}),revCombo),
    el('span',{class:'comp-priority'},flabel('priority',MDESC.phasePriority,
      {comp:'phasePriority',label:'Phase priority'}),prio))));
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
   const rows=await confirmSave({rows:()=>compChanges(patch),
     title:'Save plan & models',scope:'comp',empty:'no values changed',
     note:'writes '+STATE.manifestPath});
   if(!rows)return;
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
   showWriteResult('#comp',res,rows,'the manifest');}},'Save plan & models');
 const discard=discardButton({key:'comp',rows:()=>compChanges(patch),
   title:'Discard unsaved composition edits',
   note:'nothing is written; the table goes back to the saved manifest',
   toast:'discarded — the table is back to the saved manifest',
   revert:renderComp});
 onViewEdit('comp',()=>refreshDiscard(discard,compChanges(patch).length));
 // Out of the card and into the view's own savebar, for the reason moving the
 // table exposed: this Save writes the config cards too, and inside the table it
 // would have sat ABOVE the fields it saves. Settings and Policy both put one
 // Save for several cards in a `.savebar` at the foot of the view; this is that
 // same shape, not a fourth arrangement.
 const savebar=el('div',{class:'savebar'},save,discard,
   el('span',{class:'mut small'},'writes '+STATE.manifestPath),
   el('div',{class:'findings-slot'}));
 if(!STATE.manifestExists)tcard.append(el('div',{class:'findings warn'},'No manifest yet — run /audit:init first.'));
 if(STATE.manifestLocked)tcard.append(el('div',{class:'findings warn'},'Manifest is locked by a running /audit command.'));
 c.append(tcard,meta,bcard);
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
     tableHead(['name','source','description']),tb));};
 ['skills','agents','mcp'].forEach(k=>subtabs.append(el('button',{class:'subtab'+(k===cur?' on':''),
   onclick:e=>{cur=k;[...subtabs.children].forEach(x=>x.classList.toggle('on',x===e.currentTarget));drawTbl();}},
   k+' ('+(datasets[k]||[]).length+')')));
 drawTbl();bb.append(subtabs,host);c.append(bb,savebar);
 // Last, after renderAdoCard and the blocks table: a hand-back that runs before
 // the view is finished aims at a node the rest of the build then replaces.
 focusBack(keepBack);}

