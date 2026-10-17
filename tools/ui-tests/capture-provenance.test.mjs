// The two refusals that stand between a re-capture and a committed leak.
//
// WHY THEY ARE TESTED HERE AND NOT BY RUNNING THE CAPTURE. Driving the capture
// takes a machine-wide lock and several minutes of browser time, and neither
// refusal needs a browser to be wrong: one is a pure function over a description
// of a page, the other is a subprocess call whose whole answer is an exit code and
// a line of text. What a browser would add is the wiring, and the wiring is one
// call each.
//
// WHAT THEY GUARD. `tools/check-committed-pii.py` refuses a committed artifact
// that names the machine that made it. It reads journals, rendered reports and
// theme documents — text. Every file in `docs/screenshots/` is a picture of one of
// those same surfaces: the panel's topbar paints its project path, and the plan
// gate card paints the files under it. Re-capturing is a required step of every
// release, so a capture taken against anything but a fixture commits a leak that
// nothing in the tree can read back out.
//
// BOTH DIRECTIONS, for both refusals. A guard that always fires is the same defect
// as one that never does — it just fails on the day of the release instead of
// quietly for ever — and the always-fires case is the one that looks vacuous and
// gets cut.
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { fixtureProblem, mergeCaptureRecord, regionalFormatProblem,
         regionalFormatBasis, dateInputProblem,
         shotWriteDecision } from '../capture-screenshots.mjs';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const PY = process.env.PYTHON || 'python3';

// An absolute, platform-correct fixture root. Built with `path` rather than
// written as a literal so the cases mean the same thing on the windows runner,
// where `path.relative` is what decides containment.
const WORK = path.resolve(path.sep, 'tmp', 'audit-shots-501');
const served = (port, dir) => new Map([[port, dir]]);

// --- the refusals as pure functions ------------------------------------------

describe('fixtureProblem: the shutter may only open on this run\'s own fixture', () => {
  it('accepts a panel whose project is inside the claimed scratch tree', () => {
    const facts = { origin: 'http://127.0.0.1:51234', project: path.join(WORK, 'big') };
    expect(fixtureProblem(facts, { work: WORK, served: new Map() })).toBe(null);
  });

  it('accepts a document served out of a directory under that tree', () => {
    const facts = { origin: 'http://127.0.0.1:51235', project: null };
    const fixtures = { work: WORK, served: served(51235, path.join(WORK, 'acme')) };
    expect(fixtureProblem(facts, fixtures)).toBe(null);
  });

  // THE FAULT ITSELF: a panel started on a real repository. This is the edit that
  // must not be able to land quietly, and until this function nothing looked.
  it('REFUSES a panel serving a project outside the fixture tree', () => {
    const real = path.resolve(path.sep, 'Users', 'someone', 'src', 'their-app');
    const problem = fixtureProblem({ origin: 'http://127.0.0.1:51234', project: real },
                                   { work: WORK, served: new Map() });
    expect(problem).toContain('OUTSIDE the fixture tree');
    // ...and it does not quote back the path that failed. That string is the very
    // thing being kept out of a committed picture; repeating it in the refusal
    // would move the leak from the PNG into the CI log, which is public.
    for (const fragment of ['someone', 'their-app']) {
      expect(problem).not.toContain(fragment);
    }
  });

  it('REFUSES a document served from a directory nobody registered', () => {
    const problem = fixtureProblem({ origin: 'http://127.0.0.1:9999', project: null },
                                   { work: WORK, served: served(51235, WORK) });
    expect(problem).toContain('neither a panel naming its project');
  });

  // A dead panel reports exactly like a page that is not a panel at all — the
  // inline script throws before `const PROJECT` is bound, so there is no project
  // to read. Refusing is right: nothing can vouch for what is on the screen.
  it('REFUSES a panel whose inline script died before naming its project', () => {
    const problem = fixtureProblem({ origin: 'http://127.0.0.1:51234', project: null },
                                   { work: WORK, served: new Map() });
    expect(problem).toContain('script died');
  });

  it('REFUSES any shot taken before a scratch tree was claimed', () => {
    const facts = { origin: 'http://127.0.0.1:51234', project: path.join(WORK, 'big') };
    expect(fixtureProblem(facts, { work: null, served: new Map() }))
      .toContain('before a scratch tree was claimed');
  });

  // A sibling of the fixture root, not a child. `startsWith` on the raw string
  // would call this contained — the classic prefix bug — and `path.relative` is
  // what makes it not.
  it('REFUSES a project that merely shares the fixture root\'s prefix', () => {
    const sibling = `${WORK}-elsewhere`;
    const problem = fixtureProblem({ origin: 'http://127.0.0.1:1', project: sibling },
                                   { work: WORK, served: new Map() });
    expect(problem).toContain('OUTSIDE the fixture tree');
  });
});

// The other refusal, end to end through the process the capture really starts.
// A helper rather than an import: what the capture depends on is the CONTRACT of
// that command line — reads stdin, exit 0 clean, exit 1 on a hit — and a case that
// imported a function would prove the function while the argv drifted.
function scanText(text) {
  const r = spawnSync(PY, [path.join(REPO, 'tools', 'check-committed-pii.py'),
                           '--scan-text'],
                      { cwd: REPO, input: text, encoding: 'utf8' });
  return { status: r.status, out: `${r.stdout || ''}${r.stderr || ''}`.trim() };
}

describe('paintedIdentityProblem: the paths a capture paints, judged by the one file that owns the vocabulary', () => {
  // The POSIX scratch root the capture really builds under. A uid is a number and
  // names nobody, which is why capturing on this platform is allowed at all — and
  // this is the case that fails if the guard ever becomes unconditional.
  it('passes the scratch root a POSIX capture actually uses', () => {
    const { status, out } = scanText('/tmp/audit-shots-501\n');
    expect(status).toBe(0);
    expect(out).toMatch(/^OK:/);
  });

  // The windows root, which is the leak that can happen TODAY: windows has no
  // /tmp, so `scratchPath()` keeps the platform temp directory — which is
  // per-user and therefore spells the user's name, straight into the panel's
  // topbar and from there into a committed PNG.
  it('REFUSES the per-user temp root a windows capture would paint', () => {
    const { status, out } = scanText(
      'C:\\Users\\somebody\\AppData\\Local\\Temp\\audit-shots\n');
    expect(status).toBe(1);
    expect(out).toContain('windows-user-path');
    expect(out).not.toContain('somebody');
  });

  // "I could not ask" must never print as "it is clean", and an empty pipe is how
  // a caller asks nothing by accident.
  it('REFUSES an empty read rather than calling it clean', () => {
    const { status, out } = scanText('');
    expect(status).toBe(1);
    expect(out).toContain('NOTHING WAS READ');
  });
});

// The sidecar is shared. `docs/screenshots/captured-at.json` carries the screenshots'
// records under `images` and the demo GIF's record under a key of its own, written
// by a different tool. A screenshot re-capture used to rewrite the file as note plus
// images and nothing else, so the GIF's record vanished on every release - and the
// GIF's own check reads that absence as a finding, which would have been red for a
// reason nobody could see from the diff.
describe('mergeCaptureRecord: one shot\'s record merged into the shared sidecar', () => {
  const gifs = { 'demo-gate.gif': { sha256: 'g', refusal: 'r', model: 'sonnet' } };
  const prior = { note: 'old', images: { 'b.png': { sha256: 'b' } }, gifs };

  it('KEEPS a top-level key it does not own', () => {
    const next = mergeCaptureRecord(prior, 'new note', 'a.png', { sha256: 'a' });
    expect(next.gifs).toEqual(gifs);
  });

  // The allow twin: keeping a foreign key must not stop the merge doing its own
  // job, which is the note, the new entry and a sorted image table.
  it('still writes its own half: the note, the new entry, images sorted by name', () => {
    const next = mergeCaptureRecord(prior, 'new note', 'a.png', { sha256: 'a' });
    expect(next.note).toBe('new note');
    expect(Object.keys(next.images)).toEqual(['a.png', 'b.png']);
    expect(next.images['a.png']).toEqual({ sha256: 'a' });
    expect(Object.keys(next)).toEqual(['note', 'images', 'gifs']);
  });

  it('builds a fresh body from nothing, and leaves the one it was handed alone', () => {
    const fresh = mergeCaptureRecord(null, 'n', 'a.png', { sha256: 'a' });
    expect(fresh).toEqual({ note: 'n', images: { 'a.png': { sha256: 'a' } } });
    mergeCaptureRecord(prior, 'new note', 'a.png', { sha256: 'a' });
    expect(prior).toEqual({ note: 'old', images: { 'b.png': { sha256: 'b' } }, gifs });
  });
});

// A native <input type=date> paints its placeholder (and, once it has a value, the
// value) from the OS regional format, and no browser option moves it: the capture
// pins Intl, Date and the number format, which the page can be asked about, and
// the placeholder is not in the DOM to be asked. So the host is read instead, and
// a shot that contains such an input is refused on a host whose format differs.
//
// BOTH DIRECTIONS. A refusal that fires on every host blocks the maintainer on the
// day of the release, and one that never fires is the silent over-claim it replaces.
describe('regionalFormatProblem / dateInputProblem: a host format must not reach a date input', () => {
  const mac = (over) => ({ platform: 'darwin', identifier: 'en_US', template: 'M/d/y',
                           reference: 'M/d/y', ...over });
  const serbia = mac({ identifier: 'en_US@rg=rszzzz', template: 'd. M. y.' });

  it('accepts a darwin host whose date template is the en_US one', () => {
    expect(regionalFormatProblem(mac())).toBe(null);
  });

  it('REFUSES a darwin host whose current locale formats dates differently, naming it', () => {
    const problem = regionalFormatProblem(serbia);
    expect(problem).toContain('en_US@rg=rszzzz');
    expect(problem).toContain('date input');
  });

  // "I could not ask" must not print as "it is clean".
  it('REFUSES a darwin host that could not be read rather than calling it clean', () => {
    const problem = regionalFormatProblem({ platform: 'darwin', error: 'osascript exited 1' });
    expect(problem).toContain('could not be read');
    expect(problem).toContain('osascript exited 1');
  });

  it('REFUSES when nobody asked at all', () => {
    expect(regionalFormatProblem(null)).toContain('not asked');
  });

  // Not probed off darwin, and said so by regionalFormatBasis rather than refused:
  // refusing a platform nobody measured would block a host with no known fault.
  it('does not refuse a platform it has not probed, and says it was not read', () => {
    const linux = { platform: 'linux' };
    expect(regionalFormatProblem(linux)).toBe(null);
    expect(regionalFormatBasis(linux)).toBe('not read on linux');
  });

  it('quotes the identifier it read, and the reason when it could not', () => {
    expect(regionalFormatBasis(serbia)).toBe('en_US@rg=rszzzz');
    expect(regionalFormatBasis({ platform: 'darwin', error: 'x' })).toBe('unreadable (x)');
  });

  it('refuses a shot with a date input on a leaking host, naming the shot', () => {
    const problem = dateInputProblem('filters', 1, serbia);
    expect(problem).toContain('filters');
    expect(problem).toContain('en_US@rg=rszzzz');
  });

  // The allow twin: the host's format is irrelevant to a picture with no such input.
  it('lets a shot with no visible date input through on the same leaking host', () => {
    expect(dateInputProblem('overview', 0, serbia)).toBe(null);
  });

  it('lets a shot with a date input through on a host whose format is clean', () => {
    expect(dateInputProblem('filters', 3, mac())).toBe(null);
  });
});

// THE WRITING PATH, DECIDED IN ONE PURE FUNCTION. shot() used to carry the refusal,
// the "WRITING ... as asked" note and the sidecar entry inline, where no case could
// reach them: the gate's capture command is --check, which returns before them, and
// the cases above exercise only the helpers underneath. Deleting the refusal or the
// hostFormatAccepted record left every recorded gate green. shotWriteDecision is what
// shot() now obeys, so these cases are the wiring's evidence.
//
// THREE OUTCOMES, EACH PINNED: refuse on a leak without acceptance, write and RECORD
// the acceptance with it, and write on a clean host without claiming any acceptance.
// The last two are the allow twins — a decision that always records hostFormatAccepted,
// or one that refuses a clean host, passes the first case alone.
describe('shotWriteDecision: what shot() does once the shutter is ready to write', () => {
  const mac = (over) => ({ platform: 'darwin', identifier: 'en_US', template: 'M/d/y',
                           reference: 'M/d/y', ...over });
  const serbia = mac({ identifier: 'en_US@rg=rszzzz', template: 'd. M. y.' });

  it('REFUSES a leaking host without the flag: no note, nothing to record', () => {
    const d = shotWriteDecision('filters', 2, serbia, false);
    expect(d.refuse).toContain('filters');
    expect(d.refuse).toContain('en_US@rg=rszzzz');
    expect(d.refuse).toContain('--accept-host-date-format');
    expect(d.note).toBe(null);
    expect(d.extra).toBe(null);
  });

  it('WRITES a leaking host when accepted, says so, and records the acceptance', () => {
    const d = shotWriteDecision('filters', 2, serbia, true);
    expect(d.refuse).toBe(null);
    expect(d.note).toContain('filters');
    expect(d.note).toContain('WRITING');
    expect(d.extra).toEqual({ nativeDateInput: {
      regionalFormat: 'en_US@rg=rszzzz', hostFormatAccepted: true } });
  });

  // Allow twin: on a clean host the flag is irrelevant, and the entry must not claim
  // an acceptance nobody gave. toEqual treats an undefined-valued key as absent, so
  // the key itself is asked about.
  it('WRITES a clean host without refusing, noting or claiming an acceptance', () => {
    for (const accept of [false, true]) {
      const d = shotWriteDecision('filters', 2, mac(), accept);
      expect(d.refuse).toBe(null);
      expect(d.note).toBe(null);
      expect(d.extra).toEqual({ nativeDateInput: { regionalFormat: 'en_US' } });
      expect('hostFormatAccepted' in d.extra.nativeDateInput).toBe(false);
    }
  });

  it('WRITES a shot with no date input on a leaking host, recording nothing', () => {
    for (const accept of [false, true]) {
      const d = shotWriteDecision('overview', 0, serbia, accept);
      expect(d.refuse).toBe(null);
      expect(d.note).toBe(null);
      expect(d.extra).toBe(null);
    }
  });

  it('REFUSES when the host was never asked, flag or no flag only deciding the rest', () => {
    expect(shotWriteDecision('filters', 1, null, false).refuse).toContain('not asked');
    expect(shotWriteDecision('filters', 1, null, true).refuse).toBe(null);
  });
});

// --- the wiring of shot() ----------------------------------------------------

// A RULE THAT LIVED IN A COMMENT: every image this tool writes goes through shot(),
// because shot() is where the pinned-context, fixture and date-input checks run. A
// second call site photographs without them. This reads the source, so it needs no
// browser and cannot be skipped by a leg that never reaches a shot.
//
// Lines that are wholly comments are skipped; a trailing comment that names the call
// is counted, which fails loud rather than letting a real call hide behind one.
describe('every image is written by shot() alone', () => {
  const SRC = readFileSync(path.join(REPO, 'tools', 'capture-screenshots.mjs'), 'utf8');
  const LINES = SRC.split('\n');
  const SHUTTER = /\.\s*screenshot\b|\[\s*['"`]screenshot['"`]\s*\]/;
  const isCommentLine = (l) => /^\s*(\/\/|\*|\/\*)/.test(l);
  const hits = (lines) => lines.map((text, i) => ({ n: i + 1, text }))
    .filter((l) => !isCommentLine(l.text) && SHUTTER.test(l.text));
  const bounds = (lines) => {
    const start = lines.findIndex((l) => l.startsWith('async function shot('));
    const end = lines.findIndex((l, i) => i > start && l === '}');
    return { start: start + 1, end: end + 1 };
  };

  it('finds shot() and exactly one shutter call, inside it', () => {
    const { start, end } = bounds(LINES);
    expect(start).toBeGreaterThan(0);
    expect(end).toBeGreaterThan(start);
    const found = hits(LINES);
    expect(found.map((h) => h.n).filter((n) => n < start || n > end)).toEqual([]);
    expect(found.length).toBe(1);
  });

  // Prove the detector can see a violation: a bare call after shot() is counted and
  // placed outside its body, so the case above would go red on it.
  it('sees a shutter call placed outside shot()', () => {
    const planted = [...LINES, 'async function sneak(page) {',
                     '  await page.screenshot({ path: "x.png" });', '}'];
    const { start, end } = bounds(planted);
    const outside = hits(planted).filter((h) => h.n < start || h.n > end);
    expect(outside.length).toBe(1);
    expect(outside[0].text).toContain('page.screenshot');
  });

  it('ignores a comment line that merely names the call', () => {
    expect(hits(['// page.screenshot(x)', ' * .screenshot(y)']).length).toBe(0);
  });

  // The decision is made in shotWriteDecision, not re-derived in shot(): a second
  // copy of the refusal there would be the one no case reaches.
  it('shot() takes its refusal from shotWriteDecision and keeps no copy of it', () => {
    const { start, end } = bounds(LINES);
    const body = LINES.slice(start - 1, end).join('\n');
    expect(body.match(/shotWriteDecision\(/g).length).toBe(1);
    expect(body).not.toContain('dateInputProblem(');
    expect(body).not.toContain('hostFormatAccepted');
  });

  // The decision only matters if shot() obeys all three parts of it and hands over
  // the real flag. This is a source read, not a run: it fails when a part is dropped
  // (the refusal no longer fails the run, the sidecar entry no longer reaches
  // recordCapture) but cannot prove the order of the statements.
  it('shot() obeys the refusal, prints the note, records the extra, and passes the flag', () => {
    const { start, end } = bounds(LINES);
    const body = LINES.slice(start - 1, end).join('\n');
    expect(body).toMatch(/shotWriteDecision\(.*, ACCEPT_HOST_DATE_FORMAT\)/);
    expect(body).toMatch(/if \(decision\.refuse\) \{\s*fail\(decision\.refuse\);\s*return;/);
    expect(body).toMatch(/if \(decision\.note\) note\(decision\.note\);/);
    expect(body).toMatch(/recordCapture\(.*, decision\.extra\)/);
  });

  // ORDER, which the case above cannot see: the refusal is only a refusal if it sits
  // BEFORE the shutter, and the sidecar entry only describes a picture if it sits
  // AFTER it. Moving the shutter call above the refusal leaves every regex above
  // matching and the file's count of shutter calls at one, so the picture would be
  // written and then refused. Index comparisons over the statements need no browser.
  // Comment lines are dropped first, so a remark that names the call cannot stand in
  // for it; an anchor that is missing fails the case rather than comparing -1.
  const codeBody = (lines) => {
    const { start, end } = bounds(lines);
    return lines.slice(start - 1, end).filter((l) => !isCommentLine(l)).join('\n');
  };
  const REFUSAL = 'if (decision.refuse)';
  const orderProblems = (body) => {
    const refusal = body.indexOf(REFUSAL);
    const shutter = body.search(SHUTTER);
    const record = body.indexOf('recordCapture(');
    if (refusal < 0 || shutter < 0 || record < 0) {
      return ['anchor missing: refusal ' + refusal + ', shutter ' + shutter + ', record ' + record];
    }
    return [
      ...(refusal < shutter ? [] : ['the refusal sits after the shutter call']),
      ...(shutter < record ? [] : ['recordCapture sits before the shutter call']),
    ];
  };

  it('the case P128-R14 asks for, locking the behaviour at HEAD', () => {
    const body = codeBody(LINES);
    expect(body.indexOf(REFUSAL)).toBeGreaterThan(-1);
    expect(body.search(SHUTTER)).toBeGreaterThan(-1);
    expect(body.indexOf(REFUSAL)).toBeLessThan(body.search(SHUTTER));
    expect(body.search(SHUTTER)).toBeLessThan(body.indexOf('recordCapture('));
    expect(orderProblems(body)).toEqual([]);
  });

  // The detector's other direction: the same body with the shutter statement moved
  // above the refusal must be reported, so the case above can go red.
  it('reports a shutter call moved above the refusal', () => {
    const shutterLine = '  await page.screenshot({ path: file, fullPage: full });';
    const moved = codeBody(LINES).split('\n').filter((l) => l !== shutterLine);
    expect(moved.length).toBe(codeBody(LINES).split('\n').length - 1);
    const at = moved.findIndex((l) => l.includes(REFUSAL));
    moved.splice(at, 0, shutterLine);
    expect(orderProblems(moved.join('\n'))).toEqual(['the refusal sits after the shutter call']);
  });
});
