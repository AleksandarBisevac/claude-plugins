// The two refusals that stand between a re-capture and a committed leak (F137).
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
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { fixtureProblem } from '../capture-screenshots.mjs';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const PY = process.env.PYTHON || 'python3';

// An absolute, platform-correct fixture root. Built with `path` rather than
// written as a literal so the cases mean the same thing on the windows runner,
// where `path.relative` is what decides containment.
const WORK = path.resolve(path.sep, 'tmp', 'audit-shots-501');
const served = (port, dir) => new Map([[port, dir]]);

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
