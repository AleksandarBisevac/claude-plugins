#!/usr/bin/env python3
"""
The cases for `_manifest_phases.py` — the one walk, and what a phase carries.

`_walk_phases` is the only function in the validator that produces rather than
consumes: it visits each phase and each task once and returns a five-key INDEX
that every check in `_manifest_crossrefs` then reads. The suite treats that
index as the module's real output — a rule that stops emitting a finding is
visible from `validate()`, but an index that quietly stops recording a task id
is not, and it would silently turn four downstream checks into no-ops.

THE WALK STAYS ONE PASS. `task_files` holds only tasks whose `files` is a
non-empty list, because that is the question `_check_file_index` asks of it;
a task with no files is ABSENT rather than mapped to `[]`, and a case pins that
distinction because the fileIndex check reads it with `.items()`.

The per-phase rules here are the ones a schema cannot express: a parallel-run
claim left on a finished phase, an `area` that normalises to no tags at all, a
`budgetUSD` of zero, and a phase marked done over tasks that are not finished —
where FINISHED means done or cancelled, since a cancelled task is settled.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _manifest_phases as M                       # noqa: E402
import _manifest_io as _mio                        # noqa: E402
import _manifest_vocab as _vocab                   # noqa: E402
import _manifest_rules as _rules                   # noqa: E402


def _phase(**kw):
    p = {"id": "P0", "title": "P", "status": "pending", "tasks": []}
    p.update(kw)
    return p


def _task(tid, **kw):
    t = {"id": tid, "title": tid, "status": "pending"}
    t.update(kw)
    return t


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- the index ---
    idx, f, w = M._walk_phases([_phase(tasks=[
        _task("P0.1", files=["src/a.ts"]), _task("P0.2")])])
    check("mp1 the walk records every phase and task id in document order",
          idx["phase_ids"] == ["P0"] and idx["task_ids"] == ["P0.1", "P0.2"],
          idx)
    check("mp2 ...and `task_files` holds ONLY the tasks with a non-empty "
          "`files` list: a task with none is absent rather than mapped to [], "
          "which is exactly the question _check_file_index asks of it",
          idx["task_files"] == {"P0.1": ["src/a.ts"]}, idx["task_files"])
    check("mp3 ...and `task_by_id` indexes the task OBJECT, which is what "
          "makes the bug<->task link checkable from one side",
          idx["task_by_id"]["P0.2"]["title"] == "P0.2", "")
    idx, f, w = M._walk_phases([_phase(tasks=[_task("P0.1", bugId="BUG-1")])])
    check("mp4 ...and a task's bugId is recorded as a (where, id, bugId) link "
          "rather than resolved here - resolution needs the bugs[] half the "
          "walk has not seen",
          idx["bug_links"] == [("task P0.1", "P0.1", "BUG-1")],
          idx["bug_links"])
    idx, f, w = M._walk_phases([_phase(tasks=[])])
    check("mp5 a phase with no tasks still yields every index key, so a "
          "downstream check can read them without asking whether the walk "
          "found anything",
          sorted(idx) == ["bug_links", "phase_ids", "task_by_id", "task_files",
                          "task_ids"], sorted(idx))

    # --- the per-object rules ---
    _, f, _ = M._walk_phases(["not a phase"])
    check("mp6 a non-object phase is a finding naming its index, and the walk "
          "continues rather than raising", len(f) == 1 and "phases[0]" in f[0],
          f)
    _, f, _ = M._walk_phases([_phase(status="doing")])
    check("mp7 a status outside the vocabulary is a finding that prints the "
          "vocabulary", len(f) == 1 and "not in" in f[0], f)
    _, f, _ = M._walk_phases([_phase(status="done", tasks=[
        _task("P0.1", status="pending")])])
    check("mp8 a phase marked done over an unfinished task is a finding - "
          "sign-off means EVERY task is done or cancelled",
          any("not finished" in x for x in f), f)
    _, f, _ = M._walk_phases([_phase(status="done", tasks=[
        _task("P0.1", status="cancelled")])])
    check("mp9 ...but a CANCELLED task is settled, so a phase that signed off "
          "around it is not a slip - the case that fails if TERMINAL is "
          "narrowed back to `done`", f == [], f)

    _, f, w = M._walk_phases([_phase(status="done",
                                     claim={"sessionId": "s", "host": "h",
                                            "branch": "b"})])
    check("mp10 a claim left on a finished phase is a WARNING: it is stale "
          "bookkeeping, not a broken document",
          any("stale claim" in x for x in w), w)
    _, f, w = M._walk_phases([_phase(claim={"sessionId": "s"})])
    check("mp11 ...and a claim missing the keys that identify its holder is a "
          "warning naming them", any("host, branch" in x for x in w), w)
    _, f, w = M._walk_phases([_phase(claim="mine")])
    check("mp12 ...while a non-object claim is a FINDING: it is a shape the "
          "orchestrator would misread", len(f) == 1 and "claim must be" in f[0],
          f)

    _, f, _ = M._walk_phases([_phase(area=3)])
    check("mp13 `area: 3` is a finding, because it normalises to NO tags at "
          "all - the phase silently leaves every grouping and resolves "
          "against no area", len(f) == 1 and "area must be" in f[0], f)
    _, f, _ = M._walk_phases([_phase(area=["app", "web"])])
    check("mp14 ...and a list of tags is legal, which is the case that fails "
          "if the shape check is tightened to a bare string", f == [], f)

    _, f, _ = M._walk_phases([_phase(budgetUSD=0)])
    check("mp15 a budget of zero is a finding pointing at the exit: omit the "
          "key for 'no budget', because a zero renders as a phase at 0%",
          len(f) == 1 and "greater than 0" in f[0], f)
    _, f, _ = M._walk_phases([_phase(budgetUSD=True)])
    check("mp16 ...and a boolean budget is a finding too: bool is an int "
          "subclass, so `true` would otherwise pass as the number 1",
          len(f) == 1 and "must be a number" in f[0], f)

    _, f, w = M._walk_phases([_phase(tasks=[_task("T9")])])
    check("mp17 a task id that does not follow its phase's prefix is a "
          "WARNING, never a finding: legacy free-form ids stay legal",
          f == [] and any("phase's prefix" in x for x in w), (f, w))

    # --- _check_areas, the registry half ---
    f, w = M._check_areas({"meta": {"areas": {"app": {"root": "src"}}},
                           "phases": [_phase(area="app")]})
    check("mp18 a registered tag a phase uses is silent",
          f == [] and w == [], "f=%r w=%r" % (f, w))
    f, w = M._check_areas({"meta": {"areas": {"app": {"root": "src"}}},
                           "phases": [_phase(area="ap")]})
    check("mp19 ...and an unregistered tag is a WARNING once the manifest "
          "registers areas at all, because then it is nearly always a typo",
          f == [] and any("has no entry in meta.areas" in x for x in w), w)
    f, w = M._check_areas({"meta": {}, "phases": [_phase(area="ap")]})
    check("mp20 ...while a project that tags freely and registers NOTHING "
          "gets no warning: that is the v0.16 feature used as designed, and "
          "this is the case that fails if the gate goes away",
          f == [] and w == [], "f=%r w=%r" % (f, w))

    # --- the aliases ---
    _names = ("_check_claim", "_check_area_tag", "_check_areas",
              "_walk_phases")
    _forked = [n for n in _names if getattr(_rules, n) is not getattr(M, n)]
    check("mp21 every name `_manifest_rules` re-exports from here IS this "
          "module's function: %r" % (_forked,), _forked == [])
    check("mp22 ...and TERMINAL here is `_manifest_io`'s tuple, not a second "
          "list of the words that mean finished", M.TERMINAL is _mio.TERMINAL)
    _shared = ("_unknown_keys", "_safe_list", "_require_fields", "_check_ado",
               "STATUS", "TESTS_MODE", "RISK", "CLAIM_KEYS", "KNOWN_PHASE",
               "KNOWN_TASK")
    _drift = [n for n in _shared if getattr(M, n) is not getattr(_vocab, n)]
    check("mp23 ...and every word and shape check it reads is "
          "`_manifest_vocab`'s object: %r" % (_drift,), _drift == [])

    # mp24-mp26: the U-BOARD wiring. `_ado_tracked` owns the rule and this file
    # owns whether the walk ASKS it — two separate failures, and the wiring is the
    # one that disappears without a trace: the rule keeps passing its own suite
    # while no manifest is ever graded by it.
    _ph = _phase(tasks=[_task("P0.1")])
    _ph["adoTracked"] = "yes"
    _idx, _f, _w = M._walk_phases([_ph])
    check("mp24 a phase's mistyped `adoTracked` reaches the walk's findings - "
          "the rule lives in `_ado_tracked`, and this is the case that goes red "
          "if the walk stops asking it: %r" % (_f,),
          [x for x in _f if "adoTracked" in x] != [])
    # THE SCOPE HALF, and it is the direction that would go unnoticed: a task
    # inherits its phase's answer and declares nothing, so a finding on a TASK
    # would be the validator refusing a key the resolver never reads.
    _ph2 = _phase(tasks=[_task("P0.1")])
    _ph2["tasks"][0]["adoTracked"] = "yes"
    _idx2, _f2, _w2 = M._walk_phases([_ph2])
    check("mp25 ...while the same value on a TASK raises no adoTracked finding: "
          "the declaration is a phase's alone and a task inherits, so grading it "
          "here would refuse a key nothing reads: %r" % (_f2,),
          [x for x in _f2 if "adoTracked" in x] == [])
    _ph3 = _phase(tasks=[_task("P0.1")])
    _ph3["adoTracked"] = False
    _idx3, _f3, _w3 = M._walk_phases([_ph3])
    check("mp26 ...and a WELL-FORMED declaration is silent, so the check cannot "
          "be satisfied by one that always fires: %r" % (_f3,),
          [x for x in _f3 if "adoTracked" in x] == [])

    # --- ta: what a `tests.add` entry NAMES, and where it must name one (F294) ---
    # The schema documents `tests.add` as FREE PROSE, and `audit-task.py`'s
    # `files` union treated every entry as a path on F258's premise that a tdd
    # task "creates the file it names in tests.add BY DEFINITION". True of the
    # tasks that name one, false of the field: the scope filled up with
    # assertions and `fileIndex` grew keys no path can ever match.
    #
    # EVERY PARSER FIXTURE BELOW IS A STRING THIS REPOSITORY'S OWN PLAN CARRIES,
    # in both shapes. The writer's premise and the suite's fixtures were once
    # written by one hand and encoded one assumption, so the cases agreed with
    # the parser that a sentence is a path - which is what a hand-written
    # fixture costs when it is a mutation of reality.
    _ta_named = [
        ("test_audit_task.py: an append-only widen is accepted on an "
         "in_progress task", "test_audit_task.py"),
        ("check-git-pipeline.py: the route against a real git repository",
         "check-git-pipeline.py"),
        ("plugins/audit/tests/test__refs.py: a doc telling you to print output "
         "verbatim", "plugins/audit/tests/test__refs.py"),
        ("tests/q.test.ts", "tests/q.test.ts"),
        # Both live `files` entries in this repository's plan, and neither
        # carries an extension - which is the whole reason the dotfile arm
        # exists rather than a bare "must contain a dot" rule.
        (".gitignore: the shard directory is not ignored", ".gitignore"),
        (".gitattributes: assets carry LF only", ".gitattributes"),
    ]
    _ta_wrong = [(e, want, M.tests_add_path(e))
                 for e, want in _ta_named if M.tests_add_path(e) != want]
    check("ta1 the documented `<path>: <what it asserts>` shape yields exactly "
          "its leading path - a bare path with no colon yields itself, and a "
          "DOTFILE counts, because `.gitignore` and `.gitattributes` are both "
          "real entries here and neither has an extension: %r" % (_ta_wrong,),
          _ta_wrong == [])
    _ta_prose = [
        "ado shape cases in validate-manifest --selftest (a1-a4)",
        # BUILT, not written: `_output.prose_number_claims()` reads every `.py`
        # this repo keeps, this suite included, and the live entry really does
        # open with a case count.
        "%d selftest cases incl. exit-code matrix and readiness rule" % (14,),
        "CI runs --gate on this manifest",
        "require-plan selftests a4-a6: custom-path manifest + lock allowed",
        "validator w5: gitRoot/description/details/notes silent",
        "a sub-cent spend renders as <$0.01 through the tile",
        "flaky",
        "P29.3",
        "cli/panel parity: both surfaces agree",
    ]
    _ta_invented = [(e, M.tests_add_path(e))
                    for e in _ta_prose if M.tests_add_path(e) is not None]
    check("ta2 SECOND-DIRECTION CASE: an entry that names no file yields None "
          "and never a token pulled out of prose - a leading word guessed at "
          "would be a path nobody typed, written into `files` and into the "
          "index, which is the same defect one word narrower. Four of these "
          "carry a colon, one is a single word, one ends in a dotted number "
          "and one has a SLASH in its first word, so no single test decides "
          "them all: %r" % (_ta_invented,), _ta_invented == [])
    # F294's own defect, one shape narrower, and it shipped in the first draft:
    # a separator with no filename after it. Driven then - `--tests-add "n/a"`
    # put `n/a` into `files` AND into `fileIndex`, a key no path can match.
    _ta_bare = ["/", "\\", "n/a", "n/a: not applicable here", "docs/",
                "a//b", "/: nothing"]
    _ta_slipped = [(e, M.tests_add_path(e))
                   for e in _ta_bare if M.tests_add_path(e) is not None]
    check("ta2b ...and a SEPARATOR is not a path either: every segment has to "
          "be non-empty and the last one has to look like a filename, so a "
          "bare `/`, an `n/a` and a trailing-slash directory all name no file. "
          "An entry naming a DIRECTORY names no file, which is exactly what "
          "this is asked: %r" % (_ta_slipped,), _ta_slipped == [])
    check("ta3 ...and `P29.3` is not a filename: an extension has to start "
          "with a LETTER, or a bare id would read as a path the moment "
          "somebody wrote one into the field: %r"
          % (M.tests_add_path("P29.3: the widening lands"),),
          M.tests_add_path("P29.3") is None
          and M.tests_add_path("P29.3: the widening lands") is None)
    check("ta4 ...and a non-string, an empty string and whitespace are all "
          "None rather than a crash: the field is free prose, and a manifest "
          "reaches this parser before anything has graded it: %r"
          % ([M.tests_add_path(v) for v in (None, 7, "", "   ", [])],),
          [M.tests_add_path(v) for v in (None, 7, "", "   ", [])]
          == [None] * 5)

    # THE RULE, driven through the WALK it now rides - one phase carrying the
    # same offending entry at four statuses, so what separates the verdicts is
    # the status and nothing else about the task.
    _TA_PROSE = "cart total is correct with two stacked percentage discounts"
    _TA_NAMED = "src/cart/total.ts: two stacked percentage discounts"

    def _ta_walk(rows):
        """(findings, warnings) for one phase of `(id, status, mode, entries)`.

        Through `_walk_phases` and not through a rule of its own, which is the
        point of F294's second draft: the check rides the pass that already
        visits every task with its phase, beside F254's rule about the same
        field. A rule with a walk of its own was a third pass and a second copy
        of this filter.
        """
        tasks = [_task(tid, status=status,
                       tests={"mode": mode, "add": entries,
                              "expectRedFirst": mode == "tdd", "gate": []})
                 for tid, status, mode, entries in rows]
        _idx, _f, _w = M._walk_phases([_phase(status="in_progress",
                                              tasks=tasks)])
        return _f, [x for x in _w if "tests.add" in x]

    _ta_live_f, _ta_live_w = _ta_walk([("P0.1", "pending", "tdd", [_TA_PROSE])])
    _ta_live_one = (_ta_live_w or [""])[0]
    check("ta5 a PENDING tdd task whose tests.add entry names no file is "
          "WARNED about, and the line names the task, the entry and the "
          "release the refusal arrives in - the union promises commit-scope a "
          "path there, so an entry it cannot read is a case file the task will "
          "create and the plan gate will refuse. A warning and not a finding "
          "because COMPATIBILITY.md promises a manifest that validates keeps "
          "validating: enforcement waits for 3.0.0 and this announces it: %r"
          % (_ta_live_w,),
          _ta_live_f == [] and len(_ta_live_w) == 1
          and "P0.1" in _ta_live_one and _TA_PROSE in _ta_live_one
          and "<path>: <what it asserts>" in _ta_live_one
          and "FINDING AT 3.0.0" in _ta_live_one)
    check("ta5b ...and the deprecation SAYS WHEN IT BITES, which is what makes "
          "it a deprecation rather than noise: a reader told only that their "
          "entry is wrong has no reason to act this release, and the pointer "
          "names the promise the change is recorded against: %r"
          % (_ta_live_one[-90:],),
          "3.0.0" in _ta_live_one and "COMPATIBILITY.md" in _ta_live_one)
    # F296's sibling defect, one module over: the first draft emitted
    # `phases[P0].tasks[P0.1]: …`, which is the shape reserved for a task with
    # NO id, so `_warning_groups.locator()` returned None and the line could
    # never be grouped or attributed to its phase - silently opting out of the
    # module built for exactly that. Riding the walk gives it `twhere` for free.
    import _warning_groups as _wg
    _ta_loc = _wg.locator(_ta_live_one)
    check("ta5c ...and the line is ATTRIBUTABLE: `locator()` parses it as a "
          "task-kind line whose ident is the task id, which is what lets the "
          "grouping and the phase attribution reach it. `phases[..].tasks[i]` "
          "is reserved for a task with no id and parses as nothing: %r"
          % (_ta_loc,),
          _ta_loc is not None and _ta_loc[0] == "task"
          and _ta_loc[1] == "P0.1"
          and "%s %s: %s" % _ta_loc == _ta_live_one)
    _ta_prog_f, _ta_prog_w = _ta_walk([("P0.1", "in_progress", "tdd",
                                        [_TA_PROSE]),
                                       ("P0.2", "blocked", "tdd",
                                        [_TA_PROSE])])
    check("ta6 ...and so is an in_progress or blocked one: the rule is about "
          "whether a commit can still be graded against the task, and all "
          "three of those states still have one coming: %r" % (_ta_prog_w,),
          len(_ta_prog_w) == 2 and _ta_prog_f == [])
    _ta_done_f, _ta_done_w = _ta_walk([("P0.1", "done", "tdd", [_TA_PROSE]),
                                       ("P0.2", "cancelled", "tdd",
                                        [_TA_PROSE])])
    check("ta7 SECOND-DIRECTION CASE: a DONE or CANCELLED tdd task carrying "
          "the same entry draws nothing - the exemption is part of the rule "
          "rather than a carve-out, because a settled task's tests.add is a "
          "RECORD and F283 leaves its scope append-only, so a line there would "
          "be permanent with no remedy: %r" % (_ta_done_w,),
          _ta_done_w == [] and _ta_done_f == [])
    _ta_ok_f, _ta_ok_w = _ta_walk([("P0.1", "pending", "tdd",
                                    [_TA_NAMED, "tests/x.spec.ts"])])
    check("ta8 SECOND-DIRECTION CASE: a pending tdd task whose entries all "
          "name a file is silent, findings and warnings alike - a rule that "
          "fires on the shape it is asking for is a rule somebody routes "
          "around: %r" % ((_ta_ok_f, _ta_ok_w),),
          _ta_ok_f == [] and _ta_ok_w == [])
    _ta_other_f, _ta_other_w = _ta_walk([("P0.1", "pending", "regression",
                                          [_TA_PROSE]),
                                         ("P0.2", "pending", "gate-only",
                                          [_TA_PROSE])])
    check("ta9 SECOND-DIRECTION CASE: the same entry on a REGRESSION or "
          "gate-only task says nothing - the field is free prose and most of "
          "this plan's own entries are that shape, so the parse is total "
          "exactly where the union promises something and best-effort "
          "everywhere else: %r" % ((_ta_other_f, _ta_other_w),),
          _ta_other_f == [] and _ta_other_w == [])
    _ta_notdd_f, _ta_notdd_w = _ta_walk([("P0.1", "pending", "regression",
                                          ["a guard for the total"])])
    _ta_empty_idx, _ta_empty_f, _ta_empty_w = M._walk_phases([])
    check("ta10 a plan with no tdd task, and no phase at all, are both silent "
          "- a legitimate input for a body of behaviour-preserving work, and a "
          "line saying so would print on the starter template: %r"
          % ((_ta_notdd_w, _ta_empty_w),),
          _ta_notdd_f == [] and _ta_notdd_w == []
          and (_ta_empty_f, _ta_empty_w) == ([], []))
    # THE VACUITY GUARD, and its shape CHANGED with the move. While the rule
    # had a walk of its own, two counts off the document caught a walk that
    # read nothing. Inside `_walk_phases` there is no second walk to compare
    # against - a count taken from the pass it grades could not fail, which is
    # this suite's own rule about circular verifications - so what makes the
    # silence above meaningful is that the rule rides the pass every other
    # check rides: the INDEX it builds is the evidence the loop ran, and the
    # dozens of cases above would go red with it.
    _ta_tied_tasks = [_task("P0.1", status="pending",
                            tests={"mode": "tdd", "add": [_TA_PROSE],
                                   "expectRedFirst": True, "gate": []})]
    _ta_tied_idx, _ta_tied_f, _ta_tied_w = M._walk_phases(
        [_phase(status="in_progress", tasks=_ta_tied_tasks)])
    check("ta11 the rule rides the SHARED walk, and the index proves the pass "
          "ran: the same call that warns also records the task id, so a loop "
          "that stopped visiting tasks would take this warning and every "
          "downstream check's evidence with it - which is what makes silence "
          "here mean 'nothing was owed' rather than 'nothing was read': %r"
          % ((_ta_tied_idx["task_ids"],
              len([x for x in _ta_tied_w if "tests.add" in x])),),
          _ta_tied_idx["task_ids"] == ["P0.1"]
          and len([x for x in _ta_tied_w if "tests.add" in x]) == 1)
    # #6's reconciliation, pinned rather than argued. F254 asks whether a
    # red-first task named a case AT ALL and reads `expectRedFirst`, which is
    # what DECLARES that intent; this rule asks whether the case it named can be
    # found, and the `files` union it exists for does not read that field at
    # all. So a hand-edited `expectRedFirst: false` exempts one and not the
    # other, and the difference in their guards is the difference in subject.
    _ta_norf = [_task("P0.1", status="pending",
                      tests={"mode": "tdd", "add": [_TA_PROSE],
                             "expectRedFirst": False, "gate": []}),
                _task("P0.2", status="pending",
                      tests={"mode": "tdd", "add": [],
                             "expectRedFirst": False, "gate": []})]
    _ta_rf_idx, _ta_rf_f, _ta_rf_w = M._walk_phases(
        [_phase(status="in_progress", tasks=_ta_norf)])
    check("ta12 `expectRedFirst: false` exempts F254's rule and NOT this one, "
          "which is deliberate: that field declares the red-first intent F254 "
          "is about, and the `files` union this rule exists for never reads "
          "it - so requiring it here would let a hand edit opt a task out of a "
          "rule about a field it has no bearing on: %r"
          % ([x[:60] for x in _ta_rf_w],),
          len([x for x in _ta_rf_w if "tests.add entry names no file" in x]) == 1
          and [x for x in _ta_rf_w if "expectRedFirst and no tests.add" in x]
          == [])
    # #10: a hand-edited string `add` used to yield one warning per non-slash
    # character - ten of them for `"src/a.ts: x"` - which is the warning class
    # people learn to skip. One TYPE finding is the answer, and it is a finding
    # rather than a deprecation because the schema has always declared an array,
    # so a string never validated against it.
    _ta_str = [_task("P0.1", status="pending",
                     tests={"mode": "tdd", "add": "src/a.ts: x",
                            "expectRedFirst": True, "gate": []})]
    _ta_s_idx, _ta_s_f, _ta_s_w = M._walk_phases(
        [_phase(status="in_progress", tasks=_ta_str)])
    check("ta13 a non-array tests.add is ONE type finding and no per-character "
          "warnings - iterating the string produced ten of them, about a shape, "
          "which is exactly the class a reader learns to skip: %r"
          % ((_ta_s_f, [x[:40] for x in _ta_s_w]),),
          len([x for x in _ta_s_f if "tests.add must be an array" in x]) == 1
          and [x for x in _ta_s_w if "names no file" in x] == [])
    _ta_v_f, _ta_v_w = _rules.validate(
        {"meta": {"version": 2}, "phases": [
            _phase(status="in_progress", tasks=[
                _task("P0.1", status="pending",
                      tests={"mode": "tdd", "add": [_TA_PROSE],
                             "expectRedFirst": True, "gate": []})])]})
    check("ta14 ...and the rule reaches `validate()` through the walk, which is "
          "the only reason any of the above is a gate: read off the WARNING "
          "list with the findings asserted empty in the same breath, since a "
          "manifest whose only defect is this shape still validates through "
          "the 2.x line - the promise being kept: %r"
          % ([x[:70] for x in _ta_v_w],),
          any("names no file" in x for x in _ta_v_w) and _ta_v_f == [])


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__manifest_phases.py --selftest\n")
    raise SystemExit(2)
