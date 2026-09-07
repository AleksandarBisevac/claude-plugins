// --- the branch-naming card (meta.branch; rides the Composition form's save) -----
// A card inside the Composition tab, and unlike the ADO connector it does NOT own
// an endpoint: `branch` is a composition FORM key (`_panel_settings._META_KEYS`
// minus `_META_API_ONLY`), so its edits ride the same draft, the same confirm
// dialog and the same PUT /api/composition as reviewSkill and buildCommands. The
// server prints its rows dotted (`branch.defaultType feature -> bugfix`) through
// `_nested_meta_rows`, the same helper meta.ado uses.
//
// THE EXAMPLE IS NOT COMPUTED HERE. `comp.branchInfo.example` arrives from Python,
// where `_branch.expand` lives. A live preview updating as the operator types
// would be a second implementation of a separator rule whose whole point is that
// it has cases — and the first time the two disagreed, the branch git actually got
// would be the one nobody previewed. So the card shows what the SAVED settings
// produce and the save re-renders it, which is a smaller promise honestly kept.
/**
 * The Branch naming card.
 *
 * @param {object} comp - STATE.composition; reads `meta.branch` (the saved value)
 *   and `branchInfo` (how it currently resolves, plus the worked example)
 * @param {object} patch - the Composition form's draft; this card writes
 *   `patch.meta.branch`, and deleting every key writes null — "use the default"
 * @returns {HTMLDivElement} the card, for the caller to place
 */
function branchCard(comp,patch){
 const info=comp.branchInfo||{},saved=(comp.meta||{}).branch??null;
 let draft=saved===null?null:JSON.parse(JSON.stringify(saved));
 const card=el('div',{class:'card',id:'branchcard'});
 card.append(h2h('Branch naming (meta.branch)',MDESC.branchConvention,
   {comp:'branchConvention',label:'Branch naming'}));

 // The banner describes the FILE as saved, never the draft — the same rule the
 // ADO card's banner follows. Saying which KEY decided it matters because
 // meta.branch and meta.branchPrefix give different names from one manifest.
 const bstate=info.violations&&info.violations.length?'bad'
   :(info.basis==='meta.branch'?'set':'default');
 const bmsg=bstate==='bad'
  ?('The saved template produces a name git will reject: '
    +(info.violations||[]).join('; '))
  :(saved===null
    ?('No convention set — names come from '+(info.basis||'the default')+'.')
    :('In force: '+(info.basis||'meta.branch')+'.'));
 card.append(el('div',{class:'findings '+(bstate==='bad'?'err':(bstate==='set'?'ok':'warn')),
   'data-branchstate':bstate},bmsg));

 // The worked example, from Python. Labelled with the phase it was built from, so
 // a reader can tell "this is your plan" from "this is a stand-in".
 const ex=el('div',{class:'row',id:'branchexample'});
 // ALL THREE OR NONE. `_panel_composition.py` builds `example`, `exampleFrom`
 // and `exampleInitials` in one return, and it already labels the stand-in phase
 // as "(no phase in the plan yet)" rather than dressing it up. So the `||`
 // fallbacks that used to sit here could only fire when there was no branchInfo
 // AT ALL - and what they printed was `from phase ?, initials from ""`: a
 // question mark and an empty string rendered as though they were an example.
 // When the basis is missing that is the thing to say, not a gap to fill.
 ex.append(el('span',{class:'filtlbl'},'example:'));
 if(info.example){
  ex.append(el('code',{},info.example),
    el('span',{class:'muted'},' from phase '+info.exampleFrom
      +', initials from "'+info.exampleInitials+'"'));
 }else{
  ex.append(el('span',{class:'muted'},
    'none — a name is built from the plan, and there is no plan to read.'));
 }
 card.append(ex);

 // --- draft plumbing. Deleting a key is how "use the default" is written; an
 // emptied draft reads as null, which restores the meta.branchPrefix shape.
 const D=()=>(draft=draft||{});
 const prune=()=>{if(draft&&!Object.keys(draft).length)draft=null;
   patch.meta.branch=draft;};
 const set=(k,v)=>{if(v===''||v===null||v===undefined){if(draft)delete draft[k];}
   else{D()[k]=v;}prune();};

 const row=(label,helpKey,control)=>{
  card.append(h2h(label,MDESC[helpKey],{comp:helpKey,label:label}));
  card.append(el('div',{class:'row'},control));};

 const tmpl=el('input',{'data-branchfield':'template',
   'aria-label':'branch name template',placeholder:info.template||'{type}/{phase}-{slug}',
   value:(draft&&draft.template)||''});
 tmpl.oninput=()=>set('template',tmpl.value.trim());
 row('Template','branchTemplate',tmpl);

 const dt=el('input',{'data-branchfield':'defaultType',
   'aria-label':'default branch type',placeholder:info.defaultType||'feature',
   value:(draft&&draft.defaultType)||''});
 dt.oninput=()=>set('defaultType',dt.value.trim());
 row('Default type','branchDefaultType',dt);

 // The type list doubles as the pre-approved-glob list, which is why each chip
 // carries what its type is FOR: the panel is where someone learns the
 // convention, and a bare list of eight words teaches nothing.
 const help=info.typeHelp||{};
 // Hoisted rather than written inline: `listEditor`'s accessible name is its
 // FIFTH argument, and a multi-line arrow in the fourth pushes it off the call
 // site where `fl6` (and a reader) look for it.
 const typeHint=v=>help[v]?null:('no description — this type is outside the '
   +'documented set, which is fine, but nobody reading the panel will learn '
   +'what it means');
 row('Types','branchTypes',
   listEditor(()=>(draft&&draft.types)||info.types||[],
     a=>set('types',a.length?a:null),'add a type…',typeHint,'add a branch type'));
 const legend=el('div',{class:'muted',id:'branchtypehelp'});
 Object.keys(help).forEach(k=>legend.append(
   el('div',{},el('code',{},k),' — '+help[k])));
 if(Object.keys(help).length)card.append(legend);

 const ini=el('input',{'data-branchfield':'initials',
   'aria-label':'initials override',placeholder:'from git user.name',
   value:(draft&&draft.initials)||''});
 ini.oninput=()=>set('initials',ini.value.trim());
 row('Initials','branchInitials',ini);

 const slug=el('input',{type:'number',min:'1','data-branchfield':'slugMaxLength',
   'aria-label':'slug maximum length',placeholder:String(info.slugMaxLength||30),
   value:(draft&&draft.slugMaxLength)||''});
 slug.oninput=()=>{const n=parseInt(slug.value,10);
   set('slugMaxLength',Number.isFinite(n)&&n>0?n:null);};
 row('Slug maximum length','branchSlugMax',slug);

 // --- where it lands, and what happens once it has -------------------------
 // `developmentBranch` and `merge` are composition FORM keys like `branch`, so
 // they ride the same draft, the same confirm dialog and the same PUT. The merge
 // TARGET was reachable only by hand-editing the manifest until now, which is the
 // same gap F187 recorded for meta.areas: a lever every reader of a sign-off
 // report depends on, and nothing to set it with.
 const dev=el('input',{'data-branchfield':'developmentBranch',
   'aria-label':'development branch',
   placeholder:info.developmentBranch||'main',
   value:(comp.meta||{}).developmentBranch||''});
 dev.oninput=()=>{const v=dev.value.trim();
   if(v)patch.meta.developmentBranch=v;else delete patch.meta.developmentBranch;};
 row('Merge target (meta.developmentBranch)','developmentBranch',dev);

 // ABSENT READS AS ON, per key. The checkbox deletes the key when it agrees with
 // the default and writes `false` otherwise, which is the same grammar the guards
 // form uses — a round trip through this card leaves the file as it found it.
 const pol=(comp.meta||{}).merge||null;
 let mdraft=pol===null?null:JSON.parse(JSON.stringify(pol));
 const mprune=()=>{if(mdraft&&!Object.keys(mdraft).length)mdraft=null;
   patch.meta.merge=mdraft;};
 const sw=(key,lbl,helpKey)=>{
  const id='merge-'+key;
  const cb=el('input',{type:'checkbox',id:id,'data-mergeswitch':key});
  cb.checked=!mdraft||mdraft[key]!==false;
  cb.onchange=()=>{if(cb.checked){if(mdraft)delete mdraft[key];}
   else{(mdraft=mdraft||{})[key]=false;}mprune();};
  return el('span',{class:'f cbf'},cb,klabel(lbl,'meta.merge.'+key,
    MDESC[helpKey],id));};
 card.append(h2h('After sign-off (meta.merge)',MDESC.mergePolicy,
   {comp:'mergePolicy',label:'After sign-off'}));
 card.append(el('div',{class:'row'},
   sw('auto','Merge the phase branch','mergeAuto'),
   sw('removeWorktree','Remove its worktree','mergeRemoveWorktree'),
   sw('deleteBranch','Delete the branch','mergeDeleteBranch')));
 // The RESOLVED policy, from Python, with the key that decided each half — the
 // same rule the banner above follows: this describes the file, not the draft.
 const mp=info.mergePolicy||{};
 if(mp.autoBasis){
  card.append(el('div',{class:'muted',id:'mergebasis'},
    'in force: auto '+(mp.auto?'on':'off')+' ('+mp.autoBasis+') · worktree '
    +(mp.removeWorktree?'removed':'kept')+' ('+mp.removeWorktreeBasis+') · branch '
    +(mp.deleteBranch?'deleted':'kept')+' ('+mp.deleteBranchBasis+')'));}
 if(mp.auto===false){
  card.append(el('div',{class:'findings warn',id:'mergeauto-off'},
    'Automatic merging is OFF. Sign-off still reviews, gates and commits the '
    +'phase — it stops before the merge and prints the command. That is a '
    +'success, not a failure, and nothing stamps mergedAt.'));}

 card.append(worktreePanel());
 return card;}

// --- the live worktree table, and the one button that removes anything --------
// LAZY, and behind its own endpoint: the table asks git once for the list and
// twice more per worktree, so it is not on the Composition payload every save
// re-renders. The button is the panel's FIRST git write; everything that makes it
// safe is borrowed rather than invented — the same confirm dialog a config save
// uses, the same manifest lock, the same journal row.
/**
 * The Worktrees sub-card: a table of what git holds, and a read-only sweep.
 *
 * @returns {HTMLDivElement} the section, empty until `/api/worktrees` answers
 */
function worktreePanel(){
 const box=el('div',{id:'worktreepanel'});
 box.append(h2h('Worktrees',MDESC.worktreeTable,
   {comp:'worktreeTable',label:'Worktrees'}));
 const body=el('div',{id:'worktreerows'},el('div',{class:'muted'},'loading…'));
 box.append(body);
 const out=el('div',{id:'worktreeout'});

 const paint=st=>{
  body.replaceChildren();
  if(st.error){body.append(el('div',{class:'findings err'},st.error));return;}
  if(!st.rows.length){
   // NOT "everything is clean": there was nothing to be clean. The two states
   // are worded apart here for the same reason they are in the CLI.
   body.append(el('div',{class:'muted'},
     'no linked worktree exists, so there is nothing to sweep'));return;}
  // `tableHead` and not a hand-rolled header row: it emits <thead> with scoped
  // <th>, which is what SC 1.3.1 asks for and what the page's own census looks
  // for. A row of bare <th> passes a reader's eye and fails a screen reader's.
  const t=el('table',{class:'wt'},
    tableHead(['phase','branch','lands in','state','path']));
  // THE FIRST TWO REASONS ARE ABOUT PERMISSION, NOT SAFETY, and they are reported
  // first for the same reason the refusals order them that way: told "not landed",
  // a reader merges — and comes back to a refusal they still cannot act on, because
  // whose worktree it is was never going to change.
  st.rows.forEach(r=>{
   const state=!r.ours?'not the plugin’s'
     :(!r.settled?'phase not signed off'
     :(r.contained==='contained'
       ?(r.dirty?'landed, tree dirty':(r.locked?'landed, locked':'landed'))
       :(r.contained==='unknown'?'could not compare':'not landed')));
   t.append(el('tr',{'data-wt':r.branch||'',
     'data-ours':String(!!r.ours),'data-settled':String(!!r.settled),
     'data-sweepable':String(!!r.sweepable)},
     el('td',{},r.phaseId||'—'),
     el('td',{},el('code',{},r.branch||'(detached)')),
     el('td',{},r.parent+(r.parentIsGuess?' (guess)':'')),
     el('td',{class:r.sweepable?'ok':'muted'},state),
     el('td',{class:'muted'},r.path)));});
  body.append(t);
  const ready=st.rows.filter(r=>r.sweepable).length;
  const foreign=st.rows.filter(r=>!r.ours).length;
  body.append(el('div',{class:'muted',id:'wtcount'},
    ready+' of '+st.rows.length+' could be swept. A worktree is reaped only when '
    +'the plugin CREATED it, its phase has signed off with no task left open, its '
    +'branch has landed and its tree is clean. Removal also destroys ignored files '
    +'(.env, node_modules) that git status never mentions.'));
  if(foreign)body.append(el('div',{class:'findings warn',id:'wtforeign'},
    foreign+' of these were not created by this plugin, so nothing here will '
    +'remove them. Take one down by hand when you want it gone: '
    +'/audit:worktree remove --path <dir>'));};

 // There was an "include worktrees this plan does not name" checkbox here. It is
 // gone with the flag behind it: the panel is the surface with the button on it, so
 // it is the last place that should be able to adopt a worktree the plugin did not
 // create. A foreign worktree is shown in the table, marked, and removed by hand.
 const verbWt=el('input',{type:'checkbox',id:'wt-rm',checked:true});
 const verbBr=el('input',{type:'checkbox',id:'wt-br',checked:true});
 // `btn primary` for the ADO card's Save reason: it is this card's one action, and
 // it is a SHAPE the target-size census has already measured. Its destructiveness
 // is carried by the confirm dialog's note, not by an unmeasured button class.
 const sweep=el('button',{class:'btn primary','data-sweep':'worktrees',
   onclick:async()=>{
   const body_={removeWorktrees:verbWt.checked,deleteBranches:verbBr.checked};
   // DRY RUN FIRST, ALWAYS. The rows the server would act on are what the confirm
   // dialog shows; a button that asked for confirmation of its own guess would be
   // confirming something other than what runs.
   const pre=await api('POST','/api/worktrees/sweep',body_);
   if(!pre.ok){out.replaceChildren(findingsBox(pre));return;}
   // THE EMPTY STATE HAS TWO CAUSES AND THEY ARE DIFFERENT NEWS. "Every worktree
   // is unlanded or dirty" describes the repository; "you unticked both boxes"
   // describes the form, and the operator's next move is not the same one. The
   // server no longer infers both verbs from an empty set, so this is reachable.
   const noVerb=!verbWt.checked&&!verbBr.checked;
   const rows=await confirmSave({rows:()=>pre.applied,
     title:'Sweep worktrees',scope:'comp',
     empty:noVerb?'nothing selected — tick “Remove worktrees” or '
       +'“Delete branches” to say what a sweep should do'
       :'nothing to sweep — every worktree is either not created by this plugin, '
       +'not signed off, unlanded, or dirty',
     note:'removes directories and deletes branches — this is not undoable'});
   if(!rows)return;
   const res=await api('POST','/api/worktrees/sweep',
     Object.assign({apply:true},body_));
   out.replaceChildren(findingsBox(res));
   saveOutcome(res,rows,'the worktrees',out);
   paint(await api('GET','/api/worktrees'));}},'Sweep…');
 box.append(el('div',{class:'row'},
   el('span',{class:'f cbf'},verbWt,klabel('Remove worktrees','sweep.removeWorktrees',
     MDESC.mergeRemoveWorktree,'wt-rm')),
   el('span',{class:'f cbf'},verbBr,klabel('Delete branches','sweep.deleteBranches',
     MDESC.mergeDeleteBranch,'wt-br')),
   sweep));
 box.append(out);
 api('GET','/api/worktrees').then(paint).catch(e=>{
   body.replaceChildren(el('div',{class:'findings err'},
     'the worktree list could not be read: '+e));});
 return box;}
