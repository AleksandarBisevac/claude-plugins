/**
 * Naming a `<details>` by what it CONTAINS, for the two browser gates.
 *
 * `.more` is a shared BEHAVIOURAL class and not an identity. `report-css/
 * segments.css` forces every `details.more` open on `beforeprint`, `usage.css`
 * and `tables.css` style it, and the test-evidence history reuses it ON PURPOSE
 * to inherit that print behaviour (`_report_html.py` emits
 * `class="more tevmore"`). So the class says "this disclosure expands for
 * print"; it says nothing about WHICH disclosure you are holding.
 *
 * Both gates used to open one by writing `document.querySelector('details.more')`,
 * which is not a rule — it is a snapshot of a page that happened to hold exactly
 * one. The moment the evidence history shipped, that selector started answering
 * "whichever comes FIRST in the document", and the two readings failed in
 * opposite ways: the report gate clicked an invisible disclosure inside a closed
 * task drawer and died on a 30-second timeout, while the responsive ladder
 * quietly opened the evidence history, left the Usage detail shut, and measured
 * exactly the absence its own comment said it must not. One loud, one green for
 * the wrong reason.
 *
 * THE RULE IS CONTAINMENT, and it is here so there is one copy of it. A caller
 * names the CONTENT it is about — the heatmap's calendar navigation, the usage
 * charts — and takes the disclosure around it. Nothing below counts `.more`,
 * matches `:nth-of-type`/`:first-of-type`, or subtracts `.tevmore`; every one of
 * those is the same snapshot in a new disguise, and the next disclosure to be
 * added breaks it exactly the way this one did. A third `.more`, of any class,
 * anywhere in the document, leaves these derivations untouched — the content
 * either has a `<details>` ancestor or it does not.
 */

/**
 * The heatmap's calendar navigation. The report gate opens the disclosure around
 * it so a reader — and the gate — can reach the granularity buttons.
 * @type {string}
 */
export const HEATMAP_NAV = '#audit-hm-gran';

/**
 * The Usage section's Detail charts, which have no layout at all while their
 * disclosure is shut. Both gates open the disclosure around these before walking
 * the responsive ladder, so the ladder measures them rather than measuring their
 * absence.
 *
 * Two anchors rather than one because the detail block is assembled from parts
 * that a report can lack independently (`_report_usage.py` joins the monthly
 * block, the small multiples, the phase stacks, the economics, the routing table
 * and the heatmap, then emits the disclosure only `if detail`). They are the
 * same disclosure by construction, so either one answers; listing both means a
 * report that renders one and not the other is still measured.
 * @type {string}
 */
export const USAGE_DETAIL_CHARTS = '.hmwrap, .smgrid';

/**
 * The disclosure around a piece of content — read IN THE PAGE. Playwright
 * serializes this into the browser, so it closes over nothing and takes its
 * selector as an argument.
 *
 * This is the single copy of the rule; everything else in this file calls it.
 * @param {string} selector
 * @returns {HTMLDetailsElement|null}
 */
export const disclosureAround = (selector) => {
  const content = document.querySelector(selector);
  return content ? content.closest('details') : null;
};

/**
 * What state the disclosure around `selector` is in, optionally opening it
 * first. The five answers are worded apart because they are five different
 * bugs, and a gate that collapsed them into a boolean would report "not open"
 * for a report that simply has no usage section.
 *
 *   'absent'                the content is not on this report at all
 *   'not in a disclosure'   the content moved out from under its `<details>`
 *   'shut'                  the disclosure exists and is closed
 *   'open but not laid out' open, yet the content still measures zero high
 *   'open'                  open, and the content has a box
 *
 * @param {import('playwright').Page} page
 * @param {string} selector content the disclosure is expected to wrap
 * @param {{open?: boolean}} [opts] `open: true` sets `open` rather than only reading it
 * @returns {Promise<string>}
 */
export async function readDisclosure(page, selector, { open = false } = {}) {
  const owner = (await page.evaluateHandle(disclosureAround, selector)).asElement();
  if (!owner) {
    return await page.evaluate((s) => !!document.querySelector(s), selector)
      ? 'not in a disclosure' : 'absent';
  }
  return owner.evaluate((d, { sel, wanted }) => {
    if (wanted) d.open = true;
    if (!d.open) return 'shut';
    return document.querySelector(sel).getBoundingClientRect().height > 0
      ? 'open' : 'open but not laid out';
  }, { sel: selector, wanted: open });
}

/**
 * The disclosure's OWN summary — `:scope >`, so a nested `<details>` inside it
 * cannot answer instead. Handed back as a handle because a gate that means to
 * drive it like a reader clicks the summary rather than poking `open`.
 * @param {import('playwright').Page} page
 * @param {string} selector content the disclosure is expected to wrap
 * @returns {Promise<import('playwright').ElementHandle|null>}
 */
export async function disclosureSummary(page, selector) {
  const owner = (await page.evaluateHandle(disclosureAround, selector)).asElement();
  if (!owner) return null;
  const summary = await owner.evaluateHandle((d) => d.querySelector(':scope > summary'));
  return summary.asElement();
}
