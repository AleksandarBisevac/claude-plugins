// ---------- capability policy: the switchboard ----------
// `{"default":"deny","allow":["code-*"]}` is four words that decide the fate of
// every skill on the machine, and nobody can hold that cross-product in their
// head. This view IS the cross-product: one row per capability the project can
// actually reach, the verdict the guard would give it, and the reason.
//
// Two rules run through all of it.
//
// The verdicts are the SERVER's — computed by `_policy.resolve`, the function the
// hook itself calls — and are never recomputed here. A second matcher in the
// browser would eventually disagree with the guard, and disagreeing about a denial
// is the one thing a preview must not do. The consequence is that a verdict is
// true of the SAVED policy: an edited row is marked as pending rather than
// re-judged, and the verdicts are re-read from the server after every save.
//
// And the draft is the block AS WRITTEN (`stored`), never the merged one. PUT
// /api/policy replaces the block wholesale, so anything this form does not
// represent — a comment key, a pattern nobody clicked — would be destroyed by
// someone who came to flip one switch. Which is also why the raw rules are a table
// of their own further down: a rule the form cannot show is a rule it must not be
// trusted to save.
let POLICY=null;
// null means "no policy block on disk, and nothing typed yet". It is not {}: an
// empty object is a policy someone wrote, and writing one where there was none is
// a change this view must not make by rendering.
let PDRAFT=null;
const PKINDS=['skills','agents','mcp'];
const PKLABEL={skills:'Skills',agents:'Subagents',mcp:'MCP servers'};
const PF={kind:'skills',q:'',bad:false};
// The nodes the last save left behind — the ✓/✗ box and, if the file had moved
// under the reader, the mismatch warning. A save re-renders the whole view to pick
// up the server's fresh verdicts, which would otherwise throw away the one part of
// the page that says what just happened. Consumed once, so an edit made afterwards
// does not sit under a stale "saved".
let PNOTE=null;
const pClone=o=>(o==null?null:JSON.parse(JSON.stringify(o)));
// Every edit goes through here. It drops the last save's box — that box describes
// a file this form no longer matches — and redraws.
function pEdit(fn){PNOTE=null;fn();renderPolicy();}
function pBlock(){if(PDRAFT===null)PDRAFT={};return PDRAFT;}
const pKindCfg=(b,k)=>((b||{})[k]||{});
const pEnabled=()=>((PDRAFT||{}).enabled!==false);
const pOnViolation=()=>((PDRAFT||{}).onViolation||(POLICY&&POLICY.onViolation)||'deny');
const pDefault=k=>(pKindCfg(PDRAFT,k).default==='deny'?'deny':'allow');
// What a violation DOES, in the words the hook uses. Said next to the control that
// picks it, because "deny" and "warn" are not degrees of the same thing: one
// refuses the call and one lets it through with a sentence attached.
const PVIOL={deny:'refuse the call',ask:'ask for approval, per call',
 warn:'allow it and say so'};
// Where this row's rule is written, for one scope: '' (nothing), 'allow', 'deny'.
// EXACT names only, and deliberately so — a glob that happens to match is not this
// row's rule to move, and silently dropping `code-*` because somebody pressed
// Default on one skill it covers would change the verdict of every other one. A
// pattern is edited where it is written, in the rules table below.
function pRuleOf(block,kind,name,tag){
 const k=pKindCfg(block,kind);
 const src=tag?((k.areas||{})[tag]||{}):k;
 for(const l of ['deny','allow'])if((src[l]||[]).indexOf(name)>=0)return l;
 return '';}
function pSetRule(kind,name,tag,val){
 const b=pBlock(),k=b[kind]=b[kind]||{};
 let src=k;
 if(tag){const a=k.areas=k.areas||{};src=a[tag]=a[tag]||{};}
 ['allow','deny'].forEach(l=>{if(!Array.isArray(src[l]))return;
  const i=src[l].indexOf(name);if(i>=0)src[l].splice(i,1);});
 if(val){src[val]=src[val]||[];src[val].push(name);}
 pPrune();}
function pAddPattern(kind,list,tag,pattern){
 const b=pBlock(),k=b[kind]=b[kind]||{};
 let src=k;
 if(tag){const a=k.areas=k.areas||{};src=a[tag]=a[tag]||{};}
 src[list]=src[list]||[];
 if(src[list].indexOf(pattern)<0)src[list].push(pattern);}
function pDropPattern(kind,list,tag,pattern){
 const src=tag?((pKindCfg(PDRAFT,kind).areas||{})[tag]||{}):pKindCfg(PDRAFT,kind);
 const arr=src[list];if(!Array.isArray(arr))return;
 const i=arr.indexOf(pattern);if(i>=0)arr.splice(i,1);
 pPrune();}
// Emptying a list REMOVES it, and removing the last one removes its container —
// the same convention Settings writes with, for the same reason: a block listing
// every default is a block nobody can read, and `"areas":{"web":{"deny":[]}}` is
// a rule that looks like a rule and is not one.
function pPrune(){
 if(!PDRAFT)return;
 for(const kind of PKINDS){
  const k=PDRAFT[kind];if(!k||typeof k!=='object')continue;
  ['allow','deny'].forEach(l=>{if(Array.isArray(k[l])&&!k[l].length)delete k[l];});
  if(k.areas&&typeof k.areas==='object'){
   for(const tag of Object.keys(k.areas)){const r=k.areas[tag]||{};
    ['allow','deny'].forEach(l=>{if(Array.isArray(r[l])&&!r[l].length)delete r[l];});
    if(!Object.keys(r).length)delete k.areas[tag];}
   if(!Object.keys(k.areas).length)delete k.areas;}
  if(!Object.keys(k).length)delete PDRAFT[kind];}}
// The change rows, computed the same way Settings computes its own: this block is
// one key of the config, the server writes it through the one config writer, and
// the echo comes back as `config · policy.skills.deny · … -> …`. So the dialog is
// fed a whole config with this block swapped in, and cannot describe the save in a
// vocabulary the server does not answer in.
function policyChanges(){
 if(PDRAFT===null)return [];
 const cfg=JSON.parse(JSON.stringify(STATE.config||{}));
 cfg.policy=PDRAFT;
 return configChanges(cfg);}
// Every pattern in the draft, in the order `resolve` reads them: deny before
// allow, project before area. Annotated from the server's own matching where the
// server has seen the pattern — a rule typed a second ago has no match count and
// says so rather than borrowing the count of the one it replaced.
function pDraftRules(kind){
 const out=[],k=pKindCfg(PDRAFT,kind);
 const push=(scope,list)=>{const src=scope?((k.areas||{})[scope]||{}):k;
  (src[list]||[]).forEach(p=>out.push({scope:scope||null,list:list,pattern:p}));};
 push(null,'deny');push(null,'allow');
 Object.keys(k.areas||{}).sort().forEach(tag=>{push(tag,'deny');push(tag,'allow');});
 return out;}
const pRuleKey=r=>JSON.stringify([r.scope||null,r.list,r.pattern]);
function pServerRules(kind){const m={};
 ((POLICY.rules||{})[kind]||[]).forEach(r=>{m[pRuleKey(r)]=r;});return m;}

// px (F-P-3): ONE builder for the capability table, used by the Policy tab and
// by the expanded dialog. `full` only decides the ids (a document may hold one
// element per id, and both copies carry a search box) and whether the frame
// caps its own height — in the dialog the DIALOG is the frame.
// px (F-P-3): the capability table, given the viewport. A native <dialog>, so
// the focus trap, the backdrop and Esc are the platform's — the browse dialog's
// pattern, and for the same reason: this is a LIST, and reading a verdict per
// area means reading across it. It lives on <body> (renderPolicy rebuilds the
// whole tab on every keystroke, and a dialog inside it would be destroyed
// mid-type), it is refilled from the same builder the tab uses, and the filter
// it types into is the TAB's filter — expanding never costs you your place.
let POLFULL=null;
function polFullFill(){
 if(!POLFULL||!POLFULL.open||!POLICY)return;
 const kind=PF.kind,rows=((POLICY.resolved||{})[kind]||[]);
 const cap=pCapTable(kind,rows,true);
 POLFULL.replaceChildren(
   el('div',{class:'bhead'},
     el('h3',{},PKLABEL[kind]+' — what this project can reach'),
     el('button',{class:'bx',title:'close','aria-label':'close',
       onclick:()=>POLFULL.close()},'\u2715')),
   cap.tools,cap.body);}
function polFullOpen(){
 if(!POLFULL){POLFULL=el('dialog',{class:'polfull'});
  POLFULL.addEventListener('click',ev=>{if(ev.target===POLFULL)POLFULL.close();});
  // An <input type=search> eats the FIRST Escape to clear itself, so a dialog
  // whose caret sits in one closes on the SECOND press — which reads as the key
  // being broken (the browse dialog hit this first). Handled on the dialog, not
  // on the box: the box is built by pCapTable and the tab's copy of it must not
  // close anything. One Escape, one effect.
  POLFULL.addEventListener('keydown',ev=>{
    if(ev.key==='Escape'){ev.preventDefault();POLFULL.close();}});
  document.body.append(POLFULL);}
 // Esc and the ✕ both land in dlgOpen's close handler, which gives the caret back
 // to the control that opened it — a dialog that closes into nowhere leaves a
 // keyboard reader at the top of the document. The selector is passed explicitly
 // because the node is gone by then: typing in the dialog re-renders the tab
 // underneath, which replaces that button. Keeping it AFTER the close is
 // renderPolicy's job, not this one's.
 dlgOpen(POLFULL,'#policy [data-polexpand]');polFullFill();}
