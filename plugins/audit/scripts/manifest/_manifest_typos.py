#!/usr/bin/env python3
"""
The did-you-mean detectors: a model id or a skill name used once, one slip from
one used often.

Split out of `_manifest_rules.py`. Both detectors answer the same question over
two different vocabularies, and neither has anything to do with the referential
rules the rest of the validator enforces - a near miss is not a structural
defect, it is a guess about intent, which is why every line either of them
emits is a WARNING and `findings` is always empty.

WHY A ONE-SLIP MODEL ID IS WORTH SAYING AT ALL. It routes work to a model
nobody priced or intended, and nothing else in the pipeline notices: the
orchestrator passes the string through, the ledger records what came back, and
the spend lands under a name that appears once. Same for a skill name - a
one-slip name names a skill that never loads, silently.

DELIBERATELY INTRA-MANIFEST. This validator is an offline shape-checker with no
config, no ledger and no discovery inventory in hand, so "is this a real model"
and "is this an installed skill" are the panel's questions (it has all three
sources) and not this module's.

The two near-miss predicates differ by exactly one rule, and the difference is
about false positives rather than about taste: `_skill_near_miss` allows two
edits, but only on names of six characters or more, because on short names two
edits turn one real word into another ('web' -> 'wasm') and every hit would be
noise.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__manifest_typos.py` - see
`plugins/audit/tests/_harness.py`.
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

import _areas  # noqa: E402  (meta.areas registry - where an area's default skills live)
import _manifest_vocab as _vocab  # noqa: E402  (the words, and the shared shape checks)

# A thin module-level alias, not a copy: the bodies below were moved out of
# `_manifest_rules.py` unchanged. A case pins that this is the same object.
_safe_list = _vocab._safe_list


# --- model ids -------------------------------------------------------------------
def _model_near_miss(a, b):
    """True iff two model ids are one slip apart: case-insensitively equal but
    spelled differently, or one substitution, insertion, deletion or ADJACENT
    TRANSPOSITION away (case-insensitive) -- the four classic typo shapes."""
    if a == b:
        return False
    x, y = a.lower(), b.lower()
    if x == y:
        return True
    if abs(len(x) - len(y)) > 1:
        return False
    if len(x) == len(y):
        diffs = [i for i, (cx, cy) in enumerate(zip(x, y)) if cx != cy]
        if len(diffs) == 1:
            return True
        return (len(diffs) == 2 and diffs[1] == diffs[0] + 1
                and x[diffs[0]] == y[diffs[1]] and x[diffs[1]] == y[diffs[0]])
    short, long_ = (x, y) if len(x) < len(y) else (y, x)
    i = j = 0
    skipped = False
    while i < len(short):
        if short[i] == long_[j]:
            i += 1
            j += 1
            continue
        if skipped:
            return False
        skipped = True
        j += 1
    return True


def _check_model_typos(manifest):
    """Intra-manifest model-id near-miss detector (WARNING only).

    Returns (findings, warnings) — findings is ALWAYS empty, and the pair is
    still the shape, because every direct child of `validate()` answers the
    same way and a detector that grows a hard rule later should not change its
    signature to say so. Converted from taking the `warnings` list.

    Flags a model value that is used EXACTLY ONCE while a case-insensitive or
    edit-distance-1 neighbour is used elsewhere in the manifest, or appears
    among meta.usage.pricing keys when that table exists. A spelling used
    twice or more is an established choice, never flagged; a clean
    single-model manifest has no neighbour to near-miss and stays silent.

    Deliberately intra-manifest: this validator is an offline shape-checker
    (no config, no ledger — see validate()), so the three-source model hint
    (manifest vs rate table vs ledger) lives in the panel, which has all three
    in hand.
    """
    warnings = []
    sites = {}   # model value -> [where, ...] in document order

    def note_use(val, where):
        if isinstance(val, str) and val.strip():
            sites.setdefault(val, []).append(where)

    phases = manifest.get("phases") if isinstance(manifest, dict) else None
    for pi, phase in enumerate(_safe_list(phases)):
        if not isinstance(phase, dict):
            continue
        pwhere = "phase %s" % (phase.get("id") or ("phases[%d]" % pi))
        note_use(phase.get("model"), pwhere)
        review = phase.get("review")
        if isinstance(review, dict):
            note_use(review.get("model"), pwhere + " review")
        for ti, task in enumerate(_safe_list(phase.get("tasks"))):
            if isinstance(task, dict):
                note_use(task.get("model"), "task %s"
                         % (task.get("id") or ("%s.tasks[%d]" % (pwhere, ti))))

    pricing = []
    meta = manifest.get("meta") if isinstance(manifest, dict) else None
    if isinstance(meta, dict) and isinstance(meta.get("usage"), dict) \
            and isinstance(meta["usage"].get("pricing"), dict):
        pricing = [k for k in meta["usage"]["pricing"]
                   if isinstance(k, str) and not k.startswith("_")]

    for val in sorted(sites):
        if len(sites[val]) != 1:
            continue
        near = None
        # Prefer the most-used neighbour (the established spelling), then the
        # pricing table, so the warning names the likeliest intended id.
        for other in sorted(sites, key=lambda v: (-len(sites[v]), v)):
            if other != val and len(sites[other]) > 1 \
                    and _model_near_miss(val, other):
                near = (other, "used %d times elsewhere in this manifest"
                        % len(sites[other]))
                break
        if near is None:
            for key in sorted(pricing):
                if key != val and _model_near_miss(val, key):
                    near = (key, "a meta.usage.pricing key")
                    break
        if near is None:
            for other in sorted(sites):
                if other != val and len(sites[other]) == 1 \
                        and _model_near_miss(val, other):
                    near = (other, "used once at %s" % sites[other][0])
                    break
        if near is not None:
            warnings.append(
                "%s: model '%s' is used once and is a near-miss of '%s' (%s) "
                "-- a one-slip model id routes work to a model nobody priced "
                "or intended" % (sites[val][0], val, near[0], near[1]))
    return ([], warnings)


# --- skill names -----------------------------------------------------------------
def _skills_in_use(manifest):
    """True iff the manifest uses executor skills DELIBERATELY, anywhere.

    Evidence: a task whose `skills` key holds a non-empty list, an explicit
    null (the opt-out is use), or a wrong-typed value (someone tried); or a
    registered area declaring a non-empty default list. `skills: []` alone is
    NOT evidence -- generators initialize empty lists on every task, and a
    project that ignores the feature must get zero new warnings from it."""
    if not isinstance(manifest, dict):
        return False
    for phase in _safe_list(manifest.get("phases")):
        if not isinstance(phase, dict):
            continue
        for task in _safe_list(phase.get("tasks")):
            if isinstance(task, dict) and "skills" in task:
                v = task.get("skills")
                if v is None or (isinstance(v, list) and v) \
                        or not isinstance(v, list):
                    return True
    for entry in _areas.registry(manifest).values():
        v = entry.get("skills")
        if isinstance(v, list) and v:
            return True
    return False


def _check_skills(manifest):
    """Unresolved-skills advisory (v0.37 B2). WARNING only, never a finding.

    Returns (findings, warnings) — findings is always empty; see
    `_check_model_typos` for why the pair is still the shape. Converted from
    taking the `warnings` list.

    A task whose RESOLVED skills are empty while the manifest uses skills
    elsewhere is usually an oversight -- the executor for that one task loads
    no conventions while its siblings do. The warning names what was consulted
    (the task's own value, the phase's areas) and the three exits: set
    task.skills, register defaults on an area, or write `"skills": null` to
    say 'none applies' -- the explicit opt-out that stops the area fallback
    and this warning with it (_areas.skills_opted_out).

    GATED on _skills_in_use: a manifest that never touches the feature gets
    zero new lines, which is the whole back-compat contract here."""
    warnings = []
    if not _skills_in_use(manifest):
        return ([], warnings)
    for phase in _safe_list(manifest.get("phases")):
        if not isinstance(phase, dict):
            continue
        tags = _areas.areas_of(phase.get("area"))
        for task in _safe_list(phase.get("tasks")):
            if not isinstance(task, dict):
                continue
            twhere = "task %s" % (task.get("id") or "?")
            if _areas.skills_opted_out(task):
                continue
            tv = task.get("skills")
            if "skills" in task and not isinstance(tv, list):
                # tv is not None here: null is the opt-out, handled above.
                warnings.append("%s: skills must be an array of skill names or "
                                "null, got %s -- resolution loads nothing "
                                "from it" % (twhere, type(tv).__name__))
            if _areas.resolve_skills(manifest, phase, task):
                continue
            if "skills" not in task:
                tpart = "task has no skills key"
            elif isinstance(tv, list):
                tpart = ("task skills []" if not tv
                         else "task skills list no usable name")
            else:
                tpart = "task skills is not a list"
            apart = ("phase has no area tag" if not tags
                     else "area(s) %s declare none" % ", ".join(tags))
            warnings.append(
                "%s: no skills resolve (%s; %s) -- set task.skills, register "
                "default skills on an area in meta.areas, or write "
                "\"skills\": null to say 'none applies'"
                % (twhere, tpart, apart))
    return ([], warnings)


def _skill_near_miss(a, b):
    """True iff two skill names are one slip apart, or two on names long
    enough to carry them.

    One slip is _model_near_miss verbatim (case-only difference, one
    substitution/insertion/deletion, adjacent transposition). Two slips are
    allowed only when BOTH names are 6+ characters: on short names two edits
    can turn one real word into another ('web' -> 'wasm' is distance 2) and
    every hit would be noise -- the same false-positive discipline the md
    detector keeps by capping itself at one slip."""
    if _model_near_miss(a, b):
        return True
    x, y = a.lower(), b.lower()
    if min(len(x), len(y)) < 6 or abs(len(x) - len(y)) > 2:
        return False
    # Banded Levenshtein, capped at 2 -- rows whose minimum exceeds the cap
    # cannot recover, so the walk stops early.
    prev = list(range(len(y) + 1))
    for i, cx in enumerate(x, 1):
        cur = [i]
        for j, cy in enumerate(y, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (cx != cy)))
        if min(cur) > 2:
            return False
        prev = cur
    return prev[-1] <= 2


def _check_skill_typos(manifest):
    """Intra-manifest skill-name near-miss detector (WARNING only) -- the md
    model detector applied to skill names.

    Returns (findings, warnings) — findings is always empty; see
    `_check_model_typos` for why the pair is still the shape. Converted from
    taking the `warnings` list.

    Flags a name used EXACTLY ONCE beside a near-miss neighbour used two or
    more times anywhere in the manifest (task.skills or meta.areas defaults).
    A spelling used twice is an established choice, never flagged. And it is
    deliberately intra-manifest: whether a name exists in the DISCOVERY
    inventory is the panel's hint (the modelHints precedent) -- this validator
    stays an offline shape-checker with no inventory in hand."""
    warnings = []
    sites = {}   # skill name -> [where, ...] in document order

    def note_use(val, where):
        if isinstance(val, str) and val.strip():
            sites.setdefault(val.strip(), []).append(where)

    for phase in _safe_list(manifest.get("phases")
                            if isinstance(manifest, dict) else None):
        if not isinstance(phase, dict):
            continue
        for task in _safe_list(phase.get("tasks")):
            if not isinstance(task, dict):
                continue
            twhere = "task %s" % (task.get("id") or "?")
            sk = task.get("skills")
            for s in (sk if isinstance(sk, list) else []):
                note_use(s, twhere)
    for tag, entry in _areas.registry(manifest).items():
        sk = entry.get("skills")
        for s in (sk if isinstance(sk, list) else []):
            note_use(s, "meta.areas.%s" % tag)

    for val in sorted(sites):
        if len(sites[val]) != 1:
            continue
        # The most-used neighbour is the established spelling -- the warning
        # names the likeliest intended name, exactly as md does.
        for other in sorted(sites, key=lambda v: (-len(sites[v]), v)):
            if other != val and len(sites[other]) > 1 \
                    and _skill_near_miss(val, other):
                warnings.append(
                    "%s: skill '%s' is used once and is a near-miss of '%s' "
                    "(used %d times elsewhere in this manifest) -- a one-slip "
                    "skill name names a skill that never loads"
                    % (sites[val][0], val, other, len(sites[other])))
                break
    return ([], warnings)

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
        print("_manifest_typos.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__manifest_typos.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
