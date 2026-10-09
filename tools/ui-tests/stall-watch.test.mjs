// The capture's stall watch: a run that stops printing is failed and ended, and a
// run that recovers on its own is left alone.
//
// WHY THESE ARE TESTED HERE AND NOT BY RUNNING THE CAPTURE. The watch only acts
// after minutes of silence, and the capture holds a machine-wide browser lock;
// neither is needed to tell a right watch from a wrong one. Fake timers drive the
// whole five minutes and the grace period in microseconds, and `process.exit` is
// stubbed, so the verdict is whether it was called and with what.
//
// BOTH DIRECTIONS. A watch that never ends a stuck run is the six-hour hang it
// exists to prevent; a watch whose grace timer outlives `stop()` exits 1 a run
// that already unwound and reported. The first two cases fail on the second
// defect, the third on the first.
//
// STALL_WATCH_MODULE points the suite at another copy of the watch (it must
// export `watchForStall`, `STALL_MS` and `STALL_GRACE_MS`), which is how a red
// against an older version is shown without editing the tree.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const target = process.env.STALL_WATCH_MODULE || '../capture-screenshots.mjs';
const { watchForStall, STALL_MS, STALL_GRACE_MS } = await import(target);

// Far enough past the stall AND its grace period that any timer either version
// arms has fired by the time the case reads the verdict.
const PAST_EVERYTHING = STALL_MS + 2 * STALL_GRACE_MS + 60000;

let exit;
// The watch measures silence from the module's own last-printed stamp, which a
// stall's failure line moves to the fake clock's time. Fake timers otherwise
// restart at the real time for every case, so a case after one that stalled would
// start BEFORE that stamp and see no silence at all. Each case's clock starts
// past everything the previous one could have reached.
let clock = Date.now();

beforeEach(() => {
  clock += 10 * PAST_EVERYTHING;
  vi.useFakeTimers({ now: clock });
  exit = vi.spyOn(process, 'exit').mockImplementation(() => {});
  // The watch reports through the capture's own printer; the cases read exit codes.
  vi.spyOn(console, 'log').mockImplementation(() => {});
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('watchForStall: a stalled run is ended, a recovered one is not', () => {
  it('leaves a stall that unwinds alone once the run stops the watch', async () => {
    let stop = null;
    // Closing the browser is what lets the stuck call throw; the run then reaches
    // main()'s `finally`, which stops the watch.
    const browser = { close: async () => { setTimeout(() => stop(), 10); } };
    const cleanUp = vi.fn(async () => {});
    stop = watchForStall(() => [], browser, cleanUp);
    await vi.advanceTimersByTimeAsync(PAST_EVERYTHING);
    expect(exit).not.toHaveBeenCalled();
    expect(cleanUp).not.toHaveBeenCalled();
  });

  it('arms nothing when the watch is stopped while the tick awaits the close', async () => {
    let stop = null;
    const browser = {
      close: () => new Promise((resolve) => setTimeout(() => { stop(); resolve(); }, 20)),
    };
    const cleanUp = vi.fn(async () => {});
    stop = watchForStall(() => [], browser, cleanUp);
    await vi.advanceTimersByTimeAsync(PAST_EVERYTHING);
    expect(exit).not.toHaveBeenCalled();
    expect(cleanUp).not.toHaveBeenCalled();
  });

  it('cleans up and exits 1 when the stall never unwinds', async () => {
    const browser = { close: async () => {} };
    const cleanUp = vi.fn(async () => {});
    const stop = watchForStall(() => [], browser, cleanUp);
    try {
      await vi.advanceTimersByTimeAsync(PAST_EVERYTHING);
      expect(exit.mock.calls).toEqual([[1]]);
      expect(cleanUp).toHaveBeenCalledTimes(1);
    } finally {
      stop();
    }
  });
});
