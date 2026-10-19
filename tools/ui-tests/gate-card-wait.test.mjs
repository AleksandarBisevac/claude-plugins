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
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { POLL_MARGIN_MS, POLL_WAIT_ALLOWED, pollIntervalOf, pollWindowMs } from '../capture-screenshots.mjs';
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

// --- the structural check over capture-screenshots.mjs ---------------------------

// The helpers a poll-dependent wait must be a call of, and the only wait primitives
// whose call sites are policed.
const HELPERS = ['waitForPoll', 'sleepPollWindow'];
const PRIMITIVES = ['waitForFunction', 'waitForTimeout', 'setTimeout'];

// The allow-list lives beside the helpers in capture-screenshots.mjs, where whoever
// adds a wait meets it; this file only polices it.
const ALLOWED = POLL_WAIT_ALLOWED;

// Source with comments blanked to spaces (offsets and newlines kept) and string
// contents blanked too, so a primitive's name inside a message or a comment is not
// a call site and a brace inside a string does not move the depth.
function blank(src) {
  let out = '';
  let i = 0;
  while (i < src.length) {
    const c = src[i];
    const n = src[i + 1];
    if (c === '/' && n === '/') {
      while (i < src.length && src[i] !== '\n') { out += ' '; i += 1; }
    } else if (c === '/' && n === '*') {
      const end = src.indexOf('*/', i + 2);
      const stop = end < 0 ? src.length : end + 2;
      out += src.slice(i, stop).replace(/[^\n]/g, ' ');
      i = stop;
    } else if (c === '"' || c === "'" || c === '`') {
      out += c;
      i += 1;
      while (i < src.length && src[i] !== c) {
        if (src[i] === '\\') { out += ' '; i += 1; }
        out += src[i] === '\n' ? '\n' : ' ';
        i += 1;
      }
      out += c;
      i += 1;
    } else {
      out += c;
      i += 1;
    }
  }
  return out;
}

// The index one past the bracket that closes the one opening at `open`.
function closeOf(text, open) {
  const pair = { '(': ')', '{': '}' }[text[open]];
  let depth = 0;
  for (let i = open; i < text.length; i += 1) {
    if (text[i] === text[open]) depth += 1;
    else if (text[i] === pair) {
      depth -= 1;
      if (depth === 0) return i + 1;
    }
  }
  throw new Error('unbalanced ' + text[open] + ' at offset ' + open);
}

// [start, end) of the body of the function the file declares under `name`.
function bodyOf(blanked, name) {
  const decl = new RegExp('(?:function\\s+' + name + '\\s*\\(|(?:const|let)\\s+' + name + '\\s*=)', 'g');
  const found = [...blanked.matchAll(decl)];
  if (found.length !== 1) {
    throw new Error(name + ' is declared ' + found.length + ' times in capture-screenshots.mjs, not once');
  }
  const open = blanked.indexOf('{', found[0].index);
  return [open, closeOf(blanked, open)];
}

// A wait is poll-dependent when it names the poll's state (RUNSTATUS, pollRunStatus)
// or carries a number of milliseconds at least the poll interval: no step that only
// waits for the page to settle sits that long, so a wait that long is waiting on
// something timed by the poll. WHAT THIS CANNOT SEE: a poll-dependent wait that is
// shorter than the interval and names nothing of the poll - that one is a wrong
// wait whatever it is called, and the interval it would have to undercut is the one
// the panel declares.
function pollDependent(text, intervalMs) {
  if (/\b(?:RUNSTATUS|pollRunStatus)\b/.test(text)) return true;
  return (text.match(/\b\d{4,}\b/g) || []).some((n) => Number(n) >= intervalMs);
}

// Every call site of a wait primitive that depends on the poll, as {offset, line,
// text}, text being the whole call; the helper bodies are where the primitives are
// meant to live and are left out.
function waitSites(src, intervalMs) {
  const blanked = blank(src);
  const inside = HELPERS.map((h) => bodyOf(blanked, h));
  const call = new RegExp('\\b(?:' + PRIMITIVES.join('|') + ')\\s*\\(', 'g');
  return [...blanked.matchAll(call)]
    .filter((m) => !inside.some(([a, b]) => m.index >= a && m.index < b))
    .map((m) => ({
      offset: m.index,
      line: blanked.slice(0, m.index).split('\n').length,
      text: src.slice(m.index, closeOf(blanked, blanked.indexOf('(', m.index))),
    }))
    .filter((s) => pollDependent(s.text, intervalMs));
}

// What is wrong with `src` as a place for waits: the poll-dependent sites that are
// neither inside a helper nor allow-listed, the allow-list entries matching no site
// or more than one, and the entries that carry no reason.
function waitFindings(src, allowed, intervalMs) {
  const sites = waitSites(src, intervalMs);
  const hits = (a) => sites.filter((s) => s.text.includes(a.find));
  return {
    sites,
    unlisted: sites.filter((s) => !allowed.some((a) => s.text.includes(a.find))),
    stale: allowed.filter((a) => hits(a).length === 0),
    broad: allowed.filter((a) => hits(a).length !== (a.sites || 1)),
    unreasoned: allowed.filter((a) => typeof a.reason !== 'string' || a.reason.trim() === ''),
  };
}

describe('every poll-dependent wait routes through the helper', () => {
  it('a hand-written poll-dependent wait with another number in a scratch copy of capture-screenshots.mjs is refused, and every real call site is a helper call or an allow-listed entry with a reason', () => {
    const real = readFileSync(CAPTURE, 'utf8');
    const interval = pollIntervalOf(assemblePanelBody());

    // The real file: nothing unlisted, nothing stale, nothing without a reason.
    const found = waitFindings(real, ALLOWED, interval);
    expect(found.unlisted.map((s) => 'line ' + s.line + ': ' + s.text)).toEqual([]);
    expect(found.stale.map((a) => a.find)).toEqual([]);
    expect(found.broad.map((a) => a.find)).toEqual([]);
    expect(found.unreasoned.map((a) => a.find)).toEqual([]);
    // Both helpers are still called by the file (a file that stopped using them
    // would satisfy the rule above by having no waits to police).
    for (const h of HELPERS) {
      expect(real.split(h + '(').length - 1, h + ' has no call site').toBeGreaterThan(1);
    }

    // The other direction: a hand-written wait with another number is refused. It is
    // written into a scratch copy outside the tree, never into the real file, and
    // every primitive is tried so a scan that watched only one would pass.
    const dir = mkdtempSync(path.join(tmpdir(), 'wait-scan-'));
    try {
      for (const [i, wait] of [
        'await page.waitForTimeout(7123);',
        'await page.waitForFunction(() => document.title === "x", null, { timeout: 7123 });',
        'await new Promise((r) => setTimeout(r, 7123));',
        // Below the interval, but it names the poll's state.
        'await page.waitForFunction(() => RUNSTATUS.x === 1, null, { timeout: 7123 });',
      ].entries()) {
        const scratch = path.join(dir, 'copy' + i + '.mjs');
        writeFileSync(scratch, real + '\nasync function handWritten(page) { ' + wait + ' }\n');
        const bad = waitFindings(readFileSync(scratch, 'utf8'), ALLOWED, interval);
        expect(bad.unlisted.map((s) => s.text), wait).toHaveLength(1);
        expect(bad.unlisted[0].text).toContain('7123');
      }
      // The other mutation: a wait that only lets the page settle is not the rule's
      // business, so a scan that flagged every wait would fail here.
      const settle = path.join(dir, 'settle.mjs');
      writeFileSync(settle, real + '\nasync function s(page) { await page.waitForTimeout(250); }\n');
      expect(waitFindings(readFileSync(settle, 'utf8'), ALLOWED, interval).unlisted).toHaveLength(0);
      // An allow-list entry for a wait that is not there is stale, not silently kept.
      const ghost = waitFindings(real, [...ALLOWED, { find: 'no-such-wait(', reason: 'x' }], interval);
      expect(ghost.stale.map((a) => a.find)).toEqual(['no-such-wait(']);
      // And an entry without a reason is reported.
      const bare = waitFindings(real, [...ALLOWED, { find: 'setTimeout(', reason: ' ' }], interval);
      expect(bare.unreasoned).toHaveLength(1);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
