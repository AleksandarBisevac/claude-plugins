// ---------- Appearance ----------
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
//
// A "mode" here is one of the two columns a token carries: 'light' or 'dark'.
// It is NOT which mode the page happens to be wearing — that is isDark(). Both
// columns are edited and saved together, and only the one being worn repaints,
// which is why the editor labels the live column out loud.

/**
 * One token's value, per mode, as the theme file and the API both spell it.
 * `$dark` is absent for a token named in `THEME.single`: those carry one value
 * that serves both modes.
 * @typedef {{$value: string, $dark: (string|undefined)}} ThemeToken
 */

/**
 * One difference between the draft and what it is measured against, as every
 * surface in the Appearance tab reads it — the pill's count, the Changes list,
 * the per-row Revert, the confirm dialog and the undo trail.
 *
 * `mode` is '' for a layout row, which has no light/dark column, and `layout` is
 * present only on those rows: it is what tells Revert to reset a density or a
 * card order rather than to write a token value.
 * @typedef {{token: string, mode: 'light'|'dark'|'', from: *, to: *,
 *   layout: (number|undefined)}} ThemeChange
 */

/**
 * `GET /api/theme` in full: the theme in effect, the vocabulary to edit it with,
 * and the default to measure changes against.
 *
 * `default` arrives from the server rather than being restated here, because
 * "what did I change" is theme-minus-default and a second copy of the default in
 * the browser is how the two answers start disagreeing. `source` says which file
 * is being worn; only 'config' and 'default' can also appear in `saved`, because
 * the project and user themes are one fixed filename rather than one of the
 * .claude/themes/*.json the switcher lists.
 * @typedef {{
 *   theme: Object<string, ThemeToken>,
 *   default: Object<string, ThemeToken>,
 *   groups: Array<{key: string, title: string, tokens: string[]}>,
 *   single: string[],
 *   source: 'config'|'project'|'user'|'default',
 *   path: (string|null),
 *   name: string,
 *   error: (string|null),
 *   warnings: string[],
 *   layout: {density: (string|undefined), order: (Object<string, string[]>|undefined)},
 *   densities: string[],
 *   saved: Array<{name: string, path: (string|null), builtin: boolean}>,
 *   cards: Object<string, string[]>,
 *   locked: string[]
 * }} ThemePayload
 */

/**
 * The server's answer, replaced whole on every reload; null until the first
 * `GET /api/theme` lands, and left null when that read fails — the one state the
 * Appearance tab refuses to render rather than drawing an empty editor.
 * @type {ThemePayload|null}
 */
let THEME=null;
/**
 * What the editor is holding and the server has not seen: only the tokens
 * somebody touched, so an untouched token keeps answering from the stored theme
 * and then the default. Set back to null by a save, a reset or a theme switch.
 * @type {Object<string, ThemeToken>|null}
 */
let TDRAFT=null;
/**
 * The ordered undo and redo trails. One entry is a single token edit as it
 * happened — `from` is what the token answered before, `to` what it answers now
 * — so undoing means applying `from` and pushing the inverse onto the other
 * trail. A fresh edit clears TREDO, and neither trail survives a save or a
 * reload: they describe this sitting, not the file.
 * @type {ThemeChange[]}
 */
let TUNDO=[], TREDO=[];
/**
 * Whether the reader has asked twice for the locked group. The chart palette is
 * validated for colour-vision deficiency against these very surfaces, so it
 * opens on a deliberate second act and closes again on every reload.
 * @type {boolean}
 */
let TUNLOCK=false;
/**
 * The layout half of the draft — density and per-view card order — held apart
 * from TDRAFT because it is not a token map and the server takes it as its own
 * payload. Null means "no layout edit yet", never "no layout".
 * @type {{density: string, order: Object<string, string[]>}|null}
 */
let TLAY=null;
/**
 * The layout in effect: the draft first, then what the theme file says, then the
 * shipped defaults — the same three-layer answer tVal gives for a token.
 * @returns {{density: string, order: Object<string, string[]>}} always a whole
 *   layout, never a partial one, so no caller has to spell the fallback again
 */
function tLayout(){
 if(TLAY)return TLAY;
 const l=(THEME&&THEME.layout)||{};
 return {density:l.density||'comfortable',order:l.order||{}};}
/**
 * Patch the layout draft and show the result at once.
 *
 * The patch is merged onto a COPY of the current layout, `order` included, so a
 * caller cannot mutate what tLayout handed it.
 * @param {{density: (string|undefined), order: (Object<string, string[]>|undefined)}} patch
 *   the fields to change; anything absent keeps its current value
 * @returns {void}
 */
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
/** @type {Object<string, number>} what multiplier each density name means */
const TDENSITY={compact:0.8,comfortable:1,spacious:1.25};
/** @type {string[]} the spacing scale, scaled by the density multiplier itself */
const TSPACING=['--sp-0','--sp-1','--sp-2','--sp-3','--sp-4','--sp-5','--sp-6','--sp-7'];
/**
 * @type {string[]} the type scale, scaled at a third of the density multiplier —
 * a compact panel wants tighter air rather than smaller words
 */
const TTYPE=['--t-1','--t-2','--t-3','--t-label'];
/**
 * @type {string[]} the custom properties tPaintLayout last wrote onto :root, so
 * the next paint clears exactly those and nothing the stylesheet owns
 */
let TLAYPAINT=[];
/**
 * One CSS length, multiplied, in the unit it arrived in.
 *
 * @param {string} v - a length such as '0.75rem'; anything that is not a bare
 *   number plus rem/em/px is refused rather than guessed at
 * @param {number} f - the multiplier
 * @returns {string|null} the scaled length, or null when there is nothing to do:
 *   an unparseable value, or a multiplier of exactly 1. Null tells the caller to
 *   leave the property alone — it is not a zero length.
 */
function tScale(v,f){const m=/^(-?\d*\.?\d+)(rem|em|px)$/.exec(String(v||'').trim());
 if(!m||f===1)return null;
 let out=(parseFloat(m[1])*f).toFixed(4).replace(/0+$/,'').replace(/\.$/,'');
 if(out.indexOf('0.')===0)out=out.slice(1);
 return (out||'0')+m[2];}
/**
 * Paint the density draft onto :root, clearing whatever the last paint wrote.
 *
 * Comfortable is the identity multiplier, so it writes nothing at all and the
 * stylesheet's own values apply — which is why a return to comfortable has to
 * clear TLAYPAINT before it takes that early exit.
 * @returns {void}
 */
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
/**
 * @type {Object<string, string>} the UNSCALED value of every scale property, as
 * the stylesheet declares it
 */
const TBASE={};
/**
 * Capture the scale properties as the stylesheet declares them, once.
 *
 * Reading them back off :root after a paint would read what that paint wrote and
 * multiply it again, so the density preview would compound on every keystroke.
 * Each property is captured only while it is still missing, which is what makes
 * a second call harmless rather than merely redundant.
 * @returns {void}
 */
function tCaptureBase(){
 const cs=getComputedStyle(document.documentElement);
 TSPACING.concat(TTYPE).forEach(n=>{
  if(!TBASE[n])TBASE[n]=cs.getPropertyValue(n).trim();});}
// ---------- token values, and what differs from the default ----------
/** @type {Array<'light'|'dark'>} both columns, always edited and saved together */
const TMODES=['light','dark'];
/**
 * The key one mode is stored under, in the theme file and in every payload.
 *
 * @param {'light'|'dark'} mode - which column
 * @returns {'$value'|'$dark'} the key. A single-valued token carries no '$dark';
 *   tDefault is what falls back to '$value' for it, not this.
 */
const tKey=mode=>mode==='dark'?'$dark':'$value';
/**
 * The value a token HAS right now: the draft first, then the stored theme, then
 * the default. Three layers, one answer, so nothing on screen is ever blank.
 *
 * @param {string} name - the custom property, '--' included
 * @param {'light'|'dark'} mode - which column
 * @returns {string} the value, or '' when not even the default names this token
 */
function tVal(name,mode){
 const d=TDRAFT&&TDRAFT[name]?TDRAFT[name][tKey(mode)]:undefined;
 return (d!==undefined&&d!==null)?d:tSavedVal(name,mode);}
/**
 * The value ON DISK for one token and mode: the saved theme's, or the shipped
 * default's where the saved theme is silent.
 *
 * `tVal` is this with the draft laid over it, and it is expressed that way
 * rather than repeating the walk - two spellings of one layer stack is how
 * "unsaved" comes to mean two different things on one tab.
 *
 * @param {string} name - the custom property, '--' included
 * @param {'light'|'dark'} mode - which column
 * @returns {string} the value, or '' when not even the default names this token
 */
function tSavedVal(name,mode){
 const from=o=>o&&o[name]?o[name][tKey(mode)]:undefined;
 const s=from(THEME&&THEME.theme);if(s!==undefined&&s!==null)return s;
 const f=from(THEME&&THEME.default);
 return f===undefined?'':f;}
/**
 * Whether one value serves both modes for this token — a radius, a font stack.
 * The editor draws '— same in both' instead of a second input, and the payload
 * writes no '$dark'.
 * @param {string} name - the custom property
 * @returns {boolean} false when the theme could not be read at all, which keeps
 *   the editor two-column rather than silently collapsing it
 */
const tSingle=name=>((THEME&&THEME.single)||[]).includes(name);
/**
 * What the SHIPPED default says this token is, per mode — the thing every
 * "changed" verdict and every Revert is measured against.
 *
 * @param {string} name - the custom property
 * @param {'light'|'dark'} mode - which column
 * @returns {string|undefined} the default value, falling back to the light one
 *   for a single-valued token; undefined when the default names no such token,
 *   which is what makes an imported unknown token distinguishable from one whose
 *   default is genuinely empty
 */
function tDefault(name,mode){
 const e=(THEME&&THEME.default||{})[name]||{};
 const v=e[tKey(mode)];return v===undefined?e['$value']:v;}
// Every token whose draft differs from the DEFAULT — computed, never
// remembered, so it is answerable for a theme somebody sent you as a file.
/**
 * @returns {ThemeChange[]} one row per token and mode that differs from the
 *   shipped default, in group then token then mode order; the dark column is
 *   skipped for a single-valued token. Empty means the draft IS the default,
 *   which the tab says out loud rather than showing an empty list.
 */
/**
 * Every token and mode whose CURRENT value differs from `baseline`.
 *
 * The walk is the same for both questions this tab asks — groups, then tokens,
 * then modes, skipping the dark column of a single-valued token, comparing as
 * strings so `'0'` and `0` are one value — and the only thing that ever differed
 * between them is which baseline the draft is measured against. It was spelled
 * twice, so the skip rule and the comparison were each two places to fix, and the
 * second copy arrived the same afternoon the first was documented as the meaning
 * of "differs".
 *
 * @param {function(string, string): *} baseline - the value to measure against,
 *   given a token name and a mode: `tDefault` for the shipped look, `tSavedVal`
 *   for what is on disk
 * @returns {ThemeChange[]} one row per differing pair, in group then token then
 *   mode order
 */
function tDiff(baseline){
 const out=[];
 ((THEME&&THEME.groups)||[]).forEach(g=>g.tokens.forEach(name=>{
  TMODES.forEach(mode=>{
   if(mode==='dark'&&tSingle(name))return;
   const now=tVal(name,mode),was=baseline(name,mode);
   if(String(now)!==String(was))out.push({token:name,mode:mode,from:was,to:now});});}));
 return out;}
function tChanges(){return tDiff(tDefault);}
// What differs from the shipped defaults on the layout side, in the same
// {token,mode,from,to} shape the token diff uses, so one list shows both.
/**
 * @returns {ThemeChange[]} the density row when it is not the shipped default,
 *   then one row per reordered view, each carrying `layout:1` so a Revert resets
 *   a layout field instead of writing a token. The two halves are measured
 *   against different baselines — see the comment on the order loop.
 */
/**
 * What the DRAFT has that the disk does not — this tab's unsaved work.
 *
 * NOT `tChanges()`, and the difference is the whole point. `tChanges` measures
 * against the shipped DEFAULT because that is what gets written into a theme
 * file: `tPayload` is built from it, so a file says what its author decided and
 * nothing more. On a project wearing the built-in look the two agree; on any
 * other, `tChanges` reports the theme's OWN values as changes the moment the tab
 * opens. The server answers in this one - `_theme_changes(before=saved,
 * after=incoming)` - so a dialog built on the other disagreed with the save it
 * had just described, and registering it as unsaved work would interrupt every
 * close on a themed project.
 *
 * @returns {ThemeChange[]} one row per token and mode whose draft value differs
 *   from the value on disk, in group then token then mode order
 */
function tUnsaved(){return tDiff(tSavedVal);}
/**
 * The theme's unsaved work as CHANGE ROWS, in the shape every other surface
 * reports and every reader of a row expects.
 *
 * Built through `cfRow`, which is what makes the key `target` rather than a
 * `scope` of this surface's own. Two readers dereference it and both used to get
 * `undefined` here: the confirm dialog printed a blank target cell and stamped
 * `data-cfrow="undefined <field>"`, and `cfTouched` - which decides the phases a
 * lock notice names - collected a null for every theme row.
 *
 * @returns {Array<{target: string, field: string, from: *, to: *}>} token rows
 *   then layout rows, each field naming the token and, for a two-valued token,
 *   its mode
 */
/**
 * How a change row NAMES a token: the token, and its mode where the mode says
 * something. A single-valued token has one column, and a LAYOUT row has no mode
 * at all - it carries `mode:''`.
 *
 * That empty mode is why this is a function. Both callers used to append
 * `' · '+ch.mode` unless the token was single-valued, which spelled a layout row
 * `'layout · density · '` - a dangling separator in the dialog, and a field that
 * never equalled the `'layout · density'` the server echoes back. So every
 * density or card-order save reported "not exactly what the dialog listed", from
 * a difference of two characters nobody could see.
 *
 * @param {ThemeChange} ch - a row from tUnsaved, tChanges or tLayChanges
 * @returns {string} the `field` of the change row
 */
const tRowField=ch=>ch.token+(ch.mode&&!tSingle(ch.token)?' · '+ch.mode:'');
function tChangeRows(){return tUnsaved().concat(tLayChanges())
 .map(ch=>cfRow('theme',tRowField(ch),ch.from,ch.to));}
/**
 * What Reset is about to do, as change rows.
 *
 * DEFAULT-relative, unlike tChangeRows, and reversed. Reset removes the theme
 * FILE, so the destination is the built-in look rather than what is on disk -
 * and the dialog has to describe what reset will do, not what the draft did.
 *
 * @returns {Array<{target: string, field: string, from: *, to: *}>}
 */
function tResetRows(){return tChanges().concat(tLayChanges())
 .map(ch=>cfRow('theme',tRowField(ch),ch.to,ch.from));}
function tLayChanges(){
 const cur=tLayout(),base=(THEME&&THEME.layout)||{};
 const out=[];
 // AGAINST THE SAVED LAYOUT, like the order below it and like Python. This used
 // to compare the density with the shipped 'comfortable' constant, so wearing a
 // theme that NAMES a density read as one unsaved change the moment it loaded -
 // and because `appliedDiff` keys on `field`, pressing Save then produced
 // "Saved, but not exactly what the dialog listed" for a change nobody made.
 // `_panel_write._layout_changes` compares `before.density != after.density`;
 // this is that comparison, with the same display fallback.
 const shipped='comfortable';
 if((cur.density||shipped)!==(base.density||shipped))
  out.push({token:'layout · density',mode:'',
    from:base.density||shipped,to:cur.density||shipped,layout:1});
 Object.keys(cur.order||{}).forEach(view=>{
  const now=(cur.order[view]||[]).join(', ');
  // Measured against the SAVED order, like the density above it. This comment
  // used to say "unlike the density, which is measured against the shipped
  // default" - true when it was written, and left standing four lines below the
  // note explaining that the density had been changed to match. Two comments in
  // one function disagreeing about one rule is worse than neither.
  const was=((base.order||{})[view]||[]).join(', ');
  // An order equal to the DRAWN one is not a change: moving a card down and
  // back up must leave the tab saying "no changes", not offering to write an
  // order that says what the default already says. Named `drawn` rather than
  // shadowing the density's `shipped` above, which is a different default.
  const drawn=((THEME&&THEME.cards)||{})[view];
  const isDefault=Array.isArray(drawn)&&now===drawn.join(', ');
  if(now&&now!==was&&!isDefault)out.push({token:'layout · order · '+view,mode:'',
    from:was||'(default)',to:now,layout:1});});
 return out;}
// The draft, as the payload the server takes: only what differs from the
// default is written, so a theme file says what its author decided and nothing
// more (and a later change to a default reaches everyone who never overrode it).
/**
 * @returns {Object<string, ThemeToken>} the token map to PUT — one entry per
 *   token that differs from the default, carrying BOTH columns even when only
 *   one of them was edited, because a file naming one column would leave the
 *   other reading from a default that may move underneath it
 */
function tPayload(){
 const out={};
 tChanges().forEach(c=>{
  const e=out[c.token]||(out[c.token]={$value:tVal(c.token,'light')});
  if(!tSingle(c.token))e.$dark=tVal(c.token,'dark');});
 return out;}
// ---------- the live preview, and the undo trail ----------
// LIVE PREVIEW. The draft is written onto the document root as inline custom
// properties: the panel repaints instantly and honestly, because it is wearing
// the theme rather than showing a swatch of it. Cleared token by token, so a
// revert leaves nothing behind.
/** @type {string[]} the tokens tPaint last wrote onto :root */
let TPAINTED=[];
/**
 * Repaint the page in the draft, clearing whatever the last paint wrote.
 *
 * Only the column being WORN is painted, so a value typed into the other one
 * changes nothing on screen — correct, and baffling unless the editor says so,
 * which is what the ' · previewing' label in the table head is for.
 * @returns {void}
 */
function tPaint(){
 const root=document.documentElement;
 TPAINTED.forEach(n=>root.style.removeProperty(n));
 TPAINTED=[];
 const dark=isDark();
 tChanges().forEach(c=>{
  if(c.mode!==(dark?'dark':'light'))return;
  root.style.setProperty(c.token,String(c.to));TPAINTED.push(c.token);});}
/**
 * Put one value into the draft, repaint, and record the step.
 *
 * The other column is copied into the draft entry alongside it, so a token the
 * editor holds always carries both — tPayload says why a half-named token is not
 * something this may write.
 * @param {string} name - the custom property
 * @param {'light'|'dark'} mode - which column
 * @param {string} value - the new value; equal to the current one is a no-op, so
 *   repainting on every keystroke does not fill the undo trail with nothing
 * @param {boolean} [record] - false while undoing or redoing, where the step is
 *   already on a trail and recording it again would leave undo unable to reach
 *   the beginning. Anything else, omitted included, records.
 * @returns {void}
 */
function tSet(name,mode,value,record){
 const was=tVal(name,mode);
 // `undefined` means CLEAR THE OVERRIDE, which the Revert control produces for any
 // token the default payload does not name (`tDefault` answers undefined there).
 // Clearing is only a change if what it falls back to differs — and comparing
 // `was` with `String(undefined)` never matched, so a revert that changed nothing
 // recorded an undo step and counted as one unsaved change.
 //
 // Asked of tVal rather than by re-deriving the fallback chain: there is one
 // chain and it lives in tVal.
 if(value===undefined){
  const cur=TDRAFT&&TDRAFT[name];
  if(!cur)return;                      // no override to clear
  const keep=cur[tKey(mode)];
  cur[tKey(mode)]=undefined;
  const after=tVal(name,mode);
  cur[tKey(mode)]=keep;
  if(String(was)===String(after))return;
 } else if(String(was)===String(value))return;
 TDRAFT=TDRAFT||{};
 const e=TDRAFT[name]||(TDRAFT[name]={$value:tVal(name,'light')});
 if(!tSingle(name)&&e.$dark===undefined)e.$dark=tVal(name,'dark');
 e[tKey(mode)]=value;
 if(record!==false){TUNDO.push({token:name,mode:mode,from:was,to:value});TREDO=[];}
 tPaint();}
/**
 * Take one step off a trail, apply it backwards, and push the inverse onto the
 * other trail — which is why Undo and Redo are this one function with the stacks
 * swapped rather than two implementations free to drift apart.
 *
 * The step is applied with `record` false: recording it would push it straight
 * back onto the trail it came from and undo would never reach the beginning.
 * @param {ThemeChange[]} stack - the trail to take a step from; empty is a no-op
 * @param {ThemeChange[]} other - the trail the inverse step goes onto
 * @returns {void}
 */
function tUndo(stack,other){
 const step=stack.pop();if(!step)return;
 tSet(step.token,step.mode,step.from,false);
 // ALWAYS THE INVERSE. This used to push the step back UNCHANGED when its `to`
 // was undefined, reasoning that such a step "has no inverse to offer" — but the
 // inverse is `{from: undefined, to: <the old value>}`, and applying an undefined
 // `from` is precisely the clear. Pushed unchanged, Redo applied `from` instead:
 // the value Undo had just restored, so Redo repeated the undo.
 other.push({token:step.token,mode:step.mode,from:step.to,to:step.from});
 renderAppearance();}
/**
 * The value as a six-digit hex colour, or null when it is not one.
 *
 * Null is what tells the editor this token gets no colour picker beside it — a
 * font stack, a radius — and tells tLum there is no luminance to compute. The
 * three- and eight-digit forms are deliberately refused: `<input type=color>`
 * takes exactly this spelling and nothing else.
 * @param {*} v - anything a token might hold
 * @returns {string|null} the value unchanged when it is #rrggbb, else null
 */
function tHex(v){return /^#[0-9a-fA-F]{6}$/.test(String(v||''))?String(v):null;}
