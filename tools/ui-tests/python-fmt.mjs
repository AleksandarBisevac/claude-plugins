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

import { execFileSync } from 'node:child_process';
import { pyCall, pythonInterpreter } from './sandbox.mjs';

// RE-EXPORTED, NOT REDECLARED. `pythonInterpreter` and `pyCall` were written
// here and moved down into sandbox.mjs when the part readers there needed the
// same bridge: that file owns REPO_ROOT and this one reads it at module scope,
// so importing in the other direction closes a cycle whose python-fmt half
// evaluates first and reads REPO_ROOT in its TDZ. The names stay importable from
// here because every caller already spells them that way, and because "ask
// Python" is what this module is named for.
export { pyCall, pythonInterpreter };

/**
 * Run a batch of `_fmt` calls and return their results in order.
 * @param {Array<[string, Array<unknown>]>} calls e.g. [['fmt_tokens', [2.6]], ...]
 */
export function pyFmt(calls) {
  return pyCall('_fmt', calls);
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
