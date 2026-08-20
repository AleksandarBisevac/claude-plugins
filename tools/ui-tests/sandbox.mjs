// Load plugins/audit/scripts/ui/*.js in a node:vm sandbox and hand back the
// functions inside them, WITHOUT editing either source file.
//
// Why this exists at all: those two files are ordered parts of one inline
// <script>. There is no module system, nothing is exported, and the ~721 exact
// substring pins on the Python side read TEXT, never behaviour. So a formatter
// can disagree with the Python it claims to mirror and every gate stays green.
// This is the missing layer: run the real bytes, call the real function.
//
// TWO DIFFERENT PROBLEMS, TWO DIFFERENT ANSWERS.
//
//   report.js is one file-spanning IIFE. Every name inside it is unreachable
//   from outside by construction. The wrapper is stripped HERE, in memory, so
//   the declarations land on the sandbox's global — the file on disk is never
//   touched. The wrapper text is pinned below; if it moves, this throws by name
//   instead of quietly testing a truncated file.
//
//   panel.js is already top-level, but it opens with placeholders the Python
//   substitutes at serve time (__AUDIT_TOKEN__ and friends) and it touches the
//   DOM while it loads. The placeholders are substituted here and the DOM is
//   shimmed. Top-level `const` in a vm Script lands in the context's global
//   LEXICAL environment, which persists across runInContext calls — that is
//   what makes `uTok` reachable afterwards even though nothing exports it.
//
// WHAT THIS CANNOT REACH, said plainly rather than discovered later:
//
//   Anything declared inside a nested function. Both heatmap calendars
//   (startOf / endOf / shift / seek / hasData / the weekday helper, written
//   twice under the same names) live inside an inner scope and close over
//   locals — report.js's inside a nested IIFE, panel.js's inside uHeatmap.
//   Neither is reachable without changing the source, so neither is tested
//   here. Reaching them is a source change, and a source change is a separate
//   decision from adding a test.
//
//   Anything whose behaviour IS the DOM. The shim below is a stub, not a
//   browser: it stores attributes and returns stub elements, and it says
//   nothing true about layout, event order or rendering. Those belong to the
//   browser gates (tools/capture-screenshots.mjs, tools/check-report-interactive.mjs)
//   and this file does not compete with them. Only pure functions are asserted
//   through here.

import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';

const HERE = path.dirname(url.fileURLToPath(import.meta.url));

export const REPO_ROOT = path.resolve(HERE, '..', '..');
export const UI_DIR = path.join(REPO_ROOT, 'plugins', 'audit', 'scripts', 'ui');

// Read, never enumerated. A hand-kept list is a list that goes stale the day a
// part is added, and a part nobody parses is the exact failure `node --check`
// exists to catch. Callers assert the COUNT so an empty directory — or a walk
// that silently found nothing — cannot read as "every part is fine".
export function uiParts() {
  const out = [];
  const walk = (dir, prefix) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const rel = prefix ? prefix + '/' + entry.name : entry.name;
      if (entry.isDirectory()) walk(path.join(dir, entry.name), rel);
      else if (entry.name.endsWith('.js')) out.push(rel);
    }
  };
  walk(UI_DIR, '');
  return out.sort();
}

// The Python that assembles the page is the ONE source of truth for which parts
// exist and what order they load in. Reading it here means this harness cannot
// hold a second opinion that drifts: add a part and forget to register it, and
// the list this returns is the list the page is really built from, so the gap
// shows up as a part nobody parses rather than as two files agreeing with each
// other and neither with the product.
const PANEL_UI_PY = path.join(REPO_ROOT, 'plugins', 'audit', 'scripts', 'panel',
                              '_panel_ui.py');
const REPORT_UI_PY = path.join(REPO_ROOT, 'plugins', 'audit', 'scripts', 'report',
  '_report_ui.py');

function readReportUiPy() {
  return fs.readFileSync(REPORT_UI_PY, 'utf8');
}

export function reportParts() {
  const block = readReportUiPy().match(/_SCRIPT_PARTS = \(([\s\S]*?)\)/);
  if (!block) {
    throw new Error('_SCRIPT_PARTS is not in ' + REPORT_UI_PY
      + ' — the assembly moved and this harness would otherwise read a stale list');
  }
  const names = [...block[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
  if (!names.length) {
    throw new Error('_SCRIPT_PARTS is empty; joining nothing would load a blank '
      + 'script and every case below would pass over it');
  }
  return names;
}

// The wrapper the page gets, read from the same place, for the same reason.
// The tags the page receives, read from the same place. There is no code
// wrapper any more: the script is a module, and a module's own scope is what
// keeps the parts' top-level names out of the page's globals.
export function reportTags() {
  const py = readReportUiPy();
  const open = py.match(/_SCRIPT_TAG_OPEN = '([^']*)'/);
  const close = py.match(/_SCRIPT_TAG_CLOSE = "([^"]*)"/);
  if (!open || !close) {
    throw new Error('_SCRIPT_TAG_OPEN/_SCRIPT_TAG_CLOSE are not in ' + REPORT_UI_PY);
  }
  return { open: open[1], close: close[1] };
}

// The report's body exactly as the page receives it, minus the wrapper: the
// parts joined in load order. This is what runs in the sandbox, because the
// wrapper only creates a scope the sandbox already provides.
export function assembleReportBody() {
  return reportParts().map((n) => readPart(n)).join('');
}

export function readPart(name) {
  return fs.readFileSync(path.join(UI_DIR, name), 'utf8');
}

// The panel's parts, read the same way and for the same reason: the ORDER is
// declared once, in the module that assembles the page, and a harness that kept
// its own copy would go on loading a stale list after a part was added.
function readPanelUiPy() {
  return fs.readFileSync(PANEL_UI_PY, 'utf8');
}

export function panelParts() {
  const block = readPanelUiPy().match(/_JS_PARTS = \(([\s\S]*?)\)/);
  if (!block) {
    throw new Error('_JS_PARTS is not in ' + PANEL_UI_PY
      + ' \u2014 the assembly moved and this harness would otherwise read a stale list');
  }
  const names = [...block[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
  if (!names.length) {
    throw new Error('_JS_PARTS is empty; joining nothing would load a blank '
      + 'script and every case below would pass over it');
  }
  return names;
}

// The panel's script exactly as the page receives it: the parts joined in load
// order. There is no wrapper on this surface at all - the page gets one classic
// <script>, so the concatenation IS the scope.
export function assemblePanelBody() {
  return panelParts().map((n) => readPart(n)).join('');
}

// --- the shim -------------------------------------------------------------

function stubElement(tag) {
  const attrs = new Map();
  const self = {
    nodeType: 1,
    tagName: String(tag || 'div').toUpperCase(),
    id: '',
    textContent: '',
    innerHTML: '',
    value: '',
    href: '',
    download: '',
    hidden: false,
    disabled: false,
    checked: false,
    className: '',
    tabIndex: 0,
    dataset: {},
    cells: [],
    rows: [],
    children: [],
    parentNode: null,
    firstChild: null,
    nextSibling: null,
    style: { setProperty() {}, removeProperty() {}, getPropertyValue() { return ''; } },
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    // Attributes are really stored. isDark() reads data-theme off the root
    // element, so a setAttribute that forgot its value would make every theme
    // case agree with every other one for the wrong reason.
    setAttribute(k, v) { attrs.set(String(k), String(v)); },
    getAttribute(k) { return attrs.has(String(k)) ? attrs.get(String(k)) : null; },
    removeAttribute(k) { attrs.delete(String(k)); },
    hasAttribute(k) { return attrs.has(String(k)); },
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; },
    appendChild(c) { return c; }, append() {}, prepend() {}, remove() {},
    insertBefore(c) { return c; }, replaceChildren() {},
    click() {}, focus() {}, blur() {}, scrollIntoView() {}, closest() { return null; },
    querySelector() { return stubElement('div'); },
    querySelectorAll() { return []; },
    getBoundingClientRect() {
      return { top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0 };
    },
  };
  return self;
}

function stubDocument() {
  const doc = {
    documentElement: stubElement('html'),
    body: stubElement('body'),
    head: stubElement('head'),
    activeElement: null,
    readyState: 'complete',
    title: '',
    // getElementById returns null on purpose: report.js is written to survive a
    // missing element (an embedded report has no theme button), and returning a
    // stub for everything would run code paths a real page never reaches.
    getElementById() { return null; },
    querySelector() { return stubElement('div'); },
    querySelectorAll() { return []; },
    getElementsByClassName() { return []; },
    createElement(t) { return stubElement(t); },
    createTextNode(t) { return { nodeType: 3, textContent: String(t) }; },
    createDocumentFragment() { return stubElement('#fragment'); },
    addEventListener() {}, removeEventListener() {},
  };
  return doc;
}

function stubWindow(options) {
  const doc = stubDocument();
  const prefersDark = options.prefersDark === true;
  // RECORDED, not printed, and reachable as `loaded.consoleErrors`.
  //
  // The page's own last line is `boot().catch(...)`, so loading it here RUNS a
  // boot - and the stub DOM cannot render most views, so several renderers throw.
  // They used to be invisible because boot died at the first one; now that each
  // failure is contained, every one of them reported, on every load, in every
  // suite. Hundreds of identical lines is not more honest than none: it teaches a
  // reader to scroll past console output, which is precisely where a REAL failure
  // would appear. Kept, and assertable, rather than discarded or shouted.
  const consoleErrors = [];
  const rec = (level) => (...args) => { consoleErrors.push([level, ...args]); };
  const win = {
    console: { error: rec('error'), warn: rec('warn'), log: rec('log'),
      info: rec('info'), debug: rec('debug') },
    __consoleErrors: consoleErrors,
    document: doc,
    location: {
      hash: options.hash || '',
      search: '',
      href: 'file:///report.html',
      pathname: '/report.html',
      origin: 'null',
    },
    history: { replaceState() {}, pushState() {} },
    navigator: { userAgent: 'node', platform: 'node', clipboard: { writeText: async () => {} } },
    // Storage is best-effort in the product (file:// blocks it), so the stub is
    // the blocked shape: reads return null, writes go nowhere.
    localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    sessionStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    matchMedia: (q) => ({
      media: String(q || ''),
      matches: /dark/.test(String(q || '')) ? prefersDark : false,
      addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
    }),
    setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0, clearInterval() {},
    requestAnimationFrame: () => 0, cancelAnimationFrame() {},
    fetch: async () => ({ ok: true, json: async () => ({}), text: async () => '' }),
    // The real one from this Node, not a stub: `api()` builds a signal and hands
    // it to fetch, so a fake that merely has the shape would let a change to the
    // timeout path pass unnoticed. Without it `boot()` rejects on its first call
    // and nothing after the first await is reachable from a test at all.
    AbortController,
    URL: { createObjectURL: () => 'blob:stub', revokeObjectURL() {} },
    Blob: function Blob() {},
    FormData: function FormData() {},
    getComputedStyle: () => ({ getPropertyValue: () => '' }),
    addEventListener() {}, removeEventListener() {},
    open() { return null; }, print() {}, alert() {}, scrollTo() {},
    innerWidth: 1280, innerHeight: 900, devicePixelRatio: 1,
    AUDIT_USAGE: options.usage === undefined ? null : options.usage,
    AUDIT_MD_NAME: options.mdName === undefined ? 'audit-report.md' : options.mdName,
  };
  win.window = win;
  win.self = win;
  doc.defaultView = win;
  return win;
}

// --- report.js ------------------------------------------------------------

// Pinned as bytes. report.js is `\n(function () {\n` … `})();\n` and nothing
// else may be assumed: a reformat that turns the head into `(function() {` must
// stop this file, not silently shorten it. Both ends are checked, because
// slicing a length off a string that does not start with it succeeds quietly.

// --- panel.js -------------------------------------------------------------

// The two the panel server substitutes per REQUEST, and the only two that must
// be strings — every other placeholder is a JSON object the page reads later.
// Named here rather than imported from the Python: this harness must not carry
// an opinion about where that module currently lives.
export const PANEL_STRING_PLACEHOLDERS = ['__AUDIT_TOKEN__', '__AUDIT_PROJECT__'];

const PLACEHOLDER_RE = /__[A-Z0-9_]+__/g;

export function substitutePanelPlaceholders(src, overrides) {
  const seen = new Set();
  const given = overrides || {};
  const out = src.replace(PLACEHOLDER_RE, (m) => {
    seen.add(m);
    // An override is the REAL value, and it exists because five of these
    // placeholders are the cross-language channel: the server substitutes a
    // Python constant into them. Stubbing them all as `{}` means a sandbox case
    // about `TPAIRS` or `COST_BAND_PARAMS` runs against an empty object and
    // proves nothing about the table that actually ships. A case that needs the
    // real one asks for it; the default stays a stub so nothing else pays.
    if (Object.prototype.hasOwnProperty.call(given, m)) return given[m];
    return PANEL_STRING_PLACEHOLDERS.indexOf(m) >= 0
      ? JSON.stringify(m === '__AUDIT_TOKEN__' ? 'ui-test-token' : '/tmp/ui-test-project')
      : '{}';
  });
  if (!seen.size) {
    throw new Error(
      'the panel parts carry no __PLACEHOLDER__ at all. Either the substitution '
      + 'contract changed or this harness read the wrong file — both are '
      + 'reasons to stop, not to load a file that may no longer be the panel.');
  }
  for (const name of PANEL_STRING_PLACEHOLDERS) {
    if (!seen.has(name)) {
      throw new Error(
        'the panel parts no longer carry ' + name + '. It is substituted as a STRING '
        + 'literal here; a placeholder that has become something else needs a '
        + 'deliberate update to PANEL_STRING_PLACEHOLDERS.');
    }
  }
  return { source: out, placeholders: [...seen].sort() };
}

// --- loading --------------------------------------------------------------

function loadInto(sourceText, filename, options) {
  const sandbox = stubWindow(options || {});
  const ctx = vm.createContext(sandbox);
  vm.runInContext(sourceText, ctx, { filename });
  return { sandbox, ctx };
}

// `mutate` is applied to the RAW file text, before unwrapping or substituting,
// so a mutation can target the wrapper and the placeholders as well as the
// body. It exists for tools/ui-tests/mutants.test.mjs — the file that proves
// these cases can fail — and it never writes anything to disk.
function mutated(src, options) {
  return (options && options.mutate) ? options.mutate(src) : src;
}

// Names come back through an object literal evaluated INSIDE the context, which
// is the only way to see a top-level `const`: it lives in the context's global
// lexical environment, not on the global object. A name that is not there
// throws a ReferenceError naming it — the loud failure this needs.
export function reach(ctx, names) {
  const list = names.join(', ');
  try {
    return vm.runInContext('({ ' + list + ' })', ctx);
  } catch (cause) {
    throw new Error('cannot reach [' + list + '] in the loaded source: ' + cause.message);
  }
}

export function loadReport(options) {
  const opts = options || {};
  const loaded = loadInto(mutated(assembleReportBody(), opts), 'report parts', opts);
  loaded.consoleErrors = loaded.ctx.__consoleErrors;
  return loaded;
}

export function loadPanel(options) {
  const opts = options || {};
  const prepared = substitutePanelPlaceholders(mutated(assemblePanelBody(), opts),
                                              opts.placeholders);
  const loaded = loadInto(prepared.source, 'panel parts', opts);
  loaded.placeholders = prepared.placeholders;
  loaded.consoleErrors = loaded.ctx.__consoleErrors;
  return loaded;
}
