// executor.waveWidth is a whole number of 1 or more, or the word auto. The
// config validator refuses the string "3", so the Settings box must send a typed
// 3 as the number 3. The parse is reached out of the loaded panel rather than
// retyped here.
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';

const parse = (v) => {
  const { parseIntOrAuto } = reach(loadPanel().ctx, ['parseIntOrAuto']);
  return JSON.parse(JSON.stringify(parseIntOrAuto(v)));
};

describe('parseIntOrAuto', () => {
  it('sends a typed number as a number, not a string', () => {
    expect(parse('3')).toEqual({ ok: true, value: 3 });
    expect(typeof parse(' 12 ').value).toBe('number');
  });
  it('sends auto as the word auto', () => {
    expect(parse('auto')).toEqual({ ok: true, value: 'auto' });
  });
  it.each(['0', '-1', '2.5', '1e3', 'many', 'Auto', '03', '99999999999999999999'])(
    'refuses %s with a reason', (v) => {
      const r = parse(v);
      expect(r.ok).toBe(false);
      expect(r.reason).toMatch(/whole number of 1 or more, or the word auto/);
    });
});
