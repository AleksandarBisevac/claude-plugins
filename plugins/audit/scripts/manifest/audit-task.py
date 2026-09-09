#!/usr/bin/env python3
"""
audit-task.py -- the non-interactive task writer for /audit:task add (v0.37 C1).

/audit:task add used to dictate a hand-template into the model's hands: every
newly created task MUST carry status/attempts/maxAttempts/commit/outcome/
startedAt/completedAt/verifiedBy plus explicit blockedBy/dependsOn and a tests
object (manifest-conventions.md -> New task template) -- and hand-templating
fifteen-odd fields per add is a CLASS of error: a missed field, a misspelled
enum, a fileIndex nobody extended. This script IS the template. The command
gathers answers; this writes them, the same way every time, exactly once.

Usage:
  audit-task.py add "<title>" [manifest] [--phase P2]
                [--skills a,b | --skills null] [--model m] [--files f1,f2]
                [--risk low|med|high] [--blocked-by id,id] [--depends-on id,id]
                [--description TEXT] [--tests-mode tdd|regression|gate-only]
                [--tests-add TEXT ...] [--gate CMD ... | --gate-clear]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py add-phase "<title>" [manifest] --outcome "<what success is>"
                [--id P7] [--description TEXT] [--area a,b]
                [--gate CMD ... | --gate-clear]
                [--blocked-by id,id] [--review-skill NAME]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py cancel <id> --reason "<why>" [manifest]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py scope <taskId> [manifest] [--files f1,f2]
                [--tests-mode tdd|regression|gate-only] [--tests-add TEXT ...]
                [--gate CMD ... | --gate-clear] [--description TEXT]
                [--risk low|med|high] [--blocked-by id,id] [--depends-on id,id]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py retarget <phaseId> [manifest]
                [--gate CMD ... | --gate-clear] [--area a,b] [--outcome TEXT]
                [--description TEXT] [--project-dir DIR] [--takeover] [--json]
  audit-task.py --selftest

  <manifest> defaults to the project's configured manifestPath
  (.claude/audit.config.json, default docs/audit/audit-plan.json).
  --phase absent -> the single in_progress phase when that is unambiguous,
  else exit 2 naming the choices. --skills null is the explicit opt-out
  (v0.37 B1): written as JSON null, it STOPS the area fallback; absent/empty
  means "unconsidered" and is written as [] (the area default stays in
  force). A skill literally named "null" cannot be spelled from this flag;
  no such skill exists. --tests-add and --gate repeat (one value each).
  --risk, --blocked-by and --depends-on reach `scope` as well as `add`
  (F199): the same three fields `_build_task` sets at creation, correctable
  afterwards while the task has not started -- once it has, only `--files`
  and `--tests-add` are still on offer and only as a WIDENING (F271, and
  `_locked_scope` states why append-only is the exact operation that leaves
  a past judgement standing). They need no
  `--clear` twin -- `--blocked-by ""` empties the field, because a comma
  list of IDS has no value that reads as content the way `--gate ""` reads
  as an empty COMMAND, and `retarget --area ""` already draws that line.

Exit codes:
  0  written, manifest valid
  1  refused invalid: the manifest had findings before the write (nothing
     written), or the write itself would leave it invalid (every written file
     rolled back byte-for-byte); the findings are printed either way
  2  usage: unknown/ambiguous/done/reserved phase, missing manifest, bad args
  3  the index lock is held by a LIVE run (audit-lock's standard message)
  4  the index lock looks abandoned -- rerun with --takeover once a human
     has confirmed (audit-lock's standard message)

Design decisions, each mirroring a precedent rather than inventing one:

  * PROJECT (F-C-1). Which root owns the journal, the lock, the config and
    the file-existence notes: an explicit --project-dir wins; else a NAMED
    manifest derives the project upward from ITSELF (first ancestor holding
    `.claude/` or `.git` -- naming another project's manifest from this cwd
    must not journal or lock into THIS repo, the class audit-usage's
    resolve_ledger already solved); else $CLAUDE_PROJECT_DIR, else the cwd.

  * LOCK. The whole read-allocate-write runs under the INDEX lock, taken via
    audit-lock.py's own module (`main(["acquire", "index", ...])`) -- ids are
    allocated under the lock so two sessions can never mint the same one
    (manifest-conventions.md -> ID allocation). A held or stale lock prints
    the lock module's OWN output: one message shape everywhere. Outside a git
    repo the `<manifest>.lock` working-tree file is the fallback guard,
    exactly as in _panel_write._acquire_write_lock.

  * ID. `<phaseId>.<n>`, n = highest existing numeric suffix + 1, computed
    over the WHOLE assembled manifest plus every still-parked proposal
    payload -- gaps are history and never re-minted. A --phase naming an id
    RESERVED by a parked proposal is refused toward /audit:propose
    materialize (materialization is a move; hand-minting into a reserved id
    would make it a collision).

  * PHASE (F58). `add-phase` is the verb `/audit:phase add` calls, and it
    exists because nothing else in the tree appends to `phases[]` except the
    ADO pull: `/audit:init` synthesizes a whole plan, `/audit:propose
    materialize` MOVES a parked payload, and `add` places a task inside a phase
    that must already be there. So a maintainer whose plan outlived its first
    round -- the state every long-lived plan ends in -- had three options and
    all of them were wrong: re-run init over a finished plan, pull from a
    board, or hand-edit the index and write a shard. The phase id continues the
    sequence through `_proposals.next_phase_id` over live AND parked ids, which
    is the same allocation `/audit:propose materialize` uses rather than a
    second one; `--outcome` is required for `--reason`'s reason (a phase whose
    success cannot be stated in a line is a phase sign-off cannot address); and
    the sharded case writes the shard the phase does not have yet plus the
    index stub that points at it, which is the half a hand-edit forgets.

  * WRITE. Through _manifest_io -- never raw json for the sharded case. The
    footprint is _panel_write._write_back's: the touched phase's shard, plus
    the index only when fileIndex changed (meta lives there; rewriting
    untouched shards would manufacture merge conflicts the sharded layout
    exists to avoid). After the write the manifest is re-read from disk and
    validated in-process; findings roll every written file back
    byte-for-byte and exit 1 -- this script refuses to leave an invalid
    manifest behind.

  * HEAL (v0.37 A4). Reuses _panel_write._heal_phase_status on the target
    phase: a write this code makes must not persist a pending phase that
    already holds an in_progress task. The validator warning stays as the
    backstop for hand edits.

  * JOURNAL. A `task.add` row through audit-journal's `append`, in-process --
    see _journal_add for why the journal-writes hook cannot see this write.

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test_audit_task.py`, byte-identical labels and all - see
`plugins/audit/tests/_harness.py`. The note on which id LETTERS the suite has
already taken went with them, because it is advice to whoever adds the next case.

Stdlib only, Python 3.8 compatible.
"""
import argparse
import json
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

import _manifest_io as _mio   # noqa: E402  (dual-format loader; single-file OR index+shards)
import _areas                 # noqa: E402  (areas_of: the one area resolution every surface shares)
import _proposals             # noqa: E402  (the id allocator `/audit:propose materialize`
#                                            uses: the lowest free P<n> over live AND
#                                            parked ids. A second one here would be a
#                                            second answer about which ids are taken)
import _status_facts          # noqa: E402  (unmet_refs: the ONE answer to "what is this
#                                            waiting on". A downward edge, L7 -> L2, with
#                                            precedent at audit-status.py, _invariants.py
#                                            and _report_page.py -- see `_waiting_on` for
#                                            what the second copy here got wrong)
import _panel_write           # noqa: E402  (one answer to "where is the manifest", the
#                                            byte-shape writer, the A4 heal, the lock and
#                                            journal module handles -- reused by identity,
#                                            not reimplemented)
import _warning_groups as _wg  # noqa: E402  (the shape a repeated warning prints in)

E_INVALID, E_USAGE, E_LIVE, E_STALE = 1, 2, 3, 4

# The conventions template (manifest-conventions.md -> New task template), as
# data: every field a new task is initialized with, in the order it is written.
_TEMPLATE_KEYS = ("id", "title", "status", "description", "files", "tests",
                  "model", "skills", "risk", "blockedBy", "dependsOn",
                  "attempts", "maxAttempts", "commit", "outcome", "startedAt",
                  "completedAt", "verifiedBy")

# The same thing one level up (manifest-conventions.md -> New phase template):
# every field a new PHASE is initialized with, in the order it is written.
# `area` and `reviewSkill` are deliberately absent -- the conventions default
# both to ABSENT, and writing `area: null` would make an untagged phase claim to
# have considered the question.
_PHASE_TEMPLATE_KEYS = ("id", "title", "status", "description",
                        "desiredOutcome", "testGate", "blockedBy", "baseRef",
                        "branch", "mergedAt", "review", "summary", "tasks")


# --- flag parsing helpers ------------------------------------------------------
def _split_csv(val):
    """`a,b , c` -> ["a", "b", "c"]; None/empty -> []."""
    if not isinstance(val, str):
        return []
    return [part.strip() for part in val.split(",") if part.strip()]


def _union_paths(declared, extra):
    """`declared` plus anything in `extra` it does not already carry, order kept.

    ORDER IS KEPT because the list is read by people: the files the author typed
    stay where they typed them, and the ones derived from `tests.add` follow. A
    `sorted(set(...))` would produce the same scope and a different document on
    every edit, which is a diff nobody can review.
    """
    out = list(declared or [])
    seen = set(out)
    for path in (extra or []):
        if isinstance(path, str) and path.strip() and path not in seen:
            out.append(path)
            seen.add(path)
    return out


def _parse_skills(val):
    """Three states, spelled the way the schema spells them (v0.37 B1):
    absent/empty -> [] (unconsidered; the area default stays in force);
    the literal `null` -> None (the explicit opt-out, JSON null in the file,
    stopping the area fallback); anything else -> the comma-split list."""
    if not isinstance(val, str) or not val.strip():
        return []
    if val.strip() == "null":
        return None
    return _split_csv(val)


# --- the refusals and report lines more than one verb spends ------------------
# Not a "helpers" pile: each of these exists because TWO call sites would
# otherwise spell one fact, and the file already carries a note about what that
# costs (`_journal_row`: two verbs, two drifted copies, neither visible from the
# row that was written).
def _gate_contradiction(args):
    """The refusal line for `--gate` with `--gate-clear`, or None.

    ONE SENTENCE, THREE VERBS. `add`, `scope` and `retarget` all take both flags
    off the same global parser and the rule is one rule about one field: two
    answers to one question, and guessing which the caller meant is how a task
    ends up gated on a command nobody asked for. `scope` and `retarget` each
    carried their own copy of the sentence; `add` needed a third when it learned
    to read the flag (F201), and three copies of a refusal is how one of them
    eventually stops matching the other two.

    Every caller asks it in the SAME POSITION -- under the lock, after the target
    has been resolved and before anything is mutated -- so the order a caller
    meets its refusals in does not depend on which verb it typed.
    """
    if args.gate and args.gate_clear:
        return ("[audit-task] --gate and --gate-clear say opposite things about "
                "the same field -- pass one")
    return None


def _model_floor(risk):
    """The model `add` derives for a task at `risk` when the caller names none.

    ONE HOME for the escalation rule (`commands/task.md`: sonnet is the floor for
    all fix work, `risk: high` escalates to opus unless the caller chose). It is
    a function rather than an inline conditional because `scope --risk` has to be
    able to SAY that it did not re-apply it, and two spellings of "high means
    opus" would be two answers about what a rescoped task runs on.
    """
    return "opus" if risk == "high" else "sonnet"


def _empty_task_gate_note(now):
    """What an empty `tests.gate` MEANS, said once for the two verbs that reach it.

    `reference/orchestrator.md` has the executor run `task.tests.gate` and phase
    sign-off run `phase.testGate`, so an emptied task gate is not an ungraded
    task -- and silence over a designed state reads as breakage, which is why
    both verbs say it. The tense is the ONLY difference between the call sites:
    `scope` reports a change and `add` reports the state a creation arrived in.
    The explanation after it is one fact and is not spelled twice.
    """
    return ("  the gate is %sEMPTY: this task runs no gate command of its own, "
            "and the phase's testGate at sign-off is what still grades it"
            % ("now " if now else "",))


def _readiness_lines(waiting, tid):
    """The sentences `add` and `scope` both print about whether a task can run now.

    Shared because the `/audit:run <id>` handoff is a spelling a reader COPIES,
    and a second copy of it is the shape this repo's own cautionary tale is about
    (one formatter, three implementations, two of them disagreeing).
    """
    if waiting:
        return ["  waiting on: %s" % ", ".join(waiting)]
    return ["  ready now -- /audit:run %s" % tid]


# --- widening a scope that has already governed something (F271) ---------------
# `scope` used to refuse every task that was not pending-and-never-attempted, and
# `reference/orchestrator.md` prescribes `/audit:task scope` for the one case that
# description excludes: the plan gate refuses a file a RUNNING task needs, the
# task is `in_progress` with an attempt on it, and widening `task.files` is the
# documented remedy. So the documented remedy was unreachable in exactly its own
# scenario, and the only escape was the hand edit `commands/task.md` forbids --
# measured live, three times in one phase.
#
# THE OLD REFUSAL WAS NOT WRONG, IT WAS TOO WIDE, and the vocabulary below is what
# narrows it to the changes its reason actually covers.
_WIDENABLE = ("files", "tests.add")


def _started(task):
    """True when this task's scope has already governed something.

    TWO SIGNALS, EITHER ONE ENOUGH, and they are genuinely independent rather
    than one fact spelled twice. The orchestrator sets `in_progress` and
    increments `attempts` in the same step, but a task that ran, failed and was
    put back to `pending` carries the count with no status left to show for it
    (F190's case), and a task moved to `blocked` before its first spawn carries
    the status with no count. Reading only the status is how the guard here was
    written the first time, and F190 is the entry that added the other half.
    """
    if not isinstance(task, dict):
        return False
    return (task.get("status") != "pending"
            or (_mio.recorded_attempt(task) or 0) > 0)


def _attempt_phrase(task):
    """`during attempt N, while the task is <status>` -- or what is true instead.

    `_mio.recorded_attempt` has THREE answers and this keeps all three, because
    this line's whole job is to DATE a change and a date is the last place to
    invent a figure: a number is named, a recorded zero says the widening landed
    before any attempt was written down, and a task whose `attempts` is missing
    or not an integer gets a sentence about the gap. The alternative -- defaulting
    to 1, which is how that field has been misread here before -- would put a
    claim with no basis on the row a reader consults to find out when the scope
    grew.
    """
    status = (task or {}).get("status")
    attempt = _mio.recorded_attempt(task)
    if attempt is None:
        return ("while the task is %s, which records no attempt count -- so this "
                "cannot be dated to one" % (status,))
    if not attempt:
        return ("while the task is %s, before any attempt was recorded"
                % (status,))
    return "during attempt %s, while the task is %s" % (attempt, status)


def _narrowings(changes):
    """The rows in `changes` that are NOT a widening, each as a printable clause.

    APPEND-ONLY IS THE EXACT OPERATION THAT CANNOT RE-JUDGE A PAST COMMIT, and
    that is a property of a check rather than a feeling about safety.
    `_invariants.commit_scope` grades a task's RECORDED commit against the task's
    CURRENT `files`: every path the commit staged has to be in that list today.
    Adding a path can only turn a breach into a pass; removing one can turn a
    commit that was clean when it was made into a breach, which is a verdict
    changed after the fact on work nobody can go back and redo. The plan gate
    reads the same list forward (`hooks/_config.in_progress_task_map`), so a
    widening only ever ALLOWS an edit that was being refused.

    Every other field is refused because none of them has a safe direction:
    `risk` and `tests.mode` REPLACE a value the attempt ran under, `description`
    rewrites the question the outcome answered, and a ref list that GROWS blocks
    a task that has already started -- growth is not harmless there, which is why
    "append-only" is a rule about two named fields and not about the word.
    """
    out = []
    for row in changes:
        was, now = row.get("from") or [], row.get("to") or []
        if row["field"] in _WIDENABLE:
            dropped = [item for item in was if item not in now]
            if dropped:
                out.append("`%s` would drop %s"
                           % (row["field"], ", ".join(str(d) for d in dropped)))
        else:
            out.append("`%s` would move from %s to %s"
                       % (row["field"], json.dumps(row.get("from")),
                          json.dumps(row.get("to"))))
    return out


def _rescope_refusal(tid, task, blockers):
    """The refusal for a change `scope` will not make to a task that has moved.

    TWO HEADS, ONE TAIL. The basis differs and this repo's rule is that a claim
    carries the one that makes it true: a task can be `in_progress` with no
    attempt recorded, and a task put back to `pending` can carry several. The
    tail is shared because what is still on offer and what was asked for are one
    fact each, and neither depends on which head printed.

    THE `attempts` SENTENCE IS KEPT VERBATIM (F190's wording). It is what
    `commands/task.md` quotes, and it is still true of every change this arm
    refuses -- the outcome describes work judged under the current scope, and
    these changes would make that record describe something else. What F271
    changed is the LAST sentence: cancel-and-re-add is no longer the only way
    out, so a refusal that still said it was would send an operator to the
    expensive route for a change the verb now takes.
    """
    attempt = _mio.recorded_attempt(task)
    status = (task or {}).get("status")
    if status == "done":
        # F283's THIRD HEAD. A done task is not running and may have no attempt
        # recorded, so both heads below say something false about it - one would
        # claim a gate is matching edits nobody is making, the other needs a
        # number this task may not carry. What is true of it is the grading: its
        # commit was measured against the list it holds, and a narrowing would
        # move that judgement after the fact.
        head = ("[audit-task] %s is done -- the commit it recorded was graded "
                "against the files it names, so dropping one now would move a "
                "judgement that has already been made." % (tid,))
    elif attempt:
        head = ("[audit-task] %s has already been attempted (%s) -- its outcome "
                "describes work judged under the current scope, so rescoping it "
                "would make that record describe something else."
                % (tid, attempt))
    else:
        head = ("[audit-task] %s is %s -- it is running against the scope it "
                "has, and the plan gate has been matching its edits to that "
                "list since it started." % (tid, status))
    return ("%s Refused: %s. WIDENING is the one change that cannot re-judge "
            "what already happened, so `files` and `tests.add` may still GAIN "
            "entries here -- pass the list the task holds plus the new ones. "
            "For anything else, cancel the task and add the work again."
            % (head, "; ".join(blockers)))


# --- project resolution --------------------------------------------------------
# An ALIAS, not a copy. The body moved into `_panel_write` when `set-priority.py`
# needed the same answer: a second command deriving "which project owns this
# manifest" by its own walk is a second answer, and the two would drift on exactly
# the markerless case F-C-2 was about. The name stays here because this file spells
# it unqualified and its suite asks for it by hand.
_project_of_manifest = _panel_write.project_of_manifest


def _resolve_project(args):
    """Which root owns the journal, the lock, the config and the file notes.

    F-C-1: keying this off the cwd while the manifest was explicitly named
    wrote the `task.add` journal row into the CWD repo's journal -- the exact
    class audit-usage's resolve_ledger solved ("When a manifest was named,
    search upward from IT"). The decision table:

      explicit --project-dir            -> it (the human said so)
      else a NAMED manifest             -> derived upward from the manifest
                                           ITSELF (beats CLAUDE_PROJECT_DIR:
                                           the env names the session's repo,
                                           the positional names THIS add's)
      else                              -> $CLAUDE_PROJECT_DIR, then the cwd
                                           (audit-usage's resolve_project
                                           order)
    """
    if args.project_dir:
        return os.path.abspath(args.project_dir)
    if args.manifest:
        return _project_of_manifest(args.manifest)
    return os.path.abspath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


# --- the lock ------------------------------------------------------------------
def _acquire_lock(project, config, mpath, takeover, out):
    """Take the index lock for the whole read-allocate-write, with this
    command's prefix on the one line it adds to the lock module's own message.

    The body moved into `_panel_write` when `set-priority.py` needed the same
    acquire: the lock library prints the standard refusal either way, and the
    only thing that differs between two commands is which name goes in front of
    "rerun with --takeover". Two copies of the fallback path would have been two
    answers about what happens outside a git repo."""
    return _panel_write.acquire_index_lock(project, config, mpath, takeover,
                                           out, "[audit-task]", "task add")


# An ALIAS, for `_project_of_manifest`'s reason.
_release_lock = _panel_write.release_index_lock


# --- phase resolution + id allocation ------------------------------------------
def _phase_label(ph):
    return "%s (%s)" % (ph.get("id"), ph.get("status"))


def _reserving_proposal(assembled, pid):
    """The still-parked proposal whose payload reserves `pid`, or None.

    Phase AND task ids, because `_proposals.parked_ids` reserves both: an id
    that collides with a payload's TASK id is refused with the same sentence
    rather than minted over an id materialization would then have to rename.
    One walk, because two verbs ask this question (`add --phase`, `add-phase
    --id`) and two walks are two answers about which ids are spoken for."""
    for prop in (assembled.get("proposals") or []):
        if not isinstance(prop, dict) or prop.get("status") != "proposed":
            continue
        payload = prop.get("payload")
        pphase = payload.get("phase") if isinstance(payload, dict) else None
        if not isinstance(pphase, dict):
            continue
        if pphase.get("id") == pid:
            return prop.get("id")
        for tsk in (pphase.get("tasks") or []):
            if isinstance(tsk, dict) and tsk.get("id") == pid:
                return prop.get("id")
    return None


def _reserved_refusal(pid, prop_id):
    """The one sentence both verbs print for an id a parked payload owns."""
    return ("[audit-task] phase %s is RESERVED by parked proposal %s "
            "-- run /audit:propose materialize %s first "
            "(materialization is a move; minting into a reserved id "
            "by hand would collide)." % (pid, prop_id, prop_id))


def _resolve_phase(assembled, want, out):
    """The target phase dict, or an int exit code after printing why not."""
    phases = [p for p in (assembled.get("phases") or []) if isinstance(p, dict)]
    if want:
        for ph in phases:
            if ph.get("id") == want:
                if ph.get("status") == "done":
                    out("[audit-task] phase %s is done -- done phases are "
                        "immutable history. Pick an open phase, or create a "
                        "new one with /audit:phase add." % want)
                    return E_USAGE
                return ph
        reserving = _reserving_proposal(assembled, want)
        if reserving:
            out(_reserved_refusal(want, reserving))
            return E_USAGE
        out("[audit-task] no phase %s in the manifest; phases: %s"
            % (want, ", ".join(_phase_label(p) for p in phases) or "(none)"))
        return E_USAGE
    inprog = [p for p in phases if p.get("status") == "in_progress"]
    if len(inprog) == 1:
        return inprog[0]
    if not inprog:
        openp = [p for p in phases if p.get("status") != "done"]
        out("[audit-task] no in_progress phase to default to -- pass --phase. "
            "Open phases: %s"
            % (", ".join(_phase_label(p) for p in openp) or "(none)"))
        return E_USAGE
    out("[audit-task] --phase required -- %d phases are in_progress: %s"
        % (len(inprog), ", ".join(p.get("id") or "?" for p in inprog)))
    return E_USAGE


def _allocate_id(assembled, phase_id):
    """`<phaseId>.<n>`, n = highest existing numeric suffix + 1, over the
    WHOLE assembled manifest (a misfiled task still counts) plus every
    still-parked proposal payload (reserved ids stay reserved). Gaps are
    history: P2.1 + P2.3 allocate P2.4, never P2.2 again."""
    prefix = str(phase_id) + "."
    top = 0

    def _count(tasks):
        nonlocal top
        for t in tasks:
            if not isinstance(t, dict):
                continue
            tid = str(t.get("id") or "")
            if tid.startswith(prefix) and tid[len(prefix):].isdigit():
                top = max(top, int(tid[len(prefix):]))

    # The manifest's own tasks come from `_mio.iter_tasks`; the proposal payloads
    # below cannot, because a parked payload's phase is NOT in `manifest["phases"]`
    # yet — reserving its ids is the whole point of reading it separately.
    _count(t for _ph, t in _mio.iter_tasks(assembled))
    for prop in (assembled.get("proposals") or []):
        if not isinstance(prop, dict) or prop.get("status") != "proposed":
            continue
        payload = prop.get("payload")
        pphase = payload.get("phase") if isinstance(payload, dict) else None
        if isinstance(pphase, dict):
            _count(pphase.get("tasks") or [])
    return "%s%d" % (prefix, top + 1)


# --- write-back + rollback -----------------------------------------------------
# ALIASES, for `_project_of_manifest`'s reason: two commands that both refuse to
# leave an invalid manifest behind must roll back the same way, or one of them
# eventually learns something the other does not.
_snapshot = _panel_write.snapshot
_restore = _panel_write.restore


def _shard_rel_dir(raw_index):
    """The directory the existing shards live in, so a NEW one joins them.

    Read off a stub rather than assumed to be `_mio.save_sharded`'s default: a
    manifest split with a different `shard_rel_dir` would otherwise get its next
    phase written into a second directory, and the index would end up pointing
    at two layouts at once. The default is the fallback for an index that has no
    stub to read (a sharded manifest with no phases yet)."""
    for stub in (raw_index.get("phases") or []):
        if isinstance(stub, dict) and isinstance(stub.get("shard"), str):
            rel = os.path.dirname(stub["shard"])
            if rel:
                return rel
    return "phases"


def _new_stub_and_body(phase, shard_rel_dir):
    """`(index stub, shard body)` for a phase that has neither yet.

    Through `_mio.split_manifest` rather than by composing `{id, title, shard}`
    here: that function is where the stub's key set and the shard's FILENAME are
    decided, and a second spelling of either would be a second layout the next
    `load_manifest` has to agree with. It is handed a one-phase manifest, so
    what comes back is this phase's halves and nothing else."""
    index, shards = _mio.split_manifest({"phases": [phase]}, shard_rel_dir)
    body = shards.get(phase.get("id"))
    return index["phases"][0], dict(body or {})


def _write_paths(project, mpath, raw_index, phase_id, new_phase=None):
    """The files a write MAY touch, for the pre-write snapshot: the manifest
    itself, plus the phase's shard in the sharded layout.

    `new_phase` is the phase this write CREATES, and it is passed for the
    SNAPSHOT's sake rather than the write's: a shard that does not exist yet is
    snapshotted as absent, which is what makes a rollback delete it. Without it
    a refused `add-phase` would leave a shard body behind that the restored
    index no longer points at -- a file the next reader cannot explain."""
    paths = [mpath]
    if not _mio.is_sharded(raw_index):
        return paths
    base = os.path.dirname(os.path.abspath(mpath))
    for stub in (raw_index.get("phases") or []):
        if isinstance(stub, dict) and stub.get("id") == phase_id \
                and "shard" in stub:
            paths.append(os.path.abspath(os.path.join(base, stub["shard"])))
            return paths
    if isinstance(new_phase, dict):
        stub, _body = _new_stub_and_body(new_phase, _shard_rel_dir(raw_index))
        paths.append(os.path.abspath(os.path.join(base, stub["shard"])))
    return paths


def _write_add(project, mpath, raw_index, assembled, phase_id, files_changed):
    """Persist the patched manifest into whichever layout it is stored in.
    SINGLE FILE: write the assembled dict; it IS the file. SHARDED: the
    touched phase's shard, and the index only when fileIndex changed --
    _panel_write._write_back's footprint, for its reasons. Returns the
    project-relative paths written (shard first, index-precedent order)."""
    if not _mio.is_sharded(raw_index):
        _panel_write._atomic_write_json(mpath, assembled)
        return [_output.posix_rel(mpath, project)]
    base = os.path.dirname(os.path.abspath(mpath))
    by_pid = {p.get("id"): p for p in (assembled.get("phases") or [])
              if isinstance(p, dict)}
    written = []
    index_dirty = bool(files_changed)
    stub = None
    for entry in (raw_index.get("phases") or []):
        if isinstance(entry, dict) and entry.get("id") == phase_id:
            stub = entry
            break
    body = dict(by_pid.get(phase_id) or {})
    new_stub = None
    if stub is None:
        # A phase this write CREATED (`add-phase`): neither half of it exists on
        # disk yet. Letting it fall through to the inline branch below would find
        # nothing to replace and set nothing dirty, so the phase would live only
        # in the assembled dict this function was handed and the write would
        # report success having written no phase at all.
        new_stub, body = _new_stub_and_body(body, _shard_rel_dir(raw_index))
        stub = new_stub
        index_dirty = True
    if "shard" in stub:
        spath = os.path.abspath(os.path.join(base, stub["shard"]))
        if not _panel_write._within(project, spath):
            raise ValueError("refused: shard path escapes project: %s"
                             % stub["shard"])
        body.pop("shard", None)   # the stub owns the pointer, never the body
        _panel_write._atomic_write_json(spath, body)
        written.append(_output.posix_rel(spath, project))
    else:
        # Inline phase in a sharded index (mixed/defensive): its body lives in
        # the index itself, so the index write below must carry it.
        idx_phases = raw_index.get("phases") or []
        for i, entry in enumerate(idx_phases):
            if isinstance(entry, dict) and entry.get("id") == phase_id:
                idx_phases[i] = by_pid.get(phase_id) or entry
                index_dirty = True
    if index_dirty:
        idx = dict(raw_index)
        if new_stub is not None:
            # Appended, never inserted: the written order IS the plan's order
            # (`/audit:phase priority` is what says "reach for this one first"),
            # so a new phase goes last for the same reason `/audit:init --append`
            # continues the sequence rather than renumbering it.
            idx["phases"] = list(raw_index.get("phases") or []) + [new_stub]
        if files_changed:
            idx["fileIndex"] = assembled.get("fileIndex") or {}
        _panel_write._atomic_write_json(mpath, idx)
        written.append(_output.posix_rel(mpath, project))
    return written


# --- the journal ---------------------------------------------------------------
def _journal_row(project, config, mpath, action, summary, details):
    """One journal row, appended in-process via audit-journal's `append`.

    Why this script writes its own rows: the journal-writes HOOK observes
    Edit/Write/MultiEdit/NotebookEdit TOOL calls only (hooks.json's
    PostToolUse matcher) -- a manifest written by this script through
    os.replace never passes through a tool that hook can see.
    _panel_write._journal is the precedent (the panel's saves have exactly
    the same blindness), and /audit:task move's CLI append is the row-shape
    precedent: action + target + summary + allow-listed details
    ({taskId, phaseId}, {fromId, toId, ...}) -- no new shape is invented.
    Fail-soft by the same contract: work that WAS written must never be
    reported as failed because the record of it could not be.

    ONE ROW BUILDER, not one per verb. `add` and `cancel` each carried their
    own and the two had drifted where nothing looks: `cancel` passed the whole
    `_viewer()` DICT as `actor.author`, and `_journal_io` normalises a non-string
    author to None -- so every cancel row recorded no author at all, and
    `via` defaulted to `unknown` where the add row says `cli`. Neither could
    be seen from the row that was written; both are the reason the builder is
    shared rather than the shape being restated a third time for `add-phase`.
    """
    mod = _panel_write._journalmod()
    if mod is None or not hasattr(mod, "append"):
        return {"journaled": False, "journaledWhy": "unavailable"}
    # THE PLACEMENT RULE (F-C-2): the journal lands in a sane place INSIDE
    # the named manifest's tree -- never doubled, never outside. A project
    # with a config keeps its own answer (config=None -> audit-journal's
    # load_config resolves journal.dir/manifestPath/enabled exactly as
    # before). A project with NO config would get audit-journal's DEFAULT
    # manifestPath rel appended under the resolved root -- doubling the
    # layout, or conjuring docs/audit into a bare tree -- so the handed-over
    # config pins manifestPath to where the named manifest actually IS, and
    # the journal lands beside it (<manifest dir>/journal).
    cfg = None if config else \
        {"manifestPath": _output.posix_rel(mpath, project)}
    try:
        ok = bool(mod.append(project, {
            "action": action,
            # Persisted row: "/" separators regardless of platform, like every
            # other journal path (n3 pins it; Windows relpath says backslash).
            "target": _output.posix_rel(mpath, project),
            "summary": summary,
            "details": details,
            "actor": {"author": _panel_write._viewer(project,
                                                    config).get("author"),
                      "sessionId": os.environ.get("CLAUDE_CODE_SESSION_ID"),
                      "via": "cli"}}, config=cfg))
    except Exception:
        ok = False
    return {"journaled": True} if ok else {"journaled": False,
                                           "journaledWhy": "failed"}


def _journal_add(project, config, mpath, task_id, phase_id, title, healed):
    """The `task.add` row: what was added, where, and what the write healed."""
    summary = "%s added to %s: %s" % (task_id, phase_id, title)
    if healed:
        summary += "; " + "; ".join(_panel_write._fmt_change(r) for r in healed)
    return _journal_row(project, config, mpath, "task.add", summary,
                        {"taskId": task_id, "phaseId": phase_id})


def _journal_scope(project, config, mpath, task_id, phase_id, changes, task):
    """The `task.scope` row: which fields moved, to what, and under which attempt.

    `changes` is the allow-listed shape `_journal_io.DETAILS_KEYS` already
    carries - id/field/from/to per row - so the cascade spelling every other
    writer here uses is the one this reuses rather than inventing a `files` key
    the allow-list would drop in silence. `_journal_phase_add`'s note says what
    that costs: a field written, dropped, and believed.

    `attempt` IS A NEW KEY ON THAT ALLOW-LIST (F271), and it passes the three
    tests the list states beside itself. It names a FIELD OF THE PLAN --
    `task.attempts` is a manifest key, not something the plugin observed about
    the machine; it is bounded like every other value; and it exposes nothing
    new, since the same number is in the manifest this row is about. It earns
    its place because `scope` now accepts a WIDENING mid-run: without it a row
    reads as though the task always had that scope, and the one question a
    reader brings to a widened task -- was this list already there when attempt
    two was judged, or did it grow during it -- has no answer on the trail.

    THE SPELLING IS `_evidence_io`'s, singular `attempt`, deliberately: that
    module's rows already carry the attempt an evidence row is stamped with, and
    a journal row calling the same number `attempts` would make a reader join
    two records on a field name that differs by a letter.

    WRITTEN WHENEVER THE PLAN RECORDS ONE, including a recorded zero, and absent
    only when `recorded_attempt` says the task records nothing. A key present
    solely on the mid-run rows could not be told from a key nobody wrote, which
    is the trap `_evidence_io` names one file over.
    """
    fields = ", ".join(row["field"] for row in changes)
    attempt = _mio.recorded_attempt(task)
    if _started(task):
        # A DIFFERENT EVENT DESERVES A DIFFERENT SENTENCE. `audit-journal list`
        # prints the summary and nothing else, so a mid-run widening that read
        # like every other scope row would need `details` opened to be seen at
        # all -- and it is the row a reader is looking for.
        summary = ("%s WIDENED in %s %s: %s"
                   % (task_id, phase_id, _attempt_phrase(task), fields))
    else:
        summary = "%s scoped in %s: %s" % (task_id, phase_id, fields)
    details = {"taskId": task_id, "phaseId": phase_id, "changes": changes}
    if attempt is not None:
        details["attempt"] = attempt
    return _journal_row(project, config, mpath, "task.scope", summary, details)


def _journal_retarget(project, config, mpath, phase_id, changes):
    """The `phase.retarget` row: which of the phase's fields moved, and to what.

    `changes` again, for `_journal_scope`'s reason - the allow-list carries that
    shape and would drop an invented `testGate` key in silence.
    """
    fields = ", ".join(row["field"] for row in changes)
    return _journal_row(project, config, mpath, "phase.retarget",
                        "%s retargeted: %s" % (phase_id, fields),
                        {"phaseId": phase_id, "changes": changes})


def _journal_phase_add(project, config, mpath, phase_id, title, outcome):
    """The `phase.add` row.

    The DESIRED OUTCOME rides the SUMMARY, not `details`. It belongs in the row
    -- it is the sentence sign-off has to address, and a trail recording that a
    phase appeared without recording what it was for answers the wrong question
    a month later -- but `_journal_io.DETAILS_KEYS` is an allow-list and drops
    an unlisted key in silence, so a `details.desiredOutcome` would have been a
    field written, dropped, and believed. `details` therefore carries only the
    allow-listed `phaseId`, which is the same join `task.add` writes."""
    summary = "%s added: %s" % (phase_id, title)
    if outcome:
        summary += " -- %s" % outcome
    return _journal_row(project, config, mpath, "phase.add", summary,
                        {"phaseId": phase_id})


# --- readiness (report only) ---------------------------------------------------
def _waiting_on(assembled, node):
    """What `node` is still waiting on -- `_status_facts.unmet_refs`' answer for
    its id, looked up rather than recomputed.

    F275. THIS WAS A THIRD COPY OF THE READINESS RULE, AND IT WAS THE ONE THAT
    HAD GONE WRONG. It read `blockedBy + dependsOn` off the TASK and stopped
    there, while `reference/orchestrator.md`'s rule has FOUR terms and the fourth
    is the owning PHASE's `blockedBy` -- which no task dict carries and which
    this function, handed only a task, could not have reached. So `add` and
    `scope` printed a copyable `ready now -- /audit:run <id>` for a task whose
    phase was blocked, while `/audit:status` (reading `_status_facts`) said the
    opposite about the same manifest. Measured live.

    A SECOND COPY OF THIS RULE IS THE HAZARD, not a tidiness question, and the
    note beside `_manifest_io.TERMINAL` records the first time it bit at exactly
    this call site: the old body tested `!= "done"` while readiness counted
    `("done", "cancelled")`, so a task blocked by a CANCELLED task was ready to
    `/audit:status` and still waiting to `/audit:task add`. Both divergences were
    a term this file never heard about, which is what a copy cannot be fixed
    into: the repair is to stop having one. `unmet_refs` also spells a
    phase-level blocker `"<id> (phase)"`, so the reader is told WHICH of the four
    terms is unmet instead of being handed a bare id that resolves to no task.

    THE ID IS THE KEY, which is what makes the phase term reachable at all -- the
    node is found in `assembled` and its owning phase with it. Every caller has
    just put it there (`add` appends the task, `add-phase` the phase) or found it
    there (`scope`), so there is no call site where this can miss.
    """
    return _status_facts.unmet_refs(assembled).get((node or {}).get("id")) or []


# --- the add -------------------------------------------------------------------
def _build_task(task_id, title, args, phase):
    """The new task, fully template-initialized -- every field from the
    conventions' New task template, exactly once, in _TEMPLATE_KEYS order."""
    risk = args.risk or "low"
    # sonnet is the floor for all fix work; risk high escalates to opus unless
    # the caller chose explicitly (commands/task.md's long-standing rule).
    model = args.model or _model_floor(risk)
    mode = args.tests_mode or "gate-only"
    if args.gate:
        gate = list(args.gate)
    elif args.gate_clear:
        # F201. The flag is defined globally, so argparse ACCEPTED it here and
        # nothing read it: `add --gate-clear` reported success and wrote the
        # phase's `testGate` anyway. A flag accepted and ignored is the defect
        # F196 was one verb over -- the operator is told the call succeeded and
        # the value they asked for is not there. The empty gate is a designed
        # state (`_phase_gate`, and `scope --gate-clear` for a task that already
        # exists); creation is where the COPY of the phase gate is made, so it is
        # the one place a task could not be given the state without a rescope.
        gate = []
    else:
        gate = [g for g in (phase.get("testGate") or []) if isinstance(g, str)]
    return {
        "id": task_id,
        "title": title,
        "status": "pending",
        "description": args.description or "",
        # `tests.add` IS PART OF `files`, and keeping them apart cost a real run 13
        # hand-fixes (F258). A tdd task creates the file it names in `tests.add` by
        # definition, so a scope that excludes it trips commit-scope on the task's
        # own commit — and the operator who reported it put it plainly: there is no
        # case where the divergence is wanted. Unioned rather than replaced, and the
        # declared order is kept, so a reader still sees what the author typed first.
        "files": _union_paths(_split_csv(args.files), args.tests_add),
        "tests": {
            "mode": mode,
            "add": list(args.tests_add or []),
            # true iff tdd -- the machine-readable disambiguation of `add`.
            "expectRedFirst": mode == "tdd",
            "gate": gate,
        },
        "model": model,
        "skills": _parse_skills(args.skills),
        "risk": risk,
        "blockedBy": _split_csv(args.blocked_by),
        "dependsOn": _split_csv(args.depends_on),
        "attempts": 0,
        "maxAttempts": 3,
        "commit": None,
        "outcome": {"technical": None, "descriptive": None},
        "startedAt": None,
        "completedAt": None,
        "verifiedBy": [],
    }


def _locked_add(args, project, config, mpath, title, out):
    """Everything between acquire and release: read, allocate, mutate, write,
    validate-from-disk, roll back on findings, journal, report."""
    try:
        raw_index = _mio.read_json(mpath)
        assembled = _mio.load_manifest(mpath)
    except Exception as exc:
        out("[audit-task] cannot read/assemble manifest: %s" % exc)
        return E_USAGE
    if not isinstance(assembled, dict) or not isinstance(raw_index, dict):
        out("[audit-task] manifest root is not an object")
        return E_USAGE

    vm = _panel_write._cores()[0]
    pre_findings, _pre_w = vm.validate(assembled)
    if pre_findings:
        # Refusing BEFORE the write is what tells "your add broke it" apart
        # from "it was broken when you arrived" -- the rollback below is
        # reserved for the first.
        out("[audit-task] the manifest is already invalid -- nothing "
            "written; fix these first:")
        for line in pre_findings:
            out("FINDING: " + line)
        return E_INVALID

    phase = _resolve_phase(assembled, args.phase, out)
    if isinstance(phase, int):
        return phase
    phase_id = phase.get("id")

    # F201: `add` reads `--gate-clear` now, so it owes the same refusal the other
    # two verbs give -- asked HERE, in their position: after the target is
    # resolved and before the first mutation.
    contradiction = _gate_contradiction(args)
    if contradiction:
        out(contradiction)
        return E_USAGE

    task_id = _allocate_id(assembled, phase_id)
    task = _build_task(task_id, title, args, phase)
    missing = [f for f in task["files"]
               if not os.path.exists(os.path.join(project, f))]

    phase.setdefault("tasks", []).append(task)
    fidx = assembled.setdefault("fileIndex", {})
    for fpath in task["files"]:
        entry = fidx.setdefault(fpath, [])
        if task_id not in entry:
            entry.append(task_id)
    # v0.37 A4, at THIS write site too: reused from _panel_write, scoped to
    # the target phase -- the one shard this add writes anyway.
    healed = _panel_write._heal_phase_status({"phases": [phase]})

    snap = _snapshot(_write_paths(project, mpath, raw_index, phase_id))
    try:
        written = _write_add(project, mpath, raw_index, assembled, phase_id,
                             bool(task["files"]))
    except Exception as exc:
        _restore(snap)
        out("[audit-task] write failed -- manifest restored: %s" % exc)
        return E_INVALID
    written_manifest = {}
    try:
        written_manifest = _mio.load_manifest(mpath)
        findings, warnings = vm.validate(written_manifest)
    except Exception as exc:
        findings, warnings = ["cannot re-read the written manifest: %s"
                              % exc], []
    if findings:
        _restore(snap)
        out("[audit-task] REFUSED: the add would leave the manifest invalid "
            "-- every written file rolled back, nothing kept:")
        for line in findings:
            out("FINDING: " + line)
        return E_INVALID

    jres = _journal_add(project, config, mpath, task_id, phase_id, title,
                        healed)
    waiting = _waiting_on(assembled, task)
    if args.as_json:
        result = {"ok": True, "id": task_id, "phase": phase_id,
                  "title": title, "task": task, "written": written,
                  "healed": healed, "warnings": warnings,
                  "filesNotOnDisk": missing,
                  "ready": not waiting, "waitingOn": waiting}
        result.update(jres)
        out(json.dumps(result, indent=2, sort_keys=True))
        return 0
    out("[audit-task] %s added to %s -- %s" % (task_id, phase_id, title))
    out("  tests.mode %s  model %s  risk %s  skills %s"
        % (task["tests"]["mode"], task["model"], task["risk"],
           json.dumps(task["skills"])))
    if task["tests"]["mode"] == "tdd" and not task["tests"]["add"]:
        # F254, said HERE as well as by the validator, and the reason is when. A
        # live run created two tdd tasks with no case named, and the operator only
        # noticed later — by which point the plan was written and the work was
        # being handed to an executor told to prove a red first with nothing to
        # prove it with. Validation catches it on the next `validate` call; this
        # catches it in the sentence that says the task was created.
        out("  NOTE: mode is 'tdd' and tests.add is empty - a red-first task "
            "naming no case cannot be shown to have gone red. Name it with "
            "`/audit:task scope %s --tests-add \"<case>\"`, or use --tests-mode "
            "regression / gate-only if no new test is owed" % (task_id,))
    if not task["tests"]["gate"]:
        # `scope`'s and `retarget`'s rule at the third write site: an empty gate is
        # a designed state and silence over it reads as breakage. It is printed off
        # the STATE here rather than off a change, because a creation has no prior
        # state to have moved from - and it fires whether the empty gate came from
        # `--gate-clear` or was inherited from a phase that has none, since a
        # reader of the report cares which state the task is in and not which
        # route reached it.
        out(_empty_task_gate_note(False))
    if task["files"]:
        out("  files: %d (fileIndex updated)" % len(task["files"]))
    for fpath in missing:
        out("  note: not on disk (a new file?): %s" % fpath)
    for row in healed:
        out("  healed: %s" % _panel_write._fmt_change(row))
    # Grouped, not one line per item: a plan whose phases carry no area tag put
    # nineteen identical advisories under every `add`, and what they buried was
    # the line about THIS task. `--json` keeps every warning - see `result` above,
    # which is a machine surface and does not read.
    for line in _wg.collapse(warnings, written_manifest):
        out("WARNING: " + line)
    if not jres.get("journaled") and jres.get("journaledWhy") == "failed":
        out("  journal: the audit trail did NOT take the task.add row")
    out("  written: %s" % ", ".join(written))
    for line in _readiness_lines(waiting, task_id):
        out(line)
    return 0


# --- cancel: finished, but not done ---------------------------------------------
# ca (F-P-4, v0.40): a phase or task can end without landing — the feature was
# dropped, the approach abandoned — and until this verb the only way to say so
# was to hand-edit the manifest. Three things then went unrecorded, every time:
# WHY (the reason lived in somebody's memory), WHEN (no stamp), and THAT IT
# HAPPENED AT ALL (no journal row). The verb writes all three through the same
# lock / write / validate-from-disk / roll-back path `add` uses.
_NOW_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _utc_now():
    import time
    return time.strftime(_NOW_FMT, time.gmtime())


def _find_target(assembled, tid):
    """(kind, node, phase) for a task or phase id, or (None, None, None).

    Phases are swept first and in full, because a phase can be cancelled before
    it has a single task and `_mio.iter_tasks` yields nothing for such a phase.
    The task sweep then takes its owning phase from the pair rather than tracking
    it in an enclosing loop -- that phase is the third return value, and the one
    `_locked_cancel` writes the shard for."""
    for ph in (assembled.get("phases") or []):
        if isinstance(ph, dict) and ph.get("id") == tid:
            return "phase", ph, ph
    for ph, t in _mio.iter_tasks(assembled):
        if t.get("id") == tid:
            return "task", t, ph
    return None, None, None


def _cancel_task(task, reason, now):
    """Mark one task cancelled. The reason goes where the report already reads
    from — outcome.descriptive — so it shows up in the detail row without a
    field invented for it, and `completedAt` is the moment it stopped being
    work rather than the moment it landed (it never landed)."""
    task["status"] = "cancelled"
    if not task.get("completedAt"):
        task["completedAt"] = now
    outcome = task.get("outcome")
    if not isinstance(outcome, dict):
        outcome = {}
    prefix = "Cancelled: %s" % reason
    prev = (outcome.get("descriptive") or "").strip()
    outcome["descriptive"] = ("%s (was: %s)" % (prefix, prev)) if prev else prefix
    task["outcome"] = outcome
    return task


def _locked_cancel(args, project, config, mpath, tid, reason, out):
    try:
        raw_index = _mio.read_json(mpath)
        assembled = _mio.load_manifest(mpath)
    except Exception as exc:
        out("[audit-task] cannot read/assemble manifest: %s" % exc)
        return E_USAGE
    vm = _panel_write._cores()[0]
    pre_findings, _w = vm.validate(assembled)
    if pre_findings:
        out("[audit-task] the manifest is already invalid -- nothing written; "
            "fix these first:")
        for line in pre_findings:
            out("FINDING: " + line)
        return E_INVALID

    kind, node, phase = _find_target(assembled, tid)
    if kind is None:
        out("[audit-task] no task or phase with id %r in %s" % (tid, mpath))
        return E_USAGE
    if node.get("status") in ("done", "cancelled"):
        # Terminal is terminal. Re-writing a finished item's status here would
        # rewrite history with no record of what it said before.
        out("[audit-task] %s is already %s -- terminal work is not re-decided "
            "by this verb (edit the manifest deliberately if it is wrong)"
            % (tid, node.get("status")))
        return E_USAGE

    now = _utc_now()
    # `{"id": ..., "was": <the status it held>}` per cascaded task, not a bare
    # id. The journal row spells the cascade as `changes`, whose entries are
    # id/field/from/to, and `was` is the `from` -- read BEFORE `_cancel_task`
    # overwrites it, because afterwards every one of them says `cancelled` and
    # the fact is gone from the manifest as well as from the row.
    cascade = []
    if kind == "task":
        _cancel_task(node, reason, now)
    else:
        node["status"] = "cancelled"
        prev = (node.get("summary") or "").strip()
        line = "Cancelled: %s" % reason
        node["summary"] = ("%s %s" % (prev, line)).strip() if prev else line
        # A claim on a finished phase is stale (the validator says so).
        node.pop("claim", None)
        # ...and the work still open inside it goes with it: a pending task
        # under a dropped phase is a task /audit:next would still offer.
        for t in (node.get("tasks") or []):
            if isinstance(t, dict) and t.get("status") not in ("done", "cancelled"):
                cascade.append({"id": t.get("id"), "was": t.get("status")})
                _cancel_task(t, "phase %s cancelled: %s" % (tid, reason), now)

    cascaded = _cascade_ids(cascade)
    phase_id = phase.get("id")
    snap = _snapshot(_write_paths(project, mpath, raw_index, phase_id))
    try:
        written = _write_add(project, mpath, raw_index, assembled, phase_id, False)
    except Exception as exc:
        _restore(snap)
        out("[audit-task] write failed -- manifest restored: %s" % exc)
        return E_INVALID
    written_manifest = {}
    try:
        written_manifest = _mio.load_manifest(mpath)
        findings, warnings = vm.validate(written_manifest)
    except Exception as exc:
        findings, warnings = ["cannot re-read the written manifest: %s" % exc], []
    if findings:
        _restore(snap)
        out("[audit-task] REFUSED: the cancel would leave the manifest invalid "
            "-- every written file rolled back, nothing kept:")
        for line in findings:
            out("FINDING: " + line)
        return E_INVALID

    jres = _journal_cancel(project, config, mpath, kind, tid, phase_id,
                           reason, cascade)
    if args.as_json:
        result = {"ok": True, "id": tid, "kind": kind, "phase": phase_id,
                  "reason": reason, "at": now, "cascaded": cascaded,
                  "written": written, "warnings": warnings}
        result.update(jres)
        out(json.dumps(result, indent=2, sort_keys=True))
        return 0
    out("[audit-task] %s %s cancelled -- %s" % (kind, tid, reason))
    if cascaded:
        out("  also cancelled inside it: %s" % ", ".join(cascaded))
    for line in _wg.collapse(warnings, written_manifest):
        out("WARNING: " + line)
    if not jres.get("journaled") and jres.get("journaledWhy") == "failed":
        out("  journal: the audit trail did NOT take the %s.cancel row" % kind)
    out("  written: %s" % ", ".join(written))
    return 0


def _cascade_ids(cascade):
    """The ids out of a cascade, in order, skipping an entry that has none.

    Spelled once because the summary sentence, the human line, the `--json`
    block and the journal row all want the same list and had it filtered
    inline in each place."""
    return [c["id"] for c in cascade if c.get("id")]


def _journal_cancel(project, config, mpath, kind, tid, phase_id, reason,
                    cascade):
    """The `task.cancel` / `phase.cancel` row: why the work stopped, and what
    stopped with it.

    THE REASON RIDES BOTH the summary and the details -- a trail that records the
    state change and not the why answers the wrong question a month later -- and
    that half is a decision recorded in `_journal_io.DETAILS_KEYS` beside the key
    rather than something this writer chose.

    THE CASCADE RIDES `changes`, AN EXISTING KEY RATHER THAN A NEW ONE. A phase
    cancel closes every task still open inside it, and those ids used to be
    handed over as `details.cascaded`, which is not on the allow-list: written,
    dropped in silence, and believed by everything reading the document instead
    of the row. Both repairs were available and only one of them adds vocabulary.
    A cascaded task is a FIELD OF THE PLAN THAT MOVED -- `status`, from what it
    held to `cancelled` -- which is exactly what a `changes` entry says, so the
    allow-list already carries a bounded shape for it: the list capped at
    `MAX_CHANGES` with `truncated` set when the cut happens, and every value
    clipped to `MAX_VALUE_CHARS`. `repair-commits.py` made the same move for the
    same reason ("`changes`, not an invented key"), and a second capped-list
    mechanism beside that one would be a second expression of one rule that
    every reader after it has to learn separately. The row also carries nothing
    new: the summary already names the same ids verbatim in the same committed
    file, and a task id names neither a machine nor a person.

    `cancelledId` IS NOT WRITTEN, which is the same argument from the other end.
    It was handed over for a phase cancel and dropped, and it was redundant the
    whole time -- `_find_target` returns a phase as its own owning phase, so
    `phase_id` IS the cancelled id there and the row already said it. Putting a
    key on the allow-list to carry a string another key already carries is a
    committed row growing for nothing, which is the direction CWE-532 lies in.
    """
    summary = "%s cancelled: %s" % (tid, reason)
    ids = _cascade_ids(cascade)
    if ids:
        summary += " (also %s)" % ", ".join(ids)
    details = {"phaseId": phase_id, "reason": reason}
    if kind == "task":
        details["taskId"] = tid
    if cascade:
        details["changes"] = [{"id": c["id"], "field": "status",
                               "from": c["was"], "to": "cancelled"}
                              for c in cascade if c.get("id")]
    return _journal_row(project, config, mpath, "%s.cancel" % kind, summary,
                        details)


# --- add-phase: one more phase in a plan that already exists ---------------------
# F58. Everything that WROTE a phase before this verb wrote a whole plan or moved
# one that had already been written somewhere else, so "I have a live plan and a
# new body of work" was the one shape with no command behind it -- and it is the
# shape every plan reaches once its first round is finished.


def _allocate_phase_id(assembled):
    """The lowest free `P<n>`, counting live ids AND every parked reservation.

    `_proposals.next_phase_id` over `live_ids | parked_ids` -- the SAME pair
    `/audit:propose materialize` allocates against. A second expression of "which
    phase ids are taken" would eventually hand this verb an id materialization
    had already promised to a payload."""
    taken = _proposals.live_ids(assembled) | _proposals.parked_ids(assembled)
    return _proposals.next_phase_id(taken)


def _phase_id_refusal(assembled, raw_index, pid):
    """Why `pid` cannot be minted, or None when it can. Nothing is written yet.

    The shard-file check is not a character class: two ids that differ only in
    something `_manifest_io` sanitises out of a shard NAME would land on one
    file, and the second write would silently overwrite the first phase's body.
    Comparing the path this phase WOULD take against the paths the index already
    points at asks `_manifest_io` what it names a shard instead of restating the
    rule here, so the two cannot drift apart."""
    if not pid or not pid.strip():
        return "[audit-task] --id cannot be blank"
    for ph in (assembled.get("phases") or []):
        if isinstance(ph, dict) and ph.get("id") == pid:
            # The alternative offered depends on the phase's state, because
            # `add --phase` refuses a done one: naming a path the next command
            # would refuse is worse than naming none.
            if ph.get("status") in ("done", "cancelled"):
                nxt = "pick another --id (that phase is finished history)"
            else:
                nxt = ("pick another --id, or add a task to it with "
                       "/audit:task add --phase %s" % (pid,))
            return ("[audit-task] phase %s already exists (%s) -- %s"
                    % (pid, ph.get("status"), nxt))
    for _ph, tsk in _mio.iter_tasks(assembled):
        if tsk.get("id") == pid:
            return ("[audit-task] %s is already a TASK id -- a phase sharing it "
                    "would make every reference ambiguous" % (pid,))
    reserving = _reserving_proposal(assembled, pid)
    if reserving:
        return _reserved_refusal(pid, reserving)
    if _mio.is_sharded(raw_index):
        rel = _new_stub_and_body({"id": pid, "title": ""},
                                 _shard_rel_dir(raw_index))[0].get("shard")
        for stub in (raw_index.get("phases") or []):
            if isinstance(stub, dict) and stub.get("shard") == rel:
                return ("[audit-task] %s would be stored as %s, which phase %s "
                        "already occupies -- two ids the shard filename cannot "
                        "tell apart would overwrite one another"
                        % (pid, rel, stub.get("id")))
    return None


def _phase_gate(args, assembled):
    """`(testGate, basis)` -- the gate entries and the sentence that says where
    they came from. The basis is returned rather than printed here because an
    EMPTY gate is the answer that needs one: a phase nothing can prove done is
    a phase sign-off signs on review alone, and the reader has to be told which
    of the two reasons produced it."""
    # F207. `--gate-clear` reaches the EMPTY gate here too, and this was the third
    # verb of the same shape after F196 (`scope`) and F201 (`add`): the flag is
    # defined on the global parser, so argparse accepted it and this resolver
    # never looked -- the new phase inherited `meta.buildCommands` while the caller
    # was told the call succeeded. Measured: `--gate-clear` alone wrote `["lint"]`.
    #
    # Its basis is the FLAG rather than a sentence about the manifest, because that
    # is what makes it a different answer from the two empty cases below: those say
    # nothing here CAN prove the phase done, this says the caller decided nothing
    # should.
    # F207. `--gate-clear` was advertised on this verb, accepted by the shared
    # parser and then never read here, so it silently left the gate at its
    # default -- the third verb of that exact shape after `scope` (F196) and
    # `add` (F201). Spelled `args.gate_clear` rather than `getattr(args, ...)`:
    # the flag is `store_true` on the shared parser, so the attribute always
    # exists and the defensive form only hides a real `AttributeError` if the
    # parser ever stops declaring it.
    if args.gate_clear:
        return [], "from --gate-clear"
    if args.gate:
        return list(args.gate), "from --gate"
    meta = assembled.get("meta")
    build = (meta or {}).get("buildCommands") if isinstance(meta, dict) else None
    if isinstance(build, dict):
        keys = [k for k in build.keys() if isinstance(k, str) and k.strip()]
        if keys:
            return keys, "from meta.buildCommands"
        return [], "meta.buildCommands is empty"
    return [], "the manifest declares no meta.buildCommands"


def _build_phase(pid, title, args, gate):
    """The new phase, fully template-initialized -- every field from the
    conventions' New phase template, exactly once, in _PHASE_TEMPLATE_KEYS
    order.

    `gate` arrives as an ARGUMENT rather than being derived here, because the
    caller has to print the BASIS for it and deriving it twice is two chances
    for the value written and the value explained to stop being the same one."""
    phase = {
        "id": pid,
        "title": title,
        "status": "pending",
        "description": args.description or "",
        "desiredOutcome": (args.outcome or "").strip(),
        "testGate": gate,
        "blockedBy": _split_csv(args.blocked_by),
        "baseRef": None,
        "branch": None,
        "mergedAt": None,
        "review": {"tool": None, "model": "sonnet", "status": "pending",
                   "findings": []},
        "summary": None,
        "tasks": [],
    }
    areas = _split_csv(args.area)
    if areas:
        # A LIST only when there is more than one. The conventions spell a single
        # tag as a bare string and `_areas` reads both, so writing a one-element
        # list would make this command's phases the odd ones out in every diff
        # and every hand comparison against a phase /audit:init wrote.
        phase["area"] = areas[0] if len(areas) == 1 else areas
    if args.review_skill:
        phase["reviewSkill"] = args.review_skill
    return phase


def _locked_phase_add(args, project, config, mpath, title, out):
    """Everything between acquire and release for `add-phase`: read, allocate,
    append, write, validate-from-disk, roll back on findings, journal, report.

    `_locked_add`'s shape deliberately, down to which refusal comes before which
    write -- the two verbs differ in WHAT they append and in nothing else, and a
    second discipline for the second writer is how one of them ends up leaving an
    invalid manifest behind."""
    try:
        raw_index = _mio.read_json(mpath)
        assembled = _mio.load_manifest(mpath)
    except Exception as exc:
        out("[audit-task] cannot read/assemble manifest: %s" % exc)
        return E_USAGE
    if not isinstance(assembled, dict) or not isinstance(raw_index, dict):
        out("[audit-task] manifest root is not an object")
        return E_USAGE

    vm = _panel_write._cores()[0]
    pre_findings, _pre_w = vm.validate(assembled)
    if pre_findings:
        out("[audit-task] the manifest is already invalid -- nothing "
            "written; fix these first:")
        for line in pre_findings:
            out("FINDING: " + line)
        return E_INVALID

    # F207, and the reason this arrived only now: while `--gate-clear` was inert
    # here, refusing the pair would have reported a conflict between a flag that
    # works and a flag that does nothing -- theatre. The clear is live above, so
    # the pair is a real contradiction and gets the same sentence, in the same
    # position, as `add`, `scope` and `retarget`.
    contradiction = _gate_contradiction(args)
    if contradiction:
        out(contradiction)
        return E_USAGE

    # ABSENT and BLANK are different answers. `--id ""` falling through to the
    # allocator would write a phase under an id nobody asked for while reporting
    # success, which is the no-op-on-unexpected-input shape rather than a
    # convenience: `None` means the flag was not passed, anything else is what
    # the human typed and is graded as such.
    pid = (_allocate_phase_id(assembled) if args.phase_id is None
           else args.phase_id.strip())
    refusal = _phase_id_refusal(assembled, raw_index, pid)
    if refusal:
        out(refusal)
        return E_USAGE

    gate, gate_basis = _phase_gate(args, assembled)
    phase = _build_phase(pid, title, args, gate)
    assembled.setdefault("phases", []).append(phase)

    snap = _snapshot(_write_paths(project, mpath, raw_index, pid,
                                  new_phase=phase))
    try:
        written = _write_add(project, mpath, raw_index, assembled, pid, False)
    except Exception as exc:
        _restore(snap)
        out("[audit-task] write failed -- manifest restored: %s" % exc)
        return E_INVALID
    written_manifest = {}
    try:
        written_manifest = _mio.load_manifest(mpath)
        findings, warnings = vm.validate(written_manifest)
    except Exception as exc:
        findings, warnings = ["cannot re-read the written manifest: %s"
                              % exc], []
    if findings:
        _restore(snap)
        out("[audit-task] REFUSED: the phase would leave the manifest invalid "
            "-- every written file rolled back, nothing kept:")
        for line in findings:
            out("FINDING: " + line)
        return E_INVALID

    jres = _journal_phase_add(project, config, mpath, pid, title,
                              phase["desiredOutcome"])
    waiting = _waiting_on(assembled, phase)
    if args.as_json:
        result = {"ok": True, "id": pid, "title": title, "phase": phase,
                  "written": written, "warnings": warnings,
                  "testGateBasis": gate_basis,
                  "ready": not waiting, "waitingOn": waiting}
        result.update(jres)
        out(json.dumps(result, indent=2, sort_keys=True))
        return 0
    out("[audit-task] phase %s added -- %s" % (pid, title))
    out("  outcome: %s" % phase["desiredOutcome"])
    # The basis rides every gate line, empty or not: a phase with no gate is
    # signed off on review alone, and "gate: none" without the reason leaves the
    # reader unable to tell a deliberate choice from a manifest that declares no
    # build commands.
    out("  gate: %s (%s)" % (", ".join(gate) if gate else "none", gate_basis))
    if "area" in phase:
        out("  area: %s" % json.dumps(phase["area"]))
    if phase.get("reviewSkill"):
        out("  reviewSkill: %s" % phase["reviewSkill"])
    for line in _wg.collapse(warnings, written_manifest):
        out("WARNING: " + line)
    if not jres.get("journaled") and jres.get("journaledWhy") == "failed":
        out("  journal: the audit trail did NOT take the phase.add row")
    out("  written: %s" % ", ".join(written))
    if waiting:
        out("  waiting on: %s" % ", ".join(waiting))
    out("  next: /audit:task add \"<the first task>\" --phase %s" % pid)
    return 0


# --- the doors ------------------------------------------------------------------
def _under_lock(args, project, out, body):
    """Config, manifest path, the index lock, `body`, release.

    ONE copy for three verbs. The lock comes BEFORE the read: ids are allocated
    under it, so the read-modify-write is serialized (manifest-conventions ->
    ID allocation). What each verb checks before this point differs and stays in
    its own door; what happens after it does not differ at all, and three copies
    of that would be three answers to "where is the manifest"."""
    config = _panel_write.read_config(project)
    mpath = (os.path.abspath(args.manifest) if args.manifest
             else _panel_write._manifest_path(project, config))
    if not os.path.isfile(mpath):
        out("[audit-task] manifest not found: %s -- run /audit:init first"
            % mpath)
        return E_USAGE
    lock = _acquire_lock(project, config, mpath, args.takeover, out)
    if isinstance(lock, int):
        return lock
    try:
        return body(config, mpath)
    finally:
        _release_lock(lock)


def cmd_phase_add(args, out):
    project = _resolve_project(args)
    if not os.path.isdir(project):
        out("[audit-task] not a directory: %s" % project)
        return E_USAGE
    title = (args.title or "").strip()
    if not title:
        out("[audit-task] add-phase needs a non-empty title")
        return E_USAGE
    if not (args.outcome or "").strip():
        # `cancel --reason`'s rule, one noun up. A phase whose success cannot be
        # stated in a line is a phase sign-off cannot address, and the conventions
        # put `desiredOutcome` in the new-phase template for that reason -- so the
        # verb refuses rather than writing a phase nobody can sign off.
        out("[audit-task] add-phase needs --outcome \"<what success looks "
            "like>\" -- /audit:status shows it, task subagents receive it and "
            "sign-off must address it (conventions -> New phase template)")
        return E_USAGE
    return _under_lock(args, project, out,
                       lambda config, mpath: _locked_phase_add(
                           args, project, config, mpath, title, out))


def _locked_scope(args, project, config, mpath, tid, out):
    """Give an unscoped task its `files` (and optionally its tests), under lock.

    F189. `pull sprint` imports tasks with `files: []` and a description telling
    the reader to "scope files/tests before running" -- and no verb could. `add`
    creates, `cancel` closes, `move` relocates, `priority` ranks a phase; none of
    them edits a task, and the panel's composition card reaches `skills` and
    `model` but not `files`. So the plugin's own instruction could be obeyed only
    by the hand edit `commands/task.md` forbids for adds, for the reason that
    applies here too.

    THE COST WAS NOT TIDINESS. `files` is what `fileIndex` is built from and
    `fileIndex` is what the plan gate matches an edit against, so an imported
    phase ran with its central guard inert -- not failing, because it had nothing
    to match. Measured live before this existed.

    SETTLED WORK ONLY IS REFUSED OUTRIGHT (F271). A `done` or `cancelled` task
    has a scope its commit was graded against and its sign-off accepted, and
    nothing this verb could write to it would describe the run that happened.
    Everything short of that -- `pending`, `in_progress`, `blocked`, with or
    without attempts on it -- is reachable, but a task that has already STARTED
    will take only a WIDENING: `files` and `tests.add` may gain entries, never
    lose them, and no other field may move at all.

    THE OLD RULE WAS NOT WRONG, IT WAS TOO WIDE, and its own reason is what
    narrows it. F190 refused a started task because an `outcome` describes work
    judged under the OLD scope, so rescoping would make that record describe
    something else. A widening cannot: `_invariants.commit_scope` grades a
    recorded commit against the task's CURRENT `files`, so growing that list can
    only turn a breach into a pass and never a pass into a breach, and the plan
    gate reads it forward, so growing it only ALLOWS an edit it was refusing.
    Append-only is therefore the exact operation that leaves every past
    judgement standing -- see `_narrowings` for why no other field has a safe
    direction.

    AND THE CASE IT EXISTS FOR IS THE ONE IT USED TO REFUSE.
    `reference/orchestrator.md` prescribes `/audit:task scope` for the moment the
    plan gate refuses a file a running task genuinely needs, and a task in that
    moment is `in_progress` with an attempt on it -- the two states the guard
    excluded. Measured live: hit three times in one phase, and the only escape
    each time was hand-editing the shard and the index under the lock, which is
    the operation this verb exists to replace.

    THE EMPTY GATE NEEDS ITS OWN FLAG HERE TOO (F196), for a reason that is NOT
    `retarget`'s. That verb appends to `testGate`, so the append itself left the
    empty gate unspellable; this one REPLACES `tests.gate` outright. The gap is
    in the values: no `--gate` VALUE says "none" - `--gate ""` writes a gate
    holding an empty command, which is a gate that cannot run rather than the
    absence of one. Measured live: a phase retargeted to `testGate: []` because
    nothing in this repo could grade its remaining work left its pending tasks
    holding the `["lint"]` they had inherited at creation, and the only routes to
    the state the phase had just reached were a rescope mid-run or the hand edit
    `commands/task.md` forbids.

    RISK, BLOCKEDBY AND DEPENDSON REACH IT TOO (F199), and they were the three
    fields of the new-task template that NOTHING could correct: `add` sets them,
    the panel's composition card reaches `model` and `skills` instead, and this
    verb reached the other five. Measured live: a task filed
    `--depends-on P0.3,P0.4` against tasks parked behind a missing environment,
    where shipping the describable half meant removing one id -- and the only
    route was `cancel` plus a fresh `add`, losing the id, the journal continuity
    and the description somebody wrote. `risk` is the sharpest of the three: it
    feeds the executor's model floor and whether a commit needs confirmation, it
    is a judgement made BEFORE the work was looked at, and it is the one field
    here where being wrong has a consequence at run time.

    NO `--depends-on-clear` FAMILY, and the asymmetry with `--gate-clear` is the
    reason rather than an oversight. `--gate` takes COMMANDS, where `""` is a
    legal-if-useless value and so cannot double as "none"; `--blocked-by` and
    `--depends-on` take a comma list of IDS, where no id is the empty string, so
    `--blocked-by ""` says exactly one thing. `retarget --area ""` already draws
    that line for a CSV field and reads it with `is not None`, which is what the
    guard above does. `risk` needs no clear either: the template always carries
    one and the schema's `null` is for historical tasks, not for a live task
    somebody just re-judged.

    IT DOES NOT RE-DERIVE `model`. `_build_task` floors the model off risk at
    creation, so a rescope to `high` leaves a task at sonnet -- which the report
    SAYS, because `model` belongs to `/audit:panel` and `add --model`, and a
    second writer of it here would journal a change the caller did not ask for
    while silently overruling one they had.
    """
    try:
        raw_index = _mio.read_json(mpath)
        assembled = _mio.load_manifest(mpath)
    except Exception as exc:
        out("[audit-task] cannot read/assemble manifest: %s" % exc)
        return E_USAGE
    vm = _panel_write._cores()[0]
    pre_findings, _w = vm.validate(assembled)
    if pre_findings:
        out("[audit-task] the manifest is already invalid -- nothing written; "
            "fix these first:")
        for line in pre_findings:
            out("FINDING: " + line)
        return E_INVALID

    kind, node, phase = _find_target(assembled, tid)
    if kind != "task":
        out("[audit-task] scope takes a TASK id; %r is %s"
            % (tid, "not in this manifest" if kind is None else "a " + kind))
        return E_USAGE
    # F283. `cancelled` IS SETTLED; `done` IS NOT, AND THE DIFFERENCE WAS
    # MEASURED RATHER THAN REASONED. This refusal used to cover `_mio.TERMINAL`
    # whole, which made the plugin contradict itself out loud: at sign-off
    # `_invariants.manifest_revalidated` prints, as its own repair,
    #
    #   "by sign-off it has to be settled - run `/audit:task scope <id>
    #    --files ...` to re-derive the index"
    #
    # and every id it can name is `done` by then, so the command it hands you
    # exits 2. A remedy the product prescribes and refuses in the same breath is
    # worse than no remedy: a live run spent 172,417 tokens on three fix-run
    # subagents before finding that out.
    #
    # WHAT A WIDENING ON A DONE TASK ACTUALLY MOVES, checked in the code rather
    # than argued: `commit_scope` reads `task.files` LIVE and reports staged
    # paths outside it, so growing the list can only move a path INTO `allowed` -
    # it relaxes, never tightens. And the `fileIndex` re-derivation this write
    # performs is exactly the settlement `manifest_revalidated` is asking for.
    # The honest objection that remains is about the RECORD, not about any
    # verdict: the task's `outcome` describes a run judged under the narrower
    # list. So the row says which attempt it grew during and the report says the
    # widening settles the index rather than describing new work.
    #
    # `cancelled` stays refused. Nothing settles an index for work that will not
    # be done, and a cancelled task growing a scope is a record nobody can read.
    if node.get("status") == "cancelled":
        out("[audit-task] %s is cancelled -- its scope cannot grow: nothing "
            "will be committed against it, so there is no pairing here to "
            "settle and no run for a wider list to describe. Add the work as a "
            "new task." % (tid,))
        return E_USAGE
    # F190. STATUS IS NOT THE WHOLE TEST, and it is not the whole test in the
    # other direction either: a task that ran, failed and was put back to
    # `pending` still carries `attempts` and an `outcome` describing work judged
    # under its OLD scope, while an `in_progress` task with no attempt recorded
    # is equally mid-flight. `_started` reads both signals; what it gates is the
    # SHAPE of the change and no longer the call.
    started = _started(node)

    contradiction = _gate_contradiction(args)
    if contradiction:
        out(contradiction)
        return E_USAGE
    files = _split_csv(args.files)
    # `is None` for the two ID-LIST flags and not truthiness, because an EMPTY
    # value of either is an instruction rather than an absence: `--depends-on ""`
    # is how the field is emptied, which is `retarget --area ""`'s spelling and
    # the reason F199 needed no `--depends-on-clear` twin.
    if not files and args.tests_mode is None and not args.tests_add \
            and not args.gate and not args.gate_clear and not args.description \
            and args.risk is None and args.blocked_by is None \
            and args.depends_on is None:
        out("[audit-task] scope needs --files (and may take --tests-mode / "
            "--tests-add / --gate / --gate-clear / --description / --risk / "
            "--blocked-by / --depends-on) -- a scope call that changes nothing "
            "is a lock taken for no reason")
        return E_USAGE

    was_files = list(node.get("files") or [])
    # F197. READ BEFORE ANY WRITE, and that ordering IS the repair rather than a
    # tidier spelling: the `tests.add` and `tests.gate` branches below write the
    # field first and append the journal row second, so reading it inside the
    # branch would read back the value just written and record `from == to`. Both
    # rows used to carry a literal `None`, which made a verifying, genuine row
    # attest a prior state the task never had - `was_files` and `was_desc` were
    # already right, which is how the two got missed.
    prior_tests = node.get("tests")
    prior_tests = prior_tests if isinstance(prior_tests, dict) else {}
    was_gate = list(prior_tests.get("gate") or [])
    was_add = list(prior_tests.get("add") or [])
    changes = []
    if files:
        # `files` ⊇ `tests.add` IS AN INVARIANT, not a courtesy at creation (F258).
        # `--files` REPLACES the list, so without this a later re-scope silently
        # released the very case file the task is still declared to create, and the
        # next commit tripped commit-scope for a scope the operator had just fixed.
        # The task's CURRENT `add` is used, because `--tests-add` in the same call
        # is applied below and unions again there.
        files = _union_paths(files, was_add)
        # F202. F197's class one field over, and not named by that entry: the row
        # went in under a bare `if files:`, so re-scoping to the list the task
        # already held printed and journaled `files: [...] -> [...]`. The chain
        # verifies and the row attests a change that never happened, which is what
        # a reader counting "who changed this task's scope, and when" counts. The
        # three sibling fields below already compared; this is that comparison.
        if was_files != files:
            changes.append({"id": tid, "field": "files",
                            "from": was_files, "to": files})
        node["files"] = files
    # F208. THE `tests` OBJECT IS MATERIALIZED ONLY IF SOMETHING WRITES INTO IT.
    # It used to be created unconditionally, so `scope --files` alone left
    # `tests: {}` behind -- and an ABSENT `tests` is legal while one present
    # without a `mode` is not (`_manifest_phases.py`). The rollback held, so no
    # manifest was ever corrupted; what broke was the verb, on exactly the task
    # it was written for. Measured live: a `pull sprint` import whose own
    # description says "scope files/tests before running" carries no `tests`
    # key, and every `scope` against it was refused with
    # `tests.mode None not in [...]` -- a message about the manifest for a
    # defect in the writer, which is the half that makes it hard to read.
    tests_writes = (args.tests_mode is not None or bool(args.tests_add)
                    or bool(args.gate) or args.gate_clear)
    tests = node.get("tests")
    tests = dict(tests) if isinstance(tests, dict) else None
    if tests_writes and tests is None and args.tests_mode is None:
        # Refused BEFORE the write and named as the flag it is, because the two
        # alternatives are worse: writing produces the same invalid object one
        # step later, and defaulting the mode the way `_build_task` does would
        # have this verb invent a grading nobody chose -- on a task somebody is
        # scoping precisely because its testing was never decided.
        out("[audit-task] %s has no `tests` object, so --tests-add / --gate / "
            "--gate-clear cannot be applied on their own: the result would be a "
            "`tests` without a `mode`, which the schema refuses. Pass "
            "--tests-mode tdd|regression|gate-only in the same call to say how "
            "this task is graded." % (tid,))
        return E_USAGE
    if tests is None:
        tests = {}
    if args.tests_mode is not None:
        if tests.get("mode") != args.tests_mode:
            changes.append({"id": tid, "field": "tests.mode",
                            "from": tests.get("mode"), "to": args.tests_mode})
        tests["mode"] = args.tests_mode
        # The same derivation `_build_task` makes, so the two writers cannot
        # disagree about what `expectRedFirst` means.
        tests["expectRedFirst"] = args.tests_mode == "tdd"
    if args.tests_add:
        now_add = list(args.tests_add)
        if was_add != now_add:
            changes.append({"id": tid, "field": "tests.add",
                            "from": was_add, "to": now_add})
        tests["add"] = now_add
        # ...and into `files` here too (F258), for `_build_task`'s reason: a case
        # named by `tests.add` is a file this task creates, and a scope that omits
        # it fails the task's own commit. `scope` is the verb an operator reaches
        # for when reality differed from the plan, so it is the LAST place that
        # should hand back a scope it knows to be short.
        was_files = list(node.get("files") or [])
        now_files = _union_paths(was_files, now_add)
        if was_files != now_files:
            changes.append({"id": tid, "field": "files",
                            "from": was_files, "to": now_files})
            node["files"] = now_files
    if args.gate or args.gate_clear:
        now_gate = [] if args.gate_clear else list(args.gate)
        if was_gate != now_gate:
            changes.append({"id": tid, "field": "tests.gate",
                            "from": was_gate, "to": now_gate})
        tests["gate"] = now_gate
    # Assigned back exactly once, and only when a branch above ran: `tests` is a
    # COPY, so the branches cannot leave a half-object on the node by accident.
    if tests_writes:
        node["tests"] = tests
    if args.description:
        was_desc = node.get("description") or ""
        if was_desc != args.description:
            changes.append({"id": tid, "field": "description",
                            "from": was_desc, "to": args.description})
        node["description"] = args.description
    if args.risk is not None:
        was_risk = node.get("risk")
        if was_risk != args.risk:
            changes.append({"id": tid, "field": "risk",
                            "from": was_risk, "to": args.risk})
        node["risk"] = args.risk
    # ONE LOOP FOR THE TWO REF LISTS. They are the same field twice over -- a
    # comma list of ids, replaced outright, empty spelled by an empty value -- and
    # two blocks of it is how the pair would come to disagree about whether an
    # empty value means "empty it" or "leave it".
    for raw_refs, field in ((args.blocked_by, "blockedBy"),
                            (args.depends_on, "dependsOn")):
        if raw_refs is None:
            continue
        was_refs = list(node.get(field) or [])
        now_refs = _split_csv(raw_refs)
        if was_refs != now_refs:
            changes.append({"id": tid, "field": field,
                            "from": was_refs, "to": now_refs})
        node[field] = now_refs
    if not changes:
        out("[audit-task] %s already reads that way -- nothing written" % (tid,))
        return 0

    # F271's guard, and it is placed HERE for two reasons that both come from
    # what it grades. It asks about the CHANGE and not about the flags, so it
    # needs `changes` -- which is also what makes `--risk med` on a task already
    # at `med` a no-op above rather than a refusal, since a field that does not
    # move is not a field being changed. And it is AFTER the mutations because
    # `changes` is their record; nothing has been written yet (`_snapshot` and
    # `_write_add` are below), so returning here leaves an in-memory `assembled`
    # that is discarded with the frame and a manifest nobody touched.
    if started:
        blockers = _narrowings(changes)
        if blockers:
            out(_rescope_refusal(tid, node, blockers))
            return E_USAGE

    # THE WHOLE POINT, and it is a re-derivation rather than an append: the task
    # is losing files as well as gaining them, and an index that only ever grew
    # would keep matching edits to a scope the task no longer claims.
    fidx = assembled.setdefault("fileIndex", {})
    for fpath in was_files:
        entry = fidx.get(fpath)
        if isinstance(entry, list) and tid in entry:
            entry.remove(tid)
            if not entry:
                del fidx[fpath]
    for fpath in (node.get("files") or []):
        entry = fidx.setdefault(fpath, [])
        if tid not in entry:
            entry.append(tid)

    # F197's adjacent half. The report line below used to print unconditionally,
    # including when `--files` was absent and the re-derivation was a no-op over
    # an unchanged list - read live it said work had been dropped when none had.
    # These two ARE the derivation's outcome: `fidx` gains a row for every path
    # in `claimed` and loses this task from every path in `released`, so empty
    # both ways is an index the loop above rewrote byte for byte.
    released = [f for f in was_files if f not in (node.get("files") or [])]
    claimed = [f for f in (node.get("files") or []) if f not in was_files]

    missing = [f for f in (node.get("files") or [])
               if not os.path.exists(os.path.join(project, f))]
    phase_id = phase.get("id")
    snap = _snapshot(_write_paths(project, mpath, raw_index, phase_id))
    try:
        written = _write_add(project, mpath, raw_index, assembled, phase_id, True)
    except Exception as exc:
        _restore(snap)
        out("[audit-task] write failed -- manifest restored: %s" % exc)
        return E_INVALID
    try:
        findings, warnings = vm.validate(_mio.load_manifest(mpath))
    except Exception as exc:
        findings, warnings = ["cannot re-read the written manifest: %s" % exc], []
    if findings:
        _restore(snap)
        out("[audit-task] REFUSED: the scope would leave the manifest invalid "
            "-- every written file rolled back, nothing kept:")
        for line in findings:
            out("FINDING: " + line)
        return E_INVALID

    jres = _journal_scope(project, config, mpath, tid, phase_id, changes, node)
    # F199's payoff, and the reason it is computed unconditionally: the live case
    # was a task parked behind a `dependsOn` id, rescoped precisely so it could
    # run. "Can it run now" is the question that call was asking.
    waiting = _waiting_on(assembled, node)
    if args.as_json:
        result = {"ok": True, "id": tid, "phase": phase_id,
                  "changes": changes, "written": written,
                  "filesNotOnDisk": missing, "warnings": warnings,
                  # The two facts the human report spends a paragraph on, as
                  # data: WHICH call this was, and the attempt it landed under.
                  # `attempt` is null when the plan records none, never 0 -- a
                  # machine surface must not be the one place the three answers
                  # of `recorded_attempt` collapse into two.
                  "widened": started,
                  "attempt": _mio.recorded_attempt(node),
                  "ready": not waiting, "waitingOn": waiting}
        result.update(jres)
        out(json.dumps(result, indent=2, sort_keys=True))
        return 0
    out("[audit-task] %s scoped in %s" % (tid, phase_id))
    for row in changes:
        out("  %s: %s -> %s" % (row["field"], json.dumps(row["from"]),
                                json.dumps(row["to"])))
    if started:
        # THE BASIS FOR AN ACCEPTANCE THAT USED TO BE A REFUSAL (F271). A reader
        # of this transcript has to be able to tell a scope written BEFORE the
        # work from one written DURING it, because the two say different things
        # about every record already carrying this task's id -- and the report
        # is where an operator meets that, not the journal. It names what was
        # gained and when, and then why the verb was willing.
        gained = []
        for row in changes:
            for item in (row["to"] or []):
                if item not in (row["from"] or []):
                    gained.append("%s +%s" % (row["field"], item))
        out("  WIDENED %s: %s" % (_attempt_phrase(node), ", ".join(gained)))
        # WHY IT WAS TAKEN, and the reason differs by status because what the
        # widening BUYS differs. Mid-flight it unblocks the plan gate, which is
        # refusing an edit right now. On a finished task nothing is being edited:
        # what it buys is the `fileIndex` settlement `manifest_revalidated` asks
        # for at sign-off, and saying "the plan gate now matches" there would name
        # a benefit nobody is collecting.
        if node.get("status") == "done":
            out("  append-only, which is why a task that is already done will "
                "take it: nothing was released, so no commit graded against "
                "this task's `files` can turn into a breach, and the `fileIndex` "
                "re-derived below is the settlement sign-off asks for. This does "
                "NOT record new work - the task's outcome still describes the "
                "run that happened. Follow-up work is a new task.")
        else:
            out("  append-only, which is why a task that is not pending will "
                "take it: nothing was released, so no commit already graded "
                "against this task's `files` can turn into a breach, and the "
                "plan gate now matches the paths it was refusing")
    if (node.get("tests") or {}).get("gate") == [] \
            and any(row["field"] == "tests.gate" for row in changes):
        # `retarget`'s empty-gate line, and the MEANING differs so the sentence
        # does: `reference/orchestrator.md` has the executor run `task.tests.gate`
        # and phase sign-off run `phase.testGate`, so an emptied task gate means
        # this task runs none of its own and the phase's is what still grades it.
        # Silence would leave a designed state to read as breakage.
        out(_empty_task_gate_note(True))
    if released:
        out("  fileIndex re-derived -- released by this task: %s"
            % ", ".join(released))
    elif claimed:
        out("  fileIndex re-derived -- now claimed by this task: %s"
            % ", ".join(claimed))
    for fpath in missing:
        out("  note: not on disk (a new file?): %s" % fpath)
    risk_rows = [row for row in changes if row["field"] == "risk"]
    if risk_rows and node.get("model") != _model_floor(risk_rows[0]["to"]):
        # THE BASIS FOR A NON-CHANGE. `add` derives the model from risk when the
        # caller names none, so a rescope that moves risk and leaves the model
        # where it is diverges from a documented rule -- and silence there would
        # let an operator who raised risk to high believe the executor had been
        # escalated with it. Printed only when the two actually disagree: a
        # rescope whose risk implies the model already on the task has nothing to
        # explain.
        out("  the model stays %s -- `add` derives it from risk at creation "
            "(risk %s would derive %s) and scope does not, because `model` is "
            "the field /audit:panel and `add --model` own"
            % (node.get("model"), risk_rows[0]["to"],
               _model_floor(risk_rows[0]["to"])))
    if any(row["field"] in ("blockedBy", "dependsOn") for row in changes):
        # Only when a REF field moved. Readiness is what those two fields decide,
        # and printing it after a call that touched neither would be a claim about
        # something this call did not look at.
        for line in _readiness_lines(waiting, tid):
            out(line)
    for line in _wg.collapse(warnings, _mio.load_manifest(mpath)):
        out("WARNING: " + line)
    if not jres.get("journaled"):
        out("  note: not journaled (%s)" % jres.get("journaledWhy"))
    return 0


def _locked_retarget(args, project, config, mpath, pid, out):
    """Correct a phase's gate, area, outcome or description, under lock.

    F190, and it is the half `scope` does not reach. `pull sprint` and `init`
    synthesize a phase and choose its `testGate`; from that moment the choice is
    unreachable, and one wrong choice is enough to make the phase unable to pass
    its own sign-off. Measured live: an imported phase got `testGate: ["lint"]`,
    `lint` on that repo is `pre-commit run --all-files`, and the phase's tasks
    touched only JSON and Markdown. Every route out was outside the plugin - a
    forbidden hand edit, a `buildCommands` value that is a shell hack, or
    installing a third-party tool to satisfy a gate the plugin itself picked.

    THE EMPTY GATE IS THE POINT OF `--gate-clear`. `_phase_gate` already returns
    `[]` with a basis and its docstring says why: a phase nothing can prove done
    is a phase sign-off signs on review alone. That is a designed state, it
    validates clean, and `/audit:phase add --gate` can reach it for a NEW phase.
    An imported phase could not, which is what made a guessed gate a trap rather
    than a default: `--gate` appends, so without an explicit clear there is no
    spelling for "there is nothing here that can prove this".

    NOT PAST `in_progress`. A done or cancelled phase has a sign-off that was
    given against the gate it had; moving the gate afterwards would rewrite what
    that sign-off attested. A running phase may still be corrected - that is the
    case this verb exists for.
    """
    try:
        raw_index = _mio.read_json(mpath)
        assembled = _mio.load_manifest(mpath)
    except Exception as exc:
        out("[audit-task] cannot read/assemble manifest: %s" % exc)
        return E_USAGE
    vm = _panel_write._cores()[0]
    pre_findings, _w = vm.validate(assembled)
    if pre_findings:
        out("[audit-task] the manifest is already invalid -- nothing written; "
            "fix these first:")
        for line in pre_findings:
            out("FINDING: " + line)
        return E_INVALID

    kind, node, _phase = _find_target(assembled, pid)
    if kind != "phase":
        out("[audit-task] retarget takes a PHASE id; %r is %s"
            % (pid, "not in this manifest" if kind is None else "a " + kind))
        return E_USAGE
    if node.get("status") in ("done", "cancelled"):
        out("[audit-task] %s is %s -- its sign-off was given against the gate it "
            "had, and moving that afterwards would rewrite what the sign-off "
            "attested" % (pid, node.get("status")))
        return E_USAGE

    contradiction = _gate_contradiction(args)
    if contradiction:
        out(contradiction)
        return E_USAGE
    if not (args.gate or args.gate_clear or args.area is not None
            or args.outcome or args.description):
        out("[audit-task] retarget needs one of --gate / --gate-clear / --area / "
            "--outcome / --description -- a call that changes nothing is a lock "
            "taken for no reason")
        return E_USAGE

    changes = []

    def _moved(field, was, now):
        if was != now:
            changes.append({"id": pid, "field": field, "from": was, "to": now})

    if args.gate or args.gate_clear:
        was = list(node.get("testGate") or [])
        now = [] if args.gate_clear else list(args.gate)
        _moved("testGate", was, now)
        node["testGate"] = now
    if args.area is not None:
        was = node.get("area")
        # SPLIT FIRST, then resolve. `--area` is a CSV flag and
        # `areas_of` takes a phase FIELD - handed the raw flag it reads
        # "api,api,web" as one tag and stores it as one, which is a tag no
        # registry has. `add-phase` splits with `_split_csv` for the same
        # reason; `areas_of` still runs, because trimming and deduping are
        # its job and a second copy of that here is how two surfaces come
        # to disagree about whether ["api","api"] is one area or two.
        tags = _areas.areas_of(_split_csv(args.area))
        if not tags:
            # Absent, never `null`: the conventions default `area` to absent, and
            # `null` would make an untagged phase claim to have considered it.
            # `_PHASE_TEMPLATE_KEYS`' own note, at the second write site.
            if "area" in node:
                _moved("area", was, None)
                node.pop("area", None)
        else:
            now = tags[0] if len(tags) == 1 else tags
            _moved("area", was, now)
            node["area"] = now
    if args.outcome:
        _moved("desiredOutcome", node.get("desiredOutcome") or "", args.outcome)
        node["desiredOutcome"] = args.outcome
    if args.description:
        _moved("description", node.get("description") or "", args.description)
        node["description"] = args.description
    if not changes:
        out("[audit-task] %s already reads that way -- nothing written" % (pid,))
        return 0

    snap = _snapshot(_write_paths(project, mpath, raw_index, pid))
    try:
        written = _write_add(project, mpath, raw_index, assembled, pid, False)
    except Exception as exc:
        _restore(snap)
        out("[audit-task] write failed -- manifest restored: %s" % exc)
        return E_INVALID
    try:
        findings, warnings = vm.validate(_mio.load_manifest(mpath))
    except Exception as exc:
        findings, warnings = ["cannot re-read the written manifest: %s" % exc], []
    if findings:
        _restore(snap)
        out("[audit-task] REFUSED: the retarget would leave the manifest invalid "
            "-- every written file rolled back, nothing kept:")
        for line in findings:
            out("FINDING: " + line)
        return E_INVALID

    jres = _journal_retarget(project, config, mpath, pid, changes)
    if args.as_json:
        result = {"ok": True, "id": pid, "changes": changes,
                  "written": written, "warnings": warnings}
        result.update(jres)
        out(json.dumps(result, indent=2, sort_keys=True))
        return 0
    out("[audit-task] %s retargeted" % (pid,))
    for row in changes:
        out("  %s: %s -> %s" % (row["field"], json.dumps(row["from"]),
                                json.dumps(row["to"])))
    if node.get("testGate") == [] and any(r["field"] == "testGate"
                                          for r in changes):
        # The empty gate is a designed state and the reader is told what it means
        # rather than left to read silence as breakage - `_phase_gate`'s rule.
        out("  the gate is now EMPTY: sign-off for this phase is review alone, "
            "which is the designed answer when nothing here can prove it done")
    for line in _wg.collapse(warnings, _mio.load_manifest(mpath)):
        out("WARNING: " + line)
    if not jres.get("journaled"):
        out("  note: not journaled (%s)" % jres.get("journaledWhy"))
    return 0


def cmd_retarget(args, out):
    project = _resolve_project(args)
    if not os.path.isdir(project):
        out("[audit-task] not a directory: %s" % project)
        return E_USAGE
    pid = (args.title or "").strip()          # positional: the phase id
    if not pid:
        out("[audit-task] retarget needs a phase id")
        return E_USAGE
    return _under_lock(args, project, out,
                       lambda config, mpath: _locked_retarget(
                           args, project, config, mpath, pid, out))


def cmd_scope(args, out):
    project = _resolve_project(args)
    if not os.path.isdir(project):
        out("[audit-task] not a directory: %s" % project)
        return E_USAGE
    tid = (args.title or "").strip()          # positional: the id to scope
    if not tid:
        out("[audit-task] scope needs a task id")
        return E_USAGE
    return _under_lock(args, project, out,
                       lambda config, mpath: _locked_scope(
                           args, project, config, mpath, tid, out))


def cmd_cancel(args, out):
    project = _resolve_project(args)
    if not os.path.isdir(project):
        out("[audit-task] not a directory: %s" % project)
        return E_USAGE
    tid = (args.title or "").strip()          # positional: the id to cancel
    if not tid:
        out("[audit-task] cancel needs a task or phase id")
        return E_USAGE
    reason = (args.reason or "").strip()
    if not reason:
        # The whole point of the verb. A status flipped with no why is the
        # hand-edit this replaces, one layer up.
        out("[audit-task] cancel needs --reason \"<why>\" -- cancelling without "
            "a recorded reason is the hand-edit this verb exists to replace")
        return E_USAGE
    return _under_lock(args, project, out,
                       lambda config, mpath: _locked_cancel(
                           args, project, config, mpath, tid, reason, out))


def cmd_add(args, out):
    project = _resolve_project(args)
    if not os.path.isdir(project):
        out("[audit-task] not a directory: %s" % project)
        return E_USAGE
    title = (args.title or "").strip()
    if not title:
        out("[audit-task] add needs a non-empty title")
        return E_USAGE
    return _under_lock(args, project, out,
                       lambda config, mpath: _locked_add(
                           args, project, config, mpath, title, out))


def main(argv, out=print):
    p = argparse.ArgumentParser(prog="audit-task.py", add_help=True)
    p.add_argument("command",
                   choices=["add", "add-phase", "cancel", "scope",
                            "retarget"])
    p.add_argument("title", nargs="?", default="")
    p.add_argument("manifest", nargs="?", default=None)
    p.add_argument("--phase", default=None)
    p.add_argument("--skills", default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--files", default=None)
    p.add_argument("--risk", choices=["low", "med", "high"], default=None)
    p.add_argument("--blocked-by", dest="blocked_by", default=None)
    p.add_argument("--depends-on", dest="depends_on", default=None)
    p.add_argument("--description", default="")
    p.add_argument("--tests-mode", dest="tests_mode",
                   choices=["tdd", "regression", "gate-only"], default=None)
    p.add_argument("--tests-add", dest="tests_add", action="append",
                   default=None)
    p.add_argument("--gate", action="append", default=None)
    # `retarget` AND `scope`, and the two need it for different reasons that
    # reach the same state. On a phase `--gate` APPENDS, so without an explicit
    # clear there is no spelling for the empty gate at all; on a task `--gate`
    # replaces, and the gap is that no VALUE of it spells "none" - `--gate ""`
    # writes a gate holding an empty command, which is a gate that cannot run
    # rather than the absence of one. `_phase_gate` documents the empty gate as
    # a designed state, and it is what a wrongly-guessed gate needs.
    p.add_argument("--gate-clear", dest="gate_clear",
                   action="store_true")
    p.add_argument("--project-dir", dest="project_dir", default=None)
    p.add_argument("--reason", default=None)
    # add-phase only. `--id` rather than a positional: the title is the
    # positional every verb here already spends, and an OPTIONAL id read off
    # position two would be indistinguishable from the optional `manifest`.
    p.add_argument("--id", dest="phase_id", default=None)
    p.add_argument("--outcome", default=None)
    p.add_argument("--area", default=None)
    p.add_argument("--review-skill", dest="review_skill", default=None)
    p.add_argument("--takeover", action="store_true")
    p.add_argument("--json", action="store_true", dest="as_json")
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        return E_USAGE if exc.code else 0
    doors = {"add": cmd_add, "add-phase": cmd_phase_add,
             "cancel": cmd_cancel, "scope": cmd_scope,
             "retarget": cmd_retarget}
    try:
        return doors[args.command](args, out)
    except Exception as exc:                    # never leave a caller guessing
        out("[audit-task] internal error: %s" % exc)
        return E_INVALID


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to `main`, which would read the flag
        # as an unknown subcommand. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("audit-task.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_audit_task.py - run that file instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
