#!/usr/bin/env python3
"""
Every referential rule the audit manifest is held to, and nothing that prints.

Complements the JSON Schema (schema/audit-plan.schema.json) with the referential
checks a schema cannot express: unique ids, resolvable blockedBy/dependsOn,
dependency CYCLES, fileIndex integrity in BOTH directions, and reciprocal
bugs[] <-> task.bugId cross-links. Commands run it after EVERY manifest
mutation (the Edit-and-revalidate rule in reference/manifest-conventions.md).

WHY THIS IS NOT `validate-manifest.py` ANY MORE. It was, and the split is the
whole point: FOUR modules needed these rules and only one of them is a command.
`_panel_state`, `audit-doctor`, `audit-status` and `migrate-manifest` each
reached the validator the only way a hyphenated entry point can be reached —
`_loader.load_script("validate-manifest.py")` — and `_deps.layer_violations()`
reads those calls as real edges, so four of them stood in `KNOWN_LAYER_DEBT`: an
L5 helper and three L7 commands all pointing at an L7 peer. Extracting the CALL
would have laundered them behind a new module that shells out; extracting the
RULES retires them, because each of those four now spells a plain
`import _manifest_rules` and there is no upward edge left to record.

WHAT THIS FILE IS NOW: THE ORDER, AND THE PUBLIC SURFACE. It was 1,406 lines,
and the size was the symptom rather than the fault — five unrelated subjects
shared one file because `validate()` calls all five. They are five modules now,
cut where the file's own section markers already cut it:

  `_manifest_vocab`      L1  the words, and the shape checks every level shares
  `_manifest_phases`     L2  the one walk over phases and tasks, and what a
                             phase carries (claim, area tag, budget, sign-off)
  `_manifest_ado`        L2  `meta.ado`, the connector config — ONE front door,
                             shared with the panel's PUT /api/ado
  `_manifest_typos`      L2  the did-you-mean detectors (model ids, skill names)
  `_manifest_crossrefs`  L2  every question about how one part REFERS to another

What is left here is the one thing that could not go into a piece: `validate()`
decides the ORDER, and the order is not arbitrary — `_walk_phases` builds the
index the five checks after it read, so it runs once and first. `_check_meta`
stayed with it because the root object's key vocabulary and `meta` are the
document's HEADER: they need nothing the walk builds, and they are what decides
whether the rest is worth walking.

AND THE NAMES. Every name those five modules hold is re-exported here, as a thin
module-level alias rather than a copy, because this module is what four
consumers and two suites import. `render-report.py` keeps a dozen aliases for
the same reason; the alternative was making every caller learn which of five
files a rule now sits in, for a rule that has not changed.

This module moved from layer 2 to layer 3, and that is the whole structural cost
of the split: the four pieces at layer 2 sit above `_manifest_vocab` at layer 1,
so their only consumer has to sit above them. Nothing at layer 3 imports this
and this imports nothing at layer 3, so the move is free.

Pure by construction: `validate()` takes parsed JSON and returns
`(findings, warnings)`, never raises on arbitrary input, reads no file and holds
no module state. That is what lets four consumers share it without sharing a
process, and it is why the cases below need no fixture directory.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__manifest_rules.py` — see `plugins/audit/tests/_harness.py`.
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

import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR index+shards)
import _manifest_vocab as _vocab  # noqa: E402  (the words, and the shared shape checks)
import _manifest_phases as _phases  # noqa: E402  (the one walk, and what a phase carries)
import _manifest_ado as _ado  # noqa: E402  (meta.ado: the connector config, one front door)
import _manifest_typos as _typos  # noqa: E402  (the did-you-mean detectors)
import _manifest_crossrefs as _crossrefs  # noqa: E402  (ids, refs, cycles, fileIndex, bugs)
import _branch as _branch  # noqa: E402  (where a phase branches from, and its name)

# --- the re-exported surface ------------------------------------------------------
# ALIASES, NOT COPIES. Each name below is the SAME object the module beside it
# defines, so there is one definition of every rule and one table of every word.
# They exist because this module is the import four consumers and two suites
# already spell, and a split that made each of them learn which of five files a
# rule moved to would be charging the callers for a change they did not ask for.
# `tests/test__manifest_rules.py` pins the identity of the whole set with `is`,
# so a re-export that forks into a second definition fails by name.
STATUS = _vocab.STATUS
TESTS_MODE = _vocab.TESTS_MODE
RISK = _vocab.RISK
BUG_STATUS = _vocab.BUG_STATUS
BUG_ID_RE = _vocab.BUG_ID_RE
PROPOSAL_STATUS = _vocab.PROPOSAL_STATUS
PROP_ID_RE = _vocab.PROP_ID_RE
KNOWN_ROOT = _vocab.KNOWN_ROOT
KNOWN_META = _vocab.KNOWN_META
KNOWN_BRANCH = _vocab.KNOWN_BRANCH
KNOWN_ADO = _vocab.KNOWN_ADO
KNOWN_PHASE = _vocab.KNOWN_PHASE
CLAIM_KEYS = _vocab.CLAIM_KEYS
KNOWN_TASK = _vocab.KNOWN_TASK
KNOWN_BUG = _vocab.KNOWN_BUG
KNOWN_PROPOSAL = _vocab.KNOWN_PROPOSAL
_strip_line_suffix = _vocab._strip_line_suffix
_safe_list = _vocab._safe_list
_require_fields = _vocab._require_fields
_check_ado = _vocab._check_ado
_unknown_keys = _vocab._unknown_keys

# `TERMINAL` is `_manifest_io`'s and is re-exported from here rather than from
# `_manifest_vocab`: holding it there would give that module an import and put it
# at layer 2, which is the one layer its four consumers need to occupy.
TERMINAL = _mio.TERMINAL

_check_claim = _phases._check_claim
_check_area_tag = _phases._check_area_tag
_check_areas = _phases._check_areas
_walk_phases = _phases._walk_phases

_check_identity_map = _ado._check_identity_map
check_ado_meta = _ado.check_ado_meta

_model_near_miss = _typos._model_near_miss
_check_model_typos = _typos._check_model_typos
_skills_in_use = _typos._skills_in_use
_check_skills = _typos._check_skills
_skill_near_miss = _typos._skill_near_miss
_check_skill_typos = _typos._check_skill_typos

_cycle_findings = _crossrefs._cycle_findings
_index_bugs = _crossrefs._index_bugs
_live_ids = _crossrefs._live_ids
_check_unique_ids = _crossrefs._check_unique_ids
_ref_findings = _crossrefs._ref_findings
_check_refs_and_cycles = _crossrefs._check_refs_and_cycles
_check_file_index = _crossrefs._check_file_index
_check_bugs = _crossrefs._check_bugs
_check_proposals = _crossrefs._check_proposals


# --- the document's header --------------------------------------------------------
def _check_meta(manifest):
    """The document's header: the ROOT object's key vocabulary, and `meta`.

    Both live here because they answer one question — is this file's outermost
    layer the shape the orchestrator reads — and neither needs anything the
    phase walk builds, so this piece runs before it and depends on nothing.
    """
    f, w = [], []
    _unknown_keys(manifest, KNOWN_ROOT, "manifest root", w)

    meta = manifest.get("meta")
    if not isinstance(meta, dict):
        f.append("meta: missing or not an object")
        return (f, w)

    _unknown_keys(meta, KNOWN_META, "meta", w)
    version = meta.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        # bool is an int subclass in Python — `true` must NOT pass as a version.
        f.append("meta.version: missing or not an integer")
    # meta.ado: the whole connector config goes through check_ado_meta --
    # the ONE front door shared with the panel's write_ado, so the CLI
    # and the panel cannot disagree. (It keeps F-C-1's object-or-null rule
    # and folds in _check_identity_map.)
    if "ado" in meta:
        af, aw = check_ado_meta(meta.get("ado"))
        f.extend(af)
        w.extend(aw)
    return (f, w)


# --- the branch convention ---------------------------------------------------------
def _check_branch(manifest):
    """Would this manifest's own convention produce branches git accepts?

    The interesting failure is not a malformed config — it is a WELL-FORMED one
    that yields an illegal ref for a particular phase title, which surfaces at
    `git switch -c` in the middle of a run rather than here. So the check does not
    inspect the template in the abstract: it composes the name for EVERY phase and
    asks `_branch.ref_violations` about the result.

    A `branchType` outside `meta.branch.types` is a WARNING, not a finding: the
    branch is still legal and the run still works. What it costs is the
    pre-approval glob (`reference/orchestrator.md` -> Branch operations), so the
    consequence is a permission prompt on every branch operation — worth saying,
    not worth refusing a manifest over.
    """
    f, w = [], []
    meta = manifest.get("meta")
    if not isinstance(meta, dict):
        return (f, w)                      # _check_meta already said so

    blk = meta.get("branch")
    if blk is not None and not isinstance(blk, dict):
        f.append("meta.branch: not an object")
        return (f, w)
    if isinstance(blk, dict):
        _vocab._unknown_keys(blk, KNOWN_BRANCH, "meta.branch", w)
        tmpl = blk.get("template")
        if tmpl is not None and not isinstance(tmpl, str):
            f.append("meta.branch.template: not a string")
            return (f, w)
        # A placeholder nobody substitutes expands to nothing and takes a
        # separator with it — a shorter name than the author meant, and silent.
        for ph in re.findall(r"\{([a-zA-Z]+)\}", str(tmpl or "")):
            if ph not in _branch.PLACEHOLDERS:
                w.append("meta.branch.template: unknown placeholder '{%s}' - it "
                         "expands to nothing and collapses the separator with it; "
                         "known: %s"
                         % (ph, ", ".join("{%s}" % k for k in _branch.PLACEHOLDERS)))

    cfg = _branch.config(meta)
    for phase in (manifest.get("phases") or []):
        if not isinstance(phase, dict):
            continue
        pid = phase.get("id")
        kind = phase.get("branchType")
        if kind and str(kind) not in cfg["types"]:
            w.append("phases[%s].branchType %r is not in meta.branch.types - the "
                     "branch still works, but it is outside the pre-approved "
                     "globs, so every branch operation on it asks for "
                     "confirmation" % (pid, str(kind)))
        # The composed name, which is the thing git will actually be handed.
        name = _branch.compose(meta, phase, initials="x y")["name"]
        bad = _branch.ref_violations(name)
        if bad:
            f.append("phases[%s]: the branch name this manifest would produce "
                     "(%r) is not a legal git ref: %s"
                     % (pid, name, "; ".join(bad)))
    return (f, w)


# --- validate: one walk, then one question per piece ------------------------------
# `validate()` was 354 lines, and its size was never the reason it was hard to
# cut. The reason was the INDEX: seven accumulating locals built by one pass over
# the phases and read afterwards by four checks that have nothing else in common.
# Naming that index is the whole trick — each piece below takes it, answers one
# question, and returns its OWN (findings, warnings) instead of writing into the
# caller's lists. One contract for every direct child of `validate()`, so a piece
# can be called from a case with a hand-built index and no accumulators to
# inspect afterwards, and so no two of them can quietly depend on running order.
# That contract is also what let the pieces move into five files without any of
# them growing an argument or losing one.
def validate(manifest):
    """Return (findings, warnings) — two lists of strings; empty findings = valid.

    ORCHESTRATION ONLY. Every question lives in a piece above that answers it
    and returns its own pair; this decides the ORDER, which is the one thing
    that cannot live in a piece. The order is not arbitrary: `_walk_phases`
    builds the index the four checks after it read, so it runs once and first.

    Findings and warnings each keep the order they were produced in — the CLI
    prints them in that order and a reader walks the file top-down against it.
    """
    f, w = [], []
    if not isinstance(manifest, dict):
        return (["manifest root must be a JSON object"], w)

    def add(pair):
        """Fold one piece's (findings, warnings) into the two answers."""
        f.extend(pair[0])
        w.extend(pair[1])

    add(_check_meta(manifest))
    add(_check_branch(manifest))
    add(_check_areas(manifest))

    phases = manifest.get("phases")
    if not isinstance(phases, list):
        f.append("phases: missing or not an array")
        phases = []

    index, walk_f, walk_w = _walk_phases(phases)
    f.extend(walk_f)
    w.extend(walk_w)
    index.update(_index_bugs(manifest))

    add(_check_unique_ids(index))
    add(_check_refs_and_cycles(phases, index))
    add(_check_model_typos(manifest))
    add(_check_skills(manifest))
    add(_check_skill_typos(manifest))
    add(_check_file_index(manifest, index))
    add(_check_bugs(manifest, index))
    add(_check_proposals(manifest, index))
    return (f, w)


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
        print("_manifest_rules.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__manifest_rules.py - run that file "
              "instead.")
        sys.exit(0)
    print(__doc__.strip())
