#!/usr/bin/env python3
"""
Headless status rollup + CI gate for the audit manifest — dependency-free (stdlib).

Turns the manifest into a machine-readable summary and, in gate mode, a CI
pass/fail signal — so a pipeline can block a merge on manifest state without
any Claude session involved.

Usage:
  audit-status.py <manifest> [--json] [--gate] [--phase <id>]
                             [--fail-on <c1,c2,...>]
  audit-status.py --selftest

Modes: a bare invocation renders a human report; --json is for machines.
  --json    print the rollup as JSON
  --phase   scope the human render to one phase (totals stay whole-plan)
  --gate    evaluate fail conditions; exit 1 when any trips (prints a summary)

Conditions for --fail-on (comma list; the --gate default is
`invalid,open-high-bugs,blocked-tasks`):
  invalid          the structural validator reports findings
  open-high-bugs   high-or-worse severity bugs not yet fixed/wontfix
                   (high/critical/blocker/severe/fatal/urgent/sev0-1/s0-1/p0-1)
  open-bugs        ANY bug not yet fixed/wontfix
  blocked-tasks    any task with status "blocked"
  in-progress      any phase or task "in_progress" (for release-freeze gates)
  over-budget      a phase at or past 100% of its `budgetUSD`
  budget-80        a phase at or past 80% of its `budgetUSD`

Neither budget condition is in the --gate default: spend is a signal, not a defect,
and a phase at 105% may be entirely justified. Opt in when a budget is a commitment.

Exit codes: 0 pass · 1 gate failed · 2 usage error / unreadable manifest
(matching validate-manifest.py's convention).
"""
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, _HERE)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR index+shards)
import _areas  # noqa: E402  (meta.areas registry + the resolution every surface shares)
import _ui_theme as _theme  # noqa: E402  (the words a person reads for a machine value)
import _loader  # noqa: E402  (the one way scripts/ loads a sibling script as a library)
import _fmt  # noqa: E402  (the one token/cost formatter, since P10.6 — no indirection needed)

# --- config / loading -----------------------------------------------------------
CONDITIONS = ("invalid", "open-high-bugs", "open-bugs", "blocked-tasks",
              "in-progress", "over-budget", "budget-80")
# Neither budget condition is in the default gate. Spend is a signal, not a defect:
# a phase at 105% may be entirely justified, and failing someone's merge over it
# without them asking would make the whole gate something to switch off. Opt in with
# --fail-on when a budget is a commitment rather than an estimate.
DEFAULT_GATE = ("invalid", "open-high-bugs", "blocked-tasks")
# Warn threshold for the interactive path and the `budget-80` condition. 80% is far
# enough in to be real and early enough to act on.
BUDGET_WARN_PCT = 80.0
CLOSED_BUG = ("fixed", "wontfix")

# How many ready tasks /audit:status lists before folding. A wide-open plan can
# have hundreds; the count is always stated so the fold is never mistaken for the
# whole set.
READY_LIST_MAX = 12

# "open-high-bugs" must catch high-severity-or-worse, not only the literal word
# "high" — a bug filed as critical/blocker/sev1/p0 is the LAST thing a merge
# gate should wave through. Severity is free-text, so normalise (lowercase,
# drop non-alphanumerics) and match a vocabulary of high-or-worse terms.
HIGH_SEVERITIES = frozenset({
    "high", "critical", "crit", "blocker", "severe", "fatal", "urgent",
    "sev0", "sev1", "s0", "s1", "p0", "p1",
})


def _is_high_severity(severity):
    """True for high-or-worse free-text severities (see HIGH_SEVERITIES)."""
    return re.sub(r"[^a-z0-9]", "", str(severity or "").lower()) in HIGH_SEVERITIES


def _load_validator():
    """Import validate-manifest.py (hyphenated filename) as a library."""
    return _loader.load_script("validate-manifest.py", modname="validate_manifest",
                                cache=False)


# --- submodule conflict detection (preflight guard) -----------------------------
# The orchestrator commits from ONE git repo (the resolved gitRoot). Files that
# live inside a git SUBMODULE belong to a separate nested repo — the parent
# cannot stage them ("Pathspec is in submodule"), so a task touching them would
# fail at commit time. This flags them up front.

def parse_gitmodules(text):
    """Submodule paths (git-root-relative) from a .gitmodules file's text."""
    paths = []
    for line in str(text).splitlines():
        s = line.strip()
        # `.gitmodules` uses `path = <dir>` inside each [submodule "..."] block
        if s.lower().startswith("path") and "=" in s:
            val = s.split("=", 1)[1].strip().replace("\\", "/").strip("/")
            if val:
                paths.append(val)
    return paths


def _strip_git_root(path, git_root):
    """Project-relative file -> git-root-relative (drop the gitRoot prefix and any
    `:line` suffix)."""
    p = str(path).replace("\\", "/").split(":", 1)[0]
    gr = str(git_root or "").replace("\\", "/").strip("/")
    if gr and (p == gr or p.startswith(gr + "/")):
        return p[len(gr) + 1:]
    return p


def submodule_conflicts(manifest, submodule_paths, git_root=""):
    """List of (task_id, file, submodule) for each task file that lives inside a
    submodule. `files` are project-relative (gitRoot-prefixed); `submodule_paths`
    are git-root-relative. Path-boundary safe: 'vendor/child' matches
    'vendor/child/x' but NOT 'vendor/child-other/x'."""
    subs = [str(s).replace("\\", "/").strip("/") for s in (submodule_paths or []) if s]
    out = []
    if not isinstance(manifest, dict):
        return out
    for ph in manifest.get("phases") or []:
        if not isinstance(ph, dict):
            continue
        for t in ph.get("tasks") or []:
            if not isinstance(t, dict):
                continue
            for f in t.get("files") or []:
                rel = _strip_git_root(f, git_root)
                for s in subs:
                    if rel == s or rel.startswith(s + "/"):
                        out.append((t.get("id"), f, s))
                        break
    return out


# --- gate rollup ----------------------------------------------------------------
def ready_tasks(manifest):
    """Task ids ready to run — mirrors /audit's readiness rule: status pending,
    own blockedBy satisfied, own dependsOn all done, phase blockedBy satisfied
    ('satisfied' = referenced task/phase is done)."""
    if not isinstance(manifest, dict):
        return []
    phases = [p for p in (manifest.get("phases") or []) if isinstance(p, dict)]
    status = {}
    for ph in phases:
        if ph.get("id"):
            status[ph["id"]] = ph.get("status")
        for t in ph.get("tasks") or []:
            if isinstance(t, dict) and t.get("id"):
                status[t["id"]] = t.get("status")

    def satisfied(refs):
        return all(status.get(r) == "done" for r in (refs or []))

    out = []
    for ph in phases:
        for t in ph.get("tasks") or []:
            if not isinstance(t, dict) or t.get("status") != "pending":
                continue
            if not satisfied(t.get("blockedBy")):
                continue
            if not satisfied(t.get("dependsOn")):
                continue
            if not satisfied(ph.get("blockedBy")):
                continue
            if t.get("id"):
                out.append(t["id"])
    return out


def _by_status(items):
    out = {}
    for it in items:
        s = it.get("status") if isinstance(it, dict) else None
        out[str(s)] = out.get(str(s), 0) + 1
    return out


def _by_status_values(values):
    out = {}
    for s in values:
        out[str(s)] = out.get(str(s), 0) + 1
    return out


# A phase's `area` -> its tags. Re-exported rather than reimplemented: the panel
# and this file each carried their own copy, and one of them would eventually have
# learned something the other had not. `_areas` also owns what a tag MEANS now
# (meta.areas), so normalisation had to move next to the lookup it feeds.
areas_of = _areas.areas_of


def effective_bug_status(bug, task_by_id):
    """A bug's status, DERIVING 'fixed' from its linked task.

    The orchestrator never writes bugs[] during a run (that keeps the shared index
    untouched, so parallel phase branches merge clean). Instead a bug materialized
    into a task (bug.taskId <-> task.bugId) reads as 'fixed' once that task is done.
    A human-set 'wontfix' always wins; an un-materialized bug keeps its reported
    status (open/triaged/in_progress)."""
    stored = bug.get("status")
    if stored == "wontfix":
        return "wontfix"
    tid = bug.get("taskId")
    t = task_by_id.get(tid) if tid else None
    if isinstance(t, dict) and t.get("status") == "done":
        return "fixed"
    return stored


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
        return {
            "ledgerDir": ledger_dir,
            "pricingAsOf": meta_usage.get("pricingAsOf")
            if isinstance(meta_usage, dict) else None,
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


def rollup(manifest, findings, warnings, usage=None):
    """The machine-readable summary --json, render-report and the panel consume.

    `usage` is the optional block from `usage_summary()`; it is passed in rather
    than read here so this stays a pure dict -> dict transform."""
    if not isinstance(manifest, dict):
        manifest = {}  # non-object root -> empty rollup, never an AttributeError
    phases = [p for p in (manifest.get("phases") or []) if isinstance(p, dict)]
    tasks = [t for p in phases for t in (p.get("tasks") or [])
             if isinstance(t, dict)]
    bugs = [b for b in (manifest.get("bugs") or []) if isinstance(b, dict)]
    task_by_id = {t["id"]: t for t in tasks if t.get("id")}
    bug_eff = [effective_bug_status(b, task_by_id) for b in bugs]
    open_bugs = [b for b, s in zip(bugs, bug_eff) if s not in CLOSED_BUG]
    phase_entries = [{
        "id": p.get("id"), "title": p.get("title"),
        "status": p.get("status"), "area": areas_of(p.get("area")),
        "desiredOutcome": p.get("desiredOutcome"),
        "done": sum(1 for t in (p.get("tasks") or [])
                    if isinstance(t, dict) and t.get("status") == "done"),
        "total": sum(1 for t in (p.get("tasks") or []) if isinstance(t, dict)),
    } for p in phases]
    # group phases by each of their `area` tags (a phase with several tags counts
    # under each; untagged phases are simply not grouped)
    areas = {}
    for e in phase_entries:
        for a in e["area"]:
            g = areas.setdefault(a, {"phases": 0, "done": 0, "total": 0})
            g["phases"] += 1
            g["done"] += e["done"]
            g["total"] += e["total"]
    props = [x for x in (manifest.get("proposals") or []) if isinstance(x, dict)]
    out = {
        "valid": not findings,
        "findings": len(findings),
        "warnings": len(warnings),
        "phases": phase_entries,
        "areas": areas,
        "tasks": {"total": len(tasks), "byStatus": _by_status(tasks)},
        "bugs": {"total": len(bugs), "byStatus": _by_status_values(bug_eff),
                 "open": len(open_bugs),
                 "openHighSeverity": sum(
                     1 for b in open_bugs
                     if _is_high_severity(b.get("severity")))},
        # "parked" counts only what /audit:propose materialize can act on —
        # status 'proposed' WITH a payload. Legacy free-form entries show up in
        # total/byStatus but are not parked work.
        "proposals": {"total": len(props), "byStatus": _by_status(props),
                      "parked": sum(1 for x in props
                                    if x.get("status") == "proposed"
                                    and isinstance(x.get("payload"), dict))},
        "ready": ready_tasks(manifest),
    }
    # Only present when a ledger exists, so consumers can treat "no key" as
    # "metering not in use" without a second probe.
    if usage:
        out["usage"] = usage
    return out


def unmet_refs(manifest):
    """Task/phase id -> the refs it waits on that are not `done` yet.

    Same 'satisfied' notion as `ready_tasks`, exposed per task so the renderer can
    say WHY something is not ready instead of only that it is not."""
    if not isinstance(manifest, dict):
        return {}
    phases = [p for p in (manifest.get("phases") or []) if isinstance(p, dict)]
    status = {}
    for ph in phases:
        if ph.get("id"):
            status[ph["id"]] = ph.get("status")
        for t in ph.get("tasks") or []:
            if isinstance(t, dict) and t.get("id"):
                status[t["id"]] = t.get("status")
    out = {}
    for ph in phases:
        pending = [r for r in (ph.get("blockedBy") or [])
                   if status.get(r) != "done"]
        if ph.get("id") and pending:
            out[ph["id"]] = pending
        for t in ph.get("tasks") or []:
            if not isinstance(t, dict) or not t.get("id"):
                continue
            waits = [r for r in list(t.get("blockedBy") or [])
                     + list(t.get("dependsOn") or [])
                     if status.get(r) != "done"]
            # A task inherits its phase's gate: it cannot start while the phase
            # is blocked, and saying so is more useful than an empty column.
            waits += ["%s (phase)" % r for r in pending]
            if waits:
                out[t["id"]] = waits
    return out


# --- human rendering ------------------------------------------------------------
# `_marker` and the layout below are the vocabulary commands/status.md used to hand
# to the model as prose. Moving it here is the same move commands/usage.md already
# made for itself: a status command that spends tokens re-tabulating a rollup it was
# just handed is paying twice for one answer, and the layout comes out different
# every run. The model reads nothing here — this renders from the manifest that is
# already loaded in this process, so nothing is re-read either.
_MARKERS = {"done": "[x]", "in_progress": "[~]", "blocked": "[!]",
            "pending": "[ ]"}


def _marker(status):
    return _MARKERS.get(status, "[?]")


def _short(sha):
    s = str(sha or "")
    return s[:7] if s else "-"


def render_status(manifest, summary, width=18, only_phase=None):
    """Plain-ASCII status report. Printed verbatim by /audit:status.

    Pure ASCII, no ANSI, no box-drawing — the same constraint audit-usage.py's
    selftest enforces on its own output, so this reads in any terminal."""
    au = _load_usage_fmt()
    meta = (manifest or {}).get("meta") or {}
    lines = []
    title = meta.get("title") or "audit"
    repo = meta.get("repo") or "-"
    lines.append("AUDIT  %s   repo %s" % (title, repo))
    lines.append("")

    t_total = summary["tasks"]["total"]
    t_done = summary["tasks"]["byStatus"].get("done", 0)
    ph_done = sum(1 for p in summary["phases"] if p.get("status") == "done")
    bugs = summary["bugs"]
    frac = (float(t_done) / t_total) if t_total else 0.0
    lines.append("  %s  %d/%d tasks done - %d/%d phases signed off - "
                 "%d open bug(s) - %d ready now"
                 % (au.bar(frac, width), t_done, t_total, ph_done,
                    len(summary["phases"]), bugs["open"], len(summary["ready"])))
    if not summary["valid"]:
        lines.append("  INVALID MANIFEST: %d validator finding(s) - fix before "
                     "running a phase" % summary["findings"])
    # A park-all /audit:init leaves a valid plan with zero phases. Without this
    # line that plan reads as "nothing to do" on the one surface everyone
    # checks first, when the actual state is "everything is waiting for you".
    props_sum = summary.get("proposals") or {}
    if not summary["phases"] and props_sum.get("parked"):
        lines.append("  empty plan - %d parked proposal(s) waiting: "
                     "/audit:propose list" % props_sum["parked"])

    usage = summary.get("usage")
    if usage:
        lines.append("  " + _usage_line(summary, usage))
        lines += _budget_lines(au, summary, usage)

    unmet = unmet_refs(manifest)
    ready = set(summary["ready"])
    by_id = {p.get("id"): p for p in (manifest.get("phases") or [])
             if isinstance(p, dict)}
    # Scoping affects only which phases are LISTED. The overall line, the usage
    # line and the bug counts stay whole-plan on purpose: a phase view that
    # silently rescoped the totals would misreport the project.
    shown_phases = [p for p in summary["phases"]
                    if not only_phase or p.get("id") == only_phase]
    if only_phase:
        lines.append("  scoped to phase %s - totals above are whole-plan"
                     % only_phase)

    # Column widths are computed across EVERY task, then the header is printed once.
    # Per-phase tables re-printed their own header and re-derived their own widths,
    # so a fifty-phase manifest produced fifty header rows and fifty different
    # alignments — the columns stopped being columns.
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

    lines.append("")
    lines.append(fmt_row(list(cols)))

    for pe in shown_phases:
        lines.append("")
        pdone, ptotal = pe.get("done", 0), pe.get("total", 0)
        pfrac = (float(pdone) / ptotal) if ptotal else 0.0
        ph = by_id.get(pe.get("id")) or {}
        head = "  %-4s %-26s %-11s %s %d/%d" % (
            pe.get("id") or "?", _clip(pe.get("title") or "", 26),
            _theme.label(pe.get("status")) or "?", au.bar(pfrac, 12), pdone, ptotal)
        if ph.get("branch"):
            head += "  %s" % ph["branch"]
        lines.append(head)
        if pe.get("desiredOutcome"):
            lines.append("       desired: %s"
                         % _clip(_one_line(pe["desiredOutcome"]), 88))
        scope = _scope_line(manifest, ph, pe)
        if scope:
            lines.append(scope)
        if pe.get("id") in unmet and ph.get("status") != "done":
            lines.append("       blocked by: %s"
                         % _clip(", ".join(unmet[pe["id"]]), 70))
        for r in all_rows.get(pe.get("id")) or []:
            lines.append(fmt_row(r))

    lines.append("")
    if summary["ready"]:
        ready_list = summary["ready"]
        # A wide-open plan can have hundreds of ready tasks, and a 464-line list is
        # a list nobody reads. Fold it, and SAY the count — a silent cap would read
        # as "that is all of them", which is the worse failure.
        shown = ready_list[:READY_LIST_MAX]
        lines.append("  READY NOW  %d task(s)%s"
                     % (len(ready_list),
                        "" if len(shown) == len(ready_list)
                        else ", first %d shown" % len(shown)))
        task_by_id = {t.get("id"): t for p in (manifest.get("phases") or [])
                      if isinstance(p, dict)
                      for t in (p.get("tasks") or []) if isinstance(t, dict)}
        for tid in shown:
            t = task_by_id.get(tid) or {}
            lines.append("    %-9s %-44s %-7s run: /audit:run %s"
                         % (tid, _clip(_one_line(t.get("title")), 44),
                            t.get("model") or "-", tid))
        if len(shown) < len(ready_list):
            lines.append("    ... and %d more - /audit:next runs the first in order"
                         % (len(ready_list) - len(shown)))
    else:
        lines.append("  READY NOW  nothing - every pending task is waiting on "
                     "something, or the plan is complete")

    lines += _area_lines(au, summary)
    lines += _bug_lines(manifest, summary)
    lines += _proposal_lines(manifest, summary)
    lines += _resumable_lines(manifest, summary)
    return "\n".join(lines)


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


def _budget_lines(au, summary, usage):
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
    out = []
    for p in sorted(rows, key=lambda x: -(x.get("pct") or 0)):
        pct = p.get("pct") or 0.0
        flag = ""
        if pct >= 100.0:
            flag = "  OVER"
        elif pct >= BUDGET_WARN_PCT:
            flag = "  WARN"
        out.append("  budget %-5s %s %3.0f%%  %s of %s%s"
                   % (p.get("id") or "?", au.bar(pct / 100.0, 12), pct,
                      _fmt.fmt_cost(p.get("spent")), _fmt.fmt_cost(p.get("budget")),
                      flag))
    unbudgeted = len(budgets.get("phases") or []) - len(rows)
    if unbudgeted:
        out.append("  budget       %d phase(s) declare none - not shown, and not "
                   "phases at zero" % unbudgeted)
    return out


def _area_lines(au, summary):
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
    phases = [p for p in (summary.get("phases") or []) if isinstance(p, dict)]
    untagged = [p for p in phases if not p.get("area")]
    rows = [(tag, g.get("phases", 0), g.get("done", 0), g.get("total", 0))
            for tag, g in sorted(areas.items())]
    if untagged:
        rows.append(("untagged", len(untagged),
                     sum(p.get("done", 0) for p in untagged),
                     sum(p.get("total", 0) for p in untagged)))
    out = ["", "  BY AREA  %d tag(s) - %d of %d phase(s) tagged"
           % (len(areas), len(phases) - len(untagged), len(phases))]
    w = max(len(r[0]) for r in rows)
    for tag, n_ph, done, total in rows:
        frac = (float(done) / total) if total else 0.0
        out.append("    %-*s  %2d phase(s)  %s %d/%d tasks"
                   % (w, tag, n_ph, au.bar(frac, 12), done, total))
    if any(len(p.get("area") or []) > 1 for p in phases):
        out.append("    note: a phase with several tags counts under each - "
                   "per-area sums can exceed the plan total")
    return out


def _bug_lines(manifest, summary):
    bugs = [b for b in ((manifest or {}).get("bugs") or []) if isinstance(b, dict)]
    if not bugs:
        return []
    tasks = {t.get("id"): t for p in (manifest.get("phases") or [])
             if isinstance(p, dict)
             for t in (p.get("tasks") or []) if isinstance(t, dict)}
    ready = set(summary["ready"])
    out = ["", "  BUGS  %d total - %d open (%d high severity)"
           % (summary["bugs"]["total"], summary["bugs"]["open"],
              summary["bugs"]["openHighSeverity"])]
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


def _proposal_lines(manifest, summary):
    """Parked proposals — phases synthesized by /audit:init but not materialized.

    Listed only while parked (status 'proposed'): a materialized proposal is
    already visible as its phase, and a dropped one is history. A payload-bearing
    row carries the copy-pasteable materialize command; a legacy free-form entry
    (no payload) is listed without one — there is nothing to materialize."""
    props = [x for x in ((manifest or {}).get("proposals") or [])
             if isinstance(x, dict)]
    parked = [x for x in props if x.get("status") == "proposed"]
    if not parked:
        return []
    sp = summary.get("proposals") or {}
    out = ["", "  PROPOSALS  %d total - %d parked"
           % (sp.get("total", len(props)), len(parked))]
    for x in parked:
        payload = x.get("payload") if isinstance(x.get("payload"), dict) else {}
        ph = payload.get("phase") if isinstance(payload.get("phase"), dict) else {}
        tasks = ph.get("tasks") if isinstance(ph.get("tasks"), list) else []
        reserved = "-"
        if ph.get("id"):
            reserved = "%s (%d task%s)" % (ph["id"], len(tasks),
                                           "" if len(tasks) == 1 else "s")
        row = "    %-16s %-14s %s" % (
            x.get("id") or "?", reserved,
            _clip(_one_line(x.get("name") or x.get("id")), 40))
        if ph.get("id"):
            row += "   materialize: /audit:propose materialize %s" % (x.get("id") or "?")
        out.append(row)
    return out


def _resumable_lines(manifest, summary):
    """Flag an interrupted run, which is the one state a reader must not miss."""
    for p in ((manifest or {}).get("phases") or []):
        if not isinstance(p, dict):
            continue
        running_tasks = [t for t in (p.get("tasks") or [])
                         if isinstance(t, dict) and t.get("status") == "in_progress"]
        if p.get("status") == "in_progress" or running_tasks:
            where = " on %s" % p["branch"] if p.get("branch") else ""
            return ["", "  RESUMABLE  phase %s is %s%s - interrupted? "
                    "run /audit:resume"
                    % (p.get("id") or "?",
                       (_theme.label("in_progress") or "in progress").lower(), where)]
    return []


def _load_usage_fmt():
    """audit-usage.py's `bar()` — the share-bar renderer, which has no home in
    _fmt.py (that module holds only the token/cost/int formatters shared with
    render-report.py; `bar` is audit-usage's own CLI shape). fmt_tokens/fmt_cost
    are imported directly from _fmt (see the top-of-file import) since P10.6 made
    it the one copy; this loader stays only for what _fmt does not carry. Its
    `render()` is deliberately NOT reused — that one reads flags off an argparse
    Namespace."""
    return _loader.load_script("audit-usage.py", modname="audit_usage_fmt",
                                cache=False)


# --- gate evaluation ------------------------------------------------------------
def evaluate_gate(summary, conditions):
    """Return the list of FAILED condition names."""
    failed = []
    for c in conditions:
        if c == "invalid" and not summary["valid"]:
            failed.append(c)
        elif c == "open-high-bugs" and summary["bugs"]["openHighSeverity"] > 0:
            failed.append(c)
        elif c == "open-bugs" and summary["bugs"]["open"] > 0:
            failed.append(c)
        elif c == "blocked-tasks" and summary["tasks"]["byStatus"].get(
                "blocked", 0) > 0:
            failed.append(c)
        elif c == "in-progress" and (
                summary["tasks"]["byStatus"].get("in_progress", 0) > 0
                or any(p.get("status") == "in_progress"
                       for p in summary["phases"])):
            failed.append(c)
        elif c in ("over-budget", "budget-80") and budget_breaches(
                summary, BUDGET_WARN_PCT if c == "budget-80" else 100.0):
            failed.append(c)
    return failed


def _budget_detail(summary, threshold_pct):
    """Name the phases and their numbers, never just the count.

    "2 phase(s) over budget" sends the reader hunting; the whole point of tying spend
    to the plan is that it can say WHICH phase and by how much."""
    rows = budget_breaches(summary, threshold_pct)
    if not rows:
        return "no phase past %.0f%%" % threshold_pct
    parts = ["%s at %.0f%% (%s of %s)"
             % (p.get("id"), p.get("pct") or 0,
                _fmt.fmt_cost(p.get("spent")), _fmt.fmt_cost(p.get("budget")))
             for p in sorted(rows, key=lambda x: -(x.get("pct") or 0))[:3]]
    more = "" if len(rows) <= 3 else ", +%d more" % (len(rows) - 3)
    return "; ".join(parts) + more


def budget_breaches(summary, threshold_pct):
    """Phases at or past `threshold_pct` of their declared budget.

    Returns [] when nothing is metered or no phase declares a budget — a repo with
    no budgets must never trip a budget gate, and an unbudgeted phase is not a phase
    at zero. Reads the block `phase_budgets` already computed rather than recomputing
    a percentage from spend and budget, so the "what counts as a budget" rule lives
    in exactly one place."""
    budgets = ((summary or {}).get("usage") or {}).get("budgets") or {}
    out = []
    for p in budgets.get("phases") or []:
        pct = p.get("pct")
        if p.get("budget") and pct is not None and pct >= threshold_pct:
            out.append(p)
    return out


def _extract_opt(args, flag):
    """Pull `--flag value` out of args; return the value or None."""
    if flag in args:
        i = args.index(flag)
        if i + 1 >= len(args):
            return "__MISSING__"
        val = args[i + 1]
        del args[i:i + 2]
        return val
    return None


def main(argv):
    args = list(argv)
    want_json = "--json" in args
    want_gate = "--gate" in args
    for flag in ("--json", "--gate"):
        while flag in args:
            args.remove(flag)

    # --submodules <.gitmodules path> [--git-root <prefix>]: preflight guard,
    # exits 1 when a task file lives inside a submodule. Standalone mode.
    gitmodules = _extract_opt(args, "--submodules")
    git_root_prefix = _extract_opt(args, "--git-root") or ""
    # --phase <id>: scope the HUMAN render to one phase. /audit:phase and
    # /audit:next need a deterministic entry view; their per-task progress lines are
    # emitted as the work happens and cannot be pre-rendered, so this covers the
    # half that can be, rather than pretending to cover both.
    only_phase = _extract_opt(args, "--phase")
    if only_phase == "__MISSING__":
        sys.stderr.write("usage: --phase <phaseId>\n")
        return 2
    if git_root_prefix == "__MISSING__":
        sys.stderr.write("usage: --git-root <prefix>\n")
        return 2

    conditions = list(DEFAULT_GATE)
    if "--fail-on" in args:
        i = args.index("--fail-on")
        if i + 1 >= len(args):
            sys.stderr.write("usage: --fail-on <%s>[,...]\n" % "|".join(CONDITIONS))
            return 2
        conditions = [c.strip() for c in args[i + 1].split(",") if c.strip()]
        unknown = [c for c in conditions if c not in CONDITIONS]
        if unknown:
            sys.stderr.write("unknown condition(s): %s (known: %s)\n"
                             % (", ".join(unknown), ", ".join(CONDITIONS)))
            return 2
        del args[i:i + 2]
    if len(args) != 1:
        sys.stderr.write(
            "usage: audit-status.py <manifest> [--json] [--gate] [--phase <id>] "
            "[--fail-on <c1,c2,...>] [--submodules <.gitmodules> [--git-root <prefix>]]\n")
        return 2

    try:
        manifest = _mio.load_manifest(args[0])
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n" % (args[0], exc))
        return 2
    if not isinstance(manifest, dict):
        sys.stderr.write("ERROR: %s is not a JSON object (got %s)\n"
                         % (args[0], type(manifest).__name__))
        return 2

    if gitmodules is not None:
        if gitmodules == "__MISSING__":
            sys.stderr.write("usage: --submodules <path-to-.gitmodules>\n")
            return 2
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
                     usage=usage_summary(manifest, args[0]))

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
                                 % (only_phase, args[0], ", ".join(
                                     str(k) for k in known)))
                return 2
        print(render_status(manifest, summary, only_phase=only_phase))

    if want_gate:
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
                }.get(c, "")
                print("GATE FAILED: %s (%s)" % (c, detail))
            return 1
        print("GATE PASSED: %s" % ", ".join(conditions))
    return 0


# --- selftest -------------------------------------------------------------------
def _fixture():
    return {
        "meta": {"version": 2},
        "phases": [
            {"id": "P1", "title": "Done phase", "status": "done", "tasks": [
                {"id": "P1.1", "title": "t", "status": "done",
                 "files": ["src/a.ts"]},
            ]},
            {"id": "P2", "title": "Next phase", "status": "pending",
             "blockedBy": ["P1"], "tasks": [
                 {"id": "P2.1", "title": "ready", "status": "pending",
                  "dependsOn": [], "files": ["src/b.ts"]},
                 {"id": "P2.2", "title": "waits", "status": "pending",
                  "dependsOn": ["P2.1"]},
             ]},
        ],
        "fileIndex": {"src/a.ts": ["P1.1"], "src/b.ts": ["P2.1"]},
        "bugs": [
            {"id": "BUG-1", "title": "fixed one", "status": "fixed",
             "severity": "high"},
        ],
    }


def _selftest():
    import copy

    results = []
    vm = _load_validator()

    def summarize(m):
        findings, warnings = vm.validate(m)
        return rollup(m, findings, warnings)

    def check(name, ok, detail=""):
        results.append(ok)
        print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                           (" (%s)" % detail) if detail and not ok else ""))

    # (r) readiness mirrors /audit's rule
    s = summarize(_fixture())
    check("r1 ready = dependency-satisfied pending tasks", s["ready"] == ["P2.1"],
          repr(s["ready"]))
    m = copy.deepcopy(_fixture())
    m["phases"][0]["status"] = "pending"
    m["phases"][0]["tasks"][0]["status"] = "pending"
    s = summarize(m)
    check("r2 phase blockedBy gates readiness",
          "P2.1" not in s["ready"] and "P1.1" in s["ready"], repr(s["ready"]))

    # (ar) area tag(s) — normalized to a list, surfaced per phase + grouped in rollup;
    # a phase may carry several cross-cutting tags (e.g. ['mobile', 'security'])
    m = copy.deepcopy(_fixture())
    m["phases"][0]["area"] = "backend"                 # single string
    m["phases"][1]["area"] = ["mobile", "security"]    # cross-cutting tags
    s = summarize(m)
    check("ar1 area normalized to a list per phase",
          s["phases"][0]["area"] == ["backend"]
          and s["phases"][1]["area"] == ["mobile", "security"])
    check("ar2 areas grouping counts phases + tasks",
          set(s["areas"].keys()) == {"backend", "mobile", "security"}
          and s["areas"]["backend"]["phases"] == 1
          and s["areas"]["backend"]["total"] == s["phases"][0]["total"], repr(s["areas"]))
    check("ar3 a multi-tag phase counts under EACH of its areas",
          s["areas"]["mobile"]["phases"] == 1 and s["areas"]["security"]["phases"] == 1
          and s["areas"]["security"]["total"] == s["phases"][1]["total"], repr(s["areas"]))
    s0 = summarize(_fixture())
    check("ar4 untagged manifest -> empty areas (back-compat)", s0["areas"] == {})
    # A repeated tag used to count its phase twice under that one tag, so a phase
    # that was 1-of-1 done read 2/2 in the per-area totals — a completion figure
    # over 100% on the one surface a monorepo reader looks at first.
    m_dup = copy.deepcopy(_fixture())
    m_dup["phases"][0]["area"] = ["backend", "backend", " backend "]
    s_dup = summarize(m_dup)
    check("ar5 a tag repeated on one phase counts once, and matches trimmed",
          s_dup["phases"][0]["area"] == ["backend"]
          and s_dup["areas"]["backend"]["phases"] == 1
          and s_dup["areas"]["backend"]["total"] == s_dup["phases"][0]["total"],
          repr(s_dup["areas"]))

    # (u) usage block — absent unless a ledger exists, so every existing consumer
    # keeps working untouched
    check("u1 no ledger -> no usage key (back-compat)",
          "usage" not in summarize(_fixture()))
    # --- (s) the human status renderer -------------------------------------------------
    _fx = _fixture()
    _sum = rollup(_fx, [], [])
    _txt = render_status(_fx, _sum)

    check("s1 render is pure ASCII (the fixture carries no non-ascii data)",
          all(ord(c) < 128 for c in _txt))
    check("s2 render carries no ANSI escapes", "\033" not in _txt)
    check("s3 render has no box-drawing or emoji",
          not any(0x2500 <= ord(c) <= 0x27BF or ord(c) > 0x1F000 for c in _txt))
    check("s4 the overall line names tasks, phases, bugs and ready",
          "tasks done" in _txt and "phases signed off" in _txt
          and "open bug(s)" in _txt and "ready now" in _txt)
    check("s5 every status marker is used for the statuses present",
          "[x] P1.1" in _txt and "[ ] P2.1" in _txt)
    check("s6 the column header appears exactly once, not per phase",
          _txt.count("waiting on") == 1, str(_txt.count("waiting on")))
    # The base fixture's P1 is `done`, so P2's gate is SATISFIED and there is
    # nothing to report — asserting otherwise tested the wrong premise. A genuinely
    # unmet gate needs an unfinished P1.
    _fx_gate = copy.deepcopy(_fx)
    _fx_gate["phases"][0]["status"] = "in_progress"
    _fx_gate["phases"][0]["tasks"][0]["status"] = "in_progress"
    _txt_g = render_status(_fx_gate, rollup(_fx_gate, [], []))
    check("s7 a blocked phase says what it waits on",
          "blocked by: P1" in _txt_g, _txt_g)
    check("s8 a task inherits its phase's gate in 'waiting on'",
          "P1 (phase)" in _txt_g)
    check("s8b a satisfied gate reports nothing rather than an empty warning",
          "blocked by:" not in _txt)
    check("s9 a task waiting on a sibling names it", "P2.1" in _txt)
    check("s10 the ready list carries a copy-pasteable run command",
          "/audit:run P2.1" in _txt)
    check("s11 no usage line when metering is absent", "usage:" not in _txt)

    # usage line: present, and honest about showCost
    _u = {"ledgerDir": "/tmp/x", "showCost": True,
          "totals": {"tokens": 1234567, "costUSD": 4.5},
          "byPhase": {"P2": {"tokens": 500, "costUSD": 1.0}}}
    _txt_u = render_status(_fx, rollup(_fx, [], [], usage=_u))
    check("s12 usage line appears when a ledger exists", "usage: 1.2M tok" in _txt_u)
    check("s13 usage line shows cost when showCost is true", "equiv" in _txt_u)
    _u2 = dict(_u, showCost=False)
    _txt_u2 = render_status(_fx, rollup(_fx, [], [], usage=_u2))
    check("s14 cost is withheld when showCost is false "
          "(naming dollars would leak what the setting hides)",
          "equiv" not in _txt_u2 and "usage:" in _txt_u2)
    check("s15 no 'this phase' clause when nothing is running",
          "this phase" not in _txt_u)
    # The rate basis. It belongs on THIS surface in particular: the budget lines
    # printed under it are what the preflight check acts on, and a number that can
    # stop a phase should say what priced it.
    check("s15a the rate basis is stated when the manifest declares one",
          "rates as of 2026-08-06" in render_status(
              _fx, rollup(_fx, [], [], usage=dict(_u, pricingAsOf="2026-08-06"))))
    check("s15b and says so when it does not, rather than printing dollars that "
          "look pinned to a table nobody named",
          "rates undated" in _txt_u and "usage.pricingAsOf" in _txt_u)
    check("s15c it never falls back to the default table's date - that would "
          "manufacture a basis instead of stating one",
          "rates as of" not in _txt_u)
    check("s15d withheld with the dollars when showCost is false",
          "rates" not in _txt_u2)
    check("s15e and silent when there is no spend to price at all",
          "rates" not in render_status(
              _fx, rollup(_fx, [], [], usage=dict(_u, totals={"tokens": 0}))))

    # a running phase gets the phase clause and the RESUMABLE line
    _fx_run = copy.deepcopy(_fx)
    _fx_run["phases"][1]["status"] = "in_progress"
    _fx_run["phases"][1]["branch"] = "audit/p2-next"
    _txt_r = render_status(_fx_run, rollup(_fx_run, [], [], usage=_u))
    check("s16 a running phase adds the 'this phase' clause",
          "this phase 500" in _txt_r)
    check("s17 an interrupted phase is flagged as resumable",
          "RESUMABLE" in _txt_r and "/audit:resume" in _txt_r)
    check("s18 the phase branch is shown", "audit/p2-next" in _txt_r)

    # invalid manifest must be stated, not implied
    _txt_bad = render_status(_fx, rollup(_fx, ["boom"], []))
    check("s19 an invalid manifest is stated in the render",
          "INVALID MANIFEST" in _txt_bad)

    # open bugs, and the ready-fix cross-link
    check("s20 a closed bug is not listed as open",
          "BUG-1" not in _txt.split("BUGS")[-1] if "BUGS" in _txt else True)
    _fx_bug = copy.deepcopy(_fx)
    _fx_bug["bugs"] = [{"id": "BUG-9", "title": "live one", "status": "open",
                        "severity": "high", "taskId": "P2.1"}]
    _txt_b = render_status(_fx_bug, rollup(_fx_bug, [], []))
    check("s21 an open bug is listed", "BUG-9" in _txt_b)
    check("s22 a bug whose fix is ready says so",
          "its fix is READY: /audit:run P2.1" in _txt_b)

    # truncation must not read as corruption
    check("s23 clipping marks elision rather than cutting mid-word",
          _clip("Fix BUG-3: cart total off-by-one with stacked discounts", 44)
          .endswith("...")
          and not _clip("Fix BUG-3: cart total off-by-one with stacked", 44)
          .endswith(" ..."))
    check("s24 short text is never clipped", _clip("short", 44) == "short")

    # an empty plan must not crash or lie
    _empty = {"meta": {"version": 2}, "phases": []}
    _txt_e = render_status(_empty, rollup(_empty, [], []))
    check("s25 an empty manifest renders without raising", "AUDIT" in _txt_e)
    check("s26 an empty manifest says nothing is ready rather than showing a list",
          "nothing" in _txt_e)

    # A wide-open plan folds the ready list and states the count. Silent truncation
    # would read as "that is all of them" — the worst failure for a to-do list.
    _many = {"meta": {"version": 2}, "phases": [
        {"id": "P1", "title": "wide", "status": "pending", "tasks": [
            {"id": "P1.%d" % i, "title": "t%d" % i, "status": "pending"}
            for i in range(1, 40)]}]}
    _txt_m = render_status(_many, rollup(_many, [], []))
    check("s27 the ready list states the true total, not the shown count",
          "READY NOW  39 task(s)" in _txt_m, _txt_m.split("READY NOW")[1][:60])
    check("s28 the fold is announced with the remainder",
          "and %d more" % (39 - READY_LIST_MAX) in _txt_m)
    check("s29 the fold points at the command that runs the next one",
          "/audit:next" in _txt_m)
    _shown = [ln for ln in _txt_m.split("\n") if "run: /audit:run" in ln]
    check("s30 exactly READY_LIST_MAX rows are listed",
          len(_shown) == READY_LIST_MAX, str(len(_shown)))

    # (sp) proposals — parked phases must surface in status, not only in the file
    _fx_p = copy.deepcopy(_fx)
    _fx_p["proposals"] = [
        {"id": "PROP-1", "name": "Security hardening", "status": "proposed",
         "payload": {"phase": {"id": "P3", "title": "Security hardening",
                               "status": "pending",
                               "tasks": [{"id": "P3.1", "title": "t",
                                          "status": "pending"}]}}},
        {"id": "PROP-2", "name": "Old idea", "status": "dropped"},
    ]
    _sum_p = rollup(_fx_p, [], [])
    check("sp1 no proposals -> no PROPOSALS block (back-compat)",
          "PROPOSALS" not in _txt)
    check("sp4 rollup carries proposals {total, byStatus, parked}",
          _sum_p.get("proposals", {}).get("total") == 2
          and _sum_p.get("proposals", {}).get("parked") == 1
          and _sum_p.get("proposals", {}).get("byStatus", {}).get("proposed") == 1,
          repr(_sum_p.get("proposals")))
    _txt_p = render_status(_fx_p, _sum_p)
    check("sp2 a parked proposal renders id, reserved phase, task count and the "
          "materialize command",
          "PROP-1" in _txt_p and "P3 (1 task" in _txt_p
          and "/audit:propose materialize PROP-1" in _txt_p,
          _txt_p.split("PROPOSALS")[-1][:120] if "PROPOSALS" in _txt_p else _txt_p[-120:])
    check("sp5 materialized/dropped proposals are not listed as parked",
          "PROP-2" not in _txt_p)
    # a legacy free-form parked entry is listed but gets no materialize command
    # (there is no payload to materialize)
    _fx_leg = copy.deepcopy(_fx)
    _fx_leg["proposals"] = [{"id": "modernize-build", "name": "Modernize build",
                             "status": "proposed"}]
    _txt_leg = render_status(_fx_leg, rollup(_fx_leg, [], []))
    check("sp6 a legacy parked entry lists without a materialize command",
          "modernize-build" in _txt_leg
          and "materialize modernize-build" not in _txt_leg)
    _empty_p = {"meta": {"version": 2}, "phases": [],
                "proposals": _fx_p["proposals"][:1]}
    _txt_ep = render_status(_empty_p, rollup(_empty_p, [], []))
    check("sp3 an empty plan with parked proposals points at /audit:propose",
          "parked proposal" in _txt_ep and "/audit:propose" in _txt_ep,
          _txt_ep[:200])
    _few = {"meta": {"version": 2}, "phases": [
        {"id": "P1", "title": "narrow", "status": "pending", "tasks": [
            {"id": "P1.1", "title": "t", "status": "pending"}]}]}
    # --phase scopes the listing without rescoping the totals.
    _p1 = render_status(_fx, _sum, only_phase="P1")
    check("s32 --phase lists only that phase",
          "P1.1" in _p1 and "P2.1" not in _p1.split("READY NOW")[0])
    check("s33 --phase says the totals stay whole-plan",
          "totals above are whole-plan" in _p1)
    check("s34 --phase keeps the whole-plan overall line",
          "1/2 tasks done" in _p1 or "tasks done" in _p1)
    check("s35 no scope note when unscoped",
          "scoped to phase" not in _txt)

    check("s31 a short list is not annotated as folded",
          "more" not in render_status(_few, rollup(_few, [], []))
          .split("READY NOW")[1].split("BUGS")[0])

    # --- (h) the words a person reads (v0.28) -----------------------------------
    # `in_progress` is how a status travels; it is not how it should ever arrive.
    # The report and the panel have humanised statuses since c3/c2 — the terminal,
    # which is the surface an actual run is watched on, still printed the machine
    # spelling in three places.
    _fx_h = copy.deepcopy(_fx)
    _fx_h["phases"][1]["status"] = "in_progress"
    _fx_h["phases"][1]["tasks"][0]["status"] = "in_progress"
    _fx_h["bugs"] = [{"id": "BUG-9", "title": "live", "status": "in_progress",
                      "severity": "high"}]
    _txt_h = render_status(_fx_h, rollup(_fx_h, [], []))
    check("h1 no machine status spelling survives anywhere in the render - "
          "the phase row, the task table, the bug list and the RESUMABLE line",
          "in_progress" not in _txt_h, _txt_h)
    check("h2 ...and the words are actually there, in each of the four places",
          "In progress" in _txt_h.split("task")[0] or "In progress" in _txt_h,
          _txt_h)
    check("h3 the phase row reads as words",
          re.search(r"P2\s+Next phase\s+In progress", _txt_h) is not None, _txt_h)
    check("h4 the RESUMABLE line reads as a sentence, not as an identifier",
          "is in progress" in _txt_h, _txt_h)
    check("h5 the bug list humanises its own status vocabulary",
          re.search(r"BUG-9\s+In progress", _txt_h) is not None, _txt_h)
    check("h6 the markers are unchanged - they are the legend commands/status.md "
          "documents, and they key off the machine value",
          "[~] P2.1" in _txt_h and "[x] P1.1" in _txt_h)

    # --- (e) area + effective reviewer (v0.28) ----------------------------------
    _fx_a = copy.deepcopy(_fx)
    _fx_a["meta"]["reviewSkill"] = "house-review"
    _fx_a["meta"]["areas"] = {"api": {"root": "src", "reviewSkill": "backend-review"},
                              "web": {"root": "web"}}
    _fx_a["phases"][0]["area"] = ["api", "web"]
    _fx_a["phases"][1]["area"] = "web"
    _txt_a = render_status(_fx_a, rollup(_fx_a, [], []))
    check("e1 a phase prints its area tags, which the terminal never showed at all",
          "area: api, web" in _txt_a, _txt_a)
    check("e2 the effective reviewer is resolved, not left to the reader",
          "review: backend-review (area api)" in _txt_a, _txt_a)
    check("e3 a phase whose areas answer nothing falls through to meta, and says so",
          "review: house-review (meta)" in _txt_a, _txt_a)
    _fx_a2 = copy.deepcopy(_fx_a)
    _fx_a2["phases"][0]["reviewSkill"] = "phase-review"
    check("e4 a phase override is named as the phase's own",
          "review: phase-review (phase)" in
          render_status(_fx_a2, rollup(_fx_a2, [], [])))
    check("e5 an ordinary single-app repo pays nothing for this: no tags and no "
          "reviewer means no line", "area:" not in _txt and "review:" not in _txt)
    _fx_a3 = copy.deepcopy(_fx)
    _fx_a3["phases"][0]["area"] = "solo"
    _txt_a3 = render_status(_fx_a3, rollup(_fx_a3, [], []))
    check("e6 tags print without a registry - registration is optional",
          "area: solo" in _txt_a3 and "review:" not in _txt_a3, _txt_a3)
    check("e7 the scope line stays pure ASCII like the rest of the render",
          all(ord(c) < 128 for c in _txt_a))

    # --- (ba) BY AREA block (D2) ------------------------------------------------
    # The per-area rollup has been computed and shipped in --json since the tags
    # existed; the terminal never printed it. These pin the printed block to the
    # SAME rollup, never a re-derivation.
    check("ba1 no area tags -> no BY AREA block (back-compat)",
          "BY AREA" not in _txt)
    _fx_ba = copy.deepcopy(_fx)
    _fx_ba["phases"][0]["area"] = "backend"
    _fx_ba["phases"][1]["area"] = ["backend"]
    _txt_ba = render_status(_fx_ba, rollup(_fx_ba, [], []))
    check("ba2 a tagged plan renders per-tag phases, tasks and a bar",
          "BY AREA" in _txt_ba
          and re.search(r"backend\s+2 phase\(s\)\s+\[[#.]+\] 1/3 tasks",
                        _txt_ba) is not None,
          _txt_ba.split("BY AREA")[-1][:160] if "BY AREA" in _txt_ba
          else _txt_ba[-160:])
    check("ba3 the header counts tags and tagged phases",
          "BY AREA  1 tag(s) - 2 of 2 phase(s) tagged" in _txt_ba, _txt_ba)
    check("ba4 a fully tagged single-tag plan gets no untagged footer and no "
          "caveat - nothing to warn about",
          "untagged" not in _txt_ba and "counts under each" not in _txt_ba,
          _txt_ba)
    _fx_bm = copy.deepcopy(_fx)
    _fx_bm["phases"][0]["area"] = ["mobile", "security"]   # P2 stays untagged
    _txt_bm = render_status(_fx_bm, rollup(_fx_bm, [], []))
    check("ba5 a multi-tag phase shows the same figures under EACH of its tags",
          re.search(r"mobile\s+1 phase\(s\)\s+\[[#.]+\] 1/1 tasks",
                    _txt_bm) is not None
          and re.search(r"security\s+1 phase\(s\)\s+\[[#.]+\] 1/1 tasks",
                        _txt_bm) is not None, _txt_bm)
    check("ba6 untagged phases get a footer row with the same figures",
          re.search(r"untagged\s+1 phase\(s\)\s+\[[#.]+\] 0/2 tasks",
                    _txt_bm) is not None, _txt_bm)
    check("ba7 the multi-tag caveat is stated - per-area sums can pass the total",
          "counts under each" in _txt_bm
          and "exceed the plan total" in _txt_bm, _txt_bm)
    check("ba8 the block stays pure ASCII like the rest of the render",
          all(ord(c) < 128 for c in _txt_bm))
    check("ba9 a fully done area draws a full bar - the same bar helper as the "
          "phase rows", "[############] 1/1 tasks" in _txt_bm, _txt_bm)

    # --- (b) budget as a gate --------------------------------------------------
    def _with_budgets(*phase_rows):
        """A summary carrying only the budget block the gate reads."""
        return {"valid": True, "findings": 0, "warnings": 0, "phases": [],
                "tasks": {"total": 0, "byStatus": {}},
                "bugs": {"total": 0, "byStatus": {}, "open": 0,
                         "openHighSeverity": 0},
                "ready": [],
                "usage": {"showCost": True, "totals": {"tokens": 1, "costUSD": 1.0},
                          "budgets": {"phases": list(phase_rows)}}}

    _over = {"id": "P2", "title": "t", "budget": 25.0, "spent": 32.5,
             "pct": 130.0, "over": True}
    _warn = {"id": "P1", "title": "t", "budget": 40.0, "spent": 34.0,
             "pct": 85.0, "over": False}
    _fine = {"id": "P3", "title": "t", "budget": 40.0, "spent": 4.0,
             "pct": 10.0, "over": False}
    _none = {"id": "P4", "title": "t", "budget": None, "spent": 9.0,
             "pct": None, "over": False}

    check("b1 over-budget trips at 100%+",
          evaluate_gate(_with_budgets(_over), ["over-budget"]) == ["over-budget"])
    check("b2 over-budget does NOT trip at 85%",
          evaluate_gate(_with_budgets(_warn), ["over-budget"]) == [])
    check("b3 budget-80 trips at 85%",
          evaluate_gate(_with_budgets(_warn), ["budget-80"]) == ["budget-80"])
    check("b4 budget-80 does not trip at 10%",
          evaluate_gate(_with_budgets(_fine), ["budget-80"]) == [])
    check("b5 a phase with no budget never trips either condition",
          evaluate_gate(_with_budgets(_none), ["over-budget", "budget-80"]) == [])
    check("b6 no usage block at all trips nothing (a repo without metering)",
          evaluate_gate(rollup(_fixture(), [], []),
                        ["over-budget", "budget-80"]) == [])
    check("b7 neither budget condition is in the default gate "
          "(spend is a signal, not a defect someone else's merge fails on)",
          "over-budget" not in DEFAULT_GATE and "budget-80" not in DEFAULT_GATE)
    check("b8 both are accepted by --fail-on",
          "over-budget" in CONDITIONS and "budget-80" in CONDITIONS)

    check("b9 the gate detail names the phase and both numbers, not just a count",
          "P2" in _budget_detail(_with_budgets(_over), 100.0)
          and "130%" in _budget_detail(_with_budgets(_over), 100.0)
          and "$25.00" in _budget_detail(_with_budgets(_over), 100.0))
    check("b10 the detail folds beyond three phases",
          "+1 more" in _budget_detail(
              _with_budgets(dict(_over, id="A"), dict(_over, id="B"),
                            dict(_over, id="C"), dict(_over, id="D")), 100.0))
    check("b11 breaches are ordered worst-first",
          _budget_detail(_with_budgets(_warn, _over), 80.0).startswith("P2"))

    # the rendered budget lines
    _bl = render_status({"meta": {}, "phases": []}, _with_budgets(_over, _warn, _none))
    check("b12 an over-budget phase is flagged OVER", "OVER" in _bl)
    check("b13 a phase past the warn threshold is flagged WARN", "WARN" in _bl)
    check("b14 an unbudgeted phase is footnoted, not drawn at 0%",
          "declare none" in _bl and "not phases at zero" in _bl)
    check("b15 the overrun percentage is shown uncapped",
          "130%" in _bl)
    _bl_nb = render_status({"meta": {}, "phases": []}, _with_budgets(_none))
    check("b16 nothing is rendered when no phase declares a budget",
          "budget" not in _bl_nb)
    _sum_nc = _with_budgets(_over)
    _sum_nc["usage"]["showCost"] = False
    check("b17 budget lines are withheld when showCost is false",
          "budget" not in render_status({"meta": {}, "phases": []}, _sum_nc))

    check("u2 rollup(usage=None) omits the key",
          "usage" not in rollup(_fixture(), [], [], usage=None))
    fake_usage = {"ledgerDir": "/tmp/x", "totals": {"tokens": 10, "costUSD": 1.0}}
    su = rollup(_fixture(), [], [], usage=fake_usage)
    check("u3 rollup passes a supplied usage block straight through",
          su["usage"] == fake_usage)
    check("u4 usage never perturbs the rest of the rollup",
          {k: v for k, v in su.items() if k != "usage"} == summarize(_fixture()))
    import tempfile as _tf
    _empty = _tf.mkdtemp(prefix="audit-status-usage-")
    try:
        check("u5 usage_summary tolerates a missing ledger dir",
              usage_summary({}, os.path.join(_empty, "a", "b", "m.json")) is None)
        os.makedirs(os.path.join(_empty, ".claude", "usage"), exist_ok=True)
        check("u6 usage_summary tolerates an empty ledger dir",
              usage_summary({}, os.path.join(_empty, "docs", "audit", "m.json"),
                            project_dir=_empty) is None)
        with open(os.path.join(_empty, ".claude", "usage", "2026-08.jsonl"),
                  "w", encoding="utf-8") as _fh:
            _fh.write(json.dumps({
                "ts": "2026-08-06T07", "sessionId": "s1", "phaseId": "P1",
                "taskId": "P1.1", "attr": "task", "model": "claude-opus-5",
                "author": "a@b.c", "msgs": 1, "in": 10, "out": 20,
                "cacheW5m": 0, "cacheW1h": 0, "cacheR": 5, "costUSD": 0.5}) + "\n")
        u = usage_summary({}, os.path.join(_empty, "docs", "audit", "m.json"),
                          project_dir=_empty)
        check("u7 usage_summary reads a real ledger",
              u and u["totals"]["tokens"] == 35 and u["totals"]["msgs"] == 1)
        check("u8 usage_summary groups by phase, model and author",
              "P1" in u["byPhase"] and "claude-opus-5" in u["byModel"]
              and "a@b.c" in u["byAuthor"])
        with open(os.path.join(_empty, ".claude", "usage", "2026-08.jsonl"),
                  "a", encoding="utf-8") as _fh:
            _fh.write("{ torn\n")
        check("u9 usage_summary survives a torn ledger line",
              usage_summary({}, os.path.join(_empty, "docs", "audit", "m.json"),
                            project_dir=_empty)["totals"]["tokens"] == 35)
    finally:
        import shutil as _sh
        _sh.rmtree(_empty, ignore_errors=True)

    # (g) gate conditions
    s = summarize(_fixture())
    check("g1 clean manifest passes default gate",
          evaluate_gate(s, DEFAULT_GATE) == [])
    m = copy.deepcopy(_fixture())
    m["bugs"].append({"id": "BUG-2", "title": "live", "status": "open",
                      "severity": "high"})
    s = summarize(m)
    check("g2 open high-severity bug trips", "open-high-bugs" in
          evaluate_gate(s, DEFAULT_GATE))
    m = copy.deepcopy(_fixture())
    m["bugs"].append({"id": "BUG-2", "title": "live", "status": "triaged",
                      "severity": "low"})
    s = summarize(m)
    check("g3 low-sev open bug passes default but trips open-bugs",
          evaluate_gate(s, DEFAULT_GATE) == []
          and "open-bugs" in evaluate_gate(s, ("open-bugs",)))

    # (d) derived bug status — a bug materialized into a DONE task reads as fixed
    #     even though bugs[].status is still 'open' (the orchestrator never writes
    #     bugs[] during a run, so the index stays untouched for parallel phases).
    dm = {"meta": {"version": 2},
          "phases": [{"id": "P0", "title": "P", "status": "in_progress", "tasks": [
              {"id": "P0.1", "title": "fix", "status": "done", "bugId": "BUG-1"}]}],
          "bugs": [{"id": "BUG-1", "title": "b", "status": "open", "severity": "high",
                    "taskId": "P0.1"}]}
    s = summarize(dm)
    check("d1 bug on a done task derives fixed (index untouched)",
          s["bugs"]["byStatus"].get("fixed", 0) == 1 and s["bugs"]["open"] == 0
          and s["bugs"]["openHighSeverity"] == 0
          and evaluate_gate(s, ("open-high-bugs", "open-bugs")) == [], repr(s["bugs"]))
    dm2 = copy.deepcopy(dm)
    dm2["phases"][0]["tasks"][0]["status"] = "in_progress"
    s2 = summarize(dm2)
    check("d2 bug on a not-done task stays open",
          s2["bugs"]["open"] == 1 and s2["bugs"]["byStatus"].get("open", 0) == 1,
          repr(s2["bugs"]))
    m = copy.deepcopy(_fixture())
    m["phases"][1]["tasks"][0]["status"] = "blocked"
    s = summarize(m)
    check("g4 blocked task trips", "blocked-tasks" in
          evaluate_gate(s, DEFAULT_GATE))
    m = copy.deepcopy(_fixture())
    m["phases"][1]["tasks"][0]["status"] = "doing"  # invalid enum
    s = summarize(m)
    check("g5 validator findings trip invalid", "invalid" in
          evaluate_gate(s, DEFAULT_GATE) and s["valid"] is False)
    m = copy.deepcopy(_fixture())
    m["phases"][1]["status"] = "in_progress"
    s = summarize(m)
    check("g6 in-progress trips only when asked",
          evaluate_gate(s, DEFAULT_GATE) == []
          and "in-progress" in evaluate_gate(s, ("in-progress",)))

    # (g7) open-high-bugs catches high-OR-WORSE severities, not only "high"
    for sev in ("critical", "Blocker", "sev1", "P0", "URGENT", "sev-1"):
        m = copy.deepcopy(_fixture())
        m["bugs"].append({"id": "BUG-9", "title": "bad", "status": "open",
                          "severity": sev})
        s = summarize(m)
        check("g7 open %r bug trips open-high-bugs" % sev,
              "open-high-bugs" in evaluate_gate(s, DEFAULT_GATE))
    # a genuinely low severity must still NOT trip it (no false positive)
    m = copy.deepcopy(_fixture())
    m["bugs"].append({"id": "BUG-9", "title": "minor", "status": "open",
                      "severity": "low"})
    s = summarize(m)
    check("g8 open low-severity bug does NOT trip open-high-bugs",
          "open-high-bugs" not in evaluate_gate(s, DEFAULT_GATE))

    # (nd) a non-object manifest root must never crash the rollup path
    check("nd1 rollup on list root -> empty, no crash",
          rollup([], [], [])["tasks"]["total"] == 0)
    check("nd2 ready_tasks on None root -> [], no crash", ready_tasks(None) == [])
    check("nd3 submodule_conflicts on scalar root -> [], no crash",
          submodule_conflicts("nope", ["vendor/x"]) == [])

    # (j) --json output round-trips with the expected fields
    blob = json.loads(json.dumps(summarize(_fixture())))
    check("j1 rollup fields present",
          blob["tasks"]["total"] == 3 and blob["bugs"]["total"] == 1
          and blob["phases"][0]["done"] == 1 and blob["valid"] is True)

    # (s) submodule conflict detection
    check("s1 parse_gitmodules extracts paths", parse_gitmodules(
        '[submodule "vendor/child"]\n\tpath = vendor/child\n\turl = ../child\n'
        '[submodule "libs/x"]\n  path = libs/x\n  url = ../x\n')
        == ["vendor/child", "libs/x"])
    subm = {"meta": {"version": 2}, "phases": [{"id": "P0", "title": "p",
        "status": "pending", "tasks": [
            {"id": "P0.1", "title": "in submodule", "status": "pending",
             "files": ["vendor/child/src/foo.ts"]},
            {"id": "P0.2", "title": "boundary — NOT in submodule", "status": "pending",
             "files": ["vendor/child-other/x.ts"]},
            {"id": "P0.3", "title": "outside", "status": "pending",
             "files": ["src/app.ts"]},
        ]}]}
    conf = submodule_conflicts(subm, ["vendor/child"])
    check("s2 file inside submodule flagged", conf == [("P0.1", "vendor/child/src/foo.ts", "vendor/child")],
          repr(conf))
    check("s3 path-boundary: child-other NOT flagged",
          all(c[0] != "P0.2" for c in conf))
    # git_root prefix stripping: files are project-relative, submodules git-root-relative
    subm_gr = {"meta": {"version": 2}, "phases": [{"id": "P0", "title": "p",
        "status": "pending", "tasks": [{"id": "P0.1", "title": "t", "status": "pending",
        "files": ["test/vendor/child/src/foo.ts", "test/src/app.ts"]}]}]}
    conf_gr = submodule_conflicts(subm_gr, ["vendor/child"], git_root="test")
    check("s4 gitRoot prefix stripped before match",
          [c[0] for c in conf_gr] == ["P0.1"] and conf_gr[0][1].startswith("test/vendor"))
    check("s5 :line suffix tolerated", submodule_conflicts(
        {"meta": {}, "phases": [{"id": "P", "title": "p", "status": "pending",
         "tasks": [{"id": "P.1", "title": "t", "status": "pending",
                    "files": ["vendor/child/a.ts:10-20"]}]}]}, ["vendor/child"]) != [])

    # (c) CLI: exit codes 0 / 1 / 2
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(_fixture(), fh)
    check("c1 CLI gate passes clean manifest (exit 0)",
          main([path, "--gate"]) == 0)
    m = copy.deepcopy(_fixture())
    m["bugs"].append({"id": "BUG-2", "title": "live", "status": "open",
                      "severity": "high"})
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(m, fh)
    check("c2 CLI gate fails on open high bug (exit 1)",
          main([path, "--gate"]) == 1)
    check("c3 CLI usage error (exit 2)", main([]) == 2)
    check("c4 CLI unknown condition (exit 2)",
          main([path, "--gate", "--fail-on", "frobnicate"]) == 2)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    check("c5 CLI unreadable manifest (exit 2)", main([path, "--gate"]) == 2)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(["not", "an", "object"], fh)
    check("c5b CLI non-object JSON root (exit 2)", main([path, "--gate"]) == 2)
    os.unlink(path)

    # (cs) CLI --submodules mode
    fd, mpath = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(subm, fh)  # has P0.1 inside vendor/child
    fd, gm = tempfile.mkstemp(suffix=".gitmodules")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write('[submodule "vendor/child"]\n\tpath = vendor/child\n\turl = ../child\n')
    check("cs1 CLI flags submodule conflict (exit 1)",
          main([mpath, "--submodules", gm]) == 1)
    check("cs2 CLI clean when no .gitmodules (exit 0)",
          main([mpath, "--submodules", os.path.join(tempfile.gettempdir(), "nope.gitmodules")]) == 0)
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump({"meta": {"version": 2}, "phases": [{"id": "P", "title": "p",
            "status": "pending", "tasks": [{"id": "P.1", "title": "t",
            "status": "pending", "files": ["src/app.ts"]}]}]}, fh)
    check("cs3 CLI clean when no task in a submodule (exit 0)",
          main([mpath, "--submodules", gm]) == 0)
    os.unlink(mpath)
    os.unlink(gm)

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
