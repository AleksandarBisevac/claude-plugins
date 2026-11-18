// A confirmed write is read after the server has answered it, never after a timer.
//
// WHAT WENT WRONG. Every confirmed save in the panel gate was "click the dialog's
// primary button, sleep a fixed number of ms, read", and the number was a guess at
// how long the save takes. On a slow host the read landed before the write did:
// red on one machine, green on another. The fix was a helper, confirmWrite, that
// waits for the write's own response and for the page to act on it. The first
// conversion stopped at one file's boundary and left the same shape in a module that
// file imports, which is why the check below reads EVERY file the gate runs, derived
// from the tool's imports rather than listed by hand.
//
// WHAT IS POLICED. A click on the confirm dialog's primary button (the `data-cfgo`
// control) whose next awaited statement is a fixed wait - waitForTimeout, a
// setTimeout promise, or sleepPollWindow - is a finding, named by file and line,
// unless a row of CONFIRM_WAIT_ALLOWED in tools/ui-checks/confirm-write.mjs excuses
// it with a reason. A confirm that sends no request (a Discard) has no answer to
// wait for, and those are the rows. A row that excuses no site, or a different
// number of sites than it says, is a finding too.
//
// WHAT THIS CANNOT SEE: a confirm button reached through an alias
// (`const go = page.locator(...)` clicked later); a click inside a callback passed
// to a call (the scan splits statements only outside brackets); and a wait that is
// not one of the primitives named in FIXED_WAITS.
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, it } from 'vitest';
import { CONFIRM_WAIT_ALLOWED } from '../ui-checks/confirm-write.mjs';

const TOOLS = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const ENTRY = 'capture-screenshots.mjs';
const HELPER_FILE = 'ui-checks/confirm-write.mjs';
const HELPER = 'confirmWrite';
const FIXED_WAITS = ['waitForTimeout', 'setTimeout', 'sleepPollWindow'];

/**
 * Two copies of `src` with offsets and newlines kept: `code` with comments blanked,
 * `bare` with string and regex-literal contents blanked as well (their delimiters
 * kept), so a selector or a bracket inside a string does not move the structure.
 * A string or comment still open at the end of the file throws: the scan refuses a
 * source it cannot tokenise rather than reading the rest of it as code.
 */
function strip(src) {
  const code = [];
  const bare = [];
  const blankOf = (s) => s.replace(/[^\n]/g, ' ');
  const emit = (s, inCode, inBare) => {
    code.push(inCode ? s : blankOf(s));
    bare.push(inBare ? s : blankOf(s));
  };
  const lineAt = (at) => src.slice(0, at).split('\n').length;
  let tail = '';
  const remember = (s) => {
    const sig = s.replace(/\s+/g, ' ');
    if (sig.trim() !== '') tail = (tail + sig).slice(-12);
  };
  let i = 0;
  while (i < src.length) {
    const c = src[i];
    const n = src[i + 1];
    if (c === '/' && n === '/') {
      let e = src.indexOf('\n', i);
      if (e < 0) e = src.length;
      emit(src.slice(i, e), false, false);
      i = e;
    } else if (c === '/' && n === '*') {
      const e = src.indexOf('*/', i + 2);
      if (e < 0) throw new Error('strip(): the comment opened at line ' + lineAt(i) + ' is not closed');
      emit(src.slice(i, e + 2), false, false);
      i = e + 2;
    } else if (c === '"' || c === "'" || c === '`') {
      let j = i + 1;
      while (j < src.length && src[j] !== c) j += src[j] === '\\' ? 2 : 1;
      if (j >= src.length) {
        throw new Error('strip(): the string opened at line ' + lineAt(i)
          + ' is not closed before the end of the file, so the rest was not scanned');
      }
      emit(c, true, true);
      emit(src.slice(i + 1, j), true, false);
      emit(c, true, true);
      remember(c);
      i = j + 1;
    } else if (c === '/' && (/[(,=:[!&|?{};+\-*%<>~^]\s*$/.test(tail) || tail.trim() === ''
        || /\b(?:return|typeof|case|of|in|await|yield)\s*$/.test(tail))) {
      // A regex literal: a slash where an operand is expected.
      let j = i + 1;
      let inClass = false;
      while (j < src.length && (inClass || src[j] !== '/')) {
        if (src[j] === '\n') throw new Error('strip(): the regex at line ' + lineAt(i) + ' runs past its line');
        if (src[j] === '\\') j += 1;
        else if (src[j] === '[') inClass = true;
        else if (src[j] === ']') inClass = false;
        j += 1;
      }
      j += 1;
      while (j < src.length && /[a-z]/.test(src[j])) j += 1;
      emit('/', true, true);
      emit(src.slice(i + 1, j - 1), true, false);
      emit(src.slice(j - 1, j), true, true);
      remember('/x/');
      i = j;
    } else {
      emit(c, true, true);
      remember(c);
      i += 1;
    }
  }
  return { code: code.join(''), bare: bare.join('') };
}

/**
 * The statements of stripped source at bracket depth zero: each {start, end, term,
 * text}, `text` the comment-free code between the previous boundary and this one,
 * trimmed, `term` the boundary itself (`;`, `{` or `}`).
 */
function statements({ code, bare }) {
  const out = [];
  let depth = 0;
  let from = 0;
  for (let i = 0; i < bare.length; i += 1) {
    const c = bare[i];
    if (c === '(' || c === '[') depth += 1;
    else if (c === ')' || c === ']') depth -= 1;
    else if (depth === 0 && (c === ';' || c === '{' || c === '}')) {
      const raw = code.slice(from, i);
      const lead = raw.length - raw.trimStart().length;
      out.push({ start: from + lead, end: i + 1, term: c, text: raw.trim() });
      from = i + 1;
    }
  }
  return out;
}

const isConfirmClick = (s) => s.text.includes('data-cfgo') && /\bclick\s*\(/.test(s.text);
const isFixedWait = (s) => /^await\b/.test(s.text)
  && new RegExp('\\b(?:' + FIXED_WAITS.join('|') + ')\\s*\\(').test(s.text);
const isDialogWait = (s) => /\bawaitConfirmDialog\s*\(/.test(s.text);

/** [start, end) of each body of a function declared `function <name>(`. */
function bodiesOf({ bare }, name) {
  const out = [];
  for (const m of bare.matchAll(new RegExp('function\\s+' + name + '\\s*\\(', 'g'))) {
    const open = bare.indexOf('{', m.index);
    let depth = 0;
    for (let i = open; i < bare.length; i += 1) {
      if (bare[i] === '{') depth += 1;
      else if (bare[i] === '}') {
        depth -= 1;
        if (depth === 0) { out.push([open, i + 1]); break; }
      }
    }
  }
  return out;
}

/**
 * Every confirm click in `src` followed by a fixed wait before the next read:
 * {file, line, waitLine, text}, `text` the code from the action that opened the
 * dialog through the wait - what an allow row's `find` is matched against.
 */
function confirmWaitSites(file, src) {
  const stripped = strip(src);
  const list = statements(stripped);
  const skip = file === HELPER_FILE ? bodiesOf(stripped, HELPER) : [];
  const lineOf = (at) => src.slice(0, at).split('\n').length;
  const sites = [];
  list.forEach((s, i) => {
    if (!isConfirmClick(s) || skip.some(([a, b]) => s.start >= a && s.start < b)) return;
    let wait = null;
    for (let k = i + 1; k < list.length; k += 1) {
      const t = list[k];
      if (t.text === '' && t.term === ';') continue;
      if (t.term === ';' && !/\bawait\b/.test(t.text)) continue;
      if (t.term === ';' && isFixedWait(t)) wait = t;
      break;
    }
    if (!wait) return;
    let opener = s;
    for (let k = i - 1; k >= 0; k -= 1) {
      const t = list[k];
      if (t.term !== ';') break;
      if (t.text === '' || isDialogWait(t) || isFixedWait(t)) continue;
      opener = t;
      break;
    }
    sites.push({
      file, line: lineOf(s.start), waitLine: lineOf(wait.start),
      text: stripped.code.slice(opener.start, wait.end),
    });
  });
  return sites;
}

const siteName = (s) => s.file + ':' + s.line + ' (fixed wait at line ' + s.waitLine + ')';

/**
 * What is wrong with the gate's sources as places that read a confirmed write:
 * the confirm-then-fixed-wait sites no row excuses, the rows excusing no site, the
 * rows excusing a different number of sites than they say, and the rows with no
 * reason. `sources` maps a path relative to tools/ to its text.
 */
function confirmFindings(sources, allowed) {
  const sites = [...sources].flatMap(([file, src]) => confirmWaitSites(file, src));
  const covers = (a, s) => s.file === a.file && s.text.includes(a.find);
  const hits = (a) => sites.filter((s) => covers(a, s));
  return {
    sites,
    unlisted: sites.filter((s) => !allowed.some((a) => covers(a, s))).map(siteName),
    stale: allowed.filter((a) => hits(a).length === 0),
    broad: allowed.filter((a) => hits(a).length !== 0 && hits(a).length !== (a.sites || 1)),
    unreasoned: allowed.filter((a) => typeof a.reason !== 'string' || a.reason.trim() === ''),
  };
}

/**
 * The files the gate runs: the tool, and every .mjs it reaches through a relative
 * import, static or dynamic, transitively. Paths are relative to tools/.
 */
function gateSources(root = TOOLS, entry = ENTRY) {
  const out = new Map();
  const todo = [entry];
  while (todo.length) {
    const rel = todo.pop();
    if (out.has(rel)) continue;
    const src = readFileSync(path.join(root, rel), 'utf8');
    out.set(rel, src);
    const { code } = strip(src);
    const specs = /(?:\bfrom\s*|\bimport\s*\(\s*)(['"])(\.{1,2}\/[^'"]+\.mjs)\1/g;
    for (const m of code.matchAll(specs)) {
      const abs = path.resolve(path.dirname(path.join(root, rel)), m[2]);
      const next = path.relative(root, abs).split(path.sep).join('/');
      if (!next.startsWith('..')) todo.push(next);
    }
  }
  return out;
}

const realSources = () => gateSources();

it('cw1 no file the gate runs reads a confirmed write after a fixed wait, and every allow row excuses exactly the sites it says, with a reason', () => {
  const sources = realSources();
  // The derivation reached the files the claim is about; an empty or partial set
  // would satisfy every assertion below by having nothing to scan.
  for (const f of [ENTRY, 'ui-checks/stage-tabs.mjs', HELPER_FILE]) {
    expect([...sources.keys()], f + ' is not among the files the gate runs').toContain(f);
  }
  const found = confirmFindings(sources, CONFIRM_WAIT_ALLOWED);
  expect(found.unlisted).toEqual([]);
  expect(found.stale.map((a) => a.file + ': ' + a.find)).toEqual([]);
  expect(found.broad.map((a) => a.file + ': ' + a.find)).toEqual([]);
  expect(found.unreasoned.map((a) => a.file + ': ' + a.find)).toEqual([]);
  // The rows are load-bearing: with none, every site they excuse is reported.
  const excused = CONFIRM_WAIT_ALLOWED.reduce((n, a) => n + (a.sites || 1), 0);
  expect(excused).toBeGreaterThan(0);
  expect(confirmFindings(sources, []).unlisted).toHaveLength(excused);
});

it('cw2 a confirm click followed by a fixed wait, put back into a copy of either file, is reported by file and the line of the click', () => {
  const real = realSources();
  const variants = [
    ["  await page.locator('dialog.confirm [data-cfgo]').click();",
      '  await page.waitForTimeout(900);'],
    ['  await page.evaluate(() =>',
      "    document.querySelector('dialog.confirm[open] [data-cfgo]')?.click());",
      '  await new Promise((r) => setTimeout(r, 900));'],
    ["  await page.click('dialog.confirm [data-cfgo]');",
      "  note('saved');",
      "  await sleepPollWindow(page, 'save');"],
  ];
  for (const file of [ENTRY, 'ui-checks/stage-tabs.mjs']) {
    for (const body of variants) {
      const added = real.get(file) + '\nasync function handWritten(page) {\n'
        + "  await page.locator('#x [data-save=x]').click();\n"
        + body.join('\n') + '\n  return page.evaluate(() => 1);\n}\n';
      const sources = new Map(real);
      sources.set(file, added);
      // The click's own line and the wait's, counted in the text the scan read;
      // lastIndexOf, since the real file may carry the same line earlier.
      const lines = added.split('\n');
      const clickLine = lines.lastIndexOf(body[0]) + 1;
      const waitLine = lines.lastIndexOf(body[body.length - 1]) + 1;
      expect(waitLine - clickLine).toBe(body.length - 1);
      expect(confirmFindings(sources, CONFIRM_WAIT_ALLOWED).unlisted, body.join(' / '))
        .toEqual([file + ':' + clickLine + ' (fixed wait at line ' + waitLine + ')']);
    }
  }
});

it('cw3 an allow row that excuses nothing, excuses more than it says, or carries no reason is reported', () => {
  const sources = realSources();
  const ghost = { file: 'ui-checks/stage-tabs.mjs', find: 'no-such-opener', reason: 'x' };
  const elsewhere = { ...CONFIRM_WAIT_ALLOWED[0], file: 'no/such/file.mjs' };
  const stale = confirmFindings(sources, [...CONFIRM_WAIT_ALLOWED, ghost, elsewhere]).stale;
  expect(stale).toEqual([ghost, elsewhere]);
  // A row that matches every site in its file is broad, not silently kept.
  const wide = { file: ENTRY, find: 'data-cfgo', sites: 1, reason: 'x' };
  expect(confirmFindings(sources, [wide]).broad).toEqual([wide]);
  const bare = { ...CONFIRM_WAIT_ALLOWED[0], reason: ' ' };
  expect(confirmFindings(sources, [bare]).unreasoned).toEqual([bare]);
});

it('cw4 a confirm whose next read waits on the answer, a fixed wait that is not next, and the helper\'s own click are not reported', () => {
  const sources = new Map([[ENTRY, [
    'async function a(page) {',
    "  await page.locator('dialog.confirm [data-cfgo]').click();",
    "  const card = await awaitSaveCard(page, 'guards', 'ok', saved, 8000);",
    '  await page.waitForTimeout(400);',
    '}',
    'async function b(page) {',
    "  await confirmWrite(page, 'settings', CONFIG_WRITE, during);",
    '  await page.waitForTimeout(400);',
    '}',
    'async function c(page) {',
    "  await page.locator('dialog.confirm [data-cfgo]').click();",
    '  if (x) {',
    '    await page.waitForTimeout(400);',
    '  }',
    '}',
    // The other direction: a statement with no await between the click and the
    // wait does not hide the wait.
    'async function d(page) {',
    "  await page.locator('dialog.confirm [data-cfgo]').click();",
    "  const n = 'x';",
    '  await page.waitForTimeout(400);',
    '}',
  ].join('\n')], [HELPER_FILE, [
    'export async function confirmWrite(page) {',
    "  await page.locator('dialog.confirm [data-cfgo]').click();",
    '  await page.waitForTimeout(1);',
    '}',
  ].join('\n')]]);
  expect(confirmFindings(sources, []).unlisted).toEqual([ENTRY + ':17 (fixed wait at line 19)']);
  // The tokenizer refuses a source it cannot read to the end rather than scanning
  // half of it.
  expect(() => strip('const a = 1;\nconst b = "never closed;\n')).toThrow(/line 2/);
  expect(() => strip('const r = /a"b/;\nconst s = "ok";')).not.toThrow();
});

it('cw5 one helper, in one module, imported by both the tool and the stage checks', () => {
  const sources = realSources();
  const declares = [...sources].filter(([, src]) =>
    new RegExp('function\\s+' + HELPER + '\\s*\\(').test(strip(src).bare)).map(([f]) => f);
  expect(declares).toEqual([HELPER_FILE]);
  for (const [file, spec] of [[ENTRY, './ui-checks/confirm-write.mjs'],
    ['ui-checks/stage-tabs.mjs', './confirm-write.mjs']]) {
    const { code } = strip(sources.get(file));
    const imp = new RegExp('import\\s*\\{[^}]*\\b' + HELPER + '\\b[^}]*\\}\\s*from\\s*[\'"]'
      + spec.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&') + '[\'"]');
    expect(imp.test(code), file + ' does not import ' + HELPER + ' from ' + spec).toBe(true);
    expect((code.match(new RegExp('\\b' + HELPER + '\\s*\\(', 'g')) || []).length,
      file + ' calls ' + HELPER + ' at fewer than two sites').toBeGreaterThanOrEqual(2);
  }
});
