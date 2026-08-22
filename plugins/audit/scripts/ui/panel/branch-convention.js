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

 return card;}
