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
import time

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _evidence_io as M                           # noqa: E402
import _journal_io                                 # noqa: E402
import _locks                                      # noqa: E402
import _manifest_vocab                             # noqa: E402


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
        # --- resolved_commands: the one home for a gate entry's resolution -----
        rc_man = {"meta": {"buildCommands": {"lint": "ruff check .",
                                             "test": "pytest -q"},
                           "nodePreamble": "source ~/.nvm/nvm.sh && nvm use"}}
        check("rc0 every entry resolves through meta.buildCommands with "
              "meta.nodePreamble in front - the ONE resolution `full_status` "
              "and `run-test-gate.py` both have to share: %r"
              % (M.resolved_commands(rc_man, ["lint", "test"]),),
              M.resolved_commands(rc_man, ["lint", "test"]) == [
                  ("lint", "source ~/.nvm/nvm.sh && nvm use && ruff check ."),
                  ("test", "source ~/.nvm/nvm.sh && nvm use && pytest -q")])
        check("rc0b an entry naming no build command is carried VERBATIM, and a "
              "blank preamble is not one: %r"
              % (M.resolved_commands({"meta": {"nodePreamble": "  "}},
                                     ["echo literal"]),),
              M.resolved_commands({"meta": {"nodePreamble": "  "}},
                                  ["echo literal"])
              == [("echo literal", "echo literal")])
        check("rc0c the bare command half of THIS SAME function's answer is "
              "the one `full_status`'s `full_commands` argument reads - "
              "pinned here so the two never drift into two different shapes "
              "of the same word: %r"
              % ([c for _n, c in M.resolved_commands(rc_man, ["lint"])],),
              [c for _n, c in M.resolved_commands(rc_man, ["lint"])]
              == ["source ~/.nvm/nvm.sh && nvm use && ruff check ."])

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
              "was measured at`, which is the misreading that made the gap "
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

        # --- ef8-ef10: THE OTHER FIELD A RUNNER'S OWN OUTPUT WROTE -------------
        # `failingSuites`/`failingSuitesBasis` are `failing`'s own two rules
        # (STEP_KEYS, redaction, a bound the writer trusts from nobody) asked of
        # a PATH instead of a line of prose - a suite file is exactly the shape
        # `treeMutated` and `overlap` already answer that question for.
        _suite_leak = os.path.join(tmp, "elsewhere", "cart.test.ts")
        _fs_step = dict(RESULT["steps"][0])
        _fs_step["failingSuites"] = ["src/cart.test.ts", _suite_leak]
        _fs_step["failingSuitesBasis"] = ("the 2 suite file(s) jest named as "
                                          "failing, read from jest's FAIL "
                                          "<path> header(s)")
        _with_fs = dict(RESULT)
        _with_fs["steps"] = [_fs_step]
        _rfs = M.row_for(plain, _with_fs, "task", {"taskId": "P1.2"}, IDENT,
                         published=["pytest -q"])
        check("ef8 `failingSuites` CROSSES INTO THE ROW beside `failing`, "
              "which is what `STEP_KEYS` decides: %r"
              % (_rfs["steps"][0].get("failingSuites"),),
              "failingSuites" in M.STEP_KEYS and "failingSuitesBasis" in M.STEP_KEYS
              and _rfs["steps"][0]["failingSuites"][0] == "src/cart.test.ts"
              and "jest" in _rfs["steps"][0]["failingSuitesBasis"])
        check("ef9 ...and a path OUTSIDE the repository is tokenised on the way "
              "in, by the same redactor `treeMutated` uses - this row is "
              "committed, and a suite path naming somebody's machine is the "
              "same leak one door over: %r" % (_rfs["steps"][0]["failingSuites"],),
              _journal_io.OUTSIDE_TOKEN in _rfs["steps"][0]["failingSuites"]
              and not any(x.startswith(tmp)
                         for x in _rfs["steps"][0]["failingSuites"]))

        _over_fs = dict(RESULT)
        _over_fs["steps"] = [dict(RESULT["steps"][0], failingSuites=[
            "src/s%d.test.ts" % (n,) for n in range(M.MAX_PATHS + 5)],
            failingSuitesBasis="a caller that did not cut its own list")]
        _rofs = M.row_for(plain, _over_fs, "task", {"taskId": "P1.2"}, IDENT,
                          published=["pytest -q"])
        check("ef10 ...and CUT BY THE WRITER at `MAX_PATHS`, never trusted "
              "from the caller - the same backstop `failing`'s `ef3` holds: %r"
              % (len(_rofs["steps"][0]["failingSuites"]),),
              len(_rofs["steps"][0]["failingSuites"]) == M.MAX_PATHS)

        # --- fk: a flaky test is an OBSERVATION on the step -------------------
        # Playwright reports a test that failed and then passed on retry as
        # `flaky`, and the step still exits 0. The names are the runner's own
        # bytes, so they are cut and redacted as `failing` is; never an `outcome`,
        # because every tally here reads any outcome as not-passed.
        _fk_leak = "%s/elsewhere/cart.spec.js:2:1 > settles" % (tmp,)
        _fk_names = ["tests/s%d.spec.js:2:1 › settles on retry" % (n,)
                     for n in range(M.MAX_FAILING + 3)] + [_fk_leak]
        _fk_step = dict(RESULT["steps"][0], exit=0, flaky=_fk_names,
                        flakyBasis="the test(s) playwright named as flaky")
        _rfk = M.row_for(plain, dict(RESULT, status="passed", failed=[],
                                     steps=[_fk_step]),
                         "task", {"taskId": "P1.2"}, IDENT,
                         published=["pytest -q"])
        _fk_row_step = _rfk["steps"][0]
        check("fk1 `flaky` and `flakyBasis` CROSS INTO THE ROW on a step that "
              "exited 0 - `STEP_KEYS` names both: %r"
              % (sorted(k for k in _fk_row_step if k.startswith("flaky")),),
              "flaky" in M.STEP_KEYS and "flakyBasis" in M.STEP_KEYS
              and _fk_row_step.get("flaky", [None])[0]
              == "tests/s0.spec.js:2:1 › settles on retry"
              and "playwright" in (_fk_row_step.get("flakyBasis") or ""))
        check("fk2 ...CUT BY THE WRITER at `MAX_FAILING`, the bound `failing` "
              "carries, never trusted from the caller: %r"
              % (len(_fk_row_step.get("flaky") or []),),
              len(_fk_row_step.get("flaky") or []) == M.MAX_FAILING)
        _fk_red = M.row_for(plain, dict(RESULT, status="passed", failed=[],
                                        steps=[dict(_fk_step,
                                                    flaky=[_fk_leak])]),
                            "task", {"taskId": "P1.2"}, IDENT,
                            published=["pytest -q"])
        check("fk3 ...and REDACTED on the way in, by `failing`'s redactor - an "
              "absolute path in a flaky name is the same leak: %r"
              % (_fk_red["steps"][0].get("flaky"),),
              bool(_fk_red["steps"][0].get("flaky"))
              and tmp not in _journal_io.canonical(_fk_red["steps"][0]))
        check("fk4 A FLAKY-BUT-GREEN STEP IS A PASS in every tally: "
              "`gate_tally` counts it ran and NOT failed, which is what an "
              "`outcome` would have broken: %r"
              % (M.gate_tally([_rfk], "unit"),),
              M.gate_tally([_rfk], "unit") == (1, 0))

        # --- mq: a muted failure is on the row, with its mute -----------------
        _mq_step = dict(RESULT["steps"][0], exit=1,
                        failingSuites=["src/cart.test.ts"],
                        failingSuitesBasis="the suite file(s) jest named")
        _mq_entries = [{"test": "src/cart.test.ts", "bugId": "B1",
                        "until": "2026-10-01", "reason": "not carried",
                        "owner": "not carried either"}]
        _rmq = M.row_for(plain, dict(RESULT, status="passed", failed=[],
                                     steps=[_mq_step], muted=_mq_entries),
                         "task", {"taskId": "P1.2"}, IDENT,
                         published=["pytest -q"])
        check("mq1 `muted` CROSSES INTO THE ROW as `{test, bugId, until}` and "
              "nothing else, beside a step that keeps its own exit and "
              "failing suites: %r" % ((_rmq.get("muted"), _rmq["steps"][0]),),
              _rmq.get("muted") == [{"test": "src/cart.test.ts",
                                     "bugId": "B1", "until": "2026-10-01"}]
              and _rmq["steps"][0]["exit"] == 1
              and _rmq["steps"][0]["failingSuites"] == ["src/cart.test.ts"])
        check("mq2 ALLOW: a run nothing muted carries NO `muted` key - a key "
              "on every row could not be told from one a build does not "
              "write: %r" % (sorted(row),),
              "muted" not in row)
        _mq_over = [dict(_mq_entries[0], test="%s/out/s%d.test.ts" % (tmp, n))
                    for n in range(M.MAX_PATHS + 4)]
        _rmqo = M.row_for(plain, dict(RESULT, status="passed", failed=[],
                                      steps=[_mq_step], muted=_mq_over),
                          "task", {"taskId": "P1.2"}, IDENT,
                          published=["pytest -q"])
        check("mq3 ...CUT at `MAX_PATHS` and each `test` redacted as a suite "
              "path is: %r" % (len(_rmqo.get("muted") or []),),
              len(_rmqo.get("muted") or []) == M.MAX_PATHS
              and tmp not in _journal_io.canonical(_rmqo.get("muted")))
        _mr_rows = [dict(_rmq, **{M.REUSE_KEY: "k-mute", "ts": "2026-09-01T00:00:00Z"})]
        check("mq4 A VERDICT A MUTE EXCUSED IS NOT REPEATED: whether the mute "
              "still holds depends on the day it is graded, which no content "
              "identity can see - so `reusable_run` measures again: %r"
              % (M.reusable_run(_mr_rows, "task", {"taskId": "P1.2"},
                                "k-mute", ("passed", "failed")),),
              M.reusable_run(_mr_rows, "task", {"taskId": "P1.2"}, "k-mute",
                             ("passed", "failed")) is None
              and M.reusable_run([dict(_mr_rows[0], muted=None)], "task",
                                 {"taskId": "P1.2"}, "k-mute",
                                 ("passed", "failed")) is not None)

        # --- mq5-: the STEP carries its mute, and no tally counts it ----------
        _mq_marked = dict(_mq_step, muted=[
            {"test": "%s/out/s%d.test.ts" % (tmp, n), "bugId": "B1",
             "until": "2026-10-01", "reason": "dropped"}
            for n in range(M.MAX_PATHS + 2)])
        _rmm = M.row_for(plain, dict(RESULT, status="passed", failed=[],
                                     steps=[_mq_marked], muted=_mq_entries),
                         "task", {"taskId": "P1.2"}, IDENT,
                         published=["pytest -q"])
        _mm = _rmm["steps"][0].get("muted") or []
        check("mq5 `muted` IS A STEP KEY: the committed step says which mute "
              "excused it, cut at `MAX_PATHS`, each `test` redacted and each "
              "entry kept to suite, bug and day: %r" % (_mm[:1],),
              "muted" in M.STEP_KEYS and len(_mm) == M.MAX_PATHS
              and tmp not in _journal_io.canonical(_mm)
              and all(sorted(m) == ["bugId", "test", "until"] for m in _mm))
        _huge_bug = "B" + "x" * (_journal_io.MAX_VALUE_CHARS * 3)
        _rhb = M.row_for(plain, dict(RESULT, status="passed", failed=[],
                                     steps=[dict(_mq_step, muted=[dict(
                                         _mq_entries[0], bugId=_huge_bug,
                                         until="9" * (_journal_io.MAX_VALUE_CHARS * 3))])],
                                     muted=[dict(_mq_entries[0], bugId=_huge_bug)]),
                         "task", {"taskId": "P1.2"}, IDENT,
                         published=["pytest -q"])
        check("mq5b an oversized `bugId` or `until` is CUT to the bound every "
              "runner string on this row gets, on the row and on the step: %r"
              % ((len(_rhb["muted"][0]["bugId"]),
                  len(_rhb["steps"][0]["muted"][0]["bugId"]),
                  len(_rhb["steps"][0]["muted"][0]["until"])),),
              len(_rhb["muted"][0]["bugId"]) < len(_huge_bug)
              and len(_rhb["steps"][0]["muted"][0]["bugId"]) < len(_huge_bug)
              and len(_rhb["steps"][0]["muted"][0]["until"])
              < _journal_io.MAX_VALUE_CHARS * 3)
        _unmuted_row = M.row_for(plain, dict(RESULT, steps=[_mq_step]), "task",
                                 {"taskId": "P1.2"}, IDENT,
                                 published=["pytest -q"])
        check("mq6 A QUARANTINED FAILURE IS NOT A GATE CATCH: `gate_tally`, "
              "`command_tally` and `gate_last_caught` all read a muted step as "
              "ran and not failed: %r"
              % ((M.gate_tally([_rmm], "unit"),
                  M.command_tally([_rmm], "pytest -q"),
                  M.gate_last_caught([_rmm], "unit")),),
              M.gate_tally([_rmm], "unit") == (1, 0)
              and M.command_tally([_rmm], "pytest -q") == (1, 0)
              and M.gate_last_caught([_rmm], "unit") is None)
        check("mq7 ALLOW: the same failed step with no mute is counted as it "
              "always was: %r"
              % ((M.gate_tally([_unmuted_row], "unit"),
                  M.gate_last_caught([_unmuted_row], "unit")),),
              M.gate_tally([_unmuted_row], "unit") == (1, 1)
              and M.command_tally([_unmuted_row], "pytest -q") == (1, 1)
              and M.gate_last_caught([_unmuted_row], "unit") is not None)

        # --- og1-og5: WHY a step could not run, kept beside the verdict ---------
        # A `could-not-run` step already carries `outcome`, and until now nothing
        # else - a derived run that skipped a listed suite, a missing interpreter
        # and a runner's own "no tests found" all collapsed onto that one word,
        # which is the defect this proves closed. `outcomeBasis` and `derivedGap`
        # are the two fields `run-test-gate.observed_step`/`run_gate` already put
        # on the STEP dict; this proves they survive into the committed row.
        _cnr_step = dict(RESULT["steps"][0], exit=1)
        _cnr_step["outcome"] = "could-not-run"
        _cnr_step["outcomeBasis"] = (
            "no test files found in /Users/%s/shop" % (_leak_user,))
        _cnr = dict(RESULT)
        _cnr["steps"] = [_cnr_step]
        _rcnr = M.row_for(plain, _cnr, "task", {"taskId": "P1.2"}, IDENT,
                          published=["pytest -q"])
        check("og1 a `could-not-run` step keeps ITS OWN `outcomeBasis` on the "
              "committed row - the ONE field that says why nothing was measured, "
              "which `STEP_KEYS` has to name before `_step` will carry it: %r"
              % (_rcnr["steps"][0].get("outcomeBasis"),),
              "outcomeBasis" in M.STEP_KEYS
              and "no test files found" in _rcnr["steps"][0]["outcomeBasis"])
        check("og2 ...REDACTED on the way in, the same rule `failing` obeys: "
              "this row is committed, and a no-verdict sentence naming a home "
              "directory is the identical CWE-532 leak one field over: %r"
              % (_rcnr["steps"][0]["outcomeBasis"],),
              _journal_io.OUTSIDE_TOKEN in _rcnr["steps"][0]["outcomeBasis"]
              and _journal_io.canonical(_rcnr).count(_leak_user) == 0)

        _long_basis = dict(RESULT)
        _long_step = dict(RESULT["steps"][0], exit=1)
        _long_step["outcome"] = "could-not-run"
        _long_step["outcomeBasis"] = "x" * (_journal_io.MAX_VALUE_CHARS + 50)
        _long_basis["steps"] = [_long_step]
        _rlb = M.row_for(plain, _long_basis, "task", {"taskId": "P1.2"}, IDENT,
                         published=["pytest -q"])
        check("og3 ...and BOUNDED to a size limit exactly as `failing` is, "
              "never trusted whole from the caller - a row is hash-chained, "
              "so an unbounded free-text field is a row of unbounded size: %r"
              % (len(_rlb["steps"][0]["outcomeBasis"]),),
              len(_rlb["steps"][0]["outcomeBasis"]) <= _journal_io.MAX_VALUE_CHARS)

        # A derived run that answered on a NARROWER question than the phase
        # declared is a second, DISTINCT reason a step reads `could-not-run` -
        # `run-test-gate.run_gate` marks it with `derivedGap: True` rather than
        # a string a reader would have to parse back out of the basis sentence.
        _gap_step = dict(RESULT["steps"][0], exit=0)
        _gap_step["outcome"] = "could-not-run"
        _gap_step["outcomeBasis"] = "DERIVED RUN NAMED 1 OF 2 LISTED SUITES: unit"
        _gap_step["derivedGap"] = True
        _gap = dict(RESULT)
        _gap["steps"] = [_gap_step]
        _rgap = M.row_for(plain, _gap, "task", {"taskId": "P1.2"}, IDENT,
                          published=["pytest -q"])
        check("og4 a DERIVED-RUN GAP is a MARKER on the row, distinguishable "
              "from a missing interpreter or a bare no-verdict signature - "
              "`derivedGap` is `STEP_KEYS`'s and never a string match on the "
              "basis sentence: %r" % (_rgap["steps"][0].get("derivedGap"),),
              "derivedGap" in M.STEP_KEYS
              and _rgap["steps"][0]["derivedGap"] is True
              and _rcnr["steps"][0].get("derivedGap") is None)
        _passed_step = dict(RESULT["steps"][0], exit=0)
        _passed = dict(RESULT, steps=[_passed_step])
        _rpassed = M.row_for(plain, _passed, "task", {"taskId": "P1.2"}, IDENT,
                             published=["pytest -q"])
        check("og5 the allow case: a PASSED step - one whose input carries "
              "neither key - gains neither on the row. The row only gains "
              "keys for a step this file's own caller actually set, never for "
              "every step by default: %r" % (sorted(_rpassed["steps"][0]),),
              "outcomeBasis" not in _rpassed["steps"][0]
              and "derivedGap" not in _rpassed["steps"][0])

        # --- suiteReader and suite_keys, the ledger's own answer to "was a
        # test suite even run" for a gate key that is not test-shaped by name.
        def _row_with(steps, run_id="R-sk", ts="2026-09-01T00:00:00Z"):
            r = dict(RESULT, steps=steps)
            return M.row_for(plain, r, "task", {"taskId": "P1.2"},
                             dict(IDENT, runId=run_id, ts=ts),
                             published=["pytest -q"])

        sk_rows = [
            _row_with([dict(RESULT["steps"][0], name="lint",
                            suiteReader="none")]),
            _row_with([dict(RESULT["steps"][0], name="test",
                            suiteReader="jest")]),
            _row_with([dict(RESULT["steps"][0], name="test",
                            suiteReader="none")]),
            _row_with([{k: v for k, v in RESULT["steps"][0].items()}]),
        ]
        # the fourth row's step is named the same as `RESULT["steps"][0]`
        # ("unit") and carries NO `suiteReader` at all - unknown, unless some
        # OTHER row answers for that name too.
        sk = M.suite_keys(sk_rows)
        check("sk1 a name recorded RUNNING even once is RUNNING - one row "
              "naming `jest` for `test` settles the question for that name, "
              "whatever another row recorded beside it: %r" % (sk,),
              sk["running"] == ["test"])
        check("sk2 a name that carried the field and was NEVER anything but "
              "`none` is SILENT: %r" % (sk,),
              sk["silent"] == ["lint"])
        check("sk3 a name recorded ONLY in rows from before this field "
              "existed - the key absent outright, never `none` - is UNKNOWN: "
              "%r" % (sk,),
              sk["unknown"] == ["unit"])

        _sk_absent_then_running = [
            _row_with([{k: v for k, v in RESULT["steps"][0].items()}]),
            _row_with([dict(RESULT["steps"][0], suiteReader="jest")]),
        ]
        check("sk4 SECOND DIRECTION: a name seen BOTH ways - once with no "
              "field, once running - is not unknown. The moment any row "
              "answers for a name, `unknown` no longer names it: %r"
              % (M.suite_keys(_sk_absent_then_running),),
              M.suite_keys(_sk_absent_then_running)["unknown"] == []
              and M.suite_keys(_sk_absent_then_running)["running"] == ["unit"])

        check("sk5 ALLOW: no rows at all answers every key with an empty "
              "list rather than raising - a plan with no ledger yet has "
              "asked a real question and gotten a real, empty answer: %r"
              % (M.suite_keys([]),),
              M.suite_keys([]) == {"running": [], "silent": [], "unknown": []})

        rb_rows = [
            _row_with([RESULT["steps"][0]], run_id="R-old",
                      ts="2026-09-01T00:00:00Z"),
            _row_with([RESULT["steps"][0]], run_id="R-new",
                      ts="2026-09-02T00:00:00Z"),
            _row_with([RESULT["steps"][0]], run_id="R-new",
                      ts="2026-09-03T00:00:00Z"),
        ]
        check("rr1 `row_by_run` finds the row carrying that `runId`, newest "
              "by `ts` when more than one writer recorded the same id: %r"
              % (M.row_by_run(rb_rows, "R-new") or {}).get("ts"),
              (M.row_by_run(rb_rows, "R-new") or {}).get("ts")
              == "2026-09-03T00:00:00Z")
        check("rr2 ALLOW: an id no row carries answers None, never the newest "
              "row in the list - a caller asking for a run that was never "
              "recorded must not be handed somebody else's",
              M.row_by_run(rb_rows, "R-does-not-exist") is None
              and M.row_by_run([], "R-new") is None
              and M.row_by_run(rb_rows, None) is None)
        # THE RUNNER'S OWN READING: green is exactly `passed`. A status no
        # writer has produced, and a row with no status, are red - a reader
        # widening green to "anything not named failed" goes red on them, and
        # one reading every row as red goes red on the first.
        is_red = getattr(M, "row_is_red", None)
        red_of = [None if is_red is None else is_red(r) for r in (
            {"status": "passed"}, {"status": "failed"},
            {"status": "a-word-no-writer-wrote"}, {})]
        check("rr2b RED-FIRST: `row_is_red` is False for passed alone - True "
              "for failed, for a status no reader has written, and for no "
              "status at all: %r" % (red_of,),
              red_of == [False, True, True, True])
        # Text order and moment order DISAGREE here: the offset stamp spells
        # a later day but names an earlier moment, and the unparseable stamp
        # is greatest of all as text.
        rb_moment = [
            _row_with([RESULT["steps"][0]], run_id="R-m",
                      ts="2026-09-02T23:00:00Z"),
            _row_with([RESULT["steps"][0]], run_id="R-m",
                      ts="2026-09-03T00:00:00+05:00"),
            _row_with([RESULT["steps"][0]], run_id="R-m", ts="zzz-not-a-ts"),
        ]
        check("rr3 `row_by_run` settles a shared runId by the MOMENT each "
              "`ts` names, never by its spelling, and a `ts` that will not "
              "parse never wins over one that does: %r"
              % (M.row_by_run(rb_moment, "R-m") or {}).get("ts"),
              (M.row_by_run(rb_moment, "R-m") or {}).get("ts")
              == "2026-09-02T23:00:00Z")
        rb_undated = [
            _row_with([RESULT["steps"][0]], run_id="R-u", ts="zzz-first"),
            _row_with([RESULT["steps"][0]], run_id="R-u", ts="aaa-second"),
        ]
        check("rr4 ALLOW: when no row carrying the id has a readable `ts`, "
              "the run is still found - the last one in ledger order - rather "
              "than answered None as if it had never been recorded: %r"
              % (M.row_by_run(rb_undated, "R-u") or {}).get("ts"),
              (M.row_by_run(rb_undated, "R-u") or {}).get("ts")
              == "aaa-second")
        # The same disagreement, put to every other reader here that picks
        # a newest row: the offset stamp spells a later day, names an earlier
        # moment, and must lose.
        _mo_early_text = "2026-09-02T23:00:00Z"
        _mo_late_text = "2026-09-03T00:00:00+05:00"
        _mo_subject = [
            {"scope": "task", "taskId": "P1.1", "runId": "MO-A",
             "ts": _mo_early_text},
            {"scope": "task", "taskId": "P1.1", "runId": "MO-B",
             "ts": _mo_late_text}]
        _mo_best = M.latest_by_subject(_mo_subject).get(("task", "P1.1"))
        check("mo1 `latest_by_subject` keeps the run whose ts names the later "
              "MOMENT, not the later spelling: %r" % ((_mo_best or {}).get(
                  "runId"),),
              (_mo_best or {}).get("runId") == "MO-A")
        _mo_reuse = [dict(_mr_rows[0], muted=None,
                          **{"runId": "MO-A", "ts": _mo_early_text}),
                     dict(_mr_rows[0], muted=None,
                          **{"runId": "MO-B", "ts": _mo_late_text})]
        _mo_reused = M.reusable_run(_mo_reuse, "task", {"taskId": "P1.2"},
                                    "k-mute", ("passed", "failed"))
        check("mo2 `reusable_run` repeats the run whose ts names the later "
              "MOMENT: %r" % ((_mo_reused or {}).get("runId"),),
              (_mo_reused or {}).get("runId") == "MO-A")
        _mo_caught = [
            {"ts": _mo_early_text, "runId": "MO-A",
             "steps": [{"name": "lint", "exit": 1}]},
            {"ts": _mo_late_text, "runId": "MO-B",
             "steps": [{"name": "lint", "exit": 1}]}]
        check("mo3 `gate_last_caught` answers the ts naming the later MOMENT: "
              "%r" % (M.gate_last_caught(_mo_caught, "lint"),),
              M.gate_last_caught(_mo_caught, "lint") == _mo_early_text)
        # ...and at the OTHER end of the list: the earliest moment is the late
        # spelling here, and an unparseable stamp is never the earliest.
        check("mo4 `earliest_recorded` answers the ts naming the earliest "
              "MOMENT, and a ts that will not parse never wins: %r"
              % (M.earliest_recorded(_mo_caught + [{"ts": "0-not-a-ts"}]),),
              M.earliest_recorded(_mo_caught + [{"ts": "0-not-a-ts"}])
              == _mo_late_text)
        _mo_bound = M.boundary_of({"at": _mo_early_text}, _mo_late_text)
        check("mo5 `boundary_of` takes the earlier MOMENT of the plan's "
              "stated start and the ledger's earliest run, and hands it on in "
              "the one Z spelling every consumer reads: %r"
              % (_mo_bound["at"],),
              _mo_bound["at"] == "2026-09-02T19:00:00Z"
              and _mo_bound["sources"]["ledger"] == _mo_late_text)
        # A hand-written plan start that names a DAY: the start of that day in
        # UTC, the earliest moment it can mean, so it is never read as later.
        _mo_day = M.boundary_of({"at": "2026-09-01"}, "2026-09-05T00:00:00Z")
        check("mo6 RED-FIRST: a date-only `evidenceSince.at` is a moment - "
              "the start of that day in UTC - so it stays the earlier "
              "boundary beside a later ledger row, with nothing unknown: %r"
              % (_mo_day,),
              _mo_day["at"] == "2026-09-01T00:00:00Z"
              and _mo_day["unknown"] == []
              and _mo_day["sources"]["key"] == "2026-09-01"
              and M.stamp_moment("2026-09-01")
              == M.stamp_moment("2026-09-01T00:00:00Z"))
        _mo_junk = M.boundary_of({"at": "Sept 1 2026"}, "2026-09-05T00:00:00Z")
        check("mo7 RED-FIRST: a plan start that is no moment at all is NEVER "
              "dropped in silence: it is named in `unknown` - the answer that "
              "says the boundary may be later than the truth - and in the "
              "basis, which no longer claims it is the earlier of the two: %r"
              % (_mo_junk,),
              any("Sept 1 2026" in u for u in _mo_junk["unknown"])
              and "Sept 1 2026" in _mo_junk["basis"]
              and "the earlier of the two" not in _mo_junk["basis"])

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

        # WHERE THE `steps` LIST CAME FROM. `steps` names the entries that
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

        # THE WORD THE RUNNER COULD NOT SAY, AND THE CACHE THAT REPEATED
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

        # --- RED-FIRST: a CI writer names its own ledger file -------------------
        # A SEPARATE PROJECT, not `plain` - every case below this point counts
        # evidence FILES and ROWS in `plain`, and a write here would shift
        # both counts out from under them.
        writer_proj = _project(os.path.join(tmp, "writer"), {})
        with_session = dict(row)
        with_session["runId"] = "R-writer-session"
        p_named = M.append_row(writer_proj, with_session, session_id="sess-9",
                               writer="ci-42")
        check("ev18b RED-FIRST: `--writer` reaches `append_row` and WINS over a "
              "session id - a build's own name should not be split across files "
              "by which session happened to invoke the shard: %r"
              % (os.path.basename(p_named),),
              "ci-42" in os.path.basename(p_named)
              and "sess-9" not in os.path.basename(p_named))

        rec_result = {"status": "passed", "steps": [], "testedState": {}}
        recorded = M.record(writer_proj, rec_result, "full", {},
                            {"runId": "R-writer-record", "sessionId": "sess-10"},
                            writer="ci-99")
        check("ev18c ...and the SAME name reaches a ledger file through "
              "`record()`, not only through `append_row` called by hand: %r"
              % (os.path.basename(recorded["path"]),),
              "ci-99" in os.path.basename(recorded["path"]))

        back = M.read_rows(plain)
        check("ev19 both rows read back, and the reader says how many files it "
              "walked - 'no rows' and 'no files' are different answers and a "
              "reader that returned a bare list could not tell them apart: %r"
              % ((len(back["rows"]), back["files"], back["unreadable"]),),
              len(back["rows"]) == 2 and back["files"] == 2
              and back["unreadable"] == 0
              and sorted(r["runId"] for r in back["rows"]) == ["R1", "R2"])
        pairs = sorted(zip([r["runId"] for r in back["rows"]],
                           back.get("rowFiles") or []))
        check("ev19b `rowFiles` names, per row and at the row's own index, the "
              "BASENAME of the ledger file it was read from - a caller that "
              "must say which file holds a run reads it here instead of "
              "walking the directory a second time with a different decode: %r"
              % (pairs,),
              len(back.get("rowFiles") or []) == len(back["rows"])
              and pairs == [("R1", os.path.basename(path)),
                            ("R2", os.path.basename(p2))])

        with open(path, "a", encoding="utf-8") as fh:
            fh.write("{not json at all\n")
        torn = M.read_rows(plain)
        check("ev20b ...and a line that never became a row adds no entry, so "
              "`rowFiles` stays index-aligned with `rows`: %r"
              % ((len(torn["rows"]), len(torn.get("rowFiles") or [])),),
              len(torn.get("rowFiles") or []) == len(torn["rows"]) == 2)
        # A torn TAIL never becomes a row object at all; a bad line in the
        # MIDDLE does, marked unparseable - the branch the tail cannot reach.
        mid_proj = _project(os.path.join(tmp, "rowfiles-mid"), {})
        mid_dir = M.evidence_dir(mid_proj)
        os.makedirs(mid_dir, exist_ok=True)
        with open(os.path.join(mid_dir, "2026-01.mid.jsonl"), "w",
                  encoding="utf-8") as fh:
            fh.write('{"runId": "M1"}\n{not json at all\n{"runId": "M2"}\n')
        mid = M.read_rows(mid_proj)
        check("ev20c ...nor does an unparseable line in the MIDDLE of a file: "
              "`rowFiles` stays index-aligned with `rows`: %r"
              % ((mid["unreadable"], mid.get("rowFiles")),),
              mid["unreadable"] == 1
              and [r.get("runId") for r in mid["rows"]] == ["M1", "M2"]
              and mid.get("rowFiles") == ["2026-01.mid.jsonl"] * 2)
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

        # ONE DECODE FOR EVERY READER. A byte that is not UTF-8 is planted
        # inside a runId; a lenient reader would hand back that row with a
        # replacement character standing in for the byte, as if it were clean,
        # while the strict verifier grades the same file unreadable.
        bad_proj = _project(os.path.join(tmp, "not-utf8"), {})
        bad_dir = M.evidence_dir(bad_proj)
        os.makedirs(bad_dir, exist_ok=True)
        bad_path = os.path.join(bad_dir, "2026-01.bad.jsonl")
        with open(bad_path, "wb") as fh:
            fh.write(b'{"runId": "B-clean"}\n{"runId": "B-\xffmoved"}\n')
        bad_read = M.read_rows(bad_proj)
        bad_verdict = M.verify(bad_proj)
        replaced = [r for r in bad_read["rows"] if "�" in json.dumps(
            r, ensure_ascii=False)]
        check("ev21b RED-FIRST: a byte that does not decode loses the FILE in "
              "`read_rows` - it joins `unreadableFiles` and the count, and no "
              "row carrying a replacement character comes back as clean: %r"
              % ((bad_read["unreadableFiles"], bad_read["unreadable"],
                  [r.get("runId") for r in bad_read["rows"]]),),
              bad_read["unreadableFiles"] == [bad_path]
              and bad_read["unreadable"] >= 1
              and replaced == [] and bad_read["rows"] == [])
        bad_files = [f for f in bad_verdict["files"]
                     if f["file"] == "2026-01.bad.jsonl"]
        check("ev21c ...and `verify` grades the SAME file the same way - "
              "unreadable, a finding, not one of its rows checked - so the two "
              "readers disagree about nothing: %r" % (bad_files,),
              len(bad_files) == 1 and bad_files[0]["rows"] == 0
              and any("could not be read" in f
                      for f in bad_files[0]["findings"])
              and not bad_verdict["ok"])
        with open(bad_path, "rb") as fh:
            bad_offset = fh.read().index(b"\xff")
        bad_said = " ".join(bad_files[0]["findings"]) if bad_files else ""
        check("ev21e ...and its finding names the byte and its offset in the "
              "FILE's bytes - the remedy import-evidence prints sends the "
              "reader to that position, so it must be the file's own, not a "
              "line's: %r (byte at %d)" % (bad_said, bad_offset),
              "0xff" in bad_said
              and ("in position %d:" % bad_offset) in bad_said)
        uni_proj =_project(os.path.join(tmp, "utf8-non-ascii"), {})
        uni_dir = M.evidence_dir(uni_proj)
        os.makedirs(uni_dir, exist_ok=True)
        with open(os.path.join(uni_dir, "2026-01.uni.jsonl"), "w",
                  encoding="utf-8") as fh:
            fh.write('{"runId": "U-ćevap — été"}\n')
        uni_read = M.read_rows(uni_proj)
        uni_verdict = M.verify(uni_proj)
        check("ev21d ALLOW: a clean UTF-8 file with non-ASCII text reads as "
              "before - its row returned intact, nothing lost, no finding: %r"
              % ((uni_read, uni_verdict["findings"]),),
              [r.get("runId") for r in uni_read["rows"]]
              == ["U-ćevap — été"]
              and uni_read["unreadable"] == 0
              and uni_read["unreadableFiles"] == []
              and not any("could not be read" in f
                          for f in uni_verdict["findings"]))

        # An append onto a file no reader can decode would store a run every
        # reader then loses with the file - so the write is REFUSED, the file
        # left byte-for-byte as it was, and `record()` raises the refusal a
        # recorder prints as "evidence: NOT recorded - <reason>".
        ap_proj = _project(os.path.join(tmp, "append-undecodable"), {})
        ap_path = M.append_row(ap_proj, {"runId": "AP-1",
                                         "ts": "2026-01-05T00:00:00Z"},
                               writer="w-ap")
        with open(ap_path, "ab") as fh:
            fh.write(b'{"runId": "AP-\xff"}\n')
        with open(ap_path, "rb") as fh:
            ap_before = fh.read()
        ap_errors = []
        for ap_call in (
                lambda: M.append_row(ap_proj, {"runId": "AP-2",
                                               "ts": "2026-01-06T00:00:00Z"},
                                     writer="w-ap"),
                lambda: M.record(ap_proj, {"status": "passed", "steps": [],
                                           "testedState": {}}, "full", {},
                                 {"runId": "AP-3",
                                  "ts": "2026-01-07T00:00:00Z"},
                                 writer="w-ap")):
            try:
                ap_call()
                ap_errors.append(None)
            except Exception as exc:
                ap_errors.append(str(exc))
        with open(ap_path, "rb") as fh:
            ap_after = fh.read()
        check("ap1 RED-FIRST: appending onto a ledger file that is not UTF-8 "
              "is REFUSED - `append_row` and `record()` both raise, naming the "
              "file, and not one byte is written: %r" % (ap_errors,),
              len(ap_errors) == 2 and all(ap_errors)
              and all(os.path.basename(ap_path) in e for e in ap_errors if e)
              and all("not UTF-8" in e for e in ap_errors if e)
              and ap_after == ap_before)

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

        # ONE RULE FOR "IS THIS LOCK OURS", the lock's own. A claim another live
        # process of this session took for its own write is that process's; a
        # pointer written under it with no lock of its own is the lost write the
        # lock serialises every other caller against.
        import platform as _pf
        _pl_path = os.path.join(_locks.lock_dir(gitproj), "phase-P1.lock")
        _pl_claim = {"sessionId": "me", "pid": os.getppid(), "hostname": _pf.node(),
                     "note": "another process's write", "token": "tok-elsewhere",
                     "handedOff": False,
                     "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        _locks._write_lock(_pl_path, _pl_claim)
        _pl_other, _pl_why = M.pointer_lock_state(gitproj, "P1", session_id="me")
        _locks._write_lock(_pl_path, dict(_pl_claim, handedOff=True))
        _pl_hand, _d = M.pointer_lock_state(gitproj, "P1", session_id="me")
        os.unlink(_pl_path)
        check("ed8b RED-FIRST: a claim ANOTHER live process of this session took "
              "for its own write reads `held`, as `_locks.acquire` answers it - "
              "one rule for whose lock it is, not a second copy that still "
              "trusts the session: %r" % ((_pl_other, _pl_why),),
              _pl_other == "held" and "reconcile" in (_pl_why or ""))
        check("ed8c ALLOW: the same claim taken BY HAND (`handedOff`) is still "
              "this session's to work under, so it reads `ours`: %r" % (_pl_hand,),
              _pl_hand == "ours")

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

        # A MOVED TASK'S RUNS STILL JOIN. The ledger keeps the subject a run was
        # recorded under, and `move` gives the task a new id - so a reader keyed on
        # the id alone sees a subject the plan no longer has, and a reconcile
        # would aim at it. The plan's `movedFrom` chain is the map.
        _mv_plan = {"phases": [{"id": "P1", "tasks": [
            {"id": "P1.2", "movedFrom": {"id": "P1.1", "phase": "P1",
                                         "previous": {"id": "P0.9", "phase": "P0"}}}]}]}
        _mv_alias = M.subject_aliases(_mv_plan)
        _mv_best = M.latest_by_subject(
            [{"runId": "RO", "ts": "2026-08-26T09:00:00Z", "scope": "task",
              "taskId": "P0.9"},
             {"runId": "RM", "ts": "2026-08-26T10:00:00Z", "scope": "task",
              "taskId": "P1.1"}], aliases=_mv_alias)
        check("mvr1 `subject_aliases` maps every id a task was moved FROM onto the id "
              "it holds now, and `latest_by_subject` keys the runs through it - the "
              "newest of all of them, under the live id: %r"
              % ((_mv_alias, dict((k, v["runId"]) for k, v in _mv_best.items())),),
              _mv_alias == {("task", "P1.1"): ("task", "P1.2"),
                            ("task", "P0.9"): ("task", "P1.2")}
              and dict((k, v["runId"]) for k, v in _mv_best.items())
              == {("task", "P1.2"): "RM"})
        _mv_bad = {"phases": [{"id": "P1", "tasks": [
            {"id": "P1.1"},
            {"id": "P1.2", "movedFrom": {"id": "P1.1", "phase": "P1"}},
            {"id": "P1.3", "movedFrom": {"id": "P0.5", "phase": "P0"}},
            {"id": "P1.4", "movedFrom": {"id": "P0.5", "phase": "P0"}},
            {"id": "P1.5", "movedFrom": {"id": "P0.6", "phase": "P0"}}]}]}
        _mv_bad_alias = M.subject_aliases(_mv_bad)
        check("mvr3 an old id a LIVE task holds is never aliased away from it, and "
              "one two chains both claim is aliased to neither - only the clean "
              "link is kept: %r" % (_mv_bad_alias,),
              _mv_bad_alias == {("task", "P0.6"): ("task", "P1.5")})
        mvproj, mvpath = _manifest_project("recon-moved")
        with open(os.path.join(mvproj, "docs", "audit", "phases", "P1.json"),
                  "w") as fh:
            _json.dump({"id": "P1", "title": "one", "status": "in_progress",
                        "testGate": [], "tasks": [
                            {"id": "P1.2", "title": "t", "status": "blocked",
                             "movedFrom": {"id": "P2.1", "phase": "P2",
                                           "at": "2026-08-26T11:00:00Z"}}]}, fh)
        M.append_row(mvproj, {"v": 1, "runId": "RM", "ts": "2026-08-26T10:00:00Z",
                              "scope": "task", "taskId": "P2.1", "phaseId": "P2",
                              "status": "failed", "steps": []})
        mvrep = M.reconcile(mvproj, mvpath)
        mvbody = _json.loads(io.open(os.path.join(mvproj, "docs", "audit", "phases",
                                                  "P1.json"), encoding="utf-8").read())
        check("mvr2 reconcile points a MOVED task at the runs recorded under its old "
              "id, in the phase it lives in now - not at an id the plan no longer "
              "has: %r" % ((mvrep["moved"], mvrep["refused"]),),
              mvrep["moved"] == ["task P1.2 -> RM"] and mvrep["refused"] == []
              and mvbody["tasks"][0].get("testEvidence", {}).get("runId") == "RM")

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

        jproj, jpath = _manifest_project("junk-ts")
        for rid, ts in (("RJ", "not-a-moment"), ("RD", "2026-08-26T11:00:00Z")):
            M.append_row(jproj, {"v": 1, "runId": rid, "ts": ts, "scope": "task",
                                 "taskId": "P1.1", "phaseId": "P1",
                                 "status": "passed"})
        _junk = M.evidence_boundary(jproj, jpath)
        check("mo8 RED-FIRST: a ledger row whose ts is no moment is not dropped "
              "in silence when another row's ts parses - it may be the earliest "
              "run, so it is NAMED in `unknown`: at=%r unknown=%r"
              % (_junk["at"], _junk["unknown"]),
              _junk["at"] == "2026-08-26T11:00:00Z"
              and any("not-a-moment" in u for u in _junk["unknown"]))

        # A ROW WITH NO ts AT ALL, and no other row to place: `at` stays None,
        # which alone would excuse everything - so the run is named in
        # `unknown`, and the basis does not claim no run is readable.
        nproj, npath = _manifest_project("no-ts")
        M.append_row(nproj, {"v": 1, "runId": "RN", "scope": "task",
                             "taskId": "P1.1", "phaseId": "P1",
                             "status": "passed"})
        _nots = M.evidence_boundary(nproj, npath)
        check("mo9 RED-FIRST: a ledger row carrying NO ts is unplaced too - "
              "named in `unknown` even when no row's ts places a moment, and "
              "the basis says so rather than that nothing is readable: "
              "at=%r unknown=%r basis=%r"
              % (_nots["at"], _nots["unknown"], _nots["basis"]),
              _nots["at"] is None
              and any("RN" in u for u in _nots["unknown"])
              and "no run is readable" not in _nots["basis"])

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
        check("wr10 a run that STARTS in the second the other's row was written, BY THE "
              "SAME WRITER, is sequential - half-open at the end, in both orders: "
              "%r / %r" % (M.overlap_state((10, 20), (20, 30), ordered=True),
                           M.overlap_state((20, 30), (10, 20), ordered=True)),
              M.overlap_state((10, 20), (20, 30), ordered=True) == M.OVERLAP_NO
              and M.overlap_state((20, 30), (10, 20), ordered=True) == M.OVERLAP_NO
              and M.overlap_state((10, 20), (21, 30)) == M.OVERLAP_NO)
        check("wr10g ...but ACROSS writers the shared boundary second orders nothing - "
              "undecided, never asserted sequential: %r / %r"
              % (M.overlap_state((10, 20), (20, 30)),
                 M.overlap_state((20, 20), (10, 20), ordered=True)),
              M.overlap_state((10, 20), (20, 30)) == M.OVERLAP_UNDECIDED
              and M.overlap_state((20, 30), (10, 20)) == M.OVERLAP_UNDECIDED
              and M.overlap_state((20, 20), (10, 20), ordered=True) == M.OVERLAP_NO)
        check("wr10b SECOND DIRECTION: windows that genuinely share a second or more "
              "still overlap - %r / %r" % (M.overlap_state((10, 20), (19, 30)),
                                           M.overlap_state((15, 15), (10, 20))),
              M.overlap_state((10, 20), (19, 30)) == M.OVERLAP_YES
              and M.overlap_state((19, 30), (10, 20)) == M.OVERLAP_YES
              and M.overlap_state((15, 15), (10, 20)) == M.OVERLAP_YES)
        check("wr10c a run shorter than a second, stamped in the very second the other "
              "started or ended, is one whole-second stamps cannot place either side "
              "of it - UNDECIDED, never asserted either way: %r"
              % (M.overlap_state((20, 20), (10, 20)),),
              M.overlap_state((20, 20), (10, 20)) == M.OVERLAP_UNDECIDED
              and M.overlap_state((10, 10), (10, 20)) == M.OVERLAP_UNDECIDED
              and M.overlap_state((12, 12), (12, 12)) == M.OVERLAP_UNDECIDED)
        # The reported shape: three task gates recorded strictly one after another,
        # each starting in the second the previous row was written.
        _seq = [{"runId": "A", M.STARTED_KEY: "2026-09-26T15:48:37Z",
                 "ts": "2026-09-26T15:49:37Z"},
                {"runId": "B", M.STARTED_KEY: "2026-09-26T15:49:37Z",
                 "ts": "2026-09-26T15:50:39Z"},
                {"runId": "C", M.STARTED_KEY: "2026-09-26T15:50:39Z",
                 "ts": "2026-09-26T15:51:38Z"}]
        _chain = M.chain_file(_seq, "2026-09.writer.jsonl")
        _crowd = [_seamed(M.shared_the_machine, _chain, r, seams=[])[0]
                  for r in _chain]
        _unsure = [_seamed(M.undecided_neighbours, _chain, r, M.RUNNER_GATE,
                           seams=[]) for r in _chain]
        check("wr10d runs ONE writer's chain records strictly one after another are "
              "not a crowd and not undecided either - each finds nobody else in its "
              "window: %r / %r"
              % ([[o.get("runId") for o in c] for c in _crowd],
                 [[o.get("runId") for o in u] for u in _unsure]),
              _crowd == [[], [], []] and _unsure == [[], [], []])
        _apart = (M.chain_file([_seq[0]], "2026-09.one.jsonl")
                  + M.chain_file([_seq[1]], "2026-09.two.jsonl"))
        check("wr10h ...while the same two windows from TWO writers meet in a second "
              "no chain orders - undecided, not sequential: %r"
              % (_ids(_seamed(M.undecided_neighbours, _apart, _apart[1],
                              M.RUNNER_GATE, seams=[])),),
              _seamed(M.shared_the_machine, _apart, _apart[1], seams=[])[0] == []
              and _ids(_seamed(M.undecided_neighbours, _apart, _apart[1],
                               M.RUNNER_GATE, seams=[])) == ["A"])
        _over = [dict(_seq[0]), dict(_seq[1], **{M.STARTED_KEY:
                                                 "2026-09-26T15:49:30Z"})]
        check("wr10e SECOND DIRECTION: a run that began seven seconds before the other "
              "ended IS in its window: %r"
              % ([o.get("runId") for o in M.shared_the_machine(_over, _over[1])[0]],),
              [o.get("runId") for o in M.shared_the_machine(_over, _over[1])[0]]
              == ["A"])
        _blip = {"runId": "Z", M.STARTED_KEY: "2026-09-26T15:49:37Z",
                 "ts": "2026-09-26T15:49:37Z"}
        check("wr10f ...and a sub-second run stamped in the second the other ended is "
              "reported as undecided, not as sharing the window: shared %r, "
              "undecided %r"
              % (M.shared_the_machine([_blip], _seq[0])[0],
                 [o.get("runId") for o in
                  M.undecided_neighbours([_blip], _seq[0], M.RUNNER_GATE)]),
              M.shared_the_machine([_blip], _seq[0])[0] == []
              and [o.get("runId") for o in
                   M.undecided_neighbours([_blip], _seq[0], M.RUNNER_GATE)] == ["Z"])

        _mixed = M.chain_file(
            [_seq[0], dict(_seq[1], **{M.RUNNER_KEY: M.RUNNER_OUTSIDE})],
            "2026-09.one.jsonl")
        check("wr10i an OUTSIDE suite whose row one writer's chain holds right after a "
              "gate run is not ordered by that chain - the suite ran where no chain "
              "watched it - so the shared second stays undecided: %r"
              % (_ids(_seamed(M.undecided_neighbours, _mixed, _mixed[1],
                              M.RUNNER_GATE, seams=[])),),
              _ids(_seamed(M.undecided_neighbours, _mixed, _mixed[1],
                           M.RUNNER_GATE, seams=[])) == ["A"])
        _g = {"runId": "G", M.STARTED_KEY: "2026-09-26T10:00:12Z",
              "ts": "2026-09-26T10:00:12Z"}
        _o = {"runId": "O", M.STARTED_KEY: "2026-09-26T10:00:05Z",
              "ts": "2026-09-26T10:00:12Z", M.RUNNER_KEY: M.RUNNER_OUTSIDE}
        _gv = M.attribution_of(_g, [_o])
        check("wr11b a sub-second gate red stamped in an outside run's end second is "
              "neither its own verdict nor contested - the whole-second stamps cannot "
              "say, and the basis names the run: %r" % (_gv,),
              _gv["attributed"] is None and "O" in _gv["basis"]
              and "not knowable" in _gv["basis"])
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
        _harness.remove_tree(tmp)

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
    check("ev47 gate_cost_measured is the denominator a MEAN divides by - "
          "the count of steps that carried a durationMs, not `gate_tally`'s "
          "`ran` (which counts every matching step, measured or not): "
          "3 of the 4 rows above carry one: %r"
          % (M.gate_cost_measured(cost_rows, "lint"),),
          M.gate_cost_measured(cost_rows, "lint") == 3
          and M.gate_tally(cost_rows, "lint")[0] == 4)
    check("ev48 ...and a gate with no measured step at all reports 0, "
          "agreeing with gate_cost_ms's own None for the same rows - the "
          "two never disagree about which steps counted, because both "
          "read the one walk",
          M.gate_cost_measured([{"steps": [{"name": "lint", "exit": 0}]}],
                               "lint") == 0)

    _worktree_ledger_cases(check)
    _merge_ledger_cases(check)
    _chain_order_cases(check)
    _narrowed_shadow_cases(check)
    _selection_miss_row_cases(check)
    _resolve_named_cases(check)


def _resolve_named_cases(check):
    """(rn) `resolve_named`: the ONE candidate a runner's spelling names by
    `listed_by`'s suffix rule, or None and a sentence naming what matched.
    Read through `getattr` so the red before the function exists is an
    observed answer, not an AttributeError ending the suite."""
    resolve = getattr(M, "resolve_named", None)

    def ask(spelling, candidates):
        if resolve is None:
            return ("absent", None)
        return resolve(spelling, candidates)

    keys = ["pkg_a/tests/test_c.py", "pkg_b/tests/test_c.py",
            "tests/test_d.py"]
    one = ask("test_d.py", keys)
    check("rn1 RED-FIRST: a spelling that is a `/`-bounded suffix of exactly "
          "one candidate names that candidate, with no reason: %r" % (one,),
          one == ("tests/test_d.py", None))
    none = ask("test_z.py", keys)
    check("rn2 a spelling no candidate is listed by names none of them, and "
          "the reason says so and quotes the spelling: %r" % (none,),
          none[0] is None and isinstance(none[1], str)
          and "test_z.py" in none[1] and "no candidate" in none[1])
    several = ask("test_c.py", keys)
    check("rn3 RED-FIRST: a spelling that more than one candidate is listed "
          "by names NONE of them - an ambiguous name is not one of its "
          "matches - and the reason names every match: %r" % (several,),
          several[0] is None and isinstance(several[1], str)
          and "pkg_a/tests/test_c.py" in several[1]
          and "pkg_b/tests/test_c.py" in several[1]
          and "tests/test_d.py" not in several[1])
    # ALLOW CASE for the other direction of the suffix rule: a runner printing
    # a LONGER path than the candidate (its own absolute-ish spelling) still
    # names it, and a candidate listed twice is still one candidate.
    longer = ask("repo/pkg_b/tests/test_c.py", keys + ["pkg_b/tests/test_c.py"])
    check("rn4 ALLOW CASE: the suffix rule read either way round, and a "
          "repeated candidate counted once: %r" % (longer,),
          longer == ("pkg_b/tests/test_c.py", None))


def _selection_miss_row_cases(check):
    """(smr) `row_for`'s `selectionMiss`: `{test, phases, sources}` and no
    other key, the paths redacted, and absent when the post-pass found none."""
    tmp = _harness.fixture_root("audit-evidence-miss-")
    try:
        plain = _project(os.path.join(tmp, "plain"), {})
        base = {"status": "failed", "durationMs": 900, "failed": ["e2e"],
                "ranTotal": 4, "coverageBasis": None, "treeBasis": "b",
                "treeMutated": [], "overlap": None, "steps": []}
        ident = {"runId": "R-smr", "attempt": None, "via": "cli"}
        miss = {"test": os.path.join(plain, "e2e", "cart.spec.ts"),
                "phases": ["P2"], "sources": ["src/cart.ts"],
                "extra": "widened"}
        row = M.row_for(plain, dict(base, selectionMiss=[miss]), "full", {},
                        ident, published=[])
        check("smr1 `row_for` carries `selectionMiss` as exactly "
              "{test, phases, sources} - an inventive caller's extra key "
              "is dropped, and an absolute suite path is written "
              "repo-relative: %r" % (row.get("selectionMiss"),),
              row.get("selectionMiss") == [
                  {"test": "e2e/cart.spec.ts", "phases": ["P2"],
                   "sources": ["src/cart.ts"]}])
        over = M.MAX_PATHS + 3
        wide = {"test": "e2e/cart.spec.ts",
                "phases": ["P%d" % i for i in range(over)],
                "sources": ["src/f%d.ts" % i for i in range(over + 2)]}
        row_wide = M.row_for(plain, dict(base, selectionMiss=[wide] * (over + 1)),
                             "full", {}, ident, published=[])
        kept = row_wide.get("selectionMiss") or [{}]
        check("smr1b every list past MAX_PATHS is cut WITH its dropped count "
              "beside it - misses, each miss's phases and its sources - so a "
              "truncation announces itself: %r"
              % ((len(kept), row_wide.get("selectionMissDropped"),
                  kept[0].get("phasesDropped"), kept[0].get("sourcesDropped")),),
              len(kept) == M.MAX_PATHS
              and row_wide.get("selectionMissDropped") == 4
              and len(kept[0]["phases"]) == M.MAX_PATHS
              and kept[0].get("phasesDropped") == 3
              and len(kept[0]["sources"]) == M.MAX_PATHS
              and kept[0].get("sourcesDropped") == 5)
        check("smr1c ALLOW: a miss inside every bound carries no dropped "
              "count at all - absence means nothing was cut: %r"
              % (row.get("selectionMiss"),),
              "selectionMissDropped" not in row
              and not any(k.endswith("Dropped")
                          for k in (row.get("selectionMiss") or [{}])[0]))
        none = M.row_for(plain, dict(base, selectionMiss=[]), "full", {},
                         ident, published=[])
        check("smr2 ALLOW: a post-pass that found no miss writes no key - "
              "absence reads as none, and an empty list on every full row "
              "could not be told from a build that never asked",
              "selectionMiss" not in none)
    finally:
        _harness.remove_tree(tmp)


def _narrowed_shadow_cases(check):
    """(dgr) `row_for`'s two derived-gate fields - `narrowed`, two counts and
    no path, and `shadow`, which carries `missed`, a path list a runner's
    own output produced and so gets the same bound and redaction
    `treeMutated`/`overlap` already get.
    """
    tmp = _harness.fixture_root("audit-evidence-derived-")
    try:
        plain = _project(os.path.join(tmp, "plain"), {})
        base = {"status": "passed", "durationMs": 900, "failed": [],
                "ranTotal": 3, "coverageBasis": None, "treeBasis": "b",
                "treeMutated": [], "overlap": None, "steps": []}
        ident = {"runId": "R-dgr", "attempt": 1, "via": "cli"}
        with_both = dict(base, narrowed={"listed": 1, "full": 3},
                         shadow={"listed": 1, "full": 2,
                                 "missed": ["tests/test_x.py"]})
        row = M.row_for(plain, with_both, "phase", {"phaseId": "P1"}, ident,
                        published=[])
        check("dgr1 RED-FIRST: `row_for` carries `narrowed` and `shadow` "
              "when the run computed them - dropped before this task, an "
              "inventive caller's own two keys read back as absent: %r"
              % ((row.get("narrowed"), row.get("shadow")),),
              row.get("narrowed") == {"listed": 1, "full": 3}
              and row.get("shadow", {}).get("listed") == 1
              and row.get("shadow", {}).get("full") == 2
              and row.get("shadow", {}).get("missed")
              == ["tests/test_x.py"])

        no_derived = M.row_for(plain, base, "phase", {"phaseId": "P1"}, ident,
                               published=[])
        check("dgr2 ALLOW: a run that computed neither field carries "
              "neither key - absence is not a zero-length dict, and a "
              "writer that defaulted one in would tell every other reader "
              "this phase has a derived gate when it does not",
              "narrowed" not in no_derived and "shadow" not in no_derived)

        many_missed = ["tests/test_%d.py" % i
                       for i in range(M.MAX_PATHS + 5)]
        over = dict(base, shadow={"listed": 0, "full": len(many_missed),
                                  "missed": many_missed})
        row_over = M.row_for(plain, over, "phase", {"phaseId": "P1"}, ident,
                             published=[])
        check("dgr3 `shadow.missed` is cut at MAX_PATHS with a count beside "
              "it, the same bound `treeMutated` and `overlap` already carry "
              "- an unbounded runner-produced path list is exactly the "
              "unbounded row size this file's own rule refuses: %r"
              % ((len(row_over["shadow"]["missed"]),
                 row_over["shadow"].get("missedDropped")),),
              len(row_over["shadow"]["missed"]) == M.MAX_PATHS
              and row_over["shadow"]["missedDropped"] == 5)

        no_widen = dict(base, narrowed={"listed": 1, "full": 2, "extra": "x"})
        row_widen = M.row_for(plain, no_widen, "phase", {"phaseId": "P1"},
                              ident, published=[])
        check("dgr4 an inventive caller cannot widen `narrowed` past the "
              "two counts this file names, the same rule every other field "
              "on this row already keeps",
              "extra" not in row_widen["narrowed"])
    finally:
        _harness.remove_tree(tmp)


def _worktree_ledger_cases(check):
    """(ew) THE LEDGER'S WRITER IS THE SESSION AND THE WORKTREE, like the trail's.

    The evidence file was named by session alone, so a session appending runs in
    two linked worktrees wrote one basename in both branches, and merging them met
    a conflict `audit-journal merge` cannot resolve - it reads the journal
    directory only. Measured merging main into a phase branch."""
    import _invariants
    ok, pair = _harness.attempt(_harness.worktree_pair, "evidence-io-wt-")
    if not ok:
        check("ew0 the worktree fixture builds (%s)" % (pair,), False)
        return
    main, wt_a = pair["main"], pair["wt"]
    wt_b = os.path.join(pair["root"], "main-B")
    git = ["git", "-c", "user.email=t@t.t", "-c", "user.name=t",
           "-c", "commit.gpgsign=false"]

    def run_git(cwd, *argv):
        return subprocess.run(git + list(argv), cwd=cwd, capture_output=True,
                              text=True, timeout=30)
    run_git(main, "worktree", "add", "-q", wt_b, "-b", "chore/b")
    sid = "dddddddd-0000-4000-8000-00000000000d"

    def run(run_id, task):
        return {"v": 1, "runId": run_id, "ts": "2026-09-25T10:00:00Z",
                "scope": "task", "taskId": task, "phaseId": task.split(".")[0],
                "status": "passed", "steps": [], "failed": [],
                M.REUSE_KEY: "key-" + task}
    in_a = M.append_row(wt_a, run("run-a", "P48.1"), session_id=sid)
    in_b = M.append_row(wt_b, run("run-b", "P41.1"), session_id=sid)
    in_m = M.append_row(main, run("run-m", "P41.1"), session_id=sid)
    check("ew1 two linked worktrees driven by ONE session append their runs to "
          "two different ledger files",
          os.path.basename(in_a) != os.path.basename(in_b),
          repr((in_a, in_b)))
    check("ew2 ...and the main checkout keeps the session-keyed name",
          os.path.basename(in_m) == "2026-09.%s.jsonl"
          % _journal_io.writer_id({"sessionId": sid}), repr(in_m))
    ev_rel = os.path.relpath(M.evidence_dir(main), main).replace(os.sep, "/")
    for tree, msg in ((wt_a, "a"), (wt_b, "b"), (main, "m")):
        run_git(tree, "add", "-A", ev_rel)
        run_git(tree, "commit", "-qm", msg)
    merges = [run_git(main, "merge", "--no-edit", "-q", br)
              for br in ("chore/p48", "chore/b")]
    check("ew3 merging both worktree branches into main raises no evidence "
          "conflict", all(m.returncode == 0 for m in merges),
          repr([(m.returncode, m.stdout[-200:]) for m in merges]))
    read = M.read_rows(main)
    check("ew4 every name is read: read_rows walks all three files, and the "
          "merged ledger verifies",
          read["files"] == 3 and sorted(r["runId"] for r in read["rows"])
          == ["run-a", "run-b", "run-m"] and M.verify(main)["ok"],
          repr((read["files"], M.verify(main).get("findings"))))
    check("ew5 the reuse lookup finds a run recorded in a worktree-keyed file, "
          "by its task", (M.reusable_run(read["rows"], "task", {"taskId": "P48.1",
                          "phaseId": "P48"}, "key-P48.1", ("passed",))
                          or {}).get("runId") == "run-a")
    shared_cfg = dict(_journal_io.load_config(wt_a),
                      stateDir=os.path.join(pair["root"], "one-shared-state"))
    sa = M.append_row(wt_a, run("run-sa", "P48.1"), session_id="s" + sid[1:],
                      config=shared_cfg)
    sb = M.append_row(wt_b, run("run-sb", "P41.1"), session_id="s" + sid[1:],
                      config=dict(shared_cfg))
    check("ew7 two worktrees sharing ONE absolute stateDir still write two "
          "ledger files - the key lives in each worktree's own git dir",
          os.path.basename(sa) != os.path.basename(sb), repr((sa, sb)))
    committed, gaps = _invariants._committed_run_ids(main, ev_rel)
    check("ew6 ...and evidence-committed reads the committed worktree-keyed "
          "files as it reads the old one", not gaps
          and {"run-a", "run-b", "run-m"} <= set(committed),
          repr((sorted(committed), gaps)))



# --- em: a ledger file that diverged, merged by the journal's one merge ----------
def _em_run(run_id, ts, task, scope="task", phase="P1"):
    row = {"v": 1, "runId": run_id, "ts": ts, "scope": scope,
           "phaseId": phase, "status": "passed", "steps": [], "failed": []}
    if task is not None:
        row["taskId"] = task
    return row


def _em_merge(ours, theirs, name, aliases):
    """`merge_rows` under a plan's `aliases`. A build whose `merge_rows` takes
    none is called without them, so a case aimed at the reader's key fails on
    its ASSERTION there rather than raising and taking the rest down."""
    try:
        return M.merge_rows(ours, theirs, name, aliases=aliases)
    except TypeError:
        return M.merge_rows(ours, theirs, name)


def _em_pair(name, mine, yours):
    base = [_em_run("run-a", "2026-06-01T10:00:00Z", "P1.1")]
    return (M.chain_file(base + [mine], name),
            M.chain_file(base + [yours], name))


def _seamed(fn, *args, **kwargs):
    """`fn` told which merged stretches the ledger holds. A build whose readers
    take no `seams` is called without them, so a case aimed at the seam fails
    on its ASSERTION there rather than raising and taking the rest down."""
    try:
        return fn(*args, **kwargs)
    except TypeError:
        kwargs.pop("seams", None)
        return fn(*args, **kwargs)


def _ids(rows):
    return [o.get("runId") for o in rows or []]


def _gate(run_id, start, end):
    return {"runId": run_id, M.STARTED_KEY: "2026-09-26T10:00:%02dZ" % start,
            "ts": "2026-09-26T10:00:%02dZ" % end}


def _chain_order_cases(check):
    # A chain records the order rows were WRITTEN in. That is an order of runs
    # only when the later-written run began at or after the earlier one ended.
    _b, _a = _gate("B", 12, 12), _gate("A", 5, 12)
    _late = M.chain_file([_b, _a], "2026-09.writer.jsonl")
    check("co1 a run written AFTER a sub-second one but begun seven seconds "
          "before it ended is not called sequential by the chain - the pair "
          "is undecided, and nobody is named as sharing the window: "
          "undecided %r, shared %r"
          % (_ids(_seamed(M.undecided_neighbours, _late, _late[1],
                          M.RUNNER_GATE, seams=[])),
             _ids(_seamed(M.shared_the_machine, _late, _late[1],
                          seams=[])[0])),
          _ids(_seamed(M.undecided_neighbours, _late, _late[1], M.RUNNER_GATE,
                       seams=[])) == ["B"]
          and _seamed(M.shared_the_machine, _late, _late[1], seams=[])[0] == []
          and _seamed(M.chain_ordered, _late, _late[1], _late[0],
                      seams=[]) is False)
    _seq = M.chain_file([_gate("A", 5, 12), _gate("B", 12, 20)],
                        "2026-09.writer.jsonl")
    check("co2 SECOND DIRECTION: the same two seconds written in run order - "
          "the later run began in the second the earlier row was written - "
          "stay sequential: ordered %r, undecided %r"
          % (_seamed(M.chain_ordered, _seq, _seq[1], _seq[0], seams=[]),
             _ids(_seamed(M.undecided_neighbours, _seq, _seq[1],
                          M.RUNNER_GATE, seams=[]))),
          _seamed(M.chain_ordered, _seq, _seq[1], _seq[0], seams=[]) is True
          and _seamed(M.chain_ordered, _seq, _seq[0], _seq[1], seams=[]) is True
          and _seamed(M.undecided_neighbours, _seq, _seq[1], M.RUNNER_GATE,
                      seams=[]) == [])
    check("co3 ...and a reader not told whether the ledger was ever merged "
          "does not read order off its chain at all - the boundary second "
          "stays undecided: %r"
          % (_ids(_seamed(M.undecided_neighbours, _seq, _seq[1],
                          M.RUNNER_GATE, seams=None)),),
          _ids(_seamed(M.undecided_neighbours, _seq, _seq[1], M.RUNNER_GATE,
                       seams=None)) == ["A"]
          and M.chain_ordered(_seq, _seq[1], _seq[0]) is False)

    # Two branches appended to one file over a shared first row; the real
    # merge re-chains the union in timestamp order.
    name = "2026-09.s-co.jsonl"
    base = [_gate("R", 0, 1)]
    ours = M.chain_file(base + [_gate("X", 5, 12)], name)
    theirs = M.chain_file(base + [_gate("Y", 12, 20)], name)
    res = M.merge_rows(ours, theirs, name, aliases={})
    merged = res["rows"]
    seams = [(res.get("relinkedAfter"), res.get("relinkedThrough"))]
    check("co4 a ledger merge that re-chains a divergence says where the "
          "re-linked stretch begins and ends - after the last row both copies "
          "held, through the last row it re-chained: %r"
          % ([res.get("relinkedAfter"), res.get("relinkedThrough")],),
          res["ok"] and _ids(merged) == ["R", "X", "Y"]
          and res.get("relinkedAfter") == ours[0]["hash"]
          and res.get("relinkedThrough") == merged[-1]["hash"])
    check("co5 ...and two runs from two branches joined by that re-chain are "
          "not ordered by it - their shared boundary second is undecided, as "
          "it was before the merge: merged %r, unmerged %r"
          % (_ids(_seamed(M.undecided_neighbours, merged, merged[2],
                          M.RUNNER_GATE, seams=seams)),
             _ids(_seamed(M.undecided_neighbours, ours + theirs[1:], theirs[1],
                          M.RUNNER_GATE, seams=[]))),
          _ids(_seamed(M.undecided_neighbours, merged, merged[2], M.RUNNER_GATE,
                       seams=seams)) == ["X"]
          and _seamed(M.chain_ordered, merged, merged[2], merged[1],
                      seams=seams) is False
          and _ids(_seamed(M.undecided_neighbours, ours + theirs[1:],
                           theirs[1], M.RUNNER_GATE, seams=[])) == ["X"])
    tail = list(merged)
    for row in (_gate("P", 30, 40), _gate("Q", 40, 50)):
        tail.append(M.chain_onto(row, tail, name))
    check("co6 SECOND DIRECTION: runs the writer appended AFTER the merge are "
          "ordered by the chain again - the refusal covers the re-linked "
          "stretch, not the file: %r"
          % (_seamed(M.chain_ordered, tail, tail[4], tail[3], seams=seams),),
          _seamed(M.chain_ordered, tail, tail[4], tail[3], seams=seams) is True
          and _seamed(M.undecided_neighbours, tail, tail[4], M.RUNNER_GATE,
                      seams=seams) == []
          and _seamed(M.chain_ordered, tail, tail[3], tail[2],
                      seams=seams) is False)
    grown = M.chain_file(base + [_gate("X", 5, 12), _gate("Y", 12, 20)], name)
    flat = M.merge_rows(grown[:2], grown, name, aliases={})
    check("co7 SECOND DIRECTION: a merge with nothing to re-chain - one copy a "
          "prefix of the other - records no stretch, and the chain orders "
          "the file's runs as before: %r / %r"
          % ([flat.get("relinkedAfter"), flat.get("relinkedThrough")],
             _seamed(M.chain_ordered, flat["rows"], flat["rows"][2],
                     flat["rows"][1], seams=[]),),
          flat["ok"] and flat.get("relinkedAfter") is None
          and flat.get("relinkedThrough") is None
          and _seamed(M.chain_ordered, flat["rows"], flat["rows"][2],
                      flat["rows"][1], seams=[]) is True)

    # A second merge over a file an earlier merge re-chained: main appended Z
    # after merge one, and a second branch forked at the original prefix.
    main1 = M.chain_file(base + [_gate("Y", 12, 20)], name)
    b1 = M.chain_file(base + [_gate("X", 5, 12)], name)
    b2 = M.chain_file(base + [_gate("W", 30, 40)], name)
    m1 = M.merge_rows(main1, b1, name, aliases={})
    s1 = (m1.get("relinkedAfter"), m1.get("relinkedThrough"))
    main2 = list(m1["rows"])
    main2.append(M.chain_onto(_gate("Z", 20, 30), main2, name))
    m2 = M.merge_rows(main2, b2, name, aliases={})
    twice = m2["rows"]
    s2 = (m2.get("relinkedAfter"), m2.get("relinkedThrough"))
    by = dict((r.get("runId"), r) for r in twice)
    answers = [(_ids(_seamed(M.undecided_neighbours, twice, by.get("W", {}),
                             M.RUNNER_GATE, seams=order)),
                _seamed(M.chain_ordered, twice, by.get("W", {}), by.get("Z", {}),
                        seams=order))
               for order in ([s1, s2], [s2, s1])]
    check("co11 after TWO successive real merges, a run the second merge "
          "re-chained is undecided against the run it meets - in either order "
          "the journal lists the two stretches, so an earlier stretch cannot "
          "cut a later one short: %r over %r" % (answers, _ids(twice)),
          m2["ok"] and _ids(twice) == ["R", "X", "Y", "Z", "W"]
          and answers == [(["Z"], False), (["Z"], False)])
    _one = M.chain_index(twice, [s1])["relinked"] or set()
    _covered = sorted(r.get("runId") for r in twice if r.get("hash") in _one)
    check("co12 SECOND DIRECTION: one merge's stretch alone still covers only "
          "its own rows - X and Y, not R before it nor Z and W appended after "
          "it: %r" % (_covered,), _covered == ["X", "Y"])

    # Where no merge could be recorded, or none could be read, nobody can say
    # whether one happened - which is not "no merge happened".
    root = _harness.fixture_root("audit-evidence-seams-")
    try:
        off = _project(os.path.join(root, "off"), {"journal": {"enabled": False}})
        got = M.merge_seams(off)
        check("co13 a DISABLED journal could have recorded no ledger merge, so "
              "the answer is None with that reason, never the claim that none "
              "happened: %r" % (got,),
              got[0] is None and "disabled" in got[1])
        on = _project(os.path.join(root, "on"), {})
        real = _journal_io.read_all

        def broken(*args, **kwargs):
            raise IOError("JOURNAL-UNREADABLE")
        _journal_io.read_all = broken
        try:
            got = M.merge_seams(on)
        finally:
            _journal_io.read_all = real
        check("co14 a journal read that raises answers None, carrying the "
              "exception's text: %r" % (got,),
              got[0] is None and "JOURNAL-UNREADABLE" in got[1])
        got = M.merge_seams(on)
        check("co15 SECOND DIRECTION: a readable journal recording no merge "
              "answers [] with no reason: %r" % (got,), got == ([], ""))
    finally:
        _harness.remove_tree(root)

    # The chain is read only for a pair the windows leave undecided.
    big = M.chain_file(
        [{"runId": "r%d" % i,
          M.STARTED_KEY: "2026-09-26T%02d:%02d:%02dZ"
          % (i // 3600 % 24, i // 60 % 60, i % 60),
          "ts": "2026-09-26T%02d:%02d:%02dZ"
          % (i // 3600 % 24, i // 60 % 60, i % 60)}
         for i in range(0, 6000, 2)], "2026-09.big.jsonl")
    real, calls = M.chain_ordered, []

    def counted(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)
    M.chain_ordered = counted
    try:
        _seamed(M.undecided_neighbours, big, big[-1], M.RUNNER_GATE, seams=[])
        _seamed(M.shared_the_machine, big, big[-1], seams=[])
        quiet = len(calls)
        _seamed(M.undecided_neighbours, _seq, _seq[1], M.RUNNER_GATE, seams=[])
        meeting = len(calls) - quiet
    finally:
        M.chain_ordered = real
    check("co8 over a ledger of %d chained runs in which no two windows meet, "
          "the chain is never consulted - the windows decide every pair: %d "
          "call(s)" % (len(big), quiet), quiet == 0)
    check("co9 SECOND DIRECTION: a pair meeting in one second IS put to the "
          "chain - the count above is a count, not a wrapper nothing calls: "
          "%d call(s)" % (meeting,), meeting == 1)
    crowd = M.chain_file([_gate("S%d" % i, 12, 12) for i in range(5)]
                         + [_gate("L", 5, 12)], "2026-09.writer.jsonl")
    real, built = M.chain_index, []

    def counted_index(*args, **kwargs):
        built.append(1)
        return real(*args, **kwargs)
    M.chain_index = counted_index
    try:
        _asked = _ids(_seamed(M.undecided_neighbours, crowd, crowd[-1],
                              M.RUNNER_GATE, seams=[]))
    finally:
        M.chain_index = real
    check("co10 ...and a run meeting several others in one second builds the "
          "chain's lookups ONCE for the pass, not once per pair: %d build(s) "
          "for %r" % (len(built), _asked),
          len(built) == 1 and len(_asked) == 5)


def _merge_ledger_cases(check):
    name = "2026-06.s-em.jsonl"
    stamp = "2026-06-02T10:00:00Z"

    # THE READER'S KEY, FIRST. A `--task` run measured under its phase's gate is
    # recorded `scope: phase` with a task id, and `latest_by_subject` files it
    # under the phase - the key a phase sign-off run is filed under too.
    ours, theirs = _em_pair(name, _em_run("run-task", stamp, "P1.2",
                                          scope="phase"),
                            _em_run("run-signoff", stamp, None, scope="phase"))
    res = _em_merge(ours, theirs, name, {})
    check("em7 a --task run measured under the phase gate and a phase sign-off "
          "run of that phase in ONE second are REFUSED, not ordered - "
          "`latest_by_subject` files both under the phase, so their order is "
          "which one becomes the phase's pointer: %r"
          % (res["refusals"] or res.get("ordered"),),
          not res["ok"] and not res["rows"] and len(res["refusals"]) == 1)

    ours, theirs = _em_pair(name, _em_run("run-old", stamp, "P1.9"),
                            _em_run("run-new", stamp, "P1.2"))
    moved = {("task", "P1.9"): ("task", "P1.2")}
    res = _em_merge(ours, theirs, name, moved)
    apart = _em_merge(ours, theirs, name, {})
    check("em8 ...and so are runs under a moved task's OLD id and its NEW one: "
          "the plan's aliases make them one subject to every reader. The pair: "
          "under a plan that moved nothing the same two runs ARE disjoint and "
          "are ordered: %r / %r" % (res["refusals"], apart.get("ordered")),
          not res["ok"] and len(res["refusals"]) == 1
          and apart["ok"] and len(apart["ordered"]) == 1)

    ours, theirs = _em_pair(name, _em_run("run-o", stamp, "P1.1"),
                            _em_run("run-t", stamp, "P1.2"))
    res = _em_merge(ours, theirs, name, {})
    swapped = _em_merge(theirs, ours, name, {})
    check("em9 two task runs of DIFFERENT tasks in one second are ordered, the "
          "order is written for the record of the merge, and the ledger - which "
          "takes no marker row - comes out BYTE FOR BYTE the same whichever "
          "side is ours: %r" % (res["ordered"],),
          res["ok"] and len(res["rows"]) == 3
          and all(r.get("runId") for r in res["rows"])
          and not M.verify_rows(res["rows"], name)["findings"]
          and _journal_io.merge_text(res["rows"])
          == _journal_io.merge_text(swapped["rows"])
          and stamp in res["summary"] and len(res["ordered"]) == 1)

    blind = M.merge_rows(ours, theirs, name)
    check("em10 ...and with the plan NOT read (no aliases at all) which ids were "
          "moved is unknown, so the same tie is refused rather than ordered: %r"
          % (blind["refusals"],),
          not blind["ok"] and len(blind["refusals"]) == 1)

    x = _em_run("run-x", stamp, "P1.3")
    y = _em_run("run-y", stamp, "P1.3")
    one = M.chain_file([_em_run("run-a", "2026-06-01T10:00:00Z", "P1.1"),
                        x, y], name)
    two = M.chain_file([_em_run("run-a", "2026-06-01T10:00:00Z", "P1.1"),
                        y, x], name)
    res = _em_merge(one, two, name, {})
    swapped = _em_merge(two, one, name, {})
    check("em11 an IDENTICAL tie held in two chain orders is ordered by content "
          "too, so both resolutions of a ledger file are one file: %r"
          % ([r.get("runId") for r in res["rows"]],),
          res["ok"] and swapped["ok"]
          and _journal_io.merge_text(res["rows"])
          == _journal_io.merge_text(swapped["rows"]))

    row = _em_run("run-t", stamp, "P1.2", scope="phase")
    check("em12 a run's targets are the readers' keys - `subject_key`, which "
          "`latest_by_subject` files a pointer under, and the `_same_subject` "
          "pair, a moved id mapped in both - and nothing when the plan is "
          "unread: %r" % (M.merge_targets(row, {}),),
          M.merge_targets(row, {}) == ("key phase P1",
                                       "pair task=P1.2 phase=P1")
          and M.merge_targets(_em_run("r", stamp, "P1.9"), moved)
          == ("key task P1.2", "pair task=P1.2 phase=P1")
          and M.merge_targets(row, None) == ()
          and M.subject_key(row) == ("phase", "P1")
          and M.latest_by_subject([dict(row, ts=stamp)])
          == {("phase", "P1"): dict(row, ts=stamp)})

    # THE TIE ONLY THE VERDICT PAIR PROTECTS: a task-scope run and a phase-scope
    # run carrying the same task id are filed under different `subject_key`s, and
    # a task commit's verdict (`_same_subject`) reads both as that task's.
    ours, theirs = _em_pair(name, _em_run("run-task", stamp, "P1.2"),
                            _em_run("run-under-phase", stamp, "P1.2",
                                    scope="phase"))
    res = _em_merge(ours, theirs, name, {})
    check("em13 a scope:task run and a scope:phase run carrying the SAME task id "
          "in one second are refused: their keys differ, but the verdict a task "
          "commit is bound to reads both as that task's, so their order is "
          "which one is newest: %r" % (res["refusals"] or res.get("ordered"),),
          not res["ok"] and len(res["refusals"]) == 1)

    tmp = _harness.fixture_root("audit-evidence-plan-")
    try:
        proj = _project(os.path.join(tmp, "sharded"),
                        {"manifestPath": "docs/audit/audit-plan.json"})
        audit = os.path.join(proj, "docs", "audit")
        os.makedirs(os.path.join(audit, "phases"))
        with open(os.path.join(audit, "audit-plan.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"meta": {}, "phases": [
                {"id": "P1", "shard": "phases/P1.json"},
                {"id": "P2", "shard": "phases/P2.json"}]}, fh)
        with open(os.path.join(audit, "phases", "P1.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"id": "P1", "tasks": []}, fh)
        with open(os.path.join(audit, "phases", "P2.json"), "w",
                  encoding="utf-8") as fh:
            fh.write("<<<<<<< ours\n{}\n=======\n{}\n>>>>>>> theirs\n")
        aliases, why = M.plan_aliases(proj)
        check("em14 a plan whose SHARD will not parse is named by that shard, "
              "not by the index that parses - the operator is sent to the file "
              "that failed: %r" % (why,),
              aliases is None and "docs/audit/phases/P2.json" in why
              and "docs/audit/audit-plan.json" not in why)
    finally:
        _harness.remove_tree(tmp)

    _full_status_cases(check)


# --- full_status: whole, provisional, unknown, or not declared -----------------
def _fake_git(table):
    """A fake git for `full_status`'s injected `run` - one answer for
    `merge-base --is-ancestor`, so a case can drive the UNKNOWN branch a real
    repository cannot be made to answer with (a ref that will never resolve)."""
    def run(git_root, args, timeout=None):
        return table.get(" ".join(args[:2]), (0, "", ""))
    return run


def _real_two_commits(root):
    """A REAL git repository at `root`, two sequential commits on `main`.

    `{"first", "second"}` are the two commits' own shas - `first` an actual
    ancestor of `second`, never a string this fixture invents. This is what an
    ancestry claim needs and a fake `run` cannot give it: a case that mutated
    `full_status` to compare `head == mergedHead` would still pass against two
    equal strings, and only two REAL, DIFFERENT, ancestor-related commits
    catch that.
    """
    os.makedirs(root, exist_ok=True)
    git = ["git", "-c", "user.email=t@t.t", "-c", "user.name=t",
          "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"]

    def sh(*args):
        subprocess.run(git + list(args), cwd=root, check=True,
                       capture_output=True, timeout=30)

    def rev():
        out = subprocess.run(git + ["rev-parse", "HEAD"], cwd=root, check=True,
                             capture_output=True, timeout=30)
        return out.stdout.decode("utf-8").strip()

    sh("init", "-q")
    with open(os.path.join(root, "a.txt"), "w", encoding="utf-8") as fh:
        fh.write("1\n")
    sh("add", "-A")
    sh("commit", "-qm", "one")
    first = rev()
    with open(os.path.join(root, "a.txt"), "w", encoding="utf-8") as fh:
        fh.write("2\n")
    sh("add", "-A")
    sh("commit", "-qm", "two")
    second = rev()
    return {"root": root, "first": first, "second": second}


def _fs_row(run_id, ts, head, commands, ran_total=3, dirty_outside=(),
           status="passed", scope=None, extra=None):
    """One well-formed scope-`full` row: every command carried VERBATIM (as
    `row_for`/`_step` store it when the command is in the published set), every
    step timed, a positive count with a basis, and a clean `dirtyOutside`.

    `scope` DEFAULTS TO None RATHER THAN `M.FULL_SCOPE` DIRECTLY, on purpose:
    a default argument is evaluated once, at import time, and reaching into
    the module under test THEN would make a red-first proof against a
    checkout that does not carry `full_status` yet fail on the wrong missing
    name (`FULL_SCOPE`) instead of on the one this task actually introduces.
    """
    scope = scope if scope is not None else M.FULL_SCOPE
    row = {
        "v": M.ROW_VERSION, "runId": run_id, "ts": ts, "scope": scope,
        "status": status,
        "steps": [{"name": "gate", "command": c, "exit": 0, "durationMs": 1000}
                 for c in commands],
        "testedState": {"head": head},
        "observations": {"ranTotal": ran_total, "countsBasis": "3 checks",
                         "dirtyOutside": list(dirty_outside)},
    }
    if extra:
        row.update(extra)
    return row


def _full_status_cases(check):
    tmp = _harness.fixture_root("audit-evidence-full-")
    try:
        # --- the two questions that need no ledger at all ----------------------
        check("fs1 no meta.fullGate at all is NOT_DECLARED, whatever the ledger "
              "or the phase carry - a plan naming no third place has nothing to "
              "ask",
              M.full_status([], {"mergedHead": "abc"}, tmp, [])["answer"]
              == _manifest_vocab.FULL_STATUS_NOT_DECLARED)

        check("fs2 a declared fullGate but no phase.mergedHead is UNKNOWN, never "
              "PROVISIONAL - PROVISIONAL would claim a specific gap this plan "
              "cannot measure at all",
              M.full_status([], {"id": "P9"}, tmp, ["echo x"])["answer"]
              == _manifest_vocab.FULL_STATUS_UNKNOWN)

        # --- RED-FIRST: ancestry, never a string comparison ---------------------
        repo = _real_two_commits(os.path.join(tmp, "repo"))
        phase = {"id": "P1", "mergedHead": repo["first"]}
        whole_row = _fs_row("run-whole", "2026-01-02T00:00:00Z", repo["second"],
                            ["echo x"])
        res = M.full_status([whole_row], phase, repo["root"], ["echo x"])
        check("fs3 RED-FIRST: a full run's head that CONTAINS mergedHead "
              "without EQUALLING it reads WHOLE - real commits, so a "
              "`head == mergedHead` mutation fails on this and only ancestry "
              "passes it: %r" % (res,),
              res["answer"] == _manifest_vocab.FULL_STATUS_WHOLE
              and res["runId"] == "run-whole")

        # ALLOW: the SAME head, trivially its own ancestor, still reads WHOLE -
        # the mutation this pairs with is the opposite one (an ancestry check
        # that forgot a run can equal its own subject is not a real risk here,
        # but the case is what tells "ancestor of" apart from "strictly older
        # than").
        same_head_row = _fs_row("run-same", "2026-01-02T00:00:00Z", repo["first"],
                                ["echo x"])
        res_same = M.full_status([same_head_row], phase, repo["root"], ["echo x"])
        check("fs4 ALLOW: a full run measured AT mergedHead itself is also "
              "WHOLE - a commit is its own ancestor: %r" % (res_same,),
              res_same["answer"] == _manifest_vocab.FULL_STATUS_WHOLE)

        # A head that does NOT contain mergedHead (an unrelated commit) never
        # reads WHOLE - PROVISIONAL, naming the run that does not contain it.
        unrelated_row = _fs_row("run-unrelated", "2026-01-02T00:00:00Z",
                                "0" * 40, ["echo x"])
        res_un = M.full_status([unrelated_row], phase, repo["root"], ["echo x"],
                               run=_fake_git(
                                   {"merge-base --is-ancestor": (1, "", "")}))
        check("fs5 a whole-bearing run whose head does not contain mergedHead "
              "is PROVISIONAL, naming that run: %r" % (res_un,),
              res_un["answer"] == _manifest_vocab.FULL_STATUS_PROVISIONAL
              and "run-unrelated" in res_un["basis"])

        # --- RED-FIRST: a dirty tree certifies nothing --------------------------
        dirty_row = _fs_row("run-dirty", "2026-01-02T00:00:00Z", repo["second"],
                            ["echo x"], dirty_outside=["src/app.ts"])
        res_dirty = M.full_status([dirty_row], phase, repo["root"], ["echo x"])
        check("fs6 RED-FIRST: a full run on a dirty tree never reads WHOLE, "
              "even when its head really does contain mergedHead: %r"
              % (res_dirty,),
              res_dirty["answer"] == _manifest_vocab.FULL_STATUS_PROVISIONAL
              and "DIRTY TREE" in res_dirty["basis"])

        # A row that predates the dirtyOutside field is disqualified the same
        # way - "unknown whether it was clean" is not "known clean".
        no_dirty_key = _fs_row("run-nokey", "2026-01-02T00:00:00Z",
                               repo["second"], ["echo x"])
        del no_dirty_key["observations"]["dirtyOutside"]
        res_nokey = M.full_status([no_dirty_key], phase, repo["root"], ["echo x"])
        check("fs7 a row that never recorded dirtyOutside cannot be told clean, "
              "so it is disqualified too: %r" % (res_nokey,),
              res_nokey["answer"] == _manifest_vocab.FULL_STATUS_PROVISIONAL)

        # --- RED-FIRST: a hand-typed row that counted nothing -------------------
        no_count_row = {"v": M.ROW_VERSION, "runId": "run-empty",
                        "ts": "2026-01-02T00:00:00Z", "scope": M.FULL_SCOPE,
                        "status": "passed", "steps": [],
                        "testedState": {"head": repo["second"]}}
        res_empty = M.full_status([no_count_row], phase, repo["root"], ["echo x"])
        check("fs8 RED-FIRST: a hand-typed row with status passed and no steps "
              "is refused as whole-bearing rather than read as WHOLE: %r"
              % (res_empty,),
              res_empty["answer"] == _manifest_vocab.FULL_STATUS_PROVISIONAL
              and "counted nothing" in res_empty["basis"])

        # --- RED-FIRST: subset and reordering never satisfy fullGate ------------
        subset_row = _fs_row("run-subset", "2026-01-02T00:00:00Z", repo["second"],
                             ["echo a", "echo b"])
        res_subset = M.full_status([subset_row], phase, repo["root"],
                                   ["echo a", "echo b", "echo c"])
        check("fs9 RED-FIRST: a row whose commands are a STRICT SUBSET of "
              "fullGate is disqualified by more than a length compare would "
              "catch on its own, and the message names the count: %r"
              % (res_subset,),
              res_subset["answer"] == _manifest_vocab.FULL_STATUS_PROVISIONAL
              and "2 OF 3" in res_subset["basis"])

        reorder_row = _fs_row("run-reorder", "2026-01-02T00:00:00Z",
                              repo["second"], ["echo b", "echo a"])
        res_reorder = M.full_status([reorder_row], phase, repo["root"],
                                    ["echo a", "echo b"])
        check("fs10 RED-FIRST: a row whose commands are a REORDERING of "
              "fullGate (same length) is refused too - a length-only compare "
              "would let this one through: %r" % (res_reorder,),
              res_reorder["answer"] == _manifest_vocab.FULL_STATUS_PROVISIONAL
              and "verbatim" in res_reorder["basis"])

        # --- RED-FIRST: the ledger is the only source ---------------------------
        phase_with_stale_cache = {"id": "P1", "mergedHead": repo["first"],
                                  "fullEvidence": {"status": "whole",
                                                    "runId": "some-old-run"}}
        res_cache = M.full_status([unrelated_row], phase_with_stale_cache,
                                  repo["root"], ["echo x"],
                                  run=_fake_git(
                                      {"merge-base --is-ancestor": (1, "", "")}))
        check("fs11 RED-FIRST: a stale phase.fullEvidence claiming whole is "
              "never consulted - the answer comes from the ledger alone: %r"
              % (res_cache,),
              res_cache["answer"] == _manifest_vocab.FULL_STATUS_PROVISIONAL)

        # --- RED-FIRST: git's own could-not-ask is UNKNOWN, never folded in -----
        res_128 = M.full_status(
            [whole_row], phase, repo["root"], ["echo x"],
            run=_fake_git({"merge-base --is-ancestor":
                          (128, "", "fatal: bad object\n")}))
        check("fs12 RED-FIRST: git answering 128 (could not be asked) is "
              "UNKNOWN, never folded into PROVISIONAL - a could-not-ask is not "
              "the same claim as a definite 'does not contain': %r" % (res_128,),
              res_128["answer"] == _manifest_vocab.FULL_STATUS_UNKNOWN)

        # The walk does not stop at the first whole-bearing row it tries: two
        # rows both measured at a head that contains mergedHead, newest first,
        # and the newest one still answers CONTAINED rather than the loop
        # somehow needing a second pass over an older one.
        older_whole = _fs_row("run-older-whole", "2026-01-01T00:00:00Z",
                              repo["second"], ["echo x"])
        res_two = M.full_status([older_whole, whole_row], phase, repo["root"],
                                ["echo x"])
        check("fs13 two whole-bearing rows, both containing mergedHead: the "
              "newest one answers and names itself, not the older one: %r"
              % (res_two,),
              res_two["answer"] == _manifest_vocab.FULL_STATUS_WHOLE
              and res_two["runId"] == "run-whole")

        # Two whole-bearing rows naming the SAME moment: the tie goes to the
        # row read later, the rule every other "newest" reader here follows.
        tie_first = _fs_row("run-tie-first", "2026-01-02T00:00:00Z",
                            repo["second"], ["echo x"])
        tie_later = _fs_row("run-tie-later", "2026-01-02T00:00:00+00:00",
                            repo["second"], ["echo x"])
        tie_whole = M.newest_whole_bearing([tie_first, tie_later], ["echo x"])
        check("fs13b RED-FIRST: a dated tie between whole-bearing full rows "
              "goes to the row read LATER, as `newest_row` breaks it - one "
              "question, one order: %r" % ((tie_whole or {}).get("runId"),),
              (tie_whole or {}).get("runId") == "run-tie-later"
              and M.newest_row([tie_first, tie_later])["runId"]
              == "run-tie-later")

        # --- ALLOW: no full row at all is PROVISIONAL, not UNKNOWN -------------
        res_none = M.full_status([], phase, repo["root"], ["echo x"])
        check("fs14 ALLOW: a plan with mergedHead and fullGate but no full run "
              "ever recorded is PROVISIONAL, not UNKNOWN or WHOLE: %r"
              % (res_none,),
              res_none["answer"] == _manifest_vocab.FULL_STATUS_PROVISIONAL)

        # --- the newest WHOLE-BEARING run, named beside the answer ------------
        # The fixture separates "the run full_status's answer names" from "the
        # newest run that could bear whole": the newest row is disqualified (a
        # dirty tree, status still passed), so a reading that took the moment
        # off `runId` in the disqualified-only ledger, or off the newest row
        # of any kind, answers the dirty run and goes red here.
        newest_dirty = _fs_row("run-dirty-newest", "2026-01-03T00:00:00Z",
                               repo["second"], ["echo x"],
                               dirty_outside=["src/app.ts"])
        older_bearing = _fs_row("run-bearing", "2026-01-01T00:00:00Z",
                                "0" * 40, ["echo x"])
        not_contained = _fake_git({"merge-base --is-ancestor": (1, "", "")})
        res_wb = M.full_status([older_bearing, newest_dirty], phase,
                               repo["root"], ["echo x"], run=not_contained)
        check("fs19 RED-FIRST: full_status names the newest WHOLE-BEARING run "
              "and its moment beside its answer, passing over a newer run on "
              "a dirty tree: %r" % (res_wb,),
              res_wb.get("wholeRunId") == "run-bearing"
              and res_wb.get("wholeRunTs") == "2026-01-01T00:00:00Z"
              and res_wb["answer"] == _manifest_vocab.FULL_STATUS_PROVISIONAL)

        res_dq = M.full_status([newest_dirty], phase, repo["root"], ["echo x"])
        check("fs20 RED-FIRST: a ledger holding only a disqualified passed run "
              "names NO whole-bearing run and no moment, while `runId` still "
              "names the disqualified run its basis is about: %r" % (res_dq,),
              "wholeRunId" in res_dq and res_dq["wholeRunId"] is None
              and "wholeRunTs" in res_dq and res_dq["wholeRunTs"] is None
              and res_dq["runId"] == "run-dirty-newest")

        # An UNDATED disqualified row read FIRST: undated rows are walked
        # after every dated one, so the run the basis is about is the dated
        # disqualified run, not whichever the ledger listed first.
        undated_dirty = _fs_row("run-dirty-undated", "not-a-moment",
                                repo["second"], ["echo x"],
                                dirty_outside=["src/app.ts"])
        res_ud = M.full_status([undated_dirty, newest_dirty], phase,
                               repo["root"], ["echo x"])
        check("fs20b RED-FIRST: an undated disqualified row read before a "
              "dated one is walked AFTER it - the basis names the dated run: "
              "%r" % (res_ud,),
              res_ud["runId"] == "run-dirty-newest"
              and "run-dirty-newest" in res_ud["basis"]
              and "run-dirty-undated" not in res_ud["basis"])

        res_wh = M.full_status([whole_row], phase, repo["root"], ["echo x"])
        check("fs21 ALLOW: a WHOLE answer names its run as the newest "
              "whole-bearing one too, with that run's own moment: %r"
              % (res_wh,),
              res_wh.get("wholeRunId") == "run-whole"
              and res_wh.get("wholeRunTs") == "2026-01-02T00:00:00Z")

        # --- which phases are merged: one predicate every surface calls -------
        cases = [
            ({"id": "P1", "mergedAt": "2026-01-01T00:00:00Z"}, True),
            ({"id": "P1", "mergedAt": "2026-01-01T00:00:00Z",
              "status": "in_progress"}, True),
            ({"mergedAt": "2026-01-01T00:00:00Z", "status": "done"}, False),
            ({"id": None, "mergedAt": "2026-01-01T00:00:00Z"}, False),
            ({"id": "P1", "status": "done"}, False),
            ({"id": "P1", "mergedAt": ""}, False),
            ("P1", False),
            (None, False),
        ]
        wrong = [(p, want) for p, want in cases
                 if M.merged_phase(p) is not want]
        check("mp1 RED-FIRST: a phase is merged exactly when it carries "
              "mergedAt and an id - a stored status of done without mergedAt "
              "is not merged, an in_progress one with mergedAt is, and an "
              "id-less one never is: %r" % (wrong,),
              not wrong)

        # --- "newest" is the newest MOMENT, never the greatest string -------
        # Each pair below is ordered one way as text and the other way as
        # time, so an ordering by the stamp's spelling picks the wrong run.
        offset_later = _fs_row("run-offset", "2026-01-02T01:00:00+02:00",
                               "0" * 40, ["echo x"])
        utc_newer = _fs_row("run-utc", "2026-01-01T23:30:00Z", "0" * 40,
                            ["echo x"])
        res_off = M.full_status([offset_later, utc_newer], phase, repo["root"],
                                ["echo x"], run=not_contained)
        check("fs22 RED-FIRST: a stamp with an offset is ordered by the moment "
              "it names - the UTC run half an hour later is the newest, though "
              "its text sorts first the other way: %r" % (res_off,),
              res_off.get("wholeRunId") == "run-utc"
              and res_off["runId"] == "run-utc")

        frac_newer = _fs_row("run-frac", "2026-01-01T10:00:00.500Z", "0" * 40,
                             ["echo x"])
        whole_second = _fs_row("run-whole-second", "2026-01-01T10:00:00Z",
                               "0" * 40, ["echo x"])
        res_frac = M.full_status([whole_second, frac_newer], phase,
                                 repo["root"], ["echo x"], run=not_contained)
        check("fs23 RED-FIRST: a fractional second is later than the whole "
              "second it extends, though a text sort puts it first: %r"
              % (res_frac,),
              res_frac.get("wholeRunId") == "run-frac"
              and res_frac.get("wholeRunTs") == "2026-01-01T10:00:00.500Z")

        undated = _fs_row("run-undated", "not-a-moment", "0" * 40, ["echo x"])
        dated = _fs_row("run-dated", "2026-01-01T00:00:00Z", "0" * 40,
                        ["echo x"])
        res_und = M.full_status([dated, undated], phase, repo["root"],
                                ["echo x"], run=not_contained)
        check("fs24 RED-FIRST: a run whose ts will not parse is never the "
              "newest whole-bearing run, though its text sorts above every "
              "real stamp: %r" % (res_und,),
              res_und.get("wholeRunId") == "run-dated"
              and res_und["runId"] == "run-dated")

        res_only = M.full_status([undated], phase, repo["root"], ["echo x"],
                                 run=not_contained)
        check("fs25 a ledger whose only whole-bearing run has no readable ts "
              "names no whole-bearing moment, yet the answer still names that "
              "run rather than claiming none was recorded: %r" % (res_only,),
              res_only["answer"] == _manifest_vocab.FULL_STATUS_PROVISIONAL
              and res_only["runId"] == "run-undated"
              and res_only.get("wholeRunId") is None
              and res_only.get("wholeRunTs") is None
              and "never been recorded" not in res_only["basis"])

        contains = _fake_git({"merge-base --is-ancestor": (0, "", "")})
        res_und_whole = M.full_status([undated], phase, repo["root"],
                                      ["echo x"], run=contains)
        check("fs26 ALLOW: a run with no readable ts still answers the "
              "ancestry question it measured - an unreadable moment says "
              "nothing about the head it ran on: %r" % (res_und_whole,),
              res_und_whole["answer"] == _manifest_vocab.FULL_STATUS_WHOLE
              and res_und_whole["runId"] == "run-undated")

        # --- a run that names no tested head cannot bear whole ----------------
        # Real git, no injected `run`: asking ancestry of an absent head is
        # what git itself answers UNKNOWN to, so only a disqualification lets
        # the walk reach the older run that does name a head.
        headless_newer = _fs_row("run-headless", "2026-01-05T00:00:00Z", None,
                                 ["echo x"])
        headed_older = _fs_row("run-headed", "2026-01-01T00:00:00Z",
                               repo["second"], ["echo x"])
        res_hl = M.full_status([headed_older, headless_newer], phase,
                               repo["root"], ["echo x"])
        check("fs27 RED-FIRST: the newest whole-bearing run named beside the "
              "answer is never a head-less one - wholeRunId names the older "
              "headed run - while the WHOLE answer from that older run is "
              "unchanged: %r" % (res_hl,),
              res_hl["answer"] == _manifest_vocab.FULL_STATUS_WHOLE
              and res_hl["runId"] == "run-headed"
              and "run-headed" in res_hl["basis"]
              and res_hl.get("wholeRunId") == "run-headed")

        # The shape that really read could-not-ask: the older headed run does
        # NOT contain mergedHead, so the walk used to stop at the newer
        # head-less row and ask git about an absent head.
        headed_not = _fs_row("run-headed-not", "2026-01-01T00:00:00Z",
                             repo["first"], ["echo x"])
        later_phase = {"id": "P1", "mergedHead": repo["second"]}
        res_hn = M.full_status([headed_not, headless_newer], later_phase,
                               repo["root"], ["echo x"])
        check("fs27b RED-FIRST: an older headed run that does not contain "
              "mergedHead beside a newer head-less run reads PROVISIONAL "
              "about the older run, never a could-not-ask about the "
              "head-less one: %r" % (res_hn,),
              res_hn["answer"] == _manifest_vocab.FULL_STATUS_PROVISIONAL
              and res_hn["runId"] == "run-headed-not"
              and "could not" not in res_hn["basis"])

        no_state = _fs_row("run-nostate", "2026-01-05T00:00:00Z", None,
                           ["echo x"])
        del no_state["testedState"]
        blank_head = _fs_row("run-blank", "2026-01-05T00:00:00Z", "  ",
                             ["echo x"])
        reasons = [M._full_disqualification(r, ["echo x"])
                   for r in (headless_newer, no_state, blank_head)]
        check("fs28 RED-FIRST: a null head, a missing testedState and a blank "
              "head are each disqualified by a reason naming the missing "
              "tested head: %r" % (reasons,),
              all(r is not None and "tested head" in r for r in reasons))

        res_hl_only = M.full_status([headless_newer], phase, repo["root"],
                                    ["echo x"])
        check("fs29 RED-FIRST: when the only whole-looking run names no head "
              "the answer is not WHOLE, and its basis says the run was "
              "disqualified for the missing head rather than that git could "
              "not answer: %r" % (res_hl_only,),
              res_hl_only["answer"] == _manifest_vocab.FULL_STATUS_PROVISIONAL
              and res_hl_only["runId"] == "run-headless"
              and "tested head" in res_hl_only["basis"]
              and "could not" not in res_hl_only["basis"]
              and res_hl_only.get("wholeRunId") is None)

        # The other direction: a check that over-fired on every row would
        # turn the WHOLE answers above red; this pins it directly.
        check("fs30 ALLOW: a row that does name its tested head passes the "
              "head rule - no disqualification at all: %r"
              % (M._full_disqualification(headed_older, ["echo x"]),),
              M._full_disqualification(headed_older, ["echo x"]) is None
              and M._full_disqualification(whole_row, ["echo x"]) is None)

        # Two walks, two questions. Whole-bearing needs a head; a MEASURED
        # full run (the selection-miss bound) does not, but every other rule
        # still holds - a dirty head-less run is newer than both and is
        # neither.
        dirty_headless = _fs_row("run-dirty-headless", "2026-01-06T00:00:00Z",
                                 None, ["echo x"], dirty_outside=["src/x.ts"])
        ledger = [headed_older, headless_newer, dirty_headless]
        whole_walk = M.newest_whole_bearing(ledger, ["echo x"])
        measured_walk = M.newest_measured_full_run(ledger, ["echo x"])
        check("fs31 the two walks differ by the head rule alone: the newest "
              "whole-bearing run is the headed one, the newest measured full "
              "run the newer head-less one, and the dirty head-less run is "
              "neither: %r" % ([(b or {}).get("runId")
                                for b in (whole_walk, measured_walk)],),
              (whole_walk or {}).get("runId") == "run-headed"
              and (measured_walk or {}).get("runId") == "run-headless")
        check("fs32 a head-less row passes the measurement rule and fails "
              "only the head rule, which is what makes it measured but not "
              "whole-bearing: %r"
              % ((M._measurement_disqualification(headless_newer, ["echo x"]),
                  M._full_disqualification(headless_newer, ["echo x"])),),
              M._measurement_disqualification(headless_newer, ["echo x"])
              is None
              and "tested head" in (M._full_disqualification(
                  headless_newer, ["echo x"]) or ""))

        # --- reconcile: a full row moves nothing and refuses nothing -----------
        proj = _project(os.path.join(tmp, "recon"),
                        {"manifestPath": "docs/audit/audit-plan.json"})
        manifest_path = os.path.join(proj, "docs", "audit", "audit-plan.json")
        os.makedirs(os.path.dirname(manifest_path))
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump({"meta": {}, "phases": []}, fh)
        M.append_row(proj, whole_row)
        res_recon = M.reconcile(proj, manifest_path)
        check("fs15 a ledger holding only a scope:full row reconciles clean - "
              "`subject_key` gives it no key (no phaseId, no taskId), so it "
              "moves nothing and refuses nothing rather than being chased as "
              "a phase pointer that does not exist: %r" % (res_recon,),
              res_recon["moved"] == [] and res_recon["refused"] == []
              and res_recon["subjects"] == 0)

        # --- _same_subject / reusable_run: a head arm, widen-only --------------
        head1 = _fs_row("run-h1", "2026-01-02T00:00:00Z", "h1", ["echo x"],
                        extra={"reuseKey": "k1"})
        head2 = _fs_row("run-h2", "2026-01-03T00:00:00Z", "h2", ["echo x"],
                        extra={"reuseKey": "k1"})
        phase_scope_row = {"runId": "run-phase", "ts": "2026-01-04T00:00:00Z",
                           "scope": "phase", "status": "passed",
                           "phaseId": "P1", "reuseKey": "k1"}
        reused = M.reusable_run([head1, head2, phase_scope_row], M.FULL_SCOPE,
                                {"head": "h1"}, "k1", ["passed"])
        check("fs16 WIDEN-ONLY: reusable_run over scope:full matches the row "
              "measured at the SAME head and never the other head or a "
              "phase-scope row sharing the same reuseKey: %r"
              % (reused and reused.get("runId"),),
              reused is not None and reused["runId"] == "run-h1")
        check("fs17 ...and the taskId/phaseId loop alone would have called "
              "both full rows the same subject (neither carries either key) - "
              "`_same_subject` needs the head arm for the two to disagree: %r"
              % (M._same_subject(head1, {"head": "h2"}),),
              M._same_subject(head1, {"head": "h1"})
              and not M._same_subject(head1, {"head": "h2"}))
    finally:
        _harness.remove_tree(tmp)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__evidence_io.py --selftest\n")
    raise SystemExit(2)
