/**
 * Reading a CSV the report exported.
 *
 * Extracted from capture-screenshots.mjs, which had grown past 8000 lines with no
 * top-level section markers at all: 112 declarations in one file, the largest of
 * them 1388 lines. These two are the smallest complete concern in it and they have
 * no dependency on the run at all - no flags, no problem list, no page - which is
 * why they move first and why they can be read without the capture around them.
 */

/**
 * One CSV record as fields, double-quote escaping respected (RFC 4180).
 *
 * F-D-1 (v0.37 A3): the borrowed substring regex this replaces
 * (`/"?\d+,\d{3}[,."]/`) read a legitimate 3-digit count after a date field
 * ("…-13,123,…" across a field boundary) as a thousands separator —
 * reproduced on a real ledger. Structure cannot be fooled that way: parse the
 * record into fields, then judge only the fields that claim to be numbers.
 * The report-side export check in tools/check-report-interactive.mjs is the
 * precedent. Exported so a probe can drive the assertion without a browser.
 */
export const csvFields = (line) => {
  const out = [];
  let cur = '';
  let q = false;
  for (let i = 0; i < line.length; i += 1) {
    const c = line[i];
    if (q) {
      if (c === '"' && line[i + 1] === '"') { cur += '"'; i += 1; }
      else if (c === '"') q = false;
      else cur += c;
    } else if (c === '"') q = true;
    else if (c === ',') { out.push(cur); cur = ''; }
    else cur += c;
  }
  out.push(cur);
  return out;
};

/**
 * First data line whose named numeric columns carry anything but a raw
 * number (grouping separators included), or whose field count disagrees with
 * the header — a spreadsheet reads either as text and every sum over the
 * column is then silently wrong. `lines` is header-first, BOM/CRLF stripped.
 * Returns null when every line is clean.
 */
export const firstNonRawNumberLine = (lines, numericCols) => {
  const head = csvFields(lines[0] || '');
  const idx = numericCols.map((c) => head.indexOf(c)).filter((i) => i >= 0);
  for (const line of lines.slice(1)) {
    const f = csvFields(line);
    if (f.length !== head.length) return line;
    if (idx.some((i) => !/^\d+(\.\d+)?$/.test(f[i]))) return line;
  }
  return null;
};

// --- resolving a script by basename --------------------------------------------
