#!/usr/bin/env python3
"""
What the manifest SAYS, as a machine-readable answer — the half of status nobody prints.

`audit-status.py` does two things that look like one: it computes the facts (which
tasks are ready, what each phase adds up to, which gate conditions failed, which
files sit inside a submodule) and it renders them for a person. Only the first is
shared. This module is that first half, and `audit-status.py` is the command that
prints it.

WHY THE SPLIT EXISTS. Three modules wanted the facts and none of them wanted the
rendering: `_panel_state` (layer 5) needs `rollup` for the panel's overview,
`audit-doctor` needs `submodule_conflicts` for its preflight, and `render-report`
needs `evaluate_gate` for the verdict at the top of the report. All three reached
them the only way a hyphenated entry point can be reached —
`_loader.load_script("audit-status.py")` — and `_deps.layer_violations()` counts
those calls, so three of the seventeen entries in `KNOWN_LAYER_DEBT` were this one
file being used as a library. Layer 2 is where all three can import it, and it is
low enough because everything here reaches only `_manifest_io` and `_areas` at
layer 1.

THE REPORT'S GATE VERDICT IS THE CASE WORTH KNOWING ABOUT. `render-report.py`
computes the verdict at layer 7 and INJECTS it into `_report_page` (layer 6),
specifically so a helper never reaches up to an entry point for it. That dance was
forced by the gate living inside a command; `evaluate_gate` and `DEFAULT_GATE` are
here now, so the constraint is gone even though the injection stayed — changing
the wiring is a separate question from retiring the edge, and one change should
not quietly answer both.

PURE, AND THAT IS WHAT MAKES IT SHAREABLE. Every function here takes parsed JSON
(or, for `parse_gitmodules`, text a caller already read) and returns a value. No
file is opened, no process is run, no module state is written. `usage_summary`
and `discovery_block` do read the world, so they stayed in `audit-status.py`
where a command can own their failure modes.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__status_facts.py` — see `plugins/audit/tests/_harness.py`.
"""
import re
import os
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

import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR index+shards)
import _manifest_vocab  # noqa: E402  (the FULL_STATUS words - the third place's answers)
import _areas  # noqa: E402  (meta.areas registry + the resolution every surface shares)
import _priority  # noqa: E402  (the ONE expression of execution order, and the skip note)
import _usage_core  # noqa: E402  (parse_ts — the tree's one ISO reader, at layer 1)
import _filed_returns as _fr  # noqa: E402  (INTENT_DEFERRED: the word a close writes for an answer still owed)

# --- vocabulary -----------------------------------------------------------------
CONDITIONS = ("invalid", "open-high-bugs", "open-bugs", "blocked-tasks",
              "in-progress", "over-budget", "budget-80", "invariant-breach",
              "failing-tests", "no-test-evidence", "stranded-skills",
              "unfinished-run", "provisional", "stale-full-run",
              "unknown-full-run")
# The conditions whose reader grades `summary["fullRun"]`, a block
# `audit-status.py` pays a ledger read and git calls to inject, so it fetches it
# under --gate only when one of these was named. Declared here, beside the
# readers, so the command's fetch predicate is not a hand-kept copy of the list:
# a reader added without joining this tuple would be handed no block and read
# "never asked" on every run. A case derives the readers from `evaluate_gate`
# and pins them against this tuple.
FULL_RUN_CONDITIONS = ("provisional", "stale-full-run", "unknown-full-run")
# Neither budget condition is in the default gate. Spend is a signal, not a defect:
# a phase at 105% may be entirely justified, and failing someone's merge over it
# without them asking would make the whole gate something to switch off. Opt in with
# --fail-on when a budget is a commitment rather than an estimate.
#
# NEITHER TEST-EVIDENCE CONDITION IS IN IT EITHER, and `no-test-evidence` least of
# all: a repository that has never recorded a run carries no pointers anywhere, so
# a default holding it would fail every build on the day the plugin was upgraded --
# which is exactly the "adding a key changes behaviour for a config that does not
# set it" failure COMPATIBILITY.md refuses. `failing-tests` is out one step along
# the same road: a plan holding a red pointer somebody has already triaged would
# start blocking merges nobody asked it to block. Both are opt-in, and moving
# either into this tuple is a deliberate edit a case makes you make on purpose.
#
# `stranded-skills` is out for the first of those reasons and one of its own: a
# plan naming a skill only its author has is a correct observation about a
# repository nobody may ever clone, and the doctor already says so at exit zero.
# A team that wants it enforced is a team that will type it.
#
# AND `unfinished-run` IS OUT FOR A REASON THAT IS ALMOST THE OPPOSITE: a lock
# lives in the shared git dir rather than in the working tree, so it is never
# cloned and never committed. A fresh checkout in CI therefore holds no lock at
# all and a default carrying this would grade a question that checkout cannot
# answer, while on the machine that IS running a phase it would trip on every
# invocation made during the run. It is for the surface that can see the lock -
# the operator's terminal, and a runner that keeps its clone between jobs.
#
# `provisional` AND `stale-full-run` ARE OUT FOR `no-test-evidence`'s OWN
# REASON, restated at the third place rather than borrowed by inference. A plan
# that has never recorded a FULL run - or has never declared `meta.fullGate` at
# all - carries no whole-bearing row anywhere, so a default holding either
# condition would fail every build the day this feature shipped, on every plan
# that had not yet adopted the third place. `provisional` trips on a merged
# phase this ledger has not yet certified whole; `stale-full-run` is the
# sharper claim inside it - a full run happened AFTER the phase landed and
# STILL does not contain it, which is a plan actively falling behind its own
# gate rather than merely not having reached it yet. Both stay something a team
# types on purpose.
#
# `unknown-full-run` IS OUT FOR THE SAME REASON AND ONE MORE. It is the third
# place's other unanswered state: not "not yet certified" but "could not be
# asked" - no mergedHead recorded, git unable to answer ancestry, or a ledger
# that could not be read. A plan with a pre-recorder phase carries no mergedHead
# on it, so a default holding this would fail such a build on upgrade exactly as
# `provisional` would; and an unreadable ledger is a fact about the checkout the
# gate ran on as much as about the plan.
DEFAULT_GATE = ("invalid", "open-high-bugs", "blocked-tasks")
# Warn threshold for the interactive path and the `budget-80` condition. 80% is far
# enough in to be real and early enough to act on.
BUDGET_WARN_PCT = 80.0
# DERIVED, not listed. `fixed` is this file's own word — it is what the
# derivation below PRODUCES — and the rest are the verdicts a person wrote, which
# `_manifest_io` owns beside the derivation they beat. Spelling the human half
# here as literals is how a bug closed with a word this tuple had not learned went
# on reading as open: the plan would have shown a permanent open row and
# `--fail-on open-bugs` would have held a merge on a report somebody had already
# settled.
CLOSED_BUG = ("fixed",) + _mio.HUMAN_BUG_VERDICT

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
    # `_mio.iter_tasks` also absorbs the non-dict-root guard this used to open
    # with: a scalar manifest yields no pairs rather than raising (case nd3).
    for _ph, t in _mio.iter_tasks(manifest):
        for f in t.get("files") or []:
            rel = _strip_git_root(f, git_root)
            for s in subs:
                if rel == s or rel.startswith(s + "/"):
                    out.append((t.get("id"), f, s))
                    break
    return out


# --- gate rollup ----------------------------------------------------------------
# `{phase id or task id: status}` — what a `blockedBy`/`dependsOn` ref resolves
# through. `ready_tasks` and `unmet_refs` each built this by hand, identically; it
# moved DOWN to `_manifest_io` when a third caller appeared that this module cannot
# serve — `_manifest_crossrefs` sits at layer 2 beside this one and needs the same
# map to say whether a PINNED phase is waiting on unfinished work. The name stays
# here because ~600 lines of rendering in `audit-status.py` spell it unqualified,
# and the tie-break reasoning went with the body. An alias, never a second walk.
_status_index = _mio.status_index


def _phase_positions(manifest):
    """`{id(phase dict): its index in phases[]}` — the manifest order, by object.

    Keyed by identity rather than by `phase["id"]` because a manifest with a
    duplicate or absent phase id is exactly the manifest the read-only surfaces
    must still render: an id-keyed map would give two phases one position and
    silently re-order the ready list of a plan the validator is already
    complaining about.
    """
    if not isinstance(manifest, dict):
        return {}
    return {id(ph): i for i, ph in enumerate(manifest.get("phases") or [])
            if isinstance(ph, dict)}


def ready_tasks(manifest):
    """Task ids ready to run — mirrors /audit's readiness rule: status pending,
    own blockedBy satisfied, own dependsOn all done, phase blockedBy satisfied
    ('satisfied' = referenced task/phase is done), then SORTED by phase priority.

    THE SORT IS THE WHOLE FEATURE AND IT CANNOT CHANGE THE SET. Readiness is
    decided above, exactly as before; `_priority.rank_ready` only re-orders what
    is already ready, so a `priority` can never make an unready task ready and
    can never step over a dependency. A manifest carrying no `priority` at all
    produces the list it produced before this sort existed — every key falls
    back to (phase index, walk order), which is the document order this loop
    already emitted.
    """
    status = _status_index(manifest)
    pos = _phase_positions(manifest)

    def satisfied(refs):
        return not _mio.unsatisfied(refs, status)

    rows = []
    # The phase arrives WITH the task, so its `blockedBy` needs no second lookup —
    # and a non-dict manifest yields no pairs, which is what makes the old
    # isinstance guard above redundant (case nd2 pins it).
    for ph, t in _mio.iter_tasks(manifest):
        if t.get("status") != "pending":
            continue
        if not satisfied(t.get("blockedBy")):
            continue
        if not satisfied(t.get("dependsOn")):
            continue
        if not satisfied(ph.get("blockedBy")):
            continue
        if t.get("id"):
            rows.append((ph, pos.get(id(ph), len(pos)), len(rows), t["id"]))
    return _priority.rank_ready(rows)


def readiness_projection(phase):
    """The part of one phase body that `ready_tasks` reads, and nothing else.

    Two copies of a phase whose projections are equal give the same ready set
    for that phase whatever else differs between them - a title, a
    description, an outcome or a note moves no task into or out of readiness.
    So a comparison of projections answers "did this edit move readiness",
    which a comparison of whole files, or a count of commits to the file,
    cannot: either reads a reworded description, or a merge that brought the
    file no content, as a change.

    Kept beside `ready_tasks` because it has to name the same fields: the
    task's id and status, its own `blockedBy` and `dependsOn`, and the phase's
    `status` and `blockedBy`, which `status_index` and the phase gate read.
    A field added to the readiness rule belongs here too.
    """
    if not isinstance(phase, dict):
        return None
    return {"id": phase.get("id"), "status": phase.get("status"),
            "blockedBy": phase.get("blockedBy"),
            "tasks": [{"id": t.get("id"), "status": t.get("status"),
                       "blockedBy": t.get("blockedBy"),
                       "dependsOn": t.get("dependsOn")}
                      if isinstance(t, dict) else t
                      for t in (phase.get("tasks") or [])]}


def with_live_bodies(manifest, reads):
    """A copy of `manifest` in which each phase `reads` hands a body for is
    that body, laid over this checkout's phase; the manifest handed in is
    left as it was.

    `reads` is `{phase id: {"body": phase dict or None, ...}}`. Reading a copy
    of a phase that lives elsewhere - a linked worktree's file, a branch tip -
    is a git call or another checkout's file, and this module opens nothing,
    so `_live_copy` reads it and the caller hands the body here. A read with no
    body means this checkout's own copy is the one to show, so the phase is
    left exactly as it is. Every fact downstream - the ready list, each
    phase's counts, the plan-wide tally - is then taken from the one plan
    this returns, so no surface can count a phase from a different copy than
    another surface shows.
    """
    if not isinstance(manifest, dict):
        return manifest
    bodies = {str(pid): (read or {}).get("body")
              for pid, read in (reads or {}).items()}
    phases = manifest.get("phases")
    if not isinstance(phases, list):
        return dict(manifest)
    laid = []
    for p in phases:
        body = bodies.get(str(p.get("id"))) if isinstance(p, dict) else None
        laid.append(dict(p, **body) if isinstance(body, dict) else p)
    return dict(manifest, phases=laid)


def row_copies(reads, unread=None):
    """`{phase id: {"live", "read", "basis"}}` - the copy each row says it
    came from.

    Only a row that is NOT this checkout's own live copy says anything: a
    phase read from another copy says which, and a phase that fell back to
    this checkout's copy says it shows that copy and that this may not be
    current. `read` is True only for the first kind - the row's counts hold
    another copy's work. A phase this plan does not hold has no row to say it
    on. `unread` is `_live_copy.in_flight`'s rows for branches that exist and
    were not read, carried as they are with `read` False.
    """
    out = dict((str(k), dict(v, read=False)) for k, v in (unread or {}).items())
    for pid, read in (reads or {}).items():
        if not isinstance(read, dict) or (read.get("own") and read.get("live")):
            continue
        if not read.get("own") and not read.get("counted"):
            continue
        out[str(pid)] = {"live": bool(read.get("live")),
                         "read": not read.get("own"),
                         "basis": "%s %s" % ("shows" if read.get("own")
                                             else "read from", read["basis"])}
    return out


def ready_counts(manifest, reads):
    """`{phase id: {"readyCount", "readyLive", "readyBasis"}}` for each read -
    the phase's OWN ready tasks in the plan with every live body laid over it,
    so the count is a share of the very ready list READY NOW prints."""
    live = with_live_bodies(manifest, reads)
    by_phase = ready_by_phase(live)
    out = {}
    for pid, read in (reads or {}).items():
        if not read.get("counted"):
            out[pid] = {"readyCount": None, "readyLive": False,
                        "readyBasis": read.get("basis")}
            continue
        out[pid] = {"readyCount": len(by_phase.get(pid) or []),
                    "readyLive": bool(read.get("live")),
                    "readyBasis": "counted from %s" % (read.get("basis"),)}
    return out


def live_view(manifest, flight):
    """`{"plan", "copies", "own", "note"}` - what a surface shows when a phase
    is in flight elsewhere, out of `_live_copy.in_flight`'s answer.

    THE ONE OVERLAY. `/audit:status`, the panel and the report each take their
    phases, ready list and counts from `plan` and hand `copies` and `own` to
    `rollup`, so no two of them can read the same phase from different copies
    or name it differently. `plan` is `manifest` with every read body laid over
    it (`with_live_bodies`), and the manifest handed in is left as it was.
    `copies` is each row's copy note (`row_copies`). `own` is this checkout's
    own plan when any body was laid over it, else None: only then is `plan` a
    different plan, and `rollup` counts the bugs from `own`, because a fix that
    exists only in another worktree has not landed here. `note` is what could
    not be asked - the reader's error and its note joined - or empty; a surface
    prints it, because a row that silently shows this checkout's copy reads as
    the live one.
    """
    flight = flight if isinstance(flight, dict) else {}
    reads = flight.get("reads") or {}
    laid = any(isinstance(r, dict) and isinstance(r.get("body"), dict)
               for r in reads.values())
    return {"plan": with_live_bodies(manifest, reads),
            "copies": row_copies(reads, flight.get("unread")),
            "own": manifest if laid else None,
            "note": "; ".join(w for w in (flight.get("error"), flight.get("note"))
                              if w)}


def _ready_sources(manifest, ready):
    """`set` of phase ids the ready list was decided from: the phase of each
    ready task, the phase each of its `dependsOn` and `blockedBy` refs names
    or owns, and the same for its phase's `blockedBy`.

    A ref is read the way `ready_tasks` reads it - a task id or a phase id -
    so a task made ready by a dependency finished in another copy names that
    copy's phase although no task of that phase is listed.
    """
    owner = _mio.phase_of_task(manifest)
    phases = {str(p.get("id")): p for p in (manifest.get("phases") or [])
              if isinstance(p, dict)}
    tasks = _mio.tasks_by_id(manifest)

    def phase_of_ref(ref):
        if ref in owner:
            return str(owner[ref])
        return str(ref) if str(ref) in phases else None

    out = set()
    for tid in ready or []:
        pid = owner.get(tid)
        if pid is None:
            continue
        task = tasks.get(tid) or {}
        refs = (list(task.get("dependsOn") or []) + list(task.get("blockedBy") or [])
                + list((phases.get(str(pid)) or {}).get("blockedBy") or []))
        out.add(str(pid))
        out.update(p for p in (phase_of_ref(r) for r in refs
                               if isinstance(r, str)) if p)
    return out


def ready_copy_notes(manifest, summary):
    """`[{"phase", "live", "basis", "line"}]` - the copy note of each phase the
    ready list was decided from, in plan order, for each such phase whose
    rollup entry names a copy.

    `manifest` is the plan `summary` was rolled up from - with any live copy
    laid over it - and `line` is `/audit:status`'s own wording for a copy
    under READY NOW, `phase <id> <basis>`, so every surface says it in the
    same words. Only the contributing phases are named: the phase of a ready
    task and any phase a ready task depends on (`_ready_sources`). A phase
    whose finished work left the list is said once, beside the counts, by
    `copy_headline`. Empty when nothing ready came from another copy.
    """
    if not isinstance(manifest, dict) or not isinstance(summary, dict):
        return []
    sources = _ready_sources(manifest, summary.get("ready"))
    out = []
    for entry in summary.get("phases") or []:
        copy = entry.get("copy") if isinstance(entry, dict) else None
        if str(entry.get("id")) not in sources or not isinstance(copy, dict):
            continue
        if not copy.get("basis"):
            continue
        out.append({"phase": entry.get("id"), "live": bool(copy.get("live")),
                    "basis": copy["basis"],
                    "line": "phase %s %s" % (entry.get("id"), copy["basis"])})
    return out


def copy_headline(summary):
    """The one sentence beside a surface's counts and Next when any phase was
    read from somewhere other than this checkout's own live copy, or None.

    Two sentences, because the two cases are different news: a phase READ
    from another copy puts that copy's work into the counts, while a phase
    that fell back to this checkout's copy leaves work out that may exist.
    Which one a row is comes from its copy's `read` (`row_copies`).
    """
    copies = [p["copy"] for p in (summary or {}).get("phases") or []
              if isinstance(p, dict) and isinstance(p.get("copy"), dict)]
    if not copies:
        return None
    if any(c.get("read") for c in copies):
        return ("These counts and Next include work read from another copy "
                "than this checkout's: a phase in flight elsewhere is shown "
                "as that copy holds it, and each such phase names its copy.")
    return ("These counts and Next take a phase in flight elsewhere from this "
            "checkout's copy, which may not be current; each such phase says "
            "why.")


def phase_task_status(manifest):
    """`{phase id: {task status: n}}` over `manifest`'s tasks.

    The per-phase half of `rollup`'s `tasks.byStatus`, taken over the same
    plan so a surface filtering phases by a status keeps exactly the phases
    whose tasks that status's count was made of. Cancelled tasks are counted
    here as they are in `byStatus`.
    """
    out = {}
    for p, t in _mio.iter_tasks(manifest if isinstance(manifest, dict) else {}):
        counts = out.setdefault(str(p.get("id")), {})
        st = str(t.get("status"))
        counts[st] = counts.get(st, 0) + 1
    return out


def ready_by_phase(manifest):
    """`{phase id: [ready task ids]}` - `ready_tasks` grouped by the owning phase.

    The ONE ready list, partitioned rather than re-derived, so a phase's own
    count can never disagree with the plan-wide list it is a share of. Order
    within a phase is the list's own order; a phase with nothing ready has no
    key, which a caller reads as zero.
    """
    owner = _mio.phase_of_task(manifest)
    out = {}
    for tid in ready_tasks(manifest):
        out.setdefault(owner.get(tid), []).append(tid)
    return out


def priority_note(manifest, ready=None):
    """The one sentence about a pin that could not be honoured, or None.

    Computed here rather than in each renderer so the CLI, the Markdown report,
    the HTML report and the panel all read ONE key. `rollup()` carries it as
    `priorityNote`; `audit-status.py` prints it under READY NOW.

    `ready` is accepted so `rollup()` does not compute the ready list twice —
    the note names the task running INSTEAD of the pinned phase, which is the
    first ready id.
    """
    if not isinstance(manifest, dict):
        return None
    order_list = ready if ready is not None else ready_tasks(manifest)
    pin = _priority.pinned_but_blocked(
        [p for p in (manifest.get("phases") or []) if isinstance(p, dict)],
        unmet_refs(manifest), finished=TERMINAL,
        status_of=_mio.effective_phase_status)
    return _priority.note(pin, order_list[0] if order_list else None)


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


# The word `proposed` as a status surface reads it. Spelled once here rather than
# at each site that asks, because it was asked twice with two different answers.
PARKED_PROPOSAL_STATUS = "proposed"


def is_parked_proposal(raw_status):
    """Whether a proposal's status AS WRITTEN means it is still parked.

    WHAT `parked` MEANS ON A STATUS SURFACE, decided here so the header and the
    PROPOSALS block cannot each decide it. They did: the header counted entries
    that were `proposed` AND carried a payload, the block counted every entry
    whose raw status was `proposed`, and a payload-less proposed entry made the
    two lines of one render disagree by one under the same word.

    The answer is the raw status alone, and it follows the decision the proposal
    ROWS already record: a status surface reads `statusRaw`, reports what is
    there, and never invents. Whether `/audit:propose materialize` can act on an
    entry is a different question with a different answer -- `hasPayload` on the
    row, which is what puts the copy-pasteable command on the line that has one.
    An entry with nothing drafted yet is still a decision waiting on a human, so
    folding the payload into the count left it out of the count of exactly that,
    while the block below went on listing it. Counted here and listed there, or
    neither -- counted in one place and not the other is the state that made one
    render print two numbers under one word.

    Takes the RAW value, not the entry, so both callers can pass what they hold:
    `rollup` walks `proposals[]` and has the dict, `_proposal_lines` has rows
    whose `statusRaw` is that same value carried through.
    """
    return raw_status == PARKED_PROPOSAL_STATUS


# A phase's `area` -> its tags. Re-exported rather than reimplemented: the panel
# and this file each carried their own copy, and one of them would eventually have
# learned something the other had not. `_areas` also owns what a tag MEANS now
# (meta.areas), so normalisation had to move next to the lookup it feeds.
areas_of = _areas.areas_of


# A bug's status, DERIVING 'fixed' from its linked task. Re-exported rather than
# reimplemented, the same move `areas_of` above makes: this rule had two homes that
# could drift — here (layer 7) and `_report_html._bug_view` (layer 2) — and layer 2
# cannot import layer 7, so the copy was structural. `_manifest_io` is the only
# place underneath both readers. Its docstring carries the rule and says why the
# falsy-taskId guard is load-bearing; `_panel_state` reaches this name through
# `_cores()`, so the name stays.
effective_bug_status = _mio.effective_bug_status


# ca: the two ways a phase or task can be FINISHED. `done` is the work
# landed; `cancelled` is the work will not be done — the feature was dropped, the
# approach abandoned — and it is terminal in exactly the same sense. Readiness
# treats a cancelled blocker as settled on purpose: a plan whose dropped work
# still gates everything behind it deadlocks, and a deadlock nobody can clear is
# a worse answer than a ready task worth a second look.
TERMINAL = _mio.TERMINAL


# --- test evidence ---------------------------------------------------------------
# `task.testEvidence` / `phase.testEvidence` is a POINTER at the run that last
# exercised that subject, together with the verdict the run reached. Three
# distinctions this whole section exists to keep, each of which some surface in this
# tree has already got wrong once:
#
#   * ABSENT IS NOT FAILURE. A manifest written before the field existed, a task
#     nobody has run, and a block somebody deleted are one single state -- "no run
#     was recorded" -- and rendering the worst reading of that silence is the
#     failure the schema and COMPATIBILITY.md both name by hand.
#   * `no-checks` IS NOT A PASS. It is exit 0 over a gate that found nothing to
#     check, which is precisely the shape a green build with no tests in it has.
#   * THE POINTER IS NOT RESOLVED HERE. Whether this checkout's evidence ledger
#     actually holds that `runId` is `verify-invariants.py`'s question and
#     `/audit:doctor`'s. Nothing here opens the ledger, so nothing here may word its
#     answer as though it had.
#
# WHICH WORDS CANNOT SIGN WORK OFF. `passed` is the only verdict that signs anything
# off, and `empty-gate` -- no gate was configured at all -- is a plan's choice
# rather than a result, so neither is below. Everything else the enum declares is:
# `failed` ran to completion and came back red; `no-checks` is the exit-0-that-is-
# not-a-verdict above; `timed-out` and `cancelled` were stopped rather than answered
# (the schema pairs those two in one sentence, and splitting them here would be this
# file inventing a distinction the record does not draw); `could-not-run` means no
# verdict was reached for a reason that is not the work's -- the runner never
# started, it started and never reached a check, or the OS ended it, which can
# come after checks ran -- and that is emphatically not the same claim as a
# failing test.
#
#   * `gate-mutated` IS EXIT 0 TOO, AND IT IS THE SAME MISTAKE ONE STEP FURTHER ON.
#     Every command came back green and the gate rewrote files the work
#     under test declares, so its exit code is a claim about bytes the gate itself
#     produced -- `run-test-gate.render` has refused the commit step on exactly that
#     for as long as the bracket has existed, and until the enum had a word for it
#     the ROW said `passed` and this condition read the row. So a gate whose own
#     verdict line said GATE MUTATED THE TREE signed the work off -- the exit code
#     was right and the record it wrote was wrong, which is the worse half,
#     because the record is what a reader consults a week later. The repair is the
#     gate's and not a retry: revert those files and use the read-only spelling of
#     the check.
#
# SPELLED AS A POSITIVE SET, NEVER AS "everything except passed". The enum MAY GAIN
# MEMBERS -- COMPATIBILITY.md declines to promise the list is closed -- and a
# complement would fold a word this build has never heard of into `failed`, which is
# the one reading the schema forbids by name. An unrecognised word is carried
# through as itself (`unrecognised` in the summary below, the raw word in the CLI's
# `tests` column) and is judged by nothing.
#
# AND THE SET IS SPLIT IN TWO, THE SAME SPLIT `noVerdict` MAKES BELOW.
# `failing-tests`
# counted a run the OS killed as a FAILING TEST, because the runner recorded
# `failed` for it and this set holds that word. The runner records
# `could-not-run` now -- so the word on the record is right -- and the condition
# still read one undifferentiated list called `failing`, which means the gate's
# own vocabulary went on folding an infrastructure failure into the same news as
# a red suite. Two facts, two lists:
#
#   `NO_VERDICT_EVIDENCE`   the run never ANSWERED. Stopped at a bound, stopped
#                           by the operator, or never got to a verdict at all --
#                           and NOTHING about the work under test may be read
#                           into any of them. The repair is never the task's.
#   the remainder           the run answered, and the answer cannot sign work
#                           off: `failed` came back red, `no-checks` counted
#                           nothing, `gate-mutated` graded bytes the gate wrote.
#
# THE CONDITION STILL TRIPS ON THE UNION, and that is deliberate rather than
# unfinished. `failing-tests`'s documented claim is "a recorded test run that
# CANNOT SIGN WORK OFF", which is true of every word here; narrowing it to the
# remainder would make a `could-not-run` pointer that fails somebody's pipeline
# today start passing it on upgrade -- a refusal silently becoming a pass, which
# is the worse direction and exactly the change COMPATIBILITY.md refuses to make
# quietly. So the split is ADDITIVE: the union decides the exit code, and
# `noVerdict` is what lets a surface say WHICH it has.
#
# THE UNION STAYS SPELLED OUT AND THE REMAINDER IS DERIVED, which is the one
# ordering available rather than a preference. `_areas.py` anchors a claim in
# `reference/orchestrator.md` to this module's SOURCE TEXT: it recovers the
# vocabulary by matching the assignment on the next line with a regex and
# reading what is inside the braces. Building that name from its two halves
# instead would leave the anchor matching nothing and take the orchestrator's
# own vocabulary check down with it - and this comment may not demonstrate the
# shape either, because that same regex would match the demonstration and
# recover an empty set, which agrees with any document. (It did, once, and this
# sentence is the repair: reword, never widen the pattern.)
#
# Deriving the REMAINDER keeps the anchor readable AND keeps the halves from
# drifting: a word can be in the whole set without being a no-verdict one, and
# it lands in `ANSWERED_NO_SIGN_OFF` by subtraction rather than by somebody
# remembering to add it. The other direction - a no-verdict word that is NOT in
# the whole set - is the one subtraction cannot catch, so a case checks that
# containment rather than trusting it.
NO_SIGN_OFF_EVIDENCE = frozenset({"failed", "gate-mutated", "no-checks",
                                  "timed-out", "cancelled", "could-not-run"})
NO_VERDICT_EVIDENCE = frozenset({"timed-out", "cancelled", "could-not-run"})
ANSWERED_NO_SIGN_OFF = frozenset(NO_SIGN_OFF_EVIDENCE - NO_VERDICT_EVIDENCE)
PASSED_EVIDENCE = "passed"
NO_GATE_EVIDENCE = "empty-gate"
KNOWN_EVIDENCE = frozenset(NO_SIGN_OFF_EVIDENCE
                           | {PASSED_EVIDENCE, NO_GATE_EVIDENCE})


def evidence_status(holder):
    """A task's or phase's `testEvidence.status`, or None when it records none.

    None is "no run was recorded" and is NEVER a failure -- it is the one state a
    pre-field manifest, an unrun task and a deleted block all share.

    A block that is not an object, or one carrying no usable `status`, comes back as
    that same silence rather than as a word. A half-written block caches no verdict,
    and picking one for it would be this function answering a question the manifest
    did not: the schema requires all three keys at once precisely because dropping
    the whole block is always safe, so there is never a reason to have written half.
    """
    if not isinstance(holder, dict):
        return None
    block = holder.get("testEvidence")
    if not isinstance(block, dict):
        return None
    status = block.get("status")
    return status if isinstance(status, str) and status else None


def intent_unanswered(phase):
    """The ids of `phase`'s DONE tasks whose `intentCheck` carries no answer.

    ABSENCE IS THE SUBJECT, and it is not a verdict: the schema reads a missing
    block as "no answer recorded", never as agreement, and until something read
    it that absence was invisible on every surface a phase is judged from. A
    deliberate `not-asked` IS an answer - it carries its basis - so it is not
    listed; a cancelled task never reached the question. `deferred` is NOT an
    answer: it is the word a close writes for a task whose answers the phase
    review still owes, so such a task is listed until that review answers it.
    One home for the predicate because sign-off and `/audit:status` both print
    it, and two readings of "no answer" would be two answers about the same task.
    """
    if not isinstance(phase, dict):
        return []
    return [str(t.get("id")) for t in (phase.get("tasks") or [])
            if isinstance(t, dict) and t.get("status") == "done"
            and _intent_word(t) in (None, _fr.INTENT_DEFERRED)]


def findings_left_open(phase):
    """One line per review finding of `phase` that sign-off left open on purpose:
    `<id> accepted-open: <the human's reason>` or `<id> carried to <id>`.

    A FINDING SETTLED BY A DISPOSITION IS NOT A FIXED ONE. Sign-off records
    `accepted-open` with the reason, or `carried` with the bug or task now
    holding it; a surface that listed only unsettled findings would drop both
    the moment they were recorded, which is the vanishing this record exists to
    stop. A disposition with its reason or destination missing is said as that
    rather than filled in."""
    review = phase.get("review") if isinstance(phase, dict) else None
    if not isinstance(review, dict):
        return []
    lines = []
    for f in (review.get("findings") or []):
        if not isinstance(f, dict):
            continue
        if f.get("status") == "accepted-open":
            lines.append("%s accepted-open: %s" % (
                f.get("id"), f.get("acceptedReason") or "no reason recorded"))
        elif f.get("status") == "carried":
            lines.append("%s carried to %s" % (
                f.get("id"), f.get("carriedTo") or "no destination recorded"))
    return lines


def _intent_word(task):
    """The answer `task`'s `intentCheck` records, or None for none."""
    block = task.get("intentCheck")
    return (block.get("answer") or None) if isinstance(block, dict) else None


# --- the evidence boundary --------------------------------------------------------
# WHAT THE CONDITION COULD NOT ASK. `no-test-evidence` asks whether finished work
# is backed by a recorded run, and never whether it COULD have been. For a plan
# adopted mid-flight the answer is no for every subject finished before the
# recorder existed, and no setting helps -- `--phase` scopes the human render and
# says so in its own help, not the gate. That work is not a lapse, it is an
# impossibility, and what separates the two is a moment:
#
#     boundary = min( meta.evidenceSince.at , the earliest ts in the ledger )
#
# THE BOUNDARY IS PASSED IN, NEVER READ HERE, and that is a layer fact rather
# than a preference: `_evidence_io` computes it and sits on THIS module's layer,
# where a layer-mate may not be imported. `rollup` therefore takes it the way it
# already takes `usage` -- computed by a caller above layer 2 (`audit-status.py`
# and `render-report.py` at 7, `_panel_state` at 5) and handed down, so this file
# stays a pure dict -> dict transform and there is exactly one implementation of
# where the boundary comes from.
#
# THREE-VALUED, AND EVERY READER SPELLS IT `is None`.
#
#   boundary is None            nobody asked. Nothing may be excused, because
#                               nothing was established -- this is the shape
#                               every caller that predates the feature still
#                               passes, and its verdict is unchanged.
#   boundary["at"] is None      asked, and neither source said anything. Nothing
#                               in this plan could have carried evidence, so
#                               every gap is excused and the block's `basis` is
#                               the sentence that says why.
#   boundary["at"] is a stamp   the moment to compare against.
#
# A truthiness test flattens the first two into each other AND reads a boundary
# at the epoch as no boundary at all. The distinction is the whole feature.
GAP_BEFORE = "beforeBoundary"
GAP_SINCE = "sinceBoundary"
GAP_UNDATED = "undated"
# The three classes a gap can fall in, and the three keys the summary buckets
# them under -- ONE vocabulary, so the word `evidence_gap` answers a surface with
# is the same word `evidence_subjects` is asked for. Two spellings of this list
# would be two chances for a class to exist in one and not the other.
GAP_CLASSES = (GAP_BEFORE, GAP_SINCE, GAP_UNDATED)

# Which field DATES a subject, per scope. A phase is dated by the merge that
# landed it and a task by its own completion; neither field stands in for the
# other, and reading `completedAt` off a phase would date it by a key the schema
# does not give it.
FINISHED_KEY = {"phase": "mergedAt", "task": "completedAt"}


def finished_at(holder, scope):
    """The stamp that dates a subject's completion, or None when it carries none.

    Blank and non-string answer None: the schema declares both stamps nullable and
    the population this feature targets is the hand-maintained plan, so a key
    present and empty is the same silence as a key absent. WHICH silence it is
    does not matter here, because both lead to the same class and the same repair.
    """
    key = FINISHED_KEY.get(scope)
    value = holder.get(key) if (key and isinstance(holder, dict)) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _gap_of(row, boundary):
    """Which class a done subject carrying NO pointer falls in.

    Total over `GAP_CLASSES` -- every gap gets exactly one word, so the buckets a
    caller builds from it are a partition by construction rather than by
    assertion.

    THE STAMPS ARE PARSED, NOT COMPARED AS TEXT. `completedAt` and `mergedAt` are
    PLAN fields a human writes, so `2026-06-02T17:37:00+02:00` sorts after a
    `...15:38:00Z` boundary as text and falls a minute before it as a time -- and
    getting that backwards excuses the wrong subjects. `_usage_core.parse_ts` is
    enough for `at` because `_evidence_io.boundary_of` hands a placed boundary on
    in the one Z spelling, whatever the plan or the ledger wrote - a date-only
    `evidenceSince` included, which `parse_ts` alone would not read. That module
    is a layer-mate, so its own moment read cannot be called from here.

    A STAMP NOTHING CAN READ DATES NOTHING. Neither an unreadable `at` nor an
    unreadable subject stamp is ever resolved in favour of the excuse: an excuse
    granted on a comparison that did not happen is the silent widening this whole
    mechanism exists to prevent, and the other direction merely fails work loudly,
    where somebody sees it.
    """
    if not isinstance(boundary, dict):
        # Nobody asked. The subject's stamp cannot change the answer, so it is
        # not consulted and the reader is not sent to set a stamp that would
        # excuse nothing -- the repair here is to compute a boundary.
        return GAP_SINCE
    at = boundary.get("at")
    if at is None:
        return GAP_BEFORE
    started = _usage_core.parse_ts(at)
    if started is None:
        return GAP_SINCE
    finished = _usage_core.parse_ts(row.get("finishedAt"))
    if finished is None:
        return GAP_UNDATED
    # AT the boundary is INSIDE recording, not before it: the boundary is the
    # earliest moment we have evidence that recording existed, so a subject
    # finished at that instant could have been recorded.
    return GAP_BEFORE if finished < started else GAP_SINCE


def evidence_gap(holder, scope, boundary):
    """Which evidence gap one phase or task has, or None when it has none.

    THE DOOR THE REPORT AND THE PANEL CALL, so that "is this absence excused" is
    answered by the rule the gate bucketed by rather than by a second opinion
    rendered beside it. `scope` is `"phase"` or `"task"`; `boundary` is
    `_evidence_io.boundary_of`'s block, or None when nobody computed one.

    None means there is nothing to explain -- the subject carries a pointer, or
    the plan does not call it done. Otherwise one of `GAP_CLASSES`.

    AN UNKNOWN SCOPE IS REFUSED BY NAME rather than answered, for
    `evidence_subjects`' reason one argument over: an unrecognised scope reads no
    stamp, so a quiet fall-through would date nothing and call every subject
    undated -- a mistyped word silently changing a verdict.
    """
    if scope not in FINISHED_KEY:
        raise ValueError("%r is not a subject scope; the scopes are %s"
                         % (scope, ", ".join(sorted(FINISHED_KEY))))
    row = evidence_row(holder, scope)
    if row["status"] is not None or row["subjectStatus"] != "done":
        return None
    return _gap_of(row, boundary)


def evidence_row(holder, scope):
    """The `evidence_rows` row for ONE phase or task.

    EXTRACTED SO THE ROW HAS ONE SHAPE. The walk below built it twice, once per
    scope, and `evidence_gap` needs the same row for a single subject a surface
    is rendering — three spellings of one dict is how a key gets added to two of
    them.

    A non-dict holder answers a row of silences rather than raising: `evidence_gap`
    is called from surfaces that must render a broken plan, and the row it gets
    back says "nothing recorded, not done", which is the reading that excuses
    nothing and claims nothing.
    """
    holder = holder if isinstance(holder, dict) else {}
    return {"scope": scope, "id": holder.get("id"),
            "status": evidence_status(holder),
            "subjectStatus": holder.get("status"),
            # The stamp that DATES the subject, carried on the row rather than
            # looked up again later: the boundary comparison and the walk that
            # finds the gaps are the same pass, and a second read of the plan is
            # a second chance to read a different field.
            "finishedAt": finished_at(holder, scope),
            # WHOSE RUN THE POINTER IS, when it is not the subject's own: a member
            # of a group sign-off carries the carrier's pointer, and a surface
            # rendering it as the member's run would claim a gate nobody ran.
            "gradedBy": graded_by(holder)}


def graded_by(holder):
    """The phase whose gate run a pointer is, when a group sign-off copied it onto
    another member - or None for a pointer that is the subject's own."""
    block = holder.get("testEvidence") if isinstance(holder, dict) else None
    value = block.get("gradedBy") if isinstance(block, dict) else None
    return str(value) if isinstance(value, str) and value else None


def evidence_rows(manifest):
    """One row per phase and per task the plan carries, in document order.

    `{"scope", "id", "status", "subjectStatus", "finishedAt"}`. `status` is the
    recorded verdict, None where none is recorded; `subjectStatus` is the subject's
    OWN workflow status, which is what lets a caller ask about `done` tasks
    specifically without walking the plan a second time.

    EVERY subject is a row, including every one carrying nothing. A walk that
    yielded only the subjects holding a pointer could not answer "which done task
    has none", and that question is half of what this block is for.

    Ids are carried as written, `None` included: a subject with no id is the
    validator's finding to report, and dropping it here would quietly shrink a gate
    the reader believes covers the plan.
    """
    if not isinstance(manifest, dict):
        return []
    rows = []
    for ph in (manifest.get("phases") or []):
        if not isinstance(ph, dict):
            continue
        rows.append(evidence_row(ph, "phase"))
        for t in (ph.get("tasks") or []):
            if not isinstance(t, dict):
                continue
            rows.append(evidence_row(t, "task"))
    return rows


def test_evidence_summary(manifest, boundary=None):
    """What the plan's `testEvidence` pointers SAY -- the block `rollup` carries.

    ALWAYS PRESENT AND ALWAYS COMPLETE, every list included even when empty, for the
    reason `priorityNote` is always a key: a block that appeared only when it had
    something to report could not be told from a block nobody computed.

    `failing` and `missingOnDone` are the two the gate reads, and they are
    deliberately different questions rather than two ways to trip one condition.
    `failing` is a RECORDED VERDICT that cannot sign work off. `missingOnDone` is a
    SUBJECT the plan calls `done` with no pointer at all -- an ABSENCE, which is not
    a verdict and must never be counted as one; that is why it is its own opt-in
    condition, and why a repository that has never recorded a run trips neither.

    BOTH READ BOTH SCOPES, and `missingOnDone` did not. A phase carries its own
    pointer -- `run-test-gate.py --record` writes `phase.testEvidence` at sign-off
    and no task pointer stands in for it -- and every other reader in this tree
    walks phases and tasks alike: `failing` above, `_doctor_completions`'
    pointer check, `_invariants`' `evidence-committed`. A `missingOnDone` filtered
    to `scope == "task"` left the one subject whose sign-off this condition exists
    to ask about answering nothing at all, while its sibling condition read that
    same subject happily -- one vocabulary, two scopes, and nothing saying so.

    `unrecognised` is the default arm the schema asks for, made visible instead of
    silent. A status word this build does not know trips nothing here -- folding it
    into `failed` is the reading the schema forbids -- and a consumer that wants to
    act on one now can, without this file having guessed what it means.

    `missingOnDone` IS SPLIT THREE WAYS, and the split is a partition of it rather
    than a second walk: every gap lands in exactly one of `GAP_CLASSES`, so a count
    taken over the classes and a count taken over the gaps can never disagree.
    `missingOnDone` stays whole beside them because "which done subject records
    nothing" is true whatever the boundary says, and a surface that only wants that
    should not have to add three lists back together to get it.

    `boundary` DEFAULTS TO None AND THAT IS A THIRD STATE, not a convenience. A
    caller that never computed one excuses nothing -- which is exactly the verdict
    every caller reached before this parameter existed -- while a boundary that WAS
    computed and answers `at: None` excuses everything, because nothing in that
    plan could have carried evidence. Collapsing the two would make an upgrade
    silently pass builds nobody asked it to pass.

    NOTHING IS RESOLVED AGAINST THE LEDGER. Every row is what the manifest says
    about itself; whether a `runId` names a run this checkout holds is asked by
    `verify-invariants.py` and `_doctor_completions`, and answered nowhere near here.
    """
    rows = evidence_rows(manifest)
    recorded = [r for r in rows if r["status"] is not None]
    missing = [r for r in rows
               if r["status"] is None and r["subjectStatus"] == "done"]
    gaps = dict((name, []) for name in GAP_CLASSES)
    for row in missing:
        gaps[_gap_of(row, boundary)].append(row)
    out = {
        "recorded": len(recorded),
        "byStatus": _by_status_values([r["status"] for r in recorded]),
        "failing": [r for r in recorded
                    if r["status"] in NO_SIGN_OFF_EVIDENCE],
        # THE HALF OF `failing` THAT REACHED NO VERDICT AT ALL. It is a
        # SUBSET and not a fourth bucket: `failing` stays whole beside it for
        # `missingOnDone`'s reason - "which recorded run cannot sign work off"
        # is one question a surface may want on its own, and it should not have
        # to add lists back together to get it. What this key buys is the
        # sentence the gate could not write: a killed runner and a red suite are
        # different news with different repairs, and until the runner recorded
        # `could-not-run` at all the first was spelled as the second.
        "noVerdict": [r for r in recorded
                      if r["status"] in NO_VERDICT_EVIDENCE],
        "unrecognised": [r for r in recorded
                         if r["status"] not in KNOWN_EVIDENCE],
        "missingOnDone": missing,
    }
    out.update(gaps)
    return out


# Which of the block's keys name a subject list, DERIVED from the block itself
# over an empty plan rather than typed a second time. A subject list added to
# `test_evidence_summary` later is legal here without an edit, and `recorded` (an
# int) and `byStatus` (a dict) can never be written into this set by hand.
EVIDENCE_SUBJECT_KEYS = tuple(sorted(
    k for k, v in test_evidence_summary(None).items() if isinstance(v, list)))


def evidence_subjects(summary, key):
    """One of the test-evidence block's subject lists, off a rollup summary.

    `[]` when the block is absent, and here that really does mean "nothing to
    report" -- which is the OPPOSITE of `invariant_breaches` below, for the
    opposite reason. That block is INJECTED by a command that may or may not have
    run the checks, so its absence is "nobody looked". This one is computed by
    `rollup` unconditionally out of the manifest it was handed, so a summary
    without it is a caller that never built one rather than a read that failed:
    there is no unasked question for an empty list to be hiding.

    A KEY THAT NAMES NO SUBJECT LIST RAISES, which is the half `block.get(key) or
    []` got wrong. `recorded` is an int and `byStatus` a dict, so asking for either
    handed the caller the int or the dict back out of a function that promises a
    list -- and only when it was TRUTHY, so an empty plan answered correctly and a
    populated one did not, which is the shape nobody catches by trying it once.

    REFUSED RATHER THAN ANSWERED `[]`, because every caller is a gate condition and
    `[]` is the arm that reads "nothing to report": a mistyped key answered that
    way passes a build silently, which is worse news than the leak it replaces. A
    wrong key is a programming error, so it fails at the call with the legal set in
    the message. A legal key whose VALUE is not a list is still `[]` -- that is a
    hand-built summary, which is data rather than a caller, and the reasoning for
    an absent block applies to it unchanged.
    """
    if key not in EVIDENCE_SUBJECT_KEYS:
        raise ValueError(
            "%r names no test-evidence subject list; the subject lists are %s"
            % (key, ", ".join(EVIDENCE_SUBJECT_KEYS)))
    block = (summary or {}).get("testEvidence")
    if not isinstance(block, dict):
        return []
    value = block.get(key)
    return value if isinstance(value, list) else []


def unevidenced(summary):
    """What `no-test-evidence` FAILS on, split by the repair each part needs.

    `{GAP_SINCE: [...], GAP_UNDATED: [...], "unsound": [...]}`, and the condition
    trips when any of the three is non-empty. ONE FUNCTION, because the gate's
    verdict and the sentence a human reads under a red build have to be the same
    answer -- a renderer that re-derived "which subjects failed" is a second
    opinion that can disagree with the exit code.

    THE TWO SUBJECT LISTS ARE ONE CONDITION AND TWO SENTENCES. `sinceBoundary` is
    "the recorder existed and this was not recorded" and the repair is to run the
    gate; `undated` is "we cannot tell when this finished" and the repair is to set
    the stamp. Folding them together sends half the readers to the wrong one.

    `unsound` IS THE EXCUSE ITSELF FAILING, and it exists because the dangerous
    direction here is silence. A source that could not be ASKED may have held an
    EARLIER moment, so a boundary computed without it may be LATER than the truth
    and the excuse WIDER than it should be -- and a widened excuse turns a build
    GREEN, where nobody reads the log. So when work was actually excused and a
    source was actually unaskable, the verdict the excuse rests on is refused and
    the unreachable source is named. When nothing was excused, nothing rested on
    it and it changes no verdict: an `unknown` alone must not red a build.

    ...and a summary that names gaps and classifies NONE of them is refused for
    `invariant_breaches`' reason. `rollup` always classifies, so empty class lists
    beside a non-empty `missingOnDone` mean a caller that never computed one --
    and that shape reads exactly like a clean plan, which is the silent pass.
    """
    excused = evidence_subjects(summary, GAP_BEFORE)
    out = {GAP_SINCE: evidence_subjects(summary, GAP_SINCE),
           GAP_UNDATED: evidence_subjects(summary, GAP_UNDATED),
           "unsound": []}
    gaps = evidence_subjects(summary, "missingOnDone")
    if gaps and not excused and not out[GAP_SINCE] and not out[GAP_UNDATED]:
        out["unsound"].append(
            "%d done subject(s) record no run and none of them was classified "
            "against an evidence boundary, so nothing here has been excused and "
            "this is not a pass" % (len(gaps),))
    unknown = ((summary or {}).get("evidenceBoundary") or {}).get("unknown")
    if excused and isinstance(unknown, list) and unknown:
        out["unsound"].extend(unknown)
    return out


def bugs_fixed_elsewhere(own, live, copies):
    """`[{"id", "taskId", "status", "copy"}]` - each bug `own` still holds open
    whose fix task `live` shows finished, with the copy that shows it.

    `own` is this checkout's plan and `live` the same plan with every phase in
    flight elsewhere laid over it (`with_live_bodies`). A bug's status is this
    checkout's, because a fix that exists only in another worktree has not
    landed here; the fix shown elsewhere is still news, so it is named beside
    the bug rather than counted. `copy` is the basis `copies` holds for the
    phase that owns the fix task in `live`, or None when no copy is named for
    it.
    """
    own_tasks = _mio.tasks_by_id(own)
    live_tasks = _mio.tasks_by_id(live)
    phase_of_task = {t.get("id"): p.get("id") for p, t in _mio.iter_tasks(live)
                     if isinstance(t, dict)}
    out = []
    for b in (own.get("bugs") or []) if isinstance(own, dict) else []:
        if not isinstance(b, dict):
            continue
        if effective_bug_status(b, own_tasks) in CLOSED_BUG:
            continue
        there = effective_bug_status(b, live_tasks)
        if there not in CLOSED_BUG:
            continue
        copy = (copies or {}).get(str(phase_of_task.get(b.get("taskId"))))
        out.append({"id": b.get("id"), "taskId": b.get("taskId"),
                    "status": there,
                    "copy": copy.get("basis") if isinstance(copy, dict)
                    else None})
    return out


def rollup(manifest, findings, warnings, usage=None, boundary=None,
           copies=None, own=None):
    """The machine-readable summary --json, render-report and the panel consume.

    `usage` is the optional block from `usage_summary()`; it is passed in rather
    than read here so this stays a pure dict -> dict transform.

    `copies` is `{phase id: {"live", "basis"}}` for each phase whose row was
    read from somewhere other than this checkout's own live copy, and each
    named row carries it verbatim under `copy`. It arrives for `usage`'s
    reason: which copy holds a phase is a git question. A phase not named
    gets no key, so a plan with nothing in flight elsewhere rolls up exactly
    as it always did.

    With `copies`, the rollup also carries `readyCopies`
    (`ready_copy_notes`) and `copyHeadline` (`copy_headline`), the two things
    a surface says about copies where a reader acts.

    `own` is this checkout's own plan, handed over when `manifest` has live
    copies laid over it. The bug block is then counted from `own` - a bug is
    open until its fix lands here - and carries `elsewhere`, each open bug
    whose fix a live copy shows (`bugs_fixed_elsewhere`). Without `own` the
    bugs are counted from `manifest` and no `elsewhere` key is written.

    `boundary` is `_evidence_io`'s block and arrives the same way for the same
    reason, with one extra: that module is this one's LAYER-MATE, so reading it
    here is not merely impure, it is an import the layer lint refuses. It is
    carried into the payload VERBATIM -- the surfaces render its `basis` and the
    gate reads its `unknown`, and neither is served by a block summarised on the
    way past."""
    if not isinstance(manifest, dict):
        manifest = {}  # non-object root -> empty rollup, never an AttributeError
    phases = [p for p in (manifest.get("phases") or []) if isinstance(p, dict)]
    tasks = [t for _p, t in _mio.iter_tasks(manifest)]
    here = own if isinstance(own, dict) else manifest
    bugs = [b for b in (here.get("bugs") or []) if isinstance(b, dict)]
    task_by_id = _mio.tasks_by_id(here)
    bug_eff = [effective_bug_status(b, task_by_id) for b in bugs]
    open_bugs = [b for b, s in zip(bugs, bug_eff) if s not in CLOSED_BUG]
    # Where each phase sits in EXECUTION order, computed over `phases` — the same
    # filtered list every row below is built from, so `porder[i]` belongs to
    # `phase_entries[i]`. Over ALL of them and never over a view: a rank taken
    # across a subset is a different number, and the panel filters its rows in the
    # browser (search, status, which segment) long after this is stamped.
    #
    # UNCONDITIONAL, which is the whole point. `_report_html.phase_ranks` emits
    # nothing when no phase is pinned because it hides its sort control in the same
    # breath; the panel offers the control always, so a rank withheld here is a
    # client left to invent a fallback comparator — the very thing this key exists
    # to remove. With nothing pinned `ranks()` is the identity, so the option
    # degrades to plan order rather than to a second opinion about it.
    porder = _priority.ranks(phases)
    phase_entries = [{
        "id": p.get("id"), "title": p.get("title"),
        # The DERIVED status (`_manifest_io.effective_phase_status`): every surface
        # renders this key, so a phase signed off on its parent branch reads done
        # everywhere, and none can show a phase done that is not.
        "status": _mio.effective_phase_status(p), "area": areas_of(p.get("area")),
        # Every task terminal, no sign-off recorded: finished work nobody has
        # reviewed yet. Flagged rather than folded into `status`, so a surface can
        # say it instead of presenting the phase as either running or done.
        "signoffDue": _mio.signoff_due(p),
        # The plan gate's own rule, so a surface naming "the running phase" names
        # the one the gate is held by - not the first of every phase whose stored
        # status still reads in_progress while it only awaits sign-off.
        "running": _mio.phase_running(p),
        "desiredOutcome": p.get("desiredOutcome"),
        # Passed through verbatim, never derived: `evaluate_gate`'s
        # "in-progress" condition reads it to tell a phase that merged from
        # one that is genuinely running, and only the plan field itself can
        # say which — `status` alone cannot, since `close-phase.py` stamps
        # this without ever touching `status`.
        "mergedAt": p.get("mergedAt"),
        # Passed through verbatim for `stale_full_runs`: present only when the
        # phase's `mergedHead` was recorded after the fact, and then the moment a
        # full run has to postdate to have had that head to contain.
        "mergedHeadAt": p.get("mergedHeadAt"),
        # The tier as `_priority` reads it, not the raw field: `priority: "1"`
        # orders nothing, so a badge rendered off the raw value would advertise
        # a pin the run does not honour. `None` means unprioritised.
        "priority": _priority.tier_of(p),
        # The tier is what a READER understands; this is the ordering index, and
        # the two are not interchangeable. `priority` renders as a badge and is
        # never sorted on; `porder` sorts and is never rendered. Named after the
        # report's `data-porder` on purpose, so one grep finds every reader of the
        # one rank across both surfaces.
        "porder": porder[i],
        "done": sum(1 for t in (p.get("tasks") or [])
                    if isinstance(t, dict) and t.get("status") == "done"),
        # ca: counted separately, never folded into `done`. A bar that showed
        # 5/5 for three landed tasks and two dropped ones would be a lie in the
        # one direction that matters.
        "cancelled": sum(1 for t in (p.get("tasks") or [])
                         if isinstance(t, dict) and t.get("status") == "cancelled"),
        # THE DENOMINATOR EXCLUDES CANCELLED, and that is the repair rather
        # than an oversight. Cancelled is TERMINAL — closed on purpose, with a
        # reason and a journal row — so it belongs on the settled side of this
        # fraction, not on the side a reader reads as "still to do". Counting
        # it here made `done/total` read as a gap that was actually smaller
        # (or gone) the moment every unfinished task turned out to be a
        # cancelled one rather than an open one. `done` is always <= this
        # total by construction (a done task is never cancelled), so the
        # fraction only ever UNDER-reports how much is settled, never over.
        "total": sum(1 for t in (p.get("tasks") or [])
                     if isinstance(t, dict) and t.get("status") != "cancelled"),
    } for i, p in enumerate(phases)]
    for entry in phase_entries:
        if str(entry.get("id")) in (copies or {}):
            entry["copy"] = dict(copies[str(entry["id"])])
    # group phases by each of their `area` tags (a phase with several tags counts
    # under each; untagged phases are simply not grouped)
    areas = {}
    for e in phase_entries:
        for a in e["area"]:
            g = areas.setdefault(a, {"phases": 0, "done": 0, "total": 0,
                                     "cancelled": 0})
            g["phases"] += 1
            g["done"] += e["done"]
            g["total"] += e["total"]
            # The per-phase count above and the plan-wide one below both carry
            # this SAME repair — cancelled excluded from the denominator — so
            # the per-area rollup inherits it for free by summing the already-
            # repaired per-phase figures, rather than needing a fourth count
            # that could say something different from the other three.
            g["cancelled"] += e["cancelled"]
    # The advisory owner (v0.34 D3), only for areas that DECLARE the key - no
    # key means no claim, and an explicit null is carried as null ("nobody"),
    # the same distinction _areas.owner_of draws.
    reg = _areas.registry(manifest)
    for tag, g in areas.items():
        entry = reg.get(tag) or {}
        if "owner" in entry:
            o = entry.get("owner")
            g["owner"] = o.strip() if isinstance(o, str) and o.strip() else None
    # Whether meta.areas registers anything at all (v0.37 B3): the fact that
    # decides if an UNTAGGED phase is a blind spot (defaults exist and skip it)
    # or just a phase in a free-text-tagging project (nothing to miss).
    areas_registered = bool(reg)
    props = [x for x in (manifest.get("proposals") or []) if isinstance(x, dict)]
    # Read once, so `total` below and `byStatus` agree about what "cancelled"
    # counted from THIS SAME PASS over `tasks` means — a second walk of the
    # list here is a second place the two could disagree.
    tasks_by_status = _by_status(tasks)
    out = {
        "valid": not findings,
        "findings": len(findings),
        "warnings": len(warnings),
        "phases": phase_entries,
        "areas": areas,
        "areasRegistered": areas_registered,
        # PLAN-WIDE, and the same repair as each phase entry above: the
        # denominator excludes cancelled work, because a fraction a reader
        # resolves before the parenthetical after it must not put settled
        # work where open work goes.
        "tasks": {"total": len(tasks) - tasks_by_status.get("cancelled", 0),
                  "byStatus": tasks_by_status},
        "bugs": {"total": len(bugs), "byStatus": _by_status_values(bug_eff),
                 "open": len(open_bugs),
                 "openHighSeverity": sum(
                     1 for b in open_bugs
                     if _is_high_severity(b.get("severity")))},
        # What the plan's `testEvidence` pointers SAY, never what the ledger holds.
        # Unconditional and whole, the same call `priorityNote` makes below: an
        # empty `failing` list and a block nobody computed must not look alike, and
        # the CLI, the report and the panel all read the one key rather than each
        # walking the plan for it.
        "testEvidence": test_evidence_summary(manifest, boundary),
        # "parked" is every entry whose status AS WRITTEN is 'proposed', payload
        # or not — `is_parked_proposal` holds the decision and says why. It used
        # to require a payload as well, which is a count of what
        # /audit:propose materialize can act on rather than of what is waiting on
        # a human, and it disagreed with the PROPOSALS block that prints beneath
        # it. Legacy free-form entries (a status outside the vocabulary) show up
        # in total/byStatus and are not parked.
        "proposals": {"total": len(props), "byStatus": _by_status(props),
                      "parked": sum(1 for x in props
                                    if is_parked_proposal(x.get("status")))},
        "ready": ready_tasks(manifest),
    }
    # The sister key to "ready", and the reason the priority feature needed no
    # change in four renderers: a pin the dependencies would not let through is
    # SAID once, here, and the CLI, both reports and the panel each print this
    # one string. `None` when there is nothing to say — a key that is always
    # present is a key no consumer has to probe for.
    out["priorityNote"] = priority_note(manifest, out["ready"])
    # Only present when a ledger exists, so consumers can treat "no key" as
    # "metering not in use" without a second probe.
    if usage:
        out["usage"] = usage
    # The same seam, spelled `is not None` rather than by truthiness: a boundary
    # block is always a populated dict, so the two spellings agree today -- and
    # the one that keeps agreeing is the one that cannot read a future empty
    # block as "nobody asked". No key means nobody computed one, which is the
    # state `unevidenced` refuses to excuse anything in.
    if boundary is not None:
        out["evidenceBoundary"] = boundary
    if isinstance(own, dict):
        out["bugs"]["elsewhere"] = bugs_fixed_elsewhere(own, manifest, copies)
    # What a surface says beside the numbers a reader acts on, decided here
    # once so the report, its Markdown twin and the panel cannot name
    # different phases: `readyCopies` under Ready now, `copyHeadline` beside
    # the counts and Next. Only with copies named - with none, no row carries
    # a copy and both would be empty.
    if copies:
        out["readyCopies"] = ready_copy_notes(manifest, out)
        out["copyHeadline"] = copy_headline(out)
    return out


def unmet_refs(manifest):
    """Task/phase id -> the refs it waits on that are not `done` yet.

    Same 'satisfied' notion as `ready_tasks`, exposed per task so the renderer can
    say WHY something is not ready instead of only that it is not."""
    if not isinstance(manifest, dict):
        return {}
    status = _status_index(manifest)

    def unmet(refs):
        return _mio.unsatisfied(refs, status)

    # `_mio.iter_tasks` is deliberately NOT used here, for `_status_index`'s second
    # reason: this dict is keyed by phase ids AND task ids together, and the phase
    # rows have to be written in document order relative to the task rows or a
    # `duplicate id` manifest resolves to a different answer than it used to.
    out = {}
    for ph in (manifest.get("phases") or []):
        if not isinstance(ph, dict):
            continue
        pending = unmet(ph.get("blockedBy"))
        if ph.get("id") and pending:
            out[ph["id"]] = pending
        for t in (ph.get("tasks") or []):
            if not isinstance(t, dict) or not t.get("id"):
                continue
            waits = unmet(list(t.get("blockedBy") or [])
                          + list(t.get("dependsOn") or []))
            # A task inherits its phase's gate: it cannot start while the phase
            # is blocked, and saying so is more useful than an empty column.
            waits += ["%s (phase)" % r for r in pending]
            if waits:
                out[t["id"]] = waits
    return out


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
                or any(p.get("status") == "in_progress" and not p.get("mergedAt")
                       for p in summary["phases"])):
            failed.append(c)
        elif c in ("over-budget", "budget-80") and budget_breaches(
                summary, BUDGET_WARN_PCT if c == "budget-80" else 100.0):
            failed.append(c)
        elif c == "invariant-breach" and invariant_breaches(summary) is not None:
            failed.append(c)
        # A RECORDED verdict that cannot sign work off. Absence is not one of them
        # and cannot reach this arm: `test_evidence_summary` only ever puts a row
        # in `failing` when a status was actually written down.
        elif c == "failing-tests" and evidence_subjects(summary, "failing"):
            failed.append(c)
        # ...and the other question entirely: a SUBJECT the plan calls done with
        # no pointer at all, a phase as readily as a task - the same two scopes the
        # arm above reads, because a phase's sign-off records its own run. Opt-in,
        # and never folded into the one above - "the run was red" and "there is no
        # run" are different news with different repairs.
        #
        # NOT `missingOnDone` ANY MORE, and the difference is the whole boundary
        # feature: a gap that could not have been recorded is not a lapse. What
        # remains after the excuse is `unevidenced`, which is also what the gate
        # LINE is rendered from - one answer, so the sentence and the exit code
        # cannot disagree.
        elif c == "no-test-evidence" and any(unevidenced(summary).values()):
            failed.append(c)
        # `is not None` for `invariant-breach`'s reason: it is the only spelling
        # under which a block nobody computed fails instead of passing.
        elif c == "stranded-skills" and stranded_skills(summary) is not None:
            failed.append(c)
        # ...and `is not None` again, for the same reason one more time. What is
        # different here is which SILENCE the condition owes: a plan with ready
        # work and NO lock is every planned phase there has ever been, so this
        # arm has to stay quiet there while still tripping on a block nobody
        # computed. `unfinished_runs` keeps those two apart; a truthiness test
        # over its result would not.
        elif c == "unfinished-run" and unfinished_runs(summary) is not None:
            failed.append(c)
        # `is not None` again, for `invariant_breach`'s reason: the only spelling
        # under which a summary nobody asked `full_run_block` for fails rather
        # than reading as a plan with nothing provisional in it.
        elif c == "provisional" and provisional_phases(summary) is not None:
            failed.append(c)
        elif c == "stale-full-run" and stale_full_runs(summary) is not None:
            failed.append(c)
        elif c == "unknown-full-run" and unknown_full_runs(summary) is not None:
            failed.append(c)
    return failed


def provisional_phases(summary):
    """Merged phases the third place has not yet certified WHOLE, or None when
    `summary['fullRun']` was never computed. Never [].

    THE SAME THREE STATES `invariant_breaches` AND `stranded_skills` HAVE, for
    the same reason: `fullRun` is INJECTED by `audit-status.py` (this module is
    a layer-mate of `_evidence_io` and may not read the ledger or ask git), so
    an ABSENT block means nobody asked - and a gate reading that as clean would
    pass every repository where the injection silently failed. A phase whose
    plan declares no `meta.fullGate` at all, or that has not yet merged, is
    simply not a key in the block - `full_run_block` only ever enters a MERGED
    phase, and `full_status` only ever answers WHOLE, PROVISIONAL or UNKNOWN
    once a third place exists to ask. UNKNOWN never counts here: it is "ancestry
    could not be asked at all", which is a specific gap this condition does not
    claim - `unknown_full_runs` does.
    """
    block = (summary or {}).get("fullRun")
    if not isinstance(block, dict):
        return ["the full-gate ledger was never read, so whether a merged "
                "phase's tests are WHOLE was never asked - this is not a pass"]
    out = []
    for pid in sorted(block, key=str):
        row = block[pid]
        if isinstance(row, dict) and row.get(
                "answer") == _manifest_vocab.FULL_STATUS_PROVISIONAL:
            out.append("phase %s: %s"
                       % (pid, row.get("basis") or "no basis was recorded"))
    return out or None


def stale_full_runs(summary):
    """Provisional phases a full run has already run PAST, or None when
    `summary['fullRun']` was never computed. Never [].

    THE SHARPER CLAIM INSIDE `provisional`: not merely "not yet certified
    whole" but "a full run happened AFTER this phase merged and STILL does not
    contain it" - a plan actively falling behind its own third place rather
    than one that has not reached it yet. `full_run_block` carries the ONLY
    evidence this needs beside the phase's own `mergedAt` (already on the
    rollup): `wholeRunTs`, the moment of the newest full run
    `_full_disqualification` accepts, and `wholeRunId`, that same run's id -
    both `full_status`'s own keys, carried through `full_run_block` untouched,
    and both None when the ledger holds no such run. A run that passed but ran
    on a dirty tree, counted nothing or ran other commands is not "a full run
    happened", so it never supplies the moment, and no rule here re-decides
    which run counts.

    THE MOMENT AND THE RUN IT NAMES COME FROM ONE PAIR OF KEYS. `runId` is
    the run `full_status`'s answer is about, which on a WHOLE answer can be
    an older run than the newest accepted one; reading the moment from one
    run and printing the other's id would describe a run nobody recorded, so
    the message names `wholeRunId` beside `wholeRunTs` and never `runId`.

    MEASURED FROM `mergedHeadAt` WHEN THE PHASE CARRIES ONE, from `mergedAt`
    otherwise. A head recorded after the fact is the parent's head at that later
    moment, not the merge's own commit, so a whole-bearing run recorded between
    the merge and that moment contains the merge and not the head - and "ran
    after and still does not contain it" would be false about it. The sentence
    names which of the two moments it measured against.

    THE STAMPS ARE PARSED, NOT COMPARED AS TEXT, for `_gap_of`'s own reason:
    `mergedAt` and `wholeRunTs` are both written by this plugin's own commands in
    one UTC spelling today, but a hand-edited `mergedAt` need not agree, and a
    stamp neither side can parse dates nothing rather than being read for or
    against staleness.
    """
    block = (summary or {}).get("fullRun")
    if not isinstance(block, dict):
        return ["the full-gate ledger was never read, so whether a full run "
                "outran a provisional phase's merge was never asked - this is "
                "not a pass"]
    by_id = dict((p.get("id"), p) for p in (summary or {}).get("phases") or []
                if isinstance(p, dict))
    out = []
    for pid in sorted(block, key=str):
        row = block[pid]
        if not (isinstance(row, dict)
                and row.get("answer") == _manifest_vocab.FULL_STATUS_PROVISIONAL):
            continue
        run_when = _usage_core.parse_ts(row.get("wholeRunTs"))
        if run_when is None:
            continue
        phase = by_id.get(pid) or {}
        head_at = phase.get("mergedHeadAt")
        since = head_at if head_at else phase.get("mergedAt")
        merge_when = _usage_core.parse_ts(since)
        if merge_when is None or merge_when >= run_when:
            continue
        what = ("merged %s, its mergedHead recorded after the fact "
                "(mergedHeadAt %s)" % (phase.get("mergedAt"), head_at)
                if head_at else "merged %s" % (since,))
        out.append("phase %s: %s, but full run %s (%s) ran after and "
                   "still does not contain it"
                   % (pid, what, row.get("wholeRunId"), row.get("wholeRunTs")))
    return out or None


def unknown_full_runs(summary):
    """Merged phases whose full-run answer is UNKNOWN, each with `full_status`'s
    basis, or None when `summary['fullRun']` was never computed. Never [].

    THE STATE `provisional` REFUSES, given a condition of its own rather than
    folded into that one: "not yet contained" and "could not be asked" are
    different news with different repairs - re-run the full gate for the first,
    record a mergedHead, fetch history or fix the ledger for the second. Every
    cause arrives as the same UNKNOWN word with its cause in the basis:
    `full_status` writes the missing mergedHead and the ancestry git could not
    establish, and `full_run_block` writes a ledger it could not read or locate
    as every merged phase answering UNKNOWN. The basis is carried verbatim, so
    the gate line says WHICH of them it was and no rule here re-reads it.

    WHOLE, PROVISIONAL and NOT_DECLARED never count, and a plan naming no
    `meta.fullGate` hands over `{}` - nothing asked, nothing unknown. An ABSENT
    block is `provisional_phases`' third state for its reason: a gate reading
    it as clean would pass every repository where the injection failed.
    """
    block = (summary or {}).get("fullRun")
    if not isinstance(block, dict):
        return ["the full-gate ledger was never read, so whether a merged "
                "phase's full-run answer could be established was never asked "
                "- this is not a pass"]
    out = []
    for pid in sorted(block, key=str):
        row = block[pid]
        if isinstance(row, dict) and row.get(
                "answer") == _manifest_vocab.FULL_STATUS_UNKNOWN:
            out.append("phase %s: %s"
                       % (pid, row.get("basis") or "no basis was recorded"))
    return out or None


def invariant_breaches(summary):
    """The post-hoc breach list, or None when it was never computed. Never [].

    THREE STATES, AND A BOOLEAN WOULD HAVE TWO. The block arrives INJECTED by
    `audit-status.py`, which is where the git and ledger reads live (this module
    is layer 2 and `_invariants` is layer 4); the gate itself only reads what it
    was handed. So the interesting question is not "were there breaches" but
    "was anything read at all" — and a summary with no block is a summary nobody
    asked, which must not pass as a clean one. `None` is "no breaches, and the
    evidence was read"; a list is what was found; and an ABSENT block is also a
    list, holding the one sentence that says so.

    `evaluate_gate` therefore trips on `is not None`, which reads oddly until you
    see that it is the only spelling under which the missing block fails.
    """
    block = (summary or {}).get("invariants")
    if not isinstance(block, dict) or not isinstance(block.get("breaches"), list):
        return ["the invariant checks did not run, so nothing about them was "
                "verified - this is not a pass"]
    return block["breaches"] or None


def stranded_skills(summary):
    """The names this plan uses that a clone would not load, or None. Never [].

    THE SAME THREE STATES `invariant_breaches` has, for the same reason and with
    the same spelling of the trip: the block is INJECTED by `audit-status.py`,
    which owns the filesystem scan this module (layer two) may not reach, so an
    ABSENT block means nobody asked — and a gate that read that as clean would
    pass every repository where the enrichment silently failed.

    `graded` is carried beside `stranded` and checked here rather than trusted:
    a block that graded NOTHING — every name unresolvable, or portability off —
    has narrowed to nothing, and "no stranded names" over an empty set is the
    reading this repo refuses.
    """
    block = (summary or {}).get("portability")
    if not isinstance(block, dict) or not isinstance(block.get("stranded"), list):
        return ["the portability scan did not run, so whether this plan's "
                "skills would survive a clone was never asked - this is not a "
                "pass"]
    if not block.get("graded"):
        return ["no name in this plan could be graded, so nothing was checked - "
                "an empty result here is not a clean one"]
    return block["stranded"] or None


# --- a run that stopped mid-phase ------------------------------------------------
# `/audit:phase P5` means "execute every ready task in the phase, then run
# sign-off". A phase planned as waves of parallel subagents committed wave one,
# said which tasks wave two would be, and ENDED THE TURN. Nothing had blocked it:
# the lock was held, the manifest was valid, every remaining task was ready with
# its dependencies satisfied, no budget was declared and no guard had fired. The
# run sat idle until a human asked about it a day later.
#
# EVERY OTHER FAULT IN THIS PROJECT'S REGISTER IS A RULE THE CODE REFUSES OR A
# PROHIBITION NOTHING ENFORCES. This is a PRESCRIPTION nothing enforces - the
# document says run the phase to completion, a turn boundary between waves is
# exactly where that instruction has to survive, and nothing anywhere read it.
#
# THE STATE WAS ALREADY KNOWABLE, WHICH IS THE WHOLE IDEA. A phase whose lock is
# HELD while the plan still has READY work is a run that has not finished, and
# both halves are facts the plan and the lock file already carry. Nothing here
# caches either one.
#
# `phase-<id>` IS A RUN; `index` IS NOT. The index lock is what a structural write
# takes and gives back inside one command, so a run is never what is holding it,
# and a reading that counted it would fire on `/audit:task add`.
PHASE_LOCK_PREFIX = "phase-"
# What the sentence says after the verdict, per liveness, because the REPAIR is
# what differs and a reader under a red build has to be able to tell which one
# they have without opening anything.
UNFINISHED_LIVE = ("its holder is still there, so the run is either working or "
                   "sitting idle mid-procedure - `/audit:phase %s` picks the "
                   "remaining waves up")
UNFINISHED_STALE = ("its holder is gone, so nothing is going to finish it - "
                    "`/audit:resume` continues it, and `audit-lock.py release "
                    "phase-%s` gives the lock back")
# A zero from a copy that is not the live one says nothing about waves left -
# it says the count is not the run's - so its repair is about the reading, and
# it is the same whether the lock's holder is there or gone.
UNFINISHED_UNREAD = ("that zero is not from the copy holding phase %s live, "
                     "so it says nothing about work left - re-read the count "
                     "from the copy named, or check the branch, before acting "
                     "on the lock")


def unfinished_runs(summary):
    """The phase runs that stopped mid-phase, or None. Never [].

    THREE STATES, AND THE THIRD IS WHY THIS IS WORTH HAVING:

        lock held   + own ready work left   a run that has not finished
        lock held   + none of its own left  a sign-off in flight, or a lock to
                                            give back - `/audit:doctor` names it
        NO LOCK     + ready work left       every planned phase there has ever
                                            been, and the state this must be
                                            silent in

    Get that last row wrong and the signal fires on every plan in the world,
    which turns it into noise and gets it switched off inside a day. So the lock
    is the half that decides, and the phase's OWN ready work is what says the
    run had somewhere left to go.

    THE COUNT IS PER PHASE AND ARRIVES WITH THE LOCK ROW. A plan-wide ready list
    is one figure for every lock held, so with several phases locked each line
    printed the same number and none of them described its own phase. And the
    copy that holds a phase live may not be this checkout's: a phase run on its
    own branch leaves the development branch's shard stale. Reading a branch is
    a git call and this module opens nothing, so `audit-status.py` counts each
    held phase from the copy it judged live and hands over `readyCount` with
    `readyBasis`, the sentence naming that copy - which this line prints
    verbatim, because the copy is the claim's basis - and `readyLive`, True only
    when that copy IS the one holding the phase live.

    A ZERO IS SILENT ONLY WHEN IT WAS COUNTED FROM THE LIVE COPY. A zero read
    off a fallback copy is a stale reading of a phase whose real state lives
    elsewhere, so it prints, with its basis saying it is not current. Its
    repair is `UNFINISHED_UNREAD` rather than a resume: it says nothing about
    work left, only that the count must be re-read from the copy named. An
    absent `readyLive` is not a claim that the copy was live, so it is read as
    False.

    THE SAME THREE STATES `invariant_breaches` AND `stranded_skills` HAVE, plus
    the reading of a lock this one adds. The `locks` block is INJECTED by
    `audit-status.py` - a lock lives in the git dir and this module (layer two)
    may open nothing - so an ABSENT block means nobody asked, and a gate that
    read that as clean would pass every run where the injection silently failed.
    `evaluate_gate` therefore trips on `is not None`, which reads oddly until you
    see that it is the only spelling under which the missing block fails. A held
    phase lock whose row carries no count is refused for the same reason: zero
    is the silent row, so a count nobody computed must not read as one.

    A STALE LOCK COUNTS, AND THAT IS A DECISION RATHER THAN AN OVERSIGHT.
    `_locks.judge` resolves every uncertainty to LIVE, so `live: False` is not an
    absence of information - it is the positive finding that the holder was
    probed on this host and is gone. Excusing it would make this signal fall
    silent exactly as the abandonment became certain: the run abandoned mid-phase
    above was noticed a day later, by which time the session had long exited and
    its lock was stale. A rule that graded only live locks would have had nothing
    to say about the very instance it was written for. What liveness changes is
    the sentence, not the verdict.

    A lock whose name is not a phase's is skipped rather than graded, and the
    prefix says why. A row that is not a dict at all is a block this reader
    cannot grade, and it is refused rather than skipped - dropping it would
    shrink a gate its reader believes covers every lock held.
    """
    block = (summary or {}).get("locks")
    if not isinstance(block, dict) or not isinstance(block.get("held"), list):
        return ["the phase locks were never read, so whether a run stopped "
                "mid-phase was never asked - this is not a pass"]
    if not all(isinstance(row, dict) for row in block["held"]):
        return ["the lock list carries an entry that is not a lock, so what is "
                "held could not be graded - this is not a pass"]
    out = []
    for row in block["held"]:
        name = row.get("name")
        if not isinstance(name, str) or not name.startswith(PHASE_LOCK_PREFIX):
            continue
        phase = name[len(PHASE_LOCK_PREFIX):]
        count = row.get("readyCount")
        if not _is_count(count) or not row.get("readyBasis"):
            out.append("phase %s holds a lock, and how much of its own work is "
                       "still ready was never counted (%s) - this is not a pass"
                       % (phase, row.get("readyBasis")
                          or "no count and no reason were handed over"))
            continue
        # THE SILENT ROW. Nothing of its own is ready in the copy that holds
        # it live, so the run had nowhere left to go - whatever the rest of the
        # plan still has ready.
        if count == 0 and row.get("readyLive") is True:
            continue
        if count == 0:
            repair = UNFINISHED_UNREAD % (phase,)
        else:
            repair = (UNFINISHED_LIVE if row.get("live")
                      else UNFINISHED_STALE) % (phase,)
        out.append("phase %s holds a lock with %d task(s) still ready, %s: %s. %s"
                   % (phase, count, row["readyBasis"], row.get("basis")
                      or "no basis was recorded for the lock, which is itself a "
                         "reason to look at it", repair))
    return out or None


def _is_count(value):
    """A non-negative int that is not a bool - the shape a count of tasks has."""
    return (isinstance(value, int) and not isinstance(value, bool)
            and value >= 0)


# `_budget_detail` sat here between these two and went back to `audit-status.py`
# with the rest of the rendering: it turns `budget_breaches` into an English
# sentence with currency in it, which needs `_fmt` and is a thing a COMMAND says.
# Keeping it would have put a formatter in the module whose whole claim is that it
# only computes — and would have made `_fmt` a dependency of every consumer of the
# rollup.


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


# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio, selftest_requested  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if selftest_requested(sys.argv[1:]):
        # Answers rather than exiting silently: `--selftest` is what every other
        # file here accepts, so nothing would tell a reader whether this one ran
        # nothing or has nothing. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_status_facts.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__status_facts.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
