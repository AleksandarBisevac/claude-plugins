/**
 * How the panel gate presses Save's confirm button for a write and reads what the
 * write did - one helper, for every file the gate runs.
 *
 * WHY A FILE OF ITS OWN. The helper was born inside capture-screenshots.mjs, and the
 * stage checks under tools/ui-checks/ are imported BY that tool, so they cannot
 * import it back. Left there, the stage checks kept their own "click, sleep, read"
 * copy of the very shape the helper replaced. Both now import it from here.
 *
 * tools/ui-tests/confirm-write.test.mjs reads every file the gate runs - derived
 * from the tool's imports, not listed - and fails, naming file and line, a confirm
 * click followed by a fixed wait before the next read that is not excused by a row
 * of CONFIRM_WAIT_ALLOWED below.
 */

/**
 * The write requests a confirmed save sends, as `confirmWrite` matches them: the
 * method and the path, read off the panel's own save handlers (composition.js,
 * settings.js, policy-view.js, proposals-view.js). The policy save writes through
 * the config endpoint, so it is CONFIG_WRITE.
 */
export const COMPOSITION_WRITE = { method: 'PUT', path: '/api/composition' };
export const CONFIG_WRITE = { method: 'PUT', path: '/api/config' };
export const PROPOSAL_WRITE = { method: 'POST', path: '/api/proposal' };

/**
 * How long `confirmWrite` lets a confirmed save take to be answered, and then to be
 * acted on, before it fails naming the save. A bound on a hang, not a guess at how
 * long a save takes: the wait ends the moment the answer is handled.
 */
export const CONFIRM_ANSWER_MS = 30000;

/**
 * The confirm clicks that ARE followed by a fixed wait, each with the reason no
 * answer is waited for: `file`, relative to tools/; `find`, a snippet of the code
 * from the action that opened the dialog through the wait; `sites`, how many it
 * excuses, one unless said. Every row today is a Discard: its revert and its toast
 * run inside the click's own task, and it sends no request, so there is no answer
 * to wait for and the pause only lets the dialog close. The unit test fails a row
 * matching no site or a different number of sites than it says.
 * @type {Array<{file: string, find: string, sites?: number, reason: string}>}
 */
export const CONFIRM_WAIT_ALLOWED = [
  { file: 'capture-screenshots.mjs', find: '[data-discard=comp]',
    reason: 'confirms the Composition Discard, which sends no request; the pause lets the dialog close' },
  { file: 'capture-screenshots.mjs', find: 'discardBtn.click()',
    reason: 'confirms the Composition Discard, which sends no request; the pause lets the dialog close' },
  { file: 'capture-screenshots.mjs', find: '[data-discard=guards]',
    reason: 'confirms the settings Discard, which sends no request; the pause lets the dialog close' },
  { file: 'capture-screenshots.mjs', find: '[data-discard=ado]', sites: 2,
    reason: 'confirms the ADO card Discard, which sends no request; the pause lets the dialog close' },
  { file: 'ui-checks/stage-tabs.mjs', find: '[data-discard=policy]',
    reason: 'confirms the policy Discard, which sends no request; the pause lets the dialog close' },
];

/**
 * Press the open confirm dialog's primary button for a WRITE, and return once the
 * server has answered that write and the page has acted on the answer.
 *
 * Every confirmed save in the gate used to be "click, sleep a fixed number of ms,
 * read", and the number was a guess at how long the save takes. The composition
 * save grows with the plan it rewrites, and a CI runner is several times slower
 * than a laptop, so the read landed before the save had: the gate was reading an
 * outcome on a timer, red on one host and green on another.
 *
 * What it waits for instead, both armed BEFORE the click so neither can be missed:
 *   - the response to the write request itself, matched by `write.method` and
 *     `write.path` - which names the save when it never answers;
 *   - the page's toast being written. The saves the gate confirms report through
 *     `toast()` once they have acted: the composition and ADO saves call
 *     saveOutcome last, after re-reading the state and re-rendering; the settings
 *     save calls it and then only moves its draft's base in the same synchronous
 *     run, which ends before an observer is told; the proposal actions toast after
 *     their reload. Nothing in the panel toasts on a timer, so the first toast
 *     after the click is this save's answer, handled.
 *     A text assignment replaces the toast's child, so even a toast repeating the
 *     previous one's words is seen. The `show` class its own timer takes off is an
 *     attribute and is not observed.
 * One save path toasts BEFORE it has finished acting: the policy save reports and
 * then re-reads /api/policy and repaints. A read of that repaint needs a page
 * predicate after this helper returns, not more of this helper.
 *
 * Telling the two kinds of fixed pause apart: a pause belongs HERE when the line
 * after it reads something a request has to change - the file on disk, a row
 * re-rendered from the server's answer, the toast. A pause after an action that
 * sends no request - a Discard, whose revert and toast run inside the click's own
 * task; a dialog closing; a CSS transition - has no answer to wait for, and stays
 * a short literal, named in CONFIRM_WAIT_ALLOWED.
 *
 * A timeout is not a pass: it throws, naming the save, and saying whether the
 * request went unanswered or was answered and never acted on.
 *
 * @param {import('playwright').Page} page
 * @param {string} label - the leg's own name for this save, e.g. 'composition'
 * @param {{method: string, path: string}} write - the request the confirm sends
 * @param {function(string): void} during - the run's progress marker, told what
 *   this step is waiting for so a stall names it
 * @returns {Promise<{status: number, toast: string}>} the write's HTTP status and
 *   the toast the page wrote about it
 */
export async function confirmWrite(page, label, write, during) {
  const what = `${label}: the confirmed ${write.method} ${write.path}`;
  const answered = page.waitForResponse((r) => r.request().method() === write.method
    && new URL(r.url()).pathname === write.path, { timeout: CONFIRM_ANSWER_MS })
    .then((r) => ({ status: r.status() }),
          (err) => ({ lost: String(err).split('\n')[0] }));
  const seen = await page.evaluateHandle(() => {
    const t = document.querySelector('#toast');
    const box = { present: !!t, acted: false, text: null };
    if (t) {
      const mo = new MutationObserver(() => {
        mo.disconnect();
        box.acted = true;
        box.text = t.textContent;
      });
      mo.observe(t, { childList: true, characterData: true, subtree: true });
    }
    return box;
  });
  try {
    if (!(await seen.evaluate((b) => b.present))) {
      throw new Error(`${what}: the page has no #toast, so nothing on it can say `
        + `the save was handled`);
    }
    during(`${what}: waiting for its answer`);
    await page.locator('dialog.confirm [data-cfgo]').click();
    const res = await answered;
    if (res.lost) {
      throw new Error(`${what} got no answer within ${CONFIRM_ANSWER_MS} ms `
        + `(${res.lost})`);
    }
    const acted = await page.waitForFunction((b) => b.acted, seen,
      { timeout: CONFIRM_ANSWER_MS }).then(() => true, () => false);
    if (!acted) {
      throw new Error(`${what} was answered (HTTP ${res.status}) and the page never `
        + `acted on the answer within ${CONFIRM_ANSWER_MS} ms - no toast was written`);
    }
    return { status: res.status, toast: await seen.evaluate((b) => b.text) };
  } finally {
    await seen.dispose();
  }
}
