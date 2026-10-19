// The wait every "a disk write reaches the screen" step in the browser check gives
// the panel, and why it is computed rather than typed.
//
// WHAT WENT WRONG. The check appended a line to the gate feed and waited a
// hand-written number of milliseconds for the Overview to show it. The panel polls
// run-status at its own interval, declared in its own script; the hand-written
// number was that interval plus a margin nobody had written down, so the two could
// drift apart without anything noticing, and an append landing just after a poll
// left only the margin. One run missed, the immediate rerun passed.
//
// WHY THE CASES ARE HERE. The browser check takes a machine-wide lock and minutes of
// browser time; the claim is about a number, and a number needs no browser.
//
// WHAT THIS CANNOT SEE: whether the margin is enough on a loaded machine. That is a
// measurement, and the elapsed-time line each wait prints in the check is where it
// is taken.
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { POLL_MARGIN_MS, pollIntervalOf, pollWindowMs } from '../capture-screenshots.mjs';
import { assemblePanelBody } from './sandbox.mjs';

const CAPTURE = path.join(
  path.dirname(fileURLToPath(import.meta.url)), '..', 'capture-screenshots.mjs');

describe('the poll-window wait', () => {
  it('the poll-window wait capture-screenshots.mjs exports is computed from the poll interval the assembled panel script declares and exceeds it by the documented margin, and a changed interval moves the wait', () => {
    const script = assemblePanelBody();
    const interval = pollIntervalOf(script);
    // The interval is the panel's own: the literal in the part that starts the poll.
    const declared = /RUNPOLL=setInterval\(pollRunStatus,(\d+)\)/.exec(script);
    expect(declared, 'run-status.js no longer starts the poll with setInterval').not.toBe(null);
    expect(interval).toBe(Number(declared[1]));

    // Exceeds the interval by exactly the documented margin, and the margin is real.
    expect(POLL_MARGIN_MS).toBeGreaterThan(0);
    expect(pollWindowMs(interval)).toBe(interval + POLL_MARGIN_MS);

    // A changed interval moves the wait: fixture values chosen so a retyped constant
    // (any one number) cannot satisfy all three.
    const moved = script.replace(declared[0], 'RUNPOLL=setInterval(pollRunStatus,12345)');
    expect(moved).not.toBe(script);
    expect(pollWindowMs(pollIntervalOf(moved))).toBe(12345 + POLL_MARGIN_MS);
    const slower = script.replace(declared[0], 'RUNPOLL=setInterval(pollRunStatus,777)');
    expect(pollWindowMs(pollIntervalOf(slower))).toBe(777 + POLL_MARGIN_MS);

    // No interval, or two, leaves nothing single to derive from: it throws rather
    // than answering with a default.
    expect(() => pollIntervalOf(script.replace(declared[0], 'RUNPOLL=null'))).toThrow(/0 setInterval/);
    expect(() => pollIntervalOf(script + '\nsetInterval(pollRunStatus, 1000);'))
      .toThrow(/2 setInterval/);

    // And no hand-written wait stands beside the computed one: the 6500 ms literal
    // and its seconds spelling, built rather than typed so this file does not itself
    // carry the shape it forbids.
    const src = readFileSync(CAPTURE, 'utf8');
    const ms = ['65', '00'].join('');
    const secs = ['6', '5s'].join('.');
    expect(src.split(ms).length - 1).toBe(0);
    expect(src.split(secs).length - 1).toBe(0);
  });
});
