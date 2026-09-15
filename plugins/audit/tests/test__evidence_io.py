#!/usr/bin/env python3
"""
The cases for `governance/_evidence_io.py` - where the test-evidence record lives.

WHAT IS PROVEN HERE, and why each half has a partner. The directory is DERIVED
from `manifestPath` rather than hardcoded, so every case that asserts the default
is paired with one that moves the manifest and asserts the record moved with it -
a resolver that ignored its input would satisfy the first alone forever.

The membership test is a PREFIX comparison, and a prefix comparison written
without its separator admits every sibling whose name merely starts the same way.
So `ev6` is the boundary from the outside, and it is the case that fails when the
test is weakened rather than when it is broken.

The resolution is deliberately the JOURNAL's, one directory over: both answer
"where does this manifest keep its committed record", and two expressions of that
would separate the trail from the evidence the first time a repo set an unusual
`manifestPath`. `ev3` asserts the two agree on the same config rather than
asserting a literal, because a literal would keep agreeing after they diverged.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import io
import json
import os
import subprocess
import shutil
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _evidence_io as M                           # noqa: E402
import _journal_io                                 # noqa: E402
import _locks                                      # noqa: E402


def _project(root, config=None):
    """A project directory with a config, or with none at all."""
    os.makedirs(os.path.join(root, ".claude"), exist_ok=True)
    if config is not None:
        with open(os.path.join(root, ".claude", "audit.config.json"),
                  "w", encoding="utf-8") as fh:
            json.dump(config, fh)
    return root


def _cases(check):
    tmp = _harness.fixture_root("audit-evidence-")
    try:
        # --- where it lives ---------------------------------------------------
        plain = _project(os.path.join(tmp, "plain"), {})
        got = M.evidence_dir(plain)
        check("ev1 with no `evidence` block the record sits beside the manifest, "
              "under the default dirname - and the assertion is against the "
              "manifest's OWN directory rather than a spelled-out path, so it "
              "still holds if the default manifest moves: %r" % (got,),
              got == os.path.normpath(os.path.join(
                  plain, os.path.dirname(_journal_io.DEFAULT_MANIFEST),
                  M.DEFAULT_DIRNAME)))

        moved = _project(os.path.join(tmp, "moved"),
                         {"manifestPath": "plans/audit/plan.json"})
        got_moved = M.evidence_dir(moved)
        check("ev2 ...and the pair that proves it is DERIVED: move `manifestPath` "
              "and the record moves with it. A resolver that ignored its input "
              "would pass ev1 forever: %r" % (got_moved,),
              got_moved == os.path.normpath(
                  os.path.join(moved, "plans", "audit", M.DEFAULT_DIRNAME))
              and os.path.basename(os.path.dirname(got_moved)) == "audit")

        cfg = {"manifestPath": "plans/audit/plan.json"}
        check("ev3 the evidence directory and the journal directory are SIBLINGS "
              "under one manifest - asserted by comparing the two resolvers on "
              "the same config, not against a literal, because a literal keeps "
              "agreeing after they diverge: %r vs %r"
              % (M.evidence_dir(moved, cfg), _journal_io.journal_dir(moved, cfg)),
              os.path.dirname(M.evidence_dir(moved, cfg))
              == os.path.dirname(_journal_io.journal_dir(moved, cfg))
              and M.evidence_dir(moved, cfg)
              != _journal_io.journal_dir(moved, cfg))

        pinned = _project(os.path.join(tmp, "pinned"),
                          {"evidence": {"dir": "var/evidence"}})
        check("ev4 an explicit `evidence.dir` wins over the derivation, which is "
              "what makes the key worth reading at all: %r"
              % (M.evidence_dir(pinned),),
              M.evidence_dir(pinned)
              == os.path.normpath(os.path.join(pinned, "var", "evidence")))

        blank = _project(os.path.join(tmp, "blank"), {"evidence": {"dir": "   "}})
        check("ev5 ...and a blank one does NOT win - it falls back to the "
              "derivation rather than resolving to the project root, which is "
              "where a bare `os.path.join` would have put the whole record: %r"
              % (M.evidence_dir(blank),),
              M.evidence_dir(blank) == os.path.normpath(os.path.join(
                  blank, os.path.dirname(_journal_io.DEFAULT_MANIFEST),
                  M.DEFAULT_DIRNAME))
              and M.evidence_dir(blank) != os.path.normpath(blank))

        # --- membership -------------------------------------------------------
        home = M.evidence_dir(plain)
        os.makedirs(home, exist_ok=True)
        inside = os.path.join(home, "2026-08.w.jsonl")
        check("ev6 a file in the directory is inside it, and a SIBLING whose name "
              "merely starts the same way is not. The pair is the point: a prefix "
              "test written without its separator passes the first half and "
              "admits the second",
              M.in_evidence(plain, inside) is True
              and M.in_evidence(plain, home + "-notes/x.jsonl") is False)

        check("ev7 the directory itself counts as inside, and an unrelated path "
              "does not - the two ends of the same comparison",
              M.in_evidence(plain, home) is True
              and M.in_evidence(plain, os.path.join(plain, "src", "a.py")) is False)

        check("ev8 a project-relative path is resolved against the project, so a "
              "caller holding the spelling git prints does not have to make it "
              "absolute first",
              M.in_evidence(plain, os.path.relpath(inside, plain)) is True)

        check("ev9 a non-string path is False rather than an exception: this "
              "answers a guard's question, and a guard that raises on a payload "
              "it did not expect is a guard that is off",
              M.in_evidence(plain, None) is False
              and M.in_evidence(plain, 17) is False)

        # --- the row, and what it may not carry ---------------------------
        RESULT = {
            "status": "failed", "durationMs": 1200, "failed": ["unit"],
            "ranTotal": None, "coverageBasis": "the runner named 2 path(s)",
            "treeBasis": "git described the tree before and after",
            "treeMutated": [], "overlap": ["src/a.py"],
            "testedState": {"head": "abc1234", "headBasis": "b",
                            "scopeDigest": "sha256:1", "scopeBasis": "s",
                            "dirtyDigest": "sha256:2", "dirtyBasis": "d"},
            "steps": [{"name": "unit", "command": "pytest -q", "exit": 1,
                       "ran": None, "durationMs": 1100}],
            # Anything a caller invents. Runner output is where a stack trace
            # carrying a home directory or a token would arrive, so the sentinel
            # stands in for that class without this file having to spell one.
            "rawOutput": "SENTINEL-MUST-NOT-BE-STORED",
        }
        IDENT = {"runId": "R1", "attempt": 2, "via": "orchestrator",
                 "sessionId": "sess-1"}
        row = M.row_for(plain, RESULT, "task",
                        {"taskId": "P1.2", "phaseId": "P1"}, IDENT,
                        published=["pytest -q"])
        check("ev10 an unknown key a caller invents is DROPPED, not carried. "
              "The row is assembled from named fields, which is what makes the "
              "SHAPE of a row a property of the WRITER rather than a habit "
              "every call site has to remember. Runner output has exactly one "
              "route in and it is `failing`, which `ef1`-`ef3` hold to the two "
              "rules that route is allowed on: %r"
              % (sorted(row),),
              "rawOutput" not in row
              and "SENTINEL" not in _journal_io.canonical(row))

        check("ev11 the row carries the identity a reader joins on, and the "
              "scope whose pointer this run is eligible to move - a run "
              "recorded without saying whose it was could never be pointed "
              "back at the plan. WHICH GATE ran is a different question and "
              "ev35 is where it is asked; this clause used to say `the scope it "
              "was measured at`, which is the misreading that made F312 "
              "invisible for as long as one value answered both",
              row["runId"] == "R1" and row["scope"] == "task"
              and row["taskId"] == "P1.2" and row["phaseId"] == "P1"
              and row["attempt"] == 2 and row["via"] == "orchestrator")

        check("ev12 a command the MANIFEST publishes is stored verbatim - it is "
              "already committed in the plan, in plain text, so storing it "
              "exposes nothing new. That is the journal's own third test for a "
              "new field, applied here: %r" % (row["steps"][0].get("command"),),
              row["steps"][0].get("command") == "pytest -q")

        row_ad_hoc = M.row_for(plain, RESULT, "task",
                               {"taskId": "P1.2", "phaseId": "P1"}, IDENT,
                               published=[])
        st = row_ad_hoc["steps"][0]
        check("ev13 ...and one the manifest does NOT publish falls back to a "
              "digest, a byte length and a program name. The pair is the point: "
              "either half alone passes with the rule inverted, and an ad-hoc "
              "command is the one that can carry a path or a token: %r"
              % (sorted(st),),
              "command" not in st and st.get("program") == "pytest"
              and st.get("commandSha256") and st.get("commandBytes"))

        wide = dict(RESULT)
        wide["steps"] = [{"name": "s%d" % i, "command": "pytest -q", "exit": 0,
                          "ran": None, "durationMs": 1}
                         for i in range(M.MAX_STEPS + 5)]
        wide["treeMutated"] = ["f%d.py" % i for i in range(M.MAX_PATHS + 7)]
        rw = M.row_for(plain, wide, "phase", {"phaseId": "P1"}, IDENT,
                       published=["pytest -q"])
        check("ev14 a row too wide is cut AND SAYS SO, with what went counted. "
              "A silent truncation reads as 'that is all there was', which is "
              "the one thing a record must never imply: %r"
              % ((len(rw["steps"]), rw.get("stepsDropped"),
                  len(rw["treeMutated"]), rw.get("treeMutatedDropped")),),
              len(rw["steps"]) == M.MAX_STEPS and rw.get("stepsDropped") == 5
              and len(rw["treeMutated"]) == M.MAX_PATHS
              and rw.get("treeMutatedDropped") == 7)

        narrow = M.row_for(plain, RESULT, "task",
                           {"taskId": "P1.2", "phaseId": "P1"}, IDENT,
                           published=["pytest -q"])
        check("ev15 ...and a row that FIT carries no dropped-count at all - a "
              "count that appears only when non-zero cannot be told from a "
              "count nobody computed, so the absence has to mean something",
              "stepsDropped" not in narrow
              and "treeMutatedDropped" not in narrow)

        outside = dict(RESULT)
        outside["treeMutated"] = [os.path.join(tmp, "elsewhere.py"), "src/a.py"]
        ro = M.row_for(plain, outside, "task", {"taskId": "P1.2"}, IDENT,
                       published=["pytest -q"])
        check("ev16 a path outside the repository is stored as the token, never "
              "as itself - this file is COMMITTED, and an absolute path in it "
              "names somebody's machine in a repository that goes to clients: %r"
              % (ro["treeMutated"],),
              _journal_io.OUTSIDE_TOKEN in ro["treeMutated"]
              and not any(x.startswith(tmp) for x in ro["treeMutated"])
              and "src/a.py" in ro["treeMutated"])

        porcelain = dict(RESULT)
        porcelain["treeMutated"] = [" M src/a.py", "?? src/new.py",
                                    "R  old.py -> src/renamed.py"]
        rp = M.row_for(plain, porcelain, "task", {"taskId": "P1.2"}, IDENT,
                       published=["pytest -q"])
        check("ev24 `treeMutated` arrives as git PORCELAIN LINES, not paths - "
              "`XY <path>`, and `XY <old> -> <new>` for a rename, where the new "
              "name is the one that exists now. Storing the line verbatim would "
              "put a two-character status code where a reader expects a file: %r"
              % (rp["treeMutated"],),
              rp["treeMutated"] == ["src/a.py", "src/new.py", "src/renamed.py"])

        check("ev25 a step's `ran` keeps its None. It is three-valued and None "
              "means 'not knowable from this runner' - dropping the key would "
              "leave a reader unable to tell that from zero, which is the "
              "distinction the whole count exists to make: %r"
              % (row["steps"][0],),
              "ran" in row["steps"][0] and row["steps"][0]["ran"] is None
              and row["observations"]["ranTotal"] is None)

        check("ev26 ...and the three-valued OBSERVATIONS keep their shape too: "
              "an empty list and a None are different answers about the tree, "
              "and a row that flattened either would hand every reader the "
              "conflation the runner was rewritten to avoid: %r"
              % ((row["observations"]["treeMutated"],
                  row["observations"]["coverage"]),),
              row["observations"]["treeMutated"] == []
              and row["observations"]["coverage"] == ["src/a.py"])

        unknown_tree = dict(RESULT)
        unknown_tree["treeMutated"] = None
        unknown_tree["overlap"] = None
        ru = M.row_for(plain, unknown_tree, "task", {"taskId": "P1.2"}, IDENT,
                       published=["pytest -q"])
        check("ev27 ...and the pair that proves it: an UNKNOWN tree and an "
              "unknown coverage stay None through the row, never becoming the "
              "empty list a truthy reader would call clean: %r"
              % ((ru["observations"]["treeMutated"],
                  ru["observations"]["coverage"], ru["treeMutated"]),),
              ru["observations"]["treeMutated"] is None
              and ru["observations"]["coverage"] is None
              and ru["treeMutated"] is None)

        # --- ef: the one field whose content a RUNNER wrote -------------------
        # A red row used to carry the status, the failing gate ENTRY names and a
        # check count, and nothing about which TESTS failed - so the operator
        # re-ran the gate to find out, which is the one action that destroys the
        # output they were after. `failing` is that text carried. It is also the
        # only value on a row this plugin did not compose, so the two rules that
        # keep a committed row safe both land here.
        _leak_user = "somebody"
        _fail_step = dict(RESULT["steps"][0])
        _fail_step["failing"] = [
            "totals > applies the bulk discount",
            "    at Object.<anonymous> (/Users/%s/work/shop/a.test.ts:12:5)"
            % (_leak_user,)]
        _fail_step["failingBasis"] = ("the 2 check(s) jest named as failing, "
                                      "read from its own failure lines")
        _with_fail = dict(RESULT)
        _with_fail["steps"] = [_fail_step]
        _rf = M.row_for(plain, _with_fail, "task", {"taskId": "P1.2"}, IDENT,
                        published=["pytest -q"])
        check("ef1 the names CROSS INTO THE ROW, which is the half `STEP_KEYS` "
              "decides: a key the allow-list does not name is dropped in "
              "silence, so the answer would exist in memory for the length of "
              "the run and be absent from the only copy anybody reads "
              "afterwards - which is the defect itself, one layer down: %r"
              % (_rf["steps"][0].get("failing"),),
              "failing" in M.STEP_KEYS and "failingBasis" in M.STEP_KEYS
              and _rf["steps"][0]["failing"][0]
              == "totals > applies the bulk discount"
              # ...and the sentence travels with them, because a list a reader
              # cannot tell from a tail of arbitrary output is not evidence.
              and "jest" in _rf["steps"][0]["failingBasis"])

        check("ef2 ...REDACTED on the way in, by the trail's own redactor and "
              "not a second rule. This row is committed, and a stack frame "
              "naming a home directory is the CWE-532 leak the journal was "
              "repaired for arriving through a new door: %r"
              % (_rf["steps"][0]["failing"][1],),
              _journal_io.OUTSIDE_TOKEN in _rf["steps"][0]["failing"][1]
              and _journal_io.canonical(_rf).count(_leak_user) == 0
              and _journal_io.canonical(_rf).count("/Users/") == 0
              # The caller's own copy is untouched: the terminal prints the
              # operator's real path, and only the committed file may not.
              and _fail_step["failing"][1].count(_leak_user) == 1)

        _over = dict(RESULT)
        _over["steps"] = [dict(RESULT["steps"][0], failing=[
            "case %d" % (n,) for n in range(M.MAX_FAILING + 5)],
            failingBasis="a caller that did not cut its own list")]
        _ro = M.row_for(plain, _over, "task", {"taskId": "P1.2"}, IDENT,
                        published=["pytest -q"])
        check("ef3 ...and CUT BY THE WRITER, never trusted from the caller. A "
              "row is hash-chained, so a field with unbounded content is a row "
              "with unbounded size - and this file's rule is that an inventive "
              "caller cannot widen a row, which a bound living only in "
              "`run-test-gate` would leave as a habit: %r"
              % (len(_ro["steps"][0]["failing"]),),
              len(_ro["steps"][0]["failing"]) == M.MAX_FAILING
              and _ro["steps"][0]["failing"][-1]
              == "case %d" % (M.MAX_FAILING - 1,))

        # ef4-ef6: THE SECOND DOOR RUNNER OUTPUT COMES THROUGH, and it stood
        # open. The coverage basis ends in a sample of the paths the RUN printed
        # - a jest or pytest run naming absolute paths puts the operator's home
        # directory in it - and the row stored that sentence verbatim while the
        # path LIST beside it had been redacted since it existed. The sentence
        # went unnoticed because it is a sentence.
        _cb_abs = "/Users/%s/work/shop/node_modules/x.js" % (_leak_user,)
        _with_cb = dict(RESULT)
        _with_cb["coverageBasis"] = (
            "the runner named 2 path(s); the work under test declares 1 "
            "file(s); among them: %s, src/a.py" % (_cb_abs,))
        _rc = M.row_for(plain, _with_cb, "task", {"taskId": "P1.2"}, IDENT,
                        published=["pytest -q"])
        check("ef4 the coverage basis is redacted on the way in, by the same "
              "redactor the failing lines use: the home directory occurs "
              "nowhere in the row, and the sentence still says what it said: %r"
              % (_rc["observations"]["coverageBasis"],),
              _journal_io.canonical(_rc).count(_leak_user) == 0
              and _journal_io.canonical(_rc).count("/Users/") == 0
              and _journal_io.OUTSIDE_TOKEN
              in _rc["observations"]["coverageBasis"])
        # THE OTHER DIRECTION, and it is what a redactor is usually broken BY: a
        # rule that tokenised everything would make the sample useless and the
        # counts unreadable, after which the field is noise and the next reader
        # deletes it.
        check("ef5 ...and what the basis is FOR survives it - the counts, the "
              "sentence, and the repo-relative path in the same sample, which "
              "is the half a redactor that tokenised every path would lose",
              "the runner named 2 path(s)"
              in _rc["observations"]["coverageBasis"]
              and "src/a.py" in _rc["observations"]["coverageBasis"])
        # ...and NOT to a journal value's budget. Every other basis on this row
        # is stored whole, so borrowing the bounded wrapper would have cut this
        # one for a reason belonging to a different field.
        _long = dict(RESULT)
        _long["coverageBasis"] = ("among them: " + ", ".join(
            "src/mod%d/file.py" % (n,) for n in range(40)))
        _rl = M.row_for(plain, _long, "task", {"taskId": "P1.2"}, IDENT,
                        published=["pytest -q"])
        check("ef6 ...and it is not clipped to a journal VALUE's budget: the "
              "basis sentences on this row carry no such bound, and a cut "
              "borrowed from another field would end the sample mid-path: %r"
              % (len(_rl["observations"]["coverageBasis"]),),
              _rl["observations"]["coverageBasis"] == _long["coverageBasis"]
              and len(_rl["observations"]["coverageBasis"])
              > _journal_io.MAX_VALUE_CHARS)
        check("ef7 a run that measured no coverage keeps its None rather than "
              "gaining an empty sentence - a basis with no claim under it is "
              "the shape this file refuses everywhere else",
              M.row_for(plain, dict(RESULT, coverageBasis=None), "task",
                        {"taskId": "P1.2"}, IDENT,
                        published=["pytest -q"]
                        )["observations"]["coverageBasis"] is None)

        # A RUN NOTHING ELSE ON THE ROW COULD EXPLAIN. `failed` is read back off
        # the steps, `timed-out` off a step's `outcome` and its `timeoutSeconds`,
        # `no-checks` off `ranTotal` -- but a run a stop signal cut short keeps
        # only the steps that FINISHED, so without this field the row would say
        # `cancelled` with nothing beside it saying why. That word had no writer
        # at all until the interrupt path was built.
        stopped = dict(RESULT)
        stopped["status"] = "cancelled"
        stopped["cancelledBy"] = "SIGINT"
        stopped["treeMutated"] = None
        rc = M.row_for(plain, stopped, "phase", {"phaseId": "P1"}, IDENT,
                       published=["pytest -q"])
        check("ev31 a cancelled run carries the signal that stopped it, beside "
              "the one status word that has no other basis on the row: %r"
              % ((rc.get("status"), rc.get("cancelledBy")),),
              rc.get("status") == "cancelled"
              and rc.get("cancelledBy") == "SIGINT")

        check("ev32 SECOND DIRECTION: a run nothing stopped leaves the key OFF "
              "entirely. `run_gate` carries the field on EVERY result and sets "
              "it None, so a writer that copied it unconditionally would stamp "
              "`cancelledBy: null` on every ordinary row - and a key present "
              "everywhere cannot be told from one a build does not write: %r"
              % (sorted(k for k in row if k.startswith("cancel")),),
              "cancelledBy" not in row and "cancelledBy" not in ru)

        # F312. WHERE THE `steps` LIST CAME FROM. `steps` names the entries that
        # ran and nothing beside them says which declaration held those entries,
        # so once a task can be measured by a gate of its own OR by the phase's,
        # two rows with different `steps` differ for two reasons a reader cannot
        # separate. The fixture is the one that separates them: `scope` is `task`
        # (the pointer went on the task) while the entries came from the PHASE, so
        # a writer that reused `scope` for provenance answers `task` here and is
        # wrong, and a writer that dropped the field answers nothing.
        fell_back = dict(RESULT)
        fell_back["gateSource"] = "phase"
        rp = M.row_for(plain, fell_back, "task",
                       {"taskId": "P1.2", "phaseId": "P1"}, IDENT,
                       published=["pytest -q"])
        check("ev35 the row says WHICH declaration its steps came from, and it "
              "is not `scope` re-spelled: `scope` is the pointer subject - "
              "`latest_by_subject` keys by it and `_set_pointer` branches on it "
              "- so a row can carry one word for the subject and another for "
              "the gate, and this is that row: %r"
              % ((rp.get("scope"), rp.get("gateSource")),),
              rp.get("gateSource") == "phase" and rp.get("scope") == "task")

        check("ev36 SECOND DIRECTION: a result that says nothing about its gate "
              "leaves the key OFF. A writer that stamped a default would put "
              "`task` on every row recorded before the field existed, which is "
              "a provenance claim nobody made: %r"
              % (sorted(k for k in row if k.startswith("gate")),),
              "gateSource" not in row and "gateSource" not in ru)

        # F280. THE WORD THE RUNNER COULD NOT SAY, AND THE CACHE THAT REPEATED
        # IT. `run_status` took no tree argument, so a gate that passed every
        # command and rewrote the file it was grading came through here as
        # `passed` and `pointer_for` cached that onto `task.testEvidence` -- the
        # exit code refused the commit and the record signed the work off. What
        # this pair checks is that the row is a CONDUIT (the verdict is the
        # runner's, never re-derived here) and that the word arrives with the
        # basis that makes it checkable, which is why it needed no field of its
        # own.
        mutating = dict(RESULT)
        mutating["status"] = "gate-mutated"
        mutating["failed"] = []
        mutating["treeMutated"] = [" M src/a.py"]
        mutating["treeBasis"] = ("git described the tree before and after; "
                                 "%d of %d changed path(s) are declared by the "
                                 "work under test" % (1, 1))
        rgm = M.row_for(plain, mutating, "task", {"taskId": "P1.2"}, IDENT,
                        published=["pytest -q"])
        check("ev33 a run that passed its commands and rewrote its own subject "
              "reaches the row as `gate-mutated`, carrying the paths and the "
              "attribution sentence that let it be read back. No "
              "`treeMutatedOwned` key is invented for it: the word is already "
              "derivable from what the row holds, and a cached classification "
              "beside the thing that produces it is this file's own argument "
              "against a cached count: %r"
              % ((rgm.get("status"), rgm["observations"]["treeMutated"]),),
              rgm.get("status") == "gate-mutated"
              # The porcelain prefix is stripped by `_paths` on the way in, the
              # same as for every other row - so the assertion is on the PATH
              # this row publishes, not on the line the bracket read.
              and rgm["observations"]["treeMutated"] == ["src/a.py"]
              and "declared by the work under test" in (
                  rgm["observations"]["treeBasis"])
              and "treeMutatedOwned" not in rgm
              and "treeMutatedOwned" not in rgm["observations"])
        check("ev34 ...and `pointer_for` caches THAT word, unchanged. It is the "
              "half of the fault that reached the manifest - the plan block is "
              "what `--fail-on failing-tests` reads, and it can only be as "
              "honest as the word handed to it: %r"
              % (M.pointer_for(rgm),),
              M.pointer_for(rgm)["status"] == "gate-mutated"
              # SECOND DIRECTION: the pointer does not TRANSLATE, it copies. A
              # writer that mapped an unfamiliar verdict onto a familiar one
              # would pass the clause above by luck for this word and lose every
              # future member of an enum the schema leaves open.
              and M.pointer_for(row)["status"] == "failed"
              and sorted(M.pointer_for(rgm)) == ["at", "runId", "status"])

        # THE OTHER DIRECTION OF ev11, and the contract the gate runner leans on:
        # `run-test-gate.attempt_of` hands this an explicit None for a task whose
        # plan records no `attempts`, so if a None identity value were carried
        # instead of dropped, every such row would read `attempt: null` and both
        # renderers would print a field the plan never wrote. A recorded 0 is the
        # value that separates the rules - it must survive, and it is asserted in
        # the same case so a writer that dropped every falsy value cannot pass.
        quiet = dict(IDENT)
        quiet["attempt"] = None
        rq = M.row_for(plain, RESULT, "task", {"taskId": "P1.2"}, quiet,
                       published=["pytest -q"])
        zeroed = dict(IDENT)
        zeroed["attempt"] = 0
        rz = M.row_for(plain, RESULT, "task", {"taskId": "P1.2"}, zeroed,
                       published=["pytest -q"])
        check("ev29 an identity attempt of None leaves the field OFF the row, "
              "while a recorded 0 is written as 0. Absent means 'the plan does "
              "not say how many times this ran' and 0 means it says none - two "
              "answers a null would flatten into one: %r"
              % (("attempt" in rq, rz.get("attempt")),),
              "attempt" not in rq and "attempt" in rz and rz["attempt"] == 0)

        # --- appending, and reading back ----------------------------------
        edir = M.evidence_dir(plain)
        path = M.append_row(plain, row)
        check("ev17 the file is named for the row's OWN month and writer, not "
              "for the wall clock - so a row stamped in a past month lands "
              "where a reader of that month looks: %r"
              % (os.path.basename(path),),
              os.path.dirname(path) == edir
              and os.path.basename(path).endswith(".jsonl")
              and os.path.basename(path).startswith(row["ts"][:7]))

        other = dict(row)
        other["runId"] = "R2"
        p2 = M.append_row(plain, other, session_id="sess-2")
        check("ev18 a second WRITER gets a second file - the journal's argument "
              "and not a decoration: two sessions in two worktrees append at "
              "once, and one shared file would conflict on every merge: %r"
              % ((os.path.basename(path), os.path.basename(p2)),),
              p2 != path and os.path.dirname(p2) == edir)

        back = M.read_rows(plain)
        check("ev19 both rows read back, and the reader says how many files it "
              "walked - 'no rows' and 'no files' are different answers and a "
              "reader that returned a bare list could not tell them apart: %r"
              % ((len(back["rows"]), back["files"], back["unreadable"]),),
              len(back["rows"]) == 2 and back["files"] == 2
              and back["unreadable"] == 0
              and sorted(r["runId"] for r in back["rows"]) == ["R1", "R2"])

        with open(path, "a", encoding="utf-8") as fh:
            fh.write("{not json at all\n")
        torn = M.read_rows(plain)
        check("ev20 a torn line is skipped AND COUNTED. The usage ledger drops "
              "one in silence, which is right for telemetry and wrong here: "
              "silence about a lost EVIDENCE row is the failure this file "
              "exists to prevent: %r"
              % ((len(torn["rows"]), torn["unreadable"]),),
              len(torn["rows"]) == 2 and torn["unreadable"] == 1)

        empty = M.read_rows(os.path.join(tmp, "nothing-here"))
        check("ev21 a directory that is not there reads as no files and no "
              "rows, without raising - a reader is asked this on a repo that "
              "has never recorded anything, and an exception there would take "
              "down whatever surface asked: %r" % (empty,),
              empty["rows"] == [] and empty["files"] == 0
              and empty["unreadable"] == 0)

        # --- the chain ------------------------------------------------------
        # THE DEFECT THIS BLOCK EXISTS FOR, driven before it was written: two runs
        # were recorded, a plain string replace turned the recorded `failed` into
        # `passed`, and every verdict in the tree stayed green. The row that
        # records a MEASUREMENT was the one committed file with no chain.
        #
        # Every case here is PAIRED with the one that fails when the check is
        # weakened rather than broken, because a chain is exactly the kind of code
        # a green suite proves nothing about: a `verify` that returned "no
        # findings" unconditionally passes any case that only tampers.
        def _chain_project(name, config=None):
            """A fresh project with its own ledger. FRESH, never reused: a chain
            is per file, and a case that inherited another case's rows would be
            grading a history it did not write."""
            return _project(os.path.join(tmp, name),
                            {} if config is None else config)

        def _ledger(proj):
            return M.ledger_files(proj)[0]

        def _lines(path):
            return io.open(path, encoding="utf-8").read().splitlines()

        def _rewrite(path, lines):
            io.open(path, "w", encoding="utf-8").write(
                "".join(ln + "\n" for ln in lines))

        def _run(run_id, status, ts):
            return {"v": 1, "runId": run_id, "ts": ts, "scope": "task",
                    "taskId": "P1.1", "phaseId": "P1", "status": status,
                    "steps": [], "failed": []}

        c1 = _chain_project("chain-clean")
        cp = M.append_row(c1, _run("run-1", "failed", "2026-06-01T10:00:00Z"))
        M.append_row(c1, _run("run-2", "passed", "2026-06-02T10:00:00Z"))
        c_rows = [json.loads(ln) for ln in _lines(cp)]
        check("ec1 an appended run carries both chain keys, and the FIRST row's "
              "`prev` is derived from the file's own basename rather than from a "
              "constant - a shared seed would let a whole file be dropped over "
              "another writer's file and verify perfectly: %r"
              % ((c_rows[0].get("prev"), bool(c_rows[0].get("hash"))),),
              c_rows[0]["prev"] == _journal_io.genesis_prev(os.path.basename(cp))
              and isinstance(c_rows[0].get("hash"), str) and c_rows[0]["hash"])

        check("ec2 ...and the second row's `prev` IS the first row's `hash`, "
              "computed by the journal's own `row_hash` rather than by a second "
              "spelling of it. Asserted against `row_hash` and not a literal: a "
              "literal keeps agreeing after the two chains diverge",
              c_rows[1]["prev"] == c_rows[0]["hash"]
              and c_rows[0]["hash"] == _journal_io.row_hash(c_rows[0])
              and c_rows[1]["hash"] == _journal_io.row_hash(c_rows[1]))

        clean = M.verify(c1)
        check("ec3 a ledger nobody touched verifies GREEN, counted, with no "
              "findings and no warnings - the half that fails when the chain is "
              "made to over-fire, and without it every tamper case below is "
              "satisfied by a `verify` that always reports a break: %r"
              % ((clean["ok"], clean["rows"], len(clean["findings"]),
                  len(clean["warnings"])),),
              clean["ok"] is True and clean["rows"] == 2
              and clean["findings"] == [] and clean["warnings"] == []
              and clean["exists"] is True and clean["unchained"] == 0)

        # THE DRIVEN TAMPER, spelled the way it was driven: a plain string
        # replace of the recorded verdict, nothing else touched.
        _rewrite(cp, [ln.replace('"status":"failed"', '"status":"passed"')
                      for ln in _lines(cp)])
        tampered = M.verify(c1)
        check("ec4 a plain string replace turning a recorded `failed` into "
              "`passed` is a FINDING and takes `ok` with it. This is the defect: "
              "before the chain, the same rewrite left every verdict in the tree "
              "green, and the record of the MEASUREMENT was the one committed "
              "file a reader could edit: %r"
              % ((tampered["ok"], tampered["findings"]),),
              tampered["ok"] is False and len(tampered["findings"]) == 1
              and "does not hash to its own contents" in tampered["findings"][0]
              and "run-1" in tampered["findings"][0])

        c2 = _chain_project("chain-deleted")
        dp = M.append_row(c2, _run("run-1", "failed", "2026-06-01T10:00:00Z"))
        M.append_row(c2, _run("run-2", "passed", "2026-06-02T10:00:00Z"))
        M.append_row(c2, _run("run-3", "passed", "2026-06-03T10:00:00Z"))
        d_lines = _lines(dp)
        _rewrite(dp, [d_lines[0], d_lines[2]])
        deleted = M.verify(c2)
        check("ec5 a run DELETED from the middle is a finding on the row that "
              "followed it - the PAIR to ec4 and not a repetition of it: every "
              "surviving row still hashes to its own contents, so a check that "
              "only re-hashed rows would call this file clean: %r"
              % (deleted["findings"],),
              deleted["ok"] is False and len(deleted["findings"]) == 1
              and "does not follow the row before it" in deleted["findings"][0]
              and "run-3" in deleted["findings"][0])

        c3 = _chain_project("chain-renamed")
        rp = M.append_row(c3, _run("run-1", "passed", "2026-06-01T10:00:00Z"))
        moved_to = os.path.join(os.path.dirname(rp), "2026-05.otherwriter.jsonl")
        shutil.move(rp, moved_to)
        renamed = M.verify(c3)
        check("ec6 the SAME BYTES under a different file name stop verifying - "
              "this is what the basename seed buys, and it is the attack ec1 "
              "only half proves: one writer's whole month copied over another's "
              "would otherwise verify perfectly, every `prev` still matching its "
              "predecessor: %r" % (renamed["findings"],),
              renamed["ok"] is False and len(renamed["findings"]) == 1
              and "does not follow the row before it" in renamed["findings"][0])

        # --- rows written before the chain existed --------------------------
        # THE DECISION, exercised in both directions. An old row is a counted
        # warning; an old row AFTER a chained one is a finding. Neither half is
        # safe alone: warn at everything and the first run of this check is red in
        # every project that upgrades, and nobody reads it again; treat every
        # unchained row as legacy and the chain is opt-out, because deleting two
        # keys puts a row back outside it.
        c4 = _chain_project("chain-legacy")
        lp = M.append_row(c4, _run("run-1", "failed", "2026-06-01T10:00:00Z"))
        legacy_rows = [_run("old-1", "failed", "2026-06-01T08:00:00Z"),
                       _run("old-2", "passed", "2026-06-01T09:00:00Z")]
        _rewrite(lp, [_journal_io.canonical(r) for r in legacy_rows])
        old_only = M.verify(c4)
        check("ec7 a ledger written before the chain existed is a COUNTED "
              "WARNING and never a finding, and `ok` stays true. Grading those "
              "rows as tampering would turn the first run of this check red in "
              "every project that upgrades, and a check whose opening verdict is "
              "a wall of findings nobody intends to act on is one its reader "
              "learns to skip: %r"
              % ((old_only["ok"], old_only["unchained"], old_only["warnings"]),),
              old_only["ok"] is True and old_only["findings"] == []
              and old_only["unchained"] == 2
              and len(old_only["warnings"]) == 1
              and "carry no chain" in old_only["warnings"][0])

        M.append_row(c4, _run("run-2", "passed", "2026-06-02T10:00:00Z"))
        healed = M.verify(c4)
        after_legacy = [json.loads(ln) for ln in _lines(lp)][-1]
        check("ec8 ...and the next recorded run LINKS ONTO them, so the gap "
              "closes itself rather than staying open forever: the new row's "
              "`prev` is the hash of the unchained row it follows, which is what "
              "`link_after` is for: %r"
              % ((after_legacy["prev"] == _journal_io.row_hash(legacy_rows[-1]),
                  healed["unchained"]),),
              after_legacy["prev"] == _journal_io.row_hash(legacy_rows[-1])
              and healed["ok"] is True and healed["unchained"] == 2)

        edited_legacy = _lines(lp)
        edited_legacy[1] = edited_legacy[1].replace('"status":"passed"',
                                                    '"status":"failed"')
        _rewrite(lp, edited_legacy)
        healed_broken = M.verify(c4)
        check("ec9 ...and editing one of those old rows AFTERWARDS is now a "
              "finding, reported on the chained row that followed it. The pair "
              "with ec7 is the whole decision: the old rows are unprotected only "
              "until the next run is recorded, and this is the case that fails "
              "if `link_after` is weakened to 'the previous row's stored hash': "
              "%r" % (healed_broken["findings"],),
              healed_broken["ok"] is False
              and len(healed_broken["findings"]) == 1
              and "run-2" in healed_broken["findings"][0])

        c5 = _chain_project("chain-stripped")
        sp = M.append_row(c5, _run("run-1", "failed", "2026-06-01T10:00:00Z"))
        M.append_row(c5, _run("run-2", "passed", "2026-06-02T10:00:00Z"))
        stripped = []
        for ln in _lines(sp):
            obj = json.loads(ln)
            if obj["runId"] == "run-2":
                obj.pop("hash")
                obj.pop("prev")
            stripped.append(_journal_io.canonical(obj))
        _rewrite(sp, stripped)
        evaded = M.verify(c5)
        check("ec10 a row with its links STRIPPED so it would read as an old row "
              "is a FINDING, because the rows before it chain. Without this the "
              "chain is opt-out - delete two keys and ec4's tamper is legal "
              "again - and the finding names the innocent reading (an older copy "
              "of the plugin appended it) rather than asserting forgery: %r"
              % (evaded["findings"],),
              evaded["ok"] is False and len(evaded["findings"]) == 1
              and "carries no chain while the rows before it do"
              in evaded["findings"][0]
              and "older copy of the plugin" in evaded["findings"][0])

        # --- what is NOT a break --------------------------------------------
        c6 = _chain_project("chain-torn")
        tp = M.append_row(c6, _run("run-1", "passed", "2026-06-01T10:00:00Z"))
        with io.open(tp, "a", encoding="utf-8") as fh:
            fh.write('{"runId":"run-2","st')
        torn = M.verify(c6)
        check("ec11 a TORN TAIL is a warning and not a finding - it is what a "
              "crash mid-append leaves, the rows before it are intact, and "
              "nothing was hidden by it. A record that graded a crash as forgery "
              "would teach its reader that a finding means nothing: %r"
              % ((torn["ok"], torn["warnings"]),),
              torn["ok"] is True and torn["findings"] == []
              and len(torn["warnings"]) == 1
              and "partial line" in torn["warnings"][0])

        # THE CORRUPTED ROW IS OVERWRITTEN, NOT INSERTED BESIDE, and the
        # difference is the whole case: a garbage line ADDED between two intact
        # rows leaves the second one's `prev` still naming the first, so the
        # suspension below would be doing nothing and a mutation removing it
        # would survive. Overwriting row two destroys the hash row three points
        # at, which is the only shape where "nothing can say what this should
        # have followed" is true.
        c7 = _chain_project("chain-corrupt")
        xp = M.append_row(c7, _run("run-1", "passed", "2026-06-01T10:00:00Z"))
        M.append_row(c7, _run("run-2", "passed", "2026-06-02T10:00:00Z"))
        M.append_row(c7, _run("run-3", "passed", "2026-06-03T10:00:00Z"))
        x_lines = _lines(xp)
        _rewrite(xp, [x_lines[0], "{corrupted half a row", x_lines[2]])
        corrupt = M.verify(c7)
        check("ec12 a corrupted line in the MIDDLE is a finding, and the row "
              "after it is NOT also accused of a break it cannot be judged for: "
              "the row it should have followed is the one that was destroyed, so "
              "the link check is suspended for one row while that row's own hash "
              "is still read. One finding, not two - a record that reported a "
              "second break it could not substantiate would be teaching its "
              "reader to discount findings: %r" % (corrupt["findings"],),
              corrupt["ok"] is False and len(corrupt["findings"]) == 1
              and "not valid JSON" in corrupt["findings"][0])

        c9 = _chain_project("chain-unreadable")
        up = M.append_row(c9, _run("run-1", "passed", "2026-06-01T10:00:00Z"))
        with open(up, "wb") as fh:
            fh.write(b'{"runId":"run-1","status":"\xff\xfe not utf-8"}\n')
        unreadable = M.verify(c9)
        check("ec17 a ledger file that cannot be READ is a finding, not a file "
              "walked in silence. The shared reader answers an unreadable file "
              "with no rows, which is right for a consumer racing a `git mv` and "
              "exactly wrong here: 'no rows, no findings' is what a clean file "
              "prints too, and an unreadable record is the state a forger would "
              "settle for: %r" % (unreadable["findings"],),
              unreadable["ok"] is False and len(unreadable["findings"]) == 1
              and "could not be read" in unreadable["findings"][0]
              and unreadable["files"][0]["rows"] == 0)

        gone = M.verify(os.path.join(tmp, "chain-nothing-here"))
        check("ec13 a project that has never recorded anything is `exists` "
              "false, ok, and silent - this is asked on every repo a surface "
              "opens, and a finding here would accuse every project that has not "
              "run a gate yet: %r"
              % ((gone["exists"], gone["ok"], gone["rows"]),),
              gone["exists"] is False and gone["ok"] is True
              and gone["rows"] == 0 and gone["findings"] == []
              and gone["warnings"] == [])

        # THE LEDGER HAS THE TRAIL'S DELETION HOLE BECAUSE IT HAS THE TRAIL'S
        # SHAPE. Every pass above walks `ledger_files`, which lists what is on
        # disk - so a whole file that was removed is in no list, the chain over
        # what remains verifies clean, and `rows: 0` reads exactly like a project
        # that never ran a gate. A real repository is the only place that can be
        # told apart, because the evidence is what git still TRACKS.
        if not shutil.which("git"):
            print("SKIP ec18 (git is not on PATH)")
            print("SKIP ec19 (git is not on PATH)")
        else:
            rmp = os.path.join(tmp, "removed-ledger")
            os.makedirs(os.path.join(rmp, "docs", "audit"))
            subprocess.run(["git", "init", "-q", rmp], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _k, _v in (("user.email", "p@example.com"), ("user.name", "P")):
                subprocess.run(["git", "-C", rmp, "config", _k, _v], check=True)
            rpath = M.append_row(rmp, _run("run-1", "passed",
                                           "2026-06-01T10:00:00Z"))
            subprocess.run(["git", "-C", rmp, "add", "-A"], check=True,
                           stdout=subprocess.DEVNULL)
            subprocess.run(["git", "-C", rmp, "-c", "commit.gpgsign=false",
                            "commit", "-q", "-m", "e"], check=True,
                           stdout=subprocess.DEVNULL)
            _clean_after_commit = M.verify(rmp)
            os.remove(rpath)
            _removed = M.verify(rmp)
            check("ec18 a COMMITTED ledger file deleted from the working tree is "
                  "a FINDING naming it - before this it left `ok` true with no "
                  "findings and no files, which is what a project that has never "
                  "recorded a run also prints. The record of the measurement is "
                  "the one a green gate points at: %r" % (_removed["findings"],),
                  _removed["ok"] is False and len(_removed["findings"]) == 1
                  and os.path.basename(rpath) in _removed["findings"][0]
                  and "NOT in the working tree" in _removed["findings"][0])
            subprocess.run(["git", "-C", rmp, "checkout", "--", "."], check=True,
                           stdout=subprocess.DEVNULL)
            _back = M.verify(rmp)
            check("ec19 SECOND DIRECTION, BOTH WAYS: committing the ledger is "
                  "not itself a finding, and putting the deleted file back takes "
                  "the finding away - a check bound to anything other than what "
                  "git says the worktree is missing would fire on one of these: "
                  "%r / %r"
                  % (_clean_after_commit["findings"], _back["findings"]),
                  _clean_after_commit["ok"] is True
                  and _clean_after_commit["findings"] == []
                  and _back["ok"] is True and _back["findings"] == []
                  and _back["rows"] == 1)

        # --- the two spellings of one chain ---------------------------------
        one_pass = M.chain_file([_run("run-1", "failed", "2026-06-01T10:00:00Z"),
                                 _run("run-2", "passed", "2026-06-02T10:00:00Z")],
                                os.path.basename(cp))
        check("ec14 `chain_file` produces exactly what appending row by row "
              "produced - compared against the rows `append_row` actually wrote "
              "into that same file rather than against a literal, because the "
              "whole point of the function is that the demo generator and the "
              "recorder cannot spell the seed differently: %r"
              % ([r["hash"][:8] for r in one_pass],),
              [r["prev"] for r in one_pass] == [r["prev"] for r in c_rows]
              and [r["hash"] for r in one_pass] == [r["hash"] for r in c_rows])

        brought = M.chain_onto({"runId": "x", "prev": "SOME-OTHER-CHAIN",
                                "hash": "NOT-A-HASH"}, [], "f.jsonl")
        check("ec15 both chain keys are ASSIGNED, never defaulted. A `prev` the "
              "caller brought is the link that row had in some other file, and "
              "keeping it would splice a row into this chain carrying a "
              "predecessor that is not the row before it - the shape a "
              "`setdefault` would produce, and one that verifies nowhere: %r"
              % (brought,),
              brought["prev"] == _journal_io.genesis_prev("f.jsonl")
              and brought["hash"] == _journal_io.row_hash(
                  {"runId": "x", "prev": brought["prev"]})
              and brought["hash"] != "NOT-A-HASH")

        c8 = _chain_project("chain-locked")
        kp = M.append_row(c8, _run("run-1", "passed", "2026-06-01T10:00:00Z"))
        io.open(kp + ".lock", "w", encoding="utf-8").write("")
        # THROUGH `attempt`, because the failing direction of this case is an
        # append that DOES NOT raise - and a bare try/finally that then tidied the
        # lock file the mutated code had already removed would escape, taking the
        # whole suite with it and reporting this case by nobody's name.
        _ok, _why = _harness.attempt(
            M.append_row, c8, _run("run-2", "passed", "2026-06-01T10:00:00Z"))
        locked = _ok is False and "evidence ledger" in str(_why)
        if os.path.exists(kp + ".lock"):
            os.unlink(kp + ".lock")
        check("ec16 an append whose lock is already held RAISES rather than "
              "writing - `prev` is read off the file's tail, so two writers that "
              "both read it would write the same link and produce a break "
              "indistinguishable from a deleted run. A false tamper verdict is "
              "worse than a missing row, and `record` already declines to report "
              "a run whose evidence was not stored: %r" % (locked,),
              locked is True
              and len(_lines(kp)) == 1)

        # --- the anchor ---------------------------------------------------
        recorded = M.record(plain, RESULT, "task",
                            {"taskId": "P1.2", "phaseId": "P1"}, IDENT,
                            published=["pytest -q"])
        jrows = _journal_io.read_all(plain)
        anchors = [r for r in jrows if r.get("action") == M.ACTION_RECORDED]
        check("ev22 recording anchors the run in the EXISTING hash chain with "
              "one row - the claim is inside a chain that cannot be edited "
              "without breaking it, and no second chain had to be built to get "
              "that: %r" % (len(anchors),),
              recorded["appended"] is not False and len(anchors) == 1
              and anchors[0]["details"].get("runId") == "R1")

        check("ev23 ...and `runId` SURVIVES `normalise_details`. It has to be "
              "on the allow-list or it is dropped in silence - the failure that "
              "already bit `reason`, where the field was written, discarded, "
              "and believed by everything reading the document instead of the "
              "row: %r" % (sorted(anchors[0]["details"]),),
              "runId" in _journal_io.DETAILS_KEYS
              and anchors[0]["details"]["runId"] == "R1")
        # THE ORDER, pinned by its consequence. Writing the anchor first would
        # put a claim into a hash chain about a row that does not exist - and the
        # only way to observe the order from outside is to make the ledger write
        # FAIL and check that nothing was claimed. `record` deliberately does not
        # swallow that: a run whose evidence could not be stored must not be
        # reported as recorded.
        before_anchor = len([r for r in _journal_io.read_all(plain)
                             if r.get("action") == M.ACTION_RECORDED])
        real_append = M.append_row

        def _refuse(*_a, **_k):
            raise IOError("the evidence file could not be written")

        raised = False
        try:
            M.append_row = _refuse
            M.record(plain, RESULT, "task", {"taskId": "P1.3"},
                     {"runId": "R9", "via": "cli"}, published=["pytest -q"])
        except IOError:
            raised = True
        finally:
            M.append_row = real_append
        after_anchor = [r for r in _journal_io.read_all(plain)
                        if r.get("action") == M.ACTION_RECORDED]
        check("ev28 when the ledger row cannot be written, NO anchor is left "
              "behind and the failure is loud. The reverse order would leave "
              "the chain asserting a run nothing can produce - and a fail-soft "
              "here would report a run as recorded when its evidence is gone: "
              "raised=%r anchors %r -> %r"
              % (raised, before_anchor, len(after_anchor)),
              raised is True and len(after_anchor) == before_anchor
              and not any(r["details"].get("runId") == "R9"
                          for r in after_anchor))

        # --- the pointer: a cache, and one that may be refused -------------
        # The ledger is the source of truth and this block is a CACHE, so the
        # write that updates it is the one that is allowed to fail. Every state
        # below is a designed outcome with a sentence, not an error path.
        import json as _json

        def _manifest_project(name, git=False):
            """A fresh sharded project. FRESH, never copied from another case: a
            copied one inherits that case's journal rows, and a case counting
            rows then reads somebody else's history as its own."""
            root = os.path.join(tmp, name)
            os.makedirs(os.path.join(root, "docs", "audit", "phases"))
            os.makedirs(os.path.join(root, ".claude"))
            with open(os.path.join(root, ".claude", "audit.config.json"), "w") as fh:
                _json.dump({"manifestPath": "docs/audit/audit-plan.json"}, fh)
            with open(os.path.join(root, "docs", "audit", "audit-plan.json"),
                      "w") as fh:
                _json.dump({"meta": {"version": 3}, "phases": [
                    {"id": "P1", "title": "one", "shard": "phases/P1.json"}]}, fh)
            with open(os.path.join(root, "docs", "audit", "phases", "P1.json"),
                      "w") as fh:
                _json.dump({"id": "P1", "title": "one", "status": "in_progress",
                            "testGate": [], "tasks": [
                                {"id": "P1.1", "title": "t",
                                 "status": "in_progress"}]}, fh)
            if git:
                subprocess.run(["git", "init", "-q", root], check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return root, os.path.join(root, "docs", "audit", "audit-plan.json")

        proj, mpath = _manifest_project("ptr")
        spath = os.path.join(proj, "docs", "audit", "phases", "P1.json")
        index_before = io.open(mpath, encoding="utf-8").read()

        prow = {"runId": "R7", "status": "failed", "ts": "2026-08-26T10:00:00Z"}
        res = M.write_pointer(proj, mpath, "task", {"taskId": "P1.1",
                                                    "phaseId": "P1"}, prow)
        shard = _json.loads(io.open(spath, encoding="utf-8").read())
        check("ed1 the pointer lands on the task, in the SHARD, and carries "
              "exactly the three keys the manifest caches - identity, verdict, "
              "time, and nothing countable: %r"
              % (shard["tasks"][0].get("testEvidence"),),
              res["written"] is True
              and shard["tasks"][0]["testEvidence"] == {
                  "runId": "R7", "status": "failed", "at": "2026-08-26T10:00:00Z"})

        check("ed2 ...and the INDEX is byte-identical afterwards. A phase run "
              "that touched the index is what makes two parallel phases conflict "
              "on merge, which is the property the sharded layout exists to buy",
              io.open(mpath, encoding="utf-8").read() == index_before)

        res_ph = M.write_pointer(proj, mpath, "phase", {"phaseId": "P1"}, prow)
        shard = _json.loads(io.open(spath, encoding="utf-8").read())
        check("ed3 a phase-scoped run points at the PHASE, beside the task "
              "pointer rather than instead of it - the sign-off gate and a "
              "task's own gate are different measurements and a reader has to "
              "be able to see both: %r"
              % ((shard.get("testEvidence"), shard["tasks"][0].get("testEvidence")),),
              res_ph["written"] is True
              and shard["testEvidence"]["runId"] == "R7"
              and shard["tasks"][0]["testEvidence"]["runId"] == "R7")

        missing = M.write_pointer(proj, mpath, "task",
                                  {"taskId": "P9.9", "phaseId": "P1"}, prow)
        check("ed4 a pointer at a task that is not there is REFUSED with a "
              "reason, never written somewhere else - 'no such task' and 'the "
              "pointer moved' must not print the same way: %r"
              % (missing.get("reason"),),
              missing["written"] is False and "P9.9" in (missing.get("reason") or ""))

        # --- the lock states ----------------------------------------------
        state, _detail = M.pointer_lock_state(proj, "P1", session_id="me")
        check("ed5 with no lock scheme at all the write proceeds under the "
              "weaker guarantee and SAYS which - the panel's documented "
              "fallback, and the same reason: refusing every non-git project "
              "would refuse a case that has an answer: %r" % (state,),
              state == "unlockable")

        gitproj = os.path.join(tmp, "gitptr")
        os.makedirs(gitproj)
        subprocess.run(["git", "init", "-q", gitproj], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        free, _d = M.pointer_lock_state(gitproj, "P1", session_id="me")
        check("ed6 an unheld lock reads FREE - the state a normal standalone run "
              "meets, and the one that must not be confused with the two below",
              free == "free")

        _locks.acquire(gitproj, "phase-P1", session="me", out=lambda *_a: None)
        mine, _d = M.pointer_lock_state(gitproj, "P1", session_id="me")
        check("ed7 THE RE-ENTRANCY CASE: a lock held by OUR OWN session reads "
              "`ours`, not `held`. `_locks.acquire` is not re-entrant, so a run "
              "inside its own phase would otherwise be refused by the lock it "
              "already holds - which is every in-phase recording there is: %r"
              % (mine,),
              mine == "ours")

        theirs, detail = M.pointer_lock_state(gitproj, "P1", session_id="someone-else")
        check("ed8 ...and the SAME lock read by a different session is `held`, "
              "with a sentence naming the repair. The pair is the point: either "
              "half alone passes with the identity check deleted: %r"
              % ((theirs, detail),),
              theirs == "held" and "reconcile" in (detail or ""))

        blocked = M.write_pointer(gitproj, mpath, "task",
                                  {"taskId": "P1.1", "phaseId": "P1"}, prow,
                                  session_id="someone-else")
        check("ed9 THE DESIGNED PARTIAL STATE: a pointer refused by another live "
              "session leaves the LEDGER ROW standing and says so. That is the "
              "only reachable partial write, and it is the harmless one - a run "
              "that happened with nothing yet pointing at it, which `--reconcile` "
              "repairs. The reverse would be a claim with no basis: %r"
              % (blocked.get("reason"),),
              blocked["written"] is False
              and "reconcile" in (blocked.get("reason") or ""))
        _locks.release(gitproj, "phase-P1", session="me", out=lambda *_a: None)

        # --- C4: two events, and the second only if the move happened ------
        jproj, jpath = _manifest_project("c4")
        moved = M.write_pointer(jproj, jpath,
                                "task", {"taskId": "P1.1", "phaseId": "P1"},
                                {"runId": "R8", "status": "passed",
                                 "ts": "2026-08-26T11:00:00Z"})
        jr = [r for r in _journal_io.read_all(jproj)
              if r.get("action") == "task.testEvidence"]
        check("ed10 a pointer that LANDED writes the plan-movement row, and it "
              "names both ends - a row saying only where a field arrived cannot "
              "be read as a transition, and this field moves repeatedly over one "
              "task's life: %r" % (jr[0]["details"] if jr else None,),
              moved["written"] is True and len(jr) == 1
              and jr[0]["details"]["to"] == "R8"
              and jr[0]["details"]["field"] == "testEvidence")

        held_proj, held_path = _manifest_project("c4held", git=True)
        _locks.acquire(held_proj, "phase-P1", session="other", out=lambda *_a: None)
        refused = M.write_pointer(held_proj, held_path,
                                  "task", {"taskId": "P1.1", "phaseId": "P1"},
                                  {"runId": "R9", "status": "failed",
                                   "ts": "2026-08-26T12:00:00Z"},
                                  session_id="me")
        jr2 = [r for r in _journal_io.read_all(held_proj)
               if r.get("action") == "task.testEvidence"]
        check("ed11 THE C4 RULE: a pointer that was REFUSED writes NO "
              "plan-movement row. The chain must never assert a transition "
              "before it exists - and a refused cache write is a designed state "
              "here, so this is the ordinary path and not an error one: "
              "written=%r rows=%r" % (refused["written"], len(jr2)),
              refused["written"] is False and jr2 == [])
        _locks.release(held_proj, "phase-P1", session="other", out=lambda *_a: None)

        # A DECLINED RELEASE IS THE ONLY NEWS OF A TAKEOVER THE LOSER GETS, and
        # it used to go into a printer that discards beside a code nothing read.
        # The lock is made to decline rather than raced into declining: the
        # property under test is that the code is READ and the sentence reaches
        # the caller, and a real race would test the scheduler instead.
        dr_proj, dr_path = _manifest_project("c4declined", git=True)
        _dr_real = _locks.release
        _locks.release = lambda *_a, **_k: _locks.E_LIVE
        try:
            declined = M.write_pointer(dr_proj, dr_path, "task",
                                       {"taskId": "P1.1", "phaseId": "P1"},
                                       {"runId": "RD", "status": "passed",
                                        "ts": "2026-08-26T13:00:00Z"},
                                       session_id="me")
        finally:
            _locks.release = _dr_real
            _locks.release(dr_proj, "phase-P1", session="me",
                           out=lambda *_a: None)
        check("ed11b a lock that REFUSED to be given back is carried to the "
              "caller, and the write is still `written` - the pointer landed, "
              "and what the sentence adds is that another session was writing "
              "beside it. Silenced into a no-op printer, that was the one "
              "notice a displaced run ever got: %r"
              % (declined.get("releaseRefused"),),
              declined["written"] is True
              and "NOT released" in (declined.get("releaseRefused") or "")
              and "took it over" in (declined.get("releaseRefused") or ""))

        # --- reconcile: the repair the refusal names ------------------------
        rproj, rpath = _manifest_project("recon")
        for rid, ts, status in (("RA", "2026-08-26T09:00:00Z", "failed"),
                                ("RB", "2026-08-26T10:00:00Z", "passed")):
            M.append_row(rproj, {"v": 1, "runId": rid, "ts": ts, "scope": "task",
                                 "taskId": "P1.1", "phaseId": "P1",
                                 "status": status, "steps": []})
        M.append_row(rproj, {"v": 1, "runId": "RP", "ts": "2026-08-26T11:00:00Z",
                             "scope": "phase", "phaseId": "P1",
                             "status": "no-checks", "steps": []})
        rep = M.reconcile(rproj, rpath)
        body = _json.loads(io.open(os.path.join(rproj, "docs", "audit",
                                                "phases", "P1.json"),
                                   encoding="utf-8").read())
        check("ed12 reconcile points every subject at its NEWEST run, task and "
              "phase apart - and newest is by `ts`, never by position: rows land "
              "in one file per writer per month, so two worktrees concatenate in "
              "no meaningful order and reading position would make 'the latest' "
              "depend on a directory listing: %r"
              % ((body["tasks"][0].get("testEvidence", {}).get("runId"),
                  body.get("testEvidence", {}).get("runId")),),
              body["tasks"][0]["testEvidence"]["runId"] == "RB"
              and body["testEvidence"]["runId"] == "RP"
              and sorted(rep["moved"]) == ["phase P1 -> RP", "task P1.1 -> RB"])

        again = M.reconcile(rproj, rpath)
        check("ed13 ...and running it again moves NOTHING and says so. A repair "
              "that rewrote an already-correct pointer would put a fresh journal "
              "row on every invocation, which is a trail of transitions that "
              "never happened: %r" % ((again["moved"], again["already"]),),
              again["moved"] == []
              and sorted(again["already"]) == ["phase P1", "task P1.1"])

        orphan = _manifest_project("orphan")[0]
        M.append_row(orphan, {"v": 1, "runId": "RX", "ts": "2026-08-26T09:00:00Z",
                              "scope": "task", "status": "passed", "steps": []})
        best = M.latest_by_subject(M.read_rows(orphan)["rows"])
        check("ed14 a row that names no subject is SKIPPED, never guessed at - "
              "it cannot be pointed at anything, and inventing one would put a "
              "pointer on a task that never ran: %r" % (list(best),),
              best == {})

        held2, held2_path = _manifest_project("recon-held", git=True)
        M.append_row(held2, {"v": 1, "runId": "RH", "ts": "2026-08-26T09:00:00Z",
                             "scope": "task", "taskId": "P1.1", "phaseId": "P1",
                             "status": "failed", "steps": []})
        _locks.acquire(held2, "phase-P1", session="other", out=lambda *_a: None)
        blocked_rep = M.reconcile(held2, held2_path, session_id="me")
        _locks.release(held2, "phase-P1", session="other", out=lambda *_a: None)
        check("ed15 a reconcile that could not finish REPORTS the subjects it "
              "left behind rather than returning a smaller number - a count of "
              "what moved, read alone, would say the plan is caught up: %r"
              % (blocked_rep["refused"],),
              blocked_rep["moved"] == [] and len(blocked_rep["refused"]) == 1
              and "P1.1" in blocked_rep["refused"][0]
              and blocked_rep["subjects"] == 1)


        # --- the boundary: when could a run have been recorded at all -------
        # THE GATE'S QUESTION IS NOT "IS THIS EVIDENCED" BUT "COULD IT HAVE
        # BEEN". Excused work is BEFORE the boundary, so an EARLIER boundary is
        # the safer answer and every case below is built around that asymmetry:
        # the failure direction that matters is a boundary that drifts LATER and
        # widens the excuse in silence.
        check("eb1 with neither source present the boundary is None and the "
              "sentence says nothing was ever recorded - never the epoch, and "
              "never a value a truthiness test could flatten into 'no boundary': "
              "%r" % (M.boundary_of(None, None),),
              M.boundary_of(None, None)["at"] is None
              and M.boundary_of(None, None)["sources"] == {"key": None,
                                                           "ledger": None}
              and "no run is readable" in M.boundary_of(None, None)["basis"])

        _key_only = M.boundary_of({"at": "2026-06-02T15:38:00Z"}, None)
        _led_only = M.boundary_of(None, "2026-06-02T15:38:00Z")
        check("eb2 either source ALONE answers, and each says which one did. "
              "The pair is the point: delete the key and the ledger still dates "
              "the boundary, archive the ledger and the key still does - only "
              "destroying both widens the excuse: %r / %r"
              % (_key_only["sources"], _led_only["sources"]),
              _key_only["at"] == "2026-06-02T15:38:00Z"
              and _led_only["at"] == "2026-06-02T15:38:00Z"
              and _key_only["sources"] == {"key": "2026-06-02T15:38:00Z",
                                           "ledger": None}
              and _led_only["sources"] == {"key": None,
                                           "ledger": "2026-06-02T15:38:00Z"})

        # THE VALUES SEPARATE `min` FROM EVERY OTHER RULE, which is what a
        # fixture has to do here: with the two stamps a year apart, `max`, "the
        # key wins" and "the ledger wins" each produce a DIFFERENT answer from
        # `min`, so no wrong implementation can satisfy both halves.
        _key_first = M.boundary_of({"at": "2025-01-04T08:00:00Z"},
                                   "2026-06-02T15:38:00Z")
        _led_first = M.boundary_of({"at": "2026-06-02T15:38:00Z"},
                                   "2025-01-04T08:00:00Z")
        check("eb3 with BOTH sources the EARLIER one wins, whichever it is - "
              "asserted from both sides, because 'the key wins' and 'the ledger "
              "wins' each pass one half, and `max` passes neither. Excused work "
              "is before the boundary, so the earlier value is the safer one and "
              "a later one would widen the excuse without saying so: %r / %r"
              % (_key_first["at"], _led_first["at"]),
              _key_first["at"] == "2025-01-04T08:00:00Z"
              and _led_first["at"] == "2025-01-04T08:00:00Z")

        _blank_key = M.boundary_of({"at": "   "}, "2026-06-02T15:38:00Z")
        _no_key = M.boundary_of(None, "2026-06-02T15:38:00Z")
        check("eb4 a key that is THERE but states no usable moment is not the "
              "same state as no key at all, and the two sentences differ - the "
              "repairs differ too (fix the key, versus write one), and a reader "
              "handed only the moment could not tell them apart: %r"
              % (_blank_key["basis"],),
              _blank_key["at"] == "2026-06-02T15:38:00Z"
              and _blank_key["sources"]["key"] is None
              and "states no usable moment" in _blank_key["basis"]
              and _blank_key["basis"] != _no_key["basis"])

        _rows = [{"ts": "2026-06-02T15:38:00Z", "runId": "RA"},
                 {"ts": "2026-08-26T09:00:00Z", "runId": "RB"},
                 {"runId": "RC"}, {"ts": 17, "runId": "RD"}, "not a row"]
        check("eb5 the ledger's contribution is its EARLIEST row, not its "
              "newest - the boundary is when recording BEGAN - and a row with no "
              "usable `ts` contributes nothing rather than an empty string that "
              "would sort ahead of every real stamp: %r"
              % (M.earliest_recorded(_rows),),
              M.earliest_recorded(_rows) == "2026-06-02T15:38:00Z"
              and M.earliest_recorded([]) is None
              and M.earliest_recorded([{"runId": "RC"}]) is None)

        # --- what could not be ASKED is not what is absent ------------------
        _guessed = M.boundary_of(None, "2026-06-02T15:38:00Z",
                                 unknown=["the plan could not be read"])
        check("eb6 a source that could not be ASKED is NAMED, never folded into "
              "'absent'. An unreadable plan may hold an EARLIER moment, so "
              "treating it as missing moves the boundary later - the one "
              "direction that widens an excuse in silence: %r"
              % (_guessed["unknown"],),
              _guessed["unknown"] == ["the plan could not be read"]
              and M.boundary_of(None, None)["unknown"] == [])

        empty_proj = _project(os.path.join(tmp, "no-boundary"), {})
        _nothing = M.evidence_boundary(empty_proj,
                                       os.path.join(empty_proj, "nope.json"))
        check("eb7 the door answers on a project with no plan and no ledger "
              "rather than raising - it is asked on every gate verdict, and it "
              "names the plan it could not read instead of reporting a boundary "
              "it did not derive: at=%r unknown=%r"
              % (_nothing["at"], _nothing["unknown"]),
              _nothing["at"] is None and len(_nothing["unknown"]) == 1
              and "could not be read" in _nothing["unknown"][0])

        # --- stamping it, once ----------------------------------------------
        sproj, spath = _manifest_project("since")
        for rid, ts in (("RB", "2026-08-26T11:00:00Z"),
                        ("RA", "2026-06-02T15:38:00Z")):
            M.append_row(sproj, {"v": 1, "runId": rid, "ts": ts, "scope": "task",
                                 "taskId": "P1.1", "phaseId": "P1",
                                 "status": "passed", "steps": []})
        s_shard = os.path.join(sproj, "docs", "audit", "phases", "P1.json")
        s_shard_before = io.open(s_shard, encoding="utf-8").read()
        stamped = M.write_evidence_since(sproj, spath, "P1", session_id="me")
        s_meta = _json.loads(io.open(spath, encoding="utf-8").read())["meta"]
        check("eb8 the first stamp dates the boundary from the EARLIEST row in "
              "the ledger and names THAT run - the rows are appended "
              "newest-first here so a writer reading the last row, or the wall "
              "clock, produces a different answer from this one: %r"
              % (s_meta.get(M.SINCE_KEY),),
              stamped["written"] is True
              and s_meta[M.SINCE_KEY]["at"] == "2026-06-02T15:38:00Z"
              and s_meta[M.SINCE_KEY]["runId"] == "RA"
              and s_meta[M.SINCE_KEY]["basis"] == M.SINCE_BASIS)

        check("eb9 ...and it lands on the INDEX, where `meta` lives, leaving the "
              "phase shard byte-identical. The pointer beside it is the opposite "
              "rule and for the opposite reason: this is written ONCE in a "
              "plan's life, so it cannot be what puts two parallel phases in "
              "each other's way",
              io.open(s_shard, encoding="utf-8").read() == s_shard_before
              and stamped["at"] == "2026-06-02T15:38:00Z")

        s_rows = [r for r in _journal_io.read_all(sproj)
                  if r.get("action") == M.ACTION_SINCE]
        check("eb10 the stamp is anchored in the hash chain by a row of its "
              "own, naming both ends of the transition - `from` null is the "
              "claim that the plan carried no boundary before, which is the "
              "only thing that makes this row readable as a transition: %r"
              % (s_rows[0]["details"] if s_rows else None,),
              len(s_rows) == 1 and s_rows[0]["details"]["field"] == M.SINCE_KEY
              and s_rows[0]["details"]["from"] is None
              and s_rows[0]["details"]["to"] == "2026-06-02T15:38:00Z"
              and s_rows[0]["details"]["runId"] == "RA")

        # THE OVER-FIRE ARM, and it reads vacuous by design: a writer that
        # stamped on EVERY run would pass every case above and fail only this
        # one. The boundary is derived once and then written down; one that were
        # re-derived would move LATER as the ledger's earliest row aged out of a
        # reader's reach, which is the silent widening this whole feature exists
        # to prevent.
        M.append_row(sproj, {"v": 1, "runId": "RC", "ts": "2026-09-01T09:00:00Z",
                             "scope": "task", "taskId": "P1.1", "phaseId": "P1",
                             "status": "passed", "steps": []})
        again_since = M.write_evidence_since(sproj, spath, "P1", session_id="me")
        s_meta2 = _json.loads(io.open(spath, encoding="utf-8").read())["meta"]
        s_rows2 = [r for r in _journal_io.read_all(sproj)
                   if r.get("action") == M.ACTION_SINCE]
        check("eb11 a plan that already states a boundary is LEFT ALONE, says "
              "so, and draws no second journal row - a stamp taken on every run "
              "would put a trail of transitions that never happened beside a "
              "value that moves: %r" % (again_since.get("reason"),),
              again_since["written"] is False
              and again_since["at"] == "2026-06-02T15:38:00Z"
              and s_meta2[M.SINCE_KEY]["at"] == "2026-06-02T15:38:00Z"
              and s_meta2[M.SINCE_KEY]["runId"] == "RA"
              and len(s_rows2) == 1)

        bare_proj, bare_path = _manifest_project("since-empty")
        bare_since = M.write_evidence_since(bare_proj, bare_path, "P1")
        bare_meta = _json.loads(io.open(bare_path, encoding="utf-8").read())["meta"]
        check("eb12 a plan with NO recorded run is not stamped at all, and the "
              "missing basis is what gets said. A wall-clock stamp here would "
              "date the boundary from the moment somebody happened to run the "
              "gate and excuse every task finished before that - a claim with "
              "nothing behind it: %r" % (bare_since.get("reason"),),
              bare_since["written"] is False and bare_since["at"] is None
              and M.SINCE_KEY not in bare_meta
              and "no recorded run" in bare_since["reason"]
              and not [r for r in _journal_io.read_all(bare_proj)
                       if r.get("action") == M.ACTION_SINCE])

        anon_proj, anon_path = _manifest_project("since-anon")
        M.append_row(anon_proj, {"v": 1, "runId": "", "ts": "2026-06-02T15:38:00Z",
                                 "scope": "task", "taskId": "P1.1",
                                 "phaseId": "P1", "status": "passed", "steps": []})
        M.write_evidence_since(anon_proj, anon_path, "P1")
        anon_meta = _json.loads(io.open(anon_path, encoding="utf-8").read())["meta"]
        check("eb13 a row naming no run still DATES the boundary, and the "
              "provenance key is left OFF rather than written empty - `runId` is "
              "looked up in the ledger, so an empty one would be a pointer at "
              "nothing while `at` is a fact in its own right: %r"
              % (anon_meta.get(M.SINCE_KEY),),
              (anon_meta.get(M.SINCE_KEY) or {}).get("at") == "2026-06-02T15:38:00Z"
              and "runId" not in (anon_meta.get(M.SINCE_KEY) or {"runId": 1})
              and (anon_meta.get(M.SINCE_KEY) or {}).get("basis") == M.SINCE_BASIS)

        gone = M.write_evidence_since(sproj, os.path.join(sproj, "gone.json"), "P1")
        check("eb14 a plan that cannot be read is refused with the reason, and "
              "nothing is written anywhere - the read comes before the first "
              "mutation, so there is no half-applied state to recover from: %r"
              % (gone.get("reason"),),
              gone["written"] is False and gone["at"] is None
              and "cannot read" in gone["reason"])

        # --- the locks, and what a refusal costs here -----------------------
        lockproj, lockpath = _manifest_project("since-locked", git=True)
        M.append_row(lockproj, {"v": 1, "runId": "RL", "ts": "2026-06-02T15:38:00Z",
                                "scope": "task", "taskId": "P1.1",
                                "phaseId": "P1", "status": "passed", "steps": []})
        _locks.acquire(lockproj, "index", session="other", out=lambda *_a: None)
        idx_held = M.write_evidence_since(lockproj, lockpath, "P1",
                                          session_id="me")
        _locks.release(lockproj, "index", session="other", out=lambda *_a: None)
        check("eb15 the INDEX lock is what guards this write, because `meta` is "
              "the index's - a stamp taken while another live session holds it "
              "is refused, and the sentence does NOT send the human to "
              "`--reconcile`: that repair re-derives POINTERS and cannot write "
              "this key, while nothing here needs a repair at all because the "
              "ledger still dates the boundary: %r" % (idx_held.get("reason"),),
              idx_held["written"] is False
              and "index lock is held" in idx_held["reason"]
              and "reconcile" not in idx_held["reason"]
              and M.SINCE_KEY not in _json.loads(
                  io.open(lockpath, encoding="utf-8").read())["meta"])

        _locks.acquire(lockproj, "phase-P1", session="other", out=lambda *_a: None)
        ph_held = M.write_evidence_since(lockproj, lockpath, "P1", session_id="me")
        _locks.release(lockproj, "phase-P1", session="other", out=lambda *_a: None)
        check("eb16 ...and the PHASE lock refuses it too, which is not "
              "belt-and-braces: in the SINGLE-FILE layout the index and the "
              "phase body are the same bytes, and `write_pointer` rewrites that "
              "whole file under this very lock - so a stamp ignoring it would be "
              "the second writer of one file. A refusal costs nothing here; a "
              "lost update costs somebody's pointer: %r" % (ph_held.get("reason"),),
              ph_held["written"] is False
              and "phase lock is held" in ph_held["reason"]
              and M.SINCE_KEY not in _json.loads(
                  io.open(lockpath, encoding="utf-8").read())["meta"])

        # THE SECOND DIRECTION, and it is the case that fails when the lock
        # check is tightened until it refuses everything: a lock held by OUR OWN
        # session is the ordinary state of an in-phase recording, and refusing
        # it would refuse every gate run inside a phase.
        _locks.acquire(lockproj, "phase-P1", session="me", out=lambda *_a: None)
        ours = M.write_evidence_since(lockproj, lockpath, "P1", session_id="me")
        _locks.release(lockproj, "phase-P1", session="me", out=lambda *_a: None)
        check("eb17 a lock held by THIS session does not refuse the stamp - "
              "`_locks.acquire` is not re-entrant and an in-phase run already "
              "holds its phase lock, so the holder is compared rather than the "
              "lock re-taken: %r" % ((ours["written"], ours["at"]),),
              ours["written"] is True
              and ours["at"] == "2026-06-02T15:38:00Z")

        _locks.acquire(lockproj, "index", session="other", out=lambda *_a: None)
        _locks.acquire(lockproj, "phase-P1", session="other", out=lambda *_a: None)
        _istate, _idetail = M.lock_state(lockproj, "index", "index",
                                         session_id="me", hint="HINT-SENTINEL")
        _pstate, _pdetail = M.pointer_lock_state(lockproj, "P1", session_id="me")
        _locks.release(lockproj, "index", session="other", out=lambda *_a: None)
        _locks.release(lockproj, "phase-P1", session="other", out=lambda *_a: None)
        check("eb18 `lock_state` names the lock it was ASKED about and carries "
              "the CALLER's repair, while `pointer_lock_state` still produces "
              "the phase's own sentence through it. Two writers with two "
              "repairs: a shared hint would send half of them to a command that "
              "cannot help them, and a shared label would name the wrong lock: "
              "%r / %r" % (_idetail, _pdetail),
              _istate == "held" and _pstate == "held"
              and "the index lock is held" in _idetail
              and _idetail.endswith("HINT-SENTINEL")
              and "the phase lock is held" in _pdetail
              and _pdetail.endswith(M.RECONCILE_HINT))

        # `write_pointer`'s rule, one writer over, and with the half that writer
        # cannot show: this block takes more than one lock and can leave by a
        # refusal, so the sentence has to survive a path that returns before the
        # stamp. The lock is made to decline rather than raced into declining -
        # the property is that the code is read, not that a race can be won.
        db_proj, db_path = _manifest_project("since-declined", git=True)
        M.append_row(db_proj, {"v": 1, "runId": "RD", "ts": "2026-06-02T15:38:00Z",
                               "scope": "task", "taskId": "P1.1",
                               "phaseId": "P1", "status": "passed", "steps": []})
        _db_real = _locks.release
        _locks.release = lambda *_a, **_k: _locks.E_LIVE
        try:
            db_ok = M.write_evidence_since(db_proj, db_path, "P1",
                                           session_id="me")
        finally:
            _locks.release = _db_real
            for _n in ("index", "phase-P1"):
                _locks.release(db_proj, _n, session="me", out=lambda *_a: None)
        check("eb18b a lock that REFUSED to be given back reaches the caller, "
              "and the stamp is still `written`: the boundary landed, and what "
              "the sentence adds is that another session was writing beside it. "
              "A sentence that went into a printer which discards is how a "
              "displaced run finished, cleaned up and reported success: %r"
              % (db_ok.get("releaseRefused"),),
              db_ok["written"] is True
              and any("NOT released" in s
                      for s in (db_ok.get("releaseRefused") or [])))

        dh_proj, dh_path = _manifest_project("since-declined-refused", git=True)
        M.append_row(dh_proj, {"v": 1, "runId": "RE", "ts": "2026-06-02T15:38:00Z",
                               "scope": "task", "taskId": "P1.1",
                               "phaseId": "P1", "status": "passed", "steps": []})
        _locks.acquire(dh_proj, "phase-P1", session="other", out=lambda *_a: None)
        _dh_real = _locks.release
        _locks.release = lambda *_a, **_k: _locks.E_LIVE
        try:
            db_no = M.write_evidence_since(dh_proj, dh_path, "P1",
                                           session_id="me")
        finally:
            _locks.release = _dh_real
            _locks.release(dh_proj, "index", session="me", out=lambda *_a: None)
            _locks.release(dh_proj, "phase-P1", session="other",
                           out=lambda *_a: None)
        check("eb18c ...and on the REFUSING path too, which is the one this "
              "block can leave by. A run displaced while it held the index was "
              "displaced whether or not its own stamp went in, and those "
              "returns used to go past the release with nothing left to attach "
              "the sentence to: %r" % ((db_no["written"],
                                        db_no.get("releaseRefused")),),
              db_no["written"] is False
              and any("NOT released" in s
                      for s in (db_no.get("releaseRefused") or [])))


        # THE OVER-FIRE ARM WHERE THE VALUE ITSELF SEPARATES THE TWO WRITERS.
        # eb11's ledger could only produce the stamp the plan already carried, so
        # a writer that re-derived every run left the block looking untouched and
        # was caught by the journal alone. Here the plan states a boundary EARLIER
        # than anything in the ledger - a hand-written one, or one whose first
        # runs have since been archived - and re-deriving would replace it with a
        # LATER moment. Later is WIDER, because excused work is BEFORE the
        # boundary: that write would silently excuse every task finished in
        # between, which is the whole failure this feature is built around.
        hand_proj, hand_path = _manifest_project("since-handwritten")
        M.append_row(hand_proj, {"v": 1, "runId": "RN", "scope": "task",
                                 "ts": "2026-06-02T15:38:00Z", "taskId": "P1.1",
                                 "phaseId": "P1", "status": "passed", "steps": []})
        hand_body = _json.loads(io.open(hand_path, encoding="utf-8").read())
        hand_block = {"at": "2025-01-04T08:00:00Z", "runId": "HAND",
                      "basis": "stated by the team when the plan was adopted"}
        hand_body["meta"][M.SINCE_KEY] = dict(hand_block)
        io.open(hand_path, "w", encoding="utf-8").write(_json.dumps(hand_body))
        hand_out = M.write_evidence_since(hand_proj, hand_path, "P1")
        hand_after = _json.loads(io.open(hand_path,
                                         encoding="utf-8").read())["meta"]
        check("eb19 a boundary the plan ALREADY states is never re-derived, not "
              "even when the ledger would produce a different one - and the "
              "difference here is the direction that matters: re-deriving would "
              "move it from %s to the ledger's %s, and a LATER boundary excuses "
              "everything finished in between. `min` is what makes the two "
              "sources safe; re-deriving is what would make them dangerous: %r"
              % (hand_block["at"], "2026-06-02T15:38:00Z",
                 hand_after.get(M.SINCE_KEY)),
              hand_out["written"] is False
              and hand_out["at"] == "2025-01-04T08:00:00Z"
              and hand_after[M.SINCE_KEY] == hand_block
              and not [r for r in _journal_io.read_all(hand_proj)
                       if r.get("action") == M.ACTION_SINCE])


        # THE SINGLE-FILE LAYOUT, where the two writes land in ONE file. `meta`
        # is the index's and the pointer is the phase body's, which are separate
        # files only when the plan is sharded; in the v2 layout the boundary
        # write is a read-modify-write of the very document the pointer has just
        # been written into. A stamp that wrote back anything other than the whole
        # document it had just read would take the pointer out with it, and every
        # sharded case above would stay green while it did.
        flat = _project(os.path.join(tmp, "since-flat"),
                        {"manifestPath": "docs/audit/audit-plan.json"})
        os.makedirs(os.path.join(flat, "docs", "audit"), exist_ok=True)
        flat_path = os.path.join(flat, "docs", "audit", "audit-plan.json")
        io.open(flat_path, "w", encoding="utf-8").write(_json.dumps(
            {"meta": {"version": 2},
             "phases": [{"id": "P1", "title": "one", "status": "in_progress",
                         "testGate": [], "tasks": [{"id": "P1.1", "title": "t",
                                                    "status": "done"}]}]}))
        M.append_row(flat, {"v": 1, "runId": "RF", "ts": "2026-06-02T15:38:00Z",
                            "scope": "task", "taskId": "P1.1", "phaseId": "P1",
                            "status": "passed", "steps": []})
        M.write_pointer(flat, flat_path, "task", {"taskId": "P1.1",
                                                  "phaseId": "P1"},
                        {"runId": "RF", "status": "passed",
                         "ts": "2026-06-02T15:38:00Z"})
        M.write_evidence_since(flat, flat_path, "P1")
        flat_body = _json.loads(io.open(flat_path, encoding="utf-8").read())
        # READ DEFENSIVELY, because the bug this case exists for DELETES the keys
        # the assertion would otherwise index: a subscript would raise here and be
        # reported as "the body raised" rather than as this case failing by name,
        # which is a case that cannot say what it caught.
        flat_phase = (flat_body.get("phases") or [{}])[0]
        flat_task = (flat_phase.get("tasks") or [{}])[0]
        check("eb20 in the SINGLE-FILE layout both writes land in one document "
              "and BOTH survive - the boundary is written after the pointer, "
              "into the same file, so a stamp that wrote back less than the whole "
              "document it read would silently delete the pointer beside it. "
              "Every sharded case above passes with that bug in place, because "
              "there the two live in different files: %r"
              % (((flat_body.get("meta") or {}).get(M.SINCE_KEY),
                  flat_task.get("testEvidence"), flat_phase.get("title")),),
              (flat_body.get("meta") or {}).get(M.SINCE_KEY, {}).get("at")
              == "2026-06-02T15:38:00Z"
              and (flat_task.get("testEvidence") or {}).get("runId") == "RF"
              and flat_phase.get("title") == "one")

        # --- who ran it, when, and who else was running --------------------
        # THE QUESTION THE LEDGER COULD NOT ASK. `ts` is stamped when a row is
        # BUILT and `durationMs` is a monotonic elapsed reading, so until a start
        # was recorded the ledger could say how long a run took and never when it
        # was happening - and an overlap question needs a window, not a duration.
        check("wr1 an ABSENT `runner` means the gate, which is a fact about the "
              "corpus rather than a default covering a gap: every row written "
              "before the key existed was the wrapper's, because the wrapper was "
              "the only writer there was",
              M.runner_of({"runId": "x"}) == M.RUNNER_GATE
              and M.runner_of({}) == M.RUNNER_GATE
              and M.runner_of(None) == M.RUNNER_GATE)
        check("wr2 ...and a word outside the vocabulary comes back UNCHANGED "
              "rather than folded into either answer - a reader asking 'was "
              "this the gate's own run' gets False, which is the safe reading, "
              "and the surface can still say what it found",
              M.runner_of({M.RUNNER_KEY: "jenkins"}) == "jenkins"
              and M.runner_of({M.RUNNER_KEY: M.RUNNER_OUTSIDE})
              == M.RUNNER_OUTSIDE)
        check("wr3 ...and the two words this plugin knows are distinct, so the "
              "vocabulary cannot collapse into one answer",
              M.RUNNER_GATE != M.RUNNER_OUTSIDE
              and set(M.RUNNER_WORDS) == {M.RUNNER_GATE, M.RUNNER_OUTSIDE})

        _rec = {"runId": "R1", "ts": "2026-09-01T10:10:00Z",
                M.STARTED_KEY: "2026-09-01T10:00:00Z"}
        start, end, basis = M.window_of(_rec)
        check("wr4 a RECORDED start gives the window, and the basis says it was "
              "recorded: %r" % (basis,),
              end - start == 600 and "recorded" in basis)
        _old = {"runId": "R2", "ts": "2026-09-01T10:10:00Z", "durationMs": 600000}
        start, end, basis = M.window_of(_old)
        check("wr5 ...and a row PREDATING the key still has a window, derived "
              "from `ts` less `durationMs` and LABELLED as derived - a "
              "derivation presented as a record is how a cheap read comes to be "
              "trusted like a measurement: %r" % (basis,),
              end - start == 600 and "derived" in basis)
        for blind, why in (({"runId": "R3"}, "no `ts`"),
                           ({"runId": "R4", "ts": "not-a-time"}, "unreadable `ts`"),
                           ({"runId": "R5", "ts": "2026-09-01T10:10:00Z"},
                            "neither a start nor a duration"),
                           ({"runId": "R6", "ts": "2026-09-01T10:10:00Z",
                             "durationMs": True}, "a bool is not a duration")):
            start, _e, basis = M.window_of(blind)
            check("wr6 a row with %s places itself in no window, and says so - "
                  "a THIRD answer rather than a failure, because an overlap "
                  "computed against a window nobody knows is the shape in which "
                  "a guess gets recorded as a finding" % (why,),
                  start is None and bool(basis), repr(basis))

        _mine = {"runId": "MINE", "ts": "2026-09-01T10:10:00Z",
                 M.STARTED_KEY: "2026-09-01T10:00:00Z"}
        _same = {"runId": "MINE", "ts": "2026-09-01T10:10:00Z",
                 M.STARTED_KEY: "2026-09-01T10:00:00Z"}
        found, _basis = M.overlapping_runs([_same], _mine, M.RUNNER_GATE)
        check("wr7 a run ALONE on the machine does not find ITSELF in the "
              "window it just occupied - the rows a caller passes were read back "
              "off disk, so identity cannot do it and the `runId` test is the "
              "whole difference between this and a rule that refuses every run "
              "there is: %r" % (found,),
              found == [])
        _other = {"runId": "OTHER", "ts": "2026-09-01T10:05:00Z",
                  M.STARTED_KEY: "2026-09-01T10:02:00Z"}
        found, _basis = M.overlapping_runs([_same, _other], _mine, M.RUNNER_GATE)
        check("wr8 ...and a DIFFERENT gate run inside the window is found, which "
              "is the case wr7 would pass without: %r"
              % ([r.get("runId") for r in found],),
              [r.get("runId") for r in found] == ["OTHER"])
        _outside = dict(_other, runId="OUT")
        _outside[M.RUNNER_KEY] = M.RUNNER_OUTSIDE
        gate_side, _b = M.shared_the_machine([_outside], _mine)
        out_side, _b = M.contested_by([_outside], _mine)
        check("wr9 the runner is an ARGUMENT because the two questions have "
              "different remedies: an outside run in the window means re-run "
              "once it has finished, another gate run means two executors were "
              "invited onto one machine and that answer belongs to whoever "
              "invited them. Folding them into one list would give one remedy "
              "for two causes: %r / %r"
              % (gate_side, [r.get("runId") for r in out_side]),
              gate_side == [] and [r.get("runId") for r in out_side] == ["OUT"])
        check("wr10 an inclusive endpoint counts: two runs that met for one "
              "second met",
              M._overlaps((10, 20), (20, 30)) and M._overlaps((20, 30), (10, 20))
              and not M._overlaps((10, 20), (21, 30)))

        verdict = M.attribution_of(_mine, [_outside])
        check("wr11 a red with an outside suite in its window is CONTESTED, and "
              "the basis NAMES the rival: the one thing missing when a push's "
              "suite overlapped a recorded gate and the plugin reported the red "
              "as its own was a named rival with its own row: %r" % (verdict,),
              verdict["attributed"] is False
              and verdict["contested"] == ["OUT"]
              and "OUT" in verdict["basis"])
        verdict = M.attribution_of(_mine, [_other])
        check("wr12 SECOND-DIRECTION CASE: with nothing from outside in the "
              "window the verdict IS this run's - another GATE run does not "
              "contest it, because that is the other question: %r" % (verdict,),
              verdict["attributed"] is True and verdict["contested"] == [])
        verdict = M.attribution_of({"runId": "NOWHEN"}, [_outside])
        check("wr13 ...and a row that places itself in no window answers None, "
              "which is neither of the above: 'nothing else was running' and "
              "'nobody could look' are different answers and must never render "
              "alike: %r" % (verdict,),
              verdict["attributed"] is None and verdict["contested"] == [])
        check("wr14 attribution moves NO verdict - `status` is what the commands "
              "answered and stays what they answered. This function returns an "
              "observation beside a verdict, and the row it was handed is "
              "untouched",
              "status" not in M.attribution_of(_mine, [_outside])
              and _mine.get("status") is None)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # --- gate_tally / command_tally / gate_names_seen: pure, no fixture root ---
    # These fold ROWS a caller already has (from read_rows) into a count; no
    # disk is read here, which is the point - a tally a caller can test without
    # a temp directory is a tally that stays testable everywhere it is used.
    lint_rows = [
        {"ts": "2026-01-01T00:00:00Z", "runId": "r1",
         "steps": [{"name": "lint", "command": "ruff check .", "exit": 0}]},
        {"ts": "2026-01-02T00:00:00Z", "runId": "r2",
         "steps": [{"name": "lint", "command": "ruff check .", "exit": 1}]},
        # A DIFFERENT gate, same run - proves gate_tally narrows by name and
        # does not fold every step in a row into the count it is asked for.
        {"ts": "2026-01-03T00:00:00Z", "runId": "r3",
         "steps": [{"name": "test", "command": "pytest", "exit": 0},
                   {"name": "lint", "command": "ruff check .", "exit": 0}]},
        # An `outcome` failure with a CLEAN exit code - the shape `_step_failed`
        # exists for, and the fixture the exit-only reading would get wrong.
        {"ts": "2026-01-04T00:00:00Z", "runId": "r4",
         "steps": [{"name": "lint", "command": "ruff check .", "exit": 0,
                    "outcome": "timed-out"}]},
    ]
    check("ev37 gate_tally counts every step named `lint` across the rows and "
          "tells an exit failure from a pass: %r" % (M.gate_tally(lint_rows, "lint"),),
          M.gate_tally(lint_rows, "lint") == (4, 2))
    check("ev38 ...and an `outcome` failure counts even where `exit` reads "
          "clean, which is the pair `_step_failed` was written to tell apart "
          "from an ordinary pass",
          M.gate_tally([lint_rows[3]], "lint") == (1, 1))
    check("ev39 gate_tally never counts a DIFFERENT name's step, so the `test` "
          "row above changes nothing about `lint`'s tally",
          M.gate_tally(lint_rows, "test") == (1, 0))
    check("ev40 command_tally matches the VERBATIM command instead of the "
          "short name - a candidate spelled differently from the recorded "
          "command matches nothing, which is the lookup's own discipline "
          "applied to history instead of to a manifest",
          M.command_tally(lint_rows, "ruff check .") == (4, 2)
          and M.command_tally(lint_rows, "ruff check --fix .") == (0, 0))
    check("ev41 gate_names_seen is every distinct name across the rows, "
          "sorted, and never a step with no name at all",
          M.gate_names_seen(lint_rows) == ["lint", "test"]
          and M.gate_names_seen([{"steps": [{"exit": 0}]}]) == [])
    check("ev42 MIN_HISTORY_RUNS is a floor a caller compares a tally against, "
          "not a judgement this module makes itself - gate_tally reports the "
          "raw count for a gate run fewer times than the floor exactly as it "
          "would for one run well past it",
          M.MIN_HISTORY_RUNS >= 2
          and M.gate_tally(lint_rows[:1], "lint") == (1, 0))

    # --- gate_last_caught / gate_cost_ms: paired with the tally, not a third one
    cost_rows = [
        {"ts": "2026-02-01T00:00:00Z", "runId": "c1",
         "steps": [{"name": "lint", "exit": 0, "durationMs": 1000}]},
        {"ts": "2026-02-02T00:00:00Z", "runId": "c2",
         "steps": [{"name": "lint", "exit": 1, "durationMs": 2000}]},
        {"ts": "2026-02-03T00:00:00Z", "runId": "c3",
         "steps": [{"name": "lint", "exit": 1, "durationMs": 1500}]},
        # A run that came LATER and passed - it must not win `gate_last_caught`,
        # which asks when the gate last CAUGHT something, not when it last ran.
        {"ts": "2026-02-04T00:00:00Z", "runId": "c4",
         "steps": [{"name": "lint", "exit": 0}]},
    ]
    check("ev43 gate_last_caught is the newest ts among the FAILED steps, "
          "never the newest run overall: %r"
          % (M.gate_last_caught(cost_rows, "lint"),),
          M.gate_last_caught(cost_rows, "lint") == "2026-02-03T00:00:00Z")
    check("ev44 ...and a gate with no failed step at all reports None, which "
          "is NOT the same claim as `ran` being zero - a gate that has run "
          "and never failed is a different fact from one nobody has run",
          M.gate_last_caught(cost_rows[:1], "lint") is None
          and M.gate_tally(cost_rows[:1], "lint") == (1, 0))
    check("ev45 gate_cost_ms sums every step's OWN durationMs, and the one "
          "step here that carries none does not zero the total: %r"
          % (M.gate_cost_ms(cost_rows, "lint"),),
          M.gate_cost_ms(cost_rows, "lint") == 1000 + 2000 + 1500)
    check("ev46 ...and a gate whose every recorded step is silent about "
          "duration reports None, never zero - unmeasured is not the same "
          "claim as a run that cost nothing",
          M.gate_cost_ms([{"steps": [{"name": "lint", "exit": 0}]}], "lint")
          is None)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__evidence_io.py --selftest\n")
    raise SystemExit(2)
