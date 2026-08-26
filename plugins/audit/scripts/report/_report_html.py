#!/usr/bin/env python3
"""
HTML fragment builders for the audit report: escaping, chips/badges, table
cells and the filter panel — stdlib only.

Moved out of render-report.py (P13.1). This is pure markup generation over
already-computed values: given a task, a bug, a phase or a manifest, each
function returns an HTML string. None of it decides layout, none of it reads
usage data, none of it renders the whole document — that stays in
render-report's `render_html` / `render_md`, which call these dozens of times
each and glue the fragments into the page.

Every manifest value that reaches these functions is untrusted input (the
manifest is user-authored JSON) and is escaped through `e()` before it
reaches the page; `_safe_url` is the one gate a URL passes through before it
is allowed to become an `href`.

render-report.py keeps thin module-level aliases (`e = _report_html.e`,
`_chip = _report_html._chip`, etc.) so render_html/render_md and the
selftest's many direct references keep working unchanged.

This module must never import render-report or _report_usage: nothing that
imports THIS module (render-report does) can form a cycle through it. It may
use layer 1 — `_ui_theme` for status/label vocabulary (same as the panel),
`_areas` for tag derivation, and `_manifest_io` for reading a manifest's
shape, which is where the id -> task index and the derived bug status live so
this file and the layer-7 commands cannot drift apart.

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test__report_html.py`, byte-identical labels and all - see
`plugins/audit/tests/_harness.py`.
"""
import html
import os
import time
import sys

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

import _ui_theme as _theme  # noqa: E402  (tokens + labels shared with the panel)
import _areas  # noqa: E402  (one home for tag derivation; stdlib-only, no cycle)
import _manifest_io  # noqa: E402  (one home for reading a manifest's shape)
import _priority  # noqa: E402  (what a valid tier is - one answer, shared with the CLI)


# Chip and pipeline-rail colors live in the report's CSS theme tokens (see
# render-report's _CSS), keyed off the `data-status` / `data-risk` attributes
# the markup carries — so a single token set themes every status/risk
# consistently in both light and dark. Risk chips render only for these
# levels:
_RISK_LEVELS = ("low", "med", "high")


# --- escaping + basename ----------------------------------------------------
def stamp_time():
    """The generation stamp, honouring SOURCE_DATE_EPOCH.

    Lives HERE because both renderers stamp, and both import this module.
    The first version of this put it in `_report_page` and fixed the HTML
    only -- the Markdown twin went on stamping wall-clock, so the freshness
    check that motivated the whole change stayed red on the `.md`. Fixing
    one of two call sites is the instance-not-class mistake this repo keeps
    paying for; one definition is what stops the third copy appearing.

    Without this the report stamps wall-clock and is UNREPRODUCIBLE BY
    CONSTRUCTION, which is not a cosmetic problem: it is why nothing could ever
    compare a COMMITTED artifact against a fresh render. `examples/acme-store`
    drifted for exactly that reason -- it kept the pre-F28 `aria-label`s, the
    ones a speech user cannot reach, long after the source was fixed, and CI
    rendered its own copy to a temp directory and grepped that instead.

    SOURCE_DATE_EPOCH is the reproducible-builds convention rather than a local
    invention, so anything that already sets it gets a deterministic report for
    free. A value that is not an integer is IGNORED rather than fatal: this is
    an advisory path (a stamp), and a malformed environment variable must not
    stop a user rendering their report. It is the freshness check's job to fail
    loudly, and it sets the variable itself.
    """
    raw = os.environ.get("SOURCE_DATE_EPOCH")
    if raw:
        try:
            return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(int(raw)))
        except (TypeError, ValueError, OSError, OverflowError):
            pass
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())


def e(value):
    """Escape ANY manifest value for HTML context."""
    return html.escape(str(value if value is not None else ""), quote=True)


def _safe_url(url):
    """Return the url only when it is plain http(s) — else None (render as text)."""
    u = str(url or "")
    return u if u.startswith(("https://", "http://")) else None


def _report_basename(meta, cli_value):
    """Resolve the report file basename: --basename › meta.reportBasename ›
    'audit-report'. Sanitized to a bare filename ([A-Za-z0-9-_], no path
    separators / extension) so it can't escape --out-dir or break the download."""
    raw = cli_value if cli_value else (
        meta.get("reportBasename") if isinstance(meta, dict) else None)
    name = os.path.basename(str(raw or "").strip())          # drop any dir parts
    for ext in (".html", ".md"):                             # tolerate a given ext
        if name.lower().endswith(ext):
            name = name[: -len(ext)]
    name = "".join(c for c in name if c.isalnum() or c in "-_")
    return name or "audit-report"


# --- lookups ----------------------------------------------------------------
# The id -> task index. One implementation, in `_manifest_io`, the same one
# audit-status and the panel reach for. The local copy this alias replaced agreed
# with it on every manifest a validator would accept — same falsy-id filter, same
# LAST-wins duplicate rule, same tolerance of a non-dict phase or task — and
# disagreed on exactly one input: a JSON document whose ROOT is not an object
# survives `load_manifest` unchanged, and the copy raised AttributeError on it
# where the shared one returns {}. render-report would have crashed rather than
# rendered an empty report; a lookup is not the right place to discover that, and
# `validate-manifest` is the reader that names it.
_tasks_by_id = _manifest_io.tasks_by_id


# A phase's `area` -> its tags. One implementation, in `_areas`, the same one the
# panel and audit-status alias. This file carried a COPY that predated the trim and
# the de-duplication, so `"area": ["api","api"]` drew two chips in the HTML report
# and one on every other surface — the report was the last reader of the pre-fix
# six lines. A copy is not shared code; the alias is.
_areas_of = _areas.areas_of


# --- advisory area owners (D4, v0.36) ----------------------------------------
def _owner_map(manifest):
    """{tag: owner} for every registered area declaring a non-null string owner.

    The same filter _panel_state.usage_state ships to the panel: an explicit
    `owner: null` ("nobody owns this") and an undeclared owner read the same to
    a surface that only displays, and a non-string owner is the validator's
    finding, not this map's problem. Fail-soft to {} — the report renders from
    manifests the validator has only warned about."""
    try:
        out = {}
        for tag, entry in _areas.registry(manifest).items():
            o = entry.get("owner")
            if isinstance(o, str) and o.strip():
                out[tag] = o.strip()
        return out
    except Exception:
        return {}


def _area_tag_span(tag, owners):
    """One area tag chip, wearing its advisory owner when one is registered.

    The suffix is display, not assignment — the same claim the manifest makes,
    no more — and the title spells it the way the panel's area select already
    does (`owner: <who>`), so the two surfaces teach one habit. A tag with no
    owner emits EXACTLY the bytes it always did; the bare shape is pinned by
    name in the rd2/ready selftests and must not grow an empty suffix."""
    own = (owners or {}).get(tag)
    if not own:
        return '<span class="area-tag">%s</span>' % e(tag)
    return ('<span class="area-tag" title="owner: %s">%s'
            '<span class="aown"> — %s</span></span>'
            % (e(own), e(tag), e(own)))


# --- segments (D1, v0.36) -----------------------------------------------------
# The order the segments render in: the work in motion first, then the queue,
# then the archive. A dict, not an if-chain, so the emitter and the selftest
# read one table.
SEG_ORDER = ("active", "pending", "archived")
SEG_LABEL = {"active": "Active", "pending": "Pending", "archived": "Archived"}
# The two views a reader picks between, plus the escape hatch. `active` is the
# default and means "everything still to come or in hand" — active AND pending,
# because both are work nobody has finished.
VIEW_SEGS = {"active": ("active", "pending"),
             "archived": ("archived",),
             "all": SEG_ORDER}


def _seg_of(status):
    """Which segment a phase files under, from its ROLLED-UP status.

    in_progress and blocked are both "someone is (or should be) on this now";
    the archive holds both TERMINAL states — `done` (it landed) and `cancelled`
    (it will not be done) — because the question a reader asks of the top of
    this table is "what is left", and finished-by-dropping is finished.
    Everything else — pending, an unknown vocabulary value, a phase with no
    status at all — is work still to come. Unknowns land in pending on purpose:
    a segment that silently swallowed a typo'd status would hide the phase the
    validator is about to flag."""
    if status in ("done", "cancelled"):
        return "archived"
    if status in ("in_progress", "blocked"):
        return "active"
    return "pending"


# --- fragment builders ------------------------------------------------------
def _bug_view(b, task_by_id):
    """(status, fixedIn) for a bug row — the PRESENTATION half of the bug status.

    The rule itself is not decided here any more: `_manifest_io.effective_bug_status`
    owns it, and this is the wrapper that adds the `fixedIn` cell. That split is the
    point — the derivation had three homes (audit-status, the panel, this file, whose
    docstring said it "mirrored" audit-status) and layer 2 cannot import layer 7, so
    the copy was structural. The em dash stays HERE, deliberately: a placeholder is
    what a table draws when a cell is empty, and layer 1 has no table.

    Adopting the shared rule also picks up its falsy-`taskId` guard, which this file
    did not have: given an index built WITHOUT the truthy-id filter (audit-status's
    ready-list index is one), a bug carrying no `taskId` used to look up the `None`
    key, find a task, and read 'fixed'. Pinned by the cases below.
    """
    status = _manifest_io.effective_bug_status(b, task_by_id)
    # DECIDED, and it is the `x or default` shape the house rules single out, so it
    # is written down rather than left to the reader: an empty-string `fixedIn` means
    # "nothing recorded", NOT "recorded as empty". The field holds a commit-ish
    # reference and "" is not one — it is the shape a form or a hand edit leaves
    # behind, carrying no claim about where the fix landed. So it falls through to
    # the linked task's commit exactly as a missing key does; treating it as a
    # recorded value would print the placeholder beside a bug whose fix has a known
    # commit, which is less true, not more careful.
    recorded = b.get("fixedIn")
    if recorded:
        return status, recorded
    if status == "fixed":
        # The inner `done` check is not redundant with `status == "fixed"`: a bug can
        # carry a STORED 'fixed' while its linked task is still running, and that
        # task's commit is not the fix. The commit is borrowed only where the
        # derivation itself fired.
        tid = b.get("taskId")
        task = task_by_id.get(tid) if tid else None
        if isinstance(task, dict) and task.get("status") == "done":
            return status, (task.get("commit") or "—")
    return status, "—"


def _chip_buttons(statuses, attr, cls, humanize=True, titles=None, mapping=None):
    """Toggle buttons for a set of values — machine value in `attr`, words shown.

    `aria-pressed` is what makes a toggle's state readable; without it "which
    filter is on" is carried by colour alone.

    `humanize` is off for values that are IDENTIFIERS rather than vocabulary. A
    status is a word this product chose and should read as English; a model name
    is a string someone types into a manifest and reads back out of a bill, and
    running it through label() gave a chip reading "Opus" beside a table cell
    reading `opus` — two spellings of one value, in one table.

    `titles` (D4) maps a value to a native-tooltip string — the area chips use
    it to carry the advisory owner. A value without an entry emits EXACTLY the
    bytes it always did: the untitled shape is pinned by name in more than one
    selftest, and an empty title attribute would be a different chip.

    `mapping` is `_ui_theme.label`'s own second argument, forwarded rather than
    re-expressed: the test-evidence chips are humanised out of a vocabulary that
    is not the manifest's status set, and `label()` already takes the table to
    read. Omitted it is `None`, which is what `label()` gets today — so every
    existing caller emits the same bytes it always has.
    """
    return "".join(
        '<button type="button" class="%s" %s="%s"%s aria-pressed="false">%s</button>'
        % (cls, attr, e(s),
           (' title="%s"' % e((titles or {}).get(s))) if (titles or {}).get(s)
           else "",
           e(_theme.label(s, mapping) if humanize else s))
        for s in statuses)


def _chip(status):
    """A status badge: machine value in the attribute, words in the text.

    `in_progress` is a key — it sorts, compares and survives serialization — and
    it was being shown to people as-is, in the one place they look to find out how
    the work is going. The attribute keeps the key (the CSS themes off it and the
    filters compare it), the text says what it means.
    """
    return '<span class="chip" data-status="%s">%s</span>' % (
        e(status), e(_theme.label(status)))


def _ado_cell(item):
    ado = item.get("ado") if isinstance(item.get("ado"), dict) else None
    if not ado or ado.get("id") is None:
        return '<span class="muted">—</span>'
    label = "#%s" % e(ado.get("id"))
    url = _safe_url(ado.get("url"))
    if url:
        return '<a href="%s">%s</a>' % (e(url), label)
    return label


def _outcome_text(task):
    """One-line outcome (descriptive, else technical), truncated — for the table."""
    o = task.get("outcome") if isinstance(task.get("outcome"), dict) else {}
    txt = str(o.get("descriptive") or o.get("technical") or "").strip()
    return (txt[:70].rstrip() + "…") if len(txt) > 70 else txt


def _short_date(iso):
    """ISO timestamp -> its date part ('2026-06-28T10:00:00Z' -> '2026-06-28')."""
    s = str(iso or "")
    return s.split("T", 1)[0] if "T" in s else s


def _stamp(iso):
    """ISO timestamp -> 'YYYY-MM-DD HH:MM', the date part when there is no time.

    tm (F-P-4): the table showed the DATE a task finished and kept the clock in
    a tooltip. "Which of these two finished first" is the question this column
    is asked on a busy day, and the answer was a hover away - on paper, not
    available at all. The value is the manifest's own string, cut rather than
    parsed: these are UTC stamps written by the orchestrator, and re-formatting
    them through a local timezone here would silently move a completion across
    midnight in a file that is also read offline. The zone is named in the
    column header once, not repeated per row."""
    s = str(iso or "")
    if "T" not in s:
        return s
    day, rest = s.split("T", 1)
    return "%s %s" % (day, rest[:5]) if len(rest) >= 5 else day


def _timing_cell(task):
    """Compact completion date for the table, with the full started/completed
    timestamps on hover. Done -> completed date; started-but-not-done -> the
    started date (muted); neither -> em dash."""
    started, completed = task.get("startedAt"), task.get("completedAt")
    tip = e("started %s · completed %s" % (started or "—", completed or "—"))
    if completed:
        return '<span title="%s">%s</span>' % (tip, e(_stamp(completed)))
    if started:
        return ('<span class="muted" title="%s">started %s</span>'
                % (tip, e(_stamp(started))))
    return '<span class="muted">—</span>'


def _commit_cell(task):
    """The commit, with one press that copies the WHOLE sha (F-P-4).

    The column shows nine characters because a table cannot carry forty, and
    nine is not what `git cherry-pick` wants - so a reader who needed the sha
    was retyping it off a screenshot or opening the manifest. The button carries
    the full value in `data-copy`; report.js already owns the copy behaviour and
    its file:// fallback (clipboard.writeText is refused there, and that is
    where this report is most often opened), so this is the same control the run
    command uses, one cell down."""
    sha = str(task.get("commit") or "").strip()
    if not sha:
        return '<span class="muted">\u2014</span>'
    return ('<span class="shacell"><code>%s</code>'
            '<button type="button" class="btn-copy shacopy" data-copy="%s" '
            'title="Copy the full commit sha (%s)" '
            'aria-label="Copy the full commit sha">Copy</button></span>'
            % (e(sha[:9]), e(sha), e(sha)))


# --- test evidence: the status, and the observations BESIDE it ----------------
# A BADGE IS THE STATUS AND NOTHING ELSE. `run-test-gate.render` states the rule
# in its own comments and this is the reading half of it: a gate can fail AND
# rewrite the tree, and a single word cannot carry both - the reader who fixes
# the failure would meet the rewrite afterwards, in a commit. So the badge below
# says what the run ANSWERED, and every observation the run made is a separate
# mark rendered next to it. Two facts, two marks, never one.
#
# The key is the manifest's, spelled here rather than imported: `_evidence_io`
# owns the WRITING of it and is a layer-mate of this file, which may not be
# imported sideways. The schema is what both sides read.
POINTER_KEY = "testEvidence"

# The words a recorded run may answer with - the `testEvidence.status` enum the
# plan schema declares, spelled out rather than read: this file walks no schema,
# and `_manifest_vocab`'s own case counts the files that do. Held as a tuple as
# well as in the label table because the table also holds the three NO-RUN states
# below, and "is this a status a run reached" is a different question from "is
# this a word we can render".
TEV_RUN_STATUSES = ("passed", "failed", "no-checks", "timed-out", "cancelled",
                    "could-not-run", "empty-gate")

# ...and the three ways a subject has no run to show. THREE SENTENCES, NEVER ONE
# GREY BLOB: "nothing here can be measured" (no gate is declared at either
# level), "it can be and never was" (a gate is declared and no run is recorded)
# and "the plan points at a run this checkout does not hold" are three different
# states with three different repairs, and rendering them alike would tell a
# reader to go looking in the wrong place twice out of three times.
TEV_LABELS = {
    "passed": "Passed",
    "failed": "Failed",
    "no-checks": "No checks ran",
    "timed-out": "Timed out",
    "cancelled": "Cancelled",
    "could-not-run": "Could not run",
    "empty-gate": "Empty gate",
    "no-evidence": "No evidence",
    "no-gate": "No gate configured",
    "dangling": "Pointer without evidence",
}

# The observations, which are NOT statuses. Each one is a thing the run noticed
# about itself; a badge answers "what did it say", these answer "and what else is
# true about the run that said it".
TEV_FLAG_LABELS = {
    "tree-mutated": "tree mutated",
    "tree-unknown": "tree unknown",
    "no-overlap": "no overlap",
    "coverage-unknown": "coverage unknown",
    "checks-unknown": "checks unknown",
}

# The order a phase's task rollup counts in: the two verdicts, then the ways a
# run answered nothing, then the ways there is no run. A dict cannot order
# itself and sorting alphabetically would put "cancelled" above "passed", which
# reads as a ranking nobody chose.
TEV_ORDER = ("passed", "failed", "no-checks", "timed-out", "cancelled",
             "could-not-run", "empty-gate", "dangling", "no-evidence", "no-gate")

_TEV_WHY = {
    "no-gate": "this task declares no tests.gate and its phase declares no "
               "testGate, so no gate would run for it",
    "no-evidence": "a gate is configured for this task and no run has been "
                   "recorded against it - absent evidence is not a failure",
    "dangling": "the plan points at a run this checkout's evidence ledger does "
                "not carry",
}


def tev_pointer(holder):
    """The `testEvidence` block a task or a phase carries, or None.

    ABSENT MEANS 'NO RUN WAS RECORDED', NEVER 'FAILED'. The schema says so at
    length and every surface owes the reader the same reading: a manifest written
    before the field existed, a task nobody has run, and a block somebody deleted
    are one state.

    A block with no `runId` points at nothing, so it is read as no block at all -
    the same reading `_doctor_completions.check_evidence_pointers` takes of the
    same field, rather than a second opinion about what half a pointer means.
    """
    block = holder.get(POINTER_KEY) if isinstance(holder, dict) else None
    return block if isinstance(block, dict) and block.get("runId") else None


def tev_configured(task, phase):
    """Whether ANY gate would run for this task - its own, or its phase's.

    `run-test-gate.gate_of` is the rule and this is its reading half, taking the
    same two declarations in the same order: a task's `tests.gate` when it has
    one, else the phase's `testGate`. ABSENT AND EMPTY ARE ONE ANSWER there, so
    they are one answer here - otherwise "declares no gate" would mean one thing
    to the runner and another to the report.
    """
    task = task if isinstance(task, dict) else {}
    phase = phase if isinstance(phase, dict) else {}
    tests = task.get("tests") if isinstance(task.get("tests"), dict) else {}
    for entries in (tests.get("gate"), phase.get("testGate")):
        if isinstance(entries, list) and [x for x in entries if x]:
            return True
    return False


def tev_flags(row):
    """The observation markers a recorded run earns: [(key, words), ...].

    THREE-VALUED, EVERY FIELD, AND COMPARED AGAINST `None` FIRST. A truthy test
    merges "nobody could look" into "nothing was found" - `None` into `[]` - and
    that merge is the defect `run-test-gate` refuses in its own renderer. Written
    as an explicit `is None` arm ahead of the empty arm so the two cannot collapse
    into one branch later by accident.

    `observations` is where the runner puts them and the top-level `treeMutated`
    is the copy `_evidence_io` keeps for a reader that never opens it; the block
    WINS when it carries the key, including when it carries it as `None`.
    """
    row = row if isinstance(row, dict) else {}
    obs = row.get("observations") if isinstance(row.get("observations"), dict) else {}
    out = []
    mutated = obs.get("treeMutated", row.get("treeMutated"))
    if mutated is None:
        out.append("tree-unknown")
    elif mutated:
        out.append("tree-mutated")
    coverage = obs.get("coverage")
    if coverage is None:
        out.append("coverage-unknown")
    elif not coverage:
        out.append("no-overlap")
    # A POSITIVE ZERO IS NOT A NULL. `ranTotal is None` means this runner does not
    # report a count; `0` means it reported that nothing ran, which is the status
    # `no-checks` and not a marker. Printing "0 checks" for a null is the reading
    # this arm exists to make impossible.
    if obs.get("ranTotal") is None:
        out.append("checks-unknown")
    return [(k, TEV_FLAG_LABELS[k]) for k in out]


def tev_view(pointer, row, configured):
    """What one subject's test evidence says: one status, and the marks beside it.

    `pointer` is the manifest's cached block or None, `row` the ledger row that
    the pointer's `runId` names or None, `configured` whether any gate would run.

    THE LEDGER IS THE SOURCE OF TRUTH AND THE POINTER IS A CACHE, so the word
    rendered is the ROW's. The pointer's own `status` is never read for the badge:
    a cache that disagreed with the record it names would otherwise decide what
    the report says, and the schema is explicit that the block is disposable.

    AN UNRECOGNISED WORD IS NAMED, NOT FOLDED INTO `failed`. The schema promises
    the enum may gain members and deliberately does not promise the list is
    closed, so a reader of an older build must be told which word it did not
    know rather than shown the worst reading of it.
    """
    if pointer is None:
        key = "no-evidence" if configured else "no-gate"
        return {"key": key, "label": TEV_LABELS[key], "known": True, "flags": [],
                "pointer": None, "row": None, "history": [],
                "why": _TEV_WHY[key]}
    if row is None:
        return {"key": "dangling", "label": TEV_LABELS["dangling"], "known": True,
                "flags": [], "pointer": pointer, "row": None, "history": [],
                "why": "%s - the plan names run %s"
                       % (_TEV_WHY["dangling"], pointer.get("runId"))}
    word = str(row.get("status") or "").strip()
    if word not in TEV_RUN_STATUSES:
        return {"key": word or "unrecognised",
                "label": _theme.label(word) or "Unrecognised status",
                "known": False, "flags": tev_flags(row), "pointer": pointer,
                "row": row, "history": [],
                "why": "this build does not recognise the status %r, so it is "
                       "shown as written rather than read as a verdict" % (word,)}
    return {"key": word, "label": TEV_LABELS[word], "known": True,
            "flags": tev_flags(row), "pointer": pointer, "row": row,
            "history": [],
            "why": "run %s recorded %s" % (row.get("runId"), row.get("ts"))}


def _tev_badge(view):
    """The status badge: the run's one word, wearing the basis that produced it.

    IT IS A `.chip`, not a new component. A tinted pill reporting a value is the
    grammar this report already has for exactly that, and giving the test gate a
    second one would put two kinds of "here is a value" on one row. `data-tev`
    supplies the hue the way `data-status` already does; the extra `tev` class is
    the hook the stylesheet reaches it by, so the vocabulary the colour comes from
    is explicit rather than implied by an attribute name.
    """
    return ('<span class="chip tev" data-tev="%s" title="%s">%s</span>'
            % (e(view["key"]), e(view.get("why") or ""), e(view["label"])))


def _tev_mark_spans(flags):
    """The observation markers as markup. One definition, two callers - the badge
    beside a task and the same run listed under Earlier runs - because a second
    spelling of a mark is a second mark the CSS and the filter would have to
    learn."""
    return "".join('<span class="tevf" data-tevf="%s">%s</span>' % (e(k), e(w))
                   for k, w in flags or [])


def _tev_marks(view):
    """The observation markers, as separate marks beside the badge."""
    return _tev_mark_spans(view.get("flags"))


def _tev_cell(view):
    """The compact row's cell: the badge, then whatever the run also noticed."""
    if not view:
        return '<span class="muted">—</span>'
    return _tev_badge(view) + _tev_marks(view)


def tev_bug_view(bug, tasks):
    """`(view, why)` - a bug's evidence, DERIVED, never invented.

    A bug carries no gate of its own and never will: what proves a bug fixed is
    the run over the TASK that fixed it. So the answer here is the linked task's
    view plus the provenance that makes it readable as borrowed, and `why` is the
    sentence for the case where there is nothing to borrow.

    THREE OUTCOMES, NOT TWO. A bug with no `taskId` has no fix task yet; a bug
    naming a task this plan does not carry is a dangling reference the validator
    already reports; and neither is the same as a fix task whose gate said
    nothing. Collapsing them would send a reader to look at a task that is not
    there.
    """
    tid = bug.get("taskId") if isinstance(bug, dict) else None
    if not tid:
        return None, "no fix task yet"
    view = (tasks or {}).get(str(tid))
    if not view:
        return None, "fix task %s is not in this plan" % (tid,)
    return view, str(tid)


def _tev_bug_cell(bug, tasks):
    """A bug's evidence cell: the fixing task's badge, wearing where it came from.

    `Failed · via P3.2` is two facts and both are load-bearing - drop the second
    and a reader believes the BUG was measured, which nothing in this plugin ever
    does."""
    view, why = tev_bug_view(bug, tasks)
    if view is None:
        return '<span class="muted">%s</span>' % e(why)
    return ('%s%s <span class="muted">via %s</span>'
            % (_tev_badge(view), _tev_marks(view), e(why)))


def _tev_checks_text(row):
    """What the run says about how much ran - three answers, never two.

    `None` is "not knowable from this runner" and MUST NOT print as a count.
    Zero is a number the run really reported, and it is the one that cannot sign
    anything off."""
    obs = row.get("observations") if isinstance(row.get("observations"), dict) else {}
    ran = obs.get("ranTotal")
    basis = obs.get("countsBasis")
    if ran is None:
        return "not knowable from this runner"
    if ran == 0:
        return "none ran%s" % ((" · %s" % basis) if basis else "")
    return "%d ran%s" % (ran, (" · %s" % basis) if basis else "")


def _tev_paths_text(values, unknown_word, empty_word, basis, dropped):
    """A three-valued path list as one sentence, with its own basis.

    Shared by the tree and coverage rows because they ARE the same shape: a list
    of repo-relative paths, an empty list that means something definite, and a
    `None` that means the question could not be asked. Two copies of this would be
    two chances to let the third case collapse into the second."""
    if values is None:
        return '<span class="muted">%s</span>' % e(
            unknown_word + ((" — " + basis) if basis else ""))
    if not values:
        return e(empty_word + ((" — " + basis) if basis else ""))
    text = ", ".join(str(v) for v in values)
    return e("%s%s" % (text, (" (+%d more)" % dropped) if dropped else ""))


def _tev_step_rows(row):
    """One line per step: what ran, what it exited, and how much it checked.

    The COMMAND is shown only where the row carries one - `_evidence_io` stores a
    command verbatim only when the manifest already publishes it, and hands back a
    digest plus a program name for anything else. Printing the digest as if it
    were the command would be a claim this file cannot make, so each is labelled
    as what it is."""
    steps = [s for s in (row.get("steps") or []) if isinstance(s, dict)]
    if not steps:
        return ""
    out = []
    for st in steps:
        ran = st.get("ran")
        ran_txt = ("check count not knowable" if ran is None
                   else "%d check(s)" % ran)
        what = st.get("command")
        if what:
            what = "<code>%s</code>" % e(str(what))
        elif st.get("program"):
            what = e("%s · sha256 %s" % (st.get("program"),
                                              str(st.get("commandSha256") or "")[:12]))
        else:
            what = '<span class="muted">command not recorded</span>'
        outcome = st.get("outcome")
        # An exit code that was never recorded prints as a question mark rather
        # than as an empty space after the word "exit": a blank there reads as
        # zero to anyone scanning the column.
        out.append('<div class="dt-r"><span class="dt-k">%s</span>'
                   '<span class="dt-v">exit %s · %s%s<br>%s</span></div>'
                   % (e(st.get("name")),
                      "?" if st.get("exit") is None else e(st["exit"]),
                      e(ran_txt),
                      (" · " + e(outcome)) if outcome else "", what))
    dropped = row.get("stepsDropped")
    if dropped:
        out.append('<div class="dt-r"><span class="dt-k"></span>'
                   '<span class="dt-v muted">%s further step(s) were not '
                   "recorded</span></div>" % e(dropped))
    return "".join(out)


def _tev_history(view):
    """The runs before this one, folded away.

    `<details class="more">` and not a scripted panel: disclosure is something the
    platform already does, the print sheet already forces every `details.more`
    open, so the PDF carries the whole record without a line of script."""
    older = view.get("history") or []
    if not older:
        return ""
    rows = []
    for row in older:
        marks = _tev_mark_spans(tev_flags(row))
        word = str(row.get("status") or "").strip()
        rows.append('<div class="dt-r"><span class="dt-k">%s</span>'
                    '<span class="dt-v"><span class="chip tev" data-tev="%s">%s'
                    "</span>%s <code>%s</code></span></div>"
                    % (e(_stamp(row.get("ts"))), e(word),
                       e(TEV_LABELS.get(word) or _theme.label(word)),
                       marks, e(row.get("runId"))))
    return ('<details class="more tevmore"><summary>Earlier runs (%d)</summary>'
            "%s</details>" % (len(older), "".join(rows)))


def _tev_detail_col(view):
    """The drawer's third group: the whole record behind the badge.

    A third `.dtcol` in the row that already exists rather than a second
    disclosure mechanism - the drawer is where this report already answers "what
    happened", and a task's test run is that question with a different subject.
    """
    if not view:
        return ""
    rows = [('<div class="dt-r"><span class="dt-k">verdict</span>'
             '<span class="dt-v">%s%s</span></div>'
             % (_tev_badge(view), _tev_marks(view)))]
    row = view.get("row")
    if row is None:
        rows.append('<div class="dt-r"><span class="dt-v muted">%s</span></div>'
                    % e(view.get("why") or ""))
        pointer = view.get("pointer")
        if pointer:
            rows.append('<div class="dt-r"><span class="dt-k">run</span>'
                        '<span class="dt-v"><code>%s</code></span></div>'
                        % e(pointer.get("runId")))
        return ('<div class="dtcol"><h4>test evidence</h4>%s</div>'
                % "".join(rows))
    obs = row.get("observations") if isinstance(row.get("observations"), dict) else {}
    pairs = [("run", "<code>%s</code>" % e(row.get("runId"))),
             ("at", e(row.get("ts"))),
             ("scope", e(row.get("scope"))),
             ("attempt", e(row.get("attempt")) if row.get("attempt") is not None else ""),
             ("took", ("%d ms" % row["durationMs"])
              if isinstance(row.get("durationMs"), int) else ""),
             ("checks", e(_tev_checks_text(row))),
             ("tree", _tev_paths_text(
                 obs.get("treeMutated", row.get("treeMutated")),
                 "unknown", "unchanged", obs.get("treeBasis"),
                 row.get("treeMutatedDropped"))),
             ("coverage", _tev_paths_text(
                 obs.get("coverage"), "unknown",
                 "no declared file was named by the run", obs.get("coverageBasis"),
                 row.get("coverageDropped"))),
             ("failed", e(", ".join(str(f) for f in (row.get("failed") or []))))]
    for key, value in pairs:
        if not value:
            continue
        rows.append('<div class="dt-r"><span class="dt-k">%s</span>'
                    '<span class="dt-v">%s</span></div>' % (e(key), value))
    rows.append(_tev_step_rows(row))
    state = row.get("testedState") if isinstance(row.get("testedState"), dict) else {}
    if state.get("head"):
        rows.append('<div class="dt-r"><span class="dt-k">tested at</span>'
                    '<span class="dt-v"><code>%s</code> %s</span></div>'
                    % (e(str(state["head"])[:9]), e(state.get("headBasis") or "")))
    rows.append(_tev_history(view))
    return '<div class="dtcol"><h4>test evidence</h4>%s</div>' % "".join(rows)


def tev_rollup(views):
    """[(key, label, count), ...] over a phase's task views, in TEV_ORDER.

    An AGGREGATE, and it is rendered beside the phase's OWN sign-off run rather
    than merged with it. The two answer different questions - "did the gate this
    phase signs off with pass" and "what do the runs inside it say" - and one
    number carrying both would be a measurement nobody made.
    """
    counts = {}
    for view in views or []:
        counts[view["key"]] = counts.get(view["key"], 0) + 1
    ordered = [k for k in TEV_ORDER if k in counts]
    ordered += sorted(k for k in counts if k not in TEV_ORDER)
    return [(k, TEV_LABELS.get(k) or _theme.label(k), counts[k]) for k in ordered]


def _tev_phase_marks(entry):
    """A phase row's two evidence marks, LABELLED APART.

    The phase's own sign-off run and the rollup over its tasks are two
    measurements, and a row that showed one number would be claiming the other."""
    if not entry:
        return ""
    out = ""
    own = entry.get("own")
    if own:
        out += ('<span class="ptev" title="the run the gate this phase signs '
                'off with last recorded">sign-off %s%s</span>'
                % (_tev_badge(own), _tev_marks(own)))
    rollup = entry.get("rollup") or []
    if rollup:
        out += ('<span class="ptev" title="the tasks in this phase, by what '
                'their own last recorded run said">tasks %s</span>'
                % "".join('<span class="tevn" data-tev="%s">%d %s</span>'
                          % (e(k), n, e(lab)) for k, lab, n in rollup))
    return out


def _detail_row(task, phase, owners, ncol, seg, pid, workers=None, view=None):
    """The row under a task row: everything the compact row had to leave out.

    ex (F-P-4). The table is read at a glance and acted on in detail, and those
    are different densities. The compact row answers "where is this" — id,
    title, status, risk, when, commit — and the detail row answers "what
    happened and who do I ask", in two labelled groups because the questions
    come in two kinds:

      meta    — who owns this area, when it started and finished (to the
                second, not the minute the cell shows), the whole sha, the
                phase's branch and its work item
      details — the FULL outcome (both voices, untruncated: the table's 70-char
                cut is what made this row necessary), the model, the skills,
                what it waits on, and how it was tested

    "Who" is answered twice, by two different kinds of evidence, and neither is
    an assignee - the manifest has no such field and inventing one here would be
    a claim the file does not make:

      owner      - the AREA's advisory owner, from the plan
      worked by  - who the USAGE LEDGER metered on this task, strongest spend
                   first. Absent when there is no ledger, which is the honest
                   answer rather than a guess: with metering off, nothing on
                   this machine knows who ran the task.

    Both are labelled as what they are.

    `view` (when the plan points at any recorded run) adds a THIRD group, `test
    evidence` — the whole record behind the badge the compact row shows: the run,
    its steps, what it observed about the tree and the coverage, and every
    earlier run folded into a `<details>`. A third column in the drawer that
    already exists rather than a second disclosure mechanism: the drawer is where
    this report answers "what happened", and a test run is that question with a
    different subject.
    """
    def clamped(html):
        """Long prose, trimmed to a few lines, with the rest one press away.

        `technical` is the longest thing in the report - the worked example runs
        past twenty lines - and at full height it pushed `model`, `skills` and
        `tests` off the reader's screen entirely. The control ships HIDDEN and the
        client reveals it only when the text really is cut off: whether five lines
        is a trim at all depends on the width it is read at, which is a question
        the server cannot answer.
        """
        if not html:
            return ""
        return ('<span class="clampbox" data-clamp>%s</span>'
                '<button type="button" class="btn tiny dtmore" data-clampmore '
                'aria-expanded="false" hidden>Show more</button>' % (html,))

    def rows(pairs):
        out = []
        for k, v in pairs:
            if not v:
                continue
            out.append('<div class="dt-r"><span class="dt-k">%s</span>'
                       '<span class="dt-v">%s</span></div>' % (e(k), v))
        return "".join(out)

    areas = [a for a in (phase.get("area") if isinstance(phase.get("area"), list)
                         else [phase.get("area")]) if isinstance(a, str) and a]
    owner_bits = []
    for a in areas:
        own = (owners or {}).get(a)
        if own:
            owner_bits.append("%s <span class=\"muted\">(area %s)</span>"
                              % (e(own), e(a)))
    o = task.get("outcome") if isinstance(task.get("outcome"), dict) else {}
    waits = [w for w in list(task.get("blockedBy") or [])
             + list(task.get("dependsOn") or []) if isinstance(w, str)]
    tests = task.get("tests") if isinstance(task.get("tests"), dict) else {}
    skills = task.get("skills")
    # From the ledger, not from the plan - so it carries its source with it.
    worked = [w for w in ((workers or {}).get(task.get("id")) or [])
              if isinstance(w, str) and w]
    meta = rows([
        ("owner", " · ".join(owner_bits)),
        ("worked by", ("%s <span class=\"muted\">(metered on this task)</span>"
                       % (e(", ".join(worked)),)) if worked else ""),
        ("started", e(task.get("startedAt") or "")),
        ("completed", e(task.get("completedAt") or "")),
        ("commit", _commit_cell(task) if task.get("commit") else ""),
        ("branch", e(phase.get("branch") or "")),
        ("work item", _ado_cell(task) if isinstance(task.get("ado"), dict)
         and task["ado"].get("id") is not None else ""),
    ])
    details = rows([
        # Both voices, in the order a person reads them: what changed, then how.
        ("outcome", e(str(o.get("descriptive") or "").strip())),
        ("technical", clamped(e(str(o.get("technical") or "").strip()))),
        ("model", e(task.get("model") or "")),
        ("skills", e(", ".join(s for s in (skills or []) if isinstance(s, str)))
         if isinstance(skills, list) and skills
         else ('<span class="muted">none \u2014 opted out</span>'
               if skills is None and "skills" in task else "")),
        ("waits on", e(", ".join(waits))),
        ("tests", e(str(tests.get("mode") or ""))),
    ])
    tev = _tev_detail_col(view)
    if not meta and not details and not tev:
        details = ('<div class="dt-r"><span class="dt-v muted">Nothing recorded '
                   "for this task yet.</span></div>")
    return ('<tr class="taskdetail" data-phase="%s" data-seg="%s" '
            'data-detail="%s" hidden><td colspan="%d"><div class="dtwrap%s">'
            '<div class="dtcol"><h4>meta</h4>%s</div>'
            '<div class="dtcol"><h4>task details</h4>%s</div>%s'
            "</div></td></tr>"
            % (e(pid), e(seg), e(task.get("id") or ""), ncol,
               " dt3" if tev else "", meta, details, tev))


def _filter_attrs(task, view=None):
    """The data a task row is filtered BY, in attributes rather than in its text.

    Model and dates are filtered on, and the text search already reads the row's
    rendered text — but neither of those is reliable to read back out of it. The
    model may not be a rendered column at all (`_present_columns` drops it when no
    task has one), and the `done` cell shows a date that is sometimes prefixed
    with the word "started". A filter reading its own attributes compares the
    manifest's values, not the table's prose.

    Dates are cut to their date part on purpose: ISO-8601 dates compare correctly
    as STRINGS while they are the same length and shape, so the whole range test
    in the script is `d >= from && d <= to` with no Date parsing per row. Whole
    timestamps would break that against a bare `<input type=date>` value.

    Emitted only when present — an absent value is an absent attribute, so the
    script's `getAttribute(...) || ''` sees the same thing either way and the
    markup does not carry a row of empty strings for a plan that tracks neither.

    `view` is this task's test-evidence view, or None on a plan that points at no
    run. It carries TWO axes and they are INDEPENDENT: `data-tev` is what the run
    said, `data-tev-flags` is what else was true about it. A gate can fail and
    rewrite the tree, so folding the observations into the status would make one
    of those two facts unfilterable — which is the same collapse the badge itself
    refuses one function up.
    """
    out = []
    if task.get("model"):
        out.append(' data-model="%s"' % e(task["model"]))
    for attr, key in (("data-started", "startedAt"), ("data-completed", "completedAt")):
        if task.get(key):
            out.append(' %s="%s"' % (attr, e(_short_date(task[key]))))
    if view:
        out.append(' data-tev="%s"' % e(view["key"]))
        # Space-joined, mirroring `data-area`: one separator rule for every
        # attribute on this row that carries a list.
        flags = " ".join(k for k, _ in view.get("flags") or [])
        if flags:
            out.append(' data-tev-flags="%s"' % e(flags))
    return "".join(out)


# --- filter panel -----------------------------------------------------------
def _filter_panel(manifest, evidence=None):
    """The area, model, gate and date controls, server-rendered, or "" with none.

    Everything here is emitted from the manifest rather than built by the script,
    which is the rule the status chips already follow: built in JS, a filter UI is
    missing from every printed page and every reader that runs no script, and
    "the filters are gone" is indistinguishable from "the filters are broken".

    The date inputs carry the plan's own range as `min`/`max`, so the picker opens
    on the months the work actually happened in rather than on this century.
    """
    models, dates = set(), []
    for _, t in _manifest_io.iter_tasks(manifest):
        if t.get("model"):
            models.add(str(t["model"]))
        for key in ("startedAt", "completedAt"):
            if t.get(key):
                dates.append(_short_date(t[key]))
    tags = _areas.used_tags(manifest)
    # TWO INDEPENDENT AXES, TWO ROWS. The status a run reached and the
    # observations it made are not one vocabulary: a reader looking for "which
    # gates rewrote the tree" is asking a question the status column cannot
    # answer, whatever it says. Both come from the loaded evidence rather than
    # from the manifest, because only the ledger knows what a run observed.
    tev_keys = list((evidence or {}).get("keys") or [])
    tev_flags = list((evidence or {}).get("flags") or [])
    if not models and not dates and not tags and not tev_keys and not tev_flags:
        return ""

    rows = []
    # Area first: it gates PHASES, where model and dates narrow the tasks inside
    # them — the panel reads top-down from the coarser filter to the finer ones.
    # First-seen order, not sorted: tags are read in the order the plan
    # introduces them, same as the phase list below the panel. humanize=False
    # because a tag is an identifier someone typed into the manifest, exactly
    # like a model name (see _chip_buttons).
    if tags:
        # The advisory owner rides each chip as a native tooltip (D4) — the
        # same `owner: <who>` the panel's area select options carry. Tags with
        # no registered owner keep the pinned untitled shape.
        _owners = _owner_map(manifest)
        rows.append('<div class="frow"><span class="tbl">Area:</span>'
                    '<span id="audit-areas">%s</span></div>'
                    % _chip_buttons(tags, "data-a", "fchip", humanize=False,
                                    titles={t: "owner: %s" % _owners[t]
                                            for t in tags if t in _owners}))
    if models:
        rows.append('<div class="frow"><span class="tbl">Model:</span>'
                    '<span id="audit-model">%s</span></div>'
                    % _chip_buttons(sorted(models), "data-m", "fchip",
                                    humanize=False))
    if tev_keys:
        rows.append('<div class="frow"><span class="tbl">Test gate:</span>'
                    '<span id="audit-tev">%s</span></div>'
                    % _chip_buttons(tev_keys, "data-tev", "fchip",
                                    mapping=TEV_LABELS))
    if tev_flags:
        rows.append('<div class="frow"><span class="tbl">Observed:</span>'
                    '<span id="audit-tevf">%s</span></div>'
                    % _chip_buttons(tev_flags, "data-tevf", "fchip",
                                    mapping=TEV_FLAG_LABELS))
    if dates:
        span = ' min="%s" max="%s"' % (e(min(dates)), e(max(dates)))
        # The presets are relative to the LAST DAY IN THE DATA, not to today.
        # "Last 30 days" measured against the wall clock answers a different
        # question every morning, and would make the committed example — which CI
        # byte-compares against docs/index.html — a file that cannot stay equal to
        # itself. The script derives the dates from the rows; these carry only the
        # span, so the arithmetic has one home.
        rows.append(
            '<div class="frow"><span class="tbl">Worked between:</span>'
            '<input type="date" id="audit-from" aria-label="Show tasks worked on '
            'or after this date"%s>'
            '<span class="tbl">and</span>'
            '<input type="date" id="audit-to" aria-label="Show tasks worked on or '
            'before this date"%s></div>' % (span, span))
        rows.append(
            '<div class="frow"><span class="tbl">Last:</span><span id="audit-presets">'
            '<button type="button" class="fchip" data-days="7" aria-pressed="false">'
            '7 days</button>'
            '<button type="button" class="fchip" data-days="30" aria-pressed="false">'
            '30 days</button>'
            '<button type="button" class="fchip" data-days="all" aria-pressed="false">'
            'All</button></span></div>')
        # Says which "last 30 days" this is. Without it a reader compares the
        # dates against their own calendar, finds them stale, and concludes the
        # report is out of date rather than that it is measuring the work.
        rows.append('<p class="fnote">Counted back from %s, the last day this '
                    "plan recorded work — not from today.</p>" % e(max(dates)))
    return ('<details class="fdetails"><summary aria-label="More filters">'
            'More filters<span class="fcount" id="audit-fcount"></span></summary>'
            '<div class="filterpanel">%s</div></details>' % "".join(rows))


# --- global filter row (C1/C2) ----------------------------------------------
def _global_filter_row(authors, tags, dmin, dmax, owners=None):
    """The compact global filter row — author, area, date range — or "".

    DESIGN DECISION (C2, delegated): this row is a second line INSIDE the
    existing sticky `.topbar`, not a separate floating/anchored bar. Three
    reasons, in the order they decided it:

      * The report is long and its sticky stack is already measured geometry —
        `--topbar-h` (written by measureStack() in report.js) is what the side
        nav, the strip, the phases filter bar and every anchor offset hang off.
        Growing the bar the stack already measures keeps ONE sticky stack; a
        new independently-stuck row would be a fourth layer needing its own
        z-index token, its own offset in --sticky-*, and its own stuck-state
        handling for zero extra reachability.
      * Print must never show floating chrome mid-page: `.topbar` is already
        `display:none!important` in the print sheet (a pinned rule), so the row
        can never reach paper — the active range prints instead as the named
        line in the Usage section (#audit-urange).
      * Mobile width exists: inside the topbar the row wraps under the title
        with `flex-wrap` and compact controls, and the measured `--topbar-h`
        absorbs the extra height at every width — no breakpoint-specific
        arithmetic, because there is no second bar to place.

    Server-rendered like every other filter control (the chips rule): built in
    JS it would be missing wherever scripts do not run, and "the filters are
    gone" is indistinguishable from "the filters are broken". The controls are
    selects and date inputs rather than chip rows on purpose — this row stays
    one line; the full multi-select vocabulary lives where it always did (area
    chips in More filters, author chips in Usage), and report.js keeps the two
    presentations of each filter in sync over one state.

    `authors` arrives ordered (by spend, matching the Usage chips); `tags` in
    first-seen order (matching the panel chips). An author set smaller than two
    renders no select — one author has nothing to filter."""
    bits = []
    if len(authors or []) >= 2:
        opts = '<option value="">All authors</option>' + "".join(
            '<option value="%s">%s</option>' % (e(a), e(a)) for a in authors)
        bits.append('<label class="gf"><span class="tbl">Author</span>'
                    '<select id="audit-au-select" aria-label="Scope the Usage '
                    'section&#39;s per-author views to one author">%s</select>'
                    "</label>" % opts)
    elif authors:
        # ONE author: the question "who worked on this" still deserves an answer
        # in the header, and a one-option dropdown is not it -- a control whose
        # every use is a no-op is the same defect as a status chip the view can
        # never satisfy. So the bar STATES the author instead of offering to
        # filter by them, and the reader learns the fact without being handed a
        # dead control. Asked for by a reader who wanted Author beside Area/From/
        # To and, on a solo project, found nothing there at all.
        bits.append('<span class="gf gfone"><span class="tbl">Author</span>'
                    '<span class="gfval" id="audit-au-only" '
                    'title="the only author in this ledger - nothing to filter '
                    'between">%s</span></span>' % e(authors[0]))
    if tags:
        # Each option titles its advisory owner (D4) — exactly the panel's
        # area-select behaviour, so a habit learned there reads here too.
        opts = '<option value="">All areas</option>' + "".join(
            '<option value="%s"%s>%s</option>'
            % (e(t),
               (' title="owner: %s"' % e((owners or {}).get(t)))
               if (owners or {}).get(t) else "",
               e(t))
            for t in tags)
        bits.append('<label class="gf"><span class="tbl">Area</span>'
                    '<select id="audit-area-select" aria-label="Show only '
                    'phases tagged with this area">%s</select></label>' % opts)
    if dmin and dmax:
        span = ' min="%s" max="%s"' % (e(dmin), e(dmax))
        bits.append(
            '<label class="gf"><span class="tbl">From</span>'
            '<input type="date" id="audit-gfrom" aria-label="From - start of the '
            'date range scoping the task table and the usage charts"%s></label>'
            '<label class="gf"><span class="tbl">to</span>'
            '<input type="date" id="audit-gto" aria-label="to - end of the date '
            'range scoping the task table and the usage charts"%s></label>'
            '<button type="button" class="btn" id="audit-gclear" hidden '
            'title="Clear the date range - back to all time">All time</button>'
            % (span, span))
    if not bits:
        return ""
    return ('<div class="gfilters" role="group" aria-label="Global filters">'
            "%s</div>" % "".join(bits))


# --- ready now (C4) ----------------------------------------------------------
def _ready_now_dl(manifest, ready_ids):
    """The Ready-now section as a definition list: each ready task is a term
    (id, title, its phase's area tags in the same chip style areas wear
    everywhere else), and the definition says WHY it is ready — the blockers
    that have cleared, or that nothing ever blocked it.

    The old rendering was a comma-joined id list in monospace: correct, and
    unreadable past five entries — a reader had to look every id up by hand to
    learn what any of them was. This carries the lookup with the id.

    Renders "" for an empty list; the caller already omits the section then
    (the hero's "Nothing ready / nothing left to run" line is the empty state,
    and a heading over an empty list would say less than that line does)."""
    if not ready_ids:
        return ""
    owners = _owner_map(manifest)   # tags here wear their advisory owner too
    # One pass, not two: `phase_of` wants the phase BODY (its `area` and its
    # `blockedBy` are read below), which `_manifest_io.phase_of_task` deliberately
    # does not carry — it answers with an id. `iter_tasks` yields the pair, which
    # is the case its docstring names, and both dicts keep the shared truthy-id
    # filter and LAST-wins rule for free.
    task_of, phase_of = {}, {}
    for ph, t in _manifest_io.iter_tasks(manifest):
        if t.get("id"):
            task_of[t["id"]] = t
            phase_of[t["id"]] = ph
    items = []
    for rid in ready_ids:
        t = task_of.get(rid) or {}
        ph = phase_of.get(rid) or {}
        tags = "".join(" " + _area_tag_span(a, owners)
                       for a in _areas_of(ph.get("area")))
        title = (' <strong>%s</strong>' % e(t["title"])) if t.get("title") else ""
        cleared = []
        for word, refs in (("depends on", t.get("dependsOn")),
                           ("blocked by", t.get("blockedBy")),
                           ("phase blocked by", ph.get("blockedBy"))):
            names = [r for r in (refs or []) if isinstance(r, str) and r]
            if names:
                cleared.append("%s %s (done)"
                               % (word, ", ".join(e(r) for r in names)))
        # A ready task's blockers are all satisfied by definition (that is what
        # ready MEANS), so listing them with "(done)" states the evidence
        # rather than re-deriving it.
        why = ("Cleared: " + " · ".join(cleared)) if cleared \
            else "Nothing blocked it — ready from the start."
        where = ""
        if ph.get("id"):
            where = 'In <span class="mono">%s</span>%s. ' % (
                e(ph["id"]),
                (" — %s" % e(ph["title"])) if ph.get("title") else "")
        items.append('<dt><code class="mono">%s</code>%s%s</dt><dd>%s%s</dd>'
                     % (e(rid), title, tags, where, why))
    return '<dl class="ready">%s</dl>' % "".join(items)


# --- risk + progress fragments ----------------------------------------------
def _risk_chip(risk):
    """Tinted risk chip (low/med/high); em dash for null/unknown. Colored by the
    CSS theme token selected via data-risk (see render-report's _CSS)."""
    r = str(risk or "").lower()
    if r not in _RISK_LEVELS:
        return '<span class="muted">—</span>'
    return '<span class="rchip" data-risk="%s">%s</span>' % (r, e(r))


def _phase_meta_div(phase):
    """Muted sub-line for a phase group-row: the priority pin, desired outcome,
    branch, merge timestamp, and (once signed off) the summary — all escaped.

    The pin leads because it is the only bit that answers "when does this run"
    rather than "what is it". It reads the tier through `_priority.tier_of`, not
    off the raw field: a `priority` that is not a positive integer orders
    nothing, and a badge rendered from the raw value would advertise a pin the
    run does not honour. The table itself stays in MANIFEST order — the written
    plan is the plan, and priority only re-sorts which READY task goes first.
    """
    bits = []
    tier = _priority.tier_of(phase)
    if tier is not None:
        bits.append("priority %d" % tier)
    if phase.get("desiredOutcome"):
        bits.append("Desired: " + e(phase["desiredOutcome"]))
    if phase.get("branch"):
        bits.append("branch " + e(phase["branch"]))
    if phase.get("mergedAt"):
        bits.append("merged " + e(phase["mergedAt"]))
    if phase.get("summary"):
        bits.append(e(phase["summary"]))
    return ('<div class="pmeta muted">%s</div>' % " · ".join(bits)) if bits else ""


def any_phase_pinned(manifest):
    """Whether any phase carries a tier the run will honour.

    THE ONE PREDICATE BOTH HALVES OF THE SORT OPTION READ. A sort control the
    page offers must be backed by a rank on every row, and a rank on every row
    with no control is dead weight; deciding each separately is how the two
    become a dropdown that reorders nothing. So the toolbar asks this before
    emitting the control and `phase_ranks` asks it before emitting the numbers.

    `_priority.tier_of`, not the raw field: `priority: "1"` orders nothing, so a
    plan carrying only invalid values has nothing to sort by and is not offered
    the choice. A plan with no `priority` at all therefore renders exactly as it
    did before this existed — which is this feature's two-direction case, and
    the reason the committed example artifacts did not move.
    """
    return any(_priority.tier_of(p) is not None
               for p in (manifest.get("phases") or []) if isinstance(p, dict))


def phase_ranks(manifest):
    """Where each phase sits in EXECUTION order, positionally against the same
    `[p for p in phases if isinstance(p, dict)]` list the rollup and the table
    rows are built from — or `[]` when no phase is pinned.

    The report's table arrives in MANIFEST order and stays that way; these are
    emitted as `data-porder` so the client's sort orders by a number it was
    GIVEN. `_priority.ranks` is the only thing that computes them, which is what
    keeps the report's sort and the orchestrator's own walk from becoming two
    orders — the client has no comparator to drift.
    """
    if not any_phase_pinned(manifest):
        return []
    return _priority.ranks([p for p in (manifest.get("phases") or [])
                            if isinstance(p, dict)])


def _bar(done, total):
    # Fill width is a CSS var so the stylesheet can animate 0 -> --w on load.
    pct = int(round(100.0 * done / total)) if total else 0
    return ('<span class="bar"><span class="fill" style="--w:%d%%"></span></span> '
            '<span class="muted">%d/%d</span>' % (pct, done, total))


# --- cli --------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exits silently: `--selftest` is what every other
        # file here still accepts, so nothing would tell a reader whether this
        # one ran nothing or has nothing. It deliberately does NOT print the
        # suite contract - that literal is how `_output.selftest_coverage()`
        # tells an inline suite from a migrated one.
        print("_report_html.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__report_html.py - run that file instead.")
        raise SystemExit(0)
    print(__doc__.strip())
