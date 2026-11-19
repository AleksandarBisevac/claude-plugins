#!/usr/bin/env python3
"""
Where a test-execution evidence record lives, and what it is allowed to say.

The gate runner already answers the two questions an exit code cannot -- did the
gate change the tree, and did anything actually run -- and then throws every one
of those answers away: `run-test-gate.py` performs no disk I/O at all. This module
is the memory it never had.

WHY NOT THE JOURNAL. `_journal_io.DETAILS_KEYS` is an allow-list, and the three
tests it states for a new key are that the key names A FIELD OF THE PLAN that
moved, that it is bounded, and that it exposes nothing new. An exit code, a
duration and a check count fail the first outright -- they are things the plugin
OBSERVED ABOUT THE MACHINE -- and `MAX_DETAILS_BYTES` would clip a multi-step run
besides. So the runs live here and the journal ANCHORS them: one row per recorded
run naming its `runId`, which is a plan field and passes all three.

WHY NOT THE USAGE LEDGER'S HOME EITHER. `<ledgerDir>` is local scratch that writes
its own `.gitignore`; this is evidence for an audit somebody hands to a client, so
it sits beside the manifest and is COMMITTED, exactly like the journal. The two
differ in what they are for, not in where they belong.

FILE LAYOUT
    <evidence dir>/<YYYY-MM>.<writerId>.jsonl     (default <manifest dir>/evidence)
    <evidence dir>/<YYYY-MM>.<writerId>.wt-<key>.jsonl   (in a linked worktree)

One file per writer per month, which is the journal's argument and not a
decoration: two sessions in two git worktrees append at the same time, and a
single shared file would conflict on every merge -- the one thing the sharded
manifest layout exists to avoid. The writer id and the month come from
`_journal_io`, so the two records name the same writer the same way.

EVERY ROW IS HASH-CHAINED, using the trail's own chain and not a second one. The
row that records a MEASUREMENT was the last unchained file this plugin committed,
and a plain string replace could turn a recorded `failed` into a recorded `passed`
with nothing reporting a finding. `append_row` links each row onto the file's tail
and `verify()` reads the links back; both spell the chain with `_journal_io`'s
`row_hash`, `genesis_prev` and `canonical`. What that covers, what the journal
anchor covers instead of it, and what a row written before the chain existed is
graded as, are all at the section marked `the chain, and what each layer covers`
-- read it before trusting any of the three for something it does not do.

EVERY ANCHOR ROW HERE GOES THROUGH `_journal_io.append_from_cli`, not
`append`. `run-test-gate.py` is the only caller of the functions here that write
one, and it is a script the operator runs from Bash: nothing else can claim the
journal file the append dirties -- the journal-writes hook files its claim under a
session id no script is handed, and the panel files under its own -- so an
unclaimed row made the NEXT Bash command draw `guard-bash-writes`' notice about a
write this plugin had just made itself.

This module carries no `--selftest` of its own; its cases live in
`tests/test__evidence_io.py` -- see `tests/_harness.py`.
"""
import binascii
import calendar
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time

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

import _utc_stamp  # noqa: E402  (utc_stamp: the one spelling of this moment)
import _journal_io  # noqa: E402  (config loading, the writer id, the month)
import _loader  # noqa: E402  (load_hooks_config: the one door between git's path base and the plan's)
import _locks  # noqa: E402  (the plan-file lock: whose, is it live, take it)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; the atomic write)
import _manifest_vocab  # noqa: E402  (the FULL_STATUS words, one vocabulary)
import _worktrees  # noqa: E402  (git ancestry: merged_into, the three answers)
import _usage_core  # noqa: E402  (parse_ts: a full run's ts read as a moment)
import _task_timing as _timing  # noqa: E402  (a recorded run's stages, appended once)
from _journal_io import (command_facts, redacted_paths,  # noqa: E402
                         redacted_text, repo_relative_or_token)
from _machine_paths import OUTSIDE_TOKEN  # noqa: E402

DEFAULT_DIRNAME = "evidence"
# The one row field the append's scrub passes through untouched: a STEP's
# `command`, which is a copy of the plan's own gate entry (which the plan's save
# scrubbed) and which every reader compares back to that entry, so rewriting it
# would make a recorded run stop matching the gate it ran. By position and not
# by key name: a `command` anywhere else in a row is text some runner or caller
# composed, and is free text like the rest.
LEDGER_KEPT_STEP_KEY = "command"


# --- one resolution of a gate entry, for every reader that needs one -----------
def resolved_commands(manifest, entries):
    """`[(name, command)]` -- every entry through `meta.buildCommands`, once,
    with `meta.nodePreamble` in front.

    THE ONE HOME. `run-test-gate.py` used to be the only place that knew how
    to turn a `meta.buildCommands` KEY into a shell command, which made it the
    only caller that could ask `full_status` the question it needs asked:
    `full_status`'s `full_commands` argument is this function's answer for
    the RUNNABLE entries of `meta.fullGate` (`full_gate` below), and it is the
    SAME resolution a recorded run's
    `published` list comes from -- so a plan judged whole is judged against
    the identical list its own row was measured against, never a second
    reading of `meta.buildCommands` that could drift from it. `doctor.py`, the
    panel and the release guard all need that same question answered and none
    of them may import a hyphen-named entry point, which is what put this here
    rather than where it was written first.

    AN ENTRY NAMING NO BUILD COMMAND IS CARRIED VERBATIM, because it may be a
    literal shell command and refusing it would make this function decide
    what a gate is allowed to be. A BLANK `nodePreamble` IS NOT A PREAMBLE --
    prefixing `   && ` would make every gate on the manifest die of a shell
    syntax error, which is the false red this guards against. Joined with
    `&&` rather than a pipe: `reference/orchestrator.md`'s "un-piped" asks for
    exactly that, because a pipe hands the gate's exit status to the
    preamble's tail and loses the verdict.
    """
    manifest = manifest if isinstance(manifest, dict) else {}
    meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
    build = meta.get("buildCommands")
    build = build if isinstance(build, dict) else {}
    preamble = meta.get("nodePreamble")
    lead = preamble.strip() if isinstance(preamble, str) else ""
    resolved = []
    for entry in entries or []:
        if not (isinstance(entry, str) and entry.strip()):
            continue
        command = build.get(entry, entry)
        resolved.append(
            (entry, ("%s && %s" % (lead, command)) if lead else command))
    return resolved


def full_gate(manifest):
    """`{"commands": [(name, command)], "reviewOnly": [name]}` - the RUNNABLE
    `meta.fullGate`, resolved, and the entries left out of it because they
    are reads rather than commands, in declaration order.

    THE ONE LIST A FULL RUN IS COUNTED AGAINST. The runner records the
    commands it ran, and every reader - the release guard, the status, the
    report, the panel, the doctor, the pre-push step - compares a recorded
    row against what the plan declares. A review-only entry is never run, so
    a reader counting it would hold every green run one entry short and keep
    every merged phase provisional. Empty `commands` means NO RUNNABLE FULL
    GATE, which every reader answers exactly as it answers a plan naming no
    `meta.fullGate`; `reviewOnly` is carried so a surface can say what it
    left out rather than leave the reader to wonder.

    JUDGED BEFORE THE PREAMBLE (`_manifest_vocab.review_only_entry`), because
    a `nodePreamble` in front of the resolved command hides the prefix.
    """
    manifest = manifest if isinstance(manifest, dict) else {}
    meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
    build = meta.get("buildCommands")
    entries = meta.get("fullGate")
    entries = [e for e in (entries if isinstance(entries, list) else [])
               if isinstance(e, str) and e.strip()]
    left = [e for e in entries if _manifest_vocab.review_only_entry(e, build)]
    keep = [e for e in entries if e not in left]
    return {"commands": resolved_commands(manifest, keep), "reviewOnly": left}


def full_gate_commands(manifest):
    """The bare command half of `full_gate(manifest)["commands"]` - the
    `full_commands` argument `full_status` takes, and `[]` when there is no
    runnable full gate."""
    return [command for _name, command in full_gate(manifest)["commands"]]


def phase_gate_steps(manifest, phase):
    """`[(name, command)]` - the phase's own `testGate` as its sign-off run
    executes it: resolved once (`resolved_commands`), less the review-only
    entries, which are said and never run.

    WHAT `executor.phaseGateOnly` IS ASKED AGAINST. A task-scope run leaves a
    command the setting names to the phase gate only when this list holds it,
    and the writer's prompt, the recorder and the drive's view of a task's
    steps all read it here, so the three agree on what the phase gate runs."""
    manifest = manifest if isinstance(manifest, dict) else {}
    meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
    build = meta.get("buildCommands")
    entries = _mio.gate_entries(phase if isinstance(phase, dict) else {})[0]
    keep = [e for e in entries
            if not _manifest_vocab.review_only_entry(e, build)]
    return resolved_commands(manifest, keep)


# --- what a task's run left to the phase gate --------------------------------
# A task-scope run leaves out a command `executor.phaseGateOnly` names when the
# phase's own gate holds it (`_config_rules.phase_gate_only_split`). The row
# lists each one under this key, so the run is one step short of its declared
# gate for a reason the row itself states: the verdict binding reads the key
# as part of the declaration (`left_to_phase_gate_names`), and a reader of the
# row sees what the run did not measure. `arm` is `declared` for an entry of
# the task's gate, else the arm of the derived step that proposed it.
LEFT_TO_PHASE_GATE_KEY = "leftToPhaseGate"
LEFT_DECLARED_ARM = "declared"
LEFT_TO_PHASE_GATE_FIELDS = ("name", "arm", "basis", "matched")


def left_to_phase_gate_record(name, matched, basis):
    """One entry of `LEFT_TO_PHASE_GATE_KEY`: the step `name`, the arm that
    proposed it (`LEFT_DECLARED_ARM`, or a derived step's arm), `basis` - the
    setting that left it out - and the setting's entry it `matched`."""
    arm = LEFT_DECLARED_ARM
    if is_derived_step(name):
        arm = name[len(DERIVED_STEP_PREFIX):].partition(": ")[0]
    return {"name": name, "arm": arm, "basis": basis, "matched": matched}


def left_to_phase_gate_names(row):
    """The DECLARED gate entries `row` lists as left to the phase gate, in the
    order it lists them; [] for a row with no such key. A step another arm
    proposed is not a declared entry, so it never stands in for one."""
    listed = row.get(LEFT_TO_PHASE_GATE_KEY) if isinstance(row, dict) else None
    return [str(e.get("name")) for e in (listed if isinstance(listed, list) else [])
            if isinstance(e, dict) and e.get("arm") == LEFT_DECLARED_ARM
            and e.get("name")]


# --- where it lives -----------------------------------------------------------
def evidence_dir(project, config=None):
    """Absolute path of the evidence directory.

    `evidence.dir` when set, else `<manifest dir>/evidence` -- derived from
    `manifestPath` rather than hardcoded, for `journal_dir`'s reason: a repo that
    moved its plan must not end up with the record of it somewhere else entirely.

    THE RESOLUTION IS SHARED WITH THE JOURNAL'S, DELIBERATELY. Both answer "where
    does this manifest keep its committed record", and two expressions of that
    would put the trail and the evidence in different places the first time a repo
    set `manifestPath` to something unusual.
    """
    config = _journal_io.load_config(project) if config is None else config
    block = (config or {}).get("evidence")
    rel = block.get("dir") if isinstance(block, dict) else None
    if isinstance(rel, str) and rel.strip():
        return os.path.normpath(os.path.join(project, rel.strip()))
    manifest = (config or {}).get("manifestPath") or _journal_io.DEFAULT_MANIFEST
    return os.path.normpath(os.path.join(
        project, os.path.dirname(str(manifest)) or ".", DEFAULT_DIRNAME))


def in_evidence(project, path, config=None):
    """True when `path` (absolute or project-relative) is inside the evidence dir.

    THE PAIR `evidence_dir` MAKES: one derivation of where the record lives, and
    one test of whether a path is inside it, so a reader never has to re-derive
    the location to answer the membership question.

    The prefix test carries the separator on purpose - without it a sibling whose
    name merely STARTS the same way (`<dir>-notes/x.jsonl` beside `<dir>/`) reads
    as inside the record.

    It answers for readers on THIS side of the hook boundary. `hooks/` may import
    nothing from `scripts/`, so a guard asking the same question of the journal
    asks `hooks/_config.in_journal`, which is its own implementation and not this
    one.
    """
    try:
        d = os.path.realpath(evidence_dir(project, config))
        p = path if os.path.isabs(path) else os.path.join(project, path)
        p = os.path.realpath(p)
        return p == d or p.startswith(d + os.sep)
    except Exception:
        return False


def recorded_paths(project, manifest_path, config=None):
    """`(rels, dropped)` -- every path THIS recorder writes, as project-relative
    prefixes, sorted, and any write this function could not turn into one.

    WHO NEEDS IT. A caller asking "is this tree the one that was measured?" has to
    leave the recorder's own output out of the answer, or the first recorded run
    changes the tree and no second run can ever match it. That is a narrowing, so
    it is DERIVED from the writers rather than listed: `evidence_dir` and
    `journal_dir` are asked where they put their files, and the shards come off
    the index's own `shard` stubs, so a repo that moved its plan moves this with
    it.

    THE RAW INDEX AND NEVER THE ASSEMBLED MANIFEST, which is `_phase_file`'s rule
    and it is here for the same trap: assembly REPLACES each `shard` stub with
    the phase body it names, so a reader handed the assembled dict finds no shard
    paths at all and leaves every one of them inside the identity. The failure is
    quiet - an identity that simply never matches anything - which is why the raw
    read happens here rather than being left to a caller who already has a
    manifest in hand.

    WHAT THE NARROWING COSTS IS THE CALLER'S TO STATE, not this function's to
    hide: the manifest is in here, so a gate whose subject IS the manifest is one
    such a caller cannot tell apart. The parts of the manifest that decide what a
    gate DOES - the entries and the declared files - are things the caller reads
    directly and can put in its own key.

    BOTH SIDES ARE RESOLVED BEFORE THEY ARE COMPARED, and that is not cosmetic.
    `project` reaches this function however ITS caller spelled it, and a write
    built by joining a relative suffix onto it inherits that same spelling - so
    comparing the two lexically is safe only while neither has passed through a
    symlink. Wherever one has - and a plain child process's own working directory
    already comes back resolved on some platforms, which is what makes the system
    temp directory exactly such a path there - the two spellings of the identical
    file stop sharing a prefix, `os.path.relpath` answers with a string climbing
    back OUT of `project`, and a write this recorder makes reads as outside it:
    MORE of the tree, not less, ends up inside the content identity the caller is
    narrowing, and the one file that changes on every recorded run is exactly the
    one this function exists to leave out. Resolving both sides removes the
    spelling from the question and leaves only whether the write is really under
    the project.

    A PATH THAT IS STILL OUTSIDE `project` ONCE RESOLVED IS REPORTED, NOT
    SILENTLY DROPPED, in the second return value, as `(path, why)`. That is a
    different claim from the one the old comment made here: leaving an outside
    path out of `rels` is still safe in the direction that matters, because it
    leaves MORE of the tree inside the identity rather than inventing a match -
    but a narrowing the caller asked for that quietly did not apply is a thing to
    say, not a thing to absorb, or the only trace of it is a changed count in a
    basis line nobody was watching.
    """
    config = _journal_io.load_config(project) if config is None else config
    writes = [evidence_dir(project, config), _journal_io.journal_dir(project, config)]
    if manifest_path:
        base = os.path.dirname(os.path.abspath(manifest_path))
        writes.append(os.path.abspath(manifest_path))
        try:
            index = _mio.read_json(manifest_path)
        except Exception:
            # The manifest itself is excluded above whatever happens here, so an
            # index nobody can read costs a caller its shards and never its
            # correctness: MORE of the tree stays inside the identity, which is
            # the direction that refuses a match rather than inventing one.
            index = {}
        for stub in ((index or {}).get("phases") or []):
            shard = stub.get("shard") if isinstance(stub, dict) else None
            if isinstance(shard, str) and shard.strip():
                writes.append(os.path.normpath(os.path.join(base, shard.strip())))
    root = os.path.realpath(project)
    rels, dropped = [], []
    for path in writes:
        try:
            # Excluded against what `git ls-files` prints, which is always "/"
            # regardless of platform - the same reason every other published
            # path here goes through the one helper instead of a hand-rolled
            # replace.
            rel = _output.posix_rel(os.path.realpath(path), root)
        except Exception as exc:
            dropped.append((path, "could not be compared against the resolved "
                                  "project root: %s" % (exc,)))
            continue
        if rel == ".":
            dropped.append((path, "resolves to the project root itself, so "
                                  "excluding it would exclude everything"))
            continue
        if rel == ".." or rel.startswith("../"):
            dropped.append((path, "resolves outside the project even once "
                                  "symlinks are followed on both sides"))
            continue
        rels.append(rel)
    return sorted(set(rels)), dropped


# --- what a row may carry -----------------------------------------------------
# ASSEMBLED FROM NAMED FIELDS, NEVER COPIED. `row_for` reads the keys below out of
# whatever it is handed and nothing else, which is what makes the shape of a row a
# property of the WRITER rather than a habit each call site has to remember.
#
# RUNNER OUTPUT HAS EXACTLY ONE ROUTE IN, AND IT IS `failing`. It used to have
# none, and that was the defect rather than the safeguard: the gate runner holds
# full merged stdout while it counts checks and scrapes paths, and then dropped
# it, so a red row named the failing gate ENTRY and never a failing TEST. Two
# projects reported the same cost, and one of them recovered the names twice out
# of an artefact the next run overwrites. What the old sentence was protecting is
# kept by construction instead of by absence: that one field is cut to
# `MAX_FAILING` lines by `_step` rather than by its caller, and every line goes
# through the trail's redactor on the way in, so no path a runner printed reaches
# a committed file raw.
ROW_VERSION = 1
ACTION_RECORDED = "test.evidence.recorded"

# WHERE A VERDICT CAME FROM, WHICH IS NOT WHAT THE VERDICT IS. `status` says what
# the gate answered; this says whether THIS run is the one that asked. The word
# is its own rather than borrowed: `could-not-run` already means "no verdict, for
# a reason that is not the work's", and a repeated verdict is the opposite of
# that - there IS a verdict, it is simply not this run's measurement. Overloading
# the one to spell the other would lose both.
#
# ABSENT MEANS MEASURED. Every row written before this field existed was a
# measurement, so a missing key is the true answer for all of them and no
# back-fill is owed; a key present on every row could not be told from a build
# that does not write it.
VERDICT_SOURCE = "verdictSource"
REUSED = "reused"
# A THIRD WORD, FOR A ROW THAT IS NEITHER. A gate holding an entry that names a
# path the content identity leaves out (the plan, the ledger) measures that
# entry on every run and may repeat the rest; such a row measured some steps
# and copied others, so `reused` would claim nothing ran and absence would
# claim everything did. Each copied step carries `STEP_REUSED_KEY` naming the
# run it came from; the row's own `reusedFrom` names that same run. The
# row's tree reading, its `durationMs` and its counts are the measured steps'
# alone, so a row with this word is graded as the measurement it is
# (`measured_row` returns it, not its source).
PART_REUSED = "part-reused"
# On a step: the run whose measurement this step repeats, `{runId, ts}`. A step
# carrying it ran nothing here, so no reader counts it as a run of that step
# or as time spent (`step_repeated`), and the writer keeps no duration for it.
STEP_REUSED_KEY = "reusedFrom"

# WHO RAN THE SUITE, WHICH IS NOT THE SAME QUESTION AS `via`. `via` names the
# interface the recorder was reached through and answers "cli" on every row ever
# written; this names whether the wrapper MADE the run it is recording.
#
# It exists because a suite can run where this plugin cannot see it. A push runs
# one on a server; a developer runs one in a second terminal; a hook runs one on
# commit. Those runs move the same working tree, take the same ports and write the
# same scratch directories as a gate run, and until there was a word for them a
# red that a concurrent outside suite had caused was recorded, rendered and read
# as the gate's own verdict on the work. Recording the outside run does not make
# the red go away -- nothing here can -- but it is the difference between a
# verdict and a verdict with a rival in the same window.
#
# ABSENT MEANS THE GATE, and no back-fill is owed: every row written before this
# field existed was made by the wrapper, so a missing key is the true answer for
# all of them. `runner_of` is the one reader of that rule.
RUNNER_KEY = "runner"
RUNNER_GATE = "gate"
RUNNER_OUTSIDE = "outside"
RUNNER_WORDS = (RUNNER_GATE, RUNNER_OUTSIDE)

# WHEN THE RUN BEGAN, recorded rather than inferred. `ts` is the moment the row
# was BUILT -- after the run finished -- and `durationMs` is a monotonic elapsed
# reading that cannot be turned back into an instant, so until this key existed
# the ledger could say how long a run took and never when it was happening. A
# window is what an overlap question needs, and two rows cannot be compared
# without one.
#
# THE DERIVED WINDOW IS STILL AVAILABLE and is labelled as derived: `window_of`
# falls back to `ts` minus `durationMs` for a row written before this key, and
# says so in its basis. A derivation presented as a record is how a cheap read
# comes to be trusted like a measurement.
STARTED_KEY = "startedAt"
# The token a caller that launched a run in the background handed it, on its
# row and on its record (`row_for`, `run_record`).
LAUNCH_KEY = "launch"
# HOW LONG CHOOSING WHAT TO RUN TOOK, beside `durationMs` and never inside it,
# on the same monotonic clock. On a measured run it runs from the start of the
# gathering to the first step, so it holds the gathering of a task's affected
# suites, the identity and the reuse lookup, the reach reading, and the reading
# of the tree `run_gate` takes before its first command. On a repeat, which runs
# no step, it runs from the start of the gathering to the identity, and the
# identity and the lookup are the repeat's `durationMs`; on either path the two
# figures meet without overlapping (`run-test-gate.py`'s selection clock).
# On a measured run `durationMs` stays the steps alone because `gate_mean_ms`,
# the doctor's gate budget and the usage comparisons all decide on it, and a
# figure that grew a second meaning would move every one of their answers.
# ABSENT IS NOT ZERO: a
# row written before the key existed measured no selection, and
# `selection_ms` is the one reader that keeps those two apart.
SELECTION_KEY = "selectionMs"
# The identity that has to match for one run to stand in for another. It is
# recorded on the row rather than re-derived, because it is a statement about the
# tree AT THAT MOMENT and the moment is gone.
REUSE_KEY = "reuseKey"

# The row key for `gate_digest`'s answer.
GATE_DIGEST_KEY = "gateDigest"

# THE STEPS A TASK'S RUN ADDS THAT ITS GATE DID NOT DECLARE. A task gate
# narrower than its phase's runs the suites its change can break beside it
# (`_affected_tests.entries_for`, `run-test-gate.affected_steps`), each recorded
# under a name carrying this prefix. They are measured, never declared, so the
# question "which steps of this row are the gate it was measured under" has one
# answer, `declared_steps`, which the recorder digests and the committer
# compares - spelled here and nowhere else. The prefix is therefore reserved: a
# gate entry spelled with it reads as derived, and its gate never binds.
DERIVED_STEP_PREFIX = "affected/"


def is_derived_step(name):
    """True when a recorded step name is one the recorder added, not declared."""
    return isinstance(name, str) and name.startswith(DERIVED_STEP_PREFIX)


# The arm a derived step widened to the phase gate is named under: its name
# carries a gate entry after the colon, not a list of suites.
DERIVED_PHASE_GATE_ARM = "phase-gate"


# A DECLARED ENTRY AND THE AFFECTED STEPS RUN AS ONE CALL. When the entry is the
# plan's recorded subset spelling over a list of paths and the affected steps
# are that spelling over other lists, the run makes one call over the union
# (`_affected_tests.joined_steps`), recorded as ONE step named for the entry
# followed by each affected step's name, joined by this separator. The name, not
# a key on the step, carries both lists because every reader of a row's steps
# already reads the name - the binding, the base lookup, the repeat, the printed
# step line - so none of them has to be handed the step instead.
#
# `step_parts` IS THE ONE READER of what such a step covers, and
# `declared_steps`, `derived_step_suites` and `step_runs_suite` answer through
# it. An older name reads exactly as it did: a declared one as itself, a derived
# one as itself, and a name whose tail is no affected step as a declared one.
JOINED_STEP_SEPARATOR = " + "


def joined_step_name(declared, derived):
    """The name of one step that ran the declared entry `declared` and the
    affected steps named `derived` as one call - what `step_parts` reads."""
    return JOINED_STEP_SEPARATOR.join([str(declared)] + [str(d) for d in derived])


def _joinable_part(part):
    """Whether `part` is an affected step's name a joined step may carry: an arm,
    then a non-empty suite list. The phase-gate arm carries a gate entry, never
    a suite list, so it is never joined."""
    arm, sep, listed = part[len(DERIVED_STEP_PREFIX):].partition(": ")
    return (bool(sep) and bool(arm.strip()) and " " not in arm
            and arm != DERIVED_PHASE_GATE_ARM and bool(listed.strip()))


def step_parts(name):
    """`(declared, derived)` - the declared gate entry a recorded step ran, or
    None when it ran none, and the names of the affected steps it ran.

    A declared step is `(name, [])` and a derived one `(None, [name])`. A JOINED
    step - the declared entry, then each affected step's name, each after
    `JOINED_STEP_SEPARATOR` - is `(entry, [names])`, and only when the entry
    comes FIRST: a name opening with the derived prefix is a derived step
    whatever follows it, so the declared slot is the head of the name or
    nothing. A tail that is not an affected step's name with an arm and a suite
    list leaves the whole name declared, as it always read."""
    name = str(name)
    if is_derived_step(name):
        return None, [name]
    head, sep, rest = name.partition(JOINED_STEP_SEPARATOR + DERIVED_STEP_PREFIX)
    if not sep or not head.strip():
        return name, []
    derived = [DERIVED_STEP_PREFIX + part for part in
               rest.split(JOINED_STEP_SEPARATOR + DERIVED_STEP_PREFIX)]
    if not all(_joinable_part(part) for part in derived):
        return name, []
    return head, derived


def derived_step_suites(name):
    """The suite paths the derived steps a step ran list after their arm - the
    `<prefix><arm>: <suite>, <suite>` spelling `_affected_tests.steps_for`
    writes, read for each derived step a joined step carries (`step_parts`) -
    or [] for a declared step and for the phase-gate arm, whose name carries a
    gate entry instead."""
    out = []
    for part in step_parts(name)[1]:
        arm, sep, listed = part[len(DERIVED_STEP_PREFIX):].partition(": ")
        if not sep or arm == DERIVED_PHASE_GATE_ARM:
            continue
        out.extend(p.strip() for p in listed.split(", ") if p.strip())
    return out


def declared_steps(names, dropped=0):
    """`(declared, dropped)` - the step names in `names` that are the declared
    gate, and how many of the steps a row dropped for length were declared.

    THE DERIVED STEPS COME LAST: the recorder appends them after every declared
    entry, so the declared gate is the names before the first derived one. A
    declared-looking name AFTER a derived one is no shape the recorder writes,
    so nothing is split off and every name is answered as declared - the
    comparison then refuses rather than binding on a guess.

    `dropped` is the row's `stepsDropped`. Dropped steps are the tail: with a
    derived step kept, every dropped one came after it and none was declared;
    with none kept, which of them were declared is not recorded, so all are
    counted as declared and a gate the row cannot speak for is refused.

    A JOINED step is read through `step_parts` as the declared entry it ran:
    it stands at that entry's place among the declared steps, so the declared
    gate is the same list whether the affected steps ran joined to it or after
    it. A step that ran no declared entry ends the declared part.
    """
    names = [str(n) for n in (names or [])]
    dropped = dropped if isinstance(dropped, int) and dropped > 0 else 0
    heads = [step_parts(name)[0] for name in names]
    cut = next((i for i, head in enumerate(heads) if head is None), len(names))
    if any(head is not None for head in heads[cut:]):
        return names, dropped
    return heads[:cut], dropped if cut == len(names) else 0

# THE BANNERS A MEASURED RUN PRINTED THAT A GREEN EXIT STILL CARRIES, kept on its
# row so a later repeat of that verdict can print them again. Without them a
# repeat said `GATE GREEN` and nothing else, and the caller that asks a question
# of the banner (`drive-phase`'s coverage decision) never asked it of a repeated
# run. The names are the literals the renderer opens each banner with.
#
# ABSENT IS NOT EMPTY: a row written before this key holds nothing, a row written
# after it holds a list, and `banners_of` keeps the two apart by returning None
# for the first.
BANNERS_KEY = "banners"
BANNER_NO_OVERLAP = "NO OVERLAP WITH THIS WORK"
BANNER_TREE_CHANGED = "TREE CHANGED OUTSIDE THIS WORK"
ROW_BANNERS = (BANNER_NO_OVERLAP, BANNER_TREE_CHANGED)


def banners_of(row):
    """The banner names a row recorded, in the order of `ROW_BANNERS`, or None
    when the row does not say (written before the key existed, or a repeat of
    such a row). `[]` is the recorded answer "the run printed none"."""
    banners = row.get(BANNERS_KEY) if isinstance(row, dict) else None
    if not isinstance(banners, list):
        return None
    return [name for name in ROW_BANNERS if name in banners]


def gate_digest(entries, build):
    """`sha256:<hex>` over the gate as declared and resolved, or None for no entries.

    Each entry beside what it resolves to through `meta.buildCommands` (an entry
    naming none is its own command), in declared order, and WITHOUT
    `meta.nodePreamble` - that is the machine's prelude, not the gate. ONE
    SPELLING for the recorder that writes it and the committer that compares it,
    so the two cannot come to hash one gate two ways.
    """
    names = _mio.declared_gate_entries(list(entries or []))
    if not names:
        return None
    build = build if isinstance(build, dict) else {}
    pairs = [[name, build.get(name, name)] for name in names]
    return "sha256:" + hashlib.sha256(
        _journal_io.canonical(pairs).encode("utf-8")).hexdigest()

# A run with more steps than this is a build, not a gate; more paths than this is
# a rewrite, not a diff. Both cuts are COUNTED beside the list they cut, because a
# truncation nobody announced reads as "that is all there was".
MAX_STEPS = 24
MAX_PATHS = 40
# How many lines of a non-zero step's own output a row may carry, and it is a
# REAL bound rather than a hope: a row is hash-chained, so a field with unbounded
# content is a row with unbounded size and a chain whose cost nobody can state.
# The whole field is therefore at most this many lines of
# `_journal_io.MAX_VALUE_CHARS`, on steps that came back non-zero, of which a row
# keeps at most `MAX_STEPS` - three bounds a reader can multiply rather than a
# number written here that would rot the first time one of them moved.
#
# ONE CONSTANT, TWO READERS. `run-test-gate.run_gate` shapes the observation with
# this same name rather than a second one of its own, so the list the terminal
# prints and the list the row keeps cannot disagree about where the cut is; the
# slice below is still taken here, because this file's rule is that an inventive
# caller cannot widen a row.
MAX_FAILING = 10

# `measured` IS THE ONE DERIVED FIELD THIS ROW KEEPS, and the exception is
# deliberate rather than an oversight of the rule beside it. `signal` stays off
# the row because `exit` and `outcome` can be read for it - or, for a jest
# worker jest reaped itself at exit 1, `failing`, which names the signal beside
# the suite - and a cached claim can contradict its own source; that risk is
# what the rule guards. It cannot arise
# here: the word is computed from THIS row's `ran` by one function at write time
# (`run-test-gate.measured_state`), so the two cannot drift. What the rule does
# not guard is the failure that was actually reported - many readers, one
# integer-or-null, and each of them spelling the "ran nothing" / "does not say"
# distinction again. Recording the reading is what takes that spelling away from
# them. A row that carries no `measured` at all is a run from before the field or
# a caller that computed none; it is emphatically not a step that measured
# nothing, which is why a `None` here is dropped rather than stored.
#
# `failing` AND `failingBasis` ARE AN OBSERVATION AND NOT A SECOND VERDICT. The
# row already says whether the step failed - `exit`, `outcome` and the run's
# `status` - and these say what the runner wrote about it: the names of the
# checks it reported as failing where the summary reader recognises the runner,
# and a capped tail of its output where it does not. The basis is what tells
# those two apart, which is why neither travels without the other.
# `retriedAfterSignal` AND `retryBasis` ARE ON THE ROW FOR THE REASON `signal`
# IS NOT. The rule beside `measured` is that a claim the row can already be read
# for is not cached a second time, and `signal` obeys it: `exit` and `outcome`
# (or `failing`, for a jest worker) hold the evidence, so a reader a week later
# can name the signal without being told it. That does not hold here. Every other field of a retried step - its
# exit, its count, its duration, its outcome - describes the attempt that
# ANSWERED, and nothing in the row says an earlier attempt was ended by the OS
# and thrown away, which means a green row would read as a gate that answered on
# the terms the plan declared. The basis travels with the word because the second
# attempt may have run under a lowered worker bound or under the same one, and
# those are different claims about what was measured.
# `failingSuites`/`failingSuitesBasis` ARE THE SAME TWO RULES `failing` OBEYS,
# for the same reason: they are the other value a runner's own output wrote,
# so both the redaction rule and the row-cannot-be-widened rule land on them
# in `_step` and nowhere else. `suiteReader` needs neither - it is one of the
# vocabulary words this plugin composes, never a runner's own bytes, so it
# crosses unredacted exactly like `outcome` does.
#
# `outcomeBasis` IS THE THIRD SUCH VALUE, and the reason `could-not-run` had
# only ONE word for every cause. A no-verdict signature a runner printed, a
# derived run that skipped a listed suite, a missing interpreter and a step
# the OS killed all set `outcome` to the same word, and until this key
# existed nothing on the row said which of them happened -- a committed row
# carried the verdict and not why it was reached. It gets the same two rules
# `failing` gets, for the same reason: it is a sentence built out of a
# runner's own printed bytes (or, for the derived-gap arm, the phase's own
# suite names -- still worth bounding, since nothing here caps how many a
# phase declares), so it is redacted through `redacted_text` and cut to that
# function's own bound rather than trusted whole from the caller.
#
# `derivedGap` IS A MARKER, NOT A SECOND COPY of the sentence above. A reader
# asking "was THIS could-not-run a derived run that answered a narrower
# question than the phase declared" needs a fact it can branch on, and
# string-matching the basis sentence would break the moment its wording
# changed -- `run-test-gate.run_gate` sets the marker and composes the
# sentence in the same place, so the two cannot drift apart.
#
# `flaky` AND `flakyBasis` ARE THE TESTS A RUNNER REPORTED AS FLAKY - failed,
# then passed on retry - and the sentence saying where they were read. The
# names are a runner's own bytes, so `_step` cuts and redacts them as `failing`.
# They are an OBSERVATION and deliberately not an `outcome`: `_step_failed`
# and every tally built on it read any outcome as not-passed, and a
# flaky-but-green step is a pass with a named doubt.
#
# `muted` IS THE MUTE THAT EXCUSED THIS STEP'S FAILURE, on the step itself and
# not only on the row, because the readers that count failures read steps:
# `_step_failed` does not count a muted step, and neither does anything that
# learns failing suites off a row. A quarantined, known failure is not
# something the gate caught. Kept to suite, bug and day, cut at `MAX_PATHS`
# and each suite path redacted as `failingSuites` is.
#
# `reusedFrom` (`STEP_REUSED_KEY`) IS THE RUN A REPEATED STEP COPIES, kept to
# its `runId` and `ts`; `_step` writes no `durationMs` beside it.
STEP_KEYS = ("name", "exit", "ran", "measured", "durationMs", "outcome",
             "timeoutSeconds", "teardown", "failing", "failingBasis",
             "failingSuites", "failingSuitesBasis", "suiteReader",
             "retriedAfterSignal", "retryBasis", "outcomeBasis", "derivedGap",
             "flaky", "flakyBasis", "muted", STEP_REUSED_KEY)


def step_repeated(step):
    """True when a recorded step repeats another run's measurement rather than
    ran here: it carries `STEP_REUSED_KEY`. Every reader that counts a step as
    a run of it, or its duration as time spent, asks this first."""
    return isinstance(step, dict) and step.get(STEP_REUSED_KEY) is not None


def repeated_step_sources(row):
    """`[(step name, runId)]` for each step of `row` that repeats another run,
    in step order - empty for a row that repeated none."""
    found = []
    for step in (row or {}).get("steps") or []:
        if not step_repeated(step):
            continue
        source = step[STEP_REUSED_KEY]
        found.append((str(step.get("name")),
                      str(source.get("runId") if isinstance(source, dict)
                          else source)))
    return found
STATE_KEYS = ("head", "headBasis", "scopeDigest", "scopeBasis",
              "scopeListDigest", "dirtyDigest", "dirtyBasis", "tree")
_PORCELAIN_RENAME = " -> "
# The C-style escapes git writes INSIDE a quoted porcelain path. Git quotes a
# path whose bytes it will not print raw - a double quote, a backslash, a control
# character, and (under the default `core.quotePath`) every non-ASCII byte as a
# three-digit octal escape. A reader that only stripped the quotes would hold
# `caf\303\251.ts` and compare it against `café.ts`, which is a match it would
# miss rather than a match it would invent - silent, and in the unsafe direction
# for anything asking whose file moved.
_C_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13,
              '"': 34, "\\": 92}


def _unquote(text):
    """A C-quoted porcelain path as the name on disk; anything else unchanged.

    Returns the token EXACTLY AS GIVEN when the escape sequence is not one git
    writes, and that direction is the deliberate one: a path this cannot spell
    then fails to match, which a caller sees, where a guessed spelling would
    match some other file, which nobody sees.
    """
    if len(text) < 2 or not (text.startswith('"') and text.endswith('"')):
        return text
    body, out, i = text[1:-1], bytearray(), 0
    try:
        while i < len(body):
            if body[i] != "\\":
                out.extend(body[i].encode("utf-8"))
                i += 1
            elif body[i + 1] in _C_ESCAPES:
                out.append(_C_ESCAPES[body[i + 1]])
                i += 2
            else:
                out.append(int(body[i + 1:i + 4], 8))
                i += 4
    except (IndexError, ValueError):
        return text
    return out.decode("utf-8", "replace")


def porcelain_paths(entry):
    """EVERY path one `git status --porcelain` line names, oldest first.

    `XY <path>` names one. `XY <old> -> <new>` names TWO, and both of them
    matter to a caller asking whose file the line is about: a rename takes one
    name away and brings another, so a reader that kept only the new one would
    miss a declared file renamed OUT of the work under test. `_path_of` is the
    narrower question - which name exists NOW - and is the last of these.

    Anything that does not look like a porcelain line is passed through as a
    single path, so a caller holding bare paths is not made to know which shape
    this expects.
    """
    text = str(entry or "")
    if len(text) > 3 and text[2] == " " and not text[:2].strip(" ?!MADRCU"):
        text = text[3:]
    return [_unquote(part.strip()) for part in text.split(_PORCELAIN_RENAME)]


def _path_of(entry):
    """The path a `git status --porcelain` line is about, or the entry itself.

    The NEW name of a rename, because that is the one that exists now and this
    is what a stored row shows a reader."""
    return porcelain_paths(entry)[-1]


def _paths(project, entries):
    """`(kept, dropped)` - repo-relative paths, bounded, outside ones tokenised.

    THE REDACTION IS THE JOURNAL'S, not a second rule: this file is committed on
    purpose, and an absolute path in it names somebody's machine in a repository
    that goes to clients. `repo_relative_or_token` is where that question is
    already answered once."""
    kept = []
    for entry in (entries or [])[:MAX_PATHS]:
        kept.append(repo_relative_or_token(project, _path_of(entry)))
    return kept, max(0, len(entries or []) - MAX_PATHS)


def _mute_rows(project, mutes):
    """Mutes as a committed row keeps them: suite, bug and day, nothing else,
    cut at `MAX_PATHS`, each suite path redacted as `failingSuites` is and the
    bug and the day cut to the bound a runner string gets (`redacted_text`) -
    a manifest value is still a value this row did not compose."""
    if not isinstance(mutes, list):
        return []
    return [{"test": repo_relative_or_token(project, str(m.get("test"))),
             "bugId": redacted_text(project, str(m.get("bugId"))),
             "until": redacted_text(project, str(m.get("until")))}
            for m in mutes if isinstance(m, dict)][:MAX_PATHS]


def _step(project, step, published):
    """One step of the run, allow-listed - and its command decided, not copied.

    A COMMAND THE MANIFEST PUBLISHES IS STORED VERBATIM, and only that one. It is
    already committed in the plan, in plain text, so storing it exposes nothing
    new -- which is the third of the three tests `_journal_io` states for a field
    in a committed record. Anything else is an ad-hoc string this file has no
    claim about, so it gets the digest, byte length and program name that
    `command_facts` already produces for exactly this reason.
    """
    out = {}
    for key in STEP_KEYS:
        if key not in step:
            continue
        # `exit` and `ran` KEEP a None. `ran` is three-valued and its None means
        # "not knowable from this runner"; dropping the key would turn that into
        # "absent", which is the one reading a reader could mistake for zero.
        if step[key] is None and key not in ("exit", "ran"):
            continue
        if key in ("failing", "flaky"):
            # THE ONE FIELD WHOSE CONTENT A RUNNER WROTE, so both rules that keep
            # a committed row safe land here and nowhere else in this loop. The
            # cut is taken by the WRITER rather than trusted from the caller,
            # exactly as `_paths` takes `MAX_PATHS`; `redacted_text` is the
            # journal's own redactor, so an absolute path in a stack frame is
            # answered by the same map that answers one in `cwd`.
            out[key] = [redacted_text(project, line)
                        for line in step[key][:MAX_FAILING]]
            continue
        if key == "failingSuites":
            # THE SAME PAIR OF RULES, over a PATH rather than a line of prose:
            # bounded by `MAX_PATHS` (`run-test-gate.failing_suites` already
            # states its own cut in `failingSuitesBasis` when it truncates
            # there - this is the BACKSTOP, for a caller that did not), and
            # redacted through `repo_relative_or_token` exactly as `_paths`
            # redacts `treeMutated` and `overlap` - this row is committed, and
            # an absolute suite path names somebody's machine.
            out[key] = [repo_relative_or_token(project, p)
                        for p in step[key][:MAX_PATHS]]
            continue
        if key == "muted":
            out[key] = _mute_rows(project, step[key])
            continue
        if key == "outcomeBasis":
            # WHY THIS `could-not-run` STEP HAS NO VERDICT, bounded and
            # redacted exactly as `failing`'s lines are: a no-verdict
            # signature or a derived-gap sentence is built out of a runner's
            # own printed bytes or a phase's own suite names, and this row is
            # committed - so it gets `redacted_text`'s bound the same way
            # `failing` gets it, rather than being trusted whole from the
            # caller.
            out[key] = redacted_text(project, str(step[key]))
            continue
        if key == STEP_REUSED_KEY:
            source = step[key] if isinstance(step[key], dict) else {
                "runId": step[key]}
            out[key] = dict((k, str(source[k])) for k in ("runId", "ts")
                            if source.get(k) is not None)
            continue
        out[key] = step[key]
    # A REPEATED STEP RAN NOTHING HERE, so this row holds no duration for it:
    # the time is its source run's, and that row keeps it.
    if step_repeated(out):
        out.pop("durationMs", None)
    command = step.get("command")
    if command is None:
        return out
    if str(command) in set(str(c) for c in (published or [])):
        out["command"] = str(command)
    else:
        out.update(command_facts(str(command)))
    return out


def _miss_row(project, miss):
    """One selection miss as a committed row keeps it - see `row_for`."""
    phases = [str(p) for p in (miss.get("phases") or [])]
    sources = [str(p) for p in (miss.get("sources") or [])]
    out = {"test": repo_relative_or_token(project, str(miss.get("test"))),
           "phases": phases[:MAX_PATHS],
           "sources": [repo_relative_or_token(project, p)
                       for p in sources[:MAX_PATHS]]}
    if len(phases) > MAX_PATHS:
        out["phasesDropped"] = len(phases) - MAX_PATHS
    if len(sources) > MAX_PATHS:
        out["sourcesDropped"] = len(sources) - MAX_PATHS
    return out


# --- a follower a gate step owes ---------------------------------------------
# A file a change cannot avoid editing although no task names it: the module map
# a new import moves, a committed page a fresh render no longer matches. The step
# whose check finds it stale prints ONE line - the mark, then a JSON object - and
# the gate runner reads that line, never the check's prose, into `followersOwed`.
# Both halves live here, so the line a producer prints and the reader that parses
# it cannot drift apart: a producer prints `follower_line`.
#
# A `recipe` of None is a follower only a hand can repair (a published pin);
# `needsBrowser` marks a recipe the drive prints as an instruction rather than
# runs. A marked line that does not parse is counted (`followersUnread`), so a
# malformed line is never read as "nothing owed".
FOLLOWERS_KEY = "followersOwed"
FOLLOWER_MARK = "FOLLOWER-OWED"
_FOLLOWER_LINE = re.compile(r"^\s*%s (.*?)\s*$" % (FOLLOWER_MARK,), re.M)


# --- which declared files a task's run reached --------------------------------
# The keys a row carries `run-test-gate.gate_reach`'s observation under:
# `{gaps: [{path, why, cause?, suites}]}` for each declared file no suite of the
# run reaches, or the sentence saying the reading failed. The reading is the
# gate's; this is what a committed row keeps of it. A repeated verdict carries
# the row it repeats' reading (`run-test-gate.reused_result`), through this
# same shape again.
#
# EVERY FIELD OF IT IS BOUNDED, for the reason `MAX_FAILING` states: a row is
# hash-chained, so an unbounded field is a row of unbounded size. The gaps and
# each gap's suites are path lists, cut at `MAX_PATHS` with the cut counted
# beside the list (`gapsDropped`, `suitesDropped`); each path is redacted as
# `_paths` redacts one; each reason goes through `redacted_text`, which bounds
# it - `why`, the fixed clause, and `cause`, the varying part of a widening's
# reason, each on its own, so the clause never spends the cause's bound. The
# run's step names are not copied onto it: `steps[].name` holds them.
GATE_REACH_KEY = "gateReach"
GATE_REACH_NOT_ASKED_KEY = "gateReachNotAsked"


def _dropped(value):
    """A cut count a caller already took - a non-negative int, else 0."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


def _reach_gap(project, gap):
    """One gap as a row keeps it - see `gate_reach_record`."""
    suites = [str(s) for s in gap.get("suites") or []]
    out = {"path": repo_relative_or_token(project, str(gap.get("path") or "")),
           "why": redacted_text(project, str(gap.get("why") or "")),
           "suites": [repo_relative_or_token(project, s)
                      for s in suites[:MAX_PATHS]]}
    # The varying part of a reason, bounded on its own so the fixed clause in
    # `why` never spends its bound.
    if gap.get("cause") is not None:
        out["cause"] = redacted_text(project, str(gap["cause"]))
    dropped = (_dropped(gap.get("suitesDropped"))
               + max(0, len(suites) - MAX_PATHS))
    if dropped:
        out["suitesDropped"] = dropped
    return out


def gate_reach_record(project, reach):
    """A run's reach in the bounded shape a row keeps; None for a shape that is
    not the reading's. ONE SHAPE FOR EVERY READER: `run-test-gate` puts this on
    the result `--json` prints, and `row_for` takes it again as the backstop
    for a caller that did not, which changes nothing it already bounded."""
    if not isinstance(reach, dict):
        return None
    gaps = [g for g in reach.get("gaps") or [] if isinstance(g, dict)]
    out = {"gaps": [_reach_gap(project, g) for g in gaps[:MAX_PATHS]]}
    dropped = (_dropped(reach.get("gapsDropped"))
               + max(0, len(gaps) - MAX_PATHS))
    if dropped:
        out["gapsDropped"] = dropped
    return out

# --- a red read against its base ---------------------------------------------
# The key a row carries `run-test-gate.base_red`'s reading under, and the fields
# that cross: the reading is the gate's, this is only what a committed row keeps.
BASE_RED_KEY = "baseRed"
_BASE_RED_WORDS = ("run", "head", "task", "verdict")

# A run of a recorded task run's red steps at that run's base commit, in a tree
# of its own (`run-test-gate.py --base-of`): its row is filed under this scope
# and names the run it measured for under `BASE_OF_KEY`. It is no subject's
# evidence - `subject_key` gives it none, so no pointer is ever written for it
# or reconciled onto it - and it is read only as a base, by `base_run`.
BASE_SCOPE = "base"
BASE_OF_KEY = "baseOf"


def same_head(one, other):
    """Two spellings of one commit: a short and a full sha agree on a prefix
    of at least seven characters, which is as short as git abbreviates."""
    one, other = str(one or "").strip(), str(other or "").strip()
    return (len(one) >= 7 and len(other) >= 7
            and (one.startswith(other) or other.startswith(one)))


# The digest `_tree_stamp.dirty_digest` writes for a status holding no dirty
# line: its one spelling, `_journal_io.canonical`, of an empty list. Spelled
# here because the two modules are layer-mates; a case pins it to the value
# the producer writes, with and without a recorder exclusion.
CLEAN_DIRTY_DIGEST = "sha256:" + hashlib.sha256(
    _journal_io.canonical([]).encode("utf-8")).hexdigest()


def tested_tree_clean(state):
    """Whether a row's `testedState` says the tree it tested WAS its HEAD
    commit: git described no dirty path before the run, after whatever
    recorder exclusion the row was taken with. A row with no digest is not
    clean - nothing says what its tree held."""
    return (isinstance(state, dict)
            and state.get("dirtyDigest") == CLEAN_DIRTY_DIGEST)


def base_run(rows, head, exclude_tasks=(), names=None, suites=None):
    """The newest recorded run that tested commit `head` itself, or None when
    the ledger holds none.

    A RUN AT THAT HEAD IS NOT ENOUGH: a task gate runs on HEAD plus the task's
    uncommitted work, so its red may be that work's. Only a row whose tested
    tree was clean (`tested_tree_clean`) measured the commit. The runs of
    every task in `exclude_tasks` are passed over too - a task's own run is
    not independent evidence about its base - and, when `names` is given, so
    is a run that ran no step of those names and no step over any of
    `suites` (`step_runs_suite`): a derived step's name carries its suite
    list, so a base run spells the same suites under another name."""
    wanted = None if names is None else set(names)
    over = set(suites or ())
    skip = set(str(t) for t in exclude_tasks or ())
    return newest_row([
        row for row in rows or [] if isinstance(row, dict)
        and same_head((row.get("testedState") or {}).get("head"), head)
        and tested_tree_clean(row.get("testedState"))
        and str(row.get("taskId") or "") not in skip
        and (wanted is None or any(
            isinstance(st, dict) and (st.get("name") in wanted or any(
                step_runs_suite(st, suite) for suite in over))
            for st in row.get("steps") or []))])


def step_answered(step):
    """Whether a recorded step reached a verdict a reader may compare: an exit
    the runner reported (an int, zero or above), and no no-verdict `outcome`.
    A step that timed out, was killed by a signal (a negative exit) or left no
    exit measured nothing, so it answers for nothing at base."""
    if not isinstance(step, dict) or step.get("outcome"):
        return False
    reported = step.get("exit")
    return (isinstance(reported, int) and not isinstance(reported, bool)
            and reported >= 0)


def base_step(base_steps, step):
    """The base run's step answering for `step`: the same name and, where both
    carry the command verbatim, the same command - a renamed command is another
    check, whatever its key - and one that answered (`step_answered`): a base
    step with no verdict measured nothing, and is never read as green there."""
    for st in base_steps or []:
        if not isinstance(st, dict) or st.get("name") != step.get("name") \
                or not step_answered(st):
            continue
        if st.get("command") and step.get("command") \
                and str(st["command"]) != str(step["command"]):
            continue
        return st
    return None


def base_row_for(red, head, task_id, rows):
    """The run `base_run` reads the red steps `red` against at commit `head`:
    asked for by every red step's name and, for a joined step, by its declared
    entry's name and the suites its affected parts named failing, as a derived
    step's suites find a base. The one selection the base reading
    (`run-test-gate.base_red`) and `base_unmeasured` both make."""
    suites = [suite for st in red if step_parts(st.get("name"))[1]
              for suite in named_failing_suites([st])]
    names = [st.get("name") for st in red]
    names += [head_of for head_of, parts in
              (step_parts(st.get("name")) for st in red)
              if head_of is not None and parts and head_of not in names]
    return base_run(rows, head, [task_id], names, suites=suites)


def base_unmeasured(steps, head, task_id, rows):
    """The red steps of `steps` - a step's name, or `<name>: <suite>` for a
    suite of a derived or joined step - that no clean-tree run at commit
    `head` measured, read off the one run the base reading reads
    (`base_row_for`), the way it reads them: a step it has under the same
    name (`base_step`) is measured; a derived or joined step's suite is
    measured where a step of that run is known to have run it
    (`step_runs_suite`) - in either case only a base step that answered
    (`step_answered`). Every red step when no such run is recorded, `[]`
    when every one is measured, None when nothing in `steps` is red.

    THE QUESTION A BASE RUN ANSWERS, asked before one is started: a commit
    and step set measured once is not measured again, since a second run of
    the same steps on the same commit's clean tree measures the same thing."""
    red = [st for st in steps or [] if isinstance(st, dict)
           and _counts_as_failed(st)]
    if not red:
        return None
    base = base_row_for(red, head, task_id, rows) if head else None
    if base is None:
        return [str(st.get("name")) for st in red]
    base_steps = [st for st in base.get("steps") or [] if step_answered(st)]
    out = []
    for step in red:
        if base_step(base_steps, step) is not None:
            continue
        declared, derived = step_parts(step.get("name"))
        named = named_failing_suites([step])
        if not ((is_derived_step(step.get("name")) or derived) and named):
            out.append(str(step.get("name")))
            continue
        listed = derived_step_suites(step.get("name"))
        for suite in named:
            if derived and declared is not None \
                    and resolve_named(suite, listed)[0] is None:
                answered = base_step(base_steps, {"name": declared}) is not None
            else:
                answered = any(step_runs_suite(st, suite) for st in base_steps)
            if not answered:
                out.append("%s: %s" % (step.get("name"), suite))
    return out


def step_runs_suite(step, suite):
    """Whether a recorded step is known to have run `suite`: its runner named
    the suite as failing, or a derived step's name lists it - the step's own,
    or one a joined step carries (`derived_step_suites`). A declared step that
    names no such suite may have run it green or not at all, and the row cannot
    say which; a joined step's declared entry is such a step."""
    if not isinstance(step, dict):
        return False
    named = (NAMED_FAILING in (step.get("failingSuitesBasis") or "")
             and suite in (step.get("failingSuites") or []))
    return named or suite in derived_step_suites(step.get("name"))


def _base_red(project, found):
    """`found` as a row keeps it: words as strings, suite paths bounded and
    redacted as `failingSuites` is, sentences redacted as a basis is."""
    out = dict((k, str(found[k])) for k in _BASE_RED_WORDS
               if found.get(k) is not None)
    for key in ("atBase", "introduced"):
        out[key] = [repo_relative_or_token(project, str(p))
                    for p in (found.get(key) or [])[:MAX_PATHS]]
    out["unknown"] = [redacted_text(project, str(t))
                      for t in (found.get("unknown") or [])[:MAX_PATHS]]
    if found.get("basis") is not None:
        out["basis"] = redacted_text(project, str(found["basis"]))
    return out


# --- a base run, kept with the reading of the red it measured ------------------
# THE BASE RUN LIVES WHERE THE RED'S READING LIVES. A red task run's reading
# against its base (`BASE_RED_KEY`) is on that run's record in the plan, and it
# names the base commit (`head`); the clean-tree runs of that commit a base
# measurement took for it are kept beside the reading, under `BASE_RUNS_KEY`, so
# they survive wherever the plan does - a ledger row is only another copy. The
# one reader (`read_rows`, through `records_of_bodies`) gives each back as the
# `BASE_SCOPE` row it was recorded as, so `base_run` finds it exactly as it
# found that row, and a later red of the subject at the same commit is read
# against it with nothing measured again. The record that replaces a red's
# carries the runs while its own reading names the same commit
# (`carry_kept_bases`), and drops them once the subject's run is at another
# commit or green - neither has a red those runs could answer for.
BASE_RUNS_KEY = "baseRuns"
# How many base runs one reading keeps, the newest: one per step set a red at
# that commit was measured for, and a red of a new step set evicts the oldest,
# whose steps are then measured again if a red asks for them.
MAX_KEPT_BASE_RUNS = 2
# What a kept base run holds - every field `base_run`, the base reading and the
# time record's base stage read off a base row - and nothing a record of a
# subject's own run holds for other readers.
_KEPT_BASE_KEYS = ("runId", "at", "status", "durationMs", STARTED_KEY,
                   BASE_OF_KEY, "testedState", "steps", "stepsDropped")


def kept_base(row):
    """The base run `row` (a `BASE_SCOPE` row, `row_for`'s shape) as a reading
    keeps it: its record (`_record_of`) cut to `_KEPT_BASE_KEYS`."""
    record = _record_of(row)
    return dict((k, record[k]) for k in _KEPT_BASE_KEYS
                if record.get(k) is not None)


def kept_bases(reading):
    """The base runs a reading keeps, each a dict naming its run; [] for a
    reading that keeps none or is not one."""
    if not isinstance(reading, dict):
        return []
    return [r for r in reading.get(BASE_RUNS_KEY) or []
            if isinstance(r, dict) and r.get("runId")]


def with_kept_bases(reading, bases):
    """`reading`, a NEW dict, keeping the runs of `bases` that measured its own
    base commit - one per run, a later copy winning, the newest
    `MAX_KEPT_BASE_RUNS` - and no `BASE_RUNS_KEY` when none did."""
    head = reading.get("head")
    by_run = {}
    for base in bases or []:
        if isinstance(base, dict) and base.get("runId") and same_head(
                (base.get("testedState") or {}).get("head"), head):
            by_run.pop(str(base["runId"]), None)
            by_run[str(base["runId"])] = base
    out = dict((k, v) for k, v in reading.items() if k != BASE_RUNS_KEY)
    keep = list(by_run.values())[-MAX_KEPT_BASE_RUNS:]
    if keep:
        out[BASE_RUNS_KEY] = keep
    return out


def carry_kept_bases(record, replaced):
    """`record`, the record about to replace `replaced`, carrying the base runs
    `replaced`'s reading keeps that measured `record`'s own base commit
    (`with_kept_bases`) - a NEW dict, cut and shared again as a plan holds a
    record (`finished_record`). `record` as it is when it reads no red against
    a base, or nothing is carried."""
    old = kept_bases((resolved_shared(replaced) or {}).get(BASE_RED_KEY)
                     if isinstance(replaced, dict) else None)
    mine = resolved_shared(record) if isinstance(record, dict) else None
    reading = (mine or {}).get(BASE_RED_KEY)
    if not old or not isinstance(reading, dict) or not reading.get("head"):
        return record
    carried = with_kept_bases(reading, old + kept_bases(reading))
    if carried == reading:
        return record
    return finished_record(dict(mine, **{BASE_RED_KEY: carried}),
                           RECORD_MAX_BYTES)


def keep_base(project, manifest_path, red, base, session_id=None, wait=None,
              config=None):
    """Keep the base run `base` (its `BASE_SCOPE` row) on the record of the
    red task run `red` measured it for - the subject's newest record, whose
    reading names the same base commit, under `BASE_RUNS_KEY` - in one write
    of the shard under the plan-file lock (`write_plan_file`).
    `{"written", "reason", "path"}`: `reason` says why nothing was kept - the
    red names no task, the subject's newest run reads no red against that
    commit (it moved on, or went green), or the lock was not free.

    Waited for as a record write is (`RECORD_WAIT_SECONDS`): the base run is
    the only measurement of its commit a plan with no ledger holds."""
    ids = {"taskId": (red or {}).get("taskId"),
           "phaseId": (red or {}).get("phaseId")}
    if not ids["taskId"] or not ids["phaseId"]:
        return {"written": False, "path": None,
                "reason": "the red run %s names no task and phase, so no record "
                          "holds its reading" % ((red or {}).get("runId"),)}
    path, sharded = _phase_file(manifest_path, ids["phaseId"])
    if not path or not os.path.exists(path):
        return {"written": False, "path": None,
                "reason": "no phase %r in this manifest" % (ids["phaseId"],)}
    kept = kept_base(base)
    at = (kept.get("testedState") or {}).get("head")

    def change(body):
        subject, _task, problem = _holders(body, "task", ids, sharded)
        if problem is not None:
            return None, problem, None
        record = resolved_shared(subject.get(RECORD_KEY))
        reading = (record or {}).get(BASE_RED_KEY)
        if not isinstance(reading, dict) or not same_head(reading.get("head"),
                                                           at):
            return None, ("%s's newest run (%s) reads no red against base %s, "
                          "so the base run %s is kept on no record"
                          % (ids["taskId"], (record or {}).get("runId"), at,
                             kept.get("runId"))), None
        subject[RECORD_KEY] = finished_record(dict(record, **{
            BASE_RED_KEY: with_kept_bases(reading, kept_bases(reading)
                                          + [kept])}), RECORD_MAX_BYTES)
        return body, None, subject[RECORD_KEY]
    got = write_plan_file(
        project, path, change, "keeping a base run", session_id=session_id,
        wait=RECORD_WAIT_SECONDS if wait is None else wait,
        outcome="the base run was kept on no record",
        repair="the next red at that commit measures its base again",
        config=config)
    return {"written": got["written"], "reason": got["reason"],
            "path": got["path"]}


def follower_line(path, recipe, owner, needs_browser=False):
    """The one line a step prints for a follower it owes."""
    record = {"path": path, "recipe": recipe, "owner": owner}
    if needs_browser:
        record["needsBrowser"] = True
    return "%s %s" % (FOLLOWER_MARK, json.dumps(record, sort_keys=True))


def _follower(record):
    """`record` as a row keeps it, or None when it is not a follower record."""
    if not isinstance(record, dict):
        return None
    path, recipe, owner = (record.get(k) for k in ("path", "recipe", "owner"))
    if not (isinstance(path, str) and path and isinstance(owner, str) and owner
            and (recipe is None or isinstance(recipe, str) and recipe)):
        return None
    out = {"path": path, "recipe": recipe, "owner": owner}
    if record.get("needsBrowser") is True:
        out["needsBrowser"] = True
    return out


def followers_in(text):
    """`(records, unread)` - every follower line in `text`, distinct, in the
    order printed, and how many marked lines were not a follower record."""
    records, unread = [], 0
    for found in _FOLLOWER_LINE.finditer(text or ""):
        try:
            record = _follower(json.loads(found.group(1)))
        except ValueError:
            record = None
        if record is None:
            unread += 1
        elif record not in records:
            records.append(record)
    return records, unread


# The steps that answer, by path, for the followers they own: each is run from
# the root of the tree asked, as `<script> --follower-for <path>...`, and prints a
# follower line for every path it owns and nothing for the rest. Asked by
# command, never imported, so the tree's own copy answers and a script the tree
# does not hold is no owner there.
FOLLOWER_OWNERS = ("tools/lints/_deps.py", "tools/check-rendered-artifacts.py",
                   "tools/capture-screenshots.mjs")
# A recipe is a regeneration, not a suite: bounded so a hung one ends the run.
RECIPE_TIMEOUT = 600


def claimed_followers(root, paths):
    """Every follower record an owner gives for one of `paths`, each
    `FOLLOWER_OWNERS` script `root` holds asked by command - an owner that
    cannot be asked claims nothing. The one reading of who owns a path: the
    integration reproduces what is claimed (`integrate-task.py`), and the drive
    leaves a claimed path to that integration rather than asking about it
    before the review (`drive-phase.py` `stray_step`).

    NAMED FOR WHAT IT RETURNS, never with a reporting suffix: `prove-gates.py`
    derives every public function whose name ends in a reporting shape
    (`_GATE_SHAPES`) as a lint owed a proving row, and its `NOT_A_GATE` table
    cannot excuse a name that arm reaches."""
    records = []
    for rel in FOLLOWER_OWNERS:
        script = os.path.join(root, rel)
        runner = sys.executable if rel.endswith(".py") else shutil.which("node")
        if not (runner and os.path.isfile(script)):
            continue
        try:
            done = subprocess.run([runner, script, "--follower-for"] + list(paths),
                                  cwd=root, capture_output=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            continue
        said = followers_in(done.stdout.decode("utf-8", "replace"))[0]
        records += [r for r in said if r["path"] in paths and r not in records]
    return records


def run_recipe(recipe, cwd):
    """`(code, said)` of a follower's recipe run in `cwd`: code None when it
    could not run at all, `said` the texts that say why it failed."""
    try:
        done = subprocess.run(recipe, shell=True, cwd=cwd, capture_output=True,
                              timeout=RECIPE_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, ("%s" % (exc,),)
    return done.returncode, tuple(s.decode("utf-8", "replace")
                                  for s in (done.stderr, done.stdout))


def row_for(project, result, scope, ids, identity, published=None):
    """One evidence row: what ran, what it answered, whose run it was, and which
    declaration the run was measured against.

    `result` is `run-test-gate.run_gate`'s dict. Only the fields named here cross
    into the row; an inventive caller cannot widen it, which is the same rule
    `_journal_io._normalise` applies to a journal row and for the same reason.
    """
    result = result if isinstance(result, dict) else {}
    ids = ids if isinstance(ids, dict) else {}
    identity = identity if isinstance(identity, dict) else {}
    steps = [s for s in (result.get("steps") or []) if isinstance(s, dict)]
    mutated, mut_dropped = _paths(project, result.get("treeMutated"))
    coverage, cov_dropped = _paths(project, result.get("overlap"))
    state = result.get("testedState") if isinstance(
        result.get("testedState"), dict) else {}
    row = {
        "v": ROW_VERSION,
        "runId": str(identity.get("runId") or ""),
        "ts": str(identity.get("ts") or _utc_stamp.utc_stamp()),
        "scope": str(scope or ""),
        "status": result.get("status"),
        "durationMs": result.get("durationMs"),
        "failed": list(result.get("failed") or []),
        "steps": [_step(project, s, published) for s in steps[:MAX_STEPS]],
        "testedState": dict((k, state.get(k)) for k in STATE_KEYS if k in state),
        "observations": {
            "ranTotal": result.get("ranTotal"),
            "countsBasis": result.get("countsBasis"),
            "treeMutated": None if result.get("treeMutated") is None else mutated,
            "treeBasis": result.get("treeBasis"),
            "coverage": None if result.get("overlap") is None else coverage,
            # THE ONE BASIS SENTENCE A RUNNER'S OUTPUT REACHES, and therefore
            # the one that needs the journal's redactor. `treeBasis`,
            # `countsBasis` and the rest are composed here out of counts this
            # plugin took; this one ends in a sample of the paths the runner
            # PRINTED, so on a project whose suite reports absolute paths the
            # row was carrying somebody's home directory into a committed,
            # hash-chained file. `_paths` beside it has answered that question
            # for the path LIST since it existed; the sentence went unredacted
            # because it is a sentence. `redacted_paths` and not
            # `redacted_text`: the bound belongs to a journal value, and every
            # other basis on this row is stored whole.
            "coverageBasis": (
                None if result.get("coverageBasis") is None
                else redacted_paths(project, result.get("coverageBasis"))),
        },
    }
    # THE THIRD PLACE'S OWN OBSERVATION, WRITTEN ONLY WHEN A CALLER MEASURED IT.
    # `full_status`'s `_full_disqualification` reads its ABSENCE as "cannot be
    # told clean", which is a different claim from an empty list ("measured,
    # and nothing was dirty") - so this key is added only when
    # `run-test-gate.py`'s `--full` path actually computed it, exactly as
    # `treeMutated`/`overlap` above are bounded and repo-relative rather than
    # absolute paths naming somebody's machine in a committed file.
    if result.get("dirtyOutside") is not None:
        dirty, dirty_dropped = _paths(project, result.get("dirtyOutside"))
        row["observations"]["dirtyOutside"] = dirty
        if dirty_dropped:
            row["dirtyOutsideDropped"] = dirty_dropped
    # THE BASIS FOR THE ONE STATUS WORD THAT HAS NO OTHER. `failed` is read back
    # off the steps, `timed-out` off a step's `outcome` and its `timeoutSeconds`,
    # `no-checks` off `ranTotal`, `gate-mutated` off `observations.treeMutated`
    # plus the declared-count sentence `treeBasis` carries whenever anything moved
    # -- but a run stopped by a signal keeps only the steps that FINISHED, so
    # nothing else on the row would say what happened to the rest. Written only
    # when there is something to write: a key present on every row could not be
    # told from one a build does not produce.
    #
    # SO `gate-mutated` NEEDED NO FOURTH FIELD, and that is a finding rather than
    # an omission. The word says the gate rewrote files the work under test
    # declares; `treeMutated` already holds every path that moved and `treeBasis`
    # already ends with either "N of M changed path(s) are declared by the work
    # under test" or the sentence saying no ownership could be sorted, which are
    # exactly the two ways `run_status` reaches the word. A `treeMutatedOwned` key
    # here would be a second copy of a claim the row can already be read for, and
    # this file's rule about a cached count applies to a cached classification
    # just as well.
    if isinstance(result.get(BANNERS_KEY), list):
        row[BANNERS_KEY] = banners_of(result)
    if result.get("cancelledBy") is not None:
        row["cancelledBy"] = str(result["cancelledBy"])
    # ...AND THE SECOND SUCH WORD, FOR THE SAME REASON AND NOT BY ANALOGY. A
    # `could-not-run` reached because the tree was ALREADY dirty outside the
    # declared scope is the one member of that class the row cannot be read back
    # for: `steps[].outcome` carries the two members a step observes, `ran` and
    # `measured` carry the zero, but the state that excused the red was in a
    # `git status` snapshot taken before the first command and nothing else here
    # holds it -- `testedState.dirtyBasis` counts those paths without saying
    # whose they were. So the sentence crosses, bounded, exactly as
    # `run-test-gate.render` prints it; the raw path list does not, which is the
    # division `treeBasis` already makes for the ownership split. Written only
    # when there is something to write, like the key above it.
    if result.get("attributionBasis") is not None:
        row["attributionBasis"] = str(result["attributionBasis"])
    # THE FOLLOWERS A STEP SAID IT OWES (`followers_in`), the one record the drive
    # regenerates or widens from. Both strings went through a runner's output, so
    # both are redacted as a basis is; written only when a step named one.
    owed = [f for f in (_follower(f) for f in result.get(FOLLOWERS_KEY) or [])
            if f is not None][:MAX_PATHS]
    if owed:
        row[FOLLOWERS_KEY] = [dict(f, path=redacted_paths(project, f["path"]),
                                   recipe=None if f["recipe"] is None
                                   else redacted_paths(project, f["recipe"]))
                              for f in owed]
    if result.get("followersUnread"):
        row["followersUnread"] = int(result["followersUnread"])
    # A RED READ AGAINST THE RUN RECORDED AT ITS BASE (`run-test-gate.base_red`):
    # which base run, and which suites it charges to the base and which to the
    # work. Suite paths are bounded and redacted as `failingSuites` is, the
    # sentences as a basis is; written only when a red was read that way.
    if isinstance(result.get(BASE_RED_KEY), dict):
        row[BASE_RED_KEY] = _base_red(project, result[BASE_RED_KEY])
    # WHICH DECLARED FILES NO SUITE OF THE RUN REACHED (`run-test-gate.gate_reach`),
    # or why that was not read. Written only when the run read it, so a row
    # from a run that never asked holds no key a reader could take for "every
    # file reached" - `[]` gaps is that answer, recorded.
    reach = gate_reach_record(project, result.get(GATE_REACH_KEY))
    if reach is not None:
        row[GATE_REACH_KEY] = reach
    if result.get(GATE_REACH_NOT_ASKED_KEY) is not None:
        row[GATE_REACH_NOT_ASKED_KEY] = redacted_text(
            project, str(result[GATE_REACH_NOT_ASKED_KEY]))
    # THE MUTES THAT EXCUSED A FAILING STEP. The step itself keeps its exit and
    # its failing names, so without this a `passed` beside a red step would be
    # a verdict the row cannot be read back for. Allow-listed to the suite,
    # the bug and the day, cut at `MAX_PATHS` and each suite path redacted as
    # `failingSuites` is; written only when a mute was honoured.
    muted = _mute_rows(project, result.get("muted"))
    if muted:
        row["muted"] = muted
    # WHERE THE `steps` LIST CAME FROM. `steps` names the entries that
    # executed and carries no declaration beside them, and the manifest that
    # declared them is not on the row -- so two rows with different `steps` differ
    # either because the tasks differ or because one was measured by its own
    # `tests.gate` and the other fell back to the phase's `testGate`, and nothing
    # else here separates those.
    #
    # `scope` IS NOT THAT ANSWER, WHICH IS THE WHOLE REASON THIS IS A FIELD.
    # `scope`'s published meaning is the POINTER SUBJECT: `latest_by_subject` keys
    # by it, `_set_pointer`, `_current_pointer` and `reconcile` all branch on it to
    # choose a task or a phase, and `_status_facts.evidence_row` reads it as a
    # subject scope. `run-test-gate._record_run` happens to pass ONE value into
    # both questions, so the two strings are equal at that call site and nowhere by
    # contract -- and the second writer of this function already computes its
    # entries as `task.tests.gate or phase.testGate` while labelling every such row
    # `scope: "task"`. A reader recovering provenance from `scope` would be reading
    # a field whose contract is something else, and on a fallback run it reads
    # `phase` beside a `taskId`, which is a shape two opposite readings both fit.
    if result.get("gateSource") is not None:
        row["gateSource"] = str(result["gateSource"])
    # THE OTHER PHASES A GROUP'S ONE RUN OWNED (`run-test-gate.py --also`). Written
    # only for a group run, so a row that carries none is a run for its subject
    # alone - which is what a member's copied pointer is checked against.
    if isinstance(result.get("groupWith"), list) and result["groupWith"]:
        row["groupWith"] = [str(p) for p in result["groupWith"]]
    # THE TASK RUN A BASE RUN MEASURED FOR, on a `BASE_SCOPE` row alone.
    if result.get(BASE_OF_KEY):
        row[BASE_OF_KEY] = str(result[BASE_OF_KEY])
    # WHAT THE GATE WAS, resolved: a digest of every entry beside the command it
    # resolves to (`gate_digest`), so a reader can tell a gate whose entries kept
    # their names while `meta.buildCommands` changed what they run. Written only
    # when the writer computed one.
    if result.get(GATE_DIGEST_KEY) is not None:
        row[GATE_DIGEST_KEY] = str(result[GATE_DIGEST_KEY])
    # WHAT THIS RUN LEFT TO THE PHASE GATE (`LEFT_TO_PHASE_GATE_KEY`): the
    # fields `LEFT_TO_PHASE_GATE_FIELDS` names per entry and nothing else, cut
    # at `MAX_STEPS` as `steps` is.
    # Written only when the run left something out, so a run under an absent
    # or empty `executor.phaseGateOnly` writes the row it always wrote.
    left = [e for e in (result.get(LEFT_TO_PHASE_GATE_KEY) or [])
            if isinstance(e, dict)][:MAX_STEPS]
    if left:
        row[LEFT_TO_PHASE_GATE_KEY] = [
            dict((k, str(e[k])) for k in LEFT_TO_PHASE_GATE_FIELDS
                 if e.get(k) is not None) for e in left]
    # THE IDENTITY THE NEXT RUN COMPARES ITSELF AGAINST. It is not derivable from
    # anything else on the row and it never will be: `testedState` holds a digest
    # of WHICH paths were dirty, which is silent about their contents, so a
    # reader trying to recover this from the row would recover a different
    # question's answer. Written only when the writer computed one - a tree git
    # would not describe has no identity, and a null here would compare equal to
    # the next null and read as agreement.
    if result.get(REUSE_KEY) is not None:
        row[REUSE_KEY] = str(result[REUSE_KEY])
    # ...AND WHETHER THIS ROW IS A MEASUREMENT AT ALL. A row that repeats an
    # earlier verdict says so and names the run it repeats, so no reader meets a
    # verdict without meeting the run that took it. `status` and `failed` are
    # COPIED onto such a row on purpose, which is the one place this file's rule
    # against a cached claim yields: the source is named right here, so the copy
    # is checkable rather than free-floating, and a row whose `status` were
    # absent could not be rendered by any surface that reads one.
    if result.get(VERDICT_SOURCE) is not None:
        row[VERDICT_SOURCE] = str(result[VERDICT_SOURCE])
    prior = result.get("reusedFrom")
    if isinstance(prior, dict) and prior.get("runId"):
        row["reusedFrom"] = dict(
            (key, str(prior[key])) for key in ("runId", "ts", "status")
            if prior.get(key) is not None)
    for key in ("taskId", "phaseId"):
        if ids.get(key) is not None:
            row[key] = str(ids[key])
    for key in ("attempt", "via", "sessionId"):
        if identity.get(key) is not None:
            row[key] = identity[key]
    # WHO RAN IT AND WHEN IT BEGAN, both off `identity` and both written only when
    # the caller supplied one. A `runner` defaulted to "gate" on every row would
    # make a row the wrapper measured indistinguishable from a row nobody labelled,
    # which is the distinction the key exists to draw; `RUNNER_KEY`'s note says why
    # ABSENT is already the right answer for the gate. An unknown word is written
    # through unchanged rather than corrected: this file records what it was told,
    # and `runner_of` is where a word outside the vocabulary is reported.
    if identity.get(RUNNER_KEY) is not None:
        row[RUNNER_KEY] = str(identity[RUNNER_KEY])
    if identity.get(STARTED_KEY) is not None:
        row[STARTED_KEY] = str(identity[STARTED_KEY])
    # THE LAUNCH TOKEN a caller that started the run in the background handed
    # it (`run-test-gate.py --launch`), on the row as on the record: the record
    # is replaced by the subject's next run, so a token kept there alone is
    # lost the moment another run of the subject records after this one, and
    # the caller could then never find the run it launched. Written only when
    # one was handed.
    if identity.get(LAUNCH_KEY):
        row[LAUNCH_KEY] = str(identity[LAUNCH_KEY])
    # WRITTEN ONLY WHEN THE RUN MEASURED ITS SELECTION, and only as a duration:
    # a written zero for a run that never timed it would read as a selection
    # that took no time. On the row before `append_row` hashes it, like every
    # key above.
    selection = selection_ms(result)
    if selection is not None:
        row[SELECTION_KEY] = selection
    # PRESENT ONLY WHEN SOMETHING WENT. A count that appears solely when non-zero
    # cannot be told from a count nobody computed, so its ABSENCE has to mean
    # "nothing was cut" and never "nobody looked".
    if steps[MAX_STEPS:]:
        row["stepsDropped"] = len(steps) - MAX_STEPS
    if mut_dropped:
        row["treeMutatedDropped"] = mut_dropped
    if cov_dropped:
        row["coverageDropped"] = cov_dropped
    # THE DERIVED GATE'S OWN TWO CLAIMS, ALLOW-LISTED LIKE EVERYTHING ELSE
    # HERE - an inventive caller handing this function an ad-hoc `result`
    # cannot widen the row by inventing a third key under either one.
    # `narrowed` is two counts and carries no path, so it needs no bound;
    # `shadow.missed` is a path list a runner's own output produced, so it
    # gets the SAME cut and the SAME redaction `treeMutated`/`overlap` get
    # above, through `_paths`.
    narrowed = result.get("narrowed")
    if isinstance(narrowed, dict):
        row["narrowed"] = {"listed": narrowed.get("listed"),
                           "full": narrowed.get("full")}
    shadow = result.get("shadow")
    if isinstance(shadow, dict):
        missed, missed_dropped = _paths(project, shadow.get("missed"))
        shadow_row = {"listed": shadow.get("listed"), "full": shadow.get("full"),
                      "missed": missed}
        if missed_dropped:
            shadow_row["missedDropped"] = missed_dropped
        row["shadow"] = shadow_row
    # THE FULL RUN'S SELECTION MISSES (`selection_miss`), allow-listed to
    # `{test, phases, sources}` (`_miss_row`): the suite and every source
    # are bare paths (never porcelain lines, so not through `_paths`),
    # redacted by `repo_relative_or_token`; the phase ids are plan ids. Every
    # list is cut at `MAX_PATHS` with its dropped count beside it -
    # `phasesDropped`, `sourcesDropped`, `selectionMissDropped` - each
    # present only when something was cut. Written only when there is a
    # miss - absence is "none".
    misses = result.get("selectionMiss")
    misses = ([m for m in misses if isinstance(m, dict)]
              if isinstance(misses, list) else [])
    if misses:
        row["selectionMiss"] = [_miss_row(project, m)
                                for m in misses[:MAX_PATHS]]
        if len(misses) > MAX_PATHS:
            row["selectionMissDropped"] = len(misses) - MAX_PATHS
    # The three-valued fields keep their shape at the TOP level too, so a reader
    # that never opens `observations` still cannot mistake unknown for clean.
    row["treeMutated"] = row["observations"]["treeMutated"]
    return row


# --- a stored verdict, read against what its gate is now ----------------------
# A caller that keeps a run's verdict past the moment it was taken - a decision
# waiting on a human, a green the next step will close on - shows it later, and by
# then the gate may resolve to another command or the work may have changed. The
# words `stored_verdict_moved` answers with: the basis holds, it moved (so the
# verdict describes another gate or another tree and is measured again), or it
# could not be established either way (said, never read as agreement).
STORED_HOLDS = "holds"
STORED_MOVED = "moved"
STORED_UNKNOWN = "unknown"


def tree_key(tree):
    """A short, stable name for a measured tree that is not the project - never
    its path, which names a machine, and a row is committed. The only
    spelling: `run-test-gate` writes `testedState.tree.key` through this
    function, and the stored-verdict comparison reads it back through it."""
    return hashlib.sha1(os.path.realpath(tree).encode("utf-8")).hexdigest()[:12]


def measured_row(rows, row):
    """The row that measured what `row` says: `row` itself, or the run a repeated
    verdict repeats (`reusedFrom`), newest by moment - None when that run is not
    in `rows`, since a repeat whose source is gone names no tree. A
    `PART_REUSED` row is its own answer: it read the tree itself, before the
    steps it measured."""
    if not isinstance(row, dict) or row.get(VERDICT_SOURCE) != REUSED:
        return row if isinstance(row, dict) else None
    return row_by_run(rows, (row.get("reusedFrom") or {}).get("runId"))


def red_step_names(row):
    """The names of the steps a row recorded that did not exit 0, in step order:
    a failure and a step that reached no verdict alike, since both are what a
    rerun is asked over."""
    return [str(s.get("name")) for s in (row or {}).get("steps") or []
            if isinstance(s, dict) and s.get("exit") != 0]


def stored_verdict_moved(rows, run_id, now):
    """`(word, why)` - whether the verdict run `run_id` recorded still answers
    the gate as it resolves now. `now` is what the caller reads at this moment:
    `gateDigest` (`gate_digest` over the entries and `meta.buildCommands`) and
    `tree` (`tree_key` of the tree the gate runs in, None for the project).

    THE GATE AND THE TREE, NOT THE BYTES IN IT. A change to the declared files
    after a verdict is the committer's question (`_verdict_binding`'s digest
    binding), and it refuses: a green read again over edited work would close
    bytes a reviewer never saw.

    MOVED ONLY ON A COMPARISON THAT DISAGREES: a run whose row is gone, or a
    row that recorded no gate digest, is `STORED_UNKNOWN` with the reason - not
    agreement, and not a change either, so the caller says it rather than
    measuring for ever over a ledger it cannot read."""
    if not run_id:
        return STORED_UNKNOWN, "no run was recorded with it"
    row = row_by_run(rows, run_id)
    if row is None:
        return STORED_UNKNOWN, "run %s is not in the ledger" % (run_id,)
    was = row.get(GATE_DIGEST_KEY)
    if was is not None and was != now.get("gateDigest"):
        return STORED_MOVED, ("run %s was measured under a gate that resolves "
                              "to other commands now" % (run_id,))
    # THE TREE OF THE RUN NAMED, never of the run a repeat copies: a repeat is
    # admitted on the tree's CONTENT (`run-test-gate.reuse_identity`), so one
    # taken in tree B of a run measured in tree A is that verdict for B. A
    # repeat whose row names no tree claims none, and is not compared on one.
    tested = row.get("testedState") or {}
    repeat_unplaced = (row.get(VERDICT_SOURCE) == REUSED
                       and not isinstance(tested.get("tree"), dict))
    was_tree = (tested.get("tree") or {}).get("key")
    if not repeat_unplaced and was_tree != now.get("tree"):
        return STORED_MOVED, ("run %s was measured in %s, and the gate runs in "
                              "%s now" % (run_id, "tree %s" % (was_tree,) if was_tree
                                          else "the project",
                                          "tree %s" % (now["tree"],)
                                          if now.get("tree") else "the project"))
    if was is None:
        return STORED_UNKNOWN, "run %s recorded no gate digest" % (run_id,)
    return STORED_HOLDS, None


# --- the chain, and what each layer covers ------------------------------------
# ONE CHAIN, NOT A SECOND ONE. `prev` and `hash` mean here exactly what they mean
# in the trail, and they are computed by the journal's OWN `row_hash`,
# `genesis_prev` and `canonical`. A ledger with a chain of its own invention would
# be a second answer to "was this row edited", free to disagree with the record
# beside it the first time either was touched -- and the record of the
# MEASUREMENT is the last file in this plugin that should have its own opinion
# about what tampering looks like.
#
# WHAT EACH LAYER COVERS, written here because this one does NOT replace the
# anchor and must not be read as having done so:
#
#   this chain          a row edited in place, a row deleted, rows reordered, and
#                       a whole file dropped over another writer's file (the seed
#                       is the file's own BASENAME). It is the only one of the
#                       three that answers with a FINDING.
#   the journal anchor  `record()` writes the whole file's sha256 into the trail
#                       as `stateHash`, which is what catches the one rewrite this
#                       chain cannot: every row rewritten and every hash
#                       recomputed forward. It is the WEAKER layer, not the
#                       fallback -- it is a warning rather than a finding, it is
#                       compared only against the NEWEST trail row naming the
#                       file (so the next recorded run re-anchors rewritten bytes
#                       and the warning goes), and a row written through
#                       `append_row` alone is anchored by nothing at all.
#   git                 the committed copy, and the one absence neither layer
#                       above can be asked about: a file the index holds and the
#                       working tree does not. Both of those read rows, and a
#                       deleted file has none to read -- it drops out of the walk
#                       instead of failing it. The only layer a forger cannot
#                       also rewrite without rewriting history on every clone.
#
# A ROW FROM BEFORE THE CHAIN IS NOT A FINDING, and that is a decision rather than
# an omission. Every ledger written by an earlier release holds rows with no
# `hash`, and grading those as tampering would turn the first run of this check
# red in every project that upgrades -- a check whose opening verdict is a wall of
# findings nobody intends to act on is one its reader learns to skip, which costs
# more than the rows it would have caught. They are reported as a COUNTED WARNING
# naming what is not protected, and the gap closes itself: `link_after` hashes an
# unchained row to make the `prev` of whatever follows it, so the next recorded
# run puts every row before it under the chain.
#
# WHAT IS A FINDING IS AN UNCHAINED ROW AFTER A CHAINED ONE. Without that the
# chain is opt-out: delete two keys from a row and it is "legacy" again. The two
# innocent readings are named in the finding's own text, because one of them --
# an older copy of the plugin appending into a file a newer copy had chained -- is
# real and has a repair that is not a forensic hunt.
CHAIN_KEYS = ("prev", "hash")


def link_after(previous):
    """The `prev` a row appended after `previous` must carry.

    A row carrying no `hash` is HASHED HERE rather than skipped, which is what
    puts a ledger written before the chain existed under the chain the moment the
    next run is recorded: edit one of those rows afterwards and the first chained
    row that follows it stops following anything.
    """
    stored = previous.get("hash")
    if isinstance(stored, str) and stored:
        return stored
    return _journal_io.row_hash(previous)


def chain_onto(row, tail, basename):
    """`row` with its two chain keys set, linked onto `tail` in the file `basename`.

    `tail` is every row already in that file, oldest first. BOTH KEYS ARE
    ASSIGNED, never defaulted: a `prev` the caller brought is the link the row had
    in some other file, and keeping it would put a row into this chain carrying a
    predecessor that is not the row before it. The brought `hash` needs no such
    care and is not stripped -- `row_hash` excludes the key from its own input, so
    the digest covers the row's content either way, and a `pop` here would be a
    second guard over a rule that is already one function's own.
    """
    out = dict(row)
    out["prev"] = (link_after(tail[-1]) if tail
                   else _journal_io.genesis_prev(basename))
    out["hash"] = _journal_io.row_hash(out)
    return out


def chain_file(rows, basename):
    """Every row of one file, linked in order. The whole-file spelling of `chain_onto`.

    A writer that produces a file in one pass -- the demo generator, a ledger
    being re-linked by hand after an edit -- must not spell the seeding rule a
    second time, because the second spelling is the one that gets the genesis
    wrong and leaves a file that verifies only against itself.
    """
    out = []
    for row in rows or []:
        out.append(chain_onto(row, out, basename))
    return out


def verify_rows(rows, basename):
    """The chain verdict for ONE file's rows. The pure half of `verify`.

    `{"rows", "chained", "unchained", "findings", "warnings"}` -- `rows` as read,
    including the `_unparseable` markers `_journal_io.read_file` leaves behind, so
    a corrupted line is graded where it sits rather than silently closing the gap
    between the rows either side of it.

    THE PREV A ROW MUST CARRY IS `link_after`'s, NOT "the previous `hash`", and
    the difference is the whole of the legacy story: after an unchained row the
    expected link is that row's computed hash, so editing it breaks the chained
    row that follows. After a CORRUPTED line nothing can be expected at all and
    the link check is skipped for one row -- the same concession `_journal_io`
    makes, and for the same reason: the row's own `hash` check still fires, so a
    corrupted line buys a forger one unchecked link and no unchecked content.
    """
    out = {"rows": 0, "chained": 0, "unchained": 0,
           "findings": [], "warnings": []}
    expected = _journal_io.genesis_prev(basename)
    for i, row in enumerate(rows or []):
        if row.get("_unparseable"):
            out["findings"].append(
                "%s line %d is not valid JSON, and it is not the last line -- a "
                "recorded run was corrupted" % (basename, row.get("_line") or (i + 1)))
            expected = None
            continue
        out["rows"] += 1
        stored = row.get("hash")
        if not isinstance(stored, str) or not stored:
            if out["chained"]:
                out["findings"].append(
                    "%s row %d (run %s) carries no chain while the rows before it "
                    "do -- either an older copy of the plugin appended it (ask "
                    "/audit:doctor which copy ran) or a chained row's links were "
                    "stripped to take it out of the chain. Nothing here can tell "
                    "those apart" % (basename, i + 1, row.get("runId") or "?"))
            else:
                out["unchained"] += 1
            expected = link_after(row)
            continue
        out["chained"] += 1
        if stored != _journal_io.row_hash(row):
            out["findings"].append(
                "%s row %d (run %s) does not hash to its own contents -- it was "
                "edited after it was written"
                % (basename, i + 1, row.get("runId") or "?"))
        elif expected is not None and row.get("prev") != expected:
            out["findings"].append(
                "%s row %d (run %s) does not follow the row before it -- a run "
                "was deleted, the rows were reordered, a row before it was "
                "edited, or this file was renamed"
                % (basename, i + 1, row.get("runId") or "?"))
        expected = stored
    if out["unchained"]:
        out["warnings"].append(
            "%s: %d recorded run(s) at the head of this file carry no chain and "
            "nothing protects them -- they were written before the ledger was "
            "chained. They are not evidence of tampering. The next run recorded "
            "into this file links onto them and closes the gap"
            % (basename, out["unchained"]))
    return out


# --- merging a ledger file that diverged ----------------------------------------
# ONE MERGE FOR BOTH CHAINED RECORDS. A ledger file appended on two branches under
# one name - which every file was before the per-worktree writer key - conflicts
# exactly as a journal file does, and is resolved by `_journal_io.merge_rows`
# with the same refusals and the same re-chain: this chain IS the journal's.
#
# NO MARKER ROW IN THE LEDGER, and the reason is the readers. Every row in this
# directory is read as a RECORDED RUN - `read_rows`, `latest_by_subject`, the gate
# tallies, `earliest_recorded`, the verdict a task commit is bound to - so a row
# recording a merge would be counted as a run with no status by each of them. The
# merge is recorded in the JOURNAL instead (`ACTION_MERGED`), in a row whose
# target is the merged file: its `stateHash` is the file's new bytes, which is
# also what keeps the journal's anchor from reporting the re-chained file as an
# edit it never saw.
ACTION_MERGED = _journal_io.EVIDENCE_MERGE_ACTION


def merge_targets(row, aliases):
    """Every subject a reader of the ledger could file `row` under, as strings.

    The targets a same-second tie is ordered by, and they are the READERS' keys
    rather than a rule of the merge's own: two rows are disjoint only when no
    reader could put them on one subject, because for rows on one subject the
    order IS which verdict is newest. So a row's targets are
      * `subject_key(row, aliases)` - the `(scope, id)` key `latest_by_subject`
        writes a pointer under, moved task ids mapped onto the id held now; a
        `--task` run measured under its phase's gate is `scope: phase` and so
        shares its phase sign-off's key; and
      * the `taskId`/`phaseId` pair `_same_subject` compares a verdict by, with
        a moved task id mapped the same way and an absent id kept distinct.
    `aliases` is `subject_aliases(plan)`; None means the plan was not read, so
    how old ids map is unknown and the row has NO target - a tie is then refused,
    never ordered.
    """
    if not isinstance(row, dict) or aliases is None:
        return ()
    out = []
    key = subject_key(row, aliases)
    if key is not None:
        out.append("key %s %s" % key)
    task = row.get("taskId")
    if task is not None:
        task = aliases.get(("task", str(task)), ("task", str(task)))[1]
    out.append("pair task=%s phase=%s" % (
        "-" if task is None else task,
        "-" if row.get("phaseId") is None else str(row.get("phaseId"))))
    return tuple(out)


def merge_rows(ours, theirs, name, torn=(), aliases=None):
    """`_journal_io.merge_rows` for one ledger file: the readers' subject keys as
    each run's targets (`merge_targets`, under the plan's `aliases`), and no
    marker row (the section above says why)."""
    return _journal_io.merge_rows(
        ours, theirs, name, torn=torn,
        target_of=lambda row: merge_targets(row, aliases), marker=False)


def plan_aliases(project, config=None):
    """`(aliases, why)` - `subject_aliases` of the plan this project keeps, or
    `(None, why)` when it could not be read, which a merge reads as "no two runs
    are provably disjoint"."""
    config = _journal_io.load_config(project) if config is None else config
    rel = (config or {}).get("manifestPath") or _journal_io.DEFAULT_MANIFEST
    path = os.path.join(project, str(rel))
    try:
        return subject_aliases(_mio.load_manifest(path)), ""
    except Exception as exc:
        where, why = _unreadable_plan_file(project, path, rel, exc)
        return None, ("the plan could not be read - %s (%s) - so which task ids "
                      "were moved onto which is unknown and no same-second tie "
                      "in the ledger can be ordered" % (where, why))


def _unreadable_plan_file(project, path, rel, exc):
    """`(file, reason)` - the FILE of the plan that would not load, and why.

    The loader reads the index and then every shard it names, and its error
    carries a parser offset with no file name - so an unreadable shard would be
    reported against the index, which parses. Each is read on its own here to
    name the one that failed; when none does, the loader's own reason stands.
    """
    try:
        index = _mio.read_json(path)
    except Exception as first:
        return rel, first
    base = os.path.dirname(path)
    for stub in (index.get("phases") or []) if isinstance(index, dict) else []:
        shard = stub.get("shard") if isinstance(stub, dict) else None
        if not shard:
            continue
        try:
            _mio.read_json(os.path.join(base, str(shard)))
        except Exception as bad:
            return (_output.posix_rel(os.path.join(base, str(shard)), project),
                    bad)
    return rel, exc


def record_merge(project, path, result, actor=None, config=None):
    """The journal row recording a ledger merge. Returns the file, or False.

    Written AFTER the merged file, so its `stateHash` is the merged bytes.
    Fail-soft like every append; the caller says when it could not be written.
    """
    config = _journal_io.load_config(project) if config is None else config
    entry = {
        "action": ACTION_MERGED,
        "actor": actor if isinstance(actor, dict) else {"via": "merge"},
        "target": repo_relative_or_token(project, path),
        "summary": result.get("summary") or "",
    }
    # WHERE THE RE-CHAIN LIES, because this row is the only place it can be
    # kept: a ledger row's content may not change and no row may be added to
    # the ledger, and past this merge `prev` in that stretch no longer records
    # one writer's order (`chain_ordered`).
    stretch = dict((key, result.get(key)) for key in
                   ("relinkedAfter", "relinkedThrough") if result.get(key))
    if stretch:
        entry["details"] = stretch
    return _journal_io.append_from_cli(project, entry, config=config)


def merge_seams(project, config=None):
    """`(seams, why)` - every re-chained stretch a ledger merge recorded, as
    `(relinkedAfter, relinkedThrough)` pairs read off the journal's
    `ACTION_MERGED` rows, or `(None, why)` when the journal could not be read.

    `[]` is an answer - no merge re-chained this ledger - and None is not one,
    which is why they are kept apart: `chain_ordered` reads no chain as a
    writer's order under None. A merge whose journal row was never written
    (`record_merge` is fail-soft, and says so) leaves no stretch here.

    A DISABLED JOURNAL IS None AND NOT []: with `journal.enabled` false no
    merge could have been recorded, so the absence of one proves nothing."""
    if not _journal_io.enabled(
            _journal_io.load_config(project) if config is None else config):
        return None, ("the journal is disabled (journal.enabled false), so no "
                      "ledger merge could have been recorded")
    try:
        journal = _journal_io.read_all(project, config)
    except Exception as exc:
        return None, ("the journal that records ledger merges could not be read "
                      "(%s)" % (exc,))
    seams = []
    for row in journal:
        if row.get("action") != ACTION_MERGED:
            continue
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        after = details.get("relinkedAfter")
        if isinstance(after, str) and after:
            through = details.get("relinkedThrough")
            seams.append((after, through if isinstance(through, str) else None))
    return seams, ""


# --- writing and reading ------------------------------------------------------
def scrubbed_ledger_row(project, row):
    """`row` as the ledger may store it: every string scrubbed of machine paths
    except `steps[i].command` (`LEDGER_KEPT_STEP_KEY` says why). A NEW
    structure; the argument is untouched."""
    clean = _journal_io.scrubbed_values(project, row)
    steps = row.get("steps") if isinstance(row, dict) else None
    if not isinstance(steps, list) or not isinstance(clean.get("steps"), list):
        return clean
    for i, step in enumerate(steps):
        if isinstance(step, dict) and LEDGER_KEPT_STEP_KEY in step:
            clean["steps"][i][LEDGER_KEPT_STEP_KEY] = step[LEDGER_KEPT_STEP_KEY]
    return clean


def append_row(project, row, session_id=None, config=None, writer=None):
    """Append one row, chained onto the file's tail; return the file it landed in.

    THE LOCK IS THE CHAIN'S, and it is why this is no longer the bare O_APPEND the
    usage ledger gets away with. `prev` is read off the last row in the file, so
    two appends by one writer that both read that tail would write the same `prev`
    and produce a break indistinguishable from a deleted run. The journal's own
    lock is taken rather than a second one written here; when it cannot be taken
    the append RAISES, because a false tamper verdict is worse than a missing row
    and `record()` already declines to report a run whose evidence was not stored.

    `writer`, WHEN GIVEN, NAMES THE FILE AND WINS OVER A SESSION ID. A CI build
    has no `CLAUDE_CODE_SESSION_ID` most of the time, but even where it does, a
    build's own identity should not be split across files by which session
    happened to invoke the shard - `--writer ci-42` is the caller SAYING that
    name is the writer, so `session_id` is left out of the lookup entirely
    rather than merely offered as a fallback that a session would still beat.
    """
    config = _journal_io.load_config(project) if config is None else config
    directory = evidence_dir(project, config)
    os.makedirs(directory, exist_ok=True)
    writer = writer.strip() if isinstance(writer, str) else ""
    if writer:
        actor, fallback = {}, writer
    else:
        actor = {"sessionId": session_id} if session_id else {}
        fallback = (None if _journal_io.has_session(actor)
                   else _journal_io.writer_token(project, config))
    # The trail's own key, for the trail's reason: one writer per file, and one
    # session driving two linked worktrees is two writers - their branches would
    # otherwise each append the same basename and meet as a conflict on merge.
    path = _journal_io.file_for(
        directory, row.get("ts") or _utc_stamp.utc_stamp(), actor, fallback=fallback,
        worktree=_journal_io.worktree_key(project, config))
    lock = _journal_io._acquire(path, record="the evidence ledger")
    try:
        # The tail is read through `ledger_text` like every other ledger read.
        # A file that does not exist yet has no tail. One that exists and will
        # not decode is REFUSED: every reader loses that file whole, so a run
        # appended to it would be stored where nothing can find it - and
        # `record()` must not report a run as stored when no reader can see it.
        rows = []
        if os.path.exists(path):
            try:
                rows, _torn = _journal_io.rows_from_text(ledger_text(path))
            except UnicodeDecodeError as exc:
                raise ValueError(
                    "%s is not UTF-8 text (%s), and every reader loses such a "
                    "file whole - a run appended to it would be invisible, so "
                    "it was not appended. Restore the file from its committed "
                    "copy and record the run again"
                    % (os.path.basename(path), exc))
        tail = [r for r in rows if not r.get("_unparseable")]
        linked = chain_onto(scrubbed_ledger_row(project, row), tail,
                            os.path.basename(path))
        # LF on every platform, as the journal's appender writes it.
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(_journal_io.canonical(linked) + "\n")
    finally:
        _journal_io._release(lock)
    return path


def ledger_files(project, config=None):
    """Every ledger file, sorted. One listing, so no reader invents a second.

    Named rather than inlined because `read_rows` and `verify` must walk the SAME
    set: a verdict about a file no consumer reads, or a consumer reading a file no
    verdict covers, are both silences that look like agreement.
    """
    directory = evidence_dir(project, config)
    try:
        return [os.path.join(directory, n)
                for n in sorted(os.listdir(directory)) if n.endswith(".jsonl")]
    except Exception:
        return []


def ledger_text(path):
    """The text of one ledger file, decoded STRICTLY; raises when it cannot be.

    THE ONE DECODE every reader of a ledger file goes through, so a byte that is
    not UTF-8 is the same answer everywhere: the file could not be read. A
    lenient decode would swap that byte for a replacement character and hand
    the row back as clean, and a value it silently changed - a `runId`, a
    command, a head - would then be compared as if it had been recorded that
    way, while the chain check grades the same bytes unreadable.
    """
    with open(path, "rb") as fh:
        return ledger_decode(fh.read())


def ledger_decode(raw):
    """Ledger BYTES as text, decoded strictly; raises `UnicodeDecodeError`.

    `ledger_text`'s decode, split out for the bytes that never were a file on
    this disk - a merge side git holds in its index, a shard handed to an
    import - so they are read by the same rule as the file they become.
    """
    return raw.decode("utf-8")


def read_rows(project, config=None, *, manifest_path):
    """`{"rows", "rowFiles", "rowSources", "files", "records", "unreadable",
    "unreadableFiles", "unreadablePlanFiles", "ledgerAbsent"}` - every
    recorded run, and what was lost.

    A TORN LINE IS COUNTED, not merely skipped. `usage_ledger.read_ledger` drops
    one in silence, which is right for telemetry and wrong here: silence about a
    lost EVIDENCE row is the failure this file exists to prevent. `files` is
    reported for the same reason - "no rows" and "no files" are different answers
    and a bare list could not tell them apart.

    THE PARSE IS `_journal_io.rows_from_text`'s AND THE COUNT IS THIS FUNCTION'S,
    which is the split that lets `verify` and this reader disagree about nothing.
    A second parser here is how a row the chain graded would come to be a row this
    never returned: same bytes, two opinions about what a row even is. What stays
    local is the RULE -- the trail forgives a torn tail as a crash, and this
    counts it, because a lost measurement is not a lost note.

    `unreadableFiles` NAMES THE PATH, ADDITIVELY. `unreadable` has always been a
    bare count, which is enough for a boundary that only needs to know something
    was lost (`since_boundary`) - but a reader asking a QUESTION about the
    ledger's own content (`validate-manifest.py`'s 'phase gate runs no suite')
    has to say WHICH file it could not trust, not merely how many lines. One
    path per FILE that contributed to `unreadable` (a file unreadable outright,
    or carrying an unparseable line, or a torn tail), deduplicated, in the order
    `ledger_files` returns them.

    `rowFiles` NAMES EACH ROW'S FILE, ADDITIVELY: the basename of the ledger
    file `rows[i]` was read from, at the same index. A caller that must say
    WHICH file holds a run reads it here rather than walking the directory a
    second time - a second walk is a second decode, and one stricter than the
    read above would find a row here that it cannot find there.

    THE PLAN'S RECORDS ARE READ BESIDE THE ROWS (`RECORD_KEY`, through
    `record_row`), one entry per run: a run the ledger holds is its row, and a
    run only a record holds - the newest run of a subject, the run a repeat
    copied, or a full run a phase holds - is appended after every row. A
    project with no evidence directory at all is read from the plan alone,
    and a full run certified before the ledger stopped being written is read
    from its frozen row for as long as that row is there. `rowSources[i]` says which
    (`ROW_FROM_LEDGER` or `ROW_FROM_RECORD`); for a record `rowFiles[i]` is the
    plan file holding it, relative to `project`, where for a row it is the
    ledger file's basename. `files`, `unreadable` and `unreadableFiles` stay
    the LEDGER's; `records` counts the entries a record gave and
    `unreadablePlanFiles` names a plan file that would not read.

    `manifest_path` IS REQUIRED, and None is refused (`ValueError`): it is the
    plan whose records are read, and it is the caller's to say. A project may
    hold more than one plan, their task ids colliding, while a run's record is
    written to the plan the recording command was handed - so a reader that
    fell back to the plan the config names would look a run up in a foreign
    plan. A caller that means the configured plan says so with
    `plan_file_of(project, config)`.

    A DIRECTORY THAT IS NOT THERE IS SAID, NEVER COUNTED: `ledgerAbsent` is the
    sentence naming where the ledger was looked for when no such directory
    exists, so `files == 0` beside it reads as "no ledger", never as a ledger
    holding no file; None when the directory exists.
    """
    if manifest_path is None:
        raise ValueError("read_rows names no plan: the records read beside the "
                         "ledger are the plan the caller was handed, so a "
                         "caller passes it (plan_file_of for the configured "
                         "one)")
    config = _journal_io.load_config(project) if config is None else config
    rows, row_files, unreadable, files = [], [], 0, 0
    unreadable_files = []
    for path in ledger_files(project, config):
        files += 1
        lost_here = False
        try:
            text = ledger_text(path)
        except Exception:
            unreadable += 1
            unreadable_files.append(path)
            continue
        parsed, torn = _journal_io.rows_from_text(text)
        for obj in parsed:
            if obj.get("_unparseable"):
                unreadable += 1
                lost_here = True
            else:
                rows.append(obj)
                row_files.append(os.path.basename(path))
        if torn:
            unreadable += 1
            lost_here = True
        if lost_here:
            unreadable_files.append(path)
    directory = evidence_dir(project, config)
    absent = None if os.path.isdir(directory) else (
        "no evidence directory at %s, so no older row was read - the runs "
        "here are the records the plan holds" % (
            repo_relative_or_token(project, directory),))
    bodies, lost_plan = plan_bodies(manifest_path, project)
    sources = [ROW_FROM_LEDGER] * len(rows)
    rows, added = with_records(rows, records_of_bodies(bodies))
    row_files.extend(label for _row, label in added)
    sources.extend(ROW_FROM_RECORD for _pair in added)
    return {"rows": rows, "rowFiles": row_files, "files": files,
            "unreadable": unreadable, "unreadableFiles": unreadable_files,
            "rowSources": sources, "records": len(added),
            "unreadablePlanFiles": lost_plan, "ledgerAbsent": absent}


# --- folding history into a tally, never into a verdict ------------------------
# A CALLER FOLDS THIS INTO A CLAIM; IT NEVER IS ONE. `propose-gates.py` (a plan
# proposal reading what history actually caught) and `_doctor_trail.py` (a
# standing diagnostic over the same ledger) both need "how many times has this
# run, and how many of those runs did not simply pass" - and neither is allowed
# to invent its own count, or the two would answer one question two ways the
# first time somebody added a step key. So the tally lives here, once, beside
# the row shape it reads.
#
# THE FLOOR IS A COUNT OF RUNS, NOT A JUDGEMENT. A single recorded run passing
# is one data point, and "never failed" said about one data point is the same
# overclaim a lone start would be for a restart pattern - a caller that folds a
# tally below this floor into a claim is doing the widening this module refuses
# to do for it.
MIN_HISTORY_RUNS = 2


def _step_failed(step):
    """True when a recorded step's own fields say it did not simply pass.

    `outcome` is the three-valued field a runner sets for what `exit` alone
    cannot say (a timeout, a signal, a step that could not run at all); an
    `exit` other than zero is the ordinary failure a runner reports without
    ever reaching for that field.

    A MUTED step is not one, whatever its exit: its failure is quarantined
    and known, so counting it would credit the gate with a catch on every
    run the mute holds."""
    if step.get("muted"):
        return False
    if step.get("outcome"):
        return True
    exitcode = step.get("exit")
    return exitcode is not None and exitcode != 0


def _matching_steps(rows, key, value):
    """Every step across `rows` whose `key` equals `value`, in row order.

    `rows` is whatever `read_rows(...)["rows"]` returned - unordered by this
    function's own contract, since a tally needs a count and not a sequence.
    A caller that wants oldest-first sorts by `ts` before calling this.

    A REPEATED STEP (`step_repeated`) IS NO RUN OF THE STEP: its run is the one
    it names, which this walk already meets on that run's own row."""
    out = []
    for row in (rows or []):
        for step in (row.get("steps") or []):
            if isinstance(step, dict) and step.get(key) == value \
                    and not step_repeated(step):
                out.append({"ts": row.get("ts"), "runId": row.get("runId"),
                            "exit": step.get("exit"), "outcome": step.get("outcome"),
                            "muted": step.get("muted"),
                            "durationMs": step.get("durationMs")})
    return out


def gate_tally(rows, name):
    """`(ran, failed)` for the named gate (`steps[].name`, e.g. "lint") across
    `rows` - the basis a caller folds into a claim, never a claim on its own.

    Matches the SHORT identity a runner assigns a step (`meta.buildCommands`'
    key), which survives a command being reworded between runs - the reason
    `command_tally` exists beside this rather than in place of it."""
    hist = _matching_steps(rows, "name", name)
    return len(hist), sum(1 for s in hist if _step_failed(s))


def command_tally(rows, command):
    """`(ran, failed)` for the literal `command` (`steps[].command`) across
    `rows`.

    Matches the VERBATIM string a manifest publishes - `_step()`'s own rule
    for when a command is stored whole rather than as a digest - so a caller
    proposing a candidate command matches the same spelling the manifest
    would carry, not a name a runner happened to pick for it."""
    hist = _matching_steps(rows, "command", command)
    return len(hist), sum(1 for s in hist if _step_failed(s))


def gate_last_caught(rows, name):
    """ISO timestamp of the most recent recorded run of `name` that did not
    simply pass, or `None` -- which is NOT the same claim as `gate_tally`'s
    `failed` being zero for want of any run at all. `ran` is what tells the
    two apart; this answers only the WHEN half, for the gate that has caught
    something at least once."""
    hist = _matching_steps(rows, "name", name)
    last = newest_row([h for h in hist if h.get("ts") and _step_failed(h)])
    return last["ts"] if last else None


def _gate_cost_walk(rows, name):
    """`(total, measured)` for the named gate across `rows`, walked ONCE --
    the total ms summed over every matching step that carries a `durationMs`,
    beside a count of exactly those steps. `gate_cost_ms` and
    `gate_cost_measured` both read this one walk rather than each summing and
    counting for itself, so a future step key can never make the sum and the
    count disagree about which steps contributed.

    A REPEATED STEP (`step_repeated`) IS SKIPPED, whatever duration it carries:
    the run it names spent that time and is counted on its own row, so adding
    it here would bill one measurement twice."""
    total, measured = 0, 0
    for row in (rows or []):
        for step in (row.get("steps") or []):
            if not (isinstance(step, dict) and step.get("name") == name):
                continue
            if step_repeated(step):
                continue
            duration = step.get("durationMs")
            if isinstance(duration, (int, float)) and not isinstance(duration, bool):
                total += duration
                measured += 1
    return total, measured


def gate_cost_ms(rows, name):
    """Total recorded run time (ms) for the named gate across `rows`, summed
    over every matching step that carries one. `None` when not one step did --
    absent means UNMEASURED, never zero, which is `phase_budgets`' rule read
    for a run's own cost rather than for the plan's declared one."""
    total, measured = _gate_cost_walk(rows, name)
    return total if measured else None


def gate_cost_measured(rows, name):
    """How many recorded runs of the named gate across `rows` carried a
    `durationMs` -- the denominator a MEAN must divide by. `gate_tally`'s
    `ran` counts every matching step whether or not it carries one, so a
    history that mixes measured and unmeasured runs dilutes `total / ran`
    toward zero and can hide a gate that is over budget on the runs actually
    measured; this is the count that keeps the two questions from being
    answered as if they were one."""
    return _gate_cost_walk(rows, name)[1]


def step_mean_ms(rows, name):
    """`(mean_ms, measured)` for the named step across the `rows` that reached
    a verdict (`MEASURED_STATUSES`), or `None` when no matching step of theirs
    carries a `durationMs` -- unmeasured, never a zero mean.

    ONLY A RUN THAT REACHED A VERDICT SAYS HOW LONG THE STEP TAKES. A run that
    could not start, was cancelled or was stopped at its bound timed its steps
    too, but for as long as they were let run: a cancelled slow suite reads
    fast, and a mean over it predicts a gate shorter than it is.

    The count travels with the mean because a mean over one run and a mean over
    many are different claims, and the caller printing the mean owes its reader
    which one it is. Both come from `_gate_cost_walk`, so the divisor is exactly
    the steps the sum took, never `gate_tally`'s `ran`."""
    total, measured = _gate_cost_walk(
        [row for row in rows or () if isinstance(row, dict)
         and row.get("status") in MEASURED_STATUSES], name)
    if not measured:
        return None
    return total / measured, measured


# How long the Bash tool keeps a command in the foreground before the CLI moves
# it to the background, after which the caller waits on it and polls for its
# output instead of reading it, and later kills it. The basis is the CLI's own
# message when a command reaches it - "Command did not complete within its 120s
# timeout and was moved to the background" - read in a recorded session's tool
# result; it is the default, and a session started with a different default is
# not seen from here. One constant for every reader: the writer's brief leaves a
# step past it to the drive's gate, and the drive leaves a gate past it to the
# background.
FOREGROUND_BOUND_MS = 120 * 1000


def outlives_foreground(mean_ms):
    """Whether a recorded mean is past `FOREGROUND_BOUND_MS`; no mean (None) is
    not, since nothing says it is slow - a caller for whom an unmeasured step
    is one to keep out of the foreground says so itself."""
    return mean_ms is not None and mean_ms > FOREGROUND_BOUND_MS


def gate_mean_ms(rows, names):
    """`(mean_ms, runs)` for a gate of the steps `names` across `rows`, or None
    when it has no steps or any of them has no measured run.

    THE SUM OF THE STEPS' MEANS, because `run-test-gate.py` runs a gate's steps
    one after another, so the gate lasts as long as all of them together. A
    step with no measured run makes the whole unmeasured rather than leaving it
    out: the sum without it is only a lower bound, and the step nobody has timed
    may be the slow one. `runs` is the fewest any step was measured over - the
    weakest of the means the sum stands on."""
    readings = [step_mean_ms(rows, name) for name in names or ()]
    if not readings or any(r is None for r in readings):
        return None
    return sum(r[0] for r in readings), min(r[1] for r in readings)


def gate_names_seen(rows):
    """Every distinct `steps[].name` recorded across `rows`, sorted."""
    names = set()
    for row in (rows or []):
        for step in (row.get("steps") or []):
            if isinstance(step, dict) and step.get("name"):
                names.add(step["name"])
    return sorted(names)


def verify(project, config=None):
    """Does every recorded run still hash to what it said, in the order it said it?

    `{"ok", "dir", "exists", "rows", "files", "findings", "warnings", "unchained"}`
    -- `_journal_io.verify`'s shape on purpose, so a surface asking both records
    the same question reads one answer twice rather than two answers once.

    FINDINGS are breaks: a run edited after it was written, a run deleted or
    reordered, a file dropped over another writer's file, a corrupted line, a run
    appended with no chain into a file whose earlier rows have one, and a ledger
    file that could not be read at all. WARNINGS are the honest maybes: a torn
    tail, and the rows that predate the chain.

    IT ASKS GIT EXACTLY ONE QUESTION, and it is the one no walk of this directory
    can answer: which ledger files does git TRACK that the working tree does not
    have. `ledger_files` lists what is on disk, so a whole file that was deleted
    was never in the loop below and the chain over the files that remained came
    back clean -- the same hole the trail had, in the record a green gate points
    at, so it is closed by the same function (`_journal_io.gone_findings`) rather
    than by a second one written here. It runs before the `exists` gate, because
    an evidence directory removed whole is that deletion with more files in it.

    WHAT THIS DOES NOT ASK, so that nothing reads it as having asked. It does not
    compare a file that IS here against its committed copy and it does not compare
    it against the trail's `stateHash` -- `_journal_io.verify` already does the
    second for every evidence file `record()` anchored, and a second opinion here
    would be a second answer to one question. The rewrite this cannot see at all is
    the whole file re-written with every hash recomputed forward; that one is the
    anchor's and git's, and the section above says how far each of them reaches.
    """
    config = _journal_io.load_config(project) if config is None else config
    directory = evidence_dir(project, config)
    out = {"ok": True, "dir": directory, "exists": os.path.isdir(directory),
           "rows": 0, "files": [], "findings": [], "warnings": [],
           "unchained": 0}
    out["findings"].extend(_journal_io.gone_findings(project, directory))
    if not out["exists"]:
        out["ok"] = not out["findings"]
        return out
    for path in ledger_files(project, config):
        name = os.path.basename(path)
        try:
            text = ledger_text(path)
        except Exception as exc:
            # A FINDING, NOT A SKIP. `_journal_io.read_file` answers an unreadable
            # file with no rows, which is the right fail-open for a reader walking
            # a directory that raced a `git mv` -- and exactly the wrong answer for
            # the question being asked here, because "no rows, no findings" is what
            # a clean file also prints. A record nothing can read is not a record
            # that holds, and it is the state a forger would settle for.
            out["findings"].append(
                "%s could not be read (%s), so not one run in it was checked"
                % (name, exc))
            out["files"].append({"file": name, "rows": 0, "chained": 0,
                                 "unchained": 0,
                                 "findings": [out["findings"][-1]],
                                 "warnings": []})
            out["ok"] = False
            continue
        rows, torn = _journal_io.rows_from_text(text)
        verdict = verify_rows(rows, name)
        if torn:
            verdict["warnings"].append(
                "%s ends with a partial line -- a writer was interrupted. The "
                "runs before it are intact; nothing was hidden by it." % (name,))
        out["rows"] += verdict["rows"]
        out["unchained"] += verdict["unchained"]
        out["findings"].extend(verdict["findings"])
        out["warnings"].extend(verdict["warnings"])
        out["files"].append({"file": name, "rows": verdict["rows"],
                             "chained": verdict["chained"],
                             "unchained": verdict["unchained"],
                             "findings": verdict["findings"],
                             "warnings": verdict["warnings"]})
    out["ok"] = not out["findings"]
    return out


def record(project, result, scope, ids, identity, published=None, config=None,
           writer=None):
    """Append the row, then anchor it in the journal. Returns both outcomes.

    ORDER IS THE POINT. The ledger row is written FIRST and the journal row
    second, so the only reachable partial state is the harmless one: a run that
    happened with nothing yet pointing at it. The reverse would put a claim in a
    hash chain about a row that does not exist.

    THE ANCHOR IS NOT THE POINTER MOVING. This row's subject is the evidence
    file, and it says only that a run was recorded - which is true the moment it
    is written. The row that says the PLAN moved belongs to whoever moves it, and
    must not be written before that happens.

    Fail-soft on the journal half, `_journal_io.append`'s own contract: a run that
    was recorded must not be reported as unrecorded because the trail could not be
    written.

    THE RETURNED `row` IS THE RUN'S CONTENT AND NOT THE LINE ON DISK. `prev`
    depends on which file the row lands in and on what was already in it, so the
    two chain keys are added by `append_row` at the moment of the write and the
    dict here never carries them. Nothing downstream wants them: `pointer_for`
    caches identity, verdict and moment, and a hash cached beside the row it
    digests would be this repository's most repeated defect wearing a new field
    name. Hash the file, not the return value.

    `writer` PASSES THROUGH TO `append_row` UNCHANGED - see that function for
    why it wins over `identity["sessionId"]` rather than merely falling back
    to it.
    """
    config = _journal_io.load_config(project) if config is None else config
    row = row_for(project, result, scope, ids, identity, published=published)
    path = append_row(project, row, session_id=identity.get("sessionId"),
                      config=config, writer=writer)
    details = {"runId": row["runId"]}
    for key in ("taskId", "phaseId"):
        if row.get(key):
            details[key] = row[key]
    appended = _journal_io.append_from_cli(project, {
        "action": ACTION_RECORDED,
        "actor": {"sessionId": identity.get("sessionId"),
                  "via": identity.get("via") or "unknown"},
        "target": repo_relative_or_token(project, path),
        "summary": "%s run %s on %s: %s"
                   % (scope, row["runId"], ids.get("taskId")
                      or ids.get("phaseId") or "?", row.get("status")),
        "details": details,
    }, config=config)
    return {"row": row, "path": path, "appended": appended}


# --- the pointer: a cache the manifest keeps ----------------------------------
# THE LEDGER IS THE SOURCE OF TRUTH AND THIS IS A CACHE, which is what makes the
# write below the one allowed to fail. `COMPATIBILITY.md` already states that
# contract for `meta.ado`'s caches: deleting the block is always safe, absent
# means "never recorded", and every reader is written to that. So a refusal here
# costs a reader one lookup, never a fact.
POINTER_KEY = "testEvidence"
ACTION_MOVED = {"task": "task.testEvidence", "phase": "phase.testEvidence"}
# What a refused pointer leaves, and what to run - said in that order.
RECONCILE_OUTCOME = "the run is recorded"
RECONCILE_REPAIR = ("re-run with --reconcile once the holder is done to point "
                    "the plan at it")
RECONCILE_HINT = "%s; %s" % (RECONCILE_OUTCOME, RECONCILE_REPAIR)

# --- the one way a plan file is written -------------------------------------------
# ONE LOCK FOR EVERY WRITER OF A PLAN FILE, AND IT IS THE VERBS'. Every
# `audit-task.py` verb reads, changes and saves the plan under `index`
# (`_under_lock`), and so do the panel's writes (`_panel_write.LOCK_NAME`),
# close-phase (`under_index_lock`), the proposals, the repair commands and the
# merge driver. This module's writers used to take `phase-<id>` instead, which no
# verb takes for a write - so a record written while a verb sat between its read
# and its write, or a verb's write while a record did, were two read-modify-writes
# of one file that excluded nothing, and the later one wrote its stale read back
# over the other's change. Every save of a plan file here now goes through
# `write_plan_file`: it takes `index`, reads the file only once the lock is
# held, and saves what the caller's change made of that read. No other function
# in this module saves a plan file, and `tests/test__evidence_io.py` reads this
# module's AST for that (`lk1`), so a writer added beside it fails by name.
#
# THE PHASE LOCK IS NOT TAKEN AS WELL. It is a claim on a phase's RUN - `start`'s
# hand-off claim, held until sign-off, and the drive's phase run - not a guard of
# a write: no writer of a shard takes it alone, so it excludes nothing `index`
# does not, and taking it too would refuse a run's record whenever another
# session holds the phase, which is losing the plan's only copy of a run to
# protect no write. One lock also leaves no order to keep: `start` takes
# `phase-<id>` while it holds `index`, and a writer here taking the two the other
# way round would be the second order a deadlock needs. A gate the drive
# launches while its phase run holds `phase-<id>` therefore meets `index` alone,
# which the drive holds only for the length of a verb's write.
SHARD_LOCK = "index"
SHARD_LOCK_LABEL = "index"


def pointer_for(row):
    """The three keys the manifest caches: identity, verdict, time.

    NOTHING COUNTABLE. An attempt number and a count of runs were both cut: the
    attempt is on the row where it is written once, and a count is derived by
    reading the ledger. A cached count is this repository's most repeated defect.
    """
    return {"runId": row.get("runId"), "status": row.get("status"),
            "at": row.get("ts")}


def lock_state(project, name, label, session_id=None, outcome="", repair=""):
    """`(state, detail)` -- may this session write what `name` guards, and if not why.

    `free` | `ours` | `held` | `stale` | `unlockable`.

    `ours` IS `_locks.held_by_us`'s ANSWER, asked rather than re-derived. A gate
    recorded from inside its own phase run meets the lock that run holds, and this
    reads the claim instead of taking it; whose claim it is has one rule, the
    lock's own. A copy here that compared the session alone went on calling a
    claim another live process of this session took for its own write "ours"
    after the lock stopped doing so - and a pointer written under it raced that
    process's write of the same shard.

    `unlockable` is the panel's documented third answer, kept for its reason: a
    project with no `.git` has no lock scheme and never had one, and refusing
    every such project would refuse a case that has an answer.

    A STALE LOCK IS NOT TAKEN OVER HERE. Taking one over is a decision a human
    makes with `audit-lock --takeover` after confirming the holder is dead; a
    cache write must not make it quietly.

    `outcome` AND `repair` ARE THE CALLER'S, AND SAID IN THAT ORDER: what the
    refusal left (`nothing was written to the plan`), then what to run. The
    writers' repairs differ -- a refused pointer is caught up by `--reconcile`, a
    refused record by re-running its gate, a refused boundary needs nothing at
    all -- so a shared sentence here would send half the callers somewhere that
    cannot help them. A dead holder's sentence adds the step before the
    caller's repair, because nothing here takes a lock over.
    """
    said = "; ".join(s for s in (outcome, repair) if s)
    try:
        if not _locks.available(project):
            return "unlockable", "this project has no lock scheme"
        path = os.path.join(_locks.lock_dir(project), "%s.lock" % (name,))
        if not os.path.exists(path):
            return "free", ""
        info = _locks.read_lock(path)
        mine = _locks.held_by_us(info, session=session_id)
        if mine["ours"]:
            return "ours", mine["why"]
        live, basis = _locks.judge(info, path)
        if live:
            return "held", ("the %s lock is held by another live run (%s); %s"
                            % (label, basis, said))
        return "stale", (
            "the %s lock looks abandoned (%s) and is not taken over here, so %s. "
            "To write it: confirm with a human that its holder is gone "
            "(`audit-lock.py status`), release it (`audit-lock.py release %s "
            "--force`), then %s"
            % (label, basis, outcome or "nothing was written",
               name, repair or "run this again"))
    except Exception as exc:
        return "held", ("the %s lock could not be read (%s); %s"
                        % (label, exc, said))


def shard_lock_state(project, session_id=None, outcome="", repair=""):
    """`lock_state` of `SHARD_LOCK`, the lock every plan-file write takes."""
    return lock_state(project, SHARD_LOCK, SHARD_LOCK_LABEL,
                      session_id=session_id, outcome=outcome, repair=repair)


# THE TWO REFUSALS OF THE LOCK, WORDED APART. A claim another live run holds is
# waited out and then refused with `INDEX_BUSY_HEAD` - the one refusal that
# clears by itself, so the one a caller may wait on (`index_lock_busy`, which
# the drive reads off the gate runner's words). A claim that could not be
# WRITTEN - a lock directory this run cannot write - names no holder at all, and
# waiting for it to free would be waiting for a run that was never there.
#
# BOTH REFUSE THE WORK, and that is decided here once for every writer through
# `write_plan_file`. `_locks` calls an unwritable claim "refusing the LOCK, not
# the work" and leaves the work to the caller's other guard; a plan writer has
# none - the index lock IS the guard every verb, the panel and the repairs take,
# and each of them refuses on this same answer. A record written with no lock
# beside a verb mid-write is a lost write nothing reports; a refused record is
# exit 3 with the run's ledger row standing, which `--reconcile` catches up once
# the directory is writable. So the cost of a read-only state directory is a
# loud refusal, never a quiet race.
INDEX_BUSY_HEAD = "the %s lock was not free within" % (SHARD_LOCK_LABEL,)


def index_lock_busy(text):
    """True when `text` - a refusal, or a command's words carrying one - says
    the plan's index lock was held past the wait (`INDEX_BUSY_HEAD`), the one
    refusal a later run of the same command can get past by waiting."""
    return INDEX_BUSY_HEAD in (text or "")


def unwritable_claim_reason(said, outcome="", repair=""):
    """The refusal for an index-lock claim that could not be written, from the
    lock's own first line (`said`, what `acquire` printed). It is not a report
    that the lock is held, and it says what to fix before the caller's repair."""
    first = [" ".join(str(s).split()) for s in said or [] if str(s).strip()]
    why = first[0] if first else "acquire answered exit %d" % (_locks.E_ERR,)
    return ("the %s lock's claim could not be written (%s): this is not a report "
            "that the lock is held - nobody was found holding it - and a plan "
            "file is not written without it, so %s. Make the lock directory "
            "writable, then %s" % (
                SHARD_LOCK_LABEL, why.replace("[audit-lock] ", ""),
                outcome or "nothing was written", repair or "run this again"))


def _unwritten(reason, refused=None):
    """`write_plan_file`'s answer for a write that did not happen."""
    return {"written": False, "reason": reason, "path": None,
            "releaseRefused": refused, "pointers": [], "answer": None}


def write_plan_file(project, path, change, note, session_id=None, wait=None,
                    outcome="nothing was written to the plan", repair="",
                    config=None):
    """Take `SHARD_LOCK`, read the plan file `path`, save what `change` makes of
    that read, give the lock back -> `{"written", "reason", "path",
    "releaseRefused", "pointers", "answer"}`.

    THE ONLY SAVE OF A PLAN FILE IN THIS MODULE (`lk1` reads the AST for it).
    `path` is the file written and nothing else is - a phase's shard, or the
    index (which is the whole plan in the one-file layout) - so the caller
    names the plan file it writes rather than this function deriving one.

    `change(body)` -> `(body to save | None, problem | None, answer)`, handed the
    file as read UNDER the lock. A problem is the refusal's sentence and nothing
    is saved; a None body with no problem is a change that found nothing to do
    (`written` False, `reason` None). `answer` comes back whole either way.

    A LIVE HOLDER IS WAITED OUT, not skipped: `wait` seconds (`_locks`'
    `WAIT_SECONDS` when None), then refused with a sentence and the file byte
    for byte as it was. A dead holder is NOT taken over here - that is a human's
    call, and the sentence says what to run (`lock_state`). A lock this run
    already holds (`ours`: a verb that launched this, or the session's own
    hand-held claim) is written under and not given back; a project with no
    lock scheme writes under the weaker guarantee it always had.

    `releaseRefused` is the sentence of a release the lock declined, which says
    another session took it over while this write ran.
    """
    state, detail = shard_lock_state(project, session_id=session_id,
                                     outcome=outcome, repair=repair)
    if state == "stale":
        return _unwritten(detail)
    code = None
    if state in ("free", "held"):
        said = []
        code = _locks.acquire(project, SHARD_LOCK, note=note,
                              session=session_id, out=said.append, wait=wait)
        if code == _locks.E_ERR:
            return _unwritten(unwritable_claim_reason(said, outcome, repair))
        if not _locks.held(code):
            bound = _locks.WAIT_SECONDS if wait is None else float(wait)
            return _unwritten("%s %gs (%s); %s" % (
                INDEX_BUSY_HEAD, bound,
                detail or " ".join(" ".join(str(s).split()) for s in said)
                or _locks.refusal(code, SHARD_LOCK),
                "; ".join(s for s in (outcome, repair) if s)))
    refused, answer, problem, pointers, saved = None, None, None, [], False
    try:
        try:
            body = _mio.read_json(path)
        except Exception as exc:
            problem = "cannot read %s: %s" % (
                _journal_io.repo_relative_or_token(project, path), exc)
        else:
            new, problem, answer = change(body)
            if new is not None and problem is None:
                try:
                    pointers = _mio.save_plan_json(path, new)
                    saved = True
                except Exception as exc:
                    problem = "cannot write %s: %s" % (
                        _journal_io.repo_relative_or_token(project, path), exc)
    finally:
        if _locks.took(code):
            rcode = _locks.release(project, SHARD_LOCK, session=session_id,
                                   out=lambda *_a: None)
            if rcode != 0:
                refused = _locks.release_refusal(rcode, SHARD_LOCK)
    if saved:
        _mio.report_redactions(
            path, pointers, project=project,
            append_from_cli_why=lambda root, entry: _journal_io.append_from_cli_why(
                root, entry, config=config))
    return {"written": saved, "reason": problem, "path": path if saved else None,
            "releaseRefused": refused, "pointers": pointers, "answer": answer}


def _phase_file(manifest_path, phase_id):
    """`(path, sharded)` -- the file a phase's runtime fields live in.

    Read off the RAW index rather than derived, because `_shard_name` is the
    writer's rule and a reader that re-derived it would drift the first time it
    changed."""
    index = _mio.read_json(manifest_path)
    for stub in (index.get("phases") or []):
        if isinstance(stub, dict) and str(stub.get("id")) == str(phase_id):
            shard = stub.get("shard")
            if shard:
                return os.path.join(os.path.dirname(os.path.abspath(manifest_path)),
                                    str(shard)), True
            return os.path.abspath(manifest_path), False
    return None, _mio.is_sharded(index)


def _set_pointer(body, scope, ids, pointer, sharded):
    """`(previous, problem)` -- put the pointer in place, and say what it replaced.

    The previous value is returned because the journal row that records the move
    names both ends: a row saying only where a field landed cannot be read as a
    transition, and this field moves repeatedly over one task's life.
    """
    phases = [body] if sharded else [
        p for p in (body.get("phases") or [])
        if isinstance(p, dict) and str(p.get("id")) == str(ids.get("phaseId"))]
    if not phases:
        return None, "no phase %r in this manifest" % (ids.get("phaseId"),)
    phase = phases[0]
    if scope == "phase":
        previous = phase.get(POINTER_KEY)
        phase[POINTER_KEY] = pointer
        return previous, None
    for task in (phase.get("tasks") or []):
        if isinstance(task, dict) and str(task.get("id")) == str(ids.get("taskId")):
            previous = task.get(POINTER_KEY)
            task[POINTER_KEY] = pointer
            return previous, None
    return None, "no task %r in phase %r" % (ids.get("taskId"), ids.get("phaseId"))


def write_pointer(project, manifest_path, scope, ids, row, session_id=None,
                  config=None, wait=None):
    """Point the plan at a recorded run.
    `{"written", "reason", "path", "releaseRefused"}`.

    `releaseRefused` is set when the plan-file lock declined to be given back --
    which says another session took it over while this pointer was being
    written. A write that succeeded is still `written: True`; what the sentence
    adds is that something else was writing beside it, and the caller prints it
    rather than the lock losing it.

    WRITES THE SHARD AND NEVER THE INDEX. A task commit that carried the index is
    what makes two parallel phases conflict on merge, and the pointer is a runtime
    field, so it belongs in the phase body exactly as `status` and `attempts` do.
    The write is `write_plan_file`'s: the shard is read under the lock every
    writer of it takes, and `wait` is that function's.

    Every `written: False` here is a DESIGNED outcome carrying a sentence, not an
    error path: a refused cache write leaves the ledger row standing, which is the
    only reachable partial state and the harmless one.
    """
    pointer = pointer_for(row)
    path, sharded = _phase_file(manifest_path, ids.get("phaseId"))
    if not path or not os.path.exists(path):
        return {"written": False,
                "reason": "no phase %r in this manifest" % (ids.get("phaseId"),),
                "path": None}

    def change(body):
        previous, problem = _set_pointer(body, scope, ids, pointer, sharded)
        return (None if problem else body), problem, previous
    got = write_plan_file(project, path, change, "recording test evidence",
                          session_id=session_id, wait=wait,
                          outcome=RECONCILE_OUTCOME, repair=RECONCILE_REPAIR,
                          config=config)
    if not got["written"]:
        return {"written": False, "reason": got["reason"], "path": None,
                "releaseRefused": got["releaseRefused"]}
    _say_moved(project, path, scope, ids, got["answer"], pointer, session_id,
               config)
    return {"written": True, "reason": None, "path": path,
            "releaseRefused": got["releaseRefused"]}


def _say_moved(project, path, scope, ids, previous, pointer, session_id, config):
    """The journal row saying the plan's pointer moved - the row every pointer
    write ends with. The shard write's redaction report stays with each write,
    beside its save, where the plan-writer contract reads it.

    ONLY AFTER THE WRITE. This row says the PLAN moved, and it is written after
    the move rather than beside the attempt: a refused write returns before
    reaching here, so the chain can never assert a transition that did not
    happen. That is the whole reason this is a second action and not the row
    `record()` already wrote -- that one's subject is the evidence file and it
    was true the moment it was written."""
    details = {"runId": pointer.get("runId"), "field": POINTER_KEY,
               "from": (previous or {}).get("runId"), "to": pointer.get("runId")}
    for key in ("taskId", "phaseId"):
        if ids.get(key) is not None:
            details[key] = str(ids[key])
    _journal_io.append_from_cli(project, {
        "action": ACTION_MOVED.get(scope, ACTION_MOVED["phase"]),
        "actor": {"sessionId": session_id, "via": "evidence"},
        "target": _journal_io.repo_relative_or_token(project, path),
        "summary": "%s %s now points at run %s (%s)"
                   % (scope, ids.get("taskId") or ids.get("phaseId"),
                      pointer.get("runId"), pointer.get("status")),
        "details": details,
    }, config=config)


# --- the record: the newest run of a subject, in its shard ----------------------
# THE RECORD IS THE RUN, NOT A POINTER AT ONE. `testEvidence` names a run and
# caches its verdict; `lastRun` holds what a reader of that run needs - its
# moments, its verdict and where the verdict came from, the identity it was
# measured under, the state it tested, what it printed beside the verdict, and
# each step - so no ledger row is needed to read it. The ledger row is still
# written beside it, unchanged; the record is the copy a later reader will take
# instead of the row.
#
# REPLACED, NEVER APPENDED: one record per subject, the newest. So the shard's
# size is bounded by one record per task and per phase, and a record's own size
# by the gate's width - `MAX_STEPS` steps, each with at most `MAX_FAILING`
# failing lines of at most `_journal_io.MAX_VALUE_CHARS`, and each path list at
# most `MAX_PATHS` - bounds a reader multiplies; past `RECORD_MAX_BYTES` the
# fields `RECORD_CUT_ORDER` names go first.
#
# `testEvidence` STAYS THE THREE-KEY POINTER, written from the record in the
# same write (`pointer_from_record`), so every reader of the pointer is
# unchanged and the pointer can be re-derived from the record at any time.
RECORD_KEY = "lastRun"
# SUFFICIENCY IS THE RULE, AND THE EXCEPTIONS ARE THE TABLE. A record carries
# every key its run's ledger row carries, under the row's own name and as the
# row holds it, except the keys named here, each with why no reader of the one
# seam (`read_rows`) reads it off a record. A hand list of the keys to KEEP
# was how a record came to give `followersOwed`, the reach reading and the
# observations back as None with nothing saying so; a list of the keys to
# LEAVE is decided once per key, and `rs1`/`rs2` in tests/test__evidence_io.py
# hold it to every key `row_for` can write, read off `row_for`'s own source,
# so a key added there and decided nowhere fails by name.
RECORD_NOT_CARRIED = {
    "v": "the ledger row format's version; a record's shape is the plan "
         "schema's `lastRun`, versioned with the plan that holds it",
    "prev": "a link of the ledger file's hash chain; a record stands in no "
            "chain - the plan file's history is git's",
    "hash": "a link of the ledger file's hash chain; a record stands in no "
            "chain - the plan file's history is git's",
    "ts": "crosses as `at`, the pointer's word for the same moment, and "
          "`record_row` gives it back as `ts`",
    "scope": "the record's place in the plan says it - a phase's own key or a "
             "task's - and `record_row` writes it back from there",
    "taskId": "the record's place in the plan says it - a phase's own key or a "
              "task's - and `record_row` writes it back from there",
    "phaseId": "the record's place in the plan says it - a phase's own key or "
               "a task's - and `record_row` writes it back from there",
    "treeMutated": "the same list as `observations.treeMutated`, which crosses "
                   "whole; `record_row` gives it back at the top level too",
    "selectionMiss": "written only on a run of `--full`, which writes no "
                     "record: the plan holds a full run as `held_run_record`",
    "selectionMissDropped": "written only on a run of `--full`, which writes "
                            "no record: the plan holds a full run as "
                            "`held_run_record`",
    "dirtyOutsideDropped": "written only on a run of `--full`, which writes "
                           "no record: the plan holds a full run as "
                           "`held_run_record`",
}
# The measured tree's key crosses as `testedState.treeKey`, the one field of
# `testedState.tree` a reader asks (`stored_verdict_moved`).
RECORD_TREE_KEY = "treeKey"
# THE RECORD'S OWN BYTE BOUND, over its compact JSON, and the fields that go
# first past it, in order. The multiplied bounds above hold every list, but a
# record holds a repeat's source run whole beside its own, so the sum is
# bounded here once. What goes is what decides nothing: the paths the runner
# named beside the work (`coverage` - reported, never enforced), first of the
# run a repeat carries and then of the run itself, then the paths a run moved
# (`treeMutated`), whose verdict word the run's `status` already carries, and
# last the base runs a red's reading keeps (`BASE_RUNS_KEY`), whose loss costs
# a base run measured again and never a verdict read wrong. Each
# field cut is named under `RECORD_CUT_KEY`, and `record_row` gives it back as
# None beside a basis naming this bound - never as a run that compared nothing.
RECORD_MAX_BYTES = 49152
RECORD_CUT_ORDER = ("repeatedRun.observations.coverage",
                    "observations.coverage",
                    "repeatedRun.observations.treeMutated",
                    "observations.treeMutated",
                    "baseRed.baseRuns")
RECORD_CUT_KEY = "recordCut"
# THE PATHS A REPEAT'S RECORD STORES ONCE, in the run it carries
# (`shared_with_repeated` writes them, `resolved_shared` - which `record_row`
# asks first - gives them back), and the paths a reader could not give back.
SHARED_KEY = "sharedWithRepeated"
SHARED_UNRESOLVED_KEY = "sharedUnresolved"
# Never shared as an equal subtree: what names the run itself, which a reader
# of the raw record (`pointer_from_record`, the replaced-launch list) takes
# without resolving; the keys that hold the carried run or say what the record
# lost; and the steps, which a whole repeat shares by derivation instead - the
# entry `steps` under `SHARED_KEY` always means "copied from the carried run,
# each naming it" (`_copied_steps`), never an equal list.
_NEVER_SHARED = ("runId", "at", "status", "reusedFrom", "launch",
                 "repeatedRun", "repeatedRunUnread", "recordCut",
                 "replacedLaunches", "gradedBy", "steps", "stepsDropped")
# The basis an observation cut from a record is read back with.
_CUT_BASIS = ("cut from this run's record, which was over its bound "
              "(RECORD_MAX_BYTES); the run's ledger row, where one was "
              "written, holds it")
# Which basis sentence speaks for each observation a cut removes.
_CUT_BASIS_KEY = {"coverage": "coverageBasis", "treeMutated": "treeBasis"}
# THE RUN A REPEAT COPIED, WHOLE, on the record of a run that repeated another's
# verdict in whole or in part: that run's own record (`run_record` of its row,
# carrying none of its own). One record per subject replaces the run it
# repeated, so without it a reader of records alone could not follow a repeat
# to the run that measured the tree - the binding's arm, and the next part
# repeat's source. Never nested: the run a repeat copies measured what it
# gives, so its own copy of an older run is not carried.
REPEATED_RUN_KEY = "repeatedRun"
# ...AND WHEN NO COPY OF THAT RUN COULD BE READ, the record says so here rather
# than leaving a repeat whose `steps` are `[]` to read as a run that ran no
# step: `{"runId", "basis"}` - the run named by `reusedFrom`, and why it is not
# carried. One design with `REPEATED_RUN_KEY`: a reader asks that key for where
# a repeat's steps came from, and this one only when it is absent. Present only
# on a repeat; never beside a carried run.
REPEAT_UNREAD_KEY = "repeatedRunUnread"
# The lines the recorder prints beside a recorded run and keeps on its record.
RECORD_LINE_KEYS = ("machine", "attribution")
# How long a record write waits for the plan-file lock (`SHARD_LOCK`) another
# writer holds before it is refused. A verb holds that lock for one structural
# write, so the wait is the overlap of two writes; a lock this run already holds
# (a verb that launched this gate) is written under and never waited out here.
RECORD_WAIT_SECONDS = 30.0


def _record_step(step, source=None):
    """One step of a record: every field its row's step carries - the row's
    step is already allow-listed and bounded (`_step`) - its failing lines
    cut again at `MAX_FAILING`, each at the journal's value bound, for a step
    handed in by a caller that did not. `source` is the `{runId, ts}` a step
    copied from another run names, set when the step itself does not already
    name one."""
    out = {}
    for key, value in step.items():
        if key == "failing":
            out[key] = [_journal_io._clip(str(line))
                        for line in (value or [])[:MAX_FAILING]]
            continue
        out[key] = value
    if source is not None and STEP_REUSED_KEY not in out:
        out[STEP_REUSED_KEY] = source
    if out.get(STEP_REUSED_KEY) is not None:
        # A copied step ran nothing here, so no duration is kept for it.
        out.pop("durationMs", None)
    return out


def run_record(row, lines=None, launch=None, source=None, bound=None):
    """The record of the run `row` (the ledger row `row_for` built) - the value
    a subject's `RECORD_KEY` holds - cut to `bound` bytes (`RECORD_MAX_BYTES`
    when None) by `bounded_record`.

    `lines` holds the machine and attribution lines the recorder printed beside
    the run; `launch` is the token a caller that started the run in the
    background passed, so it can find the record of exactly that run - the
    row's own `LAUNCH_KEY` when the caller passes none.

    A REPEAT, WHOLE OR IN PART, CARRIES THE RUN IT COPIED (`repeat_carried`):
    `source`, the ledger row of the run repeated (a record read as its row,
    `record_row`, serves), whole under `REPEATED_RUN_KEY`; and a whole repeat,
    which ran no step, takes its steps from it, each naming the run it came
    from. With no `source` the record says which run it could not carry
    (`REPEAT_UNREAD_KEY`), and `write_record` looks once more, under the lock,
    in the record it replaces - by the reuse rule the run repeated is the
    subject's newest, which is that record."""
    return finished_record(
        repeat_carried(_record_of(row, lines=lines, launch=launch), source),
        RECORD_MAX_BYTES if bound is None else bound)


def record_bytes(record):
    """The size `RECORD_MAX_BYTES` bounds: the record's compact JSON, in
    UTF-8 bytes."""
    return len(json.dumps(record, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False).encode("utf-8"))


def bounded_record(record, bound):
    """`record`, a NEW dict, with the fields of `RECORD_CUT_ORDER` dropped in
    that order until its `record_bytes` are within `bound`. Each field dropped
    is named under `RECORD_CUT_KEY` of the record that held it - the run's own,
    or the run a repeat carries (`REPEATED_RUN_KEY`) - so either one read back
    alone says what it lost. A record already within the bound is returned as
    it is, with no such key; one still over it once every field of the order
    is gone is kept, the cut named, since what is left is what a reader of the
    run needs."""
    if not isinstance(record, dict) or record_bytes(record) <= bound:
        return record
    out = json.loads(json.dumps(record))
    for dotted in RECORD_CUT_ORDER:
        if record_bytes(out) <= bound:
            break
        path = dotted.split(".")
        owner = out
        if path[0] == REPEATED_RUN_KEY:
            owner, path = out.get(REPEATED_RUN_KEY), path[1:]
        holder = owner
        for part in path[:-1]:
            holder = holder.get(part) if isinstance(holder, dict) else None
        if isinstance(holder, dict) and holder.get(path[-1]) is not None:
            holder.pop(path[-1])
            owner.setdefault(RECORD_CUT_KEY, []).append(".".join(path))
    return out


def _cut_observations(record, observations):
    """`observations` as `record_row` gives them back: each one this record
    cut (`RECORD_CUT_KEY`) present as None beside the basis saying it was cut,
    so a reader never reads a cut list as no comparison made."""
    out = dict(observations) if isinstance(observations, dict) else {}
    for dotted in record.get(RECORD_CUT_KEY) or []:
        path = str(dotted).split(".")
        if len(path) == 2 and path[0] == "observations":
            out[path[1]] = None
            if path[1] in _CUT_BASIS_KEY:
                out[_CUT_BASIS_KEY[path[1]]] = _CUT_BASIS
    return out


def record_carrying(project, row, lines=None, launch=None, config=None, *,
                    manifest_path):
    """`run_record` with the run a repeat copied looked up for it: the row of
    `reusedFrom.runId` among every recorded run (`read_rows` - the ledger and
    the records of the plan at `manifest_path`, the one the record is written
    to), so a caller holding only a repeat's row never writes the unread
    marker where the source was one lookup away.

    A read that raises leaves `source` unset, and the record then says it
    could not carry the run (`REPEAT_UNREAD_KEY`) rather than carrying nothing
    silently."""
    source = None
    if repeated_source_id(row):
        try:
            source = repeat_source(row, read_rows(
                project, config=config, manifest_path=manifest_path)["rows"])
        except Exception:                                      # noqa: BLE001
            source = None
    return run_record(row, lines=lines, launch=launch, source=source)


def repeat_source(row, rows=(), replaced=None, scope=None, ids=None):
    """The run the repeat `row` repeated, row-shaped, or None - THE ONE LOOKUP
    every writer of a record asks.

    First among `rows`, which a caller hands as `read_rows` returns them: the
    ledger's rows AND the plan's records, one entry per run. Then the record
    being replaced, `replaced` - `(scope, ids)` name its subject - which a
    writer reads under the lock: by the reuse rule the run repeated is the
    subject's newest, which is that record. A lookup among ledger rows alone
    found nothing for a run held only as a record - a clone or worktree whose
    ledger never had it - and the record written over that run then carried
    the unread marker, so the run the repeat names was readable nowhere."""
    wanted = repeated_source_id(row)
    if wanted is None:
        return None
    found = row_by_run(list(rows or []), wanted)
    if found is not None:
        return found
    if isinstance(replaced, dict) and str(replaced.get("runId")) == wanted:
        ids = ids or {}
        return record_row(replaced, scope, ids.get("taskId") if scope == "task"
                          else ids.get("phaseId"), ids.get("phaseId"))
    return None


# The keys `_record_of` shapes itself rather than copying: the moment, the
# tested state, the steps and their cut - and the keys only a record holds,
# which a run read back from a record (`record_row`) may still carry and which
# never cross into the record of another run.
_RECORD_SHAPED = ("at", "testedState", "steps", "stepsDropped",
                  "repeatedRun", "recordCut", "sharedWithRepeated")


def _record_of(row, lines=None, launch=None):
    """`run_record` with nothing carried from another run: every field of the
    row but `RECORD_NOT_CARRIED`, its tested state and its steps."""
    row = row if isinstance(row, dict) else {}
    record = dict((key, value) for key, value in row.items()
                  if key not in RECORD_NOT_CARRIED
                  and key not in _RECORD_SHAPED and value is not None)
    record["at"] = row.get("ts")
    state = row.get("testedState") if isinstance(row.get("testedState"),
                                                 dict) else {}
    tested = dict((k, v) for k, v in state.items()
                  if k not in ("tree", RECORD_TREE_KEY))
    tree = state.get("tree")
    if isinstance(tree, dict) and tree.get("key"):
        tested[RECORD_TREE_KEY] = tree["key"]
    elif state.get(RECORD_TREE_KEY):
        tested[RECORD_TREE_KEY] = state[RECORD_TREE_KEY]
    if tested:
        record["testedState"] = tested
    record.update(_record_steps(row.get("steps"), row.get("stepsDropped")))
    for key in RECORD_LINE_KEYS:
        said = (lines or {}).get(key)
        if said:
            record[key] = _journal_io._clip(str(said), limit=400)
    if launch:
        record[LAUNCH_KEY] = str(launch)
    return record


def _record_steps(steps, dropped=None, copied=None):
    """`{"steps"[, "stepsDropped"]}` - `steps` as a record keeps them, cut at
    `MAX_STEPS` with the cut counted on top of any the row already counted."""
    steps = [s for s in (steps or []) if isinstance(s, dict)]
    out = {"steps": [_record_step(s, copied) for s in steps[:MAX_STEPS]]}
    # The row's own count is carried even when the record cuts nothing more:
    # a row already cut at `MAX_STEPS` holds exactly that many steps, and a
    # record that dropped its count would read as a run that had no more.
    total = int(dropped or 0) + max(0, len(steps) - MAX_STEPS)
    if total:
        out["stepsDropped"] = total
    return out


def repeated_source_id(record):
    """The run a repeat's record names as repeated (`reusedFrom.runId`), or None
    on a measured run."""
    if not isinstance(record, dict) \
            or record.get(VERDICT_SOURCE) not in (REUSED, PART_REUSED):
        return None
    run = (record.get("reusedFrom") or {}).get("runId")
    return str(run) if run else None


def repeat_carried(record, source):
    """`record`, a NEW dict, with the run it repeated carried from `source` (a
    row-shaped run: a ledger row, or a record through `record_row`).

    A measured run, or a repeat already carrying its run, is returned as it is.
    A WHOLE repeat ran no step, so its steps are `source`'s, each naming the
    run it came from; a part repeat keeps its own steps, which already name
    theirs. `source`'s own record goes under `REPEATED_RUN_KEY` and carries no
    older run - the run a repeat copies measured what it gives. A `source` that
    is not the run `reusedFrom` names carries nothing: the record then says it
    could not read that run (`REPEAT_UNREAD_KEY`), which is what a repeat with no
    source says too."""
    wanted = repeated_source_id(record)
    if wanted is None or record.get(REPEATED_RUN_KEY) is not None:
        return record
    out = dict(record)
    if not isinstance(source, dict) or str(source.get("runId")) != wanted:
        out[REPEAT_UNREAD_KEY] = {
            "runId": wanted,
            "basis": "no copy of run %s reached the writer of this record - "
                     "it is carried from that run's ledger row or from the "
                     "record this one replaced, and neither was found where "
                     "the writer looked - so the steps it repeated are not "
                     "carried here and `steps` lists none of them" % (wanted,)}
        return out
    out.pop(REPEAT_UNREAD_KEY, None)
    if out.get(VERDICT_SOURCE) == REUSED and not out.get("steps"):
        out.pop("stepsDropped", None)
        out.update(_record_steps(
            source.get("steps"), source.get("stepsDropped"),
            {"runId": wanted, "ts": str(source.get("ts") or source.get("at"))}))
    carried = _record_of(source)
    # The base runs the source's reading kept are the subject's to carry, on
    # its own reading (`carry_kept_bases`), never a second copy here.
    if isinstance(carried.get(BASE_RED_KEY), dict):
        carried[BASE_RED_KEY] = dict(
            (k, v) for k, v in carried[BASE_RED_KEY].items()
            if k != BASE_RUNS_KEY)
    out[REPEATED_RUN_KEY] = carried
    return out


def _shared_paths(mine, theirs, prefix, depth):
    """The dotted paths under `mine` whose subtree - a dict or a list - is
    equal to the one at the same path under `theirs`, and longer than the
    path that would name it; a dict that differs is looked into one level
    further. Sorted, so a record is written the same way every time."""
    out = []
    for key in sorted(mine):
        if not prefix and key in _NEVER_SHARED:
            continue
        here, there = mine[key], (theirs or {}).get(key)
        path = "%s%s" % (prefix, key)
        if isinstance(here, (dict, list)) and here == there:
            if record_bytes(here) > record_bytes(path) + 1:
                out.append(path)
        elif isinstance(here, dict) and isinstance(there, dict) and depth > 0:
            out.extend(_shared_paths(here, there, path + ".", depth - 1))
    return out


def shared_with_repeated(record):
    """THE WRITE SIDE OF ONE RULE: `record`, a NEW dict, with each subtree
    equal to the same subtree of the run it carries (`REPEATED_RUN_KEY`)
    stored once - there - and its path named under `SHARED_KEY`. A repeat's
    record holds its source run whole beside its own fields, and a repeat
    answers many of the same questions with the same value (the reach
    reading, the observations it copied), so the second copy carries no
    information; a whole repeat's steps, which are the carried run's each
    naming it, are named `steps` and derived again on the read side. A
    record carrying no run, or sharing nothing, is returned as it is.
    `resolved_shared` is the read side."""
    if not isinstance(record, dict) or SHARED_KEY in record:
        return record
    source = record.get(REPEATED_RUN_KEY)
    if not isinstance(source, dict):
        return record
    paths = _shared_paths(record, source, "", 1)
    # A WHOLE REPEAT'S STEPS ARE ITS SOURCE'S, each naming the run it came
    # from (`repeat_carried`), so they are derived again rather than copied -
    # and only when deriving them gives back exactly what is stored.
    steps = dict((k, record[k]) for k in ("steps", "stepsDropped")
                 if k in record)
    if record.get(VERDICT_SOURCE) == REUSED and steps.get("steps") \
            and _copied_steps(source) == steps:
        paths.append("steps")
    if not paths:
        return record
    out = json.loads(json.dumps(record))
    for path in paths:
        if path == "steps":
            out.pop("steps", None)
            out.pop("stepsDropped", None)
            continue
        parts = path.split(".")
        holder = out
        for part in parts[:-1]:
            holder = holder[part]
        holder.pop(parts[-1])
    out[SHARED_KEY] = paths
    return out


def _copied_steps(carried):
    """`{"steps"[, "stepsDropped"]}` as a whole repeat takes them from the
    run it carries (`carried`, that run's record): its steps, each naming
    that run and its moment."""
    return _record_steps(carried.get("steps"), carried.get("stepsDropped"),
                         {"runId": str(carried.get("runId")),
                          "ts": str(carried.get("at"))})


def resolved_shared(record):
    """THE READ SIDE: `record`, a NEW dict, with every path `SHARED_KEY`
    names given back from the run it carries, as `shared_with_repeated`
    found it there; a record naming none is returned as it is. A path the
    carried run no longer holds is given back as nothing and named under
    `SHARED_UNRESOLVED_KEY`, never read as a run that held no such field."""
    if not isinstance(record, dict) or not record.get(SHARED_KEY):
        return record
    source = record.get(REPEATED_RUN_KEY)
    source = source if isinstance(source, dict) else {}
    out = dict((k, v) for k, v in record.items() if k != SHARED_KEY)
    lost = []
    for path in record.get(SHARED_KEY) or []:
        if path == "steps":
            if isinstance(source.get("steps"), list):
                out.update(_copied_steps(source))
            else:
                lost.append("steps")
            continue
        parts = str(path).split(".")
        value = source
        for part in parts:
            value = value.get(part) if isinstance(value, dict) else None
        if value is None:
            lost.append(str(path))
            continue
        holder = out
        for part in parts[:-1]:
            holder[part] = dict(holder.get(part) or {})
            holder = holder[part]
        holder[parts[-1]] = json.loads(json.dumps(value))
    if lost:
        out[SHARED_UNRESOLVED_KEY] = lost
    return out


def finished_record(record, bound):
    """A record as a plan holds it: cut to `bound` (`bounded_record`), then
    each subtree it shares with the run it carries stored once
    (`shared_with_repeated`) - in that order, so a cut is decided on the
    record a reader resolves and is never taken from one copy only."""
    return shared_with_repeated(bounded_record(record, bound))


def pointer_from_record(record):
    """The three-key pointer (`pointer_for`'s shape) a record stands for."""
    record = record if isinstance(record, dict) else {}
    return {"runId": record.get("runId"), "status": record.get("status"),
            "at": record.get("at")}


def record_stages(row, where):
    """`(stages, gaps)` - the gate and selection stage of a measured run, as
    `_task_timing.run_stages` builds them; a run that repeated another's
    verdict measured nothing and gives none."""
    if not isinstance(row, dict) or row.get(VERDICT_SOURCE) == REUSED:
        return [], []
    return _timing.run_stages(str(row.get("runId")), row.get(STARTED_KEY),
                              row.get("durationMs"), selection_ms(row), where)


def _holders(body, scope, ids, sharded):
    """`(subject, task, problem)` - the dict a pointer of `scope` lives on, the
    task `ids` names (None at phase scope with no task), or the sentence saying
    which of them is not there."""
    phases = [body] if sharded else [
        p for p in (body.get("phases") or [])
        if isinstance(p, dict) and str(p.get("id")) == str(ids.get("phaseId"))]
    if not phases:
        return None, None, "no phase %r in this manifest" % (ids.get("phaseId"),)
    phase = phases[0]
    task = None
    if ids.get("taskId") is not None:
        found = [t for t in (phase.get("tasks") or []) if isinstance(t, dict)
                 and str(t.get("id")) == str(ids.get("taskId"))]
        if not found:
            return None, None, "no task %r in phase %r" % (ids.get("taskId"),
                                                           ids.get("phaseId"))
        task = found[0]
    if scope == "phase":
        return phase, task, None
    if task is None:
        return None, None, "no task named for a task-scope record"
    return task, task, None


def write_record(project, manifest_path, scope, ids, record, stages=(),
                 session_id=None, wait=None, config=None):
    """Write `record` as the subject's `RECORD_KEY`, its pointer beside it and
    `stages` onto the task's timing - one read and one write of the shard,
    through `write_plan_file`. `{"written", "reason", "path", "releaseRefused",
    "record"}`, `record` being what was written.

    THE LOCK IS WAITED FOR, NOT SKIPPED. A pointer could be refused because the
    ledger row stood anyway; a record that is the only copy cannot. So a lock
    another writer holds is waited out for `wait` seconds (`RECORD_WAIT_SECONDS`)
    and only then refused, and a refusal leaves the shard byte for byte as it
    was. The shard is READ under the lock, never before it: a verb that wrote it
    while this waited keeps what it wrote, and a verb that waits on this write
    reads what it wrote.

    A REPEAT THAT COULD NOT CARRY ITS RUN LOOKS ONCE MORE HERE, under the lock:
    the run repeated is the subject's newest, which is the record this write
    replaces, so when that record is the run `reusedFrom` names it is carried
    (`repeat_carried`) - the source no ledger row is needed for."""
    wait = RECORD_WAIT_SECONDS if wait is None else wait
    path, sharded = _phase_file(manifest_path, ids.get("phaseId"))
    if not path or not os.path.exists(path):
        return {"written": False,
                "reason": "no phase %r in this manifest" % (ids.get("phaseId"),),
                "path": None}
    got = write_plan_file(
        project, path,
        lambda body: _put_record(body, scope, ids, sharded, record, stages),
        "recording a gate run", session_id=session_id, wait=wait,
        outcome="nothing was written to the plan",
        repair="re-run this gate with --record once the lock is free",
        config=config)
    if not got["written"]:
        return {"written": False, "reason": got["reason"], "path": None,
                "releaseRefused": got["releaseRefused"]}
    previous, written = got["answer"]
    _say_moved(project, path, scope, ids, previous,
               pointer_from_record(written), session_id, config)
    return {"written": True, "reason": None, "path": path,
            "releaseRefused": got["releaseRefused"], "record": written}


def _put_record(body, scope, ids, sharded, record, stages=()):
    """`write_plan_file`'s change for a record: `record` (carried from the
    record it replaces when it is a repeat of that run, and naming the
    launched runs it replaces - `replaced_launches`) and its pointer on the
    subject, `stages` on the task -> `(body, problem, (previous pointer,
    record written))`."""
    subject, task, problem = _holders(body, scope, ids, sharded)
    if problem is not None:
        return None, problem, None
    replaced = subject.get(RECORD_KEY)
    source = repeat_source(record, replaced=replaced, scope=scope, ids=ids) \
        if record.get(REPEAT_UNREAD_KEY) else None
    if source is not None:
        record = finished_record(repeat_carried(
            dict((k, v) for k, v in record.items() if k != REPEAT_UNREAD_KEY),
            source), RECORD_MAX_BYTES)
    # The base runs the replaced red kept, while this run reads its red
    # against the same commit (`carry_kept_bases`).
    record = carry_kept_bases(record, replaced)
    gone = replaced_launches(replaced, record)
    if gone:
        record = dict(record)
        record[REPLACED_KEY] = gone
    previous = subject.get(POINTER_KEY)
    subject[RECORD_KEY] = record
    subject[POINTER_KEY] = pointer_from_record(record)
    if task is not None and stages:
        task["timing"] = _timing.append_run_stages(task, stages)
    return body, None, (previous, record)


def subject_records(manifest_path, project=None):
    """`({(scope, subject id): (record, phase id)}, unreadable)` - every record
    the plan's files hold, read off the raw files so a shard is read as it is
    written, and the label of each plan file that would not read
    (`plan_bodies`, the one walk and its one rule)."""
    found = {}
    bodies, lost = plan_bodies(manifest_path, project)
    for _label, phase in bodies:
        if not isinstance(phase, dict):
            continue
        pid = str(phase.get("id"))
        if isinstance(phase.get(RECORD_KEY), dict):
            found[("phase", pid)] = (phase[RECORD_KEY], pid)
        for task in phase.get("tasks") or []:
            if isinstance(task, dict) and isinstance(task.get(RECORD_KEY), dict):
                found[("task", str(task.get("id")))] = (task[RECORD_KEY], pid)
    return found, lost


# --- one reader: the plan's records beside the older rows -----------------------
# A RECORD IS READ AS THE ROW OF ITS RUN. Every reader of recorded runs asks a
# row's questions - its subject, its moment, its identity, its steps - so a
# record is handed to them in the row's shape (`record_row`) and `read_rows`
# returns the union of the ledger's rows and the plan's records, one entry per
# run: a run both hold is the ledger's row, which carries every field the
# record does and more. Where each entry came from is `ROW_FROM_LEDGER` or
# `ROW_FROM_RECORD`, at the entry's index in `rowSources`.
ROW_FROM_LEDGER = "ledger"
ROW_FROM_RECORD = "record"


def record_row(record, scope, subject, phase_id):
    """`record`, the record of the subject `(scope, subject)` in phase
    `phase_id`, in the shape of its run's ledger row - a NEW dict: every
    field the record kept, under the row's own names; `at` as `ts`; the
    subject's ids where the row carries them; the tested state's tree key as
    the row's `tree`; and `observations.treeMutated` at the top level too, as
    the row holds it. An observation the record cut past its bound
    (`RECORD_CUT_KEY`) is None beside a basis saying so. What the record does
    not keep (`RECORD_NOT_CARRIED`, the chain) is absent, as it is on a row
    written before the field existed. A field the record stored once, in the
    run it carries (`SHARED_KEY`), is read from there (`resolved_shared`)."""
    record = resolved_shared(record if isinstance(record, dict) else {})
    row = dict((key, value) for key, value in record.items()
               if key not in _RECORD_SHAPED and key != "gradedBy"
               and value is not None)
    row["runId"] = str(record.get("runId") or "")
    row["ts"] = record.get("at")
    row["scope"] = str(scope)
    if scope == "task":
        row["taskId"] = str(subject)
    row["phaseId"] = str(phase_id)
    if record.get("stepsDropped") is not None:
        row["stepsDropped"] = record["stepsDropped"]
    state = record.get("testedState") if isinstance(
        record.get("testedState"), dict) else {}
    tested = dict((k, v) for k, v in state.items() if k != RECORD_TREE_KEY)
    if state.get(RECORD_TREE_KEY):
        tested["tree"] = {"key": state[RECORD_TREE_KEY]}
    row["testedState"] = tested
    row["steps"] = [dict(s) for s in record.get("steps") or []
                    if isinstance(s, dict)]
    if isinstance(record.get("observations"), dict) \
            or record.get(RECORD_CUT_KEY):
        row["observations"] = _cut_observations(record,
                                                record.get("observations"))
        if "treeMutated" in row["observations"]:
            row["treeMutated"] = row["observations"]["treeMutated"]
    return row


def records_of_bodies(bodies):
    """`[(row, label)]` - every record the phase bodies `bodies` (`[(label,
    phase body)]`, a body as its file holds it) carry, each as `record_row`
    reads it, with the run it repeated (`REPEATED_RUN_KEY`) beside it and the
    base runs its red's reading keeps (`BASE_RUNS_KEY`) as base-scope rows,
    and every full run a phase holds (`FULL_GATE_RUNS_KEY`) as the scope-full
    row `held_run_row` gives - once per run.

    A GROUP MEMBER'S COPY IS ITS CARRIER'S RUN. Group sign-off copies the
    carrier's record onto each member naming the carrier in `gradedBy`; the
    ledger holds that run once, under the carrier, so the copy is read under
    the carrier too, and only where the carrier's own record no longer holds
    it."""
    carried, copies = [], []
    for label, phase in bodies or []:
        if not isinstance(phase, dict):
            continue
        pid = str(phase.get("id"))
        held = [("phase", pid, phase.get(RECORD_KEY))] + [
            ("task", str(t.get("id")), t.get(RECORD_KEY))
            for t in phase.get("tasks") or [] if isinstance(t, dict)]
        for scope, subject, record in held:
            if not isinstance(record, dict) or not record.get("runId"):
                continue
            graded = record.get("gradedBy") if scope == "phase" else None
            owner = str(graded) if graded else subject
            owner_phase = owner if scope == "phase" else pid
            # THE RUN REPEATED IS READ FIRST, as the ledger appended it first:
            # `oldest_first` gives a tie of moments to the row read later, and
            # a repeat made within the second of its source must still be the
            # newer of the two.
            runs = []
            repeated = record.get(REPEATED_RUN_KEY)
            if isinstance(repeated, dict) and repeated.get("runId"):
                runs.append(record_row(repeated, scope, owner, owner_phase))
            runs.append(record_row(record, scope, owner, owner_phase))
            # A base run kept with a red's reading is read as the base-scope
            # row it was recorded as: a run of no subject (`keep_base`).
            reading = resolved_shared(record).get(BASE_RED_KEY)
            runs.extend(record_row(base, BASE_SCOPE, None, pid)
                        for base in kept_bases(reading))
            (copies if graded else carried).extend((r, label) for r in runs)
        # The full runs the phase holds, each as the scope-`full` row it was
        # recorded as; a run two phases hold is read once, below.
        full_runs = phase.get(FULL_GATE_RUNS_KEY)
        carried.extend((row, label) for row in (
            held_run_row(h)
            for h in (full_runs if isinstance(full_runs, list) else []))
            if row is not None)
    seen, out = set(), []
    for row, label in carried + copies:
        if row["runId"] not in seen:
            seen.add(row["runId"])
            out.append((row, label))
    return out


def walk_plan(index_path, read, label, join):
    """`(bodies, unreadable)` - THE ONE WALK over a plan's files, wherever
    they are read from: every phase body as `[(label, body)]` - the index's
    own phases, or each shard it names - and the label of each plan file
    that would not read.

    `read(path)` gives one file's parsed JSON, None when there is no such
    file, and raises when there is one that will not read; `label(path)`
    names a file for a reader; `join(index_path, shard)` is where a stub's
    shard lives. The disk (`plan_bodies`) and a branch tip as git holds it
    (`close-phase.py`'s `tip_bodies`) are the two readers.

    ONE RULE FOR A FILE THAT WILL NOT READ: it is named in `unreadable`,
    never skipped. An index that is not there is no plan, so no file is
    named; a shard the index names and that is not there IS named - the
    plan says a phase lives there and nothing could be read of it, which a
    reader of its runs cannot tell from a phase that recorded none."""
    try:
        index = read(index_path)
    except Exception:
        return [], [label(index_path)]
    if index is None:
        return [], []
    bodies, lost = [], []
    for stub in (index.get("phases") or []) if isinstance(index, dict) else []:
        if not isinstance(stub, dict):
            continue
        if not stub.get("shard"):
            bodies.append((label(index_path), stub))
            continue
        path = join(index_path, str(stub["shard"]))
        try:
            body = read(path)
        except Exception:
            body = None
        if isinstance(body, dict):
            bodies.append((label(path), body))
        else:
            lost.append(label(path))
    return bodies, lost


def _disk_json(path):
    """One plan file's parsed JSON off the disk, None when there is none."""
    if not os.path.exists(path):
        return None
    return _mio.read_json(path)


def plan_bodies(manifest_path, project=None):
    """`(bodies, unreadable)` - `walk_plan` over the plan at `manifest_path`
    on the disk, read off the raw files so a shard is read as it is written.
    A label is the file's path relative to `project`, or the path itself
    with none."""
    def label(path):
        return (repo_relative_or_token(project, path) if project
                else str(path))
    return walk_plan(
        manifest_path, _disk_json, label,
        lambda index, shard: os.path.join(
            os.path.dirname(os.path.abspath(index)), shard))


def lost_in_read(project, read):
    """Every file `read` (`read_rows`' answer) could not read in full - the
    ledger's files, then the plan's - each relative to `project`."""
    read = read if isinstance(read, dict) else {}
    return [repo_relative_or_token(project, p) if os.path.isabs(str(p))
            else str(p)
            for p in (list(read.get("unreadableFiles") or [])
                      + list(read.get("unreadablePlanFiles") or []))]


def run_not_found(project, read, manifest_path, run_id, config=None):
    """The sentence for run `run_id` not among `read`'s runs (`read_rows`'
    answer over the plan at `manifest_path`), naming BOTH places it was
    looked for - the evidence ledger's directory, said as not existing when
    it does not, and the plan file whose records were read - and, when
    either place could not be read in full, naming those files: the run may
    be in what that read lost, which is not the same answer as no run."""
    read = read if isinstance(read, dict) else {}
    ledger = repo_relative_or_token(project, evidence_dir(project, config))
    if read.get("ledgerAbsent"):
        ledger = "%s, which does not exist" % (ledger,)
    plan = repo_relative_or_token(project, manifest_path)
    lost = lost_in_read(project, read)
    if lost:
        return ("no run %s is among the readable rows of the evidence ledger "
                "(%s) or the records the plan (%s) holds, and %s could not be "
                "read in full - the run may be in what that read lost, so "
                "repair it before asking again"
                % (run_id, ledger, plan, ", ".join(lost)))
    return ("no run %s is in the evidence ledger (%s) or in any record the "
            "plan (%s) holds" % (run_id, ledger, plan))


def plan_file_of(project, config=None):
    """The plan file `project`'s config names - `plan_aliases`' resolution."""
    config = _journal_io.load_config(project) if config is None else config
    rel = (config or {}).get("manifestPath") or _journal_io.DEFAULT_MANIFEST
    return os.path.join(project, str(rel))


def with_records(rows, entries):
    """`(rows, added)` - `rows`, then every entry of `entries` (`[(row,
    label)]`, `records_of_bodies`' shape) whose run no row of `rows` carries,
    and the `(row, label)` pairs that were added. A run both hold is the row
    already in `rows`, given the launch token and the replaced launches
    (`REPLACED_KEY`) its record carries when the row has none - a NEW dict, so
    the caller's list is untouched."""
    out = list(rows or [])
    at = dict((str(r.get("runId")), i) for i, r in enumerate(out)
              if isinstance(r, dict) and r.get("runId"))
    added = []
    for row, label in entries or []:
        run = str(row.get("runId") or "")
        if not run:
            continue
        if run in at:
            mine = out[at[run]]
            merged = dict((k, row[k]) for k in (LAUNCH_KEY, REPLACED_KEY)
                          if row.get(k) and not mine.get(k))
            if merged:
                out[at[run]] = dict(mine, **merged)
            continue
        at[run] = len(out)
        out.append(row)
        added.append((row, label))
    return out, added


def run_by_launch(rows, token):
    """The run whose row or record carries the launch token `token`, newest
    by its moment, or None - how a caller that started a run in the
    background finds exactly that run (`run-test-gate.py --launch`)."""
    if not token:
        return None
    return newest_row([r for r in rows or [] if isinstance(r, dict)
                       and str(r.get(LAUNCH_KEY) or "") == str(token)])


# A LAUNCHED RUN WHOSE RECORD ANOTHER RUN REPLACED. The record is the subject's
# newest run, so a run recorded after a launched one takes its place; with no
# ledger row of the launched run left to read, the caller that launched it
# could only wait for a run that has already ended. So the record that
# replaces one carrying a launch token names that run here -
# `[{"runId", "launch", "status", "at"}]`, newest first, the list it replaced
# carried on behind it and cut at `REPLACED_KEEP` - and the caller is told its
# run was replaced, and by which run (`replaced_by`).
REPLACED_KEY = "replacedLaunches"
REPLACED_KEEP = 8


def replaced_launches(replaced, record):
    """`REPLACED_KEY`'s list for `record`, the record written over `replaced`:
    `replaced`'s run when it carries a launch token and is not `record`'s run,
    then the launched runs `replaced` itself replaced."""
    if not isinstance(replaced, dict):
        return []
    out = []
    if replaced.get(LAUNCH_KEY) and str(replaced.get("runId")) \
            != str((record or {}).get("runId")):
        out.append(dict((k, str(replaced[k]))
                        for k in ("runId", LAUNCH_KEY, "status", "at")
                        if replaced.get(k) is not None))
    out.extend(e for e in replaced.get(REPLACED_KEY) or []
               if isinstance(e, dict))
    return out[:REPLACED_KEEP]


def replaced_by(rows, token):
    """`(the replaced run's entry, the row of the run whose record replaced
    it)` for the launched run carrying `token`, or None - asked when no run
    carries the token (`run_by_launch`): the newest row naming that token in
    its `REPLACED_KEY`."""
    if not token:
        return None
    hits = [(e, r) for r in rows or [] if isinstance(r, dict)
            for e in r.get(REPLACED_KEY) or []
            if isinstance(e, dict) and str(e.get(LAUNCH_KEY)) == str(token)]
    newest = newest_row([r for _e, r in hits])
    return ([(e, r) for e, r in hits if r is newest] or [None])[0]


# --- who ran it, when, and who else was running --------------------------------
def _epoch(text):
    """A stamp naming a time of day, as the WHOLE epoch second it fell in, or
    None when it names no such moment.

    `stamp_moment` READS IT, so a window and an order agree about when a run
    happened: a stamp with an offset or a fractional second places a run in
    the same second its Z spelling does, where a parser of the Z form alone
    left that run with no window at all. The second is floored because
    `overlap_state` reasons in whole seconds - a stamp names the second an
    instant fell in. A bare date is refused (`day_start=False`): it names a
    day, not the second a run ended, and a window built from midnight would be
    a guess recorded as an overlap. So is a time with NO ZONE (`Z` or an
    offset): `parse_ts` reads one as UTC, which is right for a stamp a machine
    wrote and a time zone wrong for a start somebody typed in local time.

    None rather than a substitute: a stamp this cannot read is a row that cannot
    take part in an overlap question, and a zero would put it at the start of the
    epoch where it would overlap nothing and look like an answer.
    """
    if not isinstance(text, str) or not _ZONED.search(text.strip()):
        return None
    moment = stamp_moment(text, day_start=False)
    return None if moment is None else int(math.floor(moment))


# A stamp's trailing zone designator - what `_epoch` requires before it reads
# the stamp at all. Not a parser: `stamp_moment` does the reading.
_ZONED = re.compile(r"(?:[Zz]|[+-]\d{2}:?\d{2})$")


def runner_of(row):
    """Which runner made this row: `RUNNER_GATE`, `RUNNER_OUTSIDE`, or the word
    the row carries when it is neither.

    ABSENT IS THE GATE, which is a fact about the corpus and not a default
    covering a gap: every row written before `RUNNER_KEY` existed was made by the
    wrapper, because the wrapper was the only writer there was. An unrecognised
    word is returned unchanged rather than folded into either answer -- a reader
    asking "was this the gate's own run" gets `False` for it, which is the safe
    reading, and the word itself so the surface can say what it found.
    """
    if not isinstance(row, dict):
        return RUNNER_GATE
    value = row.get(RUNNER_KEY)
    if value is None:
        return RUNNER_GATE
    return str(value)


def selection_ms(row):
    """The milliseconds a run spent choosing what to run, or None when the row
    did not record it - a row from before `SELECTION_KEY` existed, or a value
    that is not a whole non-negative duration. None and never 0: a reader
    summing or comparing selection times must see the rows that cannot answer,
    not fold them in as instant selections."""
    if not isinstance(row, dict):
        return None
    value = row.get(SELECTION_KEY)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def window_of(row):
    """`(start, end, basis)` in epoch seconds — when this run was happening.

    `(None, None, why)` when the row cannot say, and that is a THIRD answer
    rather than a failure: an overlap computed against a window nobody knows is
    the shape in which a guess gets recorded as a finding.

    TWO WAYS TO A START, AND THE BASIS NAMES WHICH. `startedAt` is the recorded
    one. A row written before that key existed carries `ts` (the moment the row
    was BUILT, after the run) and `durationMs` (a monotonic elapsed reading), and
    subtracting one from the other lands within the recording overhead of the
    real instant -- close enough to ask an overlap question with, and not the
    same kind of fact, so it is labelled.
    """
    if not isinstance(row, dict):
        return (None, None, "not a row")
    end = _epoch(row.get("ts"))
    if end is None:
        return (None, None, "the row carries no readable `ts`, so nothing "
                            "places it in time")
    started = _epoch(row.get(STARTED_KEY))
    if started is not None:
        return (started, end, "recorded: `%s` and `ts`" % (STARTED_KEY,))
    duration = row.get("durationMs")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        return (None, None, "the row records no `%s` and no `durationMs`, so "
                            "its start is not knowable" % (STARTED_KEY,))
    return (end - int(duration // 1000), end,
            "derived: `ts` less `durationMs`, because this row predates `%s`"
            % (STARTED_KEY,))


OVERLAP_YES, OVERLAP_NO, OVERLAP_UNDECIDED = "yes", "no", "undecided"


def overlap_state(one, other, ordered=False):
    """Whether two `(start, end)` windows, in WHOLE seconds, share a moment:
    `OVERLAP_YES`, `OVERLAP_NO`, or `OVERLAP_UNDECIDED` when the stamps cannot say.

    A stamp names the second an instant fell in, never the instant. Windows
    sharing a whole second or more overlap; windows with a second between them do
    not. What is left is two windows MEETING in one second - one ending in second
    t, the other starting in t, or a run shorter than a second stamped in the
    other's start or end second. Both instants fell inside that second in an
    order the stamps do not record, so the answer is UNDECIDED - unless `ordered`:
    the caller has established the two runs happened one after the other
    (`chain_ordered`), and then the shared second is sequential."""
    s1, e1 = one
    s2, e2 = other
    meeting = OVERLAP_NO if ordered else OVERLAP_UNDECIDED
    if s1 == e1 or s2 == e2:
        point, (s, e) = (s1, (s2, e2)) if s1 == e1 else (s2, (s1, e1))
        if s == e:
            return meeting if point == s else OVERLAP_NO
        if s < point < e:
            return OVERLAP_YES
        return meeting if point in (s, e) else OVERLAP_NO
    if s1 < e2 and s2 < e1:
        return OVERLAP_YES
    return meeting if (e1 == s2 or e2 == s1) else OVERLAP_NO


def chain_index(rows, seams):
    """The lookups `chain_ordered` walks, built once for a reader's whole pass:
    `{"byId", "byHash", "relinked"}`.

    `relinked` is the set of hashes inside a RE-CHAINED STRETCH - the rows a
    ledger merge linked in timestamp order across two branches (`merge_seams`),
    from the row after `relinkedAfter` through `relinkedThrough`. A stretch
    whose end is no longer in the rows (a later merge re-chained it again) runs
    to the end of its chain, so an unlocatable end widens the refusal rather
    than narrowing it. EACH STRETCH IS WALKED ON ITS OWN, with its own record
    of where it has been: a later merge's stretch routinely starts inside an
    earlier one whose hashes survived it, and stopping at a row another
    stretch already holds would let an earlier merge row - real or forged -
    cut a later one short. `seams` None means nobody could say whether the ledger
    was ever merged, and then `relinked` is None too."""
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    by_id = dict((str(r.get("runId")), r) for r in rows if r.get("runId"))
    by_hash = dict((r.get("hash"), r) for r in rows if r.get("hash"))
    relinked = None
    if seams is not None:
        after_of = dict((r.get("prev"), r) for r in rows if r.get("prev"))
        relinked = set()
        for after, through in seams:
            seen, cur = set(), after_of.get(after)
            while isinstance(cur, dict) and cur.get("hash") not in seen:
                seen.add(cur.get("hash"))
                relinked.add(cur.get("hash"))
                if cur.get("hash") == through:
                    break
                cur = after_of.get(cur.get("hash"))
    return {"byId": by_id, "byHash": by_hash, "relinked": relinked}


def chain_ordered(rows, one, other, seams=None, index=None):
    """Did `one` and `other` run one after the other, as ONE gate writer's chain
    records them?

    A row's `prev` names the `hash` of the row appended before it in the same
    writer's file, so following `prev` from one row and reaching the other says
    which was WRITTEN later. That is taken for the order the runs happened in
    under an ASSUMPTION nothing enforces - that one writer file runs its gates
    one at a time - and only where the windows agree with it: the later-written
    run must start at or after the earlier run ended. A long run written after
    a sub-second one began before that one's row existed, which one-at-a-time
    cannot produce, so the pair is not ordered.

    NOT ORDERED EITHER, each for its own reason:
      * an OUTSIDE run - its row is written by this plugin, but the suite ran
        where no chain watched it;
      * a row inside a re-chained stretch of a merged ledger (`chain_index`) -
        there `prev` is the timestamp order a merge chose between two
        branches, not one writer's appends;
      * any pair when `seams` is None - nobody could say whether the ledger
        was ever merged, so no chain is read as a writer's order.

    A row passed without its chain keys (the run just recorded) is matched to
    its copy on disk by `runId`. `index` is `chain_index(rows, seams)`, passed
    by a reader asking about many pairs so the lookups are built once."""
    if runner_of(one) != RUNNER_GATE or runner_of(other) != RUNNER_GATE:
        return False
    index = chain_index(rows, seams) if index is None else index
    if index["relinked"] is None:
        return False
    by_id, by_hash = index["byId"], index["byHash"]
    one = by_id.get(str(one.get("runId")), one)
    other = by_id.get(str(other.get("runId")), other)
    if not (one.get("hash") and other.get("hash")):
        return False
    if one["hash"] in index["relinked"] or other["hash"] in index["relinked"]:
        return False

    def reaches(start, target):
        seen, cur = set(), start
        while isinstance(cur, dict) and cur.get("prev") and cur["prev"] not in seen:
            seen.add(cur["prev"])
            cur = by_hash.get(cur["prev"])
            if cur is target:
                return True
        return False
    if reaches(one, other):
        later, earlier = one, other
    elif reaches(other, one):
        later, earlier = other, one
    else:
        return False
    began, _e, _w = window_of(later)
    _s, ended, _w = window_of(earlier)
    return began is not None and ended is not None and began >= ended


def _overlaps(one, other):
    """Whether two windows DEFINITELY share a moment (`overlap_state`)."""
    return overlap_state(one, other) == OVERLAP_YES


def overlapping_runs(rows, row, runner, seams=None):
    """`(overlapping, basis)` — the OTHER runs made by `runner` whose window
    overlaps `row`'s.

    `overlapping is None` means the question could not be asked, which is not the
    same answer as an empty list and must never be rendered like one: one says
    nothing else was running, the other says nobody could look.

    THE ROW ITSELF IS EXCLUDED BY `runId`, and that exclusion is the whole
    difference between this and a rule that fires on every run ever made. The
    rows a caller passes have been read back off disk, so identity cannot do it;
    without the id test a run alone on the machine finds ITSELF in the window it
    just occupied and is reported as contested, which is a rule that refuses
    every run there is and gets switched off within a day.

    THE RUNNER IS AN ARGUMENT because the two questions have different remedies
    and must not be folded into one list. An OUTSIDE run in the window means a
    suite this plugin cannot see was moving the same tree, and the answer is to
    re-run once it is finished; another GATE run in the window means two
    executors were invited onto one machine, and the answer belongs to whoever
    invited them.

    `seams` is `merge_seams(project)[0]`: where the ledger was re-chained by a
    merge, or None when that is not known - `chain_ordered` says what each
    answer lets a chain decide.
    """
    found, _undecided, basis = _classified(rows, row, runner, seams)
    return (found, basis)


def _classified(rows, row, runner, seams=None):
    """`(overlapping, undecided, basis)` for `row` against every OTHER run by
    `runner` - one pass, so a reader of either list reads one answer. Both are
    None when `row` has no window.

    THE WINDOWS DECIDE FIRST and the chain is asked only about a pair they leave
    undecided, with its lookups built once for the pass: a reader runs on every
    recorded gate run over the ledger's whole life, and a chain walk per pair
    made that quadratic in rows nobody's windows ever met. An OTHER run with
    no window of its own is undecided outright: its stamps place it nowhere,
    so neither overlap nor its absence is known."""
    start, end, basis = window_of(row)
    if start is None:
        return (None, None, basis)
    mine = str((row or {}).get("runId") or "")
    found, unsure, index = [], [], None
    for other in (rows or []):
        if not isinstance(other, dict):
            continue
        if mine and str(other.get("runId") or "") == mine:
            continue
        if runner_of(other) != runner:
            continue
        o_start, o_end, _why = window_of(other)
        if o_start is None:
            # NO WINDOW IS NOT "NOT RUNNING". Nothing places that run before,
            # inside or after this one, so it is undecided - skipping it read
            # as a run that never happened, and answered "alone".
            unsure.append(other)
            continue
        state = overlap_state((start, end), (o_start, o_end))
        if state == OVERLAP_UNDECIDED:
            index = chain_index(rows, seams) if index is None else index
            if chain_ordered(rows, row, other, seams, index):
                state = overlap_state((start, end), (o_start, o_end),
                                      ordered=True)
        if state == OVERLAP_YES:
            found.append(other)
        elif state == OVERLAP_UNDECIDED:
            unsure.append(other)
    return (found, unsure, basis)


def undecided_neighbours(rows, row, runner, seams=None):
    """The OTHER runs by `runner` that cannot be placed either side of `row`'s
    window - whole-second stamps meeting in one second (`OVERLAP_UNDECIDED`),
    or a run with no window at all - reported apart from the runs that did
    overlap, so a surface says it cannot tell rather than that the window was
    shared, or that nobody else ran. `[]` when `row` has no window."""
    return _classified(rows, row, runner, seams)[1] or []


def _undecided_basis(basis, unsure):
    """`basis`, extended by why each of `unsure` could not be placed."""
    named = ", ".join(
        "%s (%s)" % (str(o.get("runId") or "?"),
                     "no window: %s" % (window_of(o)[2],)
                     if window_of(o)[0] is None else
                     "its whole-second stamps meet this run's in one second")
        for o in unsure)
    return ("%s; whether %s ran outside this gate in the same window is not "
            "knowable" % (basis, named))


def contested_by(rows, row):
    """`(contesting, basis)` — the runs from OUTSIDE this gate whose window
    overlaps `row`'s, with the runner decided, so no caller can ask the outside
    question and get the machine one.

    THREE ANSWERS, AND `[]` IS ONLY ONE OF THEM. A non-empty list names the
    rivals. `[]` says no outside run could have shared the window. `None` says
    the question has no answer: `row` has no window, or - with no rival found -
    an outside run could not be placed either side of it (`undecided_neighbours`),
    because a run nothing places is not a run that did not happen, and reading
    it as `[]` claimed this run was alone."""
    found, unsure, basis = _classified(rows, row, RUNNER_OUTSIDE)
    if found is None or found:
        return (found, basis)
    if unsure:
        return (None, _undecided_basis(basis, unsure))
    return ([], basis)


def shared_the_machine(rows, row, seams=None):
    """`(others, basis)` — the other GATE runs whose window overlaps `row`'s.

    THE RULE THE PARALLEL-SAFETY RULE DID NOT HAVE. That rule is about the file
    system -- disjoint `files`, satisfied `dependsOn` -- and says nothing about
    the machine, which is the largest source of false failures on record here: a
    full suite takes the cores, the ports and the scratch directories, and two of
    them on one host produce reds neither change caused.

    IT REPORTS AND NEVER REFUSES, which is this file's standing division between
    a verdict and an observation beside it. A run that was alone on the machine
    gets an empty list and must be told it was alone -- a rule that refused a
    solo run would be refusing the ordinary case, which is how a rule gets routed
    around instead of read.
    """
    return overlapping_runs(rows, row, RUNNER_GATE, seams)


def attribution_of(row, rows):
    """`{"attributed", "contested", "basis"}` — whether this row's verdict is
    this gate's to claim.

    `attributed` is THREE-VALUED. `True` says nothing else was running in this
    run's window, so the verdict is the gate's; `False` says a suite the plugin
    does not control was running at the same time, so the verdict is contested
    and the red may be either run's; `None` says the question could not be asked,
    and `basis` says which piece was missing.

    IT DOES NOT MOVE THE VERDICT, and that is deliberate. `status` is what the
    commands answered and stays what they answered -- the same division
    `run-test-gate` already draws between a verdict and an observation beside it.
    What a contested red buys a reader is the one thing that was missing when a
    push's suite overlapped a recorded gate and the plugin reported the red as
    its own: a named rival, with its own row, instead of a conclusion about the
    work.
    """
    contesting, basis = contested_by(rows, row)
    if contesting is None:
        # NEITHER CLAIM IS MADE: this run has no window, or an outside run could
        # not be placed either side of it, so the verdict is not asserted as
        # this run's - and not as contested either.
        return {"attributed": None, "contested": [], "basis": basis}
    if not contesting:
        return {"attributed": True, "contested": [],
                "basis": "%s; no run from outside this gate shares that window"
                         % (basis,)}
    return {"attributed": False,
            "contested": [str(o.get("runId") or "?") for o in contesting],
            "basis": "%s; and %s ran outside this gate in the same window, so "
                     "this verdict is not this run's alone to claim"
                     % (basis, ", ".join(str(o.get("runId") or "?")
                                         for o in contesting))}


def subject_aliases(manifest):
    """`{("task", oldId): ("task", liveId)}` for every id a live task was moved from.

    THE LEDGER KEEPS THE SUBJECT A RUN WAS RECORDED UNDER, and `move` gives the
    task a new id. Rewriting append-only rows is not on offer, so the readers
    map through the plan instead: `movedFrom` and the `previous` links inside it
    are exactly the ids this task used to answer to.

    AN ALIAS ONLY WHERE IT IS UNAMBIGUOUS. An old id a live task holds now is
    that task's, and aliasing it away would move its own runs onto another; an
    old id two chains both claim has no single owner. Verb-made plans reach
    neither (the allocator never mints a chain's id), so both are skipped here
    rather than guessed at, and `_manifest_phases` warns about each by name.
    """
    live = set(str(t.get("id")) for _ph, t in _mio.iter_tasks(manifest or {})
               if t.get("id"))
    claims = {}
    for _ph, task in _mio.iter_tasks(manifest or {}):
        if not task.get("id"):
            continue
        for old in _mio.moved_from_ids(task):
            claims.setdefault(old, set()).add(str(task.get("id")))
    return dict((("task", old), ("task", next(iter(owners))))
                for old, owners in claims.items()
                if len(owners) == 1 and old not in live)


def subject_key(row, aliases=None):
    """The `(scope, id)` a pointer for `row` is written under, or None.

    ONE KEY FUNCTION, read by `latest_by_subject` and by the ledger merge's
    `merge_targets`: whether two runs' order decides a pointer is a question
    about this key, so it has exactly one spelling. A task-scope row is keyed by
    its task, anything else by its phase, and a moved task's old id by the id it
    holds now (`aliases`). None for a row missing the id its scope needs, and
    for a `BASE_SCOPE` row, which is no subject's evidence.
    """
    if not isinstance(row, dict):
        return None
    scope = row.get("scope")
    subject = row.get("taskId") if scope == "task" else row.get("phaseId")
    if not scope or not subject or scope == BASE_SCOPE:
        return None
    key = (scope, str(subject))
    return (aliases or {}).get(key, key)


def latest_by_subject(rows, aliases=None):
    """The newest recorded run per `(scope, id)`, keyed for a pointer write.

    NEWEST BY `ts` AND NOT BY FILE ORDER. Rows land in one file per writer per
    month, so two worktrees produce two files whose concatenation is in no
    meaningful order at all; reading position would make "the latest run" depend
    on a directory listing.

    A row missing the id its own scope needs is skipped rather than guessed at -
    it cannot be pointed at anything, and inventing a subject for it would put a
    pointer on a task that never ran.

    `aliases` is `subject_aliases(plan)`: a row recorded under a task's old id is
    keyed under the id the task holds now, so a moved task's runs still join it.

    Newest by the MOMENT `ts` names: rows are walked in `oldest_first` order,
    so the last one each key keeps is its newest.
    """
    best = {}
    for row in oldest_first(rows):
        key = subject_key(row, aliases)
        if key is None or not row.get("runId"):
            continue
        best[key] = row
    return best


def row_by_run(rows, run_id):
    """The row carrying `runId == run_id`, newest by `ts`; `None` when none do.

    BESIDE `latest_by_subject` AND NOT A SPECIAL CASE OF IT, because the
    question a caller already holding a `runId` asks is different: it does not
    need to know whose subject the run belonged to, only to find the run again
    - a retry's own row, a fixture a failed-first fix task was opened from. NEWEST
    BY `ts`, not by file order, for `latest_by_subject`'s own reason: nothing
    here declares `runId` unique across every writer this project's worktrees
    keep, so a second row claiming the same id is read as a later one rather
    than as an error neither caller can act on.

    NEWEST BY THE MOMENT `ts` NAMES (`newest_row`), never by its spelling, so a
    run whose every stamp is unreadable is still found.
    """
    if not run_id:
        return None
    return newest_row([row for row in rows or [] if isinstance(row, dict)
                       and str(row.get("runId") or "") == str(run_id)])


# The one status a recorded run is green under.
RUN_PASSED = "passed"
# The statuses of a run that reached a verdict - every step it started ran to
# its end - and so the only ones whose durations measure the gate.
MEASURED_STATUSES = (RUN_PASSED, "failed")


def row_is_red(row):
    """Whether the run `row` records exited red - its `status` is anything
    but `passed`.

    THE RUNNER'S OWN READING, NOT A SECOND ONE: `run-test-gate.py` exits 0
    exactly when a run's status is `passed` and non-zero for every other
    word, so a status no writer has produced yet, or none at all, is red
    here as it is there. Widening green to "not named failed" would read a
    new word - or a row missing the field - as a pass nobody measured."""
    return row.get("status") != RUN_PASSED


def suite_keys(rows):
    """`{"running", "silent", "unknown"}` - every step NAME, sorted into what its
    OWN recorded `suiteReader` says across every row that ever carried it.

    THE ONE LEDGER ANSWER `_manifest_phases.phase_gate_suite_gap` NEEDS for its
    second arm: a default gate key like `npm test` is not test-shaped by its
    spelling, so whether it runs a suite has to come from what was actually
    recorded rather than from guessing at the name.

    RUNNING beats every other reading for a name: one row recording `jest` for
    `"test"` is enough to call `"test"` a suite-running key forever, because a
    name that ran a suite even once has answered the question this asks.
    SILENT is a name that carried `suiteReader` in every row it ever appeared
    in and never once as anything but `"none"`. UNKNOWN is a name that appears
    ONLY in rows recorded before the field existed - `suiteReader` absent
    outright, never `"none"`, which is exactly the distinction the field was
    written rather than left absent to preserve: treating an absent field as
    `"none"` would call a step this gate never looked at SILENT, which is a
    stronger claim than this ledger can make about it.

    A NAME SEEN BOTH WAYS IS NOT UNKNOWN. The moment any row records the field
    for a name, that name has an answer this ledger CAN give, and it is
    RUNNING or SILENT - unknown is reserved for a name the field has never once
    reached.
    """
    running, has_field, no_field = set(), set(), set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        for step in row.get("steps") or []:
            if not isinstance(step, dict):
                continue
            name = step.get("name")
            if not name:
                continue
            if "suiteReader" not in step:
                no_field.add(name)
                continue
            has_field.add(name)
            if step.get("suiteReader") != "none":
                running.add(name)
    silent = has_field - running
    unknown = no_field - has_field - running
    return {"running": sorted(running), "silent": sorted(silent),
           "unknown": sorted(unknown)}


def _same_subject(row, ids):
    """Do a row and a set of identity keys name the same work?

    Compared as strings and with ABSENT kept distinct from any value, which is
    `row_for`'s own rule read back: a phase-scope row carries no `taskId` at all,
    and letting a missing key match a present one would hand a phase's verdict to
    a task.

    A FULL-SCOPE ROW HAS NEITHER, AND A THIRD ARM COVERS IT. `taskId` and
    `phaseId` are both absent on every full row alike, so the loop above passes
    every one of them against every other -- a plan never asks a full run's
    verdict about a task or a phase, it asks about the TREE that run measured.
    `testedState.head` is what says which tree that was, so a caller comparing
    full-scope subjects passes it under `ids["head"]` and this is where it is
    read back, with the same absent-is-distinct rule as the pair above.
    """
    for key in ("taskId", "phaseId"):
        left = row.get(key)
        right = (ids or {}).get(key)
        if (left is None) != (right is None):
            return False
        if left is not None and str(left) != str(right):
            return False
    if row.get("scope") == FULL_SCOPE:
        left = (row.get("testedState") or {}).get("head")
        right = (ids or {}).get("head")
        if (left is None) != (right is None):
            return False
        if left is not None and str(left) != str(right):
            return False
    return True


def reusable_run(rows, scope, ids, key, statuses, steps=None):
    """The newest recorded run a caller may repeat instead of measuring, or None.

    `steps` names the steps a caller repeats when it repeats only some of its
    gate (the rest it measures, `PART_REUSED`); None repeats the whole run. A
    row is a source for a named step only where it MEASURED that step - the
    step is on it, copies no other run (`step_repeated`) and reached a verdict
    (no `outcome`). So a `PART_REUSED` row is a candidate for the steps it
    measured and for no other, and never for a whole-run repeat; and when the
    newest candidate lacks a named step, the answer is None rather than an
    older row, for the newest-decides rule below.

    EVERY CONDITION NARROWS. The identity has to match, the
    subject has to be the same work and the row has to be a MEASUREMENT rather
    than another repeat; the newest such row is then the only candidate, and it
    is repeated only if its verdict is one the caller says may be repeated and
    no mute excused it. Otherwise the answer is None - never an older row.
    Drop any of them and this returns a run that answers a different
    question.

    THE IDENTITY IS NOT THE SUBJECT, which is why both are asked. Two tasks can
    declare the same files and the same gate, and their runs would then share an
    identity; a repeated verdict has to NAME the run it came from, and a run
    about somebody else's task is not a thing to name.

    A ROW THAT WAS ITSELF A REPEAT IS SKIPPED, so the run a caller is pointed at
    is always the one that did the measuring. A chain would be a chain of copies,
    and the first reader to follow it would have to walk to find out whether
    anything was ever measured at all.

    `statuses` HAS NO DEFAULT. Which verdicts survive being repeated is a
    judgement about what a verdict MEANS, and it belongs to whoever produces
    them; a default here would be this file quietly deciding that an
    infrastructure failure is a property of the bytes.
    """
    if not key:
        return None
    # THE NEWEST VERDICT FOR THE IDENTITY DECIDES. A word the caller refuses to
    # repeat (the machine failed, the run timed out) is not a verdict about the
    # bytes and is passed over; a verdict a mute excused IS one, and it is the
    # newest, so it ends the search with no repeat rather than letting an older
    # red - which the tree has since moved past - be handed back instead.
    chosen = newest_row([r for r in _identity_measurements(rows, scope, ids, key,
                                                           steps)
                         if r.get("status") in statuses])
    # A VERDICT A MUTE EXCUSED holds only while the mute does, and whether
    # it still does depends on the day - which no content identity sees.
    if chosen is None or chosen.get("muted"):
        return None
    if steps is not None and not _measured_steps(chosen, steps):
        return None
    return chosen


def _measured_steps(row, names):
    """True when `row` MEASURED every step in `names`: each is on it, copies no
    other run, and reached a verdict - a step with an `outcome` (it timed out,
    could not start) is a fact about the machine, which a repeat would cache."""
    found = dict((s.get("name"), s) for s in row.get("steps") or []
                 if isinstance(s, dict))
    return all(name in found and not step_repeated(found[name])
               and not found[name].get("outcome") for name in names)


def _identity_measurements(rows, scope, ids, key, steps=None):
    """The rows that MEASURED something for this identity, scope and subject: a
    repeat copies a verdict and is not one, so it is left out - and a row that
    repeated part of its gate is one only for the `steps` it measured, and for
    a whole-run repeat (`steps` None) not at all."""
    found = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if row.get(REUSE_KEY) != key:
            continue
        if row.get(VERDICT_SOURCE) == REUSED:
            continue
        if row.get(VERDICT_SOURCE) == PART_REUSED and (
                steps is None or not _measured_steps(row, steps)):
            continue
        if str(row.get("scope") or "") != str(scope or ""):
            continue
        if not _same_subject(row, ids):
            continue
        found.append(row)
    return found


def newer_for_identity(rows, key, chosen):
    """The newest row carrying `key` that sorts after `chosen` in
    `oldest_first` order, or None - a measurement or a repeat alike, because
    the question is what a reader of the ledger would find newer than the row
    a repeat names."""
    if not key or chosen is None:
        return None
    ordered = oldest_first([r for r in rows or []
                            if isinstance(r, dict) and r.get(REUSE_KEY) == key])
    for at, row in enumerate(ordered):
        if row is chosen:
            return ordered[-1] if at < len(ordered) - 1 else None
    return None


def reconcile(project, manifest_path, session_id=None, config=None, wait=None):
    """Re-derive every pointer from the ledger and from each subject's record
    (`RECORD_KEY`), the newer of the two. The repair `write_pointer` names.

    THIS IS WHY THE POINTER MAY BE REFUSED AT ALL. A cache write that loses a race
    with another live session leaves the plan behind the record, and this is the
    pass that catches it up - so the refusal costs a reader one command and never a
    fact. The ledger is the source of truth; nothing here reads the manifest to
    decide what is true, only to decide what still needs saying.

    THE POINTER AND THE RECORD NAME ONE RUN AFTERWARDS. When a ledger row is
    newer than the subject's record - a run whose record write was refused - the
    record is rewritten from that row (`run_record`, carrying the run it
    repeated from the rows read here) in the same write as the pointer, rather
    than the pointer moving alone and leaving `lastRun` on an older run. Each
    subject is written through `write_plan_file`, so the shard is read under
    the plan-file lock and the decision is asked again of that read: a record
    written since the rows were read is not replaced by an older run.

    Returns `{"moved", "refused", "already", "unreadable", "subjects",
    "unreadablePlanFiles"}`. `moved` and `refused` carry sentences, because a
    reconcile that could not finish must say which subjects it left behind
    rather than reporting a smaller number; `unreadablePlanFiles` names each
    plan file that would not read, whose subjects were not reconciled.
    """
    config = _journal_io.load_config(project) if config is None else config
    read = read_rows(project, config=config, manifest_path=manifest_path)
    # A MOVED TASK IS POINTED AT WHERE IT LIVES NOW. Its runs carry the old id and
    # the old phase; keyed through the plan's `movedFrom`, they aim at the live id,
    # and the phase is the one that holds it rather than the one the row names.
    try:
        plan = _mio.load_manifest(manifest_path)
    except Exception:
        plan = {}
    owner = dict((str(t.get("id")), str(ph.get("id")))
                 for ph, t in _mio.iter_tasks(plan) if t.get("id"))
    best = latest_by_subject(read["rows"], aliases=subject_aliases(plan))
    # A SUBJECT'S RECORD IS ITS NEWEST RUN, so the pointer is derived from it
    # unless the ledger holds a run of that subject stamped after it - a run
    # whose record write was refused. A ledger with no row for it, which is
    # what a plan written once the row is no longer kept holds, still points.
    held, lost_plan = subject_records(manifest_path, project)
    for key, (record, phase_id) in held.items():
        row = best.get(key)
        mine = stamp_moment(record.get("at"))
        theirs = stamp_moment(row.get("ts")) if row else None
        if row is None or theirs is None or (mine is not None and mine >= theirs):
            best[key] = dict(pointer_from_record(record), ts=record.get("at"),
                             phaseId=phase_id)
    ledger = [r for r, src in zip(read["rows"], read["rowSources"])
              if src == ROW_FROM_LEDGER]
    ledger_runs = set(str(r.get("runId")) for r in ledger)
    moved, refused, already = [], [], []
    for (scope, subject), row in sorted(best.items()):
        if scope == "task":
            ids = {"taskId": subject,
                   "phaseId": owner.get(subject) or row.get("phaseId")}
        else:
            ids = {"phaseId": subject}
        # A LEDGER ROW THAT WON is a run the plan holds no record of: its
        # record is written with the pointer, so the two stay one run.
        # Its source is looked for where the record writer looks: every run
        # the plan and the ledger hold, then (under the lock) the record this
        # write replaces.
        record = None
        if str(row.get("runId")) in ledger_runs:
            record = run_record(row, source=repeat_source(row, read["rows"]))
        out = _reconcile_subject(project, manifest_path, scope, ids, row,
                                 record, session_id, config, wait)
        said = "%s %s" % (scope, subject)
        if out["written"]:
            moved.append("%s -> %s" % (said, out["runId"]))
        elif out["reason"] is None:
            already.append(said)
        else:
            refused.append("%s: %s" % (said, out["reason"]))
    return {"moved": moved, "refused": refused, "already": already,
            "unreadable": read["unreadable"], "subjects": len(best),
            "unreadablePlanFiles": sorted(set(
                list(read.get("unreadablePlanFiles") or []) + lost_plan))}


def _reconcile_subject(project, manifest_path, scope, ids, target, record,
                       session_id, config, wait):
    """Point one subject at `target`, with `record` (the record of `target`'s
    run, built from its ledger row) written beside the pointer when there is
    one -> `{"written", "reason", "runId"}`; `reason` None with nothing
    written is a subject already pointing there."""
    path, sharded = _phase_file(manifest_path, ids.get("phaseId"))
    if not path or not os.path.exists(path):
        return {"written": False, "runId": None,
                "reason": "no phase %r in this manifest" % (ids.get("phaseId"),)}
    got = write_plan_file(
        project, path,
        lambda body: _reconciled(body, scope, ids, sharded, target, record),
        "reconciling test evidence", session_id=session_id, wait=wait,
        outcome=RECONCILE_OUTCOME, repair="run --reconcile again once the "
        "holder is done", config=config)
    if not got["written"]:
        return {"written": False, "reason": got["reason"], "runId": None}
    previous, pointer = got["answer"]
    _say_moved(project, path, scope, ids, previous, pointer, session_id, config)
    return {"written": True, "reason": None, "runId": pointer.get("runId")}


def _reconciled(body, scope, ids, sharded, target, record):
    """`write_plan_file`'s change for one reconciled subject -> `(body | None,
    problem, (previous pointer, pointer written))`.

    ASKED AGAIN OF THE SHARD AS READ UNDER THE LOCK. A record written since the
    rows were read, and newer than `target`, is the subject's newest run now: the
    pointer is derived from it and no older run's record replaces it. A subject
    whose pointer already names the run, and whose record names it too or is
    absent, is left alone (`(None, None, None)`): nothing there disagrees."""
    subject, _task, problem = _holders(body, scope, ids, sharded)
    if problem is not None:
        return None, problem, None
    held = subject.get(RECORD_KEY)
    # A repeat whose source was read nowhere before the lock looks once more,
    # in the record it is about to replace - `_put_record`'s look, through the
    # same helper, so the two writers of a record carry the same run.
    source = repeat_source(record, replaced=held, scope=scope, ids=ids) \
        if record is not None and record.get(REPEAT_UNREAD_KEY) else None
    if source is not None:
        record = finished_record(repeat_carried(
            dict((k, v) for k, v in record.items() if k != REPEAT_UNREAD_KEY),
            source), RECORD_MAX_BYTES)
    if record is not None and isinstance(held, dict):
        mine = stamp_moment(held.get("at"))
        theirs = stamp_moment(target.get("ts"))
        if mine is not None and theirs is not None and mine >= theirs:
            record, target = None, dict(pointer_from_record(held),
                                        ts=held.get("at"))
    run = str(target.get("runId"))
    current = subject.get(POINTER_KEY) or {}
    agrees = (not isinstance(held, dict)) or str(held.get("runId")) == run
    if str(current.get("runId")) == run and agrees:
        return None, None, None
    pointer = pointer_from_record(record) if record is not None \
        else pointer_for(target)
    previous = subject.get(POINTER_KEY)
    if record is not None:
        subject[RECORD_KEY] = record
    subject[POINTER_KEY] = pointer
    return body, None, (previous, pointer)


# --- full_status: whole, provisional, unknown, or not declared -----------------
# THE THIRD PLACE'S OWN VERDICT, FROM RECORDED FULL RUNS ALONE. `phase.mergedHead`
# names the commit the parent's first-parent chain brought the phase in with, or,
# with `phase.mergedHeadAt` set, the parent's head recorded after the fact. A
# WHOLE answer needs a green, measured, clean, verbatim full run whose recorded
# head CONTAINS that commit, and that
# containment is asked of git through `_worktrees.merged_into` -- never a string
# comparison, because a head that merely EQUALS `mergedHead` is a special case of
# containment and a head that is further ahead of it is the ordinary one.
#
# NO VERDICT IS EVER READ FROM THE PLAN. `phase.testEvidence` and any cache a
# surface keeps beside it answer a different, narrower question (is THIS task's
# or phase's own gate run backed by evidence); a stale or hand-edited cache must
# never be able to make a phase read WHOLE. What this reads is the rows it is
# handed - the ledger's, and the full runs phases hold (`FULL_GATE_RUNS_KEY`),
# each a run's id, head and commands whose containment is asked of git again on
# every read - and the phase dict's own `mergedHead`.
FULL_SCOPE = "full"


def _full_disqualification(row, full_commands):
    """Why `row` cannot bear WHOLE, or None when every rule holds: every
    rule of `_measurement_disqualification`, then the head rule.

    A ROW NAMING NO TESTED HEAD IS DISQUALIFIED HERE, not left for git to
    refuse: ancestry of an absent head answers UNKNOWN, and an UNKNOWN in
    `full_status`'s walk outranks an older run that does contain the merge,
    so the phase would read could-not-ask with a remedy (fetch, unshallow)
    that cannot supply a head the row never recorded. The head rule comes
    LAST so a row failing a measurement rule too is named for that one - a
    red run is red before it is head-less.
    """
    reason = _measurement_disqualification(row, full_commands)
    if reason is not None:
        return reason
    if not _names_tested_head(row):
        return ("the row names no tested head, so there is no commit to ask "
                "whether it contains the merge, and it cannot bear whole")
    return None


def _measurement_disqualification(row, full_commands):
    """Why `row` is not a MEASURED FULL RUN - the declared gate measured
    green on a clean tree - or None when it is. Whole-bearing is this plus a
    tested head (`_full_disqualification`); a caller asking whether a run
    gave the gate its chance to catch something, and not what commit it can
    vouch for, asks this alone.

    EVERY RULE NAMES ITSELF IN ITS OWN RETURN, because a caller reporting
    PROVISIONAL over the nearest disqualified row has to say WHICH condition
    failed -- a bare "not whole-bearing" would be the same silence a filter
    that narrows to nothing must never produce.

    THE ORDER IS THE ORDER A ROW WAS BUILT IN: whether it is a measurement at
    all (status, then not a repeat), what scope it claims, whether it measured
    anything, whether every step's cost is known, whether the tree it
    measured was clean, and only last whether it ran the gate that is
    actually declared now -- a row that failed every earlier test would be a
    strange one to praise for running the right commands.
    """
    if row_is_red(row):
        return "status is %r, not %s" % (row.get("status"), RUN_PASSED)
    if row.get(VERDICT_SOURCE) is not None:
        return ("this row repeats an earlier verdict (%s=%r) rather than "
                "measuring one" % (VERDICT_SOURCE, row.get(VERDICT_SOURCE)))
    if row.get("scope") != FULL_SCOPE:
        return "scope is %r, not %r" % (row.get("scope"), FULL_SCOPE)
    held = row.get(HELD_COMMANDS_KEY)
    if isinstance(held, dict):
        # A run a phase holds (`held_run_row`): every rule below but the last
        # was met when it was offered, so only the gate declared NOW is asked.
        return _commands_disqualification(held.get("entries"),
                                          held.get("digest"), full_commands)
    obs = row.get("observations") if isinstance(row.get("observations"), dict) else {}
    ran_total = obs.get("ranTotal")
    if not (isinstance(ran_total, (int, float)) and not isinstance(ran_total, bool)
            and ran_total > 0):
        return "the full run counted nothing"
    if not obs.get("countsBasis"):
        return "the full run's count carries no basis"
    steps = row.get("steps") if isinstance(row.get("steps"), list) else []
    for step in steps:
        duration = step.get("durationMs") if isinstance(step, dict) else None
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            return ("a step of this run carries no durationMs, so its cost "
                    "cannot be measured")
    if "dirtyOutside" not in obs:
        return ("this run carries no dirtyOutside observation, so a dirty "
                "tree cannot be ruled out")
    if obs.get("dirtyOutside"):
        return ("FULL RUN ON A DIRTY TREE: certifies nothing about %s"
                % ((row.get("testedState") or {}).get("head"),))
    commands = [s.get("command") if isinstance(s, dict) else None for s in steps]
    return _commands_disqualification(len(commands), commands_digest(commands),
                                      full_commands)


def commands_digest(commands):
    """`sha256:` and the hex digest of `commands` as compact JSON, in order -
    two lists digest alike exactly when they are equal, so a run a phase
    holds is judged against the gate declared now without carrying its
    commands."""
    text = json.dumps(list(commands or []), separators=(",", ":"),
                      ensure_ascii=False)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _commands_disqualification(count, digest, full_commands):
    """The commands rule, over a run's count of commands and their digest: a
    run of fewer or more than the declared entries says how many, one of the
    same count that differs says it is not verbatim. One rule for a row and
    for a run a phase holds, so the two read alike."""
    declared = list(full_commands or [])
    if count != len(declared):
        return "FULL RUN RAN %s OF %d DECLARED ENTRIES" % (count, len(declared))
    if digest != commands_digest(declared):
        return ("the published commands do not match meta.fullGate verbatim "
                "and in order")
    return None


def _names_tested_head(row):
    """Whether `row.testedState.head` is a non-blank string - the commit a
    full run's ancestry question is asked of."""
    state = row.get("testedState")
    head = state.get("head") if isinstance(state, dict) else None
    return isinstance(head, str) and bool(head.strip())


def merged_phase(phase):
    """Whether `phase` is one the third place is asked about: a dict carrying a
    truthy `mergedAt` and an `id` that is not None.

    MERGED IS THE FIELD THE MERGE STAMPS, NEVER A STATUS. `close-phase.py`
    writes `mergedAt` together with `mergedHead` and never decides merged
    from status, so a phase reads merged before its effective status catches
    up to done, and a done phase need never have merged at all. An id-less phase has no
    name any surface could print a verdict under, so none asks about it.

    ONE PREDICATE FOR EVERY SURFACE. The status, the report, the panel and
    the doctor each call this rather than spelling their own reading, so the
    set of phases they grade cannot drift apart.
    """
    return (isinstance(phase, dict) and bool(phase.get("mergedAt"))
            and phase.get("id") is not None)


_DATE_ONLY = "%Y-%m-%d"


def stamp_moment(text, day_start=True):
    """A stamp as epoch seconds, or None when it names no moment.

    THE ONE MOMENT READ this module orders and windows by: `_usage_core.parse_ts`,
    plus an ISO date with no time (`2026-09-01`), read as the START of that day
    in UTC. A hand-written `evidenceSince.at` is often a date, and the start of
    the day is the earliest moment it can mean - so a boundary read from it
    can only move earlier, never later in silence. Kept here rather than in
    `parse_ts`, whose other callers read stamps a machine wrote. With
    `day_start=False` a bare date names no moment, for a reader (`_epoch`)
    that needs the second a run ended rather than the day it ended on.
    """
    moment = _usage_core.parse_ts(text)
    if moment is not None or not isinstance(text, str) or not day_start:
        return moment
    day = text.strip()
    if len(day) != len("0000-00-00"):
        return None
    try:
        return float(calendar.timegm(time.strptime(day, _DATE_ONLY)))
    except ValueError:
        return None


def _ts_moment(row):
    """A row's `ts` as epoch seconds (`stamp_moment`), or None."""
    return stamp_moment(row.get("ts"))


def oldest_first(rows):
    """`rows` ordered by the MOMENT each `ts` names, oldest first, with every
    row whose `ts` will not parse BEFORE all of them; ledger order is kept
    among the undated rows and among rows naming the same moment.

    THE ONE ORDER every "newest row" question here is answered from, so that
    no reader compares `ts` as text: a stamp carrying an offset or a
    fractional second sorts by its spelling rather than its moment. Undated
    rows go first so an unreadable `ts` never beats a readable one, and the
    sort is stable so a tie goes to the row read later.
    """
    keyed = [(_ts_moment(r), r) for r in rows or [] if isinstance(r, dict)]
    dated = sorted([pair for pair in keyed if pair[0] is not None],
                   key=lambda pair: pair[0])
    return ([r for m, r in keyed if m is None]
            + [r for _m, r in dated])


def newest_row(rows):
    """The last row of `oldest_first(rows)`, or None: newest by moment, a
    later row winning a tie, an undated row only when none is dated."""
    ordered = oldest_first(rows)
    return ordered[-1] if ordered else None


def _newest_first(full_rows):
    """`full_rows` ordered by the MOMENT each `ts` names, newest first, with
    every row whose `ts` will not parse after all of them, in ledger order.

    DERIVED FROM `oldest_first`, so one order answers "which is newest"
    everywhere: its dated rows reversed, which puts a dated tie on the row
    read LATER - `newest_row`'s rule - and then the undated rows as read.
    An unreadable `ts` has no place in that order at all; it goes last so it
    is still walked for the answer - its head is as measured as any other -
    but `_is_dated` keeps it from ever being called newest.
    """
    ordered = oldest_first(full_rows)
    return ([r for r in reversed(ordered) if _is_dated(r)]
            + [r for r in ordered if not _is_dated(r)])


def _is_dated(row):
    """Whether `row`'s `ts` names a moment - the condition for being the
    newest whole-bearing run, since a run with no readable moment cannot be
    placed before or after any other."""
    return _ts_moment(row) is not None


def _newest_passing(rows, full_commands, disqualification):
    """The newest DATED scope-`full` row of `rows` (`_newest_first` order)
    that `disqualification(row, full_commands)` passes, or None when none
    does - also None when `full_commands` is empty, since no row can match a
    gate nothing declares."""
    declared = list(full_commands or [])
    if not declared:
        return None
    for row in _full_rows_newest_first(rows):
        if _is_dated(row) and disqualification(row, declared) is None:
            return row
    return None


def _full_rows_newest_first(rows):
    """Every scope-`full` dict of `rows`, in `_newest_first` order."""
    return _newest_first([r for r in (rows or [])
                          if isinstance(r, dict) and r.get("scope") == FULL_SCOPE])


def newest_whole_bearing(rows, full_commands):
    """The newest dated, whole-bearing scope-`full` row of `rows`
    (`_full_disqualification` passes it), or None.

    THE ROW `full_status` NAMES AS `wholeRunId`: a caller asking "what merged
    since the last full run that counted" reads this, and never a second
    reading of which run counts.
    """
    return _newest_passing(rows, full_commands, _full_disqualification)


def newest_measured_full_run(rows, full_commands):
    """The newest dated MEASURED full run of `rows`
    (`_measurement_disqualification` passes it, whatever its head), or None.

    A DIFFERENT QUESTION FROM `newest_whole_bearing`, answered by the same
    walk: whether a run gave the declared gate its chance to catch something,
    not what commit it can vouch for. `selection_miss` bounds "the work
    since" with it - passing over a green run with no head to an older one
    would widen that window over work the newer run already measured - and
    then asks about the head itself.
    """
    return _newest_passing(rows, full_commands, _measurement_disqualification)


def full_status(rows, phase, git_root, full_commands, run=None):
    """`{"answer", "basis", "runId", "wholeRunId", "wholeRunTs"}` -- is this
    phase's merge WHOLE, PROVISIONAL, UNKNOWN, or NOT_DECLARED, from the ledger
    alone, and which recorded run is the newest one that COULD bear whole.

    `runId` IS THE RUN THE ANSWER'S BASIS IS ABOUT, which for a PROVISIONAL
    answer over a ledger holding no whole-bearing run is the nearest
    DISQUALIFIED one - the run the basis names the failed rule of.

    `wholeRunId` AND `wholeRunTs` NAME THE NEWEST WHOLE-BEARING FULL RUN (one
    `_full_disqualification` finds nothing wrong with, whose `ts` parses to a
    moment) and that recorded `ts`, or None for both when no such run
    exists. They always describe ONE run, and on a WHOLE answer it can be a
    different run from `runId`'s. They are carried on every
    answer, so a caller asking "has a run that counts happened since this
    phase merged" reads them and never re-derives which run counts: a run
    that was red, repeated a verdict, measured the wrong scope, counted
    nothing, ran on a dirty tree or ran other commands is not "a full run
    happened", and its moment must not be read as one.

    `full_commands` IS `full_gate_commands(manifest)`, EXACTLY - the runnable
    `meta.fullGate`, review-only entries left out. That is the same list a
    recorded run's `published` argument carries (`run-test-gate._run_full`
    runs and records exactly `full_gate(manifest)["commands"]`), which is what
    a row's `steps[].command` stores verbatim - so a run measured through that
    resolution is judged against the identical commands it was measured
    against, and never a second reading of `meta.buildCommands` that could
    drift from it.

    NOT_DECLARED when `full_commands` is empty -- a plan naming no runnable
    full-gate entry has nothing to ask, whether it names no `meta.fullGate`
    or one holding only review-only entries. UNKNOWN when the phase
    carries no `mergedHead` -- ancestry needs two ends and this one has only
    one, so it is never PROVISIONAL, which would claim a specific gap this
    plan has no way to measure.

    OTHERWISE, every scope-`full` row is walked NEWEST FIRST by the moment
    its `ts` names (`_newest_first`; a row whose `ts` will not parse is
    walked last and is never the newest), and only the
    WHOLE-BEARING ones (`_full_disqualification` finds nothing wrong) are asked
    of git: `_worktrees.merged_into(git_root, mergedHead, row's head, run=run)`.
    CONTAINED answers WHOLE, naming the run. NOT_CONTAINED moves on to an
    older whole-bearing run. UNKNOWN is remembered rather than answered
    immediately, because a newer run that DOES answer CONTAINED still settles
    the question -- git could not say about one run is not the same as git
    saying no about all of them.

    If nothing was CONTAINED: any remembered UNKNOWN wins, because a could-not-
    ask is never folded into a definite answer. Otherwise PROVISIONAL, whose
    basis names the newest whole-bearing run and that its head does not
    contain `mergedHead` -- or, when the only whole-bearing runs carry no
    readable `ts`, the nearest of those, saying so -- or, when not one
    recorded full run was whole-bearing at all, the nearest disqualified one
    and why. With no full run at all, the basis says no run that could
    certify the phase is held or found among the rows - never that none ran.

    THE RUNS A PHASE HOLDS ARE AMONG `rows`: `read_rows` gives each back as a
    scope-`full` row (`held_run_row`), so the walk above is the same over
    the plan's runs as over the ledger's. One reading the rows give and the
    plan alone cannot, A STATED LOSS: a run that could not certify anything
    (red, dirty, unmeasured) is held by no phase, so where the rows' basis
    names such a run as the newest recorded one, the plan's alone names the
    newest run that could certify, or says it holds none - the same word.
    And where more than one run contains the merge the plan names the first
    that certified it, the rows the newest. A value under
    `FULL_GATE_RUNS_KEY` on `phase` that is not the writer's shape gives no
    row; a basis that is not WHOLE then names it (`held_runs_problems`).
    """
    phase = phase if isinstance(phase, dict) else {}
    declared = list(full_commands or [])
    full_rows = _full_rows_newest_first(rows)
    whole = newest_whole_bearing(rows, declared)
    whole_ts = whole.get("ts") if whole is not None else None
    answer = _full_answer(full_rows, phase, git_root, declared, run)
    problems = held_runs_problems(phase.get(FULL_GATE_RUNS_KEY))
    if problems and declared \
            and answer["answer"] != _manifest_vocab.FULL_STATUS_WHOLE:
        answer = dict(answer, basis="%s; phase %s holds a full run this build "
                      "does not read (%s), so it certifies nothing"
                      % (answer["basis"], phase.get("id"),
                         "; ".join(problems)))
    return dict(answer,
                wholeRunId=whole.get("runId") if whole is not None else None,
                wholeRunTs=str(whole_ts) if whole_ts else None)


def _full_answer(full_rows, phase, git_root, declared, run):
    """`full_status`'s `{"answer", "basis", "runId"}` over the scope-`full`
    rows it already sorted newest first - the walk its docstring describes."""
    if not declared:
        return {"answer": _manifest_vocab.FULL_STATUS_NOT_DECLARED,
                "basis": "this plan names no runnable meta.fullGate entry, "
                         "so there is no third place to ask",
                "runId": None}
    merged_head = phase.get("mergedHead")
    if not merged_head:
        return {"answer": _manifest_vocab.FULL_STATUS_UNKNOWN,
                "basis": "phase %s records no mergedHead, so ancestry cannot "
                         "be asked at all" % (phase.get("id"),),
                "runId": None}
    newest_whole_bearing, nearest_disqualified, newest_unknown = None, None, None
    undated_whole_bearing = None
    for row in full_rows:
        reason = _full_disqualification(row, declared)
        if reason is not None:
            if nearest_disqualified is None:
                nearest_disqualified = (row, reason)
            continue
        if not _is_dated(row):
            if undated_whole_bearing is None:
                undated_whole_bearing = row
        elif newest_whole_bearing is None:
            newest_whole_bearing = row
        head = (row.get("testedState") or {}).get("head")
        answer = _worktrees.merged_into(git_root, merged_head, head, run=run)
        if answer["answer"] == _worktrees.CONTAINED:
            return {"answer": _manifest_vocab.FULL_STATUS_WHOLE,
                    "basis": "%s is contained in run %s's head %s (%s)"
                             % (merged_head, row.get("runId"), head,
                                answer["basis"]),
                    "runId": row.get("runId")}
        if answer["answer"] == _worktrees.UNKNOWN:
            if newest_unknown is None:
                newest_unknown = (row, answer)
            continue
        # NOT_CONTAINED - an older whole-bearing run may still contain it.
    if newest_unknown is not None:
        row, answer = newest_unknown
        return {"answer": _manifest_vocab.FULL_STATUS_UNKNOWN,
                "basis": ("whether %s is contained in run %s's head could not "
                         "be established: %s"
                         % (merged_head, row.get("runId"),
                            answer.get("detail") or answer.get("basis"))),
                "runId": row.get("runId")}
    if newest_whole_bearing is not None:
        head = (newest_whole_bearing.get("testedState") or {}).get("head")
        return {"answer": _manifest_vocab.FULL_STATUS_PROVISIONAL,
                "basis": ("the newest whole-bearing full run (%s, head %s) "
                         "does not contain %s"
                         % (newest_whole_bearing.get("runId"), head,
                            merged_head)),
                "runId": newest_whole_bearing.get("runId")}
    if undated_whole_bearing is not None:
        head = (undated_whole_bearing.get("testedState") or {}).get("head")
        return {"answer": _manifest_vocab.FULL_STATUS_PROVISIONAL,
                "basis": ("no whole-bearing full run carries a readable ts; run "
                         "%s (ts %r, head %s) does not contain %s"
                         % (undated_whole_bearing.get("runId"),
                            undated_whole_bearing.get("ts"), head,
                            merged_head)),
                "runId": undated_whole_bearing.get("runId")}
    if nearest_disqualified is not None:
        row, reason = nearest_disqualified
        return {"answer": _manifest_vocab.FULL_STATUS_PROVISIONAL,
                "basis": ("the newest recorded full run (%s) is not "
                         "whole-bearing: %s" % (row.get("runId"), reason)),
                "runId": row.get("runId")}
    return {"answer": _manifest_vocab.FULL_STATUS_PROVISIONAL,
            "basis": ("no full run that could certify phase %s is held by "
                      "the plan or found among the ledger's rows, so nothing "
                      "can be asked whether it contains %s"
                      % (phase.get("id"), merged_head)),
            "runId": None}


# --- the full runs a phase holds: the third place's answer, in the plan --------
# WHY A PHASE HOLDS FULL RUNS AT ALL. `full_status` walks every recorded full
# run, and once no ledger row is written the runs it can walk are the ones the
# plan holds; keeping only the newest run would turn a certified phase
# provisional the moment a later full run is red. So each phase holds the runs
# ITS answer is read from, under `FULL_GATE_RUNS_KEY`, at most `HELD_RUNS_MAX`
# of them (`held_choice`): the run that ranks best for it (`_held_rank`: one
# containing its merge, then one git could not ask about, then one that does
# not contain it; the newest on a tie), and beside it the newest run offered
# when that is another run - the run a PROVISIONAL basis names and the moment
# `stale-full-run` measures from. Once a held run reads WHOLE nothing replaces
# it: a later red run qualifies for nothing, and a later green one changes
# nothing, so a full run does not rewrite every shard its head contains.
#
# WHO IS OFFERED A RUN (`full_run_holder`): every phase that has started, merged
# or not, that does not already hold a run reading whole for it - so a run that
# qualifies is held by no phase only when every started phase is certified. Not
# only merged phases, because a run taken on a phase branch's tip before it
# lands is the run a fast-forward landing is certified by, and the phase has no
# `mergedHead` yet: an unmerged phase ranks a run by whether its head holds every
# task commit the phase records, and the read asks git again with the
# `mergedHead` the landing writes. A PENDING PHASE IS OFFERED NOTHING: it has
# recorded no work, so what it lands is committed after this run and no head
# this run measured contains it. The one exception is a phase that lands no
# commit at all, which carries no work a certification would speak for.
#
# WHAT IS HELD IS THE RUN, NEVER A VERDICT: its id, moment and head, the status
# every held run has, and the count and digest of the commands it ran
# (`held_run_record`). `read_rows` gives each back as a scope-`full` row
# (`held_run_row`), once per run and behind a ledger row of the same run, and
# `full_status` asks git again on every read - so a `mergedHead` re-recorded, a
# history rewritten or a `meta.fullGate` changed after the run reads as the rows
# of the same run read. The measurement rules (counted, timed, clean) were met
# when the run was offered (`_full_disqualification`), so a held run is read
# against the commands rule and its shape (`held_run_problem`) alone; a shape
# this build does not write never certifies, and the basis names it.
FULL_GATE_RUNS_KEY = "fullGateRuns"
HELD_RUNS_MAX = 2
# Where a held run's commands ride on the row it is read back as.
HELD_COMMANDS_KEY = "heldCommands"
_HELD_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
# A phase or task status that says work began; `cancelled` is never offered.
_STARTED_STATUSES = ("in_progress", "blocked", "done")


def _blank(value):
    return not (isinstance(value, str) and value.strip())


def held_run_record(row):
    """What a phase holds of the full run `row`: `{runId, at, head, status,
    entries, digest}`, or None when the row names no run id, head or moment -
    a held run carries all three or is not written. It does not judge the
    run: `held_choice` offers only one `_full_disqualification` passes."""
    row = row if isinstance(row, dict) else {}
    state = row.get("testedState") if isinstance(row.get("testedState"),
                                                 dict) else {}
    run_id, at, head = row.get("runId"), row.get("ts"), state.get("head")
    if _blank(run_id) or _blank(at) or _blank(head):
        return None
    steps = row.get("steps") if isinstance(row.get("steps"), list) else []
    commands = [s.get("command") if isinstance(s, dict) else None
                for s in steps]
    return {"runId": run_id, "at": at, "head": head,
            "status": row.get("status"), "entries": len(commands),
            "digest": commands_digest(commands)}


def held_run_problem(held):
    """`(field, why)` for the first way `held` is not the shape
    `held_run_record` writes, or None. `field` is None when `held` is not an
    object at all. Strict on purpose: a value written by hand, or by a build
    with a status this one does not know, is not a run this build certifies
    from."""
    if not isinstance(held, dict):
        return None, "is not an object"
    for key in ("runId", "at", "head"):
        if _blank(held.get(key)):
            return key, "is %r, not a non-blank string" % (held.get(key),)
    if held.get("status") != RUN_PASSED:
        return "status", ("is %r, not %r, the one status a held run is "
                          "written with" % (held.get("status"), RUN_PASSED))
    entries = held.get("entries")
    if isinstance(entries, bool) or not isinstance(entries, int) or entries < 1:
        return "entries", "is %r, not a count of one command or more" % (
            entries,)
    digest = held.get("digest")
    if not isinstance(digest, str) or not _HELD_DIGEST.match(digest):
        return "digest", ("is %r, not sha256: and 64 lowercase hex digits"
                          % (digest,))
    return None


def held_runs_problems(value):
    """Every way the value a phase holds under `FULL_GATE_RUNS_KEY` is not
    the writer's shape, each naming the key and the field - `[]` when it is,
    or when the phase holds none."""
    if value is None:
        return []
    if not isinstance(value, list):
        return ["%s is not a list of held runs" % (FULL_GATE_RUNS_KEY,)]
    out = []
    for i, held in enumerate(value):
        found = held_run_problem(held)
        if found is not None:
            field, why = found
            out.append("%s[%d]%s %s" % (FULL_GATE_RUNS_KEY, i,
                                        ".%s" % (field,) if field else "", why))
    return out


def held_run_row(held):
    """The scope-`full` row a held run is read back as, or None when it is
    not the writer's shape (`held_run_problem`)."""
    if held_run_problem(held) is not None:
        return None
    return {"runId": held["runId"], "ts": held["at"], "scope": FULL_SCOPE,
            "status": held["status"], "testedState": {"head": held["head"]},
            HELD_COMMANDS_KEY: {"entries": held["entries"],
                                "digest": held["digest"]}}


def full_run_holder(phase):
    """Whether a recorded full run is offered to `phase`: one with an id that
    is not cancelled and has started - merged, a status saying work began, or
    a task that began or committed. A pending phase is not; the section's
    comment says why."""
    if not isinstance(phase, dict) or phase.get("id") is None \
            or phase.get("status") == "cancelled":
        return False
    if merged_phase(phase) or phase.get("status") in _STARTED_STATUSES:
        return True
    return any(isinstance(t, dict) and (t.get("status") in _STARTED_STATUSES
                                        or not _blank(t.get("commit")))
               for t in phase.get("tasks") or [])


def _held_rank(row, phase, declared, git_root, run):
    """How strongly the full run `row` answers for `phase` now: -1 when it
    cannot bear whole against the gate declared now; with a `mergedHead`, 2
    when its head contains it, 1 when git could not say, 0 when it does not;
    with none, 1 when its head holds every task commit the phase records and
    0 otherwise."""
    if row is None or _full_disqualification(row, declared) is not None:
        return -1
    head = (row.get("testedState") or {}).get("head")
    merged_head = phase.get("mergedHead")
    if merged_head:
        answer = _worktrees.merged_into(git_root, merged_head, head,
                                        run=run)["answer"]
        return {_worktrees.CONTAINED: 2, _worktrees.UNKNOWN: 1}.get(answer, 0)
    commits = [t.get("commit") for t in phase.get("tasks") or []
               if isinstance(t, dict) and not _blank(t.get("commit"))]
    if commits and all(_worktrees.merged_into(git_root, c, head, run=run)[
            "answer"] == _worktrees.CONTAINED for c in commits):
        return 1
    return 0


def _held_moment(held):
    moment = stamp_moment(held.get("at"))
    return moment if moment is not None else float("-inf")


def held_choice(phase, held, row, declared, git_root, run=None):
    """The runs `phase` holds once the full run `row` is offered to it, or
    None when that changes nothing.

    Nothing changes when the gate declares nothing, when `row` cannot bear
    whole (`_full_disqualification`) or names no id, head or moment, when the
    phase already holds `row`'s run, or when a run it holds reads WHOLE for
    it - the certification stays. Otherwise the phase holds the best-ranked
    of what it held and `row` (`_held_rank`; the newer on a tie, and the one
    offered last on a tie of moments, as the rows' walk breaks it) and, when
    that is another run, the newest - oldest first. A held value that is not
    the writer's shape is not kept."""
    declared = list(declared or [])
    if not declared or _full_disqualification(row, declared) is not None:
        return None
    offered = held_run_record(row)
    if offered is None:
        return None
    current = [h for h in (held if isinstance(held, list) else [])
               if held_run_problem(h) is None]
    if any(str(h["runId"]) == str(offered["runId"]) for h in current):
        return None
    pool = [(h, _held_rank(held_run_row(h), phase, declared, git_root, run))
            for h in current]
    if any(rank == 2 for _h, rank in pool):
        return None
    pool.append((offered, _held_rank(held_run_row(offered), phase, declared,
                                     git_root, run)))
    best = max(range(len(pool)),
               key=lambda i: (pool[i][1], _held_moment(pool[i][0]), i))
    newest = max(range(len(pool)), key=lambda i: (_held_moment(pool[i][0]), i))
    chosen = [pool[i][0] for i in sorted(set([best, newest]),
                                         key=lambda i: (_held_moment(pool[i][0]),
                                                        i))]
    return None if chosen == held else chosen


def added_findings(manifest_path, put, validator, prefix):
    """Why the plan at `manifest_path` would not validate with `put`'s change
    made to a copy of it as assembled now, or None.

    `put(plan)` changes the copy and returns a problem sentence or None.
    `validator` is `_manifest_rules.bound_validator()`'s and `prefix` its
    schema code prefix, both the caller's, since the rules sit above this
    module. ONLY WHAT THE CHANGE ADDS REFUSES: a finding, or a warning the
    schema check raised - its refusal of a value, or a keyword its reader
    could not check, since a value checked against less than its schema is
    not known to validate. A line the plan already carried is not this
    write's to answer."""
    try:
        now = _mio.load_manifest(manifest_path)
    except Exception as exc:
        return "the plan could not be read to validate the record (%s)" % (exc,)
    after = json.loads(json.dumps(now))
    problem = put(after)
    if problem:
        return problem

    def refuses(line):
        return str(_output.finding_code(line) or "").startswith(prefix)
    was_f, was_w = validator.validate(now)
    is_f, is_w = validator.validate(after)
    before = set(was_f) | set(w for w in was_w if refuses(w))
    new = [ln for ln in list(is_f) + [w for w in is_w if refuses(w)]
           if ln not in before]
    return "; ".join(str(ln) for ln in new[:3]) or None


def _phase_dump(phase):
    return json.dumps(phase, sort_keys=True)


def _put_holds(chosen):
    """`added_findings`' change: each phase of `chosen` (`{id: held}`) holding
    its value in the assembled plan."""
    def put(plan):
        found = [p for p in plan.get("phases") or []
                 if isinstance(p, dict) and str(p.get("id")) in chosen]
        if len(found) != len(chosen):
            return "a phase a plan file holds is not in the assembled plan"
        for p in found:
            p[FULL_GATE_RUNS_KEY] = chosen[str(p["id"])]
        return None
    return put


def _planned_holds(manifest_path, project, row, declared, git_root, run):
    """`({path: (sharded, {id: (phase as read, held | None)})}, unreadable)`
    - what each phase a full run is offered to would hold, decided over the
    plan files as read BEFORE any lock, so the plan is validated once for the
    whole run rather than once per file; each write reads its file again
    under the lock and decides again for a phase that changed meanwhile."""
    bodies, lost = plan_bodies(manifest_path, project)
    out = {}
    for _label, phase in bodies:
        if not full_run_holder(phase):
            continue
        path, sharded = _phase_file(manifest_path, phase.get("id"))
        if not path:
            continue
        got = held_choice(phase, phase.get(FULL_GATE_RUNS_KEY), row, declared,
                          git_root, run=run)
        out.setdefault(path, (sharded, {}))[1][str(phase["id"])] = (
            _phase_dump(phase), got)
    return out, lost


def _hold_in(body, sharded, planned, manifest_path, row, declared, git_root,
             run, validator, prefix):
    """`write_plan_file`'s change for one plan file: every phase in it that a
    full run is offered to holds what `held_choice` gives -> `(body | None,
    problem | None, (held, kept))`. A phase as it was when `planned` decided
    takes that decision, which was validated with the rest; one that changed
    under the lock is decided again, and the file's change validated again."""
    phases = [body] if sharded else [p for p in body.get("phases") or []
                                     if isinstance(p, dict)]
    chosen, kept, again = {}, [], False
    for phase in phases:
        if not full_run_holder(phase):
            continue
        pid = str(phase["id"])
        was = planned.get(pid)
        if was is not None and was[0] == _phase_dump(phase):
            got = was[1]
        else:
            got = held_choice(phase, phase.get(FULL_GATE_RUNS_KEY), row,
                              declared, git_root, run=run)
            again = again or got is not None
        if got is None:
            kept.append(pid)
        else:
            chosen[pid] = got
    if not chosen:
        return None, None, ([], kept)
    problem = added_findings(manifest_path, _put_holds(chosen), validator,
                             prefix) if again else None
    if problem:
        return None, ("the plan with run %s held would not validate (%s), so "
                      "nothing was written" % (row.get("runId"), problem)), None
    for phase in phases:
        if str(phase.get("id")) in chosen:
            phase[FULL_GATE_RUNS_KEY] = chosen[str(phase["id"])]
    return body, None, (sorted(chosen), kept)


def hold_full_run(project, manifest_path, row, declared, git_root, validator,
                  prefix, run=None, session_id=None, wait=None):
    """Offer the recorded full run `row` to every phase of the plan at
    `manifest_path` that `full_run_holder` admits, each plan file written
    through `write_plan_file` - the `index` lock, the file read under it.
    The plan is validated with every phase's new value in place before the
    first save (`added_findings`, with `validator` and `prefix` from the
    caller), and a file whose phase changed before its lock was taken is
    decided and validated again under it (`_hold_in`). A plan whose
    revalidation refuses is written nowhere.

    -> `{"runId", "held", "kept", "refused", "notHeld"}`: the phases whose
    held runs changed, the phases offered the run that kept what they hold,
    `[(plan file, sentence)]` for each file that refused or could not be
    read, and the sentence saying why the run was offered to no phase at all
    (None when it was). A refusal leaves its file byte for byte as it was."""
    declared = list(declared or [])
    out = {"runId": (row or {}).get("runId"), "held": [], "kept": [],
           "refused": [], "notHeld": None}
    if not declared:
        out["notHeld"] = ("this plan names no runnable meta.fullGate entry, so "
                          "no phase holds a full run")
        return out
    reason = _full_disqualification(row, declared)
    if reason is None and held_run_record(row) is None:
        reason = "the run names no run id, head or moment"
    if reason is not None:
        out["notHeld"] = ("run %s cannot certify a phase (%s), so nothing was "
                          "held and what every phase holds is unchanged"
                          % (out["runId"], reason))
        return out
    if getattr(validator, "unreadable", None):
        out["refused"].append((repo_relative_or_token(project, manifest_path),
                               "%s, so the plan could not be checked and "
                               "nothing was written" % ("; ".join(
                                   str(u) for u in validator.unreadable),)))
        return out
    files, lost = _planned_holds(manifest_path, project, row, declared,
                                 git_root, run)
    out["refused"].extend((label, "could not be read, so the phases it holds "
                                  "were offered nothing") for label in lost)
    chosen = dict((pid, got) for _s, decided in files.values()
                  for pid, (_dump, got) in decided.items() if got is not None)
    problem = added_findings(manifest_path, _put_holds(chosen), validator,
                             prefix) if chosen else None
    if problem:
        out["refused"].append((
            repo_relative_or_token(project, manifest_path),
            "the plan with run %s held would not validate (%s), so nothing was "
            "written" % (out["runId"], problem)))
        return out
    for path in sorted(files):
        sharded, decided = files[path]
        if all(got is None for _dump, got in decided.values()):
            out["kept"].extend(decided)
            continue
        got = write_plan_file(
            project, path,
            lambda body, s=sharded, d=decided: _hold_in(
                body, s, d, manifest_path, row, declared, git_root, run,
                validator, prefix),
            "holding full run %s" % (out["runId"],), session_id=session_id,
            wait=RECORD_WAIT_SECONDS if wait is None else wait,
            outcome="nothing was written to the plan",
            repair="re-run the full gate with --record once the lock is free")
        if got["reason"]:
            out["refused"].append((repo_relative_or_token(project, path),
                                   got["reason"]))
            continue
        held, kept = got["answer"] or ([], [])
        out["held"].extend(held)
        out["kept"].extend(kept)
    out["held"].sort()
    out["kept"].sort()
    if not files and not lost:
        out["notHeld"] = ("no phase has started, so no phase was offered run "
                          "%s" % (out["runId"],))
    return out


# --- a failing suite no derived gate selected: the selection miss -------------
# A PHASE SIGNED OFF ON A DERIVED GATE RAN A SUBSET OF THE SUITES, and the
# third place runs all of them. A suite that fails there and that no derived
# gate of the work merged since the newest earlier measured full run listed is a
# selection the derivation got wrong - which is only worth learning from when
# the RUNNER named that suite. A tail of output is not a list of failing
# suites, so a failure read only off one is said to be unlearned instead.
NAMED_FAILING = "named as failing"


def _counts_as_failed(step):
    """A step that ran to a verdict and failed, and was not quarantined: a
    non-zero exit, no no-verdict `outcome`, and no `muted` marker."""
    return (isinstance(step, dict) and step.get("exit") not in (0, None)
            and not step.get("outcome") and not step.get("muted"))


# The basis `run-test-gate.failing_lines` and `failing_suites` give a list they
# cut at its bound: a case or a suite past the cut is on no row, so the list is
# not every one that failed. One phrase, read by the gate and by the drive.
LIST_CUT = "the rest are not carried"


def suites_cut(step):
    """Whether a step's failing suites were cut at their bound (`LIST_CUT`), so
    a suite past the cut is on no row and the carried ones are not all."""
    return LIST_CUT in str((step or {}).get("failingSuitesBasis") or "")


def named_failing_suites(steps):
    """Every suite file a failed step's runner NAMED as failing, in step
    order, deduplicated.

    A SUITE COUNTS ONLY WHEN `failingSuitesBasis` SAYS THE RUNNER NAMED IT
    (`NAMED_FAILING` is the phrase `run-test-gate.failing_suites` composes
    for exactly that answer, and for no other) - and never off a muted step,
    whose failure is quarantined and known rather than caught.
    """
    suites = []
    for step in steps or []:
        if not _counts_as_failed(step):
            continue
        if NAMED_FAILING not in (step.get("failingSuitesBasis") or ""):
            continue
        for path in step.get("failingSuites") or []:
            if path not in suites:
                suites.append(path)
    return suites


def unnamed_failure_bases(steps):
    """The basis of every failed, unmuted step whose runner named no suite -
    `failingSuitesBasis` when the step carries one, its `failingBasis`
    otherwise - so the caller can say which failure it refused to learn from
    and why."""
    return [step.get("failingSuitesBasis") or step.get("failingBasis")
            or "the step carries no basis for its failure"
            for step in steps or []
            if _counts_as_failed(step)
            and NAMED_FAILING not in (step.get("failingSuitesBasis") or "")]


def listed_by(path, tests):
    """Whether suite `path` is one of `tests`, read either way round as a
    path suffix - a runner may print a path relative to its own directory
    while a derived gate spells it from the repository root."""
    return any(path == t or path.endswith("/" + t) or t.endswith("/" + path)
               for t in tests or [])


def resolve_named(spelling, candidates):
    """`(path, None)` for the ONE candidate a runner's `spelling` names, or
    `(None, reason)` when it names none of them or several.

    THE MATCH IS `listed_by`'s, candidate by candidate - equal, or either a
    `/`-bounded path suffix of the other - so a suite a runner prints
    relative to its own directory still finds the path the repository
    spells from its root. `candidates` is whatever set of paths the caller
    must pin the name onto: the suites a plan couples, or every file the
    repository tracks. A candidate listed twice is one candidate.

    SEVERAL MATCHES NAME NONE OF THEM. A bare `test_c.py` fits every
    `*/test_c.py`, and which one failed is not something the name can say;
    answering with any of them would act on a suite the run may never have
    touched. An exact-equal candidate does not break the tie either: a
    runner working from a subdirectory prints a repository-root-looking
    path for a deeper file. The reason names every match, so the caller can
    say what it refused to choose between.
    """
    matches = []
    for path in candidates or []:
        if path not in matches and listed_by(spelling, [path]):
            matches.append(path)
    if len(matches) == 1:
        return matches[0], None
    if not matches:
        return None, ("no candidate path is %s or ends in /%s, and %s ends "
                      "in none of them" % (spelling, spelling, spelling))
    return None, ("%s names each of %s - one name, several suites, so it "
                  "names none of them" % (spelling, ", ".join(matches)))


# --- a runner's spelling, pinned to one tracked path ---------------------------
# A RUNNER NAMES A SUITE THE WAY IT SEES IT, from whatever directory it was
# started in, while a derived gate, a coupling and a bug spell it from the
# project root. Every reader that turns the first into the second pins it here,
# onto the files git tracks, so no two readers can place one name on two paths
# - and a name that fits several tracked suites is placed on none, with the
# candidates said, rather than counted as whichever one a suffix happened to
# reach first.
def shell_unsafe(path):
    """Whether `path` holds a control character -- a newline among them --
    that a gate entry, which is one line of shell, cannot carry."""
    return any(ord(c) < 32 or ord(c) == 127 for c in path)


def project_relative(spelling, project):
    """`(path, None)` -- `spelling` normalized and spelled from `project` --
    or `(None, why)` when it names nothing inside the project.

    NORMALIZED BEFORE ANYTHING READS IT, so `./test_old.py` is `test_old.py`
    to the disk check and to the resolver alike. An ABSOLUTE spelling inside
    the project becomes relative to it; one outside it is refused, because a
    gate entry is written into a committed plan and a machine's own path does
    not belong there. The directory is resolved through its symlinks and the
    file name is not, so a suite that is itself a link still counts as the
    project's.
    """
    if spelling == OUTSIDE_TOKEN:
        # What the ledger's own scrub wrote for an absolute path outside the
        # checkout: the spelling is gone, the fact that it lay outside is not.
        return None, ("%s lies outside the project, and a machine's own path "
                      "is never written into a plan" % (spelling,))
    if os.path.isabs(spelling):
        root = os.path.realpath(project)
        full = os.path.join(os.path.realpath(os.path.dirname(spelling)),
                            os.path.basename(spelling))
        try:
            rel = _output.posix_rel(full, root)
        except ValueError:
            rel = full
    else:
        rel = os.path.normpath(spelling)
    rel = rel.replace(os.sep, "/")
    if rel == ".." or rel.startswith("../") or os.path.isabs(rel):
        return None, ("%s lies outside the project, and a machine's own path "
                      "is never written into a plan" % (spelling,))
    if rel == ".":
        return None, "%s names the project root, not a suite" % (spelling,)
    return rel, None


def suite_listing(project, run=None):
    """`{"project", "tracked", "listingFailed"}` - what `pin_suite` pins
    onto: every path `git ls-files` lists from `project`, already spelled
    from the directory a gate runs in, or `tracked: None` and the sentence
    saying why git could not list them. `run` is `_worktrees`' injectable
    git runner.

    ASKED ONCE PER READER, never once per name: every name one run printed
    is pinned against the same tree. An unlisted tree is not an empty one,
    so a listing failure is carried as a sentence rather than as `[]`.
    """
    code, said, err = _worktrees._runner(run)(project, ["ls-files", "-z"])
    if code == 0:
        # `ls-files` prints from its cwd, which is the project: said so to the
        # pair, which hands the spelling back as it stands.
        hc = _loader.load_hooks_config(modname="audit__config")
        return {"project": project, "listingFailed": None,
                "tracked": [hc.git_to_plan(p, project, project, cwd=project)
                            for p in (said or "").split("\0") if p]}
    return {"project": project, "tracked": None,
            "listingFailed": ("the tracked files could not be listed (git "
                              "ls-files: %s)" % ((err or "").strip()
                                                 or "exit %s" % (code,)))}


def _pin_relative(rel, listing):
    """`pin_suite` for a spelling already made project-relative."""
    on_disk = os.path.isfile(os.path.join(listing["project"], rel))
    tracked = listing.get("tracked")
    if tracked is None:
        path, why = ((rel, None) if on_disk else
                     (None, "%s is not on disk from the project root, and %s"
                      % (rel, listing.get("listingFailed"))))
    else:
        path, why = resolve_named(rel, tracked + ([rel] if on_disk else []))
    if path is not None and shell_unsafe(path):
        path, why = None, ("%s resolves to %r, which holds a control "
                           "character no one-line gate can carry" % (rel, path))
    return path, why


def pin_suite(spelling, listing):
    """`(path, None)` - the ONE tracked path a runner's `spelling` names,
    spelled from the project root - or `(None, why)` when it names none or
    several. `listing` is `suite_listing`'s answer.

    THE MATCH IS `resolve_named`'s over every tracked file, plus the
    spelling itself when it exists from the root: a runner working from a
    subdirectory prints `tests/x.test.js` for `pkg1/tests/x.test.js`, and a
    sibling `pkg2/tests/x.test.js` makes that name two suites, so it pins to
    neither. When git cannot list, a spelling that exists from the root is
    kept as written - nothing is left that could show it a twin - and any
    other is refused naming the listing failure. A path holding a control
    character is refused rather than handed to a one-line shell gate.
    """
    if not isinstance(spelling, str) or not spelling.strip():
        return None, "%r names no suite" % (spelling,)
    rel, why = project_relative(spelling, listing["project"])
    if rel is None:
        return None, why
    return _pin_relative(rel, listing)


def pin_suites(suites, project, run=None):
    """`(paths, None)` -- each suite a runner named, pinned by `pin_suite` --
    or `(None, why)` when any one of them cannot be.

    ONE UNRESOLVED SUITE REFUSES THEM ALL. A gate narrowed to the suites that
    did resolve could go green while a failure the run named is never run,
    so the reason names every suite that could not be pinned. A spelling
    outside the project is refused before git is asked anything at all.
    """
    rels, refused = [], []
    for spelling in suites:
        rel, why = project_relative(spelling, project)
        if rel is None:
            refused.append(why)
        else:
            rels.append(rel)
    if refused:
        return None, ("a suite the run named could not be pinned to one path "
                      "from the project root: %s" % ("; ".join(refused),))
    listing = suite_listing(project, run)
    pinned = []
    for rel in rels:
        path, why = _pin_relative(rel, listing)
        if path is None:
            refused.append(why)
        else:
            pinned.append(path)
    if refused:
        return None, ("a suite the run named could not be pinned to one path "
                      "from the project root: %s" % ("; ".join(refused),))
    return pinned, None


def _suite_names(name, listing):
    """`name` and the tracked path it pins to, when it pins to one."""
    path, _why = pin_suite(name, listing)
    return set([name] + ([path] if path is not None else []))


def same_suite(one, other, listing):
    """Whether two spellings name one suite: they are equal, or one pins
    (`pin_suite`) to the other, or both pin to the same tracked path.

    NEVER A SUFFIX ALONE. `listed_by` would call `tests/x.test.js` and
    `pkg2/tests/x.test.js` one suite while the runner meant
    `pkg1/tests/x.test.js`; only the pinned path can say which one failed.
    """
    return bool(_suite_names(one, listing) & _suite_names(other, listing))


def own_miss(row, names, listing):
    """The `selectionMiss` entry of `row` naming the suite one of `names`
    names (`same_suite`), or None.

    THE ONE READING OF "THIS RUN LISTS THAT SUITE AS ITS OWN MISS", shared by
    `full-gate.py`'s catch credit and `audit-task.py couple --caught`: a row
    saying no derived gate ran a suite cannot also be the run a coupling of
    that suite caught something in, and two copies of the comparison are
    how one verb came to credit a catch the other refused.
    """
    wanted = [n for n in names or [] if isinstance(n, str) and n]
    for miss in row.get("selectionMiss") or []:
        test = miss.get("test") if isinstance(miss, dict) else None
        if not isinstance(test, str) or not test:
            continue
        if any(same_suite(test, name, listing) for name in wanted):
            return miss
    return None


def unreadable_names(ledger, project):
    """Each ledger file `read_rows` could not read in full (`ledger` is its
    answer), spelled from `project` - the names a reader owes when a run it
    looked for may be on a line that read lost."""
    return [_output.posix_rel(p, project) if os.path.isabs(p) else p
            for p in ledger.get("unreadableFiles") or []]


def _ancestry(git_root, merged_head, head, run):
    """`(answer, unasked_sentence)` - `_worktrees.merged_into` of `merged_head`
    into `head`, with the sentence to report when git could not answer."""
    asked = _worktrees.merged_into(git_root, merged_head, head, run=run)
    if asked["answer"] == _worktrees.UNKNOWN:
        return asked["answer"], ("whether %s contains %s could not be "
                                 "established - %s"
                                 % (head, merged_head,
                                    asked.get("detail") or asked["basis"]))
    return asked["answer"], None


def _phase_since(phase, head, since, git_root, run):
    """`(verdict, sentence)` for one merged phase against the run's `head`
    and the bounding run `since` (a row carrying `testedState.head`).

    `verdict` is "counted", "underived", "unasked" or None (not merged into
    this run, or merged before `since`). EVERY way ancestry cannot be put is
    "unasked" with its sentence, never folded into either side:
    - no `mergedHead` at all;
    - git could not answer either question;
    - a `mergedHeadAt` backfill that `since` does not already contain. A
      backfilled `mergedHead` is the parent's head recorded AFTER the merge,
      so it can postdate `since` while the merge itself did not; only a
      `since` that contains it settles the order, and anything else fails
      closed rather than learn from an imprecise moment.
    A phase merged since whose `testGateDerived` is not a dict made no
    selection, so it is "underived" and is never counted toward a miss.
    """
    merged_head = phase.get("mergedHead")
    if not merged_head:
        return "unasked", ("it is merged (mergedAt %s) but records no "
                           "mergedHead, so whether this run contains it "
                           "cannot be asked" % (phase.get("mergedAt"),))
    inside, why = _ancestry(git_root, merged_head, head, run)
    if why:
        return "unasked", why
    if inside != _worktrees.CONTAINED:
        return None, None
    since_head = (since.get("testedState") or {}).get("head")
    before, why = _ancestry(git_root, merged_head, since_head, run)
    if why:
        return "unasked", why
    if before == _worktrees.CONTAINED:
        return None, None
    if phase.get("mergedHeadAt"):
        return "unasked", ("its mergedHead %s was recorded after the fact "
                           "(mergedHeadAt %s), so whether it merged before "
                           "run %s cannot be told"
                           % (merged_head, phase.get("mergedHeadAt"),
                              since.get("runId")))
    if not isinstance(phase.get("testGateDerived"), dict):
        return "underived", None
    return "counted", None


def _distinct_files(phases):
    """Every file the phases' tasks declare, in plan order, once - a
    `cancelled` task's files excluded, since that work never landed."""
    files = []
    for phase in phases:
        for task in phase.get("tasks") or []:
            if not isinstance(task, dict) or task.get("status") == "cancelled":
                continue
            for path in task.get("files") or []:
                if isinstance(path, str) and path and path not in files:
                    files.append(path)
    return files


def selection_miss(steps, phases, head, git_root, earlier_rows, full_commands,
                   run=None, unreadable=None, listing=None):
    """`{"misses", "unnamed", "phases", "underived", "since", "unasked",
    "reasons"}` - the post-pass a full run's steps are put through. Reads
    and returns; writes nothing but the one `git ls-files` it asks.

    `misses` is `[{test, phases, sources}]`: each suite the runner NAMED as
    failing (`named_failing_suites`), pinned to its one tracked path
    (`pin_suite` over `listing`, `suite_listing(git_root, run)` when None),
    that no `testGateDerived.tests` of the counted phases lists - `test` is
    that pinned path. A name that pins to no tracked path, or to several,
    is never counted as listed: it is `unasked`, the subject the runner's
    own spelling and the sentence naming the candidates, since a suffix
    match would let a sibling package's suite answer for the one that
    failed. A phase is counted when it is merged
    (`merged_phase`), the run's `head` contains its `mergedHead`, the newest
    earlier measured full run (`newest_measured_full_run` over
    `earlier_rows`, `since`) does not, and it carries a derived gate -
    `_phase_since` holds each exclusion. Both ancestry questions go to git
    (`_worktrees.merged_into`). `sources` is the union of the counted
    phases' live tasks' `files` - the work since the bounding run, read off
    the plan rather than guessed from a diff. The lists are uncut here;
    `row_for` bounds them and counts what it drops.

    LEARNING NEEDS A BOUND. With no earlier measured full run, one that
    recorded no head, or a run with no head of its own, "the work since"
    would be the whole history, so nothing is learned and `reasons` (or
    `unasked`, for a bounding run with no head) says why. `unnamed` holds
    the basis of every failed step whose runner named no suite; `unasked`
    holds `[subject, sentence]` for every ancestry that could not be put.

    A LEDGER READ WITH LOSSES BOUNDS NOTHING. `unreadable` names each file
    `read_rows` could not read in full (`unreadable_names`); the newest
    measured run may sit on the line that read lost, and bounding by the
    next one down would widen "the work since" in silence - so no miss is
    asked, and `reasons` names the files.
    """
    named = named_failing_suites(steps)
    result = {"misses": [], "unnamed": unnamed_failure_bases(steps),
              "phases": [], "underived": [], "since": None, "unasked": [],
              "reasons": []}
    if not named:
        return result
    if unreadable:
        result["reasons"].append(
            "the evidence ledger could not be read in full (%s), so the "
            "newest earlier measured full run may be on a line that read "
            "lost and no bound on the work since can be trusted; repair it "
            "and run again" % (", ".join(unreadable),))
        return result
    if not head:
        result["reasons"].append("this run recorded no head, so what it "
                                 "contains cannot be asked")
        return result
    since = newest_measured_full_run(earlier_rows, full_commands)
    if since is None:
        result["reasons"].append("no earlier measured full run bounds the "
                                 "work since")
        return result
    since_head = (since.get("testedState") or {}).get("head")
    result["since"] = {"runId": since.get("runId"), "head": since_head}
    if not _names_tested_head(since):
        result["unasked"].append(
            ["run %s" % (since.get("runId"),),
             "the newest earlier measured full run records no "
             "testedState.head, so what merged since it cannot be asked"])
        return result
    counted = []
    for phase in phases or []:
        if not merged_phase(phase):
            continue
        verdict, sentence = _phase_since(phase, head, since, git_root, run)
        if verdict == "unasked":
            result["unasked"].append(["phase %s" % (phase["id"],), sentence])
        elif verdict == "underived":
            result["underived"].append(str(phase["id"]))
        elif verdict == "counted":
            counted.append(phase)
    result["phases"] = [str(p["id"]) for p in counted]
    if not counted:
        if result["underived"]:
            result["reasons"].append(
                "the phases merged since run %s (%s) signed off on a gate "
                "that was not derived, so no selection was made that this "
                "run could show wrong"
                % (since.get("runId"), ", ".join(result["underived"])))
        elif not result["unasked"]:
            result["reasons"].append(
                "no phase merged into %s since run %s, so no derived gate "
                "selected anything this run could show wrong"
                % (head, since.get("runId")))
        return result
    listed = []
    for phase in counted:
        tests = phase["testGateDerived"].get("tests")
        listed.extend(project_relative(t, git_root)[0] or t
                      for t in (tests or []) if isinstance(t, str))
    sources = _distinct_files(counted)
    listing = suite_listing(git_root, run) if listing is None else listing
    missed = []
    for spelling in named:
        path, why = pin_suite(spelling, listing)
        if path is None:
            result["unasked"].append([spelling, why])
        elif path not in listed and path not in missed:
            missed.append(path)
    result["misses"] = [{"test": path, "phases": list(result["phases"]),
                         "sources": list(sources)} for path in missed]
    return result


# --- the boundary: when could a run have been recorded at all ------------------
# WHAT THE GATE COULD NOT ASK. `no-test-evidence` asks whether finished work is
# backed by a recorded run, and never whether it COULD have been. For a plan
# adopted mid-flight -- hundreds of tasks finished before this recorder existed --
# the answer is no for every one of them, and no setting helps: `--phase` scopes
# the human render and says so in its own help, not the gate. That work is not a
# lapse, it is an impossibility, and what separates the two is a moment:
#
#     boundary = min( meta.evidenceSince.at , the earliest ts in the ledger )
#
# EXCUSED WORK IS BEFORE THE BOUNDARY, SO THE EARLIER VALUE IS THE SAFER ONE, and
# that is the whole reason this is a `min` rather than either source alone. A
# boundary that moved LATER would silently widen the excuse, which is the failure
# direction that matters for a gate; one that moves earlier only ever fails work
# it used to excuse, loudly, where somebody sees it. Delete the key and the ledger
# still answers, archive the ledger and the key still answers -- only destroying
# both widens the excuse, and that is deliberate destruction rather than an
# accident.
#
# BOTH SOURCES ARE READ BY EXPLICIT COMPARISON, never by truthiness. "No key",
# "no ledger" and "a boundary at the epoch" are three different states, and the
# one thing that could flatten them is a reader spelling `if not boundary`.
SINCE_KEY = "evidenceSince"
ACTION_SINCE = "meta.evidenceSince"
# The sentence the block carries about itself. It is written ONLY on the path that
# derives `at` from the earliest row in the ledger, so it is true of every block
# this module writes; a second derivation would owe a second sentence rather than
# reusing this one.
SINCE_BASIS = ("the first run this plan recorded; work completed before it "
               "could not carry evidence")
# ...and what a refused stamp costs, which is not what a refused POINTER costs.
# `--reconcile` re-derives pointers from the ledger and does not touch this key,
# so naming it here would send a human to a repair that cannot make the write.
# Nothing has to: the ledger row is already standing, the boundary still derives
# from it, and the next recorded run with the lock free writes the key down.
SINCE_HINT = ("nothing is lost - the ledger still dates the boundary, and the "
              "next --record taken with the lock free writes the key")


def since_block(manifest):
    """`meta.evidenceSince` exactly as the plan states it, or None when it has none.

    THE BLOCK AND THE MOMENT ARE TWO QUESTIONS. A plan carrying no key and a plan
    carrying one that states no usable moment are different states with different
    repairs -- write the key, versus fix the key that is there -- and a reader
    handed only the moment could not tell them apart.
    """
    meta = manifest.get("meta") if isinstance(manifest, dict) else None
    block = meta.get(SINCE_KEY) if isinstance(meta, dict) else None
    return block if isinstance(block, dict) else None


def stated_at(block):
    """The moment a `meta.evidenceSince` block states, or None when it states none.

    A non-string or blank `at` answers None rather than raising: this is read on
    every gate verdict, and a hand-edited plan must not take the surface down. The
    caller is told which of the two silences it met by `boundary_of`'s basis.
    """
    at = block.get("at") if isinstance(block, dict) else None
    return at.strip() if isinstance(at, str) and at.strip() else None


def earliest_recorded(rows):
    """The earliest `ts` any recorded run carries, or None when none carries one.

    BY MOMENT, `oldest_first`'s order - `latest_by_subject`'s rule at the other
    end of the same list. A row's `ts` is not always `_utc_stamp`'s spelling (a
    caller may hand one in, an imported shard carries another writer's), and as text an
    offset or a fractional second sorts by how it is written. A `ts` that will
    not parse is the answer only when no row's does, and then the least as text,
    which is all such a stamp can be ordered by.
    """
    dated = [r for r in oldest_first(rows) if _ts_moment(r) is not None]
    if dated:
        return dated[0].get("ts")
    stamps = [r.get("ts") for r in rows or []
              if isinstance(r, dict) and isinstance(r.get("ts"), str)
              and r.get("ts").strip()]
    return min(stamps) if stamps else None


def unplaced_stamps(rows):
    """What `earliest_recorded` passes over, in ledger order, each once: every
    `ts` that `stamp_moment` cannot place, and - named by its run, since it has
    no stamp to quote - every row whose `ts` is missing, blank or not text.

    A row with no stamp is still a recorded run, and it may be the earliest
    one; leaving it out would let a ledger of such rows read as an empty one.
    """
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        ts = row.get("ts")
        if isinstance(ts, str) and ts.strip():
            label = ts if stamp_moment(ts) is None else None
        else:
            label = "run %s has no ts" % (row.get("runId") or "?",)
        if label is not None and label not in out:
            out.append(label)
    return out


def boundary_of(block, ledger_at, unknown=None):
    """The boundary from two already-read sources. The pure half of the question.

    `{"at", "sources", "basis", "unknown"}`. `at` is None when NEITHER source
    answered, which is the state of a repository that has never recorded anything
    -- everything in it predates recording, and the basis says exactly that rather
    than leaving a reader to infer it from a null.

    `unknown` is the half that must not be folded into "absent". A source that
    could not be ASKED -- an unreadable plan, a torn ledger line -- may have held
    an EARLIER moment, so treating it as absent moves the boundary later and
    widens the excuse in silence. Every such source is named here, and a caller
    with a non-empty list is holding a boundary that may be later than the truth.
    """
    key_at = stated_at(block)
    # The earlier MOMENT of the two: the plan's stamp is hand-written and need
    # not share the ledger's spelling.
    at = earliest_recorded([{"ts": s} for s in (key_at, ledger_at)
                            if s is not None])
    unknown = list(unknown or [])
    asked_unknown = list(unknown)
    # A STAMP THAT NAMES NO MOMENT IS NEVER DROPPED IN SILENCE. It cannot be
    # compared, so the other source (when there is one) becomes the boundary -
    # and that may be LATER than the start the stamp meant. `unknown` is this
    # function's word for exactly that, so the stamp is named there, where the
    # gate reads it, as well as in the basis.
    key_lost = key_at is not None and stamp_moment(key_at) is None
    ledger_lost = ledger_at is not None and stamp_moment(ledger_at) is None
    if key_lost:
        unknown.append("%s states %r, which names no moment (an ISO timestamp "
                       "or an ISO date does), so the start it means cannot be "
                       "placed and the boundary may be later than the truth"
                       % (SINCE_KEY, key_at))
    if ledger_lost:
        unknown.append("the earliest recorded run's ts is %r, which names no "
                       "moment, so where recording began cannot be placed from "
                       "the ledger" % (ledger_at,))
    if key_lost or ledger_lost:
        basis = ("the stamp(s) %s name no moment this can place, so they are "
                 "not compared; the boundary %s, and it may be later than the "
                 "truth" % (
                     ", ".join(repr(s) for s in (key_at, ledger_at)
                               if s is not None and stamp_moment(s) is None),
                     ("is %s" % (at,)) if stamp_moment(at) is not None
                     else "cannot be placed at all"))
    elif key_at is not None and ledger_at is not None:
        basis = ("the plan states recording began %s and the earliest recorded "
                 "run is %s; the earlier of the two is the boundary, because "
                 "work before it could not have been recorded" % (key_at, ledger_at))
    elif key_at is not None and asked_unknown:
        basis = ("the plan states recording began %s; no run in the ledger "
                 "places a moment to confirm it, and what could not be read or "
                 "placed is listed as unknown" % (key_at,))
    elif key_at is not None:
        basis = ("the plan states recording began %s; no run is readable in the "
                 "ledger to confirm it" % (key_at,))
    elif ledger_at is not None and block is not None:
        basis = ("the plan carries %s but it states no usable moment, so the "
                 "boundary is the earliest recorded run, %s"
                 % (SINCE_KEY, ledger_at))
    elif ledger_at is not None:
        basis = ("this plan carries no %s, so the boundary is the earliest "
                 "recorded run, %s" % (SINCE_KEY, ledger_at))
    elif asked_unknown:
        # Not "no run is readable": a source the caller could not read or
        # place may hold a run, which is what `unknown` lists.
        basis = ("nothing places when recording began: this plan states no "
                 "moment in %s and no run in its ledger places one, and what "
                 "could not be read or placed is listed as unknown - so this "
                 "boundary cannot be trusted" % (SINCE_KEY,))
    else:
        basis = ("nothing says when recording began: this plan carries no %s and "
                 "no run is readable in its ledger, so no work in it could have "
                 "carried evidence" % (SINCE_KEY,))
    # HANDED ON IN THE ONE Z SPELLING whenever the moment was placed. The
    # consumer (`_status_facts._gap_of`) is this module's layer-mate and reads
    # `at` with `_usage_core.parse_ts`, which does not read a date - so a
    # placed boundary is spelled the way it reads. The basis and `sources`
    # keep the plan's own text. A fractional second is dropped, which moves
    # the boundary earlier: the direction that excuses less, never more.
    placed = stamp_moment(at)
    if placed is not None:
        at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(placed)))
    return {"at": at, "sources": {"key": key_at, "ledger": ledger_at},
            "basis": basis, "unknown": unknown}


def evidence_boundary(project, manifest_path, config=None):
    """The boundary, read from the plan and the ledger. Never raises.

    The door `boundary_of` sits behind: this is the one that touches disk, so a
    surface asking "may this subject be excused" gets an answer on a repository
    with no plan, no ledger, or neither.
    """
    config = _journal_io.load_config(project) if config is None else config
    unknown, block = [], None
    try:
        block = since_block(_mio.read_json(manifest_path))
    except Exception as exc:
        # NOT "no key". An unreadable plan may hold an EARLIER moment than the
        # ledger's, and calling that absent moves the boundary later -- the one
        # direction that widens an excuse without saying anything.
        unknown.append("the plan could not be read (%s), so anything %s states "
                       "is unknown" % (exc, SINCE_KEY))
    read = read_rows(project, config=config, manifest_path=manifest_path)
    if read["unreadable"]:
        unknown.append("%d ledger row(s) could not be parsed, and one of them may "
                       "carry an earlier run than any that could"
                       % (read["unreadable"],))
    if read.get("unreadablePlanFiles"):
        unknown.append("plan file(s) %s could not be read, and a record there "
                       "may carry an earlier run than any that could"
                       % (", ".join(read["unreadablePlanFiles"]),))
    ledger_at = earliest_recorded(read["rows"])
    # A row whose ts names no moment - or that carries none - is passed over
    # by `earliest_recorded`, and it may be the earliest run. Named here, so
    # the boundary says it may be later than the truth; the one stamp
    # `boundary_of` is handed as `ledger_at` it names itself.
    unplaced = [u for u in unplaced_stamps(read["rows"]) if u != ledger_at]
    if unplaced and stamp_moment(ledger_at) is not None:
        unknown.append("ledger row(s) carry a ts that names no moment (%s), so "
                       "where they fall is unknown and one of them may be an "
                       "earlier run than %s" % (_output.some_of(unplaced),
                                                ledger_at))
    elif unplaced:
        unknown.append("ledger row(s) carry no ts that names a moment (%s), so "
                       "where recording began cannot be placed from the "
                       "ledger although a run is recorded there"
                       % (_output.some_of(unplaced),))
    return boundary_of(block, ledger_at, unknown=unknown)


def project_config_for(manifest_path, project_dir=None):
    """`(project, config)` for this module, pointed at THIS manifest's record.

    `manifestPath` is overridden with the file actually being read, and that is
    not a shortcut. A surface reads the manifest it was HANDED, which is not
    always the one a project's config names -- `examples/acme-store/audit-plan.json`
    inside this very repository is exactly that case -- and resolving the record
    off the config's manifest would attribute one plan's runs to another plan's
    tasks. That is the failure `usage_ledger.find_ledger_dir` was written to
    avoid, one directory over.

    IT MATTERS MOST TO THE BOUNDARY, which is why this sits here rather than in
    the report where it was written. Reading the wrong plan's ledger USUALLY only
    moves the boundary earlier -- `min` over more rows -- and an earlier boundary
    excuses less, loudly. But missing this plan's ledger entirely leaves nothing
    to date the boundary with, and a boundary of None excuses EVERYTHING. So the
    gate needs the same answer the report already had, and two expressions of it
    would be two ledgers for one plan.

    `evidence.dir` is deliberately left alone: a project that declares one has
    said where its record lives, and this has no better answer than the
    declaration.

    THE PROJECT IS `project_dir`, ELSE `_output.project_of_manifest` - the
    walk `run-test-gate.py`, the report, the status read and the
    manifest-writing commands take when no root is named. Neither the session's
    `CLAUDE_PROJECT_DIR` nor the manifest's own directory is consulted: the
    first may name another checkout than the one the plan is in, and the
    second is `docs/audit` on nearly every plan, so a hand-run gate with no
    session behind it sited its raw log at `docs/audit/.claude/` - and that
    stray marker then made the plan's project `docs/audit` for every later run.
    """
    project = project_dir or _output.project_of_manifest(manifest_path)
    try:
        config = dict(_journal_io.load_config(project) or {})
    except Exception:
        config = {}
    try:
        # "/" separators regardless of platform: this key is what every other
        # reader of `config` expects to hold a manifest path, and the manifest
        # is stored with forward slashes.
        config["manifestPath"] = _output.posix_rel(
            os.path.abspath(manifest_path), os.path.abspath(project))
    except Exception:
        pass
    return project, config


def boundary_for(manifest_path, project_dir=None):
    """The boundary for the plan at `manifest_path`, wherever that plan sits.

    The one line a caller above this module writes to hand `rollup` a boundary. It
    resolves the record the way every other reader of this module does and then
    asks the same `evidence_boundary`, so the gate's boundary and the report's
    ledger cannot come from two different directories.

    NEVER RAISES, AND NEVER ANSWERS "no boundary" BY INVENTING ONE. A read that
    fell over comes back as a block whose `unknown` names it, because a source
    that could not be ASKED may have held an EARLIER moment: calling it absent
    moves the boundary later and widens the excuse in silence, while naming it
    leaves the caller holding a boundary it can refuse to excuse anything on.
    """
    try:
        project, config = project_config_for(manifest_path, project_dir)
        return evidence_boundary(project, manifest_path, config=config)
    except Exception as exc:
        return boundary_of(None, None, unknown=[
            "the evidence boundary could not be read (%s), so neither %s nor "
            "the ledger could be asked when recording began"
            % (exc, SINCE_KEY)])


def since_from_rows(rows):
    """`{"at", "runId", "basis"}` for the earliest recorded run, or None for none.

    THE PROVENANCE AND THE MOMENT COME OFF THE SAME ROW, which is what makes the
    block's `basis` true: `at` is when the first recorded run happened and `runId`
    names that run, rather than naming whichever run happened to be writing the
    key. `runId` is dropped when the row carries none -- an empty string would be
    a pointer at nothing, and this block is read as provenance.

    PUBLIC BECAUSE IT HAS TWO CALLERS. The recorder stamps a real plan with it;
    `gen-demo-manifest.py` stamps the fixture with it, for the reason every row
    in that fixture already goes through `row_for` - a demo that spelled the
    block itself would be a second answer to what `meta.evidenceSince` IS, and
    the first thing it would get wrong is which row the `runId` names.
    """
    at = earliest_recorded(rows)
    if at is None:
        return None
    first = [r for r in rows if isinstance(r, dict) and r.get("ts") == at]
    run_id = str(first[0].get("runId") or "") if first else ""
    out = {"at": at}
    if run_id:
        out["runId"] = run_id
    out["basis"] = SINCE_BASIS
    return out


def _refused(reason, at=None):
    """The shape every declined stamp answers with, so a caller reads one dict."""
    return {"written": False, "reason": reason, "at": at, "path": None}


def write_evidence_since(project, manifest_path, phase_id=None, session_id=None,
                         config=None, wait=None):
    """Stamp `meta.evidenceSince` the first time this plan records a run.

    `{"written", "reason", "at", "path"}`, plus `releaseRefused` -- the sentences
    for a lock that declined to be given back, which says another session took
    it over while this stamp was being written. It is present on the refusing
    paths too, because a run that was displaced was displaced whether or not its
    own write went in.

    THE WRITE IS `write_plan_file`'s, of the INDEX: `meta` lives there, the
    plan-file lock is taken, and whether a boundary is already stated is asked
    again of the index as read under it. That lock is the one every writer of
    the index takes - and in the one-file layout the index is the phase body
    too, which is why the phase lock it once took as well is not needed: the
    pointer and the record now take this same lock.

    Every `written: False` is a designed
    outcome carrying a sentence -- an already-stamped plan, a plan with nothing to
    date the boundary from, a lock another session is holding -- and none of them
    is an error path, because the ledger row is standing in every one of them.

    WRITTEN ONCE, AND NEVER RE-DERIVED. A key already present is left exactly as
    it is: re-deriving it every run would make the boundary a value that MOVES,
    and the direction it would move is later, which widens the excuse. Once a
    human or a run has written it down it is the plan's own claim.

    IT IS THE INDEX THIS WRITES, unlike the pointer beside it, and that is
    affordable for one reason only: it happens once in a plan's life. `meta` lives
    on the index in the sharded layout, so a per-run write here would put every
    parallel phase back in each other's way -- the conflict the layout exists to
    avoid. One write, once, is not that.
    """
    config = _journal_io.load_config(project) if config is None else config
    try:
        body = _mio.read_json(manifest_path)
    except Exception as exc:
        return _refused("cannot read %s: %s"
                        % (repo_relative_or_token(project, manifest_path), exc))
    meta = body.get("meta") if isinstance(body, dict) else None
    if not isinstance(meta, dict):
        return _refused("this manifest has no meta object to carry the boundary")
    standing = since_block(body)
    if standing is not None:
        return _refused("%s already states %s; a boundary is derived once and "
                        "never moved" % (SINCE_KEY, stated_at(standing)),
                        at=stated_at(standing))
    derived = since_from_rows(read_rows(project, config=config,
                                       manifest_path=manifest_path)["rows"])
    if derived is None:
        # THE BASIS IS THE THING THAT IS MISSING, so this is what gets said. A
        # stamp taken from the wall clock here would date the boundary from the
        # moment somebody happened to run the gate, and every task finished after
        # that moment and before this one would be excused by a claim with
        # nothing behind it.
        return _refused("no recorded run to date the boundary from")
    def change(index):
        # ASKED AGAIN UNDER THE LOCK: a stamp another run wrote while this one
        # waited is the plan's own claim now, and is left exactly as it is.
        meta_now = index.get("meta") if isinstance(index, dict) else None
        if not isinstance(meta_now, dict):
            return None, ("this manifest has no meta object to carry the "
                          "boundary"), None
        stated = since_block(index)
        if stated is not None:
            return None, ("%s already states %s; a boundary is derived once and "
                          "never moved" % (SINCE_KEY, stated_at(stated))), \
                stated_at(stated)
        meta_now[SINCE_KEY] = derived
        return index, None, None
    got = write_plan_file(project, manifest_path, change,
                          "stamping the evidence boundary",
                          session_id=session_id, wait=wait,
                          outcome="the boundary was not stamped",
                          repair=SINCE_HINT, config=config)
    answer = ({"written": True, "reason": None, "at": derived["at"],
               "path": manifest_path} if got["written"]
              else _refused(got["reason"], at=got["answer"]))
    # A DECLINED RELEASE IS THE ONLY NEWS OF A TAKEOVER THIS RUN GETS, on the
    # refusing path as on the written one: a run displaced while it held the
    # lock was displaced whether or not its own stamp went in.
    if got["releaseRefused"]:
        answer["releaseRefused"] = [got["releaseRefused"]]
    if not answer["written"]:
        return answer
    # ONLY NOW, and for `write_pointer`'s reason one field over: this row asserts
    # that the PLAN moved, so it is written after the move and never beside the
    # attempt. A refused stamp returns above without reaching here, which is what
    # keeps the chain from claiming a transition that did not happen.
    details = {"field": SINCE_KEY, "from": None, "to": derived["at"]}
    if derived.get("runId"):
        details["runId"] = derived["runId"]
    if phase_id is not None:
        details["phaseId"] = str(phase_id)
    _journal_io.append_from_cli(project, {
        "action": ACTION_SINCE,
        "actor": {"sessionId": session_id, "via": "evidence"},
        "target": repo_relative_or_token(project, manifest_path),
        # THE SENTENCE IS THE BLOCK'S OWN, spent out of the same constant the
        # plan carries rather than paraphrased here: a summary that restated the
        # basis in its own words would be a second copy free to drift from the
        # one a reader of the manifest sees.
        "summary": "the evidence boundary is %s: %s" % (derived["at"], SINCE_BASIS),
        "details": details,
    }, config=config)
    return answer


def new_run_id():
    """A fresh, opaque run id: a stamp plus randomness.

    THE STAMP IS A CONVENIENCE FOR A HUMAN READING THE RAW FILE AND NOTHING MORE.
    The id is documented as OPAQUE and the schema says so, because the moment a
    reader parses it the format becomes an interface nobody agreed to - which is
    why `at` is a field of its own rather than something a consumer slices out of
    here.
    """
    return "%s.%s" % (_utc_stamp.utc_stamp(), binascii.hexlify(os.urandom(3)).decode("ascii"))


