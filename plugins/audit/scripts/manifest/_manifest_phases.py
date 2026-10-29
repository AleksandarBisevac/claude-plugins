#!/usr/bin/env python3
"""
The one walk over every phase and every task, and the checks it makes on the way.

Split out of `_manifest_rules.py`. This is the half of that file's
`# --- validate: one walk ---` seam that PRODUCES the index rather than reading
it: `_walk_phases` visits each phase and each task once, checks the per-object
rules a phase carries (its parallel-run claim, its area tag, its budget, its
sign-off consistency) and returns five named accumulators the checks in
`_manifest_crossrefs` then read.

THE WALK STAYS ONE PASS ON PURPOSE, and that is the whole reason the index is a
return value rather than five separate walks: splitting it per-question would
visit every task four times and would let two of them disagree about which
objects were skipped as malformed.

`_check_claim`, `_check_area_tag` and `_check_areas` live here because the walk
is their only caller and a phase is their only subject. `_check_areas` is the
odd one - it is called by `validate()` directly rather than from inside the
loop, because two of its three questions are about the REGISTRY (`meta.areas`)
rather than about any one phase.

The `tests_add_*` group lives here for a DIFFERENT reason, and it is what a
caller outside validation reads: `audit-task.py` asks `tests_add_path` which
path a `tests.add` entry puts into a task's `files`, the walk asks it to
require one of a `tdd` task that can still be committed against (the
files-union rule below, beside the red-first-naming rule about the same
field), and `repair-tests-add.py` asks
`tests_add_repair` what a one-shot migration may do to an entry written before
that rule existed. They are here because those rules are what a reader has to
compare - the first draft put the walk's one in `_manifest_rules` with a walk
of its own, which was a third pass over the tasks and a second copy of
`mode == "tdd" and status not in TERMINAL` that had already drifted from
the red-first-naming rule's own copy on `expectRedFirst`. That filter is now
`tests_add_graded`, so the walk
and the migration cannot disagree about which entries the rule reaches.
`_manifest_rules` re-exports the group, so no call site knows where it sits.

This module carries no `--selftest` of its own; its cases live in
`tests/test__manifest_phases.py` - see
`tests/_harness.py`.
"""
import json
import os
import re
import shlex
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

import _manifest_io as _mio  # noqa: E402  (TERMINAL: what 'finished' means everywhere)
import _areas  # noqa: E402  (meta.areas registry + the resolution every surface shares)
import _manifest_vocab as _vocab  # noqa: E402  (the words, and the shared shape checks)
import _task_outputs as _touts  # noqa: E402  (what an `outputs` pattern may be -- the one
#                                              rule the writer, this walk and the plan gate
#                                              all read)
import _ado_parent as _parent  # noqa: E402  (what an `adoParent` declaration may say)
import _ado_tracked as _tracked  # noqa: E402  (and what an `adoTracked` one may say)

# Thin module-level aliases, not copies: the bodies below were moved out of
# `_manifest_rules.py` unchanged, and an alias keeps them reading the same names
# while there is still exactly one definition of each. A case pins the identity.
CLAIM_KEYS = _vocab.CLAIM_KEYS
KNOWN_PHASE = _vocab.KNOWN_PHASE
KNOWN_TASK = _vocab.KNOWN_TASK
RISK = _vocab.RISK
STATUS = _vocab.STATUS
TESTS_MODE = _vocab.TESTS_MODE
TERMINAL = _mio.TERMINAL
_check_ado = _vocab._check_ado
_require_fields = _vocab._require_fields
_safe_list = _vocab._safe_list
_unknown_keys = _vocab._unknown_keys


# --- what a phase carries --------------------------------------------------------
def _check_claim(phase, pwhere, findings, warnings):
    """Validate an optional parallel-run `claim` on a phase (v0.15 sharded layout).

    A claim records which session/branch is running a phase so concurrent work
    across machines is coordinated (and a same-phase double-claim shows up as a shard
    merge conflict). Shape errors are findings; a claim missing recommended keys, or one
    left on a finished phase (stale — should be released), is a warning."""
    if "claim" not in phase:
        return
    claim = phase.get("claim")
    if claim is None:
        return
    if not isinstance(claim, dict):
        findings.append(_output.finding("phases.claim.claim-object-sessionid", "%s: claim must be an object {sessionId, branch, at}, got %s"
                        % (pwhere, type(claim).__name__)))
        return
    missing = [k for k in CLAIM_KEYS if not claim.get(k)]
    if missing:
        warnings.append("%s: claim is missing %s — a claim should identify the "
                        "session/branch holding the phase" % (pwhere, ", ".join(missing)))
    if phase.get("status") in ("done", "cancelled", "blocked"):
        warnings.append("%s: has a claim but status is %r — a finished/blocked phase should "
                        "release its claim (stale claim)" % (pwhere, phase.get("status")))


# --- what a review recorded -------------------------------------------------------
# THE FINDING'S SHAPE, AND THE WORDS ITS SEVERITY MAY TAKE. Both are written down
# here because until they were, nobody wrote them down in a place anything read: the
# reviewer agent's return format states one shape, the orchestrator's sign-off step
# asks for a record of it, and the schema declared five optional properties with no
# rule attached. So every phase recorded findings in whatever shape that run's
# reviewer happened to return -- most of them plain strings -- and a finding that
# names no file and no resolution is one no later run, report or panel can act on.
#
# The vocabulary is the one the reviewer is already asked for, rather than a new one:
# a validator that invented a fourth word would be grading returns against something
# no agent was ever told.
FINDING_FIELDS = ("id", "severity", "file", "issue", "resolution")
FINDING_SEVERITY = ("low", "med", "high")
# Both lists the review block holds findings in. The second is not read by the
# orchestrator, but it is the SAME record shape and a reader that could parse one
# and not the other would be two readers.
REVIEW_FINDING_LISTS = ("findings", "preExistingNotCharged")


def _check_review(phase, pwhere, warnings):
    """A phase's recorded review findings, held to the shape the schema names.

    WARNINGS, NEVER FINDINGS, and that is the rule rather than a soft start. Every
    plan written before this shape carries free-text findings, and a validator that
    refused them would be refusing documents the product itself wrote -- which is
    how a validator stops being run at all. The manifest stays valid; the line says
    what cannot be read back.

    ONE WARNING PER PROBLEM PER PHASE, not one per finding. The bodies are then
    byte-identical across phases, so `_warning_groups.collapse` folds a whole plan's
    worth into one line; a per-item rule that cannot fold is exactly what buries the
    warning standing next to it.
    """
    review = phase.get("review")
    if not isinstance(review, dict):
        return
    for key in REVIEW_FINDING_LISTS:
        entries = review.get(key)
        if not isinstance(entries, list):
            continue
        shapeless = False
        missing = set()
        outside = set()
        for entry in entries:
            if not isinstance(entry, dict):
                shapeless = True
                continue
            for field in FINDING_FIELDS:
                value = entry.get(field)
                if value is None or (isinstance(value, str) and not value.strip()):
                    missing.add(field)
            sev = entry.get("severity")
            if isinstance(sev, str) and sev.strip() and sev not in FINDING_SEVERITY:
                outside.add(sev)
        if shapeless:
            warnings.append(
                "%s: review.%s holds an entry that is not a finding object - a "
                "plain string records no file, no severity and no resolution, so "
                "nothing downstream can turn it into a fix task. The shape is "
                "{%s}" % (pwhere, key, ", ".join(FINDING_FIELDS)))
        if missing:
            warnings.append(
                "%s: a review.%s finding is missing %s - the shape is {%s}, and a "
                "finding missing one of them cannot be read back"
                % (pwhere, key, ", ".join(sorted(missing)),
                   ", ".join(FINDING_FIELDS)))
        if outside:
            warnings.append(
                "%s: a review.%s finding carries severity %s - the vocabulary is "
                "%s, which is what the reviewer is asked to return"
                % (pwhere, key, ", ".join(repr(s) for s in sorted(outside)),
                   ", ".join(FINDING_SEVERITY)))


# A `testGate` / `tests.gate` value as the entries that will actually run - the
# one normalisation every reader of a gate uses, so the validator's "is this task's
# gate its phase's gate verbatim" is asked of exactly what the runner would run.
_gate_entries = _mio.declared_gate_entries


def _comma_joined_gate(entries, build_keys, where, field):
    """Warnings for gate entries that are several `buildCommands` keys joined
    by commas into one string.

    The runner resolves an entry through `meta.buildCommands` WHOLE, so
    `"lint,test"` is not two keys - it is one shell command, which no shell
    can find. Named only when the entry is not itself a key and EVERY part of
    it is one: a literal command may carry a comma (`eslint a.ts,b.ts`), and
    an entry only part of which names a key is not this spelling.
    """
    out = []
    for entry in entries:
        if entry in build_keys or "," not in entry:
            continue
        parts = [p.strip() for p in entry.split(",")]
        if all(p and p in build_keys for p in parts):
            out.append(_output.finding(
                "phases.comma_joined_gate.joined-keys",
                "%s: %s entry %r is %d buildCommands keys joined by commas "
                "into ONE entry, which runs as one shell command no shell can "
                "find - split it: %s"
                % (where, field, entry, len(parts), json.dumps(parts))))
    return out


def _signoff_only_gate(entries, build_keys, where, field):
    """Warnings for gate entries that name a key the sign-off runs.

    Such a key (`_manifest_vocab.SIGNOFF_ONLY_GATES`) is run once, by the
    sign-off, over the files the phase changed; named in a gate it would run as
    an ordinary step on every gate it appears in, and the lint probe mutates
    the tree to prove a guard red. Only a name that IS a `buildCommands` key is
    read, as `_comma_joined_gate` reads one: a literal command is a command.
    """
    return [_output.finding(
        "phases.signoff_only_gate.in-gate",
        "%s: %s entry %r runs at sign-off and not as a gate step - the "
        "sign-off runs it once over what the phase changed, and as a gate "
        "entry it would run on every gate that names it. Drop it from the "
        "gate; to keep it out of a new phase's default, nothing is needed"
        % (where, field, entry))
        for entry in entries
        if entry in build_keys and _vocab.signoff_only_entry(entry)]


# --- what a NEW phase's gate defaults to -------------------------------------------
def _phase_gate_lists(meta):
    """`(always, exclude, build_keys)` - the validated pieces `phase_gate_default`
    and `_check_phase_gate` both read, asked ONCE so the two cannot disagree
    about what counts as a non-blank string.
    """
    meta = meta if isinstance(meta, dict) else {}
    build = meta.get("buildCommands")
    build_keys = ([k for k in build.keys() if isinstance(k, str) and k.strip()]
                  if isinstance(build, dict) else [])
    gate = meta.get("phaseGate")
    gate = gate if isinstance(gate, dict) else {}
    always = [a for a in _safe_list(gate.get("always"))
              if isinstance(a, str) and a.strip()]
    exclude = [e for e in _safe_list(gate.get("exclude"))
               if isinstance(e, str) and e.strip()]
    return always, exclude, build_keys


# The review-only rule lives in `_manifest_vocab`, below this module and below
# `_evidence_io`, which needs it too and is this module's layer-mate. These are
# the SAME objects, re-exported for the callers that already read them here.
REVIEW_ONLY_PREFIX = _vocab.REVIEW_ONLY_PREFIX
REVIEW_ONLY_KEYS = _vocab.REVIEW_ONLY_GATES
is_review_only = _vocab.is_review_only
review_only_keys = _vocab.review_only_keys
review_only_entry = _vocab.review_only_entry
# ...and so is the sign-off-only rule, asked in the same two places for the same
# reason: a key the sign-off runs is no more a gate step than a read is.
LINT_PROBE_KEY = _vocab.LINT_PROBE_KEY
SIGNOFF_ONLY_KEYS = _vocab.SIGNOFF_ONLY_GATES
signoff_only_entry = _vocab.signoff_only_entry
signoff_only_keys = _vocab.signoff_only_keys


def phase_gate_default(meta):
    """`{entries, always, rest, excluded, basis}` - what a NEW phase's gate
    starts as, read by `/audit:phase add` now and by a future task-level
    derivation alike - the ONE answer, so neither can quietly disagree with
    the other about what "today's default" means.

    `entries` = `always` in declared order, then every OTHER `buildCommands`
    key in buildCommands order, minus `exclude`. `always` COMES FIRST because
    that is the one thing a caller declared outright; `rest` preserves
    buildCommands order rather than sorting it, because a plan's own ordering
    is the only one this project has ever produced and there is no reason to
    prefer another.

    ALWAYS IS ALWAYS. An entry named in both lists is not dropped: `exclude`
    is the declared way to keep a key OUT, and `always` is a stronger,
    later-read declaration that puts a key back IN - so an author who lists
    the same key in both gets the key, not the absence of one. `_check_phase_gate`
    is what warns about the overlap; this function only resolves it.

    ABSENT MEANS TODAY'S BEHAVIOUR EXACTLY: with no `phaseGate` at all, `always`
    and `exclude` are both empty, so `entries` is every `buildCommands` key, in
    buildCommands order, byte-identical to what `/audit:phase add` wrote before
    this field existed - EXCEPT the keys that are not gate steps at all: a
    review-only key (`reviewOnly`) and a sign-off-only one (`signoffOnly`), each
    returned by name, and the latter named in `basis`.
    """
    always, exclude, build_keys = _phase_gate_lists(meta)
    # A READ IS NOT A COMMAND, so it is skipped HERE - the one derivation every
    # consumer asks - and returned by name so a caller can say it did.
    # ...AND SO IS A SIGN-OFF STEP, which the sign-off runs once and an ordinary
    # gate must never run: `always` cannot put it back, for the same reason.
    build = (meta or {}).get("buildCommands")
    review_only = review_only_keys(build)
    signoff_only = signoff_only_keys(build)
    not_gate = set(review_only) | set(signoff_only)
    always = [a for a in always if a not in not_gate]
    build_keys = [k for k in build_keys if k not in not_gate]
    always_set = set(always)
    exclude_set = set(exclude) - always_set
    rest = [k for k in build_keys
            if k not in always_set and k not in exclude_set]
    excluded = [k for k in build_keys if k in exclude_set]
    entries = list(always) + rest
    if not build_keys:
        basis = "no meta.buildCommands key exists to default a gate from"
    elif not always and not exclude:
        basis = ("no meta.phaseGate: default is every buildCommands key, in "
                 "buildCommands order")
    elif not excluded:
        basis = ("meta.phaseGate.always puts %d key(s) first (%s); every "
                 "other buildCommands key follows in buildCommands order"
                 % (len(always), _output.some_of(always, render=repr))
                 if always else
                 "meta.phaseGate.exclude names no key meta.buildCommands "
                 "actually declares, so the default is unchanged")
    else:
        basis = ("meta.phaseGate.exclude drops %d buildCommands key(s) (%s)%s"
                 % (len(excluded), _output.some_of(excluded, render=repr),
                    " after meta.phaseGate.always puts %d first (%s)"
                    % (len(always), _output.some_of(always, render=repr))
                    if always else ""))
    if signoff_only:
        basis += ("; %s left out - the sign-off runs %s, a gate step never "
                  "does" % (_output.some_of(signoff_only, render=repr),
                            "it" if len(signoff_only) == 1 else "them"))
    return {"entries": entries, "always": always, "rest": rest,
            "excluded": excluded, "basis": basis, "reviewOnly": review_only,
            "signoffOnly": signoff_only}


def phase_gate_suite_gap(manifest, suite_keys=None):
    """The 'phase gate runs no suite' warning, or None when the gate still runs one.

    EVALUATED ONLY WHEN `exclude` IS NON-EMPTY - without it the default is
    today's set, and today's set has always been trusted to run something.

    TWO ARMS, and only the first needs no evidence. A default EMPTY after
    exclusion (`exclude` removed every `buildCommands` key and `always` added
    none) is CERTAIN: there is no key left to have run, whatever the ledger
    says, so this arm fires from the plan alone. The second arm needs
    `suite_keys` - `{running, silent, unknown}`, computed from the evidence
    ledger by the counts reader (`run-test-gate.summary_reader`, recorded per
    step as `suiteReader`) - because a wide key like `npm test` is not
    test-shaped by its spelling and this function must not guess one from the
    other: with no default key recorded as `running`, it names the keys left
    after `exclude` as not established rather than as certainly silent.
    `suite_keys=None` (the pure validator's call, with no evidence in hand)
    answers only the certain arm.
    """
    meta = manifest.get("meta") if isinstance(manifest, dict) else None
    meta = meta if isinstance(meta, dict) else {}
    _always, exclude, _build_keys = _phase_gate_lists(meta)
    if not exclude:
        return None
    default = phase_gate_default(meta)
    if not default["entries"]:
        return ("phase gate runs no suite: meta.phaseGate.exclude removes "
                "every meta.buildCommands key and meta.phaseGate.always adds "
                "none")
    if suite_keys is None:
        return None
    running = set((suite_keys or {}).get("running") or [])
    if any(k in running for k in default["entries"]):
        return None
    return ("phase gate runs no suite as far as the ledger shows: %s are "
            "left after meta.phaseGate.exclude"
            % (_output.some_of(default["entries"]),))


# The two words `meta.phaseGate.mode` may hold. ABSENT MEANS NO DERIVATION -
# `always`/`exclude` alone still shape the wide gate, and nothing narrower is
# ever computed - so this tuple is read only when the key is PRESENT.
PHASE_GATE_MODES = ("shadow", "enforce")


def _check_phase_gate_derived(derived, build_keys):
    """WARNINGS for `meta.phaseGate.derived` - shape only, no ledger, no running.

    `derived` is None (absent or explicit null) whenever `meta.phaseGate.mode`
    applies to nothing yet - a project that turned shadow mode on before
    telling the derivation how its own runner takes paths. That is not a shape
    problem, so it draws nothing here.

    `listing` is what derive-phase-gate.py actually runs to list suites
    without executing them: `related` takes a `{paths}` placeholder it fills
    per phase, so a `related` without one would list the same thing for every
    phase; `all` runs with NO path filter and `_gather_facts` never
    substitutes into it, so a `{paths}` token left in `all` reaches the shell
    literally and the command fails silently at gate time rather than
    listing anything. Each of `related` and `all` splits its shape violation
    (blank or non-string) from its value violation (a placeholder missing
    where one is owed, or present where none is ever filled in) into its own
    CODE, the way `budgetusd-number` and `budgetusd-greater-than` split type
    from value below - a listing command is only ever produced by the
    derivation itself, so a bad value here means the manifest was edited by
    hand. A null or absent `listing`, or one where both fields are
    well-formed, stays silent.
    """
    if derived is None:
        return []
    if not isinstance(derived, dict):
        return [_output.finding(
            "phases.phase_gate_derived.object",
            "meta.phaseGate.derived: must be an object or null, got %s"
            % (type(derived).__name__,))]
    out = []
    runner = derived.get("runner")
    if runner is not None:
        if not (isinstance(runner, str) and runner.strip()):
            out.append(_output.finding(
                "phases.phase_gate_derived.runner-shape",
                "meta.phaseGate.derived.runner: must be a non-blank "
                "buildCommands key, got %s" % (type(runner).__name__,)))
        elif build_keys and runner not in build_keys:
            out.append(_output.finding(
                "phases.phase_gate_derived.runner-unknown-key",
                "meta.phaseGate.derived.runner: %r is not a buildCommands "
                "key - meta.buildCommands declares %s"
                % (runner, _output.some_of(sorted(build_keys)))))
    spelling = derived.get("spelling")
    if spelling is not None:
        if not (isinstance(spelling, str) and spelling.strip()):
            out.append(_output.finding(
                "phases.phase_gate_derived.spelling-shape",
                "meta.phaseGate.derived.spelling: must be a non-blank "
                "string, got %s" % (type(spelling).__name__,)))
        elif "{paths}" not in spelling:
            out.append(_output.finding(
                "phases.phase_gate_derived.spelling-placeholder",
                "meta.phaseGate.derived.spelling: %r carries no {paths} "
                "placeholder - the derivation has nowhere to substitute a "
                "resolved path list into it" % (spelling,)))
    listing = derived.get("listing")
    if listing is not None and not isinstance(listing, dict):
        out.append(_output.finding(
            "phases.phase_gate_derived.listing-object",
            "meta.phaseGate.derived.listing: must be an object or null, "
            "got %s" % (type(listing).__name__,)))
        listing = None
    if isinstance(listing, dict):
        # `e2eChanged` is the e2e runner's own changed-spec listing, read by
        # `_affected_tests` per task; it takes `{paths}` exactly as `related`.
        for key, code in (("related", "related"), ("e2eChanged", "e2e-changed")):
            related = listing.get(key)
            if related is None:
                continue
            if not (isinstance(related, str) and related.strip()):
                out.append(_output.finding(
                    "phases.phase_gate_derived.listing-%s-shape" % (code,),
                    "meta.phaseGate.derived.listing.%s: must be a "
                    "non-blank string, got %s - write a command that lists "
                    "the suites related to a path set"
                    % (key, type(related).__name__)))
            elif "{paths}" not in related:
                out.append(_output.finding(
                    "phases.phase_gate_derived.listing-%s-placeholder" % (code,),
                    "meta.phaseGate.derived.listing.%s: %r carries no "
                    "{paths} placeholder - it is filled in per phase and per "
                    "task, so every one would list the same suites "
                    "without it; add {paths} to the command" % (key, related)))
        all_cmd = listing.get("all")
        if all_cmd is not None:
            if not (isinstance(all_cmd, str) and all_cmd.strip()):
                out.append(_output.finding(
                    "phases.phase_gate_derived.listing-all-shape",
                    "meta.phaseGate.derived.listing.all: must be a "
                    "non-blank string, got %s - write a command that lists "
                    "every suite this runner would collect, with no path "
                    "filter" % (type(all_cmd).__name__,)))
            elif "{paths}" in all_cmd:
                out.append(_output.finding(
                    "phases.phase_gate_derived.listing-all-paths-present",
                    "meta.phaseGate.derived.listing.all: %r carries a "
                    "{paths} placeholder - derive-phase-gate.py runs `all` "
                    "with no path filter and never substitutes into it, so "
                    "the literal token reaches the shell and the command "
                    "fails silently at gate time; write `all` to list every "
                    "suite directly, with no {paths} token" % (all_cmd,)))
    verified_on = derived.get("verifiedOn")
    if listing is not None and not (isinstance(verified_on, dict)
                                    and verified_on.get("command")):
        out.append(_output.finding(
            "phases.phase_gate_derived.listing-unverified",
            "meta.phaseGate.derived: a `listing` command is declared with no "
            "`verifiedOn` - its version was never checked, so a later "
            "mismatch has no real answer to compare against, only a guess"))
    return out


_COUPLING_OBJECT_ID = re.compile(r"^[0-9a-fA-F]{7,40}$")

# `phase.mergedHead` is a FULL sha only, unlike `_COUPLING_OBJECT_ID` above:
# ancestry (`git merge-base --is-ancestor`) is what this field is read for, and
# a short sha is ambiguous input to that check in a way a coupling pointer
# (read by a human, never diffed against another commit) is not.
_FULL_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def _check_coupling(coupling, phase_ids):
    """WARNINGS for `meta.coupling` - shape only, additive.

    Every entry needs `test`, a non-empty `sources` and `basis.runId` - a
    pointer with no runId points at nothing, the same reason `testEvidence`
    requires one. Two entries naming the same `test` are named together
    rather than one silently shadowing the other: a reader (and a future
    derivation) has no rule for which of two conflicting source lists wins.

    `basis.head` (an object-id shape) and `basis.phases` (every entry a
    phase id `phase_ids` actually holds) are graded here too - `couple`
    itself asks git and the plan before it ever writes either field, so a
    bad value reaching this walk means the manifest was edited by hand.

    Every line is CODED, as the rest of `_check_phase_gate`'s family is: a
    stable code is what lets a caller keep filtering for one rule even
    though the check stays additive.
    """
    if not isinstance(coupling, list):
        return [_output.finding(
            "phases.coupling.array",
            "meta.coupling: must be an array, got %s"
            % (type(coupling).__name__,))]
    out = []
    seen, dup = set(), set()
    for i, entry in enumerate(coupling):
        where = "meta.coupling[%d]" % (i,)
        if not isinstance(entry, dict):
            out.append(_output.finding(
                "phases.coupling.entry-object",
                "%s: must be an object, got %s"
                % (where, type(entry).__name__)))
            continue
        missing = []
        test = entry.get("test")
        if not (isinstance(test, str) and test.strip()):
            missing.append("test")
        sources = entry.get("sources")
        if not (isinstance(sources, list) and sources):
            missing.append("sources")
        basis = entry.get("basis")
        run_id = basis.get("runId") if isinstance(basis, dict) else None
        if not (isinstance(run_id, str) and run_id.strip()):
            missing.append("basis.runId")
        if missing:
            out.append(_output.finding(
                "phases.coupling.missing",
                "%s: missing %s" % (where, _output.some_of(missing))))
        if isinstance(basis, dict):
            head = basis.get("head")
            if head is not None and not (isinstance(head, str)
                                         and _COUPLING_OBJECT_ID.match(head)):
                out.append(_output.finding(
                    "phases.coupling.head-shape",
                    "%s: basis.head %r does not read as an object id (7-40 "
                    "hex characters)" % (where, head)))
            phases = basis.get("phases")
            if isinstance(phases, list):
                bad = [p for p in phases if p not in phase_ids]
                if bad:
                    out.append(_output.finding(
                        "phases.coupling.phase-id",
                        "%s: basis.phases names %s that %s not a phase id "
                        "in this plan"
                        % (where, _output.some_of(bad, render=repr),
                           "is" if len(bad) == 1 else "are")))
        if isinstance(test, str) and test.strip():
            if test in seen:
                dup.add(test)
            seen.add(test)
    if dup:
        out.append(_output.finding(
            "phases.coupling.duplicate-test",
            "meta.coupling: duplicate `test` value(s) %s - each test should "
            "carry ONE entry with every source it is coupled to, not two "
            "entries a reader has no rule for choosing between"
            % (_output.some_of(sorted(dup), render=repr),)))
    return out


def _check_phase_gate(manifest):
    """WARNINGS for `meta.phaseGate`, `meta.gateBudgetMs` and `meta.coupling` -
    additive, never a finding (`COMPATIBILITY.md` -> Validation stays
    additive): all three are new, so a shape a validator does not like is
    named rather than refused.

    RETURNED, NOT WRITTEN INTO THE CALLER'S LIST, and every line built through
    `_output.finding` so it carries a stable code. The list is named `findings`
    because that is the name the stable-code walk in the suites follows, and
    the helpers extended into it are walked as its feeders; a check that wrote
    into a `warnings` parameter was outside that walk entirely, so its codes
    were held by convention alone. The caller files the list as warnings.

    THE 'RUNS NO SUITE' SENTENCE IS NOT HERE. `phase_gate_suite_gap` is asked
    directly by `_manifest_rules._check_meta`, with no evidence, so the pure
    validator emits its certain arm only - this function is the SHAPE checks
    that do not need the ledger at all.
    """
    findings = []
    meta = manifest.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    if "phaseGate" in meta:
        gate = meta.get("phaseGate")
        if gate is not None and not isinstance(gate, dict):
            findings.append(_output.finding(
                "phases.phase_gate.object",
                "meta.phaseGate: must be an object with `always` and/or "
                "`exclude`, got %s" % (type(gate).__name__,)))
        elif isinstance(gate, dict):
            for field in ("always", "exclude"):
                raw = gate.get(field)
                if raw is None:
                    continue
                if not isinstance(raw, list):
                    findings.append(_output.finding(
                        "phases.phase_gate.list-array",
                        "meta.phaseGate.%s: must be an array of "
                        "buildCommands keys, got %s"
                        % (field, type(raw).__name__)))
                    continue
                bad = [e for e in raw if not (isinstance(e, str) and e.strip())]
                if bad:
                    findings.append(_output.finding(
                        "phases.phase_gate.list-blank-entry",
                        "meta.phaseGate.%s: every entry must be a non-blank "
                        "string (%d bad: %s)"
                        % (field, len(bad), _output.some_of(bad, render=repr))))
            always, exclude, build_keys = _phase_gate_lists(meta)
            if build_keys:
                for field, entries in (("always", always), ("exclude", exclude)):
                    findings.extend(_comma_joined_gate(
                        entries, build_keys, "meta.phaseGate", field))
                    unknown = [e for e in entries if e not in build_keys]
                    if unknown:
                        findings.append(_output.finding(
                            "phases.phase_gate.unknown-key",
                            "meta.phaseGate.%s names %s, which %s not a "
                            "buildCommands key - meta.buildCommands declares "
                            "%s" % (field, _output.some_of(unknown, render=repr),
                                    "is" if len(unknown) == 1 else "are",
                                    _output.some_of(sorted(build_keys)))))
            both = sorted(set(always) & set(exclude))
            if both:
                findings.append(_output.finding(
                    "phases.phase_gate.always-and-exclude",
                    "meta.phaseGate: %s in both `always` and `exclude` - "
                    "always is always, so %s stays in the default gate"
                    % (_output.some_of(both, render=repr),
                       "it" if len(both) == 1 else "they")))
            # `exclude` naming one is the harmless spelling (the default skips
            # it already), so only `always` - the list that would put it in - is read.
            findings.extend(_signoff_only_gate(
                always, build_keys, "meta.phaseGate", "always"))
            if "mode" in gate:
                mode = gate.get("mode")
                if mode not in PHASE_GATE_MODES:
                    findings.append(_output.finding(
                        "phases.phase_gate.mode",
                        "meta.phaseGate.mode: must be 'shadow' or 'enforce', "
                        "got %r" % (mode,)))
            if "derived" in gate:
                findings.extend(_check_phase_gate_derived(
                    gate.get("derived"), build_keys))
            if "smoke" in gate:
                smoke = gate.get("smoke")
                if smoke is not None:
                    if not (isinstance(smoke, str) and smoke.strip()):
                        findings.append(_output.finding(
                            "phases.phase_gate.smoke-shape",
                            "meta.phaseGate.smoke: must be a non-blank "
                            "buildCommands key or null, got %s"
                            % (type(smoke).__name__,)))
                    elif build_keys and smoke not in build_keys:
                        findings.append(_output.finding(
                            "phases.phase_gate.smoke-unknown-key",
                            "meta.phaseGate.smoke: %r is not a buildCommands "
                            "key - meta.buildCommands declares %s"
                            % (smoke, _output.some_of(sorted(build_keys)))))
    if "gateBudgetMs" in meta:
        budget = meta.get("gateBudgetMs")
        if isinstance(budget, bool) or not isinstance(budget, int):
            findings.append(_output.finding(
                "phases.phase_gate.budget-integer",
                "meta.gateBudgetMs: must be a positive integer, got %s"
                % (type(budget).__name__,)))
        elif budget <= 0:
            findings.append(_output.finding(
                "phases.phase_gate.budget-greater-than",
                "meta.gateBudgetMs: must be greater than 0 (got %s) - omit the "
                "key entirely for 'no budget'" % (budget,)))
    if "coupling" in meta:
        phase_ids = set(p.get("id") for p in (manifest.get("phases") or [])
                        if isinstance(p, dict))
        findings.extend(_check_coupling(meta.get("coupling"), phase_ids))
    return findings


def _check_full_gate(manifest, warnings):
    """WARNINGS for `meta.fullGate` - the buildCommands keys naming the THIRD
    place tests can pass at (full suite, coverage, e2e), beyond a task's own
    gate and a phase's sign-off gate.

    ADDITIVE, NEVER A FINDING (`COMPATIBILITY.md` -> Validation stays
    additive), the same standing `meta.phaseGate.always`/`exclude` have: an
    entry naming no real `meta.buildCommands` key is named rather than
    refused, and an entry that is several such keys joined by commas into
    ONE string is the exact `_comma_joined_gate` shape `phaseGate` already
    warns about - reused here rather than re-derived, so the two definitions
    of "this runs as one shell command no shell can find" cannot drift apart.
    """
    meta = manifest.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    if "fullGate" not in meta:
        return
    full_gate = meta.get("fullGate")
    if not isinstance(full_gate, list):
        warnings.append("meta.fullGate: must be an array of buildCommands "
                        "keys, got %s" % (type(full_gate).__name__,))
        return
    bad = [e for e in full_gate if not (isinstance(e, str) and e.strip())]
    if bad:
        warnings.append("meta.fullGate: every entry must be a non-blank "
                        "string (%d bad: %s)"
                        % (len(bad), _output.some_of(bad, render=repr)))
    _, _, build_keys = _phase_gate_lists(meta)
    if not build_keys:
        return
    entries = [e for e in full_gate if isinstance(e, str) and e.strip()]
    warnings.extend(_comma_joined_gate(entries, build_keys, "meta", "fullGate"))
    unknown = [e for e in entries if e not in build_keys]
    if unknown:
        warnings.append(
            "meta.fullGate names %s, which %s not a buildCommands key - "
            "meta.buildCommands declares %s"
            % (_output.some_of(unknown, render=repr),
               "is" if len(unknown) == 1 else "are",
               _output.some_of(sorted(build_keys))))


def _check_phase_intent(phase, pwhere, build_keys):
    """Warnings for a phase whose gate or outcome says less than it should.

    ADDITIVE AND NEVER A REFUSAL (`COMPATIBILITY.md` -> Validation stays
    additive). An empty gate is a designed state - sign-off then rests on
    review alone - so a phase holding one is named, not refused. A finished
    phase is history nobody can act on, so nothing fires on one.

    THE OUTCOME AND EMPTY-GATE LINES ASK OF A PHASE IN FLIGHT: running, or
    with every task finished and its sign-off still due - the moment sign-off
    reads both. A phase not yet started is not asked; a plan parks phases whose
    outcome is written when they are picked up, and naming every one of them
    is the noise that teaches a reader to skip the class.
    """
    if _mio.effective_phase_status(phase) in TERMINAL:
        return []
    out = _comma_joined_gate(_gate_entries(phase.get("testGate")), build_keys,
                             pwhere, "testGate")
    out.extend(_signoff_only_gate(_gate_entries(phase.get("testGate")),
                                  build_keys, pwhere, "testGate"))
    if not (_mio.phase_running(phase) or _mio.signoff_due(phase)):
        return out
    outcome = phase.get("desiredOutcome")
    # The bodies carry no phase id, so `_warning_groups.collapse` folds the
    # same state across phases into one line.
    if not (isinstance(outcome, str) and outcome.strip()):
        out.append("%s: in flight (running or awaiting sign-off) with no "
                   "desiredOutcome - sign-off asks whether a phase met its "
                   "outcome, and this one states none. Set it with "
                   "`/audit:phase retarget <phaseId> --outcome \"<what success "
                   "is>\"`" % (pwhere,))
    if not _gate_entries(phase.get("testGate")):
        out.append("%s: in flight (running or awaiting sign-off) with an "
                   "EMPTY testGate - a designed state, and its sign-off rests "
                   "on review alone. If a command can grade this work, "
                   "`/audit:phase retarget <phaseId> --gate <entry>`"
                   % (pwhere,))
    return out


def _check_area_tag(phase, pwhere, findings):
    """A phase's `area` must be a tag or a list of them (v0.16 shape, v0.28 meaning).

    Shape only — WHICH tags are legal is not this function's business and is not
    anybody's: free text stays legal forever. But `area: 3` and `area: {...}`
    normalise to NO tags at all, so the phase silently leaves every grouping and
    resolves against no area. Silence is the reason this is worth a finding."""
    if "area" not in phase:
        return
    area = phase.get("area")
    if area is None or isinstance(area, str):
        return
    if not isinstance(area, list):
        findings.append(_output.finding("phases.area_tag.area-tag-list", "%s: area must be a tag or a list of tags, got %s"
                        % (pwhere, type(area).__name__)))
        return
    bad = [a for a in area if not isinstance(a, str) or not a.strip()]
    if bad:
        findings.append(_output.finding("phases.area_tag.every-area-tag", "%s: every area tag must be a non-empty string (%d bad: %s)"
                        % (pwhere, len(bad),
                           _output.some_of(bad, render=repr))))


def _check_areas(manifest):
    """The `meta.areas` registry, and the phases that name it (v0.28).

    Returns (findings, warnings). It used to take both lists and write into
    them; every direct child of `validate()` returns its own pair now, so no
    caller can depend on the order two of them happen to run in, and a piece
    can be exercised from a case without being handed two lists to inspect
    afterwards.

    Three questions, and only the first can invalidate a manifest:

      * is the registry SHAPED like a registry — findings, same as any other
        wrong type in this file;
      * does every tag a phase carries have an entry — warnings, and ONLY when
        the manifest registers areas at all. A project that tags freely and
        registers nothing is using the v0.16 feature exactly as designed, and
        warning it would be this validator nagging about a feature not in use.
        A project that DOES register is one where an unregistered tag is nearly
        always a typo of a registered one — and a typo'd tag quietly resolves to
        no area, so the reviewer and the skills the author expected never happen;
      * do a phase's areas AGREE about its reviewer — a warning naming the
        winner, because written order decides and a silent tie-break is a
        reviewer nobody can explain.

    `meta.defaultSkills`, the plan-wide level that resolves above the areas, is
    shape-checked here beside the registry because `_areas` resolves both
    together; a non-list or a non-string entry is a finding, like the registry's.
    """
    findings, warnings = [], []
    meta = manifest.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    if "areas" in meta:
        f, w = _areas.validate_registry(meta.get("areas"))
        findings.extend(f)
        warnings.extend(w)
    f, w = _areas.validate_default_skills(meta)
    findings.extend(f)
    warnings.extend(w)
    for pid, tag in _areas.unregistered_tags(manifest):
        warnings.append("phase %s: area tag %r has no entry in meta.areas — it "
                        "groups and filters, but resolves to no root, no default "
                        "reviewer and no default skills (typo? free-text tags are "
                        "legal)" % (pid, tag))
    for phase in manifest.get("phases") or []:
        if not isinstance(phase, dict):
            continue
        clash = _areas.review_skill_conflicts(manifest, phase)
        if clash:
            # json.dumps, not %r: the values came out of a JSON file and go back to
            # someone editing one, and `None` is not something they can type there.
            # A null IS one of the disagreeing answers here — an area saying "tests
            # sign this off" disagrees with an area naming a reviewer.
            warnings.append(
                "phase %s: areas %s each set a different reviewSkill — written "
                "order decides, so %s (from area %s) is the one that runs"
                % (phase.get("id") or "?",
                   ", ".join("%s=%s" % (t, json.dumps(s)) for t, s in clash),
                   json.dumps(clash[0][1]), clash[0][0]))
    return (findings, warnings)


def _add_parent(obj, where, findings, warnings):
    """Fold `_ado_parent`'s shape check into the walk's two accumulators.

    A three-line adapter rather than a call at each of the two sites, because
    the walk writes into lists and `_ado_parent` returns a pair - and the day
    that mismatch is spelled out twice is the day one of the two forgets the
    warnings half. `_ado_parent` is a layer-mate of `_manifest_vocab`, so
    this module reaches it downward like any other word it borrows.
    """
    pf, pw = _parent.declaration_findings(obj, where)
    findings.extend(pf)
    warnings.extend(pw)


def _add_tracked(obj, where, findings, warnings):
    """The same adapter for `_ado_tracked`, and separate because the SCOPE differs.

    `adoParent` is declared on a phase AND on a task; `adoTracked` is a phase's
    alone, because a task inherits. Folding the two into one adapter would have
    made the task call site carry a check that must never fire there, and the way
    that goes wrong is silent: a task growing a declaration nothing reads.
    """
    tf, tw = _tracked.declaration_findings(obj, where)
    findings.extend(tf)
    warnings.extend(tw)


# --- what a `tests.add` entry NAMES ----------------------------------------------
# The schema documents `tests.add` as free prose, and `audit-task.py`'s `files`
# union treated every entry as a path on the premise that a tdd task "creates the
# file it names in `tests.add` by definition". True of the tasks that name one, false
# of the field: the scope filled up with assertions and `fileIndex` grew keys no path
# can ever match. The SHARP half was never the pollution -- the union exists so
# `_invariants.commit_scope` will allow the file the task says it will create, and
# when the entry is a sentence the thing added to `files` is not that path, so the
# permission was never granted.
#
# IT LIVES BESIDE THE WALK, and beside the red-first-naming rule about the same
# field, because
# those two are what a reader has to compare. The first draft put it in
# `_manifest_rules` with a walk of its own, which was a THIRD pass over the
# tasks and a second expression of `mode == "tdd" and status not in TERMINAL` -- and
# the two had already drifted apart on `expectRedFirst` before anybody read them
# together. `_manifest_rules` re-exports both names, so every caller and the
# downward edge from `audit-task.py` are unchanged.
_TESTS_ADD_LEAD = re.compile(r"\A\s*([^\s:]+)\s*(?::|\Z)")
# A FILENAME, not merely something with a separator in it. `_PATHISH_EXT` wants a
# dot followed by a letter-initial extension, and `_DOTFILE` covers the other real
# shape - `.gitignore` and `.gitattributes` are both live `files` entries in this
# repository's own plan and neither carries an extension.
_PATHISH_EXT = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,7}\Z")
_DOTFILE = re.compile(r"\A\.[A-Za-z][A-Za-z0-9_.-]+\Z")

# NAMED ONCE, read by two callers that must agree on which finding this is: the
# walk below, which produces it, and `repair-tests-add.py`'s pre-write guard,
# which has to tell "this is the entry I am here to fix" apart from "the plan
# was already broken by something else" without restating the sentence.
TESTS_ADD_UNNAMED_FINDING = "this tests.add entry names no file"


def tests_add_path(entry):
    """The path a `tests.add` entry NAMES, or None when it names none.

    THREE QUESTIONS, ASKED IN ORDER, and all three have to hold.

    POSITION. The documented shape is `"<path>: <what it asserts>"`, so the
    candidate is the whole entry or everything before a colon -- never a token
    pulled out of the middle of a sentence, because a path nobody typed is the
    same defect one word narrower. `require-plan selftests a4-a6: custom-path
    manifest...` fails here: its leading token is followed by a word, not a
    colon.

    SEGMENTS. Every separator-delimited piece must be non-empty, which is what
    refuses a bare `/` and a trailing-slash directory. An entry naming a
    directory names no file, which is precisely what this is asked.

    FILENAME. The LAST segment has to look like one - an extension, or a
    dotfile. This is the bound the first draft did not have, and this rule's own
    defect one shape narrower is what its absence produced: `--tests-add "n/a"`
    put `n/a` into `files` and into `fileIndex`, a key no path can ever match.
    Measured over every `files` entry in the plans this repository ships, the
    only extensionless paths are the two dotfiles, which is why that arm exists
    and why a bare `docs/audit` does not qualify.

    NONE IS AN ANSWER AND NOT A FAILURE. A caller is expected to say the entry
    named no file rather than fall back to a default.
    """
    if not isinstance(entry, str) or not entry.strip():
        return None
    found = _TESTS_ADD_LEAD.match(entry)
    if not found:
        return None
    token = found.group(1)
    segments = re.split(r"[\\/]", token)
    if not all(segments):
        return None
    leaf = segments[-1]
    if _PATHISH_EXT.search(leaf) or _DOTFILE.match(leaf):
        return token
    return None


def tests_add_graded(task):
    """Whether the `"<path>: <what it asserts>"` rule reaches this task's entries.

    ONE FILTER, TWO CALLERS. The walk below flags the entries this accepts and
    `repair-tests-add.py` offers to rewrite exactly those, so a second
    expression of it would be a migration repairing entries the validator
    never complained about, or leaving ones it did. The neighbouring rule
    about the same field was born as a second copy of this same filter and
    had drifted before anybody read the two together, which is the argument for
    naming it rather than repeating it.

    TERMINAL IS EXEMPT, which is what the migration inherits for free: a
    settled task's `tests.add` is a record of work already judged, and rewriting
    one would edit the description of a commit that has already been graded.
    """
    if not isinstance(task, dict):
        return False
    tests = task.get("tests")
    if not isinstance(tests, dict) or tests.get("mode") != "tdd":
        return False
    return task.get("status") not in TERMINAL


# --- what a one-shot repair may do to an entry -----------------------------------
# The rule above refuses, and a refusal with no migration behind it strands every
# plan written before it. So this is the other half: what can be repaired
# mechanically, and what has to be handed back.
#
# NOTHING HERE INVENTS A PATH. The only path a repair may write is one the entry
# ITSELF already spells - moving an author's own token to the front is reading the
# entry, while deriving one from the task's `files` or from a naming convention
# would be writing a path nobody typed into the field that grants commit scope. A
# sentence is visibly not a path; a wrong path is not, which is why the wrong one
# is the worse of the two to leave behind.
#
# THE MENTION BOUND IS STRICTER THAN THE LEAD BOUND, and the asymmetry is the
# whole design. The lead position is a DECLARATION, so a filename is enough there;
# a token inside a sentence is a MENTION, and ordinary prose is full of tokens that
# pass a filename test - `e.g.` is a dot followed by a letter and would read as an
# extension. Requiring a separator refuses those, and refuses `Node.js` with them.
# What it costs is a repo-root dotfile named mid-sentence, which is then handed to
# a human rather than guessed at - the direction this errs in on purpose.
_MENTION_WRAP = "`'\"()[]{}<>,.;:!?"

# The verdicts, as words rather than as a tuple position, because three of the four
# mean "leave this entry alone" for three different reasons and a caller that
# collapsed them would print one remedy for all three.
REPAIR_NAMED = "named"            # already opens with a path; nothing to do
REPAIR_REWRITE = "rewrite"        # the entry names one path; move it to the front
REPAIR_UNNAMED = "unnamed"        # nothing in it parses as a path
REPAIR_AMBIGUOUS = "ambiguous"    # it names more than one, so which is the case?


def tests_add_mentions(entry):
    """Every DISTINCT path an entry MENTIONS, in the order it mentions them.

    A token counts when it carries a separator AND would be the whole answer if
    it stood at the lead - `tests_add_path` decides the filename half, so this
    cannot disagree with the rule it is repairing about what a path looks like.
    Wrapping punctuation is stripped because prose quotes, brackets and ends
    sentences; a token carrying a line suffix (`a/b.py:12`) is NOT the whole
    answer and falls out here, left for a human rather than truncated.
    """
    if not isinstance(entry, str):
        return []
    found = []
    for token in entry.split():
        bare = token.strip(_MENTION_WRAP)
        if "/" not in bare and "\\" not in bare:
            continue
        if tests_add_path(bare) != bare:
            continue
        if bare not in found:
            found.append(bare)
    return found


def tests_add_repair(entry):
    """`(verdict, replacement)` - what a one-shot repair may do to this entry.

    THE REWRITE ONLY EVER PREPENDS. The entry arrives back as the tail of its
    own replacement, so no claim its author made is lost and the result can be
    trusted by looking at it rather than by re-reading the sentence. That is
    also what makes the rewrite safe on a task that has already run: what
    append-only protects is a backwards grading, `_invariants.commit_scope`
    grades against `files`, and a prefix can only ADD to the paths an entry
    names.

    AMBIGUITY IS A REFUSAL AND NOT A RANKING. An entry naming a test file and
    the source file it drives names both in prose, and picking the first would
    be a convention this field has never had. The author knows which one holds
    the case; this does not.
    """
    if tests_add_path(entry) is not None:
        return (REPAIR_NAMED, None)
    mentioned = tests_add_mentions(entry)
    if not mentioned:
        return (REPAIR_UNNAMED, None)
    if len(mentioned) > 1:
        return (REPAIR_AMBIGUOUS, None)
    return (REPAIR_REWRITE, "%s: %s" % (mentioned[0], entry.strip()))


# --- what a runner printed AS A TEST IT RAN --------------------------------------
# Moved here from `run-test-gate.py` (`_TEST_MARKS`, `_TEST_DIRS`, `_subject_of`,
# `_segments`, `_is_suite_path`) and from `audit-task.py` (`_gate_entry_paths`),
# beside `tests_add_path` above for the reason that group is here at all: "is
# this string a path" and "is this path a test file" are the SAME filename bound,
# asked of two different fields by two different entry points, and an entry
# point cannot import another - so the gate-only narrowing in `audit-task.py`
# and `--own` in `run-test-gate.py` could each only ever reach it by copying.
# Both files keep the historic underscored names as thin aliases
# (`_is_suite_path = _phases.is_suite_path`, and so on), so no caller and no
# case that already existed had to change its spelling.

# The suffixes a test file carries in front of its extension, across the
# runners this is asked about. Used to relate `src/foo.test.ts` to `src/foo.ts`
# and NOWHERE ELSE: a path that is not test-shaped is never re-spelled.
TEST_MARKS = (".test", ".spec", "_test", "_spec", "-test", "-spec")


def subject_of(path):
    """The file a TEST path is about, or None when the path is not test-shaped.

    `tests/foo.spec.ts` -> `foo`, `src/foo.test.ts` -> `foo`, `src/foo.ts` -> None.
    The basename alone, because the two live in different directories as often as
    not - `src/foo.ts` tested from `tests/foo.spec.ts` is the ordinary layout.

    DELIBERATELY NARROW. `_PATHISH` above can over-match harmlessly because a
    spurious path only ADDS overlap and overlap is reported rather than enforced.
    That reasoning does NOT carry here: a false overlap tells the reader their work
    was exercised when it was not, which is the exact false comfort `NO OVERLAP`
    exists to prevent. So this fires only on a path that really is spelled like a
    test, and only onto a file whose stem it matches exactly.
    """
    base = str(path or "").rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0] if "." in base else base
    for mark in TEST_MARKS:
        if stem.endswith(mark) and len(stem) > len(mark):
            return stem[:-len(mark)]
    return None


# ...and the directory names a suite lives in when its FILE NAME does not say so.
# `__tests__/order.ts` is jest's own layout and carries no `.test` mark at all, so
# `subject_of` cannot see it. Read for the CLASSIFICATION only and never for the
# match - a directory is far too weak to re-spell a path onto another file's stem,
# which is the thing `subject_of` guards.
TEST_DIRS = frozenset((
    "__tests__", "__test__", "test", "tests", "spec", "specs", "e2e",
))


def path_segments(path):
    """A path's directory segments, POSIX-spelled, without its basename."""
    return str(path or "").replace("\\", "/").split("/")[:-1]


def is_suite_path(path):
    """Whether the runner printed this as a TEST IT RAN rather than as a file it
    processed.

    THREE READINGS, and the second and third are why this is not `subject_of`
    under another name: a suite says so in its FILE NAME (`order.test.ts`), in
    the basename PREFIX pytest's own convention uses (`test_orders.py`, which
    carries none of `TEST_MARKS`), or in its DIRECTORY (`__tests__/order.ts`,
    jest's own layout, which carries no mark either). `subject_of` may use only
    the first, because it re-spells a path onto another file's stem and neither
    a bare prefix nor a directory is strong enough to justify that - the plan
    gate's own default `exemptGlobs` already reads `**/test_*.*` as a test file,
    and classifying is the weaker job, so it may read the weaker signal.
    """
    base = str(path or "").rsplit("/", 1)[-1]
    return (subject_of(path) is not None
            or base.startswith("test_")
            or any(seg in TEST_DIRS for seg in path_segments(path)))


# --- what a derived gate's slot may be handed ------------------------------------
# A runner that relates source files to their tests (`jest --findRelatedTests`,
# `vitest related`) resolves a module through its import graph, so a SOURCE is
# a file in a language a test imports. Anything else that is not a suite - a
# document, a workflow, a config file, a stylesheet, a shell script - is an
# input neither kind of slot turns into a test, and is handed to none.
SOURCE_EXTENSIONS = frozenset((
    ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts",
    ".vue", ".svelte", ".go", ".rs", ".java", ".kt", ".kts", ".scala", ".rb",
    ".php", ".cs", ".fs", ".c", ".h", ".cc", ".cpp", ".hpp", ".cxx", ".m",
    ".mm", ".swift", ".dart", ".ex", ".exs", ".erl", ".clj", ".lua", ".jl",
))
DOCUMENT_EXTENSIONS = frozenset((
    ".md", ".markdown", ".mdx", ".rst", ".txt", ".adoc", ".asciidoc", ".org",
))
CONFIG_EXTENSIONS = frozenset((
    ".json", ".jsonc", ".json5", ".yml", ".yaml", ".toml", ".ini", ".cfg",
    ".conf", ".lock", ".env", ".properties", ".xml",
))
# Where a CI system reads its pipeline: under a directory, or one root file.
WORKFLOW_DIRS = (".github/workflows", ".circleci", ".buildkite")
WORKFLOW_FILES = frozenset((
    ".gitlab-ci.yml", ".travis.yml", "azure-pipelines.yml",
    "bitbucket-pipelines.yml", "appveyor.yml", "Jenkinsfile",
))
# A file a runner or its plugins read to set a run up, by NAME: it sits beside
# the tests and carries a source extension, and no runner collects it as one.
CONFIG_NAMES = frozenset(("conftest.py", "setup.py", "noxfile.py",
                          "jest-preset.js"))
# The basename stems (before the first dot) of a setup file a runner is told
# to load first - `setupFiles`, `globalSetup` - matched case-blind.
SETUP_STEMS = frozenset((
    "setup", "teardown", "setuptests", "setup-tests", "setup_tests",
    "test-setup", "tests-setup", "globalsetup", "global-setup", "global_setup",
    "globalteardown", "global-teardown", "global_teardown",
))
# The words a config's or setup file's middle dot-separated part carries:
# `jest.config.js`, `karma.conf.js`, `jest.setup.ts`, `vitest.workspace.ts`.
CONFIG_INNER_WORDS = frozenset(("config", "conf", "setup", "teardown",
                                "workspace"))
# Where a test's inputs live rather than its cases: any file under one of
# these directories is a fixture, whatever its extension.
FIXTURE_DIRS = frozenset((
    "fixtures", "fixture", "__fixtures__", "__mocks__", "__snapshots__",
    "testdata", "test-data", "test_data",
))
# The modules jest's and vitest's import graph resolves - the two runners
# whose related-tests mode `_gate_derive.RELATED_SLOT_WORDS` reads. A related
# slot handed a file outside these relates nothing, so a Python source given
# to `jest --findRelatedTests` is a run of nothing.
SCRIPT_MODULE_EXTENSIONS = frozenset((
    ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts", ".vue",
    ".svelte",
))


def _is_config_name(base):
    """Whether a basename names a config or setup file whatever its folder."""
    low = base.lower()
    words = low.split(".")
    return (low in CONFIG_NAMES or base.startswith(".")
            or words[0] in SETUP_STEMS
            or any(w in CONFIG_INNER_WORDS for w in words[1:-1]))


def path_kind(path):
    """`workflow`, `document`, `config`, `fixture`, `suite`, `source` or
    `other` - what kind of file a declared path is, for the one question
    `slot_takes` asks.

    KIND BEFORE DIRECTORY: a test directory holds more than tests - its
    `conftest.py`, a `playwright.config.ts`, a `setup.ts` a runner loads
    first, a `README.md`, a `fixtures/a.json` - and none of them is a test
    any runner collects. So a workflow, a document, a config by name, a
    fixture by folder and a config or data file by extension are decided
    first; a suite is then a path whose name says so (`subject_of`'s test
    mark or pytest's `test_` prefix), and a test directory decides only for a
    file with a source extension and neither mark (`__tests__/order.ts`,
    jest's own layout) - any other file there is a test's input, a fixture.
    A TEST MARK OUTRANKS A CONFIG NAME on a source file: `setup.test.ts` and
    `app.config.test.ts` are the suites of a setup file and a config, and a
    runner collects them by that mark; a fixture folder still decides first.
    `is_suite_path` keeps its wider reading, because it answers a different
    question: whether a runner printed a path as a test it ran."""
    norm = str(path or "").replace("\\", "/")
    base = norm.rsplit("/", 1)[-1]
    ext = ("." + base.rsplit(".", 1)[-1].lower()) if "." in base[1:] else ""
    segments = path_segments(norm)
    folder = "/" + "/".join(segments)
    if base in WORKFLOW_FILES or any(("/" + d) in folder for d in WORKFLOW_DIRS):
        return "workflow"
    if ext in DOCUMENT_EXTENSIONS:
        return "document"
    marked = subject_of(norm) is not None and ext in SOURCE_EXTENSIONS
    if _is_config_name(base) and not marked:
        return "config"
    if any(seg in FIXTURE_DIRS for seg in segments):
        return "fixture"
    in_test_dir = any(seg in TEST_DIRS for seg in segments)
    if ext in CONFIG_EXTENSIONS:
        return "fixture" if in_test_dir else "config"
    if subject_of(norm) is not None or base.startswith("test_"):
        return "suite"
    if in_test_dir:
        return "suite" if ext in SOURCE_EXTENSIONS else "fixture"
    return "source" if ext in SOURCE_EXTENSIONS else "other"


def slot_takes(path, takes_sources):
    """Whether a derived gate's slot may be handed `path` - `takes_sources`
    being what that slot's own command relates (`_gate_derive.slot_reading`):
    falsy for a slot that takes suites alone, the extensions a related-tests
    runner resolves (`SCRIPT_MODULE_EXTENSIONS`), or True for any source.

    A suite always, except that a related slot takes a suite only in its own
    runner's language as it takes a source; a source only when the slot
    relates sources to their tests; a document, workflow, config, fixture or
    any other file never.

    THE ONE DECISION, asked of each declared path for each command: by the
    `files` arm that points a task's gate (and so by `scope`'s re-derivation,
    which runs that arm), by the re-point handing each command its paths
    (`_gate_derive.repointed`, `point_shape`), and by the refusal reading back
    what was written (`_gate_derive.untaken_slot_paths`). A runner handed a
    file it cannot turn into a test runs nothing of the task's, red whatever
    the work."""
    kind = path_kind(path)
    if kind not in ("suite", "source"):
        return False
    if not takes_sources:
        return kind == "suite"
    if takes_sources is True:
        return True
    norm = str(path or "")
    ext = ("." + norm.rsplit(".", 1)[-1].lower()) if "." in norm else ""
    return ext in takes_sources


# --- what an open finding is ----------------------------------------------------
# A finding is SETTLED when it names a status from this table or a fix commit; an
# entry that is neither is open, and a sign-off must say what became of it.
SETTLED_STATUS = ("fixed", "accepted-open", "carried")


def open_findings(phase):
    """The findings of `phase`'s review that are neither fixed nor carrying a
    recorded disposition. Legacy string findings have no field to hold one and
    are not counted. The verb and the driver both ask this one function."""
    review = phase.get("review") if isinstance(phase.get("review"), dict) else {}
    return [f for f in (review.get("findings") or [])
            if isinstance(f, dict) and f.get("status") not in SETTLED_STATUS
            and not (f.get("fixTask") and f.get("commit"))]


def gate_entry_paths(entry):
    """Every file path a gate entry NAMES, in the order they appear in it.

    THE SAME QUESTION `tests.add` IS ASKED, asked of each whitespace-separated
    token instead of the leading one. `tests_add_path` is the ONE answer to
    "does this string name a file", and a gate entry is the other
    place a path has to be recognized inside free text -- a second spelling of
    the filename bound would be two opinions about the same token, and the one
    that drifted would either miss a suite or read `--selectProjects` as a path.

    A token has to carry an extension or be a dotfile to count, which is what
    keeps `npm`, `--shard`, `1/4` and a bare build-command key out of the answer.

    The tokens are `shell_words`: a quoted path is one word and comes back as
    the name it spells, without its quotes.
    """
    if not isinstance(entry, str):
        return []
    found = []
    for _raw, value in shell_words(entry):
        path = shell_word_path(value)
        if path:
            found.append(path)
    return found


# The words a gate entry starts its SCRIPT with: what is run, not what is tested.
# `python3 a/test_x.py a/test_y.py` runs the first path as a program and hands
# it the second, so only the first is a suite that ran. A test RUNNER
# (`pytest`, `go test`, `npx playwright test`) takes every path it is given as a
# suite, so an entry naming several behind one of those is the ordinary spelling
# and must not be read as this fault.
_SCRIPT_RUNNER = re.compile(
    r"^(?:python[0-9.]*|py|node|nodejs|deno|bun|ruby|perl|php|bash|sh|zsh|"
    r"pwsh|powershell)$")


_PYTHON_RUNNER = re.compile(r"^(?:python[0-9.]*|py)$")


def _runner_name(word):
    """The lower-cased program name of a shell word's value, or None."""
    base = str(word or "").replace("\\", "/").rsplit("/", 1)[-1]
    return base.lower().replace(".exe", "")


def _is_script_runner(word):
    """Whether `word` (a shell word's value, or None) names an interpreter."""
    return bool(_SCRIPT_RUNNER.match(_runner_name(word)))


def _is_python_runner(word):
    """Whether `word` names a Python interpreter, the only runner whose options
    `_PLAIN_INTERPRETER_FLAGS` describes."""
    return bool(_PYTHON_RUNNER.match(_runner_name(word)))


# The words that join or open simple commands; a redirection operator is the
# other half of what the punctuation reader yields and takes the word after it.
_LIST_PUNCT = frozenset("();&|")


def _is_list_operator(token):
    return bool(token) and all(c in _LIST_PUNCT for c in token)


# A redirection operator with the file it names in the SAME word: `>out.log`,
# `2>err.log`, `&>all.log`, `2>&1`. The target must not start with an operator
# character, so a bare `>>` or `>&` stays the operator that takes the next word.
_ATTACHED_REDIRECTION = re.compile(r"^(?:[0-9]*|&)[<>]+&?[^<>&|].*$")


def _is_redirection(token):
    return bool(token) and any(c in "<>" for c in token) \
        and all(c in "<>&|" for c in token)


def gate_entry_commands(entry):
    """`[[word, ...], ...]`: the simple commands of a gate entry, each a list of
    the values a POSIX shell reads its words as.

    `shell_words` answers "which words" for a whole entry and splits nothing, so
    it cannot say where one command ends. The shape check needs that: `python3
    a/test_x.py && python3 a/test_y.py` is two commands that each run one
    suite, and reading it as one hands the second suite to the first as an
    "argument". The split is shlex's own punctuation reader (no regex over
    shell syntax): `&&`, `||`, `;`, `|`, `&` and parentheses end a command
    wherever they stand outside quotes, and a redirection drops the word it
    names, which is a file written to and no part of any command's arguments.
    Backslashes stay ordinary characters, as in `shell_words`, so a Windows
    path keeps its separators.

    An entry the reader cannot delimit (an unbalanced quote) falls back to the
    whitespace split with only the bare operators separating commands, and a
    word that is a redirection with its target written against it
    (`>out.log`, `2>&1`) is dropped, as the delimited reading drops the target.
    """
    if not isinstance(entry, str):
        return []
    tokens = []
    try:
        for line in entry.splitlines():
            lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
            lexer.whitespace_split = True
            lexer.escape = ""
            tokens.extend(list(lexer))
            tokens.append(";")
    except ValueError:
        tokens = [t if t not in ("&&", "||", "|", "&", ";") else ";"
                  for t in entry.split() if not _ATTACHED_REDIRECTION.match(t)]
    commands, current, skip = [], [], False
    for token in tokens:
        if skip:
            skip = False
        elif _is_list_operator(token):
            if current:
                commands.append(current)
            current = []
        elif _is_redirection(token):
            skip = True
        else:
            current.append(token)
    if current:
        commands.append(current)
    return commands


# PYTHON'S interpreter flags that change nothing about WHICH file is run: a
# bundle of letter flags (`-u`, `-uB`) and the two that take a separate
# argument. Every other option (`-m`, `-c`, node's `--test`) can make the next
# word something other than the program, so an entry using one is not read -
# and so is any option of another runner (`bash -s` reads the script from
# stdin, so the paths behind it are its arguments), because this set is
# Python's and says nothing about theirs.
_PLAIN_INTERPRETER_FLAGS = re.compile(r"^-[uBEsSIOvqbdRxt]+$")
_ARGUMENT_FLAGS = ("-X", "-W")


def _only_plain_options(words):
    """Whether `words` are all options that leave the next word the program."""
    i = 0
    while i < len(words):
        word = words[i]
        if _PLAIN_INTERPRETER_FLAGS.match(word):
            i += 1
        elif word in _ARGUMENT_FLAGS and i + 1 < len(words):
            i += 2
        elif word[:2] in _ARGUMENT_FLAGS and len(word) > 2:
            i += 1
        else:
            return False
    return True


def _runs_first_path_as_program(before):
    """Whether the words in front of a command's first path make that path the
    program: nothing at all, or an interpreter followed by no option, or by a
    Python interpreter's plain options."""
    return not before or any(
        _is_script_runner(word) and (
            not before[i + 1:] or (_is_python_runner(word)
                                   and _only_plain_options(before[i + 1:])))
        for i, word in enumerate(before))


def _command_shape_problem(words):
    """The shape problem of ONE simple command's words, or None."""
    found = [(i, value, shell_word_path(value)) for i, value in enumerate(words)]
    found = [(i, value, path) for i, value, path in found if path]
    if not found:
        return None
    # Only a suite can be run twice: a tool given one path as its input and its
    # output (`--in p.json --out p.json`) names it twice and means it. A node id
    # makes a different word of the same file, so the words are compared as
    # written and `a_test.py::one a_test.py::two` repeats nothing.
    suites = [value for _i, value, path in found if is_suite_path(path)]
    again = [v for k, v in enumerate(suites) if v in suites[:k]]
    if again:
        return "names %s more than once" % ", ".join(
            repr(v) for v in sorted(set(again)))
    first_i, _first_value, first = found[0]
    if is_suite_path(first) and _runs_first_path_as_program(words[:first_i]):
        extra = [path for _i, _v, path in found[1:] if is_suite_path(path)]
        if extra:
            return ("runs %r as a program and hands it %s as arguments, so %s"
                    % (first, ", ".join(repr(p) for p in extra),
                       "they never run as suites" if len(extra) > 1
                       else "it never runs as a suite"))
    return None


def gate_entry_shape_problem(entry, build=None):
    """Why `entry` is not a gate entry that runs what it names, or None.

    Each SIMPLE COMMAND of the entry is read on its own (`gate_entry_commands`),
    because `a && b` runs two programs and what one is handed says nothing about
    the other. Two shapes are reported, each a gate that passes while a suite
    never ran:

      * a suite named TWICE in one command -- the same word again runs it again
        or, as an argument, asks it for itself. Only suites count, and two node
        ids of one file are two different words;
      * a suite file run as a PROGRAM with another suite behind it
        (`python3 a/test_x.py a/test_y.py`): the second is only the first's
        argument, so it never ran as a suite. "Run as a program" is read from
        the words in front of the first path -- nothing, or an interpreter and
        its plain options (`python3 -u`, `-X dev`) -- because a test runner
        given two suites runs both, and an option that may change what is run
        (`-m`, `--test`) is left unread.

    `build` is `meta.buildCommands` (or any container of its keys): an entry
    that IS a key is resolved through the plan whole and is not read here.
    A spelled sweep entry (`python3 tools/sweep-selftests.py a/test_x.py
    a/test_y.py`) is quiet because its first path word is the sweep, which is
    not a suite file.

    The reason is a clause that names the paths, so a refusal and a warning can
    each put it after the entry they quote.
    """
    if not isinstance(entry, str) or (build and entry in build):
        return None
    for words in gate_entry_commands(entry):
        problem = _command_shape_problem(words)
        if problem:
            return problem
    return None


def own_gate_entries(manifest, phase, task):
    """The gate entries that are `task`'s OWN, as declared and unresolved:
    what `run-test-gate.py --own` runs, and what decides whether the executor
    brief prints that command at all - one function, so the brief cannot offer
    a run the runner then answers with "nothing of its own to run".

    A TASK MEASURED BY ITS PHASE'S GATE HAS NONE: the phase's gate is
    everybody's, and an executor's own tests are a narrower claim than any of
    it can make. Of the task's own entries, one is kept only when it is not a
    bare `meta.buildCommands` key - a key runs whatever that build step runs
    today, however path-shaped its spelling - and when it names at least one
    path, every one of them a `tests.add` path of this task. An entry naming
    no path is pointed at nothing; one naming another test beside this one's
    is not this task's alone to claim.
    """
    build = ((manifest.get("meta") or {}).get("buildCommands") or {})
    build = build if isinstance(build, dict) else {}
    entries, source = _mio.gate_entries(phase, task)
    if source != "task":
        return []
    tests = task.get("tests") if isinstance(task.get("tests"), dict) else {}
    add_paths = set(p for p in (tests_add_path(e)
                                for e in (tests.get("add") or [])
                                if isinstance(e, str))
                    if p is not None)
    kept = []
    for entry in entries:
        paths = [] if entry in build else gate_entry_paths(entry)
        if paths and all(p in add_paths for p in paths):
            kept.append(entry)
    return kept


# One shell word as written: runs of unquoted non-space characters and whole
# single- or double-quoted spans, so whitespace inside a quote does not end the
# word. A backslash outside quotes is an ordinary character here -- see
# `shell_words` for why.
_SHELL_WORD = re.compile(r"""(?:[^\s'"]|'[^']*'|"(?:[^"\\]|\\.)*")+""")


def shell_words(entry):
    """`[(raw, value)]` for each word of a gate entry: `raw` its spelling as
    written, `value` what a POSIX shell reads it as, or None when a quoted
    word does not read as exactly one word.

    THE ONE READER of a gate entry's words. `run-test-gate.py` hands every
    entry to a POSIX shell, so "which words does this entry have" is asked
    the way that shell answers it, by `gate_entry_paths` and by the re-point
    in `_gate_derive` alike -- two readings would pick a sibling's shape by
    one and rewrite it by the other.

    ONLY A WORD CARRYING A QUOTE IS READ THROUGH `shlex.split`. A word with
    none is its own value, backslashes included, which keeps every unquoted
    entry exactly as the whitespace split has always read it -- a gate
    written with a backslash separator is not re-read as an escape. An entry
    the reader cannot delimit (an unbalanced quote) falls back to that same
    whitespace split, each token standing for itself: it fails in the runner
    either way, and this has no better reading of it to offer.
    """
    if not isinstance(entry, str):
        return []
    if _SHELL_WORD.sub("", entry).strip():
        return [(token, token) for token in entry.split()]
    words = []
    for raw in _SHELL_WORD.findall(entry):
        if "'" not in raw and '"' not in raw:
            words.append((raw, raw))
            continue
        try:
            value = shlex.split(raw)
        except ValueError:
            return [(token, token) for token in entry.split()]
        words.append((raw, value[0] if len(value) == 1 else None))
    return words


def shell_word_path(value):
    """The file one shell word names, as `shell_words` read it, or None.

    `tests_add_path` asked of the word, with WHITESPACE MAPPED AWAY FIRST: it
    refuses a space because in a `tests.add` sentence a space ends the path
    and starts the prose, but a shell word has already been bounded by the
    shell, so a space inside one is part of the name and only the segment and
    filename questions are left. The mapping replaces one character with one,
    so the answer is cut back out of the word itself, spaces restored.
    """
    if not isinstance(value, str):
        return None
    path = tests_add_path(re.sub(r"\s", "_", value))
    return value[:len(path)] if path else None


# --- the walk --------------------------------------------------------------------
def _moved_from_conflicts(task_by_id, task_ids):
    """WARNINGS for a `movedFrom` chain no verb would have written.

    The allocator never mints an id a chain holds and `move` never reuses one, so
    a plan made by the verbs cannot reach either shape - but a hand edit can, and
    the evidence readers join old-id runs to the task whose chain names the id.
    An old id a LIVE task holds would move that task's own runs onto another;
    one two chains both claim has no single owner. `_evidence_io.subject_aliases`
    skips both; this says so where a reader can repair it.
    """
    live = set(str(t) for t in task_ids)
    claims = {}
    out = []
    for tid in task_ids:
        for old in _mio.moved_from_ids(task_by_id.get(tid)):
            claims.setdefault(old, []).append(str(tid))
            if old in live:
                out.append("task %s: movedFrom names %s, which a live task holds - "
                           "the evidence readers will not join runs through it, "
                           "and the chain should name the id this task used to "
                           "have" % (tid, old))
    for old, owners in sorted(claims.items()):
        if len(owners) > 1:
            out.append("movedFrom id %s is claimed by both %s - the evidence "
                       "readers join it to neither, since a moved id has one "
                       "owner" % (old, " and ".join(sorted(set(owners)))))
    return out


def _walk_phases(phases, build_keys=()):
    """One pass over every phase and every task: (index, findings, warnings).

    `build_keys` is the set of `meta.buildCommands` names, which is what a gate
    entry resolves through; empty, the comma-joined-entry rule has nothing to
    compare against and stays silent.

    THE INDEX IS WHY THIS WAS NEVER CUT OUT BEFORE. Five accumulating locals
    ride this single walk and each is read by a DIFFERENT check further down,
    which is exactly the coupling that kept `validate()` in one 354-line piece.
    Naming them turns the coupling into an argument:

      phase_ids     every phase id, document order   -> unique ids, proposals
      task_ids      every task id, document order    -> unique ids, refs,
                                                        fileIndex, bugs
      task_by_id    id -> the task object            -> bug reciprocity
      task_files    id -> its non-empty `files` list -> fileIndex, both ways
      bug_links     (twhere, task id, bugId) per link-> bug reciprocity

    `task_files` holds only tasks whose `files` is a non-empty list, because
    that is the question `_check_file_index` asks of it; a task with no files
    is absent rather than mapped to [], and the fileIndex check reads it with
    `.items()` only.

    The walk stays ONE pass on purpose. Splitting it per-question would visit
    every task four times to build four dicts, and would let two of them
    disagree about which objects were skipped as malformed.
    """
    f, w = [], []
    phase_ids, task_ids = [], []
    task_bug_links = []       # (twhere, task_id, bugId)
    task_by_id = {}
    task_files = {}           # task_id -> files list

    for pi, phase in enumerate(phases):
        if not isinstance(phase, dict):
            f.append(_output.finding("phases.walk_phases.object", "phases[%d]: not an object" % pi))
            continue
        pid = phase.get("id")
        pwhere = "phase %s" % (pid or ("phases[%d]" % pi))
        _require_fields(phase, pwhere, f)
        _unknown_keys(phase, KNOWN_PHASE, pwhere, w)
        # connector v2: phaseWorkItems writes a phase-level adoLink
        _check_ado(phase, pwhere, f)
        # U-PARENT: the AUTHORED half beside it. Shape only here - where the
        # parent resolves to and whether that place can be true are questions
        # about the whole plan, and `_manifest_crossrefs` asks them.
        _add_parent(phase, pwhere, f, w)
        # U-BOARD: the other AUTHORED ado field, and PHASE-ONLY on purpose - a
        # task inherits its phase's answer and never declares one, so checking it
        # on the task walk below would invite a declaration the resolver ignores.
        _add_tracked(phase, pwhere, f, w)
        # A list or object id cannot key an index; `_require_fields` named it.
        if pid and not isinstance(pid, (list, dict)):
            phase_ids.append(pid)
        if phase.get("status") not in STATUS:
            f.append(_output.finding("phases.walk_phases.phase-status", "%s: status %r not in %s" % (pwhere, phase.get("status"), list(STATUS))))
        _check_claim(phase, pwhere, f, w)
        _check_review(phase, pwhere, w)
        _check_area_tag(phase, pwhere, f)
        w.extend(_check_phase_intent(phase, pwhere, build_keys))
        # A budget of 0 or a negative one is not a budget, and a string is a typo
        # that would silently render as "no budget". Both are worth saying out loud.
        if "budgetUSD" in phase:
            budget = phase.get("budgetUSD")
            if isinstance(budget, bool) or not isinstance(budget, (int, float)):
                f.append(_output.finding("phases.walk_phases.budgetusd-number", "%s: budgetUSD must be a number, got %s"
                         % (pwhere, type(budget).__name__)))
            elif budget <= 0:
                f.append(_output.finding("phases.walk_phases.budgetusd-greater-than", "%s: budgetUSD must be greater than 0 (got %s) — omit the "
                         "key entirely for 'no budget'" % (pwhere, budget)))
        # `mergedHead` is written only by close-phase.py and read by ancestry
        # (`git merge-base --is-ancestor`), so a malformed value is a WARNING
        # naming it rather than a refusal - the field stays additive, and the
        # cost of a bad value is that the phase reads `unknown` rather than
        # `whole`, never a validator refusal.
        if "mergedHead" in phase:
            merged_head = phase.get("mergedHead")
            if merged_head is not None and not (isinstance(merged_head, str)
                                                and _FULL_SHA_RE.match(merged_head)):
                w.append("%s: mergedHead %r is not a full hex SHA (40 "
                         "characters) - ancestry cannot be asked of a "
                         "partial or malformed one, so this phase reads "
                         "unknown rather than whole" % (pwhere, merged_head))

        tasks_val = phase.get("tasks")
        if "tasks" not in phase:
            w.append("%s: no 'tasks' key — the schema requires one (an empty "
                     "phase should carry an empty list)" % pwhere)
        elif not isinstance(tasks_val, list):
            f.append(_output.finding("phases.walk_phases.tasks-array", "%s: tasks must be an array, got %s"
                     % (pwhere, type(tasks_val).__name__)))
        # A phase is 'done' only after sign-off, which requires every task done.
        # A done phase with a non-done task is a stale-status slip the schema
        # can't express (e.g. a hand-regenerated roadmap that flipped the phase
        # but not its tasks).
        if phase.get("status") == "done":
            # FINISHED, not done: a task the team cancelled is settled, and a
            # phase that signed off around it is not a slip. Only genuinely
            # unfinished work (pending / in_progress / blocked) contradicts it.
            not_done = [t.get("id") or "?" for t in _safe_list(tasks_val)
                        if isinstance(t, dict) and t.get("status") not in TERMINAL]
            if not_done:
                f.append(_output.finding("phases.walk_phases.status-done-task", "%s: status 'done' but %d task(s) are not finished (%s) "
                         "— a phase is done only after ALL its tasks are done "
                         "or cancelled (sign-off)"
                         % (pwhere, len(not_done),
                            _output.some_of(not_done))))
        for ti, task in enumerate(_safe_list(tasks_val)):
            if not isinstance(task, dict):
                f.append(_output.finding("phases.walk_phases.object-2", "%s tasks[%d]: not an object" % (pwhere, ti)))
                continue
            tid = task.get("id")
            twhere = "task %s" % (tid or ("%s.tasks[%d]" % (pwhere, ti)))
            _require_fields(task, twhere, f)
            _unknown_keys(task, KNOWN_TASK, twhere, w)
            # A list or object id cannot key an index; `_require_fields` named it.
            if tid and not isinstance(tid, (list, dict)):
                task_ids.append(tid)
                task_by_id[tid] = task
                files = task.get("files")
                if isinstance(files, list) and files:
                    task_files[tid] = files
            # `outputs` is the only key on a task that can WIDEN what the plan
            # gate allows, so a pattern it may not honour is a FINDING and not a
            # warning: a warning leaves the entry in the file, and the gate would
            # then be deciding for itself which half of the plan to believe. The
            # rule is `_manifest_vocab.output_pattern_problem` and is asked here,
            # by `audit-task.py` before a write, and by the gate before it opens
            # a file - one rule, three readers, so none of them can be generous
            # on its own.
            outputs = task.get("outputs")
            if outputs is not None and not isinstance(outputs, list):
                f.append(_output.finding("phases.walk_phases.outputs-array", "%s: outputs must be an array, got %s"
                         % (twhere, type(outputs).__name__)))
            for _entry, why in _touts.output_problems(outputs):
                f.append(_output.finding("phases.walk_phases.outputs", "%s: outputs %s" % (twhere, why)))
            if task.get("status") not in STATUS:
                f.append(_output.finding("phases.walk_phases.task-status", "%s: status %r not in %s" % (twhere, task.get("status"), list(STATUS))))
            if (phase.get("status") == "pending"
                    and task.get("status") == "in_progress"):
                # WHAT THIS ESTABLISHED, AND NOT A GUESS AT THE DOCUMENT'S AGE.
                # The line used to ask whether the manifest predated a release
                # and name a command the reader had not run -- on a plan the CLI
                # had written minutes earlier, because until `start` promoted the
                # phase this state was what every command-line run produced.
                # Age was never observed here; two statuses and one stamp were.
                #
                # AND IT IS NOT A CLAIM ABOUT THE PLAN GATE. A running task under
                # a pending phase already counts as a running phase, deliberately
                # -- the reason is written where that is decided -- so nothing is
                # inert and nothing needs unblocking. What is missing is the
                # record, which is why the stamp is what the line reports.
                w.append("%s is in_progress but its %s is still 'pending' — %s. "
                         "The plan gate is unaffected: a running task counts as "
                         "a running phase. Both writers that promote a phase "
                         "(`/audit:task start`, the control panel's save) move "
                         "the status and stamp `startedAt` together, so a pair "
                         "like this is a phase whose status was set by hand"
                         % (twhere, pwhere,
                            ("the phase carries a `startedAt`, so only its "
                             "status is behind" if phase.get("startedAt")
                             else "so nothing records when the phase began")))
            tests = task.get("tests")
            if "tests" in task and tests is not None and not isinstance(tests, dict):
                f.append(_output.finding("phases.walk_phases.tests-object-with", "%s: tests must be an object with a 'mode', got %s"
                         % (twhere, type(tests).__name__)))
            if isinstance(tests, dict) and tests.get("mode") not in TESTS_MODE:
                f.append(_output.finding("phases.walk_phases.tests-mode", "%s: tests.mode %r not in %s" % (twhere, tests.get("mode"), list(TESTS_MODE))))
            # `tdd` + `expectRedFirst` + nothing named is an instruction to
            # prove a red first with no case to prove it with, and nothing said so:
            # a live run met exactly this on the largest security change of a phase,
            # generated by `/audit:init`, and only noticed later. A WARNING and not
            # a finding, because the repair is to name the case and an existing plan
            # must not go red over a field it was written without.
            #
            # UNFINISHED TASKS ONLY, and that narrowing is the difference between a
            # rule and noise. A red-first case named after the task is done is not a
            # red-first case - the opportunity it describes is gone - so warning
            # about a `done` one tells the reader about something they cannot act
            # on, which is how a warning that fires across most of a mature plan
            # teaches people to skip the whole class. Measured on this repository's
            # own manifest the moment the rule landed: 25 tasks, and every finished
            # one of them already carries its cases in `verifiedBy`.
            if isinstance(tests, dict) and tests.get("mode") == "tdd" \
                    and tests.get("expectRedFirst") \
                    and task.get("status") not in TERMINAL \
                    and not (tests.get("add") or []):
                w.append("%s: tests.mode is 'tdd' with expectRedFirst and no "
                         "tests.add - a red-first task naming no case cannot be "
                         "shown to have gone red. Name it with `/audit:task scope "
                         "%s --tests-add \"<case>\"`, or use mode 'regression' or "
                         "'gate-only' if no new test is owed" % (twhere, tid))
            # THE RULE ABOUT THE SAME FIELD ONE QUESTION OVER, and the two
            # sit together so a reader can see where they differ and why.
            #
            # The rule above asks whether a red-first task named a case AT ALL; this
            # asks whether the case it named can be found on disk. So this one
            # does NOT require `expectRedFirst`, and the difference is deliberate
            # rather than drift: `expectRedFirst` is a DERIVED field
            # (`audit-task._expects_red_first`, which `_build_task` and `scope`
            # both read: tdd, and for a fix task also a named case), it is what
            # declares the red-first intent the rule above is about, and the `files` union
            # this rule exists for does not read it at all. Requiring it here
            # would let a hand-edited `expectRedFirst: false` opt a task out of a
            # rule about a field it has no bearing on.
            #
            # TERMINAL IS EXEMPT, on the same reasoning read one step further: a
            # settled task's `tests.add` is a RECORD of work already judged, and
            # the scope verb leaves it append-only, so a line about
            # one names nothing anybody can act on.
            #
            # ANNOUNCED AS A WARNING THROUGH THE 2.x LINE, ENFORCED FROM 3.0.0.
            # `COMPATIBILITY.md` promised that a manifest which validates keeps
            # validating through 2.x, and named this release as where the shape
            # a `tdd` task's `tests.add` entry must have stops being merely
            # advised: the order it promised was announce, then enforce, and
            # this is the enforcement half landing.
            if tests_add_graded(task):
                add_val = tests.get("add")
                if add_val is not None and not isinstance(add_val, list):
                    # A FINDING, and a TYPE one, which is its neighbours' shape
                    # (`tasks must be an array`, `tests must be an object`) and
                    # not a deprecation: the schema has always declared this an
                    # array, so a string here never validated against it. Said
                    # ONCE - iterating a string yields one warning per character,
                    # which is the warning class people learn to skip.
                    f.append(_output.finding("phases.walk_phases.tests-add-array", "%s: tests.add must be an array, got %s"
                             % (twhere, type(add_val).__name__)))
                for entry in _safe_list(add_val):
                    if tests_add_path(entry) is not None:
                        continue
                    f.append(_output.finding("phases.walk_phases.so-files-union", "%s: %s, so the `files` union has no path to "
                             "carry and commit-scope will refuse the case "
                             "this task says it will create. Write it as "
                             "\"<path>: <what it asserts>\" "
                             "(COMPATIBILITY.md -> Validation stays additive). "
                             "For a plan written before the rule, "
                             "`scripts/manifest/repair-tests-add.py <manifest>` "
                             "reports every entry like this one and rewrites "
                             "the ones that already spell their path: "
                             "%r" % (twhere, TESTS_ADD_UNNAMED_FINDING, entry)))
            # THE DERIVED GATE, READ BACK. `/audit:init` step 5.3 narrows a
            # task's `tests.gate` to the paths that task names and reaches the
            # phase's wide gate only as its last arm, with a reason in the
            # description; nothing here had ever looked at the result, so a plan
            # that took the last arm on task after task validated in silence. A
            # task carrying the phase gate re-asks the PHASE's question - is the
            # repository still whole - inside the executor's retry loop, on every
            # attempt, per task, per phase running in parallel, which is the cost
            # the derivation exists to avoid.
            #
            # A WARNING, NEVER A FINDING, for two independent reasons: the wide
            # gate is the RIGHT answer for a runner with no path-scoped spelling,
            # and a validator that refused a plan written before this line
            # existed is a validator people stop running.
            #
            # TERMINAL IS EXEMPT, on the reasoning the red-first rule above uses:
            # the gate of a settled task has already run, so a line about it
            # names nothing anybody can still act on, and the settled tasks are
            # the bulk of a mature plan - which is the difference between a line
            # an operator reads and a class they learn to skip. Re-derive the
            # split on any plan with `validate-manifest.py <plan> --verbose`.
            #
            # AN EMPTY PHASE GATE RAISES NOTHING. A phase that grades itself with
            # no command has no wide gate for a task to have copied, and a task
            # with an empty gate is a designed state `audit-task.py` reports on
            # its own terms; neither is this rule's subject.
            #
            # AND A TASK THAT RECORDS WHY IT IS WIDE IS NOT ASKED AGAIN. The line
            # used to offer two routes and only one of them existed: narrowing,
            # or writing the reason into the task's `description` -- which is
            # prose nothing here reads, so an operator who took the advice saw
            # the same line for ever. Measured on the repository this plugin
            # dogfoods on, where every gate entry resolves to a command that
            # walks the tree or names fixed directories, the line covered most
            # of the plan and could never be answered.
            #
            # `gateBasis` IS THAT ANSWER AS DATA, written by the derivation that
            # is the only thing which ever knew it: `phase-no-spelling` says this
            # project records no path-scoped gate entry to read a narrower
            # spelling off, so narrowing here would be a guess; `declared` says a
            # caller named these commands outright. Neither is the unnarrowed
            # default the rule exists to name. A task recording NOTHING is still
            # named -- a generated plan that gave task after task the whole suite
            # on a runner that does take paths carries no basis at all, and that
            # is the case this rule was built from.
            phase_gate = _gate_entries(phase.get("testGate"))
            task_gate = _gate_entries(tests.get("gate")
                                      if isinstance(tests, dict) else None)
            if task.get("status") not in TERMINAL:
                w.extend(_comma_joined_gate(task_gate, build_keys, twhere,
                                            "tests.gate"))
                w.extend(_signoff_only_gate(task_gate, build_keys, twhere,
                                            "tests.gate"))
            # A WARNING, FOR EVERY TASK INCLUDING A FINISHED ONE: the verbs
            # refuse the shape when it is written now, but a plan written before
            # that holds some, and validation stays additive. A finished task's
            # gate is a record that cannot be corrected, but it is exactly the
            # record that says a suite ran when it may not have, and a warning
            # costs the operator one line.
            for entry in task_gate:
                problem = gate_entry_shape_problem(entry, build_keys)
                if problem:
                    w.append(_output.finding(
                        "phases.gate_entry_shape.malformed",
                        "%s: tests.gate entry %r %s - write one entry "
                        "naming every suite behind the plan's runner "
                        "(`meta.phaseGate.derived.spelling` when it records "
                        "one), or one entry per suite"
                        % (twhere, entry, problem)))
            gate_basis = (tests.get("gateBasis")
                          if isinstance(tests, dict) else None)
            if phase_gate and task_gate == phase_gate \
                    and task.get("status") not in TERMINAL \
                    and gate_basis not in _vocab.GATE_BASIS_ANSWERED:
                w.append("%s: tests.gate is its phase's testGate verbatim - the "
                         "wide gate, re-run on every attempt of this task "
                         "instead of once at sign-off, and %s. Narrow it to the "
                         "paths this task names, or - where the wide gate IS the "
                         "answer here - say so in a way this check reads: both "
                         "go through `/audit:task scope <id> --gate "
                         "\"<command>\"`, which records who chose the list"
                         % (twhere,
                            ("nothing on the task records which derivation "
                             "produced it" if gate_basis is None
                             else "the derivation that produced it recorded %r, "
                                  "which is a default rather than a choice"
                                  % (gate_basis,))))
            if "risk" in task and task.get("risk") not in RISK:
                f.append(_output.finding("phases.walk_phases.risk", "%s: risk %r not in %s" % (twhere, task.get("risk"), ["low", "med", "high", None])))
            _check_ado(task, twhere, f)
            _add_parent(task, twhere, f, w)
            # The id-prefix rule (workstream B) -- the hand-move detector.
            # /audit:task move renumbers a task into its target phase, so an id
            # that does not match `<phaseId>.<int>` means the object was dragged
            # by hand. A WARNING only: legacy manifests with free-form ids must
            # never go red over bookkeeping.
            # A branch suffix (`P2.4-k7m`, `_id_shape`) is part of the shape an
            # allocator mints, so it must not read as a hand move.
            if tid and pid and not re.match(
                    r"^%s\.\d+%s$" % (re.escape(str(pid)), _vocab.ID_SUFFIX), str(tid)):
                w.append("%s: id does not follow its phase's prefix (%s.<n>) "
                         "-- moved by hand? /audit:task move renumbers, "
                         "rewrites references and records a task.move row. "
                         "Informational; legacy ids stay legal" % (twhere, pid))
            if "movedFrom" in task:
                mf = task.get("movedFrom")
                if mf is not None and not isinstance(mf, dict):
                    w.append("%s: movedFrom should be an object "
                             "{id, phase, at}, got %s"
                             % (twhere, type(mf).__name__))
                elif isinstance(mf, dict):
                    lacking = [k for k in ("id", "phase", "at")
                               if not mf.get(k)]
                    if lacking:
                        w.append("%s: movedFrom is missing %s -- /audit:task "
                                 "move writes all three"
                                 % (twhere, ", ".join(lacking)))
            if task.get("bugId"):
                task_bug_links.append((twhere, tid, task["bugId"]))

    w.extend(_moved_from_conflicts(task_by_id, task_ids))
    return ({"phase_ids": phase_ids, "task_ids": task_ids,
             "task_by_id": task_by_id, "task_files": task_files,
             "bug_links": task_bug_links}, f, w)

# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    print(__doc__.strip())
