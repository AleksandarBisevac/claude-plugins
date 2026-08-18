// One RFC 4180 quoter, written twice: report.js's `csvQuote` and the `q` closed
// over inside panel.js's `uCsvText`. The two regexes are byte-identical today,
// which is precisely why nothing would notice if one of them changed.
//
// The panel's copy is not a top-level name, so it is exercised through its real
// call site — a whole CSV row rendered by uCsvText, compared field for field
// against the same row quoted with report.js's function. That is a stronger
// claim than calling two lookalike helpers side by side: it says the shipped
// export produces the shipped quoting.

import { describe, expect, it } from 'vitest';
import { loadPanel, loadReport, reach } from './sandbox.mjs';

const { csvQuote } = reach(loadReport().ctx, ['csvQuote']);
const { uCsvText, F } = reach(loadPanel().ctx, ['uCsvText', 'F']);

// Every branch of `/[",\r\n]/` and both of its neighbours: a value that needs no
// quoting at all, one per trigger character, the doubling rule, and the shapes
// that LOOK like they should trigger it and must not (a lone apostrophe,
// surrounding spaces, a semicolon).
const VALUES = [
  'plain',
  '',
  'has,comma',
  'has"quote',
  'has""two',
  '"already quoted"',
  'line\nbreak',
  'carriage\rreturn',
  'crlf\r\nboth',
  'comma,and"quote',
  ' padded ',
  "it's fine",
  'semi;colon',
  'unicode — ✓',
  null,
  undefined,
];

function panelRow(value) {
  const row = [];
  row[F.ts] = value;
  row[F.phase] = 'P1';
  row[F.task] = value;
  row[F.model] = 'sonnet';
  row[F.author] = value;
  row[F.agent] = 'ag';
  row[F.attr] = 'direct';
  row[F.tokens] = 1234;
  row[F.cost] = 0.5;
  row[F.msgs] = 7;
  return row;
}

function reportRow(value) {
  const row = panelRow(value);
  const fields = row.slice();
  fields[F.cost] = row[F.cost].toFixed(6);   // uCsvText's own shaping, before quoting
  return fields.map(csvQuote).join(',');
}

describe('the two CSV quoters agree', () => {
  it.each(VALUES.map((v, i) => [i, v]))('value #%i quotes identically', (_i, value) => {
    const text = uCsvText([panelRow(value)]);
    const [header, ...rest] = text.split('\r\n');
    expect(header).toContain('ts,phase,task');
    // Rejoined: a value containing a CR or LF spans several physical lines, and
    // splitting them apart then comparing only the first is how a test for
    // newline handling ends up never seeing a newline.
    const body = rest.join('\r\n');
    expect(body).toBe(reportRow(value) + '\r\n');
  });

  it('covers every trigger character at least once', () => {
    // The table above is only worth what it contains. If someone trims it,
    // this says so instead of the suite quietly narrowing.
    const joined = VALUES.filter((v) => typeof v === 'string').join('');
    expect(joined).toContain(',');
    expect(joined).toContain('"');
    expect(joined).toContain('\n');
    expect(joined).toContain('\r');
    expect(VALUES.length).toBeGreaterThanOrEqual(16);
  });
});

describe('the quoting rule itself', () => {
  it('quotes only what RFC 4180 requires', () => {
    expect(csvQuote('plain')).toBe('plain');
    expect(csvQuote(' padded ')).toBe(' padded ');
    expect(csvQuote('a,b')).toBe('"a,b"');
    expect(csvQuote('a"b')).toBe('"a""b"');
    expect(csvQuote('a\nb')).toBe('"a\nb"');
    expect(csvQuote('a\rb')).toBe('"a\rb"');
  });

  it('renders a missing value as empty, not as the word null', () => {
    expect(csvQuote(null)).toBe('');
    expect(csvQuote(undefined)).toBe('');
    // ...and 0 and false are values, not absences. `v == null` is the correct
    // test and `!v` is the bug it prevents; this is the case that would catch
    // the swap.
    expect(csvQuote(0)).toBe('0');
    expect(csvQuote(false)).toBe('false');
  });
});

describe('the exported file is a CSV a spreadsheet can read', () => {
  it('ends every record with CRLF, including the last', () => {
    const text = uCsvText([panelRow('a'), panelRow('b')]);
    expect(text.endsWith('\r\n')).toBe(true);
    // Counted, not merely present: header + two records = three terminators.
    expect(text.split('\r\n').length - 1).toBe(3);
  });

  it('sends numbers out raw, with no separators and no currency', () => {
    const line = uCsvText([panelRow('x')]).split('\r\n')[1];
    expect(line).toContain('1234');
    expect(line).not.toContain('1,234');
    expect(line).toContain('0.500000');
    expect(line).not.toContain('$');
  });
});
