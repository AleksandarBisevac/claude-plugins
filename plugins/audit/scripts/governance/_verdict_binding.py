#!/usr/bin/env python3
"""
Does a recorded gate verdict bind the declared work as it stands now - ONE answer.

WHY THIS IS A MODULE AND NOT A FUNCTION IN EACH CALLER. Two writers stand on a
recorded verdict: `commit-task-work.py` commits a task's work only under a green
run of the gate that measures it, and `audit-task.py signoff` records a `passed`
sign-off only under a green run of the phase's gate. They ask the same question
of the same ledger, and a second implementation of it had fewer arms than the
first: it graded a repeated verdict by the repeat's own empty stamp and refused
it, it compared a digest the recorder had taken with its own writes left out
against one taken with them in, and it accepted an `empty-gate` row under a gate
that had since gained entries. Entry points cannot import one another, so the
rule lives here, one layer above the two modules it reads - `_evidence_io` for the
ledger and `_tree_stamp` for the digest, which are peers and cannot hold it.

THE RULE, arm by arm, each with its sentence:

  * The subject's rows are the ones carrying its ids (`_evidence_io._same_subject`),
    and the NEWEST by `ts` is the verdict - never the plan's pointer, which is a
    cache that a refused write leaves behind the record.
  * A ledger line that will not parse and could be the subject's row blocks: the
    verdict is then not established. A line that names another task is passed
    over and said.
  * No gate entries now: bound to no verdict (`no-gate`), unless a red recorded
    under entries after the last green is still unanswered.
  * Entries now and an `empty-gate` newest row, or a row measured under other
    entries, other resolved commands or another gate source: a different gate.
  * A newest row that is not `passed`: refused, naming it.
  * A repeated verdict is graded against the run that MEASURED it, through
    `reusedFrom`; a repeat whose source is gone from the ledger is refused.
  * The declared work's digest, with the recorder's own paths left out on both
    sides, must match the row's - a changed LIST is told apart from changed
    CONTENT, and a question the tree cannot answer is said as that.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__verdict_binding.py`.
"""

import os
import re
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

import _evidence_io  # noqa: E402  (the ledger, the subject rule, the recorder's own paths)
import _journal_io  # noqa: E402  (the ledger's config and its line parser)
import _tree_stamp  # noqa: E402  (the declared-work digest a gate row records)

# The one status a verdict binds as.
VERDICT_PASSED = "passed"

# The status `run-test-gate.py --record` writes for a gate that declares no
# command. It is the recorded answer for a gate that is empty NOW, and binds
# nothing under a gate that has entries.
VERDICT_EMPTY_GATE = "empty-gate"

# The command that shows an unreadable ledger line for what it is.
VERIFY_COMMAND = "audit-journal.py verify"

# A `taskId` value spelled out WHOLE on a line - its closing quote included - is
# proof of whose row the line was even when the rest of it will not parse.
_TASK_ID_VALUE = re.compile(r'"taskId"\s*:\s*"((?:[^"\\]|\\.)*)"')


def label_of(ids):
    """The subject a sentence names: the task when there is one, else the phase."""
    return str((ids or {}).get("taskId") or (ids or {}).get("phaseId"))


def newest(rows):
    """The newest row by `ts`, a later row winning a tie, or None.

    BY `ts` AND NOT BY FILE ORDER, `_evidence_io.latest_by_subject`'s rule: rows
    land in one file per writer per month, so the concatenation of the ledger is
    in no meaningful order. A tie goes to the row read later, which within one
    writer's file is the row appended later. By the MOMENT `ts` names, never its
    spelling - `_evidence_io.newest_row` is that one comparison.
    """
    return _evidence_io.newest_row(rows)


# The suffix `unreadable_lines` gives a FILE it lost whole, which is a
# different repair from a line that will not parse - `blocking_sentence` says
# each in its own words.
UNREADABLE_MARK = " (unreadable)"


def blocking_sentence(who, blocking):
    """The refusal for `unreadable_lines`' blocking entries: files lost whole
    and lines that will not parse, each with the repair that fits it."""
    lost = [b for b in blocking if b.endswith(UNREADABLE_MARK)]
    lines = [b for b in blocking if not b.endswith(UNREADABLE_MARK)]
    parts = []
    if lost:
        parts.append(
            "the evidence ledger holds file(s) that could not be read at all - "
            "%s - and a file lost whole could hold %s's newest verdict, so the "
            "verdict it stands under is not established. `%s` names why for "
            "each: the first byte that is not UTF-8 text and its offset in "
            "bytes from the start of the file, or why it would not open. For a "
            "byte, restore the file from its committed copy"
            % (", ".join(b[:-len(UNREADABLE_MARK)] for b in lost), who,
               VERIFY_COMMAND))
    if lines:
        parts.append(
            "the evidence ledger holds line(s) that will not parse and could be "
            "%s's newest verdict - %s - so the verdict it stands under is not "
            "established. `%s` shows each; repair or remove it"
            % (who, ", ".join(lines), VERIFY_COMMAND))
    return "; ".join(parts)


def unreadable_lines(project, ids, config=None):
    """`(blocking, excused)` - the ledger lines that will not parse, as
    `"<file>:<line>"`, split by whether they could be the subject's row.

    A LINE IS EXCUSED ONLY WHEN IT PROVES WHOSE IT IS: a whole `taskId` value
    naming another task - or, for a PHASE subject, naming any task, because a
    phase's own row carries no `taskId` at all. Everything else might be the
    subject's newest verdict - a torn line can end before its `taskId` - so it
    blocks.
    """
    config = _journal_io.load_config(project) if config is None else config
    task_id = (ids or {}).get("taskId")
    blocking, excused = [], []
    for path in _evidence_io.ledger_files(project, config):
        where = _journal_io.repo_relative_or_token(project, path)
        # The ledger's one decode: a file `read_rows` loses whole (it will not
        # open, or a byte in it is not UTF-8) could hold the subject's newest
        # verdict, so it blocks here rather than going silently missing there.
        try:
            text = _evidence_io.ledger_text(path)
        except Exception:
            blocking.append("%s%s" % (where, UNREADABLE_MARK))
            continue
        raw = text.splitlines()
        parsed, torn = _journal_io.rows_from_text(text)
        numbers = [r.get("_line") for r in parsed if r.get("_unparseable")]
        if torn:
            numbers.append(len(raw))
        for number in numbers:
            line = raw[number - 1] if number and number <= len(raw) else ""
            found = _TASK_ID_VALUE.search(line)
            label = "%s:%s" % (where, number)
            if found and (task_id is None or found.group(1) != str(task_id)):
                excused.append(label)
            else:
                blocking.append(label)
    return blocking, excused


def gate_mismatch(measured, entries, source, build=None):
    """The sentence a verdict measured under a different gate earns, or None.

    THE ROW'S STEPS ARE ITS GATE: `run-test-gate` runs every declared entry in
    order and records one step per entry under the entry's name, so the names in
    order are the declaration it was measured under. A row that dropped steps for
    length is compared on the steps it kept AND on the count it dropped, so a
    gate widened past the kept steps is still a different gate. `gateSource` is
    compared when the row has one - the same names measured as a task gate and
    as its phase's fallback are different claims - and so is `gateDigest`, the
    entries beside what `meta.buildCommands` resolves each to: a name that held
    still while its command changed is a different gate too.
    """
    recorded = [str(s.get("name")) for s in (measured.get("steps") or [])
                if isinstance(s, dict)]
    now = list(entries)
    dropped = measured.get("stepsDropped")
    dropped = dropped if isinstance(dropped, int) and dropped > 0 else 0
    same_steps = (recorded == now[:len(recorded)]
                  and len(recorded) + dropped == len(now))
    was_source = measured.get("gateSource")
    was_digest = measured.get(_evidence_io.GATE_DIGEST_KEY)
    same_digest = (was_digest is None
                   or was_digest == _evidence_io.gate_digest(entries, build))
    if same_steps and same_digest and (was_source is None
                                       or was_source == source):
        return None
    if same_steps and not same_digest:
        return ("it was measured under the gate [%s] as `meta.buildCommands` "
                "resolved it then, and the same entries resolve to different "
                "commands now - a verdict about a different gate is not this "
                "gate's verdict" % (", ".join(recorded),))
    return ("it was measured under the gate [%s]%s, and the %s declares "
            "[%s] (%s gate) now - a verdict about a different gate is not this "
            "gate's verdict"
            % (", ".join(recorded),
               " (%s gate)" % (was_source,) if was_source else "",
               "task" if source == "task" else "phase",
               ", ".join(entries), source))


def red_after_green(rows):
    """The newest row measured under entries that is not `passed`, recorded
    after the last `passed` one - or None when every such red was retired.

    `rows` are one subject's rows; an `empty-gate` row is not measured under
    entries and retires nothing. With no green at all, every red counts.
    """
    ordered = _evidence_io.oldest_first(rows)
    greens = [i for i, r in enumerate(ordered)
              if r.get("status") == VERDICT_PASSED]
    tail = ordered[greens[-1] + 1:] if greens else ordered
    reds = [r for r in tail
            if r.get("status") not in (VERDICT_PASSED, VERDICT_EMPTY_GATE)]
    return reds[-1] if reds else None


def binding(project, ids, entries, source, owns, manifest_path, record,
            no_gate, config=None, build=None):
    """`{"state", "sentence", "row", "measured", "notes"}` - whether the subject's
    newest recorded verdict binds the declared work `owns` as it stands now.

    `ids` is `{"taskId", "phaseId"}` for a task, `{"phaseId"}` for a phase;
    `entries`/`source` are `_manifest_io.gate_entries`' answer; `record` is the
    sentence naming the run that would supply a verdict; `no_gate` is the
    caller's own sentence for a subject no gate measures. `state` is `"bound"`,
    `"no-gate"` or `"refused"`; `row` is the newest row, so an override can name
    it; `measured` is the row that measured the tree - `row` itself, or the run a
    repeated verdict repeats; `notes` are unparseable ledger lines passed over.
    """
    config = _journal_io.load_config(project) if config is None else config
    who = label_of(ids)
    blocking, excused = unreadable_lines(project, ids, config)
    notes = []
    if excused:
        notes.append("%d evidence ledger line(s) will not parse and each names "
                     "another task, so they were passed over: %s (`%s` shows "
                     "them)" % (len(excused), _output.some_of(excused),
                                VERIFY_COMMAND))
    out = {"state": "refused", "row": None, "measured": None, "notes": notes}
    if blocking:
        out["sentence"] = blocking_sentence(who, blocking)
        return out
    ledger = _evidence_io.read_rows(project, config)
    rows = [r for r in ledger["rows"]
            if isinstance(r, dict) and _evidence_io._same_subject(r, ids)]
    # A SUBJECT ROW WHOSE ts NAMES NO MOMENT BLOCKS, as an unparseable line
    # does: it cannot be placed before or after any other row, so it could be
    # the newest verdict - and ordering it first would let a green retire it.
    undated = [r for r in rows
               if _evidence_io.stamp_moment(r.get("ts")) is None]
    if undated:
        out["sentence"] = (
            "the evidence ledger holds %s row(s) whose ts names no moment - %s "
            "- so none of them can be placed before or after the others and "
            "any could be %s's newest verdict; the verdict it stands under is "
            "not established. `%s` shows the ledger; repair the ts or remove "
            "the row on purpose" % (
                who, ", ".join("run %s at %r" % (r.get("runId"), r.get("ts"))
                               for r in undated), who, VERIFY_COMMAND))
        return out
    last = newest(rows)
    out["row"] = last
    run = ("run %s at %s" % (last.get("runId"), last.get("ts")) if last else "")
    if not entries:
        red = red_after_green(rows)
        if red is not None:
            out["row"] = red
            out["sentence"] = (
                "%s declares no gate now, and a red was recorded under its gate "
                "after the last green - `%s`, run %s at %s. Neither emptying the "
                "gate nor the `%s` row recording it retires that red: record a "
                "green on a gate" % (who, red.get("status"), red.get("runId"),
                                     red.get("ts"), VERDICT_EMPTY_GATE))
            return out
        out["state"] = "no-gate"
        out["measured"] = last
        out["sentence"] = ("%s (the newest verdict recorded for it is %s, `%s`)"
                           % (no_gate, run, last.get("status"))
                           if last is not None else no_gate)
        return out
    if last is None:
        out["sentence"] = ("no gate verdict is recorded for %s, and its gate "
                           "declares entries - %s" % (who, record))
        return out
    if last.get("status") == VERDICT_EMPTY_GATE:
        out["sentence"] = ("%s's newest verdict is `%s` (%s), but %s; %s"
                           % (who, VERDICT_EMPTY_GATE, run,
                              gate_mismatch(last, entries, source, build), record))
        return out
    if last.get("status") != VERDICT_PASSED:
        out["sentence"] = ("%s's newest gate verdict is `%s` (%s), and it binds "
                           "only as `%s` - the gate is what decides the work is "
                           "done. Fix the work and %s"
                           % (who, last.get("status"), run, VERDICT_PASSED, record))
        return out
    measured = last
    if last.get(_evidence_io.VERDICT_SOURCE) == _evidence_io.REUSED:
        origin = (last.get("reusedFrom") or {}).get("runId")
        # The newest row carrying that runId by moment, never the last in
        # ledger order: two worktrees' files concatenate in no order at all.
        measured = (_evidence_io.row_by_run(ledger["rows"], origin)
                    if origin else None)
        if measured is None:
            out["sentence"] = ("%s's newest verdict (%s) repeats run %s, which is "
                               "not in the ledger, so the tree it was measured on "
                               "is not established - %s" % (who, run, origin,
                                                            record))
            return out
    out["measured"] = measured
    mismatch = gate_mismatch(measured, entries, source, build)
    if mismatch:
        out["sentence"] = ("%s's newest verdict is `%s` (%s), but %s; %s"
                           % (who, VERDICT_PASSED, run, mismatch, record))
        return out
    return dict(out, **digest_binding(project, manifest_path, who, owns, config,
                                      measured, run, record))


def digest_binding(project, manifest_path, who, owns, config, measured, run,
                   record):
    """`{"state", "sentence"}` - the declared-work half of `binding`: the measured
    row's digest against the declared files now.

    The record paths are left out on this side exactly as the recorder left them
    out (`_evidence_io.recorded_paths`), which is what lets a subject declare its
    own manifest file and still be graded on the rest of its work.
    """
    excluded, _dropped = _evidence_io.recorded_paths(project, manifest_path, config)
    owns = list(owns or [])
    state = measured.get("testedState") or {}
    was = state.get("scopeDigest")
    now, basis = _tree_stamp.scope_digest(project, owns, excluded=excluded)
    list_now = _tree_stamp.scope_list_digest(owns, excluded=excluded)
    field = _tree_stamp.field_state("scopeDigest", was, now, list_now is not None)
    if field == _tree_stamp.MOVED:
        list_was = state.get("scopeListDigest")
        if list_was is not None and list_was != list_now:
            what = ("the declared file LIST has changed since it was measured - a "
                    "scope change is a change to what the gate covered, so the "
                    "gate owes a new run on the new scope")
        elif list_was is not None:
            what = "the declared files' CONTENTS have changed since it was measured"
        else:
            what = ("the declared files, or the list of them, have changed since "
                    "it was measured (the row predates the list digest, so which "
                    "is not recorded)")
        return {"state": "refused",
                "sentence": ("%s's newest verdict is `%s` (%s), but %s - "
                             "scopeDigest was %s and is %s now (%s); %s"
                             % (who, VERDICT_PASSED, run, what, was, now, basis,
                                record))}
    if field == _tree_stamp.UNANSWERABLE:
        return {"state": "refused",
                "sentence": ("%s's newest verdict is `%s` (%s), and whether it "
                             "was measured on the declared files as they stand is "
                             "not established - scopeDigest was %s and is %s now "
                             "(%s); %s" % (who, VERDICT_PASSED, run, was, now,
                                           basis, record))}
    if field == _tree_stamp.NOT_DECLARED:
        return {"state": "bound",
                "sentence": ("bound to %s (`%s`); %s declares no files the "
                             "recorder does not write itself, so the verdict word "
                             "is bound and no declared-work digest could be"
                             % (run, VERDICT_PASSED, who))}
    return {"state": "bound",
            "sentence": ("bound to %s (`%s`) - measured under the gate declared "
                         "now, and the declared-work digest it recorded matches "
                         "the declared files now. %s"
                         % (run, VERDICT_PASSED, _tree_stamp.SCOPE_LIMIT))}


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through: it deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_verdict_binding.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__verdict_binding.py - run that file "
              "instead.")
        sys.exit(0)
    print(__doc__.strip())
