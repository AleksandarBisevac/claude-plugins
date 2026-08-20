// Call the Python formatters from the JavaScript suite, so the two sides can be
// compared instead of each being asserted against a hand-written expectation.
//
// This is the point of the whole exercise. A JS case that says
// `fmtTokens(2.6) === '2'` proves only that whoever wrote the case agreed with
// whoever wrote the function. The claim the sources actually make is that they
// MIRROR plugins/audit/scripts/_fmt.py — so the expectation has to come from
// that module, at run time, on every run. It is the same shape the repo already
// uses to hold the pricing table equal across the hooks/ <-> scripts/ boundary.
//
// One process per batch, not one per case: the interpreter start dominates.

import { execFileSync, spawnSync } from 'node:child_process';
import path from 'node:path';
import { REPO_ROOT } from './sandbox.mjs';

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
const BRIDGE = [
  'import importlib, json, os, sys',
  'sys.path.insert(0, sys.argv[1])',
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
 * Run a batch of `_fmt` calls and return their results in order.
 * @param {Array<[string, Array<unknown>]>} calls e.g. [['fmt_tokens', [2.6]], ...]
 */
export function pyFmt(calls) {
  return pyCall('_fmt', calls);
}

/**
 * The same, against any module under `scripts/`.
 *
 * A non-callable attribute is returned as its VALUE, so a table can be compared
 * as directly as a function result — which is the point for `CONTRAST_PAIRS`
 * and its like: the claim is that the JavaScript reads Python's table, and the
 * only way to check that is to fetch the table.
 *
 * @param {string} moduleName e.g. `'_ui_theme'`
 * @param {Array<[string, Array<unknown>]>} calls
 */
export function pyCall(moduleName, calls) {
  if (!Array.isArray(calls) || !calls.length) {
    throw new Error('pyCall called with no cases — an empty batch would return an '
      + 'empty list and every comparison over it would vacuously pass');
  }
  const exe = pythonInterpreter();
  let stdout;
  try {
    stdout = execFileSync(exe, ['-c', BRIDGE, SCRIPTS_DIR, moduleName], {
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

// `"%.*f"` itself, which is what every formatter in _fmt.py rounds through and
// therefore the reference for the TIE RULE specifically. Going through
// fmt_tokens instead would only reach values that survive `int(n)` and a
// magnitude divide — roughly multiples of 1/1000 between 1 and 1000 — and the
// tie rule has to hold across every magnitude and every dp.
//
// Doubles cross as JSON on purpose: JSON.stringify emits the shortest decimal
// that round-trips and Python's json parses to the nearest double, so both
// sides hold the SAME bits. -0 is the one value that does not survive
// (JSON.stringify(-0) is "0"), so callers must keep it out of the table.
const FIXED_BRIDGE = [
  'import json, sys',
  'pairs = json.load(sys.stdin)',
  'json.dump(["%.*f" % (dp, x) for x, dp in pairs], sys.stdout)',
].join('\n');

/**
 * Format each `[value, dp]` pair exactly as `_fmt.py`'s `"%.*f"` would.
 * @param {Array<[number, number]>} pairs
 */
export function pyFixed(pairs) {
  if (!Array.isArray(pairs) || !pairs.length) {
    throw new Error('pyFixed called with no pairs — an empty batch would return '
      + 'an empty list and every comparison over it would vacuously pass');
  }
  for (const [x] of pairs) {
    if (!Number.isFinite(x) || Object.is(x, -0)) {
      throw new Error('pyFixed cannot carry ' + String(x) + ' across JSON without '
        + 'changing it; keep non-finite values and -0 out of the table rather '
        + 'than comparing something neither side actually received');
    }
  }
  const exe = pythonInterpreter();
  let stdout;
  try {
    stdout = execFileSync(exe, ['-c', FIXED_BRIDGE], {
      input: JSON.stringify(pairs), encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'],
    });
  } catch (cause) {
    throw new Error('the "%.*f" bridge failed (' + exe + '): '
      + String(cause.stderr || cause.message).trim()
      + '\nstdout was: ' + String(cause.stdout || '').trim());
  }
  const out = JSON.parse(stdout);
  if (out.length !== pairs.length) {
    throw new Error('the "%.*f" bridge returned ' + out.length + ' results for '
      + pairs.length + ' pairs');
  }
  return out;
}
