#!/usr/bin/env python3
"""
_gate_derive.py -- the gate helpers' one home, and a pure derive().

`is_shared_key`, `path_scoped_sibling` and `repointed` used to live inside
`audit-task.py`, which is where a TASK's own narrow gate is derived. A PHASE's
sign-off gate needs the identical questions asked one level up -- "is this
entry a `buildCommands` key rather than a command", "which sibling task's gate
carries this project's own path-scoped spelling", "the same entries with the
paths swapped" -- and an entry point cannot import another entry point, so a
phase-level derivation could only ever have copied the three. Moving them here
gives both callers one body apiece instead of two that could drift, and gives
the new phase-level derivation a floor to stand on that owes nothing to
`audit-task.py`'s own concerns (flags, `--gate`/`--gate-clear`, a caller-
validated `--failing-from` row). `audit-task.py` keeps thin aliases so no
caller and no existing case had to change its spelling.

`derive()` is the phase-level answer: what `meta.phaseGate.mode` computes for
ONE phase's sign-off gate, replacing only the part of the wide default that is
not `meta.phaseGate.always`. It is PURE -- every observation it needs (a
listing's exit code and paths, the installed version's answer, which paths
changed since the phase's `baseRef`, the newest red phase-scope row's named
failures, the plan gate's exempt verdict per touched file) arrives through
`facts`, supplied by the caller. That is what lets its cases run with no
subprocess and no git: a fixture is a dict, not a checkout.
"""

import os
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

import _manifest_io as _mio          # noqa: E402  (gate_entries: whose gate
#                                       measures a task, and whether it is the
#                                       task's own -- the union this reads)
import _manifest_vocab as _vocab     # noqa: E402  (PHASE_GATE_BASIS: the words
#                                       this derivation's basis is drawn from,
#                                       so a phase's testGateBasis and this
#                                       function's own reasons cannot disagree)
import _manifest_phases as _phases   # noqa: E402  (gate_entry_paths,
#                                       is_suite_path, tests_add_path,
#                                       phase_gate_default -- the one filename
#                                       bound and the one default, asked here
#                                       instead of re-derived. `_manifest_rules`
#                                       is NOT imported: its `tests_add_path` is
#                                       only a re-export of `_phases`' own, and
#                                       calling the re-export would put this
#                                       module a layer above where its real
#                                       edges land)
import _evidence_io                  # noqa: E402  (subject_key: the one
#                                       reading of "which row is THIS phase's",
#                                       asked here rather than re-derived from
#                                       a row's raw scope/phaseId pair)


# THE SAME ALIAS `audit-task.py` HELD before these bodies moved: `_phases.
# gate_entry_paths` asked of a gate entry rather than of a `tests.add` one.
# Kept under this name because `path_scoped_sibling` and `repointed` below are
# their PRE-MOVE bodies, unchanged, and both read it under this name.
_gate_entry_paths = _phases.gate_entry_paths


# --- moved from audit-task.py, bodies and docstrings unchanged ------------------
def is_shared_key(entry, build):
    """True when the entry is a `meta.buildCommands` KEY rather than a command.

    Asked of the declaration and never of the shape. `commands/init.md` has
    entries resolve through `meta.buildCommands` wherever the scope is SHARED
    and be literal commands wherever it differs per task, so what makes an entry
    wide is that the manifest declares it -- not that it looks short. A key
    someone spelled `e2e.spec` would otherwise read as path-scoped on its
    punctuation alone.
    """
    return isinstance(build, dict) and entry in build


def path_scoped_sibling(phase, build):
    """`(entries, taskId)` for the first task in this phase whose `tests.gate`
    carries a path-scoped entry, or `(None, None)`.

    THE PLAN IS THE ONLY RECORD OF THE RUNNER'S SPELLING. `commands/init.md`
    step 5.3 says it plainly: nothing persists how this project narrows a gate
    except the gates themselves, so a task added later reads the shape off its
    siblings rather than re-detecting it. Which makes the sibling EVIDENCE and
    not a resemblance -- that entry was accepted by this project's runner once,
    so the same entry with different paths in it is a command that can run.

    Document order, and the id comes back with the entries because the operator
    has to be able to go and read the gate the shape was taken from.
    """
    for task in (phase.get("tasks") or []):
        if not isinstance(task, dict):
            continue
        tests = task.get("tests")
        entries = (tests.get("gate") or []) if isinstance(tests, dict) else []
        entries = [e for e in entries if isinstance(e, str) and e.strip()]
        if any(not is_shared_key(e, build) and _gate_entry_paths(e)
               for e in entries):
            return entries, task.get("id")
    return None, None


# The second `shape` source the schema itself names (the schema's
# meta.phaseGate.derived.spelling description):
# `resolve_shape`'s `source` return is this literal string whenever the shape
# came from the DECLARED template rather than a sibling's own gate entry, so
# a caller can tell the two apart without inventing a second flag.
SPELLING_SOURCE = "meta.phaseGate.derived.spelling"


def resolve_shape(phase, build, derived_cfg):
    """`(shape, source, lines)` -- where THIS phase's path-scoped shape comes
    from, in the order the schema declares: a sibling task's own path-scoped
    gate entry FIRST (`source` is that task's id), `meta.phaseGate.derived
    .spelling` SECOND (`source` is `SPELLING_SOURCE`), or `(None, None, ...)`
    when neither exists.

    THE SIBLING WINS ON PURPOSE: its entry is EVIDENCE this project's runner
    already accepted it (`path_scoped_sibling`'s own docstring says why), and
    a declared `spelling` is unverified by comparison -- read only when no
    sibling supplies one, never in preference to one that does.

    A `spelling` carrying no literal `{paths}` placeholder is IGNORED, with a
    printed reason (`lines`) rather than a silent fallback -- the schema says
    the derivation substitutes the placeholder with the resolved file list,
    and a template with nowhere to substitute into cannot do that.
    """
    shape, owner = path_scoped_sibling(phase, build)
    if shape is not None:
        return shape, owner, []
    derived_cfg = derived_cfg if isinstance(derived_cfg, dict) else {}
    spelling_tpl = derived_cfg.get("spelling")
    if not (isinstance(spelling_tpl, str) and spelling_tpl.strip()):
        return None, None, []
    if "{paths}" not in spelling_tpl:
        return None, None, ["spelling: skipped - meta.phaseGate.derived.spelling "
                            "carries no {paths} placeholder"]
    return [spelling_tpl], SPELLING_SOURCE, []


def repointed(entries, build, paths):
    """`entries` with every path-scoped entry re-pointed at `paths`.

    THE FLAGS ARE KEPT AND ONLY THE PATHS MOVE: the sibling's tokens are rebuilt
    in order, the paths it named are dropped, and this task's paths go in where
    the first of them stood. That is what carries a source-to-test flag, a `--`
    separator or a project selector through a substitution nobody wrote a parser
    for.

    A shared key and an entry naming no path are copied THROUGH rather than
    dropped: a gate of `["lint", "npm test -- <a suite>"]` narrows the suite and
    still lints, because only one of those two entries has a scope that differs
    per task.

    QUOTED FOR THE SHELL THE GATE RUNS IN: `run-test-gate.py` hands each entry
    to a POSIX shell, so every substituted path goes in through `shlex.quote`
    -- an ordinary path comes back byte for byte, and one holding a space or a
    quote stays one word instead of splitting into two the runner cannot
    open. The sibling's own words come from `_phases.shell_words`, the same
    reader `gate_entry_paths` -- and so `path_scoped_sibling` -- uses, so a
    path it already quoted is recognized and replaced rather than copied
    through, and every word that is not a path keeps the exact spelling it
    had, quotes and operators included.
    """
    out = []
    for entry in entries:
        words = _phases.shell_words(entry)
        if is_shared_key(entry, build) or not any(
                _phases.shell_word_path(value) for _raw, value in words):
            out.append(entry)
            continue
        rebuilt, placed = [], False
        for raw, value in words:
            # `_phases` directly -- see the import note above: the filename
            # bound reached through `_manifest_rules`' re-export is the one
            # edge this module cannot afford without moving up a layer.
            if not _phases.shell_word_path(value):
                rebuilt.append(raw)
            elif not placed:
                rebuilt.extend(shlex.quote(p) for p in paths)
                placed = True
        out.append(" ".join(rebuilt))
    return out


# --- the newest red phase-scope row --------------------------------------------
def newest_red_phase_row(rows, phase_id):
    """The newest `scope: "phase"`, `status: "failed"` row for `phase_id`, or None.

    `_evidence_io.subject_key` is the one reading of "which row belongs to this
    phase" -- it refuses a row missing the id its own scope needs, the same
    filter `latest_by_subject` uses to decide what a pointer may name. `status`
    is added here because a phase whose newest run went green owes a derivation
    nothing further to narrow around: an OLD failure a later green run already
    superseded would understate a gate that has since been fixed.
    """
    best = None
    for row in (rows or []):
        if not isinstance(row, dict) or row.get("status") != "failed":
            continue
        if _evidence_io.subject_key(row) != ("phase", str(phase_id)):
            continue
        if best is None or str(row.get("ts") or "") >= str(best.get("ts") or ""):
            best = row
    return best


# --- the phase-level derivation --------------------------------------------------
# Pinned verbatim: the one sentence every NARROWED answer's basis carries,
# so a reader never has to guess whether a narrow gate came from more than the
# import graph and the recorded couplings -- and a widened version of it (one
# that also claimed, say, "and the files this phase touched") would be a claim
# this derivation cannot make, because `facts` never sees anything else.
BASIS_NARROWED = "selected by import graph and recorded couplings only"


def _touched_files(phase):
    """Every path any task in `phase` declares in `files`, in task/declaration
    order, deduplicated -- what the smoke arm and the coupling arm both ask
    "is every one of these exempt or a test" and "does this coupling's sources
    overlap" against.
    """
    out = []
    for task in (phase.get("tasks") or []):
        if not isinstance(task, dict):
            continue
        for path in (task.get("files") or []):
            if isinstance(path, str) and path not in out:
                out.append(path)
    return out


def _tests_add_arm(phase, build):
    """Every path a TASK'S OWN gate names, read through `_mio.gate_entries` so
    a task falling back to its PHASE's wide gate (source `"phase"`) never
    contributes a path here -- that fallback is the wide gate already, and
    reading it as evidence of a narrow one would be the derivation citing
    itself.
    """
    paths = []
    for task in (phase.get("tasks") or []):
        if not isinstance(task, dict):
            continue
        entries, source = _mio.gate_entries(phase, task)
        if source != "task":
            continue
        for entry in entries:
            if is_shared_key(entry, build):
                continue
            for path in _gate_entry_paths(entry):
                if path not in paths:
                    paths.append(path)
    return paths


def _coupling_arm(meta, touched):
    """Every `meta.coupling[].test` whose `sources` overlap `touched`, in
    declaration order. A coupling whose sources miss the phase's files adds
    nothing -- it was learned from a DIFFERENT change, and citing it here would
    narrow this phase's gate around evidence about another one.
    """
    touched_set = set(touched)
    out = []
    for entry in (meta.get("coupling") or []):
        if not isinstance(entry, dict):
            continue
        test = entry.get("test")
        sources = entry.get("sources")
        sources = sources if isinstance(sources, list) else []
        if (isinstance(test, str) and test.strip()
                and touched_set & set(sources) and test not in out):
            out.append(test)
    return out


def _full_listing_empty(facts):
    """True when `facts["fullListing"]` RAN, exited 0, and named ZERO suites.

    This is what makes `derived-empty` reachable at all (see `derive()`'s own
    note): `meta.phaseGate.derived.listing.all` is an ADDITIONAL shape source
    beside `path_scoped_sibling`, and unlike that one it CAN legitimately come
    back with nothing to narrow to -- an all-suites listing is free to name no
    suite (an empty project, a misspelled listing command). `full is None`
    (no listing configured, or it never ran) answers False, same as a listing
    that timed out or exited non-zero: none of those says "there is nothing to
    narrow to", only "this run cannot say".
    """
    full = facts.get("fullListing") if isinstance(facts, dict) else None
    full = full if isinstance(full, dict) else None
    if full is None or full.get("exit") != 0:
        return False
    paths = full.get("paths")
    return isinstance(paths, list) and len(paths) == 0


def _importers_arm(meta, facts):
    """`(paths, full, note)` for the importer-listing arm.

    FOUR THINGS HAVE TO HOLD before a listing is trusted at all: a listing has
    to be RECORDED (`meta.phaseGate.derived.listing`), the version command
    that was supposed to answer this machine's version has to have RUN AT ALL
    (a version command that cannot be run or exits non-zero is its own skip
    reason -- "the version command failed" -- never rendered as a machine
    answering `None`, which would read as an actual mismatched answer rather
    than as no answer at all), the machine asking has to answer the SAME
    version question the listing was verified against (a listing verified on
    one npm/node/etc answer is not evidence on another), and the
    listing itself has to have exited 0. Any of the four failing skips the arm
    with the reason named -- never an empty result read as "narrowed to
    nothing", and never a stale listing trusted in silence.

    EQUAL TO THE FULL LISTING MEANS THE WIDE GATE **IS** THE NARROW ANSWER:
    every suite the runner would collect imports something this phase
    touched, so there is nothing left to narrow away from and pretending
    otherwise would be a guess dressed as a derivation.

    A RELATED listing that named NONE while the ALL listing named SOME is its
    own printed reason too -- the arm contributes nothing, but silently (a
    `None` fallthrough) is indistinguishable from "nothing here to report",
    which is not what happened: the full listing found suites, the related one
    just did not name any of them.
    """
    gate = meta.get("phaseGate")
    gate = gate if isinstance(gate, dict) else {}
    derived = gate.get("derived")
    derived = derived if isinstance(derived, dict) else None
    if not derived or not isinstance(derived.get("listing"), dict):
        return [], False, None
    if facts.get("versionCheckFailed"):
        return [], False, "importers: skipped - the version command failed"
    verified_on = derived.get("verifiedOn")
    verified_on = verified_on if isinstance(verified_on, dict) else {}
    declared_answer = verified_on.get("answer")
    current_answer = facts.get("versionAnswer")
    if declared_answer != current_answer:
        return [], False, ("importers: skipped - listing verified on %s, this "
                           "machine answers %s" % (declared_answer, current_answer))
    listing = facts.get("listing")
    listing = listing if isinstance(listing, dict) else {}
    exit_code = listing.get("exit")
    if exit_code != 0:
        return [], False, "importers: skipped - listing exited %r" % (exit_code,)
    listed = [p for p in (listing.get("paths") or []) if isinstance(p, str)]
    full = facts.get("fullListing")
    full = full if isinstance(full, dict) else {}
    full_paths = [p for p in (full.get("paths") or []) if isinstance(p, str)]
    listed_set, full_set = set(listed), set(full_paths)
    if full_set and listed_set == full_set:
        return [], True, "DERIVED = FULL"
    if listed_set and full_set and listed_set < full_set:
        return listed, False, None
    if not listed_set and full_set:
        return [], False, ("importers: skipped - the related listing named no "
                           "suite while the full listing named %d"
                           % (len(full_set),))
    return [], False, None


def derive(manifest, phase, facts):
    """`{entries, basis, derived, narrowed, lines, shapeSource, attribution}`
    -- this phase's sign-off gate, computed the way `meta.phaseGate.mode`
    asks: only the part of the wide default that is NOT `meta.phaseGate
    .always` is ever replaced, and `meta.phaseGate.exclude` is read through
    `_phases.phase_gate_default` exactly once, so a fallback can never run
    fewer suites than `/audit:phase add` would already have written.

    `attribution` IS THE ONLY BREAKDOWN THIS PLUGIN COMPUTES, and it is
    `None` whenever `narrowed` is False -- EVERY wide basis, with no
    exception, including a full-suite resolution (`test_paths` at that point
    is real, but it is not what the wide gate runs, so reporting it as a
    breakdown would print a narrowed-looking count for a gate that is not
    narrowed). A second, independent computation of these same arms does not
    know every widening trigger this function knows -- a new trigger added
    here and not there reports a narrowed-looking breakdown for a gate that
    is actually wide, which is why `derive-phase-gate.py` no longer computes
    one: `attribution` is part of THIS function's own return, `{testsAdd,
    coupling, importers, changed, lastFailed, union}` only when `narrowed`
    is True, and a caller renders ONLY off this dict -- `narrowed` and
    `basis` decide what a WIDE result means (`derived-empty`'s two triggers,
    a full-suite resolution, `phase-no-spelling`), never `attribution`'s
    presence, which is now the same fact stated a second way.

    `facts` is the ONLY place an observation may arrive from: `listing` /
    `fullListing` (each `{exit, paths}`), `versionAnswer` (this machine's
    answer to the same question `meta.phaseGate.derived.verifiedOn` recorded),
    `changedSince` (paths changed since `phase.baseRef`), `lastFailedSuites`
    (the newest red phase-scope row's NAMED failures, already filtered to a
    `failingSuitesBasis` that says the runner named them), and `exempt` (the
    plan gate's exempt verdict, keyed by path). No argument here ever shells
    out or reads git -- that is the caller's job, once, before this runs.

    `_manifest_vocab.PHASE_GATE_BASIS[1]` ("derived-empty") IS reachable, from
    TWO triggers, both widening the WHOLE derivation before entries are built
    and both rendered from the SAME `basis` word by a caller, so an operator
    reading the human line never has to know which trigger fired to trust
    what it says: `meta.phaseGate.derived.listing.all` is an ADDITIONAL shape
    source beside `resolve_shape`'s, and it CAN legitimately come back with
    nothing to narrow to (an all-suites listing is free to name no suite at
    all) -- caught by `_full_listing_empty` right after the shape is resolved,
    before coupling/importers/changed/last-failed ever run. The SECOND
    trigger is `resolve_shape`'s own SPELLING source: unlike the SIBLING
    source (the same task that supplies it necessarily contributes at least
    one path to `_tests_add_arm` through the identical read
    `path_scoped_sibling` used to find it, so a sibling-sourced shape and
    `test_paths == []` cannot both hold), a spelling-sourced shape carries no
    such guarantee -- no task's own gate backs it. So AFTER every arm
    (tests.add, coupling, importers, changed, last-failed) has had its turn,
    an empty `test_paths` on the spelling source widens too, with its own
    reason ("spelling: nothing to substitute...") rather than substituting
    `{paths}` with nothing: depending on the runner, an empty `pytest ` or
    `vitest run ` means either the WHOLE suite or NOTHING, and either reading
    would make the gate mean something other than what it prints. Both
    triggers return `attribution: None` -- there is nothing to attribute a
    path to when the whole point of the trigger is that no arm found one.
    """
    meta = manifest.get("meta") if isinstance(manifest, dict) else None
    meta = meta if isinstance(meta, dict) else {}
    phase = phase if isinstance(phase, dict) else {}
    facts = facts if isinstance(facts, dict) else {}

    default = _phases.phase_gate_default(meta)
    always = list(default["always"])

    gate = meta.get("phaseGate")
    gate = gate if isinstance(gate, dict) else {}
    mode = gate.get("mode")
    if mode not in _phases.PHASE_GATE_MODES:
        # ABSENT MEANS NO DERIVATION. The wide default is the whole answer, and
        # `derived: False` says so as data rather than leaving a reader to infer
        # it from `basis` alone.
        return {"entries": list(default["entries"]),
                "basis": "meta.phaseGate.mode is not set - no derivation",
                "derived": False, "narrowed": False, "lines": [],
                "shapeSource": None, "attribution": None}

    build = meta.get("buildCommands")
    build = build if isinstance(build, dict) else None
    derived_cfg = gate.get("derived")
    shape, shape_source, lines = resolve_shape(phase, build, derived_cfg)
    if shape is None:
        return {"entries": always + list(default["rest"]),
                "basis": "phase-no-spelling", "derived": True,
                "narrowed": False, "lines": lines, "shapeSource": None,
                "attribution": None}

    if _full_listing_empty(facts):
        # BEFORE ANYTHING ELSE RUNS: an ALL listing that ran, exited 0 and
        # named no suite is not evidence of anything narrower -- widen with
        # the reason printed rather than let coupling/importers/changed/
        # last-failed run against a listing that already said "nothing".
        return {"entries": always + list(default["rest"]),
                "basis": _vocab.PHASE_GATE_BASIS[1], "derived": True,
                "narrowed": False,
                "lines": lines + ["derived-empty: the ALL listing ran, "
                                  "exited 0 and named no suite - nothing to "
                                  "narrow to, widening"],
                "shapeSource": None, "attribution": None}

    touched = _touched_files(phase)
    tests_add = _tests_add_arm(phase, build)
    test_paths = list(tests_add)
    coupling_new = []
    for path in _coupling_arm(meta, touched):
        if path not in test_paths:
            coupling_new.append(path)
            test_paths.append(path)

    importer_paths, full_suite, importer_note = _importers_arm(meta, facts)
    if importer_note:
        lines.append(importer_note)
    if full_suite:
        # SAME RULE AS EVERY OTHER WIDE BASIS: `narrowed` is False here, so
        # `attribution` is `None` here too -- `test_paths` at this point (the
        # union of `tests.add` and coupling, BEFORE the importer/changed/
        # last-failed loops even run) is not what the wide gate runs, and a
        # caller reporting it as a per-arm breakdown would be printing a
        # narrowed-looking count for a gate that is not narrowed. What IS
        # measured for this basis -- the related listing's count and the full
        # listing's count -- lives in `facts`, which the caller already has;
        # this function is not the one to duplicate it into `attribution`.
        return {"entries": always + list(default["rest"]),
                "basis": _vocab.PHASE_GATE_BASIS[2],
                "derived": True, "narrowed": False, "lines": lines,
                "shapeSource": None, "attribution": None}
    importer_new = []
    for path in importer_paths:
        if path not in test_paths:
            importer_new.append(path)
            test_paths.append(path)

    changed_new = []
    for path in (facts.get("changedSince") or []):
        if (isinstance(path, str) and _phases.is_suite_path(path)
                and path not in test_paths):
            changed_new.append(path)
            test_paths.append(path)
    last_failed_new = []
    for path in (facts.get("lastFailedSuites") or []):
        if isinstance(path, str) and path not in test_paths:
            last_failed_new.append(path)
            test_paths.append(path)

    # NO "test_paths == []" GUARD HERE for the SIBLING-sourced shape, on
    # purpose: a sibling's own gate already contributed at least one path to
    # `test_paths` through `_tests_add_arm` (the identical read
    # `path_scoped_sibling` used to find the shape in the first place), so
    # this point in the function can never be reached with an empty set on
    # THAT source -- a branch written for it would be dead code no case here
    # could ever prove red. The SPELLING-sourced shape carries no such
    # guarantee (no task's own gate backs it), so IT gets the guard: an empty
    # `test_paths` there would substitute `{paths}` with nothing, and
    # depending on the runner an empty `pytest ` or `vitest run ` means either
    # the WHOLE suite or NOTHING -- either way a gate that silently means
    # something other than what it prints, which the phase's own rule forbids
    # (nothing narrows unless it is declared and printed; anything unbounded
    # turns wide with the reason printed).
    if shape_source == SPELLING_SOURCE and not test_paths:
        return {"entries": always + list(default["rest"]),
                "basis": _vocab.PHASE_GATE_BASIS[1], "derived": True,
                "narrowed": False,
                "lines": lines + ["spelling: nothing to substitute - no arm "
                                  "named a test path, so the wide gate runs"],
                "shapeSource": None, "attribution": None}

    entries = list(always)
    if shape_source == SPELLING_SOURCE:
        # LITERAL SUBSTITUTION, never `repointed()`: the schema's own
        # `{paths}` placeholder is not a path-shaped TOKEN `repointed()` would
        # recognize (`_gate_entry_paths` only counts tokens that already look
        # like a file), so the template is filled directly with the resolved,
        # shell-quoted test paths -- the same mechanic
        # `derive-phase-gate.py._gather_facts` uses for a listing command.
        quoted = " ".join(shlex.quote(p) for p in test_paths)
        spelled = shape[0].replace("{paths}", quoted)
        if spelled not in entries:
            entries.append(spelled)
    else:
        for entry in repointed(shape, build, test_paths):
            if entry not in entries:
                entries.append(entry)

    smoke = gate.get("smoke")
    if isinstance(smoke, str) and smoke.strip():
        exempt = facts.get("exempt")
        exempt = exempt if isinstance(exempt, dict) else {}
        # NEVER DECIDED BY `meta.runtimeBoot.appRootPath`: the ONLY
        # questions asked of a touched file are whether the plan gate's own
        # exempt verdict already cleared it and whether it is a test file
        # itself -- a source file outside an app's own root is still a source
        # file, and reading the prefix here would be a second, silently
        # different rule about what "this phase's own work" means.
        if touched and all(_phases.is_suite_path(f) or exempt.get(f)
                           for f in touched):
            lines.append("smoke: skipped - every file this phase touched is "
                         "docs or tests")
        elif smoke not in entries:
            entries.append(smoke)

    return {"entries": entries, "basis": BASIS_NARROWED, "derived": True,
            "narrowed": True, "lines": lines, "shapeSource": shape_source,
            "attribution": {"testsAdd": tests_add, "coupling": coupling_new,
                           "importers": importer_new, "changed": changed_new,
                           "lastFailed": last_failed_new,
                           "union": list(test_paths)}}


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
        print("_gate_derive.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__gate_derive.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
