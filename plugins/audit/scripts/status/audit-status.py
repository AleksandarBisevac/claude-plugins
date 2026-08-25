#!/usr/bin/env python3
"""
Headless status rollup + CI gate for the audit manifest — dependency-free (stdlib).

Turns the manifest into a machine-readable summary and, in gate mode, a CI
pass/fail signal — so a pipeline can block a merge on manifest state without
any Claude session involved.

Usage:
  audit-status.py --help
  audit-status.py <manifest> [--json [--discovery]] [--gate] [--phase <id>]
                             [--color auto|always|never]
                             [--fail-on <c1,c2,...>]
  audit-status.py --selftest

Modes: a bare invocation renders a human report; --json is for machines.
  --json    print the rollup as JSON
  --discovery  with --json only: add a `discovery` block (the skills/agents this
            project can actually see) so /audit:init and /audit:task suggest from
            ONE mechanical source instead of each scanning the filesystem in
            prose. Without the flag the --json payload is byte-identical to the
            pre-flag output (pinned by selftest dv1).
  --phase   scope the human render to one phase (totals stay whole-plan)
  --gate    evaluate fail conditions; exit 1 when any trips (prints a summary)

The `--fail-on` conditions are NOT listed a second time here, and they are not
counted here either - the number was written into this sentence once and went
stale the first time one was added. They live in
`CONDITION_HELP` below, keyed by `_status_facts.CONDITIONS`, and `--help` renders
them - so the names a user can pass and the names the gate evaluates are one list.
Read them with `audit-status.py --help`; cases `ap8`/`ap10` fail the build if the
two ever disagree.

Exit codes: 0 pass · 1 gate failed · 2 usage error / unreadable manifest
(matching validate-manifest.py's convention). `--help` exits 0.

**Under --json, stdout carries exactly one JSON document.** The `GATE PASSED/FAILED`
lines are a human rendering of `summary["gate"]`, which the payload already carries
in full, so with --json they go to stderr - a caller piping into `jq` was getting
JSON with a trailing sentence glued on. Without --json nothing moves: stdout is
byte-for-byte what it has always been, which is what CI reads.

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test_audit_status.py`, byte-identical labels and all - see
`plugins/audit/tests/_harness.py`. The `_fixture()` most of them start from went
with them (no caller outside the suite), and so did the guard that keeps two case
groups from claiming one id letter.
"""
import argparse
import json
import os
import sys
import textwrap

# The path bootstrap: byte-identical in every `.py` under `scripts/`, counted by
# `_output.path_preamble_violations()`. It walks UP to the directory holding
# `_output.py` instead of counting `dirname()` calls, so it does not encode how deep
# this file sits and keeps working if the file is moved into a subdirectory.
# `install_path()` then adds that directory AND every subdirectory of it holding a
# `.py`: the folders are LABELS, NOT NAMESPACES, and every sibling below is still
# reached by a bare basename.
_anchor_dir = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_anchor_dir, "_output.py")):
    _anchor_up = os.path.dirname(_anchor_dir)
    if _anchor_up == _anchor_dir:
        raise ImportError("audit plugin: walked to the filesystem root from %s "
                          "without finding _output.py - the scripts/ anchor is "
                          "gone and no sibling can be imported" % (__file__,))
    _anchor_dir = _anchor_up
if _anchor_dir not in sys.path:
    sys.path.insert(0, _anchor_dir)

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()

import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR index+shards)
import _manifest_rules  # noqa: E402  (the manifest rules, at layer 2 - imported, not loaded)
import _areas  # noqa: E402  (meta.areas registry + the resolution every surface shares)
import _ui_theme as _theme  # noqa: E402  (the words a person reads for a machine value)
import _loader  # noqa: E402  (the one way scripts/ loads a sibling script as a library)
import _fmt  # noqa: E402  (the one token/cost formatter, since P10.6 — no indirection needed)
import _cli_fmt  # noqa: E402  (the one place CLI color lives - mode resolution + paint)
import _proposals  # noqa: E402  (the proposal READ side: one derivation of the rows
#                                  and of the "reserved phase (N tasks)" cell that this
#                                  block, the /audit:propose table and the panel's tab
#                                  all print - F93)
import _status_facts  # noqa: E402  (what the manifest SAYS: rollup, readiness, the gate)
import _invariants  # noqa: E402  (what GIT says: the post-hoc check behind --fail-on invariant-breach)

# --- the facts, under the names this command has always called them --------------
# NOT copies. `_status_facts` (layer 2) owns every one of these; the aliases exist
# because the ~600 lines of rendering below spell them unqualified, and because
# `tests/test_audit_status.py` asks for them by hand, case by case. They moved
# out because THREE modules wanted the facts and none wanted the rendering:
# `_panel_state` (L5) needs `rollup`, `audit-doctor` needs `submodule_conflicts`,
# `render-report` needs `evaluate_gate` — three of the seventeen edges
# `_deps.KNOWN_LAYER_DEBT` recorded, all of them this file being loaded as a
# library. `tests/test__status_facts.py` pins each name to be that module's own
# object, so a second implementation here fails a case rather than drifting.
CONDITIONS = _status_facts.CONDITIONS
DEFAULT_GATE = _status_facts.DEFAULT_GATE
BUDGET_WARN_PCT = _status_facts.BUDGET_WARN_PCT
CLOSED_BUG = _status_facts.CLOSED_BUG
READY_LIST_MAX = _status_facts.READY_LIST_MAX
HIGH_SEVERITIES = _status_facts.HIGH_SEVERITIES
_is_high_severity = _status_facts._is_high_severity
parse_gitmodules = _status_facts.parse_gitmodules
_strip_git_root = _status_facts._strip_git_root
submodule_conflicts = _status_facts.submodule_conflicts
_status_index = _status_facts._status_index
ready_tasks = _status_facts.ready_tasks
_by_status = _status_facts._by_status
_by_status_values = _status_facts._by_status_values
PARKED_PROPOSAL_STATUS = _status_facts.PARKED_PROPOSAL_STATUS
is_parked_proposal = _status_facts.is_parked_proposal
areas_of = _status_facts.areas_of
effective_bug_status = _status_facts.effective_bug_status
TERMINAL = _status_facts.TERMINAL
rollup = _status_facts.rollup
unmet_refs = _status_facts.unmet_refs
evaluate_gate = _status_facts.evaluate_gate
budget_breaches = _status_facts.budget_breaches
invariant_breaches = _status_facts.invariant_breaches


def invariants_block(manifest, manifest_path):
    """`_invariants.check_manifest` over every started phase, or the reason it could not run.

    The project is CLAUDE_PROJECT_DIR when Claude Code named one and the working
    directory otherwise — the same anchor `--discovery` uses, and deliberately not
    the manifest's own directory, which is `docs/audit/` on nearly every plan.

    An exception comes back as a BLOCK WITH NO `breaches` KEY rather than as an
    empty one. `_status_facts.invariant_breaches` reads that as "nothing was
    verified" and trips the gate; an empty list would have read as a clean bill of
    health produced by a crash.
    """
    project = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    try:
        return _invariants.check_manifest(
            manifest, manifest_path,
            _invariants.git_root_for(manifest, project), project,
            ledger_dir=_invariants.ledger_dir_for(manifest, manifest_path))
    except Exception as exc:                       # defensive; the checks fail soft
        return {"error": "the invariant checks could not run: %s" % (exc,)}


def _invariant_detail(summary):
    """What `GATE FAILED: invariant-breach (...)` says after the name."""
    found = invariant_breaches(summary) or []
    return "%d breach(es): %s" % (len(found),
                                  _output.some_of(found, sep="; "))


def _budget_detail(summary, threshold_pct):
    """Name the phases and their numbers, never just the count.

    "2 phase(s) over budget" sends the reader hunting; the whole point of tying spend
    to the plan is that it can say WHICH phase and by how much.

    Stayed HERE when `budget_breaches` went to `_status_facts`, and the seam is the
    point: breaches are a fact, an English sentence with currency in it is a
    command's output. Moving it down would have made `_fmt` a dependency of every
    module that only wanted the rollup."""
    rows = budget_breaches(summary, threshold_pct)
    if not rows:
        return "no phase past %.0f%%" % threshold_pct
    parts = ["%s at %.0f%% (%s of %s)"
             % (p.get("id"), p.get("pct") or 0,
                _fmt.fmt_cost(p.get("spent")), _fmt.fmt_cost(p.get("budget")))
             for p in sorted(rows, key=lambda x: -(x.get("pct") or 0))[:3]]
    more = "" if len(rows) <= 3 else ", +%d more" % (len(rows) - 3)
    return "; ".join(parts) + more


# --- loading ---------------------------------------------------------------------
def _load_validator():
    """The manifest rules. A plain module now, not a `_loader.load_script` of
    `validate-manifest.py`: that was this file (L7) loading an L7 peer, one of
    the edges `_deps.KNOWN_LAYER_DEBT` recorded, and the rules moved to layer 2
    so every consumer could import the one implementation instead.

    Kept as a function rather than inlined at the call site: it is what the
    suite substitutes to run the gate against a stub validator."""
    return _manifest_rules


# --- usage summary --------------------------------------------------------------
def usage_summary(manifest, manifest_path, project_dir=None):
    """Compact token-usage block for the rollup, or None when there is no ledger.

    Kept OUT of `rollup` so that function stays a pure dict -> dict transform; the
    ledger is I/O and belongs to the caller. Never raises: a missing, empty or
    unreadable ledger simply means no usage key, and every consumer treats that as
    "metering not in use" rather than an error."""
    try:
        ul = _loader.load_script("usage_ledger.py", modname="usage_ledger",
                                  cache=False)
    except Exception:
        return None

    meta_usage = ((manifest or {}).get("meta") or {}).get("usage") or {}
    rel = (meta_usage.get("ledgerDir")
           if isinstance(meta_usage, dict) else None) or os.path.join(
               ".claude", "usage")
    # Search upward from the manifest rather than assuming a fixed depth — see
    # usage_ledger.find_ledger_dir for why the fixed-depth version was dangerous.
    ledger_dir = ul.find_ledger_dir(
        manifest_path, rel, project_dir or os.environ.get("CLAUDE_PROJECT_DIR"))
    if not ledger_dir:
        return None

    try:
        rows = ul.read_ledger(ledger_dir)
    except Exception:
        return None
    if not rows:
        return None
    try:
        total = ul.totals(rows)
        by_phase = ul.aggregate(rows, "phase")
        # Trimmed at the door (F160): the plan schema asks only that
        # `meta.usage.pricingAsOf` be non-empty, so a string of spaces validates
        # and `_usage_line` below printed "rates as of" followed by nothing - a
        # basis with no content, beside a cost figure the budget preflight acts
        # on. A whitespace-only setting is a typo, not a declaration, so it
        # collapses to the shape absence already has and the line says "rates
        # undated" instead. `isinstance` guards a hand-edited number, and the
        # same trim is what `panel/_panel_paths._declared_as_of` applies to the
        # config file's copy of this key.
        as_of_raw = meta_usage.get("pricingAsOf") \
            if isinstance(meta_usage, dict) else None
        return {
            "ledgerDir": ledger_dir,
            "pricingAsOf": (as_of_raw.strip() or None)
            if isinstance(as_of_raw, str) else None,
            "showCost": bool(meta_usage.get("showCost", True))
            if isinstance(meta_usage, dict) else True,
            "totals": total,
            "byPhase": {k: {"tokens": v["tokens"], "costUSD": v["costUSD"],
                            "msgs": v["msgs"]} for k, v in by_phase.items()},
            "byModel": {k: {"tokens": v["tokens"], "costUSD": v["costUSD"],
                            "msgs": v["msgs"]}
                        for k, v in ul.aggregate(rows, "model").items()},
            "byAuthor": {k: {"tokens": v["tokens"], "costUSD": v["costUSD"],
                             "msgs": v["msgs"]}
                         for k, v in ul.aggregate(rows, "author").items()},
            # `phase_budgets` is reused verbatim, not re-derived: it already returns
            # spent/budget/pct/over per phase and encodes the rule that 0, negative,
            # boolean and non-numeric all mean "no budget" rather than a budget of
            # zero. Re-implementing that here is how the three existing copies of it
            # would become four.
            "budgets": ul.phase_budgets(manifest, rows),
        }
    except Exception:
        return None


# --- discovery (--json --discovery only) ----------------------------------------
# The init/task suggestion helper (v0.38 B): ONE mechanical source for "which
# skills/agents exist here", so commands/init.md step 6.1 and commands/task.md's
# skills step offer real names from a payload instead of each scanning the
# filesystem in prose. Opt-in behind --discovery because the bare --json payload
# is a pinned machine surface (selftest dv1); the import is lazy AND inside the
# try so a broken discovery module can never take down the status/gate surface
# it merely enriches.

# Mirrors _panel_discovery._entry's own description cap; re-applied here so THIS
# payload's bound does not silently follow a future discovery-side change.
DISCOVERY_DESC_CAP = 280


def discovery_block(project, home=None):
    """{"skills": [{name, description, source}], "agents": [...]} for `project`.

    Rows come from _panel_discovery.discover (the panel's own scan: project
    .claude/, user ~/.claude/, installed plugins, this repo's plugins tree)
    trimmed to the three keys a suggestion needs -- `path` is dropped on
    purpose: an absolute path is machine-specific noise in a payload meant to
    be read back as names. Descriptions are clipped to DISCOVERY_DESC_CAP, the
    same cap discovery itself applies at ingest. An empty inventory is empty
    lists, never an error; ANY failure is {"skills": [], "agents": [],
    "error": "<one line>"} -- fail-open, because a status surface must keep
    answering when an enrichment cannot."""
    try:
        import _panel_discovery
        found = _panel_discovery.discover(project, home=home) or {}

        def rows(kind):
            out = []
            for e in found.get(kind) or []:
                if isinstance(e, dict):
                    out.append({
                        "name": e.get("name"),
                        "description": (e.get("description")
                                        or "")[:DISCOVERY_DESC_CAP],
                        "source": e.get("source"),
                    })
            return out

        return {"skills": rows("skills"), "agents": rows("agents")}
    except Exception as exc:
        msg = " ".join(("%s: %s" % (type(exc).__name__, exc)).split())
        return {"skills": [], "agents": [],
                "error": (msg or type(exc).__name__)[:200]}


# --- human rendering ------------------------------------------------------------
# `_marker` and the layout below are the vocabulary commands/status.md used to hand
# to the model as prose. Moving it here is the same move commands/usage.md already
# made for itself: a status command that spends tokens re-tabulating a rollup it was
# just handed is paying twice for one answer, and the layout comes out different
# every run. The model reads nothing here — this renders from the manifest that is
# already loaded in this process, so nothing is re-read either.
_MARKERS = {"done": "[x]", "in_progress": "[~]", "blocked": "[!]",
            "pending": "[ ]", "cancelled": "[-]"}


def _marker(status):
    return _MARKERS.get(status, "[?]")


def _short(sha):
    s = str(sha or "")
    return s[:7] if s else "-"


def render_status(manifest, summary, width=18, only_phase=None, pt=None):
    """Plain-ASCII status report. Printed verbatim by /audit:status.

    Pure ASCII, no ANSI, no box-drawing — the same constraint audit-usage.py's
    selftest enforces on its own output, so this reads in any terminal. `pt` is
    a _cli_fmt.Painter; None (every pre-color caller) means plain, and a
    disabled painter returns its input unchanged, so plain mode stays
    byte-identical to the pre-color render.

    Every block is a `_*_lines()` helper returning its own list, in print order.
    Three of them used to be written out inline here — the header, the phase
    table and READY NOW — which made this function four times the length of any
    block it sits beside and hid that they are all the same kind of thing.
    """
    pt = pt or _cli_fmt.PLAIN
    lines = _header_lines(manifest, summary, width, pt=pt)
    lines += _phase_table_lines(manifest, summary, only_phase)
    lines += _ready_lines(manifest, summary, pt=pt)
    lines += _area_lines(summary, pt=pt)
    lines += _bug_lines(manifest, summary, pt=pt)
    lines += _proposal_lines(manifest, summary, pt=pt)
    lines += _resumable_lines(manifest, summary, pt=pt)
    return "\n".join(lines)


def _header_lines(manifest, summary, width=18, pt=None):
    """Who this plan is, the whole-plan bar, and every notice that qualifies it.

    The notices sit here rather than in their own blocks because each one is a
    caveat ON the bar directly above it: an invalid manifest means the counts are
    not to be trusted, a plan with no phases but parked proposals is not the
    "nothing to do" the bar reads as, and the usage/budget lines are what the
    same numbers cost."""
    pt = pt or _cli_fmt.PLAIN
    meta = (manifest or {}).get("meta") or {}
    out = [pt.paint("AUDIT  %s   repo %s"
                    % (meta.get("title") or "audit", meta.get("repo") or "-"),
                    "header"), ""]

    t_total = summary["tasks"]["total"]
    t_done = summary["tasks"]["byStatus"].get("done", 0)
    ph_done = sum(1 for p in summary["phases"] if p.get("status") == "done")
    bugs = summary["bugs"]
    # The same problem at the top of the page: `0/10 tasks done` over a plan
    # whose remainder includes dropped work is a denominator nobody can reach.
    # Read off `byStatus`, which is where the plan-wide figure already lives.
    t_cancelled = summary["tasks"]["byStatus"].get("cancelled", 0)
    out.append("  %s  %d/%d tasks done%s - %d/%d phases signed off - "
               "%d open bug(s) - %d ready now"
               % (_fmt.fmt_bar(t_done, t_total, width), t_done, t_total,
                  (" (%d cancelled)" % t_cancelled) if t_cancelled else "",
                  ph_done, len(summary["phases"]), bugs["open"],
                  len(summary["ready"])))
    if not summary["valid"]:
        out.append(pt.paint(
            "  INVALID MANIFEST: %d validator finding(s) - fix before "
            "running a phase" % summary["findings"], "finding"))
    # A park-all /audit:init leaves a valid plan with zero phases. Without this
    # line that plan reads as "nothing to do" on the one surface everyone
    # checks first, when the actual state is "everything is waiting for you".
    props_sum = summary.get("proposals") or {}
    if not summary["phases"] and props_sum.get("parked"):
        out.append(pt.paint("  empty plan - %d parked proposal(s) waiting: "
                            "/audit:propose list" % props_sum["parked"],
                            "warn"))

    usage = summary.get("usage")
    if usage:
        out.append("  " + _usage_line(summary, usage))
        out += _budget_lines(summary, usage, pt=pt)
    return out


def _phase_table_lines(manifest, summary, only_phase=None):
    """The phase-by-phase table: one header row, then a block per phase.

    Column widths are computed across EVERY task, then the header is printed
    once. Per-phase tables re-printed their own header and re-derived their own
    widths, so a fifty-phase manifest produced fifty header rows and fifty
    different alignments — the columns stopped being columns. That shared
    `widths` is why `fmt_row` is a closure, and why this block is one function:
    the rows and the measurement of the rows cannot be separated.

    `only_phase` scopes only which phases are LISTED. The overall line, the usage
    line and the bug counts stay whole-plan on purpose (they are `_header_lines`'
    business): a phase view that silently rescoped the totals would misreport the
    project, so the scope note says so where the scoping happens.
    """
    unmet = unmet_refs(manifest)
    ready = set(summary["ready"])
    by_id = {p.get("id"): p for p in (manifest.get("phases") or [])
             if isinstance(p, dict)}
    shown_phases = [p for p in summary["phases"]
                    if not only_phase or p.get("id") == only_phase]
    out = []
    if only_phase:
        out.append("  scoped to phase %s - totals above are whole-plan"
                   % only_phase)

    all_rows = {}
    for pe in shown_phases:
        ph = by_id.get(pe.get("id")) or {}
        rows = []
        for t in (ph.get("tasks") or []):
            if not isinstance(t, dict):
                continue
            tid = t.get("id") or "?"
            rows.append([
                "%s %s" % (_marker(t.get("status")), tid),
                _clip(_one_line(t.get("title")), 44),
                _theme.label(t.get("status")) or "?",
                t.get("model") or "-",
                _clip(", ".join(unmet.get(tid, [])) or "-", 26),
                _short(t.get("commit")),
                "READY" if tid in ready else "",
            ])
        all_rows[pe.get("id")] = rows

    cols = ("task", "title", "status", "model", "waiting on", "commit", "")
    widths = [len(c) for c in cols]
    for rows in all_rows.values():
        for r in rows:
            for i, cell in enumerate(r):
                widths[i] = max(widths[i], len(cell))

    def fmt_row(cells):
        return "     " + "  ".join("%-*s" % (widths[i], cells[i])
                                   for i in range(len(cols))).rstrip()

    out.append("")
    out.append(fmt_row(list(cols)))

    for pe in shown_phases:
        out.append("")
        pdone, ptotal = pe.get("done", 0), pe.get("total", 0)
        ph = by_id.get(pe.get("id")) or {}
        head = "  %-4s %-26s %-11s %s %d/%d" % (
            pe.get("id") or "?", _clip(pe.get("title") or "", 26),
            _theme.label(pe.get("status")) or "?",
            _fmt.fmt_bar(pdone, ptotal, 12), pdone, ptotal)
        # F192. THE DENOMINATOR NEEDS ITS SENTENCE. `cancelled` is counted
        # separately and never folded into `done` - `rollup`'s comment is right
        # that a bar reading 5/5 for three landed tasks and two dropped ones would
        # be a lie in the one direction that matters. But `0/5` over four runnable
        # tasks is a total that can never be reached, and the report already prints
        # the count while this surface withheld it: one plan, two surfaces, and
        # only one of them told the reader which facts they needed.
        #
        # NON-ZERO ONLY, and that is the one case where silence and zero say the
        # same thing. `(0 cancelled)` on every phase is noise.
        if pe.get("cancelled"):
            head += "  (%d cancelled)" % pe["cancelled"]
        # The badge, off the rollup's already-resolved tier rather than the raw
        # field: an invalid `priority` orders nothing, and a badge rendered from
        # the raw value would advertise a pin the run does not honour. The table
        # itself stays in MANIFEST order - the written plan is the plan, and
        # priority is an overlay on which of its READY tasks runs first.
        if pe.get("priority") is not None:
            head += "  prio %d" % pe["priority"]
        if ph.get("branch"):
            head += "  %s" % ph["branch"]
        out.append(head)
        if pe.get("desiredOutcome"):
            out.append("       desired: %s"
                       % _clip(_one_line(pe["desiredOutcome"]), 88))
        scope = _scope_line(manifest, ph, pe)
        if scope:
            out.append(scope)
        if pe.get("id") in unmet and ph.get("status") != "done":
            out.append("       blocked by: %s"
                       % _clip(", ".join(unmet[pe["id"]]), 70))
        for r in all_rows.get(pe.get("id")) or []:
            out.append(fmt_row(r))
    return out


def _ready_lines(manifest, summary, pt=None):
    """READY NOW — what can be started right this second, and how many there are.

    A wide-open plan can have hundreds of ready tasks, and a 464-line list is a
    list nobody reads. Fold it, and SAY the count — a silent cap would read as
    "that is all of them", which is the worse failure. The empty case is a
    sentence rather than an absent heading, because "nothing is ready" and "this
    surface forgot to say" must not look the same."""
    pt = pt or _cli_fmt.PLAIN
    out = [""]
    ready_list = summary["ready"]
    # The same sentence the panel and both reports print, from the same key. A
    # phase pinned first that its own dependencies will not let through is
    # SKIPPED, and a silent skip reads as "the plan is being followed" - which
    # is the failure this whole block already exists to refuse one line down.
    # It prints in the empty case too: "nothing is ready" and "the phase you
    # pinned is blocked" are different news.
    pnote = summary.get("priorityNote")
    if not ready_list:
        out.append(pt.paint("  READY NOW  nothing - every pending task is "
                            "waiting on something, or the plan is complete",
                            "header"))
        if pnote:
            out.append("    note: %s" % pnote)
        return out
    shown = ready_list[:READY_LIST_MAX]
    out.append(pt.paint("  READY NOW  %d task(s)%s"
                        % (len(ready_list),
                           "" if len(shown) == len(ready_list)
                           else ", first %d shown" % len(shown)),
                        "header"))
    if pnote:
        out.append("    note: %s" % pnote)
    task_by_id = _mio.tasks_by_id(manifest)
    for tid in shown:
        t = task_by_id.get(tid) or {}
        out.append("    %-9s %-44s %-7s run: /audit:run %s"
                   % (tid, _clip(_one_line(t.get("title")), 44),
                      t.get("model") or "-", tid))
    if len(shown) < len(ready_list):
        out.append("    ... and %d more - /audit:next runs the first in order"
                   % (len(ready_list) - len(shown)))
    return out


def _scope_line(manifest, phase, entry):
    """`area: api, security   review: backend-review (area api)` — or nothing.

    Two facts that were computable and never shown. The area tags existed since
    v0.16 and appeared only in the report and the panel, so the terminal — the
    surface an orchestrator run actually watches — could not tell you which part of
    a monorepo a phase belonged to. And the review skill was resolvable but never
    resolved: a reader had to check the phase, then the registry, then meta, to
    learn who signs this phase off.

    The BASIS is printed with the answer. A reviewer chosen three levels away is
    otherwise a reviewer nobody can explain, and "backend-review" alone gives no
    hint about which of the three files to edit to change it.

    Nothing is printed when there is nothing to say — no tags and no reviewer is
    the ordinary single-app repo, and a line saying so on every phase would be
    this feature charging every project for a monorepo it does not have.
    """
    parts = []
    tags = (entry or {}).get("area") or areas_of((phase or {}).get("area"))
    if tags:
        parts.append("area: %s" % _clip(", ".join(tags), 44))
    skill, basis = _areas.resolve_review_skill(manifest, phase)
    if skill:
        parts.append("review: %s (%s)" % (_clip(skill, 40), basis))
    return "       " + "   ".join(parts) if parts else ""


def _one_line(text):
    return " ".join(str(text or "").split())


def _clip(text, limit):
    """Truncate with a visible marker, and never mid-word if a word boundary is
    close. A bare slice produced rows like 'Fix BUG-3: cart total off-by-one with st',
    which reads as corruption rather than as elision."""
    s = str(text or "")
    if len(s) <= limit:
        return s
    cut = s[:limit - 3]
    space = cut.rfind(" ")
    if space >= limit - 14:          # only back up to a word break if it is near
        cut = cut[:space]
    return cut.rstrip(" ,;:") + "..."


def _usage_line(summary, usage):
    """`usage: <tokens> tok - ~$<cost> equiv - this phase <tokens>`.

    The cost clause is dropped when `showCost` is false, because naming dollars
    would leak exactly what that setting exists to hide. The phase clause is
    dropped when nothing is running, because there is no phase to attribute to."""
    totals = usage.get("totals") or {}
    parts = ["usage: %s tok" % _fmt.fmt_tokens(totals.get("tokens"))]
    if usage.get("showCost"):
        parts.append("~%s equiv" % _fmt.fmt_cost(totals.get("costUSD")))
    running = [p.get("id") for p in summary["phases"]
               if p.get("status") == "in_progress"]
    if running:
        per = (usage.get("byPhase") or {}).get(running[0]) or {}
        if per:
            parts.append("this phase %s" % _fmt.fmt_tokens(per.get("tokens")))
    # The rate table behind this cost AND behind the budget lines under it, which
    # is why it belongs here rather than only in the report: those percentages are
    # what the preflight budget check acts on, and a number that can stop a phase
    # should say what priced it. No fallback to the default table's date — see
    # render-report._usage_context; manufacturing a basis is worse than stating
    # that the manifest declared none.
    if usage.get("showCost") and (totals.get("tokens") or 0):
        parts.append("rates as of %s" % usage["pricingAsOf"]
                     if usage.get("pricingAsOf")
                     else "rates undated (set usage.pricingAsOf)")
    return " - ".join(parts)


def _budget_lines(summary, usage, pt=None):
    """Budget lines, and only for phases that actually declare one.

    Renders nothing when no phase carries a `budgetUSD`, which is the common case —
    an empty "0 of 0" frame would be worse than silence, the same call
    `_budget_block` makes in the HTML report. Phases without a budget are counted in
    a footnote rather than drawn at 0%: an unbudgeted phase is not a phase at zero."""
    if not usage.get("showCost"):
        return []                       # a budget is a money claim; honour the setting
    budgets = usage.get("budgets") or {}
    rows = [p for p in (budgets.get("phases") or []) if p.get("budget")]
    if not rows:
        return []
    pt = pt or _cli_fmt.PLAIN
    out = []
    for p in sorted(rows, key=lambda x: -(x.get("pct") or 0)):
        pct = p.get("pct") or 0.0
        flag = ""
        if pct >= 100.0:
            flag = "  " + pt.paint("OVER", "finding")
        elif pct >= BUDGET_WARN_PCT:
            flag = "  " + pt.paint("WARN", "warn")
        # `pct` is ALREADY a percentage, so the whole is a literal 100 — a
        # percentage is a hundred-cell bar. bar_cells' clamp is what keeps an
        # over-budget phase (470%) inside its own bracket.
        out.append("  budget %-5s %s %3.0f%%  %s of %s%s"
                   % (p.get("id") or "?", _fmt.fmt_bar(pct, 100, 12), pct,
                      _fmt.fmt_cost(p.get("spent")), _fmt.fmt_cost(p.get("budget")),
                      flag))
    unbudgeted = len(budgets.get("phases") or []) - len(rows)
    if unbudgeted:
        out.append("  budget       %d phase(s) declare none - not shown, and not "
                   "phases at zero" % unbudgeted)
    return out


def _area_lines(summary, pt=None):
    """`BY AREA` — the per-area rollup, printed instead of only shipped in --json.

    `summary["areas"]` has been computed (and carried in --json) since the tags
    existed; this renders THAT block rather than re-deriving it, so the terminal
    and the machine can never disagree. Nothing is printed when no phase carries
    a tag — the ordinary single-app repo pays nothing for this, the same call
    `_scope_line` makes.

    The `untagged` footer keeps the columns honest: without it, phases carrying
    no tag would silently vanish from the one grouping a monorepo reader trusts.
    And the multi-tag caveat is stated only when a phase actually carries more
    than one tag — a phase tagged with N areas counts its tasks under each of
    the N, so the per-area column can sum past the plan total, and a reader who
    adds the column up deserves to be told why. A single-tag project has nothing
    to be warned about, so it is not."""
    areas = summary.get("areas") or {}
    if not areas:
        return []
    pt = pt or _cli_fmt.PLAIN
    phases = [p for p in (summary.get("phases") or []) if isinstance(p, dict)]
    untagged = [p for p in phases if not p.get("area")]
    rows = [(tag, g.get("phases", 0), g.get("done", 0), g.get("total", 0),
             g.get("owner"), g.get("cancelled", 0))
            for tag, g in sorted(areas.items())]
    if untagged:
        rows.append(("untagged", len(untagged),
                     sum(p.get("done", 0) for p in untagged),
                     sum(p.get("total", 0) for p in untagged), None,
                     sum(p.get("cancelled", 0) for p in untagged)))
    # The cross-cutting blind spot (v0.37 B3), said HERE and said ONCE. The
    # surface was a choice among three: the VALIDATOR would print a line per
    # untagged phase (a wall on a plan where untagged is common and perfectly
    # legal), a PANEL per-phase-row note repeats itself fifty times at fifty
    # phases, and this rollup is the one place a reader is already comparing
    # tags against phases - directly under the untagged row it explains.
    # Aggregated by construction (one line however many phases), and gated on
    # the registry existing: with no meta.areas there are no defaults to miss.
    advisory = bool(untagged) and bool(summary.get("areasRegistered"))
    out = ["", pt.paint("  BY AREA  %d tag(s) - %d of %d phase(s) tagged"
                        % (len(areas), len(phases) - len(untagged),
                           len(phases)), "header")]
    w = max(len(r[0]) for r in rows)
    for tag, n_ph, done, total, owner, cancelled in rows:
        line = ("    %-*s  %2d phase(s)  %s %d/%d tasks%s"
                % (w, tag, n_ph, _fmt.fmt_bar(done, total, 12), done, total,
                   (" (%d cancelled)" % cancelled) if cancelled else ""))
        if owner:
            # The advisory owner, from the same rollup --json ships - the
            # person to coordinate with, never an assignee.
            line += " - %s" % owner
        out.append(line)
    if advisory:
        out.append("    note: area defaults (skills, reviewer, owner) do not "
                   "apply to untagged phases - tag them, or leave them out of "
                   "the areas system on purpose")
    if any(len(p.get("area") or []) > 1 for p in phases):
        out.append("    note: a phase with several tags counts under each - "
                   "per-area sums can exceed the plan total")
    return out


def _bug_lines(manifest, summary, pt=None):
    bugs = [b for b in ((manifest or {}).get("bugs") or []) if isinstance(b, dict)]
    if not bugs:
        return []
    pt = pt or _cli_fmt.PLAIN
    # `_mio.tasks_by_id` drops a task with no id, where the index built here used
    # to key it under `None`. That is the shape `_manifest_io.effective_bug_status`
    # documents as the hazard it guards against — a bug with no `taskId` matching
    # the `None` key and reading 'fixed'. The guard still stands; the hazard it
    # guards against no longer reaches it from this file.
    tasks = _mio.tasks_by_id(manifest)
    ready = set(summary["ready"])
    out = ["", pt.paint("  BUGS  %d total - %d open (%d high severity)"
                        % (summary["bugs"]["total"], summary["bugs"]["open"],
                           summary["bugs"]["openHighSeverity"]), "header")]
    for b in bugs:
        eff = effective_bug_status(b, tasks)
        if eff in CLOSED_BUG:
            continue
        flag = ""
        if b.get("taskId") in ready:
            flag = "   its fix is READY: /audit:run %s" % b["taskId"]
        out.append("    %-8s %-11s %-5s %s%s"
                   % (b.get("id") or "?", _theme.label(eff) or "?",
                      b.get("severity") or "-",
                      _one_line(b.get("title"))[:44], flag))
    return out


def _proposal_lines(manifest, summary, pt=None):
    """Parked proposals — phases synthesized by /audit:init but not materialized.

    Listed only while parked (status 'proposed'): a materialized proposal is
    already visible as its phase, and a dropped one is history. A payload-bearing
    row carries the copy-pasteable materialize command; a legacy free-form entry
    (no payload) is listed without one — there is nothing to materialize.

    A status OUTSIDE that vocabulary (hand-written or older-init entries carry
    things like "open") is neither parked nor history — it used to be silently
    invisible here, which is the one failure a status surface must not have.
    Such entries are counted in a legacy footer that points at
    /audit:propose list, which reads them in full. The validator stays tolerant
    of them on purpose; counting is this surface's job, judging is not.

    THE ROWS COME FROM `_proposals.proposal_rows` AND THE CLASSIFICATION FROM
    THE RAW STATUS (F93). This block used to walk `proposals[]` itself and
    compose the reserved cell itself, which made it the third spelling of a
    string two other surfaces already print. Routing it NAIVELY would have
    changed what it reports, and that is the thing the fault turned on:
    `proposal_rows` normalises a MISSING status to `proposed`, so an entry
    carrying none would have moved out of the legacy footer and into the parked
    list -- a status surface inventing a status is exactly the failure the
    paragraph above is about. So the rows carry both readings and this block
    reads `statusRaw`/`statusKnown`, which is the same classification it always
    made, from a derivation it no longer owns."""
    rows = _proposals.proposal_rows(manifest or {})
    # `_status_facts.is_parked_proposal`, not `== "proposed"` spelled again here:
    # the rollup that feeds the header line above asks the same question, and the
    # two used to answer it differently — see that function for what `parked`
    # means and why the payload is not part of it.
    parked = [r for r in rows if _status_facts.is_parked_proposal(r["statusRaw"])]
    legacy = [r for r in rows if not r["statusKnown"]]
    if not parked and not legacy:
        return []
    pt = pt or _cli_fmt.PLAIN
    sp = summary.get("proposals") or {}
    out = ["", pt.paint("  PROPOSALS  %d total - %d parked"
                        % (sp.get("total", len(rows)), len(parked)),
                        "header")]
    for r in parked:
        row = "    %-16s %-14s %s" % (
            r["id"] or "?", _proposals.reserved_cell(r),
            _clip(_one_line(r["name"] or r["id"]), 40))
        if r["hasPayload"]:
            row += "   materialize: /audit:propose materialize %s" % (r["id"] or "?")
        out.append(row)
    if legacy:
        out.append("    +%d legacy proposal(s) (free-form) - /audit:propose list"
                   % len(legacy))
    return out


def _resumable_lines(manifest, summary, pt=None):
    """Flag an interrupted run, which is the one state a reader must not miss."""
    pt = pt or _cli_fmt.PLAIN
    for p in ((manifest or {}).get("phases") or []):
        if not isinstance(p, dict):
            continue
        running_tasks = [t for t in (p.get("tasks") or [])
                         if isinstance(t, dict) and t.get("status") == "in_progress"]
        if p.get("status") == "in_progress" or running_tasks:
            where = " on %s" % p["branch"] if p.get("branch") else ""
            return ["", pt.paint(
                "  RESUMABLE  phase %s is %s%s - interrupted? "
                "run /audit:resume"
                % (p.get("id") or "?",
                   (_theme.label("in_progress") or "in progress").lower(),
                   where), "warn")]
    return []


# `_load_usage_fmt()` used to sit here: a runtime load of audit-usage.py — an ENTRY
# POINT, a peer at layer 7 — purely to borrow its `bar()`. The share bar now lives in
# _fmt (`fmt_bar`/`bar_cells`), which this file already imports for fmt_tokens/fmt_cost,
# so the four call sites take the same downward edge as everything else and the loader
# has nothing left to load. Its entry in _deps.KNOWN_LAYER_DEBT went with it — that
# list may only shrink, and only deliberately.


# --- the CLI ---------------------------------------------------------------------
# The one-line meaning of each `--fail-on` condition, keyed by the SAME tuple the
# gate evaluates (`_status_facts.CONDITIONS`). It is a dict rather than prose so
# `--help` can render it and a case can compare its keys against `CONDITIONS`: the
# names used to exist only in this file's docstring, unreachable from the
# command line, and a name added to `CONDITIONS` alone would have gone undocumented
# with nothing going red. `ap8`/`ap10` are what make that impossible now.
CONDITION_HELP = {
    "invalid": "the structural validator reports findings",
    "open-high-bugs": "high-or-worse severity bugs not yet fixed/wontfix "
                      "(high/critical/blocker/severe/fatal/urgent/sev0-1/s0-1/p0-1)",
    "open-bugs": "ANY bug not yet fixed/wontfix",
    "blocked-tasks": 'any task with status "blocked"',
    "in-progress": 'any phase or task "in_progress" (for release-freeze gates)',
    "over-budget": "a phase at or past 100% of its `budgetUSD`",
    "budget-80": "a phase at or past %g%% of its `budgetUSD`" % BUDGET_WARN_PCT,
    "invariant-breach": "a started phase breaks an orchestrator invariant "
                        "(scripts/governance/verify-invariants.py reads git, the "
                        "shard, the journal and the ledger; several git calls per "
                        "phase, so it is opt-in)",
}
# What `--help` says about a condition CONDITION_HELP has no entry for. It is a
# `.get` default rather than a KeyError because the caller is `--help`: a condition
# added to `CONDITIONS` alone must make the omission visible in the output someone
# is reading, not take the help screen down. Case `ap10` fails the build on it
# either way, so this is loud without being fatal.
UNDOCUMENTED = "(undocumented - add it to CONDITION_HELP)"


def _conditions_epilog():
    """Every condition name with its meaning, for `--help`.

    Rendered from CONDITIONS + CONDITION_HELP rather than typed, so the listing a
    user reads IS the list the gate evaluates."""
    lines = ["conditions for --fail-on (comma list; the --gate default is",
             "  %s):" % ",".join(DEFAULT_GATE)]
    width = max(len(c) for c in CONDITIONS)
    body = 2 + width + 2
    for cond in CONDITIONS:
        lines.append(textwrap.fill(
            CONDITION_HELP.get(cond, UNDOCUMENTED), width=78,
            initial_indent="  %-*s  " % (width, cond),
            subsequent_indent=" " * body))
    lines.append("")
    lines.append(textwrap.fill(
        "Neither budget condition is in the --gate default: spend is a signal, "
        "not a defect, and a phase at 105% of budget may be entirely justified. "
        "Opt in when a budget is a commitment.", width=78))
    lines.append("")
    lines.append(textwrap.fill(
        "exit codes: 0 pass | 1 gate failed | 2 usage error / unreadable "
        "manifest. Under --json, stdout is exactly one JSON document and the "
        "human GATE line goes to stderr - the verdict is already in the "
        "payload's `gate` key.", width=78))
    return "\n".join(lines)


def build_parser():
    """The argument parser, separated so a case can read the option table.

    `allow_abbrev=False` on purpose: the hand-rolled parser this replaced treated an
    abbreviation as an unknown argument, and argparse's default would have silently
    started accepting `--js` for `--json` - a widening nobody asked for."""
    p = argparse.ArgumentParser(
        prog="audit-status.py", add_help=True, allow_abbrev=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Headless status rollup + CI gate for the audit manifest.",
        epilog=_conditions_epilog())
    p.add_argument("manifest", help="path to the audit manifest (single-file or "
                                    "sharded index)")
    p.add_argument("--json", action="store_true", dest="as_json",
                   help="print the rollup as JSON instead of the human render")
    p.add_argument("--discovery", action="store_true",
                   help="with --json only: add a `discovery` block naming the "
                        "skills and agents this project can actually see")
    p.add_argument("--gate", action="store_true",
                   help="evaluate the fail conditions; exit 1 when any trips")
    p.add_argument("--fail-on", dest="fail_on", default=None, metavar="c1,c2,...",
                   help="override the gate conditions (see the list below)")
    # --phase <id>: scope the HUMAN render to one phase. /audit:phase and
    # /audit:next need a deterministic entry view; their per-task progress lines are
    # emitted as the work happens and cannot be pre-rendered, so this covers the
    # half that can be, rather than pretending to cover both.
    p.add_argument("--phase", default=None, metavar="ID",
                   help="scope the human render to one phase (totals stay "
                        "whole-plan)")
    # --color auto|always|never: ANSI for the human render only (--json and
    # --gate output stay plain). Resolution lives in _cli_fmt - the one place
    # CLI color lives.
    p.add_argument("--color", choices=list(_cli_fmt.MODES), default="auto",
                   help="ANSI color for the human render (auto colors only a TTY "
                        "and respects NO_COLOR; --json never colors)")
    # --submodules <.gitmodules path> [--git-root <prefix>]: preflight guard,
    # exits 1 when a task file lives inside a submodule. Standalone mode.
    p.add_argument("--submodules", default=None, metavar="GITMODULES",
                   help="standalone preflight: exit 1 when a task file lives "
                        "inside a submodule listed in this .gitmodules")
    p.add_argument("--git-root", dest="git_root", default="", metavar="PREFIX",
                   help="path prefix stripped from task files before the "
                        "--submodules comparison")
    return p


def main(argv):
    try:
        args = build_parser().parse_args(list(argv))
    except SystemExit as exc:
        # argparse EXITS the process on --help and on a usage error. This command
        # RETURNS its exit code - `__main__` hands it to sys.exit, and the cases in
        # tests/test_audit_status.py call main() in-process and compare against 0/1/2
        # - so the exit is converted here rather than escaping. argparse has already
        # written the help to stdout or the error to stderr.
        return exc.code if isinstance(exc.code, int) else 2
    want_json = args.as_json
    want_gate = args.gate
    want_discovery = args.discovery
    if want_discovery and not want_json:
        sys.stderr.write("usage: --discovery requires --json (it enriches the "
                         "machine payload only)\n")
        return 2

    gitmodules = args.submodules
    git_root_prefix = args.git_root or ""
    only_phase = args.phase
    pt = _cli_fmt.painter(args.color)

    conditions = list(DEFAULT_GATE)
    if args.fail_on is not None:
        conditions = [c.strip() for c in args.fail_on.split(",") if c.strip()]
        unknown = [c for c in conditions if c not in CONDITIONS]
        if unknown:
            sys.stderr.write("unknown condition(s): %s (known: %s)\n"
                             % (", ".join(unknown), ", ".join(CONDITIONS)))
            return 2

    manifest_path = args.manifest
    try:
        manifest = _mio.load_manifest(manifest_path)
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n" % (manifest_path, exc))
        return 2
    if not isinstance(manifest, dict):
        sys.stderr.write("ERROR: %s is not a JSON object (got %s)\n"
                         % (manifest_path, type(manifest).__name__))
        return 2

    if gitmodules is not None:
        # No `__MISSING__` sentinel branch any more: the hand-rolled `_extract_opt`
        # returned one when a flag was last on the line, and argparse answers that
        # case itself ("expected one argument", exit 2, measured). A branch nothing
        # can reach reads like a guard that is working.
        try:
            with open(gitmodules, "r", encoding="utf-8") as fh:
                sub_paths = parse_gitmodules(fh.read())
        except (FileNotFoundError, NotADirectoryError):
            sub_paths = []  # no .gitmodules => no submodules => clean
        except Exception as exc:
            sys.stderr.write("ERROR: cannot read %s: %s\n" % (gitmodules, exc))
            return 2
        conflicts = submodule_conflicts(manifest, sub_paths, git_root_prefix)
        if conflicts:
            for tid, f, sub in conflicts:
                print("SUBMODULE CONFLICT: task %s file '%s' is inside submodule '%s'"
                      % (tid, f, sub))
            print("\n%d task file(s) live inside a submodule — the orchestrator "
                  "cannot commit them from the parent repo. Point meta.gitRoot at "
                  "the submodule, or remove those files from the task(s)."
                  % len(conflicts))
            return 1
        print("OK: no task files inside submodules (%d submodule(s) checked)"
              % len(sub_paths))
        return 0

    vm = _load_validator()
    try:
        findings, warnings = vm.validate(manifest)
    except Exception as exc:  # defensive
        findings, warnings = ["internal validator error: %s" % exc], []

    summary = rollup(manifest, findings, warnings,
                     usage=usage_summary(manifest, manifest_path))

    if want_discovery:
        # CLAUDE_PROJECT_DIR is how Claude Code names the project on every
        # invocation it makes; a plain CLI run means "here". The manifest is NOT
        # the anchor on purpose - it may live under docs/audit/ while the skills
        # live at the project root.
        summary["discovery"] = discovery_block(
            os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())

    if want_gate and "invariant-breach" in conditions:
        # Computed HERE and injected, not inside the rollup. `_status_facts` is
        # layer 2 and `_invariants` is layer 4, so the gate cannot reach the
        # checks; and this costs several git calls per started phase, which no
        # `/audit:status` that was not asked for it should pay.
        summary["invariants"] = invariants_block(manifest, manifest_path)

    if want_gate:
        failed = evaluate_gate(summary, conditions)
        summary["gate"] = {
            "conditions": conditions,
            "failed": failed,
            "passed": [c for c in conditions if c not in failed],
        }

    if want_json:
        print(json.dumps(summary, indent=2))
    elif not want_gate:
        # A bare invocation now renders for a human. It used to print raw JSON and
        # leave commands/status.md telling the model how to lay it out, which cost
        # tokens on every call and produced a different layout each time — the exact
        # thing commands/usage.md refuses to do. `--json` is unchanged for machines.
        if only_phase:
            known = [p.get("id") for p in summary["phases"]]
            if only_phase not in known:
                sys.stderr.write("ERROR: no phase %r in %s (have: %s)\n"
                                 % (only_phase, manifest_path, ", ".join(
                                     str(k) for k in known)))
                return 2
        print(render_status(manifest, summary, only_phase=only_phase, pt=pt))

    if want_gate:
        # WHERE THE VERDICT GOES. The machine-readable verdict is already whole in
        # `summary["gate"]` (conditions/failed/passed) and in the exit code; these
        # lines are its HUMAN rendering. Printing them after the JSON put a trailing
        # sentence on the payload, so `--gate --json | jq` failed on "Extra data".
        # Under --json they go to stderr - a CI log still shows them, `jq` no longer
        # chokes, and nothing had to be duplicated into the payload to say it twice.
        # Without --json this is `print` unchanged: stdout is what CI has always
        # grepped, and moving it there too would break that for no gain.
        say = (lambda line: sys.stderr.write(line + "\n")) if want_json else print
        failed = summary["gate"]["failed"]
        if failed:
            for c in failed:
                detail = {
                    "invalid": "%d validator finding(s)" % summary["findings"],
                    "open-high-bugs": "%d open high-severity bug(s)"
                                      % summary["bugs"]["openHighSeverity"],
                    "open-bugs": "%d open bug(s)" % summary["bugs"]["open"],
                    "blocked-tasks": "%d blocked task(s)"
                                     % summary["tasks"]["byStatus"].get("blocked", 0),
                    "in-progress": "work in progress",
                    "over-budget": _budget_detail(summary, 100.0),
                    "budget-80": _budget_detail(summary, BUDGET_WARN_PCT),
                    "invariant-breach": _invariant_detail(summary),
                }.get(c, "")
                say("GATE FAILED: %s (%s)" % (c, detail))
            return 1
        say("GATE PASSED: %s" % ", ".join(conditions))
    return 0


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv:
        # Answers rather than falling through to `main`, which would read the flag
        # as a manifest path. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("audit-status.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_audit_status.py - run that file instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
