/**
 * The panel's tab stages: Overview, the help drawer, the capability policy, and
 * Appearance.
 *
 * WHY THESE FOUR TOGETHER. They were chosen by measurement, not by theme. Every
 * top-level declaration left in capture-screenshots.mjs was scanned for references
 * to the run's module state, and these four share exactly one footprint — `note`,
 * `fail`, `tabTo`, and (Appearance only) `shot`, plus `awaitConfirmDialog` for the
 * policy stage. Nothing else in the file has so small a surface for so many lines:
 * 1023 of them, a quarter of what the orchestrator was carrying.
 *
 * THE DEPENDENCIES ARE A PARAMETER NOW, and that is the whole point of the move. In
 * one file they were free variables closed over from module scope, which is why a
 * reader could not tell what a stage touched without reading all of it, and why the
 * file could not be split without answering that question for every stage at once.
 * Each stage takes them explicitly; the orchestrator builds the object once.
 *
 * `fail` and `note` are the collector pair the whole capture reports through - the
 * same shape the liveness and ladder helpers already took as `{ report, ok }`. They
 * are not renamed here: the bodies call them by these names in a few hundred places,
 * and a rename would be a diff nobody could review against a behaviour claim.
 */

// The stages themselves follow, cut across from capture-screenshots.mjs unchanged
// apart from their signatures. Their doc comments came with them, which is most of
// what makes this file long: the reasoning is the part worth keeping next to the
// assertion it justifies.


/**
 * Overview is a filter, not a poster — so drive it.
 *
 * A panel selftest can only assert that a string is present in the document; it
 * cannot tell a working view from a dead one, and the panel has already shipped an
 * inline script with a missing paren while 209/209 string pins passed. Everything
 * below is asserted against an INDEPENDENT count taken from `STATE` in the page —
 * the manifest the server sent — rather than against the rendering path's own idea
 * of what it drew, so a filter that quietly matches everything fails here.
 *
 * The strip/pill count is deliberately not asserted to DROP: on a plan whose tasks
 * all share one status the correct filtered set is every phase, and calling that
 * "inert" is exactly the false accusation check-report-interactive.mjs made once
 * (see F3). The oracle is the expected set, computed here; equality holds either way.
 */
// --- the Overview tab ----------------------------------------------------------

export async function assertOverviewWorks(page, { note, fail, tabTo }) {
  const facts = await page.evaluate(() => {
    const rollup = STATE.rollup || {};
    const tasks = (STATE.composition || {}).tasks || [];
    const byStatus = {};
    for (const t of tasks) {
      (byStatus[t.status] = byStatus[t.status] || new Set()).add(t.phaseId);
    }
    return {
      phases: (rollup.phases || []).length,
      statuses: Object.fromEntries(
        Object.entries(byStatus).map(([s, set]) => [s, set.size])),
      areas: Object.keys(rollup.areas || {}).length,
      untagged: (rollup.phases || []).filter((p) => !(p.area || []).length).length,
      ready: (rollup.ready || []).length,
      outcomes: (rollup.phases || []).filter((p) => p.desiredOutcome).length,
      firstPhase: (rollup.phases || [])[0] ? (rollup.phases || [])[0].id : null,
      // Two search terms, derived rather than written down: one word that only an
      // OUTCOME carries, and one that only the fields a row DRAWS carry. The row
      // owes the reader a visible basis for the first and must spend no second
      // line on the second, and a term hard-coded here would be testing the demo
      // manifest's prose instead of the rule.
      ...(() => {
        const ph = rollup.phases || [];
        const words = (v) => String(v || '').toLowerCase().match(/[a-z]{4,}/g) || [];
        const drawn = ph.map((p) => (p.id + ' ' + (p.title || '') + ' '
          + (p.area || []).join(' ')).toLowerCase()).join(' ');
        const outcomes = ph.map((p) => String(p.desiredOutcome || '').toLowerCase())
          .join(' ');
        const uniq = (xs) => [...new Set(xs)];
        return {
          outcomeOnly: uniq(ph.flatMap((p) => words(p.desiredOutcome)))
            .find((w) => !drawn.includes(w)) || null,
          drawnOnly: uniq(ph.flatMap((p) => words(p.id + ' ' + (p.title || '') + ' '
            + (p.area || []).join(' ')))).find((w) => !outcomes.includes(w)) || null,
        };
      })(),
    };
  });
  // ov (F-P-5): Overview follows the report's table, so it opens on a VIEW —
  // active & pending — and the archived phases are off screen by design. Every
  // count below is therefore taken against the view the tab is actually in,
  // computed the same way the client computes it. Switch to `all` first, so the
  // filter/search assertions keep measuring filters rather than the view.
  await page.evaluate(() => { OVF.view = 'all'; renderOver(); });
  await page.waitForTimeout(200);
  const rows = () => page.locator('#over .ovrow:visible').count();

  const pills = await page.locator('#over .ovpill').count();
  if (!pills) { fail('overview: no summary pills — the rollup strips did not render'); return; }
  if (await rows() !== facts.phases) {
    fail(`overview: ${await rows()} phase rows for ${facts.phases} phases in the rollup`);
  }
  // ov (P2/4): the outcome used to be a second line on EVERY row — prose that is
  // near-identical from row to row, so it doubled every row's height and separated
  // none of them. It is on the row's tooltip and at the head of the opened detail
  // now, and a row spends a line on it in exactly one case: the search matched
  // there and nowhere the row draws. That case is the one no substring pin can
  // check, because the claim is that the words the reader typed are ON SCREEN.
  if (facts.outcomes) {
    const spent = await page.locator('#over .ovout').count();
    const tip = await page.evaluate(() => {
      const of = (r) => (STATE.rollup.phases || []).find(
        (p) => p.id === r.getAttribute('data-phase'));
      const rows = [...document.querySelectorAll('#over .ovrow')]
        .filter((r) => (of(r) || {}).desiredOutcome);
      return {
        rows: rows.length,
        carried: rows.filter((r) => (r.getAttribute('title') || '')
          .includes(of(r).desiredOutcome)).length,
      };
    });
    if (spent) {
      fail(`overview: ${spent} rows spend a second line on their outcome with no `
         + `search on — that is the doubled row height this removed`);
    } else if (!tip.rows || tip.carried !== tip.rows) {
      fail(`overview: ${tip.carried} of ${tip.rows} rows with an outcome carry it `
         + `on the tooltip, so hovering answers nothing`);
    } else {
      note(`overview: ${tip.rows} rows carry their outcome on hover and none spends `
         + `a line on it`);
    }
    // Matched THERE and nowhere visible: the row must show the outcome, and the
    // term must be inside what it shows — the line is clipped to one line, so the
    // head of a long outcome is no proof the match is on screen.
    if (facts.outcomeOnly) {
      await page.fill('#ovq', facts.outcomeOnly);
      await page.waitForTimeout(250);
      const basis = await page.evaluate((t) => {
        const lines = [...document.querySelectorAll('#over .ovrow')]
          .map((r) => r.querySelector('[data-ovhit="outcome"]'))
          .map((n) => (n ? n.textContent : null));
        return {
          rows: lines.length,
          shown: lines.filter((s) => s !== null).length,
          carrying: lines.filter((s) => s && s.toLowerCase().includes(t)).length,
        };
      }, facts.outcomeOnly);
      if (!basis.rows) {
        fail(`overview: "${facts.outcomeOnly}" is a word only an outcome carries and `
           + `searching it matched no row — the search no longer reaches the field`);
      } else if (basis.shown !== basis.rows || basis.carrying !== basis.rows) {
        fail(`overview: ${basis.rows} rows matched on their outcome alone, `
           + `${basis.shown} show it and ${basis.carrying} show the matching words `
           + `— the rest are in the list with no basis on them`);
      } else {
        note(`overview: ${basis.rows} rows matched on "${facts.outcomeOnly}" and each `
           + `shows the matching words`);
      }
      await page.fill('#ovq', '');
      await page.waitForTimeout(200);
    } else {
      note('overview: no word occurs in an outcome and nowhere a row draws, so the '
         + 'match-basis line could not be exercised on this manifest');
    }
    // ...and the other direction, which is the whole point of the change: a match
    // the row already explains costs nothing.
    if (facts.drawnOnly) {
      await page.fill('#ovq', facts.drawnOnly);
      await page.waitForTimeout(250);
      const extra = await page.locator('#over .ovout').count();
      const got = await rows();
      if (!got) {
        fail(`overview: "${facts.drawnOnly}" is a word the rows themselves carry and `
           + `searching it matched nothing`);
      } else if (extra) {
        fail(`overview: ${extra} of ${got} rows explain a match the row already `
           + `shows — the second line is back, for nothing`);
      } else {
        note(`overview: a match on a field the row draws costs no second line `
           + `(${got} rows)`);
      }
      await page.fill('#ovq', '');
      await page.waitForTimeout(200);
    }
  }

  // A task-status pill scopes the phase list to the phases carrying that status.
  const [status, expected] = Object.entries(facts.statuses)[0] || [];
  if (status) {
    const pill = page.locator(`#over .ovpill[data-status="${status}"]`).first();
    await pill.click();
    await page.waitForTimeout(150);
    const got = await rows();
    const pressed = await pill.getAttribute('aria-pressed');
    if (got !== expected) {
      fail(`overview: filtering to "${status}" shows ${got} phase rows, but ${expected} `
         + `phases carry a ${status} task`);
    } else if (pressed !== 'true') {
      fail(`overview: the "${status}" pill filters but never says it is on `
         + `(aria-pressed=${pressed})`);
    } else {
      note(`overview: "${status}" pill -> ${got}/${facts.phases} phases, aria-pressed set`);
    }
    if (!(await page.locator('#over [data-ovclear]').count())) {
      fail('overview: a filter is on and there is no way back — no Clear filters button');
    }
    await page.locator('#over [data-ovclear]').first().click();
    await page.waitForTimeout(150);
    if (await rows() !== facts.phases) fail('overview: Clear filters did not restore every phase');
  }

  // Search reaches the phase's own fields — id, title, area tags and the
  // desiredOutcome. The expected set is computed from STATE by the same substring
  // rule rather than assumed to be one row: "P1" is a prefix of P10..P19, and an
  // assertion of 1 would be testing the fixture's id scheme, not the search.
  if (facts.firstPhase) {
    for (const term of [facts.firstPhase, 'zzq-matches-nothing']) {
      const want = await page.evaluate((t) => (STATE.rollup.phases || []).filter((p) =>
        (p.id + ' ' + (p.title || '') + ' ' + (p.area || []).join(' ') + ' '
         + (p.desiredOutcome || '')).toLowerCase().includes(t.toLowerCase())).length, term);
      await page.fill('#ovq', term);
      await page.waitForTimeout(250);
      const got = await rows();
      if (got !== want) fail(`overview: searching "${term}" shows ${got} phases, ${want} match`);
      else if (!want && !(await page.locator('#over .ovempty').count())) {
        fail('overview: a search that matches nothing shows an empty list and no empty state');
      }
    }
    note('overview: search filters phases and says so when nothing matches');
    await page.fill('#ovq', '');
    await page.waitForTimeout(250);
  }

  // Group by area, from the rollup's own registry.
  if (facts.areas) {
    await page.check('#ovarea');
    await page.waitForTimeout(200);
    const groups = await page.locator('#over .ovgrp').count();
    const want = facts.areas + (facts.untagged ? 1 : 0);
    if (groups !== want) fail(`overview: grouping by area drew ${groups} groups, expected ${want}`);
    else note(`overview: grouped into ${groups} area groups`);
    await page.uncheck('#ovarea');
    await page.waitForTimeout(200);
  }

  // Ready-now is the card you act from: it must carry a real, copyable command.
  if (facts.ready) {
    const cmd = await page.locator('#over .rdy .rcmd').first().textContent();
    if (!/^\/audit:run \S+/.test(cmd || '')) {
      fail(`overview: ${facts.ready} tasks are ready and the card shows "${cmd}"`);
    } else {
      note(`overview: ready-now offers ${cmd}`);
    }
  }

  // ov (F-P-5): a phase row OPENS IN PLACE. It used to leave for Composition —
  // a tab that edits tasks, models and skills — so "show me this phase" landed
  // the reader in a form with their filters behind them. Composition is still
  // reachable, by a named press inside the detail.
  if (facts.firstPhase) {
    const firstId = await page.evaluate(() =>
      (document.querySelector('#over .ovrow') || {}).getAttribute
        ? document.querySelector('#over .ovrow').getAttribute('data-phase') : null);
    await page.locator('#over .ovrow').first().click();
    await page.waitForTimeout(250);
    const inPlace = await page.evaluate((pid) => {
      const row = document.querySelector(`#over .ovrow[data-phase="${pid}"]`);
      const det = document.querySelector(`#over [data-ovdetail="${pid}"]`);
      const tasks = ((STATE.composition || {}).tasks || [])
        .filter((t) => t.phaseId === pid).length;
      return {
        stayed: !document.getElementById('over').classList.contains('hidden'),
        expanded: row ? row.getAttribute('aria-expanded') : null,
        detail: !!det,
        rows: det ? det.querySelectorAll('[data-ovtask]').length : -1,
        want: tasks,
        cols: det ? [...det.querySelectorAll('th')].map((h) => h.textContent) : [],
        edit: !!(det && det.querySelector('[data-ovedit]')),
        // The outcome's real home now that no row carries it: in full (the row's
        // line is a window), and ABOVE the table rather than a footnote to it.
        wantPurpose: !!((STATE.rollup.phases || []).find((p) => p.id === pid) || {})
          .desiredOutcome,
        purpose: det && det.querySelector('[data-ovpurpose]')
          ? det.querySelector('[data-ovpurpose]').textContent : null,
        purposeLeads: !!(det && det.firstElementChild
          && det.firstElementChild.hasAttribute('data-ovpurpose')),
      };
    }, firstId);
    if (!inPlace.stayed || inPlace.expanded !== 'true' || !inPlace.detail) {
      fail(`overview: clicking a phase row did not open it in place `
         + `(${JSON.stringify(inPlace)})`);
    } else if (inPlace.rows !== inPlace.want) {
      fail(`overview: the detail lists ${inPlace.rows} tasks for a phase with `
         + `${inPlace.want}`);
    } else if (inPlace.cols.join(',') !== 'id,title,status,risk,commit,done (UTC)') {
      fail(`overview: the detail's columns are ${JSON.stringify(inPlace.cols)} — `
         + `it is meant to follow the report's table`);
    } else if (!inPlace.edit) {
      fail('overview: the detail offers no way to Composition — the click used to '
         + 'go there, so removing it without a named replacement strands the reader');
    } else if (inPlace.wantPurpose && !inPlace.purposeLeads) {
      fail(`overview: the phase has a desiredOutcome and the opened detail does not `
         + `lead with it (${JSON.stringify(inPlace.purpose)}) — no row carries it `
         + `any more, so this is where it is read`);
    } else {
      note(`overview: a phase opens in place with its ${inPlace.rows} tasks in the `
         + `report's columns, and Composition is a named press`);
    }
    // ...and that named press still does what the click used to.
    await page.locator(`#over [data-ovedit="${firstId}"]`).click();
    await page.waitForTimeout(300);
    const landed = await page.evaluate((pid) => {
      const visible = [...document.querySelectorAll('#comp tr.phase')]
        .filter((r) => r.offsetParent !== null);
      // The row whose id cell IS this phase — startsWith would also collect
      // P10..P19 when the target is P1, and then nothing here is being measured.
      const mine = visible.filter((r) => {
        const cell = r.querySelector('.mono');
        return cell && cell.textContent === pid;
      });
      return {
        hash: location.hash,
        hidden: document.getElementById('comp').classList.contains('hidden'),
        q: (document.querySelector('#comp input[type=search]') || {}).value,
        rows: visible.length,
        total: document.querySelectorAll('#comp tr.phase').length,
        // Filtered to it AND opened on it: landing on a collapsed row in a scrolled
        // table is not "pre-filtered", it is the same table with fewer rows.
        open: mine.length === 1 && mine[0].classList.contains('open'),
      };
    }, facts.firstPhase);
    if (landed.hidden || landed.hash !== '#/comp') {
      fail(`overview: "Edit in Composition" did not open Composition (hash ${landed.hash})`);
    } else if (landed.q !== facts.firstPhase || landed.rows >= landed.total || !landed.open) {
      fail(`overview: Composition did not open on ${facts.firstPhase} — search is `
         + `"${landed.q}", ${landed.rows}/${landed.total} phase rows visible, `
         + `target row expanded: ${landed.open}`);
    } else {
      note(`overview: "Edit in Composition" opens it filtered to ${facts.firstPhase} `
         + `(${landed.rows}/${landed.total} rows)`);
    }
    await page.fill('#comp input[type=search]', '');
    await tabTo(page, 'over');
    await page.waitForTimeout(200);
    await page.evaluate((pid) => { OVF.open[pid] = false; renderOver(); }, firstId);
    await page.waitForTimeout(150);
  }

  // The view itself: the default hides the archive, and a match it hides is
  // announced rather than silently dropped — the report's rule, same words.
  {
    const v = await page.evaluate(() => {
      OVF.view = 'active'; OVF.q = ''; renderOver();
      const seg = (st) => (st === 'done' || st === 'cancelled') ? 'archived'
        : (st === 'in_progress' || st === 'blocked') ? 'active' : 'pending';
      const all = STATE.rollup.phases || [];
      return {
        want: all.filter((p) => seg(p.status) !== 'archived').length,
        archived: all.filter((p) => seg(p.status) === 'archived').length,
        sel: !!document.querySelector('#over [data-ovview]'),
      };
    });
    await page.waitForTimeout(200);
    const shown = await rows();
    if (!v.sel) {
      fail('overview: no view select — the tab it must follow has one');
    } else if (shown !== v.want) {
      fail(`overview: the Active view shows ${shown} phases, expected ${v.want} `
         + `(${v.archived} archived)`);
    } else {
      note(`overview: the Active view shows ${shown} of ${v.want + v.archived} phases`);
    }
    if (v.archived) {
      // Search for an archived phase from the Active view: it must say so.
      const aid = await page.evaluate(() => {
        const seg = (st) => (st === 'done' || st === 'cancelled') ? 'archived' : '';
        const p = (STATE.rollup.phases || []).find((x) => seg(x.status) === 'archived');
        return p ? p.id : null;
      });
      await page.fill('#ovq', aid);
      await page.waitForTimeout(300);
      const note1 = await page.evaluate(() => {
        const n = document.querySelector('#over [data-ovoutside]');
        return n ? n.textContent : null;
      });
      if (!note1 || !/outside this view/.test(note1)) {
        fail(`overview: searching for the archived phase ${aid} from the Active `
           + `view reports nothing about it (${JSON.stringify(note1)})`);
      } else {
        await page.locator('#over [data-ovviewall]').click();
        await page.waitForTimeout(250);
        const found = await rows();
        if (!found) fail('overview: "Show all phases" did not reveal the match');
        else note(`overview: a match outside the view is announced, and one press shows it`);
      }
      await page.fill('#ovq', '');
      await page.waitForTimeout(200);
    }
    await page.evaluate(() => { OVF.view = 'all'; renderOver(); });
    await page.waitForTimeout(150);
  }
}

// --- the help drawer -----------------------------------------------------------


/* ---- the help drawer -------------------------------------------------------
 *
 * Every oracle here is `GET /api/help` — the payload itself, fetched inside the
 * page — and never the drawer's own output. That is the only way this proves
 * anything: the whole claim of the feature is that what you read came out of the
 * shipped schemas and out of the code that runs the rule, so a check that compared
 * the drawer with the drawer would be green for a page that invented every word.
 */
export async function assertHelpDrawerWorks(page, declared, { note, fail, tabTo }) {
  const doc = await page.evaluate(() => api('GET', '/api/help'));

  // --- no ⓘ opens on an empty page -------------------------------------------
  // Through the real endpoint, path by path, the way the drawer asks. `_help`
  // asserts the same coverage against its own table; this asserts the HTTP route
  // that stands between that table and the reader.
  const unresolved = await page.evaluate(async (paths) => {
    const out = [];
    for (const p of paths) {
      const r = await api('GET', `/api/help?doc=config&path=${encodeURIComponent(p)}`);
      if (!r.found || !(r.entry || {}).description) out.push(p);
    }
    return out;
  }, declared);
  if (unresolved.length) {
    fail(`help: ${unresolved.length} setting(s) the form binds a ⓘ to resolve to no `
       + `description — the drawer opens on an empty page for: `
       + `${unresolved.slice(0, 5).join(', ')}`);
  } else {
    note(`help: all ${declared.length} bound settings resolve to schema words`);
  }

  // --- and no ⓘ promises a tooltip it does not have ---------------------------
  // The bubble's content IS the attribute, so an empty one is an empty box under
  // the cursor. Two fields reached that state the moment a ⓘ stopped needing
  // tooltip text in order to exist.
  const blankTips = await page.evaluate(() =>
    [...document.querySelectorAll('.hint')]
      .filter((h) => h.hasAttribute('data-tip') && !h.getAttribute('data-tip').trim())
      .map((h) => h.dataset.hint || '(no ref)'));
  if (blankTips.length) {
    fail(`help: ${blankTips.length} hint(s) carry an empty data-tip and draw an `
       + `empty bubble on hover: ${blankTips.slice(0, 4).join(', ')}`);
  } else {
    note('help: no hint draws an empty tooltip');
  }

  // --- one field, opened the way a reader opens it ----------------------------
  // Whichever tab the run left behind, this one is about Settings. Selected
  // rather than assumed: `#guards` is merely hidden on the other four, and a
  // click on a hidden button is a 30-second Playwright timeout whose stack reads
  // exactly like a dead panel (F7's lesson, in this harness).
  await tabTo(page, 'guards');
  await page.waitForTimeout(200);
  // trivialLineThreshold as the worked example since v0.34 B1: `enforce` lost
  // its dedicated control (the planGate select owns the gate's tier now), and
  // this field keeps every assertion meaningful — a schema sentence, a real
  // default (80; planGate's is null), microcopy, and the same gate-tiers topic.
  const opener = page.locator('#guards [data-hint="trivialLineThreshold"]').first();
  if (!(await opener.count()) || !(await opener.isVisible())) {
    fail('help: the "trivialLineThreshold" setting has no ⓘ that can be pressed '
       + '— every Settings control is supposed to carry one');
    return;
  }
  await opener.click();
  await page.waitForSelector('dialog.drawer[open]', { timeout: 10000 });
  await page.waitForTimeout(150);
  const field = await page.evaluate(() => {
    const d = document.querySelector('dialog.drawer');
    const sec = [...d.querySelectorAll('.dsec')].map((s) => ({
      h: (s.querySelector('h3') || {}).textContent || '',
      t: s.textContent || '',
    }));
    const facts = [...d.querySelectorAll('.dfacts dt')].map((dt, i) => [
      dt.textContent, d.querySelectorAll('.dfacts dd')[i].textContent]);
    return {
      path: (d.querySelector('[data-hpath]') || {}).textContent,
      means: (sec.find((s) => s.h === 'What it means') || {}).t || '',
      panel: (sec.find((s) => s.h === 'In this panel') || {}).t || '',
      facts,
      topic: (d.querySelector('[data-htopic]') || {}).dataset?.htopic || null,
      sources: [...d.querySelectorAll('.dsrc span')].map((s) => s.textContent),
    };
  });
  const want = doc.fields.config.trivialLineThreshold;
  if (field.path !== 'trivialLineThreshold'
      || !field.means.includes(want.description)) {
    fail(`help: the drawer for "trivialLineThreshold" does not carry the `
       + `schema's own sentence (path=${JSON.stringify(field.path)}, shown=`
       + `${JSON.stringify(field.means.slice(0, 80))})`);
  } else {
    note('help: the trivialLineThreshold drawer quotes the schema verbatim');
  }
  // The default is the value the HOOKS fall back to. A drawer that showed a
  // different one would be worse than one that showed none, because "leave it
  // empty and you get this" is the whole reason it is there.
  const dflt = field.facts.find(([k]) => k === 'Default');
  if (!dflt || dflt[1] !== String(want.default)) {
    fail(`help: the drawer says the default of trivialLineThreshold is `
       + `${JSON.stringify(dflt)}, the payload says ${JSON.stringify(want.default)}`);
  } else if (!field.sources.some((s) => s === doc.schemas.config)) {
    fail(`help: the description is not attributed to ${doc.schemas.config} — a `
       + `quotation with no source is just prose`);
  } else {
    note(`help: type/default/citation shown (default ${dflt[1]}, `
       + `from ${doc.schemas.config})`);
  }
  // The panel's own microcopy is the OTHER voice, and it is labelled as such
  // rather than run together with the schema's sentence.
  const microcopy = await page.evaluate(() => HELP.trivialLineThreshold);
  if (!field.panel.includes(microcopy)) {
    fail('help: the drawer drops the panel\'s own note for trivialLineThreshold, '
       + 'which is the half that says what this form does about the setting');
  }

  // --- the concept page behind the field --------------------------------------
  if (field.topic !== want.topic) {
    fail(`help: the trivialLineThreshold drawer offers topic `
       + `${JSON.stringify(field.topic)}, the payload links it to `
       + `${JSON.stringify(want.topic)}`);
  } else {
    await page.click(`dialog.drawer [data-htopic="${want.topic}"]`);
    await page.waitForSelector(`dialog.drawer [data-htable="${want.topic}"]`,
      { timeout: 10000 });
    const shown = await page.evaluate(() => {
      const t = document.querySelector('dialog.drawer table.dtbl');
      return [...t.querySelectorAll('tbody tr')].map((r) =>
        [...r.querySelectorAll('td')].map((td) => td.textContent));
    });
    const oracle = doc.topics.find((t) => t.id === want.topic).table.rows;
    // The tier column, cell for cell. These are plan_gate_mode's own answers to
    // the hook's own three questions — a page that typed them out would read
    // identically and be a claim about nothing.
    const same = shown.length === oracle.length
      && shown.every((r, i) => r.join('|') === oracle[i].join('|'));
    if (!same) {
      fail(`help: the ${want.topic} page draws ${shown.length} rows that do not `
         + `match the ${oracle.length} the payload computed: `
         + `${JSON.stringify(shown.slice(0, 2))}`);
    } else {
      note(`help: the ${want.topic} page is the payload's own ${oracle.length} rows`);
    }
    // Back returns to the field, not to the index: a reader who drilled in to
    // check how the gate grades is still asking about the field they left.
    await page.click('dialog.drawer [data-hback]');
    await page.waitForTimeout(200);
    const back = await page.evaluate(() =>
      (document.querySelector('dialog.drawer [data-hpath]') || {}).textContent);
    if (back !== 'trivialLineThreshold') {
      fail(`help: going back from the topic landed on ${JSON.stringify(back)} `
         + `rather than the field it was opened from`);
    } else {
      note('help: back returns to the field the topic was reached from');
    }
  }

  // --- the paid half, described and not spent ---------------------------------
  const agent = await page.evaluate(() => {
    const a = document.querySelector('dialog.drawer [data-hagent]');
    // The BADGE, not the card's whole text. The agent's own description happens
    // to name its three tools in prose, so a card whose badge advertised an edit
    // tool still contained the string "Grep" and the first version of this check
    // passed against exactly that mutation.
    return a ? { name: a.dataset.hagent, text: a.textContent,
                 tools: (a.querySelector('.dtools .badge') || {}).textContent || '',
                 buttons: a.querySelectorAll('button').length } : null;
  });
  if (!doc.agent) {
    if (agent) fail('help: a guide card is drawn although the payload ships none');
  } else if (!agent || agent.name !== doc.agent.name) {
    fail(`help: the drawer does not name the ${doc.agent.name} agent`);
  } else if (!doc.agent.tools.every((t) => agent.tools.includes(t))
             || agent.tools.split('·').length !== doc.agent.tools.length) {
    fail(`help: the guide card does not name the tools the agent actually holds `
       + `(${doc.agent.tools.join(', ')}) — a card that advertises more is the one `
       + `thing reading it off the file was meant to prevent`);
  } else if (agent.buttons) {
    fail(`help: the guide card carries ${agent.buttons} button(s). It documents an `
       + `agent you invoke yourself; a control here would spend a model on a `
       + `question this drawer just answered`);
  } else if (agent.text.includes("''")) {
    fail('help: the guide card prints a YAML escape (the plugin\'\'s own README) — '
       + 'the frontmatter quote was stripped without being unescaped');
  } else {
    note(`help: the guide card names ${doc.agent.tools.join('/')}, model `
       + `${doc.agent.model}, and offers no way to spend one`);
  }

  // --- Esc, and where the focus lands -----------------------------------------
  // `box` is the other half, and it is the half no viewport-sized screenshot can
  // show: a shut dialog must occupy NOTHING. The UA hides one with
  // `dialog:not([open]){display:none}`, and an author `display` of equal
  // specificity beats it — which left a 100dvh block laid out at the end of
  // <body> once the drawer had been opened, and printed it across the bottom of
  // the full-page Overview shot. Asserted as the element's own rendered size
  // rather than as a page height, because by now this page has opened and closed
  // the drawer several times and a "before" measurement is already polluted.
  await page.keyboard.press('Escape');
  await page.waitForTimeout(200);
  const closed = await page.evaluate(() => {
    const d = document.querySelector('dialog.drawer'),
      r = d.getBoundingClientRect();
    return { open: !!document.querySelector('dialog.drawer[open]'),
             box: Math.round(r.width) + 'x' + Math.round(r.height),
             display: getComputedStyle(d).display,
             focus: (document.activeElement && document.activeElement.dataset
               ? document.activeElement.dataset.hint : null) || null };
  });
  if (closed.box !== '0x0' || closed.display !== 'none') {
    fail(`help: a closed drawer still renders (${closed.box}, display:`
       + `${closed.display}) — it is laid out at the end of the document, which `
       + `nothing but a full-page capture would ever show`);
  } else {
    note('help: a closed drawer occupies nothing');
  }
  if (closed.open || closed.focus !== 'trivialLineThreshold') {
    fail(`help: after Esc the drawer is open=${closed.open} and focus is on `
       + `${JSON.stringify(closed.focus)} — a keyboard reader who asked what a `
       + `field means has to find their way back to it`);
  } else {
    note('help: Esc closes and hands focus back to the ⓘ that opened it');
  }

  // --- a path into a DOCUMENT, resolved by the server --------------------------
  // `usage.pricing.<model>.in` is the case the browser must not try to work out
  // for itself. Driven through the real drawer rather than the endpoint alone, so
  // what is proven is the path a reader takes.
  await page.evaluate(() =>
    openHelp({ path: 'usage.pricing.claude-opus-4-1.in', doc: 'config',
               label: 'input rate' }));
  await page.waitForSelector('dialog.drawer[open] [data-hpath]', { timeout: 10000 });
  await page.waitForTimeout(150);
  const concrete = await page.evaluate(() => {
    const d = document.querySelector('dialog.drawer');
    return { path: (d.querySelector('[data-hpath]') || {}).textContent,
             srcs: [...d.querySelectorAll('.dsrc span')].map((s) => s.textContent),
             means: d.textContent };
  });
  const shape = doc.fields.config['usage.pricing.<name>.in'];
  if (concrete.path !== 'usage.pricing.claude-opus-4-1.in'
      || !concrete.srcs.some((s) => s === 'documented as usage.pricing.<name>.in')
      || !concrete.means.includes(shape.description)) {
    fail('help: a concrete pricing path did not resolve onto the shape that '
       + `documents it: ${JSON.stringify(concrete.srcs)}`);
  } else {
    note('help: usage.pricing.<model>.in resolves server-side onto its shape');
  }
  await page.keyboard.press('Escape');
  await page.waitForTimeout(150);

  // --- the index lists every page the payload ships ---------------------------
  await page.click('#helpbtn');
  await page.waitForSelector('dialog.drawer[open] [data-htopic]', { timeout: 10000 });
  const index = await page.evaluate(() =>
    [...document.querySelectorAll('dialog.drawer [data-htopic]')]
      .map((b) => [b.dataset.htopic, (b.querySelector('b') || {}).textContent]));
  const wantTopics = doc.topics.map((t) => [t.id, t.title]);
  if (JSON.stringify(index) !== JSON.stringify(wantTopics)) {
    fail(`help: the index lists ${JSON.stringify(index.map((x) => x[0]))} but the `
       + `payload ships ${JSON.stringify(wantTopics.map((x) => x[0]))}`);
  } else {
    note(`help: the index is the payload's own ${index.length} concept pages`);
  }
  await page.keyboard.press('Escape');
  await page.waitForTimeout(150);

  // --- a composition lever is documented by the MANIFEST schema ---------------
  await tabTo(page, 'comp');
  await page.waitForSelector('#comp table', { timeout: 15000 });
  await page.click('#comp [data-hint="taskModel"]');
  await page.waitForSelector('dialog.drawer[open] [data-hpath]', { timeout: 10000 });
  const lever = await page.evaluate(() => {
    const d = document.querySelector('dialog.drawer');
    return { path: (d.querySelector('[data-hpath]') || {}).textContent,
             text: d.textContent };
  });
  const leverPath = doc.composition.taskModel;
  if (lever.path !== leverPath
      || !lever.text.includes(doc.fields.manifest[leverPath].description)) {
    fail(`help: the task model lever opened on ${JSON.stringify(lever.path)} rather `
       + `than ${leverPath}, or without the manifest schema's words`);
  } else {
    note(`help: the task model lever is explained from ${leverPath}`);
  }
  await page.keyboard.press('Escape');
  await page.waitForTimeout(150);
  await tabTo(page, 'guards');
  await page.waitForTimeout(200);
}

/* ---- fixture homes: no panel here ever sees the capturing machine ------------
 *
 * EVERY panel this file photographs is handed a HOME of its own. The reason is what
 * discovery is: `_panel_discovery.discover` walks `<project>/.claude`, `~/.claude`
 * and `~/.claude/plugins` and returns every skill, subagent and MCP server the
 * project can reach — which, run against a real machine, is a list of whatever the
 * person capturing happens to have installed. That is two problems at once. The
 * committed PNG would publish somebody's plugin inventory (the same class of leak
 * as the identity that reached four shots before it was caught, and just as
 * permanent); and the CHECKS would be asserting against a set that is different on
 * every machine and empty on a CI runner, where ~/.claude does not exist.
 *
 * It began as the policy tab's problem, because that tab lists the inventory a row
 * at a time. It never was only that tab's. Composition's "Available building blocks
 * (discovered)" table is the same list under a different heading, and `panel-blocks`
 * committed it: `skills (101)` in the file at 08d9879, `skills (110)` on the machine
 * that found this — a hundred-odd rows of one developer's installed skills, names
 * and descriptions, in a public repository. The composition table quotes discovery
 * again in a smaller way, through `skillHints()`: a manifest-spelled skill that
 * discovery does not know draws a note beside it, so which notes appear was a
 * function of what the capturer had installed.
 *
 * So both panels get a home, both are asserted against their own declaration before
 * a shutter opens (`assertFixtureDiscovery`), and the two declarations are written
 * out below. `--check` gets the same guard, so a home that stops taking is caught on
 * the runner rather than at the next capture.
 */

// --- the capability policy -----------------------------------------------------



export async function assertPolicyWorks(page, statePath,
                                        { note, fail, tabTo,
                                          awaitConfirmDialog }) {
  await tabTo(page, 'policy');
  await page.waitForSelector('#policy .card', { timeout: 15000 });
  await page.waitForTimeout(250);

  // --- a row per discovered capability, with the server's verdict on it -------
  const table = await page.evaluate(() => ({
    kind: PF.kind,
    oracle: (POLICY.resolved[PF.kind] || []).map((r) => ({
      name: r.name, verdict: r.verdict, basis: r.basis, required: r.required })),
    rendered: [...document.querySelectorAll('#policy tr[data-pcap]')].map((tr) => ({
      name: tr.dataset.pcap,
      verdict: tr.dataset.verdict,
      word: (tr.querySelector('.pv') || {}).textContent || '',
      basis: (tr.querySelector('.pbasis') || {}).textContent || '',
      locked: !!(tr.querySelector('select.prule') || {}).disabled,
      required: !!tr.querySelector('.badge.req'),
    })),
    kindCounts: [...document.querySelectorAll('#policy [data-pk]')].map((b) =>
      [b.dataset.pk, Number((b.querySelector('b') || {}).textContent || -1),
       (POLICY.resolved[b.dataset.pk] || []).length]),
  }));
  if (table.rendered.length !== table.oracle.length) {
    fail(`policy: ${table.oracle.length} ${table.kind} resolved by the server, `
       + `${table.rendered.length} rows rendered`);
  } else {
    const byName = Object.fromEntries(table.rendered.map((r) => [r.name, r]));
    const wrong = table.oracle.filter((o) => {
      const r = byName[o.name];
      return !r || r.verdict !== o.verdict
        || r.word.trim() !== (o.verdict === 'violation' ? 'Violation' : 'Allowed')
        || r.basis.trim() !== (o.basis || '').trim();
    });
    const violations = table.oracle.filter((o) => o.verdict === 'violation').length;
    if (wrong.length) {
      fail(`policy: ${wrong.length} row(s) do not show the verdict or the basis the `
         + `server computed — first: ${JSON.stringify(wrong[0])}`);
    } else if (!violations || violations === table.oracle.length) {
      fail(`policy: the fixture resolves ${violations}/${table.oracle.length} to a `
         + `violation, so this check could not tell the two apart`);
    } else {
      note(`policy: ${table.rendered.length} ${table.kind} rows, each carrying the `
         + `server's verdict and its basis (${violations} violation(s))`);
    }
  }
  const bad = table.kindCounts.filter(([, shown, want]) => shown !== want);
  if (bad.length) {
    fail(`policy: the kind pills count ${JSON.stringify(bad)} (shown vs resolved)`);
  }

  // --- audit's own components cannot be denied here ---------------------------
  const req = table.rendered.filter((r) => r.required);
  const wantReq = table.oracle.filter((o) => o.required).length;
  if (!wantReq) {
    fail('policy: the fixture discovered none of audit\'s own skills, so the '
       + '"required" row could not be checked at all');
  } else if (req.length !== wantReq || req.some((r) => !r.locked)) {
    fail(`policy: ${wantReq} required capabilit(ies), ${req.length} marked and `
       + `${req.filter((r) => r.locked).length} actually locked`);
  } else {
    note(`policy: ${wantReq} required capabilit(ies) shown locked`);
  }

  // --- area columns say which of them decides anything today ------------------
  const cols = await page.evaluate(() => ({
    oracle: (POLICY.areaInfo || []).map((a) => [a.tag, a.active]),
    rendered: [...document.querySelectorAll('#policy th.ar')].map((th) =>
      [th.firstChild.textContent, !th.classList.contains('dormant'),
       (th.querySelector('.mut') || {}).textContent]),
  }));
  const colsOk = cols.oracle.length === cols.rendered.length
    && cols.oracle.every(([tag, live], i) => cols.rendered[i][0] === tag
      && cols.rendered[i][1] === live
      && cols.rendered[i][2] === (live ? 'live' : 'dormant'));
  if (!cols.oracle.length || !cols.oracle.some(([, live]) => live)
      || !cols.oracle.some(([, live]) => !live)) {
    fail(`policy: the fixture's areas are ${JSON.stringify(cols.oracle)} — it needs `
       + `both a live and a dormant one or the column check proves nothing`);
  } else if (!colsOk) {
    fail(`policy: area columns ${JSON.stringify(cols.rendered)} do not match the `
       + `server's ${JSON.stringify(cols.oracle)}`);
  } else {
    note(`policy: ${cols.oracle.length} area columns, each naming whether it is live`);
  }

  // --- the block as written, including the patterns no switch can express -----
  const rules = await page.evaluate(() => ({
    oracle: (POLICY.rules[PF.kind] || []).map((r) =>
      `${r.scope || 'project'} ${r.list} ${r.pattern}`),
    rendered: [...document.querySelectorAll('#policy tr[data-prule]')]
      .map((tr) => tr.dataset.prule),
  }));
  if (rules.oracle.join('|') !== rules.rendered.join('|')) {
    fail(`policy: the rules table shows ${JSON.stringify(rules.rendered)} for a block `
       + `the server reads as ${JSON.stringify(rules.oracle)}`);
  } else if (!rules.oracle.some((r) => r.includes('*'))) {
    fail('policy: the fixture has no glob rule, so "a pattern is visible and '
       + 'removable" was not actually checked');
  } else {
    note(`policy: ${rules.oracle.length} rules listed as written, globs included`);
  }

  // --- one switch: dirty, counted, guarded, and the dialog says what it will do
  const subject = await page.evaluate(() => (POLICY.resolved[PF.kind] || [])
    .find((r) => !r.required && r.verdict === 'allow') || null);
  if (!subject) { fail('policy: no allowed, non-required row to deny'); return; }
  await page.selectOption(`#policy tr[data-pcap="${subject.name}"] select.prule`, 'deny');
  await page.waitForTimeout(200);
  const dirty = await page.evaluate(() => {
    const ev = new Event('beforeunload', { cancelable: true });
    dispatchEvent(ev);
    const d = document.querySelector('#policy [data-discard=policy]');
    return { rows: editRows('policy'), blocked: ev.defaultPrevented,
             label: d ? d.textContent : null,
             // aria-disabled (F16). This one asserts the button is NOT dead, so
             // reading `.disabled` would go on passing for the rest of time
             // whatever the panel did — the direction that hides a regression.
             disabled: d ? d.getAttribute('aria-disabled') === 'true' : null,
             pend: document.querySelectorAll('#policy td.pend').length };
  });
  if (dirty.rows.length !== 1 || dirty.rows[0].field !== 'policy.skills.deny'
      || !dirty.blocked || dirty.disabled || !/1 change\b/.test(dirty.label || '')
      || dirty.pend !== 1) {
    fail(`policy: one switch produced ${JSON.stringify(dirty.rows)}, beforeunload `
       + `blocked=${dirty.blocked}, Discard "${dirty.label}", ${dirty.pend} pending cell(s)`);
  } else {
    note(`policy: denying ${subject.name} -> one change row, one pending cell, `
       + `"${dirty.label}", close guarded`);
  }
  await page.locator('#policy [data-psave]').click();
  await awaitConfirmDialog(page);
  const listed = await page.evaluate(() =>
    [...document.querySelectorAll('dialog.confirm tbody tr')]
      .map((r) => [...r.children].map((c) => c.textContent.trim())));
  if (listed.length !== 1 || listed[0][1] !== 'policy.skills.deny'
      || !listed[0][2].includes(subject.name)) {
    fail(`policy: the dialog lists ${JSON.stringify(listed)} for one denial`);
  } else {
    note(`policy: the dialog lists "${listed[0].join(' · ')}"`);
  }
  await page.locator('dialog.confirm [data-cfgo]').click();
  await page.waitForTimeout(900);

  // The point of the whole flow: the file changed, and the verdict on screen is
  // the server's fresh answer about the file — not the client's guess about it.
  const after = await page.evaluate(async (name) => {
    const p = await api('GET', '/api/policy');
    const tr = document.querySelector(`#policy tr[data-pcap="${CSS.escape(name)}"]`);
    return { stored: ((p.stored || {}).skills || {}).deny || [],
             verdict: tr ? tr.dataset.verdict : null,
             basis: tr ? (tr.querySelector('.pbasis') || {}).textContent : null,
             pend: document.querySelectorAll('#policy td.pend').length,
             dirty: editRows('policy').length };
  }, subject.name);
  if (!after.stored.includes(subject.name)) {
    fail(`policy: after confirming, policy.skills.deny on disk is `
       + `${JSON.stringify(after.stored)}`);
  } else if (after.verdict !== 'violation' || !(after.basis || '').includes('deny')
             || after.pend || after.dirty) {
    fail(`policy: after saving, ${subject.name} still reads ${after.verdict} `
       + `("${after.basis}") with ${after.pend} pending cell(s) and ${after.dirty} `
       + `unsaved change(s)`);
  } else {
    note(`policy: saved -> on disk, re-read, and the row now says violation`);
  }

  // --- the promise about audit's own components, kept by the server -----------
  // The switch for a required row is disabled, which is the friendly half. This is
  // the half that holds when someone writes the rule as a pattern instead.
  await page.fill('#poladdpat', 'audit:*');
  await page.evaluate(() => {
    const sels = document.querySelectorAll('#policy .poladd select');
    sels[0].value = 'deny'; sels[1].value = '';
  });
  await page.locator('#policy [data-poladd]').click();
  await page.waitForTimeout(200);
  await page.locator('#policy [data-psave]').click();
  await awaitConfirmDialog(page);
  await page.locator('dialog.confirm [data-cfgo]').click();
  await page.waitForTimeout(900);
  const refused = await page.evaluate(async () => {
    const p = await api('GET', '/api/policy');
    return { deny: ((p.stored || {}).skills || {}).deny || [],
             said: (document.querySelector('#policy .findings-slot .findings.err')
                    || {}).textContent || '' };
  });
  if (refused.deny.includes('audit:*')) {
    fail('policy: a rule denying audit\'s own components was written to the file');
  } else if (!/audit/i.test(refused.said)) {
    fail(`policy: the refusal did not say why — the box reads "${refused.said}"`);
  } else {
    note('policy: a deny aimed at audit\'s own components is refused, in the '
       + 'validator\'s words');
  }
  // Put the form back to the file, through the control that does it.
  await page.locator('#policy [data-discard=policy]').click();
  await awaitConfirmDialog(page);
  await page.locator('dialog.confirm [data-cfgo]').click();
  await page.waitForTimeout(400);
  const restored = await page.evaluate(() => editRows('policy').length);
  if (restored !== 0) {
    fail(`policy: Discard left ${restored} unsaved change(s) behind`);
  }
  if (statePath) note(`policy: enforcement marker read from ${statePath}`);
}


/* ---- F-P-6 (th): Appearance — the look, edited as tokens ---------------------
 *
 * The panel and the report are one visual system: a single token layer that the
 * server compiles by substituting values into the stylesheet. This tab edits
 * those values. Three things only a browser can prove, and each is the whole
 * point of the feature:
 *
 *   the PREVIEW is real — a colour typed here repaints the panel it is typed
 *   into, so it is judged on the thing it colours, not on a swatch;
 *   the CHANGE COUNT is the theme minus the default, computed rather than
 *   remembered, so it survives a reload and a file somebody else wrote;
 *   the WAY BACK works — revert one row, and the page is wearing the default
 *   again with nothing left behind on the root element.
 *
 * The write path is deliberately NOT driven here: it writes a file into the
 * fixture, and the writer's own refusals (an unknown token, a value that is not
 * a value) are pinned in _panel_write's selftest where they can be exhaustive.
 */
// --- the Appearance tab --------------------------------------------------------

export async function assertAppearanceWorks(page, { note, fail, tabTo, shot }) {
  await tabTo(page, 'look');
  await page.waitForTimeout(350);
  const shape = await page.evaluate(() => ({
    groups: [...document.querySelectorAll('#look [data-thgroup]')]
      .map((g) => g.getAttribute('data-thgroup')),
    rows: document.querySelectorAll('#look [data-thtoken]').length,
    accentRow: !!document.querySelector('#look [data-thtoken="--accent"]'),
    // The chart palette is locked until asked twice.
    chartsOpen: !!document.querySelector('#look [data-thgroup=charts] [data-thtoken]'),
    unlock: !!document.querySelector('#look [data-thunlock]'),
    count: (document.querySelector('#look [data-thcount]') || {}).textContent,
    source: (document.querySelector('#look [data-thsrc]') || {})
      .getAttribute && document.querySelector('#look [data-thsrc]').getAttribute('data-thsrc'),
  }));
  if (!shape.accentRow || shape.rows < 20) {
    fail(`appearance: the tab lists ${shape.rows} token row(s) and `
       + `${shape.accentRow ? 'has' : 'has no'} --accent — it is meant to carry the `
       + `whole editable vocabulary`);
    return;
  }
  if (shape.chartsOpen || !shape.unlock) {
    fail('appearance: the chart palette is editable without asking — it is '
       + 'validated for colour-vision deficiency against these surfaces, so it '
       + 'opens deliberately or not at all');
  } else {
    note(`appearance: ${shape.rows} tokens across ${shape.groups.length} groups, `
       + `charts locked behind an unlock, wearing "${shape.source}"`);
  }

  // The preview: type a colour, and the PANEL wears it. Into the column that is
  // LIVE — the preview paints the mode the reader is in, and the table says
  // which that is; typing into the other one correctly changes nothing.
  const live = await page.evaluate(() =>
    (document.querySelector('#look [data-thlive]') || {}).getAttribute('data-thlive'));
  const before = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue('--accent').trim());
  const cell = (token, mode) =>
    `#look [data-thtoken="${token}"] input#th-${token.slice(2)}-${mode}`;
  await page.fill(cell('--accent', live), '#b5179e');
  await page.waitForTimeout(300);
  const painted = await page.evaluate(() => ({
    accent: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),
    inline: document.documentElement.style.getPropertyValue('--accent').trim(),
    count: (document.querySelector('#look [data-thcount]') || {}).textContent,
    painted: getComputedStyle(document.querySelector('.tab.on')).color,
  }));
  if (painted.accent !== '#b5179e' || painted.inline !== '#b5179e') {
    fail(`appearance: typing a colour into the LIVE (${live}) column did not `
       + `reach the page (--accent is "${painted.accent}", inline `
       + `"${painted.inline}", was "${before}") — the preview is the panel `
       + `itself, or it is not a preview`);
  } else if (!/change/.test(painted.count || '')) {
    fail(`appearance: the page repainted but the change count says `
       + `"${painted.count}"`);
  } else {
    note(`appearance: a colour typed into the live ${live} column repaints the `
       + `panel (${before} → ${painted.accent}) and is counted`);
  }

  // ...and the way back leaves nothing behind.
  await page.click(`#look [data-threvert="--accent|${live}"]`);
  await page.waitForTimeout(300);
  const back = await page.evaluate(() => ({
    accent: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),
    inline: document.documentElement.style.getPropertyValue('--accent').trim(),
    count: (document.querySelector('#look [data-thcount]') || {}).textContent,
  }));
  if (back.accent !== before || back.inline !== '') {
    fail(`appearance: reverting left --accent at "${back.accent}" with inline `
       + `"${back.inline}" — a revert must clear the property, not overwrite it`);
  } else if (!/no changes/.test(back.count || '')) {
    fail(`appearance: after reverting the only change, the count says "${back.count}"`);
  } else {
    note('appearance: revert puts the token back and clears the override');
  }

  // Contrast is reported, and never in the way of the reader's own decision.
  await page.fill(cell('--text', live), live === 'dark' ? '#222222' : '#dddddd');
  // The tab rebuilds on a debounce (a colour picker fires per pixel dragged),
  // so this waits for the rebuild rather than for a duration.
  await page.waitForFunction(
    () => document.querySelectorAll('#look [data-thwarn]').length > 0,
    null, { timeout: 4000 }).catch(() => {});
  const warned = await page.evaluate(() => ({
    warns: [...document.querySelectorAll('#look [data-thwarn]')].map((w) => w.textContent),
    saveEnabled: !document.querySelector('#look [data-thsave]').disabled,
  }));
  if (!warned.warns.some((w) => /below/.test(w))) {
    fail('appearance: an unreadable text colour drew no contrast warning');
  } else if (!warned.saveEnabled) {
    fail('appearance: the contrast warning disabled Save — it is a warning, not a gate');
  } else {
    note(`appearance: an unreadable pair is named (${warned.warns.length} warning(s)) `
       + `and Save stays available — the reader's own call`);
  }
  await page.click(`#look [data-threvert="--text|${live}"]`);
  await page.waitForTimeout(250);

  // Density: one press, and the panel's own spacing scale moves. Measured on a
  // computed token rather than on a screenshot — "it looks tighter" is not an
  // assertion.
  const sp0 = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue('--sp-3').trim());
  await page.click('#look [data-thdensity=compact]');
  await page.waitForTimeout(350);
  const sp1 = await page.evaluate(() => ({
    sp: getComputedStyle(document.documentElement).getPropertyValue('--sp-3').trim(),
    pressed: document.querySelector('#look [data-thdensity=compact]')
      .getAttribute('aria-pressed'),
    counted: (document.querySelector('#look [data-thcount]') || {}).textContent,
  }));
  if (sp1.sp === sp0 || sp1.pressed !== 'true') {
    fail(`appearance: choosing compact left --sp-3 at "${sp1.sp}" (was "${sp0}") `
       + `and aria-pressed=${sp1.pressed} — density is meant to move the whole `
       + `spacing scale at once`);
  } else if (!/change/.test(sp1.counted || '')) {
    fail(`appearance: the density changed but the count says "${sp1.counted}"`);
  } else {
    note(`appearance: density compact scales the spacing scale live `
       + `(--sp-3 ${sp0} → ${sp1.sp}) and counts as a change`);
  }
  await page.click('#look [data-thdensity=comfortable]');
  await page.waitForTimeout(350);
  const sp2 = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue('--sp-3').trim());
  if (sp2 !== sp0) {
    fail(`appearance: back at comfortable, --sp-3 is "${sp2}" and not the `
       + `"${sp0}" it started at — the default density must be a no-op`);
  } else {
    note('appearance: comfortable puts the scale back exactly');
  }

  // Card order: move one, and Overview draws in that order.
  const first = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('#look [data-thcard]')];
    return rows.length ? rows[0].getAttribute('data-thcard') : null;
  });
  if (!first) {
    fail('appearance: no card-order control — the Layout group lists none');
  } else {
    await page.click('#look [data-thcard="' + first + '"] button:not([disabled])');
    await page.waitForTimeout(300);
    await tabTo(page, 'over');
    await page.waitForTimeout(400);
    const order = await page.evaluate(() =>
      [...document.querySelectorAll('#over [data-card]')]
        .map((n) => n.getAttribute('data-card')));
    if (order[0] === first) {
      fail(`appearance: moving "${first}" down left it first in Overview `
         + `(${order.join(', ')}) — the order is drawn, not just stored`);
    } else {
      note(`appearance: reordering moves the card in Overview (${order.join(', ')})`);
    }
    await tabTo(page, 'look');
    await page.waitForTimeout(300);
    // Put it back, so the shot below and every later check see the drawn order
    // — and moving a card down and back up must leave NO change behind, or the
    // tab offers to write an order that says what the default already says.
    const back = await page.$(`#look [data-thcard="${first}"] button:not([disabled])`);
    if (back) { await back.click(); await page.waitForTimeout(350); }
    const settled = await page.evaluate(() =>
      (document.querySelector('#look [data-thcount]') || {}).textContent);
    if (!/no changes/.test(settled || '')) {
      fail(`appearance: after moving a card down and back up the tab still says `
         + `"${settled}" — an order equal to the drawn one is not a change`);
    } else {
      note('appearance: a reorder undone leaves nothing to save');
    }
  }

  // The shot belongs here, with the tab open and nothing edited: what a reader
  // meets when they first press Appearance.
  await page.evaluate(() => window.scrollTo(0, 0));
  await shot(page, 'panel-appearance', { full: true });
}

/* ---- F-P-3 (px): the capability table, given the whole screen ----------------
 *
 * The Policy tab's table is the one surface here that is a LIST first: a
 * project with a plugin or two installed already scrolls it inside a 34rem
 * frame, and reading a verdict per area means reading across it at the same
 * time. So the frame gets an expand control and the table gets a dialog that
 * is the viewport — the browse-dialog pattern, one more time.
 *
 * What a browser has to prove, and a string pin cannot: the dialog carries the
 * SAME rows as the tab (one builder, not two), typing in either search box
 * filters both (the filter state is shared, so a reader does not lose their
 * place by expanding), and Esc gives the focus back to the control that opened
 * it — a dialog that strands the caret is worse than no dialog.
 */
/**
 * Every save/discard footer the panel renders, as a set derived from the PAGE.
 *
 * WHAT THIS REPLACES, AND WHY IT HAD TO MOVE. Three assertions in
 * `test__panel_page.py` guarded this by counting occurrences in the assembled
 * source: `count("'data-save':'") == 3`, `count("'data-discard':'") == 4`,
 * `count("offState(discard,!n);") == 3`. Each protected something real — a Save
 * with no hook cannot be named after its view is rebuilt, so a caret handed back
 * by a confirm dialog had nowhere to go, measured once as arriving at 676ms and
 * being taken away at 682ms — and each did it by requiring the copies to stay
 * copies. Factoring the five footers into one helper would have turned all three
 * red while making the page better, which is a check that has outlived its claim.
 *
 * A count cannot survive that refactor and this can: one helper emitting five
 * footers still renders five footers.
 *
 * KEYED ON THE BUTTON LABEL, not on a container or a hook, and both alternatives
 * were tried first. `.savebar` sees only two of the five — `guards` and `policy`
 * use it while `comp` and `ado` use a bare `.row` with an inline margin, so the
 * census silently checked 40% of the page. Keying on the hook is worse than
 * wrong, it is vacuous: the property being checked IS that a Save carries a hook,
 * so enumerating by hook can never find one that lacks it. What the reader sees
 * is the label, so that is what this reads.
 *
 * Reloads first, so every view is CLEAN and "Discard is dead when there is
 * nothing to throw away" describes a known state rather than whatever the
 * preceding checks left behind.
 */
