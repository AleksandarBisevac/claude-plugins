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

EVERY ANCHOR ROW HERE GOES THROUGH `_journal_io.append_from_cli` (F287), not
`append`. `run-test-gate.py` is the only caller of the functions here that write
one, and it is a script the operator runs from Bash: nothing else can claim the
journal file the append dirties -- the journal-writes hook files its claim under a
session id no script is handed, and the panel files under its own -- so an
unclaimed row made the NEXT Bash command draw `guard-bash-writes`' notice about a
write this plugin had just made itself.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__evidence_io.py` -- see `plugins/audit/tests/_harness.py`.
"""
import binascii
import calendar
import os
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

import _journal_io  # noqa: E402  (config loading, the writer id, the month)
import _locks  # noqa: E402  (whose phase lock, and is it live)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; the atomic write)
from _journal_io import (command_facts, redacted_paths,  # noqa: E402
                         redacted_text, repo_relative_or_token)

DEFAULT_DIRNAME = "evidence"


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
    """Every path THIS recorder writes, as project-relative prefixes, sorted.

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

    A PATH OUTSIDE `project` IS DROPPED rather than returned relative, and the
    drop is safe in the one direction that matters: it leaves MORE of the tree
    inside the identity, and git never names such a path anyway.
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
    rels = []
    for path in writes:
        try:
            rel = os.path.relpath(path, project).replace(os.sep, "/")
        except Exception:
            continue
        if rel == ".." or rel.startswith("../") or rel == ".":
            continue
        rels.append(rel)
    return sorted(set(rels))


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
# The identity that has to match for one run to stand in for another. It is
# recorded on the row rather than re-derived, because it is a statement about the
# tree AT THAT MOMENT and the moment is gone.
REUSE_KEY = "reuseKey"

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
# the row because `exit` and `outcome` can be read for it and a cached claim can
# contradict its own source; that risk is what the rule guards. It cannot arise
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
# hold the evidence, so a reader a week later can name the signal without being
# told it. That does not hold here. Every other field of a retried step - its
# exit, its count, its duration, its outcome - describes the attempt that
# ANSWERED, and nothing in the row says an earlier attempt was ended by the OS
# and thrown away, which means a green row would read as a gate that answered on
# the terms the plan declared. The basis travels with the word because the second
# attempt may have run under a lowered worker bound or under the same one, and
# those are different claims about what was measured.
STEP_KEYS = ("name", "exit", "ran", "measured", "durationMs", "outcome",
             "timeoutSeconds", "teardown", "failing", "failingBasis",
             "retriedAfterSignal", "retryBasis")
STATE_KEYS = ("head", "headBasis", "scopeDigest", "scopeBasis", "dirtyDigest",
              "dirtyBasis")
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


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


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
        if key == "failing":
            # THE ONE FIELD WHOSE CONTENT A RUNNER WROTE, so both rules that keep
            # a committed row safe land here and nowhere else in this loop. The
            # cut is taken by the WRITER rather than trusted from the caller,
            # exactly as `_paths` takes `MAX_PATHS`; `redacted_text` is the
            # journal's own redactor, so an absolute path in a stack frame is
            # answered by the same map that answers one in `cwd`.
            out[key] = [redacted_text(project, line)
                        for line in step[key][:MAX_FAILING]]
            continue
        out[key] = step[key]
    command = step.get("command")
    if command is None:
        return out
    if str(command) in set(str(c) for c in (published or [])):
        out["command"] = str(command)
    else:
        out.update(command_facts(str(command)))
    return out


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
        "ts": str(identity.get("ts") or _now()),
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
    # an omission (F280). The word says the gate rewrote files the work under test
    # declares; `treeMutated` already holds every path that moved and `treeBasis`
    # already ends with either "N of M changed path(s) are declared by the work
    # under test" or the sentence saying no ownership could be sorted, which are
    # exactly the two ways `run_status` reaches the word. A `treeMutatedOwned` key
    # here would be a second copy of a claim the row can already be read for, and
    # this file's rule about a cached count applies to a cached classification
    # just as well.
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
    # WHERE THE `steps` LIST CAME FROM (F312). `steps` names the entries that
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
    # PRESENT ONLY WHEN SOMETHING WENT. A count that appears solely when non-zero
    # cannot be told from a count nobody computed, so its ABSENCE has to mean
    # "nothing was cut" and never "nobody looked".
    if steps[MAX_STEPS:]:
        row["stepsDropped"] = len(steps) - MAX_STEPS
    if mut_dropped:
        row["treeMutatedDropped"] = mut_dropped
    if cov_dropped:
        row["coverageDropped"] = cov_dropped
    # The three-valued fields keep their shape at the TOP level too, so a reader
    # that never opens `observations` still cannot mistake unknown for clean.
    row["treeMutated"] = row["observations"]["treeMutated"]
    return row


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


# --- writing and reading ------------------------------------------------------
def append_row(project, row, session_id=None, config=None):
    """Append one row, chained onto the file's tail; return the file it landed in.

    THE LOCK IS THE CHAIN'S, and it is why this is no longer the bare O_APPEND the
    usage ledger gets away with. `prev` is read off the last row in the file, so
    two appends by one writer that both read that tail would write the same `prev`
    and produce a break indistinguishable from a deleted run. The journal's own
    lock is taken rather than a second one written here; when it cannot be taken
    the append RAISES, because a false tamper verdict is worse than a missing row
    and `record()` already declines to report a run whose evidence was not stored.
    """
    config = _journal_io.load_config(project) if config is None else config
    directory = evidence_dir(project, config)
    os.makedirs(directory, exist_ok=True)
    actor = {"sessionId": session_id} if session_id else {}
    path = _journal_io.file_for(
        directory, row.get("ts") or _now(), actor,
        fallback=None if _journal_io.has_session(actor)
        else _journal_io.writer_token(project, config))
    lock = _journal_io._acquire(path, record="the evidence ledger")
    try:
        rows, _torn = _journal_io.read_file(path)
        tail = [r for r in rows if not r.get("_unparseable")]
        linked = chain_onto(row, tail, os.path.basename(path))
        with open(path, "a", encoding="utf-8") as fh:
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


def read_rows(project, config=None):
    """`{"rows", "files", "unreadable"}` - every recorded run, and what was lost.

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
    """
    config = _journal_io.load_config(project) if config is None else config
    rows, unreadable, files = [], 0, 0
    for path in ledger_files(project, config):
        files += 1
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except Exception:
            unreadable += 1
            continue
        parsed, torn = _journal_io.rows_from_text(text)
        for obj in parsed:
            if obj.get("_unparseable"):
                unreadable += 1
            else:
                rows.append(obj)
        if torn:
            unreadable += 1
    return {"rows": rows, "files": files, "unreadable": unreadable}


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
    ever reaching for that field."""
    if step.get("outcome"):
        return True
    exitcode = step.get("exit")
    return exitcode is not None and exitcode != 0


def _matching_steps(rows, key, value):
    """Every step across `rows` whose `key` equals `value`, in row order.

    `rows` is whatever `read_rows(...)["rows"]` returned - unordered by this
    function's own contract, since a tally needs a count and not a sequence.
    A caller that wants oldest-first sorts by `ts` before calling this."""
    out = []
    for row in (rows or []):
        for step in (row.get("steps") or []):
            if isinstance(step, dict) and step.get(key) == value:
                out.append({"ts": row.get("ts"), "runId": row.get("runId"),
                            "exit": step.get("exit"), "outcome": step.get("outcome"),
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
    caught = sorted(h["ts"] for h in hist if h.get("ts") and _step_failed(h))
    return caught[-1] if caught else None


def gate_cost_ms(rows, name):
    """Total recorded run time (ms) for the named gate across `rows`, summed
    over every matching step that carries one. `None` when not one step did --
    absent means UNMEASURED, never zero, which is `phase_budgets`' rule read
    for a run's own cost rather than for the plan's declared one."""
    total, seen = 0, False
    for row in (rows or []):
        for step in (row.get("steps") or []):
            if not (isinstance(step, dict) and step.get("name") == name):
                continue
            duration = step.get("durationMs")
            if isinstance(duration, (int, float)) and not isinstance(duration, bool):
                total += duration
                seen = True
    return total if seen else None


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
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
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


def record(project, result, scope, ids, identity, published=None, config=None):
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
    """
    config = _journal_io.load_config(project) if config is None else config
    row = row_for(project, result, scope, ids, identity, published=published)
    path = append_row(project, row, session_id=identity.get("sessionId"),
                      config=config)
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
RECONCILE_HINT = ("the run is recorded; re-run with --reconcile once the holder "
                  "is done to point the plan at it")


def pointer_for(row):
    """The three keys the manifest caches: identity, verdict, time.

    NOTHING COUNTABLE. An attempt number and a count of runs were both cut: the
    attempt is on the row where it is written once, and a count is derived by
    reading the ledger. A cached count is this repository's most repeated defect.
    """
    return {"runId": row.get("runId"), "status": row.get("status"),
            "at": row.get("ts")}


def lock_state(project, name, label, session_id=None, hint=""):
    """`(state, detail)` -- may this session write what `name` guards, and if not why.

    `free` | `ours` | `held` | `stale` | `unlockable`.

    `ours` EXISTS BECAUSE `_locks.acquire` IS NOT RE-ENTRANT. A gate recorded from
    inside its own phase run meets the lock that run already holds, and acquiring
    would refuse it -- which is every in-phase recording there is. So the holder's
    session is COMPARED rather than the lock re-taken.

    `unlockable` is the panel's documented third answer, kept for its reason: a
    project with no `.git` has no lock scheme and never had one, and refusing
    every such project would refuse a case that has an answer.

    A STALE LOCK IS NOT TAKEN OVER HERE. Taking one over is a decision a human
    makes with `audit-lock --takeover` after confirming the holder is dead; a
    cache write must not make it quietly.

    `hint` IS THE CALLER'S REPAIR AND NOT THIS FUNCTION'S. Two writers ask this
    question now and the repairs differ -- a refused pointer is caught up by
    `--reconcile`, a refused boundary needs nothing at all -- so a shared sentence
    here would send half the callers somewhere that cannot help them.
    """
    try:
        if not _locks.available(project):
            return "unlockable", "this project has no lock scheme"
        path = os.path.join(_locks.lock_dir(project), "%s.lock" % (name,))
        if not os.path.exists(path):
            return "free", ""
        info = _locks.read_lock(path)
        holder = info.get("sessionId")
        if holder and session_id and str(holder) == str(session_id):
            return "ours", "held by this session"
        live, basis = _locks.judge(info, path)
        if live:
            return "held", ("the %s lock is held by another live run (%s); %s"
                            % (label, basis, hint))
        return "stale", ("the %s lock looks abandoned (%s); confirm with a "
                         "human and use audit-lock --takeover, then %s"
                         % (label, basis, hint))
    except Exception as exc:
        return "held", ("the %s lock could not be read (%s); %s"
                        % (label, exc, hint))


def pointer_lock_state(project, phase_id, session_id=None):
    """`(state, detail)` -- may this session write the phase's shard, and if not why.

    The pointer's spelling of `lock_state`: the phase lock, and the repair a
    refused pointer names. It stays a named function because the phase lock is
    what the POINTER is about, and a call site spelling the lock name itself is
    one that can spell it differently next year.
    """
    return lock_state(project, "phase-%s" % (phase_id,), "phase",
                      session_id=session_id, hint=RECONCILE_HINT)


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
                  config=None):
    """Point the plan at a recorded run.
    `{"written", "reason", "path", "releaseRefused"}`.

    `releaseRefused` is set only on the written path, and only when the phase
    lock declined to be given back -- which says another session took it over
    while this pointer was being written. A write that succeeded is still
    `written: True`; what the sentence adds is that something else was writing
    beside it, and the caller prints it rather than the lock losing it.

    WRITES THE SHARD AND NEVER THE INDEX. A task commit that carried the index is
    what makes two parallel phases conflict on merge, and the pointer is a runtime
    field, so it belongs in the phase body exactly as `status` and `attempts` do.

    Every `written: False` here is a DESIGNED outcome carrying a sentence, not an
    error path: a refused cache write leaves the ledger row standing, which is the
    only reachable partial state and the harmless one.
    """
    pointer = pointer_for(row)
    state, detail = pointer_lock_state(project, ids.get("phaseId"),
                                       session_id=session_id)
    if state in ("held", "stale"):
        return {"written": False, "reason": detail, "path": None}
    path, sharded = _phase_file(manifest_path, ids.get("phaseId"))
    if not path or not os.path.exists(path):
        return {"written": False,
                "reason": "no phase %r in this manifest" % (ids.get("phaseId"),),
                "path": None}
    try:
        body = _mio.read_json(path)
    except Exception as exc:
        return {"written": False, "reason": "cannot read %s: %s"
                % (_journal_io.repo_relative_or_token(project, path), exc),
                "path": None}
    previous, problem = _set_pointer(body, scope, ids, pointer, sharded)
    if problem:
        return {"written": False, "reason": problem, "path": None}
    lock_name = "phase-%s" % (ids.get("phaseId"),)
    code = None
    if state == "free":
        code = _locks.acquire(project, lock_name,
                              note="recording test evidence",
                              session=session_id, out=lambda *_a: None)
        if not _locks.held(code):
            return {"written": False,
                    "reason": "the phase lock could not be taken; " + RECONCILE_HINT,
                    "path": None}
    # WHAT MAY BE GIVEN BACK IS A NARROWER QUESTION THAN WHAT MAY BE WRITTEN
    # UNDER. `_locks.took` is the one that answers it: a lock this run already
    # held is held, and releasing it here would take it from the run that is
    # still using it.
    refused = None
    try:
        _mio.atomic_write_json(path, body)
    finally:
        if _locks.took(code):
            rcode = _locks.release(project, lock_name, session=session_id,
                                   out=lambda *_a: None)
            if rcode != 0:
                # THE REFUSAL IS A VALUE SOMEBODY READS. It says another session
                # took this phase's lock while the pointer was being written, so
                # the write above may have raced one of theirs -- and it used to
                # go into a printer that discards and a code nobody looked at.
                refused = _locks.release_refusal(rcode, lock_name)
    # ONLY NOW. This row says the PLAN moved, and it is written after the move
    # rather than beside the attempt: a refused write above returns before
    # reaching here, so the chain can never assert a transition that did not
    # happen. That is the whole reason this is a second action and not the row
    # `record()` already wrote -- that one's subject is the evidence file and it
    # was true the moment it was written.
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
    return {"written": True, "reason": None, "path": path,
            "releaseRefused": refused}


# --- who ran it, when, and who else was running --------------------------------
def _epoch(text):
    """`%Y-%m-%dT%H:%M:%SZ` as epoch seconds, or None when it is not that shape.

    None rather than a substitute: a stamp this cannot read is a row that cannot
    take part in an overlap question, and a zero would put it at the start of the
    epoch where it would overlap nothing and look like an answer.
    """
    try:
        return calendar.timegm(time.strptime(str(text), "%Y-%m-%dT%H:%M:%SZ"))
    except Exception:
        return None


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


def _overlaps(one, other):
    """Whether two `(start, end)` pairs share any moment. Inclusive at the
    endpoints, because two runs that met for one second met."""
    return one[0] <= other[1] and other[0] <= one[1]


def overlapping_runs(rows, row, runner):
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
    """
    start, end, basis = window_of(row)
    if start is None:
        return (None, basis)
    mine = str((row or {}).get("runId") or "")
    found = []
    for other in (rows or []):
        if not isinstance(other, dict):
            continue
        if mine and str(other.get("runId") or "") == mine:
            continue
        if runner_of(other) != runner:
            continue
        o_start, o_end, _why = window_of(other)
        if o_start is None:
            continue
        if _overlaps((start, end), (o_start, o_end)):
            found.append(other)
    return (found, basis)


def contested_by(rows, row):
    """`(contesting, basis)` — the runs from OUTSIDE this gate whose window
    overlaps `row`'s. `overlapping_runs` with the runner decided, so no caller
    can ask the outside question and get the machine one."""
    return overlapping_runs(rows, row, RUNNER_OUTSIDE)


def shared_the_machine(rows, row):
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
    return overlapping_runs(rows, row, RUNNER_GATE)


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


def latest_by_subject(rows):
    """The newest recorded run per `(scope, id)`, keyed for a pointer write.

    NEWEST BY `ts` AND NOT BY FILE ORDER. Rows land in one file per writer per
    month, so two worktrees produce two files whose concatenation is in no
    meaningful order at all; reading position would make "the latest run" depend
    on a directory listing.

    A row missing the id its own scope needs is skipped rather than guessed at -
    it cannot be pointed at anything, and inventing a subject for it would put a
    pointer on a task that never ran.
    """
    best = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        scope = row.get("scope")
        subject = row.get("taskId") if scope == "task" else row.get("phaseId")
        if not scope or not subject or not row.get("runId"):
            continue
        key = (scope, str(subject))
        current = best.get(key)
        if current is None or str(row.get("ts") or "") >= str(current.get("ts") or ""):
            best[key] = row
    return best


def _same_subject(row, ids):
    """Do a row and a set of identity keys name the same work?

    Compared as strings and with ABSENT kept distinct from any value, which is
    `row_for`'s own rule read back: a phase-scope row carries no `taskId` at all,
    and letting a missing key match a present one would hand a phase's verdict to
    a task.
    """
    for key in ("taskId", "phaseId"):
        left = row.get(key)
        right = (ids or {}).get(key)
        if (left is None) != (right is None):
            return False
        if left is not None and str(left) != str(right):
            return False
    return True


def reusable_run(rows, scope, ids, key, statuses):
    """The newest recorded run a caller may repeat instead of measuring, or None.

    FIVE CONDITIONS AND EVERY ONE OF THEM NARROWS. The identity has to match, the
    subject has to be the same work, the row has to be a MEASUREMENT rather than
    another repeat, and the verdict has to be one the caller says may be
    repeated. Drop any of them and this returns a run that answers a different
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
    best = None
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if row.get(REUSE_KEY) != key:
            continue
        if row.get(VERDICT_SOURCE) == REUSED:
            continue
        if row.get("status") not in statuses:
            continue
        if str(row.get("scope") or "") != str(scope or ""):
            continue
        if not _same_subject(row, ids):
            continue
        if best is None or str(row.get("ts") or "") >= str(best.get("ts") or ""):
            best = row
    return best


def reconcile(project, manifest_path, session_id=None, config=None):
    """Re-derive every pointer from the ledger. The repair `write_pointer` names.

    THIS IS WHY THE POINTER MAY BE REFUSED AT ALL. A cache write that loses a race
    with another live session leaves the plan behind the record, and this is the
    pass that catches it up - so the refusal costs a reader one command and never a
    fact. The ledger is the source of truth; nothing here reads the manifest to
    decide what is true, only to decide what still needs saying.

    Returns `{"moved", "refused", "already", "unreadable", "subjects"}`. `moved`
    and `refused` carry sentences, because a reconcile that could not finish must
    say which subjects it left behind rather than reporting a smaller number.
    """
    config = _journal_io.load_config(project) if config is None else config
    read = read_rows(project, config=config)
    best = latest_by_subject(read["rows"])
    moved, refused, already = [], [], []
    for (scope, subject), row in sorted(best.items()):
        if scope == "task":
            ids = {"taskId": subject, "phaseId": row.get("phaseId")}
        else:
            ids = {"phaseId": subject}
        current = _current_pointer(manifest_path, scope, ids)
        if current and current.get("runId") == row.get("runId"):
            already.append("%s %s" % (scope, subject))
            continue
        out = write_pointer(project, manifest_path, scope, ids, row,
                            session_id=session_id, config=config)
        if out["written"]:
            moved.append("%s %s -> %s" % (scope, subject, row.get("runId")))
        else:
            refused.append("%s %s: %s" % (scope, subject, out.get("reason")))
    return {"moved": moved, "refused": refused, "already": already,
            "unreadable": read["unreadable"], "subjects": len(best)}


def _current_pointer(manifest_path, scope, ids):
    """The pointer a subject carries now, or None. Never raises."""
    try:
        path, sharded = _phase_file(manifest_path, ids.get("phaseId"))
        if not path or not os.path.exists(path):
            return None
        body = _mio.read_json(path)
        phases = [body] if sharded else [
            p for p in (body.get("phases") or [])
            if isinstance(p, dict) and str(p.get("id")) == str(ids.get("phaseId"))]
        if not phases:
            return None
        if scope == "phase":
            return phases[0].get(POINTER_KEY)
        for task in (phases[0].get("tasks") or []):
            if isinstance(task, dict) and str(task.get("id")) == str(ids.get("taskId")):
                return task.get(POINTER_KEY)
    except Exception:
        return None
    return None


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

    COMPARED AS STRINGS, which is `latest_by_subject`'s rule at the other end of
    the same list and correct for the same reason: every row is stamped by `_now`
    in one fixed UTC spelling, so lexical order IS chronological order and parsing
    would add a way to fail without adding an answer.
    """
    stamps = [r.get("ts") for r in rows or []
              if isinstance(r, dict) and isinstance(r.get("ts"), str)
              and r.get("ts").strip()]
    return min(stamps) if stamps else None


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
    stamps = [s for s in (key_at, ledger_at) if s is not None]
    at = min(stamps) if stamps else None
    if key_at is not None and ledger_at is not None:
        basis = ("the plan states recording began %s and the earliest recorded "
                 "run is %s; the earlier of the two is the boundary, because "
                 "work before it could not have been recorded" % (key_at, ledger_at))
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
    else:
        basis = ("nothing says when recording began: this plan carries no %s and "
                 "no run is readable in its ledger, so no work in it could have "
                 "carried evidence" % (SINCE_KEY,))
    return {"at": at, "sources": {"key": key_at, "ledger": ledger_at},
            "basis": basis, "unknown": list(unknown or [])}


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
    read = read_rows(project, config=config)
    if read["unreadable"]:
        unknown.append("%d ledger row(s) could not be parsed, and one of them may "
                       "carry an earlier run than any that could"
                       % (read["unreadable"],))
    return boundary_of(block, earliest_recorded(read["rows"]), unknown=unknown)


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
    """
    project = (project_dir or os.environ.get("CLAUDE_PROJECT_DIR")
               or os.path.dirname(os.path.abspath(manifest_path)) or ".")
    try:
        config = dict(_journal_io.load_config(project) or {})
    except Exception:
        config = {}
    try:
        config["manifestPath"] = os.path.relpath(
            os.path.abspath(manifest_path), os.path.abspath(project))
    except Exception:
        pass
    return project, config


def boundary_for(manifest_path, project_dir=None):
    """The boundary for the plan at `manifest_path`, wherever that plan sits.

    The one line a caller above layer 2 writes to hand `rollup` a boundary. It
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


def _since_locks(phase_id):
    """Which locks a stamp must clear, in one fixed order.

    BOTH, AND THE REASON IS THE LAYOUT. `meta` lives on the INDEX, which is the
    `index` lock's subject -- that one is the write's own guard. The phase lock is
    here because in the SINGLE-FILE layout the index and the phase body are the
    same bytes: `write_pointer` takes `phase-<id>` and rewrites the whole
    document, so a stamp that ignored it would be the second writer of one file.
    In the sharded layout that second check can only ever cost a refusal, and a
    refusal costs nothing here while a lost update costs somebody's pointer --
    which is `_locks`'s own bias, one caller over.
    """
    names = [("index", "index")]
    if phase_id is not None:
        names.append(("phase-%s" % (phase_id,), "phase"))
    return names


def write_evidence_since(project, manifest_path, phase_id=None, session_id=None,
                         config=None):
    """Stamp `meta.evidenceSince` the first time this plan records a run.

    `{"written", "reason", "at", "path"}`, plus `releaseRefused` -- the sentences
    for any lock that declined to be given back, which says another session took
    it over while this stamp was being written. It is present on the refusing
    paths too, because a run that was displaced was displaced whether or not its
    own write went in.

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
    derived = since_from_rows(read_rows(project, config=config)["rows"])
    if derived is None:
        # THE BASIS IS THE THING THAT IS MISSING, so this is what gets said. A
        # stamp taken from the wall clock here would date the boundary from the
        # moment somebody happened to run the gate, and every task finished after
        # that moment and before this one would be excused by a claim with
        # nothing behind it.
        return _refused("no recorded run to date the boundary from")
    # `took` DECIDES WHAT GOES ON THIS LIST, not `held`. The two came apart when
    # `acquire` learnt to answer a caller that already holds what it asked for:
    # that answer is held, and a name added here on it would be given back at the
    # end -- out from under the hold that is still using it. `lock_state` usually
    # says `ours` before it gets that far, and usually is not a rule.
    taken, refusal = [], None
    for name, label in _since_locks(phase_id):
        state, detail = lock_state(project, name, label, session_id=session_id,
                                   hint=SINCE_HINT)
        if state in ("held", "stale"):
            refusal = detail
            break
        if state == "free":
            code = _locks.acquire(project, name,
                                  note="stamping the evidence boundary",
                                  session=session_id, out=lambda *_a: None)
            if not _locks.held(code):
                refusal = "the %s lock could not be taken; %s" % (label, SINCE_HINT)
                break
            if _locks.took(code):
                taken.append(name)
    # ONE CALL INSIDE THE `finally`, so there is ONE answer to decorate. The
    # release has to happen even when the write raises, and a declined release is
    # news the caller has to see on the refusing paths too -- and those used to
    # return from INSIDE the block, past the release, with nothing left to attach
    # a sentence to.
    try:
        answer = _stamp_since(project, manifest_path, body, meta, derived, refusal)
    finally:
        # A DECLINED RELEASE IS THE ONLY NEWS OF A TAKEOVER THIS RUN GETS, and it
        # used to go into a printer that discards beside a code nothing read.
        declined = _give_back(project, taken, session_id)
    if declined:
        answer["releaseRefused"] = declined
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


def _stamp_since(project, manifest_path, body, meta, derived, refusal):
    """Put the boundary in the document -> the answer `write_evidence_since` gives.

    Its own function so the release around it has ONE value to decorate, and so
    the release runs whatever this does. The stamp itself is the whole body: a
    refusal decided before the locks were taken is carried in rather than
    recomputed, because that decision has already been made and made once.
    """
    if refusal is not None:
        return _refused(refusal)
    meta[SINCE_KEY] = derived
    try:
        _mio.atomic_write_json(manifest_path, body)
    except Exception as exc:
        return _refused("cannot write %s: %s"
                        % (repo_relative_or_token(project, manifest_path), exc))
    return {"written": True, "reason": None, "at": derived["at"],
            "path": manifest_path}


def _give_back(project, names, session_id):
    """Release each of `names` -> the sentences for the ones the lock DECLINED.

    A LIST BECAUSE THE STAMP TAKES MORE THAN ONE LOCK, and a run displaced on one
    of them was displaced: collapsing two refusals into a first-one-wins string
    would drop the half the reader has no other way to learn. Empty is the normal
    answer and is what the caller reads as "nothing to say".
    """
    said = []
    for name in names:
        code = _locks.release(project, name, session=session_id,
                              out=lambda *_a: None)
        if code != 0:
            said.append(_locks.release_refusal(code, name))
    return said


def new_run_id():
    """A fresh, opaque run id: a stamp plus randomness.

    THE STAMP IS A CONVENIENCE FOR A HUMAN READING THE RAW FILE AND NOTHING MORE.
    The id is documented as OPAQUE and the schema says so, because the moment a
    reader parses it the format becomes an interface nobody agreed to - which is
    why `at` is a field of its own rather than something a consumer slices out of
    here.
    """
    return "%s.%s" % (_now(), binascii.hexlify(os.urandom(3)).decode("ascii"))


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answered rather than falling through to the library notice below: CI
        # runs `--selftest` over every file here. It deliberately does NOT print
        # the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_evidence_io.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__evidence_io.py - run that file instead.")
        raise SystemExit(0)
    print("This is a library module; run with --selftest to exercise it.")
