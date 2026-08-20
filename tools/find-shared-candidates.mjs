#!/usr/bin/env node
/**
 * Find candidate rows for `_deps.SHARED_CONCERNS` — repeated logic across the
 * `ui/` JavaScript. A SCOUT, never a gate.
 *
 * WHY THIS IS NOT A GATE, measured rather than assumed. A naive 20-token scan of
 * these files reports ~3,700 cross-file repeat groups. Preserving the shared
 * vocabulary and short string literals brings it to ~700, and the top hits are
 * still this codebase's own `el()` DOM idiom — which is house style, not
 * duplication. A build that failed on that is a build people learn to ignore. So
 * what gates is the named registry in `_deps.SHARED_CONCERNS`, where every row
 * carries a home and a reason; this tool only suggests rows to add to it.
 *
 * WHY IT IS A COMMITTED SCRIPT AND NOT `jscpd`. jscpd is the better-engineered
 * tool and would be the obvious choice for a gate. This is not a gate: it is run
 * by hand, a few times, when hunting for a row that reading has not already
 * found. A dependency that never appears in a check is weakly justified in a repo
 * whose plugin ships stdlib-only with no build step — and node builtins cover it.
 *
 * WHAT IT CANNOT SEE, said rather than implied. It is a token-window heuristic
 * with no parser, so a copy whose control flow was rewritten — an `if` turned into
 * a ternary — reads as different. It UNDER-reports. Its output is also not
 * evidence on its own: the fifteen-row inventory this repo works from came from
 * people READING 8,584 lines, and this scanner independently rediscovered three of
 * them. Treat a hit as a place to look, and confirm it by reading both sites.
 *
 *   node tools/find-shared-candidates.mjs              # default window
 *   node tools/find-shared-candidates.mjs --window 34  # longer = fewer, stronger
 *   node tools/find-shared-candidates.mjs --top 40
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';

const argv = process.argv.slice(2);
const flag = (name, fallback) => {
  const i = argv.indexOf('--' + name);
  return i >= 0 && argv[i + 1] ? Number(argv[i + 1]) : fallback;
};
const WINDOW = flag('window', 22);
const TOP = flag('top', 12);

// Relative to cwd, never absolute: `_refs.absolute_reach_violations()` forbids
// reaching a file by absolute path, and this tool is inside the surface it scans.
const ROOTS = ['plugins/audit/scripts/ui/report', 'plugins/audit/scripts/ui/panel',
               'plugins/audit/scripts/ui/shared'];

const TOKEN = /[A-Za-z_$][\w$]*|'[^'\n]{0,14}'|[0-9]+|[^\s\w]/g;
const KEYWORDS = new Set(('const let var function return if else for while of in new typeof '
  + 'delete void try catch finally throw switch case break continue default do async '
  + 'await null true false undefined this').split(' '));

/**
 * Comments and long literals out: a copied comment would inflate similarity.
 *
 * Every replacement PRESERVES THE LINE COUNT, and that is not cosmetic. Collapsing
 * a JSDoc block to one space — which the first version of this did — shifts every
 * line number after it, and these files carry a block comment above almost every
 * function. The tool then reports real duplication at the wrong coordinates, which
 * is worse than reporting none: it sends a reader to a line that has nothing to do
 * with the hit, and the natural conclusion is that the tool is noise.
 */
const keepLines = (match) => match.replace(/[^\n]/g, ' ');
const stripNoise = (text) => text
  .replace(/\/\*[\s\S]*?\*\//g, keepLines)
  .replace(/(?<!:)\/\/.*$/gm, '')
  .replace(/`(?:[^`\\]|\\.)*`/g, keepLines)
  .replace(/"(?:[^"\\\n]|\\.)*"/g, "'S'")
  .replace(/'[^'\n]{15,}'/g, "'S'");

const jsFiles = () => {
  const out = [];
  for (const root of ROOTS) {
    let entries;
    try { entries = readdirSync(root); } catch { continue; }
    for (const name of entries.sort()) {
      const full = path.join(root, name);
      if (statSync(full).isFile() && name.endsWith('.js')) out.push(full);
    }
  }
  return out;
};

const files = jsFiles();
if (!files.length) {
  console.error('found no .js under ' + ROOTS.join(', ')
    + ' — run this from the repository root');
  process.exit(2);
}

// The SHARED VOCABULARY is preserved as itself, and this is what separates signal
// from noise. Without it a local `auFilter` and a local `modelFilter` normalise
// together (wanted) but so do `el('div')` and `el('span')` (not wanted, and there
// are hundreds). Every name declared at top level in any surface is treated as
// vocabulary; only locals are anonymised.
const sources = new Map();
const vocab = new Set();
const DECL = /^[ \t]{0,2}(?:(?:async\s+)?function\s+([A-Za-z_$][\w$]*)|(?:const|let)\s+([A-Za-z_$][\w$]*))/gm;
for (const file of files) {
  const src = stripNoise(readFileSync(file, 'utf8'));
  sources.set(file, src);
  for (const m of src.matchAll(DECL)) vocab.add(m[1] || m[2]);
}

const normalise = (toks) => {
  const seen = new Map();
  const parts = toks.map((t) => {
    if (KEYWORDS.has(t) || vocab.has(t) || !/^[A-Za-z_$]/.test(t)) return t;
    if (!seen.has(t)) seen.set(t, String(seen.size));
    return '#' + seen.get(t);
  });
  return createHash('sha1').update(parts.join(' ')).digest('hex').slice(0, 12);
};

const index = new Map();
let scanned = 0;
for (const [file, src] of sources) {
  const toks = [];
  src.split('\n').forEach((line, i) => {
    for (const m of line.matchAll(TOKEN)) toks.push([m[0], i + 1]);
  });
  scanned += toks.length;
  for (let i = 0; i + WINDOW <= toks.length; i += 1) {
    const win = toks.slice(i, i + WINDOW);
    const key = normalise(win.map((w) => w[0]));
    if (!index.has(key)) index.set(key, []);
    index.get(key).push([file, win[0][1]]);
  }
}

// Collapse windows starting within a few lines of each other in one file: a copied
// block would otherwise be reported once per offset.
const groups = [];
for (const sites of index.values()) {
  const uniq = [];
  for (const [file, line] of [...new Set(sites.map((s) => s.join(':')))].sort()
      .map((s) => { const i = s.lastIndexOf(':'); return [s.slice(0, i), Number(s.slice(i + 1))]; })) {
    const last = uniq[uniq.length - 1];
    if (last && last[0] === file && line - last[1] < 4) continue;
    uniq.push([file, line]);
  }
  if (uniq.length > 1) groups.push(uniq);
}
// Cross-file first: a repeat inside one function is often an unrolled loop, while
// the same window in two files is a copy somebody made.
let cross = groups.filter((g) => new Set(g.map((s) => s[0])).size > 1);
// Two adjacent windows can normalise to different keys and still cover the same
// sites, which printed every group twice. Deduplicate by the SITE LIST, not by
// the window hash: the site list is what a reader acts on.
const bySites = new Map();
for (const g of cross) {
  const sig = g.map((s) => s.join(':')).join('|');
  if (!bySites.has(sig)) bySites.set(sig, g);
}
cross = [...bySites.values()];
cross.sort((a, b) => b.length - a.length);

console.log(`scanned ${scanned} tokens across ${files.length} file(s), window ${WINDOW}`);
console.log(`repeated windows: ${groups.length}; spanning more than one file: ${cross.length}`);
console.log('');
if (!cross.length) {
  console.log('no cross-file repeat at this window — with '
    + `${groups.length} same-file repeat(s) found that is a real answer; with 0 of `
    + 'both it would mean the scan matched nothing at all');
}
for (const g of cross.slice(0, TOP)) {
  console.log(`  ${g.length} sites:`);
  for (const [file, line] of g) console.log(`    ${file}:${line}`);
}
console.log('');
console.log('Confirm by READING both sites before adding a row to '
  + '_deps.SHARED_CONCERNS. This under-reports and it cannot judge; the existing '
  + 'rows were found by reading, and this scanner only rediscovered three of them.');
