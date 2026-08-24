// ---------- Proposals: parked phases, and what happens to them ----------
//
// F-P-32. `/audit:init` can park every synthesized phase, and until now the panel
// had no idea they existed: the whole content of the plan lived in `proposals[]`
// and the only surface that showed it was `/audit:status`. A tab that cannot see
// the work is a tab that reports "nothing here" about a full plan.
//
// ITS OWN TAB rather than a corner of Composition. That view is the plan EDITOR,
// and a parked phase is not part of the plan yet; putting them together is the
// confusion this was reported about. It also has its own verbs, which no form
// footer models: materialize, drop, revive.
//
// NO RULE LIVES HERE. Every action posts to `/api/proposal`, which runs
// `materialize-proposal.py`'s own `main` — the same code path `/audit:propose`
// takes. The closure, the index lock, the collision guard and the revalidation all
// happen once, in the file that has cases for them. What this file owns is the
// conversation: showing what an action would do before it is taken.

/** True while an action is in flight, so a double click cannot post twice. */
let PROPBUSY = false;

/**
 * The phase a proposal reserves and how big it is, as ONE string.
 *
 * `_proposals.reserved_cell` in JavaScript, down to the parentheses and the dash.
 * F93 was this cell existing in three spellings; the Python side was reduced to
 * one and THIS FILE WAS THE FOURTH AND FIFTH — the card composed it with ` · `
 * and the confirm dialog with ` (…)`, and the dialog hand-rolled the plural as
 * `+(n===1?'':'s')`, which is the exact convention `shared/plural.js` exists to
 * replace. Two spellings of one cell is how a reader comparing this tab against
 * `/audit:propose list` decides the two are describing different work.
 *
 * `hasPayload` is the basis for the dash, never a truthy `phaseId` — Python's
 * reason, and it holds here for the same one: a legacy free-form entry reserves
 * nothing, and printing a phase id for it would invent one.
 *
 * @param {{hasPayload: boolean, phaseId: ?string, taskCount: number}} row - a
 *   `_proposals.proposal_rows` row, or a plan step wearing the same three keys
 * @returns {string} `P4 (3 tasks)`, or `-` when nothing is reserved
 */
function propReservedCell(row) {
  if (!row.hasPayload) return '-';
  return row.phaseId + ' (' + plural(row.taskCount, 'task') + ')';
}

/**
 * The words on a proposal's status badge.
 *
 * THREE READINGS, NOT ONE, and that is `proposal_rows`' F93 decision arriving on
 * this surface. `status` is normalised — a MISSING status reads as `proposed` —
 * so a badge rendered from it alone tells a record with no status that it has
 * one, and tells a record carrying `parked` that it says `Parked`, in the same
 * type as the three words this plugin actually writes. `label()` cannot help:
 * it title-cases whatever it is handed, so an invented status and a real one
 * come out looking equally official.
 *
 * So the vocabulary is asked first, and where the answer is no, the value is
 * named as the thing it is. Naming it is the whole point — `/audit:propose list`
 * is the only other surface that shows these in full, and it makes the same
 * distinction from the same two fields.
 *
 * @param {{status: string, statusRaw: ?string, statusKnown: boolean}} p - one
 *   entry of STATE.proposals
 * @returns {string} the badge's text
 */
function propStatusWords(p) {
  if (p.statusKnown) return label(p.status);
  if (p.statusRaw == null) return label(p.status) + ' (none recorded)';
  return p.statusRaw + ' — not a status this plugin writes';
}

/**
 * Post one proposal action and hand back the server's answer.
 * @param {object} body - {action, id, ...}
 * @returns {Promise<object>} the endpoint's `{ok, ...}` payload
 */
function propPost(body) { return api('POST', '/api/proposal', body); }

/**
 * Re-read the manifest and repaint, after an action that changed it.
 *
 * `refreshFromDisk` rather than a local patch: materializing writes phases,
 * `fileIndex` and the proposal record at once, and every other tab reads those.
 * A local patch would leave Composition showing a plan that no longer exists.
 * @returns {Promise<void>}
 */
async function propReload() { await refreshFromDisk(); }

/**
 * Materialize a proposal, showing what it pulls in BEFORE anything is written.
 *
 * Two calls on purpose: `plan` is read-only and its answer is what the dialog
 * renders. A single call that wrote first and reported after would be asking for
 * consent to something already done.
 *
 * When the plan reports `needsDecision`, this takes the dependency-closure path —
 * the same one `/audit:propose` recommends — and the dialog names every proposal
 * it brings along. Cutting the edge instead is a `--drop-edges` decision that
 * stays on the command line, and the note says so rather than hiding it.
 * @param {object} p - one entry of STATE.proposals
 * @returns {Promise<void>}
 */
async function propMaterialize(p) {
  if (PROPBUSY) return;
  PROPBUSY = true;
  try {
    const planned = await propPost({ action: 'plan', id: p.id });
    if (!planned.ok) { toast((planned.findings || ['plan failed'])[0]); return; }
    const plan = planned.plan || {};
    const refused = plan.refused || [];
    if (refused.length && !(plan.steps || []).length) {
      toast(refused[0].reason);
      return;
    }
    // `hasPayload: true` is stated rather than read off the step, and it is not
    // a fudge: `_proposals.refusal` refuses a proposal that carries no
    // `payload.phase`, so no plan step can exist for one. The step's OWN phase
    // id is what goes in, because a collision renames it and the write uses the
    // new name — the proposal's id would name a phase that is not created.
    const rows = (plan.steps || []).map((s) => cfRow(
      s.id, 'materialize', 'parked',
      propReservedCell({ hasPayload: true, phaseId: s.phaseId,
        taskCount: s.taskCount })
        + (s.renamedFrom ? ' — renamed from ' + s.renamedFrom : '')));
    const pulled = (plan.pulledIn || []).filter((x) => x !== p.id);
    const note = pulled.length
      ? p.id + ' waits on ' + pulled.join(', ')
        + ', so those are materialized first. To cut the edge instead, use '
        + '/audit:propose materialize ' + p.id + ' --drop-edges'
      : 'writes the phase, its tasks and fileIndex';
    if (!await confirmChanges({
      title: 'Materialize ' + p.id, rows: rows, verb: 'Materialize',
      note: note, lock: false })) return;
    const done = await propPost({
      action: 'materialize', id: p.id,
      policy: plan.needsDecision ? 'with-deps' : null });
    if (!done.ok) { toast((done.findings || ['materialize failed'])[0]); return; }
    await propReload();
    toast(done.message || (p.id + ' materialized'));
  } finally { PROPBUSY = false; }
}

/**
 * Archive a proposal, with the reason the validator requires.
 *
 * The reason is typed in the row and shown in the dialog, so the sentence that
 * lands in the manifest is the one that was read before confirming. The button is
 * dead until there is one — an affordance, not a second copy of the rule: the
 * script refuses a blank reason regardless of what this does.
 * @param {object} p - one entry of STATE.proposals
 * @param {string} reason - the one-line justification
 * @returns {Promise<void>}
 */
async function propDrop(p, reason) {
  if (PROPBUSY) return;
  PROPBUSY = true;
  try {
    if (!await confirmChanges({
      title: 'Drop ' + p.id, danger: 1, lock: false, verb: 'Drop',
      rows: [cfRow(p.id, 'status', p.status, 'dropped'),
             cfRow(p.id, 'notes', null, reason)],
      note: 'the payload is kept — a dropped proposal is history, not a deletion',
    })) return;
    const done = await propPost({ action: 'drop', id: p.id, reason: reason });
    if (!done.ok) { toast((done.findings || ['drop failed'])[0]); return; }
    await propReload();
    toast(done.message || (p.id + ' dropped'));
  } finally { PROPBUSY = false; }
}

/**
 * Put a dropped proposal back in play, keeping why it was declined.
 * @param {object} p - one entry of STATE.proposals
 * @returns {Promise<void>}
 */
async function propRevive(p) {
  if (PROPBUSY) return;
  PROPBUSY = true;
  try {
    if (!await confirmChanges({
      title: 'Revive ' + p.id, lock: false, verb: 'Revive',
      rows: [cfRow(p.id, 'status', 'dropped', 'proposed')],
      note: 'the drop reason stays as history',
    })) return;
    const done = await propPost({ action: 'revive', id: p.id });
    if (!done.ok) { toast((done.findings || ['revive failed'])[0]); return; }
    await propReload();
    toast(done.message || (p.id + ' revived'));
  } finally { PROPBUSY = false; }
}

/**
 * One proposal, as a disclosure: the summary is the decision, the body is why.
 * @param {object} p - one entry of STATE.proposals
 * @returns {HTMLElement} a <details> element
 */
function propCard(p) {
  const tasks = p.tasks || [];
  const head = el('summary', {},
    el('span', { class: 'mono' }, p.id),
    el('span', { class: 'propname' }, p.name || ''),
    // The colour still comes off the NORMALISED status, because a value outside
    // the vocabulary has no colour of its own and `--st` already falls back to
    // muted. The WORDS come off the raw reading, and the extra hook is what lets
    // a gate find such a record without parsing the sentence.
    el('span', { class: 'st', 'data-status': p.status,
      'data-propstatusknown': p.statusKnown ? null : '0' },
    propStatusWords(p)),
    // The cell, then — only when there is nothing to reserve — the reason. The
    // dash is what `/audit:propose list` prints in the same column, so the two
    // surfaces agree; the sentence beside it is the room a card has and a table
    // column has not.
    el('span', { class: 'mut small' }, propReservedCell(p)),
    p.hasPayload ? null
      : el('span', { class: 'mut small' }, 'no payload — nothing to materialize'));

  const facts = [];
  const fact = (k, v) => { if (v) facts.push(el('div', { class: 'pf' },
    el('span', { class: 'pfk' }, k), el('span', { class: 'pfv' }, String(v)))); };
  fact('scope', p.scope);
  fact('benefit', p.benefit);
  fact('note', p.technicalNote);
  if ((p.openQuestions || []).length) fact('open questions', p.openQuestions.join(' · '));
  // The two states that carry their own history, and the reason each one is worth
  // keeping rather than deleting. `statusRaw` here too, and not because the two
  // readings differ for these two words - they cannot - but because ONE reading
  // per surface is what stops the next branch being written off the other one.
  if (p.statusRaw === 'dropped') fact('why declined', p.notes);
  if (p.statusRaw === 'materialized') fact('became', p.materializedAs);
  if ((p.waitsOn || []).length) fact('waits on', p.waitsOn.join(', '));

  const body = [el('div', { class: 'propfacts' }, ...facts)];
  if (tasks.length) {
    const tb = el('tbody');
    tasks.forEach((t) => tb.append(el('tr', {},
      el('td', { class: 'mono' }, t.id || ''),
      el('td', {}, t.title || ''),
      el('td', { class: 'mono' }, t.risk || '—'))));
    body.push(el('div', { class: 'tablewrap' },
      el('table', { class: 'regtbl' },
        tableHead(['task', 'title', 'risk']), tb)));
  }

  // Actions follow the state, and a state with no action says so instead of
  // showing dead buttons.
  //
  // THE TWO CLOSED STATES ARE NAMED AND EVERYTHING ELSE IS OPEN, which is
  // `_proposals.refusal`'s own shape rather than a rearrangement of it: that
  // function refuses `materialized` and `dropped` and nothing else, so a record
  // carrying no status, or one carrying a word this plugin never writes, is
  // materializable and the CLI will materialize it. Written the other way round
  // — `proposed` first, `else` last — the catch-all swallowed both of those and
  // told them their phase was live and this record was its history trail, which
  // is a claim about work that was never done. Reading `statusRaw` is what keeps
  // the two ends together: `status` normalises an absent value to `proposed`,
  // and a surface that classifies must not classify off an invention.
  const acts = el('div', { class: 'propacts' });
  if (p.statusRaw === 'materialized') {
    acts.append(el('span', { class: 'mut small' },
      'materialized — its phase is live, and this record is the history trail'));
  } else if (p.statusRaw === 'dropped') {
    acts.append(el('button', { class: 'btn small', 'data-proprevive': p.id,
      type: 'button', onclick: () => propRevive(p) }, 'Revive'));
  } else {
    if (p.hasPayload) {
      acts.append(el('button', { class: 'btn primary small',
        'data-propmat': p.id, type: 'button',
        onclick: () => propMaterialize(p) }, 'Materialize'));
    }
    const reason = el('input', { class: 'propreason', type: 'text',
      'data-propreason': p.id,
      'aria-label': 'Why ' + p.id + ' is being declined',
      placeholder: 'why is this being declined?' });
    const drop = el('button', { class: 'btn small', 'data-propdrop': p.id,
      type: 'button', onclick: () => propDrop(p, reason.value.trim()) }, 'Drop');
    offState(drop, true);
    reason.addEventListener('input', () => offState(drop, !reason.value.trim()));
    acts.append(reason, drop);
  }
  body.push(acts);
  return el('details', { class: 'prop', 'data-prop': p.id,
    'data-status': p.status }, head, ...body);
}

/**
 * Paint the Proposals tab.
 *
 * Read-only state plus actions, so unlike Composition and Settings there is no
 * draft to protect: this always repaints on a refresh, and `dirtyViews` has
 * nothing to say about it.
 * @returns {void}
 */
function renderProposals() {
  const c = $('#props');
  if (!c) return;
  const keepOpen = new Set([...c.querySelectorAll('details.prop[open]')]
    .map((d) => d.getAttribute('data-prop')));
  c.textContent = '';
  const props = (STATE && STATE.proposals) || [];
  // Inside a `.card`, like every other view. That is the panel's structural unit
  // rather than decoration: the responsive sweep waits for a pane to hold one
  // before it measures, so a view that skipped it would time out instead of being
  // checked at 390px.
  const card = el('div', { class: 'card', 'data-propcard': '1' },
    el('h2', {}, 'Proposals'));
  c.append(card);
  if (!props.length) {
    // The absent basis, named. A tab that vanished when empty would be the same
    // defect as a row that vanishes: the reader cannot tell "none" from "not
    // shown".
    // ...and "none parked" is not the same fact as "nowhere to park them". Both
    // render an empty list, so without this the reader is told the plan holds no
    // proposals when there is no plan at all - the one distinction this card's
    // own comment exists to make, missed one level up.
    card.append(el('p', { class: 'blurb', 'data-propnone': '1' },
      (STATE && STATE.rollup)
        ? 'No parked proposals. /audit:init parks a synthesized phase here when you '
          + 'decline it, so nothing is lost and nothing starts until you say so.'
        : 'No plan yet, so nothing can be parked. /audit:init proposes phases and '
          + 'parks the ones you decline here, rather than discarding them.'));
    return;
  }
  // `statusRaw`, not `status`, and this is the same reading `/audit:status`'s
  // PROPOSALS block makes — deliberately, because the two print the same number
  // about the same manifest and were free to disagree. `status` normalises an
  // absent value to `proposed`, so counting off it made a record with no status
  // parked HERE and legacy THERE, and neither surface said which it had done.
  // The out-of-vocabulary records are then counted and named rather than folded
  // into either total: a record nothing can classify is the one a reader most
  // needs to be told about, and it is still actionable below.
  const parked = props.filter((p) => p.statusRaw === 'proposed').length;
  const legacy = props.filter((p) => !p.statusKnown).length;
  card.append(el('p', { class: 'blurb' },
    plural(parked, 'proposal') + ' parked of ' + plural(props.length, 'record')
    + ' — materializing writes the phase and its tasks into the plan; dropping '
    + 'keeps the record and its reason.'
    + (legacy
      ? ' ' + plural(legacy, 'record carries', 'records carry')
        + ' a status this plugin does not write, counted as neither parked nor '
        + 'history; each names its own on the badge.'
      : '')));
  props.forEach((p) => {
    const one = propCard(p);
    if (keepOpen.has(p.id)) one.open = true;
    card.append(one);
  });
}
