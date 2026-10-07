// The Usage tab at its edges: one bucket, and a payload that is not the payload.
//
// Both were reported by a documenting agent and left for a pass that could test
// them, and both are the shape where the code is confident and wrong rather than
// absent.
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import { pyCall } from './python-fmt.mjs';
import { loadPanel, reach } from './sandbox.mjs';

// --- the chart, the payload and the filter chips --------------------------

describe('the axis labels a one-bucket chart draws', () => {
  // The guard read `if (n < 2 && i) return`, over `[0, n-1]`. With one bucket
  // that array is [0, 0], so `i` is the VALUE 0 on both passes and the guard
  // never fired: the same date was drawn twice, once left-anchored at x=0 and
  // once right-anchored at the same x. The fix tests the POSITION.
  //
  // Asserted on the arithmetic rather than through the SVG, because the sandbox's
  // element stub does not build a real tree — what was wrong here is the guard's
  // subject, and that is expressible directly.
  const drawn = (n, guard) => {
    const out = [];
    [0, n - 1].forEach((i, j) => {
      if (guard === 'value' ? (n < 2 && i) : (n < 2 && j)) return;
      out.push(i);
    });
    return out;
  };

  it('the old guard drew two labels for a single bucket', () => {
    expect(drawn(1, 'value')).toEqual([0, 0]);
  });

  it('the position guard draws one', () => {
    expect(drawn(1, 'position')).toEqual([0]);
  });

  it('and both still draw two whenever there is more than one bucket', () => {
    for (const n of [2, 5, 30]) {
      expect(drawn(n, 'position'), 'n=' + n).toEqual([0, n - 1]);
      expect(drawn(n, 'value'), 'n=' + n).toEqual([0, n - 1]);
    }
  });

  // TYING THE ARITHMETIC TO THE SHIPPED CODE is a claim about SOURCE TEXT, so it
  // is pinned in test__panel_page.py rather than faked here. The case that used
  // to sit at this spot read `expect(uChartSourceProbe).toBe(undefined)` against
  // a key `reach` never returns - vacuously true, asserting nothing, which is the
  // failure this whole suite exists to prevent. Deleted rather than repaired:
  // there was nothing in it to repair.
});

describe('a /api/usage response that is JSON but not the usage payload', () => {
  // `api()` returns `r.json()` whatever the status, so a server error that
  // serialises cleanly arrives as a truthy object with no `facts`. The guard read
  // `!USAGE || !USAGE.facts.length`, which dereferences `facts` on exactly that
  // object — so the tab went blank with a console trace instead of saying
  // anything a reader could act on.
  const emptyStateFor = (payload) => {
    const { ctx } = loadPanel();
    vm.runInContext('USAGE = ' + JSON.stringify(payload) + ';', ctx);
    const { renderUsage } = reach(ctx, ['renderUsage']);
    let threw = null;
    try { renderUsage(); } catch (cause) { threw = cause; }
    return threw;
  };

  it('does not throw where it used to [was: blank tab, console trace]', () => {
    expect(emptyStateFor({ error: 'metering is not configured' })).toBe(null);
  });

  it('nor when facts is present but the wrong type', () => {
    expect(emptyStateFor({ facts: null })).toBe(null);
    expect(emptyStateFor({ facts: 'nope' })).toBe(null);
    expect(emptyStateFor({ facts: {} })).toBe(null);
  });

  it('and the ordinary empty payload is still the ordinary empty payload', () => {
    // The half that stops the guard from being satisfiable by refusing every
    // payload: a real, well-formed, empty ledger must still reach the empty state
    // rather than an error path.
    expect(emptyStateFor({ facts: [], enabled: true, counts: {} })).toBe(null);
  });
});

describe('the filters that are on, once the controls fold away', () => {
  // The controls sit behind a shut <details> now, so the chip row above it is the
  // only thing on screen saying the numbers below are a subset. That makes "which
  // filters are on" a list the page cannot afford to hold two opinions about --
  // and it is behaviour, not source text, so it belongs here rather than in
  // test__panel_page.py's pins.
  const panel = () => {
    const { ctx } = loadPanel();
    // A well-formed empty ledger: every mutator below re-renders, and this is the
    // payload renderUsage returns early from in a stub DOM.
    vm.runInContext('USAGE = { facts: [], enabled: true, counts: {} };', ctx);
    return { ctx, run: (src) => vm.runInContext(src, ctx) };
  };

  it('counts the range preset, which wears no UF slot of its own', () => {
    const { run } = panel();
    // The fixture that separates the two implementations: the chip row used to
    // walk UORDER alone, and the range is not in it. So this is precisely the
    // state where a filter was on and nothing on screen named it.
    run("UORDER = []; UF.range = '30';");
    expect(run('uOnFilters()')).toEqual(['range']);
    expect(run('uAnyFilter()')).toBe(true);
  });

  it('keeps the range LAST, so Escape still pops it after the dimensions', () => {
    const { run } = panel();
    run("UF.model = 'opus'; UORDER = ['model']; UF.range = '30';");
    expect(run('uOnFilters()')).toEqual(['model', 'range']);
  });

  it('and reports nothing on when nothing is on', () => {
    // The second-direction case, and the one that looks vacuous: it passes on the
    // pre-change code by construction and is the only one that fails if the list
    // (or the chip row, or the summary's count) becomes unconditional.
    const { run } = panel();
    run("UORDER = []; UF.range = 'all'; UF.model = '';");
    expect(run('uOnFilters()')).toEqual([]);
    expect(run('uAnyFilter()')).toBe(false);
  });

  it('lifts the range back to its default rather than blanking it', () => {
    const { run } = panel();
    run("UF.range = '30';");
    run("uLiftF('range');");
    expect(run('UF.range')).toBe('all');
    expect(run('uOnFilters()')).toEqual([]);
    // WHY 'all' and not '': uFiltered reads any other value as a preset in days,
    // and parseInt('') is NaN. This is the buggy version, run on purpose, so the
    // case above is known to separate the two rather than merely to pass.
    run("UF.range = '';");
    expect(() => run('uFiltered()')).toThrow();
  });

  it('lifts an ordinary dimension by blanking its slot', () => {
    const { run } = panel();
    run("setF('model', 'opus');");
    expect(run('uOnFilters()')).toEqual(['model']);
    run("uLiftF('model');");
    expect(run('UF.model')).toBe('');
    expect(run('uOnFilters()')).toEqual([]);
  });

  // WHAT IS DELIBERATELY NOT HERE: whether the Filters fold arrives shut, stays
  // as the reader left it across a repaint, and shows a count while something is
  // filtering. Two cases for that were written and deleted rather than kept,
  // because nothing here could make them fail: the fold's state is read off the
  // rendered <details>, the stub document's querySelector returns a stub for
  // every selector, and it has no createElementNS at all -- so a renderUsage
  // over a real ledger dies in the chart long before the fold, and one over an
  // empty ledger returns before it. A case that cannot go red is the failure
  // this suite exists to prevent. The claim lives where it can be measured:
  // openUsageFilters in tools/capture-screenshots.mjs checks all three against a
  // real browser, and test__panel_page.py's uf3 pins that the state has exactly
  // one home.
});

// --- coverage beside cost per task ------------------------------------------

describe('attribution coverage beside cost per task', () => {
  // uUnit/uRouting/uCoverageLine are pure (no DOM), so they are exercised
  // directly rather than through renderUsage — which, per the note just above,
  // dies in the chart on any non-empty ledger in this sandbox. That also means
  // this is the same route that would prove the cost-per-task tile's sub-line
  // and the routing table's caption, since both call uCoverageLine with the
  // same uUnit(facts).doneTaskCoverage rather than each computing their own.
  function panel() {
    const { ctx } = loadPanel();
    return { ctx, run: (src) => vm.runInContext(src, ctx) };
  }

  function withTaskMeta(ctx, taskMeta) {
    vm.runInContext('USAGE = { taskMeta: ' + JSON.stringify(taskMeta) + ' };', ctx);
  }

  function fact(F, task, tokens, attr) {
    const row = [];
    row[F.ts] = '2026-01-01T00:00:00Z';
    row[F.phase] = 'P1';
    row[F.task] = task;
    row[F.model] = 'sonnet';
    row[F.author] = 'me';
    row[F.agent] = 'ag';
    row[F.attr] = attr || 'task';
    row[F.tokens] = tokens;
    row[F.cost] = tokens * 0.001;
    row[F.msgs] = 1;
    return row;
  }

  // Three done tasks in the plan, one with risk 'high' and no row at all below,
  // plus a pending task that must never enter either count.
  const TASK_META = {
    T1: { status: 'done', risk: 'high' },
    T2: { status: 'done', risk: 'low' },
    T3: { status: 'done', risk: 'high' },
    T4: { status: 'pending', risk: 'high' },
  };

  it('counts the done-task denominator from the WHOLE plan, not the rows', () => {
    const { ctx, run } = panel();
    withTaskMeta(ctx, TASK_META);
    const { uUnit, F } = reach(ctx, ['uUnit', 'F']);
    // Only T1 ever appears in the rows handed to uUnit.
    const facts = [fact(F, 'T1', 10)];
    expect(uUnit(facts).doneTaskCoverage).toEqual({ done: 3, priced: 1 });
  });

  it('filtering the rows narrows the numerator only', () => {
    const { ctx } = panel();
    withTaskMeta(ctx, TASK_META);
    const { uUnit, F } = reach(ctx, ['uUnit', 'F']);
    const all = [fact(F, 'T1', 10), fact(F, 'T2', 20)];
    expect(uUnit(all).doneTaskCoverage).toEqual({ done: 3, priced: 2 });
    // Narrowed to T1's own row: the denominator (every done task in the plan)
    // must not shrink along with the view.
    const narrowed = all.filter((f) => f[F.task] === 'T1');
    expect(uUnit(narrowed).doneTaskCoverage).toEqual({ done: 3, priced: 1 });
  });

  it('never attributes main-loop spend (task id "--") to a done task', () => {
    const { ctx } = panel();
    withTaskMeta(ctx, TASK_META);
    const { uUnit, F } = reach(ctx, ['uUnit', 'F']);
    const facts = [fact(F, 'T1', 10), fact(F, '--', 999999)];
    // The huge main-loop row changes neither side of the count.
    expect(uUnit(facts).doneTaskCoverage).toEqual({ done: 3, priced: 1 });
  });

  it('is null with no done task in the plan at all [empty-ledger silence]', () => {
    const { ctx } = panel();
    withTaskMeta(ctx, { T4: { status: 'pending', risk: 'high' } });
    const { uUnit, uCoverageLine, F } = reach(ctx, ['uUnit', 'uCoverageLine', 'F']);
    expect(uUnit([fact(F, 'T4', 10)]).doneTaskCoverage).toBe(null);
    expect(uCoverageLine(null)).toBe(null);
  });

  it('pins the sentence for full coverage, exactly as coverage_sentence() words it', () => {
    const { ctx } = panel();
    const { uCoverageLine } = reach(ctx, ['uCoverageLine']);
    expect(uCoverageLine({ done: 2, priced: 2 })).toBe(
      'Of the plan\'s 2 done task(s), 2 are priced; main-loop spend is not '
      + 'attributed to a task.');
  });

  it('pins the same sentence, unconditionally, for partial coverage too '
    + '[was: a shortfall clause only the panel printed]', () => {
    const { ctx } = panel();
    const { uCoverageLine } = reach(ctx, ['uCoverageLine']);
    // The wording is fixed now (it mirrors coverage_sentence() byte for byte),
    // so there is no second clause to fire conditionally - this is the case
    // that would catch one being added back.
    expect(uCoverageLine({ done: 3, priced: 2 })).toBe(
      'Of the plan\'s 3 done task(s), 2 are priced; main-loop spend is not '
      + 'attributed to a task.');
  });

  // The two cases above pin the panel against a sentence typed into this file,
  // which proves only that two people agreed. This one asks Python: the
  // expectation is `coverage_sentence()` itself, fetched through the
  // `usage_ledger` re-export every other caller reaches it by, for the same
  // counts. Fixtures where done and priced differ, so a swapped pair fails.
  it('says exactly what Python coverage_sentence() says for the same done and '
    + 'priced counts', () => {
    const { ctx } = panel();
    const { uCoverageLine } = reach(ctx, ['uCoverageLine']);
    const covs = [{ done: 1, priced: 0 }, { done: 3, priced: 2 },
      { done: 7, priced: 7 }, { done: 12, priced: 5 }];
    const py = pyCall('usage_ledger', covs.map((c) => ['coverage_sentence', [c]]));
    expect(py.length).toBe(covs.length);
    covs.forEach((c, i) => {
      expect(typeof py[i], JSON.stringify(c)).toBe('string');
      expect(uCoverageLine(c), JSON.stringify(c)).toBe(py[i]);
    });
    // Both sides are silent for the same reason: no done task to cover.
    expect(pyCall('usage_ledger', [['coverage_sentence', [null]]])[0]).toBe(null);
    expect(uCoverageLine(null)).toBe(null);
  });

  it('the routing table cannot show a done task its own rows never mention, '
    + 'which is exactly what the coverage line beside it states', () => {
    const { ctx } = panel();
    withTaskMeta(ctx, TASK_META);
    const { uUnit, uRouting, uCoverageLine, F } = reach(
      ctx, ['uUnit', 'uRouting', 'uCoverageLine', 'F']);
    const facts = [fact(F, 'T1', 10), fact(F, 'T2', 20)];
    const rows = uRouting(facts);
    const tasksShown = rows.reduce((a, r) => a + r.tasks, 0);
    expect(tasksShown).toBe(2); // T1 and T2 - T3 has no row at all
    const cov = uUnit(facts).doneTaskCoverage;
    expect(cov).toEqual({ done: 3, priced: 2 });
    expect(uCoverageLine(cov)).toBe(
      'Of the plan\'s 3 done task(s), 2 are priced; main-loop spend is not '
      + 'attributed to a task.');
  });
});

// --- the showCost gate, driven through renderUsage -------------------------

describe('with showCost off the tab prints no per-task dollar figure', () => {
  // Driven through renderUsage itself, not through a helper the render is
  // believed to call: the defect was a render that skipped the gate its
  // neighbours keep, and only the render can show that. The note above about
  // renderUsage dying in the chart is about the shared stub, whose append()
  // keeps nothing and which has no createElementNS. This block swaps in a
  // recording builder for its own context only, so the tree the tab builds can
  // be read back as text.
  function recordingPanel() {
    const { ctx } = loadPanel();
    const doc = vm.runInContext('document', ctx);
    const make = doc.createElement.bind(doc);
    const keep = (e) => {
      e.kids = [];
      e.append = (...k) => { e.kids.push(...k); };
      e.appendChild = (c) => { e.kids.push(c); return c; };
      e.prepend = (...k) => { e.kids.unshift(...k); };
      e.replaceChildren = (...k) => { e.kids = [...k]; };
      return e;
    };
    doc.createElement = (t) => keep(make(t));
    doc.createElementNS = (_ns, t) => keep(make(t));
    const root = keep(make('div'));
    doc.querySelector = (s) => (s === '#usage' ? root : keep(make('div')));
    return { ctx, root };
  }

  const text = (n) => {
    if (n == null) return '';
    if (typeof n === 'string') return n;
    if (n.nodeType === 3) return n.textContent;
    return (n.textContent || '') + (n.kids || []).map(text).join('');
  };
  const all = (n, pred, out = []) => {
    if (n && typeof n === 'object' && n.nodeType === 1) {
      if (pred(n)) out.push(n);
      (n.kids || []).forEach((k) => all(k, pred, out));
    }
    return out;
  };
  const hasClass = (c) => (n) => String(n.className || '').split(/\s+/).includes(c);
  const DOLLAR = /\$\d|<\$0\.01/;

  // Six done tasks: past the projection's sample gate, so the projection fact
  // is drawn rather than the sample-size notice. One retried task, so the
  // retry fact has spend to state, and one advice row, so the recommendation
  // has dollars to state. Every one of those is a dollar figure the report
  // withholds with showCost off.
  function render(showCost) {
    const { ctx, root } = recordingPanel();
    const { F } = reach(ctx, ['F']);
    const fact = (task, cost, day) => {
      const r = [];
      r[F.ts] = '2026-01-0' + day + 'T00:00:00Z';
      r[F.phase] = 'P1'; r[F.task] = task; r[F.model] = 'opus';
      r[F.author] = 'me'; r[F.agent] = 'ag'; r[F.attr] = 'task';
      r[F.tokens] = 1000; r[F.cost] = cost; r[F.msgs] = 1;
      return r;
    };
    const taskMeta = { T9: { status: 'pending', risk: 'low' } };
    const facts = [];
    for (let i = 1; i <= 6; i++) {
      taskMeta['T' + i] = { status: 'done', risk: 'high', attempts: i === 1 ? 2 : 1 };
      facts.push(fact('T' + i, i * 1.25, (i % 5) + 1));
    }
    const usage = {
      facts, enabled: true, counts: { phases: 1 }, taskMeta, showCost,
      routingAdvice: [{ risk: 'high', from: 'opus', to: 'sonnet', tasks: 6,
        fromMeanAttempts: 1.2, atToRates: 5, atFromRates: 26.25, saving: 21.25,
        savingPct: 81, evidenceTasks: 3, evidenceAttempts: 1 }],
    };
    vm.runInContext('USAGE = ' + JSON.stringify(usage) + ';', ctx);
    vm.runInContext('renderUsage();', ctx);
    const { uCoverageLine, uUnit } = reach(ctx, ['uCoverageLine', 'uUnit']);
    const covLine = uCoverageLine(uUnit(facts).doneTaskCoverage);
    const tiles = all(root, hasClass('utile'));
    const costTile = tiles.filter((t) => all(t, hasClass('k'))
      .some((k) => text(k) === 'cost per task'));
    const facts_ = all(root, hasClass('ufact')).map(text);
    const projection = facts_.filter((s) => s.startsWith('Remaining '));
    const projCov = all(root, (n) => n.getAttribute('data-ucov') === 'projection');
    const table = all(root, hasClass('utbl'));
    const heads = table.flatMap((t) => all(t, (n) => n.tagName === 'TH').map(text));
    const cells = table.flatMap((t) => all(t, (n) => n.tagName === 'TD').map(text));
    return { root, covLine, costTile, projection, projCov, heads, cells,
      whole: text(root) };
  }

  it('the cost-per-task tile is not drawn at all', () => {
    const r = render(false);
    expect(r.costTile.length).toBe(0);
  });

  it('...and with showCost on it is drawn once, with its figure and its '
    + 'coverage line [the twin: a gate that always fires fails here]', () => {
    const r = render(true);
    expect(r.covLine).toMatch(/^Of the plan's 6 done task/);
    expect(r.costTile.length).toBe(1);
    expect(text(r.costTile[0])).toMatch(DOLLAR);
    expect(text(r.costTile[0])).toContain(r.covLine);
  });

  it('the projection fact and its coverage line are withheld, and the '
    + 'sample-size notice does not stand in for them', () => {
    const r = render(false);
    expect(r.projection).toEqual([]);
    expect(r.projCov.length).toBe(0);
    // The projection was suppressed by showCost, not by sample size, so a
    // notice blaming the sample would be a false claim about why.
    expect(r.whole).not.toContain('Projection needs');
  });

  it('...and with showCost on the projection states its range and its '
    + 'coverage line once', () => {
    const r = render(true);
    expect(r.projection.length).toBe(1);
    expect(r.projection[0]).toMatch(DOLLAR);
    expect(r.projCov.map(text)).toEqual([r.covLine]);
  });

  it('the routing table drops its cost/task column, header and cells '
    + 'together, and the coverage line beside it', () => {
    const r = render(false);
    expect(r.heads).toEqual(['risk', 'model', 'tasks', 'mean attempts']);
    expect(r.cells.length).toBe(4);
    expect(r.cells.filter((c) => DOLLAR.test(c))).toEqual([]);
  });

  it('...and with showCost on the column is there, one dollar cell per row', () => {
    const r = render(true);
    expect(r.heads).toEqual(['risk', 'model', 'tasks', 'cost/task', 'mean attempts']);
    expect(r.cells.length).toBe(5);
    expect(r.cells.filter((c) => DOLLAR.test(c)).length).toBe(1);
    // The table's own coverage line: one in the tile, one for the projection,
    // one beside the table.
    expect(r.whole.split(r.covLine).length - 1).toBe(3);
  });

  it('no dollar figure anywhere on the tab, retry spend and the routing '
    + 'recommendation included', () => {
    const r = render(false);
    expect(r.whole.match(/\$[\d.,]+|<\$0\.01/g)).toBe(null);
    expect(r.whole).not.toContain(r.covLine);
    expect(r.whole).not.toContain('What the evidence supports');
  });

  it('...while with showCost on the retry spend and the recommendation are '
    + 'there [the twin of the case above]', () => {
    const r = render(true);
    expect(r.whole).toMatch(/\$1\.25 on tasks that needed more than one attempt/);
    expect(r.whole).toContain('What the evidence supports');
  });
});
