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
    """
    out = []
    for entry in entries:
        if is_shared_key(entry, build) or not _gate_entry_paths(entry):
            out.append(entry)
            continue
        rebuilt, placed = [], False
        for token in entry.split():
            # `_phases.tests_add_path` directly -- see the import note above:
            # `_manifest_rules.tests_add_path` is the same function reached
            # through a re-export, and reaching it that way is the one edge
            # this module cannot afford without moving up a layer.
            if not _phases.tests_add_path(token):
                rebuilt.append(token)
            elif not placed:
                rebuilt.extend(paths)
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
# Pinned verbatim (dg4): the one sentence every NARROWED answer's basis carries,
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


def _importers_arm(meta, facts):
    """`(paths, full, note)` for the importer-listing arm.

    THREE THINGS HAVE TO HOLD before a listing is trusted at all: a listing has
    to be RECORDED (`meta.phaseGate.derived.listing`), the machine asking has to
    answer the SAME version question the listing was verified against (dg23 --
    a listing verified on one npm/node/etc answer is not evidence on another),
    and the listing itself has to have exited 0. Any of the three failing skips
    the arm with the reason named -- never an empty result read as "narrowed to
    nothing", and never a stale listing trusted in silence.

    EQUAL TO THE FULL LISTING MEANS THE WIDE GATE **IS** THE NARROW ANSWER
    (dg1): every suite the runner would collect imports something this phase
    touched, so there is nothing left to narrow away from and pretending
    otherwise would be a guess dressed as a derivation.
    """
    gate = meta.get("phaseGate")
    gate = gate if isinstance(gate, dict) else {}
    derived = gate.get("derived")
    derived = derived if isinstance(derived, dict) else None
    if not derived or not isinstance(derived.get("listing"), dict):
        return [], False, None
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
    return [], False, None


def derive(manifest, phase, facts):
    """`{entries, basis, derived, narrowed, lines}` -- this phase's sign-off
    gate, computed the way `meta.phaseGate.mode` asks: only the part of the
    wide default that is NOT `meta.phaseGate.always` is ever replaced, and
    `meta.phaseGate.exclude` is read through `_phases.phase_gate_default`
    exactly once, so a fallback can never run fewer suites than
    `/audit:phase add` would already have written.

    `facts` is the ONLY place an observation may arrive from: `listing` /
    `fullListing` (each `{exit, paths}`), `versionAnswer` (this machine's
    answer to the same question `meta.phaseGate.derived.verifiedOn` recorded),
    `changedSince` (paths changed since `phase.baseRef`), `lastFailedSuites`
    (the newest red phase-scope row's NAMED failures, already filtered to a
    `failingSuitesBasis` that says the runner named them), and `exempt` (the
    plan gate's exempt verdict, keyed by path). No argument here ever shells
    out or reads git -- that is the caller's job, once, before this runs.

    `_manifest_vocab.PHASE_GATE_BASIS[1]` ("derived-empty") is NOT a basis this
    function ever returns, and that is deliberate rather than an oversight: the
    only `shape` this function knows how to find is `path_scoped_sibling`'s --
    a TASK's own path-scoped gate -- and the same task that supplies `shape`
    necessarily contributes at least one path to `_tests_add_arm` through the
    identical read (`_mio.gate_entries` resolves that task's gate the same way
    `path_scoped_sibling` inspected it). So `shape is not None` and
    `test_paths == []` cannot both hold here; a branch written for that
    combination would be dead code no case could ever prove. The word stays
    reserved for a CALLER whose shape source can legitimately return zero
    paths without a task's own gate backing it -- `derive-phase-gate.py`
    (P79.3), if `meta.phaseGate.derived.runner`/`.spelling` ever becomes an
    alternate shape (a recorded runner + a `{paths}` template, independent of
    any task) and its importers listing comes back empty. That caller decides
    when to write `derived-empty`; this function does not guess at it.
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
                "derived": False, "narrowed": False, "lines": []}

    build = meta.get("buildCommands")
    build = build if isinstance(build, dict) else None
    shape, owner = path_scoped_sibling(phase, build)
    if shape is None:
        return {"entries": always + list(default["rest"]),
                "basis": "phase-no-spelling", "derived": True,
                "narrowed": False, "lines": []}

    lines = []
    touched = _touched_files(phase)
    test_paths = _tests_add_arm(phase, build)
    for path in _coupling_arm(meta, touched):
        if path not in test_paths:
            test_paths.append(path)

    importer_paths, full_suite, importer_note = _importers_arm(meta, facts)
    if importer_note:
        lines.append(importer_note)
    if full_suite:
        return {"entries": always + list(default["rest"]),
                "basis": _vocab.PHASE_GATE_BASIS[2],
                "derived": True, "narrowed": False, "lines": lines}
    for path in importer_paths:
        if path not in test_paths:
            test_paths.append(path)

    for path in (facts.get("changedSince") or []):
        if (isinstance(path, str) and _phases.is_suite_path(path)
                and path not in test_paths):
            test_paths.append(path)
    for path in (facts.get("lastFailedSuites") or []):
        if isinstance(path, str) and path not in test_paths:
            test_paths.append(path)

    # NO "test_paths == []" FALLBACK HERE, on purpose -- see the module
    # docstring's note on `_manifest_vocab.PHASE_GATE_BASIS[1]`
    # ("derived-empty"): `shape` (above) can only be non-None when some task's
    # own gate already contributed at least one path to `test_paths`, so this
    # point in the function can never be reached with an empty set. A branch
    # written for it would be dead code no case here could ever prove red.

    entries = list(always)
    for entry in repointed(shape, build, test_paths):
        if entry not in entries:
            entries.append(entry)

    smoke = gate.get("smoke")
    if isinstance(smoke, str) and smoke.strip():
        exempt = facts.get("exempt")
        exempt = exempt if isinstance(exempt, dict) else {}
        # NEVER DECIDED BY `meta.runtimeBoot.appRootPath` (dg10): the ONLY
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
            "narrowed": True, "lines": lines}


# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exiting silently: `--selftest` is what every other
        # file here accepts, so nothing would tell a reader whether this one ran
        # nothing or has nothing. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_gate_derive.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__gate_derive.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
