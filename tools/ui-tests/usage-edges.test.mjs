// The Usage tab at its edges: one bucket, and a payload that is not the payload.
//
// Both were reported by a documenting agent and left for a pass that could test
// them, and both are the shape where the code is confident and wrong rather than
// absent.
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import { pyCall } from './python-fmt.mjs';
import { loadPanel, loadReport, reach } from './sandbox.mjs';

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

describe('the panel CSV export honours showCost, the way report/exports.js\'s '
  + 'usageCsv already does', () => {
  // Mirrors the report's own rule rather than re-deriving one: the costUSD
  // column leaves the file, header and cells together, whenever the tab is
  // configured to withhold the figure on screen. `uCsvText` is called
  // directly - it is the panel's half of the same quoting contract
  // csv-quote.test.mjs already holds equal to the report's - with no USAGE
  // payload beyond the one flag under test.
  function csvFor(showCost) {
    const { ctx } = loadPanel();
    vm.runInContext('USAGE = ' + JSON.stringify({ showCost }) + ';', ctx);
    const { uCsvText, F } = reach(ctx, ['uCsvText', 'F']);
    const row = [];
    row[F.ts] = '2026-01-01T00'; row[F.phase] = 'P1'; row[F.task] = 'P1.T1';
    row[F.model] = 'claude-opus-5'; row[F.author] = 'a';
    row[F.agent] = 'orchestrator'; row[F.attr] = 'task'; row[F.tokens] = 100;
    row[F.cost] = 1.234567; row[F.msgs] = 2;
    return uCsvText([row]);
  }

  it('drops costUSD, header and cell together, with showCost off', () => {
    const text = csvFor(false);
    expect(text.split('\r\n')[0].split(',')).not.toContain('costUSD');
    expect(text).not.toContain('1.234567');
  });

  it('...and keeps costUSD, header and cell together, with showCost on', () => {
    const text = csvFor(true);
    expect(text.split('\r\n')[0].split(',')).toContain('costUSD');
    expect(text).toContain('1.234567');
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
    const { ctx } = panel();
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
      // The browse dialog opens itself modally; the shared stub has no dialog API.
      e.showModal = () => {};
      e.close = () => {};
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
  // has dollars to state. A budget on the one phase the rows land in, so the
  // budget block has spend and a budget to compare. Every one of those is a
  // dollar figure the report withholds with showCost off.
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
      phaseBudgets: { P1: 40 }, phaseTitles: { P1: 'the budgeted phase' },
      routingAdvice: [{ risk: 'high', from: 'opus', to: 'sonnet', tasks: 6,
        fromMeanAttempts: 1.2, atToRates: 5, atFromRates: 26.25, saving: 21.25,
        savingPct: 81, evidenceTasks: 3, evidenceAttempts: 1 }],
    };
    // BANDS is a cache the boot may already have filled from another payload.
    vm.runInContext('USAGE = ' + JSON.stringify(usage) + '; BANDS = null;', ctx);
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
    const budgets = all(root, hasClass('bud')).map(text);
    return { ctx, facts, root, covLine, costTile, projection, projCov, heads,
      cells, budgets, whole: text(root) };
  }

  // The browse dialog is opened the way its button opens it, over the same
  // facts the ranked list was drawn from, and read back off the dialog node.
  function browse(showCost, dim) {
    const { ctx, facts } = render(showCost);
    vm.runInContext('openBrowse(' + JSON.stringify(dim) + ', "Browse", USAGE.facts);', ctx);
    const dlg = vm.runInContext('BROWSE', ctx);
    expect(facts.length).toBe(6);
    const tds = (tr) => all(tr, (c) => c.tagName === 'TD');
    const heads = all(dlg, (n) => n.tagName === 'TH').map(text);
    const rows = all(dlg, (n) => n.tagName === 'TR' && tds(n).length > 0);
    const note = (dlg.kids || []).map(text).filter((s) => s.startsWith('cost band'));
    const pills = all(dlg, hasClass('bandpill')).map(text);
    return { heads, rows, tds, note, pills, whole: text(dlg) };
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

  it('the budget block is not drawn at all, as the report withholds its own', () => {
    const r = render(false);
    expect(r.budgets).toEqual([]);
    expect(r.whole).not.toContain('All budgeted phases');
  });

  it('...and with showCost on each budgeted phase states its spend of its '
    + 'budget, and the total row the same [the twin]', () => {
    const r = render(true);
    expect(r.budgets.length).toBe(2);
    expect(r.budgets[0]).toMatch(/\$26\.25 of \$40\.00/);
    expect(r.budgets[1]).toMatch(/All budgeted phases.*\$26\.25 of \$40\.00/);
  });

  it('the browse dialog for tasks shows no dollar figure: no cost column, and '
    + 'a band note that names the bands without their thresholds', () => {
    const b = browse(false, 'task');
    expect(b.whole.match(/\$[\d.,]+|<\$0\.01/g)).toBe(null);
    expect(b.heads).not.toContain('cost');
    expect(b.heads).toContain('cost band');
    expect(b.rows.length).toBe(6);
    b.rows.forEach((tr) => expect(b.tds(tr).length).toBe(b.heads.length));
    expect(b.note.length).toBe(1);
    expect(b.note[0]).toMatch(/typical.*high.*outlier/);
    expect(b.pills.length).toBe(6);
  });

  it('...and with showCost on the cost column and the dollar thresholds are '
    + 'there [the twin: a gate that always fires fails here]', () => {
    const b = browse(true, 'task');
    expect(b.heads).toContain('cost');
    expect(b.rows.length).toBe(6);
    expect(b.rows.filter((tr) => b.tds(tr).some((c) => DOLLAR.test(text(c))))
      .length).toBe(6);
    expect(b.note.length).toBe(1);
    expect(b.note[0]).toMatch(/typical ≤ \$\d.*high ≤ \$\d/);
  });

  it('every dimension drops the cost column, header and cells together', () => {
    for (const dim of ['phase', 'model', 'author', 'task']) {
      const off = browse(false, dim), on = browse(true, dim);
      expect(off.heads, dim).not.toContain('cost');
      expect(off.whole.match(/\$[\d.,]+|<\$0\.01/g), dim).toBe(null);
      expect(off.rows.length, dim).toBeGreaterThan(0);
      off.rows.forEach((tr) => expect(off.tds(tr).length, dim).toBe(off.heads.length));
      expect(on.heads, dim).toContain('cost');
      expect(on.heads.length, dim).toBe(off.heads.length + 1);
    }
  });

  // Nested here for the recording builder above, which it needs to read the
  // tab back as text; the subject is the unpriced word, not the showCost gate.
  describe('a model no rate covers', () => {
    // 'mystery' is wholly unpriced: cost 0 because nothing priced it, not
    // because it was free. 'opus' is priced, with a figure under its tokens.
    function renderUnpriced(withUnpriced, extra, tailRows) {
      const { ctx, root } = recordingPanel();
      const { F } = reach(ctx, ['F']);
      const row = (model, tokens, cost, unpriced, day) => {
        const r = [];
        r[F.ts] = '2026-01-0' + day + 'T00:00:00Z';
        r[F.phase] = 'P1'; r[F.task] = 'T1'; r[F.model] = model;
        r[F.author] = 'me'; r[F.agent] = 'ag'; r[F.attr] = 'task';
        r[F.tokens] = tokens; r[F.cost] = cost; r[F.msgs] = 1;
        r[F.unpriced] = unpriced;
        return r;
      };
      const facts = [row('opus', 4000, 2.5, 0, 1)];
      if (withUnpriced) facts.push(row('mystery', 2500, 0, 2500, 2));
      (tailRows || []).forEach((t, i) => facts.push(row(t[0], t[1], t[2], t[3], 3 + (i % 6))));
      const usage = Object.assign({ facts, enabled: true, counts: { phases: 1 },
        showCost: true, taskMeta: { T1: { status: 'pending', risk: 'low' } } },
      extra || {});
      vm.runInContext('USAGE = ' + JSON.stringify(usage) + '; BANDS = null;', ctx);
      vm.runInContext('renderUsage();', ctx);
      const rows = all(root, hasClass('urow')).map(text);
      const tile = all(root, hasClass('utile')).filter((t) => all(t, hasClass('k'))
        .some((k) => text(k) === 'equivalent cost')).map(text);
      return { ctx, root, rows, tile };
    }

    it('words the unpriced tokens exactly as Python unpriced_phrase() does', () => {
      const { ctx } = renderUnpriced(false);
      const { uUnpricedPhrase } = reach(ctx, ['uUnpricedPhrase']);
      const ns = [999, 1500, 2500000, 1234567890];
      const py = pyCall('_usage_economics', ns.map((n) => ['unpriced_phrase', [n]]));
      ns.forEach((n, i) => {
        expect(typeof py[i], String(n)).toBe('string');
        expect(uUnpricedPhrase(n), String(n)).toBe(py[i]);
      });
      // Both sides are silent for nothing to say.
      expect(pyCall('_usage_economics', [['unpriced_phrase', [0]]])[0]).toBe('');
      expect(uUnpricedPhrase(0)).toBe('');
    });

    it('its By model row says unpriced beside its tokens, never a dollar figure', () => {
      const r = renderUnpriced(true);
      const mystery = r.rows.filter((s) => s.startsWith('mystery'));
      expect(mystery.length).toBe(1);
      expect(mystery[0]).toContain('unpriced');
      expect(mystery[0]).not.toMatch(DOLLAR);
      const opus = r.rows.filter((s) => s.startsWith('opus'));
      expect(opus.length).toBe(1);
      expect(opus[0]).toMatch(DOLLAR);
      expect(opus[0]).not.toContain('unpriced');
    });

    // Seven more priced models fill the visible eight; the rest is the tail.
    const headFill = Array.from({ length: 7 }, (_, i) => ['m' + i, 3000, 1, 0]);
    const otherRow = (r) => r.rows.filter((s) => s.startsWith('other ('));

    it("an 'other' row whose every tail value is unpriced reads 'unpriced', never $0.00 "
      + '(more values than SHOWN[dim], none of the tail priced)', () => {
      const r = renderUnpriced(false, {}, headFill.concat([['u1', 100, 0, 100], ['u2', 50, 0, 50]]));
      const other = otherRow(r);
      expect(other.length).toBe(1);
      expect(other[0]).toContain('unpriced');
      expect(other[0]).not.toContain('$0.00');
      expect(other[0]).not.toMatch(DOLLAR);
    });

    it("...and an 'other' row with priced tokens keeps its figure "
      + '[the twin: a tail that always says unpriced fails here]', () => {
      const r = renderUnpriced(false, {}, headFill.concat([['u1', 100, 0, 100], ['p1', 50, 0.5, 0]]));
      const other = otherRow(r);
      expect(other.length).toBe(1);
      expect(other[0]).toMatch(DOLLAR);
      expect(other[0]).not.toContain('unpriced');
    });

    it('the cost tile states how many tokens its figure leaves out', () => {
      const r = renderUnpriced(true);
      expect(r.tile.length).toBe(1);
      expect(r.tile[0]).toContain('2.5K tokens unpriced');
    });

    it('...and says nothing of the kind when every token is priced '
      + '[the twin: a clause that always fires fails here]', () => {
      const r = renderUnpriced(false);
      expect(r.tile.length).toBe(1);
      expect(r.tile[0]).not.toContain('unpriced');
      expect(r.rows.join(' ')).not.toContain('unpriced');
    });

    // The browse dialog, opened the way its button opens it, read back off the
    // dialog node: each row's cost cell, by the row's id cell.
    function browseUnpriced(dim, extra) {
      const { ctx } = renderUnpriced(true, extra);
      vm.runInContext('openBrowse(' + JSON.stringify(dim)
        + ', "Browse", USAGE.facts);', ctx);
      const dlg = vm.runInContext('BROWSE', ctx);
      const heads = all(dlg, (n) => n.tagName === 'TH').map(text);
      const at = heads.findIndex((h) => h.startsWith('cost'));
      const cost = {};
      all(dlg, (n) => n.tagName === 'TR').forEach((tr) => {
        const tds = all(tr, (c) => c.tagName === 'TD');
        if (tds.length > at && at >= 0) cost[text(tds[0])] = text(tds[at]);
      });
      return { cost, lines: (dlg.kids || []).map(text) };
    }

    it('the browse dialog\'s cost column says unpriced for a model no rate '
      + 'covers, and keeps a dollar figure for a priced one', () => {
      const r = browseUnpriced('model');
      expect(r.cost.mystery).toBe('unpriced');
      expect(r.cost.opus).toMatch(DOLLAR);
    });

    it('...and a group with any priced token keeps its figure there '
      + '[the twin: a cell that always says unpriced fails here]', () => {
      const r = browseUnpriced('phase');
      expect(r.cost.P1).toMatch(DOLLAR);
      expect(r.cost.P1).not.toContain('unpriced');
    });

    const CLI = "the CLI's estimate, recorded at meter time";
    const cliCost = [
      { session: 'sx', model: 'mystery', cliCostUSD: 0.4, pluginCostUSD: null,
        pluginUnpriced: true, basis: CLI },
      { session: 'sx', model: 'opus', cliCostUSD: 7.25, pluginCostUSD: 5,
        pluginUnpriced: false, basis: CLI }];
    const cliLines = (lines) => lines.filter((s) => s.includes('CLI $'));

    it('the model browse prints the CLI\'s own figure beside the plugin\'s, '
      + 'labelled, wherever the two differ', () => {
      const r = browseUnpriced('model', { cliCost, rateBasis: 'rates as of X' });
      const lines = cliLines(r.lines).join('\n');
      expect(lines).toContain('session sx · opus: CLI $7.25 (' + CLI
        + ') vs plugin $5.00');
      expect(lines).toContain('session sx · mystery: CLI $0.40 (' + CLI
        + ') vs plugin unpriced');
      expect(lines).toContain('rates as of X');
    });

    it('...and prints none of it with showCost off, or with nothing that '
      + 'differs [the twin: a line that always prints fails here]', () => {
      expect(cliLines(browseUnpriced('model',
        { cliCost, showCost: false }).lines)).toEqual([]);
      expect(cliLines(browseUnpriced('model', { cliCost: [] }).lines)).toEqual([]);
    });

    // The tab itself, not the dialog: the same lines on first paint, once each.
    // Counted rather than found, because the tab and an open dialog are two
    // places the same note could land.
    const tabCli = (extra) => {
      const { root } = renderUnpriced(true, extra);
      return all(root, (n) => n.hasAttribute('data-cli-cost')).map(text);
    };

    it('the Usage tab prints the CLI\'s own figure beside the plugin\'s, '
      + 'labelled, wherever the two differ', () => {
      const notes = tabCli({ cliCost, rateBasis: 'rates as of X' });
      expect(notes.length).toBe(1);
      expect(notes[0]).toContain('session sx · opus: CLI $7.25 (' + CLI
        + ') vs plugin $5.00');
      expect(notes[0]).toContain('session sx · mystery: CLI $0.40 (' + CLI
        + ') vs plugin unpriced');
    });

    it('...and the tab prints none of it with showCost off, or with nothing '
      + 'that differs [the twin: a note that always prints fails here]', () => {
      expect(tabCli({ cliCost, showCost: false })).toEqual([]);
      expect(tabCli({ cliCost: [] })).toEqual([]);
    });
  });
});

// --- the report's range line ------------------------------------------------

describe('the report\'s range line and the tokens no rate covers', () => {
  // The line is written by applyUsageRange() into #audit-urange. A prologue
  // installs the per-day payload and a node for that id ahead of the parts,
  // the way report-prototype-keys.test.mjs replaces the pieces it needs.
  function rangeLine(unpriced, showCost) {
    const payload = { min: '2026-01-01', max: '2026-01-03',
      showCost: showCost !== false, unpricedTokens: unpriced,
      days: { '2026-01-01': [1000, 1.5, 2, []], '2026-01-02': [2000, 2.5, 3, []],
        '2026-01-03': [4000, 4.5, 4, []] } };
    const prologue = 'window.AUDIT_USAGE = ' + JSON.stringify(payload) + ';\n'
      + 'globalThis.__urange = { hidden: true, textContent: "" };\n'
      + '{ const prior = document.getElementById.bind(document);\n'
      + '  document.getElementById = (id) => (id === "audit-urange"'
      + ' ? globalThis.__urange : prior(id)); }\n';
    const { ctx } = loadReport({ mutate: (src) => prologue + src });
    vm.runInContext('dFrom = "2026-01-02"; dTo = "2026-01-03"; '
      + 'lastRange = "|"; applyUsageRange();', ctx);
    return vm.runInContext('globalThis.__urange', ctx);
  }

  it('says how many tokens its cost leaves out, worded as Python\'s '
    + 'unpriced_phrase() words them', () => {
    const phrase = pyCall('_usage_economics', [['unpriced_phrase', [2500000]]])[0];
    const n = rangeLine(2500000);
    expect(n.hidden).toBe(false);
    expect(n.textContent).toContain('$7.00');
    expect(n.textContent).toContain(phrase);
  });

  it('...and says nothing of it for none, for a count never taken (null), or '
    + 'with showCost off [the twin: a clause that always fires fails here]', () => {
    for (const [u, show] of [[0, true], [null, true], [2500000, false]]) {
      const n = rangeLine(u, show);
      expect(n.hidden, String(u)).toBe(false);
      expect(n.textContent, String(u)).not.toContain('unpriced');
    }
  });
});
