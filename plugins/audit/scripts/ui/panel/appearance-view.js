function renderAppearance(){closeCombo();
 const c=$('#look');
 const act=document.activeElement,
   keepId=act&&act.id&&act.id.indexOf('th-')===0?act.id:null,
   caret=keepId&&act.setSelectionRange?act.selectionStart:0,
   keepBack=keepId?null:focusKeep('#look');
 c.textContent='';
 if(!THEME){c.append(el('div',{class:'card'},el('div',{class:'findings warn'},
   'The theme could not be read from this project.')));return;}
 const changes=tChanges().concat(tLayChanges());

 // --- the bar: where this look comes from, and what to do with it -----------
 const head=el('div',{class:'card'});
 head.append(h2h('Appearance',
   'The panel and the report share ONE token layer, and a theme edits its '
   +'values — never a rule. The stylesheet is compiled from those values when '
   +'a page is served and is never stored, so nothing here can reach a report '
   +'except a colour, a size or a font name.'));
 const src=THEME.source==='project'?('this project — '+(THEME.path||''))
   :THEME.source==='user'?'your ~/.claude theme'
   :THEME.source==='config'?('ui.theme → '+(THEME.path||''))
   :'the built-in Slate & Teal';
 head.append(el('p',{class:'mut','data-thsrc':THEME.source},'Wearing: '+src
   +'. A project theme lives in .claude/'+'audit.theme.json and travels with the '
   +'repo; without one, your ~/.claude theme applies; without that, the built-in.'));
 head.append(el('p',{class:'mut small','data-thlive':isDark()?'dark':'light'},
   'You are viewing '+(isDark()?'DARK':'LIGHT')+' — that column is what repaints '
   +'as you type. The other one is saved just the same and applies when the '
   +'theme toggle is flipped; both are on screen because a colour edited in one '
   +'theme and checked in the other is how a pair drifts.'));
 if(THEME.error)head.append(el('div',{class:'findings warn','data-therr':'1'},
   THEME.error));
 const bar=el('div',{class:'row'});
 const nch=changes.length;
 bar.append(el('span',{class:'pill'+(nch?' unsaved':''),'data-thcount':String(nch)},
   nch?(nch+' unsaved change'+(nch===1?'':'s')):'no changes'));
 // Which saved theme is worn, and Save-as beside it: a preset here is a FILE
 // somebody saved, so the menu lists what is on disk rather than a registry.
 const sel=el('select',{'aria-label':'which theme to wear','data-thpreset':'1',
   onchange:async()=>{
    const res=await api('PUT','/api/theme',{use:sel.value});
    THEME=await api('GET','/api/theme');TDRAFT=null;TLAY=null;TUNDO=[];TREDO=[];
    tPaint();tPaintLayout();renderAppearance();
    toast(res.ok?'wearing '+sel.value:'could not switch',res.ok?'':'err');}});
 (THEME.saved||[]).forEach(t=>{
  const v=t.builtin?'slate-teal':(t.path||t.name);
  const o=el('option',{value:v},t.name+(t.builtin?' (built-in)':''));
  const worn=THEME.source==='config'?THEME.path:(THEME.source==='default'?'slate-teal':null);
  if(worn&&(v===worn||v===String(worn).replace(/\\/g,'/')))o.selected=true;
  sel.append(o);});
 bar.append(el('span',{class:'filtlbl'},'theme:'),sel);
 bar.append(el('button',{class:'btn small',type:'button','data-thsaveas':'1',
   title:'keep this look under a name, and wear it',
   onclick:async()=>{
    const name=prompt('Save this theme as:','custom');
    if(!name||!name.trim())return;
    const lay=tLayout(),layPayload={};
    if(lay.density&&lay.density!=='comfortable')layPayload.density=lay.density;
    if(lay.order&&Object.keys(lay.order).length)layPayload.order=lay.order;
    const res=await api('PUT','/api/theme',{theme:tPayload(),layout:layPayload,
      saveAs:name.trim()});
    if(!res.ok){toast('could not save: '+(res.findings||[])[0],'err');return;}
    THEME=await api('GET','/api/theme');TDRAFT=null;TLAY=null;
    renderAppearance();toast('saved as '+name.trim());}},'Save as…'));
 // `disabled:false` would still DISABLE these: el() sets any non-null value as
 // an attribute, and `disabled="false"` is a disabled button in HTML. Present
 // or absent, never a boolean — a browser check caught this by finding no
 // clickable control where there plainly was one.
 bar.append(el('button',{class:'btn small',type:'button','data-thundo':'1',
   disabled:TUNDO.length?null:'',onclick:()=>tUndo(TUNDO,TREDO)},'Undo'));
 bar.append(el('button',{class:'btn small',type:'button','data-thredo':'1',
   disabled:TREDO.length?null:'',onclick:()=>tUndo(TREDO,TUNDO)},'Redo'));
 bar.append(el('button',{class:'btn small',type:'button','data-thexport':'json',
   title:'the theme as a file you can send someone (DTCG JSON)',
   onclick:()=>tExport('json')},'Export .json'));
 bar.append(el('button',{class:'btn small',type:'button','data-thexport':'css',
   title:'the compiled tokens, to read or paste elsewhere — never read back',
   onclick:()=>tExport('css')},'Export .css'));
 const imp=el('input',{type:'file',accept:'.json,application/json',
   style:'display:none','data-thimport':'1'});
 imp.addEventListener('change',()=>tImport(imp));
 bar.append(el('button',{class:'btn small',type:'button',
   title:'load a theme file someone sent you — validated token by token',
   onclick:()=>imp.click()},'Load a theme file…'),imp);
 head.append(bar,imp);
 c.append(head);

 // --- the groups ------------------------------------------------------------
 (THEME.groups||[]).forEach(g=>{
  const locked=(THEME.locked||[]).includes(g.key)&&!TUNLOCK;
  const card=el('div',{class:'card','data-thgroup':g.key});
  card.append(el('h2',{},g.title));
  if((THEME.locked||[]).includes(g.key)){
   card.append(el('p',{class:'blurb'},'This palette is validated for '
     +'colour-vision deficiency and for contrast against these very surfaces. '
     +'Changing it can make a chart two readers see differently — so it opens '
     +'deliberately, and the checks below keep reporting afterwards.'));
   card.append(el('div',{class:'row'},el('button',{class:'btn small',
     type:'button','data-thunlock':TUNLOCK?'on':'off',
     onclick:()=>{TUNLOCK=!TUNLOCK;renderAppearance();}},
     TUNLOCK?'Lock the chart palette':'Unlock the chart palette')));}
  if(!locked){
   // WHICH column is live, said out loud. The preview paints the mode the
   // reader is actually in, so a value typed into the other column changes
   // nothing on screen — correct, and baffling unless the table says so.
   const livemode=isDark()?'dark':'light';
   const tbl=el('table',{class:'thtbl'});
   tbl.append(el('thead',{},el('tr',{},el('th',{},'token'),
     el('th',{class:livemode==='light'?'thlive':'thoff'},'light',
       livemode==='light'?el('span',{class:'mut'},' · previewing'):null),
     el('th',{class:livemode==='dark'?'thlive':'thoff'},'dark',
       livemode==='dark'?el('span',{class:'mut'},' · previewing'):null),
     el('th',{}))));
   const tb=el('tbody');
   g.tokens.forEach(name=>{
    const row=el('tr',{'data-thtoken':name});
    row.append(el('td',{class:'mono thname'},name));
    TMODES.forEach(mode=>{
     if(mode==='dark'&&tSingle(name)){
      row.append(el('td',{class:'mut small'},'— same in both'));return;}
     const val=String(tVal(name,mode));
     const cell=el('td',{class:'thcell'});
     const hex=tHex(val);
     const text=el('input',{type:'text',id:'th-'+name.slice(2)+'-'+mode,
       value:val,'data-thval':name+'|'+mode,'aria-label':name+' '+mode,
       class:'thtext'});
     // Typing repaints the page and the counter immediately; the TAB itself is
     // rebuilt on a short debounce, because everything else on it — the Changes
     // list, the per-row revert, the contrast warnings — would otherwise sit
     // stale until the reader happened to blur. The debounce is what keeps a
     // colour-picker drag (one event per pixel) from fighting the rebuild.
     text.addEventListener('input',()=>{tSet(name,mode,text.value.trim());
       tRepaintBar();tSoon();});
     text.addEventListener('change',()=>renderAppearance());
     if(hex!==null||/^#/.test(val)){
      const pick=el('input',{type:'color',value:hex||'#000000',
        'aria-label':name+' '+mode+' colour picker',class:'thpick'});
      pick.addEventListener('input',()=>{text.value=pick.value;
        tSet(name,mode,pick.value);tRepaintBar();tSoon();});
      pick.addEventListener('change',()=>renderAppearance());
      cell.append(pick);}
     cell.append(text);
     const changed=String(tVal(name,mode))!==String(tDefault(name,mode));
     if(changed)cell.append(el('button',{class:'btn small',type:'button',
       'data-threvert':name+'|'+mode,title:'back to '+tDefault(name,mode),
       onclick:()=>{tSet(name,mode,tDefault(name,mode));renderAppearance();}},'↺'));
     row.append(cell);});
    row.append(el('td',{class:'mut small'},
      tSingle(name)?'':(String(tVal(name,'light'))!==String(tDefault(name,'light'))
        ||String(tVal(name,'dark'))!==String(tDefault(name,'dark'))?'changed':'')));
    tb.append(row);});
   tbl.append(tb);
   card.append(el('div',{class:'thwrap'},tbl));}
  c.append(card);});

 // --- layout: measurements, not colours -------------------------------------
 {
  const lay=tLayout();
  const card=el('div',{class:'card','data-thgroup':'layoutctl'});
  card.append(h2h('Density & order',
    'Density is ONE multiplier over the eight-step spacing scale; type follows '
    +'at a third of it, because a compact panel wants tighter air rather than '
    +'smaller words. The order is which card comes first in a view.'));
  const seg=el('div',{class:'row'});
  (THEME.densities||['comfortable']).forEach(d=>seg.append(
    el('button',{class:'btn small'+(lay.density===d?' primary':''),type:'button',
      'data-thdensity':d,'aria-pressed':lay.density===d?'true':'false',
      onclick:()=>{tLaySet({density:d});renderAppearance();}},
      d.charAt(0).toUpperCase()+d.slice(1))));
  card.append(el('div',{class:'row'},el('span',{class:'filtlbl'},'density:'),seg));
  // Card order, per view. Up/down rather than drag: a keyboard reader gets the
  // same control, and there is nothing to discover.
  Object.keys(THEME.cards||{}).forEach(view=>{
   const known=(THEME.cards||{})[view]||[];
   const cur=(lay.order||{})[view]||known.slice();
   const list=cur.filter(x=>known.includes(x))
     .concat(known.filter(x=>!cur.includes(x)));
   card.append(el('h3',{class:'sub2'},'Order — '+(LABELS[view]||view)));
   list.forEach((name,i)=>{
    const move=(to)=>{const a=list.slice();const t=a.splice(i,1)[0];a.splice(to,0,t);
      const order=Object.assign({},lay.order);order[view]=a;
      tLaySet({order:order});renderAppearance();};
    card.append(el('div',{class:'row thorder','data-thcard':name},
      el('span',{class:'mono'},name),
      el('button',{class:'btn small',type:'button',disabled:i===0?'':null,
        'aria-label':'move '+name+' up',onclick:()=>move(i-1)},'↑'),
      el('button',{class:'btn small',type:'button',
        disabled:i===list.length-1?'':null,
        'aria-label':'move '+name+' down',onclick:()=>move(i+1)},'↓')));});});
  c.append(card);
 }

 // --- what changed, and every way back --------------------------------------
 const chg=el('div',{class:'card','data-thchanges':String(changes.length)});
 chg.append(h2h('Changes',
   'Computed, not remembered: this is the theme minus the default, so it is '
   +'answerable even for a file somebody sent you. Revert one row, Undo one '
   +'step, or reset everything.'));
 if(!changes.length)chg.append(el('div',{class:'mut'},
   'Nothing differs from the built-in theme.'));
 else changes.forEach(ch=>chg.append(el('div',{class:'row thdiff'},
   el('span',{class:'mono'},ch.token+(tSingle(ch.token)?'':' · '+ch.mode)),
   el('span',{class:'mut'},String(ch.from)+' → '),
   el('span',{},String(ch.to)),
   el('button',{class:'btn small',type:'button',
     onclick:()=>{
      if(ch.layout){
       if(ch.token==='layout · density')tLaySet({density:'comfortable'});
       else{const view=ch.token.split(' · ').pop();
        const order=Object.assign({},tLayout().order);delete order[view];
        tLaySet({order:order});}
      }else tSet(ch.token,ch.mode,ch.from);
      renderAppearance();}},'Revert'))));
 (THEME.warnings||[]).concat(tLocalWarnings()).slice(0,6).forEach(w=>
   chg.append(el('div',{class:'mut small','data-thwarn':'1'},w)));
 const save=el('button',{class:'btn primary','data-thsave':'1',onclick:async()=>{
   const rows=changes.map(ch=>({scope:'theme',
     field:ch.token+(tSingle(ch.token)?'':' · '+ch.mode),
     from:ch.from,to:ch.to}));
   if(!rows.length){toast('nothing to save — the theme matches the default');return;}
   if(!await confirmChanges({title:'Save theme',rows:rows,scope:'look',
     verb:'Save '+rows.length+' change'+(rows.length===1?'':'s'),
     note:'writes .claude/audit.theme.json — the CSS is compiled from it, never stored'}))
    return;
   const lay=tLayout();
   const layPayload={};
   if(lay.density&&lay.density!=='comfortable')layPayload.density=lay.density;
   if(lay.order&&Object.keys(lay.order).length)layPayload.order=lay.order;
   const res=await api('PUT','/api/theme',{theme:tPayload(),layout:layPayload,
     history:TUNDO.slice(-100)});
   const slot=$('#look .findings-slot');
   if(slot)slot.replaceChildren(findingsBox(res));
   if(!res.ok){saveOutcome(res,rows,'the theme',slot);return;}
   THEME=await api('GET','/api/theme');TDRAFT=null;TLAY=null;
   renderAppearance();
   const s2=$('#look .findings-slot');
   if(s2)s2.replaceChildren(findingsBox(res));
   saveOutcome(res,rows,'the theme',s2);
   toast('theme saved — reload to see the report wear it too');}},'Save theme');
 const reset=el('button',{class:'btn small','data-threset':'1',type:'button',
   onclick:async()=>{
   if(!await confirmChanges({title:'Reset the theme',danger:1,lock:false,
     rows:changes.map(ch=>({scope:'theme',
       field:ch.token+(tSingle(ch.token)?'':' · '+ch.mode),from:ch.to,to:ch.from})),
     verb:'Back to the built-in look',
     note:'removes .claude/audit.theme.json — the file goes, not just its values'}))
    return;
   const res=await api('PUT','/api/theme',{reset:true});
   THEME=await api('GET','/api/theme');TDRAFT=null;TLAY=null;TUNDO=[];TREDO=[];
   tPaint();tPaintLayout();
   renderAppearance();
   toast(res.ok?'back to the built-in theme':'reset refused',res.ok?'':'err');}},
   'Reset to the built-in');
 chg.append(el('div',{class:'row',style:'margin-top:.9rem'},save,reset),
   el('div',{class:'findings-slot'}));
 c.append(chg);

 if(keepId){const n=document.getElementById(keepId);
  if(n){n.focus();try{n.setSelectionRange(caret,caret);}catch(e){}}}
 else focusBack(keepBack);
 tPaint();tPaintLayout();}

// Rebuild the tab shortly after the typing stops. renderAppearance puts the
// caret back by id, so a rebuild mid-sentence is invisible; what it buys is a
// Changes list, a revert control and a contrast warning that are never stale.
let TSOON=null;
function tSoon(){if(TSOON)clearTimeout(TSOON);
 TSOON=setTimeout(()=>{TSOON=null;renderAppearance();},350);}
// The count pill without a full redraw: a colour picker fires per pixel dragged,
// and rebuilding the tab on each of those would fight the drag.
function tRepaintBar(){
 const pill=$('#look [data-thcount]');if(!pill)return;
 const n=tChanges().length;
 pill.textContent=n?(n+' unsaved change'+(n===1?'':'s')):'no changes';
 pill.setAttribute('data-thcount',String(n));
 pill.className='pill'+(n?' unsaved':'');}

// Contrast, judged in the browser on the DRAFT — the server judges what is
// saved, and a reader dragging a picker deserves the answer before they commit.
function tLum(hex){const m=tHex(hex);if(!m)return null;
 const v=[1,3,5].map(i=>parseInt(m.slice(i,i+2),16)/255)
   .map(x=>x<=0.03928?x/12.92:Math.pow((x+0.055)/1.055,2.4));
 return 0.2126*v[0]+0.7152*v[1]+0.0722*v[2];}
function tRatio(a,b){const la=tLum(a),lb=tLum(b);
 if(la===null||lb===null)return null;
 const hi=Math.max(la,lb),lo=Math.min(la,lb);
 return (hi+0.05)/(lo+0.05);}
const TPAIRS=[['--text','--bg',4.5],['--text','--surface',4.5],
  ['--muted','--surface',4.5],['--accent','--surface',3]];
function tLocalWarnings(){
 const out=[];
 TPAIRS.forEach(([fg,bg,floor])=>TMODES.forEach(mode=>{
  const r=tRatio(tVal(fg,mode),tVal(bg,mode));
  if(r!==null&&r<floor)out.push(fg+' on '+bg+' in '+mode+' mode is '
    +r.toFixed(2)+':1 — below '+floor+':1. A warning, not a refusal: your '
    +'theme, your readers.');}));
 return out;}

function tExport(kind){
 const name=(THEME&&THEME.name)||'audit-theme';
 if(kind==='json'){
  const body=JSON.stringify({$description:'audit panel/report theme',
    name:name,tokens:tPayload()},null,2);
  tDownload(name+'.theme.json',body,'application/json');return;}
 // The compiled tokens, for reading or pasting elsewhere. One-way on purpose:
 // what comes BACK in is JSON, so the importer never has to parse CSS.
 const lines=[':root{'];
 tChanges().filter(ch=>ch.mode==='light').forEach(ch=>
   lines.push('  '+ch.token+':'+ch.to+';'));
 lines.push('}',':root[data-theme="dark"]{');
 tChanges().filter(ch=>ch.mode==='dark').forEach(ch=>
   lines.push('  '+ch.token+':'+ch.to+';'));
 lines.push('}');
 tDownload(name+'.theme.css',lines.join('\n'),'text/css');}
function tDownload(fname,body,mime){
 const url=URL.createObjectURL(new Blob([body],{type:mime+';charset=utf-8'}));
 const a=el('a',{href:url,download:fname});document.body.append(a);a.click();
 a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function tImport(input){
 const f=input.files&&input.files[0];input.value='';
 if(!f)return;
 const rd=new FileReader();
 rd.onload=()=>{
  let data=null;
  try{data=JSON.parse(String(rd.result||''));}
  catch(e){toast('that file is not JSON — a theme is exported as .json','err');return;}
  const tokens=(data&&typeof data==='object'&&data.tokens&&typeof data.tokens==='object')
    ?data.tokens:data;
  if(!tokens||typeof tokens!=='object'){toast('no tokens in that file','err');return;}
  const known=new Set(((THEME&&THEME.groups)||[]).flatMap(g=>g.tokens));
  const refused=[];
  Object.keys(tokens).forEach(name=>{
   if(name.charAt(0)==='$'||name==='name'||name==='history')return;
   if(!known.has(name)){refused.push(name);return;}
   const e=tokens[name]||{};
   if(e.$value!==undefined)tSet(name,'light',String(e.$value));
   if(!tSingle(name)&&e.$dark!==undefined)tSet(name,'dark',String(e.$dark));});
  renderAppearance();
  toast(refused.length
    ? ('loaded as a draft; '+refused.length+' unknown token(s) refused: '
       +refused.slice(0,3).join(', '))
    : 'loaded as a draft — nothing is written until you Save');};
 rd.readAsText(f);}

