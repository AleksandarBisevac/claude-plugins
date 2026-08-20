// ---------- Settings ----------
// The view id stays `guards`: it is the hash route (#/guards), the screenshot name
// and what several selftests pin. An internal id is an address, not a description —
// renaming it would break every link anyone already has for the sake of a word only
// this file ever sees.
// `name` is the add-box's accessible name, and it is a PARAMETER rather than
// something derived from `ph`. Three of the five call sites hand this editor to a
// caller that already wraps it in a <label class="f"> — an aria-label there would
// REPLACE "Paths the guards skip" with "add…", which is a worse name, not a
// missing one. So it is passed only by the two that stand on their own, and `el()`
// drops a null attribute, which is what makes leaving it off safe.
function listEditor(getArr,setArr,ph,validate,ariaName){const wrap=el('div',{class:'pill-in'});
 const draw=()=>{wrap.textContent='';(getArr()||[]).forEach((v,i)=>{
   const bad=validate?validate(v):null;
   wrap.append(el('span',{class:'chip'+(bad?' bad':''),title:bad||null},v,
     el('button',{'aria-label':'remove '+v,
       onclick:()=>{const a=getArr().slice();a.splice(i,1);setArr(a);draw();}},'×')));});
   const inp=el('input',{placeholder:ph||'add…','aria-label':ariaName||null});inp.addEventListener('keydown',e=>{
    if(e.key==='Enter'&&inp.value.trim()){const a=(getArr()||[]).slice();a.push(inp.value.trim());setArr(a);draw();}});
   wrap.append(inp);};draw();return wrap;}
// Does the browser's engine accept this pattern? A first pass only — the config is
// compiled by Python's `re` on save, and the two dialects are not the same, so this
// says "your browser rejects it", never "this is valid".
function reErr(src){if(!src)return null;
 try{new RegExp(src);return null;}catch(e){return String(e.message||e);}}
// Read/write a dotted config path. The form is described by path in Python, so the
// only alternative would be a getter and a setter per field, hand-written.
function getPath(o,p){let cur=o;for(const k of p.split('.')){
  if(cur==null||typeof cur!=='object')return undefined;cur=cur[k];}return cur;}
function setPath(o,p,v){const ks=p.split('.');let cur=o;
 for(const k of ks.slice(0,-1)){if(typeof cur[k]!=='object'||cur[k]===null)cur[k]={};cur=cur[k];}
 cur[ks[ks.length-1]]=v;}
// An empty field means "use the default", which is written by REMOVING the key, not
// by storing an empty string — a config listing every default is a config nobody can
// read, and it also freezes today's defaults into the file.
function delPath(o,p){const ks=p.split('.');let cur=o;
 for(const k of ks.slice(0,-1)){if(cur==null||typeof cur[k]!=='object'||cur[k]===null)return;cur=cur[k];}
 delete cur[ks[ks.length-1]];
 // Drop the container too if this emptied it, so removing the last usage override
 // does not leave `"usage": {}` behind.
 if(ks.length>1){const par=getPath(o,ks.slice(0,-1).join('.'));
  if(par&&typeof par==='object'&&!Object.keys(par).length)delPath(o,ks.slice(0,-1).join('.'));}}
const fieldId=p=>'set-'+p;
// Every "set X in audit.config.json" notice elsewhere in the panel comes here, to
// the field itself. A notice that names a setting and cannot reach it is a dead end
// on the one surface built to edit that setting.
function gotoSetting(path){showTab('guards');
 requestAnimationFrame(()=>{const t=document.getElementById(fieldId(path));
  if(!t)return;t.scrollIntoView({block:'center',behavior:'auto'});
  try{t.focus({preventScroll:true});}catch(e){}
  t.classList.add('flash');setTimeout(()=>t.classList.remove('flash'),1600);});}
function settingsLink(text,path){
 return el('button',{class:'lnk',type:'button',onclick:()=>gotoSetting(path)},text);}

function renderSettings(){closeCombo();
 // This form is rebuilt wholesale, same as #policy and #over, so it owes the same
 // hand-back. MEASURED before it was written: with the caret resting in
 // #set-manifestPath at offset 1 and nothing typed, one refreshFromDisk moved it
 // to <body> — the form is CLEAN when nothing was typed, so the 5s poll re-renders
 // it. And after a confirmed Save the caret came back to the Save button at 574ms
 // and was taken off it again by the poll's re-render at 4144ms. No id special
 // case here: focusKeep carries the selection offsets, so a path being edited
 // comes back at the character it was left at.
 const keepBack=focusKeep('#guards');
 const c=$('#guards');c.textContent='';
 const cfg=JSON.parse(JSON.stringify(STATE.config||{})),d=STATE.defaults;
 const findings=el('div',{class:'findings-slot'});
 // What this form would change, against the config the server last served. Read by
 // Save (to list it), by Discard (to say what is being thrown away) and by
 // beforeunload (to decide whether it may interrupt at all).
 EDITS.guards=()=>configChanges(cfg);
 // One `cfg`, one Save: the four cards are one FILE, and saving a quarter of a
 // document is not a thing this API can do.
 // `data-save` is the hand-back's hook, the pair of `data-discard`: focusSel names
 // an element by its id or by its data- attributes, and a savebar Save carried
 // NEITHER — so the caret that a confirm dialog gave back to it had no way home
 // across the re-render that followed. #policy and the theme card already had
 // data-psave and data-thsave; these three are the ones that did not.
 const save=el('button',{class:'btn primary','data-save':'guards',onclick:async()=>{
   const rows=configChanges(cfg);
   if(!rows.length){toast('nothing to save — no settings changed');return;}
   if(!await confirmChanges({title:'Save settings',rows,scope:'guards',
     verb:'Save '+rows.length+' change'+(rows.length===1?'':'s'),
     note:'writes .claude/audit.config.json'}))return;
   const res=await api('PUT','/api/config',cfg);
   findings.replaceChildren(findingsBox(res));
   saveOutcome(res,rows,'the config',findings);
   if(res.ok){STATE.config=JSON.parse(JSON.stringify(cfg));}}},'Save settings');
 // Enabled only when there is something to discard, and it says how much: a
 // control that throws work away must not be reachable by an idle click, and
 // "Discard" alone does not tell you whether pressing it costs you anything.
 const discard=el('button',{class:'btn small','data-discard':'guards',
   type:'button',onclick:async()=>{
   const rows=configChanges(cfg);
   if(!rows.length)return;
   if(!await confirmChanges({title:'Discard unsaved settings',rows,danger:1,
     lock:false,verb:'Discard '+rows.length+' change'+(rows.length===1?'':'s'),
     note:'nothing is written; the form goes back to the saved file'}))return;
   renderSettings();toast('discarded — the form is back to the saved file');}},
   'Discard');
 // Every control in this form mutates `cfg` and none of them announces it, so the
 // counter is refreshed from the events that reach the view rather than from a
 // hook added to each of the twenty-odd field builders.
 onViewEdit('guards',()=>{const n=configChanges(cfg).length;
   offState(discard,!n);
   discard.textContent=n?('Discard '+n+' change'+(n===1?'':'s')):'Discard';});
 const CUSTOM={
  'planGate':()=>planGateField(cfg),
  'guardEdits.tokenVars':()=>tokenVarsField(cfg,d),
  'secretPatterns.extra':()=>secretPatternsField(cfg),
  'guardEdits.customRules':()=>customRulesField(cfg),
  'usage.bands':()=>bandsField(cfg),
  'usage.pricing':()=>pricingField(cfg,d)};
 for(const grp of SETTINGS){
  const card=el('div',{class:'card',id:'setgrp-'+grp.id});
  card.append(h2h(grp.title,null,grp.topic?{topic:grp.topic}:null));
  if(grp.blurb)card.append(el('p',{class:'blurb'},grp.blurb));
  // Ordinary fields flow into a shared row; a custom one gets its own heading and
  // closes the row before it. The row is APPENDED and replaced, never cloned —
  // cloneNode copies the elements and drops every listener on them, which would
  // leave a form that looks complete and edits nothing.
  let inline=el('div',{class:'row'}),was=null;
  const flush=()=>{if(inline.childNodes.length){card.append(inline);
    inline=el('div',{class:'row'});}};
  for(const f of grp.fields){
   const tip=HELP[f.path];
   if(f.kind==='custom'){
    flush();was=null;
    card.append(el('h3',{class:'sub2'},klabel(f.label,f.path,tip)),CUSTOM[f.path]());
    continue;}
   // Switches and boxes wrap differently — a checkbox is as wide as its words, a
   // text field claims 15rem — so mixing them in one flex row leaves a ragged edge
   // that reads as an accident. They get their own rows.
   const kind=f.kind==='bool'?'bool':'input';
   if(was&&kind!==was)flush();
   was=kind;
   inline.append(kind==='bool'?boolField(cfg,d,f,tip):scalarField(cfg,d,f,tip));}
  flush();
  c.append(card);}
 // Sticky, because the form is now four cards long and a Save you have to go
 // looking for is a Save people forget to press.
 c.append(el('div',{class:'savebar'},save,discard,
   el('span',{class:'mut small'},'writes .claude/audit.config.json'),findings));
 focusBack(keepBack);}

function boolField(cfg,d,f,tip){
 const cur=getPath(cfg,f.path),def=getPath(d,f.path)!==false;
 const cb=el('input',{type:'checkbox',id:fieldId(f.path)});
 cb.checked=cur===undefined?def:cur!==false;
 cb.onchange=()=>{if(cb.checked===def)delPath(cfg,f.path);else setPath(cfg,f.path,cb.checked);};
 // The checkbox bound its label already -- it is the first labelable descendant,
 // ahead of the i. What it did NOT have was a clean name. Same shape as every
 // other field now: the control, then the words pointing at it by id.
 return el('div',{class:'f cbf'},cb,klabel(f.label,f.path,tip,fieldId(f.path)));}

function scalarField(cfg,d,f,tip){
 const cur=getPath(cfg,f.path),def=getPath(d,f.path);
 let inp;
 if(f.kind==='enum'){
  // Options come from the validator's own tuple — see _cfg_enums.
  inp=el('select',{id:fieldId(f.path)},
    el('option',{value:''},'default'+(def?' ('+def+')':'')),
    (ENUMS[f.enum]||[]).map(v=>el('option',Object.assign({value:v},
      v===cur?{selected:'selected'}:{}),v)));}
 else if(f.kind==='list'){
  // The id lands on the editor, not the label: it is what gotoSetting() scrolls to
  // and focuses, and a label is neither focusable nor the thing you came to edit.
  // Named here because listEditor's box cannot be named from inside it, and the
  // wrapping label is not an answer: MEASURED, a single chip's own "remove"
  // <button> becomes the label's first labelable descendant and the box's
  // `labels` drops 1 -> 0. A field that is labelled only while it is empty is not
  // labelled. The visible words are carried, so SC 2.5.3 holds with it.
  const ed=listEditor(()=>getPath(cfg,f.path)??def??[],a=>setPath(cfg,f.path,a),
    f.placeholder||'add…',null,f.label+': add');
  ed.id=fieldId(f.path);ed.tabIndex=-1;
  // No forId: the id is on the editor, which is a <div> and not labelable, so a
  // `for` pointing at it would associate nothing while looking as if it did. The
  // box inside it is named where it is built.
  return el('div',{class:'f wide'},klabel(f.label,f.path,tip),ed);}
 else{const t=f.kind==='date'?'date':(f.kind==='int'||f.kind==='number')?'number':'text';
  // The placeholder is the DEFAULT, so an empty box says what leaving it empty
  // gets you. Some defaults are null and mean something anyway ("beside the
  // manifest"), and an empty box beside an empty placeholder says nothing at all —
  // so a field may supply that sentence itself.
  inp=el('input',Object.assign({type:t,id:fieldId(f.path),value:cur??'',
    placeholder:def==null?(f.placeholder||''):String(def)},
    f.min!=null?{min:String(f.min)}:{}));}
 inp.oninput=inp.onchange=()=>{const v=inp.value;
  if(v===''){delPath(cfg,f.path);return;}
  if(f.kind==='int')setPath(cfg,f.path,parseInt(v,10));
  else if(f.kind==='number')setPath(cfg,f.path,Number(v));
  else setPath(cfg,f.path,v);};
 return el('div',{class:'f'},klabel(f.label,f.path,tip,fieldId(f.path)),inp);}

// The plan gate's tier, stated ONCE. The select's preset also reads the LEGACY
// `enforce` flag (true presets 'deny'), and any change writes planGate while
// deleting enforce — so a file that said the gate's tier twice leaves this form
// saying it once. The PUT sends the whole object, and _config_changes echoes
// BOTH writes at save time, honestly. Tier choices come from the validator's
// own tuple (ENUMS.planGate — see _cfg_enums), like every other enum here.
function planGateField(cfg){
 // Named from the <h3> the generic loop prints above it ("How hard the gate
 // pushes"). A heading is not a label and cannot become one without demoting it,
 // and aria-labelledby AT that heading would fold in the JSON key and the ⓘ
 // button's own name ("What is How hard the gate pushes?") — so the words are
 // repeated here instead. Same reasoning for every other control under a heading.
 const sel=el('select',{id:fieldId('planGate'),'aria-label':'How hard the gate pushes'},
   el('option',{value:''},'graded on evidence (default)'),
   (ENUMS.planGate||[]).map(v=>el('option',{value:v},v)));
 sel.value=cfg.planGate??(cfg.enforce===true?'deny':'');
 const cap=el('div',{class:'mut small'});
 const legacy=()=>{cap.textContent=
   (cfg.planGate===undefined&&cfg.enforce===true)
    ?'preset from the legacy enforce: true — saving rewrites it as planGate: "deny"'
    :(cfg.planGate===undefined&&typeof cfg.enforce==='boolean')
    ?'a legacy enforce key is in the file — any change here removes it'
    :'';};
 legacy();
 sel.onchange=()=>{const v=sel.value;
  if(v)setPath(cfg,'planGate',v);else delPath(cfg,'planGate');
  delPath(cfg,'enforce');legacy();};
 return el('div',{class:'f'},sel,cap);}

// The three defaults are ACTIVE while this list is empty, and vanish the moment it
// is not — `_config.token_vars` returns the configured list only when it is
// non-empty. An empty box that silently means "accessToken, refreshToken, idToken"
// and a one-entry box that silently means "only that one" look identical, so both
// states say which they are.
function tokenVarsField(cfg,d){
 const defs=d.guardEdits.tokenVars;
 const box=el('div',{id:fieldId('guardEdits.tokenVars'),tabindex:'-1'});
 const note=el('div');
 const cur=()=>{const v=getPath(cfg,'guardEdits.tokenVars');return Array.isArray(v)?v:[];};
 // Only the notice is redrawn. Rebuilding the list editor would take the caret out
 // of the box you are typing in, every time you add a name.
 const draw=()=>{note.textContent='';
  const list=cur();
  if(!list.length){
   note.append(el('div',{class:'ghost'},
     el('span',{class:'mut small'},'defaults are active:'),
     defs.map(v=>el('span',{class:'chip ghosted'},v))));return;}
  const missing=defs.filter(v=>!list.includes(v));
  if(missing.length)note.append(el('div',{class:'findings warn'},
    'Your list REPLACES the defaults — it does not add to them. Not covered any '
    +'more: '+missing.join(', ')+'. ',
    el('button',{class:'lnk',type:'button',onclick:()=>{
      const merged=[...missing,...cur()];setPath(cfg,'guardEdits.tokenVars',merged);
      redraw(merged);}},'put them back')));};
 let redraw=()=>{};
 const list=listEditor(cur,a=>{if(a.length)setPath(cfg,'guardEdits.tokenVars',a);
   else delPath(cfg,'guardEdits.tokenVars');draw();},'identifier…',null,
   'Secrets never written to logs: add an identifier');
 // The name has to be on the REPLACEMENT too. `redraw` swaps a whole new editor in
 // when the defaults notice changes, and an aria-label dropped there would be
 // invisible — the box looks the same and has stopped having a name.
 redraw=()=>{const fresh=listEditor(cur,a=>{
   if(a.length)setPath(cfg,'guardEdits.tokenVars',a);
   else delPath(cfg,'guardEdits.tokenVars');draw();},'identifier…',null,
   'Secrets never written to logs: add an identifier');
  list.replaceWith(fresh);draw();};
 box.append(list,note);draw();return box;}

function secretPatternsField(cfg){
 const box=el('div',{id:fieldId('secretPatterns.extra'),tabindex:'-1'});
 const cur=()=>{const v=getPath(cfg,'secretPatterns.extra');return Array.isArray(v)?v:[];};
 box.append(listEditor(cur,a=>{if(a.length)setPath(cfg,'secretPatterns.extra',a);
   else delPath(cfg,'secretPatterns.extra');},'regex…  e.g.  \\.env$',reErr,
   'Extra files treated as secrets: add a pattern'));
 box.append(el('p',{class:'blurb'},'Regexes, matched case-insensitively anywhere in '
  +'the path — so ".env" also matches secrets.envelope. Anchor it (\\.env$) when you '
  +'mean the file. A pattern your browser rejects is marked here; the save is '
  +'decided by Python’s engine, which is the one the hook uses.'));
 return box;}

function customRulesField(cfg){
 const wrap=el('div',{id:fieldId('guardEdits.customRules'),tabindex:'-1'});
 // The list is held here and written into `cfg` only when it has something in it.
 // It used to create `guardEdits.customRules: []` in the config the moment this
 // field RENDERED, so merely opening Settings on a project that had never set a
 // custom rule left an edit sitting in the form — invisible while a save wrote
 // whatever the form held, and, now that a save says what it is about to do, a
 // phantom row in the confirm dialog and a Discard button offering to throw away
 // a change nobody made.
 const cur=()=>{const v=getPath(cfg,'guardEdits.customRules');
  return Array.isArray(v)?v:[];};
 let arr=cur();
 const sync=()=>{if(arr.length)setPath(cfg,'guardEdits.customRules',arr);
  else delPath(cfg,'guardEdits.customRules');};
 const rules=()=>arr;
 const draw=()=>{wrap.textContent='';
  wrap.append(el('div',{class:'rule rulehead mut small'},
    el('span',{},'path contains'),el('span',{},'banned pattern (regex)'),
    el('span',{},'message shown when it fires'),el('span',{},'')));
  rules().forEach((r,i)=>{
   // `pathPrefix` is the key on disk and stays that, because configs in the field
   // already use it. The LABEL tells the truth about what it does: the hook tests
   // `prefix in path` against the path the tool reported, usually absolute.
   // Named by the column it sits under plus the row number. The `rulehead` row
   // above carries those three words visibly, but it is a header, not a label, and
   // it names three columns rather than one box — so the accessible name repeats
   // the column and adds the only thing that tells one row from the next.
   const pp=el('input',{value:r.pathPrefix||'',placeholder:'realtime/',
     'aria-label':'rule '+(i+1)+' path contains'});
   pp.oninput=()=>r.pathPrefix=pp.value;
   const bp=el('input',{value:r.bannedPattern||'',placeholder:'\\.removeAllListeners\\(',
     'aria-label':'rule '+(i+1)+' banned pattern (regex)'});
   const err=el('div',{class:'ferr'});
   const lint=()=>{const e=reErr(bp.value);bp.classList.toggle('bad',!!e);
     err.textContent=e?'your browser rejects this pattern: '+e:'';};
   bp.oninput=()=>{r.bannedPattern=bp.value;lint();};lint();
   const ms=el('input',{value:r.message||'',placeholder:'why this is banned here',
     'aria-label':'rule '+(i+1)+' message shown when it fires'});
   ms.oninput=()=>r.message=ms.value;
   wrap.append(el('div',{class:'rule'},pp,bp,ms,
     el('button',{class:'btn small','aria-label':'remove rule '+(i+1),
       onclick:()=>{arr.splice(i,1);sync();draw();}},'×')),err);});
  wrap.append(el('button',{class:'btn small',onclick:()=>{
    arr.push({pathPrefix:'',bannedPattern:'',message:''});sync();draw();}},'+ rule'));
  wrap.append(el('p',{class:'blurb'},'The path test is a SUBSTRING match, not a '
   +'prefix — "realtime/" fires under src/realtime/ and packages/web/src/realtime/ '
   +'alike. A rule missing either field, or whose pattern will not compile, is '
   +'skipped in silence when the hook runs; saving here refuses it instead.'));};
 draw();return wrap;}

// The same predicate usage_ledger.cost_bands applies: 0 < high <= outlier, and
// anything else falls back to the relative basis. Said here, next to the pair,
// because the fallback is silent everywhere else.
function bandsField(cfg){
 const box=el('div',{id:fieldId('usage.bands'),tabindex:'-1'});
 const row=el('div',{class:'row'}),warn=el('div');
 const mk=(key,lbl)=>{const p='usage.bands.'+key;
  const inp=el('input',{type:'number',min:'0',step:'0.01',id:fieldId(p),
    value:getPath(cfg,p)??'',placeholder:'not set'});
  inp.oninput=()=>{if(inp.value==='')delPath(cfg,p);else setPath(cfg,p,Number(inp.value));lint();};
  return el('div',{class:'f'},klabel(lbl,p,null,fieldId(p)),inp);};
 const lint=()=>{const hi=getPath(cfg,'usage.bands.highUSD'),
   ou=getPath(cfg,'usage.bands.outlierUSD');
  warn.textContent='';
  if(hi==null&&ou==null){warn.append(el('div',{class:'findings ok'},
    'Both empty: bands calibrate from this project’s own completed tasks '
    +'(median and p90), once there are five of them.'));return;}
  if(hi==null||ou==null){warn.append(el('div',{class:'findings warn'},
    'Set BOTH or neither — one threshold alone is ignored and the bands fall back '
    +'to the project-relative basis.'));return;}
  if(!(hi>0&&hi<=ou))warn.append(el('div',{class:'findings warn'},
    'high must be above 0 and no greater than outlier. As written this pair is '
    +'ignored at runtime and the bands fall back to the project-relative basis — '
    +'silently, which is why it is said here.'));};
 row.append(mk('highUSD','high above'),mk('outlierUSD','outlier above'));
 box.append(row,warn);lint();
 return box;}

function pricingField(cfg,d){
 const wrap=el('div',{id:fieldId('usage.pricing'),tabindex:'-1'});
 const COLS=[['in','input'],['out','output'],['cacheW5m','cache w 5m'],
   ['cacheW1h','cache w 1h'],['cacheR','cache read']];
 const cur=()=>{const v=getPath(cfg,'usage.pricing');
  return (v&&typeof v==='object'&&!Array.isArray(v))?v:{};};
 const draw=()=>{wrap.textContent='';
  const over=cur(),models=[...new Set([...Object.keys(d.usage.pricing),...Object.keys(over)])].sort();
  const tbl=el('table',{class:'ptbl'},el('thead',{},el('tr',{},
    el('th',{},'model'),COLS.map(([,l])=>el('th',{class:'n'},l)),el('th',{}))));
  const tb=el('tbody');
  models.forEach(m=>{
   const def=(d.usage.pricing||{})[m]||{},row=over[m]||{};
   const tds=COLS.map(([k])=>{
    const inp=el('input',{type:'number',min:'0',step:'0.01',value:row[k]??'',
      placeholder:def[k]==null?'—':String(def[k]),'aria-label':m+' '+k});
    inp.oninput=()=>{const o=cur();
     if(inp.value===''){if(o[m])delete o[m][k];}
     else{o[m]=o[m]||{};o[m][k]=Number(inp.value);}
     if(o[m]&&!Object.keys(o[m]).length)delete o[m];
     if(Object.keys(o).length)setPath(cfg,'usage.pricing',o);
     else delPath(cfg,'usage.pricing');};
    return el('td',{class:'n'},inp);});
   tb.append(el('tr',{},el('td',{class:'mono'},m),tds,
     el('td',{},over[m]?el('button',{class:'btn small','aria-label':'reset '+m,
       title:'drop this override and use the shipped rate',
       onclick:()=>{const o=cur();delete o[m];
        if(Object.keys(o).length)setPath(cfg,'usage.pricing',o);
        else delPath(cfg,'usage.pricing');draw();}},'reset'):null)));});
  tbl.append(tb);wrap.append(el('div',{class:'ptblwrap'},tbl));
  const add=el('input',{placeholder:'add a model id…',
    'aria-label':'Rates per million tokens: add a model id'});
  const addModel=v=>{const o=cur();o[v]=o[v]||{};
   setPath(cfg,'usage.pricing',o);add.value='';draw();};
  add.addEventListener('keydown',e=>{if(e.key!=='Enter'||!add.value.trim())return;
   addModel(add.value.trim());});
  // close() BEFORE addModel: draw() rebuilds this whole box, menu included.
  wrap.append(el('div',{class:'row'},comboWrap(add,modelItems,(name,close)=>{
   close();addModel(name);})));
  wrap.append(el('p',{class:'blurb'},'Empty means the shipped rate shown in the box, '
   +'so only what you change is written. An unrecognised model id falls back to the '
   +'longest matching prefix and then to _default, which is priced at the top tier '
   +'on purpose: over-stating spend is the safer error for a cost display.'));};
 draw();return wrap;}
