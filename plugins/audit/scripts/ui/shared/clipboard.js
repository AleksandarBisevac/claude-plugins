// ---------- the clipboard, and both of the ways it fails ----------
/**
 * Put `text` on the clipboard, and hand the outcome back to the caller.
 *
 * BOTH FAILURE PATHS, which is the entire reason this is a function rather than
 * a line. Over `file://` some browsers make `navigator.clipboard` throw and
 * others hand back a promise that REJECTS, and an implementation that handles
 * one of those is broken exactly where the report is most often opened — from
 * disk, by somebody who cannot fix it. Two sites had the rule right; a third
 * written from memory would have been a coin flip, and a button that silently
 * does nothing is worse than one that asks for a keystroke.
 *
 * THE FALLBACK IS THE CALLER'S, and that is not a shortcut. The two surfaces
 * answer differently and both answers are right: the panel copies through a
 * hidden textarea and toasts the text if even that is refused, the report selects
 * the text in place so a reader can press the keys themselves. A shared part that
 * picked one would be wrong on the other surface — which is why this row sat in
 * the duplication registry unextracted until the rule and the remedy were
 * separated.
 *
 * @param {string} text - what to put on the clipboard
 * @param {function(): void} onCopied - it worked
 * @param {function(): void} onFallback - it did not, either way; do it by hand
 * @returns {void} Nothing is returned and nothing is awaited: both outcomes are
 *   reported through the callbacks, so a caller cannot accidentally treat the
 *   promise's resolution as proof the text arrived.
 */
function copyText(text, onCopied, onFallback) {
  try {
    navigator.clipboard.writeText(text).then(onCopied, onFallback);
  } catch (cause) {
    onFallback();
  }
}
