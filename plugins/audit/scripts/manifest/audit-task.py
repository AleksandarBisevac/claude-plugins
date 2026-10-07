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
                [--outputs pat,pat]
                [--risk low|med|high] [--blocked-by id,id] [--depends-on id,id]
                [--description TEXT|-] [--tests-mode tdd|regression|gate-only]
                [--tests-add TEXT ...] [--gate CMD ... | --gate-clear]
                [--failing-from RUNID] [--dry-run] [--project-dir DIR]
                [--takeover] [--json]
  audit-task.py add-phase "<title>" [manifest] --outcome "<what success is>|-"
                [--park] [--id P7] [--description TEXT|-] [--area a,b]
                [--gate CMD ... | --gate-clear]
                [--blocked-by id,id] [--review-skill NAME]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py next-id bug|prop [manifest] | next-id task --phase <id> [manifest]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py signoff <phaseId> --verdict passed|skipped --summary TEXT|-
                [--review-outcome TEXT|-] [manifest]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py signoff <P1,P2,...> --branch NAME
                (--plan | --verdict passed|skipped --summary TEXT|-
                 [--review-outcome TEXT|-]) [manifest]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py start <taskId> [manifest]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py done <taskId> (--commit <sha> | --no-change --reason TEXT|-)
                [manifest] [--descriptive TEXT|-] [--technical TEXT|-]
                [--verified-by t1,t2]
                [--intent matches|diverges|cannot-tell|not-asked]
                [--intent-basis TEXT|-] [--override-verdict TEXT|-]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py move <taskId> --to <phaseId> [manifest]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py block <taskId> --reason "<why>|-" [manifest]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py note <taskId> --text "<what>|-" [manifest]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py cancel <id> --reason "<why>|-" [manifest]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py scope <taskId> [manifest] [--files f1,f2]
                [--tests-mode tdd|regression|gate-only] [--tests-add TEXT ...]
                [--gate CMD ... | --gate-clear] [--description TEXT|-]
                [--risk low|med|high] [--blocked-by id,id] [--depends-on id,id]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py retarget <phaseId> [manifest]
                [--gate CMD ... | --gate-clear | --gate-set entry ...
                 | --gate-drop entry ...]
                [--area a,b] [--outcome TEXT|-]
                [--rename TITLE|-]
                [--description TEXT|-] [--project-dir DIR] [--takeover] [--json]
  audit-task.py seed ["<phase title>"] [manifest]
                [--gate CMD ... | --gate-clear]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py settle [manifest]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py reopen <taskId> --reason "<why>|-" [manifest]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py couple --test <path> --sources p,p --basis-run <runId>
                --basis-head <sha> [--phases id,id] [manifest]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py couple --test <path> --caught <runId> [manifest]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py uncouple --test <path> [manifest]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py bug-add "<title>|-" [manifest] --severity low|med|high
                --description TEXT|- [--files a,b] [--repro TEXT|-]
                [--expected TEXT|-] [--actual TEXT|-]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py mute --test <path> --reason TEXT|- --owner NAME
                --until <YYYY-MM-DD> --bug <bugId> [manifest]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py unmute --test <path> [manifest]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py finding <phaseId> (--severity low|med|high --file <path>
                --issue TEXT|- --resolution TEXT|- | --findings-file PATH|-)
                [manifest] [--project-dir DIR] [--takeover] [--json]
  audit-task.py resolve-finding <findingId> --fix-task <taskId>
                [--commit <sha>] [manifest]
                [--project-dir DIR] [--takeover] [--json]
  audit-task.py correct <phaseId> [--review-outcome TEXT|-] [--summary TEXT|-]
                [manifest] [--project-dir DIR] [--takeover] [--json]
  audit-task.py --selftest

  <manifest> defaults to the project's configured manifestPath
  (.claude/audit.config.json, default docs/audit/audit-plan.json).
  --phase absent -> the single in_progress phase when that is unambiguous,
  else exit 2 naming the choices. --skills null is the explicit opt-out
  (v0.37 B1): written as JSON null, it STOPS the area fallback; absent/empty
  means "unconsidered" and is written as [] (the area default stays in
  force). A skill literally named "null" cannot be spelled from this flag;
  no such skill exists. --tests-add and --gate repeat (one value each).
  --files, --blocked-by, --depends-on and --verified-by repeat too, and each
  value is still split on commas, so `--files a --files b,c` is three paths.
  `add --dry-run` builds the task and validates the plan with it in memory,
  and writes nothing. Under --json every refusal is one object,
  {ok: false, exit, refused, findings}, never prose on stdout.
  A --tests-add value reaches `files` through the PATH it names, written as
  "<path>: <what it asserts>"; the field is free prose, so an entry
  naming no file adds nothing and the report says which entries those were
  rather than guessing a filename out of a sentence.
  --risk, --blocked-by and --depends-on reach `scope` as well as `add`: the
  same three fields `_build_task` sets at creation, correctable
  afterwards while the task has not started -- once it has, only `--files`
  and `--tests-add` are still on offer and only as a WIDENING (`_locked_scope`
  states why append-only is the exact operation that leaves
  a past judgement standing). They need no
  `--clear` twin -- `--blocked-by ""` empties the field, because a comma
  list of IDS has no value that reads as content the way `--gate ""` reads
  as an empty COMMAND, and `retarget --area ""` already draws that line.
  `--description -` reads the brief off STDIN instead of off argv,
  which is where a brief goes whose exact characters must survive: backticks
  a shell would run as command substitution, but also a colon, a paren or a
  comma sitting next to whitespace in code quoted straight into the prose --
  the check tests for that SHAPE and never for a backtick, so text with none
  at all can still be refused off argv. A heredoc with a QUOTED word is the
  shell-proof form either way. A description consisting of the single
  character `-` cannot be spelled from this flag, and is not a description.
  Every flag in PROSE_FLAGS takes that `-` and is checked the same way --
  `PROSE_FLAGS` is the list, and it is a tuple rather than a sentence here so
  a flag added to it cannot be added to a prose enumeration nobody updates.
  STDIN IS ONE STREAM, so at most one flag per call may claim it and a call
  where two do is refused before anything is read, naming the two.
  `done` closes a task the way `start` opens one, and it is the only verb
  here whose flag is REQUIRED for the record rather than for the field:
  `--commit` is the SHA the work landed in, without which the close is the
  state `/audit:doctor` already reports (`done`, no commit). The one close
  with no commit is `--no-change --reason`, a task whose answer was that
  nothing needed to change: it records the reason and the HEAD it examined
  in `outcome.noChange`, which is what the doctor's no-SHA warning reads to
  leave it out.
  `move`, `block` and `note` are the hand edits `commands/task.md` and the
  field reports kept making: a task renumbered into another phase with every
  reference rewritten, a task set `blocked` with the reason in
  `blockedReason`, and an append-only `{at, text}` entry on `notes[]` - the
  one thing a started task still takes, since `scope --description` refuses
  a task that has started.
  `seed` is the one verb here that WRITES WHERE NOTHING WAS: every other verb
  refuses when the manifest is missing, and this one refuses the opposite way,
  when one is already there -- pointing the caller at `add`/`add-phase` or
  /audit:init instead of overwriting it. What it writes is deliberately the
  smallest thing that validates: one phase, one task, and a `testGate` derived
  from `meta.buildCommands` the same way `add-phase` derives one -- which is
  empty, honestly, because nothing here guesses a test or lint command from a
  tree it has never run. `--gate`/`--gate-clear` still work, for a caller who
  already knows the real command and would rather not run `/audit:task
  retarget` a second time.
  `couple` and `uncouple` are the only writers of `meta.coupling`, the record
  a derived phase gate reads to widen itself back onto a test whose own run
  named a source it depends on. `couple` appends a new entry or, for a test
  already coupled, WIDENS the existing one -- unions `--sources` in, keeps
  the first `learnedAt` -- because a coupling is a fact that grows and is
  never silently replaced. `--basis-run` names a row the evidence ledger
  actually holds (looked up, never parsed) and `--basis-head` the HEAD that
  row examined; a coupling with no run to point at teaches nothing.
  `couple --caught <runId>` records that an already-coupled test earned its
  place: the run must be a `full` row whose runner NAMED the test as failing
  on a step no mute excused, whose own `selectionMiss` does not list it, and
  the entry's `lastCaught` becomes that row's
  `ts`. It never creates an entry and never touches `sources` or `basis`;
  a run no newer than the `lastCaught` already recorded (compared as a
  moment, not as text) writes nothing and exits 0 saying so.
  `uncouple` drops one entry by `--test` alone, and refuses, exit 2, a test
  that carries none.
  `bug-add` appends one bug to top-level `bugs[]` in exactly the shape
  `commands/bug.md` spells, creating the list when the plan has none, with
  the id the `next-id bug` allocator names. `mute` and `unmute` are the only
  writers of `meta.muted`: a mute names the bug tracking the failure it
  hides, and a mute naming a bug the plan lacks is refused by the
  validator's own finding on the revalidation, every written file rolled
  back (exit 1). A mute on a test already muted, with a later `--until`,
  extends that entry.
  `finding`, `resolve-finding` and `correct` are the writes sign-off's review
  step makes: a finding appended to `review.findings` in the schema's shape,
  the task and commit that fixed one, and a TEXT correction of the review's
  outcome or the phase summary that never touches the verdict. Each of them,
  and `signoff`, derives the `[findings: ...]` tally at the end of
  `review.outcome` from the list rather than taking it from the text.

Exit codes:
  0  written, manifest valid
  1  refused invalid: the manifest had findings before the write (nothing
     written), or the write itself would leave it invalid (every written file
     rolled back byte-for-byte); the findings are printed either way
  2  usage: unknown/ambiguous/done/reserved phase, missing manifest, bad args,
     a `--description` off argv that a shell has already eaten part of, or a
     flag passed to a verb that does not READ it -- one parser serves every
     verb, so argparse accepts every flag on each of them and a flag a verb
     does not read would otherwise write nothing and report success. The refusal names the verb
     that does read it; `VERB_FLAGS` is the table and the suite derives the
     same answer off this file's call graph.
  3  the index lock is held by a LIVE run (audit-lock's standard message)
  4  the index lock looks abandoned -- rerun with --takeover once a human
     has confirmed (audit-lock's standard message)

Design decisions, each mirroring a precedent rather than inventing one:

  * PROJECT. Which root owns the journal, the lock, the config and
    the file-existence notes is decided by `_panel_write.PROJECT_BASES`, which
    is that order AND the clause each row is chosen for, in one place because
    every verb here now PRINTS the clause. Naming another project's manifest
    from this cwd must not journal or lock into THIS repo -- the class
    audit-usage's resolve_ledger already solved. Every verb also says so out
    loud when the tree the caller is standing in is not the tree being written
    (`_panel_write.standing_elsewhere`, which states why that is a warning and
    neither silence nor a refusal); on a same-tree call it prints nothing.

  * LOCK. The whole read-allocate-write runs under the INDEX lock, taken by
    calling the lock LIBRARY (`_locks.acquire`) through the one door both this
    command and the panel use -- ids are allocated under the lock so two
    sessions can never mint the same one (manifest-conventions.md -> ID
    allocation). A held or stale lock prints the lock module's OWN output: one
    message shape everywhere. Outside a git repo, and only there, the
    `<manifest>.lock` working-tree file is the fallback guard, exactly as in
    _panel_write._acquire_write_lock -- a project with a repository is always
    coordinated through the shared claim, or the two surfaces would be
    guarding different things.

  * ID. `<phaseId>.<n>`, n = highest existing numeric suffix + 1, computed
    over the WHOLE assembled manifest plus every still-parked proposal
    payload -- gaps are history and never re-minted. A --phase naming an id
    RESERVED by a parked proposal is refused toward /audit:propose
    materialize (materialization is a move; hand-minting into a reserved id
    would make it a collision).

  * PHASE. `add-phase` is the verb `/audit:phase add` calls, and it
    exists because nothing else in the tree appends to `phases[]` except the
    ADO pull: `/audit:init` synthesizes a whole plan, `/audit:propose
    materialize` MOVES a parked payload, and `add` places a task inside a phase
    that must already be there. So a maintainer whose plan outlived its first
    round -- the state every long-lived plan ends in -- had three options and
    all of them were wrong: re-run init over a finished plan, pull from a
    board, or hand-edit the index and write a shard. The phase id continues the
    sequence through `_proposals.next_appended_phase_id` -- the highest `P<n>`
    plus one -- over the same live-AND-parked taken set
    `/audit:propose materialize` allocates against, sharing the set and not the
    rule (`_allocate_phase_id` says what cost sharing only the set carried);
    `--outcome` is required for `--reason`'s reason (a phase whose
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

  * BRIEF. A flag carrying a human's own
    words reaches this script through a shell, which eats a backtick span before
    argparse sees it -- silently, and usually taking the clause the author
    backticked BECAUSE it mattered. So each such flag also takes `-`, reading the
    text off stdin the way check-ado-item.py's `read_json` and four ADO siblings
    already read a payload; and a value that arrives off ARGV carrying the
    whitespace such a deletion leaves behind is refused, pointing at that route.
    `PROSE_FLAGS` is which flags those are and why the rest are not, and
    `resolve_briefs` holds the halves: the one-stream arbitration, the refusal
    off argv, and the NOTE on a stdin value that already has a hole in it --
    which is not refused, because that route is the door out of a false positive.
    `shell_eaten_gap` tests the WHITESPACE SHAPE a deletion leaves, never the
    presence of a backtick, so code quoted straight into a brief -- a ternary, a
    colon-joined pair -- trips the same refusal with no shell and no backtick
    anywhere in the call; the refusal names the shape it matched rather than
    assuming the cause, and `_marked_excerpt` marks the exact span.

  * HEAL (v0.37 A4). Reuses _panel_write._heal_phase_status on the target
    phase: a write this code makes must not persist a pending phase that
    already holds an in_progress task. The validator warning stays as the
    backstop for hand edits.

    `start` REACHES IT TOO, and that is what gave a phase a verb. The control
    surface's save used to be the only site in the tree that promoted a phase,
    so an orchestrator that never opened the panel left every phase pending
    for its life -- and the promotion carries a `startedAt`, so a plan driven
    from the terminal records when its phases began. Nothing about the plan
    gate moves: a running task under a pending phase already counted as a
    running phase, deliberately.

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
import re
import subprocess
import sys
import types

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
import _manifest_vocab as _vocab  # noqa: E402  (_strip_line_suffix: one reading of a
#                                            `files` entry's `:line-range` suffix -- a
#                                            downward edge, L7 -> L1, the same reading
#                                            `commit-task-work.py` already takes before
#                                            joining a declared entry onto a filesystem
#                                            path)
import _areas                 # noqa: E402  (areas_of: the one area resolution every surface shares)
import _manifest_rules as _rules  # noqa: E402  (tests_add_path: the ONE answer to
#                                            "does this `tests.add` entry name a file".
#                                            A downward edge, L7 -> L3, and the parse
#                                            lives there because the rule that REQUIRES
#                                            the shape grades the same field this verb
#                                            writes - two parses would be two opinions
#                                            about what `commit_scope` then judges)
import _manifest_phases as _phases  # noqa: E402  (gate_entry_paths: the same filename
#                                            bound asked of a gate entry instead of a
#                                            `tests.add` one. A downward edge, L7 -> L2,
#                                            kept separate from the `_rules` edge above
#                                            because `run-test-gate.py`'s `--own` reads
#                                            the identical function and a second copy
#                                            here is exactly what an entry point cannot
#                                            import out of the other)
import _commit_trail          # noqa: E402  (is a SHA still in this clone? A downward
#                                            edge, L7 -> L1, and the ONE answer the
#                                            doctor and `repair-commits.py` already
#                                            share -- `done` grades the SHA it is
#                                            handed before writing it, and a third
#                                            walk putting that question to git would
#                                            be a third answer to disagree with)
import _branch                # noqa: E402  (parent_branch: which branch is the development one)
import _journal_io            # noqa: E402  (read_all: the phase.add rows a side-branch
                              # warning is read back from; MAX_VALUE_CHARS, the
                              # per-value bound a long outcome is fitted into)
import _id_shape              # noqa: E402  (the one answer to which id comes next, and the
                              # branch suffix that keeps two branches from minting it twice)
import _evidence_io           # noqa: E402  (read_rows: the runs a move leaves keyed
                              # to the old id, which `move` reports)
import _gate_derive           # noqa: E402  (is_shared_key, path_scoped_sibling,
                              # repointed: a TASK's own gate and a PHASE's derived
                              # one ask the same three questions, so both entry
                              # points share one body instead of two that could
                              # drift)
import _id_refs               # noqa: E402  (rename: one id rewritten everywhere the plan
                              # points at it - `move`'s references, from the one list of
                              # fields that hold an id)
import _proposals             # noqa: E402  (the TAKEN SET `/audit:propose materialize`
#                                            allocates against - live AND parked ids - plus
#                                            the two rules over it. A second taken set here
#                                            would be a second answer about which ids are
#                                            taken; the rules differ on purpose)
import _status_facts          # noqa: E402  (unmet_refs: the ONE answer to "what is this
#                                            waiting on". A downward edge, L7 -> L2, with
#                                            precedent at audit-status.py, _invariants.py
#                                            and _report_page.py -- see `_waiting_on` for
#                                            what the second copy here got wrong)
import _panel_write           # noqa: E402  (one answer to "where is the manifest", the
#                                            byte-shape writer, the A4 heal, the lock and
#                                            journal module handles -- reused by identity,
#                                            not reimplemented)
import _invariants            # noqa: E402  (the journal actions that record a state or
#                                            index commit, which a group's branch may carry)
import _verdict_binding as _vb  # noqa: E402  (the one rule for whether a recorded gate
#                                            verdict binds the work, shared with the task commit)
import _task_outputs as _touts  # noqa: E402  (what an `outputs` pattern may be -- the
#                                            one rule this verb, the validator and the
#                                            plan gate all read)
import _warning_groups as _wg  # noqa: E402  (the shape a repeated warning prints in)
import _worktrees             # noqa: E402  (which worktree the caller is standing in,
#                                            and its branch -- a downward edge, L7 -> L1,
#                                            the same list `close-phase.py` and
#                                            `manage-worktrees.py` already read rather than
#                                            a second `git worktree list` walk of this
#                                            command's own)

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
    """`a,b , c` -> ["a", "b", "c"]; None/empty -> [].

    A LIST IS THE SAME ANSWER, one element per repeat of the flag: the list flags
    are `action="append"`, so `--files a --files b,c` arrives as `["a", "b,c"]`
    and reads as `["a", "b", "c"]`. The comma split is kept inside each value,
    because that is the spelling every existing call and document uses.
    """
    if isinstance(val, (list, tuple)):
        return [part for item in val for part in _split_csv(item)]
    if not isinstance(val, str):
        return []
    return [part.strip() for part in val.split(",") if part.strip()]


# --- what a `--files` entry may be -----------------------------------------------
# A repository-relative path, and the refusal below is for the strings that are not
# one at all. It is NOT a check that the file exists: declaring a file before it
# exists is legal and quiet, because the red-first workflow depends on it -- a task
# that will author its own case names that case in `files` before anything is there.
#
# WHAT WAS MEASURED. `--files "+a.py,-b.py"` -- the incremental spelling every
# neighbouring tool offers -- wrote `+a.py` and `-b.py` into the task's `files` as
# part of the filenames, claimed both in `fileIndex`, recorded a journal row saying
# so, and printed only the advisory that exists to reassure an author declaring a
# file they will create. The one shape that is certainly a mistake read exactly like
# the one shape that is certainly fine. The verb is right to take a REPLACEMENT list;
# it is wrong to take an operator as a filename.
#
# EACH PREFIX IS ITS OWN ENTRY because the four say different things to the caller:
# an operator is a spelling this verb does not have, a root-anchored path and a home
# path both resolve outside the repository the index is keyed on, and a parent
# segment resolves to a file the plan cannot name twice the same way.
_FILE_REFUSALS = (
    ("+", "a leading `+` is an incremental spelling this verb does not have"),
    ("-", "a leading `-` is an incremental spelling this verb does not have"),
    ("/", "a leading `/` is an absolute path, and `files` is read relative to "
          "the project root"),
    ("~", "a leading `~` is a home path, and `files` is read relative to the "
          "project root"),
)


def _path_problems(values):
    """`["'<value>': <why>", ...]` for every entry that cannot be a
    repository-relative path - the one reading `--files` and a finding's
    `--file` share.

    THE `..` ARM IS A SEGMENT TEST AND NOT A SUBSTRING ONE, because `..` inside a
    name (`a..b.py`) is an ordinary filename and only a whole segment climbs out
    of the tree.
    """
    bad = []
    for value in (values or []):
        why = None
        for prefix, reason in _FILE_REFUSALS:
            if value.startswith(prefix):
                why = reason
                break
        if why is None and ".." in value.replace("\\", "/").split("/"):
            why = ("a `..` segment resolves outside the path the plan records, "
                   "so the index would key one file under two names")
        if why:
            bad.append("%r: %s" % (value, why))
    return bad


def _files_refusal(values):
    """The refusal for a `--files` entry that cannot be a path, or None.

    ONE MESSAGE FOR EVERY BAD ENTRY IN THE CALL, not one per entry: a caller who
    typed the delta spelling typed it on both sides, and two refusals for one
    mistake is the shape an operator learns to skip.
    """
    bad = _path_problems(values)
    if not bad:
        return None
    return ("[audit-task] --files takes the REPLACEMENT list of "
            "repository-relative paths, and %s. Pass the whole list the task "
            "should end up with; a file that does not exist yet is fine and is "
            "reported as a note, which is the reassurance this refusal used to "
            "be mistaken for." % ("; ".join(bad),))


def _outputs_refusal(values):
    """The refusal for an `--outputs` entry the plan gate may not honour, or
    None.

    THE RULE IS NOT RESTATED HERE. `_task_outputs.output_pattern_problem` is
    the one expression of what an output pattern may be, and it has three
    readers: this verb before a write, the validator over a manifest already
    written, and the plan gate before it opens a file. A second reading of
    "too wide" in the writer would be the half that is easiest to relax, and
    relaxing it is how a plan comes to cover the whole tree.

    REFUSED BEFORE THE WRITE AS WELL AS AFTER IT, and the two are not redundant.
    The validator's finding would roll the write back, which is correct and
    arrives after the operator has been told the task was created; refusing here
    means the answer names the pattern while they are still looking at the
    command they typed. `_files_refusal` above draws the same line for the same
    flag-shaped mistake.
    """
    bad = ["%s" % (why,) for _entry, why in _touts.output_problems(values)]
    if not bad:
        return None
    return ("[audit-task] --outputs takes patterns for the files this task "
            "PRODUCES, each anchored at a literal directory name, and %s. "
            "`outputs` is what lets the plan gate sanction a write the task's "
            "`files` could not enumerate - a pattern reaching the whole tree "
            "would turn the gate off instead." % ("; ".join(bad),))


def _union_paths(declared, extra):
    """`declared` plus anything in `extra` it does not already carry, order kept.

    ORDER IS KEPT because the list is read by people: the files the author typed
    stay where they typed them, and the ones derived from `tests.add` follow. A
    `sorted(set(...))` would produce the same scope and a different document on
    every edit, which is a diff nobody can review.

    `extra` IS ALREADY PATHS: this joins two lists of paths, and
    `_tests_add_paths` below is the only thing that
    decides what a `tests.add` entry names. A union that also parsed would be
    the place a sentence got in.
    """
    out = list(declared or [])
    seen = set(out)
    for path in (extra or []):
        if isinstance(path, str) and path.strip() and path not in seen:
            out.append(path)
            seen.add(path)
    return out


def _tests_add_paths(entries):
    """`(paths, unnamed)` -- the file each `tests.add` entry names, and every
    entry that names none.

    `tests.add` used to be unioned into `files` on the rule that "a tdd task
    creates the file it names in `tests.add` by definition", copying the WHOLE
    STRING to do it. The premise is false of the field: the schema documents
    `tests.add` as "Assertions/tests to author" -- free prose -- so the scope
    filled up with assertions and `fileIndex` grew keys no path can ever match.

    THE SHARP HALF IS THE PERMISSION AND NOT THE POLLUTION, which is why the
    parse is total here rather than best-effort. The union exists so
    `_invariants.commit_scope` will allow the test file the task declares it will
    create. When the entry is a sentence, the thing added to `files` is not that
    path -- so the permission the union promised was never granted, in the common
    case, and the task's own commit trips a scope the operator had just set.

    AN ENTRY THAT NAMES NO FILE IS RETURNED RATHER THAN DROPPED. Every caller
    prints it: a claim carries the basis that makes it true, and when the basis
    is missing that is the thing to say. Falling back to the whole string is the
    defect; falling back to a guessed leading token is the same defect one word
    narrower; falling back to silence tells the operator their case file is in
    scope when it is not.

    THE PARSE ITSELF IS ASKED OF `_manifest_rules`, one layer down, and not
    spelled here. That module's `_check_tests_add_shape` REQUIRES the shape of a
    `tdd` task that can still be committed against, so the question "does this
    entry name a file" is asked twice about the same manifest -- once by the verb
    building `files` and once by the rule grading it. Two spellings of it would
    be two opinions about the one thing `commit_scope` then judges.
    """
    paths, unnamed = [], []
    for entry in (entries or []):
        found = _rules.tests_add_path(entry)
        if found:
            paths.append(found)
        else:
            unnamed.append(entry)
    return paths, unnamed


def _unnamed_add_note(unnamed):
    """The report line for `tests.add` entries that named no file, or None.

    ONE SENTENCE, THREE WRITE SITES. `add` and the two `scope` branches all union
    `tests.add` into `files`, so all three owe the same account of what the union
    could NOT do -- and three spellings of it is how one of them ends up silent,
    which is the state all three call sites were found in before this single
    function existed to write the line once.
    """
    if not unnamed:
        return None
    # The entries are listed rather than counted, and not because a count would
    # rot here: a count tells the reader how much was lost and the STRINGS tell
    # them which line to go and fix.
    return ("  note: `files` gained nothing from these tests.add entries, "
            "which name no file -- the field is free prose and the union can "
            "only carry a path it can read. Write it as "
            "\"<path>: <what it asserts>\" if the task creates that file, or "
            "pass the path to --files: %s"
            % (", ".join(repr(e) for e in unnamed),))


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


# --- the brief, and the shell that may already have eaten part of it ----------
# A description is the operator's OWN WORDS, and by the time argparse sees
# one it has already been through a shell. Inside double quotes a backtick span is
# COMMAND SUBSTITUTION: the shell RUNS what sits between the backticks and puts its
# output there instead, which for a sentence of prose is nothing at all. Measured
# live: a brief that quoted the one condition the work turned on arrived here with
# `gating on , returning the response untouched otherwise` -- the clause its author
# had backticked precisely BECAUSE it mattered most was the clause the shell
# deleted. This script accepted it, wrote it, and a whole phase ran against a brief
# with a hole in it. Nothing in the plugin had ever looked at the text.
#
# THE REPAIR IS THE INPUT ROUTE, and the check below only makes it findable at the
# moment it is needed. `--description -` reads the brief off stdin, which no
# argument parser and no QUOTED heredoc rewrites. The `-` spelling is the dialect
# that already exists here -- `check-ado-item.read_json` and four siblings take a
# `-` where a value goes and read stdin -- rather than the `--*-file` flag this
# plugin has nowhere and would be the odd command out for having.


# The shapes an eaten span leaves behind: whitespace sitting where a WORD was.
# Each is a different POSITION the hole can open in, and each carries what a reader
# would actually see, because "malformed" tells nobody which character to look at.
#
# WHAT IS DELIBERATELY ABSENT, all of it measured over the description strings this
# repository's own plan carries. An UNBALANCED BACKTICK COUNT is the intuitive test
# and is refuted by the mechanism: the shell removes both delimiters, so the count
# stays even and the reported damage scores clean. A TRAILING PREPOSITION
# ("...talking to.") over-fires on ordinary sentences already in the plan. TWO
# SPACES AFTER A FULL STOP is a typing convention rather than a gap, which is why
# the run below refuses to start after one -- and a run after a NEWLINE is an
# indented continuation line, so it does not start there either.
_GAP_SHAPES = (
    (re.compile(r"(?<=[^\s.!?])[ \t]{2,}"),
     "a run of spaces inside a sentence"),
    # A COLON THAT STARTS AN IDENTIFIER IS NOT A HOLE: `params :id and :key`.
    # Measured over the prose strings this plan, the shipped example and the
    # starter template carry, the arm fired at a colon on three strings - that
    # shape, a line reference `and :2680`, and a pytest `::` - and only the first
    # is released. A colon before a DIGIT stays refused on purpose: the plan's
    # commonest citation is "`path`:line", and inside double quotes the shell
    # substitutes the backticked path and leaves exactly ` :2680`, so a line
    # reference after whitespace goes in on stdin.
    (re.compile(r"[ \t](?:[,;)]|:(?![A-Za-z_]))"),
     "whitespace before a mark that hugs the word in front of it"),
    # The full stop has to be a full stop and not an ARGUMENT. A bare `.` is a
    # path, and this plan's own prose quotes `git fetch . b:p`, which the loose
    # form convicted -- the only false positive the whole corpus produced. So the
    # period is only read as ending a sentence when a sentence ends after it:
    # the string does, or the next word starts one.
    (re.compile(r"[ \t]\.(?=\Z|\s+[A-Z(\[])"),
     "whitespace before a full stop"),
    (re.compile(r"\A[ \t]+"),
     "whitespace before the first word"),
    (re.compile(r"[ \t]+\Z"),
     "whitespace after the last word"),
)


def shell_eaten_gap(text):
    """(what it looks like, the window around it, and the match's start/end
    OFFSETS WITHIN THAT WINDOW), or None if the brief reads whole.

    THE FIRST GAP AND THEN IT STOPS. A brief with two holes needs the same repair
    as a brief with one, and printing a list of them invites the reader to grade a
    severity that does not exist -- every one of them is a deleted clause.

    THE OFFSETS ARE WHAT LET A CALLER POINT AT THE MATCH rather than merely quote
    the window around it: this function tests the whitespace-adjacency SHAPES in
    `_GAP_SHAPES` and no backtick at all, so the window alone answered "something
    in here looks wrong" and left a reader to find which characters that was --
    across a run of spaces or a code snippet quoted into prose, that guess is not
    free. `_marked_excerpt` is what turns the offsets into a caret under the
    exact span.
    """
    if not isinstance(text, str) or not text:
        return None
    for pattern, what in _GAP_SHAPES:
        found = pattern.search(text)
        if found:
            start = max(0, found.start() - 30)
            return what, text[start:found.end() + 30], \
                found.start() - start, found.end() - start
    return None


# THE WINDOW, POINTED AT RATHER THAN MERELY QUOTED. `%r` alone shows the window's
# whitespace (which is the evidence) but not WHICH characters in it matched, and a
# window with more than one run of spaces leaves the reader to guess. Escaping is
# done a character at a time rather than by slicing `repr()`'s output: `repr` picks
# its escaping for the string AS A WHOLE (which quote character it wraps with), so
# an offset computed against the raw text can drift from an offset into that
# string by however many characters an earlier escape added. One loop building
# both the shown text and the caret line from the SAME per-character lengths keeps
# the two in lockstep by construction, which slicing a second computation could not
# promise.
_VISIBLE_ESCAPES = {"\t": "\\t", "\n": "\\n", "\r": "\\r"}

SEEN_PREFIX = "  Seen at: "


def _marked_excerpt(excerpt, rel_start, rel_end):
    """(the `Seen at:` line, the caret line beneath it) for a window
    `shell_eaten_gap` returned, `rel_start`/`rel_end` being the match's own
    offsets into `excerpt`.

    ORDINARY CHARACTERS, SPACES INCLUDED, ARE LEFT ALONE -- they already read as
    themselves in a terminal, and substituting a glyph for one would make the
    excerpt harder to compare against the operator's own text than the thing it
    is meant to clarify. Only the whitespace shapes in `_VISIBLE_ESCAPES` (a
    tab, a newline, a carriage return) are made visible, because a caret alone
    could not disambiguate any of those from a plain space.
    """
    shown, marks = [], []
    for i, ch in enumerate(excerpt):
        disp = _VISIBLE_ESCAPES.get(ch, ch)
        shown.append(disp)
        marks.append(("^" if rel_start <= i < rel_end else " ") * len(disp))
    seen_line = SEEN_PREFIX + "'" + "".join(shown) + "'"
    mark_line = (" " * len(SEEN_PREFIX)) + " " + "".join(marks)
    return seen_line, mark_line


# EVERY FLAG WHOSE VALUE IS THE OPERATOR'S OWN PROSE. The stdin-and-gap check above
# started with `--description` alone and widened to cover the whole class, which is what this table is. `--reason` is the
# sharpest of the rest: it is a VERBATIM field precisely so nobody would
# paraphrase it, so a clause a shell deleted out of one is silent BY DESIGN -- it
# reaches `outcome.descriptive` or a phase `summary`, and a `task.cancel` row in the
# hash-chained journal then attests it. `--outcome` is a phase's `desiredOutcome`,
# which sign-off has to address; `--rename` is a phase title, which
# `_branch.slugify` turns into a branch name.
#
# WHAT IS DELIBERATELY NOT HERE, because the boundary is the half that rots.
# `--gate` carries a COMMAND rather than prose: `make check ; true` trips the gap
# shapes and is exactly right, so checking it would convict correct input.
# `--files`, `--area`, `--skills`, `--blocked-by` and `--depends-on` are comma lists
# of IDENTIFIERS, where an eaten span leaves an empty element `_split_csv` already
# drops. `--model` and `--tests-mode` are enums argparse grades.
#
# MEASURED BEFORE EACH ONE WAS ADDED, over every string of its shape in this
# repository's plan, the shipped example and the starter template -- titles,
# outcomes, summaries, descriptions and cancel reasons alike: the gap shapes fire on
# none of them. A guard that convicts the corpus it ships with is a guard somebody
# routes around inside a day.
#
# `--descriptive` AND `--technical` ARE THE TWO HALVES OF A TASK'S `outcome`,
# spelled with the schema's own field names so neither has to be explained twice.
# They belong here for `--reason`'s reason exactly: `outcome.descriptive` is the
# line every report surface renders (`_report_html.py` reads it first and falls
# back to `technical`), and `outcome.technical` is what a retry brief quotes back
# to the next executor -- a clause a shell ate out of either is a sentence that
# reads whole and is not.
#
# `--intent-basis` and `--text` join for the same reason: the basis of a
# deliberate `not-asked` and a note's text are both the operator's sentence,
# written verbatim into the plan. They are the exception to the measurement
# above - neither field existed before these flags, so there was no corpus of
# either to measure over.
#
# `--issue` and `--resolution` are a review finding's two sentences, which a fix
# executor is handed verbatim, and they break the measurement above rather than
# escaping it: run over the findings this repository's plan already records,
# `shell_eaten_gap` fires on some of them - trailing whitespace a reviewer's
# multi-line return carries, and code quoted up against punctuation. They are in
# the table anyway, because a finding quotes code in backticks more than any other
# field does, and a silently eaten identifier is the worse failure. So the stdin
# route is the ordinary one for a finding's text, not the exception.
#
# `--repro`, `--expected` and `--actual` are a bug report's three sentences,
# which `/audit:bug fix` embeds verbatim in the fix task's description. They
# join for `--issue`'s reason: a report quotes code and output more than it
# quotes anything else, and a clause a shell ate out of one is a repro that
# reads whole and does not reproduce.
#
# `--override-verdict` joins for `--no-evidence-reason`'s reason: it is the
# operator's why for a close over a gate verdict that refuses it, journaled
# verbatim.
PROSE_FLAGS = ("description", "reason", "outcome", "rename", "descriptive",
               "technical", "summary", "review_outcome", "no_evidence_reason",
               "intent_basis", "text", "issue", "resolution", "repro",
               "expected", "actual", "override_verdict")

# THE ONE PLACE `--help` SAYS ANYTHING ABOUT THE STDIN ESCAPE. Before this, none
# of the flags in PROSE_FLAGS carried a `help=` at all -- `--help` printed the
# bare flag name and left the route out of the whole class of refusal
# undiscoverable for a caller who had not yet been refused, or whose text holds
# no backtick to go looking for. Framed on the SHAPE the check reads and not on
# backticks alone, because `_GAP_SHAPES` is whitespace-adjacency and none of
# its entries is a backtick.
_PROSE_HELP = ("free text, written into the manifest verbatim; pass - to read "
              "it off stdin instead of argv, which no shell rewrites -- worth "
              "reaching for whenever the text might trip a whitespace-adjacency "
              "check on argv, backticks or not")

# ...AND THE TITLE, WHICH IS NOT A FLAG AT ALL. The check above closed the
# class for flags and left this, which put the guard on the CORRECTION path and not
# on the path where a title first reaches the manifest: `retarget --rename "$T"`
# refused a run of spaces while `add-phase "$T"` and `add "$T"` wrote the same
# string verbatim. `_branch.slugify` derives the branch name from a phase title,
# which is the argument for checking `--rename` read one door earlier.
#
# PER VERB, because the same positional is not the same field. `args.title` is the
# TITLE for `add` and `add-phase` and the ID for `cancel`, `scope` and `retarget` --
# an id is not prose, and `- ` in an id slot would mean reading an id off stdin,
# which is not a thing. So the door and the check follow the verb, exactly as
# `VERB_FLAGS` does one question over.
#
# IT NEEDS ITS OWN LABEL. `option_dests()` leaves positionals out on purpose --
# there is no way to pass a positional to the wrong verb, so there is
# nothing to refuse -- so a message about this one cannot name a `--flag` that does
# not exist -- `--title` in particular is REFUSED by argparse, and `rn4` pins that.
PROSE_POSITIONAL = {"add": "title", "add-phase": "title", "bug-add": "title"}
_POSITIONAL_LABEL = {"title": "the <title> argument"}


def prose_labels(verb):
    """{dest: what to CALL it} for every prose value `verb` carries.

    The flags name themselves off the parser; the positional cannot, and the
    label is what a refusal has to say instead of inventing a flag.
    """
    labels = option_dests()
    out = dict((dest, labels[dest]) for dest in PROSE_FLAGS if dest in labels)
    positional = PROSE_POSITIONAL.get(verb)
    if positional:
        out[positional] = _POSITIONAL_LABEL[positional]
    return out


def read_brief(value, flag, stream=None):
    """(text, from_stdin, error) -- the value, off stdin when `value` is `-`.

    ONLY THE TRAILING NEWLINES ARE DROPPED, and only those. A heredoc always ends
    in one and nobody means it as part of the brief; a trailing SPACE, by contrast,
    is a character the operator typed, and the operator's words go into
    the manifest unchanged. That restraint is also what makes this route a real
    escape from the check above -- text that comes in this way comes in verbatim,
    so an operator whose brief genuinely holds one of the shapes has somewhere to
    put it.

    `flag` RIDES EVERY MESSAGE. One route now serves every flag in
    `PROSE_FLAGS`, and a refusal naming `--description` to somebody who typed
    `--reason` is a refusal that sends them looking at the wrong argument.
    """
    if value != "-":
        return value, False, None
    src = stream if stream is not None else sys.stdin
    try:
        text = src.read()
    except Exception as exc:                  # a closed or unreadable stdin
        return None, True, ("[audit-task] %s - was given and stdin "
                            "could not be read: %s" % (flag, exc))
    text = text.rstrip("\n")
    if not text.strip():
        return None, True, (
            "[audit-task] %s - was given and stdin held no text, so "
            "there is nothing to write -- and a value silently written "
            "empty is the fault this route exists to fix, one step further on. "
            "Pipe the text in, or use a heredoc:\n"
            "    ... %s - <<'BRIEF'\n"
            "    the text, backticks and all\n"
            "    BRIEF" % (flag, flag))
    return text, True, None


# The three shapes a substituted backtick span leaves on its own, wherever it sat:
# at the start (a leading space), between two words (two spaces in a row), or at
# the end (a trailing space). The other shapes are just as often code quoted into
# prose, which is why only these are named as likely substitution.
_SUBSTITUTION_SHAPES = ("a run of spaces inside a sentence",
                        "whitespace before the first word",
                        "whitespace after the last word")


def brief_gap_refusal(flag, what, excerpt, rel_start, rel_end):
    """The refusal for a prose flag that reached argv with a hole in it.

    THE ROUTE AND THE MARKED SPAN, AND ONE LINE OF CAUSE. It used to carry every
    reason in full and ran to ten lines, so the three lines that are the repair
    sat inside a paragraph a terminal wrapped to most of a screen. What stays is
    what the reader acts on: the heredoc to retype (its word quoted, because an
    unquoted one expands the body the way the double quotes did), the exact span
    that matched, and what that span most likely is.

    IT NAMES WHAT MATCHED, NOT A CAUSE THE CHECK NEVER TESTED FOR. The shapes are
    whitespace adjacency and no backtick, and a nested ternary passed through a
    list-form call with no shell anywhere trips the same one. So substitution is
    named as LIKELY only for the shapes it leaves on its own - a leading, a
    doubled or a trailing space - with a pointer at the shell's own stderr, which says
    `command not found` for every span it ran; for the rest the line says the
    check cannot tell substitution from code quoted into the brief.
    """
    seen_line, mark_line = _marked_excerpt(excerpt, rel_start, rel_end)
    if what in _SUBSTITUTION_SHAPES:
        cause = ("  Likely COMMAND SUBSTITUTION: inside double quotes the shell ran "
                 "a backtick span and left its output (nothing) here - its stderr "
                 "above will say `<word>: command not found`.")
    else:
        cause = ("  The check cannot tell COMMAND SUBSTITUTION of a backtick span "
                 "from code quoted straight into the brief; if the marked span is "
                 "what you meant, stdin writes it verbatim.")
    return (
        "[audit-task] %s carries %s -- refused, nothing written. Pass it on stdin "
        "(quote the word):\n"
        "    ... %s - <<'BRIEF'\n"
        "    the text, backticks and all\n"
        "    BRIEF\n"
        "%s\n"
        "%s\n"
        "%s" % (flag, what, flag, seen_line, mark_line, cause))


def stdin_gap_note(flag, what, excerpt, rel_start, rel_end):
    """The NOTE for prose that arrived on stdin already carrying a gap.

    A NOTE AND NOT A REFUSAL, and that is a decision rather than an omission.
    The stdin route is the door out of a false positive: text arriving this way
    is written exactly as it was typed, whatever shape it holds, because a guard
    with no door is the guard this repository has three fault entries about and
    which was routed around every time.

    BUT SILENCE THERE LEFT ONE MEASURED HOLE. `--description - <<BRIEF` with an
    UNQUOTED heredoc word expands its body exactly as double quotes do, so the
    shell eats the clause BEFORE this reads it -- and the route advertised as
    the repair delivers the damaged text with exit 0. Refusing would close the
    door; saying nothing left the one case where the hole bites indistinguishable
    from a brief somebody meant. So the run continues and the reader is told, at
    the moment the evidence exists, with the two readings side by side.
    """
    seen_line, mark_line = _marked_excerpt(excerpt, rel_start, rel_end)
    return (
        "[audit-task] note: the text on stdin for %s carries %s.\n"
        "%s\n"
        "%s\n"
        "  It is being written VERBATIM, because stdin is the way out of a "
        "false positive and a guard with no door gets routed around -- so if "
        "the marked span is what you meant, nothing here is wrong.\n"
        "  But if you wrote the heredoc word UNQUOTED (`<<BRIEF`), the shell "
        "expanded the body exactly as double quotes would and the clause was "
        "already gone before this read it. Quote it (`<<'BRIEF'`) and run "
        "again." % (flag, what, seen_line, mark_line))


def stdin_contest_refusal(claiming, flags):
    """The refusal for more than one flag claiming `-` in one call.

    STDIN IS ONE STREAM, and more than one flag on this parser can ask for it:
    `add-phase` takes `--description` and `--outcome`, `retarget` takes those two
    and `--rename`. Whichever the code happened to resolve first would get the
    whole stream and the others would get nothing -- one operator's brief written
    into another field, verbatim, with a journal row attesting it.

    NAMING THE COMPETITORS IS THE MESSAGE. The caller has to choose which flag
    the stream belongs to, and they cannot choose between flags nobody listed.
    """
    return (
        "[audit-task] %s each claim stdin with `-`, and stdin is one stream -- "
        "whichever was read first would take the whole of it and the rest would "
        "get nothing. Refused before reading, so nothing was consumed. Pass ONE "
        "of them as `-` and give the others their text on the command line "
        "(quote it), or make two calls."
        % (" and ".join(flags.get(d, d) for d in claiming),))


def _free_text_root(args):
    """The checkout root a prose value is judged against, or None.

    `resolve_basis`, the doors' own answer, asked early: this runs before any
    door has moved a lone positional into `args.manifest`, so for those verbs
    the root is the one `$CLAUDE_PROJECT_DIR` or the cwd names. None leaves the
    home-directory shapes judged and only the checkout-root shape unasked."""
    try:
        return resolve_basis(args)["root"]
    except Exception:
        return None


def resolve_briefs(args, out, stream=None):
    """The exit code the run must stop on, or None to carry on.

    ONE PLACE, AND BEFORE THE LOCK. Every flag in `PROSE_FLAGS` is written
    straight into the manifest by the verb that reads it, so a check living
    inside any one verb is a check the others do not have -- so this validates
    the whole class in one place rather than once per flag. Before the lock
    because a call refused here must not cost a lock, a journal row or a
    rollback.

    ONLY THE FLAGS THIS VERB READS CAN GET HERE. `misplaced_flag_refusal` has
    already run, so a prose flag carrying a value is one the verb will write --
    which is also what makes the stdin contest below exact: the flags competing
    for the stream are the flags that would each have used it.

    WHY THE STDIN ROUTE IS NOT REFUSED. The evidence the check reads is that a
    shell handled the text, and the whole worth of refusing is that the way out
    of a false positive is the route the caller should be using anyway. Refusing
    here too would take that way out away and leave prose that genuinely
    contains one of the shapes no way into the manifest at all. `stdin_gap_note`
    is what stops that being silence.

    A MACHINE PATH IS REFUSED HERE TOO, by `_journal_io.check_free_text`, and on
    both routes: the text lands verbatim in a committed manifest and its journal
    row, so the one door every prose flag passes is where it is asked, before
    the lock, the write or the row. A finding batch read off a file never passes
    this door, so `_finding_problems` asks the same check of its text.

    An EMPTY value stays legal, on the same reasoning read the other way: a task
    with no description shows as having none, in the manifest and on every
    surface that renders it, so it is not the silent loss this is about. What is
    refused is prose that still READS complete and is not.
    """
    flags = prose_labels(args.command)
    args.stdin_notes = []
    carried = [dest for dest in flags
               if isinstance(getattr(args, dest, None), str)
               and getattr(args, dest)]
    claiming = [dest for dest in carried if getattr(args, dest) == "-"]
    if len(claiming) > 1:
        # BEFORE THE READ, not after: a contest resolved by reading would have
        # already drained the stream, so a caller who fixed the call and piped
        # the same heredoc again would be piping into a closed door.
        out(stdin_contest_refusal(claiming, flags))
        return E_USAGE
    root = _free_text_root(args) if carried else None
    for dest in carried:
        flag = flags[dest]
        text, from_stdin, error = read_brief(getattr(args, dest), flag, stream)
        if error:
            out(error)
            return E_USAGE
        setattr(args, dest, text)
        # AFTER THE READ, so the stdin route is judged too: unlike a shell gap,
        # a machine path is no false positive stdin is the way out of - the text
        # arrives verbatim either way, and verbatim is what would be committed.
        machine = _journal_io.check_free_text(root, flag, text)
        if machine:
            out("[audit-task] " + machine)
            return E_USAGE
        gap = shell_eaten_gap(text)
        if not gap:
            continue
        if from_stdin:
            # COLLECTED, NOT PRINTED -- an earlier version printed here directly:
            # this runs BEFORE dispatch and wrote three human lines to the same
            # stream the verb then writes its JSON to, so `--json` came back as
            # prose followed by an object and `json.load` raised on line 1. Every
            # other advisory in these verbs is DATA in JSON mode -
            # `filesNotOnDisk`, `testsAddNamingNoFile` - and this is now too.
            # The human branch prints it below, once, in the same order.
            args.stdin_notes.append(stdin_gap_note(flag, *gap))
            continue
        out(brief_gap_refusal(flag, *gap))
        return E_USAGE
    if not args.as_json:
        for note in args.stdin_notes:
            out(note)
    return None


# A COMMAND OR A TEST NAME IS STORED VERBATIM TOO, so it passes the same
# machine-path door as prose. Not on `PROSE_FLAGS`: none of these reads stdin
# or meets the shell-gap check, and each is a list a repeated flag fills.
_VERBATIM_LIST_FLAGS = (("gate", "--gate"), ("gate_set", "--gate-set"),
                        ("verified_by", "--verified-by"))


def resolve_verbatim_values(args, out):
    """The exit code the run must stop on, or None to carry on.

    Before the lock, like `resolve_briefs`: a gate command or a test name
    holding a machine path lands in the committed plan and its journal row as
    typed, so it is refused by `_journal_io.check_free_text` before anything
    is written. `misplaced_flag_refusal` has already run, so every value here
    is one the verb would write."""
    carried = [(flag, value) for dest, flag in _VERBATIM_LIST_FLAGS
               for value in (getattr(args, dest, None) or [])
               if isinstance(value, str) and value]
    if not carried:
        return None
    root = _free_text_root(args)
    for flag, value in carried:
        machine = _journal_io.check_free_text(root, flag, value)
        if machine:
            out("[audit-task] " + machine)
            return E_USAGE
    return None


def stdin_notes_key(args):
    """`{"stdinNotes": [...]}` for a verb's `--json` block, or `{}`.

    ONE DEFINITION, EVERY JSON BRANCH, spelled the way `result.update(jres)`
    beside it already is. An advisory a human is told and a machine is not is an
    advisory two consumers disagree about, and the key is absent rather than
    empty when there is nothing to say - which is what lets a reader tell "no
    note" from "this release does not have them".
    """
    notes = list(getattr(args, "stdin_notes", None) or [])
    return {"stdinNotes": notes} if notes else {}


# --- the refusals and report lines more than one verb spends ------------------
# Not a "helpers" pile: each of these exists because TWO call sites would
# otherwise spell one fact, and the file already carries a note about what that
# costs (`_journal_row`: two verbs, two drifted copies, neither visible from the
# row that was written).
def _gate_contradiction(args):
    """The refusal line for `--gate` with `--gate-clear`, or None.

    ONE SENTENCE, THREE VERBS. `add`, `scope` and `seed` all take both flags
    off the same global parser and the rule is one rule about one field: two
    answers to one question, and guessing which the caller meant is how a task
    ends up gated on a command nobody asked for. `scope` and `retarget` each
    carried their own copy of the sentence; `add` needed a third when it
    learned to read the flag, and three copies of a refusal is how one of them
    eventually stops matching the other two.

    RETARGET ASKS THE WIDER VERSION, `_retarget_gate_contradiction`, NOT THIS
    ONE -- `gate_set` and `gate_drop` are declared on the shared parser but
    live in `VERB_FLAGS["retarget"]` alone, and `vf6` (the call-graph closure
    the manifest test suite derives `VERB_FLAGS` against) would read a call to
    a FOUR-flag version here as every verb reaching all four fields, which
    none but `retarget` actually may. Two functions, not one parametrized by a
    caller nobody passes a different value from, is what keeps `add`, `scope`
    and `seed`'s derived flag sets equal to their declared ones.

    Every caller asks it in the SAME POSITION -- under the lock, after the target
    has been resolved and before anything is mutated -- so the order a caller
    meets its refusals in does not depend on which verb it typed.
    """
    if args.gate and args.gate_clear:
        return ("[audit-task] --gate and --gate-clear say opposite things about "
                "the same field -- pass one")
    return None


def _retarget_gate_contradiction(args):
    """The refusal line for two of `--gate` / `--gate-clear` / `--gate-set` /
    `--gate-drop` together, or None -- `retarget`'s own superset of
    `_gate_contradiction`, for the reason that function's docstring gives.
    """
    present = [flag for flag, given in (
        ("--gate", bool(args.gate)),
        ("--gate-clear", bool(args.gate_clear)),
        ("--gate-set", args.gate_set is not None),
        ("--gate-drop", bool(args.gate_drop)),
    ) if given]
    if len(present) > 1:
        return ("[audit-task] %s say opposite things about the same field -- "
                "pass one" % " and ".join(present))
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


def _unchanged(args, out, ident):
    """The no-op answer of a correcting verb: exit 0, nothing written - one JSON
    object under `--json`, because a caller parsing stdout must never meet prose
    on a path that succeeded."""
    if args.as_json:
        result = {"ok": True, "changed": False, "id": ident, "written": []}
        result.update(project_basis_key(args))
        out(json.dumps(result, indent=2, sort_keys=True))
    else:
        out("[audit-task] %s already reads that way -- nothing written" % (ident,))
    return 0


def _gate_directory_notes(project, entries, meta):
    """A WARNING line for each gate entry that is a DIRECTORY rather than a command.

    One token, no `meta.buildCommands` key (`key` or `key:project`), and a
    directory under the project: an entry like that names no command, so the
    gate either fails to run or runs whatever the shell makes of a path. A
    command that merely MENTIONS a directory (`pytest tests/`) is several tokens
    and is left alone. Warned, never refused - the entry is legal JSON and the
    caller may be about to create a script of that name.
    """
    build = (meta or {}).get("buildCommands") if isinstance(meta, dict) else None
    notes = []
    for entry in entries or []:
        token = entry.strip() if isinstance(entry, str) else ""
        if not token or len(token.split()) != 1:
            continue
        if isinstance(build, dict) and (token in build
                                        or token.split(":", 1)[0] in build):
            continue
        if os.path.isdir(os.path.join(project, token)):
            notes.append("WARNING: gate entry %r is a directory in the project "
                         "tree, not a command or a meta.buildCommands key - it "
                         "names nothing to run" % (token,))
    return notes


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


def _not_on_disk_note(project, missing):
    """The `files` entries nothing answered for, and WHERE nothing was found.

    It used to name the path alone, once per path. Read from a linked worktree
    whose plan lives in another checkout, that was the only line in the whole
    report that touched on a tree at all -- and it was the one line that could
    have said which tree had been searched and did not.

    THE DIRECTORY RIDES THE SENTENCE, NOT EACH PATH. An advisory that repeats a
    constant per file is the shape an operator learns to skip, which is a fault
    this plan already carries once; the paths are a list on the one line instead.

    AND IT NAMES BOTH READINGS RATHER THAN GUESSING ONE. The line was `(new
    files?)`, which is a question with an implied answer -- and it stood in for
    three different situations at once: a file the task will author, a scope
    resolved against a root that is not the one these paths are relative to, and
    a string that was never a path at all. The third is a refusal now
    (`_files_refusal`), so two are left; the harmless one is the likelier and
    that is exactly why guessing it was wrong, since the operator who needs this
    line is the one in the other case. Both are stated, the legal one first,
    because a declaration ahead of the file is the workflow this note must not
    make anybody doubt.
    """
    if not missing:
        return None
    return ("  note: nothing on disk answers for %s, searched under %s. Either "
            "this task will author them -- declaring a file before it exists is "
            "how a red-first task names its case, and nothing here refuses it -- "
            "or that directory is not the root these paths are relative to, "
            "which is the reading to check when you meant to name files that "
            "already exist." % (", ".join(missing), project))


def _readiness_lines(waiting, tid):
    """The sentences `add` and `scope` both print about whether a task can run now.

    Shared because the `/audit:run <id>` handoff is a spelling a reader COPIES,
    and a second copy of it is the shape this repo's own cautionary tale is about
    (one formatter, three implementations, two of them disagreeing).
    """
    if waiting:
        return ["  waiting on: %s" % ", ".join(waiting)]
    return ["  ready now -- /audit:run %s" % tid]


# --- widening a scope that has already governed something ----------------------
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

# ...AND `tests.gate` IS NOT ONE OF THEM, BECAUSE IT IS NOT A SCOPE CLAIM.
# Every field above is graded BACKWARDS against work already recorded, which is
# why only growth is safe there. `tests.gate` is read FORWARDS and nowhere else:
# `run-test-gate` builds the NEXT run's steps from it, and nothing already
# written is re-read through it -- `_evidence_io.row_for` puts the commands a run
# ACTUALLY executed on its row, and `_evidence_io.pointer_for` caches identity,
# verdict and time. So a gate that moves in either direction, `--gate-clear`
# included, leaves every recorded row and every cached verdict saying exactly
# what it said before. The hand edit this verb exists to replace was measured
# live on this very field: a Python one-liner into a phase shard, three separate
# times, because the verb refused.
#
# NOT NARROWED TO "A STARTED TASK WITH NO RECORDED GREEN RUN", and that narrower
# spelling is refused rather than missed. A task holding a green pointer over a
# gate too wide to be worth re-running is the case that costs the most -- the
# next attempt pays for the wide gate, and the green pointer is the reason nobody
# re-scopes it -- so a permission stopping at the green row would refuse exactly
# the calls it exists for. A recorded green run is evidence about a measurement
# that HAPPENED; it says nothing about the one that comes next.
#
# `tests.gateBasis` RIDES THE SAME PERMISSION because it is the same event seen
# from one side: it records that a caller NAMED these commands, and it is written
# by the one branch that writes the gate. A row saying the gate now has an author
# cannot re-judge a commit for the reason the paragraph above gives about the gate
# itself, and leaving it out of this tuple would make the guard refuse exactly the
# call the permission was written for.
_FORWARD_ONLY = ("tests.gate", "tests.gateBasis")


def _gate_rows(changes):
    """The rows in `changes` that move a forward-only field."""
    return [row for row in changes if row["field"] in _FORWARD_ONLY]


def _grown_rows(changes):
    """The rows in `changes` that are NOT forward-only.

    THE COMPLEMENT, not a second list of names. Read as `_WIDENABLE` membership
    this would silently drop any field a future entry lets through, and the two
    callers -- the report's `WIDENED` line and the journal's widening row -- would
    then announce a set smaller than the one the guard accepted. Every row
    reaching either caller has already passed `_narrowings`, so what is left here
    is by construction a widening.
    """
    return [row for row in changes if row["field"] not in _FORWARD_ONLY]


def _started(task):
    """True when this task's scope has already governed something.

    TWO SIGNALS, EITHER ONE ENOUGH, and they are genuinely independent rather
    than one fact spelled twice. The orchestrator sets `in_progress` and
    increments `attempts` in the same step, but a task that ran, failed and was
    put back to `pending` carries the count with no status left to show for it,
    and a task moved to `blocked` before its first spawn carries
    the status with no count. Reading only the status is how the guard here was
    written the first time, missing the count-only case; it now reads both
    signals to catch it.
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

    `_FORWARD_ONLY` IS NOT BLOCKED IN EITHER DIRECTION, and it is a different
    permission rather than a wider one. Append-only is safe because a backwards
    grading reads the field; `tests.gate` has no backwards reading at all, so
    there is no direction to protect -- see its own note beside the constant.

    Every other field is refused because none of them has a safe direction:
    `risk` and `tests.mode` REPLACE a value the attempt ran under, `description`
    rewrites the question the outcome answered, and a ref list that GROWS blocks
    a task that has already started -- growth is not harmless there, which is why
    "append-only" is a rule about two named fields and not about the word.
    `tests.mode` is the near neighbour to keep apart from `tests.gate`: the mode
    is what an attempt was GRADED under and is quoted back by the review, while
    the gate is only the list of commands the next run shells out to.
    """
    out = []
    for row in changes:
        was, now = row.get("from") or [], row.get("to") or []
        if row["field"] in _FORWARD_ONLY:
            continue
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

    THE `attempts` SENTENCE IS KEPT VERBATIM, because `commands/task.md`
    quotes it, and it is still true of every change this arm
    refuses -- the outcome describes work judged under the current scope, and
    these changes would make that record describe something else. The LAST
    sentence changed once widening became possible: cancel-and-re-add is no
    longer the only way
    out, so a refusal that still said it was would send an operator to the
    expensive route for a change the verb now takes.

    THAT SENTENCE IS ALSO WHY `tests.gate` NO LONGER ARRIVES HERE. It grades a
    change against a RECORD, and a gate is not in any record: an evidence row
    holds the commands that ran and the pointer holds the run's id, verdict and
    time, so this head would be claiming a harm that cannot happen. The tail is
    written to match -- `_narrowings` drops the field before the blocker list is
    built, so no call reaches this function naming only the gate.
    """
    attempt = _mio.recorded_attempt(task)
    status = (task or {}).get("status")
    if status == "done":
        # A THIRD HEAD FOR THE SETTLED CASE. A done task is not running and may have no attempt
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
            "`--gate` and `--gate-clear` are still taken too, whichever way they "
            "move, because a gate is what the NEXT run measures and no record "
            "was graded against it. For anything else, cancel the task and add "
            "the work again."
            % (head, "; ".join(blockers)))


# --- project resolution --------------------------------------------------------
# An ALIAS, not a copy. The body moved into `_panel_write` when `set-priority.py`
# needed the same answer: a second command deriving "which project owns this
# manifest" by its own walk is a second answer, and the two would drift on exactly
# the markerless case. The name stays here because this file spells
# it unqualified and its suite asks for it by hand.
_project_of_manifest = _panel_write.project_of_manifest


def resolve_basis(args):
    """{"root", "basis", "why"}: which root owns the journal, the lock, the
    config and the file notes -- and the row of `_panel_write.PROJECT_BASES`
    that chose it.

    Keying this off the cwd while the manifest was explicitly named
    wrote the `task.add` journal row into the CWD repo's journal -- the exact
    class audit-usage's resolve_ledger solved ("When a manifest was named,
    search upward from IT"). The order below IS the table's order, top-down,
    and the table carries the clause each row is chosen for, so this function
    holds no sentence of its own to disagree with the one an operator reads.
    """
    if args.project_dir:
        return _panel_write.project_basis(os.path.abspath(args.project_dir),
                                          "--project-dir")
    if args.manifest:
        return _panel_write.project_basis(_project_of_manifest(args.manifest),
                                          "manifest argument")
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return _panel_write.project_basis(os.path.abspath(env),
                                          "$CLAUDE_PROJECT_DIR")
    return _panel_write.project_basis(os.path.abspath(os.getcwd()),
                                      "the working directory")


def _manifest_from_positional(args):
    """For a verb that takes no id: a lone positional IS the manifest.

    CALLED BEFORE `_resolve_project`, never after. The named manifest is one
    of the rows `resolve_basis` chooses a root by, so a door that moved the
    positional into `args.manifest` only after resolving had already fallen
    through to `$CLAUDE_PROJECT_DIR` or the cwd: the manifest was written
    where it was named while the lock, the config, the evidence lookup and
    the journal row went to another tree.
    """
    if args.title and not args.manifest:
        args.manifest = args.title
        args.title = ""


def _resolve_project(args):
    """The root alone, for the seven doors that only need somewhere to write."""
    return resolve_basis(args)["root"]


def project_basis_key(args):
    """`{"projectBasis": {...}}` for a verb's `--json` block, off the answer
    `_under_lock` already computed.

    THE KEY IS `_panel_write`'S, so this command and `set-priority.py` cannot
    ship two shapes of one fact. What is local is only WHERE the answer is kept:
    `_under_lock` leaves it on `args` because it costs a `git rev-parse`, and a
    second ask per verb could contradict the line already printed. `{}` when
    nothing put it there -- a verb reached without the shared door has resolved
    no root, and an invented one is the guess this whole pair exists to stop.
    """
    info = getattr(args, "project_basis", None)
    if not info:
        return {}
    return _panel_write.project_basis_key(info)


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
    """`P2 (in_progress)`, off the DERIVED status, naming sign-off due: a phase whose
    work is finished reads in_progress too, and a list of open phases that did not
    say which of them only await a verdict would send a task into one."""
    status = _mio.effective_phase_status(ph)
    if _mio.signoff_due(ph):
        return "%s (%s, sign-off due)" % (ph.get("id"), status)
    return "%s (%s)" % (ph.get("id"), status)


def _signed_off_refusal(ph, what):
    """The refusal for a phase whose sign-off is on record, or None.

    Awaiting its merge, the phase still reads in_progress, but the verdict on
    record reviewed it as it stands and `what` would change it after the fact."""
    pid = ph.get("id")
    if _mio.signoff_recorded(ph):
        return ("[audit-task] phase %s is signed off (%s) -- %s would change what "
                "that verdict reviewed. It reads done once %s lands; pick an open "
                "phase, or create a new one with /audit:phase add."
                % (pid, ph["review"]["status"], what, ph.get("branch") or "its merge"))
    return None


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


def _resolve_phase(assembled, want, out, branch=None, basis=None,
                   what="a task added now"):
    """The target phase dict, or an int exit code after printing why not.

    `branch` is the one checked out beside the manifest. With several phases
    running - several developers, each on a phase branch of their own - the
    current phase is the one whose recorded `branch` is checked out, which is the
    only reading that cannot land a task in someone else's phase. WHY that phase
    was chosen is appended to `basis` rather than printed here, so a `--json`
    caller keeps one parseable object and a human caller prints it."""
    phases = [p for p in (assembled.get("phases") or []) if isinstance(p, dict)]
    if want:
        for ph in phases:
            if ph.get("id") == want:
                if _mio.effective_phase_status(ph) == "done":
                    out("[audit-task] phase %s is done -- done phases are "
                        "immutable history. Pick an open phase, or create a "
                        "new one with /audit:phase add." % want)
                    return E_USAGE
                refusal = _signed_off_refusal(ph, what)
                if refusal:
                    out(refusal)
                    return E_USAGE
                return ph
        reserving = _reserving_proposal(assembled, want)
        if reserving:
            out(_reserved_refusal(want, reserving))
            return E_USAGE
        out("[audit-task] no phase %s in the manifest; phases: %s"
            % (want, ", ".join(_phase_label(p) for p in phases) or "(none)"))
        return E_USAGE
    # The default is a RUNNING phase, by the plan gate's own rule
    # (`_mio.phase_running`). A merged phase never is, whatever its `status` still
    # says - landing a task on it would reopen a branch this verb cannot run
    # anything on - and neither is one only awaiting sign-off: it reads in_progress
    # on the page with nothing left to do, and a plan with finished phases waiting
    # on a verdict would otherwise demand --phase on every add. `inProgress` in the
    # basis keeps its name for the `--json` reader; it lists the running phases.
    inprog = [p for p in phases if _mio.phase_running(p)]
    if len(inprog) == 1:
        return inprog[0]
    if not inprog:
        openp = [p for p in phases
                 if _mio.effective_phase_status(p) not in _mio.TERMINAL]
        out("[audit-task] no running phase to default to -- pass --phase. "
            "Open phases: %s"
            % (", ".join(_phase_label(p) for p in openp) or "(none)"))
        return E_USAGE
    mine = [p for p in inprog if branch and p.get("branch") == branch]
    if len(mine) == 1:
        if basis is not None:
            basis.append({"phase": mine[0].get("id"), "branch": branch,
                          "inProgress": [p.get("id") for p in inprog],
                          "why": "the running phase whose branch is checked out"})
        return mine[0]
    out("[audit-task] --phase required -- %d phases are running: %s"
        % (len(inprog), ", ".join(p.get("id") or "?" for p in inprog)))
    return E_USAGE


def _allocate_id(assembled, phase_id, suffix=None):
    """`<phaseId>.<n>[-suffix]`, n = highest existing number + 1, over the
    WHOLE assembled manifest (a misfiled task still counts) plus every
    still-parked proposal payload (reserved ids stay reserved). Gaps are
    history: P2.1 + P2.3 allocate P2.4, never P2.2 again.

    `suffix` is the branch's (`_id_shape.suffix_here`): off the development
    branch two branches adding a task to one phase would otherwise both mint
    the next number. A suffixed sibling's number counts like any other, so the
    development branch continues past it after a merge."""
    reserved = []
    # The manifest's own tasks are walked by `_id_shape`; the proposal payloads
    # below cannot be, because a parked payload's phase is NOT in
    # `manifest["phases"]` yet — reserving its ids is the whole point of reading
    # it separately.
    for prop in (assembled.get("proposals") or []):
        if not isinstance(prop, dict) or prop.get("status") != "proposed":
            continue
        payload = prop.get("payload")
        pphase = payload.get("phase") if isinstance(payload, dict) else None
        if isinstance(pphase, dict):
            reserved.extend(t.get("id") for t in (pphase.get("tasks") or [])
                            if isinstance(t, dict))
    return _id_shape.next_task_id(assembled, phase_id, suffix, extra_ids=reserved)


def _mint_suffix(mpath, assembled):
    """The branch suffix an id minted beside `mpath` carries now, or None."""
    return _id_shape.suffix_here(os.path.dirname(os.path.abspath(mpath)), assembled)


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


def _settle(assembled, only=None):
    """Store what the derivations answer, in `assembled`, and return what moved.

    `_mio.derived_disagreements` is the question; this is the one place a verb applies
    its answer, so sign-off, a close and `settle` store the same value for the
    same reason. `only` is a set of `(kind, id)` pairs naming the records this
    write changed an input of, or None for every record the plan holds - a verb
    settles what it touched and leaves the rest of a stale plan to `settle`,
    whose run is the one a reader asked for.
    """
    rows = [r for r in _mio.derived_disagreements(assembled)
            if only is None or (r["kind"], r["id"]) in only]
    phases = dict((p.get("id"), p) for p in (assembled.get("phases") or [])
                  if isinstance(p, dict))
    bugs = dict((b.get("id"), b) for b in (assembled.get("bugs") or [])
                if isinstance(b, dict))
    for row in rows:
        holder = (phases if row["kind"] == "phase" else bugs).get(row["id"])
        if holder is not None:
            holder[row["field"]] = row["derived"]
    return rows


def _settled_lines(rows):
    """One report line per stored value `_settle` moved, with its basis."""
    return ["  stored %s %s.%s: %s -> %s (%s)"
            % (r["kind"], r["id"], r["field"], r["stored"], r["derived"], r["basis"])
            for r in rows]


def _write_add(project, mpath, raw_index, assembled, phase_id, files_changed,
               index_fields=()):
    """Persist the patched manifest into whichever layout it is stored in.
    SINGLE FILE: write the assembled dict; it IS the file. SHARDED: the
    touched phase's shard, and the index only when fileIndex changed --
    _panel_write._write_back's footprint, for its reasons. Returns the
    project-relative paths written (shard first, index-precedent order).

    `index_fields` names top-level INDEX keys this write changed beside the
    phase (`bugs`, when a close stores a linked bug's derived status): each is
    copied from `assembled` and the index is written. `phase_id` None writes no
    shard, for a write that touched the index alone."""
    if not _mio.is_sharded(raw_index):
        _panel_write._atomic_write_json(mpath, assembled)
        return [_output.posix_rel(mpath, project)]
    base = os.path.dirname(os.path.abspath(mpath))
    by_pid = {p.get("id"): p for p in (assembled.get("phases") or [])
              if isinstance(p, dict)}
    written = []
    index_dirty = bool(files_changed) or bool(index_fields)
    if phase_id is None:
        idx = dict(raw_index)
        for key in index_fields:
            idx[key] = assembled.get(key)
        _panel_write._atomic_write_json(mpath, idx)
        return [_output.posix_rel(mpath, project)]
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
    # THE STUB IS A COPY, AND A COPY NOTHING REFRESHES GOES STALE. Until
    # `retarget --rename` existed no verb could change a mirrored key after the
    # split, so nothing here ever had to look. Measured on a sharded fixture the
    # moment one could: the shard carried the new title while the index went on
    # naming the phase by the one it was created with, which is the whole point
    # of a stub answered wrongly.
    #
    # THE PHASE'S STATUS IS ONE OF THOSE KEYS, which is the write
    # `reference/orchestrator.md` calls the status mirror and lists among the
    # index-lock writes. It was documented there, and in
    # `reference/manifest-conventions.md` as the thing `priority`'s index-only
    # rule rests on, while the writer copied identity alone -- so every reader of
    # the index was answered `None` about a phase that was running, and the
    # ordering argument for the layout rested on a key nothing wrote.
    #
    # COMPARED, NOT REWRITTEN, which is what keeps that from costing the layout
    # its point. The list is `_mio._STUB_KEYS` rather than a set spelled here,
    # and the index is dirtied only when a mirrored key actually MOVED -- so a
    # phase's own transition writes the index and the work inside it does not,
    # and two phase branches still touch one stub each.
    if "shard" in stub:
        for key in _mio._STUB_KEYS:
            if key in body and stub.get(key) != body.get(key):
                stub[key] = body[key]
                index_dirty = True
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
        for key in index_fields:
            idx[key] = assembled.get(key)
        # IDENTICAL BYTES ARE NOT A WRITE. A mirrored key or a field handed over
        # here can come back exactly as it was, and rewriting the index then
        # dirties nothing git can see while `written` - which the DIRTY note is
        # read off - says the index moved. So the bytes are compared first.
        if not _same_bytes(mpath, _mio.json_document(idx, 2)):
            _panel_write._atomic_write_json(mpath, idx)
            written.append(_output.posix_rel(mpath, project))
    return written


def _same_bytes(path, text):
    """Does the file at `path` already hold exactly `text`? False when unreadable.

    Read in text mode like the writer writes, so the line endings a platform's
    text mode translates compare as the same text they were written from."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read() == text
    except (OSError, UnicodeDecodeError):
        return False


# THE SECOND-ORDER TRAP `commit-task-work.py` DOES NOT CLOSE. That script
# refuses a task commit that stages the index, on purpose (two phases must be
# able to merge without meeting on one file) -- so a write here that dirtied
# BOTH the shard and the index leaves the index sitting uncommitted, and
# nothing said so at the moment it happened. A caller who commits the shard by
# hand and never runs the one script that lands the index alone produces a
# manifest that fails to validate AT that commit, because the index then names
# a task the checked-out shard does not carry -- reproduced in a scratch
# repository rather than assumed.
def _index_dirty_note(written, mpath, project, phase_id):
    """The note owed when THIS write left the shared index dirty beside the
    phase shard it also touched -- or None when this write is one file, not
    two (a single-file manifest, or a sharded write that never moved a
    mirrored key and never touched `fileIndex`).

    `written` ALREADY KNOWS THE ANSWER, so nothing further is asked of the
    manifest to tell: `_write_add`'s own docstring says shard first,
    index-precedent order, so the index sitting LAST behind a first entry is
    exactly what a dual write with the index looks like from here.

    NAMED HERE, NOT ONLY IN THE REFUSAL THAT FOLLOWS THE MISTAKE.
    `commit-task-work.py`'s own refusal already names `commit-manifest-
    index.py` -- but only once a caller has staged the index and been turned
    away for it, by which point a hand commit may already have carried the
    shard on alone. This is the same name at the moment the state is CREATED.
    """
    index_rel = _output.posix_rel(mpath, project)
    if len(written) < 2 or written[-1] != index_rel:
        return None
    return (
        "  the manifest index (%s) is now DIRTY alongside the shard this "
        "wrote, and a task commit will not carry it -- orchestrator.md step "
        "4c refuses to stage the index in a task commit on purpose, which is "
        "what lets two phases merge with no conflict there. Land it on its "
        "own, AFTER the shard it names is committed (the task commit carries "
        "the shard) - committed first, it records a plan that does not "
        "validate, and the command below refuses that:\n"
        "    python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/governance/commit-manifest-index.py\" "
        "%s %s" % (index_rel, mpath, phase_id))


def _index_dirty_key(note):
    """`{"indexDirtyNote": note}` for a verb's `--json` block, or `{}` --
    `stdin_notes_key`'s shape, so a machine reader tells "nothing to say" from
    "this release does not carry the key" the same way for both."""
    return {"indexDirtyNote": note} if note else {}


# THE PROMISE `reference/orchestrator.md` STATES FOR **run** AND THESE VERBS
# CROSS. "A phase run therefore touches only its own shard -- which is exactly
# why two phase branches merge without a manifest conflict" is true of a run:
# it stays on the phase it is executing. Every verb here takes a task or phase
# id from wherever the caller happens to be STANDING, and a write that lands in
# phase X's shard while the caller is on phase Y's branch is the exact merge
# conflict that sentence says the layout avoids -- reproduced live: same tree,
# two branches, one shard, a real conflict in the file the layout exists to
# keep conflict-free.
#
# A WARNING, NOT A REFUSAL. Naming it is the whole fix: the writer then knows
# to expect a merge, rather than being surprised by one when the branches
# meet. Nothing here is wrong enough to stop -- `run` and `next` still resolve
# and commit through their own branch machinery regardless of what this prints.
#
# NOT THE SAME SHAPE AS THE `commit-scope` invariant. That check starts from
# COMMITS the plan records (`task.commit`, a phase's merge) and asks what each
# one staged. This starts from a PATH -- the shard this write is about to touch
# -- and asks a containment question about a branch, never a commit the plan
# records anywhere.
def _phase_branch_note(git_root, phase, cwd=None, run=None):
    """The warning owed when this write lands in `phase`'s shard while the
    caller stands on a branch OTHER than the one recorded for it, or None
    when there is nothing to compare.

    SILENT WHEN THE PHASE RECORDS NO BRANCH AT ALL, and that was true of most
    of them the day this was measured against this project's own manifest:
    fewer than a fifth of its phases carried one, and every phase running
    that day carried none. A check keyed only on a populated `branch` is
    therefore silent across the whole of THIS repository's dogfood run --
    which is exactly where a wrong condition would have been noticed, so that
    silence is recorded here as a stated limit rather than discovered later.
    The alternative (deriving the expected branch from `_branch.compose` when
    none is recorded) was rejected: a composed name is a PREDICTION of what
    `run` would create, never a record of what git actually holds, and
    warning off a guess is the false-positive shape this repository's own
    fault register already has entries about.

    SILENT WHEN GIT CANNOT ANSWER, for the same reason one door over
    (`_panel_write.standing_elsewhere`): a missing git, a directory that is
    not a repository, or a worktree list git refuses to print leaves nothing
    to compare the recorded branch against, and a warning built on a guess is
    worse than none.
    """
    branch = (phase or {}).get("branch")
    if not branch:
        return None
    listing = _worktrees.list_worktrees(git_root, run=run)
    if listing["error"]:
        return None
    here = _worktrees.standing_in(listing["trees"], cwd or os.getcwd())
    standing = (here or {}).get("branch")
    if not standing or standing == branch:
        return None
    return (
        "  WARNING: phase %s is recorded on branch %s, and this write just "
        "landed from %s -- a DIFFERENT branch. The promise that a phase run "
        "touches only its own shard belongs to `run`, not to this verb: this "
        "call took an id from wherever you are standing, so phase %s's shard "
        "now holds edits made from two branches. Expect a merge conflict "
        "there when the two meet, rather than being surprised by one."
        % (phase.get("id"), branch, standing, phase.get("id")))


def _phase_branch_key(note):
    """`{"branchNote": note}` for a verb's `--json` block, or `{}` --
    `_index_dirty_key`'s shape, for the same reason."""
    return {"branchNote": note} if note else {}


# --- the journal ---------------------------------------------------------------
def _journal_cfg(config, mpath, project):
    """The journal config a CLI row is written AND read with - one answer, so a
    reader looking for the rows this file wrote looks where they were written.
    A project with a config keeps its own; one without gets `manifestPath` pinned
    to where the named manifest is, so the journal lands beside it."""
    return None if config else {"manifestPath": _output.posix_rel(mpath, project)}


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

    THE APPEND IS `append_from_cli`. `/audit:task` is run from Bash, and
    the journal file its append dirties was reported by `guard-bash-writes` as a
    shell write into the append-only trail on the next Bash command -- there was
    no claim on it, because the only writers that filed one were the hook (under
    the session id, which a script is never handed) and the panel.
    """
    mod = _panel_write._journalmod()
    if mod is None or not hasattr(mod, "append_from_cli_why"):
        return {"journaled": False, "journaledWhy": "unavailable"}
    # THE PLACEMENT RULE: the journal lands in a sane place INSIDE
    # the named manifest's tree -- never doubled, never outside. A project
    # with a config keeps its own answer (config=None -> audit-journal's
    # load_config resolves journal.dir/manifestPath/enabled exactly as
    # before). A project with NO config would get audit-journal's DEFAULT
    # manifestPath rel appended under the resolved root -- doubling the
    # layout, or conjuring docs/audit into a bare tree -- so the handed-over
    # config pins manifestPath to where the named manifest actually IS, and
    # the journal lands beside it (<manifest dir>/journal).
    cfg = _journal_cfg(config, mpath, project)
    try:
        written, why = mod.append_from_cli_why(project, {
            "action": action,
            # Persisted row: "/" separators regardless of platform, like every
            # other journal path (n3 pins it; Windows relpath says backslash).
            "target": _output.posix_rel(mpath, project),
            "summary": summary,
            "details": details,
            "actor": {"author": _panel_write._viewer(project,
                                                    config).get("author"),
                      "sessionId": os.environ.get("CLAUDE_CODE_SESSION_ID"),
                      "via": "cli"}}, config=cfg)
    except Exception as exc:
        written, why = False, exc
    return _panel_write.journal_block(project, written, why)


def _not_journaled_line(jres, what):
    """The report line for a row the trail did not take, WITH the reason the
    append gave - one word for every failure is the silence a reader cannot
    act on."""
    return ("  journal: the audit trail did NOT take %s (%s)"
            % (what, jres.get("journaledReason") or "no reason recorded"))


def _journal_add(project, config, mpath, task_id, phase_id, title, healed):
    """The `task.add` row: what was added, where, and what the write healed."""
    summary = "%s added to %s: %s" % (task_id, phase_id, title)
    if healed:
        summary += "; " + "; ".join(_panel_write._fmt_change(r) for r in healed)
    return _journal_row(project, config, mpath, "task.add", summary,
                        {"taskId": task_id, "phaseId": phase_id})


def _fields_of(rows):
    """The field names a scope row's summary lists, in the order they moved."""
    return ", ".join(row["field"] for row in rows)


def _scope_details(task_id, phase_id, rows, attempt):
    """The `details` block of a `task.scope` row, built where a case can read it.

    `_start_details`' reason, one verb over: `_journal_io` drops a key that is not
    on `DETAILS_KEYS` in SILENCE, so a row read back out of the trail looks the
    same whether the writer handed over an allow-listed block or one carrying an
    invented key beside it. Built here, the handover itself is what a case can
    compare against the allow-list.
    """
    details = {"taskId": task_id, "phaseId": phase_id, "changes": rows}
    if attempt is not None:
        details["attempt"] = attempt
    return details


def _journal_scope(project, config, mpath, task_id, phase_id, changes, task):
    """The `task.scope` row: which fields moved, to what, and under which attempt.

    `changes` is the allow-listed shape `_journal_io.DETAILS_KEYS` already
    carries - id/field/from/to per row - so the cascade spelling every other
    writer here uses is the one this reuses rather than inventing a `files` key
    the allow-list would drop in silence. `_journal_phase_add`'s note says what
    that costs: a field written, dropped, and believed.

    `attempt` IS A NEW KEY ON THAT ALLOW-LIST, and it passes the three
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

    A GATE CHANGE MID-RUN GETS ITS OWN ROW, in this row's shape and not a second
    invention: same action, same `details` keys, same `_attempt_phrase` dating,
    one event word swapped. It is a row of its own because `audit-journal list`
    prints the summary alone, and one summary can carry one event -- a gate
    folded into the widening's field list would be announced by the word
    `WIDENED`, which is exactly the claim a replaced gate does not support. The
    two rows answer two different questions a reader brings to a started task:
    which paths the scope gained, and which commands the next attempt will run.
    """
    attempt = _mio.recorded_attempt(task)
    if not _started(task):
        return _journal_row(
            project, config, mpath, "task.scope",
            "%s scoped in %s: %s"
            % (task_id, phase_id, _fields_of(changes)),
            _scope_details(task_id, phase_id, changes, attempt))
    # A DIFFERENT EVENT DESERVES A DIFFERENT SENTENCE. `audit-journal list`
    # prints the summary and nothing else, so a mid-run widening that read like
    # every other scope row would need `details` opened to be seen at all -- and
    # it is the row a reader is looking for.
    written = []
    for event, rows in (("WIDENED", _grown_rows(changes)),
                        ("GATE CHANGED", _gate_rows(changes))):
        if not rows:
            continue
        written.append(_journal_row(
            project, config, mpath, "task.scope",
            "%s %s in %s %s: %s"
            % (task_id, event, phase_id, _attempt_phrase(task),
               _fields_of(rows)),
            _scope_details(task_id, phase_id, rows, attempt)))
    # THE WORST ANSWER WINS. Every row above records part of one write, so a call
    # that got one row onto the trail and lost the other has NOT been journaled,
    # and reporting `journaled: True` would leave the missing half invisible.
    for res in written:
        if not res.get("journaled"):
            return res
    return written[0] if written else {"journaled": False,
                                       "journaledWhy": "nothing to record"}


def _journal_retarget(project, config, mpath, phase_id, changes):
    """The `phase.retarget` row: which of the phase's fields moved, and to what.

    `changes` again, for `_journal_scope`'s reason - the allow-list carries that
    shape and would drop an invented `testGate` key in silence.
    """
    fields = ", ".join(row["field"] for row in changes)
    return _journal_row(project, config, mpath, "phase.retarget",
                        "%s retargeted: %s" % (phase_id, fields),
                        {"phaseId": phase_id, "changes": changes})


def _journal_phase_add(project, config, mpath, phase_id, title, outcome,
                       branch=None):
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
    details = {"phaseId": phase_id}
    if branch:
        details["branch"] = branch
    return _journal_row(project, config, mpath, "phase.add", summary, details)


# --- readiness (report only) ---------------------------------------------------
def _waiting_on(assembled, node):
    """What `node` is still waiting on -- `_status_facts.unmet_refs`' answer for
    its id, looked up rather than recomputed.

    THIS WAS A THIRD COPY OF THE READINESS RULE, AND IT WAS THE ONE THAT
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
# A THIN ALIAS, NOT A COPY: `_manifest_phases.gate_entry_paths` is the SAME
# question `tests.add` is asked (`_rules.tests_add_path` above), asked of each
# whitespace-separated token in a gate entry instead of the leading one - and
# `run-test-gate.py`'s `--own` narrowing reads the identical function. Two
# entry points needing one answer could only have copied it before this moved;
# now both alias one body.
_gate_entry_paths = _phases.gate_entry_paths


# THIN ALIASES, NOT COPIES: `is_shared_key`, `path_scoped_sibling` and
# `repointed` moved to `_gate_derive.py` so a PHASE-level derivation and this
# TASK-level one share one body apiece rather than two that could drift. See
# that module for the (unchanged) docstrings.
_is_shared_key = _gate_derive.is_shared_key
_path_scoped_sibling = _gate_derive.path_scoped_sibling
_repointed = _gate_derive.repointed


def _failing_from_lookup(project, phase, run_id):
    """`(row, refusal)` for `--failing-from <run_id>` -- the evidence row a
    failed-first fix task derives its gate from, or the reason it cannot.
    Exactly one of the two is not `None`.

    THE RUNID IS LOOKED UP, NEVER PARSED. `_evidence_io.row_by_run` is the one
    lookup this project keeps for exactly this question, because the schema
    calls a runId opaque -- reading structure into one here would be a second,
    silently different answer to a question `row_by_run` already answers.

    THREE THINGS HAVE TO BE TRUE OF THE ROW, each refused by naming the actual
    value rather than a generic "no such run": it must EXIST (a mistyped runId
    is told there is no such run, never handed the ordinary derivation in
    silence); it must be scoped to THIS PHASE (a task's own run, or another
    phase's, cannot license a gate narrowed to suites this phase never ran);
    and it must carry `status: "failed"` (a fix task opened from a run that
    PASSED is not failed-first, and the sentence names the status the row
    actually holds, never merely "not failed").

    A RUN NOT AMONG THE READABLE ROWS IS NOT CALLED ABSENT when a ledger
    file could not be read in full: `_ledger_run`, the lookup `--caught` and
    `--basis-run` share, names that file instead, since the run may be on
    the line that read lost.
    """
    row, refusal = _ledger_run(
        project, "--failing-from", run_id,
        "a failed-first fix task names the phase run that failed")
    if refusal:
        return None, refusal
    phase_id = phase.get("id")
    if row.get("scope") != "phase" or str(row.get("phaseId")) != str(phase_id):
        subject = ("task %s" % row.get("taskId") if row.get("scope") == "task"
                  else "phase %s" % row.get("phaseId")
                  if row.get("scope") == "phase" else
                  "scope %r" % (row.get("scope"),))
        return None, (
            "[audit-task] --failing-from %s is %s's run, not phase %s's -- a "
            "fix task's gate can only be narrowed to suites THIS phase's own "
            "run named as failing" % (run_id, subject, phase_id))
    if row.get("status") != "failed":
        return None, (
            "[audit-task] --failing-from %s is not a FAILED run (status: %s) "
            "-- a failed-first fix task needs a red run to point its gate at"
            % (run_id, row.get("status")))
    return row, None


def _ordinary_task_gate(shape, owner, wide, build, add_paths, files, mode,
                        meta, phase):
    """The three ordinary defaults (`tests.add`, `files`, the phase's wide
    gate), gate-only's own suite-filtered arm included -- split out of
    `_task_gate` so a `--failing-from` call that cannot narrow anything falls
    through to EXACTLY this, with the reason it fell through said beside it
    rather than the phase's own gate handed back unexplained.
    """
    if shape is None:
        return wide, ("the phase's testGate, wide -- no sibling task in %s "
                      "declares a path-scoped gate entry to read this "
                      "project's spelling off" % (phase.get("id"),)), \
            "phase-no-spelling"
    if add_paths:
        return (_repointed(shape, build, add_paths),
                "narrowed to this task's tests.add paths, in %s's spelling"
                % (owner,), "tests.add")
    if files:
        if mode == "gate-only":
            suite_files = [p for p in files if _phases.is_suite_path(p)]
            if suite_files:
                return (_repointed(shape, build, suite_files),
                        "narrowed to this task's files, in %s's spelling"
                        % (owner,), "files")
            always = _phases.phase_gate_default(
                meta if isinstance(meta, dict) else {})["always"]
            if always:
                return (list(always),
                        "meta.phaseGate.always -- this task's files name no "
                        "suite path to narrow %s's gate at" % (owner,),
                        "gate-only-no-suite")
            passthrough = [e for e in shape
                          if _is_shared_key(e, build) or not _gate_entry_paths(e)]
            return (passthrough,
                    "%s's gate entries that name no path, carried through -- "
                    "this task's files name no suite path to narrow %s's gate "
                    "at" % (owner, owner), "gate-only-no-suite")
        return (_repointed(shape, build, files),
                "narrowed to this task's files, in %s's spelling" % (owner,),
                "files")
    return wide, ("the phase's testGate, wide -- %s is path-scoped but this "
                  "task names no file to point a gate at" % (owner,)), \
        "phase-no-paths"


def _task_gate_setup(phase, assembled):
    """`(wide, meta, build, shape, owner)` -- the pieces every arm past
    `--gate`/`--gate-clear` needs, shared by `_task_gate` and
    `_failing_from_task_gate` so the two keep exactly one copy of them rather
    than two that could drift.
    """
    wide = [g for g in (phase.get("testGate") or []) if isinstance(g, str)]
    meta = assembled.get("meta") if isinstance(assembled, dict) else None
    build = (meta or {}).get("buildCommands") if isinstance(meta, dict) else None
    shape, owner = _path_scoped_sibling(phase, build)
    return wide, meta, build, shape, owner


def _task_gate(args, phase, assembled, add_paths, files, mode="gate-only"):
    """`(gate, basis, source)` -- the new task's `tests.gate`, the sentence
    saying which of the three defaults produced it, and the ONE WORD that says
    the same thing to a rule.

    THE WORD IS WHY THE SENTENCE IS NOT ENOUGH. The basis is printed once and
    thrown away, so a narrow gate and a wide one read the same way in the
    manifest afterwards -- and the validator's line about a task carrying its
    phase's gate verbatim could not tell "this project records no path-scoped
    spelling" from "this task named no file", which are the two arms that both
    end in the wide gate and want opposite answers. It offered prose in the
    task's `description` instead, which nothing reads, so an operator who
    followed the advice saw the same line for ever. `source` is that answer as
    data, written to `tests.gateBasis`, in `_manifest_vocab.GATE_BASIS`'s words.

    THE BASIS IS THE POINT AND NOT DECORATION. A narrow gate and a wide one read
    the same way once written, so an operator who is not told which default was
    taken cannot tell them apart without opening the shard -- which is the hand
    edit `commands/task.md` forbids, reached by a route that begins with this
    command reporting nothing. It is returned rather than printed here for
    `_build_phase`'s reason, read the other way round: the value written and the
    value explained have to come out of one derivation.

    THE THREE DEFAULTS, in order:

      1. the task's own `tests.add` paths, in the sibling's spelling. First
         because `commands/init.md`'s invariant is that a derived gate must run
         every case the task promises to author -- a task whose gate never runs
         the case it just wrote has bought a green with nothing behind it.
      2. the task's `files`, in that same spelling, when it names no case.
      3. the phase's `testGate`, which is the wide one.

    THE WIDE ANSWER IS AN ANSWER. A phase whose tasks all carry the wide entry
    has recorded no path-scoped spelling, and there is nothing to read one off:
    narrowing there would be a guess, and `commands/init.md` weighs that trade
    the only way it goes -- a false red is noticed the same day and a false green
    is never noticed at all. So the third default is reached with a reason naming
    what was missing, never with silence.

    A GATE-ONLY TASK NARROWS ONLY TO A SUITE. Arm 2 above reads every kind of
    `files` entry for a tdd or regression task, because `tests.add` already
    proved the task creates a real test file -- but a gate-only task names no
    case at all, so a source file among its `files` is not evidence the
    project's suite-running command has anything of this task's to run. When
    `mode` is `"gate-only"` and none of `files` is a suite path
    (`_manifest_phases.is_suite_path`), narrowing to it would point the gate at
    a command that runs nothing this task touched -- a green bought on work
    nobody wrote. The gate is `meta.phaseGate.always` when the plan declares
    one, else the sibling's own shared keys and path-less entries, carried
    through exactly as `_repointed` already leaves them -- never the phase's
    wide `testGate`, which is the wide gate an operator already gets warned
    about running every attempt.

    `seed`'s the only OTHER caller, and this is the version it gets: no
    `--failing-from` arm, on purpose. `_failing_from_task_gate` is that arm's
    entire home, so `seed`'s own call-graph closure (`vf6`'s equality check)
    never comes to read `args.failing_from` at all -- a phase `seed` mints
    has no sibling task yet to point a failed-first gate through in the first
    place.
    """
    if args.gate:
        return list(args.gate), "from --gate", "declared"
    if args.gate_clear:
        # THIS USED TO BE ACCEPTED AND IGNORED. The flag is defined globally, so
        # argparse ACCEPTED it here and
        # nothing read it: `add --gate-clear` reported success and wrote the
        # phase's `testGate` anyway. A flag accepted and ignored is a defect this
        # repo has already hit on other verbs for other flags of the same shape --
        # the operator is told the call succeeded and
        # the value they asked for is not there. The empty gate is a designed
        # state (`_phase_gate`, and `scope --gate-clear` for a task that already
        # exists); creation is where a gate is derived at all, so it is the one
        # place a task could not be given the state without a rescope. It is
        # asked BEFORE the derivation and not instead of a branch inside it: a
        # caller saying nothing should grade this task is answering the question
        # the three defaults below exist to answer, not choosing among them.
        return [], "from --gate-clear", "cleared"
    wide, meta, build, shape, owner = _task_gate_setup(phase, assembled)
    return _ordinary_task_gate(shape, owner, wide, build, add_paths, files,
                               mode, meta, phase)


# A THIN ALIAS, NOT A COPY. The gate runs from the project root and a runner
# need not: pinning each suite a run named onto one tracked path is
# `_evidence_io.pin_suites`, the resolver the full-run post-pass, full-gate's
# learning and the printed remedy read too, so `--failing-from` cannot place
# a name somewhere they would not. See that module for the rules.
_root_spelled_suites = _evidence_io.pin_suites


def _failed_step_entries(steps):
    """The gate entry of every failed step whose runner NAMED its suites, in
    step order, once each -- the recorded `name`, which is the entry the run
    resolved and ran (`_evidence_io.resolved_commands`), so a gate made of
    them re-runs exactly the commands that failed. Which steps count is asked
    of `_evidence_io.named_failing_suites` one step at a time, never a copy
    of its rule."""
    out = []
    for step in steps or []:
        name = step.get("name") if isinstance(step, dict) else None
        if (isinstance(name, str) and name.strip() and name not in out
                and _evidence_io.named_failing_suites([step])):
            out.append(name)
    return out


def _failing_from_task_gate(args, phase, assembled, add_paths, files, mode,
                            failing_row, project=None):
    """`(gate, basis, source)` for `add` ALONE -- `_task_gate` plus the
    failed-first `--failing-from` arm, kept in its own function rather than
    folded into `_task_gate` so `seed` (which shares every other arm) never
    reads `args.failing_from` in its own call-graph closure; `vf6` grades that
    closure against `VERB_FLAGS`, and `seed`'s row does not list the flag.

    ASKED BETWEEN `--gate-clear` AND THE THREE ORDINARY DEFAULTS, never
    instead of them: `--gate`/`--gate-clear` still answer first, exactly as
    they do for every other verb. `failing_row` is a CALLER-VALIDATED evidence
    row -- `_failing_from_lookup` already refused the call if it could not be
    one -- so this function does no refusing, only derivation, the same split
    `_locked_retarget` and `_retarget_gate_now` keep for `--gate-drop`/
    `--gate-set`.

    When the row's failed steps NAMED at least one suite
    (`_evidence_io.named_failing_suites`) and the phase has a path-scoped
    spelling to point them through, the gate is those suites UNIONED with this task's own
    `tests.add` paths, in the sibling's spelling -- the union because a fix
    task may still be asked to write a NEW case beside the failure it
    repairs, and dropping that path would buy a green the task never earned.
    Source word `failing-from-run:<runId>` (`_manifest_vocab.GATE_BASIS`'s own
    spelling for it) -- a reader compares the word before the colon and looks
    the runId up, never parsing further.

    A NAMED SUITE THAT CANNOT BE PINNED to one path from the project root
    (`_root_spelled_suites`) narrows nothing, and the gate is the entry of
    each failed step that named one -- the command that ran the failure --
    so the failure this task fixes is always inside its gate. Falling
    through to the ordinary arms instead would narrow to this task's own
    paths and run none of the named failures.

    THE FALL-THROUGH NEVER REACHES AN EMPTY GATE. A row whose failed steps
    named no suite (a tail excerpt is not a list of failing tests), or a
    phase with no path-scoped sibling to narrow through, falls to
    `_ordinary_task_gate` exactly as a call with no `--failing-from` would,
    with the reason it fell through said FIRST in the returned sentence --
    never silence, and never the empty gate as though `--failing-from` were a
    second spelling of `--gate-clear`.
    """
    if args.gate:
        return list(args.gate), "from --gate", "declared"
    if args.gate_clear:
        return [], "from --gate-clear", "cleared"
    wide, meta, build, shape, owner = _task_gate_setup(phase, assembled)
    if not args.failing_from:
        return _ordinary_task_gate(shape, owner, wide, build, add_paths,
                                   files, mode, meta, phase)
    if shape is not None:
        suites = (_evidence_io.named_failing_suites(failing_row.get("steps"))
                  if failing_row else [])
        pinned, why = ((None, None) if not suites
                       else _root_spelled_suites(suites, project or "."))
        if pinned:
            union = _union_paths(pinned, add_paths)
            return (_repointed(shape, build, union),
                    "narrowed to the suite(s) run %s named as failing, "
                    "union with this task's tests.add paths, in %s's "
                    "spelling" % (args.failing_from, owner),
                    "failing-from-run:%s" % (args.failing_from,))
        if not suites:
            why = ("run %s's failed steps named no suite as failing (a tail "
                   "excerpt is not a list of failing tests)"
                   % (args.failing_from,))
        else:
            # THE FAILURE STAYS IN THE GATE. The ordinary arms below would
            # narrow to this task's own tests.add or files, which run none of
            # the suites the run named -- so an unpinnable suite gates on the
            # failed step's own entry, which ran it and failed.
            why = "--failing-from %s: %s" % (args.failing_from, why)
            entries = _failed_step_entries(failing_row.get("steps"))
            if entries:
                return (entries,
                        "%s, so no suite is narrowed to: the gate is the "
                        "entry of each step run %s failed on (%s), which "
                        "runs the named failure" % (why, args.failing_from,
                                                    ", ".join(entries)),
                        "failing-from-run:%s" % (args.failing_from,))
            if wide:
                return (wide,
                        "%s, and run %s recorded no gate entry for its failed "
                        "step, so the gate is the phase's testGate, wide, "
                        "which the run was measured against"
                        % (why, args.failing_from),
                        "failing-from-run:%s" % (args.failing_from,))
    else:
        why = ("no sibling task in %s declares a path-scoped gate entry to "
               "narrow --failing-from %s against"
               % (phase.get("id"), args.failing_from))
    gate, basis, source = _ordinary_task_gate(
        shape, owner, wide, build, add_paths, files, mode, meta, phase)
    return gate, "%s, so falling through: %s" % (why, basis), source


def _build_task(task_id, title, args, phase, assembled, failing_row=None,
                project=None):
    """`(task, unnamed, gateBasis)` -- the new task, fully template-initialized
    (every field from the conventions' New task template, exactly once, in
    _TEMPLATE_KEYS order), the `tests.add` entries that named no file, and the
    sentence saying which default produced `tests.gate`.

    THE TRAILING HALVES ARE RETURNED RATHER THAN PRINTED HERE, and rather than
    re-derived by the caller. This function is the only place that turns
    `--tests-add` into `files`, so it is the only place that knows which entries
    the union could not carry and which paths the gate could be pointed at;
    `_locked_add` is where a sentence reaches the operator. Deriving either
    twice would be two chances for the scope written and the scope explained to
    stop being the same one -- `_build_phase`'s note about its `gate` argument,
    read the other way round.
    """
    risk = args.risk or "low"
    # sonnet is the floor for all fix work; risk high escalates to opus unless
    # the caller chose explicitly (commands/task.md's long-standing rule).
    model = args.model or _model_floor(risk)
    mode = args.tests_mode or "gate-only"
    add_paths, unnamed = _tests_add_paths(args.tests_add)
    # `files` BEFORE the gate, because the gate is derived from it. These two
    # were already adjacent and in the wrong order: the copy of `phase.testGate`
    # sat immediately above the parse of `--tests-add`, so the input a narrow
    # gate needs was produced one line too late and thrown away.
    files = _union_paths(_split_csv(args.files), add_paths)
    gate, gate_basis, gate_source = _failing_from_task_gate(
        args, phase, assembled, add_paths, files, mode, failing_row, project)
    task = {
        "id": task_id,
        "title": title,
        "status": "pending",
        "description": args.description or "",
        # `tests.add` IS PART OF `files`, and keeping them apart cost a real run 13
        # hand-fixes. A task that names a file in `tests.add` creates it, so a
        # scope that excludes it trips commit-scope on the task's own commit — and the
        # operator who reported it put it plainly: there is no case where the
        # divergence is wanted. Unioned rather than replaced, and the declared order
        # is kept, so a reader still sees what the author typed first.
        #
        # THE PATH THE ENTRY NAMES, NEVER THE ENTRY. An earlier version of this union
        # said "the file it names in `tests.add` BY DEFINITION", and the field is free prose, so what
        # the union copied was usually a sentence: `files` filled with assertions and
        # the permission this union exists to grant was never granted. An entry that
        # names nothing contributes nothing and is reported instead.
        "files": files,
        "tests": {
            "mode": mode,
            "add": list(args.tests_add or []),
            # true iff tdd -- the machine-readable disambiguation of `add`.
            "expectRedFirst": mode == "tdd",
            "gate": gate,
            # WHICH ARM PRODUCED THAT LIST, as data rather than as the sentence
            # the report prints and drops. Two arms end in the phase's gate
            # verbatim and they want opposite answers from the validator -- a
            # project with no path-scoped spelling has nothing to narrow with,
            # and a task that named no file does -- so the derivation is the
            # only thing that ever knew, and this is where it says so.
            "gateBasis": gate_source,
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
    # WRITTEN ONLY WHEN ASKED FOR, which is why `outputs` is not in
    # `_TEMPLATE_KEYS`. `area` and `reviewSkill` are absent from the phase
    # template for the same reason one level up: most tasks produce no declared
    # artefact, and an empty list on every task would be a considered answer
    # nobody gave. Absent and `[]` mean the same thing to every reader, so the
    # quieter of the two is the one to write.
    patterns = _split_csv(args.outputs)
    if patterns:
        task["outputs"] = patterns
    return task, unnamed, gate_basis


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

    vm = _validator()
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

    phase_basis = []
    phase = _resolve_phase(assembled, args.phase, out,
                           _id_shape.current_branch(os.path.dirname(os.path.abspath(mpath))),
                           phase_basis)
    if isinstance(phase, int):
        return phase
    phase_id = phase.get("id")

    # `add` reads `--gate-clear` now, so it owes the same refusal the other
    # two verbs give -- asked HERE, in their position: after the target is
    # resolved and before the first mutation.
    contradiction = _gate_contradiction(args)
    if contradiction:
        out(contradiction)
        return E_USAGE
    # ...and so does the one about what a `--files` entry may be. It was measured
    # on `scope`, but this verb writes the same field into the same index off the
    # same flag, so the refusal belongs to the FLAG rather than to the verb that
    # met the defect.
    refusal = _files_refusal(_split_csv(args.files))
    if refusal:
        out(refusal)
        return E_USAGE
    refusal = _outputs_refusal(_split_csv(args.outputs))
    if refusal:
        out(refusal)
        return E_USAGE
    failing_row = None
    if args.failing_from:
        failing_row, refusal = _failing_from_lookup(project, phase,
                                                    args.failing_from)
        if refusal:
            out(refusal)
            return E_USAGE

    task_id = _allocate_id(assembled, phase_id, _mint_suffix(mpath, assembled))
    task, unnamed_add, gate_basis = _build_task(task_id, title, args, phase,
                                                assembled, failing_row,
                                                project)
    # THE STAT IS OF THE FILE THE SUFFIX POINTS AT, NOT OF THE ENTRY'S OWN
    # SPELLING. A schema-legal `a/b.py:12-34` is a real, existing `a/b.py`, and
    # `os.path.exists` asked of the raw string can only ever say no -- reporting
    # a file that IS on disk as `_not_on_disk_note`'s "nothing on disk answers
    # for" would make the one advisory an operator is asked to trust wrong about
    # the declaration it was just given. `missing` still carries the entry AS
    # DECLARED, so the note names exactly what the caller typed.
    missing = [f for f in task["files"]
               if not os.path.exists(os.path.join(project,
                                                   _vocab._strip_line_suffix(f)))]

    phase.setdefault("tasks", []).append(task)
    fidx = assembled.setdefault("fileIndex", {})
    for fpath in task["files"]:
        # By the PATH, which is what the validator and the plan gate match on -
        # a `:line-range` suffix is part of the declaration, not of the row.
        entry = fidx.setdefault(_vocab._strip_line_suffix(fpath), [])
        if task_id not in entry:
            entry.append(task_id)
    # v0.37 A4, at THIS write site too: reused from _panel_write, scoped to
    # the target phase -- the one shard this add writes anyway.
    healed = _panel_write._heal_phase_status({"phases": [phase]})
    if args.dry_run:
        return _dry_run_report(args, out, vm, assembled, task, phase_id, gate_basis,
                               missing, unnamed_add, project, mpath)

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
    index_note = _index_dirty_note(written, mpath, project, phase_id)
    git_root = os.path.abspath(os.path.join(project,
                                            (config or {}).get("gitRoot") or "."))
    branch_note = _phase_branch_note(git_root, phase, cwd=git_root)
    if args.as_json:
        result = {"ok": True, "id": task_id, "phase": phase_id,
                  "phaseBasis": phase_basis[0] if phase_basis else None,
                  "title": title, "task": task, "written": written,
                  "healed": healed,
                  # GROUPED HERE TOO. One line per rule with its count and every
                  # id named - the human branch below has grouped these since a
                  # plan put nineteen identical advisories under every write, and
                  # this block went on carrying one per item into whatever reads
                  # it. Nothing is elided: the cap is for an eye that can rerun
                  # with `--verbose`, and this reader cannot.
                  "warnings": _wg.collapse_machine(warnings, written_manifest),
                  "filesNotOnDisk": missing,
                  # THE SAME ACCOUNT AS DATA: WHICH `tests.add` entries the `files` union
                  # could not carry. A machine surface that reported only the
                  # resulting `files` would show a scope with nothing wrong
                  # with it and no way to tell that a case file is outside it.
                  "testsAddNamingNoFile": list(unnamed_add),
                  # Which of the three defaults the gate came from. `add-phase`
                  # spells the same fact with the same key, because a reader
                  # comparing a phase's basis with a task's is comparing one
                  # kind of answer.
                  "testGateBasis": gate_basis,
                  "gateDirectories": _gate_directory_notes(
                      project, task["tests"]["gate"], assembled.get("meta")),
                  "ready": not waiting, "waitingOn": waiting}
        result.update(jres)
        result.update(stdin_notes_key(args))
        result.update(project_basis_key(args))
        result.update(_index_dirty_key(index_note))
        result.update(_phase_branch_key(branch_note))
        out(json.dumps(result, indent=2, sort_keys=True))
        return 0
    out("[audit-task] %s added to %s -- %s" % (task_id, phase_id, title))
    for pb in phase_basis:
        out("  phase: %s -- of the running %s, the one whose branch %s is checked out"
            % (pb["phase"], ", ".join(pb["inProgress"]), pb["branch"]))
    out("  tests.mode %s  model %s  risk %s  skills %s"
        % (task["tests"]["mode"], task["model"], task["risk"],
           json.dumps(task["skills"])))
    # The basis rides every gate line, narrow or wide, exactly as it does under
    # `add-phase`: the entries alone cannot tell a scope this command derived
    # from a scope it inherited, and an operator who cannot tell reads the shard
    # to find out.
    out("  gate: %s (%s)"
        % (", ".join(task["tests"]["gate"]) if task["tests"]["gate"]
           else "none", gate_basis))
    for line in _gate_directory_notes(project, task["tests"]["gate"],
                                      assembled.get("meta")):
        out(line)
    if task["tests"]["mode"] == "tdd" and not task["tests"]["add"]:
        # SAID HERE AS WELL AS BY THE VALIDATOR, and the reason is when. A
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
    unnamed_note = _unnamed_add_note(unnamed_add)
    if unnamed_note:
        out(unnamed_note)
    missing_note = _not_on_disk_note(project, missing)
    if missing_note:
        out(missing_note)
    for row in healed:
        out("  healed: %s" % _panel_write._fmt_change(row))
    # Grouped, not one line per item: a plan whose phases carry no area tag put
    # nineteen identical advisories under every `add`, and what they buried was
    # the line about THIS task. `--json` keeps every warning - see `result` above,
    # which is a machine surface and does not read.
    for line in _wg.collapse(warnings, written_manifest):
        out("WARNING: " + line)
    if not jres.get("journaled") and jres.get("journaledWhy") == "failed":
        out(_not_journaled_line(jres, "the task.add row"))
    out("  written: %s" % ", ".join(written))
    if index_note:
        out(index_note)
    if branch_note:
        out(branch_note)
    for line in _readiness_lines(waiting, task_id):
        out(line)
    return 0


def _dry_run_report(args, out, vm, assembled, task, phase_id, gate_basis, missing,
                    unnamed_add, project, mpath):
    """`add --dry-run`: the task built, the plan validated IN MEMORY, nothing written.

    THE SAME VALIDATOR THE REAL ADD RE-READS FROM DISK, over the same assembled
    plan it would have written, so a finding here is the finding the write would
    have rolled back on. Nothing is journaled and no file is touched; the id is
    the one the allocator would take now, under the lock this call holds, and a
    later real call allocates afresh.
    """
    findings, warnings = vm.validate(assembled)
    if args.as_json:
        if findings:
            for line in ["[audit-task] DRY RUN: the add would leave the manifest "
                         "invalid -- nothing written"] + ["FINDING: " + f
                                                          for f in findings]:
                out(line)
            return E_INVALID
        result = {"ok": True, "dryRun": True, "id": task["id"], "phase": phase_id,
                  "task": task, "written": [], "testGateBasis": gate_basis,
                  "filesNotOnDisk": missing,
                  "testsAddNamingNoFile": list(unnamed_add),
                  "warnings": _wg.collapse_machine(warnings, assembled)}
        result.update(project_basis_key(args))
        out(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if findings:
        out("[audit-task] DRY RUN: %s would leave the manifest invalid -- nothing "
            "written:" % (task["id"],))
        for line in findings:
            out("FINDING: " + line)
        return E_INVALID
    out("[audit-task] DRY RUN: would add %s to %s -- %s; nothing written, and the "
        "plan validates with it" % (task["id"], phase_id, task["title"]))
    out("  gate: %s (%s)" % (", ".join(task["tests"]["gate"]) or "none", gate_basis))
    if task["files"]:
        out("  files: %s" % ", ".join(task["files"]))
    for note in (_unnamed_add_note(unnamed_add), _not_on_disk_note(project, missing)):
        if note:
            out(note)
    for line in _wg.collapse(warnings, assembled):
        out("WARNING: " + line)
    return 0


# --- cancel: finished, but not done ---------------------------------------------
# ca (v0.40): a phase or task can end without landing — the feature was
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
    vm = _validator()
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
    status = (_mio.effective_phase_status(node) if kind == "phase"
              else node.get("status"))
    if status in ("done", "cancelled"):
        # Terminal is terminal. Re-writing a finished item's status here would
        # rewrite history with no record of what it said before - and a phase's
        # done is derived, so its stored status is not the one to ask.
        out("[audit-task] %s is already %s -- terminal work is not re-decided "
            "by this verb (edit the manifest deliberately if it is wrong)"
            % (tid, status))
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
    index_note = _index_dirty_note(written, mpath, project, phase_id)
    git_root = os.path.abspath(os.path.join(project,
                                            (config or {}).get("gitRoot") or "."))
    branch_note = _phase_branch_note(git_root, phase, cwd=git_root)
    if args.as_json:
        result = {"ok": True, "id": tid, "kind": kind, "phase": phase_id,
                  "reason": reason, "at": now, "cascaded": cascaded,
                  "written": written,
                  "warnings": _wg.collapse_machine(warnings, written_manifest)}
        result.update(jres)
        result.update(stdin_notes_key(args))
        result.update(project_basis_key(args))
        result.update(_index_dirty_key(index_note))
        result.update(_phase_branch_key(branch_note))
        out(json.dumps(result, indent=2, sort_keys=True))
        return 0
    out("[audit-task] %s %s cancelled -- %s" % (kind, tid, reason))
    if cascaded:
        out("  also cancelled inside it: %s" % ", ".join(cascaded))
    for line in _wg.collapse(warnings, written_manifest):
        out("WARNING: " + line)
    if not jres.get("journaled") and jres.get("journaledWhy") == "failed":
        out(_not_journaled_line(jres, "the %s.cancel row" % kind))
    out("  written: %s" % ", ".join(written))
    if index_note:
        out(index_note)
    if branch_note:
        out(branch_note)
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


# --- start: the promotion the plan gate reads ------------------------------------
# `add` writes `status: "pending"`, `startedAt: null`, `attempts: 0`, and
# `hooks/_config.in_progress_task_map` -- the map `hooks/require-plan.py` resolves
# an allowed path through -- skips every task whose status is not `in_progress`,
# its `fileIndex` arm included (that arm only re-adds paths for ids already in the
# filtered set). So a task added to a phase that is ALREADY RUNNING is born in a
# state where its own declared files are refused on the first Edit, and the only
# way out was the hand edit `commands/task.md` forbids: `/audit:run <taskId>`
# promotes AND spawns, so there was no way to promote without running. Driven and
# confirmed; a field report measured two executors returning zero edits, each
# having spent a subagent's budget, both refused on a path their task's `files`
# declared.
#
# WIDENING THE MAP TO READ `pending` IS THE OTHER REPAIR, AND IT WAS REJECTED. That
# map has three consumers -- `require-plan.py`, `remind-tdd.py` (which reads its
# `testsMode`) and `_config.in_progress_files` -- so one edit there would open, in
# one move, every file declared by every pending task in the running phase. That
# deletes the per-task narrowing the plan gate's decision order exists for, which
# `plugins/audit/tests/test_require_plan.py` pins and `require-plan.py` reasons
# from. The narrowing is the guard; the missing half was a verb.
_DEFAULT_MAX_ATTEMPTS = 3           # conventions' New task template


def _attempt_ceiling(task):
    """The `maxAttempts` this task records, or the template's default.

    `bool` is excluded for `_manifest_io.recorded_attempt`'s reason: `True` is an
    `int` in Python, so a manifest carrying `maxAttempts: true` would otherwise
    read as a ceiling of one. A missing, non-integer or non-positive value is not
    a ceiling anybody set, so the template default answers for it -- refusing
    every start on a hand-edited manifest instead would put this verb out of
    reach exactly where the hand edit it replaces has already been used.
    """
    value = (task or {}).get("maxAttempts")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return _DEFAULT_MAX_ATTEMPTS
    return value


def _start_task(task, now):
    """Promote one task to running; returns the three values it held before.

    THE FIELDS ARE `reference/orchestrator.md`'s STEP 2 VERBATIM -- *Set
    `task.status = "in_progress"`, `task.startedAt = <ISO now>`,
    `task.attempts += 1`* -- because this verb exists to BE that Edit. A writer
    that stamped anything the prescribed Edit does not would make two records of
    one run disagree depending on which route promoted the task.

    `startedAt` IS RE-STAMPED ON A RE-START, which is what step 2 says and
    therefore what the hand edit does today. It is not self-evidently the right
    field semantics -- the usage `window` attribution reads
    `startedAt`/`completedAt` as the task's whole lifetime, so a re-stamp narrows
    the window a previous attempt sat in -- but that is a question about the
    prescription, and answering it differently here in silence is how one field
    comes to mean two things.

    THE PRIOR VALUES ARE READ BEFORE THE WRITE, for `_locked_cancel`'s reason one
    verb over: afterwards every one of them says `in_progress`, and the `from`
    half of the journal row is gone from the manifest as well as from the row.
    """
    was = {"status": task.get("status"),
           "attempts": _mio.recorded_attempt(task),
           "startedAt": task.get("startedAt"),
           "blockedReason": task.get("blockedReason")}
    task["status"] = "in_progress"
    task["startedAt"] = now
    task["attempts"] = (was["attempts"] or 0) + 1
    # A running task is not waiting, so the reason `block` recorded goes with the
    # status it explained; the task.start row keeps it as the `from` half.
    task.pop("blockedReason", None)
    return was


def _start_changes(tid, was, task):
    """The `changes` rows for a promotion -- id/field/from/to, one per field.

    THE SHAPE IS THE ALLOW-LIST'S, not a per-field key invented here:
    `_journal_io.DETAILS_KEYS` carries `changes` and drops anything unlisted in
    silence, which `_journal_phase_add` records the cost of. All three rows are
    written even when a value did not move -- a re-start that kept `pending` is
    not a thing, but a `startedAt` that happens to equal the old one is, and a
    row list built by filtering equality would make a reader work out which
    fields the verb even touches.
    """
    rows = [{"id": tid, "field": "status",
             "from": was["status"], "to": task.get("status")},
            {"id": tid, "field": "startedAt",
             "from": was["startedAt"], "to": task.get("startedAt")},
            {"id": tid, "field": "attempts",
             "from": was["attempts"], "to": task.get("attempts")}]
    # Only when there was one: a row for a field the start never touched would
    # claim a write that did not happen.
    if was.get("blockedReason") is not None:
        rows.append({"id": tid, "field": "blockedReason",
                     "from": was["blockedReason"], "to": None})
    return rows


def _start_details(task_id, phase_id, was, task):
    """The `details` block for a `task.start` row, built where a case can read it.

    SEPARATE FROM THE APPEND ON PURPOSE. `_journal_io` drops a key that is not on
    `DETAILS_KEYS` in SILENCE, so a row read back out of the trail is identical
    whether the writer handed over an allow-listed block or one carrying an
    invented key beside it -- which means no assertion about the written row can
    see the mistake `_journal_phase_add` records paying for. Built here, the
    handover itself is the thing a case can compare against the allow-list.
    """
    details = {"taskId": task_id, "phaseId": phase_id,
               "changes": _start_changes(task_id, was, task)}
    attempt = task.get("attempts")
    if attempt is not None:
        details["attempt"] = attempt
    return details


def _journal_start(project, config, mpath, task_id, phase_id, was, task,
                   healed=None, entry=None):
    """The `task.start` row: what the promotion moved, and which attempt it is.

    `changes` AND `attempt`, both already on `_journal_io.DETAILS_KEYS` --
    `_journal_scope`'s reasoning for the second of them applies here unchanged,
    and more directly: this row IS the attempt increment, so a trail that
    recorded the promotion without the number would leave a reader counting
    attempts by counting rows, which is the same number only while nothing else
    ever writes the field.

    A RE-START SAYS SO IN ITS SUMMARY, because `audit-journal list` prints the
    summary and nothing else. A retry whose row read like a first start would
    have to be told apart by opening `details`, and the retry is the row a reader
    of a task that failed is looking for.

    AND SO DOES THE PHASE THIS RUN PROMOTED, in the summary for that same reason
    and in `_journal_add`'s spelling: the write moved a phase as well as a task,
    and a row naming only the task would leave the phase's own start recorded in
    the manifest and nowhere in the trail. It rides the summary rather than
    `changes`, because that block's rows are this TASK's fields.
    """
    attempt = task.get("attempts")
    if was["status"] == "in_progress":
        summary = ("%s RE-STARTED in %s: attempt %s, the previous one left it "
                   "in_progress" % (task_id, phase_id, attempt))
    else:
        summary = ("%s started in %s: attempt %s, was %s"
                   % (task_id, phase_id, attempt, was["status"]))
    if healed:
        summary += "; " + "; ".join(_panel_write._fmt_change(r) for r in healed)
    details = _start_details(task_id, phase_id, was, task)
    if (entry or {}).get("state") in ("cut", "adopt"):
        summary += "; branch %s %s" % (entry["branch"], "cut from %s" % entry["parent"]
                                       if entry["state"] == "cut" else "recorded")
        details["branch"] = entry["branch"]
    return _journal_row(project, config, mpath, "task.start", summary, details)


# --- phase entry: the branch the first start cuts ---------------------------------
# `reference/orchestrator.md`'s Phase entry - resolve the name and the parent,
# verify HEAD is the parent, `git switch -c`, record the branch - was prose the
# orchestrator ran BEFORE this verb. Every phase driven through the verbs rather
# than `/audit:run` therefore ran on its parent branch with no branch at all, which
# measured most of this project's own phases, and nothing said so. The protocol
# binds this verb now, so a phase cannot start its work outside it in silence.
def _git_answer(git_root, *argv):
    """(returncode, stdout) of one git call, or (None, "") when git cannot run."""
    try:
        r = subprocess.run(["git", "-C", git_root] + list(argv),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        return None, ""
    return r.returncode, r.stdout.decode("utf-8", "replace").strip()


def _phase_entry(git_root, meta, phase):
    """What starting work in `phase` does to its branch, decided before any write.

    {"state": "none"|"on-branch"|"cut"|"adopt", "refusal": str|None,
     "branch", "parent", "baseRef"}. "none" is a directory git does not hold: the
    phase runs with no branch and the caller says so. "adopt" is standing on
    EXACTLY the name the plan composes for this phase, which is what
    `/audit:worktree add` checks out: its fork point is recorded rather than the
    worktree refused for not standing on the parent, where it cannot stand.
    """
    pid = phase.get("id")
    code, _top = _git_answer(git_root, "rev-parse", "--show-toplevel")
    if code != 0:
        return {"state": "none", "refusal": None}
    here = _id_shape.current_branch(git_root)
    recorded = phase.get("branch")
    if recorded:
        if here == recorded:
            return {"state": "on-branch", "refusal": None, "branch": recorded}
        return {"state": "refused", "refusal": (
            "[audit-task] phase %s runs on branch %s, and HEAD here is %s -- a "
            "phase's edits and commits happen on its own branch (reference/"
            "orchestrator.md, Phase entry). `git switch %s` (or start it from the "
            "worktree that has it checked out), then start again."
            % (pid, recorded, here or "detached", recorded))}
    answer = _branch.phase_answer(meta, phase, _worktrees.git_user_name(git_root))
    name, parent = answer["branch"], answer["parent"]
    if answer["violations"]:
        return {"state": "refused", "refusal": (
            "[audit-task] phase %s's branch would be %r, which git refuses as a ref "
            "(%s) -- fix the naming convention (%s) first"
            % (pid, name, "; ".join(answer["violations"]), answer["branchBasis"]))}
    if here is None:
        return {"state": "refused", "refusal": (
            "[audit-task] HEAD is detached, so there is no branch for phase %s to "
            "fork from -- `git switch %s`, then start again" % (pid, parent))}
    code, head = _git_answer(git_root, "rev-parse", "--verify", "-q", "HEAD")
    if code != 0 or not head:
        return {"state": "refused", "refusal": (
            "[audit-task] %s has no commit yet, so phase %s has no base to fork "
            "from -- commit first, then start again" % (here, pid))}
    if here == name:
        code, fork = _git_answer(git_root, "merge-base", parent, "HEAD")
        if code != 0 or not fork:
            return {"state": "refused", "refusal": (
                "[audit-task] HEAD is on %s, the branch the plan names for phase %s, "
                "but git cannot find where it forked from %s (%s) -- the fork point "
                "is what baseRef records, so it is not guessed"
                % (name, pid, parent, answer["parentBasis"]))}
        return {"state": "adopt", "refusal": None, "branch": name,
                "parent": parent, "baseRef": fork}
    if here != parent:
        return {"state": "refused", "refusal": (
            "[audit-task] phase %s forks from %s (%s), and HEAD is on %s -- a phase "
            "branch is cut from its parent. `git switch %s`, or set the phase's "
            "parentBranch, then start again" % (pid, parent, answer["parentBasis"],
                                                here, parent))}
    code, _sha = _git_answer(git_root, "rev-parse", "--verify", "-q",
                             "refs/heads/" + name)
    if code == 0:
        return {"state": "refused", "refusal": (
            "[audit-task] branch %s already exists, and phase %s does not record it "
            "-- nothing says that branch is this phase's. Delete or rename it, or "
            "check it out and start from there, then start again" % (name, pid))}
    return {"state": "cut", "refusal": None, "branch": name, "parent": parent,
            "baseRef": head}


def _entry_line(entry, phase_id):
    """The line `start` prints about the branch, or None when nothing moved."""
    state = entry.get("state")
    if state == "cut":
        return ("  branch %s cut from %s at %s -- phase %s's edits and commits "
                "happen there" % (entry["branch"], entry["parent"],
                                  entry["baseRef"][:12], phase_id))
    if state == "adopt":
        return ("  branch %s recorded for phase %s, forked from %s at %s"
                % (entry["branch"], phase_id, entry["parent"], entry["baseRef"][:12]))
    if state == "none":
        return ("  no git repository here, so phase %s runs with no branch"
                % (phase_id,))
    return None


def _entry_warnings(phase):
    """What a phase ENTERED by this start is missing that sign-off will ask for.

    WARNINGS AND NEVER A REFUSAL: an empty gate is a designed state (sign-off
    then rests on review alone), and a phase with no outcome can still be
    worked. They are said at entry because that is the last moment either is
    cheap to set - after it, the work has already been judged against it.
    """
    pid = phase.get("id")
    out = []
    if not phase.get("testGate"):
        out.append("phase entry: %s has an EMPTY testGate - sign-off will rest on "
                   "review alone. A designed state, said here so it is chosen "
                   "rather than inherited" % (pid,))
    if not (phase.get("desiredOutcome") or "").strip():
        out.append("phase entry: %s states no desiredOutcome - sign-off asks "
                   "whether the phase met it (/audit:phase retarget %s --outcome "
                   "\"<what success is>\")" % (pid, pid))
    return out


def _locked_start(args, project, config, mpath, tid, out):
    """Promote one task to `in_progress`, under the lock, with a row and a
    revalidation -- the path every mutating verb in this file takes.

    THE TERMINAL REFUSAL IS `_locked_cancel`'s, one verb over and for the same
    reason: re-opening a `done` or `cancelled` task by flipping its status would
    rewrite history with no record of what it said before, and a `done` task
    carries a commit that was graded against the scope it holds.

    A RE-START IS NOT REFUSED AND NOT IDEMPOTENT, WHICH IS THE DECISION.
    `attempts` counts SPAWNS, not states. `reference/orchestrator.md`'s step 4
    leaves a task `in_progress` when its gates run red and sends it back through
    step 2, so a second call on an already-running task IS that retry rather than
    a repeat of the first call. Refusing it would leave the retry path with no
    verb at all -- back to the hand edit -- and returning 0 having written
    nothing would freeze the count `blocked` is derived from, so a run could
    retry for ever while the plan went on saying it had been attempted once.
    That is the failure mode an idempotent spelling buys, and it is worse than a
    double call costing an attempt, which this reports by number every time.

    THE CEILING IS THE OTHER HALF OF THE PRESCRIBED STEP, so it is checked here:
    step 2 pairs the increment with *if `task.attempts > (task.maxAttempts or
    3)`, do NOT spawn -- set `status = "blocked"`*. A verb that wrote the
    increment and dropped that half would hand back exit 0 on a task the caller
    must not spawn. It REFUSES rather than writing `blocked` itself: that
    transition owes an ADO echo and a human, both of which belong to the
    orchestrator, and a verb that half-performs a transition it cannot finish is
    a worse answer than one that names the number and stops.
    """
    try:
        raw_index = _mio.read_json(mpath)
        assembled = _mio.load_manifest(mpath)
    except Exception as exc:
        out("[audit-task] cannot read/assemble manifest: %s" % exc)
        return E_USAGE
    vm = _validator()
    pre_findings, _w = vm.validate(assembled)
    if pre_findings:
        out("[audit-task] the manifest is already invalid -- nothing written; "
            "fix these first:")
        for line in pre_findings:
            out("FINDING: " + line)
        return E_INVALID

    kind, node, phase = _find_target(assembled, tid)
    if kind is None:
        out("[audit-task] no task with id %r in %s" % (tid, mpath))
        return E_USAGE
    if kind != "task":
        # The ids look alike enough that guessing between them guesses wrong.
        # A phase is not this verb's SUBJECT even though this verb now promotes
        # one: the promotion rides a task starting inside it, so a phase id
        # names no work to start.
        out("[audit-task] %s is a PHASE -- `start` takes one TASK id. The "
            "phase around that task is promoted and stamped by the same "
            "write, and a phase with no task to start is entered by the run "
            "that enters it (/audit:phase %s)" % (tid, tid))
        return E_USAGE
    status = node.get("status")
    if status in _mio.TERMINAL:
        out("[audit-task] %s is already %s -- terminal work is not re-started "
            "by this verb; the follow-up is a new task (/audit:task add)"
            % (tid, status))
        return E_USAGE
    ceiling = _attempt_ceiling(node)
    attempts = _mio.recorded_attempt(node) or 0
    if attempts + 1 > ceiling:
        out("[audit-task] %s records %s attempt(s) against a maxAttempts of "
            "%s, so this start would spend one past the ceiling -- refused. "
            "The orchestrator's move here is `blocked` plus a human "
            "(reference/orchestrator.md, Execute the task, step 2) - "
            "`audit-task.py block %s --reason \"<attempts exhausted: the last red "
            "gate's reason>\"` - which this verb will not do on its own because "
            "that transition also owes an ADO echo." % (tid, attempts, ceiling, tid))
        return E_USAGE

    git_root = os.path.abspath(os.path.join(project,
                                            (config or {}).get("gitRoot") or "."))
    entry = _phase_entry(git_root, assembled.get("meta") or {}, phase)
    if entry.get("refusal"):
        out(entry["refusal"])
        return E_USAGE

    now = _utc_now()
    was = _start_task(node, now)
    if entry["state"] in ("cut", "adopt"):
        phase["branch"] = entry["branch"]
        if not phase.get("baseRef"):
            phase["baseRef"] = entry["baseRef"]
    # THE PHASE IS PROMOTED BY THE SAME WRITE, from the same instant. Until this
    # line the control surface's save was the only site in the tree that moved a
    # phase out of `pending`, so an orchestrator driving a plan from the command
    # line left every phase pending for its whole life and nothing recorded when
    # the work in it began. Reused from `_panel_write` rather than re-derived, on
    # `_locked_add`'s reasoning: two writers of one transition is two answers
    # about what promoting a phase means.
    #
    # THE PLAN GATE IS NOT WHAT THIS BUYS and must not be read as it. A running
    # task under a pending phase already counts as a running phase, deliberately
    # -- a hand-started task is still a repository executing its plan -- so
    # nothing here widens or narrows what the gate resolves. What the write adds
    # is the record: the moment the phase started, which had no field to sit in.
    healed = _panel_write._heal_phase_status({"phases": [phase]}, now)
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
        out("[audit-task] REFUSED: the start would leave the manifest invalid "
            "-- every written file rolled back, nothing kept:")
        for line in findings:
            out("FINDING: " + line)
        return E_INVALID
    if entry["state"] == "cut":
        # AFTER the write validated, so a refused write never leaves a branch behind;
        # and the write is rolled back when git refuses, so no phase records a branch
        # git does not hold. The working tree rides along to the new branch.
        try:
            cut = subprocess.run(["git", "-C", git_root, "switch", "-c",
                                  entry["branch"]],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            cut_err = cut.stderr.decode("utf-8", "replace").strip()
            cut_ok = cut.returncode == 0
        except OSError as exc:
            cut_ok, cut_err = False, str(exc)
        if not cut_ok:
            _restore(snap)
            out("[audit-task] REFUSED: git would not cut %s for phase %s -- the "
                "start is rolled back, nothing kept: %s"
                % (entry["branch"], phase_id, cut_err))
            return E_INVALID

    jres = _journal_start(project, config, mpath, tid, phase_id, was, node,
                          healed, entry)
    entry_warnings = (_entry_warnings(phase)
                      if healed or entry["state"] in ("cut", "adopt") else [])
    index_note = _index_dirty_note(written, mpath, project, phase_id)
    entry_line = _entry_line(entry, phase_id)
    # REPORTED, NEVER REFUSED. The plan gate is what this verb serves, and the
    # case it serves is a task whose edits are being denied -- so a blocker list
    # is something the operator has to see and `/audit:run` is where readiness
    # decides a spawn. `_readiness_lines` is deliberately not reused: its other
    # branch hands back `/audit:run <id>`, which on a task this call has just put
    # in_progress is advice to trip `run.md`'s interrupted-run warning.
    waiting = _waiting_on(assembled, node)
    if args.as_json:
        result = {"ok": True, "id": tid, "phase": phase_id,
                  "status": node.get("status"), "startedAt": node.get("startedAt"),
                  "attempt": node.get("attempts"), "maxAttempts": ceiling,
                  "restarted": was["status"] == "in_progress",
                  "was": was["status"],
                  "changes": _start_changes(tid, was, node),
                  # APART FROM `changes`, which is this task's fields, for the
                  # reason the add branch keeps the two apart: the phase moved
                  # too, and folding its rows into a task's change list would
                  # make a consumer join them on an id that is not the task's.
                  "healed": healed,
                  "written": written,
                  "warnings": _wg.collapse_machine(warnings, written_manifest),
                  "ready": not waiting, "waitingOn": waiting}
        result.update(jres)
        result.update(stdin_notes_key(args))
        result.update(project_basis_key(args))
        result.update(_index_dirty_key(index_note))
        result["phaseEntry"] = {k: entry.get(k) for k in ("state", "branch", "parent",
                                                          "baseRef")}
        result["entryWarnings"] = entry_warnings
        out(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if was["status"] == "in_progress":
        out("[audit-task] %s RE-STARTED in %s -- it was already in_progress, so "
            "this is the retry step 2 of reference/orchestrator.md prescribes, "
            "and it spends an attempt" % (tid, phase_id))
    else:
        out("[audit-task] %s started in %s -- was %s" % (tid, phase_id,
                                                         was["status"]))
    out("  attempt %s, against a recorded ceiling of %s"
        % (node.get("attempts"), ceiling))
    out("  startedAt %s" % (node.get("startedAt"),))
    for row in healed:
        # THE PHASE'S OWN LINE, and it names the field rather than announcing a
        # promotion, because two fields move and only one of them is a status.
        out("  phase %s" % _panel_write._fmt_change(row))
    out("  the plan gate now resolves this task's `files` -- that is what the "
        "promotion buys, and it is per task: no other pending task in %s moved"
        % (phase_id,))
    if waiting:
        out("  NOTE: still waiting on %s -- promoted anyway, because this verb "
            "does not decide a spawn; /audit:run is where readiness does"
            % ", ".join(waiting))
    for line in entry_warnings:
        out("WARNING: " + line)
    for line in _wg.collapse(warnings, written_manifest):
        out("WARNING: " + line)
    if not jres.get("journaled") and jres.get("journaledWhy") == "failed":
        out(_not_journaled_line(jres, "the task.start row"))
    out("  written: %s" % ", ".join(written))
    if entry_line:
        out(entry_line)
    if index_note:
        out(index_note)
    return 0


# --- done: the close the record is made of ---------------------------------------
# `start` gave the promotion a verb and the close still had none, so
# `reference/orchestrator.md`'s step 4 stayed two hand Edits: 4b's status and
# completion stamp, 4c's SHA. Measured here: one run wrote a task's completion into
# the phase shard AND the manifest index, a later `git reset --hard` reverted the
# index, the shard turned out never to have carried the marks at all, and the record
# of three finished tasks survived only in their commit subjects -- rebuilt
# afterwards out of `git log`. Two places for one fact is one place and one lie, and
# the one a reader would have opened was the empty one.
#
# THE SHA IS REQUIRED, which is the decision this verb turns on. It is what fixes
# the close to something git can be asked about afterwards -- `_commit_trail` and
# `_invariants.commit_scope` both grade a task through it -- and `/audit:doctor`
# already warns about done tasks that carry none. A verb that made that state cheap
# to reach would be a verb that manufactures the finding it exists to prevent.
#
# WHICH PUTS THE CALL AT THE END OF STEP 4c, after `git rev-parse HEAD`: the SHA
# does not exist until the commit does. The manifest write then rides along with the
# next task's commit or with sign-off, which is exactly what 4c already prescribes
# for `task.commit` -- so the ordering is the document's rather than a new one, and
# what changes is that ONE write carries both halves instead of two writes carrying
# one each.
#
# THE COMPLETION ROWS ARE NOT THIS VERB'S TO WRITE. `hooks/journal-writes.py`
# derives `task.complete` and `task.commit` from the write itself, and step 4c says
# never to append those by hand: two writers means duplicate rows and a doctor whose
# completion count is no longer a count. So the row here is `task.done`, named after
# the verb the way `task.start` and `task.cancel` are, and it is what records the
# close where no hook is watching -- that hook sees a tool call, and this script is
# also run straight from a terminal.
_SHA_SHAPE = re.compile(r"^[0-9a-fA-F]{7,40}$")

# The words `intentCheck.answer` may hold, in the schema enum's order. The first
# three are the reviewer's; `not-asked` is the orchestrator's own - the question
# deliberately not put - and it is the one the door refuses without a basis.
INTENT_ANSWERS = ("matches", "diverges", "cannot-tell", "not-asked")


def _commit_shape_refusal(sha):
    """The refusal for a `--commit` value that is not a SHA at all, or None.

    SYNTAX BEFORE GIT, and it is the half that still fires where git cannot be
    asked. `HEAD`, a branch name and a tag all RESOLVE -- `git rev-parse` hands
    each of them back a commit -- so a check that only asked git would accept a
    NAME into a field the schema calls a SHA, where it goes on meaning whatever
    that ref points at next month. A trail whose rows move afterwards is not one.
    """
    if _SHA_SHAPE.match((sha or "").strip()):
        return None
    return ("[audit-task] --commit %r is not a commit SHA (7-40 hex characters). "
            "`task.commit` is an OBJECT id, so a name -- HEAD, a branch, a tag -- "
            "would go on resolving to whatever it points at later, and the trail's "
            "worth is that a written row cannot move. Pass the output of "
            "`git rev-parse HEAD`." % (sha,))


def _commit_git_note(git_root, sha):
    """`(refusal, note)` for a SHA git was asked about -- at most one of them set.

    `_commit_trail.resolve` IS THE ANSWER, asked rather than re-derived: that
    module holds this question for `/audit:doctor` and for `repair-commits.py`,
    and a third walk putting it to git would be a third answer waiting to disagree
    with the other two.

    A NEGATIVE IS A REFUSAL ONLY IN A CLONE THAT CAN ANSWER FOR IT, which is
    `_commit_trail.is_shallow`'s rule read forward. With no git on PATH, in a
    shallow clone, or where git will not answer, a failed `rev-parse` says the
    question was never put rather than that the object does not exist -- and the
    doctor's remedy for a false `missing` is `repair-commits.py --apply`, which
    NULLS the SHA. Graded the other way this verb would refuse honest closes on
    CI's default checkout and then invite an operator to destroy an intact trail.
    So the unasked question is written and SAID; only the answered negative
    refuses.
    """
    verdict = _commit_trail.resolve(git_root, sha)
    if verdict == "present":
        return None, None
    if verdict == "absent":
        return ("[audit-task] git cannot resolve %s in %s -- refused. A "
                "`task.commit` that resolves nowhere is what /audit:doctor "
                "reports as a fabricated SHA or one gc has collected, and "
                "writing one here would put that finding into the manifest "
                "deliberately. Commit first, then pass `git rev-parse HEAD`."
                % (sha[:12], git_root), None)
    return None, ("  commit %s: NOT VERIFIED -- no git on PATH, git would not "
                  "answer, or this clone is SHALLOW and the object is past where "
                  "it was cut. An unasked question is not a clean trail; the SHA "
                  "was written as given (`git fetch --unshallow` makes it "
                  "askable)" % (sha[:12],))


def _examined_head(git_root):
    """The SHA HEAD names in `git_root`, or None when git cannot say.

    What a no-change close was measured against. None is written and SAID rather
    than refused: a project outside git runs this plugin (a phase there runs with
    no branch), and refusing would leave it no way to record the answer at all.
    """
    code, head = _git_answer(git_root, "rev-parse", "HEAD")
    return head if code == 0 and _SHA_SHAPE.match(head or "") else None


def _done_task(task, now, commit, descriptive, technical, verified, intent,
               intent_basis=None, no_change=None):
    """Close one task; returns the values it held before.

    THE FIELDS ARE `reference/orchestrator.md`'s STEP 4 VERBATIM -- 4b's *Set
    `task.status = "done"`, `task.completedAt = <ISO now>`, fill `task.outcome` and
    `task.verifiedBy`* and 4c's *Capture the SHA ... and write it into
    `task.commit`* -- because this verb exists to BE those two Edits. `_start_task`
    states the rule one verb over: a writer that stamped anything the prescribed
    Edit does not would make two records of one run disagree depending on which
    route closed the task.

    `completedAt` AND `commit` ARE WRITTEN UNCONDITIONALLY, which the terminal
    refusal in `_locked_done` is what makes safe: the only task reaching here is an
    unfinished one, so there is no earlier close to overwrite.

    THE OUTCOME HALVES ARE TOUCHED ONLY WHEN THE CALLER PASSED THEM, and `None`
    (the flag absent) is told apart from `""` (the flag passed empty). That is not
    tidiness: step 4's test-failure arm writes the last red gate's reason into
    `outcome.technical` and the retry brief quotes it back from there, so a close
    that nulled the half nobody mentioned would delete the record of how the work
    got here on its way to saying it arrived.

    `intent` FOLLOWS THE SAME RULE, and for the reason this task exists: `None`
    (the reviewer's call was never made, or its answer never reached this close)
    leaves `task.intentCheck` untouched -- absent on a task that has never closed
    before, which is what makes absence read as NO ANSWER rather than agreement.
    A caller that passed one of the three words gets a whole new block, `commit`
    included: the answer NAMES the diff it was given, because the reviewer read
    the working tree the moment before this same commit and nothing else on the
    record ties the two together.

    `not-asked` IS THE ONE ANSWER NO REVIEWER GAVE, so its `basis` is required
    by the door and written beside it: a skip with no reason on the record reads
    exactly like a reviewer call that never came back.

    `no_change` IS THE CLOSE WITH NO COMMIT, `{reason, examinedAt}` into
    `outcome.noChange`: `commit` stays None because nothing was committed, and
    the HEAD that was examined is what the claim "nothing needed to change" was
    measured against.

    THE PRIOR VALUES ARE READ BEFORE THE WRITE, for `_locked_cancel`'s reason two
    verbs over: afterwards every one of them says `done`, and the `from` half of
    the journal row is gone from the manifest as well as from the row.
    """
    prior = task.get("outcome") if isinstance(task.get("outcome"), dict) else {}
    was = {"status": task.get("status"),
           "completedAt": task.get("completedAt"),
           "commit": task.get("commit"),
           "descriptive": prior.get("descriptive"),
           "technical": prior.get("technical"),
           "noChange": prior.get("noChange"),
           "verifiedBy": task.get("verifiedBy"),
           "intentCheck": task.get("intentCheck")
           if isinstance(task.get("intentCheck"), dict) else None}
    task["status"] = "done"
    task["completedAt"] = now
    task["commit"] = commit
    if descriptive is not None or technical is not None or no_change is not None:
        outcome = task.get("outcome")
        if not isinstance(outcome, dict):
            outcome = {}
        if descriptive is not None:
            outcome["descriptive"] = descriptive
        if technical is not None:
            outcome["technical"] = technical
        if no_change is not None:
            outcome["noChange"] = no_change
        task["outcome"] = outcome
    if verified is not None:
        task["verifiedBy"] = verified
    if intent is not None:
        task["intentCheck"] = {"answer": intent, "commit": commit, "at": now}
        if intent_basis is not None:
            task["intentCheck"]["basis"] = intent_basis
    return was


def _done_changes(tid, was, task):
    """The `changes` rows for a close -- id/field/from/to, one per field WRITTEN.

    THE SHAPE IS THE ALLOW-LIST'S (`_journal_io.DETAILS_KEYS` carries `changes` and
    drops anything unlisted in silence), which is `_start_changes`' reasoning
    unchanged.

    WHERE THIS DIFFERS FROM `_start_changes` IS THE OPTIONAL HALF, and the
    difference is what each row asserts. `start` writes three fields every time, so
    filtering by equality there would hide which fields the verb even touches. Here
    `status`, `completedAt` and `commit` are written every time and the outcome
    halves, `outcome.noChange`, `verifiedBy` and `intentCheck` only when the
    caller passed them -- so a
    row for an untouched one would claim a write that did not happen, which is the
    opposite mistake and the worse one on a trail.
    """
    rows = [{"id": tid, "field": "status",
             "from": was["status"], "to": task.get("status")},
            {"id": tid, "field": "completedAt",
             "from": was["completedAt"], "to": task.get("completedAt")},
            {"id": tid, "field": "commit",
             "from": was["commit"], "to": task.get("commit")}]
    outcome = task.get("outcome") if isinstance(task.get("outcome"), dict) else {}
    for half in ("descriptive", "technical", "noChange"):
        if outcome.get(half) != was.get(half):
            rows.append({"id": tid, "field": "outcome.%s" % half,
                         "from": was.get(half), "to": outcome.get(half)})
    if task.get("verifiedBy") != was["verifiedBy"]:
        rows.append({"id": tid, "field": "verifiedBy",
                     "from": was["verifiedBy"], "to": task.get("verifiedBy")})
    if task.get("intentCheck") != was["intentCheck"]:
        rows.append({"id": tid, "field": "intentCheck",
                     "from": was["intentCheck"], "to": task.get("intentCheck")})
    return rows


def _done_details(task_id, phase_id, was, task):
    """The `details` block for a `task.done` row, built where a case can read it.

    SEPARATE FROM THE APPEND FOR `_start_details`' REASON, word for word:
    `_journal_io` drops a key that is not on `DETAILS_KEYS` in SILENCE, so a row
    read back out of the trail looks identical whether the writer handed over an
    allow-listed block or one carrying an invented key beside it -- and no
    assertion about the WRITTEN row can see the difference. Built here, the
    handover is the thing a case compares against the allow-list.

    `commit` AND `completedAt` ARE BOTH ALREADY ON THAT LIST, put there by the
    hook's own derived rows, so this row invents no vocabulary of its own.
    """
    details = {"taskId": task_id, "phaseId": phase_id,
               "changes": _done_changes(task_id, was, task),
               "completedAt": task.get("completedAt")}
    if task.get("commit"):
        details["commit"] = task.get("commit")
    return details


def _journal_done(project, config, mpath, task_id, phase_id, was, task):
    """The `task.done` row: what closed, against which commit, and out of what.

    NOT `task.complete`. That action and `task.commit` are DERIVED by
    `hooks/journal-writes.py` from the write itself, and `reference/
    orchestrator.md` step 4c forbids appending them by hand -- two writers means
    duplicate rows and a doctor whose completion count is no longer a count. This
    row is the verb's own, the way `task.start` and `task.cancel` are, and it is
    the only record of the close on a machine where that hook never runs.

    THE SHA RIDES THE SUMMARY TOO, for the reason `_journal_cancel` gives about its
    reason: `audit-journal list` prints the summary and nothing else, and the
    commit is the one thing a reader of a finished task is looking for. It exposes
    nothing new -- the same SHA is in the manifest this row is about.
    """
    no_change = _commit_trail.no_change_close(task)
    if no_change is not None:
        # The reason rides the summary and `details.reason`, `_journal_cancel`'s
        # rule for a why: a close with no commit has nothing else to name.
        summary = ("%s done in %s with no change, was %s: %s"
                   % (task_id, phase_id, was["status"], no_change.get("reason")))
        details = _done_details(task_id, phase_id, was, task)
        details["reason"] = no_change.get("reason")
        return _journal_row(project, config, mpath, "task.done", summary, details)
    summary = ("%s done in %s: commit %s, was %s"
               % (task_id, phase_id, str(task.get("commit") or "")[:12],
                  was["status"]))
    return _journal_row(project, config, mpath, "task.done", summary,
                        _done_details(task_id, phase_id, was, task))



def _close_gate(project, mpath, manifest, phase, task):
    """`_verdict_binding.task_binding` in a close's words.

    A NO-CHANGE CLOSE ASKS IT TOO. Its claim is that the code as it stands
    needed nothing, and a recorded verdict that no longer holds - a red above
    all - is a measurement of that code saying otherwise; one left by an attempt
    since abandoned is answered by a green run, or by the override with its
    reason.

    ACCEPTED: A COMMIT OVERRIDDEN IS ASKED AGAIN HERE. A task committed with
    `commit-task-work.py --override-verdict` over a verdict that does not hold
    is refused again at this close and needs its own `--override-verdict`, so
    one decision leaves two rows. They are two acts - committing work, and
    recording it finished - and the trail says each was done over the verdict;
    a close that trusted the commit's override would let one reason given for
    one act stand for the other."""
    tid, pid = str(task.get("id")), str(phase.get("id"))
    record = ("run `%s` on the work, then close it"
              % (_plugin_cmd("governance/run-test-gate.py",
                             _output.posix_rel(mpath, project), pid, "--task",
                             tid, "--record"),))
    return _vb.task_binding(
        project, mpath, manifest, phase, task, record,
        "%s declares no gate, nor does its phase, so its close rests on its "
        "commit alone" % (tid,))


def _gate_lines(gate, refusal, override):
    """The lines a close owes about the verdict it stood on, the override and an
    override given with nothing to go over included."""
    if refusal:
        return ["  gate: CLOSED OVER ITS VERDICT'S REFUSAL - %s" % (refusal,),
                "  %s: %s (journaled as %s)"
                % (_vb.OVERRIDE_FLAG, override, _vb.ACTION_CLOSE_OVERRIDDEN)]
    lines = ["  gate: %s" % (_vb.close_line(gate),)]
    if override is not None:
        lines.append("  %s was given and not needed: the verdict refuses nothing "
                     "here, so no exception was journaled" % (_vb.OVERRIDE_FLAG,))
    return lines


def _gate_key(gate, refusal, override):
    """The `--json` shape of `_gate_lines`."""
    return {"state": gate.get("state"), "arm": gate.get("arm"),
            "sentence": gate.get("sentence"),
            "runId": (gate.get("row") or {}).get("runId"),
            "overridden": bool(refusal),
            "overrideReason": override if refusal else None}


def _still_open(phase):
    """The ids in `phase` that are not finished -- `_mio.TERMINAL` is the word.

    Read AFTER the close, so the task this call just finished is already out of it.
    Cancelled counts as finished for the validator's reason one module over: a
    phase that signed off around dropped work is not a slip.
    """
    return [str(t.get("id")) for t in (phase.get("tasks") or [])
            if isinstance(t, dict) and t.get("status") not in _mio.TERMINAL]


def _locked_done(args, project, config, mpath, tid, out):
    """Close one task, under the lock, with a row and a revalidation -- the path
    every mutating verb in this file takes.

    THE TERMINAL REFUSAL IS `_locked_start`'s AND `_locked_cancel`'s, and it is
    named the same way by both: re-closing a `done` or `cancelled` task would
    rewrite history with no record of what it said before, and a `done` task
    already carries a commit that was graded against the scope it holds.

    A TASK THAT WAS NEVER STARTED IS REFUSED, NOT WARNED, and that is the decision.
    `pending` with no attempt recorded means no spawn was ever written down, so the
    close would lay a terminal state over a hole -- and terminal is exactly the
    state this file will not re-decide, so the hole could afterwards be filled by
    no verb here. It is also the shape `/audit:doctor` reads as POSITIVE evidence
    that the manifest was edited outside the pipeline (a done task inside the
    completion-record era with no receipt), so warning and writing would
    manufacture that finding rather than report it. The remedy costs one command
    and nothing irreversible, so the refusal names it. `_started` is the predicate
    rather than a second reading of `status`: that function already holds the two
    independent signals -- a task put back to `pending` carrying its count, and a
    task moved to `blocked` before its first spawn -- and this verb must not have a
    third opinion about what "has been attempted" means.

    THE PHASE IS REPORTED AND NEVER FLIPPED, which is `start`'s shape for the other
    end of the lifecycle. `reference/orchestrator.md`'s *Phase sign-off* is a
    strict-order procedure -- review resolution, the reviewer agent, the test gate,
    the invariant check, the optional runtime boot, the merge -- and only its last
    step writes `phase.status = "done"`, beside `phase.review.status`,
    `review.outcome` and `mergedAt`. A verb that flipped the phase because the last
    task closed would be asserting every one of those happened: the status IS the
    claim that sign-off passed, and this verb holds no basis for it. So the last
    close says sign-off is due and leaves the field alone, which the `pd` group in
    `plugins/audit/tests/test_audit_task.py` pins in both directions.
    """
    try:
        raw_index = _mio.read_json(mpath)
        assembled = _mio.load_manifest(mpath)
    except Exception as exc:
        out("[audit-task] cannot read/assemble manifest: %s" % exc)
        return E_USAGE
    vm = _validator()
    pre_findings, _w = vm.validate(assembled)
    if pre_findings:
        out("[audit-task] the manifest is already invalid -- nothing written; "
            "fix these first:")
        for line in pre_findings:
            out("FINDING: " + line)
        return E_INVALID

    kind, node, phase = _find_target(assembled, tid)
    if kind is None:
        out("[audit-task] no task with id %r in %s" % (tid, mpath))
        return E_USAGE
    if kind != "task":
        # A phase reaches `done` through sign-off, not here, and the ids look
        # alike enough that guessing is wrong -- `_locked_start` draws the same
        # line at the other end.
        out("[audit-task] %s is a PHASE -- `done` closes one task, and a phase "
            "reaches done only through sign-off (/audit:review %s), which writes "
            "the review verdict and the merge stamp beside the status"
            % (tid, tid))
        return E_USAGE
    status = node.get("status")
    if status in _mio.TERMINAL:
        out("[audit-task] %s is already %s -- terminal work is not re-closed by "
            "this verb (edit the manifest deliberately if it is wrong)"
            % (tid, status))
        return E_USAGE
    if not _started(node):
        out("[audit-task] %s is %s and records no attempt, so closing it would "
            "lay a terminal state over a hole: nothing says the work was ever "
            "spawned, and `done` is the one state this verb will not re-decide "
            "afterwards. Record the attempt first (/audit:task start %s), then "
            "close it." % (tid, status, tid))
        return E_USAGE
    # Where git runs: `_doctor_setup.check_git`'s spelling, byte for byte -- the
    # project plus the config's `gitRoot`, absolute, for a workspace whose
    # repository is a subdirectory. A third answer here would send this verb to a
    # different repository from the one the doctor grades the same SHA in, and the
    # two verdicts would then disagree about one manifest.
    git_root = os.path.abspath(os.path.join(project,
                                            (config or {}).get("gitRoot") or "."))
    no_change, unverified = None, None
    if args.no_change:
        # A BUG IS NEVER FIXED WITHOUT A FIX COMMIT. A done fix task derives its
        # bug `fixed` whatever its commit, so a no-change close would store the bug
        # fixed with no `fixedIn` - and the release guard stops counting it as
        # open. "Nothing needed to change" about a bug is a human verdict on the
        # bug, which `/audit:bug close` records.
        bugs = sorted(set(
            [str(node["bugId"])] if node.get("bugId") else []) | set(
            str(b.get("id")) for b in (assembled.get("bugs") or [])
            if isinstance(b, dict) and b.get("taskId") == tid and b.get("id")))
        if bugs:
            # CANCEL FIRST: `/audit:bug close` refuses while the bug's task is
            # in progress, and this task has started, so the other order fails
            # at its first step.
            out("[audit-task] %s is the fix task of %s -- a no-change close would "
                "mark the bug fixed with no fix commit. If nothing needed to "
                "change, cancel this task first (/audit:task cancel %s --reason "
                "...), then record the verdict on the bug: /audit:bug close %s "
                "not_a_bug|wontfix" % (tid, ", ".join(bugs), tid, bugs[0]))
            return E_USAGE
        sha = None
        no_change = {"reason": args.reason.strip(),
                     "examinedAt": _examined_head(git_root)}
    else:
        sha = (args.commit or "").strip()
        shape = _commit_shape_refusal(sha)
        if shape:
            out(shape)
            return E_USAGE
        refusal, unverified = _commit_git_note(git_root, sha)
        if refusal:
            out(refusal)
            return E_USAGE
    gate = _close_gate(project, mpath, assembled, phase, node)
    override = (args.override_verdict or "").strip() or None
    refused = _vb.close_refusal(gate)
    if refused and override is None:
        out("[audit-task] REFUSED: %s cannot close over its newest gate verdict - "
            "%s. Nothing written." % (tid, refused))
        out("    or pass %s \"<why this closes over it>\", which is journaled as %s"
            % (_vb.OVERRIDE_FLAG, _vb.ACTION_CLOSE_OVERRIDDEN))
        return E_USAGE
    # THE PROJECT'S OWN CONFIG, where `journal.enabled` lives. `_journal_cfg`
    # answers where a row is written and hands back None for a project that has
    # a config, which reads as enabled whatever the config says.
    if refused and not _journal_io.enabled(config or {}):
        out("[audit-task] REFUSED: %s was given and journal.enabled is false, so "
            "the close over its verdict would be recorded nowhere - an exception "
            "nobody can find afterwards is a gate quietly removed. The verdict: "
            "%s. Nothing written." % (_vb.OVERRIDE_FLAG, refused))
        return E_USAGE

    now = _utc_now()
    verified = None if args.verified_by is None else _split_csv(args.verified_by)
    was = _done_task(node, now, sha, args.descriptive, args.technical, verified,
                     args.intent, intent_basis=args.intent_basis,
                     no_change=no_change)
    phase_id = phase.get("id")
    # A bug this task fixes derives `fixed` (and its `fixedIn`) from this close, so
    # both are stored on the bug - in the index, which is where `bugs[]` lives.
    settled = _settle(assembled, set(
        ("bug", b.get("id")) for b in (assembled.get("bugs") or [])
        if isinstance(b, dict) and b.get("taskId") == tid))
    snap = _snapshot(_write_paths(project, mpath, raw_index, phase_id))
    try:
        written = _write_add(project, mpath, raw_index, assembled, phase_id, False,
                             index_fields=("bugs",) if settled else ())
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
        out("[audit-task] REFUSED: the close would leave the manifest invalid "
            "-- every written file rolled back, nothing kept:")
        for line in findings:
            out("FINDING: " + line)
        return E_INVALID
    if refused:
        # AFTER THE WRITE STANDS AND BEFORE ANYTHING ELSE IS SAID: a close over
        # its verdict that the trail did not take is rolled back, so no `done`
        # stands over a refusal with nothing saying why.
        ids = {"taskId": tid, "phaseId": phase_id}
        taken = _journal_row(project, config, mpath, _vb.ACTION_CLOSE_OVERRIDDEN,
                             _vb.override_summary(ids, gate, override),
                             _vb.override_details(ids, gate, override))
        if not taken.get("journaled"):
            _restore(snap)
            out("[audit-task] REFUSED: the journal row recording the close over "
                "its verdict could NOT be written, so every written file was "
                "rolled back and nothing kept. The verdict: %s" % (refused,))
            return E_INVALID

    jres = _journal_done(project, config, mpath, tid, phase_id, was, node)
    index_note = _index_dirty_note(written, mpath, project, phase_id)
    branch_note = _phase_branch_note(git_root, phase, cwd=git_root)
    open_left = _still_open(phase)
    outcome = node.get("outcome") if isinstance(node.get("outcome"), dict) else {}
    if args.as_json:
        result = {"ok": True, "id": tid, "phase": phase_id,
                  "status": node.get("status"),
                  "completedAt": node.get("completedAt"),
                  "commit": node.get("commit"),
                  # None for a no-change close: there is no commit to have
                  # verified, and False would read as one git could not find.
                  "commitVerified": (None if no_change is not None
                                     else unverified is None),
                  "noChange": no_change,
                  "was": was["status"],
                  "outcome": {"descriptive": outcome.get("descriptive"),
                              "technical": outcome.get("technical")},
                  "verifiedBy": node.get("verifiedBy"),
                  # ABSENT (None) is its own answer and reads apart from every
                  # word `intentCheck.answer` can hold - a close with no such
                  # answer must not render as one that agrees.
                  "intentCheck": node.get("intentCheck"),
                  "changes": _done_changes(tid, was, node),
                  "phaseOpenTasks": open_left,
                  "phaseComplete": not open_left,
                  "phaseStatus": _mio.effective_phase_status(phase),
                  "gate": _gate_key(gate, refused, override),
                  "stored": settled,
                  "written": written,
                  "warnings": _wg.collapse_machine(warnings, written_manifest)}
        result.update(jres)
        result.update(stdin_notes_key(args))
        result.update(project_basis_key(args))
        result.update(_index_dirty_key(index_note))
        result.update(_phase_branch_key(branch_note))
        out(json.dumps(result, indent=2, sort_keys=True))
        return 0
    out("[audit-task] %s done in %s -- was %s" % (tid, phase_id, was["status"]))
    out("  completedAt %s" % (node.get("completedAt"),))
    for line in _gate_lines(gate, refused, override):
        out(line)
    if no_change is not None:
        out("  commit none -- closed with NO CHANGE: %s" % (no_change["reason"],))
        out("  examinedAt: %s" % (no_change["examinedAt"] or
                                  "NOT RECORDED -- git could not name HEAD here, "
                                  "so the claim names no commit it was measured "
                                  "against",))
    else:
        out("  commit %s" % (node.get("commit"),))
    if unverified:
        out(unverified)
    # EACH LINE CARRIES ITS BASIS, THE ABSENT ONE INCLUDED. A close that said
    # nothing about the outcome would read as a close that recorded one; these are
    # the fields sign-off and the report render, and the caller is the only one who
    # can still supply them.
    for half, flag in (("descriptive", "--descriptive"),
                       ("technical", "--technical")):
        if outcome.get(half):
            out("  outcome.%s: %s" % (half, outcome[half]))
        else:
            out("  outcome.%s: not recorded -- pass %s" % (half, flag))
    if node.get("verifiedBy"):
        out("  verifiedBy: %s" % ", ".join(str(v) for v in node["verifiedBy"]))
    else:
        out("  verifiedBy: not recorded -- pass --verified-by with the test "
            "names this task added")
    # NO ANSWER READS DIFFERENTLY FROM A NEGATIVE ONE, which is the whole
    # point of this line: a reviewer call that never reached this close and
    # an explicit `diverges` are opposite facts, and a shared "not recorded"
    # sentence would flatten them into one. The word itself is quoted rather
    # than paraphrased, the same rule `--descriptive`/`--technical` follow.
    intent_check = node.get("intentCheck")
    if isinstance(intent_check, dict) and intent_check.get("answer"):
        out("  intentCheck: %s (commit %s)%s"
            % (intent_check["answer"], intent_check.get("commit") or "none",
               " -- basis: %s" % intent_check["basis"]
               if intent_check.get("basis") else ""))
    else:
        out("  intentCheck: NO ANSWER RECORDED -- pass --intent %s"
            % ("|".join(INTENT_ANSWERS),))
    if open_left:
        out("  %s still has open work: %s" % (phase_id, ", ".join(open_left)))
    else:
        out("  %s has no open task left -- SIGN-OFF is what closes a phase and "
            "this verb does not: it reads %r, sign-off due, until the review "
            "(/audit:review %s) is recorded with /audit:phase signoff %s"
            % (phase_id, _mio.effective_phase_status(phase), phase_id, phase_id))
    for line in _settled_lines(settled):
        out(line)
    for line in _wg.collapse(warnings, written_manifest):
        out("WARNING: " + line)
    if not jres.get("journaled") and jres.get("journaledWhy") == "failed":
        out(_not_journaled_line(jres, "the task.done row"))
    out("  written: %s" % ", ".join(written))
    if index_note:
        out(index_note)
    if branch_note:
        out(branch_note)
    return 0


# --- reopen: a done task back to pending, or a refusal naming the way forward ---
# `commands/run.md`'s re-open was a hand edit of six task fields and the linked
# bug's two, which is why it had no refusal: nothing asked what the phase around the
# task said. A SIGNED-OFF PHASE REFUSES, closed or awaiting its merge. Its verdict
# reviewed the work as it stands and sign-off is not re-decided, so a task re-opened
# under it could never be signed off again - and once the phase's `done` is stored,
# a stored done winning inside the derivation leaves `done` over open work, a
# finding every verb after it refuses on, the one that would close the task
# included. New work under a signed-off phase is a new task in an open phase, or a
# bug.
def cmd_reopen(args, out):
    project = _resolve_project(args)
    if not os.path.isdir(project):
        out("[audit-task] not a directory: %s" % project)
        return E_USAGE
    tid = (args.title or "").strip()          # positional: the id to re-open
    if not tid:
        out("[audit-task] reopen needs a task id")
        return E_USAGE
    reason = (args.reason or "").strip()
    if not reason:
        out("[audit-task] reopen needs --reason \"<why>\" -- undoing a close with "
            "no recorded why is the hand edit this verb replaces")
        return E_USAGE
    return _under_lock(args, project, out,
                       lambda config, mpath: _locked_reopen(
                           args, project, config, mpath, tid, reason, out))


def _reopen_refusal(kind, node, phase, tid):
    """Why `tid` cannot be re-opened, or None."""
    if kind is None:
        return "no task with id %r in this plan" % (tid,)
    if kind != "task":
        return ("%s is a PHASE -- `reopen` takes one task id, and a phase is "
                "closed by sign-off, which is not re-decided" % (tid,))
    if node.get("status") != "done":
        return ("%s is %s, not done -- there is no close to undo"
                % (tid, node.get("status")))
    pid = phase.get("id")
    if _mio.effective_phase_status(phase) in _mio.TERMINAL \
            or _mio.signoff_recorded(phase):
        return ("%s's phase %s is signed off (%s) -- its verdict reviewed the work "
                "as it stands and is not re-decided, so a task re-opened under it "
                "could never be signed off again. Put the new work in an open "
                "phase (/audit:task add \"<title>\" --phase <open phase>), or "
                "report it as a bug (/audit:bug add)"
                % (tid, pid, _mio.effective_phase_status(phase)
                   if _mio.effective_phase_status(phase) in _mio.TERMINAL
                   else "review.status %s" % ((phase.get("review") or {})
                                              .get("status"),)))
    return None


def _unresolve_findings(assembled, tid):
    """`(phase_ids, changes)` after taking `tid`'s commit off every review finding
    that recorded it as its fix - mutating those phases' reviews in place.

    A FINDING'S FIX COMMIT IS A COPY taken when `resolve-finding` ran, and the
    tally counts the copies. A re-opened task has no close any more, so a finding
    still naming its commit would go on reading as fixed by work the plan has just
    undone. `fixTask` stays - the task is still the one meant to fix it - and the
    resolution goes back to what the reviewer asked for.
    """
    phase_ids, changes = [], []
    for ph in (assembled.get("phases") or []):
        review = ph.get("review") if isinstance(ph, dict) else None
        listed = review.get("findings") if isinstance(review, dict) else None
        if not isinstance(listed, list):
            continue
        hits = [i for i, f in enumerate(listed) if isinstance(f, dict)
                and f.get("fixTask") == tid and f.get("commit")]
        if not hits:
            continue
        findings = list(listed)
        for i in hits:
            was = findings[i]
            entry = dict(was)
            entry.pop("commit", None)
            asked = _FIXED_PREFIX.sub("", (was.get("resolution") or "").strip())
            entry["resolution"] = asked or was.get("resolution")
            findings[i] = entry
            changes.append({"id": was.get("id"), "field": "commit",
                            "from": was.get("commit"), "to": None})
        was_outcome = review.get("outcome")
        new_review = dict(review, findings=findings,
                          outcome=outcome_with_tally(was_outcome, findings))
        changes.append({"id": ph.get("id"), "field": "review.outcome",
                        "from": _journal_outcome(was_outcome),
                        "to": _journal_outcome(new_review["outcome"])})
        ph["review"] = new_review
        phase_ids.append(ph.get("id"))
    return phase_ids, changes


def _locked_reopen(args, project, config, mpath, tid, reason, out):
    try:
        raw_index = _mio.read_json(mpath)
        assembled = _mio.load_manifest(mpath)
    except Exception as exc:
        out("[audit-task] cannot read/assemble manifest: %s" % exc)
        return E_USAGE
    vm = _validator()
    pre_findings, _w = vm.validate(assembled)
    if pre_findings:
        out("[audit-task] the manifest is already invalid -- nothing written; "
            "fix these first:")
        for line in pre_findings:
            out("FINDING: " + line)
        return E_INVALID
    kind, node, phase = _find_target(assembled, tid)
    refusal = _reopen_refusal(kind, node, phase, tid)
    if refusal:
        out("[audit-task] " + refusal)
        return E_USAGE
    phase_id = phase.get("id")
    changes = []

    def put(holder, rid, field, value):
        if holder.get(field) != value:
            changes.append({"id": rid, "field": field, "from": holder.get(field),
                            "to": value})
        holder[field] = value

    put(node, tid, "status", "pending")
    put(node, tid, "attempts", 0)
    put(node, tid, "commit", None)
    put(node, tid, "completedAt", None)
    put(node, tid, "verifiedBy", [])
    put(node, tid, "outcome", {"technical": None, "descriptive": None})
    if "intentCheck" in node:
        changes.append({"id": tid, "field": "intentCheck",
                        "from": node.pop("intentCheck"), "to": None})
    bugs = [b for b in (assembled.get("bugs") or [])
            if isinstance(b, dict) and b.get("taskId") == tid
            and b.get("status") not in _mio.HUMAN_BUG_VERDICT]
    for bug in bugs:
        put(bug, bug.get("id"), "status", "in_progress")
        put(bug, bug.get("id"), "fixedIn", None)
    unresolved, finding_changes = _unresolve_findings(assembled, tid)
    changes.extend(finding_changes)
    phase_ids = [phase_id] + [p for p in unresolved if p != phase_id]
    snap = _snapshot([path for pid in phase_ids
                      for path in _write_paths(project, mpath, raw_index, pid)])
    try:
        written = []
        for pid in phase_ids:
            for rel in _write_add(project, mpath, raw_index, assembled, pid, False,
                                  index_fields=("bugs",) if bugs else ()):
                if rel not in written:
                    written.append(rel)
    except Exception as exc:
        _restore(snap)
        out("[audit-task] write failed -- manifest restored: %s" % exc)
        return E_INVALID
    try:
        written_manifest = _mio.load_manifest(mpath)
        findings, warnings = vm.validate(written_manifest)
    except Exception as exc:
        written_manifest, findings, warnings = {}, ["cannot re-read the written "
                                                    "manifest: %s" % exc], []
    if findings:
        _restore(snap)
        out("[audit-task] REFUSED: the re-open would leave the manifest invalid "
            "-- every written file rolled back, nothing kept:")
        for line in findings:
            out("FINDING: " + line)
        return E_INVALID
    jres = _journal_row(project, config, mpath, "task.reopen",
                        "%s re-opened in %s: %s" % (tid, phase_id, reason),
                        {"taskId": tid, "phaseId": phase_id, "reason": reason,
                         "changes": changes})
    index_note = _index_dirty_note(written, mpath, project, phase_id)
    if args.as_json:
        result = {"ok": True, "id": tid, "phase": phase_id, "status": "pending",
                  "reason": reason, "changes": changes,
                  "bugs": [b.get("id") for b in bugs], "written": written,
                  "warnings": _wg.collapse_machine(warnings, written_manifest)}
        result.update(jres)
        result.update(stdin_notes_key(args))
        result.update(project_basis_key(args))
        result.update(_index_dirty_key(index_note))
        out(json.dumps(result, indent=2, sort_keys=True))
        return 0
    out("[audit-task] %s re-opened in %s -- pending, its close cleared: %s"
        % (tid, phase_id, reason))
    for bug in bugs:
        out("  bug %s back to in_progress, fixedIn cleared" % (bug.get("id"),))
    for change in finding_changes:
        if change["field"] == "commit":
            out("  finding %s no longer records a fix commit" % (change["id"],))
    for line in _wg.collapse(warnings, written_manifest):
        out("WARNING: " + line)
    if not jres.get("journaled") and jres.get("journaledWhy") == "failed":
        out(_not_journaled_line(jres, "the task.reopen row"))
    out("  written: %s" % ", ".join(written))
    if index_note:
        out(index_note)
    return 0


# --- block, note, move: the hand edits operators kept making ---------------------
# Each of these was a documented or reported hand edit: `blocked` set with the
# reason living nowhere but a chat, a finding appended to a description `scope`
# refuses on a started task, and `commands/task.md`'s six-step move procedure run
# with Edit. They take the path every mutating verb here takes - the index lock,
# validate before and after, byte-for-byte rollback on findings, a journal row.
def _validator():
    """The manifest rules with the plan schema LOADED ONCE and bound in.

    A verb validates before its write and again after it; both calls share
    the one schema read here, so `validate()` itself reads no file. A schema
    that cannot be read is this entry point's finding: it is carried on every
    validation the verb makes, so a verb with a pre-write check refuses there,
    and it is exposed as `unreadable` for the verbs that validate only after
    writing, which refuse on it up front (`_refuse_broken_install`)."""
    rules = _panel_write._cores()[0]
    schema, unreadable = rules.load_validation_schema()

    def validate(manifest):
        findings, warnings = rules.validate(manifest, schema=schema)
        return list(unreadable) + findings, warnings
    return types.SimpleNamespace(validate=validate, unreadable=list(unreadable))


def _refuse_broken_install(vm, out):
    """E_INVALID after saying so, or None: a verb whose only validation runs
    after its write asks this first, so a broken install is refused before
    anything is written rather than rolled back as if the change were at fault."""
    if not vm.unreadable:
        return None
    out("[audit-task] the plugin install is broken -- nothing written:")
    for line in vm.unreadable:
        out("FINDING: " + line)
    return E_INVALID


def _read_plan(mpath, out):
    """`(raw_index, assembled, validator)`, or the exit code after saying why not.

    The read and the refusal of an already-invalid plan that every verb below
    starts with: a write laid on top of findings would be blamed for them.
    """
    try:
        raw_index = _mio.read_json(mpath)
        assembled = _mio.load_manifest(mpath)
    except Exception as exc:
        out("[audit-task] cannot read/assemble manifest: %s" % exc)
        return E_USAGE
    vm = _validator()
    pre_findings, _w = vm.validate(assembled)
    if pre_findings:
        out("[audit-task] the manifest is already invalid -- nothing written; "
            "fix these first:")
        for line in pre_findings:
            out("FINDING: " + line)
        return E_INVALID
    return raw_index, assembled, vm


def _write_plan(project, mpath, raw_index, assembled, vm, phase_ids, what, out,
                files_changed=False, index_fields=()):
    """`(written, written_manifest, warnings)`, or the exit code after a rollback.

    SEVERAL PHASES IN ONE WRITE, which is what `move` needs and `_write_add`
    alone does not do: the task leaves one shard and joins another, and a
    reference to it can sit in a third. Every file any of them may touch is
    snapshotted BEFORE the first write, so a refusal restores all of them.
    """
    paths = [mpath]
    for pid in phase_ids:
        for path in _write_paths(project, mpath, raw_index, pid):
            if path not in paths:
                paths.append(path)
    snap = _snapshot(paths)
    written = []
    try:
        if not _mio.is_sharded(raw_index) or not phase_ids:
            written = _write_add(project, mpath, raw_index, assembled,
                                 phase_ids[0] if phase_ids else None,
                                 files_changed, index_fields=index_fields)
        else:
            for pid in phase_ids:
                for rel in _write_add(project, mpath, raw_index, assembled, pid,
                                      files_changed, index_fields=index_fields):
                    if rel not in written:
                        written.append(rel)
    except Exception as exc:
        _restore(snap)
        out("[audit-task] write failed -- manifest restored: %s" % exc)
        return E_INVALID
    try:
        written_manifest = _mio.load_manifest(mpath)
        findings, warnings = vm.validate(written_manifest)
    except Exception as exc:
        written_manifest, findings, warnings = {}, ["cannot re-read the written "
                                                    "manifest: %s" % exc], []
    if findings:
        _restore(snap)
        out("[audit-task] REFUSED: %s would leave the manifest invalid -- every "
            "written file rolled back, nothing kept:" % (what,))
        for line in findings:
            out("FINDING: " + line)
        return E_INVALID
    return written, written_manifest, warnings


def _task_target(assembled, tid, verb):
    """`(task, phase, None)` for a task id, or `(None, None, refusal)`.

    A phase id is refused by name for `_locked_done`'s reason: the ids look alike
    enough that guessing between them guesses wrong.
    """
    kind, node, phase = _find_target(assembled, tid)
    if kind is None:
        return None, None, "no task with id %r in this plan" % (tid,)
    if kind != "task":
        return None, None, ("%s is a PHASE -- `%s` takes one task id"
                            % (tid, verb))
    return node, phase, None


def _report_tail(out, jres, action, warnings, written_manifest, written,
                 index_note):
    """The lines every verb below ends on, in the order the others print them."""
    for line in _wg.collapse(warnings, written_manifest):
        out("WARNING: " + line)
    if not jres.get("journaled") and jres.get("journaledWhy") == "failed":
        out(_not_journaled_line(jres, "the %s row" % (action,)))
    out("  written: %s" % ", ".join(written))
    if index_note:
        out(index_note)


def _json_tail(result, args, jres, warnings, written_manifest, index_note):
    """The keys every verb's `--json` block carries beside its own."""
    result["warnings"] = _wg.collapse_machine(warnings, written_manifest)
    result.update(jres)
    result.update(stdin_notes_key(args))
    result.update(project_basis_key(args))
    result.update(_index_dirty_key(index_note))
    return json.dumps(result, indent=2, sort_keys=True)


# `block`: the status the orchestrator sets on exhausted attempts and on a
# refused start, and the one an operator sets for a dependency no id can name -
# another team's endpoint, a reply nobody has sent. `blockedBy` refuses such a
# dependency on purpose (nothing could clear it), so the reason lives beside the
# status, and `start` clears it when the task runs again.
def cmd_block(args, out):
    project = _resolve_project(args)
    if not os.path.isdir(project):
        out("[audit-task] not a directory: %s" % project)
        return E_USAGE
    tid = (args.title or "").strip()          # positional: the id to block
    if not tid:
        out("[audit-task] block needs a task id")
        return E_USAGE
    reason = (args.reason or "").strip()
    if not reason:
        out("[audit-task] block needs --reason \"<what it is waiting on>\" -- a "
            "task blocked with no recorded why is the hand edit this verb "
            "replaces, and nobody can tell when it may run again")
        return E_USAGE
    return _under_lock(args, project, out,
                       lambda config, mpath: _locked_block(
                           args, project, config, mpath, tid, reason, out))


def _locked_block(args, project, config, mpath, tid, reason, out):
    plan = _read_plan(mpath, out)
    if isinstance(plan, int):
        return plan
    raw_index, assembled, vm = plan
    node, phase, refusal = _task_target(assembled, tid, "block")
    if refusal:
        out("[audit-task] " + refusal)
        return E_USAGE
    status = node.get("status")
    if status in _mio.TERMINAL:
        out("[audit-task] %s is already %s -- terminal work is not blocked; the "
            "follow-up is a new task (/audit:task add)" % (tid, status))
        return E_USAGE
    if status == "blocked":
        out("[audit-task] %s is already blocked: %s -- the reason on record "
            "stands; add what changed with /audit:task note %s --text \"...\""
            % (tid, node.get("blockedReason") or "(no reason recorded)", tid))
        return E_USAGE
    phase_id = phase.get("id")
    changes = [{"id": tid, "field": "status", "from": status, "to": "blocked"},
               {"id": tid, "field": "blockedReason",
                "from": node.get("blockedReason"), "to": reason}]
    node["status"] = "blocked"
    node["blockedReason"] = reason
    wrote = _write_plan(project, mpath, raw_index, assembled, vm, [phase_id],
                        "the block", out)
    if isinstance(wrote, int):
        return wrote
    written, written_manifest, warnings = wrote
    jres = _journal_row(project, config, mpath, "task.block",
                        "%s blocked in %s, was %s: %s"
                        % (tid, phase_id, status, reason),
                        {"taskId": tid, "phaseId": phase_id, "reason": reason,
                         "changes": changes})
    index_note = _index_dirty_note(written, mpath, project, phase_id)
    linked = bool(((assembled.get("meta") or {}).get("ado") or {}))
    if args.as_json:
        out(_json_tail({"ok": True, "id": tid, "phase": phase_id,
                        "status": "blocked", "was": status, "reason": reason,
                        "changes": changes, "adoEchoOwed": linked,
                        "written": written},
                       args, jres, warnings, written_manifest, index_note))
        return 0
    out("[audit-task] %s blocked in %s -- was %s: %s"
        % (tid, phase_id, status, reason))
    if linked:
        out("  ADO: this plan links a board, and a task entering blocked owes the "
            "ADO echo (reference/orchestrator.md -> ADO echo) - this verb does "
            "not send it")
    _report_tail(out, jres, "task.block", warnings, written_manifest, written,
                 index_note)
    return 0


# `note`: append-only, which is what lets it reach a STARTED task. `scope
# --description` refuses one because its brief is what its attempts were judged
# against, and a finding that arrived since belongs beside the brief, dated,
# rather than in place of it.
def cmd_note(args, out):
    project = _resolve_project(args)
    if not os.path.isdir(project):
        out("[audit-task] not a directory: %s" % project)
        return E_USAGE
    tid = (args.title or "").strip()          # positional: the id to note on
    if not tid:
        out("[audit-task] note needs a task id")
        return E_USAGE
    text = (args.text or "").strip()
    if not text:
        out("[audit-task] note needs --text \"<what to record>\" -- an empty note "
            "records nothing and would still take a journal row")
        return E_USAGE
    return _under_lock(args, project, out,
                       lambda config, mpath: _locked_note(
                           args, project, config, mpath, tid, text, out))


def _locked_note(args, project, config, mpath, tid, text, out):
    plan = _read_plan(mpath, out)
    if isinstance(plan, int):
        return plan
    raw_index, assembled, vm = plan
    node, phase, refusal = _task_target(assembled, tid, "note")
    if refusal:
        out("[audit-task] " + refusal)
        return E_USAGE
    notes = node.get("notes")
    if notes is not None and not isinstance(notes, list):
        out("[audit-task] %s carries `notes` that is not a list (%s) -- nothing "
            "appended; an append onto a value of another shape would replace it"
            % (tid, type(notes).__name__))
        return E_USAGE
    phase_id = phase.get("id")
    entry = {"at": _utc_now(), "text": text}
    node["notes"] = list(notes or []) + [entry]
    wrote = _write_plan(project, mpath, raw_index, assembled, vm, [phase_id],
                        "the note", out)
    if isinstance(wrote, int):
        return wrote
    written, written_manifest, warnings = wrote
    changes = [{"id": tid, "field": "notes", "from": None, "to": entry}]
    jres = _journal_row(project, config, mpath, "task.note",
                        "%s note in %s: %s" % (tid, phase_id, text),
                        {"taskId": tid, "phaseId": phase_id, "changes": changes})
    index_note = _index_dirty_note(written, mpath, project, phase_id)
    if args.as_json:
        out(_json_tail({"ok": True, "id": tid, "phase": phase_id, "note": entry,
                        "notes": len(node["notes"]), "written": written},
                       args, jres, warnings, written_manifest, index_note))
        return 0
    out("[audit-task] %s note %d appended in %s at %s: %s"
        % (tid, len(node["notes"]), phase_id, entry["at"], text))
    _report_tail(out, jres, "task.note", warnings, written_manifest, written,
                 index_note)
    return 0


# `move`: `commands/task.md`'s procedure, performed rather than described. The
# new id comes from the allocator `next-id task` prints (so a moved task is
# numbered exactly as a hand-written one would have been), the references are
# rewritten by `_id_refs.rename` (the one list of fields that hold an id), and
# `movedFrom` is what lets a reader join ledger rows written under the old id.
def cmd_move(args, out):
    project = _resolve_project(args)
    if not os.path.isdir(project):
        out("[audit-task] not a directory: %s" % project)
        return E_USAGE
    tid = (args.title or "").strip()          # positional: the id to move
    if not tid:
        out("[audit-task] move needs a task id")
        return E_USAGE
    target = (args.to or "").strip()
    if not target:
        out("[audit-task] move needs --to <phaseId> -- the phase the task moves "
            "into")
        return E_USAGE
    return _under_lock(args, project, out,
                       lambda config, mpath: _locked_move(
                           args, project, config, mpath, tid, target, out))


def _move_refusal(node, phase, target_id):
    """Why this task cannot move to `target_id`, or None - `commands/task.md`'s
    refusals, in its order, after the id has resolved."""
    tid = node.get("id")
    if phase.get("id") == target_id:
        return "%s is already in %s -- nothing to move" % (tid, target_id)
    status = node.get("status")
    if status == "done":
        return ("%s is done -- done tasks are history. Re-open it first "
                "(/audit:task reopen %s --reason ...), then move it" % (tid, tid))
    if status == "cancelled":
        return ("%s is cancelled -- terminal work is not moved; the follow-up is "
                "a new task in %s (/audit:task add)" % (tid, target_id))
    if status == "in_progress":
        return ("%s is in_progress -- likely a live or interrupted run. Finish it "
                "or resume it (/audit:resume) before moving it" % (tid,))
    return None


def _runs_under(project, tid):
    """How many ledger rows name `tid` as their task, or None when the ledger
    cannot be read - an unread ledger is said as such, never counted as none."""
    try:
        rows = _evidence_io.read_rows(project)["rows"]
    except Exception:
        return None
    return len([r for r in rows if isinstance(r, dict) and r.get("scope") == "task"
                and str(r.get("taskId")) == str(tid)])


def _changed_phases(before, after):
    """The ids of the phases whose body differs between two assembled plans."""
    def bodies(doc):
        return dict((p.get("id"), json.dumps(p, sort_keys=True))
                    for p in (doc.get("phases") or []) if isinstance(p, dict))
    old, new = bodies(before), bodies(after)
    return [pid for pid in new if old.get(pid) != new[pid]]


def _locked_move(args, project, config, mpath, tid, target_id, out):
    plan = _read_plan(mpath, out)
    if isinstance(plan, int):
        return plan
    raw_index, assembled, vm = plan
    node, phase, refusal = _task_target(assembled, tid, "move")
    if refusal:
        out("[audit-task] %s; tasks: %s" % (refusal, ", ".join(
            sorted(str(k) for k in _mio.tasks_by_id(assembled))) or "(none)"))
        return E_USAGE
    # `commands/task.md`'s DOCUMENTED ORDER: that the target EXISTS is item 1,
    # the task's own status items 2-4, and the target's STATE item 5 - so the
    # phase is looked up first and judged only after the task has been.
    if _find_target(assembled, target_id)[0] != "phase":
        return _resolve_phase(assembled, target_id, out)
    refusal = _move_refusal(node, phase, target_id)
    if refusal:
        out("[audit-task] " + refusal)
        return E_USAGE
    target = _resolve_phase(assembled, target_id, out, what="a task moved into it now")
    if isinstance(target, int):
        return target
    if _mio.effective_phase_status(target) == "cancelled":
        out("[audit-task] phase %s is cancelled -- a task moved into it would be "
            "open work under a phase that will not run" % (target_id,))
        return E_USAGE
    new_id = _allocate_id(assembled, target_id, _mint_suffix(mpath, assembled))
    clash = _id_refs.collisions(assembled, {tid: new_id})
    if clash:
        out("[audit-task] the allocator named %s, which the plan already holds -- "
            "refused rather than merging two records" % (", ".join(clash),))
        return E_USAGE
    from_phase = phase.get("id")
    renamed, rewritten = _id_refs.rename(assembled, {tid: new_id})
    moved = None
    for ph in (renamed.get("phases") or []):
        if isinstance(ph, dict) and ph.get("id") == from_phase:
            keep = []
            for t in (ph.get("tasks") or []):
                if isinstance(t, dict) and t.get("id") == new_id and moved is None:
                    moved = t
                else:
                    keep.append(t)
            ph["tasks"] = keep
    # THE CHAIN IS KEPT: a second move nests the first one's record as
    # `previous`, so every id this task ever held stays taken for the allocator
    # and joinable for the evidence readers.
    prior = moved.get("movedFrom")
    moved["movedFrom"] = {"id": tid, "phase": from_phase, "at": _utc_now()}
    if isinstance(prior, dict):
        moved["movedFrom"]["previous"] = prior
    for ph in (renamed.get("phases") or []):
        if isinstance(ph, dict) and ph.get("id") == target_id:
            ph["tasks"] = list(ph.get("tasks") or []) + [moved]
    index_fields = tuple(key for key in ("bugs", "proposals")
                         if renamed.get(key) != assembled.get(key))
    files_changed = renamed.get("fileIndex") != assembled.get("fileIndex")
    phase_ids = _changed_phases(assembled, renamed)
    wrote = _write_plan(project, mpath, raw_index, renamed, vm, phase_ids,
                        "the move", out, files_changed=files_changed,
                        index_fields=index_fields)
    if isinstance(wrote, int):
        return wrote
    written, written_manifest, warnings = wrote
    # One reference is the task's own id, which `rename` counts beside the rest.
    refs = rewritten - 1
    jres = _journal_row(project, config, mpath, "task.move",
                        "%s -> %s (%s -> %s), %d reference(s) rewritten"
                        % (tid, new_id, from_phase, target_id, refs),
                        {"fromId": tid, "toId": new_id, "fromPhase": from_phase,
                         "toPhase": target_id, "taskId": new_id,
                         "phaseId": target_id})
    index_note = _index_dirty_note(written, mpath, project, target_id)
    waiting = _waiting_on(renamed, moved)
    left_runs = _runs_under(project, tid)
    # A BLOCKED task moves with its status, and readiness over its references
    # alone would print a copyable `/audit:run` for work that is not runnable.
    blocked = moved.get("status") == "blocked"
    if args.as_json:
        out(_json_tail({"ok": True, "from": tid, "id": new_id,
                        "fromPhase": from_phase, "phase": target_id,
                        "status": moved.get("status"),
                        "referencesRewritten": refs, "waitingOn": waiting,
                        "evidenceRunsLeft": left_runs,
                        "ready": not waiting and not blocked, "written": written},
                       args, jres, warnings, written_manifest, index_note))
        return 0
    out("[audit-task] %s moved to %s as %s -- %d reference(s) to it rewritten"
        % (tid, target_id, new_id, refs))
    if blocked:
        out("  not ready -- it is still blocked: %s"
            % (moved.get("blockedReason") or "(no reason recorded)",))
    else:
        for line in _readiness_lines(waiting, new_id):
            out(line)
    out("  ledger: historical rows keep %s - history is never rewritten; new spend "
        "attributes to %s, and movedFrom plus the task.move row are what join the "
        "two" % (tid, new_id))
    if left_runs is None:
        out("  evidence: the ledger could not be read, so what it holds under %s "
            "is unknown" % (tid,))
    elif left_runs:
        out("  evidence: %d recorded run(s) stay keyed to %s in the append-only "
            "ledger; /audit:doctor and --reconcile join them to %s through "
            "movedFrom, and the report's run history lists them under %s"
            % (left_runs, tid, new_id, tid))
    out("  other branches: a blockedBy/dependsOn on %s written there is not "
        "rewritten here, and surfaces as a validator finding at the merge"
        % (tid,))
    _report_tail(out, jres, "task.move", warnings, written_manifest, written,
                 index_note)
    return 0


# --- add-phase: one more phase in a plan that already exists ---------------------
# Everything that WROTE a phase before this verb wrote a whole plan or moved
# one that had already been written somewhere else, so "I have a live plan and a
# new body of work" was the one shape with no command behind it -- and it is the
# shape every plan reaches once its first round is finished.


def _allocate_phase_id(assembled):
    """The highest `P<n>` in use plus one, over live ids AND every parked
    reservation.

    ONE TAKEN SET, TWO RULES, and the comment above was right about the first
    half and wrong about the second. `live_ids | parked_ids` is the SAME pair
    `/audit:propose materialize` allocates against, because a second expression
    of "which phase ids are taken" would eventually hand this verb an id
    materialization had already promised to a payload. But the RULE over that
    set is `next_appended_phase_id` and not materialize's
    `next_phase_id`: filling a gap is harmless when re-placing a payload whose
    id collided, and reusing that same rule here is what produced the wrong ids
    below. Measured on a copy of this
    repository's own plan, consecutive calls to this verb returned `P0`, then
    `P30`, then `P32` -- and `P30` at that moment named four live branches and
    two merges into `main`, which `meta.branch` would have derived again from
    the id this handed back.
    """
    taken = _proposals.live_ids(assembled) | _proposals.parked_ids(assembled)
    return _proposals.next_appended_phase_id(taken)


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
            status = _mio.effective_phase_status(ph)
            if status in _mio.TERMINAL or _mio.signoff_recorded(ph):
                nxt = "pick another --id (that phase is finished history)"
            else:
                nxt = ("pick another --id, or add a task to it with "
                       "/audit:task add --phase %s" % (pid,))
            return ("[audit-task] phase %s already exists (%s) -- %s"
                    % (pid, status, nxt))
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
    # `--gate-clear` reaches the EMPTY gate here too, and this was the third
    # verb of the same shape after `scope` and `add`: the flag is
    # defined on the global parser, so argparse accepted it and this resolver
    # never looked -- the new phase inherited `meta.buildCommands` while the caller
    # was told the call succeeded. Measured: `--gate-clear` alone wrote `["lint"]`.
    #
    # Its basis is the FLAG rather than a sentence about the manifest, because that
    # is what makes it a different answer from the two empty cases below: those say
    # nothing here CAN prove the phase done, this says the caller decided nothing
    # should.
    # `--gate-clear` was advertised on this verb, accepted by the shared
    # parser and then never read here, so it silently left the gate at its
    # default -- the third verb of that exact shape after `scope` and
    # `add`. Spelled `args.gate_clear` rather than `getattr(args, ...)`:
    # the flag is `store_true` on the shared parser, so the attribute always
    # exists and the defensive form only hides a real `AttributeError` if the
    # parser ever stops declaring it.
    if args.gate_clear:
        return [], "from --gate-clear"
    if args.gate:
        return list(args.gate), "from --gate"
    meta = assembled.get("meta")
    build = (meta or {}).get("buildCommands") if isinstance(meta, dict) else None
    if not isinstance(build, dict):
        return [], "the manifest declares no meta.buildCommands"
    keys = [k for k in build.keys() if isinstance(k, str) and k.strip()]
    if not keys:
        return [], "meta.buildCommands is empty"
    # `phase_gate_default` IS THE DERIVATION -- `always` is an ORDER and never a
    # narrowing (an entry named in both `always` and `exclude` stays IN), and
    # `exclude` is the only declared way to drop a buildCommands key. Asking it
    # here rather than re-reading `meta.phaseGate` a second time is what keeps
    # this resolver, the validator's shape warnings and the sign-off run from
    # ever disagreeing about what "today's default" means.
    default = _phases.phase_gate_default(meta if isinstance(meta, dict) else {})
    entries, always, excluded = (default["entries"], default["always"],
                                 default["excluded"])
    if not entries:
        # CERTAIN, EVEN WITH NO EVIDENCE: `exclude` removed every buildCommands
        # key and `always` put none back, so there is nothing left to have run
        # whatever a future ledger says. `phase_gate_suite_gap` names the same
        # cause for the validator's own warning, printed among the post-write
        # warnings a moment after this basis is written.
        return [], ("meta.phaseGate.exclude drops every meta.buildCommands key "
                   "(%s)%s -- the new phase's gate is empty"
                   % (_output.some_of(excluded, render=repr),
                      " and meta.phaseGate.always adds none back" if not always
                      else ""))
    if not always and not excluded:
        # BYTE-IDENTICAL TO TODAY: no `meta.phaseGate` at all is `always` and
        # `exclude` both empty, so `entries` is exactly `keys` in buildCommands
        # order -- the sentence a phase without the field has always gotten.
        return entries, "from meta.buildCommands"
    if not excluded:
        return entries, "from meta.buildCommands, meta.phaseGate.always first"
    return entries, (
        "from meta.buildCommands%s; excluded by meta.phaseGate.exclude: %s -- "
        "declared out of this phase's gate, and the sign-off run prints it too"
        % (", meta.phaseGate.always first" if always else "",
           _output.some_of(excluded, render=repr)))


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

    vm = _validator()
    pre_findings, _pre_w = vm.validate(assembled)
    if pre_findings:
        out("[audit-task] the manifest is already invalid -- nothing "
            "written; fix these first:")
        for line in pre_findings:
            out("FINDING: " + line)
        return E_INVALID

    # The reason this arrived only now: while `--gate-clear` was inert
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
    side = _side_branch(mpath, assembled)
    if args.park:
        return _park_phase(args, project, config, mpath, raw_index, assembled,
                           phase, side, vm, out)
    warn_side = side["suffix"] is not None and not _side_branch_warned(
        project, config, mpath, side["branch"])
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
                              phase["desiredOutcome"],
                              side["branch"] if side["suffix"] else None)
    index_note = _index_dirty_note(written, mpath, project, pid)
    # ALWAYS None HERE, and not asked for: `_build_phase` seeds `branch: None`
    # (manifest-conventions -> New phase template), so a phase this write just
    # created has nothing yet for `_phase_branch_note` to compare against --
    # kept as a named constant rather than omitted so the JSON/report wiring
    # below is the same shape on every verb.
    branch_note = None
    waiting = _waiting_on(assembled, phase)
    if args.as_json:
        result = {"ok": True, "id": pid, "title": title, "phase": phase,
                  "written": written,
                  "warnings": _wg.collapse_machine(warnings, written_manifest),
                  "testGateBasis": gate_basis,
                  "ready": not waiting, "waitingOn": waiting}
        if side["suffix"] is not None:
            result["sideBranch"] = {"branch": side["branch"],
                                    "developmentBranch": side["development"],
                                    "warned": warn_side}
        result.update(jres)
        result.update(stdin_notes_key(args))
        result.update(project_basis_key(args))
        result.update(_index_dirty_key(index_note))
        result.update(_phase_branch_key(branch_note))
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
        out(_not_journaled_line(jres, "the phase.add row"))
    out("  written: %s" % ", ".join(written))
    if index_note:
        out(index_note)
    if branch_note:
        out(branch_note)
    if waiting:
        out("  waiting on: %s" % ", ".join(waiting))
    if warn_side:
        for line in _side_branch_warning(pid, side):
            out(line)
    out("  next: /audit:task add \"<the first task>\" --phase %s" % pid)
    return 0


# --- a phase minted on a side branch ---------------------------------------------
# PHASES ARE MINTED ON THE DEVELOPMENT BRANCH. A phase id is a branch name, a lock
# name and a shard name, so it is the one id `_id_shape` does not suffix - and the
# price is that two phase branches each adding a phase would both mint `P<max+1>`.
# The operator's rule answers it at the source: new work found on a phase branch
# is parked as a proposal and materialized on the development branch once that
# branch has merged. It is a WARNING and never a refusal, and it is said once per
# branch: a guard that refused would be routed around the first time the work was
# urgent, and one that repeated itself would stop being read.
def _side_branch(mpath, assembled):
    """{branch, suffix, development}: the branch standing beside `mpath`, the suffix
    it mints (None on a trunk branch), and the development branch it is not."""
    cwd = os.path.dirname(os.path.abspath(mpath))
    meta = assembled.get("meta") or {}
    return {"branch": _id_shape.current_branch(cwd),
            "suffix": _id_shape.suffix_here(cwd, assembled),
            "development": _branch.parent_branch(meta, None)["branch"]}


def _side_branch_warned(project, config, mpath, branch):
    """True when a phase was already minted on `branch` - read from the phase.add
    rows, which carry the branch, so "warned once" is a fact of the trail rather
    than a flag of its own. A journal that cannot be read reads as not warned:
    the warning then repeats, which is the failure that costs the least."""
    try:
        rows = _journal_io.read_all(project, _journal_cfg(config, mpath, project))
    except Exception:
        return False
    return any(r.get("action") == "phase.add"
               and (r.get("details") or {}).get("branch") == branch for r in rows)


def _side_branch_warning(pid, side):
    return ["WARNING: phase %s was minted on %s, not on the development branch %s. "
            "Phases belong on %s: merge this phase branch first, then materialize new "
            "phases there and commit that branch before starting them. Nothing was "
            "blocked; to park the next one instead, pass --park (it becomes a proposal "
            "to materialize after the merge). Said once for this branch."
            % (pid, side["branch"], side["development"], side["development"])]


def _park_phase(args, project, config, mpath, raw_index, assembled, phase, side, vm, out):
    """The same phase `add-phase` built, written as a parked proposal instead.

    The payload is the phase exactly as the live verb would have written it, and
    its id stays RESERVED (every allocator counts parked ids), so materializing it
    is a move rather than a rebuild. The proposal lives where proposals live - the
    single file, or the sharded INDEX - and nothing else is touched."""
    now = _proposals.iso_now()
    prop_id = _id_shape.next_prop_id(assembled, side["suffix"])
    # ON A SIDE BRANCH THE RESERVED PHASE ID IS A PLACEHOLDER. Two phase branches
    # parking one each would otherwise both reserve the next plain `P<n>`, and the
    # merged plan would carry a reservation clash neither side had - which the
    # merge driver reports as a conflict, on the one merge this flow exists for.
    # `materialize` on the development branch mints the real id. A caller's own
    # `--id` is theirs and is kept.
    if side["suffix"] and args.phase_id is None:
        taken = _proposals.live_ids(assembled) | _proposals.parked_ids(assembled)
        phase = dict(phase, id=_id_shape.next_phase_id(taken, side["suffix"]))
    proposal = {"id": prop_id, "name": phase.get("title"), "status": "proposed",
                "origin": "audit-task add-phase --park", "createdISO": now,
                "branch": side["branch"], "benefit": phase.get("desiredOutcome"),
                "openQuestions": [], "materializedAs": None, "materializedAt": None,
                "payload": {"phase": phase}}
    assembled.setdefault("proposals", []).append(proposal)
    if _mio.is_sharded(raw_index):
        target = dict(raw_index)
        target["proposals"] = assembled["proposals"]
    else:
        target = assembled
    snap = _snapshot([mpath])
    try:
        _panel_write._atomic_write_json(mpath, target)
        findings, warnings = vm.validate(_mio.load_manifest(mpath))
    except Exception as exc:
        _restore(snap)
        out("[audit-task] write failed -- manifest restored: %s" % exc)
        return E_INVALID
    if findings:
        _restore(snap)
        out("[audit-task] REFUSED: the proposal would leave the manifest invalid "
            "-- rolled back, nothing kept:")
        for line in findings:
            out("FINDING: " + line)
        return E_INVALID
    details = {"phaseId": phase.get("id")}
    if side["branch"]:
        details["branch"] = side["branch"]
    jres = _journal_row(project, config, mpath, "proposal.add",
                        "%s parked (reserves %s): %s" % (prop_id, phase.get("id"),
                                                         phase.get("title")), details)
    written = [_output.posix_rel(mpath, project)]
    target_branch = side["development"]
    if args.as_json:
        result = {"ok": True, "id": prop_id, "reserves": phase.get("id"),
                  "proposal": proposal, "written": written,
                  "materializeOn": target_branch}
        result.update(jres)
        result.update(stdin_notes_key(args))
        result.update(project_basis_key(args))
        out(json.dumps(result, indent=2, sort_keys=True))
        return 0
    out("[audit-task] parked %s (reserves %s) -- %s" % (prop_id, phase.get("id"),
                                                        phase.get("title")))
    out("  outcome: %s" % phase.get("desiredOutcome"))
    for line in _wg.collapse(warnings, _mio.load_manifest(mpath)):
        out("WARNING: " + line)
    if not jres.get("journaled") and jres.get("journaledWhy") == "failed":
        out(_not_journaled_line(jres, "the proposal.add row"))
    out("  written: %s" % ", ".join(written))
    if side["suffix"] is not None:
        out("  next: merge %s into %s, then on %s: /audit:propose materialize %s"
            % (side["branch"], target_branch, target_branch, prop_id))
    else:
        out("  next: /audit:propose materialize %s when it is time to start it on %s"
            % (prop_id, target_branch))
    return 0


# --- the doors ------------------------------------------------------------------
def _under_lock(args, project, out, body, must_exist=True):
    """Config, manifest path, the index lock, `body`, release.

    ONE copy for every verb. The lock comes BEFORE the read: ids are allocated
    under it, so the read-modify-write is serialized (manifest-conventions ->
    ID allocation). What each verb checks before this point differs and stays in
    its own door; what happens after it does not differ at all, and three copies
    of that would be three answers to "where is the manifest".

    IT IS ALSO WHERE EVERY VERB SAYS WHICH TREE IT IS WRITING, for that same
    reason and one more: every door reaches this function and nothing else
    they all reach comes after the project is known, so a verb cannot be added
    that quietly skips the line. It is emitted BEFORE the manifest check, so a
    refusal a reader is about to argue with already names the root it was
    arguing about. Under `--json` it is not printed at all -- the payload must
    stay one parseable object -- and travels as `projectBasis` instead.

    `must_exist` IS THE ONE THING `seed` NEEDS THE OTHER WAY ROUND. Every other
    verb reads or mutates a plan that must already be there; `seed` writes the
    first one, so ITS refusal fires on the opposite condition -- a manifest
    already at the path is the state it declines to overwrite. One door with a
    flag is what keeps the lock, the config read and the release in one place
    for both directions rather than `seed` growing a near-duplicate of this
    function for the one line that differs.
    """
    args.project_basis = _panel_write.standing_elsewhere(resolve_basis(args))
    if args.project_basis["note"] and not args.as_json:
        out(args.project_basis["note"])
    config = _panel_write.read_config(project)
    mpath = (os.path.abspath(args.manifest) if args.manifest
             else _panel_write._manifest_path(project, config))
    exists = os.path.isfile(mpath)
    if must_exist and not exists:
        out("[audit-task] manifest not found: %s -- run /audit:init first"
            % mpath)
        return E_USAGE
    if not must_exist and exists:
        out("[audit-task] a manifest already exists at %s -- seed only writes "
            "the very first one. Use add/add-phase to extend it, or "
            "/audit:init for a full audit." % mpath)
        return E_USAGE
    lock = _acquire_lock(project, config, mpath, args.takeover, out)
    if isinstance(lock, int):
        return lock
    try:
        return body(config, mpath)
    finally:
        # A RELEASE THE LOCK DECLINES IS THE ONLY NOTICE THIS RUN GETS THAT
        # ANOTHER ONE TOOK ITS LOCK, so it is printed rather than dropped -- and
        # under `--json` it goes to stderr for the reason the line above states
        # about the note: the payload stays one parseable object.
        _release_lock(lock, out=(_panel_write.stderr_line if args.as_json
                                 else out))


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

    `pull sprint` imports tasks with `files: []` and a description telling
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

    SETTLED WORK ONLY IS REFUSED OUTRIGHT. A `done` or `cancelled` task
    has a scope its commit was graded against and its sign-off accepted, and
    nothing this verb could write to it would describe the run that happened.
    Everything short of that -- `pending`, `in_progress`, `blocked`, with or
    without attempts on it -- is reachable, but a task that has already STARTED
    will take only a WIDENING or a new GATE: `files` and `tests.add` may gain
    entries and never lose them, `tests.gate` may be replaced outright, and no
    other field may move at all.

    THE OLD RULE WAS NOT WRONG, IT WAS TOO WIDE, and its own reason is what
    narrows it. It refused a started task because an `outcome` describes work
    judged under the OLD scope, so rescoping would make that record describe
    something else. A widening cannot: `_invariants.commit_scope` grades a
    recorded commit against the task's CURRENT `files`, so growing that list can
    only turn a breach into a pass and never a pass into a breach, and the plan
    gate reads it forward, so growing it only ALLOWS an edit it was refusing.
    Append-only is therefore the exact operation that leaves every past
    judgement standing -- see `_narrowings` for why no other field has a safe
    direction.

    AND `tests.gate` MOVES FREELY, WHICH IS A SECOND PERMISSION AND NOT A WIDER
    FIRST ONE. Append-only answers a field that is read BACKWARDS; the gate has
    no backwards reading to protect. It is the measurement the NEXT run will
    make: `run-test-gate` builds that run's steps from it, an evidence row
    carries the commands that actually ran, and the pointer caches the run's id,
    verdict and time -- so replacing it, `--gate-clear` included, moves no
    recorded row and no cached verdict. The constant's own note says why this is
    NOT narrowed to a started task with no green run recorded. What the change
    does owe the reader is a date, so it gets a report line and a journal row of
    its own rather than riding the widening's.

    AND THE CASE IT EXISTS FOR IS THE ONE IT USED TO REFUSE.
    `reference/orchestrator.md` prescribes `/audit:task scope` for the moment the
    plan gate refuses a file a running task genuinely needs, and a task in that
    moment is `in_progress` with an attempt on it -- the two states the guard
    excluded. Measured live: hit three times in one phase, and the only escape
    each time was hand-editing the shard and the index under the lock, which is
    the operation this verb exists to replace.

    THE EMPTY GATE NEEDS ITS OWN FLAG HERE TOO, for a reason that is NOT
    `retarget`'s. That verb replaces `testGate` too, so the replacement itself
    still left the empty gate unspellable; this one REPLACES `tests.gate`
    outright. The gap is
    in the values: no `--gate` VALUE says "none" - `--gate ""` writes a gate
    holding an empty command, which is a gate that cannot run rather than the
    absence of one. Measured live: a phase retargeted to `testGate: []` because
    nothing in this repo could grade its remaining work left its pending tasks
    holding the `["lint"]` they had inherited at creation, and the only routes to
    the state the phase had just reached were a rescope mid-run or the hand edit
    `commands/task.md` forbids.

    RISK, BLOCKEDBY AND DEPENDSON REACH IT TOO, and they were the three
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
    vm = _validator()
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
    # `cancelled` IS SETTLED; `done` IS NOT, AND THE DIFFERENCE WAS
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
    # STATUS IS NOT THE WHOLE TEST, and it is not the whole test in the
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
    # Asked BEFORE the no-op check below and before any mutation, in
    # `_gate_contradiction`'s position: a string that cannot be a path must
    # never reach `files`, `fileIndex` or a journal row, and a refusal is worth
    # more than a rollback.
    refusal = _files_refusal(files)
    if refusal:
        out(refusal)
        return E_USAGE
    # `is None` for the two ID-LIST flags and not truthiness, because an EMPTY
    # value of either is an instruction rather than an absence: `--depends-on ""`
    # is how the field is emptied, which is `retarget --area ""`'s spelling and
    # the reason this flag needed no `--depends-on-clear` twin.
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
    # READ BEFORE ANY WRITE, and that ordering IS the repair rather than a
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
    # Computed here rather than in each branch below because BOTH of them
    # union `tests.add` into `files` and the note they owe is one note.
    #
    # OVER THE ENTRIES THIS CALL ACTUALLY CONSULTS, which is not the same as "the
    # task's `tests.add`". `--files` REPLACES the list and unions the task's
    # CURRENT entries back in, so those are what it read; `--tests-add` replaces
    # the entries themselves, so the NEW ones are what it read. A call passing
    # both reads both lists, and a call passing only `--tests-add` must not
    # report entries it has just replaced - naming a string no longer in the
    # manifest is a basis pointing at something the reader cannot find.
    #
    # DEDUPED, ORDER KEPT. A re-scope that passes an entry the task already
    # carries consults it twice - once through `was_add`, once through
    # `--tests-add` - and `_unnamed_add_note` lists the STRINGS so the reader
    # knows which line to go and fix. Naming one line twice makes them count
    # instead of read.
    consulted = []
    for entry in (list(was_add) if files else []) + list(args.tests_add or []):
        if entry not in consulted:
            consulted.append(entry)
    unnamed_add = _tests_add_paths(consulted)[1]
    changes = []
    if files:
        # `files` ⊇ the paths `tests.add` NAMES is an invariant, not a courtesy,
        # at creation too. `--files` REPLACES the list, so without
        # this a later re-scope silently released the very case file the task is
        # still declared to create, and the next commit tripped commit-scope for a
        # scope the operator had just fixed. The task's CURRENT `add` is used,
        # because `--tests-add` in the same call is applied below and unions again
        # there -- and only the PATH each entry names is carried, since the field is
        # free prose and copying a sentence in grants no permission at all.
        files = _union_paths(files, _tests_add_paths(was_add)[0])
        # THE SAME READ-BEFORE-WRITE CLASS ONE FIELD OVER, and not named by that
        # entry: the row
        # went in under a bare `if files:`, so re-scoping to the list the task
        # already held printed and journaled `files: [...] -> [...]`. The chain
        # verifies and the row attests a change that never happened, which is what
        # a reader counting "who changed this task's scope, and when" counts. The
        # three sibling fields below already compared; this is that comparison.
        if was_files != files:
            changes.append({"id": tid, "field": "files",
                            "from": was_files, "to": files})
        node["files"] = files
    # THE `tests` OBJECT IS MATERIALIZED ONLY IF SOMETHING WRITES INTO IT.
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
        # ...and into `files` here too, for `_build_task`'s reason: a case
        # whose PATH `tests.add` names is a file this task creates, and a scope that
        # omits it fails the task's own commit. `scope` is the verb an operator
        # reaches for when reality differed from the plan, so it is the LAST place
        # that should hand back a scope it knows to be short -- which is exactly
        # what unioning the whole entry, rather than just its path, used to do,
        # since a sentence unioned in is not the path
        # `commit_scope` will be looking for.
        # A NAME OF ITS OWN, not `was_files`: that one is the scope the task held
        # BEFORE this call, and the `fileIndex` derivation below reads it - rebound
        # here it would be the scope `--files` just wrote, and a path that call
        # claimed would never reach the index.
        before_union = list(node.get("files") or [])
        now_files = _union_paths(before_union, _tests_add_paths(now_add)[0])
        if before_union != now_files:
            changes.append({"id": tid, "field": "files",
                            "from": before_union, "to": now_files})
            node["files"] = now_files
    if args.gate or args.gate_clear:
        now_gate = [] if args.gate_clear else list(args.gate)
        if was_gate != now_gate:
            changes.append({"id": tid, "field": "tests.gate",
                            "from": was_gate, "to": now_gate})
        tests["gate"] = now_gate
        # THE BASIS MOVES WITH THE GATE, and it is a change of its own rather
        # than a field that rides the list. A caller passing `--gate` has NAMED
        # these commands, which is a different fact from whichever arm of the
        # derivation produced the list they replace -- and it is the fact the
        # validator reads when it asks whether a task carrying its phase's gate
        # verbatim is holding a default or an answer.
        #
        # WHICH IS WHY A CALL THAT MOVES ONLY THIS IS STILL A WRITE. Declaring
        # the wide gate outright leaves `tests.gate` byte-identical, and that
        # call is exactly the one an operator makes to answer the line: a verb
        # comparing lists alone would report "already reads that way" and write
        # nothing, leaving the only route back to prose nothing reads.
        was_basis = prior_tests.get("gateBasis")
        now_basis = "cleared" if args.gate_clear else "declared"
        if was_basis != now_basis:
            changes.append({"id": tid, "field": "tests.gateBasis",
                            "from": was_basis, "to": now_basis})
        tests["gateBasis"] = now_basis
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
        return _unchanged(args, out, tid)

    # THE WIDENING GUARD, and it is placed HERE for two reasons that both come from
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

    # WHAT THE TWO SURFACES BELOW ANNOUNCE, split once here rather than twice
    # apiece. `started` says the task has moved; it does NOT say a widening
    # happened, and it stopped saying so the moment `tests.gate` became a change
    # a started task takes. A `WIDENED` line or a `widened: true` derived from
    # `started` alone would now claim a growth on a call whose only change was a
    # gate replacement -- which is the one claim the permission does not carry.
    grown = _grown_rows(changes)
    gate_changed = started and bool(_gate_rows(changes))
    widened = started and bool(grown)

    # THE WHOLE POINT, and it is a re-derivation rather than an append: the task
    # is losing files as well as gaining them, and an index that only ever grew
    # would keep matching edits to a scope the task no longer claims.
    #
    # ONLY WHAT MOVED IS TOUCHED. The loop used to remove the task from every path
    # it held and append it back, which on a no-op moved it to the END of a row it
    # shares - a reordered shared `fileIndex` row on a call that changed nothing,
    # which is merge-conflict material in the one file two phases both write.
    # `released` and `claimed` ARE the derivation, so the index is rewritten for
    # exactly those paths and a row the task keeps stays as it was.
    #
    # KEYED BY THE PATH, not the entry: a `files` entry may carry a `:line-range`
    # suffix the schema allows, and the validator and the plan gate both match
    # `fileIndex` on the stripped path. Two entries naming one path are one row,
    # released only when neither is left; a row left keyed by a raw entry by an
    # older writer is released as well.
    released = [f for f in was_files if f not in (node.get("files") or [])]
    claimed = [f for f in (node.get("files") or []) if f not in was_files]
    now_keys = set(_vocab._strip_line_suffix(f) for f in (node.get("files") or []))
    was_keys = set(_vocab._strip_line_suffix(f) for f in was_files)
    fidx = assembled.setdefault("fileIndex", {})
    moved_rows = False
    for fpath in released:
        for key in (_vocab._strip_line_suffix(fpath), fpath):
            if key in now_keys:
                continue
            entry = fidx.get(key)
            if isinstance(entry, list) and tid in entry:
                entry.remove(tid)
                moved_rows = True
                if not entry:
                    del fidx[key]
    for fpath in claimed:
        key = _vocab._strip_line_suffix(fpath)
        if key in was_keys and tid in (fidx.get(key) or []):
            continue
        entry = fidx.setdefault(key, [])
        if tid not in entry:
            entry.append(tid)
            moved_rows = True

    # SAME REPAIR AS `add`'s, AND FOR THE SAME REASON: the entry may carry a
    # `:line-range` suffix the schema allows, and stating a declaration is
    # "not on disk" while the file it names sits right there is worse than
    # saying nothing. Strip before the stat, keep the raw entry in `missing`.
    missing = [f for f in (node.get("files") or [])
               if not os.path.exists(os.path.join(project,
                                                   _vocab._strip_line_suffix(f)))]
    phase_id = phase.get("id")
    snap = _snapshot(_write_paths(project, mpath, raw_index, phase_id))
    try:
        written = _write_add(project, mpath, raw_index, assembled, phase_id,
                             moved_rows)
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
        out("[audit-task] REFUSED: the scope would leave the manifest invalid "
            "-- every written file rolled back, nothing kept:")
        for line in findings:
            out("FINDING: " + line)
        return E_INVALID

    jres = _journal_scope(project, config, mpath, tid, phase_id, changes, node)
    index_note = _index_dirty_note(written, mpath, project, phase_id)
    git_root = os.path.abspath(os.path.join(project,
                                            (config or {}).get("gitRoot") or "."))
    branch_note = _phase_branch_note(git_root, phase, cwd=git_root)
    # THE PAYOFF FOR COMPUTING READINESS HERE, and the reason it is computed unconditionally: the live case
    # was a task parked behind a `dependsOn` id, rescoped precisely so it could
    # run. "Can it run now" is the question that call was asking.
    waiting = _waiting_on(assembled, node)
    if args.as_json:
        result = {"ok": True, "id": tid, "phase": phase_id,
                  "changes": changes, "written": written,
                  "filesNotOnDisk": missing,
                  "warnings": _wg.collapse_machine(warnings, written_manifest),
                  # The facts the human report spends a paragraph on, as data:
                  # WHICH call this was, and the attempt it landed under.
                  # `attempt` is null when the plan records none, never 0 -- a
                  # machine surface must not be the one place the three answers
                  # of `recorded_attempt` collapse into two.
                  #
                  # TWO FLAGS BECAUSE THERE ARE TWO EVENTS, and they are not
                  # alternatives: a call may widen, change the gate, or do both.
                  # `changes` alone cannot answer either question -- it says a
                  # field moved and never whether the task had already started,
                  # which is the whole of what makes these two worth naming.
                  "widened": widened,
                  "gateChanged": gate_changed,
                  "attempt": _mio.recorded_attempt(node),
                  # THE SAME BASIS, on this surface too: `changes` shows the
                  # `files` list that resulted, and nothing in it says a case
                  # file the task declares is outside it.
                  "testsAddNamingNoFile": list(unnamed_add),
                  "ready": not waiting, "waitingOn": waiting}
        result.update(jres)
        result.update(stdin_notes_key(args))
        result.update(project_basis_key(args))
        result.update(_index_dirty_key(index_note))
        result.update(_phase_branch_key(branch_note))
        out(json.dumps(result, indent=2, sort_keys=True))
        return 0
    out("[audit-task] %s scoped in %s" % (tid, phase_id))
    for row in changes:
        out("  %s: %s -> %s" % (row["field"], json.dumps(row["from"]),
                                json.dumps(row["to"])))
    if widened:
        # THE BASIS FOR AN ACCEPTANCE THAT USED TO BE A REFUSAL. A reader
        # of this transcript has to be able to tell a scope written BEFORE the
        # work from one written DURING it, because the two say different things
        # about every record already carrying this task's id -- and the report
        # is where an operator meets that, not the journal. It names what was
        # gained and when, and then why the verb was willing.
        gained = []
        for row in grown:
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
    if gate_changed:
        # THE BASIS FOR THE OTHER ACCEPTANCE, and it is a different one rather
        # than the same sentence about a second field. A widening is safe
        # because it cannot move a past judgement; a gate is safe because it was
        # never part of one. The report says so where the operator meets it: the
        # question a mid-run gate change raises is "what happens to the run
        # already recorded against this task", and the answer is nothing.
        out("  GATE CHANGED %s -- a gate is not a claim about work already "
            "graded, it is the measurement the NEXT run will make. The evidence "
            "row of any run already recorded carries the commands that actually "
            "ran, and the pointer on this task caches that run's id, verdict "
            "and time, so neither says anything different after this write. A "
            "green run already recorded is no reason to leave a wrong gate in "
            "place -- it measured the gate that was there, not this one."
            % (_attempt_phrase(node),))
    if (node.get("tests") or {}).get("gate") == [] \
            and any(row["field"] == "tests.gate" for row in changes):
        # `retarget`'s empty-gate line, and the MEANING differs so the sentence
        # does: `reference/orchestrator.md` has the executor run `task.tests.gate`
        # and phase sign-off run `phase.testGate`, so an emptied task gate means
        # this task runs none of its own and the phase's is what still grades it.
        # Silence would leave a designed state to read as breakage.
        out(_empty_task_gate_note(True))
    if any(row["field"] == "tests.gate" for row in changes):
        for line in _gate_directory_notes(project, (node.get("tests") or {})
                                          .get("gate"), assembled.get("meta")):
            out(line)
    unnamed_note = _unnamed_add_note(unnamed_add)
    if unnamed_note:
        # BEFORE the index lines, because it is about what did NOT reach the
        # index: a reader who has just been told the index was re-derived and
        # what it now claims has already formed the belief this line corrects.
        out(unnamed_note)
    if released:
        out("  fileIndex re-derived -- released by this task: %s"
            % ", ".join(released))
    elif claimed:
        out("  fileIndex re-derived -- now claimed by this task: %s"
            % ", ".join(claimed))
    missing_note = _not_on_disk_note(project, missing)
    if missing_note:
        out(missing_note)
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
    for line in _wg.collapse(warnings, written_manifest):
        out("WARNING: " + line)
    if not jres.get("journaled"):
        out("  note: not journaled (%s)" % (jres.get("journaledReason")
                                             or jres.get("journaledWhy"),))
    if index_note:
        out(index_note)
    if branch_note:
        out(branch_note)
    return 0


_EMPTY_GATE_REFUSAL = ("[audit-task] an empty gate is --gate-clear, which says "
                      "so")


def _retarget_gate_now(args, current):
    """`(now, refusal)` -- the phase's NEXT `testGate`, or the refusal line,
    for whichever ONE of `--gate` / `--gate-clear` / `--gate-set` /
    `--gate-drop` is present. Exactly one of the two return values is not
    `None`; the caller already asked `_gate_contradiction` that at most one of
    the four is present at all, so this never has to choose between them.

    `--gate` AND `--gate-set` ARE ONE OPERATION, kept in this one function
    rather than each carrying its own emptiness rule: both REPLACE the gate
    outright, `--gate` one value per repeat of the flag, `--gate-set` several
    values under one flag. `--gate-set` is the stricter of the two on purpose
    -- an ALL-BLANK value set is refused the same way an empty one is, where
    plain `--gate ""` still writes the odd literal gate it always has, because
    `--gate-set`'s whole reason to exist is a caller who wants to name several
    entries at once, and a caller who typed nothing but blanks almost always
    meant the empty gate and not a gate of blank commands.

    `--gate-drop` is the other operation, narrowing the CURRENT gate by name --
    the only one of the four that reads `current` at all. Every named entry
    must already be in it (refused by name otherwise, with the gate as it
    stands, so a typo is not silently a no-op), and a drop that would leave
    nothing is the same empty-gate refusal as the other three: the state is
    reached through `--gate-clear` alone, which SAYS it is choosing that,
    rather than through an operation that arrives there as a side effect of
    what it dropped.
    """
    if args.gate_clear:
        return [], None
    if args.gate_set is not None:
        now = [g for g in args.gate_set if isinstance(g, str)]
        if not now or all(not g.strip() for g in now):
            return None, _EMPTY_GATE_REFUSAL
        return now, None
    if args.gate:
        return list(args.gate), None
    if args.gate_drop:
        missing = [g for g in args.gate_drop if g not in current]
        if missing:
            return None, (
                "[audit-task] --gate-drop names %s, which %s not in this "
                "phase's testGate (%s)"
                % (_output.some_of(missing, render=repr),
                   "is" if len(missing) == 1 else "are", json.dumps(current)))
        drop = set(args.gate_drop)
        now = [g for g in current if g not in drop]
        if not now:
            return None, _EMPTY_GATE_REFUSAL
        return now, None
    return None, None


def _locked_retarget(args, project, config, mpath, pid, out):
    """Correct a phase's gate, area, outcome or description, under lock.

    THIS VERB EXISTS FOR THE HALF `scope` DOES NOT REACH. `pull sprint` and `init`
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
    than a default: `--gate` replaces, so without an explicit clear there is no
    spelling for "there is nothing here that can prove this".

    NOT PAST SIGN-OFF. A done or cancelled phase - and one whose verdict is
    recorded while its branch has yet to merge - has a sign-off that was given
    against the gate it had; moving the gate afterwards would rewrite what that
    sign-off attested. A phase with no verdict recorded may still be corrected -
    that is the case this verb exists for.
    """
    try:
        raw_index = _mio.read_json(mpath)
        assembled = _mio.load_manifest(mpath)
    except Exception as exc:
        out("[audit-task] cannot read/assemble manifest: %s" % exc)
        return E_USAGE
    vm = _validator()
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
    status = _mio.effective_phase_status(node)
    if status in _mio.TERMINAL or _mio.signoff_recorded(node):
        out("[audit-task] %s is %s -- its sign-off was given against the gate it "
            "had, and moving that afterwards would rewrite what the sign-off "
            "attested" % (pid, status if status in _mio.TERMINAL else "signed off"))
        return E_USAGE

    # A TITLE IS NOT A LABEL HERE, and that is why the rename has a guard
    # rather than being a free field. `_branch.slugify`'s own docstring is
    # "phase.title -> the `{slug}` segment", composed into
    # "<prefix>/{phase}-{slug}" - so before a phase enters, its title decides
    # which branch will be created, and renaming it is exactly right.
    #
    # AFTER IT ENTERS, THE READERS DISAGREE, and that is measured rather than
    # feared: `close-phase.py` and `manage-worktrees.py` both prefer the recorded
    # `phase.branch`, while `resolve-branch.py` composes from the title
    # unconditionally and never looks at it. Rename a phase that is already on a
    # branch and two of the three answer with the branch it is on while the third
    # answers with a name nothing created. Refusing there is the honest reading
    # until those three agree; the title stays correctable for every phase that
    # has not entered, which is when a widened scope is usually noticed.
    if args.rename and node.get("branch"):
        out("[audit-task] %s is already on branch %r -- renaming it now would "
            "leave `resolve-branch.py` composing a name from the new title while "
            "`close-phase.py` and `manage-worktrees.py` keep using the recorded "
            "one, so the phase would have two names and no reader agreeing on "
            "which. Rename before phase entry, or leave the title as the record "
            "of what this branch was cut for." % (pid, node.get("branch")))
        return E_USAGE

    contradiction = _retarget_gate_contradiction(args)
    if contradiction:
        out(contradiction)
        return E_USAGE
    if not (args.gate or args.gate_clear or args.gate_set is not None
            or args.gate_drop or args.area is not None
            or args.outcome or args.description or args.rename):
        out("[audit-task] retarget needs one of --gate / --gate-clear / "
            "--gate-set / --gate-drop / --area / --outcome / --description / "
            "--rename -- a call that changes nothing is a lock taken for no "
            "reason")
        return E_USAGE

    changes = []

    def _moved(field, was, now):
        if was != now:
            changes.append({"id": pid, "field": field, "from": was, "to": now})

    if args.gate or args.gate_clear or args.gate_set is not None or args.gate_drop:
        was = list(node.get("testGate") or [])
        now, refusal = _retarget_gate_now(args, was)
        if refusal:
            out(refusal)
            return E_USAGE
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
    if args.rename:
        # `--rename` and not `--title`: the positional slot named `title` is the
        # PHASE ID for this verb (`cmd_retarget` reads `args.title` for it), so
        # a `--title` flag would shadow the id in the parser and read as the one
        # thing it is not. `--rename` is also the word an operator looking for
        # this reaches for first.
        _moved("title", node.get("title") or "", args.rename)
        node["title"] = args.rename
    if args.outcome:
        _moved("desiredOutcome", node.get("desiredOutcome") or "", args.outcome)
        node["desiredOutcome"] = args.outcome
    if args.description:
        _moved("description", node.get("description") or "", args.description)
        node["description"] = args.description
    if not changes:
        return _unchanged(args, out, pid)

    snap = _snapshot(_write_paths(project, mpath, raw_index, pid))
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
        findings, warnings = ["cannot re-read the written manifest: %s" % exc], []
    if findings:
        _restore(snap)
        out("[audit-task] REFUSED: the retarget would leave the manifest invalid "
            "-- every written file rolled back, nothing kept:")
        for line in findings:
            out("FINDING: " + line)
        return E_INVALID

    jres = _journal_retarget(project, config, mpath, pid, changes)
    index_note = _index_dirty_note(written, mpath, project, pid)
    git_root = os.path.abspath(os.path.join(project,
                                            (config or {}).get("gitRoot") or "."))
    branch_note = _phase_branch_note(git_root, node, cwd=git_root)
    if args.as_json:
        result = {"ok": True, "id": pid, "changes": changes,
                  "written": written,
                  "warnings": _wg.collapse_machine(warnings, written_manifest)}
        result.update(jres)
        result.update(stdin_notes_key(args))
        result.update(project_basis_key(args))
        result.update(_index_dirty_key(index_note))
        result.update(_phase_branch_key(branch_note))
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
    for line in _wg.collapse(warnings, written_manifest):
        out("WARNING: " + line)
    if not jres.get("journaled"):
        out("  note: not journaled (%s)" % (jres.get("journaledReason")
                                             or jres.get("journaledWhy"),))
    if index_note:
        out(index_note)
    if branch_note:
        out(branch_note)
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


def cmd_start(args, out):
    project = _resolve_project(args)
    if not os.path.isdir(project):
        out("[audit-task] not a directory: %s" % project)
        return E_USAGE
    tid = (args.title or "").strip()          # positional: the id to start
    if not tid:
        out("[audit-task] start needs a task id")
        return E_USAGE
    return _under_lock(args, project, out,
                       lambda config, mpath: _locked_start(
                           args, project, config, mpath, tid, out))


def cmd_done(args, out):
    project = _resolve_project(args)
    if not os.path.isdir(project):
        out("[audit-task] not a directory: %s" % project)
        return E_USAGE
    tid = (args.title or "").strip()          # positional: the id to close
    if not tid:
        out("[audit-task] done needs a task id")
        return E_USAGE
    refusal = _done_flags_refusal(args)
    if refusal:
        out(refusal)
        return E_USAGE
    return _under_lock(args, project, out,
                       lambda config, mpath: _locked_done(
                           args, project, config, mpath, tid, out))


def _done_flags_refusal(args):
    """Why this combination of `done` flags cannot close anything, or None.

    TWO CLOSES, AND EACH FLAG BELONGS TO ONE. `--commit` is the close whose work
    landed; `--no-change --reason` is the close whose answer was that nothing
    needed to change. Both at once is two claims about one task, and a
    `--reason` without `--no-change` is a why with no close it explains - the
    parser accepts it because `done` reads the flag, so the door is what refuses.

    `--intent-basis` IS THE BASIS OF AN ANSWER, so it needs one beside it, and
    `not-asked` needs one: it is the one answer no reviewer gave, and a skip
    with no reason on the record reads exactly like a reviewer call that died.
    """
    commit = (args.commit or "").strip()
    reason = (args.reason or "").strip()
    if args.no_change and commit:
        return ("[audit-task] done takes --commit OR --no-change, not both -- "
                "the first records the commit the work landed in, the second "
                "that nothing needed to change, and one close cannot be both")
    if args.no_change and not reason:
        return ("[audit-task] done --no-change needs --reason \"<why nothing "
                "needed to change>\" -- a close with no commit and no reason is "
                "the state /audit:doctor reports, with nothing to tell it apart")
    if not args.no_change and args.reason is not None:
        return ("[audit-task] done reads --reason only beside --no-change, where "
                "it is why nothing needed to change; a close with a commit "
                "records its account in --descriptive/--technical")
    if not args.no_change and not commit:
        # The whole point of the verb, and `cmd_cancel`'s `--reason` one door
        # down is the shape: a close with no commit is the state /audit:doctor
        # already reports, and it cannot be corrected afterwards because `done`
        # is terminal here.
        return ("[audit-task] done needs --commit <sha> -- the SHA is what fixes "
                "this close to work git can still be asked about, and a done task "
                "carrying none is what /audit:doctor reports. Commit first, then "
                "pass `git rev-parse HEAD`. A task whose answer was that nothing "
                "needed to change closes with --no-change --reason instead.")
    if args.override_verdict is not None and not args.override_verdict.strip():
        return ("[audit-task] --override-verdict needs the reason - it is what "
                "the journal records for a close over a gate verdict that "
                "refuses it")
    if args.intent_basis is not None and args.intent is None:
        return ("[audit-task] --intent-basis is the basis of an --intent answer, "
                "and none was passed -- pass --intent %s beside it"
                % ("|".join(INTENT_ANSWERS),))
    if args.intent == "not-asked" and not (args.intent_basis or "").strip():
        return ("[audit-task] --intent not-asked needs --intent-basis \"<why the "
                "question was not put>\" -- it is the one answer no reviewer "
                "gave, and without its reason it reads exactly like a reviewer "
                "call that never came back")
    return None


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


# --- signoff: the record a phase's `done` is derived from --------------------------
# A PHASE'S STATUS IS DERIVED (`_manifest_io.effective_phase_status`), so what
# sign-off writes is the record the derivation reads - the review's verdict, its
# outcome, and the summary sign-off owes the reader - and then the status that record
# now derives, stored for the readers that do not derive. It was a hand edit of
# `status: done`, made on the phase branch before `close-phase` merged it - so a
# phase worked on its parent branch had nothing to hand `close-phase` and stayed
# in_progress for ever. With a branch the phase reads done once it merges, and
# `close-phase.py` stores it then; without one, now, and this verb stores it. The
# verb refuses what sign-off must not do: sign an open phase, re-sign a signed one,
# or sign one already closed.
def cmd_signoff(args, out):
    project = _resolve_project(args)
    pid = (args.title or "").strip()
    if not pid:
        out("[audit-task] signoff needs a phase id")
        return E_USAGE
    ids = signoff_ids(pid)
    # EVERY GROUP-ONLY FLAG ROUTES TO THE GROUP DOOR, which refuses it without
    # --branch: on the single path they were read by nothing, so a `--bind` or an
    # `--accept` beside a verdict signed off and recorded nothing of either.
    if len(ids) > 1 or args.branch or args.plan or args.bind or args.accept \
            or (args.reason or "").strip():
        return _group_door(args, project, ids, out)
    if not args.verdict:
        out("[audit-task] signoff needs --verdict %s: which verdict the review reached "
            "is the reviewer's call" % ("|".join(_mio.SIGNOFF_VERDICTS),))
        return E_USAGE
    summary = (args.summary or "").strip()
    if not summary:
        out("[audit-task] signoff needs --summary \"<what the phase did, and how it met "
            "its outcome>\" -- sign-off owes the reader that paragraph")
        return E_USAGE
    return _under_lock(args, project, out,
                       lambda config, mpath: _locked_signoff(
                           args, project, config, mpath, pid, summary, out))


def _signoff_refusal(phase, pid):
    """Why `phase` cannot be signed off now, or None."""
    if phase.get("status") in _mio.TERMINAL:
        return ("phase %s is already %s -- a closed phase is not signed off again"
                % (pid, phase.get("status")))
    if _mio.signoff_recorded(phase):
        return ("phase %s is already signed off (review.status %s) -- the verdict on "
                "record is not re-decided by this verb" % (pid, phase["review"]["status"]))
    tasks = [t for t in (phase.get("tasks") or []) if isinstance(t, dict)]
    if not tasks:
        return "phase %s has no task, so there is no finished work to sign off" % (pid,)
    still = [t.get("id") for t in tasks if t.get("status") not in _mio.TERMINAL]
    if still:
        return ("phase %s still has open work: %s -- sign-off runs once every task is "
                "done or cancelled" % (pid, ", ".join("%s" % (s,) for s in still)))
    return None


# A `passed` VERDICT STANDS ON A GATE RUN OR SAYS WHY THERE IS NONE. The procedure
# runs the gate before the record, and nothing held it: a verdict could be written
# with no run behind it. Whether a recorded run binds the work is
# `_verdict_binding.binding`'s answer - the SAME rule a task commit is bound by, so
# a repeated verdict, the recorder's own writes and a gate changed after the run
# are graded here exactly as they are there. The union of a phase's files is
# that module's too, because `close-phase.py` asks the same phase the same
# question at the merge.
phase_files = _vb.phase_files


def phase_binding(project, mpath, manifest, phase, files, record):
    """`_verdict_binding.phase_binding` in sign-off's words."""
    pid = str(phase.get("id"))
    return _vb.phase_binding(
        project, mpath, manifest, phase, files, record,
        "phase %s declares no gate, so its sign-off rests on review alone" % (pid,))


def _locked_signoff(args, project, config, mpath, pid, summary, out):
    try:
        raw_index = _mio.read_json(mpath)
        assembled = _mio.load_manifest(mpath)
    except Exception as exc:
        out("[audit-task] cannot read/assemble manifest: %s" % exc)
        return E_USAGE
    vm = _validator()
    broken = _refuse_broken_install(vm, out)
    if broken is not None:
        return broken
    kind, phase, _owner = _find_target(assembled, pid)
    if kind != "phase":
        out("[audit-task] no phase %r in %s" % (pid, mpath))
        return E_USAGE
    refusal = _signoff_refusal(phase, pid)
    if refusal:
        out("[audit-task] " + refusal)
        return E_USAGE
    reason = (args.no_evidence_reason or "").strip()
    if args.verdict == "passed" and not reason:
        gate = _plugin_cmd("governance/run-test-gate.py",
                           _output.posix_rel(mpath, project), pid, "--record")
        bound = phase_binding(project, mpath, assembled, phase,
                              phase_files([phase]),
                              "run `%s` on the work, then sign off" % (gate,))
        if bound["state"] == "refused":
            out("[audit-task] REFUSED: --verdict passed needs a gate run that binds "
                "the phase's work - %s." % (bound["sentence"],))
            out("    or pass --no-evidence-reason \"<why no gate run backs this "
                "verdict>\", which is recorded on the review")
            return E_USAGE
    review = phase.get("review") if isinstance(phase.get("review"), dict) else {}
    review = dict(review, status=args.verdict)
    if args.review_outcome:
        review["outcome"] = outcome_with_tally(args.review_outcome.strip(),
                                               review.get("findings"))
    # THE REASON BELONGS TO THE SIGN-OFF THAT GAVE IT. The review is carried
    # forward whole, so a reason an earlier sign-off recorded would otherwise
    # outlive it and excuse, at the landing, a green this sign-off did stand on.
    if reason:
        review["noEvidenceReason"] = reason
    else:
        review.pop("noEvidenceReason", None)
    phase["review"] = review
    phase["summary"] = summary
    phase.pop("claim", None)
    # The verdict is an input of the derived status, so the status it now derives
    # is stored beside it - `done` for a phase with no branch, nothing yet for one
    # awaiting its merge, where `close-phase.py`'s stamp is the write that settles it.
    settled = _settle(assembled, {("phase", pid)})
    snap = _snapshot(_write_paths(project, mpath, raw_index, pid))
    try:
        written = _write_add(project, mpath, raw_index, assembled, pid, False)
    except Exception as exc:
        _restore(snap)
        out("[audit-task] write failed -- manifest restored: %s" % exc)
        return E_INVALID
    try:
        written_manifest = _mio.load_manifest(mpath)
        findings, warnings = vm.validate(written_manifest)
    except Exception as exc:
        written_manifest, findings, warnings = {}, ["cannot re-read the written "
                                                    "manifest: %s" % exc], []
    if findings:
        _restore(snap)
        out("[audit-task] REFUSED: the sign-off would leave the manifest invalid -- "
            "every written file rolled back, nothing kept:")
        for line in findings:
            out("FINDING: " + line)
        return E_INVALID
    # `phase.verdict`, not `phase.signoff`: the journal-writes hook DERIVES
    # `phase.signoff` from the write (the phase reaching done), and two writers of
    # one action is two rows for one sign-off - `task.done` beside the hook's
    # `task.complete` is the same split.
    jres = _journal_row(project, config, mpath, "phase.verdict",
                        "%s signed off (%s): %s" % (pid, args.verdict, summary),
                        {"phaseId": pid})
    effective = _mio.effective_phase_status(phase)
    branch = phase.get("branch")
    awaiting = "merge" if effective not in _mio.TERMINAL and branch else None
    # A stored status moves the index stub's mirror too, so a sharded sign-off can
    # leave the index dirty beside its shard - which a task commit does not carry.
    index_note = _index_dirty_note(written, mpath, project, pid)
    # THE ABSENT INTENT ANSWERS, named at the moment a phase is judged. Reported
    # and never refused: a plan older than `intentCheck` has none on any task, and
    # a sign-off refused for that would be a gate on history nobody can rewrite.
    unanswered = _status_facts.intent_unanswered(phase)
    if args.as_json:
        result = {"ok": True, "id": pid, "verdict": args.verdict, "summary": summary,
                  "effectiveStatus": effective, "awaiting": awaiting, "branch": branch,
                  "intentUnanswered": unanswered,
                  "stored": settled, "written": written,
                  "warnings": _wg.collapse_machine(warnings, written_manifest)}
        result.update(jres)
        result.update(stdin_notes_key(args))
        result.update(project_basis_key(args))
        result.update(_index_dirty_key(index_note))
        out(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if awaiting:
        out("[audit-task] phase %s signed off (%s) -- done once %s lands: "
            "close-phase.py merges it and stamps mergedAt" % (pid, args.verdict, branch))
    else:
        out("[audit-task] phase %s signed off (%s) -- now %s" % (pid, args.verdict,
                                                                effective))
    if unanswered:
        out("  no intent answer recorded for %d done task(s): %s -- `intentCheck` "
            "is absent, which reads as no answer and never as agreement"
            % (len(unanswered), ", ".join(unanswered)))
    for line in _settled_lines(settled):
        out(line)
    for line in _wg.collapse(warnings, written_manifest):
        out("WARNING: " + line)
    if not jres.get("journaled") and jres.get("journaledWhy") == "failed":
        out(_not_journaled_line(jres, "the phase.verdict row"))
    out("  written: %s" % ", ".join(written))
    if index_note:
        out(index_note)
    return 0


# --- review findings: the record sign-off's first step writes ----------------------
# The reviewer returns findings in the schema's shape and sign-off records them, and
# that record was a hand edit of the phase shard: no lock, no revalidation, no
# journal row, and a severity nothing graded until the validator warned about it
# afterwards. One verb per write the step makes: `finding` appends one,
# `resolve-finding` names the task and commit that fixed one, and `correct`
# rewrites the review's outcome or the phase's summary as TEXT. The verdict is
# `signoff`'s alone, and none of these three reads `--verdict`.
#
# THE TALLY IS DERIVED, NEVER TYPED. Every verb that writes `review.outcome` -
# these three and `signoff` - rewrites its trailing `[findings: ...]` segment from
# `review.findings` as it stands after the write, so the count in the outcome
# cannot disagree with the list it counts. The prose before the segment is the
# operator's and is kept verbatim; a segment of that shape the operator typed is
# replaced, because a count nobody derived is the thing this removes.
_TALLY_TAIL = re.compile(r"\s*\[findings: [^\[\]]*\]\s*$")
# A finding's id is `<phaseId>-R<n>`, the spelling the plan's hand-recorded
# findings already use, numbered past every id of that shape the review holds.
_FINDING_ID = re.compile(r"^(?P<phase>.+)-R(?P<n>[0-9]+)$")
# The resolution text a fix writes in front of what the reviewer asked for,
# matched so a second resolution replaces the first rather than stacking on it.
_FIXED_PREFIX = re.compile(r"^fixed in \S+ \([0-9a-fA-F]+\)(: )?")


def review_tally(findings):
    """The `[findings: ...]` segment `findings` derives, or None when it is empty.

    None RATHER THAN A ZERO TALLY: a review with no finding recorded is one that
    found nothing or one nobody recorded, and a count of zero would claim the
    first. An entry outside the vocabulary - a legacy string, `medium` - is
    counted as that, never dropped, so the total is always the list's length.
    """
    entries = list(findings or [])
    if not entries:
        return None
    vocab = _phases.FINDING_SEVERITY
    counts = dict((sev, 0) for sev in vocab)
    outside = fixed = 0
    for entry in entries:
        sev = entry.get("severity") if isinstance(entry, dict) else None
        if sev in counts:
            counts[sev] += 1
        else:
            outside += 1
        if isinstance(entry, dict) and entry.get("fixTask") and entry.get("commit"):
            fixed += 1
    parts = ["%d %s" % (counts[sev], sev) for sev in reversed(vocab)]
    if outside:
        parts.append("%d outside %s" % (outside, "|".join(vocab)))
    # "RECORDED" IS THE WHOLE CLAUSE: it counts the findings `resolve-finding`
    # wrote a fix task and commit onto, and says nothing about the rest - a fix
    # a plan recorded in the resolution's prose is not one the fields hold.
    return "[findings: %d - %s; %d with a recorded fix commit]" % (
        len(entries), ", ".join(parts), fixed)


def outcome_with_tally(text, findings):
    """`text` with its trailing tally replaced by the one `findings` derives.

    An absent outcome stays absent when there is nothing to count, and a tally
    with no finding under it is stripped rather than kept: it has no basis.
    """
    base = text if isinstance(text, str) else ""
    while _TALLY_TAIL.search(base):
        base = _TALLY_TAIL.sub("", base)
    base = base.strip()
    tally = review_tally(findings)
    if tally is None:
        return base if (base or text is not None) else None
    return "%s %s" % (base, tally) if base else tally


def _next_finding_id(pid, review):
    """`<pid>-R<n>`, one past every id of that shape either finding list holds."""
    taken = [0]
    for key in _phases.REVIEW_FINDING_LISTS:
        for entry in (review.get(key) or []):
            match = _FINDING_ID.match(str(entry.get("id"))) \
                if isinstance(entry, dict) else None
            if match and match.group("phase") == pid:
                taken.append(int(match.group("n")))
    return "%s-R%d" % (pid, max(taken) + 1)


def _finding_problems(entry):
    """Every reason `entry` - `{severity, file, issue, resolution}` - is not a
    finding, in field order; empty when it is one."""
    missing = [field for field in _phases.FINDING_FIELDS
               if field != "id" and not entry.get(field)]
    if missing:
        return ["missing %s -- the shape is {%s}, and a finding missing one is one "
                "no later run, report or panel can act on"
                % (", ".join(missing), ", ".join(_phases.FINDING_FIELDS))]
    problems = []
    if entry["severity"] not in _phases.FINDING_SEVERITY:
        problems.append("severity %r is outside the vocabulary: %s, the words the "
                        "reviewer is asked to return and the validator grades"
                        % (entry["severity"], ", ".join(_phases.FINDING_SEVERITY)))
    bad = _path_problems([entry["file"]])
    if bad:
        problems.append("file is the repository-relative path a fix task's "
                        "`files` is built from, and %s" % ("; ".join(bad),))
    # A batch's text never passes `resolve_briefs`, which judges flags; asked
    # here it is judged on both routes. No project is at hand, so the home
    # shapes are asked and the checkout-root shape is not.
    problems.extend(why for why in (
        _journal_io.check_free_text(None, field, entry[field])
        for field in ("issue", "resolution")) if why)
    return problems


def _field_text(value):
    """A finding field as the record holds it: stripped text, or `""`."""
    return value.strip() if isinstance(value, str) else ""


def _read_findings_file(path, stream=None):
    """`(entries, None)` off a JSON list of findings, or `(None, refusal)`.

    A reviewer's own `id` is dropped rather than kept: the plan allocates its ids,
    and a number the reviewer counted from one would collide across reviews.
    """
    try:
        if path == "-":
            text = (stream if stream is not None else sys.stdin).read()
        else:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        data = json.loads(text)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, ("--findings-file %s could not be read as JSON: %s" % (path, exc))
    if not isinstance(data, list) or not data:
        return None, ("--findings-file %s holds %s, not a non-empty JSON list of "
                      "findings" % (path, "an empty list" if data == [] else
                                    type(data).__name__))
    entries, bad = [], []
    for n, raw in enumerate(data, 1):
        if not isinstance(raw, dict):
            bad.append("entry %d is %s, not a finding object" % (n, type(raw).__name__))
            continue
        entry = dict((field, _field_text(raw.get(field)))
                     for field in _phases.FINDING_FIELDS if field != "id")
        bad.extend("entry %d: %s" % (n, why) for why in _finding_problems(entry))
        entries.append(entry)
    if bad:
        return None, ("--findings-file %s is refused WHOLE, nothing written: %s"
                      % (path, "; ".join(bad)))
    return entries, None


def _finding_refusal(args):
    """`(findings, None)` - one from the four flags, or a batch off
    `--findings-file` - or `(None, refusal)`.

    EVERY PROBLEM IN ONE REFUSAL, `_files_refusal`'s rule. The severity is
    graded here and not by argparse `choices`: argparse answers on stderr before
    `main` buffers anything, so a `--json` caller would read no object at all.
    """
    flagged = [flag for flag, value in (("--severity", args.severity),
                                        ("--file", args.file),
                                        ("--issue", args.issue),
                                        ("--resolution", args.resolution))
               if value is not None]
    if args.findings_file is not None:
        if flagged:
            return None, ("[audit-task] --findings-file is the whole batch, so %s "
                          "beside it would be a second finding nobody listed. "
                          "Nothing written." % (", ".join(flagged),))
        entries, refusal = _read_findings_file(args.findings_file)
        return entries, ("[audit-task] " + refusal) if refusal else None
    finding = {"severity": _field_text(args.severity),
               "file": _field_text(args.file),
               "issue": _field_text(args.issue),
               "resolution": _field_text(args.resolution)}
    missing = ["--%s" % field for field in _phases.FINDING_FIELDS
               if field != "id" and not finding[field]]
    if missing:
        return None, ("[audit-task] finding needs %s (or --findings-file for a "
                      "batch) -- the shape is {%s}, and a finding missing one is "
                      "one no later run, report or panel can act on. Nothing "
                      "written." % (", ".join(missing),
                                    ", ".join(_phases.FINDING_FIELDS)))
    problems = _finding_problems(finding)
    if problems:
        return None, "[audit-task] --%s. Nothing written." % ("; --".join(problems),)
    return [finding], None


def _review_target(assembled, pid, verb):
    """`(phase, review, None)` for a phase whose review a verb may write, or
    `(None, None, refusal)`. `review` is a COPY, so a refusal leaves no trace."""
    kind, phase, _owner = _find_target(assembled, pid)
    if kind is None:
        return None, None, "no phase with id %r in this plan" % (pid,)
    if kind != "phase":
        return None, None, ("%s is a TASK -- `%s` takes the id of the phase whose "
                            "review it writes" % (pid, verb))
    if phase.get("status") == "cancelled":
        return None, None, ("phase %s is cancelled -- a phase that will not be done "
                            "has no review to record" % (pid,))
    review = phase.get("review")
    if review is not None and not isinstance(review, dict):
        return None, None, ("phase %s carries a `review` that is not an object (%s) "
                            "-- a write onto a value of another shape would replace "
                            "it" % (pid, type(review).__name__))
    review = dict(review or {})
    listed = review.get("findings")
    if listed is not None and not isinstance(listed, list):
        return None, None, ("phase %s carries `review.findings` that is not a list "
                            "(%s) -- nothing written" % (pid, type(listed).__name__))
    return phase, review, None


def _journal_outcome(text):
    """`text` as a journal row holds it: shortened from the MIDDLE past the row's
    per-value bound, keeping a trailing tally whole.

    The row's own bound cuts from the end, and the tally sits at the end - so a
    long outcome's before and after read identically in the trail while the one
    part that changed was cut off.
    """
    limit = _journal_io.MAX_VALUE_CHARS
    if not isinstance(text, str) or len(text) <= limit:
        return text
    gap = " ... "
    match = _TALLY_TAIL.search(text)
    keep = text[match.start():].strip() if match else text[-(limit // 2):]
    room = limit - len(keep) - len(gap)
    if room <= 0:
        return keep[-limit:]
    return text[:room].rstrip() + gap + keep


def _landed_refusal(phase, pid):
    """Why `phase` is a closed record no finding may be added to, or None."""
    merged = phase.get("mergedAt")
    if not merged:
        return None
    return ("phase %s landed at %s -- its review is the record the merge closed, "
            "and a finding added now would sit under a verdict that never saw "
            "it. Re-open the review with /audit:review %s, or report it as a bug "
            "(/audit:bug add)" % (pid, merged, pid))


def cmd_finding(args, out):
    project = _resolve_project(args)
    if not os.path.isdir(project):
        out("[audit-task] not a directory: %s" % project)
        return E_USAGE
    pid = (args.title or "").strip()          # positional: the phase reviewed
    if not pid:
        out("[audit-task] finding needs a phase id")
        return E_USAGE
    findings, refusal = _finding_refusal(args)
    if refusal:
        out(refusal)
        return E_USAGE
    return _under_lock(args, project, out,
                       lambda config, mpath: _locked_finding(
                           args, project, config, mpath, pid, findings, out))


def _locked_finding(args, project, config, mpath, pid, findings, out):
    plan = _read_plan(mpath, out)
    if isinstance(plan, int):
        return plan
    raw_index, assembled, vm = plan
    phase, review, refusal = _review_target(assembled, pid, "finding")
    refusal = refusal or (_landed_refusal(phase, pid) if phase else None)
    if refusal:
        out("[audit-task] " + refusal)
        return E_USAGE
    # A VERDICT ALREADY ON RECORD is said, not refused: a phase signed off and
    # still awaiting its merge can still take a fix, and the finding that asks
    # for one arrived after the verdict - which the row has to say.
    verdict = review.get("status") if _mio.signoff_recorded(phase) else None
    after = " (after its verdict %s)" % (verdict,) if verdict else ""
    records = []
    for finding in findings:
        fid = _next_finding_id(pid, review)
        records.append(dict([("id", fid)] + [(field, finding[field])
                                             for field in _phases.FINDING_FIELDS
                                             if field != "id"]))
        review["findings"] = list(review.get("findings") or []) + [records[-1]]
    was_outcome = review.get("outcome")
    review["outcome"] = outcome_with_tally(was_outcome, review["findings"])
    phase["review"] = review
    wrote = _write_plan(project, mpath, raw_index, assembled, vm, [pid],
                        "the finding", out)
    if isinstance(wrote, int):
        return wrote
    written, written_manifest, warnings = wrote
    outcome_change = {"id": pid, "field": "review.outcome",
                      "from": _journal_outcome(was_outcome),
                      "to": _journal_outcome(review["outcome"])}
    # ONE ROW PER FINDING, each attesting its own; the outcome moved once, so
    # the last row carries that change.
    rows = []
    for n, record in enumerate(records, 1):
        changes = [{"id": record["id"], "field": "review.findings", "from": None,
                    "to": "%s %s" % (record["severity"], record["file"])}]
        if n == len(records):
            changes.append(outcome_change)
        rows.append(_journal_row(project, config, mpath, "review.finding",
                                 "%s finding %s (%s) in %s%s: %s"
                                 % (pid, record["id"], record["severity"],
                                    record["file"], after, record["issue"]),
                                 {"phaseId": pid, "changes": changes}))
    jres = next((r for r in rows if not r.get("journaled")), rows[-1])
    index_note = _index_dirty_note(written, mpath, project, pid)
    if args.as_json:
        out(_json_tail({"ok": True, "id": records[-1]["id"], "phase": pid,
                        "finding": records[-1], "findings": records,
                        "verdictOnRecord": verdict,
                        "outcome": review["outcome"], "written": written},
                       args, jres, warnings, written_manifest, index_note))
        return 0
    for record in records:
        out("[audit-task] %s recorded on %s%s (%s, %s): %s"
            % (record["id"], pid, after, record["severity"], record["file"],
               record["issue"]))
    out("  review.outcome: %s" % (review["outcome"],))
    _report_tail(out, jres, "review.finding", warnings, written_manifest, written,
                 index_note)
    return 0


# `resolve-finding`: the finding named by its own id, which is unique across the
# plan by construction (`<phaseId>-R<n>`) and refused by name when a hand-written
# one is not. The commit is the fix task's own when it has closed, so the SHA is
# the one `done` already fixed rather than a second typing of it; a fix that has
# not landed has no commit to name, and that is the refusal.
def cmd_resolve_finding(args, out):
    project = _resolve_project(args)
    if not os.path.isdir(project):
        out("[audit-task] not a directory: %s" % project)
        return E_USAGE
    fid = (args.title or "").strip()          # positional: the finding's id
    if not fid:
        out("[audit-task] resolve-finding needs a finding id")
        return E_USAGE
    fix = (args.fix_task or "").strip()
    if not fix:
        out("[audit-task] resolve-finding needs --fix-task <taskId> -- the task "
            "whose commit settles the finding")
        return E_USAGE
    commit = (args.commit or "").strip()
    if commit:
        shape = _commit_shape_refusal(commit)
        if shape:
            out(shape)
            return E_USAGE
    return _under_lock(args, project, out,
                       lambda config, mpath: _locked_resolve_finding(
                           args, project, config, mpath, fid, fix, commit, out))


def _finding_hits(assembled, fid):
    """`[(phase, index), ...]` for every review finding whose id is `fid`."""
    hits = []
    for ph in (assembled.get("phases") or []):
        review = ph.get("review") if isinstance(ph, dict) else None
        listed = review.get("findings") if isinstance(review, dict) else None
        for i, entry in enumerate(listed if isinstance(listed, list) else []):
            if isinstance(entry, dict) and str(entry.get("id")) == fid:
                hits.append((ph, i))
    return hits


def _fix_commit(task, commit):
    """`(sha, None)` - the fix's commit - or `(None, refusal)`.

    THE TASK MUST BE DONE, whatever `--commit` says. A SHA typed for a task
    nobody closed is a claim about work the plan does not record as finished;
    `--commit` only supplies the SHA a done task did not record.
    """
    if task.get("status") != "done":
        return None, ("%s is %s, not done -- the fix has not landed, and a commit "
                      "passed for it would record a fix the plan does not hold. "
                      "Close it with `audit-task.py done %s --commit <sha>` first"
                      % (task.get("id"), task.get("status"), task.get("id")))
    recorded = (task.get("commit") or "").strip()
    if commit and recorded and not (recorded.lower().startswith(commit.lower())
                                    or commit.lower().startswith(recorded.lower())):
        return None, ("--commit %s is not the commit %s recorded (%s) -- one fix "
                      "cannot have landed in two" % (commit[:12], task.get("id"),
                                                     recorded[:12]))
    sha = commit or recorded
    if not sha:
        return None, ("%s records no commit and no --commit was passed -- the fix "
                      "has not landed. Close it with `audit-task.py done %s "
                      "--commit <sha>` first, or pass the SHA it landed in"
                      % (task.get("id"), task.get("id")))
    shape = _commit_shape_refusal(sha)
    if shape:
        return None, shape[len("[audit-task] "):]
    return sha, None


def _locked_resolve_finding(args, project, config, mpath, fid, fix, commit, out):
    plan = _read_plan(mpath, out)
    if isinstance(plan, int):
        return plan
    raw_index, assembled, vm = plan
    hits = _finding_hits(assembled, fid)
    if not hits:
        out("[audit-task] no review finding with id %r in this plan -- "
            "`audit-task.py finding <phaseId>` records one" % (fid,))
        return E_USAGE
    if len(hits) > 1:
        out("[audit-task] %r names a finding in more than one place (%s) -- a "
            "resolution cannot choose between them; renumber the hand-written one"
            % (fid, ", ".join(sorted(set(str(ph.get("id")) for ph, _i in hits)))))
        return E_USAGE
    phase, index = hits[0]
    pid = phase.get("id")
    kind, task, _owner = _find_target(assembled, fix)
    if kind != "task":
        out("[audit-task] --fix-task %s is %s -- a finding is settled by the "
            "commit of one TASK" % (fix, "a PHASE" if kind else "no task in this plan"))
        return E_USAGE
    sha, refusal = _fix_commit(task, commit)
    if refusal:
        out("[audit-task] " + refusal)
        return E_USAGE
    git_root = os.path.abspath(os.path.join(project,
                                            (config or {}).get("gitRoot") or "."))
    refusal, unverified = _commit_git_note(git_root, sha)
    if refusal:
        out(refusal)
        return E_USAGE
    review = dict(phase["review"])
    findings = list(review["findings"])
    was = findings[index]
    if was.get("fixTask") == fix and was.get("commit") == sha:
        return _unchanged(args, out, fid)
    asked = _FIXED_PREFIX.sub("", (was.get("resolution") or "").strip())
    head = "fixed in %s (%s)" % (fix, sha[:12])
    entry = dict(was, fixTask=fix, commit=sha,
                 resolution="%s: %s" % (head, asked) if asked else head)
    findings[index] = entry
    review["findings"] = findings
    was_outcome = review.get("outcome")
    review["outcome"] = outcome_with_tally(was_outcome, findings)
    phase["review"] = review
    wrote = _write_plan(project, mpath, raw_index, assembled, vm, [pid],
                        "the resolution", out)
    if isinstance(wrote, int):
        return wrote
    written, written_manifest, warnings = wrote
    changes = [{"id": fid, "field": "resolution", "from": was.get("resolution"),
                "to": entry["resolution"]},
               {"id": pid, "field": "review.outcome",
                "from": _journal_outcome(was_outcome),
                "to": _journal_outcome(review["outcome"])}]
    jres = _journal_row(project, config, mpath, "review.resolve",
                        "%s resolved by %s in %s" % (fid, fix, sha[:12]),
                        {"phaseId": pid, "taskId": fix, "commit": sha,
                         "changes": changes})
    index_note = _index_dirty_note(written, mpath, project, pid)
    if args.as_json:
        out(_json_tail({"ok": True, "id": fid, "phase": pid,
                                "finding": entry, "outcome": review["outcome"],
                                "commitVerified": unverified is None,
                                "changes": changes, "written": written},
                       args, jres, warnings, written_manifest, index_note))
        return 0
    out("[audit-task] %s resolved by %s in %s" % (fid, fix, sha[:12]))
    if unverified:
        out(unverified)
    out("  review.outcome: %s" % (review["outcome"],))
    _report_tail(out, jres, "review.resolve", warnings, written_manifest, written,
                 index_note)
    return 0


# `correct`: a typo in a signed-off record is fixed without re-signing it. It
# writes TEXT and nothing a derivation reads - not the verdict, not the stored
# status, not the claim - so the `phase.verdict` row the sign-off wrote stays the
# only record of the verdict, and this verb's own row records the correction.
def cmd_correct(args, out):
    project = _resolve_project(args)
    if not os.path.isdir(project):
        out("[audit-task] not a directory: %s" % project)
        return E_USAGE
    pid = (args.title or "").strip()          # positional: the phase corrected
    if not pid:
        out("[audit-task] correct needs a phase id")
        return E_USAGE
    given = [(flag, value) for flag, value in (("--review-outcome", args.review_outcome),
                                               ("--summary", args.summary))
             if value is not None]
    if not given:
        out("[audit-task] correct needs --review-outcome TEXT and/or --summary TEXT "
            "-- the two texts a sign-off wrote; the verdict is not one of them")
        return E_USAGE
    empty = [flag for flag, value in given if not value.strip()]
    if empty:
        out("[audit-task] %s is empty -- a correction replaces text with text, and "
            "an empty one would erase what sign-off owes the reader"
            % (", ".join(empty),))
        return E_USAGE
    return _under_lock(args, project, out,
                       lambda config, mpath: _locked_correct(
                           args, project, config, mpath, pid, out))


def _locked_correct(args, project, config, mpath, pid, out):
    plan = _read_plan(mpath, out)
    if isinstance(plan, int):
        return plan
    raw_index, assembled, vm = plan
    phase, review, refusal = _review_target(assembled, pid, "correct")
    if refusal:
        out("[audit-task] " + refusal)
        return E_USAGE
    if not _mio.signoff_recorded(phase):
        out("[audit-task] phase %s has no verdict recorded, so there is no sign-off "
            "text to correct -- `audit-task.py signoff %s` writes the outcome and "
            "the summary with the verdict" % (pid, pid))
        return E_USAGE
    changes = []
    if args.review_outcome is not None:
        new = outcome_with_tally(args.review_outcome.strip(), review.get("findings"))
        if new != review.get("outcome"):
            changes.append({"id": pid, "field": "review.outcome",
                            "from": _journal_outcome(review.get("outcome")),
                            "to": _journal_outcome(new)})
            review["outcome"] = new
    if args.summary is not None and args.summary.strip() != phase.get("summary"):
        changes.append({"id": pid, "field": "summary", "from": phase.get("summary"),
                        "to": args.summary.strip()})
        phase["summary"] = args.summary.strip()
    if not changes:
        return _unchanged(args, out, pid)
    phase["review"] = review
    wrote = _write_plan(project, mpath, raw_index, assembled, vm, [pid],
                        "the correction", out)
    if isinstance(wrote, int):
        return wrote
    written, written_manifest, warnings = wrote
    jres = _journal_row(project, config, mpath, "review.correct",
                        "%s sign-off text corrected (%s); verdict %s unchanged"
                        % (pid, ", ".join(c["field"] for c in changes),
                           review.get("status")),
                        {"phaseId": pid, "changes": changes})
    index_note = _index_dirty_note(written, mpath, project, pid)
    if args.as_json:
        out(_json_tail({"ok": True, "id": pid, "phase": pid,
                                "verdict": review.get("status"),
                                "changes": changes, "written": written},
                       args, jres, warnings, written_manifest, index_note))
        return 0
    out("[audit-task] %s corrected: %s -- verdict %s unchanged"
        % (pid, ", ".join(c["field"] for c in changes), review.get("status")))
    _report_tail(out, jres, "review.correct", warnings, written_manifest, written,
                 index_note)
    return 0


# --- group sign-off: phases built on one branch --------------------------------
# A FLAG ON THIS VERB, NOT A VERB OF ITS OWN. A group writes the record one phase's
# sign-off writes - the verdict, its outcome, the summary, the status that derives -
# under the same refusals, and a second writer of the record the derivation reads
# is where two answers to "is this phase signed off" would start. What a group
# changes is what the evidence is scoped by: there is no `baseRef` to diff from,
# so the review is scoped by the tasks' commits; the phases share one tree, so one
# gate run and one invariants run measure all of them; and the branch is landed
# once, so every member but the last keeps it for the next. `--plan` prints that;
# the record re-asks the same planner under the lock, so the two cannot disagree.
def signoff_ids(text):
    """The phase ids a `signoff` names: one, or a comma list for a group."""
    ids = []
    for part in (text or "").split(","):
        pid = part.strip()
        if pid and pid not in ids:
            ids.append(pid)
    return ids


def _group_gate(members):
    """(carrier id, union) -- the member whose `testGate` holds every entry any
    member declares, or (None, union) when none does. One run of the phase gate
    measures one phase's gate, so the union is runnable only when one carries it."""
    union = []
    for ph in members:
        for entry in (ph.get("testGate") or []):
            if entry not in union:
                union.append(entry)
    for ph in members:
        if set(union) <= set(ph.get("testGate") or []):
            return ph.get("id"), union
    return None, union


def _accounted_commits(ids, journal_rows):
    """The commits the journal records as a member's audit-state or index commit -
    the other commits a group's branch may carry beside its tasks' own."""
    actions = (_invariants.ACTION_STATE_COMMITTED, _invariants.ACTION_INDEX_COMMITTED)
    out = set()
    for row in (journal_rows or []):
        det = row.get("details") if isinstance(row.get("details"), dict) else {}
        if row.get("action") in actions and str(det.get("phaseId")) in ids \
                and det.get("commit"):
            out.add(str(det["commit"]))
    return out


def _is_accounted(sha, known):
    """Does `sha` match a recorded commit, full or abbreviated either way?"""
    return any(sha.startswith(k) or k.startswith(sha) for k in known if k)


def group_plan(assembled, ids, branch, git_root, run=None, journal_rows=None,
               journal_error=None, accepted=None):
    """{"members", "refusals", "commits", "files", "gate", "union", "fork",
    "accepted"} -- what
    signing `ids` off together on `branch` owes, and every reason it cannot yet.
    `fork` is `git merge-base <parent> <branch>`, the baseRef a member is bound to.

    `commits` is `(phaseId, taskId, sha)` per task that landed work, in plan order;
    a cancelled task is skipped, and any other task without a commit is a refusal,
    because a review scoped by commits cannot see work no commit records. Each sha
    is asked of git (`merge-base --is-ancestor <sha> <branch>`), since the plan's
    word for where a commit is does not make it so - and the other direction is
    asked too: every commit `fork..branch` carries must be one of those, or an
    audit-state or index commit `journal_rows` records for a member. The first
    landing merges the whole branch, so a commit that is neither lands unreviewed.

    Two more are accounted, and neither hides anything. A MERGE commit whose every
    parent is accounted, or lies on the parent side of the fork, AND whose tree is
    the automatic merge of those parents (`_clean_merge`) - a merge carrying content
    of its own is refused by SHA for review. And a commit named in `accepted`
    (`--accept <sha> --reason`, each resolved to one full commit) is taken
    into the group and listed in `accepted`, so it is reviewed with the members'
    commits rather than refused or passed over. `journal_error` is the journal
    read that failed: a commit only the journal could account for is then said as
    that, rather than as a commit no member records.
    """
    refusals, members, commits, files = [], [], [], []
    for pid in ids:
        kind, phase, _owner = _find_target(assembled, pid)
        if kind != "phase":
            refusals.append("no phase %r in this plan" % (pid,))
            continue
        members.append(phase)
        why = _signoff_refusal(phase, pid)
        if why:
            refusals.append(why)
        recorded = phase.get("branch")
        if recorded and recorded != branch:
            refusals.append("phase %s records branch %r, not %r - a group is phases "
                            "built on one branch" % (pid, recorded, branch))
        for task in (phase.get("tasks") or []):
            if not isinstance(task, dict) or task.get("status") == "cancelled":
                continue
            if not task.get("commit"):
                refusals.append("task %s records no commit, and a group's review is "
                                "scoped by its tasks' commits" % (task.get("id"),))
                continue
            commits.append((pid, task.get("id"), str(task["commit"])))
    files = phase_files(members)
    meta = assembled.get("meta") or {}
    parents = []
    for ph in members:
        parent = _branch.parent_branch(meta, ph)["branch"]
        if parent not in parents:
            parents.append(parent)
    if len(parents) > 1:
        refusals.append("the members land in different parents (%s), and one branch "
                        "lands in one" % (", ".join(str(p) for p in parents),))
    if branch in parents:
        # LANDING A BRANCH INTO ITSELF LANDS NOTHING, and close-phase's cleanup
        # would then plan deleting that branch - the parent - as settled work.
        refusals.append("%r is its own parent - a group branch is the one the "
                        "members' work was built on, never the branch it lands in"
                        % (branch,))
        return {"members": members, "refusals": refusals, "commits": commits,
                "files": files, "gate": None, "union": [], "fork": "",
                "accepted": []}
    fork = ""
    found = _worktrees.ref_exists(git_root, branch, run=run)
    fn = _worktrees._runner(run)
    if found["exists"] is not True:
        refusals.append("%r %s" % (branch, "is not a branch in this repository"
                                   if found["exists"] is False
                                   else "could not be resolved (%s)" % (found["basis"],)))
    else:
        code, said, _err = fn(git_root, ["merge-base", parents[0] if parents else "",
                                         branch])
        fork = (said or "").strip() if code == 0 else ""
        if not fork:
            refusals.append("where %r left %r could not be established (`git "
                            "merge-base %s %s`), so no baseRef can be recorded for "
                            "it" % (branch, parents[0] if parents else None,
                                    parents[0] if parents else "<parent>", branch))
        for pid, tid, sha in commits:
            held = _worktrees.merged_into(git_root, sha, branch, run=run)
            if held["answer"] != _worktrees.CONTAINED:
                refusals.append("task %s's commit %s is not established to be on %r "
                                "(%s: %s) - if the branch was rebased, "
                                "`repair-commits.py` re-points the task at the commit "
                                "that now carries its work"
                                % (tid, sha[:12], branch, held["answer"],
                                   held["basis"]))
    taken, review = [], {}
    if fork:
        code, said, err = fn(git_root, ["rev-list", "--reverse", "--topo-order",
                                        "--parents", "%s..%s" % (fork, branch)])
        if code != 0:
            refusals.append("which commits %r carries past %s could not be listed "
                            "(`git rev-list %s..%s`: %s)"
                            % (branch, fork[:12], fork[:12], branch,
                               (err or "").strip().split("\n")[0]))
        else:
            known = set(sha for _p, _t, sha in commits) \
                | _accounted_commits(ids, journal_rows)
            resolved = {}
            for name in (accepted or []):
                if not _HEX_SHA.match(name or ""):
                    refusals.append(
                        "--accept %s is not a commit SHA - it takes a hex SHA, or a "
                        "unique hex prefix of at least 4 digits, resolved to exactly "
                        "one commit; a ref or a revision expression would be "
                        "re-resolved on every call" % (name,))
                    continue
                code, full, _e = fn(git_root, ["rev-parse", "--verify", "--quiet",
                                               "%s^{commit}" % (name,)])
                full = (full or "").strip()
                if code == 0 and full.startswith(name.lower()):
                    resolved[full] = name
                elif code == 0 and full:
                    # A REF WHOSE NAME IS HEX wins over the commit it spells: git
                    # prefers the ref, which re-resolves on every call.
                    refusals.append("--accept %s names a ref, not a commit SHA - git "
                                    "resolves it through the ref of that name to %s, "
                                    "a commit it does not prefix; name the commit by "
                                    "its full SHA" % (name, full[:12]))
                else:
                    refusals.append("--accept %s does not resolve to exactly one "
                                    "commit (`git rev-parse --verify %s^{commit}`) "
                                    "- name the commit by its full SHA, or a prefix "
                                    "only it has" % (name, name))
            verdicts = {}

            def judge(sha, parents):
                verdicts[sha] = _clean_merge(fn, git_root, sha, parents)
                return verdicts[sha]
            stray, taken, used, blocked, waiting = _account(
                said, known, list(resolved), judge)
            unused = [resolved[a] for a in resolved if a not in used]
            if unused:
                refusals.append("--accept %s names no commit %r carries past its "
                                "fork %s" % (", ".join(unused), branch, fork[:12]))
            for sha, over in blocked:
                refusals.append(_merge_refusal(sha, verdicts[sha], over))
            for sha, over in waiting:
                refusals.append(
                    "%s is a merge over %s, refused above - it recomputes clean, so "
                    "it is accounted once %s" % (
                        sha[:12], ", ".join(o[:12] for o in over),
                        "that one is" if len(over) == 1 else "those are"))
            review = dict((sha, _review_command(sha, verdicts.get(sha)))
                          for sha in taken)
            if stray and journal_error:
                refusals.append(
                    "%r carries %s no task records, and the journal could not be "
                    "read, so whether it is a member's audit-state or index commit "
                    "could not be accounted: %s (%s)"
                    % (branch, "a commit" if len(stray) == 1 else "commits",
                       ", ".join(c[:12] for c in stray), journal_error))
            elif stray:
                refusals.append(
                    "%r carries %s that no member records - not reviewed, and the "
                    "first landing would merge it: %s. Each has to be a member task's "
                    "commit, an audit-state or index commit the journal records for a "
                    "member, or a merge of those - or pass --accept <sha> --reason "
                    "\"<why>\" to review it with the group"
                    % (branch, "a commit" if len(stray) == 1 else "commits",
                       ", ".join(c[:12] for c in stray)))
    carrier, union = _group_gate(members)
    if members and carrier is None:
        refusals.append(
            "no member's testGate holds the group's union (%s): %s - one gate run "
            "measures one phase's gate, so give one member every entry with "
            "`/audit:phase retarget <phaseId> --gate <entry>`"
            % (", ".join(union), "; ".join("%s: %s" % (
                ph.get("id"), ", ".join(ph.get("testGate") or []) or "(empty)")
                for ph in members)))
    return {"members": members, "refusals": refusals, "commits": commits,
            "files": files, "gate": carrier, "union": union, "fork": fork,
            "accepted": taken, "acceptedReview": review}


# `--accept` takes a commit SHA - never a ref, which re-resolves on every call and
# can name a different commit at the record than at the plan.
_HEX_SHA = re.compile(r"^[0-9a-fA-F]{4,40}$")

MERGE_CLEAN, MERGE_OWN, MERGE_UNASKED = "clean", "own", "could-not-ask"


def _clean_merge(fn, git_root, sha, parents):
    """`{"state", "tree", "why"}` - does merge `sha` carry content of its own?

    `git merge-tree --write-tree` recomputes the automatic merge of two parents
    without touching a work tree. THREE ANSWERS, because two would lie: `clean`
    (exit 0 and the same tree), `own` (the parents conflict - exit 1, a hand
    resolution - or the trees differ: an edit made inside the merge commit), and
    `could-not-ask` - an octopus merge, which merge-tree cannot recompute, or any
    other exit (a git before 2.38 has no `--write-tree`; a shallow clone may lack
    an object). The last is said as a question not asked, never as an edit.
    `tree` is the recomputed tree when there is one, which is what a reviewer
    diffs the merge against."""
    if len(parents) != 2:
        return {"state": MERGE_UNASKED, "tree": None,
                "why": "an octopus merge of %d parents cannot be recomputed - `git "
                       "merge-tree --write-tree` takes two parents only"
                       % (len(parents),)}
    code, tree, err = fn(git_root, ["merge-tree", "--write-tree", parents[0],
                                    parents[1]])
    first = (tree or "").strip().split("\n")[0].strip()
    if code not in (0, 1) or not first:
        return {"state": MERGE_UNASKED, "tree": None,
                "why": "`git merge-tree --write-tree` answered %s: %s - replaying a "
                       "merge without writing it needs git 2.38+"
                       % (code, (err or "").strip().split("\n")[0]
                          or "no output")}
    if code == 1:
        return {"state": MERGE_OWN, "tree": first,
                "why": "its parents conflict, so its tree is a hand resolution"}
    code2, own, _err2 = fn(git_root, ["rev-parse", "%s^{tree}" % (sha,)])
    if code2 != 0:
        return {"state": MERGE_UNASKED, "tree": first,
                "why": "the merge's own tree could not be read"}
    if first == (own or "").strip():
        return {"state": MERGE_CLEAN, "tree": first, "why": ""}
    return {"state": MERGE_OWN, "tree": first,
            "why": "its tree is not the automatic merge of its parents - an edit "
                   "made inside the merge commit, or a change of a side it dropped"}


def _review_command(sha, verdict):
    """What a reviewer runs to see what a commit carries. For a merge, the
    comparison the check made - the automatic merge's tree against the merge -
    because a combined diff hides a path whose result equals one parent, which
    is exactly how a dropped change looks. A merge with no recomputed tree gets a
    diff against EACH parent (`git show -m`), which shows a drop on any git and
    for any number of parents. `verdict` is set only for a merge."""
    if verdict and verdict.get("tree"):
        return "git diff %s %s" % (verdict["tree"], sha)
    if verdict:
        return "git show -m %s" % (sha,)
    return "git show %s" % (sha,)


def _merge_refusal(sha, verdict, over=None):
    """The refusal a merge the accounting could not take in earns - with, when it
    sits over merges refused above, those named too: it is judged on its own
    account now, never promised accounting once they are."""
    tail = ("; it is also a merge over %s, refused above"
            % (", ".join(o[:12] for o in over),) if over else "")
    if verdict["state"] == MERGE_UNASKED:
        return ("merge %s: whether it adds or drops anything of its own could not "
                "be asked (%s)%s. Review it (`%s`) and pass --accept %s --reason "
                "\"<why>\" to take it into the group"
                % (sha[:12], verdict["why"], tail, _review_command(sha, verdict),
                   sha))
    return ("merge %s carries content of its own - %s%s. Review what it adds or "
            "drops with `%s`, and pass --accept %s --reason \"<why>\" to take it "
            "into the group" % (sha[:12], verdict["why"], tail,
                                _review_command(sha, verdict), sha))


def _account(listing, known, accepted, judge):
    """`(stray, taken, used, blocked, waiting)` over `git rev-list --parents`
    output: the commits nothing accounts for, the ones `accepted` (full SHAs) took
    in, which of those matched, the merges `judge` could not take in, and the
    clean merges held up only by those - both `(sha, [refused merges below it])`.

    A merge is accounted when every parent is accounted - an accepted commit
    included - or lies outside the listed range, which is the parent side of the
    fork, AND `judge` answers `clean`. Accounted parents are not enough: an edit
    made inside a merge commit belongs to no parent, and the first landing would
    carry it unreviewed."""
    lines = [ln.split() for ln in (listing or "").splitlines() if ln.strip()]
    in_range = set(parts[0] for parts in lines)
    ok, stray, taken, used, blocked, waiting = set(), [], [], [], [], []
    held = set()
    for parts in lines:
        sha, parents = parts[0], parts[1:]
        named = [a for a in accepted if a == sha]
        if _is_accounted(sha, known):
            ok.add(sha)
            continue
        if named:
            ok.add(sha)
            taken.append(sha)
            used.extend(named)
            if len(parents) > 1:
                judge(sha, parents)
            continue
        if len(parents) > 1:
            pending = [p for p in parents if p in in_range and p not in ok]
            if not pending:
                if judge(sha, parents)["state"] == MERGE_CLEAN:
                    ok.add(sha)
                else:
                    blocked.append((sha, []))
                    held.add(sha)
                continue
            if all(p in held for p in pending):
                # JUDGED NOW, as if the refused merges below were accounted:
                # merge-tree replays two parents whatever is known of them, so a
                # promise of accounting is made only for a merge that recomputes
                # clean, and any other is refused on its own account.
                if judge(sha, parents)["state"] == MERGE_CLEAN:
                    waiting.append((sha, pending))
                else:
                    blocked.append((sha, pending))
                held.add(sha)
                continue
        stray.append(sha)
    return stray, taken, used, blocked, waiting


def _plugin_cmd(rel, *argv):
    """A plugin script call, spelled the way the command docs spell every one."""
    return 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/%s" %s' % (rel, " ".join(argv))


def landing_commands(mrel, ids, branch):
    """One `close-phase.py --branch` per member, in order. The first landing merges
    the whole branch and each later one finds it contained and stamps its own
    phase, so every member but the last keeps the branch and its worktree - a
    deletion on the first would leave the rest nothing to land."""
    last = len(ids) - 1
    return [_plugin_cmd("git/close-phase.py", mrel, pid, "--project", ".",
                        "--branch", branch,
                        *(() if i == last else ("--keep-worktree", "--keep-branch")))
            for i, pid in enumerate(ids)]


def gate_command(mrel, plan, ids):
    """The group's one gate run, owning every member's files (`--also`)."""
    others = [pid for pid in ids if pid != plan["gate"]]
    return _plugin_cmd("governance/run-test-gate.py", mrel, plan["gate"],
                       *(("--also", ",".join(others)) if others else ()),
                       "--record")


def commit_commands(mrel, ids, sharded):
    """The sign-off commit, spelled as the plugin's own committers: one audit-state
    commit per member - one commit carrying two members' shards reads as a scope
    breach for each - and, sharded, the index alone after them."""
    if not sharded:
        return [_plugin_cmd("governance/commit-audit-state.py", mrel, ids[0],
                            "--project", ".")]
    return ([_plugin_cmd("governance/commit-audit-state.py", mrel, pid,
                         "--project", ".") for pid in ids]
            + [_plugin_cmd("governance/commit-manifest-index.py", mrel, ids[-1],
                           "--project", ".")])


def _group_door(args, project, ids, out):
    if len(ids) > 1 and not args.branch:
        out("[audit-task] signoff of %s is a group sign-off, which needs --branch "
            "<name>: the one branch these phases were built on" % (", ".join(ids),))
        return E_USAGE
    if not args.branch:
        out("[audit-task] --plan, --bind, --accept and --reason belong to a group "
            "sign-off - `signoff <P1,P2,...> --branch <name>` - and one phase's "
            "sign-off reads none of them. Nothing was written.")
        return E_USAGE
    if args.plan and args.bind:
        out("[audit-task] signoff --plan writes nothing and --bind writes the "
            "branch - one at a time")
        return E_USAGE
    if (args.plan or args.bind) and (args.verdict or args.summary
                                     or args.review_outcome
                                     or args.no_evidence_reason):
        out("[audit-task] signoff --%s records no verdict, so --verdict, --summary, "
            "--review-outcome and --no-evidence-reason have no reader there - "
            "record the verdict on its own" % ("plan" if args.plan else "bind",))
        return E_USAGE
    if args.accept and not (args.reason or "").strip():
        out("[audit-task] --accept takes a commit into the group's review, and it "
            "is recorded with why: pass --reason \"<why this commit belongs>\"")
        return E_USAGE
    if (args.reason or "").strip() and not args.accept:
        out("[audit-task] --reason on a group sign-off is the why of --accept "
            "<sha>, and no commit was named")
        return E_USAGE
    summary = (args.summary or "").strip()
    if not (args.plan or args.bind) and (not args.verdict or not summary):
        out("[audit-task] a group sign-off records --verdict %s and --summary "
            "\"<what the phases did>\"; `--plan` prints what it owes first"
            % ("|".join(_mio.SIGNOFF_VERDICTS),))
        return E_USAGE
    return _under_lock(args, project, out,
                       lambda config, mpath: _locked_group(
                           args, project, config, mpath, ids, summary, out))


def _group_write(project, mpath, raw_index, assembled, ids, vm, out):
    """(written, warnings, manifest, exit) -- every member's file in one write,
    revalidated and rolled back whole on a finding. `exit` is None on success."""
    paths = []
    for pid in ids:
        paths.extend(p for p in _write_paths(project, mpath, raw_index, pid)
                     if p not in paths)
    snap = _snapshot(paths)
    written = []
    try:
        for pid in ids:
            written.extend(w for w in _write_add(project, mpath, raw_index,
                                                 assembled, pid, False)
                           if w not in written)
    except Exception as exc:
        _restore(snap)
        out("[audit-task] write failed -- manifest restored: %s" % exc)
        return [], [], {}, E_INVALID
    try:
        written_manifest = _mio.load_manifest(mpath)
        findings, warnings = vm.validate(written_manifest)
    except Exception as exc:
        written_manifest, findings, warnings = {}, ["cannot re-read the written "
                                                    "manifest: %s" % exc], []
    if findings:
        _restore(snap)
        out("[audit-task] REFUSED: the group write would leave the manifest invalid "
            "-- every written file rolled back, nothing kept:")
        for line in findings:
            out("FINDING: " + line)
        return [], [], {}, E_INVALID
    return written, warnings, written_manifest, None


def _group_index_note(written, mpath, project, ids):
    """`_index_dirty_note` for a write that touched several shards and the index."""
    index_rel = _output.posix_rel(mpath, project)
    if index_rel not in written or len(written) < 2:
        return None
    return _index_dirty_note([w for w in written if w != index_rel] + [index_rel],
                             mpath, project, ids[-1])


def _group_binding(project, mpath, assembled, carrier, plan, ids, gate):
    """`(refusal, row)` - whether the carrier's newest run binds every member's
    work: the one binding rule over the union of their files, and, for a group,
    a measuring run that owned each other member (its row's `groupWith`)."""
    bound = phase_binding(project, mpath, assembled, carrier, plan["files"],
                          "run `%s` over every member's files, then record" % (gate,))
    if bound["state"] == "refused":
        return bound["sentence"], None
    if bound["state"] == "no-gate":
        # A GATE THAT DECLARES NO ENTRY GRADES NOTHING, so no run is copied: the
        # carrier's newest row may be any older run, under a gate that is gone,
        # that never owned the other members.
        return None, None
    measured = bound.get("measured") or {}
    others = [pid for pid in ids if pid != carrier.get("id")]
    owned = [str(p) for p in (measured.get("groupWith") or [])]
    missing = [pid for pid in others if pid not in owned]
    if bound["state"] == "bound" and missing:
        return ("the run that measured it (%s) owned %s alone, not %s - run `%s`"
                % (measured.get("runId"), carrier.get("id"), ", ".join(missing),
                   gate)), None
    return None, bound.get("row")


def _locked_group(args, project, config, mpath, ids, summary, out):
    try:
        raw_index = _mio.read_json(mpath)
        assembled = _mio.load_manifest(mpath)
    except Exception as exc:
        out("[audit-task] cannot read/assemble manifest: %s" % exc)
        return E_USAGE
    git_root = os.path.abspath(os.path.join(project,
                                            (config or {}).get("gitRoot") or "."))
    journal_error = None
    try:
        journal_rows = _journal_io.read_all(project,
                                            _journal_cfg(config, mpath, project))
    except Exception as exc:
        # Carried, not absorbed: a commit only the journal could account for is
        # then said as unaccountable, not as a commit nobody records.
        journal_rows, journal_error = [], "%s" % (exc,)
    plan = group_plan(assembled, ids, args.branch, git_root,
                      journal_rows=journal_rows, journal_error=journal_error,
                      accepted=list(args.accept or []))
    mrel = _output.posix_rel(mpath, project)
    if plan["refusals"]:
        out("[audit-task] REFUSED: %s cannot be signed off together on %s - nothing "
            "written:" % (", ".join(ids), args.branch))
        for line in plan["refusals"]:
            out("  - " + line)
        return E_USAGE
    landing = landing_commands(mrel, ids, args.branch)
    sharded = _mio.is_sharded(raw_index)
    if args.plan:
        return _print_group_plan(args, plan, ids, mrel, landing, sharded, out)
    vm = _validator()
    broken = _refuse_broken_install(vm, out)
    if broken is not None:
        return broken
    if args.bind:
        return _bind_group(args, project, config, mpath, raw_index, assembled,
                           plan, ids, vm, out)
    unbound = [ph.get("id") for ph in plan["members"]
               if ph.get("branch") != args.branch or not ph.get("baseRef")]
    if unbound:
        out("[audit-task] REFUSED: %s %s not bound to %s yet - run `signoff %s "
            "--branch %s --bind` first, so the sign-off's invariants run sees the "
            "branch and baseRef it grades. Nothing written."
            % (", ".join(unbound), "is" if len(unbound) == 1 else "are",
               args.branch, ",".join(ids), args.branch))
        return E_USAGE
    reason = (args.no_evidence_reason or "").strip()
    carrier = [ph for ph in plan["members"] if ph.get("id") == plan["gate"]][0]
    pointer = None
    if args.verdict == "passed" and not reason:
        why, row = _group_binding(project, mpath, assembled, carrier, plan, ids,
                                  gate_command(mrel, plan, ids))
        if why:
            out("[audit-task] REFUSED: --verdict passed needs the group's one gate "
                "run to bind every member's work - %s." % (why,))
            out("    or pass --no-evidence-reason \"<why no gate run backs this "
                "verdict>\", which is recorded on every member's review")
            return E_USAGE
        pointer = _evidence_io.pointer_for(row) if row else None
    for phase in plan["members"]:
        review = phase.get("review") if isinstance(phase.get("review"), dict) else {}
        review = dict(review, status=args.verdict)
        if args.review_outcome:
            review["outcome"] = outcome_with_tally(args.review_outcome.strip(),
                                                   review.get("findings"))
        # The reason belongs to this sign-off, as on the single-phase path.
        if reason:
            review["noEvidenceReason"] = reason
        else:
            review.pop("noEvidenceReason", None)
        if plan["accepted"]:
            review["acceptedCommits"] = [{"commit": sha, "reason": args.reason.strip()}
                                         for sha in plan["accepted"]]
        phase["review"] = review
        phase["summary"] = summary
        phase.pop("claim", None)
        if pointer and phase is not carrier:
            # THE CARRIER'S RUN, NAMED AS THE CARRIER'S. A member with no pointer
            # reads as done work with no run recorded, and its repair - run its own
            # gate - would re-measure the tree the one run already graded.
            phase["testEvidence"] = dict(pointer, gradedBy=carrier.get("id"))
    settled = _settle(assembled, set(("phase", pid) for pid in ids))
    written, warnings, written_manifest, stop = _group_write(
        project, mpath, raw_index, assembled, ids, vm, out)
    if stop is not None:
        return stop
    rows = [_journal_row(project, config, mpath, "phase.verdict",
                         "%s signed off (%s) with %s on %s: %s"
                         % (pid, args.verdict, ", ".join(ids), args.branch, summary),
                         {"phaseId": pid}) for pid in ids]
    # EVERY POINTER MOVE IS A ROW, `write_pointer`'s rule: the copy a member takes
    # is named with the run and the phase whose run it is.
    rows += [_journal_row(project, config, mpath, "phase.testEvidence",
                          "phase %s now points at %s's run %s (%s), gradedBy %s"
                          % (pid, carrier.get("id"), pointer.get("runId"),
                             pointer.get("status"), carrier.get("id")),
                          {"phaseId": pid, "runId": str(pointer.get("runId")),
                           "fromPhase": str(carrier.get("id"))})
             for pid in ids if pointer and pid != carrier.get("id")]
    effective = dict((ph.get("id"), _mio.effective_phase_status(ph))
                     for ph in plan["members"])
    commits = commit_commands(mrel, ids, sharded)
    index_note = _group_index_note(written, mpath, project, ids)
    if args.as_json:
        result = {"ok": True, "ids": ids, "branch": args.branch,
                  "verdict": args.verdict, "summary": summary,
                  "effectiveStatus": effective, "stored": settled,
                  "written": written, "commit": commits, "land": landing,
                  "gatePhase": plan["gate"],
                  "journaled": all(r.get("journaled") for r in rows),
                  "warnings": _wg.collapse_machine(warnings, written_manifest)}
        result.update(stdin_notes_key(args))
        result.update(project_basis_key(args))
        result.update(_index_dirty_key(index_note))
        out(json.dumps(result, indent=2, sort_keys=True))
        return 0
    for pid in ids:
        out("[audit-task] phase %s signed off (%s) with %s -- %s"
            % (pid, args.verdict, ", ".join(q for q in ids if q != pid),
               "now %s" % (effective[pid],) if effective[pid] in _mio.TERMINAL
               else "done once %s lands" % (args.branch,)))
    for line in _settled_lines(settled):
        out(line)
    for line in _wg.collapse(warnings, written_manifest):
        out("WARNING: " + line)
    if not all(r.get("journaled") for r in rows) \
            and any(r.get("journaledWhy") == "failed" for r in rows):
        out(_not_journaled_line(
            next(r for r in rows if r.get("journaledWhy") == "failed"),
            "every phase.verdict row"))
    if reason:
        out("  gate: none - the reason is recorded on every member's review")
    elif not pointer:
        out("  gate: %s's gate declares no entry, so the sign-off rests on review "
            "alone" % (plan["gate"],))
    else:
        others = [q for q in ids if q != plan["gate"]]
        out("  gate: the group's one run is %s's; %s %s it as %s, gradedBy %s"
            % (plan["gate"], ", ".join(others),
               "records" if len(others) == 1 else "record",
               "its own" if len(others) == 1 else "theirs", plan["gate"]))
    out("  written: %s" % ", ".join(written))
    if index_note:
        out(index_note)
    out("  commit it on %s, then land them in this order, from %s:"
        % (args.branch, project))
    for line in commits + landing:
        out("    " + line)
    return 0


def _bind_group(args, project, config, mpath, raw_index, assembled, plan, ids, vm,
                out):
    """Record each member's branch and its fork point as baseRef, and nothing of the
    verdict - the write that lets the sign-off's invariants run grade them."""
    moved, changes = [], {}
    for phase in plan["members"]:
        pid = str(phase.get("id"))
        if phase.get("branch") != args.branch:
            changes.setdefault(pid, []).append(
                {"id": pid, "field": "branch", "from": phase.get("branch"),
                 "to": args.branch})
            phase["branch"] = args.branch
            moved.append("%s.branch" % (pid,))
        if not phase.get("baseRef"):
            changes.setdefault(pid, []).append(
                {"id": pid, "field": "baseRef", "from": phase.get("baseRef"),
                 "to": plan["fork"]})
            phase["baseRef"] = plan["fork"]
            moved.append("%s.baseRef" % (pid,))
    if not moved:
        out("[audit-task] %s already bound to %s - nothing written"
            % (", ".join(ids), args.branch))
        return 0
    written, warnings, written_manifest, stop = _group_write(
        project, mpath, raw_index, assembled, ids, vm, out)
    if stop is not None:
        return stop
    # A row per member, `start`'s rule for the branch it cuts: the trail says when
    # a member was bound, to which branch, from what.
    for pid in ids:
        if pid in changes:
            _journal_row(project, config, mpath,
                         "phase.bind", "%s bound to %s, baseRef %s"
                         % (pid, args.branch, plan["fork"][:12]),
                         {"phaseId": pid, "branch": args.branch,
                          "changes": changes[pid]})
    if args.as_json:
        result = {"ok": True, "ids": ids, "branch": args.branch,
                  "baseRef": plan["fork"], "moved": moved, "written": written}
        result.update(project_basis_key(args))
        out(json.dumps(result, indent=2, sort_keys=True))
        return 0
    out("[audit-task] %s bound to %s, baseRef %s (where it left the parent): %s"
        % (", ".join(ids), args.branch, plan["fork"][:12], ", ".join(moved)))
    for line in _wg.collapse(warnings, written_manifest):
        out("WARNING: " + line)
    out("  written: %s" % ", ".join(written))
    return 0


def _print_group_plan(args, plan, ids, mrel, landing, sharded, out):
    """The group's sign-off, step by step, with the one command each step runs."""
    commits = commit_commands(mrel, ids, sharded)
    record = _plugin_cmd("manifest/audit-task.py", "signoff", ",".join(ids),
                         "--branch", args.branch)
    if args.as_json:
        result = {"ok": True, "ids": ids, "branch": args.branch,
                  "commits": [{"phaseId": p, "taskId": t, "commit": s}
                              for p, t, s in plan["commits"]],
                  "files": plan["files"], "gatePhase": plan["gate"],
                  "gateUnion": plan["union"], "gate": gate_command(mrel, plan, ids),
                  "bind": record + " --bind", "commit": commits, "land": landing}
        result.update(project_basis_key(args))
        out(json.dumps(result, indent=2, sort_keys=True))
        return 0
    out("[audit-task] group sign-off of %s on %s - the plan; nothing was written"
        % (", ".join(ids), args.branch))
    out("  1. bind - each member's branch, and baseRef %s where it left the parent, "
        "so the invariants run below grades them:" % (plan["fork"][:12],))
    out("       " + record + " --bind")
    out("  2. review - scoped by the tasks' commits; every other commit the branch "
        "carries past its fork is a member's journaled state or index commit, a "
        "merge of accounted work, or accepted below:")
    for pid, tid, sha in plan["commits"]:
        out("       %s  git show %s" % (tid, sha))
    for sha in plan["accepted"]:
        out("       accepted  %s  (%s)" % (
            (plan.get("acceptedReview") or {}).get(sha) or "git show %s" % (sha,),
            (args.reason or "").strip()))
    out("     files: %s" % (", ".join(plan["files"]) or "(none declared)",))
    out("  3. gate - one run over the union (%s), carried by %s and owning every "
        "member's files:" % (", ".join(plan["union"]) or "empty", plan["gate"]))
    out("       " + gate_command(mrel, plan, ids))
    out("  4. invariants - one run; `--all` is its one spelling over more than one "
        "phase, so read the rows for %s:" % (", ".join(ids),))
    out("       " + _plugin_cmd("governance/verify-invariants.py", mrel, "--all"))
    out("  5. record the sign-off:")
    out("       " + record + " --verdict passed|skipped --summary \"<...>\"")
    out("  6. commit it on %s:" % (args.branch,))
    for line in commits:
        out("       " + line)
    out("  7. land each phase, in this order:")
    for line in landing:
        out("       " + line)
    return 0


# --- settle: store every derived value a plan carries stale ---------------------
# The verbs store what they change an input of; a plan written before they did, or
# edited by hand since, still carries the old values, and `validate-manifest` warns
# about each one and names this verb. It is the ONE writer of a whole plan's derived
# values, under the index lock with revalidate-or-roll-back and a journal row, the
# path every mutating verb here takes - and it never runs on its own initiative: the
# warning names it, and whoever owns the plan decides when.
def cmd_settle(args, out):
    # `settle` takes no title, so a manifest named in the first free positional is
    # the manifest - the verb's usage line spells it `settle [manifest]`.
    _manifest_from_positional(args)
    project = _resolve_project(args)
    return _under_lock(args, project, out,
                       lambda config, mpath: _locked_settle(
                           args, project, config, mpath, out))


def _locked_settle(args, project, config, mpath, out):
    try:
        raw_index = _mio.read_json(mpath)
        assembled = _mio.load_manifest(mpath)
    except Exception as exc:
        out("[audit-task] cannot read/assemble manifest: %s" % exc)
        return E_USAGE
    vm = _validator()
    pre_findings, _w = vm.validate(assembled)
    if pre_findings:
        out("[audit-task] the manifest is already invalid -- nothing written; "
            "fix these first:")
        for line in pre_findings:
            out("FINDING: " + line)
        return E_INVALID
    rows = _settle(assembled, None)
    phase_ids = []
    for pid in ([r["id"] for r in rows if r["kind"] == "phase"]
                + [row[0] for row in _mio.stale_stubs(mpath)]):
        if pid not in phase_ids:
            phase_ids.append(pid)
    bugs_moved = any(r["kind"] == "bug" for r in rows)
    n_phases = len([p for p in (assembled.get("phases") or []) if isinstance(p, dict)])
    n_bugs = len([b for b in (assembled.get("bugs") or []) if isinstance(b, dict)])
    examined = "%d phase(s) and %d bug(s) examined" % (n_phases, n_bugs)
    if not phase_ids and not bugs_moved:
        if args.as_json:
            result = {"ok": True, "stored": [], "stubs": [], "written": [],
                      "phases": n_phases, "bugs": n_bugs}
            result.update(project_basis_key(args))
            out(json.dumps(result, indent=2, sort_keys=True))
            return 0
        out("[audit-task] nothing to settle -- %s, and every stored status is the "
            "derived one" % (examined,))
        return 0
    paths = [mpath]
    for pid in phase_ids:
        for path in _write_paths(project, mpath, raw_index, pid):
            if path not in paths:
                paths.append(path)
    snap = _snapshot(paths)
    written = []
    try:
        if not _mio.is_sharded(raw_index):
            written = _write_add(project, mpath, raw_index, assembled, None, False)
        else:
            for pid in phase_ids:
                for rel in _write_add(project, mpath, raw_index, assembled, pid,
                                      False,
                                      index_fields=("bugs",) if bugs_moved else ()):
                    if rel not in written:
                        written.append(rel)
            if not phase_ids:
                written = _write_add(project, mpath, raw_index, assembled, None,
                                     False, index_fields=("bugs",))
    except Exception as exc:
        _restore(snap)
        out("[audit-task] write failed -- manifest restored: %s" % exc)
        return E_INVALID
    try:
        written_manifest = _mio.load_manifest(mpath)
        findings, warnings = vm.validate(written_manifest)
    except Exception as exc:
        written_manifest, findings, warnings = {}, ["cannot re-read the written "
                                                    "manifest: %s" % exc], []
    if findings:
        _restore(snap)
        out("[audit-task] REFUSED: settling would leave the manifest invalid -- "
            "every written file rolled back, nothing kept:")
        for line in findings:
            out("FINDING: " + line)
        return E_INVALID
    stubs = [pid for pid in phase_ids
             if pid not in [r["id"] for r in rows if r["kind"] == "phase"]]
    changes = [{"id": r["id"], "field": r["field"], "from": r["stored"],
                "to": r["derived"]} for r in rows]
    jres = _journal_row(project, config, mpath, "plan.settle",
                        "settled %d derived value(s)%s: %s"
                        % (len(rows),
                           (" and %d stale index stub(s)" % (len(stubs),))
                           if stubs else "",
                           ", ".join("%s.%s" % (r["id"], r["field"]) for r in rows)
                           or ", ".join(stubs)),
                        {"changes": changes})
    if args.as_json:
        result = {"ok": True, "stored": rows, "stubs": stubs, "written": written,
                  "phases": n_phases, "bugs": n_bugs,
                  "warnings": _wg.collapse_machine(warnings, written_manifest)}
        result.update(jres)
        result.update(project_basis_key(args))
        out(json.dumps(result, indent=2, sort_keys=True))
        return 0
    out("[audit-task] settled -- %s; %d stored value(s) moved to the derived one"
        % (examined, len(rows)))
    for line in _settled_lines(rows):
        out(line)
    for pid in stubs:
        out("  index stub %s re-mirrored from its shard" % (pid,))
    for line in _wg.collapse(warnings, written_manifest):
        out("WARNING: " + line)
    if not jres.get("journaled") and jres.get("journaledWhy") == "failed":
        out(_not_journaled_line(jres, "the plan.settle row"))
    out("  written: %s" % ", ".join(written))
    return 0


# --- couple / uncouple: meta.coupling, an index-only write ----------------------
# THE ENTRY `_manifest_phases._check_coupling` ALREADY GRADES: `{test, sources,
# basis: {runId, head, phases}, learnedAt}`, one entry per `test` -- a second
# entry for the same test is the validator's own duplicate-test finding, so
# `couple` widens an existing entry's `sources` rather than appending a
# second one, and never invents a shape the checker does not already accept.
#
# THESE TWO READS STAY OUT OF EVERY OTHER VERB'S CLOSURE. `vf6` derives what a
# verb reads by walking the call graph from its door, so a helper this pair
# calls that also read `args.sources` from `add` or `scope` would put
# `sources` in both derived sets at once and the table could not describe
# both truthfully. `_coupling_test_refusal` and `_coupling_sources_refusal`
# take plain values, never `args`, for the same reason `_files_refusal` does;
# `_locked_couple`, `_locked_couple_caught` (reached only through
# `_locked_couple`) and `_locked_uncouple` are the only functions that read
# `args.test` / `args.sources` / `args.basis_run` / `args.basis_head` /
# `args.phases` / `args.caught` at all, the way `retarget`'s own `--gate-set`/`--gate-drop`
# pair stayed inside `_retarget_gate_contradiction` and `_retarget_gate_now`.
def _coupling_test_refusal(test, verbs="couple/uncouple", what="a coupling"):
    """Whether `--test <path>` names something a coupling can be about, or
    None. The same two readings `tests.add` and a suite path already share
    (`_rules.tests_add_path`, `_phases.is_suite_path`) -- a coupling is a
    file a runner ran, never free prose. `mute`/`unmute` ask the same
    question of the same flag, so `verbs` and `what` only change the words."""
    if not test:
        return ("[audit-task] %s needs --test <path>" % (verbs,))
    if _rules.tests_add_path(test) is None or not _phases.is_suite_path(test):
        return ("[audit-task] --test %r does not read as a suite path this "
                "project already recognises a test by (`tests_add_path` and "
                "`is_suite_path` both have to accept it) -- %s names "
                "a file a runner ran, not a sentence about one" % (test, what))
    return None


def _coupling_sources_refusal(sources):
    """Whether every `--sources` value is a path `tests_add_path` accepts, or
    the refusal naming the ones that are not."""
    bad = [s for s in sources if _rules.tests_add_path(s) is None]
    if not bad:
        return None
    return ("[audit-task] --sources names %s that does not read as a path -- "
            "each source is a file the test failed alongside, not free prose"
            % (_output.some_of(bad, render=repr),))


def _coupling_phases_refusal(phases, phase_ids):
    """Whether every `--phases` value names a phase this plan actually
    holds, or the refusal naming the ones that do not. Stored unchecked,
    a typo would sit in `meta.coupling` forever with no rule grading it
    after the fact."""
    bad = [p for p in phases if p not in phase_ids]
    if not bad:
        return None
    return ("[audit-task] --phases names %s that %s not a phase id in this "
            "plan" % (_output.some_of(bad, render=repr),
                     "is" if len(bad) == 1 else "are"))


def cmd_couple(args, out):
    _manifest_from_positional(args)
    project = _resolve_project(args)
    if not os.path.isdir(project):
        out("[audit-task] not a directory: %s" % project)
        return E_USAGE
    return _under_lock(args, project, out,
                       lambda config, mpath: _locked_couple(
                           args, project, config, mpath, out))


def _locked_couple(args, project, config, mpath, out):
    """Learn (or widen) one `meta.coupling` entry, under lock.

    THE THREE REQUIRED FLAGS ARE THE ENTRY'S OWN REQUIRED FIELDS, asked in the
    same order `_check_coupling` grades them in: `--test`, `--sources`, then
    `--basis-run` -- a coupling with no source names nothing this test is
    coupled to, and one with no run id points at nothing, the exact reason
    `_check_coupling`'s own docstring gives for requiring `basis.runId`.

    `--basis-run` IS LOOKED UP, NEVER TRUSTED AS TYPED, `_failing_from_lookup`'s
    own reason: `_evidence_io.row_by_run` is the one answer this project keeps
    to "does a run with this id exist", and reading structure into the string
    here would be a second, silently different answer to a question that
    lookup already settles.

    WIDENED, NEVER SILENTLY REPLACED: a test already coupled gets its
    `sources` UNIONED with the ones just named, `basis` and `learnedAt` left
    exactly as the first call wrote them -- so the entry records what first
    taught the coupling and grows only the list of what it now covers, the
    same shape `_check_coupling`'s docstring reads a widened entry as ("each
    test should carry ONE entry with every source it is coupled to"). A
    re-couple's own `--basis-run`/`--basis-head`/`--phases` are still
    validated (a re-couple with a bad basis is still refused), but never
    written over the first call's basis.

    `--basis-head` IS ASKED OF GIT, not trusted as typed: refused when git
    can be asked and says no, written and reported unverified when it
    cannot be asked at all (no git, a shallow clone) -- `--commit`'s own
    rule, reused rather than re-derived. `--phases` is checked against the
    plan this call is writing into, refused by name when an id is not a
    phase this plan holds.

    `--caught` IS THE OTHER SPELLING, handed to `_locked_couple_caught`
    before any learning flag is read.
    """
    test = (args.test or "").strip()
    refusal = _coupling_test_refusal(test)
    if refusal:
        out(refusal)
        return E_USAGE
    if args.caught is not None:
        return _locked_couple_caught(args, test, project, config, mpath, out)
    sources = _split_csv(args.sources)
    if not sources:
        out("[audit-task] couple needs --sources <path,path> -- a coupling "
            "with no source names nothing this test is coupled to")
        return E_USAGE
    refusal = _coupling_sources_refusal(sources)
    if refusal:
        out(refusal)
        return E_USAGE
    run_id = (args.basis_run or "").strip()
    if not run_id:
        out("[audit-task] couple needs --basis-run <runId> -- a coupling "
            "says what taught it, and a run id is the pointer")
        return E_USAGE
    head = (args.basis_head or "").strip()
    if not head:
        out("[audit-task] couple needs --basis-head <sha> -- the HEAD the "
            "run examined, so a later mismatch has a real answer to compare "
            "against")
        return E_USAGE
    if not _SHA_SHAPE.match(head):
        out("[audit-task] --basis-head %r is not a commit SHA (7-40 hex "
            "characters) -- the same object-id shape `--commit` requires, "
            "so a later mismatch has a real SHA to compare against, not a "
            "name that goes on resolving to whatever it points at later"
            % (head,))
        return E_USAGE
    row, refusal = _ledger_run(
        project, "--basis-run", run_id,
        "a coupling says what taught it, and this run taught nothing "
        "recorded")
    if refusal:
        out(refusal)
        return E_USAGE
    # THE SAME ASK `done --commit` MAKES, reused rather than re-derived
    # (`_commit_git_note`'s own reason): refused when git can be asked and
    # says no, written and reported unverified when it cannot be asked at
    # all (no git, a shallow clone) -- an unasked question is not a clean
    # trail, but it is not a fabricated SHA either.
    git_root = os.path.abspath(os.path.join(project,
                                            (config or {}).get("gitRoot") or "."))
    refusal, unverified = _commit_git_note(git_root, head)
    if refusal:
        out(refusal)
        return E_USAGE
    phases = _split_csv(args.phases)

    plan = _read_plan(mpath, out)
    if isinstance(plan, int):
        return plan
    raw_index, assembled, vm = plan
    phase_ids = set(p.get("id") for p in (assembled.get("phases") or [])
                    if isinstance(p, dict))
    refusal = _coupling_phases_refusal(phases, phase_ids)
    if refusal:
        out(refusal)
        return E_USAGE
    meta = dict(assembled.get("meta") or {})
    coupling = [dict(e) for e in (meta.get("coupling") or [])
               if isinstance(e, dict)]
    idx = next((i for i, e in enumerate(coupling) if e.get("test") == test),
               None)
    if idx is None:
        entry = {"test": test, "sources": sources,
                 "basis": {"runId": run_id, "head": head, "phases": phases},
                 "learnedAt": _utc_now()}
        coupling.append(entry)
        summary = "%s coupled to %s (basis %s)" % (
            test, ", ".join(sources), run_id)
    else:
        was = list(coupling[idx].get("sources") or [])
        merged = list(was)
        for s in sources:
            if s not in merged:
                merged.append(s)
        coupling[idx]["sources"] = merged
        entry = coupling[idx]
        summary = "%s widened: sources %s -> %s (learnedAt kept)" % (
            test, was, merged)
    meta["coupling"] = coupling
    assembled["meta"] = meta

    wrote = _write_plan(project, mpath, raw_index, assembled, vm, [],
                        "the coupling", out, index_fields=("meta",))
    if isinstance(wrote, int):
        return wrote
    written, written_manifest, warnings = wrote
    jres = _journal_row(project, config, mpath, "coupling.learned", summary,
                        {"field": test, "to": entry.get("sources"),
                         "runId": run_id, "commit": head})
    index_note = _index_dirty_note(written, mpath, project, None)
    if args.as_json:
        result = {"ok": True, "test": test, "entry": entry,
                  "written": written, "commitVerified": unverified is None}
        out(_json_tail(result, args, jres, warnings, written_manifest,
                       index_note))
        return 0
    out("[audit-task] %s" % (summary,))
    if unverified:
        out(unverified)
    _report_tail(out, jres, "coupling.learned", warnings, written_manifest,
                written, index_note)
    return 0


def _ledger_run(project, flag, run_id, why):
    """`(row, refusal)` for the evidence row `run_id` names -- exactly one is
    not None. `why` ends the refusal for a run the ledger does not hold.

    A LOST LINE IS NAMED, NEVER READ AS ABSENCE. `read_rows` skips a line it
    cannot parse and counts it; a run not found among the readable rows may
    be on exactly that line, so the refusal says which file could not be
    read in full rather than asserting the run was never recorded."""
    try:
        ledger = _evidence_io.read_rows(project)
    except Exception as exc:
        return None, ("[audit-task] %s %s: the evidence ledger could not be "
                      "read (%s)" % (flag, run_id, exc))
    row = _evidence_io.row_by_run(ledger.get("rows") or [], run_id)
    if row is not None:
        return row, None
    if ledger.get("unreadable"):
        lost = [_output.posix_rel(p, project) if os.path.isabs(p) else p
                for p in (ledger.get("unreadableFiles") or [])]
        return None, ("[audit-task] %s %s: no run with this id is among the "
                      "readable rows of the evidence ledger, and some of it "
                      "could not be read (%s) -- the run may be on a line "
                      "that read lost, so repair it before asking again"
                      % (flag, run_id, ", ".join(lost) or "file unnamed"))
    return None, ("[audit-task] %s %s: no run with this id is in the "
                  "evidence ledger -- %s" % (flag, run_id, why))


def _caught_refusal(row, run_id, test, listing):
    """Why the evidence row `run_id` names cannot be a catch of `test`, or
    None. A catch is a THIRD-PLACE run (scope `full`) whose runner named
    `test` as failing on a step no mute excused. That reading is
    `_evidence_io.named_failing_suites`, the one a fix task's
    `--failing-from` gate and the gate runner take, so a tail excerpt and a
    quarantined step are refused here for the reason they are refused there.
    Its `ts` must read as a moment through `_evidence_io.stamp_moment`, the
    one moment read the ledger orders its rows by, so a date-only stamp is
    placed here where the ledger places it.

    WHETHER `test` IS ONE OF THE NAMED SUITES is `_evidence_io.listed_by`:
    a runner may print a suite relative to its own directory while the
    coupling spells it from the repository root. The catch is still written
    under `test`, the plan's key, never under the runner's spelling.

    A ROW LISTING `test` AS ITS OWN SELECTION MISS IS NO CATCH OF IT
    (`_evidence_io.own_miss`, pinned through `listing`, `full-gate.py`'s
    reading): that row says no derived gate ran the suite, so no coupling
    caught anything in it."""
    if row.get("scope") != _evidence_io.FULL_SCOPE:
        return ("[audit-task] --caught %s is a run of scope %r, not %r -- "
                "only a third-place run is a catch the coupling earned; a "
                "phase or task run is the kind of run that taught it"
                % (run_id, row.get("scope"), _evidence_io.FULL_SCOPE))
    named = _evidence_io.named_failing_suites(row.get("steps"))
    if not _evidence_io.listed_by(test, named):
        return ("[audit-task] --caught %s does not name %s as failing on a "
                "step whose runner named its failing suites and no mute "
                "excused (it named: %s) -- a tail excerpt or a quarantined "
                "failure is not a catch"
                % (run_id, test, ", ".join(named) if named else "none"))
    # THE KEY AND EVERY SPELLING OF IT THE RUNNER PRINTED, as `full-gate.py`
    # asks with the coupled key and the spelling that resolved to it - so a
    # miss the row recorded under the runner's spelling withholds the catch
    # here exactly as it does there, even where git cannot pin that spelling.
    own = _evidence_io.own_miss(
        row, [test] + [s for s in named if _evidence_io.listed_by(test, [s])],
        listing)
    if own is not None:
        return ("[audit-task] --caught %s lists %s as its own selection miss "
                "(selectionMiss names %s) -- no derived gate ran that suite, "
                "so no coupling caught anything in it; full-gate.py credits "
                "no catch from this row either" % (run_id, test,
                                                   own.get("test")))
    if _evidence_io.stamp_moment(row.get("ts")) is None:
        return ("[audit-task] --caught %s carries ts %r, which does not read "
                "as a moment, so there is nothing to record as lastCaught"
                % (run_id, row.get("ts")))
    return None


def _caught_ambiguity(row, run_id, test, keys):
    """Why the run cannot pin its failure on `test` among the plan's coupled
    `keys`, or None. Asked after `_caught_refusal` has found a named suite
    `listed_by` reads as `test`.

    EVERY SPELLING THE RUNNER NAMED FOR `test` IS RESOLVED AGAINST EVERY
    COUPLED KEY (`_evidence_io.resolve_named`), and one that pins to `test`
    alone is the catch. A spelling that also fits another coupled key - a
    bare `test_c.py` beside two `*/test_c.py` couplings - cannot say which
    one failed, and crediting both would reset the age of the coupling that
    caught nothing; so it credits neither, `full-gate.py`'s own reading."""
    named = _evidence_io.named_failing_suites(row.get("steps"))
    reasons = []
    for spelling in named:
        if not _evidence_io.listed_by(test, [spelling]):
            continue
        key, why = _evidence_io.resolve_named(spelling, keys)
        if key == test:
            return None
        reasons.append(why)
    return ("[audit-task] --caught %s: no suite the run named pins to %s "
            "alone among the coupled tests (%s) -- a failure the name cannot "
            "place on one coupling is credited to none"
            % (run_id, test, "; ".join(reasons) or "nothing named it"))


def _locked_couple_caught(args, test, project, config, mpath, out):
    """Set one coupled test's `lastCaught` from a named third-place failure,
    under lock.

    A CATCH NEVER CREATES OR RESHAPES A COUPLING: a test with no entry is
    refused, the learning flags are refused beside `--caught`, and only
    `lastCaught` is written. The run is LOOKED UP through
    `_evidence_io.row_by_run`, `--basis-run`'s own reason.

    NEWEST ONLY, AND IDEMPOTENT. `lastCaught` is the newest catch, so a
    well-formed catch at or before the recorded one -- an older run imported
    late, or the same run replayed by a retry -- writes nothing and adds no
    journal row, and still exits 0 saying so: the fact it offers is already
    covered. Both sides are compared as MOMENTS through
    `_evidence_io.stamp_moment`, the ledger's own moment read, never as
    text, because an offset against `Z` or a fractional second
    sorts differently as a string than in time. A recorded `lastCaught` no
    parser reads is replaced by the catch offered, which does read.
    """
    run_id = (args.caught or "").strip()
    if not run_id:
        out("[audit-task] --caught needs a runId -- the full run that named "
            "this test as failing")
        return E_USAGE
    extra = [flag for flag, value in (
        ("--sources", args.sources), ("--basis-run", args.basis_run),
        ("--basis-head", args.basis_head), ("--phases", args.phases))
        if value is not None]
    if extra:
        out("[audit-task] --caught records a catch and changes nothing else "
            "on the entry, so it takes none of %s" % (", ".join(extra),))
        return E_USAGE
    row, refusal = _ledger_run(
        project, "--caught", run_id,
        "a catch names the full run that caught it")
    if refusal:
        out(refusal)
        return E_USAGE
    refusal = _caught_refusal(row, run_id, test,
                              _evidence_io.suite_listing(project))
    if refusal:
        out(refusal)
        return E_USAGE
    ts = str(row.get("ts"))

    plan = _read_plan(mpath, out)
    if isinstance(plan, int):
        return plan
    raw_index, assembled, vm = plan
    meta = dict(assembled.get("meta") or {})
    coupling = [dict(e) for e in (meta.get("coupling") or [])
               if isinstance(e, dict)]
    idx = next((i for i, e in enumerate(coupling) if e.get("test") == test),
               None)
    if idx is None:
        out("[audit-task] couple --caught: %r carries no meta.coupling entry "
            "-- a catch is recorded against a coupling, never in place of "
            "one; learn it with --sources/--basis-run/--basis-head first"
            % (test,))
        return E_USAGE
    refusal = _caught_ambiguity(row, run_id, test,
                                [e.get("test") for e in coupling
                                 if e.get("test")])
    if refusal:
        out(refusal)
        return E_USAGE
    was = coupling[idx].get("lastCaught")
    was_at = _evidence_io.stamp_moment(was)
    if was_at is not None and was_at >= _evidence_io.stamp_moment(ts):
        if args.as_json:
            out(json.dumps({"ok": True, "test": test,
                            "entry": coupling[idx], "written": [],
                            "unchanged": True}, sort_keys=True))
            return 0
        out("[audit-task] %s: lastCaught already records a newer or the same "
            "catch (%s; run %s ran at %s) -- nothing written, since "
            "lastCaught is the newest catch and never moves back"
            % (test, was, run_id, ts))
        return 0
    coupling[idx]["lastCaught"] = ts
    entry = coupling[idx]
    meta["coupling"] = coupling
    assembled["meta"] = meta

    wrote = _write_plan(project, mpath, raw_index, assembled, vm, [],
                        "the catch", out, index_fields=("meta",))
    if isinstance(wrote, int):
        return wrote
    written, written_manifest, warnings = wrote
    summary = "%s caught by run %s: lastCaught %s -> %s" % (
        test, run_id, was or "(never)", ts)
    jres = _journal_row(project, config, mpath, "coupling.caught", summary,
                        {"field": test, "from": was, "to": ts,
                         "runId": run_id})
    index_note = _index_dirty_note(written, mpath, project, None)
    if args.as_json:
        result = {"ok": True, "test": test, "entry": entry,
                  "written": written}
        out(_json_tail(result, args, jres, warnings, written_manifest,
                       index_note))
        return 0
    out("[audit-task] %s" % (summary,))
    _report_tail(out, jres, "coupling.caught", warnings, written_manifest,
                written, index_note)
    return 0


def cmd_uncouple(args, out):
    _manifest_from_positional(args)
    project = _resolve_project(args)
    if not os.path.isdir(project):
        out("[audit-task] not a directory: %s" % project)
        return E_USAGE
    return _under_lock(args, project, out,
                       lambda config, mpath: _locked_uncouple(
                           args, project, config, mpath, out))


def _locked_uncouple(args, project, config, mpath, out):
    """Drop one `meta.coupling` entry by `--test <path>`, under lock. Refused,
    exit 2, when the test carries no entry -- an uncouple of a test nothing
    coupled would otherwise be a no-op reporting success."""
    test = (args.test or "").strip()
    refusal = _coupling_test_refusal(test)
    if refusal:
        out(refusal)
        return E_USAGE
    plan = _read_plan(mpath, out)
    if isinstance(plan, int):
        return plan
    raw_index, assembled, vm = plan
    meta = dict(assembled.get("meta") or {})
    coupling = [dict(e) for e in (meta.get("coupling") or [])
               if isinstance(e, dict)]
    idx = next((i for i, e in enumerate(coupling) if e.get("test") == test),
               None)
    if idx is None:
        out("[audit-task] uncouple: %r carries no meta.coupling entry -- "
            "nothing to drop" % (test,))
        return E_USAGE
    entry = coupling.pop(idx)
    meta["coupling"] = coupling
    assembled["meta"] = meta

    wrote = _write_plan(project, mpath, raw_index, assembled, vm, [],
                        "the uncoupling", out, index_fields=("meta",))
    if isinstance(wrote, int):
        return wrote
    written, written_manifest, warnings = wrote
    jres = _journal_row(project, config, mpath, "coupling.dropped",
                        "%s uncoupled from %s" % (
                            test, ", ".join(entry.get("sources") or [])),
                        {"field": test, "from": entry.get("sources")})
    index_note = _index_dirty_note(written, mpath, project, None)
    if args.as_json:
        result = {"ok": True, "test": test, "dropped": entry,
                  "written": written}
        out(_json_tail(result, args, jres, warnings, written_manifest,
                       index_note))
        return 0
    out("[audit-task] %s uncoupled" % (test,))
    _report_tail(out, jres, "coupling.dropped", warnings, written_manifest,
                written, index_note)
    return 0


# --- bug-add: the bug `commands/bug.md` spells, written by a verb ---------------
# `/audit:bug add` used to hand-edit `bugs[]` after asking `next-id bug` for the
# id, so the step-3 shape was a paragraph the model re-typed on every report and
# nothing checked that every key reached the file. The shape is a tuple here,
# written in this order, every key present -- the unset links as null, which is
# how a reader tells "not materialized yet" from "this writer forgot the key".
_BUG_TEMPLATE_KEYS = ("id", "title", "status", "severity", "reportedAt",
                      "reportedBy", "description", "repro", "expected",
                      "actual", "files", "taskId", "fixedIn", "notes")


def cmd_bug_add(args, out):
    project = _resolve_project(args)
    if not os.path.isdir(project):
        out("[audit-task] not a directory: %s" % project)
        return E_USAGE
    return _under_lock(args, project, out,
                       lambda config, mpath: _locked_bug_add(
                           args, project, config, mpath, out))


def _locked_bug_add(args, project, config, mpath, out):
    """Append one bug to `bugs[]`, under lock, in `_BUG_TEMPLATE_KEYS`' shape.

    THE REQUIRED ANSWERS ARE REFUSED BEFORE THE READ: a title, a severity in
    the words a finding takes (`_phases.FINDING_SEVERITY`, which the schema
    says a bug's severity is consistent with) and a description. `--files`,
    `--repro`, `--expected` and `--actual` may be absent -- `commands/bug.md`
    allows an empty `files`, and a report can know what happened before it
    knows how to make it happen again -- and an absent one is written as the
    empty list or null, never left out.

    THE WORDS ARE WRITTEN AS PASSED. `resolve_briefs` has already read `-`
    off stdin and refused a shell-eaten gap; nothing here trims or rewraps
    the operator's text, because a bug's repro is quoted verbatim into the
    fix task `/audit:bug fix` materializes.

    INDEX-ONLY: `bugs` lives in the index, so no shard is touched.
    """
    title = args.title or ""
    if not title.strip():
        out("[audit-task] bug-add needs a title: bug-add \"<title>\"")
        return E_USAGE
    severity = (args.severity or "").strip()
    if severity not in _phases.FINDING_SEVERITY:
        out("[audit-task] bug-add needs --severity %s, got %r"
            % ("|".join(_phases.FINDING_SEVERITY), args.severity))
        return E_USAGE
    description = args.description or ""
    if not description.strip():
        out("[audit-task] bug-add needs --description TEXT -- a bug with no "
            "description is a title nobody can triage")
        return E_USAGE
    files = _split_csv(args.files)
    bad = _path_problems(files)
    if bad:
        out("[audit-task] --files names the suspected repository-relative "
            "files, and %s" % ("; ".join(bad),))
        return E_USAGE

    plan = _read_plan(mpath, out)
    if isinstance(plan, int):
        return plan
    raw_index, assembled, vm = plan
    bug_id = _id_shape.next_bug_id(assembled, _mint_suffix(mpath, assembled))
    values = {"id": bug_id, "title": title, "status": "open",
              "severity": severity, "reportedAt": _utc_now(),
              "reportedBy": None, "description": description,
              "repro": args.repro, "expected": args.expected,
              "actual": args.actual, "files": files, "taskId": None,
              "fixedIn": None, "notes": None}
    bug = dict((key, values[key]) for key in _BUG_TEMPLATE_KEYS)
    assembled["bugs"] = list(assembled.get("bugs") or []) + [bug]

    wrote = _write_plan(project, mpath, raw_index, assembled, vm, [],
                        "the bug", out, index_fields=("bugs",))
    if isinstance(wrote, int):
        return wrote
    written, written_manifest, warnings = wrote
    summary = "%s reported (%s): %s" % (bug_id, severity, title)
    jres = _journal_row(project, config, mpath, "bug.add", summary,
                        {"field": bug_id, "to": "open"})
    index_note = _index_dirty_note(written, mpath, project, None)
    if args.as_json:
        result = {"ok": True, "bugId": bug_id, "bug": bug,
                  "written": written}
        out(_json_tail(result, args, jres, warnings, written_manifest,
                       index_note))
        return 0
    out("[audit-task] %s" % (summary,))
    out("  next: /audit:bug fix %s when it is ready to be worked" % (bug_id,))
    _report_tail(out, jres, "bug.add", warnings, written_manifest, written,
                 index_note)
    return 0


# --- mute / unmute: meta.muted, an index-only write -----------------------------
# THE ENTRY `_manifest_rules._check_muted` ALREADY GRADES, `{test, reason,
# owner, until, bugId}`, one per `test`. These two verbs are its only writers.
#
# THE BUG IS NOT LOOKED UP HERE. A mute naming a bug `bugs[]` lacks is the
# validator's own finding, and `_write_plan` revalidates the written plan and
# rolls every file back on a finding -- so the refusal arrives as the
# validator's sentence, exit 1, with nothing kept. A second lookup in this
# verb would be a second answer to that question, free to drift from the one
# the plan is graded by. What IS refused here, exit 2, is a mute with no
# `--bug` at all: that is a missing answer, not a wrong one, and refusing it
# before the read costs no rollback.
#
# AN EXPIRED MUTE IS A WARNING, NEVER A FINDING, so `_read_plan`'s pre-check
# passes a plan that carries one and both verbs run on it -- which is the whole
# reason `_check_muted` keeps expiry out of the findings.
#
# THE READS STAY INSIDE THIS PAIR, `couple`'s reason: `_locked_mute` and
# `_locked_unmute` are the only functions that read `args.test`/`args.owner`/
# `args.until`/`args.bug` for these verbs, so the call-graph derivation of
# `VERB_FLAGS` sees them on these doors alone.
def _mute_until_refusal(raw, today, current=None):
    """The refusal for an `--until` this mute cannot carry, or None.

    Read through `_vocab.mute_until`/`mute_expired`, the one reading of the
    field the validator and the runner share: an unreadable day, a day already
    past (a mute the runner would not honour, so a write reporting success
    for nothing), and -- on a test already muted -- a day that does not move
    the current `until` later, since extending is the one change this verb
    makes to an existing entry.
    """
    until = _vocab.mute_until(raw)
    if until is None:
        return ("[audit-task] mute needs --until <YYYY-MM-DD>, the last UTC "
                "day the mute holds; got %r" % (raw,))
    if _vocab.mute_expired(until, today):
        return ("[audit-task] --until %s is already past (today is %s in "
                "UTC), so the runner would not honour this mute and nothing "
                "would be quarantined" % (raw, today.isoformat()))
    held = _vocab.mute_until(current) if current is not None else None
    if current is not None and held is not None and not until > held:
        return ("[audit-task] this test is already muted until %s, and a "
                "re-mute only EXTENDS: --until %s does not move that later. "
                "Lift it with `unmute --test` first to shorten it"
                % (current, raw))
    return None


def cmd_mute(args, out):
    _manifest_from_positional(args)
    project = _resolve_project(args)
    if not os.path.isdir(project):
        out("[audit-task] not a directory: %s" % project)
        return E_USAGE
    return _under_lock(args, project, out,
                       lambda config, mpath: _locked_mute(
                           args, project, config, mpath, out))


def _locked_mute(args, project, config, mpath, out):
    """Write (or extend) one `meta.muted` entry, under lock."""
    test = (args.test or "").strip()
    refusal = _coupling_test_refusal(test, "mute/unmute", "a mute")
    if refusal:
        out(refusal)
        return E_USAGE
    bug = (args.bug or "").strip()
    if not bug:
        out("[audit-task] mute needs --bug <bugId> -- a quarantine must name "
            "the bug tracking the failure it hides; file one with "
            "`/audit:bug add` first")
        return E_USAGE
    reason = args.reason or ""
    if not reason.strip():
        out("[audit-task] mute needs --reason TEXT -- why the suite is muted "
            "rather than fixed")
        return E_USAGE
    owner = (args.owner or "").strip()
    if not owner:
        out("[audit-task] mute needs --owner NAME -- who answers for lifting "
            "it")
        return E_USAGE
    raw_until = (args.until or "").strip()
    today = _vocab.mute_today()
    refusal = _mute_until_refusal(raw_until, today)
    if refusal:
        out(refusal)
        return E_USAGE

    plan = _read_plan(mpath, out)
    if isinstance(plan, int):
        return plan
    raw_index, assembled, vm = plan
    meta = dict(assembled.get("meta") or {})
    muted = [dict(e) if isinstance(e, dict) else e
             for e in (meta.get("muted") or [])]
    idx = next((i for i, e in enumerate(muted)
                if isinstance(e, dict) and e.get("test") == test), None)
    entry = {"test": test, "reason": reason, "owner": owner,
             "until": raw_until, "bugId": bug}
    was = None
    if idx is None:
        muted.append(entry)
        summary = "%s muted until %s (%s, owner %s)" % (test, raw_until, bug,
                                                       owner)
    else:
        was = muted[idx].get("until")
        refusal = _mute_until_refusal(raw_until, today, current=was)
        if refusal:
            out(refusal)
            return E_USAGE
        muted[idx] = entry
        summary = "%s mute extended: until %s -> %s (%s, owner %s)" % (
            test, was, raw_until, bug, owner)
    meta["muted"] = muted
    assembled["meta"] = meta

    wrote = _write_plan(project, mpath, raw_index, assembled, vm, [],
                        "the mute", out, index_fields=("meta",))
    if isinstance(wrote, int):
        return wrote
    written, written_manifest, warnings = wrote
    jres = _journal_row(project, config, mpath, "test.muted", summary,
                        {"field": test, "from": was, "to": raw_until,
                         "reason": reason})
    index_note = _index_dirty_note(written, mpath, project, None)
    if args.as_json:
        result = {"ok": True, "test": test, "entry": entry,
                  "extendedFrom": was, "written": written}
        out(_json_tail(result, args, jres, warnings, written_manifest,
                       index_note))
        return 0
    out("[audit-task] %s" % (summary,))
    _report_tail(out, jres, "test.muted", warnings, written_manifest, written,
                 index_note)
    return 0


def cmd_unmute(args, out):
    _manifest_from_positional(args)
    project = _resolve_project(args)
    if not os.path.isdir(project):
        out("[audit-task] not a directory: %s" % project)
        return E_USAGE
    return _under_lock(args, project, out,
                       lambda config, mpath: _locked_unmute(
                           args, project, config, mpath, out))


def _locked_unmute(args, project, config, mpath, out):
    """Drop the one `meta.muted` entry for `--test`, under lock. Refused, exit
    2, when the test carries none -- a lift of nothing reporting success would
    hide that nothing was muted."""
    test = (args.test or "").strip()
    refusal = _coupling_test_refusal(test, "mute/unmute", "a mute")
    if refusal:
        out(refusal)
        return E_USAGE
    plan = _read_plan(mpath, out)
    if isinstance(plan, int):
        return plan
    raw_index, assembled, vm = plan
    meta = dict(assembled.get("meta") or {})
    muted = list(meta.get("muted") or [])
    idx = next((i for i, e in enumerate(muted)
                if isinstance(e, dict) and e.get("test") == test), None)
    if idx is None:
        out("[audit-task] unmute: %r carries no meta.muted entry -- nothing "
            "to lift" % (test,))
        return E_USAGE
    entry = muted.pop(idx)
    meta["muted"] = muted
    assembled["meta"] = meta

    wrote = _write_plan(project, mpath, raw_index, assembled, vm, [],
                        "the unmute", out, index_fields=("meta",))
    if isinstance(wrote, int):
        return wrote
    written, written_manifest, warnings = wrote
    jres = _journal_row(project, config, mpath, "test.unmuted",
                        "%s unmuted (was until %s, %s)" % (
                            test, entry.get("until"), entry.get("bugId")),
                        {"field": test, "from": entry.get("until")})
    index_note = _index_dirty_note(written, mpath, project, None)
    if args.as_json:
        result = {"ok": True, "test": test, "dropped": entry,
                  "written": written}
        out(_json_tail(result, args, jres, warnings, written_manifest,
                       index_note))
        return 0
    out("[audit-task] %s unmuted" % (test,))
    _report_tail(out, jres, "test.unmuted", warnings, written_manifest,
                 written, index_note)
    return 0


# --- next-id: the id a hand-written record takes ---------------------------------
# A bug, a parked proposal and a bug's fix task are the records the model still
# writes by hand (`commands/bug.md`, `init.md`), so they were also the ids the model
# computed by hand - `BUG-<max+1>`, `PROP-<max+1>`, `<phaseId>.<next>` - and two
# branches computing one from the same base wrote the same id. A moved task was one
# of them until `move` became a verb; it takes this same allocator's answer in
# process. This prints the id the allocator would take, suffix and
# reservations included, so the hand-written record carries the same answer every
# scripted one does. NOT `phase`: a phase is minted only by `add-phase`, which
# writes it under the lock, and a phase id printed ahead of its write would be one
# nothing reserves in between - where for a task the phase it belongs to is fixed.
NEXT_ID_KINDS = ("bug", "prop", "task")


def cmd_next_id(args, out):
    project = _resolve_project(args)
    kind = (args.title or "").strip()
    if kind not in NEXT_ID_KINDS:
        out("[audit-task] next-id takes %s, not %r - a phase id is minted only by "
            "add-phase, which writes it" % (" | ".join(NEXT_ID_KINDS), kind))
        return E_USAGE
    if kind == "task" and not args.phase:
        out("[audit-task] next-id task needs --phase <id>: a task id belongs to a phase")
        return E_USAGE
    if kind != "task" and args.phase:
        out("[audit-task] next-id %s does not read --phase" % (kind,))
        return E_USAGE

    def body(config, mpath):
        assembled = _mio.load_manifest(mpath)
        suffix = _mint_suffix(mpath, assembled)
        if kind == "task":
            ident = _allocate_id(assembled, args.phase, suffix)
        elif kind == "prop":
            ident = _id_shape.next_prop_id(assembled, suffix)
        else:
            ident = _id_shape.next_bug_id(assembled, suffix)
        if args.as_json:
            # `suffix` is carried so a reader can tell "this branch mints plain ids"
            # (null) from an id that merely happens to end in three letters.
            result = {"kind": kind, "id": ident, "suffix": suffix}
            result.update(project_basis_key(args))
            out(json.dumps(result, indent=2, sort_keys=True))
            return 0
        out(ident)
        return 0
    return _under_lock(args, project, out, body)


# --- seed: the smallest honest plan, written where none exists yet -------------
# `/audit:init` is multi-agent and interviews a human before it writes
# anything, which is the right shape for a real audit and the wrong one for a
# repository that only wants the guards a manifest turns on. This verb is the
# second, cheap door: no interview, no exploration, no invented findings -- one
# phase, one task, a gate that is either the caller's own `--gate` or honestly
# empty. A plan that LOOKS complete and describes work nobody agreed to is worse
# than three lines, because the first thing it teaches a reader is that the
# manifest is decoration.
DEFAULT_SEED_PHASE_TITLE = "Bootstrap"
DEFAULT_SEED_TASK_TITLE = "Point this plan at real work"
DEFAULT_SEED_OUTCOME = ("A valid plan exists, and the guards that need one are "
                        "live; nothing in it was invented.")
DEFAULT_SEED_DESCRIPTION = (
    "No test, lint or build command could be honestly detected here, so "
    "meta.buildCommands stays empty rather than guessed. Set it once you know "
    "what this repository actually runs -- by hand, or from /audit:panel -- "
    "then use /audit:task add for the first real task. This one exists only "
    "to make the plan true instead of empty.")


def _git_remote_name(project):
    """The repo name off `git remote get-url origin`, or None.

    Best-effort and silent on failure by design: a project with no remote, or
    no git at all, still gets a plan. `meta.repo` is descriptive text nothing
    validates against, so a wrong guess here costs nothing a human cannot fix
    by hand later -- which is not true of a guessed gate command, and is why
    only THIS field is guessed at all.
    """
    try:
        raw = subprocess.check_output(
            ["git", "-C", project, "remote", "get-url", "origin"],
            stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return None
    url = raw.decode("utf-8", "replace").strip()
    name = url.rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name or None


def _seed_meta(project):
    """The smallest honest `meta` for a plan nobody has written yet.

    NOTHING HERE IS DETECTED. `/audit:init`'s recon reads a tree's
    package.json/Makefile/pyproject.toml and drafts `meta.buildCommands` from
    what LOOKS runnable -- a judgement call this file leaves to the human
    being interviewed, because a wrong guess here is a gate that refuses a
    phase for a command that was never real. So a seeded plan's
    `buildCommands` is empty rather than guessed, and `_phase_gate` says so
    in the sentence it returns rather than in a comment nobody reads at
    run time.
    """
    repo = _git_remote_name(project) or os.path.basename(
        os.path.abspath(project).rstrip(os.sep)) or "repo"
    return {
        "version": _mio.LAYOUT_VERSION["single-file"],
        "repo": repo,
        "developmentBranch": "main",
        "branchPrefix": "audit",
        "gitRoot": ".",
        "buildCommands": {},
        "createdISO": _utc_now(),
    }


def _seed_phase(pid, title, gate):
    """The new phase's dict, template fields only (conventions -> New phase
    template).

    NOT `_build_phase`. That function reads `args.description`, `.outcome`,
    `.blocked_by`, `.area` and `.review_skill` off the caller's namespace, none
    of which `seed` exposes as a flag -- there is nothing yet to describe,
    block on or tag. Calling it anyway would put every one of those reads in
    `seed`'s own derived flag set the way the suite's `vf6` computes it, which
    would make a verb that accepts none of those flags LOOK like it reads all
    of them. The one piece of real judgement -- deriving an honest gate -- is
    still shared, through `_phase_gate`; this is the fixed shape the
    conventions document, applied to fixed values.
    """
    return {
        "id": pid,
        "title": title,
        "status": "pending",
        "description": "",
        "desiredOutcome": DEFAULT_SEED_OUTCOME,
        "testGate": gate,
        "blockedBy": [],
        "baseRef": None,
        "branch": None,
        "mergedAt": None,
        "review": {"tool": None, "model": "sonnet", "status": "pending",
                   "findings": []},
        "summary": None,
        "tasks": [],
    }


def _seed_task(task_id, title, gate, gate_basis):
    """The new task's dict, template fields only (conventions -> New task
    template). See `_seed_phase` for why this does not call `_build_task`."""
    return {
        "id": task_id,
        "title": title,
        "status": "pending",
        "description": DEFAULT_SEED_DESCRIPTION,
        "files": [],
        "tests": {"mode": "gate-only", "add": [], "expectRedFirst": False,
                  "gate": gate, "gateBasis": gate_basis},
        "model": _model_floor("low"),
        "skills": [],
        "risk": "low",
        "blockedBy": [],
        "dependsOn": [],
        "attempts": 0,
        "maxAttempts": 3,
        "commit": None,
        "outcome": {"technical": None, "descriptive": None},
        "startedAt": None,
        "completedAt": None,
        "verifiedBy": [],
    }


def _locked_seed(args, project, config, mpath, out):
    """Write the smallest valid, honest manifest to a path nothing occupies
    yet: one phase, one task, and a gate the caller declared with `--gate` or
    an honestly empty one -- never a guessed one. Written straight to disk
    (there is no earlier version to read, allocate against or roll back to),
    then re-read and validated exactly like every other write in this file; a
    manifest this would leave invalid is REMOVED rather than kept, because
    keeping an invalid file nobody asked for is worse than writing nothing."""
    contradiction = _gate_contradiction(args)
    if contradiction:
        out(contradiction)
        return E_USAGE
    meta = _seed_meta(project)
    assembled = {"meta": meta, "phases": [], "fileIndex": {}, "bugs": []}
    gate, gate_basis = _phase_gate(args, assembled)
    pid = "P1"
    phase_title = (args.title or "").strip() or DEFAULT_SEED_PHASE_TITLE
    phase = _seed_phase(pid, phase_title, gate)
    assembled["phases"].append(phase)

    task_id = pid + ".1"
    task_gate, _task_gate_sentence, task_gate_word = _task_gate(
        args, phase, assembled, [], [])
    task = _seed_task(task_id, DEFAULT_SEED_TASK_TITLE, task_gate,
                      task_gate_word)
    phase["tasks"].append(task)

    vm = _validator()
    broken = _refuse_broken_install(vm, out)
    if broken is not None:
        return broken
    try:
        written = _mio.save_single_file(mpath, assembled)
    except Exception as exc:
        out("[audit-task] write failed: %s" % exc)
        return E_INVALID

    try:
        written_manifest = _mio.load_manifest(mpath)
        findings, warnings = vm.validate(written_manifest)
    except Exception as exc:
        findings, warnings = ["cannot re-read the written manifest: %s"
                              % exc], []
    if findings:
        try:
            os.remove(mpath)
        except OSError:
            pass
        out("[audit-task] REFUSED: the smallest plan this would write is "
            "not valid, so nothing was kept:")
        for line in findings:
            out("FINDING: " + line)
        return E_INVALID

    jres = _journal_row(project, config, mpath, "plan.seed",
                        "seeded the smallest honest plan: %s (%s)"
                        % (pid, task_id),
                        {"phaseId": pid, "taskId": task_id})
    if args.as_json:
        result = {"ok": True, "phaseId": pid, "taskId": task_id,
                  "phase": phase, "written": written,
                  "warnings": _wg.collapse_machine(warnings, written_manifest),
                  "testGateBasis": gate_basis, "taskGateBasis": task_gate_word}
        result.update(jres)
        result.update(project_basis_key(args))
        out(json.dumps(result, indent=2, sort_keys=True))
        return 0
    out("[audit-task] seeded the smallest honest plan at %s" % mpath)
    out("  phase %s: %s" % (pid, phase_title))
    out("  task %s: %s" % (task_id, DEFAULT_SEED_TASK_TITLE))
    out("  gate: %s (%s)" % (", ".join(gate) if gate else "none", gate_basis))
    for line in _wg.collapse(warnings, written_manifest):
        out("WARNING: " + line)
    if not jres.get("journaled") and jres.get("journaledWhy") == "failed":
        out(_not_journaled_line(jres, "the plan.seed row"))
    out("  written: %s" % ", ".join(written))
    out("  next: /audit:status, then set meta.buildCommands once you know "
        "what this repository runs, or /audit:task add the first real work")
    return 0


def cmd_seed(args, out):
    project = _resolve_project(args)
    if not os.path.isdir(project):
        out("[audit-task] not a directory: %s" % project)
        return E_USAGE
    return _under_lock(args, project, out,
                       lambda config, mpath: _locked_seed(
                           args, project, config, mpath, out),
                       must_exist=False)


# --- which verb reads which flag -------------------------------------------------
# ONE PARSER SERVES EVERY VERB, so argparse accepts every flag on every one of them
# and each verb's writer reads only the subset it knows. Driven across the whole
# grid, half the (verb, flag) pairs were accepted, wrote nothing and reported
# success with exit 0: `scope --outcome`, `retarget --files`, `add --id`,
# `add-phase --risk`, `add-phase --files` among them. That is the same defect
# fixed before, each time for ONE flag on ONE verb -- and `--rename`
# was born
# ignored by four verbs, which is what makes it a class: a new flag inherits it by
# existing.
#
# NOT SUBPARSERS. That is the obvious repair and the expensive one: it moves every
# flag's help text, changes `--help`, and breaks the `argument-hint` shape
# `tests/test__refs.py` parses out of both command docs. The table is the thing that
# has to exist either way -- subparsers would BE this table, spelled in argparse.
#
# THE FLAGS EVERY VERB READS, spelled once. `_resolve_project` reads
# `project_dir`, `_under_lock` reads `takeover`, and every verb's report branches
# on `as_json`, so these are not per-verb facts: listing them once per verb would
# let one verb quietly stop reading one while the table went on saying it did. The
# suite's `vf8` asserts this is EXACTLY the intersection of the derived sets,
# so a flag that becomes universal cannot stay listed per verb and one that stops
# being universal cannot stay here either.
#
# `command`, `title` and `manifest` are POSITIONALS and are deliberately absent:
# there is no way to pass one to the wrong verb, so there is nothing here to
# refuse. `option_dests()` is what draws that line, off the parser rather than by
# this tuple remembering to leave them out.
UNIVERSAL_FLAGS = ("project_dir", "takeover", "as_json")

# ...and the rest, per verb, as DESTS rather than option strings: a dest is what the
# code reads and what the AST derivation below sees, and the option string is
# recovered from the parser for the message. Graded against the real dispatch by
# `plugins/audit/tests/test_audit_task.py`'s `vf` group, which walks this file's own
# call graph from `main`'s `doors` map -- a hand-written table nothing compares to
# the code is the same defect one level up.
VERB_FLAGS = {
    # `outputs` is on `add` and on no other verb, and that is a bound rather
    # than an oversight: `scope`'s whole apparatus -- the widening permission,
    # the narrowing refusal, the fileIndex re-derivation -- is written about
    # `files`, and a second scope-shaped list moving through it would inherit
    # none of those rules while looking as though it had. Declaring the
    # artefacts at `add` is the shape the plan is written in; changing them
    # afterwards is its own verb and its own refusals.
    "add": ("phase", "skills", "model", "files", "outputs", "risk",
            "blocked_by", "depends_on", "description", "tests_mode",
            "tests_add", "gate", "gate_clear", "dry_run", "failing_from"),
    "add-phase": ("phase_id", "outcome", "description", "area", "review_skill",
                  "blocked_by", "gate", "gate_clear", "park"),
    "cancel": ("reason",),
    # EMPTY ON PURPOSE, and it is a row rather than an omission: `start` takes
    # an id and writes the three fields `reference/orchestrator.md` prescribes,
    # so every flag on this parser except the universal ones belongs to some
    # other verb and passing one here is a usage error. A verb ABSENT
    # from this table would instead be refused every flag including the
    # universal ones, and `vf6` grades the row against the real dispatch either
    # way.
    "start": (),
    # `done` closes what `start` opened, and `commit` is the row that makes the
    # verb worth having rather than an optional extra -- `cmd_done` refuses
    # without it, which is a different check from this one: this table says which
    # flags the verb READS, and the door says which of them it requires.
    "done": ("commit", "descriptive", "technical", "verified_by", "intent",
             "intent_basis", "no_change", "reason", "override_verdict"),
    "scope": ("files", "tests_mode", "tests_add", "gate", "gate_clear",
              "description", "risk", "blocked_by", "depends_on"),
    "retarget": ("gate", "gate_clear", "gate_drop", "gate_set", "area",
                 "outcome", "description", "rename"),
    # `seed` writes where nothing exists yet, so it has no target to describe,
    # tag or rename -- only the one pair every gate-bearing verb offers, for a
    # caller who already knows the real command.
    "seed": ("gate", "gate_clear"),
    # `next-id` prints an id and writes nothing; `--phase` is the phase a task id
    # belongs to, and the only flag it reads.
    "next-id": ("phase",),
    # `signoff` writes the one record a phase's `done` is derived from - the
    # review's verdict - and the paragraph sign-off owes the reader.
    # `--branch` and `--plan` are the group's: the branch several phases were
    # built on, and the read-only preview of what signing them off together owes.
    # `--bind` writes a group's branch and fork point before its invariants run;
    # `--no-evidence-reason` is the recorded why of a `passed` with no gate run.
    # `--accept <sha> --reason` takes a commit no member records into a group's
    # review, recorded with why.
    "signoff": ("verdict", "summary", "review_outcome", "branch", "plan", "bind",
                "no_evidence_reason", "accept", "reason"),
    # `settle` stores what the derivations already answer, over the whole plan, so
    # there is nothing for a flag to choose - an empty row, for `start`'s reason.
    "settle": (),
    # `reopen` undoes one close and records why, so its one flag is `cancel`'s.
    "reopen": ("reason",),
    # `move` takes the phase the task goes to; the new id is allocated, never
    # passed, so there is no flag for it.
    "move": ("to",),
    # `block` records why, so its one flag is `cancel`'s too.
    "block": ("reason",),
    # `note` appends one entry, and its text is its one flag.
    "note": ("text",),
    # `couple` writes `meta.coupling`: the test, what it is coupled to, and
    # the run that taught it. `--phases` is the only learning flag that may
    # be absent -- a coupling learned off a run with no phase scope narrows
    # nothing by phase, which is a legal answer and not a hole. `--caught` is
    # the other spelling: it records a catch on an entry that already exists
    # and takes none of the learning flags.
    "couple": ("test", "sources", "basis_run", "basis_head", "phases",
               "caught"),
    # `uncouple` drops one entry by the test alone; it shares `--test` with
    # `couple` and reads nothing else `couple` does.
    "uncouple": ("test",),
    # `finding` takes a finding's four flagged fields, one flag per field and
    # spelled as the field; the id is allocated, never passed.
    "finding": ("severity", "file", "issue", "resolution", "findings_file"),
    # `resolve-finding` names the fix task and, when it has not recorded one,
    # the commit - `done`'s `--commit`, the same SHA in the same shape.
    "resolve-finding": ("fix_task", "commit"),
    # `correct` takes the two texts a sign-off wrote and nothing else; it has
    # no `verdict` on purpose, so passing one is refused as a misplaced flag.
    "correct": ("review_outcome", "summary"),
    # `bug-add` writes one bug in the shape `commands/bug.md` spells; the
    # title is the positional and the id is allocated, so neither is a flag.
    # `--severity` is shared with `finding`, whose field takes the same words.
    "bug-add": ("severity", "description", "files", "repro", "expected",
                "actual"),
    # `mute` writes one `meta.muted` entry, one flag per field; `unmute`
    # drops one by the test alone, `uncouple`'s shape.
    "mute": ("test", "reason", "owner", "until", "bug"),
    "unmute": ("test",),
}



def _list_help(what, example, empties=True):
    """The `--help` text every comma-list flag carries: the separator, that the
    flag repeats, and an example - the separator used to be guessed. `empties`
    is whether `--flag ""` empties the field, which holds for the id lists and
    `--verified-by` and not for `--files` (a scope with no files is refused)."""
    return ("%s, comma-separated; the flag may also repeat, and the values join "
            "in order (e.g. %s, or the same flag once per value)%s"
            % (what, example, ". An empty value empties the field" if empties
               else ""))


def build_parser():
    """The parser, reachable without starting a process.

    EXTRACTED FOR THREE READERS, and P26.1 did the same to `audit-doctor.py` for
    the first of them. `_help.command_choice_drift` constructs a command's parser
    and asks argparse itself which values a flag takes, and a parser built inside
    `main()` cannot be asked; `supplied_flags` below needs a SECOND instance of
    the same parser, and a second copy of the construction is how the two would
    come to disagree about which flags exist; and a case can read the option
    surface without driving a command.
    """
    p = argparse.ArgumentParser(prog="audit-task.py", add_help=True)
    p.add_argument("command",
                   choices=["add", "add-phase", "cancel", "scope",
                            "retarget", "start", "done", "seed", "next-id",
                            "signoff", "settle", "reopen", "move", "block",
                            "note", "couple", "uncouple", "finding",
                            "resolve-finding", "correct", "bug-add", "mute",
                            "unmute"])
    p.add_argument("title", nargs="?", default="")
    p.add_argument("manifest", nargs="?", default=None)
    p.add_argument("--phase", default=None)
    p.add_argument("--park", action="store_true", default=False,
                   help="add-phase: write the phase as a parked proposal instead, to "
                        "materialize on the development branch after this branch merges")
    p.add_argument("--skills", default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--files", action="append", default=None,
                   help=_list_help("repo-relative paths", "--files src/a.ts,src/b.ts",
                                   empties=False))
    # `add` only. The patterns for what this task PRODUCES, beside the list of
    # what it edits: a comma list like `--files`, and anchored at a literal
    # directory name so a plan cannot declare the whole tree and switch the plan
    # gate off through the door built to keep it on.
    p.add_argument("--outputs", default=None)
    p.add_argument("--risk", choices=["low", "med", "high"], default=None)
    p.add_argument("--blocked-by", dest="blocked_by", action="append", default=None,
                   help=_list_help("task, phase or decision ids",
                                   "--blocked-by P2.1,P3"))
    p.add_argument("--depends-on", dest="depends_on", action="append", default=None,
                   help=_list_help("task ids", "--depends-on P2.1,P2.2"))
    p.add_argument("--description", default="", help=_PROSE_HELP)
    # `retarget --rename "<new title>"`. Not `--title`: this verb's
    # POSITIONAL slot is called `title` and carries the phase id, so the flag
    # would shadow it. A phase title is not decoration - `_branch.slugify` turns
    # it into the branch's `{slug}` - which is why it is corrected through a verb
    # that can refuse rather than by hand.
    p.add_argument("--rename", default="", metavar="TITLE", help=_PROSE_HELP)
    p.add_argument("--tests-mode", dest="tests_mode",
                   choices=["tdd", "regression", "gate-only"], default=None)
    p.add_argument("--tests-add", dest="tests_add", action="append",
                   default=None)
    p.add_argument("--gate", action="append", default=None)
    # `retarget` AND `scope`, for the SAME reason: `--gate` REPLACES on both a
    # phase and a task, and the gap is that no VALUE of it spells "none" -
    # `--gate ""` writes a gate holding an empty command, which is a gate that
    # cannot run rather than the absence of one. `_phase_gate` documents the
    # empty gate as a designed state, and it is what a wrongly-guessed gate
    # needs.
    p.add_argument("--gate-clear", dest="gate_clear",
                   action="store_true")
    # `retarget` only (`VERB_FLAGS["retarget"]`). `--gate-drop` names entries to
    # REMOVE one at a time (`append`, so it can repeat); `--gate-set` REPLACES
    # the whole gate, which is `--gate`'s own operation under a name that takes
    # several values without the repeated-flag spelling `--gate` already uses
    # for the same thing. `nargs="*"` and not `"+"`: a caller who passes NO
    # value is answering "the empty gate", which is THIS verb's own refusal
    # ("an empty gate is --gate-clear, which says so") -- argparse's own usage
    # error for a starved `"+"` would answer instead, in argparse's words and
    # not this project's.
    p.add_argument("--gate-drop", dest="gate_drop", action="append",
                   default=None,
                   help="retarget: drop one testGate entry (repeatable)")
    p.add_argument("--gate-set", dest="gate_set", nargs="*", default=None,
                   help="retarget: replace testGate with these entries")
    p.add_argument("--project-dir", dest="project_dir", default=None)
    p.add_argument("--reason", default=None, help=_PROSE_HELP)
    p.add_argument("--verdict", default=None, choices=list(_mio.SIGNOFF_VERDICTS),
                   help="signoff: the sign-off verdict the phase's review reached")
    p.add_argument("--summary", default=None, metavar="TEXT", help=_PROSE_HELP)
    p.add_argument("--review-outcome", dest="review_outcome", default=None,
                   metavar="TEXT", help=_PROSE_HELP)
    p.add_argument("--branch", default=None, metavar="NAME",
                   help="signoff: the one branch a group of phases was built on")
    p.add_argument("--plan", action="store_true", default=False,
                   help="signoff: print what a group sign-off owes, write nothing")
    p.add_argument("--accept", action="append", default=None, metavar="SHA",
                   help="signoff: a commit on a group's branch no member records, "
                        "taken into its review; needs --reason")
    p.add_argument("--bind", action="store_true", default=False,
                   help="signoff: record a group's branch and baseRef, nothing else")
    p.add_argument("--no-evidence-reason", dest="no_evidence_reason", default=None,
                   metavar="TEXT", help=_PROSE_HELP)
    # add-phase only. `--id` rather than a positional: the title is the
    # positional every verb here already spends, and an OPTIONAL id read off
    # position two would be indistinguishable from the optional `manifest`.
    p.add_argument("--id", dest="phase_id", default=None)
    p.add_argument("--outcome", default=None, help=_PROSE_HELP)
    p.add_argument("--area", default=None)
    p.add_argument("--review-skill", dest="review_skill", default=None)
    # `done` only. The SHA of the commit the task's work landed in, which is what
    # `task.commit` has always been and what `_commit_trail` asks git about. Not
    # `--sha`: the field is `commit` on every surface that renders it, and a flag
    # spelled differently from the field it writes is one more translation for a
    # reader to keep straight.
    p.add_argument("--commit", default=None)
    # ...and the two halves of `task.outcome`, spelled with the schema's own field
    # names. `--outcome` was already taken by a PHASE's `desiredOutcome` on
    # `add-phase` and `retarget`, and reusing one flag for two different fields on
    # two different nouns is how a caller writes the right words into the wrong
    # place.
    p.add_argument("--descriptive", default=None, metavar="TEXT", help=_PROSE_HELP)
    p.add_argument("--technical", default=None, metavar="TEXT", help=_PROSE_HELP)
    # `verifiedBy`: the test names this task added, the field `reference/
    # orchestrator.md` step 4b fills beside the outcome. A comma list of names for
    # `--blocked-by`'s reason, and `--verified-by ""` empties it for the same one.
    p.add_argument("--verified-by", dest="verified_by", action="append",
                   default=None,
                   help=_list_help("test names", "--verified-by t_refund,t_retry"))
    # `done` only. The reviewer's own per-task verdict on whether the diff
    # does what `description` asked - `matches` / `diverges` / `cannot-tell`,
    # never a bare flag: an ENUM argparse grades, so this needs no place on
    # `PROSE_FLAGS` beside `--model` and `--tests-mode` for the same reason.
    # ABSENT IS ITS OWN ANSWER and is not this flag's default word: a close
    # that never passes `--intent` records no `intentCheck` at all, which is
    # what tells "no answer" apart from an explicit "matches".
    p.add_argument("--intent", choices=list(INTENT_ANSWERS), default=None)
    # ...and the reason beside `not-asked`, which the door requires for that word
    # alone: it is the one answer no reviewer gave.
    p.add_argument("--intent-basis", dest="intent_basis", default=None,
                   metavar="TEXT", help=_PROSE_HELP)
    # `done` only. The close whose answer was that nothing needed to change: no
    # commit, and `--reason` says why.
    p.add_argument("--no-change", dest="no_change", action="store_true",
                   default=False)
    # `done` only. Why this close stands over a newest gate verdict that refuses
    # it - `commit-task-work.py`'s flag for the same act; the close is journaled
    # with it, and refused without it.
    p.add_argument("--override-verdict", dest="override_verdict", default=None,
                   metavar="TEXT", help=_PROSE_HELP)
    # `move` only. The phase the task moves into - `--phase` stays `add`'s, where
    # it names the phase a new task is born in.
    p.add_argument("--to", default=None, metavar="PHASE")
    # `note` only. The note itself, appended to `notes[]` verbatim.
    p.add_argument("--text", default=None, metavar="TEXT", help=_PROSE_HELP)
    # `add` only. Build and validate the task in memory and write nothing.
    p.add_argument("--dry-run", dest="dry_run", action="store_true", default=False,
                   help="add: build the task and validate the plan with it, and "
                        "write nothing - no manifest, no journal row")
    # `add` only. A FAILED-FIRST fix task: point the new task's gate at the
    # suites a red sign-off run's own steps NAMED as failing, rather than at
    # the ordinary tests.add/files/phase-wide chain. The runId is opaque and
    # looked up through `_evidence_io.row_by_run`, never parsed -- see
    # `_failing_from_lookup`'s docstring for the three things the row must be.
    p.add_argument("--failing-from", dest="failing_from", default=None,
                   metavar="RUNID",
                   help="add: point the new task's gate at the suites this "
                        "run's own steps named as failing")
    # `couple`/`uncouple` only. `--test` names the entry both verbs act on;
    # `--sources`, `--basis-run`, `--basis-head` and `--phases` belong to
    # `couple` alone (`VERB_FLAGS["couple"]`), one per field of the
    # `meta.coupling` entry `_check_coupling` grades.
    p.add_argument("--test", default=None, metavar="PATH",
                   help="couple/uncouple: the test file the entry is about")
    p.add_argument("--sources", action="append", default=None,
                   help=_list_help("repo-relative source paths",
                                   "--sources src/a.ts,src/b.ts",
                                   empties=False))
    p.add_argument("--basis-run", dest="basis_run", default=None,
                   metavar="RUNID",
                   help="couple: the evidence row that taught this coupling")
    p.add_argument("--basis-head", dest="basis_head", default=None,
                   metavar="SHA",
                   help="couple: the HEAD the run examined")
    p.add_argument("--phases", action="append", default=None,
                   help=_list_help("phase ids", "--phases P2,P3"))
    # `couple` only, and never beside the learning flags above: the full run
    # whose runner named the already-coupled test as failing.
    p.add_argument("--caught", default=None, metavar="RUNID",
                   help="couple: a full run that named this coupled test as "
                        "failing; sets its lastCaught and changes nothing else")
    # `finding` only. A review finding's fields, spelled as the schema spells
    # them. `--severity` carries no `choices`: argparse would refuse on stderr
    # before `main` buffers anything, so `_finding_refusal` grades the word and a
    # `--json` caller still receives one object.
    p.add_argument("--severity", default=None,
                   help="finding: %s" % ("|".join(_phases.FINDING_SEVERITY),))
    p.add_argument("--file", default=None, metavar="PATH",
                   help="finding: the repository-relative path, optionally "
                        "path:lines")
    p.add_argument("--issue", default=None, metavar="TEXT", help=_PROSE_HELP)
    p.add_argument("--resolution", default=None, metavar="TEXT", help=_PROSE_HELP)
    # ...or the whole batch a review returned: a JSON list of those four fields,
    # read off a file or `-` (stdin), written under ONE lock in ONE write.
    p.add_argument("--findings-file", dest="findings_file", default=None,
                   metavar="PATH",
                   help="finding: a JSON list of {severity, file, issue, "
                        "resolution}, or - for stdin; recorded in one write")
    # `resolve-finding` only. The task whose commit settles the finding.
    p.add_argument("--fix-task", dest="fix_task", default=None, metavar="TASK",
                   help="resolve-finding: the task whose commit settles it")
    # `bug-add` only. The three sentences of a bug report beside its
    # `--description`, one flag per field and spelled as the field. The title
    # stays the POSITIONAL, for `--rename`'s reason above: a `--title` flag
    # would shadow the slot every verb here already names `title`.
    p.add_argument("--repro", default=None, metavar="TEXT", help=_PROSE_HELP)
    p.add_argument("--expected", default=None, metavar="TEXT", help=_PROSE_HELP)
    p.add_argument("--actual", default=None, metavar="TEXT", help=_PROSE_HELP)
    # `mute` only. The `meta.muted` fields `--test` and `--reason` do not
    # already carry: who answers for lifting it, the last UTC day it holds,
    # and the bug tracking the failure it hides.
    p.add_argument("--owner", default=None, metavar="NAME",
                   help="mute: who answers for lifting the mute")
    p.add_argument("--until", default=None, metavar="YYYY-MM-DD",
                   help="mute: the last UTC calendar day the mute holds, "
                        "inclusive")
    p.add_argument("--bug", default=None, metavar="BUGID",
                   help="mute: the bugs[] id tracking the failure it hides")
    p.add_argument("--takeover", action="store_true")
    p.add_argument("--json", action="store_true", dest="as_json")
    return p


def option_dests(parser=None):
    """{dest: "--flag"} for every OPTION the parser declares.

    Off `_actions`, which is `_help.parser_choices`' reason too: argparse is the
    thing the command runs on, so it is the only answer that cannot be a second
    opinion. Positionals are absent by construction -- `command`, `title` and
    `manifest` are read by every verb's door and are not flags anybody can
    misplace -- and so is `--help`, which argparse answers itself.
    """
    out = {}
    for action in getattr(parser or build_parser(), "_actions", ()):
        if not action.option_strings or action.dest in ("help", "==SUPPRESS=="):
            continue
        longest = [f for f in action.option_strings if f.startswith("--")]
        out[action.dest] = longest[0] if longest else action.option_strings[0]
    return out


def supplied_flags(argv):
    """The dests actually PRESENT in `argv`, or None if argparse could not say.

    ASKED OF ARGPARSE AND NOT OF THE NAMESPACE, because a namespace cannot tell
    `--description ""` from a `--description` nobody passed: both hold the
    default. A second parser whose every option default is a sentinel can, and
    it costs one parse of an argv argparse has already accepted. Abbreviations
    (`--desc`) and the `--flag=value` spelling come out right for free, which a
    hand scan of `argv` would each get wrong separately.

    None RATHER THAN AN EMPTY SET on a parse the probe rejects: empty would mean
    "no flags were passed", which is the answer that lets every misplaced flag
    through. The caller refuses instead.

    THAT BRANCH IS DEFENSIVE AND `main` CANNOT REACH IT, said here because a
    reader owes no time to working out why there is no case for it there.
    Measured: the probe is the same parser over an argv the real parse has
    already accepted, so the only argv it rejects (`--gate --json`, where a
    flag's value looks like a flag) is one `main`'s own parse
    (`parse_intermixed_args`) rejects first,
    and `main` has returned E_USAGE before this is called. It is still not
    dropped -- a `None` the caller silently read as "no flags" is the whole
    defect this returns None to avoid -- and `vf9` drives it by calling this
    function directly, which is the only door it has.

    THE SENTINEL IS A FRESH LIST PER FLAG, AND ITS IDENTITY IS THE ANSWER. Two
    of argparse's own mechanics decide that. An `append` action APPENDS to its
    default, so a sentinel it cannot append to raises inside argparse; and a
    STRING default is passed through `type` on its way into the namespace, so a
    sentinel spelled as text would be graded against `choices` on the flags
    that declare them. A list is safe on both counts, argparse copies it before
    appending, and it sets an untouched default by reference -- so "the
    namespace still holds THIS object" is exactly "the flag was not passed".
    """
    probe = build_parser()
    marks = {}
    for action in getattr(probe, "_actions", ()):
        if action.option_strings:
            marks[action.dest] = []
            action.default = marks[action.dest]
    try:
        parsed = probe.parse_intermixed_args(argv)   # `main`'s parse, exactly
    except SystemExit:
        return None
    return set(dest for dest in option_dests(probe)
               if getattr(parsed, dest, None) is not marks.get(dest))


def readers_of(dest):
    """The verbs that read `dest`, in the order `VERB_FLAGS` declares them."""
    if dest in UNIVERSAL_FLAGS:
        return sorted(VERB_FLAGS)
    return [verb for verb in sorted(VERB_FLAGS) if dest in VERB_FLAGS[verb]]


def misplaced_flag_refusal(verb, supplied, flags=None):
    """The refusal for flags `verb` does not read, or None when there are none.

    EVERY MISPLACED FLAG, not the first one. `shell_eaten_gap` reports one hole
    and stops because a list there invites the reader to grade a severity that
    does not exist; here each flag names a DIFFERENT verb as the one that reads
    it, so a list is one round trip instead of one per flag.

    A FLAG NO VERB READS IS SAID DIFFERENTLY, and loudly. It is not a mistake in
    the call -- the caller cannot have got it right -- so the sentence points at
    the table rather than at them. What stops that line being reachable is the
    `vf` group in `plugins/audit/tests/test_audit_task.py`, which derives each
    verb's reads off this file's own call graph and demands equality with
    `VERB_FLAGS` -- and the line exists anyway, because a check with no output
    for its own broken state is how a table stops meaning anything.

    NAMED AS WHAT IT IS. This paragraph and the message below both used to cite
    a `verb_flag_drift()` that was never written -- a comment naming a function,
    read as a promise that something checks this, with nothing behind it.
    """
    flags = flags if flags is not None else option_dests()
    known = set(VERB_FLAGS.get(verb) or ()) | set(UNIVERSAL_FLAGS)
    stray = sorted(d for d in (supplied or ()) if d not in known)
    if not stray:
        return None
    lines = ["[audit-task] `%s` does not read %s -- one parser serves every "
             "verb, so argparse accepted %s and the verb's writer would never "
             "have looked at %s. Nothing was written."
             % (verb, ", ".join(flags.get(d, d) for d in stray),
                "them" if len(stray) > 1 else "it",
                "them" if len(stray) > 1 else "it")]
    for dest in stray:
        who = [v for v in readers_of(dest) if v != verb]
        if who:
            lines.append("  %s is read by: %s"
                         % (flags.get(dest, dest),
                            ", ".join("`%s`" % v for v in who)))
        else:
            lines.append("  %s is read by NO verb on this parser, which is a "
                         "hole in `VERB_FLAGS` rather than a mistake in your "
                         "call -- please report it" % (flags.get(dest, dest),))
    return "\n".join(lines)


def json_refusal(code, lines):
    """`{ok: false, refused, findings}` for a refusal whose text went to `lines`.

    A `--json` caller parses stdout, and a refusal printed as prose there is a
    `json.loads` error standing in for the answer - so every refusal, from any
    door of any verb, reaches that caller as one object. `refused` is the
    message; `findings` are its `FINDING:` lines, apart, because they are the
    validator's own words and a consumer acting on them should not parse prose.
    """
    text = [ln for ln in lines if not ln.startswith("FINDING: ")]
    return json.dumps({"ok": False, "exit": code,
                       "refused": "\n".join(text).strip(),
                       "findings": [ln[len("FINDING: "):] for ln in lines
                                    if ln.startswith("FINDING: ")]},
                      indent=2, sort_keys=True)


def main(argv, out=print):
    p = build_parser()
    # INTERMIXED, BECAUSE THE DOCUMENTED ORDER PUTS THE MANIFEST LAST. On some
    # interpreters this project still supports (3.9 measured), plain
    # `parse_args` stops filling positionals at the first option, so
    # `bug-add "<title>" --severity low --description d <manifest>` is
    # "unrecognized arguments" there.
    # The parser has no REMAINDER, no subparsers and no positional inside a
    # mutually exclusive group, which is all this call rules out. `supplied_flags`
    # makes the same call, so the flag census reads the same parse.
    try:
        args = p.parse_intermixed_args(argv)
    except SystemExit as exc:
        return E_USAGE if exc.code else 0
    if not args.as_json:
        return _dispatch(args, argv, out)
    # UNDER `--json` THE OUTPUT IS BUFFERED, so a refusal can be handed over as
    # data: a verb that answers prints its one object and it is passed through
    # unchanged; one that refuses printed prose, which becomes `json_refusal`.
    lines = []
    code = _dispatch(args, argv, lines.append)
    if code != 0 and not _is_one_object(lines):
        out(json_refusal(code, "\n".join(str(x) for x in lines).splitlines()))
        return code
    for line in lines:
        out(line)
    return code


def _is_one_object(lines):
    """Is the buffered output exactly one JSON object?"""
    try:
        return isinstance(json.loads("\n".join(str(x) for x in lines)), dict)
    except ValueError:
        return False


def _dispatch(args, argv, out):
    """The checks every call gets, then the verb's door."""
    # This check comes FIRST because it is the cheapest true thing that can be
    # said about this call: a flag the verb does not read is a usage error whatever
    # its value, and asking about the VALUE of a flag nothing will read would be
    # grading input that has no reader.
    supplied = supplied_flags(argv)
    if supplied is None:
        # A parse argparse has already accepted must parse again. Saying so beats
        # continuing with an empty census, which reads as "no flags were passed"
        # and lets every misplaced flag through.
        out("[audit-task] the flag census could not re-read this invocation, so "
            "which verb reads which flag cannot be checked -- refusing rather "
            "than writing on an unchecked call")
        return E_USAGE
    misplaced = misplaced_flag_refusal(args.command, supplied)
    if misplaced:
        out(misplaced)
        return E_USAGE
    # THE PROSE-GAP CHECK, WIDENED TO ITS WHOLE CLASS: every flag carrying the
    # operator's own prose, for the verbs that read it. It used to run for every verb on the
    # argument that a caller passing `--description` to `cancel` should not be told
    # a different story about the same flag by a different verb -- and the story
    # they are told now is the true one, from the check above, which is that the
    # verb never reads it.
    stop = resolve_briefs(args, out)
    if stop is None:
        stop = resolve_verbatim_values(args, out)
    if stop is not None:
        return stop
    # THE DISPATCH `VERB_FLAGS` IS GRADED AGAINST. `vf` in the suite reads this
    # map out of the AST and walks the call graph from each door, so the table and
    # the doors cannot describe different verbs.
    doors = {"add": cmd_add, "add-phase": cmd_phase_add,
             "cancel": cmd_cancel, "scope": cmd_scope,
             "retarget": cmd_retarget, "start": cmd_start,
             "done": cmd_done, "seed": cmd_seed, "next-id": cmd_next_id,
             "signoff": cmd_signoff, "settle": cmd_settle,
             "reopen": cmd_reopen, "move": cmd_move, "block": cmd_block,
             "note": cmd_note, "couple": cmd_couple, "uncouple": cmd_uncouple,
             "finding": cmd_finding, "resolve-finding": cmd_resolve_finding,
             "correct": cmd_correct, "bug-add": cmd_bug_add,
             "mute": cmd_mute, "unmute": cmd_unmute}
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
