// One broken view costs that view, not the panel.
//
// `boot()` ran seven renderers, the initial tab, the run poller and the tip
// placement as a single sequence of bare calls. They are independent of each
// other, so a throw in any one of them - a malformed ledger reaching
// `renderUsage` is the realistic one - skipped every later view, the tab
// restore, the run poller and the tip placement. The outer `boot().catch` then
// showed "load failed", naming the one thing that had NOT failed.
//
// Two levels, because the claim has two halves. `runContained` is a pure
// function and is tested as one. That boot() actually routes its steps through
// it is a fact about the call sites, so it is driven here with every step
// replaced by a recorder - which is what makes the premise controlled rather
// than inherited from whatever the stub DOM happens to break.
//
// WHAT THIS CANNOT SEE: whether a real renderer throws on real data. Nothing
// here supplies a browser or a real payload; it says only that a throw is
// contained wherever one comes from. The browser gates are what drive the
// painted page.
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';

/**
 * A panel, and the console the sandbox already records for it.
 *
 * Not a second recorder: `loadPanel` captures the context's console because the
 * page's own last line boots on load and the stub DOM cannot render every view.
 * Each entry is `[level, ...args]`.
 */
function quietPanel() {
  const loaded = loadPanel();
  return { ctx: loaded.ctx, errors: loaded.consoleErrors };
}

describe('runContained', () => {
  const { ctx, errors } = quietPanel();
  const { runContained } = reach(ctx, ['runContained']);

  it('runs every step in order and reports nothing when none throws', () => {
    const ran = [];
    const first = () => ran.push('first');
    const second = () => ran.push('second');
    expect(runContained([first, second])).toEqual([]);
    expect(ran).toEqual(['first', 'second']);
  });

  it('names the step that threw AND still runs the ones after it', () => {
    const ran = [];
    const before = () => ran.push('before');
    const boom = () => { ran.push('boom'); throw new Error('malformed ledger'); };
    const after = () => ran.push('after');
    expect(runContained([before, boom, after])).toEqual(['boom']);
    // The half that matters: `after` is the renderer, the tab restore and the
    // poller that used to be skipped.
    expect(ran).toEqual(['before', 'boom', 'after']);
  });

  it('reports several failures in the order they happened', () => {
    const one = () => { throw new Error('1'); };
    const fine = () => {};
    const two = () => { throw new Error('2'); };
    expect(runContained([one, fine, two])).toEqual(['one', 'two']);
  });

  it('and hands the cause to the console rather than swallowing it', () => {
    errors.length = 0;
    const boom = () => { throw new Error('the actual cause'); };
    runContained([boom]);
    expect(errors.length).toBe(1);
    // [level, message, cause] - the level is the recorder's, the rest is ours.
    expect(errors[0][0]).toBe('error');
    expect(String(errors[0][1])).toContain('boom');
    expect(String(errors[0][2] && errors[0][2].message)).toBe('the actual cause');
  });

  it('calls an unnamed step what it is, rather than leaving a blank in the list', () => {
    // A blank entry in a list of failures is something a reader reads past, and
    // an anonymous step is a wiring mistake worth seeing.
    expect(runContained([() => { throw new Error('x'); }])).toEqual(['(anonymous)']);
  });

  it('an empty list is not a failure, and not a silent success either', () => {
    // The guard on the guard: every case above passes over a function that
    // always returns []. This one pins that [] means "nothing threw" by pairing
    // it with a case that DOES throw in the same run.
    expect(runContained([])).toEqual([]);
    expect(runContained([function named() { throw new Error('x'); }])).toEqual(['named']);
  });
});

describe('boot() survives a view that throws', () => {
  const STEPS = ['renderViewer', 'renderSettings', 'renderComp', 'renderOver',
    'renderUsage', 'renderPolicy', 'renderAppearance',
    'showTab', 'startRunPoll', 'startTipPlacement'];

  // What a reader is shown is the step's own identifier. `showTab` is the one
  // step boot() has to wrap, because it takes an argument, so the name that
  // surfaces is the wrapper's - and the wrapper is named for the job it does
  // rather than the call it makes, which is the more useful of the two: the
  // initial-tab RESTORE is what failed, not showing tabs in general.
  const REPORTED = { showTab: 'showInitialTab' };
  const reportedName = (step) => REPORTED[step] || step;

  /**
   * Drive boot() with every step replaced by a recorder, one of them throwing.
   * @param {?string} broken the step name to break, or null for none
   */
  async function bootWith(broken) {
    const { ctx, errors } = quietPanel();
    const script = ['__ran = []; __toasts = [];']
      .concat(STEPS.map((n) => 'var ' + n + ' = function ' + n + '() { __ran.push("'
        + n + '"); if ("' + n + '" === ' + JSON.stringify(broken)
        + ') throw new Error("boom"); };'))
      // `tCaptureBase` is not one of the contained steps and runs before them;
      // it is stubbed only so the run reaches them.
      .concat(['var tCaptureBase = function tCaptureBase() {};',
        'var toast = function toast(m, k) { __toasts.push([m, k]); };'])
      .join('\n');
    vm.runInContext(script, ctx);
    // `loadPanel()` RUNS the page, and the last line of boot.js is
    // `boot().catch(...)` - so a boot is already in flight, parked on the stubbed
    // fetches, and it resumes into the recorders installed just above. Drained
    // and cleared here or every list below arrives doubled, which is how the
    // first version of this helper failed five cases for a reason that had
    // nothing to do with the code under test.
    for (let i = 0; i < 8; i++) await Promise.resolve();
    await new Promise((resolve) => { setImmediate(resolve); });
    vm.runInContext('__ran.length = 0; __toasts.length = 0;', ctx);
    const { boot } = reach(ctx, ['boot']);
    let rejected = null;
    try { await boot(); } catch (cause) { rejected = cause; }
    const { __ran, __toasts } = reach(ctx, ['__ran', '__toasts']);
    return { rejected, ran: __ran, toasts: __toasts, errors };
  }

  it('with nothing broken, every step runs and no toast is shown', async () => {
    const r = await bootWith(null);
    expect(r.rejected).toBe(null);
    expect(r.ran).toEqual(STEPS);
    expect(r.toasts).toEqual([]);
  });

  it('a throwing renderer no longer takes the tab, the poller and the tips '
     + 'with it [was: boot rejected at that renderer]', async () => {
    const r = await bootWith('renderUsage');
    expect(r.rejected).toBe(null);
    expect(r.ran).toEqual(STEPS);          // including everything after renderUsage
  });

  it('and the panel SAYS which part is missing, naming it', async () => {
    const r = await bootWith('renderUsage');
    expect(r.toasts.length).toBe(1);
    const [msg, kind] = r.toasts[0];
    expect(msg).toContain('renderUsage');
    expect(kind).toBe('err');
    // Not "load failed": the load succeeded, and blaming it sent a reader to
    // the wrong place. And no bare count in place of the name.
    expect(msg).not.toContain('load failed');
    expect(msg).toMatch(/console/);
  });

  it('a throwing step in the TAIL is contained too, and the poller after it '
     + 'still starts', async () => {
    const r = await bootWith('showTab');
    expect(r.rejected).toBe(null);
    expect(r.ran).toEqual(STEPS);
    expect(r.toasts[0][0]).toContain('showInitialTab');
  });

  it('every one of the ten steps is reached and contained — no step is wired '
     + 'outside the guard', async () => {
    // The check that would catch a step left as a bare call: it would reject
    // boot() instead of being reported.
    for (const step of STEPS) {
      const r = await bootWith(step);
      expect(r.rejected, step + ' rejected boot()').toBe(null);
      expect(r.toasts[0] && r.toasts[0][0], step + ' was not named in a toast')
        .toContain(reportedName(step));
      expect(r.ran, step + ' stopped a later step').toEqual(STEPS);
    }
  });
});

describe('the load-time boot reports where a test can see it', () => {
  // The recorder replaced hundreds of printed lines, so it owes proof that it
  // captures rather than discards. Without this case, silencing the console and
  // breaking the console would look identical from here.
  it('loadPanel keeps the contained failures, and they are the real ones', async () => {
    const loaded = loadPanel();
    // The page's last line is `boot().catch(...)`, parked on the stubbed fetches;
    // nothing is recorded until it resumes.
    expect(loaded.consoleErrors).toEqual([]);
    for (let i = 0; i < 8; i++) await Promise.resolve();
    await new Promise((resolve) => { setImmediate(resolve); });
    const contained = loaded.consoleErrors.filter(
      (e) => String(e[1]).startsWith('panel step failed'));
    expect(contained.length, 'nothing was recorded: either the stub DOM now '
      + 'renders every view - say so here if it does - or the recording broke')
      .toBeGreaterThan(0);
    // A cause, not just a message: an entry with nothing attached would name a
    // failure while losing the only thing that explains it.
    //
    // Not `instanceof Error`. The throw happens inside the vm's own realm, whose
    // Error is a different constructor from this file's, so the check would be
    // false for a perfectly good error - a harness fact, and one that would have
    // read as "the cause is missing".
    expect(contained.every((e) => e[2] && typeof e[2].message === 'string'
      && typeof e[2].stack === 'string')).toBe(true);
  });
});
