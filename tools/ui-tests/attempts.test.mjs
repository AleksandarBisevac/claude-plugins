// A recorded zero is a value; an absent field is not a zero.
//
// `t.attempts||1` was written at both of the panel's readers, on the belief -
// stated in a pin's own comment - that "one attempt is the true default". It is
// not. `audit-task.py` writes `attempts: 0` for every new task, and two documented
// paths take a count back DOWN while the ledger keeps the tokens: the orchestrator
// reverts the increment after a specific failure, and `/audit:run` resets a blocked
// or re-opened task. So zero is recorded, and reading it as one reported an attempt
// the plan says never happened.
//
// THE AGREEMENT WITH PYTHON IS THE POINT OF THIS FILE. The same mean is computed
// twice - `_usage_routing._recorded_attempts` for the report and the CLI, `uAtt`
// for the panel - and this repo has already shipped two token formatters that
// disagreed while both claimed in comments to mirror the same Python. A claim that
// two implementations agree is testable, so it is tested here rather than asserted
// in a docstring.
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { loadPanel, reach, REPO_ROOT } from './sandbox.mjs';

const { ctx } = loadPanel();
const { uAtt } = reach(ctx, ['uAtt']);

// The Python answer for the same inputs, from the module that owns it. Called out
// to rather than reimplemented: a JavaScript copy of the rule would make this file
// agree with itself and prove nothing.
function pythonRecorded(tasks) {
  const src = [
    'import sys, json',
    'sys.path.insert(0, ' + JSON.stringify(
      path.join(REPO_ROOT, 'plugins', 'audit', 'scripts')) + ')',
    'import _output; _output.install_path()',
    'import _usage_routing as R',
    'print(json.dumps(R._recorded_attempts(json.loads(sys.argv[1]))))',
  ].join('\n');
  const out = execFileSync('python3', ['-c', src, JSON.stringify(tasks)],
                           { encoding: 'utf8' });
  return JSON.parse(out);
}

describe('uAtt: the attempt count a task records', () => {
  it('reads a recorded zero as zero, not as one', () => {
    expect(uAtt({ attempts: 0 })).toBe(0);
  });

  it('reads a recorded number as itself', () => {
    expect(uAtt({ attempts: 3 })).toBe(3);
  });

  it('answers null when the field is absent - unknown is not unattempted', () => {
    expect(uAtt({})).toBe(null);
    expect(uAtt(undefined)).toBe(null);
  });

  it('answers null for a value that is not an integer count', () => {
    expect(uAtt({ attempts: 'two' })).toBe(null);
    expect(uAtt({ attempts: 1.5 })).toBe(null);
    // `true` is not one attempt. JavaScript keeps booleans out of `typeof
    // 'number'` for free; Python does not, and its side excludes them explicitly.
    expect(uAtt({ attempts: true })).toBe(null);
  });

  it('the retried test reads a zero as not-retried, and the old form agreed', () => {
    // This is the one position where `||1` and the recorded value give the same
    // answer, which is why it never showed the bug: `0||1` is 1 and `1 > 1` is
    // false, exactly as `0 > 1` is. Asserted so the change is known to be
    // behaviour-free HERE while being a fix one function over.
    expect(uAtt({ attempts: 0 }) > 1).toBe(false);
    expect((0 || 1) > 1).toBe(false);
    expect(uAtt({ attempts: 2 }) > 1).toBe(true);
  });
});

describe('the panel and the Python agree about what is recorded', () => {
  const cases = [
    [{ attempts: 0 }, { attempts: 2 }],
    [{ attempts: 0 }, {}],
    [{}, { attempts: 'x' }, { attempts: true }],
    [{ attempts: 7 }],
  ];

  it.each(cases.map((tasks, i) => [i, tasks]))(
    'case %i: the same tasks give the same list of recorded counts',
    (_i, tasks) => {
      const js = tasks.map(uAtt).filter((v) => v !== null);
      expect(js).toEqual(pythonRecorded(tasks));
    });

  it('and the means agree, including the empty one', () => {
    const mean = (xs) => (xs.length
      ? Math.round((xs.reduce((a, b) => a + b, 0) / xs.length) * 100) / 100
      : null);
    for (const tasks of cases) {
      const js = tasks.map(uAtt).filter((v) => v !== null);
      expect(mean(js)).toEqual(mean(pythonRecorded(tasks)));
    }
  });
});
