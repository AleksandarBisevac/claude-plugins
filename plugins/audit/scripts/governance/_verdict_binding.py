#!/usr/bin/env python3
"""
Does a recorded gate verdict bind the declared work as it stands now - ONE answer.

WHY THIS IS A MODULE AND NOT A FUNCTION IN EACH CALLER. Every writer below
stands on a recorded verdict: `commit-task-work.py` commits a task's work only under a green
run of the gate that measures it, `audit-task.py signoff` records a `passed`
sign-off only under a green run of the phase's gate, and `audit-task.py done` and
`close-phase.py` close a task or land a phase only while its newest recorded
verdict still holds (`close_refusal`). They ask the same question of the same
ledger, and a second implementation of it had fewer arms than the first: it
graded a repeated verdict by the repeat's own empty stamp and refused
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

Every refusal carries the `arm` that produced it, so a caller asking a narrower
question than a commit - a CLOSE - reads which refusal it was rather than
re-parsing the sentence.

A CLOSE NEVER VOUCHES FOR A VERDICT THAT NO LONGER HOLDS. A close refuses on
every arm of `binding` that refuses (`CLOSE_REFUSING_ARMS`) except the two where
there is no measurement to vouch for at all - no run recorded under a gate that
has entries, and an `empty-gate` row under one - because those are what
sign-off's `--no-evidence-reason` and a gate declared empty already answer, and
refusing them would refuse every phase signed off that way. The one way past a
refusal is the caller's `OVERRIDE_FLAG` with a reason, journaled as
`ACTION_CLOSE_OVERRIDDEN`.

THE DIGEST READS THE DECLARED FILES' CONTENT AND NOTHING WIDER. Whether an
undeclared file's bytes moved is the stamp's question (`_tree_stamp`'s
`content` field), and the gate row carries no content digest of undeclared
paths to compare one against: `tested_state` records the three older fields
only. A task commit stages its declared files alone, so an undeclared file is
not part of the work the verdict is bound to.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__verdict_binding.py`.
"""

import json
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
import _manifest_io as _mio  # noqa: E402  (which gate measures a task or a phase)
import _tree_stamp  # noqa: E402  (the declared-work digest a gate row records)

# The one status a verdict binds as.
VERDICT_PASSED = "passed"

# The status `run-test-gate.py --record` writes for a gate that declares no
# command. It is the recorded answer for a gate that is empty NOW, and binds
# nothing under a gate that has entries.
VERDICT_EMPTY_GATE = "empty-gate"

# The command that shows an unreadable ledger line for what it is.
VERIFY_COMMAND = "audit-journal.py verify"

# The arms of `binding`'s refusals, one word each, each with why a CLOSE over
# it would vouch for a verdict that does not hold.
# a ledger file or line that could be the newest verdict cannot be read - it may be a red
ARM_UNREADABLE = "unreadable"
# a subject row names no moment, so it may be newer than every green
ARM_UNDATED = "undated"
# a red after the last green is unanswered, and emptying the gate does not answer it
ARM_RED_AFTER_GREEN = "red-after-green"
# the newest verdict says the work failed
ARM_RED = "red"
# the newest verdict repeats a run the ledger no longer holds, so what it measured is unknown
ARM_REPEAT_GONE = "repeat-gone"
# the green was measured under a different gate from the one declared now
ARM_GATE_CHANGED = "gate-changed"
# the declared files, or their list, changed after the green measured them
ARM_DIGEST_MOVED = "digest-moved"
# whether the green measured the declared files as they stand cannot be answered
ARM_DIGEST_UNANSWERABLE = "digest-unanswerable"
# NOT refusing a close: no run is recorded under a gate that has entries, or the
# newest row is an `empty-gate` answer under one - there is no measurement to
# vouch for, and sign-off's `--no-evidence-reason` and a gate declared empty
# are the records that answer that.
ARM_NO_VERDICT = "no-verdict"
ARM_EMPTY_GATE = "empty-gate"
CLOSE_REFUSING_ARMS = (ARM_UNREADABLE, ARM_UNDATED, ARM_RED_AFTER_GREEN, ARM_RED,
                       ARM_REPEAT_GONE, ARM_GATE_CHANGED, ARM_DIGEST_MOVED,
                       ARM_DIGEST_UNANSWERABLE)

# The journal action a close made over its verdict's refusal writes - `done`
# and `close-phase` alike, so one name finds every such close in the trail.
ACTION_CLOSE_OVERRIDDEN = "audit.verdict.close-overridden"

# The flag both closing verbs take for it - `commit-task-work.py`'s spelling of
# the same act, going over a verdict that refused, with the reason recorded.
OVERRIDE_FLAG = "--override-verdict"

# A `taskId` value spelled out WHOLE on a line - its closing quote included - is
# proof of whose row the line was even when the rest of it will not parse.
_TASK_ID_VALUE = re.compile(r'"taskId"\s*:\s*"((?:[^"\\]|\\.)*)"')


# --- the binding: does the newest verdict bind the work now -------------------
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


def ledger_texts(project, config=None, directory=None):
    """`[(label, text or None)]` - every ledger file under `project`, decoded
    by the ledger's one strict decode; None where it would not open or decode.

    `directory` reads another directory of the same shape - the journal's - by
    the same rule. A file lost whole could hold the subject's newest verdict,
    so it travels as None and blocks rather than going silently missing.
    """
    config = _journal_io.load_config(project) if config is None else config
    if directory is None:
        paths = _evidence_io.ledger_files(project, config)
    else:
        try:
            paths = [os.path.join(directory, n) for n in sorted(os.listdir(directory))
                     if n.endswith(".jsonl")]
        except Exception:
            paths = []
    out = []
    for path in paths:
        try:
            text = _evidence_io.ledger_text(path)
        except Exception:
            text = None
        out.append((_journal_io.repo_relative_or_token(project, path), text))
    return out


def _row_identity(row):
    """A row's identity for a union of two copies of one ledger: its recorded
    fields, the parser's own bookkeeping left out."""
    return json.dumps(dict((k, v) for k, v in row.items()
                           if not str(k).startswith("_")), sort_keys=True)


def rows_of(texts):
    """Every parsed row in `texts`, once each by `_row_identity` - the union a
    reader of two copies of one ledger needs, so a row both copies hold is one
    row and a row only one of them holds is still read."""
    seen, rows = set(), []
    for _label, text in texts:
        if text is None:
            continue
        for row in _journal_io.rows_from_text(text)[0]:
            if row.get("_unparseable") or not isinstance(row, dict):
                continue
            key = _row_identity(row)
            if key not in seen:
                seen.add(key)
                rows.append(row)
    return rows


def unreadable_lines(project, ids, config=None, texts=None):
    """`(blocking, excused)` - the ledger lines that will not parse, as
    `"<file>:<line>"`, split by whether they could be the subject's row.

    `texts` is the ledger as `ledger_texts` reads it, or another reading of the
    same shape (a branch tip's, a worktree's); None reads the project's.

    A LINE IS EXCUSED ONLY WHEN IT PROVES WHOSE IT IS: a whole `taskId` value
    naming another task - or, for a PHASE subject, naming any task, because a
    phase's own row carries no `taskId` at all. Everything else might be the
    subject's newest verdict - a torn line can end before its `taskId` - so it
    blocks.
    """
    texts = ledger_texts(project, config) if texts is None else texts
    task_id = (ids or {}).get("taskId")
    blocking, excused = [], []
    for where, text in texts:
        if text is None:
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
            no_gate, config=None, build=None, texts=None, digest_root=None):
    """`{"state", "sentence", "row", "measured", "notes"}` - whether the subject's
    newest recorded verdict binds the declared work `owns` as it stands now.

    `texts` is the ledger to read (`ledger_texts`' shape) when it is not the
    one under `project` - a landing reads the branch it would merge - and
    `digest_root` the tree whose declared files the digest is taken over when
    that is not `project` either.

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
    texts = ledger_texts(project, config) if texts is None else texts
    blocking, excused = unreadable_lines(project, ids, config, texts=texts)
    notes = []
    if excused:
        notes.append("%d evidence ledger line(s) will not parse and each names "
                     "another task, so they were passed over: %s (`%s` shows "
                     "them)" % (len(excused), _output.some_of(excused),
                                VERIFY_COMMAND))
    out = {"state": "refused", "row": None, "measured": None, "notes": notes,
           "arm": None}
    if blocking:
        out["sentence"] = blocking_sentence(who, blocking)
        out["arm"] = ARM_UNREADABLE
        return out
    ledger = {"rows": rows_of(texts)}
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
        out["arm"] = ARM_UNDATED
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
            out["arm"] = ARM_RED_AFTER_GREEN
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
        out["arm"] = ARM_NO_VERDICT
        return out
    if last.get("status") == VERDICT_EMPTY_GATE:
        out["sentence"] = ("%s's newest verdict is `%s` (%s), but %s; %s"
                           % (who, VERDICT_EMPTY_GATE, run,
                              gate_mismatch(last, entries, source, build), record))
        out["arm"] = ARM_EMPTY_GATE
        return out
    if last.get("status") != VERDICT_PASSED:
        out["sentence"] = ("%s's newest gate verdict is `%s` (%s), and it binds "
                           "only as `%s` - the gate is what decides the work is "
                           "done. Fix the work and %s"
                           % (who, last.get("status"), run, VERDICT_PASSED, record))
        out["arm"] = ARM_RED
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
            out["arm"] = ARM_REPEAT_GONE
            return out
    out["measured"] = measured
    mismatch = gate_mismatch(measured, entries, source, build)
    if mismatch:
        out["sentence"] = ("%s's newest verdict is `%s` (%s), but %s; %s"
                           % (who, VERDICT_PASSED, run, mismatch, record))
        out["arm"] = ARM_GATE_CHANGED
        return out
    return dict(out, **digest_binding(project, manifest_path, who, owns, config,
                                      measured, run, record,
                                      digest_root=digest_root))


def digest_binding(project, manifest_path, who, owns, config, measured, run,
                   record, digest_root=None):
    """`{"state", "sentence"}` - the declared-work half of `binding`: the measured
    row's digest against the declared files now - under `digest_root` when the
    caller names the tree being judged, else under `project`.

    The record paths are left out on this side exactly as the recorder left them
    out (`_evidence_io.recorded_paths`), which is what lets a subject declare its
    own manifest file and still be graded on the rest of its work.
    """
    excluded, _dropped = _evidence_io.recorded_paths(project, manifest_path, config)
    owns = list(owns or [])
    state = measured.get("testedState") or {}
    was = state.get("scopeDigest")
    now, basis = _tree_stamp.scope_digest(digest_root or project, owns,
                                          excluded=excluded)
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
        return {"state": "refused", "arm": ARM_DIGEST_MOVED,
                "sentence": ("%s's newest verdict is `%s` (%s), but %s - "
                             "scopeDigest was %s and is %s now (%s); %s"
                             % (who, VERDICT_PASSED, run, what, was, now, basis,
                                record))}
    if field == _tree_stamp.UNANSWERABLE:
        return {"state": "refused", "arm": ARM_DIGEST_UNANSWERABLE,
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


# --- the close: a task's `done`, a phase's landing ------------------------------
def phase_files(phases):
    """The union of the task files `phases` declare, in plan order."""
    files = []
    for ph in phases:
        for task in (ph.get("tasks") or []):
            if isinstance(task, dict):
                files.extend(f for f in (task.get("files") or []) if f not in files)
    return files


def task_binding(project, manifest_path, manifest, phase, task, record, no_gate,
                 config=None):
    """`binding` for `task` under the gate that measures it - its own, or its
    phase's - over its declared files. `record` and `no_gate` are the caller's
    words; which gate and which files are this one answer."""
    entries, source = _mio.gate_entries(phase, task)
    build = ((manifest or {}).get("meta") or {}).get("buildCommands")
    return binding(project, {"taskId": str(task.get("id")),
                             "phaseId": str(phase.get("id"))},
                   entries, source, list(task.get("files") or []), manifest_path,
                   record, no_gate, config=config, build=build)


def phase_binding(project, manifest_path, manifest, phase, files, record,
                  no_gate, config=None, texts=None, digest_root=None):
    """`binding` for `phase`'s own gate over `files` - its task files, or a
    group's union when `phase` carries a group's one run. `texts` and
    `digest_root` are `binding`'s: the ledger and the tree being judged when
    they are not the ones under `project`."""
    entries, source = _mio.gate_entries(phase, None)
    build = ((manifest or {}).get("meta") or {}).get("buildCommands")
    return binding(project, {"phaseId": str(phase.get("id"))}, entries, source,
                   files, manifest_path, record, no_gate, config=config,
                   build=build, texts=texts, digest_root=digest_root)


# The arms a sign-off recorded with `--no-evidence-reason` answers: a green that
# no longer binds. That sign-off chose to stand on no run, so a stale green is
# not the verdict it stood on; a red, an unplaceable row or an unreadable ledger
# is still asked.
STALE_GREEN_ARMS = (ARM_REPEAT_GONE, ARM_GATE_CHANGED, ARM_DIGEST_MOVED,
                    ARM_DIGEST_UNANSWERABLE)
_RED_ARMS = (ARM_RED, ARM_RED_AFTER_GREEN)


def close_refusal(answer, signed_without_run=None):
    """The sentence a close over `answer` is refused with, or None when the
    close may stand on it - `CLOSE_REFUSING_ARMS` is the rule.

    `signed_without_run` is `{"at": <ts or None>}` when the subject's sign-off
    recorded a `--no-evidence-reason`, else None. That decision is honoured: the
    stale-green arms do not refuse, and a red refuses only when it was recorded
    AFTER the sign-off - newer evidence it never saw. A red the sign-off came
    after, it chose to stand over. With no moment for the sign-off (`at` None:
    its journal row could not be read), every red refuses, the side that cannot
    land work over a red nobody answered.
    """
    if answer.get("state") != "refused" \
            or answer.get("arm") not in CLOSE_REFUSING_ARMS:
        return None
    if signed_without_run is not None:
        arm = answer.get("arm")
        if arm in STALE_GREEN_ARMS:
            return None
        at = _evidence_io.stamp_moment(signed_without_run.get("at"))
        red = _evidence_io.stamp_moment((answer.get("row") or {}).get("ts"))
        if arm in _RED_ARMS and at is not None and red is not None \
                and red <= at:
            return None
    return answer.get("sentence")


def member_red(texts, member_id, carrier_answer, record):
    """A refusal in `binding`'s shape when a group member's own newest red - the
    newest after its last green - is newer than the carrier's run that grades the
    group, else None.

    The carrier's run is the group's verdict, and a member's own rows are not
    asked by it; a red recorded on the member alone afterwards is newer evidence
    about the branch every member lands. A red whose moment cannot be placed
    refuses, the side that cannot land over it unanswered."""
    rows = [r for r in rows_of(texts)
            if _evidence_io._same_subject(r, {"phaseId": str(member_id)})]
    red = red_after_green(rows)
    if red is None:
        return None
    graded = carrier_answer.get("measured") or carrier_answer.get("row") or {}
    then = _evidence_io.stamp_moment(graded.get("ts"))
    when = _evidence_io.stamp_moment(red.get("ts"))
    if then is not None and when is not None and when <= then:
        return None
    return {"state": "refused", "arm": ARM_RED, "row": red, "measured": None,
            "notes": list(carrier_answer.get("notes") or []),
            "sentence": ("%s's own newest gate verdict is `%s` (run %s at %s), "
                         "recorded after the group's run %s that grades it - a "
                         "red on one member is newer evidence about the branch "
                         "every member lands. Fix the work and %s"
                         % (member_id, red.get("status"), red.get("runId"),
                            red.get("ts"), graded.get("runId"), record))}


def signoff_moment(texts, phase_id):
    """The `ts` of the newest `phase.verdict` journal row for `phase_id` in
    `texts` (`ledger_texts`' shape over the journal), or None - the moment a
    sign-off was recorded, which the plan itself does not carry."""
    rows = [r for r in rows_of(texts)
            if r.get("action") == "phase.verdict"
            and str((r.get("details") or {}).get("phaseId")) == str(phase_id)]
    last = newest(rows)
    return (last or {}).get("ts")


def close_line(answer):
    """What a close says about the verdict it stood on - one sentence for every
    answer it closed over, a refused-for-a-commit one included, so a close never
    reads as bound when it was not."""
    if answer.get("state") != "refused":
        return answer.get("sentence")
    return ("not bound, and no measurement to vouch for: %s. A close refuses "
            "only over a verdict recorded and no longer holding"
            % (answer.get("sentence"),))


def group_of(manifest, phase):
    """`(carrier, members)` - the phase whose run grades `phase`, and every phase
    that run grades, carrier first; `(phase, [phase])` for a phase graded alone.

    A GROUP'S VERDICT IS ITS CARRIER'S RUN. Group sign-off records the one run
    on the carrier and copies its pointer onto every other member with
    `testEvidence.gradedBy` naming the carrier, so a member's own ledger rows
    are none and its own binding would read as no verdict at all. Asked the way
    sign-off asked it: the carrier's gate, over the union of the members' files.
    """
    phases = [p for p in ((manifest or {}).get("phases") or [])
              if isinstance(p, dict)]
    pid = str((phase or {}).get("id"))

    def graded_by(p):
        evidence = p.get("testEvidence")
        return str(evidence.get("gradedBy")) if isinstance(evidence, dict) \
            and evidence.get("gradedBy") else None
    carrier_id = graded_by(phase or {}) or pid
    carrier = ([p for p in phases if str(p.get("id")) == carrier_id] or [phase])[0]
    members = [carrier] + [p for p in phases
                           if graded_by(p) == carrier_id
                           and str(p.get("id")) != carrier_id]
    return carrier, members


def override_details(ids, answer, reason):
    """The `details` of the row a close over its verdict's refusal writes: the
    subject, the run it went over when there is one, and the operator's reason."""
    details = dict((k, str(v)) for k, v in (ids or {}).items()
                   if k in ("taskId", "phaseId") and v is not None)
    details["reason"] = reason
    row = answer.get("row") or {}
    if row.get("runId"):
        details["runId"] = str(row["runId"])
    return details


def override_summary(ids, answer, reason):
    """The row's summary: which close, over which refusal, and why."""
    return ("%s's close was asked to stand over the verdict that refused it "
            "(%s): %s"
            % (label_of(ids), answer.get("sentence"), reason))


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
