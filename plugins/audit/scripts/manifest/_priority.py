#!/usr/bin/env python3
"""
Which ready task the orchestrator reaches for first — and nothing about whether it may.

Execution order used to be implicit in the array: `phases[]` in written order, then
task id inside a phase (`reference/orchestrator.md` -> Readiness rule). Nothing could
say "this phase first" without physically moving the phase — a structural edit of the
whole file, and in the sharded layout an edit of the index — so nobody did it in
flight, and the workaround was to hang `blockedBy` off every OTHER phase.

THE INVARIANT, WHICH IS WHY THIS MODULE IS ARITHMETIC AND NOT A SCHEDULER:

    Priority re-sorts only tasks that are ALREADY ready. It never makes an unready
    task ready and never skips a dependency.

`_status_facts.ready_tasks()` decides readiness; this only sorts its output.
Dependencies always win — a priority is a wish about the schedule, never a permission.
A phase pinned first whose own `blockedBy` is unsatisfied is therefore SKIPPED, and
`pinned_but_blocked()` is here so the skip is SAID rather than silently absorbed.

ABSENT MEANS UNPRIORITISED, NOT MIDDLE AND NOT ZERO. An unprioritised phase sorts
after every prioritised one and keeps manifest order among its peers. That is a
testable property rather than a taste: adding a priority to ONE phase must not
quietly re-sort the rest, and a manifest carrying no `priority` at all must order
exactly as it did before this module existed — which is the case that goes red if
`sort_key` ever becomes unconditional.

WHY LAYER 1. `_branch` is the precedent and `_deps.LAYERS` states the reason in the
same words: four surfaces need the SAME answer — `_status_facts` (L2) for the ready
list, `_manifest_crossrefs` (L2) for the findings, `_panel_composition` (L4) for the
control, and `set-priority.py` for the write. A second expression of the order would
be a second order. So this reaches nothing but `_output`: it is arithmetic over
plain dicts, it opens no file and holds no module state.

TWO THINGS IT DELIBERATELY DOES NOT OWN. `TERMINAL` (what counts as settled) is
`_manifest_io`'s, at this same layer and therefore not importable from here — so
`pinned_but_blocked` takes the ALREADY-COMPUTED unmet map instead of re-deriving
readiness, which is the half of this feature that must never have a second opinion.
And `maxTier` is a CONFIG value, so `over_max` takes it as an argument rather than
carrying a default that would be a second copy of `hooks/_config.py`'s.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__priority.py`.
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

# The field, spelled once. Every reader and both writers ask this module for it, so
# a rename is one edit rather than a grep.
FIELD = "priority"

# Tier 1 is the only unique tier. The rest are shared on purpose: a plan usually
# knows what must come FIRST and only roughly ranks what follows, and forcing a
# total order onto the rest is how a priority scheme turns into renumbering work.
UNIQUE_TIER = 1

# The two ranks `sort_key` puts in front of the tier. Named because the whole
# meaning of "absent priority" lives in the gap between them: an unprioritised
# phase is not tier 0 and not a middle tier, it is a separate class that sorts
# after every prioritised phase.
_PRIORITISED = 0
_UNPRIORITISED = 1


# --- what a valid priority is ---------------------------------------------------
def tier_of(phase):
    """The phase's tier, or None when it has none — the ONE place that decides
    what a valid value is.

    A `bool` is rejected before the `int` test because `True` is an `int` in
    Python and `priority: true` is a typo, not tier 1. Zero and negatives are
    rejected because a tier is a rank starting at one; they read as
    unprioritised here AND are reported by `invalid_tiers()`, so a value with no
    effect is never silently absorbed.
    """
    if not isinstance(phase, dict):
        return None
    val = phase.get(FIELD)
    if isinstance(val, bool) or not isinstance(val, int) or val < 1:
        return None
    return val


def invalid_tiers(phases):
    """`[(phase id, the value)]` for every phase carrying a `priority` that is
    not a positive integer.

    Separate from `tier_of` because the two answer different questions: `tier_of`
    says how to SORT the phase (it has no tier), and this says the file contains
    a value nobody will honour. Without it, `priority: "1"` would order exactly
    like no priority at all and nothing would ever mention it.
    """
    out = []
    for phase in (phases or []):
        if not isinstance(phase, dict) or FIELD not in phase:
            continue
        if tier_of(phase) is None:
            out.append((phase.get("id"), phase.get(FIELD)))
    return out


# --- the order ------------------------------------------------------------------
def sort_key(phase, index):
    """The ONE expression of execution order in this repo, as a tuple.

    `index` is the phase's position in `phases[]` — the manifest order, which is
    both the tie-break between two phases sharing a tier and the ENTIRE order
    when nothing is prioritised. Keeping it in the key is what makes the
    no-priority case identical to the behaviour before this module existed:
    every key becomes `(_UNPRIORITISED, 0, index)` and the sort is the identity.

    Extending this to a per-task priority later is adding members to the tuple
    (phase tier, phase index, task tier, task id), which is why it is a tuple
    and not a number.
    """
    tier = tier_of(phase)
    if tier is None:
        return (_UNPRIORITISED, 0, index)
    return (_PRIORITISED, tier, index)


def ranks(phases):
    """Each phase's POSITION in execution order, positionally — `ranks[i]` is
    where `phases[i]` runs.

    `order()` answers "what runs next"; this answers "where in the run does THIS
    phase sit", and a renderer that must keep SHOWING the written plan needs the
    second. BOTH FRONT ENDS ARE HANDED THIS NUMBER AND NEITHER HOLDS THE RULE:
    the HTML report stamps it on each phase row as `data-porder`, and
    `_status_facts.rollup` ships it to the panel as the row's `porder`. A client
    re-expressing `sort_key` in JavaScript is the one way this feature could grow
    a second opinion about order; the panel's Overview did exactly that for a
    while, under a comment saying its key mirrored this function, and what
    replaced the comment is a lint — `_deps.SHARED_CONCERNS`' "phase execution
    order" row fails the build on that shape anywhere under `scripts/ui/`.

    Two callers of this function is not two orders, and it is structural rather
    than a preference: `_report_html` and `_status_facts` are both layer 2, so
    neither can import the other and each has to reach down to here.

    This is the module's only permutation — `order()` reads it rather than
    sorting again, so a change to the comparator cannot land in one and miss
    the other.
    """
    items = list(phases or [])
    ranked = sorted(range(len(items)), key=lambda i: sort_key(items[i], i))
    out = [0] * len(items)
    for rank, i in enumerate(ranked):
        out[i] = rank
    return out


def order(phases):
    """`phases` re-ordered by `sort_key` — a NEW list, never sorted in place.

    In place would be the cheaper spelling and the wrong contract: the display
    surfaces read the same list and must keep showing the plan in the order it
    was written. Execution order changes; the written plan does not.
    """
    items = list(phases or [])
    out = [None] * len(items)
    for i, rank in enumerate(ranks(items)):
        out[rank] = items[i]
    return out


def rank_ready(rows):
    """Sort `(phase, phase index, sequence, value)` rows and return the values.

    The shape `ready_tasks()` needs, kept HERE so the ready list and the phase
    list cannot end up sorted by two different expressions. `sequence` is the
    row's position in the caller's own walk, which preserves document order
    inside one phase — priority ranks phases, never the tasks within one.
    """
    ranked = sorted(rows, key=lambda r: (sort_key(r[0], r[1]), r[2]))
    return [r[3] for r in ranked]


# --- uniqueness -----------------------------------------------------------------
def tier_one_holder(phases):
    """The id of the phase holding tier 1, or None.

    FIRST IN MANIFEST ORDER WINS, and that is the deterministic tie-break the
    validator names when it reports a second holder. The panel and
    `set-priority.py` both ask THIS function whether the tier is free, for the
    reason the Policy tab already answers to: two places deciding what is legal
    are two rules that will disagree, and the disagreement surfaces as a write
    the UI promised and the CLI refuses.
    """
    for phase in (phases or []):
        if tier_of(phase) == UNIQUE_TIER:
            return phase.get("id")
    return None


def tier_conflicts(phases):
    """`[(tier, [phase ids])]` for every tier that must be unique and is not.

    Only tier 1 can appear here — `UNIQUE_TIER` is the whole rule — but the
    return stays a list of tiers so that widening uniqueness later is a change to
    one constant rather than to every caller's unpacking.
    """
    holders = [p.get("id") for p in (phases or [])
               if tier_of(p) == UNIQUE_TIER]
    if len(holders) < 2:
        return []
    return [(UNIQUE_TIER, holders)]


def over_max(phases, max_tier):
    """`[(phase id, tier)]` for phases pinned above `max_tier`.

    ADVISORY, AND NOTHING IS CLAMPED. A clamped value is a file that says one
    thing and a run that does another; the phase keeps the tier it was given,
    sorts after every tier at or under the maximum by ordinary arithmetic, and
    the surfaces say so. `max_tier` is an argument because it is a CONFIG value
    (`priority.maxTier`) and a default here would be a second copy of it.
    """
    if isinstance(max_tier, bool) or not isinstance(max_tier, int):
        return []
    out = []
    for phase in (phases or []):
        tier = tier_of(phase)
        if tier is not None and tier > max_tier:
            out.append((phase.get("id"), tier))
    return out


# --- the pin that cannot be honoured --------------------------------------------
def pinned_but_blocked(phases, unmet_by_id, finished=()):
    """The top-priority unfinished phase whose own waits are unsatisfied, or None.

    THE ONE PLACE THE SKIP IS TURNED INTO FACTS, so that the CLI, both reports
    and the panel say the same sentence from one `rollup()` key instead of four
    renderings that drift. Returns a dict rather than a tuple because the note
    needs the tier as well as the id, and a caller unpacking two values would
    have had to be edited to learn a third.

    `unmet_by_id` is `_status_facts.unmet_refs()`'s answer — computed by
    `_manifest_io.unsatisfied`, the module that owns what "satisfied" means. It
    is passed IN rather than derived here on purpose: readiness having a second
    implementation is the one way this feature could break correctness rather
    than only order, and `_manifest_io` sits at this same layer, so importing it
    would be a sideways edge the layer lint fails.

    `finished` is the statuses that mean the phase will not run again — also
    `_manifest_io`'s (`TERMINAL`), handed over for the same reason. A done phase
    holding tier 1 is a pin that was honoured, not one that was skipped.
    """
    settled = tuple(finished or ())
    for phase in order(phases):
        tier = tier_of(phase)
        if tier is None:
            return None          # order() puts every prioritised phase first
        if phase.get("status") in settled:
            continue
        waiting = list((unmet_by_id or {}).get(phase.get("id")) or [])
        if waiting:
            return {"phaseId": phase.get("id"), "tier": tier,
                    "waitingOn": waiting}
        return None              # the top pin CAN run; nothing to report
    return None


def note(pin, first_ready):
    """The sentence every surface prints, or None when there is nothing to say.

    Built here rather than in each renderer because the whole DRY claim of this
    feature rests on one string reaching four surfaces. It names the id running
    INSTEAD, because "the pin was skipped" without the substitute reads as "the
    run stalled" — and when nothing is ready at all it says that, rather than
    printing a blank where a task id belongs.
    """
    if not pin:
        return None
    waiting = ", ".join(str(r) for r in (pin.get("waitingOn") or []))
    instead = ("running %s instead" % first_ready) if first_ready \
        else "and nothing else is ready either"
    return ("%s holds priority %s but is waiting on %s (not done) - %s"
            % (pin.get("phaseId"), pin.get("tier"),
               waiting or "(nothing named)", instead))


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
        print("_priority.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__priority.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
