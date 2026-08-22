/**
 * Resolving a plugin script by BASENAME, wherever it sits under scripts/.
 *
 * The folders under the scripts tree are labels, not namespaces, so a join against
 * the tree root looks one directory too high the moment a script is filed under a
 * domain folder. `.mjs` cannot import the Python module that owns that rule, so
 * this is the JavaScript side of it - and `_refs.tool_basename_drift()` is what
 * checks the names it is given still exist.
 */
import { readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * The scripts tree, derived from THIS file's own location.
 *
 * It used to be a `SCRIPTS` const in capture-screenshots.mjs, and the first cut of
 * this split left the reference behind: the module imported cleanly, because a free
 * variable inside a function body is only resolved when the function runs, and every
 * call to `scriptIndex()` threw `SCRIPTS is not defined`. An `import` check cannot
 * see that; the editor's own diagnostic reported the other half of it — a constant
 * left with no readers in the file it stayed in.
 */
const REPO = path.dirname(path.dirname(path.dirname(fileURLToPath(import.meta.url))));

const SCRIPTS = path.join(REPO, 'plugins', 'audit', 'scripts');

/**
 * Every spelling of a directory separator on this platform — the mirror of
 * `_loader._SEPARATORS`. `'/'` is always one; `path.sep` is the same character on
 * POSIX and a backslash on Windows, so the Set is one entry there and two here.
 */
const SEPARATORS = [...new Set(['/', path.sep])];

/** Memoised for the DEFAULT tree only. See scriptIndex(). */
let scriptIndexMemo = null;

/**
 * `Map` of basename -> [absolute path, ...] for every `.py` under scripts/, at ANY
 * DEPTH. The JavaScript half of `_loader.script_index()`.
 *
 * WHY THIS EXISTS AT ALL. This file used to build each script path by joining the
 * SCRIPTS constant with a filename, nine times over. Two things were wrong with that.
 * No lint could see those lines — `_refs.py` matched a directory-plus-name PATH per
 * line, and a join carries the name only — so they failed at RUN time, in a browser
 * gate, instead of at lint time. And when `render-report.py` moved into a subdirectory,
 * one join was patched by inserting the folder's name into it, which hard-codes a
 * DOMAIN NAME into a tool: the folders under scripts/ are labels, not namespaces, and
 * no consumer should have to know which one a script was filed under. Seven more
 * domains are due to move.
 *
 * NO join of the SCRIPTS constant survives in this file any more. One did until
 * recently — a read of `ui/panel.js`, argued at its site as safe because a UI asset
 * is not a script and so could not be relabelled. Then panel.js was cut into parts
 * and the path stopped existing, which is the answer to the argument: the exemption
 * was sound about relabelling and silent about the file simply not being there.
 * `assertNoHandAssignedPolledState` now asks Python for the assembled page instead,
 * which is what its subject was all along. `test__refs.py` asserts the count, so a
 * join cannot creep back in quietly.
 *
 * WHY IT IS A COPY. This is the fourth statement of one resolution rule (`_loader.py`,
 * `_config.py`'s find_script, `_output.py`'s script_files are the other three) and the
 * copy is not avoidable, because `.mjs` cannot import Python. It is held true by
 * READING rather than by merging: `test__refs.py` runs this function under node and
 * compares its answer with `_loader.script_index()`, basename by basename — the same
 * shape as the pricing table this repo holds equal between `_config.py` and
 * `_usage_core.py`.
 *
 * A LIST PER NAME, NEVER A PATH, for `_loader`'s reason: a Map of name -> path keeps
 * whichever file the walk saw last and leaves nothing to report about the other.
 *
 * `__pycache__` is deliberately NOT skipped, because `_output.py_files()` does not skip
 * it either and it holds `.pyc` and no `.py`. A filter here would be this walk and that
 * walk answering "what is in the tree" differently about a directory neither ever finds
 * a file in.
 *
 * `root` is a TEST SEAM and is deliberately NOT memoised — a fixture tree must neither
 * poison the real tree's answer nor read it. Same rule, same reason, as
 * `_output.script_files()`.
 */
export function scriptIndex(root = null) {
  if (root === null && scriptIndexMemo) return scriptIndexMemo;
  const index = new Map();
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith('.py')) index.set(entry.name, [...(index.get(entry.name) || []), full]);
    }
  };
  walk(root === null ? SCRIPTS : root);
  // Sorted so a duplicate-name refusal names the two files in a stable order;
  // readdirSync order is not stable across filesystems, os.walk's is not either.
  for (const paths of index.values()) paths.sort();
  if (root === null) scriptIndexMemo = index;
  return index;
}

/**
 * The absolute path of `basename` WHEREVER it sits under scripts/.
 *
 * THROWS, NEVER GUESSES, and there is no fallback join behind any of the three
 * refusals — they are `_loader.script_path()`'s, restated where the resolution
 * actually happens:
 *
 *   * NOTHING WITH THAT NAME -> naming the basename AND how many files were searched.
 *     The count is not decoration: "not found among 39" is a typo in a filename, "not
 *     found among 0" is a tree that was never walked, and whoever is reading the
 *     failure has to be able to tell those two apart.
 *   * TWO FILES WITH THAT NAME -> naming BOTH paths. Picking the one the walk saw first
 *     is the only failure this shape can produce SILENTLY: the wrong script, run under
 *     the right name, behaving plausibly.
 *   * A VALUE CARRYING A PATH SEPARATOR -> naming the value. The index is keyed by
 *     basename, so 'report/render-report.py' would either miss and report a name nobody
 *     spelled, or be quietly reduced to the basename and resolved out of a different
 *     directory than the caller wrote down. Dropping a directory the caller spelled is
 *     how a caller comes to believe the directory mattered — which is the exact belief
 *     this function exists to remove.
 */
export function resolveScript(basename, root = null) {
  const name = String(basename);
  const sep = SEPARATORS.find((s) => name.includes(s));
  if (sep !== undefined) {
    throw new Error(`resolveScript() takes a BASENAME and "${name}" carries the `
      + `directory separator "${sep}". The index is keyed by basename — the folders `
      + `under scripts/ are labels, not namespaces — so the directory you spelled `
      + 'would be dropped rather than honoured.');
  }
  const index = scriptIndex(root);
  const found = index.get(name) || [];
  if (found.length === 0) {
    let total = 0;
    for (const paths of index.values()) total += paths.length;
    throw new Error(`no script named "${name}" among the ${total} Python file(s) found `
      + `under ${root === null ? SCRIPTS : root}. (0 searched means the walk found `
      + 'nothing at all — a tree that is not there — which is a different problem from '
      + 'a misspelled name)');
  }
  if (found.length > 1) {
    throw new Error(`the basename "${name}" is claimed by ${found.length} files `
      + `(${found.join(', ')}) — import and every resolver here go by basename, so `
      + 'picking one would run the WRONG script under the RIGHT name. '
      + '_deps.layer_violations() fails the build on this same rule; this is it '
      + 'holding at capture time.');
  }
  return found[0];
}
