// What a Composition phase row says about its sign-off, driven rather than read.
//
// The server decides where sign-off stands (`_panel_composition` ships the
// derived status, `signoffDue` and `signoffVerdict`); this proves the words the
// row puts beside it say that and nothing else. The row used to derive the state
// itself from `every task done`, which counted a cancelled task as open and told
// a phase that was already signed off to go and get signed off.
//
// Whether the note is painted where the eye trips on it belongs to the browser
// gates. What this proves is what the words SAY.
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';

const P = reach(loadPanel().ctx, ['phaseSignoffNote']);

const phase = (over) => Object.assign(
  { id: 'P4', status: 'in_progress', signoffDue: false, signoffVerdict: null,
    branch: null }, over || {});

describe('the sign-off note on a phase row', () => {
  it('a phase awaiting sign-off is told both steps, naming its own id', () => {
    const note = P.phaseSignoffNote(phase({ signoffDue: true }));
    expect(note).toContain('sign-off due');
    expect(note).toContain('/audit:review');
    expect(note).toContain('/audit:phase signoff P4');
  });

  it('a phase signed off on an unmerged branch says what it waits for instead', () => {
    const note = P.phaseSignoffNote(
      phase({ signoffVerdict: 'passed', branch: 'audit/p4-x' }));
    expect(note).toContain('signed off (passed)');
    expect(note).toContain('audit/p4-x');
    expect(note).not.toContain('sign-off due');
  });

  it('a phase that is done, cancelled or still running carries no note', () => {
    expect(P.phaseSignoffNote(phase({ status: 'done', signoffVerdict: 'passed' })))
      .toBeNull();
    expect(P.phaseSignoffNote(phase({ status: 'cancelled' }))).toBeNull();
    expect(P.phaseSignoffNote(phase())).toBeNull();
  });
});
