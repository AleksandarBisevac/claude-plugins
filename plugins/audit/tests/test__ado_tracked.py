#!/usr/bin/env python3
"""
The cases for `_ado_tracked.py` — whether one audit item belongs on the board.

Arithmetic over dicts, so there is no fixture directory below this file: the
door's suite (`test_resolve_ado_tracked.py`) owns everything that needs a real
sharded manifest on disk. What is pinned HERE is the rule set, and every family
below carries both directions, because every one of these rules has a wrong
implementation that never fires AND a wrong implementation that always does:

- **A declaration is honoured, and an absence is not one.** `at1` is the
  feature; `at3` is the case that looks vacuous and is the only one that fails
  if `adoTracked` ever becomes load-bearing on a file that does not carry it.
  Absent means tracked, so a plan nobody has touched does not move.
- **A task inherits under BOTH settings of `phaseWorkItems`, and the basis
  differs.** `at10`/`at11` hold the two regimes apart by comparing the whole
  sentences rather than asserting one substring, because a resolver that lost
  the regime clause entirely would still satisfy an `in`.
- **A bug is NOT ANSWERED and says so.** `at20`; `at22` is its control, so a
  rule that answered nothing at all cannot pass the family.
- **An index STUB is refused rather than read as an absence.** `at31` is the
  bug class this feature would otherwise ship on the sharded layout — a raw
  read of `manifestPath` sees no declaration on any phase and no task at all,
  and a resolver trusting that reports a whole plan TRACKED by default. `at32`
  is the other direction: a real phase body must still be answered.
- **`tracked` is three-valued and the predicates are strict.** `at71` pins that
  a truthy `1` is not True here, because a falsy/truthy read of the third value
  reports an unanswered item as deliberately untracked — which is the exact
  collapse the feature undoes one layer up.
- **Counts, never presence.** The assertions below compare NUMBERS of rows or
  whole lists wherever more than one could appear: a rule that fires twice and a
  rule that fires once both satisfy `in`.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _ado_tracked as M                           # noqa: E402


def _phase(pid, tracked=None, tasks=None, **extra):
    """One phase. `tracked=None` means the key is ABSENT, which is a state and
    not a missing argument — the whole default rule turns on that difference."""
    phase = {"id": pid, "title": pid, "status": "pending",
             "tasks": list(tasks or [])}
    if tracked is not None:
        phase[M.FIELD] = tracked
    phase.update(extra)
    return phase


def _task(tid, **extra):
    task = {"id": tid, "title": tid, "status": "pending"}
    task.update(extra)
    return task


def _manifest(phases, ado=None, bugs=None):
    return {"meta": {"version": 2, "ado": ado if ado is not None else {}},
            "phases": list(phases), "bugs": list(bugs or [])}


def _cases(check):
    # --- a phase's own declaration, all three states --------------------------
    _false = M.resolve(_phase("P2", tracked=False))
    check("at1 a phase declaring adoTracked: false is NOT tracked, and the "
          "answer carries the sentence that makes it true rather than a bare "
          "boolean: %r" % (_false,),
          _false["tracked"] is False and _false["kind"] == "phase"
          and _false["id"] == "P2"
          and _false["basis"] == "declared adoTracked: false")
    _true = M.resolve(_phase("P3", tracked=True))
    check("at2 ...and a phase declaring adoTracked: true IS tracked - the "
          "control, without which a resolver that read every declaration as "
          "'keep it off the board' would pass at1: %r" % (_true,),
          _true["tracked"] is True
          and _true["basis"] == "declared adoTracked: true")
    # THE SECOND-DIRECTION CASE. It passes by construction on the code before
    # this key existed, and it is the only one that fails if absent ever stops
    # meaning tracked - i.e. if the key becomes load-bearing on a file that does
    # not carry it, which is what `COMPATIBILITY.md` forbids.
    _absent = M.resolve(_phase("P1"))
    check("at3 a phase declaring NOTHING is tracked, and the default is said "
          "out loud instead of being left as an unexplained true: %r"
          % (_absent,),
          _absent["tracked"] is True
          and _absent["basis"] == M.DEFAULT_BASIS
          and M.FIELD in _absent["basis"])
    check("at4 the three phase answers carry three DIFFERENT sentences - a "
          "shared basis would make the feature unreadable exactly where it is "
          "supposed to explain itself: %r"
          % (sorted([_false["basis"], _true["basis"], _absent["basis"]]),),
          len(set([_false["basis"], _true["basis"], _absent["basis"]])) == 3)

    # --- what `declared()` may and may not read -------------------------------
    check("at5 declared() answers (value, problem) for the two spellings that "
          "ARE declarations, and (None, None) for the absence",
          M.declared(_phase("P1", tracked=True)) == (True, None)
          and M.declared(_phase("P1", tracked=False)) == (False, None)
          and M.declared(_phase("P1")) == (None, None)
          and M.declared(None) == (None, None))
    _bad_value, _bad_problem = M.declared({"id": "P9", M.FIELD: "false"})
    check("at6 a value that is not a boolean is NEITHER a declaration nor an "
          "absence: it gets a sentence, because reading the string 'false' as "
          "'nothing was said' answers TRACKED and puts on the board the one "
          "phase whose author was trying to keep it off: %r" % (_bad_problem,),
          _bad_value is None and _bad_problem is not None
          and "P9" in _bad_problem and "true or false" in _bad_problem)
    _one_value, _one_problem = M.declared({"id": "P9", M.FIELD: 1})
    check("at7 ...and 1 is a typo rather than 'true', because True is an int in "
          "Python and a truthiness read here would honour a number as a "
          "declaration: %r" % (_one_problem,),
          _one_value is None and _one_problem is not None)
    check("at8 ...while a real boolean produces NO problem - the control, "
          "without which a check that refused every value would pass at6",
          M.declared(_phase("P1", tracked=False))[1] is None
          and M.declared(_phase("P1", tracked=True))[1] is None)
    _unreadable = M.resolve({"id": "P9", "title": "t", M.FIELD: "false"})
    check("at9 an unreadable declaration resolves to NOT ANSWERED rather than "
          "to the default, and the problem is raised as a warning instead of "
          "being folded away silently: %r" % (_unreadable,),
          _unreadable["tracked"] is None
          and _unreadable["warnings"][:1] == [_unreadable["basis"]]
          and len(_unreadable["warnings"]) == 1)

    # --- a task inherits, and the basis names WHICH regime --------------------
    _p_off = _phase("P2", tracked=False, tasks=[_task("P2.1")])
    _on = M.resolve(_task("P2.1"), ado={}, phase=_p_off)
    _off = M.resolve(_task("P2.1"), ado={"phaseWorkItems": False}, phase=_p_off)
    check("at10 a task under an untracked phase is untracked with phase work "
          "items ON, and the basis quotes the phase's own declaration so a "
          "reader can chase it one level up: %r" % (_on,),
          _on["tracked"] is False and _on["kind"] == "task"
          and _on["basis"].startswith(
              "inherited from phase P2 (adoTracked: false)")
          and "phaseWorkItems is on" in _on["basis"])
    check("at11 ...and with phaseWorkItems FALSE the verdict is the same and "
          "the sentence is not: the task would get a work item of its own, so "
          "nothing mechanical decides this - the phase is the unit the operator "
          "chose. Whole sentences compared, because a resolver that dropped the "
          "regime clause entirely would satisfy an `in`: %r" % (_off,),
          _off["tracked"] is False
          and _off["basis"] != _on["basis"]
          and "phaseWorkItems is false" in _off["basis"])
    _t_tracked = M.resolve(_task("P1.1"), phase=_phase("P1"))
    _t_declared = M.resolve(_task("P3.1"), phase=_phase("P3", tracked=True))
    check("at12 ...and a task under a TRACKED phase is tracked under both "
          "spellings of the phase's answer - the control, without which a rule "
          "that returned 'not tracked' for every task would pass at10 and at11: "
          "%r" % ([_t_tracked["tracked"], _t_declared["tracked"]],),
          _t_tracked["tracked"] is True and _t_declared["tracked"] is True
          and M.DEFAULT_BASIS in _t_tracked["basis"]
          and "adoTracked: true" in _t_declared["basis"])
    _inert = M.resolve(_task("P2.1", adoTracked=True), phase=_p_off)
    check("at13 a task's OWN adoTracked is INERT and is said out loud, never "
          "dropped: the key is defined on a phase, so a task carrying one is "
          "somebody expecting it honoured, and the answer still comes from the "
          "phase: %r" % (_inert,),
          _inert["tracked"] is False
          and len(_inert["warnings"]) == 1
          and len([w for w in _inert["warnings"]
                   if "INERT" in w and "P2.1" in w]) == 1)
    check("at14 ...and an ordinary task warns about NOTHING - the second "
          "direction, and the only case that fails if that warning ever becomes "
          "unconditional: %r" % (_on["warnings"],),
          _on["warnings"] == [] and _off["warnings"] == []
          and _t_tracked["warnings"] == [])
    _orphan = M.resolve(_task("P9.9"), kind="task")
    check("at15 a task asked about with NO phase is not answered, because a "
          "task's answer IS its phase's and the invented answer would be "
          "'tracked' - the direction that puts work on a board: %r" % (_orphan,),
          _orphan["tracked"] is None and _orphan["kind"] == "task"
          and "nothing here to inherit from" in _orphan["basis"])

    # --- a bug is out of scope, and SAYS so -----------------------------------
    _bug = M.resolve({"id": "BUG-1", "title": "b", "status": "open"},
                     kind="bug")
    check("at20 a bug is NOT ANSWERED rather than answered tracked: it is owned "
          "by no phase, so there is nothing to inherit, and bug.ado is written "
          "by a pull off somebody else's board: %r" % (_bug,),
          _bug["tracked"] is None and _bug["kind"] == "bug"
          and not M.is_tracked(_bug) and not M.is_untracked(_bug))
    check("at21 ...and the basis SAYS which of those it is, rather than leaving "
          "a null a reader has to interpret: %r" % (_bug["basis"],),
          "owned by no phase" in _bug["basis"]
          and "PULL" in _bug["basis"])
    _bug_declared = M.resolve({"id": "BUG-2", M.FIELD: False}, kind="bug")
    check("at22 ...and a bug carrying the key anyway is still not answered, "
          "while a PHASE carrying it is - the control, without which a rule "
          "that answered nothing at all would pass at20: %r"
          % ([_bug_declared["tracked"], _false["tracked"]],),
          _bug_declared["tracked"] is None and _false["tracked"] is False)

    # --- the whole manifest, walked once --------------------------------------
    _inv = M.inventory(_manifest(
        [_phase("P1", tasks=[_task("P1.1")]),
         _phase("P2", tracked=False, tasks=[_task("P2.1"), _task("P2.2")]),
         _phase("P3", tracked=True)],
        bugs=[{"id": "BUG-1", "status": "open"}]))
    _tally = M.counts(_inv["rows"])
    check("at23 counts() partitions the PLAN - phases and tasks - across the "
          "three verdicts, so a reader can check the arithmetic instead of "
          "trusting it, and bugs are counted apart because every bug is "
          "unanswered by construction: %r" % (_tally,),
          _tally["items"] == 6 and _tally["bugs"] == 1
          and (_tally["tracked"] + _tally["untracked"]
               + _tally["unanswered"]) == _tally["items"]
          and _tally["tracked"] == 3 and _tally["untracked"] == 3
          and _tally["unanswered"] == 0)
    check("at24 ...and the walk reaches every task under every phase, in "
          "document order, so the plan block and --json cannot disagree about "
          "which items were asked about: %r"
          % ([r["id"] for r in _inv["rows"]],),
          [r["id"] for r in _inv["rows"]]
          == ["P1", "P1.1", "P2", "P2.1", "P2.2", "P3", "BUG-1"])
    check("at25 an empty manifest is answered with ZEROS rather than with "
          "silence: a count that appears only when it is non-zero cannot be "
          "told from a count nobody took: %r"
          % (M.counts(M.inventory({})["rows"]),),
          M.counts(M.inventory({})["rows"])
          == {"items": 0, "tracked": 0, "untracked": 0, "unanswered": 0,
              "bugs": 0}
          and len(M.plan_lines([])) == 1
          and "0 item(s), 0 on the board" in M.plan_lines([])[0])
    check("at26 ...and the bug line prints at zero too, over a manifest with no "
          "bugs at all: %r" % (M.bug_line([]),),
          "bugs: 0 not covered" in M.bug_line([])
          and "bugs: 1 not covered" in M.bug_line(_inv["rows"]))
    check("at27 plan_lines carries one line per PHASE AND TASK and no bug row - "
          "a bug counted among the plan's items would report the ordinary state "
          "of every bug as a gap: %r" % (M.plan_lines(_inv["rows"])[:1],),
          len(M.plan_lines(_inv["rows"])) == 7
          and len([x for x in M.plan_lines(_inv["rows"])
                   if "BUG-1" in x]) == 0)

    # --- the sharded layout: the bug class this feature would have shipped ----
    # An ASSEMBLED phase against the same phase as the INDEX STUB it is stored
    # as. The declaration and the tasks BOTH live in the shard body, so the two
    # fixtures differ in exactly the way `json.load(open(manifestPath))` differs
    # from `_manifest_io.load_manifest(manifestPath)`.
    _assembled = _manifest([_phase("P4", tracked=False,
                                   tasks=[_task("P4.1")])])
    _index = _manifest([{"id": "P4", "title": "P4", "status": "pending",
                         "shard": "phases/P4.json"}])
    _a_rows = M.inventory(_assembled)["rows"]
    check("at30 the ASSEMBLED phase is answered and its task inherits - which "
          "is what the sharded layout looks like once _manifest_io has read the "
          "shard: %r" % ([(r["id"], r["tracked"]) for r in _a_rows],),
          [(r["id"], r["tracked"]) for r in _a_rows]
          == [("P4", False), ("P4.1", False)])
    _i_inv = M.inventory(_index)
    _i_rows = _i_inv["rows"]
    # A `[:1]` slice and never `[0]`: the mutation these cases are for stops the
    # stub row being built at all, and an IndexError in the FORMATTING would
    # abort the suite before `check` ever ran.
    _i_first = (_i_rows[:1] or [{}])[0]
    check("at31 ...and the INDEX STUB is NOT ANSWERED, naming the shard and the "
          "loader. This is the whole point: a raw read of manifestPath sees no "
          "adoTracked on any phase and no task at all, so a resolver that "
          "trusted it would report a deliberately internal plan as TRACKED, by "
          "default, on the layout parallel worktrees use: %r"
          % ([(r["id"], r["tracked"]) for r in _i_rows],),
          [(r["id"], r["tracked"]) for r in _i_rows] == [("P4", None)]
          and "phases/P4.json" in _i_first.get("basis", "")
          and "load_manifest" in _i_first.get("basis", ""))
    check("at32 ...and the refusal fires ONCE, as a warning as well as a basis, "
          "so a caller reading only the warnings still learns it: %r"
          % (_i_inv["warnings"],),
          len(_i_inv["warnings"]) == 1
          and M.counts(_i_rows)["unanswered"] == 1
          and M.counts(_i_rows)["tracked"] == 0)
    check("at33 ...while a phase carrying no shard key warns about NOTHING - "
          "the second direction, and the only case that fails if the stub check "
          "ever becomes unconditional: %r"
          % (M.inventory(_assembled)["warnings"],),
          M.inventory(_assembled)["warnings"] == []
          and M.counts(_a_rows)["unanswered"] == 0)

    # --- the scope a CLI flag names -------------------------------------------
    _rows = _inv["rows"]
    check("at40 --phase covers the tasks under it too, because a task's answer "
          "IS its phase's: a scope returning the phase alone would drop every "
          "row that phase's declaration actually moved: %r"
          % ([r["id"] for r in M.scope_rows(_rows, "phase", "P2")],),
          [r["id"] for r in M.scope_rows(_rows, "phase", "P2")]
          == ["P2", "P2.1", "P2.2"])
    check("at41 ...and --task narrows to the one task, never to its siblings: "
          "%r" % ([r["id"] for r in M.scope_rows(_rows, "task", "P2.1")],),
          [r["id"] for r in M.scope_rows(_rows, "task", "P2.1")] == ["P2.1"]
          and M.scope_rows(_rows, "task", "P2") == [])
    check("at42 ...and the prefix rule does not leak across a shared leading "
          "id: P2 must not reach P20.1",
          [r["id"] for r in M.scope_rows(
              [{"kind": "task", "id": "P20.1"}, {"kind": "task", "id": "P2.1"}],
              "phase", "P2")] == ["P2.1"])
    check("at43 a bug is in NO scope but `all` - it belongs to no phase and is "
          "not a task, so --phase BUG-1 would answer about a bug in a sentence "
          "naming a phase. With the control beside it, or a filter that "
          "excluded everything would pass: %r"
          % ([r["id"] for r in M.scope_rows(_rows, "all", None)],),
          M.scope_rows(_rows, "phase", "BUG-1") == []
          and M.scope_rows(_rows, "task", "BUG-1") == []
          and [r["id"] for r in M.scope_rows(_rows, "phase", "P3")] == ["P3"]
          and len(M.scope_rows(_rows, "all", None)) == len(_rows))
    check("at44 an unknown scope word names nothing rather than falling through "
          "to `phase` - the door turns an empty scope into exit 2 with the name "
          "it could not find, and a silent fall-through would answer a question "
          "nobody asked",
          M.scope_rows(_rows, "bug", "BUG-1") == []
          and M.scope_rows(_rows, "", "P2") == [])

    # --- the three-valued answer, and the predicates that read it -------------
    check("at50 is_tracked and is_untracked are STRICT about identity: a truthy "
          "1 is not True and a falsy 0 is not False, so a manifest carrying a "
          "number cannot be reported as a decision somebody made",
          not M.is_tracked({"tracked": 1})
          and not M.is_untracked({"tracked": 0})
          and M.is_tracked({"tracked": True})
          and M.is_untracked({"tracked": False}))
    check("at51 ...and NEITHER predicate claims the third value: an unanswered "
          "row is not untracked, which is the collapse this whole feature "
          "undoes one layer up",
          not M.is_tracked({"tracked": None})
          and not M.is_untracked({"tracked": None})
          and not M.is_tracked("not a row") and not M.is_untracked(None))

    # --- the manifest shapes a validator would refuse, tolerated on the way down
    check("at52 a manifest whose phases are not a list, and a phase whose tasks "
          "are not a list, yield NO rows rather than raising - a traversal that "
          "took down every read-only consumer of a file the validator is "
          "already about to fail is a second, louder answer to one defect",
          M.inventory({"phases": "nope"})["rows"] == []
          and [r["id"] for r in M.inventory(
              {"phases": [_phase("P1"), "nope"]})["rows"]] == ["P1"]
          and [r["id"] for r in M.inventory(
              {"phases": [{"id": "P1", "tasks": "nope"}]})["rows"]] == ["P1"])
    # Joined rather than indexed, for the reason `_i_first` above is sliced: a
    # mutation that empties the walk must fail this case, not abort the suite.
    _off_file = _manifest([_phase("P1", tasks=[_task("P1.1")])],
                          ado={"phaseWorkItems": False})
    _from_file = " ".join(r["basis"] for r in M.inventory(_off_file)["rows"])
    _overridden = " ".join(r["basis"] for r in
                           M.inventory(_off_file, ado={})["rows"])
    check("at53 meta.ado is read off the manifest when no ado is passed, so the "
          "regime clause is right for a caller that only has the file - and an "
          "explicit ado still WINS, which is what lets a validator resolve "
          "against a config it has already graded: %r"
          % ([_from_file[-40:], _overridden[-40:]],),
          "phaseWorkItems is false" in _from_file
          and "phaseWorkItems is on" not in _from_file
          and "phaseWorkItems is on" in _overridden
          and "phaseWorkItems is false" not in _overridden)

    # at60-at64: the SHAPE CHECK the validator runs. Found by asking
    # `validate-manifest.py` rather than by reading it: `adoParent = "x"` was
    # refused and named, `status = 17` was refused and named, and
    # `adoTracked = "yes"` was ACCEPTED in silence with exit 0 - F203 inverted,
    # the schema forbidding what the validator waved through. Both halves of the
    # rule are cased, because a check that only ever fires is as wrong as one
    # that never does.
    check("at60 an ABSENT declaration is legal and silent - absent means "
          "tracked, the default the whole feature is built around",
          M.declaration_findings({"id": "P1"}, "phase P1") == ([], []))
    for _ok in (True, False):
        check("at61-%r a boolean is legal and silent" % (_ok,),
              M.declaration_findings({"id": "P1", M.FIELD: _ok}, "phase P1")
              == ([], []))
    for _bad, _tag in (("yes", "str"), (1, "int"), (0, "zero"), (None, "null"),
                       ([], "list")):
        _f, _w = M.declaration_findings({"id": "P1", M.FIELD: _bad}, "phase P1")
        check("at62-%s %r is a FINDING, not a warning: a mistyped value puts a "
              "phase ON a board its author was keeping it off, and a warning is "
              "a thing a run continues past: %r" % (_tag, _bad, _f),
              len(_f) == 1 and _w == []
              and "phase P1" in _f[0] and M.FIELD in _f[0])
    # `1` and `0` are the pair that separates a type test from a truthiness test:
    # in Python `True == 1`, so a check reaching for truthiness reads a typo'd
    # `adoTracked: 1` as a declaration and `0` as a false one. Both must be
    # findings, and this case is what goes red if the check is ever relaxed to
    # `if not isinstance(value, (bool, int))`.
    check("at63 an int is refused in BOTH directions, because True == 1 in "
          "Python and a truthiness test would read the typo as a declaration",
          len(M.declaration_findings({"id": "P1", M.FIELD: 1}, "phase P1")[0]) == 1
          and len(M.declaration_findings({"id": "P1", M.FIELD: 0},
                                         "phase P1")[0]) == 1)
    check("at64 the finding names WHERE, so a plan with many phases says which "
          "one: the walk passes `phase P7` and it survives into the sentence",
          [f for f in M.declaration_findings(
              {"id": "P7", M.FIELD: "yes"}, "phase P7")[0] if "phase P7" in f]
          != [])


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__ado_tracked.py --selftest\n")
    raise SystemExit(2)
