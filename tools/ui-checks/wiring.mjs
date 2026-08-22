/**
 * A stage nobody calls reports nothing and fails nothing, which reads exactly like
 * a stage that passed.
 *
 * IT SCANS A SET OF FILES, not one. It used to be handed `import.meta.url`'s own
 * source inside capture-screenshots.mjs — correct while every stage lived in that
 * one file, and silently narrower the moment four concerns moved into
 * tools/ui-checks/: a stage declared in a module and called from nowhere would have
 * been invisible, which is the exact failure this guard exists to name. The split
 * had to pay for this, and paying for it is what makes the split honest.
 *
 * Static on purpose: a runtime tally would need 30 call-site edits and would still
 * only prove what THIS invocation reached, while the defect is a stage nothing
 * anywhere calls. What it therefore cannot see is a stage wired inside a branch that
 * never runs — that is the leg guard's job, and the direction here is
 * under-reporting, which is the quiet one.
 *
 * Line-based on purpose too. A stage named in prose is not a call, and that lesson
 * was paid for one file over, where a coverage check counted its own comments and
 * reported five phantom findings on a clean run.
 */
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export function unwiredStages(sources) {
  const declared = new Map();
  const called = new Set();
  for (const { file, source } of sources) {
    const lines = source.split('\n');
    lines.forEach((line, i) => {
      const m = line.match(/^(?:export )?(?:async )?function (assert\w+)/);
      // The declaration site is recorded WITH ITS FILE now. A bare line number was
      // enough while there was one file; across five it names nothing a reader can
      // open.
      if (m) declared.set(m[1], `${file} line ${i + 1}`);
    });
  }
  for (const { source } of sources) {
    source.split('\n').forEach((line) => {
      const t = line.trim();
      if (t.startsWith('//') || t.startsWith('*') || t.startsWith('/*')) return;
      if (/^(?:export )?(?:async )?function assert/.test(t)) return;
      for (const name of declared.keys()) {
        if (new RegExp('(?<![A-Za-z_.])' + name + '\\s*\\(').test(line)) {
          called.add(name);
        }
      }
    });
  }
  return [...declared.entries()]
    .filter(([name]) => !called.has(name))
    .map(([name, where]) => `${name} (declared at ${where})`)
    .sort();
}

/**
 * Every file a stage may be declared in: the orchestrator plus its modules.
 *
 * Read off the DIRECTORY rather than listed, for the same reason the Python sweep
 * walks a tree instead of an enumerated list: adding a module and adding a line to
 * a list are two acts, and only one of them would ever be enforced.
 */
export function stageSources(toolsDir = null) {
  const here = path.dirname(fileURLToPath(import.meta.url));
  const dir = toolsDir || path.dirname(here);
  const files = [path.join(dir, 'capture-screenshots.mjs')];
  const sub = path.join(dir, 'ui-checks');
  for (const name of readdirSync(sub).sort()) {
    if (name.endsWith('.mjs')) files.push(path.join(sub, name));
  }
  return files.map((f) => ({ file: path.basename(f),
                             source: readFileSync(f, 'utf8') }));
}
