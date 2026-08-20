// ---------- Appearance (th, F-P-6) ----------
// The visual system is one token layer, shared by this panel and the report, and
// every value in it is already a custom property — so editing the look is
// editing those values, not writing CSS. That is the whole design: the server
// compiles a theme by SUBSTITUTING values into the stylesheet, so a theme can
// change token values and nothing else, and the default compiles back to the
// shipped sheet byte for byte.
//
// What lives here: a draft, a live preview (this page IS the preview — the draft
// is written straight onto :root, so a colour is judged on the thing it will
// colour), an ordered undo trail, and one Save that goes through the same
// confirm-and-echo path every other write in this panel uses.
let THEME=null;                 // the server's answer: stored theme + default + groups
let TDRAFT=null;                // what the editor is holding, before Save
let TUNDO=[], TREDO=[];         // the ordered trail: {token, mode, from, to}
let TUNLOCK=false;              // the Charts group's deliberate second act
let TLAY=null;                  // the layout draft: density + card order
// The layout in effect: draft first, then what the theme file says, then the
// shipped defaults — the same three-layer answer tVal gives for a token.
function tLayout(){
 if(TLAY)return TLAY;
 const l=(THEME&&THEME.layout)||{};
 return {density:l.density||'comfortable',order:l.order||{}};}
function tLaySet(patch){
 const cur=tLayout();
 TLAY=Object.assign({density:cur.density,order:Object.assign({},cur.order)},patch);
 tPaintLayout();
 // ...and the views that carry ordered cards restack at once, so the change is
 // visible on the tab it is about rather than only after a save.
 Object.keys((THEME&&THEME.cards)||{}).forEach(v=>applyCardOrder(v));}
// The density preview: the panel's own spacing scale, scaled here so the tab
// shows what it is about to write. The compiler does the same arithmetic
// server-side — this is the preview of it, not a second source.
const TDENSITY={compact:0.8,comfortable:1,spacious:1.25};
const TSPACING=['--sp-0','--sp-1','--sp-2','--sp-3','--sp-4','--sp-5','--sp-6','--sp-7'];
const TTYPE=['--t-1','--t-2','--t-3','--t-label'];
let TLAYPAINT=[];
function tScale(v,f){const m=/^(-?\d*\.?\d+)(rem|em|px)$/.exec(String(v||'').trim());
 if(!m||f===1)return null;
 let out=(parseFloat(m[1])*f).toFixed(4).replace(/0+$/,'').replace(/\.$/,'');
 if(out.indexOf('0.')===0)out=out.slice(1);
 return (out||'0')+m[2];}
function tPaintLayout(){
 const root=document.documentElement;
 TLAYPAINT.forEach(n=>root.style.removeProperty(n));TLAYPAINT=[];
 // Spelled out rather than `||1`: this is a lookup with a known default, and
 // the sheet's own lint bans that idiom outright — it is a denominator's
 // disguise everywhere else in this file, and one exception is how the rule
 // stops being read.
 const d=tLayout().density;
 const f=TDENSITY[d]===undefined?1:TDENSITY[d];
 if(f===1)return;
 const tf=1+(f-1)/3;
 const cs=getComputedStyle(root);
 TSPACING.forEach(n=>{const v=tScale(TBASE[n]||cs.getPropertyValue(n),f);
  if(v){root.style.setProperty(n,v);TLAYPAINT.push(n);}});
 TTYPE.forEach(n=>{const v=tScale(TBASE[n]||cs.getPropertyValue(n),tf);
  if(v){root.style.setProperty(n,v);TLAYPAINT.push(n);}});}
// The UNSCALED values, read once before anything is painted — reading them back
// off the root after a paint would compound the scale on every keystroke.
const TBASE={};
function tCaptureBase(){
 const cs=getComputedStyle(document.documentElement);
 TSPACING.concat(TTYPE).forEach(n=>{
  if(!TBASE[n])TBASE[n]=cs.getPropertyValue(n).trim();});}
const TMODES=['light','dark'];
const tKey=(name,mode)=>mode==='dark'?'$dark':'$value';
// The value a token HAS right now: the draft first, then the stored theme, then
// the default. Three layers, one answer, so nothing on screen is ever blank.
function tVal(name,mode){
 const from=o=>o&&o[name]?o[name][tKey(name,mode)]:undefined;
 const d=from(TDRAFT);if(d!==undefined&&d!==null)return d;
 const s=from(THEME&&THEME.theme);if(s!==undefined&&s!==null)return s;
 const f=from(THEME&&THEME.default);
 return f===undefined?'':f;}
const tSingle=name=>((THEME&&THEME.single)||[]).includes(name);
function tDefault(name,mode){
 const e=(THEME&&THEME.default||{})[name]||{};
 const v=e[tKey(name,mode)];return v===undefined?e['$value']:v;}
// Every token whose draft differs from the DEFAULT — computed, never
// remembered, so it is answerable for a theme somebody sent you as a file.
function tChanges(){
 const out=[];
 ((THEME&&THEME.groups)||[]).forEach(g=>g.tokens.forEach(name=>{
  TMODES.forEach(mode=>{
   if(mode==='dark'&&tSingle(name))return;
   const now=tVal(name,mode),was=tDefault(name,mode);
   if(String(now)!==String(was))out.push({token:name,mode:mode,from:was,to:now});});}));
 return out;}
// The draft, as the payload the server takes: only what differs from the
// default is written, so a theme file says what its author decided and nothing
// more (and a later change to a default reaches everyone who never overrode it).
// What differs from the shipped defaults on the layout side, in the same
// {token,mode,from,to} shape the token diff uses, so one list shows both.
function tLayChanges(){
 const cur=tLayout(),base=(THEME&&THEME.layout)||{};
 const out=[];
 const shipped='comfortable';
 if((cur.density||shipped)!==shipped)
  out.push({token:'layout · density',mode:'',from:shipped,to:cur.density,layout:1});
 Object.keys(cur.order||{}).forEach(view=>{
  const now=(cur.order[view]||[]).join(', ');
  const was=((base.order||{})[view]||[]).join(', ');
  // An order equal to the DRAWN one is not a change: moving a card down and
  // back up must leave the tab saying "no changes", not offering to write an
  // order that says what the default already says.
  const shipped=((THEME&&THEME.cards)||{})[view];
  const isDefault=Array.isArray(shipped)&&now===shipped.join(', ');
  if(now&&now!==was&&!isDefault)out.push({token:'layout · order · '+view,mode:'',
    from:was||'(default)',to:now,layout:1});});
 return out;}
function tPayload(){
 const out={};
 tChanges().forEach(c=>{
  const e=out[c.token]||(out[c.token]={$value:tVal(c.token,'light')});
  if(!tSingle(c.token))e.$dark=tVal(c.token,'dark');});
 return out;}
// LIVE PREVIEW. The draft is written onto the document root as inline custom
// properties: the panel repaints instantly and honestly, because it is wearing
// the theme rather than showing a swatch of it. Cleared token by token, so a
// revert leaves nothing behind.
let TPAINTED=[];
function tPaint(){
 const root=document.documentElement;
 TPAINTED.forEach(n=>root.style.removeProperty(n));
 TPAINTED=[];
 const dark=isDark();
 tChanges().forEach(c=>{
  if(c.mode!==(dark?'dark':'light'))return;
  root.style.setProperty(c.token,String(c.to));TPAINTED.push(c.token);});}
function tSet(name,mode,value,record){
 const was=tVal(name,mode);
 if(String(was)===String(value))return;
 TDRAFT=TDRAFT||{};
 const e=TDRAFT[name]||(TDRAFT[name]={$value:tVal(name,'light')});
 if(!tSingle(name)&&e.$dark===undefined)e.$dark=tVal(name,'dark');
 e[tKey(name,mode)]=value;
 if(record!==false){TUNDO.push({token:name,mode:mode,from:was,to:value});TREDO=[];}
 tPaint();}
function tUndo(stack,other){
 const step=stack.pop();if(!step)return;
 const back={token:step.token,mode:step.mode,from:step.to,to:step.from};
 tSet(step.token,step.mode,step.from,false);
 other.push(back.from===undefined?step:{token:step.token,mode:step.mode,
   from:step.to,to:step.from});
 renderAppearance();}
function tHex(v){return /^#[0-9a-fA-F]{6}$/.test(String(v||''))?String(v):null;}

