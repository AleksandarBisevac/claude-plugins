#!/usr/bin/env python3
"""
Whether ONE audit item belongs on the shared board at all - and never a bare yes.

`/audit:sync status` could not tell DELIBERATELY UNTRACKED from DRIFT. A phase
nobody ever intended to put on Azure DevOps - an internal refactor, a sweep a
team wants kept off a shared board - reported as `unlinked` on every run, for
ever. That is a false positive with no expiry: the drift lens grows one
permanent row per such phase, and a lens carrying permanent rows stops being
read, which costs it the REAL drift it was built to catch.

`phase.ado` could not carry the intention either, and that is a fact about the
field rather than an oversight: `ado` is an `adoLink` that SYNC writes, so a
phase declaring an intention there would be authoring into somebody else's
record. `phases[].adoTracked` is the authored sibling, exactly as `adoParent`
is the authored sibling of `ado`.

ABSENT MEANS TRACKED, and that is the half that makes the key shippable: a plan
that never sets it resolves precisely as it did before the key existed, so
nothing moves for anybody who does not opt in.

THE RULES, AND THE LAST ONE REFUSES TO ANSWER:

    phase, adoTracked false     not tracked
    phase, adoTracked true      tracked
    phase, nothing declared     tracked - the default, said out loud
    task                        its PHASE's answer, inherited
    bug                         NOT COVERED, and it says so

A TASK INHERITS UNDER BOTH SETTINGS OF `meta.ado.phaseWorkItems`, and the two
are not one rule wearing two hats. With phase work items ON the inheritance is
FORCED: a task hangs under its phase's work item and an untracked phase has
none, so there is nowhere for the task to go. With them OFF the task would get
a work item of its own, so mechanics decide nothing - the PHASE is the unit an
operator chose to keep off the board, and honouring that choice at the phase
while pushing its tasks anyway would put the same work on the same board under
another name. The answer is the same; the BASIS is not, and the basis is the
half a reader has to check.

A BUG IS NOT ANSWERED, RATHER THAN ANSWERED `TRACKED`. Bugs are owned by no
phase, so there is nothing for one to inherit; `bug.ado` is usually written by
a PULL, off somebody else's board, and reporting that as tracked by this
feature would be the plugin claiming a card it never created. So `tracked` is
THREE-VALUED - True, False, and None for "no basis to answer" - and
`is_tracked` / `is_untracked` are named functions so that no caller has to
decide for itself what a falsy None meant.

EVERY ANSWER CARRIES ITS BASIS. That is the repo's rule everywhere, and here it
is also the feature: the whole point is telling apart two states that used to
print the same, and a bare `false` on a status line is the state we started
from one sentence later.

WHY LAYER 1, AND WHY EVERYTHING ARRIVES AS AN ARGUMENT. `_ado_parent` is this
module's template throughout and the argument is its argument: the push plan,
the status lens, the validator's neighbours and `resolve-ado-tracked.py` all
need the SAME answer, and two of those are layer-2 mates that cannot import
each other. A second expression of "does this belong on the board" would BE a
second policy. So this reaches nothing but `_output`.

THAT IS ALSO WHY IT DOES NOT OPEN THE MANIFEST, and the alternative was weighed
rather than waved off: loading the file here means importing `_manifest_io`,
which is a LAYER-MATE - the sideways edge `layer_violations()` refuses - and
would push this module to layer 2, where half its consumers could not reach it.
`resolve-ado-tracked.py` calls `_manifest_io.load_manifest()` and hands the
assembled dict down.

AND THE SHARDED LAYOUT IS WHY THAT MATTERS, rather than tidiness. In the
sharded layout the file at `manifestPath` is an INDEX whose phases are stubs -
`{id, title, status, shard}` - while `adoTracked` and `tasks` both live in the
shard BODY. A caller that reached for `json.load` would therefore see no
`adoTracked` on any phase and no task at all, and would report every phase
TRACKED by default: the confident wrong answer, on the layout parallel
worktrees use. So a phase still carrying a `shard` key is NOT resolved here. It
is reported as unanswered, naming the shard and the loader, because a stub is a
missing basis and a missing basis is the thing to say.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__ado_tracked.py`.
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

# The field, spelled once. Every reader and every writer asks this module for
# it, so a rename is one edit rather than a grep - `_ado_parent.FIELD`'s reason,
# for the key that sits beside it on the same level.
FIELD = "adoTracked"

# The sentence a phase that declares nothing gets. It is a CONSTANT because the
# task basis quotes it verbatim: a reader chasing "why is P3.1 on the board"
# reads the same words at the task and at the phase, or learns nothing at the
# second one.
DEFAULT_BASIS = "no %s anywhere - the default is tracked" % (FIELD,)

# The stub key `_manifest_io` writes into a sharded INDEX. Named here rather
# than imported for the layer reason in the docstring: that module is a
# layer-mate, and this is ONE key read for one refusal, not a second
# implementation of the layout.
_SHARD_KEY = "shard"

# Why a task's answer is its phase's, in the two regimes. Two sentences and not
# one, because the two are different facts that happen to agree: the first is
# mechanical (there is nowhere else for the task to hang), the second is a
# policy (the phase is the unit the operator chose). A single sentence covering
# both would have to say neither.
_WORK_ITEMS_ON = ("meta.ado.phaseWorkItems is on, so a task hangs under its "
                  "phase's work item and an untracked phase has none")
_WORK_ITEMS_OFF = ("meta.ado.phaseWorkItems is false, so this task would get a "
                   "work item of its own; it inherits anyway, because the "
                   "phase is the unit the operator chose to keep off the board")

# What a BUG's answer is about, spelled once because the row and the summary
# line both say it. It is a fact about the FIELD rather than a preference:
# `adoTracked` is defined on a phase, a bug belongs to no phase, and `bug.ado`
# is written by a pull off a board this plugin did not create.
_BUG_NOT_COVERED = ("a bug is owned by no phase, so there is nothing for it to "
                    "inherit and %s answers about no bug: bug.ado is usually "
                    "written by a PULL, off somebody else's board, and calling "
                    "that tracked would be this plugin claiming a card it "
                    "never created" % (FIELD,))


# --- the declaration: what one phase said about itself ---------------------------
def declared(item):
    """(declaration, problem) - what `item` says about itself, and what is wrong
    with what it said.

    `declaration` is True, False, or None when the key is ABSENT. `problem` is a
    sentence, or None.

    TWO HALVES BECAUSE ONE RETURN COULD NOT CARRY THEM. A key present with a
    value that is not a boolean is neither a declaration nor an absence, and a
    reader that folded it into `None` would answer TRACKED - putting on the
    board the one phase whose author was trying to keep it off. So the
    unreadable value gets a sentence and `resolve` turns that into "no basis to
    answer" rather than into a default, which is this repo's rule about a
    missing basis applied to the one input where the default is harmful.

    `bool` is checked before anything else for `_ado_parent._positive_id`'s
    reason inverted: `True` is an `int` in Python, so a value test that reached
    for truthiness would read `adoTracked: 1` as a declaration when it is a typo.
    """
    if not isinstance(item, dict) or FIELD not in item:
        return (None, None)
    value = item.get(FIELD)
    if isinstance(value, bool):
        return (value, None)
    return (None, "%s: %s must be true or false, got %r - nothing was declared "
                  "and nothing is assumed, because assuming the default here "
                  "puts a phase on the board its author was trying to keep off"
                  % (item.get("id") or "?", FIELD, value))


def declaration_findings(item, where):
    """(findings, warnings) for one item's `adoTracked`. The ONE shape check.

    THE NEIGHBOUR ONE RELEASE EARLIER ALREADY HAD THIS and its absence here was a
    real hole, found by asking the validator rather than by reading it:
    `adoParent = "not-an-object"` is REFUSED and named, `status = 17` is REFUSED
    and named, and `adoTracked = "yes"` was accepted in silence with exit 0. That
    is F203 inverted - there the schema PERMITTED what the validator refused, here
    the schema forbids (`"type": "boolean"`) what the validator waved through - and
    the two halves disagreeing about what a valid plan is has already shipped once.

    IT MATTERS MOST FOR THE WRITERS. Every command that mutates the manifest
    revalidates through `validate-manifest.py`, and the panel's PUT does too, so
    without this a panel or a script could write `adoTracked: 1`, pass validation,
    and produce a phase that `resolve` can only report as unanswerable forever.

    A FINDING RATHER THAN A WARNING, for `declaration_findings`' own reason one
    field over: the failure mode of a mistyped value is a phase going ONTO a board
    its author was trying to keep off, and a warning is a thing a run continues
    past. ABSENT is legal and silent - absent means tracked, which is the default
    the whole feature is built around.
    """
    findings, warnings = [], []
    if not isinstance(item, dict) or FIELD not in item:
        return (findings, warnings)
    _decl, problem = declared(item)
    if problem:
        findings.append("%s: %s" % (where, problem.split(": ", 1)[-1]))
    return (findings, warnings)


def _clause(value):
    """The phrase a basis quotes when it names what a phase said.

    One function so the phase's own basis and the task's inherited one cannot
    spell the same declaration two ways - which is the drift that makes a
    two-level explanation useless to the reader following it down.
    """
    if value is None:
        return DEFAULT_BASIS
    return "%s: %s" % (FIELD, "true" if value else "false")


def _stub_basis(item_id, phase):
    """The refusal a sharded INDEX STUB earns, or None for a real phase body.

    `_manifest_io._merge_phase` drops the `shard` key when it assembles, so a
    phase still carrying one has NOT been assembled: `adoTracked` and `tasks`
    both live in the shard body, and a caller holding the index alone has a
    phase that declares nothing and owns nothing. Reading that as "declares
    nothing, so tracked" is the confident wrong answer, and it lands on the
    layout parallel worktrees use rather than on an exotic one.
    """
    if not isinstance(phase, dict) or _SHARD_KEY not in phase:
        return None
    return ("phase %s is an index stub pointing at %r - its body was never "
            "read, so nothing here has seen whether it declares %s. Load the "
            "manifest through _manifest_io.load_manifest() rather than reading "
            "the file at manifestPath directly"
            % (item_id, phase.get(_SHARD_KEY), FIELD))


# --- resolution: the one function every surface calls ----------------------------
def _answer(kind, item_id, tracked, basis, warnings=None):
    """One answer, as a dict - never a bare boolean and never a tuple.

    `tracked` is THREE-VALUED, and the third value is why this shape exists at
    all: True is on the board, False is deliberately off it, None is "nothing
    here has a basis to say either". A tuple would have had to be re-unpacked at
    every call site the day it grew a fourth member, and it has four already -
    what the answer is about, which item, the answer, and the sentence that
    makes it true.
    """
    return {"kind": kind, "id": item_id, "tracked": tracked, "basis": basis,
            "warnings": list(warnings or [])}


def is_tracked(row):
    """True only when this row was ANSWERED `on the board`.

    `is True`, never `bool(...)`. The third value is None - "no basis to
    answer" - and a truthiness test would silently file it as untracked, which
    is a claim nothing here made and the exact collapse this feature undoes.
    """
    return isinstance(row, dict) and row.get("tracked") is True


def is_untracked(row):
    """True only when this row was ANSWERED `deliberately off the board`.

    The predicate exists so no caller writes `not is_tracked(row)`: that reads
    an unanswered row as untracked, and an unanswered row is exactly the one a
    push must neither create nor report as drift.
    """
    return isinstance(row, dict) and row.get("tracked") is False


def _phase_answer(item_id, phase):
    """What a phase says about itself, or the default said out loud."""
    stub = _stub_basis(item_id, phase)
    if stub is not None:
        return _answer("phase", item_id, None, stub, [stub])
    value, problem = declared(phase)
    if problem is not None:
        return _answer("phase", item_id, None, problem, [problem])
    if value is None:
        return _answer("phase", item_id, True, DEFAULT_BASIS)
    return _answer("phase", item_id, value, "declared %s" % (_clause(value),))


def _task_answer(task, phase, ado):
    """A task's answer is its phase's, and the basis names the regime.

    A TASK'S OWN `adoTracked` IS INERT AND IS SAID OUT LOUD, never dropped. The
    key is defined on a phase and nowhere else, so a task carrying one is
    somebody expecting it to be honoured - and a no-op on unexpected input
    leaves that author believing their file applied. `_ado_parent._phase_result`
    warns about an inert `adoParent` for the same reason and in the same words.
    """
    item_id = task.get("id") or "?"
    pid = (phase.get("id") if isinstance(phase, dict) else None) or "?"
    warnings = []
    if isinstance(task, dict) and FIELD in task:
        warnings.append("task %s declares %s, which is INERT: whether work "
                        "belongs on the board is a property of the PHASE, and "
                        "this task inherits phase %s's answer. Move the "
                        "declaration to the phase, or drop it."
                        % (item_id, FIELD, pid))
    parent = _phase_answer(pid, phase)
    if parent["tracked"] is None:
        return _answer("task", item_id, None,
                       "phase %s was not answered, so task %s is not either: %s"
                       % (pid, item_id, parent["basis"]),
                       warnings + parent["warnings"])
    value, _problem = declared(phase)
    regime = (_WORK_ITEMS_OFF if ado.get("phaseWorkItems") is False
              else _WORK_ITEMS_ON)
    return _answer("task", item_id, parent["tracked"],
                   "inherited from phase %s (%s) - %s"
                   % (pid, _clause(value), regime), warnings)


def resolve(item, ado=None, phase=None, kind=None):
    """{"kind", "id", "tracked", "basis", "warnings"} for ONE item.

    THE ONE FUNCTION, and every surface calls it - the push plan, the status
    lens, `resolve-ado-tracked.py` and the panel after them.

    `phase` is the task's phase, or None when `item` IS a phase; `kind="bug"`
    is the one thing a caller must say out loud, because a bug is structurally
    indistinguishable from a phase here - both are dicts with an `id` - and
    guessing would answer TRACKED about a card this plugin never created.

    `ado` is `meta.ado`. The only key read from it is `phaseWorkItems`, and it
    changes the BASIS and never the answer: a task inherits either way (see the
    module docstring), so a caller that has no connector config gets the right
    verdict with a basis naming the default regime.
    """
    ado = ado if isinstance(ado, dict) else {}
    item = item if isinstance(item, dict) else {}
    item_id = item.get("id") or "?"
    if kind == "bug":
        return _answer("bug", item_id, None, _BUG_NOT_COVERED)
    if phase is not None:
        return _task_answer(item, phase, ado)
    if kind == "task":
        # Asked about a task with no phase to inherit from. An answer would have
        # to be invented, and the invented one is TRACKED - the direction that
        # puts work on a board. So it is refused with the reason.
        return _answer("task", item_id, None,
                       "task %s was asked about with no phase, and a task's "
                       "answer IS its phase's - there is nothing here to "
                       "inherit from" % (item_id,))
    return _phase_answer(item_id, item)


# --- the whole manifest, walked once ---------------------------------------------
def inventory(manifest, ado=None):
    """{"rows": [...], "warnings": [...]} - every item in an ASSEMBLED manifest.

    ONE WALK, so the plan block, the counts and the door's `--json` cannot
    disagree about which items were asked about - `_ado_parent.inventory`'s
    reason exactly.

    THE MANIFEST MUST BE ASSEMBLED, and the un-assembled shape is DETECTED
    rather than trusted: a phase still carrying a `shard` key is answered "not
    answered", with the loader named. See the module docstring for why that is
    the bug class this feature would otherwise ship on the sharded layout.

    `bugs` NEEDS NO `None`/`[]` DISTINCTION HERE, unlike `_ado_parent.inventory`
    where it is an argument and the two spellings mean "did not ask" and "asked,
    none". This function is handed the MANIFEST, so it always asks and the file
    always answers - which is also what lets `bug_line` print at zero without a
    second meaning.
    """
    manifest = manifest if isinstance(manifest, dict) else {}
    if ado is None:
        meta = manifest.get("meta")
        meta = meta.get("ado") if isinstance(meta, dict) else None
        ado = meta
    ado = ado if isinstance(ado, dict) else {}
    rows, warnings = [], []
    phases = manifest.get("phases")
    for phase in (phases if isinstance(phases, list) else []):
        if not isinstance(phase, dict):
            continue
        answer = resolve(phase, ado=ado)
        rows.append(answer)
        warnings.extend(answer["warnings"])
        tasks = phase.get("tasks")
        for task in (tasks if isinstance(tasks, list) else []):
            if not isinstance(task, dict):
                continue
            tanswer = resolve(task, ado=ado, phase=phase)
            rows.append(tanswer)
            warnings.extend(tanswer["warnings"])
    # After the plan and never inside it: a bug belongs to no phase, and a row
    # order that interleaved them would put an item nothing answers for in the
    # middle of the items it does.
    bugs = manifest.get("bugs")
    for bug in (bugs if isinstance(bugs, list) else []):
        if not isinstance(bug, dict):
            continue
        rows.append(resolve(bug, ado=ado, kind="bug"))
    return {"rows": rows, "warnings": warnings}


def scope_rows(rows, scope, target):
    """The rows one CLI scope names: `all`, `phase` or `task`.

    A `--phase` COVERS THE TASKS UNDER IT, because here the phase's answer and
    its tasks' answers are literally one answer - a scope returning the phase
    alone would drop every row that phase's declaration actually moved, which is
    the whole visible effect of the key.

    A BUG IS IN NO SCOPE BUT `all`. It belongs to no phase and is not a task, so
    `--phase BUG-3` would answer about a bug in a sentence naming a phase. An
    unknown scope word names nothing for the same reason it should: the door
    turns an empty scope into exit 2 with the name it could not find, and a
    silent fall-through to `phase` would answer a question nobody asked.
    """
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    if scope == "all":
        return rows
    if scope == "task":
        return [r for r in rows
                if r.get("kind") == "task" and r.get("id") == target]
    if scope != "phase":
        return []
    return [r for r in rows
            if r.get("kind") != "bug"
            and (r.get("id") == target
                 or str(r.get("id") or "").startswith("%s." % (target,)))]


# --- the sentences every surface prints ------------------------------------------
def counts(rows):
    """{"items", "tracked", "untracked", "unanswered", "bugs"} over `rows`.

    `items` COUNTS PHASES AND TASKS, AND THE THREE VERDICTS PARTITION IT, so a
    reader can check the arithmetic instead of trusting it. Bugs are counted
    apart and appear in none of the other four: every bug is unanswered by
    construction, so folding them in would make `unanswered` a number that can
    never reach zero and would report the ordinary state of every bug as a gap
    in the plan. `_ado_parent.plan_lines` keeps bugs out of its counts for the
    same reason.
    """
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    plan = [r for r in rows if r.get("kind") != "bug"]
    return {"items": len(plan),
            "tracked": len([r for r in plan if is_tracked(r)]),
            "untracked": len([r for r in plan if is_untracked(r)]),
            "unanswered": len([r for r in plan
                               if r.get("tracked") is None]),
            "bugs": len([r for r in rows if r.get("kind") == "bug"])}


def _verdict(row):
    """The word one row prints for its own answer.

    THREE WORDS FOR THREE ANSWERS. A shared word for two of them is precisely
    the collapse this feature exists to undo, one layer down.
    """
    if is_tracked(row):
        return "tracked"
    if is_untracked(row):
        return "NOT TRACKED"
    return "NOT ANSWERED"


def plan_lines(rows):
    """The block every surface prints, as lines.

    BUILT HERE rather than in each renderer, for `_ado_parent.plan_lines`'
    reason: the DRY claim of this feature is one set of sentences reaching the
    push plan, the status lens, the door and the panel, instead of four
    renderings that drift apart at the first correction.

    EVERY COUNT PRINTS AT ZERO. A count that appears only when it is non-zero
    cannot be told from a count nobody took, and this feature's whole subject is
    telling apart two states that used to print the same way.

    THE BUG LINE IS NOT IN HERE, and `bug_line` is a separate function for a
    reason that is about scoping rather than tidiness: this block is printed for
    the SCOPED rows, and a `--phase P1` run printing "0 bugs" would answer about
    P1 in a sentence that reads as a fact about the file.
    """
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    tally = counts(rows)
    out = ["tracked: %d item(s), %d on the board, %d deliberately untracked, "
           "%d not answered"
           % (tally["items"], tally["tracked"], tally["untracked"],
              tally["unanswered"])]
    for row in rows:
        if row.get("kind") == "bug":
            continue
        out.append("  %s %s -> %s -- %s"
                   % (row.get("kind"), row.get("id") or "?", _verdict(row),
                      row.get("basis") or "(no basis recorded)"))
    return out


def bug_line(rows):
    """The one sentence about bugs - printed ALWAYS, including at zero.

    Separate from `plan_lines` so a caller can print it over the WHOLE
    inventory while the plan block is narrowed to a scope. It is one derivation
    with two call sites rather than a sentence each surface re-words, which is
    the only version of this that stays true.
    """
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    return ("  bugs: %d not covered - %s"
            % (len([r for r in rows if r.get("kind") == "bug"]),
               _BUG_NOT_COVERED))


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
        print("_ado_tracked.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__ado_tracked.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
