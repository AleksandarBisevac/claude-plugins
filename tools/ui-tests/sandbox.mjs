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
//   Anything declared inside a nested function. This note used to name both
//   heatmap calendars as the example — startOf / endOf / shift / seek and a
//   weekday helper, written twice under the same names, one copy inside the
//   report's IIFE and one inside the panel's uHeatmap — and said that reaching
//   them was a source change, and a source change a separate decision from
//   adding a test. That decision was taken: they are one `shared/calendar.js`
//   now, they close over nothing, and tools/ui-tests/calendar.test.mjs is the
//   test this note was waiting for. The DATA half stayed behind in each surface
//   and is still out of reach from here, which is why the calendar takes it as a
//   predicate rather than closing over it.
//
//   The limit itself stands: a name declared inside a function is not reachable
//   from this harness, and the answer is to hoist what deserves hoisting rather
//   than to reach further.
//
//   Anything whose behaviour IS the DOM. The shim below is a stub, not a
//   browser: it stores attributes and returns stub elements, and it says
//   nothing true about layout, event order or rendering. Those belong to the
//   browser gates (tools/capture-screenshots.mjs, tools/check-report-interactive.mjs)
//   and this file does not compete with them.
//
//   It does store LISTENERS, and `__fire(type)` calls the ones registered on
//   that element for that type. So a handler is reachable — which is the whole
//   difference between asserting what a control is built LIKE and asserting what
//   pressing it DOES. What is still absent is everything that makes a real
//   event: no bubbling, no capture phase, no ordering between elements, no
//   default action, and no proof that the element is even in a document. A claim
//   that depends on any of those is a browser-gate claim, and calling `__fire`
//   on a chain of parents would be inventing propagation rather than testing it.

import { execFileSync, spawnSync } from 'node:child_process';
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

// --- the python bridge ----------------------------------------------------
//
// Moved here from python-fmt.mjs, which now imports it back. It had to live
// somewhere BELOW that file: `sandbox.mjs` owns REPO_ROOT and python-fmt.mjs
// reads it at module scope, so a static import in the other direction closes a
// cycle whose python-fmt half evaluates first and reads REPO_ROOT in its TDZ.
// One bridge and one dependency direction, rather than a second copy of the
// interpreter probe that could pick a different interpreter than the one the
// formatter cases compare against.

const SCRIPTS_DIR = path.join(REPO_ROOT, 'plugins', 'audit', 'scripts');

const CANDIDATES = ['python3', 'python'];

let cachedInterpreter = null;

// Never a skip. A missing interpreter means the cross-language claim was not
// checked, and a suite that quietly drops its only real assertion is the exact
// silent pass this repo rejects — so it throws, and the run goes red.
export function pythonInterpreter() {
  if (cachedInterpreter) return cachedInterpreter;
  const tried = [];
  for (const exe of CANDIDATES) {
    const probe = spawnSync(exe, ['-c', 'import sys; print(sys.version_info[0])'],
      { encoding: 'utf8' });
    if (probe.status === 0 && probe.stdout.trim() === '3') {
      cachedInterpreter = exe;
      return exe;
    }
    tried.push(exe + ': ' + (probe.error ? probe.error.message
      : 'exit ' + probe.status + ' ' + (probe.stdout + probe.stderr).trim()));
  }
  throw new Error(
    'no Python 3 on PATH, so the cross-language formatter cases cannot run and '
    + 'are NOT being silently skipped. Tried:\n  ' + tried.join('\n  '));
}

// The module is an ARGUMENT, so a second cross-language claim does not need a
// second copy of this protocol. It began as `_fmt` only; `_ui_theme` joined it
// when the contrast checker turned out to grade four pairs against Python's six,
// and the fix was to stop having two tables rather than to align them by hand.
//
// `sys.argv[3]` is an EXTRA directory, empty for every production caller. It
// exists so the part readers below can be pointed at a fixture module instead of
// the shipped one — a reader that can only ever be run against the real file is a
// reader whose failure mode cannot be reproduced, which is how F129 survived.
const BRIDGE = [
  'import importlib, json, os, sys',
  'sys.path.insert(0, sys.argv[1])',
  // install_path() puts scripts/ AND every subdirectory of it holding a .py on
  // the path, which is how the plugin itself resolves a sibling: by BARE
  // BASENAME, because the folders under scripts/ are labels rather than
  // namespaces. Without it this bridge could only reach the modules at the root,
  // and `_panel_write` — which owns the change rows the panel's dialog is
  // compared against — sits in scripts/panel/.
  "import _output; _output.install_path()",
  'if len(sys.argv) > 3 and sys.argv[3]:',
  '    sys.path.insert(0, sys.argv[3])',
  'mod = importlib.import_module(sys.argv[2])',
  'calls = json.load(sys.stdin)',
  'out = []',
  'for name, args in calls:',
  '    fn = getattr(mod, name, None)',
  '    if fn is None:',
  '        sys.exit("%s has no attribute %r" % (sys.argv[2], name))',
  '    out.append(fn(*args) if callable(fn) else fn)',
  'json.dump(out, sys.stdout)',
].join('\n');

/**
 * Run a batch of calls against any module under `scripts/`, in order.
 *
 * A non-callable attribute is returned as its VALUE, so a table can be compared
 * as directly as a function result — which is the point for `CONTRAST_PAIRS`
 * and its like: the claim is that the JavaScript reads Python's table, and the
 * only way to check that is to fetch the table.
 *
 * @param {string} moduleName e.g. `'_ui_theme'`
 * @param {Array<[string, Array<unknown>]>} calls
 * @param {string} [extraPath] a directory searched before `scripts/`, for
 *   fixture modules; production callers omit it
 */
export function pyCall(moduleName, calls, extraPath) {
  if (!Array.isArray(calls) || !calls.length) {
    throw new Error('pyCall called with no cases — an empty batch would return an '
      + 'empty list and every comparison over it would vacuously pass');
  }
  const exe = pythonInterpreter();
  let stdout;
  try {
    stdout = execFileSync(exe, ['-c', BRIDGE, SCRIPTS_DIR, moduleName, extraPath || ''], {
      input: JSON.stringify(calls),
      encoding: 'utf8',
      // stdout is the ANSWER even on a non-zero exit here, so both streams are
      // captured and both are reported on failure.
      stdio: ['pipe', 'pipe', 'pipe'],
    });
  } catch (cause) {
    throw new Error('the ' + moduleName + ' bridge failed (' + exe + '): '
      + String(cause.stderr || cause.message).trim()
      + '\nstdout was: ' + String(cause.stdout || '').trim());
  }
  const out = JSON.parse(stdout);
  if (out.length !== calls.length) {
    throw new Error('the ' + moduleName + ' bridge returned ' + out.length + ' results for '
      + calls.length + ' calls');
  }
  return out;
}

// --- the part lists -------------------------------------------------------
//
// The Python that assembles the page is the ONE source of truth for which parts
// exist and what order they load in. Asking it here means this harness cannot
// hold a second opinion that drifts: add a part and forget to register it, and
// the list this returns is the list the page is really built from, so the gap
// shows up as a part nobody parses rather than as two files agreeing with each
// other and neither with the product.
//
// ASKED, NOT PARSED, and that distinction is F129. This used to match
// `_JS_PARTS = \(([\s\S]*?)\)` over the module's SOURCE — a second Python parser,
// written as one regex, which ended at the first closing parenthesis. A comment
// inside the tuple containing one therefore truncated the list, and every browser
// suite then loaded a panel missing its tail: the symptom was a function that did
// not exist, never "the list was cut short". The workaround at the time was to
// take the parentheses out of the comment. The regex was the defect, and the fact
// it read is one the source already owns, so this asks the module for its own
// value instead. A comment cannot defeat the interpreter that compiled it, and
// neither can a quote style, a line break or a value that stops being a literal.

let reportCache = null;
let panelCache = null;

/**
 * One Python tuple of asset names, checked for the shapes a truncation takes.
 *
 * COMPLETENESS CANNOT BE ASSERTED FROM HERE — this has no second opinion about
 * how many parts there ought to be, and inventing one would be the drifting copy
 * the whole file avoids. What it can refuse is a list that is not a list of asset
 * names at all, and the empty case, which is the one a short read degenerates to.
 *
 * @param {string} moduleName the Python module holding the tuple
 * @param {string} attr its name there
 * @param {string} [extraPath] a directory searched first, for fixture modules
 */
export function pyParts(moduleName, attr, extraPath) {
  const [names] = pyCall(moduleName, [[attr, []]], extraPath);
  if (!Array.isArray(names)) {
    throw new Error(moduleName + '.' + attr + ' is ' + JSON.stringify(names)
      + ', not a list of asset names — the assembly changed shape and this '
      + 'harness would otherwise iterate something that is not the part list');
  }
  if (!names.length) {
    throw new Error(moduleName + '.' + attr + ' is empty; joining nothing would '
      + 'load a blank script and every case over it would pass having run none '
      + 'of the page');
  }
  const odd = names.filter((n) => typeof n !== 'string' || !n.endsWith('.js'));
  if (odd.length) {
    throw new Error(moduleName + '.' + attr + ' holds ' + JSON.stringify(odd)
      + ', which are not `.js` asset names');
  }
  return names;
}

function reportUi() {
  if (!reportCache) {
    const [open, close] = pyCall('_report_ui',
      [['_SCRIPT_TAG_OPEN', []], ['_SCRIPT_TAG_CLOSE', []]]);
    reportCache = { parts: pyParts('_report_ui', '_SCRIPT_PARTS'), open, close };
  }
  return reportCache;
}

export function reportParts() {
  return reportUi().parts;
}

// The tags the page receives, read from the same place. There is no code
// wrapper any more: the script is a module, and a module's own scope is what
// keeps the parts' top-level names out of the page's globals.
export function reportTags() {
  const { open, close } = reportUi();
  return { open, close };
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

// The panel's parts, asked the same way and for the same reason: the ORDER is
// declared once, in the module that assembles the page, and a harness that kept
// its own copy would go on loading a stale list after a part was added.
export function panelParts() {
  if (!panelCache) panelCache = pyParts('_panel_ui', '_JS_PARTS');
  return panelCache;
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
  const listeners = {};
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
    // RECORDED, and reachable as `__fire(type, ev)`. They used to be dropped,
    // which meant no suite could reach a handler at all: `el()` wires an `onclick`
    // key through addEventListener, so every button built by the page was inert
    // here and every claim about what pressing one DOES had to be taken on trust
    // or driven in a browser. Storing them costs nothing and does not change any
    // existing case, because nothing dispatched before.
    //
    // This is still not a browser: no bubbling, no capture order, no default
    // actions. `__fire` calls the handlers registered on THIS element for THIS
    // type, in order, and returns what they returned — so a handler that awaits
    // can be awaited. Anything depending on propagation belongs in a browser gate.
    addEventListener(t, fn) {
      if (typeof fn !== 'function') return;
      const key = String(t);
      (listeners[key] || (listeners[key] = [])).push(fn);
    },
    removeEventListener(t, fn) {
      const l = listeners[String(t)];
      if (l) listeners[String(t)] = l.filter((f) => f !== fn);
    },
    dispatchEvent() { return true; },
    __listeners: listeners,
    __fire(t, ev) {
      const l = listeners[String(t)] || [];
      return l.map((fn) => fn.call(self, ev || { type: String(t),
        target: self, preventDefault() {}, stopPropagation() {} })).pop();
    },
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
