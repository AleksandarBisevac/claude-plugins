#!/usr/bin/env python3
"""
The cases for `resolve-ado-parent.py` — the door onto `_ado_parent`.

The rules live in `_ado_parent` and have their own suite; what is pinned HERE is
the door, and its exit-code contract is most of it:

- **"no parent anywhere" is EXIT 0.** Uncategorised work is an answer and a
  create, not an error. A door that exited non-zero over it would be switched
  off inside a day, and `conventions.requireParent` is the board saying
  otherwise — graded where the whole plan can be seen, not here.
- **Unreadable input is 2 and never 1.** Saying "this does not belong" about
  something we could not read is the confident wrong answer, and a caller
  reading 1 as a refusal would stop a push over a typo in a path.
- **A scope naming nothing is 2, not a clean 0.** "Resolved: nothing" about an
  id that does not exist reads exactly like a healthy plan.
- **The hierarchy is computed over the WHOLE plan and the VERDICT is scoped.**
  `rp20` is the case: a loop between two phases is still found when the scope is
  one of them, and `rp22` counts the out-of-scope refusals the report has to
  name rather than drop.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import io
import json
import os
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402

import _manifest_rules as _rules                  # noqa: E402

M = _loader.load_script("resolve-ado-parent.py", modname="resolve_ado_parent")

LEVELS = {"Task": 1, "Product Backlog Item": 2, "Feature": 3, "Epic": 4}

# A trimmed capture of `az devops invoke --area work --resource
# backlogconfiguration --route-parameters project=audit-gate-scrum` - Scrum,
# so `bugsBehavior` is `asRequirements` and `requirementBacklog.workItemTypes`
# does not name a bug at all, which is why the behaviour field is the only
# thing that can place one. Trimmed to the fields the rules read.
#
# THE PARSE IS NOT WHAT THIS SUITE PINS. `test__ado_parent.py` owns the full
# capture, the second project that ranks a bug the other way, and every case
# about what the ladder should come out as. What is pinned HERE is the door:
# that the block reaches stdout whole, that it carries THIS manifest's bug
# type, and that a payload nobody could read never becomes an empty ladder.
BACKLOG = {
    "bugsBehavior": "asRequirements",
    "taskBacklog": {"rank": 1, "workItemTypes": [{"name": "Task"}]},
    "requirementBacklog": {"rank": 2,
                           "workItemTypes": [{"name": "Product Backlog Item"}]},
    "portfolioBacklogs": [{"rank": 3, "workItemTypes": [{"name": "Feature"}]},
                          {"rank": 4, "workItemTypes": [{"name": "Epic"}]}],
}


def _manifest(ado, phases):
    return {"meta": {"version": "0.3.0", "ado": ado}, "phases": phases,
            "bugs": []}


def _write(tmp, name, obj):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)
    return path


def _run_full(argv):
    """(exit code, stdout, stderr) — the printed answer is half this command's
    contract, and on the exit-2 paths the SENTENCE is the other half.

    Three different failures share exit 2 here — a payload nobody can open, a
    payload that ranks nothing, and a flag combination that answers nothing —
    and a case reading only the code cannot tell which one it provoked. That is
    the shape where a mutation moves the failure from one branch to another and
    every case stays green.
    """
    out, err = io.StringIO(), io.StringIO()
    real_out, real_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        code = M.main(argv)
    finally:
        sys.stdout, sys.stderr = real_out, real_err
    return (code, out.getvalue(), err.getvalue())


def _run(argv):
    """(exit code, stdout) — `_run_full` for the cases that read no stderr."""
    code, out, _err = _run_full(argv)
    return code, out


def _cases(check):
    # --- argument parsing, before anything reads a file -----------------------
    check("rp1 no arguments is a usage error, not an accidental pass",
          M.main([]) == 2)
    check("rp2 the default scope is every item, so a caller that forgets to "
          "scope gets the whole plan rather than nothing: %r"
          % (M.parse_args(["m.json"])[0],),
          M.parse_args(["m.json"])[0]["scope"] == "all")
    for _argv, _why in ((["m.json", "--phase"], "a scope flag with no id"),
                        (["m.json", "--nope"], "an unknown flag"),
                        (["--json", "m.json"], "no manifest first")):
        _opts, _err = M.parse_args(_argv)
        check("rp3 %s is refused with a sentence rather than parsed into a "
              "default: %r" % (_why, _err), bool(_err))
    check("rp4 a --phase covers the tasks under it too, because a phase whose "
          "own parent is fine and whose tasks close a loop must not read as "
          "clean",
          M.in_scope({"kind": "task", "id": "P3.1"},
                     {"scope": "phase", "target": "P3"})
          and not M.in_scope({"kind": "task", "id": "P30.1"},
                             {"scope": "phase", "target": "P3"}))

    tmp = tempfile.mkdtemp(prefix="qg-adoparent-")
    try:
        # --- exit 2: the input, and only the input ----------------------------
        check("rp10 an unreadable manifest is exit 2 and NEVER 1 - a 1 would "
              "tell the caller this plan does not belong on the board",
              M.main([os.path.join(tmp, "no-such.json")]) == 2)
        _bad = os.path.join(tmp, "broken.json")
        with open(_bad, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        check("rp11 ...and so is a manifest that parses to nothing",
              M.main([_bad]) == 2)

        # --- exit 0: including the answer that looks like a failure -----------
        _none = _write(tmp, "none.json", _manifest(
            {"phaseWorkItems": False},
            [{"id": "P1", "title": "P1", "status": "pending",
              "tasks": [{"id": "P1.1", "title": "t", "status": "pending"}]}]))
        _code, _out = _run([_none])
        check("rp12 a plan with NO parent anywhere is EXIT 0 - uncategorised "
              "work is an answer and a create, not an error: rc=%d" % (_code,),
              _code == 0)
        check("rp13 ...and it SAYS so, with both counts, rather than printing a "
              "clean line that cannot be told from a plan nobody looked at: %r"
              % (_out.splitlines()[:1],),
              "0 refused" in _out and "2 uncategorised" in _out)
        check("rp14 ...and it names the missing basis for the type check "
              "instead of implying the ranks were consulted",
              "not cached" in _out and "not verified" in _out)

        _fine = _write(tmp, "fine.json", _manifest(
            {"parentWorkItem": 41, "phaseWorkItems": False,
             "types": {"pbi": "Product Backlog Item", "task": "Task"},
             "hierarchy": {"levels": LEVELS, "fetchedAt": "2026-08-24T00:00:00Z",
                           "basis": "captured for this case"}},
            [{"id": "P1", "title": "P1", "status": "pending", "ado": {"id": 800},
              "adoParent": {"id": 41, "type": "Feature"},
              "tasks": [{"id": "P1.1", "title": "t", "status": "pending",
                         "ado": {"id": 801},
                         "adoParent": {"id": 800,
                                       "type": "Product Backlog Item"}}]}]))
        _code, _out = _run([_fine])
        check("rp15 a legitimate ladder is exit 0 with nothing refused and "
              "nothing unverified: rc=%d %r" % (_code, _out.splitlines()[-1:]),
              _code == 0 and "0 refused" in _out and "0 not verified" in _out)
        check("rp16 ...and the cached hierarchy's own basis is printed, so a "
              "stale cache can be spotted rather than trusted: %r"
              % ([x for x in _out.splitlines() if "basis:" in x],),
              "captured for this case" in _out)

        # --- exit 1: a violation, and only in scope ---------------------------
        _loop = _write(tmp, "loop.json", _manifest(
            {"types": {"pbi": "Product Backlog Item"}},
            [{"id": "P1", "title": "P1", "status": "pending", "ado": {"id": 501},
              "adoParent": {"id": 500}, "tasks": []},
             {"id": "P2", "title": "P2", "status": "pending", "ado": {"id": 500},
              "adoParent": {"id": 501}, "tasks": []},
             {"id": "P3", "title": "P3", "status": "pending", "tasks": []}]))
        _code, _out = _run([_loop])
        check("rp17 two phases declaring each other is exit 1: rc=%d" % (_code,),
              _code == 1)
        check("rp18 ...and BOTH are named, counted rather than asserted "
              "present - one refusal would leave the other looking creatable: "
              "%r" % ([x for x in _out.splitlines() if "REFUSED [" in x],),
              len([x for x in _out.splitlines() if "REFUSED [" in x]) == 2)
        check("rp19 ...offline, with no meta.ado.hierarchy anywhere in that "
              "manifest - the structural tier needs no cache and no network",
              "not cached" in _out)
        _code, _out = _run([_loop, "--phase", "P1"])
        check("rp20 the loop is still found when the scope is ONE of the two "
              "phases, because a loop is a property of the graph and not of the "
              "item asked about: rc=%d" % (_code,),
              _code == 1)
        check("rp21 ...and the scope narrows the REPORT to that phase: %r"
              % ([x for x in _out.splitlines() if " -> " in x],),
              len([x for x in _out.splitlines() if " -> " in x]) == 1)
        # The bug this file found on the way: the printed refusals and the exit
        # code came from two separate walks, so a scoped run could exit 1 over a
        # loop it did not print. One walk, narrowed - and the case counts.
        check("rp28 ...and what it PRINTS as refused is what it exited over - "
              "one walk narrowed, never a second walk over the scoped rows: %r"
              % ([x for x in _out.splitlines() if "REFUSED [" in x],),
              len([x for x in _out.splitlines() if "REFUSED [" in x]) == 1
              and "1 refused" in _out)
        check("rp22 ...and the refusal it did NOT ask about is counted and "
              "named rather than dropped: %r"
              % ([x for x in _out.splitlines() if "outside this scope" in x],),
              "outside this scope: 1 refusal(s)" in _out and "P2" in _out)
        _code, _out = _run([_loop, "--phase", "P3"])
        check("rp23 ...and a phase that is clean stays exit 0 even while the "
              "plan around it is not - the verdict answers the question that "
              "was asked: rc=%d" % (_code,),
              _code == 0 and "outside this scope: 2 refusal(s)" in _out)
        check("rp24 a scope naming nothing is exit 2, not a clean 0 - "
              "'resolved: nothing' about an id that does not exist reads "
              "exactly like a healthy plan",
              M.main([_loop, "--phase", "P9"]) == 2
              and M.main([_loop, "--task", "P9.9"]) == 2)

        # --- --json carries the same verdict ----------------------------------
        _code, _out = _run([_loop, "--json"])
        _doc = json.loads(_out)
        check("rp25 --json exits with the SAME code as the printed form, so a "
              "script and a person cannot disagree about a board: rc=%d"
              % (_code,),
              _code == 1 and len(_doc["refusals"]) == 2)
        _code, _out = _run([_none, "--json"])
        _doc = json.loads(_out)
        check("rp26 ...and it carries `checked` so a consumer can tell 'nothing "
              "was wrong' from 'nothing was looked at': %r" % (_doc["checked"],),
              _code == 0 and _doc["checked"] == 0 and _doc["rows"])

        # --- the two surfaces, pinned as disagreeing ON PURPOSE ---------------
        # A MANIFEST is not a PAYLOAD. `validate-manifest.py` grades a file
        # somebody keeps in their repository, under a promise that a file which
        # validates keeps validating; this command grades a link the connector
        # is about to create, under no such promise. A loop reachable through
        # `meta.ado.parentWorkItem` ALONE - no adoParent anywhere, so the file
        # could predate the key - is the one shape where the two must answer
        # differently, and a board that cannot be built still cannot be built.
        _legacy = {"meta": {"version": 2, "ado": {"parentWorkItem": 31}},
                   "phases": [{"id": "P1", "title": "P1", "status": "pending",
                               "ado": {"id": 30},
                               "tasks": [{"id": "P1.1", "title": "t",
                                          "status": "pending",
                                          "ado": {"id": 31}}]}],
                   "bugs": []}
        _legacy_path = _write(tmp, "legacy.json", _legacy)
        _code, _out = _run([_legacy_path])
        check("rp30 push REFUSES a loop inherited from meta.ado.parentWorkItem "
              "- exit 1, both members named - because the link is one ADO would "
              "accept and nothing could then unbuild: rc=%d %r"
              % (_code, [x for x in _out.splitlines() if "REFUSED [" in x]),
              _code == 1
              and len([x for x in _out.splitlines() if "REFUSED [" in x]) == 2)
        check("rp31 ...while `validate()` calls that SAME manifest valid, "
              "because a file that validates must keep validating and this one "
              "carries no adoParent at all. The two surfaces disagreeing here "
              "is the design, and this is the case that fails if either side "
              "is 'simplified' into the other: %r"
              % (_rules.validate(_legacy)[0],),
              _rules.validate(_legacy)[0] == []
              and len([x for x in _rules.validate(_legacy)[1]
                       if "loop" in x]) == 2)
        # The control: the same board written with an adoParent. Both surfaces
        # refuse, so rp30/rp31 cannot be satisfied by a door that always exits 1
        # and a validator that never finds anything.
        _authored = {"meta": {"version": 2, "ado": {}},
                     "phases": [{"id": "P1", "title": "P1",
                                 "status": "pending", "ado": {"id": 30},
                                 "adoParent": {"id": 31},
                                 "tasks": [{"id": "P1.1", "title": "t",
                                            "status": "pending",
                                            "ado": {"id": 31}}]}],
                     "bugs": []}
        _authored_path = _write(tmp, "authored.json", _authored)
        check("rp32 ...and with the parent AUTHORED instead, both surfaces "
              "refuse: the door exits 1 and the manifest is invalid, which is "
              "the direction that is fully additive because no older file can "
              "carry the key: rc=%d" % (M.main([_authored_path]),),
              M.main([_authored_path]) == 1
              and len(_rules.validate(_authored)[0]) == 2)

        # --- the inert declaration reaches the operator -----------------------
        _inert = _write(tmp, "inert.json", _manifest(
            {"types": {"pbi": "Product Backlog Item"}},
            [{"id": "P1", "title": "P1", "status": "pending", "ado": {"id": 700},
              "tasks": [{"id": "P1.1", "title": "t", "status": "pending",
                         "adoParent": {"id": 900}}]}]))
        _code, _out = _run([_inert])
        check("rp27 a task's adoParent under phaseWorkItems is reported as "
              "INERT rather than silently ignored, and the run still exits 0 "
              "because nothing about it is unbuildable: rc=%d" % (_code,),
              _code == 0
              and len([x for x in _out.splitlines()
                       if x.startswith("WARNING:") and "INERT" in x]) == 1)
        # --- bugs: asked about here, and reported apart (F101) ----------------
        # WHAT WAS MISSING WAS THE MANIFEST SIDE. `status` fetches a linked
        # bug's `System.Parent` like any other item's, and this door walked
        # phases and tasks only - so a linked bug got no `parent?` verdict and
        # none of that feature's wordings covered "we did not ask about this
        # kind of item". The ids differ from the fallback throughout: a fixture
        # where the declared parent and `parentWorkItem` agree cannot tell a
        # declaration from a fallback.
        _bugs = _write(tmp, "bugs.json", {
            "meta": {"version": 2,
                     "ado": {"parentWorkItem": 41,
                             "types": {"pbi": "Product Backlog Item",
                                       "task": "Task", "bug": "Bug"},
                             "hierarchy": {"levels": LEVELS,
                                           "fetchedAt": "2026-08-24T00:00:00Z",
                                           "basis": "captured for this case"}}},
            "phases": [{"id": "P1", "title": "P1", "status": "pending",
                        "ado": {"id": 800}, "tasks": []}],
            "bugs": [{"id": "BUG-1", "title": "off the board", "status": "open",
                      "ado": {"id": 900},
                      "adoParent": {"id": 101, "type": "Epic",
                                    "source": "imported",
                                    "observedAt": "2026-08-24T09:00:00Z"}},
                     {"id": "BUG-2", "title": "linked, undeclared",
                      "status": "open", "ado": {"id": 901}},
                     {"id": "BUG-3", "title": "not linked", "status": "open"}]})
        _code, _out = _run([_bugs, "--json"])
        _doc = json.loads(_out)
        _brows = dict((r["id"], r) for r in _doc["rows"] if r["kind"] == "bug")
        check("rp40 every bug gets a row, so a linked one has a manifest side "
              "to compare a fetched System.Parent against - the gap that left "
              "`status` with a cell it could not fill: %r" % (sorted(_brows),),
              sorted(_brows) == ["BUG-1", "BUG-2", "BUG-3"]
              and (_brows.get("BUG-1") or {}).get("parent") == 101
              and (_brows.get("BUG-1") or {}).get("workItemId") == 900
              # ...and `checked` still counts only the links this command would
              # create. BUG-1 carries a parent, so a count that walked every
              # row would read 2 here and tell a consumer the hierarchy check
              # looked at a link it has no opinion about.
              and _doc["checked"] == 1)
        # `.get` and never `[]`, including in the message: the mutation these
        # cases are for stops the bug rows being built at all, and a KeyError
        # in the FORMATTING would abort the suite before `check` ever ran.
        _b2 = _brows.get("BUG-2") or {}
        check("rp41 ...and an undeclared bug resolves to NO parent rather than "
              "to meta.ado.parentWorkItem #41, which is the audit's own branch "
              "- a bug reported as drifting from a link no push was going to "
              "make is a false alarm about somebody else's card: %r"
              % (_b2.get("parent"),),
              "BUG-2" in _brows and _b2.get("parent") is None
              and _b2.get("source") == "none"
              and "41" in (_b2.get("basis") or ""))
        _code, _out = _run([_bugs])
        check("rp42 the printed plan still counts PHASES AND TASKS: a bug with "
              "no parent is the ordinary state of every bug, and counting it "
              "among the plan's uncategorised items would report that as a gap: "
              "%r" % (_out.splitlines()[0],),
              _code == 0 and "1 item(s)" in _out.splitlines()[0]
              and "0 uncategorised" in _out.splitlines()[0]
              and len([x for x in _out.splitlines() if " -> " in x]) == 1)
        check("rp43 ...and one line names the bugs instead, with BOTH counts, "
              "so 'this manifest has no bugs' and 'nobody asked about bugs' "
              "cannot print the same way: %r"
              % ([x for x in _out.splitlines() if "bugs:" in x],),
              "bugs: 3 resolved, 2 linked" in _out)
        _code, _out = _run([_none])
        check("rp44 ...and it prints AT ZERO, on the manifest with no bugs at "
              "all - a count that appears only when there is something to "
              "count cannot be told from a count nobody took: %r"
              % ([x for x in _out.splitlines() if "bugs:" in x],),
              "bugs: 0 resolved, 0 linked" in _out)
        # A bug of type Bug ranks 2 here and #800 is a Product Backlog Item at
        # rank 2 - so the phase's own link is legal and the bug's would be a
        # NOTE at most. What this case is for is the exit code: nothing about a
        # bug may change it, because nothing about a bug is being created.
        _bug_only = _write(tmp, "bug-inverted.json", {
            "meta": {"version": 2,
                     "ado": {"types": {"pbi": "Product Backlog Item",
                                       "bug": "Bug"},
                             "hierarchy": {"levels": LEVELS,
                                           "fetchedAt": "2026-08-24T00:00:00Z",
                                           "basis": "captured for this case"}}},
            "phases": [{"id": "P1", "title": "P1", "status": "pending",
                        "ado": {"id": 800}, "tasks": []}],
            "bugs": [{"id": "BUG-1", "title": "under a Task", "status": "open",
                      "ado": {"id": 900},
                      "adoParent": {"id": 801, "type": "Task",
                                    "source": "imported"}}]})
        _code, _out = _run([_bug_only])
        check("rp45 a bug hanging under a lower-ranked type is exit 0 and no "
              "refusal: the pair is the wrong way round on somebody's board, "
              "and this command refuses LINKS IT WOULD CREATE - it creates no "
              "bug parent link at all: rc=%d %r"
              % (_code, [x for x in _out.splitlines() if "REFUSED" in x]),
              _code == 0
              and len([x for x in _out.splitlines() if "REFUSED" in x]) == 0
              and "0 not verified" in _out)
        check("rp47 a bug is not a phase and is under none, so no scope flag "
              "reaches one: `--phase BUG-3` is exit 2 - the same answer an id "
              "that does not exist gets - rather than a report about a bug in "
              "a sentence that names a phase: rc=%d"
              % (M.main([_bugs, "--phase", "BUG-3"]),),
              not M.in_scope({"kind": "bug", "id": "BUG-3"},
                             {"scope": "phase", "target": "BUG-3"})
              and not M.in_scope({"kind": "bug", "id": "BUG-3"},
                                 {"scope": "task", "target": "BUG-3"})
              # The control, or a guard that excluded EVERYTHING would pass.
              and M.in_scope({"kind": "phase", "id": "P1"},
                             {"scope": "phase", "target": "P1"})
              and M.main([_bugs, "--phase", "BUG-3"]) == 2)
        check("rp46 ...and a --phase scope reaches no bug, while the bug line "
              "still reports the whole manifest - a scoped run printing '0 "
              "bugs' would answer about P1 in a sentence that reads as a fact "
              "about the file: %r"
              % ([x for x in _run([_bugs, "--phase", "P1"])[1].splitlines()
                  if "bugs:" in x],),
              "bugs: 3 resolved, 2 linked" in _run([_bugs, "--phase", "P1"])[1]
              and len([x for x in _run([_bugs, "--phase", "P1"])[1].splitlines()
                       if " -> " in x]) == 1)

        # --- the ladder mode: the block `/audit:sync parents` writes ----------
        # F157. `levels_from_backlog_config` had no caller at all: the command
        # file, the reference doc and the connector guide each carried the RULE
        # for building `meta.ado.hierarchy` by hand, and the rule had moved
        # under them - the bug rung's rank comes from `bugsBehavior` and its
        # NAME from `meta.ado.types.bug` (F143), so prose telling a reader to
        # write `Bug` filed that rank under a name no work item carries on a
        # board that renamed the type.
        _payload = _write(tmp, "backlogconfig.json", BACKLOG)
        _code, _out = _run([_none, "--hierarchy-from", _payload])
        _block = json.loads(_out)
        check("rp50 --hierarchy-from prints meta.ado.hierarchy WHOLE - the "
              "ranks, the basis and the moment - so the caller writes an "
              "answer instead of assembling one from a rule in prose: rc=%d %r"
              % (_code, sorted(_block)),
              _code == 0
              and sorted(_block) == ["basis", "fetchedAt", "levels"]
              and _block["levels"] == dict(LEVELS, Bug=2)
              and "backlogconfiguration" in _block["basis"])
        _renamed = _write(tmp, "renamed.json", _manifest(
            {"types": {"pbi": "Product Backlog Item", "bug": "Defect"},
             "phaseWorkItems": False}, []))
        _code, _out = _run([_renamed, "--hierarchy-from", _payload])
        _rblock = json.loads(_out)
        check("rp51 ...and the bug rung is filed under THIS board's bug type "
              "rather than the literal the three documents taught - which is "
              "why the manifest is still the first argument: the payload gave "
              "the rank and meta.ado.types.bug gave the name: %r"
              % (_rblock["levels"],),
              _code == 0
              and _rblock["levels"].get("Defect") == 2
              and "Bug" not in _rblock["levels"]
              # The rung MOVED rather than being added beside the old one, and
              # the basis names it exactly once - a second mention would mean a
              # second spelling reached the block.
              and len(_rblock["levels"]) == len(_block["levels"])
              and _rblock["basis"].count("'Defect'") == 1)
        # The CONSEQUENCE, end to end, because rp51 alone would pass on a door
        # that printed the right key into a block nothing reads. #801 is typed
        # with the board's own bug name at rank 2 and the phase is a Product
        # Backlog Item at rank 2: an equal-rank note, which is a graded answer.
        # Under a ladder built the way the prose taught, the same link came
        # back `not verified` - the one verdict that means nobody looked.
        _graded = _write(tmp, "graded.json", _manifest(
            {"types": {"pbi": "Product Backlog Item", "bug": "Defect"},
             "hierarchy": _rblock},
            [{"id": "P1", "title": "P1", "status": "pending",
              "ado": {"id": 800}, "tasks": [],
              "adoParent": {"id": 801, "type": "Defect",
                            "source": "declared"}}]))
        _code, _out = _run([_graded])
        check("rp52 ...and the block this door PRINTED is the block the "
              "resolver READS: a parent typed with the board's own bug name is "
              "graded instead of reporting `not verified`: rc=%d %r"
              % (_code, [x for x in _out.splitlines() if "hierarchy:" in x]),
              _code == 0 and "0 not verified" in _out
              and len([x for x in _out.splitlines() if "REFUSED" in x]) == 0)
        _junk = _write(tmp, "not-backlog.json", {"bugsBehavior": "asTasks"})
        _code, _out, _err = _run_full([_none, "--hierarchy-from", _junk])
        check("rp53 a payload that ranks no backlog level is exit 2 with "
              "NOTHING on stdout - an unreadable answer cached as an empty "
              "ladder reads as a project that ranks nothing, which is the "
              "shape that turns the type check off: rc=%d %r" % (_code, _out),
              _code == 2 and _out == ""
              and "ranks no backlog level" in _err)
        _missing = os.path.join(tmp, "no-such-payload.json")
        _code, _out, _err = _run_full([_none, "--hierarchy-from", _missing])
        check("rp54 ...and so is a payload nobody can OPEN - a different "
              "failure under the same exit code, so the sentence names the "
              "file rather than reporting it as a board that ranks nothing: "
              "rc=%d %r" % (_code, _err.strip()[:80]),
              _code == 2 and _out == ""
              and "cannot read/parse the backlogconfiguration payload" in _err
              and _missing in _err)
        for _extra in (["--phase", "P1"], ["--task", "P1.1"], ["--json"],
                       ["--all"]):
            _code, _out, _err = _run_full(
                [_none, "--hierarchy-from", _payload] + _extra)
            check("rp55 %s cannot narrow a question about the PROJECT's "
                  "ladder, so it is refused with a sentence NAMING it rather "
                  "than accepted and quietly ignored: rc=%d %r"
                  % (_extra[0], _code, _out),
                  _code == 2 and _out == "" and _extra[0] in _err)
        check("rp56 ...and the control, because a guard that refused every "
              "combination would pass rp55 while making the mode unreachable",
              _run([_none, "--hierarchy-from", _payload])[0] == 0)
        # The second direction, and it looks vacuous on purpose: it passes by
        # construction on the code before this flag existed, and it is the only
        # case that fails if the ladder mode ever stops being opt-in.
        _code, _out = _run([_none])
        check("rp57 a run with no --hierarchy-from still answers about the "
              "ITEMS and prints no ladder block - the mode is a flag, not a "
              "second thing every run does: rc=%d %r"
              % (_code, _out.splitlines()[:1]),
              _code == 0 and "parents:" in _out and '"levels"' not in _out)
    finally:
        for name in sorted(os.listdir(tmp)):
            os.remove(os.path.join(tmp, name))
        os.rmdir(tmp)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_resolve_ado_parent.py --selftest\n")
    raise SystemExit(2)
