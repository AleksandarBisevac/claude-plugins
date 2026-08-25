// --- the light/dark question -------------------------------------------------
//
// BOTH SURFACES ASK IT AND BOTH ANSWERED IT SEPARATELY. The panel's copy and the
// report's agreed on the rule and disagreed on one thing, which is exactly what a
// second implementation is for: the report guarded `window.matchMedia` before
// calling it and the panel did not, so in a context without it the panel threw
// where the report answered light. Neither surface knew the other had decided.
//
// The guarded reading is the one kept, and not as a compromise: a page opened
// over file://, printed, or embedded in a host that stubs its environment is a
// place the report already expected to run, and a theme helper that throws there
// takes the whole script down with it.

/**
 * Whether the reader's OS asks for a dark UI.
 *
 * @returns {boolean} false when the browser cannot answer the question, which is
 *   the honest answer rather than a guess: no preference expressed is the same
 *   ground the light palette already stands on
 */
const prefersDark = () =>
  Boolean(window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches);

/**
 * Whether the document is painting dark right now.
 *
 * An explicit `data-theme` on the root element wins; with no choice at all the OS
 * preference decides. Only 'dark' counts as an explicit dark — any other value
 * present means light, so a stray or future value cannot read as dark by accident.
 *
 * Reads `document.documentElement` rather than taking it: one attribute on one
 * element is the whole authority on both surfaces, the CSS themes off it, and a
 * parameter would invite a caller to ask about some other element and get an
 * answer the stylesheet does not agree with.
 *
 * @returns {boolean} true when the dark palette is in force
 */
const isDark = () => {
  const t = document.documentElement.getAttribute('data-theme');
  return t ? t === 'dark' : prefersDark();
};
