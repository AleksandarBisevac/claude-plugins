/**
 * Draw the whole Appearance tab from THEME and the draft, and put the caret back
 * where it was.
 *
 * Called on every change that alters more than one value on screen — a save, a
 * theme switch, an undo, a colour committed with `change` — and by tSoon shortly
 * after typing stops. It reads state and rebuilds; it never fetches. The two
 * exceptions are the handlers it wires INTO the tab, which is where every write
 * to /api/theme in this file lives.
 *
 * A rebuild mid-sentence is invisible only because focus is restored: the id of
 * the focused `th-*` input and its caret offset are read before the tab is
 * emptied and reapplied at the end. Anything else focused falls back to
 * focusKeep/focusBack, the panel's generic restore.
 *
 * With no THEME it draws one warning card and stops — an empty editor would
 * invite somebody to type values into a theme that could not be read.
 * @returns {void}
 */
function renderAppearance(){closeCombo();
 const c=$('#look');
 const act=document.activeElement,
   keepId=act&&act.id&&act.id.indexOf('th-')===0?act.id:null,
   caret=keepId&&act.setSelectionRange?act.selectionStart:0,
   keepBack=keepId?null:focusKeep('#look');
 c.textContent='';
 if(!THEME){c.append(el('div',{class:'card'},el('div',{class:'findings warn'},
   'The theme could not be read from this project.')));return;}
 // Registered here, where the view is wired, exactly as the other writable
 // surfaces are. The theme draft lives in memory only - nothing persists TDRAFT
 // or TLAY - so before this, closing the tab took every unsaved colour with it
 // without asking, on the one surface whose Save has no Discard beside it.
 EDITS.look=()=>tChangeRows();
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
 // UNSAVED, not "differs from the built-in look". The card below shows the
 // second thing and says so in its own header; this pill sits beside Save and
 // says what Save will report, so it counts the rows Save actually sends. It
 // counted the card's set, so a project wearing a theme opened claiming unsaved
 // changes nobody had made - and now that beforeunload reads the same registry,
 // the pill would have contradicted a close that went through without a word.
 const nch=tChangeRows().length;
 bar.append(el('span',{class:'pill'+(nch?' unsaved':''),'data-thcount':String(nch)},
   nch?plural(nch,'unsaved change'):'no changes'));
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
  // Only 'config' and 'default' can be MARKED here, and that is not an
  // oversight: the project and user themes are a fixed filename, and the list
  // is .claude/themes/*.json plus the built-in, so a worn project theme is not
  // one of the options to select. Compared with slashes normalised, because the
  // path arrives from the server the way that platform spells it.
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
   const modeCol=m=>({attrs:{class:livemode===m?'thlive':'thoff'},label:m,
     extra:livemode===m?el('span',{class:'mut'},' · previewing'):null});
   tbl.append(tableHead(['token',modeCol('light'),modeCol('dark'),null]));
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
     // The id is what renderAppearance restores focus by, so it has to be
     // stable across a rebuild: token plus mode, with the leading '--' cut
     // because it is the same two characters on every row.
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
     // A picker appears for a value that IS a colour, and also for one that
     // merely opens with '#': a half-typed '#ab' still wants the picker beside
     // it, and the picker falls back to black rather than refusing to render.
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
   // The union, in this order: what the theme asks for, minus cards that no
   // longer exist, then every known card the theme never named. So a theme
   // written today lists a card added next year at the end rather than hiding
   // it, and an order naming a deleted card does not leave a gap.
   const known=(THEME.cards||{})[view]||[];
   const cur=(lay.order||{})[view]||known.slice();
   const list=cur.filter(x=>known.includes(x))
     .concat(known.filter(x=>!cur.includes(x)));
   card.append(el('h3',{class:'sub2'},'Order — '+(LABELS[view]||view)));
   list.forEach((name,i)=>{
    /**
     * Move this card to another index and redraw.
     * @param {number} to - the index to splice it back in at; the two buttons
     *   are disabled at the ends, so this is never out of range
     * @returns {void}
     */
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
      // A layout row is reverted by DELETING the draft field, not by writing
      // the old value back: writing it would leave a theme file saying what the
      // default already says, which is the one thing tLayChanges refuses to
      // offer in the first place.
      if(ch.layout){
       if(ch.token==='layout · density')tLaySet({density:'comfortable'});
       else{const view=ch.token.split(' · ').pop();
        const order=Object.assign({},tLayout().order);delete order[view];
        tLaySet({order:order});}
      }else tSet(ch.token,ch.mode,ch.from);
      renderAppearance();}},'Revert'))));
 // Capped at six: the server's verdict and the browser's draft warnings share
 // one list, and a palette in mid-edit can fail every pair at once.
 (THEME.warnings||[]).concat(tLocalWarnings()).slice(0,6).forEach(w=>
   chg.append(el('div',{class:'mut small','data-thwarn':'1'},w)));
 const save=el('button',{class:'btn primary','data-thsave':'1',onclick:async()=>{
   // "matches the default" was the old measurement talking: these rows are
   // measured against what is ON DISK, so an untouched themed project has
   // nothing to save without matching the built-in look at all.
   const rows=await confirmSave({rows:tChangeRows,title:'Save theme',
     scope:'look',empty:'this is already what is on disk',
     note:'writes .claude/audit.theme.json — the CSS is compiled from it, '
       +'never stored'});
   if(!rows)return;
   const lay=tLayout();
   const layPayload={};
   if(lay.density&&lay.density!=='comfortable')layPayload.density=lay.density;
   if(lay.order&&Object.keys(lay.order).length)layPayload.order=lay.order;
   const res=await api('PUT','/api/theme',{theme:tPayload(),layout:layPayload,
     history:TUNDO.slice(-100)});
   // The findings are shown BEFORE the re-render and again after it: a refusal
   // must be readable even though the failure path returns without redrawing,
   // and the second slot is a different node because renderAppearance rebuilt
   // the card the first one lived in.
   const slot=showFindings('#look',res);
   if(!res.ok){saveOutcome(res,rows,'the theme',slot);return;}
   THEME=await api('GET','/api/theme');TDRAFT=null;TLAY=null;
   renderAppearance();
   showWriteResult('#look',res,rows,'the theme');
   toast('theme saved — reload to see the report wear it too');}},'Save theme');
 const reset=el('button',{class:'btn small','data-threset':'1',type:'button',
   onclick:async()=>{
   // The confirm rows are the change list REVERSED — from and to swapped —
   // because the dialog has to describe what reset is about to do, not what the
   // draft did. `lock:false` because deleting the theme file is not a write the
   // gate holds; `danger` because the file goes, not just its values.
   if(!await confirmChanges({title:'Reset the theme',danger:1,lock:false,
     rows:tResetRows(),
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

 restoreCaret(keepId?document.getElementById(keepId):null,caret,keepBack);
 tPaint();tPaintLayout();}

/**
 * @type {number|null} the pending tSoon timer, so a second keystroke replaces
 * the rebuild the first one scheduled instead of queueing another
 */
let TSOON=null;
/**
 * Rebuild the tab shortly after the typing stops.
 *
 * renderAppearance puts the caret back by id, so a rebuild mid-sentence is
 * invisible; what it buys is a Changes list, a revert control and a contrast
 * warning that are never stale. Every call pushes the rebuild further out, so a
 * colour-picker drag firing per pixel rebuilds once, at the end.
 * @returns {void}
 */
function tSoon(){if(TSOON)clearTimeout(TSOON);
 TSOON=setTimeout(()=>{TSOON=null;renderAppearance();},350);}
/**
 * Repaint the unsaved-change pill in place, without redrawing the tab.
 *
 * This is the immediate half of the pair tSoon completes: a colour picker fires
 * an event per pixel dragged, and rebuilding the tab on each of those would
 * fight the drag — but a counter that only caught up 350ms later would read as
 * a stuck control.
 *
 * Counts the SAME set the pill above is built with — `tChangeRows`, which is
 * what Save sends. It used to count `tChanges()` alone, so typing a colour while
 * a density or a card order was pending dropped the layout rows out of the pill
 * until `tSoon` rebuilt the tab 350ms later: one sentence, two different
 * numbers, in the control whose whole job is saying how much is unsaved. Reading
 * a different SET from the render was the same bug one level up.
 * @returns {void}
 */
function tRepaintBar(){
 const pill=$('#look [data-thcount]');if(!pill)return;
 const n=tChangeRows().length;
 pill.textContent=n?plural(n,'unsaved change'):'no changes';
 pill.setAttribute('data-thcount',String(n));
 pill.className='pill'+(n?' unsaved':'');}

// --- contrast, judged in the browser on the DRAFT --------------------------
// The server judges what is SAVED, and a reader dragging a picker deserves the
// answer before they commit. So this is a second implementation of the same
// arithmetic on purpose, and it answers about a value that does not exist on
// disk yet.
/**
 * Relative luminance, per WCAG 2.x: sRGB channels linearised, then weighted.
 *
 * @param {string} hex - a #rrggbb colour; anything else yields null
 * @returns {number|null} luminance in 0..1, or null when the value is not a
 *   colour this can judge — a token holding a var() reference or a font stack
 */
function tLum(hex){const m=tHex(hex);if(!m)return null;
 const v=[1,3,5].map(i=>parseInt(m.slice(i,i+2),16)/255)
   .map(x=>x<=0.03928?x/12.92:Math.pow((x+0.055)/1.055,2.4));
 return 0.2126*v[0]+0.7152*v[1]+0.0722*v[2];}
/**
 * The contrast ratio between two colours, order-independent.
 *
 * @param {string} a - one #rrggbb colour
 * @param {string} b - the other
 * @returns {number|null} the ratio, 1 to 21, or null when EITHER side is not a
 *   colour — a null is "cannot judge this pair", never "this pair is fine"
 */
function tRatio(a,b){const la=tLum(a),lb=tLum(b);
 if(la===null||lb===null)return null;
 const hi=Math.max(la,lb),lo=Math.min(la,lb);
 // ROUNDED TO 2dp BEFORE ANY COMPARISON, because `_ui_theme.contrast_ratio`
 // returns `round(x, 2)` and the floor is checked against that. Comparing the
 // raw quotient made the two sides disagree for a true ratio anywhere in
 // [4.495, 4.5): Python saw 4.5 and stayed quiet, this saw 4.497 and warned.
 return Math.round(((hi+0.05)/(lo+0.05))*100)/100;}
/**
 * @type {Array<[string, string, number]>} the pairs worth checking, as
 * [foreground token, background token, the ratio below which it is reported].
 * 4.5 is the AA floor for body text; 3 is the large-text and non-text floor the
 * accent only has to clear.
 */
// _ui_theme.CONTRAST_PAIRS itself, JSON-dumped into the page by _panel_page.py -
// NOT a copy of its rows. This carried four of the six, so a draft could report
// no warnings where the server reported two, and the reader sees one merged list.
const TPAIRS=__CONTRAST_PAIRS__;
/**
 * Every TPAIRS combination the DRAFT fails, in both modes, as sentences.
 *
 * A pair this cannot judge — either side not a colour — produces no line at all
 * rather than a passing one, so an empty list means "nothing measurable failed"
 * and not "everything was measured and passed".
 * @returns {string[]} one warning per failing pair and mode; empty when none
 *   failed or none could be measured
 */
function tLocalWarnings(){
 const out=[];
 TPAIRS.forEach(([fg,bg,floor])=>TMODES.forEach(mode=>{
  const r=tRatio(tVal(fg,mode),tVal(bg,mode));
  // The floor is rendered at ONE decimal because Python's message uses `%.1f`,
  // so an accent floor of 3 reads '3.0:1' on both sides. These two lists are
  // concatenated for the reader; a difference in wording between the halves is a
  // difference the reader would have to attribute, and cannot.
  if(r!==null&&r<floor)out.push(fg+' on '+bg+' in '+mode+' mode is '
    +r.toFixed(2)+':1 — below '+floor.toFixed(1)+':1. A warning, not a refusal: '
    +'your theme, your readers.');}));
 return out;}

// --- taking a theme out of the panel, and bringing one back ----------------
/**
 * Download the draft as a file.
 *
 * Only what differs from the default is exported, which is the same rule
 * tPayload writes by: a theme file says what its author decided, and a later
 * change to a default reaches everyone who never overrode it.
 * @param {'json'|'css'} kind - 'json' is the round-trippable DTCG file tImport
 *   reads back; 'css' is the compiled tokens, one-way on purpose
 * @returns {void}
 */
function tExport(kind){
 const name=(THEME&&THEME.name)||'audit-theme';
 if(kind==='json'){
  const body=JSON.stringify({$description:'audit panel/report theme',
    name:name,tokens:tPayload()},null,2);
  downloadText(name+'.theme.json',body,'application/json');return;}
 // The compiled tokens, for reading or pasting elsewhere. One-way on purpose:
 // what comes BACK in is JSON, so the importer never has to parse CSS.
 const lines=[':root{'];
 tChanges().filter(ch=>ch.mode==='light').forEach(ch=>
   lines.push('  '+ch.token+':'+ch.to+';'));
 lines.push('}',':root[data-theme="dark"]{');
 tChanges().filter(ch=>ch.mode==='dark').forEach(ch=>
   lines.push('  '+ch.token+':'+ch.to+';'));
 lines.push('}');
 downloadText(name+'.theme.css',lines.join('\n'),'text/css');}
/**
 * Load a theme file somebody sent, as a DRAFT — nothing is written until Save.
 *
 * Every token is checked against the groups the server declared, and an unknown
 * one is REFUSED and named rather than dropped: a file half-applied in silence
 * is how somebody comes to believe a token exists. The input's value is cleared
 * first so that picking the same file twice fires again.
 *
 * Reads asynchronously and returns before the file is parsed; everything the
 * import does happens in the reader's onload, including the toast.
 * @param {HTMLInputElement} input - the hidden file input the button clicks
 * @returns {void}
 */
function tImport(input){
 const f=input.files&&input.files[0];input.value='';
 if(!f)return;
 const rd=new FileReader();
 rd.onload=()=>{
  let data=null;
  try{data=JSON.parse(String(rd.result||''));}
  catch(e){toast('that file is not JSON — a theme is exported as .json','err');return;}
  // Both shapes are accepted: the file tExport writes, which nests the map under
  // `tokens`, and a bare map somebody hand-wrote.
  const tokens=(data&&typeof data==='object'&&data.tokens&&typeof data.tokens==='object')
    ?data.tokens:data;
  if(!tokens||typeof tokens!=='object'){toast('no tokens in that file','err');return;}
  const known=new Set(((THEME&&THEME.groups)||[]).flatMap(g=>g.tokens));
  const refused=[],unusable=[];
  let applied=0;
  Object.keys(tokens).forEach(name=>{
   // The file's own metadata, skipped rather than refused: `$description`, the
   // name, and the undo history a save writes back into the theme file.
   if(name.charAt(0)==='$'||name==='name'||name==='history')return;
   if(!known.has(name)){refused.push(name);return;}
   // A BARE STRING is a value, and this is what the comment above always
   // promised. A hand-written map is `{"--accent":"#abc"}`, not
   // `{"--accent":{"$value":"#abc"}}` - and on the string form `e.$value` was
   // undefined, so the token was neither applied nor refused and the toast still
   // said "loaded as a draft". Silent success on a file that changed nothing.
   const raw=tokens[name];
   const e=(typeof raw==='string')?{$value:raw}
     :((raw&&typeof raw==='object')?raw:null);
   if(!e){unusable.push(name);return;}
   let touched=false;
   if(e.$value!==undefined){tSet(name,'light',String(e.$value));touched=true;}
   if(!tSingle(name)&&e.$dark!==undefined){
    tSet(name,'dark',String(e.$dark));touched=true;}
   // A known name whose entry carries no value sets nothing. Counted, so it
   // cannot hide inside a success message.
   if(touched)applied+=1;else unusable.push(name);});
  renderAppearance();
  // NOTHING APPLIED IS NOT A SUCCESS. Every branch below names what happened,
  // and the count of what landed comes first, because that is the thing the
  // reader is about to Save.
  const notes=[];
  if(refused.length)notes.push(refused.length+' unknown: '+refused.slice(0,3).join(', '));
  if(unusable.length)notes.push(unusable.length+' with no usable value: '
    +unusable.slice(0,3).join(', '));
  const tail=notes.length?(' ('+notes.join('; ')+')'):'';
  if(!applied)toast('nothing in that file could be applied'+tail,'err');
  else toast(plural(applied,'token')+' loaded as a draft'+tail
    +' — nothing is written until you Save');};
 rd.readAsText(f);}
